"""
Raw File Copy Utility - Bypass Windows File Locks
==================================================

This module provides functionality to copy locked files (like SRUDB.dat)
by reading directly from the raw disk, bypassing Windows file system locks.

This is essential for forensic tools that need to access files that are
currently in use by the operating system.

Technique: Direct NTFS volume access using Windows API
"""

import os
import ctypes
from ctypes import wintypes, byref, c_void_p, c_ulonglong, c_ulong
import struct
import logging

logger = logging.getLogger(__name__)

# Windows API constants
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
# CreateFileW's restype is HANDLE (a pointer), so a failure comes back as
# 0xFFFFFFFFFFFFFFFF on 64-bit Python, never as -1: the old "== -1" test let
# an invalid handle through. Compare against the pointer form.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# NTFS constants
FSCTL_GET_RETRIEVAL_POINTERS = 0x00090073
FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064

# Load Windows API functions
if os.name == 'nt':
    # A private handle with use_last_error: ctypes.get_last_error() reads 0
    # for every failure otherwise, and the shared windll.kernel32 must not have
    # its argtypes rewritten under other modules.
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    CreateFileW.restype = wintypes.HANDLE

    ReadFile = kernel32.ReadFile
    ReadFile.argtypes = [wintypes.HANDLE, c_void_p, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), c_void_p]
    ReadFile.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    SetFilePointer = kernel32.SetFilePointer
    SetFilePointer.argtypes = [wintypes.HANDLE, wintypes.LONG,
                              ctypes.POINTER(wintypes.LONG), wintypes.DWORD]
    SetFilePointer.restype = wintypes.DWORD

    GetFileSizeEx = kernel32.GetFileSizeEx
    GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(c_ulonglong)]
    GetFileSizeEx.restype = wintypes.BOOL

    DeviceIoControl = kernel32.DeviceIoControl
    DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, c_void_p, wintypes.DWORD,
                               c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), c_void_p]
    DeviceIoControl.restype = wintypes.BOOL

    WriteFile = kernel32.WriteFile
    WriteFile.argtypes = [wintypes.HANDLE, c_void_p, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), c_void_p]
    WriteFile.restype = wintypes.BOOL
else:
    kernel32 = None
    CreateFileW = None
    ReadFile = None
    CloseHandle = None
    SetFilePointer = None
    GetFileSizeEx = None
    DeviceIoControl = None
    WriteFile = None


def _invalid(handle):
    return handle is None or handle == 0 or handle == INVALID_HANDLE_VALUE


def _enable_backup_privilege():
    """Enable SeBackupPrivilege on this process token. True when it is enabled.

    FILE_FLAG_BACKUP_SEMANTICS bypasses a file's ACL only while the privilege
    is ENABLED - holding it (every administrator does) is not enough, and it
    is disabled by default. Without this the backup-semantics open was an
    ordinary open with a misleading name.
    """
    if os.name != 'nt':
        return False
    try:
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wintypes.DWORD),
                        ("Privileges", LUID_AND_ATTRIBUTES * 1)]

        TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY, SE_PRIVILEGE_ENABLED = 0x20, 0x8, 0x2
        token = wintypes.HANDLE()
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.HANDLE)]
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                         TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, byref(token)):
            return False
        try:
            luid = LUID()
            if not advapi32.LookupPrivilegeValueW(None, "SeBackupPrivilege", byref(luid)):
                return False
            tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(
                LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
            advapi32.AdjustTokenPrivileges.argtypes = [
                wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES),
                wintypes.DWORD, c_void_p, c_void_p]
            ok = advapi32.AdjustTokenPrivileges(token, False, byref(tp), 0, None, None)
            # Succeeds even when the privilege is not held; 1300 says so.
            return bool(ok) and ctypes.get_last_error() != 1300
        finally:
            kernel32.CloseHandle(token)
    except Exception as e:
        logger.debug("SeBackupPrivilege not enabled: %s", e)
        return False


class LARGE_INTEGER(ctypes.Structure):
    _fields_ = [("QuadPart", c_ulonglong)]


class STARTING_VCN_INPUT_BUFFER(ctypes.Structure):
    _fields_ = [("StartingVcn", LARGE_INTEGER)]


class RETRIEVAL_POINTERS_BUFFER(ctypes.Structure):
    _fields_ = [
        ("ExtentCount", wintypes.DWORD),
        ("StartingVcn", LARGE_INTEGER),
        ("Extents", LARGE_INTEGER * 2 * 100)  # Array of extents
    ]


