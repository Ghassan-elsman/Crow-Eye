"""
Database Initializer for Crow Eye
Handles database connection initialization with automatic index creation.
"""

import sqlite3
import logging
from typing import Optional
from pathlib import Path

from data.index_manager import IndexManager
from config.data_config import DataConfig


class DatabaseInitializer:
    """
    Initializes database connections with optional index creation and optimization.
    """
    
    # SQLite PRAGMA settings for optimal performance
    PRAGMAS = {
        'journal_mode': 'WAL',
        'synchronous': 'NORMAL',
        'cache_size': -64000,  # 64MB cache
        'temp_store': 'MEMORY',
        'mmap_size': 268435456,  # 256MB memory-mapped I/O
        'page_size': 4096,
        'busy_timeout': 30000
    }
    
    def __init__(self, config: Optional[DataConfig] = None):
        """
        Initialize the database initializer.
        
        Args:
            config: Optional DataConfig instance for configuration settings
        """
        self.config = config or DataConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def initialize_database(
        self,
        db_path: str,
        create_indexes: Optional[bool] = None,
        progress_callback: Optional[callable] = None
    ) -> Optional[sqlite3.Connection]:
        """
        Initialize a database connection with optimizations and indexes.
        
        Args:
            db_path: Path to the SQLite database file
            create_indexes: Whether to create default indexes (None = use config)
            progress_callback: Optional callback function for progress updates
            
        Returns:
            SQLite connection or None if initialization failed
        """
        try:
            # Check if database exists
            if not Path(db_path).exists():
                self.logger.error(f"Database file not found: {db_path}")
                return None
            
            # Connect to database
            self.logger.info(f"Connecting to database: {db_path}")
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            
            # Apply PRAGMA settings
            self._apply_pragmas(connection)
            
            # Determine if we should create indexes
            should_create_indexes = create_indexes
            if should_create_indexes is None:
                should_create_indexes = self.config.get_auto_create_indexes()
            
            # Create indexes if enabled
            if should_create_indexes:
                self._create_default_indexes(connection, progress_callback)
            
            # Analyze database if configured
            if self.config.get_analyze_on_startup():
                self._analyze_database(connection, progress_callback)
            
            self.logger.info(f"Database initialized successfully: {db_path}")
            return connection
            
        except sqlite3.Error as e:
            self.logger.error(f"Error initializing database {db_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error initializing database {db_path}: {e}")
            return None
    
    def _apply_pragmas(self, connection: sqlite3.Connection) -> None:
        """
        Apply PRAGMA settings to optimize database performance.
        
        Args:
            connection: SQLite connection
        """
        cursor = connection.cursor()
        
        for pragma, value in self.PRAGMAS.items():
            try:
                cursor.execute(f"PRAGMA {pragma} = {value}")
                self.logger.debug(f"Applied PRAGMA {pragma} = {value}")
            except sqlite3.Error as e:
                self.logger.warning(f"Failed to apply PRAGMA {pragma}: {e}")
        
        connection.commit()
    
    def _create_default_indexes(
        self,
        connection: sqlite3.Connection,
        progress_callback: Optional[callable] = None
    ) -> None:
        """
        Create default indexes for the database.
        
        Args:
            connection: SQLite connection
            progress_callback: Optional callback for progress updates
        """
        self.logger.info("Creating default indexes...")
        
        if progress_callback:
            progress_callback("Creating database indexes...")
        
        # Create index manager
        index_manager = IndexManager(connection)
        
        # Create default indexes
        results = index_manager.ensure_default_indexes()
        
        # Log results
        created_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        self.logger.info(
            f"Index creation complete: {created_count}/{total_count} indexes created/verified"
        )
        
        if progress_callback:
            progress_callback(f"Created {created_count} indexes")
    
    def _analyze_database(
        self,
        connection: sqlite3.Connection,
        progress_callback: Optional[callable] = None
    ) -> None:
        """
        Analyze database to optimize query performance.
        
        Args:
            connection: SQLite connection
            progress_callback: Optional callback for progress updates
        """
        self.logger.info("Analyzing database...")
        
        if progress_callback:
            progress_callback("Analyzing database...")
        
        try:
            cursor = connection.cursor()
            cursor.execute("ANALYZE")
            connection.commit()
            
            self.logger.info("Database analysis complete")
            
            if progress_callback:
                progress_callback("Database analysis complete")
                
        except sqlite3.Error as e:
            self.logger.warning(f"Error analyzing database: {e}")
    
    def get_database_info(self, connection: sqlite3.Connection) -> dict:
        """
        Get information about the database.
        
        Args:
            connection: SQLite connection
            
        Returns:
            Dictionary with database information
        """
        try:
            cursor = connection.cursor()
            
            # Get table count
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            
            # Get index count
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'")
            index_count = cursor.fetchone()[0]
            
            # Get database size
            cursor.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            db_size = page_count * page_size
            
            # Get journal mode
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            
            return {
                'table_count': table_count,
                'index_count': index_count,
                'size_bytes': db_size,
                'size_mb': db_size / (1024 * 1024),
                'journal_mode': journal_mode
            }
            
        except sqlite3.Error as e:
            self.logger.error(f"Error getting database info: {e}")
            return {}
    
    @staticmethod
    def close_database(connection: Optional[sqlite3.Connection]) -> None:
        """
        Safely close a database connection.
        
        Args:
            connection: SQLite connection to close
        """
        if connection:
            try:
                connection.close()
            except Exception as e:
                logging.error(f"Error closing database connection: {e}")


# Convenience functions for common use cases

def initialize_mft_database(
    db_path: str,
    config: Optional[DataConfig] = None,
    progress_callback: Optional[callable] = None
) -> Optional[sqlite3.Connection]:
    """
    Initialize an MFT database with default settings.
    
    Args:
        db_path: Path to MFT database
        config: Optional DataConfig instance
        progress_callback: Optional progress callback
        
    Returns:
        SQLite connection or None
    """
    initializer = DatabaseInitializer(config)
    return initializer.initialize_database(db_path, progress_callback=progress_callback)


def initialize_usn_database(
    db_path: str,
    config: Optional[DataConfig] = None,
    progress_callback: Optional[callable] = None
) -> Optional[sqlite3.Connection]:
    """
    Initialize a USN database with default settings.
    
    Args:
        db_path: Path to USN database
        config: Optional DataConfig instance
        progress_callback: Optional progress callback
        
    Returns:
        SQLite connection or None
    """
    initializer = DatabaseInitializer(config)
    return initializer.initialize_database(db_path, progress_callback=progress_callback)


def initialize_correlated_database(
    db_path: str,
    config: Optional[DataConfig] = None,
    progress_callback: Optional[callable] = None
) -> Optional[sqlite3.Connection]:
    """
    Initialize a correlated data database with default settings.
    
    Args:
        db_path: Path to correlated database
        config: Optional DataConfig instance
        progress_callback: Optional progress callback
        
    Returns:
        SQLite connection or None
    """
    initializer = DatabaseInitializer(config)
    return initializer.initialize_database(db_path, progress_callback=progress_callback)
