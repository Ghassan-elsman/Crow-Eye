"""
Time-Window Scanning Correlation Engine
Implements O(N) time-window scanning approach instead of O(N²) anchor-based correlation.

This module provides a new correlation strategy that:
1. Scans through time systematically from year 2000 in fixed intervals
2. Uses wing's time_window_minutes as the scanning window size
3. Handles any timestamp format automatically with robust indexing
4. Provides O(N) performance for large datasets
"""

import time
import sqlite3
import logging
import uuid
import fnmatch
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Iterator, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from .base_engine import BaseCorrelationEngine, EngineMetadata, FilterConfig
from .feather_loader import FeatherLoader
from .correlation_result import CorrelationResult, CorrelationMatch
from .weighted_scoring import WeightedScoringEngine
from .two_phase_correlation import (
    TimeWindow,
    WindowDataCollector,
    WindowDataStorage,
    TwoPhaseConfig,
    Phase1ErrorHandler
)

# Core identity fields across all artifact types (Requirement 6.3 - Performance optimization)
CORE_IDENTITY_FIELDS = [
    # Names (higher priority)
    'name', 'filename', 'executable_name', 'app_name', 'application',
    'fn_filename', 'Source_Name', 'original_filename', 'program_name',
    'display_name', 'product_name', 'Source', 'FileName', 'Name',
    'ProductName', 'FileDescription', 'OriginalFileName', 'value',
    'Value', 'entry_name', 'program', 'executable', 'Executable',
    'service_name', 'ServiceName', 'task_name', 'TaskName', 'process',
    'Process', 'application_name',
    # Paths (lower priority)
    'path', 'file_path', 'app_path', 'Local_Path', 'reconstructed_path',
    'original_path', 'lower_case_long_path', 'install_location',
    'root_dir_path', 'ShortcutTargetPath', 'Source_Path', 'folder_path',
    'registry_path', 'FullPath', 'Path', 'FilePath', 'LowerCaseLongPath',
    'focus_path', 'run_path', 'ExecutablePath', 'executable_path',
    'image_path', 'ImagePath', 'binary_path', 'BinaryPath',
    'full_path', 'application_path', 'program_path', 'command_line',
    'exe_path', 'exepath', 'target_path', 'TargetPath'
]
from .memory_manager import WindowMemoryManager
from .database_persistence import StreamingMatchWriter, ResultsDatabase
from .parallel_window_processor import ParallelWindowProcessor, ParallelProcessingStats
from .progress_tracking import ProgressTracker, ProgressListener, ProgressEvent, ProgressEventType
from .time_estimation import AdaptiveTimeEstimator
from .cancellation_support import EnhancedCancellationManager
from .time_window_config import TimeWindowScanningConfig
from .wing_config_adapter import WingConfigurationAdapter, adapt_wing_for_time_window_scanning
from .performance_monitor import PerformanceMonitor, ProcessingPhase, PhaseTimer, create_performance_monitor
from .performance_analysis import AdvancedPerformanceAnalyzer, create_performance_analyzer, generate_performance_report_summary
from .database_error_handler import DatabaseErrorHandler, RetryConfig, FallbackStrategy, DatabaseErrorType
from .timestamp_parser import ResilientTimestampParser, TimestampFormat, TimestampValidationRule
from .error_handling_coordinator import ErrorHandlingCoordinator, ErrorCategory, ErrorSeverity
from .semantic_rule_evaluator import SemanticRuleEvaluator, SemanticMatchResult
from ..wings.core.wing_model import Wing
from ..config.semantic_mapping import SemanticMappingManager
from ..optimization.optimization_components import (
    PerformanceProfiler,
    EmptyWindowDetector,
    MemoryMonitor,
    TimestampCache,
    TimestampFormatCache,
    TimestampParseCache,
    TimestampFormat
)
from ..optimization.performance_config import PerformanceConfig

# Initialize logger
logger = logging.getLogger(__name__)


@dataclass
class TimeRangeDetectionResult:
    """Result from automatic time range detection"""
    earliest_timestamp: datetime
    latest_timestamp: datetime
    total_span_days: float
    feather_ranges: Dict[str, Tuple[datetime, datetime]]
    detection_time_seconds: float
    warnings: List[str] = field(default_factory=list)
    
    def get_span_years(self) -> float:
        """Get time span in years"""
        return self.total_span_days / 365.25
    
    def is_reasonable_range(self, max_years: int = 10) -> bool:
        """Check if range is reasonable"""
        return self.get_span_years() <= max_years


@dataclass
class WindowProcessingStats:
    """Enhanced statistics for window processing with empty window tracking"""
    total_windows_generated: int = 0
    windows_with_data: int = 0
    empty_windows_skipped: int = 0
    
    # Timing breakdown
    time_range_detection_seconds: float = 0.0
    empty_window_check_time_seconds: float = 0.0
    actual_processing_time_seconds: float = 0.0
    
    # Efficiency metrics
    skip_rate_percentage: float = 0.0
    time_saved_by_skipping_seconds: float = 0.0
    
    def calculate_efficiency_metrics(self):
        """Calculate derived efficiency metrics"""
        if self.total_windows_generated > 0:
            self.skip_rate_percentage = (self.empty_windows_skipped / self.total_windows_generated) * 100
        else:
            self.skip_rate_percentage = 0.0
        
        # Estimate time saved: assume each empty window would have taken 50ms if fully processed
        # vs <1ms with quick check
        estimated_full_processing_time_per_window = 0.050  # 50ms
        actual_quick_check_time_per_window = 0.001  # 1ms
        time_saved_per_empty_window = estimated_full_processing_time_per_window - actual_quick_check_time_per_window
        self.time_saved_by_skipping_seconds = self.empty_windows_skipped * time_saved_per_empty_window
    
    def get_efficiency_summary(self) -> str:
        """Get human-readable efficiency summary"""
        return (
            f"Processed {self.windows_with_data:,} windows with data, "
            f"skipped {self.empty_windows_skipped:,} empty windows "
            f"({self.skip_rate_percentage:.1f}% skip rate), "
            f"saved ~{self.time_saved_by_skipping_seconds:.1f}s"
        )


class OptimizedFeatherQuery:
    """Optimized querying for time windows with robust timestamp handling and error resilience"""
    
    def __init__(self, feather_loader: FeatherLoader, debug_mode: bool = False, profiler: Optional[PerformanceProfiler] = None):
        self.loader = feather_loader
        self.timestamp_format = None
        self.debug_mode = debug_mode
        self.profiler = profiler  # Optional profiler for performance tracking (Requirements 1.1)
        
        # Support multiple timestamp columns per feather (e.g., created, modified, accessed)
        self.timestamp_columns = []  # List of timestamp column names
        self.timestamp_column = None  # Primary timestamp column (for backward compatibility)
        
        # Initialize resilient timestamp parser
        validation_rules = TimestampValidationRule(
            min_year=1970,
            max_year=2100,
            allow_future_dates=True,
            max_future_days=365
        )
        
        self.timestamp_parser = ResilientTimestampParser(
            validation_rules=validation_rules,
            debug_mode=debug_mode
        )
        
        # Timestamp caching for optimization (Requirements 7.1, 7.2, 7.5)
        from ..optimization.optimization_components import TimestampParseCache
        self.timestamp_parse_cache = TimestampParseCache(max_size=10000)
        
        # Initialize database error handler
        retry_config = RetryConfig(
            max_retries=3,
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            retry_on_error_types=[
                DatabaseErrorType.CONNECTION_FAILED,
                DatabaseErrorType.DATABASE_LOCKED,
                DatabaseErrorType.TIMEOUT
            ]
        )
        
        fallback_strategy = FallbackStrategy(
            skip_unavailable_feathers=True,
            use_cached_results=True,
            continue_with_partial_data=True,
            log_fallback_actions=True
        )
        
        self.error_handler = DatabaseErrorHandler(
            retry_config=retry_config,
            fallback_strategy=fallback_strategy,
            debug_mode=debug_mode
        )
        
        # Cache for timestamp range (min/max timestamps)
        self._timestamp_range_cache: Optional[Tuple[Optional[datetime], Optional[datetime]]] = None
        self._timestamp_range_cached = False
        
        # Cache for query results (for overlapping time windows) with LRU eviction
        self._query_result_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_access_order: List[str] = []  # Track access order for LRU eviction
        self._max_cache_size = 100  # Limit cache entry count
        self._max_cache_size_mb = 512  # Limit cache memory size (Requirements 2.4, 2.5)
        self._current_cache_size_mb = 0.0  # Track current cache size in MB
        
        # Cache statistics (Requirements 2.4, 2.5)
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_requests': 0
        }
        
        # Batching statistics (Requirements 2.3)
        self._batch_stats = {
            'total_batch_calls': 0,
            'total_ranges_requested': 0,
            'total_groups_detected': 0,
            'total_queries_executed': 0,
            'ranges_batched': 0,
            'ranges_queried_individually': 0
        }
        
        # Initialize with error handling
        self._detect_and_index_timestamps()
    
    def _detect_and_index_timestamps(self):
        """Detect timestamp columns and format, then ensure proper indexing with error handling"""
        def detect_operation(connection):
            # Try to detect timestamp columns using multiple methods
            timestamp_detected = False
            
            # Method 1: Try forensic patterns if detect_columns exists
            if hasattr(self.loader, 'detect_columns'):
                try:
                    detected_cols = self.loader.detect_columns()
                    if detected_cols and hasattr(detected_cols, 'timestamp_columns') and detected_cols.timestamp_columns:
                        self.timestamp_columns = detected_cols.timestamp_columns
                        self.timestamp_column = self.timestamp_columns[0]  # Primary column
                        timestamp_detected = True
                        if self.debug_mode:
                            print(f"[OptimizedFeatherQuery] Found {len(self.timestamp_columns)} timestamp columns via forensic detection: {self.timestamp_columns}")
                except Exception as e:
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Forensic detection failed: {e}")
            
            # Method 2: Use resilient timestamp parser
            if not timestamp_detected:
                sample_records = self._get_sample_records_safe(connection, 100)
                if sample_records:
                    try:
                        timestamp_candidates = self.timestamp_parser.find_timestamp_columns(sample_records, sample_size=50)
                        
                        if timestamp_candidates:
                            # Get ALL candidates, not just the first one
                            self.timestamp_columns = [col for col, fmt, conf in timestamp_candidates]
                            self.timestamp_column = self.timestamp_columns[0]  # Primary column
                            detected_format = timestamp_candidates[0][1]
                            self.timestamp_format = detected_format.value
                            timestamp_detected = True
                            
                            if self.debug_mode:
                                print(f"[OptimizedFeatherQuery] Found {len(self.timestamp_columns)} timestamp columns via resilient parser: {self.timestamp_columns}")
                    except Exception as e:
                        if self.debug_mode:
                            print(f"[OptimizedFeatherQuery] Resilient parser failed: {e}")
            
            # Method 3: Final fallback detection using common column names
            if not timestamp_detected:
                self.timestamp_columns = self._fallback_timestamp_detection(connection)
                if self.timestamp_columns:
                    self.timestamp_column = self.timestamp_columns[0]  # Primary column
                    timestamp_detected = True
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Found {len(self.timestamp_columns)} timestamp columns via fallback: {self.timestamp_columns}")
            
            if self.timestamp_columns:
                # Detect timestamp format if not already detected
                if not hasattr(self, 'timestamp_format') or not self.timestamp_format:
                    self.timestamp_format = self._detect_timestamp_format_resilient(connection)
                
                # OPTIMIZATION: Ensure timestamp indexes are created for ALL timestamp columns
                # This is critical for performance of time range operations
                # Requirements 7.1, 7.2: Automatic index management
                for ts_col in self.timestamp_columns:
                    # Temporarily set timestamp_column for index creation
                    original_col = self.timestamp_column
                    self.timestamp_column = ts_col
                    index_created = self.ensure_timestamp_index()
                    self.timestamp_column = original_col
                    
                    if self.debug_mode:
                        if index_created:
                            print(f"[OptimizedFeatherQuery] Timestamp index ensured on {ts_col}")
                        else:
                            print(f"[OptimizedFeatherQuery] Failed to ensure timestamp index on {ts_col}")
            else:
                if self.debug_mode:
                    print("[OptimizedFeatherQuery] No timestamp columns found - queries will return empty results")
            
            return True
        
        try:
            self.error_handler.execute_with_retry(
                operation=detect_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="detect_and_index_timestamps"
            )
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Failed to detect timestamps: {e}")
            # Continue without timestamp detection - queries will return empty results
    
    def _detect_timestamp_format_resilient(self, connection) -> str:
        """Detect timestamp format using resilient parser"""
        def format_detection_operation(conn):
            sample_records = self._get_sample_records_safe(conn, 100)
            
            if not sample_records:
                return 'unknown'
            
            # Use resilient parser to analyze timestamp formats
            format_counts = {}
            successful_parses = 0
            total_attempts = 0
            
            for record in sample_records:
                if self.timestamp_column in record and record[self.timestamp_column] is not None:
                    total_attempts += 1
                    
                    result = self.timestamp_parser.parse_timestamp(record[self.timestamp_column])
                    if result.success:
                        successful_parses += 1
                        format_key = result.detected_format.value
                        format_counts[format_key] = format_counts.get(format_key, 0) + 1
            
            if format_counts:
                # Return most common format
                most_common_format = max(format_counts, key=format_counts.get)
                
                if self.debug_mode:
                    success_rate = (successful_parses / total_attempts * 100) if total_attempts > 0 else 0
                    print(f"[OptimizedFeatherQuery] Timestamp format detection: {most_common_format} "
                          f"(success rate: {success_rate:.1f}%, formats found: {format_counts})")
                
                return most_common_format
            else:
                return 'unknown'
        
        try:
            return self.error_handler.execute_with_retry(
                operation=format_detection_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="detect_timestamp_format_resilient"
            )
        except Exception:
            return 'unknown'
    
    def _fallback_timestamp_detection(self, connection) -> List[str]:
        """
        Fallback timestamp column detection with error handling.
        
        Returns:
            List of timestamp column names found (can be empty)
        """
        # Common timestamp column names from forensic artifacts (ordered by priority)
        common_names = [
            # Generic high-priority
            'timestamp', 'time', 'datetime', 'date_time', 'date',
            # Prefetch
            'last_run_time', 'last_run', 'run_time', 'execution_time',
            # ShimCache
            'last_modified', 'last_modified_readable', 'modified_time',
            # AmCache
            'install_date', 'link_date', 'file_time',
            # LNK & Jumplist
            'time_access', 'time_creation', 'time_modification',
            'access_time', 'creation_time', 'modification_time',
            # SRUM
            'timestamp_utc', 'time_stamp',
            # MFT & USN
            'created', 'modified', 'accessed', 'mft_modified',
            'si_creation_time', 'si_modification_time', 'si_access_time', 'si_mft_modified_time',
            'fn_creation_time', 'fn_modification_time', 'fn_access_time', 'fn_mft_modified_time',
            # Event Logs
            'eventtimestamputc', 'event_time', 'generated_time',
            # Registry artifacts
            'last_write_time', 'last_write', 'write_time',
            'access_date', 'modified_date', 'created_date',
            # ShellBags specific
            'first_interaction', 'last_interaction',
            # Generic variations
            'created_time', 'modified_time', 'accessed_time',
            'create_time', 'modify_time', 'access_time'
        ]
        
        try:
            # Get column names from the table
            cursor = connection.cursor()
            table_name = self.loader.current_table
            if not table_name:
                # Try to find the main data table
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'feather_metadata'")
                tables = [row[0] for row in cursor.fetchall()]
                if tables:
                    table_name = tables[0]
                else:
                    return []
            
            cursor.execute(f"PRAGMA table_info({table_name})")
            all_columns = [(row[1], row[2]) for row in cursor.fetchall()]  # (name, type)
            column_names_lower = [col[0].lower() for col in all_columns]
            
            if self.debug_mode:
                feather_id = getattr(self.loader, 'feather_id', 'unknown')
                print(f"[OptimizedFeatherQuery] {feather_id} - Available columns: {[col[0] for col in all_columns]}")
            
            timestamp_columns_found = []
            
            # Check for exact matches first (case-insensitive)
            for common_name in common_names:
                if common_name.lower() in column_names_lower:
                    # Get the actual column name (preserve case)
                    idx = column_names_lower.index(common_name.lower())
                    actual_name = all_columns[idx][0]
                    if actual_name not in timestamp_columns_found:
                        timestamp_columns_found.append(actual_name)
            
            # Check for partial matches - prioritize columns with timestamp-like patterns
            for col_name, col_type in all_columns:
                col_lower = col_name.lower()
                # Skip obviously non-timestamp columns
                if any(skip in col_lower for skip in ['id', 'count', 'size', 'length', 'number', 'index', 'key', 'value', 'path', 'name', 'type', 'flag']):
                    continue
                # Look for timestamp indicators
                if any(pattern in col_lower for pattern in ['time', 'date', 'stamp', 'created', 'modified', 'accessed', 'write', 'interaction']):
                    if col_name not in timestamp_columns_found:
                        timestamp_columns_found.append(col_name)
            
            if timestamp_columns_found:
                if self.debug_mode:
                    feather_id = getattr(self.loader, 'feather_id', 'unknown')
                    print(f"[OptimizedFeatherQuery] {feather_id} - Found {len(timestamp_columns_found)} timestamp columns: {timestamp_columns_found}")
                return timestamp_columns_found
            
            if self.debug_mode:
                feather_id = getattr(self.loader, 'feather_id', 'unknown')
                print(f"[OptimizedFeatherQuery] {feather_id} - No timestamp columns found in {len(all_columns)} columns")
                        
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Fallback timestamp detection failed: {e}")
        
        return []
    
    def _detect_timestamp_format(self, connection) -> str:
        """Detect timestamp format from sample records with error handling"""
        def format_detection_operation(conn):
            sample_records = self._get_sample_records_safe(conn, 100)
            formats_found = set()
            
            for record in sample_records:
                if self.timestamp_column in record and record[self.timestamp_column]:
                    timestamp_value = record[self.timestamp_column]
                    detected_format = self._identify_timestamp_format(timestamp_value)
                    if detected_format:
                        formats_found.add(detected_format)
            
            # Return most common format or 'mixed' if multiple formats
            return list(formats_found)[0] if len(formats_found) == 1 else 'mixed'
        
        try:
            return self.error_handler.execute_with_retry(
                operation=format_detection_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="detect_timestamp_format"
            )
        except Exception:
            return 'unknown'
    
    def _get_sample_records_safe(self, connection, limit: int) -> List[Dict[str, Any]]:
        """Safely get sample records with error handling"""
        try:
            cursor = connection.cursor()
            cursor.execute(f"SELECT * FROM {self.loader.current_table} LIMIT ?", (limit,))
            
            # Convert rows to dictionaries
            columns = [description[0] for description in cursor.description]
            records = []
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                records.append(record)
            
            return records
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Failed to get sample records: {e}")
            return []
    
    def _create_universal_timestamp_index(self, connection):
        """Create index that works with any timestamp format with error handling"""
        if not self.timestamp_column:
            return
        
        # Create index on timestamp column regardless of format
        # SQLite can index text, numeric, or datetime columns efficiently
        index_name = f"idx_timewindow_{self.timestamp_column}"
        
        try:
            connection.execute(f"""
                CREATE INDEX IF NOT EXISTS {index_name} 
                ON {self.loader.current_table} ({self.timestamp_column})
            """)
            connection.commit()
            
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Created timestamp index on {self.timestamp_column}")
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Warning: Could not create index on {self.timestamp_column}: {e}")
    
    def _identify_timestamp_format(self, timestamp_value: Any) -> Optional[str]:
        """Identify the format of a timestamp value"""
        if isinstance(timestamp_value, (int, float)):
            # Unix timestamp (seconds or milliseconds)
            if timestamp_value > 1000000000000:  # Milliseconds
                return 'unix_ms'
            elif timestamp_value > 1000000000:  # Seconds
                return 'unix_s'
            else:
                return 'numeric'
        
        elif isinstance(timestamp_value, str):
            # Try common string formats
            if 'T' in timestamp_value and 'Z' in timestamp_value:
                return 'iso8601'
            elif '-' in timestamp_value and ':' in timestamp_value:
                return 'datetime_string'
            elif '/' in timestamp_value:
                return 'date_slash'
            else:
                return 'string_unknown'
        
        return None
    
    def query_time_range(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """Optimized time range query that handles any timestamp format with error resilience and caching"""
        # Start profiling if profiler is available (Requirements 1.1, 1.4)
        if self.profiler:
            self.profiler.start_operation("query_time_range")
        
        try:
            if not self.timestamp_column:
                return []
            
            # Track cache request (Requirements 2.4)
            cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
            self._cache_stats['total_requests'] += 1
            
            # OPTIMIZATION: Check cache first for overlapping time windows
            if cache_key in self._query_result_cache:
                # Cache hit - update statistics and LRU order (Requirements 2.4, 2.5)
                self._cache_stats['hits'] += 1
                
                # Move to end of access order (most recently used)
                if cache_key in self._cache_access_order:
                    self._cache_access_order.remove(cache_key)
                self._cache_access_order.append(cache_key)
                
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Cache hit for time range {start_time} to {end_time}")
                return self._query_result_cache[cache_key]
            
            # Cache miss - track statistics (Requirements 2.4)
            self._cache_stats['misses'] += 1
            
            def query_operation(connection):
                # Convert datetime objects to format that matches the database
                start_value = self._convert_datetime_for_query(start_time)
                end_value = self._convert_datetime_for_query(end_time)
                
                # Build WHERE clause for multiple timestamp columns (OR condition)
                # This allows records to match if ANY timestamp column falls in the range
                if self.timestamp_columns and len(self.timestamp_columns) > 1:
                    # Multiple timestamp columns - check all with OR
                    where_conditions = []
                    for ts_col in self.timestamp_columns:
                        where_conditions.append(f"({ts_col} >= ? AND {ts_col} <= ?)")
                    where_clause = " OR ".join(where_conditions)
                    
                    # Build parameter list (start, end for each column)
                    params = []
                    for _ in self.timestamp_columns:
                        params.extend([start_value, end_value])
                    
                    query = f"""
                        SELECT * FROM {self.loader.current_table}
                        WHERE {where_clause}
                        ORDER BY {self.timestamp_columns[0]}
                    """
                elif self.timestamp_columns and len(self.timestamp_columns) == 1:
                    # Single column in list
                    query = f"""
                        SELECT * FROM {self.loader.current_table}
                        WHERE {self.timestamp_columns[0]} >= ? AND {self.timestamp_columns[0]} <= ?
                        ORDER BY {self.timestamp_columns[0]}
                    """
                    params = [start_value, end_value]
                elif self.timestamp_column:
                    # Fallback to primary timestamp column
                    query = f"""
                        SELECT * FROM {self.loader.current_table}
                        WHERE {self.timestamp_column} >= ? AND {self.timestamp_column} <= ?
                        ORDER BY {self.timestamp_column}
                    """
                    params = [start_value, end_value]
                else:
                    # No timestamp columns - return empty results
                    return []
                
                cursor = connection.cursor()
                cursor.execute(query, params)
                
                # Convert rows to dictionaries
                columns = [description[0] for description in cursor.description]
                records = []
                for row in cursor.fetchall():
                    record = dict(zip(columns, row))
                    records.append(record)
                
                return records
            
            try:
                results = self.error_handler.execute_with_retry(
                    operation=query_operation,
                    feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                    database_path=self.loader.database_path,
                    operation_name="query_time_range"
                )
                
                # OPTIMIZATION: Cache results with LRU eviction (Requirements 2.4, 2.5)
                result_size_mb = self._estimate_result_size_mb(results)
                
                # Check if we need to evict entries before caching
                if (self._current_cache_size_mb + result_size_mb > self._max_cache_size_mb or
                    len(self._query_result_cache) >= self._max_cache_size):
                    
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Cache limit reached, evicting LRU entries")
                    
                    # Evict LRU entries to make room
                    self._evict_lru_cache_entries(self._max_cache_size_mb - result_size_mb)
                
                # Add to cache if there's room
                if (self._current_cache_size_mb + result_size_mb <= self._max_cache_size_mb and
                    len(self._query_result_cache) < self._max_cache_size):
                    
                    self._query_result_cache[cache_key] = results
                    self._cache_access_order.append(cache_key)
                    self._current_cache_size_mb += result_size_mb
                    
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Cached query result (size: {result_size_mb:.2f} MB, "
                              f"total cache: {self._current_cache_size_mb:.2f} MB)")
                elif self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Result too large to cache ({result_size_mb:.2f} MB)")
                
                return results
                
            except Exception as e:
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Query failed for range {start_time} to {end_time}: {e}")
                return []  # Return empty list on failure
        finally:
            # End profiling if profiler is available (Requirements 1.1, 1.3)
            if self.profiler:
                try:
                    self.profiler.end_operation("query_time_range")
                except Exception:
                    pass  # Silently ignore profiler errors
    
    def _convert_datetime_for_query(self, dt: datetime) -> Any:
        """
        Convert datetime to format that matches database timestamp format.
        
        CRITICAL: This must match the exact format stored in the database,
        otherwise range queries will fail to find records.
        """
        if not self.timestamp_format or self.timestamp_format == 'unknown':
            # Try multiple formats to ensure we don't miss data
            # This is a fallback for when format detection fails
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] WARNING: Unknown timestamp format, trying multiple formats")
            # Default to ISO format as it's most common
            return dt.isoformat()
        
        if self.timestamp_format == 'unix_s':
            return int(dt.timestamp())
        elif self.timestamp_format == 'unix_ms':
            return int(dt.timestamp() * 1000)
        elif self.timestamp_format == 'iso8601':
            return dt.isoformat() + 'Z'
        elif self.timestamp_format in ['datetime_string', 'string_unknown']:
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        elif self.timestamp_format == 'date_slash':
            return dt.strftime('%m/%d/%Y %H:%M:%S')
        elif self.timestamp_format == 'mixed':
            # For mixed formats, use ISO as it's most flexible
            return dt.isoformat()
        else:
            # Fallback: try ISO format
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] WARNING: Unhandled timestamp format '{self.timestamp_format}', using ISO")
            return dt.isoformat()
    
    def get_timestamp_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Get the min/max timestamp range from this feather with error handling and caching.
        
        OPTIMIZATION: 
        - Results are cached after first query to avoid repeated MIN/MAX queries
        - Works directly with numeric timestamps (Unix epoch) for maximum speed
        - No timestamp format parsing needed for range detection
        
        Returns:
            Tuple of (min_timestamp, max_timestamp) or (None, None) if no timestamps found
        """
        if not self.timestamp_column:
            return None, None
        
        # OPTIMIZATION: Return cached result if available
        if self._timestamp_range_cached:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Using cached timestamp range: {self._timestamp_range_cache}")
            return self._timestamp_range_cache
        
        def range_operation(connection):
            # OPTIMIZATION: Try to query numeric timestamps directly first (fast path)
            # This works for Unix timestamps (seconds/milliseconds) and is much faster
            try:
                query = f"""
                    SELECT MIN({self.timestamp_column}), MAX({self.timestamp_column})
                    FROM {self.loader.current_table}
                    WHERE {self.timestamp_column} IS NOT NULL
                """
                cursor = connection.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                
                if result and result[0] is not None and result[1] is not None:
                    min_val, max_val = result[0], result[1]
                    
                    # Fast conversion: Check if values are numeric (int or float)
                    if isinstance(min_val, (int, float)) and isinstance(max_val, (int, float)):
                        # Fast path: Direct numeric conversion
                        # If value > 1 billion, it's likely milliseconds (after year 2001)
                        try:
                            if min_val > 1000000000000:
                                min_dt = datetime.fromtimestamp(min_val / 1000)
                            elif min_val > 1000000000:
                                min_dt = datetime.fromtimestamp(min_val)
                            else:
                                # Fallback to parser for unusual formats
                                min_dt = self._parse_timestamp_value(min_val)
                            
                            if max_val > 1000000000000:
                                max_dt = datetime.fromtimestamp(max_val / 1000)
                            elif max_val > 1000000000:
                                max_dt = datetime.fromtimestamp(max_val)
                            else:
                                # Fallback to parser for unusual formats
                                max_dt = self._parse_timestamp_value(max_val)
                            
                            if min_dt and max_dt:
                                return min_dt, max_dt
                        except (ValueError, OSError, OverflowError) as e:
                            if self.debug_mode:
                                print(f"[OptimizedFeatherQuery] Fast timestamp conversion failed: {e}, using parser")
                    
                    # Slow path: Use full parser for string timestamps or conversion failures
                    min_dt = self._parse_timestamp_value(min_val)
                    max_dt = self._parse_timestamp_value(max_val)
                    return min_dt, max_dt
                
            except Exception as e:
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Range query error: {e}")
            
            return None, None
        
        try:
            result = self.error_handler.execute_with_retry(
                operation=range_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="get_timestamp_range"
            )
            
            # OPTIMIZATION: Cache the result for future calls
            self._timestamp_range_cache = result
            self._timestamp_range_cached = True
            
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Cached timestamp range: {result}")
            
            return result
            
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Could not get timestamp range: {e}")
            return None, None
    
    def _parse_timestamp_value(self, value: Any) -> Optional[datetime]:
        """
        Parse a timestamp value to datetime object using resilient parser.
        
        Uses caching to avoid redundant parsing and to skip known parse errors.
        Requirements: 7.2, 7.5
        """
        # Check if this is a known parse error
        if self.timestamp_parse_cache.is_known_error(value):
            return None
        
        # Check cache for successful parse
        cached_result = self.timestamp_parse_cache.get(value)
        if cached_result is not None:
            return cached_result.datetime_value
        
        # Parse the timestamp
        result = self.timestamp_parser.parse_timestamp(value)
        if result.success:
            # Cache successful parse
            self.timestamp_parse_cache.put_success(value, result.datetime_value, result.detected_format)
            return result.datetime_value
        
        # Fallback for edge cases not handled by resilient parser
        if isinstance(value, (int, float)):
            try:
                if value > 1000000000000:  # Milliseconds
                    dt = datetime.fromtimestamp(value / 1000)
                    # Cache successful fallback parse
                    from ..optimization.optimization_components import TimestampFormat
                    self.timestamp_parse_cache.put_success(value, dt, TimestampFormat.UNIX_MILLISECONDS)
                    return dt
                elif value > 1000000000:  # Seconds
                    dt = datetime.fromtimestamp(value)
                    # Cache successful fallback parse
                    from ..optimization.optimization_components import TimestampFormat
                    self.timestamp_parse_cache.put_success(value, dt, TimestampFormat.UNIX_SECONDS)
                    return dt
            except (ValueError, OSError):
                pass
        
        # Cache parse error to avoid retrying
        self.timestamp_parse_cache.put_error(value)
        return None
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get database error statistics for this feather"""
        return self.error_handler.get_error_statistics()
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for this feather"""
        feather_id = getattr(self.loader, 'feather_id', 'unknown')
        health_status = self.error_handler.get_feather_health_status()
        return health_status.get(feather_id, {'status': 'unknown'})
    
    def clear_query_cache(self):
        """
        Clear the query result cache.
        
        This can be useful to free memory or when data has been updated.
        """
        cache_size = len(self._query_result_cache)
        self._query_result_cache.clear()
        self._cache_access_order.clear()
        self._current_cache_size_mb = 0.0
        
        if self.debug_mode:
            print(f"[OptimizedFeatherQuery] Cleared query cache ({cache_size} entries)")
    
    def clear_timestamp_range_cache(self):
        """
        Clear the cached timestamp range.
        
        This should be called if the underlying data has been modified.
        """
        self._timestamp_range_cache = None
        self._timestamp_range_cached = False
        
        if self.debug_mode:
            print(f"[OptimizedFeatherQuery] Cleared timestamp range cache")
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about cache usage.
        
        Returns:
            Dictionary with cache statistics including:
            - query_cache_size: Number of cached query results
            - query_cache_max_size: Maximum cache size
            - query_cache_size_mb: Current cache size in MB
            - query_cache_max_size_mb: Maximum cache size in MB
            - cache_hit_rate: Percentage of cache hits
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - cache_evictions: Number of LRU evictions
            - timestamp_range_cached: Whether timestamp range is cached
        """
        hit_rate = 0.0
        if self._cache_stats['total_requests'] > 0:
            hit_rate = (self._cache_stats['hits'] / self._cache_stats['total_requests']) * 100
        
        return {
            'query_cache_size': len(self._query_result_cache),
            'query_cache_max_size': self._max_cache_size,
            'query_cache_size_mb': round(self._current_cache_size_mb, 2),
            'query_cache_max_size_mb': self._max_cache_size_mb,
            'query_cache_utilization_percent': (len(self._query_result_cache) / self._max_cache_size * 100) if self._max_cache_size > 0 else 0,
            'cache_hit_rate': round(hit_rate, 2),
            'cache_hits': self._cache_stats['hits'],
            'cache_misses': self._cache_stats['misses'],
            'cache_evictions': self._cache_stats['evictions'],
            'total_cache_requests': self._cache_stats['total_requests'],
            'timestamp_range_cached': self._timestamp_range_cached,
            'timestamp_range_value': self._timestamp_range_cache if self._timestamp_range_cached else None
        }
    
    def get_batch_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about query batching performance.
        
        Returns:
            Dictionary with batching statistics including:
            - total_batch_calls: Number of times batch_query_time_ranges was called
            - total_ranges_requested: Total number of time ranges requested
            - total_groups_detected: Number of consecutive groups detected
            - total_queries_executed: Actual number of database queries executed
            - ranges_batched: Number of ranges that were batched together
            - ranges_queried_individually: Number of ranges queried individually
            - batching_efficiency: Percentage of ranges that were batched
            - query_reduction: Percentage reduction in queries due to batching
        """
        stats = self._batch_stats.copy()
        
        # Calculate efficiency metrics
        if stats['total_ranges_requested'] > 0:
            stats['batching_efficiency'] = (stats['ranges_batched'] / stats['total_ranges_requested']) * 100
            stats['query_reduction'] = ((stats['total_ranges_requested'] - stats['total_queries_executed']) / stats['total_ranges_requested']) * 100
        else:
            stats['batching_efficiency'] = 0.0
            stats['query_reduction'] = 0.0
        
        return stats
    
    def _estimate_result_size_mb(self, results: List[Dict[str, Any]]) -> float:
        """
        Estimate the memory size of query results in MB.
        
        This uses sys.getsizeof for a rough estimate. It's not perfect but
        provides a reasonable approximation for cache size tracking.
        
        Args:
            results: List of query result dictionaries
            
        Returns:
            Estimated size in MB
        """
        import sys
        
        if not results:
            return 0.0
        
        # Estimate size of the list and its contents
        total_bytes = sys.getsizeof(results)
        
        # Sample a few records to estimate average record size
        sample_size = min(10, len(results))
        sample_bytes = sum(sys.getsizeof(results[i]) for i in range(sample_size))
        avg_record_bytes = sample_bytes / sample_size
        
        # Estimate total size
        total_bytes += avg_record_bytes * len(results)
        
        # Convert to MB
        return total_bytes / (1024 * 1024)
    
    def _evict_lru_cache_entries(self, target_size_mb: Optional[float] = None) -> int:
        """
        Evict least-recently-used cache entries to free memory.
        
        This implements LRU (Least Recently Used) eviction by removing the oldest
        accessed entries from the cache until the target size is reached.
        
        Requirements 2.5: LRU eviction when cache exceeds memory limits
        
        Args:
            target_size_mb: Target cache size in MB. If None, evicts until under max_cache_size_mb
            
        Returns:
            Number of entries evicted
        """
        if target_size_mb is None:
            target_size_mb = self._max_cache_size_mb * 0.8  # Evict to 80% of max
        
        evicted_count = 0
        
        # Evict entries from the front of the access order list (least recently used)
        while (self._current_cache_size_mb > target_size_mb and 
               self._cache_access_order and 
               len(self._query_result_cache) > 0):
            
            # Get the least recently used key
            lru_key = self._cache_access_order.pop(0)
            
            # Remove from cache if it exists
            if lru_key in self._query_result_cache:
                results = self._query_result_cache[lru_key]
                entry_size = self._estimate_result_size_mb(results)
                
                del self._query_result_cache[lru_key]
                self._current_cache_size_mb -= entry_size
                evicted_count += 1
                self._cache_stats['evictions'] += 1
                
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Evicted LRU cache entry (size: {entry_size:.2f} MB)")
        
        if self.debug_mode and evicted_count > 0:
            print(f"[OptimizedFeatherQuery] LRU eviction complete: {evicted_count} entries removed, "
                  f"cache size now {self._current_cache_size_mb:.2f} MB")
        
        return evicted_count
    
    def configure_cache(self, max_size_mb: Optional[int] = None, max_entries: Optional[int] = None) -> None:
        """
        Configure cache size limits.
        
        This allows dynamic adjustment of cache parameters for different workloads.
        
        Requirements 2.4, 2.5: Cache configuration parameters
        
        Args:
            max_size_mb: Maximum cache size in MB (default: 512)
            max_entries: Maximum number of cache entries (default: 100)
        """
        if max_size_mb is not None:
            self._max_cache_size_mb = max_size_mb
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Set max cache size to {max_size_mb} MB")
        
        if max_entries is not None:
            self._max_cache_size = max_entries
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Set max cache entries to {max_entries}")
        
        # Evict if current cache exceeds new limits
        if self._current_cache_size_mb > self._max_cache_size_mb:
            self._evict_lru_cache_entries()
        
        while len(self._query_result_cache) > self._max_cache_size:
            if self._cache_access_order:
                lru_key = self._cache_access_order.pop(0)
                if lru_key in self._query_result_cache:
                    results = self._query_result_cache[lru_key]
                    entry_size = self._estimate_result_size_mb(results)
                    del self._query_result_cache[lru_key]
                    self._current_cache_size_mb -= entry_size
                    self._cache_stats['evictions'] += 1
    
    def get_cache_hit_rate(self) -> float:
        """
        Get the cache hit rate as a percentage.
        
        Requirements 2.4: Track cache hit rate statistics
        
        Returns:
            Cache hit rate percentage (0-100)
        """
        if self._cache_stats['total_requests'] == 0:
            return 0.0
        
        return (self._cache_stats['hits'] / self._cache_stats['total_requests']) * 100
    
    def has_timestamp_index(self) -> bool:
        """
        Check if timestamp index exists on the timestamp column.
        
        Returns:
            True if index exists, False otherwise
        """
        if not self.timestamp_column:
            return False
        
        def check_index_operation(connection):
            try:
                cursor = connection.cursor()
                index_name = f"idx_timewindow_{self.timestamp_column}"
                
                # Query SQLite's index list
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='index' AND name=?
                """, (index_name,))
                
                result = cursor.fetchone()
                return result is not None
            except Exception as e:
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Error checking index: {e}")
                return False
        
        try:
            return self.error_handler.execute_with_retry(
                operation=check_index_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="has_timestamp_index"
            )
        except Exception:
            return False
    
    def create_timestamp_index(self) -> bool:
        """
        Create timestamp index if it doesn't exist.
        
        Returns:
            True if index was created or already exists, False on failure
        """
        if not self.timestamp_column:
            if self.debug_mode:
                print("[OptimizedFeatherQuery] Cannot create index: no timestamp column detected")
            return False
        
        def create_index_operation(connection):
            try:
                index_name = f"idx_timewindow_{self.timestamp_column}"
                
                connection.execute(f"""
                    CREATE INDEX IF NOT EXISTS {index_name} 
                    ON {self.loader.current_table} ({self.timestamp_column})
                """)
                connection.commit()
                
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Created/verified timestamp index on {self.timestamp_column}")
                
                return True
            except Exception as e:
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Failed to create index: {e}")
                return False
        
        try:
            return self.error_handler.execute_with_retry(
                operation=create_index_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="create_timestamp_index"
            )
        except Exception:
            return False
    
    def ensure_timestamp_index(self) -> bool:
        """
        Ensure timestamp index exists, creating it automatically if missing.
        
        This method checks for index existence and creates it if needed,
        providing automatic index management for optimal query performance.
        
        Requirements 2.1, 2.2: Automatic timestamp index creation
        
        Returns:
            True if index exists or was created successfully, False otherwise
        """
        if not self.timestamp_column:
            if self.debug_mode:
                print("[OptimizedFeatherQuery] Cannot ensure index: no timestamp column detected")
            return False
        
        # Check if index already exists
        if self.has_timestamp_index():
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Timestamp index already exists on {self.timestamp_column}")
            return True
        
        # Index doesn't exist, create it
        if self.debug_mode:
            print(f"[OptimizedFeatherQuery] Timestamp index missing, creating automatically on {self.timestamp_column}")
        
        success = self.create_timestamp_index()
        
        if success:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Successfully created timestamp index on {self.timestamp_column}")
        else:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Failed to create timestamp index on {self.timestamp_column}")
        
        return success
    
    def quick_count_in_range(self, start_time: datetime, end_time: datetime) -> int:
        """
        Quickly count records in time range using indexed COUNT(*) query.
        
        This method uses SELECT COUNT(*) with indexed timestamp range for fast
        empty window detection. Supports multiple timestamp columns with OR logic.
        Target performance: <1ms per check.
        
        CRITICAL: Returns -1 if no timestamp columns exist (can't check).
        Returns 1 on error to force full query (safer than assuming empty).
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            Number of records in the time range, -1 if can't check (no timestamps), or 1 on error
        """
        if not self.timestamp_column and not self.timestamp_columns:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Quick count skipped: no timestamp columns")
            return -1  # Return -1 to indicate "can't check" (not "has 1 record")
        
        def count_operation(connection):
            try:
                # Convert datetime objects to format that matches the database
                start_value = self._convert_datetime_for_query(start_time)
                end_value = self._convert_datetime_for_query(end_time)
                
                # Build WHERE clause for multiple timestamp columns (OR condition)
                if self.timestamp_columns and len(self.timestamp_columns) > 1:
                    # Multiple timestamp columns - check all with OR
                    where_conditions = []
                    for ts_col in self.timestamp_columns:
                        where_conditions.append(f"({ts_col} >= ? AND {ts_col} <= ?)")
                    where_clause = " OR ".join(where_conditions)
                    
                    # Build parameter list (start, end for each column)
                    params = []
                    for _ in self.timestamp_columns:
                        params.extend([start_value, end_value])
                    
                    query = f"""
                        SELECT COUNT(*) FROM {self.loader.current_table}
                        WHERE {where_clause}
                    """
                elif self.timestamp_columns and len(self.timestamp_columns) == 1:
                    # Single column in list
                    query = f"""
                        SELECT COUNT(*) FROM {self.loader.current_table}
                        WHERE {self.timestamp_columns[0]} >= ? AND {self.timestamp_columns[0]} <= ?
                    """
                    params = [start_value, end_value]
                elif self.timestamp_column:
                    # Fallback to primary timestamp column
                    query = f"""
                        SELECT COUNT(*) FROM {self.loader.current_table}
                        WHERE {self.timestamp_column} >= ? AND {self.timestamp_column} <= ?
                    """
                    params = [start_value, end_value]
                else:
                    # No timestamp columns - return 1 to force full query
                    return 1
                
                cursor = connection.cursor()
                cursor.execute(query, params)
                result = cursor.fetchone()
                
                count = result[0] if result else 0
                
                # Debug logging for troubleshooting
                if self.debug_mode and count == 0:
                    # Double-check: try to get total record count
                    cursor.execute(f"SELECT COUNT(*) FROM {self.loader.current_table}")
                    total = cursor.fetchone()[0]
                    if total > 0:
                        print(f"[OptimizedFeatherQuery] WARNING: Quick count returned 0 but table has {total} records")
                        print(f"[OptimizedFeatherQuery]   Range: {start_time} to {end_time}")
                        print(f"[OptimizedFeatherQuery]   Format: {self.timestamp_format}")
                        print(f"[OptimizedFeatherQuery]   Columns: {self.timestamp_columns if self.timestamp_columns else [self.timestamp_column]}")
                
                return count
            except Exception as e:
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Quick count failed for range {start_time} to {end_time}: {e}")
                # Fallback: return 1 to force full query (safer than assuming empty)
                return 1
        
        try:
            return self.error_handler.execute_with_retry(
                operation=count_operation,
                feather_id=getattr(self.loader, 'feather_id', 'unknown'),
                database_path=self.loader.database_path,
                operation_name="quick_count_in_range"
            )
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Quick count error: {e}")
            # Fallback: return 1 to force full query (safer than assuming empty)
            return 1
    
    def batch_query_time_ranges(self, time_ranges: List[Tuple[datetime, datetime]]) -> Dict[Tuple[datetime, datetime], List[Dict[str, Any]]]:
        """
        OPTIMIZATION: Batch query multiple time ranges in a single database operation.
        
        This method optimizes querying multiple consecutive time windows by combining
        them into fewer database queries, reducing query overhead. It detects groups
        of consecutive ranges and batches each group separately.
        
        Args:
            time_ranges: List of (start_time, end_time) tuples to query
            
        Returns:
            Dictionary mapping each time range to its query results
        """
        if not self.timestamp_column or not time_ranges:
            return {}
        
        # Update statistics
        self._batch_stats['total_batch_calls'] += 1
        self._batch_stats['total_ranges_requested'] += len(time_ranges)
        
        results = {}
        
        # Check cache first for all ranges (track statistics)
        uncached_ranges = []
        for time_range in time_ranges:
            start_time, end_time = time_range
            cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
            
            # Track cache request (Requirements 2.4)
            self._cache_stats['total_requests'] += 1
            
            if cache_key in self._query_result_cache:
                # Cache hit - update statistics and LRU order (Requirements 2.4, 2.5)
                self._cache_stats['hits'] += 1
                
                # Move to end of access order (most recently used)
                if cache_key in self._cache_access_order:
                    self._cache_access_order.remove(cache_key)
                self._cache_access_order.append(cache_key)
                
                results[time_range] = self._query_result_cache[cache_key]
            else:
                # Cache miss (Requirements 2.4)
                self._cache_stats['misses'] += 1
                uncached_ranges.append(time_range)
        
        if not uncached_ranges:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] All {len(time_ranges)} ranges found in cache")
            return results
        
        # Detect groups of consecutive ranges
        consecutive_groups = self._detect_consecutive_ranges(uncached_ranges)
        self._batch_stats['total_groups_detected'] += len(consecutive_groups)
        
        if self.debug_mode:
            print(f"[OptimizedFeatherQuery] Detected {len(consecutive_groups)} consecutive groups from {len(uncached_ranges)} uncached ranges")
        
        # Process each group
        for group in consecutive_groups:
            if len(group) > 1:
                # Batch query for consecutive ranges
                overall_start = min(r[0] for r in group)
                overall_end = max(r[1] for r in group)
                
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Batch querying {len(group)} consecutive ranges")
                
                all_records = self.query_time_range(overall_start, overall_end)
                self._batch_stats['total_queries_executed'] += 1
                self._batch_stats['ranges_batched'] += len(group)
                
                # Split records into individual time ranges
                for time_range in group:
                    start_time, end_time = time_range
                    range_records = [
                        record for record in all_records
                        if self._record_in_range(record, start_time, end_time)
                    ]
                    results[time_range] = range_records
                    
                    # Cache individual results with LRU eviction (Requirements 2.4, 2.5)
                    cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
                    result_size_mb = self._estimate_result_size_mb(range_records)
                    
                    # Check if we need to evict entries before caching
                    if (self._current_cache_size_mb + result_size_mb > self._max_cache_size_mb or
                        len(self._query_result_cache) >= self._max_cache_size):
                        self._evict_lru_cache_entries(self._max_cache_size_mb - result_size_mb)
                    
                    # Add to cache if there's room
                    if (self._current_cache_size_mb + result_size_mb <= self._max_cache_size_mb and
                        len(self._query_result_cache) < self._max_cache_size):
                        self._query_result_cache[cache_key] = range_records
                        self._cache_access_order.append(cache_key)
                        self._current_cache_size_mb += result_size_mb
            else:
                # Single range - query individually
                time_range = group[0]
                start_time, end_time = time_range
                
                if self.debug_mode:
                    print(f"[OptimizedFeatherQuery] Querying single range individually")
                
                results[time_range] = self.query_time_range(start_time, end_time)
                self._batch_stats['total_queries_executed'] += 1
                self._batch_stats['ranges_queried_individually'] += 1
        
        return results
    
    def _are_ranges_consecutive(self, time_ranges: List[Tuple[datetime, datetime]]) -> bool:
        """
        Check if time ranges are consecutive (no gaps between them).
        
        Args:
            time_ranges: List of (start_time, end_time) tuples
            
        Returns:
            True if ranges are consecutive, False otherwise
        """
        if len(time_ranges) < 2:
            return True
        
        # Sort ranges by start time
        sorted_ranges = sorted(time_ranges, key=lambda r: r[0])
        
        # Check if each range starts where the previous one ended
        for i in range(1, len(sorted_ranges)):
            prev_end = sorted_ranges[i-1][1]
            curr_start = sorted_ranges[i][0]
            
            # Allow small gaps (up to 1 second) for rounding
            gap = (curr_start - prev_end).total_seconds()
            if gap > 1:
                return False
        
        return True
    
    def _detect_consecutive_ranges(self, time_ranges: List[Tuple[datetime, datetime]]) -> List[List[Tuple[datetime, datetime]]]:
        """
        Detect groups of consecutive time ranges that can be batched together.
        
        This method analyzes a list of time ranges and groups consecutive ranges
        together. Consecutive ranges are those where each range starts where the
        previous one ended (allowing up to 1 second gap for rounding).
        
        Args:
            time_ranges: List of (start_time, end_time) tuples
            
        Returns:
            List of groups, where each group is a list of consecutive time ranges
            
        Example:
            Input: [(0-1), (1-2), (2-3), (5-6), (6-7)]
            Output: [[(0-1), (1-2), (2-3)], [(5-6), (6-7)]]
        """
        if not time_ranges:
            return []
        
        if len(time_ranges) == 1:
            return [time_ranges]
        
        # Sort ranges by start time
        sorted_ranges = sorted(time_ranges, key=lambda r: r[0])
        
        # Group consecutive ranges
        groups = []
        current_group = [sorted_ranges[0]]
        
        for i in range(1, len(sorted_ranges)):
            prev_end = current_group[-1][1]
            curr_start = sorted_ranges[i][0]
            
            # Check if consecutive (allow up to 1 second gap for rounding)
            gap = (curr_start - prev_end).total_seconds()
            
            if gap <= 1:
                # Consecutive - add to current group
                current_group.append(sorted_ranges[i])
            else:
                # Not consecutive - start new group
                groups.append(current_group)
                current_group = [sorted_ranges[i]]
        
        # Add the last group
        groups.append(current_group)
        
        return groups
    
    def _record_in_range(self, record: Dict[str, Any], start_time: datetime, end_time: datetime) -> bool:
        """
        Check if a record's timestamp falls within the given time range.
        
        Args:
            record: Record dictionary
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            True if record is in range, False otherwise
        """
        if self.timestamp_column not in record:
            return False
        
        timestamp_value = record[self.timestamp_column]
        record_time = self._parse_timestamp_value(timestamp_value)
        
        if not record_time:
            return False
        
        return start_time <= record_time <= end_time
    
    def cleanup(self):
        """Cleanup database connections and resources"""
        if hasattr(self, 'error_handler'):
            self.error_handler.cleanup()


