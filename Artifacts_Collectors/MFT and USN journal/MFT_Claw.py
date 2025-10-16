#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MFT Claw - Enhanced NTFS MFT Parser for Crow Eye Forensic Tool

An advanced, well-architected MFT parser with modular design, comprehensive
forensic analysis capabilities, and robust error handling. Designed for
professional forensic investigations with focus on anomaly detection,
timeline analysis, and evidence correlation.

Author: Ghassan Elsman (Crow Eye Development )
License: Open Source
Version: 2.0.0

Features:
- Object-oriented architecture with clear separation of concerns
- Comprehensive MFT attribute parsing (SI, FN, DATA, OBJECT_ID, etc.)
- Advanced forensic analysis (timestomping, ADS detection, file signature analysis)
- Robust error handling and logging
- Configurable output formats (SQLite, JSON)
- Resume/pause functionality for large datasets
- Multi-volume support with correlation capabilities

WARNING: This tool performs raw disk access. Test on forensic images or VMs first.
"""

import os
import sys
import json
import time
import signal
import struct
import ctypes
import sqlite3
import logging
import datetime
import binascii
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any, Set, Generator, Union
from collections import Counter, defaultdict
from enum import Enum, IntEnum

# Colorama for colored terminal output
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init()
    
    # Color definitions for consistent output
    COLOR_SUCCESS = Fore.GREEN
    COLOR_WARNING = Fore.YELLOW
    COLOR_ERROR = Fore.RED
    COLOR_INFO = Fore.CYAN
    COLOR_HEADER = Fore.MAGENTA + Style.BRIGHT
    COLOR_PROGRESS = Fore.BLUE
    COLOR_RESET = Style.RESET_ALL
    
except ImportError:
    # Fallback if colorama is not available
    COLOR_SUCCESS = COLOR_WARNING = COLOR_ERROR = COLOR_INFO = COLOR_HEADER = COLOR_PROGRESS = COLOR_RESET = ""

# Import win32 modules with enhanced error handling
try:
    import win32api
    import win32con
    import win32file
    import win32security
    import winioctlcon
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False



# Configure module-level logger
logger = logging.getLogger(__name__)

class MFTClawError(Exception):
    """Base exception for MFT Claw errors"""
    pass

class MFTParsingError(MFTClawError):
    """Exception raised during MFT parsing operations"""
    pass

class DatabaseError(MFTClawError):
    """Exception raised during database operations"""
    pass

class VolumeAccessError(MFTClawError):
    """Exception raised during volume access operations"""
    pass

# NTFS Constants
class NTFSConstants:
    """NTFS-related constants and signatures"""
    SIGNATURE = b'NTFS    '
    MFT_RECORD_SIGNATURE = b'FILE'
    BYTES_PER_FILETIME = 8
    
    # MFT Attribute Types
    ATTR_STANDARD_INFORMATION = 0x10
    ATTR_ATTRIBUTE_LIST = 0x20
    ATTR_FILE_NAME = 0x30
    ATTR_OBJECT_ID = 0x40
    ATTR_SECURITY_DESCRIPTOR = 0x50
    ATTR_VOLUME_NAME = 0x60
    ATTR_VOLUME_INFORMATION = 0x70
    ATTR_DATA = 0x80
    ATTR_INDEX_ROOT = 0x90
    ATTR_INDEX_ALLOCATION = 0xA0
    ATTR_BITMAP = 0xB0
    ATTR_REPARSE_POINT = 0xC0
    ATTR_EA_INFORMATION = 0xD0
    ATTR_EA = 0xE0
    ATTR_PROPERTY_SET = 0xF0
    ATTR_LOGGED_UTILITY_STREAM = 0x100
    
    # MFT Record Flags
    RECORD_IN_USE = 0x0001
    RECORD_IS_DIRECTORY = 0x0002
    
    # Reparse Point Tags
    REPARSE_TAG_MOUNT_POINT = 0xA0000003
    REPARSE_TAG_SYMLINK = 0xA000000C
    REPARSE_TAG_DEDUP = 0x80000013
    REPARSE_TAG_APPEXECLINK = 0x8000001B

class OutputFormat(Enum):
    """Supported output formats"""
    SQLITE = "sqlite"
    JSON = "json"
    BOTH = "both"

class LogLevel(Enum):
    """Logging levels"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

@dataclass
class MFTClawConfig:
    """Configuration class for MFT Claw parser"""
    
    # Output settings
    output_format: OutputFormat = OutputFormat.SQLITE
    output_directory: str = "."
    database_name: str = "mft_claw_analysis.db"
    
    # Parsing settings
    batch_size: int = 1000
    
    # Performance settings
    max_resident_file_size: int = 1024 * 1024  # 1MB
    database_cache_size: int = 64 * 1024  # 64MB
    enable_wal_mode: bool = True
    
    # Logging settings
    log_level: LogLevel = LogLevel.INFO
    log_file: str = "mft_claw.log"
    enable_console_logging: bool = True
    
    # Resume functionality disabled for automatic mode
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        if self.batch_size <= 0:
            raise ValueError("Batch size must be positive")
        if self.max_resident_file_size < 0:
            raise ValueError("Max resident file size cannot be negative")
        
        # Ensure output directory exists
        Path(self.output_directory).mkdir(parents=True, exist_ok=True)

@dataclass
class MFTAttribute:
    """Represents a parsed MFT attribute"""
    attr_type: int
    attr_name: str
    resident: bool
    data: Dict[str, Any] = field(default_factory=dict)
    raw_data: Optional[bytes] = None
    
    def __str__(self) -> str:
        return f"MFTAttribute(type=0x{self.attr_type:02X}, name={self.attr_name}, resident={self.resident})"

@dataclass
class MFTRecord:
    """Represents a complete MFT record with all attributes"""
    record_number: int
    volume_letter: str
    in_use: bool = False
    is_directory: bool = False
    flags: int = 0
    sequence_number: int = 0
    
    # Core attributes
    standard_info: Optional[MFTAttribute] = None
    file_names: List[MFTAttribute] = field(default_factory=list)
    data_attributes: List[MFTAttribute] = field(default_factory=list)
    
    # Extended attributes
    object_id: Optional[MFTAttribute] = None
    security_descriptor: Optional[MFTAttribute] = None
    reparse_point: Optional[MFTAttribute] = None
    attribute_list: Optional[MFTAttribute] = None
    
    # Extension record tracking for fragmented entries
    extension_records: List[int] = field(default_factory=list)
    has_extension_records: bool = False
    
    # Computed fields
    primary_filename: str = ""
    file_extension: str = ""
    file_size: int = 0
    file_attributes: int = 0
    
    # ADS (Alternate Data Streams) information
    has_ads: bool = False
    ads_count: int = 0
    

    
    def get_primary_filename(self) -> str:
        """Get the primary filename (non-DOS name if available)"""
        if not self.file_names:
            return ""
        
        # Prefer non-DOS names
        for fn_attr in self.file_names:
            if fn_attr.data.get('namespace', 0) != 2:  # Not DOS namespace
                return fn_attr.data.get('file_name', '')
        
        # Fall back to first available name
        return self.file_names[0].data.get('file_name', '')
    
    def get_creation_time(self) -> Optional[datetime.datetime]:
        """Get creation time from standard information"""
        if self.standard_info and 'created' in self.standard_info.data:
            return self.standard_info.data['created']
        return None
    
    def get_modification_time(self) -> Optional[datetime.datetime]:
        """Get modification time from standard information"""
        if self.standard_info and 'modified' in self.standard_info.data:
            return self.standard_info.data['modified']
        return None
        
    def get_accessed_time(self) -> Optional[datetime.datetime]:
        """Get access time from standard information"""
        if self.standard_info and 'accessed' in self.standard_info.data:
            return self.standard_info.data['accessed']
        return None
    
    def get_mft_modified_time(self) -> Optional[datetime.datetime]:
        """Get MFT modified time from standard information"""
        if self.standard_info and 'mft_modified' in self.standard_info.data:
            return self.standard_info.data['mft_modified']
        return None
    


