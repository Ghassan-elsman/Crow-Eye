"""
Crow Eye - Recycle Bin Forensic Parser
=====================================

Advanced Windows Recycle Bin artifact parser for digital forensic investigations.
This module provides comprehensive analysis of Windows $Recycle.Bin folders,
extracting critical metadata from $I files and correlating with $R files for
complete deleted file reconstruction.

Features:
---------
• Multi-Version Support: Windows Vista/7/8/10/11 $I/$R file formats
• Metadata Extraction: Original filename, full path, deletion timestamp, file size
• User Attribution: Correlates deleted files with user SIDs
• File Type Analysis: Identifies file types through binary signature analysis
• Recovery Assessment: Determines file recovery possibility and integrity status
• Database Integration: SQLite storage with comprehensive forensic metadata

Supported Artifacts:
-------------------
• $I Files: Metadata containers with original file information
• $R Files: Actual deleted file content for recovery analysis
• User SID Mapping: Links deleted files to specific user accounts
• Timestamp Analysis: Precise deletion time tracking

Usage Examples:
--------------
# Parse system Recycle Bin
result = parse_recycle_bin()

# Parse offline artifacts
result = parse_recycle_bin(case_path="/path/to/case", offline_mode=True)

# Parse network locations
result = parse_recycle_bin(network_paths=["\\\\server\\share"])

Output:
-------
SQLite database containing:
- Original filenames and paths
- Deletion timestamps
- File sizes (raw and formatted)
- User SID attribution
- File type signatures
- Recovery status assessment
- Parsing metadata

Author: Ghassan Elsman
License: Open Source
Version: 2.0 
Part of: Crow Eye Digital Forensics Suite
"""

import os
import struct
import datetime
import sqlite3
import subprocess
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from pathlib import Path
import binascii
import ctypes
from ctypes import wintypes, WinDLL, WinError

# Configure logging for forensic analysis
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [RecycleBin] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Import file signature detection utility
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils'))
from file_signature_detector import FileSignatureDetector, get_detector

@dataclass
class RecycleBinEntry:
    """Represents a parsed Recycle Bin entry from $I metadata files.
    
    Attributes:
        original_filename (str): The original name of the deleted file
        original_path (str): The full original path of the deleted file
        deletion_time (datetime): When the file was deleted (FILETIME)
        file_size (int): Original file size in bytes
        user_sid (str): User SID who deleted the file
        recycle_bin_path (str): Path to the $I file in Recycle Bin
        r_file_path (str): Corresponding $R file path if exists
        random_i_filename (str): The random filename of the $I file in Recycle Bin
        random_r_filename (str): The random filename of the $R file in Recycle Bin
        file_signature (str): File header signature for type identification
        recovery_status (str): Recovery possibility assessment
    """
    original_filename: str
    original_path: str
    deletion_time: datetime.datetime
    file_size: int
    user_sid: str
    recycle_bin_path: str
    r_file_path: str
    random_i_filename: str = ""
    random_r_filename: str = ""
    file_signature: str = ""
    recovery_status: str = "Unknown"
    
    @property
    def formatted_file_size(self) -> str:
        """Get human-readable file size format.
        
        Returns:
            str: Formatted size (e.g., "1.5 MB", "512 KB", "2.3 GB")
        """
        if self.file_size == 0:
            return "0 B"
        
        # Define size units
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        size = float(self.file_size)
        
        # Find appropriate unit
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        
        # Format with appropriate decimal places
        if unit_index == 0:  # Bytes
            return f"{int(size)} {units[unit_index]}"
        elif size >= 100:  # No decimal for large numbers
            return f"{int(size)} {units[unit_index]}"
        elif size >= 10:  # One decimal place
            return f"{size:.1f} {units[unit_index]}"
        else:  # Two decimal places for small numbers
            return f"{size:.2f} {units[unit_index]}"

