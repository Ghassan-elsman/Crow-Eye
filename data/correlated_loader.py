"""
Correlated Data Loader - Specialized loader for MFT-USN correlated data

This module provides a specialized data loader for correlated MFT and USN Journal
forensic artifacts, inheriting from BaseDataLoader to provide search, pagination,
and query capabilities.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Iterator, Any
from .base_loader import BaseDataLoader


class CorrelatedDataLoader(BaseDataLoader):
    """
    Specialized data loader for correlated MFT and USN Journal data.
    Handles loading and processing correlated forensic data from SQLite databases.
    """
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """
        Initialize the correlated data loader.
        
        Args:
            db_path: Path to the correlated data SQLite database file
        """
        super().__init__(db_path)
        self.correlated_table = 'mft_usn_correlated'
    
    def load_correlated_data(
        self,
        page: int = 1,
        page_size: int = 1000,
        order_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load correlated MFT-USN data with pagination.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            order_by: Optional ORDER BY clause
            
        Returns:
            Dictionary containing paginated correlated data and metadata
        """
        if not self.table_exists(self.correlated_table):
            self.logger.warning(f"{self.correlated_table} table does not exist in the database")
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
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            order_by=order_by or 'mft_record_number ASC'
        )
    
    def get_by_mft_record(
        self,
        mft_record_number: int,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data for a specific MFT record number.
        
        Args:
            mft_record_number: The MFT record number to filter by
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated correlated data and metadata
        """
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where='mft_record_number = ?',
            where_params=(mft_record_number,),
            order_by='mft_record_number ASC'
        )
    
    def get_by_usn_event(
        self,
        usn_event_id: int,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data for a specific USN event ID.
        
        Args:
            usn_event_id: The USN event ID to filter by
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated correlated data and metadata
        """
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where='usn_event_id = ?',
            where_params=(usn_event_id,),
            order_by='mft_record_number ASC'
        )
    
    def get_by_path(
        self,
        path_pattern: str,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data for files matching a path pattern.
        
        Args:
            path_pattern: The path pattern to search for (supports wildcards)
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated correlated data and metadata
        """
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where='reconstructed_path LIKE ?',
            where_params=(f'%{path_pattern}%',),
            order_by='reconstructed_path ASC'
        )
    
    def get_by_correlation_score(
        self,
        min_score: float,
        max_score: Optional[float] = None,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data filtered by correlation score range.
        
        Args:
            min_score: Minimum correlation score
            max_score: Maximum correlation score (None for no upper limit)
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated correlated data and metadata
        """
        if max_score is not None:
            where = 'correlation_score BETWEEN ? AND ?'
            where_params = (min_score, max_score)
        else:
            where = 'correlation_score >= ?'
            where_params = (min_score,)
        
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where=where,
            where_params=where_params,
            order_by='correlation_score DESC'
        )
    
    def get_high_confidence_correlations(
        self,
        threshold: float = 0.8,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get high-confidence correlations (score above threshold).
        
        Args:
            threshold: Minimum correlation score (default 0.8)
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated high-confidence correlations
        """
        return self.get_by_correlation_score(
            min_score=threshold,
            page=page,
            page_size=page_size
        )
    
    def get_by_time_range(
        self,
        start_time: str,
        end_time: str,
        time_column: str = 'mft_modification_time',
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data within a specific time range.
        
        Args:
            start_time: Start timestamp (ISO format or epoch)
            end_time: End timestamp (ISO format or epoch)
            time_column: Which time column to filter on
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated correlated data and metadata
        """
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where=f'{time_column} BETWEEN ? AND ?',
            where_params=(start_time, end_time),
            order_by=f'{time_column} ASC'
        )
    
    def search_correlated_data(
        self,
        search_term: str,
        columns: Optional[List[str]] = None,
        case_sensitive: bool = False,
        exact_match: bool = False,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Search correlated data for a specific term.
        
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
            table_name=self.correlated_table,
            search_term=search_term,
            columns=columns,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            page=page,
            page_size=page_size
        )
    
    def get_deleted_files_with_correlation(
        self,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data for deleted files (from both MFT and USN).
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated deleted file correlations
        """
        # Assuming there's a column indicating deletion status
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where='(mft_flags & 1) = 0 OR usn_reason LIKE ?',
            where_params=('%FILE_DELETE%',),
            order_by='mft_record_number ASC'
        )
    
    def get_suspicious_activity(
        self,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data that may indicate suspicious activity.
        This includes files with mismatched timestamps, unusual locations, etc.
        
        Args:
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated suspicious activity records
        """
        # Example: Files with significant timestamp discrepancies
        # This is a placeholder - actual implementation depends on schema
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where='ABS(JULIANDAY(mft_modification_time) - JULIANDAY(usn_timestamp)) > 1',
            order_by='correlation_score ASC'
        )
    
    def stream_all_correlated_data(
        self,
        page_size: int = 5000,
        order_by: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream all correlated data for memory-efficient processing.
        
        Args:
            page_size: Number of rows to fetch per page
            order_by: Optional ORDER BY clause
            
        Yields:
            Dictionary representing each correlated record
        """
        return self.stream_table(
            table_name=self.correlated_table,
            order_by=order_by or 'mft_record_number ASC',
            page_size=page_size
        )
    
    def get_correlation_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the correlated data.
        
        Returns:
            Dictionary containing statistics for the correlated table
        """
        if not self.table_exists(self.correlated_table):
            return {
                'table_exists': False,
                'row_count': 0,
                'column_count': 0,
                'columns': [],
                'indexes': []
            }
        
        stats = self.get_table_statistics(self.correlated_table)
        
        # Add correlation-specific statistics
        if stats['table_exists']:
            # Get average correlation score
            query = f"SELECT AVG(correlation_score) as avg_score FROM {self.correlated_table}"
            result = self.execute_query(query)
            if result:
                stats['average_correlation_score'] = result[0].get('avg_score')
            
            # Get count of high-confidence correlations
            query = f"SELECT COUNT(*) as high_confidence FROM {self.correlated_table} WHERE correlation_score >= 0.8"
            result = self.execute_query(query)
            if result:
                stats['high_confidence_count'] = result[0].get('high_confidence', 0)
            
            # Get count of unique MFT records
            query = f"SELECT COUNT(DISTINCT mft_record_number) as unique_mft FROM {self.correlated_table}"
            result = self.execute_query(query)
            if result:
                stats['unique_mft_records'] = result[0].get('unique_mft', 0)
            
            # Get count of unique USN events
            query = f"SELECT COUNT(DISTINCT usn_event_id) as unique_usn FROM {self.correlated_table}"
            result = self.execute_query(query)
            if result:
                stats['unique_usn_events'] = result[0].get('unique_usn', 0)
        
        return stats
    
    def get_timeline_data(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        page_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Get correlated data for timeline analysis.
        
        Args:
            start_time: Optional start timestamp filter
            end_time: Optional end timestamp filter
            page: Page number (1-indexed)
            page_size: Number of records per page
            
        Returns:
            Dictionary containing paginated timeline data
        """
        where = None
        where_params = ()
        
        if start_time and end_time:
            where = 'mft_modification_time BETWEEN ? AND ?'
            where_params = (start_time, end_time)
        elif start_time:
            where = 'mft_modification_time >= ?'
            where_params = (start_time,)
        elif end_time:
            where = 'mft_modification_time <= ?'
            where_params = (end_time,)
        
        return self.fetch_paginated(
            table_name=self.correlated_table,
            page=page,
            page_size=page_size,
            where=where,
            where_params=where_params,
            order_by='mft_modification_time ASC'
        )
