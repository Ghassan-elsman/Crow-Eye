"""
Timeline Widget for Time-Based Hierarchical Results View

Provides visual timeline representation of anchor times with interactive navigation,
time range selection, and comparative analysis capabilities.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QSlider, QFrame, QScrollArea, QToolTip, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QPoint, QTimer
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QFontMetrics, QMouseEvent, QPaintEvent

from ..engine.data_structures import AnchorTimeGroup, TimeBasedQueryResult

logger = logging.getLogger(__name__)


@dataclass
class TimelineEvent:
    """Represents an event on the timeline."""
    timestamp: datetime
    event_type: str  # "anchor_time", "activity_peak", "gap"
    data: Dict[str, Any]
    color: QColor
    size: int = 5  # Visual size on timeline


class TimelineWidget(QWidget):
    """
    Interactive timeline widget for visualizing anchor times and activity patterns.
    
    Features:
    - Visual representation of anchor times with activity levels
    - Interactive time range selection
    - Zoom and pan capabilities
    - Activity density visualization
    - Time period comparison
    """
    
    # Signals
    time_range_selected = pyqtSignal(datetime, datetime)  # Start, end time selected
    anchor_time_clicked = pyqtSignal(datetime)  # Anchor time clicked
    time_period_compared = pyqtSignal(datetime, datetime, datetime, datetime)  # Two time ranges for comparison
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.anchor_time_groups: List[AnchorTimeGroup] = []
        self.time_range: Optional[Tuple[datetime, datetime]] = None
        self.zoom_level: float = 1.0
        self.pan_offset: float = 0.0
        
        # Selection state
        self.selection_start: Optional[datetime] = None
        self.selection_end: Optional[datetime] = None
        self.comparison_range_1: Optional[Tuple[datetime, datetime]] = None
        self.comparison_range_2: Optional[Tuple[datetime, datetime]] = None
        
        # Visual settings
        self.timeline_height = 60
        self.margin = 20
        self.activity_colors = {
            'low': QColor(100, 150, 200),
            'medium': QColor(255, 200, 100),
            'high': QColor(255, 100, 100)
        }
        
        self._init_ui()
        self._setup_interactions()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Zoom controls
        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.setMaximumWidth(30)
        zoom_out_btn.clicked.connect(self.zoom_out)
        controls_layout.addWidget(zoom_out_btn)
        
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(1)
        self.zoom_slider.setMaximum(100)
        self.zoom_slider.setValue(10)
        self.zoom_slider.setMaximumWidth(100)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        controls_layout.addWidget(self.zoom_slider)
        
        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setMaximumWidth(30)
        zoom_in_btn.clicked.connect(self.zoom_in)
        controls_layout.addWidget(zoom_in_btn)
        
        # Time range display
        self.time_range_label = QLabel("No time range")
        self.time_range_label.setStyleSheet("color: #888; font-size: 9pt;")
        controls_layout.addWidget(self.time_range_label)
        
        controls_layout.addStretch()
        
        # Action buttons
        fit_btn = QPushButton("Fit All")
        fit_btn.setMaximumWidth(60)
        fit_btn.clicked.connect(self.fit_to_data)
        controls_layout.addWidget(fit_btn)
        
        clear_btn = QPushButton("Clear Selection")
        clear_btn.setMaximumWidth(100)
        clear_btn.clicked.connect(self.clear_selection)
        controls_layout.addWidget(clear_btn)
        
        compare_btn = QPushButton("Compare Periods")
        compare_btn.setMaximumWidth(120)
        compare_btn.clicked.connect(self._start_comparison_mode)
        controls_layout.addWidget(compare_btn)
        
        layout.addLayout(controls_layout)
        
        # Timeline canvas
        self.timeline_canvas = TimelineCanvas(self)
        self.timeline_canvas.setMinimumHeight(self.timeline_height + 40)
        self.timeline_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.timeline_canvas)
        
        # Activity summary
        self.activity_summary = QLabel("No data loaded")
        self.activity_summary.setStyleSheet("color: #888; font-size: 8pt; padding: 5px;")
        layout.addWidget(self.activity_summary)
    
    def _setup_interactions(self):
        """Setup mouse and keyboard interactions."""
        self.timeline_canvas.mousePressEvent = self._on_canvas_mouse_press
        self.timeline_canvas.mouseMoveEvent = self._on_canvas_mouse_move
        self.timeline_canvas.mouseReleaseEvent = self._on_canvas_mouse_release
        self.timeline_canvas.wheelEvent = self._on_canvas_wheel
        
        # Enable mouse tracking for hover effects
        self.timeline_canvas.setMouseTracking(True)
    
    def set_data(self, anchor_time_groups: List[AnchorTimeGroup]):
        """Set timeline data and update visualization."""
        self.anchor_time_groups = anchor_time_groups
        
        if anchor_time_groups:
            # Calculate time range
            times = [group.anchor_time for group in anchor_time_groups]
            self.time_range = (min(times), max(times))
            
            # Update display
            self._update_time_range_display()
            self._update_activity_summary()
            self.fit_to_data()
        else:
            self.time_range = None
            self.time_range_label.setText("No data")
            self.activity_summary.setText("No data loaded")
        
        self.timeline_canvas.update()
    
    def _update_time_range_display(self):
        """Update time range display label."""
        if self.time_range:
            start, end = self.time_range
            duration = end - start
            
            if duration.days > 0:
                duration_text = f"{duration.days}d {duration.seconds // 3600}h"
            elif duration.seconds > 3600:
                duration_text = f"{duration.seconds // 3600}h {(duration.seconds % 3600) // 60}m"
            else:
                duration_text = f"{duration.seconds // 60}m"
            
            self.time_range_label.setText(
                f"{start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')} ({duration_text})"
            )
    
    def _update_activity_summary(self):
        """Update activity summary display."""
        if not self.anchor_time_groups:
            return
        
        total_identities = sum(group.total_identities for group in self.anchor_time_groups)
        total_evidence = sum(group.total_evidence for group in self.anchor_time_groups)
        peak_activity = max(group.total_evidence for group in self.anchor_time_groups)
        
        # Calculate activity distribution
        low_activity = sum(1 for group in self.anchor_time_groups if group.total_evidence < peak_activity * 0.3)
        medium_activity = sum(1 for group in self.anchor_time_groups if peak_activity * 0.3 <= group.total_evidence < peak_activity * 0.7)
        high_activity = sum(1 for group in self.anchor_time_groups if group.total_evidence >= peak_activity * 0.7)
        
        summary_text = (
            f"📊 {len(self.anchor_time_groups)} anchor times | "
            f"👥 {total_identities} identities | "
            f"📄 {total_evidence} evidence | "
            f"Activity: 🟢{high_activity} 🟡{medium_activity} 🔵{low_activity}"
        )
        
        self.activity_summary.setText(summary_text)
    
    def zoom_in(self):
        """Zoom in on timeline."""
        self.zoom_level = min(self.zoom_level * 1.5, 50.0)
        self.timeline_canvas.update()
    
    def zoom_out(self):
        """Zoom out on timeline."""
        self.zoom_level = max(self.zoom_level / 1.5, 0.1)
        self.timeline_canvas.update()
    
    def _on_zoom_changed(self, value: int):
        """Handle zoom slider change."""
        self.zoom_level = value / 10.0
        self.timeline_canvas.update()
    
    def fit_to_data(self):
        """Fit timeline to show all data."""
        if self.time_range:
            self.zoom_level = 1.0
            self.pan_offset = 0.0
            self.zoom_slider.setValue(10)
            self.timeline_canvas.update()
    
    def clear_selection(self):
        """Clear current selection."""
        self.selection_start = None
        self.selection_end = None
        self.comparison_range_1 = None
        self.comparison_range_2 = None
        self.timeline_canvas.update()
    
    def _start_comparison_mode(self):
        """Start comparison mode for selecting two time periods."""
        # Implementation for comparison mode
        self.clear_selection()
        # Set flag to indicate comparison mode
        self.timeline_canvas.comparison_mode = True
        self.timeline_canvas.update()
    
    def _on_canvas_mouse_press(self, event: QMouseEvent):
        """Handle mouse press on timeline canvas."""
        if not self.time_range:
            return
        
        # Convert mouse position to time
        time_at_pos = self._mouse_pos_to_time(event.x())
        
        if event.button() == Qt.LeftButton:
            # Start selection
            self.selection_start = time_at_pos
            self.selection_end = None
            
            # Check if clicking on anchor time
            clicked_anchor = self._find_anchor_at_time(time_at_pos)
            if clicked_anchor:
                self.anchor_time_clicked.emit(clicked_anchor.anchor_time)
        
        self.timeline_canvas.update()
    
    def _on_canvas_mouse_move(self, event: QMouseEvent):
        """Handle mouse move on timeline canvas."""
        if not self.time_range:
            return
        
        time_at_pos = self._mouse_pos_to_time(event.x())
        
        # Update selection if dragging
        if self.selection_start and event.buttons() & Qt.LeftButton:
            self.selection_end = time_at_pos
            self.timeline_canvas.update()
        
        # Show tooltip for anchor times
        anchor = self._find_anchor_at_time(time_at_pos)
        if anchor:
            tooltip_text = (
                f"Time: {anchor.anchor_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Identities: {anchor.total_identities}\n"
                f"Evidence: {anchor.total_evidence}\n"
                f"Artifacts: {', '.join(anchor.primary_artifacts[:3])}"
            )
            QToolTip.showText(event.globalPos(), tooltip_text)
    
    def _on_canvas_mouse_release(self, event: QMouseEvent):
        """Handle mouse release on timeline canvas."""
        if self.selection_start and self.selection_end:
            # Emit time range selection
            start_time = min(self.selection_start, self.selection_end)
            end_time = max(self.selection_start, self.selection_end)
            
            # Only emit if selection is meaningful (> 1 minute)
            if (end_time - start_time).total_seconds() > 60:
                self.time_range_selected.emit(start_time, end_time)
    
    def _on_canvas_wheel(self, event):
        """Handle mouse wheel for zooming."""
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
    
    def _mouse_pos_to_time(self, x_pos: int) -> datetime:
        """Convert mouse X position to datetime."""
        if not self.time_range:
            return datetime.now()
        
        start_time, end_time = self.time_range
        canvas_width = self.timeline_canvas.width() - 2 * self.margin
        
        # Account for zoom and pan
        effective_width = canvas_width * self.zoom_level
        x_offset = x_pos - self.margin + self.pan_offset
        
        # Calculate time position
        time_ratio = x_offset / effective_width
        time_delta = (end_time - start_time) * time_ratio
        
        return start_time + time_delta
    
    def _find_anchor_at_time(self, target_time: datetime, tolerance_minutes: int = 180) -> Optional[AnchorTimeGroup]:
        """Find anchor time group near the target time (default: 3 hours tolerance)."""
        tolerance = timedelta(minutes=tolerance_minutes)
        
        for group in self.anchor_time_groups:
            if abs((group.anchor_time - target_time).total_seconds()) <= tolerance.total_seconds():
                return group
        
        return None


class TimelineCanvas(QWidget):
    """Canvas widget for drawing the timeline visualization."""
    
    def __init__(self, timeline_widget: TimelineWidget):
        super().__init__()
        self.timeline = timeline_widget
        self.comparison_mode = False
        
        # Visual settings
        self.background_color = QColor(30, 30, 30)
        self.grid_color = QColor(60, 60, 60)
        self.selection_color = QColor(33, 150, 243, 100)
        self.anchor_color = QColor(255, 255, 255)
        
    def paintEvent(self, event: QPaintEvent):
        """Paint the timeline visualization."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Fill background
        painter.fillRect(self.rect(), self.background_color)
        
        if not self.timeline.time_range or not self.timeline.anchor_time_groups:
            # Draw "no data" message
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(self.rect(), Qt.AlignCenter, "No timeline data available")
            return
        
        # Draw timeline components
        self._draw_time_grid(painter)
        self._draw_anchor_times(painter)
        self._draw_activity_density(painter)
        self._draw_selection(painter)
        self._draw_time_labels(painter)
    
    def _draw_time_grid(self, painter: QPainter):
        """Draw time grid lines."""
        if not self.timeline.time_range:
            return
        
        start_time, end_time = self.timeline.time_range
        canvas_width = self.width() - 2 * self.timeline.margin
        canvas_height = self.height()
        
        painter.setPen(QPen(self.grid_color, 1))
        
        # Calculate grid interval based on time range
        duration = (end_time - start_time).total_seconds()
        
        if duration < 3600:  # Less than 1 hour - 10 minute intervals
            interval = timedelta(minutes=10)
        elif duration < 86400:  # Less than 1 day - 1 hour intervals
            interval = timedelta(hours=1)
        else:  # 6 hour intervals
            interval = timedelta(hours=6)
        
        # Draw grid lines
        current_time = start_time
        while current_time <= end_time:
            x_pos = self._time_to_x_pos(current_time)
            if self.timeline.margin <= x_pos <= self.width() - self.timeline.margin:
                painter.drawLine(x_pos, 0, x_pos, canvas_height)
            current_time += interval
    
    def _draw_anchor_times(self, painter: QPainter):
        """Draw anchor time markers."""
        if not self.timeline.anchor_time_groups:
            return
        
        # Calculate activity levels for color coding
        max_evidence = max(group.total_evidence for group in self.timeline.anchor_time_groups)
        
        for group in self.timeline.anchor_time_groups:
            x_pos = self._time_to_x_pos(group.anchor_time)
            
            if not (self.timeline.margin <= x_pos <= self.width() - self.timeline.margin):
                continue
            
            # Determine color based on activity level
            activity_ratio = group.total_evidence / max_evidence if max_evidence > 0 else 0
            
            if activity_ratio >= 0.7:
                color = self.timeline.activity_colors['high']
            elif activity_ratio >= 0.3:
                color = self.timeline.activity_colors['medium']
            else:
                color = self.timeline.activity_colors['low']
            
            # Draw anchor marker
            marker_size = 4 + int(activity_ratio * 6)  # Size based on activity
            y_center = self.height() // 2
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(150), 2))
            painter.drawEllipse(x_pos - marker_size//2, y_center - marker_size//2, marker_size, marker_size)
            
            # Draw activity bar
            bar_height = int(activity_ratio * 30)
            painter.fillRect(x_pos - 1, y_center - bar_height//2, 2, bar_height, color)
    
    def _draw_activity_density(self, painter: QPainter):
        """Draw activity density visualization."""
        if not self.timeline.anchor_time_groups:
            return
        
        # Create density map
        canvas_width = self.width() - 2 * self.timeline.margin
        density_height = 20
        y_pos = self.height() - density_height - 5
        
        # Calculate density in time buckets
        bucket_count = min(canvas_width // 2, 200)  # Limit buckets for performance
        bucket_width = canvas_width / bucket_count
        
        start_time, end_time = self.timeline.time_range
        time_per_bucket = (end_time - start_time) / bucket_count
        
        densities = []
        for i in range(bucket_count):
            bucket_start = start_time + time_per_bucket * i
            bucket_end = bucket_start + time_per_bucket
            
            # Count evidence in this bucket
            evidence_count = 0
            for group in self.timeline.anchor_time_groups:
                if bucket_start <= group.anchor_time < bucket_end:
                    evidence_count += group.total_evidence
            
            densities.append(evidence_count)
        
        # Draw density bars
        max_density = max(densities) if densities else 1
        
        for i, density in enumerate(densities):
            if density == 0:
                continue
            
            x_pos = self.timeline.margin + i * bucket_width
            bar_height = (density / max_density) * density_height
            
            # Color based on density
            intensity = density / max_density
            color = QColor(int(100 + intensity * 155), int(150 - intensity * 50), int(200 - intensity * 100))
            
            painter.fillRect(int(x_pos), int(y_pos + density_height - bar_height), 
                           int(bucket_width), int(bar_height), color)
    
    def _draw_selection(self, painter: QPainter):
        """Draw time range selection."""
        if not (self.timeline.selection_start and self.timeline.selection_end):
            return
        
        start_x = self._time_to_x_pos(self.timeline.selection_start)
        end_x = self._time_to_x_pos(self.timeline.selection_end)
        
        # Ensure proper order
        left_x = min(start_x, end_x)
        right_x = max(start_x, end_x)
        
        # Draw selection rectangle
        painter.fillRect(left_x, 0, right_x - left_x, self.height(), self.selection_color)
        
        # Draw selection borders
        painter.setPen(QPen(self.selection_color.darker(150), 2))
        painter.drawLine(left_x, 0, left_x, self.height())
        painter.drawLine(right_x, 0, right_x, self.height())
    
    def _draw_time_labels(self, painter: QPainter):
        """Draw time labels on the timeline."""
        if not self.timeline.time_range:
            return
        
        start_time, end_time = self.timeline.time_range
        
        painter.setPen(QPen(QColor(200, 200, 200)))
        font = QFont("Arial", 8)
        painter.setFont(font)
        
        # Draw start and end labels
        start_label = start_time.strftime("%H:%M")
        end_label = end_time.strftime("%H:%M")
        
        painter.drawText(self.timeline.margin, self.height() - 5, start_label)
        
        end_label_width = QFontMetrics(font).width(end_label)
        painter.drawText(self.width() - self.timeline.margin - end_label_width, self.height() - 5, end_label)
        
        # Draw middle label if space allows
        if self.width() > 300:
            middle_time = start_time + (end_time - start_time) / 2
            middle_label = middle_time.strftime("%H:%M")
            middle_x = self.width() // 2 - QFontMetrics(font).width(middle_label) // 2
            painter.drawText(middle_x, self.height() - 5, middle_label)
    
    def _time_to_x_pos(self, time: datetime) -> int:
        """Convert datetime to X position on canvas."""
        if not self.timeline.time_range:
            return 0
        
        start_time, end_time = self.timeline.time_range
        canvas_width = self.width() - 2 * self.timeline.margin
        
        # Calculate position ratio
        time_ratio = (time - start_time).total_seconds() / (end_time - start_time).total_seconds()
        
        # Account for zoom and pan
        effective_width = canvas_width * self.timeline.zoom_level
        x_pos = self.timeline.margin + (time_ratio * effective_width) - self.timeline.pan_offset
        
        return int(x_pos)