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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = {}  # {label: value}
        self.title = "Pie Chart"
        self.setMinimumHeight(300)
        self.setMinimumWidth(400)
        self.hovered_slice = -1
        self.setMouseTracking(True)
        
        # Store slice angles for hover detection
        self.slice_angles = []
        
    def set_data(self, data: Dict[str, float], title: str = "Pie Chart"):
        """Set chart data and labels."""
        self.data = data
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        """Draw the pie chart."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        
        if not self.data:
            painter.drawText(self.rect(), Qt.AlignCenter, "No data available")
            return
        
        # Draw background
        painter.fillRect(self.rect(), QColor("#1a1a2e"))
        
        # Draw title
        painter.setPen(QPen(QColor("#ffffff")))
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRect(0, 5, width, 30), Qt.AlignCenter, self.title)
        
        # Calculate pie dimensions
        margin = 60
        legend_width = 180
        pie_size = min(width - legend_width - margin * 2, height - margin * 2 - 40)
        pie_x = margin
        pie_y = 40 + (height - 40 - pie_size) // 2
        
        # Calculate total
        total = sum(self.data.values())
        if total == 0:
            painter.drawText(self.rect(), Qt.AlignCenter, "No data available")
            return
        
        # Clear slice angles
        self.slice_angles = []
        
        # Draw pie slices
        start_angle = 0
        for i, (label, value) in enumerate(self.data.items()):
            # Calculate angle (in 1/16th of a degree for Qt)
            span_angle = int((value / total) * 360 * 16)
            
            # Store slice info for hover detection
            self.slice_angles.append((start_angle, span_angle, label, value))
            
            # Get color
            color = self.COLORS[i % len(self.COLORS)]
            
            # Highlight hovered slice
            if i == self.hovered_slice:
                color = color.lighter(130)
            
            # Draw slice
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor("#1a1a2e"), 2))
            painter.drawPie(pie_x, pie_y, pie_size, pie_size, start_angle, span_angle)
            
            start_angle += span_angle
        
        # Draw legend
        legend_x = pie_x + pie_size + 20
        legend_y = pie_y + 10
        legend_item_height = 25
        
        small_font = QFont()
        small_font.setPointSize(9)
        painter.setFont(small_font)
        
        for i, (label, value) in enumerate(self.data.items()):
            if legend_y + legend_item_height > height - 10:
                break  # Stop if we run out of space
            
            # Color box
            color = self.COLORS[i % len(self.COLORS)]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(120)))
            painter.drawRect(legend_x, legend_y, 15, 15)
            
            # Label and percentage
            percentage = (value / total * 100) if total > 0 else 0
            display_label = label if len(label) <= 15 else label[:12] + "..."
            legend_text = f"{display_label} ({percentage:.1f}%)"
            
            painter.setPen(QPen(QColor("#cccccc")))
            painter.drawText(QRect(legend_x + 20, legend_y, legend_width - 25, 20), 
                           Qt.AlignLeft | Qt.AlignVCenter, legend_text)
            
            legend_y += legend_item_height
    
    def mouseMoveEvent(self, event):
        """Handle mouse movement for hover effects."""
        pos = event.pos()
        
        # Calculate pie center and radius
        width = self.width()
        height = self.height()
        margin = 60
        legend_width = 180
        pie_size = min(width - legend_width - margin * 2, height - margin * 2 - 40)
        center_x = margin + pie_size // 2
        center_y = 40 + (height - 40 - pie_size) // 2 + pie_size // 2
        radius = pie_size // 2
        
        # Check if mouse is within pie
        dx = pos.x() - center_x
        dy = pos.y() - center_y
        distance = (dx * dx + dy * dy) ** 0.5
        
        new_hovered = -1
        
        if distance <= radius:
            # Calculate angle from center
            import math
            angle = math.atan2(-dy, dx)  # Negative dy because Qt y-axis is inverted
            angle_deg = math.degrees(angle)
            if angle_deg < 0:
                angle_deg += 360
            
            # Convert to Qt angle (starts at 3 o'clock, counter-clockwise)
            qt_angle = int(angle_deg * 16)
            
            # Find which slice contains this angle
            for i, (start, span, label, value) in enumerate(self.slice_angles):
                # Normalize angles
                end = start + span
                if start <= qt_angle < end:
                    new_hovered = i
                    total = sum(self.data.values())
                    percentage = (value / total * 100) if total > 0 else 0
                    QToolTip.showText(
                        self.mapToGlobal(pos),
                        f"{label}\nCount: {int(value):,}\nPercentage: {percentage:.1f}%"
                    )
                    break
        
        if new_hovered != self.hovered_slice:
            self.hovered_slice = new_hovered
            self.update()
    
    def leaveEvent(self, event):
        """Handle mouse leaving widget."""
        self.hovered_slice = -1
        self.update()


class PyQt5GroupedBarChart(QWidget):
    """
    A grouped bar chart widget using pure PyQt5.
    Shows multiple data series side by side for comparison.
    """
    
    # Color palette for series
    SERIES_COLORS = [
        QColor("#2196F3"),  # Blue - Records
        QColor("#4CAF50"),  # Green - Identities Extracted
        QColor("#F44336"),  # Red - Invalid Identities
        QColor("#FF9800"),  # Orange
        QColor("#9C27B0"),  # Purple
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = {}  # {label: {series1: value, series2: value, ...}}
        self.series_names = []  # ["Records", "Identities", "Invalid"]
        self.title = "Grouped Bar Chart"
        self.setMinimumHeight(300)
        self.setMinimumWidth(500)
        self.hovered_bar = (-1, -1)  # (group_index, series_index)
        self.setMouseTracking(True)
        
        # Store bar rectangles for hover detection
        self.bar_rects = []
        
    def set_data(self, data: Dict[str, Dict[str, float]], series_names: List[str], title: str = "Grouped Bar Chart"):
        """
        Set chart data with multiple series.
        
        Args:
            data: {label: {series_name: value, ...}}
            series_names: List of series names for legend
            title: Chart title
        """
        self.data = data
        self.series_names = series_names
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        """Draw the grouped bar chart."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        
        # Margins
        left_margin = 80
        right_margin = 20
        top_margin = 60
        bottom_margin = 100
        
        # Chart area
        chart_width = width - left_margin - right_margin
        chart_height = height - top_margin - bottom_margin
        
        if not self.data or chart_width <= 0 or chart_height <= 0:
            painter.drawText(self.rect(), Qt.AlignCenter, "No data available")
            return
        
        # Calculate max value for scaling
        max_value = 0
        for label_data in self.data.values():
            for value in label_data.values():
                max_value = max(max_value, value)
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
        
        # Draw legend
        legend_y = 35
        legend_x = left_margin
        small_font = QFont()
        small_font.setPointSize(9)
        painter.setFont(small_font)
        
        for i, series_name in enumerate(self.series_names):
            color = self.SERIES_COLORS[i % len(self.SERIES_COLORS)]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(120)))
            painter.drawRect(legend_x, legend_y, 12, 12)
            
            painter.setPen(QPen(QColor("#cccccc")))
            painter.drawText(QRect(legend_x + 16, legend_y - 2, 100, 16), 
                           Qt.AlignLeft | Qt.AlignVCenter, series_name)
            legend_x += 120
        
        # Draw Y-axis grid lines and labels
        num_grid_lines = 5
        painter.setPen(QPen(QColor("#444444")))
        
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
        num_groups = len(self.data)
        num_series = len(self.series_names)
        if num_groups == 0 or num_series == 0:
            return
            
        group_spacing = 20
        bar_spacing = 2
        total_group_spacing = group_spacing * (num_groups + 1)
        group_width = (chart_width - total_group_spacing) // num_groups
        bar_width = max(10, (group_width - bar_spacing * (num_series - 1)) // num_series)
        
        # Clear bar rectangles
        self.bar_rects = []
        
        # Draw bars
        for group_idx, (label, series_data) in enumerate(self.data.items()):
            group_x = left_margin + group_spacing + group_idx * (group_width + group_spacing)
            
            for series_idx, series_name in enumerate(self.series_names):
                value = series_data.get(series_name, 0)
                
                # Calculate bar position and size
                x = group_x + series_idx * (bar_width + bar_spacing)
                bar_height = int((value / max_value) * chart_height) if max_value > 0 else 0
                y = top_margin + chart_height - bar_height
                
                # Store bar rectangle for hover detection
                bar_rect = QRect(x, y, bar_width, bar_height)
                self.bar_rects.append((bar_rect, label, series_name, value, group_idx, series_idx))
                
                # Get color
                color = self.SERIES_COLORS[series_idx % len(self.SERIES_COLORS)]
                
                # Highlight hovered bar
                if (group_idx, series_idx) == self.hovered_bar:
                    color = color.lighter(130)
                
                # Draw bar
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color.darker(120), 1))
                painter.drawRect(bar_rect)
                
                # Draw value on top of bar (only if bar is tall enough)
                if bar_height > 20:
                    painter.setPen(QPen(QColor("#ffffff")))
                    value_text = f"{int(value):,}"
                    tiny_font = QFont()
                    tiny_font.setPointSize(7)
                    painter.setFont(tiny_font)
                    painter.drawText(QRect(x, y - 15, bar_width, 15), 
                                   Qt.AlignCenter, value_text)
            
            # Draw label below group (rotated)
            painter.save()
            label_x = group_x + group_width // 2
            label_y = top_margin + chart_height + 5
            
            # Truncate long labels
            display_label = label if len(label) <= 12 else label[:10] + "..."
            
            painter.translate(label_x, label_y)
            painter.rotate(45)
            painter.setPen(QPen(QColor("#cccccc")))
            painter.setFont(small_font)
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
        new_hovered = (-1, -1)
        
        for rect, label, series_name, value, group_idx, series_idx in self.bar_rects:
            if rect.contains(pos):
                new_hovered = (group_idx, series_idx)
                QToolTip.showText(
                    self.mapToGlobal(pos),
                    f"{label}\n{series_name}: {int(value):,}"
                )
                break
        
        if new_hovered != self.hovered_bar:
            self.hovered_bar = new_hovered
            self.update()
    
    def leaveEvent(self, event):
        """Handle mouse leaving widget."""
        self.hovered_bar = (-1, -1)
        self.update()


