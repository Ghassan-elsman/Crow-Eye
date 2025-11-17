from pathlib import Path
from typing import Dict, List, Optional, Union
from .base_loader import BaseDataLoader

class RegistryDataLoader(BaseDataLoader):
    """
    Specialized data loader for registry operations.
    Handles loading and processing registry data from SQLite databases.
    """
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        super().__init__(db_path)
        self.registry_tables = [
            'computer_Name', 'time_zone', 'TimeZoneInfo', 'network_interfaces',
            'NetworkInterfacesInfo', 'Network_list', 'SystemServices', 'machine_run',
            'machine_run_once', 'user_run', 'user_run_once', 'Windows_lastupdate',
            'WindowsUpdateInfo', 'ShutdownInfo', 'BrowserHistory', 'USBDevices',
            'USBInstances', 'USBProperties', 'USBStorageDevices', 'USBStorageVolumes',
            'RecentDocs', 'Search_Explorer_bar', 'OpenSaveMRU', 'lastSaveMRU',
            'TypedPaths', 'BAM', 'DAM', 'InstalledSoftware'
        ]
    
    def load_registry_table(self, table_name: str) -> List[Dict]:
        """
        Load data from a specific registry table.
        
        Args:
            table_name: Name of the registry table to load
            
        Returns:
            List of dictionaries containing the table data
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return []
            
        if not self.table_exists(table_name):
            self.logger.warning(f"Table '{table_name}' does not exist in the database.")
            return []
            
        query = f"SELECT * FROM {table_name}"
        return self.execute_query(query)
    
    def load_all_registry_data(self) -> Dict[str, List[Dict]]:
        """
        Load data from all known registry tables.
        
        Returns:
            Dictionary mapping table names to their data
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return {}
            
        result = {}
        for table in self.registry_tables:
            if self.table_exists(table):
                self.logger.debug(f"Loading data from table: {table}")
                data = self.load_registry_table(table)
                if data:
                    result[table] = data
                    self.logger.info(f"Loaded {len(data)} records from {table}")
        
        return result
    
    def get_table_schema(self, table_name: str) -> List[Dict]:
        """
        Get the schema information for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of dictionaries containing column information
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return []
            
        if not self.table_exists(table_name):
            return []
            
        query = f"PRAGMA table_info({table_name})"
        return self.execute_query(query)
