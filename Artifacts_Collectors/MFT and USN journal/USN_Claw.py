#!/usr/bin/env python3
"""
usn_journal_parser_forensics.py - Revised

Automatic USN Journal parser for forensic use.
- Runs with no arguments
- Auto-detects NTFS volumes
- Saves output to USN_journal.db
- Run as Administrator on Windows
"""
import ctypes
from ctypes import wintypes
import struct
import sqlite3
import datetime
import logging
import sys
import os
import gc
import psutil
from tqdm import tqdm

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

# Optional dependency: wmi for volume discovery
try:
    import wmi
    _HAS_WMI = True
except ImportError:
    _HAS_WMI = False
    print(f"{COLOR_WARNING}WMI module not available - installing it now...{COLOR_RESET}")
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "wmi"])
        import wmi
        _HAS_WMI = True
        print(f"{COLOR_SUCCESS}Successfully installed wmi module{COLOR_RESET}")
    except Exception as e:
        print(f"{COLOR_ERROR}Failed to install wmi module: {e}{COLOR_RESET}")
        print(f"{COLOR_WARNING}Volume discovery will use alternative methods{COLOR_RESET}")

# --------- Config ---------
OUTPUT_DB = "USN_journal.db"
BUFFER_SIZE = 65536
BATCH_SIZE = 500  # commit after this many records
COMMIT_FREQUENCY_BYTES = 4 * 1024 * 1024  # or commit when this many bytes processed in a chunk

# --------- Logging ---------
# Create timestamped log filename
log_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
# Create Target_Artifacts directory for logs if it doesn't exist
target_artifacts_dir = os.path.join(".", "Target_Artifacts")
os.makedirs(target_artifacts_dir, exist_ok=True)
log_filename = os.path.join(target_artifacts_dir, f"usn_claw_{log_timestamp}.log")

# Configure separate loggers for console (simplified) and file (detailed)
# Remove any existing handlers
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Create console handler with simplified output (INFO level only)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(message)s")  # Simple format for console
console_handler.setFormatter(console_formatter)

# Create file handler with detailed output (DEBUG level)
file_handler = logging.FileHandler(log_filename, mode='w', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)

# Configure root logger
logging.basicConfig(level=logging.DEBUG, handlers=[console_handler, file_handler])
logger = logging.getLogger(__name__)

# Create a separate logger for detailed file-only logging
file_logger = logging.getLogger('file_only')
file_logger.setLevel(logging.DEBUG)
file_logger.addHandler(file_handler)
file_logger.propagate = False  # Don't propagate to root logger

# Log the log file location (file only)
file_logger.info(f"Detailed logging to file: {log_filename}")
print(f"{COLOR_INFO}Crow Eye USN Journal Parser - Detailed logs: {log_filename}{COLOR_RESET}")

# --------- Windows API constants ----------
kernel32 = ctypes.windll.kernel32

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# USN Journal FSCTL codes - all versions
FSCTL_QUERY_USN_JOURNAL_V0 = 0x000900B4  # Original version
FSCTL_QUERY_USN_JOURNAL_V1 = 0x000900B4  # Same as V0
FSCTL_QUERY_USN_JOURNAL_V2 = 0x000900F4  # Windows 8+ version
FSCTL_READ_USN_JOURNAL = 0x000900BB

ERROR_HANDLE_EOF = 38
ERROR_NO_DATA = 232

DRIVE_FIXED = 3

# --------- ctypes structures ----------
class USN_JOURNAL_DATA_V0(ctypes.Structure):
    _fields_ = [
        ("UsnJournalID", ctypes.c_ulonglong),
        ("FirstUsn", ctypes.c_ulonglong),
        ("NextUsn", ctypes.c_ulonglong),
        ("LowestValidUsn", ctypes.c_ulonglong),
        ("MaxUsn", ctypes.c_ulonglong),
        ("MaximumSize", ctypes.c_ulonglong),
        ("AllocationDelta", ctypes.c_ulonglong),
    ]

class USN_JOURNAL_DATA_V1(ctypes.Structure):
    _fields_ = [
        ("UsnJournalID", ctypes.c_ulonglong),
        ("FirstUsn", ctypes.c_ulonglong),
        ("NextUsn", ctypes.c_ulonglong),
        ("LowestValidUsn", ctypes.c_ulonglong),
        ("MaxUsn", ctypes.c_ulonglong),
        ("MaximumSize", ctypes.c_ulonglong),
        ("AllocationDelta", ctypes.c_ulonglong),
        ("MinSupportedMajorVersion", ctypes.c_ushort),
        ("MaxSupportedMajorVersion", ctypes.c_ushort),
    ]



class USN_JOURNAL_DATA_V2(ctypes.Structure):
    _fields_ = [
        ("UsnJournalID", ctypes.c_ulonglong),
        ("FirstUsn", ctypes.c_ulonglong),
        ("NextUsn", ctypes.c_ulonglong),
        ("LowestValidUsn", ctypes.c_ulonglong),
        ("MaxUsn", ctypes.c_ulonglong),
        ("MaximumSize", ctypes.c_ulonglong),
        ("AllocationDelta", ctypes.c_ulonglong),
        ("MinSupportedMajorVersion", wintypes.WORD),
        ("MaxSupportedMajorVersion", wintypes.WORD),
        ("Flags", wintypes.DWORD),
        ("RangeTrackChunkSize", ctypes.c_ulonglong),
        ("RangeTrackFileSizeThreshold", ctypes.c_longlong),
    ]

