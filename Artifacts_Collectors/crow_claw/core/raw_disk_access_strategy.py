# pylint: disable=no-member
"""
Raw disk access strategy implementation.

This module implements the RawDiskAccessStrategy which uses raw disk access
to read MFT and USN Journal directly from NTFS volumes. This bypasses the
file system layer and requires administrator privileges.
"""

import os
import time
from typing import TYPE_CHECKING

from .access_strategy import FileAccessStrategy
from .artifacts import ArtifactType

if TYPE_CHECKING:
    from .access_result import AccessResult

# A file small enough to live inside its own MFT record has no clusters, and
# FSCTL_GET_RETRIEVAL_POINTERS answers ERROR_HANDLE_EOF (38) for it: the
# cluster reader (utils/locked_file_extents) then declines it with "stored
# inside its MFT record (no clusters to read)". For a small file that is also
# locked, that left every rung failed (Sentinel VM finding F-Q). Its bytes are
# the record's resident $DATA value, and FSCTL_GET_NTFS_FILE_RECORD hands the
# record over by number from the volume handle - no data open of the file.
ERROR_HANDLE_EOF = 38
FSCTL_GET_NTFS_FILE_RECORD = 0x00090068
_ATTR_ATTRIBUTE_LIST = 0x20
_ATTR_DATA = 0x80
_ATTR_END = 0xFFFFFFFF
_ATTR_FLAG_COMPRESSED = 0x0001
_ATTR_FLAG_ENCRYPTED = 0x4000
_RECORD_IN_USE = 0x0001
_RECORD_NUMBER_MASK = 0xFFFFFFFFFFFF


class ResidentReadError(OSError):
    """The file's resident data could not be read; the message says why."""


def resident_data(record, sequence=None):
    """The unnamed $DATA value of one MFT FILE record, when it is resident.

    `record` is the record as FSCTL_GET_NTFS_FILE_RECORD returns it, with the
    update-sequence fixups already applied (measured: a 612-byte value that
    crosses the first sector's last two bytes reads back byte for byte).
    `sequence` is the sequence number the file's reference carries; a record
    with another one has been reused by a different file since, and its bytes
    are not this file's. Raises ResidentReadError with the reason otherwise.
    """
    import struct
    if len(record) < 0x18 or record[:4] != b"FILE":
        raise ResidentReadError(0, "the MFT record is not a FILE record")
    flags = struct.unpack_from("<H", record, 0x16)[0]
    if not flags & _RECORD_IN_USE:
        raise ResidentReadError(0, "the MFT record is not in use")
    if sequence is not None and struct.unpack_from("<H", record, 0x10)[0] != sequence:
        raise ResidentReadError(0, "the MFT record was reused by another file (sequence differs)")
    offset = struct.unpack_from("<H", record, 0x14)[0]
    listed = False
    while offset + 16 <= len(record):
        kind, length = struct.unpack_from("<II", record, offset)
        if kind == _ATTR_END:
            break
        if length < 16 or offset + length > len(record):
            raise ResidentReadError(0, "the MFT record's attributes are malformed")
        non_resident, name_length = record[offset + 8], record[offset + 9]
        attr_flags = struct.unpack_from("<H", record, offset + 0x0C)[0]
        if kind == _ATTR_ATTRIBUTE_LIST:
            listed = True
        if kind == _ATTR_DATA and name_length == 0:
            if non_resident:
                raise ResidentReadError(0, "the file's $DATA is not resident")
            if attr_flags & (_ATTR_FLAG_COMPRESSED | _ATTR_FLAG_ENCRYPTED):
                raise ResidentReadError(0, "the file's resident $DATA is compressed or encrypted")
            value_length, value_offset = struct.unpack_from("<IH", record, offset + 0x10)
            if value_offset + value_length > length:
                raise ResidentReadError(0, "the resident $DATA runs past its attribute")
            start = offset + value_offset
            return bytes(record[start:start + value_length])
        offset += length
    if listed:
        raise ResidentReadError(0, "the file's $DATA is in an extension record ($ATTRIBUTE_LIST), not read")
    raise ResidentReadError(0, "the MFT record has no unnamed $DATA attribute")


