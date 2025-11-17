"""
Database Search Engine for Crow Eye.

Provides high-level search functionality across multiple forensic databases
with result aggregation, ranking, caching, and optimization features.
"""

import logging
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from collections import OrderedDict

from .base_loader import BaseDataLoader


@dataclass
class SearchConfig:
    """Configuration for a search operation."""
    search_term: str
    tables: Optional[List[str]] = None
    columns: Optional[Dict[str, List[str]]] = None
    case_sensitive: bool = False
    exact_match: bool = False
    use_regex: bool = False
    max_results: int = 1000
    timeout_seconds: float = 30.0


@dataclass
class SearchResult:
    """Represents a single search result."""
    table_name: str
    row_id: Optional[int]
    matched_columns: List[str]
    record_data: Dict[str, Any]
    relevance_score: float = 1.0
    
    def __post_init__(self):
        """Extract row_id from record_data if not provided."""
        if self.row_id is None and 'id' in self.record_data:
            self.row_id = self.record_data['id']


@dataclass
class SearchResults:
    """Container for search results with metadata."""
    # Fields with defaults must come after fields without defaults
    # All fields have defaults, so order doesn't matter for dataclass
    results: Dict[str, List[SearchResult]] = field(default_factory=dict)
    total_matches: int = 0
    search_time: float = 0.0
    truncated: bool = False
    search_term: str = ""
    tables_searched: int = 0
    tables_with_results: int = 0
    database_name: str = ""  # Database name for time-filtered searches
    
    def add_result(self, result: SearchResult):
        """Add a search result to the container."""
        if result.table_name not in self.results:
            self.results[result.table_name] = []
        self.results[result.table_name].append(result)
        self.total_matches += 1
    
    def get_all_results(self) -> List[SearchResult]:
        """Get all results as a flat list."""
        all_results = []
        for table_results in self.results.values():
            all_results.extend(table_results)
        return all_results
    
    def get_results_by_table(self, table_name: str) -> List[SearchResult]:
        """Get results for a specific table."""
        return self.results.get(table_name, [])
    
    def sort_by_relevance(self):
        """Sort results within each table by relevance score (descending)."""
        for table_name in self.results:
            self.results[table_name].sort(key=lambda r: r.relevance_score, reverse=True)


class SearchCache:
    """LRU cache for search results."""
    
    def __init__(self, max_size: int = 100):
        """
        Initialize search cache.
        
        Args:
            max_size: Maximum number of cached search results
        """
        self.max_size = max_size
        self.cache: OrderedDict[str, SearchResults] = OrderedDict()
        self.lock = threading.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def _make_key(self, config: SearchConfig) -> str:
        """Create a cache key from search configuration."""
        tables_str = ",".join(sorted(config.tables)) if config.tables else "all"
        return (
            f"{config.search_term}|{tables_str}|"
            f"{config.case_sensitive}|{config.exact_match}|"
            f"{config.max_results}"
        )
    
    def get(self, config: SearchConfig) -> Optional[SearchResults]:
        """
        Get cached search results.
        
        Args:
            config: Search configuration
            
        Returns:
            Cached SearchResults or None if not found
        """
        key = self._make_key(config)
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                self.logger.debug(f"Cache hit for search: {config.search_term}")
                return self.cache[key]
        return None
    
    def put(self, config: SearchConfig, results: SearchResults):
        """
        Store search results in cache.
        
        Args:
            config: Search configuration
            results: Search results to cache
        """
        key = self._make_key(config)
        with self.lock:
            # Remove oldest if at capacity
            if len(self.cache) >= self.max_size and key not in self.cache:
                self.cache.popitem(last=False)
            
            self.cache[key] = results
            self.cache.move_to_end(key)
            self.logger.debug(f"Cached search results for: {config.search_term}")
    
    def clear(self):
        """Clear all cached results."""
        with self.lock:
            self.cache.clear()
            self.logger.debug("Search cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'utilization': len(self.cache) / self.max_size if self.max_size > 0 else 0
            }