class RecycleBinParser:
    """Advanced Windows Recycle Bin Parser for comprehensive forensic analysis.
    
    This class provides sophisticated parsing capabilities for Windows Recycle Bin
    artifacts, including metadata extraction from $I files, recovery assessment
    of $R files, and detailed forensic analysis with file signature detection.
    
    Features:
        - Parses $I metadata files (all Windows versions)
        - Assesses recovery status of $R data files
        - Detects file signatures and types
        - Supports both live and offline analysis
        - Enhanced error handling and logging
        - Professional forensic reporting
    
    Attributes:
        db_path (str): Path to the output SQLite database
        
    Example:
        >>> parser = RecycleBinParser()
        >>> entries = parser.parse_recycle_bin_directory("C:\\$Recycle.Bin\\S-1-5-21-...")
        >>> db_path = parser.save_to_database(entries)
        >>> print(f"Analysis complete: {len(entries)} entries found")
        
    Note:
        - Requires appropriate permissions for system directory access
        - Automatically handles different Windows Recycle Bin formats
        - Provides detailed recovery assessments for digital forensics
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize the Recycle Bin parser.
        
        Args:
            db_path (str, optional): Path to SQLite database for storing results
        """
        self.db_path = db_path
        self.entries: List[RecycleBinEntry] = []
        
        # Initialize Windows API
        self._init_windows_api()
        
    def detect_file_signature(self, file_path: str) -> Tuple[str, str]:
        """Enhanced file type detection using the dedicated file signature detector utility.
        
        Args:
            file_path (str): Path to the file to analyze
            
        Returns:
            Tuple[str, str]: (Signature description, File extension) or ("Unknown", "")
        """
        try:
            # Use the global detector instance for performance
            detector = get_detector()
            result = detector.detect_file_signature(file_path)
            
            # The detector returns a tuple (description, extension)
            description, extension = result
            
            return description, extension
            
        except Exception as e:
            logger.error(f"Error detecting file signature for {file_path}: {e}")
            return "Error", ""

    def _detect_text_based_signatures(self, file_data: bytes, file_path: str) -> List[Tuple[str, str, str, int]]:
        """Legacy function - now handled by file_signature_detector utility.
        
        This function is kept for compatibility but delegates to the new utility.
        """
        try:
            # Use the new utility for text-based detection
            detector = get_detector()
            result = detector.detect_file_signature(file_path)
            
            # Convert to old format if it's a text-based detection
            if result.get('match_type') == 'text_heuristic':
                description = result.get('description', 'Unknown')
                extension = result.get('extension', '')
                return [(description, extension, "heuristic", 50)]
            
            return []
            
        except Exception as e:
            logger.debug(f"Text-based signature detection failed: {e}")
            return []

    def _init_windows_api(self):
            """Initialize Windows API functions for Recycle Bin access."""
            try:
                self.kernel32 = WinDLL('kernel32', use_last_error=True)
                self.shell32 = WinDLL('shell32', use_last_error=True)
                
                # Define function prototypes
                self.kernel32.GetLastError.restype = wintypes.DWORD
                
                # Shell32 functions for Recycle Bin - simplified approach
                # We'll use SHGetFolderPathW directly instead of complex function definitions
                
            except Exception as e:
                logger.warning(f"Failed to initialize Windows API: {e}")
    
    def _get_recycle_bin_path_windows_api(self) -> Optional[str]:
        """Get Recycle Bin path using Windows API."""
        try:
            # Use CSIDL_BITBUCKET to get Recycle Bin path
            from ctypes import create_unicode_buffer
            
            # CSIDL_BITBUCKET = 0x000A
            buf = create_unicode_buffer(260)  # MAX_PATH
            
            # SHGetFolderPathW is deprecated but still works
            result = ctypes.windll.shell32.SHGetFolderPathW(
                None, 0x000A, None, 0, buf
            )
            
            if result == 0:  # S_OK
                return buf.value
            else:
                return None
                
        except Exception as e:
            print(f"[Warning] Windows API method failed: {e}")
            return None
    
    def _read_file_with_windows_api(self, file_path: str, max_bytes: int = None) -> Optional[bytes]:
        """Read file using standard Python file operations.
        
        Args:
            file_path (str): Path to the file to read
            max_bytes (int, optional): Maximum bytes to read. If None, reads entire file.
            
        Returns:
            Optional[bytes]: File content or None if failed
        """
        try:
            with open(file_path, 'rb') as f:
                if max_bytes is None:
                    return f.read()
                else:
                    return f.read(max_bytes)
        except Exception as e:
            logger.error(f"File read failed for {os.path.basename(file_path)}: {e}")
            return None
    
    def parse_recycle_bin_directory(self, recycle_bin_path: str) -> List[RecycleBinEntry]:
        """Parse all $I files in a Recycle Bin directory.
        
        Args:
            recycle_bin_path (str): Path to $Recycle.Bin directory
            
        Returns:
            List[RecycleBinEntry]: List of parsed Recycle Bin entries
        """
        entries = []
        
        try:
            # Use the provided path instead of hardcoding
            if not recycle_bin_path:
                recycle_bin_path = r"C:\$Recycle.Bin"
                print(f"[RecycleBin] No path provided, using default: {recycle_bin_path}")
            
            print(f"[RecycleBin] Parsing Recycle Bin directory: {recycle_bin_path}")
            
            # Use PowerShell to list directories with Force flag to show hidden items
            ps_command = f"Get-ChildItem -Path '{recycle_bin_path}' -Directory -Force | Where-Object {{ $_.Name.Length -gt 8 }} | Select-Object -ExpandProperty FullName"
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_command], 
                                   capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                print(f"[RecycleBin] Failed to access Recycle Bin at {recycle_bin_path}: {result.stderr}")
                print("[RecycleBin] This is a hidden system folder that may require Administrator privileges.")
                print("[RecycleBin] Try running Crow Eye as Administrator to access Recycle Bin data.")
                return entries
                
            # Parse PowerShell output to get user SID directories
            user_dirs = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            
            # Debug output
            print(f"[RecycleBin Debug] Found {len(user_dirs)} user directories in {recycle_bin_path}")
            
            if not user_dirs:
                print(f"[RecycleBin] No user directories found in Recycle Bin at {recycle_bin_path}")
                return entries
            
            # Parse each user's Recycle Bin directory
            for user_dir in user_dirs:
                user_sid = os.path.basename(user_dir)
                
                # Use PowerShell to list $I files with Force flag to show hidden items
                ps_command = f"Get-ChildItem -Path '{user_dir}' -File -Force | Where-Object {{ $_.Name -like '$I*' -and $_.Name -notlike '*.info' }} | Select-Object -ExpandProperty FullName"
                result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_command], 
                                       capture_output=True, text=True, timeout=30)
                
                # Debug output
                print(f"[RecycleBin Debug] Processing user directory: {user_sid}")
                
                if result.returncode != 0:
                    print(f"[RecycleBin] Failed to access user directory {user_sid}: {result.stderr}")
                    continue
                
                # Parse PowerShell output to get $I files
                i_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                
                for i_path in i_files:
                    try:
                        # Parse the $I file with the user SID
                        entry = self.parse_i_file(i_path, user_sid)
                        if entry:
                            entries.append(entry)
                    except Exception as e:
                        logger.error(f"Failed to parse $I file {os.path.basename(i_path)}: {e}")
                    
        except Exception as e:
            logger.error(f"Error parsing Recycle Bin directory: {e}")
            
        return entries
    
    def parse_i_file(self, i_file_path: str, user_sid: str) -> Optional[RecycleBinEntry]:
        """Parse a single $I metadata file from Recycle Bin.
        
        Args:
            i_file_path (str): Path to the $I file
            user_sid (str): User SID who owns the Recycle Bin
            
        Returns:
            Optional[RecycleBinEntry]: Parsed entry or None if failed
        """
        try:
            data = self._read_file_with_windows_api(i_file_path)
            
            if len(data) < 24:  # Minimum size for basic metadata
                return None
            
            # Detect $I file format version based on file structure
            # Check if first 8 bytes match version pattern
            header = data[:8]
            
            # Windows Vista/7: starts with 01 00 00 00 00 00 00 00
            # Windows 8+: starts with 02 00 00 00 00 00 00 00  
            # Windows 10+: may have different patterns
            
            version = 1  # Default to Vista/7 format
            if len(data) >= 8:
                version_bytes = struct.unpack('<Q', header)[0]
                if version_bytes == 1:
                    version = 1  # Vista/7
                elif version_bytes == 2:
                    version = 2  # Windows 8+
                else:
                    # Try to detect based on file size - if data at offset 0 looks like file size, it's Vista/7
                    potential_size = struct.unpack('<Q', data[0:8])[0]
                    if potential_size > 0 and potential_size < 0x7FFFFFFFFFFFFFFF:
                        version = 0  # Vista/7 without version header
                    else:
                        version = 1  # Default to version 1
            
            # Set correct offsets based on detected version
            if version == 0:  # Windows Vista/7 (no version header)
                file_size_offset = 0
                deletion_time_offset = 8
                path_offset = 16
            else:  # Windows 8+ (with version header)
                file_size_offset = 8
                deletion_time_offset = 16
                if version == 2 and len(data) >= 28:  # Windows 10+ with filename length
                    filename_length_offset = 24
                    path_offset = 28
                else:
                    path_offset = 24
            
            # Parse file size (64-bit little endian)
            if len(data) >= file_size_offset + 8:
                file_size = struct.unpack('<Q', data[file_size_offset:file_size_offset+8])[0]
            else:
                file_size = 0
            
            # Parse deletion timestamp (Windows FILETIME)
            deletion_time = None
            if len(data) >= deletion_time_offset + 8:
                filetime = struct.unpack('<Q', data[deletion_time_offset:deletion_time_offset+8])[0]
                deletion_time = self.filetime_to_datetime(filetime)
            
            # Parse filename length for Windows 10+ (if present)
            filename_length = None
            if version == 2 and len(data) >= 28:
                try:
                    filename_length = struct.unpack('<L', data[24:28])[0]
                    path_offset = 28
                except:
                    path_offset = 24
            
            # Parse original path (UTF-16LE encoded)
            original_path = "<Unknown Path>"
            original_filename = "<Unknown>"
            
            if len(data) > path_offset:
                try:
                    path_data = data[path_offset:]
                    
                    # For Windows 10+ with filename length, use it to determine string length
                    if filename_length is not None and filename_length > 0:
                        # Filename length is in characters, multiply by 2 for bytes (UTF-16)
                        string_bytes = min(filename_length * 2, len(path_data))
                        path_str = path_data[:string_bytes].decode('utf-16le', errors='replace')
                    else:
                        # Find null terminator for older versions
                        null_pos = -1
                        for i in range(0, len(path_data) - 1, 2):
                            if path_data[i] == 0 and path_data[i + 1] == 0:
                                null_pos = i
                                break
                        
                        if null_pos > 0:
                            path_str = path_data[:null_pos].decode('utf-16le', errors='replace')
                        else:
                            # Try to decode entire remaining data
                            path_str = path_data.decode('utf-16le', errors='replace')
                    
                    # Clean and validate the path
                    original_path = path_str.strip('\x00').strip()
                    
                    # Extract filename from path
                    if original_path and original_path != "<Unknown Path>":
                        if '\\' in original_path:
                            original_filename = original_path.split('\\')[-1]
                        elif '/' in original_path:
                            original_filename = original_path.split('/')[-1]
                        else:
                            original_filename = original_path
                    
                    # Clean up non-printable characters
                    original_path = ''.join(c for c in original_path if c.isprintable() or c in ' \\/:.-_')
                    original_filename = ''.join(c for c in original_filename if c.isprintable() or c in ' .-_')
                    
                except Exception as e:
                    logger.warning(f"Path decode error in {os.path.basename(i_file_path)}: {e}")
                    original_path = "<Decoding Error>"
                    original_filename = "<Decoding Error>"
            
            logger.debug(f"Parsed: '{original_filename}' from '{original_path}' (size: {file_size}, version: {version})")
            
            # Find corresponding $R file
            i_file_name = os.path.basename(i_file_path)
            r_file_name = i_file_name.replace('$I', '$R')
            r_file_path = os.path.join(os.path.dirname(i_file_path), r_file_name)
            
            # Extract random filenames
            random_i_filename = i_file_name
            random_r_filename = r_file_name
            
            # Analyze file signature if $R file exists
            file_signature = ""
            recovery_status = "Unknown"
            
            if os.path.exists(r_file_path):
                signature_desc, signature_ext = self.detect_file_signature(r_file_path)
                file_signature = f"{signature_desc} ({signature_ext})" if signature_desc != "Unknown" else ""
                recovery_status = self.assess_recovery_status(r_file_path, file_size)
            
            return RecycleBinEntry(
                original_filename=original_filename,
                original_path=original_path,
                deletion_time=deletion_time,
                file_size=file_size,
                user_sid=user_sid,
                recycle_bin_path=i_file_path,
                r_file_path=r_file_path,
                random_i_filename=random_i_filename,
                random_r_filename=random_r_filename,
                file_signature=file_signature,
                recovery_status=recovery_status
            )
            
        except Exception as e:
            logger.error(f"Failed to parse $I file {os.path.basename(i_file_path)}: {e}")
            return None
    
    def filetime_to_datetime(self, filetime: int) -> Optional[datetime.datetime]:
        """Convert Windows FILETIME to datetime object.
        
        Args:
            filetime (int): Windows FILETIME value (100-nanosecond intervals since 1601)
            
        Returns:
            Optional[datetime.datetime]: Converted datetime object or None if invalid
        """
        try:
            # Check for invalid FILETIME values
            if filetime == 0 or filetime < 0:
                return None
                
            # Windows FILETIME epoch: January 1, 1601
            # Unix epoch: January 1, 1970
            # Difference: 11644473600 seconds
            FILETIME_EPOCH_DIFF = 11644473600
            
            # Convert from 100-nanosecond intervals to seconds
            unix_timestamp = (filetime / 10000000.0) - FILETIME_EPOCH_DIFF
            
            # Validate timestamp is within reasonable range
            if unix_timestamp < 0 or unix_timestamp > 4102444800:  # 1970 to 2100
                return None
                
            return datetime.datetime.fromtimestamp(unix_timestamp)
        except (ValueError, OSError, OverflowError) as e:
            print(f"[RecycleBin Warning] Invalid FILETIME value: {filetime}, Error: {e}")
            return None
    
    def analyze_file_signature(self, file_path: str) -> str:
        """Analyze file header signature to identify file type.
        
        Args:
            file_path (str): Path to the file to analyze
            
        Returns:
            str: File type signature or "Unknown"
        """
        try:
            # Use Windows API/PowerShell to read file header to handle $ character
            header = self._read_file_with_windows_api(file_path, 20)  # Read first 20 bytes for signature
            
            # Common file signatures
            signatures = {
                b'\x4D\x5A': 'PE/EXE',  # MZ header
                b'\x50\x4B\x03\x04': 'ZIP/Office',  # PK header
                b'\x25\x50\x44\x46': 'PDF',  # %PDF
                b'\xFF\xD8\xFF': 'JPEG',  # JPEG
                b'\x89\x50\x4E\x47': 'PNG',  # PNG
                b'\x47\x49\x46\x38': 'GIF',  # GIF
                b'\x52\x49\x46\x46': 'RIFF (AVI/WAV)',  # RIFF
                b'\x7F\x45\x4C\x46': 'ELF',  # ELF
                b'\x4D\x4D\x00\x2A': 'TIFF',  # TIFF
                b'\x49\x49\x2A\x00': 'TIFF',  # TIFF
            }
            
            for sig, file_type in signatures.items():
                if header.startswith(sig):
                    return file_type
            
            # Check for text files
            try:
                header.decode('utf-8', errors='ignore')
                if any(c in header for c in b'\x00\x01\x02\x03\x04\x05\x06\x07'):
                    return "Binary"
                return "Text"
            except:
                return "Binary"
                
        except Exception:
            return "Unknown"
    
    def format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format.
        
        Args:
            size_bytes (int): Size in bytes
            
        Returns:
            str: Formatted size (e.g., "1.5 MB", "512 KB", "2.3 GB")
        """
        if size_bytes == 0:
            return "0 B"
        
        # Define size units
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        size = float(size_bytes)
        
        # Find appropriate unit
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        
        # Format with appropriate decimal places
        if unit_index == 0:  # Bytes
            return f"{int(size)} {units[unit_index]}"
        elif size >= 100:  # No decimal for large numbers
            return f"{int(size)} {units[unit_index]}"
        elif size >= 10:  # One decimal place
            return f"{size:.1f} {units[unit_index]}"
        else:  # Two decimal places for small numbers
            return f"{size:.2f} {units[unit_index]}"

    def assess_recovery_status(self, file_path: str, original_size: int) -> str:
        """Enhanced assessment of file recovery possibility.
        
        Args:
            file_path (str): Path to the $R file
            original_size (int): Original file size from $I metadata
            
        Returns:
            str: Detailed recovery assessment
        """
        try:
            # Check if $R file exists
            if not os.path.exists(file_path):
                return "❌ File not found - likely permanently deleted"
            
            current_size = os.path.getsize(file_path)
            
            # Calculate recovery percentage
            if original_size > 0:
                recovery_percentage = (current_size / original_size) * 100
            else:
                recovery_percentage = 0
            
            # Enhanced status assessment
            if current_size == 0:
                return "❌ Zero bytes - overwritten/corrupted"
            elif current_size == original_size:
                # Additional checks for file integrity
                if self._check_file_integrity(file_path, original_size):
                    return "✅ Full recovery possible - file intact"
                else:
                    return "⚠️ Full size but may be corrupted"
            elif current_size < original_size:
                if recovery_percentage >= 90:
                    return f"⚠️ Nearly complete ({recovery_percentage:.1f}%) - good recovery chance"
                elif recovery_percentage >= 50:
                    return f"⚠️ Partial recovery possible ({recovery_percentage:.1f}%)"
                elif recovery_percentage >= 10:
                    return f"❌ Limited recovery ({recovery_percentage:.1f}%) - mostly overwritten"
                else:
                    return "❌ Minimal data remaining - poor recovery chance"
            else:
                # File is larger than expected
                size_diff = current_size - original_size
                return f"⚠️ Size mismatch (+{self.format_file_size(size_diff)}) - may be corrupted"
                
        except PermissionError:
            return "❌ Access denied - cannot assess recovery"
        except Exception as e:
            return f"❌ Assessment failed: {str(e)[:50]}"
    
    def _check_file_integrity(self, file_path: str, expected_size: int) -> bool:
        """Basic file integrity check.
        
        Args:
            file_path (str): Path to the file
            expected_size (int): Expected file size
            
        Returns:
            bool: True if file appears intact
        """
        try:
            # Basic checks
            if not os.path.exists(file_path):
                return False
            
            actual_size = os.path.getsize(file_path)
            if actual_size != expected_size:
                return False
            
            # Check if file is not all zeros (basic corruption check)
            with open(file_path, 'rb') as f:
                # Read first 1KB to check for null bytes
                sample = f.read(min(1024, actual_size))
                if len(sample) > 0:
                    # If more than 90% of sample is null bytes, likely corrupted
                    null_count = sample.count(b'\x00')
                    if null_count / len(sample) > 0.9:
                        return False
            
            return True
            
        except Exception:
            return False
    
    def save_to_database(self, entries: List[RecycleBinEntry], output_format: str = "db") -> str:
        """Save parsed Recycle Bin entries to SQLite database.
        
        Args:
            entries (List[RecycleBinEntry]): List of parsed entries
            output_format (str): Output format - only "db" for SQLite database is supported
            
        Returns:
            str: Path to the output database file
        """
        if not self.db_path:
            # Create default database path
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            self.db_path = f'recyclebin_analysis_{timestamp}.db'
        
        # Check if database already exists
        db_exists = os.path.exists(self.db_path)
        if db_exists:
            logger.info(f"Database already exists at {self.db_path} - appending new data")
            # Create a backup of the existing file for safety
            backup_path = f"{self.db_path}.bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                import shutil
                shutil.copy2(self.db_path, backup_path)
                logger.info(f"Created backup of existing database at {backup_path}")
            except Exception as e:
                logger.warning(f"Failed to create database backup: {e}")
        else:
            logger.info(f"Creating new database at {self.db_path}")
        

        
        # Otherwise, save to SQLite database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create table (removed ID field and integer file_size for cleaner output)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recycle_bin_entries (
                original_filename TEXT,
                original_path TEXT,
                deletion_time TEXT,
                formatted_file_size TEXT,
                user_sid TEXT,
                recycle_bin_path TEXT,
                r_file_path TEXT,
                random_i_filename TEXT,
                random_r_filename TEXT,
                file_signature TEXT,
                recovery_status TEXT,
                parsed_at TEXT
            )
        """)
        
        # Insert entries
        for entry in entries:
            cursor.execute("""
                INSERT INTO recycle_bin_entries 
                (original_filename, original_path, deletion_time, formatted_file_size,
                 user_sid, recycle_bin_path, r_file_path, random_i_filename, random_r_filename,
                 file_signature, recovery_status, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.original_filename,
                entry.original_path,
                entry.deletion_time.isoformat() if entry.deletion_time else None,
                entry.formatted_file_size,
                entry.user_sid,
                entry.recycle_bin_path,
                entry.r_file_path,
                entry.random_i_filename,
                entry.random_r_filename,
                entry.file_signature,
                entry.recovery_status,
                datetime.datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
        
        return self.db_path
    


def parse_recycle_bin(case_path: Optional[str] = None, offline_mode: bool = False, network_paths: Optional[List[str]] = None) -> str:
    """Parse Windows Recycle Bin artifacts for comprehensive forensic analysis.
    
    This function performs a complete analysis of Windows Recycle Bin artifacts,
    extracting metadata from $I files and assessing recovery status of $R files.
    
    Args:
        case_path (str, optional): Path to case directory for offline analysis.
                                 If None, analyzes live system Recycle Bins.
        offline_mode (bool): Whether to perform offline analysis of artifacts.
                           Defaults to False for live system analysis.
        network_paths (List[str], optional): List of network paths to check for Recycle Bin
        
    Returns:
        str: Path to the generated SQLite database containing analysis results.
             Returns empty string if no entries were found.
    
    Example:
        >>> # Live system analysis
        >>> db_path = parse_recycle_bin()
        >>> print(f"Results saved to: {db_path}")
        
        >>> # Offline case analysis
        >>> db_path = parse_recycle_bin(case_path="/cases/case001", offline_mode=True)
        
    Note:
        - Requires administrative privileges for live system analysis
        - Supports both local and network Recycle Bin locations
        - Automatically creates timestamped database files
        - Provides detailed recovery status assessment for each file
    """
    logger.info("=== Crow Eye Recycle Bin Parser Started ===")
    
    # Determine database path
    if case_path:
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        os.makedirs(artifacts_dir, exist_ok=True)
        output_path = os.path.join(artifacts_dir, 'recyclebin_analysis.db')
    else:
        output_path = 'recyclebin_analysis.db'
    
    parser = RecycleBinParser(output_path)
    entries = []
    
    if offline_mode:
        # Parse offline artifacts from case directory
        target_dir = os.path.join(case_path, 'Target Artifacts', 'Recycle Bin') if case_path else 'Target Artifacts/Recycle Bin'
        
        if os.path.exists(target_dir):
            print(f"[RecycleBin] Parsing offline artifacts from: {target_dir}")
            for item in os.listdir(target_dir):
                item_path = os.path.join(target_dir, item)
                if os.path.isdir(item_path):
                    entries.extend(parser.parse_recycle_bin_directory(item_path))
        else:
            print(f"[RecycleBin] Offline directory not found: {target_dir}")
    else:
        # Parse live system Recycle Bin from all available drives
        try:
            # Use PowerShell to get all drives
            ps_command = "Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Root"
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_command], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                drives = [drive.strip() for drive in result.stdout.splitlines() if drive.strip()]
                
                if not drives:
                    # Fallback to system drive if no drives found
                    system_drive = os.environ.get('SystemDrive', 'C:')
                    if not system_drive.endswith('\\'):
                        system_drive += '\\'
                    drives = [system_drive]
                    
                print(f"[RecycleBin] Found {len(drives)} drives to check for Recycle Bin")
                
                # Parse Recycle Bin on each drive
                for drive in drives:
                    if not drive.endswith('\\'):
                        drive += '\\'
                    
                    recycle_bin_path = f"{drive}$Recycle.Bin"
                    print(f"[RecycleBin] Checking for Recycle Bin at: {recycle_bin_path}")
                    
                    try:
                        if os.path.exists(recycle_bin_path):
                            print(f"[RecycleBin] Parsing Recycle Bin on drive {drive}: {recycle_bin_path}")
                            entries.extend(parser.parse_recycle_bin_directory(recycle_bin_path))
                        else:
                            print(f"[RecycleBin] No Recycle Bin found at: {recycle_bin_path}")
                    except Exception as e:
                        print(f"[RecycleBin] Error accessing Recycle Bin at {recycle_bin_path}: {e}")
            else:
                # Fallback to system drive if PowerShell command fails
                system_drive = os.environ.get('SystemDrive', 'C:')
                if not system_drive.endswith('\\'):
                    system_drive += '\\'
                
                recycle_bin_path = f"{system_drive}$Recycle.Bin"
                try:
                    if os.path.exists(recycle_bin_path):
                        print(f"[RecycleBin] Parsing Recycle Bin (PowerShell fallback): {recycle_bin_path}")
                        entries.extend(parser.parse_recycle_bin_directory(recycle_bin_path))
                    else:
                        print(f"[RecycleBin] No Recycle Bin found at: {recycle_bin_path}")
                except Exception as e:
                    print(f"[RecycleBin] Error accessing Recycle Bin: {e}")
                    print("[RecycleBin] Try running Crow Eye as Administrator for Recycle Bin access")
                
        except Exception as e:
            # Fallback to system drive if any error occurs
            system_drive = os.environ.get('SystemDrive', 'C:')
            if not system_drive.endswith('\\'):
                system_drive += '\\'
            
            print(f"[RecycleBin] Error enumerating drives: {e}")
            print(f"[RecycleBin] Falling back to system drive: {system_drive}")
            recycle_bin_path = f"{system_drive}$Recycle.Bin"
            try:
                if os.path.exists(recycle_bin_path):
                    print(f"[RecycleBin] Parsing Recycle Bin (system drive fallback): {recycle_bin_path}")
                    entries.extend(parser.parse_recycle_bin_directory(recycle_bin_path))
                else:
                    print(f"[RecycleBin] No Recycle Bin found at: {recycle_bin_path}")
            except Exception as e:
                print(f"[RecycleBin] Error accessing Recycle Bin: {e}")
                print("[RecycleBin] Try running Crow Eye as Administrator for Recycle Bin access")
    
    # Process network paths if provided
    if network_paths:
        print(f"[RecycleBin] Processing {len(network_paths)} network paths")
        for path in network_paths:
            if not path.endswith('\\'):
                path += '\\'
                
            recycle_bin_path = f"{path}$Recycle.Bin"
            print(f"[RecycleBin] Checking network Recycle Bin at: {recycle_bin_path}")
            
            if os.path.exists(recycle_bin_path):
                try:
                    net_entries = parser.parse_recycle_bin_directory(recycle_bin_path)
                    if net_entries:
                        logger.info(f"Found {len(net_entries)} entries on network path {path}")
                        entries.extend(net_entries)
                    else:
                        logger.info(f"No entries found on network path {path}")
                except Exception as e:
                    logger.error(f"Error accessing network Recycle Bin at {path}: {e}")
            else:
                logger.warning(f"No Recycle Bin found at network path {recycle_bin_path}")
    
    # Save results
    if entries:
        # Save to database only
        result_path = parser.save_to_database(entries)
        logger.info(f"Analysis complete: {len(entries)} entries saved to database: {result_path}")
    else:
        logger.warning("No Recycle Bin entries found")
        result_path = ""
    
    return result_path

def main():
    """Command-line entry point for Recycle Bin parser."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Windows Recycle Bin Forensic Parser')
    parser.add_argument('--offline', '-o', action='store_true', help='Parse offline artifacts')
    parser.add_argument('--case-path', '-c', help='Path to case directory')
    parser.add_argument('--output', '-out', help='Output database path')
    
    args = parser.parse_args()
    
    # Set database path if specified
    db_path = args.output
    
    # Parse Recycle Bin
    parse_recycle_bin(
        case_path=args.case_path,
        offline_mode=args.offline
    )

if __name__ == "__main__":
    main()
