"""
Progress Tracking System for Correlation Engines

This module provides comprehensive progress tracking and monitoring capabilities
for both time-window scanning and identity-based correlation engines, including 
event system, time estimation, and cancellation support.
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod


class ProgressTerminology:
    """
    Engine-specific terminology for progress messages.
    
    Provides consistent terminology based on the correlation engine type.
    """
    
    TIME_WINDOW = {
        "unit": "windows",
        "unit_singular": "window",
        "processing_verb": "scanning",
        "item_description": "time window",
        "progress_format": "{processed}/{total} windows processed",
        "rate_format": "{rate:.1f} windows/sec",
        "current_item_format": "Processing window {start} - {end}",
        "completion_format": "Scanned {total} windows, found {matches} matches"
    }
    
    IDENTITY_BASED = {
        "unit": "identities",
        "unit_singular": "identity",
        "processing_verb": "correlating",
        "item_description": "identity",
        "progress_format": "{processed}/{total} identities processed",
        "rate_format": "{rate:.1f} identities/sec",
        "current_item_format": "Processing identity: {value}",
        "completion_format": "Correlated {total} identities, found {matches} matches"
    }
    
    @classmethod
    def get_terminology(cls, engine_type: str) -> Dict[str, str]:
        """
        Get terminology dictionary for the specified engine type.
        
        Args:
            engine_type: Either "time_window", "time_based", "time_window_scanning", or "identity_based"
            
        Returns:
            Dictionary with terminology strings
        """
        if engine_type in ("identity_based",):
            return cls.IDENTITY_BASED
        else:
            # Default to time window for any unrecognized type
            return cls.TIME_WINDOW


class ProgressEventType(Enum):
    """Types of progress events that can be emitted"""
    SCANNING_START = "scanning_start"
    WINDOW_START = "window_start"
    WINDOW_COMPLETE = "window_complete"
    WINDOW_PROGRESS = "window_progress"
    BATCH_COMPLETE = "batch_complete"
    STREAMING_ENABLED = "streaming_enabled"
    MEMORY_WARNING = "memory_warning"
    CANCELLATION_REQUESTED = "cancellation_requested"
    SCANNING_COMPLETE = "scanning_complete"
    ERROR_OCCURRED = "error_occurred"
    # New database operation events
    DATABASE_QUERY_START = "database_query_start"
    DATABASE_QUERY_PROGRESS = "database_query_progress"
    DATABASE_QUERY_COMPLETE = "database_query_complete"


@dataclass
class WindowProgressData:
    """Progress data for individual window processing"""
    window_id: str
    window_start_time: datetime
    window_end_time: datetime
    records_found: int
    matches_created: int
    processing_time_seconds: float
    feathers_with_records: List[str] = field(default_factory=list)
    memory_usage_mb: Optional[float] = None


@dataclass
class OverallProgressData:
    """Overall progress data for the entire scanning operation"""
    windows_processed: int
    total_windows: int
    matches_found: int
    current_window_time: Optional[datetime] = None
    estimated_completion_time: Optional[datetime] = None
    time_remaining_seconds: Optional[float] = None
    processing_rate_windows_per_second: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    streaming_mode: bool = False
    processing_mode: str = "sequential"  # "sequential" or "parallel"
    # Enhanced window statistics
    windows_with_data: int = 0
    empty_windows_skipped: int = 0
    skip_rate_percentage: float = 0.0
    time_saved_by_skipping_seconds: float = 0.0
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage"""
        if self.total_windows == 0:
            return 100.0
        return (self.windows_processed / self.total_windows) * 100.0


@dataclass
class ProgressEvent:
    """A progress event emitted during correlation processing"""
    event_type: ProgressEventType
    timestamp: datetime
    overall_progress: OverallProgressData
    window_progress: Optional[WindowProgressData] = None
    message: Optional[str] = None
    error_details: Optional[str] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)


class ProgressListener(ABC):
    """Abstract base class for progress listeners"""
    
    @abstractmethod
    def on_progress_event(self, event: ProgressEvent):
        """
        Handle a progress event.
        
        Args:
            event: ProgressEvent containing progress information
        """
        pass


