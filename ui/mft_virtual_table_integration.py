"""
MFT Virtual Table Integration Example
Demonstrates how to integrate VirtualTableWidget with MFT data loading.

This module shows how to replace traditional table loading with virtual scrolling
for efficient handling of large MFT datasets.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.virtual_table_widget import VirtualTableWidget
from ui.progress_indicator import TableLoadingOverlay
from data.mft_loader import MFTDataLoader


class MFTVirtualTableWidget(QWidget):
    """
    Widget that displays MFT data using VirtualTableWidget for efficient loading.
    
    This widget demonstrates the integration pattern for task 9:
    - Uses VirtualTableWidget for lazy loading
    - Integrates with MFTDataLoader for data access
    - Shows loading overlay during initial data fetch
    - Provides pagination controls
    """
    
    def __init__(self, db_path: str, parent=None):
        """
        Initialize MFT virtual table widget.
        
        Args:
            db_path: Path to the MFT SQLite database
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.db_path = db_path
        self.mft_loader = None
        self.virtual_table = None
        self.loading_overlay = None
        
        self._init_ui()
        self._init_data_loader()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        
        # Info label
        self.info_label = QLabel("MFT Records - Virtual Scrolling Enabled")
        self.info_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self.info_label)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        button_layout.addWidget(self.refresh_btn)
        
        self.clear_filter_btn = QPushButton("Clear Filter")
        self.clear_filter_btn.clicked.connect(self._on_clear_filter_clicked)
        button_layout.addWidget(self.clear_filter_btn)
        
        button_layout.addStretch()
        
        self.stats_label = QLabel("Loading...")
        button_layout.addWidget(self.stats_label)
        
        layout.addLayout(button_layout)
        
        # Placeholder for virtual table (will be created after data loader init)
        self.table_container = QWidget()
        self.table_layout = QVBoxLayout(self.table_container)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table_container)
    
    def _init_data_loader(self):
        """Initialize the MFT data loader and virtual table."""
        try:
            # Initialize MFT data loader
            self.mft_loader = MFTDataLoader(self.db_path)
            
            if not self.mft_loader.connect():
                self.stats_label.setText("Error: Failed to connect to database")
                return
            
            # Get MFT columns
            if not self.mft_loader.table_exists('mft_records'):
                self.stats_label.setText("Error: mft_records table not found")
                return
            
            # Get column names from the table
            columns = self.mft_loader.get_columns('mft_records')
            
            if not columns:
                self.stats_label.setText("Error: No columns found in mft_records")
                return
            
            # Create virtual table widget
            # Configure for MFT data: 5000 rows per page, 10000 row buffer
            self.virtual_table = VirtualTableWidget(
                data_loader=self.mft_loader,
                table_name='mft_records',
                columns=columns,
                page_size=5000,  # As recommended in task 9
                buffer_size=10000,
                parent=self.table_container
            )
            
            # Set default ordering
            self.virtual_table.set_order_by('record_number ASC')
            
            # Connect signals
            self.virtual_table.loading_started.connect(self._on_loading_started)
            self.virtual_table.loading_finished.connect(self._on_loading_finished)
            
            # Add to layout
            self.table_layout.addWidget(self.virtual_table)
            
            # Create loading overlay
            self.loading_overlay = TableLoadingOverlay(self.virtual_table)
            
            # Load initial data
            self._load_initial_data()
            
        except Exception as e:
            self.stats_label.setText(f"Error: {str(e)}")
            print(f"[MFT Virtual Table] Error initializing: {e}")
    
    def _load_initial_data(self):
        """Load the initial page of MFT data."""
        try:
            self.loading_overlay.show_loading("Loading MFT records...")
            
            # Load initial data
            success = self.virtual_table.load_initial_data()
            
            if success:
                total_rows = self.virtual_table.get_total_rows()
                loaded_rows = self.virtual_table.get_loaded_row_count()
                self.stats_label.setText(
                    f"Total: {total_rows:,} records | "
                    f"Loaded: {loaded_rows:,} in memory"
                )
                print(f"[MFT Virtual Table] Successfully loaded {total_rows:,} records")
            else:
                self.stats_label.setText("Error: Failed to load data")
                print("[MFT Virtual Table] Failed to load initial data")
            
        except Exception as e:
            self.stats_label.setText(f"Error: {str(e)}")
            print(f"[MFT Virtual Table] Error loading initial data: {e}")
        finally:
            self.loading_overlay.hide_loading()
    
    def _on_loading_started(self):
        """Handle loading started signal."""
        self.loading_overlay.show_loading("Loading more data...")
    
    def _on_loading_finished(self):
        """Handle loading finished signal."""
        self.loading_overlay.hide_loading()
        
        # Update stats
        total_rows = self.virtual_table.get_total_rows()
        loaded_rows = self.virtual_table.get_loaded_row_count()
        self.stats_label.setText(
            f"Total: {total_rows:,} records | "
            f"Loaded: {loaded_rows:,} in memory"
        )
    
    def _on_refresh_clicked(self):
        """Handle refresh button click."""
        if self.virtual_table:
            self.loading_overlay.show_loading("Refreshing data...")
            self.virtual_table.refresh_data()
    
    def _on_clear_filter_clicked(self):
        """Handle clear filter button click."""
        if self.virtual_table:
            self.loading_overlay.show_loading("Clearing filter...")
            self.virtual_table.clear_filter()
    
    def apply_filter(self, where_clause: str, where_params: tuple = ()):
        """
        Apply a filter to the MFT data.
        
        Args:
            where_clause: SQL WHERE clause (without WHERE keyword)
            where_params: Parameters for the WHERE clause
        """
        if self.virtual_table:
            self.loading_overlay.show_loading("Applying filter...")
            self.virtual_table.apply_filter(where_clause, where_params)
    
    def get_selected_records(self):
        """
        Get the selected MFT records.
        
        Returns:
            List of dictionaries representing selected records
        """
        if self.virtual_table:
            return self.virtual_table.get_selected_records()
        return []
    
    def closeEvent(self, event):
        """Handle widget close event."""
        # Disconnect from database
        if self.mft_loader:
            self.mft_loader.disconnect()
        event.accept()


