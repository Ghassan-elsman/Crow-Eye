"""
Animation Manager - Smooth animations for timeline interactions.

This module provides smooth, professional animations for zoom, pan, and other
timeline interactions to enhance user experience.
"""

from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, QObject, pyqtProperty, QPointF
from PyQt5.QtWidgets import QGraphicsView


class SmoothScrollAnimation(QObject):
    """
    Smooth scrolling animation for timeline panning.
    
    Provides eased scrolling animations when panning the timeline view.
    """
    
    def __init__(self, graphics_view, duration=300):
        """
        Initialize smooth scroll animation.
        
        Args:
            graphics_view (QGraphicsView): The graphics view to animate
            duration (int): Animation duration in milliseconds
        """
        super().__init__()
        self.graphics_view = graphics_view
        self.duration = duration
        
        # Create horizontal scroll animation
        self.h_animation = QPropertyAnimation(
            graphics_view.horizontalScrollBar(),
            b"value"
        )
        self.h_animation.setDuration(duration)
        self.h_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Create vertical scroll animation
        self.v_animation = QPropertyAnimation(
            graphics_view.verticalScrollBar(),
            b"value"
        )
        self.v_animation.setDuration(duration)
        self.v_animation.setEasingCurve(QEasingCurve.OutCubic)
    
    def scroll_to(self, x=None, y=None):
        """
        Smoothly scroll to specified position.
        
        Args:
            x (int): Target horizontal scroll position (None to skip)
            y (int): Target vertical scroll position (None to skip)
        """
        if x is not None:
            self.h_animation.setEndValue(x)
            self.h_animation.start()
        
        if y is not None:
            self.v_animation.setEndValue(y)
            self.v_animation.start()
    
    def scroll_by(self, dx=0, dy=0):
        """
        Smoothly scroll by specified delta.
        
        Args:
            dx (int): Horizontal scroll delta
            dy (int): Vertical scroll delta
        """
        if dx != 0:
            current_x = self.graphics_view.horizontalScrollBar().value()
            self.scroll_to(x=current_x + dx)
        
        if dy != 0:
            current_y = self.graphics_view.verticalScrollBar().value()
            self.scroll_to(y=current_y + dy)


class SmoothZoomAnimation(QObject):
    """
    Smooth zoom animation for timeline scaling.
    
    Provides eased zoom animations with center point preservation.
    """
    
    def __init__(self, graphics_view, duration=250):
        """
        Initialize smooth zoom animation.
        
        Args:
            graphics_view (QGraphicsView): The graphics view to animate
            duration (int): Animation duration in milliseconds
        """
        super().__init__()
        self.graphics_view = graphics_view
        self.duration = duration
        self._zoom_factor = 1.0
        
        # Create zoom animation
        self.animation = QPropertyAnimation(self, b"zoomFactor")
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._apply_zoom)
    
    def get_zoom_factor(self):
        """Get current zoom factor."""
        return self._zoom_factor
    
    def set_zoom_factor(self, factor):
        """Set zoom factor and apply to view."""
        self._zoom_factor = factor
    
    zoomFactor = pyqtProperty(float, get_zoom_factor, set_zoom_factor)
    
    def _apply_zoom(self):
        """Apply current zoom factor to graphics view."""
        # This would be called during animation
        # Actual zoom implementation depends on timeline canvas
        pass
    
    def zoom_to(self, target_factor, center_point=None):
        """
        Smoothly zoom to target factor.
        
        Args:
            target_factor (float): Target zoom factor
            center_point (QPointF): Point to keep centered during zoom
        """
        self.animation.setStartValue(self._zoom_factor)
        self.animation.setEndValue(target_factor)
        self.animation.start()


class FadeAnimation(QObject):
    """
    Fade in/out animation for UI elements.
    
    Provides smooth opacity transitions for showing/hiding elements.
    """
    
    def __init__(self, widget, duration=200):
        """
        Initialize fade animation.
        
        Args:
            widget (QWidget): Widget to animate
            duration (int): Animation duration in milliseconds
        """
        super().__init__()
        self.widget = widget
        self.duration = duration
        
        # Create opacity effect and animation
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self.opacity_effect = QGraphicsOpacityEffect()
        self.widget.setGraphicsEffect(self.opacity_effect)
        
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
    
    def fade_in(self):
        """Fade in the widget."""
        self.widget.show()
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
    
    def fade_out(self, hide_on_finish=True):
        """
        Fade out the widget.
        
        Args:
            hide_on_finish (bool): Hide widget when animation completes
        """
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        
        if hide_on_finish:
            self.animation.finished.connect(self.widget.hide)
        
        self.animation.start()


