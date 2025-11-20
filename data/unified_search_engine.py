"""
Unified Database Search Engine for Crow Eye.

Provides comprehensive search functionality across multiple forensic artifact
databases with advanced query construction, result aggregation, and search
history management.
"""

import re
import logging
import threading
import sqlite3
import time
import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass

from .database_manager import DatabaseManager, SearchResult, DatabaseInfo, TimestampMatch
from .search_history_manager import SearchHistoryManager, SearchHistoryEntry, SavedSearch
from .database_discovery_manager import DatabaseDiscoveryManager, EnhancedDatabaseInfo, TimestampColumnInfo
from .timestamp_parser import TimestampParser
from data.search_engine import DatabaseSearchEngine, SearchResults
from data.base_loader import BaseDataLoader


@dataclass
class SearchParameters:
    """
    Parameters for a database search operation.
    
    Attributes:
        term: Search term or pattern
        databases: List of database names to search
        tables: Dictionary mapping database names to table lists
        case_sensitive: Whether to perform case-sensitive search
        exact_match: Whether to match exact values only
        use_regex: Whether to interpret term as regex pattern
        max_results_per_table: Maximum results per table (default 1000)
    """
    term: str
    databases: List[str]
    tables: Dict[str, List[str]]
    case_sensitive: bool = False
    exact_match: bool = False
    use_regex: bool = False
    max_results_per_table: int = 1000


