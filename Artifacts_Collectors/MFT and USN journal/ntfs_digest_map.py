"""The MFT digest map: what each record looked like at the last parse.

A re-parse of the same volume reads every record again (the read is cheap
next to the parse), digests it, and compares the digest with this map - so it
parses only the records that changed, and it can say which ones were deleted
or reused in between. The USN journal is not trusted for this: it can be
deleted, it wraps, it skips last-access updates and it never sees a raw or
offline write.

Two digests per record, both keyed BLAKE2b-128 (hashlib, no new dependency):

* **FULL** - the record's bytes after the update-sequence fixups, over
  ``0..bytes_in_use``, with the LSN (0x08) and the update-sequence array
  zeroed. NTFS rewrites both on every logged write, so hashing the raw bytes
  would call every touched record "changed". Slack after ``bytes_in_use`` is
  out of it too. Computed for every record.
* **SEMANTIC** - only the fields a parse stores or an examiner judges:
  in-use / directory flags, base reference, sequence, link count, the
  $STANDARD_INFORMATION created / modified / MFT-changed times, file attributes,
  owner and security ID, every $FILE_NAME (except its access time), the list
  of attribute types and names, the content of each resident attribute
  ($DATA, $EA, $REPARSE_POINT, $OBJECT_ID, $ATTRIBUTE_LIST ...), and each
  non-resident attribute's logical size. It leaves out the last-access time,
  the SI's USN and quota fields, run lists and slack - so an access-time
  flush, a defrag or a TRIM is "FULL changed, SEMANTIC not": noise, not a
  change. Computed only where FULL changed.

The map is a flat file indexed by record number (48 bytes a record: FULL,
SEMANTIC, LSN, sequence, update-sequence counter, flags, link count), with one
digest per block of 64 records - a block whose digest matches is skipped
without looking at its records. A Merkle root over the block digests stands
for the whole volume in the integrity manifest. The file is sealed with an
HMAC whose key is held by DPAPI for the Windows user (a key file in the case
folder only where DPAPI is not available, and the manifest says which). A map
whose seal does not check is never used: the parse falls back to a full
parse and says why (``map_tamper``).

Plainly stated: anyone running as the same user - or as SYSTEM - can recompute
the seal. It catches a map edited by someone who does not hold the key, and an
accident; it is not a trust anchor on its own. Sentinel's server-held chain is.
"""

import hashlib
import hmac
import json
import logging
import os
import struct
import tempfile
import time

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
MAGIC = b'CEMFTMAP'
BLOCK = 64
DIGEST_SIZE = 16
SEAL_SIZE = 32

# full, semantic, lsn, sequence, update-sequence counter, flags, link count
ENTRY = struct.Struct('<16s16sQHHHH')
ENTRY_SIZE = ENTRY.size            # 48

F_PRESENT = 0x0001        # a FILE or BAAD record (not a zeroed / never-used slot)
F_IN_USE = 0x0002
F_FIXUP_OK = 0x0004
F_BAAD = 0x0008
F_BASE = 0x0010           # no base-record reference (not an extension record)
F_SEMANTIC = 0x0020       # the SEMANTIC digest was computed for this entry
F_DIRECTORY = 0x0040

ZERO_DIGEST = b'\0' * DIGEST_SIZE

ATTR_SI = 0x10
ATTR_ATTRIBUTE_LIST = 0x20
ATTR_FILE_NAME = 0x30
ATTR_OBJECT_ID = 0x40
ATTR_DATA = 0x80
ATTR_INDEX_ROOT = 0x90
ATTR_INDEX_ALLOCATION = 0xA0
ATTR_BITMAP = 0xB0
END_MARKER = 0xFFFFFFFF

# Resident attributes whose CONTENT is not semantic: a directory's small index
# and its bitmap change whenever a child is added or removed, and the parse
# stores neither. Their presence (type and name) still is.
_CONTENT_NOT_SEMANTIC = (ATTR_INDEX_ROOT, ATTR_BITMAP)


