"""
Unified Database Search Engine for Crow Eye.

Provides comprehensive search functionality across multiple forensic artifact
databases with advanced query construction, result aggregation, and search
history management.
"""

import os
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
from data.base_loader import BaseDataLoader, value_matcher

# Tables (and slices of tables) searched at once. sqlite3 releases the GIL
# while a query runs, so a LIKE scan of one table proceeds beside another's.
# One per core, at least the six this started with and at most sixteen.
# Measured on a live parse of this machine (3.9 M MFT/USN rows, 32 cores):
# 54 s table by table, 19.2 s on six threads (the largest table 16.6 s of
# it), 8.2 s with the slices below on sixteen, the same hits each time.
SEARCH_THREADS = min(16, max(6, os.cpu_count() or 6))

# A table of at least twice this many rowids is searched in slices of about
# this size, each its own task on the pool, so the largest table no longer
# bounds the whole search alone. The LIKE over the 43 columns of
# mft_usn_correlated is CPU (9 to 10 s warm against 1.6 s to read the rows),
# and a narrow row count is not a small table: 265,000 AI agent steps of
# prompt and output text took 13.6 s read whole. At most SEARCH_SLICES of one
# table, so one table cannot queue thousands of tasks.
SLICE_ROWS = 50000
SEARCH_SLICES = 12
_ROWID_MIN = -(2 ** 63)
_ROWID_MAX = 2 ** 63 - 1


