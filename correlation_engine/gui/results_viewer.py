"""
Results Viewer
Display, filter, and analyze correlation results.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGroupBox, QFormLayout,
    QPushButton, QLineEdit, QSlider, QCheckBox, QComboBox,
    QSplitter, QTextEdit, QMessageBox, QFileDialog, QDateTimeEdit,
    QFrame, QGridLayout, QProgressDialog, QToolTip, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime, QRect, QPoint
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen, QFont, QFontMetrics, QPalette

# Matplotlib imports for chart rendering (optional)
try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
    print("[Info] matplotlib Qt5Agg backend loaded successfully")
except ImportError as e:
    MATPLOTLIB_AVAILABLE = False
    print(f"[Info] matplotlib not available, using PyQt5 native charts")
except Exception as e:
    MATPLOTLIB_AVAILABLE = False
    print(f"[Info] matplotlib not available, using PyQt5 native charts")


def format_time_duration(seconds: float) -> str:
    """Format time duration into human-readable format (seconds, minutes, hours)"""
    try:
        if seconds == 0:
            return "0s"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            if secs > 0:
                return f"{hours}h {minutes}m {secs}s"
            else:
                return f"{hours}h {minutes}m"
    except:
        return f"{seconds:.1f}s"


class PyQt5BarChart(QWidget):
    """
    A simple bar chart widget using pure PyQt5.
    No external dependencies required.
    """
    
    # Color palette for bars
    COLORS = [
        QColor("#2196F3"),  # Blue
        QColor("#4CAF50"),  # Green
        QColor("#FF9800"),  # Orange
        QColor("#9C27B0"),  # Purple
        QColor("#F44336"),  # Red
        QColor("#00BCD4"),  # Cyan
        QColor("#FFEB3B"),  # Yellow
        QColor("#795548"),  # Brown
        QColor("#607D8B"),  # Blue Grey
        QColor("#E91E63"),  # Pink
        QColor("#3F51B5"),  # Indigo
        QColor("#009688"),  # Teal
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = {}  # {label: value}
        self.title = "Bar Chart"
        self.ylabel = "Count"
        self.setMinimumHeight(250)
        self.setMinimumWidth(400)
        self.hovered_bar = -1
        self.setMouseTracking(True)
        
        # Store bar rectangles for hover detection
        self.bar_rects = []
        
    def set_data(self, data: Dict[str, float], title: str = "Bar Chart", ylabel: str = "Count"):
        """Set chart data and labels."""
        self.data = data
        self.title = title
        self.ylabel = ylabel
        self.update()
    
    def paintEvent(self, event):
        """Draw the bar chart."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        
        # Margins
        left_margin = 80
        right_margin = 20
        top_margin = 40
        bottom_margin = 80
        
        # Chart area
        chart_width = width - left_margin - right_margin
        chart_height = height - top_margin - bottom_margin
        
        if not self.data or chart_width <= 0 or chart_height <= 0:
            painter.drawText(self.rect(), Qt.AlignCenter, "No data available")
            return
        
        # Calculate max value for scaling
        max_value = max(self.data.values()) if self.data.values() else 1
        if max_value == 0:
            max_value = 1
        
        # Draw background
        painter.fillRect(self.rect(), QColor("#1a1a2e"))
        
        # Draw title
        painter.setPen(QPen(QColor("#ffffff")))
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRect(0, 5, width, 30), Qt.AlignCenter, self.title)
        
        # Draw Y-axis label
        painter.save()
        painter.translate(15, height // 2)
        painter.rotate(-90)
        label_font = QFont()
        label_font.setPointSize(9)
        painter.setFont(label_font)
        painter.drawText(QRect(-50, -10, 100, 20), Qt.AlignCenter, self.ylabel)
        painter.restore()
        
        # Draw Y-axis grid lines and labels
        num_grid_lines = 5
        painter.setPen(QPen(QColor("#444444")))
        small_font = QFont()
        small_font.setPointSize(8)
        painter.setFont(small_font)
        
        for i in range(num_grid_lines + 1):
            y = top_margin + chart_height - (i * chart_height // num_grid_lines)
            value = int(max_value * i / num_grid_lines)
            
            # Grid line
            painter.setPen(QPen(QColor("#333333")))
            painter.drawLine(left_margin, y, width - right_margin, y)
            
            # Y-axis label
            painter.setPen(QPen(QColor("#aaaaaa")))
            painter.drawText(QRect(5, y - 10, left_margin - 10, 20), 
                           Qt.AlignRight | Qt.AlignVCenter, f"{value:,}")
        
        # Calculate bar dimensions
        num_bars = len(self.data)
        if num_bars == 0:
            return
            
        bar_spacing = 10
        total_spacing = bar_spacing * (num_bars + 1)
        bar_width = max(20, (chart_width - total_spacing) // num_bars)
        
        # Clear bar rectangles
        self.bar_rects = []
        
        # Draw bars
        for i, (label, value) in enumerate(self.data.items()):
            # Calculate bar position and size
            x = left_margin + bar_spacing + i * (bar_width + bar_spacing)
            bar_height = int((value / max_value) * chart_height) if max_value > 0 else 0
            y = top_margin + chart_height - bar_height
            
            # Store bar rectangle for hover detection
            bar_rect = QRect(x, y, bar_width, bar_height)
            self.bar_rects.append((bar_rect, label, value))
            
            # Get color
            color = self.COLORS[i % len(self.COLORS)]
            
            # Highlight hovered bar
            if i == self.hovered_bar:
                color = color.lighter(130)
            
            # Draw bar
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(120), 1))
            painter.drawRect(bar_rect)
            
            # Draw value on top of bar
            painter.setPen(QPen(QColor("#ffffff")))
            value_text = f"{int(value):,}"
            painter.drawText(QRect(x, y - 20, bar_width, 20), 
                           Qt.AlignCenter, value_text)
            
            # Draw label below bar (rotated if needed)
            painter.save()
            label_x = x + bar_width // 2
            label_y = top_margin + chart_height + 5
            
            # Truncate long labels
            display_label = label if len(label) <= 12 else label[:10] + "..."
            
            painter.translate(label_x, label_y)
            painter.rotate(45)
            painter.setPen(QPen(QColor("#cccccc")))
            painter.drawText(QRect(0, 0, 100, 20), Qt.AlignLeft, display_label)
            painter.restore()
        
        # Draw axes
        painter.setPen(QPen(QColor("#666666"), 2))
        # Y-axis
        painter.drawLine(left_margin, top_margin, left_margin, top_margin + chart_height)
        # X-axis
        painter.drawLine(left_margin, top_margin + chart_height, 
                        width - right_margin, top_margin + chart_height)
    
    def mouseMoveEvent(self, event):
        """Handle mouse movement for hover effects."""
        pos = event.pos()
        new_hovered = -1
        
        for i, (rect, label, value) in enumerate(self.bar_rects):
            if rect.contains(pos):
                new_hovered = i
                # Show tooltip
                total = sum(self.data.values())
                percentage = (value / total * 100) if total > 0 else 0
                QToolTip.showText(
                    self.mapToGlobal(pos),
                    f"{label}\nCount: {int(value):,}\nPercentage: {percentage:.1f}%"
                )
                break
        
        if new_hovered != self.hovered_bar:
            self.hovered_bar = new_hovered
            self.update()
    
    def leaveEvent(self, event):
        """Handle mouse leaving widget."""
        self.hovered_bar = -1
        self.update()


class PyQt5PieChart(QWidget):
    """
    A simple pie chart widget using pure PyQt5.
    No external dependencies required.
    """
    
    # Color palette for slices
    COLORS = [
        QColor("#2196F3"),  # Blue
        QColor("#4CAF50"),  # Green
        QColor("#FF9800"),  # Orange
        QColor("#9C27B0"),  # Purple
        QColor("#F44336"),  # Red
        QColor("#00BCD4"),  # Cyan
        QColor("#FFEB3B"),  # Yellow
        QColor("#795548"),  # Brown
        QColor("#607D8B"),  # Blue Grey
        QColor("#E91E63"),  # Pink
        QColor("#3F51B5"),  # Indigo
        QColor("#009688"),  # Teal
    ]
    
    def __init__(self, parent=None, show_legend=True):
        super().__init__(parent)
        self.data = {}  # {label: value}
        self.title = "Pie Chart"
        self.setMinimumHeight(200)
        self.setMinimumWidth(200)
        self.hovered_slice = -1
        self.setMouseTracking(True)
        self.slice_angles = []  # Store slice info for hover detection
        self.show_legend = show_legend  # Control whether to show built-in legend
        
    def set_data(self, data: Dict[str, float], title: str = "Pie Chart"):
        """Set chart data and labels."""
        self.data = data
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        """Draw the pie chart."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Draw background
        painter.fillRect(self.rect(), QColor("#1a1a2e"))
        
        if not self.data:
            painter.setPen(QPen(QColor("#ffffff")))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data available")
            return
        
        # Draw title
        painter.setPen(QPen(QColor("#ffffff")))
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRect(0, 5, width, 25), Qt.AlignCenter, self.title)
        
        # Calculate pie dimensions
        top_margin = 30
        # Reserve space for legend on the right - more space if we have many items
        legend_items_count = len(self.data)
        use_two_columns = legend_items_count > 8
        legend_width = 400 if use_two_columns else 200  # Double width for two columns
        pie_size = min(width - legend_width - 30, height - top_margin - 10)
        pie_x = 10
        pie_y = top_margin + (height - top_margin - pie_size) // 2
        
        # Calculate total
        total = sum(self.data.values())
        if total == 0:
            return
        
        # Clear slice angles
        self.slice_angles = []
        
        # Draw pie slices
        start_angle = 90 * 16  # Start from top (in 1/16th degrees)
        pie_rect = QRect(pie_x, pie_y, pie_size, pie_size)
        
        for i, (label, value) in enumerate(self.data.items()):
            span_angle = int((value / total) * 360 * 16)
            
            color = self.COLORS[i % len(self.COLORS)]
            if i == self.hovered_slice:
                color = color.lighter(130)
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor("#1a1a2e"), 1))
            painter.drawPie(pie_rect, start_angle, span_angle)
            
            # Store slice info for hover
            self.slice_angles.append((start_angle, span_angle, label, value))
            
            start_angle += span_angle
        
        # Draw legend as text labels next to pie chart (always visible)
        if self.show_legend:
            # Legend positioned to the right of pie chart
            legend_x = pie_x + pie_size + 20
            legend_y = top_margin + 10
            
            # Draw "Feathers:" title
            painter.setPen(QPen(QColor("#00FFFF")))
            title_font = QFont()
            title_font.setPointSize(8)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(legend_x, legend_y, "Feathers:")
            legend_y += 20
            
            # Draw legend items
            small_font = QFont()
            small_font.setPointSize(7)
            painter.setFont(small_font)
            
            legend_items = list(self.data.items())
            
            # Determine if we need two columns (more than 8 items)
            use_two_columns = len(legend_items) > 8
            items_per_column = (len(legend_items) + 1) // 2 if use_two_columns else len(legend_items)
            column_width = 200  # Width of each column
            
            for i, (label, value) in enumerate(legend_items):
                color = self.COLORS[i % len(self.COLORS)]
                
                # Calculate position based on column
                if use_two_columns and i >= items_per_column:
                    # Second column
                    col_x = legend_x + column_width
                    row_index = i - items_per_column
                else:
                    # First column
                    col_x = legend_x
                    row_index = i
                
                # Color box
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawRect(col_x, legend_y + row_index * 18, 12, 12)
                
                # Label with color
                painter.setPen(QPen(color))
                display_label = label if len(label) <= 18 else label[:16] + ".."
                painter.drawText(col_x + 18, legend_y + row_index * 18 + 10, display_label)
                
                # Count and percentage
                percentage = (value / total * 100) if total > 0 else 0
                stats_text = f"{int(value):,} ({percentage:.0f}%)"
                painter.setPen(QPen(color.lighter(120)))
                painter.drawText(col_x + 120, legend_y + row_index * 18 + 10, stats_text)
    
    def mouseMoveEvent(self, event):
        """Handle mouse movement for hover effects."""
        if not self.slice_angles:
            return
            
        pos = event.pos()
        width = self.width()
        height = self.height()
        
        # Calculate pie center
        top_margin = 30
        legend_width = min(120, width // 3)
        pie_size = min(width - legend_width - 20, height - top_margin - 10)
        center_x = 10 + pie_size // 2
        center_y = top_margin + (height - top_margin - pie_size) // 2 + pie_size // 2
        radius = pie_size // 2
        
        # Check if mouse is within pie
        dx = pos.x() - center_x
        dy = pos.y() - center_y
        distance = (dx * dx + dy * dy) ** 0.5
        
        new_hovered = -1
        if distance <= radius:
            # Calculate angle from center
            import math
            angle = math.degrees(math.atan2(-dy, dx))  # Negative dy because y increases downward
            if angle < 0:
                angle += 360
            angle = (90 - angle) % 360  # Convert to start from top
            angle_16 = angle * 16
            
            # Find which slice
            for i, (start, span, label, value) in enumerate(self.slice_angles):
                start_deg = (start / 16) % 360
                span_deg = span / 16
                end_deg = (start_deg + span_deg) % 360
                
                # Check if angle is within this slice
                if span_deg > 0:
                    if start_deg + span_deg <= 360:
                        if start_deg <= angle < start_deg + span_deg:
                            new_hovered = i
                            break
                    else:
                        if angle >= start_deg or angle < end_deg:
                            new_hovered = i
                            break
        
        if new_hovered != self.hovered_slice:
            self.hovered_slice = new_hovered
            self.update()
            
        if new_hovered >= 0:
            _, _, label, value = self.slice_angles[new_hovered]
            total = sum(self.data.values())
            percentage = (value / total * 100) if total > 0 else 0
            QToolTip.showText(
                self.mapToGlobal(pos),
                f"{label}\nRecords: {int(value):,}\nPercentage: {percentage:.1f}%"
            )
    
    def leaveEvent(self, event):
        """Handle mouse leaving widget."""
        self.hovered_slice = -1
        self.update()


class PieChartWithBreakdown(QWidget):
    """
    A widget that combines a pie chart with a detailed breakdown table.
    When there are 8+ categories, the breakdown table is shown next to the pie chart.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = {}
        self.title = "Pie Chart"
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI layout."""
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(10)
        
        # Create pie chart without built-in legend
        self.pie_chart = PyQt5PieChart(show_legend=False)
        
        # Create legend widget (grid layout with colored indicators)
        self.legend_widget = QWidget()
        self.legend_main_layout = QVBoxLayout(self.legend_widget)
        self.legend_main_layout.setContentsMargins(5, 5, 5, 5)
        self.legend_main_layout.setSpacing(3)
        
        # Add title for legend
        legend_title = QLabel("Feathers:")
        legend_title.setStyleSheet("color: #00FFFF; font-size: 8pt; font-weight: bold;")
        self.legend_main_layout.addWidget(legend_title)
        
        # Scroll area for legend items
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setWidgetResizable(True)
        self.legend_scroll.setFrameShape(QFrame.NoFrame)
        self.legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.legend_scroll.setMinimumWidth(180)
        self.legend_scroll.setMaximumWidth(400)  # Wider to accommodate multiple columns
        self.legend_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #1a1a2e;
                border: 1px solid #334155;
                border-radius: 4px;
            }
            QScrollBar:vertical {
                background-color: #1E293B;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #64748B;
            }
        """)
        
        self.legend_content = QWidget()
        self.legend_items_layout = QGridLayout(self.legend_content)  # Changed to QGridLayout
        self.legend_items_layout.setContentsMargins(5, 5, 5, 5)
        self.legend_items_layout.setSpacing(4)
        self.legend_items_layout.setColumnStretch(0, 1)
        self.legend_items_layout.setColumnStretch(1, 1)
        
        self.legend_scroll.setWidget(self.legend_content)
        self.legend_main_layout.addWidget(self.legend_scroll)
        
        self.legend_widget.setStyleSheet("""
            QWidget {
                background-color: #1a1a2e;
            }
        """)
        self.legend_widget.hide()
        
        # Add widgets to layout
        self.main_layout.addWidget(self.pie_chart, stretch=1)
        self.main_layout.addWidget(self.legend_widget, stretch=0)
    
    def set_data(self, data: Dict[str, float], title: str = "Pie Chart"):
        """Set chart data and update display."""
        self.data = data
        self.title = title
        
        # Update pie chart
        self.pie_chart.set_data(data, title)
        
        # Show legend if 8+ categories
        if len(data) >= 8:
            self._populate_legend()
            self.legend_widget.show()
        else:
            self.legend_widget.hide()
    
    def _populate_legend(self):
        """Populate the legend with colored indicators in a grid layout."""
        # Clear existing legend items
        while self.legend_items_layout.count() > 0:
            item = self.legend_items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Calculate total
        total = sum(self.data.values())
        
        # Sort by count descending
        sorted_items = sorted(self.data.items(), key=lambda x: x[1], reverse=True)
        
        # Get color palette from PyQt5PieChart
        colors = PyQt5PieChart.COLORS
        
        # Determine number of columns based on item count
        # If more than 8 items, use 2 columns; otherwise use 1 column
        num_items = len(sorted_items)
        num_columns = 2 if num_items > 8 else 1
        items_per_column = (num_items + num_columns - 1) // num_columns  # Ceiling division
        
        # Create legend items in grid layout
        for idx, (feather_name, count) in enumerate(sorted_items):
            percentage = (count / total * 100) if total > 0 else 0
            
            # Get color for this item (same as pie chart)
            color = colors[idx % len(colors)]
            
            # Calculate grid position
            if num_columns == 2:
                # Fill first column, then second column
                col = idx // items_per_column
                row = idx % items_per_column
            else:
                # Single column
                row = idx
                col = 0
            
            # Create horizontal layout for each legend item
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(6)
            
            # Color indicator (square box)
            color_box = QLabel()
            color_box.setFixedSize(12, 12)
            color_box.setStyleSheet(f"""
                QLabel {{
                    background-color: {color.name()};
                    border: 1px solid #334155;
                    border-radius: 2px;
                }}
            """)
            item_layout.addWidget(color_box)
            
            # Feather name and stats
            text_label = QLabel(f"{feather_name}")
            text_label.setStyleSheet(f"color: {color.name()}; font-size: 7pt; font-weight: bold;")
            text_label.setWordWrap(False)
            text_label.setToolTip(f"{feather_name}\nRecords: {int(count):,}\nPercentage: {percentage:.1f}%")
            item_layout.addWidget(text_label, stretch=1)
            
            # Count
            count_label = QLabel(f"{int(count):,}")
            count_label.setStyleSheet(f"color: {color.name()}; font-size: 7pt;")
            count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_layout.addWidget(count_label)
            
            # Percentage
            pct_label = QLabel(f"({percentage:.0f}%)")
            pct_label.setStyleSheet(f"color: {color.lighter(120).name()}; font-size: 6pt;")
            pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_layout.addWidget(pct_label)
            
            # Add to grid layout
            self.legend_items_layout.addWidget(item_widget, row, col)
    
    def setMinimumHeight(self, height: int):
        """Set minimum height for the widget."""
        super().setMinimumHeight(height)
        self.pie_chart.setMinimumHeight(height)
        self.legend_widget.setMinimumHeight(height)