class WindowQueryManager:
    """
    Manages efficient querying of feathers for time windows.
    
    Coordinates queries across multiple feathers and provides caching.
    Applies identity filters if configured.
    """
    
    def __init__(self, feather_queries: Dict[str, OptimizedFeatherQuery], 
                 filters: Optional[FilterConfig] = None,
                 debug_mode: bool = False):
        self.feather_queries = feather_queries
        self.filters = filters
        self.debug_mode = debug_mode
        self.query_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.cache_hits = 0
        self.cache_misses = 0
    
    def query_window(self, window: TimeWindow, progress_tracker: Optional['ProgressTracker'] = None) -> TimeWindow:
        """
        Query all feathers for records in the given time window.
        Applies identity filters if configured.
        
        Args:
            window: TimeWindow to populate with records
            progress_tracker: Optional progress tracker for reporting query progress
            
        Returns:
            TimeWindow populated with records from all feathers
        """
        total_feathers = len(self.feather_queries)
        feathers_queried = 0
        total_records = 0
        total_filtered = 0  # Track filtered records
        query_start_time = time.time()
        
        # Report query start
        if progress_tracker:
            progress_tracker.report_database_query_start(window.window_id, total_feathers)
        
        for feather_id, query_manager in self.feather_queries.items():
            # Create cache key
            cache_key = f"{feather_id}_{window.start_time.isoformat()}_{window.end_time.isoformat()}"
            
            # Check cache first
            if cache_key in self.query_cache:
                records = self.query_cache[cache_key]
                self.cache_hits += 1
            else:
                # Query feather
                records = query_manager.query_time_range(window.start_time, window.end_time)
                
                # Cache results (limit cache size)
                if len(self.query_cache) < 1000:  # Limit cache size
                    self.query_cache[cache_key] = records
                
                self.cache_misses += 1
            
            # APPLY IDENTITY FILTERS
            if records and self.filters and self.filters.identity_filters:
                original_count = len(records)
                records = [r for r in records if not self._should_filter_record(r)]
                filtered_count = original_count - len(records)
                total_filtered += filtered_count
                
                if filtered_count > 0 and self.debug_mode:
                    print(f"[WindowQueryManager] Filtered {filtered_count}/{original_count} records from {feather_id}")
            
            # Add records to window
            if records:
                window.add_records(feather_id, records)
                total_records += len(records)
            
            feathers_queried += 1
            
            # Report progress for this feather
            if progress_tracker:
                progress_tracker.report_database_query_progress(
                    window.window_id, feather_id, feathers_queried, total_feathers, len(records) if records else 0
                )
        
        # Report query completion
        query_time = time.time() - query_start_time
        if progress_tracker:
            progress_tracker.report_database_query_complete(
                window.window_id, total_feathers, total_records, query_time
            )
        
        # Log filter statistics
        if total_filtered > 0:
            print(f"[WindowQueryManager] Identity filters excluded {total_filtered:,} records from window {window.window_id}")
        
        return window
    
    def quick_check_window_has_records(self, window: TimeWindow) -> bool:
        """
        Quickly check if window has any records without performing full query.
        
        Uses COUNT(*) with indexed timestamp range for fast empty window detection.
        This method checks all feathers and returns True if ANY feather has records
        in the window. Feathers without timestamp columns are skipped.
        Target performance: <1ms per window.
        
        Args:
            window: TimeWindow to check
            
        Returns:
            True if window has at least one record in any feather, False if all feathers are empty
        """
        feathers_checked = 0
        
        for feather_id, query_manager in self.feather_queries.items():
            # Quick count query using index
            count = query_manager.quick_count_in_range(window.start_time, window.end_time)
            
            # -1 means feather has no timestamp columns, skip it
            if count == -1:
                continue
            
            feathers_checked += 1
            
            if count > 0:
                # Found data in this feather, no need to check others
                return True
        
        # If no feathers could be checked (all lack timestamps), assume has data (safe fallback)
        if feathers_checked == 0:
            return True
        
        # No data found in any feather that could be checked
        return False
    
    def get_overall_time_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Get the overall time range across all feathers.
        
        Returns:
            Tuple of (earliest_time, latest_time) across all feathers
        """
        earliest_times = []
        latest_times = []
        
        for query_manager in self.feather_queries.values():
            min_time, max_time = query_manager.get_timestamp_range()
            if min_time:
                earliest_times.append(min_time)
            if max_time:
                latest_times.append(max_time)
        
        earliest = min(earliest_times) if earliest_times else None
        latest = max(latest_times) if latest_times else None
        
        return earliest, latest
    
    def _should_filter_record(self, record: Dict[str, Any]) -> bool:
        """
        Check if a record should be filtered out based on identity filters.
        
        OPTIMIZATION: Normalized identity values and filters are pre-calculated
        to avoid redundant string operations in the window loop.
        """
        if not self.filters or not self.filters.identity_filters:
            return False  # No filters, keep all records
        
        # Use global CORE_IDENTITY_FIELDS for performance
        identity_values = []
        for field in CORE_IDENTITY_FIELDS:
            if field in record and record[field]:
                identity_values.append(str(record[field]))
        
        # If no identity information found, keep the record (don't filter out)
        if not identity_values:
            return False
            
        # Optimization: pre-calculate normalized values if not case-sensitive
        if not self.filters.case_sensitive:
            identity_values = [v.lower() for v in identity_values]
        
        # Check if any identity value matches the filter patterns
        for filter_pattern in self.filters.identity_filters:
            pattern_cmp = filter_pattern if self.filters.case_sensitive else filter_pattern.lower()
            
            # Check if pattern matches any identity value
            for value in identity_values:
                if fnmatch.fnmatch(value, pattern_cmp):
                    return False  # Match found, keep record
        
        # No match found in any pattern, filter out record (exclude)
        return True
        
        # No match found, filter out
        return True
    
    def clear_cache(self):
        """Clear the query cache"""
        self.query_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache performance statistics"""
        total_queries = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_queries * 100) if total_queries > 0 else 0
        
        return {
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate_percent': hit_rate,
            'cache_size': len(self.query_cache)
        }
    
    def get_batch_statistics(self) -> Dict[str, Any]:
        """
        Get aggregated batching statistics from all feather queries.
        
        Returns:
            Dictionary with aggregated batching statistics across all feathers
        """
        aggregated_stats = {
            'total_batch_calls': 0,
            'total_ranges_requested': 0,
            'total_groups_detected': 0,
            'total_queries_executed': 0,
            'ranges_batched': 0,
            'ranges_queried_individually': 0
        }
        
        # Aggregate statistics from all feather queries
        for feather_id, query_manager in self.feather_queries.items():
            feather_stats = query_manager.get_batch_statistics()
            aggregated_stats['total_batch_calls'] += feather_stats['total_batch_calls']
            aggregated_stats['total_ranges_requested'] += feather_stats['total_ranges_requested']
            aggregated_stats['total_groups_detected'] += feather_stats['total_groups_detected']
            aggregated_stats['total_queries_executed'] += feather_stats['total_queries_executed']
            aggregated_stats['ranges_batched'] += feather_stats['ranges_batched']
            aggregated_stats['ranges_queried_individually'] += feather_stats['ranges_queried_individually']
        
        # Calculate efficiency metrics
        if aggregated_stats['total_ranges_requested'] > 0:
            aggregated_stats['batching_efficiency'] = (aggregated_stats['ranges_batched'] / aggregated_stats['total_ranges_requested']) * 100
            aggregated_stats['query_reduction'] = ((aggregated_stats['total_ranges_requested'] - aggregated_stats['total_queries_executed']) / aggregated_stats['total_ranges_requested']) * 100
        else:
            aggregated_stats['batching_efficiency'] = 0.0
            aggregated_stats['query_reduction'] = 0.0
        
        return aggregated_stats


