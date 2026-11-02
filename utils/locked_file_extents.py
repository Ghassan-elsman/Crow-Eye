r"""Copy a file Windows holds open by reading its clusters from the volume.

A database a service keeps open - SRUDB.dat (the SRUM service), a hive, an
event log - refuses every open that asks for its data (Error 32), backup
semantics included. Opening it for its ATTRIBUTES only is not subject to that
sharing check, and that is enough to ask NTFS where the file lives
(FSCTL_GET_RETRIEVAL_POINTERS). The clusters are then read from \\.\C: and
written out in file order, truncated to the file's size.

Nothing on the machine changes: no snapshot, no service stopped, no handle
with data access. It needs administrator rights (the volume read).

What it reads is the file as it is on disk at that moment. A live database
can be mid-write, which is why its logs are copied the same way and replayed
(SRUM: esentutl /r) before it is parsed.

Declined, with a reason, where the clusters are not the file's bytes:
compressed and EFS-encrypted files, files stored inside their MFT record
(resident: no extents), and volumes that are not NTFS.
"""

import ctypes
import os
import struct
import sys

FILE_READ_ATTRIBUTES = 0x80
GENERIC_READ = 0x80000000
FILE_SHARE_ALL = 0x7
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FSCTL_GET_RETRIEVAL_POINTERS = 0x00090073
ERROR_MORE_DATA = 234
ERROR_HANDLE_EOF = 38
FILE_ATTRIBUTE_COMPRESSED = 0x800
FILE_ATTRIBUTE_ENCRYPTED = 0x4000
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

_CHUNK = 4 * 1024 * 1024
_k32 = None


class ExtentCopyError(OSError):
    """The file could not be copied by its extents; the message says why."""


def _kernel32():
    global _k32
    if _k32 is None:
        import ctypes.wintypes as wt
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wt.HANDLE
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                                  wt.DWORD, wt.DWORD, wt.HANDLE]
        k.DeviceIoControl.restype = wt.BOOL
        k.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                      ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                      ctypes.c_void_p]
        k.GetFileSizeEx.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
        k.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                               ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
        k.SetFilePointerEx.argtypes = [wt.HANDLE, ctypes.c_longlong,
                                       ctypes.POINTER(ctypes.c_longlong), wt.DWORD]
        k.GetFileAttributesW.restype = wt.DWORD
        k.GetFileAttributesW.argtypes = [wt.LPCWSTR]
        k.CloseHandle.argtypes = [wt.HANDLE]
        _k32 = k
    return _k32


def _invalid(h):
    return h is None or h == ctypes.c_void_p(-1).value


def _volume_of(path):
    """'C:' for C:\\..., else None (UNC, device or relative paths)."""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if len(drive) == 2 and drive[1] == ":":
        return drive.upper()
    return None


def _volume_facts(drive):
    """(file system name, bytes per cluster) of ``drive``."""
    import ctypes.wintypes as wt
    k = _kernel32()
    fs = ctypes.create_unicode_buffer(32)
    if not k.GetVolumeInformationW(drive + "\\", None, 0, None, None, None, fs, 32):
        raise ExtentCopyError(ctypes.get_last_error(), "cannot read the volume information of %s" % drive)
    spc, bps, free, total = wt.DWORD(), wt.DWORD(), wt.DWORD(), wt.DWORD()
    if not k.GetDiskFreeSpaceW(drive + "\\", ctypes.byref(spc), ctypes.byref(bps),
                               ctypes.byref(free), ctypes.byref(total)):
        raise ExtentCopyError(ctypes.get_last_error(), "cannot read the cluster size of %s" % drive)
    return fs.value, spc.value * bps.value


