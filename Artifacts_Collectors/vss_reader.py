"""
Crow-Eye's own reader of Volume Shadow Copies: an NTFS volume's VSS catalog and stores, and each
shadow copy rebuilt as a readable volume - from a live volume, a raw device or a forensic image.

Why not a library. dissect.volume's reader (a port of libvshadow's ideas) zeroes blocks that are in
use on Windows 10/11, so no file system opens; it refuses a whole catalog when one store has only
one of its two catalog entries; it expands each store bitmap into a Python list of every block (some
60 million items on a 1 TB volume); and it prints debugging text. Everything here is checked against
Windows itself: on a live machine each copy Windows exposes has its own device, and
`verify_against_device` compares this reader's blocks with the device's, block by block.

The format (libvshadow's documentation, and the measurements in correlation_engine/tests/test_vss_reader.py):

    volume header   at 0x1E00: VSS id, version, catalog offset, maximum size
    catalog         16 KiB blocks chained by next_offset, 128-byte header, 128-byte entries:
                      0x01 unused; 0x02 a copy (volume size, store id, creation FILETIME);
                      0x03 its store (block list, store header, range list, bitmaps, the store
                      file's MFT reference)
    store header    record type 4, then the store information: copy id, copy set id, context,
                    provider, attribute flags, originating and service machine
    block list      record type 3 blocks chained by next_offset, 32-byte descriptors:
                      original offset (the volume block preserved), relative offset, store offset
                      (where the old bytes are), flags (1 forwarder, 2 overlay, 4 not used),
                      allocation bitmap (an overlay's 512-byte sectors)
    range list      record type 5: (store offset, relative offset, size) - where the store's
                    data sits on the volume, which is the copy's own footprint
    bitmaps         record type 6: one bit per 16 KiB block of the volume, current and previous

Reading a block of copy N: the stores are applied newest first over the volume, so the first store
from N forward that holds the block wins. A forwarder sends the read to another block of the next
store (or of the volume); an overlay lays its sectors over what lies beneath; a block no store
holds is the volume's. A block that was free when the copy was made was never preserved: the
volume's bytes there are today's, and `FREE_AS` chooses whether such blocks read as the volume or
as zeros (measured: see VALIDATION).
"""
from __future__ import annotations

import collections
import datetime
import io
import struct
import uuid
from typing import BinaryIO, Dict, List, Optional, Tuple

VSS_ID = bytes.fromhex("6b87083876c1484eb7ae04046e6cc752")
HEADER_OFFSET = 0x1E00
BLOCK = 0x4000                      # copy-on-write unit, catalog and store block size
REC_HEADER, REC_CATALOG, REC_INDEX, REC_STORE_HEADER, REC_RANGE, REC_BITMAP = 1, 2, 3, 4, 5, 6
F_FORWARDER, F_OVERLAY, F_NOT_USED = 0x1, 0x2, 0x4

ATTRIBUTES = {
    0x00000001: "persistent", 0x00000002: "no autorecovery", 0x00000004: "client accessible",
    0x00000008: "no auto release", 0x00000010: "no writers", 0x00000020: "transportable",
    0x00000040: "not surfaced", 0x00000080: "not transacted", 0x00010000: "hardware assisted",
    0x00020000: "differential", 0x00040000: "plex", 0x00080000: "imported",
    0x00100000: "exposed locally", 0x00200000: "exposed remotely", 0x00400000: "autorecover",
    0x00800000: "rollback recovery", 0x01000000: "delayed postsnapshot", 0x02000000: "TxF recovery",
}

