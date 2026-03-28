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
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
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
        
        # Check if win32file is available
        if not self._win32file_available:
            self._report_progress(f"[RAW_DISK] Cannot handle: win32file not available")
            return False
        
        # Check if admin privileges are present
        if not self._check_admin_privileges():
            self._report_progress(f"[RAW_DISK] Cannot handle: admin privileges not present")
            return False
        
        # Check artifact type
        artifact_type_lower = artifact_type.lower()
        can_handle_result = artifact_type_lower in ["mft", "usn_journal"]
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
        
        # Check prerequisites
        if not self._win32file_available:
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
        
        # For other raw disk access (generic)
        import win32file
        import pywintypes
        
        device_handle = None
        output_file = None
        
        try:
            # Construct device path: \\.\C:
            device_path = f"\\\\.\\{drive_letter}:"
            
            # Open device handle with read access and sharing flags
            # GENERIC_READ = 0x80000000
            # FILE_SHARE_READ = 0x00000001
            # FILE_SHARE_WRITE = 0x00000002
            # OPEN_EXISTING = 3
            device_handle = win32file.CreateFile(
                device_path,
                win32file.GENERIC_READ,
                win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )
            
            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
            
            # Open output file for writing
            output_file = open(dest_path, 'wb')
            
            # Read and write in chunks
            # Use 64KB chunks for better performance
            chunk_size = 64 * 1024  # 64KB
            total_bytes_read = 0
            
            while True:
                try:
                    # Read chunk from device
                    hr, data = win32file.ReadFile(device_handle, chunk_size)
                    
                    if not data:
                        # No more data to read
                        break
                    
                    # Write chunk to output file
                    output_file.write(data)
                    total_bytes_read += len(data)
                    
                    # If we read less than chunk_size, we've reached the end
                    if len(data) < chunk_size:
                        break
                        
                except pywintypes.error as e:
                    # Check if this is an EOF error
                    if e.winerror == 38:  # ERROR_HANDLE_EOF
                        break
                    else:
                        raise
            
            # Close handles
            output_file.close()
            output_file = None
            
            win32file.CloseHandle(device_handle)
            device_handle = None
            
            duration = time.time() - start_time
            
            return AccessResult(
                success=True,
                source_path=file_path,
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
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
            
        except PermissionError as e:
            # Permission denied
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw_disk",
                error=f"Permission denied: {str(e)}",
                duration_seconds=duration,
                status="failed"
            )
            
        except OSError as e:
            # Other OS errors
            duration = time.time() - start_time
            error_msg = f"OS error: {str(e)}"
            
            if hasattr(e, 'winerror'):
                error_msg = f"OS error (code {e.winerror}): {str(e)}"
            
            return AccessResult(
                success=False,
                source_path=file_path,
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
                source_path=file_path,
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
