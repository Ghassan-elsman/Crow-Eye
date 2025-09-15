"""Advanced search and filtering capabilities for Crow Eye."""

import re
import sqlite3
import json
from typing import Dict, List, Any, Optional, Union, Tuple, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import QObject, pyqtSignal, QThread
import logging


@dataclass
class SearchCriteria:
    """Search criteria for advanced searches."""
    query: str = ""
    case_sensitive: bool = False
    regex_mode: bool = False
    whole_word: bool = False
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    artifact_types: Optional[List[str]] = None
    exclude_artifact_types: Optional[List[str]] = None
    file_extensions: Optional[List[str]] = None
    size_range_min: Optional[int] = None
    size_range_max: Optional[int] = None
    custom_filters: Optional[Dict[str, Any]] = None


@dataclass
class SearchResult:
    """Result of a search operation."""
    artifact_type: str
    table_name: str
    record_id: int
    matched_fields: List[str]
    matched_values: List[str]
    context: Dict[str, Any]
    relevance_score: float
    timestamp: Optional[str] = None


@dataclass
class FilterRule:
    """A filtering rule for advanced data filtering."""
    field_name: str
    operator: str  # eq, ne, gt, lt, ge, le, contains, regex, in, not_in
    value: Any
    case_sensitive: bool = False


