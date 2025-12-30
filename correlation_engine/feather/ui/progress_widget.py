"""
Progress Widget
Animated progress tracking with cyberpunk styling.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class ProgressWidget(QWidget):
    """Custom progress widget with cyberpunk styling."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the progress widget."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Status label
        self.status_label = QLabel("Processing...")
        self.status_label.setAlignment(Qt.AlignCenter)
        font = QFont("Consolas", 12, QFont.Bold)
        self.status_label.setFont(font)
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)
        
        # Stats label
        self.stats_label = QLabel("")
        self.stats_label.setAlignment(Qt.AlignCenter)
        stats_font = QFont("Consolas", 10)
        self.stats_label.setFont(stats_font)
        layout.addWidget(self.stats_label)
        
        # Timer label
        self.timer_label = QLabel("")
        self.timer_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.timer_label)
        
        # Animation timer
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate_progress)
        self.animation_value = 0
    
    def set_status(self, status: str):
        """Set the status message."""
        self.status_label.setText(status)
    
    def set_progress(self, value: int):
        """Set progress value (0-100)."""
        self.progress_bar.setValue(value)
    
    def set_stats(self, stats: str):
        """Set statistics text."""
        self.stats_label.setText(stats)
    
    def set_timer(self, time_str: str):
        """Set timer text."""
        self.timer_label.setText(time_str)
    
    def start_animation(self):
        """Start progress animation."""
        self.animation_timer.start(50)
    
    def stop_animation(self):
        """Stop progress animation."""
        self.animation_timer.stop()
    
    def animate_progress(self):
        """Animate progress bar."""
        self.animation_value = (self.animation_value + 1) % 100
        # Create pulsing effect
        if self.progress_bar.value() < 100:
            self.progress_bar.setFormat(f"{self.progress_bar.value()}% " + "." * (self.animation_value % 4))
