"""
Search utilities for Crow Eye application.
Provides enhanced search functionality with filtering capabilities.
"""

from PyQt5.QtCore import QObject, pyqtSignal, Qt, QThread
from PyQt5 import QtWidgets, QtCore
import re
from typing import List, Tuple, Dict, Set, Optional, Any, Union


class SearchWorker(QObject):
    """Worker class for performing searches in table widgets."""
    finished = pyqtSignal(list)

    def __init__(self, tables, search_text, include_tables=None, exclude_tables=None, start_time=None, end_time=None):
        """
        Initialize the search worker.
        
        Args:
            tables (list): List of QTableWidget instances to search in.
            search_text (str): Text to search for.
            include_tables (list, optional): List of table names to include in the search. If None, all tables are included.
            exclude_tables (list, optional): List of table names to exclude from the search.
            start_time (datetime, optional): Start time for filtering results.
            end_time (datetime, optional): End time for filtering results.
        """
        super().__init__()
        self.tables = tables
        self.search_text = search_text
        self.include_tables = include_tables
        self.exclude_tables = exclude_tables or []
        self.start_time = start_time
        self.end_time = end_time

    def run(self):
        """
        Perform the search operation and emit results.
        
        The search is performed in all specified tables, looking for the search text
        in each cell. Results are emitted as a list of tuples (table, row).
        Only one result per row is emitted, even if multiple cells match.
        Time filtering is applied if start_time or end_time are specified.
        """
        from datetime import datetime
        
        results = []
        search_text_lower = self.search_text.lower()
        
        for table in self.tables:
            # Skip if table doesn't have required methods
            if not hasattr(table, 'rowCount') or not hasattr(table, 'columnCount'):
                continue
                
            # Skip if table is not in include_tables (when specified)
            if self.include_tables and table.objectName() not in self.include_tables:
                continue
                
            # Skip if table is in exclude_tables
            if table.objectName() in self.exclude_tables:
                continue
            
            # Find timestamp column index if time filtering is enabled
            timestamp_col = -1
            if self.start_time or self.end_time:
                # Look for common timestamp column headers
                timestamp_headers = ['timestamp', 'time', 'date', 'datetime', 'last modified', 'created', 'accessed']
                for col in range(table.columnCount()):
                    header_item = table.horizontalHeaderItem(col)
                    if header_item:
                        header_text = header_item.text().lower()
                        if any(ts_header in header_text for ts_header in timestamp_headers):
                            timestamp_col = col
                            break
                
            # Search in table cells - track rows that have already been added
            found_rows = set()
            for row in range(table.rowCount()):
                if row in found_rows:
                    continue
                
                # Apply time filtering if enabled and timestamp column found
                if timestamp_col >= 0 and (self.start_time or self.end_time):
                    timestamp_item = table.item(row, timestamp_col)
                    if timestamp_item:
                        try:
                            # Try to parse the timestamp
                            timestamp_text = timestamp_item.text()
                            # Try multiple datetime formats
                            row_time = None
                            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S']:
                                try:
                                    row_time = datetime.strptime(timestamp_text, fmt)
                                    break
                                except ValueError:
                                    continue
                            
                            # If we couldn't parse the timestamp, skip time filtering for this row
                            if row_time:
                                # Check if row is within time range
                                if self.start_time and row_time < self.start_time:
                                    continue
                                if self.end_time and row_time > self.end_time:
                                    continue
                        except Exception:
                            # If timestamp parsing fails, include the row (don't filter it out)
                            pass
                    
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item and search_text_lower in item.text().lower():
                        results.append((table, row))
                        found_rows.add(row)
                        break  # Only one result per row
        
        self.finished.emit(results)


