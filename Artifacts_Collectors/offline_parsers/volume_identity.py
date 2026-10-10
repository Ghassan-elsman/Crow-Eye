"""
The volume a collected $MFT / $UsnJrnl belongs to.

An offline $MFT carries no drive letter. It used to be stored under a label
made from its file name alone ('OFFLINE', 'OFFLINE_1', ...), so:

  * the C: disk a live parse had already stored as 'C' was stored a second
    time, whole, as 'OFFLINE' when Crow-Claw's copy of the same $MFT was
    imported (3.3 M records twice on one case);
  * two different disks whose copies were both named $MFT shared 'OFFLINE'
    and their records joined by record number.

The label is now the disk's own, found in this order:

  1. Crow-Claw's record of where the copy came from: a chain-of-custody
     record (logs/custody_*.json, or a run's journal under
     logs/custody_parts/) whose raw-disk source is \\\\.\\C:\\$MFT and whose
     copy is this file; or, for a file in Crow-Claw's own MFT / USN folder,
     live_acquisition/collection_manifest.json paths.windows_partition.
     A letter is taken only when the database holds no other disk under it.
  2. A fingerprint of the $MFT - record 0's $STANDARD_INFORMATION times,
     record 3's $Volume name and object id, and the size of the $MFT -
     matched against the volumes already in mft_claw_analysis.db.
  3. 'OFFLINE_<first 8 hex of the SHA-1 of record 0>': a disk of its own,
     never shared with another.

A same-disk import then goes through the normal per-volume re-parse guard
(utils/dedupe_insert.insert_new) and adds only what is new.
"""

import glob
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_collectors = os.path.dirname(_here)
_mft_dir = os.path.join(_collectors, 'MFT and USN journal')
for _p in (_here, _mft_dir, os.path.dirname(_collectors)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# A raw-volume source as Crow-Claw records it: \\.\C:\$MFT (MFT) and
# C:\$Extend\$UsnJrnl:$J (USN journal).
_RAW_SOURCE = re.compile(r'^(?:\\\\[.?]\\)?([A-Za-z]):\\\$(?:MFT\b|Extend\\\$UsnJrnl)', re.I)
_LETTER_LABEL = re.compile(r'^[A-Za-z]:?$')

# The $MFT of one disk grows over time but never by this much between two
# captures; a recovery partition's is a few hundred records against millions.
_SIZE_BAND = 2.0

_custody_cache = {}


# ----------------------------------------------------------------- helpers
def _key(path):
    """A path compared as Windows compares it, without an ADS suffix
    ($UsnJrnl:$J and $UsnJrnl are the same collected file)."""
    p = str(path or "")
    head, tail = os.path.split(p.replace('/', os.sep))
    if ':' in tail:
        tail = tail.split(':', 1)[0]
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.join(head, tail))))


def _letter(value):
    m = re.match(r'^\s*([A-Za-z]):?\\?\s*$', str(value or ""))
    return m.group(1).upper() if m else None


def legacy_label(path):
    """The pre-round-21 label from the file name: 'OFFLINE', 'OFFLINE_<n>'
    for a name-conflict copy ($MFT_1 / $UsnJrnl_$J_1). Last resort only."""
    name = os.path.basename(str(path or ""))
    m = re.search(r"_(\d+)$", name)
    return "OFFLINE_%s" % m.group(1) if m else "OFFLINE"


def _find_case_root(path):
    """The case folder: the parent of the live_acquisition folder the file is in."""
    p = os.path.dirname(os.path.abspath(str(path)))
    while True:
        if os.path.basename(p).lower() == 'live_acquisition':
            return os.path.dirname(p)
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


# ---------------------------------------------------- 1. Crow-Claw's record
def _custody_entries(case_root):
    """(source, method, copy) of every copied source in the case's custody
    records - closed records and the per-process journals of a run."""
    logs = os.path.join(case_root, 'logs')
    files = sorted(glob.glob(os.path.join(logs, 'custody_*.json')), reverse=True)
    files += sorted(glob.glob(os.path.join(logs, 'custody_parts', '*', '*.jsonl')), reverse=True)
    for path in files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        ck = (path, st.st_mtime, st.st_size)
        if ck not in _custody_cache:
            entries = []
            try:
                with open(path, 'rb') as fh:
                    data = fh.read()
                # Only raw-disk reads name a volume; skip records without one
                # (they can be 50 MB of JSON).
                if b'raw_disk' in data and b'"copy"' in data:
                    if path.endswith('.jsonl'):
                        items = []
                        for line in data.splitlines():
                            if b'raw_disk' not in line:
                                continue
                            try:
                                obj = json.loads(line.decode('utf-8'))
                            except ValueError:
                                continue
                            if obj.get('section') == 'sources':
                                items.append(obj.get('item') or {})
                    else:
                        items = json.loads(data.decode('utf-8')).get('sources') or []
                    for s in items:
                        if isinstance(s, dict) and s.get('copy') and s.get('method') == 'raw_disk':
                            entries.append((s.get('source'), s.get('method'), s.get('copy')))
            except (OSError, ValueError, UnicodeDecodeError, AttributeError):
                entries = []
            _custody_cache[ck] = entries
        for e in _custody_cache[ck]:
            yield e


