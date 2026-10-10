"""NTFS data runs: where a non-resident attribute's bytes really are on disk.

The $MFT is a file like any other, and on a volume that has been in use for a
while it is fragmented. Reading "record N" as ``mft_lcn * cluster + N * 1024``
only works inside the first fragment: past it the arithmetic lands on unrelated
clusters, the "FILE" signature check fails, and the record is dropped with no
error. On a real C: drive that was 205,056 records read out of 3.3 million, so
97% of the USN journal pointed at files the MFT "did not have".

Shared by the live MFT parser (``MFT_Claw.VolumeReader``) and the raw-disk
$MFT copier (``crow_claw.core.raw_disk_access_strategy.read_mft``), so the copy
an offline import parses and the live parse read the same bytes.
"""

import bisect
import struct
from typing import Callable, List, Optional, Tuple

ATTR_ATTRIBUTE_LIST = 0x20
ATTR_DATA = 0x80
END_MARKER = 0xFFFFFFFF

# (first VCN, first LCN or None for a sparse run, length in clusters)
Run = Tuple[int, Optional[int], int]


def apply_fixups(raw: bytes, stride: int = 512):
    """Undo NTFS's update-sequence protection on one FILE record.

    NTFS writes a record with the last two bytes of every 512-byte stride
    replaced by the update sequence number, and keeps the real bytes in the
    update sequence array (offset and count at 0x04 / 0x06). A record read
    without putting them back has two wrong bytes at offsets 510 and 1022 -
    in a file name, a timestamp or a data run, whatever sits there.

    Returns (bytes, ok); ok is False when a stride did not end with the
    sequence number (a torn write) - the bytes are restored regardless.
    """
    if len(raw) < 48:
        return raw, False
    usa_off, usa_count = struct.unpack_from('<HH', raw, 4)
    if usa_count < 2 or usa_off < 42 or usa_off + 2 * usa_count > len(raw):
        return raw, False
    buf = bytearray(raw)
    usn = raw[usa_off:usa_off + 2]
    ok = True
    for i in range(1, usa_count):
        end = i * stride - 2
        if end + 2 > len(buf):
            break
        if bytes(buf[end:end + 2]) != usn:
            ok = False
        buf[end:end + 2] = raw[usa_off + 2 * i:usa_off + 2 * i + 2]
    return bytes(buf), ok


def decode_runlist(buf: bytes, offset: int = 0, first_vcn: int = 0) -> List[Run]:
    """Decode a mapping-pairs array into runs.

    Each run starts with a header byte: the low nibble is the size of the
    length field, the high nibble the size of the (signed, relative) LCN
    offset; a zero offset size means a sparse run. A zero header ends it.
    """
    runs: List[Run] = []
    lcn = 0
    vcn = first_vcn
    n = len(buf)
    while offset < n:
        header = buf[offset]
        if header == 0:
            break
        len_size = header & 0x0F
        off_size = header >> 4
        offset += 1
        if len_size == 0 or len_size > 8 or off_size > 8 or offset + len_size + off_size > n:
            break
        length = int.from_bytes(buf[offset:offset + len_size], 'little')
        offset += len_size
        if off_size == 0:
            runs.append((vcn, None, length))
        else:
            lcn += int.from_bytes(buf[offset:offset + off_size], 'little', signed=True)
            offset += off_size
            runs.append((vcn, lcn, length))
        vcn += length
    return runs


def nonresident_header(rec: bytes, attr_off: int) -> dict:
    """The fields of a non-resident attribute header, offsets from the
    attribute's own start: 0x10 first VCN, 0x18 last VCN, 0x20 runlist
    offset, 0x28 allocated size, 0x30 data (real) size, 0x38 initialised."""
    first_vcn, last_vcn = struct.unpack_from('<QQ', rec, attr_off + 0x10)
    runlist_off = struct.unpack_from('<H', rec, attr_off + 0x20)[0]
    allocated, data_size, initialised = struct.unpack_from('<QQQ', rec, attr_off + 0x28)
    return {
        'first_vcn': first_vcn, 'last_vcn': last_vcn, 'runlist_offset': runlist_off,
        'allocated_size': allocated, 'data_size': data_size,
        'initialized_size': initialised,
    }


def _attributes(rec: bytes):
    """Yield (type, offset, length, non_resident, name) for each attribute."""
    off = struct.unpack_from('<H', rec, 0x14)[0]
    while off + 16 <= len(rec):
        a_type, a_len = struct.unpack_from('<II', rec, off)
        if a_type == END_MARKER or a_len == 0 or off + a_len > len(rec):
            return
        non_res = rec[off + 8]
        name_len = rec[off + 9]
        name_off = struct.unpack_from('<H', rec, off + 10)[0]
        name = ''
        if name_len:
            name = rec[off + name_off:off + name_off + 2 * name_len].decode('utf-16le', 'replace')
        yield a_type, off, a_len, non_res, name
        off += a_len


