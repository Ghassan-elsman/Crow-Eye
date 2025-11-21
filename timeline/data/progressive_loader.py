"""
Progressive Data Loader
=======================

This module provides progressive loading functionality for timeline data.
It loads visible time ranges first, then loads additional data in the background
to enable smooth panning and scrolling without blocking the UI.

The ProgressiveLoader manages:
- Priority-based loading of time ranges
- Background loading with threading
- Cache management for loaded time ranges
- Loading state tracking and cancellation

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import logging
import threading
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta
from collections import OrderedDict
from PyQt5.QtCore import QObject, pyqtSignal, QThread

logger = logging.getLogger(__name__)


class TimeRange:
    """Represents a time range with start and end times."""
    
    def __init__(self, start: datetime, end: datetime):
        """
        Initialize time range.
        
        Args:
            start: Start time (inclusive)
            end: End time (inclusive)
        """
        self.start = start
        self.end = end
    
    def __eq__(self, other):
        """Check equality with another TimeRange."""
        if not isinstance(other, TimeRange):
            return False
        return self.start == other.start and self.end == other.end
    
    def __hash__(self):
        """Hash for use in dictionaries and sets."""
        return hash((self.start, self.end))
    
    def __repr__(self):
        """String representation."""
        return f"TimeRange({self.start} to {self.end})"
    
    def overlaps(self, other: 'TimeRange') -> bool:
        """Check if this range overlaps with another."""
        return self.start <= other.end and other.start <= self.end
    
    def contains(self, other: 'TimeRange') -> bool:
        """Check if this range fully contains another."""
        return self.start <= other.start and self.end >= other.end
    
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        return (self.end - self.start).total_seconds()


class LoadRequest:
    """Represents a data loading request with priority."""
    
    def __init__(self, time_range: TimeRange, priority: int = 0):
        """
        Initialize load request.
        
        Args:
            time_range: Time range to load
            priority: Priority level (higher = more important)
        """
        self.time_range = time_range
        self.priority = priority
        self.cancelled = False
    
    def __lt__(self, other):
        """Compare by priority for priority queue."""
        return self.priority > other.priority  # Higher priority first


class LoadWorker(QThread):
    """Worker thread for loading data in background."""
    
    # Signals
    data_loaded = pyqtSignal(object, list)  # (time_range, events)
    load_error = pyqtSignal(object, Exception)  # (time_range, error)
    
    def __init__(self, data_manager, time_range: TimeRange, artifact_types: List[str]):
        """
        Initialize load worker.
        
        Args:
            data_manager: TimelineDataManager instance
            time_range: Time range to load
            artifact_types: List of artifact types to query
        """
        super().__init__()
        self.data_manager = data_manager
        self.time_range = time_range
        self.artifact_types = artifact_types
        self._cancelled = False
    
    def run(self):
        """Execute data loading in background thread."""
        try:
            if self._cancelled:
                return
            
            logger.debug(f"Loading data for range: {self.time_range}")
            
            # Query data from data manager
            events = self.data_manager.query_time_range(
                start_time=self.time_range.start,
                end_time=self.time_range.end,
                artifact_types=self.artifact_types
            )
            
            if not self._cancelled:
                logger.debug(f"Loaded {len(events)} events for range: {self.time_range}")
                self.data_loaded.emit(self.time_range, events)
        
        except Exception as e:
            if not self._cancelled:
                logger.error(f"Error loading data for range {self.time_range}: {e}")
                self.load_error.emit(self.time_range, e)
        
        finally:
            # Clean up database connections for this thread
            if hasattr(self.data_manager, 'cleanup_thread_connections'):
                self.data_manager.cleanup_thread_connections()
    
    def cancel(self):
        """Cancel this load operation."""
        self._cancelled = True


class ProgressiveLoader(QObject):
    """
    Manages progressive loading of timeline data.
    
    Loads visible time ranges first, then loads adjacent ranges in background
    to enable smooth panning without delays.
    """
    
    # Signals
    data_loaded = pyqtSignal(object, list)  # (time_range, events)
    loading_started = pyqtSignal(object)  # (time_range)
    loading_finished = pyqtSignal(object)  # (time_range)
    cache_updated = pyqtSignal()  # Cache state changed
    
    def __init__(self, data_manager, max_cache_size: int = 50):
        """
        Initialize progressive loader.
        
        Args:
            data_manager: TimelineDataManager instance
            max_cache_size: Maximum number of time ranges to cache
        """
        super().__init__()
        self.data_manager = data_manager
        self.max_cache_size = max_cache_size
        
        # Cache: OrderedDict to maintain LRU order
        self._cache = OrderedDict()
        
        # Active load workers
        self._active_workers = {}
        
        # Lock for thread safety
        self._lock = threading.Lock()
        
        # Current artifact types filter
        self._artifact_types = None
        
        logger.info("ProgressiveLoader initialized")
    
    def set_artifact_types(self, artifact_types: List[str]):
        """
        Set artifact types filter for loading.
        
        Args:
            artifact_types: List of artifact types to load
        """
        self._artifact_types = artifact_types
        logger.debug(f"Artifact types set: {artifact_types}")
    
    def load_range(self, time_range: TimeRange, priority: int = 0, 
                   background: bool = False) -> Optional[List[Dict]]:
        """
        Load data for a time range.
        
        Args:
            time_range: Time range to load
            priority: Priority level (higher = more important)
            background: If True, load in background thread
        
        Returns:
            Optional[List[Dict]]: Cached events if available, None if loading in background
        """
        # Check cache first
        cached_events = self._get_from_cache(time_range)
        if cached_events is not None:
            logger.debug(f"Cache hit for range: {time_range}")
            return cached_events
        
        # Check if already loading
        if time_range in self._active_workers:
            logger.debug(f"Already loading range: {time_range}")
            return None
        
        # Load in background or foreground
        if background:
            self._load_background(time_range, priority)
            return None
        else:
            return self._load_foreground(time_range)
    
    def load_visible_range(self, time_range: TimeRange) -> List[Dict]:
        """
        Load visible time range with high priority (foreground).
        
        This is used for the initially visible viewport and should complete
        within 2 seconds.
        
        Args:
            time_range: Visible time range
        
        Returns:
            List[Dict]: Loaded events
        """
        logger.info(f"Loading visible range: {time_range}")
        return self.load_range(time_range, priority=100, background=False) or []
    
    def preload_adjacent_ranges(self, center_range: TimeRange, buffer_factor: float = 1.0):
        """
        Preload time ranges adjacent to the center range in background.
        
        This enables smooth panning by loading data before the user scrolls to it.
        
        Args:
            center_range: Currently visible time range
            buffer_factor: How much to preload (1.0 = same duration on each side)
        """
        duration = center_range.duration_seconds()
        buffer_seconds = duration * buffer_factor
        
        # Calculate adjacent ranges
        before_range = TimeRange(
            start=center_range.start - timedelta(seconds=buffer_seconds),
            end=center_range.start
        )
        
        after_range = TimeRange(
            start=center_range.end,
            end=center_range.end + timedelta(seconds=buffer_seconds)
        )
        
        # Load adjacent ranges in background with lower priority
        logger.debug(f"Preloading adjacent ranges: before={before_range}, after={after_range}")
        self.load_range(before_range, priority=50, background=True)
        self.load_range(after_range, priority=50, background=True)
    
    def _load_foreground(self, time_range: TimeRange) -> List[Dict]:
        """
        Load data in foreground (blocking).
        
        Args:
            time_range: Time range to load
        
        Returns:
            List[Dict]: Loaded events
        """
        try:
            self.loading_started.emit(time_range)
            
            logger.debug(f"Loading foreground: {time_range}")
            events = self.data_manager.query_time_range(
                start_time=time_range.start,
                end_time=time_range.end,
                artifact_types=self._artifact_types
            )
            
            # Add to cache
            self._add_to_cache(time_range, events)
            
            self.loading_finished.emit(time_range)
            self.data_loaded.emit(time_range, events)
            
            logger.info(f"Loaded {len(events)} events for range: {time_range}")
            return events
        
        except Exception as e:
            logger.error(f"Error loading foreground data: {e}")
            self.loading_finished.emit(time_range)
            raise
    
    def _load_background(self, time_range: TimeRange, priority: int):
        """
        Load data in background thread.
        
        Args:
            time_range: Time range to load
            priority: Priority level
        """
        with self._lock:
            # Create worker thread
            worker = LoadWorker(
                self.data_manager,
                time_range,
                self._artifact_types or []
            )
            
            # Connect signals
            worker.data_loaded.connect(self._on_background_loaded)
            worker.load_error.connect(self._on_background_error)
            worker.finished.connect(lambda: self._on_worker_finished(time_range))
            
            # Store worker
            self._active_workers[time_range] = worker
            
            # Start loading
            self.loading_started.emit(time_range)
            worker.start()
            
            logger.debug(f"Started background loading for range: {time_range}")
    
    def _on_background_loaded(self, time_range: TimeRange, events: List[Dict]):
        """
        Handle background loading completion.
        
        Args:
            time_range: Loaded time range
            events: Loaded events
        """
        # Add to cache
        self._add_to_cache(time_range, events)
        
        # Emit signals
        self.loading_finished.emit(time_range)
        self.data_loaded.emit(time_range, events)
        
        logger.info(f"Background loaded {len(events)} events for range: {time_range}")
    
    def _on_background_error(self, time_range: TimeRange, error: Exception):
        """
        Handle background loading error.
        
        Args:
            time_range: Time range that failed
            error: Exception that occurred
        """
        logger.error(f"Background loading failed for range {time_range}: {error}")
        self.loading_finished.emit(time_range)
    
    def _on_worker_finished(self, time_range: TimeRange):
        """
        Handle worker thread completion.
        
        Args:
            time_range: Time range that finished loading
        """
        with self._lock:
            if time_range in self._active_workers:
                del self._active_workers[time_range]
    
    def _get_from_cache(self, time_range: TimeRange) -> Optional[List[Dict]]:
        """
        Get events from cache if available.
        
        Args:
            time_range: Time range to retrieve
        
        Returns:
            Optional[List[Dict]]: Cached events or None
        """
        with self._lock:
            if time_range in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(time_range)
                return self._cache[time_range]
            
            # Check if any cached range contains this range
            for cached_range, cached_events in self._cache.items():
                if cached_range.contains(time_range):
                    # Filter events to requested range
                    filtered_events = [
                        e for e in cached_events
                        if time_range.start <= e['timestamp'] <= time_range.end
                    ]
                    logger.debug(f"Filtered {len(filtered_events)} events from cached range")
                    return filtered_events
            
            return None
    
    def _add_to_cache(self, time_range: TimeRange, events: List[Dict]):
        """
        Add events to cache.
        
        Args:
            time_range: Time range
            events: Events to cache
        """
        with self._lock:
            # Add to cache
            self._cache[time_range] = events
            
            # Enforce cache size limit (LRU eviction)
            while len(self._cache) > self.max_cache_size:
                # Remove oldest (first) item
                oldest_range = next(iter(self._cache))
                del self._cache[oldest_range]
                logger.debug(f"Evicted from cache: {oldest_range}")
            
            self.cache_updated.emit()
            logger.debug(f"Added to cache: {time_range} ({len(events)} events)")
    
    def clear_cache(self):
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
            self.cache_updated.emit()
            logger.info("Cache cleared")
    
    def cancel_all_loads(self):
        """Cancel all active background loads."""
        with self._lock:
            for worker in self._active_workers.values():
                worker.cancel()
            
            # Wait for workers to finish
            for worker in self._active_workers.values():
                worker.wait(1000)  # Wait up to 1 second
            
            self._active_workers.clear()
            logger.info("All background loads cancelled")
    
    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.
        
        Returns:
            Dict: Cache statistics
        """
        with self._lock:
            total_events = sum(len(events) for events in self._cache.values())
            
            return {
                'cached_ranges': len(self._cache),
                'total_cached_events': total_events,
                'max_cache_size': self.max_cache_size,
                'active_loads': len(self._active_workers)
            }
    
    def is_loading(self, time_range: TimeRange) -> bool:
        """
        Check if a time range is currently being loaded.
        
        Args:
            time_range: Time range to check
        
        Returns:
            bool: True if loading
        """
        with self._lock:
            return time_range in self._active_workers
    
    def get_loading_ranges(self) -> List[TimeRange]:
        """
        Get list of time ranges currently being loaded.
        
        Returns:
            List[TimeRange]: Loading ranges
        """
        with self._lock:
            return list(self._active_workers.keys())
