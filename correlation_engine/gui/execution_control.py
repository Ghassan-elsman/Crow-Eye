"""
Execution Control Widget
Orchestrate correlation engine execution and monitor progress.
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

# Set up logger
logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFileDialog, QLineEdit, QFormLayout,
    QMessageBox, QListWidget, QListWidgetItem, QComboBox, QDateTimeEdit,
    QCheckBox, QDialog, QInputDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject, QMetaType, QDateTime, QTimer
from PyQt5.QtGui import QFont, QTextCursor

# Register QTextCursor as a metatype to avoid warnings
QMetaType.type("QTextCursor")

from ..config import PipelineConfig
from ..pipeline import PipelineExecutor

# Import styles for calendar widget
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from styles import CrowEyeStyles


class OutputRedirector(QObject):
    """Redirects stdout/stderr to a QTextEdit widget"""
    
    output_written = pyqtSignal(str)
    
    def __init__(self, text_widget=None, original_stream=None):
        super().__init__()
        self.text_widget = text_widget
        self.original_stream = original_stream
        if text_widget:
            # Use Qt.QueuedConnection to ensure thread-safe updates
            # Use insertPlainText instead of append to avoid extra newlines
            self.output_written.connect(
                self._append_text,
                Qt.QueuedConnection
            )
    
    def _append_text(self, text):
        """Append text with single newline"""
        if self.text_widget:
            cursor = self.text_widget.textCursor()
            cursor.movePosition(cursor.End)
            # Add text with single newline (text was already stripped of trailing \n)
            cursor.insertText(text + '\n')
            self.text_widget.setTextCursor(cursor)
            self.text_widget.ensureCursorVisible()
    
    def write(self, text):
        """Write text to the widget"""
        try:
            # Only emit if there's actual content (not just whitespace/newlines)
            if text and text.strip():
                # Remove both leading and trailing newlines
                cleaned_text = text.strip('\n')
                if cleaned_text:  # Make sure there's still content after stripping
                    self.output_written.emit(cleaned_text)
            # DON'T write to original stream - causes double printing
        except RuntimeError:
            # Handle case where the widget has been deleted
            pass
    
    def flush(self):
        """Flush (required for file-like object)"""
        if self.original_stream:
            try:
                self.original_stream.flush()
            except:
                pass


class CorrelationEngineWrapper(QObject):
    """Wrapper for running correlation engine in background thread"""
    
    progress_updated = pyqtSignal(int, int, str)  # wing_index, total, status
    anchor_progress_updated = pyqtSignal(int, int)  # NEW: anchor_index, total_anchors
    execution_completed = pyqtSignal(dict)  # results summary
    wing_completed = pyqtSignal(dict)  # NEW: Signal for individual wing completion
    execution_failed = pyqtSignal(str)  # error message
    log_message = pyqtSignal(str)  # NEW: Signal for log messages from worker thread
    
    def __init__(self):
        super().__init__()
        self.executor: Optional[PipelineExecutor] = None
        self.pipeline_config: Optional[PipelineConfig] = None
        self.output_dir: str = ""
        self.progress_handler = None  # Reference to progress handler method
        self._original_stdout = None
        self._log_widget = None
        self.selected_wings = []  # NEW: List of wings to execute sequentially
        self.current_wing_index = 0  # NEW: Track current wing being executed
        self._cancelled = False  # NEW: Cancellation flag
        self._wing_summaries = []  # NEW: Track all wing summaries for aggregate statistics
    
    def set_pipeline(self, pipeline_config: PipelineConfig, output_dir: str, selected_wings=None, resume_execution_id: int = None):
        """Set pipeline configuration and output directory"""
        self.pipeline_config = pipeline_config
        self.output_dir = output_dir
        self.selected_wings = selected_wings or pipeline_config.wing_configs
        self.current_wing_index = 0
        self._cancelled = False
        self.resume_execution_id = resume_execution_id  # NEW: Resume functionality
    
    def set_log_widget(self, widget):
        """Set the log widget for output redirection"""
        self._log_widget = widget
    
    def set_progress_handler(self, handler):
        """Set progress handler method for detailed progress display"""
        self.progress_handler = handler
    
    def handle_engine_progress(self, event):
        """
        Handle progress events from correlation engine.
        
        This method receives ProgressEvent objects and emits Qt signals
        for the GUI to update the progress bar.
        """
        # Forward to progress handler if set (for detailed logging)
        if self.progress_handler:
            self.progress_handler(event)
        
        # Handle new ProgressEvent objects with ProgressEventType
        if hasattr(event, 'event_type') and hasattr(event, 'overall_progress'):
            # New progress tracking system
            from ..engine.progress_tracking import ProgressEventType
            
            if event.event_type == ProgressEventType.WINDOW_PROGRESS:
                # Update progress bar based on window progress
                progress = event.overall_progress
                if progress.total_windows > 0:
                    self.anchor_progress_updated.emit(progress.windows_processed, progress.total_windows)
            
            elif event.event_type == ProgressEventType.SCANNING_START:
                # Reset progress bar for new scanning
                progress = event.overall_progress
                self.anchor_progress_updated.emit(0, progress.total_windows)
            
            elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
                # Complete progress bar
                progress = event.overall_progress
                self.anchor_progress_updated.emit(progress.total_windows, progress.total_windows)
            
            elif event.event_type == ProgressEventType.WINDOW_COMPLETE:
                # Update progress on window completion
                progress = event.overall_progress
                if progress.total_windows > 0:
                    self.anchor_progress_updated.emit(progress.windows_processed, progress.total_windows)
        
        # Handle legacy event format (for backward compatibility)
        elif hasattr(event, 'event_type') and hasattr(event, 'data'):
            # Legacy progress event format
            if event.event_type == "anchor_progress":
                anchor_index = event.data.get('anchor_index', 0)
                total_anchors = event.data.get('total_anchors', 1)
                self.anchor_progress_updated.emit(anchor_index, total_anchors)
            
            elif event.event_type == "summary_progress":
                # Also emit on summary progress
                anchors_processed = event.data.get('anchors_processed', 0)
                total_anchors = event.data.get('total_anchors', 1)
                self.anchor_progress_updated.emit(anchors_processed, total_anchors)
    
    def run(self):
        """Execute correlation in worker thread - runs wings sequentially"""
        try:
            # Clear wing summaries from previous execution
            self._wing_summaries = []
            
            # Redirect stdout in this thread to emit signals
            class ThreadOutputRedirector:
                def __init__(self, signal, original):
                    self.signal = signal
                    self.original = original
                
                def write(self, text):
                    # Only emit if there's actual content (not just whitespace/newlines)
                    if text and text.strip():
                        # Remove both leading and trailing newlines
                        cleaned_text = text.strip('\n')
                        if cleaned_text:  # Make sure there's still content after stripping
                            self.signal.emit(cleaned_text)
                    # DON'T write to original - causes double printing
                
                def flush(self):
                    if self.original:
                        try:
                            self.original.flush()
                        except:
                            pass
            
            # Save original stdout and redirect
            self._original_stdout = sys.stdout
            sys.stdout = ThreadOutputRedirector(self.log_message, self._original_stdout)
            
            if not self.pipeline_config:
                error_msg = "No pipeline configuration set"
                self.execution_failed.emit(error_msg)
                return
            
            # Set output directory
            self.pipeline_config.output_directory = self.output_dir
            
            total_wings = len(self.selected_wings)
            
            # Execute each wing sequentially
            for wing_index, wing_config in enumerate(self.selected_wings, start=1):
                # Check for cancellation
                if self._cancelled:
                    self.log_message.emit(f"\n❌ Execution cancelled after {wing_index - 1} of {total_wings} wings")
                    break
                
                wing_name = getattr(wing_config, 'wing_name', f'Wing {wing_index}')
                
                self.progress_updated.emit(wing_index - 1, total_wings, f"Executing Wing {wing_index} of {total_wings}: {wing_name}")
                self.log_message.emit(f"\n{'='*60}")
                self.log_message.emit(f"EXECUTING WING {wing_index} OF {total_wings}: {wing_name}")
                self.log_message.emit(f"{'='*60}")
                
                # Create a copy of pipeline config with only this wing
                from copy import deepcopy
                single_wing_pipeline = deepcopy(self.pipeline_config)
                single_wing_pipeline.wing_configs = [wing_config]
                
                # CRITICAL FIX: Force generate_report to True to ensure execution_id is created
                # Without this, execution_id will be None and Summary tab won't load
                single_wing_pipeline.generate_report = True
                
                # Create executor for this wing
                self.executor = PipelineExecutor(single_wing_pipeline)
                
                # Register our progress handler to receive events
                self.executor.engine.register_progress_listener(self.handle_engine_progress)
                
                # Execute this wing - pass resume_execution_id if this is the first wing and we're resuming
                if wing_index == 1 and hasattr(self, 'resume_execution_id') and self.resume_execution_id:
                    # For resume, pass the execution_id to the engine's execute method
                    summary = self.executor.execute(resume_execution_id=self.resume_execution_id)
                else:
                    # Normal execution
                    summary = self.executor.execute()
                
                # DEBUG: Log what execute() returned
                self.log_message.emit(f"[DEBUG] execute() returned summary with keys: {list(summary.keys())}")
                self.log_message.emit(f"[DEBUG] generate_report config: {self.pipeline_config.generate_report}")
                self.log_message.emit(f"[DEBUG] execution_id in summary: {summary.get('execution_id')}")
                self.log_message.emit(f"[DEBUG] database_path in summary: {summary.get('database_path')}")
                self.log_message.emit(f"[DEBUG] engine_type in summary: {summary.get('engine_type')}")
                
                # Add wing-specific information to summary
                summary['wing_name'] = wing_name
                summary['wing_index'] = wing_index
                summary['total_wings'] = total_wings
                
                # Store wing summary for aggregate statistics
                self._wing_summaries.append(summary.copy())
                
                # Emit wing completion signal (for creating separate tab)
                self.wing_completed.emit(summary)
                
                self.log_message.emit(f"\n✓ Wing {wing_index} completed: {summary.get('total_matches', 0)} matches found")
            
            # All wings complete
            if not self._cancelled:
                self.progress_updated.emit(total_wings, total_wings, "All wings executed successfully")
                
                # DEBUG: Log summary contents before creating final_summary
                self.log_message.emit(f"\n[DEBUG] Last wing summary keys: {list(summary.keys())}")
                self.log_message.emit(f"[DEBUG] execution_id from summary: {summary.get('execution_id')}")
                self.log_message.emit(f"[DEBUG] database_path from summary: {summary.get('database_path')}")
                self.log_message.emit(f"[DEBUG] engine_type from summary: {summary.get('engine_type')}")
                
                # Aggregate statistics from all wings
                total_matches_all_wings = sum(ws.get('total_matches', 0) for ws in self._wing_summaries)
                execution_times = [ws.get('execution_time', 0) for ws in self._wing_summaries]
                
                # Emit final completion signal with aggregate statistics
                final_summary = {
                    'pipeline_name': self.pipeline_config.pipeline_name,
                    'total_wings_executed': total_wings,
                    'total_matches_all_wings': total_matches_all_wings,
                    'execution_times': execution_times,
                    'wing_summaries': self._wing_summaries,
                    'execution_complete': True,
                    # Include last wing's execution info for Summary tab
                    'execution_id': summary.get('execution_id'),
                    'database_path': summary.get('database_path'),
                    'engine_type': summary.get('engine_type', 'time_window_scanning')
                }
                
                # DEBUG: Log final_summary contents
                self.log_message.emit(f"[DEBUG] final_summary execution_id: {final_summary.get('execution_id')}")
                self.log_message.emit(f"[DEBUG] final_summary database_path: {final_summary.get('database_path')}")
                self.log_message.emit(f"[DEBUG] final_summary engine_type: {final_summary.get('engine_type')}")
                self.log_message.emit(f"[DEBUG] final_summary total_matches_all_wings: {final_summary.get('total_matches_all_wings')}")
                
                self.execution_completed.emit(final_summary)
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            self.execution_failed.emit(error_msg)
        finally:
            # Restore original stdout
            if self._original_stdout:
                sys.stdout = self._original_stdout
    
    def cancel(self):
        """Request cancellation of execution"""
        self._cancelled = True
        if self.executor:
            if hasattr(self.executor, '_cancelled'):
                self.executor._cancelled = True
            if hasattr(self.executor, 'request_cancellation'):
                self.executor.request_cancellation("User requested cancellation")


class ExecutionControlWidget(QWidget):
    """Widget for controlling correlation execution"""
    
    execution_started = pyqtSignal()
    execution_completed = pyqtSignal(dict)
    wing_completed = pyqtSignal(dict)  # NEW: Signal for individual wing completion
    load_results_requested = pyqtSignal(dict)  # Signal to request loading results
    progress_message = pyqtSignal(str)  # Signal for thread-safe progress messages
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.current_pipeline: Optional[PipelineConfig] = None
        self.worker_thread: Optional[QThread] = None
        self.engine_wrapper: Optional[CorrelationEngineWrapper] = None
        
        # Store original stdout/stderr
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.stdout_redirector = None
        self.stderr_redirector = None
        
        # Progress throttling state
        self._last_progress_time: Optional[datetime] = None
        self._min_progress_interval: float = 0.5  # Minimum 0.5 seconds between progress updates
        self._last_progress_message: str = ""
        
        # NEW: Performance optimization components (Task 5)
        from .performance_utils import ProgressThrottler, ProgressEventQueue, BatchedTextWidget, OptimizedHeartbeat, ProgressMessageBuffer
        
        self._progress_throttler = None  # Will be initialized after UI
        self._event_queue = ProgressEventQueue(max_size=1000)
        self._batched_log = None  # Will be initialized after UI
        self._heartbeat = None  # Will be initialized after UI
        self._processing_timer = QTimer()
        self._processing_timer.timeout.connect(self._process_event_queue)
        
        # NEW: Memory-bounded progress message storage (Task 12)
        self._progress_message_buffer = ProgressMessageBuffer(max_messages=1000, trim_count=200)
        
        # NEW: Periodic trimming timer (Task 7)
        self._trimming_timer = QTimer()
        self._trimming_timer.timeout.connect(self._periodic_trim_check)
        self._trimming_timer.setInterval(30000)  # Check every 30 seconds
        
        self._init_ui()
        
        # Initialize performance components that depend on UI widgets
        self._progress_throttler = ProgressThrottler(min_interval_ms=150)  # Increased from 100ms to 150ms for less frequent updates
        self._batched_log = BatchedTextWidget(self.log_output, batch_window_ms=300)  # Increased from 200ms to 300ms for even less frequent updates
        self._heartbeat = OptimizedHeartbeat(self.progress_bar, interval_ms=500)
        
        # Setup output redirection after UI is initialized
        self._setup_output_redirection()
        
        # Connect progress message signal to append method with QueuedConnection
        self.progress_message.connect(self._append_to_log, Qt.QueuedConnection)
    
    def _setup_output_redirection(self):
        """Setup stdout/stderr redirection to the log output widget"""
        # Create redirectors that write to both the widget and original streams
        self.stdout_redirector = OutputRedirector(self.log_output, self.original_stdout)
        self.stderr_redirector = OutputRedirector(self.log_output, self.original_stderr)
        
        # Redirect stdout and stderr
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stderr_redirector
    
    def _restore_output(self):
        """Restore original stdout/stderr"""
        if self.original_stdout:
            sys.stdout = self.original_stdout
        if self.original_stderr:
            sys.stderr = self.original_stderr
    
    def _init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 10)
        layout.setSpacing(4)  # Even more compact spacing
        
        # Row 1: Pipeline Overview + Engine Selection (side by side)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(6)
        
        overview_group = self._create_overview_section()
        top_layout.addWidget(overview_group, stretch=1)
        
        engine_selection_group = self._create_engine_selection_section()
        top_layout.addWidget(engine_selection_group, stretch=1)
        
        layout.addLayout(top_layout)
        
        # Row 2: Wing Selection + Output Settings (side by side)
        wing_output_layout = QHBoxLayout()
        wing_output_layout.setSpacing(6)
        
        wing_selection_group = self._create_wing_selection_section()
        wing_output_layout.addWidget(wing_selection_group, stretch=1)
        
        output_group = self._create_output_section()
        wing_output_layout.addWidget(output_group, stretch=1)
        
        layout.addLayout(wing_output_layout)
        
        # Row 3: Time Filter + Run/Cancel Buttons (side by side, compact)
        time_control_layout = QHBoxLayout()
        time_control_layout.setSpacing(6)
        
        time_filter_group = self._create_time_period_filter_section()
        time_control_layout.addWidget(time_filter_group, stretch=2)
        
        control_group = self._create_control_section()
        time_control_layout.addWidget(control_group, stretch=1)
        
        layout.addLayout(time_control_layout)
        
        # Row 4: Identity filter (full width, hidden by default)
        self.identity_filter_section = self._create_identity_filter_section()
        layout.addWidget(self.identity_filter_section)
        
        # Row 5: Execution Terminal (large space)
        progress_group = self._create_progress_section()
        layout.addWidget(progress_group, stretch=4)  # Even more space for terminal
        
        layout.addSpacing(4)
    
    def _create_overview_section(self) -> QGroupBox:
        """Create pipeline overview section"""
        group = QGroupBox("Pipeline Overview")
        layout = QFormLayout()
        
        self.pipeline_name_label = QLabel("No pipeline loaded")
        self.pipeline_name_label.setStyleSheet("font-weight: bold;")
        layout.addRow("Pipeline:", self.pipeline_name_label)
        
        self.feather_count_label = QLabel("0")
        layout.addRow("Feathers:", self.feather_count_label)
        
        self.wing_count_label = QLabel("0")
        layout.addRow("Wings:", self.wing_count_label)
        
        self.case_info_label = QLabel("-")
        layout.addRow("Case:", self.case_info_label)
        
        group.setLayout(layout)
        return group
    
    def _create_wing_selection_section(self) -> QGroupBox:
        """Create wing selection section"""
        group = QGroupBox("Wing Selection")
        layout = QVBoxLayout()
        
        # Instructions
        info_label = QLabel("Select which Wings to execute:")
        info_label.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(info_label)
        
        # Wing list with checkboxes
        self.wing_list = QListWidget()
        self.wing_list.setMaximumHeight(120)
        self.wing_list.setStyleSheet("""
            QListWidget {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E5E7EB;
                font-size: 9pt;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #334155;
            }
            QListWidget::item:hover {
                background-color: #334155;
            }
            QListWidget::item:selected {
                background-color: #3B82F6;
            }
        """)
        layout.addWidget(self.wing_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all_wings)
        select_all_btn.setMaximumWidth(100)
        button_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all_wings)
        deselect_all_btn.setMaximumWidth(100)
        button_layout.addWidget(deselect_all_btn)
        
        button_layout.addStretch()
        
        # Selected count label
        self.selected_count_label = QLabel("0/0 selected")
        self.selected_count_label.setStyleSheet("color: #00d9ff; font-weight: bold;")
        button_layout.addWidget(self.selected_count_label)
        
        layout.addLayout(button_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_output_section(self) -> QGroupBox:
        """Create output directory section"""
        group = QGroupBox("Output Settings")
        layout = QHBoxLayout()
        
        layout.addWidget(QLabel("Output Directory:"))
        
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Select output directory...")
        self.output_dir_input.setText("output")
        layout.addWidget(self.output_dir_input)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output_dir)
        layout.addWidget(browse_btn)
        
        group.setLayout(layout)
        return group
    
    def _create_control_section(self) -> QWidget:
        """Create compact execution control section (no group box)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Execute button (compact)
        self.execute_btn = QPushButton("▶️ RUN")
        self.execute_btn.setEnabled(False)
        self.execute_btn.setMinimumHeight(35)
        self.execute_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #10B981, stop:0.5 #059669, stop:1 #10B981);
                color: white;
                border: 2px solid #047857;
                border-radius: 6px;
                font-size: 10pt;
                font-weight: bold;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #34D399, stop:0.5 #10B981, stop:1 #34D399);
            }
            QPushButton:disabled {
                background: #4B5563;
                color: #9CA3AF;
                border: 2px solid #374151;
            }
        """)
        self.execute_btn.clicked.connect(self._start_execution)
        layout.addWidget(self.execute_btn)
        
        # Cancel button (compact)
        self.cancel_btn = QPushButton("⏹ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(30)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #EF4444, stop:1 #DC2626);
                color: white;
                border: 2px solid #B91C1C;
                border-radius: 4px;
                font-size: 9pt;
                font-weight: bold;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F87171, stop:1 #EF4444);
            }
            QPushButton:disabled {
                background: #4B5563;
                color: #9CA3AF;
                border: #374151;
            }
        """)
        self.cancel_btn.clicked.connect(self._cancel_execution)
        layout.addWidget(self.cancel_btn)
        
        # Load Last Results button
        self.load_results_btn = QPushButton("📂 Load Last Results")
        self.load_results_btn.setMinimumHeight(30)
        self.load_results_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3B82F6, stop:1 #2563EB);
                color: white;
                border: 2px solid #1D4ED8;
                border-radius: 4px;
                font-size: 9pt;
                font-weight: bold;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #60A5FA, stop:1 #3B82F6);
            }
            QPushButton:disabled {
                background: #4B5563;
                color: #9CA3AF;
                border: #374151;
            }
        """)
        self.load_results_btn.clicked.connect(self._load_last_results)
        layout.addWidget(self.load_results_btn)
        
        return widget
    
    def _create_progress_section(self) -> QWidget:
        """Create progress display section (no group box for maximum space)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # No margins for maximum space
        layout.setSpacing(4)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)  # Start in determinate mode (not animated)
        self.progress_bar.setValue(0)  # Empty bar
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready")
        self.progress_bar.setMaximumHeight(20)  # Compact progress bar
        layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Ready to execute")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMaximumHeight(20)  # Compact status
        self.status_label.setStyleSheet("font-weight: bold; color: #00d9ff;")
        layout.addWidget(self.status_label)
        
        # Terminal output (takes all remaining space)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(300)  # Reduced for better layout balance
        self.log_output.setFont(QFont("Courier", 9))
        self.log_output.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
                background-color: #0B1220;
                color: #00d9ff;
                border: 1px solid #1e3a5f;
                padding: 5px 5px 30px 5px;
            }
        """)
        # Set document margins for extra bottom space
        self.log_output.document().setDocumentMargin(8)
        layout.addWidget(self.log_output, stretch=1)  # Terminal gets all stretch
        
        return widget
    
    def _create_engine_selection_section(self) -> QGroupBox:
        """Create engine selection section with integration features display"""
        from ..engine.engine_selector import EngineSelector
        
        group = QGroupBox("🔧 Correlation Engine")
        layout = QVBoxLayout()
        layout.setSpacing(4)
        
        # Engine dropdown with compare button
        engine_layout = QHBoxLayout()
        engine_layout.setSpacing(4)
        
        self.engine_combo = QComboBox()
        engines = EngineSelector.get_available_engines()
        
        for engine_data in engines:
            # Handle both old and new format for backward compatibility
            if len(engine_data) >= 7:  # New format with integration features
                engine_type, name, desc, complexity, use_cases, supports_id_filter, integration_features = engine_data
            else:  # Old format
                engine_type, name, desc, complexity, use_cases, supports_id_filter = engine_data
                integration_features = {}
            
            # Skip the legacy time_based engine - only show the modern engines
            if engine_type == "time_based":
                continue  # Skip legacy engine
            
            # Map engine types to proper display names
            if engine_type == "time_window_scanning":
                display_name = "Time Engine"
            elif engine_type == "identity_based":
                display_name = "Identity-Based"
            else:
                display_name = name  # Fallback to full name for unknown types
            
            # Add integration feature count to display
            feature_count = len(integration_features)
            self.engine_combo.addItem(f"{display_name} ({complexity}) - {feature_count} features", engine_type)
        
        # Set Identity-Based as default (index 1, but now index 0 since we removed time_based)
        self.engine_combo.setCurrentIndex(1)
        
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_layout.addWidget(self.engine_combo, stretch=1)
        
        # Compare button (smaller)
        compare_btn = QPushButton("📊")
        compare_btn.setToolTip("Compare correlation engines and integration features")
        compare_btn.setMaximumWidth(40)
        compare_btn.clicked.connect(self._show_engine_comparison)
        engine_layout.addWidget(compare_btn)
        
        # Integration features button
        features_btn = QPushButton("🔧")
        features_btn.setToolTip("View integration features for selected engine")
        features_btn.setMaximumWidth(40)
        features_btn.clicked.connect(self._show_integration_features)
        engine_layout.addWidget(features_btn)
        
        layout.addLayout(engine_layout)
        
        # Engine description (more compact)
        self.engine_description = QLabel()
        self.engine_description.setWordWrap(True)
        self.engine_description.setStyleSheet("color: #888; font-size: 8pt; padding: 3px;")
        self.engine_description.setMaximumHeight(40)
        layout.addWidget(self.engine_description)
        
        # Recommended for - hidden (kept for backward compatibility)
        self.engine_recommendations = QLabel()
        self.engine_recommendations.setVisible(False)
        
        # Integration features display - hidden (kept for backward compatibility)
        self.integration_features_label = QLabel()
        self.integration_features_label.setVisible(False)
        
        # Set initial description for Identity-Based engine (default)
        self._on_engine_changed(1)
        
        group.setLayout(layout)
        return group
    
    def _create_time_period_filter_section(self) -> QGroupBox:
        """Create time period filter section (compact for side-by-side layout)"""
        group = QGroupBox("📅 Time Period Filter (Optional)")
        layout = QVBoxLayout()
        layout.setSpacing(4)
        
        # Info label at top
        info_label = QLabel("💡 Filter correlation to specific time period")
        info_label.setStyleSheet("color: #888; font-size: 8pt;")
        layout.addWidget(info_label)
        
        # Start time (more compact)
        start_layout = QHBoxLayout()
        start_layout.setSpacing(4)
        start_layout.addWidget(QLabel("Start:"))
        self.start_datetime = QDateTimeEdit()
        self.start_datetime.setCalendarPopup(True)
        self.start_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_datetime.setDateTime(QDateTime.currentDateTime().addDays(-30))
        # Apply dark theme to calendar popup
        if self.start_datetime.calendarWidget():
            self.start_datetime.calendarWidget().setStyleSheet(CrowEyeStyles.CALENDAR_STYLE)
        self.start_datetime.setStyleSheet(CrowEyeStyles.DATETIME_STYLE)
        start_layout.addWidget(self.start_datetime, stretch=1)
        
        self.start_enabled = QCheckBox("Enable")
        self.start_enabled.stateChanged.connect(lambda: self.start_datetime.setEnabled(self.start_enabled.isChecked()))
        self.start_datetime.setEnabled(False)
        start_layout.addWidget(self.start_enabled)
        
        layout.addLayout(start_layout)
        
        # End time (more compact)
        end_layout = QHBoxLayout()
        end_layout.setSpacing(4)
        end_layout.addWidget(QLabel("End:"))
        self.end_datetime = QDateTimeEdit()
        self.end_datetime.setCalendarPopup(True)
        self.end_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end_datetime.setDateTime(QDateTime.currentDateTime())
        # Apply dark theme to calendar popup
        if self.end_datetime.calendarWidget():
            self.end_datetime.calendarWidget().setStyleSheet(CrowEyeStyles.CALENDAR_STYLE)
        self.end_datetime.setStyleSheet(CrowEyeStyles.DATETIME_STYLE)
        end_layout.addWidget(self.end_datetime, stretch=1)
        
        self.end_enabled = QCheckBox("Enable")
        self.end_enabled.stateChanged.connect(lambda: self.end_datetime.setEnabled(self.end_enabled.isChecked()))
        self.end_datetime.setEnabled(False)
        end_layout.addWidget(self.end_enabled)
        
        layout.addLayout(end_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_identity_filter_section(self) -> QGroupBox:
        """Create identity filter section (Identity engine only)"""
        group = QGroupBox("Identity Filter (Identity Engine Only)")
        layout = QVBoxLayout()
        
        # Info label
        info_label = QLabel("Enter identities to search for (one per line). Supports wildcards (* and ?).")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #888; font-size: 8pt;")
        layout.addWidget(info_label)
        
        # Identity input
        self.identity_filter_input = QTextEdit()
        self.identity_filter_input.setPlaceholderText(
            "Examples:\n"
            "chrome.exe\n"
            "C:\\Windows\\System32\\*.exe\n"
            "*malware*\n"
            "abc123def456..."  # Hash example
        )
        self.identity_filter_input.setMaximumHeight(100)
        layout.addWidget(self.identity_filter_input)
        
        # Case sensitive checkbox
        self.case_sensitive_checkbox = QCheckBox("Case Sensitive")
        layout.addWidget(self.case_sensitive_checkbox)
        
        group.setLayout(layout)
        group.setVisible(False)  # Hidden by default
        return group
    
    def display_pipeline_overview(self, pipeline_config: PipelineConfig):
        """
        Display pipeline summary.
        
        Args:
            pipeline_config: Pipeline configuration to display
        """
        self.current_pipeline = pipeline_config
        
        # Update labels
        self.pipeline_name_label.setText(pipeline_config.pipeline_name)
        self.feather_count_label.setText(str(len(pipeline_config.feather_configs)))
        self.wing_count_label.setText(str(len(pipeline_config.wing_configs)))
        
        # Case info
        if pipeline_config.case_name:
            case_text = pipeline_config.case_name
            if pipeline_config.case_id:
                case_text += f" ({pipeline_config.case_id})"
            self.case_info_label.setText(case_text)
        else:
            self.case_info_label.setText("-")
        
        # Set output directory from pipeline config
        if pipeline_config.output_directory:
            self.output_dir_input.setText(pipeline_config.output_directory)
        
        # Populate wing list
        self.wing_list.clear()
        
        if not pipeline_config.wing_configs:
            # No wings in pipeline - show message
            info_item = QListWidgetItem("⚠ No Wings configured in this pipeline")
            info_item.setFlags(Qt.ItemIsEnabled)  # Not selectable
            info_item.setForeground(Qt.yellow)
            self.wing_list.addItem(info_item)
            
            # Disable execute button
            self.execute_btn.setEnabled(False)
            
            self._batched_log.append_text("\n⚠ Warning: No Wings configured in pipeline")
            self._batched_log.append_text("Please add Wings to the pipeline before executing.")
        else:
            # Populate wings
            for wing_config in pipeline_config.wing_configs:
                wing_name = getattr(wing_config, 'wing_name', 'Unknown Wing')
                feather_count = len(getattr(wing_config, 'feathers', []))
                
                item = QListWidgetItem(f"{wing_name} ({feather_count} feathers)")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)  # Default to checked
                item.setData(Qt.UserRole, wing_config)
                self.wing_list.addItem(item)
            
            # Enable execute button
            self.execute_btn.setEnabled(True)
        
        # Connect item changed signal to update count (only if we have wings)
        if pipeline_config.wing_configs:
            self.wing_list.itemChanged.connect(self._update_selected_count)
            self._update_selected_count()
        
        # Clear log
        self.log_output.clear()
        self._batched_log.append_text(f"Pipeline loaded: {pipeline_config.pipeline_name}")
        self._batched_log.append_text(f"Feathers: {len(pipeline_config.feather_configs)}")
        self._batched_log.append_text(f"Wings: {len(pipeline_config.wing_configs)}")
        self._batched_log.append_text(f"Output Directory: {pipeline_config.output_directory or 'output'}")
        self._batched_log.append_text("\nReady to execute.")
        self._batched_log.flush()  # Flush immediately for user feedback
    
    def _browse_output_dir(self):
        """Browse for output directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.output_dir_input.text()
        )
        
        if directory:
            self.output_dir_input.setText(directory)
    
    def _start_execution(self, resume_execution_id: int = None):
        """Start correlation execution"""
        try:
            # print("[ExecutionControl] _start_execution called")
            
            if not self.current_pipeline:
                QMessageBox.warning(
                    self,
                    "No Pipeline",
                    "No pipeline loaded. Please load a pipeline first."
                )
                return
            
            # print(f"[ExecutionControl] Current pipeline: {self.current_pipeline.pipeline_name}")
            
            # Get selected wings
            selected_wings = self._get_selected_wings()
            # print(f"[ExecutionControl] Selected wings: {len(selected_wings)}")
            
            if not selected_wings:
                QMessageBox.warning(
                    self,
                    "No Wings Selected",
                    "Please select at least one Wing to execute."
                )
                return
            
            # Get output directory
            output_dir = self.output_dir_input.text().strip()
            # print(f"[ExecutionControl] Output directory: {output_dir}")
            
            if not output_dir:
                QMessageBox.warning(
                    self,
                    "No Output Directory",
                    "Please specify an output directory."
                )
                return
            
            # Create output directory
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                # print(f"[ExecutionControl] Output directory created/verified")
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Directory Error",
                    f"Failed to create output directory:\n{str(e)}"
                )
                return
            
            # Disable execute button and change appearance
            self.execute_btn.setEnabled(False)
            self.execute_btn.setText("⏳  Executing...")
            
            # Switch cancel button to executing mode
            self._switch_to_executing_mode()
            
            # Create a copy of pipeline config with only selected wings
            from copy import deepcopy
            # print("[ExecutionControl] Creating execution pipeline copy...")
            execution_pipeline = deepcopy(self.current_pipeline)
            execution_pipeline.wing_configs = selected_wings
            # print(f"[ExecutionControl] Execution pipeline created with {len(selected_wings)} wings")
            
            # NEW: Apply engine selection and filters
            if hasattr(self, 'engine_combo'):
                engine_type = self.engine_combo.currentData()
                execution_pipeline.engine_type = engine_type
                print(f"[ExecutionControl] Engine type selected: {engine_type}")
            else:
                print(f"[ExecutionControl] WARNING: No engine_combo found!")
            
            # NEW: Apply time period filter
            if hasattr(self, 'start_enabled') and self.start_enabled.isChecked():
                execution_pipeline.time_period_start = self.start_datetime.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
                self._batched_log.append_text(f"Time Filter Start: {execution_pipeline.time_period_start}")
            else:
                execution_pipeline.time_period_start = None
            
            if hasattr(self, 'end_enabled') and self.end_enabled.isChecked():
                execution_pipeline.time_period_end = self.end_datetime.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
                self._batched_log.append_text(f"Time Filter End: {execution_pipeline.time_period_end}")
            else:
                execution_pipeline.time_period_end = None
            
            # Log if time filter is applied
            if execution_pipeline.time_period_start or execution_pipeline.time_period_end:
                self._batched_log.append_text(f"✓ Time period filter enabled")
            
            # NEW: Apply identity filter
            if hasattr(self, 'identity_filter_input') and self.identity_filter_section.isVisible():
                identity_text = self.identity_filter_input.toPlainText().strip()
                if identity_text:
                    execution_pipeline.identity_filters = [line.strip() for line in identity_text.split('\n') if line.strip()]
                    execution_pipeline.identity_filter_case_sensitive = self.case_sensitive_checkbox.isChecked()
                    # print(f"[ExecutionControl] Identity filters: {len(execution_pipeline.identity_filters)} patterns")
                else:
                    execution_pipeline.identity_filters = None
            else:
                execution_pipeline.identity_filters = None
            
            # Clear log
            self.log_output.clear()
            self._batched_log.append_text("Starting correlation execution...")
            self._batched_log.append_text(f"Output directory: {output_dir}")
            self._batched_log.append_text(f"Selected wings: {len(selected_wings)}/{len(self.current_pipeline.wing_configs)}")
            
            # List selected wings
            for wing in selected_wings:
                wing_name = getattr(wing, 'wing_name', 'Unknown Wing')
                self._batched_log.append_text(f"  - {wing_name}")
            self._batched_log.append_text("")
            self._batched_log.flush()  # Flush immediately for user feedback
            
            # Reset progress bar to indeterminate mode
            self.progress_bar.setMaximum(0)  # Indeterminate - shows activity
            self.progress_bar.setFormat("Correlation Engine Working...")
            self._last_progress_time = None  # Reset throttling for new execution
            self.status_label.setText("Initializing...")
            
            # Start optimized heartbeat (Task 5)
            self._heartbeat.start()
            
            # Start event processing timer (Task 5) - increased to 150ms to further reduce UI blocking
            self._processing_timer.start(150)  # Process queue every 150ms (increased from 100ms)
            
            # Start periodic trimming timer (Task 7)
            self._trimming_timer.start()  # Check every 30 seconds
            
            # print("[ExecutionControl] Creating worker thread...")
            
            # Create worker thread
            self.worker_thread = QThread()
            self.engine_wrapper = CorrelationEngineWrapper()
            self.engine_wrapper.moveToThread(self.worker_thread)
            
            # print("[ExecutionControl] Setting pipeline on engine wrapper...")
            
            # Set pipeline (use filtered pipeline with only selected wings)
            self.engine_wrapper.set_pipeline(execution_pipeline, output_dir, selected_wings, resume_execution_id)
            
            # Set progress handler for detailed progress display in log_output
            self.engine_wrapper.set_progress_handler(self._handle_progress_event)
            
            # print("[ExecutionControl] Connecting signals...")
            
            # Connect signals with explicit Qt.QueuedConnection for async handling (Task 5)
            self.worker_thread.started.connect(self.engine_wrapper.run)
            self.engine_wrapper.progress_updated.connect(
                self._queue_progress_event, 
                Qt.QueuedConnection
            )
            self.engine_wrapper.anchor_progress_updated.connect(
                self._queue_progress_event,
                Qt.QueuedConnection
            )
            self.engine_wrapper.wing_completed.connect(
                self._on_wing_completed,
                Qt.QueuedConnection
            )
            self.engine_wrapper.log_message.connect(
                self._batched_log.append_text,
                Qt.QueuedConnection
            )
            self.engine_wrapper.execution_completed.connect(
                self._on_execution_completed,
                Qt.QueuedConnection
            )
            self.engine_wrapper.execution_failed.connect(
                self._on_execution_failed,
                Qt.QueuedConnection
            )
            self.engine_wrapper.execution_completed.connect(self.worker_thread.quit)
            self.engine_wrapper.execution_failed.connect(self.worker_thread.quit)
            self.worker_thread.finished.connect(self._cleanup_thread)
            
            # print("[ExecutionControl] Starting worker thread...")
            
            # Start thread
            self.worker_thread.start()
            
            # print("[ExecutionControl] Worker thread started successfully")
            
            # Emit signal
            self.execution_started.emit()
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to start execution:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            # print(f"[ExecutionControl] EXCEPTION in _start_execution: {error_msg}")
            QMessageBox.critical(
                self,
                "Execution Error",
                error_msg
            )
            # Re-enable button
            self.execute_btn.setEnabled(True)
            self.execute_btn.setText("▶️ RUN")
            self.cancel_btn.setEnabled(False)
    
    def _cancel_execution(self):
        """Handle pause/resume functionality."""
        if self.cancel_btn.text().startswith("⏹"):
            # Currently showing "Cancel" - user wants to pause
            self._pause_execution()
        else:
            # Currently showing "Resume" - user wants to resume
            self._resume_execution()
    
    def _pause_execution(self):
        """Pause execution and save partial results."""
        if self.worker_thread and self.worker_thread.isRunning():
            # Switch to cancelling mode immediately for visual feedback (Requirement 8.3)
            self._switch_to_cancelling_mode()
            
            # Request graceful shutdown
            if self.engine_wrapper:
                self._batched_log.append_text("\n⏹ Cancelling execution - saving partial results...")
                self._batched_log.flush()  # Flush immediately for user feedback
                self.status_label.setText("Cancelling...")  # Requirement 8.3
                
                # Set cancellation flag on wrapper immediately (Requirement 8.1)
                self.engine_wrapper.cancel()
                
                # Give it time to save partial results (Requirement 8.4 - within 2 seconds)
                self.worker_thread.quit()
                if not self.worker_thread.wait(2000):  # Wait up to 2 seconds (Requirement 8.4)
                    self._batched_log.append_text("⚠️ Force terminating execution...")
                    self._batched_log.flush()
                    self.worker_thread.terminate()
                    self.worker_thread.wait()
            else:
                self.worker_thread.quit()
                self.worker_thread.wait()
            
            self._batched_log.append_text("⏹ Execution cancelled by user")
            self._batched_log.flush()  # Flush immediately for user feedback
            
            # Clean up resources (Requirement 8.5)
            self._cleanup_after_cancellation()
            
            # Show cancellation confirmation message
            partial_results_count = 0
            if self.engine_wrapper and self.engine_wrapper.executor:
                # Try to get partial results count
                if hasattr(self.engine_wrapper.executor, 'identities'):
                    partial_results_count = len(self.engine_wrapper.executor.identities)
                elif hasattr(self.engine_wrapper.executor, 'stats'):
                    partial_results_count = getattr(self.engine_wrapper.executor.stats, 'total_identities', 0)
            
            if partial_results_count > 0:
                QMessageBox.information(
                    self,
                    "Execution Cancelled",
                    f"Execution cancelled. Saved {partial_results_count} partial results.\n\n"
                    f"Partial results have been saved to the database.\n"
                    f"Click 'Resume' to continue from where you left off."
                )
                self._batched_log.append_text(f"✓ Partial results saved: {partial_results_count} identities")
                self._batched_log.flush()
            else:
                self._batched_log.append_text("✓ Partial results have been saved to database")
                self._batched_log.flush()
            
            self.status_label.setText("⏸️ Paused - Click Resume to continue")
            
            # Change button to Resume
            self._switch_to_resume_mode()
            
            self._cleanup_thread()
    
    def _resume_execution(self):
        """Resume paused execution."""
        try:
            # Check for paused executions in current output directory
            output_dir = self.output_dir_input.text().strip()
            if not output_dir:
                QMessageBox.warning(self, "No Output Directory", 
                                  "Please select an output directory first.")
                return
            
            # Get paused executions
            from ..engine.database_persistence import ResultsDatabase
            db_path = Path(output_dir) / "correlation_results.db"
            
            if not db_path.exists():
                QMessageBox.information(self, "No Database Found", 
                                      "No correlation database found in the selected output directory.")
                self._switch_to_cancel_mode()
                return
            
            with ResultsDatabase(str(db_path)) as db:
                paused_executions = db.get_paused_executions()
            
            if not paused_executions:
                QMessageBox.information(self, "No Paused Executions", 
                                      "No paused executions found in the selected output directory.")
                self._switch_to_cancel_mode()
                return
            
            # If multiple paused executions, let user choose
            if len(paused_executions) > 1:
                execution_names = []
                for exec_data in paused_executions:
                    progress = exec_data.get('progress_details', {})
                    percentage = progress.get('percentage_complete', 0)
                    execution_names.append(f"{exec_data['wing_name']} - {percentage:.1f}% complete")
                
                choice, ok = QInputDialog.getItem(
                    self, "Select Execution to Resume", 
                    "Multiple paused executions found:", 
                    execution_names, 0, False
                )
                
                if not ok:
                    return
                
                selected_index = execution_names.index(choice)
                selected_execution = paused_executions[selected_index]
            else:
                selected_execution = paused_executions[0]
            
            # Resume the selected execution
            execution_id = selected_execution['execution_id']
            progress = selected_execution.get('progress_details', {})
            
            self._batched_log.append_text(f"\n▶️ Resuming execution ID: {execution_id}")
            self._batched_log.append_text(f"   Progress: {progress.get('percentage_complete', 0):.1f}% complete")
            self._batched_log.append_text(f"   Existing matches: {selected_execution['total_matches']:,}")
            self._batched_log.flush()  # Flush immediately for user feedback
            
            # Switch back to cancel mode and start execution with resume parameter
            self._switch_to_cancel_mode()
            self._start_execution(resume_execution_id=execution_id)
            
        except Exception as e:
            QMessageBox.critical(self, "Resume Failed", f"Failed to resume execution:\n{str(e)}")
            self._switch_to_cancel_mode()
    
    def _switch_to_resume_mode(self):
        """Switch cancel button to resume mode with enhanced styling."""
        self.cancel_btn.setText("▶️ Resume")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #10B981, stop:1 #059669);
                color: white;
                border: 2px solid #047857;
                border-radius: 6px;
                font-size: 10pt;
                font-weight: bold;
                padding: 6px 16px;
                min-height: 30px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34D399, stop:1 #10B981);
                border: 2px solid #059669;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
            }
            QPushButton:disabled {
                background: #4B5563;
                color: #9CA3AF;
                border: 2px solid #374151;
            }
        """)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setToolTip("Resume paused execution from where it left off")
    
    def _switch_to_cancel_mode(self):
        """Switch resume button back to cancel mode with enhanced styling."""
        self.cancel_btn.setText("⏹ Cancel")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #EF4444, stop:1 #DC2626);
                color: white;
                border: 2px solid #B91C1C;
                border-radius: 6px;
                font-size: 10pt;
                font-weight: bold;
                padding: 6px 16px;
                min-height: 30px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F87171, stop:1 #EF4444);
                border: 2px solid #DC2626;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #DC2626, stop:1 #B91C1C);
            }
            QPushButton:disabled {
                background: #4B5563;
                color: #9CA3AF;
                border: 2px solid #374151;
            }
        """)
        self.cancel_btn.setEnabled(False)  # Will be enabled when execution starts
        self.cancel_btn.setToolTip("Cancel execution and save partial results")
    
    def _switch_to_pausing_mode(self):
        """Switch button to pausing mode with animated styling."""
        self.cancel_btn.setText("⏸️ Pausing...")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F59E0B, stop:1 #D97706);
                color: white;
                border: 2px solid #B45309;
                border-radius: 6px;
                font-size: 10pt;
                font-weight: bold;
                padding: 6px 16px;
                min-height: 30px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FBBF24, stop:1 #F59E0B);
            }
            QPushButton:disabled {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F59E0B, stop:1 #D97706);
                color: white;
                border: 2px solid #B45309;
            }
        """)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("Pausing execution and saving partial results...")
    
    def _switch_to_cancelling_mode(self):
        """Switch button to cancelling mode with animated styling (Requirement 8.3)."""
        self.cancel_btn.setText("⏹ Cancelling...")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F59E0B, stop:1 #D97706);
                color: white;
                border: 2px solid #B45309;
                border-radius: 6px;
                font-size: 10pt;
                font-weight: bold;
                padding: 6px 16px;
                min-height: 30px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FBBF24, stop:1 #F59E0B);
            }
            QPushButton:disabled {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F59E0B, stop:1 #D97706);
                color: white;
                border: 2px solid #B45309;
            }
        """)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("Cancelling execution and saving partial results...")
    
    def _switch_to_executing_mode(self):
        """Switch button to executing mode with enhanced styling."""
        self.cancel_btn.setText("⏹ Cancel")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #EF4444, stop:1 #DC2626);
                color: white;
                border: 2px solid #B91C1C;
                border-radius: 6px;
                font-size: 10pt;
                font-weight: bold;
                padding: 6px 16px;
                min-height: 30px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F87171, stop:1 #EF4444);
                border: 2px solid #DC2626;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #DC2626, stop:1 #B91C1C);
            }
            QPushButton:disabled {
                background: #4B5563;
                color: #9CA3AF;
                border: 2px solid #374151;
            }
        """)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setToolTip("Cancel execution and save partial results")
    
    def _update_progress(self, wing_index: int, total_wings: int, status: str):
        """Update progress indicators - simplified"""
        try:
            # Validate inputs
            if not isinstance(wing_index, (int, float)) or not isinstance(total_wings, (int, float)):
                logger.error(f"Invalid progress values: wing_index={wing_index}, total_wings={total_wings}")
                return
            
            if not isinstance(status, str):
                logger.error(f"Invalid status type: {type(status)}")
                status = str(status)  # Try to convert
            
            # Just update status, progress bar stays in indeterminate mode
            self.status_label.setText(status)
            # Use the improved _append_to_log method for consistent scrolling
            self._append_to_log(f"[{wing_index}/{total_wings}] {status}")
        except Exception as e:
            logger.error(f"Error updating progress: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def _update_anchor_progress(self, anchor_index: int, total_anchors: int):
        """
        Update progress bar based on anchor processing.
        Shows actual progress with percentage.
        """
        try:
            # Validate inputs
            if not isinstance(anchor_index, (int, float)) or not isinstance(total_anchors, (int, float)):
                logger.error(f"Invalid anchor progress values: anchor_index={anchor_index}, total_anchors={total_anchors}")
                return
            
            if total_anchors > 0:
                # Set to determinate mode with actual progress
                self.progress_bar.setMaximum(total_anchors)
                self.progress_bar.setValue(anchor_index)
                percentage = (anchor_index / total_anchors * 100)
                self.progress_bar.setFormat(f"{anchor_index:,}/{total_anchors:,} ({percentage:.1f}%)")
                self.status_label.setText(f"Processing... {anchor_index:,} items processed")
                
                # Force GUI update to prevent lagging
                try:
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass  # Ignore if not in GUI context
        except Exception as e:
            logger.error(f"Error updating anchor progress: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def _on_wing_completed(self, summary: dict):
        """Handle individual wing completion - emit signal for parent to create separate tab"""
        try:
            # Validate summary structure
            if not isinstance(summary, dict):
                logger.error(f"Invalid summary type: {type(summary)}")
                return
            
            wing_name = summary.get('wing_name', 'Unknown Wing')
            wing_index = summary.get('wing_index', 0)
            total_wings = summary.get('total_wings', 1)
            total_matches = summary.get('total_matches', 0)
            
            # Log wing completion
            self._batched_log.append_text(f"\n✓ Wing {wing_index}/{total_wings} completed: {wing_name}")
            self._batched_log.append_text(f"  Matches found: {total_matches}")
            self._batched_log.flush()  # Flush immediately for user feedback
            
            # Emit signal for parent widget to create separate result tab
            self.wing_completed.emit(summary)
        except Exception as e:
            logger.error(f"Error handling wing completion: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def _on_execution_completed(self, summary: dict):
        """Handle execution completion - all wings finished"""
        try:
            # Stop processing timer and heartbeat (Task 6)
            if self._processing_timer.isActive():
                self._processing_timer.stop()
            
            if self._heartbeat:
                self._heartbeat.stop()
            
            # Validate summary structure
            if not isinstance(summary, dict):
                logger.error(f"Invalid summary type: {type(summary)}")
                summary = {}  # Use empty dict as fallback
            
            # Set to determinate mode and show complete
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Complete")
            self.status_label.setText("✓ All wings executed successfully")
            
            # Reset button to default state
            self._switch_to_cancel_mode()
            
            # Log summary using batched log (Task 5)
            if self._batched_log:
                self._batched_log.append_text("\n" + "=" * 60)
                self._batched_log.append_text("ALL WINGS EXECUTION COMPLETE")
                self._batched_log.append_text("=" * 60)
                self._batched_log.append_text(f"Pipeline: {summary.get('pipeline_name', 'Unknown')}")
                self._batched_log.append_text(f"Total Wings Executed: {summary.get('total_wings_executed', 0)}")
                self._batched_log.flush()  # Force immediate display
            
            # Show completion message
            QMessageBox.information(
                self,
                "Execution Complete",
                f"All wings executed successfully!\n\n"
                f"Total Wings: {summary.get('total_wings_executed', 0)}\n\n"
                f"Results have been saved to separate tabs."
            )
            
            # Emit signal for parent widget
            self.execution_completed.emit(summary)
        except Exception as e:
            logger.error(f"Error handling execution completion: {e}", exc_info=True)
            # Still try to clean up
            try:
                if self._processing_timer.isActive():
                    self._processing_timer.stop()
                if self._heartbeat:
                    self._heartbeat.stop()
            except:
                pass
    
    def _on_execution_failed(self, error_message: str):
        """Handle execution failure"""
        # Stop processing timer and heartbeat (Task 6)
        if self._processing_timer.isActive():
            self._processing_timer.stop()
        
        if self._heartbeat:
            self._heartbeat.stop()
        
        self.status_label.setText("❌ Execution failed")
        
        # Reset button to default state
        self._switch_to_cancel_mode()
        
        # Log error using batched log (Task 5)
        if self._batched_log:
            self._batched_log.append_text("\n" + "=" * 60)
            self._batched_log.append_text("EXECUTION FAILED")
            self._batched_log.append_text("=" * 60)
            self._batched_log.append_text(f"Error: {error_message}")
            self._batched_log.flush()  # Force immediate display
        
        QMessageBox.critical(
            self,
            "Execution Failed",
            f"Correlation execution failed:\n\n{error_message}"
        )
    
    def _cleanup_thread(self):
        """Cleanup worker thread"""
        # Stop processing timer and heartbeat (Task 5)
        if self._processing_timer.isActive():
            self._processing_timer.stop()
        
        if self._heartbeat:
            self._heartbeat.stop()
        
        # Stop trimming timer (Task 7)
        if self._trimming_timer.isActive():
            self._trimming_timer.stop()
        
        # Clear event queue (Task 5)
        self._event_queue.clear()
        
        # Clear progress message buffer (Task 12)
        if hasattr(self, '_progress_message_buffer'):
            self._progress_message_buffer.clear()
        
        # Flush any remaining batched log messages (Task 7)
        if self._batched_log:
            self._batched_log.flush()
            # Force scroll to bottom to show completion message
            self._batched_log.force_scroll_to_bottom()
        
        self.execute_btn.setEnabled(True)
        self.execute_btn.setText("▶️ RUN")
        
        # Reset cancel button to default state if not already in resume mode
        if not self.cancel_btn.text().startswith("▶️"):
            self._switch_to_cancel_mode()
        
        if self.worker_thread:
            self.worker_thread.deleteLater()
            self.worker_thread = None
        
        if self.engine_wrapper:
            self.engine_wrapper.deleteLater()
            self.engine_wrapper = None
    
    def _cleanup_after_cancellation(self):
        """
        Clean up resources after cancellation and re-enable controls (Requirement 8.5).
        This is called immediately after cancellation to ensure UI is responsive.
        """
        # Stop all timers
        if self._processing_timer.isActive():
            self._processing_timer.stop()
        
        if self._heartbeat:
            self._heartbeat.stop()
        
        if self._trimming_timer.isActive():
            self._trimming_timer.stop()
        
        # Clear event queue and buffers
        self._event_queue.clear()
        
        if hasattr(self, '_progress_message_buffer'):
            self._progress_message_buffer.clear()
        
        # Flush any remaining batched log messages
        if self._batched_log:
            self._batched_log.flush()
        
        # Re-enable controls (Requirement 8.5)
        self.execute_btn.setEnabled(True)
        self.execute_btn.setText("▶️ RUN")
        
        # Update status
        self.status_label.setText("⏹ Execution cancelled")
        
        # Switch to resume mode to allow resuming from where we left off
        self._switch_to_resume_mode()
    
    def _queue_progress_event(self, *args):
        """
        Queue progress event instead of processing immediately.
        
        This method enqueues progress events for batch processing to prevent
        UI thread blocking during high-frequency progress updates.
        
        Args:
            *args: Variable arguments from progress signal
        """
        try:
            event = {'args': args, 'timestamp': time.time()}
            self._event_queue.enqueue(event)
        except Exception as e:
            logger.error(f"Error queuing progress event: {e}", exc_info=True)
            # Continue processing - don't let one bad event break everything
    
    def _process_event_queue(self):
        """
        Process batched events from queue.
        
        This method is called by the processing timer to handle queued progress
        events in batches, applying throttling to limit UI update frequency.
        """
        try:
            queue_size = self._event_queue.size()
            
            # Log queue size for debugging (only when queue has events)
            if queue_size > 0:
                logger.debug(f"Processing event queue: size={queue_size}, dropped={self._event_queue.get_dropped_count()}")
            
            # Adaptive throttling based on queue size
            interval = self._progress_throttler.get_adaptive_interval(queue_size)
            
            if not self._progress_throttler.should_update():
                return
            
            # Process up to 30 events per iteration (reduced from 50 to minimize UI blocking even further)
            events = self._event_queue.dequeue_batch(max_count=30)
            
            if events:
                # Process only the most recent event for display
                latest_event = events[-1]
                
                # Validate event structure
                if not isinstance(latest_event, dict):
                    logger.error(f"Invalid event type: {type(latest_event)}")
                    return
                
                if 'args' not in latest_event:
                    logger.error(f"Missing 'args' in event: {latest_event}")
                    return
                
                args = latest_event.get('args', ())
                
                # Call the original progress update handler with the latest event
                try:
                    if len(args) == 3:
                        # This is a progress_updated signal (wing_index, total_wings, status)
                        self._update_progress(*args)
                    elif len(args) == 2:
                        # This is an anchor_progress_updated signal (anchor_index, total_anchors)
                        self._update_anchor_progress(*args)
                    else:
                        logger.warning(f"Unexpected event args length: {len(args)}")
                except Exception as e:
                    logger.error(f"Error processing progress event: {e}", exc_info=True)
                    # Continue processing - don't let one bad event break everything
        except Exception as e:
            logger.error(f"Error in event queue processing: {e}", exc_info=True)
            # Continue processing - don't crash the UI thread
    
    def _periodic_trim_check(self):
        """
        Periodically check and trim log output to prevent memory issues.
        
        This method is called by the trimming timer to ensure the log widget
        doesn't grow unbounded during long-running executions.
        """
        try:
            if self._batched_log:
                self._batched_log.trim_to_size(max_lines=10000)
        except Exception as e:
            logger.error(f"Error during periodic trim check: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def _handle_progress_event(self, event):
        """
        Handle progress events from the correlation engine.
        Updates the progress bar and log output with detailed progress information.
        
        Args:
            event: Progress event from the engine (ProgressEvent or legacy format)
        """
        try:
            # Throttle progress updates to avoid UI lag
            current_time = datetime.now()
            if self._last_progress_time:
                time_diff = (current_time - self._last_progress_time).total_seconds()
                if time_diff < self._min_progress_interval:
                    return  # Skip this update
            self._last_progress_time = current_time
            
            # Handle new ProgressEvent format
            if hasattr(event, 'event_type') and hasattr(event, 'overall_progress'):
                from ..engine.progress_tracking import ProgressEventType
                
                progress = event.overall_progress
                
                # Update progress bar based on event type
                if event.event_type == ProgressEventType.SCANNING_START:
                    # Set progress bar to determinate mode with total
                    total = progress.total_windows if progress.total_windows > 0 else 100
                    self.progress_bar.setMaximum(total)
                    self.progress_bar.setValue(0)
                    self.progress_bar.setFormat(f"0/{total} (0%)")
                    self.status_label.setText("Starting correlation...")
                    
                elif event.event_type == ProgressEventType.WINDOW_PROGRESS:
                    # Update progress bar
                    processed = progress.windows_processed
                    total = progress.total_windows if progress.total_windows > 0 else 100
                    percentage = progress.completion_percentage
                    
                    self.progress_bar.setMaximum(total)
                    self.progress_bar.setValue(processed)
                    self.progress_bar.setFormat(f"{processed}/{total} ({percentage:.1f}%)")
                    self.status_label.setText(f"Processing... {progress.matches_found:,} matches found")
                    
                elif event.event_type == ProgressEventType.WINDOW_COMPLETE:
                    # Update on window completion
                    processed = progress.windows_processed
                    total = progress.total_windows if progress.total_windows > 0 else 100
                    percentage = progress.completion_percentage
                    
                    self.progress_bar.setMaximum(total)
                    self.progress_bar.setValue(processed)
                    self.progress_bar.setFormat(f"{processed}/{total} ({percentage:.1f}%)")
                    
                elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
                    # Complete the progress bar
                    self.progress_bar.setMaximum(100)
                    self.progress_bar.setValue(100)
                    self.progress_bar.setFormat("Complete (100%)")
                    self.status_label.setText(f"✓ Completed - {progress.matches_found:,} matches found")
                
                # Force GUI update to prevent lagging
                try:
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass  # Ignore if not in GUI context
                
                # Log message if provided
                if event.message and event.message != self._last_progress_message:
                    self._last_progress_message = event.message
                    # Use signal for thread-safe logging
                    self.progress_message.emit(event.message)
            
            # Handle legacy event format
            elif hasattr(event, 'event_type') and hasattr(event, 'data'):
                data = event.data
                
                if event.event_type == "anchor_progress":
                    anchor_index = data.get('anchor_index', 0)
                    total_anchors = data.get('total_anchors', 1)
                    percentage = (anchor_index / total_anchors * 100) if total_anchors > 0 else 0
                    
                    self.progress_bar.setMaximum(total_anchors)
                    self.progress_bar.setValue(anchor_index)
                    self.progress_bar.setFormat(f"{anchor_index}/{total_anchors} ({percentage:.1f}%)")
                    
                elif event.event_type == "summary_progress":
                    anchors_processed = data.get('anchors_processed', 0)
                    total_anchors = data.get('total_anchors', 1)
                    percentage = (anchors_processed / total_anchors * 100) if total_anchors > 0 else 0
                    
                    self.progress_bar.setMaximum(total_anchors)
                    self.progress_bar.setValue(anchors_processed)
                    self.progress_bar.setFormat(f"{anchors_processed}/{total_anchors} ({percentage:.1f}%)")
                
                # Force GUI update to prevent lagging
                try:
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass  # Ignore if not in GUI context
                    
        except Exception as e:
            # Don't let progress handling errors crash the execution
            print(f"[ExecutionControl] Progress event handling error: {e}")
    
    def _append_to_log(self, message: str):
        """
        Append message to log output with auto-scroll.
        This method handles all progress and log messages.
        
        Args:
            message: Message to append
        """
        # Skip empty or whitespace-only messages to prevent empty lines
        if message and message.strip():
            # Store message in memory-bounded buffer (Task 12)
            if hasattr(self, '_progress_message_buffer'):
                self._progress_message_buffer.add_message(message)
            
            # Use cursor-based insertion for better control over scrolling
            cursor = self.log_output.textCursor()
            cursor.movePosition(cursor.End)
            cursor.insertText(message + '\n')
            self.log_output.setTextCursor(cursor)
            
            # Force scroll to bottom immediately
            self._scroll_to_bottom()
    
    def _scroll_to_bottom(self):
        """Scroll the log output to the bottom"""
        # Move cursor to end of document first
        cursor = self.log_output.textCursor()
        cursor.movePosition(cursor.End)
        self.log_output.setTextCursor(cursor)
        
        # Force scroll to bottom using scrollbar
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # Ensure the cursor is visible
        self.log_output.ensureCursorVisible()
        
        # Force a repaint to ensure scrolling happens immediately
        self.log_output.repaint()
        
        # Additional safety: Use QTimer for a final scroll check
        # This handles edge cases where the scrollbar maximum changes after text insertion
        QTimer.singleShot(10, self._final_scroll_check)
    
    def _final_scroll_check(self):
        """Final scroll check to ensure we're at the bottom"""
        scrollbar = self.log_output.verticalScrollBar()
        if scrollbar.value() < scrollbar.maximum():
            scrollbar.setValue(scrollbar.maximum())
    
    def _load_last_results(self):
        """Load results from database using enhanced loader dialog with robust error handling."""
        output_dir = self.output_dir_input.text().strip()
        
        if not output_dir:
            QMessageBox.warning(
                self,
                "No Output Directory",
                "Please specify an output directory first."
            )
            return
        
        output_path = Path(output_dir)
        
        # Check if output directory exists
        if not output_path.exists():
            QMessageBox.warning(
                self,
                "Directory Not Found",
                f"Output directory does not exist:\n{output_dir}\n\n"
                "Please run a correlation first or select a different output directory."
            )
            return
        
        db_file = output_path / "correlation_results.db"
        
        # Check if database file exists
        if not db_file.exists():
            QMessageBox.warning(
                self,
                "No Database Found",
                f"No results database found in:\n{output_dir}\n\n"
                "Please run a correlation first or select a different output directory."
            )
            return
        
        try:
            # Import and show the enhanced database loader dialog
            from .database_results_loader import DatabaseResultsLoaderDialog
            
            # Verify database is accessible before opening dialog
            try:
                from ..engine.database_persistence import ResultsDatabase
                with ResultsDatabase(str(db_file)) as db:
                    # Quick check to see if database has any executions
                    latest_id = db.get_latest_execution_id()
                    if not latest_id:
                        QMessageBox.information(
                            self,
                            "No Results Found",
                            f"The database exists but contains no execution results:\n{db_file}\n\n"
                            "Please run a correlation first."
                        )
                        return
            except Exception as db_error:
                QMessageBox.critical(
                    self,
                    "Database Error",
                    f"Failed to access database:\n{db_file}\n\n"
                    f"Error: {str(db_error)}\n\n"
                    "The database may be corrupted or in use by another process."
                )
                return
            
            # Database is valid, show the loader dialog
            dialog = DatabaseResultsLoaderDialog(self, str(db_file))
            
            if dialog.exec_() == QDialog.Accepted:
                selected_executions = dialog.get_selected_executions()
                
                if selected_executions:
                    self._batched_log.append_text(f"\n📂 Loading {len(selected_executions)} execution(s)...")
                    
                    for db_path, execution_id, engine_type in selected_executions:
                        self._batched_log.append_text(f"   • Execution {execution_id} ({engine_type})")
                    
                    self._batched_log.flush()  # Flush immediately for user feedback
                    
                    # Emit signal to load results in main window
                    self.load_results_requested.emit({
                        'selected_executions': selected_executions,
                        'output_dir': output_dir
                    })
                else:
                    self._batched_log.append_text("\n⚠️ No executions selected")
                    self._batched_log.flush()
            
        except ImportError as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import database loader:\n\n{str(e)}\n\n"
                "This may indicate a missing dependency or installation issue."
            )
            import traceback
            traceback.print_exc()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Loading Results",
                f"Failed to load results:\n\n{str(e)}\n\n"
                "Check the console for detailed error information."
            )
            import traceback
            traceback.print_exc()
    
    def _select_all_wings(self):
        """Select all wings"""
        for i in range(self.wing_list.count()):
            item = self.wing_list.item(i)
            item.setCheckState(Qt.Checked)
        self._update_selected_count()
    
    def _deselect_all_wings(self):
        """Deselect all wings"""
        for i in range(self.wing_list.count()):
            item = self.wing_list.item(i)
            item.setCheckState(Qt.Unchecked)
        self._update_selected_count()
    
    def _update_selected_count(self):
        """Update the selected count label"""
        selected_count = 0
        for i in range(self.wing_list.count()):
            item = self.wing_list.item(i)
            if item.checkState() == Qt.Checked:
                selected_count += 1
        
        total_count = self.wing_list.count()
        self.selected_count_label.setText(f"{selected_count}/{total_count} selected")
    
    def _on_engine_changed(self, index: int):
        """Handle engine selection change with integration features"""
        engine_type = self.engine_combo.itemData(index)
        
        # Update description and recommendations
        from ..engine.engine_selector import EngineSelector
        engines = EngineSelector.get_available_engines()
        
        for engine_data in engines:
            # Handle both old and new format for backward compatibility
            if len(engine_data) >= 7:  # New format with integration features
                et, name, desc, complexity, use_cases, supports_id_filter, integration_features = engine_data
            else:  # Old format
                et, name, desc, complexity, use_cases, supports_id_filter = engine_data
                integration_features = {}
            
            if et == engine_type:
                self.engine_description.setText(desc)
                # engine_recommendations and integration_features_label are hidden
                
                # Show/hide identity filter based on engine support
                if hasattr(self, 'identity_filter_group'):
                    self.identity_filter_group.setVisible(supports_id_filter)
                break
        
        # Update pipeline config if loaded
        if self.current_pipeline:
            self.current_pipeline.engine_type = engine_type
    
    def _show_integration_features(self):
        """Show integration features dialog for selected engine"""
        engine_type = self.engine_combo.currentData()
        if not engine_type:
            return
        
        from ..engine.engine_selector import EngineSelector
        
        # Get engine metadata with integration features
        engine_metadata = EngineSelector.get_engine_metadata(engine_type)
        if not engine_metadata:
            QMessageBox.information(self, "No Information", "No integration features information available.")
            return
        
        # Handle both old and new format
        if len(engine_metadata) >= 7:
            _, name, desc, complexity, use_cases, supports_id_filter, integration_features = engine_metadata
        else:
            _, name, desc, complexity, use_cases, supports_id_filter = engine_metadata
            integration_features = {}
        
        # Create features dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Integration Features - {name}")
        dialog.setModal(True)
        dialog.resize(600, 500)
        
        layout = QVBoxLayout(dialog)
        
        # Header
        header_label = QLabel(f"<h3>{name}</h3>")
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Description
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #888; margin: 10px;")
        layout.addWidget(desc_label)
        
        # Features list
        features_text = QTextEdit()
        features_text.setReadOnly(True)
        
        features_content = f"<h4>Integration Features ({len(integration_features)} available):</h4>\n\n"
        
        for feature_name, feature_info in integration_features.items():
            supported = feature_info.get('supported', False)
            description = feature_info.get('description', 'No description available')
            feature_list = feature_info.get('features', [])
            
            status_icon = "✅" if supported else "❌"
            features_content += f"<h5>{status_icon} {feature_name.replace('_', ' ').title()}</h5>\n"
            features_content += f"<p><i>{description}</i></p>\n"
            
            if feature_list:
                features_content += "<ul>\n"
                for feature in feature_list:
                    features_content += f"<li>{feature}</li>\n"
                features_content += "</ul>\n"
            
            features_content += "<br>\n"
        
        if not integration_features:
            features_content += "<p><i>No integration features available for this engine.</i></p>\n"
        
        features_text.setHtml(features_content)
        layout.addWidget(features_text)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec_()
    
    def _show_engine_comparison(self):
        """Show enhanced engine comparison dialog with integration features"""
        from ..engine.engine_selector import EngineSelector
        
        # Get comprehensive comparison data
        comparison_data = EngineSelector.get_engine_comparison_data()
        
        # Create comparison dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Correlation Engine Comparison")
        dialog.setModal(True)
        dialog.resize(800, 600)
        
        layout = QVBoxLayout(dialog)
        
        # Header
        header_label = QLabel("<h2>Correlation Engine Comparison</h2>")
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Comparison content
        comparison_text = QTextEdit()
        comparison_text.setReadOnly(True)
        
        content = ""
        
        # Engine overview
        content += "<h3>Available Engines:</h3>\n"
        for engine_info in comparison_data['engines']:
            engine_type = engine_info['type']
            name = engine_info['name']
            desc = engine_info['description']
            complexity = engine_info['complexity']
            use_cases = engine_info['use_cases']
            supports_id_filter = engine_info['supports_identity_filter']
            integration_features = engine_info['integration_features']
            
            content += f"<h4>{name}</h4>\n"
            content += f"<p><b>Complexity:</b> {complexity}</p>\n"
            content += f"<p><b>Description:</b> {desc}</p>\n"
            content += f"<p><b>Identity Filter Support:</b> {'Yes' if supports_id_filter else 'No'}</p>\n"
            
            content += "<p><b>Best for:</b></p>\n<ul>\n"
            for use_case in use_cases:
                content += f"<li>{use_case}</li>\n"
            content += "</ul>\n"
            
            content += f"<p><b>Integration Features ({len(integration_features)}):</b></p>\n<ul>\n"
            for feature_name, feature_info in integration_features.items():
                supported = feature_info.get('supported', False)
                description = feature_info.get('description', '')
                status_icon = "✅" if supported else "❌"
                content += f"<li>{status_icon} <b>{feature_name.replace('_', ' ').title()}:</b> {description}</li>\n"
            content += "</ul>\n"
            
            content += "<hr>\n"
        
        # Feature matrix
        content += "<h3>Feature Comparison Matrix:</h3>\n"
        content += "<table border='1' cellpadding='5' cellspacing='0'>\n"
        content += "<tr><th>Feature</th>"
        
        # Header row with engine names
        for engine_info in comparison_data['engines']:
            content += f"<th>{engine_info['name']}</th>"
        content += "</tr>\n"
        
        # Feature rows
        for feature_name, feature_data in comparison_data['feature_matrix'].items():
            content += f"<tr><td><b>{feature_name.replace('_', ' ').title()}</b></td>"
            
            for engine_info in comparison_data['engines']:
                engine_type = engine_info['type']
                if engine_type in feature_data:
                    supported = feature_data[engine_type]['supported']
                    status = "✅ Yes" if supported else "❌ No"
                else:
                    status = "❓ Unknown"
                content += f"<td>{status}</td>"
            
            content += "</tr>\n"
        
        content += "</table>\n"
        
        # Performance comparison
        content += "<h3>Performance Comparison:</h3>\n"
        content += "<table border='1' cellpadding='5' cellspacing='0'>\n"
        content += "<tr><th>Engine</th><th>Complexity</th><th>Memory Efficiency</th><th>Processing Speed</th><th>Scalability</th></tr>\n"
        
        for engine_info in comparison_data['engines']:
            engine_type = engine_info['type']
            name = engine_info['name']
            perf_data = comparison_data['performance_comparison'][engine_type]
            
            content += f"<tr>"
            content += f"<td><b>{name}</b></td>"
            content += f"<td>{perf_data['complexity']}</td>"
            content += f"<td>{perf_data['memory_efficiency']}</td>"
            content += f"<td>{perf_data['processing_speed']}</td>"
            content += f"<td>{perf_data['scalability']}</td>"
            content += "</tr>\n"
        
        content += "</table>\n"
        
        comparison_text.setHtml(content)
        layout.addWidget(comparison_text)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec_()
    
    def _get_filter_config(self) -> dict:
        """Get current filter configuration from GUI controls"""
        filters = {}
        
        # Time period filter
        if hasattr(self, 'start_enabled') and self.start_enabled.isChecked():
            filters['time_period_start'] = self.start_datetime.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
        
        if hasattr(self, 'end_enabled') and self.end_enabled.isChecked():
            filters['time_period_end'] = self.end_datetime.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
        
        # Identity filter (if visible)
        if hasattr(self, 'identity_filter_section') and self.identity_filter_section.isVisible():
            identity_text = self.identity_filter_input.toPlainText().strip()
            if identity_text:
                # Split by newlines and filter empty lines
                filters['identity_filters'] = [line.strip() for line in identity_text.split('\n') if line.strip()]
                filters['identity_filter_case_sensitive'] = self.case_sensitive_checkbox.isChecked()
        
        return filters
    
    def _get_selected_wings(self):
        """Get list of selected wing configs"""
        selected_wings = []
        for i in range(self.wing_list.count()):
            item = self.wing_list.item(i)
            if item.checkState() == Qt.Checked:
                wing_config = item.data(Qt.UserRole)
                selected_wings.append(wing_config)
        return selected_wings
    

    def _handle_progress_event(self, event):
        """
        Handle progress events and display them in the log output.
        This replaces the progress_display widget functionality.
        Thread-safe: Uses signals to update GUI from worker thread.
        
        Args:
            event: ProgressEvent object with event_type and overall_progress
        """
        # Handle new ProgressEvent objects with ProgressEventType
        if hasattr(event, 'event_type') and hasattr(event, 'overall_progress'):
            # New progress tracking system
            from ..engine.progress_tracking import ProgressEventType
            
            if event.event_type == ProgressEventType.SCANNING_START:
                progress = event.overall_progress
                self.progress_message.emit(f"\n[Correlation] Starting correlation scan...")
                self.progress_message.emit(f"[Correlation] Total windows to process: {progress.total_windows}")
                self.progress_message.emit(f"[Correlation] Processing mode: {progress.processing_mode}")
                if progress.streaming_mode:
                    self.progress_message.emit(f"[Correlation] Streaming mode: enabled")
            
            elif event.event_type == ProgressEventType.WINDOW_START:
                if hasattr(event, 'window_progress') and event.window_progress:
                    wp = event.window_progress
                    self.progress_message.emit(f"[Correlation] Processing window: {wp.window_id}")
            
            elif event.event_type == ProgressEventType.WINDOW_COMPLETE:
                if hasattr(event, 'window_progress') and event.window_progress:
                    wp = event.window_progress
                    self.progress_message.emit(
                        f"[Correlation] Window {wp.window_id} complete: "
                        f"{wp.records_found} records, {wp.matches_created} matches, "
                        f"{wp.processing_time_seconds:.2f}s"
                    )
            
            elif event.event_type == ProgressEventType.WINDOW_PROGRESS:
                # Throttle progress updates to avoid flooding the GUI
                if self._should_throttle_progress():
                    return
                
                progress = event.overall_progress
                percentage = progress.completion_percentage
                time_remaining = ""
                if progress.time_remaining_seconds:
                    remaining_mins = int(progress.time_remaining_seconds / 60)
                    remaining_secs = int(progress.time_remaining_seconds % 60)
                    if remaining_mins > 0:
                        time_remaining = f", ETA: {remaining_mins}m {remaining_secs}s"
                    else:
                        time_remaining = f", ETA: {remaining_secs}s"
                
                rate_info = ""
                if progress.processing_rate_windows_per_second:
                    rate_info = f", {progress.processing_rate_windows_per_second:.1f}/sec"
                
                self.progress_message.emit(
                    f"[Progress] {percentage:.1f}% ({progress.windows_processed}/{progress.total_windows} windows, "
                    f"{progress.matches_found} matches{rate_info}{time_remaining})"
                )
            
            elif event.event_type == ProgressEventType.STREAMING_ENABLED:
                self.progress_message.emit(f"[Correlation] Streaming mode enabled: {event.message}")
            
            elif event.event_type == ProgressEventType.MEMORY_WARNING:
                self.progress_message.emit(f"[Warning] Memory usage high: {event.message}")
            
            elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
                progress = event.overall_progress
                self.progress_message.emit(f"\n[Correlation] Scan complete!")
                self.progress_message.emit(f"[Correlation] Total matches found: {progress.matches_found}")
                self.progress_message.emit(f"[Correlation] Windows processed: {progress.windows_processed}")
            
            elif event.event_type == ProgressEventType.DATABASE_QUERY_START:
                data = event.additional_data
                self.progress_message.emit(f"[Database] Querying {data['total_feathers']} feathers...")
            
            elif event.event_type == ProgressEventType.DATABASE_QUERY_PROGRESS:
                data = event.additional_data
                # Update the same line to show progress without flooding the log
                feather_id = data['feather_id']
                feathers_queried = data['feathers_queried']
                total_feathers = data['total_feathers']
                records_found = data['records_found']
                
                # Show a dynamic progress indicator
                progress_percent = (feathers_queried / total_feathers * 100) if total_feathers > 0 else 0
                self.progress_message.emit(
                    f"[Database] {progress_percent:.0f}% - {feather_id}: {records_found} records "
                    f"({feathers_queried}/{total_feathers})"
                )
            
            elif event.event_type == ProgressEventType.DATABASE_QUERY_COMPLETE:
                data = event.additional_data
                self.progress_message.emit(
                    f"[Database] Query complete: {data['total_records']} records "
                    f"from {data['total_feathers']} feathers ({data['query_time_seconds']:.2f}s)"
                )
            
            elif event.event_type == ProgressEventType.ERROR_OCCURRED:
                self.progress_message.emit(f"[Error] {event.message}")
                if hasattr(event, 'error_details') and event.error_details:
                    self.progress_message.emit(f"[Error Details] {event.error_details}")
        
        # Handle legacy event format (for backward compatibility)
        elif hasattr(event, 'event_type') and hasattr(event, 'data'):
            event_type = event.event_type
            data = event.data
            
            if event_type == "wing_start":
                self.progress_message.emit(f"\n[Correlation] Wing: {data['wing_name']} (ID: {data['wing_id']})")
                self.progress_message.emit(f"[Correlation] Feathers in wing: {data['feather_count']}")
            
            elif event_type == "anchor_collection":
                self.progress_message.emit(
                    f"[Correlation]   • {data['feather_id']} "
                    f"({data['artifact_type']}): {data['anchor_count']} anchors"
                )
            
            elif event_type == "correlation_start":
                self.progress_message.emit(f"[Correlation] Total anchors collected: {data['total_anchors']}")
                self.progress_message.emit(f"[Correlation] Time window: {data['time_window']} minutes")
                self.progress_message.emit(f"[Correlation] Minimum matches required: {data['minimum_matches']}")
                self.progress_message.emit("[Correlation] Starting correlation analysis...")
            
            elif event_type == "anchor_progress":
                # Throttle progress updates to avoid flooding the GUI
                if self._should_throttle_progress():
                    return
                
                # Show progress updates
                self.progress_message.emit(
                    f"    [Analyzing] Anchor {data['anchor_index']}/{data['total_anchors']} "
                    f"from {data['feather_id']} ({data['artifact_type']}) "
                    f"at {data['timestamp']}"
                )
            
            elif event_type == "summary_progress":
                # Throttle summary progress updates
                if self._should_throttle_progress():
                    return
                
                # Show summary progress
                self.progress_message.emit(
                    f"    Progress: {data['anchors_processed']}/{data['total_anchors']} "
                    f"anchors processed, {data['matches_found']} matches found"
                )
    
    def _should_throttle_progress(self) -> bool:
        """
        Check if progress update should be throttled.
        
        Returns:
            True if update should be skipped (throttled)
        """
        now = datetime.now()
        
        if self._last_progress_time is None:
            self._last_progress_time = now
            return False
        
        elapsed = (now - self._last_progress_time).total_seconds()
        
        if elapsed < self._min_progress_interval:
            return True
        
        self._last_progress_time = now
        return False
    
    def _setup_output_redirection(self):
        """Setup stdout/stderr redirection to log output widget"""
        # Create redirectors that write ONLY to the widget (not to original streams)
        # This prevents duplicate output in the terminal
        self.stdout_redirector = OutputRedirector(self.log_output, None)
        self.stderr_redirector = OutputRedirector(self.log_output, None)
        
        # Keep strong references to prevent garbage collection
        self.stdout_redirector.setParent(self)
        self.stderr_redirector.setParent(self)
        
        # Redirect stdout and stderr
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stderr_redirector
    
    def closeEvent(self, event):
        """Restore stdout/stderr when closing"""
        # Restore original streams
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        
        # Clean up redirectors
        if self.stdout_redirector:
            self.stdout_redirector.deleteLater()
            self.stdout_redirector = None
        if self.stderr_redirector:
            self.stderr_redirector.deleteLater()
            self.stderr_redirector = None
        
        super().closeEvent(event)