def custody_letter(path, case_root=None):
    """The drive letter Crow-Claw read this copy from, per the custody record."""
    case_root = case_root or _find_case_root(path)
    if not case_root:
        return None
    want = _key(path)
    for source, _method, copy in _custody_entries(case_root):
        if _key(copy) != want:
            continue
        m = _RAW_SOURCE.match(str(source or ""))
        if m:
            return m.group(1).upper()
    return None


def manifest_letter(path, case_root=None):
    """windows_partition of Crow-Claw's collection, for a file in its own
    live_acquisition/MFT or live_acquisition/USN folder (the importer's
    MFT_USN folder sits beside them and holds other disks)."""
    case_root = case_root or _find_case_root(path)
    if not case_root:
        return None
    la = os.path.join(case_root, 'live_acquisition')
    folder = os.path.normcase(os.path.dirname(_key(path)))
    if folder not in (os.path.normcase(os.path.abspath(os.path.join(la, 'MFT'))),
                      os.path.normcase(os.path.abspath(os.path.join(la, 'USN')))):
        return None
    try:
        with open(os.path.join(la, 'collection_manifest.json'), encoding='utf-8') as fh:
            manifest = json.load(fh)
        return _letter((manifest.get('paths') or {}).get('windows_partition'))
    except (OSError, ValueError, AttributeError):
        return None


# ------------------------------------------------------------ 2. fingerprint
class Fingerprint(object):
    """What identifies the disk a $MFT came from."""

    def __init__(self, si=None, volume_name=None, object_id=None, records=None, record0_sha1=None):
        self.si = si                    # (created, modified, accessed, mft_modified) of record 0
        self.volume_name = volume_name  # record 3 $VOLUME_NAME
        self.object_id = object_id      # record 3 $OBJECT_ID
        self.records = records          # $MFT size / record size
        self.record0_sha1 = record0_sha1

    def __repr__(self):
        return "Fingerprint(si=%r, name=%r, oid=%r, records=%r)" % (
            self.si, self.volume_name, self.object_id, self.records)


def _ts(value):
    if value is None or value == "":
        return None
    if hasattr(value, 'year'):
        from utils.time_utils import format_forensic_timestamp
        return format_forensic_timestamp(value) or None
    return str(value)


def fingerprint_file(mft_path):
    """Fingerprint of a $MFT file, read with the MFT parser itself. None when
    record 0 is not a FILE record (not a $MFT, or the start is missing)."""
    try:
        with open(mft_path, 'rb') as fh:
            head = fh.read(4 * 4096)
    except OSError:
        return None
    if len(head) < 1024 or head[:4] not in (b'FILE', b'BAAD'):
        return None
    rec_size = struct.unpack('<I', head[28:32])[0]
    if rec_size not in (1024, 4096):
        rec_size = 1024
    raw0 = head[:rec_size]
    fp = Fingerprint(record0_sha1=hashlib.sha1(raw0).hexdigest())
    try:
        from MFT_Claw import MFTParser, AttributeParserRegistry
        parser = MFTParser.__new__(MFTParser)          # the record parser only: no database
        parser.attr_registry = AttributeParserRegistry()
        r0 = parser._parse_mft_record(0, '', raw0)
        if r0 is not None and r0.standard_info is not None:
            d = r0.standard_info.data or {}
            si = tuple(_ts(d.get(k)) for k in ('created', 'modified', 'accessed', 'mft_modified'))
            fp.si = si if any(si) else None
        if r0 is not None and r0.file_size:
            fp.records = int(r0.file_size) // rec_size
        raw3 = head[3 * rec_size:4 * rec_size]
        if len(raw3) == rec_size:
            r3 = parser._parse_mft_record(3, '', raw3)
            if r3 is not None:
                if r3.volume_name is not None:
                    fp.volume_name = (r3.volume_name.data or {}).get('volume_label', '')
                if r3.object_id is not None:
                    fp.object_id = (r3.object_id.data or {}).get('object_id') or None
    except Exception:
        pass
    return fp


class _Volume(object):
    def __init__(self):
        self.si = set()
        self.names = set()
        self.object_ids = set()
        self.records = None


def _open_ro(db_path):
    try:
        from pathlib import Path
        return sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error:
        return sqlite3.connect(db_path)