# How a block that no store holds reads.
#
# "windows" (the default) is what Windows' own devices return, measured block by block against
# four exposed copies (VALIDATION). Such a block is the volume's - except a block that BOTH the
# copy's current and previous bitmaps mark: free when the copy was made, so never preserved.
# Windows hands those out as the volume only for an older copy made without writers (attribute
# "no writers", 0x10: the kind System Restore makes). For a copy made with writers (store 1 here:
# "autorecover", Windows Update) the device returns zeros, and for the NEWEST copy it returns an
# uninitialised kernel buffer (pointer patterns, not the volume's bytes). This reader returns zeros
# for both: the honest answer for a block the copy never kept (`Store.unpreserved`).
#
# "volume" never zero-fills; "zero" zero-fills every block the current bitmap marks, for carving
# work where today's bytes in yesterday's free space would mislead.
FREE_AS = "windows"
ATTR_NO_WRITERS = 0x00000010

VALIDATION = ("2026-10-30, Windows 11 24H2, 4 exposed copies (2 older 'no writers', 1 with writers, the "
              "newest), 5,700 sampled blocks each (own descriptors, later stores', bitmap set and clear, "
              "random) compared with each copy's own device: overlays applied for the copy read only "
              "('active'; 'chain' broke 114 blocks of one copy); free blocks by the rule above (the "
              "'differential' attribute was tried and broke 763 and 737 blocks of the two older copies). "
              "The newest copy's unpreserved blocks are uninitialised on the device and are counted "
              "apart. verify_against_device() repeats the measurement.")


class VssError(Exception):
    pass


def _guid(b: bytes) -> str:
    return "{%s}" % str(uuid.UUID(bytes_le=bytes(b))).upper()


def _filetime(ft: int) -> Optional[str]:
    if not ft:
        return None
    try:
        return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError):
        return None


class _Reader:
    """Positioned reads on any seekable binary file (a raw volume, a device, an image stream)."""

    def __init__(self, fh: BinaryIO):
        self.fh = fh

    def read(self, offset: int, length: int) -> bytes:
        self.fh.seek(offset)
        data = self.fh.read(length)
        if len(data) < length:
            data += b"\0" * (length - len(data))
        return data


def _chain(rd: _Reader, offset: int, record_type: int, limit: int = 1 << 20) -> List[Tuple[int, bytes]]:
    """Every block of a record chain: [(block offset, block bytes)]. Stops on a loop, a foreign
    block or a wrong record type, so a damaged store yields what is readable and no more."""
    out, seen = [], set()
    while offset and offset not in seen and len(out) < limit:
        seen.add(offset)
        blk = rd.read(offset, BLOCK)
        if blk[:16] != VSS_ID:
            break
        rtype, = struct.unpack_from("<I", blk, 20)
        if rtype != record_type:
            break
        out.append((offset, blk))
        offset, = struct.unpack_from("<Q", blk, 40)
    return out


class Descriptor:
    __slots__ = ("original", "relative", "store", "flags", "bitmap", "overlay")

    def __init__(self, original, relative, store_off, flags, bitmap):
        self.original, self.relative, self.store, self.flags, self.bitmap = original, relative, store_off, flags, bitmap
        self.overlay = None

    @property
    def forwarder(self):
        return bool(self.flags & F_FORWARDER)

    @property
    def is_overlay(self):
        return bool(self.flags & F_OVERLAY)

    def __repr__(self):
        return "<Descriptor orig=%#x rel=%#x store=%#x flags=%#x bitmap=%#x>" % (
            self.original, self.relative, self.store, self.flags, self.bitmap)


