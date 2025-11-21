"""
Loading Indicator - Visual feedback for loading operations.

This module provides loading spinners and progress indicators for timeline operations.
"""

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QProgressBar
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen
import math


class LoadingSpinner(QWidget):
    """
    Animated loading spinner widget.
    
    Displays a rotating spinner to indicate loading operations.
    """
    
    def __init__(self, parent=None, size=40):
        """
        Initialize the loading spinner.
        
        Args:
            parent: Parent widget
            size (int): Size of the spinner in pixels
        """
        super().__init__(parent)
        
        self.size = size
        self.angle = 0
        self.is_spinning = False
        
        # Setup widget
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._rotate)
        
    def start(self):
        """Start the spinner animation."""
        self.is_spinning = True
        self.timer.start(50)  # Update every 50ms
        self.show()
    
    def stop(self):
        """Stop the spinner animation."""
        self.is_spinning = False
        self.timer.stop()
        self.hide()
    
    def _rotate(self):
        """Rotate the spinner."""
        self.angle = (self.angle + 30) % 360
        self.update()
    
    def paintEvent(self, event):
        """
        Paint the spinner.
        
        Args:
            event: QPaintEvent
        """
        if not self.is_spinning:
            return
        
        # Safety check: ensure widget is valid and visible
        if not self.isVisible() or self.size == 0:
            return
            
        painter = QPainter(self)
        if not painter.isActive():
            return
            
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw rotating arcs
        center_x = self.size / 2
        center_y = self.size / 2
        radius = self.size / 2 - 4
        
        # Draw 8 arcs with decreasing opacity
        for i in range(8):
            angle = (self.angle + i * 45) % 360
            opacity = 255 - (i * 30)
            
            # Calculate arc position
            rad = math.radians(angle)
            x = center_x + radius * math.cos(rad)
            y = center_y + radius * math.sin(rad)
            
            # Draw arc
            pen = QPen(QColor(59, 130, 246, opacity))  # Blue with varying opacity
            pen.setWidth(3)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            
            arc_length = 6
            painter.drawLine(
                int(x - arc_length * math.cos(rad)),
                int(y - arc_length * math.sin(rad)),
                int(x),
                int(y)
            )
        
        painter.end()


