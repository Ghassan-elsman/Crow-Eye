"""
Index Manager for optimizing database search performance.
Manages creation, deletion, and analysis of database indexes.
"""

import sqlite3
import logging
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


class IndexManager:
    """
    Manages database indexes for optimal search performance.
    Provides methods to create, drop, and analyze indexes on SQLite databases.
    """
    
    def __init__(self, connection: Optional[sqlite3.Connection] = None):
        """
        Initialize the IndexManager.
        
        Args:
            connection: Optional SQLite connection. If None, must be set later.
        """
        self.connection = connection
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def set_connection(self, connection: sqlite3.Connection) -> None:
        """
        Set or update the database connection.
        
        Args:
            connection: SQLite connection to use for index operations.
        """
        self.connection = connection
    
    def ensure_default_indexes(self) -> Dict[str, bool]:
        """
        Ensure default indexes exist for common search patterns.
        Creates indexes for MFT, USN, and correlated data tables if they exist.
        
        Returns:
            Dict mapping index names to creation status (True if created/exists, False if failed).
        """
        if not self.connection:
            self.logger.error("No database connection. Set connection first.")
            return {}
        
        # Get available tables
        available_tables = self._get_table_names()
        
        # Define default indexes for each table type
        index_specs = [
            # MFT databases
            {"table": "mft_records", "columns": ["record_number"], "name": "idx_mft_records_record_number"},
            {"table": "mft_standard_info", "columns": ["record_number"], "name": "idx_mft_si_record_number"},
            {"table": "mft_file_names", "columns": ["record_number"], "name": "idx_mft_fn_record_number"},
            {"table": "mft_file_names", "columns": ["parent_record_number"], "name": "idx_mft_fn_parent_record_number"},
            {"table": "mft_file_names", "columns": ["file_name"], "name": "idx_mft_fn_file_name"},
            {"table": "mft_file_names", "columns": ["full_path"], "name": "idx_mft_fn_full_path"},
            {"table": "mft_data_attributes", "columns": ["record_number"], "name": "idx_mft_da_record_number"},
            
            # USN journal
            {"table": "journal_events", "columns": ["usn"], "name": "idx_usn_usn"},
            {"table": "journal_events", "columns": ["frn"], "name": "idx_usn_frn"},
            {"table": "journal_events", "columns": ["parent_frn"], "name": "idx_usn_parent_frn"},
            {"table": "journal_events", "columns": ["timestamp"], "name": "idx_usn_timestamp"},
            {"table": "journal_events", "columns": ["filename"], "name": "idx_usn_filename"},
            {"table": "journal_events", "columns": ["reason"], "name": "idx_usn_reason"},
            
            # Correlated database
            {"table": "mft_usn_correlated", "columns": ["mft_record_number"], "name": "idx_corr_mft_record_number"},
            {"table": "mft_usn_correlated", "columns": ["usn_event_id"], "name": "idx_corr_usn_event_id"},
            {"table": "mft_usn_correlated", "columns": ["reconstructed_path"], "name": "idx_corr_reconstructed_path"},
            {"table": "mft_usn_correlated", "columns": ["timestamp"], "name": "idx_corr_timestamp"},
        ]
        
        results = {}
        
        for spec in index_specs:
            table = spec["table"]
            
            # Only create index if table exists
            if table in available_tables:
                name = spec["name"]
                columns = spec["columns"]
                success = self.create_index(
                    table_name=table,
                    columns=columns,
                    index_name=name,
                    unique=False
                )
                results[name] = success
                
                if success:
                    self.logger.debug(f"Ensured index: {name}")
            else:
                self.logger.debug(f"Skipping index for non-existent table: {table}")
        
        return results
    
    def create_index(
        self,
        table_name: str,
        columns: List[str],
        index_name: Optional[str] = None,
        unique: bool = False
    ) -> bool:
        """
        Create an index on specified columns if it doesn't already exist.
        
        Args:
            table_name: Name of the table.
            columns: List of column names to include in the index.
            index_name: Optional explicit index name. If None, generate one.
            unique: Whether to create a UNIQUE index.
            
        Returns:
            True if index exists or was created successfully, False otherwise.
        """
        if not self.connection:
            self.logger.error("No database connection. Set connection first.")
            return False
        
        if not columns:
            self.logger.error("No columns specified for index creation.")
            return False
        
        # Generate index name if not provided
        if not index_name:
            cols_key = "_".join(columns)
            index_name = f"idx_{table_name}_{cols_key}"
        
        try:
            # Check if index already exists
            if self._index_exists(index_name):
                self.logger.debug(f"Index '{index_name}' already exists.")
                return True
            
            # Create the index
            cursor = self.connection.cursor()
            unique_sql = "UNIQUE " if unique else ""
            columns_str = ", ".join(columns)
            
            sql = f"CREATE {unique_sql}INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns_str})"
            cursor.execute(sql)
            self.connection.commit()
            
            self.logger.info(f"Created index '{index_name}' on {table_name}({columns_str})")
            return True
            
        except sqlite3.Error as e:
            self.logger.error(f"Error creating index '{index_name}' on {table_name}: {e}")
            return False
    
    def drop_index(self, index_name: str) -> bool:
        """
        Drop an existing index.
        
        Args:
            index_name: Name of the index to drop.
            
        Returns:
            True if index was dropped successfully, False otherwise.
        """
        if not self.connection:
            self.logger.error("No database connection. Set connection first.")
            return False
        
        try:
            # Check if index exists
            if not self._index_exists(index_name):
                self.logger.warning(f"Index '{index_name}' does not exist.")
                return False
            
            cursor = self.connection.cursor()
            cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
            self.connection.commit()
            
            self.logger.info(f"Dropped index '{index_name}'")
            return True
            
        except sqlite3.Error as e:
            self.logger.error(f"Error dropping index '{index_name}': {e}")
            return False
    
    def list_indexes(self, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all indexes, optionally filtered by table.
        
        Args:
            table_name: Optional table name to filter indexes.
            
        Returns:
            List of dicts with keys: name, table, sql, unique
        """
        if not self.connection:
            self.logger.error("No database connection. Set connection first.")
            return []
        
        try:
            cursor = self.connection.cursor()
            
            if table_name:
                # Get indexes for specific table
                cursor.execute(
                    """
                    SELECT name, tbl_name, sql 
                    FROM sqlite_master 
                    WHERE type='index' AND tbl_name=?
                    ORDER BY name
                    """,
                    (table_name,)
                )
            else:
                # Get all indexes
                cursor.execute(
                    """
                    SELECT name, tbl_name, sql 
                    FROM sqlite_master 
                    WHERE type='index'
                    ORDER BY tbl_name, name
                    """
                )
            
            indexes = []
            for row in cursor.fetchall():
                index_info = {
                    'name': row[0],
                    'table': row[1],
                    'sql': row[2],
                    'unique': 'UNIQUE' in (row[2] or '').upper() if row[2] else False
                }
                indexes.append(index_info)
            
            return indexes
            
        except sqlite3.Error as e:
            self.logger.error(f"Error listing indexes: {e}")
            return []
    
    def analyze_query_performance(
        self,
        query: str,
        params: Tuple = ()
    ) -> Dict[str, Any]:
        """
        Analyze query performance and suggest indexes.
        Uses EXPLAIN QUERY PLAN to understand query execution.
        
        Args:
            query: SQL query to analyze.
            params: Parameters for the query.
            
        Returns:
            Dictionary containing:
            - 'query_plan': List of query plan steps
            - 'uses_index': Whether the query uses any indexes
            - 'full_scan': Whether the query performs a full table scan
            - 'suggested_indexes': List of suggested index improvements
        """
        if not self.connection:
            self.logger.error("No database connection. Set connection first.")
            return {
                'query_plan': [],
                'uses_index': False,
                'full_scan': False,
                'suggested_indexes': []
            }
        
        try:
            cursor = self.connection.cursor()
            
            # Get query plan
            explain_query = f"EXPLAIN QUERY PLAN {query}"
            cursor.execute(explain_query, params)
            
            query_plan = []
            uses_index = False
            full_scan = False
            
            for row in cursor.fetchall():
                plan_step = {
                    'id': row[0],
                    'parent': row[1],
                    'detail': row[3] if len(row) > 3 else row[2]
                }
                query_plan.append(plan_step)
                
                detail_upper = plan_step['detail'].upper()
                if 'USING INDEX' in detail_upper or 'SEARCH' in detail_upper:
                    uses_index = True
                if 'SCAN' in detail_upper and 'USING INDEX' not in detail_upper:
                    full_scan = True
            
            # Generate suggestions based on query plan
            suggested_indexes = []
            if full_scan and not uses_index:
                suggested_indexes.append(
                    "Query performs full table scan. Consider adding indexes on columns used in WHERE, JOIN, or ORDER BY clauses."
                )
            
            return {
                'query_plan': query_plan,
                'uses_index': uses_index,
                'full_scan': full_scan,
                'suggested_indexes': suggested_indexes
            }
            
        except sqlite3.Error as e:
            self.logger.error(f"Error analyzing query performance: {e}")
            return {
                'query_plan': [],
                'uses_index': False,
                'full_scan': False,
                'suggested_indexes': []
            }
    
    def get_index_info(self, index_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific index.
        
        Args:
            index_name: Name of the index.
            
        Returns:
            Dictionary with index details or None if not found.
        """
        if not self.connection:
            self.logger.error("No database connection. Set connection first.")
            return None
        
        try:
            cursor = self.connection.cursor()
            
            # Get index information from sqlite_master
            cursor.execute(
                """
                SELECT name, tbl_name, sql 
                FROM sqlite_master 
                WHERE type='index' AND name=?
                """,
                (index_name,)
            )
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Get index columns using PRAGMA
            cursor.execute(f"PRAGMA index_info({index_name})")
            columns = [col[2] for col in cursor.fetchall()]
            
            return {
                'name': row[0],
                'table': row[1],
                'sql': row[2],
                'columns': columns,
                'unique': 'UNIQUE' in (row[2] or '').upper() if row[2] else False
            }
            
        except sqlite3.Error as e:
            self.logger.error(f"Error getting index info for '{index_name}': {e}")
            return None
    
    def _index_exists(self, index_name: str) -> bool:
        """
        Check if an index exists in the database.
        
        Args:
            index_name: Name of the index to check.
            
        Returns:
            True if index exists, False otherwise.
        """
        if not self.connection:
            return False
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,)
            )
            return cursor.fetchone() is not None
            
        except sqlite3.Error as e:
            self.logger.error(f"Error checking if index exists: {e}")
            return False
    
    def _get_table_names(self) -> List[str]:
        """
        Get a list of all tables in the database.
        
        Returns:
            List of table names.
        """
        if not self.connection:
            return []
        
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return [row[0] for row in cursor.fetchall()]
            
        except sqlite3.Error as e:
            self.logger.error(f"Error getting table names: {e}")
            return []
