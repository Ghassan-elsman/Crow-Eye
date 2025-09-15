"""Enhanced timeline and visualization components for Crow Eye."""

import sys
import json
import sqlite3
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFrame, QSplitter, QTabWidget, QComboBox, QSpinBox, QCheckBox,
    QSlider, QGroupBox, QGridLayout, QTextEdit, QProgressBar,
    QSizePolicy, QApplication
)
from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QObject,
    pyqtSignal, QThread, QSize
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPalette,
    QLinearGradient, QPixmap, QIcon
)

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import pandas as pd
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Matplotlib not available. Some visualization features will be limited.")


@dataclass
class TimelineEvent:
    """Represents an event on the timeline."""
    timestamp: datetime
    event_type: str
    title: str
    description: str
    artifact_type: str
    metadata: Dict[str, Any]
    importance: int = 1  # 1-5 scale
    color: str = "#3B82F6"


class TimelineWidget(QWidget):
    """Interactive timeline widget for visualizing forensic artifacts."""
    
    event_selected = pyqtSignal(dict)  # Emitted when an event is selected
    
    def __init__(self, parent=None):
        """Initialize the timeline widget."""
        super().__init__(parent)
        self.events: List[TimelineEvent] = []
        self.visible_events: List[TimelineEvent] = []
        self.selected_event: Optional[TimelineEvent] = None
        self.zoom_level = 1.0
        self.time_range_start: Optional[datetime] = None
        self.time_range_end: Optional[datetime] = None
        self.event_height = 30
        self.margin_left = 100
        self.margin_top = 50
        
        self.logger = logging.getLogger(__name__)
        self.setup_ui()
        
    def setup_ui(self):
        """Set up the timeline UI."""
        layout = QVBoxLayout(self)
        
        # Control panel
        controls = self.create_control_panel()
        layout.addWidget(controls)
        
        # Timeline view
        timeline_frame = QFrame()
        timeline_frame.setMinimumHeight(400)
        timeline_frame.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 5px;
            }
        """)
        
        timeline_layout = QVBoxLayout(timeline_frame)
        
        # Scroll area for timeline
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Timeline canvas
        self.timeline_canvas = TimelineCanvas(self)
        self.scroll_area.setWidget(self.timeline_canvas)
        
        timeline_layout.addWidget(self.scroll_area)
        layout.addWidget(timeline_frame)
        
        # Details panel
        self.details_panel = self.create_details_panel()
        layout.addWidget(self.details_panel)
        
        # Set up refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_timeline)
        self.refresh_timer.setSingleShot(True)
        
    def create_control_panel(self) -> QWidget:
        """Create the timeline control panel."""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #475569;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        
        layout = QHBoxLayout(panel)
        
        # Zoom controls
        zoom_group = QGroupBox("Zoom")
        zoom_layout = QHBoxLayout(zoom_group)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_out_btn = QPushButton("-")
        zoom_out_btn.clicked.connect(self.zoom_out)
        
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(1, 100)
        self.zoom_slider.setValue(int(self.zoom_level * 10))
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        
        zoom_layout.addWidget(zoom_out_btn)
        zoom_layout.addWidget(self.zoom_slider)
        zoom_layout.addWidget(zoom_in_btn)
        
        layout.addWidget(zoom_group)
        
        # Filter controls
        filter_group = QGroupBox("Filters")
        filter_layout = QHBoxLayout(filter_group)
        
        self.artifact_filter = QComboBox()
        self.artifact_filter.addItem("All Artifacts")
        self.artifact_filter.currentTextChanged.connect(self.on_filter_changed)
        
        self.importance_filter = QComboBox()
        self.importance_filter.addItems(["All", "High (4-5)", "Medium (2-3)", "Low (1)"])
        self.importance_filter.currentTextChanged.connect(self.on_filter_changed)
        
        filter_layout.addWidget(QLabel("Artifact Type:"))
        filter_layout.addWidget(self.artifact_filter)
        filter_layout.addWidget(QLabel("Importance:"))
        filter_layout.addWidget(self.importance_filter)
        
        layout.addWidget(filter_group)
        
        # Auto-refresh toggle
        self.auto_refresh_cb = QCheckBox("Auto-refresh")
        self.auto_refresh_cb.stateChanged.connect(self.on_auto_refresh_changed)
        layout.addWidget(self.auto_refresh_cb)
        
        # Export button
        export_btn = QPushButton("Export Timeline")
        export_btn.clicked.connect(self.export_timeline)
        layout.addWidget(export_btn)
        
        layout.addStretch()
        
        return panel
        
    def create_details_panel(self) -> QWidget:
        """Create the event details panel."""
        panel = QGroupBox("Event Details")
        panel.setMaximumHeight(150)
        panel.setStyleSheet("""
            QGroupBox {
                background-color: #1E293B;
                border: 1px solid #475569;
                border-radius: 5px;
                font-weight: bold;
                color: #E2E8F0;
            }
        """)
        
        layout = QVBoxLayout(panel)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet("""
            QTextEdit {
                background-color: #0F172A;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 3px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        
        layout.addWidget(self.details_text)
        
        return panel
    
    def add_events(self, events: List[TimelineEvent]):
        """Add events to the timeline."""
        self.events.extend(events)
        self.update_artifact_filter()
        self.apply_filters()
        self.timeline_canvas.update_events(self.visible_events)
        
    def clear_events(self):
        """Clear all events from the timeline."""
        self.events.clear()
        self.visible_events.clear()
        self.timeline_canvas.update_events([])
        
    def apply_filters(self):
        """Apply current filters to events."""
        filtered_events = []
        
        artifact_filter = self.artifact_filter.currentText()
        importance_filter = self.importance_filter.currentText()
        
        for event in self.events:
            # Artifact type filter
            if artifact_filter != "All Artifacts" and event.artifact_type != artifact_filter:
                continue
                
            # Importance filter
            if importance_filter == "High (4-5)" and event.importance < 4:
                continue
            elif importance_filter == "Medium (2-3)" and not (2 <= event.importance <= 3):
                continue
            elif importance_filter == "Low (1)" and event.importance != 1:
                continue
            
            filtered_events.append(event)
        
        self.visible_events = filtered_events
        self.timeline_canvas.update_events(self.visible_events)
        
    def update_artifact_filter(self):
        """Update the artifact type filter options."""
        current_text = self.artifact_filter.currentText()
        self.artifact_filter.clear()
        self.artifact_filter.addItem("All Artifacts")
        
        artifact_types = set(event.artifact_type for event in self.events)
        for artifact_type in sorted(artifact_types):
            self.artifact_filter.addItem(artifact_type)
        
        # Restore previous selection if possible
        index = self.artifact_filter.findText(current_text)
        if index >= 0:
            self.artifact_filter.setCurrentIndex(index)
    
    def zoom_in(self):
        """Zoom in on the timeline."""
        self.zoom_level = min(10.0, self.zoom_level * 1.2)
        self.zoom_slider.setValue(int(self.zoom_level * 10))
        self.timeline_canvas.set_zoom(self.zoom_level)
        
    def zoom_out(self):
        """Zoom out of the timeline."""
        self.zoom_level = max(0.1, self.zoom_level / 1.2)
        self.zoom_slider.setValue(int(self.zoom_level * 10))
        self.timeline_canvas.set_zoom(self.zoom_level)
        
    def on_zoom_changed(self, value):
        """Handle zoom slider changes."""
        self.zoom_level = value / 10.0
        self.timeline_canvas.set_zoom(self.zoom_level)
        
    def on_filter_changed(self):
        """Handle filter changes."""
        self.apply_filters()
        
    def on_auto_refresh_changed(self, state):
        """Handle auto-refresh toggle."""
        if state == Qt.Checked:
            self.refresh_timer.start(5000)  # Refresh every 5 seconds
        else:
            self.refresh_timer.stop()
            
    def refresh_timeline(self):
        """Refresh the timeline data."""
        if self.auto_refresh_cb.isChecked():
            # Emit signal to request fresh data
            # This would be connected to the main application
            self.refresh_timer.start(5000)
            
    def export_timeline(self):
        """Export timeline data."""
        try:
            from PyQt5.QtWidgets import QFileDialog
            
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Timeline", "", "JSON Files (*.json)"
            )
            
            if filename:
                timeline_data = {
                    "events": [
                        {
                            "timestamp": event.timestamp.isoformat(),
                            "event_type": event.event_type,
                            "title": event.title,
                            "description": event.description,
                            "artifact_type": event.artifact_type,
                            "metadata": event.metadata,
                            "importance": event.importance,
                            "color": event.color
                        }
                        for event in self.visible_events
                    ],
                    "exported_at": datetime.now().isoformat(),
                    "total_events": len(self.visible_events)
                }
                
                with open(filename, 'w') as f:
                    json.dump(timeline_data, f, indent=2)
                    
                self.logger.info(f"Timeline exported to {filename}")
                
        except Exception as e:
            self.logger.error(f"Error exporting timeline: {e}")
    
    def on_event_selected(self, event: TimelineEvent):
        """Handle event selection."""
        self.selected_event = event
        self.event_selected.emit(event.metadata)
        
        # Update details panel
        details_html = f"""
        <h3 style="color: #00FFFF;">{event.title}</h3>
        <p><strong>Type:</strong> {event.event_type}</p>
        <p><strong>Artifact:</strong> {event.artifact_type}</p>
        <p><strong>Time:</strong> {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Importance:</strong> {event.importance}/5</p>
        <p><strong>Description:</strong> {event.description}</p>
        """
        
        if event.metadata:
            details_html += "<p><strong>Metadata:</strong></p><ul>"
            for key, value in event.metadata.items():
                details_html += f"<li><strong>{key}:</strong> {value}</li>"
            details_html += "</ul>"
        
        self.details_text.setHtml(details_html)


