"""
Database Manager for Unified Database Search.

Provides low-level database access, connection management, schema introspection,
and query execution for forensic artifact databases.
"""

import sqlite3
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class TimestampMatch:
    """
    Information about a matched timestamp in a search result.
    
    Attributes:
        column_name: Name of the timestamp column
        original_value: Original value from the database
        parsed_value: Parsed datetime object
        formatted_display: Human-readable formatted string
        format_type: Detected format ('iso8601', 'unix', 'filetime', 'datetime', etc.)
    """
    column_name: str
    original_value: Any
    parsed_value: Any  # datetime.datetime
    formatted_display: str
    format_type: str


@dataclass
class SearchResult:
    """
    Encapsulates search result information from a database query.
    
    Attributes:
        database: Name of the database file (e.g., 'registry_data.db')
        table: Name of the table containing the result
        row_id: Primary key value of the matching row
        matched_columns: List of column names that matched the search term
        row_data: Complete row data as a dictionary
        match_preview: Preview string showing matched content
        matched_timestamps: List of TimestampMatch objects (for time-filtered searches)
        supports_navigation: Whether this result supports GUI navigation
        gui_tab_name: GUI tab name for navigation
    """
    database: str
    table: str
    row_id: Optional[int]
    matched_columns: List[str]
    row_data: Dict[str, Any]
    match_preview: str = ""
    matched_timestamps: Optional[List[TimestampMatch]] = None
    supports_navigation: bool = True
    gui_tab_name: Optional[str] = None
    
    def __post_init__(self):
        """Generate match preview if not provided."""
        if not self.match_preview and self.matched_columns:
            # Create preview from first matched column
            preview_parts = []
            for col in self.matched_columns[:3]:  # Limit to first 3 columns
                if col in self.row_data and self.row_data[col] is not None:
                    value = str(self.row_data[col])
                    # Truncate long values
                    if len(value) > 100:
                        value = value[:97] + "..."
                    preview_parts.append(f"{col}: {value}")
            
            self.match_preview = " | ".join(preview_parts)


@dataclass
class DatabaseInfo:
    """
    Information about a discovered database.
    
    Attributes:
        name: Database filename (e.g., 'registry_data.db')
        path: Full path to the database file
        category: Forensic category (e.g., 'Registry Evidence')
        display_name: Human-readable name for UI display
        tables: List of table names in the database
        exists: Whether the database file exists
        accessible: Whether the database can be opened
        error: Error message if database is not accessible
    """
    name: str
    path: Path
    category: str
    display_name: str
    tables: List[str] = field(default_factory=list)
    exists: bool = True
    accessible: bool = True
    error: Optional[str] = None


