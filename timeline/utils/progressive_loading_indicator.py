"""
Progressive Loading Indicator
==============================

Visual indicator for progressive data loading in the timeline.
Shows subtle loading indicators for time ranges being fetched in the background.

Author: Crow Eye Timeline Feature
Version: 1.0
"""

from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsTextItem
from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QPen, QBrush, QFont
from typing import Dict, List
from datetime import datetime


class LoadingIndicator(QGraphicsRectItem):
    """Visual indicator for a loading time range."""
    
    def __init__(self, x: float, width: float, height: float):
        """
        Initialize loading indicator.
        
        Args:
            x: X position
            width: Width of the indicator
            height: Height of the indicator
        """
        super().__init__(0, 0, width, height)
        
        # Position
        self.setPos(x, 0)
        
        # Style - subtle semi-transparent overlay
        self.setPen(QPen(QColor(100, 200, 255, 100), 1))
        self.setBrush(QBrush(QColor(100, 200, 255, 30)))
        
        # Animation state
        self._opacity = 0.3
        self._opacity_direction = 1
        
        # Z-order - behind events but above background
        self.setZValue(-10)
    
    def animate_pulse(self):
        """Animate the loading indicator with a pulsing effect."""
        # Update opacity
        self._opacity += 0.05 * self._opacity_direction
        
        if self._opacity >= 0.5:
            self._opacity_direction = -1
        elif self._opacity <= 0.2:
            self._opacity_direction = 1
        
        # Update brush
        color = QColor(100, 200, 255, int(self._opacity * 255))
        self.setBrush(QBrush(color))


class ProgressiveLoadingManager(QObject):
    """
    Manages loading indicators for progressive data loading.
    
    Displays subtle visual feedback for time ranges being loaded in the background.
    """
    
    def __init__(self, scene, timeline_height: float):
        """
        Initialize loading manager.
        
        Args:
            scene: QGraphicsScene to add indicators to
            timeline_height: Height of the timeline area
        """
        super().__init__()
        self.scene = scene
        self.timeline_height = timeline_height
        
        # Active loading indicators
        self._indicators: Dict[object, LoadingIndicator] = {}  # time_range -> indicator
        
        # Animation timer
        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._animate_indicators)
        self._animation_timer.setInterval(50)  # 50ms = 20 FPS
    
    def show_loading(self, time_range, x_pos: float, width: float):
        """
        Show loading indicator for a time range.
        
        Args:
            time_range: TimeRange object being loaded
            x_pos: X position on timeline
            width: Width of the time range
        """
        if time_range in self._indicators:
            return  # Already showing
        
        # Create indicator
        indicator = LoadingIndicator(x_pos, width, self.timeline_height)
        self.scene.addItem(indicator)
        
        # Store reference
        self._indicators[time_range] = indicator
        
        # Start animation if not running
        if not self._animation_timer.isActive():
            self._animation_timer.start()
    
    def hide_loading(self, time_range):
        """
        Hide loading indicator for a time range.
        
        Args:
            time_range: TimeRange object that finished loading
        """
        if time_range not in self._indicators:
            return
        
        # Remove indicator
        indicator = self._indicators[time_range]
        self.scene.removeItem(indicator)
        del self._indicators[time_range]
        
        # Stop animation if no more indicators
        if not self._indicators and self._animation_timer.isActive():
            self._animation_timer.stop()
    
    def clear_all(self):
        """Clear all loading indicators."""
        for indicator in list(self._indicators.values()):
            self.scene.removeItem(indicator)
        
        self._indicators.clear()
        
        if self._animation_timer.isActive():
            self._animation_timer.stop()
    
    def _animate_indicators(self):
        """Animate all active indicators."""
        for indicator in self._indicators.values():
            indicator.animate_pulse()
    
    def is_loading(self, time_range) -> bool:
        """
        Check if a time range is currently showing loading indicator.
        
        Args:
            time_range: TimeRange to check
        
        Returns:
            bool: True if loading indicator is shown
        """
        return time_range in self._indicators
