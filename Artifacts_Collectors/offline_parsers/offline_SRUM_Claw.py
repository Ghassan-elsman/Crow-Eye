"""
Crow Eye - Offline SRUM (System Resource Usage Monitor) Parser
================================================================

Offline Windows SRUM database parser for digital forensic investigations.
This module provides comprehensive analysis of collected SRUDB.dat files,
extracting critical application resource usage, network connectivity, and
energy consumption data for timeline reconstruction and behavior analysis.

Features:
---------
• Offline Parsing: Parse collected SRUDB.dat files without Windows API access
• ESE Database Support: Uses libesedb-python for Extensible Storage Engine format
• Application Tracking: Resource usage metrics per application
• Network Analysis: Connectivity and data usage patterns
• Energy Monitoring: Power consumption and battery metrics
• User Attribution: Links activity to specific user accounts via SID resolution
• Database Integration: SQLite storage with indexed forensic metadata
• Schema Compatibility: Identical output to live SRUM-Claw parser

Supported SRUM Tables:
---------------------
• Application Resource Usage: CPU time, I/O operations, memory usage
• Network Connectivity: Connection times, interface information
• Network Data Usage: Bytes sent/received per application
• Energy Usage: Battery consumption and charge levels

Forensic Value:
--------------
• Evidence of program execution with detailed resource metrics
• Network activity timeline reconstruction
• User behavior analysis and attribution
• Timeline correlation with other artifacts
• Identification of suspicious resource consumption patterns

Usage Examples:
--------------
# Parse offline SRUDB.dat file
result = main(srudb_path="path/to/SRUDB.dat", case_path="output/directory")

# Parse with registry hives for enhanced SID resolution
result = main(
    srudb_path="path/to/SRUDB.dat",
    case_path="output/directory",
    registry_hives=["path/to/SAM", "path/to/SOFTWARE"]
)

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
import sqlite3
import logging
import datetime
from typing import List, Optional, Dict, Tuple
from pathlib import Path

# Import time utilities for standardized forensic timestamp formatting
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from utils.time_utils import format_forensic_timestamp, get_current_forensic_timestamp, get_current_utc

# Try to import Registry library for registry hive parsing
try:
    from Registry import Registry
    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False
    logger.warning("Registry library not available - registry hive SID resolution will be disabled")

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Configure logging for forensic analysis
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SRUM-Offline] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================================
# ESE DATABASE LIBRARY IMPORTS
# ============================================================================

# Try to import ESE database libraries (in order of preference for dirty database handling)
# dissect.esedb is preferred for forensic analysis as it handles dirty databases better
try:
    from dissect.esedb import EseDB
    ESEDB_AVAILABLE = True
    ESEDB_LIBRARY = "dissect"
    logger.info("Using dissect.esedb library (best for dirty state databases)")
except ImportError:
    try:
        import pyesedb
        ESEDB_AVAILABLE = True
        ESEDB_LIBRARY = "pyesedb"
        logger.info("Using pyesedb library")
    except ImportError:
        try:
            import libesedb
            ESEDB_AVAILABLE = True
            ESEDB_LIBRARY = "libesedb"
            logger.info("Using libesedb library")
        except ImportError:
            ESEDB_AVAILABLE = False
            ESEDB_LIBRARY = None

# ============================================================================
# DATABASE SCHEMA CONSTANTS
# ============================================================================
# These schemas match the live SRUM-Claw parser exactly for compatibility

# Application Resource Usage Table Schema
SCHEMA_APPLICATION_USAGE = """
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
"""

# Network Connectivity Table Schema
SCHEMA_NETWORK_CONNECTIVITY = """
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
"""

# Network Data Usage Table Schema
SCHEMA_NETWORK_DATA_USAGE = """
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
"""

# Energy Usage Table Schema
SCHEMA_ENERGY_USAGE = """
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
"""

# Metadata Table Schema
SCHEMA_METADATA = """
    CREATE TABLE IF NOT EXISTS srum_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parse_timestamp TEXT NOT NULL,
        srudb_path TEXT,
        total_records_parsed INTEGER,
        parsing_duration_seconds REAL,
        windows_version TEXT,
        notes TEXT
    )
