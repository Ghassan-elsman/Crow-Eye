"""
USN Journal Data Loader - Specialized loader for USN Journal data

This module provides a specialized data loader for USN (Update Sequence Number) Journal
forensic artifacts, inheriting from BaseDataLoader to provide search, pagination, and
query capabilities.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Iterator, Any
from .base_loader import BaseDataLoader


class USNDataLoader(BaseDataLoader):
    """
    Specialized data loader for USN (Update Sequence Number) Journal operations.
    Handles loading and processing USN journal data from SQLite databases.
    """
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """
        Initialize the USN data loader.
        
        Args:
            db_path: Path to the USN Journal SQLite database file
        """
        super().__init__(db_path)
        self.usn_table = 'journal_events'
    
    def load_journal_events(
        self,
        page: int = 1,
        page_size: int = 1000,
        order_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load USN journal events with pagination.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            order_by: Optional ORDER BY clause
            
        Returns:
            Dictionary containing paginated journal events and metadata
        """
        if not self.table_exists(self.usn_table):
            self.logger.warning(f"{self.usn_table} table does not exist in the database")
            return {
                'data': [],
                'total_count': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0,
                'has_next': False,
                'has_prev': False
            }
        
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            order_by=order_by or 'timestamp DESC'
        )
    
    def get_events_by_frn(
        self,
        frn: int,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all USN journal events for a specific File Reference Number (FRN).
        
        Args:
            frn: The File Reference Number to filter by
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='frn = ?',
            where_params=(frn,),
            order_by='timestamp DESC'
        )
    
    def get_events_by_parent_frn(
        self,
        parent_frn: int,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all USN journal events for files in a specific parent directory.
        
        Args:
            parent_frn: The parent File Reference Number to filter by
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='parent_frn = ?',
            where_params=(parent_frn,),
            order_by='timestamp DESC'
        )
    
    def get_events_by_reason(
        self,
        reason: str,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get USN journal events filtered by reason (e.g., 'FILE_CREATE', 'FILE_DELETE').
        
        Args:
            reason: The reason string to filter by
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='reason LIKE ?',
            where_params=(f'%{reason}%',),
            order_by='timestamp DESC'
        )
    
    def get_events_by_time_range(
        self,
        start_time: str,
        end_time: str,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get USN journal events within a specific time range.
        
        Args:
            start_time: Start timestamp (ISO format or epoch)
            end_time: End timestamp (ISO format or epoch)
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='timestamp BETWEEN ? AND ?',
            where_params=(start_time, end_time),
            order_by='timestamp ASC'
        )
    
    def search_journal_events(
        self,
        search_term: str,
        columns: Optional[List[str]] = None,
        case_sensitive: bool = False,
        exact_match: bool = False,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Search USN journal events for a specific term.
        
        Args:
            search_term: The term to search for
            columns: List of column names to search in (None for all)
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match the exact term
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing search results and metadata
        """
        return self.search_table(
            table_name=self.usn_table,
            search_term=search_term,
            columns=columns,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            page=page,
            page_size=page_size
        )
    
    def get_file_history(
        self,
        filename: str,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get the complete history of changes for a specific filename.
        
        Args:
            filename: The filename to search for
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated file history and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='filename LIKE ?',
            where_params=(f'%{filename}%',),
            order_by='timestamp ASC'
        )
    
    def get_deleted_files(
        self,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all file deletion events from the USN journal.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated deletion events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='reason LIKE ?',
            where_params=('%FILE_DELETE%',),
            order_by='timestamp DESC'
        )
    
    def get_created_files(
        self,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all file creation events from the USN journal.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated creation events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='reason LIKE ?',
            where_params=('%FILE_CREATE%',),
            order_by='timestamp DESC'
        )
    
    def get_renamed_files(
        self,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all file rename events from the USN journal.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated rename events and metadata
        """
        return self.fetch_paginated(
            table_name=self.usn_table,
            page=page,
            page_size=page_size,
            where='reason LIKE ?',
            where_params=('%RENAME%',),
            order_by='timestamp DESC'
        )
    
    def stream_all_events(
        self,
        page_size: int = 5000,
        order_by: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream all USN journal events for memory-efficient processing.
        
        Args:
            page_size: Number of rows to fetch per page
            order_by: Optional ORDER BY clause
            
        Yields:
            Dictionary representing each journal event
        """
        return self.stream_table(
            table_name=self.usn_table,
            order_by=order_by or 'timestamp DESC',
            page_size=page_size
        )
    
    def get_usn_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the USN journal database.
        
        Returns:
            Dictionary containing statistics for the journal_events table
        """
        if not self.table_exists(self.usn_table):
            return {
                'table_exists': False,
                'row_count': 0,
                'column_count': 0,
                'columns': [],
                'indexes': []
            }
        
        stats = self.get_table_statistics(self.usn_table)
        
        # Add USN-specific statistics
        if stats['table_exists']:
            # Get earliest and latest timestamps
            query = f"SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest FROM {self.usn_table}"
            result = self.execute_query(query)
            if result:
                stats['earliest_event'] = result[0].get('earliest')
                stats['latest_event'] = result[0].get('latest')
            
            # Get count of unique files (FRNs)
            query = f"SELECT COUNT(DISTINCT frn) as unique_files FROM {self.usn_table}"
            result = self.execute_query(query)
            if result:
                stats['unique_files'] = result[0].get('unique_files', 0)
        
        return stats
    
    def get_event_by_usn(self, usn: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific USN journal event by its USN value.
        
        Args:
            usn: The Update Sequence Number to retrieve
            
        Returns:
            Dictionary containing the event data, or None if not found
        """
        if not self.table_exists(self.usn_table):
            return None
        
        query = f"SELECT * FROM {self.usn_table} WHERE usn = ?"
        results = self.execute_query(query, (usn,))
        
        return results[0] if results else None