class PulseAnimation(QObject):
    """
    Pulse animation for highlighting elements.
    
    Provides attention-grabbing pulse effect for important UI elements.
    """
    
    def __init__(self, widget, duration=1000):
        """
        Initialize pulse animation.
        
        Args:
            widget (QWidget): Widget to animate
            duration (int): Animation duration in milliseconds
        """
        super().__init__()
        self.widget = widget
        self.duration = duration
        
        # Create opacity effect and animation
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self.opacity_effect = QGraphicsOpacityEffect()
        self.widget.setGraphicsEffect(self.opacity_effect)
        
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.InOutSine)
        self.animation.setLoopCount(-1)  # Infinite loop
    
    def start_pulse(self):
        """Start pulsing animation."""
        self.animation.setStartValue(0.3)
        self.animation.setEndValue(1.0)
        self.animation.start()
    
    def stop_pulse(self):
        """Stop pulsing animation."""
        self.animation.stop()
        self.opacity_effect.setOpacity(1.0)


class SlideAnimation(QObject):
    """
    Slide animation for panel transitions.
    
    Provides smooth sliding transitions for showing/hiding panels.
    """
    
    def __init__(self, widget, duration=300):
        """
        Initialize slide animation.
        
        Args:
            widget (QWidget): Widget to animate
            duration (int): Animation duration in milliseconds
        """
        super().__init__()
        self.widget = widget
        self.duration = duration
        
        # Create geometry animation
        self.animation = QPropertyAnimation(widget, b"maximumHeight")
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
    
    def slide_down(self, target_height):
        """
        Slide down to reveal widget.
        
        Args:
            target_height (int): Target height in pixels
        """
        self.widget.show()
        self.animation.setStartValue(0)
        self.animation.setEndValue(target_height)
        self.animation.start()
    
    def slide_up(self, hide_on_finish=True):
        """
        Slide up to hide widget.
        
        Args:
            hide_on_finish (bool): Hide widget when animation completes
        """
        current_height = self.widget.height()
        self.animation.setStartValue(current_height)
        self.animation.setEndValue(0)
        
        if hide_on_finish:
            self.animation.finished.connect(self.widget.hide)
        
        self.animation.start()


class HoverEffectManager:
    """
    Manager for hover effects on interactive elements.
    
    Provides consistent hover feedback across all timeline UI elements.
    """
    
    @staticmethod
    def apply_button_hover_effect(button):
        """
        Apply hover effect to a button.
        
        Args:
            button (QPushButton): Button to enhance
        """
        # Store original stylesheet
        original_style = button.styleSheet()
        
        def on_enter(event):
            # Add glow effect on hover
            button.setStyleSheet(original_style + """
                QPushButton {
                    border: 1px solid #00FFFF;
                    box-shadow: 0 0 10px rgba(0, 255, 255, 0.3);
                }
            """)
        
        def on_leave(event):
            # Restore original style
            button.setStyleSheet(original_style)
        
        # Install event filter for hover
        button.enterEvent = on_enter
        button.leaveEvent = on_leave
    
    @staticmethod
    def apply_checkbox_hover_effect(checkbox):
        """
        Apply hover effect to a checkbox.
        
        Args:
            checkbox (QCheckBox): Checkbox to enhance
        """
        # Hover effects are typically handled in stylesheet
        # This method can be extended for custom hover behaviors
        pass
    
    @staticmethod
    def apply_marker_hover_effect(marker_item):
        """
        Apply hover effect to an event marker.
        
        Args:
            marker_item (QGraphicsItem): Marker to enhance
        """
        # Enable hover events
        marker_item.setAcceptHoverEvents(True)
        
        # Store original properties
        original_scale = marker_item.scale()
        
        def on_hover_enter(event):
            # Scale up slightly on hover
            marker_item.setScale(original_scale * 1.2)
        
        def on_hover_leave(event):
            # Restore original scale
            marker_item.setScale(original_scale)
        
        # Set hover event handlers
        marker_item.hoverEnterEvent = on_hover_enter
        marker_item.hoverLeaveEvent = on_hover_leave