class Store:
    """One shadow copy: its catalog entries, store information, and how to read it."""

    def __init__(self, volume: "VssVolume", entry2: Optional[dict], entry3: Optional[dict]):
        self.volume = volume
        self.entry2, self.entry3 = entry2 or {}, entry3 or {}
        self.store_id = (entry2 or entry3)["store_id"]
        self.created = self.entry2.get("created")
        self.volume_size = self.entry2.get("volume_size") or volume.size
        self.index = None
        self.next = self.previous = None           # the readable stores either side, by creation
        self.copy_id = self.set_id = self.unknown_id = None
        self.context = self.provider = self.attributes = self.information_reserved = None
        self.originating_machine = self.service_machine = ""
        self.store_header: Dict[str, int] = {}
        self.problems: List[str] = []
        self._map = None
        self._reverse = None
        self._bitmap = None
        self._prev_bitmap = None
        if not entry3:
            self.problems.append("the catalog holds this copy but no store for it")
        else:
            self._read_information()

    # ---- metadata -------------------------------------------------------------------------
    def _read_information(self):
        off = self.entry3.get("store_header")
        if not off:
            self.problems.append("no store header offset")
            return
        blk = self.volume.rd.read(off, BLOCK)
        if blk[:16] != VSS_ID or struct.unpack_from("<I", blk, 20)[0] != REC_STORE_HEADER:
            self.problems.append("the store header is not where the catalog says")
            return
        version, rtype, rel, offset, nxt, size = struct.unpack_from("<IIQQQQ", blk, 16)
        self.store_header = {"version": version, "record_type": rtype, "relative_offset": rel,
                             "offset": offset, "next_offset": nxt, "size": size}
        info = blk[128:]
        self.unknown_id = _guid(info[0:16])
        self.copy_id = _guid(info[16:32])
        self.set_id = _guid(info[32:48])
        self.context, self.provider, self.attributes, self.information_reserved = struct.unpack_from(
            "<IIII", info, 48)
        pos = 64
        n, = struct.unpack_from("<H", info, pos)
        self.originating_machine = info[pos + 2:pos + 2 + n].decode("utf-16-le", "replace")
        pos += 2 + n
        n, = struct.unpack_from("<H", info, pos)
        self.service_machine = info[pos + 2:pos + 2 + n].decode("utf-16-le", "replace")

    @property
    def creation_time(self) -> int:
        """The copy's creation time as the catalog stores it (FILETIME); `created` is the UTC text."""
        return self.entry2.get("created_ft") or 0

    def attribute_names(self) -> List[str]:
        a = self.attributes or 0
        return [name for bit, name in sorted(ATTRIBUTES.items()) if a & bit]

    @property
    def readable(self) -> bool:
        return bool(self.entry3) and self.copy_id is not None

    # ---- the block map ----------------------------------------------------------------------
    def _load_map(self):
        """The descriptors, folded as the format requires: a forwarder whose target another
        descriptor already moved is re-pointed; overlays on the same block merge their sector
        bitmaps; a later full descriptor keeps an earlier overlay beneath it."""
        if self._map is not None:
            return
        blockmap, reverse = {}, {}
        for _off, blk in _chain(self.volume.rd, self.entry3.get("block_list", 0), REC_INDEX):
            for p in range(128, BLOCK, 32):
                original, relative, store_off, flags, bitmap = struct.unpack_from("<QQQII", blk, p)
                if not (original or relative or store_off or flags):
                    break
                if flags & F_NOT_USED:
                    continue
                d = Descriptor(original, relative, store_off, flags, bitmap)
                key = d.original // BLOCK
                if not d.is_overlay:
                    prior = reverse.pop(d.relative // BLOCK, None)
                    if prior is not None:
                        d.original = prior.relative
                if d.forwarder and d.original == d.relative:
                    continue
                existing = blockmap.get(key)
                if existing is not None:
                    if d.is_overlay:
                        ov = existing if existing.is_overlay else existing.overlay
                        if ov is not None:
                            ov.bitmap |= d.bitmap
                        else:
                            existing.overlay = d
                        continue
                    d.overlay = existing if existing.is_overlay else existing.overlay
                blockmap[key] = d
                if d.forwarder:
                    reverse[d.relative // BLOCK] = d
        self._map, self._reverse = blockmap, reverse

    def descriptors(self) -> Dict[int, Descriptor]:
        self._load_map()
        return self._map

    def _bitmap_bytes(self, previous=False) -> Optional[bytes]:
        attr = "_prev_bitmap" if previous else "_bitmap"
        if getattr(self, attr) is None:
            off = self.entry3.get("previous_bitmap" if previous else "bitmap", 0)
            data = b"".join(blk[128:] for _o, blk in _chain(self.volume.rd, off, REC_BITMAP)) if off else b""
            setattr(self, attr, data)
        return getattr(self, attr) or None

    def unpreserved(self, block: int) -> bool:
        """True when Windows keeps no data for this block in this copy: both bitmaps mark it free
        and the copy is the newest or was made with writers (see FREE_AS)."""
        if not (self.bitmap_bit(block) and self.bitmap_bit(block, previous=True) is not False):
            return False
        return self.next is None or not (self.attributes or 0) & ATTR_NO_WRITERS

    def bitmap_bit(self, block: int, previous=False) -> Optional[bool]:
        """The store bitmap's bit for one volume block (None when there is no bitmap)."""
        data = self._bitmap_bytes(previous)
        if not data or block // 8 >= len(data):
            return None
        return bool(data[block // 8] & (1 << (block % 8)))

    def in_use(self, block: int, previous=False) -> Optional[bool]:
        """Whether the volume used this block when the copy was made: a set bitmap bit means free."""
        bit = self.bitmap_bit(block, previous)
        return None if bit is None else not bit

    def free_blocks(self, previous=False):
        """Every block the bitmap marks free when the copy was made, ascending, without expanding
        the bitmap into a list (a 1 TB volume has some 60 million blocks)."""
        data = self._bitmap_bytes(previous) or b""
        for i, byte in enumerate(data):
            if byte:
                for bit in range(8):
                    if byte & (1 << bit):
                        yield i * 8 + bit

    def forwarded_to(self, block: int) -> bool:
        """True when a forwarder of this store points at `block` (the format's reverse map)."""
        self._load_map()
        return block in self._reverse

    # ---- footprint ----------------------------------------------------------------------------
    def range_entries(self) -> List[dict]:
        """The range list as stored: {store_offset, relative_offset, size} per range."""
        out = []
        for _off, blk in _chain(self.volume.rd, self.entry3.get("range_list", 0), REC_RANGE):
            for p in range(128, BLOCK - 23, 24):
                store_off, relative, size = struct.unpack_from("<QQQ", blk, p)
                if not (store_off or relative or size):
                    break
                out.append({"store_offset": store_off, "relative_offset": relative, "size": size})
        return out

    def ranges(self) -> List[Tuple[int, int]]:
        """Where this store's data sits on the volume: [(offset, length)], from its range list."""
        return [(r["store_offset"], r["size"]) for r in self.range_entries()]

    def footprint(self) -> int:
        """The bytes this copy's store holds on the volume: its ranges, or its block count."""
        r = self.ranges()
        if r:
            return sum(n for _o, n in r)
        return len(self.descriptors()) * BLOCK

    # ---- reading ------------------------------------------------------------------------------
    def read_block(self, block: int, active: Optional["Store"] = None) -> bytes:
        """Block `block` of the volume as this copy (or, called down the chain, `active`) saw it."""
        active = active or self
        self._load_map()
        rd = self.volume.rd
        d = self._map.get(block)
        data = None
        if d is not None and not d.is_overlay:
            if d.forwarder:
                target = d.relative // BLOCK
                data = self.next.read_block(target, active) if self.next is not None else rd.read(d.relative, BLOCK)
            else:
                data = rd.read(d.store, BLOCK)
        if data is None:
            if self.next is not None:
                data = self.next.read_block(block, active)
            elif block in self._reverse:
                # A forwarder of the last store points here: the block was moved, not freed, so it
                # is the volume's whatever the bitmaps say (libvshadow's reverse-map rule).
                data = rd.read(block * BLOCK, BLOCK)
            else:
                data = self.volume.base_block(block, active)
        ov = d if (d is not None and d.is_overlay) else (d.overlay if d is not None else None)
        if ov is not None and (self.volume.overlays == "chain" or active is self):
            buf = bytearray(data)
            for i in range(32):
                if (ov.bitmap >> i) & 1:
                    buf[i * 512:(i + 1) * 512] = rd.read(ov.store + i * 512, 512)
            data = bytes(buf)
        return data

    def open(self) -> "SnapshotStream":
        if not self.readable:
            raise VssError("shadow copy %s cannot be read: %s" % (self.copy_id or self.store_id,
                                                                  "; ".join(self.problems) or "no store"))
        return SnapshotStream(self)

    def describe(self) -> dict:
        return {"index": self.index, "store_id": self.store_id, "copy_id": self.copy_id, "set_id": self.set_id,
                "created": self.created, "volume_size": self.volume_size, "context": self.context,
                "provider": self.provider, "attributes": self.attribute_names(),
                "originating_machine": self.originating_machine, "service_machine": self.service_machine,
                "store_file_record": (self.entry3.get("file_ref") or 0) & 0xFFFFFFFFFFFF or None,
                "readable": self.readable, "problems": list(self.problems)}

    def __repr__(self):
        return "<Store %s copy=%s created=%s>" % (self.index, self.copy_id, self.created)


class VssVolume:
    """The VSS structures of one NTFS volume."""

    def __init__(self, fh: BinaryIO, size: Optional[int] = None, overlays: str = "active",
                 free_as: str = None, cache_blocks: int = 512):
        self.rd = _Reader(fh)
        self.fh = fh
        self.overlays = overlays
        self.free_as = free_as or FREE_AS
        self.size = size or getattr(fh, "size", None) or 0
        head = self.rd.read(HEADER_OFFSET, 512)
        if head[:16] != VSS_ID:
            raise VssError("no VSS volume header at 0x1E00: the volume has no shadow copies")
        self.version, self.record_type, self.current_offset = struct.unpack_from("<IIQ", head, 16)
        self.catalog_offset, self.maximum_size = struct.unpack_from("<QQ", head, 48)
        self.volume_id = _guid(head[64:80])
        self.store_volume_id = _guid(head[80:96])
        self.stores: List[Store] = []
        self.catalog_blocks: List[int] = []
        self.catalog_entries: List[dict] = []      # every entry in catalog order: {type, offset, ...}
        self.problems: List[str] = []
        self._cache = collections.OrderedDict()
        self._cache_max = cache_blocks
        if self.catalog_offset:
            self._read_catalog()

    def _read_catalog(self):
        e2, e3, order = {}, {}, []
        for off, blk in _chain(self.rd, self.catalog_offset, REC_CATALOG):
            self.catalog_blocks.append(off)
            for p in range(128, BLOCK, 128):
                etype, = struct.unpack_from("<Q", blk, p)
                if etype == 0:
                    break
                self.catalog_entries.append({"type": etype, "offset": off + p})
                if etype == 1:                     # an unused slot
                    continue
                if etype not in (2, 3):
                    self.problems.append("catalog entry of unknown type %d at %#x" % (etype, off + p))
                    continue
                self.catalog_entries[-1]["store_id"] = _guid(blk[p + 16:p + 32])
                if etype == 2:
                    sid = _guid(blk[p + 16:p + 32])
                    e2[sid] = {"store_id": sid, "volume_size": struct.unpack_from("<Q", blk, p + 8)[0],
                               "created": _filetime(struct.unpack_from("<Q", blk, p + 48)[0]),
                               "created_ft": struct.unpack_from("<Q", blk, p + 48)[0]}
                    order.append(sid)
                elif etype == 3:
                    sid = _guid(blk[p + 16:p + 32])
                    block_list, = struct.unpack_from("<Q", blk, p + 8)
                    store_header, range_list, bitmap, file_ref, allocated, prev_bitmap = struct.unpack_from(
                        "<QQQQQQ", blk, p + 32)
                    e3[sid] = {"store_id": sid, "block_list": block_list, "store_header": store_header,
                               "range_list": range_list, "bitmap": bitmap, "file_ref": file_ref,
                               "allocated": allocated, "previous_bitmap": prev_bitmap}
                    if sid not in order:
                        order.append(sid)
        stores = [Store(self, e2.get(sid), e3.get(sid)) for sid in order]
        stores.sort(key=lambda s: (s.entry2.get("created_ft") or 0))
        chain = [s for s in stores if s.entry3]
        for i, s in enumerate(stores):
            s.index = i
        for a, b in zip(chain, chain[1:] + [None]):
            a.next = b
            if b is not None:
                b.previous = a
        self.stores = stores

    def unused_slots(self) -> int:
        """Catalog entries of type 1: unused slots between the copies' entries."""
        return sum(1 for e in self.catalog_entries if e["type"] == 1)

    def base_block(self, block: int, active: Store) -> bytes:
        """A block no store holds: the volume's, or zeros where it was never preserved (FREE_AS)."""
        if self.free_as == "zero":
            if active.bitmap_bit(block):
                return b"\0" * BLOCK
        elif self.free_as == "windows" and active.unpreserved(block):
            return b"\0" * BLOCK
        return self.rd.read(block * BLOCK, BLOCK)

    def cached_block(self, store: Store, block: int) -> bytes:
        key = (store.index, block)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        data = store.read_block(block)
        self._cache[key] = data
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return data

    def find(self, copy_id: str = None, index: int = None, store_id: str = None) -> Store:
        for s in self.stores:
            if copy_id and s.copy_id and s.copy_id.strip("{}").upper() == copy_id.strip("{}").upper():
                return s
            if store_id and s.store_id.strip("{}").upper() == store_id.strip("{}").upper():
                return s
        if index is not None and 0 <= index < len(self.stores):
            return self.stores[index]
        raise VssError("the catalog holds no shadow copy %s" % (copy_id or store_id or index))


class SnapshotStream(io.RawIOBase):
    """A shadow copy as a seekable, read-only volume (file-like; also has .size for dissect)."""

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.size = store.volume_size or store.volume.size
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self.size + offset
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self._pos
        n = max(0, min(n, self.size - self._pos))
        out = bytearray()
        pos = self._pos
        vol = self.store.volume
        while n > 0:
            block, inner = divmod(pos, BLOCK)
            chunk = vol.cached_block(self.store, block)[inner:inner + n]
            out += chunk
            pos += len(chunk)
            n -= len(chunk)
        self._pos = pos
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def verify_against_device(store: Store, device_path: str, blocks: List[int]) -> dict:
    """Compare this reader's blocks of one copy with Windows' own device for it. Returns counts
    and the first differing blocks with what kind of descriptor each has. A block the copy never
    preserved, which the device fills with an uninitialised buffer, counts as `undefined`, not as
    a difference: there is no right answer to compare with."""
    with open(device_path, "rb", buffering=0) as dev:
        same = diff = undefined = 0
        examples = []
        desc = store.descriptors()
        for b in blocks:
            dev.seek(b * BLOCK)
            truth = dev.read(BLOCK)
            ours = store.read_block(b)
            if truth == ours:
                same += 1
                continue
            if b not in desc and store.unpreserved(b) and not any(b in s.descriptors() for s in _later(store)):
                undefined += 1
                continue
            diff += 1
            if len(examples) < 20:
                d = desc.get(b)
                examples.append({"block": b, "descriptor": repr(d) if d else None,
                                 "in_later_store": any(b in s.descriptors() for s in _later(store)),
                                 "bitmap_bit": store.bitmap_bit(b),
                                 "previous_bit": store.bitmap_bit(b, previous=True), "ours_zero": not any(ours),
                                 "device_zero": not any(truth)})
    return {"same": same, "different": diff, "undefined": undefined, "examples": examples}


def _later(store):
    s = store.next
    while s is not None:
        yield s
        s = s.next