class TimeWindowScanningEngine(BaseCorrelationEngine):
    """
    Time-Window Scanning Correlation Engine.
    
    This engine scans through time systematically in fixed intervals to find correlations.
    Provides O(N) performance compared to O(N²) anchor-based approach.
    
    Key features:
    - Uses wing's time_window_minutes as scanning window size
    - Handles any timestamp format automatically
    - Creates optimized indexes for fast queries
    - Scans from year 2000 in configurable intervals
    
    Complexity: O(N) where N is the number of records
    
    Best for:
    - Large datasets (>1,000 records)
    - Performance-critical environments
    - Systematic temporal analysis
    - Memory-constrained systems
    
    Example:
        engine = TimeWindowScanningEngine(
            config=pipeline_config,
            filters=FilterConfig(
                time_period_start=datetime(2024, 1, 1),
                time_period_end=datetime(2024, 12, 31)
            )
        )
        result = engine.execute([wing])
    """
    
    @classmethod
    def create_with_config(cls, 
                          scanning_config: TimeWindowScanningConfig,
                          filters: Optional[FilterConfig] = None) -> 'TimeWindowScanningEngine':
        """
        Create TimeWindowScanningEngine with specific configuration.
        
        Args:
            scanning_config: Time-window scanning configuration
            filters: Optional filter configuration
            
        Returns:
            TimeWindowScanningEngine instance
        """
        return cls(config=scanning_config, filters=filters, debug_mode=scanning_config.debug_mode)
    
    @classmethod
    def create_for_wing(cls,
                       wing: Any,
                       base_config: Optional[TimeWindowScanningConfig] = None,
                       filters: Optional[FilterConfig] = None) -> 'TimeWindowScanningEngine':
        """
        Create TimeWindowScanningEngine adapted for specific wing.
        
        Args:
            wing: Wing configuration object
            base_config: Base configuration to adapt (uses default if None)
            filters: Optional filter configuration
            
        Returns:
            TimeWindowScanningEngine instance adapted for the wing
        """
        # Adapt configuration for wing
        adaptation_result = adapt_wing_for_time_window_scanning(wing, base_config)
        
        # Create engine with adapted configuration
        engine = cls.create_with_config(adaptation_result.adapted_config, filters)
        
        # Log any warnings or incompatibilities
        if adaptation_result.warnings:
            for warning in adaptation_result.warnings:
                print(f"[TimeWindow] Wing Adaptation Warning: {warning}")
        
        if adaptation_result.incompatibilities:
            for incompatibility in adaptation_result.incompatibilities:
                print(f"[TimeWindow] Wing Adaptation Error: {incompatibility}")
        
        return engine
    
    def __init__(self, config: Any, filters: Optional[FilterConfig] = None, debug_mode: bool = True,
                 scoring_integration: Optional['IScoringIntegration'] = None,
                 mapping_integration: Optional['ISemanticMappingIntegration'] = None,
                 two_phase_config: Optional['TwoPhaseConfig'] = None,
                 performance_config: Optional['PerformanceConfig'] = None):
        """
        Initialize Time-Window Scanning Engine.
        
        Args:
            config: Pipeline configuration object or TimeWindowScanningConfig
            filters: Optional filter configuration
            debug_mode: Enable debug logging
            scoring_integration: Optional scoring integration (for dependency injection)
            mapping_integration: Optional semantic mapping integration (for dependency injection)
            two_phase_config: Optional two-phase configuration
            performance_config: Optional performance configuration for optimization tuning (Requirements 8.1, 8.2, 8.3, 8.4)
        """
        super().__init__(config, filters)
        
        # Task 21 & 23: Initialize and validate performance configuration (Requirements 8.1, 8.2, 8.3, 8.4, 8.5)
        if performance_config is not None:
            self.performance_config = performance_config
        else:
            # Use safe defaults if not provided
            from ..optimization.performance_config import PerformanceConfig
            self.performance_config = PerformanceConfig.get_safe_defaults()
        
        # Validate performance configuration on initialization (Requirement 8.5)
        validation_errors = self.performance_config.validate()
        if validation_errors:
            logger.warning(
                f"[Time-Window Engine] Invalid performance configuration: {', '.join(validation_errors)}. "
                f"Using safe defaults."
            )
            from ..optimization.performance_config import PerformanceConfig
            self.performance_config = PerformanceConfig.get_safe_defaults()
        
        if debug_mode:
            logger.info(f"[Time-Window Engine] Performance configuration loaded: "
                       f"window_size={self.performance_config.window_size_minutes}min, "
                       f"max_workers={self.performance_config.max_workers}, "
                       f"memory_threshold={self.performance_config.memory_threshold_mb}MB, "
                       f"query_cache={self.performance_config.query_cache_size_mb}MB, "
                       f"profiling={'enabled' if self.performance_config.enable_profiling else 'disabled'}, "
                       f"empty_window_skipping={'enabled' if self.performance_config.enable_empty_window_skipping else 'disabled'}")
        
        # Initialize centralized score configuration manager
        # Requirements: 7.2, 8.3
        from ..config.score_configuration_manager import ScoreConfigurationManager
        self.score_config_manager = ScoreConfigurationManager()
        
        # Handle configuration - can be pipeline config or TimeWindowScanningConfig
        if isinstance(config, TimeWindowScanningConfig):
            self.scanning_config = config
        else:
            # Use default configuration for pipeline config
            self.scanning_config = TimeWindowScanningConfig.create_default()
        
        # Time window parameters (will be adapted from wing configuration)
        self.window_size_minutes = self.scanning_config.window_size_minutes
        self.scanning_interval_minutes = self.scanning_config.scanning_interval_minutes
        self.starting_epoch = self.scanning_config.starting_epoch
        self.ending_epoch = self.scanning_config.ending_epoch
        
        self.debug_mode = debug_mode or self.scanning_config.debug_mode
        
        # Wing configuration adapter
        self.wing_adapter = WingConfigurationAdapter(debug_mode=self.debug_mode)
        
        # Store last execution result
        self.last_result = None
        
        # Progress tracking system
        self.progress_tracker = ProgressTracker(debug_mode=debug_mode)
        self.time_estimator = AdaptiveTimeEstimator()
        self.cancellation_manager = EnhancedCancellationManager(debug_mode=debug_mode)
        
        # Legacy progress listener (for backward compatibility)
        self.progress_listener = None
        
        # Feather query managers
        self.feather_queries: Dict[str, OptimizedFeatherQuery] = {}
        self.window_query_manager: Optional[WindowQueryManager] = None
        
        # Semantic and scoring engines with integration layer
        # Support dependency injection for testing and flexibility
        if scoring_integration is not None:
            self.scoring_integration = scoring_integration
        else:
            # Create default integration if not provided (backward compatibility)
            from ..integration.weighted_scoring_integration import WeightedScoringIntegration
            self.scoring_integration = WeightedScoringIntegration(getattr(config, 'config_manager', None))
        
        if mapping_integration is not None:
            self.semantic_integration = mapping_integration
        else:
            # Create default integration if not provided (backward compatibility)
            from ..integration.semantic_mapping_integration import SemanticMappingIntegration
            self.semantic_integration = SemanticMappingIntegration(getattr(config, 'config_manager', None))
        
        # Load case-specific configurations if available
        case_id = getattr(config, 'case_id', None)
        if case_id:
            self.semantic_integration.load_case_specific_mappings(case_id)
            self.scoring_integration.load_case_specific_scoring_weights(case_id)
        
        # Task 2.3: Verify semantic integration health (only log if debug mode)
        # Requirements: 5.1, 5.2, 5.4 - Check if semantic integration is properly initialized
        if not self.semantic_integration.is_healthy() and self.debug_mode:
            logger.warning("[Time-Window Engine] Semantic mapping integration health check failed - some features may not work correctly")
        
        # Add logging for semantic integration health status
        if self.debug_mode:
            health_status = "healthy" if self.semantic_integration.is_healthy() else "unhealthy"
            enabled_status = "enabled" if self.semantic_integration.is_enabled() else "disabled"
            logger.info(f"[Time-Window Engine] Semantic integration status: {health_status}, {enabled_status}")
            
            # Log configuration source and availability
            manager = self.semantic_integration.semantic_manager
            if manager.config_dir.exists():
                logger.info(f"[Time-Window Engine] Semantic config directory found: {manager.config_dir}")
                if manager.default_rules_path.exists():
                    logger.info(f"[Time-Window Engine]   Default rules file: available")
                else:
                    logger.warning(f"[Time-Window Engine]   Default rules file: missing")
                if manager.custom_rules_path.exists():
                    logger.info(f"[Time-Window Engine]   Custom rules file: available")
                else:
                    logger.info(f"[Time-Window Engine]   Custom rules file: not found (optional)")
            else:
                logger.warning(f"[Time-Window Engine] Semantic config directory not found: {manager.config_dir}")
        
        # Log semantic rules source (JSON vs built-in)
        if self.debug_mode:
            manager = self.semantic_integration.semantic_manager
            rules_count = len(manager.global_rules)
            mappings_count = sum(len(v) for v in manager.global_mappings.values())
            logger.info(f"[Time-Window Engine] Semantic rules loaded: {rules_count} rules, {mappings_count} mappings")
            logger.info(f"[Time-Window Engine] Rules source: JSON files (configs directory)")
            if manager.config_dir.exists():
                logger.info(f"[Time-Window Engine] Config directory: {manager.config_dir}")
                if manager.default_rules_path.exists():
                    logger.info(f"[Time-Window Engine]   - Default rules: {manager.default_rules_path.name}")
                if manager.custom_rules_path.exists():
                    logger.info(f"[Time-Window Engine]   - Custom rules: {manager.custom_rules_path.name}")
        
        # Memory management and streaming
        self.memory_manager: Optional[WindowMemoryManager] = None
        self.memory_monitor: Optional['MemoryMonitor'] = None  # Task 15: Memory monitoring for streaming mode
        self.streaming_writer: Optional[StreamingMatchWriter] = None
        self.streaming_mode_active = False
        # Task 21: Apply memory threshold from performance config (Requirement 8.4)
        self.memory_limit_mb = self.performance_config.memory_threshold_mb
        
        # Output directory for streaming mode (set by pipeline)
        self._output_dir: Optional[str] = None
        self._execution_id: Optional[int] = None
        
        # Parallel processing configuration
        # Task 21: Apply parallel processing config from performance config (Requirement 8.2)
        self.enable_parallel_processing = self.performance_config.enable_parallel
        self.max_workers = self.performance_config.max_workers or self.scanning_config.max_workers or 4
        self.parallel_batch_size = self.scanning_config.parallel_batch_size
        self.parallel_processor: Optional[ParallelWindowProcessor] = None
        
        # Task 12: Parallel Coordinator for optimized parallel processing (Requirements 4.1, 4.2, 4.3, 4.4, 4.5)
        self.parallel_coordinator: Optional['ParallelCoordinator'] = None
        self.use_parallel_coordinator = getattr(self.scanning_config, 'use_parallel_coordinator', False)
        
        # Window processing statistics tracking
        self.window_processing_stats = WindowProcessingStats()
        
        # Empty window detector (Requirements 3.1, 3.2, 3.3, 3.4, 3.5)
        self.empty_window_detector: Optional['EmptyWindowDetector'] = None
        
        # Time range detection result (for statistics reporting)
        self._time_range_detection_result: Optional[TimeRangeDetectionResult] = None
        
        # Performance monitoring system
        self.performance_monitor = create_performance_monitor(
            engine_name="TimeWindowScanningEngine",
            enable_detailed=debug_mode
        )
        
        # Task 23: Performance profiler for optimization (Requirements 1.1, 1.2)
        # Task 21: Enable/disable profiling based on performance config (Requirement 8.1)
        from ..optimization.optimization_components import PerformanceProfiler
        if self.performance_config.enable_profiling:
            self.profiler = PerformanceProfiler(enabled=True)
            self._profiling_enabled = True
            if debug_mode:
                logger.info("[Time-Window Engine] Performance profiling enabled")
        else:
            # Create a disabled profiler for consistent interface
            self.profiler = PerformanceProfiler(enabled=False)
            self._profiling_enabled = False
            if debug_mode:
                logger.info("[Time-Window Engine] Performance profiling disabled")
        
        # Advanced performance analyzer
        self.performance_analyzer = create_performance_analyzer()
        
        # Timestamp caching for optimization (Requirements 6.3, 7.1, 7.2, 7.3, 7.4, 7.5)
        # Task 21: Apply cache size from performance config (Requirement 8.3)
        from ..optimization.optimization_components import TimestampCache, TimestampFormatCache, TimestampParseCache
        self.timestamp_utc_cache = TimestampCache(max_size=self.performance_config.timestamp_cache_size)
        self.timestamp_format_cache = TimestampFormatCache()
        self.timestamp_parse_cache = TimestampParseCache(max_size=self.performance_config.timestamp_cache_size)
        
        # Comprehensive error handling coordination
        self.error_coordinator: Optional[ErrorHandlingCoordinator] = None
        
        # Two-Phase Architecture: Phase 1 data collection
        self.window_data_storage: Optional[WindowDataStorage] = None
        self.window_data_collector: Optional[WindowDataCollector] = None
        
        # Two-Phase Configuration
        if two_phase_config is not None:
            self.two_phase_config = two_phase_config
        else:
            # Use default two-phase configuration
            self.two_phase_config = TwoPhaseConfig.create_default()
        
        # Validate two-phase configuration
        is_valid, error_msg = self.two_phase_config.validate()
        if not is_valid:
            raise ValueError(f"Invalid two-phase configuration: {error_msg}")
        
        # Semantic rule evaluator for advanced semantic rules (AND/OR logic, wildcards, etc.)
        self.semantic_rule_evaluator = SemanticRuleEvaluator(debug_mode=debug_mode)
        
        # Execution context for semantic rule evaluation
        self.wing_id: Optional[str] = None
        self.pipeline_id: Optional[str] = None
        self.wing_semantic_rules: List[Dict] = []
    
    def set_execution_context(self, wing_id: Optional[str] = None,
                              pipeline_id: Optional[str] = None,
                              wing_semantic_rules: Optional[List[Dict]] = None):
        """
        Set execution context for semantic rule evaluation.
        
        Args:
            wing_id: Wing ID for wing-specific rules
            pipeline_id: Pipeline ID for pipeline-specific rules
            wing_semantic_rules: Wing-specific semantic rules from WingConfig
        """
        self.wing_id = wing_id
        self.pipeline_id = pipeline_id
        self.wing_semantic_rules = wing_semantic_rules or []
        
        # Clear rule cache when context changes
        self.semantic_rule_evaluator.clear_cache()
    
    def register_progress_listener(self, listener):
        """
        Register a progress listener for GUI updates.
        
        Args:
            listener: Callable that receives progress events or ProgressListener object
        """
        # Support both old-style callable listeners and new ProgressListener objects
        if hasattr(listener, 'on_progress_event'):
            # New-style ProgressListener
            self.progress_tracker.add_listener(listener)
        else:
            # Legacy callable listener
            self.progress_listener = listener
        
        # Also register with cancellation manager for cancellation events
        self.cancellation_manager.register_progress_listener(listener)
    
    def request_cancellation(self, reason: str = "User requested"):
        """
        Request cancellation of the current correlation operation.
        
        Args:
            reason: Reason for cancellation
        """
        self.cancellation_manager.request_cancellation(reason=reason, requested_by="User")
        
        # Also request cancellation from progress tracker
        self.progress_tracker.request_cancellation()
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        return self.cancellation_manager.is_cancelled()
    
    def get_cancellation_status(self) -> Dict[str, Any]:
        """Get detailed cancellation status"""
        return self.cancellation_manager.get_status_summary()
    
    def get_progress_tracker(self) -> ProgressTracker:
        """Get the progress tracker instance"""
        return self.progress_tracker
    
    def get_time_estimator(self) -> AdaptiveTimeEstimator:
        """Get the time estimator instance"""
        return self.time_estimator
    
    def get_cancellation_manager(self) -> EnhancedCancellationManager:
        """Get the cancellation manager instance"""
        return self.cancellation_manager
    
    def get_error_coordinator(self) -> Optional[ErrorHandlingCoordinator]:
        """Get the error handling coordinator instance"""
        return self.error_coordinator
    
    def get_system_health_status(self) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive system health status.
        
        Returns:
            Dictionary with system health information or None if coordinator not initialized
        """
        if self.error_coordinator:
            health_status = self.error_coordinator.check_system_health()
            return {
                'overall_health': health_status.overall_health,
                'database_health': health_status.database_health,
                'memory_health': health_status.memory_health,
                'timestamp_health': health_status.timestamp_health,
                'error_count_24h': health_status.error_count_24h,
                'critical_errors': len(health_status.critical_errors),
                'recommendations': health_status.recommendations,
                'last_updated': health_status.last_updated.isoformat()
            }
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
            """
            Get correlation statistics from last execution.

            Returns:
                Dictionary containing statistics including:
                    - Basic execution statistics
                    - Memory statistics
                    - Streaming statistics
                    - Parallel processing statistics
                    - Progress tracking statistics
                    - Time estimation statistics
                    - Cancellation statistics
                    - Time range detection statistics (NEW)
                    - Empty window skipping statistics (NEW)
                    - Efficiency metrics (NEW)
                    - Cache hit rates (Task 22)
                    - Index usage rates (Task 22)
                    - Skip rates (Task 22)
            """
            if not self.last_result:
                return {}

            stats = {
                'execution_time': self.last_result.execution_duration_seconds,
                'record_count': self.last_result.total_records_scanned,
                'match_count': self.last_result.total_matches,
                'feathers_processed': self.last_result.feathers_processed,
                'window_size_minutes': self.window_size_minutes,
                'scanning_approach': 'time_window_scanning',
                'streaming_mode_used': self.streaming_mode_active,
                'parallel_processing_enabled': self.enable_parallel_processing
            }

            # Add memory statistics if available
            if self.memory_manager:
                memory_stats = self.memory_manager.get_memory_statistics()
                stats.update({
                    'memory_statistics': memory_stats,
                    'peak_memory_mb': memory_stats.get('peak_memory_mb', 0),
                    'memory_efficiency_mb_per_1k_records': memory_stats.get('recent_efficiency_mb_per_1k_records', 0)
                })

            # Add streaming statistics if used
            if self.streaming_mode_active and self.streaming_writer:
                stats.update({
                    'streaming_database_path': self.streaming_writer.database_path,
                    'total_matches_written': self.streaming_writer.total_matches_written
                })

            # Add parallel processing statistics if used
            if self.enable_parallel_processing and self.parallel_processor:
                parallel_stats = self.parallel_processor.get_processing_stats()
                stats.update({
                    'parallel_processing_stats': {
                        'max_workers': self.max_workers,
                        'batch_size': self.parallel_batch_size,
                        'total_windows_processed': parallel_stats.total_windows_processed,
                        'average_window_time': parallel_stats.average_window_time,
                        'parallel_speedup': parallel_stats.parallel_speedup,
                        'load_balancing_efficiency': parallel_stats.load_balancing_efficiency,
                        'worker_utilization': parallel_stats.worker_utilization
                    }
                })

            # Add progress tracking statistics
            if hasattr(self, 'progress_tracker'):
                progress_data = self.progress_tracker._create_overall_progress()
                stats.update({
                    'progress_tracking_stats': {
                        'windows_processed': progress_data.windows_processed,
                        'total_windows': progress_data.total_windows,
                        'completion_percentage': progress_data.completion_percentage,
                        'processing_rate_windows_per_second': progress_data.processing_rate_windows_per_second,
                        'estimated_completion_time': progress_data.estimated_completion_time.isoformat() if progress_data.estimated_completion_time else None,
                        'time_remaining_seconds': progress_data.time_remaining_seconds
                    }
                })

            # Add time estimation statistics
            if hasattr(self, 'time_estimator'):
                estimation_stats = self.time_estimator.get_performance_statistics()
                stats.update({
                    'time_estimation_stats': estimation_stats
                })

            # Add cancellation statistics
            if hasattr(self, 'cancellation_manager'):
                cancellation_stats = self.cancellation_manager.get_status_summary()
                stats.update({
                    'cancellation_stats': cancellation_stats
                })

            # Add time range detection statistics (NEW)
            time_range_stats = self.get_time_range_detection_statistics()
            if time_range_stats.get('available'):
                stats.update({
                    'time_range_detection_stats': time_range_stats
                })

            # Add empty window skipping statistics (NEW)
            empty_window_stats = self.get_empty_window_skipping_statistics()
            if empty_window_stats.get('available'):
                stats.update({
                    'empty_window_skipping_stats': empty_window_stats
                })

            # Add cache hit rates (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4)
            cache_stats = self._get_cache_statistics()
            if cache_stats:
                stats.update({
                    'cache_statistics': cache_stats
                })

            # Add index usage rates (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4)
            index_stats = self._get_index_usage_statistics()
            if index_stats:
                stats.update({
                    'index_usage_statistics': index_stats
                })

            # Add skip rates (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4)
            skip_stats = self._get_skip_rate_statistics()
            if skip_stats:
                stats.update({
                    'skip_rate_statistics': skip_stats
                })

            # Add efficiency metrics (NEW)
            efficiency_metrics = self.get_efficiency_metrics()
            if efficiency_metrics.get('available'):
                stats.update({
                    'efficiency_metrics': efficiency_metrics
                })

            return stats

    
    def configure_parallel_processing(self, 
                                    enable: bool = True,
                                    max_workers: Optional[int] = None,
                                    batch_size: int = 100,
                                    enable_load_balancing: bool = True,
                                    use_coordinator: bool = False):
        """
        Configure parallel processing settings.
        
        Task 12: Enhanced to support ParallelCoordinator integration.
        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
        
        Args:
            enable: Enable or disable parallel processing
            max_workers: Maximum number of worker threads (None = auto-detect)
            batch_size: Number of windows to process in each batch
            enable_load_balancing: Enable intelligent load balancing
            use_coordinator: Use ParallelCoordinator instead of ParallelWindowProcessor
        """
        self.enable_parallel_processing = enable
        self.use_parallel_coordinator = use_coordinator
        
        if max_workers is not None:
            self.max_workers = max_workers
        else:
            # Auto-detect optimal worker count
            import os
            cpu_count = os.cpu_count() or 4
            self.max_workers = min(cpu_count * 2, 8)  # Cap at 8 for database I/O
        
        self.parallel_batch_size = batch_size
        
        if enable:
            if use_coordinator:
                # Task 12: Use ParallelCoordinator for optimized parallel processing
                from ..optimization.optimization_components import ParallelCoordinator
                self.parallel_coordinator = ParallelCoordinator(
                    max_workers=self.max_workers,
                    memory_limit_mb=self.memory_limit_mb,
                    shared_data_strategy="thread_local"
                )
                
                if self.debug_mode:
                    print(f"[TimeWindow] Parallel coordinator enabled: {self.max_workers} workers, "
                          f"memory_limit={self.memory_limit_mb}MB")
            else:
                # Use existing ParallelWindowProcessor
                self.parallel_processor = ParallelWindowProcessor(
                    max_workers=self.max_workers,
                    enable_load_balancing=enable_load_balancing,
                    batch_size=batch_size,
                    memory_limit_mb=self.memory_limit_mb
                )
                
                if self.debug_mode:
                    print(f"[TimeWindow] Parallel processing enabled: {self.max_workers} workers, "
                          f"batch_size={batch_size}, load_balancing={enable_load_balancing}")
        else:
            self.parallel_processor = None
            self.parallel_coordinator = None
            if self.debug_mode:
                print("[TimeWindow] Parallel processing disabled")
    
    def get_parallel_processing_stats(self) -> Optional[ParallelProcessingStats]:
        """
        Get parallel processing statistics from last execution.
        
        Task 12: Enhanced to support ParallelCoordinator statistics.
        
        Returns:
            ParallelProcessingStats object or None if parallel processing not used
        """
        if self.parallel_processor:
            return self.parallel_processor.get_processing_stats()
        elif self.parallel_coordinator:
            # Return coordinator statistics in a compatible format
            stats = self.parallel_coordinator.get_statistics()
            # Note: ParallelCoordinator returns a dict, not ParallelProcessingStats
            # For now, return None and let callers check coordinator directly
            return None
        return None
    
    def get_parallel_coordinator_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get parallel coordinator statistics from last execution.
        
        Task 12: New method for ParallelCoordinator statistics.
        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
        
        Returns:
            Dictionary with coordinator statistics or None if coordinator not used
        """
        if self.parallel_coordinator:
            return self.parallel_coordinator.get_statistics()
        return None
        if self.parallel_processor:
            return self.parallel_processor.get_processing_stats()
        return None
    
    @property
    def metadata(self) -> EngineMetadata:
        """Get engine metadata"""
        return EngineMetadata(
            name="Time-Window Scanning",
            version="1.0.0",
            description="O(N) time-window scanning correlation with systematic temporal analysis",
            complexity="O(N)",
            best_for=[
                "Large datasets (>1,000 records)",
                "Performance-critical environments",
                "Systematic temporal analysis",
                "Memory-constrained systems"
            ],
            supports_identity_filter=False
        )
    
    def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
        """
        Execute time-window scanning correlation.
        
        Args:
            wing_configs: List of Wing configuration objects (typically one wing)
            
        Returns:
            Dictionary containing:
                - 'result': CorrelationResult object
                - 'engine_type': 'time_window_scanning'
                - 'filters_applied': Dictionary of applied filters
        """
        if not wing_configs:
            raise ValueError("No wing configurations provided")
        
        # Always print which engine is being used
        print("\n" + "="*70)
        print("🔧 CORRELATION ENGINE: Time-Window Scanning")
        print("="*70)
        print(f"[Time-Window Engine] 🎯 Target: {len(wing_configs)} wing(s)")
        window_display = self._format_time_window(self.window_size_minutes)
        print(f"[Time-Window Engine] ⚙️ Window: {window_display}, Interval: {self.scanning_interval_minutes} min")
        
        if self.enable_parallel_processing:
            print(f"[Time-Window Engine] 🔄 Mode: Parallel processing ({self.max_workers} workers)")
        else:
            print(f"[Time-Window Engine] ➡️ Mode: Sequential processing")
        
        wing = wing_configs[0]  # Typically one wing per execution
        
        # Get feather paths from wing
        feather_paths = self._extract_feather_paths(wing)
        
        # Execute time-window scanning
        result = self._scan_time_windows(wing, feather_paths)
        
        # Store engine type as a direct attribute for easy access
        result.engine_type = "time_based"
        
        # Store result
        self.last_result = result
        
        # Return standardized format
        return {
            'result': result,
            'engine_type': 'time_window_scanning',
            'filters_applied': {
                'time_period_start': self.filters.time_period_start.isoformat() if self.filters.time_period_start else None,
                'time_period_end': self.filters.time_period_end.isoformat() if self.filters.time_period_end else None,
                'window_size_minutes': self.window_size_minutes,
                'starting_epoch': self.starting_epoch.isoformat()
            }
        }
    
    def set_output_directory(self, output_dir: str, execution_id: int = None):
        """
        Set output directory for streaming results to database.
        
        This method is called by the pipeline executor to enable streaming mode.
        When set, matches will be written directly to the database instead of
        being stored in memory.
        
        Args:
            output_dir: Directory where correlation_results.db will be created
            execution_id: Execution ID for this correlation run
        """
        self._output_dir = output_dir
        self._execution_id = execution_id
        
        if self.debug_mode:
            print(f"[Time-Window Engine] Output directory set: {output_dir}")
            print(f"[Time-Window Engine] Execution ID: {execution_id}")
    
    def _should_run_identity_semantic_phase(self) -> bool:
        """
        Determine if Identity Semantic Phase should run.
        
        Task 5.1: Add _should_run_identity_semantic_phase() method
        Requirements: 2.1, 2.3
        
        Returns:
            True if phase is enabled and correlation is complete
        """
        # Check if Identity Semantic Phase is enabled in configuration
        # Default to True if not explicitly set
        if not hasattr(self.config, 'identity_semantic_phase_enabled'):
            # Default: enabled
            phase_enabled = True
        else:
            phase_enabled = self.config.identity_semantic_phase_enabled
        
        if not phase_enabled:
            if self.debug_mode:
                logger.info("[Time-Window Engine] Identity Semantic Phase disabled in configuration")
            return False
        
        # Check if semantic integration is available
        if not hasattr(self, 'semantic_integration'):
            if self.debug_mode:
                logger.warning("[Time-Window Engine] Semantic integration not available")
            return False
        
        # Check if semantic integration is enabled
        if not self.semantic_integration.is_enabled():
            if self.debug_mode:
                logger.info("[Time-Window Engine] Semantic integration disabled")
            return False
        
        # All checks passed - phase should run
        return True
    
    def _execute_identity_semantic_phase(self, 
                                        correlation_results: CorrelationResult,
                                        wing_configs: List[Any]) -> CorrelationResult:
        """
        Execute Identity Semantic Phase after correlation completes.
        
        This method applies identity-level semantic mappings in a dedicated final analysis phase,
        processing each unique identity once rather than per-record during correlation.
        
        Task 5.1: Integrate with TimeWindowScanningEngine
        Requirements: 2.1, 2.2, 2.3, 2.4, 14.1, 14.2
        
        Args:
            correlation_results: Results from correlation engine
            wing_configs: Wing configurations for context
            
        Returns:
            Enhanced correlation results with identity-level semantic data
        """
        # Task 5.1: Check if Identity Semantic Phase should run
        if not self._should_run_identity_semantic_phase():
            if self.debug_mode:
                logger.info("[Time-Window Engine] Identity Semantic Phase skipped")
            return correlation_results
        
        try:
            # Import Identity Semantic Phase components
            from ..identity_semantic_phase.identity_semantic_controller import (
                IdentitySemanticController,
                IdentitySemanticConfig
            )
            
            # Create configuration for Identity Semantic Phase
            # Use semantic integration from the engine
            phase_config = IdentitySemanticConfig(
                enabled=True,
                semantic_mapping_enabled=self.semantic_integration.is_enabled(),
                identity_extraction_enabled=True,
                progress_reporting_enabled=True,
                debug_mode=self.debug_mode
            )
            
            # Create Identity Semantic Controller
            controller = IdentitySemanticController(
                config=phase_config,
                semantic_integration=self.semantic_integration
            )
            
            # Pass database information for streaming mode support
            if correlation_results.streaming_mode:
                db_path = Path(self._output_dir) / "correlation_results.db"
                correlation_results.database_path = str(db_path)
                correlation_results.execution_id = self._execution_id
                
                if self.debug_mode:
                    logger.info(f"[Time-Window Engine] Passing database info to Identity Semantic Phase: {db_path}, execution_id={self._execution_id}")
            
            # Execute final analysis phase
            # Pass engine type as "time_based" and correlation results
            enhanced_results = controller.execute_final_analysis(
                correlation_results=correlation_results,
                engine_type="time_based"
            )
            
            return enhanced_results
            
        except ImportError as e:
            # Identity Semantic Phase components not available
            logger.warning(f"[Time-Window Engine] Identity Semantic Phase not available: {e}")
            if self.debug_mode:
                print(f"[Time-Window Engine] Identity Semantic Phase import failed: {e}")
            return correlation_results
            
        except Exception as e:
            # Error during Identity Semantic Phase execution
            # Log error but return original results (graceful degradation)
            logger.error(f"[Time-Window Engine] Identity Semantic Phase failed: {e}")
            print(f"[Time-Window Engine] WARNING: Identity Semantic Phase failed: {e}")
            print(f"[Time-Window Engine] Continuing with original correlation results")
            return correlation_results
    
    def execute_wing(self, wing: Any, feather_paths: Dict[str, str]) -> Any:
        """
        Execute correlation for a single wing (backward compatibility method).
        
        Args:
            wing: Wing configuration object
            feather_paths: Dictionary mapping feather_id to database path
            
        Returns:
            CorrelationResult object
        """
        result = self._scan_time_windows(wing, feather_paths)
        self.last_result = result
        return result
    
    def _scan_time_windows(self, wing: Wing, feather_paths: Dict[str, str]) -> CorrelationResult:
        """
        Main time-window scanning algorithm.
        
        Args:
            wing: Wing configuration
            feather_paths: Dictionary mapping feather_id to database path
            
        Returns:
            CorrelationResult with matches found
        """
        start_time = time.time()
        total_windows = 0  # Initialize early to avoid UnboundLocalError in finally block
        
        import sys
        
        def log(msg):
            """Print with immediate flush for visibility"""
            print(msg)
            sys.stdout.flush()
        
        # Task 23: Start profiling the entire scan operation (Requirements 1.1, 1.2)
        if self._profiling_enabled:
            self.profiler.start_operation("_scan_time_windows")
            self.profiler.record_memory_checkpoint("scan_start")
        
        # Requirement 6.1: Log time range at engine start
        log(f"\n[Time-Window Engine] 🚀 Starting correlation...")
        log(f"[Time-Window Engine] Wing: {wing.wing_name}")
        log(f"[Time-Window Engine] Feathers: {len(feather_paths)}")
        
        # Show feather paths for debugging
        for fid, fpath in list(feather_paths.items())[:3]:  # Show first 3
            path_display = fpath[:50] if len(fpath) > 50 else fpath
            log(f"[Time-Window Engine]   • {fid}: {path_display}...")
        if len(feather_paths) > 3:
            log(f"[Time-Window Engine]   ... and {len(feather_paths) - 3} more")
        
        result = CorrelationResult(
            wing_id=wing.wing_id,
            wing_name=wing.wing_name
        )
        
        # Start performance monitoring (with error handling)
        log(f"[Time-Window Engine] Starting performance monitor...")
        try:
            performance_report = self.performance_monitor.start_execution({
                'wing_id': wing.wing_id,
                'wing_name': wing.wing_name,
                'window_size_minutes': self.window_size_minutes,
                'scanning_interval_minutes': self.scanning_interval_minutes,
                'parallel_processing': self.enable_parallel_processing,
                'max_workers': self.max_workers,
                'memory_limit_mb': self.memory_limit_mb,
                'feather_count': len(feather_paths)
            })
            log(f"[Time-Window Engine] Performance monitor started ✓")
        except Exception as perf_error:
            log(f"[Time-Window Engine] Performance monitor error: {perf_error}")
            performance_report = None
        
        try:
            # Step 1: Adapt wing configuration for time-window scanning
            log(f"[Time-Window Engine] 📋 Step 1: Adapting wing configuration...")
            with PhaseTimer(self.performance_monitor, ProcessingPhase.INITIALIZATION) as timer:
                adaptation_result = self.wing_adapter.adapt_wing_configuration(wing, self.scanning_config)
                
                # Update scanning configuration with adapted values
                self.scanning_config = adaptation_result.adapted_config
                self.window_size_minutes = self.scanning_config.window_size_minutes
                self.scanning_interval_minutes = self.scanning_config.scanning_interval_minutes
                
                if adaptation_result.success:
                    print(f"[Time-Window Engine]   ✓ Configuration adapted successfully")
                    sys.stdout.flush()
                else:
                    print(f"[Time-Window Engine]   ❌ Configuration adaptation failed")
                    sys.stdout.flush()
                
                # Log adaptation warnings
                if adaptation_result.warnings and self.debug_mode:
                    for warning in adaptation_result.warnings:
                        print(f"[Time-Window Engine]   ⚠️ Warning: {warning}")
                        result.warnings.append(f"Configuration: {warning}")
                
                # Log incompatibilities as errors
                if adaptation_result.incompatibilities:
                    for incompatibility in adaptation_result.incompatibilities:
                        print(f"[Time-Window Engine]   ❌ Error: {incompatibility}")
                        result.errors.append(f"Configuration: {incompatibility}")
                        timer.add_error()
                    
                    # Return early if there are critical incompatibilities
                    if result.errors:
                        return result
                
                if self.debug_mode:
                    print(f"[Time-Window Engine]   📊 Feather priorities: {adaptation_result.feather_priority_mapping}")
            
            # Set execution context for semantic rule evaluation
            wing_semantic_rules = getattr(wing, 'semantic_rules', [])
            self.set_execution_context(
                wing_id=wing.wing_id,
                pipeline_id=getattr(wing, 'pipeline_id', None),
                wing_semantic_rules=wing_semantic_rules
            )
            if self.debug_mode:
                print(f"[Time-Window Engine]   🏷️ Semantic context: wing={wing.wing_id}, rules={len(wing_semantic_rules)}")
            
            # Step 2: Initialize memory management and error coordination
            print(f"[Time-Window Engine] 🧠 Step 2: Initializing memory management...")
            sys.stdout.flush()
            with PhaseTimer(self.performance_monitor, ProcessingPhase.INITIALIZATION) as timer:
                self.memory_manager = WindowMemoryManager(
                    max_memory_mb=self.scanning_config.memory_limit_mb,
                    enable_gc=True
                )
                
                # Task 15: Initialize MemoryMonitor for streaming mode memory management
                # Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
                # Task 21: Apply memory thresholds from performance config (Requirement 8.4)
                self.memory_monitor = MemoryMonitor(
                    threshold_mb=self.performance_config.memory_threshold_mb,
                    check_interval_seconds=1
                )
                
                # Initialize comprehensive error handling coordination
                self.error_coordinator = ErrorHandlingCoordinator(
                    debug_mode=self.debug_mode
                )
                
                # Initialize progress tracking and time estimation
                self.time_estimator.start_tracking()
                
                # Register resources for cleanup on cancellation
                self.cancellation_manager.resource_manager.register_resource(
                    "memory_manager", self.memory_manager
                )
                
                print(f"[Time-Window Engine]   ✓ Memory limit: {self.scanning_config.memory_limit_mb} MB")
                print(f"[Time-Window Engine]   ✓ Memory monitor initialized")
                print(f"[Time-Window Engine]   ✓ Error handling initialized")
                sys.stdout.flush()
            
            # Step 3: Load and initialize feather databases
            print(f"[Time-Window Engine] 📂 Step 3: Loading feather databases...")
            sys.stdout.flush()
            with PhaseTimer(self.performance_monitor, ProcessingPhase.FEATHER_LOADING) as timer:
                self._load_feathers(wing, feather_paths, result)
                timer.add_records(result.feathers_processed)
                
                # Task 23: Record memory checkpoint after loading (Requirements 1.2)
                if self._profiling_enabled:
                    self.profiler.record_memory_checkpoint("after_feather_loading")
                
                print(f"[Time-Window Engine]   ✓ Loaded {result.feathers_processed} feathers")
                sys.stdout.flush()
                
                if result.errors:
                    print(f"[Time-Window Engine]   ⚠️ {len(result.errors)} feather loading errors")
                    for err in result.errors[:3]:  # Show first 3 errors
                        print(f"[Time-Window Engine]     • {err}")
                    sys.stdout.flush()
                    timer.error_count = len(result.errors)
                    return result
                
                # Show feather summary
                if self.feather_queries:
                    total_records = sum(
                        result.feather_metadata.get(fid, {}).get('total_records', 0) 
                        for fid in self.feather_queries.keys()
                    )
                    print(f"[Time-Window Engine]   📊 Total records: {total_records:,}")
                    
                    # Show feather types
                    feather_types = {}
                    for fid in self.feather_queries.keys():
                        artifact_type = result.feather_metadata.get(fid, {}).get('artifact_type', 'Unknown')
                        feather_types[artifact_type] = feather_types.get(artifact_type, 0) + 1
                    
                    type_summary = ", ".join([f"{count} {type_name}" for type_name, count in feather_types.items()])
                    print(f"[Time-Window Engine]   📋 Types: {type_summary}")
                    sys.stdout.flush()
                
                # Display timestamp columns detected for each feather
                print(f"\n[Time-Window Engine]   ⏰ Timestamp Columns Detected:")
                print(f"[Time-Window Engine]   {'='*80}")
                print(f"[Time-Window Engine]   {'Feather':<25} {'Timestamp Columns':<55}")
                print(f"[Time-Window Engine]   {'-'*80}")
                
                for fid, query_manager in self.feather_queries.items():
                    # Get timestamp columns
                    if hasattr(query_manager, 'timestamp_columns') and query_manager.timestamp_columns:
                        ts_cols = query_manager.timestamp_columns
                        if len(ts_cols) > 3:
                            # Show first 3 and count
                            cols_display = f"{', '.join(ts_cols[:3])} (+{len(ts_cols)-3} more)"
                        else:
                            cols_display = ', '.join(ts_cols)
                        print(f"[Time-Window Engine]   {fid:<25} {cols_display:<55}")
                    elif hasattr(query_manager, 'timestamp_column') and query_manager.timestamp_column:
                        print(f"[Time-Window Engine]   {fid:<25} {query_manager.timestamp_column:<55}")
                    else:
                        print(f"[Time-Window Engine]   {fid:<25} {'⚠️  None detected':<55}")
                
                print(f"[Time-Window Engine]   {'='*80}\n")
                sys.stdout.flush()
                
                # Register error handling components with coordinator
                if self.feather_queries:
                    # Get the first query manager to access error handlers
                    first_query = next(iter(self.feather_queries.values()))
                    
                    # Register error handling components
                    self.error_coordinator.register_error_handlers(
                        database_handler=first_query.error_handler,
                        timestamp_parser=first_query.timestamp_parser,
                        memory_manager=self.memory_manager
                    )
                
                # Register feather connections for cleanup
                for feather_id, query_manager in self.feather_queries.items():
                    self.cancellation_manager.resource_manager.register_resource(
                        f"feather_{feather_id}", query_manager.loader
                    )
                
                # Create window query manager
                self.window_query_manager = WindowQueryManager(
                    self.feather_queries,
                    filters=self.filters,
                    debug_mode=self.debug_mode
                )
                
                # Initialize empty window detector (Requirements 3.1, 3.2, 3.3, 3.4, 3.5)
                # Task 21: Only initialize if enabled in performance config
                if self.performance_config.enable_empty_window_skipping:
                    self.empty_window_detector = EmptyWindowDetector(
                        window_manager=self.window_query_manager,
                        debug_mode=self.debug_mode
                    )
                else:
                    self.empty_window_detector = None
                    if self.debug_mode:
                        logger.info("[Time-Window Engine] Empty window skipping disabled by performance config")
                
                # Initialize Two-Phase Architecture components
                # Phase 1: WindowDataStorage for persisting window data
                correlation_db_path = getattr(wing, 'correlation_database', 'correlation_results.db')
                if not Path(correlation_db_path).is_absolute():
                    # Make path relative to first feather's directory
                    if feather_paths:
                        first_feather_path = next(iter(feather_paths.values()))
                        correlation_db_path = str(Path(first_feather_path).parent / correlation_db_path)
                
                self.window_data_storage = WindowDataStorage(
                    database_path=correlation_db_path,
                    debug_mode=self.debug_mode
                )
                
                # Phase 1: WindowDataCollector for fast data collection
                # Note: WindowDataCollector expects feather_loader and error_handler
                # Create error handler for Phase 1
                phase1_error_handler = Phase1ErrorHandler(debug_mode=self.debug_mode)
                
                # WindowDataCollector is not currently used in the simplified architecture
                # The window_query_manager handles data collection directly
                # Commenting out for now to avoid initialization errors
                # self.window_data_collector = WindowDataCollector(
                #     feather_loader=None,  # Would need to pass appropriate loader
                #     error_handler=phase1_error_handler,
                #     debug_mode=self.debug_mode
                # )
                
                print(f"[Time-Window Engine]   ✓ Two-phase architecture initialized")
                print(f"[Time-Window Engine]   📁 Correlation DB: {correlation_db_path}")
                sys.stdout.flush()
            
            # Step 4: Determine overall time range for scanning
            print(f"[Time-Window Engine] ⏰ Step 4: Determining time range...")
            sys.stdout.flush()
            with PhaseTimer(self.performance_monitor, ProcessingPhase.TIME_RANGE_DETERMINATION) as timer:
                start_epoch, end_epoch = self._determine_time_range(result)
                
                # Requirement 6.1: Log time range at engine start
                duration_hours = (end_epoch - start_epoch).total_seconds() / 3600
                duration_days = (end_epoch - start_epoch).total_seconds() / 86400
                
                print(f"[Time-Window Engine]   ✓ Time range determined successfully")
                print(f"[Time-Window Engine] 🕐 Time Range: {start_epoch.strftime('%Y-%m-%d %H:%M:%S')} to {end_epoch.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[Time-Window Engine]   📅 Data Span: {duration_days:.1f} days ({duration_hours:.1f} hours)")
                
                # Requirement 6.2: Log time window generation summary
                estimated_windows = self._calculate_total_windows(start_epoch, end_epoch)
                print(f"[Time-Window Engine] 📊 Generated {estimated_windows:,} time windows ({self.window_size_minutes} minutes each)")
                
                # Calculate and display estimated processing time with improved accuracy
                # Base estimate depends on dataset size and configuration
                total_records = sum(meta.get('records_processed', 0) for meta in result.feather_metadata.values())
                
                # Improved estimation based on actual data characteristics
                if total_records > 0:
                    # Estimate based on records per window and processing rate
                    avg_records_per_window = total_records / estimated_windows if estimated_windows > 0 else 0
                    
                    # Processing rate estimates (records/second):
                    # - Small windows (<100 records): ~5000 records/sec (fast, mostly empty)
                    # - Medium windows (100-1000 records): ~2000 records/sec
                    # - Large windows (>1000 records): ~1000 records/sec (correlation overhead)
                    if avg_records_per_window < 100:
                        processing_rate = 5000  # Fast processing for sparse data
                        base_time_per_window = 0.02  # 20ms overhead per window
                    elif avg_records_per_window < 1000:
                        processing_rate = 2000
                        base_time_per_window = 0.05  # 50ms overhead
                    else:
                        processing_rate = 1000
                        base_time_per_window = 0.1  # 100ms overhead
                    
                    # Calculate time based on records + overhead
                    estimated_seconds = (total_records / processing_rate) + (estimated_windows * base_time_per_window)
                    
                    # Add overhead for streaming mode
                    if self.streaming_mode_active:
                        estimated_seconds *= 1.2  # 20% overhead for database writes
                    
                    # Add overhead for parallel processing coordination
                    if self.enable_parallel_processing:
                        estimated_seconds *= 0.7  # 30% speedup from parallelization
                    
                    estimated_processing_minutes = estimated_seconds / 60
                else:
                    # Fallback: use simple per-window estimate
                    estimated_processing_minutes = (estimated_windows * 0.1) / 60  # 100ms per window
                
                estimated_time_str = self._format_time_duration(estimated_processing_minutes)
                
                # Show estimate with context
                if estimated_processing_minutes < 1:
                    print(f"[Time-Window Engine] ⏱️ Estimated Time: ~{estimated_seconds:.1f} seconds")
                elif estimated_processing_minutes < 60:
                    print(f"[Time-Window Engine] ⏱️ Estimated Time: ~{estimated_processing_minutes:.1f} minutes")
                else:
                    print(f"[Time-Window Engine] ⏱️ Estimated Time: ~{estimated_time_str}")
                    print(f"[Time-Window Engine]   ℹ️  Initial estimate - will refine as processing begins")
                
                # Show data density information
                if total_records > 0 and estimated_windows > 0:
                    avg_records_per_window = total_records / estimated_windows
                    if avg_records_per_window < 10:
                        density = "very sparse"
                    elif avg_records_per_window < 100:
                        density = "sparse"
                    elif avg_records_per_window < 1000:
                        density = "moderate"
                    else:
                        density = "dense"
                    
                    print(f"[Time-Window Engine] 📊 Data Density: {avg_records_per_window:.1f} records/window ({density})")
                
                # Show performance comparison if we avoided year 2000 default
                if self.scanning_config.auto_detect_time_range:
                    # Calculate what it would have been from year 2000
                    from datetime import timezone
                    year_2000 = datetime(2000, 1, 1, tzinfo=timezone.utc)  # Make timezone-aware
                    if start_epoch > year_2000:
                        windows_from_2000 = self._calculate_total_windows(year_2000, end_epoch)
                        windows_saved = windows_from_2000 - estimated_windows
                        if windows_saved > 0:
                            savings_percent = (windows_saved / windows_from_2000 * 100) if windows_from_2000 > 0 else 0
                            time_saved_hours = (windows_saved * base_time_per_window) / 3600 if 'base_time_per_window' in locals() else (windows_saved * 0.1) / 3600
                            
                            print(f"[Time-Window Engine] 💡 Smart Time Range Detection:")
                            print(f"[Time-Window Engine]   • Avoided {windows_saved:,} unnecessary windows ({savings_percent:.1f}% reduction)")
                            print(f"[Time-Window Engine]   • Saved ~{time_saved_hours:.1f} hours of processing time")
                            print(f"[Time-Window Engine]   • Started from {start_epoch.year} instead of 2000")
                
                sys.stdout.flush()
            
            # Step 5: Generate and process time windows
            matches = []
            total_windows = self._calculate_total_windows(start_epoch, end_epoch)
            
            processing_mode = "parallel" if self.enable_parallel_processing else "sequential"
            print(f"\n[Time-Window Engine] 🔍 Step 5: Processing Time Windows")
            print(f"[Time-Window Engine] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"[Time-Window Engine] Mode: {processing_mode.upper()}")
            
            if self.enable_parallel_processing and self.parallel_processor:
                print(f"[Time-Window Engine] Workers: {self.max_workers} parallel threads")
            
            if self.streaming_mode_active:
                print(f"[Time-Window Engine] Streaming: ENABLED (memory-efficient mode)")
            
            print(f"[Time-Window Engine] Windows: {total_windows:,} to process")
            print(f"[Time-Window Engine] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            
            sys.stdout.flush()
            
            # Start progress tracking with actual window count (not from year 2000)
            self.progress_tracker.start_scanning(
                total_windows=total_windows,
                window_size_minutes=self.window_size_minutes,
                time_range_start=start_epoch,
                time_range_end=end_epoch,
                parallel_processing=self.enable_parallel_processing,
                max_workers=self.max_workers if self.enable_parallel_processing else 1
            )
            
            # Legacy progress event for backward compatibility
            self._emit_progress_event("scanning_start", {
                'total_windows': total_windows,
                'window_size_minutes': self.window_size_minutes,
                'time_range_start': start_epoch.isoformat(),
                'time_range_end': end_epoch.isoformat(),
                'parallel_processing': self.enable_parallel_processing,
                'max_workers': self.max_workers if self.enable_parallel_processing else 1
            })
            
            # Choose processing method based on configuration
            if self.enable_parallel_processing and self.parallel_processor and total_windows > 10:
                # Use parallel processing for larger workloads
                matches = self._process_windows_parallel(start_epoch, end_epoch, wing, result)
            else:
                # Use sequential processing
                matches = self._process_windows_sequential(start_epoch, end_epoch, wing, result, total_windows)
            
            # Task 23: Record memory checkpoint after processing (Requirements 1.2)
            if self._profiling_enabled:
                self.profiler.record_memory_checkpoint("after_window_processing")
            
            # Task 2.1: Semantic mappings REMOVED from correlation processing
            # Requirements: 1.1, 1.2, 1.3, 1.4
            # Semantic matching will be applied in Identity Semantic Phase AFTER correlation reaches 100%
            result.matches = matches
            print(f"[Time-Window Engine] ✓ Correlation processing complete - NO semantic mappings during correlation")
            print(f"[Time-Window Engine]   Semantic matching will be applied in Identity Semantic Phase after 100%")
            print(f"[Time-Window Engine]   Weighted scoring was applied DURING correlation (fast operation)")
            
            # Complete progress tracking
            self.progress_tracker.complete_scanning()
            
            print(f"\n[Time-Window Engine] ✅ Phase 1 Complete: Data Collection")
            print(f"[Time-Window Engine]   📊 Windows processed: {total_windows:,}")
            print(f"[Time-Window Engine]   💾 Data saved to database")
            
            # Finalize streaming if active
            if self.streaming_mode_active and self.streaming_writer:
                self._finalize_streaming_mode(result)
                
                # Apply semantic mapping post-processing AFTER streaming is finalized
                if hasattr(self, '_output_dir') and hasattr(self, '_execution_id'):
                    db_path = Path(self._output_dir) / "correlation_results.db"
                    if db_path.exists():
                        print("\n[Time-Window Engine] Starting post-processing semantic mapping...")
                        semantic_result = self.apply_semantic_mapping_post_processing(
                            database_path=str(db_path),
                            execution_id=self._execution_id
                        )
                        
                        if semantic_result.get('success'):
                            print(f"[Time-Window Engine] ✓ Semantic mapping applied to {semantic_result.get('matches_updated', 0):,} matches")
                        else:
                            print(f"[Time-Window Engine] ⚠ Semantic mapping skipped: {semantic_result.get('reason', 'unknown')}")

            
            if self.debug_mode:
                final_memory = self.memory_manager.check_memory_pressure() if self.memory_manager else None
                memory_info = f", peak memory: {final_memory.peak_memory_mb:.1f}MB" if final_memory else ""
                streaming_info = " (streamed to database)" if self.streaming_mode_active else ""
                parallel_info = f" (parallel: {self.max_workers} workers)" if self.enable_parallel_processing else ""
                print(f"[TimeWindow] Scanning complete: {result.total_matches} matches found{memory_info}{streaming_info}{parallel_info}")
                
                # Log parallel processing statistics if available
                if self.enable_parallel_processing and self.parallel_processor:
                    parallel_stats = self.parallel_processor.get_processing_stats()
                    if parallel_stats.total_windows_processed > 0:
                        print(f"[TimeWindow] Parallel stats: {parallel_stats.parallel_speedup:.1f}x speedup, "
                              f"{parallel_stats.load_balancing_efficiency:.1f} load balance efficiency, "
                              f"{parallel_stats.average_window_time:.3f}s avg window time")
            
        except Exception as e:
            # Check if this was a cancellation
            if self.cancellation_manager.is_cancelled():
                # Perform graceful shutdown
                context = self.cancellation_manager.perform_graceful_shutdown(
                    correlation_result=result,
                    save_partial_results=True
                )
                
                result.errors.append(f"Operation cancelled: {context.reason}")
                if context.partial_results_preserved:
                    result.warnings.append("Partial results have been saved")
                
                # Report cancellation to progress tracker
                self.progress_tracker.report_error(
                    f"Operation cancelled: {context.reason}",
                    f"Partial results preserved: {context.partial_results_preserved}"
                )
            else:
                # Regular error - use comprehensive error handling
                error_message = str(e)
                
                print(f"[Time-Window Engine] ❌ Error: {error_message}")
                
                # Attempt recovery using error coordinator
                if self.error_coordinator:
                    recovered, recovery_action = self.error_coordinator.handle_error(
                        category=ErrorCategory.PROCESSING,
                        component="TimeWindowScanningEngine",
                        error_message=error_message,
                        context={
                            'wing_id': wing.wing_id,
                            'feather_count': len(feather_paths),
                            'window_size_minutes': self.window_size_minutes
                        },
                        severity=ErrorSeverity.HIGH
                    )
                    
                    if recovered:
                        result.warnings.append(f"Error recovered: {recovery_action}")
                        if self.debug_mode:
                            print(f"[Time-Window Engine]   ✓ Error recovered: {recovery_action}")
                    else:
                        result.errors.append(f"Time-window scanning error: {error_message}")
                        if self.debug_mode:
                            print(f"[Time-Window Engine]   ❌ Error recovery failed: {recovery_action}")
                else:
                    result.errors.append(f"Time-window scanning error: {error_message}")
                
                self.progress_tracker.report_error(f"Scanning error: {error_message}")
                
                if self.debug_mode:
                    import traceback
                    result.errors.append(f"Stack trace:\n{traceback.format_exc()}")
        
        finally:
            # Task 23: End profiling operation (Requirements 1.1, 1.3)
            try:
                if self._profiling_enabled:
                    self.profiler.end_operation("_scan_time_windows")
                    self.profiler.record_memory_checkpoint("scan_end")
                    
                    # Generate and log performance report if debug mode
                    if self.debug_mode:
                        perf_report = self.profiler.get_performance_report()
                        print(f"\n[Time-Window Engine] 📊 Performance Profiling Report:")
                        print(f"[Time-Window Engine]   Total execution time: {perf_report.total_execution_time:.2f}s")
                        print(f"[Time-Window Engine]   Peak memory: {perf_report.peak_memory_mb:.1f}MB")
                        
                        # Show top 5 operations by time
                        sorted_ops = sorted(
                            perf_report.operation_stats.items(),
                            key=lambda x: x[1].total_time_seconds,
                            reverse=True
                        )[:5]
                        
                        if sorted_ops:
                            print(f"[Time-Window Engine]   Top operations by time:")
                            for op_name, stats in sorted_ops:
                                print(f"[Time-Window Engine]     • {op_name}: {stats.total_time_seconds:.2f}s "
                                     f"({stats.call_count} calls, avg {stats.average_time_seconds:.3f}s)")
            except Exception as prof_error:
                if self.debug_mode:
                    print(f"[Time-Window Engine] Profiler error: {prof_error}")
            
            # Cleanup
            self._cleanup_feather_queries()
            
            # Record execution time
            result.execution_duration_seconds = time.time() - start_time
            
            # Update feather_metadata with matches_created counts and identities_found
            # Count how many matches each feather contributed to and unique identities per feather
            if result.matches and result.feather_metadata:
                feather_match_counts = {fid: 0 for fid in result.feather_metadata.keys()}
                feather_identities_in_matches = {fid: set() for fid in result.feather_metadata.keys()}
                feather_identities_extracted = {fid: set() for fid in result.feather_metadata.keys()}
                
                # First pass: Track all unique identities extracted from each feather
                # This happens by examining all matches and their feather_records
                for match in result.matches:
                    if hasattr(match, 'feather_records') and match.feather_records:
                        # Get identity value from match
                        identity_value = getattr(match, 'matched_application', None)
                        
                        for fid in match.feather_records.keys():
                            if fid in feather_identities_extracted and identity_value:
                                # Track all identities that were extracted from this feather
                                feather_identities_extracted[fid].add(identity_value)
                
                # Second pass: Track identities that participated in matches and count matches
                for match in result.matches:
                    if hasattr(match, 'feather_records') and match.feather_records:
                        # Get identity value from match
                        identity_value = getattr(match, 'matched_application', None)
                        
                        for fid in match.feather_records.keys():
                            if fid in feather_match_counts:
                                feather_match_counts[fid] += 1
                                # Track unique identities that participated in matches
                                if identity_value and fid in feather_identities_in_matches:
                                    feather_identities_in_matches[fid].add(identity_value)
                
                # Update feather_metadata with correct statistics
                for fid in result.feather_metadata.keys():
                    if fid in feather_match_counts:
                        result.feather_metadata[fid]['matches_created'] = feather_match_counts[fid]
                        # FIXED: identities_found = unique identities that participated in matches
                        result.feather_metadata[fid]['identities_found'] = len(feather_identities_in_matches[fid])
                        # FIXED: identities_extracted = all unique identities extracted from this feather
                        result.feather_metadata[fid]['identities_extracted'] = len(feather_identities_extracted[fid])
                
                if self.debug_mode:
                    print(f"[Time-Window Engine] 📊 Feather statistics:")
                    for fid in sorted(result.feather_metadata.keys()):
                        if fid in feather_match_counts and feather_match_counts[fid] > 0:
                            matches = feather_match_counts[fid]
                            identities_found = len(feather_identities_in_matches[fid])
                            identities_extracted = len(feather_identities_extracted[fid])
                            print(f"  • {fid}: {identities_extracted:,} extracted, {identities_found:,} in matches, {matches:,} match contributions")
            
            # Calculate and log total feather data size
            total_feather_data_size = 0
            if result.matches:
                import json
                for match in result.matches:
                    if hasattr(match, 'feather_records') and match.feather_records:
                        feather_json = json.dumps(match.feather_records)
                        total_feather_data_size += len(feather_json.encode('utf-8'))
                
                # Log feather data size
                size_mb = total_feather_data_size / (1024 * 1024)
                if size_mb > 100:
                    print(f"[Time-Window Engine] ⚠️ Large feather data size: {size_mb:.2f} MB")
                    result.warnings.append(f"Large feather data size: {size_mb:.2f} MB - consider data reduction strategies")
                elif self.debug_mode:
                    print(f"[Time-Window Engine] 📊 Total feather data size: {size_mb:.2f} MB")
            
            # Print completion summary (Requirement 6.6)
            print(f"\n[Time-Window Engine] ✅ Complete!")
            print(f"[Time-Window Engine] ✅ Processed {total_windows:,} time windows")
            
            # Add summary of records that were loaded but not parsed into matches
            if result.feather_metadata:
                total_records_loaded = sum(meta.get('records_processed', 0) for meta in result.feather_metadata.values())
                total_records_in_matches = sum(
                    sum(len(records) for records in match.feather_records.values())
                    for match in result.matches
                ) if result.matches else 0
                
                records_not_parsed = total_records_loaded - total_records_in_matches
                
                if records_not_parsed > 0:
                    parse_rate = (total_records_in_matches / total_records_loaded * 100) if total_records_loaded > 0 else 0
                    print(f"\n[Time-Window Engine] 📊 Record Processing Summary:")
                    print(f"[Time-Window Engine]   • Total records loaded: {total_records_loaded:,}")
                    print(f"[Time-Window Engine]   • Records in matches: {total_records_in_matches:,} ({parse_rate:.1f}%)")
                    print(f"[Time-Window Engine]   • Records not parsed: {records_not_parsed:,} ({100-parse_rate:.1f}%)")
                    print(f"[Time-Window Engine]   ℹ️  Records not parsed were likely filtered by minimum_matches={wing.correlation_rules.minimum_matches}")
                    print(f"[Time-Window Engine]   ℹ️  To include all records, set minimum_matches=1 in wing configuration")
            
            # Task 23: Add window statistics if available (Requirements 3.3, 9.3, 9.4)
            if self.scanning_config.track_empty_window_stats:
                windows_with_data = self.window_processing_stats.windows_with_data
                empty_windows = self.window_processing_stats.empty_windows_skipped
                skip_rate = self.window_processing_stats.skip_rate_percentage
                print(f"[Time-Window Engine] ✅ Windows with correlations: {windows_with_data:,}")
                print(f"[Time-Window Engine] ⏭️ Empty windows skipped: {empty_windows:,} ({skip_rate:.1f}%)")
                
                # Task 23: Add EmptyWindowDetector statistics if available (Requirements 3.3)
                if self.empty_window_detector:
                    detector_stats = self.empty_window_detector.get_skip_statistics()
                    if detector_stats.time_saved_seconds > 0:
                        print(f"[Time-Window Engine] ⚡ Time saved by skipping: ~{detector_stats.time_saved_seconds:.1f}s")
                    
                    # Log detector efficiency
                    if self.debug_mode and detector_stats.total_windows_checked > 0:
                        print(f"[Time-Window Engine] 📊 Empty window detection:")
                        print(f"[Time-Window Engine]   • Windows checked: {detector_stats.total_windows_checked:,}")
                        print(f"[Time-Window Engine]   • Empty found: {detector_stats.empty_windows_found:,}")
                        print(f"[Time-Window Engine]   • Skip rate: {detector_stats.skip_rate_percentage:.1f}%")
            
            # Count unique identities and total records from matches
            if result.total_matches > 0:
                # Each match represents one unique identity
                unique_identities = result.total_matches
                
                # Calculate total records across all matches
                total_records = 0
                if hasattr(result, 'matches') and result.matches:
                    for match in result.matches:
                        if hasattr(match, 'feather_records') and match.feather_records:
                            total_records += sum(len(records) for records in match.feather_records.values())
                
                print(f"[Time-Window Engine] 🔗 Total unique identities: {unique_identities:,}")
                print(f"[Time-Window Engine] 📊 Total records correlated: {total_records:,}")
            
            print(f"[Time-Window Engine] ✅ Correlation complete")
            
            # Display processing time with formatted duration
            processing_time_minutes = result.execution_duration_seconds / 60
            processing_time_str = self._format_time_duration(processing_time_minutes)
            print(f"[Time-Window Engine] ⏱️ Processing Time: {processing_time_str}")
            
            if result.warnings:
                print(f"[Time-Window Engine] ⚠️ Warnings: {len(result.warnings)}")
            if result.errors:
                print(f"[Time-Window Engine] ❌ Errors: {len(result.errors)}")
            
            if self.streaming_mode_active:
                print(f"[Time-Window Engine] 💾 Streaming mode: Results saved to database")
            
            print("="*70 + "\n")
            
            # Complete performance monitoring
            performance_report = self.performance_monitor.complete_execution()
            
            # Add to performance analyzer for advanced analysis
            self.performance_analyzer.add_performance_report(performance_report)
            
            # Add performance metrics to result
            result.performance_metrics = self.performance_monitor.get_detailed_report()
            
            # Add advanced analysis if available
            if hasattr(self, 'performance_analyzer'):
                result.performance_insights = self.performance_analyzer.generate_performance_insights()
                result.complexity_analysis = self.performance_analyzer.analyze_algorithm_complexity()
            
            # Add comprehensive performance analysis
            result.performance_analysis = self.performance_analyzer.analyze_performance_report(performance_report)
            
            # Generate performance summary
            result.performance_summary = generate_performance_report_summary(performance_report)
            
            # Log performance summary if debug mode
            if self.debug_mode:
                print("\n" + "="*60)
                print("PERFORMANCE ANALYSIS SUMMARY")
                print("="*60)
                print(result.performance_summary)
                print("="*60)
                
                # Task 23: Add optimization components summary (Requirements 9.3, 9.4)
                print("\n" + "="*60)
                print("OPTIMIZATION COMPONENTS SUMMARY")
                print("="*60)
                
                # Profiling summary
                if self._profiling_enabled:
                    print("✓ Performance Profiling: ENABLED")
                    perf_report = self.profiler.get_performance_report()
                    print(f"  • Total operations tracked: {len(perf_report.operation_stats)}")
                    print(f"  • Memory checkpoints: {len(perf_report.memory_checkpoints)}")
                else:
                    print("○ Performance Profiling: DISABLED")
                
                # Empty window detection summary
                if self.empty_window_detector and self.performance_config.enable_empty_window_skipping:
                    detector_stats = self.empty_window_detector.get_skip_statistics()
                    print("✓ Empty Window Detection: ENABLED")
                    print(f"  • Windows checked: {detector_stats.total_windows_checked:,}")
                    print(f"  • Empty windows found: {detector_stats.empty_windows_found:,}")
                    print(f"  • Skip rate: {detector_stats.skip_rate_percentage:.1f}%")
                    print(f"  • Time saved: {detector_stats.time_saved_seconds:.1f}s")
                else:
                    print("○ Empty Window Detection: DISABLED")
                
                # Memory monitoring summary
                if self.memory_monitor:
                    print("✓ Memory Monitoring: ENABLED")
                    print(f"  • Threshold: {self.memory_monitor.threshold_mb:.0f}MB")
                    print(f"  • Streaming mode: {'ACTIVE' if self.streaming_mode_active else 'INACTIVE'}")
                else:
                    print("○ Memory Monitoring: DISABLED")
                
                # Parallel processing summary
                if self.enable_parallel_processing:
                    print("✓ Parallel Processing: ENABLED")
                    print(f"  • Max workers: {self.max_workers}")
                    if self.use_parallel_coordinator:
                        print(f"  • Mode: ParallelCoordinator")
                    else:
                        print(f"  • Mode: ParallelWindowProcessor")
                else:
                    print("○ Parallel Processing: DISABLED")
                
                # Cache statistics summary
                if self.feather_queries:
                    total_cache_hits = 0
                    total_cache_misses = 0
                    for query in self.feather_queries.values():
                        if hasattr(query, '_cache_stats'):
                            total_cache_hits += query._cache_stats.get('hits', 0)
                            total_cache_misses += query._cache_stats.get('misses', 0)
                    
                    if total_cache_hits + total_cache_misses > 0:
                        cache_hit_rate = (total_cache_hits / (total_cache_hits + total_cache_misses)) * 100
                        print("✓ Query Caching: ACTIVE")
                        print(f"  • Cache hits: {total_cache_hits:,}")
                        print(f"  • Cache misses: {total_cache_misses:,}")
                        print(f"  • Hit rate: {cache_hit_rate:.1f}%")
                
                # Timestamp caching summary
                if hasattr(self, 'timestamp_utc_cache'):
                    print("✓ Timestamp Caching: ENABLED")
                    print(f"  • UTC cache size: {self.timestamp_utc_cache.max_size:,}")
                    print(f"  • Parse cache size: {self.timestamp_parse_cache.max_size:,}")
                
                print("="*60)
        
        return result
    
    def _load_feathers(self, wing: Wing, feather_paths: Dict[str, str], result: CorrelationResult):
        """Load all feather databases and create optimized query managers with comprehensive error handling"""
        import sys
        total_feathers = len(wing.feathers)
        
        for idx, feather_spec in enumerate(wing.feathers, 1):
            feather_id = feather_spec.feather_id
            
            # Print progress for each feather
            print(f"[Time-Window Engine]   Loading feather {idx}/{total_feathers}: {feather_id}...")
            sys.stdout.flush()
            
            if feather_id not in feather_paths:
                error_msg = f"Missing path for feather: {feather_id}"
                result.errors.append(error_msg)
                print(f"[Time-Window Engine]     ❌ {error_msg}")
                sys.stdout.flush()
                continue
            
            db_path = feather_paths[feather_id]
            
            # Check if file exists
            if not Path(db_path).exists():
                error_msg = f"Feather database not found: {db_path}"
                result.errors.append(error_msg)
                print(f"[Time-Window Engine]     ❌ {error_msg}")
                sys.stdout.flush()
                continue
            
            try:
                # Create feather loader with error handling
                loader = FeatherLoader(db_path)
                
                # Set feather_id on loader for error tracking
                loader.feather_id = feather_id
                
                # Test connection before proceeding
                try:
                    loader.connect()
                    # Test basic query to ensure database is accessible
                    test_count = loader.get_record_count()
                    print(f"[Time-Window Engine]     ✓ Connected: {test_count:,} records")
                    sys.stdout.flush()
                except Exception as conn_error:
                    error_msg = f"Failed to connect to feather {feather_id}: {str(conn_error)}"
                    result.errors.append(error_msg)
                    print(f"[Time-Window Engine]     ❌ Connection failed: {conn_error}")
                    sys.stdout.flush()
                    continue
                
                # Create optimized query manager with error handling
                print(f"[Time-Window Engine]     Creating query manager...")
                sys.stdout.flush()
                query_manager = OptimizedFeatherQuery(loader, debug_mode=self.debug_mode, profiler=self.profiler)
                
                # Task 21: Apply cache configuration from performance config (Requirement 8.3)
                query_manager.configure_cache(
                    max_size_mb=self.performance_config.query_cache_size_mb,
                    max_entries=100  # Keep default max entries
                )
                
                self.feather_queries[feather_id] = query_manager
                
                result.feathers_processed += 1
                
                # Collect feather metadata with error handling
                try:
                    record_count = loader.get_record_count()
                    timestamp_range = query_manager.get_timestamp_range()
                    
                    result.feather_metadata[feather_id] = {
                        'feather_name': feather_id,  # Requirement 7.2
                        'artifact_type': loader.artifact_type or feather_spec.artifact_type,
                        'database_path': db_path,
                        'records_processed': record_count,  # Requirement 7.2 (renamed from total_records)
                        'total_records': record_count,  # Keep for backward compatibility
                        'identities_extracted': 0,  # Will be calculated during window processing
                        'identities_found': 0,  # Will be calculated from matches (for GUI compatibility)
                        'timestamp_column': query_manager.timestamp_column,
                        'timestamp_format': query_manager.timestamp_format,
                        'timestamp_range': {
                            'min': timestamp_range[0].isoformat() if timestamp_range[0] else None,
                            'max': timestamp_range[1].isoformat() if timestamp_range[1] else None
                        },
                        'matches_created': 0,  # Requirement 7.2 - will be updated during correlation
                        'health_status': query_manager.get_health_status(),
                        'error_statistics': query_manager.get_error_statistics()
                    }
                    
                    print(f"[Time-Window Engine]     ✓ Metadata loaded (ts_col: {query_manager.timestamp_column})")
                    sys.stdout.flush()
                    
                    if self.debug_mode:
                        print(f"[TimeWindow] Loaded {feather_id}: {record_count} records, "
                              f"timestamp_column={query_manager.timestamp_column}, "
                              f"format={query_manager.timestamp_format}")
                        
                        # Log any database errors encountered during initialization
                        error_stats = query_manager.get_error_statistics()
                        if error_stats['total_errors'] > 0:
                            print(f"[TimeWindow] {feather_id} had {error_stats['total_errors']} initialization errors "
                                  f"(success rate: {error_stats['success_rate_percent']:.1f}%)")
                
                except Exception as metadata_error:
                    # Feather loaded but metadata collection failed - continue with warnings
                    warning_msg = f"Feather {feather_id} loaded but metadata collection failed: {str(metadata_error)}"
                    result.warnings.append(warning_msg)
                    if self.debug_mode:
                        print(f"[TimeWindow] Warning: {warning_msg}")
                    
                    # Add minimal metadata
                    result.feather_metadata[feather_id] = {
                        'feather_name': feather_id,  # Requirement 7.2
                        'artifact_type': feather_spec.artifact_type,
                        'database_path': db_path,
                        'records_processed': 0,  # Requirement 7.2
                        'total_records': 0,
                        'identities_found': 0,  # For GUI compatibility
                        'timestamp_column': None,
                        'timestamp_format': 'unknown',
                        'matches_created': 0,  # Requirement 7.2
                        'error': str(metadata_error)
                    }
                
            except Exception as e:
                error_msg = f"Failed to load feather {feather_id}: {str(e)}"
                result.errors.append(error_msg)
                if self.debug_mode:
                    print(f"[TimeWindow] {error_msg}")
                    import traceback
                    print(f"[TimeWindow] Stack trace: {traceback.format_exc()}")
        
        # Log summary of feather loading
        if self.debug_mode:
            total_feathers = len(wing.feathers)
            loaded_feathers = result.feathers_processed
            failed_feathers = total_feathers - loaded_feathers
            
            print(f"[TimeWindow] Feather loading summary: {loaded_feathers}/{total_feathers} loaded successfully")
            if failed_feathers > 0:
                print(f"[TimeWindow] {failed_feathers} feathers failed to load - correlation will continue with available feathers")
            
            # Check if we have enough feathers for correlation
            # minimum_matches represents the minimum number of feathers required
            minimum_feathers = wing.correlation_rules.minimum_matches
            if loaded_feathers < minimum_feathers:
                error_msg = f"Insufficient feathers loaded ({loaded_feathers}) for correlation (minimum required: {minimum_feathers})"
                result.errors.append(error_msg)
                print(f"[TimeWindow] Critical: {error_msg}")
        
        # Add feather loading statistics to result
        result.feather_loading_stats = {
            'total_feathers': len(wing.feathers),
            'loaded_successfully': result.feathers_processed,
            'failed_to_load': len(wing.feathers) - result.feathers_processed,
            'loading_errors': len([e for e in result.errors if 'feather' in e.lower()]),
            'loading_warnings': len([w for w in result.warnings if 'feather' in w.lower()])
        }
    
    def _normalize_datetime_to_utc(self, dt: datetime) -> datetime:
        """
        Normalize a datetime to timezone-aware UTC.
        
        This ensures consistent timezone handling when comparing datetimes from
        different sources (FilterConfig vs database).
        
        Uses caching to avoid redundant conversions for identical input values.
        Requirements: 6.3, 7.3
        
        Args:
            dt: Datetime object (timezone-aware or naive)
            
        Returns:
            Timezone-aware datetime in UTC
        """
        if dt is None:
            return None
        
        # Check cache first
        cached_result = self.timestamp_utc_cache.get(dt)
        if cached_result is not None:
            return cached_result
        
        # Perform conversion
        if dt.tzinfo is not None:
            # If already timezone-aware, convert to UTC
            utc_dt = dt.astimezone(datetime.timezone.utc) if hasattr(datetime, 'timezone') else dt
        else:
            # If timezone-naive, assume UTC
            from datetime import timezone
            utc_dt = dt.replace(tzinfo=timezone.utc)
        
        # Cache the result
        self.timestamp_utc_cache.put(dt, utc_dt)
        
        return utc_dt
    
    def _detect_actual_time_range(self) -> TimeRangeDetectionResult:
        """
        Detect actual time range from feather data with FilterConfig integration and outlier filtering.
        
        Priority Order:
        1. Use FilterConfig.time_period_start/end if provided (user override)
        2. Auto-detect from feather data with statistical outlier filtering
        3. Apply max_time_range_years limit if needed
        
        Statistical Outlier Detection:
        - Collects all timestamps from all feathers
        - Uses IQR (Interquartile Range) method to detect outliers
        - Automatically excludes false timestamps (e.g., 1999/2000 when bulk data is from 2024)
        - Logs excluded outliers for transparency
        
        Returns:
            TimeRangeDetectionResult with detected range and metadata
        """
        detection_start = time.time()
        feather_ranges = {}
        warnings = []
        
        # Priority 1: Check FilterConfig for user-specified time range
        if self.filters.time_period_start and self.filters.time_period_end:
            # User has specified exact time range via FilterConfig
            # Normalize to UTC for consistent comparison
            earliest = self._normalize_datetime_to_utc(self.filters.time_period_start)
            latest = self._normalize_datetime_to_utc(self.filters.time_period_end)
            
            # CRITICAL: Validate that start is before end
            if earliest > latest:
                error_msg = (
                    f"Invalid time range: Start time ({earliest.strftime('%Y-%m-%d %H:%M:%S')}) "
                    f"is after end time ({latest.strftime('%Y-%m-%d %H:%M:%S')}). "
                    f"Please check your time filter settings."
                )
                print(f"[Time-Window Engine] ❌ ERROR: {error_msg}")
                raise ValueError(error_msg)
            
            # Requirement 6.7: Log time filter when applied
            total_span_seconds = (latest - earliest).total_seconds()
            print(f"[Time-Window Engine] 🔍 Time Filter: {earliest.strftime('%Y-%m-%d %H:%M:%S')} to {latest.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if self.debug_mode:
                print(f"[TimeWindow] Using FilterConfig time range:")
                print(f"  Start: {earliest}")
                print(f"  End: {latest}")
            
            # Still query feather ranges for validation
            for feather_id, query_manager in self.feather_queries.items():
                min_ts, max_ts = query_manager.get_timestamp_range()
                if min_ts and max_ts:
                    # Normalize database timestamps too
                    min_ts = self._normalize_datetime_to_utc(min_ts)
                    max_ts = self._normalize_datetime_to_utc(max_ts)
                    feather_ranges[feather_id] = (min_ts, max_ts)
            
            # Warn if FilterConfig range is outside actual data range
            if feather_ranges:
                actual_earliest = min(r[0] for r in feather_ranges.values())
                actual_latest = max(r[1] for r in feather_ranges.values())
                
                if earliest < actual_earliest:
                    warnings.append(
                        f"FilterConfig start ({earliest}) is before earliest data "
                        f"({actual_earliest}). Empty windows will be skipped."
                    )
                if latest > actual_latest:
                    warnings.append(
                        f"FilterConfig end ({latest}) is after latest data "
                        f"({actual_latest}). Empty windows will be skipped."
                    )
        
        elif self.filters.time_period_start:
            # Only start time specified - use it as start, auto-detect end with outlier filtering
            earliest = self._normalize_datetime_to_utc(self.filters.time_period_start)
            
            # Query feathers for end time
            for feather_id, query_manager in self.feather_queries.items():
                min_ts, max_ts = query_manager.get_timestamp_range()
                if min_ts and max_ts:
                    # Normalize database timestamps
                    min_ts = self._normalize_datetime_to_utc(min_ts)
                    max_ts = self._normalize_datetime_to_utc(max_ts)
                    feather_ranges[feather_id] = (min_ts, max_ts)
            
            if not feather_ranges:
                raise ValueError("No timestamp data found in any feather")
            
            # Apply outlier filtering to end times
            all_max_timestamps = [r[1] for r in feather_ranges.values()]
            filtered_max, outliers_removed = self._filter_timestamp_outliers(all_max_timestamps, filter_high=True)
            
            latest = max(filtered_max) if filtered_max else max(all_max_timestamps)
            
            if outliers_removed > 0:
                warnings.append(f"Excluded {outliers_removed} outlier end timestamps (likely false timestamps)")
            
            if self.debug_mode:
                print(f"[TimeWindow] Using FilterConfig start, auto-detected end:")
                print(f"  Start: {earliest} (from FilterConfig)")
                print(f"  End: {latest} (auto-detected, {outliers_removed} outliers excluded)")
        
        elif self.filters.time_period_end:
            # Only end time specified - auto-detect start with outlier filtering, use specified end
            latest = self._normalize_datetime_to_utc(self.filters.time_period_end)
            
            # Query feathers for start time
            for feather_id, query_manager in self.feather_queries.items():
                min_ts, max_ts = query_manager.get_timestamp_range()
                if min_ts and max_ts:
                    # Normalize database timestamps
                    min_ts = self._normalize_datetime_to_utc(min_ts)
                    max_ts = self._normalize_datetime_to_utc(max_ts)
                    feather_ranges[feather_id] = (min_ts, max_ts)
            
            if not feather_ranges:
                raise ValueError("No timestamp data found in any feather")
            
            # Apply outlier filtering to start times
            all_min_timestamps = [r[0] for r in feather_ranges.values()]
            filtered_min, outliers_removed = self._filter_timestamp_outliers(all_min_timestamps, filter_low=True)
            
            earliest = min(filtered_min) if filtered_min else min(all_min_timestamps)
            
            if outliers_removed > 0:
                warnings.append(f"Excluded {outliers_removed} outlier start timestamps (likely false timestamps)")
            
            if self.debug_mode:
                print(f"[TimeWindow] Using auto-detected start, FilterConfig end:")
                print(f"  Start: {earliest} (auto-detected, {outliers_removed} outliers excluded)")
                print(f"  End: {latest} (from FilterConfig)")
        
        else:
            # Priority 2: Auto-detect from feather data with statistical outlier filtering
            for feather_id, query_manager in self.feather_queries.items():
                min_ts, max_ts = query_manager.get_timestamp_range()
                if min_ts and max_ts:
                    # Normalize database timestamps
                    min_ts = self._normalize_datetime_to_utc(min_ts)
                    max_ts = self._normalize_datetime_to_utc(max_ts)
                    feather_ranges[feather_id] = (min_ts, max_ts)
            
            if not feather_ranges:
                raise ValueError("No timestamp data found in any feather")
            
            # Collect all timestamps for statistical analysis
            all_min_timestamps = [r[0] for r in feather_ranges.values()]
            all_max_timestamps = [r[1] for r in feather_ranges.values()]
            
            # Apply outlier filtering to both start and end times
            filtered_min, outliers_removed_min = self._filter_timestamp_outliers(all_min_timestamps, filter_low=True)
            filtered_max, outliers_removed_max = self._filter_timestamp_outliers(all_max_timestamps, filter_high=True)
            
            # Use filtered timestamps if available, otherwise fall back to original
            earliest = min(filtered_min) if filtered_min else min(all_min_timestamps)
            latest = max(filtered_max) if filtered_max else max(all_max_timestamps)
            
            total_outliers = outliers_removed_min + outliers_removed_max
            
            if total_outliers > 0:
                warnings.append(
                    f"Excluded {total_outliers} outlier timestamps "
                    f"({outliers_removed_min} early, {outliers_removed_max} late) - likely false timestamps"
                )
                
                if self.debug_mode:
                    print(f"[TimeWindow] Auto-detected time range with outlier filtering:")
                    print(f"  Start: {earliest} ({outliers_removed_min} outliers excluded)")
                    print(f"  End: {latest} ({outliers_removed_max} outliers excluded)")
                    print(f"  Original range would have been: {min(all_min_timestamps)} to {max(all_max_timestamps)}")
            else:
                if self.debug_mode:
                    print(f"[TimeWindow] Auto-detected time range from data:")
                    print(f"  Start: {earliest}")
                    print(f"  End: {latest}")
                    print(f"  No outliers detected")
        
        # Calculate span
        span_days = (latest - earliest).total_seconds() / 86400
        
        # Apply max_time_range_years limit to prevent false timestamps from expanding range
        if span_days / 365.25 > self.scanning_config.max_time_range_years:
            # Cap the range to max_time_range_years by adjusting the start time
            max_span_days = self.scanning_config.max_time_range_years * 365.25
            earliest = latest - timedelta(days=max_span_days)
            
            warnings.append(
                f"Time range exceeded {self.scanning_config.max_time_range_years} years "
                f"({span_days/365.25:.1f} years detected). "
                f"Limited to {self.scanning_config.max_time_range_years} years starting from {earliest.strftime('%Y-%m-%d')}. "
                f"This prevents false timestamps from expanding the scan range."
            )
            
            # Recalculate span after limiting
            span_days = (latest - earliest).total_seconds() / 86400
            
            if self.debug_mode:
                print(f"[TimeWindow] Applied {self.scanning_config.max_time_range_years}-year limit:")
                print(f"  New start: {earliest}")
                print(f"  End: {latest}")
                print(f"  New span: {span_days:.1f} days ({span_days/365.25:.2f} years)")
        
        detection_time = time.time() - detection_start
        
        return TimeRangeDetectionResult(
            earliest_timestamp=earliest,
            latest_timestamp=latest,
            total_span_days=span_days,
            feather_ranges=feather_ranges,
            detection_time_seconds=detection_time,
            warnings=warnings
        )
    
    def _filter_timestamp_outliers(self, timestamps: List[datetime], 
                                   filter_low: bool = False, 
                                   filter_high: bool = False) -> Tuple[List[datetime], int]:
        """
        Filter outlier timestamps using combined statistical and heuristic methods.
        
        This detects and removes false timestamps like 1999/2000 when the bulk of data
        is from 2024. Uses two methods:
        1. IQR (Interquartile Range) statistical analysis
        2. 20-year rule: Timestamps more than 20 years older than the latest are marked as false
        
        Args:
            timestamps: List of datetime objects to filter
            filter_low: If True, filter out low outliers (e.g., 1999/2000)
            filter_high: If True, filter out high outliers (e.g., future dates)
            
        Returns:
            Tuple of (filtered_timestamps, number_of_outliers_removed)
        """
        if len(timestamps) < 4:
            # Need at least 4 timestamps for meaningful statistical analysis
            return timestamps, 0
        
        # Convert timestamps to Unix timestamps for numerical analysis
        unix_timestamps = [ts.timestamp() for ts in timestamps]
        unix_timestamps.sort()
        
        # Calculate quartiles for IQR method
        n = len(unix_timestamps)
        q1_idx = n // 4
        q3_idx = 3 * n // 4
        
        q1 = unix_timestamps[q1_idx]
        q3 = unix_timestamps[q3_idx]
        iqr = q3 - q1
        
        # Calculate outlier boundaries using IQR method
        # Using 1.5 * IQR is standard for outlier detection
        lower_bound_iqr = q1 - 1.5 * iqr
        upper_bound_iqr = q3 + 1.5 * iqr
        
        # Calculate 20-year rule boundary
        # If a timestamp is more than 20 years older than the latest, it's likely false
        latest_timestamp = max(unix_timestamps)
        twenty_years_seconds = 20 * 365.25 * 24 * 3600  # 20 years in seconds
        lower_bound_20yr = latest_timestamp - twenty_years_seconds
        
        # Filter outliers using both methods
        filtered_unix = []
        outliers_removed = 0
        outliers_by_method = {'iqr': 0, '20yr_rule': 0, 'both': 0}
        
        for unix_ts in unix_timestamps:
            is_outlier_iqr = False
            is_outlier_20yr = False
            
            # Check IQR method
            if filter_low and unix_ts < lower_bound_iqr:
                is_outlier_iqr = True
            if filter_high and unix_ts > upper_bound_iqr:
                is_outlier_iqr = True
            
            # Check 20-year rule (only for low outliers)
            if filter_low and unix_ts < lower_bound_20yr:
                is_outlier_20yr = True
            
            # Mark as outlier if either method flags it
            is_outlier = is_outlier_iqr or is_outlier_20yr
            
            if is_outlier:
                outliers_removed += 1
                
                # Track which method detected it
                if is_outlier_iqr and is_outlier_20yr:
                    outliers_by_method['both'] += 1
                elif is_outlier_iqr:
                    outliers_by_method['iqr'] += 1
                elif is_outlier_20yr:
                    outliers_by_method['20yr_rule'] += 1
                
                if self.debug_mode:
                    outlier_dt = datetime.fromtimestamp(unix_ts)
                    latest_dt = datetime.fromtimestamp(latest_timestamp)
                    years_diff = (latest_timestamp - unix_ts) / (365.25 * 24 * 3600)
                    
                    method = []
                    if is_outlier_iqr:
                        method.append("IQR")
                    if is_outlier_20yr:
                        method.append(f"20yr rule ({years_diff:.1f} years old)")
                    
                    print(f"[TimeWindow] Excluding outlier timestamp: {outlier_dt} "
                          f"(detected by: {', '.join(method)})")
            else:
                filtered_unix.append(unix_ts)
        
        # Convert back to datetime objects (preserve timezone awareness)
        from datetime import timezone
        filtered_timestamps = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in filtered_unix]
        
        # Log detection method statistics
        if self.debug_mode and outliers_removed > 0:
            print(f"[TimeWindow] Outlier detection summary:")
            print(f"  Total outliers: {outliers_removed}")
            print(f"  Detected by IQR only: {outliers_by_method['iqr']}")
            print(f"  Detected by 20-year rule only: {outliers_by_method['20yr_rule']}")
            print(f"  Detected by both methods: {outliers_by_method['both']}")
        
        # If we filtered out everything, return original (safety check)
        if not filtered_timestamps:
            if self.debug_mode:
                print(f"[TimeWindow] Warning: Outlier filtering removed all timestamps, using original data")
            return timestamps, 0
        
        return filtered_timestamps, outliers_removed
    
    def _determine_time_range(self, result: Optional[CorrelationResult] = None) -> Tuple[datetime, datetime]:
        """
        Determine the overall time range for scanning.
        
        Uses the new _detect_actual_time_range method with FilterConfig integration.
        This method integrates automatic time range detection to avoid processing
        millions of empty windows from year 2000.
        
        Args:
            result: Optional CorrelationResult to add warnings and recommendations to
        
        Returns:
            Tuple of (start_time, end_time) for scanning
        """
        # Use new detection method if auto-detection is enabled
        if self.scanning_config.auto_detect_time_range:
            print(f"[Time-Window Engine] 🔍 Auto-detecting time range from data...")
            try:
                detection_result = self._detect_actual_time_range()
                
                # Store detection result for statistics reporting
                self._time_range_detection_result = detection_result
                
                # Update window processing stats with detection time
                self.window_processing_stats.time_range_detection_seconds = detection_result.detection_time_seconds
                
                # Log warnings if any (always show warnings, not just in debug mode)
                for warning in detection_result.warnings:
                    print(f"[TimeWindow] ⚠️ Warning: {warning}")
                    # Add warning to result object
                    if result:
                        result.warnings.append(f"Time Range: {warning}")
                
                # Log detection summary with enhanced information
                print(f"[TimeWindow] ✓ Time range detection completed in {detection_result.detection_time_seconds:.2f}s")
                print(f"[TimeWindow]   📅 Start: {detection_result.earliest_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[TimeWindow]   📅 End: {detection_result.latest_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[TimeWindow]   ⏱️ Span: {detection_result.total_span_days:.1f} days ({detection_result.get_span_years():.2f} years)")
                
                # Calculate and log estimated window count
                estimated_windows = self._calculate_total_windows(
                    detection_result.earliest_timestamp, 
                    detection_result.latest_timestamp
                )
                print(f"[TimeWindow]   🔢 Estimated windows: {estimated_windows:,}")
                
                # Show feather-specific ranges in debug mode
                if self.debug_mode and detection_result.feather_ranges:
                    print(f"[TimeWindow]   📊 Feather time ranges:")
                    for feather_id, (min_ts, max_ts) in detection_result.feather_ranges.items():
                        span_days = (max_ts - min_ts).total_seconds() / 86400
                        print(f"[TimeWindow]     • {feather_id}: {min_ts.strftime('%Y-%m-%d')} to {max_ts.strftime('%Y-%m-%d')} ({span_days:.1f} days)")
                
                # Warn if FilterConfig range extends beyond actual data
                if detection_result.warnings:
                    print(f"[TimeWindow] ⚠️ {len(detection_result.warnings)} warning(s) detected during time range detection")
                
                # TASK 9: Add validation when detected range exceeds max_time_range_years
                if not detection_result.is_reasonable_range(self.scanning_config.max_time_range_years):
                    warning_msg = (
                        f"Time range spans {detection_result.get_span_years():.1f} years, "
                        f"exceeding recommended maximum of {self.scanning_config.max_time_range_years} years"
                    )
                    print(f"[TimeWindow] ⚠️ Warning: {warning_msg}")
                    print(f"[TimeWindow]   Consider using FilterConfig to limit the range for better performance")
                    
                    # Add warning to result object
                    if result:
                        result.warnings.append(f"Time Range Validation: {warning_msg}")
                
                # TASK 9: Add recommendations for optimal configuration based on dataset
                recommendations = self._generate_configuration_recommendations(
                    detection_result, estimated_windows
                )
                
                if recommendations:
                    print(f"[TimeWindow] 💡 Configuration Recommendations:")
                    for i, recommendation in enumerate(recommendations, 1):
                        print(f"[TimeWindow]   {i}. {recommendation}")
                        # Add recommendations to result object
                        if result:
                            result.warnings.append(f"Recommendation: {recommendation}")
                
                # Performance comparison message
                if estimated_windows > 100000:
                    perf_warning = f"Large window count detected ({estimated_windows:,} windows) - processing may take significant time"
                    print(f"[TimeWindow] ⚠️ {perf_warning}")
                    print(f"[TimeWindow]   Consider narrowing the time range.")
                    if result:
                        result.warnings.append(f"Performance: {perf_warning}")
                elif estimated_windows < 10000:
                    print(f"[TimeWindow] ✓ Reasonable window count - processing should be fast")
                
                return detection_result.earliest_timestamp, detection_result.latest_timestamp
                
            except Exception as e:
                error_msg = f"Auto-detection failed: {e}"
                print(f"[Time-Window Engine] ❌ {error_msg}")
                print(f"[Time-Window Engine] Falling back to legacy time range determination")
                if result:
                    result.warnings.append(f"Time Range Detection: {error_msg}, using fallback method")
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()
        else:
            print(f"[Time-Window Engine] ⚠️ Auto-detection is DISABLED (auto_detect_time_range=False)")
            print(f"[Time-Window Engine] Using legacy time range determination")
        
        # Fallback to legacy behavior (for backward compatibility)
        print(f"[Time-Window Engine] 📅 Legacy Mode: Querying timestamp ranges from feathers...")
        
        earliest_times = []
        latest_times = []
        
        # Get time ranges from all feathers
        for feather_id, query_manager in self.feather_queries.items():
            min_time, max_time = query_manager.get_timestamp_range()
            if min_time:
                earliest_times.append(min_time)
            if max_time:
                latest_times.append(max_time)
        
        # Use configured starting epoch or earliest data
        if self.filters.time_period_start:
            start_time = self.filters.time_period_start
            print(f"[TimeWindow]   Using FilterConfig start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        elif earliest_times:
            # Use the earliest data time, but don't go back further than 1 year from latest data
            earliest_data = min(earliest_times)
            latest_data = max(latest_times) if latest_times else datetime.now()
            one_year_ago = latest_data - timedelta(days=365)
            start_time = max(earliest_data, one_year_ago)
            print(f"[TimeWindow]   Using earliest data time (limited to 1 year): {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            # Default to 30 days ago instead of year 2000
            start_time = datetime.now() - timedelta(days=30)
            print(f"[TimeWindow]   Using default (30 days ago): {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Use configured ending epoch or latest data
        if self.filters.time_period_end:
            end_time = self.filters.time_period_end
            print(f"[TimeWindow]   Using FilterConfig end time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        elif latest_times:
            end_time = max(latest_times)
            print(f"[TimeWindow]   Using latest data time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            end_time = datetime.now()
            print(f"[TimeWindow]   Using current time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Safety check: limit time range to prevent excessive processing
        max_range_days = 365  # Maximum 1 year range
        if (end_time - start_time).days > max_range_days:
            warning_msg = f"Time range too large ({(end_time - start_time).days} days), limiting to {max_range_days} days from end time"
            print(f"[TimeWindow] ⚠️ Warning: {warning_msg}")
            if result:
                result.warnings.append(f"Time Range: {warning_msg}")
            start_time = end_time - timedelta(days=max_range_days)
        
        # Calculate expected windows for user awareness
        total_windows = self._calculate_total_windows(start_time, end_time)
        print(f"[TimeWindow]   🔢 Expected windows: {total_windows:,}")
        
        if total_windows > 10000:
            warning_msg = f"Large number of windows ({total_windows:,}) may take significant time"
            print(f"[TimeWindow] ⚠️ Warning: {warning_msg}")
            if result:
                result.warnings.append(f"Performance: {warning_msg}")
        
        return start_time, end_time
    
    def _generate_configuration_recommendations(self, 
                                               detection_result: TimeRangeDetectionResult,
                                               estimated_windows: int) -> List[str]:
        """
        Generate configuration recommendations based on detected time range and dataset characteristics.
        
        Args:
            detection_result: Time range detection result with metadata
            estimated_windows: Estimated number of windows to process
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        # Recommendation 1: Time range optimization
        if detection_result.get_span_years() > 5:
            recommendations.append(
                f"Time range spans {detection_result.get_span_years():.1f} years. "
                f"Consider using FilterConfig.time_period_start and time_period_end to focus on specific time periods of interest."
            )
        
        # Recommendation 2: Window size optimization based on data density
        if detection_result.feather_ranges:
            # Calculate average data density (records per day estimate)
            total_span_days = detection_result.total_span_days
            if total_span_days > 0:
                # Estimate based on window count
                avg_windows_per_day = estimated_windows / total_span_days
                
                if avg_windows_per_day > 288:  # More than 5-minute windows
                    recommendations.append(
                        f"High temporal resolution detected ({avg_windows_per_day:.0f} windows/day). "
                        f"Consider increasing window_size_minutes (currently {self.window_size_minutes}) "
                        f"to reduce processing time if fine-grained temporal analysis is not required."
                    )
                # Removed: Low temporal resolution warning (user preference)
        
        # Recommendation 3: Parallel processing for large datasets
        if estimated_windows > 1000 and not self.enable_parallel_processing:
            recommendations.append(
                f"Large dataset detected ({estimated_windows:,} windows). "
                f"Enable parallel processing (parallel_window_processing=True) to improve performance."
            )
        
        # Recommendation 4: Memory management for very large datasets
        if estimated_windows > 10000:
            recommendations.append(
                f"Very large dataset detected ({estimated_windows:,} windows). "
                f"Ensure adequate memory_limit_mb is configured (currently {self.memory_limit_mb} MB) "
                f"and consider enabling streaming mode for optimal memory usage."
            )
        
        # Recommendation 5: Scanning interval optimization
        if self.scanning_interval_minutes < self.window_size_minutes:
            overlap_percent = ((self.window_size_minutes - self.scanning_interval_minutes) / self.window_size_minutes) * 100
            recommendations.append(
                f"Window overlap detected ({overlap_percent:.0f}% overlap). "
                f"scanning_interval_minutes ({self.scanning_interval_minutes}) is less than window_size_minutes ({self.window_size_minutes}). "
                f"This creates overlapping windows which may find duplicate correlations. "
                f"Consider setting scanning_interval_minutes equal to window_size_minutes for non-overlapping windows."
            )
        
        # Recommendation 6: FilterConfig range outside actual data
        if detection_result.warnings:
            for warning in detection_result.warnings:
                if "FilterConfig" in warning and ("before earliest" in warning or "after latest" in warning):
                    recommendations.append(
                        f"FilterConfig time range extends beyond actual data. "
                        f"Adjust FilterConfig.time_period_start/end to match actual data range "
                        f"({detection_result.earliest_timestamp.strftime('%Y-%m-%d')} to {detection_result.latest_timestamp.strftime('%Y-%m-%d')}) "
                        f"to avoid processing empty windows."
                    )
                    break  # Only add this recommendation once
        
        return recommendations
    
    def _format_time_duration(self, minutes: float) -> str:
        """
        Format time duration in human-readable format.
        
        Args:
            minutes: Duration in minutes
            
        Returns:
            Formatted string (e.g., "45s", "5.2m", "2.3h")
        """
        if minutes < 1:
            return f"{minutes * 60:.0f}s"
        elif minutes < 60:
            return f"{minutes:.1f}m"
        else:
            return f"{minutes / 60:.1f}h"
    
    def _format_time_window(self, minutes: int) -> str:
        """
        Format time window in both minutes and hours for clarity.
        
        Args:
            minutes: Time window in minutes
            
        Returns:
            Formatted string (e.g., "180 minutes (3.0 hours)")
        """
        hours = minutes / 60
        return f"{minutes} minutes ({hours:.1f} hours)"
    
    def _calculate_total_windows(self, start_time: datetime, end_time: datetime) -> int:
        """Calculate total number of windows to process"""
        total_minutes = (end_time - start_time).total_seconds() / 60
        return int(total_minutes / self.scanning_interval_minutes) + 1
    
    def _generate_time_windows(self, start_time: datetime, end_time: datetime) -> Iterator[TimeWindow]:
        """
        Generate time windows for scanning.
        
        Args:
            start_time: Start of scanning range
            end_time: End of scanning range
            
        Yields:
            TimeWindow objects for processing
        """
        current_time = start_time
        window_counter = 0
        
        while current_time < end_time:
            # Calculate window end
            window_end = current_time + timedelta(minutes=self.window_size_minutes)
            
            # CRITICAL FIX: Clip window end to not exceed the overall end_time
            # This ensures that when a time filter is set, the last window doesn't
            # extend beyond the filter end time and include records outside the range
            window_end = min(window_end, end_time)
            
            yield TimeWindow(
                start_time=current_time,
                end_time=window_end,
                window_id=f"window_{window_counter:06d}",
                records_by_feather={}  # Empty dict, will be populated by query_window
            )
            
            # Advance by scanning interval
            current_time += timedelta(minutes=self.scanning_interval_minutes)
            window_counter += 1
    
    def _normalize_identity(self, identity: str) -> str:
        """
        Normalize identity for grouping by removing symbols and numbers.
        
        This ensures that variations like:
        - "chrome.exe", "chrome", "Chrome.exe" -> "chrome"
        - "app-v1.2.3", "app_v2.0", "app" -> "app"
        - "program (x86)", "program", "Program" -> "program"
        
        Args:
            identity: Raw identity string
            
        Returns:
            Normalized identity string (lowercase, no symbols/numbers)
        """
        import re
        
        # Convert to lowercase
        normalized = identity.lower()
        
        # Remove common file extensions
        extensions = ['.exe', '.dll', '.sys', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.jar', '.msi']
        for ext in extensions:
            if normalized.endswith(ext):
                normalized = normalized[:-len(ext)]
                break
        
        # Remove version numbers and common patterns
        # Examples: "v1.2.3", "version 2.0", "(x86)", "[64bit]"
        normalized = re.sub(r'\s*v?\d+[\d.]*', '', normalized)  # Remove version numbers
        normalized = re.sub(r'\s*\(.*?\)', '', normalized)  # Remove parentheses content
        normalized = re.sub(r'\s*\[.*?\]', '', normalized)  # Remove brackets content
        
        # Remove all symbols and numbers, keep only letters and spaces
        normalized = re.sub(r'[^a-z\s]', '', normalized)
        
        # Remove extra whitespace
        normalized = ' '.join(normalized.split())
        
        # Remove common noise words
        noise_words = ['the', 'a', 'an', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for']
        words = normalized.split()
        words = [w for w in words if w not in noise_words]
        normalized = ' '.join(words)
        
        return normalized.strip()
    
    def _extract_identity_from_record(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Extract identity value from a record with normalization.
        
        Args:
            record: Record to extract identity from
            
        Returns:
            Normalized identity value or None if no identity found
        """
        # Try to find first non-empty identity field from core list
        for field in CORE_IDENTITY_FIELDS:
            if field in record and record[field]:
                value = str(record[field]).strip()
                if value:
                    # Normalize identity for proper grouping
                    # This removes symbols, numbers, and standardizes format
                    return self._normalize_identity(value)
        
        return None
    
    def _correlate_window_records(self, window: TimeWindow, wing: Wing) -> List[CorrelationMatch]:
        """
        Correlate records in a window by grouping them by identity.
        
        OPTIMIZED VERSION (Task 16):
        1. Apply filters BEFORE correlation (Requirement 6.2)
        2. Use identity index with hash map for O(1) lookups
        3. Deduplicate records to avoid redundant processing (Requirement 6.4)
        
        This is the core correlation logic:
        1. Filter records first (optimization)
        2. Deduplicate records (optimization)
        3. Group all records by identity value using hash map
        4. Check minimum feather requirement
        5. Create CorrelationMatch for each identity group
        
        Args:
            window: TimeWindow with populated records
            wing: Wing configuration
            
        Returns:
            List of CorrelationMatch objects
        """
        # Start profiling (Requirements 1.1, 1.4)
        self.profiler.start_operation("_correlate_window_records")
        
        try:
            # OPTIMIZATION 1: Apply filters BEFORE correlation (Requirement 6.2)
            # This reduces the number of records passed to correlation
            filtered_records_by_feather = {}
            total_filtered = 0
            
            for feather_id, records in window.records_by_feather.items():
                # FIXED: Use correct attribute name window_query_manager (Requirements 4.1, 4.2, 4.3)
                if self.window_query_manager and self.window_query_manager.filters:
                    # Apply filters to reduce record set
                    filtered_records = [r for r in records if not self.window_query_manager._should_filter_record(r)]
                    filtered_count = len(records) - len(filtered_records)
                    total_filtered += filtered_count
                    
                    if filtered_count > 0 and self.debug_mode:
                        logger.debug(f"[Correlation Optimization] Filtered {filtered_count}/{len(records)} records from {feather_id} before correlation")
                    
                    filtered_records_by_feather[feather_id] = filtered_records
                else:
                    # No filters or window_query_manager not available, use all records
                    if self.debug_mode and not self.window_query_manager:
                        logger.debug(f"[Correlation Optimization] Skipping filtering for {feather_id} - window_query_manager not available")
                    filtered_records_by_feather[feather_id] = records
            
            # OPTIMIZATION 2: Deduplicate records (Requirement 6.4)
            # Build identity index with deduplication using hash map for O(1) lookups
            identity_groups = {}  # identity_value -> {feather_id: [records]}
            seen_records = set()  # Track seen records to avoid duplicates
            total_duplicates = 0
            
            for feather_id, records in filtered_records_by_feather.items():
                for record in records:
                    # Create a record signature for deduplication
                    # Use identity + timestamp + feather_id as unique key
                    identity = self._extract_identity_from_record(record)
                    
                    if identity:
                        # Create record signature for deduplication
                        timestamp_val = None
                        timestamp_fields = ['timestamp', 'event_time', 'last_run_time', 'access_time', 
                                          'creation_time', 'modification_time', 'last_modified']
                        for ts_field in timestamp_fields:
                            if ts_field in record and record[ts_field]:
                                timestamp_val = record[ts_field]
                                break
                        
                        # Create unique signature
                        record_signature = (identity, feather_id, str(timestamp_val))
                        
                        # Check if we've seen this record before
                        if record_signature in seen_records:
                            total_duplicates += 1
                            if self.debug_mode:
                                logger.debug(f"[Correlation Optimization] Skipped duplicate record: {record_signature}")
                            continue  # Skip duplicate
                        
                        # Mark as seen
                        seen_records.add(record_signature)
                        
                        # OPTIMIZATION 3: Use hash map for O(1) identity lookups
                        # Initialize identity group if needed
                        if identity not in identity_groups:
                            identity_groups[identity] = {}
                        
                        # Initialize feather list if needed
                        if feather_id not in identity_groups[identity]:
                            identity_groups[identity][feather_id] = []
                        
                        # Add record to group
                        identity_groups[identity][feather_id].append(record)
            
            # Log optimization statistics
            if total_filtered > 0 or total_duplicates > 0:
                logger.info(f"[Correlation Optimization] Filtered {total_filtered} records, removed {total_duplicates} duplicates before correlation")
            
            # Create matches from identity groups
            matches = []
            minimum_feathers = wing.correlation_rules.minimum_matches
            
            # Track skipped identities for logging
            skipped_identities = []
            total_skipped_records = 0
            
            for identity_value, feather_records in identity_groups.items():
                # Check if we have enough feathers
                feather_count = len(feather_records)
                
                if feather_count < minimum_feathers:
                    # Track skipped identity
                    record_count = sum(len(records) for records in feather_records.values())
                    skipped_identities.append({
                        'identity': identity_value,
                        'feather_count': feather_count,
                        'record_count': record_count,
                        'feathers': list(feather_records.keys())
                    })
                    total_skipped_records += record_count
                    continue  # Skip - not enough feathers
                
                # Get timestamp from first record (use any feather)
                first_feather_id = list(feather_records.keys())[0]
                first_record = feather_records[first_feather_id][0]
                
                # Try to extract timestamp
                timestamp = None
                timestamp_fields = ['timestamp', 'event_time', 'last_run_time', 'access_time', 
                                  'creation_time', 'modification_time', 'last_modified']
                for ts_field in timestamp_fields:
                    if ts_field in first_record and first_record[ts_field]:
                        timestamp = first_record[ts_field]
                        break
                
                # Use window start time if no timestamp found
                if not timestamp:
                    timestamp = window.start_time
                
                # Convert timestamp to ISO format string
                if isinstance(timestamp, datetime):
                    timestamp_str = timestamp.isoformat()
                else:
                    timestamp_str = str(timestamp)
                
                # Calculate time spread (earliest to latest record in group)
                # Calculate time spread (earliest to latest record in group)
                earliest_time = window.start_time
                latest_time = window.end_time
                time_spread = (latest_time - earliest_time).total_seconds()
                
                # Prepare feather_records dict for CorrelationMatch
                match_feather_records = {}
                for fid, records_list in feather_records.items():
                    # Include ALL records (metadata + actual data) - don't discard anything!
                    match_feather_records[fid] = records_list if records_list else []
                    
                    # Log record inclusion for verification (Requirement 6.3 - Debug only)
                    if records_list:
                        logger.debug(f"[Time-Based Engine] Included {len(records_list)} records for feather_id={fid}")
                        
                        # Debug logging: track record types
                        if self.debug_mode:
                            metadata_count = sum(1 for r in records_list if isinstance(r, dict) and 
                                               set(r.keys()) <= {'key', 'value', '_table', '_feather_id'})
                            actual_data_count = len(records_list) - metadata_count
                            logger.debug(f"[Time-Based Engine]   Record types - Metadata: {metadata_count}, Actual data: {actual_data_count}")
                
                # Create CorrelationMatch (without semantic_data - will be added in post-processing)
                match = CorrelationMatch(
                    match_id=str(uuid.uuid4()),
                    timestamp=timestamp_str,
                    feather_records=match_feather_records,
                    match_score=1.0,  # Identity matches are high confidence
                    feather_count=feather_count,
                    time_spread_seconds=time_spread,
                    anchor_feather_id=first_feather_id,
                    anchor_artifact_type='Unknown',
                    matched_application=identity_value,
                    confidence_score=1.0,
                    confidence_category="High",
                    semantic_data=None  # Will be populated by post-processing semantic phase
                )
                
                matches.append(match)
            
            # Log skipped identities if any
            if skipped_identities:
                print(f"\n[Time-Window Engine] ⚠️  Skipped {len(skipped_identities)} identities ({total_skipped_records:,} records) - found in fewer than {minimum_feathers} feathers")
                
                if self.debug_mode:
                    print(f"[Time-Window Engine] Skipped identities details:")
                    for skip_info in skipped_identities[:10]:  # Show first 10
                        print(f"[Time-Window Engine]   • {skip_info['identity']}: {skip_info['record_count']} records in {skip_info['feather_count']} feather(s) {skip_info['feathers']}")
                    if len(skipped_identities) > 10:
                        print(f"[Time-Window Engine]   ... and {len(skipped_identities) - 10} more")
            
            return matches
        finally:
            # End profiling (Requirements 1.1, 1.3)
            try:
                self.profiler.end_operation("_correlate_window_records")
            except Exception:
                pass  # Silently ignore profiler errors
    
    def _process_window(self, window: TimeWindow, wing: Wing) -> List[CorrelationMatch]:
        """
        Process a single time window - Create correlations by grouping records by identity.
        
        Phase 1: Collect data and create matches by grouping records by identity
        Phase 2: Apply semantic mappings and scoring (done in _apply_semantic_mappings_to_matches)
        
        Task 15: Enhanced with memory monitoring and release
        Requirements: 5.2, 5.3
        
        Args:
            window: TimeWindow to process
            wing: Wing configuration
            
        Returns:
            List of CorrelationMatch objects
        """
        # Task 23: Start profiling (Requirements 1.1, 1.4)
        if self._profiling_enabled:
            self.profiler.start_operation("_process_window")
        
        # Task 15: Record memory checkpoint at window start (Requirements 5.2, 5.3)
        memory_before = None
        if hasattr(self, 'memory_monitor') and self.memory_monitor:
            memory_before = self.memory_monitor.get_current_usage_mb()
        
        # Start window performance monitoring
        window_metrics = self.performance_monitor.start_window_processing(
            window.window_id, window.start_time, window.end_time
        )
        
        try:
            # Step 0: Quick empty window check (if enabled)
            # Requirements 3.1, 3.2, 3.3, 3.4, 3.5
            if self.scanning_config.enable_quick_empty_check and self.empty_window_detector:
                quick_check_start = time.time()
                
                # Use EmptyWindowDetector to check if window is empty
                is_empty = self.empty_window_detector.is_window_empty(window)
                
                quick_check_duration = time.time() - quick_check_start
                
                # Track empty window check time
                if hasattr(self, 'window_processing_stats'):
                    self.window_processing_stats.empty_window_check_time_seconds += quick_check_duration
                
                if is_empty:
                    # Window is empty - skip immediately without full query
                    # Record time saved by skipping (Requirements 3.3)
                    estimated_processing_time = 0.050  # 50ms estimated for full processing
                    self.empty_window_detector.record_time_saved(estimated_processing_time)
                    
                    if window_metrics:
                        self.performance_monitor.complete_window_processing(
                            window.window_id, 0, 0, 0
                        )
                    return []
            
            # Step 1: Query all feathers for records in this window
            query_start_time = time.time()
            populated_window = self.window_query_manager.query_window(window, self.progress_tracker)
            query_duration = time.time() - query_start_time
            
            # Record query timing
            records_found = populated_window.get_total_record_count()
            feathers_queried = len(populated_window.records_by_feather)
            
            if window_metrics:
                self.performance_monitor.record_query_timing(
                    window.window_id, query_duration, "all_feathers", records_found
                )
            
            # Step 2: Skip if window is empty or doesn't meet minimum threshold
            minimum_feathers = wing.correlation_rules.minimum_matches
            if populated_window.is_empty() or not populated_window.has_minimum_feathers(minimum_feathers):
                # Complete window monitoring with no data
                if window_metrics:
                    self.performance_monitor.complete_window_processing(
                        window.window_id, records_found, 0, feathers_queried
                    )
                return []
            
            # Step 3: PHASE 1 - Create correlations by grouping records by identity
            correlation_start_time = time.time()
            
            # Correlate records by identity
            matches = self._correlate_window_records(populated_window, wing)
            
            correlation_duration = time.time() - correlation_start_time
            
            # Record correlation timing
            if window_metrics:
                self.performance_monitor.record_correlation_timing(
                    window.window_id, correlation_duration, 0  # No semantic comparisons yet
                )
            
            # Complete window monitoring
            if window_metrics:
                self.performance_monitor.complete_window_processing(
                    window.window_id, records_found, len(matches), feathers_queried
                )
            
            # Task 15: Monitor memory and trigger actions if needed (Requirements 5.2, 5.3)
            if hasattr(self, 'memory_monitor') and self.memory_monitor:
                memory_status = self.memory_monitor.check_threshold()
                
                # Track memory usage in progress tracker
                if hasattr(self, 'progress_tracker'):
                    self.progress_tracker.memory_usage_mb = memory_status.current_mb
                
                # If memory pressure detected, take action
                if memory_status.should_enable_streaming:
                    # Enable streaming mode if not already active
                    if not self.streaming_mode_active and hasattr(self, '_output_dir') and self._output_dir:
                        self._enable_streaming_mode("Memory threshold exceeded")
                    
                    # Trigger garbage collection to free memory
                    memory_freed = self.memory_monitor.trigger_garbage_collection()
                    
                    if self.debug_mode:
                        print(f"[TimeWindow] Memory pressure detected: {memory_status.current_mb:.1f}MB, freed {memory_freed:.1f}MB")
                
                elif memory_status.should_reduce_caches:
                    # Reduce cache sizes if available
                    if hasattr(self, 'window_query_manager') and self.window_query_manager:
                        # Calculate target reduction (10% of threshold)
                        target_reduction_mb = int(self.memory_monitor.threshold_mb * 0.1)
                        
                        # Collect cache reducers from feather queries
                        cache_reducers = []
                        for feather_query in self.feather_queries.values():
                            if hasattr(feather_query, 'reduce_cache_size'):
                                cache_reducers.append(feather_query.reduce_cache_size)
                        
                        # Reduce caches
                        if cache_reducers:
                            actual_freed = self.memory_monitor.reduce_cache_sizes(
                                target_reduction_mb, cache_reducers
                            )
                            
                            if self.debug_mode:
                                print(f"[TimeWindow] Cache reduction: freed {actual_freed:.1f}MB")
            
            # Task 15: Release memory after window processing (Requirements 5.3)
            # Clear local references to allow garbage collection
            populated_window = None
            
            # Calculate memory released
            if memory_before is not None and hasattr(self, 'memory_monitor') and self.memory_monitor:
                memory_after = self.memory_monitor.get_current_usage_mb()
                memory_delta = memory_after - memory_before
                
                # Track memory delta for statistics
                if hasattr(self, 'window_processing_stats'):
                    if not hasattr(self.window_processing_stats, 'memory_deltas'):
                        self.window_processing_stats.memory_deltas = []
                    self.window_processing_stats.memory_deltas.append(memory_delta)
            
            # Return matches for Phase 2 processing (semantic mappings and scoring)
            return matches
            
        except Exception as e:
            # Complete window monitoring with error
            if window_metrics:
                self.performance_monitor.complete_window_processing(
                    window.window_id, 0, 0, 0
                )
            raise e
        finally:
            # Task 23: End profiling (Requirements 1.1, 1.3)
            try:
                if self._profiling_enabled:
                    self.profiler.end_operation("_process_window")
            except Exception:
                pass  # Silently ignore profiler errors
    
    def _process_windows_sequential(self, 
                                  start_epoch: datetime, 
                                  end_epoch: datetime, 
                                  wing: Wing, 
                                  result: CorrelationResult,
                                  total_windows: int) -> List[CorrelationMatch]:
        """
        Process windows sequentially with time-window-specific progress tracking.
        
        Args:
            start_epoch: Start time for scanning
            end_epoch: End time for scanning
            wing: Wing configuration
            result: CorrelationResult to update
            total_windows: Total number of windows to process
            
        Returns:
            List of all correlation matches found
        """
        matches = []
        window_count = 0
        
        # Task 8.3: Initialize progress reporter for window processing
        # Requirements: 4.1, 4.2, 4.3, 4.4
        # Reports progress every 5% (at 5%, 10%, 15%, 20%, etc.)
        from .progress_tracking import CorrelationProgressReporter, CorrelationStallMonitor, CorrelationStallException
        
        progress_reporter = CorrelationProgressReporter(
            total_items=total_windows,
            report_percentage_interval=5.0,  # Report every 5%
            phase_name="Time-Window Scanning"
        )
        
        # Task 9.3: Initialize stall monitor for window processing
        # Requirements: 5.2, 5.3, 5.4, 5.5
        # Detects stalls when no progress for 300 seconds (5 minutes)
        stall_monitor = CorrelationStallMonitor(stall_timeout_seconds=300)
        
        # Report initial progress (0%)
        progress_reporter.force_report()
        
        # Task 9.3: Update stall monitor at start
        stall_monitor.update_progress(0, current_stage="window_processing", last_operation="started_window_scanning")
        
        # Initialize smart empty window tracking for early termination
        # DISABLED: Smart stop was too risky - it skipped windows that were "likely" empty
        # For forensic analysis, we must process ALL windows to ensure no data is missed
        consecutive_empty_windows = 0
        max_consecutive_empty_before_stop = 999999999  # Effectively disabled - never stop early
        found_any_data = False  # Track if we've found any data yet
        
        for window in self._generate_time_windows(start_epoch, end_epoch):
            # Task 9.3: Check for stall before processing each window
            # Requirements: 5.2, 5.3, 5.4
            if stall_monitor.check_for_stall():
                diagnostics = stall_monitor.get_stall_diagnostics()
                logger.error(f"Correlation stalled during window processing. Diagnostics: {diagnostics}")
                raise CorrelationStallException(
                    f"Correlation stalled: No progress for {diagnostics['time_since_last_progress']:.1f} seconds. "
                    f"Last operation: {diagnostics['last_successful_operation']}"
                )
            
            # Check for cancellation before processing each window
            try:
                self.cancellation_manager.check_cancellation()
                self.progress_tracker.check_cancellation()
            except Exception:
                # Cancellation requested - break out of loop
                if self.debug_mode:
                    print(f"[TimeWindow] Cancellation detected at window {window_count}")
                break
            
            # Start window processing tracking with time-window-specific formatting
            window_start_time = time.time()
            self.progress_tracker.start_window(
                window_id=window.window_id,
                window_start_time=window.start_time,
                window_end_time=window.end_time
            )
            
            # Log per-window processing (Requirement 6.3)
            window_num = window_count + 1  # 1-indexed for display
            window_start_str = window.start_time.strftime('%Y-%m-%d %H:%M:%S')
            window_end_str = window.end_time.strftime('%Y-%m-%d %H:%M:%S')
            progress_percent = (window_num / total_windows * 100) if total_windows > 0 else 0
            
            # Log time-window-specific progress summary - only every 10%
            # Calculate which 10% milestone we're at
            current_percentage = int((window_num / total_windows) * 100)
            previous_percentage = int(((window_num - 1) / total_windows) * 100) if window_num > 1 else -1
            
            # Print progress summary when we cross a 10% boundary
            if current_percentage % 10 == 0 and current_percentage != previous_percentage and current_percentage > 0:
                # Get current progress stats
                progress_stats = self.progress_tracker._create_overall_progress()
                
                # Format current window time range
                current_window_range = f"{window_start_str} → {window_end_str}"
                
                # Format progress message with enhanced statistics
                progress_msg = f"[Time-Window Engine] Progress Summary: {progress_percent:.0f}% ({window_count:,}/{total_windows:,} windows, {len(matches):,} matches) | Window: {current_window_range}"
                
                # Add empty window statistics if significant
                if progress_stats.empty_windows_skipped > 0:
                    # Calculate windows with data
                    windows_with_data = window_count - progress_stats.empty_windows_skipped
                    skip_rate = (progress_stats.empty_windows_skipped / window_count * 100) if window_count > 0 else 0
                    progress_msg += f" | Empty: {progress_stats.empty_windows_skipped:,} ({skip_rate:.1f}%) | With data: {windows_with_data:,}"
                
                # Add time saved if significant
                if progress_stats.time_saved_by_skipping_seconds > 1.0:
                    progress_msg += f" | Time saved: ~{progress_stats.time_saved_by_skipping_seconds:.1f}s"
                
                # Add time remaining estimate
                if progress_stats.time_remaining_seconds:
                    remaining_minutes = progress_stats.time_remaining_seconds / 60
                    if remaining_minutes < 1:
                        progress_msg += f" | ETA: {progress_stats.time_remaining_seconds:.0f}s"
                    else:
                        progress_msg += f" | ETA: {remaining_minutes:.1f}m"
                
                print(progress_msg)
                
                # Force GUI update to prevent freezing
                try:
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass  # Ignore if not in GUI context
            
            # Check memory pressure before processing window (silently)
            self._check_memory_and_enable_streaming(result, wing)
            
            # Process this time window with error handling (Requirement 6.8)
            try:
                window_matches = self._process_window(window, wing)
            except Exception as e:
                # Log error for window processing failure (Requirement 6.8)
                error_msg = str(e)
                print(f"[Time-Window Engine] ❌ Error in window {window.window_id}: {error_msg}")
                
                # Add error to result
                result.errors.append(f"Window {window.window_id}: {error_msg}")
                
                # Continue with next window instead of failing completely
                window_matches = []
                
                if self.debug_mode:
                    import traceback
                    print(f"[Time-Window Engine] DEBUG: Full traceback:")
                    traceback.print_exc()
            
            # Calculate processing metrics
            window_processing_time = time.time() - window_start_time
            records_found = sum(len(records) for records in window.records_by_feather.values())
            feathers_with_records = list(window.records_by_feather.keys())
            # A window is considered "empty" if it has no matches (not just no records)
            # This is more accurate because records can exist but not meet minimum_matches requirement
            is_empty_window = (len(window_matches) == 0)
            
            # Log window results (Requirements 6.4 and 6.5)
            if is_empty_window:
                # Empty window - skip silently (no print to reduce noise)
                pass
            else:
                # Count unique NORMALIZED identities in this window
                # Each match represents one identity group, so len(window_matches) = number of unique identities
                # Total records across all matches
                total_records = sum(
                    sum(len(records) for records in match.feather_records.values())
                    for match in window_matches
                    if hasattr(match, 'feather_records') and match.feather_records
                )
                
                # Log window correlation results (Requirement 6.4)
                # Note: Each match = one unique identity, total_records = all data records
                print(f"[Time-Window Engine] ✓ Window {window.window_id} ({window_start_str} → {window_end_str}): {len(window_matches)} identities, {total_records} records")
                found_any_data = True  # Mark that we've found data
                consecutive_empty_windows = 0  # Reset counter when we find data
            
            # Smart early termination: Stop if we've seen too many consecutive empty windows AFTER finding data
            if is_empty_window:
                consecutive_empty_windows += 1
                
                # Only consider early termination if we've already found some data
                if found_any_data and consecutive_empty_windows >= max_consecutive_empty_before_stop:
                    remaining_windows = total_windows - window_count
                    print(f"\n[Time-Window Engine] 🎯 Smart Stop: {consecutive_empty_windows} consecutive empty windows detected")
                    print(f"[Time-Window Engine]   Skipping remaining {remaining_windows:,} windows (likely all empty)")
                    print(f"[Time-Window Engine]   Processed: {window_count:,}/{total_windows:,} windows ({window_count/total_windows*100:.1f}%)")
                    print(f"[Time-Window Engine]   Found: {len(matches):,} matches in {window_count - consecutive_empty_windows:,} windows with data")
                    
                    # Add info to result
                    result.warnings.append(
                        f"Early termination: Stopped after {consecutive_empty_windows} consecutive empty windows. "
                        f"Skipped {remaining_windows:,} likely empty windows."
                    )
                    break  # Exit the scanning loop early
            
            # Update window processing statistics (if enabled)
            if self.scanning_config.track_empty_window_stats:
                if is_empty_window:
                    self.window_processing_stats.empty_windows_skipped += 1
                else:
                    self.window_processing_stats.windows_with_data += 1
                self.window_processing_stats.total_windows_generated += 1
                
                # Calculate efficiency metrics
                self.window_processing_stats.calculate_efficiency_metrics()
            
            # Add measurement to time estimator (only for non-empty windows for accurate estimates)
            if not is_empty_window:
                self.time_estimator.add_measurement(
                    windows_processed=1,
                    processing_time_seconds=window_processing_time,
                    records_processed=records_found,
                    matches_found=len(window_matches),
                    memory_usage_mb=self.memory_manager.check_memory_pressure().current_memory_mb if self.memory_manager else None
                )
            
            # Add matches to result (handles streaming automatically)
            for match in window_matches:
                # Apply scoring DURING correlation (fast operation)
                # Semantic mapping will be applied AFTER streaming completes (slow operation)
                scored_match = self._apply_scoring_to_single_match(match, wing)
                
                if self.streaming_mode_active and self.streaming_writer:
                    # Write match WITH scoring but WITHOUT semantic data during correlation
                    result.add_match(scored_match)
                    result_id = getattr(result, '_result_id', 0)
                    if result_id > 0:
                        self.streaming_writer.write_match(result_id, scored_match)
                else:
                    result.add_match(scored_match)
            
            matches.extend(window_matches)
            window_count += 1
            
            # Task 8.3: Update progress (will auto-report at 10%, 20%, 30%, etc.)
            # Requirements: 4.2, 4.3, 4.4
            progress_reporter.update(items_processed=1)
            
            # Task 9.3: Update stall monitor after processing each window
            # Requirements: 5.2, 5.4
            stall_monitor.update_progress(
                window_count,
                current_stage="window_processing",
                last_operation=f"processed_window_{window_count}"
            )
            
            # OPTIMIZATION: Consolidate memory pressure checks and throttle reporting
            memory_usage = None
            if window_count % 50 == 0 or window_count == total_windows:
                # Only check memory pressure and perform cleanup every 50 windows
                if self.memory_manager:
                    memory_report = self.memory_manager.check_memory_pressure()
                    memory_usage = memory_report.current_memory_mb
                    
                    # Perform memory cleanup between windows if needed (silently)
                    self._cleanup_memory_between_windows(window_count, memory_report)
            
            # Complete window processing tracking with time-window-specific details
            # Pass cached memory_usage to avoid redundant psutil calls
            self.progress_tracker.complete_window(
                window_id=window.window_id,
                window_start_time=window.start_time,
                window_end_time=window.end_time,
                records_found=records_found,
                matches_created=len(window_matches),
                feathers_with_records=feathers_with_records,
                memory_usage_mb=memory_usage,
                is_empty_window=is_empty_window
            )
            
            # Report time-window processing milestone - throttled to every 100 windows
            if window_count % 100 == 0 or window_count == total_windows:
                self._report_time_window_milestone(window_count, total_windows, window.start_time, window.end_time)
            
            # Legacy progress reporting for backward compatibility
            if window_count % 100 == 0 or window_count == total_windows:
                self._emit_progress_event("window_progress", {
                    'windows_processed': window_count,
                    'total_windows': total_windows,
                    'matches_found': result.total_matches,
                    'current_window_time': window.start_time.isoformat(),
                    'streaming_mode': self.streaming_mode_active,
                    'memory_usage_mb': memory_usage or 0,
                    'processing_mode': 'sequential'
                })
            
            # Force GUI update more frequently to prevent freezing (every 10 windows)
            if window_count % 10 == 0:
                try:
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass  # Ignore if not in GUI context
            
            if self.debug_mode and window_count % 1000 == 0:
                memory_report = self.memory_manager.check_memory_pressure() if self.memory_manager else None
                memory_info = f", memory: {memory_report.current_memory_mb:.1f}MB" if memory_report else ""
                streaming_info = " (streaming)" if self.streaming_mode_active else ""
                print(f"[TimeWindow] Processed {window_count}/{total_windows} windows, "
                      f"{result.total_matches} matches found{memory_info}{streaming_info}")
        
        # Task 8.3: Report final progress (100%)
        # Requirements: 4.1, 4.5
        progress_reporter.force_report()
        
        return matches
    
    def _process_windows_parallel(self, 
                                start_epoch: datetime, 
                                end_epoch: datetime, 
                                wing: Wing, 
                                result: CorrelationResult) -> List[CorrelationMatch]:
        """
        Process windows in parallel using ParallelWindowProcessor or ParallelCoordinator.
        
        Task 12: Enhanced to support ParallelCoordinator.
        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
        
        Args:
            start_epoch: Start time for scanning
            end_epoch: End time for scanning
            wing: Wing configuration
            result: CorrelationResult to update
            
        Returns:
            List of all correlation matches found
        """
        # Generate all windows first (needed for parallel processing)
        windows = list(self._generate_time_windows(start_epoch, end_epoch))
        
        if self.debug_mode:
            processor_type = "coordinator" if self.use_parallel_coordinator else "processor"
            print(f"[TimeWindow] Starting parallel processing of {len(windows)} windows "
                  f"with {self.max_workers} workers using {processor_type}")
        
        # Task 12: Use ParallelCoordinator if configured
        if self.use_parallel_coordinator and self.parallel_coordinator:
            return self._process_windows_with_coordinator(windows, wing, result)
        
        # Use existing ParallelWindowProcessor
        if not self.parallel_processor:
            raise RuntimeError("Parallel processor not initialized")
        
        # Create a wrapper function that handles memory checking and streaming
        def process_window_with_context(window: TimeWindow, wing_config: Wing) -> List[CorrelationMatch]:
            """Wrapper function for parallel processing that handles context"""
            # Note: Memory checking and streaming are handled at batch level in parallel mode
            # Individual windows don't need to check memory pressure
            return self._process_window(window, wing_config)
        
        # Process windows in parallel
        all_matches = self.parallel_processor.process_windows_parallel(
            windows=windows,
            wing=wing,
            window_processor_func=process_window_with_context,
            progress_callback=self._handle_parallel_progress_callback
        )
        
        # Add all matches to result
        for match in all_matches:
            result.add_match(match)
        
        return all_matches
    
    def _process_windows_with_coordinator(self,
                                         windows: List[TimeWindow],
                                         wing: Wing,
                                         result: CorrelationResult) -> List[CorrelationMatch]:
        """
        Process windows in parallel using ParallelCoordinator.
        
        Task 12: New method for ParallelCoordinator integration.
        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
        
        Args:
            windows: List of time windows to process
            wing: Wing configuration
            result: CorrelationResult to update
            
        Returns:
            List of all correlation matches found
        """
        if not self.parallel_coordinator:
            raise RuntimeError("Parallel coordinator not initialized")
        
        # Create process function for coordinator
        def process_window_func(window: TimeWindow, shared_data: Optional[Dict[str, Any]] = None) -> List[CorrelationMatch]:
            """Process a single window - called by coordinator workers"""
            try:
                # Process the window
                matches = self._process_window(window, wing)
                
                # Update progress tracker
                self.progress_tracker.complete_window(
                    window_id=window.window_id,
                    window_start_time=window.start_time,
                    window_end_time=window.end_time,
                    records_found=0,  # Not tracked in parallel mode
                    matches_created=len(matches),
                    feathers_with_records=0,  # Not tracked in parallel mode
                    memory_usage_mb=0,  # Not tracked per window in parallel mode
                    is_empty_window=len(matches) == 0
                )
                
                return matches
            except Exception as e:
                if self.debug_mode:
                    print(f"[TimeWindow] Error processing window {window.window_id}: {e}")
                # Return empty list on error - coordinator will track the error
                return []
        
        # Prepare shared data (if any)
        shared_data = {
            'wing': wing,
            'filters': self.filters,
            'debug_mode': self.debug_mode
        }
        
        # Process windows with coordinator
        all_matches = self.parallel_coordinator.process_with_shared_cache(
            windows=windows,
            process_func=process_window_func,
            shared_data=shared_data
        )
        
        # Flatten matches (each window returns a list of matches)
        flattened_matches = []
        for window_matches in all_matches:
            if window_matches:  # Skip None results from errors
                flattened_matches.extend(window_matches)
        
        # Add all matches to result
        for match in flattened_matches:
            result.add_match(match)
        
        # Check for errors
        if self.parallel_coordinator.has_errors():
            error_summary = self.parallel_coordinator.get_error_summary()
            if self.debug_mode:
                print(f"[TimeWindow] Parallel coordinator completed with {error_summary['total_errors']} errors")
            
            # Add error summary to result warnings
            result.warnings.append(
                f"Parallel processing completed with {error_summary['total_errors']} errors. "
                f"Check logs for details."
            )
        
        return flattened_matches
    
    def _handle_parallel_progress_callback(self, progress_data: Dict[str, Any]):
        """
        Handle progress callbacks from parallel processor.
        
        Args:
            progress_data: Progress data from parallel processor
        """
        # Check memory pressure periodically during parallel processing
        if hasattr(self, 'memory_manager') and self.memory_manager:
            memory_report = self.memory_manager.check_memory_pressure()
            progress_data['memory_usage_mb'] = memory_report.current_memory_mb
        
        # Add processing mode information
        progress_data['processing_mode'] = 'parallel'
        progress_data['streaming_mode'] = self.streaming_mode_active
        
        # Emit progress event
        self._emit_progress_event("window_progress", progress_data)
        
        # Debug logging for parallel batches
        if self.debug_mode and progress_data.get('event_type') == 'parallel_batch_complete':
            batch_size = progress_data.get('batch_size', 0)
            windows_processed = progress_data.get('windows_processed', 0)
            total_windows = progress_data.get('total_windows', 0)
            matches_found = progress_data.get('matches_found', 0)
            
            # Load balancing stats
            lb_stats = progress_data.get('load_balancing_stats', {})
            efficiency = lb_stats.get('balancing_efficiency', 0.0)
            
            print(f"[TimeWindow] Parallel batch complete: {batch_size} windows, "
                  f"{windows_processed}/{total_windows} total, {matches_found} matches, "
                  f"load balance: {efficiency:.2f}")
    
    def _cleanup_parallel_processing(self):
        """
        Cleanup parallel processing resources.
        
        Task 12: Enhanced to support ParallelCoordinator cleanup.
        """
        if self.parallel_processor:
            # Request cancellation if processing is active
            if self.parallel_processor.is_processing:
                self.parallel_processor.request_cancellation()
            
            # The parallel processor handles its own cleanup
            self.parallel_processor = None
        
        if self.parallel_coordinator:
            # Reset coordinator statistics
            self.parallel_coordinator.reset_statistics()
            self.parallel_coordinator = None
    
    def _emit_progress_event(self, event_type: str, data: Dict[str, Any]):
        """Emit progress event to registered listeners"""
        if self.progress_listener:
            try:
                self.progress_listener({
                    'event_type': event_type,
                    'timestamp': datetime.now(),
                    'data': data
                })
            except Exception as e:
                if self.debug_mode:
                    print(f"[TimeWindow] Progress listener error: {e}")
    
    def _cleanup_feather_queries(self):
        """Cleanup feather query managers with comprehensive error handling"""
        cleanup_errors = []
        
        for feather_id, query_manager in self.feather_queries.items():
            try:
                # Cleanup query manager's error handler
                if hasattr(query_manager, 'cleanup'):
                    query_manager.cleanup()
                
                # Cleanup loader connection
                if hasattr(query_manager.loader, 'disconnect'):
                    query_manager.loader.disconnect()
                    
            except Exception as e:
                cleanup_errors.append(f"Error cleaning up feather {feather_id}: {str(e)}")
                if self.debug_mode:
                    print(f"[TimeWindow] Cleanup error for {feather_id}: {e}")
        
        self.feather_queries.clear()
        
        # Cleanup streaming writer
        if self.streaming_writer:
            try:
                self.streaming_writer.close()
            except Exception as e:
                cleanup_errors.append(f"Error closing streaming writer: {str(e)}")
                if self.debug_mode:
                    print(f"[TimeWindow] Streaming writer cleanup error: {e}")
            self.streaming_writer = None
        
        # Cleanup parallel processing
        try:
            self._cleanup_parallel_processing()
        except Exception as e:
            cleanup_errors.append(f"Error cleaning up parallel processing: {str(e)}")
            if self.debug_mode:
                print(f"[TimeWindow] Parallel processing cleanup error: {e}")
        
        # Log cleanup summary
        if self.debug_mode:
            if cleanup_errors:
                print(f"[TimeWindow] Cleanup completed with {len(cleanup_errors)} errors:")
                for error in cleanup_errors:
                    print(f"[TimeWindow]   - {error}")
            else:
                print("[TimeWindow] Cleanup completed successfully")
        
        return cleanup_errors
    
    def _check_memory_and_enable_streaming(self, result: CorrelationResult, wing: Wing):
        """
        Check memory pressure and enable streaming mode if needed.
        
        Args:
            result: CorrelationResult to potentially switch to streaming
            wing: Wing configuration for streaming database path
        """
        if not self.memory_manager or self.streaming_mode_active:
            return
        
        # Check memory pressure and get recommendations
        memory_report = self.memory_manager.check_memory_pressure()
        
        # Force garbage collection if memory usage is high (silently)
        if memory_report.usage_percentage > 70:
            self.memory_manager.force_garbage_collection()
            memory_report = self.memory_manager.check_memory_pressure()
        
        # Check if streaming mode should be enabled
        should_stream, reason = self.memory_manager.should_enable_streaming_mode()
        
        if should_stream:
            print(f"[Time-Window Engine] 💾 Streaming mode enabled")
            
            # Create streaming database path
            streaming_db_path = self._get_streaming_database_path(wing)
            
            # Report memory warning to progress tracker
            self.progress_tracker.report_memory_warning(
                current_usage_mb=memory_report.current_memory_mb,
                limit_mb=self.memory_limit_mb,
                message=f"Memory limit approached: {reason}"
            )
            
            # Report streaming enabled to progress tracker
            self.progress_tracker.report_streaming_enabled(reason, streaming_db_path)
            
            try:
                # Create streaming writer using database persistence
                self.streaming_writer = StreamingMatchWriter(
                    db_path=streaming_db_path,
                    batch_size=1000
                )
                
                # Create result session with proper execution_id
                result_id = self.streaming_writer.create_result(
                    execution_id=self._execution_id if self._execution_id else 0,  # Use pipeline execution_id
                    wing_id=wing.wing_id,
                    wing_name=wing.wing_name,
                    feathers_processed=result.feathers_processed,
                    total_records_scanned=result.total_records_scanned
                )
                
                # Store result_id on result for later reference
                result._result_id = result_id
                result._streaming_writer = self.streaming_writer
                result._streaming_db_path = streaming_db_path
                
                # Update state
                self.streaming_mode_active = True
                self.memory_manager.activate_streaming_mode(reason)
                
                print(f"[Time-Window Engine]   ✓ Streaming to: {streaming_db_path}")
                
                # Legacy progress event for backward compatibility
                self._emit_progress_event("streaming_enabled", {
                    'reason': reason,
                    'database_path': streaming_db_path,
                    'result_id': result_id
                })
                
            except Exception as e:
                print(f"[Time-Window Engine]   ❌ Failed to enable streaming: {e}")
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()
        
        # Issue memory warnings if needed
        elif memory_report.usage_percentage > 80:
            if self.debug_mode:
                print(f"[Time-Window Engine]   ⚠️ Memory warning: {memory_report.usage_percentage:.1f}%")
            
            # Report memory warning to progress tracker
            self.progress_tracker.report_memory_warning(
                current_usage_mb=memory_report.current_memory_mb,
                limit_mb=self.memory_limit_mb,
                message=f"High memory usage: {memory_report.usage_percentage:.1f}%"
            )
    
    def _get_streaming_database_path(self, wing: Wing) -> str:
        """
        Get path for streaming database.
        
        Args:
            wing: Wing configuration
            
        Returns:
            Path to streaming database file
        """
        # Priority 1: Use pipeline-provided output directory (set via set_output_directory)
        if self._output_dir:
            output_dir = Path(self._output_dir)
            db_path = output_dir / "correlation_results.db"
            if self.debug_mode:
                print(f"[TimeWindow] Using pipeline output directory: {output_dir}")
                print(f"[TimeWindow] Database path: {db_path}")
            return str(db_path)
        
        # Priority 2: Use pipeline config's output_directory if available
        if hasattr(self, 'config') and hasattr(self.config, 'output_directory') and self.config.output_directory:
            output_dir = Path(self.config.output_directory)
            db_path = output_dir / "correlation_results.db"
            if self.debug_mode:
                print(f"[TimeWindow] Using pipeline config output directory: {output_dir}")
            return str(db_path)
        
        # Priority 3: Use wing path parent directory
        elif hasattr(wing, 'wing_path') and wing.wing_path:
            output_dir = Path(wing.wing_path).parent
            if self.debug_mode:
                print(f"[TimeWindow] Using wing path parent directory: {output_dir}")
        # Priority 4: Fall back to current working directory
        else:
            output_dir = Path.cwd()
            if self.debug_mode:
                print(f"[TimeWindow] WARNING: Falling back to current working directory: {output_dir}")
        
        # Create streaming_results subdirectory (fallback mode only)
        streaming_dir = output_dir / "streaming_results"
        streaming_dir.mkdir(parents=True, exist_ok=True)
        
        # Create unique database name with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_name = f"{wing.wing_id}_{timestamp}_streaming.db"
        
        db_path = streaming_dir / db_name
        if self.debug_mode:
            print(f"[TimeWindow] Streaming database path: {db_path}")
        
        return str(db_path)
    
    def _cleanup_memory_between_windows(self, window_count: int, memory_report: Optional[Any] = None):
        """
        Perform memory cleanup between windows to maintain efficiency.
        
        Args:
            window_count: Current window count for cleanup scheduling
            memory_report: Optional pre-calculated memory report
        """
        if not self.memory_manager:
            return
        
        # Use provided memory report or only check every 100 windows
        if not memory_report:
            if window_count % 100 != 0:
                return
            memory_report = self.memory_manager.check_memory_pressure()
        
        # Perform cleanup based on memory usage and window count
        # OPTIMIZATION: More conservative cleanup interval
        should_cleanup = (
            memory_report.usage_percentage > 85 or  # High memory usage (was 70)
            window_count % 1000 == 0 or  # Periodic cleanup every 1000 windows
            memory_report.is_over_limit  # Over memory limit
        )
        
        if should_cleanup:
            # Force garbage collection silently
            collected = self.memory_manager.force_garbage_collection()
            
            # Clear query cache if it exists
            if hasattr(self, 'window_query_manager') and hasattr(self.window_query_manager, 'query_cache'):
                cache_size = len(self.window_query_manager.query_cache)
                if cache_size > 500:  # Clear cache if it's getting large (was 100)
                    self.window_query_manager.query_cache.clear()
    
    def _report_time_window_milestone(self, processed_windows: int, total_windows: int, 
                                    window_start: datetime, window_end: datetime):
        """
        Report time window processing milestone with specific formatting.
        
        Args:
            processed_windows: Number of windows processed so far
            total_windows: Total number of windows to process
            window_start: Start time of current window
            window_end: End time of current window
        """
        # Calculate progress percentage
        progress_percent = (processed_windows / total_windows * 100) if total_windows > 0 else 0
        
        # Log time-window-specific progress format
        if self.debug_mode and processed_windows % 100 == 0:
            print(f"[TimeWindow] Processing window {processed_windows} of {total_windows} ({progress_percent:.1f}% complete)")
            print(f"[TimeWindow] Current window: {window_start.strftime('%Y-%m-%d %H:%M:%S')} to {window_end.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Report to progress tracker with time-window-specific message
        from .progress_tracking import ProgressEvent, ProgressEventType
        
        # Create time-window-specific progress event
        event = ProgressEvent(
            event_type=ProgressEventType.WINDOW_PROGRESS,
            timestamp=datetime.now(),
            overall_progress=self.progress_tracker._create_overall_progress(),
            message=f"Processing window {processed_windows} of {total_windows} ({progress_percent:.1f}% complete)",
            additional_data={
                'time_window_progress': {
                    'processed_windows': processed_windows,
                    'total_windows': total_windows,
                    'progress_percent': progress_percent,
                    'current_window_start': window_start.isoformat(),
                    'current_window_end': window_end.isoformat(),
                    'window_size_minutes': self.window_size_minutes,
                    'engine_type': 'time_window_scanning'
                }
            }
        )
        
        # Emit the event to all listeners
        self.progress_tracker._emit_event(event)
    
    def _finalize_streaming_mode(self, result: CorrelationResult):
        """
        Finalize streaming mode and update result metadata.
        
        Args:
            result: CorrelationResult to finalize
        """
        if not self.streaming_writer or not self.streaming_mode_active:
            return
        
        print(f"[Time-Window Engine] 💾 Finalizing streaming mode...")
        
        try:
            # Flush any remaining matches
            self.streaming_writer.flush()
            
            # Get memory statistics
            memory_stats = self.memory_manager.get_memory_statistics() if self.memory_manager else {}
            
            # Update result record with final counts
            result_id = getattr(result, '_result_id', 0)
            if result_id > 0:
                self.streaming_writer.update_result_count(
                    result_id=result_id,
                    total_matches=result.total_matches,
                    execution_duration=result.execution_duration_seconds,
                    duplicates_prevented=result.duplicates_prevented,
                    feather_metadata=result.feather_metadata
                )
            
            total_written = self.streaming_writer.get_total_written()
            print(f"[Time-Window Engine]   ✓ {total_written:,} matches written to database")
            
            # Store streaming info in result
            result.streaming_database_path = getattr(result, '_streaming_db_path', None)
            result.streaming_matches_written = total_written
            
        except Exception as e:
            print(f"[Time-Window Engine]   ❌ Error finalizing streaming: {e}")
            if self.debug_mode:
                import traceback
                traceback.print_exc()
    
    def get_results(self) -> Any:
        """
        Get correlation results from last execution.
        
        Returns:
            CorrelationResult object or None if no execution yet
        """
        return self.last_result
    
    def _get_cache_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics from all caching components.
        
        Returns:
            Dictionary with cache hit rates and statistics (Requirements 9.1, 9.2, 9.3, 9.4)
        """
        cache_stats = {
            'available': True,
            'query_cache': {},
            'timestamp_cache': {},
            'window_manager_cache': {},
            'overall_cache_hit_rate': 0.0
        }
        
        # Collect query cache statistics from all feather queries
        if hasattr(self, 'window_query_manager') and self.window_query_manager:
            total_hits = 0
            total_misses = 0
            total_evictions = 0
            total_cache_size_mb = 0.0
            
            for feather_id, query_manager in self.window_query_manager.feather_queries.items():
                feather_cache_stats = query_manager.get_cache_statistics()
                total_hits += feather_cache_stats.get('cache_hits', 0)
                total_misses += feather_cache_stats.get('cache_misses', 0)
                total_evictions += feather_cache_stats.get('cache_evictions', 0)
                total_cache_size_mb += feather_cache_stats.get('query_cache_size_mb', 0.0)
            
            total_requests = total_hits + total_misses
            query_hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0.0
            
            cache_stats['query_cache'] = {
                'total_hits': total_hits,
                'total_misses': total_misses,
                'total_requests': total_requests,
                'hit_rate_percent': round(query_hit_rate, 2),
                'total_evictions': total_evictions,
                'total_cache_size_mb': round(total_cache_size_mb, 2)
            }
            
            # Window manager cache statistics
            wm_cache_stats = self.window_query_manager.get_cache_stats()
            cache_stats['window_manager_cache'] = wm_cache_stats
        
        # Collect timestamp cache statistics
        if hasattr(self, 'window_query_manager') and self.window_query_manager:
            timestamp_stats_list = []
            for feather_id, query_manager in self.window_query_manager.feather_queries.items():
                if hasattr(query_manager, 'timestamp_parse_cache'):
                    ts_stats = query_manager.timestamp_parse_cache.get_statistics()
                    timestamp_stats_list.append(ts_stats)
            
            if timestamp_stats_list:
                # Aggregate timestamp cache statistics
                total_ts_hits = sum(s.get('cache_hits', 0) for s in timestamp_stats_list)
                total_ts_misses = sum(s.get('cache_misses', 0) for s in timestamp_stats_list)
                total_ts_requests = total_ts_hits + total_ts_misses
                ts_hit_rate = (total_ts_hits / total_ts_requests * 100) if total_ts_requests > 0 else 0.0
                
                cache_stats['timestamp_cache'] = {
                    'total_hits': total_ts_hits,
                    'total_misses': total_ts_misses,
                    'total_requests': total_ts_requests,
                    'hit_rate_percent': round(ts_hit_rate, 2)
                }
        
        # Calculate overall cache hit rate
        all_hits = cache_stats['query_cache'].get('total_hits', 0) + cache_stats['timestamp_cache'].get('total_hits', 0)
        all_requests = cache_stats['query_cache'].get('total_requests', 0) + cache_stats['timestamp_cache'].get('total_requests', 0)
        cache_stats['overall_cache_hit_rate'] = round((all_hits / all_requests * 100) if all_requests > 0 else 0.0, 2)
        
        return cache_stats
    
    def _get_index_usage_statistics(self) -> Dict[str, Any]:
        """
        Get index usage statistics from all feather queries.
        
        Returns:
            Dictionary with index usage rates (Requirements 9.1, 9.2, 9.3, 9.4)
        """
        index_stats = {
            'available': True,
            'total_feathers': 0,
            'feathers_with_index': 0,
            'index_usage_rate_percent': 0.0,
            'feather_details': {}
        }
        
        if hasattr(self, 'window_query_manager') and self.window_query_manager:
            total_feathers = len(self.window_query_manager.feather_queries)
            feathers_with_index = 0
            
            for feather_id, query_manager in self.window_query_manager.feather_queries.items():
                # Check if timestamp column is detected (indicates index is available/used)
                has_index = query_manager.timestamp_column is not None
                if has_index:
                    feathers_with_index += 1
                
                index_stats['feather_details'][feather_id] = {
                    'has_timestamp_index': has_index,
                    'timestamp_column': query_manager.timestamp_column,
                    'timestamp_format': query_manager.timestamp_format
                }
            
            index_stats['total_feathers'] = total_feathers
            index_stats['feathers_with_index'] = feathers_with_index
            index_stats['index_usage_rate_percent'] = round((feathers_with_index / total_feathers * 100) if total_feathers > 0 else 0.0, 2)
        
        return index_stats
    
    def _get_skip_rate_statistics(self) -> Dict[str, Any]:
        """
        Get skip rate statistics from empty window detection.
        
        Returns:
            Dictionary with skip rates (Requirements 9.1, 9.2, 9.3, 9.4)
        """
        skip_stats = {
            'available': False
        }
        
        # Get empty window skipping statistics
        empty_window_stats = self.get_empty_window_skipping_statistics()
        if empty_window_stats.get('available'):
            skip_stats = {
                'available': True,
                'total_windows': empty_window_stats.get('total_windows_generated', 0),
                'windows_skipped': empty_window_stats.get('empty_windows_skipped', 0),
                'windows_processed': empty_window_stats.get('windows_with_data', 0),
                'skip_rate_percent': empty_window_stats.get('skip_rate_percentage', 0.0),
                'time_saved_seconds': empty_window_stats.get('time_saved_by_skipping_seconds', 0.0),
                'average_check_time_ms': empty_window_stats.get('average_check_time_ms', 0.0),
                'efficiency_summary': empty_window_stats.get('efficiency_summary', '')
            }
        
        return skip_stats
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get correlation statistics from last execution.
        
        Returns:
            Dictionary containing statistics including:
                - Basic execution statistics
                - Memory statistics
                - Streaming statistics
                - Parallel processing statistics
                - Progress tracking statistics
                - Time estimation statistics
                - Cancellation statistics
                - Time range detection statistics (NEW)
                - Empty window skipping statistics (NEW)
                - Efficiency metrics (NEW)
                - Cache hit rates (Task 22)
                - Index usage rates (Task 22)
                - Skip rates (Task 22)
        """
        if not self.last_result:
            return {}
        
        stats = {
            'execution_time': self.last_result.execution_duration_seconds,
            'record_count': self.last_result.total_records_scanned,
            'match_count': self.last_result.total_matches,
            'feathers_processed': self.last_result.feathers_processed,
            'window_size_minutes': self.window_size_minutes,
            'scanning_approach': 'time_window_scanning',
            'streaming_mode_used': self.streaming_mode_active,
            'parallel_processing_enabled': self.enable_parallel_processing
        }
        
        # Add memory statistics if available
        if self.memory_manager:
            memory_stats = self.memory_manager.get_memory_statistics()
            stats.update({
                'memory_statistics': memory_stats,
                'peak_memory_mb': memory_stats.get('peak_memory_mb', 0),
                'memory_efficiency_mb_per_1k_records': memory_stats.get('recent_efficiency_mb_per_1k_records', 0)
            })
        
        # Add streaming statistics if used
        if self.streaming_mode_active and self.streaming_writer:
            stats.update({
                'streaming_database_path': self.streaming_writer.database_path,
                'total_matches_written': self.streaming_writer.total_matches_written
            })
        
        # Add parallel processing statistics if used
        if self.enable_parallel_processing and self.parallel_processor:
            parallel_stats = self.parallel_processor.get_processing_stats()
            stats.update({
                'parallel_processing_stats': {
                    'max_workers': self.max_workers,
                    'batch_size': self.parallel_batch_size,
                    'total_windows_processed': parallel_stats.total_windows_processed,
                    'average_window_time': parallel_stats.average_window_time,
                    'parallel_speedup': parallel_stats.parallel_speedup,
                    'load_balancing_efficiency': parallel_stats.load_balancing_efficiency,
                    'worker_utilization': parallel_stats.worker_utilization
                }
            })
        
        # Add progress tracking statistics
        if hasattr(self, 'progress_tracker'):
            progress_data = self.progress_tracker._create_overall_progress()
            stats.update({
                'progress_tracking_stats': {
                    'windows_processed': progress_data.windows_processed,
                    'total_windows': progress_data.total_windows,
                    'completion_percentage': progress_data.completion_percentage,
                    'processing_rate_windows_per_second': progress_data.processing_rate_windows_per_second,
                    'estimated_completion_time': progress_data.estimated_completion_time.isoformat() if progress_data.estimated_completion_time else None,
                    'time_remaining_seconds': progress_data.time_remaining_seconds
                }
            })
        
        # Add time estimation statistics
        if hasattr(self, 'time_estimator'):
            estimation_stats = self.time_estimator.get_performance_statistics()
            stats.update({
                'time_estimation_stats': estimation_stats
            })
        
        # Add cancellation statistics
        if hasattr(self, 'cancellation_manager'):
            cancellation_stats = self.cancellation_manager.get_status_summary()
            stats.update({
                'cancellation_stats': cancellation_stats
            })
        
        # Add time range detection statistics (NEW)
        time_range_stats = self.get_time_range_detection_statistics()
        if time_range_stats.get('available'):
            stats.update({
                'time_range_detection_stats': time_range_stats
            })
        
        # Add empty window skipping statistics (NEW)
        empty_window_stats = self.get_empty_window_skipping_statistics()
        if empty_window_stats.get('available'):
            stats.update({
                'empty_window_skipping_stats': empty_window_stats
            })
        
        # Add cache hit rates (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4)
        cache_stats = self._get_cache_statistics()
        if cache_stats.get('available'):
            stats.update({
                'cache_statistics': cache_stats
            })
        
        # Add index usage rates (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4)
        index_stats = self._get_index_usage_statistics()
        if index_stats.get('available'):
            stats.update({
                'index_usage_statistics': index_stats
            })
        
        # Add skip rates (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4)
        skip_stats = self._get_skip_rate_statistics()
        if skip_stats.get('available'):
            stats.update({
                'skip_rate_statistics': skip_stats
            })
        
        # Add efficiency metrics (NEW)
        efficiency_metrics = self.get_efficiency_metrics()
        if efficiency_metrics.get('available'):
            stats.update({
                'efficiency_metrics': efficiency_metrics
            })
        
        return stats
    
    def get_time_range_detection_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about time range detection from last execution.
        
        Returns:
            Dictionary containing time range detection statistics:
                - earliest_timestamp: Earliest timestamp detected
                - latest_timestamp: Latest timestamp detected
                - total_span_days: Total time span in days
                - total_span_years: Total time span in years
                - feather_ranges: Time ranges for each feather
                - detection_time_seconds: Time taken to detect range
                - warnings: List of warnings during detection
                - source: Source of time range (FilterConfig, auto-detected, or hybrid)
        """
        if not hasattr(self, '_time_range_detection_result') or not self._time_range_detection_result:
            return {
                'available': False,
                'message': 'No time range detection data available from last execution'
            }
        
        detection_result = self._time_range_detection_result
        
        # Determine source of time range
        source = 'unknown'
        if hasattr(self, 'filters') and self.filters:
            if self.filters.time_period_start and self.filters.time_period_end:
                source = 'FilterConfig (both start and end)'
            elif self.filters.time_period_start:
                source = 'Hybrid (FilterConfig start + auto-detected end)'
            elif self.filters.time_period_end:
                source = 'Hybrid (auto-detected start + FilterConfig end)'
            else:
                source = 'Auto-detected from feather data'
        else:
            source = 'Auto-detected from feather data'
        
        return {
            'available': True,
            'earliest_timestamp': detection_result.earliest_timestamp.isoformat(),
            'latest_timestamp': detection_result.latest_timestamp.isoformat(),
            'total_span_days': detection_result.total_span_days,
            'total_span_years': detection_result.get_span_years(),
            'feather_ranges': {
                feather_id: {
                    'earliest': min_ts.isoformat(),
                    'latest': max_ts.isoformat(),
                    'span_days': (max_ts - min_ts).total_seconds() / 86400
                }
                for feather_id, (min_ts, max_ts) in detection_result.feather_ranges.items()
            },
            'detection_time_seconds': detection_result.detection_time_seconds,
            'warnings': detection_result.warnings,
            'source': source,
            'is_reasonable_range': detection_result.is_reasonable_range(
                self.scanning_config.max_time_range_years if hasattr(self, 'scanning_config') else 10
            )
        }
    
    def get_empty_window_skipping_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about empty window skipping from last execution.
        
        Returns:
            Dictionary containing empty window skipping statistics:
                - total_windows_generated: Total number of windows generated
                - windows_with_data: Number of windows containing data
                - empty_windows_skipped: Number of empty windows skipped
                - skip_rate_percentage: Percentage of windows skipped
                - time_saved_by_skipping_seconds: Estimated time saved by skipping
                - empty_window_check_time_seconds: Time spent checking for empty windows
                - average_check_time_ms: Average time per empty window check
                - efficiency_summary: Human-readable efficiency summary
        """
        if not hasattr(self, 'window_processing_stats') or not self.window_processing_stats:
            return {
                'available': False,
                'message': 'No empty window skipping data available from last execution'
            }
        
        stats = self.window_processing_stats
        
        # Calculate average check time
        avg_check_time_ms = 0.0
        if stats.empty_windows_skipped > 0 and stats.empty_window_check_time_seconds > 0:
            avg_check_time_ms = (stats.empty_window_check_time_seconds / stats.empty_windows_skipped) * 1000
        
        return {
            'available': True,
            'total_windows_generated': stats.total_windows_generated,
            'windows_with_data': stats.windows_with_data,
            'empty_windows_skipped': stats.empty_windows_skipped,
            'skip_rate_percentage': stats.skip_rate_percentage,
            'time_saved_by_skipping_seconds': stats.time_saved_by_skipping_seconds,
            'empty_window_check_time_seconds': stats.empty_window_check_time_seconds,
            'average_check_time_ms': avg_check_time_ms,
            'efficiency_summary': stats.get_efficiency_summary(),
            'performance_target_met': avg_check_time_ms < 1.0  # Target: <1ms per check
        }
    
    def get_efficiency_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive efficiency metrics combining time range detection and empty window skipping.
        Enhanced with bottleneck identification heuristics (Task 22 - Requirements 9.1, 9.2, 9.3, 9.4).
        
        Returns:
            Dictionary containing efficiency metrics:
                - overall_efficiency_score: Overall efficiency score (0-100)
                - time_range_optimization: Metrics about time range optimization
                - empty_window_optimization: Metrics about empty window skipping
                - total_time_saved_seconds: Total time saved by all optimizations
                - performance_improvements: Performance improvement factors
                - bottlenecks_identified: List of identified performance bottlenecks (NEW)
                - recommendations: List of recommendations for further optimization
        """
        time_range_stats = self.get_time_range_detection_statistics()
        empty_window_stats = self.get_empty_window_skipping_statistics()
        
        if not time_range_stats.get('available') or not empty_window_stats.get('available'):
            return {
                'available': False,
                'message': 'Insufficient data for efficiency metrics calculation'
            }
        
        # Calculate overall efficiency score (0-100)
        efficiency_score = 0.0
        
        # Factor 1: Skip rate (40 points max)
        skip_rate = empty_window_stats.get('skip_rate_percentage', 0)
        efficiency_score += min(skip_rate * 0.4, 40)
        
        # Factor 2: Time range optimization (30 points max)
        # Compare detected range vs scanning from year 2000
        span_years = time_range_stats.get('total_span_years', 0)
        years_from_2000 = datetime.now().year - 2000
        if years_from_2000 > 0:
            range_optimization = (1 - (span_years / years_from_2000)) * 100
            efficiency_score += min(range_optimization * 0.3, 30)
        
        # Factor 3: Quick check performance (30 points max)
        avg_check_time = empty_window_stats.get('average_check_time_ms', 999)
        if avg_check_time < 1.0:
            efficiency_score += 30  # Perfect score
        elif avg_check_time < 5.0:
            efficiency_score += 20  # Good
        elif avg_check_time < 10.0:
            efficiency_score += 10  # Acceptable
        
        # Calculate total time saved
        total_time_saved = (
            time_range_stats.get('detection_time_seconds', 0) +
            empty_window_stats.get('time_saved_by_skipping_seconds', 0)
        )
        
        # Calculate performance improvements
        # Estimate what would have happened without optimizations
        windows_with_data = empty_window_stats.get('windows_with_data', 1)
        empty_windows = empty_window_stats.get('empty_windows_skipped', 0)
        total_windows = windows_with_data + empty_windows
        
        # Estimate time without optimizations (assuming 50ms per window)
        estimated_time_without_optimization = total_windows * 0.050
        actual_processing_time = getattr(self.window_processing_stats, 'actual_processing_time_seconds', 0)
        
        speedup_factor = 1.0
        if actual_processing_time > 0:
            speedup_factor = estimated_time_without_optimization / actual_processing_time
        
        # BOTTLENECK IDENTIFICATION HEURISTICS (Task 22 - Requirements 9.4)
        bottlenecks = self._identify_performance_bottlenecks(
            time_range_stats, empty_window_stats, skip_rate, avg_check_time, span_years
        )
        
        # Generate recommendations
        recommendations = []
        
        if skip_rate < 50:
            recommendations.append(
                "Consider using FilterConfig to narrow the time range - current skip rate is low"
            )
        
        if avg_check_time > 1.0:
            recommendations.append(
                f"Empty window checks are taking {avg_check_time:.2f}ms - ensure timestamp indexes are created"
            )
        
        if span_years > 5:
            recommendations.append(
                f"Time range spans {span_years:.1f} years - consider using FilterConfig to focus on specific periods"
            )
        
        if not time_range_stats.get('is_reasonable_range'):
            recommendations.append(
                "Detected time range exceeds recommended maximum - consider splitting analysis into smaller time periods"
            )
        
        # Add bottleneck-specific recommendations
        for bottleneck in bottlenecks:
            if bottleneck['recommendation'] and bottleneck['recommendation'] not in recommendations:
                recommendations.append(bottleneck['recommendation'])
        
        return {
            'available': True,
            'overall_efficiency_score': round(efficiency_score, 2),
            'efficiency_grade': self._get_efficiency_grade(efficiency_score),
            'time_range_optimization': {
                'span_years': span_years,
                'years_saved_vs_2000': years_from_2000 - span_years,
                'optimization_percentage': round((1 - (span_years / years_from_2000)) * 100, 2) if years_from_2000 > 0 else 0,
                'source': time_range_stats.get('source')
            },
            'empty_window_optimization': {
                'skip_rate_percentage': skip_rate,
                'time_saved_seconds': empty_window_stats.get('time_saved_by_skipping_seconds', 0),
                'average_check_time_ms': avg_check_time,
                'performance_target_met': empty_window_stats.get('performance_target_met', False)
            },
            'total_time_saved_seconds': total_time_saved,
            'performance_improvements': {
                'speedup_factor': round(speedup_factor, 2),
                'estimated_time_without_optimization_seconds': round(estimated_time_without_optimization, 2),
                'actual_processing_time_seconds': round(actual_processing_time, 2),
                'time_saved_percentage': round((1 - (actual_processing_time / estimated_time_without_optimization)) * 100, 2) if estimated_time_without_optimization > 0 else 0
            },
            'bottlenecks_identified': bottlenecks,
            'recommendations': recommendations
        }
    
    def _identify_performance_bottlenecks(self, time_range_stats: Dict[str, Any], 
                                         empty_window_stats: Dict[str, Any],
                                         skip_rate: float, avg_check_time: float, 
                                         span_years: float) -> List[Dict[str, Any]]:
        """
        Identify performance bottlenecks using heuristics (Task 22 - Requirements 9.4).
        
        Args:
            time_range_stats: Time range detection statistics
            empty_window_stats: Empty window skipping statistics
            skip_rate: Skip rate percentage
            avg_check_time: Average check time in milliseconds
            span_years: Time span in years
            
        Returns:
            List of identified bottlenecks with severity and recommendations
        """
        bottlenecks = []
        
        # Bottleneck 1: Low cache hit rate
        cache_stats = self._get_cache_statistics()
        if cache_stats.get('available'):
            overall_hit_rate = cache_stats.get('overall_cache_hit_rate', 0.0)
            if overall_hit_rate < 30:
                bottlenecks.append({
                    'type': 'low_cache_hit_rate',
                    'severity': 'high',
                    'description': f'Cache hit rate is very low ({overall_hit_rate:.1f}%)',
                    'impact': 'Queries are not being reused, causing redundant database access',
                    'recommendation': 'Increase cache size or adjust window size to improve cache reuse'
                })
            elif overall_hit_rate < 50:
                bottlenecks.append({
                    'type': 'moderate_cache_hit_rate',
                    'severity': 'medium',
                    'description': f'Cache hit rate could be improved ({overall_hit_rate:.1f}%)',
                    'impact': 'Some queries are being repeated unnecessarily',
                    'recommendation': 'Consider increasing cache size for better performance'
                })
        
        # Bottleneck 2: Missing or unused indexes
        index_stats = self._get_index_usage_statistics()
        if index_stats.get('available'):
            index_usage_rate = index_stats.get('index_usage_rate_percent', 0.0)
            if index_usage_rate < 100:
                missing_count = index_stats.get('total_feathers', 0) - index_stats.get('feathers_with_index', 0)
                bottlenecks.append({
                    'type': 'missing_indexes',
                    'severity': 'high',
                    'description': f'{missing_count} feather(s) missing timestamp indexes ({index_usage_rate:.1f}% coverage)',
                    'impact': 'Queries on unindexed feathers require full table scans',
                    'recommendation': 'Ensure all feathers have timestamp indexes created'
                })
        
        # Bottleneck 3: Slow empty window checks
        if avg_check_time > 5.0:
            bottlenecks.append({
                'type': 'slow_empty_window_checks',
                'severity': 'high',
                'description': f'Empty window checks are slow ({avg_check_time:.2f}ms per check)',
                'impact': 'Empty window detection overhead is significant',
                'recommendation': 'Create timestamp indexes to speed up COUNT queries'
            })
        elif avg_check_time > 1.0:
            bottlenecks.append({
                'type': 'moderate_empty_window_checks',
                'severity': 'medium',
                'description': f'Empty window checks could be faster ({avg_check_time:.2f}ms per check)',
                'impact': 'Some overhead from empty window detection',
                'recommendation': 'Verify timestamp indexes are being used effectively'
            })
        
        # Bottleneck 4: Low skip rate (processing too many empty windows)
        if skip_rate < 20:
            bottlenecks.append({
                'type': 'low_skip_rate',
                'severity': 'high',
                'description': f'Very low skip rate ({skip_rate:.1f}%) - most windows contain data',
                'impact': 'Cannot benefit from empty window optimization',
                'recommendation': 'Use FilterConfig to narrow time range to periods with relevant data'
            })
        elif skip_rate < 40:
            bottlenecks.append({
                'type': 'moderate_skip_rate',
                'severity': 'medium',
                'description': f'Moderate skip rate ({skip_rate:.1f}%) - some optimization potential',
                'impact': 'Some windows are being processed unnecessarily',
                'recommendation': 'Consider refining time range filters to skip more empty periods'
            })
        
        # Bottleneck 5: Excessive time range
        if span_years > 10:
            bottlenecks.append({
                'type': 'excessive_time_range',
                'severity': 'high',
                'description': f'Very large time range ({span_years:.1f} years)',
                'impact': 'Processing many windows, high memory usage, long execution time',
                'recommendation': 'Split analysis into smaller time periods (e.g., yearly or quarterly)'
            })
        elif span_years > 5:
            bottlenecks.append({
                'type': 'large_time_range',
                'severity': 'medium',
                'description': f'Large time range ({span_years:.1f} years)',
                'impact': 'Processing overhead from many time windows',
                'recommendation': 'Consider narrowing time range if possible'
            })
        
        # Bottleneck 6: Memory pressure
        if hasattr(self, 'memory_manager') and self.memory_manager:
            memory_stats = self.memory_manager.get_memory_statistics()
            peak_memory_mb = memory_stats.get('peak_memory_mb', 0)
            if peak_memory_mb > 4096:  # > 4GB
                bottlenecks.append({
                    'type': 'high_memory_usage',
                    'severity': 'high',
                    'description': f'High peak memory usage ({peak_memory_mb:.0f} MB)',
                    'impact': 'Risk of out-of-memory errors, potential swapping',
                    'recommendation': 'Enable streaming mode or reduce cache sizes'
                })
            elif peak_memory_mb > 2048:  # > 2GB
                bottlenecks.append({
                    'type': 'moderate_memory_usage',
                    'severity': 'medium',
                    'description': f'Moderate memory usage ({peak_memory_mb:.0f} MB)',
                    'impact': 'May limit parallel processing capability',
                    'recommendation': 'Monitor memory usage and consider streaming mode for larger datasets'
                })
        
        # Bottleneck 7: Parallel processing efficiency
        if self.enable_parallel_processing and hasattr(self, 'parallel_processor') and self.parallel_processor:
            parallel_stats = self.parallel_processor.get_processing_stats()
            parallel_efficiency = parallel_stats.load_balancing_efficiency
            if parallel_efficiency < 0.6:
                bottlenecks.append({
                    'type': 'low_parallel_efficiency',
                    'severity': 'high',
                    'description': f'Low parallel processing efficiency ({parallel_efficiency:.1%})',
                    'impact': 'Workers are not being utilized effectively',
                    'recommendation': 'Adjust worker count or batch size for better load balancing'
                })
            elif parallel_efficiency < 0.8:
                bottlenecks.append({
                    'type': 'moderate_parallel_efficiency',
                    'severity': 'medium',
                    'description': f'Parallel efficiency could be improved ({parallel_efficiency:.1%})',
                    'impact': 'Some worker idle time',
                    'recommendation': 'Fine-tune parallel processing parameters'
                })
        
        # Sort bottlenecks by severity (high first)
        severity_order = {'high': 0, 'medium': 1, 'low': 2}
        bottlenecks.sort(key=lambda x: severity_order.get(x['severity'], 3))
        
        return bottlenecks
    
    def _get_efficiency_grade(self, score: float) -> str:
        """
        Convert efficiency score to letter grade.
        
        Args:
            score: Efficiency score (0-100)
            
        Returns:
            Letter grade (A+ to F)
        """
        if score >= 95:
            return 'A+'
        elif score >= 90:
            return 'A'
        elif score >= 85:
            return 'A-'
        elif score >= 80:
            return 'B+'
        elif score >= 75:
            return 'B'
        elif score >= 70:
            return 'B-'
        elif score >= 65:
            return 'C+'
        elif score >= 60:
            return 'C'
        elif score >= 55:
            return 'C-'
        elif score >= 50:
            return 'D'
        else:
            return 'F'
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        Get comprehensive performance report from the performance monitor.
        
        Returns:
            Detailed performance report dictionary
        """
        if hasattr(self, 'performance_monitor'):
            return self.performance_monitor.get_detailed_report()
        return {}
    
    def get_performance_analysis(self) -> Dict[str, Any]:
        """
        Get comprehensive performance analysis with complexity validation.
        
        Returns:
            Detailed performance analysis dictionary
        """
        if not hasattr(self, 'performance_monitor') or not self.performance_monitor.current_report:
            return {}
        
        # Perform comprehensive analysis
        return self.performance_analyzer.analyze_performance_report(self.performance_monitor.current_report)
    
    def validate_on_complexity(self, expected_records_per_second: float = 10000) -> Dict[str, Any]:
        """
        Validate that the engine achieves O(N) complexity performance.
        
        Args:
            expected_records_per_second: Expected performance for O(N) algorithm
            
        Returns:
            Complexity validation results
        """
        if not hasattr(self, 'performance_monitor') or not self.performance_monitor.current_report:
            return {'error': 'No performance data available'}
        
        return self.performance_analyzer.compare_with_theoretical_performance(
            self.performance_monitor.current_report,
            expected_records_per_second
        )
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get current performance summary.
        
        Returns:
            Current performance metrics summary
        """
        if hasattr(self, 'performance_monitor'):
            return self.performance_monitor.get_current_performance_summary()
        return {}
    
    def compare_performance_with_baseline(self, baseline_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare current performance with baseline engine metrics.
        
        Args:
            baseline_metrics: Performance metrics from baseline engine
            
        Returns:
            Performance comparison results
        """
        if not hasattr(self, 'performance_monitor'):
            return {}
        
        try:
            comparison = self.performance_monitor.compare_with_baseline(
                baseline_engine_name="AnchorBasedEngine",
                baseline_metrics=baseline_metrics
            )
            
            return {
                'current_engine': {
                    'name': comparison.engine_name,
                    'execution_time_seconds': comparison.execution_time_seconds,
                    'memory_peak_mb': comparison.memory_peak_mb,
                    'records_processed': comparison.records_processed,
                    'matches_found': comparison.matches_found,
                    'windows_processed': comparison.windows_processed,
                    'records_per_second': comparison.records_per_second,
                    'matches_per_second': comparison.matches_per_second,
                    'windows_per_second': comparison.windows_per_second,
                    'memory_per_1k_records_mb': comparison.memory_per_1k_records_mb
                },
                'baseline_comparison': comparison.metadata.get('baseline_comparison').__dict__ if comparison.metadata.get('baseline_comparison') else {},
                'improvements': comparison.metadata.get('improvements', {}),
                'performance_analysis': self._analyze_performance_improvements(comparison.metadata.get('improvements', {}))
            }
        except Exception as e:
            return {'error': f"Performance comparison failed: {str(e)}"}
    
    def _analyze_performance_improvements(self, improvements: Dict[str, float]) -> Dict[str, str]:
        """
        Analyze performance improvements and provide human-readable descriptions.
        
        Args:
            improvements: Dictionary of improvement factors
            
        Returns:
            Dictionary with analysis descriptions
        """
        analysis = {}
        
        if 'speed_improvement' in improvements:
            speed_factor = improvements['speed_improvement']
            if speed_factor > 10:
                analysis['speed'] = f"Dramatically faster: {speed_factor:.1f}x speedup"
            elif speed_factor > 2:
                analysis['speed'] = f"Significantly faster: {speed_factor:.1f}x speedup"
            elif speed_factor > 1.2:
                analysis['speed'] = f"Moderately faster: {speed_factor:.1f}x speedup"
            elif speed_factor > 0.8:
                analysis['speed'] = f"Similar performance: {speed_factor:.1f}x"
            else:
                analysis['speed'] = f"Slower: {1/speed_factor:.1f}x slower"
        
        if 'memory_efficiency' in improvements:
            memory_factor = improvements['memory_efficiency']
            if memory_factor > 2:
                analysis['memory'] = f"Much more memory efficient: {memory_factor:.1f}x less memory"
            elif memory_factor > 1.2:
                analysis['memory'] = f"More memory efficient: {memory_factor:.1f}x less memory"
            elif memory_factor > 0.8:
                analysis['memory'] = f"Similar memory usage: {memory_factor:.1f}x"
            else:
                analysis['memory'] = f"Uses more memory: {1/memory_factor:.1f}x more memory"
        
        return analysis
    
    def get_complexity_analysis(self) -> Dict[str, Any]:
        """
        Get algorithm complexity analysis.
        
        Returns:
            Dictionary with complexity analysis results
        """
        if hasattr(self, 'performance_analyzer'):
            return self.performance_analyzer.analyze_algorithm_complexity()
        return {}
    
    def get_performance_insights(self) -> Dict[str, Any]:
        """
        Get comprehensive performance insights.
        
        Returns:
            Dictionary with performance insights and recommendations
        """
        if hasattr(self, 'performance_analyzer'):
            return self.performance_analyzer.generate_performance_insights()
        return {}
    
    def compare_with_anchor_engine_advanced(self, anchor_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Advanced comparison with anchor-based engine including scalability analysis.
        
        Args:
            anchor_metrics: Performance metrics from anchor-based engine
            
        Returns:
            Detailed comparison analysis with insights
        """
        if hasattr(self, 'performance_analyzer'):
            return self.performance_analyzer.compare_with_anchor_engine(anchor_metrics)
        return self.compare_with_baseline_engine(anchor_metrics)
    
    def export_performance_data(self, filepath: str):
        """
        Export performance data to file.
        
        Args:
            filepath: Path to export performance data
        """
        if hasattr(self, 'performance_monitor'):
            self.performance_monitor.export_performance_data(filepath)
            print(f"[TimeWindow] Performance data exported to {filepath}")
        else:
            print("[TimeWindow] No performance monitor available for export")
    
    def _extract_feather_paths(self, wing: Wing) -> Dict[str, str]:
        """
        Extract feather paths from wing configuration.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            Dictionary mapping feather_id to database path
        """
        feather_paths = {}
        
        for feather_spec in wing.feathers:
            # Get database path from feather spec
            if hasattr(feather_spec, 'database_path') and feather_spec.database_path:
                feather_paths[feather_spec.feather_id] = feather_spec.database_path
            elif hasattr(feather_spec, 'feather_path') and feather_spec.feather_path:
                feather_paths[feather_spec.feather_id] = feather_spec.feather_path
        
        return feather_paths

    def _extract_semantic_data_from_records(self, 
                                           enhanced_records: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Extract semantic data from enhanced feather records.
        
        This method iterates through enhanced records that have been processed by
        the semantic integration layer and extracts the _semantic_mappings from each
        record to build a consolidated semantic_data dict for the CorrelationMatch.
        
        Args:
            enhanced_records: Dict of feather_id -> enhanced record with _semantic_mappings
            
        Returns:
            Consolidated semantic_data dict for the match containing:
            - Individual semantic mappings keyed by feather_id.field_name
            - _metadata with mappings_applied flag and count
            
        Requirements: 2.2, 2.3
        """
        semantic_data = {}
        mappings_count = 0
        
        for feather_id, record in enhanced_records.items():
            if not isinstance(record, dict):
                continue
            
            semantic_mappings = record.get('_semantic_mappings', {})
            if not semantic_mappings:
                continue
            
            for field_name, mapping_info in semantic_mappings.items():
                if isinstance(mapping_info, dict) and 'semantic_value' in mapping_info:
                    # Use feather_id.field_name as key to avoid collisions
                    key = f"{feather_id}.{field_name}" if feather_id else field_name
                    semantic_data[key] = {
                        'semantic_value': mapping_info['semantic_value'],
                        'technical_value': mapping_info.get('technical_value', ''),
                        'description': mapping_info.get('description', ''),
                        'category': mapping_info.get('category', ''),
                        'confidence': mapping_info.get('confidence', 1.0),
                        'rule_name': mapping_info.get('rule_name', field_name),
                        'feather_id': feather_id
                    }
                    mappings_count += 1
        
        # Add metadata
        semantic_data['_metadata'] = {
            'mappings_applied': mappings_count > 0,
            'mappings_count': mappings_count,
            'engine_type': self.__class__.__name__
        }
        
        # Task 11.2: Add debug logging for semantic data extraction
        # Requirements: 7.1, 7.2 - Log semantic mapping application details
        if self.debug_mode and mappings_count > 0:
            logger.debug(f"[Time-Window Engine] Extracted semantic data: {mappings_count} mappings from {len(enhanced_records)} records")
            # Log summary of semantic values found
            semantic_values = [v.get('semantic_value', '') for k, v in semantic_data.items() 
                             if k != '_metadata' and isinstance(v, dict)]
            if semantic_values:
                unique_values = list(set(semantic_values))[:5]  # Show first 5 unique values
                logger.debug(f"[Time-Window Engine] Semantic values sample: {unique_values}")
        
        return semantic_data
    
    def _extract_semantic_data_batch(self, 
                                      all_records: List[Dict],
                                      match_indices: List[int]) -> List[Dict[str, Any]]:
        """
        Extract semantic data from a batch of records efficiently.
        
        Task 18: Batch semantic processing optimization
        Requirements: 6.5 - Process semantic mappings in batches rather than individually
        
        This method processes all records from multiple matches in a single batch,
        then distributes the semantic data back to individual matches.
        
        Args:
            all_records: List of all records from all matches (flattened)
            match_indices: List mapping each record to its match index
            
        Returns:
            List of semantic_data dicts, one per match
        """
        # Initialize semantic data for each match
        num_matches = max(match_indices) + 1 if match_indices else 0
        semantic_data_per_match = [{'_metadata': {'mappings_applied': False, 'mappings_count': 0}} 
                                    for _ in range(num_matches)]
        
        # Process all records and group semantic data by match
        for record_idx, record in enumerate(all_records):
            if not isinstance(record, dict):
                continue
            
            match_idx = match_indices[record_idx]
            semantic_mappings = record.get('_semantic_mappings', {})
            
            if not semantic_mappings:
                continue
            
            # Extract feather_id from record
            feather_id = record.get('_feather_id', '')
            
            # Add semantic mappings to the appropriate match's semantic data
            for field_name, mapping_info in semantic_mappings.items():
                if isinstance(mapping_info, dict) and 'semantic_value' in mapping_info:
                    # Use feather_id.field_name as key to avoid collisions
                    key = f"{feather_id}.{field_name}" if feather_id else field_name
                    semantic_data_per_match[match_idx][key] = {
                        'semantic_value': mapping_info['semantic_value'],
                        'technical_value': mapping_info.get('technical_value', ''),
                        'description': mapping_info.get('description', ''),
                        'category': mapping_info.get('category', ''),
                        'confidence': mapping_info.get('confidence', 1.0),
                        'rule_name': mapping_info.get('rule_name', field_name),
                        'feather_id': feather_id
                    }
                    # Update metadata
                    semantic_data_per_match[match_idx]['_metadata']['mappings_count'] += 1
                    semantic_data_per_match[match_idx]['_metadata']['mappings_applied'] = True
        
        # Add engine type to metadata
        for semantic_data in semantic_data_per_match:
            semantic_data['_metadata']['engine_type'] = self.__class__.__name__
        
        # Task 18: Add debug logging for batch semantic data extraction
        if self.debug_mode:
            total_mappings = sum(sd['_metadata']['mappings_count'] for sd in semantic_data_per_match)
            if total_mappings > 0:
                logger.debug(f"[Time-Window Engine] Batch extracted semantic data: {total_mappings} mappings from {len(all_records)} records across {num_matches} matches")
        
        return semantic_data_per_match

    def _apply_semantic_mappings_to_single_match(self, 
                                                match: CorrelationMatch, 
                                                wing: Any) -> CorrelationMatch:
        """
        Apply semantic mappings to a single correlation match.
        Used in streaming mode to apply semantic mappings before writing to database.
        
        IMPORTANT: This method checks the SemanticMappingController to determine if
        per-record semantic mapping should be skipped (when Identity Semantic Phase is enabled).
        
        Args:
            match: Single correlation match to process
            wing: Wing configuration for context
            
        Returns:
            Enhanced match with semantic mapping information (or original match if skipped)
            
        Requirements: 2.1, 2.2 - Store semantic data in CorrelationMatch.semantic_data
        Requirements: 1.5, 2.5 - Semantic processing isolation (skip if Identity Semantic Phase enabled)
        """
        # CRITICAL: Check if per-record semantic mapping should be skipped
        # This ensures semantic processing isolation when Identity Semantic Phase is enabled
        if hasattr(self, 'semantic_mapping_controller'):
            if not self.semantic_mapping_controller.should_apply_per_record_semantic_mapping():
                # Skip per-record semantic mapping - return original match
                return match
        
        try:
            # Convert match records to format expected by semantic integration
            records_list = [record for record in match.feather_records.values()]
            
            # Apply semantic mappings
            enhanced_records_list = self.semantic_integration.apply_to_correlation_results(
                records_list,
                wing_id=getattr(wing, 'wing_id', None),
                pipeline_id=getattr(wing, 'pipeline_id', None),
                artifact_type=getattr(match, 'anchor_artifact_type', None)
            )
            
            # Convert back to match format
            enhanced_records = {}
            original_keys = list(match.feather_records.keys())
            for i, enhanced_record in enumerate(enhanced_records_list):
                key = original_keys[i] if i < len(original_keys) else f"record_{i}"
                enhanced_records[key] = enhanced_record
            
            # Extract actual semantic values from enhanced records
            semantic_data = self._extract_semantic_data_from_records(enhanced_records)
            
            # Create enhanced match with actual semantic data
            enhanced_match = CorrelationMatch(
                match_id=match.match_id,
                feather_records=enhanced_records,
                timestamp=match.timestamp,
                match_score=match.match_score,
                feather_count=match.feather_count,
                time_spread_seconds=match.time_spread_seconds,
                anchor_feather_id=match.anchor_feather_id,
                anchor_artifact_type=match.anchor_artifact_type,
                matched_application=match.matched_application,
                matched_file_path=match.matched_file_path,
                matched_event_id=match.matched_event_id,
                confidence_score=match.confidence_score,
                confidence_category=match.confidence_category,
                weighted_score=match.weighted_score,
                score_breakdown=match.score_breakdown,
                semantic_data=semantic_data
            )
            
            return enhanced_match
            
        except Exception as e:
            # Requirements 2.4: Log error and continue processing
            logger.warning(f"Failed to apply semantic mappings to match {match.match_id}: {e}")
            
            # Return original match with error metadata
            error_semantic_data = {
                '_metadata': {
                    'mappings_applied': False,
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'match_id': match.match_id,
                    'engine_type': 'TimeBasedCorrelationEngine'
                }
            }
            
            # Create match with error semantic_data
            error_match = CorrelationMatch(
                match_id=match.match_id,
                feather_records=match.feather_records,
                timestamp=match.timestamp,
                match_score=match.match_score,
                feather_count=match.feather_count,
                time_spread_seconds=match.time_spread_seconds,
                anchor_feather_id=match.anchor_feather_id,
                anchor_artifact_type=match.anchor_artifact_type,
                matched_application=match.matched_application,
                matched_file_path=match.matched_file_path,
                matched_event_id=match.matched_event_id,
                confidence_score=match.confidence_score,
                confidence_category=match.confidence_category,
                weighted_score=match.weighted_score,
                score_breakdown=match.score_breakdown,
                semantic_data=error_semantic_data
            )
            
            return error_match

    def _apply_semantic_mappings_to_matches(self, 
                                          matches: List[CorrelationMatch], 
                                          wing: Any) -> List[CorrelationMatch]:
        """
        Apply semantic mappings to correlation matches with comprehensive error handling.
        
        IMPORTANT: This method checks the SemanticMappingController to determine if
        per-record semantic mapping should be skipped (when Identity Semantic Phase is enabled).
        
        Task 6.1: Enhanced graceful degradation for semantic mapping failures
        Requirements: 7.1, 7.2, 7.3 - Ensure correlation continues even if semantic mapping fails
        Requirements: 1.5, 2.5 - Semantic processing isolation (skip if Identity Semantic Phase enabled)
        
        Args:
            matches: List of correlation matches
            wing: Wing configuration for context
            
        Returns:
            Enhanced matches with semantic mapping information (or original matches if skipped)
        """
        # CRITICAL: Check if per-record semantic mapping should be skipped
        # This ensures semantic processing isolation when Identity Semantic Phase is enabled
        from ..identity_semantic_phase import SemanticMappingController
        
        # Check if we have a semantic mapping controller that says to skip per-record mapping
        if hasattr(self, 'semantic_mapping_controller'):
            if not self.semantic_mapping_controller.should_apply_per_record_semantic_mapping():
                if self.debug_mode:
                    logger.info("[Time-Window Engine] Skipping per-record semantic mapping - will be applied in Identity Semantic Phase")
                print("[Time-Window Engine] Semantic mapping deferred to Identity Semantic Phase")
                return matches
        
        # Task 6.1: Check if semantic integration is available before proceeding
        if not hasattr(self, 'semantic_integration') or not self.semantic_integration:
            logger.warning("Semantic integration not available - skipping semantic mapping")
            print("[SEMANTIC] WARNING: Semantic integration not initialized - continuing without semantic mapping")
            return matches
        
        if not self.semantic_integration.is_enabled():
            logger.info("Semantic mapping is disabled, skipping mapping application")
            print("[SEMANTIC] INFO: Semantic mapping disabled - continuing correlation")
            return matches
        
        # Task 6.1: Check semantic integration health before processing
        if not self.semantic_integration.is_healthy():
            logger.warning("Semantic integration health check failed - continuing without semantic mapping")
            print("[SEMANTIC] WARNING: Semantic integration unhealthy - continuing correlation without semantic mapping")
            return matches
        
        enhanced_matches = []
        errors_count = 0
        critical_failure = False
        
        try:
            # Task 18: Batch semantic processing optimization
            # Requirements: 6.5 - Process all matches at once instead of one-by-one
            
            # Phase 1: Collect all records from all matches into a single batch
            all_records = []
            match_indices = []
            record_to_match_map = []  # Track which records belong to which match
            
            for match_idx, match in enumerate(matches):
                for feather_id, record in match.feather_records.items():
                    record_with_feather = record.copy() if isinstance(record, dict) else {'value': record}
                    record_with_feather['_feather_id'] = feather_id
                    all_records.append(record_with_feather)
                    match_indices.append(match_idx)
                    record_to_match_map.append((match_idx, feather_id))
            
            # Phase 2: Apply semantic mappings to all records in one batch
            enhanced_records_list = self.semantic_integration.apply_to_correlation_results(
                all_records,
                wing_id=getattr(wing, 'wing_id', None),
                pipeline_id=getattr(wing, 'pipeline_id', None),
                artifact_type=getattr(matches[0], 'anchor_artifact_type', None) if matches else None
            )
            
            # Phase 3: Extract semantic data for all matches in one pass
            semantic_data_per_match = self._extract_semantic_data_batch(enhanced_records_list, match_indices)
            
            # Phase 4: Reconstruct enhanced records per match
            enhanced_records_per_match = [{}  for _ in range(len(matches))]
            for record_idx, enhanced_record in enumerate(enhanced_records_list):
                match_idx, feather_id = record_to_match_map[record_idx]
                enhanced_records_per_match[match_idx][feather_id] = enhanced_record
            
            # Phase 5: Create enhanced matches with batch-processed semantic data
            for match_idx, match in enumerate(matches):
                try:
                    semantic_data = semantic_data_per_match[match_idx]
                    enhanced_records = enhanced_records_per_match[match_idx]
                    
                    # Task 11.2: Log per-match semantic mapping count (Requirements: 7.1, 7.2)
                    if self.debug_mode:
                        mappings_count = semantic_data.get('_metadata', {}).get('mappings_count', 0)
                        if mappings_count > 0:
                            logger.debug(f"[Time-Window Engine] Match {match.match_id}: {mappings_count} semantic mappings applied")
                    
                    # Create enhanced match with actual semantic data (not just a flag)
                    enhanced_match = CorrelationMatch(
                        match_id=match.match_id,
                        feather_records=enhanced_records,
                        timestamp=match.timestamp,
                        match_score=match.match_score,
                        feather_count=match.feather_count,
                        time_spread_seconds=match.time_spread_seconds,
                        anchor_feather_id=match.anchor_feather_id,
                        anchor_artifact_type=match.anchor_artifact_type,
                        matched_application=match.matched_application,
                        matched_file_path=match.matched_file_path,
                        matched_event_id=match.matched_event_id,
                        confidence_score=match.confidence_score,
                        confidence_category=match.confidence_category,
                        weighted_score=match.weighted_score,
                        score_breakdown=match.score_breakdown,
                        semantic_data=semantic_data  # Now contains actual values from batch processing
                    )
                    
                    enhanced_matches.append(enhanced_match)
                    
                except Exception as e:
                    # Task 6.1: Log error and continue processing remaining matches
                    # Requirements: 7.1, 7.2, 7.3 - Never stop correlation due to semantic mapping failures
                    errors_count += 1
                    logger.warning(f"Failed to create enhanced match for {match.match_id}: {e}")
                    
                    # Create match with error metadata in semantic_data
                    error_semantic_data = {
                        '_metadata': {
                            'mappings_applied': False,
                            'error': str(e),
                            'error_type': type(e).__name__,
                            'match_id': match.match_id,
                            'engine_type': 'TimeBasedCorrelationEngine',
                            'fallback_reason': 'Individual match reconstruction failed'
                        }
                    }
                    
                    # Keep original match but add error semantic_data
                    error_match = CorrelationMatch(
                        match_id=match.match_id,
                        feather_records=match.feather_records,  # Keep original records
                        timestamp=match.timestamp,
                        match_score=match.match_score,
                        feather_count=match.feather_count,
                        time_spread_seconds=match.time_spread_seconds,
                        anchor_feather_id=match.anchor_feather_id,
                        anchor_artifact_type=match.anchor_artifact_type,
                        matched_application=match.matched_application,
                        matched_file_path=match.matched_file_path,
                        matched_event_id=match.matched_event_id,
                        confidence_score=match.confidence_score,
                        confidence_category=match.confidence_category,
                        weighted_score=match.weighted_score,
                        score_breakdown=match.score_breakdown,
                        semantic_data=error_semantic_data
                    )
                    
                    enhanced_matches.append(error_match)
        
        except Exception as e:
            # Task 6.1: Critical failure in semantic mapping - continue correlation without semantic data
            # Requirements: 7.1, 7.2, 7.3 - Never crash correlation due to semantic mapping issues
            critical_failure = True
            logger.error(f"Critical failure in semantic mapping processing: {e}")
            print(f"[SEMANTIC] ERROR: Critical semantic mapping failure - {str(e)[:100]}...")
            print("[SEMANTIC] WARNING: Continuing correlation without semantic mapping")
            
            # Return original matches with error metadata
            enhanced_matches = []
            for match in matches:
                error_semantic_data = {
                    '_metadata': {
                        'mappings_applied': False,
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'engine_type': 'TimeBasedCorrelationEngine',
                        'fallback_reason': 'Critical semantic mapping failure'
                    }
                }
                
                error_match = CorrelationMatch(
                    match_id=match.match_id,
                    feather_records=match.feather_records,  # Keep original records
                    timestamp=match.timestamp,
                    match_score=match.match_score,
                    feather_count=match.feather_count,
                    time_spread_seconds=match.time_spread_seconds,
                    anchor_feather_id=match.anchor_feather_id,
                    anchor_artifact_type=match.anchor_artifact_type,
                    matched_application=match.matched_application,
                    matched_file_path=match.matched_file_path,
                    matched_event_id=match.matched_event_id,
                    confidence_score=match.confidence_score,
                    confidence_category=match.confidence_category,
                    weighted_score=match.weighted_score,
                    score_breakdown=match.score_breakdown,
                    semantic_data=error_semantic_data
                )
                
                enhanced_matches.append(error_match)
        
        # Add GUI terminal output showing semantic rule detection statistics - SUMMARY ONLY
        # Requirements: 4.1, 4.2, 4.3 - Print detected semantic rules to GUI terminal
        try:
            if not critical_failure:
                semantic_stats = self.semantic_integration.get_mapping_statistics()
                if semantic_stats.mappings_applied > 0:
                    mapping_rate = (semantic_stats.mappings_applied / semantic_stats.total_records_processed) * 100 if semantic_stats.total_records_processed > 0 else 0
                    print(f"[SEMANTIC] Time-Based Engine: {semantic_stats.mappings_applied} mappings applied ({mapping_rate:.1f}%)")
                    
                    # Show only high-level statistics
                    if semantic_stats.pattern_matches > 0 or semantic_stats.exact_matches > 0:
                        rule_types = []
                        if semantic_stats.exact_matches > 0:
                            rule_types.append(f"exact: {semantic_stats.exact_matches}")
                        if semantic_stats.pattern_matches > 0:
                            rule_types.append(f"pattern: {semantic_stats.pattern_matches}")
                        print(f"[SEMANTIC] Rule types: {', '.join(rule_types)}")
                else:
                    print("[SEMANTIC] Time-Based Engine: No semantic mappings applied")
                
                # Show errors if any
                if errors_count > 0:
                    print(f"[SEMANTIC] WARNING: {errors_count} matches had semantic mapping errors")
            else:
                print("[SEMANTIC] ERROR: Time-Based Engine semantic mapping failed - correlation completed")
        except Exception as stats_error:
            # Even statistics printing should not crash correlation
            logger.debug(f"Failed to print semantic mapping statistics: {stats_error}")
            # Don't print error to GUI - just continue silently
        
        # Log error summary if any errors occurred (debug level only)
        if errors_count > 0 and not critical_failure:
            logger.debug(f"Time-Based Engine semantic mapping completed with {errors_count} errors out of {len(matches)} matches")
        
        return enhanced_matches
    
    def _apply_semantic_rules_to_matches(self, 
                                        matches: List[CorrelationMatch], 
                                        wing: Any) -> List[CorrelationMatch]:
        """
        Apply advanced semantic rules to correlation matches.
        
        This evaluates semantic rules with AND/OR logic, wildcards, and multi-condition
        support against each match and stores the results in the match's semantic_data.
        
        Args:
            matches: List of correlation matches
            wing: Wing configuration for context
            
        Returns:
            Enhanced matches with semantic rule results
        """
        if not self.semantic_rule_evaluator:
            return matches
        
        # Reset evaluator statistics
        self.semantic_rule_evaluator.reset_statistics()
        
        enhanced_matches = []
        matches_with_results = 0
        total_rule_matches = 0
        
        for match in matches:
            try:
                # Evaluate semantic rules against this match
                results = self.semantic_rule_evaluator.evaluate_match(
                    match,
                    wing_id=self.wing_id,
                    pipeline_id=self.pipeline_id,
                    wing_rules=self.wing_semantic_rules
                )
                
                if results:
                    matches_with_results += 1
                    total_rule_matches += len(results)
                    
                    # Update match semantic_data with rule results
                    if match.semantic_data is None:
                        match.semantic_data = {}
                    
                    # Add rule results
                    match.semantic_data['semantic_rule_results'] = [r.to_dict() for r in results]
                    
                    # Set primary semantic value from first result
                    match.semantic_data['semantic_value'] = results[0].semantic_value
                    match.semantic_data['rule_name'] = results[0].rule_name
                    match.semantic_data['semantic_rules_applied'] = True
                    
                    if self.debug_mode:
                        logger.debug(f"Match {match.match_id} matched {len(results)} semantic rules")
                else:
                    # No rules matched
                    if match.semantic_data is None:
                        match.semantic_data = {}
                    match.semantic_data['semantic_rules_applied'] = True
                    match.semantic_data['semantic_rule_results'] = []
                
                enhanced_matches.append(match)
                
            except Exception as e:
                logger.warning(f"Failed to apply semantic rules to match {match.match_id}: {e}")
                
                # Add error info to semantic_data
                if match.semantic_data is None:
                    match.semantic_data = {}
                match.semantic_data['semantic_rule_error'] = str(e)
                match.semantic_data['semantic_rules_applied'] = False
                
                enhanced_matches.append(match)
        
        # Log summary
        if matches_with_results > 0:
            stats = self.semantic_rule_evaluator.get_statistics()
            logger.info(f"Applied semantic rules: {matches_with_results} matches matched {total_rule_matches} rules")
            logger.info(f"Rules loaded from: JSON configuration files (configs directory)")
            if self.debug_mode:
                logger.debug(f"Semantic rule stats: {stats.to_dict()}")
                # Log which specific rules matched
                for match in enhanced_matches:
                    if match.semantic_data and 'semantic_rule_results' in match.semantic_data:
                        results = match.semantic_data['semantic_rule_results']
                        if results:
                            rule_names = [r['rule_name'] for r in results]
                            logger.debug(f"Match {match.match_id}: matched rules {rule_names}")
        
        return enhanced_matches
    
    def _apply_weighted_scoring_to_matches(self, 
                                         matches: List[CorrelationMatch], 
                                         wing: Any) -> List[CorrelationMatch]:
        """
        Apply weighted scoring to correlation matches using integration layer.
        
        Args:
            matches: List of correlation matches
            wing: Wing configuration for scoring context
            
        Returns:
            Matches with weighted scoring information
        """
        scored_matches = []
        case_id = getattr(self.config, 'case_id', None)
        
        # Check if weighted scoring is enabled
        if not self.scoring_integration.is_enabled():
            logger.info("Weighted scoring is disabled, using simple count-based scoring")
            return self._apply_simple_count_scoring_to_matches(matches, wing)
        
        logger.info(f"Applying weighted scoring to {len(matches)} correlation matches")
        
        for match in matches:
            try:
                # Calculate weighted score using integration layer
                weighted_score = self.scoring_integration.calculate_match_scores(
                    match.feather_records, wing, case_id
                )
                
                # Create scored match with weighted scoring information
                scored_match = CorrelationMatch(
                    match_id=match.match_id,
                    feather_records=match.feather_records,
                    timestamp=match.timestamp,
                    match_score=weighted_score.get('score', match.match_score) if isinstance(weighted_score, dict) else match.match_score,
                    feather_count=match.feather_count,
                    time_spread_seconds=match.time_spread_seconds,
                    anchor_feather_id=match.anchor_feather_id,
                    anchor_artifact_type=match.anchor_artifact_type,
                    matched_application=match.matched_application,
                    matched_file_path=match.matched_file_path,
                    matched_event_id=match.matched_event_id,
                    confidence_score=weighted_score.get('score', match.confidence_score) if isinstance(weighted_score, dict) else match.confidence_score,
                    confidence_category=weighted_score.get('interpretation', match.confidence_category) if isinstance(weighted_score, dict) else match.confidence_category,
                    weighted_score=weighted_score if isinstance(weighted_score, dict) else None,
                    score_breakdown=weighted_score.get('breakdown', {}) if isinstance(weighted_score, dict) else {},
                    semantic_data=match.semantic_data
                )
                
                scored_matches.append(scored_match)
                
            except Exception as e:
                # If weighted scoring fails for this match, fall back to simple scoring
                logger.warning(f"Weighted scoring failed for match {match.match_id}: {e}")
                logger.info(f"Falling back to simple count-based scoring for match {match.match_id}")
                
                # Apply simple scoring to this match
                simple_scored_match = self._apply_simple_count_scoring_to_match(match, wing)
                scored_matches.append(simple_scored_match)
        
        # Log weighted scoring statistics
        scoring_stats = self.scoring_integration.get_scoring_statistics()
        logger.info(f"Weighted scoring application completed:")
        logger.info(f"  Matches processed: {len(matches)}")
        logger.info(f"  Scores calculated: {scoring_stats.scores_calculated}")
        logger.info(f"  Fallbacks to simple count: {scoring_stats.fallback_to_simple_count}")
        logger.info(f"  Average score: {scoring_stats.average_score:.2f}")
        
        # Log detailed scoring summary
        execution_time = 0.1  # This would be actual execution time from the calling method
        self.scoring_integration.log_scoring_summary(len(matches), execution_time)
        
        return scored_matches
    
    def _apply_simple_count_scoring_to_matches(self, 
                                             matches: List[CorrelationMatch], 
                                             wing: Any) -> List[CorrelationMatch]:
        """
        Apply simple count-based scoring as fallback when weighted scoring is disabled.
        
        Args:
            matches: List of correlation matches
            wing: Wing configuration for context
            
        Returns:
            Matches with simple count-based scoring information
        """
        scored_matches = []
        
        for match in matches:
            scored_match = self._apply_simple_count_scoring_to_match(match, wing)
            scored_matches.append(scored_match)
        
        logger.info(f"Simple count-based scoring applied to {len(matches)} matches")
        return scored_matches
    
    def _apply_simple_count_scoring_to_match(self, 
                                           match: CorrelationMatch, 
                                           wing: Any) -> CorrelationMatch:
        """
        Apply simple count-based scoring to a single match.
        
        Args:
            match: Correlation match to score
            wing: Wing configuration for context
            
        Returns:
            Match with simple count-based scoring information
        """
        # Calculate simple score based on record count
        record_count = len(match.feather_records)
        total_feathers = len(getattr(wing, 'feathers', [])) if wing else record_count
        
        # Simple score is just the count of matched records/feathers
        simple_score = record_count
        
        # Generate simple interpretation
        if total_feathers > 0:
            match_percentage = (record_count / total_feathers) * 100
            if match_percentage >= 80:
                interpretation = f"Strong Match ({record_count}/{total_feathers} feathers)"
            elif match_percentage >= 50:
                interpretation = f"Good Match ({record_count}/{total_feathers} feathers)"
            elif match_percentage >= 25:
                interpretation = f"Partial Match ({record_count}/{total_feathers} feathers)"
            else:
                interpretation = f"Weak Match ({record_count}/{total_feathers} feathers)"
        else:
            interpretation = f"Match ({record_count} records)"
        
        # Create simple scoring breakdown
        simple_breakdown = {
            feather_id: {
                'matched': True,
                'weight': 1.0,
                'contribution': 1.0,
                'tier': 1,
                'tier_name': 'Standard'
            }
            for feather_id in match.feather_records.keys()
        }
        
        # Create simple weighted score structure
        simple_weighted_score = {
            'score': simple_score,
            'interpretation': interpretation,
            'breakdown': simple_breakdown,
            'matched_feathers': record_count,
            'total_feathers': total_feathers,
            'scoring_mode': 'simple_count'
        }
        
        # Update match with simple scoring information
        return CorrelationMatch(
            match_id=match.match_id,
            feather_records=match.feather_records,
            timestamp=match.timestamp,
            match_score=simple_score,
            feather_count=match.feather_count,
            time_spread_seconds=match.time_spread_seconds,
            anchor_feather_id=match.anchor_feather_id,
            anchor_artifact_type=match.anchor_artifact_type,
            matched_application=match.matched_application,
            matched_file_path=match.matched_file_path,
            matched_event_id=match.matched_event_id,
            confidence_score=simple_score,
            confidence_category=interpretation,
            weighted_score=simple_weighted_score,
            score_breakdown=simple_breakdown,
            semantic_data=match.semantic_data
        )
    
    def _apply_scoring_to_single_match(self, match: CorrelationMatch, wing: Any) -> CorrelationMatch:
        """
        Apply weighted scoring to a single match during correlation.
        
        This is called during streaming to score matches before writing to database.
        
        Args:
            match: Correlation match to score
            wing: Wing configuration for scoring context
            
        Returns:
            Match with scoring applied
        """
        # Check if scoring is enabled
        if not self.scoring_integration.is_enabled():
            return match
        
        try:
            case_id = getattr(self.config, 'case_id', None)
            
            # Calculate weighted score
            weighted_score = self.scoring_integration.calculate_match_scores(
                match.feather_records, wing, case_id
            )
            
            if isinstance(weighted_score, dict):
                # Create scored match
                scored_match = CorrelationMatch(
                    match_id=match.match_id,
                    feather_records=match.feather_records,
                    timestamp=match.timestamp,
                    match_score=weighted_score.get('score', match.match_score),
                    feather_count=match.feather_count,
                    time_spread_seconds=match.time_spread_seconds,
                    anchor_feather_id=match.anchor_feather_id,
                    anchor_artifact_type=match.anchor_artifact_type,
                    matched_application=match.matched_application,
                    matched_file_path=match.matched_file_path,
                    matched_event_id=match.matched_event_id,
                    confidence_score=weighted_score.get('score', match.confidence_score),
                    confidence_category=weighted_score.get('interpretation', match.confidence_category),
                    weighted_score=weighted_score,
                    score_breakdown=weighted_score.get('breakdown', {}),
                    semantic_data=match.semantic_data
                )
                return scored_match
            else:
                return match
                
        except Exception as e:
            logger.warning(f"Scoring failed for match {match.match_id}: {e}")
            return match
    
    def _calculate_score(self, match: CorrelationMatch, wing_config: Any) -> float:
        """
        Calculate score for a match using centralized configuration.
        
        This method delegates to the scoring integration layer which uses
        the centralized score configuration.
        
        Args:
            match: Correlation match to score
            wing_config: Wing configuration for scoring context
        
        Returns:
            Calculated score value
        
        Requirements: 7.2, 8.3
        """
        if self.scoring_integration.is_enabled():
            case_id = getattr(self.config, 'case_id', None)
            weighted_score = self.scoring_integration.calculate_match_scores(
                match.feather_records, wing_config, case_id
            )
            if isinstance(weighted_score, dict):
                return weighted_score.get('score', 0.0)
        
        # Fallback to simple count-based scoring
        record_count = len(match.feather_records)
        total_feathers = len(getattr(wing_config, 'feathers', [])) if wing_config else record_count
        return record_count / total_feathers if total_feathers > 0 else 0.5
    
    def _interpret_score(self, score: float) -> str:
        """
        Interpret a score value using centralized configuration thresholds.
        
        Args:
            score: Score value to interpret (0.0 to 1.0)
        
        Returns:
            String interpretation ('Critical', 'High', 'Medium', 'Low', or 'Minimal')
        
        Requirements: 7.2, 8.3
        """
        config = self.score_config_manager.get_configuration()
        return config.interpret_score(score)
    
    def get_results(self) -> Optional[CorrelationResult]:
        """Get correlation results from last execution"""
        return self.last_result
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get correlation statistics from last execution"""
        if not self.last_result:
            return {}
        
        stats = {
            'execution_time': self.last_result.execution_duration_seconds,
            'record_count': sum(
                metadata.get('total_records', 0) 
                for metadata in self.last_result.feather_metadata.values()
            ),
            'match_count': self.last_result.total_matches,
            'feathers_processed': self.last_result.feathers_processed,
            'duplicate_rate': 0.0,  # Time-window scanning has minimal duplicates
            'windows_processed': getattr(self.last_result, 'windows_processed', 0),
            'semantic_mapping_enabled': self.semantic_integration.is_enabled(),
            'weighted_scoring_enabled': self.scoring_integration.is_enabled()
        }
        
        # Add semantic mapping statistics if available
        if hasattr(self.last_result, 'semantic_mapping_stats'):
            semantic_stats = self.last_result.semantic_mapping_stats
            stats.update({
                'semantic_mappings_applied': semantic_stats.mappings_applied,
                'semantic_mapping_rate': (
                    semantic_stats.mappings_applied / max(1, semantic_stats.total_records_processed)
                ) * 100,
                'pattern_matches': semantic_stats.pattern_matches,
                'exact_matches': semantic_stats.exact_matches
            })
        
        # Add weighted scoring statistics if available
        if hasattr(self.last_result, 'weighted_scoring_stats'):
            scoring_stats = self.last_result.weighted_scoring_stats
            stats.update({
                'scores_calculated': scoring_stats.scores_calculated,
                'average_score': scoring_stats.average_score,
                'highest_score': scoring_stats.highest_score,
                'lowest_score': scoring_stats.lowest_score,
                'fallback_to_simple_count': scoring_stats.fallback_to_simple_count,
                'case_specific_configs_used': scoring_stats.case_specific_configs_used,
                'global_configs_used': scoring_stats.global_configs_used
            })
        
        # Add time range detection statistics (NEW)
        time_range_stats = self.get_time_range_detection_statistics()
        if time_range_stats.get('available'):
            stats.update({
                'time_range_detection_stats': time_range_stats
            })
        
        # Add empty window skipping statistics (NEW)
        empty_window_stats = self.get_empty_window_skipping_statistics()
        if empty_window_stats.get('available'):
            stats.update({
                'empty_window_skipping_stats': empty_window_stats
            })
        
        # Add efficiency metrics (NEW)
        efficiency_metrics = self.get_efficiency_metrics()
        if efficiency_metrics.get('available'):
            stats.update({
                'efficiency_metrics': efficiency_metrics
            })
        
        return stats

    
    def apply_semantic_mapping_post_processing(self, database_path: str, execution_id: int) -> Dict[str, Any]:
        """
        Apply semantic mapping to matches in database after correlation completes.
        
        This is a post-processing step that runs AFTER streaming mode finishes,
        similar to how the Identity engine applies semantic mapping.
        
        Benefits:
        - Faster correlation (no semantic processing during streaming)
        - Better performance with large datasets
        - Easier debugging (semantic mapping is separate phase)
        - Can be re-run independently if needed
        
        Args:
            database_path: Path to correlation_results.db
            execution_id: Execution ID to process
            
        Returns:
            Dictionary with statistics about semantic mapping applied
        """
        print("\n" + "="*80)
        print("[Time-Window Engine] Starting Post-Processing Semantic Mapping")
        print("="*80)
        
        # Check if semantic mapping is enabled in settings
        try:
            from config.case_history_manager import CaseHistoryManager
            case_manager = CaseHistoryManager()
            wings_semantic_enabled = getattr(case_manager.global_config, 'wings_semantic_mapping_enabled', True)
            
            if not wings_semantic_enabled:
                print("[Time-Window Engine] ⚠ Semantic mapping is disabled in settings")
                print("[Time-Window Engine] You can enable it from Settings > General > Wings Semantic Mapping")
                print("="*80)
                return {
                    'status': 'skipped',
                    'reason': 'disabled_in_settings',
                    'message': 'Semantic mapping is disabled in general settings'
                }
        except Exception as e:
            # If we can't load settings, default to enabled (backward compatibility)
            print(f"[Time-Window Engine] ⚠ Could not load settings: {e}")
            print("[Time-Window Engine] Defaulting to semantic mapping enabled")
        
        start_time = time.time()
        
        try:
            # Import required modules
            from ..config.semantic_mapping import SemanticMappingManager
            from ..identity_semantic_phase.sql_semantic_mapper import SQLSemanticMapper
            
            # Initialize semantic manager
            print("[Time-Window Engine] Loading semantic rules...")
            semantic_manager = SemanticMappingManager()
            rules_count = len(semantic_manager.global_rules)
            print(f"[Time-Window Engine] Loaded {rules_count} semantic rules")
            
            if rules_count == 0:
                print("[Time-Window Engine] ⚠ No semantic rules found - skipping semantic mapping")
                return {
                    'success': False,
                    'reason': 'no_rules',
                    'matches_updated': 0,
                    'processing_time_seconds': time.time() - start_time
                }
            
            # Create SQL semantic mapper
            print(f"[Time-Window Engine] Initializing SQL semantic mapper...")
            print(f"[Time-Window Engine] Database: {database_path}")
            print(f"[Time-Window Engine] Execution ID: {execution_id}")
            
            mapper = SQLSemanticMapper(database_path, execution_id)
            
            # Apply semantic mapping using SQL (same as Identity engine)
            print("[Time-Window Engine] Applying semantic mapping to database...")
            result = mapper.apply_semantic_mapping(semantic_manager.global_rules)
            
            processing_time = time.time() - start_time
            
            # Print summary
            print("\n" + "="*80)
            print("[Time-Window Engine] Post-Processing Semantic Mapping Complete")
            print("="*80)
            print(f"Matches updated: {result.get('matches_updated', 0):,}")
            print(f"Processing time: {processing_time:.2f}s")
            print("="*80 + "\n")
            
            return {
                'success': True,
                'matches_updated': result.get('matches_updated', 0),
                'processing_time_seconds': processing_time,
                'details': result
            }
            
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = str(e)
            
            print(f"\n[Time-Window Engine] ❌ Error in post-processing semantic mapping: {error_msg}")
            logger.error(f"Post-processing semantic mapping failed: {e}")
            
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'reason': 'error',
                'error': error_msg,
                'matches_updated': 0,
                'processing_time_seconds': processing_time
            }

    def apply_scoring_post_processing(self, database_path: str, execution_id: int, wing: Any) -> Dict[str, Any]:
        """
        Apply weighted scoring to matches in database after correlation completes.
        
        This is a post-processing step that runs AFTER streaming mode finishes,
        updating the database with calculated scores.
        
        Args:
            database_path: Path to correlation_results.db
            execution_id: Execution ID to process
            wing: Wing configuration for scoring context
            
        Returns:
            Dictionary with statistics about scoring applied
        """
        print("\n" + "="*80)
        print("[Time-Window Engine] Starting Post-Processing Weighted Scoring")
        print("="*80)
        
        start_time = time.time()
        
        try:
            # Check if scoring is enabled
            if not self.scoring_integration.is_enabled():
                print("[Time-Window Engine] ⚠ Weighted scoring is disabled - skipping")
                return {
                    'success': False,
                    'reason': 'scoring_disabled',
                    'matches_updated': 0,
                    'processing_time_seconds': time.time() - start_time
                }
            
            # Connect to database
            import sqlite3
            conn = sqlite3.connect(database_path, timeout=30.0)
            cursor = conn.cursor()
            
            # Get all matches for this execution
            print(f"[Time-Window Engine] Loading matches from database...")
            cursor.execute("""
                SELECT match_id, feather_records, confidence_score, confidence_category
                FROM matches
                WHERE execution_id = ?
            """, (execution_id,))
            
            matches_data = cursor.fetchall()
            print(f"[Time-Window Engine] Loaded {len(matches_data):,} matches")
            
            if len(matches_data) == 0:
                conn.close()
                return {
                    'success': False,
                    'reason': 'no_matches',
                    'matches_updated': 0,
                    'processing_time_seconds': time.time() - start_time
                }
            
            # Apply scoring to each match
            print("[Time-Window Engine] Calculating weighted scores...")
            case_id = getattr(self.config, 'case_id', None)
            updates = []
            
            for match_id, feather_records_json, old_confidence_score, old_confidence_category in matches_data:
                try:
                    # Parse feather records
                    feather_records = json.loads(feather_records_json) if feather_records_json else []
                    
                    # Calculate weighted score
                    weighted_score = self.scoring_integration.calculate_match_scores(
                        feather_records, wing, case_id
                    )
                    
                    if isinstance(weighted_score, dict):
                        # Extract score components
                        score = weighted_score.get('score', old_confidence_score)
                        category = weighted_score.get('interpretation', old_confidence_category)
                        breakdown = json.dumps(weighted_score.get('breakdown', {}))
                        weighted_score_json = json.dumps(weighted_score)
                        
                        updates.append((score, category, weighted_score_json, breakdown, match_id))
                    
                except Exception as e:
                    logger.warning(f"Scoring failed for match {match_id}: {e}")
                    continue
            
            # Bulk update database
            if updates:
                print(f"[Time-Window Engine] Updating {len(updates):,} matches in database...")
                cursor.executemany("""
                    UPDATE matches
                    SET confidence_score = ?,
                        confidence_category = ?,
                        weighted_score = ?,
                        score_breakdown = ?
                    WHERE match_id = ?
                """, updates)
                conn.commit()
            
            conn.close()
            
            processing_time = time.time() - start_time
            
            # Print summary
            print("\n" + "="*80)
            print("[Time-Window Engine] Post-Processing Weighted Scoring Complete")
            print("="*80)
            print(f"Matches updated: {len(updates):,}")
            print(f"Processing time: {processing_time:.2f}s")
            print("="*80 + "\n")
            
            return {
                'success': True,
                'matches_updated': len(updates),
                'processing_time_seconds': processing_time
            }
            
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = str(e)
            
            print(f"\n[Time-Window Engine] ❌ Error in post-processing scoring: {error_msg}")
            logger.error(f"Post-processing scoring failed: {e}")
            
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'reason': 'error',
                'error': error_msg,
                'matches_updated': 0,
                'processing_time_seconds': processing_time
            }
