"""
Pagination Helper for Crow Eye
Provides helper functions to integrate pagination widgets with data loaders.
"""

from PyQt5.QtWidgets import QTableWidgetItem


class PaginationHelper:
    """
    Helper class to manage paginated data loading for table widgets.
    Integrates PaginationWidget with data loaders (MFTDataLoader, USNDataLoader, etc.)
    """
    
    @staticmethod
    def load_paginated_data(data_loader, load_method, table_widget, pagination_widget,
                           page=None, page_size=None, progress_callback=None, **loader_kwargs):
        """
        Load paginated data from a data loader and populate a table widget.
        
        Args:
            data_loader: BaseDataLoader instance (e.g., MFTDataLoader)
            load_method: Method to call on the loader (e.g., loader.load_mft_records)
            table_widget: QTableWidget to populate
            pagination_widget: PaginationWidget to update
            page: Page number to load (None to use pagination_widget's current page)
            page_size: Page size to use (None to use pagination_widget's current page size)
            progress_callback: Optional callback for progress updates
            **loader_kwargs: Additional arguments to pass to the load method
            
        Returns:
            int: Number of records loaded, or 0 if failed
        """
        try:
            # Get page and page_size from pagination widget if not provided
            if page is None:
                page = pagination_widget.get_current_page()
            if page_size is None:
                page_size = pagination_widget.get_page_size()
            
            # Call the loader method with pagination parameters
            result = load_method(page=page, page_size=page_size, **loader_kwargs)
            
            if not result or result.get('total_count', 0) == 0:
                # No data found
                table_widget.setRowCount(0)
                pagination_widget.update_pagination_info(0, page, page_size)
                if progress_callback:
                    progress_callback(f"No records found")
                return 0
            
            # Extract pagination metadata
            total_count = result.get('total_count', 0)
            data = result.get('data', [])
            
            # Update pagination widget with metadata
            pagination_widget.update_pagination_info(total_count, page, page_size)
            
            # Clear existing table data
            table_widget.setRowCount(0)
            
            if not data:
                if progress_callback:
                    progress_callback(f"Page {page} is empty")
                return 0
            
            # Set up table columns from first record
            columns = list(data[0].keys())
            table_widget.setColumnCount(len(columns))
            table_widget.setHorizontalHeaderLabels(columns)
            
            # Set row count
            table_widget.setRowCount(len(data))
            
            # Populate table with data
            for row_index, record in enumerate(data):
                for col_index, column_name in enumerate(columns):
                    value = record.get(column_name)
                    item = QTableWidgetItem(str(value) if value is not None else "")
                    table_widget.setItem(row_index, col_index, item)
            
            if progress_callback:
                start_record = (page - 1) * page_size + 1
                end_record = min(page * page_size, total_count)
                progress_callback(
                    f"Loaded records {start_record:,} to {end_record:,} of {total_count:,}"
                )
            
            return len(data)
            
        except Exception as e:
            print(f"[PaginationHelper] Error loading paginated data: {e}")
            if progress_callback:
                progress_callback(f"Error loading data: {str(e)}")
            return 0
    
    @staticmethod
    def setup_pagination_handlers(pagination_widget, data_loader, load_method, 
                                  table_widget, progress_callback=None, **loader_kwargs):
        """
        Set up event handlers for pagination widget to automatically reload data.
        
        Args:
            pagination_widget: PaginationWidget instance
            data_loader: BaseDataLoader instance
            load_method: Method to call on the loader
            table_widget: QTableWidget to populate
            progress_callback: Optional callback for progress updates
            **loader_kwargs: Additional arguments to pass to the load method
        """
        def on_page_changed(new_page):
            """Handle page change event."""
            PaginationHelper.load_paginated_data(
                data_loader=data_loader,
                load_method=load_method,
                table_widget=table_widget,
                pagination_widget=pagination_widget,
                page=new_page,
                progress_callback=progress_callback,
                **loader_kwargs
            )
        
        def on_page_size_changed(new_page_size):
            """Handle page size change event."""
            # Reset to page 1 when page size changes
            PaginationHelper.load_paginated_data(
                data_loader=data_loader,
                load_method=load_method,
                table_widget=table_widget,
                pagination_widget=pagination_widget,
                page=1,
                page_size=new_page_size,
                progress_callback=progress_callback,
                **loader_kwargs
            )
        
        # Connect signals
        pagination_widget.page_changed.connect(on_page_changed)
        pagination_widget.page_size_changed.connect(on_page_size_changed)
    
    @staticmethod
    def initialize_paginated_table(data_loader, load_method, table_widget, 
                                   pagination_widget, pagination_config, 
                                   table_type, progress_callback=None, **loader_kwargs):
        """
        Initialize a table with pagination support.
        
        This is a convenience method that:
        1. Loads saved pagination preferences
        2. Sets up pagination handlers
        3. Loads the initial page of data
        
        Args:
            data_loader: BaseDataLoader instance
            load_method: Method to call on the loader
            table_widget: QTableWidget to populate
            pagination_widget: PaginationWidget instance
            pagination_config: PaginationConfig instance
            table_type: Type of table ('mft', 'usn', 'correlated')
            progress_callback: Optional callback for progress updates
            **loader_kwargs: Additional arguments to pass to the load method
            
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        try:
            # Load saved preferences
            preferences = pagination_config.get_preferences(table_type)
            page_size = preferences.get('page_size', 1000)
            current_page = preferences.get('current_page', 1)
            
            # Set up pagination handlers
            PaginationHelper.setup_pagination_handlers(
                pagination_widget=pagination_widget,
                data_loader=data_loader,
                load_method=load_method,
                table_widget=table_widget,
                progress_callback=progress_callback,
                **loader_kwargs
            )
            
            # Load initial data
            loaded_count = PaginationHelper.load_paginated_data(
                data_loader=data_loader,
                load_method=load_method,
                table_widget=table_widget,
                pagination_widget=pagination_widget,
                page=current_page,
                page_size=page_size,
                progress_callback=progress_callback,
                **loader_kwargs
            )
            
            # Save current state
            pagination_config.set_preferences(table_type, {
                'page_size': pagination_widget.get_page_size(),
                'current_page': pagination_widget.get_current_page()
            })
            
            return loaded_count > 0
            
        except Exception as e:
            print(f"[PaginationHelper] Error initializing paginated table: {e}")
            if progress_callback:
                progress_callback(f"Error initializing table: {str(e)}")
            return False
