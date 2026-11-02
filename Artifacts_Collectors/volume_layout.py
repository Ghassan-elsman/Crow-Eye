"""
Where a volume's own forensic structures sit: $MFT, the USN journal and shadow-copy storage.

The partition bar draws a volume to scale, and on that scale these structures are slivers: a
3 GB $MFT on a 1 TB volume is 0.3% of the bar. So the bar needs their real positions, not a
guess, and this module supplies them for a live NTFS volume:

- $MFT and $Extend\\$UsnJrnl:$J: FSCTL_GET_RETRIEVAL_POINTERS on the files themselves.
- Shadow-copy storage: the store files in System Volume Information, named
  {random GUID}{3808876b-c176-4e48-b7ae-04046e6cc752}. The volume shadow driver refuses to open
  them even with SeBackupPrivilege and no access requested (error 5), so their extents are read
  from their own $MFT records instead: the directory listing gives each file's record number,
  the record is read raw from the volume, and its $DATA runs (through an $ATTRIBUTE_LIST when the
  file is fragmented enough to need one) are the extents. Their sum is checked against WMI's
  Win32_ShadowStorage.AllocatedSpace by the caller's tests, which is how a wrong offset shows.
- Shadow storage used / allocated / maximum and the number of copies: Win32_ShadowStorage and
  Win32_ShadowCopy, through PowerShell like the rest of the partition analyzer.

Live only, and administrator only: without elevation the volume cannot be opened and every
field stays empty, with the reason in `layout_note`. Offsets are bytes from the start of the
volume. Output is ASCII-only, because parsers run inside the GUI process on a cp1252 console.
"""
import ctypes
import json
import os
import struct
import subprocess
import sys

VSS_GUID = '{3808876b-c176-4e48-b7ae-04046e6cc752}'

# One volume's extents are kept to this many runs per kind. Shadow storage on a busy volume can
# run to thousands of fragments; past the cap the nearest neighbours are merged, which keeps the
# drawn coverage right to within a pixel and keeps the table small enough to send every day.
MAX_RUNS = 2048

_FSCTL_GET_RETRIEVAL_POINTERS = 0x00090073
_FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064
_ERROR_MORE_DATA = 234
_ERROR_HANDLE_EOF = 38
_FILE_ID_BOTH_DIR_INFO = 10
_FILE_ID_BOTH_DIR_RESTART = 11

_win = None


def _api():
    """ctypes bindings, built once and only on Windows."""
    global _win
    if _win is not None:
        return _win
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    k32.GetFileInformationByHandleEx.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.GetCurrentProcess.restype = wt.HANDLE
    adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    adv.LookupPrivilegeValueW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p]
    adv.AdjustTokenPrivileges.argtypes = [wt.HANDLE, wt.BOOL, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    _win = (k32, adv, wt, wt.HANDLE(-1).value)
    return _win


def _enable_backup_privilege():
    """SeBackupPrivilege, so System Volume Information can be listed whatever its ACL says."""
    k32, adv, wt, _ = _api()

    class LUID(ctypes.Structure):
        _fields_ = [('Low', wt.DWORD), ('High', wt.LONG)]

    class TP(ctypes.Structure):
        _fields_ = [('Count', wt.DWORD), ('Luid', LUID), ('Attr', wt.DWORD)]

    tok = wt.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):
        return False
    try:
        luid = LUID()
        if not adv.LookupPrivilegeValueW(None, 'SeBackupPrivilege', ctypes.byref(luid)):
            return False
        adv.AdjustTokenPrivileges(tok, False, ctypes.byref(TP(1, luid, 2)), 0, None, None)
        return ctypes.get_last_error() == 0
    finally:
        k32.CloseHandle(tok)


def _open(path, access):
    k32, _, _, invalid = _api()
    h = k32.CreateFileW(path, access, 7, None, 3, 0x02000000, None)   # share all, OPEN_EXISTING, BACKUP_SEMANTICS
    if h == invalid:
        raise OSError(ctypes.get_last_error(), 'cannot open ' + path)
    return h