def unnamed_data_runs(rec: bytes) -> Tuple[List[Run], Optional[dict], List[Tuple[int, int]]]:
    """Runs of the unnamed $DATA attribute in one (fixed-up) FILE record.

    Returns (runs, header of the segment that starts at VCN 0 or None,
    [(record_number, first_vcn)] of further $DATA segments named in an
    $ATTRIBUTE_LIST - an $MFT so fragmented its runlist did not fit).
    """
    runs: List[Run] = []
    header = None
    more: List[Tuple[int, int]] = []
    own_record = struct.unpack_from('<I', rec, 0x2C)[0] if len(rec) >= 0x30 else -1
    for a_type, off, a_len, non_res, name in _attributes(rec):
        if a_type == ATTR_DATA and not name and non_res:
            h = nonresident_header(rec, off)
            runs.extend(decode_runlist(rec[off:off + a_len], h['runlist_offset'], h['first_vcn']))
            if h['first_vcn'] == 0:
                header = h
        elif a_type == ATTR_ATTRIBUTE_LIST and not non_res:
            v_len, v_off = struct.unpack_from('<IH', rec, off + 0x10)
            body = rec[off + v_off:off + v_off + v_len]
            p = 0
            while p + 26 <= len(body):
                e_type, e_len = struct.unpack_from('<IH', body, p)
                if e_len == 0:
                    break
                e_name_len = body[p + 6]
                start_vcn = struct.unpack_from('<Q', body, p + 8)[0]
                ref = struct.unpack_from('<Q', body, p + 16)[0] & 0xFFFFFFFFFFFF
                if e_type == ATTR_DATA and e_name_len == 0 and ref != own_record and start_vcn > 0:
                    more.append((ref, start_vcn))
                p += e_len
    return runs, header, more


class RunMap:
    """Translate a byte range of an attribute's stream to disk pieces."""

    def __init__(self, runs: List[Run], cluster_size: int):
        self.cluster = cluster_size
        self.runs = sorted(runs, key=lambda r: r[0])
        self._starts = [r[0] for r in self.runs]

    @property
    def clusters(self) -> int:
        return sum(r[2] for r in self.runs)

    def pieces(self, offset: int, length: int):
        """Yield (disk_offset or None for sparse/unmapped, length) covering
        ``length`` bytes of the stream from ``offset``."""
        c = self.cluster
        while length > 0:
            vcn = offset // c
            i = bisect.bisect_right(self._starts, vcn) - 1
            if i < 0 or vcn >= self.runs[i][0] + self.runs[i][2]:
                # Not mapped: the next run start bounds the hole.
                nxt = self._starts[i + 1] * c if i + 1 < len(self.runs) else offset + length
                take = max(1, min(length, nxt - offset))
                yield None, take
            else:
                first_vcn, lcn, count = self.runs[i]
                run_end = (first_vcn + count) * c
                take = min(length, run_end - offset)
                if lcn is None:
                    yield None, take
                else:
                    yield (lcn + (vcn - first_vcn)) * c + offset % c, take
            offset += take
            length -= take


def read_stream(read_at: Callable[[int, int], bytes], runmap: RunMap,
                offset: int, length: int) -> bytes:
    """Read ``length`` bytes of a stream through its run map; holes read as
    zeros. ``read_at(disk_offset, n)`` must return exactly n bytes or fewer
    at the end of the device."""
    out = bytearray()
    for disk_off, n in runmap.pieces(offset, length):
        if disk_off is None:
            out += b'\0' * n
        else:
            data = read_at(disk_off, n)
            out += data
            if len(data) < n:
                out += b'\0' * (n - len(data))
    return bytes(out)


def mft_layout(read_at: Callable[[int, int], bytes], mft_lcn: int,
               cluster_size: int, record_size: int):
    """Locate the whole $MFT from its own record 0.

    Returns (RunMap, data_size, allocated_size). Record 0 always lies in the
    first run, so it can be read at ``mft_lcn``; when its runlist continues in
    extension records (an $ATTRIBUTE_LIST), those are read through the runs
    known so far.
    """
    raw = read_at(mft_lcn * cluster_size, record_size)
    if raw[:4] != b'FILE':
        raise ValueError("record 0 of the $MFT has no FILE signature")
    rec, _ok = apply_fixups(raw)
    runs, header, more = unnamed_data_runs(rec)
    if header is None:
        raise ValueError("record 0 of the $MFT has no non-resident unnamed $DATA")
    runmap = RunMap(runs, cluster_size)
    for ref, _vcn in sorted(more, key=lambda x: x[1]):
        ext_raw = read_stream(read_at, runmap, ref * record_size, record_size)
        if ext_raw[:4] != b'FILE':
            continue
        ext, _ok = apply_fixups(ext_raw)
        ext_runs, _h, _m = unnamed_data_runs(ext)
        runs.extend(ext_runs)
        runmap = RunMap(runs, cluster_size)
    return runmap, header['data_size'], header['allocated_size']
