"""
Search utilities for result navigation and highlighting.
Provides functionality to navigate to search results and highlight them in tables.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QTimer, QMetaObject
from typing import Optional, Dict, Any, Callable, Tuple
import logging

# Import colors from centralized styles module
try:
    from styles import Colors
    HIGHLIGHT_COLOR = Colors.ACCENT_CYAN
    HIGHLIGHT_BG_COLOR = "#1a4d4d"  # Dark cyan background
    HIGHLIGHT_BORDER_COLOR = Colors.ACCENT_CYAN
except ImportError:
    # Fallback if styles module not available
    HIGHLIGHT_COLOR = "#00FFFF"
    HIGHLIGHT_BG_COLOR = "#1a4d4d"
    HIGHLIGHT_BORDER_COLOR = "#00FFFF"


class SearchUtils:
    """
    Utility class for search result navigation and highlighting.
    
    Provides methods to:
    - Navigate to search results in different tabs
    - Highlight rows with cyberpunk-style visual indicators
    - Auto-scroll to highlighted rows
    - Manage highlight timeouts and user interaction clearing
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize SearchUtils.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        
        # Track currently highlighted items
        self._highlighted_items: Dict[QtWidgets.QTableWidget, list] = {}
        self._highlight_timers: Dict[QtWidgets.QTableWidget, QTimer] = {}
        self._original_styles: Dict[QtWidgets.QTableWidget, Dict[int, Dict[int, Tuple]]] = {}
        self._cell_click_connections: Dict[QtWidgets.QTableWidget, Any] = {}
        
    def highlight_search_result(
        self,
        table_widget: QtWidgets.QTableWidget,
        row_index: int,
        matched_columns: Optional[list] = None,
        duration_ms: int = 3000,
        auto_scroll: bool = True
    ) -> bool:
        """
        Highlight a search result in a table widget.
        
        Args:
            table_widget: QTableWidget to highlight in
            row_index: Row index to highlight
            matched_columns: Optional list of column names that matched (for column-specific highlighting)
            duration_ms: Duration to keep highlight (milliseconds), 0 for permanent
            auto_scroll: Whether to auto-scroll to the highlighted row
            
        Returns:
            bool: True if highlighting was successful, False otherwise
        """
        try:
            # Validate row index
            if row_index < 0 or row_index >= table_widget.rowCount():
                self.logger.warning(f"Invalid row index: {row_index}")
                return False
            
            # Clear any existing highlights on this table
            self.clear_highlight(table_widget)
            
            # Auto-scroll to the row if requested
            if auto_scroll:
                self._scroll_to_row(table_widget, row_index)
            
            # Store original styles for restoration
            if table_widget not in self._original_styles:
                self._original_styles[table_widget] = {}
            
            self._original_styles[table_widget][row_index] = {}
            
            # Determine which columns to highlight
            columns_to_highlight = []
            
            if matched_columns:
                # Highlight only matched columns
                for col_index in range(table_widget.columnCount()):
                    header_item = table_widget.horizontalHeaderItem(col_index)
                    if header_item and header_item.text() in matched_columns:
                        columns_to_highlight.append(col_index)
            
            # If no matched columns specified or found, highlight entire row
            if not columns_to_highlight:
                columns_to_highlight = list(range(table_widget.columnCount()))
            
            # Apply highlight to cells
            highlighted_items = []
            
            for col_index in columns_to_highlight:
                item = table_widget.item(row_index, col_index)
                
                if item is None:
                    # Create item if it doesn't exist, preserving any model data
                    item = QtWidgets.QTableWidgetItem("")
                    # Try to get data from model if available
                    model = table_widget.model()
                    if model:
                        model_index = model.index(row_index, col_index)
                        data = model.data(model_index, Qt.DisplayRole)
                        if data:
                            item.setText(str(data))
                    table_widget.setItem(row_index, col_index, item)
                
                # Store original background and foreground
                original_bg = item.background()
                original_fg = item.foreground()
                self._original_styles[table_widget][row_index][col_index] = (original_bg, original_fg)
                
                # Apply cyberpunk highlight style
                self._apply_highlight_style(item)
                highlighted_items.append((row_index, col_index))
            
            # Store highlighted items for this table
            self._highlighted_items[table_widget] = highlighted_items
            
            # Set up highlight timeout if duration specified
            if duration_ms > 0:
                self._setup_highlight_timer(table_widget, duration_ms)
            
            # Connect to user interaction events to clear highlight
            self._connect_clear_on_interaction(table_widget)
            
            self.logger.info(f"Highlighted row {row_index} in table")
            return True
            
        except Exception as e:
            self.logger.error(f"Error highlighting search result: {e}")
            return False
    
    def _apply_highlight_style(self, item: QtWidgets.QTableWidgetItem):
        """
        Apply cyberpunk-style highlighting to a table item.
        
        Args:
            item: QTableWidgetItem to style
        """
        # Set background color with gradient effect
        gradient = QtGui.QLinearGradient(0, 0, 1, 0)
        gradient.setCoordinateMode(QtGui.QGradient.ObjectBoundingMode)
        gradient.setColorAt(0, QtGui.QColor(HIGHLIGHT_BG_COLOR))
        gradient.setColorAt(0.5, QtGui.QColor("#2a6d6d"))
        gradient.setColorAt(1, QtGui.QColor(HIGHLIGHT_BG_COLOR))
        
        item.setBackground(QtGui.QBrush(gradient))
        
        # Set text color to cyan
        item.setForeground(QtGui.QBrush(QtGui.QColor(HIGHLIGHT_COLOR)))
        
        # Make text bold
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    
    def _scroll_to_row(self, table_widget: QtWidgets.QTableWidget, row_index: int):
        """
        Scroll to a specific row in the table.
        
        Args:
            table_widget: QTableWidget to scroll
            row_index: Row index to scroll to
        """
        try:
            # Find an existing item in the row to scroll to
            scroll_item = None
            for col_index in range(table_widget.columnCount()):
                item = table_widget.item(row_index, col_index)
                if item is not None:
                    scroll_item = item
                    break
            
            # If no item found, create a temporary one in column 0
            if scroll_item is None:
                scroll_item = QtWidgets.QTableWidgetItem("")
                table_widget.setItem(row_index, 0, scroll_item)
            
            # Scroll to make the row visible in the center of the viewport
            table_widget.scrollToItem(
                scroll_item,
                QtWidgets.QAbstractItemView.PositionAtCenter
            )
            
            # Select the row
            table_widget.selectRow(row_index)
            
            self.logger.debug(f"Scrolled to row {row_index}")
            
        except Exception as e:
            self.logger.error(f"Error scrolling to row: {e}")
    
    def _setup_highlight_timer(self, table_widget: QtWidgets.QTableWidget, duration_ms: int):
        """
        Set up a timer to clear the highlight after a duration.
        
        Args:
            table_widget: QTableWidget with highlight
            duration_ms: Duration in milliseconds
        """
        # Cancel existing timer if any
        if table_widget in self._highlight_timers:
            self._highlight_timers[table_widget].stop()
            self._highlight_timers[table_widget].deleteLater()
        
        # Create new timer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.clear_highlight(table_widget))
        timer.start(duration_ms)
        
        self._highlight_timers[table_widget] = timer
        
        self.logger.debug(f"Set highlight timer for {duration_ms}ms")
    
    def _connect_clear_on_interaction(self, table_widget: QtWidgets.QTableWidget):
        """
        Connect signals to clear highlight on user interaction.
        
        Args:
            table_widget: QTableWidget to monitor
        """
        # Clear on cell click
        def on_cell_clicked(row, col):
            # Only clear if clicking a different row
            if table_widget in self._highlighted_items:
                highlighted_rows = set(item[0] for item in self._highlighted_items[table_widget])
                if row not in highlighted_rows:
                    self.clear_highlight(table_widget)
        
        # Disconnect only our previous connection if it exists
        if table_widget in self._cell_click_connections:
            try:
                table_widget.cellClicked.disconnect(self._cell_click_connections[table_widget])
            except:
                pass
        
        # Store the connection for later cleanup
        self._cell_click_connections[table_widget] = on_cell_clicked
        table_widget.cellClicked.connect(on_cell_clicked)
    
    def clear_highlight(self, table_widget: QtWidgets.QTableWidget):
        """
        Clear highlight from a table widget.
        
        Args:
            table_widget: QTableWidget to clear highlight from
        """
        try:
            # Stop timer if exists
            if table_widget in self._highlight_timers:
                self._highlight_timers[table_widget].stop()
                self._highlight_timers[table_widget].deleteLater()
                del self._highlight_timers[table_widget]
            
            # Restore original styles
            if table_widget in self._highlighted_items:
                for row_index, col_index in self._highlighted_items[table_widget]:
                    item = table_widget.item(row_index, col_index)
                    
                    if item and table_widget in self._original_styles:
                        if row_index in self._original_styles[table_widget]:
                            if col_index in self._original_styles[table_widget][row_index]:
                                # Restore original background and foreground
                                original_bg, original_fg = self._original_styles[table_widget][row_index][col_index]
                                item.setBackground(original_bg)
                                item.setForeground(original_fg)
                                
                                # Restore normal font weight
                                font = item.font()
                                font.setBold(False)
                                item.setFont(font)
                
                # Clear stored data
                del self._highlighted_items[table_widget]
                del self._original_styles[table_widget]
            
            # Disconnect our cell click handler
            if table_widget in self._cell_click_connections:
                try:
                    table_widget.cellClicked.disconnect(self._cell_click_connections[table_widget])
                    del self._cell_click_connections[table_widget]
                except:
                    pass
            
            self.logger.debug("Cleared highlight")
            
        except Exception as e:
            self.logger.error(f"Error clearing highlight: {e}")
    
    def navigate_to_result(
        self,
        tab_widget: QtWidgets.QTabWidget,
        table_widget: QtWidgets.QTableWidget,
        tab_index: int,
        row_index: int,
        matched_columns: Optional[list] = None,
        highlight_duration_ms: int = 3000
    ) -> bool:
        """
        Navigate to a search result by switching tabs and highlighting the row.
        
        Args:
            tab_widget: QTabWidget containing the tabs
            table_widget: QTableWidget within the tab
            tab_index: Index of the tab to switch to
            row_index: Row index to navigate to
            matched_columns: Optional list of matched column names
            highlight_duration_ms: Duration to keep highlight (milliseconds)
            
        Returns:
            bool: True if navigation was successful, False otherwise
        """
        try:
            # Validate tab index
            if tab_index < 0 or tab_index >= tab_widget.count():
                self.logger.warning(f"Invalid tab index: {tab_index}")
                return False
            
            # Switch to the target tab
            tab_widget.setCurrentIndex(tab_index)
            
            # Use QTimer to defer highlighting until after tab switch completes
            # This avoids re-entrancy issues with processEvents()
            def do_highlight():
                self.highlight_search_result(
                    table_widget=table_widget,
                    row_index=row_index,
                    matched_columns=matched_columns,
                    duration_ms=highlight_duration_ms,
                    auto_scroll=True
                )
            
            QTimer.singleShot(50, do_highlight)
            success = True
            
            if success:
                self.logger.info(f"Navigated to tab {tab_index}, row {row_index}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error navigating to result: {e}")
            return False
    
    def find_row_by_record_id(
        self,
        table_widget: QtWidgets.QTableWidget,
        record_id: Any,
        id_column_index: int = 0
    ) -> Optional[int]:
        """
        Find a row index by searching for a record ID in a specific column.
        
        Args:
            table_widget: QTableWidget to search
            record_id: Record ID to find
            id_column_index: Column index containing the record ID
            
        Returns:
            Optional[int]: Row index if found, None otherwise
        """
        try:
            record_id_str = str(record_id)
            
            for row_index in range(table_widget.rowCount()):
                item = table_widget.item(row_index, id_column_index)
                
                if item and item.text() == record_id_str:
                    return row_index
            
            self.logger.warning(f"Record ID {record_id} not found in table")
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding row by record ID: {e}")
            return None
    
    def highlight_virtual_table_result(
        self,
        virtual_table_widget,
        row_index: int,
        matched_columns: Optional[list] = None,
        duration_ms: int = 3000
    ) -> bool:
        """
        Highlight a search result in a VirtualTableWidget.
        
        This method handles the special case of virtual tables that may not have
        all rows loaded in memory. Only works with VirtualTableWidget instances.
        
        Args:
            virtual_table_widget: VirtualTableWidget instance (must have loaded_data, 
                                 page_size, _load_data_chunk, _populate_visible_rows attributes)
            row_index: Row index to highlight
            matched_columns: Optional list of matched column names
            duration_ms: Duration to keep highlight (milliseconds)
            
        Returns:
            bool: True if highlighting was successful, False otherwise
        """
        try:
            # Verify this is a virtual table widget with required attributes
            required_attrs = ['loaded_data', 'page_size', '_load_data_chunk', '_populate_visible_rows']
            if not all(hasattr(virtual_table_widget, attr) for attr in required_attrs):
                self.logger.warning(
                    "Widget does not have required VirtualTableWidget attributes. "
                    "Using standard highlighting instead."
                )
                # Fall back to standard highlighting for regular QTableWidget
                return self.highlight_search_result(
                    table_widget=virtual_table_widget,
                    row_index=row_index,
                    matched_columns=matched_columns,
                    duration_ms=duration_ms,
                    auto_scroll=True
                )
            
            # Check if the row is currently loaded
            if row_index not in virtual_table_widget.loaded_data:
                # Row not loaded, need to load it first
                self.logger.info(f"Row {row_index} not loaded, loading data chunk")
                
                # Calculate offset to load the chunk containing this row
                page_size = virtual_table_widget.page_size
                offset = (row_index // page_size) * page_size
                
                # Load the data chunk
                virtual_table_widget._load_data_chunk(offset, page_size)
                
                # Populate the rows
                virtual_table_widget._populate_visible_rows()
            
            # Now highlight using the standard method
            return self.highlight_search_result(
                table_widget=virtual_table_widget,
                row_index=row_index,
                matched_columns=matched_columns,
                duration_ms=duration_ms,
                auto_scroll=True
            )
            
        except Exception as e:
            self.logger.error(f"Error highlighting virtual table result: {e}")
            return False


# Global instance for convenience
_search_utils_instance = None


def get_search_utils() -> SearchUtils:
    """
    Get the global SearchUtils instance.
    
    Returns:
        SearchUtils: Global SearchUtils instance
    """
    global _search_utils_instance
    
    if _search_utils_instance is None:
        _search_utils_instance = SearchUtils()
    
    return _search_utils_instance
