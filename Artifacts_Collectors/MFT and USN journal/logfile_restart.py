"""$LogFile restart pages and the highest LSN in its log pages.

NTFS logs every metadata change to $LogFile before it writes the change into
the MFT record, and stamps the record with the LSN of that log record (FILE
header 0x08). Two facts follow, and both are read here:

* the **restart area** - two copies, at offset 0 and at one system page - says
  where recovery would start (``current_lsn``), whether the volume was
  dismounted cleanly (flag 0x0002) and which log version is in use (1.1, or
  2.0 from Windows 8). ntfs-3g and chkdsk ``/L`` reset it; an offline mount
  of a hibernated or Fast Startup volume leaves it inconsistent. Facts for the
  integrity manifest (D5); comparing them between parses is a later check.
* the **highest LSN in the log record pages** ("RCRD"). No MFT record can carry
  an LSN above it - the log is written first - so a record that does was
  written by something other than NTFS (D3). The restart area's
  ``current_lsn`` is NOT that bound: it is only rewritten at a checkpoint, and
  records flushed since then legitimately carry higher LSNs. Comparing against
  it would raise an alarm on every live volume.

Layouts from the Linux ntfs driver (fs/ntfs/logfile.h: RESTART_PAGE_HEADER,
RESTART_AREA, RECORD_PAGE_HEADER). Every field read here lies in the first
510 bytes of its page, before the first update-sequence position, so no fixup
is needed to read them.

Pure functions over bytes or a ``read(offset, length)`` callable: the live
parser reads $LogFile through its data runs, an image or a collected copy
reads a file, and a test passes bytes.
"""

import logging
import struct

logger = logging.getLogger(__name__)

RSTR = b'RSTR'
CHKD = b'CHKD'
RCRD = b'RCRD'
RESTART_VOLUME_IS_CLEAN = 0x0002
LOG_PAGE_LOG_RECORD_END = 0x0001
DEFAULT_PAGE = 4096
_PIECE = 1 << 20              # read the log in 1 MB pieces


def parse_restart_page(buf: bytes) -> dict:
    """One restart page: its header and its restart area.

    ``valid`` is False when the page does not start with RSTR/CHKD or its
    offsets point outside the page (a damaged or wiped copy)."""
    out = {'valid': False, 'magic': buf[:4].decode('latin-1') if len(buf) >= 4 else ''}
    if len(buf) < 0x30 or buf[:4] not in (RSTR, CHKD):
        return out
    try:
        (chkdsk_lsn, system_page_size, log_page_size, ra_off,
         minor, major) = struct.unpack_from('<QIIHhh', buf, 0x08)
        out.update({'chkdsk_lsn': chkdsk_lsn, 'system_page_size': system_page_size,
                    'log_page_size': log_page_size, 'restart_area_offset': ra_off,
                    'minor_version': minor, 'major_version': major,
                    'version': '%d.%d' % (major, minor)})
        if ra_off < 0x1E or ra_off + 0x30 > len(buf):
            return out
        (current_lsn, log_clients, _free, _in_use, flags, seq_bits, ra_len,
         _client_off, file_size, last_lsn_len, rec_hdr_len, page_data_off,
         open_count) = struct.unpack_from('<QHHHHIHHqIHHI', buf, ra_off)
        out.update({'current_lsn': current_lsn, 'log_clients': log_clients,
                    'flags': flags, 'clean': bool(flags & RESTART_VOLUME_IS_CLEAN),
                    'seq_number_bits': seq_bits, 'restart_area_length': ra_len,
                    'file_size': file_size, 'last_lsn_data_length': last_lsn_len,
                    'log_record_header_length': rec_hdr_len,
                    'log_page_data_offset': page_data_off,
                    'restart_log_open_count': open_count})
        out['valid'] = (system_page_size in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
                        and log_page_size in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536))
    except struct.error:
        out['valid'] = False
    return out


def record_page_lsns(page: bytes):
    """(last_lsn, last_end_lsn or None, flags) of one RCRD page, or None.

    ``last_end_lsn`` is meaningful only when the page holds the end of a log
    record (flag 0x0001)."""
    if len(page) < 0x28 or page[:4] != RCRD:
        return None
    last_lsn = struct.unpack_from('<Q', page, 0x08)[0]
    flags = struct.unpack_from('<I', page, 0x10)[0]
    end = struct.unpack_from('<Q', page, 0x20)[0] if flags & LOG_PAGE_LOG_RECORD_END else None
    return last_lsn, end, flags