class ConsoleProgressListener(ProgressListener):
    """Simple console-based progress listener for debugging"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.last_percentage = -1
    
    def on_progress_event(self, event: ProgressEvent):
        """Print progress to console with enhanced statistics"""
        progress = event.overall_progress
        
        # Only print percentage updates for major milestones
        current_percentage = int(progress.completion_percentage)
        
        if event.event_type == ProgressEventType.SCANNING_START:
            print(f"[Progress] Starting time-window scanning: {progress.total_windows} windows")
        
        elif event.event_type == ProgressEventType.WINDOW_PROGRESS:
            if current_percentage != self.last_percentage and current_percentage % 10 == 0:
                # Build progress message with enhanced statistics
                msg_parts = [
                    f"[Progress] {current_percentage}% complete",
                    f"({progress.windows_processed}/{progress.total_windows} windows",
                    f"{progress.matches_found} matches)"
                ]
                
                # Add empty window statistics if significant
                if progress.empty_windows_skipped > 0:
                    msg_parts.append(
                        f"| Skipped: {progress.empty_windows_skipped} empty ({progress.skip_rate_percentage:.1f}%)"
                    )
                
                # Add time saved if significant
                if progress.time_saved_by_skipping_seconds > 1.0:
                    msg_parts.append(f"| Time saved: ~{progress.time_saved_by_skipping_seconds:.1f}s")
                
                # Add time remaining estimate
                if progress.time_remaining_seconds:
                    remaining = timedelta(seconds=progress.time_remaining_seconds)
                    msg_parts.append(f"| ETA: {remaining}")
                
                # Add processing rate
                if progress.processing_rate_windows_per_second:
                    msg_parts.append(f"| Rate: {progress.processing_rate_windows_per_second:.1f} win/s")
                
                print(" ".join(msg_parts))
                self.last_percentage = current_percentage
        
        elif event.event_type == ProgressEventType.STREAMING_ENABLED:
            print(f"[Progress] Streaming mode enabled: {event.message}")
        
        elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
            # Enhanced completion message with statistics
            msg_parts = [
                f"[Progress] Scanning complete: {progress.matches_found} matches found",
                f"in {progress.windows_processed} windows"
            ]
            
            if progress.empty_windows_skipped > 0:
                msg_parts.append(
                    f"(skipped {progress.empty_windows_skipped} empty windows, "
                    f"saved ~{progress.time_saved_by_skipping_seconds:.1f}s)"
                )
            
            print(" ".join(msg_parts))
        
        elif event.event_type == ProgressEventType.ERROR_OCCURRED:
            print(f"[Progress] Error: {event.message}")
        
        # Verbose mode: print all events
        if self.verbose:
            if event.window_progress:
                wp = event.window_progress
                print(f"[Progress] Window {wp.window_id}: {wp.records_found} records, "
                      f"{wp.matches_created} matches, {wp.processing_time_seconds:.3f}s")


class TimeEstimator:
    """Estimates completion time based on processing history"""
    
    def __init__(self, window_size: int = 50):
        """
        Initialize time estimator.
        
        Args:
            window_size: Number of recent measurements to use for estimation
        """
        self.window_size = window_size
        self.processing_times: List[float] = []
        self.start_time: Optional[datetime] = None
        self.last_update_time: Optional[datetime] = None
    
    def start_estimation(self):
        """Start time estimation tracking"""
        self.start_time = datetime.now()
        self.last_update_time = self.start_time
        self.processing_times.clear()
    
    def record_window_processing(self, processing_time_seconds: float):
        """
        Record processing time for a window.
        
        Args:
            processing_time_seconds: Time taken to process the window
        """
        self.processing_times.append(processing_time_seconds)
        
        # Keep only recent measurements
        if len(self.processing_times) > self.window_size:
            self.processing_times.pop(0)
        
        self.last_update_time = datetime.now()
    
    def estimate_completion_time(self, windows_processed: int, total_windows: int) -> Optional[datetime]:
        """
        Estimate completion time based on current progress.
        
        Uses actual elapsed time divided by windows processed to get a more accurate
        estimate that accounts for both empty and non-empty windows.
        
        Args:
            windows_processed: Number of windows already processed
            total_windows: Total number of windows to process
            
        Returns:
            Estimated completion datetime or None if insufficient data
        """
        if windows_processed == 0 or windows_processed >= total_windows:
            return None
        
        if not self.start_time:
            return None
        
        # Calculate actual elapsed time
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        
        # Calculate average time per window (including empty windows)
        avg_time_per_window = elapsed_seconds / windows_processed
        
        # Estimate remaining time
        remaining_windows = total_windows - windows_processed
        estimated_remaining_seconds = remaining_windows * avg_time_per_window
        
        # Add current time
        return datetime.now() + timedelta(seconds=estimated_remaining_seconds)
    
    def get_processing_rate(self) -> Optional[float]:
        """
        Get current processing rate in windows per second.
        
        Uses actual elapsed time to calculate rate, accounting for both
        empty and non-empty windows.
        
        Returns:
            Processing rate or None if insufficient data
        """
        if not self.start_time or not self.last_update_time:
            return None
        
        # Calculate elapsed time
        elapsed_seconds = (self.last_update_time - self.start_time).total_seconds()
        
        if elapsed_seconds <= 0:
            return None
        
        # Use the number of processing times recorded as a proxy for windows processed
        # This gives us the rate of actual window processing
        windows_count = len(self.processing_times)
        
        if windows_count > 0:
            return windows_count / elapsed_seconds
        
        return None
    
    def get_time_remaining(self, windows_processed: int, total_windows: int) -> Optional[float]:
        """
        Get estimated time remaining in seconds.
        
        Uses actual elapsed time to provide accurate estimates that account for
        both empty and non-empty windows.
        
        Args:
            windows_processed: Number of windows already processed
            total_windows: Total number of windows to process
            
        Returns:
            Estimated remaining seconds or None if insufficient data
        """
        if windows_processed == 0 or windows_processed >= total_windows:
            return None
        
        if not self.start_time:
            return None
        
        # Calculate actual elapsed time
        elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
        
        # Calculate average time per window (including empty windows)
        avg_time_per_window = elapsed_seconds / windows_processed
        
        # Estimate remaining time
        remaining_windows = total_windows - windows_processed
        estimated_remaining_seconds = remaining_windows * avg_time_per_window
        
        return max(0, estimated_remaining_seconds)


class CancellationToken:
    """Thread-safe cancellation token for graceful shutdown"""
    
    def __init__(self):
        self._cancelled = False
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[], None]] = []
    
    def request_cancellation(self):
        """Request cancellation of the operation"""
        with self._lock:
            if not self._cancelled:
                self._cancelled = True
                # Execute all registered callbacks
                for callback in self._callbacks:
                    try:
                        callback()
                    except Exception as e:
                        print(f"[Cancellation] Error in callback: {e}")
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        with self._lock:
            return self._cancelled
    
    def register_callback(self, callback: Callable[[], None]):
        """
        Register a callback to be called when cancellation is requested.
        
        Args:
            callback: Function to call on cancellation
        """
        with self._lock:
            self._callbacks.append(callback)
    
    def check_cancellation(self):
        """
        Check for cancellation and raise exception if cancelled.
        
        Raises:
            OperationCancelledException: If operation was cancelled
        """
        if self.is_cancelled():
            raise OperationCancelledException("Operation was cancelled")


class OperationCancelledException(Exception):
    """Exception raised when an operation is cancelled"""
    pass


class ProgressTracker:
    """
    Main progress tracking coordinator for correlation engines.
    
    Manages progress events, time estimation, and cancellation support.
    Supports both time-window scanning and identity-based engines.
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize progress tracker.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.listeners: List[ProgressListener] = []
        self.time_estimator = TimeEstimator()
        self.cancellation_token = CancellationToken()
        
        # Engine type and terminology
        self.engine_type = "time_window"
        self._terminology = ProgressTerminology.TIME_WINDOW
        
        # Progress state
        self.total_windows = 0
        self.windows_processed = 0
        self.matches_found = 0
        self.current_window_time: Optional[datetime] = None
        self.streaming_mode = False
        self.processing_mode = "sequential"
        self.memory_usage_mb: Optional[float] = None
        
        # Enhanced window statistics
        self.windows_with_data = 0
        self.empty_windows_skipped = 0
        self.skip_rate_percentage = 0.0
        self.time_saved_by_skipping_seconds = 0.0
        
        # Timing
        self.operation_start_time: Optional[datetime] = None
        self.last_window_start_time: Optional[datetime] = None
        
        # Track actual processing rate (windows per second including empty windows)
        self._actual_windows_processed_for_rate = 0
        
        # Add console listener in debug mode - DISABLED to reduce console output
        # if debug_mode:
        #     self.add_listener(ConsoleProgressListener(verbose=False))
    
    def set_engine_type(self, engine_type: str):
        """
        Set the engine type and update terminology.
        
        Args:
            engine_type: Either "time_window", "time_based", "time_window_scanning", or "identity_based"
        """
        self.engine_type = engine_type
        self._terminology = ProgressTerminology.get_terminology(engine_type)
    
    def get_progress_unit(self) -> str:
        """
        Get the progress unit name based on engine type.
        
        Returns:
            "windows" for time-window engine, "identities" for identity-based engine
        """
        return self._terminology["unit"]
    
    def format_progress_message(self, processed: int, total: int, matches: int = 0, 
                               rate: Optional[float] = None) -> str:
        """
        Format a progress message using engine-specific terminology.
        
        Args:
            processed: Number of items processed
            total: Total number of items
            matches: Number of matches found
            rate: Processing rate (items per second)
            
        Returns:
            Formatted progress message
        """
        message = self._terminology["progress_format"].format(
            processed=processed, 
            total=total
        )
        
        if matches > 0:
            message += f", {matches} matches found"
        
        if rate is not None and rate > 0:
            rate_str = self._terminology["rate_format"].format(rate=rate)
            message += f" ({rate_str})"
        
        return message
    
    def add_listener(self, listener: ProgressListener):
        """
        Add a progress listener.
        
        Args:
            listener: ProgressListener to receive events
        """
        self.listeners.append(listener)
    
    def remove_listener(self, listener: ProgressListener):
        """
        Remove a progress listener.
        
        Args:
            listener: ProgressListener to remove
        """
        if listener in self.listeners:
            self.listeners.remove(listener)
    
    def start_scanning(self, total_windows: int, window_size_minutes: int, 
                      time_range_start: datetime, time_range_end: datetime,
                      parallel_processing: bool = False, max_workers: int = 1):
        """
        Start progress tracking for scanning operation.
        
        Args:
            total_windows: Total number of windows to process
            window_size_minutes: Size of each window in minutes
            time_range_start: Start of time range being scanned
            time_range_end: End of time range being scanned
            parallel_processing: Whether parallel processing is enabled
            max_workers: Number of worker threads (if parallel)
        """
        self.total_windows = total_windows
        self.windows_processed = 0
        self.matches_found = 0
        self.operation_start_time = datetime.now()
        self.processing_mode = "parallel" if parallel_processing else "sequential"
        
        # Start time estimation
        self.time_estimator.start_estimation()
        
        # Emit start event
        event = ProgressEvent(
            event_type=ProgressEventType.SCANNING_START,
            timestamp=self.operation_start_time,
            overall_progress=self._create_overall_progress(),
            message=f"Starting {self.processing_mode} scanning of {total_windows} windows",
            additional_data={
                'window_size_minutes': window_size_minutes,
                'time_range_start': time_range_start.isoformat(),
                'time_range_end': time_range_end.isoformat(),
                'parallel_processing': parallel_processing,
                'max_workers': max_workers
            }
        )
        self._emit_event(event)
    
    def start_window(self, window_id: str, window_start_time: datetime, window_end_time: datetime):
        """
        Record the start of window processing.
        
        Args:
            window_id: Unique identifier for the window
            window_start_time: Start time of the window
            window_end_time: End time of the window
        """
        self.current_window_time = window_start_time
        self.last_window_start_time = datetime.now()
        
        # Check for cancellation
        self.cancellation_token.check_cancellation()
        
        # Emit window start event (only in verbose mode)
        if self.debug_mode:
            event = ProgressEvent(
                event_type=ProgressEventType.WINDOW_START,
                timestamp=datetime.now(),
                overall_progress=self._create_overall_progress(),
                window_progress=WindowProgressData(
                    window_id=window_id,
                    window_start_time=window_start_time,
                    window_end_time=window_end_time,
                    records_found=0,
                    matches_created=0,
                    processing_time_seconds=0.0
                )
            )
            self._emit_event(event)
    
    def complete_window(self, window_id: str, window_start_time: datetime, window_end_time: datetime,
                       records_found: int, matches_created: int, feathers_with_records: List[str],
                       memory_usage_mb: Optional[float] = None, is_empty_window: bool = False):
        """
        Record the completion of window processing.
        
        Args:
            window_id: Unique identifier for the window
            window_start_time: Start time of the window
            window_end_time: End time of the window
            records_found: Number of records found in the window
            matches_created: Number of matches created from the window
            feathers_with_records: List of feather IDs that had records
            memory_usage_mb: Current memory usage in MB
            is_empty_window: Whether this window was empty (skipped)
        """
        # Calculate processing time
        processing_time = 0.0
        if self.last_window_start_time:
            processing_time = (datetime.now() - self.last_window_start_time).total_seconds()
        
        # Update counters
        self.windows_processed += 1
        self.matches_found += matches_created
        self.memory_usage_mb = memory_usage_mb
        
        # Update empty window statistics
        if is_empty_window:
            self.empty_windows_skipped += 1
        else:
            self.windows_with_data += 1
        
        # Calculate efficiency metrics
        if self.windows_processed > 0:
            self.skip_rate_percentage = (self.empty_windows_skipped / self.windows_processed) * 100
        
        # Estimate time saved: assume each empty window would have taken 50ms if fully processed
        # vs <1ms with quick check
        estimated_full_processing_time_per_window = 0.050  # 50ms
        actual_quick_check_time_per_window = 0.001  # 1ms
        time_saved_per_empty_window = estimated_full_processing_time_per_window - actual_quick_check_time_per_window
        self.time_saved_by_skipping_seconds = self.empty_windows_skipped * time_saved_per_empty_window
        
        # Record processing time for estimation (only for non-empty windows for accurate estimates)
        if not is_empty_window:
            self.time_estimator.record_window_processing(processing_time)
        
        # Create window progress data
        window_progress = WindowProgressData(
            window_id=window_id,
            window_start_time=window_start_time,
            window_end_time=window_end_time,
            records_found=records_found,
            matches_created=matches_created,
            processing_time_seconds=processing_time,
            feathers_with_records=feathers_with_records,
            memory_usage_mb=memory_usage_mb
        )
        
        # Emit completion event
        event = ProgressEvent(
            event_type=ProgressEventType.WINDOW_COMPLETE,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            window_progress=window_progress
        )
        self._emit_event(event)
        
        # Emit progress update on every window completion
        # The terminal logger handles throttling to prevent flooding
        self._emit_progress_update()
    
    def report_batch_complete(self, batch_size: int, batch_matches: int, 
                            additional_data: Optional[Dict[str, Any]] = None):
        """
        Report completion of a batch of windows (for parallel processing).
        
        Args:
            batch_size: Number of windows in the batch
            batch_matches: Number of matches found in the batch
            additional_data: Additional batch-specific data
        """
        event = ProgressEvent(
            event_type=ProgressEventType.BATCH_COMPLETE,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=f"Batch complete: {batch_size} windows, {batch_matches} matches",
            additional_data=additional_data or {}
        )
        self._emit_event(event)
    
    def report_streaming_enabled(self, reason: str, database_path: str):
        """
        Report that streaming mode has been enabled.
        
        Args:
            reason: Reason why streaming was enabled
            database_path: Path to streaming database
        """
        self.streaming_mode = True
        
        event = ProgressEvent(
            event_type=ProgressEventType.STREAMING_ENABLED,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=f"Streaming enabled: {reason}",
            additional_data={
                'reason': reason,
                'database_path': database_path
            }
        )
        self._emit_event(event)
    
    def report_memory_warning(self, current_usage_mb: float, limit_mb: float, message: str):
        """
        Report a memory usage warning.
        
        Args:
            current_usage_mb: Current memory usage in MB
            limit_mb: Memory limit in MB
            message: Warning message
        """
        self.memory_usage_mb = current_usage_mb
        
        event = ProgressEvent(
            event_type=ProgressEventType.MEMORY_WARNING,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=message,
            additional_data={
                'current_usage_mb': current_usage_mb,
                'limit_mb': limit_mb,
                'usage_percentage': (current_usage_mb / limit_mb) * 100
            }
        )
        self._emit_event(event)
    
    def report_error(self, error_message: str, error_details: Optional[str] = None):
        """
        Report an error during processing.
        
        Args:
            error_message: Brief error description
            error_details: Detailed error information (e.g., stack trace)
        """
        event = ProgressEvent(
            event_type=ProgressEventType.ERROR_OCCURRED,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=error_message,
            error_details=error_details
        )
        self._emit_event(event)
    
    def complete_scanning(self):
        """Mark scanning as complete"""
        event = ProgressEvent(
            event_type=ProgressEventType.SCANNING_COMPLETE,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=f"Scanning complete: {self.matches_found} matches in {self.windows_processed} windows"
        )
        self._emit_event(event)
    
    def report_database_query_start(self, window_id: str, total_feathers: int):
        """
        Report the start of database querying for a window.
        
        Args:
            window_id: Unique identifier for the window
            total_feathers: Total number of feathers to query
        """
        event = ProgressEvent(
            event_type=ProgressEventType.DATABASE_QUERY_START,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=f"Querying {total_feathers} feathers for window {window_id}",
            additional_data={
                'window_id': window_id,
                'total_feathers': total_feathers,
                'feathers_queried': 0
            }
        )
        self._emit_event(event)
    
    def report_database_query_progress(self, window_id: str, feather_id: str, 
                                     feathers_queried: int, total_feathers: int, 
                                     records_found: int):
        """
        Report progress during database querying.
        
        Args:
            window_id: Unique identifier for the window
            feather_id: ID of the feather being queried
            feathers_queried: Number of feathers already queried
            total_feathers: Total number of feathers to query
            records_found: Number of records found in this feather
        """
        event = ProgressEvent(
            event_type=ProgressEventType.DATABASE_QUERY_PROGRESS,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=f"Querying {feather_id}: {records_found} records ({feathers_queried}/{total_feathers})",
            additional_data={
                'window_id': window_id,
                'feather_id': feather_id,
                'feathers_queried': feathers_queried,
                'total_feathers': total_feathers,
                'records_found': records_found
            }
        )
        self._emit_event(event)
    
    def report_database_query_complete(self, window_id: str, total_feathers: int, 
                                     total_records: int, query_time_seconds: float):
        """
        Report completion of database querying for a window.
        
        Args:
            window_id: Unique identifier for the window
            total_feathers: Total number of feathers queried
            total_records: Total number of records found
            query_time_seconds: Time taken for all queries
        """
        event = ProgressEvent(
            event_type=ProgressEventType.DATABASE_QUERY_COMPLETE,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message=f"Query complete: {total_records} records from {total_feathers} feathers ({query_time_seconds:.2f}s)",
            additional_data={
                'window_id': window_id,
                'total_feathers': total_feathers,
                'total_records': total_records,
                'query_time_seconds': query_time_seconds
            }
        )
        self._emit_event(event)
    
    def request_cancellation(self):
        """Request cancellation of the scanning operation"""
        self.cancellation_token.request_cancellation()
        
        event = ProgressEvent(
            event_type=ProgressEventType.CANCELLATION_REQUESTED,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress(),
            message="Cancellation requested"
        )
        self._emit_event(event)
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        return self.cancellation_token.is_cancelled()
    
    def check_cancellation(self):
        """Check for cancellation and raise exception if cancelled"""
        self.cancellation_token.check_cancellation()
    
    def register_cancellation_callback(self, callback: Callable[[], None]):
        """Register a callback for when cancellation is requested"""
        self.cancellation_token.register_callback(callback)
    
    def _create_overall_progress(self) -> OverallProgressData:
        """Create overall progress data snapshot with accurate time estimates"""
        # Calculate processing rate based on actual elapsed time
        processing_rate = None
        if self.operation_start_time and self.windows_processed > 0:
            elapsed_seconds = (datetime.now() - self.operation_start_time).total_seconds()
            if elapsed_seconds > 0:
                processing_rate = self.windows_processed / elapsed_seconds
        
        return OverallProgressData(
            windows_processed=self.windows_processed,
            total_windows=self.total_windows,
            matches_found=self.matches_found,
            current_window_time=self.current_window_time,
            estimated_completion_time=self.time_estimator.estimate_completion_time(
                self.windows_processed, self.total_windows
            ),
            time_remaining_seconds=self.time_estimator.get_time_remaining(
                self.windows_processed, self.total_windows
            ),
            processing_rate_windows_per_second=processing_rate,
            memory_usage_mb=self.memory_usage_mb,
            streaming_mode=self.streaming_mode,
            processing_mode=self.processing_mode,
            windows_with_data=self.windows_with_data,
            empty_windows_skipped=self.empty_windows_skipped,
            skip_rate_percentage=self.skip_rate_percentage,
            time_saved_by_skipping_seconds=self.time_saved_by_skipping_seconds
        )
    
    def _emit_progress_update(self):
        """Emit a general progress update event"""
        event = ProgressEvent(
            event_type=ProgressEventType.WINDOW_PROGRESS,
            timestamp=datetime.now(),
            overall_progress=self._create_overall_progress()
        )
        self._emit_event(event)
    
    def _emit_event(self, event: ProgressEvent):
        """
        Emit a progress event to all listeners.
        
        Args:
            event: ProgressEvent to emit
        """
        for listener in self.listeners:
            try:
                listener.on_progress_event(event)
            except Exception as e:
                if self.debug_mode:
                    # print(f"[Progress] Error in listener {type(listener).__name__}: {e}")
                    pass