"""
Zoom Manager - Controls zoom levels and time scale calculations for the timeline.

This module provides the ZoomManager class which manages:
- Zoom level transitions (0-10 scale)
- Time unit calculations for axis labels
- Viewport time range calculations
- Aggregation threshold logic
"""

from datetime import timedelta


class ZoomManager:
    """
    Manages zoom levels and time scale calculations for the timeline.
    
    The ZoomManager provides a unified interface for controlling timeline zoom,
    calculating appropriate time units for axis labels, and determining when
    to switch between individual and aggregated event views.
    
    Zoom levels range from 0 (year view) to 10 (minute view), with each level
    corresponding to a specific time unit and interval.
    """
    
    # Zoom levels map to time units and their intervals in minutes
    ZOOM_LEVELS = {
        0: {'unit': 'year', 'interval_minutes': 365 * 24 * 60, 'label': 'Year'},
        1: {'unit': 'quarter', 'interval_minutes': 90 * 24 * 60, 'label': 'Quarter'},
        2: {'unit': 'month', 'interval_minutes': 30 * 24 * 60, 'label': 'Month'},
        3: {'unit': 'week', 'interval_minutes': 7 * 24 * 60, 'label': 'Week'},
        4: {'unit': 'day', 'interval_minutes': 24 * 60, 'label': 'Day'},
        5: {'unit': '12hour', 'interval_minutes': 12 * 60, 'label': '12 Hours'},
        6: {'unit': '6hour', 'interval_minutes': 6 * 60, 'label': '6 Hours'},
        7: {'unit': 'hour', 'interval_minutes': 60, 'label': 'Hour'},
        8: {'unit': '15min', 'interval_minutes': 15, 'label': '15 Minutes'},
        9: {'unit': '5min', 'interval_minutes': 5, 'label': '5 Minutes'},
        10: {'unit': 'minute', 'interval_minutes': 1, 'label': 'Minute'}
    }
    
    # Aggregation threshold: switch to aggregation when more than this many events are visible
    AGGREGATION_THRESHOLD = 1000
    
    # Clustering threshold: auto-disable clustering when zoomed in past this level
    # At zoom level 8 (15 minutes) and above, individual events are clearly visible
    CLUSTERING_THRESHOLD = 8
    
    # Minimum and maximum zoom levels
    MIN_ZOOM = 0
    MAX_ZOOM = 10
    
    def __init__(self, initial_zoom=2):
        """
        Initialize the ZoomManager.
        
        Args:
            initial_zoom (int): Initial zoom level (default: 2 = month view)
        
        Raises:
            ValueError: If initial_zoom is not between MIN_ZOOM and MAX_ZOOM
        """
        if not self.MIN_ZOOM <= initial_zoom <= self.MAX_ZOOM:
            raise ValueError(
                f"Initial zoom level must be between {self.MIN_ZOOM} and {self.MAX_ZOOM}, "
                f"got {initial_zoom}"
            )
        
        self._current_zoom = initial_zoom
        self._max_zoom_cap = self.MAX_ZOOM  # Default to absolute max
    
    @property
    def current_zoom(self):
        """
        Get the current zoom level.
        
        Returns:
            int: Current zoom level (0-10)
        """
        return self._current_zoom
    
    def zoom_in(self):
        """
        Increase zoom level (zoom in to show more detail).
        
        Returns:
            bool: True if zoom level changed, False if already at maximum
        """
        if self._current_zoom < self._max_zoom_cap:
            self._current_zoom += 1
            return True
        return False
    
    def zoom_out(self):
        """
        Decrease zoom level (zoom out to show broader view).
        
        Returns:
            bool: True if zoom level changed, False if already at minimum
        """
        if self._current_zoom > self.MIN_ZOOM:
            self._current_zoom -= 1
            return True
        return False
    
    def set_zoom_level(self, level):
        """
        Set zoom level directly.
        
        Args:
            level (int): Zoom level to set (0-10)
        
        Raises:
            ValueError: If level is not between MIN_ZOOM and MAX_ZOOM
        """
        if not self.MIN_ZOOM <= level <= self.MAX_ZOOM:
            raise ValueError(
                f"Zoom level must be between {self.MIN_ZOOM} and {self.MAX_ZOOM}, "
                f"got {level}"
            )
        
        self._current_zoom = level
    
    def set_max_zoom_cap(self, level):
        """
        Set a dynamic maximum zoom limit.
        
        Args:
            level (int): Maximum zoom level allowed (must be <= MAX_ZOOM)
        """
        if not self.MIN_ZOOM <= level <= self.MAX_ZOOM:
            raise ValueError(
                f"Max zoom cap must be between {self.MIN_ZOOM} and {self.MAX_ZOOM}, "
                f"got {level}"
            )
        
        self._max_zoom_cap = level
        
        # Adjust current zoom if it exceeds new cap
        if self._current_zoom > self._max_zoom_cap:
            self._current_zoom = self._max_zoom_cap
    
    def get_time_unit(self):
        """
        Get the time unit for the current zoom level.
        
        Returns:
            str: Time unit name (e.g., 'day', 'hour', 'minute')
        """
        return self.ZOOM_LEVELS[self._current_zoom]['unit']
    
    def get_interval_minutes(self):
        """
        Get the interval in minutes for the current zoom level.
        
        Returns:
            int: Interval in minutes
        """
        return self.ZOOM_LEVELS[self._current_zoom]['interval_minutes']
    
    def get_zoom_label(self):
        """
        Get a human-readable label for the current zoom level.
        
        Returns:
            str: Zoom level label (e.g., 'Day', 'Hour', 'Minute')
        """
        return self.ZOOM_LEVELS[self._current_zoom]['label']
    
    def get_zoom_info(self):
        """
        Get complete information about the current zoom level.
        
        Returns:
            dict: Dictionary with keys 'level', 'unit', 'interval_minutes', 'label'
        """
        return {
            'level': self._current_zoom,
            'unit': self.get_time_unit(),
            'interval_minutes': self.get_interval_minutes(),
            'label': self.get_zoom_label()
        }
    
    def should_aggregate(self, visible_event_count):
        """
        Determine if events should be aggregated at current zoom level.
        
        Aggregation is recommended when the number of visible events exceeds
        the threshold to maintain performance and visual clarity.
        
        Args:
            visible_event_count (int): Number of events visible in viewport
        
        Returns:
            bool: True if aggregation is recommended, False otherwise
        """
        return visible_event_count > self.AGGREGATION_THRESHOLD
    
    def should_cluster(self):
        """
        Determine if events should be clustered at current zoom level.
        
        Clustering is automatically disabled when zoomed in sufficiently
        (at or above CLUSTERING_THRESHOLD) to show individual events clearly.
        
        Returns:
            bool: True if clustering is recommended, False if zoomed in too far
        """
        return self._current_zoom < self.CLUSTERING_THRESHOLD
    
    def calculate_viewport_range(self, center_time, canvas_width_pixels):
        """
        Calculate the time range visible in the viewport based on zoom level.
        
        This method calculates how much time should be visible in the viewport
        based on the current zoom level and canvas width.
        
        Args:
            center_time (datetime): Center point of the viewport
            canvas_width_pixels (int): Width of the canvas in pixels
        
        Returns:
            tuple: (start_time, end_time) as datetime objects
        """
        # Calculate time span based on zoom level
        # At zoom level 10 (minute view), 1 pixel = 1 minute
        # At zoom level 0 (year view), 1 pixel = 1024 minutes
        
        # Scale factor: zoom 0 = 1/1024, zoom 10 = 1
        zoom_scale = 2 ** (self._current_zoom - 10)
        
        # Calculate total minutes visible
        total_minutes = canvas_width_pixels / zoom_scale
        
        # Calculate half-span on each side of center
        half_span = timedelta(minutes=total_minutes / 2)
        
        start_time = center_time - half_span
        end_time = center_time + half_span
        
        return (start_time, end_time)
    
    # Target pixels per interval for consistent visual density
    TARGET_PIXEL_SPACING = 150
    
    def get_scale_factor(self):
        """
        Get the scale factor for the current zoom level.
        
        The scale factor represents how many pixels correspond to one minute
        of time. This is used for rendering calculations.
        
        Returns:
            float: Scale factor (pixels per minute)
        """
        # Calculate scale to ensure consistent visual spacing between grid lines
        # Scale = pixels / minutes
        interval_minutes = self.get_interval_minutes()
        return self.TARGET_PIXEL_SPACING / interval_minutes
    
    def can_zoom_in(self):
        """
        Check if zooming in is possible.
        
        Returns:
            bool: True if can zoom in, False if at maximum zoom
        """
        return self._current_zoom < self._max_zoom_cap
    
    def can_zoom_out(self):
        """
        Check if zooming out is possible.
        
        Returns:
            bool: True if can zoom out, False if at minimum zoom
        """
        return self._current_zoom > self.MIN_ZOOM
    
    def get_recommended_marker_interval(self):
        """
        Get the recommended interval for time axis markers at current zoom.
        
        Returns:
            timedelta: Recommended interval between time markers
        """
        interval_minutes = self.get_interval_minutes()
        return timedelta(minutes=interval_minutes)
    
    def get_all_zoom_configs(self):
        """
        Get all zoom level configurations for pre-calculation purposes.
        
        This method returns the complete zoom level configuration dictionary,
        which is used by the marker cache system to pre-calculate markers
        for all zoom levels during initial load.
        
        Returns:
            dict: Dictionary mapping zoom levels (0-10) to their configurations
                  Each configuration contains: unit, interval_minutes, label
        """
        return self.ZOOM_LEVELS.copy()
    
    def __repr__(self):
        """
        String representation of ZoomManager.
        
        Returns:
            str: String representation
        """
        return (
            f"ZoomManager(level={self._current_zoom}, "
            f"unit='{self.get_time_unit()}', "
            f"label='{self.get_zoom_label()}')"
        )