class READ_USN_JOURNAL_DATA_V0(ctypes.Structure):
    _fields_ = [
        ("StartUsn", ctypes.c_ulonglong),
        ("ReasonMask", wintypes.DWORD),
        ("ReturnOnlyOnClose", wintypes.DWORD),
        ("Timeout", ctypes.c_ulonglong),
        ("BytesToWaitFor", ctypes.c_ulonglong),
        ("UsnJournalID", ctypes.c_ulonglong),
    ]

class FILE_ID_128(ctypes.Structure):
    _fields_ = [
        ("LowPart", ctypes.c_ulonglong),
        ("HighPart", ctypes.c_ulonglong),
    ]

class USN_RECORD_V2(ctypes.Structure):
    _fields_ = [
        ("RecordLength", wintypes.DWORD),
        ("MajorVersion", wintypes.WORD),
        ("MinorVersion", wintypes.WORD),
        ("FileReferenceNumber", ctypes.c_ulonglong),
        ("ParentFileReferenceNumber", ctypes.c_ulonglong),
        ("Usn", ctypes.c_longlong),
        ("TimeStamp", ctypes.c_longlong),
        ("Reason", wintypes.DWORD),
        ("SourceInfo", wintypes.DWORD),
        ("SecurityId", wintypes.DWORD),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.WORD),
        ("FileNameOffset", wintypes.WORD),
    ]

class USN_RECORD_V3(ctypes.Structure):
    _fields_ = [
        ("RecordLength", wintypes.DWORD),
        ("MajorVersion", wintypes.WORD),
        ("MinorVersion", wintypes.WORD),
        ("FileReferenceNumber", FILE_ID_128),
        ("ParentFileReferenceNumber", FILE_ID_128),
        ("Usn", ctypes.c_ulonglong),
        ("TimeStamp", ctypes.c_longlong),
        ("Reason", wintypes.DWORD),
        ("SourceInfo", wintypes.DWORD),
        ("SecurityId", wintypes.DWORD),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.WORD),
        ("FileNameOffset", wintypes.WORD),
    ]

# --------- File Attribute Mappings ----------
FILE_ATTRIBUTE_MAP = {
    0x00000001: "READONLY",
    0x00000002: "HIDDEN",
    0x00000004: "SYSTEM",
    0x00000010: "DIRECTORY",
    0x00000020: "ARCHIVE",
    0x00000040: "DEVICE",
    0x00000080: "NORMAL",
    0x00000100: "TEMPORARY",
    0x00000200: "SPARSE_FILE",
    0x00000400: "REPARSE_POINT",
    0x00000800: "COMPRESSED",
    0x00001000: "OFFLINE",
    0x00002000: "NOT_CONTENT_INDEXED",
    0x00004000: "ENCRYPTED",
    0x00008000: "INTEGRITY_STREAM",
    0x00010000: "VIRTUAL",
    0x00020000: "NO_SCRUB_DATA",
    0x00040000: "RECALL_ON_OPEN",
    0x00080000: "RECALL_ON_DATA_ACCESS",
}

def file_attributes_to_text(file_attributes):
    """Convert numeric file attributes to human-readable text representation"""
    if file_attributes == 0:
        return "NORMAL"
    
    attributes = []
    for attr_value, attr_name in FILE_ATTRIBUTE_MAP.items():
        if file_attributes & attr_value:
            attributes.append(attr_name)
    
    return "|".join(attributes) if attributes else "NORMAL"

# --------- Reason / Source Mappings ----------
REASON_MAP = {
    0x00000001: "DATA_OVERWRITE",
    0x00000002: "DATA_EXTEND",
    0x00000004: "DATA_TRUNCATION",
    0x00000100: "FILE_CREATE",
    0x00000200: "FILE_DELETE",
    0x00000400: "EA_CHANGE",
    0x00000800: "SECURITY_CHANGE",
    0x00001000: "RENAME_OLD_NAME",
    0x00002000: "RENAME_NEW_NAME",
    0x00004000: "INDEXABLE_CHANGE",
    0x00008000: "BASIC_INFO_CHANGE",
    0x00010000: "HARD_LINK_CHANGE",
    0x00020000: "COMPRESSION_CHANGE",
    0x00040000: "ENCRYPTION_CHANGE",
    0x00080000: "OBJECT_ID_CHANGE",
    0x00100000: "REPARSE_POINT_CHANGE",
    0x00200000: "STREAM_CHANGE",
    0x80000000: "CLOSE",
}

SOURCE_INFO_MAP = {
    0x00000001: "DATA_MANAGEMENT",
    0x00000002: "AUXILIARY_DATA",
    0x00000004: "REPLICATION_MANAGEMENT",
    0x00000008: "CLIENT_REPLICATION_MANAGEMENT",
}

# --------- Forensic Filtering ----------
# Patterns to exclude from USN Journal analysis to prevent self-referential entries
FORENSIC_EXCLUSION_PATTERNS = [
    # SQLite database files (our own operations)
    "USN_journal.db",
    "USN_journal.db-journal",
    "USN_journal.db-wal", 
    "USN_journal.db-shm",
    # Other common forensic tool database patterns
    ".db-journal",
    ".db-wal",
    ".db-shm",
    # Trae AI workspace database files
    "_codekg.db-journal",
    "_embedding_vec.db-journal",
    # Common temporary/cache files that create noise
    "state.vscdb-journal",
    "hianalytics.sqlite-journal",
]

def should_exclude_from_analysis(filename):
    """
    Determine if a filename should be excluded from forensic analysis.
    
    This prevents the USN Journal parser from capturing its own database operations
    and other forensic tool artifacts that would create noise in the analysis.
    
    Args:
        filename (str): The filename to check
        
    Returns:
        bool: True if the file should be excluded, False otherwise
    """
    if not filename:
        return False
    
    filename_lower = filename.lower()
    
    # Check exact matches and patterns
    for pattern in FORENSIC_EXCLUSION_PATTERNS:
        if pattern.lower() in filename_lower:
            return True
    
    # Additional checks for forensic tool artifacts
    if filename_lower.endswith(('.db-journal', '.db-wal', '.db-shm')):
        return True
    
    return False