# --------------------------------------------------------------- the record --
def record_header(raw: bytes) -> dict:
    """The FILE header fields the map and the checks use. Offsets per
    libfsntfs / the Linux ntfs driver: 0x04 USA offset, 0x06 USA count,
    0x08 LSN, 0x10 sequence, 0x12 link count, 0x14 first attribute,
    0x16 flags, 0x18 bytes in use, 0x1C bytes allocated, 0x20 base reference."""
    sig = bytes(raw[:4])
    h = {'signature': sig, 'present': sig in (b'FILE', b'BAAD'), 'baad': sig == b'BAAD'}
    if not h['present'] or len(raw) < 0x30:
        h['present'] = False
        return h
    (usa_off, usa_count, lsn, seq, links, attr_off, flags, in_use_bytes,
     alloc_bytes, base_ref) = struct.unpack_from('<HHQHHHHIIQ', raw, 0x04)
    h.update({'usa_offset': usa_off, 'usa_count': usa_count, 'lsn': lsn, 'sequence': seq,
              'links': links, 'attr_offset': attr_off, 'flags': flags,
              'in_use': bool(flags & 0x0001), 'directory': bool(flags & 0x0002),
              'bytes_in_use': in_use_bytes, 'bytes_allocated': alloc_bytes,
              'base_ref': base_ref, 'base_record': base_ref & 0xFFFFFFFFFFFF,
              'usa_value': (struct.unpack_from('<H', raw, usa_off)[0]
                            if usa_off + 2 <= len(raw) else 0)})
    return h


def full_digest(fixed: bytes, header: dict, key: bytes) -> bytes:
    """FULL: fixed-up bytes over 0..bytes_in_use, LSN and USA zeroed."""
    n = header.get('bytes_in_use') or len(fixed)
    n = max(0x30, min(n, len(fixed)))
    buf = bytearray(fixed[:n])
    buf[0x08:0x10] = b'\0' * 8
    usa_off, usa_count = header.get('usa_offset', 0), header.get('usa_count', 0)
    if usa_off and usa_count:
        end = min(n, usa_off + 2 * usa_count)
        if usa_off < end:
            buf[usa_off:end] = b'\0' * (end - usa_off)
    return hashlib.blake2b(bytes(buf), digest_size=DIGEST_SIZE, key=key).digest()


def walk(fixed: bytes, header: dict) -> dict:
    """Every attribute of one fixed-up record, as the facts the checks read
    and the parts the SEMANTIC digest is taken over.

    Never raises: a malformed attribute ends the walk and sets ``truncated``.
    """
    facts = {'attr_types': [], 'si': None, 'fns': [], 'has_attribute_list': False,
             'object_id': None, 'truncated': False, 'parts': []}
    parts = facts['parts']
    parts.append(struct.pack('<HQHH', header.get('flags', 0) & 0xFFFF,
                             header.get('base_ref', 0), header.get('sequence', 0),
                             header.get('links', 0)))
    off = header.get('attr_offset') or 0
    end = min(len(fixed), max(0x30, header.get('bytes_in_use') or len(fixed)))
    guard = 0
    while off + 16 <= end and guard < 512:
        guard += 1
        a_type, a_len = struct.unpack_from('<II', fixed, off)
        if a_type == END_MARKER:
            break
        if a_len < 16 or off + a_len > len(fixed):
            facts['truncated'] = True
            break
        non_res = fixed[off + 8]
        name_len = fixed[off + 9]
        name_off = struct.unpack_from('<H', fixed, off + 10)[0]
        name = bytes(fixed[off + name_off:off + name_off + 2 * name_len]) if name_len else b''
        facts['attr_types'].append(a_type)
        parts.append(struct.pack('<IB', a_type, non_res) + name)
        if a_type == ATTR_ATTRIBUTE_LIST:
            # Resident or not: a large list (many hard links) is non-resident,
            # and the names then sit in extension records.
            facts['has_attribute_list'] = True
        if non_res:
            if off + 0x38 <= len(fixed):
                data_size = struct.unpack_from('<Q', fixed, off + 0x30)[0]
                first_vcn = struct.unpack_from('<Q', fixed, off + 0x10)[0]
                parts.append(struct.pack('<QQ', first_vcn, data_size))
                if a_type == ATTR_DATA and not name and first_vcn == 0:
                    facts['data_size'] = data_size
            off += a_len
            continue
        v_len, v_off = struct.unpack_from('<IH', fixed, off + 0x10)
        content = bytes(fixed[off + v_off:off + v_off + v_len])
        if a_type == ATTR_SI and len(content) >= 48:
            si = {'created': struct.unpack_from('<Q', content, 0)[0],
                  'modified': struct.unpack_from('<Q', content, 8)[0],
                  'mft_modified': struct.unpack_from('<Q', content, 16)[0],
                  'accessed': struct.unpack_from('<Q', content, 24)[0],
                  'file_attributes': struct.unpack_from('<I', content, 32)[0]}
            if len(content) >= 72:
                si['owner_id'], si['security_id'] = struct.unpack_from('<II', content, 48)
            facts['si'] = si
            # Not the access time (0x18), quota (0x38) or USN (0x40).
            parts.append(content[0:24] + content[32:56])
        elif a_type == ATTR_FILE_NAME and len(content) >= 66:
            n_len, ns = content[64], content[65]
            fn = {'parent_ref': struct.unpack_from('<Q', content, 0)[0],
                  'created': struct.unpack_from('<Q', content, 8)[0],
                  'modified': struct.unpack_from('<Q', content, 16)[0],
                  'mft_modified': struct.unpack_from('<Q', content, 24)[0],
                  'accessed': struct.unpack_from('<Q', content, 32)[0],
                  'namespace': ns,
                  'name': content[66:66 + 2 * n_len].decode('utf-16le', 'replace')}
            facts['fns'].append(fn)
            # Not the access time (0x20).
            parts.append(content[0:32] + content[40:66 + 2 * n_len])
        elif a_type in _CONTENT_NOT_SEMANTIC:
            pass
        else:
            if a_type == ATTR_ATTRIBUTE_LIST:
                facts['has_attribute_list'] = True
            elif a_type == ATTR_OBJECT_ID and len(content) >= 16:
                facts['object_id'] = content[:16]
            elif a_type == ATTR_DATA and not name:
                facts['data_size'] = len(content)
            parts.append(content)
        off += a_len
    return facts


