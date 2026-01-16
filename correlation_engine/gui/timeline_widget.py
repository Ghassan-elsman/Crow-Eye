"""
Timeline Widget

A reusable timeline visualization widget for displaying temporal events.
Can be used in Identity and Anchor detail dialogs.

Implements Task 11: Create Timeline Widget
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsLineItem, QFileDialog, QMessageBox
)
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPen, QBrush, QColor, QFont, QPainter
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from correlation_engine.engine.data_structures import EvidenceRow


class TimelineCanvas(QGraphicsView):
    """
    Canvas for drawing timeline visualization.
    
    Implements Task 11.2: Timeline rendering
    """
    
    def __init__(self, parent=None):
        """Initialize timeline canvas."""
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        
        # Timeline parameters
        self.margin = 50
        self.timeline_height = 400
        self.event_height = 30
        self.zoom_level = 1.0
        
        # Style
        self.setStyleSheet("""
            QGraphicsView {
                background-color: #1e1e1e;
                border: 1px solid #3a3a3a;
            }
        """)
    
    def draw_timeline(self, evidence_list: List[EvidenceRow]):
        """
        Draw timeline with events.
        
        Args:
            evidence_list: List of evidence to plot
        """
        self.scene.clear()
        
        if not evidence_list:
            # Show "No data" message
            text = self.scene.addText("No timestamped evidence to display")
            text.setDefaultTextColor(QColor(150, 150, 150))
            text.setPos(100, 100)
            return
        
        # Filter timestamped evidence
        timestamped = [e for e in evidence_list if e.timestamp]
        if not timestamped:
            text = self.scene.addText("No timestamped evidence to display")
            text.setDefaultTextColor(QColor(150, 150, 150))
            text.setPos(100, 100)
            return
        
        # Sort by timestamp
        timestamped.sort(key=lambda e: e.timestamp)
        
        # Calculate time range
        start_time = timestamped[0].timestamp
        end_time = timestamped[-1].timestamp
        duration = (end_time - start_time).total_seconds()
        
        if duration == 0:
            duration = 1  # Avoid division by zero
        
        # Calculate canvas dimensions
        canvas_width = 800
        timeline_width = canvas_width - 2 * self.margin
        
        # Draw timeline axis
        self._draw_axis(start_time, end_time, timeline_width)
        
        # Draw events
        for i, evidence in enumerate(timestamped):
            # Calculate position
            time_offset = (evidence.timestamp - start_time).total_seconds()
            x_pos = self.margin + (time_offset / duration) * timeline_width
            y_pos = self.margin + 50 + (i % 10) * 40  # Stagger vertically
            
            # Draw event marker
            self._draw_event(evidence, x_pos, y_pos)
    
    def _draw_axis(self, start_time: datetime, end_time: datetime, width: float):
        """Draw timeline axis with time labels."""
        y_pos = self.margin + 30
        
        # Draw main line
        line = QGraphicsLineItem(self.margin, y_pos, self.margin + width, y_pos)
        line.setPen(QPen(QColor(100, 100, 100), 2))
        self.scene.addItem(line)
        
        # Draw start time label
        start_text = self.scene.addText(start_time.strftime("%H:%M:%S"))
        start_text.setDefaultTextColor(QColor(200, 200, 200))
        start_text.setPos(self.margin - 30, y_pos + 10)
        
        # Draw end time label
        end_text = self.scene.addText(end_time.strftime("%H:%M:%S"))
        end_text.setDefaultTextColor(QColor(200, 200, 200))
        end_text.setPos(self.margin + width - 30, y_pos + 10)
        
        # Draw middle time label
        mid_time = start_time + (end_time - start_time) / 2
        mid_text = self.scene.addText(mid_time.strftime("%H:%M:%S"))
        mid_text.setDefaultTextColor(QColor(200, 200, 200))
        mid_text.setPos(self.margin + width / 2 - 30, y_pos + 10)
    
    def _draw_event(self, evidence: EvidenceRow, x: float, y: float):
        """Draw event marker on timeline."""
        # Color by role
        if evidence.role == "primary":
            color = QColor(255, 100, 100)
        elif evidence.role == "secondary":
            color = QColor(255, 255, 100)
        else:
            color = QColor(100, 255, 100)
        
        # Draw marker circle
        marker = self.scene.addEllipse(x - 5, y - 5, 10, 10, 
                                      QPen(color, 2), 
                                      QBrush(color))
        
        # Draw label
        label_text = f"{evidence.artifact}"
        if evidence.semantic_data and 'meaning' in evidence.semantic_data:
            label_text += f"\n{evidence.semantic_data['meaning']}"
        
        label = self.scene.addText(label_text)
        label.setDefaultTextColor(color)
        font = QFont()
        font.setPointSize(8)
        label.setFont(font)
        label.setPos(x + 10, y - 10)
    
    def zoom_in(self):
        """Zoom in on timeline."""
        self.zoom_level *= 1.2
        self.scale(1.2, 1.2)
    
    def zoom_out(self):
        """Zoom out on timeline."""
        self.zoom_level /= 1.2
        self.scale(1/1.2, 1/1.2)
    
    def reset_zoom(self):
        """Reset zoom to default."""
        self.resetTransform()
        self.zoom_level = 1.0


class TimelineWidget(QWidget):
    """
    Complete timeline widget with controls.
    
    Implements Task 11: Timeline Widget
    """
    
    def __init__(self, parent=None):
        """Initialize timeline widget."""
        super().__init__(parent)
        self.evidence_list: List[EvidenceRow] = []
        self.setup_ui()
    
    def setup_ui(self):
        """Setup widget UI."""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("<h3>Timeline Visualization</h3>")
        layout.addWidget(title)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        zoom_in_btn = QPushButton("Zoom In")
        zoom_in_btn.clicked.connect(self.zoom_in)
        controls_layout.addWidget(zoom_in_btn)
        
        zoom_out_btn = QPushButton("Zoom Out")
        zoom_out_btn.clicked.connect(self.zoom_out)
        controls_layout.addWidget(zoom_out_btn)
        
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_view)
        controls_layout.addWidget(reset_btn)
        
        export_btn = QPushButton("Export Image")
        export_btn.clicked.connect(self.export_image)
        controls_layout.addWidget(export_btn)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Timeline canvas
        self.canvas = TimelineCanvas()
        layout.addWidget(self.canvas)
        
        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("Legend:"))
        
        primary_label = QLabel("● Primary")
        primary_label.setStyleSheet("color: #ff6464;")
        legend_layout.addWidget(primary_label)
        
        secondary_label = QLabel("● Secondary")
        secondary_label.setStyleSheet("color: #ffff64;")
        legend_layout.addWidget(secondary_label)
        
        supporting_label = QLabel("● Supporting")
        supporting_label.setStyleSheet("color: #64ff64;")
        legend_layout.addWidget(supporting_label)
        
        legend_layout.addStretch()
        layout.addLayout(legend_layout)
    
    def set_evidence(self, evidence_list: List[EvidenceRow]):
        """
        Set evidence to display on timeline.
        
        Args:
            evidence_list: List of evidence to plot
        """
        self.evidence_list = evidence_list
        self.canvas.draw_timeline(evidence_list)
    
    def zoom_in(self):
        """Zoom in on timeline."""
        self.canvas.zoom_in()
    
    def zoom_out(self):
        """Zoom out on timeline."""
        self.canvas.zoom_out()
    
    def reset_view(self):
        """Reset view to default."""
        self.canvas.reset_zoom()
        self.canvas.draw_timeline(self.evidence_list)
    
    def export_image(self):
        """Export timeline as image."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Timeline",
            "timeline.png",
            "PNG Files (*.png);;All Files (*)"
        )
        
        if filename:
            try:
                # Render scene to image
                from PyQt5.QtGui import QImage, QPainter
                
                rect = self.canvas.scene.sceneRect()
                image = QImage(int(rect.width()), int(rect.height()), 
                             QImage.Format_ARGB32)
                image.fill(Qt.black)
                
                painter = QPainter(image)
                self.canvas.scene.render(painter)
                painter.end()
                
                image.save(filename)
                QMessageBox.information(self, "Success", f"Timeline exported to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export: {str(e)}")