def _ioctl(h, code, inbuf, size):
    k32, _, wt, _ = _api()
    buf = ctypes.create_string_buffer(size)
    ret = wt.DWORD()
    ok = k32.DeviceIoControl(h, code, inbuf, len(inbuf) if inbuf else 0, buf, size, ctypes.byref(ret), None)
    return ok, ctypes.get_last_error(), buf


def volume_data(letter):
    """FSCTL_GET_NTFS_VOLUME_DATA: cluster size, cluster count, $MFT position and valid length."""
    k32 = _api()[0]
    h = _open('\\\\.\\' + letter + ':', 0x80000000)
    try:
        ok, err, buf = _ioctl(h, _FSCTL_GET_NTFS_VOLUME_DATA, None, 256)
        if not ok:
            raise OSError(err, 'NTFS volume data')
        f = struct.unpack_from('<qqqqqIIIIqqqqq', buf, 0)
        return {'total_clusters': f[2], 'free_clusters': f[3], 'bytes_per_cluster': f[6],
                'bytes_per_record': f[7], 'mft_valid_length': f[9], 'mft_start_lcn': f[10],
                'mft_zone_start': f[12], 'mft_zone_end': f[13]}
    finally:
        k32.CloseHandle(h)


def file_runs(path):
    """[(vcn, lcn, clusters)] of a file's default or named stream; lcn -1 is sparse."""
    k32 = _api()[0]
    h = _open(path, 0x80)                                  # FILE_READ_ATTRIBUTES
    out, vcn = [], 0
    try:
        while True:
            ok, err, buf = _ioctl(h, _FSCTL_GET_RETRIEVAL_POINTERS, struct.pack('<q', vcn), 64 * 1024)
            if not ok and err == _ERROR_HANDLE_EOF:
                return out
            if not ok and err != _ERROR_MORE_DATA:
                raise OSError(err, 'retrieval pointers ' + path)
            count, prev = struct.unpack_from('<I4xq', buf, 0)
            for i in range(count):
                nxt, lcn = struct.unpack_from('<qq', buf, 16 + i * 16)
                out.append((prev, lcn, nxt - prev))
                prev = nxt
            if ok:
                return out
            vcn = prev
    finally:
        k32.CloseHandle(h)


def _dir_entries(path):
    """[(name, size, mft_record)] of a directory, from FileIdBothDirectoryInfo."""
    k32 = _api()[0]
    h = _open(path, 0x1)                                   # FILE_LIST_DIRECTORY
    out, cls = [], _FILE_ID_BOTH_DIR_RESTART
    try:
        while True:
            buf = ctypes.create_string_buffer(64 * 1024)
            if not k32.GetFileInformationByHandleEx(h, cls, buf, len(buf)):
                if ctypes.get_last_error() == 18:          # ERROR_NO_MORE_FILES
                    return out
                raise OSError(ctypes.get_last_error(), 'list ' + path)
            cls, off = _FILE_ID_BOTH_DIR_INFO, 0
            while True:
                nxt = struct.unpack_from('<I', buf, off)[0]
                eof = struct.unpack_from('<q', buf, off + 40)[0]
                nlen = struct.unpack_from('<I', buf, off + 60)[0]
                fid = struct.unpack_from('<q', buf, off + 96)[0]
                name = buf.raw[off + 104: off + 104 + nlen].decode('utf-16-le', 'replace')
                out.append((name, eof, fid & 0xFFFFFFFFFFFF))
                if not nxt:
                    break
                off += nxt
    finally:
        k32.CloseHandle(h)


def _decode_runlist(data, pos):
    """[(lcn, clusters)] from an NTFS mapping-pairs array; lcn None is sparse."""
    out, lcn = [], 0
    while pos < len(data) and data[pos]:
        head = data[pos]
        ls, os_ = head & 0x0F, head >> 4
        pos += 1
        length = int.from_bytes(data[pos:pos + ls], 'little')
        pos += ls
        if os_:
            lcn += int.from_bytes(data[pos:pos + os_], 'little', signed=True)
            out.append((lcn, length))
        else:
            out.append((None, length))
        pos += os_
    return out