from .ui_styling import CorrelationEngineStyles


from ..engine.correlation_result import CorrelationResult, CorrelationMatch
from .scoring_breakdown_widget import ScoringBreakdownWidget
from .results_tab_widget import ResultsTabWidget
from .results_exporter import show_export_dialog, export_results_with_progress


class LoadingProgressDialog(QProgressDialog):
    """Helper class for showing loading progress with convenience methods - Crow Eye styled."""
    
    def __init__(self, title: str, parent=None):
        super().__init__(title, "Cancel", 0, 100, parent)
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumDuration(0)  # Show immediately
        self.setAutoClose(True)
        self.setAutoReset(True)
        self.setWindowTitle("Loading Results")
        self.setMinimumWidth(350)
        self.setMinimumHeight(120)
        
        # Apply Crow Eye dark theme styling
        self.setStyleSheet("""
            QProgressDialog {
                background-color: #0B1220;
                border: 2px solid #00FFFF;
                border-radius: 8px;
            }
            QProgressDialog QLabel {
                color: #E2E8F0;
                font-size: 10pt;
                padding: 8px;
            }
            QProgressBar {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                text-align: center;
                color: #E2E8F0;
                font-size: 9pt;
                font-weight: bold;
                min-height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00FFFF, stop:0.5 #10B981, stop:1 #00FFFF);
                border-radius: 3px;
            }
            QPushButton {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 9pt;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #00FFFF;
                color: #00FFFF;
            }
            QPushButton:pressed {
                background-color: #0F172A;
            }
        """)
    
    def update_progress(self, current: int, total: int, message: str = ""):
        """Update progress bar and message."""
        if total > 0:
            percentage = int((current / total) * 100)
            self.setValue(percentage)
        
        if message:
            self.setLabelText(f"{message}\n{current:,}/{total:,} items")
        
        # Process events to keep UI responsive
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()


class ResultsTableWidget(QTableWidget):
    """Table widget for displaying correlation matches"""
    
    match_selected = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.all_matches: List[CorrelationMatch] = []
        self.filtered_matches: List[CorrelationMatch] = []
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize table"""
        # Set columns - added Interpretation column for weighted scoring
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels([
            "Match ID", "Timestamp", "Score", "Interpretation",
            "Feather Count", "Time Spread (s)", "Application", "File Path"
        ])
        
        # Configure table
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSortingEnabled(True)
        
        # Resize columns
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        
        # Connect selection
        self.itemSelectionChanged.connect(self._on_selection_changed)
    
    def populate_results(self, matches: List[CorrelationMatch]):
        """Populate table with matches"""
        self.all_matches = matches
        self.filtered_matches = matches.copy()
        self._update_table()
    
    def _update_table(self):
        """Update table display"""
        self.setSortingEnabled(False)
        self.setRowCount(0)
        
        for match in self.filtered_matches:
            row = self.rowCount()
            self.insertRow(row)
            
            # Match ID
            self.setItem(row, 0, QTableWidgetItem(match.match_id[:8]))
            
            # Timestamp
            self.setItem(row, 1, QTableWidgetItem(match.timestamp))
            
            # Score - check if weighted scoring is used
            if match.weighted_score and isinstance(match.weighted_score, dict):
                score_value = match.weighted_score.get('score', match.match_score)
                score_item = QTableWidgetItem(f"{score_value:.2f}")
                score_item.setData(Qt.UserRole, score_value)
                
                # Color code based on interpretation
                interpretation = match.weighted_score.get('interpretation', '')
                if 'Confirmed' in interpretation:
                    score_item.setForeground(QColor(CorrelationEngineStyles.SCORE_CONFIRMED))  # Green
                elif 'Probable' in interpretation or 'Likely' in interpretation:
                    score_item.setForeground(QColor(CorrelationEngineStyles.SCORE_PROBABLE))  # Orange
                elif 'Weak' in interpretation or 'Insufficient' in interpretation:
                    score_item.setForeground(QColor(CorrelationEngineStyles.SCORE_WEAK))  # Red
            else:
                score_item = QTableWidgetItem(f"{match.match_score:.2f}")
                score_item.setData(Qt.UserRole, match.match_score)
            
            self.setItem(row, 2, score_item)
            
            # Interpretation (for weighted scoring)
            if match.weighted_score and isinstance(match.weighted_score, dict):
                interpretation = match.weighted_score.get('interpretation', '-')
                interp_item = QTableWidgetItem(interpretation)
                # Apply same color coding
                if 'Confirmed' in interpretation:
                    interp_item.setForeground(QColor(CorrelationEngineStyles.SCORE_CONFIRMED))
                elif 'Probable' in interpretation or 'Likely' in interpretation:
                    interp_item.setForeground(QColor(CorrelationEngineStyles.SCORE_PROBABLE))
                elif 'Weak' in interpretation or 'Insufficient' in interpretation:
                    interp_item.setForeground(QColor(CorrelationEngineStyles.SCORE_WEAK))
                self.setItem(row, 3, interp_item)
            else:
                self.setItem(row, 3, QTableWidgetItem('-'))
            
            # Feather count
            count_item = QTableWidgetItem(str(match.feather_count))
            count_item.setData(Qt.UserRole, match.feather_count)
            self.setItem(row, 4, count_item)
            
            # Time spread
            spread_item = QTableWidgetItem(f"{match.time_spread_seconds:.1f}")
            spread_item.setData(Qt.UserRole, match.time_spread_seconds)
            self.setItem(row, 5, spread_item)
            
            # Application
            app = match.matched_application or "-"
            self.setItem(row, 6, QTableWidgetItem(app))
            
            # File path
            path = match.matched_file_path or "-"
            self.setItem(row, 7, QTableWidgetItem(path))
            
            # Store full match data
            self.item(row, 0).setData(Qt.UserRole + 1, match)
        
        self.setSortingEnabled(True)
    
    def apply_filters(self, filters: Dict[str, Any]):
        """Apply filter criteria"""
        self.filtered_matches = []
        
        for match in self.all_matches:
            # Application filter
            if filters.get('application'):
                if not match.matched_application:
                    continue
                if filters['application'].lower() not in match.matched_application.lower():
                    continue
            
            # File path filter
            if filters.get('file_path'):
                if not match.matched_file_path:
                    continue
                if filters['file_path'].lower() not in match.matched_file_path.lower():
                    continue
            
            # Score range filter
            if 'score_min' in filters and match.match_score < filters['score_min']:
                continue
            if 'score_max' in filters and match.match_score > filters['score_max']:
                continue
            
            # Add to filtered list
            self.filtered_matches.append(match)
        
        self._update_table()
    
    def _on_selection_changed(self):
        """Handle selection change"""
        selected_items = self.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            match = self.item(row, 0).data(Qt.UserRole + 1)
            if match:
                self.match_selected.emit(match.to_dict())


class MatchDetailViewer(QWidget):
    """Widget for displaying match details"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI with improved layout"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Match info section (compact)
        info_group = QGroupBox("Match Information")
        info_layout = QFormLayout()
        info_layout.setSpacing(5)
        
        self.match_id_label = QLabel("-")
        info_layout.addRow("Match ID:", self.match_id_label)
        
        self.timestamp_label = QLabel("-")
        info_layout.addRow("Timestamp:", self.timestamp_label)
        
        self.feather_count_label = QLabel("-")
        info_layout.addRow("Feather Count:", self.feather_count_label)
        
        self.time_spread_label = QLabel("-")
        info_layout.addRow("Time Spread:", self.time_spread_label)
        
        info_group.setLayout(info_layout)
        info_group.setMaximumHeight(150)
        layout.addWidget(info_group)
        
        # Weighted scoring breakdown widget
        self.scoring_widget = ScoringBreakdownWidget()
        layout.addWidget(self.scoring_widget)
        
        # Create vertical splitter for Feather Records and Semantic Mappings
        self.splitter = QSplitter(Qt.Vertical)
        
        # === FEATHER RECORDS SECTION (80% height by default, 100% if no semantic data) ===
        # This section is now FIRST (top position)
        feather_widget = QWidget()
        feather_layout = QVBoxLayout(feather_widget)
        feather_layout.setContentsMargins(0, 0, 0, 0)
        feather_layout.setSpacing(5)
        
        feather_label = QLabel("📄 Feather Records")
        feather_label_font = QFont()
        feather_label_font.setBold(True)
        feather_label_font.setPointSize(10)
        feather_label.setFont(feather_label_font)
        feather_layout.addWidget(feather_label)
        
        # Feather selector label
        self.feather_selector_label = QLabel("")
        feather_layout.addWidget(self.feather_selector_label)
        
        # TWO-COLUMN TABLE for feather records
        self.feather_table = QTableWidget()
        self.feather_table.setColumnCount(2)
        self.feather_table.setHorizontalHeaderLabels(["Field", "Value"])
        
        # Configure feather table
        header = self.feather_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Field column
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Value column stretches
        
        self.feather_table.setAlternatingRowColors(True)
        self.feather_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.feather_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.feather_table.verticalHeader().setVisible(False)
        
        feather_layout.addWidget(self.feather_table)
        self.splitter.addWidget(feather_widget)
        
        # === SEMANTIC MAPPINGS SECTION (20% height by default, hidden if no data) ===
        # This section is now SECOND (bottom position)
        self.semantic_widget = QWidget()
        semantic_layout = QVBoxLayout(self.semantic_widget)
        semantic_layout.setContentsMargins(0, 0, 0, 0)
        semantic_layout.setSpacing(5)
        
        semantic_label = QLabel("🔮 Semantic Mappings")
        semantic_label_font = QFont()
        semantic_label_font.setBold(True)
        semantic_label_font.setPointSize(10)
        semantic_label.setFont(semantic_label_font)
        semantic_layout.addWidget(semantic_label)
        
        self.semantic_table = QTableWidget()
        self.semantic_table.setColumnCount(6)
        self.semantic_table.setHorizontalHeaderLabels([
            "Semantic Value", "Identity Type", "Rule Name", 
            "Category", "Confidence", "Severity"
        ])
        
        # Configure semantic table
        header = self.semantic_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Semantic Value
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Identity Type
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # Rule Name
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Category
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Confidence
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Severity
        
        self.semantic_table.setAlternatingRowColors(True)
        self.semantic_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.semantic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.semantic_table.verticalHeader().setVisible(False)
        
        semantic_layout.addWidget(self.semantic_table)
        self.splitter.addWidget(self.semantic_widget)
        
        # Set splitter sizes: 80% feather (index 0), 20% semantic (index 1)
        # Total height = 1000, so 800 for feather, 200 for semantic
        self.splitter.setSizes([800, 200])
        self.splitter.setStretchFactor(0, 4)  # Feather gets 4x more space (index 0 now)
        self.splitter.setStretchFactor(1, 1)  # Semantic can shrink (index 1 now)
        
        # Add splitter with stretch factor 1 to fill all remaining vertical space
        layout.addWidget(self.splitter, 1)
    
    def display_match(self, match_data: dict):
        """Display match details with semantic value highlighting"""
        self.match_id_label.setText(str(match_data.get('match_id', '-')))
        self.timestamp_label.setText(match_data.get('timestamp', '-'))
        self.feather_count_label.setText(str(match_data.get('feather_count', 0)))
        self.time_spread_label.setText(f"{match_data.get('time_spread_seconds', 0):.1f} seconds")
        
        # Display weighted scoring using the dedicated widget
        weighted_score = match_data.get('weighted_score')
        self.scoring_widget.display_scoring(weighted_score)
        
        # Get semantic data from the match (stored in separate semantic_data column)
        semantic_data = match_data.get('semantic_data', {})
        
        # === POPULATE SEMANTIC MAPPINGS TABLE ===
        self.semantic_table.setRowCount(0)
        has_semantic_data = False
        
        if semantic_data:
            row = 0
            for semantic_key, semantic_info in semantic_data.items():
                if not isinstance(semantic_info, dict):
                    continue
                
                semantic_mappings = semantic_info.get('semantic_mappings', [])
                if semantic_mappings and isinstance(semantic_mappings, list):
                    for mapping in semantic_mappings:
                        if isinstance(mapping, dict):
                            has_semantic_data = True
                            self.semantic_table.insertRow(row)
                            
                            # Semantic Value
                            self.semantic_table.setItem(row, 0, QTableWidgetItem(
                                mapping.get('semantic_value', '')
                            ))
                            
                            # Identity Type
                            identity_type = semantic_info.get('identity_type', 'unknown')
                            self.semantic_table.setItem(row, 1, QTableWidgetItem(identity_type))
                            
                            # Rule Name
                            self.semantic_table.setItem(row, 2, QTableWidgetItem(
                                mapping.get('rule_name', '')
                            ))
                            
                            # Category
                            self.semantic_table.setItem(row, 3, QTableWidgetItem(
                                mapping.get('category', '')
                            ))
                            
                            # Confidence
                            confidence = mapping.get('confidence', 0.0)
                            self.semantic_table.setItem(row, 4, QTableWidgetItem(
                                f"{confidence:.0%}"
                            ))
                            
                            # Severity
                            severity = mapping.get('severity', 'info').upper()
                            self.semantic_table.setItem(row, 5, QTableWidgetItem(severity))
                            
                            row += 1
        
        # Hide/show semantic section based on whether there's data
        if has_semantic_data:
            self.semantic_widget.setVisible(True)
            # Reset to default sizes: 80% feather (index 0), 20% semantic (index 1)
            self.splitter.setSizes([800, 200])
        else:
            self.semantic_widget.setVisible(False)
            # Feather table takes 100% when no semantic data
            self.splitter.setSizes([1000, 0])
        
        # === POPULATE FEATHER RECORDS TABLE (TWO COLUMNS) ===
        feather_records = match_data.get('feather_records', {})
        self.feather_table.setRowCount(0)
        
        if feather_records:
            # For now, show first feather (in future, could add tabs/dropdown for multiple feathers)
            first_feather = list(feather_records.keys())[0]
            record = feather_records[first_feather]
            
            feather_count = len(feather_records)
            self.feather_selector_label.setText(f"{first_feather} ({feather_count})")
            
            row = 0
            for key, value in record.items():
                # Skip internal fields
                if key.startswith('_'):
                    continue
                
                self.feather_table.insertRow(row)
                
                # Field column (bold)
                field_item = QTableWidgetItem(key)
                field_font = QFont()
                field_font.setBold(True)
                field_item.setFont(field_font)
                self.feather_table.setItem(row, 0, field_item)
                
                # Value column
                value_str = str(value)
                
                # Check if this field has semantic mapping
                identity_value = record.get('identity_value', '')
                semantic_match = None
                
                if identity_value and semantic_data:
                    # Find semantic data for this identity
                    for semantic_key, semantic_info in semantic_data.items():
                        if not isinstance(semantic_info, dict):
                            continue
                        
                        # Check if this semantic data matches the identity
                        semantic_identity = semantic_info.get('identity_value', '')
                        if semantic_identity:
                            # Split by | and check if identity matches
                            semantic_values = [v.strip().upper() for v in semantic_identity.split('|')]
                            if identity_value.upper() in semantic_values:
                                # Get the semantic value
                                semantic_mappings = semantic_info.get('semantic_mappings', [])
                                if semantic_mappings and isinstance(semantic_mappings, list):
                                    semantic_match = semantic_mappings[0].get('semantic_value', '')
                                    break
                
                # Add semantic value indicator if available
                if semantic_match and isinstance(value, str) and identity_value.upper() in value_str.upper():
                    value_str += f" ✨ ({semantic_match})"
                
                value_item = QTableWidgetItem(value_str)
                self.feather_table.setItem(row, 1, value_item)
                
                row += 1


