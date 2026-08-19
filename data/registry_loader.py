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
            # 'LastSaveMRU', not 'lastSaveMRU': table_exists() binds
            # sqlite_master.name = ?, which is case-sensitive, so the
            # mis-cased name never matched and the table was silently
            # dropped from load_all_registry_data().
            'RecentDocs', 'OpenSaveMRU', 'LastSaveMRU',
            'TypedPaths', 'BAM', 'DAM', 'InstalledSoftware',
            'ScheduledTasks', 'AutoStartPrograms',
            'RunMRU', 'Shellbags', 'UserAssist', 'MUICache', 'WordWheelQuery',
            'UserProfiles', 'winlogon', 'image_file_execution_options', 'appinit_dlls',
            'appcert_dlls', 'active_setup', 'run_services', 'run_services_once',
            'policies_explorer_run', 'user_shell_folders', 'lsa_packages', 'boot_execute',
            'clsid_inprocserver32', 'UserAccounts', 'ComputerNameInfo', 'shutdown_information',
            'Windows_lastupdate_subkeys',
            # Provenance about the parse itself: one row per hive saying
            # whether Windows had it open and whether its transaction logs were
            # replayed. Empty on a live parse - there is no hive file to be
            # stale - and the first thing to read on an offline case.
            'registry_hive_state',
            'SecurityPosture', 'DefenderExclusions', 'FirewallRules',
            'NetworkShares', 'ConnectedDevices', 'MountPoints2',
            'RDPClientMRU', 'OfficeDocuments', 'FeatureUsage',
            'CompatibilityAssistant', 'RecentApps', 'ApplicationArtifacts',
            'command_processor', 'drivers32', 'shell_service_object_delay_load',
            'browser_helper_objects', 'shared_task_scheduler', 'shell_icon_overlay_identifiers',
            'credential_providers', 'netsh_helper_dlls', 'amsi_providers',
            'security_providers', 'print_monitors', 'print_processors',
            'network_providers', 'wmi_autorecover_mofs', 'windows_load_run',
            'shell_open_command', 'file_exts', 'cid_size_mru',
            'programs_cache', 'regedit_lastkey', 'printer_connections',
            'explorer_advanced', 'rdp_tcp', 'usbstor_start',
            'windows_script_host', 'dnscache_parameters', 'files_not_to_snapshot',
            'winevt_channels', 'wpdbusenum', 'device_classes',
            'volume_info_cache', 'machine_guid', 'product_options',
            'os_install_history', 'active_computer_name', 'hivelist',
            'system_environment', 'network_adapters', 'group_policy_history',
            'local_groups', 'lsa_policy', 'audit_policy', 'lsa_secrets', 'cached_domain_logons'
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