def copy_resident_data(path, dest):
    """Copy a resident file to `dest` from its MFT record. Returns the bytes written.

    Opens the file for its attributes only (not subject to the sharing check
    a locked file refuses data opens with) to learn its file reference and
    size, then asks the volume for that record. Needs administrator rights
    (the volume handle). `dest` is removed on any failure, so a failed copy
    never looks like evidence.
    """
    import ctypes
    import ctypes.wintypes as wt
    import struct
    import sys
    if sys.platform != "win32":
        raise ResidentReadError(0, "reading a file from its MFT record is implemented for Windows only")
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not (len(drive) == 2 and drive[1] == ":"):
        raise ResidentReadError(0, "%s is not on a local drive letter" % path)

    class _Info(ctypes.Structure):
        _fields_ = [("attributes", wt.DWORD), ("created", wt.FILETIME),
                    ("accessed", wt.FILETIME), ("written", wt.FILETIME),
                    ("serial", wt.DWORD), ("size_high", wt.DWORD),
                    ("size_low", wt.DWORD), ("links", wt.DWORD),
                    ("index_high", wt.DWORD), ("index_low", wt.DWORD)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wt.HANDLE
    k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                              wt.DWORD, wt.DWORD, wt.HANDLE]
    k.GetFileInformationByHandle.restype = wt.BOOL
    k.GetFileInformationByHandle.argtypes = [wt.HANDLE, ctypes.POINTER(_Info)]
    k.DeviceIoControl.restype = wt.BOOL
    k.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                  ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                  ctypes.c_void_p]
    k.CloseHandle.argtypes = [wt.HANDLE]
    invalid = ctypes.c_void_p(-1).value

    handle = k.CreateFileW(path, 0x80, 0x7, None, 3, 0x02000000, None)    # attributes only
    if handle is None or handle == invalid:
        raise ResidentReadError(ctypes.get_last_error(), "cannot open %s for its attributes" % path)
    try:
        info = _Info()
        if not k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ResidentReadError(ctypes.get_last_error(), "cannot read the file reference of %s" % path)
    finally:
        k.CloseHandle(handle)
    reference = (info.index_high << 32) | info.index_low
    size = (info.size_high << 32) | info.size_low
    number = reference & _RECORD_NUMBER_MASK

    volume = k.CreateFileW("\\\\.\\" + drive, 0x80000000, 0x3, None, 3, 0, None)
    if volume is None or volume == invalid:
        raise ResidentReadError(ctypes.get_last_error(),
                                "cannot open volume %s for reading (administrator rights are needed)" % drive)
    try:
        out = ctypes.create_string_buffer(12 + 65536)
        got = wt.DWORD()
        request = struct.pack("<q", number)
        if not k.DeviceIoControl(volume, FSCTL_GET_NTFS_FILE_RECORD, request, len(request),
                                 out, len(out), ctypes.byref(got), None):
            raise ResidentReadError(ctypes.get_last_error(), "cannot read the MFT record of %s" % path)
    finally:
        k.CloseHandle(volume)
    returned, length = struct.unpack_from("<qI", out.raw, 0)
    # Asked for a record not in use, NTFS returns the nearest one below it.
    if returned & _RECORD_NUMBER_MASK != number:
        raise ResidentReadError(0, "NTFS returned MFT record %d for %d (%s)"
                                % (returned & _RECORD_NUMBER_MASK, number, path))
    data = resident_data(out.raw[12:12 + length], sequence=reference >> 48)
    if len(data) != size:
        raise ResidentReadError(0, "the resident $DATA of %s is %d bytes, the file %d"
                                % (path, len(data), size))
    try:
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest, "wb") as handle_out:
            handle_out.write(data)
        if os.path.getsize(dest) != size:
            raise ResidentReadError(0, "wrote %d of %d bytes of %s" % (os.path.getsize(dest), size, path))
        return size
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise


