"""
Prefetch File Parser for Windows Forensic Analysis

This module provides functionality to parse Windows Prefetch files (.pf), which are 
critical forensic artifacts that track program execution history on Windows systems.

Key Features:
- Supports all Windows Prefetch file formats (XP/2003, Vista/7, 8/8.1/2012, 10/11)
- Handles compressed Windows 10/11 prefetch files using native Windows API
- Extracts execution timestamps, run counts, and accessed files
- Preserves file references and volume information
- Exports parsed data to SQLite database and JSON for analysis



Author: Ghassan Elsman
Version: 1.0

"""

import os
import struct
import datetime
import enum
import sqlite3
import json
from dataclasses import dataclass, field
from typing import List, Optional
import ctypes
import re
from ctypes import windll, wintypes

class Version(enum.IntEnum):
    """Enum representing Windows Prefetch file format versions.
    
    Each Windows version uses a specific prefetch file format version number.
    This enum maps those version numbers to their corresponding Windows OS versions,
    which is critical for proper forensic parsing as the format structure varies.
    
    Format differences include:
    - Number of last execution timestamps stored (1 vs 8)
    - Presence of MFT information
    - Compression (Windows 10/11)
    - Section layouts and sizes
    """
    WIN_XP_OR_2003 = 17     # Windows XP and Server 2003 (single last run time)
    VISTA_OR_WIN7 = 23      # Windows Vista and Windows 7 (8 last run times)
    WIN8X_OR_WIN2012X = 26  # Windows 8, 8.1 and Server 2012/R2
    WIN10_OR_WIN11 = 30     # Windows 10 and early Windows 11 (compressed)
    WIN11 = 31              # Later Windows 11 versions (compressed)

@dataclass
class Header:
    """Represents the header section of a Windows Prefetch file.
    
    The header contains critical forensic information including the format version,
    signature ('SCCA'), file size, the name of the executable that was run, and a hash
    value derived from the executable path. This hash is used in the prefetch filename
    (e.g., NOTEPAD.EXE-AF43252D.pf where AF43252D is the hash).
    
    Attributes:
        version (Version): The prefetch format version (indicates Windows version)
        signature (str): The signature string, should be 'SCCA'
        file_size (int): The size of the prefetch file in bytes
        executable_filename (str): The name of the executed program
        hash (str): The hash value derived from the executable path
    """
    version: Version
    signature: str
    file_size: int
    executable_filename: str
    hash: str

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Header':
        """Parse prefetch header from binary data.
        
        Args:
            data (bytes): Raw binary data from the prefetch file
            
        Returns:
            Header: Parsed header object with all fields populated
        """
        version = Version(struct.unpack_from("<I", data, 0)[0])
        signature = data[4:8].decode('ascii')  # Should be 'SCCA'
        file_size = struct.unpack_from("<I", data, 12)[0]
        
        # Executable name is stored as UTF-16LE string (60 bytes, null-terminated)
        exe_filename_bytes = data[16:76]
        exe_filename = exe_filename_bytes.decode('utf-16le').split('\x00')[0].strip()
        
        # Hash is a 32-bit value derived from the executable path
        hash_val = hex(struct.unpack_from("<I", data, 76)[0])[2:].upper()
        
        return cls(version, signature, file_size, exe_filename, hash_val)

@dataclass
class MFTInformation:
    """Represents a Master File Table (MFT) entry reference in Windows NTFS.
    
    MFT references in prefetch files provide crucial forensic linkage between
    the executed program and the actual files on disk. Each reference consists of
    an entry number and sequence number that uniquely identifies a file in the
    NTFS file system's Master File Table.
    
    Attributes:
        mft_entry (int): The MFT entry number (file identifier)
        sequence_number (int): The sequence number (prevents reuse confusion)
    """
    mft_entry: int
    sequence_number: int
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'MFTInformation':
        """Parse MFT information from binary data.
        
        The MFT reference is stored as a 64-bit value where the lower 48 bits
        represent the entry number and the upper 16 bits represent the sequence number.
        
        Args:
            data (bytes): Raw binary data containing the MFT reference
            
        Returns:
            MFTInformation: Parsed MFT reference object
        """
        entry_seq = struct.unpack("<Q", data)[0]  # 64-bit unsigned integer
        mft_entry = entry_seq & 0xFFFFFFFFFFFF   # Lower 48 bits = entry number
        sequence_number = entry_seq >> 48        # Upper 16 bits = sequence number
        
        return cls(mft_entry, sequence_number)
    
    def __str__(self) -> str:
        """Return the standard MFT reference string format.
        
        Returns:
            str: MFT reference in the format 'entry-sequence'
        """
        return f"{self.mft_entry}-{self.sequence_number}"