class DatabaseSearchEngine:
    """
    High-level search engine for forensic databases.
    
    Provides synchronous and asynchronous search operations with result
    aggregation, ranking, caching, and optimization features.
    """
    
    def __init__(self, data_loader: BaseDataLoader, enable_cache: bool = True, cache_size: int = 100):
        """
        Initialize the search engine.
        
        Args:
            data_loader: BaseDataLoader instance for database access
            enable_cache: Whether to enable result caching
            cache_size: Maximum number of cached search results
        """
        self.data_loader = data_loader
        self.logger = logging.getLogger(self.__class__.__name__)
        self.enable_cache = enable_cache
        self.cache = SearchCache(max_size=cache_size) if enable_cache else None
        self._search_thread: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()
    
    def search(
        self,
        search_term: str,
        tables: Optional[List[str]] = None,
        columns: Optional[Dict[str, List[str]]] = None,
        case_sensitive: bool = False,
        exact_match: bool = False,
        max_results: int = 1000,
        timeout_seconds: float = 30.0,
        use_cache: bool = True
    ) -> SearchResults:
        """
        Perform a synchronous search across specified tables.
        
        Args:
            search_term: The term to search for
            tables: List of table names to search (None for all tables)
            columns: Dict mapping table names to column lists to search
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match the exact term (no wildcards)
            max_results: Maximum total results to return
            timeout_seconds: Maximum time to spend searching
            use_cache: Whether to use cached results if available
            
        Returns:
            SearchResults object containing all matches
        """
        # Create search configuration
        config = SearchConfig(
            search_term=search_term,
            tables=tables,
            columns=columns,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            max_results=max_results,
            timeout_seconds=timeout_seconds
        )
        
        # Check cache first
        if use_cache and self.enable_cache:
            cached_results = self.cache.get(config)
            if cached_results is not None:
                return cached_results
        
        # Perform search
        start_time = time.time()
        results = SearchResults(search_term=search_term)
        
        try:
            # Get tables to search
            if tables is None:
                tables = self.data_loader.get_table_names()
            
            if not tables:
                self.logger.warning("No tables found to search")
                return results
            
            results.tables_searched = len(tables)
            
            # Calculate max results per table
            max_per_table = max(100, max_results // len(tables))
            
            # Search each table
            for table_name in tables:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    self.logger.warning(f"Search timeout after {elapsed:.2f}s")
                    results.truncated = True
                    break
                
                # Skip non-existent tables
                if not self.data_loader.table_exists(table_name):
                    self.logger.debug(f"Skipping non-existent table: {table_name}")
                    continue
                
                # Get columns for this table
                table_columns = None
                if columns and table_name in columns:
                    table_columns = columns[table_name]
                
                # Search the table
                table_results = self.data_loader.search_table(
                    table_name=table_name,
                    search_term=search_term,
                    columns=table_columns,
                    case_sensitive=case_sensitive,
                    exact_match=exact_match,
                    page=1,
                    page_size=max_per_table
                )
                
                # Convert to SearchResult objects
                if table_results['total_count'] > 0:
                    results.tables_with_results += 1
                    
                    for record in table_results['data']:
                        # Identify which columns matched
                        matched_cols = self._find_matched_columns(
                            record, search_term, table_columns, case_sensitive
                        )
                        
                        # Calculate relevance score
                        relevance = self._calculate_relevance(
                            record, search_term, matched_cols, case_sensitive
                        )
                        
                        # Create SearchResult
                        search_result = SearchResult(
                            table_name=table_name,
                            row_id=record.get('id'),
                            matched_columns=matched_cols,
                            record_data=record,
                            relevance_score=relevance
                        )
                        
                        results.add_result(search_result)
                        
                        # Check if we've hit max results
                        if results.total_matches >= max_results:
                            results.truncated = True
                            break
                
                if results.truncated:
                    break
            
            # Sort results by relevance
            results.sort_by_relevance()
            
            # Record search time
            results.search_time = time.time() - start_time
            
            # Cache results
            if use_cache and self.enable_cache:
                self.cache.put(config, results)
            
            self.logger.info(
                f"Search completed: '{search_term}' - "
                f"{results.total_matches} matches in {results.search_time:.2f}s"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error during search: {e}", exc_info=True)
            results.search_time = time.time() - start_time
            return results
    
    def search_async(
        self,
        search_term: str,
        callback: Callable[[SearchResults], None],
        tables: Optional[List[str]] = None,
        columns: Optional[Dict[str, List[str]]] = None,
        case_sensitive: bool = False,
        exact_match: bool = False,
        max_results: int = 1000,
        timeout_seconds: float = 30.0,
        use_cache: bool = True
    ) -> None:
        """
        Perform an asynchronous search with callback.
        
        Note: Creates a new database connection in the worker thread to avoid
        SQLite threading issues.
        
        Args:
            search_term: The term to search for
            callback: Function to call with SearchResults when complete
            tables: List of table names to search (None for all tables)
            columns: Dict mapping table names to column lists to search
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match the exact term (no wildcards)
            max_results: Maximum total results to return
            timeout_seconds: Maximum time to spend searching
            use_cache: Whether to use cached results if available
        """
        def search_worker():
            """Worker function for async search."""
            # Create a new loader for this thread to avoid SQLite threading issues
            thread_loader = BaseDataLoader(self.data_loader.db_path)
            thread_engine = DatabaseSearchEngine(thread_loader, enable_cache=False)
            
            try:
                # Connect in the worker thread
                if not thread_loader.connect():
                    self.logger.error("Failed to connect to database in async search")
                    callback(SearchResults(search_term=search_term))
                    return
                
                results = thread_engine.search(
                    search_term=search_term,
                    tables=tables,
                    columns=columns,
                    case_sensitive=case_sensitive,
                    exact_match=exact_match,
                    max_results=max_results,
                    timeout_seconds=timeout_seconds,
                    use_cache=False  # Don't use cache in async thread
                )
                
                # Call callback with results
                if not self._cancel_flag.is_set():
                    callback(results)
                    
            except Exception as e:
                self.logger.error(f"Error in async search: {e}", exc_info=True)
                # Call callback with empty results
                callback(SearchResults(search_term=search_term))
            finally:
                # Clean up thread connection
                thread_loader.disconnect()
        
        # Cancel any existing search
        self.cancel_async_search()
        
        # Start new search thread
        self._cancel_flag.clear()
        self._search_thread = threading.Thread(target=search_worker, daemon=True)
        self._search_thread.start()
        
        self.logger.debug(f"Started async search for: {search_term}")
    
    def cancel_async_search(self):
        """Cancel any running async search."""
        if self._search_thread and self._search_thread.is_alive():
            self._cancel_flag.set()
            self.logger.debug("Cancelled async search")
    
    def _find_matched_columns(
        self,
        record: Dict[str, Any],
        search_term: str,
        columns: Optional[List[str]],
        case_sensitive: bool
    ) -> List[str]:
        """
        Identify which columns in a record contain the search term.
        
        Args:
            record: The database record
            search_term: The search term
            columns: Columns to check (None for all)
            case_sensitive: Whether to use case-sensitive matching
            
        Returns:
            List of column names that contain the search term
        """
        matched = []
        search_lower = search_term.lower() if not case_sensitive else search_term
        
        for col_name, col_value in record.items():
            # Skip if not in specified columns
            if columns and col_name not in columns:
                continue
            
            # Skip non-string values
            if col_value is None:
                continue
            
            value_str = str(col_value)
            value_check = value_str if case_sensitive else value_str.lower()
            
            if search_lower in value_check:
                matched.append(col_name)
        
        return matched
    
    def _calculate_relevance(
        self,
        record: Dict[str, Any],
        search_term: str,
        matched_columns: List[str],
        case_sensitive: bool
    ) -> float:
        """
        Calculate relevance score for a search result.
        
        Higher scores indicate better matches. Scoring factors:
        - Number of matched columns
        - Exact matches vs partial matches
        - Match position (earlier is better)
        - Column importance (filename > path > other)
        
        Args:
            record: The database record
            search_term: The search term
            matched_columns: Columns that contain the search term
            case_sensitive: Whether search was case-sensitive
            
        Returns:
            Relevance score (higher is better)
        """
        if not matched_columns:
            return 0.0
        
        score = 0.0
        search_lower = search_term.lower() if not case_sensitive else search_term
        
        # Column importance weights
        column_weights = {
            'filename': 3.0,
            'name': 3.0,
            'file_name': 3.0,
            'path': 2.0,
            'full_path': 2.0,
            'reconstructed_path': 2.0,
            'description': 1.5,
            'content': 1.5,
        }
        
        for col_name in matched_columns:
            if col_name not in record or record[col_name] is None:
                continue
            
            value_str = str(record[col_name])
            value_check = value_str if case_sensitive else value_str.lower()
            
            # Base score for match
            col_score = 1.0
            
            # Apply column weight
            weight = column_weights.get(col_name.lower(), 1.0)
            col_score *= weight
            
            # Bonus for exact match
            if value_check == search_lower:
                col_score *= 2.0
            
            # Bonus for match at start
            if value_check.startswith(search_lower):
                col_score *= 1.5
            
            # Bonus for shorter values (more specific match)
            if len(value_str) < 50:
                col_score *= 1.2
            
            score += col_score
        
        # Bonus for multiple column matches
        if len(matched_columns) > 1:
            score *= (1.0 + 0.1 * (len(matched_columns) - 1))
        
        return score
    
    def create_indexes_for_search(
        self,
        tables: List[str],
        columns: Dict[str, List[str]]
    ) -> Dict[str, bool]:
        """
        Create indexes on specified columns to optimize search performance.
        
        Args:
            tables: List of table names
            columns: Dict mapping table names to column lists
            
        Returns:
            Dict mapping table names to success status
        """
        results = {}
        
        for table_name in tables:
            if table_name not in columns:
                continue
            
            if not self.data_loader.table_exists(table_name):
                self.logger.warning(f"Table '{table_name}' does not exist")
                results[table_name] = False
                continue
            
            try:
                # Create index for each column
                table_columns = columns[table_name]
                success = True
                
                for column in table_columns:
                    index_name = f"idx_search_{table_name}_{column}"
                    if not self.data_loader.create_index_if_missing(
                        table_name=table_name,
                        columns=[column],
                        index_name=index_name
                    ):
                        success = False
                        self.logger.warning(
                            f"Failed to create index on {table_name}.{column}"
                        )
                
                results[table_name] = success
                
            except Exception as e:
                self.logger.error(f"Error creating indexes for {table_name}: {e}")
                results[table_name] = False
        
        return results
    
    def get_search_suggestions(
        self,
        partial_term: str,
        table: str,
        column: str,
        limit: int = 10
    ) -> List[str]:
        """
        Get search suggestions based on partial input (autocomplete).
        
        Args:
            partial_term: Partial search term
            table: Table name to search
            column: Column name to search
            limit: Maximum number of suggestions
            
        Returns:
            List of suggested search terms
        """
        if not self.data_loader.table_exists(table):
            self.logger.warning(f"Table '{table}' does not exist")
            return []
        
        try:
            # Query for distinct values matching the partial term
            query = f"""
                SELECT DISTINCT {column}
                FROM {table}
                WHERE {column} LIKE ? ESCAPE '\\'
                AND {column} IS NOT NULL
                LIMIT ?
            """
            
            # Escape and add wildcards
            escaped_term = self.data_loader._escape_like_pattern(partial_term)
            params = (f"%{escaped_term}%", limit)
            
            results = self.data_loader.execute_query(query, params)
            
            # Extract column values
            suggestions = [r[column] for r in results if r[column]]
            
            return suggestions
            
        except Exception as e:
            self.logger.error(f"Error getting search suggestions: {e}")
            return []
    
    def clear_cache(self):
        """Clear the search result cache."""
        if self.cache:
            self.cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if self.cache:
            return self.cache.get_stats()
        return {'enabled': False}
