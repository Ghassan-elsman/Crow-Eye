"""
Database Connection Manager

Manages database connections for all feathers in a pipeline.
Handles connection pooling, status tracking, and graceful error handling.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..config.feather_config import FeatherConfig
from ..config.session_state import ConnectionStatus


class DatabaseConnectionManager:
    """
    Manages database connections for feather databases.
    Maintains a connection pool and tracks connection status.
    """
    
    def __init__(self):
        """Initialize database connection manager."""
        self._connections: Dict[str, sqlite3.Connection] = {}
        self._connection_status: Dict[str, ConnectionStatus] = {}
    
    def connect_feather(self, feather_config: FeatherConfig) -> Optional[sqlite3.Connection]:
        """
        Connect to a feather database.
        
        Args:
            feather_config: FeatherConfig with database path
        
        Returns:
            Database connection or None if connection fails
        """
        feather_name = feather_config.feather_name
        database_path = feather_config.output_database
        
        try:
            # Check if database file exists
            if not Path(database_path).exists():
                raise FileNotFoundError(f"Database file not found: {database_path}")
            
            # Create connection
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row  # Enable column access by name
            
            # Test connection by getting record count
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM feather_data")
            record_count = cursor.fetchone()[0]
            
            # Store connection
            self._connections[feather_name] = connection
            
            # Update status
            self._connection_status[feather_name] = ConnectionStatus(
                feather_name=feather_name,
                database_path=database_path,
                is_connected=True,
                connection_time=datetime.now().isoformat(),
                record_count=record_count
            )
            
            return connection
            
        except Exception as e:
            # Update status with error
            self._connection_status[feather_name] = ConnectionStatus(
                feather_name=feather_name,
                database_path=database_path,
                is_connected=False,
                error_message=str(e)
            )
            return None
    
    def connect_all(self, feather_configs: List[FeatherConfig]) -> Dict[str, Optional[sqlite3.Connection]]:
        """
        Connect to all feather databases.
        
        Args:
            feather_configs: List of FeatherConfig objects
        
        Returns:
            Dictionary mapping feather names to connections (None if failed)
        """
        connections = {}
        
        for feather_config in feather_configs:
            connection = self.connect_feather(feather_config)
            connections[feather_config.feather_name] = connection
        
        return connections
    
    def disconnect_feather(self, feather_name: str):
        """
        Disconnect from a feather database.
        
        Args:
            feather_name: Name of the feather to disconnect
        """
        if feather_name in self._connections:
            try:
                self._connections[feather_name].close()
            except Exception as e:
                print(f"Error closing connection for {feather_name}: {e}")
            finally:
                del self._connections[feather_name]
                if feather_name in self._connection_status:
                    self._connection_status[feather_name].is_connected = False
    
    def disconnect_all(self):
        """
        Disconnect from all databases.
        """
        feather_names = list(self._connections.keys())
        for feather_name in feather_names:
            self.disconnect_feather(feather_name)
    
    def get_connection(self, feather_name: str) -> Optional[sqlite3.Connection]:
        """
        Get connection for a feather.
        
        Args:
            feather_name: Name of the feather
        
        Returns:
            Database connection or None if not connected
        """
        return self._connections.get(feather_name)
    
    def get_connection_status(self, feather_name: Optional[str] = None) -> Dict[str, ConnectionStatus]:
        """
        Get connection status for feathers.
        
        Args:
            feather_name: Optional specific feather name, or None for all
        
        Returns:
            Dictionary of connection statuses
        """
        if feather_name:
            if feather_name in self._connection_status:
                return {feather_name: self._connection_status[feather_name]}
            return {}
        return self._connection_status.copy()
    
    def test_connection(self, database_path: str) -> bool:
        """
        Test if a database is accessible.
        
        Args:
            database_path: Path to database file
        
        Returns:
            True if database is accessible, False otherwise
        """
        try:
            # Check file exists
            if not Path(database_path).exists():
                return False
            
            # Try to connect and query
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            cursor.fetchall()
            conn.close()
            return True
            
        except Exception:
            return False
    
    def is_connected(self, feather_name: str) -> bool:
        """
        Check if a feather is connected.
        
        Args:
            feather_name: Name of the feather
        
        Returns:
            True if connected, False otherwise
        """
        return feather_name in self._connections
    
    def get_connected_count(self) -> int:
        """
        Get count of connected feathers.
        
        Returns:
            Number of active connections
        """
        return len(self._connections)
    
    def get_record_count(self, feather_name: str) -> Optional[int]:
        """
        Get record count for a connected feather.
        
        Args:
            feather_name: Name of the feather
        
        Returns:
            Record count or None if not connected
        """
        if feather_name in self._connection_status:
            return self._connection_status[feather_name].record_count
        return None
    
    def refresh_connection_status(self, feather_name: str):
        """
        Refresh connection status for a feather.
        
        Args:
            feather_name: Name of the feather
        """
        if feather_name not in self._connections:
            return
        
        try:
            connection = self._connections[feather_name]
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM feather_data")
            record_count = cursor.fetchone()[0]
            
            if feather_name in self._connection_status:
                self._connection_status[feather_name].record_count = record_count
                self._connection_status[feather_name].is_connected = True
                self._connection_status[feather_name].error_message = None
                
        except Exception as e:
            if feather_name in self._connection_status:
                self._connection_status[feather_name].is_connected = False
                self._connection_status[feather_name].error_message = str(e)