@dataclass
class FileMetric:
    """Represents information about a file referenced in a prefetch file.
    
    FileMetric objects store information about files accessed during program execution,
    including offsets to the filename string and MFT information. This provides forensic
    evidence of which files were accessed when a program was launched.
    
    The structure varies between Windows versions, with newer versions (Vista and later)
    including MFT information that links to the actual file on disk.
    
    Attributes:
        unknown0 (int): Unknown metric value (possibly flags or timestamps)
        unknown1 (int): Unknown metric value (possibly flags or timestamps)
        unknown2 (int): Unknown metric value (possibly flags or timestamps)
        unknown3 (int): Unknown metric value (possibly flags or timestamps)
        filename_string_offset (int): Offset to the filename string in the strings section
        filename_string_size (int): Size of the filename string in bytes
        mft_info (Optional[MFTInformation]): MFT reference (not present in Windows XP/2003)
    """
    unknown0: int = 0
    unknown1: int = 0
    unknown2: int = 0
    unknown3: int = 0
    filename_string_offset: int = 0
    filename_string_size: int = 0
    mft_info: Optional[MFTInformation] = None
    
    @classmethod
    def from_bytes(cls, data: bytes, is_version17: bool) -> 'FileMetric':
        """Parse file metric information from binary data.
        
        The structure differs between Windows XP/2003 (version 17) and later versions.
        Windows XP/2003 has a simpler structure without MFT information, while later
        versions include MFT references that link to the actual files on disk.
        
        Args:
            data (bytes): Raw binary data containing the file metric
            is_version17 (bool): True if parsing Windows XP/2003 format (version 17)
            
        Returns:
            FileMetric: Parsed file metric object
        """
        if is_version17:
            # Windows XP/2003 format (version 17) - 20 bytes, no MFT information
            unknown0 = struct.unpack_from("<I", data, 0)[0]
            unknown1 = struct.unpack_from("<I", data, 4)[0]
            filename_offset = struct.unpack_from("<I", data, 8)[0]
            filename_size = struct.unpack_from("<I", data, 12)[0]
            unknown2 = struct.unpack_from("<I", data, 16)[0]
            
            return cls(
                unknown0=unknown0,
                unknown1=unknown1,
                filename_string_offset=filename_offset,
                filename_string_size=filename_size,
                unknown2=unknown2
            )
        else:
            # Windows Vista and later format - 32 bytes, includes MFT information
            unknown0 = struct.unpack_from("<I", data, 0)[0]
            unknown1 = struct.unpack_from("<I", data, 4)[0]
            unknown2 = struct.unpack_from("<I", data, 8)[0]
            filename_offset = struct.unpack_from("<I", data, 12)[0]
            filename_size = struct.unpack_from("<I", data, 16)[0]
            unknown3 = struct.unpack_from("<I", data, 20)[0]
            
            # Parse MFT reference (8 bytes at offset 24)
            mft_info = MFTInformation.from_bytes(data[24:32])
            
            return cls(
                unknown0=unknown0,
                unknown1=unknown1,
                unknown2=unknown2,
                unknown3=unknown3,
                filename_string_offset=filename_offset,
                filename_string_size=filename_size,
                mft_info=mft_info
            )

@dataclass
class TraceChain:
    """Represents a trace chain entry in a prefetch file.
    
    Trace chains in prefetch files track the execution flow of a program, including
    information about disk block access patterns. This data is used by Windows to
    optimize future program launches by preloading necessary resources.
    
    From a forensic perspective, trace chains provide evidence of program execution
    patterns and can help establish how a program interacted with the system.
    
    Attributes:
        next_array_entry_index (int): Index of the next entry in the trace chain array
        total_block_load_count (int): Total number of disk blocks that need to be loaded
        unknown0 (int): Unknown value (possibly flags or additional metrics)
        loaded_block_count (int): Number of blocks actually loaded during execution
    """
    next_array_entry_index: int
    total_block_load_count: int
    unknown0: int = 0
    loaded_block_count: int = 0
    
    @classmethod
    def from_bytes(cls, data: bytes, has_loaded_count: bool) -> 'TraceChain':
        """Parse trace chain information from binary data.
        
        The structure varies between Windows versions. Some versions include a
        loaded block count field, while others don't.
        
        Args:
            data (bytes): Raw binary data containing the trace chain entry
            has_loaded_count (bool): Whether the format includes a loaded block count field
            
        Returns:
            TraceChain: Parsed trace chain object
        """
        next_index = struct.unpack_from("<I", data, 0)[0]  # Index to next entry
        total_count = struct.unpack_from("<I", data, 4)[0]  # Total blocks to load
        
        if has_loaded_count:
            # Format with separate loaded count (2-byte values)
            unknown = struct.unpack_from("<H", data, 8)[0]
            loaded_count = struct.unpack_from("<H", data, 10)[0]  # Actual blocks loaded
            return cls(next_index, total_count, unknown, loaded_count)
        else:
            # Format without loaded count (just a 4-byte unknown value)
            unknown = struct.unpack_from("<I", data, 8)[0]
            return cls(next_index, total_count, unknown)

@dataclass
class VolumeInfo:
    """Represents volume information stored in a prefetch file.
    
    Prefetch files contain information about the volumes (drives) accessed during
    program execution, including device names, volume serial numbers, and creation times.
    This provides forensic evidence of which volumes were accessed and when they were
    created.
    
    From a forensic perspective, this can help identify external drives that were
    connected during program execution and establish timeline correlations.
    
    Attributes:
        device_name_offset (int): Offset to the device name string in the strings section
        creation_time (datetime.datetime): Volume creation timestamp
        serial_number (str): Volume serial number in hexadecimal format
        device_name (str): Name of the device (e.g., \\Device\\HarddiskVolume1)
        file_references (List[MFTInformation]): MFT references to files on this volume
        directory_names (List[str]): Directory paths accessed on this volume
    """
    device_name_offset: int
    creation_time: datetime.datetime
    serial_number: str
    device_name: str
    file_references: List[MFTInformation] = field(default_factory=list)
    directory_names: List[str] = field(default_factory=list)