# --------- Utility Functions ----------
def filetime_to_datetime(filetime_value):
    if not filetime_value:
        return None
    try:
        ft = int(filetime_value)
    except Exception:
        return None
    if ft == 0:
        return None
    # FILETIME is 100-nanosecond intervals since Jan 1, 1601 (UTC)
    try:
        ts = (ft / 10_000_000.0) - 11644473600  # convert to seconds since epoch
        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
    except Exception:
        return None

def file_id_128_to_str(fid):
    try:
        return f"{fid.HighPart:016x}{fid.LowPart:016x}"
    except Exception:
        # fallback - tuple
        return str((getattr(fid, 'HighPart', 0), getattr(fid, 'LowPart', 0)))

def reason_to_text(val):
    return " | ".join([name for bit, name in REASON_MAP.items() if val & bit]) or "UNKNOWN"

def sourceinfo_to_text(val):
    if val == 0:
        return "USER/APPLICATION"
    return " | ".join([name for bit, name in SOURCE_INFO_MAP.items() if val & bit]) or "UNKNOWN"

# --------- Low-level API helpers ----------
def create_file_handle(path):
    # Use FILE_SHARE_DELETE to be more tolerant; open as read-only
    handle = kernel32.CreateFileW(
        path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING, 0, None
    )
    if int(handle) == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.GetLastError(), f"CreateFileW failed for {path}")
    return int(handle)

def close_handle(handle):
    try:
        if handle and handle != INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
    except (OSError, ctypes.WinError) as e:
        file_logger.warning(f"Failed to close handle {handle}: {e}")
    except Exception as e:
        file_logger.error(f"Unexpected error closing handle {handle}: {e}")

def get_file_size(handle):
    size = ctypes.c_longlong(0)
    if not kernel32.GetFileSizeEx(wintypes.HANDLE(handle), ctypes.byref(size)):
        raise OSError(ctypes.GetLastError(), "GetFileSizeEx failed")
    return int(size.value)