def semantic_digest(parts, key: bytes) -> bytes:
    """SEMANTIC over the parts walk() collected, each length-prefixed so two
    different splits of the same bytes never digest alike."""
    h = hashlib.blake2b(digest_size=DIGEST_SIZE, key=key)
    for p in parts:
        h.update(struct.pack('<I', len(p)))
        h.update(p)
    return h.digest()


# ------------------------------------------------------------------- keys --
_KEY_FILE = 'ntfs_integrity_key.dpapi'
_CASE_KEY_FILE = 'ntfs_integrity.key'


def _dpapi_protect(data: bytes) -> bytes:
    import win32crypt                                    # pywin32
    return win32crypt.CryptProtectData(data, 'Crow-Eye NTFS integrity map key',
                                       None, None, None, 0)


def _dpapi_unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]


def _config_dir():
    try:
        from config.case_history_manager import default_config_dir
        return default_config_dir()
    except Exception:                                    # noqa: BLE001
        appdata = os.getenv('APPDATA')
        return os.path.join(appdata, 'CrowEye', 'config') if appdata else None


def load_key(case_dir=None):
    """The map's secret: (key, where it is held).

    Held by DPAPI for the Windows user, in Crow-Eye's per-user config folder,
    and created there on first use. Where DPAPI is not available (not
    Windows, no pywin32) a key file in ``<case>/state`` is used instead - and
    ``store`` says so, because a key next to the map protects it only from
    accidents."""
    folder = _config_dir()
    if folder:
        path = os.path.join(folder, _KEY_FILE)
        try:
            if os.path.isfile(path):
                with open(path, 'rb') as fh:
                    return _dpapi_unprotect(fh.read()), 'dpapi'
            key = os.urandom(32)
            blob = _dpapi_protect(key)
            os.makedirs(folder, exist_ok=True)
            with open(path, 'wb') as fh:
                fh.write(blob)
            return key, 'dpapi'
        except Exception as e:                           # noqa: BLE001
            logger.info("DPAPI key unavailable (%s); using a key file in the case folder", e)
    if not case_dir:
        raise RuntimeError("no DPAPI and no case folder for the integrity map key")
    state = os.path.join(case_dir, 'state')
    os.makedirs(state, exist_ok=True)
    path = os.path.join(state, _CASE_KEY_FILE)
    if os.path.isfile(path):
        with open(path, 'rb') as fh:
            return fh.read(), 'case_file'
    key = os.urandom(32)
    with open(path, 'wb') as fh:
        fh.write(key)
    return key, 'case_file'