class PrefetchFile:
    """Main class for parsing and analyzing Windows prefetch files.
    
    Windows prefetch files (.pf) are created by the Windows operating system to speed up
    application startup. They contain valuable forensic artifacts including:
    - Executable name and path
    - Last execution times (up to 8 timestamps in Windows 10/11)
    - Run count (number of times the program was executed)
    - Files and directories accessed during program execution
    - Volume information including serial numbers
    
    This class supports parsing prefetch files from Windows XP through Windows 11,
    handling the various format changes and compression methods used across versions.
    
    Forensic Value:
    - Evidence of program execution (what, when, how many times)
    - File and directory access patterns
    - Timeline reconstruction and correlation with other artifacts
    - Identification of connected volumes (including removable media)
    """
    SIGNATURE = 0x41434353  # 'SCCA' in little-endian (ASCII 'SCCA')
    
    def __init__(self):
        """Initialize an empty PrefetchFile object."""
        # Source file metadata
        self.raw_bytes = None
        self.source_filename = ""
        self.source_created_on = None
        self.source_modified_on = None
        self.source_accessed_on = None
        
        # Prefetch file structure information
        self.header = None
        self.file_metrics_offset = 0
        self.file_metrics_count = 0
        self.filename_strings_offset = 0
        self.filename_strings_size = 0
        self.volumes_info_offset = 0
        self.volume_count = 0
        self.volumes_info_size = 0
        self.total_directory_count = -1
        
        # Key forensic artifacts
        self.last_run_times = []  # Timestamps of program execution
        self.volume_information = []  # Information about accessed volumes
        self.run_count = 0  # Number of times the program was executed
        self.parsing_error = False
        
        # Parsed file and directory references
        self.filenames = []  # List of files accessed during execution
        self.file_metrics = []  # Detailed metrics about accessed files

    @classmethod
    def open(cls, file_path: str) -> 'PrefetchFile':
        """Open and parse a prefetch file from disk.
        
        This is the primary method for loading prefetch files for forensic analysis.
        It reads the raw file bytes and passes them to from_bytes() for parsing.
        
        Args:
            file_path (str): Path to the prefetch file (.pf)
            
        Returns:
            PrefetchFile: Parsed prefetch file object
            
        Raises:
            Various exceptions if the file cannot be read or parsed
        """
        with open(file_path, 'rb') as f:
            raw_bytes = f.read()
            return cls.from_bytes(raw_bytes, file_path)
    
    @staticmethod
    def _decompress_win10_prefetch(data: bytes) -> bytes:
        """Decompress Windows 10/11 prefetch files.
        
        Starting with Windows 10, prefetch files are compressed using the Windows
        XPRESS_HUFF compression algorithm. This method detects compressed prefetch
        files by checking for the 'MAM' signature and decompresses them using the
        Windows native API functions.
        
        Forensic Note: The compression does not alter the forensic value of the data,
        but is an important consideration when parsing Windows 10/11 prefetch files.
        
        Args:
            data (bytes): Raw prefetch file data
            
        Returns:
            bytes: Decompressed prefetch data if compressed, otherwise original data
            
        Raises:
            NotImplementedError: If running on a non-Windows system
            Exception: If decompression fails
        """
        # Check for Windows 10/11 compressed prefetch signature ('MAM')
        if data[:3] == b'MAM':
            try:
                # Get the decompressed size from the header
                size = struct.unpack("<I", data[4:8])[0]
                compressed_data = data[8:]
                
                if os.name == 'nt':
                    # Windows 10/11 uses XPRESS_HUFF compression
                    COMPRESSION_FORMAT_XPRESS_HUFF = 4
                    ntdll = windll.ntdll
                    
                    # Get required workspace sizes for decompression
                    compress_workspace_size = wintypes.ULONG()
                    compress_fragment_workspace_size = wintypes.ULONG()
                    
                    status = ntdll.RtlGetCompressionWorkSpaceSize(
                        COMPRESSION_FORMAT_XPRESS_HUFF,
                        ctypes.byref(compress_workspace_size),
                        ctypes.byref(compress_fragment_workspace_size)
                    )
                    
                    if status != 0:
                        raise Exception(f"RtlGetCompressionWorkSpaceSize failed with status {status}")
                    
                    # Allocate buffers for decompression
                    workspace = (ctypes.c_ubyte * compress_fragment_workspace_size.value)()
                    uncompressed_buffer = (ctypes.c_ubyte * size)()
                    final_size = wintypes.ULONG()
                    
                    # Convert compressed data to ctypes buffer
                    compressed_buffer = (ctypes.c_ubyte * len(compressed_data))()
                    for i, b in enumerate(compressed_data):
                        compressed_buffer[i] = b
                    
                    # Call Windows API to decompress the data
                    status = ntdll.RtlDecompressBufferEx(
                        COMPRESSION_FORMAT_XPRESS_HUFF,
                        uncompressed_buffer,
                        size,
                        compressed_buffer,
                        len(compressed_data),
                        ctypes.byref(final_size),
                        workspace
                    )
                    
                    if status != 0:
                        raise Exception(f"RtlDecompressBufferEx failed with status {status}")
                    
                    # Convert back to Python bytes
                    return bytes(uncompressed_buffer)
                else:
                    raise NotImplementedError(
                        "Windows 10/11 prefetch decompression is only supported on Windows."
                    )
            except Exception as e:
                print(f"Error decompressing Windows 10/11 prefetch: {e}")
                raise
        # If not compressed or decompression failed, return original data
        return data

    @classmethod
    def from_bytes(cls, data: bytes, source_filename: str = "") -> 'PrefetchFile':
        """Parse a prefetch file from raw bytes.
        
        This method handles the core parsing logic for prefetch files, including:
        1. Decompressing Windows 10/11 prefetch files if needed
        2. Validating the signature ('SCCA')
        3. Determining the Windows version format
        4. Parsing the appropriate format version
        5. Collecting file metadata if a source filename is provided
        
        Forensic Value:
        - Supports all Windows versions (XP through Windows 11)
        - Handles format differences between versions
        - Extracts key artifacts like execution times and run counts
        
        Args:
            data (bytes): Raw prefetch file data
            source_filename (str, optional): Original file path for metadata collection
            
        Returns:
            PrefetchFile: Parsed prefetch file object
            
        Raises:
            ValueError: If the signature is invalid or version is unknown
            Various exceptions if parsing fails
        """
        # Handle Windows 10/11 compression
        data = cls._decompress_win10_prefetch(data)
        
        # Validate signature ('SCCA' in little-endian)
        signature = struct.unpack_from("<I", data, 4)[0]
        if signature != cls.SIGNATURE:
            raise ValueError(f"Invalid signature: {signature:08X}, expected 'SCCA' (0x{cls.SIGNATURE:08X})")
        
        # Get Windows version format
        version = struct.unpack_from("<I", data, 0)[0]
        
        # Create and initialize instance
        instance = cls()
        instance.raw_bytes = data
        instance.source_filename = source_filename
        
        # Collect file metadata if source filename provided
        if source_filename:
            try:
                stat_info = os.stat(source_filename)
                instance.source_created_on = datetime.datetime.fromtimestamp(stat_info.st_ctime)
                instance.source_modified_on = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                instance.source_accessed_on = datetime.datetime.fromtimestamp(stat_info.st_atime)
            except Exception:
                pass  # Silently continue if metadata collection fails
        
        try:
            # Parse based on Windows version format
            if version == Version.WIN_XP_OR_2003:
                instance._parse_version17()  # Windows XP/2003 format
            elif version == Version.VISTA_OR_WIN7:
                instance._parse_version23()  # Windows Vista/7 format
            elif version == Version.WIN8X_OR_WIN2012X:
                instance._parse_version26()  # Windows 8/8.1/2012 format
            elif version == Version.WIN10_OR_WIN11 or version == Version.WIN11:
                instance._parse_version30or31()  # Windows 10/11 format
            else:
                raise ValueError(f"Unknown version: {version}")
            
            # Sanity check: Fix unreasonably high run counts (possible corruption)
            if instance.run_count > 1000000:
                instance.run_count = len([t for t in instance.last_run_times if t is not None]) or 0
            
            # Adjust run count if 0 but execution times exist
            if instance.run_count == 0 and len(instance.last_run_times) > 0:
                instance.run_count = len([t for t in instance.last_run_times if t is not None])
        
        except Exception as e:
            print(f"Error parsing prefetch file: {e}")
            instance.parsing_error = True
            
        return instance
    
    def _parse_version17(self):
        header_bytes = self.raw_bytes[:84]
        self.header = Header.from_bytes(header_bytes)
        
        file_info_bytes = self.raw_bytes[84:152]
        
        self.file_metrics_offset = struct.unpack_from("<I", file_info_bytes, 0)[0]
        self.file_metrics_count = struct.unpack_from("<I", file_info_bytes, 4)[0]
        self.filename_strings_offset = struct.unpack_from("<I", file_info_bytes, 16)[0]
        self.filename_strings_size = struct.unpack_from("<I", file_info_bytes, 20)[0]
        self.volumes_info_offset = struct.unpack_from("<I", file_info_bytes, 24)[0]
        self.volume_count = struct.unpack_from("<I", file_info_bytes, 28)[0]
        self.volumes_info_size = struct.unpack_from("<I", file_info_bytes, 32)[0]
        
        raw_time = struct.unpack_from("<Q", file_info_bytes, 36)[0]
        self.last_run_times = [self._filetime_to_datetime(raw_time)]
        
        self.run_count = struct.unpack_from("<I", file_info_bytes, 60)[0]
        
        self._parse_file_metrics(True)
        self._parse_filenames()
        self._parse_volume_info()
    
    def _parse_version23(self):
        header_bytes = self.raw_bytes[:84]
        self.header = Header.from_bytes(header_bytes)
        
        file_info_bytes = self.raw_bytes[84:156]
        
        self.file_metrics_offset = struct.unpack_from("<I", file_info_bytes, 0)[0]
        self.file_metrics_count = struct.unpack_from("<I", file_info_bytes, 4)[0]
        self.filename_strings_offset = struct.unpack_from("<I", file_info_bytes, 16)[0]
        self.filename_strings_size = struct.unpack_from("<I", file_info_bytes, 20)[0]
        self.volumes_info_offset = struct.unpack_from("<I", file_info_bytes, 24)[0]
        self.volume_count = struct.unpack_from("<I", file_info_bytes, 28)[0]
        self.volumes_info_size = struct.unpack_from("<I", file_info_bytes, 32)[0]
        
        run_time_offset = 44
        self.last_run_times = []
        for i in range(8):
            raw_time = struct.unpack_from("<Q", file_info_bytes, run_time_offset)[0]
            if raw_time > 0:
                self.last_run_times.append(self._filetime_to_datetime(raw_time))
            run_time_offset += 8
        
        self.run_count = struct.unpack_from("<I", file_info_bytes, run_time_offset)[0]
        
        self._parse_file_metrics(False)
        self._parse_filenames()
        self._parse_volume_info()
    
    def _parse_version26(self):
        header_bytes = self.raw_bytes[:84]
        self.header = Header.from_bytes(header_bytes)
        
        file_info_bytes = self.raw_bytes[84:224]
        
        self.file_metrics_offset = struct.unpack_from("<I", file_info_bytes, 0)[0]
        self.file_metrics_count = struct.unpack_from("<I", file_info_bytes, 4)[0]
        self.filename_strings_offset = struct.unpack_from("<I", file_info_bytes, 16)[0]
        self.filename_strings_size = struct.unpack_from("<I", file_info_bytes, 20)[0]
        self.volumes_info_offset = struct.unpack_from("<I", file_info_bytes, 24)[0]
        self.volume_count = struct.unpack_from("<I", file_info_bytes, 28)[0]
        self.volumes_info_size = struct.unpack_from("<I", file_info_bytes, 32)[0]
        self.total_directory_count = struct.unpack_from("<I", file_info_bytes, 36)[0]
        
        run_time_offset = 44
        self.last_run_times = []
        for i in range(8):
            raw_time = struct.unpack_from("<Q", file_info_bytes, run_time_offset)[0]
            if raw_time > 0:
                self.last_run_times.append(self._filetime_to_datetime(raw_time))
            run_time_offset += 8
        
        self.run_count = struct.unpack_from("<I", file_info_bytes, run_time_offset)[0]
        
        self._parse_file_metrics(False)
        self._parse_filenames()
        self._parse_volume_info()
    
    def _parse_version30or31(self):
        header_bytes = self.raw_bytes[:84]
        self.header = Header.from_bytes(header_bytes)
        
        file_info_bytes = self.raw_bytes[84:224]
        
        self.file_metrics_offset = struct.unpack_from("<I", file_info_bytes, 0)[0]
        self.file_metrics_count = struct.unpack_from("<I", file_info_bytes, 4)[0]
        self.filename_strings_offset = struct.unpack_from("<I", file_info_bytes, 16)[0]
        self.filename_strings_size = struct.unpack_from("<I", file_info_bytes, 20)[0]
        self.volumes_info_offset = struct.unpack_from("<I", file_info_bytes, 24)[0]
        self.volume_count = struct.unpack_from("<I", file_info_bytes, 28)[0]
        self.volumes_info_size = struct.unpack_from("<I", file_info_bytes, 32)[0]
        self.total_directory_count = struct.unpack_from("<I", file_info_bytes, 36)[0]
        
        run_time_offset = 44
        self.last_run_times = []
        for i in range(8):
            raw_time = struct.unpack_from("<Q", file_info_bytes, run_time_offset)[0]
            if raw_time > 0:
                self.last_run_times.append(self._filetime_to_datetime(raw_time))
            run_time_offset += 8
        
        self.run_count = struct.unpack_from("<I", file_info_bytes, run_time_offset)[0]
        
        self._parse_file_metrics(False)
        self._parse_filenames()
        self._parse_volume_info()
    
    def _parse_file_metrics(self, is_version17: bool):
        self.file_metrics = []
        
        if self.file_metrics_count == 0:
            return
        
        metric_size = 20 if is_version17 else 32
        
        metrics_end = self.file_metrics_offset + (self.file_metrics_count * metric_size)
        if metrics_end > len(self.raw_bytes):
            print(f"Warning: File metrics extend beyond file size")
            return
        
        try:
            metrics_data = self.raw_bytes[self.file_metrics_offset:metrics_end]
            
            for i in range(self.file_metrics_count):
                offset = i * metric_size
                if offset + metric_size > len(metrics_data):
                    print(f"Warning: Incomplete file metric at index {i}")
                    break
                
                metric_data = metrics_data[offset:offset + metric_size]
                self.file_metrics.append(FileMetric.from_bytes(metric_data, is_version17))
        except Exception as e:
            print(f"Error parsing file metrics: {e}")
            return
        
        # Parse trace chains (if applicable, for newer versions)
        if not is_version17:
            trace_chain_offset = self.file_metrics_offset + (self.file_metrics_count * metric_size)
            trace_chain_size = 12 if self.header.version <= Version.VISTA_OR_WIN7 else 16
            trace_chain_end = trace_chain_offset + (self.file_metrics_count * trace_chain_size)
            
            if trace_chain_end <= len(self.raw_bytes):
                try:
                    trace_data = self.raw_bytes[trace_chain_offset:trace_chain_end]
                    for i in range(self.file_metrics_count):
                        offset = i * trace_chain_size
                        if offset + trace_chain_size > len(trace_data):
                            print(f"Warning: Incomplete trace chain at index {i}")
                            break
                        trace_chain_data = trace_data[offset:offset + trace_chain_size]
                        has_loaded_count = self.header.version >= Version.WIN8X_OR_WIN2012X
                        self.file_metrics[i].trace_chain = TraceChain.from_bytes(trace_chain_data, has_loaded_count)
                except Exception as e:
                    print(f"Error parsing trace chains: {e}")
    
    def _parse_filenames(self):
        self.filenames = []
        
        if self.filename_strings_size == 0:
            return
        
        if self.filename_strings_offset + self.filename_strings_size > len(self.raw_bytes):
            print(f"Warning: Filename strings extend beyond file size")
            return
        
        try:
            filenames_data = self.raw_bytes[self.filename_strings_offset:
                                            self.filename_strings_offset + self.filename_strings_size]
            
            filenames_str = filenames_data.decode('utf-16le')
            self.filenames = [name for name in filenames_str.split('\x00') if name]
        except Exception as e:
            print(f"Error parsing filename strings: {e}")
    
    def _parse_volume_info(self):
        self.volume_information = []
        
        if self.volumes_info_size == 0 or self.volume_count == 0:
            print("Warning: No volume information in prefetch file")
            return
        
        if self.volumes_info_offset + self.volumes_info_size > len(self.raw_bytes):
            print(f"Warning: Volume info extends beyond file size (offset:{self.volumes_info_offset}, size:{self.volumes_info_size}, file size:{len(self.raw_bytes)})")
            return
        
        vol_entry_size = 40
        
        try:
            volume_data = self.raw_bytes[self.volumes_info_offset:
                                        self.volumes_info_offset + self.volumes_info_size]
            
            for i in range(self.volume_count):
                if i * vol_entry_size + vol_entry_size > len(volume_data):
                    print(f"Warning: Not enough data for volume {i+1}/{self.volume_count}")
                    break
                
                offset = i * vol_entry_size
                vol_data = volume_data[offset:offset + vol_entry_size]
                
                try:
                    vol_dev_offset = struct.unpack_from("<I", vol_data, 0)[0]
                    vol_dev_num_char = struct.unpack_from("<I", vol_data, 4)[0]
                    
                    creation_time_raw = struct.unpack_from("<Q", vol_data, 8)[0]
                    creation_time = self._filetime_to_datetime(creation_time_raw)
                    
                    serial_number = hex(struct.unpack_from("<I", vol_data, 16)[0])[2:].upper()
                    
                    if self.volumes_info_offset + vol_dev_offset + (vol_dev_num_char * 2) > len(self.raw_bytes):
                        print(f"Warning: Device name for volume {i+1} extends beyond file size")
                        device_name = "Unknown Device"
                    else:
                        try:
                            dev_name_bytes = self.raw_bytes[self.volumes_info_offset + vol_dev_offset:
                                                        self.volumes_info_offset + vol_dev_offset + (vol_dev_num_char * 2)]
                            device_name = dev_name_bytes.decode('utf-16le')
                            
                            readable_name = self._get_readable_volume_name(device_name, serial_number)
                            if readable_name:
                                device_name = f"{device_name} ({readable_name})"
                        except Exception as e:
                            print(f"Warning: Error decoding device name: {e}")
                            device_name = f"Device-{serial_number}"
                    
                    vol_info = VolumeInfo(vol_dev_offset, creation_time, serial_number, device_name)
                    
                    file_ref_offset = struct.unpack_from("<I", vol_data, 20)[0]
                    file_ref_size = struct.unpack_from("<I", vol_data, 24)[0]
                    
                    dir_strings_offset = struct.unpack_from("<I", vol_data, 28)[0]
                    num_dir_strings = struct.unpack_from("<I", vol_data, 32)[0]
                    
                    if self.volumes_info_offset + file_ref_offset + file_ref_size > len(self.raw_bytes):
                        print(f"Warning: File references for volume {i+1} extend beyond file size")
                    else:
                        try:
                            file_refs_index = self.volumes_info_offset + file_ref_offset
                            file_ref_bytes = self.raw_bytes[file_refs_index:file_refs_index + file_ref_size]
                            
                            if len(file_ref_bytes) >= 8:
                                file_ref_ver = struct.unpack_from("<I", file_ref_bytes, 0)[0]
                                num_file_refs = struct.unpack_from("<I", file_ref_bytes, 4)[0]
                                
                                temp_index = 8
                                while temp_index + 8 <= len(file_ref_bytes) and len(vol_info.file_references) < num_file_refs:
                                    mft_data = file_ref_bytes[temp_index:temp_index + 8]
                                    vol_info.file_references.append(MFTInformation.from_bytes(mft_data))
                                    temp_index += 8
                        except Exception as e:
                            print(f"Warning: Error parsing file references: {e}")
                    
                    if self.volumes_info_offset + dir_strings_offset > len(self.raw_bytes):
                        print(f"Warning: Directory strings for volume {i+1} extend beyond file size")
                    else:
                        try:
                            dir_strings_index = self.volumes_info_offset + dir_strings_offset
                            dir_strings_bytes = self.raw_bytes[dir_strings_index:]
                            
                            temp_index = 0
                            for k in range(num_dir_strings):
                                if temp_index + 2 > len(dir_strings_bytes):
                                    break
                                
                                dir_char_count = struct.unpack_from("<H", dir_strings_bytes, temp_index)[0] * 2 + 2
                                temp_index += 2
                                
                                if temp_index + dir_char_count > len(dir_strings_bytes):
                                    break
                                
                                dir_name_bytes = dir_strings_bytes[temp_index:temp_index + dir_char_count]
                                dir_name = dir_name_bytes.decode('utf-16le').rstrip('\x00')
                                vol_info.directory_names.append(dir_name)
                                
                                temp_index += dir_char_count
                        except Exception as e:
                            print(f"Warning: Error parsing directory strings: {e}")
                    
                    self.volume_information.append(vol_info)
                except Exception as e:
                    print(f"Error parsing volume {i+1}: {e}")
        except Exception as e:
            print(f"Error parsing volume information: {e}")
    
    @staticmethod
    def _filetime_to_datetime(filetime: int) -> datetime.datetime:
        if filetime == 0:
            return None
        
        seconds_since_1601 = filetime / 10000000
        epoch_diff = 11644473600
        timestamp = seconds_since_1601 - epoch_diff
        
        return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    
    def _format_paths_with_drive_letters(self, paths):
        formatted_paths = []
        
        for path in paths:
            drive_letter = None
            volume_id = None
            
            if "\\VOLUME{" in path:
                for vol in self.volume_information:
                    if vol.device_name in path:
                        if "Drive" in vol.device_name and ":" in vol.device_name:
                            match = re.search(r'Drive ([A-Z]):', vol.device_name)
                            if match:
                                drive_letter = match.group(1)
                                volume_id = vol.device_name
                                break
            
            if drive_letter and volume_id:
                idx = path.find(volume_id)
                if idx >= 0:
                    end_idx = idx + len(volume_id)
                    rest_of_path = path[end_idx:].lstrip("\\")
                    formatted_path = f"{drive_letter}:\\{rest_of_path}"
                    formatted_paths.append(formatted_path)
                    continue
        
            formatted_paths.append(path)
        
        return formatted_paths

    def save_to_sqlite(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA integrity_check")
            conn.close()
        except sqlite3.DatabaseError:
            print(f"Database at {db_path} is malformed. Recreating database...")
            try:
                os.remove(db_path)
            except OSError as e:
                print(f"Error removing corrupted database: {e}")
                return

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prefetch_data (
                    filename TEXT,
                    executable_name TEXT,
                    hash TEXT,
                    run_count INTEGER,
                    last_executed TIMESTAMP,
                    run_times JSON,
                    volumes JSON,
                    directories JSON,
                    resources JSON,
                    created_on TIMESTAMP,
                    modified_on TIMESTAMP,
                    accessed_on TIMESTAMP,
                    PRIMARY KEY(filename, hash)
                )
            """)

            filename = os.path.basename(self.source_filename) if self.source_filename else "Unknown"
            most_recent = max([t for t in self.last_run_times if t is not None], default=None)
            display_run_count = self.run_count
            if display_run_count > 1000000:
                display_run_count = len([t for t in self.last_run_times if t is not None])
                if display_run_count == 0:
                    display_run_count = None

            drive_letters = {}
            volume_pattern = re.compile(r'\\VOLUME\{[0-9a-f-]+\}', re.IGNORECASE)
            
            for vol in self.volume_information:
                if "Drive" in vol.device_name and ":" in vol.device_name:
                    match = re.search(r'Drive ([A-Z]):', vol.device_name)
                    if match:
                        drive_letter = match.group(1)
                        drive_letters[vol.device_name] = drive_letter
                        volume_match = volume_pattern.search(vol.device_name)
                        if volume_match:
                            volume_id = volume_match.group(0)
                            drive_letters[volume_id] = drive_letter

            volumes_data = []
            for i, vol in enumerate(self.volume_information, 1):
                drive_letter = drive_letters.get(vol.device_name)
                vol_id = f"{drive_letter}:" if drive_letter else f"Volume{i}"
                # Format volume creation time without timezone information and milliseconds
                creation_time_str = None
                if vol.creation_time:
                    if vol.creation_time.tzinfo is not None:
                        creation_time_str = vol.creation_time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # Remove milliseconds from string representation
                        creation_time_str = str(vol.creation_time).split('.')[0]
                volumes_data.append({
                    "volume_id": vol_id,
                    "device_name": vol.device_name,
                    "creation_time": creation_time_str,
                    "serial_number": vol.serial_number
                })
            directories_data = []
            for i, vol in enumerate(self.volume_information, 1):
                drive_letter = drive_letters.get(vol.device_name)
                vol_id = f"{drive_letter}:" if drive_letter else f"Volume{i}"
                formatted_dirs = []
                for dir_name in vol.directory_names:
                    formatted_dir = dir_name
                    volume_match = volume_pattern.search(dir_name)
                    if volume_match and drive_letter:
                        volume_id = volume_match.group(0)
                        rest_of_path = dir_name[volume_match.end():].lstrip("\\")
                        formatted_dir = f"{drive_letter}:\\{rest_of_path}"
                    formatted_dirs.append(formatted_dir)
                directories_data.extend(formatted_dirs)

            formatted_resources = []
            for name in self.filenames:
                formatted_name = name
                volume_match = volume_pattern.search(name)
                if volume_match:
                    volume_id = volume_match.group(0)
                    drive_letter = drive_letters.get(volume_id)
                    if not drive_letter:
                        for vol in self.volume_information:
                            if volume_id in vol.device_name:
                                drive_letter = drive_letters.get(vol.device_name)
                                if drive_letter:
                                    break
                    if drive_letter:
                        rest_of_path = name[volume_match.end():].lstrip("\\")
                        formatted_name = f"{drive_letter}:\\{rest_of_path}"
                formatted_resources.append(formatted_name)

            # Format run times without timezone information and milliseconds
            run_times_data = []
            for t in sorted([t for t in self.last_run_times if t is not None], reverse=True):
                if t.tzinfo is not None:
                    # Remove timezone info and milliseconds for display
                    run_times_data.append(t.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    # Remove milliseconds from string representation
                    run_times_data.append(str(t).split('.')[0])

            # Check for existing record with the same filename and hash
            cursor.execute("""
                SELECT COUNT(*) FROM prefetch_data
                WHERE filename = ? AND hash = ?
            """, (filename, self.header.hash))
            if cursor.fetchone()[0] > 0:
                conn.close()
                return

            cursor.execute("""
                INSERT INTO prefetch_data (
                    filename, executable_name, hash, run_count, last_executed,
                    run_times, volumes, directories, resources,
                    created_on, modified_on, accessed_on
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                filename,
                self.header.executable_filename,
                self.header.hash,
                display_run_count,
                # Format most_recent without timezone information and milliseconds
                most_recent.strftime("%Y-%m-%d %H:%M:%S") if most_recent and most_recent.tzinfo is not None else (str(most_recent).split('.')[0] if most_recent else most_recent),
                json.dumps(run_times_data),
                json.dumps(volumes_data),
                json.dumps(directories_data),
                json.dumps(formatted_resources),
                # Format source timestamps to remove milliseconds
                str(self.source_created_on).split('.')[0] if self.source_created_on else self.source_created_on,
                str(self.source_modified_on).split('.')[0] if self.source_modified_on else self.source_modified_on,
                str(self.source_accessed_on).split('.')[0] if self.source_accessed_on else self.source_accessed_on
            ))

            conn.commit()
        except sqlite3.DatabaseError as e:
            print(f"Database error: {e}")
        finally:
            conn.close()

    def __str__(self) -> str:
        result = []

        filename = os.path.basename(self.source_filename) if self.source_filename else "Unknown"
        result.append(f"Prefetch File: {filename}")

        result.append(f"Executable Name: {self.header.executable_filename}")
        result.append(f"Hash: {self.header.hash}")

        display_run_count = self.run_count
        if display_run_count > 1000000:
            display_run_count = len([t for t in self.last_run_times if t is not None])
            if display_run_count == 0:
                display_run_count = "Unknown (parsing error)"
        
        result.append(f"Run Count: {display_run_count}")

        if self.last_run_times and len(self.last_run_times) > 0:
            most_recent = max([t for t in self.last_run_times if t is not None], default=None)
            if most_recent:
                # Format without timezone for display and remove milliseconds
                if most_recent.tzinfo is not None:
                    formatted_time = most_recent.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # Remove milliseconds from string representation
                    formatted_time = str(most_recent).split('.')[0]
                result.append(f"Last Executed: {formatted_time}")
        
            valid_times = [t for t in self.last_run_times if t is not None]
            if len(valid_times) > 1:
                result.append("Execution Timeline:")
                for i, time in enumerate(sorted(valid_times, reverse=True), 1):
                    # Format without timezone for display and remove milliseconds
                    if time.tzinfo is not None:
                        formatted_time = time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # Remove milliseconds from string representation
                        formatted_time = str(time).split('.')[0]
                    result.append(f"  {i}. {formatted_time}")

        if self.volume_information:
            result.append("Volume Information:")
        
            drive_letters = {}
            volume_pattern = re.compile(r'\\VOLUME\{[0-9a-f-]+\}', re.IGNORECASE)
        
            for vol in self.volume_information:
                if "Drive" in vol.device_name and ":" in vol.device_name:
                    match = re.search(r'Drive ([A-Z]):', vol.device_name)
                    if match:
                        drive_letter = match.group(1)
                        drive_letters[vol.device_name] = drive_letter
                        volume_match = volume_pattern.search(vol.device_name)
                        if volume_match:
                            volume_id = volume_match.group(0)
                            drive_letters[volume_id] = drive_letter

            for i, vol in enumerate(self.volume_information, 1):
                drive_letter = drive_letters.get(vol.device_name)
                vol_id = f"{drive_letter}:" if drive_letter else f"Volume{i}"
                result.append(f"Volume {vol_id}:")
                result.append(f"  Device Name: {vol.device_name}")
                # Format volume creation time without timezone
                if vol.creation_time:
                    if vol.creation_time.tzinfo is not None:
                        formatted_time = vol.creation_time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # Remove milliseconds from string representation
                        formatted_time = str(vol.creation_time).split('.')[0]
                    result.append(f"  Creation Date: {formatted_time}")
                else:
                    result.append(f"  Creation Date: {vol.creation_time}")
                result.append(f"  Serial Number: {vol.serial_number}")
            
                if vol.directory_names:
                    result.append(f"  Directories Referenced:")
                    formatted_dirs = []
                    for dir_name in vol.directory_names:
                        formatted_dir = dir_name
                        volume_match = volume_pattern.search(dir_name)
                        if volume_match and drive_letter:
                            volume_id = volume_match.group(0)
                            rest_of_path = dir_name[volume_match.end():].lstrip("\\")
                            formatted_dir = f"{drive_letter}:\\{rest_of_path}"
                        formatted_dirs.append(formatted_dir)
                    for dir_path in formatted_dirs:
                        result.append(f"    {dir_path}")

        if self.filenames:
            result.append("Resources Loaded:")
            formatted_resources = []
            for name in self.filenames:
                formatted_name = name
                volume_match = volume_pattern.search(name)
                if volume_match:
                    volume_id = volume_match.group(0)
                    drive_letter = drive_letters.get(volume_id)
                    if not drive_letter:
                        for vol in self.volume_information:
                            if volume_id in vol.device_name:
                                drive_letter = drive_letters.get(vol.device_name)
                                if drive_letter:
                                    break
                    if drive_letter:
                        rest_of_path = name[volume_match.end():].lstrip("\\")
                        formatted_name = f"{drive_letter}:\\{rest_of_path}"
                formatted_resources.append(formatted_name)
        
            for i, name in enumerate(formatted_resources, 1):
                result.append(f"  {i}. {name}")

        return "\n".join(result)

    @staticmethod
    def _get_readable_volume_name(device_name, serial_number):
        guid_match = re.search(r'\{([0-9a-f-]+)\}', device_name, re.IGNORECASE)
        
        if guid_match:
            guid = guid_match.group(1)
            
            if os.name == 'nt':
                try:
                    from ctypes.wintypes import DWORD, LPCWSTR, LPWSTR
                    
                    DRIVE_UNKNOWN = 0
                    DRIVE_REMOVABLE = 2
                    DRIVE_FIXED = 3
                    DRIVE_REMOTE = 4
                    DRIVE_CDROM = 5
                    DRIVE_RAMDISK = 6
                    
                    drives = []
                    bitmask = windll.kernel32.GetLogicalDrives()
                    for letter in range(ord('A'), ord('Z')+1):
                        if bitmask & 1:
                            drives.append(chr(letter))
                        bitmask >>= 1
                    
                    for drive in drives:
                        drive_path = f"{drive}:\\"
                        
                        drive_type = windll.kernel32.GetDriveTypeW(LPCWSTR(drive_path))
                        
                        vol_name_buf = ctypes.create_unicode_buffer(1024)
                        fs_name_buf = ctypes.create_unicode_buffer(1024)
                        serial_num = DWORD(0)
                        
                        result = windll.kernel32.GetVolumeInformationW(
                            LPCWSTR(drive_path),
                            vol_name_buf,
                            ctypes.sizeof(vol_name_buf),
                            ctypes.byref(serial_num),
                            None,
                            None,
                            fs_name_buf,
                            ctypes.sizeof(fs_name_buf)
                        )
                        
                        if result:
                            drive_serial = format(serial_num.value, '08X')
                            
                            if drive_serial == serial_number:
                                vol_label = vol_name_buf.value
                                drive_type_str = {
                                    DRIVE_UNKNOWN: "Unknown",
                                    DRIVE_REMOVABLE: "Removable",
                                    DRIVE_FIXED: "Fixed",
                                    DRIVE_REMOTE: "Network",
                                    DRIVE_CDROM: "CD-ROM",
                                    DRIVE_RAMDISK: "RAM Disk"
                                }.get(drive_type, "Unknown")
                                
                                if vol_label:
                                    return f"Drive {drive}: '{vol_label}' ({drive_type_str})"
                                else:
                                    return f"Drive {drive}: ({drive_type_str})"
                
                    return None
                    
                except Exception as e:
                    return f"Volume ID: {guid}"
            
            return f"Volume ID: {guid}"
        
        return None