class RawDiskAccessStrategy(FileAccessStrategy):
    r"""Raw disk access strategy for MFT and USN Journal.
    
    This strategy uses raw disk access via device paths (e.g., \\.\C:) to
    read MFT and USN Journal directly from NTFS volumes. This is necessary
    because these artifacts are locked by the file system and cannot be
    accessed through standard file operations.
    
    Requirements:
        - 3.1: Use raw disk access for MFT artifacts
        - 3.2: Use raw disk access for USN Journal artifacts
        - 3.3: Require admin privileges
        - 3.5: Read data in chunks to avoid memory issues
    """
    
    def __init__(self):
        """Initialize the raw disk access strategy.
        
        Checks if win32file is available for raw disk operations.
        """
        self._win32file_available = False
        try:
            import win32file
            self._win32file_available = True
        except ImportError:
            pass
        
        # Callbacks for progress reporting
        self.progress_callback = None
        self.status_callback = None
    
    def set_progress_callback(self, callback):
        """Set callback for progress updates during long operations."""
        self.progress_callback = callback
    
    def set_status_callback(self, callback):
        """Set callback for status messages during operations."""
        self.status_callback = callback
    
    def _report_progress(self, message: str):
        """Report progress if callback is set."""
        if self.status_callback:
            self.status_callback(message)
    
    def _check_admin_privileges(self) -> bool:
        """Check if the current process has administrator privileges.
        
        Returns:
            True if running with admin privileges, False otherwise
            
        Requirements:
            - 3.3: Check admin privileges before raw disk access
        """
        if os.name == 'nt':
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        else:
            try:
                return getattr(os, 'getuid', lambda: 1)() == 0
            except:
                return False
    
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        """Check if this strategy can handle the file.
        
        Raw disk access is only used for MFT and USN_JOURNAL artifact types.
        Also checks if win32file is available and admin privileges are present.
        
        Args:
            file_path: Path to the file to access
            artifact_type: Type of artifact (must be "mft" or "usn_journal")
            
        Returns:
            True if this is an MFT or USN_JOURNAL artifact and prerequisites are met
            
        Requirements:
            - 3.1: Handle MFT artifact type
            - 3.2: Handle USN_JOURNAL artifact type
        """
        # DEBUG: Log can_handle call
        self._report_progress(f"[RAW_DISK] can_handle called: file_path={file_path}, artifact_type={artifact_type}")

        # Check if admin privileges are present (the volume read needs them)
        if not self._check_admin_privileges():
            self._report_progress(f"[RAW_DISK] Cannot handle: admin privileges not present")
            return False

        artifact_type_lower = (artifact_type or "").lower()
        if artifact_type_lower in ["mft", "usn", "usn_journal"]:
            # The $MFT and journal readers use win32file.
            if not self._win32file_available:
                self._report_progress(f"[RAW_DISK] Cannot handle: win32file not available")
                return False
            return True
        # Any other file on a local drive is read by its clusters
        # (utils/locked_file_extents): a database a service holds open - SRUM's
        # SRUDB.dat - refuses every data open, and this was only ever offered
        # for the MFT and journal, so with no current shadow copy nothing
        # could read it, even elevated.
        can_handle_result = os.name == 'nt' and bool(self._extract_drive_letter(file_path)) \
            and not file_path.startswith("\\\\")
        self._report_progress(f"[RAW_DISK] can_handle result: {can_handle_result} (artifact_type_lower={artifact_type_lower})")
        return can_handle_result
    
    def access_file(self, file_path: str, dest_path: str) -> 'AccessResult':
        r"""Attempt to access and copy the file using raw disk access.
        
        For MFT and USN Journal, routes to specialized methods.
        For other files, opens the device handle and reads in chunks.
        
        Args:
            file_path: Source file path (e.g., \\.\C:\$MFT)
            dest_path: Destination file path
            
        Returns:
            AccessResult containing success status, file size, and any errors
            
        Requirements:
            - 3.1: Use raw disk access via device path
            - 3.5: Read in chunks to avoid memory issues
            - 12.4: Properly close device handles
        """
        from .access_result import AccessResult
        
        start_time = time.time()
        
        # DEBUG: Log access_file call
        self._report_progress(f"[RAW_DISK] access_file CALLED: file_path={file_path}, dest_path={dest_path}")

        is_ntfs_metafile = ("$MFT" in file_path or "$UsnJrnl" in file_path
                            or "UsnJrnl" in file_path)
        # Check prerequisites (win32file only for the $MFT / journal readers)
        if is_ntfs_metafile and not self._win32file_available:
            duration = time.time() - start_time
            error_msg = "win32file module not available (pywin32 not installed)"
            self._report_progress(f"[RAW_DISK] access_file ERROR: {error_msg}")
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
        
        if not self._check_admin_privileges():
            duration = time.time() - start_time
            error_msg = "Administrator privileges required for raw disk access"
            self._report_progress(f"[RAW_DISK] access_file ERROR: {error_msg}")
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
        
        # Extract drive letter
        drive_letter = self._extract_drive_letter(file_path)
        self._report_progress(f"[RAW_DISK] Extracted drive letter: {drive_letter}")
        if not drive_letter:
            duration = time.time() - start_time
            error_msg = "Could not extract drive letter from path"
            self._report_progress(f"[RAW_DISK] access_file ERROR: {error_msg}")
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
        
        # Route to specialized methods for MFT and USN Journal
        self._report_progress(f"[RAW_DISK] Checking file_path: {file_path}")
        self._report_progress(f"[RAW_DISK] $MFT in file_path: {'$MFT' in file_path}")
        self._report_progress(f"[RAW_DISK] \\$MFT in file_path: {'\\$MFT' in file_path}")
        self._report_progress(f"[RAW_DISK] $UsnJrnl in file_path: {'$UsnJrnl' in file_path}")
        self._report_progress(f"[RAW_DISK] UsnJrnl in file_path: {'UsnJrnl' in file_path}")
        
        if "$MFT" in file_path or "\\$MFT" in file_path:
            self._report_progress(f"[RAW_DISK] Routing to read_mft for drive {drive_letter}")
            return self.read_mft(drive_letter, dest_path)
        elif "$UsnJrnl" in file_path or "UsnJrnl" in file_path:
            self._report_progress(f"[RAW_DISK] Routing to read_usn_journal for drive {drive_letter}")
            return self.read_usn_journal(drive_letter, dest_path)
        
        # Any other file: read by its clusters. This used to open the volume
        # and copy it from sector 0 - the whole disk into the destination,
        # never the file asked for (unreachable only because can_handle
        # turned every other file away).
        try:
            from utils.locked_file_extents import copy_by_extents
        except ImportError as e:
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=f"Cluster reader unavailable: {e}",
                duration_seconds=time.time() - start_time,
                status="failed"
            )
        try:
            try:
                size = copy_by_extents(file_path, dest_path)
                how = "by its clusters"
            except OSError as e:
                # ERROR_HANDLE_EOF from the cluster map: the file is stored
                # inside its MFT record, so its bytes are read from there.
                if getattr(e, "errno", 0) != ERROR_HANDLE_EOF:
                    raise
                size = copy_resident_data(file_path, dest_path)
                how = "from its MFT record (resident data)"
            self._report_progress(f"[RAW_DISK] Read {size:,} bytes of {file_path} {how}")
            return AccessResult(
                success=True,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                file_size=size,
                duration_seconds=time.time() - start_time,
                status="success"
            )
        except OSError as e:
            reason = e.strerror or str(e)
            if getattr(e, "errno", 0):
                reason = f"{reason} (code {e.errno})"
            # errno 2 on a destination past MAX_PATH reads as if the SOURCE
            # were missing; say which path was refused (decision 168).
            full = os.path.abspath(dest_path)
            if getattr(e, "errno", 0) == 2 and len(full) >= 260 \
                    and not full.startswith("\\\\?\\"):
                reason = (f"destination path too long ({len(full)} characters, "
                          f"MAX_PATH is 260): {reason}")
            self._report_progress(f"[RAW_DISK] Cluster read failed: {reason}")
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=f"Raw disk read failed: {reason}",
                duration_seconds=time.time() - start_time,
                status="failed"
            )
    
    def _extract_drive_letter(self, file_path: str) -> str:
        r"""Extract drive letter from file path.
        
        Handles various path formats:
        - \\.\C:\$MFT -> C
        - C:\$MFT -> C
        - C:\$Extend\$UsnJrnl:$J -> C
        
        Args:
            file_path: File path to extract drive letter from
            
        Returns:
            Drive letter (e.g., "C") or empty string if not found
        """
        # Remove device path prefix if present
        path = file_path.replace("\\\\.\\", "")
        
        # Check if path starts with drive letter
        if len(path) >= 2 and path[1] == ':':
            return path[0].upper()
        
        return ""
    
    
    def read_usn_journal(self, drive_letter: str, dest_path: str) -> 'AccessResult':
        """Read USN Journal using FSCTL_QUERY_USN_JOURNAL control code.
        
        Reads the Update Sequence Number (USN) Journal from the specified drive
        using the FSCTL_QUERY_USN_JOURNAL control code. The USN Journal tracks
        changes to files and directories on NTFS volumes.
        
        Args:
            drive_letter: Drive letter (e.g., "C")
            dest_path: Destination file path to write USN Journal data
            
        Returns:
            AccessResult containing success status, file size, and any errors
            
        Requirements:
            - 3.2: Read USN Journal using FSCTL_QUERY_USN_JOURNAL
            - 3.5: Read in chunks to avoid memory issues
            - 12.4: Properly close device handles in finally blocks
        """
        from .access_result import AccessResult
        import time
        import struct
        
        start_time = time.time()
        
        # Check prerequisites
        if not self._win32file_available:
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error="win32file module not available (pywin32 not installed)",
                duration_seconds=duration,
                status="failed"
            )
        
        if not self._check_admin_privileges():
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error="Administrator privileges required for raw disk access",
                duration_seconds=duration,
                status="failed"
            )
        
        import win32file
        import pywintypes
        import winioctlcon
        
        volume_handle = None
        output_file = None
        
        try:
            # Construct volume path: \\.\C:
            volume_path = f"\\\\.\\{drive_letter}:"
            
            # Open volume handle with read access
            volume_handle = win32file.CreateFile(
                volume_path,
                win32file.GENERIC_READ,
                win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )
            
            # Query USN Journal information using FSCTL_QUERY_USN_JOURNAL
            # This returns a USN_JOURNAL_DATA structure
            try:
                usn_journal_data = win32file.DeviceIoControl(
                    volume_handle,
                    winioctlcon.FSCTL_QUERY_USN_JOURNAL,
                    None,
                    1024,
                    None
                )
            except pywintypes.error as e:
                # USN Journal might not be enabled
                duration = time.time() - start_time
                return AccessResult(
                    success=False,
                    source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                    dest_path=dest_path,
                    strategy_used="raw_disk",
                    error=f"Failed to query USN Journal (code {e.winerror}): {e.strerror}. Journal may not be enabled.",
                    duration_seconds=duration,
                    status="failed"
                )
            
            # Parse USN_JOURNAL_DATA structure
            # Structure: UsnJournalID (8 bytes), FirstUsn (8 bytes), NextUsn (8 bytes), 
            #            LowestValidUsn (8 bytes), MaxUsn (8 bytes), MaximumSize (8 bytes), 
            #            AllocationDelta (8 bytes)
            if len(usn_journal_data) < 56:
                duration = time.time() - start_time
                return AccessResult(
                    success=False,
                    source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                    dest_path=dest_path,
                    strategy_used="raw_disk",
                    error="Invalid USN Journal data structure",
                    duration_seconds=duration,
                    status="failed"
                )
            
            # Extract USN range
            usn_journal_id = struct.unpack('<Q', usn_journal_data[0:8])[0]
            first_usn = struct.unpack('<Q', usn_journal_data[8:16])[0]
            next_usn = struct.unpack('<Q', usn_journal_data[16:24])[0]
            lowest_valid_usn = struct.unpack('<Q', usn_journal_data[24:32])[0]
            
            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
            
            # Open output file for writing
            self._report_progress(f"[USN_DEBUG] Opening output file: {dest_path}")
            self._report_progress(f"[USN_DEBUG] Opening file in mode: 'wb'")
            output_file = open(dest_path, 'wb')
            self._report_progress(f"[USN_DEBUG] Output file opened successfully")
            self._report_progress(f"[USN_DEBUG] File object: {output_file}")
            self._report_progress(f"[USN_DEBUG] File name: {output_file.name}")
            
            # Read USN records using FSCTL_READ_USN_JOURNAL
            # Start from the lowest valid USN
            current_usn = lowest_valid_usn
            total_bytes_read = 0
            chunk_size = 64 * 1024  # 64KB buffer for USN records
            max_iterations = 10000  # Prevent infinite loops
            iteration_count = 0
            timeout_seconds = 300  # 5 minute timeout
            collection_start = time.time()
            last_progress_report = 0
            progress_interval = 100  # Report every 100 iterations
            
            self._report_progress(f"Reading USN Journal from {drive_letter}: (this may take 2-5 minutes)")
            
            # DEBUG: Log initial USN range
            self._report_progress(f"[USN_DEBUG] Reading from USN {lowest_valid_usn} to {next_usn}")
            self._report_progress(f"[USN_DEBUG] Journal ID: {usn_journal_id}")
            
            # Create READ_USN_JOURNAL_DATA_V0 structure (40 bytes)
            # Structure: 
            #   StartUsn (8), ReasonMask (4), ReturnOnlyOnClose (4), 
            #   Timeout (8), BytesToWaitFor (8), UsnJournalID (8)
            while current_usn < next_usn and iteration_count < max_iterations:
                try:
                    # Check timeout
                    if time.time() - collection_start > timeout_seconds:
                        break
                    
                    iteration_count += 1
                    
                    # Build input buffer for FSCTL_READ_USN_JOURNAL
                    # We use READ_USN_JOURNAL_DATA_V0 which is 40 bytes
                    read_usn_data = struct.pack(
                        '<QIIQQQ',
                        current_usn,        # StartUsn
                        0xFFFFFFFF,         # ReasonMask (all reasons)
                        0,                  # ReturnOnlyOnClose
                        0,                  # Timeout
                        0,                  # BytesToWaitFor (New field added to fix 1784)
                        usn_journal_id      # UsnJournalID
                    )
                    
                    # FIXED: Use a more robust buffer handling for FSCTL_READ_USN_JOURNAL
                    # ERROR 1784 often occurs due to alignment or size issues.
                    try:
                        # Use a bytearray buffer for better compatibility
                        out_buffer = win32file.AllocateReadBuffer(chunk_size)
                        
                        bytes_returned = win32file.DeviceIoControl(
                            volume_handle,
                            winioctlcon.FSCTL_READ_USN_JOURNAL,
                            read_usn_data,
                            out_buffer
                        )
                        
                        # Handle the returned data (DeviceIoControl returns bytes for AllocateReadBuffer)
                        usn_records = bytes_returned
                    except pywintypes.error as e:
                        if e.winerror == 1784: # ERROR_INVALID_USER_BUFFER
                            # Fallback to direct call if AllocateReadBuffer fails
                            usn_records = win32file.DeviceIoControl(
                                volume_handle,
                                winioctlcon.FSCTL_READ_USN_JOURNAL,
                                read_usn_data,
                                chunk_size,
                                None
                            )
                        else:
                            raise
                    
                    if not usn_records or len(usn_records) <= 8:
                        # No more records or only NextUsn returned
                        break
                    
                    # First 8 bytes contain the next USN to read
                    next_usn_to_read = struct.unpack('<Q', usn_records[0:8])[0]
                    
                    # Write records to output file (skip first 8 bytes which is NextUsn)
                    if len(usn_records) > 8:
                        data_to_write = usn_records[8:]
                        try:
                            self._report_progress(f"[USN_DEBUG] Writing {len(data_to_write)} bytes to file")
                            output_file.write(data_to_write)
                            total_bytes_read += len(data_to_write)
                            # Explicitly flush to ensure data is written to disk
                            output_file.flush()
                            self._report_progress(f"[USN_DEBUG] Flush successful, file size now: {output_file.tell()} bytes")
                            
                            # DEBUG: Log write operation
                            if iteration_count <= 5:  # Only log first 5 iterations
                                self._report_progress(f"[USN_DEBUG] Iteration {iteration_count}: wrote {len(data_to_write)} bytes (total: {total_bytes_read} bytes)")
                        except Exception as e:
                            self._report_progress(f"[USN_DEBUG] ERROR writing data: {e}")
                            import traceback
                            self._report_progress(f"[USN_DEBUG] Traceback: {traceback.format_exc()}")
                    else:
                        # DEBUG: Log when no data is written
                        if iteration_count <= 5:
                            self._report_progress(f"[USN_DEBUG] Iteration {iteration_count}: usn_records length = {len(usn_records)}, no data written")
                    
                    # Update current USN for next iteration
                    if next_usn_to_read <= current_usn:
                        # No progress, avoid infinite loop
                        break
                    
                    current_usn = next_usn_to_read
                    
                except pywintypes.error as e:
                    # Check for specific errors
                    if e.winerror == 38:  # ERROR_HANDLE_EOF
                        break
                    elif e.winerror == 1179:  # ERROR_JOURNAL_ENTRY_DELETED
                        # Some entries were deleted, continue from next USN
                        current_usn = next_usn_to_read if 'next_usn_to_read' in locals() else current_usn + 1
                        continue
                    else:
                        raise
            
            # Close handles
            output_file.close()
            output_file = None
            
            win32file.CloseHandle(volume_handle)
            volume_handle = None
            
            # Final progress report
            mb_total = total_bytes_read / (1024 * 1024)
            elapsed = time.time() - collection_start
            self._report_progress(f"USN Journal: Completed - {mb_total:.1f} MB collected in {elapsed:.0f}s ({iteration_count} iterations)")
            
            duration = time.time() - start_time
            
            return AccessResult(
                success=True,
                source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                dest_path=dest_path,
                strategy_used="raw_disk",
                file_size=total_bytes_read,
                duration_seconds=duration,
                status="success"
            )
            
        except pywintypes.error as e:
            # Windows API error
            duration = time.time() - start_time
            error_msg = f"Windows API error (code {e.winerror}): {e.strerror}"
            
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
            
        except Exception as e:
            # Catch-all for unexpected errors
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$Extend\\$UsnJrnl:$J",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=f"Unexpected error: {str(e)}",
                duration_seconds=duration,
                status="failed"
            )
            
        finally:
            # Ensure handles are closed even if an error occurs
            if output_file:
                try:
                    # Explicitly flush before closing to ensure all data is written
                    self._report_progress(f"[USN_DEBUG] Final flush before closing file")
                    output_file.flush()
                    self._report_progress(f"[USN_DEBUG] File size before close: {output_file.tell()} bytes")
                    output_file.close()
                    self._report_progress(f"[USN_DEBUG] File closed successfully")
                except Exception as e:
                    self._report_progress(f"[USN_DEBUG] ERROR in finally block: {e}")
                    import traceback
                    self._report_progress(f"[USN_DEBUG] Traceback: {traceback.format_exc()}")
            
            if volume_handle:
                try:
                    import win32file
                    win32file.CloseHandle(volume_handle)
                except Exception:
                    pass
    
    def requires_admin(self) -> bool:
        """Check if this strategy requires administrator privileges.
        
        Raw disk access requires administrator privileges.
        
        Returns:
            True - raw disk access requires admin privileges
            
        Requirements:
            - 3.3: Require admin privileges for raw disk access
        """
        return True


    def _copy_mft_by_runs(self, device_handle, mft_cluster: int, bytes_per_cluster: int,
                          boot_sector: bytes, dest_path: str):
        """Write the whole $MFT (its data size) to ``dest_path`` by following
        record 0's data runs. Returns the bytes written, or None when the runs
        could not be read - the caller then falls back to the contiguous read."""
        import win32file
        try:
            from utils.ntfs_runs import mft_layout, read_stream
        except ImportError as e:
            self._report_progress(f"MFT: data-run reader unavailable ({e})")
            return None
        clusters_per_record = int.from_bytes(boot_sector[0x40:0x41], 'little', signed=True)
        if clusters_per_record > 0:
            record_size = clusters_per_record * bytes_per_cluster
        else:
            record_size = 1 << (-clusters_per_record)

        def read_at(offset, length):
            win32file.SetFilePointer(device_handle, offset, win32file.FILE_BEGIN)
            _hr, data = win32file.ReadFile(device_handle, length)
            return data

        try:
            runmap, data_size, _allocated = mft_layout(read_at, mft_cluster,
                                                       bytes_per_cluster, record_size)
        except Exception as e:
            self._report_progress(f"MFT: could not read its data runs ({e}); "
                                  f"falling back to a contiguous read")
            return None
        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        chunk = 4 * 1024 * 1024
        written = 0
        last_report = 0
        self._report_progress(f"MFT: {len(runmap.runs)} data run(s), "
                              f"{data_size / (1024 * 1024):.1f} MB to copy")
        with open(dest_path, 'wb') as out:
            while written < data_size:
                n = min(chunk, data_size - written)
                # Whole records only: data_size is a record multiple anyway.
                out.write(read_stream(read_at, runmap, written, n))
                written += n
                if written - last_report >= 64 * 1024 * 1024:
                    self._report_progress(f"MFT: Read {written / (1024 * 1024):.1f} MB so far...")
                    last_report = written
        return written

    def read_mft(self, drive_letter: str, dest_path: str) -> 'AccessResult':
        """Read MFT using raw disk access.

        Reads the Master File Table (MFT) from a fixed NTFS location on the
        specified drive. The MFT is located at a specific offset on NTFS volumes
        and can be read directly using raw disk access.

        Args:
            drive_letter: Drive letter (e.g., "C")
            dest_path: Destination file path to write MFT data

        Returns:
            AccessResult containing success status, file size, and any errors

        Requirements:
            - 3.1: Read MFT from fixed NTFS location
            - 3.5: Read in chunks to avoid memory issues
            - 12.4: Properly close device handles in finally blocks
        """
        from .access_result import AccessResult
        import time

        start_time = time.time()
        
        # DEBUG: Log read_mft entry
        self._report_progress(f"[RAW_DISK] read_mft CALLED: drive_letter={drive_letter}, dest_path={dest_path}")

        # Check prerequisites
        if not self._win32file_available:
            duration = time.time() - start_time
            error_msg = "win32file module not available (pywin32 not installed)"
            self._report_progress(f"[RAW_DISK] read_mft ERROR: {error_msg}")
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$MFT",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )

        if not self._check_admin_privileges():
            duration = time.time() - start_time
            error_msg = "Administrator privileges required for raw disk access"
            self._report_progress(f"[RAW_DISK] read_mft ERROR: {error_msg}")
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$MFT",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )

        import win32file
        import pywintypes

        device_handle = None
        output_file = None

        try:
            # Construct device path: \\.\C:
            device_path = f"\\\\.\\{drive_letter}:"

            # Open device handle with read access and sharing flags
            device_handle = win32file.CreateFile(
                device_path,
                win32file.GENERIC_READ,
                win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )

            # Read the boot sector to get MFT location
            # Boot sector is at offset 0, size 512 bytes
            win32file.SetFilePointer(device_handle, 0, win32file.FILE_BEGIN)
            hr, boot_sector = win32file.ReadFile(device_handle, 512)

            if len(boot_sector) < 512:
                duration = time.time() - start_time
                return AccessResult(
                    success=False,
                    source_path=f"{drive_letter}:\\$MFT",
                    dest_path=dest_path,
                    strategy_used="raw_disk",
                    error="Failed to read boot sector",
                    duration_seconds=duration,
                    status="failed"
                )

            # Parse NTFS boot sector to get MFT location
            # Bytes per sector: offset 0x0B (2 bytes)
            # Sectors per cluster: offset 0x0D (1 byte)
            # MFT cluster number: offset 0x30 (8 bytes)
            bytes_per_sector = int.from_bytes(boot_sector[0x0B:0x0D], byteorder='little')
            sectors_per_cluster = boot_sector[0x0D]
            mft_cluster = int.from_bytes(boot_sector[0x30:0x38], byteorder='little')

            # Calculate MFT offset
            bytes_per_cluster = bytes_per_sector * sectors_per_cluster
            mft_offset = mft_cluster * bytes_per_cluster

            # Copy the $MFT through its own data runs. It is fragmented on any
            # volume in use for a while, and the contiguous read below stops at
            # the first fragment (or copies unrelated clusters after it) - on
            # one C: drive that kept 205,056 of 3.3 million records.
            copied = self._copy_mft_by_runs(device_handle, mft_cluster, bytes_per_cluster,
                                            boot_sector, dest_path)
            if copied is not None:
                win32file.CloseHandle(device_handle)
                device_handle = None
                self._report_progress(f"MFT: Completed - {copied / (1024 * 1024):.1f} MB collected "
                                      f"(all data runs)")
                return AccessResult(
                    success=True,
                    source_path=f"{drive_letter}:\\$MFT",
                    dest_path=dest_path,
                    strategy_used="raw_disk",
                    file_size=copied,
                    duration_seconds=time.time() - start_time,
                    status="success"
                )

            # Seek to MFT location
            win32file.SetFilePointer(device_handle, mft_offset, win32file.FILE_BEGIN)

            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)

            # Open output file for writing
            output_file = open(dest_path, 'wb')

            # Read MFT in chunks
            # Use 64KB chunks for better performance
            chunk_size = 64 * 1024  # 64KB
            total_bytes_read = 0
            # FIXED: Increased from 512MB to 2GB to handle large volumes
            max_mft_size = 2 * 1024 * 1024 * 1024  # 2GB max
            
            consecutive_invalid_records = 0
            max_invalid_records = 100 # Stop after 100 invalid chunks (likely end of MFT or fragmentation)
            
            # Initialize progress tracking variables
            last_progress_report = 0
            progress_interval = 10 * 1024 * 1024  # Report every 10MB
            
            self._report_progress(f"Reading MFT from {drive_letter}: (this may take 1-2 minutes for large drives)")

            while total_bytes_read < max_mft_size:
                try:
                    # Read chunk from device
                    hr, data = win32file.ReadFile(device_handle, chunk_size)

                    if not data:
                        # No more data to read
                        break

                    # Check for MFT record signature "FILE" in the chunk
                    # Every 1024 bytes (MFT record size) should start with 'FILE' or 'BAAD'
                    # We check the first few records in the chunk
                    is_valid_chunk = False
                    for i in range(0, min(len(data), 4096), 1024):
                        if data[i:i+4] in [b'FILE', b'BAAD']:
                            is_valid_chunk = True
                            break
                    
                    if not is_valid_chunk and total_bytes_read > 0:
                        consecutive_invalid_records += 1
                        if consecutive_invalid_records > max_invalid_records:
                            # We've likely hit the end of the MFT fragment or partition
                            self._report_progress(f"MFT: Detected end of MFT fragment at {total_bytes_read / (1024*1024):.1f} MB")
                            break
                    else:
                        consecutive_invalid_records = 0

                    # Check for MFT record signature "FILE" at the start of first chunk
                    if total_bytes_read == 0 and not is_valid_chunk:
                        # Not a valid MFT start
                        duration = time.time() - start_time
                        return AccessResult(
                            success=False,
                            source_path=f"{drive_letter}:\\$MFT",
                            dest_path=dest_path,
                            strategy_used="raw_disk",
                            error="Invalid MFT signature at start cluster",
                            duration_seconds=duration,
                            status="failed"
                        )

                    # Write chunk to output file
                    output_file.write(data)
                    total_bytes_read += len(data)
                    
                    # Report progress periodically
                    if total_bytes_read - last_progress_report >= progress_interval:
                        mb_read = total_bytes_read / (1024 * 1024)
                        self._report_progress(f"MFT: Read {mb_read:.1f} MB so far...")
                        last_progress_report = total_bytes_read

                    # If we read less than chunk_size, we've reached the end
                    if len(data) < chunk_size:
                        break

                except pywintypes.error as e:
                    # Check if this is an EOF error
                    if e.winerror == 38:  # ERROR_HANDLE_EOF
                        break
                    else:
                        raise
            
            # Final progress report
            mb_total = total_bytes_read / (1024 * 1024)
            self._report_progress(f"MFT: Completed - {mb_total:.1f} MB collected")

            # Close handles
            output_file.close()
            output_file = None

            win32file.CloseHandle(device_handle)
            device_handle = None

            duration = time.time() - start_time

            return AccessResult(
                success=True,
                source_path=f"{drive_letter}:\\$MFT",
                dest_path=dest_path,
                strategy_used="raw_disk",
                file_size=total_bytes_read,
                duration_seconds=duration,
                status="success"
            )

        except pywintypes.error as e:
            # Windows API error
            duration = time.time() - start_time
            error_msg = f"Windows API error (code {e.winerror}): {e.strerror}"

            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$MFT",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )

        except Exception as e:
            # Catch-all for unexpected errors
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=f"{drive_letter}:\\$MFT",
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=f"Unexpected error: {str(e)}",
                duration_seconds=duration,
                status="failed"
            )

        finally:
            # Ensure handles are closed even if an error occurs
            if output_file:
                try:
                    output_file.close()
                except Exception:
                    pass

            if device_handle:
                try:
                    import win32file
                    win32file.CloseHandle(device_handle)
                except Exception:
                    pass