class Keys:
    """The three keys derived from the secret: FULL digests, SEMANTIC digests
    and the map's seal. One secret, separate keys, so a digest can never be
    passed off as a seal."""

    def __init__(self, secret: bytes, store: str = 'given'):
        self.store = store
        self.full = hmac.new(secret, b'crow-eye mft full digest v1', hashlib.sha256).digest()
        self.semantic = hmac.new(secret, b'crow-eye mft semantic digest v1', hashlib.sha256).digest()
        self.seal = hmac.new(secret, b'crow-eye mft map seal v1', hashlib.sha256).digest()
        self.block = hmac.new(secret, b'crow-eye mft block digest v1', hashlib.sha256).digest()
        self.fingerprint = hashlib.sha256(b'fingerprint' + secret).hexdigest()[:16]


# -------------------------------------------------------------------- map --
class DigestMap:
    """One volume's entries, indexed by record number, plus block digests."""

    def __init__(self, record_count: int, header: dict = None, entries=None, blocks=None):
        self.record_count = int(record_count)
        self.header = dict(header or {})
        self.entries = entries if entries is not None else bytearray(ENTRY_SIZE * self.record_count)
        nblocks = (self.record_count + BLOCK - 1) // BLOCK
        self.blocks = blocks if blocks is not None else bytearray(DIGEST_SIZE * nblocks)

    # entries
    def set(self, i, full, semantic, lsn, seq, usa, flags, links):
        if 0 <= i < self.record_count:
            ENTRY.pack_into(self.entries, i * ENTRY_SIZE, full, semantic, lsn & 0xFFFFFFFFFFFFFFFF,
                            seq & 0xFFFF, usa & 0xFFFF, flags & 0xFFFF, links & 0xFFFF)

    def get(self, i):
        """(full, semantic, lsn, seq, usa, flags, links) or None past the end."""
        if 0 <= i < self.record_count:
            return ENTRY.unpack_from(self.entries, i * ENTRY_SIZE)
        return None

    def full_of(self, i):
        if 0 <= i < self.record_count:
            o = i * ENTRY_SIZE
            return bytes(self.entries[o:o + DIGEST_SIZE])
        return None

    # blocks
    def block_digest(self, b):
        o = b * DIGEST_SIZE
        if 0 <= o < len(self.blocks):
            return bytes(self.blocks[o:o + DIGEST_SIZE])
        return None

    def set_block(self, b, digest):
        o = b * DIGEST_SIZE
        if 0 <= o < len(self.blocks):
            self.blocks[o:o + DIGEST_SIZE] = digest

    def merkle_root(self) -> str:
        return merkle_root([bytes(self.blocks[o:o + DIGEST_SIZE])
                            for o in range(0, len(self.blocks), DIGEST_SIZE)])

    def in_use_flags(self):
        """Per record: True / False for a FILE record's in-use flag, None for a
        slot that holds no record."""
        out = []
        for i in range(self.record_count):
            flags = struct.unpack_from('<H', self.entries, i * ENTRY_SIZE + 44)[0]
            out.append(bool(flags & F_IN_USE) if flags & F_PRESENT else None)
        return out

    # file
    def save(self, path: str, keys: 'Keys'):
        """Write atomically (a temp file renamed over the old one), sealed."""
        head = dict(self.header)
        head.update({'format_version': FORMAT_VERSION, 'record_count': self.record_count,
                     'entry_size': ENTRY_SIZE, 'block': BLOCK,
                     'key_fingerprint': keys.fingerprint, 'key_store': keys.store,
                     'merkle_root': self.merkle_root(),
                     'saved_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        hj = json.dumps(head, sort_keys=True, default=str).encode('utf-8')
        mac = hmac.new(keys.seal, digestmod=hashlib.sha256)
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.ntfs_map_', suffix='.tmp', dir=folder)
        try:
            with os.fdopen(fd, 'wb') as fh:
                for part in (MAGIC, struct.pack('<I', len(hj)), hj,
                             bytes(self.entries), bytes(self.blocks)):
                    mac.update(part)
                    fh.write(part)
                fh.write(mac.digest())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self.header = head
        return head

    @classmethod
    def load(cls, path: str, keys: 'Keys'):
        """(map, None) when the file is there and its seal checks;
        (None, reason) otherwise. Reasons: no_map, map_unreadable,
        map_key_unavailable (sealed with another user's key), map_tamper."""
        if not os.path.isfile(path):
            return None, 'no_map'
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError:
            return None, 'map_unreadable'
        if len(data) < len(MAGIC) + 4 + SEAL_SIZE or data[:len(MAGIC)] != MAGIC:
            return None, 'map_tamper'
        hlen = struct.unpack_from('<I', data, len(MAGIC))[0]
        body_end = len(data) - SEAL_SIZE
        hstart = len(MAGIC) + 4
        if hstart + hlen > body_end:
            return None, 'map_tamper'
        try:
            head = json.loads(data[hstart:hstart + hlen].decode('utf-8'))
        except ValueError:
            return None, 'map_tamper'
        if head.get('key_fingerprint') and head.get('key_fingerprint') != keys.fingerprint:
            return None, 'map_key_unavailable'
        mac = hmac.new(keys.seal, data[:body_end], hashlib.sha256).digest()
        if not hmac.compare_digest(mac, data[body_end:]):
            return None, 'map_tamper'
        n = int(head.get('record_count') or 0)
        ent_end = hstart + hlen + n * ENTRY_SIZE
        nblocks = (n + BLOCK - 1) // BLOCK
        if head.get('entry_size') != ENTRY_SIZE or ent_end + nblocks * DIGEST_SIZE != body_end:
            return None, 'map_tamper'
        entries = bytearray(data[hstart + hlen:ent_end])
        blocks = bytearray(data[ent_end:body_end])
        return cls(n, head, entries, blocks), None


def block_digest(fulls, key: bytes) -> bytes:
    """One block's digest over its records' FULL digests (in order)."""
    return hashlib.blake2b(b''.join(fulls), digest_size=DIGEST_SIZE, key=key[:64]).digest()


def merkle_root(leaves) -> str:
    """Binary Merkle tree over the block digests; an odd node is carried up.
    Leaves and nodes are domain-separated (0x00 / 0x01)."""
    level = [hashlib.blake2b(b'\x00' + leaf, digest_size=DIGEST_SIZE).digest() for leaf in leaves]
    if not level:
        return hashlib.blake2b(b'', digest_size=DIGEST_SIZE).hexdigest()
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(hashlib.blake2b(b'\x01' + level[i] + level[i + 1],
                                       digest_size=DIGEST_SIZE).digest())
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0].hex()


def chain_value(prev_chain: str, root: str, manifest: dict) -> str:
    """chain = H(prev || root || manifest), the manifest without its own chain."""
    body = {k: v for k, v in manifest.items() if k != 'chain'}
    h = hashlib.sha256()
    h.update(bytes.fromhex(prev_chain) if prev_chain else b'\0' * 32)
    h.update(bytes.fromhex(root) if root else b'')
    h.update(json.dumps(body, sort_keys=True, default=str).encode('utf-8'))
    return h.hexdigest()


def runlist_hash(runs) -> str:
    """The $MFT's own runlist as one value: where the table lives on disk."""
    h = hashlib.blake2b(digest_size=DIGEST_SIZE)
    for first_vcn, lcn, count in runs or []:
        h.update(struct.pack('<qqq', int(first_vcn), -1 if lcn is None else int(lcn), int(count)))
    return h.hexdigest()


def map_id(identity: dict) -> str:
    """The map file's name part: a hash of what identifies the volume and is
    stable across parses (serial, $Volume object ID, source kind, label).
    The runlist hash is NOT in it: a grown $MFT keeps its map, and a runlist
    change with an unchanged record count is a full-parse reason, not a new
    map."""
    parts = [str(identity.get(k) or '') for k in ('source', 'serial', 'volume_object_id', 'label')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:16]


def map_path(case_dir: str, identity: dict) -> str:
    return os.path.join(case_dir, 'state', 'ntfs_map_%s.bin' % map_id(identity))