"""

# Index Creation Statements
INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_app_usage_timestamp ON srum_application_usage(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_app_usage_app_name ON srum_application_usage(app_name)",
    "CREATE INDEX IF NOT EXISTS idx_app_usage_user_name ON srum_application_usage(user_name)",
    "CREATE INDEX IF NOT EXISTS idx_net_conn_timestamp ON srum_network_connectivity(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_net_conn_app_name ON srum_network_connectivity(app_name)",
    "CREATE INDEX IF NOT EXISTS idx_net_data_timestamp ON srum_network_data_usage(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_net_data_app_name ON srum_network_data_usage(app_name)",
    "CREATE INDEX IF NOT EXISTS idx_energy_timestamp ON srum_energy_usage(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_energy_app_name ON srum_energy_usage(app_name)",
]

# ============================================================================
# SRUM TABLE GUID MAPPINGS
# ============================================================================
# These GUIDs identify specific tables in the SRUDB.dat ESE database
# Based on Windows SRUM forensics research and documentation

SRUM_TABLE_GUIDS = {
    'APPLICATION_RESOURCE_USAGE': '{D10CA2FE-6FCF-4F6D-848E-B2E99266FA89}',
    'NETWORK_DATA_USAGE': '{973F5D5C-1D90-4944-BE8E-24B94231A174}',
    'NETWORK_CONNECTIVITY': '{DD6636C4-8929-4683-974E-22C046A43763}',
    'ENERGY_USAGE': '{FEE4E14F-02A9-4550-B5CE-5FA2DA202E37}',
    'ENERGY_USAGE_LONG_TERM': '{DA73FB89-2BEA-4DDC-86B8-6E048C6DA477}',
}

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
# Used for parsing ESE database tables
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
    ]
}

# ============================================================================
# EXCEPTION CLASSES
# ============================================================================

class SRUMParsingError(Exception):
    """Base exception for SRUM parsing errors."""
    pass


class SRUMFileAccessError(SRUMParsingError):
    """Raised when SRUDB.dat cannot be accessed."""
    pass


class SRUMDatabaseCorruptError(SRUMParsingError):
    """Raised when SRUDB.dat is corrupted or invalid."""
    pass


class SRUMLibraryNotAvailableError(SRUMParsingError):
    """Raised when required ESE parsing library is not available."""
    pass


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def create_database(case_path: Optional[str] = None) -> Tuple[sqlite3.Connection, sqlite3.Cursor, str]:
    """
    Create srum_data.db database with schema matching live SRUM-Claw parser.
    
    Args:
        case_path: Optional path to case directory. If provided, database will be
                  created in case_path/live_acquisition/srum_data.db
    
    Returns:
        Tuple of (connection, cursor, db_path)
    
    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
    """
    db_path = 'srum_data.db'
    
    if case_path:
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        os.makedirs(artifacts_dir, exist_ok=True)
        db_path = os.path.join(artifacts_dir, 'srum_data.db')
    
    logger.info(f"Creating database at: {db_path}")
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create tables with exact schema from live parser
        cursor.execute(SCHEMA_APPLICATION_USAGE)
        cursor.execute(SCHEMA_NETWORK_CONNECTIVITY)
        cursor.execute(SCHEMA_NETWORK_DATA_USAGE)
        cursor.execute(SCHEMA_ENERGY_USAGE)
        cursor.execute(SCHEMA_METADATA)
        
        # Create indexes for performance
        for index_sql in INDEX_STATEMENTS:
            cursor.execute(index_sql)
        
        conn.commit()
        logger.info("Database schema created successfully")
        
        return conn, cursor, db_path
        
    except sqlite3.Error as e:
        logger.error(f"Database creation failed: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Database path: {db_path}")
        
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                logger.info(f"Cleaned up partial database file: {db_path}")
            except OSError as cleanup_error:
                logger.warning(f"Failed to clean up partial database file: {cleanup_error}")
        
        raise
    except Exception as e:
        logger.error(f"Unexpected error during database creation: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        
        raise


# ============================================================================
# ID RESOLUTION CLASSES
# ============================================================================

class IDResolver:
    """
    Resolves App IDs and User SIDs to human-readable names.
    
    Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
    """
    
    def __init__(self, id_map: Dict[int, Tuple[str, str]], registry_hives: Optional[List[str]] = None):
        """
        Initialize with ID map from SruDbIdMapTable.
        Optionally provide registry hives for additional SID resolution.

        Args:
            id_map: Dictionary mapping ID -> (resolved_value, type)
            registry_hives: Optional list of registry hive paths for SID resolution

        Requirements: 5.3
        """
        self.app_id_map = {}
        self.user_id_map = {}
        self.unresolved_app_ids = set()
        self.unresolved_user_ids = set()
        self.registry_sid_map = {}  # SID -> username from registry hives

        # Separate app IDs and user IDs
        for id_num, (value, id_type) in id_map.items():
            if id_type == 'app':
                self.app_id_map[id_num] = value
            elif id_type == 'user':
                self.user_id_map[id_num] = value

        # Add special system IDs
        for id_num, (name, _) in SPECIAL_APP_IDS.items():
            self.app_id_map[id_num] = name

        for id_num, (sid, name) in SPECIAL_USER_IDS.items():
            self.user_id_map[id_num] = (sid, name)

        # Load registry hives if provided
        if registry_hives:
            self.load_registry_hives(registry_hives)

    def load_registry_hives(self, hive_paths: List[str]):
        """
        Load registry hives for additional SID resolution.
        
        Parses SOFTWARE hive to extract user profile information from:
        SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList
        
        Args:
            hive_paths: List of registry hive file paths to load
        
        Requirements: 5.3
        """
        if not REGISTRY_AVAILABLE:
            logger.warning("Registry library not available - skipping registry hive loading")
            return
        
        for hive_path in hive_paths:
            try:
                if not os.path.exists(hive_path):
                    logger.warning(f"Registry hive not found: {hive_path}")
                    continue
                
                logger.info(f"Loading registry hive: {hive_path}")
                
                # Open registry hive
                reg = Registry.Registry(hive_path)
                
                # Try to find ProfileList key (typically in SOFTWARE hive)
                profile_list_path = "Microsoft\\Windows NT\\CurrentVersion\\ProfileList"
                
                try:
                    # Try with SOFTWARE prefix
                    try:
                        profile_key = reg.open(f"SOFTWARE\\{profile_list_path}")
                    except:
                        # Try without SOFTWARE prefix (in case it's already at root)
                        profile_key = reg.open(profile_list_path)
                    
                    # Iterate through each SID subkey
                    for subkey in profile_key.subkeys():
                        sid = subkey.name()
                        
                        # Skip non-SID keys
                        if not sid.startswith('S-'):
                            continue
                        
                        try:
                            # Get ProfileImagePath value to extract username
                            profile_image_path = None
                            for value in subkey.values():
                                if value.name() == "ProfileImagePath":
                                    profile_image_path = value.value()
                                    break
                            
                            if profile_image_path:
                                # Extract username from path (e.g., C:\Users\John -> John)
                                username = profile_image_path.split('\\')[-1] if '\\' in profile_image_path else profile_image_path
                                
                                # Store SID -> username mapping
                                self.registry_sid_map[sid] = username
                                logger.debug(f"Mapped SID {sid} to username {username} from registry")
                        
                        except Exception as e:
                            logger.debug(f"Error reading profile for SID {sid}: {e}")
                            continue
                    
                    logger.info(f"Loaded {len(self.registry_sid_map)} SID mappings from registry hive")
                
                except Exception as e:
                    logger.debug(f"ProfileList not found in hive {hive_path}: {e}")
            
            except Exception as e:
                logger.error(f"Error loading registry hive {hive_path}: {e}")
                continue

    
    def resolve_app_id(self, app_id: int) -> Tuple[str, str]:
        """
        Resolve application ID to application name and path.
        
        Args:
            app_id: Application ID from SRUM data
        
        Returns:
            Tuple of (app_name, app_path). Returns raw ID if resolution fails.
        
        Requirements: 5.1, 5.4, 5.6
        """
        if app_id in self.app_id_map:
            app_path = self.app_id_map[app_id]
            app_name = os.path.basename(app_path) if app_path else f"AppID_{app_id}"
            return (app_name, app_path)
        else:
            # Log unresolved ID (debug level to avoid cluttering output)
            if app_id not in self.unresolved_app_ids:
                self.unresolved_app_ids.add(app_id)
                logger.debug(f"Unresolved App ID: {app_id}")
            
            return (f"AppID_{app_id}", f"AppID_{app_id}")
    
    def resolve_sid(self, user_id: int) -> Tuple[str, str]:
        """
        Resolve User ID to SID and username.
        Uses both SruDbIdMapTable and registry hives for resolution.
        
        Args:
            user_id: User ID from SRUM data
        
        Returns:
            Tuple of (sid, username). Returns raw ID if resolution fails.
        
        Requirements: 5.2, 5.3, 5.5, 5.6
        """
        if user_id in self.user_id_map:
            sid_data = self.user_id_map[user_id]
            if isinstance(sid_data, tuple):
                sid, username = sid_data
                
                # If username is not resolved but we have registry data, try registry
                if (not username or username == sid) and sid in self.registry_sid_map:
                    username = self.registry_sid_map[sid]
                    logger.debug(f"Enhanced SID resolution using registry: {sid} -> {username}")
                
                return (sid, username)
            else:
                sid = sid_data
                
                # Try to resolve using registry hives
                if sid in self.registry_sid_map:
                    username = self.registry_sid_map[sid]
                    logger.debug(f"Resolved SID using registry: {sid} -> {username}")
                    return (sid, username)
                
                return (sid, sid)
        else:
            # Log unresolved ID (debug level to avoid cluttering output)
            if user_id not in self.unresolved_user_ids:
                self.unresolved_user_ids.add(user_id)
                logger.debug(f"Unresolved User ID: {user_id}")
            
            return (f"UserID_{user_id}", f"UserID_{user_id}")


# ============================================================================
# ESE DATABASE PARSER
# ============================================================================

class ESEDatabaseParser:
    """
    Parser for SRUDB.dat using ESE database library.
    
    Requirements: 3.1, 9.2
    """
    
    def __init__(self, srudb_path: str):
        """
        Initialize parser with path to SRUDB.dat.
        
        Args:
            srudb_path: Path to the SRUDB.dat file
        """
        self.srudb_path = srudb_path
        self.ese_db = None
        self.temp_recovery_dir = None  # For dirty state recovery
    
    def open_database(self):
        """
        Open ESE database file and validate structure.
        
        Handles databases in "dirty state" (not properly shut down) by using
        different ESE libraries with varying levels of dirty database support:
        
        1. dissect.esedb - Best for dirty databases (forensic-focused)
        2. pyesedb - May handle some dirty databases
        3. libesedb - Limited dirty database support
        4. esentutl repair - Fallback for severely dirty databases
        
        Requirements: 3.1, 9.2
        """
        try:
            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb is designed for forensic analysis and handles dirty databases well
                logger.info(f"Opening SRUDB.dat with dissect.esedb: {self.srudb_path}")
                self.ese_db = EseDB(open(self.srudb_path, 'rb'))
                logger.info(f"Successfully opened SRUDB.dat with dissect.esedb")
                
            elif ESEDB_LIBRARY == "pyesedb":
                # pyesedb can handle some dirty databases automatically
                logger.info(f"Opening SRUDB.dat with pyesedb: {self.srudb_path}")
                self.ese_db = pyesedb.open(self.srudb_path)
                logger.info(f"Successfully opened SRUDB.dat with pyesedb")
                
            else:
                # libesedb also handles some dirty databases
                logger.info(f"Opening SRUDB.dat with libesedb: {self.srudb_path}")
                self.ese_db = libesedb.file()
                self.ese_db.open(self.srudb_path)
                logger.info(f"Successfully opened SRUDB.dat with libesedb")
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check if this is a dirty state error
            if "page" in error_msg or "catalog" in error_msg or "invalid" in error_msg or "dirty" in error_msg:
                logger.warning(f"Database appears to be in dirty state: {e}")
                
                # If we're not using dissect, suggest trying it
                if ESEDB_LIBRARY != "dissect":
                    logger.error(
                        f"\n{'='*70}\n"
                        f"DIRTY STATE DATABASE DETECTED\n"
                        f"{'='*70}\n"
                        f"The SRUM database is in 'dirty state' (not properly shut down).\n"
                        f"This is common for databases collected from live systems or forensic images.\n\n"
                        f"SOLUTION: Install dissect.esedb for better dirty database support:\n"
                        f"  pip install dissect.esedb\n\n"
                        f"dissect.esedb is specifically designed for forensic analysis and\n"
                        f"handles dirty state databases much better than pyesedb/libesedb.\n"
                        f"{'='*70}\n"
                    )
                
                # Try esentutl repair as last resort
                logger.info("Attempting to repair database using esentutl...")
                
                try:
                    import tempfile
                    import shutil
                    import subprocess
                    
                    # Create a temporary copy for repair
                    temp_dir = tempfile.mkdtemp(prefix="srum_recovery_")
                    temp_srudb = os.path.join(temp_dir, "SRUDB.dat")
                    
                    logger.info(f"Creating temporary copy for repair: {temp_srudb}")
                    shutil.copy2(self.srudb_path, temp_srudb)
                    
                    # Run esentutl repair (not recovery, since we don't have log files)
                    logger.info("Running esentutl /p (repair mode) on database...")
                    result = subprocess.run(
                        ["esentutl", "/p", temp_srudb, "/o"],
                        cwd=temp_dir,
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    
                    if result.returncode == 0 or "Operation completed successfully" in result.stdout:
                        logger.info("Database repair completed successfully")
                        
                        # Try to open the repaired database
                        if ESEDB_LIBRARY == "dissect":
                            self.ese_db = EseDB(open(temp_srudb, 'rb'))
                        elif ESEDB_LIBRARY == "pyesedb":
                            self.ese_db = pyesedb.open(temp_srudb)
                        else:
                            self.ese_db = libesedb.file()
                            self.ese_db.open(temp_srudb)
                        
                        logger.info("Successfully opened repaired database")
                        self.temp_recovery_dir = temp_dir
                        return
                    else:
                        logger.warning(f"esentutl returned code {result.returncode}")
                        logger.debug(f"esentutl output: {result.stdout}")
                        logger.debug(f"esentutl errors: {result.stderr}")
                        
                except FileNotFoundError:
                    logger.error("esentutl not found. This tool is required to repair dirty SRUM databases.")
                    logger.error("esentutl is part of Windows and should be available in System32.")
                    
                except subprocess.TimeoutExpired:
                    logger.error("esentutl repair timed out after 120 seconds")
                    
                except Exception as repair_error:
                    logger.error(f"Repair attempt failed: {repair_error}")
                
                finally:
                    # Clean up temp directory if repair failed
                    if not hasattr(self, 'temp_recovery_dir') or self.temp_recovery_dir is None:
                        if 'temp_dir' in locals() and os.path.exists(temp_dir):
                            try:
                                shutil.rmtree(temp_dir)
                            except:
                                pass
                
                # If we get here, repair failed
                raise SRUMDatabaseCorruptError(
                    f"\n{'='*70}\n"
                    f"CANNOT OPEN DIRTY STATE DATABASE\n"
                    f"{'='*70}\n"
                    f"The SRUM database is in 'dirty state' and cannot be opened.\n\n"
                    f"RECOMMENDED SOLUTIONS:\n\n"
                    f"1. Install dissect.esedb (BEST OPTION for forensics):\n"
                    f"   pip install dissect.esedb\n"
                    f"   Then run this parser again.\n\n"
                    f"2. Manually repair the database:\n"
                    f"   a. Copy SRUDB.dat to a working directory\n"
                    f"   b. Run: esentutl /p SRUDB.dat /o\n"
                    f"   c. Parse the repaired database\n\n"
                    f"3. Use the live SRUM parser (Artifacts_Collectors/SRUM_Claw.py)\n"
                    f"   which uses Windows ESE API and can handle dirty databases.\n"
                    f"{'='*70}\n"
                )
            else:
                logger.error(f"Failed to open SRUDB.dat: {e}")
                raise SRUMDatabaseCorruptError(f"Cannot open SRUDB.dat: {e}")
    
    def close_database(self):
        """Close the ESE database and clean up temporary files."""
        if self.ese_db:
            try:
                self.ese_db.close()
            except Exception:
                pass
        
        # Clean up temporary recovery directory if it exists
        if self.temp_recovery_dir and os.path.exists(self.temp_recovery_dir):
            try:
                import shutil
                shutil.rmtree(self.temp_recovery_dir)
                logger.debug(f"Cleaned up temporary recovery directory: {self.temp_recovery_dir}")
            except Exception as e:
                logger.warning(f"Could not clean up temporary directory: {e}")
    
    def get_table_by_name(self, table_name: str):
        """
        Get table by name from ESE database.
        
        Args:
            table_name: Name of the table to retrieve
        
        Returns:
            Table object or None if not found
        """
        try:
            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses a different API
                try:
                    table = self.ese_db.table(table_name)
                    return table
                except Exception:
                    return None
                    
            elif ESEDB_LIBRARY == "pyesedb":
                num_tables = self.ese_db.get_number_of_tables()
                for i in range(num_tables):
                    table = self.ese_db.get_table(i)
                    if table.name == table_name:
                        return table
            else:
                for table in self.ese_db.tables:
                    if table.name == table_name:
                        return table
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting table {table_name}: {e}")
            return None
    
    def parse_id_map_table(self) -> Dict[int, Tuple[str, str]]:
        """
        Parse SruDbIdMapTable for ID resolution.
        
        Returns:
            Dictionary mapping ID -> (resolved_value, type)
        
        Requirements: 3.6, 3.7
        """
        id_map = {}
        
        try:
            table = self.get_table_by_name("SruDbIdMapTable")
            if not table:
                logger.warning("SruDbIdMapTable not found in database")
                return id_map
            
            logger.info("Parsing SruDbIdMapTable for ID resolution")
            
            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses records() iterator
                for record in table.records():
                    try:
                        id_index = record.get('IdIndex')
                        id_blob = record.get('IdBlob')
                        
                        if id_index and id_blob:
                            # Determine if it's an app or user ID based on blob content
                            if isinstance(id_blob, bytes):
                                blob_str = id_blob.decode('utf-16-le', errors='ignore').rstrip('\x00')
                            else:
                                blob_str = str(id_blob)
                            
                            if blob_str.startswith('S-1-'):
                                # It's a SID
                                id_map[id_index] = (blob_str, 'user')
                            else:
                                # It's an app path
                                id_map[id_index] = (blob_str, 'app')
                    
                    except Exception as e:
                        logger.debug(f"Error parsing ID map record: {e}")
                        continue
                        
            elif ESEDB_LIBRARY == "pyesedb":
                num_records = table.get_number_of_records()
                for i in range(num_records):
                    try:
                        record = table.get_record(i)
                        id_index = record.get_value_data(0)  # IdIndex column
                        id_blob = record.get_value_data(2)  # IdBlob column
                        
                        if id_index and id_blob:
                            # Determine if it's an app or user ID based on blob content
                            blob_str = id_blob.decode('utf-16-le', errors='ignore').rstrip('\x00')
                            
                            if blob_str.startswith('S-1-'):
                                # It's a SID
                                id_map[id_index] = (blob_str, 'user')
                            else:
                                # It's an app path
                                id_map[id_index] = (blob_str, 'app')
                    
                    except Exception as e:
                        logger.debug(f"Error parsing ID map record {i}: {e}")
                        continue
            
            logger.info(f"Loaded {len(id_map)} ID mappings from SruDbIdMapTable")
            
        except Exception as e:
            logger.error(f"Error parsing SruDbIdMapTable: {e}")
        
        return id_map

    def parse_application_resource_usage(self, resolver: 'IDResolver') -> List[Dict]:
        """
        Parse Application Resource Usage table from SRUM database.

        Extracts all resource usage metrics including CPU time, I/O operations,
        context switches, and resolves App IDs and User SIDs.

        Args:
            resolver: IDResolver instance for App ID and SID resolution

        Returns:
            List of dictionaries containing parsed application resource usage records

        Requirements: 3.2, 3.6, 3.7
        """
        records = []
        table_guid = SRUM_TABLE_GUIDS['APPLICATION_RESOURCE_USAGE']

        try:
            # Get table by GUID
            table = self.get_table_by_name(table_guid)
            if not table:
                logger.warning(f"Application Resource Usage table not found (GUID: {table_guid})")
                return records

            logger.info(f"Parsing Application Resource Usage table (GUID: {table_guid})")

            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses records() iterator with column names
                record_count = 0
                for record in table.records():
                    try:
                        # Extract timestamp
                        timestamp_raw = record.get('TimeStamp')
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID and User ID
                        app_id = record.get('AppId')
                        user_id = record.get('UserId')

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract resource usage metrics
                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'foreground_cycle_time': record.get('ForegroundCycleTime'),
                            'background_cycle_time': record.get('BackgroundCycleTime'),
                            'face_time': record.get('FaceTime'),
                            'foreground_context_switches': record.get('ForegroundContextSwitches'),
                            'background_context_switches': record.get('BackgroundContextSwitches'),
                            'foreground_bytes_read': record.get('ForegroundBytesRead'),
                            'foreground_bytes_written': record.get('ForegroundBytesWritten'),
                            'foreground_num_read_operations': record.get('ForegroundNumReadOperations'),
                            'foreground_num_write_operations': record.get('ForegroundNumWriteOperations'),
                            'foreground_number_of_flushes': record.get('ForegroundNumberOfFlushes'),
                            'background_bytes_read': record.get('BackgroundBytesRead'),
                            'background_bytes_written': record.get('BackgroundBytesWritten'),
                            'background_num_read_operations': record.get('BackgroundNumReadOperations'),
                            'background_num_write_operations': record.get('BackgroundNumWriteOperations'),
                            'background_number_of_flushes': record.get('BackgroundNumberOfFlushes')
                        }

                        records.append(parsed_record)
                        record_count += 1

                    except Exception as e:
                        logger.debug(f"Error parsing Application Resource Usage record: {e}")
                        continue
                
                logger.info(f"Found {record_count} records in Application Resource Usage table")
                
            elif ESEDB_LIBRARY == "pyesedb":
                num_records = table.get_number_of_records()
                logger.info(f"Found {num_records} records in Application Resource Usage table")

                for i in range(num_records):
                    try:
                        record = table.get_record(i)

                        # Extract timestamp (column 1)
                        timestamp_raw = record.get_value_data(1)
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID (column 2)
                        app_id = record.get_value_data(2)

                        # Extract User ID (column 3)
                        user_id = record.get_value_data(3)

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract resource usage metrics
                        foreground_cycle_time = record.get_value_data(4)  # ForegroundCycleTime
                        background_cycle_time = record.get_value_data(5)  # BackgroundCycleTime
                        face_time = record.get_value_data(6)  # FaceTime
                        foreground_context_switches = record.get_value_data(7)  # ForegroundContextSwitches
                        background_context_switches = record.get_value_data(8)  # BackgroundContextSwitches
                        foreground_bytes_read = record.get_value_data(9)  # ForegroundBytesRead
                        foreground_bytes_written = record.get_value_data(10)  # ForegroundBytesWritten
                        foreground_num_read_ops = record.get_value_data(11)  # ForegroundNumReadOperations
                        foreground_num_write_ops = record.get_value_data(12)  # ForegroundNumWriteOperations
                        foreground_num_flushes = record.get_value_data(13)  # ForegroundNumberOfFlushes
                        background_bytes_read = record.get_value_data(14)  # BackgroundBytesRead
                        background_bytes_written = record.get_value_data(15)  # BackgroundBytesWritten
                        background_num_read_ops = record.get_value_data(16)  # BackgroundNumReadOperations
                        background_num_write_ops = record.get_value_data(17)  # BackgroundNumWriteOperations
                        background_num_flushes = record.get_value_data(18)  # BackgroundNumberOfFlushes

                        # Create record dictionary
                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'foreground_cycle_time': foreground_cycle_time,
                            'background_cycle_time': background_cycle_time,
                            'face_time': face_time,
                            'foreground_context_switches': foreground_context_switches,
                            'background_context_switches': background_context_switches,
                            'foreground_bytes_read': foreground_bytes_read,
                            'foreground_bytes_written': foreground_bytes_written,
                            'foreground_num_read_operations': foreground_num_read_ops,
                            'foreground_num_write_operations': foreground_num_write_ops,
                            'foreground_number_of_flushes': foreground_num_flushes,
                            'background_bytes_read': background_bytes_read,
                            'background_bytes_written': background_bytes_written,
                            'background_num_read_operations': background_num_read_ops,
                            'background_num_write_operations': background_num_write_ops,
                            'background_number_of_flushes': background_num_flushes
                        }

                        records.append(parsed_record)

                    except Exception as e:
                        logger.debug(f"Error parsing Application Resource Usage record {i}: {e}")
                        continue

            logger.info(f"Successfully parsed {len(records)} Application Resource Usage records")

        except Exception as e:
            logger.error(f"Error parsing Application Resource Usage table: {e}")

        return records

    def parse_network_connectivity(self, resolver: 'IDResolver') -> List[Dict]:
        """
        Parse Network Connectivity table from SRUM database.

        Extracts network connectivity information including interface details,
        connection times, and resolves App IDs and User SIDs.

        Args:
            resolver: IDResolver instance for App ID and SID resolution

        Returns:
            List of dictionaries containing parsed network connectivity records

        Requirements: 3.3, 3.6, 3.7
        """
        records = []
        table_guid = SRUM_TABLE_GUIDS['NETWORK_CONNECTIVITY']

        try:
            # Get table by GUID
            table = self.get_table_by_name(table_guid)
            if not table:
                logger.warning(f"Network Connectivity table not found (GUID: {table_guid})")
                return records

            logger.info(f"Parsing Network Connectivity table (GUID: {table_guid})")

            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses records() iterator with column names
                record_count = 0
                for record in table.records():
                    try:
                        # Extract timestamp
                        timestamp_raw = record.get('TimeStamp')
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID and User ID
                        app_id = record.get('AppId')
                        user_id = record.get('UserId')

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract network connectivity metrics
                        connect_start_time_raw = record.get('ConnectStartTime')
                        connect_start_time = self._convert_filetime_to_datetime(connect_start_time_raw) if connect_start_time_raw else None

                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'interface_luid': record.get('InterfaceLuid'),
                            'l2_profile_id': record.get('L2ProfileId'),
                            'l2_profile_flags': record.get('L2ProfileFlags'),
                            'connected_time': record.get('ConnectedTime'),
                            'connect_start_time': format_forensic_timestamp(connect_start_time) if connect_start_time else None
                        }

                        records.append(parsed_record)
                        record_count += 1

                    except Exception as e:
                        logger.debug(f"Error parsing Network Connectivity record: {e}")
                        continue
                
                logger.info(f"Found {record_count} records in Network Connectivity table")
                
            elif ESEDB_LIBRARY == "pyesedb":
                num_records = table.get_number_of_records()
                logger.info(f"Found {num_records} records in Network Connectivity table")

                for i in range(num_records):
                    try:
                        record = table.get_record(i)

                        # Extract timestamp (column 1)
                        timestamp_raw = record.get_value_data(1)
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID (column 2)
                        app_id = record.get_value_data(2)

                        # Extract User ID (column 3)
                        user_id = record.get_value_data(3)

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract network connectivity metrics
                        interface_luid = record.get_value_data(4)  # InterfaceLuid
                        l2_profile_id = record.get_value_data(5)  # L2ProfileId
                        l2_profile_flags = record.get_value_data(6)  # L2ProfileFlags
                        connected_time = record.get_value_data(7)  # ConnectedTime
                        connect_start_time_raw = record.get_value_data(8)  # ConnectStartTime
                        connect_start_time = self._convert_filetime_to_datetime(connect_start_time_raw) if connect_start_time_raw else None

                        # Create record dictionary
                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'interface_luid': interface_luid,
                            'l2_profile_id': l2_profile_id,
                            'l2_profile_flags': l2_profile_flags,
                            'connected_time': connected_time,
                            'connect_start_time': format_forensic_timestamp(connect_start_time) if connect_start_time else None
                        }

                        records.append(parsed_record)

                    except Exception as e:
                        logger.debug(f"Error parsing Network Connectivity record {i}: {e}")
                        continue

            logger.info(f"Successfully parsed {len(records)} Network Connectivity records")

        except Exception as e:
            logger.error(f"Error parsing Network Connectivity table: {e}")

        return records

    def _convert_filetime_to_datetime(self, filetime):
        """
        Convert Windows FILETIME to Python datetime.
        
        This method matches the live SRUM parser's timestamp conversion for
        pyesedb/libesedb, but uses OLE Automation Date format for dissect.esedb.
        
        SRUM timestamps format by library:
        - dissect.esedb: OLE Automation Date (double, days since 1899-12-30)
        - pyesedb/libesedb: Standard FILETIME (100-ns intervals since 1601)
        
        Args:
            filetime: Timestamp value (integer, bytes, or types.int64)
                     For dissect: Raw bytes representing OLE Date (double)
                     For pyesedb/libesedb: Windows FILETIME integer
        
        Returns:
            datetime: Converted datetime or None if invalid
        """
        if filetime == 0 or filetime is None:
            return None
        
        try:
            # Convert to integer if needed
            if hasattr(filetime, '__int__'):
                # Handle types.int64 from dissect.cstruct
                filetime_int = int(filetime)
            elif isinstance(filetime, bytes):
                # Convert bytes to integer (little-endian)
                filetime_int = int.from_bytes(filetime, byteorder='little')
            elif isinstance(filetime, int):
                filetime_int = filetime
            else:
                logger.debug(f"Unknown timestamp type: {type(filetime)}")
                return None

            # Determine which library we're using and convert accordingly
            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb stores DateTime columns as OLE Automation Date
                # OLE Date is a double (8 bytes) representing days since 1899-12-30
                import struct
                
                # Convert integer to bytes, then interpret as double
                timestamp_bytes = filetime_int.to_bytes(8, byteorder='little')
                ole_date = struct.unpack('<d', timestamp_bytes)[0]
                
                # Convert OLE Date to datetime
                # OLE Automation Date epoch is December 30, 1899
                base_date = datetime.datetime(1899, 12, 30)
                return base_date + datetime.timedelta(days=ole_date)
            
            else:
                # pyesedb/libesedb use standard FILETIME format
                # FILETIME epoch is January 1, 1601
                # Convert 100-nanosecond intervals to seconds
                # This matches the live parser's conversion exactly
                timestamp = filetime_int / 10000000.0
                epoch = datetime.datetime(1601, 1, 1)
                return epoch + datetime.timedelta(seconds=timestamp)

        except Exception as e:
            logger.debug(f"Error converting FILETIME {filetime}: {e}")
            return None
    
    def _get_record_value(self, record, column_name_or_index, default=None):
        """
        Get a value from a record, handling both dissect.esedb and pyesedb APIs.
        
        Args:
            record: Record object (dissect or pyesedb)
            column_name_or_index: Column name (for dissect) or index (for pyesedb)
            default: Default value if column is null or not found
            
        Returns:
            Column value or default
        """
        try:
            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses column names
                return record.get(column_name_or_index, default)
            else:
                # pyesedb uses column indices
                return record.get_value_data(column_name_or_index) if hasattr(record, 'get_value_data') else default
        except Exception:
            return default

    def parse_network_data_usage(self, resolver: 'IDResolver') -> List[Dict]:
        """
        Parse Network Data Usage table from SRUM database.

        Extracts network data usage information including bytes sent/received,
        interface details, and resolves App IDs and User SIDs.

        Args:
            resolver: IDResolver instance for App ID and SID resolution

        Returns:
            List of dictionaries containing parsed network data usage records

        Requirements: 3.4, 3.6, 3.7
        """
        records = []
        table_guid = SRUM_TABLE_GUIDS['NETWORK_DATA_USAGE']

        try:
            # Get table by GUID
            table = self.get_table_by_name(table_guid)
            if not table:
                logger.warning(f"Network Data Usage table not found (GUID: {table_guid})")
                return records

            logger.info(f"Parsing Network Data Usage table (GUID: {table_guid})")

            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses records() iterator with column names
                record_count = 0
                for record in table.records():
                    try:
                        # Extract timestamp
                        timestamp_raw = record.get('TimeStamp')
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID and User ID
                        app_id = record.get('AppId')
                        user_id = record.get('UserId')

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'interface_luid': record.get('InterfaceLuid'),
                            'l2_profile_id': record.get('L2ProfileId'),
                            'bytes_sent': record.get('BytesSent'),
                            'bytes_received': record.get('BytesRecvd')
                        }

                        records.append(parsed_record)
                        record_count += 1

                    except Exception as e:
                        logger.debug(f"Error parsing Network Data Usage record: {e}")
                        continue
                
                logger.info(f"Found {record_count} records in Network Data Usage table")
                
            elif ESEDB_LIBRARY == "pyesedb":
                num_records = table.get_number_of_records()
                logger.info(f"Found {num_records} records in Network Data Usage table")

                for i in range(num_records):
                    try:
                        record = table.get_record(i)

                        # Extract timestamp (column 1)
                        timestamp_raw = record.get_value_data(1)
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID (column 2)
                        app_id = record.get_value_data(2)

                        # Extract User ID (column 3)
                        user_id = record.get_value_data(3)

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract network data usage metrics
                        interface_luid = record.get_value_data(4)  # InterfaceLuid
                        l2_profile_id = record.get_value_data(5)  # L2ProfileId
                        bytes_sent = record.get_value_data(6)  # BytesSent
                        bytes_received = record.get_value_data(7)  # BytesRecvd

                        # Create record dictionary
                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'interface_luid': interface_luid,
                            'l2_profile_id': l2_profile_id,
                            'bytes_sent': bytes_sent,
                            'bytes_received': bytes_received
                        }

                        records.append(parsed_record)

                    except Exception as e:
                        logger.debug(f"Error parsing Network Data Usage record {i}: {e}")
                        continue

            logger.info(f"Successfully parsed {len(records)} Network Data Usage records")

        except Exception as e:
            logger.error(f"Error parsing Network Data Usage table: {e}")

        return records

    def parse_energy_usage(self, resolver: 'IDResolver') -> List[Dict]:
        """
        Parse Energy Usage table from SRUM database.

        Extracts energy usage information including battery consumption, charge levels,
        and state transitions, and resolves App IDs and User SIDs.

        Args:
            resolver: IDResolver instance for App ID and SID resolution

        Returns:
            List of dictionaries containing parsed energy usage records

        Requirements: 3.5, 3.6, 3.7
        """
        records = []
        table_guid = SRUM_TABLE_GUIDS['ENERGY_USAGE']

        try:
            # Get table by GUID
            table = self.get_table_by_name(table_guid)
            if not table:
                logger.warning(f"Energy Usage table not found (GUID: {table_guid})")
                return records

            logger.info(f"Parsing Energy Usage table (GUID: {table_guid})")

            if ESEDB_LIBRARY == "dissect":
                # dissect.esedb uses records() iterator with column names
                record_count = 0
                for record in table.records():
                    try:
                        # Extract timestamp
                        timestamp_raw = record.get('TimeStamp')
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID and User ID
                        app_id = record.get('AppId')
                        user_id = record.get('UserId')

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract energy usage metrics
                        event_timestamp_raw = record.get('EventTimestamp')
                        event_timestamp = self._convert_filetime_to_datetime(event_timestamp_raw) if event_timestamp_raw else None

                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'event_timestamp': format_forensic_timestamp(event_timestamp) if event_timestamp else None,
                            'state_transition': record.get('StateTransition') if record.get('StateTransition') is not None else 0,
                            'charge_level': record.get('ChargeLevel') if record.get('ChargeLevel') is not None else 0,
                            'cycle_count': record.get('CycleCount') if record.get('CycleCount') is not None else 0
                        }

                        records.append(parsed_record)
                        record_count += 1

                    except Exception as e:
                        logger.debug(f"Error parsing Energy Usage record: {e}")
                        continue
                
                logger.info(f"Found {record_count} records in Energy Usage table")
                
            elif ESEDB_LIBRARY == "pyesedb":
                num_records = table.get_number_of_records()
                logger.info(f"Found {num_records} records in Energy Usage table")

                for i in range(num_records):
                    try:
                        record = table.get_record(i)

                        # Extract timestamp (column 1)
                        timestamp_raw = record.get_value_data(1)
                        timestamp = self._convert_filetime_to_datetime(timestamp_raw) if timestamp_raw else None
                        
                        # Skip records with NULL timestamps (required field)
                        if not timestamp:
                            continue

                        # Extract App ID (column 2)
                        app_id = record.get_value_data(2)

                        # Extract User ID (column 3)
                        user_id = record.get_value_data(3)

                        # Resolve App ID and User SID
                        app_name, app_path = resolver.resolve_app_id(app_id) if app_id else ("Unknown", "Unknown")
                        user_sid, user_name = resolver.resolve_sid(user_id) if user_id else ("Unknown", "Unknown")

                        # Extract energy usage metrics
                        event_timestamp_raw = record.get_value_data(4)  # EventTimestamp
                        event_timestamp = self._convert_filetime_to_datetime(event_timestamp_raw) if event_timestamp_raw else None

                        state_transition = record.get_value_data(5)  # StateTransition
                        charge_level = record.get_value_data(6)  # ChargeLevel
                        cycle_count = record.get_value_data(7)  # CycleCount

                        # Create record dictionary
                        parsed_record = {
                            'timestamp': format_forensic_timestamp(timestamp),
                            'app_name': app_name,
                            'app_path': app_path,
                            'user_sid': user_sid,
                            'user_name': user_name,
                            'event_timestamp': format_forensic_timestamp(event_timestamp) if event_timestamp else None,
                            'state_transition': state_transition if state_transition is not None else 0,
                            'charge_level': charge_level if charge_level is not None else 0,
                            'cycle_count': cycle_count if cycle_count is not None else 0
                        }

                        records.append(parsed_record)

                    except Exception as e:
                        logger.debug(f"Error parsing Energy Usage record {i}: {e}")
                        continue

            logger.info(f"Successfully parsed {len(records)} Energy Usage records")

        except Exception as e:
            logger.error(f"Error parsing Energy Usage table: {e}")

        return records





# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main(srudb_path: str = None, case_path: str = None, registry_hives: List[str] = None):
    """
    Main entry point for offline SRUM parsing.
    
    Parses a collected SRUDB.dat file and creates a SQLite database with
    identical schema to the live SRUM-Claw parser for forensic timeline analysis.
    
    Args:
        srudb_path (str): Path to SRUDB.dat file to parse
        case_path (str, optional): Path where output database should be created.
                                   If None, creates srum_data.db in current directory
        registry_hives (List[str], optional): List of registry hive paths for 
                                             enhanced SID resolution (SAM, SOFTWARE, etc.)
    
    Returns:
        dict: Parsing results with statistics and output database path
        
    Raises:
        SRUMFileAccessError: If SRUDB.dat cannot be accessed
        SRUMDatabaseCorruptError: If SRUDB.dat is corrupted or invalid
        SRUMLibraryNotAvailableError: If required ESE library is not available
    
    Requirements: 8.4, 8.6, 8.7
    """
    start_time = get_current_utc()
    
    logger.info("=" * 70)
    logger.info("Crow Eye - Offline SRUM Parser")
    logger.info("=" * 70)
    
    # Wrap entire parsing logic in try-except to return error dict on any failure
    try:
        # Check if ESE library is available
        if not ESEDB_AVAILABLE:
            error_msg = (
                f"\n{'='*70}\n"
                f"ESE DATABASE LIBRARY NOT AVAILABLE\n"
                f"{'='*70}\n"
                f"No ESE database library found. Please install one of:\n\n"
                f"RECOMMENDED (best for forensics and dirty databases):\n"
                f"  pip install dissect.esedb\n\n"
                f"ALTERNATIVES:\n"
                f"  pip install pyesedb\n"
                f"  pip install libesedb-python\n\n"
                f"For dirty state databases (common in forensics), dissect.esedb\n"
                f"is strongly recommended as it handles them much better.\n"
                f"{'='*70}\n"
            )
            logger.error(error_msg)
            return {
                'success': False,
                'records': 0,
                'error': 'ESE database library not available'
            }
        
        logger.info(f"Using ESE library: {ESEDB_LIBRARY}")
        
        # Validate input file
        if not srudb_path:
            return {
                'success': False,
                'records': 0,
                'error': 'SRUDB.dat path is required'
            }
        
        if not os.path.exists(srudb_path):
            return {
                'success': False,
                'records': 0,
                'error': f'SRUDB.dat not found at: {srudb_path}'
            }
        
        if not os.access(srudb_path, os.R_OK):
            return {
                'success': False,
                'records': 0,
                'error': f'Cannot read SRUDB.dat at: {srudb_path}'
            }
        
        logger.info(f"Input SRUDB.dat: {srudb_path}")
        
        # Create output database
        try:
            conn, cursor, output_db_path = create_database(case_path)
        except Exception as e:
            logger.error(f"Failed to create output database: {e}")
            return {
                'success': False,
                'records': 0,
                'error': f'Failed to create output database: {str(e)}'
            }
        
        logger.info(f"Output database: {output_db_path}")
        
        # Initialize statistics
        stats = {
            'total_records': 0,
            'app_usage_records': 0,
            'network_conn_records': 0,
            'network_data_records': 0,
            'energy_records': 0,
            'errors': 0
        }
    
        try:
            # Open ESE database
            parser = ESEDatabaseParser(srudb_path)
            parser.open_database()
            
            # Load ID map for resolution
            logger.info("Loading ID mappings...")
            id_map = parser.parse_id_map_table()
            
            # Create resolver with optional registry hives for enhanced SID resolution
            if registry_hives:
                logger.info(f"Loading {len(registry_hives)} registry hive(s) for enhanced SID resolution...")
            resolver = IDResolver(id_map, registry_hives=registry_hives)
            
            # Parse Application Resource Usage table
            logger.info("Parsing Application Resource Usage table...")
            app_usage_records = parser.parse_application_resource_usage(resolver)
            stats['app_usage_records'] = len(app_usage_records)
            stats['total_records'] += len(app_usage_records)
            
            # Insert Application Resource Usage records into database
            if app_usage_records:
                logger.info(f"Inserting {len(app_usage_records)} Application Resource Usage records into database...")
                for record in app_usage_records:
                    try:
                        cursor.execute("""
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
                        """, (
                            record['timestamp'],
                            record['app_name'],
                            record['app_path'],
                            record['user_sid'],
                            record['user_name'],
                            record['foreground_cycle_time'],
                            record['background_cycle_time'],
                            record['face_time'],
                            record['foreground_context_switches'],
                            record['background_context_switches'],
                            record['foreground_bytes_read'],
                            record['foreground_bytes_written'],
                            record['foreground_num_read_operations'],
                            record['foreground_num_write_operations'],
                            record['foreground_number_of_flushes'],
                            record['background_bytes_read'],
                            record['background_bytes_written'],
                            record['background_num_read_operations'],
                            record['background_num_write_operations'],
                            record['background_number_of_flushes']
                        ))
                    except Exception as e:
                        logger.error(f"Error inserting Application Resource Usage record: {e}")
                        stats['errors'] += 1
                
                conn.commit()
                logger.info("Application Resource Usage records inserted successfully")
            
            # Parse Network Connectivity table
            logger.info("Parsing Network Connectivity table...")
            network_conn_records = parser.parse_network_connectivity(resolver)
            stats['network_conn_records'] = len(network_conn_records)
            stats['total_records'] += len(network_conn_records)
            
            # Insert Network Connectivity records into database
            if network_conn_records:
                logger.info(f"Inserting {len(network_conn_records)} Network Connectivity records into database...")
                for record in network_conn_records:
                    try:
                        cursor.execute("""
                            INSERT INTO srum_network_connectivity (
                                timestamp, app_name, app_path, user_sid, user_name,
                                interface_luid, l2_profile_id, l2_profile_flags,
                                connected_time, connect_start_time
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record['timestamp'],
                            record['app_name'],
                            record['app_path'],
                            record['user_sid'],
                            record['user_name'],
                            record['interface_luid'],
                            record['l2_profile_id'],
                            record['l2_profile_flags'],
                            record['connected_time'],
                            record['connect_start_time']
                        ))
                    except Exception as e:
                        logger.error(f"Error inserting Network Connectivity record: {e}")
                        stats['errors'] += 1
                
                conn.commit()
                logger.info("Network Connectivity records inserted successfully")
            
            # Parse Network Data Usage table
            logger.info("Parsing Network Data Usage table...")
            network_data_records = parser.parse_network_data_usage(resolver)
            stats['network_data_records'] = len(network_data_records)
            stats['total_records'] += len(network_data_records)
            
            # Insert Network Data Usage records into database
            if network_data_records:
                logger.info(f"Inserting {len(network_data_records)} Network Data Usage records into database...")
                for record in network_data_records:
                    try:
                        cursor.execute("""
                            INSERT INTO srum_network_data_usage (
                                timestamp, app_name, app_path, user_sid, user_name,
                                interface_luid, l2_profile_id, bytes_sent, bytes_received
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record['timestamp'],
                            record['app_name'],
                            record['app_path'],
                            record['user_sid'],
                            record['user_name'],
                            record['interface_luid'],
                            record['l2_profile_id'],
                            record['bytes_sent'],
                            record['bytes_received']
                        ))
                    except Exception as e:
                        logger.error(f"Error inserting Network Data Usage record: {e}")
                        stats['errors'] += 1
                
                conn.commit()
                logger.info("Network Data Usage records inserted successfully")
            
            # Parse Energy Usage table
            logger.info("Parsing Energy Usage table...")
            energy_records = parser.parse_energy_usage(resolver)
            stats['energy_records'] = len(energy_records)
            stats['total_records'] += len(energy_records)
            
            # Insert Energy Usage records into database
            if energy_records:
                logger.info(f"Inserting {len(energy_records)} Energy Usage records into database...")
                for record in energy_records:
                    try:
                        cursor.execute("""
                            INSERT INTO srum_energy_usage (
                                timestamp, app_name, app_path, user_sid, user_name,
                                event_timestamp, state_transition, charge_level, cycle_count
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record['timestamp'],
                            record['app_name'],
                            record['app_path'],
                            record['user_sid'],
                            record['user_name'],
                            record['event_timestamp'],
                            record['state_transition'],
                            record['charge_level'],
                            record['cycle_count']
                        ))
                    except Exception as e:
                        logger.error(f"Error inserting Energy Usage record: {e}")
                        stats['errors'] += 1
                
                conn.commit()
                logger.info("Energy Usage records inserted successfully")
            
            logger.info("SRUM parsing completed successfully")
            
            # Calculate duration
            end_time = get_current_utc()
            duration = (end_time - start_time).total_seconds()
            
            # Insert metadata
            cursor.execute("""
                INSERT INTO srum_metadata 
                (parse_timestamp, srudb_path, total_records_parsed, parsing_duration_seconds, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (
                get_current_forensic_timestamp(),
                srudb_path,
                stats['total_records'],
                duration,
                f"Parsed with {ESEDB_LIBRARY}"
            ))
            
            conn.commit()
            
            # Print summary
            logger.info("=" * 70)
            logger.info("PARSING SUMMARY")
            logger.info("=" * 70)
            logger.info(f"  Total records parsed:     {stats['total_records']}")
            logger.info(f"  App usage records:        {stats['app_usage_records']}")
            logger.info(f"  Network conn records:     {stats['network_conn_records']}")
            logger.info(f"  Network data records:     {stats['network_data_records']}")
            logger.info(f"  Energy records:           {stats['energy_records']}")
            logger.info(f"  Errors encountered:       {stats['errors']}")
            logger.info(f"  Processing time:          {duration:.2f} seconds")
            logger.info("=" * 70)
            
            print(f"\nSRUM parsing completed successfully!")
            print(f"Database created at: {output_db_path}")
            
            return {
                'success': True,
                'records': stats.get('total_records', 0),
                'output_path': output_db_path
            }
            
        except Exception as e:
            logger.error(f"SRUM parsing failed: {e}")
            return {
                'success': False,
                'records': 0,
                'error': str(e)
            }
            
        finally:
            # Clean up
            if 'parser' in locals():
                parser.close_database()
            
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    
    except Exception as outer_e:
        # Catch any exceptions from validation or setup
        logger.error(f"SRUM parser initialization failed: {outer_e}")
        return {
            'success': False,
            'records': 0,
            'error': str(outer_e)
        }


if __name__ == "__main__":
    # Example usage for testing
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python offline_SRUM_Claw.py <srudb_path> [case_path] [registry_hive1] [registry_hive2] ...")
        print("\nExample:")
        print("  python offline_SRUM_Claw.py C:\\Evidence\\SRUDB.dat C:\\Cases\\Case001")
        sys.exit(1)
    
    srudb = sys.argv[1]
    case = sys.argv[2] if len(sys.argv) > 2 else None
    hives = sys.argv[3:] if len(sys.argv) > 3 else None
    
    try:
        result = main(srudb_path=srudb, case_path=case, registry_hives=hives)
        print(f"\nSuccess! Database created at: {result['output_path']}")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