class AdvancedSearchEngine:
    """Advanced search engine with multiple search modes and filtering."""
    
    def __init__(self, database_paths: Dict[str, str], max_workers: int = 4):
        """Initialize the advanced search engine.
        
        Args:
            database_paths: Dictionary mapping artifact types to database paths
            max_workers: Maximum number of worker threads for parallel search
        """
        self.database_paths = database_paths
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
        self._search_cache: Dict[str, List[SearchResult]] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._cache_lock = threading.Lock()
        
    def search(
        self,
        criteria: SearchCriteria,
        use_cache: bool = True,
        progress_callback: Optional[callable] = None
    ) -> List[SearchResult]:
        """Perform an advanced search based on criteria.
        
        Args:
            criteria: Search criteria
            use_cache: Whether to use cached results
            progress_callback: Callback for progress updates
            
        Returns:
            List of search results sorted by relevance
        """
        # Check cache first
        cache_key = self._generate_cache_key(criteria)
        if use_cache and self._is_cache_valid(cache_key):
            self.logger.info("Returning cached search results")
            return self._search_cache[cache_key]
        
        start_time = time.time()
        all_results = []
        
        # Determine which databases to search
        databases_to_search = self._get_databases_to_search(criteria)
        
        # Search in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_db = {
                executor.submit(self._search_database, db_type, db_path, criteria): db_type
                for db_type, db_path in databases_to_search.items()
            }
            
            completed = 0
            for future in future_to_db:
                try:
                    results = future.result()
                    all_results.extend(results)
                    completed += 1
                    
                    if progress_callback:
                        progress_callback(completed, len(databases_to_search))
                        
                except Exception as e:
                    db_type = future_to_db[future]
                    self.logger.error(f"Error searching {db_type} database: {e}")
        
        # Sort results by relevance score
        all_results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        # Cache results
        if use_cache:
            with self._cache_lock:
                self._search_cache[cache_key] = all_results
                self._cache_expiry[cache_key] = datetime.now() + timedelta(minutes=15)
        
        duration = time.time() - start_time
        self.logger.info(f"Search completed in {duration:.2f}s, found {len(all_results)} results")
        
        return all_results
    
    def _search_database(
        self,
        db_type: str,
        db_path: str,
        criteria: SearchCriteria
    ) -> List[SearchResult]:
        """Search a specific database."""
        results = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for table_row in tables:
                table_name = table_row[0]
                
                # Get table schema
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [col[1] for col in cursor.fetchall()]
                
                # Build search query
                query, params = self._build_search_query(table_name, columns, criteria)
                
                if query:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    
                    # Process results
                    for row in rows:
                        result = self._process_search_result(
                            db_type, table_name, columns, row, criteria
                        )
                        if result:
                            results.append(result)
            
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error searching database {db_path}: {e}")
        
        return results
    
    def _build_search_query(
        self,
        table_name: str,
        columns: List[str],
        criteria: SearchCriteria
    ) -> Tuple[str, List[Any]]:
        """Build SQL search query based on criteria."""
        if not criteria.query and not criteria.date_range_start and not criteria.custom_filters:
            return "", []
        
        # Base query
        query_parts = [f"SELECT * FROM {table_name}"]
        where_conditions = []
        params = []
        
        # Text search conditions
        if criteria.query:
            text_conditions = []
            searchable_columns = [col for col in columns if self._is_searchable_column(col)]
            
            for col in searchable_columns:
                if criteria.regex_mode:
                    # SQLite doesn't support regex directly, so we'll do a LIKE search
                    # and filter with regex later
                    text_conditions.append(f"{col} LIKE ?")
                    params.append(f"%{criteria.query}%")
                elif criteria.whole_word:
                    # Use word boundaries for whole word search
                    text_conditions.append(f"{col} REGEXP ?")
                    pattern = r'\b' + re.escape(criteria.query) + r'\b'
                    if not criteria.case_sensitive:
                        pattern = f"(?i){pattern}"
                    params.append(pattern)
                else:
                    # Simple LIKE search
                    if criteria.case_sensitive:
                        text_conditions.append(f"{col} LIKE ? COLLATE BINARY")
                    else:
                        text_conditions.append(f"{col} LIKE ?")
                    
                    search_term = criteria.query if criteria.case_sensitive else criteria.query.lower()
                    params.append(f"%{search_term}%")
            
            if text_conditions:
                where_conditions.append(f"({' OR '.join(text_conditions)})")
        
        # Date range conditions
        if criteria.date_range_start or criteria.date_range_end:
            date_columns = [col for col in columns if self._is_date_column(col)]
            if date_columns:
                date_col = date_columns[0]  # Use first date column found
                
                if criteria.date_range_start:
                    where_conditions.append(f"{date_col} >= ?")
                    params.append(criteria.date_range_start)
                
                if criteria.date_range_end:
                    where_conditions.append(f"{date_col} <= ?")
                    params.append(criteria.date_range_end)
        
        # Size range conditions
        if criteria.size_range_min is not None or criteria.size_range_max is not None:
            size_columns = [col for col in columns if self._is_size_column(col)]
            if size_columns:
                size_col = size_columns[0]
                
                if criteria.size_range_min is not None:
                    where_conditions.append(f"{size_col} >= ?")
                    params.append(criteria.size_range_min)
                
                if criteria.size_range_max is not None:
                    where_conditions.append(f"{size_col} <= ?")
                    params.append(criteria.size_range_max)
        
        # Custom filters
        if criteria.custom_filters:
            for field, filter_value in criteria.custom_filters.items():
                if field in columns:
                    if isinstance(filter_value, list):
                        placeholders = ','.join(['?' for _ in filter_value])
                        where_conditions.append(f"{field} IN ({placeholders})")
                        params.extend(filter_value)
                    else:
                        where_conditions.append(f"{field} = ?")
                        params.append(filter_value)
        
        # Combine conditions
        if where_conditions:
            query_parts.append("WHERE " + " AND ".join(where_conditions))
        
        # Add ordering for consistent results
        query_parts.append("ORDER BY rowid")
        
        return " ".join(query_parts), params
    
    def _process_search_result(
        self,
        db_type: str,
        table_name: str,
        columns: List[str],
        row: Tuple,
        criteria: SearchCriteria
    ) -> Optional[SearchResult]:
        """Process a database row into a search result."""
        try:
            # Create record dictionary
            record = dict(zip(columns, row))
            
            # Find matched fields and values
            matched_fields = []
            matched_values = []
            
            if criteria.query:
                for col, value in record.items():
                    if value and self._is_searchable_column(col):
                        value_str = str(value)
                        
                        # Check if query matches
                        if self._value_matches_query(value_str, criteria):
                            matched_fields.append(col)
                            matched_values.append(value_str)
            
            # Calculate relevance score
            relevance_score = self._calculate_relevance_score(
                matched_fields, matched_values, criteria, record
            )
            
            # Extract timestamp if available
            timestamp = None
            date_columns = [col for col in columns if self._is_date_column(col)]
            if date_columns and record.get(date_columns[0]):
                timestamp = str(record[date_columns[0]])
            
            return SearchResult(
                artifact_type=db_type,
                table_name=table_name,
                record_id=record.get('id', record.get('rowid', 0)),
                matched_fields=matched_fields,
                matched_values=matched_values,
                context=record,
                relevance_score=relevance_score,
                timestamp=timestamp
            )
            
        except Exception as e:
            self.logger.error(f"Error processing search result: {e}")
            return None
    
    def _value_matches_query(self, value: str, criteria: SearchCriteria) -> bool:
        """Check if a value matches the search query."""
        if criteria.regex_mode:
            try:
                flags = 0 if criteria.case_sensitive else re.IGNORECASE
                return bool(re.search(criteria.query, value, flags))
            except re.error:
                # Invalid regex, fall back to simple search
                pass
        
        if criteria.whole_word:
            pattern = r'\b' + re.escape(criteria.query) + r'\b'
            flags = 0 if criteria.case_sensitive else re.IGNORECASE
            return bool(re.search(pattern, value, flags))
        
        # Simple substring search
        search_value = value if criteria.case_sensitive else value.lower()
        search_query = criteria.query if criteria.case_sensitive else criteria.query.lower()
        
        return search_query in search_value
    
    def _calculate_relevance_score(
        self,
        matched_fields: List[str],
        matched_values: List[str],
        criteria: SearchCriteria,
        record: Dict[str, Any]
    ) -> float:
        """Calculate relevance score for a search result."""
        if not matched_fields:
            return 0.0
        
        score = 0.0
        
        # Base score for number of matches
        score += len(matched_fields) * 10
        
        # Boost score for important fields
        important_fields = ['name', 'path', 'filename', 'executable', 'description']
        for field in matched_fields:
            if any(important in field.lower() for important in important_fields):
                score += 20
        
        # Boost score for exact matches
        for value in matched_values:
            if criteria.query.lower() == value.lower():
                score += 50
        
        # Boost score for multiple occurrences in the same field
        for value in matched_values:
            occurrences = value.lower().count(criteria.query.lower())
            score += (occurrences - 1) * 5  # Bonus for multiple occurrences
        
        # Penalize very long fields (less relevant)
        for value in matched_values:
            if len(value) > 200:
                score *= 0.8
        
        return score
    
    def _is_searchable_column(self, column_name: str) -> bool:
        """Check if a column should be included in text searches."""
        column_lower = column_name.lower()
        
        # Include text-like columns
        include_keywords = [
            'name', 'path', 'filename', 'description', 'command', 'args',
            'executable', 'title', 'url', 'comment', 'data', 'value'
        ]
        
        # Exclude binary/numeric-only columns
        exclude_keywords = [
            'id', 'size', 'count', 'offset', 'length', 'timestamp',
            'hash', 'checksum', 'crc', 'binary'
        ]
        
        # Check include keywords
        if any(keyword in column_lower for keyword in include_keywords):
            return True
        
        # Check exclude keywords
        if any(keyword in column_lower for keyword in exclude_keywords):
            return False
        
        # Default to searchable
        return True
    
    def _is_date_column(self, column_name: str) -> bool:
        """Check if a column contains date/time data."""
        column_lower = column_name.lower()
        date_keywords = [
            'time', 'date', 'timestamp', 'created', 'modified',
            'accessed', 'deleted', 'run', 'executed'
        ]
        return any(keyword in column_lower for keyword in date_keywords)
    
    def _is_size_column(self, column_name: str) -> bool:
        """Check if a column contains size data."""
        column_lower = column_name.lower()
        size_keywords = ['size', 'length', 'bytes', 'kb', 'mb']
        return any(keyword in column_lower for keyword in size_keywords)
    
    def _get_databases_to_search(self, criteria: SearchCriteria) -> Dict[str, str]:
        """Get the databases to search based on criteria."""
        if criteria.artifact_types:
            # Only search specified artifact types
            return {
                db_type: db_path for db_type, db_path in self.database_paths.items()
                if db_type in criteria.artifact_types
            }
        elif criteria.exclude_artifact_types:
            # Search all except excluded types
            return {
                db_type: db_path for db_type, db_path in self.database_paths.items()
                if db_type not in criteria.exclude_artifact_types
            }
        else:
            # Search all databases
            return self.database_paths
    
    def _generate_cache_key(self, criteria: SearchCriteria) -> str:
        """Generate a cache key for search criteria."""
        key_parts = [
            criteria.query,
            str(criteria.case_sensitive),
            str(criteria.regex_mode),
            str(criteria.whole_word),
            criteria.date_range_start or "",
            criteria.date_range_end or "",
            ",".join(sorted(criteria.artifact_types or [])),
            ",".join(sorted(criteria.exclude_artifact_types or [])),
            ",".join(sorted(criteria.file_extensions or [])),
            str(criteria.size_range_min or ""),
            str(criteria.size_range_max or ""),
            json.dumps(criteria.custom_filters or {}, sort_keys=True)
        ]
        return "|".join(key_parts)
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached results are still valid."""
        with self._cache_lock:
            if cache_key not in self._search_cache:
                return False
            
            expiry_time = self._cache_expiry.get(cache_key)
            if not expiry_time or datetime.now() > expiry_time:
                # Remove expired cache entry
                self._search_cache.pop(cache_key, None)
                self._cache_expiry.pop(cache_key, None)
                return False
            
            return True
    
    def clear_cache(self):
        """Clear the search cache."""
        with self._cache_lock:
            self._search_cache.clear()
            self._cache_expiry.clear()
        self.logger.info("Search cache cleared")


class FilterEngine:
    """Advanced filtering engine for complex data filtering."""
    
    def __init__(self):
        """Initialize the filter engine."""
        self.logger = logging.getLogger(__name__)
    
    def apply_filters(
        self,
        data: List[Dict[str, Any]],
        filters: List[FilterRule]
    ) -> List[Dict[str, Any]]:
        """Apply a list of filter rules to data.
        
        Args:
            data: List of data records
            filters: List of filter rules to apply
            
        Returns:
            Filtered data
        """
        if not filters:
            return data
        
        filtered_data = []
        
        for record in data:
            if self._record_matches_filters(record, filters):
                filtered_data.append(record)
        
        return filtered_data
    
    def _record_matches_filters(
        self,
        record: Dict[str, Any],
        filters: List[FilterRule]
    ) -> bool:
        """Check if a record matches all filter rules (AND logic)."""
        for filter_rule in filters:
            if not self._apply_single_filter(record, filter_rule):
                return False
        return True
    
    def _apply_single_filter(
        self,
        record: Dict[str, Any],
        filter_rule: FilterRule
    ) -> bool:
        """Apply a single filter rule to a record."""
        field_value = record.get(filter_rule.field_name)
        
        if field_value is None:
            return False
        
        # Convert to string for text operations
        if isinstance(field_value, str):
            compare_value = field_value if filter_rule.case_sensitive else field_value.lower()
            filter_value = filter_rule.value if filter_rule.case_sensitive else str(filter_rule.value).lower()
        else:
            compare_value = field_value
            filter_value = filter_rule.value
        
        # Apply operator
        if filter_rule.operator == 'eq':
            return compare_value == filter_value
        elif filter_rule.operator == 'ne':
            return compare_value != filter_value
        elif filter_rule.operator == 'gt':
            return compare_value > filter_value
        elif filter_rule.operator == 'lt':
            return compare_value < filter_value
        elif filter_rule.operator == 'ge':
            return compare_value >= filter_value
        elif filter_rule.operator == 'le':
            return compare_value <= filter_value
        elif filter_rule.operator == 'contains':
            return str(filter_value) in str(compare_value)
        elif filter_rule.operator == 'regex':
            try:
                flags = 0 if filter_rule.case_sensitive else re.IGNORECASE
                return bool(re.search(str(filter_value), str(compare_value), flags))
            except re.error:
                return False
        elif filter_rule.operator == 'in':
            return compare_value in filter_value
        elif filter_rule.operator == 'not_in':
            return compare_value not in filter_value
        else:
            self.logger.warning(f"Unknown filter operator: {filter_rule.operator}")
            return True


class SearchWorkerThread(QThread):
    """Worker thread for performing searches without blocking the UI."""
    
    search_completed = pyqtSignal(list)  # Emitted when search completes
    search_progress = pyqtSignal(int, int)  # Emitted for progress updates
    search_error = pyqtSignal(str)  # Emitted when search fails
    
    def __init__(self, search_engine: AdvancedSearchEngine, criteria: SearchCriteria):
        """Initialize the search worker thread.
        
        Args:
            search_engine: The search engine to use
            criteria: Search criteria
        """
        super().__init__()
        self.search_engine = search_engine
        self.criteria = criteria
        self.logger = logging.getLogger(__name__)
    
    def run(self):
        """Run the search in a separate thread."""
        try:
            def progress_callback(current: int, total: int):
                self.search_progress.emit(current, total)
            
            results = self.search_engine.search(
                self.criteria,
                progress_callback=progress_callback
            )
            
            self.search_completed.emit(results)
            
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            self.logger.error(error_msg)
            self.search_error.emit(error_msg)


# Utility functions for common search operations

def create_basic_search_criteria(query: str, case_sensitive: bool = False) -> SearchCriteria:
    """Create basic search criteria for simple text search.
    
    Args:
        query: Search query
        case_sensitive: Whether search should be case sensitive
        
    Returns:
        SearchCriteria object
    """
    return SearchCriteria(
        query=query,
        case_sensitive=case_sensitive
    )


def create_regex_search_criteria(pattern: str, case_sensitive: bool = False) -> SearchCriteria:
    """Create search criteria for regex pattern search.
    
    Args:
        pattern: Regular expression pattern
        case_sensitive: Whether search should be case sensitive
        
    Returns:
        SearchCriteria object
    """
    return SearchCriteria(
        query=pattern,
        case_sensitive=case_sensitive,
        regex_mode=True
    )


def create_date_range_criteria(
    start_date: str,
    end_date: str,
    artifact_types: Optional[List[str]] = None
) -> SearchCriteria:
    """Create search criteria for date range filtering.
    
    Args:
        start_date: Start date (ISO format)
        end_date: End date (ISO format)
        artifact_types: Specific artifact types to search
        
    Returns:
        SearchCriteria object
    """
    return SearchCriteria(
        date_range_start=start_date,
        date_range_end=end_date,
        artifact_types=artifact_types
    )


def highlight_search_matches(text: str, query: str, case_sensitive: bool = False) -> str:
    """Highlight search matches in text for display.
    
    Args:
        text: Text to highlight
        query: Search query
        case_sensitive: Whether matching should be case sensitive
        
    Returns:
        Text with HTML highlighting tags
    """
    if not query or not text:
        return text
    
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.escape(query)
    
    def replace_func(match):
        return f'<mark style="background-color: #00FFFF; color: #000000;">{match.group()}</mark>'
    
    try:
        return re.sub(pattern, replace_func, text, flags=flags)
    except Exception:
        return text  # Return original text if highlighting fails