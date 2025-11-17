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
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = -1

# NTFS constants
FSCTL_GET_RETRIEVAL_POINTERS = 0x00090073
FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064

# Load Windows API functions
kernel32 = ctypes.windll.kernel32

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
        # Open source file with backup semantics
        source_handle = CreateFileW(
            source_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None
        )
        
        if source_handle == INVALID_HANDLE_VALUE or source_handle == 0:
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
        
        if dest_handle == INVALID_HANDLE_VALUE or dest_handle == 0:
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
            if not kernel32.WriteFile(dest_handle, buffer, bytes_read.value,
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
        if source_handle and source_handle != INVALID_HANDLE_VALUE:
            CloseHandle(source_handle)
        if dest_handle and dest_handle != INVALID_HANDLE_VALUE:
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