class _RawMft:
    """Reads FILE records straight from the volume, through the $MFT's own extents."""

    def __init__(self, letter, vd):
        self.bpc = vd['bytes_per_cluster']
        self.rec = vd['bytes_per_record']
        self.extents = [(v, l, c) for v, l, c in file_runs(letter + ':\\$MFT') if l >= 0]
        self.f = open('\\\\.\\' + letter + ':', 'rb', buffering=0)

    def close(self):
        self.f.close()

    def _read(self, offset, length):
        start = offset - offset % 4096
        end = offset + length
        end += (-end) % 4096
        self.f.seek(start)
        return self.f.read(end - start)[offset - start: offset - start + length]

    def record(self, number):
        byte = number * self.rec
        for vcn, lcn, n in self.extents:
            lo = vcn * self.bpc
            if lo <= byte < lo + n * self.bpc:
                buf = bytearray(self._read(lcn * self.bpc + (byte - lo), self.rec))
                break
        else:
            return None
        if buf[:4] != b'FILE':
            return None
        uso, usc = struct.unpack_from('<HH', buf, 4)
        usn = buf[uso:uso + 2]
        for i in range(1, usc):
            end = i * 512
            if end > len(buf) or buf[end - 2:end] != usn:
                return None                                # a torn record: trust none of it
            buf[end - 2:end] = buf[uso + 2 * i: uso + 2 * i + 2]
        return bytes(buf)

    def read_runs(self, runs, length):
        data = b''
        for lcn, n in runs:
            if lcn is None:
                data += b'\0' * (n * self.bpc)
            else:
                data += self._read(lcn * self.bpc, n * self.bpc)
            if len(data) >= length:
                break
        return data[:length]


class StreamMft(_RawMft):
    """The $MFT of an NTFS volume held in any seekable stream - a shadow copy rebuilt by
    vss_reader, an image partition, a raw volume. The boot sector gives the cluster and record
    sizes and where $MFT starts; record 0's own $DATA (and its attribute list) gives the rest."""

    def __init__(self, fh):
        self.f = fh
        boot = self._read(0, 512)
        if boot[3:11] != b'NTFS    ':
            raise ValueError('not an NTFS volume (no NTFS boot sector)')
        bps = struct.unpack_from('<H', boot, 0x0B)[0]
        spc = boot[0x0D]
        if spc > 0x80:
            spc = 1 << (256 - spc)
        self.bpc = bps * spc
        cpr = struct.unpack_from('<b', boot, 0x40)[0]
        self.rec = cpr * self.bpc if cpr > 0 else 1 << (-cpr)
        mft_lcn = struct.unpack_from('<Q', boot, 0x30)[0]
        self.extents = [(0, mft_lcn, 64)]                 # enough for record 0 and its neighbours
        rec0 = self.record(0)
        if rec0 is None:
            raise ValueError('$MFT record 0 is not readable')
        self.extents = [(0, mft_lcn, 1 << 40)]
        self.size = 0
        for atype, a in _attrs(rec0):
            if atype == 0x80 and a[9] == 0 and a[8] and struct.unpack_from('<q', a, 0x10)[0] == 0:
                self.size = struct.unpack_from('<q', a, 0x30)[0]
        extents, vcn = [], 0
        for lcn, n in _data_runs(self, 0):
            if lcn is not None:
                extents.append((vcn, lcn, n))
            vcn += n
        if not extents:
            raise ValueError('$MFT has no data runs')
        self.extents = extents
        self.size = min(self.size or vcn * self.bpc, vcn * self.bpc)

    def close(self):
        pass

    def _read(self, offset, length):
        self.f.seek(offset)
        data = self.f.read(length)
        return data + b'\0' * (length - len(data))

    def read_records(self, first, count):
        """`count` raw records from record `first`, through the $MFT's extents (fixups not applied)."""
        want = first * self.rec
        end = min(want + count * self.rec, self.size)
        out = bytearray()
        while want < end:
            for vcn, lcn, n in self.extents:
                lo = vcn * self.bpc
                hi = lo + n * self.bpc
                if lo <= want < hi:
                    take = min(end, hi) - want
                    out += self._read(lcn * self.bpc + (want - lo), take)
                    want += take
                    break
            else:                                         # a hole in the run list: no records there
                nxt = min((v * self.bpc for v, _l, _n in self.extents if v * self.bpc > want), default=end)
                out += b'\0' * (min(nxt, end) - want)
                want = min(nxt, end)
        return bytes(out)


