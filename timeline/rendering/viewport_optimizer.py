"""
Viewport Optimizer - Optimizes rendering performance for large timelines.

This module provides the ViewportOptimizer class which implements:
- Viewport culling (only render visible events)
- Level-of-detail rendering (simpler markers when zoomed out)
- Batch rendering operations
- Render caching
"""

from PyQt5.QtCore import QRectF
from datetime import datetime


class ViewportOptimizer:
    """
    Optimizes timeline rendering performance through viewport culling and LOD.
    
    This class manages which events should be rendered based on the visible
    viewport, implements level-of-detail rendering for zoomed-out views,
    and caches rendered items for better performance.
    """
    
    # Level-of-detail thresholds
    LOD_HIGH_DETAIL = 0  # Show full detail (< 1000 events visible)
    LOD_MEDIUM_DETAIL = 1  # Simplified markers (1000-5000 events visible)
    LOD_LOW_DETAIL = 2  # Minimal markers (> 5000 events visible)
    
    # Viewport buffer (percentage of viewport to render outside visible area)
    VIEWPORT_BUFFER = 0.2  # 20% buffer on each side
    
    # Cache management thresholds
    MAX_CACHE_SIZE = 5000  # Maximum number of items to keep in cache
    CACHE_CLEANUP_THRESHOLD = 6000  # Trigger cleanup when cache exceeds this
    
    def __init__(self):
        """Initialize the viewport optimizer."""
        self.cached_items = {}  # Cache of rendered items by event ID
        self.visible_event_ids = set()  # Currently visible event IDs
        self.current_lod = self.LOD_HIGH_DETAIL
        self.cache_hits = 0  # Track cache hit rate for performance monitoring
        self.cache_misses = 0  # Track cache miss rate
        self.items_removed_from_scene = 0  # Track memory optimization impact
        
    def get_visible_events(self, events, viewport_rect, scene_rect, start_time, end_time):
        """
        Filter events to only those visible in the viewport (with buffer).
        
        This implements viewport culling to avoid rendering off-screen events.
        
        Args:
            events (list): All events to potentially render
            viewport_rect (QRectF): Visible viewport rectangle in scene coordinates
            scene_rect (QRectF): Full scene rectangle
            start_time (datetime): Timeline start time
            end_time (datetime): Timeline end time
        
        Returns:
            list: Filtered list of events that should be rendered
        """
        if not events or not viewport_rect or not scene_rect:
            return []
        
        # Calculate viewport bounds with buffer
        buffer_width = viewport_rect.width() * self.VIEWPORT_BUFFER
        visible_left = max(0, viewport_rect.left() - buffer_width)
        visible_right = min(scene_rect.width(), viewport_rect.right() + buffer_width)
        
        # Calculate time range for visible area
        total_duration = (end_time - start_time).total_seconds()
        if total_duration == 0:
            return events
        
        visible_start_ratio = visible_left / scene_rect.width()
        visible_end_ratio = visible_right / scene_rect.width()
        
        visible_start_time = start_time + (end_time - start_time) * visible_start_ratio
        visible_end_time = start_time + (end_time - start_time) * visible_end_ratio
        
        # Filter events by timestamp
        visible_events = []
        for event in events:
            timestamp = event.get('timestamp')
            if timestamp and visible_start_time <= timestamp <= visible_end_time:
                visible_events.append(event)
        
        # Update visible event IDs
        self.visible_event_ids = {event.get('id') for event in visible_events if event.get('id')}
        
        return visible_events
    
    def calculate_lod(self, visible_event_count):
        """
        Calculate appropriate level-of-detail based on visible event count.
        
        Args:
            visible_event_count (int): Number of events visible in viewport
        
        Returns:
            int: LOD level (LOD_HIGH_DETAIL, LOD_MEDIUM_DETAIL, or LOD_LOW_DETAIL)
        """
        if visible_event_count < 1000:
            lod = self.LOD_HIGH_DETAIL
        elif visible_event_count < 5000:
            lod = self.LOD_MEDIUM_DETAIL
        else:
            lod = self.LOD_LOW_DETAIL
        
        self.current_lod = lod
        return lod
    
    def should_use_simplified_rendering(self):
        """
        Check if simplified rendering should be used.
        
        Returns:
            bool: True if simplified rendering should be used
        """
        return self.current_lod >= self.LOD_MEDIUM_DETAIL
    
    def get_marker_size_for_lod(self, base_size):
        """
        Get marker size adjusted for current LOD level.
        
        Args:
            base_size (float): Base marker size
        
        Returns:
            float: Adjusted marker size
        """
        if self.current_lod == self.LOD_HIGH_DETAIL:
            return base_size
        elif self.current_lod == self.LOD_MEDIUM_DETAIL:
            return base_size * 0.8  # 80% size for medium detail
        else:
            return base_size * 0.6  # 60% size for low detail
    
    def should_show_effects(self):
        """
        Check if visual effects (shadows, glows) should be shown.
        
        Returns:
            bool: True if effects should be shown
        """
        return self.current_lod == self.LOD_HIGH_DETAIL
    
    def cache_item(self, event_id, item):
        """
        Cache a rendered item for potential reuse.
        
        Args:
            event_id (str): Event identifier
            item: QGraphicsItem to cache
        """
        self.cached_items[event_id] = item
    
    def get_cached_item(self, event_id):
        """
        Retrieve a cached item if available.
        
        Args:
            event_id (str): Event identifier
        
        Returns:
            QGraphicsItem or None: Cached item if available
        """
        return self.cached_items.get(event_id)
    
    def clear_cache(self):
        """Clear the render cache and reset statistics."""
        self.cached_items.clear()
        self.visible_event_ids.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        self.items_removed_from_scene = 0
    
    def cleanup_cache_if_needed(self):
        """
        Clean up cache if it exceeds the threshold.
        
        Removes least recently used items to keep cache size manageable.
        This prevents unbounded memory growth while maintaining performance.
        
        Returns:
            int: Number of items removed from cache
        """
        if len(self.cached_items) <= self.CACHE_CLEANUP_THRESHOLD:
            return 0
        
        # Calculate how many items to remove
        items_to_remove = len(self.cached_items) - self.MAX_CACHE_SIZE
        
        if items_to_remove <= 0:
            return 0
        
        # Remove items that are not currently visible
        # These are the least likely to be needed soon
        non_visible_items = []
        for event_id in self.cached_items.keys():
            if event_id not in self.visible_event_ids:
                non_visible_items.append(event_id)
        
        # Remove oldest non-visible items
        removed_count = 0
        for event_id in non_visible_items[:items_to_remove]:
            self.cached_items.pop(event_id, None)
            removed_count += 1
        
        return removed_count
    
    def get_cache_stats(self):
        """
        Get cache performance statistics.
        
        Returns:
            dict: Dictionary containing cache statistics
        """
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'cache_size': len(self.cached_items),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate_percent': hit_rate,
            'items_removed_from_scene': self.items_removed_from_scene,
            'visible_items': len(self.visible_event_ids)
        }
    
    def record_cache_access(self, event_id, hit):
        """
        Record a cache access for statistics.
        
        Args:
            event_id (str): Event identifier
            hit (bool): True if cache hit, False if cache miss
        """
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
    
    def record_item_removed(self):
        """Record that an item was removed from the scene for memory optimization."""
        self.items_removed_from_scene += 1
    
    def is_event_visible(self, event_id):
        """
        Check if an event is currently visible.
        
        Args:
            event_id (str): Event identifier
        
        Returns:
            bool: True if event is visible
        """
        return event_id in self.visible_event_ids
    
    def batch_events_for_rendering(self, events, batch_size=100):
        """
        Split events into batches for progressive rendering.
        
        This allows rendering large numbers of events without blocking the UI.
        
        Args:
            events (list): Events to batch
            batch_size (int): Number of events per batch
        
        Returns:
            list: List of event batches
        """
        batches = []
        for i in range(0, len(events), batch_size):
            batches.append(events[i:i + batch_size])
        return batches
    
    def get_aggregation_threshold(self):
        """
        Get the threshold for event aggregation based on current LOD.
        
        Returns:
            int: Number of events at same timestamp before aggregation
        """
        if self.current_lod == self.LOD_HIGH_DETAIL:
            return 3  # Aggregate if more than 3 events
        elif self.current_lod == self.LOD_MEDIUM_DETAIL:
            return 2  # Aggregate if more than 2 events
        else:
            return 1  # Aggregate all events at same timestamp
