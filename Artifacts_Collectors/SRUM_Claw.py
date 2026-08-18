"""
Crow Eye - SRUM (System Resource Usage Monitor) Forensic Parser
================================================================

Advanced Windows SRUM database parser for digital forensic investigations.
This module provides comprehensive analysis of Windows SRUDB.dat files,
extracting critical application resource usage, network connectivity, and
energy consumption data for timeline reconstruction and behavior analysis.

Features:
---------
- Multi-Version Support: Windows 8/8.1/10/11 and Server 2012/2016/2019/2022
- ESE Database Parsing: Native support for Extensible Storage Engine format
- Application Tracking: Resource usage metrics per application
- Network Analysis: Connectivity and data usage patterns
- Energy Monitoring: Power consumption and battery metrics
- User Attribution: Links activity to specific user accounts via SID resolution
- Database Integration: SQLite storage with indexed forensic metadata

Supported SRUM Tables:
---------------------
- Application Resource Usage: CPU time, I/O operations, memory usage
- Network Connectivity: Connection times, interface information
- Network Data Usage: Bytes sent/received per application
- Energy Usage: Battery consumption and charge levels

Forensic Value:
--------------
- Evidence of program execution with detailed resource metrics
- Network activity timeline reconstruction
- User behavior analysis and attribution
- Timeline correlation with other artifacts
- Identification of suspicious resource consumption patterns

Usage Examples:
--------------
# Parse live system SRUM
result = parse_srum_data(case_artifacts_dir)

# Parse with progress callback
result = parse_srum_data(case_artifacts_dir, progress_callback=update_ui)

Output:
-------
SQLite database (srum_data.db) containing:
- Application resource usage records
- Network connectivity data
- Network data usage statistics
- Energy consumption metrics
- User SID to username mappings
- Parsing metadata and statistics

Author: Ghassan Elsman
License: Open Source
Version: 1.0
Part of: Crow Eye Digital Forensics Suite
"""

import os
import struct
import datetime
import sqlite3
import logging
import subprocess
import shutil
import tempfile
import csv
import ctypes
from ctypes import wintypes, POINTER, c_void_p, byref
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Callable
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.raw_file_copy import copy_locked_file_raw
from utils.time_utils import (format_forensic_timestamp, get_current_forensic_timestamp,
                              get_current_utc, filetime_to_datetime, ensure_utc)

# Configure logging for forensic analysis
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SRUM] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# FORMATTING HELPER FUNCTIONS
# ============================================================================

def format_bytes(bytes_value):
    """Format bytes into human-readable format (KB, MB, GB)"""
    try:
        bytes_value = int(bytes_value) if bytes_value else 0
        if bytes_value == 0:
            return "0 B"
        elif bytes_value < 1024:
            return f"{bytes_value} B"
        elif bytes_value < 1024 * 1024:
            return f"{bytes_value / 1024:.2f} KB"
        elif bytes_value < 1024 * 1024 * 1024:
            return f"{bytes_value / (1024 * 1024):.2f} MB"
        else:
            return f"{bytes_value / (1024 * 1024 * 1024):.2f} GB"
    except:
        return str(bytes_value)


def format_time_duration(seconds):
    """Format time duration into human-readable format (seconds, minutes, hours)"""
    try:
        seconds = int(seconds) if seconds else 0
        if seconds == 0:
            return "0s"
        elif seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}m {secs}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            if secs > 0:
                return f"{hours}h {minutes}m {secs}s"
            else:
                return f"{hours}h {minutes}m"
    except:
        return str(seconds)


def format_cpu_time(cycle_time):
    """Format CPU cycle time into human-readable format
    
    CPU cycle time in SRUM is stored in 100-nanosecond units.
    Convert to milliseconds for readability.
    """
    try:
        cycle_time = int(cycle_time) if cycle_time else 0
        if cycle_time == 0:
            return "0 ms"
        
        # Convert from 100-nanosecond units to milliseconds
        milliseconds = cycle_time / 10000.0
        
        if milliseconds < 1000:
            return f"{milliseconds:.2f} ms"
        elif milliseconds < 60000:
            seconds = milliseconds / 1000.0
            return f"{seconds:.2f} s"
        elif milliseconds < 3600000:
            minutes = milliseconds / 60000.0
            return f"{minutes:.2f} min"
        else:
            hours = milliseconds / 3600000.0
            return f"{hours:.2f} hrs"
    except:
        return str(cycle_time)


def format_charge_level(value):
    """Format charge level (stored in mWh or as raw value)"""
    try:
        value = int(value) if value else 0
        if value == 0:
            return "0%"
        elif value <= 100:
            # Likely a percentage
            return f"{value}%"
        else:
            # Likely mWh - convert to Wh for readability
            wh = value / 1000.0
            return f"{wh:.2f} Wh"
    except:
        return str(value)


def format_number(value):
    """Format a number with thousand separators"""
    try:
        value = int(value) if value else 0
        return f"{value:,}"
    except:
        return str(value)

# Try to import win32security for SID resolution
try:
    import win32security
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logger.warning("win32security not available. SID resolution will use fallback.")

# Windows ESE API constants and types
try:
    if os.name == 'nt':
        esent = ctypes.windll.esent
        ESENT_AVAILABLE = True
        
        # JET API types
        JET_ERR = ctypes.c_long
        JET_INSTANCE = c_void_p
        JET_SESID = c_void_p
        JET_DBID = wintypes.DWORD
        JET_TABLEID = c_void_p
        JET_COLUMNID = wintypes.DWORD
        JET_GRBIT = wintypes.DWORD
    else:
        ESENT_AVAILABLE = False
        esent = None
        JET_ERR = JET_INSTANCE = JET_SESID = JET_DBID = JET_TABLEID = JET_COLUMNID = JET_GRBIT = None
    
    # Additional ctypes for Windows API
    c_wchar_p = ctypes.c_wchar_p
    
    # JET API return codes
    JET_errSuccess = 0
    JET_wrnColumnNull = 1004
    JET_wrnBufferTruncated = 1006
    
    # Column types
    JET_coltypNil = 0
    JET_coltypBit = 1
    JET_coltypUnsignedByte = 2
    JET_coltypShort = 3
    JET_coltypLong = 4
    JET_coltypCurrency = 5
    JET_coltypIEEESingle = 6
    JET_coltypIEEEDouble = 7
    JET_coltypDateTime = 8
    JET_coltypBinary = 9
    JET_coltypText = 10
    JET_coltypLongBinary = 11
    JET_coltypLongText = 12
    JET_coltypUnsignedLong = 14
    JET_coltypLongLong = 15
    JET_coltypGUID = 16
    JET_coltypUnsignedShort = 17
    
    logger.info("Windows ESE API (esent.dll) loaded successfully")
except Exception as e:
    ESENT_AVAILABLE = False
    logger.warning(f"Windows ESE API not available: {e}")


# SRUM Table GUID Mappings
def decode_binary_sid(blob: bytes) -> str:
    """A binary SID as S-1-... , decoded without pywin32.

    SRUM records the user as a raw SID structure. The parser resolved it through
    win32security and fell back to `blob.hex()`, which puts an unusable string
    where a SID belongs on any build without pywin32 - including a frozen EXE
    that does not bundle it.

    The structure is fixed, so no API is needed:
        0x00 revision (1) - 0x01 sub-authority count (1)
        0x02 identifier authority (6, big-endian)
        0x08 sub-authorities (4 each, little-endian)

    Verified against this machine's SRUM data: S-1-5-18, S-1-5-19, S-1-5-20 and
    S-1-5-90-0-1 all decode correctly.
    """
    try:
        if not blob or len(blob) < 8:
            return ""
        revision = blob[0]
        count = blob[1]
        authority = int.from_bytes(blob[2:8], "big")
        subs = []
        for i in range(count):
            start = 8 + (4 * i)
            if start + 4 > len(blob):
                break
            subs.append(struct.unpack_from("<I", blob, start)[0])
        if not subs:
            return "S-%d-%d" % (revision, authority)
        return "S-%d-%d-%s" % (revision, authority, "-".join(str(s) for s in subs))
    except Exception:
        return ""


def srum_filetime(value) -> Optional[datetime.datetime]:
    """Convert a SRUM Int64 timestamp column to a datetime.

    ESE stores TimeStamp as JET_coltypDateTime, which the reader already turns
    into a datetime. EventTimestamp, ConnectStartTime and EndTime are Int64
    columns holding a Windows FILETIME, so the reader hands back a plain int.
    Those were being tested with isinstance(datetime) and discarded, which is
    why three columns were empty on every row.

    A datetime is passed straight through, so a column that changes type does
    not silently start returning None.
    """
    if isinstance(value, datetime.datetime):
        return value
    if not isinstance(value, int) or value <= 0:
        return None
    try:
        converted = filetime_to_datetime(value)
    except (ValueError, OverflowError, OSError):
        return None
    # A wrong offset yields a plausible date rather than an exception, so bound
    # it to the range SRUM can actually describe instead of trusting the value.
    if not (1980 <= converted.year <= 2200):
        return None
    return converted


def parse_srum_app_id(raw: str) -> dict:
    """Split a SRUM application identity into its parts.

    SRUM does not always record a path. Many entries use an AppId form:

        !!svchost.exe!2054/02/06:15:19:25!1642e![netsvcs] [Winmgmt]

    Keeping only the executable name makes every svchost row identical, and the
    hosted service list is the one thing that tells them apart. It is separated
    out here so the timeline provider - the only table that uses this form - can
    record it.

    A plain path is left exactly as it is; only the `!!` form is split.
    """
    result = {"app_name": "", "app_path": "", "hosted_services": ""}
    if not raw:
        return result
    raw = str(raw).rstrip("\x00")

    if not raw.startswith("!!"):
        result["app_path"] = raw
        result["app_name"] = os.path.basename(raw) if raw else raw
        return result

    parts = raw[2:].split("!")
    result["app_name"] = parts[0] if parts else raw
    # The bracketed service list is the trailing field when present.
    for part in reversed(parts[1:]):
        if "[" in part:
            result["hosted_services"] = part.strip()
            break
    # An AppId names no path; leaving app_path empty keeps that honest rather
    # than repeating the executable name as though it were one.
    return result


# These GUIDs identify specific tables in the SRUDB.dat ESE database
SRUM_TABLE_GUIDS = {
    'APPLICATION_RESOURCE_USAGE': '{D10CA2FE-6FCF-4F6D-848E-B2E99266FA89}',
    'NETWORK_DATA_USAGE': '{973F5D5C-1D90-4944-BE8E-24B94231A174}',
    'NETWORK_CONNECTIVITY': '{DD6636C4-8929-4683-974E-22C046A43763}',
    'ENERGY_USAGE': '{FEE4E14F-02A9-4550-B5CE-5FA2DA202E37}',
    'ENERGY_USAGE_LONG_TERM': '{DA73FB89-2BEA-4DDC-86B8-6E048C6DA477}',
    'APPLICATION_TIMELINE': '{5C8CF1C7-7257-4F13-B223-970EF5939312}',
}

