"""
Search integration module for connecting search widgets with data loaders.
Provides helper functions to integrate database search with UI tables.
"""

from PyQt5 import QtWidgets, QtCore
from typing import Optional, Callable, Dict, Any, List
import logging


class SearchIntegration:
    """
    Helper class for integrating search functionality with data loaders and table widgets.
    """
    
    def __init__(self, 
                 data_loader,
                 table_widget: QtWidgets.QTableWidget,
                 search_method: Callable,
                 load_all_method: Callable,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize search integration.
        
        Args:
            data_loader: Data loader instance (MFTDataLoader, USNDataLoader, etc.)
            table_widget: QTableWidget to display results
            search_method: Method to call for searching (e.g., loader.search_mft_records)
            load_all_method: Method to call for loading all data (e.g., loader.load_mft_records)
            logger: Optional logger instance
        """
        self.data_loader = data_loader
        self.table_widget = table_widget
        self.search_method = search_method
        self.load_all_method = load_all_method
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        
        self._original_data_cache = None
        self._search_active = False
        
    def perform_search(self, 
                      search_term: str, 
                      case_sensitive: bool = False,
                      page_size: int = 10000) -> Dict[str, Any]:
        """
        Perform a search and update the table widget with results.
        
        Args:
            search_term: Term to search for
            case_sensitive: Whether search should be case-sensitive
            page_size: Number of results per page
            
        Returns:
            Dictionary with search results metadata
        """
        try:
            self.logger.info(f"Performing search for: '{search_term}' (case_sensitive={case_sensitive})")
            
            # Perform search using the data loader
            result = self.search_method(
                search_term=search_term,
                case_sensitive=case_sensitive,
                page=1,
                page_size=page_size
            )
            
            if not result:
                self.logger.warning("Search returned no results")
                return {'total_count': 0, 'data': []}
            
            # Clear existing table data
            self.table_widget.setRowCount(0)
            
            # Get column names from first result
            if result['data']:
                columns = list(result['data'][0].keys())
                self.table_widget.setColumnCount(len(columns))
                self.table_widget.setHorizontalHeaderLabels(columns)
                
                # Populate table with search results
                for row_index, record in enumerate(result['data']):
                    self.table_widget.insertRow(row_index)
                    
                    for col_index, column_name in enumerate(columns):
                        value = record.get(column_name)
                        item = QtWidgets.QTableWidgetItem(str(value) if value is not None else "")
                        self.table_widget.setItem(row_index, col_index, item)
                
                self.logger.info(f"Search complete: {result['total_count']} results found")
            else:
                self.logger.info("Search complete: 0 results found")
            
            self._search_active = True
            return result
            
        except Exception as e:
            self.logger.error(f"Error performing search: {str(e)}")
            raise
            
    def clear_search(self, 
                    reload_all: bool = True,
                    progress_callback: Optional[Callable] = None,
                    batch_process_method: Optional[Callable] = None) -> int:
        """
        Clear search results and optionally reload all data.
        
        Args:
            reload_all: Whether to reload all data after clearing
            progress_callback: Optional callback for progress updates
            batch_process_method: Optional method for batch processing data
            
        Returns:
            Number of records loaded (if reload_all is True)
        """
        try:
            self.logger.info("Clearing search results")
            
            # Clear table
            self.table_widget.setRowCount(0)
            self._search_active = False
            
            if reload_all:
                self.logger.info("Reloading all data")
                
                if batch_process_method:
                    # Use batch processing method if provided
                    loaded_count = batch_process_method(
                        data_loader=self.data_loader,
                        load_method=self.load_all_method,
                        table_widget=self.table_widget,
                        progress_callback=progress_callback,
                        table_name="Data",
                        batch_size=500,
                        page_size=10000,
                        handle_row_errors=True
                    )
                    return loaded_count
                else:
                    # Simple reload without batch processing
                    result = self.load_all_method(page=1, page_size=10000)
                    
                    if result and result['data']:
                        columns = list(result['data'][0].keys())
                        self.table_widget.setColumnCount(len(columns))
                        self.table_widget.setHorizontalHeaderLabels(columns)
                        
                        for row_index, record in enumerate(result['data']):
                            self.table_widget.insertRow(row_index)
                            
                            for col_index, column_name in enumerate(columns):
                                value = record.get(column_name)
                                item = QtWidgets.QTableWidgetItem(str(value) if value is not None else "")
                                self.table_widget.setItem(row_index, col_index, item)
                        
                        return len(result['data'])
                    
            return 0
            
        except Exception as e:
            self.logger.error(f"Error clearing search: {str(e)}")
            raise
            
    def is_search_active(self) -> bool:
        """Check if a search is currently active."""
        return self._search_active


def create_search_handlers(ui_instance,
                          search_widget,
                          data_loader,
                          table_widget: QtWidgets.QTableWidget,
                          search_method: Callable,
                          load_all_method: Callable,
                          table_name: str,
                          progress_callback: Optional[Callable] = None) -> SearchIntegration:
    """
    Create and connect search handlers for a tab.
    
    Args:
        ui_instance: The main UI instance (for accessing batch processing methods)
        search_widget: SearchWidget instance
        data_loader: Data loader instance
        table_widget: Table widget to display results
        search_method: Search method from data loader
        load_all_method: Load all method from data loader
        table_name: Name of the table (for logging)
        progress_callback: Optional progress callback
        
    Returns:
        SearchIntegration instance
    """
    # Create search integration
    integration = SearchIntegration(
        data_loader=data_loader,
        table_widget=table_widget,
        search_method=search_method,
        load_all_method=load_all_method
    )
    
    # Connect search requested signal
    def on_search_requested(search_term: str, case_sensitive: bool):
        try:
            # Perform search
            result = integration.perform_search(search_term, case_sensitive)
            
            # Update search widget with results
            search_widget.set_search_results(
                result_count=result['total_count'],
                total_count=None  # We don't have total count without loading all data
            )
            
            if progress_callback:
                if hasattr(progress_callback, 'emit'):
                    progress_callback.emit(f"[{table_name}] Search complete: {result['total_count']} results found")
                else:
                    progress_callback(f"[{table_name}] Search complete: {result['total_count']} results found")
                    
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            search_widget.set_search_error(error_msg)
            
            if progress_callback:
                if hasattr(progress_callback, 'emit'):
                    progress_callback.emit(f"[{table_name}] {error_msg}")
                else:
                    progress_callback(f"[{table_name}] {error_msg}")
    
    # Connect clear requested signal
    def on_clear_requested():
        try:
            # Get batch processing method if available
            batch_process_method = getattr(ui_instance, '_batch_process_data_with_loader', None)
            
            # Clear search and reload data
            loaded_count = integration.clear_search(
                reload_all=True,
                progress_callback=progress_callback,
                batch_process_method=batch_process_method
            )
            
            if progress_callback:
                if hasattr(progress_callback, 'emit'):
                    progress_callback.emit(f"[{table_name}] Reloaded {loaded_count:,} records")
                else:
                    progress_callback(f"[{table_name}] Reloaded {loaded_count:,} records")
                    
        except Exception as e:
            error_msg = f"Failed to reload data: {str(e)}"
            search_widget.set_search_error(error_msg)
            
            if progress_callback:
                if hasattr(progress_callback, 'emit'):
                    progress_callback.emit(f"[{table_name}] {error_msg}")
                else:
                    progress_callback(f"[{table_name}] {error_msg}")
    
    # Connect signals
    search_widget.search_requested.connect(on_search_requested)
    search_widget.clear_requested.connect(on_clear_requested)
    
    return integration