# ============================================================================
# Integration Instructions for Crow Eye.py
# ============================================================================

"""
To integrate VirtualTableWidget with MFT data in Crow Eye.py:

1. Import the necessary modules:
   ```python
   from ui.virtual_table_widget import VirtualTableWidget
   from ui.progress_indicator import TableLoadingOverlay
   from data.mft_loader import MFTDataLoader
   ```

2. Replace the existing MFT table widget with VirtualTableWidget:
   ```python
   # In setupUi or wherever MFT_table is created:
   
   # OLD CODE (remove):
   # self.MFT_table = QtWidgets.QTableWidget(self.MFT_tab)
   
   # NEW CODE:
   # Create container for virtual table
   self.MFT_table_container = QtWidgets.QWidget(self.MFT_tab)
   self.MFT_table_layout = QtWidgets.QVBoxLayout(self.MFT_table_container)
   
   # Virtual table will be created when data is loaded
   self.MFT_virtual_table = None
   self.MFT_loading_overlay = None
   ```

3. Update the load_mft_data method:
   ```python
   def load_mft_data(self, progress_callback=None):
       '''Load MFT data using VirtualTableWidget for efficient handling.'''
       try:
           # Get database path
           db_path = self.case_paths.get('databases', {}).get('mft')
           if not db_path or not os.path.exists(db_path):
               print("[MFT] Database not found")
               return
           
           # Initialize MFT data loader
           mft_loader = MFTDataLoader(db_path)
           if not mft_loader.connect():
               print("[MFT] Failed to connect to database")
               return
           
           # Get columns
           columns = mft_loader.get_columns('mft_records')
           
           # Create virtual table if not exists
           if self.MFT_virtual_table is None:
               self.MFT_virtual_table = VirtualTableWidget(
                   data_loader=mft_loader,
                   table_name='mft_records',
                   columns=columns,
                   page_size=5000,  # Recommended for MFT data
                   buffer_size=10000,
                   parent=self.MFT_table_container
               )
               
               # Set ordering
               self.MFT_virtual_table.set_order_by('record_number ASC')
               
               # Add to layout
               self.MFT_table_layout.addWidget(self.MFT_virtual_table)
               
               # Create loading overlay
               self.MFT_loading_overlay = TableLoadingOverlay(
                   self.MFT_virtual_table
               )
               
               # Connect signals
               self.MFT_virtual_table.loading_started.connect(
                   lambda: self.MFT_loading_overlay.show_loading("Loading MFT data...")
               )
               self.MFT_virtual_table.loading_finished.connect(
                   lambda: self.MFT_loading_overlay.hide_loading()
               )
           
           # Load initial data
           self.MFT_loading_overlay.show_loading("Loading MFT records...")
           success = self.MFT_virtual_table.load_initial_data()
           
           if success:
               total_rows = self.MFT_virtual_table.get_total_rows()
               print(f"[MFT] Successfully loaded {total_rows:,} records")
               if progress_callback:
                   progress_callback(f"[MFT] Loaded {total_rows:,} records")
           else:
               print("[MFT] Failed to load data")
               if progress_callback:
                   progress_callback("[MFT] Failed to load data")
           
       except Exception as e:
           print(f"[MFT] Error: {e}")
           if progress_callback:
               progress_callback(f"[MFT] Error: {e}")
       finally:
           if self.MFT_loading_overlay:
               self.MFT_loading_overlay.hide_loading()
   ```

4. Update any code that references self.MFT_table:
   ```python
   # OLD: self.MFT_table.setRowCount(0)
   # NEW: self.MFT_virtual_table.refresh_data()
   
   # OLD: selected_items = self.MFT_table.selectedItems()
   # NEW: selected_records = self.MFT_virtual_table.get_selected_records()
   ```

5. Benefits of this integration:
   - Handles datasets with 1M+ records without crashes
   - Loads data on-demand as user scrolls
   - Maintains smooth scrolling performance
   - Reduces memory usage significantly
   - Shows loading indicators during data fetch
   - Supports filtering and searching

6. Testing:
   - Test with small MFT database (< 10,000 records)
   - Test with medium MFT database (100,000 - 500,000 records)
   - Test with large MFT database (1M+ records)
   - Verify scrolling is smooth
   - Verify memory usage stays reasonable
   - Test filtering and search functionality
"""