class FilterPanelWidget(QWidget):
    """Widget for filtering results"""
    
    filters_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        
        # Application filter
        app_layout = QHBoxLayout()
        app_layout.addWidget(QLabel("Application:"))
        self.app_input = QLineEdit()
        self.app_input.setPlaceholderText("Filter by application...")
        self.app_input.textChanged.connect(self._emit_filters)
        app_layout.addWidget(self.app_input)
        layout.addLayout(app_layout)
        
        # File path filter
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("File Path:"))
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Filter by file path...")
        self.path_input.textChanged.connect(self._emit_filters)
        path_layout.addWidget(self.path_input)
        layout.addLayout(path_layout)
        
        # Score range
        score_layout = QVBoxLayout()
        score_layout.addWidget(QLabel("Score Range:"))
        
        self.score_slider = QSlider(Qt.Horizontal)
        self.score_slider.setMinimum(0)
        self.score_slider.setMaximum(100)
        self.score_slider.setValue(0)
        self.score_slider.valueChanged.connect(self._emit_filters)
        score_layout.addWidget(self.score_slider)
        
        self.score_label = QLabel("Min: 0.00")
        score_layout.addWidget(self.score_label)
        
        layout.addLayout(score_layout)
        
        # Reset button
        reset_btn = QPushButton("Reset Filters")
        reset_btn.clicked.connect(self.reset_filters)
        layout.addWidget(reset_btn)
        
        layout.addStretch()
    
    def get_filter_criteria(self) -> dict:
        """Get current filter settings"""
        return {
            'application': self.app_input.text().strip(),
            'file_path': self.path_input.text().strip(),
            'score_min': self.score_slider.value() / 100.0
        }
    
    def reset_filters(self):
        """Clear all filters"""
        self.app_input.clear()
        self.path_input.clear()
        self.score_slider.setValue(0)
    
    def _emit_filters(self):
        """Emit filter change signal"""
        self.score_label.setText(f"Min: {self.score_slider.value() / 100.0:.2f}")
        self.filters_changed.emit(self.get_filter_criteria())