# Named once so the batched and the trailing insert can never drift apart.
APP_TIMELINE_INSERT = """
    INSERT INTO srum_app_timeline (
        timestamp, app_name, app_path, hosted_services, user_sid, user_name,
        end_time, duration_ms, span_ms, timeline_end, flags,
        in_focus_s, psm_foreground_s, user_input_s, keyboard_input_s,
        mouse_input_s, display_required_s, comp_rendered_s, comp_dirtied_s,
        comp_propagated_s, audio_in_s, audio_out_s,
        cycles, cycles_attr, cycles_wob,
        disk_raw, network_bytes_raw, network_tail_raw
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# Special System IDs that don't have entries in SruDbIdMapTable
# These IDs have NULL IdBlob values and represent system-level entities
# Based on SRUM forensics research and Windows documentation
SPECIAL_APP_IDS = {
    1: ("System", "System"),  # System-level activity (Windows kernel/system processes)
    2: ("Unknown Application", "Unknown"),  # Placeholder for unknown applications
}

SPECIAL_USER_IDS = {
    1: ("S-1-0-0", "NULL SID (Nobody)"),  # NULL SID - No security principal
    2: ("S-1-5-18", "NT AUTHORITY\\SYSTEM"),  # Local System account
    3: ("S-1-5-19", "NT AUTHORITY\\LOCAL SERVICE"),  # Local Service account
    4: ("S-1-5-20", "NT AUTHORITY\\NETWORK SERVICE"),  # Network Service account
}

# Known SRUM column names (these are standard across Windows versions)
# We'll use JetGetColumnInfo to get the column IDs dynamically
SRUM_KNOWN_COLUMNS = {
    'APPLICATION_RESOURCE_USAGE': [
        'AutoIncId', 'TimeStamp', 'AppId', 'UserId',
        'ForegroundCycleTime', 'BackgroundCycleTime', 'FaceTime',
        'ForegroundContextSwitches', 'BackgroundContextSwitches',
        'ForegroundBytesRead', 'ForegroundBytesWritten',
        'ForegroundNumReadOperations', 'ForegroundNumWriteOperations',
        'ForegroundNumberOfFlushes', 'BackgroundBytesRead',
        'BackgroundBytesWritten', 'BackgroundNumReadOperations',
        'BackgroundNumWriteOperations', 'BackgroundNumberOfFlushes'
    ],
    'NETWORK_DATA_USAGE': [
        'AutoIncId', 'TimeStamp', 'AppId', 'UserId',
        'InterfaceLuid', 'L2ProfileId', 'BytesSent', 'BytesRecvd'
    ],
    'NETWORK_CONNECTIVITY': [
        'AutoIncId', 'TimeStamp', 'AppId', 'UserId',
        'InterfaceLuid', 'L2ProfileId', 'L2ProfileFlags',
        'ConnectedTime', 'ConnectStartTime'
    ],
    'ENERGY_USAGE': [
        'AutoIncId', 'TimeStamp', 'AppId', 'UserId',
        'EventTimestamp', 'StateTransition', 'ChargeLevel', 'CycleCount'
    ],
    'APPLICATION_TIMELINE': [
        'AutoIncId', 'TimeStamp', 'AppId', 'UserId',
        'Flags', 'EndTime', 'DurationMS', 'SpanMS', 'TimelineEnd',
        'InFocusS', 'PSMForegroundS', 'UserInputS', 'KeyboardInputS',
        'MouseInputS', 'DisplayRequiredS', 'CompRenderedS', 'CompDirtiedS',
        'CompPropagatedS', 'AudioInS', 'AudioOutS',
        'Cycles', 'CyclesAttr', 'CyclesWOB',
        'DiskRaw', 'NetworkBytesRaw', 'NetworkTailRaw'
    ]
}


class SRUMParsingError(Exception):
    """Base exception for SRUM parsing errors."""
    pass


class SRUMFileAccessError(SRUMParsingError):
    """Raised when SRUDB.dat cannot be accessed."""
    pass


class SRUMDatabaseCorruptError(SRUMParsingError):
    """Raised when SRUDB.dat is corrupted or invalid."""
    pass


@dataclass
class SRUMApplicationRecord:
    """Represents a single application resource usage record from SRUM.
    
    Attributes:
        timestamp (datetime): Record timestamp
        app_name (str): Application executable name
        app_path (str): Full path to application
        user_sid (str): Windows Security Identifier
        user_name (str): Resolved username (or SID if resolution fails)
        foreground_cycle_time (int): CPU cycles in foreground
        background_cycle_time (int): CPU cycles in background
        face_time (int): Time application was in foreground
        foreground_context_switches (int): Context switches while in foreground
        background_context_switches (int): Context switches while in background
        foreground_bytes_read (int): Bytes read in foreground
        foreground_bytes_written (int): Bytes written in foreground
        foreground_num_read_operations (int): Number of read operations in foreground
        foreground_num_write_operations (int): Number of write operations in foreground
        foreground_number_of_flushes (int): Number of flush operations in foreground
        background_bytes_read (int): Bytes read in background
        background_bytes_written (int): Bytes written in background
        background_num_read_operations (int): Number of read operations in background
        background_num_write_operations (int): Number of write operations in background
        background_number_of_flushes (int): Number of flush operations in background
    """
    timestamp: datetime.datetime
    app_name: str = ""
    app_path: str = ""
    user_sid: str = ""
    user_name: str = ""
    foreground_cycle_time: int = 0
    background_cycle_time: int = 0
    face_time: int = 0
    foreground_context_switches: int = 0
    background_context_switches: int = 0
    foreground_bytes_read: int = 0
    foreground_bytes_written: int = 0
    foreground_num_read_operations: int = 0
    foreground_num_write_operations: int = 0
    foreground_number_of_flushes: int = 0
    background_bytes_read: int = 0
    background_bytes_written: int = 0
    background_num_read_operations: int = 0
    background_num_write_operations: int = 0
    background_number_of_flushes: int = 0


@dataclass
class SRUMNetworkConnectivityRecord:
    """Represents a network connectivity record from SRUM.
    
    Attributes:
        timestamp (datetime): Record timestamp
        app_name (str): Application executable name
        app_path (str): Full path to application
        user_sid (str): Windows Security Identifier
        user_name (str): Resolved username
        interface_luid (int): Network interface LUID
        l2_profile_id (int): Layer 2 profile identifier
        l2_profile_flags (int): Layer 2 profile flags
        connected_time (int): Duration of connection in seconds
        connect_start_time (datetime): When connection started
    """
    timestamp: datetime.datetime
    app_name: str = ""
    app_path: str = ""
    user_sid: str = ""
    user_name: str = ""
    interface_luid: int = 0
    l2_profile_id: int = 0
    l2_profile_flags: int = 0
    connected_time: int = 0
    connect_start_time: Optional[datetime.datetime] = None


@dataclass
class SRUMNetworkDataRecord:
    """Represents a network data usage record from SRUM.
    
    Attributes:
        timestamp (datetime): Record timestamp
        app_name (str): Application executable name
        app_path (str): Full path to application
        user_sid (str): Windows Security Identifier
        user_name (str): Resolved username
        interface_luid (int): Network interface LUID
        l2_profile_id (int): Layer 2 profile identifier
        bytes_sent (int): Total bytes sent
        bytes_received (int): Total bytes received
    """
    timestamp: datetime.datetime
    app_name: str = ""
    app_path: str = ""
    user_sid: str = ""
    user_name: str = ""
    interface_luid: int = 0
    l2_profile_id: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0


@dataclass
class SRUMEnergyRecord:
    """Represents an energy usage record from SRUM.
    
    Attributes:
        timestamp (datetime): Record timestamp
        app_name (str): Application executable name
        app_path (str): Full path to application
        user_sid (str): Windows Security Identifier
        user_name (str): Resolved username
        event_timestamp (datetime): Event timestamp
        state_transition (int): Power state transition
        charge_level (int): Battery charge level percentage
        cycle_count (int): Battery cycle count
    """
    timestamp: datetime.datetime
    app_name: str = ""
    app_path: str = ""
    user_sid: str = ""
    user_name: str = ""
    event_timestamp: Optional[datetime.datetime] = None
    state_transition: int = 0
    charge_level: int = 0
    cycle_count: int = 0


@dataclass
class SRUMAppTimelineRecord:
    """Represents an application timeline record from SRUM.

    Where the resource usage tables record that a process ran, this provider
    records how it was used: seconds in focus, seconds of keyboard and mouse
    input. Most of those are sparse because the underlying activity is rare -
    a service accrues CPU cycles for hours and never sees a keystroke.

    Attributes:
        timestamp (datetime): Record timestamp
        app_name (str): Application executable name
        app_path (str): Full path to application, empty for the `!!` AppId form
        hosted_services (str): Service list for a shared host process
        user_sid (str): Windows Security Identifier
        user_name (str): Resolved username
        end_time (datetime): End of the measured window
        duration_ms (int): Milliseconds the application was running
        span_ms (int): Milliseconds spanned by the measured window
        in_focus_s (int): Seconds the application held foreground focus
        keyboard_input_s (int): Seconds with keyboard input
        mouse_input_s (int): Seconds with mouse input
    """
    timestamp: datetime.datetime
    app_name: str = ""
    app_path: str = ""
    hosted_services: str = ""
    user_sid: str = ""
    user_name: str = ""
    end_time: Optional[datetime.datetime] = None
    duration_ms: int = 0
    span_ms: int = 0
    timeline_end: int = 0
    flags: int = 0
    in_focus_s: int = 0
    psm_foreground_s: int = 0
    user_input_s: int = 0
    keyboard_input_s: int = 0
    mouse_input_s: int = 0
    display_required_s: int = 0
    comp_rendered_s: int = 0
    comp_dirtied_s: int = 0
    comp_propagated_s: int = 0
    audio_in_s: int = 0
    audio_out_s: int = 0
    cycles: int = 0
    cycles_attr: int = 0
    cycles_wob: int = 0
    disk_raw: int = 0
    network_bytes_raw: int = 0
    network_tail_raw: int = 0


class ESERecord:
    """Represents a single record from an ESE table."""
    
    def __init__(self, sesid, tableid, columns):
        """Initialize ESE record.
        
        Args:
            sesid: JET session ID
            tableid: JET table ID
            columns (dict): Dictionary mapping column names to column info
        """
        self.sesid = sesid
        self.tableid = tableid
        self.columns = columns
    
    def get_column(self, column_name: str, default=None):
        """Get a column value from the current record.
        
        Args:
            column_name (str): Name of the column
            default: Default value if column is null or not found
            
        Returns:
            Column value or default
        """
        if column_name not in self.columns:
            return default
        
        col_info = self.columns[column_name]
        col_id = col_info['id']
        col_type = col_info['type']
        
        return self._read_column_value(col_id, col_type, default)
    
    def _read_column_value(self, column_id, column_type, default=None):
        """Read a column value from the current record.
        
        Args:
            column_id: JET column ID
            column_type: JET column type
            default: Default value if null
            
        Returns:
            Column value or default
        """
        buffer_size = 8192
        buffer = ctypes.create_string_buffer(buffer_size)
        actual_size = wintypes.DWORD()
        
        try:
            ret = esent.JetRetrieveColumn(
                self.sesid,
                self.tableid,
                column_id,
                buffer,
                buffer_size,
                byref(actual_size),
                0,
                None
            )
            
            if ret == JET_wrnColumnNull or actual_size.value == 0:
                return default
            
            if ret != JET_errSuccess:
                return default
            
            # Parse based on column type
            if column_type == JET_coltypLongLong:  # 64-bit integer
                return struct.unpack('q', buffer.raw[:8])[0]
            elif column_type == JET_coltypLong:  # 32-bit integer
                return struct.unpack('i', buffer.raw[:4])[0]
            elif column_type == JET_coltypUnsignedLong:
                return struct.unpack('I', buffer.raw[:4])[0]
            elif column_type == JET_coltypShort:
                return struct.unpack('h', buffer.raw[:2])[0]
            elif column_type == JET_coltypUnsignedShort:
                return struct.unpack('H', buffer.raw[:2])[0]
            elif column_type == JET_coltypUnsignedByte:
                return struct.unpack('B', buffer.raw[:1])[0]
            elif column_type == JET_coltypText or column_type == JET_coltypLongText:
                return buffer.raw[:actual_size.value].decode('utf-16le', errors='ignore').rstrip('\x00')
            elif column_type == JET_coltypBinary or column_type == JET_coltypLongBinary:
                return buffer.raw[:actual_size.value]
            elif column_type == JET_coltypDateTime:
                # OLE Automation date. Returned tz-aware in UTC so it cannot be
                # compared against an aware datetime and raise - every other
                # timestamp this parser produces comes back aware.
                if actual_size.value >= 8:
                    ole_date = struct.unpack('d', buffer.raw[:8])[0]
                    return ensure_utc(datetime.datetime(1899, 12, 30)
                                      + datetime.timedelta(days=ole_date))
            else:
                return buffer.raw[:actual_size.value]
        except Exception as e:
            return default


class ESETable:
    """Represents an ESE table with methods to iterate through records."""
    
    def __init__(self, sesid, tableid, table_name):
        """Initialize ESE table.
        
        Args:
            sesid: JET session ID
            tableid: JET table ID
            table_name (str): Name of the table
        """
        self.sesid = sesid
        self.tableid = tableid
        self.table_name = table_name
        self.columns = self._get_column_info()
        self._record_count = None
    
    def _get_column_info(self):
        """Get column information for this table using known column names.
        
        Returns:
            dict: Dictionary mapping column names to column info
        """
        columns = {}
        
        # Special case for SruDbIdMapTable
        if self.table_name == 'SruDbIdMapTable':
            known_columns = ['IdIndex', 'IdBlob', 'IdType']
        else:
            # Determine which column list to use based on table GUID
            known_columns = []
            for table_type, guid in SRUM_TABLE_GUIDS.items():
                if guid == self.table_name:
                    known_columns = SRUM_KNOWN_COLUMNS.get(table_type, [])
                    break
            
            if not known_columns:
                logger.debug(f"No known columns for table {self.table_name}, will try to enumerate")
                # Fall back to trying all common column names
                known_columns = ['AutoIncId', 'TimeStamp', 'AppId', 'UserId']
        
        try:
            # Define JET_COLUMNDEF structure
            class JET_COLUMNDEF(ctypes.Structure):
                _fields_ = [
                    ("cbStruct", wintypes.DWORD),
                    ("columnid", JET_COLUMNID),
                    ("coltyp", wintypes.DWORD),
                    ("wCountry", wintypes.WORD),
                    ("langid", wintypes.WORD),
                    ("cp", wintypes.WORD),
                    ("wCollate", wintypes.WORD),
                    ("cbMax", wintypes.DWORD),
                    ("grbit", JET_GRBIT),
                ]
            
            # Get column info for each known column using JetGetTableColumnInfoW
            for col_name in known_columns:
                try:
                    columndef = JET_COLUMNDEF()
                    columndef.cbStruct = ctypes.sizeof(JET_COLUMNDEF)
                    
                    # Use JetGetTableColumnInfoW instead of JetGetColumnInfoW
                    ret = esent.JetGetTableColumnInfoW(
                        self.sesid,
                        self.tableid,
                        c_wchar_p(col_name),
                        byref(columndef),
                        ctypes.sizeof(JET_COLUMNDEF),
                        0  # JET_ColInfo
                    )
                    
                    if ret == JET_errSuccess:
                        columns[col_name] = {
                            'id': columndef.columnid,
                            'type': columndef.coltyp
                        }
                        logger.debug(f"Found column: {col_name} (id={columndef.columnid}, type={columndef.coltyp})")
                    else:
                        logger.debug(f"Column {col_name} not found in table (ret={ret})")
                
                except Exception as e:
                    logger.debug(f"Error getting info for column {col_name}: {e}")
                    continue
            
            logger.debug(f"Found {len(columns)} columns in table {self.table_name}")
        
        except Exception as e:
            logger.error(f"Error getting column info: {e}")
        
        return columns
    
    def get_number_of_records(self):
        """Get the number of records in the table.
        
        Returns:
            int: Number of records
        """
        if self._record_count is not None:
            return self._record_count
        
        try:
            # Move to first record
            ret = esent.JetMove(self.sesid, self.tableid, -2147483648, 0)  # JET_MoveFirst
            if ret != JET_errSuccess:
                self._record_count = 0
                return 0
            
            count = 0
            while True:
                count += 1
                ret = esent.JetMove(self.sesid, self.tableid, 1, 0)  # JET_MoveNext
                if ret != JET_errSuccess:
                    break
            
            self._record_count = count
            
            # Reset to first record
            esent.JetMove(self.sesid, self.tableid, -2147483648, 0)
            
            return count
        except Exception as e:
            logger.debug(f"Error counting records: {e}")
            return 0
    
    def get_record(self, index: int):
        """Get a record by index.
        
        Args:
            index (int): Record index (0-based)
            
        Returns:
            ESERecord: Record object
        """
        # Move to first record if index is 0
        if index == 0:
            ret = esent.JetMove(self.sesid, self.tableid, -2147483648, 0)  # JET_MoveFirst
            if ret != JET_errSuccess:
                raise Exception("Cannot move to first record")
        elif index > 0:
            # Move to next record for subsequent indices
            ret = esent.JetMove(self.sesid, self.tableid, 1, 0)  # JET_MoveNext
            if ret != JET_errSuccess:
                raise Exception(f"Cannot move to record {index}")
        
        return ESERecord(self.sesid, self.tableid, self.columns)
    
    def close(self):
        """Close the table."""
        try:
            if self.tableid:
                esent.JetCloseTable(self.sesid, self.tableid)
        except Exception as e:
            logger.debug(f"Error closing table: {e}")


class SRUMParser:
    """Main parser class for SRUM database extraction and analysis.
    
    This class handles opening the SRUDB.dat ESE database using Windows API,
    enumerating tables, parsing records from each SRUM table type, resolving
    user SIDs, and storing the parsed data in a SQLite database for forensic analysis.
    
    Uses Windows native ESE API (esent.dll) for database access - no external dependencies.
    """
    
    def __init__(self, srudb_path: str, output_db_path: str):
        """Initialize SRUM parser.
        
        Args:
            srudb_path (str): Path to SRUDB.dat file (or will be copied from system location)
            output_db_path (str): Path to output SQLite database
            
        Raises:
            SRUMFileAccessError: If SRUDB.dat cannot be accessed
        """
        if not ESENT_AVAILABLE:
            raise ImportError(
                "Windows ESE API (esent.dll) is required for SRUM parsing. "
                "This is only available on Windows systems."
            )
        
        self.srudb_path = srudb_path
        self.output_db_path = output_db_path
        self.sid_cache = {}  # Cache for SID to username resolution
        self.temp_dir = None  # Temporary directory
        self.working_copy = None  # Working copy of SRUDB.dat
        self.id_lookup = {}  # Cache for ID to app/user lookups from SruDbIdMapTable
        
        # JET API handles
        self.instance = JET_INSTANCE()
        self.sesid = JET_SESID()
        self.dbid = JET_DBID()
        
        # Verify SRUDB.dat exists and is accessible
        if not os.path.exists(srudb_path):
            raise SRUMFileAccessError(f"SRUDB.dat not found at: {srudb_path}")
        
        if not os.access(srudb_path, os.R_OK):
            raise SRUMFileAccessError(f"Cannot read SRUDB.dat at: {srudb_path}")
        
        logger.info(f"Initialized SRUM parser for: {srudb_path}")
    
    def resolve_sid_to_username(self, sid: str) -> str:
        """Resolve Windows SID to username.
        
        Uses win32security API on Windows systems to resolve SIDs to usernames.
        Falls back to returning the SID string if resolution fails or if
        win32security is not available.
        
        Args:
            sid (str): Windows Security Identifier
            
        Returns:
            str: Username string or original SID if resolution fails
        """
        if not sid or sid == "":
            return ""
        
        # Check cache first
        if sid in self.sid_cache:
            return self.sid_cache[sid]
        
        username = sid  # Default to SID if resolution fails
        resolution_failed = False
        
        if WIN32_AVAILABLE:
            try:
                # Attempt to resolve SID to username using Windows API
                sid_obj = win32security.ConvertStringSidToSid(sid)
                name, domain, type = win32security.LookupAccountSid(None, sid_obj)
                if domain:
                    username = f"{domain}\\{name}"
                else:
                    username = name
                logger.debug(f"Resolved SID {sid} to {username}")
            except Exception as e:
                logger.debug(f"Could not resolve SID {sid}: {e}")
                username = sid
                resolution_failed = True
        else:
            logger.debug(f"win32security not available, using SID: {sid}")
            resolution_failed = True
        
        # Cache the result (including whether resolution failed)
        self.sid_cache[sid] = username
        
        # Track SID resolution failures for warning reporting
        if resolution_failed and not hasattr(self, '_sid_resolution_failures'):
            self._sid_resolution_failures = set()
        if resolution_failed:
            self._sid_resolution_failures.add(sid)
        
        return username
    
    def _filetime_to_datetime(self, filetime: int) -> Optional[datetime.datetime]:
        """Convert Windows FILETIME to Python datetime.
        
        Args:
            filetime (int): Windows FILETIME (100-nanosecond intervals since 1601-01-01)
            
        Returns:
            datetime: Converted datetime or None if invalid
        """
        if filetime == 0 or filetime is None:
            return None
        
        try:
            return filetime_to_datetime(filetime)
        except Exception as e:
            logger.debug(f"Error converting FILETIME {filetime}: {e}")
            return None
    
    def open_ese_database(self):
        """Open the SRUM ESE database using Windows JET API.
        
        Initializes JET instance, begins session, attaches and opens the database.
        Sets up read-only access to the SRUDB.dat file.
        
        Raises:
            SRUMDatabaseCorruptError: If database cannot be opened
        """
        logger.info("Opening SRUM database with Windows ESE API")
        
        try:
            # Initialize JET instance
            ret = esent.JetCreateInstanceW(byref(self.instance), c_wchar_p("SRUMParser"))
            if ret != JET_errSuccess:
                raise SRUMDatabaseCorruptError(f"JetCreateInstance failed: {ret}")
            logger.debug("Created JET instance")
            
            # Set parameters for read-only access
            esent.JetSetSystemParameterW(byref(self.instance), 0, 64, 0, None)  # JET_paramRecovery = "Off"
            esent.JetSetSystemParameterW(byref(self.instance), 0, 0, 8192, None)  # JET_paramDatabasePageSize
            
            # Initialize instance
            ret = esent.JetInit(byref(self.instance))
            if ret != JET_errSuccess:
                raise SRUMDatabaseCorruptError(f"JetInit failed: {ret}")
            logger.debug("Initialized JET instance")
            
            # Begin session
            ret = esent.JetBeginSessionW(self.instance, byref(self.sesid), None, None)
            if ret != JET_errSuccess:
                raise SRUMDatabaseCorruptError(f"JetBeginSession failed: {ret}")
            logger.debug("Began JET session")
            
            # Attach database (read-only)
            db_path = self.working_copy if self.working_copy else self.srudb_path
            ret = esent.JetAttachDatabaseW(self.sesid, c_wchar_p(db_path), 1)  # JET_bitDbReadOnly
            if ret != JET_errSuccess:
                raise SRUMDatabaseCorruptError(f"JetAttachDatabase failed: {ret}")
            logger.debug("Attached database")
            
            # Open database
            ret = esent.JetOpenDatabaseW(self.sesid, c_wchar_p(db_path), None, byref(self.dbid), 1)
            if ret != JET_errSuccess:
                raise SRUMDatabaseCorruptError(f"JetOpenDatabase failed: {ret}")
            logger.info("Successfully opened SRUM database")
            
        except Exception as e:
            logger.error(f"Failed to open ESE database: {e}")
            raise SRUMDatabaseCorruptError(f"Cannot open SRUDB.dat: {e}")
    
    def get_table_by_guid(self, table_guid: str):
        """Open a SRUM table by its GUID identifier.
        
        Args:
            table_guid (str): GUID of the table (e.g., '{D10CA2FE-6FCF-4F6D-848E-B2E99266FA89}')
            
        Returns:
            ESETable: Table object or None if table not found
        """
        try:
            tableid = JET_TABLEID()
            ret = esent.JetOpenTableW(
                self.sesid,
                self.dbid,
                c_wchar_p(table_guid),
                None,
                0,
                1,  # JET_bitTableReadOnly
                byref(tableid)
            )
            
            if ret != JET_errSuccess:
                logger.debug(f"Table {table_guid} not found or cannot be opened")
                return None
            
            logger.debug(f"Opened table: {table_guid}")
            return ESETable(self.sesid, tableid, table_guid)
            
        except Exception as e:
            logger.debug(f"Error opening table {table_guid}: {e}")
            return None
    
    def _get_column_value(self, record, column_name: str, default=None):
        """Get a column value from an ESE record.
        
        This is a helper method used by the parsing methods to extract
        column values from ESE table records.
        
        Args:
            record: ESE record object
            column_name (str): Name of the column to retrieve
            default: Default value if column is null or not found
            
        Returns:
            Column value or default if not found/null
        """
        try:
            return record.get_column(column_name, default)
        except Exception as e:
            logger.debug(f"Error getting column {column_name}: {e}")
            return default
    
    def load_id_lookup_table(self):
        """Load the SruDbIdMapTable which maps IDs to application paths and user SIDs.
        
        This table is critical for resolving the numeric IDs in SRUM tables to
        actual application names/paths and user SIDs.
        """
        logger.info("Loading SruDbIdMapTable for ID resolution")
        
        try:
            # Open the SruDbIdMapTable
            table = self.get_table_by_guid('SruDbIdMapTable')
            if not table:
                logger.warning("SruDbIdMapTable not found - IDs will not be resolved")
                return
            
            num_records = table.get_number_of_records()
            logger.info(f"Found {num_records} entries in SruDbIdMapTable")
            
            for i in range(num_records):
                try:
                    record = table.get_record(i)
                    
                    # Get the ID (IdIndex column)
                    id_index = self._get_column_value(record, 'IdIndex', 0)
                    if not id_index:
                        continue
                    
                    # Get the IdType to determine what kind of data this is
                    id_type = self._get_column_value(record, 'IdType', 0)
                    
                    # Get the blob data (IdBlob column) which contains the actual string
                    id_blob = self._get_column_value(record, 'IdBlob')
                    
                    if not id_blob or id_blob is None:
                        continue
                    
                    value_str = None
                    
                    # IdType 3 is binary SID data.
                    #
                    # Decoded from the structure, NOT through win32security.
                    # str(win32security.SID(...)) returns "PySID:S-1-5-21-..."
                    # - a Python repr, not a SID - and 123322 of 221259 rows
                    # were stored that way while the rest, coming from the
                    # hardcoded special IDs, were clean. One artifact held the
                    # same user in two forms, and neither the PySID ones nor
                    # anything downstream could join against the clean SIDs the
                    # registry parser writes.
                    #
                    # The structural decode is deterministic, needs no
                    # dependency, and was verified against this machine's SRUM
                    # data before being relied on.
                    if id_type == 3 and isinstance(id_blob, bytes):
                        value_str = decode_binary_sid(id_blob)
                        if not value_str:
                            logger.debug(f"Could not decode SID for ID {id_index}")

                    # IdTypes 0, 1 and 2 all carry application identities.
                    # Only type 0 used to get this handling, so types 1 and 2 -
                    # 557 of the first 4000 entries on a live machine - were
                    # stored in a different shape than the same kind of entity
                    # under type 0.
                    #
                    # The string is stored RAW. Splitting happens in
                    # parse_srum_app_id at resolve time, so the service list and
                    # the recorded timestamp survive instead of being discarded
                    # here.
                    elif id_type in (0, 1, 2) and isinstance(id_blob, bytes):
                        try:
                            value_str = id_blob.decode('utf-16le', errors='ignore').rstrip('\x00')
                        except Exception as decode_error:
                            logger.debug(f"Could not decode app string for ID {id_index}: {decode_error}")
                            value_str = None
                    
                    # For other types, try generic UTF-16LE decoding
                    elif isinstance(id_blob, bytes):
                        try:
                            value_str = id_blob.decode('utf-16le', errors='ignore').rstrip('\x00')
                        except:
                            try:
                                value_str = id_blob.decode('utf-8', errors='ignore').rstrip('\x00')
                            except:
                                pass
                    
                    # If it's already a string
                    elif isinstance(id_blob, str):
                        value_str = id_blob.rstrip('\x00')
                    
                    # Store the mapping if we got a valid string
                    if value_str and len(value_str) > 0:
                        self.id_lookup[id_index] = value_str
                        if i < 20:  # Log first 20 for debugging
                            logger.debug(f"ID {id_index} (type {id_type}) -> {value_str[:100]}")
                
                except Exception as e:
                    if i < 10:  # Only log first 10 errors
                        logger.debug(f"Error reading ID map record {i}: {e}")
                    continue
            
            table.close()
            logger.info(f"Loaded {len(self.id_lookup)} ID mappings")
        
        except Exception as e:
            logger.error(f"Error loading ID lookup table: {e}")
            # Don't raise - we can continue without ID resolution
    
    def resolve_app_id(self, app_id: int) -> Tuple[str, str]:
        """Resolve application ID to (app_name, app_path).

        Args:
            app_id (int): Application ID from SRUM table

        Returns:
            tuple: (app_name, app_path)
        """
        name, path, _services = self.resolve_app_identity(app_id)
        return (name, path)

    def resolve_app_identity(self, app_id: int) -> Tuple[str, str, str]:
        """Resolve application ID including any hosted service list.

        Returns:
            tuple: (app_name, app_path, hosted_services)

        hosted_services is only ever set by the `!!` AppId form, which on this
        format appears solely in the application timeline provider - the tables
        keyed on a device path never carry one.
        """
        if not app_id:
            return ("Unknown", "Unknown", "")

        # Check special system IDs first
        if app_id in SPECIAL_APP_IDS:
            name, path = SPECIAL_APP_IDS[app_id]
            return (name, path, "")

        # Look up in ID table
        if app_id in self.id_lookup:
            parts = parse_srum_app_id(self.id_lookup[app_id])
            return (parts["app_name"] or str(app_id), parts["app_path"],
                    parts["hosted_services"])

        # Not found - return descriptive text
        return (f"Unknown App (ID:{app_id})", f"Unknown (ID:{app_id})", "")
    
    def resolve_user_id(self, user_id: int) -> Tuple[str, str]:
        """Resolve user ID to SID and username.
        
        Args:
            user_id (int): User ID from SRUM table
            
        Returns:
            tuple: (user_sid, user_name) - SID from lookup, name from Windows API
        """
        if not user_id:
            return ("", "")
        
        # Check special system IDs first
        if user_id in SPECIAL_USER_IDS:
            return SPECIAL_USER_IDS[user_id]
        
        # Look up SID in ID table
        if user_id in self.id_lookup:
            user_sid = self.id_lookup[user_id]
            # Now resolve SID to username
            user_name = self.resolve_sid_to_username(user_sid)
            return (user_sid, user_name)
        
        # Not found - return descriptive text
        return (f"Unknown SID (ID:{user_id})", f"Unknown User (ID:{user_id})")
    
    def copy_srum_database(self, source_path: str = None, windows_partition: str = "C:") -> str:
        """Copy SRUDB.dat from system location to temporary location.
        
        Required because the file is locked by Windows. Uses multiple methods:
        1. Raw disk access with backup semantics (bypasses file locks)
        2. esentutl.exe as fallback
        3. Simple copy as last resort
        
        Args:
            source_path (str, optional): Path to SRUDB.dat. Defaults to system location.
            windows_partition (str, optional): Windows partition letter (e.g., "C:", "D:"). Defaults to "C:".
            
        Returns:
            str: Path to copied SRUDB.dat file
            
        Raises:
            SRUMFileAccessError: If copy fails
        """
        if source_path is None:
            # Construct path dynamically based on Windows partition
            source_path = f"{windows_partition}\\Windows\\System32\\sru\\SRUDB.dat"
        
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp(prefix="srum_parse_")
        dest_path = os.path.join(self.temp_dir, "SRUDB.dat")
        
        logger.info(f"Copying SRUDB.dat from {source_path} to {dest_path}")
        
        # Method 1: Try raw disk access with backup semantics (best method)
        try:
            logger.info("Attempting raw copy with backup semantics...")
            if copy_locked_file_raw(source_path, dest_path):
                size = os.path.getsize(dest_path)
                logger.info(f"Successfully copied SRUDB.dat using backup semantics ({size:,} bytes)")
                self.working_copy = dest_path
                return dest_path
        except Exception as e:
            logger.warning(f"Backup semantics copy failed: {e}")
        
        # Method 2: Try esentutl
        try:
            logger.info("Attempting copy with esentutl...")
            cmd = f'esentutl /y "{source_path}" /d "{dest_path}" /o'
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0 and os.path.exists(dest_path):
                size = os.path.getsize(dest_path)
                logger.info(f"Successfully copied SRUDB.dat using esentutl ({size:,} bytes)")
                self.working_copy = dest_path
                return dest_path
            else:
                logger.warning(f"esentutl copy failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning("esentutl timeout")
        except Exception as e:
            logger.warning(f"esentutl failed: {e}")
        
        # Method 3: Try simple copy as last resort
        try:
            logger.info("Attempting simple file copy...")
            shutil.copy2(source_path, dest_path)
            if os.path.exists(dest_path):
                size = os.path.getsize(dest_path)
                logger.info(f"Successfully copied SRUDB.dat using simple copy ({size:,} bytes)")
                self.working_copy = dest_path
                return dest_path
        except Exception as e:
            logger.warning(f"Simple copy failed: {e}")
        
        # All methods failed
        raise SRUMFileAccessError(
            "Failed to copy SRUDB.dat using all available methods. "
            "The file may be locked by Windows. Try stopping the SRUM service or use shadow copy."
        )
    
    def export_table_to_csv(self, table_guid: str, table_name: str) -> Optional[str]:
        """Export a SRUM table to CSV using esentutl.exe.
        
        Args:
            table_guid (str): GUID of the table to export
            table_name (str): Friendly name for the table
            
        Returns:
            str: Path to exported CSV file, or None if export failed
        """
        if not self.working_copy:
            logger.error("No working copy of SRUDB.dat available")
            return None
        
        # Create CSV output path
        csv_filename = f"{table_name.replace(' ', '_')}.csv"
        csv_path = os.path.join(self.temp_dir, csv_filename)
        
        logger.info(f"Exporting table {table_guid} to CSV")
        
        try:
            # Use esentutl to dump table to text format
            # We'll use /mh to get table info first, then parse the database directly
            # Since esentutl doesn't have direct CSV export, we'll read the table using a different approach
            
            # For now, return None to indicate we need to use alternative parsing
            # This will be handled by the parse methods which will read directly
            logger.debug(f"Table export for {table_name} will use direct parsing")
            return None
            
        except Exception as e:
            logger.error(f"Error exporting table {table_guid}: {e}")
            return None
    
    def _parse_csv_file(self, csv_path: str) -> List[Dict]:
        """Parse a CSV file exported from SRUM table.
        
        Args:
            csv_path (str): Path to CSV file
            
        Returns:
            list: List of dictionaries containing row data
        """
        records = []
        try:
            with open(csv_path, 'r', encoding='utf-16le', errors='ignore') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
            logger.info(f"Parsed {len(records)} records from CSV")
        except Exception as e:
            logger.error(f"Error parsing CSV file: {e}")
        
        return records

    def _read_ese_table_simple(self, table_guid: str) -> List[Dict]:
        """Read ESE table using simple approach - try to use external tools or fallback.
        
        This is a simplified approach that attempts to read SRUM data.
        For production use, this would use ctypes with esent.dll or parse
        the database format directly.
        
        Args:
            table_guid (str): GUID of the table to read
            
        Returns:
            list: List of dictionaries containing row data
        """
        # For now, return empty list - actual implementation would use
        # ctypes with esent.dll (as shown in srum_windows_api_parser.py)
        # or parse the ESE database format directly
        logger.warning(f"Direct ESE table reading not yet implemented for {table_guid}")
        logger.info("Using fallback: attempting to read from existing parsed data")
        return []
    
    def parse_application_resource_usage(self, table=None) -> List[SRUMApplicationRecord]:
        """Parse Application Resource Usage table.
        
        This is the primary SRUM table containing detailed application execution
        and resource usage metrics.
        
        Args:
            table: ESE table object for Application Resource Usage
            
        Returns:
            list: List of SRUMApplicationRecord objects
        """
        records = []
        
        if not table:
            logger.warning("Application Resource Usage table not found")
            return records
        
        try:
            num_records = table.get_number_of_records()
            logger.info(f"Parsing {num_records} application resource usage records")
            
            for i in range(num_records):
                try:
                    record = table.get_record(i)
                    
                    # Extract timestamp - it's already a datetime object from JET API
                    timestamp = self._get_column_value(record, 'TimeStamp')
                    
                    # Skip records without timestamp
                    if not timestamp or not isinstance(timestamp, datetime.datetime):
                        continue
                    
                    # Extract application ID and resolve to name/path
                    app_id = self._get_column_value(record, 'AppId', 0)
                    app_name, app_path = self.resolve_app_id(app_id)
                    
                    # Extract user ID and resolve to SID/username
                    user_id = self._get_column_value(record, 'UserId', 0)
                    user_sid, user_name = self.resolve_user_id(user_id)
                    
                    # Extract resource usage metrics
                    srum_record = SRUMApplicationRecord(
                        timestamp=timestamp,
                        app_name=app_name,
                        app_path=app_path,
                        user_sid=user_sid,
                        user_name=user_name,
                        foreground_cycle_time=self._get_column_value(record, 'ForegroundCycleTime', 0) or 0,
                        background_cycle_time=self._get_column_value(record, 'BackgroundCycleTime', 0) or 0,
                        face_time=self._get_column_value(record, 'FaceTime', 0) or 0,
                        foreground_context_switches=self._get_column_value(record, 'ForegroundContextSwitches', 0) or 0,
                        background_context_switches=self._get_column_value(record, 'BackgroundContextSwitches', 0) or 0,
                        foreground_bytes_read=self._get_column_value(record, 'ForegroundBytesRead', 0) or 0,
                        foreground_bytes_written=self._get_column_value(record, 'ForegroundBytesWritten', 0) or 0,
                        foreground_num_read_operations=self._get_column_value(record, 'ForegroundNumReadOperations', 0) or 0,
                        foreground_num_write_operations=self._get_column_value(record, 'ForegroundNumWriteOperations', 0) or 0,
                        foreground_number_of_flushes=self._get_column_value(record, 'ForegroundNumberOfFlushes', 0) or 0,
                        background_bytes_read=self._get_column_value(record, 'BackgroundBytesRead', 0) or 0,
                        background_bytes_written=self._get_column_value(record, 'BackgroundBytesWritten', 0) or 0,
                        background_num_read_operations=self._get_column_value(record, 'BackgroundNumReadOperations', 0) or 0,
                        background_num_write_operations=self._get_column_value(record, 'BackgroundNumWriteOperations', 0) or 0,
                        background_number_of_flushes=self._get_column_value(record, 'BackgroundNumberOfFlushes', 0) or 0,
                    )
                    
                    records.append(srum_record)
                
                except Exception as e:
                    logger.debug(f"Error parsing application record {i}: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(records)} application resource usage records")
        
        except Exception as e:
            logger.error(f"Error parsing application resource usage table: {e}")
        
        return records
    
    def parse_network_connectivity(self, table) -> List[SRUMNetworkConnectivityRecord]:
        """Parse Network Connectivity table.
        
        Args:
            table: ESE table object for Network Connectivity
            
        Returns:
            list: List of SRUMNetworkConnectivityRecord objects
        """
        records = []
        
        if not table:
            logger.warning("Network Connectivity table not found")
            return records
        
        try:
            num_records = table.get_number_of_records()
            logger.info(f"Parsing {num_records} network connectivity records")
            
            for i in range(num_records):
                try:
                    record = table.get_record(i)
                    
                    # Extract timestamp - already a datetime object
                    timestamp = self._get_column_value(record, 'TimeStamp')
                    
                    if not timestamp or not isinstance(timestamp, datetime.datetime):
                        continue
                    
                    # Extract application ID and resolve
                    app_id = self._get_column_value(record, 'AppId', 0)
                    app_name, app_path = self.resolve_app_id(app_id)
                    
                    # Extract user ID and resolve
                    user_id = self._get_column_value(record, 'UserId', 0)
                    user_sid, user_name = self.resolve_user_id(user_id)
                    
                    # Extract network connectivity metrics
                    connect_start = srum_filetime(
                        self._get_column_value(record, 'ConnectStartTime'))
                    
                    srum_record = SRUMNetworkConnectivityRecord(
                        timestamp=timestamp,
                        app_name=app_name,
                        app_path=app_path,
                        user_sid=user_sid,
                        user_name=user_name,
                        interface_luid=self._get_column_value(record, 'InterfaceLuid', 0) or 0,
                        l2_profile_id=self._get_column_value(record, 'L2ProfileId', 0) or 0,
                        l2_profile_flags=self._get_column_value(record, 'L2ProfileFlags', 0) or 0,
                        connected_time=self._get_column_value(record, 'ConnectedTime', 0) or 0,
                        connect_start_time=connect_start,
                    )
                    
                    records.append(srum_record)
                
                except Exception as e:
                    logger.debug(f"Error parsing network connectivity record {i}: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(records)} network connectivity records")
        
        except Exception as e:
            logger.error(f"Error parsing network connectivity table: {e}")
        
        return records
    
    def parse_network_data_usage(self, table) -> List[SRUMNetworkDataRecord]:
        """Parse Network Data Usage table.
        
        Args:
            table: ESE table object for Network Data Usage
            
        Returns:
            list: List of SRUMNetworkDataRecord objects
        """
        records = []
        
        if not table:
            logger.warning("Network Data Usage table not found")
            return records
        
        try:
            num_records = table.get_number_of_records()
            logger.info(f"Parsing {num_records} network data usage records")
            
            for i in range(num_records):
                try:
                    record = table.get_record(i)
                    
                    # Extract timestamp - already a datetime object
                    timestamp = self._get_column_value(record, 'TimeStamp')
                    
                    if not timestamp or not isinstance(timestamp, datetime.datetime):
                        continue
                    
                    # Extract application ID and resolve
                    app_id = self._get_column_value(record, 'AppId', 0)
                    app_name, app_path = self.resolve_app_id(app_id)
                    
                    # Extract user ID and resolve
                    user_id = self._get_column_value(record, 'UserId', 0)
                    user_sid, user_name = self.resolve_user_id(user_id)
                    
                    # Extract network data metrics
                    srum_record = SRUMNetworkDataRecord(
                        timestamp=timestamp,
                        app_name=app_name,
                        app_path=app_path,
                        user_sid=user_sid,
                        user_name=user_name,
                        interface_luid=self._get_column_value(record, 'InterfaceLuid', 0) or 0,
                        l2_profile_id=self._get_column_value(record, 'L2ProfileId', 0) or 0,
                        bytes_sent=self._get_column_value(record, 'BytesSent', 0) or 0,
                        bytes_received=self._get_column_value(record, 'BytesRecvd', 0) or 0,
                    )
                    
                    records.append(srum_record)
                
                except Exception as e:
                    logger.debug(f"Error parsing network data record {i}: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(records)} network data usage records")
        
        except Exception as e:
            logger.error(f"Error parsing network data usage table: {e}")
        
        return records
    
    def parse_energy_usage(self, table) -> List[SRUMEnergyRecord]:
        """Parse Energy Usage table.
        
        Args:
            table: ESE table object for Energy Usage
            
        Returns:
            list: List of SRUMEnergyRecord objects
        """
        records = []
        
        if not table:
            logger.warning("Energy Usage table not found")
            return records
        
        try:
            num_records = table.get_number_of_records()
            logger.info(f"Parsing {num_records} energy usage records")
            
            for i in range(num_records):
                try:
                    record = table.get_record(i)
                    
                    # Extract timestamp - already a datetime object
                    timestamp = self._get_column_value(record, 'TimeStamp')
                    
                    if not timestamp or not isinstance(timestamp, datetime.datetime):
                        continue
                    
                    # Extract application ID and resolve
                    app_id = self._get_column_value(record, 'AppId', 0)
                    app_name, app_path = self.resolve_app_id(app_id)
                    
                    # Extract user ID and resolve
                    user_id = self._get_column_value(record, 'UserId', 0)
                    user_sid, user_name = self.resolve_user_id(user_id)
                    
                    # Extract energy metrics
                    event_timestamp = srum_filetime(
                        self._get_column_value(record, 'EventTimestamp'))
                    
                    srum_record = SRUMEnergyRecord(
                        timestamp=timestamp,
                        app_name=app_name,
                        app_path=app_path,
                        user_sid=user_sid,
                        user_name=user_name,
                        event_timestamp=event_timestamp,
                        state_transition=self._get_column_value(record, 'StateTransition', 0) or 0,
                        charge_level=self._get_column_value(record, 'ChargeLevel', 0) or 0,
                        cycle_count=self._get_column_value(record, 'CycleCount', 0) or 0,
                    )
                    
                    records.append(srum_record)
                
                except Exception as e:
                    logger.debug(f"Error parsing energy record {i}: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(records)} energy usage records")

        except Exception as e:
            logger.error(f"Error parsing energy usage table: {e}")

        return records

    def parse_app_timeline(self, table) -> List[SRUMAppTimelineRecord]:
        """Parse Application Timeline table.

        Args:
            table: ESE table object for the application timeline provider

        Returns:
            list: List of SRUMAppTimelineRecord objects
        """
        records = []

        if not table:
            logger.warning("Application Timeline table not found")
            return records

        try:
            num_records = table.get_number_of_records()
            logger.info(f"Parsing {num_records} application timeline records")

            for i in range(num_records):
                try:
                    record = table.get_record(i)

                    timestamp = self._get_column_value(record, 'TimeStamp')

                    if not timestamp or not isinstance(timestamp, datetime.datetime):
                        continue

                    app_id = self._get_column_value(record, 'AppId', 0)
                    app_name, app_path, hosted_services = self.resolve_app_identity(app_id)

                    user_id = self._get_column_value(record, 'UserId', 0)
                    user_sid, user_name = self.resolve_user_id(user_id)

                    # EndTime is an Int64 FILETIME, not an ESE DateTime.
                    end_time = srum_filetime(self._get_column_value(record, 'EndTime'))

                    srum_record = SRUMAppTimelineRecord(
                        timestamp=timestamp,
                        app_name=app_name,
                        app_path=app_path,
                        hosted_services=hosted_services,
                        user_sid=user_sid,
                        user_name=user_name,
                        end_time=end_time,
                        duration_ms=self._get_column_value(record, 'DurationMS', 0) or 0,
                        span_ms=self._get_column_value(record, 'SpanMS', 0) or 0,
                        timeline_end=self._get_column_value(record, 'TimelineEnd', 0) or 0,
                        flags=self._get_column_value(record, 'Flags', 0) or 0,
                        in_focus_s=self._get_column_value(record, 'InFocusS', 0) or 0,
                        psm_foreground_s=self._get_column_value(record, 'PSMForegroundS', 0) or 0,
                        user_input_s=self._get_column_value(record, 'UserInputS', 0) or 0,
                        keyboard_input_s=self._get_column_value(record, 'KeyboardInputS', 0) or 0,
                        mouse_input_s=self._get_column_value(record, 'MouseInputS', 0) or 0,
                        display_required_s=self._get_column_value(record, 'DisplayRequiredS', 0) or 0,
                        comp_rendered_s=self._get_column_value(record, 'CompRenderedS', 0) or 0,
                        comp_dirtied_s=self._get_column_value(record, 'CompDirtiedS', 0) or 0,
                        comp_propagated_s=self._get_column_value(record, 'CompPropagatedS', 0) or 0,
                        audio_in_s=self._get_column_value(record, 'AudioInS', 0) or 0,
                        audio_out_s=self._get_column_value(record, 'AudioOutS', 0) or 0,
                        cycles=self._get_column_value(record, 'Cycles', 0) or 0,
                        cycles_attr=self._get_column_value(record, 'CyclesAttr', 0) or 0,
                        cycles_wob=self._get_column_value(record, 'CyclesWOB', 0) or 0,
                        disk_raw=self._get_column_value(record, 'DiskRaw', 0) or 0,
                        network_bytes_raw=self._get_column_value(record, 'NetworkBytesRaw', 0) or 0,
                        network_tail_raw=self._get_column_value(record, 'NetworkTailRaw', 0) or 0,
                    )

                    records.append(srum_record)

                except Exception as e:
                    logger.debug(f"Error parsing application timeline record {i}: {e}")
                    continue

            logger.info(f"Successfully parsed {len(records)} application timeline records")

        except Exception as e:
            logger.error(f"Error parsing application timeline table: {e}")

        return records

    def create_database_schema(self):
        """Create SQLite database schema for SRUM data storage.
        
        Creates tables for:
        - Application resource usage
        - Network connectivity
        - Network data usage
        - Energy usage
        - Parsing metadata
        
        Also creates indexes on frequently searched columns.
        """
        try:
            conn = sqlite3.connect(self.output_db_path)
            cursor = conn.cursor()
            
            # Create application resource usage table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS srum_application_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT,
                    app_path TEXT,
                    user_sid TEXT,
                    user_name TEXT,
                    foreground_cycle_time INTEGER,
                    background_cycle_time INTEGER,
                    face_time INTEGER,
                    foreground_context_switches INTEGER,
                    background_context_switches INTEGER,
                    foreground_bytes_read INTEGER,
                    foreground_bytes_written INTEGER,
                    foreground_num_read_operations INTEGER,
                    foreground_num_write_operations INTEGER,
                    foreground_number_of_flushes INTEGER,
                    background_bytes_read INTEGER,
                    background_bytes_written INTEGER,
                    background_num_read_operations INTEGER,
                    background_num_write_operations INTEGER,
                    background_number_of_flushes INTEGER
                )
            """)
            
            # Create network connectivity table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS srum_network_connectivity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT,
                    app_path TEXT,
                    user_sid TEXT,
                    user_name TEXT,
                    interface_luid INTEGER,
                    l2_profile_id INTEGER,
                    l2_profile_flags INTEGER,
                    connected_time INTEGER,
                    connect_start_time TEXT
                )
            """)
            
            # Create network data usage table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS srum_network_data_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT,
                    app_path TEXT,
                    user_sid TEXT,
                    user_name TEXT,
                    interface_luid INTEGER,
                    l2_profile_id INTEGER,
                    bytes_sent INTEGER,
                    bytes_received INTEGER
                )
            """)
            
            # Create energy usage table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS srum_energy_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT,
                    app_path TEXT,
                    user_sid TEXT,
                    user_name TEXT,
                    event_timestamp TEXT,
                    state_transition INTEGER,
                    charge_level INTEGER,
                    cycle_count INTEGER
                )
            """)
            
            # Create application timeline table
            #
            # This is the provider that records how an application was used
            # rather than only that it ran - focus time, keyboard and mouse
            # input. It is also the only table whose AppId uses the `!!` form,
            # so hosted_services lives here and nowhere else.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS srum_app_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT,
                    app_path TEXT,
                    hosted_services TEXT,
                    user_sid TEXT,
                    user_name TEXT,
                    end_time TEXT,
                    duration_ms INTEGER,
                    span_ms INTEGER,
                    timeline_end INTEGER,
                    flags INTEGER,
                    in_focus_s INTEGER,
                    psm_foreground_s INTEGER,
                    user_input_s INTEGER,
                    keyboard_input_s INTEGER,
                    mouse_input_s INTEGER,
                    display_required_s INTEGER,
                    comp_rendered_s INTEGER,
                    comp_dirtied_s INTEGER,
                    comp_propagated_s INTEGER,
                    audio_in_s INTEGER,
                    audio_out_s INTEGER,
                    cycles INTEGER,
                    cycles_attr INTEGER,
                    cycles_wob INTEGER,
                    disk_raw INTEGER,
                    network_bytes_raw INTEGER,
                    network_tail_raw INTEGER
                )
            """)

            # Create metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS srum_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parsed_at TEXT NOT NULL,
                    srudb_path TEXT,
                    total_records_parsed INTEGER,
                    parsing_duration_seconds REAL,
                    windows_version TEXT,
                    notes TEXT
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_usage_timestamp ON srum_application_usage(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_usage_app_name ON srum_application_usage(app_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_usage_user_name ON srum_application_usage(user_name)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_net_conn_timestamp ON srum_network_connectivity(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_net_conn_app_name ON srum_network_connectivity(app_name)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_net_data_timestamp ON srum_network_data_usage(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_net_data_app_name ON srum_network_data_usage(app_name)")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_energy_timestamp ON srum_energy_usage(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_energy_app_name ON srum_energy_usage(app_name)")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_timeline_timestamp ON srum_app_timeline(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_timeline_app_name ON srum_app_timeline(app_name)")

            self._drop_retired_columns(cursor)

            conn.commit()
            conn.close()
            
            logger.info(f"Created database schema at: {self.output_db_path}")
        
        except Exception as e:
            logger.error(f"Error creating database schema: {e}")
            raise
    
    # Columns that were added on a miscount and can never carry data on these
    # four tables: hosted_services only ever comes from the `!!` AppId form,
    # which none of them reference, and app_id_raw repeated app_path verbatim.
    RETIRED_COLUMNS = {
        'srum_application_usage': ('hosted_services', 'app_id_raw'),
        'srum_network_connectivity': ('hosted_services', 'app_id_raw'),
        'srum_network_data_usage': ('hosted_services', 'app_id_raw'),
        'srum_energy_usage': ('hosted_services', 'app_id_raw'),
    }

    def _drop_retired_columns(self, cursor) -> None:
        """Remove retired columns from a database created by an earlier build.

        Rows are appended rather than replaced on each parse, so an existing
        database cannot simply be recreated - the columns are dropped in place
        and every other column is left untouched.
        """
        for table, columns in self.RETIRED_COLUMNS.items():
            try:
                cursor.execute("PRAGMA table_info(%s)" % table)
                present = {row[1] for row in cursor.fetchall()}
            except sqlite3.Error:
                continue
            if not present:
                continue
            for column in columns:
                if column not in present:
                    continue
                try:
                    cursor.execute("ALTER TABLE %s DROP COLUMN %s" % (table, column))
                    logger.info("Removed retired column %s.%s", table, column)
                except sqlite3.Error as e:
                    # DROP COLUMN needs SQLite 3.35+. Leaving the column in
                    # place is harmless; losing the rows would not be.
                    logger.warning("Could not drop %s.%s: %s", table, column, e)

    def save_to_database(self, parsed_data: Dict[str, List], metadata: Optional[Dict[str, any]] = None) -> None:
        """Save parsed SRUM data to SQLite database.
        
        Uses batch insertion with transactions for performance.
        Commits records in batches of 1000.
        Stores parsing metadata including timestamp, duration, and record counts.
        
        Args:
            parsed_data (dict): Dictionary containing parsed records by type
            metadata (dict, optional): Parsing metadata (timestamp, duration, record counts)
        
        Raises:
            Exception: If database write operations fail
        """
        try:
            conn = sqlite3.connect(self.output_db_path)
            cursor = conn.cursor()
            
            # Track total records for metadata
            total_records = 0
            
            # Save application resource usage records
            if 'application_usage' in parsed_data:
                records = parsed_data['application_usage']
                total_records += len(records)
                logger.info(f"Saving {len(records)} application usage records")
                
                batch = []
                for record in records:
                    batch.append((
                        format_forensic_timestamp(record.timestamp) if record.timestamp else None,
                        record.app_name,
                        record.app_path,
                        record.user_sid,
                        record.user_name,
                        record.foreground_cycle_time,
                        record.background_cycle_time,
                        record.face_time,
                        record.foreground_context_switches,
                        record.background_context_switches,
                        record.foreground_bytes_read,
                        record.foreground_bytes_written,
                        record.foreground_num_read_operations,
                        record.foreground_num_write_operations,
                        record.foreground_number_of_flushes,
                        record.background_bytes_read,
                        record.background_bytes_written,
                        record.background_num_read_operations,
                        record.background_num_write_operations,
                        record.background_number_of_flushes,
                    ))
                    
                    # Commit in batches of 1000
                    if len(batch) >= 1000:
                        cursor.executemany("""
                            INSERT INTO srum_application_usage (
                                timestamp, app_name, app_path, user_sid, user_name,
                                foreground_cycle_time, background_cycle_time, face_time,
                                foreground_context_switches, background_context_switches,
                                foreground_bytes_read, foreground_bytes_written,
                                foreground_num_read_operations, foreground_num_write_operations,
                                foreground_number_of_flushes, background_bytes_read,
                                background_bytes_written, background_num_read_operations,
                                background_num_write_operations, background_number_of_flushes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch = []
                
                # Commit remaining records
                if batch:
                    cursor.executemany("""
                        INSERT INTO srum_application_usage (
                            timestamp, app_name, app_path, user_sid, user_name,
                            foreground_cycle_time, background_cycle_time, face_time,
                            foreground_context_switches, background_context_switches,
                            foreground_bytes_read, foreground_bytes_written,
                            foreground_num_read_operations, foreground_num_write_operations,
                            foreground_number_of_flushes, background_bytes_read,
                            background_bytes_written, background_num_read_operations,
                            background_num_write_operations, background_number_of_flushes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    conn.commit()
            
            # Save network connectivity records
            if 'network_connectivity' in parsed_data:
                records = parsed_data['network_connectivity']
                total_records += len(records)
                logger.info(f"Saving {len(records)} network connectivity records")
                
                batch = []
                for record in records:
                    batch.append((
                        format_forensic_timestamp(record.timestamp) if record.timestamp else None,
                        record.app_name,
                        record.app_path,
                        record.user_sid,
                        record.user_name,
                        record.interface_luid,
                        record.l2_profile_id,
                        record.l2_profile_flags,
                        record.connected_time,
                        format_forensic_timestamp(record.connect_start_time) if record.connect_start_time else None,
                    ))
                    
                    if len(batch) >= 1000:
                        cursor.executemany("""
                            INSERT INTO srum_network_connectivity (
                                timestamp, app_name, app_path, user_sid, user_name,
                                interface_luid, l2_profile_id, l2_profile_flags,
                                connected_time, connect_start_time
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch = []
                
                if batch:
                    cursor.executemany("""
                        INSERT INTO srum_network_connectivity (
                            timestamp, app_name, app_path, user_sid, user_name,
                            interface_luid, l2_profile_id, l2_profile_flags,
                            connected_time, connect_start_time
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    conn.commit()
            
            # Save network data usage records
            if 'network_data_usage' in parsed_data:
                records = parsed_data['network_data_usage']
                total_records += len(records)
                logger.info(f"Saving {len(records)} network data usage records")
                
                batch = []
                for record in records:
                    batch.append((
                        format_forensic_timestamp(record.timestamp) if record.timestamp else None,
                        record.app_name,
                        record.app_path,
                        record.user_sid,
                        record.user_name,
                        record.interface_luid,
                        record.l2_profile_id,
                        record.bytes_sent,
                        record.bytes_received,
                    ))
                    
                    if len(batch) >= 1000:
                        cursor.executemany("""
                            INSERT INTO srum_network_data_usage (
                                timestamp, app_name, app_path, user_sid, user_name,
                                interface_luid, l2_profile_id, bytes_sent, bytes_received
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch = []
                
                if batch:
                    cursor.executemany("""
                        INSERT INTO srum_network_data_usage (
                            timestamp, app_name, app_path, user_sid, user_name,
                            interface_luid, l2_profile_id, bytes_sent, bytes_received
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    conn.commit()
            
            # Save energy usage records
            if 'energy_usage' in parsed_data:
                records = parsed_data['energy_usage']
                total_records += len(records)
                logger.info(f"Saving {len(records)} energy usage records")
                
                batch = []
                for record in records:
                    batch.append((
                        format_forensic_timestamp(record.timestamp) if record.timestamp else None,
                        record.app_name,
                        record.app_path,
                        record.user_sid,
                        record.user_name,
                        format_forensic_timestamp(record.event_timestamp) if record.event_timestamp else None,
                        record.state_transition,
                        record.charge_level,
                        record.cycle_count,
                    ))
                    
                    if len(batch) >= 1000:
                        cursor.executemany("""
                            INSERT INTO srum_energy_usage (
                                timestamp, app_name, app_path, user_sid, user_name,
                                event_timestamp, state_transition, charge_level, cycle_count
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, batch)
                        conn.commit()
                        batch = []
                
                if batch:
                    cursor.executemany("""
                        INSERT INTO srum_energy_usage (
                            timestamp, app_name, app_path, user_sid, user_name,
                            event_timestamp, state_transition, charge_level, cycle_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    conn.commit()
            
            # Save application timeline records
            #
            # Stored as raw integers, not through format_number. A comma makes
            # the value TEXT, and SQLite sorts every TEXT above every INTEGER,
            # so `duration_ms > 1000000` matches all 38359 formatted rows
            # whatever the threshold - and a Wing filtering on one of these
            # would be quietly wrong. Formatting belongs to the view.
            if 'app_timeline' in parsed_data:
                records = parsed_data['app_timeline']
                total_records += len(records)
                logger.info(f"Saving {len(records)} application timeline records")

                batch = []
                for record in records:
                    batch.append((
                        format_forensic_timestamp(record.timestamp) if record.timestamp else None,
                        record.app_name,
                        record.app_path,
                        record.hosted_services,
                        record.user_sid,
                        record.user_name,
                        format_forensic_timestamp(record.end_time) if record.end_time else None,
                        record.duration_ms,
                        record.span_ms,
                        record.timeline_end,
                        record.flags,
                        record.in_focus_s,
                        record.psm_foreground_s,
                        record.user_input_s,
                        record.keyboard_input_s,
                        record.mouse_input_s,
                        record.display_required_s,
                        record.comp_rendered_s,
                        record.comp_dirtied_s,
                        record.comp_propagated_s,
                        record.audio_in_s,
                        record.audio_out_s,
                        record.cycles,
                        record.cycles_attr,
                        record.cycles_wob,
                        record.disk_raw,
                        record.network_bytes_raw,
                        record.network_tail_raw,
                    ))

                    if len(batch) >= 1000:
                        cursor.executemany(APP_TIMELINE_INSERT, batch)
                        conn.commit()
                        batch = []

                if batch:
                    cursor.executemany(APP_TIMELINE_INSERT, batch)
                    conn.commit()

            # Save parsing metadata
            if metadata:
                logger.info("Saving parsing metadata")
                try:
                    cursor.execute("""
                        INSERT INTO srum_metadata (
                            parsed_at, srudb_path, total_records_parsed,
                            parsing_duration_seconds, windows_version, notes
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        metadata.get('parsed_at', get_current_forensic_timestamp()),
                        metadata.get('srudb_path', self.srudb_path),
                        metadata.get('total_records', total_records),
                        metadata.get('parsing_duration_seconds', 0.0),
                        metadata.get('windows_version', 'Unknown'),
                        metadata.get('notes', 'Parsed by Crow Eye SRUM Parser')
                    ))
                    conn.commit()
                    logger.info("Metadata saved successfully")
                except Exception as meta_error:
                    logger.warning(f"Could not save metadata: {meta_error}")
                    # Don't raise - metadata is non-critical
            
            conn.close()
            logger.info(f"Successfully saved all SRUM data to database (Total: {total_records} records)")
        
        except sqlite3.Error as db_error:
            logger.error(f"Database error while saving data: {db_error}")
            try:
                conn.close()
            except:
                pass
            raise Exception(f"Failed to save SRUM data to database: {db_error}")
        
        except Exception as e:
            logger.error(f"Error saving data to database: {e}")
            try:
                conn.close()
            except:
                pass
            raise

    def parse_srum_database(self, progress_callback: Optional[Callable] = None) -> Dict[str, any]:
        """Parse SRUM database and extract all tables.
        
        Main parsing method that orchestrates the entire SRUM parsing process:
        1. Opens the ESE database
        2. Enumerates and identifies SRUM tables
        3. Parses each table type
        4. Returns parsed data organized by table type
        
        Args:
            progress_callback (callable, optional): Callback function for progress updates
                Should accept (current, total, table_name) parameters
        
        Returns:
            dict: Dictionary containing parsed data organized by table type
                Keys: 'application_usage', 'network_connectivity', 'network_data_usage',
                      'energy_usage', 'app_timeline', 'warnings'
                Values: Lists of corresponding record objects, and list of warning messages
        """
        parsed_data = {
            'application_usage': [],
            'network_connectivity': [],
            'network_data_usage': [],
            'energy_usage': [],
            'app_timeline': [],
            'warnings': [],  # Track warnings during parsing
        }
        
        tables_to_close = []
        
        try:
            # Open ESE database
            logger.info("Opening SRUDB.dat ESE database")
            self.open_ese_database()
            
            # Load ID lookup table first (maps IDs to app paths and user SIDs)
            self.load_id_lookup_table()
            
            # Parse Application Resource Usage table (primary table)
            logger.info("Parsing Application Resource Usage table")
            app_table = self.get_table_by_guid(SRUM_TABLE_GUIDS['APPLICATION_RESOURCE_USAGE'])
            if app_table:
                tables_to_close.append(app_table)
                parsed_data['application_usage'] = self.parse_application_resource_usage(app_table)
                if progress_callback:
                    progress_callback(
                        len(parsed_data['application_usage']),
                        len(parsed_data['application_usage']),
                        "Application Resource Usage"
                    )
            else:
                warning_msg = "Application Resource Usage table not found in SRUDB.dat"
                logger.warning(warning_msg)
                parsed_data['warnings'].append(warning_msg)
            
            # Parse Network Data Usage table
            logger.info("Parsing Network Data Usage table")
            net_data_table = self.get_table_by_guid(SRUM_TABLE_GUIDS['NETWORK_DATA_USAGE'])
            if net_data_table:
                tables_to_close.append(net_data_table)
                parsed_data['network_data_usage'] = self.parse_network_data_usage(net_data_table)
                if progress_callback:
                    progress_callback(
                        len(parsed_data['network_data_usage']),
                        len(parsed_data['network_data_usage']),
                        "Network Data Usage"
                    )
            else:
                warning_msg = "Network Data Usage table not found in SRUDB.dat"
                logger.warning(warning_msg)
                parsed_data['warnings'].append(warning_msg)
            
            # Parse Network Connectivity table
            logger.info("Parsing Network Connectivity table")
            net_conn_table = self.get_table_by_guid(SRUM_TABLE_GUIDS['NETWORK_CONNECTIVITY'])
            if net_conn_table:
                tables_to_close.append(net_conn_table)
                parsed_data['network_connectivity'] = self.parse_network_connectivity(net_conn_table)
                if progress_callback:
                    progress_callback(
                        len(parsed_data['network_connectivity']),
                        len(parsed_data['network_connectivity']),
                        "Network Connectivity"
                    )
            else:
                warning_msg = "Network Connectivity table not found in SRUDB.dat"
                logger.warning(warning_msg)
                parsed_data['warnings'].append(warning_msg)
            
            # Parse Energy Usage table (may not exist on all systems)
            logger.info("Parsing Energy Usage table")
            energy_table = self.get_table_by_guid(SRUM_TABLE_GUIDS['ENERGY_USAGE'])
            if energy_table:
                tables_to_close.append(energy_table)
                parsed_data['energy_usage'] = self.parse_energy_usage(energy_table)
                if progress_callback:
                    progress_callback(
                        len(parsed_data['energy_usage']),
                        len(parsed_data['energy_usage']),
                        "Energy Usage"
                    )
            else:
                # Try long-term energy usage table (Windows 10+)
                energy_table = self.get_table_by_guid(SRUM_TABLE_GUIDS['ENERGY_USAGE_LONG_TERM'])
                if energy_table:
                    tables_to_close.append(energy_table)
                    parsed_data['energy_usage'] = self.parse_energy_usage(energy_table)
                    if progress_callback:
                        progress_callback(
                            len(parsed_data['energy_usage']),
                            len(parsed_data['energy_usage']),
                            "Energy Usage (Long Term)"
                        )
                else:
                    warning_msg = "Energy Usage tables not found (not available on Windows 8 or older systems)"
                    logger.info(warning_msg)
                    parsed_data['warnings'].append(warning_msg)

            # Parse Application Timeline table (Windows 10+)
            logger.info("Parsing Application Timeline table")
            timeline_table = self.get_table_by_guid(SRUM_TABLE_GUIDS['APPLICATION_TIMELINE'])
            if timeline_table:
                tables_to_close.append(timeline_table)
                parsed_data['app_timeline'] = self.parse_app_timeline(timeline_table)
                if progress_callback:
                    progress_callback(
                        len(parsed_data['app_timeline']),
                        len(parsed_data['app_timeline']),
                        "Application Timeline"
                    )
            else:
                warning_msg = "Application Timeline table not found (not available on Windows 8 or older systems)"
                logger.info(warning_msg)
                parsed_data['warnings'].append(warning_msg)

            # Close all opened tables
            for table in tables_to_close:
                try:
                    table.close()
                except Exception as e:
                    logger.debug(f"Error closing table: {e}")
            
            # Close ESE database
            try:
                if self.dbid:
                    esent.JetCloseDatabase(self.sesid, self.dbid, 0)
                if self.sesid:
                    esent.JetEndSession(self.sesid, 0)
                if self.instance:
                    esent.JetTerm(self.instance)
                logger.info("Closed ESE database")
            except Exception as e:
                logger.debug(f"Error closing database: {e}")
            
            # Add SID resolution warnings if any SIDs could not be resolved
            if hasattr(self, '_sid_resolution_failures') and self._sid_resolution_failures:
                num_failed = len(self._sid_resolution_failures)
                warning_msg = f"Could not resolve {num_failed} user SID(s) to usernames. SIDs will be displayed instead."
                logger.warning(warning_msg)
                parsed_data['warnings'].append(warning_msg)
            
            logger.info("SRUM database parsing completed successfully")
        
        except Exception as e:
            logger.error(f"Error parsing SRUM database: {e}")
            # Close all opened tables
            for table in tables_to_close:
                try:
                    table.close()
                except:
                    pass
            # Close database
            try:
                if self.dbid:
                    esent.JetCloseDatabase(self.sesid, self.dbid, 0)
                if self.sesid:
                    esent.JetEndSession(self.sesid, 0)
                if self.instance:
                    esent.JetTerm(self.instance)
            except:
                pass
            raise
        
        return parsed_data


def parse_srum_data(case_artifacts_dir: str, progress_callback: Optional[Callable] = None, windows_partition: str = "C:") -> Dict[str, any]:
    """Main entry point for SRUM parsing called by Crow Eye application.
    
    This function:
    1. Locates SRUDB.dat at the default Windows location
    2. Copies SRUDB.dat to temporary location (file is locked by Windows)
    3. Creates output database path in Target_Artifacts folder
    4. Instantiates SRUMParser and executes parsing using Windows API
    5. Creates database schema and saves parsed data
    6. Cleans up temporary SRUDB.dat copy after parsing
    7. Returns dictionary with success status, statistics, and any errors
    
    Args:
        case_artifacts_dir (str): Path to Target_Artifacts folder
        progress_callback (callable, optional): Callback for progress updates
        windows_partition (str, optional): Windows partition letter (e.g., "C:", "D:"). Defaults to "C:".
    
    Returns:
        dict: Dictionary with parsing results
            Keys: 'success', 'statistics', 'errors', 'warnings', 'output_db'
    """
    result = {
        'success': False,
        'statistics': {},
        'errors': [],
        'warnings': [],
        'output_db': None,
    }
    
    start_time = get_current_utc()
    parser = None
    
    try:
        # Locate SRUDB.dat at Windows location based on partition
        srudb_path = f"{windows_partition}\\Windows\\System32\\sru\\SRUDB.dat"
        logger.info(f"Looking for SRUDB.dat at: {srudb_path} (Windows partition: {windows_partition})")
        
        if not os.path.exists(srudb_path):
            error_msg = f"SRUDB.dat not found at: {srudb_path}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            result['warnings'].append("SRUM data is only available on Windows 8 and later")
            return result
        
        # Create output database path
        output_db_path = os.path.join(case_artifacts_dir, 'srum_data.db')
        result['output_db'] = output_db_path
        
        logger.info(f"Starting SRUM parsing: {srudb_path} -> {output_db_path}")
        
        # Check for administrator privileges (SRUDB.dat typically requires admin access)
        if not os.access(srudb_path, os.R_OK):
            error_msg = "Cannot access SRUDB.dat. Administrator privileges may be required."
            logger.error(error_msg)
            result['errors'].append(error_msg)
            result['warnings'].append("Try running Crow Eye as Administrator")
            return result
        
        # Instantiate parser (this will verify file exists and is accessible)
        parser = SRUMParser(srudb_path, output_db_path)
        
        # Copy SRUDB.dat to temporary location (file is locked by Windows)
        logger.info("Copying SRUDB.dat to temporary location (file is locked by Windows)")
        try:
            temp_srudb_path = parser.copy_srum_database(srudb_path, windows_partition)
            logger.info(f"Successfully copied SRUDB.dat to: {temp_srudb_path}")
        except SRUMFileAccessError as copy_error:
            error_msg = f"Failed to copy SRUDB.dat: {str(copy_error)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            result['warnings'].append("SRUDB.dat is locked by Windows. Try stopping the SRUM service or running as Administrator.")
            return result
        
        # Create database schema
        logger.info("Creating database schema")
        parser.create_database_schema()
        
        # Parse SRUM database
        logger.info("Parsing SRUM database")
        parsed_data = parser.parse_srum_database(progress_callback)
        
        # Propagate warnings from parsing
        if 'warnings' in parsed_data and parsed_data['warnings']:
            result['warnings'].extend(parsed_data['warnings'])
        
        # Calculate statistics
        end_time = get_current_utc()
        duration = (end_time - start_time).total_seconds()
        
        total_records = sum([
            len(parsed_data.get('application_usage', [])),
            len(parsed_data.get('network_connectivity', [])),
            len(parsed_data.get('network_data_usage', [])),
            len(parsed_data.get('energy_usage', [])),
        ])
        
        result['statistics'] = {
            'total_records': total_records,
            'application_usage_records': len(parsed_data.get('application_usage', [])),
            'network_connectivity_records': len(parsed_data.get('network_connectivity', [])),
            'network_data_usage_records': len(parsed_data.get('network_data_usage', [])),
            'energy_usage_records': len(parsed_data.get('energy_usage', [])),
            'parsing_duration_seconds': duration,
            'srudb_path': srudb_path,
        }
        
        # Prepare metadata for database storage
        metadata = {
            'parsed_at': get_current_forensic_timestamp(),
            'srudb_path': srudb_path,
            'total_records': total_records,
            'parsing_duration_seconds': duration,
            'windows_version': 'Unknown',  # Could be detected from system
            'notes': 'Parsed by Crow Eye SRUM Parser v1.0'
        }
        
        # Save to database with metadata
        logger.info("Saving parsed data to database")
        parser.save_to_database(parsed_data, metadata)
        
        result['success'] = True
        
        # Create detailed success message
        success_msg = f"SRUM parsing completed successfully! Parsed {total_records:,} total records in {duration:.2f} seconds."
        logger.info(success_msg)
        result['success_message'] = success_msg
        
        # Create detailed breakdown message
        breakdown_parts = []
        if result['statistics']['application_usage_records'] > 0:
            breakdown_parts.append(f"{result['statistics']['application_usage_records']:,} Application Usage")
        if result['statistics']['network_connectivity_records'] > 0:
            breakdown_parts.append(f"{result['statistics']['network_connectivity_records']:,} Network Connectivity")
        if result['statistics']['network_data_usage_records'] > 0:
            breakdown_parts.append(f"{result['statistics']['network_data_usage_records']:,} Network Data Usage")
        if result['statistics']['energy_usage_records'] > 0:
            breakdown_parts.append(f"{result['statistics']['energy_usage_records']:,} Energy Usage")
        
        if breakdown_parts:
            breakdown_msg = "Records by type: " + ", ".join(breakdown_parts)
            logger.info(f"  {breakdown_msg}")
            result['breakdown_message'] = breakdown_msg
        
        # Log individual statistics for debugging
        logger.info(f"  - Application Usage: {result['statistics']['application_usage_records']}")
        logger.info(f"  - Network Connectivity: {result['statistics']['network_connectivity_records']}")
        logger.info(f"  - Network Data Usage: {result['statistics']['network_data_usage_records']}")
        logger.info(f"  - Energy Usage: {result['statistics']['energy_usage_records']}")
        logger.info(f"  - Duration: {duration:.2f} seconds")
    
    except SRUMFileAccessError as e:
        error_msg = f"File access error: {str(e)}"
        logger.error(error_msg)
        result['errors'].append(error_msg)
    
    except SRUMDatabaseCorruptError as e:
        error_msg = f"Database corruption error: {str(e)}"
        logger.error(error_msg)
        result['errors'].append(error_msg)
    
    except ImportError as e:
        error_msg = f"Missing required library: {str(e)}"
        logger.error(error_msg)
        result['errors'].append(error_msg)
        result['warnings'].append("Windows ESE API (esent.dll) is required for SRUM parsing")
    
    except Exception as e:
        error_msg = f"Unexpected error during SRUM parsing: {str(e)}"
        logger.error(error_msg, exc_info=True)
        result['errors'].append(error_msg)
    
    finally:
        # Clean up temporary SRUDB.dat copy after parsing
        if parser and parser.temp_dir:
            try:
                logger.info(f"Cleaning up temporary directory: {parser.temp_dir}")
                shutil.rmtree(parser.temp_dir, ignore_errors=True)
                logger.info("Temporary files cleaned up successfully")
            except Exception as cleanup_error:
                logger.warning(f"Could not clean up temporary directory: {cleanup_error}")
                result['warnings'].append(f"Temporary files may remain at: {parser.temp_dir}")
    
    return result


# Module test code
if __name__ == "__main__":
    # Test SRUM parser
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python SRUM_Claw.py <output_directory>")
        sys.exit(1)
    
    output_dir = sys.argv[1]
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    print("=" * 60)
    print("Crow Eye SRUM Parser - Test Mode")
    print("=" * 60)
    
    result = parse_srum_data(output_dir)
    
    print("\nParsing Results:")
    print(f"Success: {result['success']}")
    
    if result['success']:
        print("\nStatistics:")
        for key, value in result['statistics'].items():
            print(f"  {key}: {value}")
    
    if result['errors']:
        print("\nErrors:")
        for error in result['errors']:
            print(f"  - {error}")
    
    if result['warnings']:
        print("\nWarnings:")
        for warning in result['warnings']:
            print(f"  - {warning}")
    
    print("\n" + "=" * 60)