def file_extents(path):
    """``(size, [(vcn, cluster_count, lcn), ...])`` for ``path``; lcn -1 is sparse."""
    import ctypes.wintypes as wt
    k = _kernel32()
    h = k.CreateFileW(path, FILE_READ_ATTRIBUTES, FILE_SHARE_ALL, None, OPEN_EXISTING,
                      FILE_FLAG_BACKUP_SEMANTICS, None)
    if _invalid(h):
        raise ExtentCopyError(ctypes.get_last_error(), "cannot open %s for its attributes" % path)
    try:
        size = ctypes.c_longlong()
        if not k.GetFileSizeEx(h, ctypes.byref(size)):
            raise ExtentCopyError(ctypes.get_last_error(), "cannot read the size of %s" % path)
        extents, vcn = [], 0
        out = ctypes.create_string_buffer(64 * 1024)
        while True:
            inb = struct.pack("<q", vcn)
            got = wt.DWORD()
            ok = k.DeviceIoControl(h, FSCTL_GET_RETRIEVAL_POINTERS, inb, len(inb),
                                   out, len(out), ctypes.byref(got), None)
            err = ctypes.get_last_error()
            if not ok and err == ERROR_HANDLE_EOF:
                if size.value == 0:
                    return 0, []
                raise ExtentCopyError(err, "%s is stored inside its MFT record (no clusters to read)" % path)
            if not ok and err != ERROR_MORE_DATA:
                raise ExtentCopyError(err, "cannot read the cluster map of %s" % path)
            count, start = struct.unpack_from("<I4xq", out.raw, 0)
            prev = start
            for i in range(count):
                next_vcn, lcn = struct.unpack_from("<qq", out.raw, 16 + 16 * i)
                extents.append((prev, next_vcn - prev, lcn))
                prev = next_vcn
            if ok or count == 0:
                return size.value, extents
            vcn = prev
    finally:
        k.CloseHandle(h)


def copy_by_extents(path, dest):
    """Copy ``path`` to ``dest`` from its clusters. Returns the bytes written.

    Raises ExtentCopyError with the reason when the file cannot be copied this
    way; ``dest`` is removed then, so a failed copy never looks like evidence.
    """
    if sys.platform != "win32":
        raise ExtentCopyError(0, "reading a file by its clusters is implemented for Windows only")
    import ctypes.wintypes as wt
    k = _kernel32()
    drive = _volume_of(path)
    if not drive:
        raise ExtentCopyError(0, "%s is not on a local drive letter" % path)
    attrs = k.GetFileAttributesW(path)
    if attrs == INVALID_FILE_ATTRIBUTES:
        raise ExtentCopyError(ctypes.get_last_error(), "cannot read the attributes of %s" % path)
    if attrs & FILE_ATTRIBUTE_COMPRESSED:
        raise ExtentCopyError(0, "%s is NTFS-compressed; its clusters are not its bytes" % path)
    if attrs & FILE_ATTRIBUTE_ENCRYPTED:
        raise ExtentCopyError(0, "%s is EFS-encrypted; its clusters are not its bytes" % path)
    fs_name, cluster = _volume_facts(drive)
    if fs_name.upper() != "NTFS":
        raise ExtentCopyError(0, "%s is on a %s volume; only NTFS cluster maps are read" % (path, fs_name))
    size, extents = file_extents(path)

    vol = k.CreateFileW("\\\\.\\" + drive, GENERIC_READ, 0x3, None, OPEN_EXISTING, 0, None)
    if _invalid(vol):
        raise ExtentCopyError(ctypes.get_last_error(),
                              "cannot open volume %s for reading (administrator rights are needed)" % drive)
    written = 0
    try:
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        buf = ctypes.create_string_buffer(_CHUNK)
        with open(dest, "wb") as out:
            for _vcn, count, lcn in extents:
                if written >= size:
                    break
                want = min(count * cluster, size - written)
                if lcn == -1:                       # sparse run: never written, reads as zeros
                    out.write(b"\0" * want)
                    written += want
                    continue
                # Whole clusters from the volume (aligned reads); the tail of
                # the last one is cut by the truncate below.
                left = count * cluster
                if not k.SetFilePointerEx(vol, lcn * cluster, None, 0):
                    raise ExtentCopyError(ctypes.get_last_error(), "cannot seek volume %s" % drive)
                while left > 0:
                    n = min(left, _CHUNK)
                    got = wt.DWORD()
                    if not k.ReadFile(vol, buf, n, ctypes.byref(got), None):
                        raise ExtentCopyError(ctypes.get_last_error(), "cannot read volume %s" % drive)
                    if got.value == 0:
                        raise ExtentCopyError(0, "volume %s ended inside %s" % (drive, path))
                    out.write(buf.raw[:got.value])
                    left -= got.value
                written += want
            out.truncate(size)
        if os.path.getsize(dest) != size:
            raise ExtentCopyError(0, "copied %d of %d bytes of %s" % (os.path.getsize(dest), size, path))
        return size
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    finally:
        k.CloseHandle(vol)
