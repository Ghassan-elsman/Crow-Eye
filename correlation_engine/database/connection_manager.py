"""
Database Connection Manager

Manages database connections for streaming mode with proper lifecycle management.
Ensures connections are properly opened, used, and closed to prevent leaks.

Requirements: 6.4, 15.1
"""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ConnectionStatistics:
    """Statistics for database connection management"""
    connections_opened: int = 0
    connections_closed: int = 0
    connections_failed: int = 0
    active_connections: int = 0
    connection_errors: int = 0
    total_queries_executed: int = 0
    total_updates_executed: int = 0


class DatabaseConnectionManager:
    """
    Manages database connections for streaming mode correlation processing.
    
    This class provides proper connection lifecycle management:
    - Opens connections before use
    - Tracks active connections
    - Closes connections after completion
    - Handles connection errors gracefully
    - Prevents connection leaks
    
    Requirements: 6.4, 15.1
    Property 9: Database Connection Management in Streaming Mode
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize Database Connection Manager.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.statistics = ConnectionStatistics()
        self._lock = threading.Lock()
        self._active_connections: Dict[int, sqlite3.Connection] = {}
        
        if self.debug_mode:
            logger.info("[Database Connection Manager] Initialized")
    
    @contextmanager
    def get_connection(self, database_path: str):
        """
        Get a database connection with automatic cleanup.
        
        This context manager ensures proper connection lifecycle:
        1. Opens connection before use
        2. Yields connection for queries/updates
        3. Closes connection after completion (even on errors)
        
        Usage:
            with manager.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ...")
        
        Args:
            database_path: Path to SQLite database
            
        Yields:
            sqlite3.Connection object
            
        Requirements: 6.4, 15.1
        Property 9: Database Connection Management in Streaming Mode
        """
        conn = None
        conn_id = None
        
        try:
            # Validate database path
            if not database_path:
                raise ValueError("Database path cannot be empty")
            
            db_path = Path(database_path)
            if not db_path.exists():
                raise FileNotFoundError(f"Database file not found: {database_path}")
            
            # Open connection before use (Requirement 6.4)
            try:
                conn = sqlite3.connect(database_path)
                conn.row_factory = sqlite3.Row  # Enable column access by name
                
                # Track connection
                with self._lock:
                    conn_id = id(conn)
                    self._active_connections[conn_id] = conn
                    self.statistics.connections_opened += 1
                    self.statistics.active_connections = len(self._active_connections)
                
                if self.debug_mode:
                    logger.info(f"[Database Connection Manager] Opened connection to {database_path} "
                               f"(active: {self.statistics.active_connections})")
                
            except sqlite3.Error as e:
                error_msg = f"Failed to connect to database {database_path}: {e}"
                logger.error(f"[Database Connection Manager] {error_msg}")
                
                with self._lock:
                    self.statistics.connections_failed += 1
                    self.statistics.connection_errors += 1
                
                raise ConnectionError(error_msg) from e
            
            # Yield connection for use (Requirement 6.4)
            yield conn
            
        except Exception as e:
            # Handle connection errors gracefully (Requirement 6.4)
            logger.error(f"[Database Connection Manager] Error during connection use: {e}")
            
            with self._lock:
                self.statistics.connection_errors += 1
            
            raise
            
        finally:
            # Close connection after completion (Requirement 6.4)
            # This happens even if errors occur
            if conn is not None:
                try:
                    conn.close()
                    
                    # Update tracking
                    with self._lock:
                        if conn_id in self._active_connections:
                            del self._active_connections[conn_id]
                        self.statistics.connections_closed += 1
                        self.statistics.active_connections = len(self._active_connections)
                    
                    if self.debug_mode:
                        logger.info(f"[Database Connection Manager] Closed connection to {database_path} "
                                   f"(active: {self.statistics.active_connections})")
                    
                except Exception as e:
                    logger.warning(f"[Database Connection Manager] Error closing connection: {e}")
                    
                    with self._lock:
                        self.statistics.connection_errors += 1
    
    def execute_query(self, database_path: str, query: str, params: tuple = ()) -> list:
        """
        Execute a SELECT query with proper connection management.
        
        Args:
            database_path: Path to SQLite database
            query: SQL SELECT query
            params: Query parameters
            
        Returns:
            List of result rows
            
        Requirements: 6.4, 15.1
        """
        try:
            with self.get_connection(database_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                with self._lock:
                    self.statistics.total_queries_executed += 1
                
                if self.debug_mode:
                    logger.debug(f"[Database Connection Manager] Executed query, returned {len(results)} rows")
                
                return results
                
        except Exception as e:
            logger.error(f"[Database Connection Manager] Query execution failed: {e}")
            raise
    
    def execute_update(self, database_path: str, query: str, params: tuple = ()) -> int:
        """
        Execute an UPDATE/INSERT/DELETE query with proper connection management.
        
        Args:
            database_path: Path to SQLite database
            query: SQL UPDATE/INSERT/DELETE query
            params: Query parameters
            
        Returns:
            Number of rows affected
            
        Requirements: 6.4, 15.1
        """
        try:
            with self.get_connection(database_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                rows_affected = cursor.rowcount
                
                with self._lock:
                    self.statistics.total_updates_executed += 1
                
                if self.debug_mode:
                    logger.debug(f"[Database Connection Manager] Executed update, affected {rows_affected} rows")
                
                return rows_affected
                
        except Exception as e:
            logger.error(f"[Database Connection Manager] Update execution failed: {e}")
            raise
    
    def execute_batch_update(self, database_path: str, query: str, params_list: list) -> int:
        """
        Execute a batch UPDATE/INSERT query with proper connection management.
        
        Args:
            database_path: Path to SQLite database
            query: SQL UPDATE/INSERT query
            params_list: List of parameter tuples
            
        Returns:
            Total number of rows affected
            
        Requirements: 6.4, 15.1
        """
        try:
            with self.get_connection(database_path) as conn:
                cursor = conn.cursor()
                cursor.executemany(query, params_list)
                conn.commit()
                rows_affected = cursor.rowcount
                
                with self._lock:
                    self.statistics.total_updates_executed += len(params_list)
                
                if self.debug_mode:
                    logger.debug(f"[Database Connection Manager] Executed batch update with {len(params_list)} operations, "
                               f"affected {rows_affected} rows")
                
                return rows_affected
                
        except Exception as e:
            logger.error(f"[Database Connection Manager] Batch update execution failed: {e}")
            raise
    
    def get_statistics(self) -> ConnectionStatistics:
        """
        Get connection management statistics.
        
        Returns:
            ConnectionStatistics object
        """
        with self._lock:
            return ConnectionStatistics(
                connections_opened=self.statistics.connections_opened,
                connections_closed=self.statistics.connections_closed,
                connections_failed=self.statistics.connections_failed,
                active_connections=self.statistics.active_connections,
                connection_errors=self.statistics.connection_errors,
                total_queries_executed=self.statistics.total_queries_executed,
                total_updates_executed=self.statistics.total_updates_executed
            )
    
    def reset_statistics(self):
        """Reset connection statistics"""
        with self._lock:
            self.statistics = ConnectionStatistics()
    
    def get_active_connection_count(self) -> int:
        """
        Get the number of currently active connections.
        
        Returns:
            Number of active connections
        """
        with self._lock:
            return len(self._active_connections)
    
    def validate_no_leaks(self) -> Dict[str, Any]:
        """
        Validate that there are no connection leaks.
        
        Returns:
            Dictionary with validation results
        """
        with self._lock:
            active_count = len(self._active_connections)
            
            validation_results = {
                'valid': active_count == 0,
                'active_connections': active_count,
                'total_opened': self.statistics.connections_opened,
                'total_closed': self.statistics.connections_closed,
                'warnings': [],
                'errors': []
            }
            
            if active_count > 0:
                validation_results['errors'].append(
                    f"Connection leak detected: {active_count} connections still active"
                )
            
            if self.statistics.connections_opened != self.statistics.connections_closed:
                validation_results['warnings'].append(
                    f"Connection count mismatch: opened={self.statistics.connections_opened}, "
                    f"closed={self.statistics.connections_closed}"
                )
            
            return validation_results