class DatabaseManager:
    """
    Manages SQLite database connections and provides schema introspection
    for forensic artifact databases.
    
    This class handles:
    - Database discovery in case directories
    - Connection pooling and management
    - Schema introspection (tables, columns)
    - Query execution with proper error handling
    """
    
    # Database configuration mapping
    DATABASE_CONFIG = {
        "registry_data.db": {
            "category": "Registry Evidence",
            "display_name": "Registry Data",
            "description": "Windows Registry keys and values"
        },
        "mft_data.db": {
            "category": "File System Evidence",
            "display_name": "MFT Records",
            "description": "Master File Table records"
        },
        "usn_data.db": {
            "category": "File System Evidence",
            "display_name": "USN Journal",
            "description": "Update Sequence Number journal events"
        },
        "prefetch_data.db": {
            "category": "Execution Evidence",
            "display_name": "Prefetch Files",
            "description": "Windows Prefetch execution artifacts"
        },
        "amcache_data.db": {
            "category": "Execution Evidence",
            "display_name": "AmCache",
            "description": "Application execution and installation data"
        },
        "shimcache_data.db": {
            "category": "Execution Evidence",
            "display_name": "ShimCache",
            "description": "Application Compatibility Cache"
        },
        "lnk_data.db": {
            "category": "File System Evidence",
            "display_name": "LNK Files",
            "description": "Windows shortcut files"
        },
        "jumplist_data.db": {
            "category": "Execution Evidence",
            "display_name": "Jump Lists",
            "description": "Windows Jump List artifacts"
        },
        "eventlog_data.db": {
            "category": "System Information",
            "display_name": "Event Logs",
            "description": "Windows Event Log entries"
        },
        "shellbags_data.db": {
            "category": "Registry Evidence",
            "display_name": "ShellBags",
            "description": "Folder access history from ShellBags"
        },
        "userassist_data.db": {
            "category": "Registry Evidence",
            "display_name": "UserAssist",
            "description": "Program execution tracking"
        },
        "muicache_data.db": {
            "category": "Registry Evidence",
            "display_name": "MUICache",
            "description": "Application execution cache"
        },
        "bam_dam_data.db": {
            "category": "Execution Evidence",
            "display_name": "BAM/DAM",
            "description": "Background Activity Moderator data"
        },
        "recyclebin_data.db": {
            "category": "File System Evidence",
            "display_name": "Recycle Bin",
            "description": "Deleted files information"
        },
        "srum_data.db": {
            "category": "System Resource Usage",
            "display_name": "SRUM Data",
            "description": "System Resource Usage Monitor data"
        }
    }
    
    # Alternative filenames that may contain the same artifacts
    # This aligns with UI categories and common outputs from Crow Eye collectors
    ALT_NAME_MAP: Dict[str, List[str]] = {
        "amcache_data.db": ["amcache.db", "Log_Claw.db"],
        "shimcache_data.db": ["shimcache.db", "Log_Claw.db"],
        "lnk_data.db": ["LnkDB.db", "Log_Claw.db"],
        "jumplist_data.db": ["Log_Claw.db"],
        "mft_data.db": ["mft_claw_analysis.db"],
        "usn_data.db": ["USN_journal.db"],
        "recyclebin_data.db": ["recyclebin_analysis.db"],
        "eventlog_data.db": ["Log_Claw.db"],
        "registry_data.db": ["Log_Claw.db"],
        "shellbags_data.db": ["Log_Claw.db"],
        "userassist_data.db": ["Log_Claw.db"],
        "muicache_data.db": ["Log_Claw.db"],
        "bam_dam_data.db": ["Log_Claw.db"],
    }

    # Table signatures used to detect artifacts when they are stored as tables
    # inside a consolidated/aggregator database (e.g., Log_Claw.db)
    TABLE_SIGNATURES: Dict[str, List[str]] = {
        # Execution Evidence
        "amcache_data.db": ["amcache", "amcache_entries", "amcache_programs"],
        "shimcache_data.db": ["shimcache", "shim_cache", "appcompat"],
        "lnk_data.db": ["lnk", "shortcut", "lnk_entries"],
        "jumplist_data.db": ["jumplist", "jump_list", "dest_list"],
        "prefetch_data.db": ["prefetch", "prefetch_files"],
        "userassist_data.db": ["userassist", "user_assist"],
        "bam_dam_data.db": ["bam", "dam", "background_activity"],

        # Registry Evidence
        "registry_data.db": ["registry_", "reg_", "hive_"],
        "muicache_data.db": ["muicache"],
        "shellbags_data.db": ["shellbags", "shell_bags"],

        # File System Evidence
        "mft_data.db": ["mft_", "mft_records"],
        "usn_data.db": ["usn_", "usn_journal"],
        "recyclebin_data.db": ["recyclebin", "recycle_bin", "$recycle"],

        # System Information
        "eventlog_data.db": ["eventlog", "event_log", "windows_event"],
        
        # System Resource Usage
        "srum_data.db": ["srum_", "srum_application", "srum_network", "srum_energy"],
    }
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the DatabaseManager.
        
        Args:
            case_directory: Path to the case directory containing artifact databases
        """
        self.case_directory = Path(case_directory)
        self.connections: Dict[str, sqlite3.Connection] = {}
        self.database_schemas: Dict[str, Dict[str, List[str]]] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        # Map logical database names (e.g., 'amcache_data.db') to their actual
        # file paths when artifacts are consolidated into aggregator databases.
        # This prevents false "Missing" statuses when the data exists as tables.
        self.resolved_paths: Dict[str, Path] = {}
        
        # Validate case directory
        if not self.case_directory.exists():
            self.logger.warning(f"Case directory does not exist: {self.case_directory}")
    
    def discover_databases(self) -> List[DatabaseInfo]:
        """
        Discover all artifact databases in the case directory.
        
        Scans the case directory for known artifact database files and
        returns information about each discovered database.
        
        Returns:
            List of DatabaseInfo objects for discovered databases
        """
        discovered = []
        
        # Pre-scan the directory for any candidate SQLite databases to support
        # consolidated storage (e.g., Log_Claw.db). We scan shallow and avoid
        # assumptions about fixed filenames.
        candidate_dbs: List[Path] = []
        try:
            # Search within the provided case directory only; users often point
            # this directly to the Target_Artifacts directory.
            candidate_dbs = list(self.case_directory.glob("*.db"))
        except Exception:
            candidate_dbs = []

        for db_name, config in self.DATABASE_CONFIG.items():
            db_path = self.case_directory / db_name
            
            db_info = DatabaseInfo(
                name=db_name,
                path=db_path,
                category=config["category"],
                display_name=config["display_name"],
                exists=db_path.exists()
            )
            
            # Try to open and get tables if database exists
            # If the configured file doesn't exist, attempt to resolve to an
            # alternative filename or aggregator database that contains the
            # expected tables. This addresses cases where artifacts are stored
            # as tables in a consolidated DB and prevents false "Missing".
            if not db_info.exists:
                resolved_path: Optional[Path] = None
                # Try alternative filenames first
                for alt_name in self.ALT_NAME_MAP.get(db_name, []):
                    alt_path = self.case_directory / alt_name
                    if alt_path.exists():
                        resolved_path = alt_path
                        break
                # If still unresolved, inspect candidate DBs and match by table signatures
                if resolved_path is None and candidate_dbs:
                    signatures = self.TABLE_SIGNATURES.get(db_name, [])
                    for cand in candidate_dbs:
                        try:
                            # Open read-only and check table names
                            uri = f"file:{cand}?mode=ro"
                            conn = sqlite3.connect(uri, uri=True, timeout=10.0)
                            conn.row_factory = sqlite3.Row
                            cur = conn.cursor()
                            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                            table_names = [r['name'].lower() for r in cur.fetchall()]
                            conn.close()

                            # If any signature matches, consider this a resolved path
                            if any(any(tn.startswith(sig) or sig in tn for tn in table_names) for sig in signatures):
                                resolved_path = cand
                                break
                        except Exception:
                            # Ignore inaccessible candidates and continue
                            try:
                                conn.close()
                            except Exception:
                                pass

                if resolved_path is not None:
                    # Mark as existing via resolved path and cache mapping
                    db_info.exists = True
                    db_info.path = resolved_path
                    self.resolved_paths[db_name] = resolved_path
                    # Note: accessible/tables will be determined below

            # Try to open and get tables if database exists (resolved or actual)
            if db_info.exists:
                try:
                    # When resolved, connect() will use the mapped path
                    tables = self.get_tables(db_name)
                    db_info.tables = tables
                    db_info.accessible = True
                    self.logger.debug(f"Database {db_name} is accessible with {len(tables)} tables")
                except sqlite3.DatabaseError as e:
                    # Database file is corrupted or invalid format
                    db_info.accessible = False
                    db_info.error = f"Database corrupted or invalid format: {str(e)}"
                    self.logger.warning(
                        f"Database {db_name} is corrupted or has invalid format: {e}"
                    )
                except sqlite3.OperationalError as e:
                    # Database is locked or has operational issues
                    db_info.accessible = False
                    error_msg = str(e).lower()
                    if 'locked' in error_msg:
                        db_info.error = f"Database is locked by another process: {str(e)}"
                        self.logger.warning(f"Database {db_name} is locked: {e}")
                    elif 'disk i/o error' in error_msg:
                        db_info.error = f"Disk I/O error accessing database: {str(e)}"
                        self.logger.error(f"Disk I/O error for {db_name}: {e}")
                    else:
                        db_info.error = f"Operational error: {str(e)}"
                        self.logger.warning(f"Operational error for {db_name}: {e}")
                except PermissionError as e:
                    # Permission denied accessing database
                    db_info.accessible = False
                    db_info.error = f"Permission denied: {str(e)}"
                    self.logger.error(f"Permission denied accessing {db_name}: {e}")
                except Exception as e:
                    # Catch-all for unexpected errors
                    db_info.accessible = False
                    db_info.error = f"Unexpected error: {str(e)}"
                    self.logger.error(
                        f"Unexpected error accessing {db_name}: {e}",
                        exc_info=True
                    )
            else:
                db_info.accessible = False
                db_info.error = "Database file not found"
                self.logger.debug(f"Database {db_name} not found in case directory")
            
            discovered.append(db_info)
        
        accessible_count = len([d for d in discovered if d.exists and d.accessible])
        exists_count = len([d for d in discovered if d.exists])
        
        self.logger.info(
            f"Discovered {exists_count} databases in {self.case_directory}, "
            f"{accessible_count} accessible"
        )
        
        # Log warning if some databases exist but are not accessible
        inaccessible = [d for d in discovered if d.exists and not d.accessible]
        if inaccessible:
            self.logger.warning(
                f"{len(inaccessible)} database(s) exist but are not accessible: "
                f"{', '.join([d.name for d in inaccessible])}"
            )
        
        return discovered
    
    def connect(self, database_name: str) -> bool:
        """
        Open a connection to a database.
        
        Args:
            database_name: Name of the database file (e.g., 'registry_data.db')
            
        Returns:
            True if connection was successful, False otherwise
        """
        # Return True if already connected
        if database_name in self.connections:
            return True
        
        # Resolve path: prefer a previously discovered mapping when artifacts
        # are stored in a consolidated DB. Otherwise fall back to the standard
        # case_directory/database_name.
        db_path = self.resolved_paths.get(database_name, self.case_directory / database_name)
        
        if not db_path.exists():
            self.logger.error(f"Database file not found: {db_path}")
            return False
        
        try:
            # Open in read-only mode with URI
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30.0)
            
            # Return rows as dictionaries
            conn.row_factory = sqlite3.Row
            
            # Apply performance optimizations
            conn.execute("PRAGMA cache_size = 10000")
            conn.execute("PRAGMA temp_store = MEMORY")
            
            self.connections[database_name] = conn
            self.logger.debug(f"Connected to database: {database_name}")
            return True
            
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database corrupted or invalid format for {database_name}: {e}")
            return False
        except sqlite3.OperationalError as e:
            self.logger.error(f"Database locked or inaccessible for {database_name}: {e}")
            return False
        except PermissionError as e:
            self.logger.error(f"Permission denied accessing {database_name}: {e}")
            return False
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to {database_name}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error connecting to {database_name}: {e}", exc_info=True)
            return False
    
    def disconnect(self, database_name: str):
        """
        Close a database connection.
        
        Args:
            database_name: Name of the database to disconnect
        """
        if database_name in self.connections:
            try:
                self.connections[database_name].close()
                del self.connections[database_name]
                self.logger.debug(f"Disconnected from database: {database_name}")
            except sqlite3.Error as e:
                self.logger.error(f"Error disconnecting from {database_name}: {e}")
    
    def close_all(self):
        """Close all open database connections."""
        for db_name in list(self.connections.keys()):
            self.disconnect(db_name)
        self.logger.debug("Closed all database connections")
    
    def execute_query(
        self,
        database_name: str,
        query: str,
        params: Tuple = (),
        timeout: Optional[float] = 30.0
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return results with timeout support.
        
        Args:
            database_name: Name of the database to query
            query: SQL query to execute
            params: Query parameters for parameterized queries
            timeout: Query timeout in seconds (default 30.0)
            
        Returns:
            List of dictionaries representing query results
        """
        # Ensure connection exists
        if not self.connect(database_name):
            self.logger.warning(f"Cannot execute query - connection failed for {database_name}")
            return []
        
        try:
            conn = self.connections[database_name]

            # Set timeout and ensure no cache spill to avoid stale reads
            if timeout is not None:
                conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
            conn.execute("PRAGMA cache_spill=0")

            cursor = conn.cursor()
            try:
                cursor.execute(query, params)

                # Convert Row objects to dictionaries
                columns = [column[0] for column in cursor.description] if cursor.description else []
                results = []
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))

                return results
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
            
        except sqlite3.DatabaseError as e:
            self.logger.error(
                f"Database error executing query on {database_name}: {e}\nQuery: {query}"
            )
            return []
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if 'timeout' in error_msg or 'locked' in error_msg:
                self.logger.error(
                    f"Query timeout or database locked for {database_name}: {e}"
                )
            else:
                self.logger.error(
                    f"Operational error executing query on {database_name}: {e}\nQuery: {query}"
                )
            return []
        except sqlite3.Error as e:
            self.logger.error(
                f"Error executing query on {database_name}: {e}\nQuery: {query}"
            )
            return []
        except Exception as e:
            self.logger.error(
                f"Unexpected error executing query on {database_name}: {e}\nQuery: {query}",
                exc_info=True
            )
            return []
    
    def get_tables(self, database_name: str) -> List[str]:
        """
        Get list of all tables in a database.
        
        Args:
            database_name: Name of the database
            
        Returns:
            List of table names
            
        Raises:
            Exception: If database cannot be queried (for error handling in discover_databases)
        """
        # Ensure connection exists - this will raise exceptions if database is corrupted
        if not self.connect(database_name):
            raise sqlite3.DatabaseError(f"Cannot connect to {database_name}")
        
        query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        
        # For schema introspection, we want to propagate errors
        # so discover_databases can properly mark databases as inaccessible
        try:
            conn = self.connections[database_name]
            cursor = conn.cursor()
            try:
                cursor.execute(query)
                results = cursor.fetchall()
                return [row['name'] for row in results]
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
        except Exception as e:
            # Re-raise the exception so discover_databases can catch it
            raise
    
    def get_columns(self, database_name: str, table_name: str) -> List[str]:
        """
        Get list of column names for a table.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table
            
        Returns:
            List of column names
        """
        query = f"PRAGMA table_info({table_name})"
        results = self.execute_query(database_name, query)
        return [row['name'] for row in results]
    
    def get_text_columns(self, database_name: str, table_name: str) -> List[str]:
        """
        Get list of text-based columns suitable for searching.
        
        Filters out binary and numeric-only columns to focus on searchable text.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table
            
        Returns:
            List of text column names
        """
        query = f"PRAGMA table_info({table_name})"
        results = self.execute_query(database_name, query)
        
        text_columns = []
        for row in results:
            col_type = row['type'].upper()
            # Include TEXT, VARCHAR, CHAR, and columns without explicit type
            if (col_type.startswith('TEXT') or 
                col_type.startswith('VARCHAR') or 
                col_type.startswith('CHAR') or
                col_type == ''):
                text_columns.append(row['name'])
        
        return text_columns
    
    def get_database_schema(self, database_name: str) -> Dict[str, List[str]]:
        """
        Get complete schema information for a database.
        
        Returns a dictionary mapping table names to their column lists.
        Results are cached for performance.
        
        Args:
            database_name: Name of the database
            
        Returns:
            Dictionary mapping table names to column name lists
        """
        # Return cached schema if available
        if database_name in self.database_schemas:
            return self.database_schemas[database_name]
        
        schema = {}
        tables = self.get_tables(database_name)
        
        for table in tables:
            columns = self.get_columns(database_name, table)
            schema[table] = columns
        
        # Cache the schema
        self.database_schemas[database_name] = schema
        
        self.logger.debug(
            f"Retrieved schema for {database_name}: {len(tables)} tables"
        )
        
        return schema
    
    def table_exists(self, database_name: str, table_name: str) -> bool:
        """
        Check if a table exists in a database.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table to check
            
        Returns:
            True if table exists, False otherwise
        """
        query = """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """
        results = self.execute_query(database_name, query, (table_name,))
        return len(results) > 0
    
    def get_row_count(self, database_name: str, table_name: str) -> int:
        """
        Get the total number of rows in a table.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table
            
        Returns:
            Number of rows in the table
        """
        query = f"SELECT COUNT(*) as count FROM {table_name}"
        results = self.execute_query(database_name, query)
        
        if results and 'count' in results[0]:
            return results[0]['count']
        return 0
    
    def get_indexes(self, database_name: str, table_name: str) -> List[Dict[str, Any]]:
        """
        Get list of indexes for a table.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table
            
        Returns:
            List of dictionaries containing index information
        """
        query = f"PRAGMA index_list({table_name})"
        return self.execute_query(database_name, query)
    
    def get_index_columns(self, database_name: str, index_name: str) -> List[str]:
        """
        Get list of columns in an index.
        
        Args:
            database_name: Name of the database
            index_name: Name of the index
            
        Returns:
            List of column names in the index
        """
        query = f"PRAGMA index_info({index_name})"
        results = self.execute_query(database_name, query)
        return [row['name'] for row in results]
    
    def has_index_on_column(self, database_name: str, table_name: str, column_name: str) -> bool:
        """
        Check if a specific column has an index.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table
            column_name: Name of the column to check
            
        Returns:
            True if column has an index, False otherwise
        """
        try:
            indexes = self.get_indexes(database_name, table_name)
            
            for index in indexes:
                index_name = index.get('name', '')
                if not index_name:
                    continue
                
                # Get columns in this index
                index_columns = self.get_index_columns(database_name, index_name)
                
                # Check if our column is in this index
                if column_name in index_columns:
                    self.logger.debug(f"Found index '{index_name}' on column '{column_name}' in {table_name}")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Error checking index for {column_name} in {table_name}: {e}")
            return False
    
    def explain_query(self, database_name: str, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """
        Get query execution plan using EXPLAIN QUERY PLAN.
        
        Args:
            database_name: Name of the database
            query: SQL query to explain
            params: Query parameters
            
        Returns:
            List of dictionaries containing query plan information
        """
        explain_query = f"EXPLAIN QUERY PLAN {query}"
        return self.execute_query(database_name, explain_query, params)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure all connections are closed."""
        self.close_all()