class TimelineCanvas(QWidget):
    """Canvas for drawing the timeline visualization."""
    
    def __init__(self, parent_timeline: TimelineWidget):
        """Initialize the timeline canvas."""
        super().__init__()
        self.parent_timeline = parent_timeline
        self.events: List[TimelineEvent] = []
        self.zoom_level = 1.0
        self.scroll_offset_x = 0
        self.scroll_offset_y = 0
        
        self.setMinimumSize(800, 400)
        self.setMouseTracking(True)
        
        # Colors
        self.bg_color = QColor("#0F172A")
        self.grid_color = QColor("#334155")
        self.text_color = QColor("#E2E8F0")
        self.accent_color = QColor("#00FFFF")
        
    def update_events(self, events: List[TimelineEvent]):
        """Update the events to display."""
        self.events = events
        self.calculate_layout()
        self.update()
        
    def set_zoom(self, zoom_level: float):
        """Set the zoom level."""
        self.zoom_level = zoom_level
        self.calculate_layout()
        self.update()
        
    def calculate_layout(self):
        """Calculate the layout of events on the timeline."""
        if not self.events:
            return
        
        # Sort events by timestamp
        sorted_events = sorted(self.events, key=lambda e: e.timestamp)
        
        # Calculate time range
        if sorted_events:
            start_time = sorted_events[0].timestamp
            end_time = sorted_events[-1].timestamp
            time_range = (end_time - start_time).total_seconds()
            
            if time_range == 0:
                time_range = 1  # Minimum range
            
            # Calculate positions
            timeline_width = max(800, int(time_range * self.zoom_level / 3600))  # 1 hour = 1 pixel at zoom 1
            self.setMinimumWidth(timeline_width + 200)
            
            # Store layout information
            for event in sorted_events:
                time_offset = (event.timestamp - start_time).total_seconds()
                x_pos = int(self.parent_timeline.margin_left + (time_offset / time_range) * timeline_width)
                
                # Store position in event metadata for drawing
                event.metadata['_x_pos'] = x_pos
                event.metadata['_y_pos'] = self.parent_timeline.margin_top + (hash(event.event_type) % 10) * 40
    
    def paintEvent(self, event):
        """Paint the timeline."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Fill background
        painter.fillRect(self.rect(), self.bg_color)
        
        if not self.events:
            painter.setPen(self.text_color)
            painter.drawText(self.rect(), Qt.AlignCenter, "No events to display")
            return
        
        # Draw timeline axis
        self.draw_timeline_axis(painter)
        
        # Draw events
        self.draw_events(painter)
        
        # Draw time labels
        self.draw_time_labels(painter)
        
    def draw_timeline_axis(self, painter: QPainter):
        """Draw the main timeline axis."""
        painter.setPen(QPen(self.accent_color, 2))
        
        y_pos = self.parent_timeline.margin_top
        start_x = self.parent_timeline.margin_left
        end_x = self.width() - 50
        
        painter.drawLine(start_x, y_pos, end_x, y_pos)
        
        # Draw tick marks
        painter.setPen(QPen(self.grid_color, 1))
        num_ticks = 10
        tick_spacing = (end_x - start_x) / num_ticks
        
        for i in range(num_ticks + 1):
            x_pos = start_x + i * tick_spacing
            painter.drawLine(int(x_pos), y_pos - 5, int(x_pos), y_pos + 5)
            
    def draw_events(self, painter: QPainter):
        """Draw the events on the timeline."""
        font = QFont("Arial", 8)
        painter.setFont(font)
        
        for event in self.events:
            x_pos = event.metadata.get('_x_pos', 0)
            y_pos = event.metadata.get('_y_pos', 0)
            
            # Draw event marker
            color = QColor(event.color)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(), 2))
            
            # Size based on importance
            size = 6 + event.importance * 2
            painter.drawEllipse(x_pos - size//2, y_pos - size//2, size, size)
            
            # Draw connecting line to timeline
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.drawLine(x_pos, y_pos + size//2, x_pos, self.parent_timeline.margin_top)
            
            # Draw event title
            painter.setPen(self.text_color)
            text_rect = QRect(x_pos - 50, y_pos + size//2 + 5, 100, 20)
            painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, event.title[:20])
            
    def draw_time_labels(self, painter: QPainter):
        """Draw time labels on the timeline."""
        if not self.events:
            return
        
        sorted_events = sorted(self.events, key=lambda e: e.timestamp)
        start_time = sorted_events[0].timestamp
        end_time = sorted_events[-1].timestamp
        
        painter.setPen(self.text_color)
        font = QFont("Arial", 9)
        painter.setFont(font)
        
        # Draw start and end times
        start_text = start_time.strftime("%H:%M:%S")
        end_text = end_time.strftime("%H:%M:%S")
        
        painter.drawText(self.parent_timeline.margin_left, self.parent_timeline.margin_top - 10, start_text)
        painter.drawText(self.width() - 100, self.parent_timeline.margin_top - 10, end_text)
        
    def mousePressEvent(self, event):
        """Handle mouse clicks to select events."""
        click_x = event.x()
        click_y = event.y()
        
        # Find clicked event
        for timeline_event in self.events:
            x_pos = timeline_event.metadata.get('_x_pos', 0)
            y_pos = timeline_event.metadata.get('_y_pos', 0)
            
            # Check if click is within event bounds
            size = 6 + timeline_event.importance * 2
            if (abs(click_x - x_pos) <= size and abs(click_y - y_pos) <= size):
                self.parent_timeline.on_event_selected(timeline_event)
                break


class MatplotlibTimelineWidget(QWidget):
    """Advanced timeline widget using matplotlib for better visualization."""
    
    def __init__(self, parent=None):
        """Initialize the matplotlib timeline widget."""
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        if not MATPLOTLIB_AVAILABLE:
            self.show_fallback_message()
            return
            
        self.events: List[TimelineEvent] = []
        self.setup_ui()
        
    def show_fallback_message(self):
        """Show a message when matplotlib is not available."""
        layout = QVBoxLayout(self)
        
        message = QLabel("""
        <h3 style='color: #FF5555;'>Advanced Timeline Not Available</h3>
        <p style='color: #E2E8F0;'>
        Matplotlib is required for advanced timeline visualization.<br>
        Please install matplotlib to enable this feature:<br><br>
        <code style='background-color: #334155; padding: 5px;'>pip install matplotlib</code>
        </p>
        """)
        message.setAlignment(Qt.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)
        
    def setup_ui(self):
        """Set up the matplotlib timeline UI."""
        layout = QVBoxLayout(self)
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(12, 8), facecolor='#0F172A')
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color: #0F172A;")
        
        layout.addWidget(self.canvas)
        
        # Control panel
        controls = self.create_controls()
        layout.addWidget(controls)
        
    def create_controls(self) -> QWidget:
        """Create control panel for the matplotlib timeline."""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #475569;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        
        layout = QHBoxLayout(panel)
        
        # View type selection
        self.view_type = QComboBox()
        self.view_type.addItems(["Scatter Plot", "Timeline Bars", "Heatmap", "Gantt Chart"])
        self.view_type.currentTextChanged.connect(self.update_plot)
        
        # Color scheme
        self.color_scheme = QComboBox()
        self.color_scheme.addItems(["Cyberpunk", "Artifact Type", "Importance", "Monochrome"])
        self.color_scheme.currentTextChanged.connect(self.update_plot)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.update_plot)
        
        layout.addWidget(QLabel("View:"))
        layout.addWidget(self.view_type)
        layout.addWidget(QLabel("Colors:"))
        layout.addWidget(self.color_scheme)
        layout.addWidget(refresh_btn)
        layout.addStretch()
        
        return panel
        
    def add_events(self, events: List[TimelineEvent]):
        """Add events to the timeline."""
        self.events.extend(events)
        self.update_plot()
        
    def clear_events(self):
        """Clear all events."""
        self.events.clear()
        self.update_plot()
        
    def update_plot(self):
        """Update the matplotlib plot."""
        if not MATPLOTLIB_AVAILABLE or not self.events:
            return
            
        self.figure.clear()
        
        view_type = self.view_type.currentText()
        
        if view_type == "Scatter Plot":
            self.create_scatter_plot()
        elif view_type == "Timeline Bars":
            self.create_timeline_bars()
        elif view_type == "Heatmap":
            self.create_heatmap()
        elif view_type == "Gantt Chart":
            self.create_gantt_chart()
            
        self.canvas.draw()
        
    def create_scatter_plot(self):
        """Create a scatter plot of events."""
        ax = self.figure.add_subplot(111)
        ax.set_facecolor('#0F172A')
        
        # Prepare data
        timestamps = [event.timestamp for event in self.events]
        artifact_types = list(set(event.artifact_type for event in self.events))
        y_positions = [artifact_types.index(event.artifact_type) for event in self.events]
        colors = [event.color for event in self.events]
        sizes = [event.importance * 20 for event in self.events]
        
        # Create scatter plot
        scatter = ax.scatter(timestamps, y_positions, c=colors, s=sizes, alpha=0.7)
        
        # Customize plot
        ax.set_xlabel('Time', color='#E2E8F0')
        ax.set_ylabel('Artifact Type', color='#E2E8F0')
        ax.set_yticks(range(len(artifact_types)))
        ax.set_yticklabels(artifact_types, color='#E2E8F0')
        ax.tick_params(colors='#E2E8F0')
        ax.grid(True, color='#334155', alpha=0.3)
        
        # Format time axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, color='#E2E8F0')
        
        ax.set_title('Forensic Artifacts Timeline', color='#00FFFF', fontsize=14)
        
    def create_timeline_bars(self):
        """Create a timeline with bars for event duration."""
        ax = self.figure.add_subplot(111)
        ax.set_facecolor('#0F172A')
        
        # Group events by artifact type
        artifact_groups = {}
        for event in self.events:
            if event.artifact_type not in artifact_groups:
                artifact_groups[event.artifact_type] = []
            artifact_groups[event.artifact_type].append(event)
        
        y_pos = 0
        yticks = []
        ylabels = []
        
        for artifact_type, events in artifact_groups.items():
            for event in events:
                # Create bar (assuming 1-hour duration for visualization)
                start_time = event.timestamp
                duration = timedelta(hours=1)
                
                ax.barh(y_pos, duration.total_seconds()/3600, left=start_time, 
                       height=0.8, color=event.color, alpha=0.7)
                
                # Add event title
                ax.text(start_time, y_pos, event.title[:15], 
                       va='center', color='#E2E8F0', fontsize=8)
                
                y_pos += 1
            
            yticks.extend(range(y_pos - len(events), y_pos))
            ylabels.extend([artifact_type] * len(events))
        
        ax.set_yticks(yticks)
        ax.set_yticklabels(ylabels, color='#E2E8F0')
        ax.set_xlabel('Time', color='#E2E8F0')
        ax.tick_params(colors='#E2E8F0')
        ax.grid(True, color='#334155', alpha=0.3)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, color='#E2E8F0')
        
        ax.set_title('Forensic Artifacts Gantt Chart', color='#00FFFF', fontsize=14)
        
    def create_heatmap(self):
        """Create a heatmap showing event density over time."""
        if len(self.events) < 2:
            return
            
        ax = self.figure.add_subplot(111)
        
        # Create time bins (hourly)
        timestamps = [event.timestamp for event in self.events]
        min_time = min(timestamps)
        max_time = max(timestamps)
        
        time_range = (max_time - min_time).total_seconds() / 3600  # hours
        num_bins = max(1, int(time_range))
        
        # Create 2D histogram data
        artifact_types = list(set(event.artifact_type for event in self.events))
        data = np.zeros((len(artifact_types), num_bins))
        
        for event in self.events:
            time_bin = int((event.timestamp - min_time).total_seconds() / 3600 / (time_range / num_bins))
            artifact_idx = artifact_types.index(event.artifact_type)
            
            if 0 <= time_bin < num_bins:
                data[artifact_idx, time_bin] += event.importance
        
        # Create heatmap
        im = ax.imshow(data, cmap='plasma', aspect='auto', interpolation='nearest')
        
        # Customize
        ax.set_yticks(range(len(artifact_types)))
        ax.set_yticklabels(artifact_types, color='#E2E8F0')
        ax.set_xlabel('Time (Hours)', color='#E2E8F0')
        ax.set_title('Event Density Heatmap', color='#00FFFF', fontsize=14)
        ax.tick_params(colors='#E2E8F0')
        
        # Add colorbar
        cbar = self.figure.colorbar(im, ax=ax)
        cbar.ax.tick_params(colors='#E2E8F0')
        cbar.set_label('Event Importance', color='#E2E8F0')
        
    def create_gantt_chart(self):
        """Create a Gantt chart view."""
        self.create_timeline_bars()  # Same as timeline bars for now


# Utility functions for creating timeline events from database data

def create_timeline_events_from_database(
    db_path: str,
    artifact_type: str,
    title_field: str = "name",
    timestamp_field: str = "timestamp",
    description_field: str = "description"
) -> List[TimelineEvent]:
    """Create timeline events from database data.
    
    Args:
        db_path: Path to SQLite database
        artifact_type: Type of artifact
        title_field: Field to use for event title
        timestamp_field: Field containing timestamp
        description_field: Field to use for description
        
    Returns:
        List of TimelineEvent objects
    """
    events = []
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        for table_row in tables:
            table_name = table_row[0]
            
            # Check if required fields exist
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            
            if timestamp_field not in columns:
                continue
                
            # Query data
            query = f"SELECT * FROM {table_name} WHERE {timestamp_field} IS NOT NULL"
            cursor.execute(query)
            rows = cursor.fetchall()
            
            for row in rows:
                record = dict(zip(columns, row))
                
                try:
                    # Parse timestamp
                    timestamp_str = record[timestamp_field]
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    
                    # Create event
                    event = TimelineEvent(
                        timestamp=timestamp,
                        event_type=table_name,
                        title=str(record.get(title_field, f"{artifact_type} Event")),
                        description=str(record.get(description_field, "No description")),
                        artifact_type=artifact_type,
                        metadata=record,
                        importance=3,  # Default importance
                        color="#3B82F6"  # Default color
                    )
                    
                    events.append(event)
                    
                except Exception as e:
                    logging.getLogger(__name__).warning(f"Error processing timeline event: {e}")
                    continue
        
        conn.close()
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Error creating timeline events: {e}")
    
    return events


def assign_event_colors_by_type(events: List[TimelineEvent]) -> List[TimelineEvent]:
    """Assign colors to events based on their type."""
    color_map = {
        "prefetch": "#FF6B6B",
        "registry": "#4ECDC4",
        "logs": "#45B7D1",
        "lnk": "#96CEB4",
        "jumplist": "#FFEAA7",
        "amcache": "#DDA0DD",
        "shimcache": "#98D8C8"
    }
    
    for event in events:
        artifact_lower = event.artifact_type.lower()
        for key, color in color_map.items():
            if key in artifact_lower:
                event.color = color
                break
        else:
            event.color = "#94A3B8"  # Default gray
    
    return events