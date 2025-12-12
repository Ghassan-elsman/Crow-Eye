"""
Pagination Control Widget for Crow Eye
Provides reusable pagination controls for data tables with page navigation and size selection.
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QComboBox, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont


class PaginationWidget(QWidget):
    """
    A reusable pagination control widget that provides:
    - Previous/Next page navigation
    - Current page display (Page X of Y)
    - Total record count display
    - Page size selector
    - Signals for page changes
    """
    
    # Signals
    page_changed = pyqtSignal(int)  # Emits new page number
    page_size_changed = pyqtSignal(int)  # Emits new page size
    
    def __init__(self, parent=None, table_type="Data"):
        """
        Initialize pagination widget.
        
        Args:
            parent: Parent widget
            table_type: Type of data being paginated (e.g., "MFT", "USN", "Correlated")
        """
        super().__init__(parent)
        self.table_type = table_type
        
        # Pagination state
        self.current_page = 1
        self.total_pages = 1
        self.total_records = 0
        self.current_page_size = 1000
        
        # Available page sizes
        self.page_sizes = [100, 500, 1000, 5000]
        
        self._init_ui()
        self._update_controls()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # Previous button
        self.prev_button = QPushButton("◀ Previous")
        self.prev_button.setFixedWidth(100)
        self.prev_button.clicked.connect(self._on_previous_clicked)
        layout.addWidget(self.prev_button)
        
        # Page info label
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setMinimumWidth(120)
        font = QFont()
        font.setBold(True)
        self.page_label.setFont(font)
        layout.addWidget(self.page_label)
        
        # Next button
        self.next_button = QPushButton("Next ▶")
        self.next_button.setFixedWidth(100)
        self.next_button.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_button)
        
        # Spacer
        layout.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        
        # Record count label
        self.record_label = QLabel("Total: 0 records")
        self.record_label.setAlignment(Qt.AlignCenter)
        self.record_label.setMinimumWidth(150)
        layout.addWidget(self.record_label)
        
        # Page size selector
        page_size_label = QLabel("Rows per page:")
        layout.addWidget(page_size_label)
        
        self.page_size_combo = QComboBox()
        self.page_size_combo.setFixedWidth(80)
        for size in self.page_sizes:
            self.page_size_combo.addItem(str(size), size)
        # Set default to 1000
        default_index = self.page_sizes.index(1000) if 1000 in self.page_sizes else 0
        self.page_size_combo.setCurrentIndex(default_index)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        layout.addWidget(self.page_size_combo)
        
        self.setLayout(layout)
    
    def _update_controls(self):
        """Update the state of pagination controls based on current page."""
        # Update page label
        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")
        
        # Update record count label
        self.record_label.setText(f"Total: {self.total_records:,} records")
        
        # Enable/disable navigation buttons
        self.prev_button.setEnabled(self.current_page > 1)
        self.next_button.setEnabled(self.current_page < self.total_pages)
    
    def _on_previous_clicked(self):
        """Handle previous button click."""
        if self.current_page > 1:
            self.current_page -= 1
            self._update_controls()
            self.page_changed.emit(self.current_page)
    
    def _on_next_clicked(self):
        """Handle next button click."""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._update_controls()
            self.page_changed.emit(self.current_page)
    
    def _on_page_size_changed(self, index):
        """Handle page size selection change."""
        new_page_size = self.page_size_combo.itemData(index)
        if new_page_size != self.current_page_size:
            self.current_page_size = new_page_size
            # Reset to page 1 when page size changes
            self.current_page = 1
            self.page_size_changed.emit(new_page_size)
    
    def update_pagination_info(self, total_records, current_page=None, page_size=None):
        """
        Update pagination information from loader metadata.
        
        Args:
            total_records: Total number of records in the dataset
            current_page: Current page number (optional, keeps current if not provided)
            page_size: Current page size (optional, keeps current if not provided)
        """
        self.total_records = total_records
        
        if page_size is not None:
            self.current_page_size = page_size
            # Update combo box selection
            try:
                index = self.page_sizes.index(page_size)
                self.page_size_combo.setCurrentIndex(index)
            except ValueError:
                pass  # Page size not in list
        
        # Calculate total pages
        if self.current_page_size > 0:
            self.total_pages = max(1, (total_records + self.current_page_size - 1) // self.current_page_size)
        else:
            self.total_pages = 1
        
        if current_page is not None:
            self.current_page = max(1, min(current_page, self.total_pages))
        else:
            # Ensure current page is within valid range
            self.current_page = max(1, min(self.current_page, self.total_pages))
        
        self._update_controls()
    
    def reset(self):
        """Reset pagination to initial state."""
        self.current_page = 1
        self.total_pages = 1
        self.total_records = 0
        self._update_controls()
    
    def get_current_page(self):
        """Get the current page number."""
        return self.current_page
    
    def get_page_size(self):
        """Get the current page size."""
        return self.current_page_size
    
    def set_page(self, page_number):
        """
        Set the current page programmatically.
        
        Args:
            page_number: Page number to navigate to
        """
        if 1 <= page_number <= self.total_pages:
            self.current_page = page_number
            self._update_controls()
            self.page_changed.emit(self.current_page)
    
    def get_pagination_state(self):
        """
        Get the current pagination state as a dictionary.
        
        Returns:
            dict: Current pagination state
        """
        return {
            'current_page': self.current_page,
            'page_size': self.current_page_size,
            'total_pages': self.total_pages,
            'total_records': self.total_records,
            'table_type': self.table_type
        }
    
    def restore_pagination_state(self, state):
        """
        Restore pagination state from a dictionary.
        
        Args:
            state: Dictionary containing pagination state
        """
        if not state:
            return
        
        self.current_page = state.get('current_page', 1)
        self.current_page_size = state.get('page_size', 1000)
        self.total_pages = state.get('total_pages', 1)
        self.total_records = state.get('total_records', 0)
        
        # Update combo box
        try:
            index = self.page_sizes.index(self.current_page_size)
            self.page_size_combo.setCurrentIndex(index)
        except ValueError:
            pass
        
        self._update_controls()
