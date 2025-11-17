"""
Progress indicator components for data loading operations.
Provides visual feedback during long-running database operations with cyberpunk styling.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from typing import Optional
import time


class ProgressIndicator(QtWidgets.QWidget):
    """
    A non-blocking progress indicator for data loading operations.
    Supports both determinate (progress bar) and indeterminate (spinner) modes.
    
    Signals:
        cancelled: Emitted when user cancels the operation
    """
    
    cancelled = QtCore.pyqtSignal()
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        cancellable: bool = True
    ):
        """
        Initialize progress indicator.
        
        Args:
            parent: Parent widget
            cancellable: Whether to show a cancel button
        """
        super().__init__(parent)
        self._cancellable = cancellable
        self._is_indeterminate = True
        self._start_time = 0
        self._current_value = 0
        self._total_value = 0
        self._setup_ui()
        self._apply_styles()
        
    def _setup_ui(self):
        """Set up the user interface components."""
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Message label
        self.message_label = QtWidgets.QLabel("Loading...")
        self.message_label.setAlignment(QtCore.Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        main_layout.addWidget(self.message_label)
        
        # Progress bar (for determinate mode)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(self.progress_bar)
        
        # Details label (for showing counts, ETA, etc.)
        self.details_label = QtWidgets.QLabel("")
        self.details_label.setAlignment(QtCore.Qt.AlignCenter)
        self.details_label.setWordWrap(True)
        main_layout.addWidget(self.details_label)
        
        # Cancel button
        if self._cancellable:
            button_layout = QtWidgets.QHBoxLayout()
            button_layout.addStretch()
            
            self.cancel_button = QtWidgets.QPushButton("Cancel")
            self.cancel_button.setMinimumWidth(100)
            self.cancel_button.clicked.connect(self._on_cancel_clicked)
            button_layout.addWidget(self.cancel_button)
            
            button_layout.addStretch()
            main_layout.addLayout(button_layout)
        
        # Set initial state to indeterminate
        self.set_indeterminate()
        
    def _apply_styles(self):
        """Apply cyberpunk-themed styles to the widget."""
        # Widget background
        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                border: 2px solid #00FFFF;
                border-radius: 12px;
            }
        """)
        
        # Message label style
        self.message_label.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 16px;
                font-weight: 700;
                font-family: 'Segoe UI', sans-serif;
                background: transparent;
                border: none;
                letter-spacing: 0.5px;
                padding: 5px;
            }
        """)
        
        # Details label style
        self.details_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
                background: transparent;
                border: none;
                padding: 5px;
            }
        """)
        
        # Progress bar style with cyberpunk theme
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1E293B;
                border: 2px solid #334155;
                border-radius: 8px;
                text-align: center;
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
                min-height: 30px;
            }
            
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3B82F6,
                    stop:0.5 #00FFFF,
                    stop:1 #3B82F6
                );
                border-radius: 6px;
                margin: 2px;
            }
            
            QProgressBar[indeterminate="true"] {
                background-color: #1E293B;
                border: 2px solid #00FFFF;
            }
        """)
        
        # Cancel button style
        if self._cancellable:
            self.cancel_button.setStyleSheet("""
                QPushButton {
                    background-color: #EF4444;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: 600;
                    font-size: 13px;
                    font-family: 'Segoe UI', sans-serif;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                QPushButton:hover {
                    background-color: #F87171;
                    border: 1px solid #00FFFF;
                }
                QPushButton:pressed {
                    background-color: #B91C1C;
                }
            """)
        
    def _on_cancel_clicked(self):
        """Handle cancel button click."""
        if self._cancellable:
            self.cancelled.emit()
            
    def show_progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0
    ) -> None:
        """
        Update progress display.
        
        Args:
            message: Status message to display
            current: Current progress value
            total: Total value (0 for indeterminate)
        """
        self.message_label.setText(message)
        
        if total > 0:
            # Determinate mode
            self.set_determinate(total)
            self._current_value = current
            self._total_value = total
            
            # Update progress bar
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)
            
            # Calculate and display ETA
            self._update_eta(current, total)
        else:
            # Indeterminate mode
            self.set_indeterminate()
            self.details_label.setText("")
            
    def _update_eta(self, current: int, total: int):
        """
        Calculate and display estimated time remaining.
        
        Args:
            current: Current progress value
            total: Total value
        """
        if current == 0 or self._start_time == 0:
            self.details_label.setText(f"{current:,} / {total:,} records")
            return
            
        elapsed_time = time.time() - self._start_time
        
        if elapsed_time > 0 and current > 0:
            # Calculate rate and ETA
            rate = current / elapsed_time
            remaining = total - current
            
            if rate > 0:
                eta_seconds = remaining / rate
                
                # Format ETA
                if eta_seconds < 60:
                    eta_str = f"{int(eta_seconds)}s"
                elif eta_seconds < 3600:
                    minutes = int(eta_seconds / 60)
                    seconds = int(eta_seconds % 60)
                    eta_str = f"{minutes}m {seconds}s"
                else:
                    hours = int(eta_seconds / 3600)
                    minutes = int((eta_seconds % 3600) / 60)
                    eta_str = f"{hours}h {minutes}m"
                
                # Display details
                percentage = (current / total) * 100
                details = f"{current:,} / {total:,} records ({percentage:.1f}%) - ETA: {eta_str}"
                self.details_label.setText(details)
            else:
                self.details_label.setText(f"{current:,} / {total:,} records")
        else:
            self.details_label.setText(f"{current:,} / {total:,} records")
            
    def set_indeterminate(self) -> None:
        """Switch to indeterminate mode (spinner animation)."""
        self._is_indeterminate = True
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)  # This creates the indeterminate animation
        self.progress_bar.setProperty("indeterminate", "true")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        self._start_time = 0
        
    def set_determinate(self, total: int) -> None:
        """
        Switch to determinate mode (progress bar).
        
        Args:
            total: Total value for progress calculation
        """
        if self._is_indeterminate or self._total_value != total:
            self._is_indeterminate = False
            self._total_value = total
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.progress_bar.setProperty("indeterminate", "false")
            self.progress_bar.style().unpolish(self.progress_bar)
            self.progress_bar.style().polish(self.progress_bar)
            
            # Start timing for ETA calculation
            if self._start_time == 0:
                self._start_time = time.time()
                
    def hide_progress(self) -> None:
        """Hide the progress indicator."""
        self.hide()
        self._start_time = 0
        self._current_value = 0
        self._total_value = 0
        
    def reset(self):
        """Reset the progress indicator to initial state."""
        self.message_label.setText("Loading...")
        self.details_label.setText("")
        self.progress_bar.setValue(0)
        self._start_time = 0
        self._current_value = 0
        self._total_value = 0
        self.set_indeterminate()


class TableLoadingOverlay(QtWidgets.QWidget):
    """
    An overlay widget that displays over a table during loading.
    Provides a semi-transparent background with a progress indicator.
    
    Signals:
        cancelled: Emitted when user cancels the operation
    """
    
    cancelled = QtCore.pyqtSignal()
    
    def __init__(
        self,
        parent_table: QtWidgets.QTableWidget,
        cancellable: bool = True
    ):
        """
        Initialize overlay for a specific table.
        
        Args:
            parent_table: The table widget to overlay
            cancellable: Whether to show a cancel button
        """
        super().__init__(parent_table)
        self._parent_table = parent_table
        self._cancellable = cancellable
        self._setup_ui()
        self._apply_styles()
        
        # Initially hidden
        self.hide()
        
        # Connect to parent resize events
        parent_table.installEventFilter(self)
        
    def _setup_ui(self):
        """Set up the user interface components."""
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Center the progress indicator
        main_layout.addStretch()
        
        center_layout = QtWidgets.QHBoxLayout()
        center_layout.addStretch()
        
        # Create progress indicator
        self.progress_indicator = ProgressIndicator(
            parent=self,
            cancellable=self._cancellable
        )
        self.progress_indicator.setMinimumSize(400, 200)
        self.progress_indicator.setMaximumSize(600, 300)
        
        # Connect cancel signal
        self.progress_indicator.cancelled.connect(self._on_cancelled)
        
        center_layout.addWidget(self.progress_indicator)
        center_layout.addStretch()
        
        main_layout.addLayout(center_layout)
        main_layout.addStretch()
        
    def _apply_styles(self):
        """Apply cyberpunk-themed styles to the overlay."""
        # Semi-transparent dark background
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(11, 18, 32, 0.95);
            }
        """)
        
    def _on_cancelled(self):
        """Handle cancel signal from progress indicator."""
        self.cancelled.emit()
        
    def eventFilter(self, obj, event):
        """Handle parent widget events."""
        if obj == self._parent_table and event.type() == QtCore.QEvent.Resize:
            # Resize overlay to match parent
            self.resize(self._parent_table.size())
        return super().eventFilter(obj, event)
        
    def show_loading(self, message: str = "Loading data...") -> None:
        """
        Show the loading overlay.
        
        Args:
            message: Loading message to display
        """
        # Resize to match parent
        self.resize(self._parent_table.size())
        
        # Show overlay
        self.show()
        self.raise_()
        
        # Update progress indicator
        self.progress_indicator.show_progress(message)
        
        # Process events to ensure UI updates
        QtWidgets.QApplication.processEvents()
        
    def hide_loading(self) -> None:
        """Hide the loading overlay."""
        self.hide()
        self.progress_indicator.hide_progress()
        
    def update_progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0
    ) -> None:
        """
        Update the progress display.
        
        Args:
            message: Status message to display
            current: Current progress value
            total: Total value (0 for indeterminate)
        """
        self.progress_indicator.show_progress(message, current, total)
        
        # Process events to ensure UI updates
        QtWidgets.QApplication.processEvents()
        
    def set_indeterminate(self) -> None:
        """Switch to indeterminate mode."""
        self.progress_indicator.set_indeterminate()
        
    def set_determinate(self, total: int) -> None:
        """
        Switch to determinate mode.
        
        Args:
            total: Total value for progress calculation
        """
        self.progress_indicator.set_determinate(total)