class DynamicResultsTabWidget(QWidget):
    """Widget with dynamic tabs for wing results with semantic and scoring support"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.results_data: Dict[str, CorrelationResult] = {}
        self.engine_type = "time_based"  # Default engine type
        
        # Use results tab widget
        self.enhanced_tab_widget = ResultsTabWidget()
        self.enhanced_tab_widget.match_selected.connect(self._on_match_selected)
        self.enhanced_tab_widget.export_requested.connect(self._on_export_requested)
        
        self._init_ui()
        
        # Create Summary tab (index 0) - will be populated when execution completes
        self._create_summary_tab()
    
    def _init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Add enhanced tab widget
        layout.addWidget(self.enhanced_tab_widget)
    
    def _create_summary_tab(self):
        """
        Create the Summary tab (index 0) with placeholder content.
        Will be populated with aggregate statistics when execution completes.
        
        Requirements: 5.1
        """
        # Create placeholder widget for Summary tab
        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        summary_layout.setContentsMargins(20, 20, 20, 20)
        
        # Placeholder message
        placeholder_label = QLabel("Summary\n\nAggregate statistics will appear here after wing execution completes.")
        placeholder_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 12pt;
                padding: 40px;
                background-color: #1E293B;
                border: 2px dashed #334155;
                border-radius: 8px;
            }
        """)
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_label.setWordWrap(True)
        summary_layout.addWidget(placeholder_label)
        
        # Add Summary tab at index 0
        self.enhanced_tab_widget.tab_widget.insertTab(0, summary_widget, "Summary")
        
        print("[DynamicResultsTabWidget] ✓ Summary tab created at index 0")
    
    def set_engine_type(self, engine_type: str):
        """Set the engine type for results display and reconfigure layout."""
        self.engine_type = engine_type
        self.enhanced_tab_widget.set_engine_type(engine_type)
        
        # Reconfigure display layout based on engine type
        print(f"[DynamicResultsTabWidget] Engine type set to: {engine_type}")
        
        # Clear any existing charts
        if hasattr(self, 'chart_container'):
            self.chart_container.setParent(None)
            self.chart_container.deleteLater()
            delattr(self, 'chart_container')
    
    def _render_identity_charts(self, feather_metadata: Dict) -> PyQt5BarChart:
        """
        Render charts for Identity Engine results using PyQt5 native chart.
        
        MODIFIED: Returns PyQt5BarChart widget instead of adding to tab directly.
        Reusable for both wing-specific and aggregate charts.
        
        Requirements: 1.3
        
        Args:
            feather_metadata: Dictionary of feather_id -> metadata
            
        Returns:
            PyQt5BarChart widget or None if no data available
        """
        try:
            # Extract data from feather_metadata
            chart_data = {}
            
            for feather_id, metadata in feather_metadata.items():
                if isinstance(metadata, dict) and not feather_id.startswith('_'):
                    count = metadata.get('identities_found', metadata.get('identities_final', metadata.get('matches_created', 0)))
                    if count > 0:
                        chart_data[feather_id] = count
            
            if not chart_data:
                print("[DynamicResultsTabWidget] No chart data available")
                return None
            
            # Sort by value descending and limit to top 15
            sorted_data = dict(sorted(chart_data.items(), key=lambda x: x[1], reverse=True)[:15])
            
            # Create PyQt5 native bar chart
            chart = PyQt5BarChart()
            chart.set_data(sorted_data, "Identity Extraction by Feather", "Identities Found")
            
            # Store chart data for export
            chart.chart_data = {
                'feathers': list(sorted_data.keys()),
                'counts': list(sorted_data.values()),
                'title': 'Identity Extraction by Feather',
                'ylabel': 'Identities Found'
            }
            
            print(f"[DynamicResultsTabWidget] Created PyQt5 bar chart with {len(sorted_data)} bars")
            return chart
            
        except Exception as e:
            print(f"[Error] Failed to render identity charts: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _render_timebased_charts(self, time_windows: List):
        """Render charts for Time-Based Engine results using PyQt5 native chart."""
        try:
            # Extract timestamp counts per feather from time windows
            feather_timestamps = {}
            
            for window in time_windows:
                for identity in window.get('identities', []):
                    for feather in identity.get('feathers_found', []):
                        if feather not in feather_timestamps:
                            feather_timestamps[feather] = 0
                        feather_timestamps[feather] += identity.get('total_matches', 0)
            
            if not feather_timestamps:
                print("[DynamicResultsTabWidget] No time window data available")
                return None
            
            # Sort by value descending and limit to top 15
            sorted_data = dict(sorted(feather_timestamps.items(), key=lambda x: x[1], reverse=True)[:15])
            
            # Create PyQt5 native bar chart
            chart = PyQt5BarChart()
            chart.set_data(sorted_data, "Timestamp Extraction by Feather", "Timestamp Records")
            
            # Store chart data for export
            chart.chart_data = {
                'feathers': list(sorted_data.keys()),
                'counts': list(sorted_data.values()),
                'title': 'Timestamp Extraction by Feather',
                'ylabel': 'Timestamp Records'
            }
            
            print(f"[DynamicResultsTabWidget] Created PyQt5 bar chart with {len(sorted_data)} bars")
            return chart
            
        except Exception as e:
            print(f"[Error] Failed to render time-based charts: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _render_text_summary(self, feather_data: Dict, engine_name: str):
        """
        Render a text-based summary when matplotlib charts are not available.
        
        Args:
            feather_data: Dictionary of feather_id -> metadata or feather_id -> count
            engine_name: Name of the engine for display
            
        Returns:
            QWidget containing the text summary
        """
        try:
            # Create summary widget
            summary_widget = QWidget()
            layout = QVBoxLayout(summary_widget)
            layout.setContentsMargins(10, 10, 10, 10)
            
            # Title
            title_label = QLabel(f"📊 {engine_name} - Feather Statistics")
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 14pt;
                    font-weight: bold;
                    color: #2196F3;
                    padding: 10px;
                }
            """)
            layout.addWidget(title_label)
            
            # Note about charts
            note_label = QLabel("ℹ️ Charts unavailable (matplotlib Qt5Agg backend not loaded)")
            note_label.setStyleSheet("color: #ff9800; font-style: italic; padding: 5px;")
            layout.addWidget(note_label)
            
            # Create table for feather statistics
            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(["Feather", "Count", "Percentage"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setAlternatingRowColors(True)
            table.setStyleSheet("""
                QTableWidget {
                    background-color: #2a2a2a;
                    gridline-color: #444;
                    color: white;
                }
                QTableWidget::item {
                    padding: 5px;
                }
                QHeaderView::section {
                    background-color: #3a3a3a;
                    color: white;
                    padding: 5px;
                    font-weight: bold;
                }
            """)
            
            # Extract and sort data
            sorted_data = []
            total_count = 0
            
            for feather_id, data in feather_data.items():
                if feather_id.startswith('_'):  # Skip metadata entries
                    continue
                if isinstance(data, dict):
                    count = data.get('identities_found', data.get('matches_created', 0))
                else:
                    count = data
                sorted_data.append((feather_id, count))
                total_count += count
            
            # Sort by count descending
            sorted_data.sort(key=lambda x: x[1], reverse=True)
            
            # Populate table
            table.setRowCount(len(sorted_data))
            for row, (feather_id, count) in enumerate(sorted_data):
                percentage = (count / total_count * 100) if total_count > 0 else 0
                
                table.setItem(row, 0, QTableWidgetItem(feather_id))
                table.setItem(row, 1, QTableWidgetItem(f"{count:,}"))
                table.setItem(row, 2, QTableWidgetItem(f"{percentage:.1f}%"))
            
            layout.addWidget(table)
            
            # Total summary
            total_label = QLabel(f"Total: {total_count:,} items across {len(sorted_data)} feathers")
            total_label.setStyleSheet("font-weight: bold; padding: 10px; color: #4CAF50;")
            layout.addWidget(total_label)
            
            print(f"[DynamicResultsTabWidget] Text summary created for {len(sorted_data)} feathers")
            return summary_widget
            
        except Exception as e:
            print(f"[Error] Failed to render text summary: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_global_semantic_mappings(self, semantic_mappings: Dict[str, Any]):
        """Update global semantic mappings for all tabs."""
        self.enhanced_tab_widget.update_global_semantic_mappings(semantic_mappings)
    
    def update_global_scoring_configuration(self, scoring_config: Dict[str, Any]):
        """Update global scoring configuration for all tabs."""
        self.enhanced_tab_widget.update_global_scoring_configuration(scoring_config)
    
    def _on_match_selected(self, tab_id: str, match_data: dict):
        """Handle match selection from enhanced tab widget."""
        print(f"[Results Viewer] Match selected in tab {tab_id}: {match_data.get('match_id', 'Unknown')}")
    
    def _on_export_requested(self, tab_id: str, export_options: dict):
        """Handle export request from enhanced tab widget."""
        try:
            # Get all tab states for export
            all_tab_states = self.enhanced_tab_widget.get_all_tab_states()
            
            # Convert tab states to export format
            export_tab_states = {}
            for state_id, tab_state in all_tab_states.items():
                export_tab_states[state_id] = {
                    'tab_id': tab_state.tab_id,
                    'wing_name': tab_state.wing_name,
                    'matches': [match.to_dict() for match in tab_state.result.matches],
                    'semantic_mappings': tab_state.semantic_mappings,
                    'scoring_configuration': tab_state.scoring_configuration,
                    'filter_state': tab_state.filter_state,
                    'created_timestamp': tab_state.created_timestamp.isoformat(),
                    'last_accessed': tab_state.last_accessed.isoformat()
                }
            
            # Show export dialog
            export_config = show_export_dialog(export_tab_states, self)
            
            if export_config:
                # Perform export with progress
                success, message = export_results_with_progress(export_config, self)
                
                if success:
                    QMessageBox.information(
                        self,
                        "Export Successful",
                        f"Results exported successfully:\n{message}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Export Failed",
                        f"Export failed:\n{message}"
                    )
        
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )
    
    def _show_error_message(self, message: str):
        """Display error message in the tab with retry functionality."""
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton
        from PyQt5.QtCore import Qt
        
        # Create error widget
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        error_layout.setContentsMargins(20, 20, 20, 20)
        
        # Error message
        error_label = QLabel(f"⚠️ {message}")
        error_label.setStyleSheet("""
            QLabel {
                color: #ff9800;
                font-size: 14pt;
                padding: 20px;
                font-weight: bold;
                background-color: #2a2a2a;
                border: 2px solid #ff9800;
                border-radius: 5px;
            }
        """)
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setWordWrap(True)
        error_layout.addWidget(error_label)
        
        # Retry button
        retry_btn = QPushButton("🔄 Retry Loading")
        retry_btn.clicked.connect(self._retry_load_results)
        retry_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                padding: 10px 20px;
                font-size: 12pt;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        retry_btn.setMaximumWidth(200)
        error_layout.addWidget(retry_btn, alignment=Qt.AlignCenter)
        
        error_layout.addStretch()
        
        # Add to main layout
        self.layout().insertWidget(0, error_widget)
        print(f"[DynamicResultsTabWidget] Error message displayed: {message}")
    
    def _retry_load_results(self):
        """Retry loading results."""
        print("[DynamicResultsTabWidget] Retrying result load...")
        if hasattr(self, 'output_dir') and self.output_dir:
            # Clear any existing error widgets
            for i in reversed(range(self.layout().count())):
                widget = self.layout().itemAt(i).widget()
                if widget and isinstance(widget, QWidget):
                    # Check if it's an error widget (has the warning style)
                    if "⚠️" in widget.findChild(QLabel).text() if widget.findChild(QLabel) else False:
                        widget.setParent(None)
                        widget.deleteLater()
            
            # Retry loading
            self.load_results(self.output_dir)
        else:
            print("[DynamicResultsTabWidget] ERROR: No output_dir set for retry")
            QMessageBox.warning(
                self,
                "Cannot Retry",
                "No output directory is set. Please run a correlation first."
            )
    
    def load_results(self, output_dir: str, wing_id: Optional[str] = None, pipeline_id: Optional[str] = None, engine_type: Optional[str] = None):
        """
        Load results from output directory with enhanced semantic and scoring support.
        
        Args:
            output_dir: Directory containing result files (typically Case/Correlation/output)
            wing_id: Optional Wing ID for Wing-specific semantic mappings
            pipeline_id: Optional Pipeline ID for Pipeline-specific semantic mappings
            engine_type: Optional engine type to render appropriate charts
        """
        try:
            # Store output_dir for database queries (Requirement 4.6)
            # Database is located at: output_dir/correlation_results.db
            # Typical path: E:\Cases\CaseName\Correlation\output\correlation_results.db
            self.output_dir = output_dir
            
            # Set engine type if provided
            if engine_type:
                self.set_engine_type(engine_type)
            
            # Delegate to enhanced tab widget
            self.enhanced_tab_widget.load_results(output_dir, wing_id, pipeline_id)
            
            # Update local results data for compatibility
            self.results_data.clear()
            all_tab_states = self.enhanced_tab_widget.get_all_tab_states()
            
            for tab_state in all_tab_states.values():
                self.results_data[tab_state.wing_name] = tab_state.result
            
            # Render charts based on engine type and available data
            self._render_charts_for_results()
                
            print(f"✓ Results loaded successfully from {output_dir}")
            
        except Exception as e:
            print(f"❌ Failed to load results from {output_dir}: {e}")
            import traceback
            traceback.print_exc()
    
    def _render_charts_for_results(self):
        """Render charts based on loaded results and engine type."""
        try:
            print("[DynamicResultsTabWidget] DEBUG: _render_charts_for_results() called")
            
            # CRITICAL CHECK: Verify results_data is populated
            if not self.results_data:
                print("[DynamicResultsTabWidget] ERROR: results_data is EMPTY")
                print("[DynamicResultsTabWidget] ERROR: Cannot render charts without data")
                self._show_error_message("No correlation results available")
                return
            
            print(f"[DynamicResultsTabWidget] DEBUG: results_data has {len(self.results_data)} entries")
            print(f"[DynamicResultsTabWidget] DEBUG: results_data keys: {list(self.results_data.keys())}")
            
            first_result = next(iter(self.results_data.values()))
            print(f"[DynamicResultsTabWidget] DEBUG: first_result type: {type(first_result)}")
            
            # Check if we have feather_metadata
            # Requirement 4.7: Check for feather_metadata in CorrelationResult
            feather_metadata = getattr(first_result, 'feather_metadata', {})
            print(f"[DynamicResultsTabWidget] DEBUG: feather_metadata found: {bool(feather_metadata)}")
            if feather_metadata:
                print(f"[DynamicResultsTabWidget] DEBUG: feather_metadata has {len(feather_metadata)} feathers")
                print(f"[DynamicResultsTabWidget] DEBUG: feather_metadata keys: {list(feather_metadata.keys())}")
            
            # Requirement 4.3, 4.5, 4.7: If no feather_metadata and streaming mode, query database
            if not feather_metadata:
                print("[DynamicResultsTabWidget] No feather_metadata found, attempting database fallback...")
                # Try to query database for feather statistics
                feather_metadata = self._query_feather_metadata_from_database(first_result)
                print(f"[DynamicResultsTabWidget] DEBUG: Database query returned {len(feather_metadata)} feathers")
                
                if not feather_metadata:
                    print("[DynamicResultsTabWidget] ERROR: No feather_metadata available from any source")
                    self._show_error_message("Feather statistics unavailable - charts cannot be rendered")
                    return
            
            # Update the feather stats table in the enhanced_tab_widget
            if feather_metadata and hasattr(self.enhanced_tab_widget, 'update_feather_stats_from_data'):
                total_matches = first_result.total_matches if hasattr(first_result, 'total_matches') else 0
                self.enhanced_tab_widget.update_feather_stats_from_data(feather_metadata, total_matches)
                print(f"[DynamicResultsTabWidget] Updated feather stats table with {len(feather_metadata)} feathers")
            
            chart_widget = None
            
            print(f"[DynamicResultsTabWidget] DEBUG: engine_type = {self.engine_type}")
            
            if self.engine_type == "identity_based" and feather_metadata:
                print("[DynamicResultsTabWidget] Rendering Identity Engine charts...")
                try:
                    chart_widget = self._render_identity_charts(feather_metadata)
                    print(f"[DynamicResultsTabWidget] DEBUG: chart_widget created: {chart_widget is not None}")
                except Exception as e:
                    print(f"[DynamicResultsTabWidget] ERROR rendering identity charts: {e}")
                    import traceback
                    traceback.print_exc()
            
            elif self.engine_type in ["time_window_scanning", "time_based"]:
                # Try to get time_windows data
                print("[DynamicResultsTabWidget] Rendering Time-Based Engine charts...")
                try:
                    # For time-based, we need to extract time windows from results
                    # This might be in a different format, so we'll handle it
                    time_windows = self._extract_time_windows_from_results()
                    if time_windows:
                        chart_widget = self._render_timebased_charts(time_windows)
                    else:
                        print("[DynamicResultsTabWidget] WARNING: No time windows extracted")
                except Exception as e:
                    print(f"[DynamicResultsTabWidget] ERROR rendering time-based charts: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Add chart to layout if created
            if chart_widget:
                print(f"[DynamicResultsTabWidget] Chart widget created successfully: {type(chart_widget)}")
                
                # Remove existing chart container if present
                if hasattr(self, 'chart_container') and self.chart_container:
                    self.chart_container.setParent(None)
                    self.chart_container.deleteLater()
                
                # Create new chart container with horizontal layout (chart + results viewer)
                self.chart_container = QWidget()
                main_layout = QHBoxLayout(self.chart_container)
                main_layout.setContentsMargins(5, 5, 5, 5)
                main_layout.setSpacing(10)
                
                # Left side: Chart section
                chart_section = QWidget()
                chart_layout = QVBoxLayout(chart_section)
                chart_layout.setContentsMargins(0, 0, 0, 0)
                
                # Add engine type label
                engine_display = self.engine_type.replace('_', ' ').title()
                engine_label = QLabel(f"📊 {engine_display} - Feather Statistics")
                engine_label.setStyleSheet("font-weight: bold; font-size: 12pt; color: #2196F3; padding: 5px;")
                chart_layout.addWidget(engine_label)
                
                # Add the chart widget
                chart_widget.setMinimumHeight(300)
                chart_layout.addWidget(chart_widget)
                
                # Summary tab should only contain charts - no results table
                # Detailed results will be shown in wing-specific tabs (Requirements 1.1, 1.2)
                main_layout.addWidget(chart_section, stretch=1)
                
                # Add chart container to Summary tab (index 0)
                summary_tab = self.enhanced_tab_widget.tab_widget.widget(0)
                if summary_tab:
                    summary_layout = summary_tab.layout()
                    if summary_layout:
                        # Insert chart at the beginning of the summary tab
                        summary_layout.insertWidget(0, self.chart_container)
                        print("[DynamicResultsTabWidget] ✓ Chart added to Summary tab (Requirements 1.1, 1.2)")
                    else:
                        print("[DynamicResultsTabWidget] ERROR: Summary tab has no layout!")
                else:
                    print("[DynamicResultsTabWidget] ERROR: Summary tab not found!")
                
                print("[DynamicResultsTabWidget] ✓ Charts rendered successfully")
            else:
                # Requirement 4.8: Display error message if no data available
                print("[DynamicResultsTabWidget] WARNING: No chart widget was created")
                self._show_error_message("Unable to render charts")
        
        except Exception as e:
            print(f"[DynamicResultsTabWidget] CRITICAL ERROR in _render_charts_for_results: {e}")
            import traceback
            traceback.print_exc()
            self._show_error_message(f"Chart rendering failed: {str(e)}")
    
    def _extract_time_windows_from_results(self) -> List:
        """Extract time windows data from results for chart rendering."""
        try:
            # This is a helper to extract time window data
            # The actual structure depends on how results are stored
            time_windows = []
            
            for result in self.results_data.values():
                # Check if result has time_windows attribute or similar
                if hasattr(result, 'time_windows'):
                    time_windows.extend(result.time_windows)
                # Or if matches can be grouped into windows
                elif hasattr(result, 'matches'):
                    # Group matches by time window (simplified)
                    # This is a placeholder - actual implementation depends on data structure
                    pass
            
            return time_windows
            
        except Exception as e:
            print(f"[Error] Failed to extract time windows: {e}")
            return []
    
    def _query_feather_metadata_from_database(self, result) -> Dict:
        """
        Query database to reconstruct feather_metadata when not available in result.
        
        Requirements: 4.3, 4.4, 4.5, 4.7
        
        Args:
            result: CorrelationResult object
            
        Returns:
            Dictionary of feather_id -> metadata
        """
        try:
            # Requirement 4.6: Get database path from result or output directory
            db_path = getattr(result, 'database_path', None)
            
            # Try to get from output_dir if database_path not set
            if not db_path and hasattr(self, 'output_dir') and self.output_dir:
                from pathlib import Path
                db_path = str(Path(self.output_dir) / "correlation_results.db")
            
            if not db_path:
                print("[DynamicResultsTabWidget] No database path available to query feather metadata")
                return {}
            
            # Check if database file exists
            from pathlib import Path
            if not Path(db_path).exists():
                print(f"[DynamicResultsTabWidget] Database file not found: {db_path}")
                return {}
            
            import sqlite3
            print(f"[DynamicResultsTabWidget] Querying database for feather statistics: {db_path}")
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get execution_id from result
            execution_id = getattr(result, 'execution_id', None)
            
            if not execution_id:
                # Try to get the most recent execution
                cursor.execute("SELECT MAX(execution_id) FROM executions")
                row = cursor.fetchone()
                if row and row[0]:
                    execution_id = row[0]
                    print(f"[DynamicResultsTabWidget] Using most recent execution_id: {execution_id}")
                else:
                    print("[DynamicResultsTabWidget] No execution_id found in database")
                    conn.close()
                    return {}
            
            # Requirement 4.4: Query feather_metadata table first, then fall back to matches
            # First try the feather_metadata table which has proper feather info
            cursor.execute("""
                SELECT 
                    fm.feather_id,
                    fm.artifact_type,
                    fm.total_records,
                    fm.identities_extracted,
                    fm.identities_found,
                    COUNT(m.match_id) as matches_count
                FROM feather_metadata fm
                LEFT JOIN results r ON fm.result_id = r.result_id
                LEFT JOIN matches m ON m.result_id = r.result_id AND m.anchor_feather_id = fm.feather_id
                WHERE r.execution_id = ?
                GROUP BY fm.feather_id
            """, (execution_id,))
            
            feather_metadata = {}
            rows = cursor.fetchall()
            
            if rows:
                for row in rows:
                    feather_id, artifact_type, total_records, identities_extracted, identities_found, matches_count = row
                    if feather_id:  # Skip None feather_ids
                        feather_metadata[feather_id] = {
                            'feather_name': feather_id,
                            'artifact_type': artifact_type or 'Unknown',
                            'identities_found': identities_found or 0,  # FIXED: Read from database
                            'identities_final': identities_found or 0,
                            'matches_created': matches_count,
                            'records_processed': total_records or 0,
                            'identities_extracted': identities_extracted or 0,
                            'identities_filtered': 0
                        }
            
            # If no feather_metadata found, fall back to querying matches table directly
            if not feather_metadata:
                print("[DynamicResultsTabWidget] No feather_metadata table data, trying results.feather_metadata JSON column...")
                
                # Try to get feather_metadata from results table JSON column
                cursor.execute("""
                    SELECT feather_metadata FROM results WHERE execution_id = ? AND feather_metadata IS NOT NULL
                """, (execution_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    try:
                        feather_metadata = json.loads(row[0])
                        # Filter out engine metadata
                        feather_metadata = {k: v for k, v in feather_metadata.items() if not k.startswith('_')}
                        print(f"[DynamicResultsTabWidget] Loaded {len(feather_metadata)} feathers from results.feather_metadata JSON")
                    except:
                        pass
            
            # Final fallback: query matches table directly
            if not feather_metadata:
                print("[DynamicResultsTabWidget] Falling back to matches table query...")
                cursor.execute("""
                    SELECT 
                        m.anchor_feather_id,
                        m.anchor_artifact_type,
                        COUNT(*) as matches_count
                    FROM matches m
                    JOIN results r ON m.result_id = r.result_id
                    WHERE r.execution_id = ?
                    GROUP BY m.anchor_feather_id
                """, (execution_id,))
                
                for row in cursor.fetchall():
                    feather_id, artifact_type, matches_count = row
                    if feather_id:
                        feather_metadata[feather_id] = {
                            'feather_name': feather_id,
                            'artifact_type': artifact_type or 'Unknown',
                            'identities_found': 0,  # FIXED: Can't determine from matches table alone
                            'identities_final': 0,
                            'matches_created': matches_count,
                            'records_processed': 0,
                            'identities_extracted': 0,  # FIXED: Can't determine from matches table alone
                            'identities_filtered': 0
                        }
            
            conn.close()
            
            print(f"[DynamicResultsTabWidget] Reconstructed metadata for {len(feather_metadata)} feathers from database")
            return feather_metadata
            
        except Exception as e:
            print(f"[DynamicResultsTabWidget] Failed to query feather metadata from database: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _export_chart_as_png(self, chart_widget, filepath: str):
        """Export chart to PNG file."""
        try:
            if not hasattr(chart_widget, 'figure'):
                QMessageBox.warning(self, "Export Error", "Chart figure not available for export")
                return False
            
            # Save figure to file
            chart_widget.figure.savefig(filepath, dpi=300, bbox_inches='tight')
            print(f"[Export] Chart saved to: {filepath}")
            return True
            
        except Exception as e:
            print(f"[Error] Failed to export chart as PNG: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export chart:\n{str(e)}")
            return False
    
    def _export_chart_data_as_csv(self, chart_data: Dict, filepath: str):
        """Export chart data to CSV file."""
        try:
            import csv
            
            if not chart_data:
                QMessageBox.warning(self, "Export Error", "No chart data available for export")
                return False
            
            feathers = chart_data.get('feathers', [])
            counts = chart_data.get('counts', [])
            
            if not feathers or not counts:
                QMessageBox.warning(self, "Export Error", "Chart data is incomplete")
                return False
            
            # Calculate percentages
            total = sum(counts)
            percentages = [(c / total * 100) if total > 0 else 0 for c in counts]
            
            # Write to CSV
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Feather', 'Count', 'Percentage'])
                for feather, count, percentage in zip(feathers, counts, percentages):
                    writer.writerow([feather, count, f"{percentage:.2f}%"])
            
            print(f"[Export] Chart data saved to: {filepath}")
            return True
            
        except Exception as e:
            print(f"[Error] Failed to export chart data as CSV: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export data:\n{str(e)}")
            return False
    
    def _setup_chart_context_menu(self, chart_widget):
        """Setup right-click context menu for chart."""
        try:
            from PyQt5.QtWidgets import QMenu
            from PyQt5.QtCore import QPoint
            
            def show_context_menu(event):
                if event.button == 3:  # Right click
                    menu = QMenu(self)
                    
                    export_png_action = menu.addAction("Export as PNG")
                    export_csv_action = menu.addAction("Export Data as CSV")
                    
                    action = menu.exec_(chart_widget.mapToGlobal(QPoint(int(event.x), int(event.y))))
                    
                    if action == export_png_action:
                        self._handle_export_png(chart_widget)
                    elif action == export_csv_action:
                        self._handle_export_csv(chart_widget)
            
            chart_widget.mpl_connect('button_press_event', show_context_menu)
            
        except Exception as e:
            print(f"[Error] Failed to setup context menu: {e}")
    
    def _handle_export_png(self, chart_widget):
        """Handle PNG export action."""
        try:
            # Generate default filename
            wing_name = next(iter(self.results_data.keys()), "chart")
            timestamp = datetime.now().strftime("%Y-%m-%d")
            default_filename = f"{wing_name}_{self.engine_type}_chart_{timestamp}.png"
            
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Export Chart as PNG",
                default_filename,
                "PNG Files (*.png);;All Files (*)"
            )
            
            if filepath:
                if self._export_chart_as_png(chart_widget, filepath):
                    QMessageBox.information(self, "Export Successful", f"Chart exported to:\n{filepath}")
                    
        except Exception as e:
            print(f"[Error] Failed to handle PNG export: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{str(e)}")
    
    def _handle_export_csv(self, chart_widget):
        """Handle CSV export action."""
        try:
            if not hasattr(chart_widget, 'chart_data'):
                QMessageBox.warning(self, "Export Error", "Chart data not available")
                return
            
            # Generate default filename
            wing_name = next(iter(self.results_data.keys()), "chart")
            timestamp = datetime.now().strftime("%Y-%m-%d")
            default_filename = f"{wing_name}_{self.engine_type}_data_{timestamp}.csv"
            
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Export Chart Data as CSV",
                default_filename,
                "CSV Files (*.csv);;All Files (*)"
            )
            
            if filepath:
                if self._export_chart_data_as_csv(chart_widget.chart_data, filepath):
                    QMessageBox.information(self, "Export Successful", f"Data exported to:\n{filepath}")
                    
        except Exception as e:
            print(f"[Error] Failed to handle CSV export: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{str(e)}")
    
    def create_wing_result_tab(self, wing_summary: dict, show_progress=True) -> None:
        """
        Create a new tab for a wing's results.
        
        Each tab contains:
        1. Wing-specific summary section (charts + statistics for THIS wing only)
        2. Tree view with detailed results (Identity or Time-Based)
        
        Args:
            wing_summary: Dictionary containing:
                - wing_name: str
                - engine_type: str ('identity_based' or 'time_window_scanning')
                - execution_id: str
                - database_path: str
                - total_matches: int
                - wing_index: int
                - feather_metadata: dict (for wing-specific charts)
            show_progress: If False, suppresses progress dialogs
        
        Requirements: 2.1, 2.2, 2.3
        """
        try:
            # Validate required fields
            required_fields = ['wing_name', 'engine_type', 'execution_id', 'database_path']
            missing = [f for f in required_fields if f not in wing_summary]
            
            if missing:
                print(f"[Error] Cannot create wing tab: missing fields {missing}")
                # Create error tab with message
                error_widget = QLabel(f"Error: Missing data for wing results\nMissing: {', '.join(missing)}")
                error_widget.setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 12pt;
                        padding: 20px;
                        background-color: #2a2a2a;
                        border: 2px solid #ff9800;
                        border-radius: 5px;
                    }
                """)
                error_widget.setAlignment(Qt.AlignCenter)
                error_widget.setWordWrap(True)
                tab_name = wing_summary.get('wing_name', 'Unknown Wing')
                self.enhanced_tab_widget.tab_widget.addTab(error_widget, tab_name)
                return
            
            # Extract wing information
            wing_name = wing_summary['wing_name']
            engine_type = wing_summary['engine_type']
            execution_id = wing_summary['execution_id']
            database_path = wing_summary['database_path']
            
            print(f"[DynamicResultsTabWidget] Creating wing tab: {wing_name} (engine: {engine_type})")
            
            # Create container widget for the tab
            tab_container = QWidget()
            tab_layout = QVBoxLayout(tab_container)
            tab_layout.setContentsMargins(5, 5, 5, 5)
            tab_layout.setSpacing(5)
            
            # Add wing-specific summary section at top
            summary_section = self._create_wing_summary_section(wing_summary)
            if summary_section:
                tab_layout.addWidget(summary_section)
            
            # Add appropriate tree viewer below (Identity or Time-Based)
            viewer = None
            if engine_type == 'identity_based':
                viewer = self._create_identity_viewer(database_path, execution_id, show_progress=show_progress)
            elif engine_type in ['time_window_scanning', 'time_based']:
                viewer = self._create_timebased_viewer(database_path, execution_id, show_progress=show_progress)
            else:
                # Unknown engine type - create error widget
                print(f"[Error] Unknown engine type: {engine_type}")
                error_widget = QLabel(f"Error: Unknown engine type '{engine_type}'\nCannot display results.\n\nSupported types: identity_based, time_window_scanning")
                error_widget.setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 11pt;
                        padding: 20px;
                        background-color: #2a2a2a;
                        border: 2px solid #ff9800;
                        border-radius: 5px;
                    }
                """)
                error_widget.setAlignment(Qt.AlignCenter)
                error_widget.setWordWrap(True)
                viewer = error_widget
            
            if viewer:
                tab_layout.addWidget(viewer)
            
            # Add tab to ResultsTabWidget with wing name
            self.enhanced_tab_widget.tab_widget.addTab(tab_container, wing_name)
            
            print(f"[DynamicResultsTabWidget] ✓ Wing tab created: {wing_name}")
            
        except Exception as e:
            print(f"[Error] Failed to create wing result tab: {e}")
            import traceback
            traceback.print_exc()
            
            # Create error tab
            error_widget = QLabel(f"Error creating wing tab:\n{str(e)}")
            error_widget.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 11pt;
                    padding: 20px;
                    background-color: #2a2a2a;
                    border: 2px solid #ff9800;
                    border-radius: 5px;
                }
            """)
            error_widget.setAlignment(Qt.AlignCenter)
            error_widget.setWordWrap(True)
            tab_name = wing_summary.get('wing_name', 'Error')
            self.enhanced_tab_widget.tab_widget.addTab(error_widget, tab_name)
    
    def _create_wing_summary_section(self, wing_summary: dict) -> QWidget:
        """
        Create summary section for a specific wing.
        
        Returns a widget containing:
        - Wing-specific charts (feather extraction for THIS wing)
        - Wing-specific statistics (matches, time, feathers used)
        - Execution metadata (execution_id, timestamp, engine type)
        
        Requirements: 2.1
        """
        try:
            # Create container widget
            summary_widget = QWidget()
            summary_layout = QVBoxLayout(summary_widget)
            summary_layout.setContentsMargins(5, 5, 5, 5)
            summary_layout.setSpacing(5)
            
            # Wing header with metadata
            header_frame = QFrame()
            header_frame.setStyleSheet("""
                QFrame {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 6px;
                }
            """)
            header_layout = QHBoxLayout(header_frame)
            header_layout.setContentsMargins(10, 5, 10, 5)
            
            # Wing name and engine type
            wing_name = wing_summary.get('wing_name', 'Unknown Wing')
            engine_type = wing_summary.get('engine_type', 'unknown')
            engine_display = engine_type.replace('_', ' ').title()
            
            title_label = QLabel(f"📊 {wing_name}")
            title_label.setStyleSheet("font-weight: bold; font-size: 11pt; color: #00FFFF;")
            header_layout.addWidget(title_label)
            
            engine_label = QLabel(f"Engine: {engine_display}")
            engine_label.setStyleSheet("font-size: 9pt; color: #94A3B8;")
            header_layout.addWidget(engine_label)
            
            header_layout.addStretch()
            
            # Statistics
            total_matches = wing_summary.get('total_matches', 0)
            matches_label = QLabel(f"Matches: {total_matches:,}")
            matches_label.setStyleSheet("font-size: 9pt; color: #4CAF50; font-weight: bold;")
            header_layout.addWidget(matches_label)
            
            execution_time = wing_summary.get('execution_time', 0)
            time_display = format_time_duration(execution_time)
            time_label = QLabel(f"Time: {time_display}")
            time_label.setStyleSheet("font-size: 9pt; color: #94A3B8;")
            header_layout.addWidget(time_label)
            
            # Execution ID (truncated)
            execution_id = wing_summary.get('execution_id', 'N/A')
            # Convert to string if it's an integer
            exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id
            exec_id_display = exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str
            exec_label = QLabel(f"ID: {exec_id_display}")
            exec_label.setStyleSheet("font-size: 8pt; color: #64748B;")
            exec_label.setToolTip(f"Execution ID: {exec_id_str}")
            header_layout.addWidget(exec_label)
            
            summary_layout.addWidget(header_frame)
            
            # Wing-specific chart (using existing chart rendering methods)
            feather_metadata = wing_summary.get('feather_metadata', {})
            if feather_metadata:
                chart_widget = None
                
                if engine_type == 'identity_based':
                    chart_widget = self._render_identity_charts(feather_metadata)
                elif engine_type in ['time_window_scanning', 'time_based']:
                    # For time-based, we might not have time_windows in summary
                    # Use feather_metadata to create a chart
                    chart_widget = self._render_identity_charts(feather_metadata)  # Reuse identity chart for feather stats
                
                if chart_widget:
                    chart_widget.setMaximumHeight(200)  # Compact chart for wing summary
                    summary_layout.addWidget(chart_widget)
            
            return summary_widget
            
        except Exception as e:
            print(f"[Error] Failed to create wing summary section: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_identity_viewer(self, database_path: str, execution_id: str, show_progress=True):
        """
        Create and populate Identity-Based results viewer.
        
        Args:
            database_path: Path to the database
            execution_id: Execution ID to load
            show_progress: If False, suppresses the progress dialog
        
        Requirements: 2.4, 3.1
        """
        try:
            from .identity_results_view import IdentityResultsView
            
            print(f"[DynamicResultsTabWidget] Creating Identity viewer for execution {execution_id}")
            
            # Create viewer instance
            viewer = IdentityResultsView()
            
            # Load data from database using execution_id
            # We need to load the CorrelationResult from the database
            from pathlib import Path
            import sqlite3
            
            if not Path(database_path).exists():
                raise FileNotFoundError(f"Database not found: {database_path}")
            
            # Query database for this execution's results
            # For now, we'll create a minimal CorrelationResult-like object
            # The viewer expects a CorrelationResult object with matches
            from ..engine.correlation_result import CorrelationResult, CorrelationMatch
            
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Load matches for this execution (including semantic_data for Task 1)
            cursor.execute("""
                SELECT 
                    m.match_id,
                    m.anchor_feather_id,
                    m.anchor_artifact_type,
                    m.match_score,
                    m.feather_count,
                    m.time_spread_seconds,
                    m.matched_application,
                    m.matched_file_path,
                    m.timestamp,
                    m.feather_records,
                    m.weighted_score_value,
                    m.weighted_score_interpretation,
                    m.semantic_data
                FROM matches m
                JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (execution_id,))
            
            matches = []
            for row in cursor.fetchall():
                match_id, feather_id, artifact_type, score, feather_count, \
                time_spread, app, file_path, timestamp, feather_records_json, \
                weighted_score_value, weighted_score_interpretation, semantic_data_json = row
                
                # Parse JSON fields
                import json
                feather_records = json.loads(feather_records_json) if feather_records_json else {}
                
                # Parse semantic_data if present (Task 1 fix)
                semantic_data = None
                if semantic_data_json:
                    try:
                        semantic_data = json.loads(semantic_data_json)
                    except:
                        pass
                
                # Reconstruct weighted_score dict if values exist
                weighted_score = None
                if weighted_score_value is not None:
                    weighted_score = {
                        'score': weighted_score_value,
                        'interpretation': weighted_score_interpretation or ''
                    }
                
                match = CorrelationMatch(
                    match_id=match_id,
                    timestamp=timestamp,
                    feather_records=feather_records,
                    match_score=score,
                    feather_count=feather_count,
                    time_spread_seconds=time_spread,
                    anchor_feather_id=feather_id,
                    anchor_artifact_type=artifact_type,
                    matched_application=app,
                    matched_file_path=file_path,
                    weighted_score=weighted_score,
                    semantic_data=semantic_data
                )
                matches.append(match)
            
            # Load feather metadata
            cursor.execute("""
                SELECT feather_metadata 
                FROM results 
                WHERE execution_id = ? AND feather_metadata IS NOT NULL
                LIMIT 1
            """, (execution_id,))
            
            feather_metadata = {}
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    feather_metadata = json.loads(row[0])
                except:
                    pass
            
            # Load statistics from results table
            cursor.execute("""
                SELECT 
                    feathers_processed,
                    total_records_scanned,
                    execution_duration_seconds
                FROM results
                WHERE execution_id = ?
                LIMIT 1
            """, (execution_id,))
            
            stats_row = cursor.fetchone()
            feathers_processed = stats_row[0] if stats_row and stats_row[0] is not None else 0
            total_records_scanned = stats_row[1] if stats_row and stats_row[1] is not None else 0
            execution_duration_seconds = stats_row[2] if stats_row and stats_row[2] is not None else 0.0
            
            conn.close()
            
            print(f"[DynamicResultsTabWidget] Loaded {len(matches)} matches from database")
            print(f"[DynamicResultsTabWidget] Statistics: feathers={feathers_processed}, records={total_records_scanned}, time={execution_duration_seconds:.1f}s")
            
            # Create a minimal CorrelationResult object
            exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id
            result = CorrelationResult(
                wing_id=f"wing_{exec_id_str}",
                wing_name=f"Wing {exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str}",
                matches=matches,
                total_matches=len(matches),
                feather_metadata=feather_metadata,
                feathers_processed=feathers_processed,
                total_records_scanned=total_records_scanned,
                execution_duration_seconds=execution_duration_seconds
            )
            
            # Load into viewer (suppress progress dialog since parent already shows one)
            viewer.load_from_correlation_result(result, show_progress=show_progress)
            
            return viewer
            
        except Exception as e:
            print(f"[Error] Failed to create identity viewer: {e}")
            import traceback
            traceback.print_exc()
            
            # Return viewer with error message
            from .identity_results_view import IdentityResultsView
            viewer = IdentityResultsView()
            
            # Create error message widget
            error_label = QLabel(f"Failed to load identity results:\n{str(e)}")
            error_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10pt;
                    padding: 15px;
                    background-color: #2a2a2a;
                    border: 2px solid #ff9800;
                    border-radius: 5px;
                }
            """)
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setWordWrap(True)
            
            # Add error to viewer layout
            viewer.layout().insertWidget(0, error_label)
            
            return viewer
    
    def _create_timebased_viewer(self, database_path: str, execution_id: str, show_progress=True):
        """
        Create and populate Time-Based results viewer from timebased_results_viewer.py.
        
        Args:
            database_path: Path to the database
            execution_id: Execution ID to load
            show_progress: If False, suppresses the progress dialog
        
        Requirements: 2.5, 3.2
        """
        try:
            from .timebased_results_viewer import TimeBasedResultsViewer
            
            print(f"[DynamicResultsTabWidget] Creating Time-Based viewer for execution {execution_id}")
            
            # Create viewer instance
            viewer = TimeBasedResultsViewer()
            
            # Set database path
            viewer.set_database_path(database_path)
            
            # Load data from database using execution_id
            from pathlib import Path
            import sqlite3
            
            if not Path(database_path).exists():
                raise FileNotFoundError(f"Database not found: {database_path}")
            
            # Query database for this execution's results
            from ..engine.correlation_result import CorrelationResult, CorrelationMatch
            
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Load matches for this execution (including semantic_data for Task 1)
            cursor.execute("""
                SELECT 
                    m.match_id,
                    m.anchor_feather_id,
                    m.anchor_artifact_type,
                    m.match_score,
                    m.feather_count,
                    m.time_spread_seconds,
                    m.matched_application,
                    m.matched_file_path,
                    m.timestamp,
                    m.feather_records,
                    m.weighted_score_value,
                    m.weighted_score_interpretation,
                    m.semantic_data
                FROM matches m
                JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (execution_id,))
            
            matches = []
            for row in cursor.fetchall():
                match_id, feather_id, artifact_type, score, feather_count, \
                time_spread, app, file_path, timestamp, feather_records_json, \
                weighted_score_value, weighted_score_interpretation, semantic_data_json = row
                
                # Parse JSON fields
                import json
                feather_records = json.loads(feather_records_json) if feather_records_json else {}
                
                # Parse semantic_data if present (Task 1 fix)
                semantic_data = None
                if semantic_data_json:
                    try:
                        semantic_data = json.loads(semantic_data_json)
                    except:
                        pass
                
                # Reconstruct weighted_score dict if values exist
                weighted_score = None
                if weighted_score_value is not None:
                    weighted_score = {
                        'score': weighted_score_value,
                        'interpretation': weighted_score_interpretation or ''
                    }
                
                match = CorrelationMatch(
                    match_id=match_id,
                    timestamp=timestamp,
                    feather_records=feather_records,
                    match_score=score,
                    feather_count=feather_count,
                    time_spread_seconds=time_spread,
                    anchor_feather_id=feather_id,
                    anchor_artifact_type=artifact_type,
                    matched_application=app,
                    matched_file_path=file_path,
                    weighted_score=weighted_score,
                    semantic_data=semantic_data
                )
                matches.append(match)
            
            # Load feather metadata
            cursor.execute("""
                SELECT feather_metadata 
                FROM results 
                WHERE execution_id = ? AND feather_metadata IS NOT NULL
                LIMIT 1
            """, (execution_id,))
            
            feather_metadata = {}
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    feather_metadata = json.loads(row[0])
                except:
                    pass
            
            # Load statistics from results table
            cursor.execute("""
                SELECT 
                    feathers_processed,
                    total_records_scanned,
                    execution_duration_seconds
                FROM results
                WHERE execution_id = ?
                LIMIT 1
            """, (execution_id,))
            
            stats_row = cursor.fetchone()
            feathers_processed = stats_row[0] if stats_row and stats_row[0] is not None else 0
            total_records_scanned = stats_row[1] if stats_row and stats_row[1] is not None else 0
            execution_duration_seconds = stats_row[2] if stats_row and stats_row[2] is not None else 0.0
            
            conn.close()
            
            print(f"[DynamicResultsTabWidget] Loaded {len(matches)} matches from database")
            print(f"[DynamicResultsTabWidget] Statistics: feathers={feathers_processed}, records={total_records_scanned}, time={execution_duration_seconds:.1f}s")
            
            # Create a minimal CorrelationResult object
            exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id
            result = CorrelationResult(
                wing_id=f"wing_{exec_id_str}",
                wing_name=f"Wing {exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str}",
                matches=matches,
                total_matches=len(matches),
                feather_metadata=feather_metadata,
                feathers_processed=feathers_processed,
                total_records_scanned=total_records_scanned,
                execution_duration_seconds=execution_duration_seconds
            )
            
            # Load into viewer (suppress progress dialog since parent already shows one)
            viewer.load_from_correlation_result(result, show_progress=show_progress)
            
            return viewer
            
        except Exception as e:
            print(f"[Error] Failed to create time-based viewer: {e}")
            import traceback
            traceback.print_exc()
            
            # Return viewer with error message
            from .timebased_results_viewer import TimeBasedResultsViewer
            viewer = TimeBasedResultsViewer()
            
            # Create error message widget
            error_label = QLabel(f"Failed to load time-based results:\n{str(e)}")
            error_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10pt;
                    padding: 15px;
                    background-color: #2a2a2a;
                    border: 2px solid #ff9800;
                    border-radius: 5px;
                }
            """)
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setWordWrap(True)
            
            # Add error to viewer layout
            viewer.layout().insertWidget(0, error_label)
            
            return viewer
    
    def load_last_results(self, output_dir: str, progress_callback=None) -> None:
        """
        Load the most recent execution results from output directory.
        
        NEW METHOD for "Load Last Results" button support.
        
        Process:
        1. Scan output directory for most recent execution
        2. Detect all wings from that execution
        3. Update Summary tab with aggregate statistics
        4. Create single Results tab with all wings combined as sub-tabs
        5. Handle both database and JSON formats
        
        Tab Structure Created:
        - Summary (index 0): Aggregate statistics, charts, wing breakdown
        - Results - Exec XXX (index 1): Combined viewer with wing sub-tabs
          ├── Wing 1 (sub-tab)
          ├── Wing 2 (sub-tab)
          └── Wing N (sub-tab)
        
        This keeps all wings from the same execution grouped together.
        
        Requirements: 5.1, 5.2, 5.3, 5.4, 9.1, 9.2, 9.3
        
        Args:
            output_dir: Path to output directory containing results
            progress_callback: Optional callback function(message: str, percent: int)
        """
        try:
            from pathlib import Path
            import sqlite3
            
            def update_progress(message: str, percent: int):
                """Helper to update progress if callback provided."""
                if progress_callback:
                    progress_callback(message, percent)
            
            print(f"[DynamicResultsTabWidget] Loading last results from: {output_dir}")
            update_progress("Checking output directory...", 10)
            
            # Check if output directory exists
            output_path = Path(output_dir)
            if not output_path.exists():
                print(f"[DynamicResultsTabWidget] ERROR: Output directory does not exist: {output_dir}")
                QMessageBox.warning(
                    self,
                    "Directory Not Found",
                    f"Output directory does not exist:\n{output_dir}"
                )
                return
            
            update_progress("Looking for database file...", 20)
            
            # Look for database file
            db_path = output_path / "correlation_results.db"
            if not db_path.exists():
                print(f"[DynamicResultsTabWidget] ERROR: Database file not found: {db_path}")
                QMessageBox.warning(
                    self,
                    "No Results Found",
                    f"No correlation results database found in:\n{output_dir}\n\nPlease run a correlation first."
                )
                return
            
            update_progress("Connecting to database...", 30)
            
            # Connect to database and find most recent execution
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            update_progress("Finding most recent execution...", 40)
            
            # Get the most recent execution_id
            cursor.execute("""
                SELECT execution_id, engine_type, execution_time
                FROM executions
                ORDER BY execution_time DESC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if not row:
                conn.close()
                print(f"[DynamicResultsTabWidget] ERROR: No executions found in database")
                QMessageBox.information(
                    self,
                    "No Results",
                    "No correlation executions found in the database.\n\nPlease run a correlation first."
                )
                return
            
            execution_id, engine_type, execution_time = row
            print(f"[DynamicResultsTabWidget] Found most recent execution: {execution_id} ({engine_type}) at {execution_time}")
            
            conn.close()
            
            update_progress(f"Detecting wings from execution {execution_id}...", 50)
            
            # Detect all wings from this execution
            wing_summaries = self._detect_wings_from_execution(str(db_path), execution_id)
            
            if not wing_summaries:
                print(f"[DynamicResultsTabWidget] ERROR: No wings found for execution {execution_id}")
                QMessageBox.information(
                    self,
                    "No Wings Found",
                    f"No wing data found for execution {execution_id}.\n\nThe execution may be incomplete or corrupted."
                )
                return
            
            print(f"[DynamicResultsTabWidget] Detected {len(wing_summaries)} wings for execution {execution_id}")
            
            # Calculate aggregate statistics first
            update_progress("Calculating aggregate statistics...", 60)
            
            aggregate_stats = {
                'total_wings_executed': len(wing_summaries),
                'total_matches_all_wings': sum(ws.get('total_matches', 0) for ws in wing_summaries),
                'execution_times': [ws.get('execution_time', 0) for ws in wing_summaries],
                'wing_summaries': wing_summaries,
                'feather_statistics': {}
            }
            
            # Aggregate feather statistics from all wings
            print(f"[DynamicResultsTabWidget] Aggregating feather statistics from {len(wing_summaries)} wings...")
            for wing_summary in wing_summaries:
                wing_feather_metadata = wing_summary.get('feather_metadata', {})
                wing_name = wing_summary.get('wing_name', 'Unknown')
                print(f"[DynamicResultsTabWidget]   Wing '{wing_name}': {len(wing_feather_metadata)} feathers in metadata")
                
                for feather_id, metadata in wing_feather_metadata.items():
                    if feather_id.startswith('_'):
                        continue
                    
                    if feather_id not in aggregate_stats['feather_statistics']:
                        aggregate_stats['feather_statistics'][feather_id] = {
                            'identities_found': 0,
                            'identities_extracted': 0,  # Add this for extraction rate
                            'records_processed': 0,
                            'matches_created': 0
                        }
                    
                    if isinstance(metadata, dict):
                        identities = metadata.get('identities_found', metadata.get('identities_final', 0))
                        extracted = metadata.get('identities_extracted', identities)  # Get extracted count
                        records = metadata.get('records_processed', 0)
                        matches = metadata.get('matches_created', 0)
                        
                        aggregate_stats['feather_statistics'][feather_id]['identities_found'] += identities
                        aggregate_stats['feather_statistics'][feather_id]['identities_extracted'] += extracted
                        aggregate_stats['feather_statistics'][feather_id]['records_processed'] += records
                        aggregate_stats['feather_statistics'][feather_id]['matches_created'] += matches
                        
                        print(f"[DynamicResultsTabWidget]     - {feather_id}: identities={identities}, extracted={extracted}, records={records}, matches={matches}")
                    else:
                        print(f"[DynamicResultsTabWidget]     - {feather_id}: metadata is not a dict (type={type(metadata)})")
            
            print(f"[DynamicResultsTabWidget] ✓ Aggregated statistics for {len(aggregate_stats['feather_statistics'])} feathers")
            
            # Don't clear existing tabs - add new tabs for this execution (Requirements 5.1, 5.2)
            update_progress("Creating new tabs...", 70)
            tab_widget = self.enhanced_tab_widget.tab_widget
            
            # Create Summary tab for this execution (Requirements 5.1, 5.2)
            update_progress("Creating Summary tab...", 75)
            
            # Create a new widget for the summary
            summary_widget = QWidget()
            summary_layout = QVBoxLayout(summary_widget)
            summary_layout.setContentsMargins(0, 0, 0, 0)
            
            # Build summary content (reuse update_summary_tab logic but in a new widget)
            exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id
            exec_id_display = exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str
            
            # Create scroll area for summary content
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.NoFrame)
            scroll_area.setStyleSheet("""
                QScrollArea {
                    background-color: #0B1220;
                    border: none;
                }
                QScrollBar:vertical {
                    background-color: #1E293B;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background-color: #475569;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #64748B;
                }
            """)
            
            # Create container widget for scroll area
            scroll_content = QWidget()
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(10, 10, 10, 10)
            scroll_layout.setSpacing(12)
            
            # Create aggregate statistics section - compact horizontal layout with execution ID
            stats_frame = QFrame()
            stats_frame.setStyleSheet("""
                QFrame {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
            stats_layout = QHBoxLayout(stats_frame)
            stats_layout.setContentsMargins(6, 4, 6, 4)
            stats_layout.setSpacing(4)
            
            # Title
            title_label = QLabel("Stats:")
            title_label.setStyleSheet("color: #00FFFF; font-size: 8pt; font-weight: bold;")
            stats_layout.addWidget(title_label)
            
            # All stats in one horizontal line including execution ID
            total_wings = aggregate_stats.get('total_wings_executed', 0)
            total_matches = aggregate_stats.get('total_matches_all_wings', 0)
            execution_times = aggregate_stats.get('execution_times', [])
            total_time = sum(execution_times) if execution_times else 0
            avg_matches = total_matches / total_wings if total_wings > 0 else 0
            
            # Format time for display
            time_display = format_time_duration(total_time)
            
            stats_text = QLabel(f"Exec ID: <span style='color:#00FFFF;font-weight:bold;'>{exec_id_display}</span> | "
                               f"Wings: <span style='color:#4CAF50;font-weight:bold;'>{total_wings}</span> | "
                               f"Matches: <span style='color:#4CAF50;font-weight:bold;'>{total_matches:,}</span> | "
                               f"Time: <span style='color:#00FFFF;font-weight:bold;'>{time_display}</span> | "
                               f"Avg: <span style='color:#FF9800;font-weight:bold;'>{avg_matches:.0f}</span>")
            stats_text.setStyleSheet("color: #94A3B8; font-size: 8pt;")
            stats_text.setTextFormat(Qt.RichText)
            stats_text.setToolTip(f"Full Execution ID: {exec_id_str}")
            stats_layout.addWidget(stats_text)
            stats_layout.addStretch()
            
            scroll_layout.addWidget(stats_frame)
            
            # Add charts if feather statistics available
            feather_statistics = aggregate_stats.get('feather_statistics', {})
            if feather_statistics:
                # Create charts frame
                charts_frame = QFrame()
                charts_frame.setStyleSheet("""
                    QFrame {
                        background-color: #0B1220;
                        border: 1px solid #334155;
                        border-radius: 4px;
                    }
                """)
                charts_layout = QVBoxLayout(charts_frame)
                charts_layout.setContentsMargins(8, 8, 8, 8)
                charts_layout.setSpacing(8)
                
                # Title
                charts_title = QLabel("Feather Statistics Charts")
                charts_title.setStyleSheet("color: #00FFFF; font-size: 9pt; font-weight: bold;")
                charts_layout.addWidget(charts_title)
                
                # Create horizontal layout for charts
                charts_row = QHBoxLayout()
                charts_row.setSpacing(10)
                
                # Chart 1: Matches by Feather (Bar Chart)
                matches_data = {}
                for feather_id, stats in feather_statistics.items():
                    if feather_id.startswith('_'):
                        continue
                    matches = stats.get('identities_found', stats.get('matches_created', 0))
                    if matches > 0:
                        matches_data[feather_id] = matches
                
                if matches_data:
                    sorted_data = dict(sorted(matches_data.items(), key=lambda x: x[1], reverse=True)[:10])
                    chart1 = PyQt5BarChart()
                    chart1.set_data(sorted_data, "Matches by Feather", "Matches")
                    chart1.setMinimumHeight(180)
                    chart1.show()  # Ensure chart is visible
                    charts_row.addWidget(chart1, stretch=1)
                
                # Chart 2: Records by Feather (Pie Chart with Breakdown)
                records_data = {}
                for feather_id, stats in feather_statistics.items():
                    if feather_id.startswith('_'):
                        continue
                    records = stats.get('records_processed', 0)
                    if records > 0:
                        records_data[feather_id] = records
                
                if records_data:
                    sorted_data = dict(sorted(records_data.items(), key=lambda x: x[1], reverse=True)[:10])
                    # Always use PyQt5PieChart with legend displayed as text labels
                    chart2 = PyQt5PieChart(show_legend=True)
                    chart2.set_data(sorted_data, "Records by Feather")
                    chart2.setMinimumHeight(200)
                    chart2.setMinimumWidth(700)  # Ensure enough width for pie + two-column legend
                    chart2.show()  # Ensure chart is visible
                    charts_row.addWidget(chart2, stretch=1)
                
                charts_layout.addLayout(charts_row)
                scroll_layout.addWidget(charts_frame)
                
                # Force update of charts to ensure they render
                QApplication.processEvents()
                print(f"[DynamicResultsTabWidget] ✓ Charts created and added to layout")
            
            # Add wing breakdown table
            wing_frame = QFrame()
            wing_frame.setStyleSheet("""
                QFrame {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
            wing_layout = QVBoxLayout(wing_frame)
            wing_layout.setContentsMargins(6, 4, 6, 4)
            wing_layout.setSpacing(4)
            
            wing_title = QLabel(f"Wing Breakdown ({total_wings} wings):")
            wing_title.setStyleSheet("color: #00FFFF; font-size: 8pt; font-weight: bold;")
            wing_layout.addWidget(wing_title)
            
            # Helper function to format time
            def format_time(seconds):
                """Format time as seconds, minutes, or hours"""
                if seconds < 60:
                    return f"{seconds:.1f}s"
                elif seconds < 3600:
                    return f"{seconds/60:.1f}m"
                else:
                    return f"{seconds/3600:.2f}h"
            
            wing_table = QTableWidget()
            wing_table.setColumnCount(4)
            wing_table.setHorizontalHeaderLabels(["Wing Name", "Engine Type", "Matches", "Time"])
            wing_table.horizontalHeader().setStretchLastSection(False)
            wing_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            wing_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            wing_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            wing_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            wing_table.verticalHeader().setVisible(False)
            wing_table.setEditTriggers(QTableWidget.NoEditTriggers)
            wing_table.setSelectionBehavior(QTableWidget.SelectRows)
            wing_table.setMaximumHeight(200)
            wing_table.setStyleSheet("""
                QTableWidget {
                    background-color: #0B1220;
                    color: #E2E8F0;
                    border: 1px solid #334155;
                    gridline-color: #334155;
                }
                QTableWidget::item {
                    padding: 4px;
                }
                QHeaderView::section {
                    background-color: #1E293B;
                    color: #00FFFF;
                    padding: 4px;
                    border: 1px solid #334155;
                    font-weight: bold;
                }
            """)
            
            wing_summaries = aggregate_stats.get('wing_summaries', [])
            wing_table.setRowCount(len(wing_summaries))
            
            for row, wing_summary in enumerate(wing_summaries):
                wing_name = wing_summary.get('wing_name', f'Wing {row}')
                engine_type = wing_summary.get('engine_type', 'unknown')
                matches = wing_summary.get('total_matches', 0)
                exec_time = wing_summary.get('execution_time', 0)
                
                wing_table.setItem(row, 0, QTableWidgetItem(wing_name))
                wing_table.setItem(row, 1, QTableWidgetItem(engine_type))
                
                matches_item = QTableWidgetItem(f"{matches:,}")
                matches_item.setForeground(QColor("#4CAF50"))
                wing_table.setItem(row, 2, matches_item)
                
                time_item = QTableWidgetItem(format_time(exec_time))
                time_item.setForeground(QColor("#00FFFF"))
                wing_table.setItem(row, 3, time_item)
            
            wing_layout.addWidget(wing_table)
            scroll_layout.addWidget(wing_frame)
            
            scroll_area.setWidget(scroll_content)
            summary_layout.addWidget(scroll_area)
            
            # Update the existing Summary tab (index 0) instead of adding a new one
            # The Summary tab was created in _create_summary_tab() during __init__
            existing_summary_tab = tab_widget.widget(0)
            if existing_summary_tab:
                # Replace the content of the existing Summary tab
                existing_layout = existing_summary_tab.layout()
                if existing_layout:
                    # Clear existing content
                    while existing_layout.count():
                        item = existing_layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    # Add new summary content
                    existing_layout.addWidget(scroll_area)
                    print(f"[DynamicResultsTabWidget] ✓ Updated existing Summary tab (index 0)")
                else:
                    # No layout, create one and add content
                    new_layout = QVBoxLayout(existing_summary_tab)
                    new_layout.setContentsMargins(0, 0, 0, 0)
                    new_layout.addWidget(scroll_area)
                    print(f"[DynamicResultsTabWidget] ✓ Created layout and updated Summary tab (index 0)")
                
                # Update tab title
                tab_widget.setTabText(0, f"Summary - Exec {exec_id_display}")
            else:
                # No existing Summary tab, add a new one (shouldn't happen)
                summary_tab_index = tab_widget.addTab(summary_widget, f"Summary - Exec {exec_id_display}")
                print(f"[DynamicResultsTabWidget] ✓ Summary tab created at index {summary_tab_index}")
            
            # Create single combined Results tab for all wings from this execution (Requirements 5.1, 5.3, 5.4)
            # All wings from the same execution are grouped together in one tab
            update_progress("Creating Results tab with all wings...", 85)
            
            # Create a tabbed widget to hold all wing viewers from this execution
            from PyQt5.QtWidgets import QTabWidget
            combined_viewer = QTabWidget()
            combined_viewer.setStyleSheet("""
                QTabWidget::pane {
                    border: 1px solid #334155;
                    background-color: #0B1220;
                }
                QTabBar::tab {
                    background-color: #1E293B;
                    color: #94A3B8;
                    padding: 6px 12px;
                    margin-right: 2px;
                    border: 1px solid #334155;
                    border-bottom: none;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background-color: #0B1220;
                    color: #00FFFF;
                    border-bottom: 2px solid #00FFFF;
                }
                QTabBar::tab:hover {
                    background-color: #334155;
                }
            """)
            
            # Add each wing as a sub-tab within the combined viewer
            for i, wing_summary in enumerate(wing_summaries):
                wing_name = wing_summary.get('wing_name', f'Wing {i}')
                engine_type = wing_summary.get('engine_type', 'unknown')
                database_path = wing_summary.get('database_path', str(db_path))
                
                progress_percent = 85 + int((i / len(wing_summaries)) * 10)
                update_progress(f"Loading {wing_name}...", progress_percent)
                
                print(f"[DynamicResultsTabWidget] Creating viewer for wing: {wing_name} ({engine_type})")
                
                # Create appropriate viewer based on engine type
                viewer = None
                if engine_type == 'identity_based':
                    viewer = self._create_identity_viewer(database_path, execution_id, show_progress=False)
                elif engine_type in ['time_window_scanning', 'time_based']:
                    viewer = self._create_timebased_viewer(database_path, execution_id, show_progress=False)
                
                if viewer:
                    combined_viewer.addTab(viewer, wing_name)
                    print(f"[DynamicResultsTabWidget]   ✓ Added {wing_name} to combined viewer")
            
            # Add the combined viewer as a single Results tab (Requirements 5.1, 5.3)
            # This keeps all wings from the same execution together
            tab_widget.addTab(combined_viewer, f"Results - Exec {exec_id_display}")
            print(f"[DynamicResultsTabWidget] ✓ Results tab created with {len(wing_summaries)} wings combined")
            
            update_progress("Loading complete!", 100)
            
            print(f"[DynamicResultsTabWidget] ✓ Successfully loaded last results: {len(wing_summaries)} wings, {aggregate_stats['total_matches_all_wings']} total matches")
            print(f"[DynamicResultsTabWidget] ✓ Created 2 tabs: Summary and Results (all wings combined) (Requirements 5.1, 5.2, 5.3)")
            
            QMessageBox.information(
                self,
                "Results Loaded",
                f"Successfully loaded results from execution {execution_id}\n\n"
                f"Wings: {len(wing_summaries)}\n"
                f"Total Matches: {aggregate_stats['total_matches_all_wings']:,}\n\n"
                f"Two tabs created:\n"
                f"  • Summary - Exec {exec_id_display}\n"
                f"  • Results - Exec {exec_id_display} (all {len(wing_summaries)} wings combined)"
            )
            
        except Exception as e:
            print(f"[DynamicResultsTabWidget] ERROR: Failed to load last results: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Error Loading Results",
                f"Failed to load last results:\n\n{str(e)}"
            )
    
    def _detect_wings_from_execution(self, database_path: str, execution_id: str) -> List[dict]:
        """
        Detect all wings from a specific execution.
        
        Requirements: 9.2, 9.5
        
        Args:
            database_path: Path to SQLite database
            execution_id: Execution ID to query
            
        Returns:
            List of wing_summary dicts sorted by wing_index
        """
        try:
            import sqlite3
            import json
            
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Query for all results in this execution
            cursor.execute("""
                SELECT 
                    r.result_id,
                    r.wing_id,
                    r.wing_name,
                    e.engine_type,
                    r.execution_id,
                    r.total_matches,
                    r.execution_duration_seconds,
                    r.feather_metadata
                FROM results r
                JOIN executions e ON r.execution_id = e.execution_id
                WHERE r.execution_id = ?
                ORDER BY r.result_id ASC
            """, (execution_id,))
            
            wing_summaries = []
            wing_index = 0  # Track wing index manually
            
            for row in cursor.fetchall():
                result_id, wing_id, wing_name, engine_type, exec_id, \
                total_matches, execution_duration, feather_metadata_json = row
                
                # Parse feather_metadata JSON
                feather_metadata = {}
                if feather_metadata_json:
                    try:
                        feather_metadata = json.loads(feather_metadata_json)
                        print(f"[DynamicResultsTabWidget] Parsed feather_metadata for '{wing_name}': {len(feather_metadata)} feathers")
                        # Log first few feather IDs for debugging
                        feather_ids = [fid for fid in feather_metadata.keys() if not fid.startswith('_')]
                        if feather_ids:
                            print(f"[DynamicResultsTabWidget]   Feather IDs: {feather_ids[:5]}{'...' if len(feather_ids) > 5 else ''}")
                    except Exception as e:
                        print(f"[DynamicResultsTabWidget] Warning: Failed to parse feather_metadata for wing {wing_name}: {e}")
                
                # Create wing summary dict
                wing_summary = {
                    'wing_name': wing_name or f"Wing {wing_index}",
                    'wing_index': wing_index,
                    'engine_type': engine_type or 'unknown',
                    'execution_id': exec_id,
                    'database_path': database_path,
                    'total_matches': total_matches or 0,
                    'execution_time': execution_duration or 0.0,
                    'feather_metadata': feather_metadata,
                    'timestamp': execution_duration  # Use execution_duration from results table
                }
                
                wing_index += 1  # Increment for next wing
                
                wing_summaries.append(wing_summary)
                print(f"[DynamicResultsTabWidget] Detected wing: {wing_name} (index={wing_index}, matches={total_matches})")
            
            conn.close()
            
            # Sort by wing_index to ensure correct order
            wing_summaries.sort(key=lambda x: x.get('wing_index', 0))
            
            return wing_summaries
            
        except Exception as e:
            print(f"[DynamicResultsTabWidget] ERROR: Failed to detect wings from execution: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def update_summary_tab(self, aggregate_stats: dict) -> None:
        """
        Update Summary tab with aggregate statistics across ALL wings.
        
        Requirements: 5.1, 5.2, 5.3
        
        Args:
            aggregate_stats: Dictionary containing:
                - total_wings_executed: int
                - total_matches_all_wings: int
                - feather_statistics: dict (combined across all wings)
                - execution_times: list
                - wing_summaries: list (individual wing summaries)
        """
        try:
            print(f"[DynamicResultsTabWidget] Updating Summary tab with aggregate statistics")
            
            # Get Summary tab (index 0)
            summary_tab = self.enhanced_tab_widget.tab_widget.widget(0)
            if not summary_tab:
                print("[DynamicResultsTabWidget] ERROR: Summary tab not found!")
                return
            
            # Clear existing content in summary tab
            summary_layout = summary_tab.layout()
            if not summary_layout:
                summary_layout = QVBoxLayout(summary_tab)
                summary_tab.setLayout(summary_layout)
            
            # Clear all widgets from summary tab
            while summary_layout.count():
                item = summary_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            # Apply Crow-Eye styling to summary tab
            summary_tab.setStyleSheet("""
                QWidget {
                    background-color: #0B1220;
                    color: #E2E8F0;
                }
                QLabel {
                    color: #E2E8F0;
                }
                QFrame {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 8px;
                }
            """)
            
            # Add Execution ID header (Requirements 3.1, 3.3)
            # Extract execution_id from wing_summaries
            wing_summaries = aggregate_stats.get('wing_summaries', [])
            execution_id = None
            if wing_summaries and len(wing_summaries) > 0:
                execution_id = wing_summaries[0].get('execution_id', None)
            
            # Create scroll area for summary content
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.NoFrame)
            scroll_area.setStyleSheet("""
                QScrollArea {
                    background-color: #0B1220;
                    border: none;
                }
                QScrollBar:vertical {
                    background-color: #1E293B;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background-color: #475569;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #64748B;
                }
            """)
            
            # Create container widget for scroll area
            scroll_content = QWidget()
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(10, 10, 10, 10)
            scroll_layout.setSpacing(12)
            
            # Create aggregate statistics section - compact horizontal layout
            stats_frame = QFrame()
            stats_frame.setStyleSheet("""
                QFrame {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 4px;
                }
            """)
            stats_layout = QHBoxLayout(stats_frame)
            stats_layout.setContentsMargins(6, 4, 6, 4)
            stats_layout.setSpacing(4)
            
            # Title
            title_label = QLabel("Stats:")
            title_label.setStyleSheet("color: #00FFFF; font-size: 8pt; font-weight: bold;")
            stats_layout.addWidget(title_label)
            
            # All stats in one horizontal line including execution ID
            total_wings = aggregate_stats.get('total_wings_executed', 0)
            total_matches = aggregate_stats.get('total_matches_all_wings', 0)
            execution_times = aggregate_stats.get('execution_times', [])
            total_time = sum(execution_times) if execution_times else 0
            avg_matches = total_matches / total_wings if total_wings > 0 else 0
            
            # Format time for display
            time_display = format_time_duration(total_time)
            
            # Format execution ID
            exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id if execution_id else "N/A"
            exec_id_display = exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str
            
            stats_text = QLabel(f"Exec ID: <span style='color:#00FFFF;font-weight:bold;'>{exec_id_display}</span> | "
                               f"Wings: <span style='color:#4CAF50;font-weight:bold;'>{total_wings}</span> | "
                               f"Matches: <span style='color:#4CAF50;font-weight:bold;'>{total_matches:,}</span> | "
                               f"Time: <span style='color:#00FFFF;font-weight:bold;'>{time_display}</span> | "
                               f"Avg: <span style='color:#FF9800;font-weight:bold;'>{avg_matches:.0f}</span>")
            stats_text.setStyleSheet("color: #94A3B8; font-size: 8pt;")
            stats_text.setTextFormat(Qt.RichText)
            if execution_id:
                stats_text.setToolTip(f"Full Execution ID: {exec_id_str}")
            stats_layout.addWidget(stats_text)
            stats_layout.addStretch()
            
            scroll_layout.addWidget(stats_frame)
            print(f"[DynamicResultsTabWidget] ✓ Stats with Execution ID added to Summary tab: {exec_id_str}")
            
            # Combine feather statistics from all wings
            feather_statistics = aggregate_stats.get('feather_statistics', {})
            
            print(f"[DynamicResultsTabWidget] feather_statistics from aggregate_stats: {len(feather_statistics)} feathers")
            
            # If feather_statistics is empty, try to aggregate from wing_summaries
            if not feather_statistics:
                print("[DynamicResultsTabWidget] feather_statistics empty, aggregating from wing_summaries...")
                wing_summaries = aggregate_stats.get('wing_summaries', [])
                print(f"[DynamicResultsTabWidget] Found {len(wing_summaries)} wing summaries")
                feather_statistics = {}
                
                for wing_summary in wing_summaries:
                    # CRITICAL FIX: feather_metadata is inside results array, not at wing_summary level
                    # wing_summary structure: {'results': [result_dict], 'wing_name': ..., 'execution_id': ...}
                    # result_dict structure: {'feather_metadata': {...}, 'matches': [...], ...}
                    
                    wing_feather_metadata = {}
                    
                    # Check if feather_metadata is at top level (legacy format)
                    if 'feather_metadata' in wing_summary:
                        wing_feather_metadata = wing_summary.get('feather_metadata', {})
                        print(f"[DynamicResultsTabWidget] Wing '{wing_summary.get('wing_name')}' has feather_metadata at top level: {len(wing_feather_metadata)} feathers")
                    # Check if results array exists (current format)
                    elif 'results' in wing_summary:
                        results_list = wing_summary.get('results', [])
                        print(f"[DynamicResultsTabWidget] Wing '{wing_summary.get('wing_name')}' has {len(results_list)} results")
                        
                        # Extract feather_metadata from first result (single wing execution)
                        if results_list and len(results_list) > 0:
                            first_result = results_list[0]
                            wing_feather_metadata = first_result.get('feather_metadata', {})
                            print(f"[DynamicResultsTabWidget] Extracted feather_metadata from results[0]: {len(wing_feather_metadata)} feathers")
                        else:
                            print(f"[DynamicResultsTabWidget] ⚠ No results in wing_summary for '{wing_summary.get('wing_name')}'")
                    else:
                        print(f"[DynamicResultsTabWidget] ⚠ Wing '{wing_summary.get('wing_name')}' has no feather_metadata or results")
                    
                    # Aggregate feather statistics
                    for feather_id, metadata in wing_feather_metadata.items():
                        if feather_id.startswith('_'):  # Skip metadata entries
                            continue
                        
                        if feather_id not in feather_statistics:
                            feather_statistics[feather_id] = {
                                'identities_found': 0,
                                'identities_extracted': 0,  # FIXED: Add identities_extracted
                                'records_processed': 0,
                                'matches_created': 0
                            }
                        
                        # Aggregate counts
                        if isinstance(metadata, dict):
                            feather_statistics[feather_id]['identities_found'] += metadata.get('identities_found', metadata.get('identities_final', 0))
                            feather_statistics[feather_id]['identities_extracted'] += metadata.get('identities_extracted', metadata.get('identities_found', 0))  # FIXED: Add with fallback
                            feather_statistics[feather_id]['records_processed'] += metadata.get('records_processed', 0)
                            feather_statistics[feather_id]['matches_created'] += metadata.get('matches_created', 0)
                            print(f"[DynamicResultsTabWidget]   - {feather_id}: identities={metadata.get('identities_found', 0)}, extracted={metadata.get('identities_extracted', 0)}, records={metadata.get('records_processed', 0)}, matches={metadata.get('matches_created', 0)}")
                
                print(f"[DynamicResultsTabWidget] After aggregation: {len(feather_statistics)} feathers with data")
            
            # Create charts section with three charts
            if feather_statistics:
                print(f"[DynamicResultsTabWidget] ✓ Creating charts for {len(feather_statistics)} feathers...")
                try:
                    charts_frame = QFrame()
                    charts_frame.setStyleSheet("""
                        QFrame {
                            background-color: #1E293B;
                            border: 1px solid #334155;
                            border-radius: 8px;
                            padding: 8px;
                        }
                    """)
                    charts_layout = QVBoxLayout(charts_frame)
                    charts_layout.setContentsMargins(8, 8, 8, 8)
                    charts_layout.setSpacing(10)
                    
                    charts_title = QLabel("Feather Statistics Charts")
                    charts_title.setStyleSheet("""
                        QLabel {
                            font-weight: bold;
                            font-size: 10pt;
                            color: #00FFFF;
                            padding: 2px;
                        }
                    """)
                    charts_layout.addWidget(charts_title)
                    
                    # Create horizontal layout for Chart 1 and Chart 2 side by side
                    charts_row = QHBoxLayout()
                    charts_row.setSpacing(10)
                    
                    # Chart 1: Identities/Matches Found per Feather (Bar Chart)
                    # Use identities_found for identity engine, matches_created for time-based engine
                    identities_data = {}
                    for feather_id, stats in feather_statistics.items():
                        if not feather_id.startswith('_'):
                            # Try identities_found first, then identities_final, then matches_created
                            count = stats.get('identities_found', 0)
                            if count == 0:
                                count = stats.get('identities_final', 0)
                            if count == 0:
                                count = stats.get('matches_created', 0)
                            if count > 0:
                                identities_data[feather_id] = count
                    
                    if identities_data:
                        sorted_data = dict(sorted(identities_data.items(), key=lambda x: x[1], reverse=True)[:10])
                        chart1 = PyQt5BarChart()
                        chart1.set_data(sorted_data, "Matches by Feather", "Matches")
                        chart1.setMinimumHeight(180)
                        charts_row.addWidget(chart1, stretch=1)
                        print(f"[DynamicResultsTabWidget] ✓ Chart 1 added: Matches Found ({len(sorted_data)} feathers)")
                    
                    # Chart 2: Records Processed per Feather (Pie Chart with Breakdown)
                    records_data = {}
                    for feather_id, stats in feather_statistics.items():
                        if not feather_id.startswith('_'):
                            count = stats.get('records_processed', 0)
                            if count > 0:
                                records_data[feather_id] = count
                    
                    if records_data:
                        sorted_data = dict(sorted(records_data.items(), key=lambda x: x[1], reverse=True)[:10])
                        # Always use PyQt5PieChart with legend displayed as text labels
                        chart2 = PyQt5PieChart(show_legend=True)
                        chart2.set_data(sorted_data, "Records by Feather")
                        chart2.setMinimumHeight(200)
                        chart2.setMinimumWidth(700)  # Ensure enough width for pie + two-column legend
                        charts_row.addWidget(chart2, stretch=1)
                        print(f"[DynamicResultsTabWidget] ✓ Chart 2 added: Records Pie ({len(sorted_data)} feathers)")

                    
                    charts_layout.addLayout(charts_row)
                    
                    # Chart 3: Feather Extraction Summary - Compact Grid Layout (4 per row)
                    extraction_frame = QFrame()
                    extraction_frame.setStyleSheet("""
                        QFrame {
                            background-color: #0B1220;
                            border: 1px solid #334155;
                            border-radius: 4px;
                        }
                    """)
                    extraction_layout = QVBoxLayout(extraction_frame)
                    extraction_layout.setContentsMargins(4, 4, 4, 4)
                    extraction_layout.setSpacing(2)
                    
                    extraction_title = QLabel("Evidence Extracted By Feathers")
                    extraction_title.setStyleSheet("color: #00FFFF; font-size: 8pt; font-weight: bold; padding: 1px;")
                    extraction_layout.addWidget(extraction_title)
                    
                    # Build extraction data with percentages
                    # Show evidence extraction rate: identities_extracted / records_processed
                    # Also show correlation rate: identities_found / extracted (secondary)
                    extraction_data = []
                    for feather_id, stats in feather_statistics.items():
                        if feather_id.startswith('_'):
                            continue
                        # Get extracted evidence count (identities_extracted)
                        extracted = stats.get('identities_extracted', 0)
                        if extracted == 0:
                            # Fallback to identities_found or matches_created
                            extracted = stats.get('identities_found', 0)
                        if extracted == 0:
                            extracted = stats.get('matches_created', 0)
                        
                        # Get correlated feathers count (identities_found or matches_created)
                        correlated = stats.get('identities_found', 0)
                        if correlated == 0:
                            correlated = stats.get('matches_created', 0)
                        
                        records = stats.get('records_processed', 0)
                        # Calculate extraction rate (PRIMARY - what percentage of records had evidence extracted)
                        extraction_percentage = (extracted / records * 100) if records > 0 else 0
                        # Calculate correlation rate (SECONDARY - what percentage of extracted became correlated)
                        correlation_percentage = (correlated / extracted * 100) if extracted > 0 else 0
                        extraction_data.append((feather_id, extracted, records, correlated, extraction_percentage, correlation_percentage))
                    
                    # Sort by extraction percentage descending (primary metric)
                    extraction_data.sort(key=lambda x: x[4], reverse=True)
                    
                    # Create compact grid layout - 4 items per row
                    grid_widget = QWidget()
                    grid_layout = QGridLayout(grid_widget)
                    grid_layout.setContentsMargins(0, 0, 0, 0)
                    grid_layout.setSpacing(3)
                    
                    items_per_row = 4
                    for idx, (feather_id, extracted, records, correlated, extraction_percentage, correlation_percentage) in enumerate(extraction_data):
                        row = idx // items_per_row
                        col = idx % items_per_row
                        
                        # Create compact card for each feather
                        card = QFrame()
                        # Color border based on PRIMARY extraction percentage
                        if extraction_percentage >= 50:
                            border_color = "#10B981"  # green
                        elif extraction_percentage >= 20:
                            border_color = "#F59E0B"  # yellow
                        else:
                            border_color = "#EF4444"  # red
                        
                        card.setStyleSheet(f"""
                            QFrame {{
                                background-color: #1E293B;
                                border: 1px solid {border_color};
                                border-radius: 3px;
                                padding: 2px;
                            }}
                        """)
                        card_layout = QVBoxLayout(card)
                        card_layout.setContentsMargins(4, 2, 4, 2)
                        card_layout.setSpacing(1)
                        
                        # Feather name (truncated if too long) - smaller font
                        display_name = feather_id if len(feather_id) <= 18 else feather_id[:15] + "..."
                        name_label = QLabel(display_name)
                        name_label.setStyleSheet("color: #E2E8F0; font-size: 7pt; font-weight: bold;")
                        name_label.setToolTip(feather_id)
                        card_layout.addWidget(name_label)
                        
                        # Stats line: Extracted / Records - smaller font
                        stats_label = QLabel(f"{extracted:,} / {records:,}")
                        stats_label.setStyleSheet("color: #94A3B8; font-size: 6pt;")
                        stats_label.setToolTip(f"Evidence Extracted: {extracted:,} | Total Records: {records:,}")
                        card_layout.addWidget(stats_label)
                        
                        # PRIMARY Percentage (Extraction Rate) - larger, bold, colored
                        pct_label = QLabel(f"{extraction_percentage:.1f}%")
                        pct_label.setStyleSheet(f"color: {border_color}; font-size: 8pt; font-weight: bold;")
                        pct_label.setToolTip(f"Extraction Rate: {extraction_percentage:.1f}% of records had evidence extracted")
                        card_layout.addWidget(pct_label)
                        
                        # SECONDARY Percentage (Correlation Rate) - smaller, gray
                        corr_label = QLabel(f"↳ {correlation_percentage:.1f}% correlated")
                        corr_label.setStyleSheet("color: #64748B; font-size: 5pt;")
                        corr_label.setToolTip(f"Correlation Rate: {correlation_percentage:.1f}% of extracted evidence resulted in correlations ({correlated:,} / {extracted:,})")
                        card_layout.addWidget(corr_label)
                        
                        grid_layout.addWidget(card, row, col)
                    
                    extraction_layout.addWidget(grid_widget)
                    charts_layout.addWidget(extraction_frame)
                    print(f"[DynamicResultsTabWidget] ✓ Chart 3 added: Extraction grid with {len(extraction_data)} feathers")
                    
                    scroll_layout.addWidget(charts_frame)
                    print(f"[DynamicResultsTabWidget] ✓ Charts frame added to scroll layout")
                    
                except Exception as e:
                    print(f"[DynamicResultsTabWidget] ✗ ERROR creating charts: {e}")
                import traceback
                traceback.print_exc()
            else:
                print("[DynamicResultsTabWidget] ⚠ WARNING: No feather_statistics available - charts not created")
                print(f"[DynamicResultsTabWidget] aggregate_stats keys: {list(aggregate_stats.keys())}")
                print(f"[DynamicResultsTabWidget] feather_statistics content: {aggregate_stats.get('feather_statistics', {})}")
                
                # Add a message to the summary tab
                no_charts_label = QLabel("⚠ No feather statistics available for charts")
                no_charts_label.setStyleSheet("color: #FF9800; font-size: 10pt; padding: 20px;")
                no_charts_label.setAlignment(Qt.AlignCenter)
                scroll_layout.addWidget(no_charts_label)
            
            # Add wing breakdown section (Requirements 4.1, 4.2, 4.3, 4.4)
            wing_summaries = aggregate_stats.get('wing_summaries', [])
            if wing_summaries:
                print(f"[DynamicResultsTabWidget] Creating wing breakdown table with {len(wing_summaries)} wings")
                
                breakdown_frame = QFrame()
                breakdown_frame.setStyleSheet("""
                    QFrame {
                        background-color: #1E293B;
                        border: 1px solid #334155;
                        border-radius: 8px;
                        padding: 8px;
                    }
                """)
                breakdown_layout = QVBoxLayout(breakdown_frame)
                breakdown_layout.setContentsMargins(8, 8, 8, 8)
                breakdown_layout.setSpacing(6)
                
                breakdown_title = QLabel(f"Wing Breakdown ({len(wing_summaries)} wings)")
                breakdown_title.setStyleSheet("""
                    QLabel {
                        font-weight: bold;
                        font-size: 10pt;
                        color: #00FFFF;
                        padding: 2px;
                    }
                """)
                breakdown_layout.addWidget(breakdown_title)
                
                # Create table for wing breakdown
                from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
                wing_table = QTableWidget()
                wing_table.setColumnCount(4)
                wing_table.setHorizontalHeaderLabels(["Wing Name", "Engine Type", "Matches", "Time"])
                wing_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
                wing_table.setAlternatingRowColors(True)
                wing_table.setStyleSheet("""
                    QTableWidget {
                        background-color: #0B1220;
                        gridline-color: #334155;
                        color: #E2E8F0;
                        border: 1px solid #334155;
                        border-radius: 4px;
                        font-size: 9pt;
                    }
                    QTableWidget::item {
                        padding: 4px;
                        border-bottom: 1px solid #334155;
                    }
                    QTableWidget::item:selected {
                        background-color: #334155;
                        color: #00FFFF;
                    }
                    QHeaderView::section {
                        background-color: #1E293B;
                        color: #00FFFF;
                        padding: 4px;
                        font-weight: bold;
                        font-size: 9pt;
                        border: none;
                        border-bottom: 2px solid #00FFFF;
                    }
                """)
                
                # Helper function to format time
                def format_time(seconds):
                    """Format time as seconds, minutes, or hours."""
                    if seconds < 60:
                        return f"{seconds:.1f}s"
                    elif seconds < 3600:
                        minutes = seconds / 60
                        return f"{minutes:.1f}m"
                    else:
                        hours = seconds / 3600
                        return f"{hours:.2f}h"
                
                # Set row count to match ALL wings (Requirements 4.1, 4.4)
                wing_table.setRowCount(len(wing_summaries))
                
                # Populate table with ALL wings - no filtering (Requirements 4.1, 4.2, 4.4)
                for row, wing_summary in enumerate(wing_summaries):
                    wing_name = wing_summary.get('wing_name', 'Unknown')
                    engine_type = wing_summary.get('engine_type', 'unknown').replace('_', ' ').title()
                    matches = wing_summary.get('total_matches', 0)
                    exec_time = wing_summary.get('execution_time', 0)
                    time_formatted = format_time(exec_time)
                    
                    print(f"[DynamicResultsTabWidget]   Row {row}: {wing_name} | {engine_type} | {matches:,} matches | {time_formatted}")
                    
                    wing_table.setItem(row, 0, QTableWidgetItem(wing_name))
                    wing_table.setItem(row, 1, QTableWidgetItem(engine_type))
                    wing_table.setItem(row, 2, QTableWidgetItem(f"{matches:,}"))
                    wing_table.setItem(row, 3, QTableWidgetItem(time_formatted))
                
                # Set minimum row height for better spacing
                wing_table.verticalHeader().setDefaultSectionSize(24)
                wing_table.verticalHeader().setVisible(False)
                
                breakdown_layout.addWidget(wing_table)
                scroll_layout.addWidget(breakdown_frame)
                
                print(f"[DynamicResultsTabWidget] ✓ Wing breakdown table created with {len(wing_summaries)} wings")
            else:
                print(f"[DynamicResultsTabWidget] ⚠ No wing summaries available for breakdown table")
            
            scroll_layout.addStretch()
            
            # Set scroll content
            scroll_area.setWidget(scroll_content)
            summary_layout.addWidget(scroll_area)
            
            print(f"[DynamicResultsTabWidget] ✓ Summary tab updated with aggregate statistics")
            print(f"  - Execution ID: {execution_id if execution_id else 'N/A'}")
            print(f"  - Total wings: {total_wings}")
            print(f"  - Total matches: {total_matches:,}")
            print(f"  - Total time: {total_time:.2f}s")
            print(f"  - Charts displayed: 3")
            print(f"  - Wing breakdown rows: {len(wing_summaries)}")
            
        except Exception as e:
            print(f"[Error] Failed to update summary tab: {e}")
            import traceback
            traceback.print_exc()


class ResultsViewer(QWidget):
    """
    Main Results Viewer Widget
    
    Provides a comprehensive interface for viewing, filtering, and analyzing correlation results.
    Integrates enhanced tab management, semantic mapping, and weighted scoring support.
    """
    
    # Signals
    results_loaded = pyqtSignal(str)  # output_dir
    match_selected = pyqtSignal(dict)  # match_data
    export_completed = pyqtSignal(str)  # export_path
    
    def __init__(self, parent=None):
        """Initialize the Results Viewer"""
        super().__init__(parent)
        
        # Initialize centralized score configuration manager
        # Requirements: 7.2, 8.4
        from ..config.score_configuration_manager import ScoreConfigurationManager
        self.score_config_manager = ScoreConfigurationManager()
        
        self.current_output_dir = None
        self.engine_type = "time_based"
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header section
        header_frame = self._create_header_section()
        layout.addWidget(header_frame)
        
        # Main content - use DynamicResultsTabWidget
        self.results_widget = DynamicResultsTabWidget()
        # Also create enhanced_tab_widget alias for compatibility
        self.enhanced_tab_widget = self.results_widget.enhanced_tab_widget
        layout.addWidget(self.results_widget)
        
        # Status bar
        self.status_label = QLabel("Ready to load results")
        self.status_label.setStyleSheet("color: #666; font-size: 9pt; padding: 2px;")
        layout.addWidget(self.status_label)
    
    def _create_header_section(self) -> QFrame:
        """Create the header section with controls"""
        frame = QFrame()
        frame.setMaximumHeight(50)
        frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Title
        title_label = QLabel("Correlation Results Viewer")
        title_label.setStyleSheet("font-weight: bold; font-size: 11pt; color: #00FFFF;")
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        # Engine type indicator
        self.engine_label = QLabel("Engine: Time-Based")
        self.engine_label.setStyleSheet("color: #94A3B8; font-size: 9pt;")
        layout.addWidget(self.engine_label)
        
        # Load results button
        load_btn = QPushButton("Load Results")
        load_btn.setMaximumWidth(100)
        load_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
                padding: 4px 8px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        load_btn.clicked.connect(self._load_results_dialog)
        layout.addWidget(load_btn)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMaximumWidth(70)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
                padding: 4px 8px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        refresh_btn.clicked.connect(self._refresh_results)
        layout.addWidget(refresh_btn)
        
        return frame
    
    def _connect_signals(self):
        """Connect internal signals"""
        if hasattr(self.results_widget, 'match_selected'):
            self.results_widget.match_selected.connect(self._on_match_selected)
    
    def _get_score_interpretation(self, score: float) -> str:
        """
        Get score interpretation using centralized configuration.
        
        Args:
            score: Score value to interpret (0.0 to 1.0)
        
        Returns:
            String interpretation ('Critical', 'High', 'Medium', 'Low', or 'Minimal')
        
        Requirements: 7.2, 8.4
        """
        config = self.score_config_manager.get_configuration()
        return config.interpret_score(score)
        
        if hasattr(self.results_widget, 'export_requested'):
            self.results_widget.export_requested.connect(self._on_export_requested)
    
    def _load_results_dialog(self):
        """Show dialog to select results directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Results Directory",
            self.current_output_dir or ".",
            QFileDialog.ShowDirsOnly
        )
        
        if directory:
            self.load_results(directory)
    
    def _refresh_results(self):
        """Refresh current results"""
        if self.current_output_dir:
            self.load_results(self.current_output_dir)
        else:
            QMessageBox.information(
                self,
                "No Results",
                "No results directory loaded. Please load results first."
            )
    
    def _on_match_selected(self, tab_id: str, match_data: dict):
        """Handle match selection from results widget"""
        self.match_selected.emit(match_data)
    
    def _on_export_requested(self, tab_id: str, export_options: dict):
        """Handle export request from results widget"""
        # The DynamicResultsTabWidget handles the export internally
        pass
    
    def load_results(self, output_dir: str, wing_id: Optional[str] = None, pipeline_id: Optional[str] = None):
        """
        Load correlation results from output directory
        
        Args:
            output_dir: Directory containing result files
            wing_id: Optional Wing ID for semantic mappings
            pipeline_id: Optional Pipeline ID for semantic mappings
        """
        try:
            # Handle None input
            if output_dir is None:
                self.status_label.setText("No directory specified")
                return
            
            self.current_output_dir = output_dir
            self.status_label.setText(f"Loading results from {output_dir}...")
            
            # Delegate to results widget
            self.results_widget.load_results(output_dir, wing_id, pipeline_id)
            
            # Update status
            result_count = len(self.results_widget.results_data)
            if result_count > 0:
                self.status_label.setText(f"Loaded {result_count} result sets from {output_dir}")
            else:
                self.status_label.setText(f"No results found in {output_dir}")
            
            # Emit signal
            self.results_loaded.emit(output_dir)
            
        except Exception as e:
            error_msg = f"Failed to load results: {str(e)}"
            self.status_label.setText(error_msg)
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
    
    def set_engine_type(self, engine_type: str):
        """Set the correlation engine type"""
        self.engine_type = engine_type
        self.results_widget.set_engine_type(engine_type)
        
        # Update engine label with visual indicator
        engine_display = {
            "time_based": "Time-Based",
            "time_window_scanning": "Time-Based",
            "identity_based": "Identity-Based"
        }.get(engine_type, f"{engine_type.title()}")
        
        self.engine_label.setText(f"Engine: {engine_display}")
        
        # Show warning for unrecognized engine types
        if engine_type not in ("time_based", "time_window_scanning", "identity_based"):
            print(f"[ResultsViewer] Warning: Unrecognized engine type '{engine_type}', defaulting to time_window_scanning")
    
    def clear_and_reconfigure(self, engine_type: str = None):
        """
        Clear all results and reconfigure display for a new engine type.
        
        This method should be called when switching between correlation engines
        to ensure the display is properly configured for the new engine type.
        
        Args:
            engine_type: Optional new engine type. If not provided, uses current engine type.
        """
        # Clear existing results
        self.clear_results()
        
        # Reconfigure for new engine type if provided
        if engine_type:
            self.set_engine_type(engine_type)
        
        # Clear all tabs in the results widget
        if hasattr(self.results_widget, 'enhanced_tab_widget'):
            self.results_widget.enhanced_tab_widget.clear_all_tabs()
        
        # Update status
        engine_display = {
            "time_based": "Time-Based",
            "time_window_scanning": "Time-Based",
            "identity_based": "Identity-Based"
        }.get(self.engine_type, self.engine_type)
        
        self.status_label.setText(f"Ready for {engine_display} correlation results")
    
    def update_semantic_mappings(self, semantic_mappings: Dict[str, Any]):
        """Update semantic mappings for all result tabs"""
        self.results_widget.update_global_semantic_mappings(semantic_mappings)
    
    def update_scoring_configuration(self, scoring_config: Dict[str, Any]):
        """Update scoring configuration for all result tabs"""
        self.results_widget.update_global_scoring_configuration(scoring_config)
    
    def get_current_results(self) -> Dict[str, Any]:
        """Get currently loaded results data"""
        return self.results_widget.results_data
    
    def clear_results(self):
        """Clear all loaded results"""
        self.results_widget.results_data.clear()
        self.current_output_dir = None
        self.status_label.setText("Ready to load results")
    
    def export_all_results(self, export_path: str, export_format: str = "json"):
        """
        Export all results to file
        
        Args:
            export_path: Path to export file
            export_format: Export format (json, csv, xlsx)
        """
        try:
            # Use the results exporter
            from .results_exporter import export_results_with_progress
            
            # Get all tab states for export
            all_tab_states = {}
            if hasattr(self.results_widget, 'enhanced_tab_widget'):
                all_tab_states = self.results_widget.enhanced_tab_widget.get_all_tab_states()
            
            # Convert to export format
            export_data = {}
            for state_id, tab_state in all_tab_states.items():
                export_data[state_id] = {
                    'tab_id': tab_state.tab_id,
                    'wing_name': tab_state.wing_name,
                    'matches': [match.to_dict() for match in tab_state.result.matches],
                    'semantic_mappings': tab_state.semantic_mappings,
                    'scoring_configuration': tab_state.scoring_configuration
                }
            
            # Export configuration
            export_config = {
                'export_path': export_path,
                'format': export_format,
                'data': export_data,
                'include_semantic': True,
                'include_scoring': True
            }
            
            # Perform export
            success, message = export_results_with_progress(export_config, self)
            
            if success:
                self.export_completed.emit(export_path)
                QMessageBox.information(self, "Export Complete", f"Results exported to:\n{export_path}")
            else:
                QMessageBox.warning(self, "Export Failed", f"Export failed:\n{message}")
        
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Export error:\n{str(e)}")