from .ui_styling import CorrelationEngineStyles


from ..engine.correlation_result import CorrelationResult, CorrelationMatch
from .scoring_breakdown_widget import ScoringBreakdownWidget
from .results_tab_widget import ResultsTabWidget
from .results_exporter import show_export_dialog, export_results_with_progress


class LoadingProgressDialog(QProgressDialog):
    """Helper class for showing loading progress with convenience methods."""
    
    def __init__(self, title: str, parent=None):
        super().__init__(title, "Cancel", 0, 100, parent)
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumDuration(500)  # Show after 500ms
        self.setAutoClose(True)
        self.setAutoReset(True)
        self.setWindowTitle("Loading")
    
    def update_progress(self, current: int, total: int, message: str = ""):
        """Update progress bar and message."""
        if total > 0:
            percentage = int((current / total) * 100)
            self.setValue(percentage)
        
        if message:
            self.setLabelText(f"{message}\n{current}/{total} items")
        
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
        """Initialize UI"""
        layout = QVBoxLayout(self)
        
        # Match info section
        info_group = QGroupBox("Match Information")
        info_layout = QFormLayout()
        
        self.match_id_label = QLabel("-")
        info_layout.addRow("Match ID:", self.match_id_label)
        
        self.timestamp_label = QLabel("-")
        info_layout.addRow("Timestamp:", self.timestamp_label)
        
        self.feather_count_label = QLabel("-")
        info_layout.addRow("Feather Count:", self.feather_count_label)
        
        self.time_spread_label = QLabel("-")
        info_layout.addRow("Time Spread:", self.time_spread_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Weighted scoring breakdown widget
        self.scoring_widget = ScoringBreakdownWidget()
        layout.addWidget(self.scoring_widget)
        
        # Feather records section
        self.records_text = QTextEdit()
        self.records_text.setReadOnly(True)
        layout.addWidget(QLabel("Feather Records:"))
        layout.addWidget(self.records_text)
    
    def display_match(self, match_data: dict):
        """Display match details with semantic value highlighting"""
        self.match_id_label.setText(match_data.get('match_id', '-'))
        self.timestamp_label.setText(match_data.get('timestamp', '-'))
        self.feather_count_label.setText(str(match_data.get('feather_count', 0)))
        self.time_spread_label.setText(f"{match_data.get('time_spread_seconds', 0):.1f} seconds")
        
        # Display weighted scoring using the dedicated widget
        weighted_score = match_data.get('weighted_score')
        self.scoring_widget.display_scoring(weighted_score)
        
        # Display feather records with semantic value highlighting
        records_text = ""
        feather_records = match_data.get('feather_records', {})
        
        for feather_id, record in feather_records.items():
            records_text += f"\n{'='*60}\n"
            records_text += f"Feather: {feather_id}\n"
            records_text += f"{'='*60}\n"
            
            # Separate fields into regular and semantic
            regular_fields = {}
            semantic_fields = {}
            
            for key, value in record.items():
                if key.endswith('_semantic'):
                    # Skip standalone semantic fields (we'll show them with display fields)
                    continue
                elif key.endswith('_display'):
                    # This is a formatted display field with semantic value
                    base_key = key.replace('_display', '')
                    semantic_fields[base_key] = value
                else:
                    regular_fields[key] = value
            
            # Display fields with semantic values highlighted
            for key, value in regular_fields.items():
                if key in semantic_fields:
                    # Use the display format (includes semantic value)
                    records_text += f"{key}: {semantic_fields[key]} ✨\n"
                else:
                    # Regular field
                    records_text += f"{key}: {value}\n"
        
        self.records_text.setPlainText(records_text)


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
    
    def _init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Add enhanced tab widget
        layout.addWidget(self.enhanced_tab_widget)
    
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
    
    def _render_identity_charts(self, feather_metadata: Dict):
        """Render charts for Identity Engine results using PyQt5 native chart."""
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
    
    def _render_timebased_charts(self, time_windows: List, feather_metadata: Dict = None):
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
            
            # If no time window data, try to use feather_metadata
            if not feather_timestamps and feather_metadata:
                print("[DynamicResultsTabWidget] Using feather_metadata for time-based chart")
                for feather_id, metadata in feather_metadata.items():
                    if isinstance(metadata, dict) and not feather_id.startswith('_'):
                        count = metadata.get('matches_created', metadata.get('identities_found', 0))
                        if count > 0:
                            feather_timestamps[feather_id] = count
            
            if not feather_timestamps:
                print("[DynamicResultsTabWidget] No time window data available")
                return None
            
            # Sort by value descending and limit to top 15
            sorted_data = dict(sorted(feather_timestamps.items(), key=lambda x: x[1], reverse=True)[:15])
            
            # Create PyQt5 native bar chart
            chart = PyQt5BarChart()
            chart.set_data(sorted_data, "Matches by Feather", "Match Count")
            
            # Store chart data for export
            chart.chart_data = {
                'feathers': list(sorted_data.keys()),
                'counts': list(sorted_data.values()),
                'title': 'Matches by Feather',
                'ylabel': 'Match Count'
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
            
            # Update the feather stats table and summary statistics in the enhanced_tab_widget
            if feather_metadata and hasattr(self.enhanced_tab_widget, 'update_feather_stats_from_data'):
                total_matches = first_result.total_matches if hasattr(first_result, 'total_matches') else len(first_result.matches) if hasattr(first_result, 'matches') else 0
                self.enhanced_tab_widget.update_feather_stats_from_data(feather_metadata, total_matches)
                print(f"[DynamicResultsTabWidget] Updated feather stats table with {len(feather_metadata)} feathers")
            
            # Update the full summary from the result
            if hasattr(self.enhanced_tab_widget, 'update_summary_from_result'):
                self.enhanced_tab_widget.update_summary_from_result(first_result, self.engine_type)
                print(f"[DynamicResultsTabWidget] Updated summary from result")
            
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
                        chart_widget = self._render_timebased_charts(time_windows, feather_metadata)
                    elif feather_metadata:
                        # Fallback: use feather_metadata directly if no time windows
                        print("[DynamicResultsTabWidget] Using feather_metadata fallback for time-based charts")
                        chart_widget = self._render_timebased_charts([], feather_metadata)
                    else:
                        print("[DynamicResultsTabWidget] WARNING: No time windows extracted")
                except Exception as e:
                    print(f"[DynamicResultsTabWidget] ERROR rendering time-based charts: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Add chart to layout if created
            if chart_widget:
                print(f"[DynamicResultsTabWidget] Chart widget created successfully: {type(chart_widget)}")
                
                # Setup context menu for export
                self._setup_chart_context_menu(chart_widget)
                
                # Remove existing chart container if present
                if hasattr(self, 'chart_container') and self.chart_container:
                    self.chart_container.setParent(None)
                    self.chart_container.deleteLater()
                
                # Create new chart container
                self.chart_container = QWidget()
                chart_layout = QVBoxLayout(self.chart_container)
                chart_layout.setContentsMargins(5, 5, 5, 5)
                
                # Add engine type label
                engine_display = self.engine_type.replace('_', ' ').title()
                engine_label = QLabel(f"📊 {engine_display} - Feather Statistics")
                engine_label.setStyleSheet("font-weight: bold; font-size: 12pt; color: #2196F3; padding: 5px;")
                chart_layout.addWidget(engine_label)
                
                # Create horizontal layout for bar chart and pie chart side by side
                charts_row = QHBoxLayout()
                
                # Add the bar chart widget
                chart_widget.setMinimumHeight(300)
                charts_row.addWidget(chart_widget, stretch=3)
                
                # Create and add pie chart if we have feather_metadata
                if feather_metadata:
                    try:
                        # Extract data for pie chart (top 10 feathers)
                        pie_data = {}
                        for feather_id, metadata in feather_metadata.items():
                            if isinstance(metadata, dict) and not feather_id.startswith('_'):
                                count = metadata.get('identities_found', metadata.get('identities_final', metadata.get('matches_created', 0)))
                                if count > 0:
                                    pie_data[feather_id] = count
                        
                        if pie_data:
                            # Sort and limit to top 10
                            sorted_pie_data = dict(sorted(pie_data.items(), key=lambda x: x[1], reverse=True)[:10])
                            
                            # Create pie chart
                            pie_chart = PyQt5PieChart()
                            pie_chart.set_data(sorted_pie_data, "Distribution by Feather")
                            pie_chart.setMinimumHeight(300)
                            
                            # Store chart data for export
                            pie_chart.chart_data = {
                                'feathers': list(sorted_pie_data.keys()),
                                'counts': list(sorted_pie_data.values()),
                                'title': 'Distribution by Feather'
                            }
                            
                            # Setup context menu for pie chart
                            self._setup_chart_context_menu(pie_chart)
                            
                            charts_row.addWidget(pie_chart, stretch=2)
                            print("[DynamicResultsTabWidget] ✓ Pie chart added")
                    except Exception as e:
                        print(f"[DynamicResultsTabWidget] Warning: Could not create pie chart: {e}")
                
                chart_layout.addLayout(charts_row)
                
                # Add second row with Records vs Identities grouped bar chart
                if feather_metadata:
                    try:
                        # Prepare data for grouped bar chart
                        grouped_data = {}
                        for feather_id, metadata in feather_metadata.items():
                            if isinstance(metadata, dict) and not feather_id.startswith('_'):
                                records = metadata.get('records_processed', metadata.get('total_records', 0))
                                identities = metadata.get('identities_final', metadata.get('identities_found', 0))
                                invalid = metadata.get('identities_filtered', metadata.get('invalid_identities', 0))
                                
                                if records > 0 or identities > 0:
                                    grouped_data[feather_id] = {
                                        'Records': records,
                                        'Identities': identities,
                                        'Invalid': invalid
                                    }
                        
                        if grouped_data:
                            # Sort by records descending and limit to top 10
                            sorted_grouped = dict(sorted(grouped_data.items(), 
                                                        key=lambda x: x[1]['Records'], 
                                                        reverse=True)[:10])
                            
                            # Create grouped bar chart
                            grouped_chart = PyQt5GroupedBarChart()
                            grouped_chart.set_data(sorted_grouped, 
                                                  ['Records', 'Identities', 'Invalid'],
                                                  "Records vs Identities Extracted vs Invalid")
                            grouped_chart.setMinimumHeight(300)
                            
                            # Store chart data for export
                            grouped_chart.chart_data = {
                                'feathers': list(sorted_grouped.keys()),
                                'series': ['Records', 'Identities', 'Invalid'],
                                'data': sorted_grouped,
                                'title': 'Records vs Identities Extracted vs Invalid'
                            }
                            
                            # Setup context menu
                            self._setup_chart_context_menu(grouped_chart)
                            
                            # Add label and chart
                            grouped_label = QLabel("📈 Records vs Identities Comparison")
                            grouped_label.setStyleSheet("font-weight: bold; font-size: 11pt; color: #4CAF50; padding: 5px; margin-top: 10px;")
                            chart_layout.addWidget(grouped_label)
                            chart_layout.addWidget(grouped_chart)
                            
                            print("[DynamicResultsTabWidget] ✓ Grouped bar chart added")
                    except Exception as e:
                        print(f"[DynamicResultsTabWidget] Warning: Could not create grouped bar chart: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Add export buttons
                export_layout = QHBoxLayout()
                export_png_btn = QPushButton("📷 Export Bar Chart as PNG")
                export_png_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 5px 15px; border-radius: 3px;")
                export_png_btn.clicked.connect(lambda: self._handle_export_png(chart_widget))
                export_layout.addWidget(export_png_btn)
                
                export_csv_btn = QPushButton("📊 Export Data as CSV")
                export_csv_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px 15px; border-radius: 3px;")
                export_csv_btn.clicked.connect(lambda: self._handle_export_csv(chart_widget))
                export_layout.addWidget(export_csv_btn)
                
                export_layout.addStretch()
                chart_layout.addLayout(export_layout)
                
                # Insert at top of main layout
                main_layout = self.layout()
                if main_layout:
                    main_layout.insertWidget(0, self.chart_container)
                    print("[DynamicResultsTabWidget] ✓ Chart container added to layout")
                else:
                    print("[DynamicResultsTabWidget] ERROR: No main layout found!")
                
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
                    feather_id, artifact_type, total_records, matches_count = row
                    if feather_id:  # Skip None feather_ids
                        feather_metadata[feather_id] = {
                            'feather_name': feather_id,
                            'artifact_type': artifact_type or 'Unknown',
                            'identities_found': matches_count,
                            'identities_final': matches_count,
                            'matches_created': matches_count,
                            'records_processed': total_records or 0,
                            'identities_extracted': matches_count,
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
                            'identities_found': matches_count,
                            'identities_final': matches_count,
                            'matches_created': matches_count,
                            'records_processed': 0,
                            'identities_extracted': matches_count,
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
        """Export chart to PNG file using QWidget.grab() for PyQt5 native charts."""
        try:
            # For PyQt5BarChart (native widget), use grab() to capture as pixmap
            if isinstance(chart_widget, PyQt5BarChart):
                pixmap = chart_widget.grab()
                if pixmap.save(filepath, "PNG"):
                    print(f"[Export] PyQt5 chart saved to: {filepath}")
                    return True
                else:
                    print(f"[Error] Failed to save pixmap to: {filepath}")
                    return False
            
            # For matplotlib charts (if available)
            elif hasattr(chart_widget, 'figure'):
                chart_widget.figure.savefig(filepath, dpi=300, bbox_inches='tight')
                print(f"[Export] Matplotlib chart saved to: {filepath}")
                return True
            
            # Fallback: try grab() on any QWidget
            elif hasattr(chart_widget, 'grab'):
                pixmap = chart_widget.grab()
                if pixmap.save(filepath, "PNG"):
                    print(f"[Export] Widget captured and saved to: {filepath}")
                    return True
                else:
                    print(f"[Error] Failed to save widget capture to: {filepath}")
                    return False
            else:
                QMessageBox.warning(self, "Export Error", "Chart widget does not support export")
                return False
            
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
            
            # For PyQt5BarChart, use standard Qt context menu
            if isinstance(chart_widget, PyQt5BarChart):
                chart_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                
                def show_context_menu(pos):
                    menu = QMenu(self)
                    
                    export_png_action = menu.addAction("📷 Export as PNG")
                    export_csv_action = menu.addAction("📊 Export Data as CSV")
                    
                    action = menu.exec_(chart_widget.mapToGlobal(pos))
                    
                    if action == export_png_action:
                        self._handle_export_png(chart_widget)
                    elif action == export_csv_action:
                        self._handle_export_csv(chart_widget)
                
                chart_widget.customContextMenuRequested.connect(show_context_menu)
                print("[DynamicResultsTabWidget] Context menu setup for PyQt5BarChart")
            
            # For matplotlib charts
            elif hasattr(chart_widget, 'mpl_connect'):
                def show_mpl_context_menu(event):
                    if event.button == 3:  # Right click
                        menu = QMenu(self)
                        
                        export_png_action = menu.addAction("📷 Export as PNG")
                        export_csv_action = menu.addAction("📊 Export Data as CSV")
                        
                        action = menu.exec_(chart_widget.mapToGlobal(QPoint(int(event.x), int(event.y))))
                        
                        if action == export_png_action:
                            self._handle_export_png(chart_widget)
                        elif action == export_csv_action:
                            self._handle_export_csv(chart_widget)
                
                chart_widget.mpl_connect('button_press_event', show_mpl_context_menu)
                print("[DynamicResultsTabWidget] Context menu setup for matplotlib chart")
            
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
        frame.setMaximumHeight(60)
        frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 6px;
            }
        """)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Title
        title_label = QLabel("Correlation Results Viewer")
        title_label.setStyleSheet("font-weight: bold; font-size: 12pt; color: #2c3e50;")
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        # Engine type indicator
        self.engine_label = QLabel("Engine: Time-Based")
        self.engine_label.setStyleSheet("color: #6c757d; font-size: 9pt;")
        layout.addWidget(self.engine_label)
        
        # Load results button
        load_btn = QPushButton("Load Results")
        load_btn.setMaximumWidth(100)
        load_btn.clicked.connect(self._load_results_dialog)
        layout.addWidget(load_btn)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMaximumWidth(70)
        refresh_btn.clicked.connect(self._refresh_results)
        layout.addWidget(refresh_btn)
        
        return frame
    
    def _connect_signals(self):
        """Connect internal signals"""
        if hasattr(self.results_widget, 'match_selected'):
            self.results_widget.match_selected.connect(self._on_match_selected)
        
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