# --------- Admin check ----------
def is_admin():
    """Check if the script is running with administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

# --------- Volume discovery ----------
def get_ntfs_volumes():
    """
    Return list of drive letters (e.g. ['C', 'D']) for fixed NTFS volumes.
    Tries WMI (if available), else falls back to GetDriveTypeW + GetVolumeInformationW.
    """
    volumes = []
    # Try WMI first if available
    if _HAS_WMI:
        try:
            c = wmi.WMI()
            for disk in c.Win32_LogicalDisk(DriveType=3):  # fixed
                if str(disk.FileSystem).upper() == "NTFS":
                    volumes.append(str(disk.DeviceID)[0].upper())
            if volumes:
                return volumes
        except Exception as e:
            logger.debug(f"WMI enumeration failed: {e}")

    # Fallback: Windows API approach
    logger.info("Using Windows API fallback volume detection")
    GetDriveTypeW = kernel32.GetDriveTypeW
    GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    GetDriveTypeW.restype = wintypes.UINT

    GetVolumeInformationW = kernel32.GetVolumeInformationW
    GetVolumeInformationW.argtypes = [wintypes.LPCWSTR,
                                      wintypes.LPWSTR, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      wintypes.LPWSTR, wintypes.DWORD]
    GetVolumeInformationW.restype = wintypes.BOOL

    for drive_letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{drive_letter}:\\"
        try:
            dtype = GetDriveTypeW(root)
            if dtype != DRIVE_FIXED:
                continue
            fs_name_buf = ctypes.create_unicode_buffer(32)
            volname_buf = ctypes.create_unicode_buffer(256)
            serial = wintypes.DWORD()
            max_comp_len = wintypes.DWORD()
            fs_flags = wintypes.DWORD()
            ok = GetVolumeInformationW(root, volname_buf, ctypes.sizeof(volname_buf),
                                       ctypes.byref(serial), ctypes.byref(max_comp_len),
                                       ctypes.byref(fs_flags),
                                       fs_name_buf, ctypes.sizeof(fs_name_buf))
            if ok:
                fsname = fs_name_buf.value
                if fsname and fsname.upper() == "NTFS":
                    volumes.append(drive_letter)
        except Exception:
            continue
    return volumes

# --------- Record parsing ----------
def parse_record(data_bytes, offset):
    """
    Parse a single USN record starting at offset into data_bytes.
    Returns dict or None on failure.
    """
    # Need at least 8 bytes for header to get length & version
    if offset + 8 > len(data_bytes):
        return None
    try:
        rec_len = struct.unpack_from("<I", data_bytes, offset)[0]
        # defensive checks
        if rec_len <= 0 or rec_len > (len(data_bytes) - offset):
            return None

        major_version = struct.unpack_from("<H", data_bytes, offset + 4)[0]
    except Exception:
        return None

    try:
        if major_version == 2:
            min_size = ctypes.sizeof(USN_RECORD_V2)
            if offset + min_size > len(data_bytes):
                # not enough data for the header
                return None
            hdr = USN_RECORD_V2.from_buffer_copy(data_bytes[offset:offset + min_size])
            frn = str(hdr.FileReferenceNumber)
            parent_frn = str(hdr.ParentFileReferenceNumber)
            usn = int(hdr.Usn)

            timestamp = filetime_to_datetime(hdr.TimeStamp)
            reason = reason_to_text(hdr.Reason)
            source_info = sourceinfo_to_text(hdr.SourceInfo)
            security_id = int(hdr.SecurityId)
            file_attributes = int(hdr.FileAttributes)
            fn_len, fn_off = int(hdr.FileNameLength), int(hdr.FileNameOffset)
        elif major_version == 3:
            min_size = ctypes.sizeof(USN_RECORD_V3)
            if offset + min_size > len(data_bytes):
                return None
            hdr = USN_RECORD_V3.from_buffer_copy(data_bytes[offset:offset + min_size])
            frn = file_id_128_to_str(hdr.FileReferenceNumber)
            parent_frn = file_id_128_to_str(hdr.ParentFileReferenceNumber)
            usn = int(hdr.Usn)

            timestamp = filetime_to_datetime(hdr.TimeStamp)
            reason = reason_to_text(hdr.Reason)
            source_info = sourceinfo_to_text(hdr.SourceInfo)
            security_id = int(hdr.SecurityId)
            file_attributes = int(hdr.FileAttributes)
            fn_len, fn_off = int(hdr.FileNameLength), int(hdr.FileNameOffset)
        else:
            # unknown major version - skip
            return None

        filename = ""
        if fn_len and fn_off:
            start, end = offset + fn_off, offset + fn_off + fn_len
            if end <= len(data_bytes):
                try:
                    filename = data_bytes[start:end].decode("utf-16le", errors="replace")
                except Exception:
                    filename = ""
        return {
            "major_version": major_version,
            "usn": usn,
            "frn": frn,
            "parent_frn": parent_frn,
            "timestamp": timestamp,
            "reason": reason,
            "source_info": source_info,
            "security_id": security_id,
            "file_attributes": file_attributes,
            "filename": filename,
            "record_length": rec_len
        }
    except Exception:
        return None

# --------- MFT Parsing for Enhanced Forensics ----------


def analyze_file_properties(filename, file_attributes):
    """
    Analyze file properties for forensic significance.
    Returns dict with file type analysis.
    """
    if not filename:
        return {
            'file_extension': '',
            'is_directory': 0,
            'is_system_file': 0,
            'is_hidden': 0,
            'is_executable': 0
        }
    
    # Extract file extension
    file_extension = ''
    if '.' in filename:
        file_extension = filename.split('.')[-1].lower()
    
    # Analyze file attributes
    FILE_ATTRIBUTE_DIRECTORY = 0x10
    FILE_ATTRIBUTE_SYSTEM = 0x04
    FILE_ATTRIBUTE_HIDDEN = 0x02
    
    is_directory = 1 if (file_attributes & FILE_ATTRIBUTE_DIRECTORY) else 0
    is_system_file = 1 if (file_attributes & FILE_ATTRIBUTE_SYSTEM) else 0
    is_hidden = 1 if (file_attributes & FILE_ATTRIBUTE_HIDDEN) else 0
    
    # Determine if file is executable
    executable_extensions = {
        'exe', 'com', 'bat', 'cmd', 'scr', 'pif', 'msi', 'dll',
        'sys', 'drv', 'ocx', 'cpl', 'ps1', 'vbs', 'js', 'jar'
    }
    is_executable = 1 if file_extension in executable_extensions else 0
    
    return {
        'file_extension': file_extension,
        'is_directory': is_directory,
        'is_system_file': is_system_file,
        'is_hidden': is_hidden,
        'is_executable': is_executable
    }

# --------- DB utilities ----------

class DatabaseTransaction:
    """Context manager for database transactions with automatic rollback on error"""
    def __init__(self, connection):
        self.connection = connection
        self.transaction_started = False
    
    def __enter__(self):
        try:
            self.connection.execute("BEGIN")
            self.transaction_started = True
            file_logger.info("Database transaction started")
        except sqlite3.Error as e:
            file_logger.error(f"Failed to start database transaction: {e}")
            raise
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                # No exception occurred, commit the transaction
                self.connection.commit()
                file_logger.info("Database transaction committed successfully")
            else:
                # Exception occurred, rollback the transaction
                if self.transaction_started:
                    self.connection.rollback()
                    file_logger.warning(f"Database transaction rolled back due to error: {exc_val}")
        except sqlite3.Error as e:
            file_logger.error(f"Error during transaction cleanup: {e}")
        return False  # Don't suppress exceptions

def get_memory_usage():
    """Get current memory usage in MB"""
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        return memory_info.rss / 1024 / 1024  # Convert to MB
    except Exception as e:
        file_logger.warning(f"Failed to get memory usage: {e}")
        return 0

def check_memory_usage(threshold_mb=1024):
    """Check if memory usage exceeds threshold and log warning"""
    current_memory = get_memory_usage()
    if current_memory > threshold_mb:
        file_logger.warning(f"High memory usage detected: {current_memory:.1f} MB (threshold: {threshold_mb} MB)")
        return True
    return False

def cleanup_memory():
    """Force garbage collection to free memory"""
    try:
        collected = gc.collect()
        file_logger.debug(f"Garbage collection freed {collected} objects")
        return collected
    except Exception as e:
        file_logger.warning(f"Error during garbage collection: {e}")
        return 0

def init_db(db_path=OUTPUT_DB):
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit off; we'll control commits
    cur = conn.cursor()
    
    # Table 1: Journal Events (from FSCTL_READ_USN_JOURNAL)
    # This is our "Diary Entries" - actual events with timestamps and reasons
    cur.execute('''
        CREATE TABLE IF NOT EXISTS journal_events (
            volume_letter TEXT,
            filename TEXT,
            usn INTEGER,
            major_version INTEGER,
            frn TEXT,
            parent_frn TEXT,
            timestamp TEXT,
            reason TEXT,
            source_info TEXT,
            security_id INTEGER,
            file_attributes TEXT,
            record_length INTEGER,
            inserted_at TEXT,
            PRIMARY KEY (volume_letter, usn)
        )
    ''')
    
    # Table 2: Deleted Journal Entries (USN gaps and deleted entries)
    # Tracks forensically significant gaps in the USN journal
    cur.execute('''
        CREATE TABLE IF NOT EXISTS deleted_entries (
            volume_letter TEXT,
            gap_start_usn INTEGER,
            gap_end_usn INTEGER,
            gap_size INTEGER,
            detection_timestamp TEXT,
            last_known_usn INTEGER,
            next_valid_usn INTEGER,
            forensic_significance TEXT,
            potential_activity TEXT,
            inserted_at TEXT,
            PRIMARY KEY (volume_letter, gap_start_usn)
        )
    ''')
    
    # Commit table creation before creating indexes
    conn.commit()
    
    # Indexes for performance
    cur.execute('CREATE INDEX IF NOT EXISTS idx_journal_volume ON journal_events (volume_letter, usn)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_journal_frn ON journal_events (volume_letter, frn)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_journal_timestamp ON journal_events (timestamp)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_deleted_volume ON deleted_entries (volume_letter, gap_start_usn)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_deleted_timestamp ON deleted_entries (detection_timestamp)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_deleted_gap_size ON deleted_entries (gap_size)')
    
    conn.commit()
    return conn, cur





def detect_usn_journal_version(handle, volume_letter):
    """
    Detect which USN Journal version to use by testing each version
    Returns tuple: (fsctl_code, structure_class, version_name)
    """
    versions_to_test = [
        (FSCTL_QUERY_USN_JOURNAL_V2, USN_JOURNAL_DATA_V2, "V2"),
        (FSCTL_QUERY_USN_JOURNAL_V1, USN_JOURNAL_DATA_V1, "V1"), 
        (FSCTL_QUERY_USN_JOURNAL_V0, USN_JOURNAL_DATA_V0, "V0")
    ]
    
    for fsctl_code, structure_class, version_name in versions_to_test:
        try:
            journal_buf = ctypes.create_string_buffer(ctypes.sizeof(structure_class))
            bytes_ret = wintypes.DWORD(0)
            
            ok = kernel32.DeviceIoControl(
                wintypes.HANDLE(handle), fsctl_code,
                None, 0,
                journal_buf, ctypes.sizeof(journal_buf),
                ctypes.byref(bytes_ret), None
            )
            
            if ok:
                logger.info(f"{volume_letter}: Successfully detected USN Journal {version_name}")
                return fsctl_code, structure_class, version_name
                
        except Exception as e:
            logger.debug(f"{volume_letter}: USN Journal {version_name} test failed: {e}")
            continue
    
    # If all versions fail, return None
    logger.warning(f"{volume_letter}: No compatible USN Journal version found")
    return None, None, None

# --------- Phase 2: Read Journal Events ----------
def read_journal_events(volume_letter, cursor, conn):
    """
    Phase 2: Use FSCTL_READ_USN_JOURNAL to get actual events with timestamps
    This is our "Diary Entries" - actual recorded events with timestamps and reasons
    """
    volume_path = f"\\\\.\\{volume_letter}:"
    logger.info(f"Phase 2: Reading journal events for {volume_path}")

    try:
        handle = create_file_handle(volume_path)
    except OSError as e:
        error_code = e.args[0] if e.args else 0
        if error_code == 5:  # Access denied
            logger.error(f"Access denied to {volume_path}. Administrator privileges required.")
        else:
            logger.error(f"Failed to open {volume_path}: {e}")
        return None

    try:
        # First, detect which USN journal version to use
        file_logger.info(f"{volume_letter}: Detecting USN journal version")
        
        fsctl_code, structure_class, version_name = detect_usn_journal_version(handle, volume_letter)
        
        if fsctl_code is None:
            file_logger.warning(f"Volume {volume_letter}: USN Journal not supported or not enabled")
            file_logger.info(f"To enable USN Journal on {volume_letter}:, run as Administrator: fsutil usn createjournal m=1000 a=100 {volume_letter}:")
            close_handle(handle)  # Ensure handle is closed before returning
            return None
        
        # Query the USN journal using the detected version
        file_logger.info(f"{volume_letter}: Querying USN journal information using {version_name}")
        
        journal_buf = ctypes.create_string_buffer(ctypes.sizeof(structure_class))
        bytes_ret = wintypes.DWORD(0)
        
        ok = kernel32.DeviceIoControl(
            wintypes.HANDLE(handle), fsctl_code,
            None, 0,
            journal_buf, ctypes.sizeof(journal_buf),
            ctypes.byref(bytes_ret), None
        )
        
        if not ok:
            err = ctypes.GetLastError()
            logger.error(f"Volume {volume_letter}: FSCTL_QUERY_USN_JOURNAL failed with error {err}")
            close_handle(handle)  # Ensure handle is closed before returning
            return None
        
        # Parse journal information using the detected structure
        journal_data = structure_class.from_buffer_copy(journal_buf.raw)
        file_logger.info(f"{volume_letter}: Journal ID: {journal_data.UsnJournalID}")
        file_logger.info(f"{volume_letter}: First USN: {journal_data.FirstUsn}")
        file_logger.info(f"{volume_letter}: Next USN: {journal_data.NextUsn}")
        file_logger.info(f"{volume_letter}: Lowest Valid USN: {journal_data.LowestValidUsn}")
        
        # Validate USN range to prevent error 87 (ERROR_INVALID_PARAMETER)
        if journal_data.FirstUsn >= journal_data.NextUsn:
            file_logger.warning(f"Volume {volume_letter}: Invalid USN range - FirstUSN >= NextUSN")
            close_handle(handle)  # Ensure handle is closed before returning
            return 0
        
        # Now use FSCTL_READ_USN_JOURNAL to read actual journal entries with valid timestamps
        file_logger.info(f"{volume_letter}: Reading USN journal entries with FSCTL_READ_USN_JOURNAL")
        
        # Set up READ_USN_JOURNAL_DATA_V0 structure
        read_struct = READ_USN_JOURNAL_DATA_V0()
        read_struct.StartUsn = journal_data.FirstUsn  # Start from first available USN
        read_struct.ReasonMask = 0xFFFFFFFF  # All reasons
        read_struct.ReturnOnlyOnClose = 0   # Return all records, not just close records
        read_struct.Timeout = 0             # No timeout
        read_struct.BytesToWaitFor = 0      # Don't wait for new data
        read_struct.UsnJournalID = journal_data.UsnJournalID
        
        # Use larger buffer for better performance (1MB instead of default)
        ENHANCED_BUFFER_SIZE = 1024 * 1024  # 1MB buffer for faster reading
        out_buf = ctypes.create_string_buffer(ENHANCED_BUFFER_SIZE)
        record_count = 0
        total_bytes_processed = 0
        
        # Enhanced batch processing for better performance
        batch_records = []
        batch_size = 1000  # Process records in larger batches
        excluded_count = 0  # Track excluded files for summary logging
        
        # Calculate total USN range for progress tracking
        total_usn_range = journal_data.NextUsn - journal_data.FirstUsn
        start_usn = journal_data.FirstUsn
        
        # Convert to MB for display (USN values are roughly equivalent to bytes)
        total_usn_range_mb = total_usn_range / (1024 * 1024)
        
        # Initialize progress bar with total USN range in MB and enhanced format
        pbar = tqdm(total=total_usn_range_mb, unit="MB", unit_scale=False, 
                   desc=f"Journal {volume_letter}", 
                   bar_format="{l_bar}{bar}| {n:.1f}/{total:.1f} {unit} [{percentage:3.1f}%] {elapsed} {postfix}")
        
        # Track timing for proper rate calculation
        import time
        start_time = time.time()
        MAX_PROCESSING_TIME = 3600  # 1 hour timeout to prevent infinite loops
        stall_detection_usn = read_struct.StartUsn
        stall_detection_time = start_time
        MAX_STALL_TIME = 300  # 5 minutes without USN advancement
        
        # Progress bar update frequency
        progress_update_counter = 0
        PROGRESS_UPDATE_FREQUENCY = 50  # Update every 50 records for more frequent updates
        
        try:
            while True:
                # Check for timeout conditions
                current_time = time.time()
                if current_time - start_time > MAX_PROCESSING_TIME:
                    logger.warning(f"Volume {volume_letter}: Processing timeout after {MAX_PROCESSING_TIME} seconds")
                    break
                
                # Check for USN advancement stall
                if current_time - stall_detection_time > MAX_STALL_TIME:
                    if read_struct.StartUsn == stall_detection_usn:
                        logger.warning(f"Volume {volume_letter}: USN advancement stalled at {read_struct.StartUsn} for {MAX_STALL_TIME} seconds")
                        break
                    else:
                        # USN advanced, reset stall detection
                        stall_detection_usn = read_struct.StartUsn
                        stall_detection_time = current_time
                bytes_ret = wintypes.DWORD(0)
                
                # Read a chunk of USN journal entries
                ok = kernel32.DeviceIoControl(
                    wintypes.HANDLE(handle), FSCTL_READ_USN_JOURNAL,
                    ctypes.byref(read_struct), ctypes.sizeof(read_struct),
                    out_buf, ctypes.sizeof(out_buf),
                    ctypes.byref(bytes_ret), None
                )
                
                if not ok:
                    err = ctypes.GetLastError()
                    if err == ERROR_HANDLE_EOF or err == ERROR_NO_DATA:
                        # End of journal reached
                        logger.info(f"{volume_letter}: Reached end of USN journal")
                        break
                    elif err == 1179:  # ERROR_JOURNAL_NOT_ACTIVE
                        logger.warning(f"Volume {volume_letter}: USN Journal became inactive")
                        break
                    elif err == 87:  # ERROR_INVALID_PARAMETER
                        # Check if we're stuck in a loop by tracking consecutive error 87s
                        if not hasattr(read_struct, '_error87_count'):
                            read_struct._error87_count = 0
                            read_struct._last_error87_usn = read_struct.StartUsn
                        
                        # If we're hitting error 87 at the same USN repeatedly, make a bigger jump
                        if read_struct.StartUsn == read_struct._last_error87_usn:
                            read_struct._error87_count += 1
                        else:
                            read_struct._error87_count = 1
                            read_struct._last_error87_usn = read_struct.StartUsn
                        
                        # If we've hit error 87 too many times, make a significant jump
                        if read_struct._error87_count > 5:
                            jump_size = 1024 * 1024  # Jump 1MB forward
                            logger.warning(f"Volume {volume_letter}: Multiple error 87s - jumping {jump_size} bytes forward")
                            read_struct.StartUsn += jump_size
                            read_struct._error87_count = 0
                        else:
                            # Normal small increment
                            read_struct.StartUsn += 64  # Advance by 64 bytes instead of 8
                        
                        # Safety check - don't go beyond NextUsn
                        if read_struct.StartUsn >= journal_data.NextUsn:
                            logger.info(f"{volume_letter}: Reached end of journal after error 87 handling")
                            break
                        continue
                    elif err == 1181:  # ERROR_JOURNAL_ENTRY_DELETED
                        # Journal entries have been deleted due to space constraints - this is normal
                        # Try smaller increments first to avoid missing valid data
                        gap_start = read_struct.StartUsn
                        
                        # Start with small increment and increase if needed
                        increment = 8  # Start with 8 bytes (size of USN)
                        max_increment = 1000
                        
                        while increment <= max_increment:
                            test_usn = gap_start + increment
                            
                            # Test if this USN works by trying a small read
                            test_struct = read_struct
                            test_struct.StartUsn = test_usn
                            
                            test_buf = ctypes.create_string_buffer(1024)  # Small test buffer
                            test_bytes = wintypes.DWORD(0)
                            
                            test_ok = kernel32.DeviceIoControl(
                                wintypes.HANDLE(handle), FSCTL_READ_USN_JOURNAL,
                                ctypes.byref(test_struct), ctypes.sizeof(test_struct),
                                test_buf, ctypes.sizeof(test_buf),
                                ctypes.byref(test_bytes), None
                            )
                            
                            if test_ok or ctypes.GetLastError() != 1181:
                                # Found valid USN or different error - use this position
                                gap_end = test_usn
                                break
                            
                            increment *= 2  # Double the increment and try again
                        else:
                            # If we couldn't find valid data, use the max increment
                            gap_end = gap_start + max_increment
                        
                        # Record the deleted entry gap for forensic analysis
                        record_deleted_entry(volume_letter, gap_start, gap_end, cursor, conn)
                        
                        # Advance USN to the found position
                        read_struct.StartUsn = gap_end
                        continue
                    else:
                        logger.error(f"Volume {volume_letter}: FSCTL_READ_USN_JOURNAL failed with error {err}")
                        break
                
                if bytes_ret.value == 0:
                    logger.info(f"{volume_letter}: No more USN data available")
                    break
                
                data = out_buf.raw[:bytes_ret.value]
                if len(data) < 8:
                    logger.warning(f"Volume {volume_letter}: Insufficient USN data returned")
                    break
                
                # First 8 bytes contain the next USN to read from
                try:
                    next_usn = struct.unpack_from("<Q", data, 0)[0]
                    previous_start_usn = read_struct.StartUsn  # Store previous USN for comparison
                    read_struct.StartUsn = next_usn  # Update for next iteration
                    
                    # Progress bar is now updated more frequently in the record processing loop
                except Exception as e:
                    logger.error(f"Failed to parse next USN: {e}")
                    break
                
                # Parse USN records starting from offset 8
                offset = 8
                chunk_records = 0
                
                while offset + 8 <= len(data):
                    try:
                        rec_len = struct.unpack_from("<I", data, offset)[0]
                    except Exception:
                        break
                    
                    if rec_len <= 0 or offset + rec_len > len(data):
                        break
                    
                    rec = parse_record(data, offset)
                    if rec:
                        # Apply forensic filtering to exclude self-referential entries
                        if should_exclude_from_analysis(rec["filename"]):
                            # Count excluded entries instead of logging each one
                            excluded_count += 1
                            offset += rec_len
                            continue
                        
                        record_count += 1
                        chunk_records += 1
                        inserted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
                        
                        # Add to batch instead of immediate insert
                        batch_records.append((
                            volume_letter, rec["filename"], rec["usn"], rec["major_version"], rec["frn"], rec["parent_frn"],
                            rec["timestamp"], rec["reason"], rec["source_info"], rec["security_id"],
                            rec["file_attributes"], rec["record_length"], inserted_at
                        ))
                        
                        # Increment progress counter and update progress bar more frequently
                        progress_update_counter += 1
                        if progress_update_counter >= PROGRESS_UPDATE_FREQUENCY:
                            # Update progress bar based on USN position
                            current_progress = next_usn - start_usn
                            if current_progress <= total_usn_range:
                                # Calculate elapsed time and rate
                                elapsed_time = time.time() - start_time
                                if elapsed_time > 0:
                                    # Progress bar without rate and ETA display
                                    pbar.set_postfix_str("")
                                # Convert current progress to MB for display
                                current_progress_mb = current_progress / (1024 * 1024)
                                pbar.n = current_progress_mb
                                pbar.refresh()
                            progress_update_counter = 0  # Reset counter
                        
                        # Process batch when it reaches batch_size
                        if len(batch_records) >= batch_size:
                            with DatabaseTransaction(conn) as transaction:
                                # Check for existing records to avoid duplicates
                                new_records = []
                                usn_list = [str(record[1]) for record in batch_records]  # USN is at index 1
                                
                                # Query existing USNs in batch
                                placeholders = ','.join(['?' for _ in usn_list])
                                cursor.execute(f"SELECT usn FROM journal_events WHERE volume_letter = ? AND usn IN ({placeholders})", 
                                             [volume_letter] + usn_list)
                                existing_usns = set(row[0] for row in cursor.fetchall())
                                
                                # Filter out existing records
                                for record in batch_records:
                                    if record[1] not in existing_usns:  # USN is at index 1
                                        new_records.append(record)
                                
                                # Insert only new records
                                if new_records:
                                    cursor.executemany(
                                        "INSERT INTO journal_events (volume_letter, filename, usn, major_version, frn, parent_frn, timestamp, reason, source_info, security_id, file_attributes, record_length, inserted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                        new_records
                                    )
                                
                                batch_records.clear()
                                
                                # Memory monitoring and cleanup
                                if check_memory_usage(1024):  # Check if memory > 1GB
                                    cleanup_memory()
                    
                    offset += rec_len
                
                total_bytes_processed += len(data)
                
                # If we didn't get any records in this chunk, we might be at the end
                if chunk_records == 0:
                    file_logger.info(f"{volume_letter}: No more records found, ending read")
                    break
                
                # If the next USN hasn't advanced from the previous iteration, we're done
                if next_usn == previous_start_usn:
                    logger.info(f"{volume_letter}: USN hasn't advanced, ending read")
                    break
            
            # Final commit
            conn.commit()
            pbar.close()
            
        except KeyboardInterrupt:
            logger.warning("Interrupted by user - committing and exiting journal read")
        finally:
            # Process any remaining records in the batch
            if batch_records:
                with DatabaseTransaction(conn) as transaction:
                    # Check for existing records in final batch
                    new_records = []
                    usn_list = [str(record[1]) for record in batch_records]  # USN is at index 1
                    
                    # Query existing USNs in final batch
                    placeholders = ','.join(['?' for _ in usn_list])
                    cursor.execute(f"SELECT usn FROM journal_events WHERE volume_letter = ? AND usn IN ({placeholders})", 
                                 [volume_letter] + usn_list)
                    existing_usns = set(row[0] for row in cursor.fetchall())
                    
                    # Filter out existing records
                    for record in batch_records:
                        if record[1] not in existing_usns:  # USN is at index 1
                            new_records.append(record)
                    
                    # Insert only new records
                    if new_records:
                        cursor.executemany(
                            "INSERT INTO journal_events (volume_letter, filename, usn, major_version, frn, parent_frn, timestamp, reason, source_info, security_id, file_attributes, record_length, inserted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            new_records
                        )
                    
                    logger.info(f"Final batch: {len(new_records)} new records inserted")

        logger.info(f"{volume_letter}: {record_count} journal events parsed from {total_bytes_processed} bytes")
        if excluded_count > 0:
            file_logger.info(f"{volume_letter}: Excluded {excluded_count} files from analysis (database files, temp files, etc.)")
        return record_count
    finally:
        close_handle(handle)



# --------- Main USN Processing Function ----------
def read_usn_journal_for_volume(volume_letter, cursor, conn):
    """
    Main function that reads and processes USN Journal events for forensic analysis.
    Focuses solely on USN Journal parsing and event extraction.
    """
    # Detailed logging to file only
    file_logger.info(f"=== Starting forensic analysis for volume {volume_letter}: ===")
    
    # Simple console output
    print(f"Processing volume {volume_letter}...")
    
    try:
        # Read journal events using FSCTL_READ_USN_JOURNAL
        file_logger.info(f"Reading USN journal events for {volume_letter}:")
        event_count = read_journal_events(volume_letter, cursor, conn)
        if event_count is None:
            file_logger.warning(f"Failed to read journal events for {volume_letter}")
            event_count = 0
        
        # Summary - show only essential info in console
        print(f"Volume {volume_letter}: {event_count} journal events processed")
        
        # Detailed summary to file
        file_logger.info(f"=== USN Journal parsing complete for {volume_letter}: ===")
        file_logger.info(f"  Journal events: {event_count}")
        
        return {
            'journal_events': event_count
        }
        
    except Exception as e:
        logger.error(f"Error processing {volume_letter}: {e}")
        return None
        
        # Gap recorded silently - data is stored in database for forensic analysis
        
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to record deleted entry gap: {e}")

# --------- Main ----------
def main():
    # Check for administrator privileges
    if not is_admin():
        logger.error("This script requires administrator privileges to access USN Journal.")
        logger.error("Please run as administrator (right-click -> 'Run as administrator')")
        return 1  # Return error code instead of exiting

    logger.info("Running with administrator privileges")

    volumes = get_ntfs_volumes()
    if not volumes:
        logger.error("No NTFS fixed volumes detected. Exiting.")
        return 1  # Return error code instead of exiting

    logger.info(f"Found volumes: {', '.join(volumes)}")

    # Create Target_Artifacts directory for consistent output location
    target_artifacts_dir = os.path.join(".", "Target_Artifacts")
    os.makedirs(target_artifacts_dir, exist_ok=True)
    
    # Use Target_Artifacts directory for database
    usn_db_path = os.path.join(target_artifacts_dir, "USN_journal.db")
    conn, cursor = init_db(usn_db_path)
    processed_count = 0
    volume_results = {}

    try:
        for vol in volumes:
            try:
                result = read_usn_journal_for_volume(vol, cursor, conn)
                if result is not None:  # Successfully processed
                    processed_count += 1
                    if isinstance(result, dict):
                        volume_results[vol] = result
                        logger.info(f"Volume {vol} summary: {result['journal_events']} journal events processed")
            except Exception as e:
                logger.error(f"Unexpected error processing {vol}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if processed_count == 0:
        logger.warning("No volumes were successfully processed. This may be due to:")
        logger.warning("- USN Journal not enabled on any volumes")
        logger.warning("- Insufficient privileges")
        logger.warning("- Volumes not being NTFS")
        logger.info("To enable USN Journal for forensic analysis, run as Administrator:")
        logger.info("  fsutil usn createjournal m=1000 a=100 C:")
    else:
        logger.info(f"Successfully processed {processed_count} volume(s) for USN Journal analysis")
        
        # Check if any volumes had no journal events
        has_journal_issues = False
        for vol, result in volume_results.items():
            if result['journal_events'] == 0:
                has_journal_issues = True
                break
        
        if has_journal_issues:
            logger.info("Note: Some volumes had no journal events. For full USN Journal analysis:")
            logger.info("  Enable USN Journal with: fsutil usn createjournal m=1000 a=100 <drive>:")
            logger.info("  Then re-run this tool to capture file system activity")

    logger.info("Done.")
    return 0  # Success

if __name__ == "__main__":
    sys.exit(main())
