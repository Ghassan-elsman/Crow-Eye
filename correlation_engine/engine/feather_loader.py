"""
Feather Loader
Loads feather databases and provides query interface with identifier extraction capabilities.
"""

import logging
import sqlite3
from typing import List, Dict, Any, Optional, Iterator
from pathlib import Path

logger = logging.getLogger(__name__)


# Exception hierarchy for FeatherLoader errors
class FeatherLoaderError(Exception):
    """Base exception for FeatherLoader errors"""
    pass


class InvalidDatabaseError(FeatherLoaderError):
    """Database file is invalid or corrupted"""
    pass


class NoDataTablesError(FeatherLoaderError):
    """No suitable data tables found in database"""
    pass


class EmptyTableError(FeatherLoaderError):
    """Primary data table contains no rows"""
    pass


class SchemaDetectionError(FeatherLoaderError):
    """Failed to detect usable schema"""
    pass


class FeatherLoader:
    """Loads and queries feather databases with identifier extraction support"""
    
    # Column detection patterns for identifier extraction
    NAME_PATTERNS = ['name', 'executable', 'filename', 'exe_name', 'application', 'app_name', 'process_name']
    PATH_PATTERNS = ['path', 'filepath', 'full_path', 'exe_path', 'executable_path', 'file_path', 'full_file_path']
    TIMESTAMP_PATTERNS = [
        # Exact matches (highest priority)
        'timestamp', 'eventtimestamputc', 'focus_time',
        # ShimCache patterns
        'last_modified', 'last_modified_readable',
        # AmCache patterns
        'install_date', 'link_date',
        # LNK & Jumplist patterns
        'time_access', 'time_creation', 'time_modification',
        # Generic patterns
        'datetime', 'execution_time', 'last_run', 'modified_time', 
        'created_time', 'accessed_time', 'run_time', 'exec_time',
        'access_date', 'creation_date', 'modification_date'
    ]
    
    def __init__(self, database_path: str, config=None, timestamp_parser=None):
        """
        Initialize feather loader.
        
        Args:
            database_path: Path to the feather database
            config: Optional Wings configuration for identifier extraction
            timestamp_parser: Optional timestamp parser for parsing timestamps
        """
        self.database_path = database_path
        self.connection = None
        self.artifact_type = None
        self.metadata = {}
        self.config = config
        self.timestamp_parser = timestamp_parser
        self.current_table = None
        self.is_metadata_based = False  # Track if metadata table was found
        self.inferred_artifact_type = None  # Track inferred artifact type
        self.detection_confidence = "low"  # Track detection confidence
        self.schema_cache = {}  # Cache detected columns per table
    
    def connect(self):
        """Connect to the feather database with metadata-optional support"""
        if not Path(self.database_path).exists():
            raise FileNotFoundError(f"Feather database not found: {self.database_path}")
        
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row  # Access columns by name
        
        # Check if metadata table exists
        has_metadata = self._check_metadata_table()
        
        # Only validate schema if not using identifier extraction mode
        if not self.config:
            if has_metadata:
                # Validate schema for traditional feather databases
                self._validate_schema()
            else:
                # Metadata-optional mode: skip strict validation
                logger.info(f"No metadata table found in {self.database_path}, using metadata-optional mode")
        
        # Load metadata (if exists)
        self._load_metadata()
        
        # Apply artifact_type_override if provided in config
        if self.config and hasattr(self.config, 'artifact_type_override') and self.config.artifact_type_override:
            logger.info(f"Using artifact type override: {self.config.artifact_type_override}")
            self.artifact_type = self.config.artifact_type_override
            self.detection_confidence = "high"
        
        # Log connection status with detection summary
        if self.is_metadata_based:
            logger.info(
                f"Feather detection complete for {self.database_path}\n"
                f"  - Artifact Type: {self.artifact_type} (confidence: high)\n"
                f"  - Inference Method: metadata\n"
                f"  - Metadata-based: True"
            )
        else:
            logger.info(
                f"Feather detection complete for {self.database_path}\n"
                f"  - Artifact Type: {self.artifact_type} (confidence: {self.detection_confidence})\n"
                f"  - Inference Method: inferred\n"
                f"  - Metadata-based: False"
            )
    
    def _check_metadata_table(self) -> bool:
        """
        Check if feather_metadata table exists.
        
        Returns:
            True if metadata table exists and is readable
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='feather_metadata'"
            )
            exists = cursor.fetchone() is not None
            self.is_metadata_based = exists
            return exists
        except sqlite3.Error as e:
            logger.warning(f"Error checking metadata table: {e}")
            self.is_metadata_based = False
            return False
    
    def _validate_schema(self):
        """
        Validate feather database schema with auto-detection of data table.
        
        Checks:
        - At least one data table exists (excluding feather_metadata)
        - Auto-detects the data table name
        - feather_metadata table exists (optional)
        
        Raises:
            ValueError: If schema validation fails
        """
        cursor = self.connection.cursor()
        
        # Get all tables except feather_metadata
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'feather_metadata'"
        )
        data_tables = [row[0] for row in cursor.fetchall()]
        
        if not data_tables:
            raise ValueError(
                f"Schema validation failed: no data tables found in {self.database_path}"
            )
        
        # Use the first data table (or 'feather_data' if it exists)
        if 'feather_data' in data_tables:
            self.current_table = 'feather_data'
        else:
            self.current_table = data_tables[0]
        
        logger.info(f"Using data table: {self.current_table}")
        
        # Check if feather_metadata table exists (optional)
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='feather_metadata'"
        )
        has_metadata = cursor.fetchone() is not None
        
        if not has_metadata:
            logger.warning(f"No feather_metadata table found in {self.database_path}, using metadata-optional mode")
    
    @staticmethod
    def validate_schema_standalone(database_path: str) -> tuple[bool, List[str]]:
        """
        Standalone schema validation utility.
        
        Can be used to check feather databases without creating a loader instance.
        
        Args:
            database_path: Path to feather database
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        if not Path(database_path).exists():
            return False, [f"Database file not found: {database_path}"]
        
        try:
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Check feather_data table
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='feather_data'"
            )
            if not cursor.fetchone():
                errors.append("'feather_data' table not found")
            else:
                # Check required columns
                cursor.execute("PRAGMA table_info(feather_data)")
                columns = {row[1] for row in cursor.fetchall()}
                required_columns = {'timestamp', 'application', 'file_path', 'event_id', 'data'}
                missing_columns = required_columns - columns
                if missing_columns:
                    errors.append(f"Missing columns in feather_data: {', '.join(missing_columns)}")
            
            # Check feather_metadata table
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='feather_metadata'"
            )
            if not cursor.fetchone():
                errors.append("'feather_metadata' table not found")
            
            conn.close()
            
        except Exception as e:
            errors.append(f"Database error: {str(e)}")
        
        return len(errors) == 0, errors
    
    def disconnect(self):
        """Disconnect from the feather database"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def _load_metadata(self):
        """Load metadata from the feather database"""
        try:
            cursor = self.connection.cursor()
            # Metadata is stored as key-value pairs
            cursor.execute("SELECT key, value FROM feather_metadata")
            rows = cursor.fetchall()
            
            if rows:
                # Convert key-value pairs to dictionary
                self.metadata = {row[0]: row[1] for row in rows}
                self.artifact_type = self.metadata.get('artifact_type', 'Unknown')
                logger.debug(f"Loaded metadata: artifact_type={self.artifact_type}")
            else:
                self.artifact_type = 'Unknown'
        except sqlite3.Error as e:
            # Metadata table doesn't exist or is empty
            logger.debug(f"Could not load metadata: {e}")
            self.artifact_type = 'Unknown'
    
    def _detect_primary_table(self) -> str:
        """
        Detect the primary data table in the database.
        
        Logic:
        1. Enumerate all tables using sqlite_master
        2. Filter out system tables (sqlite_*, feather_metadata, import_history, data_lineage)
        3. If config specifies table_name, use that
        4. If one table remains, use it
        5. If multiple tables, select the one with most rows
        
        Returns:
            Name of the primary data table
            
        Raises:
            ValueError: If no suitable tables found
        """
        if not self.connection:
            raise RuntimeError("No active database connection")
        
        cursor = self.connection.cursor()
        
        # Check if config specifies table name
        if self.config and hasattr(self.config, 'table_name') and self.config.table_name:
            # Verify the specified table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (self.config.table_name,)
            )
            if cursor.fetchone():
                logger.info(f"Using configured table: {self.config.table_name}")
                return self.config.table_name
            else:
                logger.warning(f"Configured table '{self.config.table_name}' not found, auto-detecting")
        
        # Enumerate all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [row[0] for row in cursor.fetchall()]
        
        # Filter out system tables
        system_tables = {'sqlite_sequence', 'feather_metadata', 'import_history', 'data_lineage'}
        data_tables = [t for t in all_tables if t not in system_tables and not t.startswith('sqlite_')]
        
        if not data_tables:
            raise NoDataTablesError(
                f"No data tables found in {self.database_path}\n"
                f"Details: Database contains only system tables\n"
                f"Suggestion: Ensure the database contains forensic artifact data"
            )
        
        if len(data_tables) == 1:
            logger.info(f"Single data table found: {data_tables[0]}")
            return data_tables[0]
        
        # Multiple tables: select the one with most rows
        logger.info(f"Multiple data tables found: {data_tables}, selecting table with most rows")
        max_rows = 0
        primary_table = data_tables[0]
        
        for table in data_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                row_count = cursor.fetchone()[0]
                logger.debug(f"Table '{table}' has {row_count} rows")
                if row_count > max_rows:
                    max_rows = row_count
                    primary_table = table
            except sqlite3.Error as e:
                logger.warning(f"Error counting rows in table '{table}': {e}")
        
        logger.info(f"Selected primary table: {primary_table} ({max_rows} rows)")
        return primary_table
    
    def _infer_artifact_type_from_table(self, table_name: str) -> Optional[str]:
        """
        Infer artifact type from table name.
        
        Patterns:
        - "systemlog", "system_log" → "systemlog"
        - "prefetch", "windows_prefetch" → "prefetch"
        - "mft", "mft_records", "mft_entries" → "mft"
        - "srum", "srum_data" → "srum"
        - "amcache", "amcache_entries" → "amcache"
        - "userassist" → "userassist"
        - "recyclebin", "recycle_bin" → "recyclebin"
        
        Returns:
            Inferred artifact type or None if no match
        """
        table_lower = table_name.lower()
        
        # Exact matches
        exact_matches = {
            'prefetch': 'Prefetch',
            'prefetch_data': 'Prefetch',
            'systemlog': 'SystemLog',
            'system_log': 'SystemLog',
            'mft': 'MFT',
            'mft_records': 'MFT',
            'srum': 'SRUM',
            'srum_data': 'SRUM',
            'amcache': 'AmCache',
            'userassist': 'UserAssist',
            'recyclebin': 'RecycleBin',
            'recycle_bin': 'RecycleBin',
        }
        
        if table_lower in exact_matches:
            return exact_matches[table_lower]
        
        # Partial matches
        if 'prefetch' in table_lower:
            return 'Prefetch'
        if 'log' in table_lower or 'event' in table_lower:
            return 'SystemLog'
        if 'mft' in table_lower:
            return 'MFT'
        if 'srum' in table_lower:
            return 'SRUM'
        if 'cache' in table_lower:
            return 'AmCache'
        if 'assist' in table_lower:
            return 'UserAssist'
        if 'recycle' in table_lower:
            return 'RecycleBin'
        
        return None
    
    def _infer_artifact_type_from_filename(self) -> Optional[str]:
        """
        Infer artifact type from database filename.
        
        Uses same patterns as table name inference but applied to filename.
        
        Returns:
            Inferred artifact type or None if no match
        """
        filename = Path(self.database_path).stem.lower()
        
        # Exact matches
        exact_matches = {
            'prefetch': 'Prefetch',
            'systemlog': 'SystemLog',
            'mft': 'MFT',
            'srum': 'SRUM',
            'amcache': 'AmCache',
            'userassist': 'UserAssist',
            'recyclebin': 'RecycleBin',
        }
        
        if filename in exact_matches:
            return exact_matches[filename]
        
        # Partial matches
        if 'prefetch' in filename:
            return 'Prefetch'
        if 'log' in filename or 'event' in filename:
            return 'SystemLog'
        if 'mft' in filename:
            return 'MFT'
        if 'srum' in filename:
            return 'SRUM'
        if 'cache' in filename:
            return 'AmCache'
        if 'assist' in filename:
            return 'UserAssist'
        if 'recycle' in filename:
            return 'RecycleBin'
        
        return None
    
    def _calculate_confidence(self, inference_method: str) -> str:
        """
        Calculate confidence level for artifact type inference.
        
        Levels:
        - "high": Exact table name match or metadata
        - "medium": Filename match or partial table name match
        - "low": Generic fallback
        
        Args:
            inference_method: "metadata", "table_name", "filename", "fallback"
            
        Returns:
            Confidence level string
        """
        confidence_map = {
            "metadata": "high",
            "table_name": "high",
            "filename": "medium",
            "fallback": "low"
        }
        return confidence_map.get(inference_method, "low")
    
    def validate_database(self) -> tuple[bool, List[str]]:
        """
        Comprehensive database validation.
        
        Checks:
        1. File exists and is valid SQLite database
        2. At least one non-system table exists
        3. Primary table contains at least one row
        4. Detected columns are usable (if in identifier extraction mode)
        
        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []
        
        # Check 1: File exists
        if not Path(self.database_path).exists():
            errors.append(
                f"InvalidDatabaseError: Database file not found in {self.database_path}\n"
                f"Details: File does not exist\n"
                f"Suggestion: Verify the file path is correct"
            )
            return False, errors
        
        # Check 2: Valid SQLite database
        try:
            if not self.connection:
                self.connect()
        except Exception as e:
            errors.append(
                f"InvalidDatabaseError: Not a valid SQLite database in {self.database_path}\n"
                f"Details: {str(e)}\n"
                f"Suggestion: Verify the file is a SQLite database and not corrupted"
            )
            return False, errors
        
        # Check 3: At least one non-system table exists
        try:
            primary_table = self._detect_primary_table()
        except NoDataTablesError as e:
            errors.append(str(e))
            return False, errors
        except Exception as e:
            errors.append(
                f"NoDataTablesError: Error detecting tables in {self.database_path}\n"
                f"Details: {str(e)}\n"
                f"Suggestion: Check database structure"
            )
            return False, errors
        
        # Check 4: Primary table contains at least one row
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {primary_table}")
            row_count = cursor.fetchone()[0]
            if row_count == 0:
                errors.append(
                    f"EmptyTableError: Data table '{primary_table}' contains no rows in {self.database_path}\n"
                    f"Details: Table exists but has 0 rows\n"
                    f"Suggestion: Verify the database was populated correctly"
                )
        except sqlite3.Error as e:
            errors.append(f"Error checking table row count: {str(e)}")
        
        # Check 5: If in identifier extraction mode, validate columns
        if self.config and len(errors) == 0:
            try:
                detected_columns = self.detect_columns(primary_table)
                if not detected_columns.has_names() and not detected_columns.has_paths():
                    errors.append(
                        f"SchemaDetectionError: No name or path columns detected in table '{primary_table}'\n"
                        f"Details: Cannot extract identifiers without name or path columns\n"
                        f"Suggestion: Verify the table contains columns with names like 'name', 'executable', 'path', etc."
                    )
            except Exception as e:
                errors.append(
                    f"SchemaDetectionError: Error detecting columns in {self.database_path}\n"
                    f"Details: {str(e)}\n"
                    f"Suggestion: Check table schema"
                )
        
        return len(errors) == 0, errors
    
    def get_all_records(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all records from the feather database.
        
        Args:
            filters: Optional filters to apply (e.g., {'application': 'chrome.exe'})
            
        Returns:
            List of records as dictionaries
        """
        if not self.connection:
            self.connect()
        
        query = f"SELECT * FROM {self.current_table}"
        params = []
        
        if filters:
            where_clauses = []
            for key, value in filters.items():
                where_clauses.append(f"{key} = ?")
                params.append(value)
            
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
        
        cursor = self.connection.cursor()
        cursor.execute(query, params)
        
        records = []
        for row in cursor.fetchall():
            records.append(dict(row))
        
        return records
    
    def get_records_by_application(self, application: str) -> List[Dict[str, Any]]:
        """Get records filtered by application name"""
        return self.get_all_records({'application': application})
    
    def get_records_by_time_range(self, start_time: str, end_time: str) -> List[Dict[str, Any]]:
        """
        Get records within a time range.
        
        Args:
            start_time: Start timestamp (ISO format)
            end_time: End timestamp (ISO format)
            
        Returns:
            List of records
        """
        if not self.connection:
            self.connect()
        
        query = f"""
            SELECT * FROM {self.current_table}
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp
        """
        
        cursor = self.connection.cursor()
        cursor.execute(query, (start_time, end_time))
        
        records = []
        for row in cursor.fetchall():
            records.append(dict(row))
        
        return records
    
    def get_records_by_filters(self, 
                               application: Optional[str] = None,
                               file_path: Optional[str] = None,
                               event_id: Optional[str] = None,
                               exclude_application: Optional[str] = None,
                               exclude_file_path: Optional[str] = None,
                               use_regex: bool = False) -> List[Dict[str, Any]]:
        """
        Get records with multiple advanced filters.
        
        Supports:
        - Exact matching
        - Wildcard patterns (*)
        - Regular expressions (when use_regex=True)
        - Multiple event IDs (comma-separated)
        - Exclusion filters (NOT patterns)
        
        Args:
            application: Application name filter (exact or wildcard)
            file_path: File path filter (exact, wildcard, or regex)
            event_id: Event ID filter (single or comma-separated list)
            exclude_application: Application to exclude (NOT filter)
            exclude_file_path: File path to exclude (NOT filter)
            use_regex: If True, treat file_path as regex pattern
            
        Returns:
            List of matching records
        """
        import re
        
        if not self.connection:
            self.connect()
        
        query = f"SELECT * FROM {self.current_table} WHERE 1=1"
        params = []
        
        # Application filter (exact or wildcard)
        if application:
            if '*' in application:
                query += " AND application LIKE ?"
                params.append(application.replace('*', '%'))
            else:
                query += " AND application = ?"
                params.append(application)
        
        # Application exclusion filter
        if exclude_application:
            if '*' in exclude_application:
                query += " AND application NOT LIKE ?"
                params.append(exclude_application.replace('*', '%'))
            else:
                query += " AND application != ?"
                params.append(exclude_application)
        
        # File path filter (exact, wildcard, or regex)
        if file_path:
            if use_regex:
                # Regex filtering - need to fetch all and filter in Python
                # (SQLite doesn't have native regex support)
                pass  # Will filter after query
            elif '*' in file_path:
                query += " AND file_path LIKE ?"
                params.append(file_path.replace('*', '%'))
            else:
                query += " AND file_path = ?"
                params.append(file_path)
        
        # File path exclusion filter
        if exclude_file_path:
            if '*' in exclude_file_path:
                query += " AND file_path NOT LIKE ?"
                params.append(exclude_file_path.replace('*', '%'))
            else:
                query += " AND file_path != ?"
                params.append(exclude_file_path)
        
        # Event ID filter (single or multiple)
        if event_id:
            # Handle comma-separated event IDs
            if ',' in event_id:
                event_ids = [eid.strip() for eid in event_id.split(',')]
                placeholders = ','.join(['?'] * len(event_ids))
                query += f" AND event_id IN ({placeholders})"
                params.extend(event_ids)
            else:
                query += " AND event_id = ?"
                params.append(event_id)
        
        cursor = self.connection.cursor()
        cursor.execute(query, params)
        
        records = []
        for row in cursor.fetchall():
            records.append(dict(row))
        
        # Apply regex filtering if needed (post-query)
        if file_path and use_regex:
            try:
                regex_pattern = re.compile(file_path)
                records = [r for r in records if regex_pattern.match(r.get('file_path', ''))]
            except re.error:
                # Invalid regex - return empty results
                records = []
        
        return records
    
    def get_timestamp_column(self) -> str:
        """Get the name of the timestamp column"""
        return self.metadata.get('timestamp_column', 'timestamp')
    
    def get_application_column(self) -> str:
        """Get the name of the application column"""
        return self.metadata.get('application_column', 'application')
    
    def get_record_count(self) -> int:
        """Get total number of records in the feather"""
        if not self.connection:
            self.connect()
        
        cursor = self.connection.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {self.current_table}")
        return cursor.fetchone()[0]
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
    
    # Enhanced identifier extraction methods
    
    def load_table_with_extraction(self, artifact_name: Optional[str] = None):
        """
        Load and yield rows with identifier extraction.
        
        Args:
            artifact_name: Optional artifact name (e.g., "prefetch", "srum")
            
        Yields:
            ExtractedValues for each row
        """
        if not self.config or not self.timestamp_parser:
            raise RuntimeError("Config and timestamp_parser required for identifier extraction")
        
        # Import here to avoid circular dependency
        from correlation_engine.engine.data_structures import ExtractedValues, DetectedColumns
        
        # Infer artifact name from path if not provided
        if artifact_name is None:
            artifact_name = Path(self.database_path).stem
        
        logger.info(f"Loading Feather table with extraction: {self.database_path} (artifact: {artifact_name})")
        
        try:
            if not self.connection:
                self.connect()
            
            self.current_table = artifact_name
            
            # Find the main data table (not metadata or system tables)
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Filter out metadata and system tables
            data_tables = [t for t in tables if t not in ['feather_metadata', 'sqlite_sequence', 'import_history', 'data_lineage']]
            
            if not data_tables:
                logger.warning(f"No data tables found in {self.database_path}")
                return
            
            # Use the first data table found
            data_table = data_tables[0]
            logger.info(f"Using data table: {data_table}")
            
            # Detect columns
            detected_columns = self.detect_columns(data_table)
            
            if not detected_columns.has_names() and not detected_columns.has_paths():
                logger.warning(f"No name or path columns detected in {self.database_path}")
            
            # Query all rows
            cursor.execute(f"SELECT * FROM {data_table}")
            
            row_count = 0
            for row in cursor.fetchall():
                row_count += 1
                extracted = self.extract_values(row, detected_columns, artifact_name)
                
                if extracted.has_data():
                    yield extracted
            
            logger.info(f"Loaded {row_count} rows from {self.database_path}")
        
        finally:
            # Always close the connection after loading
            self.disconnect()
    
    def detect_columns(self, table_name=None):
        """
        Detect name, path, and timestamp columns in specified table with caching.
        
        Args:
            table_name: Name of the table to inspect (defaults to self.current_table)
        
        Returns:
            DetectedColumns with identified column names
        """
        from correlation_engine.engine.data_structures import DetectedColumns
        
        # Use current_table if no table_name specified
        if table_name is None:
            table_name = self.current_table
        
        # Check cache first
        if table_name in self.schema_cache:
            logger.debug(f"Using cached schema for table '{table_name}'")
            return self.schema_cache[table_name]
        
        if not self.connection:
            raise RuntimeError("No active database connection")
        
        # Get all column names
        cursor = self.connection.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        all_columns = [row[1].lower() for row in cursor.fetchall()]  # row[1] is column name
        
        detected = DetectedColumns()
        
        # Check for manual column specification
        if self.config and hasattr(self.config, 'has_manual_name_columns') and self.config.has_manual_name_columns():
            detected.name_columns = [
                col for col in self.config.identifier_extraction.name_columns
                if col.lower() in all_columns
            ]
            missing = set(self.config.identifier_extraction.name_columns) - set(detected.name_columns)
            if missing:
                logger.warning(f"Specified name columns not found: {missing}")
        else:
            # Auto-detect name columns
            detected.name_columns = [
                col for col in all_columns
                if any(pattern in col for pattern in self.NAME_PATTERNS)
            ]
        
        if self.config and hasattr(self.config, 'has_manual_path_columns') and self.config.has_manual_path_columns():
            detected.path_columns = [
                col for col in self.config.identifier_extraction.path_columns
                if col.lower() in all_columns
            ]
            missing = set(self.config.identifier_extraction.path_columns) - set(detected.path_columns)
            if missing:
                logger.warning(f"Specified path columns not found: {missing}")
        else:
            # Auto-detect path columns
            detected.path_columns = [
                col for col in all_columns
                if any(pattern in col for pattern in self.PATH_PATTERNS)
            ]
        
        # Auto-detect timestamp columns (always auto-detect)
        detected.timestamp_columns = [
            col for col in all_columns
            if any(pattern in col for pattern in self.TIMESTAMP_PATTERNS)
        ]
        
        # Validate detected columns
        if not detected.has_names() and not detected.has_paths():
            logger.warning(f"No name or path columns detected in table '{table_name}'")
        
        logger.info(f"Detected columns in '{table_name}' - Names: {detected.name_columns}, "
                   f"Paths: {detected.path_columns}, Timestamps: {detected.timestamp_columns}")
        
        # Cache the result
        self.schema_cache[table_name] = detected
        
        return detected
    
    def extract_values(self, row: sqlite3.Row, columns, artifact_name: str):
        """
        Extract name, path, and timestamp values from a Feather row.
        
        Args:
            row: Database row
            columns: Detected columns
            artifact_name: Name of the artifact
            
        Returns:
            ExtractedValues with extracted data
        """
        from correlation_engine.engine.data_structures import ExtractedValues
        
        # Convert Row to dict for easier access
        row_dict = dict(row)
        
        extracted = ExtractedValues(
            artifact_name=artifact_name,
            table_name=self.current_table or artifact_name,
            row_id=row_dict.get('id', row_dict.get('rowid', 0))
        )
        
        # Extract names
        if self.config and self.config.identifier_extraction.extract_from_names:
            for col in columns.name_columns:
                value = row_dict.get(col)
                if value and isinstance(value, str) and value.strip():
                    extracted.names.append(value.strip())
        
        # Extract paths
        if self.config and self.config.identifier_extraction.extract_from_paths:
            for col in columns.path_columns:
                value = row_dict.get(col)
                if value and isinstance(value, str) and value.strip():
                    extracted.paths.append(value.strip())
        
        # Extract timestamps
        if self.timestamp_parser:
            for col in columns.timestamp_columns:
                value = row_dict.get(col)
                if value is not None:
                    parsed_ts = self.timestamp_parser.parse_timestamp(value)
                    if parsed_ts and self.timestamp_parser.validate_timestamp(parsed_ts):
                        extracted.timestamps.append(parsed_ts)
                    elif parsed_ts:
                        logger.warning(f"Timestamp out of valid range: {parsed_ts}")
                    else:
                        logger.warning(f"Failed to parse timestamp: {value}")
        
        return extracted
    
    def get_table_info(self) -> Dict[str, Any]:
        """
        Get information about the Feather table.
        
        Returns:
            Dictionary with table information
        """
        if not self.connection:
            self.connect()
        
        cursor = self.connection.cursor()
        
        # Get column names
        cursor.execute(f"PRAGMA table_info({self.current_table})")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {self.current_table}")
        row_count = cursor.fetchone()[0]
        
        return {
            'path': self.database_path,
            'columns': columns,
            'row_count': row_count,
            'metadata': self.metadata
        }