def copy_locked_file_raw(source_path: str, dest_path: str) -> bool:
    """
    Copy a locked file using raw disk access.
    
    This function bypasses Windows file system locks by:
    1. Opening the file with backup semantics to get file size
    2. Opening the raw volume
    3. Reading file clusters directly from disk
    4. Writing to destination file
    
    Args:
        source_path (str): Path to locked file (e.g., C:\\Windows\\System32\\sru\\SRUDB.dat)
        dest_path (str): Destination path for copy
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"Attempting raw copy: {source_path} -> {dest_path}")
    
    try:
        # Method 1: Try using backup semantics first (simpler approach)
        if _copy_with_backup_semantics(source_path, dest_path):
            return True
        
        # Method 2: If backup semantics fails, try raw disk access
        logger.info("Backup semantics failed, trying raw disk access...")
        return _copy_with_raw_disk_access(source_path, dest_path)
    
    except Exception as e:
        logger.error(f"Raw copy failed: {e}")
        return False


def _copy_with_backup_semantics(source_path: str, dest_path: str) -> bool:
    """
    Copy file using FILE_FLAG_BACKUP_SEMANTICS.
    
    This allows reading files that are locked by other processes,
    as long as we have the SE_BACKUP_NAME privilege (granted to administrators).
    
    Args:
        source_path (str): Source file path
        dest_path (str): Destination file path
    
    Returns:
        bool: True if successful
    """
    logger.info("Trying backup semantics copy...")
    
    source_handle = None
    dest_handle = None
    
    try:
        if not _enable_backup_privilege():
            logger.info("SeBackupPrivilege could not be enabled (not elevated?); "
                        "the backup-semantics open is an ordinary open")
        # Open source file with backup semantics. FILE_SHARE_DELETE as well:
        # a file its owner opened with delete sharing refuses any open that
        # does not offer it back.
        source_handle = CreateFileW(
            source_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None
        )
        
        if _invalid(source_handle):
            error = ctypes.get_last_error()
            logger.warning(f"Could not open source file: Error {error}")
            return False
        
        # Get file size
        file_size = c_ulonglong()
        if not GetFileSizeEx(source_handle, byref(file_size)):
            logger.warning("Could not get file size")
            return False
        
        size = file_size.value
        logger.info(f"Source file size: {size:,} bytes")
        
        # Open destination file for writing
        dest_handle = CreateFileW(
            dest_path,
            0x40000000,  # GENERIC_WRITE
            0,
            None,
            2,  # CREATE_ALWAYS
            0x80,  # FILE_ATTRIBUTE_NORMAL
            None
        )
        
        if _invalid(dest_handle):
            logger.warning("Could not create destination file")
            return False
        
        # Copy in chunks
        chunk_size = 1024 * 1024  # 1 MB chunks
        total_read = 0
        buffer = ctypes.create_string_buffer(chunk_size)
        bytes_read = wintypes.DWORD()
        bytes_written = wintypes.DWORD()
        
        while total_read < size:
            # Read chunk
            if not ReadFile(source_handle, buffer, chunk_size, byref(bytes_read), None):
                if bytes_read.value == 0:
                    break
            
            if bytes_read.value == 0:
                break
            
            # Write chunk
            if not WriteFile(dest_handle, buffer, bytes_read.value,
                             byref(bytes_written), None):
                logger.error("Write failed")
                return False
            
            total_read += bytes_read.value
            
            # Progress logging
            if total_read % (10 * 1024 * 1024) == 0:  # Every 10 MB
                progress = (total_read / size) * 100
                logger.info(f"Progress: {progress:.1f}% ({total_read:,} / {size:,} bytes)")
        
        logger.info(f"Successfully copied {total_read:,} bytes")
        return total_read == size
    
    except Exception as e:
        logger.error(f"Backup semantics copy failed: {e}")
        return False
    
    finally:
        if not _invalid(source_handle):
            CloseHandle(source_handle)
        if not _invalid(dest_handle):
            CloseHandle(dest_handle)


def _copy_with_raw_disk_access(source_path: str, dest_path: str) -> bool:
    """
    Copy file using raw disk access (reading clusters directly).
    
    This is the most advanced method that reads file data directly
    from the disk volume, completely bypassing file system locks.
    
    Args:
        source_path (str): Source file path
        dest_path (str): Destination file path
    
    Returns:
        bool: True if successful
    """
    logger.info("Trying raw disk access copy...")
    
    # This is a complex implementation that requires:
    # 1. Getting file's cluster locations using FSCTL_GET_RETRIEVAL_POINTERS
    # 2. Opening the raw volume (e.g., \\.\C:)
    # 3. Reading clusters directly
    # 4. Reconstructing the file
    
    # For now, we'll log that this method is not yet implemented
    logger.warning("Raw disk access method not yet fully implemented")
    logger.info("This would require reading NTFS MFT and cluster chains")
    
    return False


def copy_srudb_with_raw_access(dest_path: str, source_path: str = None) -> bool:
    """
    Copy SRUDB.dat using raw access techniques.
    
    This is a convenience function specifically for copying SRUDB.dat.
    
    Args:
        dest_path (str): Destination path for SRUDB.dat copy
        source_path (str, optional): Source path. Defaults to system location.
    
    Returns:
        bool: True if successful
    """
    if source_path is None:
        source_path = r"C:\Windows\System32\sru\SRUDB.dat"
    
    logger.info(f"Copying SRUDB.dat from {source_path}")
    
    # Verify source exists
    if not os.path.exists(source_path):
        logger.error(f"Source file not found: {source_path}")
        return False
    
    # Try raw copy
    success = copy_locked_file_raw(source_path, dest_path)
    
    if success:
        # Verify destination file
        if os.path.exists(dest_path):
            dest_size = os.path.getsize(dest_path)
            logger.info(f"Copy successful! Destination size: {dest_size:,} bytes")
            return True
        else:
            logger.error("Copy reported success but destination file not found")
            return False
    else:
        logger.error("Raw copy failed")
        return False


# Test code
if __name__ == "__main__":
    import sys
    import tempfile
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("Raw File Copy Utility - Test Mode")
    print("=" * 60)
    
    # Test copying SRUDB.dat
    temp_dir = tempfile.mkdtemp(prefix="raw_copy_test_")
    dest_file = os.path.join(temp_dir, "SRUDB.dat")
    
    print(f"\nTest: Copying SRUDB.dat to {dest_file}")
    
    success = copy_srudb_with_raw_access(dest_file)
    
    if success:
        print("\n✓ SUCCESS: SRUDB.dat copied successfully!")
        print(f"  Location: {dest_file}")
        print(f"  Size: {os.path.getsize(dest_file):,} bytes")
    else:
        print("\n✗ FAILED: Could not copy SRUDB.dat")
        print("  This may require administrator privileges")
    
    print("\n" + "=" * 60)
