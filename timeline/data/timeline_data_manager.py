"""
Timeline Data Manager
=====================

This module provides database access and query functionality for the forensic timeline
visualization feature. It manages connections to multiple artifact databases, executes
time-range queries, and handles data caching.

The TimelineDataManager is responsible for:
- Managing database connections to all artifact databases
- Querying events within specified time ranges
- Finding earliest and latest timestamps across all databases
- Caching query results for performance
- Handling database errors gracefully

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import sqlite3
import os
import logging
import threading
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Import timestamp parser utility
from timeline.utils.timestamp_parser import TimestampParser
from timeline.data.timestamp_indexer import TimestampIndexer
from timeline.data.srum_app_resolver import SrumAppResolver
from timeline.utils.value_parser import parsable_num_adapter
from timeline.utils.error_handler import (
    ErrorHandler, DatabaseError, DataLoadError, 
    ErrorSeverity, create_recovery_options
)

# Configure logger
logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Exception raised when database connection fails."""
    pass


class ConnectionPoolEntry:
    """
    Represents a pooled database connection with metadata.
    
    Tracks connection usage, last access time, and thread ownership
    for proper connection management and cleanup.
    """
    
    def __init__(self, connection: sqlite3.Connection, artifact_type: str):
        """
        Initialize connection pool entry.
        
        Args:
            connection: SQLite database connection
            artifact_type: Type of artifact this connection is for
        """
        self.connection = connection
        self.artifact_type = artifact_type
        self.thread_id = threading.get_ident()
        self.created_at = time.time()
        self.last_used = time.time()
        self.use_count = 0
        self.is_valid = True
    
    def mark_used(self):
        """Mark connection as recently used."""
        self.last_used = time.time()
        self.use_count += 1
    
    def is_idle(self, timeout_seconds: float) -> bool:
        """
        Check if connection has been idle for longer than timeout.
        
        Args:
            timeout_seconds: Idle timeout in seconds
        
        Returns:
            bool: True if connection is idle beyond timeout
        """
        return (time.time() - self.last_used) > timeout_seconds
    
    def is_same_thread(self) -> bool:
        """
        Check if current thread matches the thread that created this connection.
        
        Returns:
            bool: True if same thread
        """
        return threading.get_ident() == self.thread_id
    
    def health_check(self) -> bool:
        """
        Perform health check on connection.
        
        Returns:
            bool: True if connection is healthy
        """
        try:
            self.connection.execute("SELECT 1")
            return True
        except sqlite3.Error:
            self.is_valid = False
            return False


