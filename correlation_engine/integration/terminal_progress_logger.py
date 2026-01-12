"""
Terminal Progress Logger

This module provides comprehensive progress logging to terminal display
with detailed information, final statistics, and error logging with timestamps.
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, TextIO
from dataclasses import dataclass

from ..engine.progress_tracking import (
    ProgressListener, ProgressEvent, ProgressEventType,
    OverallProgressData, WindowProgressData
)

logger = logging.getLogger(__name__)


@dataclass
class TerminalDisplayConfig:
    """Configuration for terminal progress display"""
    show_detailed_progress: bool = True
    show_memory_info: bool = True
    show_timing_info: bool = True
    show_semantic_stats: bool = True
    show_scoring_stats: bool = True
    progress_update_interval: int = 10  # Show progress every N%
    verbose_window_logging: bool = False
    output_stream: TextIO = sys.stdout
    use_dynamic_line: bool = True  # Use carriage return for dynamic updates
    min_update_interval_seconds: float = 1.0  # Minimum time between updates (throttling)


class TerminalProgressLogger(ProgressListener):
    """
    Comprehensive terminal progress logger that provides detailed progress
    information logging to terminal display with timestamps and statistics.
    
    This logger handles:
    - Detailed progress information logging
    - Final statistics display for correlation completion
    - Error logging with timestamps for correlation failures
    - Engine-specific progress formatting
    - Memory usage and performance metrics
    """
    
    def __init__(self, config: Optional[TerminalDisplayConfig] = None):
        """
        Initialize terminal progress logger.
        
        Args:
            config: Terminal display configuration
        """
        self.config = config or TerminalDisplayConfig()
        self.output = self.config.output_stream
        
        # Progress tracking state
        self.start_time: Optional[datetime] = None
        self.last_percentage_reported = -1
        self.engine_type: Optional[str] = None
        self.total_windows = 0
        self.total_matches = 0
        
        # Statistics tracking
        self.semantic_stats: Dict[str, Any] = {}
        self.scoring_stats: Dict[str, Any] = {}
        self.error_count = 0
        self.warning_count = 0
        
        # Performance metrics
        self.processing_times: List[float] = []
        self.memory_usage_history: List[float] = []
        
        # Throttling state
        self._last_update_time: Optional[datetime] = None
        self._last_dynamic_message: str = ""
        
        logger.info("TerminalProgressLogger initialized")
    
    def set_engine_context(self, engine_type: str, total_windows: int = 0):
        """
        Set engine context for progress formatting.
        
        Args:
            engine_type: Type of engine ("identity_based" or "time_window")
            total_windows: Total number of windows/identities to process
        """
        self.engine_type = engine_type
        self.total_windows = total_windows
        
        # Log engine context
        engine_name = "Identity-Based" if engine_type == "identity_based" else "Time Engine"
        item_type = "identities" if engine_type == "identity_based" else "windows"
        
        self._log_with_timestamp(f"Engine Context: {engine_name} Engine")
        self._log_with_timestamp(f"Total {item_type} to process: {total_windows}")
    
    def update_semantic_stats(self, stats: Dict[str, Any]):
        """Update semantic mapping statistics"""
        self.semantic_stats.update(stats)
    
    def update_scoring_stats(self, stats: Dict[str, Any]):
        """Update scoring statistics"""
        self.scoring_stats.update(stats)
    
    def on_progress_event(self, event: ProgressEvent):
        """
        Handle progress event with comprehensive terminal logging.
        
        Args:
            event: ProgressEvent from the correlation engine
        """
        try:
            if event.event_type == ProgressEventType.SCANNING_START:
                self._handle_scanning_start(event)
            
            elif event.event_type == ProgressEventType.WINDOW_START:
                self._handle_window_start(event)
            
            elif event.event_type == ProgressEventType.WINDOW_COMPLETE:
                self._handle_window_complete(event)
            
            elif event.event_type == ProgressEventType.WINDOW_PROGRESS:
                self._handle_window_progress(event)
            
            elif event.event_type == ProgressEventType.STREAMING_ENABLED:
                self._handle_streaming_enabled(event)
            
            elif event.event_type == ProgressEventType.MEMORY_WARNING:
                self._handle_memory_warning(event)
            
            elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
                self._handle_scanning_complete(event)
            
            elif event.event_type == ProgressEventType.ERROR_OCCURRED:
                self._handle_error_occurred(event)
            
            elif event.event_type == ProgressEventType.CANCELLATION_REQUESTED:
                self._handle_cancellation_requested(event)
            
            else:
                # Generic event handling
                self._log_with_timestamp(f"Progress Event: {event.event_type.value} - {event.message or 'Processing...'}")
                
        except Exception as e:
            logger.error(f"Error in terminal progress logging: {e}")
            self._log_with_timestamp(f"ERROR: Terminal logging failed - {e}")
    
    def _handle_scanning_start(self, event: ProgressEvent):
        """Handle scanning start event"""
        self.start_time = event.timestamp
        progress = event.overall_progress
        
        engine_name = "Identity-Based" if self.engine_type == "identity_based" else "Time Engine"
        item_type = "identities" if self.engine_type == "identity_based" else "windows"
        
        self._log_separator()
        self._log_with_timestamp(f"STARTING {engine_name.upper()} CORRELATION")
        self._log_separator()
        
        self._log_with_timestamp(f"Configuration:")
        self._log_with_timestamp(f"  Engine Type: {engine_name}")
        self._log_with_timestamp(f"  Total {item_type}: {progress.total_windows}")
        self._log_with_timestamp(f"  Processing Mode: {progress.processing_mode}")
        
        if progress.processing_mode == "parallel":
            # Extract parallel info from additional data
            additional_data = event.additional_data
            max_workers = additional_data.get('max_workers', 1)
            self._log_with_timestamp(f"  Parallel Workers: {max_workers}")
        
        # Log time range if available
        additional_data = event.additional_data
        if 'time_range_start' in additional_data and 'time_range_end' in additional_data:
            start_time = additional_data['time_range_start']
            end_time = additional_data['time_range_end']
            self._log_with_timestamp(f"  Time Range: {start_time} to {end_time}")
        
        if 'window_size_minutes' in additional_data:
            window_size = additional_data['window_size_minutes']
            self._log_with_timestamp(f"  Window Size: {window_size} minutes")
        
        self._log_with_timestamp("Starting correlation processing...")
    
    def _handle_window_start(self, event: ProgressEvent):
        """Handle window/identity start event"""
        if not self.config.verbose_window_logging:
            return
        
        progress = event.overall_progress
        window_progress = event.window_progress
        
        if window_progress:
            if self.engine_type == "identity_based":
                self._log_with_timestamp(f"Processing identity: {window_progress.window_id}")
            else:
                window_time = window_progress.window_start_time.strftime("%Y-%m-%d %H:%M:%S")
                self._log_with_timestamp(f"Processing window: {window_progress.window_id} (time: {window_time})")
    
    def _handle_window_complete(self, event: ProgressEvent):
        """Handle window/identity complete event"""
        progress = event.overall_progress
        window_progress = event.window_progress
        
        if window_progress and self.config.verbose_window_logging:
            processing_time = window_progress.processing_time_seconds
            records = window_progress.records_found
            matches = window_progress.matches_created
            
            if self.engine_type == "identity_based":
                self._log_with_timestamp(
                    f"Identity {window_progress.window_id} complete: "
                    f"{records} records, {matches} matches ({processing_time:.3f}s)"
                )
            else:
                self._log_with_timestamp(
                    f"Window {window_progress.window_id} complete: "
                    f"{records} records, {matches} matches ({processing_time:.3f}s)"
                )
            
            # Track performance metrics
            self.processing_times.append(processing_time)
            if window_progress.memory_usage_mb:
                self.memory_usage_history.append(window_progress.memory_usage_mb)
    
    def _handle_window_progress(self, event: ProgressEvent):
        """Handle window progress event"""
        # Apply throttling - skip if update is too frequent
        if self._should_throttle_update():
            return
        
        progress = event.overall_progress
        current_percentage = int(progress.completion_percentage)
        
        # Format progress message based on engine type
        item_type = "identities" if self.engine_type == "identity_based" else "windows"
        
        progress_msg = (f"Progress: {current_percentage}% "
                      f"({progress.windows_processed}/{progress.total_windows} {item_type})")
        
        # Add matches found
        progress_msg += f", {progress.matches_found} matches"
        
        # Add time estimation if available
        if progress.time_remaining_seconds and self.config.show_timing_info:
            remaining = timedelta(seconds=int(progress.time_remaining_seconds))
            progress_msg += f", ETA: {remaining}"
        
        # Add processing rate if available
        if progress.processing_rate_windows_per_second and self.config.show_timing_info:
            rate = progress.processing_rate_windows_per_second
            progress_msg += f", {rate:.1f}/sec"
        
        # Add memory info if available and configured
        if progress.memory_usage_mb and self.config.show_memory_info:
            progress_msg += f", Mem: {progress.memory_usage_mb:.0f}MB"
        
        # Use dynamic line update for progress
        self._log_with_timestamp(progress_msg, dynamic=True)
        
        # Only log integration stats at major milestones (every 25%)
        if current_percentage % 25 == 0 and current_percentage != self.last_percentage_reported:
            self.last_percentage_reported = current_percentage
            # Force a newline before stats
            if self._last_dynamic_message:
                self.output.write('\n')
                self._last_dynamic_message = ""
            self._log_integration_stats()
    
    def _handle_streaming_enabled(self, event: ProgressEvent):
        """Handle streaming enabled event"""
        self.warning_count += 1
        
        self._log_with_timestamp(f"STREAMING MODE ENABLED: {event.message}")
        
        additional_data = event.additional_data
        if 'database_path' in additional_data:
            db_path = additional_data['database_path']
            self._log_with_timestamp(f"  Streaming database: {db_path}")
        
        if 'reason' in additional_data:
            reason = additional_data['reason']
            self._log_with_timestamp(f"  Reason: {reason}")
    
    def _handle_memory_warning(self, event: ProgressEvent):
        """Handle memory warning event"""
        self.warning_count += 1
        
        additional_data = event.additional_data
        current_mb = additional_data.get('current_usage_mb', 0)
        limit_mb = additional_data.get('limit_mb', 0)
        usage_percent = additional_data.get('usage_percentage', 0)
        
        self._log_with_timestamp(f"MEMORY WARNING: {event.message}")
        self._log_with_timestamp(f"  Current usage: {current_mb:.1f}MB / {limit_mb:.1f}MB ({usage_percent:.1f}%)")
    
    def _handle_scanning_complete(self, event: ProgressEvent):
        """Handle scanning complete event with comprehensive final statistics"""
        # Ensure any dynamic line is closed
        if self._last_dynamic_message:
            self.output.write('\n')
            self._last_dynamic_message = ""
        
        progress = event.overall_progress
        
        self._log_separator()
        self._log_with_timestamp("CORRELATION COMPLETED")
        self._log_separator()
        
        # Calculate total execution time
        total_time = ""
        if self.start_time:
            elapsed = (event.timestamp - self.start_time).total_seconds()
            total_time = str(timedelta(seconds=int(elapsed)))
        
        # Basic completion statistics
        item_type = "identities" if self.engine_type == "identity_based" else "windows"
        engine_name = "Identity-Based" if self.engine_type == "identity_based" else "Time Engine"
        
        self._log_with_timestamp(f"Final Results:")
        self._log_with_timestamp(f"  Engine: {engine_name}")
        self._log_with_timestamp(f"  Total {item_type} processed: {progress.windows_processed}")
        self._log_with_timestamp(f"  Total matches found: {progress.matches_found}")
        self._log_with_timestamp(f"  Total execution time: {total_time}")
        
        # Processing performance statistics
        if self.processing_times:
            avg_time = sum(self.processing_times) / len(self.processing_times)
            min_time = min(self.processing_times)
            max_time = max(self.processing_times)
            
            self._log_with_timestamp(f"Performance Statistics:")
            self._log_with_timestamp(f"  Average processing time per {item_type[:-1]}: {avg_time:.3f}s")
            self._log_with_timestamp(f"  Fastest {item_type[:-1]}: {min_time:.3f}s")
            self._log_with_timestamp(f"  Slowest {item_type[:-1]}: {max_time:.3f}s")
            
            if progress.processing_rate_windows_per_second:
                self._log_with_timestamp(f"  Overall processing rate: {progress.processing_rate_windows_per_second:.2f} {item_type}/sec")
        
        # Memory usage statistics
        if self.memory_usage_history and self.config.show_memory_info:
            avg_memory = sum(self.memory_usage_history) / len(self.memory_usage_history)
            peak_memory = max(self.memory_usage_history)
            
            self._log_with_timestamp(f"Memory Usage Statistics:")
            self._log_with_timestamp(f"  Average memory usage: {avg_memory:.1f}MB")
            self._log_with_timestamp(f"  Peak memory usage: {peak_memory:.1f}MB")
            
            if progress.streaming_mode:
                self._log_with_timestamp(f"  Streaming mode was activated during processing")
        
        # Integration statistics (semantic mapping and scoring)
        self._log_final_integration_stats()
        
        # Error and warning summary
        if self.error_count > 0 or self.warning_count > 0:
            self._log_with_timestamp(f"Issues Summary:")
            if self.error_count > 0:
                self._log_with_timestamp(f"  Errors encountered: {self.error_count}")
            if self.warning_count > 0:
                self._log_with_timestamp(f"  Warnings issued: {self.warning_count}")
        else:
            self._log_with_timestamp("No errors or warnings encountered during processing")
        
        self._log_separator()
    
    def _handle_error_occurred(self, event: ProgressEvent):
        """Handle error occurred event with detailed error logging"""
        self.error_count += 1
        
        self._log_with_timestamp(f"ERROR: {event.message}")
        
        if event.error_details:
            # Log error details with proper formatting
            error_lines = event.error_details.split('\n')
            for line in error_lines:
                if line.strip():
                    self._log_with_timestamp(f"  {line}")
        
        # Log current progress context
        progress = event.overall_progress
        if progress:
            item_type = "identities" if self.engine_type == "identity_based" else "windows"
            self._log_with_timestamp(f"Error occurred at: {progress.windows_processed}/{progress.total_windows} {item_type} processed")
    
    def _handle_cancellation_requested(self, event: ProgressEvent):
        """Handle cancellation requested event"""
        self._log_with_timestamp("CANCELLATION REQUESTED - Stopping correlation...")
        
        progress = event.overall_progress
        if progress:
            item_type = "identities" if self.engine_type == "identity_based" else "windows"
            self._log_with_timestamp(f"Partial results: {progress.windows_processed}/{progress.total_windows} {item_type} processed")
            self._log_with_timestamp(f"Matches found before cancellation: {progress.matches_found}")
    
    def _log_integration_stats(self):
        """Log semantic mapping and scoring statistics"""
        if not (self.config.show_semantic_stats or self.config.show_scoring_stats):
            return
        
        if self.semantic_stats and self.config.show_semantic_stats:
            mappings_applied = self.semantic_stats.get('mappings_applied', 0)
            total_records = self.semantic_stats.get('total_records_processed', 0)
            
            if mappings_applied > 0:
                self._log_with_timestamp(f"Semantic Mapping: {mappings_applied} mappings applied to {total_records} records")
        
        if self.scoring_stats and self.config.show_scoring_stats:
            scores_calculated = self.scoring_stats.get('scores_calculated', 0)
            avg_score = self.scoring_stats.get('average_score', 0)
            
            if scores_calculated > 0:
                self._log_with_timestamp(f"Weighted Scoring: {scores_calculated} scores calculated, avg: {avg_score:.2f}")
    
    def _log_final_integration_stats(self):
        """Log final comprehensive integration statistics"""
        if self.semantic_stats and self.config.show_semantic_stats:
            self._log_with_timestamp("Semantic Mapping Statistics:")
            
            for key, value in self.semantic_stats.items():
                if isinstance(value, (int, float)):
                    self._log_with_timestamp(f"  {key.replace('_', ' ').title()}: {value}")
        
        if self.scoring_stats and self.config.show_scoring_stats:
            self._log_with_timestamp("Weighted Scoring Statistics:")
            
            for key, value in self.scoring_stats.items():
                if isinstance(value, (int, float)):
                    if isinstance(value, float):
                        self._log_with_timestamp(f"  {key.replace('_', ' ').title()}: {value:.2f}")
                    else:
                        self._log_with_timestamp(f"  {key.replace('_', ' ').title()}: {value}")
    
    def _log_with_timestamp(self, message: str, dynamic: bool = False):
        """
        Log message with timestamp to terminal.
        
        Args:
            message: Message to log
            dynamic: If True, use carriage return to update same line (for progress)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        
        if dynamic and self.config.use_dynamic_line:
            # Use carriage return to overwrite the same line
            # Pad with spaces to clear any previous longer message
            padded_message = formatted_message.ljust(100)
            self.output.write(f"\r{padded_message}")
            self.output.flush()
            self._last_dynamic_message = formatted_message
        else:
            # If we had a dynamic message, print newline first to preserve it
            if self._last_dynamic_message:
                self.output.write('\n')
                self._last_dynamic_message = ""
            
            # Write to output stream with newline
            self.output.write(formatted_message + '\n')
            self.output.flush()
        
        # Also log to logger for file logging
        logger.info(message)
    
    def _should_throttle_update(self) -> bool:
        """
        Check if update should be throttled based on time interval.
        
        Returns:
            True if update should be skipped (throttled)
        """
        now = datetime.now()
        
        if self._last_update_time is None:
            self._last_update_time = now
            return False
        
        elapsed = (now - self._last_update_time).total_seconds()
        
        if elapsed < self.config.min_update_interval_seconds:
            return True
        
        self._last_update_time = now
        return False
    
    def _log_separator(self):
        """Log a separator line"""
        self.output.write("=" * 80 + '\n')
        self.output.flush()
    
    def log_custom_message(self, message: str):
        """
        Log a custom message with timestamp.
        
        Args:
            message: Custom message to log
        """
        self._log_with_timestamp(message)
    
    def get_statistics_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics summary.
        
        Returns:
            Dictionary with all collected statistics
        """
        return {
            'engine_type': self.engine_type,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'total_windows': self.total_windows,
            'total_matches': self.total_matches,
            'error_count': self.error_count,
            'warning_count': self.warning_count,
            'semantic_stats': self.semantic_stats.copy(),
            'scoring_stats': self.scoring_stats.copy(),
            'performance_metrics': {
                'processing_times_count': len(self.processing_times),
                'average_processing_time': sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0,
                'memory_samples_count': len(self.memory_usage_history),
                'average_memory_usage': sum(self.memory_usage_history) / len(self.memory_usage_history) if self.memory_usage_history else 0,
                'peak_memory_usage': max(self.memory_usage_history) if self.memory_usage_history else 0
            }
        }