class SearchUtils:
    """Utility class for search operations in Crow Eye."""
    
    @staticmethod
    def find_all_table_widgets(parent_obj):
        """
        Find all QTableWidget instances in the parent object.
        This method will find all tables, including nested ones.
        
        Args:
            parent_obj: The parent object containing table widgets.
            
        Returns:
            list: List of QTableWidget instances.
        """
        tables = []
        
        # Try using findChildren if available (for QObject-based parents)
        if hasattr(parent_obj, 'findChildren'):
            tables = parent_obj.findChildren(QtWidgets.QTableWidget)
        else:
            # Fallback to dir() method for non-QObject parents
            for attr_name in dir(parent_obj):
                try:
                    attr = getattr(parent_obj, attr_name)
                    if isinstance(attr, QtWidgets.QTableWidget):
                        tables.append(attr)
                except Exception:
                    pass  # Skip attributes that can't be accessed
        
        return tables
    
    @staticmethod
    def get_table_names(parent_obj):
        """
        Get names of all table widgets in the parent object.
        
        Args:
            parent_obj: The parent object containing table widgets.
            
        Returns:
            list: List of table widget names.
        """
        tables = SearchUtils.find_all_table_widgets(parent_obj)
        return [table.objectName() for table in tables]
    
    @staticmethod
    def make_table_visible(parent_obj, table):
        """
        Make the table visible by switching to its tab, handling nested tabs.
        
        Args:
            parent_obj: The parent object containing the UI structure.
            table: The table widget to make visible.
            
        Returns:
            bool: True if the table was made visible, False otherwise.
        """
        print(f"DEBUG: make_table_visible called for table: {table.objectName()}")
        
        # Store the original table to check if it's visible at the end
        original_table = table
        
        # Find the direct parent widget of the table
        direct_parent = table.parentWidget()
        print(f"DEBUG: Direct parent of {table.objectName()} is {direct_parent.objectName()}")
        
            # Special handling for Amcache tables
        if table.objectName().startswith("Amcache_") and table.objectName().endswith("_table"):
            # Make sure we're on the Amcache_main_tab in the main_tab
            if hasattr(parent_obj, 'main_tab') and hasattr(parent_obj, 'Amcache_main_tab'):
                # First, ensure main_tab is visible and has focus
                parent_obj.main_tab.show()
                parent_obj.main_tab.setFocus()
                QtWidgets.QApplication.processEvents()
                
                # Find and select the Amcache_main_tab in main_tab
                for i in range(parent_obj.main_tab.count()):
                    if parent_obj.main_tab.widget(i) is parent_obj.Amcache_main_tab:
                        print(f"DEBUG: Setting main_tab to Amcache_main_tab (index {i})")
                        parent_obj.main_tab.setCurrentIndex(i)
                        QtWidgets.QApplication.processEvents()
                        QThread.msleep(200)  # Longer delay for tab switching
                        QtWidgets.QApplication.processEvents()
                        break
                
                # Now find the specific table tab in Amcache_tab_widget
                if hasattr(parent_obj, 'Amcache_tab_widget'):
                    # Extract the table name from the object name (format: Amcache_TableName_table)
                    table_name = table.objectName()[8:-6]  # Remove 'Amcache_' prefix and '_table' suffix
                    
                    # Find the tab with this table
                    for j in range(parent_obj.Amcache_tab_widget.count()):
                        tab = parent_obj.Amcache_tab_widget.widget(j)
                        if tab.findChild(QtWidgets.QTableWidget, table.objectName()):
                            print(f"DEBUG: Setting Amcache_tab_widget to tab index {j} for {table_name}")
                            parent_obj.Amcache_tab_widget.setCurrentIndex(j)
                            QtWidgets.QApplication.processEvents()
                            QThread.msleep(100)
                            break
                
                # Now focus on the table itself
                table.show()
                table.raise_()
                table.setFocus()
                QtWidgets.QApplication.processEvents()
                return table.isVisible()
        
        # Special handling for LNK_table, AJL_table, and Clj_table
        if table.objectName() in ["LNK_table", "AJL_table", "Clj_table"]:
            # Make sure we're on the LNK_JL_Tab in the main_tab
            if hasattr(parent_obj, 'main_tab') and hasattr(parent_obj, 'LNK_JL_Tab'):
                # First, ensure main_tab is visible and has focus
                parent_obj.main_tab.show()
                parent_obj.main_tab.setFocus()
                QtWidgets.QApplication.processEvents()
                
                # Find and select the LNK_JL_Tab in main_tab
                for i in range(parent_obj.main_tab.count()):
                    if parent_obj.main_tab.widget(i) is parent_obj.LNK_JL_Tab:
                        print(f"DEBUG: Setting main_tab to LNK_JL_Tab (index {i})")
                        parent_obj.main_tab.setCurrentIndex(i)
                        QtWidgets.QApplication.processEvents()
                        QThread.msleep(200)  # Longer delay for tab switching
                        QtWidgets.QApplication.processEvents()
                        break
            
            # Force focus on the LNK_JL_Tab and then the table
            if hasattr(parent_obj, 'LNK_JL_Tab'):
                parent_obj.LNK_JL_Tab.show()
                parent_obj.LNK_JL_Tab.raise_()
                parent_obj.LNK_JL_Tab.setFocus()
                QtWidgets.QApplication.processEvents()
                QThread.msleep(100)
                
                # Select the appropriate subtab based on the table
                if hasattr(parent_obj, 'lnk_jl_subtabs'):
                    subtab_mapping = {
                        "LNK_table": "LNK_subtab",
                        "AJL_table": "AJL_subtab",
                        "Clj_table": "CJL_subtab"
                    }
                    
                    subtab_attr = subtab_mapping.get(table.objectName())
                    if subtab_attr and hasattr(parent_obj, subtab_attr):
                        subtab = getattr(parent_obj, subtab_attr)
                        for j in range(parent_obj.lnk_jl_subtabs.count()):
                            if parent_obj.lnk_jl_subtabs.widget(j) is subtab:
                                parent_obj.lnk_jl_subtabs.setCurrentIndex(j)
                                break
                
                # Now focus on the table itself
                table.show()
                table.raise_()
                table.setFocus()
                QtWidgets.QApplication.processEvents()
        
        # Generic approach for other tables - traverse up the widget hierarchy
        # to find tab widgets and set the correct tab
        current_widget = table
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        while current_widget and iteration < max_iterations:
            parent_widget = current_widget.parentWidget()
            if not parent_widget:
                break
                
            # Check if the parent is a tab widget
            if isinstance(parent_widget, QtWidgets.QTabWidget):
                # Find which tab contains our widget
                for i in range(parent_widget.count()):
                    if parent_widget.widget(i) is current_widget or parent_widget.widget(i).isAncestorOf(current_widget):
                        print(f"DEBUG: Setting tab index {i} in {parent_widget.objectName()}")
                        parent_widget.setCurrentIndex(i)
                        QtWidgets.QApplication.processEvents()
                        break
            
            # Move up to the next parent
            current_widget = parent_widget
            iteration += 1
        
        # Final check - is the original table visible?
        QtWidgets.QApplication.processEvents()
        return original_table.isVisible()
    
    @staticmethod
    def highlight_search_result(parent_obj, table, row, process_immediately=False):
        """
        Highlight a search result in a table by selecting the entire row.
        
        Args:
            parent_obj: The parent object containing the UI structure.
            table: The table widget containing the result.
            row: The row index of the result.
            process_immediately (bool): If True, process the highlight immediately instead of waiting for the timer.
            
        Returns:
            bool: True if the result was highlighted, False otherwise.
        """
        # Make sure the table is visible
        if not SearchUtils.make_table_visible(parent_obj, table):
            print(f"WARNING: Could not make table {table.objectName()} visible")
            return False
        
        # Clear previous selection
        table.clearSelection()
        
        # Check if the row exists
        if row >= 0 and row < table.rowCount():
            # First ensure the table has focus
            table.setFocus()
            QtWidgets.QApplication.processEvents()
            
            # Find the first non-empty cell in the row to scroll to
            scroll_item = None
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item:
                    scroll_item = item
                    break
            
            # Scroll to the item if found, otherwise just select the row
            if scroll_item:
                table.scrollToItem(scroll_item, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
                QtWidgets.QApplication.processEvents()
            
            # Select the entire row
            table.selectRow(row)
            QtWidgets.QApplication.processEvents()
            
            print(f"DEBUG: Scrolled to and selected row {row} in table {table.objectName()}")
            return True
        else:
            print(f"WARNING: Row {row} is out of range in table {table.objectName()}")
            return False
            
    @staticmethod
    def process_highlight_queue(parent_obj, force=False):
        """
        Processes one highlight request from the queue.
        
        Args:
            parent_obj: The parent object containing the UI structure.
            force (bool): If True, process the queue even if is_processing_highlight is True.
        """
        # Skip if already processing a highlight and not forced
        if hasattr(parent_obj, 'is_processing_highlight') and parent_obj.is_processing_highlight and not force:
            return
            
        # Skip if queue is empty
        if not hasattr(parent_obj, 'highlight_queue') or not parent_obj.highlight_queue:
            return
            
        # Set processing flag
        parent_obj.is_processing_highlight = True
        
        # Get the next highlight request
        try:
            # Use popleft() for deque objects instead of pop(0)
            highlight_request = parent_obj.highlight_queue.popleft()
            
            # Process the highlight request
            if len(highlight_request) == 2:  # New format: (table, row)
                table, row = highlight_request
                SearchUtils.highlight_search_result(parent_obj, table, row)
            elif len(highlight_request) == 3:  # Old format: (table, row, column) for backward compatibility
                table, row, _ = highlight_request  # Ignore column
                SearchUtils.highlight_search_result(parent_obj, table, row)
        except Exception as e:
            print(f"ERROR in process_highlight_queue: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Clear processing flag
        parent_obj.is_processing_highlight = False
    
    @staticmethod
    def clear_search_results(parent_obj):
        """
        Clear all search results and selections in tables.
        
        Args:
            parent_obj: The parent object containing the UI structure.
        """
        print("DEBUG: Clearing all search results")
        
        # Clear the highlight queue if it exists
        if hasattr(parent_obj, 'highlight_queue'):
            parent_obj.highlight_queue.clear()
        
        # Stop processing if it's running
        if hasattr(parent_obj, 'processing_highlights'):
            parent_obj.processing_highlights = False
        
        # Clear selections in all tables
        tables = SearchUtils.find_all_table_widgets(parent_obj)
        for table in tables:
            if table.isVisible():
                table.clearSelection()
                QtWidgets.QApplication.processEvents()