class TimelineDataManager:
    """
    Manages database access and queries for timeline visualization.
    
    This class handles connections to multiple artifact databases and provides
    methods to query events within time ranges, find time bounds, and manage
    data caching for performance.
    """
    
    # Artifact type to database mapping
    # Maps artifact types to their actual database filenames in the case directory
    ARTIFACT_DB_MAPPING = {
        'Prefetch': 'prefetch_data.db',
        'LNK': 'LnkDB.db',  # Actual filename in case directory
        'Registry': 'registry_data.db',
        'BAM': 'registry_data.db',  # BAM data is in registry database
        'ShellBag': 'registry_data.db',  # ShellBag data is in registry database
        'SRUM': 'srum_data.db',
        'USN': 'USN_journal.db',  # Actual filename in case directory
        'MFT': 'mft_claw_analysis.db',  # Actual filename in case directory
    }
    
    # Alternative database names to check if primary name not found
    ARTIFACT_DB_ALTERNATIVES = {
        'MFT': ['MFT_data.db'],  # Support old naming convention
    }
    
    # Timestamp column mappings for each artifact type
    # Format: artifact_type -> [(table_name, timestamp_column, timestamp_type, description)]
    # Updated to match actual database schemas in case directory
    TIMESTAMP_MAPPINGS = {
        'Prefetch': [
            ('prefetch_data', 'last_executed', 'executed', 'Last execution time'),
            ('prefetch_data', 'created_on', 'created', 'File creation time'),
            ('prefetch_data', 'modified_on', 'modified', 'File modification time'),
            ('prefetch_data', 'accessed_on', 'accessed', 'File access time'),
        ],
        'LNK': [
            ('LNK_Files', 'Time_Creation', 'created'),
            ('LNK_Files', 'Time_Modification', 'modified'),
            ('LNK_Files', 'Time_Access', 'accessed'),
            ('Automatic_JumpLists', 'Time_Creation', 'created'),
            ('Automatic_JumpLists', 'Time_Modification', 'modified'),
            ('Automatic_JumpLists', 'Time_Access', 'accessed'),
            ('Custom_JumpLists', 'Time_Creation', 'created'),
            ('Custom_JumpLists', 'Time_Modification', 'modified'),
            ('Custom_JumpLists', 'Time_Access', 'accessed'),
        ],
        'Registry': [
            ('UserAssist', 'last_execution', 'executed'),
            ('MUICache', 'timestamp', 'various'),
            ('InstalledSoftware', 'install_date', 'installed'),
            ('ComputerNameInfo', 'installation_date', 'installed'),
            ('Auto', 'last_install_time', 'installed'),
            ('Auto', 'scheduled_install_time', 'created'),
            ('WindowsUpdateInfo', 'last_check_time', 'accessed'),
            ('WindowsUpdateInfo', 'last_install_time', 'installed'),
            ('WindowsUpdateInfo', 'scheduled_install_time', 'created'),
            ('ShutdownInfo', 'shutdown_time', 'executed'),
            ('WordWheelQuery', 'access_date', 'accessed'),
            ('RunMRU', 'access_date', 'accessed'),
            ('Network_list', 'connection_date', 'accessed'),
            ('NetworkListProfiles', 'timestamp', 'various'),
            ('OpenSaveMRU', 'access_date', 'accessed'),
            ('LastSaveMRU', 'access_date', 'accessed'),
            ('NetworkInterfacesInfo', 'timestamp', 'various'),
        ],
        'DAM': [
            ('DAM', 'last_execution', 'executed'),
        ],
        'USBStorageDevices': [
            ('USBStorageDevices', 'first_connected', 'installed'),
            ('USBStorageDevices', 'last_connected', 'accessed'),
            ('USBStorageDevices', 'last_removed', 'deleted'),
        ],
        'BAM': [
            ('BAM', 'last_execution', 'executed'),
        ],
        'Amcache': [
            ('InventoryApplication', 'install_date', 'installed', 'Application install date'),
            ('InventoryApplicationFile', 'link_date', 'linked', 'Application file link date'),
            ('InventoryDriverBinary', 'driver_last_write_time', 'modified', 'Driver last write time'),
            ('InventoryDriverBinary', 'driver_time_stamp', 'created', 'Driver timestamp'),
        ],
        'Shimcache': [
            ('shimcache_entries', 'last_modified', 'modified', 'Shimcache last modified time'),
        ],
        'RecycleBin': [
            ('recycle_bin_entries', 'deletion_time', 'deleted', 'File deletion time'),
        ],
        'Shellbags': [
            ('Shellbags', 'created_date', 'created'),
            ('Shellbags', 'modified_date', 'modified'),
            ('Shellbags', 'accessed_date', 'accessed'),
        ],
        'SRUM': [
            ('srum_application_usage', 'timestamp', 'various'),
            ('srum_network_connectivity', 'timestamp', 'various'),
            ('srum_network_data_usage', 'timestamp', 'various'),
            ('srum_energy_usage', 'timestamp', 'various'),
        ],
        'USN': [
            ('journal_events', 'timestamp', 'various'),
        ],
        'MFT': [
            ('mft_records', 'created_time', 'created'),
            ('mft_records', 'modified_time', 'modified'),
            ('mft_records', 'accessed_time', 'accessed'),
            ('mft_records', 'mft_modified_time', 'mft_modified'),
        ],
    }
    
    def __init__(self, case_paths: Dict[str, str], error_handler: Optional[ErrorHandler] = None):
        """
        Initialize TimelineDataManager with case paths.
        
        Args:
            case_paths: Dictionary containing paths to case directories and databases
                       Expected keys: 'case_root', 'artifacts_dir', and individual db paths
            error_handler: Optional ErrorHandler instance for centralized error handling
        
        Raises:
            ValueError: If case_paths is invalid or missing required keys
        """
        if not case_paths or 'case_root' not in case_paths:
            raise ValueError("case_paths must contain 'case_root' key")
        
        self.case_paths = case_paths
        self.case_root = case_paths['case_root']
        self.artifacts_dir = case_paths.get('artifacts_dir', os.path.join(self.case_root, 'artifacts'))
        self.timeline_dir = case_paths.get('timeline_dir', os.path.join(self.case_root, 'timeline'))
        
        # Error handler
        self.error_handler = error_handler
        
        # Connection pool with metadata
        # Key: (thread_id, artifact_type) -> ConnectionPoolEntry
        self._connection_pool: Dict[Tuple[int, str], ConnectionPoolEntry] = {}
        self._pool_lock = threading.Lock()
        
        # Connection pool configuration
        self._idle_timeout = 300.0  # 5 minutes idle timeout
        self._max_connections_per_type = 3  # Max connections per artifact type
        self._health_check_interval = 60.0  # Health check every 60 seconds
        self._last_cleanup = time.time()
        self._cleanup_interval = 30.0  # Cleanup idle connections every 30 seconds
        
        # Connection statistics
        self._connection_stats = {
            'total_created': 0,
            'total_closed': 0,
            'total_reused': 0,
            'total_health_checks': 0,
            'total_health_failures': 0,
            'idle_timeouts': 0
        }
        
        # Query results cache
        self._cache = {}
        
        # Available artifact types (databases that exist)
        self._available_artifacts = []
        
        # Initialize timestamp indexer
        try:
            self.timestamp_indexer = TimestampIndexer(self.artifacts_dir, self.timeline_dir)
        except Exception as e:
            logger.error(f"Failed to initialize timestamp indexer: {e}")
            if self.error_handler:
                self.error_handler.handle_error(e, "initializing timestamp indexer", show_dialog=False)
            # Continue without indexer - queries will be slower but still work
            self.timestamp_indexer = None
        
        # Initialize SRUM app resolver
        try:
            self.srum_resolver = SrumAppResolver()
        except Exception as e:
            logger.error(f"Failed to initialize SRUM resolver: {e}")
            if self.error_handler:
                self.error_handler.handle_error(e, "initializing SRUM resolver", show_dialog=False)
            # Continue without resolver - SRUM will show IDs instead of names
            self.srum_resolver = None
        
        # Initialize available artifacts
        try:
            self._detect_available_artifacts()
        except Exception as e:
            logger.error(f"Failed to detect available artifacts: {e}")
            if self.error_handler:
                self.error_handler.handle_error(e, "detecting available artifacts", show_dialog=False)
            # Continue with empty artifact list
            self._available_artifacts = []
        
        logger.info(f"TimelineDataManager initialized for case: {self.case_root}")
        logger.info(f"Available artifact types: {', '.join(self._available_artifacts)}")
    
    def _detect_available_artifacts(self):
        """
        Detect which artifact databases are available in the case directory.
        
        Populates the _available_artifacts list with artifact types that have
        existing database files. Checks alternative database names if primary not found.
        """
        self._available_artifacts = []
        self._unavailable_artifacts = []
        
        for artifact_type, db_filename in self.ARTIFACT_DB_MAPPING.items():
            db_path = os.path.join(self.artifacts_dir, db_filename)
            found = False
            
            # Check primary database name
            if os.path.exists(db_path) and os.path.isfile(db_path):
                # Check if database is not empty
                file_size = os.path.getsize(db_path)
                if file_size > 0:
                    self._available_artifacts.append(artifact_type)
                    logger.debug(f"Found database for {artifact_type}: {db_path} ({file_size:,} bytes)")
                    found = True
                else:
                    self._unavailable_artifacts.append((artifact_type, 'empty'))
                    logger.warning(f"Database for {artifact_type} is empty: {db_path}")
                    found = True
            
            # If primary not found, check alternatives
            if not found and artifact_type in self.ARTIFACT_DB_ALTERNATIVES:
                for alt_filename in self.ARTIFACT_DB_ALTERNATIVES[artifact_type]:
                    alt_path = os.path.join(self.artifacts_dir, alt_filename)
                    if os.path.exists(alt_path) and os.path.isfile(alt_path):
                        file_size = os.path.getsize(alt_path)
                        if file_size > 0:
                            # Update mapping to use alternative name
                            self.ARTIFACT_DB_MAPPING[artifact_type] = alt_filename
                            self._available_artifacts.append(artifact_type)
                            logger.debug(f"Found alternative database for {artifact_type}: {alt_path} ({file_size:,} bytes)")
                            found = True
                            break
                        else:
                            self._unavailable_artifacts.append((artifact_type, 'empty'))
                            logger.warning(f"Alternative database for {artifact_type} is empty: {alt_path}")
                            found = True
                            break
            
            if not found:
                self._unavailable_artifacts.append((artifact_type, 'missing'))
                logger.warning(f"Database not found for {artifact_type}: {db_path}")
    
    def get_available_artifacts(self) -> List[str]:
        """
        Get list of available artifact types.
        
        Returns:
            List[str]: List of artifact type names that have available databases
        """
        return self._available_artifacts.copy()
    
    def get_unavailable_artifacts(self) -> List[Tuple[str, str]]:
        """
        Get list of unavailable artifact types with reasons.
        
        Returns:
            List[Tuple[str, str]]: List of (artifact_type, reason) tuples
                                   where reason is 'missing' or 'empty'
        """
        return self._unavailable_artifacts.copy()
    
    def _get_connection(self, artifact_type: str) -> Optional[sqlite3.Connection]:
        """
        Get or create database connection for an artifact type with connection pooling.
        
        This method implements connection pooling with:
        - Thread-safe connection management (one connection per thread)
        - Automatic health checks
        - Idle connection cleanup
        - Connection reuse statistics
        
        Args:
            artifact_type: Type of artifact (e.g., 'Prefetch', 'LNK')
        
        Returns:
            sqlite3.Connection: Database connection, or None if database doesn't exist
        
        Raises:
            DatabaseConnectionError: If connection fails
        """
        # Check if artifact type is available
        if artifact_type not in self._available_artifacts:
            logger.warning(f"Artifact type not available: {artifact_type}")
            return None
        
        # Cleanup idle connections periodically
        self._cleanup_idle_connections()
        
        thread_id = threading.get_ident()
        pool_key = (thread_id, artifact_type)
        
        with self._pool_lock:
            # Check if we have a valid pooled connection for this thread
            if pool_key in self._connection_pool:
                pool_entry = self._connection_pool[pool_key]
                
                # Perform health check
                if pool_entry.health_check():
                    # Connection is healthy, reuse it
                    pool_entry.mark_used()
                    self._connection_stats['total_reused'] += 1
                    # logger.debug(f"Reusing connection for {artifact_type} (thread {thread_id})")
                    return pool_entry.connection
                else:
                    # Connection failed health check
                    logger.warning(f"Connection for {artifact_type} failed health check, creating new connection")
                    self._connection_stats['total_health_failures'] += 1
                    try:
                        pool_entry.connection.close()
                        self._connection_stats['total_closed'] += 1
                    except Exception as e:
                        logger.debug(f"Error closing connection for {artifact_type}: {e}")
                    del self._connection_pool[pool_key]
        
        # Get database path
        db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type)
        if not db_filename:
            logger.error(f"Unknown artifact type: {artifact_type}")
            return None
        
        db_path = os.path.join(self.artifacts_dir, db_filename)
        
        # Verify database file exists and is readable
        if not os.path.exists(db_path):
            error_msg = f"Database file not found: {db_path}"
            logger.error(error_msg)
            if self.error_handler:
                self.error_handler.handle_database_error(
                    FileNotFoundError(error_msg),
                    db_path,
                    f"connecting to {artifact_type} database",
                    show_dialog=False
                )
            return None
        
        if not os.access(db_path, os.R_OK):
            error_msg = f"Database file not readable: {db_path}"
            logger.error(error_msg)
            if self.error_handler:
                self.error_handler.handle_database_error(
                    PermissionError(error_msg),
                    db_path,
                    f"connecting to {artifact_type} database",
                    show_dialog=False
                )
            return None
        
        # Create new connection with timeout and error handling
        try:
            # BUG FIX #1: Removed check_same_thread=False for thread safety
            # SQLite connections must only be used in the thread that created them
            # to prevent database corruption
            conn = sqlite3.connect(
                db_path,
                timeout=30.0  # 30 second timeout
            )
            
            # Register the dynamic value parser as a custom SQLite function
            conn.create_function("PARSABLE_NUM", 1, parsable_num_adapter)
            
            conn.row_factory = sqlite3.Row  # Enable column access by name
            
            # Test connection
            conn.execute("SELECT 1")
            
            # Add to connection pool
            with self._pool_lock:
                pool_entry = ConnectionPoolEntry(conn, artifact_type)
                pool_entry.mark_used()
                self._connection_pool[pool_key] = pool_entry
                self._connection_stats['total_created'] += 1
            
            logger.debug(f"Created new database connection for {artifact_type} (thread {thread_id})")
            return conn
        
        except sqlite3.Error as e:
            from timeline.utils.error_handler import create_database_error_with_guidance
            
            logger.error(f"Failed to connect to database for {artifact_type}: {e}")
            
            # Create detailed error with guidance
            db_error = create_database_error_with_guidance(
                f"connecting to {artifact_type} database",
                db_path,
                e
            )
            
            if self.error_handler:
                self.error_handler.handle_error(
                    db_error,
                    f"connecting to {artifact_type} database",
                    show_dialog=False
                )
            
            raise DatabaseConnectionError(f"{db_error.message}: {e}")
        
        except Exception as e:
            from timeline.utils.error_handler import create_database_error_with_guidance
            
            logger.error(f"Unexpected error connecting to database for {artifact_type}: {e}")
            
            # Create detailed error with guidance
            db_error = create_database_error_with_guidance(
                f"connecting to {artifact_type} database",
                db_path,
                e
            )
            
            if self.error_handler:
                self.error_handler.handle_error(
                    db_error,
                    f"connecting to {artifact_type} database",
                    show_dialog=False
                )
            
            raise DatabaseConnectionError(f"{db_error.message}: {e}")
    
    def _cleanup_idle_connections(self):
        """
        Clean up idle database connections that have exceeded timeout.
        
        This method is called periodically to close connections that haven't
        been used recently, freeing up resources.
        """
        current_time = time.time()
        
        # Only cleanup if enough time has passed since last cleanup
        if (current_time - self._last_cleanup) < self._cleanup_interval:
            return
        
        self._last_cleanup = current_time
        
        with self._pool_lock:
            idle_keys = []
            
            # Find idle connections
            for key, pool_entry in self._connection_pool.items():
                if pool_entry.is_idle(self._idle_timeout):
                    idle_keys.append(key)
            
            # Close and remove idle connections
            for key in idle_keys:
                pool_entry = self._connection_pool[key]
                
                # Only close if it's the current thread (SQLite requirement)
                # If it's another thread, we can't close it safely here
                # But we can remove it from the pool and let GC handle it eventually
                if pool_entry.is_same_thread():
                    try:
                        pool_entry.connection.close()
                        self._connection_stats['total_closed'] += 1
                        self._connection_stats['idle_timeouts'] += 1
                        logger.debug(f"Closed idle connection for {pool_entry.artifact_type} (idle for {current_time - pool_entry.last_used:.1f}s)")
                    except Exception as e:
                        logger.debug(f"Error closing idle connection: {e}")
                else:
                    logger.debug(f"Dropping idle connection for {pool_entry.artifact_type} from another thread (GC will close)")
                
                del self._connection_pool[key]
    
    def perform_health_checks(self) -> Dict[str, bool]:
        """
        Perform health checks on all pooled connections for the CURRENT thread.
        
        Returns:
            Dict[str, bool]: Dictionary mapping artifact types to health status
        """
        health_status = {}
        thread_id = threading.get_ident()
        
        with self._pool_lock:
            # Only check connections for the current thread
            keys_to_check = [k for k in self._connection_pool.keys() if k[0] == thread_id]
            
            for key in keys_to_check:
                pool_entry = self._connection_pool[key]
                artifact_type = key[1]
                
                self._connection_stats['total_health_checks'] += 1
                is_healthy = pool_entry.health_check()
                health_status[artifact_type] = is_healthy
                
                if not is_healthy:
                    # Remove unhealthy connection
                    logger.warning(f"Removing unhealthy connection for {artifact_type}")
                    self._connection_stats['total_health_failures'] += 1
                    try:
                        pool_entry.connection.close()
                        self._connection_stats['total_closed'] += 1
                    except Exception as e:
                        logger.debug(f"Error closing unhealthy connection for {artifact_type}: {e}")
                    del self._connection_pool[key]
        
        return health_status
    
    def cleanup_thread_connections(self, thread_id: Optional[int] = None):
        """
        Close and remove all connections belonging to a specific thread.
        
        This should be called when a worker thread finishes to prevent
        connection leaks in the pool.
        
        Args:
            thread_id: ID of the thread to cleanup (defaults to current thread)
        """
        if thread_id is None:
            thread_id = threading.get_ident()
            
        with self._pool_lock:
            # Find keys to remove
            keys_to_remove = []
            for key, entry in self._connection_pool.items():
                if key[0] == thread_id:
                    keys_to_remove.append(key)
            
            # Close and remove
            for key in keys_to_remove:
                entry = self._connection_pool.pop(key)
                try:
                    entry.connection.close()
                    logger.debug(f"Closed connection for {key[1]} (thread {thread_id})")
                except Exception as e:
                    logger.warning(f"Error closing connection for {key[1]}: {e}")
                    
            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} connections for thread {thread_id}")

    def get_connection_stats(self) -> Dict:
        """
        Get statistics about the connection pool.
        
        Returns:
            Dict: Pool statistics
        """
        with self._pool_lock:
            stats = self._connection_stats.copy()
            stats['active_connections'] = len(self._connection_pool)
            stats['unique_threads'] = len(set(k[0] for k in self._connection_pool.keys()))
            stats['unique_artifacts'] = len(set(k[1] for k in self._connection_pool.keys()))
            
            # Add detailed connection info
            stats['connections'] = [
                {
                    'thread_id': thread_id,
                    'artifact_type': artifact_type,
                    'use_count': entry.use_count,
                    'age_seconds': time.time() - entry.created_at,
                    'idle_seconds': time.time() - entry.last_used
                }
                for (thread_id, artifact_type), entry in self._connection_pool.items()
            ]
            
            return stats
    
    def set_idle_timeout(self, timeout_seconds: float):
        """
        Set the idle timeout for connection pooling.
        
        Args:
            timeout_seconds: Timeout in seconds (default: 300 = 5 minutes)
        """
        self._idle_timeout = max(60.0, timeout_seconds)  # Minimum 60 seconds
        logger.info(f"Connection idle timeout set to {self._idle_timeout} seconds")
    
    def set_cleanup_interval(self, interval_seconds: float):
        """
        Set the cleanup interval for idle connections.
        
        Args:
            interval_seconds: Interval in seconds (default: 30)
        """
        self._cleanup_interval = max(10.0, interval_seconds)  # Minimum 10 seconds
        logger.info(f"Connection cleanup interval set to {self._cleanup_interval} seconds")
    
    def get_all_time_bounds(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Find earliest and latest timestamps across all available databases.
        
        This method queries all available artifact databases to find the absolute
        earliest and latest timestamps, which defines the full time range of the case.
        
        Filters out unrealistic timestamps (before year 2000) which are often artifacts
        of uninitialized or corrupted data.
        
        Returns:
            Tuple[Optional[datetime], Optional[datetime]]: (earliest, latest) timestamps,
                                                           or (None, None) if no timestamps found
        """
        all_timestamps = []
        
        # Define minimum realistic timestamp (year 2000)
        # Timestamps before this are likely corrupted/uninitialized data
        MIN_REALISTIC_DATE = datetime(2000, 1, 1)
        
        for artifact_type in self._available_artifacts:
            try:
                bounds = self._get_artifact_time_bounds(artifact_type)
                if bounds[0] and bounds[1]:
                    # Filter out unrealistic timestamps
                    if bounds[0] >= MIN_REALISTIC_DATE:
                        all_timestamps.append(bounds[0])
                    if bounds[1] >= MIN_REALISTIC_DATE:
                        all_timestamps.append(bounds[1])
            
            except Exception as e:
                logger.warning(f"Failed to get time bounds for {artifact_type}: {e}")
                continue
        
        if not all_timestamps:
            logger.warning("No timestamps found in any database")
            return (None, None)
        
        earliest = min(all_timestamps)
        latest = max(all_timestamps)
        
        logger.info(f"Time bounds (filtered): {earliest} to {latest}")
        return (earliest, latest)
    
    def _get_artifact_time_bounds(self, artifact_type: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Get earliest and latest timestamps for a specific artifact type.
        
        Args:
            artifact_type: Type of artifact (e.g., 'Prefetch', 'LNK')
        
        Returns:
            Tuple[Optional[datetime], Optional[datetime]]: (earliest, latest) timestamps
        """
        conn = self._get_connection(artifact_type)
        if not conn:
            return (None, None)
        
        timestamp_mappings = self.TIMESTAMP_MAPPINGS.get(artifact_type, [])
        if not timestamp_mappings:
            logger.warning(f"No timestamp mappings defined for {artifact_type}")
            return (None, None)
        
        all_timestamps = []
        cursor = conn.cursor()
        
        for table_name, timestamp_column, *_ in timestamp_mappings:
            try:
                # Query min and max timestamps from this table/column
                query = f"""
                    SELECT MIN({timestamp_column}) as min_ts, MAX({timestamp_column}) as max_ts
                    FROM {table_name}
                    WHERE {timestamp_column} IS NOT NULL
                """
                
                cursor.execute(query)
                row = cursor.fetchone()
                
                if row and row['min_ts'] and row['max_ts']:
                    min_ts = TimestampParser.parse_timestamp(row['min_ts'])
                    max_ts = TimestampParser.parse_timestamp(row['max_ts'])
                    
                    if min_ts:
                        all_timestamps.append(min_ts)
                    if max_ts:
                        all_timestamps.append(max_ts)
            
            except sqlite3.Error as e:
                logger.debug(f"Failed to query {table_name}.{timestamp_column}: {e}")
                continue
        
        if not all_timestamps:
            return (None, None)
        
        return (min(all_timestamps), max(all_timestamps))
    
    def query_time_range(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        artifact_types: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Query events within a specified time range.
        
        This method queries one or more artifact databases for events that fall
        within the specified time range. If no time range is specified, all events
        are returned.
        
        Args:
            start_time: Start of time range (inclusive), or None for no lower bound
            end_time: End of time range (inclusive), or None for no upper bound
            artifact_types: List of artifact types to query, or None for all available
        
        Returns:
            List[Dict]: List of event dictionaries with standardized structure
        """
        # Default to all available artifacts if not specified
        if artifact_types is None:
            artifact_types = self._available_artifacts
        
        # Filter to only available artifacts
        artifact_types = [at for at in artifact_types if at in self._available_artifacts]
        
        if not artifact_types:
            logger.warning("No valid artifact types specified for query")
            return []
        
        # Query all specified artifact types and merge results
        all_events = []
        failed_artifacts = []
        
        for artifact_type in artifact_types:
            try:
                events = self._query_artifact_time_range(artifact_type, start_time, end_time)
                all_events.extend(events)
                logger.debug(f"Queried {len(events)} events from {artifact_type}")
            
            except DatabaseConnectionError as e:
                from timeline.utils.error_handler import create_database_error_with_guidance
                
                # Database connection failed - log and track
                logger.error(f"Database connection failed for {artifact_type}: {e}")
                failed_artifacts.append((artifact_type, "connection failed"))
                
                if self.error_handler:
                    db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type, "unknown")
                    db_path = os.path.join(self.artifacts_dir, db_filename)
                    
                    # Create detailed error with guidance
                    db_error = create_database_error_with_guidance(
                        f"querying {artifact_type} database",
                        db_path,
                        e
                    )
                    
                    self.error_handler.handle_error(
                        db_error,
                        f"querying {artifact_type} database",
                        show_dialog=False
                    )
                continue
            
            except sqlite3.Error as e:
                from timeline.utils.error_handler import create_query_error_with_guidance
                
                # SQL error - log and track
                logger.error(f"SQL error querying {artifact_type}: {e}")
                failed_artifacts.append((artifact_type, "query failed"))
                
                if self.error_handler:
                    db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type, "unknown")
                    db_path = os.path.join(self.artifacts_dir, db_filename)
                    
                    # Create detailed error with guidance
                    db_error = create_query_error_with_guidance(
                        artifact_type,
                        db_path,
                        e
                    )
                    
                    self.error_handler.handle_error(
                        db_error,
                        f"querying {artifact_type} events",
                        show_dialog=False
                    )
                continue
            
            except Exception as e:
                from timeline.utils.error_handler import create_database_error_with_guidance
                
                # Unexpected error - log and track
                logger.error(f"Unexpected error querying {artifact_type}: {e}")
                failed_artifacts.append((artifact_type, "unexpected error"))
                
                if self.error_handler:
                    db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type, "unknown")
                    db_path = os.path.join(self.artifacts_dir, db_filename)
                    
                    # Create detailed error with guidance
                    db_error = create_database_error_with_guidance(
                        f"querying {artifact_type} database",
                        db_path,
                        e
                    )
                    
                    self.error_handler.handle_error(
                        db_error,
                        f"querying {artifact_type} database",
                        show_dialog=False
                    )
                continue
        
        # Log summary of failures
        if failed_artifacts:
            logger.warning(f"Failed to query {len(failed_artifacts)} artifact types: {failed_artifacts}")
        
        # Sort events by timestamp
        try:
            all_events.sort(key=lambda e: e['timestamp'])
        except Exception as e:
            logger.error(f"Failed to sort events: {e}")
            # Continue with unsorted events rather than failing completely
        
        logger.info(f"Queried total of {len(all_events)} events from {len(artifact_types) - len(failed_artifacts)}/{len(artifact_types)} artifact types")
        return all_events
    
    def _query_artifact_time_range(
        self,
        artifact_type: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """
        Query a specific artifact type within time range.
        
        Args:
            artifact_type: Type of artifact to query
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            max_events: Maximum number of events to return (None for unlimited)
        
        Returns:
            List[Dict]: List of event dictionaries
        """
        # Route to specific query method based on artifact type
        query_methods = {
            'Prefetch': self._query_prefetch_time_range,
            'LNK': self._query_lnk_time_range,
            'Registry': self._query_registry_time_range,
            'BAM': self._query_bam_time_range,
            'ShellBag': self._query_shellbag_time_range,
            'SRUM': self._query_srum_time_range,
            'USN': self._query_usn_time_range,
            'MFT': self._query_mft_time_range,
        }
        
        query_method = query_methods.get(artifact_type)
        if query_method:
            return query_method(start_time, end_time, max_events)
        else:
            logger.warning(f"No query method defined for artifact type: {artifact_type}")
            return []
    
    def _query_prefetch_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """
        Query Prefetch artifacts within time range.
        
        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            max_events: Maximum number of events to return (None for unlimited)
        
        Returns:
            List[Dict]: List of Prefetch event dictionaries
        """
        conn = self._get_connection('Prefetch')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        try:
            # Build query with time range filters on ALL timestamp columns
            query = """
                SELECT rowid, *
                FROM prefetch_data
                WHERE (last_executed IS NOT NULL)
            """
            
            params = []
            if start_time and end_time:
                query += """ AND (
                    (last_executed BETWEEN ? AND ?) OR
                    (created_on BETWEEN ? AND ?) OR
                    (modified_on BETWEEN ? AND ?) OR
                    (accessed_on BETWEEN ? AND ?)
                )"""
                s, e = start_time.isoformat(), end_time.isoformat()
                params.extend([s, e, s, e, s, e, s, e])
            elif start_time:
                query += " AND (last_executed >= ? OR created_on >= ? OR modified_on >= ? OR accessed_on >= ?)"
                s = start_time.isoformat()
                params.extend([s, s, s, s])
            elif end_time:
                query += " AND (last_executed <= ? OR created_on <= ? OR modified_on <= ? OR accessed_on <= ?)"
                e = end_time.isoformat()
                params.extend([e, e, e, e])
            
            query += " ORDER BY last_executed ASC"
            
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Helper to check if timestamp is in range
            def is_in_range(ts_dt):
                if not ts_dt: return False
                if start_time and ts_dt < start_time: return False
                if end_time and ts_dt > end_time: return False
                return True

            for row in rows:
                # Emit events for all in-range timestamps
                ts_map = [
                    ('last_executed', 'executed'),
                    ('created_on',    'created'),
                    ('modified_on',   'modified'),
                    ('accessed_on',   'accessed')
                ]
                
                rid = row['rowid']
                
                for col, sub_type in ts_map:
                    raw_ts = row[col]
                    if not raw_ts: continue
                    ts = TimestampParser.parse_timestamp(raw_ts)
                    if ts and is_in_range(ts):
                        events.append({
                            'id': f"prefetch_{rid}_{sub_type}_{raw_ts}",
                            'timestamp': ts,
                            'subType': sub_type,
                            'artifact_type': 'Prefetch',
                            'source_db': 'prefetch_data.db',
                            'source_table': 'prefetch_data',
                            'source_row_id': str(rid),
                            'display_name': row['executable_name'] or 'Unknown',
                            'full_path': row['filename'] or '',
                            'details': {k: row[k] for k in row.keys()},
                            'annotation': None
                        })
                
                # Also process historical run_times if present
                try:
                    import json
                    rt_json = row['run_times']
                    if rt_json:
                        run_times = json.loads(rt_json)
                        if isinstance(run_times, list):
                            for rt_str in run_times:
                                if not rt_str: continue
                                rt_ts = TimestampParser.parse_timestamp(rt_str)
                                if rt_ts and is_in_range(rt_ts):
                                    events.append({
                                        'id': f"prefetch_{rid}_run_time_{rt_str}",
                                        'timestamp': rt_ts,
                                        'subType': 'run_time',
                                        'artifact_type': 'Prefetch',
                                        'source_db': 'prefetch_data.db',
                                        'source_table': 'prefetch_data',
                                        'source_row_id': str(rid),
                                        'display_name': row['executable_name'] or 'Unknown',
                                        'full_path': row['filename'] or '',
                                        'details': {k: row[k] for k in row.keys()},
                                        'annotation': None
                                    })
                except Exception as e:
                    logger.debug(f"Failed to parse run_times for prefetch row {rid}: {e}")
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query Prefetch data: {e}")
        
        return events
    
    def _query_lnk_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query LNK artifacts within time range."""
        conn = self._get_connection('LNK')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        try:
            # Query all three LNK tables: LNK_Files, Automatic_JumpLists, Custom_JumpLists
            for table_name in ['LNK_Files', 'Automatic_JumpLists', 'Custom_JumpLists']:
                query = f"""
                    SELECT rowid, *
                    FROM {table_name}
                    WHERE (Time_Modification IS NOT NULL OR Time_Creation IS NOT NULL OR Time_Access IS NOT NULL)
                """
                
                params = []
                if start_time and end_time:
                    query += " AND (Time_Modification BETWEEN ? AND ? OR Time_Creation BETWEEN ? AND ? OR Time_Access BETWEEN ? AND ?)"
                    s, e = start_time.isoformat(), end_time.isoformat()
                    params.extend([s, e, s, e, s, e])
                elif start_time:
                    query += " AND (Time_Modification >= ? OR Time_Creation >= ? OR Time_Access >= ?)"
                    s = start_time.isoformat()
                    params.extend([s, s, s])
                elif end_time:
                    query += " AND (Time_Modification <= ? OR Time_Creation <= ? OR Time_Access <= ?)"
                    e = end_time.isoformat()
                    params.extend([e, e, e])
                
                query += " ORDER BY COALESCE(Time_Modification, Time_Creation, Time_Access) ASC"
                
                if max_events is not None:
                    remaining = max_events - len(events)
                    if remaining <= 0: break
                    query += f" LIMIT {remaining}"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                def is_in_range(ts_dt):
                    if not ts_dt: return False
                    if start_time and ts_dt < start_time: return False
                    if end_time and ts_dt > end_time: return False
                    return True

                for row in rows:
                    rid = row['rowid']
                    ts_map = [
                        ('Time_Modification', 'modified'),
                        ('Time_Creation',     'created'),
                        ('Time_Access',       'accessed')
                    ]
                    
                    for col, sub_type in ts_map:
                        raw_ts = row[col]
                        if not raw_ts: continue
                        ts = TimestampParser.parse_timestamp(raw_ts)
                        if ts and is_in_range(ts):
                            lnk_name = 'Unknown'
                            if 'LNK_Name' in row.keys(): lnk_name = row['LNK_Name']
                            elif 'Source_Name' in row.keys(): lnk_name = row['Source_Name']
                            
                            lnk_path = ''
                            if 'LNK_Path' in row.keys(): lnk_path = row['LNK_Path']
                            elif 'Source_Path' in row.keys(): lnk_path = row['Source_Path']
                            
                            events.append({
                                'id': f"lnk_{rid}_{sub_type}_{raw_ts}_{table_name}",
                                'timestamp': ts,
                                'subType': sub_type,
                                'artifact_type': 'LNK',
                                'source_db': 'LnkDB.db',
                                'source_table': table_name,
                                'source_row_id': str(rid),
                                'display_name': lnk_name,
                                'full_path': lnk_path,
                                'details': {k: row[k] for k in row.keys()},
                                'annotation': None
                            })
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query LNK data: {e}")
        
        return events
    
    def _query_registry_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query Registry artifacts within time range."""
        conn = self._get_connection('Registry')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        # Use mappings to iterate through all registry sub-tables
        registry_mappings = self.TIMESTAMP_MAPPINGS.get('Registry', [])
        
        for table_name, timestamp_col, type_tag, *extra in registry_mappings:
            # Check if we've reached max_events limit
            if max_events is not None and len(events) >= max_events:
                break
            
            try:
                query = f"""
                    SELECT rowid, *
                    FROM {table_name}
                    WHERE {timestamp_col} IS NOT NULL
                """
                
                params = []
                if start_time:
                    query += f" AND {timestamp_col} >= ?"
                    params.append(start_time.isoformat())
                if end_time:
                    query += f" AND {timestamp_col} <= ?"
                    params.append(end_time.isoformat())
                
                query += f" ORDER BY {timestamp_col} ASC"
                
                # Add LIMIT for remaining events if max_events is specified
                if max_events is not None:
                    remaining = max_events - len(events)
                    query += f" LIMIT {remaining}"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                for row in rows:
                    rid = row['rowid']
                    timestamp = TimestampParser.parse_timestamp(row[timestamp_col])
                    if timestamp:
                        # Find a name column safely
                        name = 'Unknown'
                        for name_col in ['filename', 'name', 'program_path', 'app_path', 'path', 'display_name', 'folder_name', 'extension']:
                            try:
                                if name_col in row.keys() and row[name_col]:
                                    name = row[name_col]
                                    break
                            except: continue
                        
                        event = {
                            'id': f"registry_{table_name}_{rid}_{row[timestamp_col]}",
                            'timestamp': timestamp,
                            'artifact_type': 'Registry',
                            'source_db': 'registry_data.db',
                            'source_table': table_name,
                            'source_row_id': str(rid),
                            'display_name': f"[{table_name}] {name}",
                            'full_path': '',
                            'details': {k: row[k] for k in row.keys()},
                            'annotation': None
                        }
                        events.append(event)
            
            except sqlite3.Error as e:
                logger.debug(f"Failed to query {table_name}: {e}")
                continue
        
        return events
    
    def _query_bam_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query BAM artifacts within time range."""
        # BAM data is in the registry database
        conn = self._get_connection('BAM')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT rowid, *
                FROM BAM
                WHERE last_execution IS NOT NULL
            """
            
            params = []
            if start_time:
                query += " AND last_execution >= ?"
                params.append(start_time.isoformat())
            if end_time:
                query += " AND last_execution <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY last_execution ASC"
            
            # Add LIMIT only if max_events is specified
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                rid = row['rowid']
                timestamp = TimestampParser.parse_timestamp(row['last_execution'])
                if timestamp:
                    program_name = row['Program_Name'] if 'Program_Name' in row.keys() else 'Unknown'
                    program_path = row['Program_Path'] if 'Program_Path' in row.keys() else ''
                    
                    event = {
                        'id': f"bam_{rid}_{row['last_execution']}",
                        'timestamp': timestamp,
                        'artifact_type': 'BAM',
                        'source_db': 'registry_data.db',
                        'source_table': 'BAM',
                        'source_row_id': str(rid),
                        'display_name': program_name,
                        'full_path': program_path,
                        'details': {k: row[k] for k in row.keys()},
                        'annotation': None
                    }
                    events.append(event)
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query BAM data: {e}")
        
        return events
    
    def _query_shellbag_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query ShellBag artifacts within time range."""
        # ShellBag data is in the registry database
        conn = self._get_connection('ShellBag')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        try:
            # Filter on all available shellbag timestamps
            query = """
                SELECT rowid, *
                FROM Shellbags
                WHERE (modified_date IS NOT NULL OR created_date IS NOT NULL OR access_date IS NOT NULL OR accessed_date IS NOT NULL)
            """
            
            params = []
            if start_time and end_time:
                query += " AND (modified_date BETWEEN ? AND ? OR created_date BETWEEN ? AND ? OR access_date BETWEEN ? AND ? OR accessed_date BETWEEN ? AND ?)"
                s, e = start_time.isoformat(), end_time.isoformat()
                params.extend([s, e, s, e, s, e, s, e])
            elif start_time:
                query += " AND (modified_date >= ? OR created_date >= ? OR access_date >= ? OR accessed_date >= ?)"
                s = start_time.isoformat()
                params.extend([s, s, s, s])
            elif end_time:
                query += " AND (modified_date <= ? OR created_date <= ? OR access_date <= ? OR accessed_date <= ?)"
                e = end_time.isoformat()
                params.extend([e, e, e, e])
            
            query += " ORDER BY COALESCE(modified_date, created_date, access_date) ASC"
            
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            def is_in_range(ts_dt):
                if not ts_dt: return False
                if start_time and ts_dt < start_time: return False
                if end_time and ts_dt > end_time: return False
                return True

            for row in rows:
                rid = row['rowid']
                ts_map = [
                    ('modified_date', 'modified'),
                    ('created_date',  'created'),
                    ('access_date',   'accessed'),
                    ('accessed_date', 'accessed')
                ]
                
                path = 'Unknown'
                if 'Path' in row.keys(): path = row['Path']
                elif 'path' in row.keys(): path = row['path']

                for col, sub_type in ts_map:
                    raw_ts = row[col]
                    if not raw_ts: continue
                    ts = TimestampParser.parse_timestamp(raw_ts)
                    if ts and is_in_range(ts):
                        events.append({
                            'id': f"shellbag_{rid}_{sub_type}_{raw_ts}",
                            'timestamp': ts,
                            'subType': sub_type,
                            'artifact_type': 'ShellBag',
                            'source_db': 'registry_data.db',
                            'source_table': 'Shellbags',
                            'source_row_id': str(rid),
                            'display_name': os.path.basename(path) if path else 'Unknown',
                            'full_path': path,
                            'details': {k: row[k] for k in row.keys()},
                            'annotation': None
                        })
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query ShellBag data: {e}")
        
        return events
    
    def _query_srum_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query SRUM artifacts within time range."""
        conn = self._get_connection('SRUM')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        # Query from srum_application_usage table (primary table)
        try:
            query = """
                SELECT rowid, *
                FROM srum_application_usage
                WHERE timestamp IS NOT NULL
            """
            
            params = []
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY timestamp ASC"
            
            # Add LIMIT only if max_events is specified
            # This allows unlimited queries when time range filtering is sufficient
            if max_events is not None:
                query += f" LIMIT {max_events}"
                logger.debug(f"SRUM query limited to {max_events} events")
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                rid = row['rowid']
                timestamp = TimestampParser.parse_timestamp(row['timestamp'])
                if timestamp:
                    # sqlite3.Row doesn't have .get() method, use dict() or direct access with try/except
                    app_id = row['app_name'] if 'app_name' in row.keys() else 'unknown'
                    app_path = row['app_path'] if 'app_path' in row.keys() else ''
                    user_sid = row['user_sid'] if 'user_sid' in row.keys() else ''
                    user_name_raw = row['user_name'] if 'user_name' in row.keys() else ''
                    foreground_cycle_time = row['foreground_cycle_time'] if 'foreground_cycle_time' in row.keys() else 0
                    
                    # Resolve app name using the resolver
                    resolved_app_name = self.srum_resolver.resolve_app_name(app_id, app_path)
                    
                    # Resolve user name using the resolver
                    resolved_user_name = self.srum_resolver.resolve_user_name(user_sid, user_name_raw)
                    
                    event = {
                        'id': f"srum_{rid}_{row['timestamp']}",
                        'timestamp': timestamp,
                        'artifact_type': 'SRUM',
                        'source_db': 'srum_data.db',
                        'source_table': 'srum_application_usage',
                        'source_row_id': str(rid),
                        'display_name': resolved_app_name,
                        'full_path': app_path if app_path != app_id else '',
                        'details': {k: row[k] for k in row.keys()},
                        'annotation': None
                    }
                    events.append(event)
        except sqlite3.Error as e:
            logger.error(f"Failed to query SRUM data: {e}")
        
        return events
    
    def _query_usn_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query USN artifacts within time range."""
        conn = self._get_connection('USN')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT *
                FROM journal_events
                WHERE timestamp IS NOT NULL
            """
            
            params = []
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY timestamp ASC"
            
            # Add LIMIT only if max_events is specified
            # This allows unlimited queries when time range filtering is sufficient
            if max_events is not None:
                query += f" LIMIT {max_events}"
                logger.debug(f"USN query limited to {max_events} events")
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                timestamp = TimestampParser.parse_timestamp(row['timestamp'])
                if timestamp:
                    # Get file name and reason safely - sqlite3.Row doesn't have .get()
                    try:
                        file_name = row['filename']  # Column is 'filename' not 'file_name'
                    except (KeyError, IndexError):
                        file_name = 'Unknown'
                    
                    try:
                        reason = row['reason']
                    except (KeyError, IndexError):
                        reason = ''
                    
                    event = {
                        'id': f"usn_{file_name}_{row['timestamp']}",
                        'timestamp': timestamp,
                        'artifact_type': 'USN',
                        'source_db': 'USN_journal.db',
                        'source_table': 'journal_events',
                        'source_row_id': file_name,
                        'display_name': file_name,
                        'full_path': '',  # USN doesn't have full path in this schema
                        'details': {
                            'reason': reason,
                        },
                        'annotation': None
                    }
                    events.append(event)
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query USN data: {e}")
        
        return events
    
    def _query_mft_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        max_events: Optional[int] = None
    ) -> List[Dict]:
        """Query MFT artifacts within time range."""
        conn = self._get_connection('MFT')
        if not conn:
            return []
        
        events = []
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT *
                FROM mft_records
                WHERE modified_time IS NOT NULL
            """
            
            params = []
            if start_time:
                query += " AND modified_time >= ?"
                params.append(start_time.isoformat())
            if end_time:
                query += " AND modified_time <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY modified_time ASC"
            
            # Add LIMIT only if max_events is specified
            # This allows unlimited queries when time range filtering is sufficient
            if max_events is not None:
                query += f" LIMIT {max_events}"
                logger.debug(f"MFT query limited to {max_events} events")
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                timestamp = TimestampParser.parse_timestamp(row['modified_time'])
                if timestamp:
                    # Get file name safely - sqlite3.Row doesn't have .get()
                    try:
                        file_name = row['file_name']
                    except (KeyError, IndexError):
                        file_name = 'Unknown'
                    
                    try:
                        created_time = row['created_time']
                    except (KeyError, IndexError):
                        created_time = None
                    
                    try:
                        accessed_time = row['accessed_time']
                    except (KeyError, IndexError):
                        accessed_time = None
                    
                    event = {
                        'id': f"mft_{file_name}_{row['modified_time']}",
                        'timestamp': timestamp,
                        'artifact_type': 'MFT',
                        'source_db': 'mft_claw_analysis.db',
                        'source_table': 'mft_records',
                        'source_row_id': file_name,
                        'display_name': file_name,
                        'full_path': '',  # MFT doesn't have full path in single column
                        'details': {
                            'created_time': created_time,
                            'accessed_time': accessed_time,
                        },
                        'annotation': None
                    }
                    events.append(event)
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query MFT data: {e}")
        
        return events
    
    def create_timestamp_indexes(
        self,
        artifact_types: Optional[List[str]] = None,
        progress_callback: Optional[callable] = None,
        skip_existing: bool = True
    ) -> Dict[str, bool]:
        """
        Create indexes on timestamp columns in artifact databases.
        
        This method creates database indexes on all timestamp columns to optimize
        time-range queries. Indexes are created once and metadata is stored to
        avoid re-indexing on subsequent loads.
        
        Args:
            artifact_types: List of artifact types to index, or None for all available
            progress_callback: Optional callback function(current, total, artifact_type, message)
            skip_existing: If True, skip databases that are already indexed
        
        Returns:
            Dict[str, bool]: Dictionary mapping artifact types to success status
        """
        # Default to all available artifacts if not specified
        if artifact_types is None:
            artifact_types = self._available_artifacts
        
        # Filter to only available artifacts
        artifact_types = [at for at in artifact_types if at in self._available_artifacts]
        
        if not artifact_types:
            logger.warning("No valid artifact types specified for indexing")
            return {}
        
        results = {}
        total = len(artifact_types)
        
        for idx, artifact_type in enumerate(artifact_types):
            if progress_callback:
                progress_callback(idx + 1, total, artifact_type, f"Indexing {artifact_type}...")
            
            # Get database path
            db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type)
            if not db_filename:
                logger.warning(f"Unknown artifact type: {artifact_type}")
                results[artifact_type] = False
                continue
            
            db_path = os.path.join(self.artifacts_dir, db_filename)
            
            if not os.path.exists(db_path):
                logger.warning(f"Database not found: {db_path}")
                results[artifact_type] = False
                continue
            
            # Check if already indexed
            if skip_existing and self.timestamp_indexer._is_indexed(db_filename):
                logger.info(f"Database {db_filename} already indexed, skipping")
                results[artifact_type] = True
                continue
            
            # Create indexes
            try:
                success = self.timestamp_indexer.create_indexes(
                    db_path,
                    artifact_type,
                    progress_callback=lambda c, t, m: progress_callback(idx + 1, total, artifact_type, m) if progress_callback else None
                )
                results[artifact_type] = success
            
            except Exception as e:
                logger.error(f"Failed to create indexes for {artifact_type}: {e}")
                results[artifact_type] = False
        
        if progress_callback:
            progress_callback(total, total, "Complete", "Indexing complete")
        
        logger.info(f"Indexing complete: {sum(results.values())}/{len(results)} successful")
        return results
    
    def is_indexed(self, artifact_type: str) -> bool:
        """
        Check if an artifact database has been indexed.
        
        Args:
            artifact_type: Type of artifact
        
        Returns:
            bool: True if indexed, False otherwise
        """
        db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type)
        if not db_filename:
            return False
        
        return self.timestamp_indexer._is_indexed(db_filename)
    
    def get_index_info(self, artifact_type: str) -> Optional[Dict]:
        """
        Get index information for an artifact database.
        
        Args:
            artifact_type: Type of artifact
        
        Returns:
            Optional[Dict]: Index information or None
        """
        db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type)
        if not db_filename:
            return None
        
        return self.timestamp_indexer.get_index_info(db_filename)
    
    def clear_index_metadata(self, artifact_type: Optional[str] = None):
        """
        Clear index metadata for an artifact or all artifacts.
        
        This forces re-indexing on next load.
        
        Args:
            artifact_type: Type of artifact, or None to clear all
        """
        if artifact_type:
            db_filename = self.ARTIFACT_DB_MAPPING.get(artifact_type)
            if db_filename:
                self.timestamp_indexer.clear_index_metadata(db_filename)
        else:
            self.timestamp_indexer.clear_index_metadata()
    
    def close_connections(self):
        """
        Close all database connections in the connection pool.
        
        Should be called when timeline dialog is closed to free resources.
        This method safely closes all pooled connections and clears statistics.
        """
        with self._pool_lock:
            for artifact_type, pool_entry in list(self._connection_pool.items()):
                try:
                    pool_entry.connection.close()
                    self._connection_stats['total_closed'] += 1
                    logger.debug(f"Closed connection for {artifact_type} (used {pool_entry.use_count} times)")
                except Exception as e:
                    logger.debug(f"Could not close connection for {artifact_type}: {e}")
            
            self._connection_pool.clear()
        
        logger.info(f"All database connections closed. Stats: {self._connection_stats['total_created']} created, "
                   f"{self._connection_stats['total_reused']} reused, {self._connection_stats['total_closed']} closed")
    
    def set_srum_show_ids(self, show_ids: bool):
        """
        Set whether to show SRUM app IDs alongside names.
        
        Args:
            show_ids: If True, show both name and ID; if False, show name only
        """
        self.srum_resolver.set_show_ids(show_ids)
    
    def get_srum_show_ids(self) -> bool:
        """
        Get current SRUM show_ids setting.
        
        Returns:
            bool: Current show_ids value
        """
        return self.srum_resolver.get_show_ids()
    
    def add_srum_custom_mapping(self, app_id: str, app_name: str):
        """
        Add a custom SRUM application ID to name mapping.
        
        Args:
            app_id: The application ID
            app_name: The application name
        """
        self.srum_resolver.add_custom_mapping(app_id, app_name)
    
    def get_srum_cache_stats(self) -> Dict[str, int]:
        """
        Get SRUM resolver cache statistics.
        
        Returns:
            Dict[str, int]: Dictionary with cache statistics
        """
        return self.srum_resolver.get_cache_stats()
    
    def get_power_events(self, start_time: Optional[datetime] = None, 
                         end_time: Optional[datetime] = None) -> List[Dict]:
        """
        Extract power events from Windows Event Logs.
        
        Args:
            start_time: Optional start time for filtering
            end_time: Optional end time for filtering
        
        Returns:
            List[Dict]: List of power event dictionaries
        """
        from timeline.data.power_event_extractor import PowerEventExtractor
        
        try:
            # Initialize power event extractor
            extractor = PowerEventExtractor()
            
            # Set event log database path
            event_log_path = os.path.join(self.artifacts_dir, 'event_log.db')
            if not os.path.exists(event_log_path):
                logger.warning(f"Event log database not found: {event_log_path}")
                return []
            
            extractor.set_event_log_path(event_log_path)
            
            # Extract power events
            power_events = extractor.extract_power_events(start_time, end_time)
            
            logger.info(f"Extracted {len(power_events)} power events")
            return power_events
            
        except Exception as e:
            logger.error(f"Error extracting power events: {e}")
            if self.error_handler:
                self.error_handler.handle_error(
                    e, 
                    "extracting power events",
                    severity=ErrorSeverity.WARNING,
                    show_dialog=False
                )
            return []
    
    def get_system_sessions(self, power_events: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Detect system uptime sessions from power events.
        
        Args:
            power_events: Optional list of power events (if None, will extract them)
        
        Returns:
            List[Dict]: List of session dictionaries with start/end times and durations
        """
        from timeline.data.power_event_extractor import PowerEventExtractor
        
        try:
            # Get power events if not provided
            if power_events is None:
                power_events = self.get_power_events()
            
            if not power_events:
                logger.warning("No power events available for session detection")
                return []
            
            # Initialize extractor for session detection
            extractor = PowerEventExtractor()
            
            # Detect sessions
            sessions = extractor.detect_system_sessions(power_events)
            
            logger.info(f"Detected {len(sessions)} system sessions")
            return sessions
            
        except Exception as e:
            logger.error(f"Error detecting system sessions: {e}")
            if self.error_handler:
                self.error_handler.handle_error(
                    e,
                    "detecting system sessions",
                    severity=ErrorSeverity.WARNING,
                    show_dialog=False
                )
            return []
    
    def get_uptime_statistics(self, sessions: Optional[List[Dict]] = None) -> Dict:
        """
        Calculate system uptime statistics.
        
        Args:
            sessions: Optional list of sessions (if None, will detect them)
        
        Returns:
            Dict: Statistics including total uptime, session count, average duration
        """
        from timeline.data.power_event_extractor import PowerEventExtractor
        
        try:
            # Get sessions if not provided
            if sessions is None:
                sessions = self.get_system_sessions()
            
            if not sessions:
                logger.warning("No sessions available for statistics")
                return {
                    'total_uptime_seconds': 0,
                    'total_uptime_hours': 0.0,
                    'session_count': 0,
                    'startup_count': 0,
                    'average_session_seconds': 0,
                    'average_session_hours': 0.0
                }
            
            # Initialize extractor for statistics
            extractor = PowerEventExtractor()
            
            # Calculate statistics
            stats = extractor.calculate_uptime_statistics(sessions)
            
            logger.info(f"Calculated uptime statistics: {stats['total_uptime_hours']:.2f} hours total")
            return stats
            
        except Exception as e:
            logger.error(f"Error calculating uptime statistics: {e}")
            if self.error_handler:
                self.error_handler.handle_error(
                    e,
                    "calculating uptime statistics",
                    severity=ErrorSeverity.WARNING,
                    show_dialog=False
                )
            return {}
    
    def get_aggregated_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        artifact_types: Optional[List[str]] = None,
        bucket_size: str = 'hour'
    ) -> List[Dict]:
        """
        Get aggregated events grouped into time buckets.
        
        This method queries events and aggregates them into time buckets with
        counts by artifact type. This is used for efficient rendering when
        the timeline is zoomed out and showing many events.
        
        Args:
            start_time: Start of time range (inclusive), or None for no lower bound
            end_time: End of time range (inclusive), or None for no upper bound
            artifact_types: List of artifact types to query, or None for all available
            bucket_size: Size of time buckets ('minute', 'hour', 'day', 'week', etc.)
        
        Returns:
            List[Dict]: List of aggregated bucket dictionaries with structure:
                {
                    'time_bucket': datetime,
                    'bucket_size': str,
                    'counts_by_type': dict,
                    'total_count': int,
                    'event_ids': list
                }
        """
        from timeline.data.event_aggregator import EventAggregator
        
        try:
            # Query events in time range
            events = self.query_time_range(start_time, end_time, artifact_types)
            
            if not events:
                logger.info("No events to aggregate")
                return []
            
            # Initialize aggregator
            aggregator = EventAggregator()
            
            # Aggregate events
            aggregated = aggregator.aggregate_events(
                events,
                bucket_size=bucket_size,
                start_time=start_time,
                end_time=end_time
            )
            
            logger.info(f"Aggregated {len(events)} events into {len(aggregated)} buckets")
            return aggregated
            
        except Exception as e:
            logger.error(f"Error aggregating events: {e}")
            if self.error_handler:
                self.error_handler.handle_error(
                    e,
                    "aggregating timeline events",
                    show_dialog=False
                )
            return []
    
    def calculate_optimal_bucket_size(
        self,
        event_count: int,
        time_range_seconds: float,
        target_buckets: int = 100
    ) -> str:
        """
        Calculate optimal bucket size for aggregation.
        
        Args:
            event_count: Number of events to aggregate
            time_range_seconds: Time range in seconds
            target_buckets: Target number of buckets (default: 100)
        
        Returns:
            str: Optimal bucket size name
        """
        from timeline.data.event_aggregator import EventAggregator
        
        aggregator = EventAggregator()
        return aggregator.calculate_optimal_bucket_size(
            event_count,
            time_range_seconds,
            target_buckets
        )
    
    def __del__(self):
        """Destructor to ensure connections are closed."""
        self.close_connections()