def _attrs(rec):
    pos = struct.unpack_from('<H', rec, 0x14)[0]
    while pos + 8 <= len(rec):
        atype, alen = struct.unpack_from('<II', rec, pos)
        if atype == 0xFFFFFFFF or alen == 0:
            return
        yield atype, rec[pos:pos + alen]
        pos += alen


def _data_runs(mft, number, seen=None):
    """[(lcn, clusters)] of the unnamed $DATA of one record, following its $ATTRIBUTE_LIST."""
    rec = mft.record(number)
    if rec is None:
        return []
    runs, extra = [], []
    for atype, a in _attrs(rec):
        nonres, nlen = a[8], a[9]
        if atype == 0x80 and nlen == 0 and nonres:
            runs += _decode_runlist(a, struct.unpack_from('<H', a, 0x20)[0])
        elif atype == 0x20:
            if nonres:
                size = struct.unpack_from('<q', a, 0x30)[0]
                lst = mft.read_runs(_decode_runlist(a, struct.unpack_from('<H', a, 0x20)[0]), size)
            else:
                vlen, voff = struct.unpack_from('<IH', a, 0x10)
                lst = a[voff:voff + vlen]
            p = 0
            while p + 26 <= len(lst):
                etype, elen, enlen = struct.unpack_from('<IHB', lst, p)
                if elen == 0:
                    break
                ref = struct.unpack_from('<Q', lst, p + 16)[0] & 0xFFFFFFFFFFFF
                if etype == 0x80 and enlen == 0 and ref != number:
                    extra.append(ref)
                p += elen
    seen = seen if seen is not None else {number}
    for ref in dict.fromkeys(extra):
        if ref in seen:
            continue
        seen.add(ref)
        r = mft.record(ref)
        if r is None:
            continue
        for atype, a in _attrs(r):
            if atype == 0x80 and a[9] == 0 and a[8]:
                runs += _decode_runlist(a, struct.unpack_from('<H', a, 0x20)[0])
    return runs


def _merge(runs, cap=MAX_RUNS):
    """Sorted (offset, length) runs, adjacent ones joined, then the smallest gaps closed to the cap."""
    runs = sorted(r for r in runs if r[1] > 0)
    out = []
    for off, ln in runs:
        if out and off <= out[-1][0] + out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][0] + out[-1][1], off + ln) - out[-1][0])
        else:
            out.append((off, ln))
    while len(out) > cap:
        gaps = sorted(range(len(out) - 1), key=lambda i: out[i + 1][0] - (out[i][0] + out[i][1]))
        drop = set(gaps[:len(out) - cap])
        merged = []
        for i, r in enumerate(out):
            if merged and (i - 1) in drop:
                merged[-1] = (merged[-1][0], r[0] + r[1] - merged[-1][0])
            else:
                merged.append(r)
        out = merged
    return out


def _powershell_json(cmd):
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=60)
        data = json.loads(r.stdout) if r.stdout.strip() else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


