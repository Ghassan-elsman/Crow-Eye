import sqlite3
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path

class BaseDataLoader:
    """
    Base class for data loading operations with common database functionality.
    Handles database connections, query execution, and error handling.
    """
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """
        Initialize the data loader with an optional database path.
        
        Args:
            db_path: Path to the SQLite database file. If None, must be set later.
        """
        self.db_path = Path(db_path) if db_path else None
        self.connection = None
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def connect(self, db_path: Optional[Union[str, Path]] = None) -> bool:
        """
        Establish a connection to the database.
        
        Args:
            db_path: Optional path to override the instance db_path.
            
        Returns:
            bool: True if connection was successful, False otherwise.
        """
        if db_path:
            self.db_path = Path(db_path)
            
        if not self.db_path or not self.db_path.exists():
            self.logger.error(f"Database file not found: {self.db_path}")
            return False
            
        try:
            self.connection = sqlite3.connect(str(self.db_path))
            self.connection.row_factory = sqlite3.Row  # Return rows as dictionaries
            self.logger.debug(f"Connected to database: {self.db_path}")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to database {self.db_path}: {str(e)}")
            return False
            
    def disconnect(self):
        """Close the database connection if it's open."""
        if self.connection:
            self.connection.close()
            self.connection = None
            self.logger.debug("Database connection closed")
            
    def execute_query(self, query: str, params: Tuple = (), fetch: bool = True) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return the results.
        
        Args:
            query: SQL query to execute
            params: Parameters for the query
            fetch: Whether to fetch results (True for SELECT, False for INSERT/UPDATE)
            
        Returns:
            List of dictionaries representing the query results
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return []
            
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            
            if fetch:
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            else:
                self.connection.commit()
                return []
                
        except sqlite3.Error as e:
            self.logger.error(f"Error executing query: {str(e)}\nQuery: {query}")
            return []
            
    def get_table_names(self) -> List[str]:
        """Get a list of all tables in the database."""
        if not self.connection:
            return []
            
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            self.logger.error(f"Error getting table names: {str(e)}")
            return []
            
    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        if not self.connection:
            return False
            
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            self.logger.error(f"Error checking if table exists: {str(e)}")
            return False

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure connection is closed."""
        self.disconnect()