def rowid_slices(lo, hi, slice_rows=SLICE_ROWS, most=SEARCH_SLICES):
    """[(lo, hi), ...] covering every rowid of a table whose rowids run from
    `lo` to `hi`, or None when it is small enough to read as one. The first
    slice starts at the smallest rowid there can be and the last ends at the
    largest, so a row written while the search runs is in a slice exactly as
    it would be in one scan."""
    if lo is None or hi is None:
        return None
    span = int(hi) - int(lo) + 1
    if span < slice_rows * 2:
        return None
    n = min(most, -(-span // slice_rows))
    step = -(-span // n)
    out = []
    for i in range(n):
        a = int(lo) + i * step
        b = min(int(hi), a + step - 1)
        out.append((_ROWID_MIN if i == 0 else a, _ROWID_MAX if i == n - 1 else b))
    return out


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
        self.logger = logging.getLogger(__name__)
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
        completion_callback: Optional[Callable[[List[SearchResults]], None]] = None,
        record_history: bool = True
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
            record_history: Save the search to history here. The dialog
                passes False: it saves its own entry, with the time filter,
                and each search was listed twice

        Returns:
            List of SearchResults objects
        """
        if use_regex:
            try:
                re.compile(search_term)
            except re.error as e:
                raise ValueError("not a valid regular expression: %s" % e)
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
            
            # One read per physical file, whatever the tree called it.
            enhanced_db_infos, tables, db_aliases = self._one_entry_per_file(
                enhanced_db_infos, tables)

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
            
            db_infos = [d for d in db_infos
                        if getattr(d, "exists", False) and getattr(d, "accessible", False)]
            db_infos, tables, db_aliases = self._one_entry_per_file(
                db_infos, tables)

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

                # Progress indicator with percentage 
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
                    db_tables = self._tables_or_all(db_tables, enhanced_db_info)
                    
                    results = self._search_database_with_time_filter(
                        enhanced_db_info=enhanced_db_info,
                        search_term=search_term,
                        tables=db_tables,
                        case_sensitive=case_sensitive,
                        exact_match=exact_match,
                        max_results=max_results_per_table,
                        timeout_seconds=timeout_seconds,
                        start_time=start_time,
                        end_time=end_time,
                        use_regex=use_regex
                    )
                    if results:
                        all_results.append(results)
                except Exception as e:
                    self.logger.error(f"Error searching database {enhanced_db_info.name}: {e}", exc_info=True)
        else:
            # Standard search without time filtering: every table at once.
            all_results.extend(self._search_tables_in_parallel(
                db_infos, tables, search_term, case_sensitive, exact_match,
                max_results_per_table, timeout_seconds, progress_callback,
                use_regex=use_regex))


        elapsed_time = time.time() - start_search_time
        total_matches = sum(res.total_matches for res in all_results)
        
        if time_filtering_enabled:
            self.logger.info(
                f"Time-filtered search completed in {elapsed_time:.2f}s with {total_matches} total matches "
                f"(start: {start_time}, end: {end_time})"
            )
        else:
            self.logger.info(f"Unified search completed in {elapsed_time:.2f}s with {total_matches} total matches.")

        if record_history:
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

    def _search_tables_in_parallel(self, db_infos, tables, search_term, case_sensitive,
                                   exact_match, max_results, timeout_seconds,
                                   progress_callback=None, use_regex=False):
        """Search every table of every database on SEARCH_THREADS threads.

        Returns one SearchResults per database, in the databases' order, with
        exactly what the table-by-table search returned: each table capped at
        max(100, max_results // its database's table count), and a database's
        results cut at max_results in table order. Each task opens its own
        connection (a sqlite3 connection belongs to its thread).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import os

        plans = []          # (database info, [tables], per-table cap)
        for info in db_infos:
            db_tables = tables.get(info.name) if tables and info.name in tables else None
            db_tables = self._tables_or_all(db_tables, info)
            if db_tables is None:
                loader = BaseDataLoader(info.path)
                if not loader.connect():
                    self.logger.error(f"Failed to connect to database: {info.path}")
                    continue
                try:
                    db_tables = loader.get_table_names()
                finally:
                    loader.disconnect()
            shadow = self._shadow_tables(info.path)
            db_tables = [t for t in (db_tables or []) if t not in shadow]
            plans.append((info, db_tables, max(100, max_results // max(1, len(db_tables)))))

        # (database, table, rowid slice or None for the whole table)
        tasks = []
        slices = {}
        for p, (info, ts, _c) in enumerate(plans):
            spans = self._rowid_spans(info.path, ts)
            for t in ts:
                parts = rowid_slices(*spans[t]) if t in spans else None
                slices[(p, t)] = parts or [None]
                tasks.extend((p, t, r) for r in slices[(p, t)])

        # ONCE THE FIRST SLICES HOLD THE CAP, THE REST ARE STOPPED. One scan
        # of a table stops at its cap; its slices each ran to their own, so a
        # common term read a sliced table a dozen times over (3.6 s -> 5.0 s
        # for "chrome" on this case). When slices 0..k of a table have all
        # answered and together hold its cap, rows past slice k can never be
        # kept (_join_slices keeps the first cap rows in rowid order), so a
        # slice after k that is running is interrupted (BaseDataLoader.interrupt:
        # sqlite3_interrupt may be called from another thread, and the loader
        # then logs its "interrupted" errors at debug) and one not started is
        # skipped.
        cut_lock = threading.Lock()
        cuts = {key: {"done": {}, "conns": {}, "upto": None}
                for key, parts in slices.items() if len(parts) > 1}

        def _past_the_cut(state, i):
            return state["upto"] is not None and i > state["upto"]

        def _answered(state, i, matches, cap):
            state["done"][i] = matches
            if state["upto"] is not None:
                return
            total, k = 0, 0
            while k in state["done"]:
                total += state["done"][k]
                if total >= cap:
                    state["upto"] = k
                    for j, running in list(state["conns"].items()):
                        if j > k:
                            running.interrupt()
                    return
                k += 1

        def size(info):
            try:
                return os.path.getsize(info.path)
            except OSError:
                return 0

        def run(task):
            p, table, rowid_range = task
            if self._cancel_event.is_set():
                return None
            info, _ts, cap = plans[p]
            state = cuts.get((p, table))
            i = slices[(p, table)].index(rowid_range) if state else 0
            if state:
                with cut_lock:
                    if _past_the_cut(state, i):
                        return None
            loader = BaseDataLoader(info.path)
            if not loader.connect():
                return None
            try:
                if state:
                    with cut_lock:
                        if _past_the_cut(state, i):
                            return None
                        state["conns"][i] = loader
                found_here = DatabaseSearchEngine(loader, enable_cache=False).search(
                    search_term=search_term, tables=[table],
                    case_sensitive=case_sensitive, exact_match=exact_match,
                    max_results=cap, timeout_seconds=timeout_seconds,
                    rowid_range=rowid_range, use_regex=use_regex)
                if state:
                    with cut_lock:
                        state["conns"].pop(i, None)
                        if _past_the_cut(state, i):
                            return None      # interrupted: its rows are never kept
                        _answered(state, i, found_here.total_matches, cap)
                return found_here
            except Exception as e:
                self.logger.error(f"Error searching {info.name}/{table}: {e}", exc_info=True)
                return None
            finally:
                if state:
                    with cut_lock:
                        state["conns"].pop(i, None)
                loader.disconnect()

        found = {}
        if tasks:
            # Every table's first slice before any table's second, and within
            # a round the largest files first, so the long scans start at
            # once. A common term fills a table's cap in its first slice and
            # cuts the table before its later slices are taken from the queue.
            def slice_no(tk):
                return slices[(tk[0], tk[1])].index(tk[2])
            order = sorted(tasks, key=lambda tk: (slice_no(tk), -size(plans[tk[0]][0])))
            with ThreadPoolExecutor(max_workers=min(SEARCH_THREADS, len(tasks))) as pool:
                futures = {pool.submit(run, tk): tk for tk in order}
                done = 0
                for future in as_completed(futures):
                    tk = futures[future]
                    done += 1
                    try:
                        found[tk] = future.result()
                    except Exception as e:                  # pragma: no cover
                        self.logger.error(f"Search task failed: {e}")
                    if progress_callback:
                        info = plans[tk[0]][0]
                        progress_callback(
                            f"[{int(done * 100 / len(tasks))}%] Searched {done}/{len(tasks)} "
                            f"tables: {info.display_name or info.name} / {tk[1]}...")
                    if self._cancel_event.is_set():
                        self.logger.info("Search was cancelled.")
                        for f in futures:
                            f.cancel()
                        break

        out = []
        for p, (info, ts, _cap) in enumerate(plans):
            merged = SearchResults(search_term=search_term)
            merged.database_name = info.name
            merged.tables_searched = len(ts)
            for table in ts:
                part = self._join_slices(search_term, table, _cap,
                                         [found.get((p, table, r)) for r in slices[(p, table)]])
                if part is None or not part.total_matches:
                    continue
                merged.tables_with_results += 1
                merged.search_time = max(merged.search_time, part.search_time)
                for result in part.get_results_by_table(table):
                    merged.add_result(result)
                    if merged.total_matches >= max_results:
                        merged.truncated = True
                        break
                if merged.truncated:
                    break
            merged.sort_by_relevance()
            out.append(merged)
        return out

    # The tables SQLite itself keeps behind a virtual table (FTS3/4/5's index
    # pages and settings, R*Tree's nodes): the index's internals, never
    # evidence. A search of them errored or matched index bytes; the virtual
    # table itself (matches_fts) is still searched.
    _SHADOW_SUFFIXES = ("_data", "_idx", "_content", "_docsize", "_config",
                        "_segments", "_segdir", "_stat", "_node", "_rowid", "_parent")

    @classmethod
    def _shadow_tables(cls, path):
        """Names of the shadow tables of every virtual table in one database."""
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True,
                                   timeout=5)
        except sqlite3.Error:
            return set()
        try:
            rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        except sqlite3.Error:
            return set()
        finally:
            conn.close()
        names = {n for n, _sql in rows}
        virtual = [n for n, sql in rows
                   if sql and sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE")]
        return {v + s for v in virtual for s in cls._SHADOW_SUFFIXES if v + s in names}

    def _rowid_spans(self, path, tables):
        """{table: (min rowid, max rowid)} for the tables of one database
        that have a rowid; one indexed read each. A WITHOUT ROWID table, a
        view or an unreadable one is left out and read whole."""
        out = {}
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True,
                                   timeout=5)
        except sqlite3.Error:
            return out
        try:
            for t in tables:
                q = str(t).replace('"', '""')
                try:
                    # Two scalar subqueries, never min() and max() in one
                    # SELECT: SQLite reads a lone min or max from the end of
                    # the rowid tree, but both together scan the whole table
                    # (12.9 s over this case's tables before the search began).
                    out[t] = conn.execute('SELECT (SELECT min(rowid) FROM "%s"), '
                                          '(SELECT max(rowid) FROM "%s")' % (q, q)).fetchone()
                except sqlite3.Error:
                    continue
        finally:
            conn.close()
        return out

    @staticmethod
    def _join_slices(search_term, table, cap, parts):
        """One table's SearchResults from its slices', exactly as one scan of
        it returns them: the rows in rowid order, cut at the table's cap, then
        sorted by relevance. A single part (a table read whole) is returned as
        it is; None when no slice answered."""
        answered = [x for x in parts if x is not None]
        if len(parts) == 1 or not answered:
            return answered[0] if answered else None
        rows = []
        for part in parts:
            if part is None:
                continue
            got = part.get_results_by_table(table)
            got.sort(key=lambda r: (r.record_data or {}).get("_rowid_") or 0)
            rows.extend(got)
        joined = SearchResults(search_term=search_term)
        joined.tables_searched = 1
        joined.search_time = max(x.search_time for x in answered)
        for result in rows[:cap]:
            joined.add_result(result)
        joined.truncated = len(rows) > cap or any(x.truncated for x in answered)
        if joined.total_matches:
            joined.tables_with_results = 1
        joined.sort_by_relevance()
        return joined

    @staticmethod
    def _tables_or_all(db_tables, info):
        """An EMPTY table list is not "every table" - it is nothing.

        `DatabaseSearchEngine.search` reads `tables=None` as everything and
        `tables=[]` as nothing, and the two arrive from the same place: the
        dialog builds `selected[name] = []` and then appends whichever table
        children are checked. A database checked with no child checked would
        search nothing at all and report zero hits, which is indistinguishable
        from a database that simply has none.

        Fall back to the entry's OWN tables, which for an artifact scoped
        inside a shared file (`shellbags_data.db` -> `Shellbags`) is its
        artifact and not the other 123 tables beside it.
        """
        if db_tables:
            return db_tables
        if db_tables is None:
            return None
        own = getattr(info, "tables", None)
        if isinstance(own, dict):
            own = list(own)
        return list(own) if own else None

    @staticmethod
    def _one_entry_per_file(infos, tables):
        """Collapse several logical names that resolve to the same file.

        Six of the configured names - jumplist, eventlog, shellbags,
        userassist, muicache and bam_dam - all resolve to the one physical
        `Log_Claw.db`, because those artifacts live as TABLES inside it. Both
        search paths iterated the logical list, so its 43,802 rows were read
        six times per search and every hit was reported six times.

        The tree keeps showing them separately, which is right: an examiner
        looks for "UserAssist", not for a filename. Only the reading is
        collapsed.

        Returns `(infos, tables, aliases)`; `aliases` maps the surviving name
        to every logical name that resolved to the same file, so a hit can
        still say which artifact it belongs to.
        """
        from pathlib import Path

        import copy

        kept, seen, aliases = [], {}, {}
        merged = dict(tables or {})
        for info in infos:
            try:
                key = str(Path(info.path).resolve()).lower()
            except Exception:
                key = str(getattr(info, "path", info.name)).lower()
            if key not in seen:
                seen[key] = info
                aliases[info.name] = [info.name]
                kept.append(info)
                continue

            first = seen[key]
            aliases[first.name].append(info.name)
            if tables:
                # A table selected under ANY of the names has to survive, and a
                # name with no restriction means "every table" - which wins.
                if first.name not in merged or info.name not in merged:
                    merged.pop(first.name, None)
                else:
                    merged[first.name] = sorted(
                        set(merged[first.name]) | set(merged[info.name]))
                merged.pop(info.name, None)

        # Report a collapsed entry under its FILE name. Which logical name
        # happens to survive is an accident of iteration order - `Log_Claw.db`
        # came out as "jumplist_data.db" - and an event log hit labelled
        # "jumplist_data.db" tells the examiner something untrue about where
        # the evidence is.
        renamed = []
        for info in kept:
            names = aliases.get(info.name, [info.name])
            file_name = Path(info.path).name
            if len(names) > 1 and info.name != file_name:
                shown = copy.copy(info)
                try:
                    shown.name = file_name
                except Exception:
                    shown = info
                if tables and info.name in merged:
                    merged[file_name] = merged.pop(info.name)
                aliases[file_name] = names
                aliases.pop(info.name, None)
                renamed.append(shown)
            else:
                renamed.append(info)

        return renamed, (merged if tables else tables), aliases

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
        end_time: Optional[datetime.datetime],
        use_regex: bool = False
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
                    timeout_seconds=timeout_seconds,
                    use_regex=use_regex
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
                    # The term is matched in SQL too, with the plain search's
                    # own rule (match_where): only the first max_results * 10
                    # rows in the period were read and then matched in
                    # Python, so a match past them was never found, and Exact
                    # Match and Regex were ignored (a substring test).
                    match_sql, match_params = table_loader.match_where(
                        table_loader.get_columns(table_name), search_term,
                        case_sensitive, exact_match, use_regex)
                    query = query.replace(
                        "            LIMIT ",
                        "            AND (%s)\n            LIMIT " % match_sql, 1)

                    # Execute query with remaining timeout
                    remaining_timeout = timeout_seconds - elapsed
                    results = table_loader.execute_query(
                        query,
                        params=match_params,
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
                        case_sensitive=case_sensitive,
                        exact_match=exact_match,
                        use_regex=use_regex
                    )

                    if not filtered_results:
                        # Timestamps the SQL range cannot compare (another
                        # format in the same column): the term's matches,
                        # each period checked by the parser below.
                        fallback_query = (f"SELECT rowid as _rowid_, * FROM \"{table_name}\" "
                                          f"WHERE {match_sql} LIMIT {max_results * 10}")
                        fallback_rows = table_loader.execute_query(
                            fallback_query,
                            params=match_params,
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
                            case_sensitive=case_sensitive,
                            exact_match=exact_match,
                            use_regex=use_regex
                        )

                    all_table_results.extend(filtered_results)
                    
                    # Log performance metrics 
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
            
            # Log overall performance metrics 
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
            SELECT rowid as _rowid_, * FROM "{table_name}"
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
        case_sensitive: bool = False,
        exact_match: bool = False,
        use_regex: bool = False
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
        
        matches = value_matcher(search_term, case_sensitive, exact_match, use_regex) \
            if search_term else None
        for row in results:
            # First check if row matches search term (if provided): the rule
            # the SQL used, so a column is named matched only when it is.
            if search_term:
                matched_columns = [c for c, v in row.items()
                                   if c != "_rowid_" and matches(v)]
                row_matches_search = bool(matched_columns)
                
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
