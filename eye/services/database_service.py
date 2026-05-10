"""
ForensicDatabaseService - Read-only database access service for EYE AI Assistant.

This service provides secure, read-only access to Crow-eye's forensic databases
with multiple layers of security enforcement:
- PRAGMA query_only = ON at connection level
- SQL keyword validation to reject write operations
- Schema introspection for LLM context
- Integration with Crow-eye's DatabaseManager

"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Import Crow-eye's DatabaseManager
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data.database_manager import DatabaseManager


class ForensicDatabaseService:
    """
    Provides read-only access to forensic databases with security enforcement.
    
    This service wraps Crow-eye's DatabaseManager and adds additional security
    layers to ensure evidence integrity during AI-assisted analysis.
    
    Security Features:
    - Read-only PRAGMA enforcement at connection level
    - SQL keyword validation (rejects DROP, UPDATE, DELETE, INSERT, ALTER, CREATE)
    - Connection-level read-only file permissions
    - Comprehensive error handling and logging
    
    Attributes:
        case_directory: Path to the case directory containing databases
        db_manager: Instance of Crow-eye's DatabaseManager
        logger: Logger instance for audit trail
    """
    
    # Forbidden SQL keywords that would modify data or perform unsafe operations
    FORBIDDEN_KEYWORDS = [
        'DROP', 'UPDATE', 'DELETE', 'INSERT', 'ALTER', 'CREATE',
        'TRUNCATE', 'REPLACE', 'ATTACH', 'DETACH', 'GRANT', 'REVOKE',
        'LOAD_EXTENSION', 'EXECUTE', 'VACUUM', 'REINDEX'
    ]
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the ForensicDatabaseService.
        
        Args:
            case_directory: Path to the case directory containing artifact databases
        """
        self.case_directory = Path(case_directory)
        self.db_manager = DatabaseManager(case_directory)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Validate case directory
        if not self.case_directory.exists():
            self.logger.warning(f"Case directory does not exist: {self.case_directory}")
    
    def get_connection(self, database_name: str) -> Optional[sqlite3.Connection]:
        """
        Get a read-only connection to a forensic database.
        
        This method enforces read-only access at multiple layers:
        1. Opens database with read-only URI mode
        2. Sets PRAGMA query_only = ON
        3. Returns connection for direct use if needed
        
        Args:
            database_name: Name of the database file (e.g., 'registry_data.db')
            
        Returns:
            Read-only SQLite connection, or None if connection fails
            
        """
        # Use DatabaseManager to establish connection
        if not self.db_manager.connect(database_name):
            self.logger.error(f"Failed to connect to database: {database_name}")
            return None
        
        # Get the connection from DatabaseManager
        conn = self.db_manager.connections.get(database_name)
        if conn is None:
            self.logger.error(f"Connection not found for database: {database_name}")
            return None
        
        try:
            # Enforce read-only mode with PRAGMA
            conn.execute("PRAGMA query_only = ON")
            self.logger.debug(f"Read-only PRAGMA enforced for: {database_name}")
            return conn
            
        except sqlite3.Error as e:
            self.logger.error(f"Error setting read-only PRAGMA for {database_name}: {e}")
            return None
    
    def execute_query(
        self,
        database_name: str,
        sql_query: str,
        params: Tuple = (),
        timeout: Optional[float] = 30.0
    ) -> Dict[str, Any]:
        """
        Execute a SQL query with read-only validation.
        
        This method validates that the query is read-only before execution:
        1. Checks for forbidden keywords (DROP, UPDATE, DELETE, etc.)
        2. Executes query through DatabaseManager
        3. Returns results with metadata
        
        Args:
            database_name: Name of the database to query
            sql_query: SQL SELECT query to execute
            params: Query parameters for parameterized queries
            timeout: Query timeout in seconds (default 30.0)
            
        Returns:
            Dictionary containing:
                - success: bool indicating if query succeeded
                - data: List of result rows (as dictionaries)
                - row_count: Number of rows returned
                - error: Error message if query failed
                
        """
        # Validate query is read-only
        if not self._is_readonly_query(sql_query):
            error_msg = (
                f"Query rejected: Contains forbidden keywords. "
                f"Only SELECT queries are allowed for evidence integrity. "
                f"Query: {sql_query[:100]}..."
            )
            self.logger.warning(error_msg)
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": error_msg
            }
        
        try:
            # Ensure database is connected
            if not self.db_manager.connect(database_name):
                error_msg = f"Failed to connect to database: {database_name}"
                return {
                    "success": False,
                    "data": [],
                    "row_count": 0,
                    "error": error_msg
                }

            # Execute query through DatabaseManager
            results = self.db_manager.execute_query(
                database_name=database_name,
                query=sql_query,
                params=params,
                timeout=timeout
            )
            
            self.logger.info(
                f"Query executed successfully on {database_name}: "
                f"{len(results)} rows returned"
            )
            
            return {
                "success": True,
                "data": results,
                "row_count": len(results),
                "error": None,
                "database_name": database_name
            }
            
        except Exception as e:
            error_msg = str(e)
            # Detect common schema errors
            if "no such column" in error_msg.lower():
                self.logger.warning(f"Schema mismatch on {database_name}: {error_msg}")
            elif "no such table" in error_msg.lower():
                self.logger.warning(f"Table missing in {database_name}: {error_msg}")
            
            self.logger.error(f"Error executing query on {database_name}: {e}")
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": f"Database Error: {error_msg}"
            }
    
    def get_schema(
        self,
        database_name: str,
        table_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get schema information for database introspection.
        
        This method provides schema information to help the LLM understand
        available data structures and generate valid SQL queries.
        
        Args:
            database_name: Name of the database
            table_name: Optional specific table name. If None, returns all tables.
            
        Returns:
            Dictionary containing:
                - success: bool indicating if schema retrieval succeeded
                - database: Database name
                - tables: List of table names (if table_name is None)
                - schema: Dict mapping table names to column lists
                - sample_data: Dict with sample rows for each table (first 3 rows)
                - row_counts: Dict with row counts for each table
                - error: Error message if retrieval failed
                
        """
        try:
            # Ensure connection exists
            if not self.db_manager.connect(database_name):
                return {
                    "success": False,
                    "database": database_name,
                    "error": f"Failed to connect to database: {database_name}"
                }
            
            # Get tables
            if table_name:
                tables = [table_name]
            else:
                tables = self.db_manager.get_tables(database_name)
            
            if not tables:
                return {
                    "success": False,
                    "database": database_name,
                    "error": f"No tables found in database: {database_name}"
                }
            
            # Build schema information
            schema = {}
            sample_data = {}
            row_counts = {}
            
            for table in tables:
                # Get columns
                columns = self.db_manager.get_columns(database_name, table)
                schema[table] = columns
                
                # Get row count
                try:
                    row_count = self.db_manager.get_row_count(database_name, table)
                    row_counts[table] = row_count
                except Exception as e:
                    self.logger.warning(f"Could not get row count for {table}: {e}")
                    row_counts[table] = 0
                
                # Get sample data (first 3 rows)
                try:
                    # Escape table name for safety
                    sample_query = f'SELECT * FROM "{table}" LIMIT 3'
                    sample_rows = self.db_manager.execute_query(
                        database_name=database_name,
                        query=sample_query
                    )
                    sample_data[table] = sample_rows
                except Exception as e:
                    self.logger.warning(f"Could not get sample data for {table}: {e}")
                    sample_data[table] = []
            
            self.logger.info(
                f"Schema retrieved for {database_name}: "
                f"{len(tables)} tables"
            )
            
            return {
                "success": True,
                "database": database_name,
                "tables": tables if not table_name else None,
                "schema": schema,
                "sample_data": sample_data,
                "row_counts": row_counts,
                "error": None
            }
            
        except Exception as e:
            error_msg = f"Schema retrieval failed: {str(e)}"
            self.logger.error(f"Error getting schema for {database_name}: {e}")
            return {
                "success": False,
                "database": database_name,
                "error": error_msg
            }
    
    def _is_readonly_query(self, sql: str) -> bool:
        """
        Validate that SQL query is read-only.
        
        Checks for forbidden keywords that would modify the database.
        Uses case-insensitive regex matching to catch variations.
        Removes string literals and comments before checking to avoid false positives/bypasses.
        
        Args:
            sql: SQL query string to validate
            
        Returns:
            True if query is read-only (safe), False if it contains forbidden keywords
            
        """
        # 1. Remove SQL comments (both -- and /* */) to prevent bypasses
        # Remove multi-line comments
        sql_clean = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # Remove single-line comments
        sql_clean = re.sub(r'--.*$', '', sql_clean, flags=re.MULTILINE)
        
        # 2. Remove string literals to avoid false positives
        # (e.g., "WHERE name LIKE '%UPDATE%'" should not trigger)
        # Remove single-quoted strings
        sql_without_strings = re.sub(r"'[^']*'", "''", sql_clean)
        # Remove double-quoted strings
        sql_without_strings = re.sub(r'"[^"]*"', '""', sql_without_strings)
        
        # Normalize SQL: convert to uppercase and remove extra whitespace
        normalized_sql = ' '.join(sql_without_strings.upper().split())
        
        # Check for forbidden keywords using word boundaries
        for keyword in self.FORBIDDEN_KEYWORDS:
            # Use word boundary regex to avoid false positives
            # (e.g., "DESCRIPTION" should not match "DELETE")
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, normalized_sql):
                self.logger.warning(
                    f"Forbidden keyword detected: {keyword} in query: {sql[:100]}..."
                )
                return False
        
        return True
    
    def discover_databases(self) -> List[Dict[str, Any]]:
        """
        Discover all available forensic databases in the case directory.
        
        Returns:
            List of dictionaries containing database information:
                - name: Database filename
                - path: Full path to database
                - category: Artifact category
                - display_name: Human-readable name
                - exists: Whether file exists
                - accessible: Whether database can be opened
                - tables: List of table names (if accessible)
                - error: Error message (if not accessible)
        """
        db_infos = self.db_manager.discover_databases()
        
        # Convert DatabaseInfo objects to dictionaries
        result = []
        for db_info in db_infos:
            result.append({
                "name": db_info.name,
                "path": str(db_info.path),
                "category": db_info.category,
                "display_name": db_info.display_name,
                "exists": db_info.exists,
                "accessible": db_info.accessible,
                "tables": db_info.tables if db_info.tables else [],
                "error": db_info.error
            })
        
        return result
    
    def close_all(self):
        """Close all open database connections."""
        self.db_manager.close_all()
        self.logger.debug("All database connections closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close all connections."""
        self.close_all()
