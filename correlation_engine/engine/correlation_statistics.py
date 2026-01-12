"""
Correlation Statistics Module

Provides percentage analysis and statistics for correlation engines,
tracking how much has been correlated and how much remains.
Works for both Time-Window Scanning and Identity-Based engines.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum


class CorrelationPhase(Enum):
    """Phases of correlation processing"""
    NOT_STARTED = "not_started"
    INITIALIZING = "initializing"
    LOADING_DATA = "loading_data"
    CORRELATING = "correlating"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class CorrelationProgress:
    """
    Comprehensive correlation progress statistics.
    
    Tracks progress for both Time-Window and Identity-Based engines.
    """
    # Engine identification
    engine_type: str  # "time_window_scanning" or "identity_based"
    
    # Current phase
    current_phase: CorrelationPhase = CorrelationPhase.NOT_STARTED
    
    # Item tracking (windows or identities)
    total_items: int = 0  # Total windows or identities to process
    processed_items: int = 0  # Items processed so far
    remaining_items: int = 0  # Items remaining
    
    # Match tracking
    matches_found: int = 0
    
    # Time tracking
    start_time: Optional[datetime] = None
    current_time: Optional[datetime] = None
    estimated_completion_time: Optional[datetime] = None
    
    # Performance metrics
    processing_rate: float = 0.0  # Items per second
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float = 0.0
    
    # Memory and resource tracking
    memory_usage_mb: float = 0.0
    streaming_enabled: bool = False
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def completion_percentage(self) -> float:
        """
        Calculate completion percentage.
        
        Returns:
            Percentage complete (0.0 to 100.0)
        """
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100.0
    
    @property
    def remaining_percentage(self) -> float:
        """
        Calculate remaining percentage.
        
        Returns:
            Percentage remaining (0.0 to 100.0)
        """
        return 100.0 - self.completion_percentage
    
    @property
    def is_complete(self) -> bool:
        """Check if correlation is complete"""
        return self.current_phase == CorrelationPhase.COMPLETE
    
    @property
    def is_in_progress(self) -> bool:
        """Check if correlation is in progress"""
        return self.current_phase in (
            CorrelationPhase.INITIALIZING,
            CorrelationPhase.LOADING_DATA,
            CorrelationPhase.CORRELATING,
            CorrelationPhase.FINALIZING
        )
    
    @property
    def estimated_time_remaining(self) -> Optional[timedelta]:
        """Get estimated time remaining as timedelta"""
        if self.estimated_remaining_seconds > 0:
            return timedelta(seconds=self.estimated_remaining_seconds)
        return None
    
    @property
    def elapsed_time(self) -> Optional[timedelta]:
        """Get elapsed time as timedelta"""
        if self.elapsed_seconds > 0:
            return timedelta(seconds=self.elapsed_seconds)
        return None
    
    def update_from_progress_data(self, overall_progress: Any):
        """
        Update statistics from OverallProgressData.
        
        Args:
            overall_progress: OverallProgressData object from progress tracking
        """
        self.processed_items = overall_progress.windows_processed
        self.total_items = overall_progress.total_windows
        self.remaining_items = self.total_items - self.processed_items
        self.matches_found = overall_progress.matches_found
        
        if overall_progress.processing_rate_windows_per_second:
            self.processing_rate = overall_progress.processing_rate_windows_per_second
        
        if overall_progress.time_remaining_seconds:
            self.estimated_remaining_seconds = overall_progress.time_remaining_seconds
        
        if overall_progress.memory_usage_mb:
            self.memory_usage_mb = overall_progress.memory_usage_mb
        
        self.streaming_enabled = overall_progress.streaming_mode
        
        # Update phase based on progress
        if self.processed_items == 0:
            self.current_phase = CorrelationPhase.INITIALIZING
        elif self.processed_items < self.total_items:
            self.current_phase = CorrelationPhase.CORRELATING
        elif self.processed_items >= self.total_items:
            self.current_phase = CorrelationPhase.FINALIZING
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of progress statistics
        """
        return {
            'engine_type': self.engine_type,
            'current_phase': self.current_phase.value,
            'total_items': self.total_items,
            'processed_items': self.processed_items,
            'remaining_items': self.remaining_items,
            'completion_percentage': self.completion_percentage,
            'remaining_percentage': self.remaining_percentage,
            'matches_found': self.matches_found,
            'processing_rate': self.processing_rate,
            'elapsed_seconds': self.elapsed_seconds,
            'estimated_remaining_seconds': self.estimated_remaining_seconds,
            'memory_usage_mb': self.memory_usage_mb,
            'streaming_enabled': self.streaming_enabled,
            'is_complete': self.is_complete,
            'is_in_progress': self.is_in_progress,
            'metadata': self.metadata
        }
    
    def get_summary_text(self) -> str:
        """
        Get human-readable summary text.
        
        Returns:
            Formatted summary string
        """
        item_type = "identities" if self.engine_type == "identity_based" else "windows"
        
        lines = [
            f"Correlation Progress Summary ({self.engine_type})",
            f"{'=' * 60}",
            f"Phase: {self.current_phase.value}",
            f"Progress: {self.completion_percentage:.1f}% complete",
            f"Processed: {self.processed_items:,} / {self.total_items:,} {item_type}",
            f"Remaining: {self.remaining_items:,} {item_type} ({self.remaining_percentage:.1f}%)",
            f"Matches Found: {self.matches_found:,}",
        ]
        
        if self.processing_rate > 0:
            lines.append(f"Processing Rate: {self.processing_rate:.2f} {item_type}/sec")
        
        if self.elapsed_seconds > 0:
            elapsed = timedelta(seconds=self.elapsed_seconds)
            lines.append(f"Elapsed Time: {elapsed}")
        
        if self.estimated_remaining_seconds > 0:
            remaining = timedelta(seconds=self.estimated_remaining_seconds)
            lines.append(f"Estimated Time Remaining: {remaining}")
        
        if self.memory_usage_mb > 0:
            lines.append(f"Memory Usage: {self.memory_usage_mb:.1f} MB")
        
        if self.streaming_enabled:
            lines.append("Streaming Mode: Enabled")
        
        lines.append(f"{'=' * 60}")
        
        return '\n'.join(lines)


