"""
Database Search Integration for Crow Eye.
Provides easy integration of DatabaseSearchDialog with main application.
"""

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt
import logging
from typing import Optional, Dict, List

from ui.database_search_dialog import DatabaseSearchDialog
from data.unified_search_engine import UnifiedDatabaseSearchEngine
from data.base_loader import BaseDataLoader


class DatabaseSearchIntegration:
    """
    Handles integration of database search with Crow Eye main window.
    Manages search dialog, navigation, and result highlighting.
    """
    
    def __init__(self, parent_window):
        """
        Initialize database search integration.
        
        Args:
            parent_window: Main Crow Eye window instance
        """
        self.parent = parent_window
        self.logger = logging.getLogger(self.__class__.__name__)
        self.search_dialog = None
        self.unified_search_engine = None  # Will be created when needed with proper case directory
        
        # Track current highlight to clear when switching results
        self.current_highlight = None  # (table_widget, row, original_colors)
        
        # Track which GUI tabs have loaded data
        self.loaded_tabs: set = set()
        
        # Table mapping: database table name -> (tab_name, table_widget_attr, loader_attr, id_column, match_columns)
        # id_column: primary key in database
        # match_columns: list of columns to match between database and GUI (in order of preference)
        self.table_mapping = {
            # MFT tables - all under MFT_USN_tab_widget -> MFT tab
            'mft_records': ('MFT', 'MFT_table', 'mft_loader', 'id', ['record_number', 'filename', 'full_path', 'file_name']),
            'mft_file_names': ('MFT File Names', 'MFT_file_names_table', 'mft_loader', 'id', ['record_number', 'file_name', 'parent_record_number']),
            'mft_standard_info': ('MFT Standard Info', 'MFT_standard_info_table', 'mft_loader', 'id', ['record_number', 'creation_time']),
            'mft_data_attributes': ('MFT Data Attributes', 'MFT_data_attributes_table', 'mft_loader', 'id', ['record_number', 'attribute_type']),
            
            # USN tables - under MFT_USN_tab_widget -> USN Journal tab
            'journal_events': ('USN Journal', 'USN_table', 'usn_loader', 'id', ['usn', 'filename', 'timestamp', 'file_name']),
            'usn_journal': ('USN Journal', 'USN_table', 'usn_loader', 'id', ['usn', 'filename', 'reason', 'file_name']),
            
            # Correlated tables - under MFT_USN_tab_widget -> Correlated Data tab
            'mft_usn_correlated': ('Correlated Data', 'Correlated_table', 'correlated_loader', 'id', ['mft_record_number', 'reconstructed_path', 'full_path']),
            'correlated_data': ('Correlated Data', 'Correlated_table', 'correlated_loader', 'id', ['mft_record_number', 'file_name']),
            
            # Execution Evidence tables - under main_tab -> Execution tab
            'prefetch_files': ('Execution', 'Prefetch_table', None, 'id', ['file_name', 'executable_name', 'prefetch_hash']),
            'Prefetch_table': ('Execution', 'Prefetch_table', None, 'id', ['file_name', 'executable_name']),
            'amcache_entries': ('Amcache', 'Amcache_table', None, 'id', ['file_name', 'sha1', 'full_path']),
            'Amcache_table': ('Amcache', 'Amcache_table', None, 'id', ['file_name', 'sha1']),
            'Amcache_Programs_table': ('Amcache', 'Amcache_Programs_table', None, 'id', ['program_name', 'publisher']),
            'Amcache_Shortcuts_table': ('Amcache', 'Amcache_Shortcuts_table', None, 'id', ['lnk_name', 'lnk_path']),
            'shimcache_entries': ('ShimCache', 'ShimCache_main_table', None, 'id', ['path', 'file_name']),
            'ShimCache_main_table': ('ShimCache', 'ShimCache_main_table', None, 'id', ['path', 'file_name']),
            'lnk_files': ('LNK/JL', 'LNK_table', None, 'id', ['file_name', 'target_path', 'lnk_path']),
            'LNK_table': ('LNK/JL', 'LNK_table', None, 'id', ['file_name', 'target_path']),
            'AJL_table': ('LNK/JL', 'AJL_table', None, 'id', ['file_name', 'app_id']),
            'Clj_table': ('LNK/JL', 'Clj_table', None, 'id', ['file_name', 'destination_list']),
            'bam_entries': ('BAM/DAM', 'Bam_table', None, 'id', ['executable_path', 'execution_time']),
            'dam_entries': ('BAM/DAM', 'Dam_table', None, 'id', ['executable_path', 'execution_time']),
            'Bam_table': ('BAM/DAM', 'Bam_table', None, 'id', ['executable_path', 'execution_time']),
            'Dam_table': ('BAM/DAM', 'Dam_table', None, 'id', ['executable_path', 'execution_time']),
            'userassist_entries': ('UserAssist', 'UserAssist_table', None, 'id', ['program_name', 'execution_count']),
            'UserAssist_table': ('UserAssist', 'UserAssist_table', None, 'id', ['program_name', 'execution_count']),
            
            # Registry Evidence tables - under main_tab -> File Activity tab
            'registry_keys': ('Registry', 'Registry_table', None, 'id', ['key_path', 'last_write_time']),
            'registry_values': ('Registry', 'Registry_table', None, 'id', ['key_path', 'value_name', 'value_data']),
            'recent_docs': ('File Activity', 'RecentDocs_table', None, 'id', ['file_name', 'extension', 'mru_position']),
            'RecentDocs': ('File Activity', 'RecentDocs_table', None, 'id', ['file_name', 'extension', 'mru_position']),
            'RecentDocs_table': ('File Activity', 'RecentDocs_table', None, 'id', ['file_name', 'extension']),
            'search_explorer_bar': ('File Activity', 'SearchViaExplorer_table', None, 'id', ['search_term', 'timestamp']),
            'Search_Explorer_bar': ('File Activity', 'SearchViaExplorer_table', None, 'id', ['search_term', 'timestamp']),
            'SearchViaExplorer_table': ('File Activity', 'SearchViaExplorer_table', None, 'id', ['search_term']),
            'opensave_mru': ('File Activity', 'OpenSaveMRU_table', None, 'id', ['file_path', 'extension']),
            'OpenSaveMRU': ('File Activity', 'OpenSaveMRU_table', None, 'id', ['file_path', 'extension']),
            'OpenSaveMRU_table': ('File Activity', 'OpenSaveMRU_table', None, 'id', ['file_path', 'extension']),
            'lastsave_mru': ('File Activity', 'LastSaveMRU_table', None, 'id', ['file_path', 'extension']),
            'lastSaveMRU': ('File Activity', 'LastSaveMRU_table', None, 'id', ['file_path', 'extension']),
            'LastSaveMRU_table': ('File Activity', 'LastSaveMRU_table', None, 'id', ['file_path']),
            'typed_paths': ('File Activity', 'TypedPath_table', None, 'id', ['path', 'url']),
            'TypedPaths': ('File Activity', 'TypedPath_table', None, 'id', ['path', 'url']),
            'TypedPath_table': ('File Activity', 'TypedPath_table', None, 'id', ['path', 'url']),
            'run_mru': ('File Activity', 'RunMRU_table', None, 'id', ['command', 'mru_position']),
            'RunMRU_table': ('File Activity', 'RunMRU_table', None, 'id', ['command', 'mru_position']),
            'muicache_entries': ('File Activity', 'MUICache_table', None, 'id', ['application_path', 'application_name']),
            'MUICache_table': ('File Activity', 'MUICache_table', None, 'id', ['application_path', 'application_name']),
            'shellbags_entries': ('File Activity', 'Shellbags_table', None, 'id', ['path', 'shell_type']),
            'Shellbags_table': ('File Activity', 'Shellbags_table', None, 'id', ['path', 'shell_type']),
            'wordwheel_query': ('File Activity', 'WordWheelQuery_table', None, 'id', ['search_term', 'mru_position']),
            'WordWheelQuery_table': ('File Activity', 'WordWheelQuery_table', None, 'id', ['search_term', 'mru_position']),
            
            # System Information tables - under main_tab -> System Info tab
            'user_run': ('System Info', 'UserRun_table', None, 'id', ['key_path', 'value_name', 'value_data']),
            'UserRun_table': ('System Info', 'UserRun_table', None, 'id', ['key_path', 'value_name']),
            'machine_run': ('System Info', 'MachineRun_table', None, 'id', ['key_path', 'value_name', 'value_data']),
            'MachineRun_table': ('System Info', 'MachineRun_table', None, 'id', ['key_path', 'value_name']),
            'machine_run_once': ('System Info', 'MachineRunOnce_tabel', None, 'id', ['key_path', 'value_name', 'value_data']),
            'MachineRunOnce_table': ('System Info', 'MachineRunOnce_tabel', None, 'id', ['key_path', 'value_name']),
            'computer_name': ('System Info', 'computerName_table', None, 'id', ['computer_name', 'domain']),
            'computerName_table': ('System Info', 'computerName_table', None, 'id', ['computer_name', 'domain']),
            'last_update_info': ('System Info', 'LastUpdateInfo_table', None, 'id', ['update_time', 'update_type']),
            'LastUpdateInfo_table': ('System Info', 'LastUpdateInfo_table', None, 'id', ['update_time', 'update_type']),
            'shutdown_info': ('System Info', 'ShutDown_table', None, 'id', ['shutdown_time', 'shutdown_type']),
            'ShutDown_table': ('System Info', 'ShutDown_table', None, 'id', ['shutdown_time', 'shutdown_type']),
            'network_interfaces': ('System Info', 'NetworkInterface_table', None, 'id', ['interface_name', 'mac_address']),
            'NetworkInterface_table': ('System Info', 'NetworkInterface_table', None, 'id', ['interface_name', 'mac_address']),
            'network_list': ('System Info', 'NetworkLists_table', None, 'id', ['network_name', 'profile_name']),
            'NetworkLists_table': ('System Info', 'NetworkLists_table', None, 'id', ['network_name', 'profile_name']),
            'time_zone': ('System Info', 'TimeZone_table', None, 'id', ['time_zone', 'bias']),
            'TimeZone_table': ('System Info', 'TimeZone_table', None, 'id', ['time_zone', 'bias']),
            'system_services': ('System Info', 'SystemServices_table', None, 'id', ['service_name', 'display_name']),
            'SystemServices_table': ('System Info', 'SystemServices_table', None, 'id', ['service_name', 'display_name']),
            
            # Event Logs tables
            'system_logs': ('Event Logs', 'SystemLogs_table', None, 'id', ['event_id', 'timestamp', 'source']),
            'SystemLogs': ('Event Logs', 'SystemLogs_table', None, 'id', ['event_id', 'timestamp', 'source']),
            'SystemLogs_table': ('Event Logs', 'SystemLogs_table', None, 'id', ['event_id', 'timestamp']),
            'application_logs': ('Event Logs', 'ApplicationLogs_table', None, 'id', ['event_id', 'timestamp', 'source']),
            'ApplicationLogs': ('Event Logs', 'ApplicationLogs_table', None, 'id', ['event_id', 'timestamp', 'source']),
            'ApplicationLogs_table': ('Event Logs', 'ApplicationLogs_table', None, 'id', ['event_id', 'timestamp']),
            'security_logs': ('Event Logs', 'SecurityLogs_table', None, 'id', ['event_id', 'timestamp', 'source']),
            'SecurityLogs': ('Event Logs', 'SecurityLogs_table', None, 'id', ['event_id', 'timestamp', 'source']),
            'SecurityLogs_table': ('Event Logs', 'SecurityLogs_table', None, 'id', ['event_id', 'timestamp']),
            
            # USB tables
            'usb_devices': ('USB', 'USBDevices_table', None, 'id', ['device_id', 'serial_number', 'vendor_id']),
            'USBDevices_table': ('USB', 'USBDevices_table', None, 'id', ['device_id', 'serial_number']),
            'usb_properties': ('USB', 'USBProperties_table', None, 'id', ['device_id', 'property_name']),
            'USBProperties_table': ('USB', 'USBProperties_table', None, 'id', ['device_id', 'property_name']),
            'usb_instances': ('USB', 'USBInstances_table', None, 'id', ['instance_id', 'device_id']),
            'USBInstances_table': ('USB', 'USBInstances_table', None, 'id', ['instance_id', 'device_id']),
            'usb_storage_devices': ('USB', 'USBStorageDevices_table', None, 'id', ['device_id', 'serial_number']),
            'USBStorageDevices_table': ('USB', 'USBStorageDevices_table', None, 'id', ['device_id', 'serial_number']),
            'usb_storage_volumes': ('USB', 'USBStorageVolumes_table', None, 'id', ['volume_guid', 'volume_name']),
            'USBStorageVolumes_table': ('USB', 'USBStorageVolumes_table', None, 'id', ['volume_guid', 'volume_name']),
            
            # Browser History
            'browser_history': ('Browser', 'Browser_history_table', None, 'id', ['url', 'title', 'visit_time']),
            'Browser_history_table': ('Browser', 'Browser_history_table', None, 'id', ['url', 'title', 'visit_time']),
            
            # Recycle Bin
            'recyclebin_entries': ('Recycle Bin', 'RecycleBin_table', None, 'id', ['original_path', 'deleted_time']),
            'RecycleBin_table': ('Recycle Bin', 'RecycleBin_table', None, 'id', ['original_path', 'deleted_time']),
            
            # SRUM tables - under main_tab -> SRUM tab -> sub-tabs
            'srum_application_usage': ('SRUM', 'SRUM_application_usage_table', None, 'id', ['app_name', 'app_path', 'timestamp', 'user_name']),
            'srum_network_connectivity': ('SRUM', 'SRUM_network_connectivity_table', None, 'id', ['app_name', 'app_path', 'timestamp', 'user_name']),
            'srum_network_data_usage': ('SRUM', 'SRUM_network_data_table', None, 'id', ['app_name', 'app_path', 'timestamp', 'user_name']),
            'srum_energy_usage': ('SRUM', 'SRUM_energy_usage_table', None, 'id', ['app_name', 'app_path', 'timestamp', 'user_name']),
        }
    
    def show_search_dialog(self, case_directory: str):
        """
        Show the database search dialog with multi-database support.

        Args:
            case_directory: The root directory of the current case.
        """
        try:
            if not case_directory:
                # No case loaded
                parent_widget = getattr(self.parent, 'main_window', None)
                QtWidgets.QMessageBox.warning(
                    parent_widget,
                    "No Case Loaded",
                    "Please open or create a case before using database search.\n\n"
                    "Use 'Create case' or 'Open case' buttons to get started."
                )
                return
        except Exception as e:
            self.logger.error(f"Error preparing for database search: {e}")
            import traceback
            traceback.print_exc()
            parent_widget = getattr(self.parent, 'main_window', None)
            QtWidgets.QMessageBox.critical(
                parent_widget,
                "Database Search Error",
                f"Failed to prepare for database search:\n{str(e)}"
            )
            return

        # Create or update search dialog
        parent_widget = getattr(self.parent, 'main_window', None)
        try:
            if self.search_dialog is None or not self.search_dialog.isVisible():
                # Create search engine with case directory if not already created
                if self.unified_search_engine is None:
                    self.logger.info(f"Creating unified search engine for case: {case_directory}")
                    self.unified_search_engine = UnifiedDatabaseSearchEngine(case_directory)
                
                self.logger.info("Creating database search dialog...")
                self.search_dialog = DatabaseSearchDialog(parent_widget, self.unified_search_engine)
                self.search_dialog.navigate_to_result.connect(self._on_navigate_to_result)
                self.logger.info("Database search dialog created successfully")

            # Show the dialog
            self.logger.info("Showing database search dialog...")
            self.search_dialog.show()
            self.search_dialog.raise_()
            self.search_dialog.activateWindow()
            self.logger.info("Database search dialog shown successfully")
            
        except Exception as e:
            self.logger.error(f"Error creating or showing search dialog: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                parent_widget,
                "Database Search Error",
                f"Failed to open database search dialog:\n\n{str(e)}\n\n"
                "Please check the log file for more details."
            )
    
    def _on_navigate_to_result(self, database: str, table: str, row_id, timestamp_info: Optional[Dict] = None):
        """
        Handle navigation to search result from unified database search.
        Enhanced with tab load state checking and timestamp context.
        
        Args:
            database: Database name (e.g., 'registry_data.db')
            table: Table name in the database
            row_id: Row ID in the table
            timestamp_info: Optional dictionary with timestamp context
                           {'matched_timestamps': [...], 'time_range': (start, end)}
        
        Requirements: 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5
        """
        try:
            self.logger.info(f"Navigating to {database}/{table}, row {row_id}")
            
            # Get table mapping
            mapping = self.table_mapping.get(table.lower())
            
            if not mapping:
                self.logger.warning(f"No mapping found for table: {table}")
                parent_widget = getattr(self.parent, 'main_window', None)
                QtWidgets.QMessageBox.information(
                    parent_widget,
                    "Navigation Not Supported",
                    f"Navigation to table '{table}' is not yet supported.\n\n"
                    f"Database: {database}\n"
                    f"Table: {table}\n"
                    f"Row ID: {row_id}"
                )
                return
            
            tab_name, table_attr, loader_attr, id_column, match_columns = mapping
            
            # Check if target tab is loaded before navigation (Requirement 6.1, 6.2)
            if not self.is_tab_loaded(tab_name):
                self.logger.info(f"Tab '{tab_name}' is not loaded")
                parent_widget = getattr(self.parent, 'main_window', None)
                
                # Build message with timestamp context if available
                message = f"The '{tab_name}' tab does not have data loaded yet.\n\n"
                message += "Please load the artifact data first by:\n"
                message += f"1. Navigate to the '{tab_name}' tab\n"
                message += "2. Load the data using the appropriate button or action\n"
                message += "3. Return to search and try navigation again"
                
                if timestamp_info and 'matched_timestamps' in timestamp_info:
                    message += "\n\nTimestamp Context:\n"
                    for ts_match in timestamp_info['matched_timestamps'][:3]:  # Show first 3
                        message += f"  • {ts_match.get('column_name', 'unknown')}: {ts_match.get('formatted_display', 'N/A')}\n"
                
                QtWidgets.QMessageBox.information(
                    parent_widget,
                    "Tab Not Loaded",
                    message
                )
                return
            
            # Navigate to the tab
            success = self._navigate_to_tab(tab_name)
            
            if not success:
                self.logger.warning(f"Could not navigate to tab: {tab_name}")
                parent_widget = getattr(self.parent, 'main_window', None)
                QtWidgets.QMessageBox.warning(
                    parent_widget,
                    "Navigation Failed",
                    f"Could not find tab '{tab_name}' in the application."
                )
                return
            
            # Get the table widget
            table_widget = self._get_table_widget(table_attr)
            
            if not table_widget:
                self.logger.warning(f"Table widget not found: {table_attr}")
                parent_widget = getattr(self.parent, 'main_window', None)
                QtWidgets.QMessageBox.warning(
                    parent_widget,
                    "Navigation Failed",
                    f"Could not find table widget '{table_attr}' in tab '{tab_name}'."
                )
                return
            
            # Fetch record data from database to use for matching
            record_data = self._fetch_record_data(database, table, row_id)
            
            if not record_data:
                self.logger.warning(f"Could not fetch record data for row {row_id}")
                parent_widget = getattr(self.parent, 'main_window', None)
                QtWidgets.QMessageBox.warning(
                    parent_widget,
                    "Navigation Failed",
                    f"Could not retrieve record data from database.\n\n"
                    f"The record may have been deleted or the database may be unavailable."
                )
                return
            
            # Highlight the result with timestamp context (Requirement 6.5)
            self._highlight_result(table_widget, row_id, record_data, loader_attr, match_columns, timestamp_info)
            
            # Log timestamp context if available
            if timestamp_info:
                self.logger.info(f"Navigation includes timestamp context: {timestamp_info}")
            
            # Hide search dialog
            if self.search_dialog:
                self.search_dialog.hide()
                
        except Exception as e:
            self.logger.error(f"Error in _on_navigate_to_result: {e}")
            import traceback
            traceback.print_exc()
            parent_widget = getattr(self.parent, 'main_window', None)
            QtWidgets.QMessageBox.critical(
                parent_widget,
                "Navigation Error",
                f"Failed to navigate to result:\n{str(e)}"
            )
    
    def _fetch_record_data(self, database: str, table: str, row_id) -> Optional[dict]:
        """
        Fetch record data from database for navigation.
        
        Args:
            database: Database name
            table: Table name
            row_id: Row ID to fetch
            
        Returns:
            Dictionary of record data or None if not found
        """
        try:
            # Get case paths
            if not hasattr(self.parent, 'case_paths'):
                return None
            
            case_paths = self.parent.case_paths
            if not case_paths or 'artifacts_dir' not in case_paths:
                return None
            
            import os
            import sqlite3
            
            # Build database path
            artifacts_dir = case_paths['artifacts_dir']
            db_path = os.path.join(artifacts_dir, database)
            
            if not os.path.exists(db_path):
                self.logger.warning(f"Database not found: {db_path}")
                return None
            
            # Query the database
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Try to fetch by id column
            try:
                cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
                row = cursor.fetchone()
                
                if row:
                    record_data = dict(row)
                    conn.close()
                    return record_data
            except sqlite3.Error as e:
                self.logger.warning(f"Error querying by id: {e}")
            
            # If that failed, try ROWID
            try:
                cursor.execute(f"SELECT * FROM {table} WHERE ROWID = ?", (row_id,))
                row = cursor.fetchone()
                
                if row:
                    record_data = dict(row)
                    conn.close()
                    return record_data
            except sqlite3.Error as e:
                self.logger.warning(f"Error querying by ROWID: {e}")
            
            conn.close()
            return None
            
        except Exception as e:
            self.logger.error(f"Error fetching record data: {e}")
            return None
    
    def _on_result_selected(self, table_name: str, row_id, record_data: dict):
        """
        Handle search result selection - navigate and highlight.
        
        DEPRECATED: This method is kept for backward compatibility.
        Use _on_navigate_to_result instead.
        
        Args:
            table_name: Database table name
            row_id: Row ID in the table
            record_data: Full record data
        """
        try:
            self.logger.info(f"Navigating to {table_name}, row {row_id}")
            
            # Get table mapping
            mapping = self.table_mapping.get(table_name.lower())
            
            if not mapping:
                self.logger.warning(f"No mapping found for table: {table_name}")
                parent_widget = getattr(self.parent, 'main_window', None)
                QtWidgets.QMessageBox.information(
                    parent_widget,
                    "Search Result",
                    f"Found result in {table_name}:\n\n" +
                    "\n".join(f"{k}: {v}" for k, v in list(record_data.items())[:5])
                )
                return
            
            tab_name, table_attr, loader_attr, id_column, match_columns = mapping
        except Exception as e:
            self.logger.error(f"Error in _on_result_selected: {e}")
            import traceback
            traceback.print_exc()
            parent_widget = getattr(self.parent, 'main_window', None)
            QtWidgets.QMessageBox.critical(
                parent_widget,
                "Navigation Error",
                f"Failed to navigate to result:\n{str(e)}"
            )
            return
        
        # Navigate to the tab
        success = self._navigate_to_tab(tab_name)
        
        if not success:
            self.logger.warning(f"Could not navigate to tab: {tab_name}")
            return
        
        # Get the table widget
        table_widget = self._get_table_widget(table_attr)
        
        if not table_widget:
            self.logger.warning(f"Table widget not found: {table_attr}")
            return
        
        # Highlight the result
        self._highlight_result(table_widget, row_id, record_data, loader_attr, match_columns)
        
        # Hide search dialog
        if self.search_dialog:
            self.search_dialog.hide()
    
    def _navigate_to_tab(self, tab_name: str) -> bool:
        """Navigate to a specific tab."""
        # Try to find main_tab or similar tab widget
        tab_widgets = ['main_tab', 'tabWidget', 'tab_widget']
        
        for attr in tab_widgets:
            if hasattr(self.parent, attr):
                tab_widget = getattr(self.parent, attr)
                if isinstance(tab_widget, QtWidgets.QTabWidget):
                    # Find tab by name
                    for i in range(tab_widget.count()):
                        if tab_name.lower() in tab_widget.tabText(i).lower():
                            tab_widget.setCurrentIndex(i)
                            QtWidgets.QApplication.processEvents()
                            return True
        
        return False
    
    def _get_table_widget(self, table_attr: str):
        """Get table widget by attribute name."""
        if hasattr(self.parent, table_attr):
            return getattr(self.parent, table_attr)
        return None
    
    def _highlight_result(self, table_widget, row_id, record_data: dict, loader_attr: Optional[str], match_columns: list, timestamp_info: Optional[Dict] = None):
        """
        Highlight search result in table widget.
        Handles both regular QTableWidget and VirtualTableWidget.
        
        Args:
            table_widget: Table widget to highlight in
            row_id: Database row ID
            record_data: Record data from database
            loader_attr: Loader attribute name
            match_columns: Columns to match for finding the row
            timestamp_info: Optional timestamp context information
        """
        from ui.virtual_table_widget import VirtualTableWidget
        
        # Clear previous highlight first
        self._clear_current_highlight()
        
        # Check if it's a virtual table
        if isinstance(table_widget, VirtualTableWidget):
            self._highlight_virtual_table_result(table_widget, row_id, record_data, loader_attr, match_columns, timestamp_info)
        else:
            self._highlight_regular_table_result(table_widget, row_id, record_data, match_columns, timestamp_info)
    
    def _highlight_virtual_table_result(self, table_widget, row_id, record_data: dict, loader_attr: Optional[str], match_columns: list, timestamp_info: Optional[Dict] = None):
        """
        Highlight result in VirtualTableWidget by matching database record to GUI row.
        
        Args:
            table_widget: Virtual table widget
            row_id: Database row ID
            record_data: Record data from database
            loader_attr: Loader attribute name
            match_columns: Columns to match for finding the row
            timestamp_info: Optional timestamp context information
        """
        # For virtual tables, we need to find the row by matching data fields
        # since the database ID might not match the GUI row index
        
        # Get the data loader
        if loader_attr and hasattr(self.parent, loader_attr):
            loader = getattr(self.parent, loader_attr)
            
            # Try to find the row by matching columns
            gui_row = self._find_matching_row(table_widget, record_data, match_columns)
            
            if gui_row is not None:
                # Found the row in current view
                table_widget.selectRow(gui_row)
                table_widget.scrollToItem(
                    table_widget.item(gui_row, 0),
                    QtWidgets.QAbstractItemView.PositionAtCenter
                )
                self._apply_persistent_highlight(table_widget, gui_row, timestamp_info)
            else:
                # Row not in current view - need to load the correct page
                # Calculate which page contains this row (if we have sequential IDs)
                page_size = table_widget.page_size if hasattr(table_widget, 'page_size') else 100
                
                # Try to estimate page from row_id
                estimated_page = (row_id // page_size) + 1
                
                # Load that page
                if hasattr(table_widget, 'load_page'):
                    table_widget.load_page(estimated_page)
                    QtWidgets.QApplication.processEvents()
                    
                    # Try to find the row again
                    gui_row = self._find_matching_row(table_widget, record_data, match_columns)
                    
                    if gui_row is not None:
                        table_widget.selectRow(gui_row)
                        table_widget.scrollToItem(
                            table_widget.item(gui_row, 0),
                            QtWidgets.QAbstractItemView.PositionAtCenter
                        )
                        self._apply_persistent_highlight(table_widget, gui_row, timestamp_info)
                    else:
                        # Still not found - show message with timestamp context
                        parent_widget = getattr(self.parent, 'main_window', None)
                        message = f"Found record in database but it's not currently loaded in the table.\n\n"
                        message += f"Try adjusting filters or loading more data."
                        
                        if timestamp_info and 'matched_timestamps' in timestamp_info:
                            message += "\n\nTimestamp Context:\n"
                            for ts_match in timestamp_info['matched_timestamps'][:3]:
                                message += f"  • {ts_match.get('column_name', 'unknown')}: {ts_match.get('formatted_display', 'N/A')}\n"
                        
                        QtWidgets.QMessageBox.information(
                            parent_widget,
                            "Result Not Visible",
                            message
                        )
    
    def _highlight_regular_table_result(self, table_widget, row_id, record_data: dict, match_columns: list, timestamp_info: Optional[Dict] = None):
        """
        Highlight result in regular QTableWidget by matching data fields.
        
        Args:
            table_widget: Regular table widget
            row_id: Database row ID
            record_data: Record data from database
            match_columns: Columns to match for finding the row
            timestamp_info: Optional timestamp context information
        """
        # Try to find the row by matching columns
        gui_row = self._find_matching_row(table_widget, record_data, match_columns)
        
        if gui_row is not None:
            # Select and scroll to row
            table_widget.selectRow(gui_row)
            table_widget.scrollToItem(
                table_widget.item(gui_row, 0),
                QtWidgets.QAbstractItemView.PositionAtCenter
            )
            
            # Apply persistent highlight with timestamp context
            self._apply_persistent_highlight(table_widget, gui_row, timestamp_info)
        else:
            # Not found in current view - show message with timestamp context
            parent_widget = getattr(self.parent, 'main_window', None)
            message = f"Found record in database but it's not currently loaded in the table.\n\n"
            message += f"Try adjusting filters or loading more data."
            
            if timestamp_info and 'matched_timestamps' in timestamp_info:
                message += "\n\nTimestamp Context:\n"
                for ts_match in timestamp_info['matched_timestamps'][:3]:
                    message += f"  • {ts_match.get('column_name', 'unknown')}: {ts_match.get('formatted_display', 'N/A')}\n"
            
            QtWidgets.QMessageBox.information(
                parent_widget,
                "Result Not Visible",
                message
            )
    
    def _find_matching_row(self, table_widget, record_data: dict, match_columns: list) -> Optional[int]:
        """
        Find GUI row that matches database record by comparing column values.
        
        Args:
            table_widget: QTableWidget to search
            record_data: Database record data
            match_columns: List of column names to match (in order of preference)
        
        Returns:
            Row index if found, None otherwise
        """
        # Get column headers
        headers = []
        for col in range(table_widget.columnCount()):
            header_item = table_widget.horizontalHeaderItem(col)
            if header_item:
                headers.append(header_item.text().lower())
            else:
                headers.append(f"col_{col}")
        
        # Try each match column
        for match_col in match_columns:
            if match_col not in record_data:
                continue
            
            match_value = str(record_data[match_col])
            
            # Find column index in GUI
            col_idx = None
            for idx, header in enumerate(headers):
                if match_col.lower() in header or header in match_col.lower():
                    col_idx = idx
                    break
            
            if col_idx is None:
                continue
            
            # Search for matching value in this column
            for row in range(table_widget.rowCount()):
                item = table_widget.item(row, col_idx)
                if item and str(item.text()) == match_value:
                    return row
        
        return None
    
    def _clear_current_highlight(self):
        """Clear the current highlight before applying a new one."""
        if self.current_highlight:
            table_widget, row, original_colors = self.current_highlight
            
            # Restore original colors
            for col in range(table_widget.columnCount()):
                item = table_widget.item(row, col)
                if item and col < len(original_colors):
                    bg, fg = original_colors[col]
                    if bg:
                        item.setBackground(bg)
                    if fg:
                        item.setForeground(fg)
            
            self.current_highlight = None
    
    def _apply_persistent_highlight(self, table_widget, row: int, timestamp_info: Optional[Dict] = None):
        """
        Apply persistent highlight to a row (stays until next result).
        
        Args:
            table_widget: Table widget to highlight in
            row: Row index to highlight
            timestamp_info: Optional timestamp context information
        """
        from PyQt5.QtGui import QColor, QBrush
        
        # Store original colors
        original_colors = []
        for col in range(table_widget.columnCount()):
            item = table_widget.item(row, col)
            if item:
                original_colors.append((
                    item.background(),
                    item.foreground()
                ))
            else:
                original_colors.append((None, None))
        
        # Apply highlight
        for col in range(table_widget.columnCount()):
            item = table_widget.item(row, col)
            if item:
                item.setBackground(QBrush(QColor("#00FFFF")))
                item.setForeground(QBrush(QColor("#000000")))
                
                # Add timestamp info to tooltip if available
                if timestamp_info and 'matched_timestamps' in timestamp_info:
                    current_tooltip = item.toolTip()
                    timestamp_text = "\n\nMatched Timestamps:\n"
                    for ts_match in timestamp_info['matched_timestamps']:
                        timestamp_text += f"  • {ts_match.get('column_name', 'unknown')}: {ts_match.get('formatted_display', 'N/A')}\n"
                    
                    if current_tooltip:
                        item.setToolTip(current_tooltip + timestamp_text)
                    else:
                        item.setToolTip(timestamp_text.strip())
        
        # Store current highlight info
        self.current_highlight = (table_widget, row, original_colors)
    
    def update_loaded_tabs(self, tab_name: str, is_loaded: bool):
        """
        Update the set of loaded tabs.
        
        This method should be called when a GUI tab loads or unloads data
        to keep track of which tabs are currently available for navigation.
        
        Args:
            tab_name: Name of the GUI tab (e.g., 'Prefetch', 'MFT', 'SRUM')
            is_loaded: True if tab has loaded data, False if unloaded
            
        Requirements: 6.4, 10.7
        """
        if is_loaded:
            self.loaded_tabs.add(tab_name)
            self.logger.info(f"Tab '{tab_name}' marked as loaded")
        else:
            self.loaded_tabs.discard(tab_name)
            self.logger.info(f"Tab '{tab_name}' marked as not loaded")
        
        # Update database tree indicators if search dialog is open (Requirement 10.7)
        if self.search_dialog and self.search_dialog.isVisible():
            # Trigger a refresh of the database tree to update indicators
            # This calls the method to update just the indicators without reloading the entire tree
            if hasattr(self.search_dialog, 'update_database_tree_indicators'):
                try:
                    self.search_dialog.update_database_tree_indicators()
                    self.logger.debug(f"Updated database tree indicators after tab '{tab_name}' load state change")
                except Exception as e:
                    self.logger.warning(f"Failed to update database tree indicators: {e}")
    
    def is_tab_loaded(self, tab_name: str) -> bool:
        """
        Check if a tab has loaded data.
        
        Args:
            tab_name: Name of the GUI tab to check
            
        Returns:
            True if tab is loaded, False otherwise
            
        Requirements: 6.4, 10.7
        """
        return tab_name in self.loaded_tabs
    
    def monitor_tab_load_events(self):
        """
        Monitor main window tab load events and update loaded_tabs set.
        
        This method should be called during initialization to hook into
        main window tab load events. It monitors when tabs load/unload data
        and automatically updates the loaded_tabs set.
        
        Requirements: 6.4, 10.7
        """
        try:
            # Hook into common loader completion signals if they exist
            # This is a generic approach that can be customized per loader type
            
            loaders = [
                ('mft_loader', 'MFT'),
                ('usn_loader', 'USN Journal'),
                ('correlated_loader', 'Correlated Data'),
                ('prefetch_loader', 'Execution'),
                ('amcache_loader', 'Amcache'),
                ('shimcache_loader', 'ShimCache'),
                ('lnk_loader', 'LNK/JL'),
                ('bam_loader', 'BAM/DAM'),
                ('userassist_loader', 'UserAssist'),
                ('registry_loader', 'Registry'),
                ('recentdocs_loader', 'File Activity'),
                ('system_info_loader', 'System Info'),
                ('event_logs_loader', 'Event Logs'),
                ('usb_loader', 'USB'),
                ('browser_loader', 'Browser'),
                ('recyclebin_loader', 'Recycle Bin'),
                ('srum_loader', 'SRUM'),
            ]
            
            for loader_attr, tab_name in loaders:
                if hasattr(self.parent, loader_attr):
                    loader = getattr(self.parent, loader_attr)
                    
                    # Try to connect to common completion signals
                    if hasattr(loader, 'data_loaded'):
                        try:
                            loader.data_loaded.connect(
                                lambda tn=tab_name: self.update_loaded_tabs(tn, True)
                            )
                            self.logger.debug(f"Connected to {loader_attr}.data_loaded signal")
                        except Exception as e:
                            self.logger.debug(f"Could not connect to {loader_attr}.data_loaded: {e}")
                    
                    if hasattr(loader, 'data_cleared'):
                        try:
                            loader.data_cleared.connect(
                                lambda tn=tab_name: self.update_loaded_tabs(tn, False)
                            )
                            self.logger.debug(f"Connected to {loader_attr}.data_cleared signal")
                        except Exception as e:
                            self.logger.debug(f"Could not connect to {loader_attr}.data_cleared: {e}")
            
            self.logger.info("Tab load event monitoring initialized")
            
        except Exception as e:
            self.logger.warning(f"Error setting up tab load event monitoring: {e}")
    
    def get_loaded_tabs(self) -> set:
        """
        Get the set of currently loaded tabs.
        
        Returns:
            Set of tab names that have loaded data
            
        Requirements: 10.7
        """
        return self.loaded_tabs.copy()


def add_database_search_action(main_window, menu_bar=None, toolbar=None):
    """
    Add database search action to menu bar or toolbar.
    
    Args:
        main_window: Main Crow Eye window
        menu_bar: QMenuBar to add action to (optional)
        toolbar: QToolBar to add action to (optional)
    
    Returns:
        DatabaseSearchIntegration instance
    """
    integration = DatabaseSearchIntegration(main_window)
    
    # Create action
    search_action = QtWidgets.QAction("Database Search", main_window)
    search_action.setShortcut("Ctrl+Shift+F")
    search_action.setStatusTip("Search across all forensic databases")
    search_action.triggered.connect(integration.show_search_dialog)
    
    # Add to menu bar if provided
    if menu_bar:
        # Try to find Search menu or create one
        search_menu = None
        for action in menu_bar.actions():
            if action.menu() and 'search' in action.text().lower():
                search_menu = action.menu()
                break
        
        if not search_menu:
            search_menu = menu_bar.addMenu("&Search")
        
        search_menu.addAction(search_action)
    
    # Add to toolbar if provided
    if toolbar:
        toolbar.addAction(search_action)
    
    return integration
