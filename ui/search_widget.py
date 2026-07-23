"""
Search widget component for database-driven search functionality.
Provides a reusable search interface that can be integrated into any tab.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from typing import Optional, Callable, Dict, Any
import time


class SearchWidget(QtWidgets.QWidget):
    """
    A reusable search widget with search input, buttons, and result display.
    
    Signals:
        search_requested: Emitted when user initiates a search (search_term, case_sensitive)
        clear_requested: Emitted when user clears the search
    """
    
    search_requested = QtCore.pyqtSignal(str, bool)  # search_term, case_sensitive
    clear_requested = QtCore.pyqtSignal()
    
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        """
        Initialize the search widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()
        self._search_active = False
        self._last_search_term = ""
        self._search_start_time = 0
        
    def _setup_ui(self):
        """Set up the user interface components."""
        # Main layout
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        
        # Search label
        search_label = QtWidgets.QLabel("Search:")
        search_label.setMinimumWidth(40)
        search_label.setMaximumWidth(50)
        main_layout.addWidget(search_label)
        
        # Search input field
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Enter search term...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(250)
        main_layout.addWidget(self.search_input, stretch=1)
        
        # Case sensitive checkbox
        self.case_sensitive_checkbox = QtWidgets.QCheckBox("Case")
        self.case_sensitive_checkbox.setChecked(False)
        self.case_sensitive_checkbox.setToolTip("Case sensitive search")
        main_layout.addWidget(self.case_sensitive_checkbox)
        
        # Search button
        self.search_button = QtWidgets.QPushButton("Search")
        self.search_button.setMinimumWidth(70)
        self.search_button.setMaximumWidth(80)
        self.search_button.setDefault(True)
        main_layout.addWidget(self.search_button)
        
        # Clear button
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.setMinimumWidth(70)
        self.clear_button.setMaximumWidth(80)
        self.clear_button.setEnabled(False)
        self.clear_button.setToolTip("Clear search results")
        main_layout.addWidget(self.clear_button)
        
        # Results label
        self.results_label = QtWidgets.QLabel("")
        self.results_label.setMinimumWidth(180)
        self.results_label.setMaximumWidth(250)
        self.results_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        main_layout.addWidget(self.results_label)
        
        # Add stretch to push everything to the left
        main_layout.addStretch()
        
        # Apply cyberpunk styling
        self._apply_styles()
        
    def _apply_styles(self):
        """Apply cyberpunk styling to the search widget components."""
        from styles import Colors, CrowEyeStyles
        
        # Apply compact styling to all components
        self.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
            }}
            QLabel {{
                color: {Colors.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: 600;
                padding: 2px 4px;
            }}
            QLineEdit {{
                background-color: {Colors.BG_TABLES};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
                min-height: 28px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Colors.ACCENT_CYAN};
            }}
            QCheckBox {{
                color: {Colors.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: 500;
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
            }}
            QPushButton {{
                background-color: {Colors.ACCENT_BLUE};
                color: {Colors.TEXT_PRIMARY};
                border: none;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 28px;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_CYAN};
                color: {Colors.BG_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: {Colors.ACCENT_PURPLE};
            }}
            QPushButton:disabled {{
                background-color: {Colors.BORDER_SUBTLE};
                color: {Colors.TEXT_MUTED};
            }}
        """)
        
        # Apply specific button styles
        self.search_button.setStyleSheet(CrowEyeStyles.SEARCH_BUTTON_STYLE)
        self.clear_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ACCENT_PURPLE};
                color: {Colors.TEXT_PRIMARY};
                border: none;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 28px;
            }}
            QPushButton:hover {{
                background-color: #A78BFA;
                color: {Colors.BG_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: #6D28D9;
            }}
        """)
        
    def _connect_signals(self):
        """Connect widget signals to handlers."""
        self.search_button.clicked.connect(self._on_search_clicked)
        self.clear_button.clicked.connect(self._on_clear_clicked)
        self.search_input.returnPressed.connect(self._on_search_clicked)
        
    def _on_search_clicked(self):
        """Handle search button click."""
        search_term = self.search_input.text().strip()
        
        if not search_term:
            QtWidgets.QMessageBox.warning(
                self,
                "Empty Search",
                "Please enter a search term."
            )
            return
        
        # Record search start time
        self._search_start_time = time.time()
        self._last_search_term = search_term
        self._search_active = True
        
        # Update UI state
        self.search_button.setEnabled(False)
        self.search_input.setEnabled(False)
        self.case_sensitive_checkbox.setEnabled(False)
        self.results_label.setText("Searching...")
        
        # Emit search signal
        case_sensitive = self.case_sensitive_checkbox.isChecked()
        self.search_requested.emit(search_term, case_sensitive)
        
    def _on_clear_clicked(self):
        """Handle clear button click."""
        self.search_input.clear()
        self.results_label.clear()
        self._search_active = False
        self._last_search_term = ""
        self.clear_button.setEnabled(False)
        
        # Emit clear signal
        self.clear_requested.emit()
        
    def set_search_results(self, result_count: int, total_count: Optional[int] = None):
        """
        Update the UI with search results.
        
        Args:
            result_count: Number of results found
            total_count: Total number of records (for displaying percentage)
        """
        # Calculate search time
        search_time = time.time() - self._search_start_time
        
        # Format results message
        if total_count is not None and total_count > 0:
            percentage = (result_count / total_count) * 100
            results_text = f"Found {result_count:,} of {total_count:,} records ({percentage:.1f}%) in {search_time:.2f}s"
        else:
            results_text = f"Found {result_count:,} results in {search_time:.2f}s"
        
        self.results_label.setText(results_text)
        self.results_label.setStyleSheet("")  # Clear any error styling
        
        # Update UI state
        self.search_button.setEnabled(True)
        self.search_input.setEnabled(True)
        self.case_sensitive_checkbox.setEnabled(True)
        self.clear_button.setEnabled(True)
        
    def set_search_error(self, error_message: str):
        """
        Display an error message.
        
        Args:
            error_message: Error message to display
        """
        from styles import Colors
        
        self.results_label.setText(f"Error: {error_message}")
        self.results_label.setStyleSheet(f"color: {Colors.ERROR};")
        
        # Re-enable UI
        self.search_button.setEnabled(True)
        self.search_input.setEnabled(True)
        self.case_sensitive_checkbox.setEnabled(True)
        
    def reset(self):
        """Reset the search widget to initial state."""
        self.search_input.clear()
        self.results_label.clear()
        self.results_label.setStyleSheet("")
        self._search_active = False
        self._last_search_term = ""
        self.clear_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.search_input.setEnabled(True)
        self.case_sensitive_checkbox.setEnabled(True)
        
    def is_search_active(self) -> bool:
        """Check if a search is currently active."""
        return self._search_active
        
    def get_last_search_term(self) -> str:
        """Get the last search term used."""
        return self._last_search_term
        
    def set_enabled(self, enabled: bool):
        """Enable or disable the entire search widget."""
        self.search_input.setEnabled(enabled)
        self.search_button.setEnabled(enabled)
        self.case_sensitive_checkbox.setEnabled(enabled)
        self.clear_button.setEnabled(False if not enabled else self.clear_button.isEnabled())