# ---------------------------------------------------------------------------------------------
# one PowerShell process for every WMI and event-log question, shared by the windows
# ---------------------------------------------------------------------------------------------
# Each PowerShell launch costs about half a second before it answers anything, and the Shadow Copies
# window asked ten questions in ten launches (7 s), then the File Browser asked them again. They now go
# in one script, and each answer is kept for SNAPSHOT_MAX_AGE seconds so the next window reuses it.
SNAPSHOT_MAX_AGE = 60.0
SECTIONS = {
    'volumes': "Get-CimInstance Win32_Volume | Select-Object DeviceID, DriveLetter",
    'storage': ("Get-CimInstance Win32_ShadowStorage | ForEach-Object { [pscustomobject]@{"
                "Volume=$_.Volume.DeviceID; Diff=$_.DiffVolume.DeviceID; Used=$_.UsedSpace;"
                "Allocated=$_.AllocatedSpace; Max=$_.MaxSpace } }"),
    'copies': ("Get-CimInstance Win32_ShadowCopy | ForEach-Object { [pscustomobject]@{ ID=$_.ID; Set=$_.SetID;"
               "Device=$_.DeviceObject; Volume=$_.VolumeName; ClientAccessible=$_.ClientAccessible;"
               "Persistent=$_.Persistent; Provider=$_.ProviderID; State=$_.State;"
               "At=$_.InstallDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } }"),
}
_snapshot_cache = {}             # (name, command) -> (when, rows)
_snapshot_lock = None


def wmi_snapshot(sections=None, max_age=None):
    """{name: rows} for the named PowerShell pipelines (SECTIONS, or {name: command} given), in ONE
    PowerShell process. An answer younger than `max_age` seconds (SNAPSHOT_MAX_AGE) is reused; 0
    asks again. A pipeline that fails gives [] and the others still answer."""
    import threading
    import time as _time
    global _snapshot_lock
    if _snapshot_lock is None:
        _snapshot_lock = threading.Lock()
    if sections is None:
        sections = dict(SECTIONS)
    elif not isinstance(sections, dict):
        sections = {n: SECTIONS[n] for n in sections}
    max_age = SNAPSHOT_MAX_AGE if max_age is None else max_age
    now = _time.time()
    out, missing = {}, {}
    with _snapshot_lock:
        for name, cmd in sections.items():
            hit = _snapshot_cache.get((name, cmd))
            if hit is not None and now - hit[0] <= max_age:
                out[name] = hit[1]
            else:
                missing[name] = cmd
    if missing:
        script = ["$ErrorActionPreference = 'SilentlyContinue'", "$o = [ordered]@{}"]
        for name, cmd in missing.items():
            script.append("try { $o['%s'] = @(%s) } catch { $o['%s'] = @() }" % (name, cmd, name))
        script.append("$o | ConvertTo-Json -Compress -Depth 5")
        data = {}
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-Command', '; '.join(script)], capture_output=True,
                               text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=120)
            data = json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            data = {}
        with _snapshot_lock:
            for name, cmd in missing.items():
                rows = data.get(name) if isinstance(data, dict) else None
                rows = [] if rows is None else (rows if isinstance(rows, list) else [rows])
                out[name] = rows
                _snapshot_cache[(name, cmd)] = (now, rows)
    return out


def _volume_letters(snapshot):
    return {v.get('DeviceID'): (v.get('DriveLetter') or '').rstrip(':') for v in snapshot.get('volumes') or []}


def shadow_storage(snapshot=None, max_age=None):
    """{'C': {used, allocated, max, diff_volume, copies, oldest, newest}} from WMI, times in UTC."""
    snap = snapshot if snapshot is not None else wmi_snapshot(('volumes', 'storage', 'copies'), max_age)
    vols = _volume_letters(snap)
    out = {}
    for s in snap.get('storage') or []:
        letter = vols.get(s.get('Volume'))
        if letter:
            out[letter] = {'used': int(s.get('Used') or 0), 'allocated': int(s.get('Allocated') or 0),
                           'max': int(s.get('Max') or 0), 'diff_volume': vols.get(s.get('Diff')) or '',
                           'copies': 0, 'oldest': '', 'newest': ''}
    for c in snap.get('copies') or []:
        letter = vols.get(c.get('Volume'))
        if not letter:
            continue
        s = out.setdefault(letter, {'used': 0, 'allocated': 0, 'max': 0, 'diff_volume': '',
                                    'copies': 0, 'oldest': '', 'newest': ''})
        s['copies'] += 1
        at = c.get('At') or ''
        if at and (not s['oldest'] or at < s['oldest']):
            s['oldest'] = at
        if at and at > s['newest']:
            s['newest'] = at
    return out


