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
    
    # Timestamp column mappings for each artifact type
    # Format: artifact_type -> [(table_name, timestamp_column, timestamp_type)]
    # Updated to match actual database schemas in case directory
    TIMESTAMP_MAPPINGS = {
        'Prefetch': [
            ('prefetch_data', 'last_executed', 'executed'),
        ],
        'LNK': [
            ('JLCE', 'Time_Creation', 'created'),
            ('JLCE', 'Time_Modification', 'modified'),
            ('JLCE', 'Time_Access', 'accessed'),
        ],
        'Registry': [
            ('UserAssist', 'timestamp', 'various'),
            ('MUICache', 'timestamp', 'various'),
            ('InstalledSoftware', 'timestamp', 'various'),
        ],
        'BAM': [
            ('BAM', 'timestamp', 'executed'),
        ],
        'ShellBag': [
            ('Shellbags', 'created_date', 'created'),
            ('Shellbags', 'modified_date', 'modified'),
            ('Shellbags', 'access_date', 'accessed'),
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
        self._connection_pool: Dict[str, ConnectionPoolEntry] = {}
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
        existing database files.
        """
        self._available_artifacts = []
        self._unavailable_artifacts = []
        
        for artifact_type, db_filename in self.ARTIFACT_DB_MAPPING.items():
            db_path = os.path.join(self.artifacts_dir, db_filename)
            
            if os.path.exists(db_path) and os.path.isfile(db_path):
                # Check if database is not empty
                file_size = os.path.getsize(db_path)
                if file_size > 0:
                    self._available_artifacts.append(artifact_type)
                    logger.debug(f"Found database for {artifact_type}: {db_path} ({file_size:,} bytes)")
                else:
                    self._unavailable_artifacts.append((artifact_type, 'empty'))
                    logger.warning(f"Database for {artifact_type} is empty: {db_path}")
            else:
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
        - Thread-safe connection management
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
        
        with self._pool_lock:
            # Check if we have a valid pooled connection
            if artifact_type in self._connection_pool:
                pool_entry = self._connection_pool[artifact_type]
                
                # Verify connection is from same thread (SQLite requirement)
                if not pool_entry.is_same_thread():
                    logger.debug(f"Connection for {artifact_type} is from different thread, creating new connection")
                    # Don't close here - will be cleaned up by owning thread
                    del self._connection_pool[artifact_type]
                else:
                    # Perform health check
                    if pool_entry.health_check():
                        # Connection is healthy, reuse it
                        pool_entry.mark_used()
                        self._connection_stats['total_reused'] += 1
                        logger.debug(f"Reusing connection for {artifact_type} (used {pool_entry.use_count} times)")
                        return pool_entry.connection
                    else:
                        # Connection failed health check
                        logger.warning(f"Connection for {artifact_type} failed health check, creating new connection")
                        self._connection_stats['total_health_failures'] += 1
                        try:
                            pool_entry.connection.close()
                            self._connection_stats['total_closed'] += 1
                        except:
                            pass
                        del self._connection_pool[artifact_type]
        
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
            conn = sqlite3.connect(
                db_path,
                timeout=30.0,  # 30 second timeout
                check_same_thread=False  # Allow connection to be used across threads (with caution)
            )
            conn.row_factory = sqlite3.Row  # Enable column access by name
            
            # Test connection
            conn.execute("SELECT 1")
            
            # Add to connection pool
            with self._pool_lock:
                pool_entry = ConnectionPoolEntry(conn, artifact_type)
                pool_entry.mark_used()
                self._connection_pool[artifact_type] = pool_entry
                self._connection_stats['total_created'] += 1
            
            logger.debug(f"Created new database connection for {artifact_type}")
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
            idle_connections = []
            
            # Find idle connections
            for artifact_type, pool_entry in self._connection_pool.items():
                if pool_entry.is_idle(self._idle_timeout):
                    idle_connections.append(artifact_type)
            
            # Close and remove idle connections
            for artifact_type in idle_connections:
                pool_entry = self._connection_pool[artifact_type]
                try:
                    pool_entry.connection.close()
                    self._connection_stats['total_closed'] += 1
                    self._connection_stats['idle_timeouts'] += 1
                    logger.debug(f"Closed idle connection for {artifact_type} (idle for {current_time - pool_entry.last_used:.1f}s)")
                except Exception as e:
                    logger.debug(f"Error closing idle connection for {artifact_type}: {e}")
                
                del self._connection_pool[artifact_type]
    
    def perform_health_checks(self) -> Dict[str, bool]:
        """
        Perform health checks on all pooled connections.
        
        Returns:
            Dict[str, bool]: Dictionary mapping artifact types to health status
        """
        health_status = {}
        
        with self._pool_lock:
            for artifact_type, pool_entry in list(self._connection_pool.items()):
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
                    except:
                        pass
                    del self._connection_pool[artifact_type]
        
        return health_status
    
    def get_connection_stats(self) -> Dict:
        """
        Get connection pool statistics.
        
        Returns:
            Dict: Dictionary with connection statistics including:
                - total_created: Total connections created
                - total_closed: Total connections closed
                - total_reused: Total connection reuses
                - total_health_checks: Total health checks performed
                - total_health_failures: Total health check failures
                - idle_timeouts: Total idle timeout closures
                - active_connections: Current number of active connections
                - connections_by_type: Active connections per artifact type
        """
        with self._pool_lock:
            stats = self._connection_stats.copy()
            stats['active_connections'] = len(self._connection_pool)
            stats['connections_by_type'] = {
                artifact_type: {
                    'use_count': entry.use_count,
                    'age_seconds': time.time() - entry.created_at,
                    'idle_seconds': time.time() - entry.last_used,
                    'thread_id': entry.thread_id,
                    'is_valid': entry.is_valid
                }
                for artifact_type, entry in self._connection_pool.items()
            }
        
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
        
        for table_name, timestamp_column, _ in timestamp_mappings:
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
                    self.error_handler.handle_error(
                        e,
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
            # Build query with time range filters
            query = """
                SELECT 
                    filename,
                    executable_name,
                    hash,
                    run_count,
                    last_executed,
                    created_on,
                    modified_on
                FROM prefetch_data
                WHERE last_executed IS NOT NULL
            """
            
            params = []
            
            if start_time:
                query += " AND last_executed >= ?"
                params.append(start_time.isoformat())
            
            if end_time:
                query += " AND last_executed <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY last_executed ASC"
            
            # Add LIMIT only if max_events is specified
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Convert rows to event dictionaries
            for row in rows:
                timestamp = TimestampParser.parse_timestamp(row['last_executed'])
                
                if timestamp:
                    event = {
                        'id': f"prefetch_{row['filename']}",
                        'timestamp': timestamp,
                        'artifact_type': 'Prefetch',
                        'source_db': 'prefetch_data.db',
                        'source_table': 'prefetch_data',
                        'source_row_id': row['filename'],
                        'display_name': row['executable_name'] or 'Unknown',
                        'full_path': row['filename'] or '',
                        'details': {
                            'run_count': row['run_count'],
                            'hash': row['hash'],
                            'created_on': row['created_on'],
                            'modified_on': row['modified_on'],
                        },
                        'annotation': None
                    }
                    events.append(event)
        
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
            # Query using primary timestamp (Time_Modification)
            # LnkDB.db has JLCE and Custom_JLCE tables
            query = """
                SELECT *
                FROM JLCE
                WHERE Time_Modification IS NOT NULL
            """
            
            params = []
            if start_time:
                query += " AND Time_Modification >= ?"
                params.append(start_time.isoformat())
            if end_time:
                query += " AND Time_Modification <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY Time_Modification ASC"
            
            # Add LIMIT only if max_events is specified
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                timestamp = TimestampParser.parse_timestamp(row['Time_Modification'])
                if timestamp:
                    # Get column names safely - sqlite3.Row doesn't have .get()
                    try:
                        lnk_name = row['LNK_Name']
                    except (KeyError, IndexError):
                        lnk_name = 'Unknown'
                    
                    try:
                        lnk_path = row['LNK_Path']
                    except (KeyError, IndexError):
                        lnk_path = ''
                    
                    try:
                        target_path = row['Target_Path']
                    except (KeyError, IndexError):
                        target_path = ''
                    
                    try:
                        creation_time = row['Time_Creation']
                    except (KeyError, IndexError):
                        creation_time = None
                    
                    try:
                        access_time = row['Time_Access']
                    except (KeyError, IndexError):
                        access_time = None
                    
                    event = {
                        'id': f"lnk_{lnk_name}_{row['Time_Modification']}",
                        'timestamp': timestamp,
                        'artifact_type': 'LNK',
                        'source_db': 'LnkDB.db',
                        'source_table': 'JLCE',
                        'source_row_id': lnk_name,
                        'display_name': lnk_name,
                        'full_path': lnk_path,
                        'details': {
                            'target_path': target_path,
                            'creation_time': creation_time,
                            'access_time': access_time,
                        },
                        'annotation': None
                    }
                    events.append(event)
        
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
        
        # Query multiple registry tables that have timestamps
        tables_to_query = [
            ('UserAssist', 'timestamp', 'Program_Name'),
            ('MUICache', 'timestamp', 'Program_Name'),
            ('InstalledSoftware', 'timestamp', 'Display_Name'),
        ]
        
        for table_name, timestamp_col, name_col in tables_to_query:
            # Check if we've reached max_events limit
            if max_events is not None and len(events) >= max_events:
                break
            
            try:
                query = f"""
                    SELECT *
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
                    timestamp = TimestampParser.parse_timestamp(row[timestamp_col])
                    if timestamp:
                        # Get name safely - sqlite3.Row doesn't have .get()
                        try:
                            name = row[name_col]
                        except (KeyError, IndexError):
                            name = 'Unknown'
                        
                        event = {
                            'id': f"registry_{table_name}_{name}_{row[timestamp_col]}",
                            'timestamp': timestamp,
                            'artifact_type': 'Registry',
                            'source_db': 'registry_data.db',
                            'source_table': table_name,
                            'source_row_id': name,
                            'display_name': name,
                            'full_path': '',
                            'details': {
                                'table': table_name,
                            },
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
                SELECT *
                FROM BAM
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
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                timestamp = TimestampParser.parse_timestamp(row['timestamp'])
                if timestamp:
                    # Get program name safely - sqlite3.Row doesn't have .get()
                    try:
                        program_name = row['Program_Name']
                    except (KeyError, IndexError):
                        program_name = 'Unknown'
                    
                    try:
                        program_path = row['Program_Path']
                    except (KeyError, IndexError):
                        program_path = ''
                    
                    event = {
                        'id': f"bam_{program_name}_{row['timestamp']}",
                        'timestamp': timestamp,
                        'artifact_type': 'BAM',
                        'source_db': 'registry_data.db',
                        'source_table': 'BAM',
                        'source_row_id': program_name,
                        'display_name': program_name,
                        'full_path': program_path,
                        'details': {},
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
            # Use modified_date as primary timestamp
            query = """
                SELECT *
                FROM Shellbags
                WHERE modified_date IS NOT NULL
            """
            
            params = []
            if start_time:
                query += " AND modified_date >= ?"
                params.append(start_time.isoformat())
            if end_time:
                query += " AND modified_date <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY modified_date ASC"
            
            # Add LIMIT only if max_events is specified
            if max_events is not None:
                query += f" LIMIT {max_events}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for row in rows:
                timestamp = TimestampParser.parse_timestamp(row['modified_date'])
                if timestamp:
                    # Get path safely - sqlite3.Row doesn't have .get()
                    try:
                        path = row['Path']
                    except (KeyError, IndexError):
                        path = 'Unknown'
                    
                    try:
                        created_date = row['created_date']
                    except (KeyError, IndexError):
                        created_date = None
                    
                    try:
                        access_date = row['access_date']
                    except (KeyError, IndexError):
                        access_date = None
                    
                    event = {
                        'id': f"shellbag_{path}_{row['modified_date']}",
                        'timestamp': timestamp,
                        'artifact_type': 'ShellBag',
                        'source_db': 'registry_data.db',
                        'source_table': 'Shellbags',
                        'source_row_id': path,
                        'display_name': os.path.basename(path) if path else 'Unknown',
                        'full_path': path,
                        'details': {
                            'created_date': created_date,
                            'access_date': access_date,
                        },
                        'annotation': None
                    }
                    events.append(event)
        
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
                SELECT *
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
                        'id': f"srum_{app_id}_{row['timestamp']}",
                        'timestamp': timestamp,
                        'artifact_type': 'SRUM',
                        'source_db': 'srum_data.db',
                        'source_table': 'srum_application_usage',
                        'source_row_id': app_id,
                        'display_name': resolved_app_name,
                        'full_path': app_path if app_path != app_id else '',
                        'details': {
                            'app_id': app_id,
                            'user_sid': user_sid,
                            'user_name': resolved_user_name,
                            'foreground_cycle_time': foreground_cycle_time,
                        },
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
