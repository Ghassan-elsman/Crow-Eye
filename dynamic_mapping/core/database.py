"""
Database management module for the Dynamic Linking Intelligence Engine.

This module provides the DatabaseManager class for handling all database operations
including initialization, schema creation, and connection management.
"""

import os
import sqlite3
from typing import Optional


class DatabaseManager:
    """
    Manages the Crow_Intelligence.db database for the Dynamic Linking Intelligence Engine.
    
    This class handles all database operations including:
    - Creating/opening the intelligence database
    - Initializing the required schema (Mapping, CustomRules, GatherHistory tables)
    - Managing database connections
    - Providing proper cleanup and error handling
    """
    
    def __init__(self, case_directory: str):
        """
        Initialize the database manager for a case.
        
        Args:
            case_directory: Path to the active case directory where Crow_Intelligence.db will be stored
        """
        self.case_directory = case_directory
        self.intelligence_db_path = os.path.join(case_directory, "Crow_Intelligence.db")
        self._connection: Optional[sqlite3.Connection] = None
        self._is_initialized = False
    
    def ensure_db(self) -> bool:
        """
        Ensure the intelligence database exists and is properly initialized.
        
        Creates the database file if it doesn't exist and initializes all required tables
        and indexes if they are not present.
        
        Returns:
            True if database is ready and initialized successfully, False otherwise
        """
        try:
            # Create case directory if it doesn't exist
            if not os.path.exists(self.case_directory):
                os.makedirs(self.case_directory, exist_ok=True)
            
            # Connect to database (creates if doesn't exist)
            self._connection = sqlite3.connect(self.intelligence_db_path)
            self._connection.row_factory = sqlite3.Row
            cursor = self._connection.cursor()
            
            # Create Mapping table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    value TEXT NOT NULL UNIQUE,
                    key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for Mapping table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mapping_value ON Mapping(value)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mapping_source ON Mapping(source)")
            
            # Drop old category index if it exists (from previous schema)
            cursor.execute("DROP INDEX IF EXISTS idx_mapping_category")
            
            # Create CustomRules table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS CustomRules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    description TEXT,
                    db_name TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    value_column TEXT NOT NULL,
                    key_column TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for CustomRules table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_customrules_name ON CustomRules(name)")
            
            # Create GatherHistory table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS GatherHistory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_name TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    mappings_count INTEGER DEFAULT 0,
                    execution_time_ms INTEGER,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for GatherHistory table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_gatherhistory_rule ON GatherHistory(rule_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_gatherhistory_executed ON GatherHistory(executed_at)")
            
            self._connection.commit()
            self._is_initialized = True
            return True
            
        except Exception:
            self._is_initialized = False
            return False
    
    def close(self) -> bool:
        """
        Properly close the database connection.
        
        Returns:
            True if connection was closed successfully, False otherwise
        """
        if self._connection:
            try:
                self._connection.close()
                self._connection = None
                self._is_initialized = False
                return True
            except Exception:
                return False
        return True
    
    @property
    def connection(self) -> Optional[sqlite3.Connection]:
        """
        Get the current database connection.
        
        Returns:
            The sqlite3.Connection object if initialized, None otherwise
        """
        return self._connection
    
    @property
    def is_initialized(self) -> bool:
        """
        Check if the database is initialized.
        
        Returns:
            True if the database is initialized and ready for use
        """
        return self._is_initialized
    
    def get_db_path(self) -> str:
        """
        Get the path to the intelligence database.
        
        Returns:
            Full path to Crow_Intelligence.db
        """
        return self.intelligence_db_path
