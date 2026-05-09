"""
Virtual Table Widget for Crow Eye
Provides lazy loading table widget that loads data on-demand using virtual scrolling.
"""

from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from typing import Optional, List, Dict, Any, Callable
import logging
import os
from dynamic_mapping.enrichment.enrichment_mixin import EnrichmentMixin


class VirtualTableWidget(QTableWidget, EnrichmentMixin):
    """
    A table widget that loads data on-demand using virtual scrolling.
    
    This widget efficiently handles large datasets by:
    - Loading only visible rows plus a buffer
    - Dynamically fetching data as the user scrolls
    - Recycling QTableWidgetItem objects to reduce memory usage
    - Managing a configurable buffer to keep rows in memory
    """
    
    # Signals
    data_requested = pyqtSignal(int, int)  # offset, limit
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()
    data_loaded = pyqtSignal()  # Emitted when data is loaded and ready for styling
    
    # Enrichment Target Columns: Set of column names that should be enriched
    # If empty, the heuristic in _initialize_intelligence will try to pick the best ones.
    ENRICHMENT_TARGET_COLUMNS = {
        # --- File & Path Identifiers ---
        'target_path', 'Local_Path', 'Source_Name', 'Source_Path', 'executable_path', 
        'key_path', 'program_path', 'app_path', 'file_path', 'folder_path', 'root_dir_path',
        'lower_case_long_path', 'process_path', 'image_path', 'ShortcutPath', 
        'ShortcutTargetPath', 'mare_path', 'install_location', 'original_path',
        'recycle_bin_path', 'r_file_path', 'reconstructed_path', 'registry_path',
        'parent_path', 'Relative_Path', 'Working_Directory', 'Icon_Location',
        'Common_Path', 'manifest_path', 'package_full_name', 'bundle_manifest_path',
        'srudb_path', 'uninstall_string', 'path', 'folder_path', 'icon', 'ShortcutAumid',

        # --- User & System Identifiers ---
        'SID', 'user_sid', 'sid', 'User', 'username', 'user_name', 'Owner_UID', 
        'registered_owner', 'ComputerName', 'computer_name', 'ComputerNameInfo',
        'Tracker_NetBIOS', 'ComputerName', 'registered_organization', 'product_id',
        'Owner_GID', 'owner_id', 'security_id', 'profile_image_path',

        # --- Network Identifiers ---
        'MAC_Address', 'gateway_mac', 'mac_address', 'dhcp_server', 'dns_servers',
        'network_name', 'server_name', 'share_name', 'interface_id', 'Tracker_MAC',
        'ip_address', 'network_share', 'interface_luid', 'l2_profile_id',
        'Birth_Object_ID_MAC', 'dhcp_server',

        # --- Hardware & Device Identifiers ---
        'device_id', 'instance_id', 'parent_id', 'serial_number', 'vendor_id', 
        'product_id', 'volume_guid', 'model_id', 'class_guid', 'Device_ID',
        'Volume_Serial', 'Volume_Label', 'volume_name', 'Known_Folder_GUID',
        'Birth_Volume_ID', 'Birth_Object_ID', 'DestList_New_Volume_ID', 
        'DestList_New_Object_ID', 'LNK_Class_ID', 'class_id', 'interface_luid',

        # --- Forensic & Process Identifiers ---
        'Value', 'Name', 'Filename', 'file_name', 'executable_name', 'fn_filename',
        'original_file_name', 'file_id', 'program_id', 'program_instance_id',
        'Process Name', 'app_name', 'program_name', 'service_name', 'display_name',
        'friendly_name', 'model_name', 'mare_name', 'search_term', 'command',
        'EventID', 'Source', 'TaskCategory', 'AppID', 'record_number', 
        'mft_record_number', 'mft_record_number', 'frn', 'parent_frn', 
        'parent_record', 'usn_event_id', 'entry_hash', 'original_filename',
        'random_i_filename', 'random_r_filename', 'ShortcutAumid', 'ShortcutProgramId',
        'driver_name', 'driver_id', 'mare_id', 'uup_id', 'uup_name', 'subkey_name',
        'folder_name', 'short_name',
        
        # --- Generic but Pattern-Heavy Columns ---
        'row_data', 'subkey', 'data', 'id', 'version', 'bin_file_version', 
        'bin_product_version', 'display_version', 'driver_version', 'product_version'
    }

    def __init__(
        self,
        data_loader,
        table_name: str,
        columns: List[str],
        page_size: int = 1000,
        buffer_size: int = 2000,
        parent=None
    ):
        """
        Initialize virtual table widget.
        
        Args:
            data_loader: BaseDataLoader instance for database access
            table_name: Name of the database table
            columns: List of column names to display
            page_size: Number of rows to fetch per request
            buffer_size: Total rows to keep in memory
            parent: Parent widget
        """
        # Call multiple inheritance constructors because we are fancy like that
        QTableWidget.__init__(self, parent)
        EnrichmentMixin.__init__(self)
        
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Data source configuration
        self.data_loader = data_loader
        self.table_name = table_name
        self.columns = columns
        
        # Enrichment configuration - where the magic happens
        self.enrichment_column = None  # Will be auto-detected if None
        self._intelligence_initialized = False
        
        # Pagination configuration
        self.page_size = page_size
        self.buffer_size = buffer_size
        
        # Data state
        self.total_rows = 0
        self.loaded_data = {}  # Maps row index to data dict
        self.current_offset = 0
        self.is_loading = False
        
        # Filter state
        self.where_clause = None
        self.where_params = ()
        self.order_by = None
        
        # Item recycling pool
        self.item_pool = []
        self.max_pool_size = 1000
        
        # Scroll detection
        self.scroll_timer = QTimer()
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self._on_scroll_timer)
        self.scroll_delay_ms = 100
        
        # Initialize UI
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        # Set up columns
        self.setColumnCount(len(self.columns))
        self.setHorizontalHeaderLabels(self.columns)
        
        # Configure table behavior
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        # Enable sorting
        self.setSortingEnabled(False)  # Disable during loading
        
        # Enable alternating row colors for better readability
        self.setAlternatingRowColors(True)
        
        # Show grid lines
        self.setShowGrid(True)
        
        # Set attribute to enable styled background
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        # Resize columns to content
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        header.setAttribute(Qt.WA_StyledBackground, True)
        
        # Set vertical header properties
        vertical_header = self.verticalHeader()
        vertical_header.setDefaultSectionSize(30)
        vertical_header.setMinimumSectionSize(24)
        vertical_header.setAttribute(Qt.WA_StyledBackground, True)
        
        # Connect scroll event
        self.verticalScrollBar().valueChanged.connect(self._on_vertical_scroll_changed)
        
        # Connect double-click event for row details
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        
    def load_initial_data(self) -> bool:
        """
        Load the first page of data.
        
        Returns:
            bool: True if data was loaded successfully, False otherwise
        """
        try:
            self.loading_started.emit()
            self.is_loading = True
            
            # Get table statistics to determine total rows
            stats = self.data_loader.get_table_statistics(self.table_name)
            
            if not stats.get('table_exists', False):
                self.logger.error(f"Table '{self.table_name}' does not exist. It's ghosting us.")
                return False
            
            # --- Intelligence Integration: Time to wake up the brain! ---
            if not self._intelligence_initialized:
                self._initialize_intelligence()
            
            # Re-attach if already initialized but new connection (just in case)
            if self.get_intelligence_db_path():
                # We use the cursor from our data_loader because it knows the way
                cursor = self.data_loader.connection.cursor()
                self.attach_intelligence_db(cursor)
                self.logger.info(f"Attached intelligence brain to {self.table_name} view.")
            
            # Get total row count (with filter if applied)
            if self.where_clause:
                count_query = f"SELECT COUNT(*) FROM {self.table_name} WHERE {self.where_clause}"
                self.total_rows = self.data_loader.count_query(count_query, self.where_params)
            else:
                self.total_rows = stats.get('row_count', 0)
            
            if self.total_rows == 0:
                self.setRowCount(0)
                self.logger.info(f"No data found in table '{self.table_name}'")
                return True
            
            # Set virtual row count
            self.setRowCount(self.total_rows)
            
            # Load first chunk of data
            self._load_data_chunk(0, self.buffer_size)
            
            # Populate visible rows
            self._populate_visible_rows()
            
            # Schedule viewport update after Qt event loop processes
            QTimer.singleShot(0, self._force_viewport_update)
            
            # Apply styles immediately after data is loaded
            self._apply_styles_immediately()
            
            # Emit signal that data is loaded
            self.data_loaded.emit()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading initial data: {e}")
            return False
            
        finally:
            self.is_loading = False
            self.loading_finished.emit()
    
    def _load_data_chunk(self, offset: int, limit: int) -> bool:
        """
        Load a chunk of data from the database.
        
        Args:
            offset: Starting row index
            limit: Number of rows to load
            
        Returns:
            bool: True if data was loaded successfully
        """
        try:
            # Build query
            select_cols = ", ".join(self.columns)
            query = f"SELECT {select_cols} FROM {self.table_name}"
            
            if self.where_clause:
                query += f" WHERE {self.where_clause}"
            
            if self.order_by:
                query += f" ORDER BY {self.order_by}"
            
            # Check if we should sprinkle some intelligence on this query
            if self.get_intelligence_db_path() and self.enrichment_column:
                # Build enriched query
                # Enforce Source Exclusion explicitly in the ON clause
                # We use a unique alias to avoid naming collisions with existing identifiers.
                alias = "base_tbl"
                
                # To avoid ambiguous columns (like 'Source'), we must ensure columns are prefixed
                select_part = ", ".join(self.columns)
                
                select_cols = select_part
                if "*" in select_part:
                    select_cols = f"{alias}.*"
                elif "," in select_part and not any(f"{alias}." in col for col in select_part.split(",")):
                    # Try a simple prefixing for common columns if no alias is present
                    if "(" not in select_part: # Avoid complex expressions
                        cols = [c.strip() for c in select_part.split(",")]
                        select_cols = ", ".join([f"{alias}.{c}" for c in cols])
                
                enriched_query = (
                    f"SELECT {select_cols}, Intel.Mapping.Key AS Dynamic_Key "
                    f"FROM {self.table_name} AS {alias} "
                    f"LEFT JOIN Intel.Mapping ON {alias}.{self.enrichment_column} = Intel.Mapping.Value "
                    f"AND Intel.Mapping.source != '{self.table_name}'"
                )
                
                query = enriched_query
                if self.where_clause:
                    # We need to make sure the where clause uses the alias if needed.
                    # For now, we hope the user didn't use ambiguous names in their filters.
                    query += f" WHERE {self.where_clause}"
                if self.order_by:
                    query += f" ORDER BY {self.order_by}"
            
            query += f" LIMIT {limit} OFFSET {offset}"
            
            # Execute query
            results = self.data_loader.execute_query(query, self.where_params)
            
            # Store results in loaded_data dict
            for i, record in enumerate(results):
                row_index = offset + i
                self.loaded_data[row_index] = record
            
            self.logger.debug(f"Loaded {len(results)} rows from offset {offset}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading data chunk: {e}")
            return False
    
    def _populate_visible_rows(self, force_count: int = 0):
        """
        Populate the visible rows in the table with data.
        
        Args:
            force_count: If > 0, force populate this many rows regardless of visibility
        """
        try:
            if force_count > 0:
                # Force populate specified number of rows
                last_visible = min(self.total_rows - 1, force_count - 1)
                for row_index in range(0, last_visible + 1):
                    if row_index in self.loaded_data:
                        self._populate_row(row_index)
                self.logger.debug(f"Force populated {last_visible + 1} rows")
                return
            
            # Get visible row range
            first_visible = self.rowAt(0)
            last_visible = self.rowAt(self.viewport().height())
            
            # If table not yet rendered, populate first 500 rows
            if first_visible < 0:
                first_visible = 0
            if last_visible < 0:
                # Force populate first 500 rows
                last_visible = min(self.total_rows - 1, 499)
            
            # Populate visible rows
            for row_index in range(first_visible, last_visible + 1):
                if row_index >= self.total_rows:
                    break
                    
                if row_index in self.loaded_data:
                    self._populate_row(row_index)
            
            self.logger.debug(f"Populated rows {first_visible} to {last_visible}")
            
        except Exception as e:
            self.logger.error(f"Error populating visible rows: {e}")
    
    def _populate_row(self, row_index: int):
        """
        Populate a single row with data.
        
        Args:
            row_index: Index of the row to populate
        """
        if row_index not in self.loaded_data:
            return
        
        record = self.loaded_data[row_index]
        
        for col_index, column_name in enumerate(self.columns):
            value = record.get(column_name)
            
            # Get or create item
            item = self.item(row_index, col_index)
            if item is None:
                item = self._get_item_from_pool()
                # Set item flags to make it read-only and selectable
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.setItem(row_index, col_index, item)
            
            # Get item value
            raw_text = str(value) if value is not None else ""
            
            # Apply inline enrichment if this column is the chosen one
            if column_name == self.enrichment_column:
                dynamic_key = record.get('Dynamic_Key')
                if dynamic_key:
                    # Apply formatting: "Value [Key]"
                    enriched_text = self.format_enriched_value(raw_text, dynamic_key)
                    item.setText(enriched_text)
                    
                    # --- Verification Print: Confirming enrichment status ---
                    print(f"[Verification] Enrichment Applied | Table: {self.table_name} | Row: {row_index} | Column: {column_name} | Result: {raw_text} -> [{dynamic_key}]")
                else:
                    item.setText(raw_text)
            else:
                item.setText(raw_text)
    
    def _get_item_from_pool(self) -> QTableWidgetItem:
        """
        Get a QTableWidgetItem from the pool or create a new one.
        
        Returns:
            QTableWidgetItem instance
        """
        if self.item_pool:
            return self.item_pool.pop()
        return QTableWidgetItem()
    
    def _return_item_to_pool(self, item: QTableWidgetItem):
        """
        Return a QTableWidgetItem to the pool for reuse.
        
        Args:
            item: Item to return to pool
        """
        if len(self.item_pool) < self.max_pool_size:
            item.setText("")
            self.item_pool.append(item)
    
    def _on_vertical_scroll_changed(self, value: int):
        """
        Handle vertical scroll bar value changes.
        
        Args:
            value: New scroll bar value
        """
        # Use timer to debounce scroll events
        self.scroll_timer.stop()
        self.scroll_timer.start(self.scroll_delay_ms)
    
    def _on_scroll_timer(self):
        """Handle scroll timer timeout - load data if needed."""
        if self.is_loading:
            return
        
        try:
            # Get visible row range
            first_visible = self.rowAt(0)
            last_visible = self.rowAt(self.viewport().height())
            
            if first_visible < 0:
                first_visible = 0
            if last_visible < 0:
                last_visible = min(self.rowCount() - 1, first_visible + 100)
            
            # Check if we need to load more data
            buffer_start = max(0, first_visible - self.page_size)
            buffer_end = min(self.total_rows, last_visible + self.page_size)
            
            # Check if data is loaded for visible range
            needs_loading = False
            for row_index in range(buffer_start, buffer_end):
                if row_index not in self.loaded_data:
                    needs_loading = True
                    break
            
            if needs_loading:
                # Load data chunk
                self.is_loading = True
                self.loading_started.emit()
                
                # Calculate chunk to load
                chunk_start = (buffer_start // self.page_size) * self.page_size
                chunk_size = min(self.buffer_size, self.total_rows - chunk_start)
                
                self._load_data_chunk(chunk_start, chunk_size)
                
                # Clean up old data outside buffer
                self._cleanup_old_data(chunk_start, chunk_start + chunk_size)
                
                self.is_loading = False
                self.loading_finished.emit()
            
            # Populate visible rows
            self._populate_visible_rows()
            
        except Exception as e:
            self.logger.error(f"Error handling scroll: {e}")
            self.is_loading = False
            self.loading_finished.emit()
    
    def _cleanup_old_data(self, keep_start: int, keep_end: int):
        """
        Remove data outside the buffer range to free memory.
        
        Args:
            keep_start: Start of range to keep
            keep_end: End of range to keep
        """
        rows_to_remove = []
        
        for row_index in self.loaded_data.keys():
            if row_index < keep_start or row_index >= keep_end:
                rows_to_remove.append(row_index)
        
        for row_index in rows_to_remove:
            del self.loaded_data[row_index]
            
            # Return items to pool
            for col_index in range(self.columnCount()):
                item = self.item(row_index, col_index)
                if item:
                    self._return_item_to_pool(item)
                    self.setItem(row_index, col_index, None)
        
        if rows_to_remove:
            self.logger.debug(f"Cleaned up {len(rows_to_remove)} rows from memory")
    
    def apply_filter(
        self,
        where_clause: str,
        where_params: tuple = ()
    ) -> bool:
        """
        Apply a filter to the data and reload.
        
        Args:
            where_clause: SQL WHERE clause (without the WHERE keyword)
            where_params: Parameters for the WHERE clause
            
        Returns:
            bool: True if filter was applied successfully
        """
        try:
            self.where_clause = where_clause
            self.where_params = where_params
            
            # Clear existing data
            self.loaded_data.clear()
            self.current_offset = 0
            
            # Reload data
            return self.load_initial_data()
            
        except Exception as e:
            self.logger.error(f"Error applying filter: {e}")
            return False
    
    def clear_filter(self) -> bool:
        """
        Clear any applied filters and reload all data.
        
        Returns:
            bool: True if filter was cleared successfully
        """
        try:
            self.where_clause = None
            self.where_params = ()
            
            # Clear existing data
            self.loaded_data.clear()
            self.current_offset = 0
            
            # Reload data
            return self.load_initial_data()
            
        except Exception as e:
            self.logger.error(f"Error clearing filter: {e}")
            return False
    
    def refresh_data(self) -> bool:
        """
        Refresh the current view with updated data from database.
        
        Returns:
            bool: True if data was refreshed successfully
        """
        try:
            # Clear existing data
            self.loaded_data.clear()
            
            # Reload data
            return self.load_initial_data()
            
        except Exception as e:
            self.logger.error(f"Error refreshing data: {e}")
            return False
    
    def get_selected_records(self) -> List[Dict[str, Any]]:
        """
        Get the full database records for selected rows.
        
        Returns:
            List of dictionaries representing selected records
        """
        selected_records = []
        
        try:
            selected_rows = set()
            for item in self.selectedItems():
                selected_rows.add(item.row())
            
            for row_index in sorted(selected_rows):
                if row_index in self.loaded_data:
                    selected_records.append(self.loaded_data[row_index])
                else:
                    # Load this specific row if not in memory
                    select_cols = ", ".join(self.columns)
                    query = f"SELECT {select_cols} FROM {self.table_name}"
                    
                    if self.where_clause:
                        query += f" WHERE {self.where_clause}"
                    
                    if self.order_by:
                        query += f" ORDER BY {self.order_by}"
                    
                    query += f" LIMIT 1 OFFSET {row_index}"
                    
                    results = self.data_loader.execute_query(query, self.where_params)
                    if results:
                        selected_records.append(results[0])
            
            return selected_records
            
        except Exception as e:
            self.logger.error(f"Error getting selected records: {e}")
            return []
    
    def set_order_by(self, order_by: Optional[str]):
        """
        Set the ORDER BY clause for data loading.
        
        Args:
            order_by: ORDER BY clause (without ORDER BY keyword), or None
        """
        self.order_by = order_by
    
    def get_total_rows(self) -> int:
        """
        Get the total number of rows in the dataset.
        
        Returns:
            Total row count
        """
        return self.total_rows
    
    def get_loaded_row_count(self) -> int:
        """
        Get the number of rows currently loaded in memory.
        
        Returns:
            Number of rows loaded in memory
        """
        return len(self.loaded_data)
    
    def _force_viewport_update(self):
        """Force viewport update to ensure rows are visible."""
        try:
            self.viewport().update()
            self.update()
            # Force populate first 500 rows after viewport is ready
            self._populate_visible_rows(force_count=500)
        except Exception as e:
            self.logger.error(f"Error forcing viewport update: {e}")
    
    def _apply_styles_immediately(self):
        """Apply Crow Eye styles immediately after data is loaded."""
        try:
            from styles import CrowEyeStyles
            CrowEyeStyles.apply_table_styles(self)
        except Exception as e:
            self.logger.error(f"Error applying styles: {e}")
    
    def set_intelligence_db_path(self, case_directory: str):
        """
        Manually set the path to the intelligence database.
        
        Args:
            case_directory: Root directory of the case
        """
        intel_db = os.path.join(case_directory, "Crow_Intelligence.db")
        if os.path.exists(intel_db):
            # Update the mixin state
            super().set_intelligence_db_path(case_directory)
            self._intelligence_initialized = True
            
            # Re-attach if we have a connection
            if self.data_loader and self.data_loader.connection:
                try:
                    cursor = self.data_loader.connection.cursor()
                    self.attach_intelligence_db(cursor)
                    self.logger.info(f"Attached intelligence brain from {intel_db}")
                except Exception as e:
                    self.logger.error(f"Failed to attach intelligence: {e}")
        else:
            self.logger.warning(f"Intelligence database not found at {intel_db}")

    def _on_item_double_clicked(self, item: QTableWidgetItem):
        """
        Handle double-click on table item to show row details.
        
        Args:
            item: The table item that was double-clicked
        """
        try:
            from ui.row_detail_dialog import RowDetailDialog
            
            # Get the row data
            row = item.row()
            
            # Get data from loaded_data if available, otherwise fetch it
            if row in self.loaded_data:
                row_data = self.loaded_data[row]
            else:
                # Fetch this specific row from database
                select_cols = ", ".join(self.columns)
                query = f"SELECT {select_cols} FROM {self.table_name}"
                
                if self.where_clause:
                    query += f" WHERE {self.where_clause}"
                
                if self.order_by:
                    query += f" ORDER BY {self.order_by}"
                
                query += f" LIMIT 1 OFFSET {row}"
                
                results = self.data_loader.execute_query(query, self.where_params)
                if results:
                    row_data = results[0]
                else:
                    self.logger.warning(f"No data found for row {row}")
                    return
            
            # Determine Row Name (heuristic)
            row_name = "Unknown Row"
            # Priority keys to look for
            name_keys = ["Name", "Filename", "Executable Name", "Process Name", "Service Name", "Device Name", "User", "Key", "app_name", "folder_name"]
            
            # Try to find a matching key
            for key in name_keys:
                # Check case-insensitive
                for data_key in row_data.keys():
                    if data_key.lower() == key.lower() and row_data[data_key]:
                        row_name = str(row_data[data_key])
                        break
                if row_name != "Unknown Row":
                    break
            
            # Fallback: use the first available value if no priority key found
            if row_name == "Unknown Row" and row_data:
                # Get the first value from the data dictionary
                first_value = next(iter(row_data.values()))
                if first_value:
                    row_name = str(first_value)
            
            # Get Row Number (1-based)
            row_number = row + 1
            
            # Format table name for display
            display_name = self.table_name.replace('_', ' ').title()
            
            # Create and show the detail dialog
            dialog = RowDetailDialog(row_data, display_name, row_name, row_number, self.parent())
            dialog.show()
            
        except Exception as e:
            self.logger.error(f"Error showing row detail dialog: {e}")
            import traceback
            traceback.print_exc()

    def _initialize_intelligence(self):
        """
        Detect Crow_Intelligence.db and set up enrichment targets.
        Because we want our tables to be smarter than the average bear.
        """
        try:
            # Try to find case directory from data_loader
            if hasattr(self.data_loader, 'db_path') and self.data_loader.db_path:
                db_path_str = str(self.data_loader.db_path)
                case_dir = os.path.dirname(db_path_str)
                intel_db = os.path.join(case_dir, "Crow_Intelligence.db")
                
                if os.path.exists(intel_db):
                    self.set_intelligence_db_path(case_dir)
                    self.logger.info(f"Found the secret sauce at: {intel_db}")
                    
                    # Heuristic: Pick the best column to enrich
                    # We look for common identifiers defined in ENRICHMENT_TARGET_COLUMNS
                    found_target = False
                    for candidate in self.columns:
                        if candidate in self.ENRICHMENT_TARGET_COLUMNS:
                            self.enrichment_column = candidate
                            self.logger.info(f"Choosing '{candidate}' as the enrichment target. Good choice!")
                            found_target = True
                            break
                    
                    # If still not found, try common patterns
                    if not found_target:
                        pattern_candidates = [
                            'path', 'name', 'sid', 'mac', 'hash', 'user', 'id'
                        ]
                        for pattern in pattern_candidates:
                            for col in self.columns:
                                if pattern in col.lower():
                                    self.enrichment_column = col
                                    self.logger.info(f"Pattern match: Choosing '{col}' for enrichment.")
                                    found_target = True
                                    break
                            if found_target: break
                    
                    # If still None, pick the first one (usually Name/Date)
                    if not self.enrichment_column and self.columns:
                        self.enrichment_column = self.columns[0]
                else:
                    self.logger.debug("No Crow_Intelligence.db found. Table remains blissfully ignorant.")
            
            self._intelligence_initialized = True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize intelligence brain: {e}")
            self._intelligence_initialized = True  # Don't keep trying if it's broken
