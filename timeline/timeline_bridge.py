"""
Timeline Bridge — QWebChannel bridge for React ↔ Python communication.

This module provides the TimelineBridge class which exposes forensic database
queries to the React frontend via QWebChannel slots. It handles:
- Universal timestamp parsing (any format → ISO 8601)
- Corruptdata filtering (future/ancient dates discarded)
- All 10 database query methods
- Chunked data loading for large datasets

Author: Crow Eye Development Team
"""

import json
import time
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor


from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QThread

from timeline.utils.value_parser import parsable_num_adapter
from utils.time_utils import get_current_utc, format_forensic_timestamp

logger = logging.getLogger(__name__)


class UniversalTimestampParser:
    """
    Universal timestamp parser that handles any format and converts to ISO 8601.
    
    Parse chain: ISO 8601 → Windows FILETIME → Unix epoch (s) → 
                 Unix epoch (ms) → custom date strings → skip
    
    Dates in the future (> current year + 2) or too old (< year 2000)
    are silently discarded as corrupted data.
    """
    
    # Windows FILETIME epoch: January 1, 1601
    FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
    FILETIME_TICKS_PER_SECOND = 10_000_000  # 100-nanosecond intervals
    
    # Mac/Cocoa Absolute Time epoch: January 1, 2001
    COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
    
    # OLE Automation Date epoch: December 30, 1899
    OLE_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
    
    # Validity bounds
    MIN_VALID_YEAR = 2000
    MAX_VALID_YEAR = datetime.now().year + 2
    
    # ISO format patterns to try
    ISO_FORMATS = [
        "%Y-%m-%dT%H:%M:%S.%f%z",      # 2025-09-08T12:23:45.312258+00:00
        "%Y-%m-%dT%H:%M:%S%z",          # 2025-09-08T12:23:45+00:00
        "%Y-%m-%dT%H:%M:%S.%f",         # 2026-02-16T01:48:59.084999
        "%Y-%m-%dT%H:%M:%S",            # 2026-02-05T16:56:00
        "%Y-%m-%d %H:%M:%S.%f",         # 2025-09-08 12:23:45.312258
        "%Y-%m-%d %H:%M:%S",            # 2026-03-31 12:00:00
        "%Y-%m-%d",                      # 2026-03-31
        "%m/%d/%Y %H:%M:%S",            # 03/31/2026 12:00:00
        "%m/%d/%Y",                      # 03/31/2026
        "%d-%b-%Y %H:%M:%S",            # 31-Mar-2026 12:00:00
        "%d-%b-%Y",                      # 31-Mar-2026
    ]
    
    @classmethod
    def parse(cls, value: Any) -> Optional[str]:
        """
        Parse any timestamp value to ISO 8601 string.
        
        Returns None for unparseable or corrupted (out-of-range) values.
        """
        if value is None or value == '' or value == 'N/A':
            return None
        
        dt = None
        
        # If already a datetime
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            dt = cls._parse_numeric(value)
        elif isinstance(value, str):
            value = value.strip()
            if not value or value == 'N/A':
                return None
            dt = cls._parse_string(value)
        
        if dt is None:
            return None
        
        # Validate bounds — silently discard corrupted data
        try:
            if dt.year < cls.MIN_VALID_YEAR or dt.year > cls.MAX_VALID_YEAR:
                return None
        except (AttributeError, ValueError):
            return None
        
        if dt is None:
            return None
            
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    
    @classmethod
    def _parse_string(cls, value: str) -> Optional[datetime]:
        """Try all string parsing strategies."""
        # Try ISO formats
        for fmt in cls.ISO_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except (ValueError, OverflowError):
                continue
        
        # Try Python's fromisoformat (handles many ISO variants)
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, OverflowError):
            pass
        
        # Try as numeric string
        try:
            num = float(value)
            return cls._parse_numeric(num)
        except (ValueError, OverflowError):
            pass
        
        return None
    
    @classmethod
    def _parse_numeric(cls, value: float) -> Optional[datetime]:
        """Parse numeric timestamps with forensic heuristics."""
        try:
            # 1. Windows FILETIME or high-precision Chromium (17+ digits)
            # e.g. 132600000000000000 (100ns since 1601) or 1326000000000000 (us since 1601)
            if value > 1_000_000_000_000_000:
                if value > 100_000_000_000_000_000: # 100ns
                    seconds = value / 10_000_000
                else: # us (Chromium/Webkit)
                    seconds = value / 1_000_000
                return cls.FILETIME_EPOCH + __import__('datetime').timedelta(seconds=seconds)
            
            # 2. Unix epoch in milliseconds (13 digits)
            if value > 10_000_000_000_00:
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            
            # 3. Unix epoch in seconds (10 digits)
            if 946684800 < value < 2524608000: # 2000 to 2050
                return datetime.fromtimestamp(value, tz=timezone.utc)
            
            # 4. Mac/Cocoa Absolute Time (seconds since 2001)
            # e.g. 631152000 is ~20 years after 2001 (approx 2021)
            #
            # The floor is one day, not zero. A bare number smaller than that
            # is a version fragment, a count or a fraction - never a moment -
            # and reading it as "seconds since 2001" made every one of them
            # land on 2001-01-01. AmCache stores a version string in
            # `link_date` on some rows, one of which is "0.5", and that single
            # value became the left edge of the whole timeline: the case span
            # read 2001 to 2026 on a machine whose oldest real evidence was
            # 2010.
            if 86_400 < value < 1_500_000_000:
                cand = cls.COCOA_EPOCH + __import__('datetime').timedelta(seconds=value)
                if cls.MIN_VALID_YEAR <= cand.year <= cls.MAX_VALID_YEAR:
                    return cand
            
            # 5. OLE Automation Dates (Float days since 1899)
            # 2024 is roughly 45300
            if 36526 < value < 60000: 
                # If it has a decimal, it's likely an OLE date
                if isinstance(value, float) and not value.is_integer():
                    seconds = (value - 25569) * 86400 # 25569 is Unix epoch in OA
                    return datetime.fromtimestamp(seconds, tz=timezone.utc)

        except (OSError, OverflowError, ValueError):
            pass
        
        return None


class UniversalDurationParser:
    """
    Parses human-readable forensic duration strings into numeric seconds.
    Supports: "1.01 hrs", "1.60 min", "4.57 s", "1h 0m 44s", "0.93 ms"
    """
    
    @classmethod
    def parse_to_seconds(cls, value: Any) -> float:
        """Delegates to high-fidelity ValueParser."""
        from timeline.utils.value_parser import ValueParser
        return ValueParser.parse_to_num(value)


