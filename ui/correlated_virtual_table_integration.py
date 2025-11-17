"""
Correlated Data Virtual Table Integration Example
Demonstrates how to integrate VirtualTableWidget with correlated MFT-USN data loading.

This module shows how to replace traditional table loading with virtual scrolling
for efficient handling of large correlated datasets.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox
from PyQt5.QtCore import Qt
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.virtual_table_widget import VirtualTableWidget
from ui.progress_indicator import TableLoadingOverlay
from data.correlated_loader import CorrelatedDataLoader


class CorrelatedVirtualTableWidget(QWidget):
    """
    Widget that displays correlated MFT-USN data using VirtualTableWidget for efficient loading.
    
    This widget demonstrates the integration pattern for task 11:
    - Uses VirtualTableWidget for lazy loading
    - Integrates with CorrelatedDataLoader for data access
    - Shows loading overlay during initial data fetch
    - Provides filtering by correlation score, path, time range
    - Configured for correlated datasets
    """
    
    def __init__(self, db_path: str, parent=None):
        """
        Initialize correlated data virtual table widget.
        
        Args:
            db_path: Path to the correlated data SQLite database
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.db_path = db_path
        self.correlated_loader = None
        self.virtual_table = None
        self.loading_overlay = None
        
        self._init_ui()
        self._init_data_loader()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        
        # Info label
        self.info_label = QLabel("Correlated MFT-USN Data - Virtual Scrolling Enabled")
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
        
        # Correlation score filter
        self.score_label = QLabel("Min Score:")
        button_layout.addWidget(self.score_label)
        
        self.score_combo = QComboBox()
        self.score_combo.addItems(["All", "0.5+", "0.7+", "0.8+", "0.9+"])
        self.score_combo.currentTextChanged.connect(self._on_score_filter_changed)
        button_layout.addWidget(self.score_combo)
        
        self.filter_deleted_btn = QPushButton("Show Deleted")
        self.filter_deleted_btn.clicked.connect(self._on_filter_deleted_clicked)
        button_layout.addWidget(self.filter_deleted_btn)
        
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
        """Initialize the correlated data loader and virtual table."""
        try:
            # Initialize correlated data loader
            self.correlated_loader = CorrelatedDataLoader(self.db_path)
            
            if not self.correlated_loader.connect():
                self.stats_label.setText("Error: Failed to connect to database")
                return
            
            # Get correlated data columns
            if not self.correlated_loader.table_exists('mft_usn_correlated'):
                self.stats_label.setText("Error: mft_usn_correlated table not found")
                return
            
            # Get column names from the table
            columns = self.correlated_loader.get_columns('mft_usn_correlated')
            
            if not columns:
                self.stats_label.setText("Error: No columns found in mft_usn_correlated")
                return
            
            # Create virtual table widget
            # Configure for correlated data: 5000 rows per page, 10000 row buffer (task 11 recommendation)
            self.virtual_table = VirtualTableWidget(
                data_loader=self.correlated_loader,
                table_name='mft_usn_correlated',
                columns=columns,
                page_size=5000,  # As recommended in task 11 for correlated data
                buffer_size=10000,
                parent=self.table_container
            )
            
            # Set default ordering (by MFT record number)
            self.virtual_table.set_order_by('mft_record_number ASC')
            
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
            print(f"[Correlated Virtual Table] Error initializing: {e}")
    
    def _load_initial_data(self):
        """Load the initial page of correlated data."""
        try:
            self.loading_overlay.show_loading("Loading correlated data...")
            
            # Load initial data
            success = self.virtual_table.load_initial_data()
            
            if success:
                total_rows = self.virtual_table.get_total_rows()
                loaded_rows = self.virtual_table.get_loaded_row_count()
                
                # Get correlation statistics
                stats = self.correlated_loader.get_correlation_statistics()
                avg_score = stats.get('average_correlation_score', 0)
                high_conf = stats.get('high_confidence_count', 0)
                unique_mft = stats.get('unique_mft_records', 0)
                unique_usn = stats.get('unique_usn_events', 0)
                
                self.stats_label.setText(
                    f"Total: {total_rows:,} | "
                    f"Loaded: {loaded_rows:,} | "
                    f"Avg Score: {avg_score:.2f} | "
                    f"High Conf: {high_conf:,}"
                )
                
                print(f"[Correlated Virtual Table] Successfully loaded {total_rows:,} correlations")
                print(f"[Correlated Virtual Table] Average score: {avg_score:.2f}")
                print(f"[Correlated Virtual Table] High confidence: {high_conf:,}")
                print(f"[Correlated Virtual Table] Unique MFT records: {unique_mft:,}")
                print(f"[Correlated Virtual Table] Unique USN events: {unique_usn:,}")
            else:
                self.stats_label.setText("Error: Failed to load data")
                print("[Correlated Virtual Table] Failed to load initial data")
            
        except Exception as e:
            self.stats_label.setText(f"Error: {str(e)}")
            print(f"[Correlated Virtual Table] Error loading initial data: {e}")
        finally:
            self.loading_overlay.hide_loading()
    
    def _on_loading_started(self):
        """Handle loading started signal."""
        self.loading_overlay.show_loading("Loading more correlated data...")
    
    def _on_loading_finished(self):
        """Handle loading finished signal."""
        self.loading_overlay.hide_loading()
        
        # Update stats
        total_rows = self.virtual_table.get_total_rows()
        loaded_rows = self.virtual_table.get_loaded_row_count()
        self.stats_label.setText(
            f"Total: {total_rows:,} | "
            f"Loaded: {loaded_rows:,}"
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
            self.score_combo.setCurrentText("All")
    
    def _on_score_filter_changed(self, text: str):
        """Handle correlation score filter change."""
        if not self.virtual_table:
            return
        
        score_map = {
            "All": None,
            "0.5+": 0.5,
            "0.7+": 0.7,
            "0.8+": 0.8,
            "0.9+": 0.9
        }
        
        min_score = score_map.get(text)
        if min_score is None:
            self._on_clear_filter_clicked()
        else:
            self.loading_overlay.show_loading(f"Filtering by score >= {min_score}...")
            self.virtual_table.apply_filter("correlation_score >= ?", (min_score,))
    
    def _on_filter_deleted_clicked(self):
        """Filter to show only deleted files."""
        if self.virtual_table:
            self.loading_overlay.show_loading("Filtering deleted files...")
            self.virtual_table.apply_filter(
                "(mft_flags & 1) = 0 OR usn_reason LIKE '%FILE_DELETE%'"
            )
    
    def apply_filter(self, where_clause: str, where_params: tuple = ()):
        """
        Apply a filter to the correlated data.
        
        Args:
            where_clause: SQL WHERE clause (without WHERE keyword)
            where_params: Parameters for the WHERE clause
        """
        if self.virtual_table:
            self.loading_overlay.show_loading("Applying filter...")
            self.virtual_table.apply_filter(where_clause, where_params)
    
    def filter_by_mft_record(self, mft_record_number: int):
        """
        Filter by MFT record number.
        
        Args:
            mft_record_number: The MFT record number to filter by
        """
        self.apply_filter("mft_record_number = ?", (mft_record_number,))
    
    def filter_by_path(self, path_pattern: str):
        """
        Filter by file path pattern.
        
        Args:
            path_pattern: The path pattern to search for
        """
        self.apply_filter("reconstructed_path LIKE ?", (f'%{path_pattern}%',))
    
    def filter_by_time_range(self, start_time: str, end_time: str):
        """
        Filter by time range.
        
        Args:
            start_time: Start timestamp
            end_time: End timestamp
        """
        self.apply_filter(
            "mft_modification_time BETWEEN ? AND ?",
            (start_time, end_time)
        )
    
    def filter_by_correlation_score(self, min_score: float, max_score: float = None):
        """
        Filter by correlation score range.
        
        Args:
            min_score: Minimum correlation score
            max_score: Maximum correlation score (optional)
        """
        if max_score:
            self.apply_filter(
                "correlation_score BETWEEN ? AND ?",
                (min_score, max_score)
            )
        else:
            self.apply_filter("correlation_score >= ?", (min_score,))
    
    def get_selected_records(self):
        """
        Get the selected correlated records.
        
        Returns:
            List of dictionaries representing selected records
        """
        if self.virtual_table:
            return self.virtual_table.get_selected_records()
        return []
    
    def closeEvent(self, event):
        """Handle widget close event."""
        # Disconnect from database
        if self.correlated_loader:
            self.correlated_loader.disconnect()
        event.accept()


# ============================================================================
# Integration Instructions for Crow Eye.py
# ============================================================================

"""
To integrate VirtualTableWidget with correlated data in Crow Eye.py:

1. Import the necessary modules:
   ```python
   from ui.virtual_table_widget import VirtualTableWidget
   from ui.progress_indicator import TableLoadingOverlay
   from data.correlated_loader import CorrelatedDataLoader
   ```

2. Replace the existing correlated table widget with VirtualTableWidget:
   ```python
   # In setupUi or wherever Correlated_table is created:
   
   # OLD CODE (remove):
   # self.Correlated_table = QtWidgets.QTableWidget(self.Correlated_tab)
   
   # NEW CODE:
   # Create container for virtual table
   self.Correlated_table_container = QtWidgets.QWidget(self.Correlated_tab)
   self.Correlated_table_layout = QtWidgets.QVBoxLayout(self.Correlated_table_container)
   
   # Virtual table will be created when data is loaded
   self.Correlated_virtual_table = None
   self.Correlated_loading_overlay = None
   ```

3. Update the load_correlated_data method:
   ```python
   def load_correlated_data(self, progress_callback=None):
       '''Load correlated MFT-USN data using VirtualTableWidget.'''
       try:
           # Get database path
           db_path = self.case_paths.get('databases', {}).get('correlated')
           if not db_path or not os.path.exists(db_path):
               print("[Correlated] Database not found")
               return
           
           # Initialize correlated data loader
           correlated_loader = CorrelatedDataLoader(db_path)
           if not correlated_loader.connect():
               print("[Correlated] Failed to connect to database")
               return
           
           # Get columns
           columns = correlated_loader.get_columns('mft_usn_correlated')
           
           # Create virtual table if not exists
           if self.Correlated_virtual_table is None:
               self.Correlated_virtual_table = VirtualTableWidget(
                   data_loader=correlated_loader,
                   table_name='mft_usn_correlated',
                   columns=columns,
                   page_size=5000,  # Recommended for correlated data (task 11)
                   buffer_size=10000,
                   parent=self.Correlated_table_container
               )
               
               # Set ordering
               self.Correlated_virtual_table.set_order_by('mft_record_number ASC')
               
               # Add to layout
               self.Correlated_table_layout.addWidget(self.Correlated_virtual_table)
               
               # Create loading overlay
               self.Correlated_loading_overlay = TableLoadingOverlay(
                   self.Correlated_virtual_table
               )
               
               # Connect signals
               self.Correlated_virtual_table.loading_started.connect(
                   lambda: self.Correlated_loading_overlay.show_loading("Loading correlated data...")
               )
               self.Correlated_virtual_table.loading_finished.connect(
                   lambda: self.Correlated_loading_overlay.hide_loading()
               )
           
           # Load initial data
           self.Correlated_loading_overlay.show_loading("Loading correlated data...")
           success = self.Correlated_virtual_table.load_initial_data()
           
           if success:
               total_rows = self.Correlated_virtual_table.get_total_rows()
               print(f"[Correlated] Successfully loaded {total_rows:,} correlations")
               if progress_callback:
                   progress_callback(f"[Correlated] Loaded {total_rows:,} correlations")
           else:
               print("[Correlated] Failed to load data")
               if progress_callback:
                   progress_callback("[Correlated] Failed to load data")
           
       except Exception as e:
           print(f"[Correlated] Error: {e}")
           if progress_callback:
               progress_callback(f"[Correlated] Error: {e}")
       finally:
           if self.Correlated_loading_overlay:
               self.Correlated_loading_overlay.hide_loading()
   ```

4. Benefits for correlated data:
   - Handles large correlation datasets efficiently
   - Filters by correlation score, path, MFT record, time range
   - Shows correlation statistics (average score, high confidence count)
   - Supports timeline analysis
   - Identifies suspicious activity patterns

5. Correlated data filtering examples:
   ```python
   # Filter by high confidence correlations
   self.Correlated_virtual_table.apply_filter("correlation_score >= 0.8")
   
   # Filter by specific MFT record
   self.Correlated_virtual_table.apply_filter("mft_record_number = ?", (12345,))
   
   # Filter by path
   self.Correlated_virtual_table.apply_filter(
       "reconstructed_path LIKE ?",
       ('%Windows\\System32%',)
   )
   
   # Filter deleted files
   self.Correlated_virtual_table.apply_filter(
       "(mft_flags & 1) = 0 OR usn_reason LIKE '%FILE_DELETE%'"
   )
   ```
"""

