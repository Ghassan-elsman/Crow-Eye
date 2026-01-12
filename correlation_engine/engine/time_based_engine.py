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
    TwoPhaseConfig
)
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
from ..wings.core.wing_model import Wing
from ..config.semantic_mapping import SemanticMappingManager

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
    
    def __init__(self, feather_loader: FeatherLoader, debug_mode: bool = False):
        self.loader = feather_loader
        self.timestamp_column = None
        self.timestamp_format = None
        self.debug_mode = debug_mode
        
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
        
        # Cache for query results (for overlapping time windows)
        self._query_result_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._max_cache_size = 100  # Limit cache size to prevent memory issues
        
        # Initialize with error handling
        self._detect_and_index_timestamps()
    
    def _detect_and_index_timestamps(self):
        """Detect timestamp column and format, then ensure proper indexing with error handling"""
        def detect_operation(connection):
            # Try to detect timestamp columns using multiple methods
            timestamp_detected = False
            
            # Method 1: Try forensic patterns if detect_columns exists
            if hasattr(self.loader, 'detect_columns'):
                try:
                    detected_cols = self.loader.detect_columns()
                    if detected_cols and hasattr(detected_cols, 'timestamp_columns') and detected_cols.timestamp_columns:
                        self.timestamp_column = detected_cols.timestamp_columns[0]
                        timestamp_detected = True
                        if self.debug_mode:
                            print(f"[OptimizedFeatherQuery] Found timestamp column via forensic detection: {self.timestamp_column}")
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
                            # Use the best candidate (highest confidence)
                            self.timestamp_column, detected_format, confidence = timestamp_candidates[0]
                            self.timestamp_format = detected_format.value
                            timestamp_detected = True
                            
                            if self.debug_mode:
                                print(f"[OptimizedFeatherQuery] Found timestamp column via resilient parser: "
                                      f"{self.timestamp_column} (format: {self.timestamp_format}, confidence: {confidence:.2f})")
                    except Exception as e:
                        if self.debug_mode:
                            print(f"[OptimizedFeatherQuery] Resilient parser failed: {e}")
            
            # Method 3: Final fallback detection using common column names
            if not timestamp_detected:
                self.timestamp_column = self._fallback_timestamp_detection(connection)
                if self.timestamp_column:
                    timestamp_detected = True
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Found timestamp column via fallback: {self.timestamp_column}")
            
            if self.timestamp_column:
                # Detect timestamp format if not already detected
                if not hasattr(self, 'timestamp_format') or not self.timestamp_format:
                    self.timestamp_format = self._detect_timestamp_format_resilient(connection)
                
                # OPTIMIZATION: Ensure timestamp index is created before any queries
                # This is critical for performance of time range operations
                if not self.has_timestamp_index():
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Creating timestamp index for performance optimization...")
                    self._create_universal_timestamp_index(connection)
                else:
                    if self.debug_mode:
                        print(f"[OptimizedFeatherQuery] Timestamp index already exists")
            else:
                if self.debug_mode:
                    print("[OptimizedFeatherQuery] No timestamp column found - queries will return empty results")
            
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
    
    def _fallback_timestamp_detection(self, connection) -> Optional[str]:
        """Fallback timestamp column detection with error handling"""
        # Common timestamp column names from forensic artifacts
        common_names = [
            # Generic
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
            # MFT
            'created', 'modified', 'accessed', 'mft_modified',
            # Event Logs
            'eventtimestamputc', 'event_time', 'generated_time',
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
                    return None
            
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1].lower() for row in cursor.fetchall()]
            
            # Check for exact matches first
            for common_name in common_names:
                if common_name.lower() in columns:
                    # Return the actual column name (preserve case)
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    for row in cursor.fetchall():
                        if row[1].lower() == common_name.lower():
                            return row[1]
            
            # Check for partial matches
            for col in columns:
                for pattern in ['time', 'date', 'stamp']:
                    if pattern in col.lower():
                        cursor.execute(f"PRAGMA table_info({table_name})")
                        for row in cursor.fetchall():
                            if row[1].lower() == col:
                                return row[1]
                        
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Fallback timestamp detection failed: {e}")
        
        return None
    
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
        if not self.timestamp_column:
            return []
        
        # OPTIMIZATION: Check cache first for overlapping time windows
        cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
        if cache_key in self._query_result_cache:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Cache hit for time range {start_time} to {end_time}")
            return self._query_result_cache[cache_key]
        
        def query_operation(connection):
            # Convert datetime objects to format that matches the database
            start_value = self._convert_datetime_for_query(start_time)
            end_value = self._convert_datetime_for_query(end_time)
            
            # Use indexed range query
            query = f"""
                SELECT * FROM {self.loader.current_table}
                WHERE {self.timestamp_column} >= ? AND {self.timestamp_column} <= ?
                ORDER BY {self.timestamp_column}
            """
            
            cursor = connection.cursor()
            cursor.execute(query, (start_value, end_value))
            
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
            
            # OPTIMIZATION: Cache results for future queries (with size limit)
            if len(self._query_result_cache) < self._max_cache_size:
                self._query_result_cache[cache_key] = results
            elif self.debug_mode:
                print(f"[OptimizedFeatherQuery] Query cache full ({self._max_cache_size} entries), not caching")
            
            return results
            
        except Exception as e:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Query failed for range {start_time} to {end_time}: {e}")
            return []  # Return empty list on failure
    
    def _convert_datetime_for_query(self, dt: datetime) -> Any:
        """Convert datetime to format that matches database timestamp format"""
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
        else:
            # Default: try ISO format
            return dt.isoformat()
    
    def get_timestamp_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Get the min/max timestamp range from this feather with error handling and caching.
        
        OPTIMIZATION: Results are cached after first query to avoid repeated MIN/MAX queries.
        This is critical for performance when detecting time ranges across multiple feathers.
        
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
            query = f"""
                SELECT MIN({self.timestamp_column}), MAX({self.timestamp_column})
                FROM {self.loader.current_table}
                WHERE {self.timestamp_column} IS NOT NULL
            """
            cursor = connection.cursor()
            cursor.execute(query)
            result = cursor.fetchone()
            
            if result and result[0] and result[1]:
                min_val, max_val = result[0], result[1]
                min_dt = self._parse_timestamp_value(min_val)
                max_dt = self._parse_timestamp_value(max_val)
                return min_dt, max_dt
            
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
        """Parse a timestamp value to datetime object using resilient parser"""
        result = self.timestamp_parser.parse_timestamp(value)
        if result.success:
            return result.datetime_value
        
        # Fallback for edge cases not handled by resilient parser
        if isinstance(value, (int, float)):
            try:
                if value > 1000000000000:  # Milliseconds
                    return datetime.fromtimestamp(value / 1000)
                elif value > 1000000000:  # Seconds
                    return datetime.fromtimestamp(value)
            except (ValueError, OSError):
                pass
        
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
            - timestamp_range_cached: Whether timestamp range is cached
        """
        return {
            'query_cache_size': len(self._query_result_cache),
            'query_cache_max_size': self._max_cache_size,
            'query_cache_utilization_percent': (len(self._query_result_cache) / self._max_cache_size * 100) if self._max_cache_size > 0 else 0,
            'timestamp_range_cached': self._timestamp_range_cached,
            'timestamp_range_value': self._timestamp_range_cache if self._timestamp_range_cached else None
        }
    
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
    
    def quick_count_in_range(self, start_time: datetime, end_time: datetime) -> int:
        """
        Quickly count records in time range using indexed COUNT(*) query.
        
        This method uses SELECT COUNT(*) with indexed timestamp range for fast
        empty window detection. Target performance: <1ms per check.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            Number of records in the time range, or 0 on error
        """
        if not self.timestamp_column:
            return 0
        
        def count_operation(connection):
            try:
                # Convert datetime objects to format that matches the database
                start_value = self._convert_datetime_for_query(start_time)
                end_value = self._convert_datetime_for_query(end_time)
                
                # Use indexed COUNT query for fast check
                query = f"""
                    SELECT COUNT(*) FROM {self.loader.current_table}
                    WHERE {self.timestamp_column} >= ? AND {self.timestamp_column} <= ?
                """
                
                cursor = connection.cursor()
                cursor.execute(query, (start_value, end_value))
                result = cursor.fetchone()
                
                return result[0] if result else 0
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
        them into fewer database queries, reducing query overhead.
        
        Args:
            time_ranges: List of (start_time, end_time) tuples to query
            
        Returns:
            Dictionary mapping each time range to its query results
        """
        if not self.timestamp_column or not time_ranges:
            return {}
        
        results = {}
        
        # Check cache first for all ranges
        uncached_ranges = []
        for time_range in time_ranges:
            start_time, end_time = time_range
            cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
            
            if cache_key in self._query_result_cache:
                results[time_range] = self._query_result_cache[cache_key]
            else:
                uncached_ranges.append(time_range)
        
        if not uncached_ranges:
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] All {len(time_ranges)} ranges found in cache")
            return results
        
        # For uncached ranges, use batch query if they're consecutive
        # Otherwise fall back to individual queries
        if len(uncached_ranges) > 1 and self._are_ranges_consecutive(uncached_ranges):
            # Batch query: query the entire span and split results
            overall_start = min(r[0] for r in uncached_ranges)
            overall_end = max(r[1] for r in uncached_ranges)
            
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Batch querying {len(uncached_ranges)} consecutive ranges")
            
            all_records = self.query_time_range(overall_start, overall_end)
            
            # Split records into individual time ranges
            for time_range in uncached_ranges:
                start_time, end_time = time_range
                range_records = [
                    record for record in all_records
                    if self._record_in_range(record, start_time, end_time)
                ]
                results[time_range] = range_records
                
                # Cache individual results
                cache_key = f"{start_time.isoformat()}_{end_time.isoformat()}"
                if len(self._query_result_cache) < self._max_cache_size:
                    self._query_result_cache[cache_key] = range_records
        else:
            # Query individually for non-consecutive ranges
            if self.debug_mode:
                print(f"[OptimizedFeatherQuery] Querying {len(uncached_ranges)} non-consecutive ranges individually")
            
            for time_range in uncached_ranges:
                start_time, end_time = time_range
                results[time_range] = self.query_time_range(start_time, end_time)
        
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
    """
    
    def __init__(self, feather_queries: Dict[str, OptimizedFeatherQuery]):
        self.feather_queries = feather_queries
        self.query_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.cache_hits = 0
        self.cache_misses = 0
    
    def query_window(self, window: TimeWindow, progress_tracker: Optional['ProgressTracker'] = None) -> TimeWindow:
        """
        Query all feathers for records in the given time window.
        
        Args:
            window: TimeWindow to populate with records
            progress_tracker: Optional progress tracker for reporting query progress
            
        Returns:
            TimeWindow populated with records from all feathers
        """
        total_feathers = len(self.feather_queries)
        feathers_queried = 0
        total_records = 0
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
        
        return window
    
    def quick_check_window_has_records(self, window: TimeWindow) -> bool:
        """
        Quickly check if window has any records without performing full query.
        
        Uses COUNT(*) with indexed timestamp range for fast empty window detection.
        This method checks all feathers and returns True if ANY feather has records
        in the window. Target performance: <1ms per window.
        
        Args:
            window: TimeWindow to check
            
        Returns:
            True if window has at least one record in any feather, False if all feathers are empty
        """
        for feather_id, query_manager in self.feather_queries.items():
            # Quick count query using index
            count = query_manager.quick_count_in_range(window.start_time, window.end_time)
            
            if count > 0:
                # Found data in this feather, no need to check others
                return True
        
        # No data found in any feather
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
                 two_phase_config: Optional['TwoPhaseConfig'] = None):
        """
        Initialize Time-Window Scanning Engine.
        
        Args:
            config: Pipeline configuration object or TimeWindowScanningConfig
            filters: Optional filter configuration
            debug_mode: Enable debug logging
            scoring_integration: Optional scoring integration (for dependency injection)
            mapping_integration: Optional semantic mapping integration (for dependency injection)
        """
        super().__init__(config, filters)
        
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
        
        # Memory management and streaming
        self.memory_manager: Optional[WindowMemoryManager] = None
        # self.streaming_writer: Optional[StreamingMatchWriter] = None
        self.streaming_writer = None  # Temporarily disabled
        self.streaming_mode_active = False
        self.memory_limit_mb = self.scanning_config.memory_limit_mb
        
        # Parallel processing configuration
        self.enable_parallel_processing = self.scanning_config.parallel_window_processing
        self.max_workers = self.scanning_config.max_workers or 4  # Default number of worker threads
        self.parallel_batch_size = self.scanning_config.parallel_batch_size
        self.parallel_processor: Optional[ParallelWindowProcessor] = None
        
        # Window processing statistics tracking
        self.window_processing_stats = WindowProcessingStats()
        
        # Time range detection result (for statistics reporting)
        self._time_range_detection_result: Optional[TimeRangeDetectionResult] = None
        
        # Performance monitoring system
        self.performance_monitor = create_performance_monitor(
            engine_name="TimeWindowScanningEngine",
            enable_detailed=debug_mode
        )
        
        # Advanced performance analyzer
        self.performance_analyzer = create_performance_analyzer()
        
        # Performance analyzer for detailed analysis
        self.performance_analyzer = create_performance_analyzer()
        
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
    
    def get_error_handling_statistics(self) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive error handling statistics.
        
        Returns:
            Dictionary with error handling statistics or None if coordinator not initialized
        """
        if self.error_coordinator:
            stats = self.error_coordinator.get_error_statistics()
            return {
                'total_errors': stats.total_errors,
                'errors_by_category': stats.errors_by_category,
                'errors_by_severity': stats.errors_by_severity,
                'recovery_success_rate': stats.recovery_success_rate,
                'average_recovery_time_seconds': stats.average_recovery_time_seconds,
                'degradation_events': stats.degradation_events,
                'system_uptime_percentage': stats.system_uptime_percentage
            }
        return None
    
    def configure_parallel_processing(self, 
                                    enable: bool = True,
                                    max_workers: Optional[int] = None,
                                    batch_size: int = 100,
                                    enable_load_balancing: bool = True):
        """
        Configure parallel processing settings.
        
        Args:
            enable: Enable or disable parallel processing
            max_workers: Maximum number of worker threads (None = auto-detect)
            batch_size: Number of windows to process in each batch
            enable_load_balancing: Enable intelligent load balancing
        """
        self.enable_parallel_processing = enable
        
        if max_workers is not None:
            self.max_workers = max_workers
        else:
            # Auto-detect optimal worker count
            import os
            cpu_count = os.cpu_count() or 4
            self.max_workers = min(cpu_count * 2, 8)  # Cap at 8 for database I/O
        
        self.parallel_batch_size = batch_size
        
        if enable:
            # Create parallel processor
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
            if self.debug_mode:
                print("[TimeWindow] Parallel processing disabled")
    
    def get_parallel_processing_stats(self) -> Optional[ParallelProcessingStats]:
        """
        Get parallel processing statistics from last execution.
        
        Returns:
            ParallelProcessingStats object or None if parallel processing not used
        """
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
            
            # Step 2: Initialize memory management and error coordination
            print(f"[Time-Window Engine] 🧠 Step 2: Initializing memory management...")
            sys.stdout.flush()
            with PhaseTimer(self.performance_monitor, ProcessingPhase.INITIALIZATION) as timer:
                self.memory_manager = WindowMemoryManager(
                    max_memory_mb=self.scanning_config.memory_limit_mb,
                    enable_gc=True
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
                print(f"[Time-Window Engine]   ✓ Error handling initialized")
                sys.stdout.flush()
            
            # Step 3: Load and initialize feather databases
            print(f"[Time-Window Engine] 📂 Step 3: Loading feather databases...")
            sys.stdout.flush()
            with PhaseTimer(self.performance_monitor, ProcessingPhase.FEATHER_LOADING) as timer:
                self._load_feathers(wing, feather_paths, result)
                timer.add_records(result.feathers_processed)
                
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
                self.window_query_manager = WindowQueryManager(self.feather_queries)
                
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
                self.window_data_collector = WindowDataCollector(
                    wing=wing,
                    storage=self.window_data_storage,
                    debug_mode=self.debug_mode
                )
                
                print(f"[Time-Window Engine]   ✓ Two-phase architecture initialized")
                print(f"[Time-Window Engine]   📁 Correlation DB: {correlation_db_path}")
                sys.stdout.flush()
            
            # Step 4: Determine overall time range for scanning
            print(f"[Time-Window Engine] ⏰ Step 4: Determining time range...")
            sys.stdout.flush()
            with PhaseTimer(self.performance_monitor, ProcessingPhase.TIME_RANGE_DETERMINATION) as timer:
                start_epoch, end_epoch = self._determine_time_range(result)
                
                # Calculate and display comprehensive time range information
                duration_hours = (end_epoch - start_epoch).total_seconds() / 3600
                duration_days = (end_epoch - start_epoch).total_seconds() / 86400
                
                print(f"[Time-Window Engine]   ✓ Time range determined successfully")
                print(f"[Time-Window Engine]   📅 Start: {start_epoch.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[Time-Window Engine]   📅 End: {end_epoch.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[Time-Window Engine]   📅 Data Span: {duration_days:.1f} days ({duration_hours:.1f} hours)")
                
                # Calculate estimated window count
                estimated_windows = self._calculate_total_windows(start_epoch, end_epoch)
                print(f"[Time-Window Engine]   🔢 Estimated windows: {estimated_windows:,}")
                
                # Calculate and display estimated processing time
                # Rough estimate: 0.5 seconds per window on average
                estimated_processing_minutes = (estimated_windows * 0.5) / 60
                estimated_time_str = self._format_time_duration(estimated_processing_minutes)
                print(f"[Time-Window Engine]   ⏱️ Estimated Processing Time: ~{estimated_time_str}")
                
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
                            print(f"[Time-Window Engine]   💡 Performance: Avoided {windows_saved:,} empty windows "
                                  f"({savings_percent:.1f}% reduction vs. year 2000 default)")
                
                sys.stdout.flush()
            
            # Step 5: Generate and process time windows
            matches = []
            total_windows = self._calculate_total_windows(start_epoch, end_epoch)
            
            processing_mode = "🔄 parallel" if self.enable_parallel_processing else "➡️ sequential"
            print(f"[Time-Window Engine] 🔍 Step 5: Scanning {total_windows:,} time windows ({processing_mode} mode)...")
            
            if self.enable_parallel_processing and self.parallel_processor:
                print(f"[Time-Window Engine]   👥 Workers: {self.max_workers}")
            
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
            
            # Apply semantic mappings to all matches if enabled
            print(f"[Time-Window Engine] 🔗 Applying semantic mappings...")
            if self.semantic_integration.is_enabled():
                enhanced_matches = self._apply_semantic_mappings_to_matches(matches, wing)
                # Update result with enhanced matches
                result.matches = enhanced_matches
                
                # Log semantic mapping statistics
                semantic_stats = self.semantic_integration.get_mapping_statistics()
                if self.debug_mode:
                    print(f"[Time-Window Engine]   ✓ Applied {semantic_stats.mappings_applied} mappings to {semantic_stats.total_records_processed} records")
                else:
                    print(f"[Time-Window Engine]   ✓ Semantic mappings applied")
                
                # Add semantic mapping statistics to result metadata
                if not hasattr(result, 'semantic_mapping_stats'):
                    result.semantic_mapping_stats = semantic_stats
            else:
                result.matches = matches
                print(f"[Time-Window Engine]   ⏭️ Semantic mappings disabled")
            
            # Apply weighted scoring to all matches if enabled
            print(f"[Time-Window Engine] 📊 Applying weighted scoring...")
            if self.scoring_integration.is_enabled():
                scored_matches = self._apply_weighted_scoring_to_matches(result.matches, wing)
                # Update result with scored matches
                result.matches = scored_matches
                
                # Log weighted scoring statistics
                scoring_stats = self.scoring_integration.get_scoring_statistics()
                if self.debug_mode:
                    avg_score = scoring_stats.average_score if hasattr(scoring_stats, 'average_score') and scoring_stats.average_score else 0
                    print(f"[Time-Window Engine]   ✓ Scored {scoring_stats.total_matches_scored} matches (avg: {avg_score:.2f})")
                else:
                    print(f"[Time-Window Engine]   ✓ Weighted scoring applied")
                
                # Add weighted scoring statistics to result metadata
                if not hasattr(result, 'weighted_scoring_stats'):
                    result.weighted_scoring_stats = scoring_stats
            else:
                print(f"[Time-Window Engine]   ⏭️ Weighted scoring disabled")
            
            # Complete progress tracking
            self.progress_tracker.complete_scanning()
            
            print(f"\n[Time-Window Engine] ✅ Phase 1 Complete: Data Collection")
            print(f"[Time-Window Engine]   📊 Windows processed: {total_windows:,}")
            print(f"[Time-Window Engine]   💾 Data saved to database")
            
            # Step 6: Phase 2 - Correlation Processing (if enabled by configuration)
            if self.two_phase_config.should_run_phase2():
                print(f"\n[Time-Window Engine] 🔗 Step 6: Phase 2 - Correlation Processing...")
                
                if self.window_data_storage and self.window_data_collector:
                    try:
                        # Import PostCorrelationProcessor
                        from .post_correlation_processor import PostCorrelationProcessor
                        
                        # Create processor
                        processor = PostCorrelationProcessor(
                            wing=wing,
                            storage=self.window_data_storage,
                            debug_mode=self.debug_mode
                        )
                        
                        # Process all windows
                        phase2_stats = processor.process_all_windows()
                        
                        print(f"[Time-Window Engine] ✅ Phase 2 Complete: Correlation Analysis")
                        print(f"[Time-Window Engine]   📊 Windows analyzed: {phase2_stats['windows_processed']:,}")
                        print(f"[Time-Window Engine]   🔗 Correlations found: {phase2_stats['correlations_found']:,}")
                        print(f"[Time-Window Engine]   ⏱️ Phase 2 time: {phase2_stats['processing_time_seconds']:.1f}s")
                        
                        # Store Phase 2 statistics in result
                        result.phase2_statistics = phase2_stats
                        
                    except Exception as phase2_error:
                        error_msg = f"Phase 2 correlation processing failed: {phase2_error}"
                        result.errors.append(error_msg)
                        print(f"[Time-Window Engine] ⚠️ {error_msg}")
                        print(f"[Time-Window Engine] ℹ️ Phase 1 data is preserved in database")
                        
                        if self.debug_mode:
                            import traceback
                            print(f"[Time-Window Engine] Stack trace: {traceback.format_exc()}")
                else:
                    print(f"[Time-Window Engine] ⏭️ Phase 2 skipped (two-phase components not initialized)")
            else:
                print(f"\n[Time-Window Engine] ⏭️ Phase 2 skipped (disabled by configuration)")
                print(f"[Time-Window Engine] ℹ️ Mode: {self.two_phase_config.get_execution_mode()}")
                if self.two_phase_config.run_phase1_only:
                    print(f"[Time-Window Engine] ℹ️ Run Phase 2 later with run_phase2_only=True")
            
            # Finalize streaming if active
            if self.streaming_mode_active and self.streaming_writer:
                self._finalize_streaming_mode(result)
            
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
            # Cleanup
            self._cleanup_feather_queries()
            
            # Record execution time
            result.execution_duration_seconds = time.time() - start_time
            
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
            
            # Print completion summary
            print(f"\n[Time-Window Engine] ✅ Complete!")
            print(f"[Time-Window Engine] ✅ Processed {total_windows:,} time windows")
            print(f"[Time-Window Engine] ✅ Found {result.total_matches:,} correlation matches")
            
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
                query_manager = OptimizedFeatherQuery(loader, debug_mode=self.debug_mode)
                self.feather_queries[feather_id] = query_manager
                
                result.feathers_processed += 1
                
                # Collect feather metadata with error handling
                try:
                    record_count = loader.get_record_count()
                    timestamp_range = query_manager.get_timestamp_range()
                    
                    result.feather_metadata[feather_id] = {
                        'artifact_type': loader.artifact_type or feather_spec.artifact_type,
                        'database_path': db_path,
                        'total_records': record_count,
                        'timestamp_column': query_manager.timestamp_column,
                        'timestamp_format': query_manager.timestamp_format,
                        'timestamp_range': {
                            'min': timestamp_range[0].isoformat() if timestamp_range[0] else None,
                            'max': timestamp_range[1].isoformat() if timestamp_range[1] else None
                        },
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
                        'artifact_type': feather_spec.artifact_type,
                        'database_path': db_path,
                        'total_records': 0,
                        'timestamp_column': None,
                        'timestamp_format': 'unknown',
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
        
        Args:
            dt: Datetime object (timezone-aware or naive)
            
        Returns:
            Timezone-aware datetime in UTC
        """
        if dt is None:
            return None
        
        # If already timezone-aware, convert to UTC
        if dt.tzinfo is not None:
            return dt.astimezone(datetime.timezone.utc) if hasattr(datetime, 'timezone') else dt
        
        # If timezone-naive, assume UTC
        from datetime import timezone
        return dt.replace(tzinfo=timezone.utc)
    
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
                print(f"[TimeWindow] ❌ {error_msg}")
                print(f"[TimeWindow] Falling back to legacy time range determination")
                if result:
                    result.warnings.append(f"Time Range Detection: {error_msg}, using fallback method")
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()
        
        # Fallback to legacy behavior (for backward compatibility)
        print(f"[TimeWindow] Using legacy time range determination (auto-detection disabled)")
        
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
                elif avg_windows_per_day < 24:  # Less than hourly windows
                    recommendations.append(
                        f"Low temporal resolution detected ({avg_windows_per_day:.0f} windows/day). "
                        f"Consider decreasing window_size_minutes (currently {self.window_size_minutes}) "
                        f"for more fine-grained temporal analysis."
                    )
        
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
            window_end = current_time + timedelta(minutes=self.window_size_minutes)
            
            yield TimeWindow(
                start_time=current_time,
                end_time=window_end,
                window_id=f"window_{window_counter:06d}",
                records_by_feather={}  # Empty dict, will be populated by query_window
            )
            
            # Advance by scanning interval
            current_time += timedelta(minutes=self.scanning_interval_minutes)
            window_counter += 1
    
    def _process_window(self, window: TimeWindow, wing: Wing) -> List[CorrelationMatch]:
        """
        Process a single time window - Phase 1: Fast data collection only.
        
        NO correlation, NO semantic matching, NO scoring - just collect and save data.
        Phase 2 (correlation processing) will be done separately after all windows are collected.
        
        Args:
            window: TimeWindow to process
            wing: Wing configuration
            
        Returns:
            Empty list (Phase 1 doesn't create matches, just saves data)
        """
        # Start window performance monitoring
        window_metrics = self.performance_monitor.start_window_processing(
            window.window_id, window.start_time, window.end_time
        )
        
        try:
            # Step 0: Quick empty window check (if enabled)
            if self.scanning_config.enable_quick_empty_check:
                quick_check_start = time.time()
                has_records = self.window_query_manager.quick_check_window_has_records(window)
                quick_check_duration = time.time() - quick_check_start
                
                # Track empty window check time
                if hasattr(self, 'window_processing_stats'):
                    self.window_processing_stats.empty_window_check_time_seconds += quick_check_duration
                
                if not has_records:
                    # Window is empty - skip immediately without full query
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
            
            # Step 3: PHASE 1 - Collect and save window data (NO correlation)
            collection_start_time = time.time()
            
            # Use WindowDataCollector to organize and save data
            success = self.window_data_collector.collect_and_save(
                window_id=window.window_id,
                start_time=window.start_time,
                end_time=window.end_time,
                records_by_feather=populated_window.records_by_feather
            )
            
            collection_duration = time.time() - collection_start_time
            
            # Record collection timing (replaces correlation timing)
            if window_metrics:
                self.performance_monitor.record_correlation_timing(
                    window.window_id, collection_duration, 0  # No semantic comparisons in Phase 1
                )
            
            # Complete window monitoring
            if window_metrics:
                # In Phase 1, we don't create matches - just save data
                # Report 0 matches but track that we processed the window
                self.performance_monitor.complete_window_processing(
                    window.window_id, records_found, 0, feathers_queried
                )
            
            # Phase 1 returns empty list - matches will be created in Phase 2
            return []
            
        except Exception as e:
            # Complete window monitoring with error
            if window_metrics:
                self.performance_monitor.complete_window_processing(
                    window.window_id, 0, 0, 0
                )
            raise e
    
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
        
        for window in self._generate_time_windows(start_epoch, end_epoch):
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
            
            # Log time-window-specific progress - only every 5%
            progress_percent = (window_count / total_windows * 100) if total_windows > 0 else 0
            progress_interval = max(1, total_windows // 20)  # Every 5%
            
            # Print progress every 5%
            if window_count % progress_interval == 0:
                # Get current progress stats
                progress_stats = self.progress_tracker._create_overall_progress()
                
                # Format progress message with enhanced statistics
                progress_msg = f"[Time-Window Engine]   Progress: {progress_percent:.0f}% ({window_count:,}/{total_windows:,} windows, {len(matches):,} matches)"
                
                # Add empty window statistics if significant
                if progress_stats.empty_windows_skipped > 0:
                    progress_msg += f" | Skipped: {progress_stats.empty_windows_skipped:,} empty ({progress_stats.skip_rate_percentage:.1f}%)"
                
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
            
            # Check memory pressure before processing window (silently)
            self._check_memory_and_enable_streaming(result, wing)
            
            # Process this time window
            window_matches = self._process_window(window, wing)
            
            # Calculate processing metrics
            window_processing_time = time.time() - window_start_time
            records_found = sum(len(records) for records in window.records_by_feather.values())
            feathers_with_records = list(window.records_by_feather.keys())
            is_empty_window = (records_found == 0)
            
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
                result.add_match(match)
                
                # Write to streaming database if active
                if self.streaming_mode_active and self.streaming_writer:
                    result_id = getattr(result, '_result_id', 0)
                    if result_id > 0:
                        self.streaming_writer.write_match(result_id, match)
            
            matches.extend(window_matches)
            window_count += 1
            
            # Complete window processing tracking with time-window-specific details
            memory_usage = self.memory_manager.check_memory_pressure().current_memory_mb if self.memory_manager else None
            
            # Perform memory cleanup between windows if needed (silently)
            self._cleanup_memory_between_windows(window_count)
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
            
            # Report time-window processing milestone
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
            
            if self.debug_mode and window_count % 1000 == 0:
                memory_report = self.memory_manager.check_memory_pressure() if self.memory_manager else None
                memory_info = f", memory: {memory_report.current_memory_mb:.1f}MB" if memory_report else ""
                streaming_info = " (streaming)" if self.streaming_mode_active else ""
                print(f"[TimeWindow] Processed {window_count}/{total_windows} windows, "
                      f"{result.total_matches} matches found{memory_info}{streaming_info}")
        
        return matches
    
    def _process_windows_parallel(self, 
                                start_epoch: datetime, 
                                end_epoch: datetime, 
                                wing: Wing, 
                                result: CorrelationResult) -> List[CorrelationMatch]:
        """
        Process windows in parallel using ParallelWindowProcessor.
        
        Args:
            start_epoch: Start time for scanning
            end_epoch: End time for scanning
            wing: Wing configuration
            result: CorrelationResult to update
            
        Returns:
            List of all correlation matches found
        """
        if not self.parallel_processor:
            raise RuntimeError("Parallel processor not initialized")
        
        # Generate all windows first (needed for parallel processing)
        windows = list(self._generate_time_windows(start_epoch, end_epoch))
        
        if self.debug_mode:
            print(f"[TimeWindow] Starting parallel processing of {len(windows)} windows "
                  f"with {self.max_workers} workers")
        
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
        """Cleanup parallel processing resources"""
        if self.parallel_processor:
            # Request cancellation if processing is active
            if self.parallel_processor.is_processing:
                self.parallel_processor.request_cancellation()
            
            # The parallel processor handles its own cleanup
            self.parallel_processor = None
    
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
            print(f"[Time-Window Engine] 💾 Enabling streaming mode: Memory usage ({memory_report.current_memory_mb:.0f}MB) exceeds limit")
            
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
                
                # Create result session
                result_id = self.streaming_writer.create_result(
                    execution_id=0,  # Will be updated later
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
        # Create streaming directory in same location as wing
        wing_dir = Path(wing.wing_path).parent if hasattr(wing, 'wing_path') else Path.cwd()
        streaming_dir = wing_dir / "streaming_results"
        streaming_dir.mkdir(exist_ok=True)
        
        # Create unique database name with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_name = f"{wing.wing_id}_{timestamp}_streaming.db"
        
        return str(streaming_dir / db_name)
    
    def _cleanup_memory_between_windows(self, window_count: int):
        """
        Perform memory cleanup between windows to maintain efficiency.
        
        Args:
            window_count: Current window count for cleanup scheduling
        """
        if not self.memory_manager:
            return
        
        # Check memory pressure
        memory_report = self.memory_manager.check_memory_pressure()
        
        # Perform cleanup based on memory usage and window count
        should_cleanup = (
            memory_report.usage_percentage > 70 or  # High memory usage
            window_count % 1000 == 0 or  # Periodic cleanup every 1000 windows
            memory_report.is_over_limit  # Over memory limit
        )
        
        if should_cleanup:
            # Force garbage collection silently
            collected = self.memory_manager.force_garbage_collection()
            
            # Clear query cache if it exists
            if hasattr(self, 'query_manager') and hasattr(self.query_manager, 'query_cache'):
                cache_size = len(self.query_manager.query_cache)
                if cache_size > 100:  # Clear cache if it's getting large
                    self.query_manager.query_cache.clear()
    
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
        
        Returns:
            Dictionary containing efficiency metrics:
                - overall_efficiency_score: Overall efficiency score (0-100)
                - time_range_optimization: Metrics about time range optimization
                - empty_window_optimization: Metrics about empty window skipping
                - total_time_saved_seconds: Total time saved by all optimizations
                - performance_improvements: Performance improvement factors
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
            'recommendations': recommendations
        }
    
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
    def _apply_semantic_mappings_to_matches(self, 
                                          matches: List[CorrelationMatch], 
                                          wing: Any) -> List[CorrelationMatch]:
        """
        Apply semantic mappings to correlation matches.
        
        Args:
            matches: List of correlation matches
            wing: Wing configuration for context
            
        Returns:
            Enhanced matches with semantic mapping information
        """
        enhanced_matches = []
        
        for match in matches:
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
                for i, enhanced_record in enumerate(enhanced_records_list):
                    # Use original keys if available, otherwise use index
                    original_keys = list(match.feather_records.keys())
                    key = original_keys[i] if i < len(original_keys) else f"record_{i}"
                    enhanced_records[key] = enhanced_record
                
                # Create enhanced match with semantic information
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
                    semantic_data={'semantic_mappings_applied': True, 'engine_type': 'time_window_scanning'}
                )
                
                enhanced_matches.append(enhanced_match)
                
            except Exception as e:
                # If semantic mapping fails, include original match with warning
                logger.warning(f"Failed to apply semantic mappings to match {match.match_id}: {e}")
                
                # Add warning to match semantic_data
                match.semantic_data = {
                    'semantic_mapping_error': str(e),
                    'semantic_mappings_applied': False
                }
                
                enhanced_matches.append(match)
        
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