class UnifiedDatabaseSearchEngine:
    """
    High-level search engine for searching across multiple forensic databases.
    
    This engine coordinates searches across all artifact databases in a case
    directory, constructs appropriate SQL queries based on search parameters,
    aggregates results, and provides search cancellation capabilities.
    """
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the search engine for a given case.
        
        Args:
            case_directory: The root directory for the case.
        """
        self.case_directory = Path(case_directory)
        self.db_manager = DatabaseManager(self.case_directory)
        self.history_manager = SearchHistoryManager(self.case_directory)
        self.discovery_manager = DatabaseDiscoveryManager(self.case_directory)
        self.timestamp_parser = TimestampParser()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._discovered_databases: Optional[List[DatabaseInfo]] = None
        self._enhanced_databases: Optional[List[EnhancedDatabaseInfo]] = None
        
        self._cancel_event = threading.Event()
        self.current_search_task = None
        
        self.logger.info(f"Initialized unified search engine for case: {self.case_directory}")

    def discover_databases(self) -> List[Dict[str, Any]]:
        """
        Discover all artifact databases in the case directory.
        
        Scans the case directory for known forensic artifact databases and
        returns information about each discovered database including tables,
        accessibility status, and categorization.
        
        Returns:
            List of DatabaseInfo objects for all discovered databases
        """
        self.logger.debug("Discovering databases in case directory")
        
        # Use cached results if available
        if self._discovered_databases is not None:
            return self._discovered_databases
        
        # Discover databases using DatabaseManager
        databases = self.db_manager.discover_databases()
        
        # Cache the results
        self._discovered_databases = databases
        
        # Log summary
        accessible_count = len([db for db in databases if db.accessible])
        self.logger.info(
            f"Discovered {len(databases)} databases, "
            f"{accessible_count} accessible"
        )
        
        return databases
    
    def get_database_schema(self, database_name: str) -> Dict[str, List[str]]:
        """
        Get complete schema information for a database.
        
        Returns a dictionary mapping table names to their column lists.
        
        Args:
            database_name: Name of the database (e.g., 'registry_data.db')
            
        Returns:
            Dictionary mapping table names to column name lists
        """
        self.logger.debug(f"Retrieving schema for database: {database_name}")
        
        try:
            schema = self.db_manager.get_database_schema(database_name)
            
            self.logger.debug(
                f"Retrieved schema for {database_name}: {len(schema)} tables"
            )
            
            return schema
            
        except Exception as e:
            self.logger.error(
                f"Error retrieving schema for {database_name}: {e}",
                exc_info=True
            )
            return {}
    
    def get_available_databases(self) -> Dict[str, DatabaseInfo]:
        """
        Get dictionary of available (accessible) databases.
        
        Returns:
            Dictionary mapping database names to DatabaseInfo objects
        """
        databases = self.discover_databases()
        return {
            db.name: db 
            for db in databases 
            if db.exists and db.accessible
        }
    
    def refresh_database_list(self):
        """
        Refresh the cached list of discovered databases.
        
        Call this method if databases are added or removed from the case
        directory during runtime.
        """
        self.logger.debug("Refreshing database list")
        self._discovered_databases = None
        self._enhanced_databases = None
        self.discovery_manager.clear_cache()
        self.discover_databases()
    
    def discover_databases_with_metadata(
        self,
        force_refresh: bool = False
    ) -> List[EnhancedDatabaseInfo]:
        """
        Discover databases with enhanced metadata including timestamp columns.
        
        Args:
            force_refresh: Force re-discovery and bypass cache
            
        Returns:
            List of EnhancedDatabaseInfo objects
        """
        if not force_refresh and self._enhanced_databases is not None:
            return self._enhanced_databases
        
        enhanced_databases = self.discovery_manager.discover_databases_with_metadata(
            force_refresh=force_refresh,
            verify_timestamps=True,
            sample_size=50
        )
        
        self._enhanced_databases = enhanced_databases
        return enhanced_databases
    
    def add_to_history(
        self,
        term: str,
        databases: List[str],
        tables: Dict[str, List[str]],
        case_sensitive: bool = False,
        exact_match: bool = False,
        use_regex: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        time_preset: Optional[str] = None
    ) -> bool:
        """
        Add a search to the search history.
        
        Saves the search parameters to persistent storage for later retrieval.
        History is limited to the 20 most recent searches.
        
        Args:
            term: Search term or pattern
            databases: List of database names searched
            tables: Dictionary mapping database names to table lists
            case_sensitive: Whether search was case-sensitive
            exact_match: Whether search was exact match
            use_regex: Whether search used regex
            start_time: Optional start datetime for time filtering (ISO format)
            end_time: Optional end datetime for time filtering (ISO format)
            time_preset: Optional preset name used for time filtering
            
        Returns:
            True if save was successful, False otherwise
        """
        return self.history_manager.save_history(
            term=term,
            databases=databases,
            tables=tables,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            use_regex=use_regex,
            start_time=start_time,
            end_time=end_time,
            time_preset=time_preset
        )
    
    def get_search_history(self) -> List[SearchHistoryEntry]:
        """
        Retrieve recent search history.
        
        Returns up to 20 most recent searches, ordered with most recent first.
        
        Returns:
            List of SearchHistoryEntry objects
        """
        return self.history_manager.load_history()
    
    def clear_search_history(self) -> bool:
        """
        Clear all search history.
        
        Returns:
            True if clear was successful, False otherwise
        """
        return self.history_manager.clear_history()
    
    def save_search(
        self,
        name: str,
        term: str,
        databases: List[str],
        tables: Dict[str, List[str]],
        case_sensitive: bool = False,
        exact_match: bool = False,
        use_regex: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        time_preset: Optional[str] = None
    ) -> bool:
        """
        Save a search with a user-provided name.
        
        Stores the search parameters for easy retrieval later. If a saved
        search with the same name already exists, it will be updated.
        
        Args:
            name: User-provided name for the search
            term: Search term or pattern
            databases: List of database names to search
            tables: Dictionary mapping database names to table lists
            case_sensitive: Whether search is case-sensitive
            exact_match: Whether search is exact match
            use_regex: Whether search uses regex
            start_time: Optional start datetime for time filtering (ISO format)
            end_time: Optional end datetime for time filtering (ISO format)
            time_preset: Optional preset name used for time filtering
            
        Returns:
            True if save was successful, False otherwise
        """
        return self.history_manager.save_named_search(
            name=name,
            term=term,
            databases=databases,
            tables=tables,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            use_regex=use_regex,
            start_time=start_time,
            end_time=end_time,
            time_preset=time_preset
        )
    
    def get_saved_searches(self) -> List[SavedSearch]:
        """
        Retrieve all saved searches.
        
        Returns:
            List of SavedSearch objects
        """
        return self.history_manager.load_saved_searches()
    
    def get_saved_search(self, search_name: str) -> Optional[SavedSearch]:
        """Get a single saved search by its name."""
        return self.history_manager.get_saved_search(search_name)

    def delete_saved_search(self, search_name: str) -> bool:
        """Delete a saved search by its name."""
        return self.history_manager.delete_saved_search(search_name)

    def update_saved_search_last_used(self, search_name: str) -> bool:
        """Update the last_used timestamp of a saved search."""
        return self.history_manager.update_saved_search_last_used(search_name)

    def close(self):
        """
        Close any open resources, such as database connections.
        """
        self.logger.info("Closing UnifiedDatabaseSearchEngine resources.")
        
        if hasattr(self, 'db_manager'):
            try:
                self.db_manager.close_all()
            except Exception as e:
                self.logger.error(f"Error closing database manager: {e}")
                
        if hasattr(self, 'discovery_manager'):
            try:
                self.discovery_manager.close()
            except Exception as e:
                self.logger.error(f"Error closing discovery manager: {e}")

    def reset_cancellation(self):
        """
        Reset the cancellation flag to allow new searches.
        """
        self._cancel_event.clear()
        self.logger.info("Search cancellation flag reset")

    def reset_for_search(self):
        """
        Reset database manager state before running a new search.
        """
        self.logger.info("Resetting search engine state for new search")
        
        # Close existing managers
        try:
            if hasattr(self, 'db_manager'):
                self.db_manager.close_all()
            if hasattr(self, 'discovery_manager'):
                self.discovery_manager.close()
        except Exception as e:
            self.logger.error(f"Error closing managers during reset: {e}")
            
        # Re-initialize managers to ensure fresh state
        # This is critical for the time filter bug where connections became stale
        self.db_manager = DatabaseManager(self.case_directory)
        self.discovery_manager = DatabaseDiscoveryManager(self.case_directory)
        self.logger.debug("Re-initialized database and discovery managers")

    def search(
        self,
        search_term: str,
        databases: Optional[List[str]] = None,
        tables: Optional[Dict[str, List[str]]] = None,
        case_sensitive: bool = False,
        exact_match: bool = False,
        use_regex: bool = False,
        max_results_per_table: int = 1000,
        timeout_seconds: float = 60.0,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        completion_callback: Optional[Callable[[List[SearchResults]], None]] = None
    ) -> List[SearchResults]:
        """
        Perform a unified search across multiple databases with optional time filtering.
        
        Args:
            search_term: Text to search for
            databases: Optional list of database names to search
            tables: Optional dict mapping database names to table lists
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match exact values only
            use_regex: Whether to interpret term as regex pattern
            max_results_per_table: Maximum results per table
            timeout_seconds: Search timeout in seconds
            start_time: Optional start datetime for time filtering
            end_time: Optional end datetime for time filtering
            progress_callback: Optional callback for progress updates
            completion_callback: Optional callback when search completes
            
        Returns:
            List of SearchResults objects
        """
        self._cancel_event.clear()
        self.reset_for_search()
        try:
            self.discovery_manager.clear_cache()
        except Exception:
            pass
        self._discovered_databases = None
        self._enhanced_databases = None
        all_results = []
        
        # Check if time filtering is requested
        time_filtering_enabled = start_time is not None or end_time is not None

        # Discover databases with enhanced metadata if time filtering is enabled
        if time_filtering_enabled:
            self.logger.info("Time filtering enabled - discovering databases with timestamp metadata")
            # CRITICAL: Force refresh on each search to ensure fresh database connections
            # and metadata. Without this, cached connections can become stale and return
            # incorrect results on subsequent searches with different time parameters.
            enhanced_db_infos = self.discovery_manager.discover_databases_with_metadata(
                verify_timestamps=True,
                sample_size=50,
                force_refresh=True  # Changed from False to True to fix caching bug
            )
            self._enhanced_databases = enhanced_db_infos
            
            # Filter to requested databases
            if databases:
                enhanced_db_infos = [db for db in enhanced_db_infos if db.name in databases]
            
            # Filter to only accessible databases
            enhanced_db_infos = [db for db in enhanced_db_infos if db.accessible]
            
            if not enhanced_db_infos:
                self.logger.warning("No accessible databases found for time-filtered search.")
                if completion_callback:
                    completion_callback([])
                return []
        else:
            # Use standard database discovery
            db_infos = self.db_manager.discover_databases()
            if databases:
                db_infos = [db for db in db_infos if db.name in databases]
            
            if not db_infos:
                self.logger.warning("No databases found or specified for search.")
                if completion_callback:
                    completion_callback([])
                return []

        start_search_time = time.time()

        # Perform search based on whether time filtering is enabled
        if time_filtering_enabled:
            print(f"[INFO] Time filtering enabled - searching {len(enhanced_db_infos)} databases")
            print(f"[INFO] Time range: {start_time} to {end_time}")
            self.logger.info(f"Starting time-filtered search: {start_time} to {end_time}")
            
            for i, enhanced_db_info in enumerate(enhanced_db_infos):
                if self._cancel_event.is_set():
                    self.logger.info("Search was cancelled.")
                    break

                # Progress indicator with percentage (Requirements: 14.3)
                progress_pct = int((i / len(enhanced_db_infos)) * 100)
                if progress_callback:
                    progress_callback(
                        f"[{progress_pct}%] Searching database {i+1}/{len(enhanced_db_infos)}: "
                        f"{enhanced_db_info.gui_tab_name or enhanced_db_info.name}..."
                    )

                try:
                    # Get tables for this specific database
                    db_tables = None
                    if tables and enhanced_db_info.name in tables:
                        db_tables = tables[enhanced_db_info.name]
                    
                    results = self._search_database_with_time_filter(
                        enhanced_db_info=enhanced_db_info,
                        search_term=search_term,
                        tables=db_tables,
                        case_sensitive=case_sensitive,
                        exact_match=exact_match,
                        max_results=max_results_per_table,
                        timeout_seconds=timeout_seconds,
                        start_time=start_time,
                        end_time=end_time
                    )
                    if results:
                        all_results.append(results)
                except Exception as e:
                    self.logger.error(f"Error searching database {enhanced_db_info.name}: {e}", exc_info=True)
        else:
            # Standard search without time filtering
            for i, db_info in enumerate(db_infos):
                if self._cancel_event.is_set():
                    self.logger.info("Search was cancelled.")
                    break

                # Progress indicator with percentage (Requirements: 14.3)
                progress_pct = int((i / len(db_infos)) * 100)
                if progress_callback:
                    progress_callback(
                        f"[{progress_pct}%] Searching database {i+1}/{len(db_infos)}: "
                        f"{db_info.display_name or db_info.name}..."
                    )

                try:
                    # Get tables for this specific database
                    db_tables = None
                    if tables and db_info.name in tables:
                        db_tables = tables[db_info.name]
                    
                    results = self._search_database(
                        db_info=db_info,
                        search_term=search_term,
                        tables=db_tables,
                        case_sensitive=case_sensitive,
                        exact_match=exact_match,
                        max_results=max_results_per_table,
                        timeout_seconds=timeout_seconds
                    )
                    if results:
                        all_results.append(results)
                except Exception as e:
                    self.logger.error(f"Error searching database {db_info.name}: {e}", exc_info=True)

        elapsed_time = time.time() - start_search_time
        total_matches = sum(res.total_matches for res in all_results)
        
        if time_filtering_enabled:
            self.logger.info(
                f"Time-filtered search completed in {elapsed_time:.2f}s with {total_matches} total matches "
                f"(start: {start_time}, end: {end_time})"
            )
        else:
            self.logger.info(f"Unified search completed in {elapsed_time:.2f}s with {total_matches} total matches.")

        # Add to history
        self.history_manager.save_history(
            term=search_term,
            databases=databases or [],
            tables=tables or {},
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            use_regex=use_regex
        )

        print(f"[SEARCH] Returning {len(all_results)} SearchResults objects to caller")
        for idx, sr in enumerate(all_results):
            print(f"[SEARCH]   Result {idx}: {sr.database_name if hasattr(sr, 'database_name') else 'Unknown'} - {sr.total_matches} matches")
        
        if completion_callback:
            completion_callback(all_results)

        return all_results

    def _search_database(
        self,
        db_info: DatabaseInfo,
        search_term: str,
        tables: Optional[List[str]],
        case_sensitive: bool,
        exact_match: bool,
        max_results: int,
        timeout_seconds: float
    ) -> Optional[SearchResults]:
        """
        Search a single database using the DatabaseSearchEngine.
        """
        loader = BaseDataLoader(db_info.path)
        if not loader.connect():
            self.logger.error(f"Failed to connect to database: {db_info.path}")
            return None

        try:
            engine = DatabaseSearchEngine(loader, enable_cache=False)
            
            # Perform the search
            results = engine.search(
                search_term=search_term,
                tables=tables,
                case_sensitive=case_sensitive,
                exact_match=exact_match,
                max_results=max_results,
                timeout_seconds=timeout_seconds
            )
            
            # Add database name to results for context
            results.database_name = db_info.name
            return results
            
        except Exception as e:
            self.logger.error(f"Error during search in {db_info.name}: {e}", exc_info=True)
            return None
        finally:
            loader.disconnect()
    
    def _search_database_with_time_filter(
        self,
        enhanced_db_info: EnhancedDatabaseInfo,
        search_term: str,
        tables: Optional[List[str]],
        case_sensitive: bool,
        exact_match: bool,
        max_results: int,
        timeout_seconds: float,
        start_time: Optional[datetime.datetime],
        end_time: Optional[datetime.datetime]
    ) -> Optional[SearchResults]:
        """
        Search a single database with time filtering.
        
        Args:
            enhanced_db_info: Enhanced database information with timestamp metadata
            search_term: Text to search for
            tables: Optional list of tables to search
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match exact values only
            max_results: Maximum results per table
            timeout_seconds: Search timeout in seconds
            start_time: Optional start datetime for filtering
            end_time: Optional end datetime for filtering
            
        Returns:
            SearchResults object or None if search fails
        """
        search_start_time = time.time()
        
        loader = BaseDataLoader(enhanced_db_info.path)
        if not loader.connect():
            self.logger.error(f"Failed to connect to database: {enhanced_db_info.path}")
            return None

        try:
            # Determine which tables to search
            search_tables = tables if tables else list(enhanced_db_info.tables.keys())
            
            # Filter to only tables that support time filtering
            time_filterable_tables = []
            non_time_filterable_tables = []
            
            for table_name in search_tables:
                table_info = enhanced_db_info.tables.get(table_name)
                if table_info and table_info.supports_time_filtering:
                    time_filterable_tables.append(table_name)
                else:
                    non_time_filterable_tables.append(table_name)
            
            if not time_filterable_tables:
                self.logger.warning(
                    f"No tables with timestamp columns found in {enhanced_db_info.name}. "
                    "Performing regular search without time filtering."
                )
                # Fall back to regular search
                engine = DatabaseSearchEngine(loader, enable_cache=False)
                results = engine.search(
                    search_term=search_term,
                    tables=search_tables,
                    case_sensitive=case_sensitive,
                    exact_match=exact_match,
                    max_results=max_results,
                    timeout_seconds=timeout_seconds
                )
                results.database_name = enhanced_db_info.name
                return results
            
            # Log which tables will be time-filtered
            self.logger.debug(
                f"Time-filtering {len(time_filterable_tables)} tables in {enhanced_db_info.name}: "
                f"{', '.join(time_filterable_tables)}"
            )
            
            if non_time_filterable_tables:
                self.logger.debug(
                    f"Skipping time filter for {len(non_time_filterable_tables)} tables without timestamps: "
                    f"{', '.join(non_time_filterable_tables)}"
                )
            
            # Perform time-filtered search on each table
            all_table_results = []
            
            for table_name in time_filterable_tables:
                # Check for cancellation
                if self._cancel_event.is_set():
                    self.logger.info(f"Search cancelled while processing {table_name}")
                    break
                
                # Check for timeout
                elapsed = time.time() - search_start_time
                if elapsed > timeout_seconds:
                    self.logger.warning(
                        f"Search timeout reached ({timeout_seconds}s) while processing {table_name}. "
                        f"Returning partial results."
                    )
                    break
                
                table_info = enhanced_db_info.tables[table_name]
                table_start_time = time.time()
                
                try:
                    table_loader = BaseDataLoader(enhanced_db_info.path)
                    if not table_loader.connect():
                        continue
                    indexed_columns = []
                    
                    # Build time-filtered query
                    query = self._build_time_filtered_query(
                        search_term=search_term,
                        table_name=table_name,
                        timestamp_columns=table_info.timestamp_columns,
                        case_sensitive=case_sensitive,
                        exact_match=exact_match,
                        start_time=start_time,
                        end_time=end_time,
                        max_results=max_results
                    )
                    
                    
                    
                    # Execute query with remaining timeout
                    remaining_timeout = timeout_seconds - elapsed
                    results = table_loader.execute_query(
                        query,
                        params=(),
                        fetch=True
                    )
                    
                    print(f"[INFO] Query returned {len(results)} raw results from {table_name}")
                    self.logger.info(f"Query returned {len(results)} raw results from {table_name}")
                    
                    # Parse and filter timestamps for verification
                    filtered_results = self._parse_and_filter_timestamps(
                        results=results,
                        table_name=table_name,
                        timestamp_columns=table_info.timestamp_columns,
                        start_time=start_time,
                        end_time=end_time,
                        database_name=enhanced_db_info.name,
                        gui_tab_name=enhanced_db_info.gui_tab_name,
                        search_term=search_term,
                        case_sensitive=case_sensitive
                    )

                    if not filtered_results:
                        fallback_query = f"SELECT * FROM \"{table_name}\" LIMIT {max_results * 10}"
                        fallback_rows = table_loader.execute_query(
                            fallback_query,
                            params=(),
                            fetch=True
                        )
                        filtered_results = self._parse_and_filter_timestamps(
                            results=fallback_rows,
                            table_name=table_name,
                            timestamp_columns=table_info.timestamp_columns,
                            start_time=start_time,
                            end_time=end_time,
                            database_name=enhanced_db_info.name,
                            gui_tab_name=enhanced_db_info.gui_tab_name,
                            search_term=search_term,
                            case_sensitive=case_sensitive
                        )
                    
                    all_table_results.extend(filtered_results)
                    
                    # Log performance metrics (Requirements: 14.5)
                    table_elapsed = time.time() - table_start_time
                    self.logger.info(
                        f"Searched {table_name} in {table_elapsed:.2f}s: "
                        f"{len(filtered_results)} results (indexed: {len(indexed_columns)} columns)"
                    )
                    
                except Exception as e:
                    self.logger.error(
                        f"Error searching table {table_name} in {enhanced_db_info.name}: {e}",
                        exc_info=True
                    )
                finally:
                    try:
                        table_loader.disconnect()
                    except Exception:
                        pass
            
            # Create SearchResults object (imported at top of file)
            total_search_time = time.time() - search_start_time
            
            # Log overall performance metrics (Requirements: 14.5)
            self.logger.info(
                f"Time-filtered search in {enhanced_db_info.name} completed in {total_search_time:.2f}s: "
                f"{len(all_table_results)} total results from {len(time_filterable_tables)} tables"
            )
            
            # Group results by table for SearchResults structure
            results_by_table = {}
            for result in all_table_results:
                table_name = result.table
                if table_name not in results_by_table:
                    results_by_table[table_name] = []
                results_by_table[table_name].append(result)
            
            print(f"[INFO] Creating SearchResults with {len(all_table_results)} results across {len(results_by_table)} tables")
            
            search_results = SearchResults(
                database_name=enhanced_db_info.name,
                search_term=search_term,
                total_matches=len(all_table_results),
                results=results_by_table,  # Dictionary of table_name -> list of results
                search_time=total_search_time
            )
            
            return search_results
            
        except Exception as e:
            self.logger.error(f"Error during time-filtered search in {enhanced_db_info.name}: {e}", exc_info=True)
            return None
        finally:
            loader.disconnect()
    
    def _build_time_filtered_query(
        self,
        search_term: str,
        table_name: str,
        timestamp_columns: List[TimestampColumnInfo],
        case_sensitive: bool,
        exact_match: bool,
        start_time: Optional[datetime.datetime],
        end_time: Optional[datetime.datetime],
        max_results: int
    ) -> str:
        """
        Construct SQL query with time filtering constraints.
        
        Generates WHERE clauses that check if any timestamp column
        falls within the specified range using OR logic.
        
        Args:
            search_term: Text to search for
            table_name: Name of the table to search
            timestamp_columns: List of timestamp column information
            case_sensitive: Whether to perform case-sensitive search
            exact_match: Whether to match exact values only
            start_time: Optional start datetime
            end_time: Optional end datetime
            max_results: Maximum number of results
            
        Returns:
            SQL query string with time filtering
        """
        # Build base search conditions
        search_conditions = []
        
        # Get all columns for the table (we'll search text columns)
        # For now, we'll use a simple LIKE search across all columns
        # This is a simplified version - in production, you'd want to get column info
        
        # Build time filter conditions
        time_conditions = []
        
        for ts_col in timestamp_columns:
            col_name = ts_col.name
            col_conditions = []
            
            # Handle different timestamp formats
            if ts_col.format in ['iso8601', 'datetime']:
                # String-based timestamp comparison
                if start_time:
                    start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
                    col_conditions.append(f'"{col_name}" >= \'{start_str}\'')
                
                if end_time:
                    end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
                    col_conditions.append(f'"{col_name}" <= \'{end_str}\'')
            
            elif ts_col.format == 'unix':
                # Unix timestamp comparison (numeric)
                if start_time:
                    start_unix = int(start_time.timestamp())
                    col_conditions.append(f'"{col_name}" >= {start_unix}')
                
                if end_time:
                    end_unix = int(end_time.timestamp())
                    col_conditions.append(f'"{col_name}" <= {end_unix}')
            
            elif ts_col.format == 'filetime':
                # Windows FILETIME comparison (large integer)
                if start_time:
                    # Convert to FILETIME (100-nanosecond intervals since 1601-01-01)
                    start_filetime = int((start_time.timestamp() + 11644473600) * 10000000)
                    col_conditions.append(f'"{col_name}" >= {start_filetime}')
                
                if end_time:
                    end_filetime = int((end_time.timestamp() + 11644473600) * 10000000)
                    col_conditions.append(f'"{col_name}" <= {end_filetime}')
            
            else:
                # Unknown or mixed format - try string comparison
                if start_time:
                    start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
                    col_conditions.append(f'"{col_name}" >= \'{start_str}\'')
                
                if end_time:
                    end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
                    col_conditions.append(f'"{col_name}" <= \'{end_str}\'')
            
            # Combine conditions for this column with AND
            if col_conditions:
                time_conditions.append('(' + ' AND '.join(col_conditions) + ')')
        
        # Combine all timestamp column conditions with OR
        time_filter = ' OR '.join(time_conditions) if time_conditions else '1=1'
        
        # Build search term conditions
        # We'll search across all columns using LIKE
        search_operator = '=' if exact_match else 'LIKE'
        search_value = search_term if exact_match else f'%{search_term}%'
        
        # For case-insensitive search in SQLite, we can use LIKE (which is case-insensitive by default)
        # For case-sensitive, we need to use GLOB or add COLLATE BINARY
        if case_sensitive and not exact_match:
            # Use GLOB for case-sensitive pattern matching
            search_value = f'*{search_term}*'
            search_operator = 'GLOB'
        elif case_sensitive and exact_match:
            # Use = with COLLATE BINARY for case-sensitive exact match
            search_operator = '= COLLATE BINARY'
        
        # Build the complete query
        # We search all columns by checking if any column contains the search term
        # This is done by getting all columns and building OR conditions
        query = f"""
            SELECT * FROM "{table_name}"
            WHERE ({time_filter})
            AND (
                SELECT COUNT(*) FROM pragma_table_info('{table_name}') AS col
                WHERE (
                    SELECT "{table_name}"."" || col.name || "" {search_operator} '{search_value}'
                ) > 0
            )
            LIMIT {max_results}
        """
        
        # Simpler approach: Just filter by time and let the post-processing handle search term matching
        # This is more reliable and works with all column types
        query = f"""
            SELECT * FROM "{table_name}"
            WHERE ({time_filter})
            LIMIT {max_results * 10}
        """
        
        # Log the query for debugging
        print(f"[QUERY] Table: {table_name}")
        print(f"[QUERY]   Timestamp columns: {[(col.name, col.format) for col in timestamp_columns]}")
        print(f"[QUERY]   Time filter SQL: {time_filter}")
        self.logger.debug(f"Generated time-filtered query for {table_name}:")
        self.logger.debug(f"  Time filter: {time_filter}")
        self.logger.debug(f"  Timestamp columns: {[(col.name, col.format) for col in timestamp_columns]}")
        self.logger.debug(f"  Full query: {query}")
        
        return query
    
    def _parse_and_filter_timestamps(
        self,
        results: List[Dict[str, Any]],
        table_name: str,
        timestamp_columns: List[TimestampColumnInfo],
        start_time: Optional[datetime.datetime],
        end_time: Optional[datetime.datetime],
        database_name: str,
        gui_tab_name: str,
        search_term: str = "",
        case_sensitive: bool = False
    ) -> List[SearchResult]:
        """
        Post-process results to verify timestamp filtering and add metadata.
        
        Parses timestamp values from results and adds matched_timestamp metadata
        to each result. Filters out results that don't match after parsing.
        Also filters by search term if provided.
        
        Args:
            results: Raw query results
            table_name: Name of the table
            timestamp_columns: List of timestamp column information
            start_time: Optional start datetime
            end_time: Optional end datetime
            database_name: Name of the database
            gui_tab_name: GUI tab name for navigation
            search_term: Optional search term to filter by
            case_sensitive: Whether search is case-sensitive
            
        Returns:
            List of SearchResult objects with timestamp metadata
        """
        filtered_results = []
        
        print(f"[DEBUG] Filtering {len(results)} results for table {table_name}")
        print(f"[DEBUG]   Search term: '{search_term}', Case sensitive: {case_sensitive}")
        print(f"[DEBUG]   Time range: {start_time} to {end_time}")
        self.logger.debug(f"Filtering {len(results)} results for table {table_name}")
        self.logger.debug(f"  Search term: '{search_term}', Case sensitive: {case_sensitive}")
        self.logger.debug(f"  Time range: {start_time} to {end_time}")
        
        for row in results:
            # First check if row matches search term (if provided)
            if search_term:
                row_matches_search = False
                matched_columns = []
                
                for col_name, col_value in row.items():
                    if col_value is None:
                        continue
                    
                    # Convert to string for searching
                    str_value = str(col_value)
                    search_str = search_term
                    
                    # Handle case sensitivity
                    if not case_sensitive:
                        str_value = str_value.lower()
                        search_str = search_str.lower()
                    
                    # Check if search term is in the value
                    if search_str in str_value:
                        row_matches_search = True
                        matched_columns.append(col_name)
                
                # Skip this row if it doesn't match the search term
                if not row_matches_search:
                    continue
            else:
                matched_columns = list(row.keys())
            
            # Now check timestamps
            matched_timestamps = []
            has_valid_timestamp = False
            
            # Check each timestamp column
            for ts_col in timestamp_columns:
                col_name = ts_col.name
                
                if col_name not in row or row[col_name] is None:
                    continue
                
                # Parse the timestamp
                parsed_dt = self.timestamp_parser.parse_timestamp(
                    row[col_name],
                    hint=ts_col.format if ts_col.format != 'mixed' else None
                )
                
                if parsed_dt is None:
                    continue
                
                # Check if timestamp falls within range
                in_range = True
                
                # Ensure both timestamps are comparable (handle timezone awareness)
                # If one is timezone-aware and the other isn't, make both naive for comparison
                compare_parsed_dt = parsed_dt
                compare_start_time = start_time
                compare_end_time = end_time
                
                if parsed_dt and start_time:
                    if parsed_dt.tzinfo is not None and start_time.tzinfo is None:
                        compare_parsed_dt = parsed_dt.replace(tzinfo=None)
                    elif parsed_dt.tzinfo is None and start_time.tzinfo is not None:
                        compare_start_time = start_time.replace(tzinfo=None)
                
                if parsed_dt and end_time:
                    if parsed_dt.tzinfo is not None and end_time.tzinfo is None:
                        compare_parsed_dt = parsed_dt.replace(tzinfo=None)
                    elif parsed_dt.tzinfo is None and end_time.tzinfo is not None:
                        compare_end_time = end_time.replace(tzinfo=None)
                
                if compare_start_time and compare_parsed_dt < compare_start_time:
                    in_range = False
                
                if compare_end_time and compare_parsed_dt > compare_end_time:
                    in_range = False
                
                if in_range:
                    has_valid_timestamp = True
                    
                    # Format for display
                    include_microseconds = parsed_dt.microsecond > 0
                    formatted_display = self.timestamp_parser.format_for_display(
                        parsed_dt,
                        include_microseconds=include_microseconds
                    )
                    
                    # Create TimestampMatch
                    matched_timestamps.append(
                        TimestampMatch(
                            column_name=col_name,
                            original_value=row[col_name],
                            parsed_value=parsed_dt,
                            formatted_display=formatted_display,
                            format_type=ts_col.format
                        )
                    )
            
            # Only include results with at least one valid timestamp in range
            if has_valid_timestamp:
                # Try to get row ID (common column names)
                row_id = None
                for id_col in ['id', 'rowid', 'ID', 'ROWID', '_rowid_']:
                    if id_col in row:
                        row_id = row[id_col]
                        break
                
                # Create SearchResult
                search_result = SearchResult(
                    database=database_name,
                    table=table_name,
                    row_id=row_id,
                    matched_columns=matched_columns if 'matched_columns' in locals() else list(row.keys()),
                    row_data=row,
                    match_preview="",
                    matched_timestamps=matched_timestamps,
                    supports_navigation=True,
                    gui_tab_name=gui_tab_name
                )
                
                filtered_results.append(search_result)
        
        print(f"[INFO] Filtered results for {table_name}: {len(filtered_results)} out of {len(results)} passed filters")
        self.logger.info(f"Filtered results for {table_name}: {len(filtered_results)} out of {len(results)} passed filters")
        
        return filtered_results

    def cancel_search(self):
        """
        Cancel an ongoing search operation.
        
        Sets the cancellation flag that is checked during search execution.
        The search will stop at the next checkpoint (between databases/tables).
        """
        self.logger.info("Cancelling search")
        self._cancel_event.set()
    
    def is_search_cancelled(self) -> bool:
        """
        Check if search has been cancelled.
        
        Returns:
            True if search is cancelled, False otherwise
        """
        return self._cancel_event.is_set()