def scan_logfile(read, size: int) -> dict:
    """Both restart pages, which one is in force, and the highest LSN in the
    log pages.

    ``read(offset, length)`` returns up to ``length`` bytes of the $LogFile
    stream; ``size`` is its length. Never raises: what could not be read is
    said in ``errors``.
    """
    out = {'size': size, 'restart_pages': [], 'in_force': None, 'consistent': None,
           'highest_lsn': None, 'record_pages': 0, 'empty_pages': 0, 'other_pages': 0,
           'clean': None, 'version': None, 'current_lsn': None, 'errors': []}
    try:
        first = read(0, DEFAULT_PAGE)
    except Exception as e:                       # noqa: BLE001 - reported, not raised
        out['errors'].append('restart page 1 unreadable: %s' % e)
        return out
    p1 = parse_restart_page(first)
    sys_page = p1.get('system_page_size') if p1.get('valid') else DEFAULT_PAGE
    log_page = p1.get('log_page_size') if p1.get('valid') else DEFAULT_PAGE
    if sys_page != DEFAULT_PAGE:
        try:
            first = read(0, sys_page)
            p1 = parse_restart_page(first)
        except Exception as e:                   # noqa: BLE001
            out['errors'].append('restart page 1 unreadable: %s' % e)
    try:
        p2 = parse_restart_page(read(sys_page, sys_page))
    except Exception as e:                       # noqa: BLE001
        p2 = {'valid': False, 'magic': ''}
        out['errors'].append('restart page 2 unreadable: %s' % e)
    p1['offset'], p2['offset'] = 0, sys_page
    out['restart_pages'] = [p1, p2]
    valid = [p for p in (p1, p2) if p.get('valid')]
    if valid:
        # The copy written last (the higher current LSN) is the one in force.
        in_force = max(valid, key=lambda p: p.get('current_lsn') or 0)
        out['in_force'] = in_force['offset']
        out['clean'] = in_force.get('clean')
        out['version'] = in_force.get('version')
        out['current_lsn'] = in_force.get('current_lsn')
    # Two copies "agree" when both are readable and describe the same log:
    # same version and page sizes. Their current LSNs differ by design (they
    # are written alternately), so those are not compared.
    if len(valid) == 2:
        keys = ('version', 'system_page_size', 'log_page_size', 'file_size')
        out['consistent'] = all(p1.get(k) == p2.get(k) for k in keys)
    else:
        out['consistent'] = False

    highest = None
    start = 2 * sys_page
    off = start
    while off + log_page <= size:
        want = min(_PIECE, size - off)
        want -= want % log_page
        if want <= 0:
            break
        try:
            piece = read(off, want)
        except Exception as e:                   # noqa: BLE001
            out['errors'].append('log pages at %d unreadable: %s' % (off, e))
            break
        if not piece:
            break
        for p in range(0, len(piece) - log_page + 1, log_page):
            page = piece[p:p + log_page]
            lsns = record_page_lsns(page)
            if lsns is None:
                if page[:4] in (b'\xff\xff\xff\xff', b'\x00\x00\x00\x00'):
                    out['empty_pages'] += 1
                else:
                    out['other_pages'] += 1
                continue
            out['record_pages'] += 1
            for v in (lsns[0], lsns[1]):
                if v is not None and (highest is None or v > highest):
                    highest = v
        off += len(piece) - len(piece) % log_page
        if len(piece) < want:
            break
    out['highest_lsn'] = highest
    return out


def scan_logfile_bytes(data: bytes) -> dict:
    """scan_logfile over a $LogFile already in memory (a test, a small copy)."""
    return scan_logfile(lambda o, n: data[o:o + n], len(data))


def scan_logfile_path(path: str) -> dict:
    """scan_logfile over a $LogFile copied out as a file."""
    import os
    size = os.path.getsize(path)
    with open(path, 'rb') as fh:
        def read(o, n):
            fh.seek(o)
            return fh.read(n)
        return scan_logfile(read, size)


def summary(scan: dict) -> dict:
    """The facts the integrity manifest keeps (D5): no per-page detail."""
    if not scan:
        return {'available': False}
    pages = []
    for p in scan.get('restart_pages') or []:
        pages.append({k: p.get(k) for k in ('offset', 'magic', 'valid', 'version',
                                             'current_lsn', 'clean', 'flags',
                                             'restart_log_open_count', 'file_size')})
    return {'available': True, 'size': scan.get('size'), 'version': scan.get('version'),
            'clean': scan.get('clean'), 'current_lsn': scan.get('current_lsn'),
            'restart_pages': pages, 'restart_pages_consistent': scan.get('consistent'),
            'in_force': scan.get('in_force'), 'highest_lsn': scan.get('highest_lsn'),
            'record_pages': scan.get('record_pages'), 'empty_pages': scan.get('empty_pages'),
            'errors': scan.get('errors') or []}