def volume_layout(letter, storage=None):
    """One NTFS volume's structures: sizes, positions and shadow storage. Never raises."""
    letter = letter.rstrip(':\\').upper()
    out = {'mft_bytes': 0, 'usn_bytes': 0, 'vss_used': 0, 'vss_allocated': 0, 'vss_max': 0,
           'vss_copies': 0, 'vss_diff_volume': '', 'vss_oldest': '', 'vss_newest': '',
           'cluster_size': 0, 'extents': [], 'layout_note': ''}
    s = (storage if storage is not None else shadow_storage()).get(letter)
    if s:
        out.update(vss_used=s['used'], vss_allocated=s['allocated'], vss_max=s['max'], vss_copies=s['copies'],
                   vss_diff_volume=s['diff_volume'], vss_oldest=s['oldest'], vss_newest=s['newest'])
    if sys.platform != 'win32':
        out['layout_note'] = 'live Windows only'
        return out
    try:
        vd = volume_data(letter)
    except OSError as e:
        out['layout_note'] = 'volume not readable (%s); run as administrator' % (e.args[0],)
        return out
    bpc = vd['bytes_per_cluster']
    out['cluster_size'] = bpc
    notes = []

    def add(kind, runs):
        """Keep the merged runs for drawing; the size is the raw runs' sum, gaps never counted."""
        raw = [(l * bpc, n * bpc) for l, n in runs if l is not None and l >= 0]
        out['extents'] += [(kind, o, n) for o, n in _merge(raw)]
        return sum(n for _, n in raw)

    try:
        out['mft_bytes'] = add('mft', [(l, n) for _, l, n in file_runs(letter + ':\\$MFT')])
    except OSError as e:
        notes.append('$MFT: %s' % (e.args[0],))
    try:
        out['usn_bytes'] = add('usn', [(l, n) for _, l, n in file_runs(letter + ':\\$Extend\\$UsnJrnl:$J')])
    except OSError as e:
        notes.append('USN journal: %s' % (e.args[0],))      # 2 = no journal on this volume
    if out['vss_allocated'] or out['vss_copies']:
        _enable_backup_privilege()
        mft = None
        try:
            mft = _RawMft(letter, vd)
            runs = []
            for name, _size, rec in _dir_entries(letter + ':\\System Volume Information'):
                if name.lower().endswith(VSS_GUID):
                    runs += _data_runs(mft, rec)
            add('vss', runs)
        except OSError as e:
            notes.append('shadow storage position: %s' % (e.args[0],))
        finally:
            if mft:
                mft.close()
    out['layout_note'] = '; '.join(notes)
    return out


