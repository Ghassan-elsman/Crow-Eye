"""
MFT Data Loader - Specialized loader for MFT (Master File Table) data

This module provides a specialized data loader for MFT forensic artifacts,
inheriting from BaseDataLoader to provide search, pagination, and query capabilities.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Iterator, Any
from .base_loader import BaseDataLoader


class MFTDataLoader(BaseDataLoader):
    """
    Specialized data loader for MFT (Master File Table) operations.
    Handles loading and processing MFT data from SQLite databases.
    """
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """
        Initialize the MFT data loader.
        
        Args:
            db_path: Path to the MFT SQLite database file
        """
        super().__init__(db_path)
        self.mft_tables = [
            'mft_records',
            'mft_standard_info',
            'mft_file_names',
            'mft_data_attributes'
        ]
    
    def load_mft_records(
        self,
        page: int = 1,
        page_size: int = 1000,
        order_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load MFT records with pagination.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            order_by: Optional ORDER BY clause
            
        Returns:
            Dictionary containing paginated MFT records and metadata
        """
        if not self.table_exists('mft_records'):
            self.logger.warning("mft_records table does not exist in the database")
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
            table_name='mft_records',
            page=page,
            page_size=page_size,
            order_by=order_by or 'record_number ASC'
        )
    
    def load_standard_info(
        self,
        page: int = 1,
        page_size: int = 1000,
        record_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Load MFT standard information attributes.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            record_number: Optional filter by specific record number
            
        Returns:
            Dictionary containing paginated standard info and metadata
        """
        if not self.table_exists('mft_standard_info'):
            self.logger.warning("mft_standard_info table does not exist")
            return {
                'data': [],
                'total_count': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0,
                'has_next': False,
                'has_prev': False
            }
        
        where = None
        where_params = ()
        
        if record_number is not None:
            where = 'record_number = ?'
            where_params = (record_number,)
        
        return self.fetch_paginated(
            table_name='mft_standard_info',
            page=page,
            page_size=page_size,
            where=where,
            where_params=where_params,
            order_by='record_number ASC'
        )
    
    def load_file_names(
        self,
        page: int = 1,
        page_size: int = 1000,
        record_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Load MFT file name attributes.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            record_number: Optional filter by specific record number
            
        Returns:
            Dictionary containing paginated file names and metadata
        """
        if not self.table_exists('mft_file_names'):
            self.logger.warning("mft_file_names table does not exist")
            return {
                'data': [],
                'total_count': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0,
                'has_next': False,
                'has_prev': False
            }
        
        where = None
        where_params = ()
        
        if record_number is not None:
            where = 'record_number = ?'
            where_params = (record_number,)
        
        return self.fetch_paginated(
            table_name='mft_file_names',
            page=page,
            page_size=page_size,
            where=where,
            where_params=where_params,
            order_by='record_number ASC'
        )
    
    def load_data_attributes(
        self,
        page: int = 1,
        page_size: int = 1000,
        record_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Load MFT data attributes.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            record_number: Optional filter by specific record number
            
        Returns:
            Dictionary containing paginated data attributes and metadata
        """
        if not self.table_exists('mft_data_attributes'):
            self.logger.warning("mft_data_attributes table does not exist")
            return {
                'data': [],
                'total_count': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0,
                'has_next': False,
                'has_prev': False
            }
        
        where = None
        where_params = ()
        
        if record_number is not None:
            where = 'record_number = ?'
            where_params = (record_number,)
        
        return self.fetch_paginated(
            table_name='mft_data_attributes',
            page=page,
            page_size=page_size,
            where=where,
            where_params=where_params,
            order_by='record_number ASC'
        )
    
    def search_mft_records(
        self,
        search_term: str,
        columns: Optional[List[str]] = None,
        case_sensitive: bool = False,
        exact_match: bool = False,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Search MFT records for a specific term.
        
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
            table_name='mft_records',
            search_term=search_term,
            columns=columns,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            page=page,
            page_size=page_size
        )
    
    def search_all_mft_tables(
        self,
        search_term: str,
        case_sensitive: bool = False,
        exact_match: bool = False,
        max_results_per_table: int = 100
    ) -> Dict[str, Any]:
        """
        Search across all MFT tables.
        
        Args:
            search_term: The term to search for
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match the exact term
            max_results_per_table: Maximum results to return per table
            
        Returns:
            Dictionary containing search results from all tables
        """
        # Only search tables that exist
        existing_tables = [t for t in self.mft_tables if self.table_exists(t)]
        
        return self.search_multiple_tables(
            table_names=existing_tables,
            search_term=search_term,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            max_results_per_table=max_results_per_table
        )
    
    def get_record_by_number(self, record_number: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific MFT record by its record number.
        
        Args:
            record_number: The MFT record number to retrieve
            
        Returns:
            Dictionary containing the record data, or None if not found
        """
        if not self.table_exists('mft_records'):
            return None
        
        query = "SELECT * FROM mft_records WHERE record_number = ?"
        results = self.execute_query(query, (record_number,))
        
        return results[0] if results else None
    
    def get_records_by_parent(
        self,
        parent_record_number: int,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all MFT records with a specific parent record number.
        
        Args:
            parent_record_number: The parent record number to filter by
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated child records and metadata
        """
        return self.fetch_paginated(
            table_name='mft_records',
            page=page,
            page_size=page_size,
            where='parent_record_number = ?',
            where_params=(parent_record_number,),
            order_by='record_number ASC'
        )
    
    def get_deleted_records(
        self,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get all deleted MFT records (records with FILE_RECORD_SEGMENT_IN_USE flag not set).
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated deleted records and metadata
        """
        # Assuming flags column exists and bit 0 indicates in-use
        return self.fetch_paginated(
            table_name='mft_records',
            page=page,
            page_size=page_size,
            where='(flags & 1) = 0',
            order_by='record_number ASC'
        )
    
    def stream_all_records(
        self,
        page_size: int = 5000,
        order_by: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream all MFT records for memory-efficient processing.
        
        Args:
            page_size: Number of rows to fetch per page
            order_by: Optional ORDER BY clause
            
        Yields:
            Dictionary representing each MFT record
        """
        return self.stream_table(
            table_name='mft_records',
            order_by=order_by or 'record_number ASC',
            page_size=page_size
        )
    
    def get_mft_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the MFT database.
        
        Returns:
            Dictionary containing statistics for all MFT tables
        """
        stats = {}
        
        for table_name in self.mft_tables:
            if self.table_exists(table_name):
                stats[table_name] = self.get_table_statistics(table_name)
        
        return stats