class CorrelationStatisticsTracker:
    """
    Tracks and provides correlation statistics for both engine types.
    
    This class integrates with the progress tracking system to provide
    real-time percentage analysis and statistics.
    """
    
    def __init__(self, engine_type: str):
        """
        Initialize statistics tracker.
        
        Args:
            engine_type: Type of correlation engine ("time_window_scanning" or "identity_based")
        """
        self.engine_type = engine_type
        self.progress = CorrelationProgress(engine_type=engine_type)
        self.history: List[CorrelationProgress] = []
        self.update_count = 0
    
    def update_progress(self, overall_progress: Any):
        """
        Update progress from OverallProgressData.
        
        Args:
            overall_progress: OverallProgressData object
        """
        self.progress.update_from_progress_data(overall_progress)
        self.progress.current_time = datetime.now()
        
        # Calculate elapsed time
        if self.progress.start_time:
            elapsed = (self.progress.current_time - self.progress.start_time).total_seconds()
            self.progress.elapsed_seconds = elapsed
        
        self.update_count += 1
        
        # Store snapshot in history (every 10 updates)
        if self.update_count % 10 == 0:
            from copy import deepcopy
            self.history.append(deepcopy(self.progress))
    
    def start_correlation(self, total_items: int):
        """
        Mark the start of correlation.
        
        Args:
            total_items: Total number of items (windows or identities) to process
        """
        self.progress.start_time = datetime.now()
        self.progress.current_time = datetime.now()
        self.progress.total_items = total_items
        self.progress.remaining_items = total_items
        self.progress.current_phase = CorrelationPhase.INITIALIZING
    
    def complete_correlation(self):
        """Mark correlation as complete"""
        self.progress.current_phase = CorrelationPhase.COMPLETE
        self.progress.current_time = datetime.now()
        
        # Final elapsed time calculation
        if self.progress.start_time:
            elapsed = (self.progress.current_time - self.progress.start_time).total_seconds()
            self.progress.elapsed_seconds = elapsed
    
    def fail_correlation(self, error_message: str):
        """
        Mark correlation as failed.
        
        Args:
            error_message: Error message describing the failure
        """
        self.progress.current_phase = CorrelationPhase.FAILED
        self.progress.metadata['error_message'] = error_message
    
    def get_current_progress(self) -> CorrelationProgress:
        """
        Get current progress statistics.
        
        Returns:
            Current CorrelationProgress object
        """
        return self.progress
    
    def get_progress_dict(self) -> Dict[str, Any]:
        """
        Get current progress as dictionary.
        
        Returns:
            Dictionary with progress statistics
        """
        return self.progress.to_dict()
    
    def get_summary(self) -> str:
        """
        Get human-readable summary.
        
        Returns:
            Formatted summary string
        """
        return self.progress.get_summary_text()
    
    def get_percentage_breakdown(self) -> Dict[str, float]:
        """
        Get detailed percentage breakdown.
        
        Returns:
            Dictionary with various percentage metrics
        """
        return {
            'completion_percentage': self.progress.completion_percentage,
            'remaining_percentage': self.progress.remaining_percentage,
            'match_rate_percentage': (
                (self.progress.matches_found / self.progress.processed_items * 100.0)
                if self.progress.processed_items > 0 else 0.0
            ),
            'processing_efficiency': (
                (self.progress.processing_rate / self.progress.total_items * 100.0)
                if self.progress.total_items > 0 else 0.0
            )
        }
    
    def get_history(self) -> List[CorrelationProgress]:
        """
        Get progress history snapshots.
        
        Returns:
            List of historical CorrelationProgress snapshots
        """
        return self.history
    
    def reset(self):
        """Reset all statistics"""
        self.progress = CorrelationProgress(engine_type=self.engine_type)
        self.history.clear()
        self.update_count = 0