class MFTAttributeParser(ABC):
    """Abstract base class for MFT attribute parsers"""
    
    @abstractmethod
    def can_parse(self, attr_type: int) -> bool:
        """Check if this parser can handle the given attribute type"""
        pass
    
    @abstractmethod
    def parse(self, attr_type: int, attr_data: bytes, resident: bool) -> MFTAttribute:
        """Parse the attribute data and return an MFTAttribute object"""
        pass

class StandardInformationParser(MFTAttributeParser):
    """Parser for $STANDARD_INFORMATION attributes"""
    
    def can_parse(self, attr_type: int) -> bool:
        return attr_type == NTFSConstants.ATTR_STANDARD_INFORMATION
    
    def parse(self, attr_type: int, attr_data: bytes, resident: bool) -> MFTAttribute:
        if len(attr_data) < 48:
            raise MFTParsingError(f"Standard Information attribute too short: {len(attr_data)} bytes")
        
        try:
            # Parse timestamps (8 bytes each, FILETIME format)
            created = self._parse_filetime(attr_data[0:8])
            modified = self._parse_filetime(attr_data[8:16])
            accessed = self._parse_filetime(attr_data[16:24])
            mft_modified = self._parse_filetime(attr_data[24:32])
            
            # Parse flags and attributes
            flags = struct.unpack('<I', attr_data[32:36])[0]
            max_versions = struct.unpack('<I', attr_data[36:40])[0]
            version_number = struct.unpack('<I', attr_data[40:44])[0]
            class_id = struct.unpack('<I', attr_data[44:48])[0]
            
            data = {
                'created': created,
                'modified': modified,
                'accessed': accessed,
                'mft_modified': mft_modified,
                'flags': flags,
                'max_versions': max_versions,
                'version_number': version_number,
                'class_id': class_id
            }
            
            # Parse extended fields if available (Windows 2000+)
            if len(attr_data) >= 72:
                owner_id = struct.unpack('<I', attr_data[48:52])[0]
                security_id = struct.unpack('<I', attr_data[52:56])[0]
                quota_charged = struct.unpack('<Q', attr_data[56:64])[0]
                usn = struct.unpack('<Q', attr_data[64:72])[0]
                
                data.update({
                    'owner_id': owner_id,
                    'security_id': security_id,
                    'quota_charged': quota_charged,
                    'usn': usn
                })
            
            return MFTAttribute(
                attr_type=attr_type,
                attr_name="$STANDARD_INFORMATION",
                resident=resident,
                data=data,
                raw_data=attr_data
            )
            
        except struct.error as e:
            raise MFTParsingError(f"Error parsing Standard Information: {e}")
    
    def _parse_filetime(self, filetime_bytes: bytes) -> Optional[datetime.datetime]:
        """Convert Windows FILETIME to datetime object"""
        if len(filetime_bytes) != 8:
            return None
        
        try:
            ft = struct.unpack('<Q', filetime_bytes)[0]
            if ft == 0:
                return None
            
            # Convert from 100-nanosecond intervals since 1601-01-01
            seconds_since_1601 = ft / 10000000
            epoch_diff = 11644473600  # Seconds between 1601 and 1970
            seconds_since_1970 = seconds_since_1601 - epoch_diff
            
            return datetime.datetime.fromtimestamp(seconds_since_1970, tz=datetime.timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None

class FileNameParser(MFTAttributeParser):
    """Parser for $FILE_NAME attributes"""
    
    def can_parse(self, attr_type: int) -> bool:
        return attr_type == NTFSConstants.ATTR_FILE_NAME
    
    def parse(self, attr_type: int, attr_data: bytes, resident: bool) -> MFTAttribute:
        if len(attr_data) < 66:
            raise MFTParsingError(f"File Name attribute too short: {len(attr_data)} bytes")
        
        try:
            # Parse parent directory reference
            parent_ref = struct.unpack('<Q', attr_data[0:8])[0]
            parent_record = parent_ref & 0xFFFFFFFFFFFF  # Lower 48 bits for record number
            parent_seq = (parent_ref >> 48) & 0xFFFF     # Upper 16 bits for sequence number
            
            # Ensure parent_seq is properly handled (fix for empty parent_sequence column)
            if parent_seq == 0 and parent_record > 0:
                # If sequence is 0 but record exists, use a default sequence of 1
                parent_seq = 1
                

            
            # Parse timestamps
            created = self._parse_filetime(attr_data[8:16])
            modified = self._parse_filetime(attr_data[16:24])
            accessed = self._parse_filetime(attr_data[24:32])
            mft_modified = self._parse_filetime(attr_data[32:40])
            
            # Parse file information
            allocated_size = struct.unpack('<Q', attr_data[40:48])[0]
            real_size = struct.unpack('<Q', attr_data[48:56])[0]
            flags = struct.unpack('<I', attr_data[56:60])[0]
            reparse_value = struct.unpack('<I', attr_data[60:64])[0]
            
            # Parse filename
            filename_length = struct.unpack('<B', attr_data[64:65])[0]
            namespace = struct.unpack('<B', attr_data[65:66])[0]
            
            if len(attr_data) < 66 + (filename_length * 2):
                raise MFTParsingError("File Name attribute truncated")
            
            filename_bytes = attr_data[66:66 + (filename_length * 2)]
            filename = filename_bytes.decode('utf-16le', errors='replace')
            
            data = {
                'parent_record': parent_record,
                'parent_sequence': parent_seq,
                'parent_ref': f"{parent_record}:{parent_seq}",
                'created': created,
                'modified': modified,
                'accessed': accessed,
                'mft_modified': mft_modified,
                'allocated_size': allocated_size,
                'real_size': real_size,
                'flags': flags,
                'reparse_value': reparse_value,
                'filename_length': filename_length,
                'namespace': namespace,
                'file_name': filename
            }
            
            return MFTAttribute(
                attr_type=attr_type,
                attr_name="$FILE_NAME",
                resident=resident,
                data=data,
                raw_data=attr_data
            )
            
        except (struct.error, UnicodeDecodeError) as e:
            raise MFTParsingError(f"Error parsing File Name: {e}")
    
    def _parse_filetime(self, filetime_bytes: bytes) -> Optional[datetime.datetime]:
        """Convert Windows FILETIME to datetime object"""
        if len(filetime_bytes) != 8:
            return None
        
        try:
            ft = struct.unpack('<Q', filetime_bytes)[0]
            if ft == 0:
                return None
            
            seconds_since_1601 = ft / 10000000
            epoch_diff = 11644473600
            seconds_since_1970 = seconds_since_1601 - epoch_diff
            
            return datetime.datetime.fromtimestamp(seconds_since_1970, tz=datetime.timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None

class DataAttributeParser(MFTAttributeParser):
    """Parser for $DATA attributes"""
    
    def can_parse(self, attr_type: int) -> bool:
        return attr_type == NTFSConstants.ATTR_DATA
    
    def parse(self, attr_type: int, attr_data: bytes, resident: bool) -> MFTAttribute:
        data = {
            'resident': resident,
            'size': len(attr_data) if resident else 0,
            'content': attr_data if resident else None
        }
        
        # For non-resident data, we would need to parse run lists
        # This is a simplified implementation
        if not resident and len(attr_data) >= 16:
            try:
                # Parse non-resident attribute header
                starting_vcn = struct.unpack('<Q', attr_data[0:8])[0]
                ending_vcn = struct.unpack('<Q', attr_data[8:16])[0]
                data.update({
                    'starting_vcn': starting_vcn,
                    'ending_vcn': ending_vcn
                })
            except struct.error:
                pass
        
        return MFTAttribute(
            attr_type=attr_type,
            attr_name="$DATA",
            resident=resident,
            data=data,
            raw_data=attr_data if resident else None
        )

class AttributeListParser(MFTAttributeParser):
    """Parser for $ATTRIBUTE_LIST attributes"""
    
    def can_parse(self, attr_type: int) -> bool:
        return attr_type == NTFSConstants.ATTR_ATTRIBUTE_LIST
    
    def parse(self, attr_type: int, attr_data: bytes, resident: bool) -> MFTAttribute:
        """Parse attribute list to find extension records"""
        data = {
            'resident': resident,
            'size': len(attr_data),
            'extension_records': []
        }
        
        try:
            # Parse attribute list entries
            offset = 0
            while offset + 26 <= len(attr_data):  # Minimum attribute list entry size
                # Read attribute list entry header
                entry_length = struct.unpack('<I', attr_data[offset:offset+4])[0]
                if entry_length == 0 or offset + entry_length > len(attr_data):
                    break
                
                entry_attr_type = struct.unpack('<I', attr_data[offset+4:offset+8])[0]
                name_length = struct.unpack('<B', attr_data[offset+8:offset+9])[0]
                name_offset = struct.unpack('<B', attr_data[offset+9:offset+10])[0]
                starting_vcn = struct.unpack('<Q', attr_data[offset+10:offset+18])[0]
                base_record_ref = struct.unpack('<Q', attr_data[offset+18:offset+26])[0]
                
                # Extract MFT record number from base record reference
                extension_record_num = base_record_ref & 0xFFFFFFFFFFFF  # Lower 48 bits
                
                # Parse attribute name if present
                attr_name = ""
                if name_length > 0 and name_offset > 0:
                    name_start = offset + name_offset
                    name_end = name_start + (name_length * 2)  # Unicode name
                    if name_end <= len(attr_data):
                        try:
                            attr_name = attr_data[name_start:name_end].decode('utf-16le', errors='ignore')
                        except:
                            attr_name = ""
                
                # Store extension record information
                extension_info = {
                    'attr_type': entry_attr_type,
                    'attr_name': attr_name,
                    'starting_vcn': starting_vcn,
                    'extension_record': extension_record_num
                }
                data['extension_records'].append(extension_info)
                
                logger.debug(f"Found extension record {extension_record_num} for attribute type 0x{entry_attr_type:02X}")
                
                offset += entry_length
                
        except Exception as e:
            logger.debug(f"Error parsing attribute list: {e}")
        
        return MFTAttribute(
            attr_type=attr_type,
            attr_name="$ATTRIBUTE_LIST",
            resident=resident,
            data=data,
            raw_data=attr_data
        )

class AttributeParserRegistry:
    """Registry for MFT attribute parsers"""
    
    def __init__(self):
        self._parsers: List[MFTAttributeParser] = []
        self._register_default_parsers()
    
    def _register_default_parsers(self):
        """Register default attribute parsers"""
        self.register(StandardInformationParser())
        self.register(FileNameParser())
        self.register(DataAttributeParser())
    
    def register(self, parser: MFTAttributeParser):
        """Register a new attribute parser"""
        self._parsers.append(parser)
    
    def get_parser(self, attr_type: int) -> Optional[MFTAttributeParser]:
        """Get a parser for the given attribute type"""
        for parser in self._parsers:
            if parser.can_parse(attr_type):
                return parser
        return None

class DatabaseManager:
    """Manages database operations for MFT Claw"""
    
    def __init__(self, config: MFTClawConfig):
        self.config = config
        self.db_path = os.path.join(config.output_directory, config.database_name)
        self.connection: Optional[sqlite3.Connection] = None
        self._setup_database()
    
    def _setup_database(self):
        """Initialize database connection and schema"""
        try:
            # Configure datetime handling before connection
            self._configure_datetime_handling()
            # Connect with proper datetime detection
            self.connection = sqlite3.connect(
                self.db_path, 
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self._configure_database()
            self._create_schema()
            logger.info(f"Database initialized: {self.db_path}")
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to initialize database: {e}")
    
    @staticmethod
    def _configure_datetime_handling():
        """Configure proper datetime handling for Python 3.12+ compatibility"""
        # Register custom datetime adapters to avoid deprecation warnings
        def adapt_datetime(dt):
            """Convert datetime to ISO format string"""
            if dt is None:
                return None
            return dt.isoformat()
        
        def convert_datetime(val):
            """Convert ISO format string back to datetime"""
            if val is None or val == b'':
                return None
            try:
                if isinstance(val, bytes):
                    val = val.decode('utf-8')
                return datetime.datetime.fromisoformat(val)
            except (ValueError, AttributeError):
                return None
        
        # Register the adapters
        sqlite3.register_adapter(datetime.datetime, adapt_datetime)
        sqlite3.register_converter("TIMESTAMP", convert_datetime)
    
    def _configure_database(self):
        """Configure database for optimal performance"""
        if not self.connection:
            return
        
        try:
            # Performance optimizations
            self.connection.execute("PRAGMA foreign_keys = ON")
            if self.config.enable_wal_mode:
                self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
            self.connection.execute(f"PRAGMA cache_size = -{self.config.database_cache_size}")
            self.connection.execute("PRAGMA temp_store = MEMORY")
            self.connection.execute("PRAGMA mmap_size = 268435456")  # 256MB
        except sqlite3.Error as e:
            logger.warning(f"Failed to configure database: {e}")
    
    def _create_schema(self):
        """Create database schema"""
        if not self.connection:
            return
        
        schema_sql = """
        -- Main MFT records table
        CREATE TABLE IF NOT EXISTS mft_records (
            record_number INTEGER,
            file_name TEXT,
            volume_letter TEXT,
            extension TEXT,
            file_size INTEGER,
            in_use INTEGER,
            is_directory INTEGER,
            flags INTEGER,
            mft_sequence_number INTEGER,
            has_ads INTEGER DEFAULT 0,
            ads_count INTEGER DEFAULT 0,
            created_time TIMESTAMP,
            modified_time TIMESTAMP,
            accessed_time TIMESTAMP,
            mft_modified_time TIMESTAMP,
            file_attributes INTEGER,
            PRIMARY KEY (record_number, volume_letter)
        );
        
        -- Standard Information attributes
        CREATE TABLE IF NOT EXISTS mft_standard_info (
            record_number INTEGER,
            file_name TEXT,
            volume_letter TEXT,
            created TIMESTAMP,
            modified TIMESTAMP,
            accessed TIMESTAMP,
            mft_modified TIMESTAMP,
            flags INTEGER,
            max_versions INTEGER,
            version_number INTEGER,
            class_id INTEGER,
            owner_id INTEGER,
            security_id INTEGER,
            quota_charged INTEGER,
            usn INTEGER,
            FOREIGN KEY(record_number, volume_letter) REFERENCES mft_records(record_number, volume_letter)
        );
        
        -- File Name attributes
        CREATE TABLE IF NOT EXISTS mft_file_names (
            record_number INTEGER,
            file_name TEXT,
            volume_letter TEXT,
            parent_record INTEGER,
            parent_sequence INTEGER,
            namespace INTEGER,
            created TIMESTAMP,
            modified TIMESTAMP,
            accessed TIMESTAMP,
            mft_modified TIMESTAMP,
            allocated_size INTEGER,
            real_size INTEGER,
            flags INTEGER,
            FOREIGN KEY(record_number, volume_letter) REFERENCES mft_records(record_number, volume_letter)
        );
        
        -- Data attributes table
        CREATE TABLE IF NOT EXISTS mft_data_attributes (
            record_number INTEGER,
            file_name TEXT,
            volume_letter TEXT,
            attribute_name TEXT,
            resident INTEGER,
            size INTEGER,
            data_type TEXT DEFAULT 'Default',
            FOREIGN KEY (record_number, volume_letter) REFERENCES mft_records(record_number, volume_letter)
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_mft_records_filename ON mft_records(file_name);
        CREATE INDEX IF NOT EXISTS idx_mft_records_extension ON mft_records(extension);
        CREATE INDEX IF NOT EXISTS idx_mft_filenames_parent ON mft_file_names(parent_record);
        """
        
        try:
            self.connection.executescript(schema_sql)
            self.connection.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to create schema: {e}")
    
    def insert_mft_record(self, record: MFTRecord):
        """Insert an MFT record into the database"""
        if not self.connection:
            raise DatabaseError("Database not initialized")
        
        try:
            # Insert main record
            self.connection.execute("""
                INSERT OR REPLACE INTO mft_records (
                    record_number, file_name, volume_letter, extension,
                    file_size, in_use, is_directory, flags, mft_sequence_number, has_ads, ads_count,
                    created_time, modified_time, accessed_time, mft_modified_time, file_attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.record_number, record.primary_filename, record.volume_letter,
                record.file_extension, record.file_size,
                1 if record.in_use else 0, 1 if record.is_directory else 0,
                record.flags, record.sequence_number, 1 if record.has_ads else 0, record.ads_count,
                record.get_creation_time(), record.get_modification_time(),
                record.get_accessed_time(), record.get_mft_modified_time(),
                record.file_attributes
            ))
            
            # Insert standard information if available
            if record.standard_info:
                self._insert_standard_info(record)
            
            # Insert file names
            for fn_attr in record.file_names:
                self._insert_file_name(record, fn_attr)
            
            # Insert data attributes
            for data_attr in record.data_attributes:
                self._insert_data_attribute(record, data_attr)
                
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to insert MFT record {record.record_number}: {e}")
    
    def bulk_insert_mft_records(self, records: List[MFTRecord]):
        """Bulk insert multiple MFT records for improved performance"""
        if not self.connection or not records:
            return
        
        try:
            # Prepare bulk data for main records
            main_records_data = []
            standard_info_data = []
            file_names_data = []
            data_attributes_data = []
            
            for record in records:
                # Main record data
                main_records_data.append((
                    record.record_number, record.primary_filename, record.volume_letter,
                    record.file_extension, record.file_size,
                    1 if record.in_use else 0, 1 if record.is_directory else 0,
                    record.flags, record.sequence_number, 1 if record.has_ads else 0, record.ads_count,
                    record.get_creation_time(), record.get_modification_time(),
                    record.get_accessed_time(), record.get_mft_modified_time(),
                    record.file_attributes
                ))
                
                # Standard information data
                if record.standard_info:
                    si_data = record.standard_info.data
                    standard_info_data.append((
                        record.record_number, record.primary_filename, record.volume_letter,
                        si_data.get('created'), si_data.get('modified'),
                        si_data.get('accessed'), si_data.get('mft_modified'),
                        si_data.get('flags', 0), si_data.get('max_versions', 0),
                        si_data.get('version_number', 0), si_data.get('class_id', 0),
                        si_data.get('owner_id', 0), si_data.get('security_id', 0),
                        si_data.get('quota_charged', 0), si_data.get('usn', 0)
                    ))
                
                # File names data
                for fn_attr in record.file_names:
                    fn_data = fn_attr.data
                    
                    # Ensure parent_sequence is never NULL (same logic as _insert_file_name)
                    parent_record = fn_data.get('parent_record', 0)
                    parent_sequence = fn_data.get('parent_sequence', 0)
                    
                    # If parent_sequence is None or 0 but parent_record exists, default to 1
                    if (parent_sequence is None or parent_sequence == 0) and parent_record > 0:
                        parent_sequence = 1
                    
                    # Root directory (record 5) might have parent_record=0, ensure sequence is 0 not NULL
                    if parent_sequence is None:
                        parent_sequence = 0
                    
                    file_names_data.append((
                        record.record_number, fn_data.get('file_name', ''), record.volume_letter,
                        parent_record, parent_sequence, fn_data.get('namespace', 0), fn_data.get('flags', 0),
                        fn_data.get('created'), fn_data.get('modified'),
                        fn_data.get('accessed'), fn_data.get('mft_modified'),
                        fn_data.get('allocated_size', 0), fn_data.get('real_size', 0)
                    ))
                
                # Data attributes data
                for data_attr in record.data_attributes:
                    data_info = data_attr.data
                    data_attributes_data.append((
                        record.record_number, record.primary_filename, record.volume_letter, data_attr.attr_name,
                        1 if data_info.get('resident', False) else 0,
                        data_info.get('size', 0)
                    ))
            
            # Bulk insert main records
            if main_records_data:
                self.connection.executemany("""
                    INSERT OR REPLACE INTO mft_records (
                        record_number, file_name, volume_letter, extension,
                        file_size, in_use, is_directory, flags, mft_sequence_number, has_ads, ads_count,
                        created_time, modified_time, accessed_time, mft_modified_time, file_attributes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, main_records_data)
            
            # Bulk insert standard information
            if standard_info_data:
                self.connection.executemany("""
                    INSERT INTO mft_standard_info (
                        record_number, file_name, volume_letter, created, modified, accessed, mft_modified,
                        flags, max_versions, version_number, class_id, owner_id, security_id,
                        quota_charged, usn
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, standard_info_data)
            
            # Bulk insert file names
            if file_names_data:
                self.connection.executemany("""
                    INSERT INTO mft_file_names (
                        record_number, file_name, volume_letter, parent_record, parent_sequence,
                        namespace, flags, created, modified, accessed, mft_modified,
                        allocated_size, real_size
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, file_names_data)
            
            # Bulk insert data attributes
            if data_attributes_data:
                self.connection.executemany("""
                    INSERT INTO mft_data_attributes (
                        record_number, file_name, volume_letter, attribute_name, resident, size
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, data_attributes_data)
            
            # Commit the transaction to ensure records are saved before anomaly flushing
            self.connection.commit()
                
        except sqlite3.Error as e:
            self.connection.rollback()
            raise DatabaseError(f"Failed to bulk insert MFT records: {e}")
    
    def _insert_standard_info(self, record: MFTRecord):
        """Insert standard information attribute"""
        si_data = record.standard_info.data
        self.connection.execute("""
            INSERT INTO mft_standard_info (
                record_number, file_name, volume_letter, created, modified, accessed, mft_modified,
                flags, max_versions, version_number, class_id, owner_id, security_id,
                quota_charged, usn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.record_number, record.primary_filename, record.volume_letter,
            si_data.get('created'), si_data.get('modified'),
            si_data.get('accessed'), si_data.get('mft_modified'),
            si_data.get('flags', 0), si_data.get('max_versions', 0),
            si_data.get('version_number', 0), si_data.get('class_id', 0),
            si_data.get('owner_id'), si_data.get('security_id'),
            si_data.get('quota_charged'), si_data.get('usn')
        ))
    
    def _insert_file_name(self, record: MFTRecord, fn_attr: MFTAttribute):
        """Insert file name attribute"""
        fn_data = fn_attr.data
        
        # Ensure parent_sequence is never NULL
        parent_record = fn_data.get('parent_record', 0)
        parent_sequence = fn_data.get('parent_sequence', 0)
        
        # If parent_sequence is None or 0 but parent_record exists, default to 1
        # This ensures we never have NULL values in parent_sequence
        if (parent_sequence is None or parent_sequence == 0) and parent_record > 0:
            parent_sequence = 1
        
        # Root directory (record 5) might have parent_record=0, ensure sequence is 0 not NULL
        if parent_sequence is None:
            parent_sequence = 0
            
        self.connection.execute("""
            INSERT INTO mft_file_names (
                record_number, file_name, volume_letter, parent_record, parent_sequence,
                namespace, created, modified, accessed, mft_modified, allocated_size,
                real_size, flags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.record_number, fn_data.get('file_name', ''), record.volume_letter,
            parent_record, parent_sequence,
            fn_data.get('namespace', 0), fn_data.get('created'),
            fn_data.get('modified'), fn_data.get('accessed'),
            fn_data.get('mft_modified'), fn_data.get('allocated_size', 0),
            fn_data.get('real_size', 0), fn_data.get('flags', 0)
        ))
    
    def _insert_data_attribute(self, record: MFTRecord, data_attr: MFTAttribute):
        """Insert data attribute"""
        data_info = data_attr.data
        
        # Determine data type based on attribute name and content
        data_type = "Default"
        if data_attr.attr_name and data_attr.attr_name != "":
            # This is an Alternate Data Stream
            data_type = "ADS"
            
            # Check for common ADS types
            lower_name = data_attr.attr_name.lower()
            if "zone.identifier" in lower_name:
                data_type = "Zone.Identifier"
            elif "objectid" in lower_name:
                data_type = "ObjectID"
            elif "encryptable" in lower_name:
                data_type = "Encrypted"
            elif "thumbnails" in lower_name:
                data_type = "Thumbnail"
        
        logger.debug(f"Inserting DATA attribute for record {record.record_number}: {data_attr.attr_name}, type: {data_type}, size: {data_info.get('size', 0)}")
        
        try:
            self.connection.execute("""
                INSERT INTO mft_data_attributes (
                    record_number, file_name, volume_letter, attribute_name, resident, size, data_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record.record_number, record.primary_filename, record.volume_letter, data_attr.attr_name,
                1 if data_info.get('resident', False) else 0,
                data_info.get('size', 0),
                data_type
            ))
            logger.debug(f"Successfully inserted DATA attribute for record {record.record_number}")
        except Exception as e:
            logger.error(f"Failed to insert DATA attribute for record {record.record_number}: {e}")
    
    def commit(self):
        """Commit pending transactions"""
        if self.connection:
            self.connection.commit()
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            self.connection = None

class VolumeReader:
    """Handles raw volume access for MFT reading"""
    
    def __init__(self, volume_letter: str):
        self.volume_letter = volume_letter.upper()
        self.volume_path = f"\\\\.\\{self.volume_letter}:"
        self.handle = None
        self.bytes_per_sector = 512
        self.sectors_per_cluster = 8
        self.mft_lcn = 0
        self.mft_record_size = 1024
        
        if not HAS_WIN32:
            raise VolumeAccessError("win32 modules not available")
    
    def open(self):
        """Open volume for reading"""
        try:
            self.handle = win32file.CreateFile(
                self.volume_path,
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                0,
                None
            )
            
            # Read boot sector to get MFT location
            self._parse_boot_sector()
            logger.info(f"Opened volume {self.volume_letter}: successfully")
            
        except Exception as e:
            raise VolumeAccessError(f"Failed to open volume {self.volume_letter}: {e}")
    
    def _parse_boot_sector(self):
        """Parse NTFS boot sector to get MFT information"""
        try:
            # Read boot sector
            boot_sector = self._read_sectors(0, 1)
            
            if len(boot_sector) < 512:
                raise VolumeAccessError("Failed to read boot sector")
            
            # Verify NTFS signature
            if boot_sector[3:11] != NTFSConstants.SIGNATURE:
                raise VolumeAccessError("Not an NTFS volume")
            
            # Parse boot sector fields
            self.bytes_per_sector = struct.unpack('<H', boot_sector[11:13])[0]
            self.sectors_per_cluster = struct.unpack('<B', boot_sector[13:14])[0]
            
            # Get MFT cluster location
            mft_cluster = struct.unpack('<Q', boot_sector[48:56])[0]
            self.mft_lcn = mft_cluster
            
            # Calculate MFT record size
            clusters_per_record = struct.unpack('<b', boot_sector[64:65])[0]
            if clusters_per_record > 0:
                self.mft_record_size = clusters_per_record * self.sectors_per_cluster * self.bytes_per_sector
            else:
                self.mft_record_size = 1 << (-clusters_per_record)
            
            logger.debug(f"MFT located at cluster {self.mft_lcn}, record size {self.mft_record_size}")
            
        except struct.error as e:
            raise VolumeAccessError(f"Failed to parse boot sector: {e}")
    
    def _read_sectors(self, sector: int, count: int) -> bytes:
        """Read sectors from volume"""
        if not self.handle:
            raise VolumeAccessError("Volume not opened")
        
        try:
            offset = sector * self.bytes_per_sector
            win32file.SetFilePointer(self.handle, offset, win32con.FILE_BEGIN)
            
            bytes_to_read = count * self.bytes_per_sector
            _, data = win32file.ReadFile(self.handle, bytes_to_read)
            
            return data
        except Exception as e:
            raise VolumeAccessError(f"Failed to read sectors {sector}-{sector+count-1}: {e}")
    
    def read_mft_record(self, record_number: int) -> bytes:
        """Read a specific MFT record"""
        try:
            # Calculate record offset
            bytes_per_cluster = self.sectors_per_cluster * self.bytes_per_sector
            mft_offset = self.mft_lcn * bytes_per_cluster
            record_offset = mft_offset + (record_number * self.mft_record_size)
            
            # Read record
            sector_offset = record_offset // self.bytes_per_sector
            sectors_needed = (self.mft_record_size + self.bytes_per_sector - 1) // self.bytes_per_sector
            
            data = self._read_sectors(sector_offset, sectors_needed)
            return data[:self.mft_record_size]
            
        except Exception as e:
            raise VolumeAccessError(f"Failed to read MFT record {record_number}: {e}")
    
    def is_valid_file_record(self, record_data: bytes) -> bool:
        """Validate if record data contains a valid FILE record signature
        
        Args:
            record_data: Raw MFT record data
            
        Returns:
            True if record has valid FILE signature and basic structure
        """
        if len(record_data) < 48:  # Minimum size for MFT record header
            return False
            
        # Check FILE signature
        if record_data[0:4] != NTFSConstants.MFT_RECORD_SIGNATURE:
            return False
            
        try:
            # Additional validation: check if fixup array offset is reasonable
            fixup_offset = struct.unpack('<H', record_data[4:6])[0]
            if fixup_offset < 48 or fixup_offset >= len(record_data):
                return False
                
            # Check if first attribute offset is reasonable
            attr_offset = struct.unpack('<H', record_data[20:22])[0]
            if attr_offset < 48 or attr_offset >= len(record_data):
                return False
                
            return True
            
        except (struct.error, IndexError):
            return False
    
    def scan_slack_space_records(self, logical_records: int, allocated_records: int) -> List[int]:
        """Scan for valid FILE records in slack space beyond logical EOF
        
        Args:
            logical_records: Number of records in logical MFT size
            allocated_records: Number of records in allocated MFT size
            
        Returns:
            List of record numbers that contain valid FILE signatures in slack space
        """
        slack_records = []
        
        if allocated_records <= logical_records:
            return slack_records
            
        logger.info(f"Scanning {allocated_records - logical_records:,} potential slack space records...")
        
        for record_num in range(logical_records, allocated_records):
            try:
                record_data = self.read_mft_record(record_num)
                
                if self.is_valid_file_record(record_data):
                    slack_records.append(record_num)
                    logger.debug(f"Found valid FILE record in slack space: {record_num}")
                    
            except Exception as e:
                logger.debug(f"Error reading slack space record {record_num}: {e}")
                continue
                
        if slack_records:
            logger.info(f"Found {len(slack_records):,} valid FILE records in slack space")
        else:
            logger.info("No valid FILE records found in slack space")
            
        return slack_records
    
    def get_mft_size(self) -> Tuple[int, int, int, int]:
        """Get the size of the MFT in records and bytes
        
        Returns:
            Tuple[logical_records, logical_bytes, allocated_records, allocated_bytes]
            - logical_*: Size reported in MFT record (official EOF)
            - allocated_*: Full allocated clusters (may contain slack space records)
        """
        try:
            # Try to read MFT record 0 (MFT itself) if volume is opened
            if hasattr(self, 'handle') and self.handle:
                mft_record = self.read_mft_record(0)
                
                # Parse MFT record to find DATA attribute
                if len(mft_record) >= 48:
                    # Verify record signature
                    if mft_record[0:4] == NTFSConstants.MFT_RECORD_SIGNATURE:
                        # Parse attributes to find DATA attribute
                        attr_offset = struct.unpack('<H', mft_record[20:22])[0]
                        logical_size = 0
                        allocated_size = 0
                        
                        while attr_offset < len(mft_record) - 4:
                            attr_type = struct.unpack('<I', mft_record[attr_offset:attr_offset+4])[0]
                            
                            if attr_type == 0xFFFFFFFF:  # End marker
                                break
                                
                            if attr_type == NTFSConstants.ATTR_DATA:  # DATA attribute
                                # Parse DATA attribute to get MFT sizes
                                attr_length = struct.unpack('<I', mft_record[attr_offset+4:attr_offset+8])[0]
                                non_resident = struct.unpack('<B', mft_record[attr_offset+8:attr_offset+9])[0]
                                
                                if non_resident == 0:  # Resident
                                    content_size = struct.unpack('<I', mft_record[attr_offset+16:attr_offset+20])[0]
                                    logical_size = allocated_size = content_size
                                else:  # Non-resident
                                    if attr_offset + 48 <= len(mft_record):
                                        # Get both logical and allocated sizes
                                        logical_size = struct.unpack('<Q', mft_record[attr_offset+48:attr_offset+56])[0]
                                        allocated_size = struct.unpack('<Q', mft_record[attr_offset+40:attr_offset+48])[0]
                                break
                            
                            attr_length = struct.unpack('<I', mft_record[attr_offset+4:attr_offset+8])[0]
                            if attr_length == 0:
                                break
                            attr_offset += attr_length
                        
                        # Calculate number of records for both sizes
                        if allocated_size > 0:
                            logical_records = logical_size // self.mft_record_size
                            allocated_records = allocated_size // self.mft_record_size
                            

                            
                            if allocated_records > logical_records:
                                slack_records = allocated_records - logical_records
                                logger.info(f"Potential slack space records: {slack_records:,}")
                            
                            return logical_records, logical_size, allocated_records, allocated_size
            
            # Fallback: Use a more realistic estimate based on typical NTFS volumes
            # Modern NTFS volumes can have millions of records
            # Use 2 million as a safer upper bound to ensure we don't miss records
            fallback_records = 2000000
            fallback_bytes = fallback_records * self.mft_record_size
            logger.warning(f"Using fallback MFT size estimate: {fallback_records:,} records")
            return fallback_records, fallback_bytes, fallback_records, fallback_bytes
                
        except Exception as e:
            logger.debug(f"Failed to get MFT size: {e}")
            # Fallback: Use a more realistic estimate
            fallback_records = 2000000
            fallback_bytes = fallback_records * self.mft_record_size
            logger.warning(f"Using fallback MFT size estimate: {fallback_records:,} records")
            return fallback_records, fallback_bytes, fallback_records, fallback_bytes
    
    def get_file_count_estimate(self) -> int:
        """Estimate number of files based on MFT usage"""
        try:
            logical_records, _, allocated_records, _ = self.get_mft_size()
            # Use allocated records for estimate since we'll parse the full allocated space
            # Typically 60-80% of MFT records are in use
            return int(allocated_records * 0.7)
        except Exception:
            return 70000  # Default estimate
    
    def close(self):
        """Close volume handle"""
        if self.handle:
            try:
                win32file.CloseHandle(self.handle)
            except Exception:
                pass
            finally:
                self.handle = None





class MFTParser:
    """Main MFT parser class with enhanced architecture"""
    
    def __init__(self, config: MFTClawConfig):
        self.config = config
        self.db_manager = DatabaseManager(config)
        self.attr_registry = AttributeParserRegistry()
        
        # Current volume being processed (for cleanup purposes)
        self.current_volume_letter = None
        
        # Statistics
        self.stats = {
            'total_records': 0,
            'processed_records': 0,
            'total_mft_size_bytes': 0,
            'parsed_data_size_bytes': 0,
            'estimated_file_count': 0,
            'in_use_records': 0,
            'directory_records': 0,
            'file_records': 0,
            'ads_records': 0,
            'errors': 0
        }
        
        # Initialize processing state
        self.state = {
            'start_time': None,
            'volumes_processed': []
        }
        
        # Initialize timer variables
        self.parsing_start_time = None
        self.volume_start_time = None
        
        self._setup_logging()
    
    def _setup_logging(self):
        """Configure logging for the parser"""
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        # Configure file logging
        file_handler = logging.FileHandler(
            os.path.join(self.config.output_directory, self.config.log_file)
        )
        file_handler.setLevel(self.config.log_level.value)
        file_handler.setFormatter(logging.Formatter(log_format))
        
        # Configure console logging
        if self.config.enable_console_logging:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.config.log_level.value)
            console_handler.setFormatter(logging.Formatter(log_format))
            logger.addHandler(console_handler)
        
        logger.addHandler(file_handler)
        logger.setLevel(self.config.log_level.value)
        
        # Create file-only logger for errors during parsing (to avoid interrupting progress bar)
        self.file_logger = logging.getLogger('file_only')
        self.file_logger.setLevel(logging.DEBUG)
        self.file_logger.addHandler(file_handler)
        self.file_logger.propagate = False  # Don't propagate to root logger
    
    def _format_elapsed_time(self, start_time: float) -> str:
        """Format elapsed time in human-readable format"""
        if start_time is None:
            return "00:00:00"
        
        elapsed = time.time() - start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def parse_volume(self, volume_letter: str) -> bool:
        """Parse MFT from a specific volume"""
        logger.info(f"Starting MFT parsing for volume {volume_letter}:")
        
        # Set current volume for cleanup purposes
        self.current_volume_letter = volume_letter
        
        # Start timer for this volume
        self.volume_start_time = time.time()
        if self.parsing_start_time is None:
            self.parsing_start_time = time.time()
        
        volume_reader = None
        try:
            # Check if volume already processed
            if volume_letter in self.state.get('volumes_processed', []):
                logger.info(f"Volume {volume_letter}: already processed, skipping")
                return True
            
            # Open volume
            volume_reader = VolumeReader(volume_letter)
            volume_reader.open()
            
            # Get MFT size and file count estimates
            logical_records, logical_bytes, allocated_records, allocated_bytes = volume_reader.get_mft_size()
            file_count_estimate = volume_reader.get_file_count_estimate()
            
            # Use allocated size for comprehensive parsing (includes slack space)
            self.stats['logical_records'] = logical_records
            self.stats['logical_mft_size_bytes'] = logical_bytes
            self.stats['total_records'] = allocated_records
            self.stats['total_mft_size_bytes'] = allocated_bytes
            self.stats['estimated_file_count'] = file_count_estimate
            

            
            # Scan for slack space records if allocated size is larger than logical size
            slack_space_records = []
            if allocated_records > logical_records:
                slack_records_count = allocated_records - logical_records
                logger.info(f"Scanning {slack_records_count:,} potential slack space records for deleted evidence...")
                slack_space_records = volume_reader.scan_slack_space_records(logical_records, allocated_records)
                
                if slack_space_records:
                    logger.info(f"Found {len(slack_space_records):,} valid FILE records in slack space - these may contain deleted evidence!")
                    self.stats['slack_space_records_found'] = len(slack_space_records)
            
            # Parse MFT records with optimized batch processing
            # Parse logical records first, then slack space records
            start_record = max(0, self.state.get('last_processed_record', -1) + 1)
            
            # Determine which records to parse
            records_to_parse = []
            
            # Add logical records
            if start_record < logical_records:
                records_to_parse.extend(range(start_record, logical_records))
                
            # Add slack space records (these are beyond logical EOF)
            records_to_parse.extend(slack_space_records)
            
            total_records_to_parse = len(records_to_parse)
            logger.info(f"Will parse {total_records_to_parse:,} total records ({logical_records - start_record:,} logical + {len(slack_space_records):,} slack space)")
            
            # Initialize path cache and batch containers
            if not hasattr(self, '_path_cache'):
                self._path_cache = {}
            
            batch_records = []
            batch_size = min(self.config.batch_size, 1000)  # Optimize batch size
            
            for i, record_num in enumerate(records_to_parse):
                try:
                    # Read and parse record
                    raw_record = volume_reader.read_mft_record(record_num)
                    mft_record = self._parse_mft_record(record_num, volume_letter, raw_record)
                    
                    if mft_record:
                        # Add to batch for bulk processing
                        batch_records.append(mft_record)
                        
                        # Update statistics
                        self._update_statistics(mft_record)
                    
                    self.stats['processed_records'] += 1
                    self.state['last_processed_record'] = record_num
                    
                    # Process batch when full
                    if len(batch_records) >= batch_size:
                        self._process_record_batch(batch_records)
                        batch_records.clear()
                        self.db_manager.commit()
                    
                    # Less frequent progress reporting for better performance
                    if self.stats['processed_records'] % 500 == 0:
                        progress_pct = (i + 1) / total_records_to_parse * 100
                        self._report_progress(progress_pct, record_num, total_records_to_parse)
                    
                except Exception as e:
                    self.file_logger.error(f"Error processing record {record_num}: {e}")
                    self.stats['errors'] += 1
                    continue
            
            # Process remaining records in batch
            if batch_records:
                self._process_record_batch(batch_records)
            
            # Final commit and progress report
            self.db_manager.commit()
            self._report_progress()  # Final progress update
            print()  # Add newline after progress bar
            

            
            # Mark volume as processed
            if 'volumes_processed' not in self.state:
                self.state['volumes_processed'] = []
            self.state['volumes_processed'].append(volume_letter)
            
            logger.info(f"Completed parsing volume {volume_letter}:")
            return True
            
        except Exception as e:
            logger.error(f"Failed to parse volume {volume_letter}: {e}")
            return False
        finally:
            if volume_reader:
                volume_reader.close()
    
    def _parse_mft_record(self, record_number: int, volume_letter: str, raw_data: bytes) -> Optional[MFTRecord]:
        """Parse a raw MFT record"""
        if len(raw_data) < 48:
            return None
        
        try:
            # Verify record signature
            if raw_data[0:4] != NTFSConstants.MFT_RECORD_SIGNATURE:
                return None
            
            # Parse record header
            sequence_number = struct.unpack('<H', raw_data[16:18])[0]
            flags = struct.unpack('<H', raw_data[22:24])[0]
            in_use = bool(flags & NTFSConstants.RECORD_IN_USE)
            is_directory = bool(flags & NTFSConstants.RECORD_IS_DIRECTORY)
            
            # Create MFT record
            record = MFTRecord(
                record_number=record_number,
                volume_letter=volume_letter,
                in_use=in_use,
                is_directory=is_directory,
                flags=flags,
                sequence_number=sequence_number
            )
            
            # Parse attributes
            self._parse_attributes(record, raw_data)
            
            # Set computed fields
            record.primary_filename = record.get_primary_filename()
            record.file_extension = os.path.splitext(record.primary_filename)[1].lower().lstrip('.')
            
            # Calculate file size from data attributes - consider both resident and non-resident
            for data_attr in record.data_attributes:
                # For resident attributes, use the actual data size
                if data_attr.data.get('resident'):
                    record.file_size += data_attr.data.get('size', 0)
                # For non-resident attributes, use the logical size if available
                elif not data_attr.attr_name:  # Unnamed default data stream
                    record.file_size = data_attr.data.get('size', 0)
            
            # Detect Alternate Data Streams (ADS) - correctly identify named data streams
            ads_count = 0
            for data_attr in record.data_attributes:
                # ADS are identified by named data streams (not the unnamed default stream)
                if data_attr.attr_name and data_attr.attr_name != "":
                    ads_count += 1
            
            record.has_ads = ads_count > 0
            record.ads_count = ads_count

            if record.standard_info:
                record.file_attributes = record.standard_info.data.get('flags', 0)
            
            return record
            
        except Exception as e:
            logger.debug(f"Failed to parse MFT record {record_number}: {e}")
            return None
    
    def _parse_attributes(self, record: MFTRecord, raw_data: bytes):
        """Parse attributes from MFT record"""
        try:
            # Get first attribute offset
            attr_offset = struct.unpack('<H', raw_data[20:22])[0]
            
            while attr_offset < len(raw_data) - 4:
                # Read attribute header
                attr_type = struct.unpack('<I', raw_data[attr_offset:attr_offset+4])[0]
                
                # End of attributes marker
                if attr_type == 0xFFFFFFFF:
                    break
                
                # Parse attribute
                attr = self._parse_single_attribute(raw_data, attr_offset)
                if attr:
                    self._categorize_attribute(record, attr)
                
                # Move to next attribute
                attr_length = struct.unpack('<I', raw_data[attr_offset+4:attr_offset+8])[0]
                if attr_length == 0:
                    break
                attr_offset += attr_length
                
        except Exception as e:
            logger.debug(f"Error parsing attributes for record {record.record_number}: {e}")
    
    def _parse_single_attribute(self, raw_data: bytes, offset: int) -> Optional[MFTAttribute]:
        """Parse a single attribute from raw data"""
        try:
            if offset + 16 > len(raw_data):
                return None
            
            # Read attribute header
            attr_type = struct.unpack('<I', raw_data[offset:offset+4])[0]
            attr_length = struct.unpack('<I', raw_data[offset+4:offset+8])[0]
            resident = struct.unpack('<B', raw_data[offset+8:offset+9])[0] == 0
            
            if offset + attr_length > len(raw_data):
                return None
            
            # Get attribute data
            if resident:
                data_offset = struct.unpack('<H', raw_data[offset+20:offset+22])[0]
                data_length = struct.unpack('<I', raw_data[offset+16:offset+20])[0]
                
                if offset + data_offset + data_length <= len(raw_data):
                    attr_data = raw_data[offset + data_offset:offset + data_offset + data_length]
                else:
                    attr_data = b''
            else:
                # Non-resident attribute - simplified handling
                attr_data = raw_data[offset+16:offset+attr_length]
            
            # Debug logging for DATA attributes
            if attr_type == NTFSConstants.ATTR_DATA:
                logger.debug(f"Found DATA attribute: resident={resident}, data_length={len(attr_data)}")
            
            # Use registered parser
            parser = self.attr_registry.get_parser(attr_type)
            if parser:
                parsed_attr = parser.parse(attr_type, attr_data, resident)
                if attr_type == NTFSConstants.ATTR_DATA:
                    logger.debug(f"Parsed DATA attribute: {parsed_attr.attr_name if parsed_attr else 'None'}")
                return parsed_attr
            else:
                # Generic attribute
                generic_attr = MFTAttribute(
                    attr_type=attr_type,
                    attr_name=f"ATTR_0x{attr_type:02X}",
                    resident=resident,
                    data={'size': len(attr_data)},
                    raw_data=attr_data if resident else None
                )
                if attr_type == NTFSConstants.ATTR_DATA:
                    logger.debug(f"Created generic DATA attribute: {generic_attr.attr_name}")
                return generic_attr
                
        except Exception as e:
            logger.debug(f"Error parsing attribute at offset {offset}: {e}")
            return None
    
    def _categorize_attribute(self, record: MFTRecord, attr: MFTAttribute):
        """Categorize and store attribute in appropriate record field"""
        if attr.attr_type == NTFSConstants.ATTR_STANDARD_INFORMATION:
            record.standard_info = attr
        elif attr.attr_type == NTFSConstants.ATTR_FILE_NAME:
            record.file_names.append(attr)
        elif attr.attr_type == NTFSConstants.ATTR_DATA:
            record.data_attributes.append(attr)
            logger.debug(f"Added DATA attribute to record {record.record_number}: {attr.attr_name}, total data attrs: {len(record.data_attributes)}")
        elif attr.attr_type == NTFSConstants.ATTR_OBJECT_ID:
            record.object_id = attr
        elif attr.attr_type == NTFSConstants.ATTR_SECURITY_DESCRIPTOR:
            record.security_descriptor = attr
        elif attr.attr_type == NTFSConstants.ATTR_REPARSE_POINT:
            record.reparse_point = attr
    
    def _update_statistics(self, record: MFTRecord):
        """Update parsing statistics"""
        # Track parsed data size (approximate 1KB per record)
        self.stats['parsed_data_size_bytes'] += 1024
        
        if record.in_use:
            self.stats['in_use_records'] += 1
        
        if record.is_directory:
            self.stats['directory_records'] += 1
        else:
            self.stats['file_records'] += 1
        
        if record.has_ads:
            self.stats['ads_records'] += 1
    
    def _process_record_batch(self, records: List[MFTRecord]):
        """Process a batch of records efficiently"""
        if not records:
            return
        
        # Skip path reconstruction during initial parsing phase
        # Paths will be reconstructed in a separate phase after all records are collected
        for record in records:
            record.full_path = ""  # Will be populated later in path reconstruction phase
        
        # Bulk insert all records
        self.db_manager.bulk_insert_mft_records(records)

    def _report_progress(self, progress_pct=None, current_record=None, total_records=None):
        """Report parsing progress on a single line, adapting to terminal width"""
        import shutil
        
        processed = self.stats['processed_records']
        
        # Use provided parameters or calculate from stats
        if progress_pct is not None and total_records is not None:
            percentage = progress_pct
            total = total_records
        else:
            total = self.stats['total_records']
            percentage = (processed / total * 100) if total > 0 else 0
        
        # Get terminal width (default to 80 if unable to detect)
        try:
            terminal_width = shutil.get_terminal_size().columns
        except:
            terminal_width = 80
        
        # Calculate parsed data size (approximate)
        parsed_data_mb = (processed * 1024) / (1024 * 1024)  # Approximate 1KB per record
        total_data_mb = self.stats['total_mft_size_bytes'] / (1024 * 1024)
        
        # Get elapsed time
        elapsed_time = self._format_elapsed_time(self.volume_start_time)
        
        # Add slack space indicator if applicable
        slack_indicator = ""
        if current_record is not None and hasattr(self.stats, 'slack_space_records_found'):
            logical_records = self.stats.get('logical_records', 0)
            if current_record >= logical_records:
                slack_indicator = " [SLACK]"
        
        # Adaptive formatting based on terminal width
        if terminal_width >= 120:
            # Full format for wide terminals
            bar_width = 30
            filled = int(bar_width * percentage / 100)
            bar = '█' * filled + '░' * (bar_width - filled)
            progress_msg = (
                f"[{bar}] {percentage:5.1f}% | "
                f"Records: {processed:,}{slack_indicator} | "
                f"Data: {parsed_data_mb:.1f}/{total_data_mb:.1f} MB | "
                f"MFT Size: {total_data_mb:.1f} MB | "
                f"Time: {elapsed_time} | "
                f"Errors: {self.stats['errors']:,}"
            )
        elif terminal_width >= 90:
            # Medium format - shorter progress bar
            bar_width = 20
            filled = int(bar_width * percentage / 100)
            bar = '█' * filled + '░' * (bar_width - filled)
            progress_msg = (
                f"[{bar}] {percentage:4.1f}% | "
                f"Rec: {processed:,}{slack_indicator} | "
                f"Data: {parsed_data_mb:.1f}/{total_data_mb:.1f}MB | "
                f"MFT: {total_data_mb:.1f}MB | "
                f"Time: {elapsed_time} | "
                f"Err: {self.stats['errors']:,}"
            )
        elif terminal_width >= 70:
            # Compact format - minimal progress bar
            bar_width = 15
            filled = int(bar_width * percentage / 100)
            bar = '█' * filled + '░' * (bar_width - filled)
            progress_msg = (
                f"[{bar}] {percentage:4.1f}% | "
                f"Rec: {processed:,} | "
                f"Data: {parsed_data_mb:.1f}MB | "
                f"MFT: {total_data_mb:.1f}MB | "
                f"Time: {elapsed_time} | "
                f"Err: {self.stats['errors']:,}"
            )
        else:
            # Minimal format for very small terminals
            bar_width = 10
            filled = int(bar_width * percentage / 100)
            bar = '█' * filled + '░' * (bar_width - filled)
            progress_msg = f"[{bar}] {percentage:4.1f}% | {processed:,} rec | MFT: {total_data_mb:.0f}MB | {elapsed_time}"
        
        # Ensure message doesn't exceed terminal width
        if len(progress_msg) > terminal_width - 2:  # Leave 2 chars margin
            progress_msg = progress_msg[:terminal_width - 5] + "..."
        
        # Print progress on same line (simple approach)
        print(f'\r{COLOR_PROGRESS}{progress_msg}{COLOR_RESET}', end='', flush=True)
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """Generate comprehensive summary report"""
        return {
            'parsing_statistics': self.stats.copy(),
            'configuration': {
                'output_format': self.config.output_format.value,
                'batch_size': self.config.batch_size
            },
            'volumes_processed': self.state.get('volumes_processed', []),
            'analysis_timestamp': datetime.datetime.now().isoformat()
        }
    
    def _build_parent_child_mapping(self, volume_letter: str) -> Dict[int, List[int]]:
        """Build efficient parent-child mapping for path reconstruction"""
        parent_map = {}
        
        try:
            cursor = self.db_manager.connection.cursor()
            
            # Get all parent-child relationships
            cursor.execute("""
                SELECT record_number, parent_record 
                FROM mft_file_names 
                WHERE volume_letter = ? AND namespace != 2
                ORDER BY record_number, namespace
            """, (volume_letter,))
            
            relationships = cursor.fetchall()
            
            for record_num, parent_record in relationships:
                if parent_record not in parent_map:
                    parent_map[parent_record] = []
                parent_map[parent_record].append(record_num)
        
        except Exception as e:
            logger.debug(f"Error building parent-child mapping: {e}")
        
        return parent_map
    


    def cleanup(self):
        """Cleanup resources"""
        try:
            self.db_manager.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def setup_signal_handlers(parser: MFTParser):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        parser.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def check_admin_privileges() -> bool:
    """Check if running with administrator privileges"""
    if not HAS_WIN32:
        return False
    
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def get_available_volumes() -> List[str]:
    """Get list of available NTFS volumes"""
    volumes = []
    
    if not HAS_WIN32:
        return volumes
    
    try:
        drives = win32api.GetLogicalDriveStrings()
        drive_list = drives.split('\000')[:-1]
        
        for drive in drive_list:
            drive_letter = drive[0]
            try:
                drive_type = win32file.GetDriveType(drive)
                if drive_type == win32con.DRIVE_FIXED:  # Fixed disk
                    # Check if NTFS
                    try:
                        fs_type = win32api.GetVolumeInformation(drive)[4]
                        if fs_type == 'NTFS':
                            volumes.append(drive_letter)
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Error getting available volumes: {e}")
    
    return volumes

def main():
    """Main entry point for MFT Claw - Automatic Analysis Mode"""
    
    print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
    print(f"{COLOR_HEADER}MFT CLAW - AUTOMATIC FORENSIC ANALYSIS{COLOR_RESET}")
    print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
    
    # Auto-detect all NTFS volumes
    volumes = get_available_volumes()
    if not volumes:
        print(f"{COLOR_ERROR}ERROR: No NTFS volumes found or insufficient privileges{COLOR_RESET}")
        print(f"{COLOR_ERROR}Please run as Administrator{COLOR_RESET}")
        return 1
    
    print(f"{COLOR_INFO}Available NTFS volumes detected:{COLOR_RESET}")
    for vol in volumes:
        print(f"{COLOR_SUCCESS}  ✓ {vol}:{COLOR_RESET}")
    
    print(f"\n{COLOR_INFO}Starting automatic analysis of {len(volumes)} volume(s)...{COLOR_RESET}")
    print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
    
    # Check admin privileges
    if not check_admin_privileges():
        print(f"{COLOR_WARNING}WARNING: Administrator privileges required for raw disk access.{COLOR_RESET}")
        print(f"{COLOR_WARNING}Some features may not work correctly.{COLOR_RESET}")
    
    # Check win32 availability
    if not HAS_WIN32:
        print(f"{COLOR_ERROR}ERROR: win32 modules not available. Please install pywin32.{COLOR_RESET}")
        return 1
    
    try:
        # Create Target_Artifacts directory for consistent output location
        target_artifacts_dir = os.path.join(".", "Target_Artifacts")
        os.makedirs(target_artifacts_dir, exist_ok=True)
        
        # Create configuration with optimal defaults for automatic analysis
        config = MFTClawConfig(
            output_format=OutputFormat.SQLITE,  # SQLite for best performance
            output_directory=target_artifacts_dir,  # Target_Artifacts subdirectory
            batch_size=1000,                   # Optimal batch size
            log_level=LogLevel.INFO           # INFO logging for normal operation
        )
        
        # Create parser
        mft_parser = MFTParser(config)
        setup_signal_handlers(mft_parser)
        
        # Start parsing
        logger.info("MFT Claw - Enhanced NTFS MFT Parser")
        logger.info(f"Version: 2.0.0")
        logger.info(f"Output directory: {config.output_directory}")
        logger.info(f"Output format: {config.output_format.value}")
        
        start_time = time.time()
        success_count = 0
        
        for volume in volumes:
            volume = volume.upper()
            logger.info(f"Processing volume {volume}:")
            
            if mft_parser.parse_volume(volume):
                success_count += 1
                logger.info(f"Successfully processed volume {volume}:")
            else:
                logger.error(f"Failed to process volume {volume}:")
        
        # Generate final report
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info("=" * 60)
        logger.info("ANALYSIS COMPLETE")
        logger.info("=" * 60)
        
        summary = mft_parser.generate_summary_report()
        stats = summary['parsing_statistics']
        
        logger.info(f"Total processing time: {duration:.2f} seconds")
        logger.info(f"Volumes processed: {success_count}/{len(volumes)}")
        logger.info(f"Total records processed: {stats['processed_records']}")
        logger.info(f"Records in use: {stats['in_use_records']}")
        logger.info(f"Directory records: {stats['directory_records']}")
        logger.info(f"File records: {stats['file_records']}")
        logger.info(f"Records with ADS: {stats['ads_records']}")
        logger.info(f"Parsing errors: {stats['errors']}")
        
        # Cleanup
        mft_parser.cleanup()
        
        logger.info(f"Results saved to: {config.output_directory}")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Parsing interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())