def process_prefetch_files(case_path: str = None, offline_mode: bool = False):
    """
    Process prefetch files and store results in a SQLite database with case management.
    
    Args:
        case_path (str, optional): Path to the case directory for offline analysis.
        offline_mode (bool): If True, process files from case_path/Target_Artifacts/Prefetch.
    """
    # Set the database path and prefetch directory
    default_db_path = "prefetch_data.db"
    default_prefetch_dir = "C:\\Windows\\Prefetch"
    
    if offline_mode and case_path:
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        os.makedirs(artifacts_dir, exist_ok=True)
        db_path = os.path.join(artifacts_dir, 'prefetch_data.db')
        prefetch_dir = os.path.join(artifacts_dir, 'Prefetch')
        print(f"Offline mode: Using prefetch files from {prefetch_dir}")
        print(f"Database will be saved to: {db_path}")
    else:
        # For live mode, check if we're running within Crow Eye with a case directory
        # This ensures the database is saved to the case directory when run from Crow Eye
        if case_path and os.path.exists(case_path):
            artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
            os.makedirs(artifacts_dir, exist_ok=True)
            db_path = os.path.join(artifacts_dir, 'prefetch_data.db')
            print(f"Live mode with case: Using prefetch files from {default_prefetch_dir}")
            print(f"Database will be saved to: {db_path}")
        else:
            db_path = default_db_path
            print(f"Live mode: Using prefetch files from {default_prefetch_dir}")
            print(f"Database will be saved to: {db_path}")
        prefetch_dir = default_prefetch_dir
    
    parsed_files = []
    total_pf_files = 0
    failed_files = []

    try:
        if not os.path.isdir(prefetch_dir):
            raise NotADirectoryError(f"Prefetch directory not found: {prefetch_dir}")
        
        files = [f for f in os.listdir(prefetch_dir) if f.lower().endswith('.pf')]
        total_pf_files = len(files)
        
        for idx, filename in enumerate(files, 1):
            file_path = os.path.join(prefetch_dir, filename)
            try:
                prefetch = PrefetchFile.open(file_path)
                prefetch.save_to_sqlite(db_path)
                parsed_files.append(filename)
                print(f"Processed {filename} ({idx}/{total_pf_files})")
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                failed_files.append(filename)
            
            # Progress update every 10 files or at the end
            if idx % 10 == 0 or idx == total_pf_files:
                progress = (idx / total_pf_files) * 100
                print(f"\rProgress: {idx}/{total_pf_files} ({progress:.1f}%)", end='')
        
        print("\n")
        percentage = (len(parsed_files) / total_pf_files * 100) if total_pf_files > 0 else 0
        print(f"Successfully processed {len(parsed_files)}/{total_pf_files} prefetch files ({percentage:.2f}%)")
        
        if failed_files:
            failed_log_path = os.path.join(os.path.dirname(db_path), 'failed_prefetch_files.txt')
            with open(failed_log_path, 'w') as f:
                for file in failed_files:
                    f.write(f"{file}\n")
            print(f"Failed to process {len(failed_files)} files. List saved to {failed_log_path}")
        
        print(f"\033[92mPrefetch forensic analysis completed! Database saved to: {db_path}\033[0m")
        
    except Exception as e:
        print(f"Error accessing prefetch directory: {e}")
        if total_pf_files == 0:
            print("No .pf files found in the prefetch directory.")

def prefetch_claw(case_path=None, offline_mode=False):
    """Wrapper function for process_prefetch_files to maintain compatibility with Crow Eye.
    
    Args:
        case_path (str, optional): Path to the case directory.
        offline_mode (bool): If True, process files from case_path/Target_Artifacts/Prefetch.
    """
    return process_prefetch_files(case_path=case_path, offline_mode=offline_mode)

if __name__ == "__main__":
    # Example usage: Live mode
    process_prefetch_files()
    
    # Example usage: Offline mode
    # process_prefetch_files(case_path="path/to/case", offline_mode=True)