class TimelineBridge(QObject):
    """
    QWebChannel bridge exposing forensic data to React frontend.
    
    All methods return JSON strings. The React side calls these via
    window.bridge.methodName(args) through QWebChannel.
    """
    
    # Signal emitted when data is ready (for async loading)
    dataReady = pyqtSignal(str, str)  # (method_name, json_data)
    show_event_detail = pyqtSignal(str) # (event_json)

    def __init__(self, case_directory: str, parent=None):
        """
        Initialize the bridge with the path to the case's Target_Artifacts directory.
        
        Args:
            case_directory: Path to Target_Artifacts folder containing all .db files
        """
        super().__init__(parent)
        self.case_dir = case_directory
        self.parser = UniversalTimestampParser()
        self.duration_parser = UniversalDurationParser()
        self._db_cache = {}  # Cache open connections
        logger.info(f"TimelineBridge initialized with case dir: {case_directory}")
    
    def _get_db_path(self, db_name: str) -> Optional[str]:
        """Get full path to a database file, or None if it doesn't exist."""
        path = os.path.join(self.case_dir, db_name)
        if os.path.exists(path):
            return path
        return None
    
    def _table_exists(self, db_name: str, table_name: str) -> bool:
        """Safe helper to verify table existence without external data_manager."""
        try:
            res = self._query_db(db_name, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            return len(res) > 0
        except Exception:
            return False
    
    def _query_db(self, db_name: str, sql: str, params: tuple = ()) -> List[Dict]:
        """
        Execute a query and return results as list of dicts.
        
        Args:
            db_name: Database filename (e.g., 'srum_data.db')
            sql: SQL query string
            params: Query parameters
            
        Returns:
            List of row dictionaries
        """
        db_path = self._get_db_path(db_name)
        if not db_path:
            logger.warning(f"Database not found: {db_name}")
            return []
        
        retries = 3
        delay = 0.1
        
        for attempt in range(retries):
            try:
                conn = sqlite3.connect(db_path)
                # Register the dynamic value parser as a custom SQLite function
                conn.create_function("PARSABLE_NUM", 1, parsable_num_adapter)
                # And the timestamp normaliser. SQLite's own `datetime()`
                # returns NULL for anything it does not recognise - and
                # returning NULL is not an error, so a WHERE clause built on it
                # simply matches nothing. AmCache stores `02/14/2026 00:00:00`
                # and raw Unix epochs, so every AmCache query on this timeline
                # had been returning zero rows for as long as they existed.
                conn.create_function("NORM_TS", 1, self._norm_ts)


                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = [dict(row) for row in cursor.fetchall()]
                conn.close()
                return rows
            except sqlite3.OperationalError as e:
                # Handle busy/locked errors with backoff
                if ("locked" in str(e).lower() or "busy" in str(e).lower()) and attempt < retries - 1:
                    logger.warning(f"Database {db_name} is locked. Retrying in {delay}s (Attempt {attempt+1}/{retries})")
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.error(f"Query error on {db_name}: {e}")
                return []
            except Exception as e:
                logger.error(f"Critical query failure on {db_name}: {e}")
                return []
        return []
    
    def _parse_timestamps_in_rows(self, rows: List[Dict], timestamp_cols: List[str]) -> List[Dict]:
        """Parse and validate timestamps in specified columns, discard rows with no valid timestamp."""
        result = []
        for row in rows:
            has_valid_ts = False
            for col in timestamp_cols:
                if col in row and row[col] is not None:
                    parsed = self.parser.parse(row[col])
                    row[col] = parsed
                    if parsed is not None:
                        has_valid_ts = True
            if has_valid_ts:
                result.append(row)
        return result

    # FIX: Bug 6 - Python Time-Slicing Parameter Injection Vulnerability
    # Uses positional parameter replacement instead of value matching to prevent SQL injection
    # Adds input validation and bounds checking for secure time-sliced queries
    def _substitute_slice_params(self, params: tuple, slice_start: str, slice_end: str, 
                                start_idx: int, end_idx: int) -> tuple:
        """
        Safely substitute slice parameters using positional indices.
        
        CRITICAL: This function prevents SQL injection vulnerabilities by using positional
        parameter replacement instead of value matching. Value matching is fragile and can
        cause incorrect data fetching when start/end timestamps appear multiple times in
        the params tuple or are in unexpected order.
        
        WARNING: Always use this function for parameter substitution in time-sliced queries.
        DO NOT use value matching like: tuple(ss if p == params[0] else se if p == params[1] else p for p in params)
        
        Args:
            params: Original parameter tuple from the SQL query
            slice_start: New start timestamp for this time slice (ISO 8601 format)
            slice_end: New end timestamp for this time slice (ISO 8601 format)
            start_idx: Index of start parameter in params tuple (typically 0)
            end_idx: Index of end parameter in params tuple (typically 1)
            
        Returns:
            New parameter tuple with slice bounds substituted at specified indices
            
        Raises:
            ValueError: If start_idx or end_idx are out of bounds for params length
        
        Example:
            >>> params = ('2024-01-01T00:00:00.000Z', '2024-01-07T23:59:59.999Z', 'user123')
            >>> slice_start = '2024-01-01T00:00:00.000Z'
            >>> slice_end = '2024-01-02T00:00:00.000Z'
            >>> _substitute_slice_params(params, slice_start, slice_end, 0, 1)
            ('2024-01-01T00:00:00.000Z', '2024-01-02T00:00:00.000Z', 'user123')
        """
        if start_idx < 0 or start_idx >= len(params):
            raise ValueError(f"start_idx {start_idx} out of bounds for params length {len(params)}")
        if end_idx < 0 or end_idx >= len(params):
            raise ValueError(f"end_idx {end_idx} out of bounds for params length {len(params)}")
            
        # Convert to list for modification
        params_list = list(params)
        params_list[start_idx] = slice_start
        params_list[end_idx] = slice_end
        
        return tuple(params_list)
    
    def _validate_iso8601_timestamp(self, timestamp: str) -> bool:
        """
        Validate that a timestamp is valid ISO 8601 format.
        
        Used for input validation in time-sliced queries to prevent malformed
        timestamps from causing query errors or security issues.
        
        Accepts formats:
        - 2024-01-01T12:00:00.000Z (with milliseconds and Z suffix)
        - 2024-01-01T12:00:00+00:00 (with timezone offset)
        - 2024-01-01T12:00:00 (without timezone)
        
        Args:
            timestamp: Timestamp string to validate
            
        Returns:
            True if valid ISO 8601 format, False otherwise
        
        Example:
            >>> _validate_iso8601_timestamp('2024-01-01T12:00:00.000Z')
            True
            >>> _validate_iso8601_timestamp('2024-01-01 12:00:00')
            False
            >>> _validate_iso8601_timestamp('invalid')
            False
        """
        try:
            # Try parsing with fromisoformat
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return True
        except (ValueError, AttributeError):
            return False
    
    def _query_time_sliced(self, db_name: str, sql: str, params: tuple, 
                         ts_col: str, limit_per_slice: int = 1000, 
                         slices: int = 10, start_idx: int = 0, end_idx: int = 1) -> List[Dict]:
        """
        Fetch data in multiple time-slices to ensure even coverage across the time range.
        
        WARNING: Critical time-slicing parameter replacement - Uses positional indices, NOT value matching
        DO NOT replace parameters by value matching (e.g., ss if p == params[0])
        Value matching is fragile and causes incorrect data fetching when:
        - Start/end timestamps appear multiple times in params tuple
        - Parameters are in unexpected order
        - Similar timestamp values exist in params
        Use ONLY positional replacement via _substitute_slice_params(params, ss, se, start_idx, end_idx)
        Incorrect parameter replacement can cause:
        - SQL injection vulnerabilities if user input reaches params
        - Data integrity issues with wrong time slices
        - Unpredictable query results
        
        Uses positional parameter replacement to safely substitute slice bounds without
        value matching, preventing SQL injection and incorrect parameter substitution.
        
        Args:
            db_name: Database filename
            sql: SQL query with parameterized placeholders
            params: Query parameters (start and end timestamps expected at start_idx and end_idx)
            ts_col: Timestamp column name (for reference, not used in current implementation)
            limit_per_slice: Maximum rows per slice
            slices: Number of time slices to divide the range into
            start_idx: Index of start timestamp in params tuple (default: 0)
            end_idx: Index of end timestamp in params tuple (default: 1)
            
        Returns:
            List of row dictionaries with duplicates removed
        """
        results = []
        try:
            # Input validation
            if not params or len(params) < 2:
                logger.warning("_query_time_sliced: Insufficient parameters, falling back to simple query")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            # Validate slice count is reasonable (1-100)
            if slices < 1 or slices > 100:
                logger.warning(f"_query_time_sliced: Invalid slice count {slices}, clamping to [1, 100]")
                slices = max(1, min(100, slices))
            
            # Validate indices
            if start_idx < 0 or start_idx >= len(params):
                logger.error(f"_query_time_sliced: Invalid start_idx {start_idx} for params length {len(params)}")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            if end_idx < 0 or end_idx >= len(params):
                logger.error(f"_query_time_sliced: Invalid end_idx {end_idx} for params length {len(params)}")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            # Log original params for debugging
            logger.debug(f"_query_time_sliced: Original params: {params}")
            
            # Parse start/end from specified indices
            start_param = params[start_idx]
            end_param = params[end_idx]
            
            # Validate timestamps are valid ISO 8601
            if not self._validate_iso8601_timestamp(str(start_param)):
                logger.error(f"_query_time_sliced: Invalid start timestamp format: {start_param}")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            if not self._validate_iso8601_timestamp(str(end_param)):
                logger.error(f"_query_time_sliced: Invalid end timestamp format: {end_param}")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            s_iso = self.parser.parse(start_param)
            e_iso = self.parser.parse(end_param)
            
            if not s_iso or not e_iso:
                logger.warning("_query_time_sliced: Failed to parse timestamps, falling back to simple query")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            s_dt = datetime.fromisoformat(s_iso.replace('Z', '+00:00'))
            e_dt = datetime.fromisoformat(e_iso.replace('Z', '+00:00'))
            
            # Validate start < end
            if s_dt >= e_dt:
                logger.error(f"_query_time_sliced: Start timestamp {s_dt} >= end timestamp {e_dt}")
                return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
            
            # Calculate time delta per slice with bounds checking
            delta = (e_dt - s_dt) / slices
            
            sql_upper = sql.upper()
            order_by_idx = sql_upper.find("ORDER BY")
            
            base_query = sql
            order_clause = ""
            if order_by_idx != -1:
                base_query = sql[:order_by_idx]
                order_clause = sql[order_by_idx:]
            
            slice_sql = f"{base_query} {order_clause} LIMIT {limit_per_slice}"

            for i in range(slices):
                slice_start = s_dt + (delta * i)
                slice_end = s_dt + (delta * (i + 1))
                
                # Ensure slice bounds are within original range
                if slice_start < s_dt:
                    slice_start = s_dt
                if slice_end > e_dt:
                    slice_end = e_dt
                
                ss = slice_start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                se = slice_end.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                
                # WARNING: Critical parameter substitution - Use positional replacement ONLY
                # DO NOT use value matching like: tuple(ss if p == params[0] else se if p == params[1] else p for p in params)
                # Value matching fails when start/end appear multiple times or in unexpected order
                # ALWAYS use _substitute_slice_params for safe positional replacement
                # Use positional parameter replacement instead of value matching
                try:
                    slice_params = self._substitute_slice_params(params, ss, se, start_idx, end_idx)
                    logger.debug(f"_query_time_sliced: Slice {i+1}/{slices} params: {slice_params}")
                except ValueError as e:
                    logger.error(f"_query_time_sliced: Parameter substitution error: {e}")
                    continue
                
                results.extend(self._query_db(db_name, slice_sql, slice_params))
            
            # Deduplicate results
            unique = {}
            for r in results:
                rid = r.get('id') or r.get('rowid') or hash(frozenset(r.items()))
                unique[rid] = r
            
            logger.debug(f"_query_time_sliced: Returned {len(unique)} unique results from {len(results)} total")
            return list(unique.values())
            
        except Exception as e:
            logger.error(f"Time-sliced query error: {e}", exc_info=True)
            return self._query_db(db_name, sql + f" LIMIT {limit_per_slice * slices}", params)
    
    # ──────────────────────────────────────────────
    # SLOT: Get Time Bounds across all databases
    # ──────────────────────────────────────────────
    
    # Which columns define the case SPAN. Deliberately a short list, and
    # deliberately not "everything the map plots":
    #
    #   * SPEED. Running MIN/MAX over all 71 record-time columns takes 10.7
    #     seconds on this case, most of it the MFT - 205,052 records by four
    #     columns, plus 348,090 $FN rows by four more. The span does not need
    #     them; `mft_usn_correlated.usn_timestamp` already covers file activity.
    #   * NOISE. An MFT full of 1601 sentinels and randomised PE link dates
    #     would stretch the window across centuries with nothing in most of it.
    #
    # Every entry here must still be a column `artifact_map` plots, which
    # `timeline/tests` asserts - that is what catches the next rename. The
    # entry that made this list worth writing down was AmCache's raw
    # `link_date`, which holds version strings ("6.4.7.0", "0.5"): the span
    # read 2000 to 2028 on a machine whose real evidence runs 2010 to 2026.
    _BOUNDS_SOURCES = [
        ("Log_Claw.db", "SystemLogs", "EventTimestampUTC"),
        ("Log_Claw.db", "SecurityLogs", "EventTimestampUTC"),
        ("Log_Claw.db", "ApplicationLogs", "EventTimestampUTC"),
        ("srum_data.db", "srum_application_usage", "timestamp"),
        ("srum_data.db", "srum_network_data_usage", "timestamp"),
        ("mft_usn_correlated_analysis.db", "mft_usn_correlated",
         "usn_timestamp"),
        ("prefetch_data.db", "prefetch_data", "last_executed"),
        ("shimcache.db", "shimcache_entries", "last_modified"),
        ("recyclebin_analysis.db", "recycle_bin_entries", "deletion_time"),
        ("LnkDB.db", "LNK_Files", "Time_Access"),
        ("LnkDB.db", "Automatic_JumpLists", "Time_Access"),
        ("LnkDB.db", "Custom_JumpLists", "Time_Access"),
        # The registry was not represented here at all, and it is the largest
        # source of events in most cases. A case parsed with "Parse Registry"
        # alone therefore had no time bounds, and the timeline opened on "No
        # forensic data available" while the bridge held 4,600 plottable rows.
        ("registry_data.db", "ScheduledTasks", "task_registered"),
        ("registry_data.db", "ScheduledTasks", "last_run"),
        ("registry_data.db", "registry_value_changes", "changed_at"),
        ("registry_data.db", "UserAssist", "last_execution"),
        ("registry_data.db", "BAM", "last_execution"),
        ("registry_data.db", "InstalledSoftware", "install_date"),
        ("registry_data.db", "Network_list", "connection_date"),
        ("registry_data.db", "USBStorageDevices", "first_connected"),
        ("registry_data.db", "USBStorageDevices", "last_connected"),
        ("registry_data.db", "Shellbags", "created_date"),
        ("registry_data.db", "Shellbags", "modified_date"),
        ("registry_data.db", "Shellbags", "accessed_date"),
        ("registry_data.db", "ShutdownInfo", "shutdown_time"),
        ("amcache.db", "InventoryApplicationFile", "link_date_utc"),
        ("amcache.db", "InventoryApplication", "install_date_utc"),
    ]

    @pyqtSlot(result=str)
    def getTimeBounds(self) -> str:
        """The earliest and latest EXACT times anywhere in the case."""
        all_timestamps = []

        for db_name, table, column in self._BOUNDS_SOURCES:
            # Order on the normalised value, not the stored string. A
            # `MM/DD/YYYY` column sorts by month, and a column holding a
            # version string on some rows sorts by whatever that is.
            expr = ('datetime(NORM_TS("%s"))' % column
                    if self._needs_normalising(db_name, table, column)
                    else 'datetime("%s")' % column)
            sql = ('SELECT MIN({e}) as mn, MAX({e}) as mx FROM "{t}" '
                   'WHERE {e} IS NOT NULL'.format(e=expr, t=table))
            for row in self._query_db(db_name, sql):
                for key in ("mn", "mx"):
                    parsed = self.parser.parse(row.get(key))
                    if parsed:
                        all_timestamps.append(parsed)

        # Extend bounds with any imported evidence feathers so the case time range
        # covers external data the investigator added (see getImportedData).
        for db_path, table, ts_col, _id_col in self._imported_feather_tables():
            rel = os.path.relpath(db_path, self.case_dir)
            sql = f'SELECT MIN("{ts_col}") as mn, MAX("{ts_col}") as mx FROM "{table}" WHERE "{ts_col}" IS NOT NULL'
            for row in self._query_db(rel, sql):
                for key in ['mn', 'mx']:
                    parsed = self.parser.parse(row.get(key))
                    if parsed:
                        all_timestamps.append(parsed)

        # Nothing in a case happened after the case was collected. A PE link
        # date is routinely randomised into the future - AmCache carries one
        # reading 2027-06-19 here - and one such value stretched the visible
        # window nine months past the end of the evidence, so the timeline
        # opened on a stretch of empty screen.
        horizon = format_forensic_timestamp(get_current_utc())
        real = [t for t in all_timestamps if t <= horizon]
        if real:
            all_timestamps = real

        if not all_timestamps:
            return json.dumps({"start": None, "end": None})

        all_timestamps.sort()
        return json.dumps({
            "start": all_timestamps[0],
            "end": all_timestamps[-1]
        })

    # ──────────────────────────────────────────────
    # Imported evidence (external SQLite / converted CSV·JSON feathers)
    # ──────────────────────────────────────────────

    _IMPORTED_SUBDIR = "Imported_Evidence"
    _TS_NAME_RE = re.compile(
        r"(time|date|timestamp|created|modified|accessed|executed|deleted|"
        r"installed|connected|logon|logoff|start|end|when|_at$|_on$)",
        re.IGNORECASE,
    )
    _ID_NAME_RE = re.compile(r"(name|path|file|host|user|sid|hash|process|image|url|ip)", re.IGNORECASE)

    def _imported_feather_tables(self):
        """Discover imported evidence tables to plot on the timeline.

        Returns a list of ``(db_path, table, timestamp_col, identity_col)``. Works for
        both converted CSV/JSON feathers (which stamp ``feather_metadata`` with the
        primary timestamp) and directly-imported SQLite databases (columns inferred by
        name, validated against real values). Tables without any recognisable timestamp
        are skipped — they can't be placed on a temporal grid.
        """
        import glob
        out = []
        folder = os.path.join(self.case_dir, self._IMPORTED_SUBDIR)
        if not os.path.isdir(folder):
            return out
        for db_path in sorted(glob.glob(os.path.join(folder, "*.db"))):
            rel = os.path.relpath(db_path, self.case_dir)
            # feather_metadata (converted files) declares the primary timestamp directly.
            meta = {}
            try:
                for row in self._query_db(rel, "SELECT key, value FROM feather_metadata WHERE key LIKE 'table:%'"):
                    try:
                        blob = json.loads(row.get("value") or "{}")
                        meta[blob.get("name")] = blob
                    except (json.JSONDecodeError, TypeError):
                        continue
            except Exception:
                meta = {}

            tables = [
                r["name"] for r in self._query_db(
                    rel,
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'feather_%'",
                )
            ]
            for table in tables:
                cols = [r["name"] for r in self._query_db(rel, f'PRAGMA table_info("{table}")')]
                if not cols:
                    continue
                ts_col = None
                id_col = None
                blob = meta.get(table)
                if blob:
                    ts_col = blob.get("primary_timestamp_column")
                    id_cols = blob.get("identity_columns") or []
                    id_col = id_cols[0] if id_cols else None
                if not ts_col:
                    ts_col = self._infer_timestamp_column(rel, table, cols)
                if not id_col:
                    id_col = next((c for c in cols if self._ID_NAME_RE.search(c)), None) or (cols[0] if cols else None)
                if ts_col:
                    out.append((db_path, table, ts_col, id_col))
        return out

    def _infer_timestamp_column(self, rel_db, table, cols):
        """Pick the timestamp column of a metadata-less table by name + value sampling."""
        candidates = [c for c in cols if self._TS_NAME_RE.search(c)] + list(cols)
        for c in candidates:
            try:
                sample = self._query_db(
                    rel_db, f'SELECT "{c}" AS v FROM "{table}" WHERE "{c}" IS NOT NULL LIMIT 20')
            except Exception:
                continue
            vals = [r.get("v") for r in sample if r.get("v") not in (None, "")]
            if not vals:
                continue
            hits = sum(1 for v in vals if self.parser.parse(v))
            if hits and hits >= max(1, int(0.6 * len(vals))):
                return c
        return None

    @pyqtSlot(str, str, result=str)
    def getImportedData(self, start: str, end: str) -> str:
        """Get imported external-evidence events for the 'imported' artifact type.

        Each row is emitted with a normalised ``timestamp`` (so the timeline's generic
        artifact plotter places it) and a ``display_name`` (so identity-based correlation
        links it to native artifacts). Capped per table to keep the payload bounded.
        """
        MAX_PER_TABLE = 5000
        events = []
        for db_path, table, ts_col, id_col in self._imported_feather_tables():
            rel = os.path.relpath(db_path, self.case_dir)
            source_db = os.path.splitext(os.path.basename(db_path))[0]
            sql = (
                f'SELECT * FROM "{table}" '
                f'WHERE datetime("{ts_col}") BETWEEN datetime(?) AND datetime(?) '
                f'ORDER BY "{ts_col}" LIMIT {MAX_PER_TABLE}'
            )
            rows = self._query_db(rel, sql, (start, end))
            for row in rows:
                parsed = self.parser.parse(row.get(ts_col))
                if not parsed:
                    continue
                name = row.get(id_col) if id_col else None
                row["timestamp"] = parsed
                row["display_name"] = str(name) if name not in (None, "") else f"{source_db}:{table}"
                row["artifact_type"] = "imported"
                row["source_db"] = source_db
                row["source_table"] = table
                events.append(row)
        return json.dumps(events)

    # ──────────────────────────────────────────────
    # SLOT: Lane 1 — Sessions / Power / Login
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getSessionData(self, start: str, end: str) -> str:
        """Get power on/off, sleep, login/logout events for session band lane."""
        events = []
        
        # Fetch ALL power events to correctly build bands across time windows
        power_sql = """
            SELECT EventID, EventTimestampUTC, Source, ComputerName, 
                   EventType, EventDescription
            FROM SystemLogs
            WHERE EventID IN (12, 13, 42, 107, 1, 27, 28, 6005, 6006, 6008, 6009, 1074, 109, 41)
            ORDER BY EventTimestampUTC
        """
        power_rows = self._query_db("Log_Claw.db", power_sql)
        
        EVENT_TYPE_MAP = {
            12: 'power_on', 6005: 'power_on', 6009: 'power_on',
            13: 'power_off', 6006: 'power_off', 1074: 'power_off',
            109: 'power_off', 41: 'unexpected_shutdown', 6008: 'unexpected_shutdown',
            42: 'sleep', 27: 'hibernate',
            1: 'wake', 107: 'wake', 28: 'wake',
            1074: 'shutdown',
        }
        
        for row in power_rows:
            parsed_ts = self.parser.parse(row.get('EventTimestampUTC'))
            if parsed_ts:
                events.append({
                    'timestamp': parsed_ts,
                    'type': EVENT_TYPE_MAP.get(row['EventID'], 'unknown'),
                    'source': 'power',
                    'event_id': row['EventID'],
                    'description': row.get('EventDescription', ''),
                    'computer': row.get('ComputerName', ''),
                })
        
        # Fetch ALL Login/Logout events
        login_sql = """
            SELECT EventID, EventTimestampUTC, User, ComputerName,
                   Keywords, TaskCategory, EventDescription
            FROM SecurityLogs
            WHERE EventID IN (4624, 4634, 4800, 4801)
            ORDER BY EventTimestampUTC
        """
        login_rows = self._query_db("Log_Claw.db", login_sql)
        
        LOGIN_TYPE_MAP = {
            4624: 'login', 4634: 'logout',
            4800: 'lock', 4801: 'unlock',
        }
        
        for row in login_rows:
            parsed_ts = self.parser.parse(row.get('EventTimestampUTC'))
            if parsed_ts:
                # Extract LogonType from Keywords if EventID is 4624 (Logon)
                logon_type = None
                if row['EventID'] == 4624:
                    keywords = row.get('Keywords', '')
                    # Typically LogonType is the 9th comma-separated field in the Keywords string for Log_Claw.db
                    parts = keywords.split(',')
                    if len(parts) >= 9:
                        logon_type = parts[8].strip()
                
                events.append({
                    'timestamp': parsed_ts,
                    'type': LOGIN_TYPE_MAP.get(row['EventID'], 'unknown'),
                    'source': 'security',
                    'event_id': row['EventID'],
                    'user': row.get('User', ''),
                    'logon_type': logon_type,
                    'description': row.get('EventDescription', ''),
                    'computer': row.get('ComputerName', ''),
                })
        
        # Sort all events by timestamp
        events.sort(key=lambda e: e['timestamp'])
        
        # Build session bands (pair on↔off, login↔logout, etc.)
        all_bands = self._build_session_bands(events)
        
        # Now filter events and bands to only those intersecting [start, end]
        start_dt = self.parser.parse(start)
        end_dt = self.parser.parse(end)
        
        filtered_events = []
        if start_dt and end_dt:
            for e in events:
                e_dt = self.parser.parse(e['timestamp'])
                if e_dt and start_dt <= e_dt <= end_dt:
                    filtered_events.append(e)
        else:
            filtered_events = events
            
        filtered_bands = []
        if start_dt and end_dt:
            for b in all_bands:
                b_start = self.parser.parse(b['start'])
                b_end = self.parser.parse(b['end']) if b.get('end') else end_dt
                
                # Check intersection
                if b_start and b_end:
                    intersect_start = max(b_start, start_dt)
                    intersect_end = min(b_end, end_dt)
                    if intersect_start <= intersect_end:
                        filtered_bands.append(b)
        else:
            filtered_bands = all_bands
            
        return json.dumps({'events': filtered_events, 'bands': filtered_bands})
    
    def _build_session_bands(self, events: List[Dict]) -> List[Dict]:
        """
        Build paired session bands from sequential events.
        
        Processes power, login, lock, and sleep events to create time-span bands
        representing system states. Pairs opening events (power_on, login, lock, sleep)
        with their corresponding closing events (power_off, logout, unlock, wake).
        
        Handles edge cases:
        - Unexpected shutdowns (marked as 'is_dirty')
        - Unclosed sessions (end=None, marked as 'ongoing')
        - Multiple overlapping session types (power, login, lock, sleep tracked separately)
        
        Args:
            events: List of event dictionaries sorted by timestamp, each containing:
                - timestamp: ISO 8601 timestamp string
                - type: Event type (power_on, power_off, login, logout, etc.)
                - source: Event source ('power' or 'security')
                - Other event-specific fields
        
        Returns:
            List of band dictionaries, each containing:
                - start: ISO 8601 timestamp of opening event
                - end: ISO 8601 timestamp of closing event (or None if ongoing)
                - type: Band type ('power', 'login', 'lock', 'sleep')
                - start_event: Opening event type
                - end_event: Closing event type (or 'ongoing')
                - is_dirty: True if ended with unexpected_shutdown
        
        Example:
            events = [
                {'timestamp': '2024-01-01T08:00:00.000Z', 'type': 'power_on'},
                {'timestamp': '2024-01-01T08:05:00.000Z', 'type': 'login'},
                {'timestamp': '2024-01-01T17:00:00.000Z', 'type': 'logout'},
                {'timestamp': '2024-01-01T17:05:00.000Z', 'type': 'power_off'}
            ]
            
            Returns:
            [
                {
                    'start': '2024-01-01T08:00:00.000Z',
                    'end': '2024-01-01T17:05:00.000Z',
                    'type': 'power',
                    'start_event': 'power_on',
                    'end_event': 'power_off',
                    'is_dirty': False
                },
                {
                    'start': '2024-01-01T08:05:00.000Z',
                    'end': '2024-01-01T17:00:00.000Z',
                    'type': 'login',
                    'start_event': 'login',
                    'end_event': 'logout',
                    'is_dirty': False
                }
            ]
        """
        bands = []
        
        # Track open sessions per type
        open_sessions = {
            'power': None,      # power_on waiting for power_off
            'login': None,      # login waiting for logout
            'lock': None,       # lock waiting for unlock
            'sleep': None,      # sleep waiting for wake
        }
        
        OPENERS = {'power_on': 'power', 'login': 'login', 'lock': 'lock', 'sleep': 'sleep', 'hibernate': 'sleep'}
        CLOSERS = {'power_off': 'power', 'unexpected_shutdown': 'power', 'logout': 'login', 'unlock': 'lock', 'wake': 'sleep', 'shutdown': 'power'}
        
        for event in events:
            evt_type = event['type']
            
            if evt_type in OPENERS:
                session_key = OPENERS[evt_type]
                
                # If a session of this type is already open, close it at the new session's start (forensic best-effort)
                if open_sessions[session_key]:
                    bands.append({
                        'start': open_sessions[session_key]['timestamp'],
                        'end': event['timestamp'],
                        'type': session_key,
                        'start_event': open_sessions[session_key]['type'],
                        'end_event': 'superseded',
                        'logon_type': open_sessions[session_key].get('logon_type'),
                        'user': open_sessions[session_key].get('user'),
                        'is_dirty': False
                    })
                
                open_sessions[session_key] = event
            elif evt_type in CLOSERS:
                session_key = CLOSERS[evt_type]
                opener = open_sessions.get(session_key)
                if opener:
                    bands.append({
                        'start': opener['timestamp'],
                        'end': event['timestamp'],
                        'type': session_key,
                        'start_event': opener['type'],
                        'end_event': evt_type,
                        'logon_type': opener.get('logon_type'),
                        'user': opener.get('user'),
                        'is_dirty': evt_type == 'unexpected_shutdown'
                    })
                    open_sessions[session_key] = None
                
                # If it's a major system closer (power off), close ALL currently open sessions
                if evt_type in ['power_off', 'unexpected_shutdown', 'shutdown']:
                    for key, op in open_sessions.items():
                        if op and key != 'power': # 'power' is already handled above
                            bands.append({
                                'start': op['timestamp'],
                                'end': event['timestamp'],
                                'type': key,
                                'start_event': op['type'],
                                'end_event': 'system_shutdown',
                                'logon_type': op.get('logon_type'),
                                'user': op.get('user'),
                                'is_dirty': evt_type == 'unexpected_shutdown'
                            })
                            open_sessions[key] = None
        
        # Close any remaining open sessions with no explicit end
        for key, opener in open_sessions.items():
            if opener:
                bands.append({
                    'start': opener['timestamp'],
                    'end': None,
                    'type': key,
                    'start_event': opener['type'],
                    'end_event': 'ongoing',
                    'logon_type': opener.get('logon_type'),
                    'user': opener.get('user'),
                    'is_dirty': False
                })
        
        return bands
    
    # ──────────────────────────────────────────────
    # SLOT: Lane 2 — SRUM Application Usage
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getSrumAppData(self, start: str, end: str) -> str:
        """Get SRUM application usage data with time-sliced coverage."""
        base_sql = """
            SELECT id, timestamp, app_name,
                   foreground_cycle_time, background_cycle_time, face_time
            FROM srum_application_usage
            WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
        """
        rows = self._query_time_sliced("srum_data.db", base_sql, (start, end), "timestamp", 1000)
        rows = self._parse_timestamps_in_rows(rows, ['timestamp'])
        
        # Parse durations
        for r in rows:
            r['face_time'] = self.duration_parser.parse_to_seconds(r.get('face_time'))
            r['foreground_cycle_time'] = self.duration_parser.parse_to_seconds(r.get('foreground_cycle_time'))
            r['background_cycle_time'] = self.duration_parser.parse_to_seconds(r.get('background_cycle_time'))
            
        return json.dumps(rows)
    
    # ──────────────────────────────────────────────
    # SLOT: Lane 3 — SRUM Network
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getSrumNetData(self, start: str, end: str) -> str:
        """Get SRUM network connectivity and data usage."""
        # Network connectivity
        conn_sql = """
            SELECT id, timestamp, app_name, connected_time
            FROM srum_network_connectivity
            WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
            ORDER BY timestamp
            LIMIT 5000
        """
        connectivity = self._query_db("srum_data.db", conn_sql, (start, end))
        connectivity = self._parse_timestamps_in_rows(connectivity, ['timestamp'])
        
        for c in connectivity:
            c['connected_time'] = self.duration_parser.parse_to_seconds(c.get('connected_time'))
        
        # Network data usage
        data_sql = """
            SELECT id, timestamp, app_name, bytes_sent, bytes_received
            FROM srum_network_data_usage
            WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
            ORDER BY timestamp
            LIMIT 5000
        """
        data_usage = self._query_db("srum_data.db", data_sql, (start, end))
        data_usage = self._parse_timestamps_in_rows(data_usage, ['timestamp'])
        
        return json.dumps({
            'connectivity': connectivity,
            'data_usage': data_usage
        })
    
    # ──────────────────────────────────────────────
    # SLOT: Lane 4 — MFT/USN Correlated
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getMftUsnData(self, start: str, end: str) -> str:
        """Get MFT/USN correlated file activity with time-sliced coverage.

        The column list comes from `artifact_map` now. It used to name three
        columns of the nine the map plots, so every $FILE_NAME time on 202,729
        correlated records was fetched by nothing at all - and $SI against $FN
        is the comparison an examiner makes to spot a timestomp.
        """
        # The correlator's output is preferred: the same file events, with the
        # MFT record's own times beside each. Where it has not been run, the
        # raw journal is all there is - and until this fallback existed a case
        # with 314,469 USN records and no correlation run showed no file
        # activity at all, because the only query the bridge had named a
        # database that was not there.
        if not self._get_db_path("mft_usn_correlated_analysis.db"):
            return json.dumps(self._mapped_rows(
                "USN_journal.db", "USN", "journal_events", start, end,
                extra_cols=("filename as fn_filename, volume_letter, "
                            "reason as usn_reason,"),
                order_by="timestamp"))

        base_sql, n_pairs, ts_cols = self._mapped_query(
            "MftUsn", "mft_usn_correlated",
            extra_cols="fn_filename, reconstructed_path, usn_reason, is_deleted,")
        if not base_sql:
            return json.dumps([])
        # Time slicing needs one column to drive coverage; the USN entry is the
        # one that actually spreads across the window.
        rows = self._query_time_sliced(
            "mft_usn_correlated_analysis.db", base_sql,
            tuple([start, end] * n_pairs), "usn_timestamp", 1000)
        rows = self._parse_timestamps_in_rows(rows, ts_cols)
        return json.dumps(rows)
    
    # ──────────────────────────────────────────────
    # SLOT: Lane 5 — Execution Artifacts
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getPrefetchData(self, start: str, end: str) -> str:
        """Get prefetch execution data."""
        sql = """
            SELECT filename, executable_name, PARSABLE_NUM(run_count) as run_count,
                   last_executed, run_times,
                   created_on, modified_on, accessed_on
            FROM prefetch_data
            WHERE datetime(last_executed) BETWEEN datetime(?) AND datetime(?)
            ORDER BY last_executed
        """
        rows = self._query_db("prefetch_data.db", sql, (start, end))
        
        # Parse run_times JSON array
        for row in rows:
            if row.get('run_times'):
                try:
                    run_times_raw = json.loads(row['run_times'])
                    parsed_run_times = []
                    for rt in run_times_raw:
                        parsed = self.parser.parse(rt)
                        if parsed:
                            parsed_run_times.append(parsed)
                    row['run_times_parsed'] = parsed_run_times
                except (json.JSONDecodeError, TypeError):
                    row['run_times_parsed'] = []
        
        rows = self._parse_timestamps_in_rows(rows, ['last_executed', 'created_on', 'modified_on', 'accessed_on'])
        return json.dumps(rows)
    
    @pyqtSlot(str, str, result=str)
    def getLnkData(self, start: str, end: str) -> str:
        """Get LNK/Jump List data from all three tables (LNK_Files, Automatic_JumpLists, Custom_JumpLists)."""
        results = []
        
        # LNK_Files table
        lnk_sql = """
            SELECT rowid as id, Source_Name, Source_Path, Time_Access, Time_Creation, Time_Modification,
                   Local_Path, Common_Path, File_Attributes_Flags AS File_Attributes, 
                   FileSize, Artifact, LNK_Class_ID, Hot_Key_Value, IconIndex, Description
            FROM LNK_Files
            WHERE (datetime(Time_Access) BETWEEN datetime(?) AND datetime(?))
               OR (datetime(Time_Creation) BETWEEN datetime(?) AND datetime(?))
               OR (datetime(Time_Modification) BETWEEN datetime(?) AND datetime(?))
            ORDER BY COALESCE(Time_Access, Time_Creation, Time_Modification)
        """
        lnk_rows = self._query_db("LnkDB.db", lnk_sql,
                                    (start, end, start, end, start, end))
        for row in lnk_rows:
            row['table_source'] = 'LNK_Files'
        
        # Automatic_JumpLists table
        ajl_sql = """
            SELECT rowid as id, Source_Name, Source_Path, Time_Access, Time_Creation, Time_Modification,
                   AppType, AppID, Artifact, Local_Path, Common_Path, 
                   File_Attributes_Flags AS File_Attributes, FileSize,
                   DestList_Access_Counter, DestList_Pin_Status, Birth_Volume_ID, Birth_Object_ID,
                   DestList_Total_Current_Entries, DestList_Total_Pinned_Entries
            FROM Automatic_JumpLists
            WHERE (datetime(Time_Access) BETWEEN datetime(?) AND datetime(?))
               OR (datetime(Time_Creation) BETWEEN datetime(?) AND datetime(?))
               OR (datetime(Time_Modification) BETWEEN datetime(?) AND datetime(?))
            ORDER BY COALESCE(Time_Access, Time_Creation, Time_Modification)
        """
        ajl_rows = self._query_db("LnkDB.db", ajl_sql,
                                    (start, end, start, end, start, end))
        for row in ajl_rows:
            row['table_source'] = 'Automatic_JumpLists'
        
        # Custom_JumpLists table 
        cjl_sql = """
            SELECT rowid as id, Source_Name, Source_Path, Time_Access, Time_Creation, Time_Modification,
                   AppType, AppID, Artifact, Local_Path, FileSize, Category, Footer_Signature_Valid
            FROM Custom_JumpLists
            WHERE (datetime(Time_Access) BETWEEN datetime(?) AND datetime(?))
               OR (datetime(Time_Creation) BETWEEN datetime(?) AND datetime(?))
               OR (datetime(Time_Modification) BETWEEN datetime(?) AND datetime(?))
            ORDER BY COALESCE(Time_Access, Time_Creation, Time_Modification)
        """
        cjl_rows = self._query_db("LnkDB.db", cjl_sql,
                                      (start, end, start, end, start, end))
        for row in cjl_rows:
            row['table_source'] = 'Custom_JumpLists'
        
        all_rows = lnk_rows + ajl_rows + cjl_rows
        all_rows = self._parse_timestamps_in_rows(all_rows, 
                                                    ['Time_Access', 'Time_Creation', 'Time_Modification'])
        return json.dumps(all_rows)
    
    @pyqtSlot(str, str, result=str)
    def getBamData(self, start: str, end: str) -> str:
        """Get BAM (Background Activity Moderator) and DAM data."""
        results = {}
        
        # BAM. It has no run_count and never has - BAM records one last-run
        # time per executable, not a count - so this whole query threw and the
        # panel showed nothing. `app_name` is the decoded program name the
        # parser derives from the value name.
        bam_sql = """
            SELECT process_path, last_execution, sid, app_name
            FROM BAM
            WHERE datetime(last_execution) BETWEEN datetime(?) AND datetime(?)
            ORDER BY last_execution
        """
        results['bam'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", bam_sql, (start, end)), 
            ['last_execution']
        )
        
        # DAM (Desktop Activity Moderator)
        dam_sql = """
            SELECT app_name as process_path, last_execution, 'N/A' as sid
            FROM DAM
            WHERE datetime(last_execution) BETWEEN datetime(?) AND datetime(?)
            ORDER BY last_execution
        """
        results['dam'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", dam_sql, (start, end)), 
            ['last_execution']
        )
        
        return json.dumps(results)
    
    @pyqtSlot(str, str, result=str)
    def getRegistryData(self, start: str, end: str) -> str:
        """Get registry artifact data (OpenSaveMRU, LastSaveMRU, Shellbags, RecentDocs, UserAssist)."""
        result = {}
        
        # OpenSaveMRU
        # An MRU list stores no time per entry, so `access_date` is empty by
        # design and the parser refuses to guess. `key_last_write` is the
        # containing key's own time - it dates the newest entry in the list,
        # and every row carries it. Keyed on access_date this returned nothing
        # from 246 OpenSaveMRU rows and 20 LastSaveMRU rows.
        open_sql = """
            SELECT extension, file_name as filename, file_path,
                   key_last_write as access_date, 1 as bounded_time,
                   'opensavemru' as tsType
            FROM OpenSaveMRU
            WHERE datetime(key_last_write) BETWEEN datetime(?) AND datetime(?)
            ORDER BY key_last_write
        """
        result['open_save_mru'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", open_sql, (start, end)),
            ['access_date']
        )
        
        # LastSaveMRU
        last_sql = """
            SELECT type as extension, folder_name as filename, folder_path,
                   key_last_write as access_date, 1 as bounded_time,
                   application, 'lastsavemru' as tsType
            FROM LastSaveMRU
            WHERE datetime(key_last_write) BETWEEN datetime(?) AND datetime(?)
            ORDER BY key_last_write
        """
        result['last_save_mru'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", last_sql, (start, end)),
            ['access_date']
        )
        
        # Shellbags
        shell_sql = """
            SELECT rowid as id, file_name as path, file_name as name, shell_item_type as shell_type, modified_date, accessed_date, created_date,
                   'shellbags' as tsType
            FROM Shellbags
            WHERE datetime(modified_date) BETWEEN datetime(?) AND datetime(?)
               OR datetime(accessed_date) BETWEEN datetime(?) AND datetime(?)
               OR datetime(created_date) BETWEEN datetime(?) AND datetime(?)
            ORDER BY COALESCE(modified_date, accessed_date, created_date)
        """
        result['shellbags'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", shell_sql, (start, end, start, end, start, end)),
            ['modified_date', 'accessed_date', 'created_date']
        )

        # RecentDocs
        # RecentDocs holds subkey/name/row_data/key_last_write - never
        # file_name, file_path, extension or access_date. This query threw on
        # every case and the panel showed an empty section.
        recent_docs_sql = """
            SELECT rowid as id, row_data as filename, row_data as path,
                   subkey as extension, key_last_write as access_date,
                   'linked' as tsType
            FROM RecentDocs
            WHERE datetime(key_last_write) BETWEEN datetime(?) AND datetime(?)
            ORDER BY key_last_write
        """
        result['recent_docs'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", recent_docs_sql, (start, end)),
            ['access_date']
        )

        # UserAssist
        userassist_sql = """
            SELECT program_path as filename, program_path as path, program_path as name, 
                   last_execution as access_date, PARSABLE_NUM(focus_time) as focus_time, run_count,
                   'executed' as tsType
            FROM UserAssist
            WHERE datetime(last_execution) BETWEEN datetime(?) AND datetime(?)
            ORDER BY last_execution
        """
        result['user_assist'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", userassist_sql, (start, end)),
            ['access_date']
        )

        # BAM
        bam_sql = """
            SELECT rowid as id, process_path as filename, process_path as path, last_execution as access_date, sid,
                   'bam' as tsType
            FROM BAM
            WHERE datetime(last_execution) BETWEEN datetime(?) AND datetime(?)
            ORDER BY last_execution
        """
        result['bam'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", bam_sql, (start, end)),
            ['access_date']
        )
        
        # ComputerNameInfo
        comp_name_sql = """
            SELECT * FROM ComputerNameInfo
            WHERE datetime(installation_date) BETWEEN datetime(?) AND datetime(?)
        """
        result['computer_name'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", comp_name_sql, (start, end)),
            ['installation_date']
        )

        # `Auto` was an abandoned draft of WindowsUpdateInfo and no parser has
        # written it for a long time. The query below it reads the real table.

        # WindowsUpdateInfo
        # `scheduled_install_time` is NOT a time. It holds Windows Update's
        # `ScheduledInstallTime` policy value - the hour of day, an integer
        # 0-23 - and filtering or plotting on it is meaningless.
        winupdate_sql = """
            SELECT * FROM WindowsUpdateInfo
            WHERE datetime(last_check_time) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_install_time) BETWEEN datetime(?) AND datetime(?)
        """
        result['windows_update'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", winupdate_sql, (start, end, start, end)),
            ['last_check_time', 'last_install_time']
        )

        # NetworkInterfacesInfo and NetworkListProfiles are deliberately NOT
        # placed on the timeline.
        #
        # NetworkInterfacesInfo carries no real event time — its only timestamp
        # is the parser-bookkeeping column (now `parsed_at`, formerly
        # `timestamp`). Plotting it rendered "when Crow-Eye ran" as network
        # activity, which is exactly the confusion the parsed_at rename removes.
        # Interface configuration is still available in the Registry tab.
        #
        # NetworkListProfiles was never a table any RegClaw path creates (the
        # real table is Network_list, queried below), so that query only ever
        # returned nothing.

        # USBStorageDevices
        usb_sql = """
            SELECT rowid as id, friendly_name as filename, friendly_name as name, vendor_id, product_id, serial_number,
                   first_connected, last_connected, last_removed,
                   'usb_devices' as tsType
            FROM USBStorageDevices
            WHERE datetime(first_connected) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_connected) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_removed) BETWEEN datetime(?) AND datetime(?)
        """
        result['usb_devices'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", usb_sql, (start, end, start, end, start, end)),
            ['first_connected', 'last_connected', 'last_removed']
        )

        # ShutdownInfo
        shutdown_sql = """
            SELECT * FROM ShutdownInfo
            WHERE datetime(shutdown_time) BETWEEN datetime(?) AND datetime(?)
        """
        result['shutdown_info'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", shutdown_sql, (start, end)),
            ['shutdown_time']
        )

        # InstalledSoftware
        installed_software_sql = """
            SELECT * FROM InstalledSoftware
            WHERE datetime(install_date) BETWEEN datetime(?) AND datetime(?)
        """
        result['installed_software'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", installed_software_sql, (start, end)),
            ['install_date']
        )

        # WordWheelQuery
        wordwheel_sql = """
            SELECT *, key_last_write as access_date, 1 as bounded_time,
                   'wordwheelquery' as tsType FROM WordWheelQuery
            WHERE datetime(key_last_write) BETWEEN datetime(?) AND datetime(?)
        """
        result['wordwheel'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", wordwheel_sql, (start, end)),
            ['access_date']
        )

        # RunMRU
        run_mru_sql = """
            SELECT *, key_last_write as access_date, 1 as bounded_time
            FROM RunMRU
            WHERE datetime(key_last_write) BETWEEN datetime(?) AND datetime(?)
        """
        result['run_mru'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", run_mru_sql, (start, end)),
            ['access_date']
        )

        # Network_list
        netlist_sql = """
            SELECT * FROM Network_list
            WHERE datetime(connection_date) BETWEEN datetime(?) AND datetime(?)
        """
        result['network_list'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", netlist_sql, (start, end)),
            ['connection_date']
        )

        # ---- artifacts the parsers collect that the timeline never plotted --
        #
        # `bounded_time` marks a row whose time is the containing KEY's write
        # time rather than the record's own. The front end draws those hollow
        # and hides them behind a toggle, because a key time is an upper bound
        # on every value under it and a solid marker at a precise point claims
        # more than the evidence does.

        # Scheduled tasks - the scheduler's own per-task times, so NOT bounded.
        tasks_sql = """
            SELECT rowid as id, task_path as filename, task_path as path,
                   command, run_context, task_registered, last_run,
                   last_completed, last_result, 'scheduledtask' as tsType
            FROM ScheduledTasks
            WHERE datetime(task_registered) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_run) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_completed) BETWEEN datetime(?) AND datetime(?)
            ORDER BY COALESCE(task_registered, last_run)
        """
        result['scheduled_tasks'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", tasks_sql,
                           (start, end, start, end, start, end)),
            ['task_registered', 'last_run', 'last_completed']
        )

        # Value changes recovered from the transaction log. `changed_at` is the
        # exact moment that value changed - the one registry time that is not
        # an upper bound.
        changes_sql = """
            SELECT rowid as id, key_path as path, value_name as filename,
                   change_kind, changed_at, hive_name,
                   'registrychange' as tsType
            FROM registry_value_changes
            WHERE changed_at IS NOT NULL AND trim(changed_at) <> ''
              AND datetime(changed_at) BETWEEN datetime(?) AND datetime(?)
            ORDER BY changed_at
        """
        result['registry_changes'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", changes_sql, (start, end)),
            ['changed_at']
        )

        # USB storage. Device property FILETIMEs read from the acquired hive -
        # empty on every live case until the USBSTOR block stopped raising
        # NameError on an unassigned variable.
        usbstor_sql = """
            SELECT rowid as id, friendly_name as filename, serial_number,
                   vendor_id, product_id, first_connected, last_connected,
                   last_removed, 'usbstorage' as tsType
            FROM USBStorageDevices
            WHERE datetime(first_connected) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_connected) BETWEEN datetime(?) AND datetime(?)
               OR datetime(last_removed) BETWEEN datetime(?) AND datetime(?)
            ORDER BY COALESCE(last_connected, first_connected)
        """
        result['usb_storage'] = self._parse_timestamps_in_rows(
            self._query_db("registry_data.db", usbstor_sql,
                           (start, end, start, end, start, end)),
            ['first_connected', 'last_connected', 'last_removed']
        )

        # Network profiles. `date_created` and `date_last_connected` are the
        # profile's OWN times, unlike the `last_written` on the same table -
        # they were mapped and read by nothing, so a wireless network first
        # joined three years ago appeared on the timeline nowhere.
        result['network_profiles'] = self._mapped_rows(
            "registry_data.db", "Registry", "NetworkProfiles", start, end,
            extra_cols=("profile_name as filename, key_path as path, "
                        "description, gateway_mac, category_label, "
                        "'networkprofile' as tsType,"),
            order_by="date_created")

        # SAM accounts. When an account last signed in and when its
        # password was last set - two of the first questions in an intrusion,
        # and neither reached the timeline. They come from `user_identity.py`
        # rather than Regclaw, which is why nothing that reads one file per
        # artifact family ever noticed.
        result['user_accounts'] = self._mapped_rows(
            "registry_data.db", "Registry", "UserAccounts", start, end,
            extra_cols=("username as filename, display_name, user_sid, rid, "
                        "account_type, account_enabled, "
                        "'useraccount' as tsType,"),
            order_by="last_logon")

        # Per-app capability use: microphone, camera, location. The record's
        # own start/stop times, beside the same table's key write time.
        result['app_permissions'] = self._mapped_rows(
            "registry_data.db", "Registry", "app_permissions", start, end,
            extra_cols=("app as filename, key_path as path, capability, "
                        "permission, 'apppermission' as tsType,"),
            order_by="last_used_start")

        # Every remaining registry table whose only time is its key's write
        # time. One query shape, so a table added later is one line here.
        result['key_times'] = self._registry_key_time_rows(start, end)

        return json.dumps(result)

    # Per table: the analyst-facing label, the column naming what the row is
    # about, and the column holding the key path (None where the table has
    # none). The TIME column and whether the table records a `time_basis` come
    # from `artifact_map`, so this cannot drift away from the map that decides
    # what gets plotted - which is how three separate copies of this list came
    # to disagree in the first place.
    #
    # The MRU tables are deliberately absent: they are key times too, but each
    # already has its own query above with the columns an MRU row needs.
    _KEY_TIME_LABELS = {
        "AutoStartPrograms": ("Autostart entry", "program_name", "key_path"),
        "DefenderExclusions": ("Defender exclusion", "value", "key_path"),
        "SecurityPosture": ("Security setting", "setting", "key_path"),
        "file_exts": ("File type handler", "extension", "key_path"),
        "FeatureUsage": ("Feature usage", "program", "key_path"),
        "CompatibilityAssistant": ("Compatibility Assistant", "program_path", "key_path"),
        "ConnectedDevices": ("Connected device", "friendly_name", "key_path"),
        "MountPoints2": ("Volume opened", "mount_id", "key_path"),
        "OfficeDocuments": ("Office document", "document", "key_path"),
        "FirewallRules": ("Firewall rule", "rule_name", "key_path"),
        "app_paths": ("App path", "app_name", "key_path"),
        "shared_dlls": ("Shared DLL", "dll_path", "key_path"),
        "startup_approved": ("Startup approval", "entry_name", "key_path"),
        "explorer_advanced": ("Explorer setting", "setting", "key_path"),
        "windows_script_host": ("Script host setting", "setting", "key_path"),
        "winevt_channels": ("Event log channel", "channel", "key_path"),
        "zone_map": ("Zone policy", "scope", "key_path"),
        "system_configuration": ("System configuration", "setting", "key_path"),
        # SECURITY hive. Small tables, but an audit policy or an LSA secret
        # changing is worth more on a timeline than most of the rows above.
        "audit_policy": ("Audit policy", "name", "key_path"),
        "lsa_policy": ("LSA policy", "name", "key_path"),
        "lsa_secrets": ("LSA secret", "secret_name", "key_path"),
        "local_groups": ("Local group", "group_name", None),
        # Deleted keys recovered by carving - 2,106 dated rows on an ordinary
        # machine, and none of them reached the timeline before.
        "registry_carved_keys": ("Deleted key (carved)", "key_name", "key_path"),
    }

    @property
    def _key_time_sources(self):
        """(label, table, name column, time column, path column, basis column).

        Built from `artifact_map`, so a table added to the plotting map and
        given a label here is drawn; one given a label and no map entry is
        not, rather than being drawn under rules nothing else agrees with.
        """
        from timeline.data import artifact_map as _am

        out = []
        for table, column, _kind, basis in _am._KEY_TIME_TABLES:
            meta = self._KEY_TIME_LABELS.get(table)
            if not meta:
                continue
            label, name_col, path_col = meta
            out.append((label, table, name_col, column, path_col, basis))
        return out

    def _registry_key_time_rows(self, start: str, end: str) -> list:
        """Rows whose only time is the containing key's last-write time.

        Every one is an upper bound, so each row is tagged `bounded_time` and
        carries its `time_basis` where the parser records one. A table missing
        from the case, or missing the label column, is skipped rather than
        failing the lot - these tables come and go between parser versions.
        """
        rows = []
        for label, table, name_col, time_col, path_col, basis in self._key_time_sources:
            sql = """
                SELECT rowid as id, {name} as filename, {path} as path,
                       {time} as access_date, {basis} as time_basis,
                       1 as bounded_time, '{label}' as subType,
                       'keytime' as tsType
                FROM {table}
                WHERE {time} IS NOT NULL AND trim({time}) <> ''
                  AND datetime({time}) BETWEEN datetime(?) AND datetime(?)
            """.format(name=name_col, table=table, time=time_col,
                       path=path_col or "''",
                       basis=basis or "'key upper bound'",
                       label=label.replace("'", ""))
            got = self._query_db("registry_data.db", sql, (start, end))
            if got:
                rows.extend(self._parse_timestamps_in_rows(got, ['access_date']))
        return rows

    # ──────────────────────────────────────────────
    # Queries built from the map
    # ──────────────────────────────────────────────

    def _norm_ts(self, value):
        """SQLite `NORM_TS()` - any stored timestamp format to `YYYY-MM-DD ...`.

        Backed by the same `UniversalTimestampParser` that normalises the value
        one step later, so the filter and the display agree by construction.
        """
        try:
            return self.parser.parse(value)
        except Exception:
            return None

    def _needs_normalising(self, db_name: str, table: str, column: str) -> bool:
        """Does SQLite's own `datetime()` understand what this column holds?

        Probed against one real value and cached, rather than assumed. Wrapping
        every column would put a Python call on every row of every query -
        202,729 correlated MFT records times nine columns - to fix three
        AmCache tables.
        """
        key = (db_name, table, column)
        cache = self.__dict__.setdefault("_norm_probe", {})
        if key in cache:
            return cache[key]
        verdict = False
        try:
            rows = self._query_db(
                db_name,
                'SELECT datetime("{c}") as iso, "{c}" as raw FROM "{t}" '
                'WHERE "{c}" IS NOT NULL AND trim("{c}") <> \'\' '
                'LIMIT 1'.format(c=column, t=table))
            if rows and rows[0].get("iso") is None and rows[0].get("raw"):
                verdict = True
        except Exception:
            verdict = False
        cache[key] = verdict
        return verdict

    def _mapped_time_columns(self, artifact: str, table: str) -> list:
        """The RECORD time columns `artifact_map` plots for one table.

        Reading them from the map instead of writing them out here is what
        stops a query and the map disagreeing. `getMftUsnData` selected three
        of the nine columns the map names, so six populated time columns -
        every $FN time on 202,729 records - were fetched by nothing.

        Key write times are excluded: they have their own query shape, which
        tags each row `bounded_time` so the front end draws it hollow. Letting
        one through here would put a key upper bound on screen as an exact
        moment - `NetworkProfiles` is the table that would do it, carrying two
        record times and a `last_written` side by side.
        """
        from timeline.data import artifact_map as _am
        return [e[1] for e in _am.TIMESTAMP_MAPPINGS.get(artifact, [])
                if e[0] == table and not _am.is_key_time(e)]

    def _mapped_query(self, artifact: str, table: str, extra_cols: str = "",
                      order_by: str = "", where_extra: str = "",
                      normalise: tuple = ()):
        """(sql, params_needed, time_columns) for one mapped table.

        One row per RECORD carrying all of its times, not one row per time -
        that is the shape the front end already expands with
        `getForensicTimestamps`, and the other shape would turn 202,729
        correlated records into 1.6 million points.

        `params_needed` is how many (start, end) pairs the caller must supply:
        the WHERE is an OR across every mapped time column, because a record
        whose only in-window time is its third one still belongs on screen.
        """
        cols = self._mapped_time_columns(artifact, table)
        if not cols:
            return None, 0, []
        selected = ", ".join('"%s"' % c for c in cols)

        def _expr(c):
            # NORM_TS only where SQLite cannot read the stored format itself.
            return ('datetime(NORM_TS("%s"))' % c if c in normalise
                    else 'datetime("%s")' % c)

        window = "\n               OR ".join(
            '%s BETWEEN datetime(?) AND datetime(?)' % _expr(c) for c in cols)
        sql = """
            SELECT rowid as id, {extra}{selected}
            FROM {table}
            WHERE ({window}){extra_where}
            {order}
        """.format(
            extra=(extra_cols.rstrip().rstrip(",") + ", ") if extra_cols else "",
            selected=selected, table=table, window=window,
            extra_where=(" AND " + where_extra) if where_extra else "",
            order=("ORDER BY " + order_by) if order_by else "",
        )
        return sql, len(cols), cols

    def _mapped_rows(self, db_name: str, artifact: str, table: str,
                     start: str, end: str, extra_cols: str = "",
                     order_by: str = "", where_extra: str = "",
                     params_extra: tuple = ()) -> list:
        """Run `_mapped_query` and parse its timestamps."""
        cols_all = self._mapped_time_columns(artifact, table)
        normalise = tuple(c for c in cols_all
                          if self._needs_normalising(db_name, table, c))
        sql, n_pairs, cols = self._mapped_query(
            artifact, table, extra_cols, order_by, where_extra, normalise)
        if not sql:
            return []
        params = tuple([start, end] * n_pairs) + tuple(params_extra)
        return self._parse_timestamps_in_rows(
            self._query_db(db_name, sql, params), cols)

    # ──────────────────────────────────────────────
    # SLOT: Event logs
    # ──────────────────────────────────────────────

    @pyqtSlot(str, str, bool, result=str)
    def getEventLogData(self, start: str, end: str, include_all: bool) -> str:
        """Windows Event Log records for the artifact lane.

        The event log is the largest time source in a case and, until this
        slot existed, 41,109 of 43,802 records on an ordinary machine reached
        the timeline through nothing at all - `getSessionData` reads eighteen
        hard-coded IDs for the session band and no other query touches these
        tables. A service install, a process creation and a cleared log were
        all invisible.

        By default only `SIGNIFICANT_EVENT_IDS` are returned, each carrying its
        meaning in words, because one ID alone (5379, a credential-manager
        read) is 22,012 rows and would bury everything else. `include_all`
        lifts the filter.
        """
        from timeline.data import artifact_map as _am

        rows = []
        for table in _am.EVENT_LOG_TABLES:
            wanted = [str(i) for i, (log, _lab)
                      in _am.SIGNIFICANT_EVENT_IDS.items() if log == table]
            if not include_all and not wanted:
                continue
            where_extra = ("" if include_all
                           else "EventID IN (%s)" % ", ".join(wanted))
            got = self._mapped_rows(
                "Log_Claw.db", "Logs", table, start, end,
                extra_cols=("EventID, Source, EventType, User, ComputerName, "
                            "EventDescription, '%s' as source_log, "
                            "'eventlog' as tsType," % table),
                order_by="EventTimestampUTC",
                where_extra=where_extra)
            for r in got:
                # The marker reads "Service installed", not "7045".
                meaning = _am.SIGNIFICANT_EVENT_IDS.get(r.get("EventID"))
                r["subType"] = meaning[1] if meaning else (
                    "Event %s" % r.get("EventID"))
                r["significant"] = 1 if meaning else 0
                r["filename"] = r["subType"]
            rows.extend(got)
        rows.sort(key=lambda r: r.get("EventTimestampUTC") or "")
        return json.dumps(rows)

    # ──────────────────────────────────────────────
    # SLOT: Lane 6 — AmCache, ShimCache, RecycleBin
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getAmcacheData(self, start: str, end: str) -> str:
        """Get AmCache data — lightweight columns only.

        Keys unchanged: `App.jsx` merges these three by name. Only the SQL
        moved, so the map decides which times are read.
        """
        result = {}

        result['application_files'] = self._mapped_rows(
            "amcache.db", "Amcache", "InventoryApplicationFile", start, end,
            extra_cols="name,")

        result['applications'] = self._mapped_rows(
            "amcache.db", "Amcache", "InventoryApplication", start, end,
            extra_cols="name,")
        
        result['drivers'] = self._mapped_rows(
            "amcache.db", "Amcache", "InventoryDriverBinary", start, end,
            extra_cols="driver_name,")

        # Device and driver-package installation. When a piece of hardware or
        # a driver first appeared on this machine is asked in most USB and
        # rogue-device investigations, and AmCache records it - three dates on
        # InventoryDevicePnp alone, none of them previously read.
        result['devices'] = self._mapped_rows(
            "amcache.db", "Amcache", "InventoryDevicePnp", start, end,
            extra_cols=("model as filename, manufacturer, driver_name, "
                        "class, service, 'amcachedevice' as tsType,"))
        result['driver_packages'] = self._mapped_rows(
            "amcache.db", "Amcache", "InventoryDriverPackage", start, end,
            extra_cols=("inf as filename, provider, class, version, "
                        "'amcachedriverpkg' as tsType,"))

        return json.dumps(result)
    
    @pyqtSlot(str, str, result=str)
    def getShimcacheData(self, start: str, end: str) -> str:
        """Get ShimCache entries. Time columns from `artifact_map`."""
        return json.dumps(self._mapped_rows(
            "shimcache.db", "Shimcache", "shimcache_entries", start, end,
            extra_cols=("filename, path, last_modified_readable, data_size, "
                        "entry_size, cache_entry_position,"),
            order_by="last_modified"))

    @pyqtSlot(str, str, result=str)
    def getRecyclebinData(self, start: str, end: str) -> str:
        """Get Recycle Bin entries. Time columns from `artifact_map`."""
        return json.dumps(self._mapped_rows(
            "recyclebin_analysis.db", "RecycleBin", "recycle_bin_entries",
            start, end,
            extra_cols=("original_filename, original_path, "
                        "PARSABLE_NUM(formatted_file_size) as file_size_raw, "
                        "formatted_file_size, user_sid, file_signature, "
                        "recovery_status,"),
            order_by="deletion_time"))
    
    # ──────────────────────────────────────────────
    # SLOT: SRUM Energy (supplementary)
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getSrumEnergyData(self, start: str, end: str) -> str:
        """Get SRUM energy usage data."""
        sql = """
            SELECT id, timestamp, app_name, user_name,
                   event_timestamp, state_transition, charge_level, cycle_count
            FROM srum_energy_usage
            WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
            ORDER BY timestamp
        """
        rows = self._query_db("srum_data.db", sql, (start, end))
        rows = self._parse_timestamps_in_rows(rows, ['timestamp', 'event_timestamp'])
        return json.dumps(rows)
    
    # ──────────────────────────────────────────────
    # SLOT: Event Detail (double-click)
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, str, result=str)
    def getEventDetail(self, db_name: str, table_name: str, row_id: str) -> str:
        """Get full row detail for a specific event (on double-click).

        The allow-list is derived from `artifact_map`, not written out. It was
        a fourth hand-maintained copy of the same table list and it had gone
        stale in the worst possible way: it named none of the tables added
        recently - ScheduledTasks, registry_value_changes, registry_carved_keys,
        the SECURITY-hive tables, all 26 key-time tables, mft_records,
        journal_events - so double-clicking any of those rows returned
        `Table not allowed` and `EventDetailModal` fell back to the summary
        row. The modal opened, showed six fields instead of thirty, and said
        nothing about why.

        Still an allow-list, and still a fixed one: the caller cannot widen it,
        it just no longer has to be remembered.
        """
        from timeline.data import artifact_map as _am

        allowed = set()
        for entries in _am.TIMESTAMP_MAPPINGS.values():
            allowed.update(e[0] for e in entries)
        allowed.update(t for t, _c, _k, _b in _am._KEY_TIME_TABLES)
        # Tables the timeline shows but does not plot a time from.
        allowed.update((
            "USBDevices", "NetworkListProfiles", "NetworkInterfacesInfo",
            "srum_app_timeline", "DAM",
        ))

        if table_name not in allowed:
            return json.dumps({'error': f'Table not allowed: {table_name}'})

        # Which column identifies a row. `id` where the parser writes one,
        # `rowid` otherwise - and getting this wrong returns "Not found"
        # rather than an error.
        id_col = 'rowid'
        try:
            cols = {r['name'] for r in self._query_db(
                db_name, f'PRAGMA table_info("{table_name}")')}
            if 'id' in cols:
                id_col = 'id'
        except Exception:
            pass

        sql = f"SELECT * FROM [{table_name}] WHERE {id_col} = ? LIMIT 1"
        rows = self._query_db(db_name, sql, (row_id,))
        
        if rows:
            return json.dumps(rows[0])
        return json.dumps({'error': 'Not found'})
    
    # ──────────────────────────────────────────────
    # SLOT: Aggregated counts (for week/heatmap views)
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, str, result=str)
    def getAggregatedCounts(self, start: str, end: str) -> str:
        """
        Get per-day event counts for each data source.
        Used by WeekView and HeatmapView for aggregated rendering.
        """
        result = {}
        
        def fetch_system():
            return self._query_db("Log_Claw.db", """
                SELECT DATE(EventTimestampUTC) as day, STRFTIME('%H', EventTimestampUTC) as hour, COUNT(*) as count
                FROM [SystemLogs]
                WHERE datetime(EventTimestampUTC) BETWEEN datetime(?) AND datetime(?)
                GROUP BY DATE(EventTimestampUTC), STRFTIME('%H', EventTimestampUTC) ORDER BY day
            """, (start, end))

        def fetch_app():
            return self._query_db("Log_Claw.db", """
                SELECT DATE(EventTimestampUTC) as day, STRFTIME('%H', EventTimestampUTC) as hour, COUNT(*) as count
                FROM [ApplicationLogs]
                WHERE datetime(EventTimestampUTC) BETWEEN datetime(?) AND datetime(?)
                GROUP BY DATE(EventTimestampUTC), STRFTIME('%H', EventTimestampUTC) ORDER BY day
            """, (start, end))

        def fetch_sec():
            return self._query_db("Log_Claw.db", """
                SELECT DATE(EventTimestampUTC) as day, STRFTIME('%H', EventTimestampUTC) as hour, COUNT(*) as count
                FROM [SecurityLogs]
                WHERE datetime(EventTimestampUTC) BETWEEN datetime(?) AND datetime(?)
                GROUP BY DATE(EventTimestampUTC), STRFTIME('%H', EventTimestampUTC) ORDER BY day
            """, (start, end))
            
        def fetch_srum_app():
            return self._query_db("srum_data.db", """
                SELECT DATE(timestamp) as day, STRFTIME('%H', timestamp) as hour, COUNT(*) as count
                FROM srum_application_usage
                WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
                GROUP BY DATE(timestamp), STRFTIME('%H', timestamp) ORDER BY day
            """, (start, end))
            
        def fetch_srum_net():
            return self._query_db("srum_data.db", """
                SELECT DATE(timestamp) as day, STRFTIME('%H', timestamp) as hour, COUNT(*) as count,
                       SUM(PARSABLE_NUM(bytes_sent)) as total_sent, SUM(PARSABLE_NUM(bytes_received)) as total_received
                FROM srum_network_data_usage
                WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
                GROUP BY DATE(timestamp), STRFTIME('%H', timestamp) ORDER BY day
            """, (start, end))
            
        def fetch_mft():
            return self._query_db("mft_usn_correlated_analysis.db", """
                SELECT DATE(COALESCE(usn_timestamp, si_modification_time)) as day, STRFTIME('%H', COALESCE(usn_timestamp, si_modification_time)) as hour, COUNT(*) as count
                FROM mft_usn_correlated
                WHERE (datetime(usn_timestamp) BETWEEN datetime(?) AND datetime(?)) OR (datetime(si_modification_time) BETWEEN datetime(?) AND datetime(?))
                GROUP BY day, hour ORDER BY day
            """, (start, end, start, end))
        def fetch_prefetch():
            return self._query_db("prefetch_data.db", """
                SELECT DATE(last_executed) as day, STRFTIME('%H', last_executed) as hour, COUNT(*) as count
                FROM prefetch_data WHERE datetime(last_executed) BETWEEN datetime(?) AND datetime(?)
                GROUP BY day, hour ORDER BY day
            """, (start, end))

        def fetch_shimcache():
            return self._query_db("shimcache.db", """
                SELECT DATE(last_modified) as day, STRFTIME('%H', last_modified) as hour, COUNT(*) as count
                FROM shimcache_entries WHERE datetime(last_modified) BETWEEN datetime(?) AND datetime(?)
                GROUP BY day, hour ORDER BY day
            """, (start, end))

        def fetch_amcache():
            return self._query_db("amcache.db", """
                SELECT day, hour, SUM(c) as count FROM (
                    SELECT DATE(link_date) as day, STRFTIME('%H', link_date) as hour, COUNT(*) as c FROM InventoryApplicationFile GROUP BY day, hour
                    UNION ALL
                    SELECT DATE(install_date) as day, STRFTIME('%H', install_date) as hour, COUNT(*) as c FROM InventoryApplication GROUP BY day, hour
                ) WHERE day BETWEEN DATE(?) AND DATE(?) GROUP BY day, hour ORDER BY day
            """, (start, end))

        def fetch_recycle():
            return self._query_db("recyclebin_analysis.db", """
                SELECT DATE(deletion_time) as day, STRFTIME('%H', deletion_time) as hour, COUNT(*) as count
                FROM recycle_bin_entries WHERE datetime(deletion_time) BETWEEN datetime(?) AND datetime(?)
                GROUP BY day, hour ORDER BY day
            """, (start, end))

        def fetch_lnk():
            # Robust dynamic union to skip missing tables
            query_parts = []
            if self._table_exists("LnkDB.db", "LNK_Files"):
                query_parts.append("SELECT DATE(Time_Access) as day, STRFTIME('%H', Time_Access) as hour, COUNT(*) as c FROM LNK_Files GROUP BY day, hour")
                query_parts.append("SELECT DATE(Time_Creation) as day, STRFTIME('%H', Time_Creation) as hour, COUNT(*) as c FROM LNK_Files GROUP BY day, hour")
                query_parts.append("SELECT DATE(Time_Modification) as day, STRFTIME('%H', Time_Modification) as hour, COUNT(*) as c FROM LNK_Files GROUP BY day, hour")
            if self._table_exists("LnkDB.db", "Automatic_JumpLists"):
                query_parts.append("SELECT DATE(Time_Access) as day, STRFTIME('%H', Time_Access) as hour, COUNT(*) as c FROM Automatic_JumpLists GROUP BY day, hour")
                query_parts.append("SELECT DATE(Time_Creation) as day, STRFTIME('%H', Time_Creation) as hour, COUNT(*) as c FROM Automatic_JumpLists GROUP BY day, hour")
                query_parts.append("SELECT DATE(Time_Modification) as day, STRFTIME('%H', Time_Modification) as hour, COUNT(*) as c FROM Automatic_JumpLists GROUP BY day, hour")
            if self._table_exists("LnkDB.db", "Custom_JumpLists"):
                query_parts.append("SELECT DATE(Time_Access) as day, STRFTIME('%H', Time_Access) as hour, COUNT(*) as c FROM Custom_JumpLists GROUP BY day, hour")
                query_parts.append("SELECT DATE(Time_Creation) as day, STRFTIME('%H', Time_Creation) as hour, COUNT(*) as c FROM Custom_JumpLists GROUP BY day, hour")
                query_parts.append("SELECT DATE(Time_Modification) as day, STRFTIME('%H', Time_Modification) as hour, COUNT(*) as c FROM Custom_JumpLists GROUP BY day, hour")
            
            if not query_parts: return []
            union_sql = f"SELECT day, hour, SUM(c) as count FROM ({' UNION ALL '.join(query_parts)}) WHERE day BETWEEN DATE(?) AND DATE(?) GROUP BY day, hour ORDER BY day"
            return self._query_db("LnkDB.db", union_sql, (start, end))

        def fetch_artifacts_registry():
            """Per-day registry counts for the heatmap and week views.

            The (table, column) list used to be written out here by hand, and
            it was the THIRD copy of that list in the codebase. It had drifted
            the same way the other two had: the four MRU tables keyed on
            `access_date`, which the MRU parser leaves empty by design;
            `UserAssist.focus_time`, which is a duration stored as "0.00s";
            `NetworkListProfiles`, `Registry_Run`, `JumpList` and
            `AppX_Execution`, none of which exist. Nine of eighteen entries
            counted nothing, and the heatmap simply showed fewer days.

            Now derived from `artifact_map`, so a parser change reaches the
            heatmap the same way it reaches everything else.

            RECORD times only. The 2,161 key write times are an upper bound
            apiece, most of them stamped on install day, and pouring them into
            a per-day heatmap would put one enormous block where the machine
            was built and read as activity.
            """
            from timeline.data import artifact_map as _am

            tables = []
            for artifact, entries in _am.TIMESTAMP_MAPPINGS.items():
                if _am.ARTIFACT_DB_MAPPING.get(artifact) != "registry_data.db":
                    continue
                for entry in entries:
                    if _am.is_key_time(entry):
                        continue
                    tables.append((entry[0], entry[1]))

            query_parts = []
            for table, date_col in tables:
                if self._table_exists("registry_data.db", table):
                    # Robust SQL: Filter out 'N/A' or empty dates at the database level to prevent NULL days
                    query_parts.append(f"""
                        SELECT DATE({date_col}) as day, STRFTIME('%H', {date_col}) as hour, COUNT(*) as c 
                        FROM {table} 
                        WHERE {date_col} IS NOT NULL AND {date_col} NOT IN ('', 'N/A', '0s')
                        GROUP BY day, hour
                    """)
            
            if not query_parts: return []
            
            union_sql = f"SELECT day, hour, SUM(c) as count FROM ({' UNION ALL '.join(query_parts)}) WHERE day BETWEEN DATE(?) AND DATE(?) GROUP BY day, hour ORDER BY day"
            return self._query_db("registry_data.db", union_sql, (start, end))

        with ThreadPoolExecutor(max_workers=11) as executor:
            fut_sys = executor.submit(fetch_system)
            fut_app = executor.submit(fetch_app)
            fut_sec = executor.submit(fetch_sec)
            fut_sap = executor.submit(fetch_srum_app)
            fut_snt = executor.submit(fetch_srum_net)
            fut_mft = executor.submit(fetch_mft)
            fut_pref = executor.submit(fetch_prefetch)
            fut_shim = executor.submit(fetch_shimcache)
            fut_amc = executor.submit(fetch_amcache)
            fut_recy = executor.submit(fetch_recycle)
            fut_lnk = executor.submit(fetch_lnk)
            fut_reg = executor.submit(fetch_artifacts_registry)
            
            # Consolidate results
            result['SystemLogs'] = fut_sys.result()
            result['ApplicationLogs'] = fut_app.result()
            result['SecurityLogs'] = fut_sec.result()
            result['srum_app'] = fut_sap.result()
            result['srum_net'] = fut_snt.result()
            result['mft_usn'] = fut_mft.result()
            
            # Individual Forensic Keys
            result['prefetch'] = fut_pref.result()
            result['shimcache'] = fut_shim.result()
            result['amcache'] = fut_amc.result()
            result['recyclebin'] = fut_recy.result()
            result['lnk'] = fut_lnk.result()
            result['registry_others'] = fut_reg.result()
        
        return json.dumps(result)
    
    # ──────────────────────────────────────────────
    # SLOT: Available databases check
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str)
    def openEventDetailDialog(self, event_json: str):
        """Slot to open the native Python QDialog for event details."""
        self.show_event_detail.emit(event_json)

    @pyqtSlot(result=str)
    def getAvailableDatabases(self) -> str:
        """Check which databases exist in the case directory."""
        dbs = [
            'Log_Claw.db', 'srum_data.db', 'mft_usn_correlated_analysis.db',
            'mft_claw_analysis.db', 'prefetch_data.db', 'LnkDB.db',
            'registry_data.db', 'shimcache.db', 'amcache.db',
            'recyclebin_analysis.db', 'USN_journal.db'
        ]
        available = {}
        for db in dbs:
            path = self._get_db_path(db)
            available[db] = path is not None
        return json.dumps(available)