def db_volumes(db_path):
    """{volume_letter: _Volume} for every volume in mft_claw_analysis.db -
    read through the (record_number, volume_letter) indexes: records 0 and 3."""
    vols = {}
    if not db_path or not os.path.exists(db_path):
        return vols
    try:
        conn = _open_ro(db_path)
    except sqlite3.Error:
        return vols
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'mft_standard_info' in tables:
            for v, c, m, a, mm in conn.execute(
                    "SELECT volume_letter, created, modified, accessed, mft_modified "
                    "FROM mft_standard_info WHERE record_number = 0"):
                vols.setdefault(v, _Volume()).si.add(tuple(_ts(x) for x in (c, m, a, mm)))
        if 'mft_data_attributes' in tables:
            for v, name, kind in conn.execute(
                    "SELECT volume_letter, attribute_name, data_type FROM mft_data_attributes "
                    "WHERE record_number = 3 AND data_type IN ('VolumeName', 'ObjectID')"):
                vol = vols.setdefault(v, _Volume())
                if kind == 'VolumeName':
                    vol.names.add(name or '')
                elif name:
                    vol.object_ids.add(name)
        if 'mft_records' in tables:
            for v, size in conn.execute(
                    "SELECT volume_letter, file_size FROM mft_records WHERE record_number = 0"):
                if size:
                    vols.setdefault(v, _Volume()).records = int(size) // 1024
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return vols


def matches(fp, vol):
    """True when the $MFT fingerprinted as ``fp`` is the disk stored as ``vol``."""
    if fp is None or not fp.si or not vol.si or fp.si not in vol.si:
        return False
    if fp.volume_name is not None and vol.names and fp.volume_name not in vol.names:
        return False
    if fp.object_id and vol.object_ids and fp.object_id not in vol.object_ids:
        return False
    if fp.records and vol.records:
        lo, hi = sorted((fp.records, vol.records))
        if hi > lo * _SIZE_BAND:
            return False
    return True


def _pick(labels):
    """A drive letter over an OFFLINE* label; then the first by name."""
    letters = sorted(l for l in labels if _LETTER_LABEL.match(str(l or "")))
    return (letters or sorted(labels))[0]


# ----------------------------------------------------------------- resolve
def resolve_volume(mft_path, case_root=None, db_path=None):
    """(label, how) for a $MFT file; how is 'custody', 'manifest',
    'fingerprint', 'new disk' or 'file name'."""
    case_root = case_root or _find_case_root(mft_path)
    fp = fingerprint_file(mft_path)
    vols = db_volumes(db_path)

    for how, finder in (('custody', custody_letter), ('manifest', manifest_letter)):
        letter = finder(mft_path, case_root)
        if not letter:
            continue
        stored = vols.get(letter)
        # Taken unless another disk is already stored under that letter (a
        # collection from another machine, whose C: is not this case's C:).
        if stored is None or fp is None or not stored.si or matches(fp, stored):
            return letter, how
        break

    if fp is not None:
        hits = [label for label, vol in vols.items() if matches(fp, vol)]
        if hits:
            return _pick(hits), 'fingerprint'
        return 'OFFLINE_%s' % fp.record0_sha1[:8].upper(), 'new disk'
    return legacy_label(mft_path), 'file name'


def resolve_volume_label(mft_path, case_root=None, db_path=None):
    """The volume_letter a collected $MFT is stored under (see the module doc)."""
    return resolve_volume(mft_path, case_root, db_path)[0]


def sibling_mft(usn_path):
    """The $MFT collected with this journal: the same name-conflict suffix
    ($UsnJrnl_$J_1 <-> $MFT_1), in the journal's folder (the importer's
    MFT_USN) or Crow-Claw's MFT folder beside it."""
    name = os.path.basename(str(usn_path or "")).split(':', 1)[0]
    m = re.search(r"_(\d+)$", name)
    mft_name = "$MFT_%s" % m.group(1) if m else "$MFT"
    folder = os.path.dirname(os.path.abspath(str(usn_path)))
    parent = os.path.dirname(folder)
    for cand in (os.path.join(folder, mft_name), os.path.join(parent, 'MFT', mft_name),
                 os.path.join(parent, 'MFT_USN', mft_name)):
        if os.path.isfile(cand):
            return cand
    return None


def resolve_usn_volume(usn_path, case_root=None, mft_db_path=None):
    """(label, how) for a collected USN journal - the label its $MFT gets, so
    the correlator pairs them. The journal itself names no disk: its $MFT is
    asked first, then Crow-Claw's record of the journal."""
    case_root = case_root or _find_case_root(usn_path)
    mft = sibling_mft(usn_path)
    if mft:
        label, how = resolve_volume(mft, case_root, mft_db_path)
        return label, 'its $MFT (%s)' % how
    for how, finder in (('custody', custody_letter), ('manifest', manifest_letter)):
        letter = finder(usn_path, case_root)
        if letter:
            return letter, how
    return legacy_label(usn_path), 'file name'


def resolve_usn_volume_label(usn_path, case_root=None, mft_db_path=None):
    return resolve_usn_volume(usn_path, case_root, mft_db_path)[0]