class LoadingOverlay(QWidget):
    """
    Full-screen loading overlay with spinner, message, and progress bar.
    
    Displays a semi-transparent overlay with a spinner, optional message,
    and progress bar for per-artifact loading feedback.
    """
    
    def __init__(self, parent=None):
        """
        Initialize the loading overlay.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Setup overlay
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 41, 59, 180);
            }
        """)
        
        # Create layout
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        # Create spinner
        self.spinner = LoadingSpinner(self, size=60)
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)
        
        # Create message label
        self.message_label = QLabel("Loading...")
        self.message_label.setStyleSheet("""
            QLabel {
                color: #E2E8F0;
                font-size: 14px;
                font-weight: bold;
                background-color: transparent;
                padding: 10px;
            }
        """)
        self.message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message_label)
        
        # Create artifact type label (shows which artifact is being queried)
        self.artifact_label = QLabel("")
        self.artifact_label.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 13px;
                font-weight: 600;
                background-color: transparent;
                padding: 5px;
            }
        """)
        self.artifact_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.artifact_label)
        
        # Create progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #475569;
                border-radius: 5px;
                background-color: #1E293B;
                text-align: center;
                color: #E2E8F0;
                font-weight: bold;
                min-width: 300px;
                max-width: 400px;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 3px;
            }
        """)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignCenter)
        
        # Create event count label
        self.event_count_label = QLabel("")
        self.event_count_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 12px;
                background-color: transparent;
                padding: 5px;
            }
        """)
        self.event_count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.event_count_label)
        
        # Initially hidden
        self.hide()
        self.progress_bar.hide()
        self.artifact_label.hide()
        self.event_count_label.hide()
    
    def show_loading(self, message="Loading..."):
        """
        Show the loading overlay with a message.
        
        Args:
            message (str): Loading message to display
        """
        self.message_label.setText(message)
        self.spinner.start()
        self.show()
        self.raise_()
    
    def show_loading_with_progress(self, message="Loading...", current=0, total=100, artifact_type="", event_count=0):
        """
        Show the loading overlay with progress bar and per-artifact details.
        
        Args:
            message (str): Loading message to display
            current (int): Current progress value
            total (int): Total progress value
            artifact_type (str): Name of artifact type being queried
            event_count (int): Number of events loaded so far
        """
        self.message_label.setText(message)
        
        # Show artifact type if provided
        if artifact_type:
            self.artifact_label.setText(f"Querying {artifact_type}...")
            self.artifact_label.show()
        else:
            self.artifact_label.hide()
        
        # Update progress bar
        if total > 0:
            progress_percent = int((current / total) * 100)
            self.progress_bar.setValue(progress_percent)
            self.progress_bar.setFormat(f"{current}/{total} artifact types")
            self.progress_bar.show()
        else:
            self.progress_bar.hide()
        
        # Show event count if provided
        if event_count > 0:
            self.event_count_label.setText(f"{event_count:,} events loaded")
            self.event_count_label.show()
        else:
            self.event_count_label.hide()
        
        self.spinner.start()
        self.show()
        self.raise_()
    
    def update_progress(self, current, total, artifact_type="", event_count=0):
        """
        Update progress without changing the main message.
        
        Args:
            current (int): Current progress value
            total (int): Total progress value
            artifact_type (str): Name of artifact type being queried
            event_count (int): Number of events loaded so far
        """
        # Update artifact type
        if artifact_type:
            self.artifact_label.setText(f"Querying {artifact_type}...")
            self.artifact_label.show()
        
        # Update progress bar
        if total > 0:
            progress_percent = int((current / total) * 100)
            self.progress_bar.setValue(progress_percent)
            self.progress_bar.setFormat(f"{current}/{total} artifact types")
        
        # Update event count
        if event_count > 0:
            self.event_count_label.setText(f"{event_count:,} events loaded")
            self.event_count_label.show()
    
    def hide_loading(self):
        """Hide the loading overlay."""
        self.spinner.stop()
        self.progress_bar.hide()
        self.artifact_label.hide()
        self.event_count_label.hide()
        self.hide()
    
    def resizeEvent(self, event):
        """
        Handle resize to cover parent.
        
        Args:
            event: QResizeEvent
        """
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(event)


class ProgressIndicator(QWidget):
    """
    Progress bar indicator for long operations.
    
    Displays a progress bar with percentage and optional message.
    """
    
    cancelled = pyqtSignal()
    
    def __init__(self, parent=None):
        """
        Initialize the progress indicator.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Setup widget
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 41, 59, 220);
                border-radius: 8px;
                padding: 15px;
            }
        """)
        
        # Create layout
        layout = QVBoxLayout(self)
        
        # Message label
        self.message_label = QLabel("Processing...")
        self.message_label.setStyleSheet("""
            QLabel {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: bold;
                background-color: transparent;
            }
        """)
        layout.addWidget(self.message_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #475569;
                border-radius: 5px;
                background-color: #1E293B;
                text-align: center;
                color: #E2E8F0;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 3px;
            }
        """)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Initially hidden
        self.hide()
    
    def show_progress(self, message="Processing...", value=0):
        """
        Show the progress indicator.
        
        Args:
            message (str): Progress message
            value (int): Initial progress value (0-100)
        """
        self.message_label.setText(message)
        self.progress_bar.setValue(value)
        self.show()
        self.raise_()
    
    def update_progress(self, value, message=None):
        """
        Update progress value and optionally message.
        
        Args:
            value (int): Progress value (0-100)
            message (str, optional): New message
        """
        self.progress_bar.setValue(value)
        if message:
            self.message_label.setText(message)
    
    def hide_progress(self):
        """Hide the progress indicator."""
        self.hide()