def _filetime_iso(ft):
    """FILETIME (100 ns since 1601) -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC)."""
    if not ft:
        return ''
    import datetime
    try:
        return (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (OverflowError, ValueError):
        return ''


def _guid(b):
    import uuid
    return '{' + str(uuid.UUID(bytes_le=bytes(b))).upper() + '}'


class _ReadAt:
    """A positioned-read function as a seekable file, for vss_reader."""

    def __init__(self, read):
        self._r, self._pos = read, 0

    def seek(self, offset, whence=0):
        self._pos = offset
        return offset

    def read(self, n):
        data = self._r(self._pos, n)
        self._pos += len(data)
        return data


def _wmi_copies(snapshot=None):
    """Win32_ShadowCopy rows keyed by the copy's id: device, volume and creation time (UTC)."""
    out = {}
    snap = snapshot if snapshot is not None else wmi_snapshot(('copies',))
    for c in snap.get('copies') or []:
        if c.get('ID'):
            out[str(c['ID']).upper()] = c
    return out


def shadow_copies(letter, snapshot=None):
    """Every shadow copy of a live NTFS volume with what it occupies and where.

    The catalog joins each copy to its store; the store's MFT record gives its data runs, so a
    copy's size is what its own store files hold on disk, not a share of a total. WMI adds the
    device each copy is browsed through. Returns (copies, catalog_bytes, note); copies are dicts
    with number (from the device name), shadow_id, created (UTC), device, store_bytes and extents
    [(offset, length)], oldest first. A copy WMI lists but the catalog does not has no size."""
    letter = letter.rstrip(':\\').upper()
    snap = snapshot if snapshot is not None else wmi_snapshot(('volumes', 'copies'))
    wmi = _wmi_copies(snap)
    vols = _volume_letters(snap)
    mine = {k: v for k, v in wmi.items() if vols.get(v.get('Volume')) == letter}
    copies, note, catalog_bytes = [], '', 0
    try:
        vd = volume_data(letter)
        _enable_backup_privilege()
        mft = _RawMft(letter, vd)
    except OSError as e:
        mft, note = None, 'volume not readable (%s); run as administrator' % (e.args[0],)
    by_id = {}
    if mft is not None:
        try:
            from Artifacts_Collectors import vss_reader
            bpc = vd['bytes_per_cluster']
            try:
                stores = vss_reader.VssVolume(_ReadAt(mft._read), vd['total_clusters'] * bpc).stores
            except vss_reader.VssError:
                stores = []
            for st in stores:
                ref = (st.entry3.get('file_ref') or 0) & 0xFFFFFFFFFFFF
                runs = [(l * bpc, n * bpc) for l, n in _data_runs(mft, ref) if l is not None] if ref else []
                if st.copy_id:
                    by_id[st.copy_id] = {
                        'store_guid': st.store_id, 'created': st.created, 'set_id': st.set_id,
                        'context': st.context, 'attributes': st.attribute_names(),
                        'originating_machine': st.originating_machine, 'readable': st.readable,
                        'problems': list(st.problems), 'store_bytes': sum(n for _, n in runs),
                        'extents': _merge(runs, 256)}
            for name, _size, rec in _dir_entries(letter + ':\\System Volume Information'):
                if name.lower() == VSS_GUID:
                    catalog_bytes = sum(n * bpc for l, n in _data_runs(mft, rec) if l is not None)
        except OSError as e:
            note = 'catalog not readable (%s)' % (e.args[0],)
        finally:
            mft.close()
    for sid in sorted(set(by_id) | set(mine)):
        s, w = by_id.get(sid, {}), mine.get(sid, {})
        device = w.get('Device') or ''
        tail = device.rstrip('\\').rsplit('HarddiskVolumeShadowCopy', 1)
        copies.append({'shadow_id': sid, 'set_id': s.get('set_id') or w.get('Set') or '',
                       'number': int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else None,
                       'created': w.get('At') or s.get('created') or '', 'device': device, 'volume': letter,
                       'store_bytes': s.get('store_bytes', 0), 'extents': s.get('extents', []),
                       'client_accessible': bool(w.get('ClientAccessible')), 'persistent': bool(w.get('Persistent')),
                       'originating_machine': s.get('originating_machine', ''),
                       'attributes': s.get('attributes', []), 'readable': s.get('readable', False),
                       'problems': s.get('problems', []),
                       'in_catalog': bool(s), 'in_wmi': bool(w)})
    copies.sort(key=lambda c: c['created'])
    return copies, catalog_bytes, note


if __name__ == '__main__':
    if sys.argv[1:2] == ['--copies']:
        cps, cat, note = shadow_copies(sys.argv[2] if len(sys.argv) > 2 else 'C')
        for c in cps:
            print(c['number'], c['created'], c['shadow_id'], c['store_bytes'], len(c['extents']),
                  'cat' if c['in_catalog'] else '-', 'wmi' if c['in_wmi'] else '-')
        print('catalog', cat, 'sum', sum(c['store_bytes'] for c in cps) + cat, note)
        sys.exit(0)
    for v in (sys.argv[1:] or ['C']):
        lay = volume_layout(v)
        ext = lay.pop('extents')
        print(v, json.dumps(lay))
        for kind in ('mft', 'usn', 'vss'):
            k = [e for e in ext if e[0] == kind]
            print('  %s: %d runs, %d bytes, first at %s' % (kind, len(k), sum(e[2] for e in k),
                                                         k[0][1] if k else '-'))
