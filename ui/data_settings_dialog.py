"""
Data Settings Dialog for Crow Eye
Provides UI for configuring pagination, search, and indexing preferences.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from typing import Optional
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.data_config import DataConfig


class DataSettingsDialog(QtWidgets.QDialog):
    """Dialog for configuring data loading and search settings."""
    
    def __init__(self, config: DataConfig, parent: Optional[QtWidgets.QWidget] = None):
        """
        Initialize data settings dialog.
        
        Args:
            config: DataConfig instance
            parent: Parent widget
        """
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Data Settings")
        self.setModal(True)
        self.resize(600, 500)
        
        self._init_ui()
        self._load_current_settings()
    
    def _init_ui(self) -> None:
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Create tab widget for different setting categories
        tab_widget = QtWidgets.QTabWidget()
        
        # Pagination tab
        pagination_tab = self._create_pagination_tab()
        tab_widget.addTab(pagination_tab, "Pagination")
        
        # Search tab
        search_tab = self._create_search_tab()
        tab_widget.addTab(search_tab, "Search")
        
        # Indexes tab
        indexes_tab = self._create_indexes_tab()
        tab_widget.addTab(indexes_tab, "Indexes")
        
        # UI tab
        ui_tab = self._create_ui_tab()
        tab_widget.addTab(ui_tab, "UI")
        
        layout.addWidget(tab_widget)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        reset_button = QtWidgets.QPushButton("Reset to Defaults")
        reset_button.clicked.connect(self._reset_to_defaults)
        button_layout.addWidget(reset_button)
        
        button_layout.addStretch()
        
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        save_button = QtWidgets.QPushButton("Save")
        save_button.clicked.connect(self._save_settings)
        save_button.setDefault(True)
        button_layout.addWidget(save_button)
        
        layout.addLayout(button_layout)
    
    def _create_pagination_tab(self) -> QtWidgets.QWidget:
        """Create pagination settings tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(widget)
        
        # Default page size
        self.default_page_size_spin = QtWidgets.QSpinBox()
        self.default_page_size_spin.setRange(100, 50000)
        self.default_page_size_spin.setSingleStep(100)
        layout.addRow("Default Page Size:", self.default_page_size_spin)
        
        # Buffer size
        self.buffer_size_spin = QtWidgets.QSpinBox()
        self.buffer_size_spin.setRange(500, 20000)
        self.buffer_size_spin.setSingleStep(500)
        layout.addRow("Buffer Size:", self.buffer_size_spin)
        
        # Max memory rows
        self.max_memory_rows_spin = QtWidgets.QSpinBox()
        self.max_memory_rows_spin.setRange(1000, 100000)
        self.max_memory_rows_spin.setSingleStep(1000)
        layout.addRow("Max Memory Rows:", self.max_memory_rows_spin)
        
        # Preload pages
        self.preload_pages_spin = QtWidgets.QSpinBox()
        self.preload_pages_spin.setRange(0, 10)
        layout.addRow("Preload Pages:", self.preload_pages_spin)
        
        # Add separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout.addRow(line)
        
        # Table-specific settings
        layout.addRow(QtWidgets.QLabel("<b>Table-Specific Settings</b>"))
        
        # MFT page size
        self.mft_page_size_spin = QtWidgets.QSpinBox()
        self.mft_page_size_spin.setRange(100, 50000)
        self.mft_page_size_spin.setSingleStep(100)
        layout.addRow("MFT Page Size:", self.mft_page_size_spin)
        
        # USN page size
        self.usn_page_size_spin = QtWidgets.QSpinBox()
        self.usn_page_size_spin.setRange(100, 50000)
        self.usn_page_size_spin.setSingleStep(100)
        layout.addRow("USN Page Size:", self.usn_page_size_spin)
        
        # Correlated page size
        self.correlated_page_size_spin = QtWidgets.QSpinBox()
        self.correlated_page_size_spin.setRange(100, 50000)
        self.correlated_page_size_spin.setSingleStep(100)
        layout.addRow("Correlated Page Size:", self.correlated_page_size_spin)
        
        # Add help text
        help_label = QtWidgets.QLabel(
            "<i>Note: Larger page sizes improve performance but use more memory. "
            "Adjust based on your system's available RAM.</i>"
        )
        help_label.setWordWrap(True)
        layout.addRow(help_label)
        
        layout.addStretch()
        return widget
    
    def _create_search_tab(self) -> QtWidgets.QWidget:
        """Create search settings tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(widget)
        
        # Case sensitive
        self.case_sensitive_check = QtWidgets.QCheckBox()
        layout.addRow("Case Sensitive by Default:", self.case_sensitive_check)
        
        # Max results
        self.max_results_spin = QtWidgets.QSpinBox()
        self.max_results_spin.setRange(100, 10000)
        self.max_results_spin.setSingleStep(100)
        layout.addRow("Max Search Results:", self.max_results_spin)
        
        # Max results per table
        self.max_results_per_table_spin = QtWidgets.QSpinBox()
        self.max_results_per_table_spin.setRange(10, 1000)
        self.max_results_per_table_spin.setSingleStep(10)
        layout.addRow("Max Results Per Table:", self.max_results_per_table_spin)
        
        # Search timeout
        self.search_timeout_spin = QtWidgets.QSpinBox()
        self.search_timeout_spin.setRange(1000, 30000)
        self.search_timeout_spin.setSingleStep(1000)
        self.search_timeout_spin.setSuffix(" ms")
        layout.addRow("Search Timeout:", self.search_timeout_spin)
        
        # Debounce delay
        self.debounce_spin = QtWidgets.QSpinBox()
        self.debounce_spin.setRange(0, 2000)
        self.debounce_spin.setSingleStep(50)
        self.debounce_spin.setSuffix(" ms")
        layout.addRow("Search Debounce Delay:", self.debounce_spin)
        
        # Enable suggestions
        self.enable_suggestions_check = QtWidgets.QCheckBox()
        layout.addRow("Enable Search Suggestions:", self.enable_suggestions_check)
        
        # Add help text
        help_label = QtWidgets.QLabel(
            "<i>Debounce delay controls how long to wait after typing before starting a search. "
            "Higher values reduce database load but feel less responsive.</i>"
        )
        help_label.setWordWrap(True)
        layout.addRow(help_label)
        
        layout.addStretch()
        return widget
    
    def _create_indexes_tab(self) -> QtWidgets.QWidget:
        """Create index settings tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(widget)
        
        # Auto-create indexes
        self.auto_create_indexes_check = QtWidgets.QCheckBox()
        layout.addRow("Auto-Create Indexes:", self.auto_create_indexes_check)
        
        # Analyze on startup
        self.analyze_on_startup_check = QtWidgets.QCheckBox()
        layout.addRow("Analyze on Startup:", self.analyze_on_startup_check)
        
        # Add help text
        help_label = QtWidgets.QLabel(
            "<i>Auto-creating indexes improves search performance but may slow down "
            "initial database loading. Analyzing on startup can help optimize query "
            "performance but adds startup time.</i>"
        )
        help_label.setWordWrap(True)
        layout.addRow(help_label)
        
        layout.addStretch()
        return widget
    
    def _create_ui_tab(self) -> QtWidgets.QWidget:
        """Create UI settings tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(widget)
        
        # Progress threshold
        self.progress_threshold_spin = QtWidgets.QSpinBox()
        self.progress_threshold_spin.setRange(0, 2000)
        self.progress_threshold_spin.setSingleStep(50)
        self.progress_threshold_spin.setSuffix(" ms")
        layout.addRow("Progress Indicator Threshold:", self.progress_threshold_spin)
        
        # Highlight duration
        self.highlight_duration_spin = QtWidgets.QSpinBox()
        self.highlight_duration_spin.setRange(0, 10000)
        self.highlight_duration_spin.setSingleStep(500)
        self.highlight_duration_spin.setSuffix(" ms")
        layout.addRow("Highlight Duration:", self.highlight_duration_spin)
        
        # Scroll buffer rows
        self.scroll_buffer_spin = QtWidgets.QSpinBox()
        self.scroll_buffer_spin.setRange(0, 500)
        self.scroll_buffer_spin.setSingleStep(10)
        layout.addRow("Scroll Buffer Rows:", self.scroll_buffer_spin)
        
        # Add help text
        help_label = QtWidgets.QLabel(
            "<i>Progress threshold controls when loading indicators appear. "
            "Highlight duration controls how long search results stay highlighted. "
            "Set to 0 for no automatic timeout.</i>"
        )
        help_label.setWordWrap(True)
        layout.addRow(help_label)
        
        layout.addStretch()
        return widget
    
    def _load_current_settings(self) -> None:
        """Load current settings from config into UI."""
        # Pagination
        self.default_page_size_spin.setValue(self.config.get_default_page_size())
        self.buffer_size_spin.setValue(self.config.get_buffer_size())
        self.max_memory_rows_spin.setValue(self.config.get_max_memory_rows())
        self.preload_pages_spin.setValue(self.config.get_preload_pages())
        
        # Table-specific
        self.mft_page_size_spin.setValue(self.config.get_table_page_size('mft'))
        self.usn_page_size_spin.setValue(self.config.get_table_page_size('usn'))
        self.correlated_page_size_spin.setValue(self.config.get_table_page_size('correlated'))
        
        # Search
        self.case_sensitive_check.setChecked(self.config.get_search_case_sensitive())
        self.max_results_spin.setValue(self.config.get_search_max_results())
        self.max_results_per_table_spin.setValue(self.config.get_search_max_results_per_table())
        self.search_timeout_spin.setValue(self.config.get_search_timeout_ms())
        self.debounce_spin.setValue(self.config.get_search_debounce_ms())
        self.enable_suggestions_check.setChecked(self.config.get_search_suggestions_enabled())
        
        # Indexes
        self.auto_create_indexes_check.setChecked(self.config.get_auto_create_indexes())
        self.analyze_on_startup_check.setChecked(self.config.get_analyze_on_startup())
        
        # UI
        self.progress_threshold_spin.setValue(self.config.get_progress_threshold_ms())
        self.highlight_duration_spin.setValue(self.config.get_highlight_duration_ms())
        self.scroll_buffer_spin.setValue(self.config.get_scroll_buffer_rows())
    
    def _save_settings(self) -> None:
        """Save settings from UI to config."""
        # Pagination
        self.config.set_default_page_size(self.default_page_size_spin.value())
        self.config.set_buffer_size(self.buffer_size_spin.value())
        self.config.set_max_memory_rows(self.max_memory_rows_spin.value())
        self.config.set_preload_pages(self.preload_pages_spin.value())
        
        # Table-specific
        self.config.set_table_page_size('mft', self.mft_page_size_spin.value())
        self.config.set_table_page_size('usn', self.usn_page_size_spin.value())
        self.config.set_table_page_size('correlated', self.correlated_page_size_spin.value())
        
        # Search
        self.config.set_search_case_sensitive(self.case_sensitive_check.isChecked())
        self.config.set_search_max_results(self.max_results_spin.value())
        self.config.set_search_max_results_per_table(self.max_results_per_table_spin.value())
        self.config.set_search_timeout_ms(self.search_timeout_spin.value())
        self.config.set_search_debounce_ms(self.debounce_spin.value())
        self.config.set_search_suggestions_enabled(self.enable_suggestions_check.isChecked())
        
        # Indexes
        self.config.set_auto_create_indexes(self.auto_create_indexes_check.isChecked())
        self.config.set_analyze_on_startup(self.analyze_on_startup_check.isChecked())
        
        # UI
        self.config.set_progress_threshold_ms(self.progress_threshold_spin.value())
        self.config.set_highlight_duration_ms(self.highlight_duration_spin.value())
        self.config.set_scroll_buffer_rows(self.scroll_buffer_spin.value())
        
        # Validate and accept
        if self.config.validate_config():
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Configuration",
                "Some configuration values are invalid. Please check your settings."
            )
    
    def _reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset to Defaults",
            "Are you sure you want to reset all settings to their default values?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.config.reset_to_defaults()
            self._load_current_settings()


if __name__ == '__main__':
    """Test the settings dialog."""
    app = QtWidgets.QApplication(sys.argv)
    
    # Create a test config
    config = DataConfig()
    
    # Show dialog
    dialog = DataSettingsDialog(config)
    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        print("Settings saved!")
        print(f"Default page size: {config.get_default_page_size()}")
        print(f"Buffer size: {config.get_buffer_size()}")
        print(f"Case sensitive: {config.get_search_case_sensitive()}")
    else:
        print("Settings cancelled")
    
    sys.exit(0)
