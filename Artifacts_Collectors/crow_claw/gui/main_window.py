"""
Main Window Implementation
==========================

Main PyQt5 window for Crow-Claw artifact acquisition tool.
Integrates with Crow-Eye styling for consistent UI appearance.

Phase 2: GUI Main Window
"""

import sys
import os
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QMessageBox,
    QProgressBar, QTextEdit, QFileDialog, QCheckBox,
    QFrame, QSplitter, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QIcon, QPixmap

# Add parent directory to path for importing modules
crow_eye_root = Path(__file__).parent.parent.parent.resolve()
if str(crow_eye_root) not in sys.path:
    sys.path.insert(0, str(crow_eye_root))

# Import from crow_claw package
from crow_claw.core import Artifact, get_all_artifacts, ArtifactType
from crow_claw.core.validator import PathValidator

try:
    from Artifacts_Collectors.windows_partition_detector import WindowsPartitionDetector
except ImportError:
    WindowsPartitionDetector = None


class HeaderPanel(QWidget):
    """Header panel with title, subtitle, and output directory selector.

    Supports two modes:
    - Integrated mode: Shows case directory and hides output selector
    - Standalone mode: Shows output directory selector
    """

    def __init__(self, parent=None, integrated_mode=False, case_directory=None):
        super().__init__(parent)
        self.full_output_path = None
        self.integrated_mode = integrated_mode
        self.case_directory = case_directory
        self.setup_ui()

    def setup_ui(self):
        """Setup header UI components for both integrated and standalone modes."""
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)

        # Title - Professional style
        title = QLabel("CROW-CLAW")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_font.setFamily("Segoe UI")
        title.setFont(title_font)
        title.setStyleSheet(
            "color: #FFFFFF; "
            "background-color: transparent; "
            "letter-spacing: 3px;"
        )
        layout.addWidget(title)

        # Subtitle with mode indicator - Professional
        subtitle_text = "Windows Forensic Artifact Acquisition Tool"
        if self.integrated_mode:
            subtitle_text += " | Integrated Mode"
        subtitle = QLabel(subtitle_text)
        subtitle_font = QFont()
        subtitle_font.setPointSize(10)
        subtitle_font.setBold(False)
        subtitle.setFont(subtitle_font)
        subtitle.setStyleSheet(
            "color: #94A3B8; "
            "background-color: transparent; "
            "letter-spacing: 0.5px;"
        )
        layout.addWidget(subtitle)

        # Separator - Professional line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(
            "background-color: #475569; "
            "border: none; "
            "height: 1px; "
            "margin: 8px 0px;"
        )
        layout.addWidget(separator)

        # Status info layout - all aligned together
        status_layout = QVBoxLayout()
        status_layout.setSpacing(3)
        status_layout.setContentsMargins(0, 5, 0, 5)

        # Admin status indicator (no border, plain text)
        admin_layout = QHBoxLayout()
        admin_layout.setSpacing(10)
        admin_label = QLabel("Admin Status:")
        admin_label_font = QFont()
        admin_label_font.setPointSize(9)
        admin_label_font.setBold(True)
        admin_label.setFont(admin_label_font)
        admin_label.setStyleSheet("color: #CBD5E1; font-weight: 600;")
        admin_label.setMinimumWidth(150)
        
        self.admin_status_indicator = QLabel("Checking...")
        indicator_font = QFont()
        indicator_font.setPointSize(9)
        indicator_font.setBold(True)
        self.admin_status_indicator.setFont(indicator_font)
        self.admin_status_indicator.setStyleSheet(
            "color: #F59E0B; "
            "font-weight: 600; "
            "background-color: transparent;"
        )
        admin_layout.addWidget(admin_label)
        admin_layout.addWidget(self.admin_status_indicator)
        admin_layout.addStretch()
        status_layout.addLayout(admin_layout)

        # Windows partition info (no border, plain text)
        partition_layout = QHBoxLayout()
        partition_layout.setSpacing(10)
        partition_label = QLabel("Active Partition:")
        partition_label_font = QFont()
        partition_label_font.setPointSize(9)
        partition_label_font.setBold(True)
        partition_label.setFont(partition_label_font)
        partition_label.setStyleSheet("color: #CBD5E1; font-weight: 600;")
        partition_label.setMinimumWidth(150)
        
        self.partition_info = QLabel("Detecting...")
        partition_info_font = QFont()
        partition_info_font.setPointSize(9)
        partition_info_font.setBold(True)
        self.partition_info.setFont(partition_info_font)
        self.partition_info.setStyleSheet(
            "color: #60A5FA; "
            "font-weight: 600; "
            "background-color: transparent;"
        )
        partition_layout.addWidget(partition_label)
        partition_layout.addWidget(self.partition_info)
        partition_layout.addStretch()
        status_layout.addLayout(partition_layout)

        # Mode-specific output/case directory display
        if self.integrated_mode:
            # Integrated mode: Show case directory (read-only, no border)
            case_layout = QHBoxLayout()
            case_layout.setSpacing(10)
            case_label = QLabel("Case Directory:")
            case_label_font = QFont()
            case_label_font.setPointSize(9)
            case_label_font.setBold(True)
            case_label.setFont(case_label_font)
            case_label.setStyleSheet("color: #CBD5E1; font-weight: 600;")
            case_label.setMinimumWidth(150)
            
            self.case_path = QLabel("(No case directory)")
            case_path_font = QFont()
            case_path_font.setPointSize(9)
            case_path_font.setBold(True)
            self.case_path.setFont(case_path_font)
            self.case_path.setStyleSheet("color: #34D399; font-weight: 600; background-color: transparent;")
            if self.case_directory:
                self.case_path.setText(self.case_directory)
                self.case_path.setToolTip(self.case_directory)
            case_layout.addWidget(case_label)
            case_layout.addWidget(self.case_path)
            case_layout.addStretch()
            status_layout.addLayout(case_layout)

            # Show target artifact directory (no border)
            artifact_layout = QHBoxLayout()
            artifact_layout.setSpacing(10)
            artifact_label = QLabel("Output Directory:")
            artifact_label_font = QFont()
            artifact_label_font.setPointSize(9)
            artifact_label_font.setBold(True)
            artifact_label.setFont(artifact_label_font)
            artifact_label.setStyleSheet("color: #CBD5E1; font-weight: 600;")
            artifact_label.setMinimumWidth(150)
            
            self.target_artifact_path = QLabel("(Not set)")
            target_font = QFont()
            target_font.setPointSize(9)
            target_font.setBold(True)
            self.target_artifact_path.setFont(target_font)
            self.target_artifact_path.setStyleSheet("color: #34D399; font-weight: 600; background-color: transparent;")
            if self.case_directory:
                # In integrated mode, output goes directly to case_directory (live_acquisition)
                self.target_artifact_path.setText(self.case_directory)
                self.target_artifact_path.setToolTip(self.case_directory)
            artifact_layout.addWidget(artifact_label)
            artifact_layout.addWidget(self.target_artifact_path)
            artifact_layout.addStretch()
            status_layout.addLayout(artifact_layout)
        else:
            # Standalone mode: Show output directory selector (no border on text)
            output_layout = QHBoxLayout()
            output_layout.setSpacing(10)
            output_label = QLabel("Output Directory:")
            output_label_font = QFont()
            output_label_font.setPointSize(9)
            output_label_font.setBold(True)
            output_label.setFont(output_label_font)
            output_label.setStyleSheet("color: #CBD5E1; font-weight: 600;")
            output_label.setMinimumWidth(150)
            
            # Output path - RED when not selected, GREEN when selected (no border)
            self.output_path = QLabel("(No directory selected)")
            output_path_font = QFont()
            output_path_font.setPointSize(9)
            output_path_font.setBold(True)
            self.output_path.setFont(output_path_font)
            self.output_path.setStyleSheet(
                "color: #EF4444; "  # RED for not selected
                "font-weight: 600; "
                "background-color: transparent;"
            )
            
            self.output_button = QPushButton("BROWSE...")
            button_font = QFont()
            button_font.setPointSize(9)
            button_font.setBold(True)
            self.output_button.setFont(button_font)
            self.output_button.setMaximumWidth(120)
            self.output_button.setMinimumHeight(32)
            self.output_button.setStyleSheet(
                "QPushButton { "
                "background-color: #3B82F6; "
                "color: #FFFFFF; "
                "border: none; "
                "border-radius: 4px; "
                "padding: 6px 16px; "
                "font-weight: 600; "
                "} "
                "QPushButton:hover { "
                "background-color: #2563EB; "
                "} "
                "QPushButton:pressed { "
                "background-color: #1D4ED8; "
                "}"
            )

            output_layout.addWidget(output_label)
            output_layout.addWidget(self.output_path, 1)  # Stretch to fill
            output_layout.addWidget(self.output_button)
            status_layout.addLayout(output_layout)

        # Add status layout to main layout
        layout.addLayout(status_layout)

        layout.addStretch()
        self.setLayout(layout)

        # Apply dark background
        self.setStyleSheet("background-color: #0F172A;")

    def get_output_path(self) -> Optional[str]:
        """Get selected output path."""
        return self.full_output_path

    def set_output_path(self, path: str):
        """Set output path display and change color to GREEN when selected."""
        self.full_output_path = path
        display_text = path
        if len(display_text) > 50:
            display_text = "..." + display_text[-47:]
        
        self.output_path.setText(f"✓ {display_text}")
        self.output_path.setToolTip(path)
        
        # Change to GREEN when path is selected (no border)
        self.output_path.setStyleSheet(
            "color: #10B981; "  # GREEN for selected
            "font-weight: 600; "
            "background-color: transparent;"
        )

    def set_partition_info(self, partition: str):
        """Set Windows partition display."""
        self.partition_info.setText(f"✓ {partition} (auto-detected)")
        self.partition_info.setToolTip(f"Windows installation found on partition: {partition}")

    def set_admin_status(self, is_admin: bool):
        """Set admin status display with prominent visual indicator.
        
        Args:
            is_admin: Whether the application is running with admin privileges
        """
        if is_admin:
            self.admin_status_indicator.setText("✓ Administrator")
            self.admin_status_indicator.setStyleSheet(
                "color: #00FF88; font-weight: bold; padding: 5px; "
                "background-color: #1E293B; border: 2px solid #00FF88; border-radius: 3px;"
            )
            self.admin_status_indicator.setToolTip("Running with administrator privileges - all artifacts can be collected")
        else:
            self.admin_status_indicator.setText("⚠ Standard User")
            self.admin_status_indicator.setStyleSheet(
                "color: #FF6B6B; font-weight: bold; padding: 5px; "
                "background-color: #1E293B; border: 2px solid #FF6B6B; border-radius: 3px;"
            )
            self.admin_status_indicator.setToolTip("Not running as administrator - some artifacts require elevation")


class CollectionWorker(QThread):
    """Worker thread for artifact collection to prevent GUI freezing."""
    
    # Signals for communication with main thread
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, object)  # success, statistics
    error_signal = pyqtSignal(str)
    
    def __init__(self, artifacts, output_directory, windows_partition, is_admin=False):
        super().__init__()
        self.artifacts = artifacts
        self.output_directory = output_directory
        self.windows_partition = windows_partition
        self.is_admin = is_admin
        self.collector = None
        
    def run(self):
        """Run collection in background thread."""
        try:
            from ..core.collector import ArtifactCollector
            import time
            
            # Create collector with admin status from main thread
            self.collector = ArtifactCollector(verbose=True, is_admin=self.is_admin)
            
            # Rate limiting for GUI updates to prevent flooding
            last_log_time = 0
            last_status_time = 0
            log_interval = 0.3  # Minimum 300ms between log updates (was 0.1)
            status_interval = 0.15  # Minimum 150ms between status updates (was 0.05)
            
            # Set up callbacks that emit signals with rate limiting
            def log_callback(message: str):
                nonlocal last_log_time
                current_time = time.time()
                # Rate limit log messages to prevent GUI flooding
                if current_time - last_log_time >= log_interval:
                    self.log_signal.emit(message)
                    last_log_time = current_time
            
            def progress_callback(percent: int):
                self.progress_signal.emit(percent)
            
            def status_callback(message: str):
                nonlocal last_status_time
                current_time = time.time()
                # Rate limit status messages to prevent GUI flooding
                if current_time - last_status_time >= status_interval:
                    self.status_signal.emit(message)
                    last_status_time = current_time
            
            # Set callbacks
            self.collector.set_progress_callback(progress_callback)
            self.collector.set_status_callback(status_callback)
            
            # Override log method with rate limiting
            original_log = self.collector.log
            def custom_log(message: str):
                log_callback(message)
                # Still call original log for file logging
                try:
                    original_log(message)
                except Exception as log_error:
                    # Don't crash on logging errors
                    pass
            self.collector.log = custom_log
            
            # Collect artifacts
            success, statistics = self.collector.collect_artifacts(
                artifacts=self.artifacts,
                output_directory=self.output_directory,
                windows_partition=self.windows_partition,
                handle_locked_files="skip"
            )
            
            # Emit finished signal
            self.finished_signal.emit(success, statistics)
            
        except Exception as e:
            import traceback
            error_details = f"{str(e)}\n{traceback.format_exc()}"
            self.error_signal.emit(error_details)


class CrowClawMainWindow(QMainWindow):
    """
    Main window for Crow-Claw artifact acquisition tool.

    Features:
    - Displays all artifact types with configurable paths
    - Allows custom path configuration
    - Handles artifact collection with progress tracking
    - Generates collection manifest
    """

    # Signals
    collection_started = pyqtSignal()
    collection_completed = pyqtSignal(dict)
    collection_failed = pyqtSignal(str)

    def __init__(self, parent=None, case_directory=None):
        super().__init__(parent)
        self.setWindowTitle("Crow-Claw - Artifact Acquisition Tool")
        self.setGeometry(100, 100, 1200, 800)

        # Load Crow-Eye styles
        self.apply_crow_eye_styles()

        # Determine if running in integrated mode
        self.integrated_mode = case_directory is not None
        self.case_directory = case_directory

        # Detect Windows partition
        self.windows_partition = self.detect_windows_partition()
        print(f"[INFO] Detected Windows partition: {self.windows_partition}")

        # Initialize artifacts
        self.artifacts = get_all_artifacts()
        self.selected_artifact: Optional[Artifact] = None

        # Set full_output_path based on mode
        if self.integrated_mode and self.case_directory:
            # Integrated mode: output is directly in the case_directory
            # The case_directory passed from Crow-Eye is already the live_acquisition directory
            self.full_output_path = self.case_directory
            print(f"[INFO] Running in INTEGRATED mode")
            print(f"[INFO] Case directory: {self.case_directory}")
            print(f"[INFO] Output path will be set to: {self.full_output_path}")
        else:
            # Standalone mode: user selects output directory
            self.full_output_path: Optional[str] = None
            print(f"[INFO] Running in STANDALONE mode, user must select output directory")

        # Setup UI
        self.setup_ui()

        # Display detected Windows partition in header
        self.header.set_partition_info(self.windows_partition)

        # Check admin status
        self.check_admin_status()

    def apply_crow_eye_styles(self):
        """Apply Crow-Eye styling to the main window."""
        try:
            # Add path to load styles from main app directory
            if not hasattr(sys, 'frozen'):
                # Running from source, go up to main project dir
                main_app_dir = Path(__file__).parent.parent.parent.parent
                sys.path.append(str(main_app_dir))

            from styles import CrowEyeStyles
            self.setStyleSheet(CrowEyeStyles.BODY)
            
        except Exception as e:
            print(f"Warning: Could not load Crow-Eye styles, using fallback: {e}")
            self.setStyleSheet(self.get_default_styles())

    @staticmethod
    def get_default_styles() -> str:
        """Get default dark theme styles."""
        return """
            QMainWindow {
                background-color: #0F172A;
            }
            QLabel {
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #1E293B;
                color: #FFFFFF;
                border: 1px solid #00FFFF;
                border-radius: 4px;
                padding: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QPushButton:pressed {
                background-color: #00FFFF;
                color: #0F172A;
            }
            QLineEdit, QTextEdit {
                background-color: #1E293B;
                color: #FFFFFF;
                border: 1px solid #00FFFF;
                border-radius: 4px;
                padding: 5px;
            }
            QComboBox {
                background-color: #1E293B;
                color: #FFFFFF;
                border: 1px solid #00FFFF;
                border-radius: 4px;
                padding: 5px;
            }
            QCheckBox {
                color: #FFFFFF;
            }
            QProgressBar {
                background-color: #1E293B;
                border: 1px solid #00FFFF;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #00FFFF;
            }
            QTabWidget::pane {
                border: 1px solid #00FFFF;
            }
            QTabBar::tab {
                background-color: #1E293B;
                color: #FFFFFF;
                padding: 5px;
            }
            QTabBar::tab:selected {
                background-color: #334155;
                color: #00FFFF;
                border-bottom: 2px solid #00FFFF;
            }
            QListWidget {
                background-color: #1E293B;
                color: #FFFFFF;
                border: 1px solid #00FFFF;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #00FFFF;
                color: #0F172A;
            }
            QFrame {
                background-color: #0F172A;
            }
            
            /* Scrollbar Styling */
            QScrollBar:vertical {
                background-color: #0F172A;
                width: 16px;
                border: 1px solid #00FFFF;
                border-radius: 2px;
                margin: 16px 0 16px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #334155;
                border: 1px solid #00FFFF;
                border-radius: 2px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #475569;
            }
            QScrollBar::handle:vertical:pressed {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:vertical {
                background-color: #1E293B;
                border: 1px solid #00FFFF;
                height: 14px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
                border-radius: 2px;
            }
            QScrollBar::sub-line:vertical {
                background-color: #1E293B;
                border: 1px solid #00FFFF;
                height: 14px;
                subcontrol-position: top;
                subcontrol-origin: margin;
                border-radius: 2px;
            }
            QScrollBar::add-line:vertical:hover,
            QScrollBar::sub-line:vertical:hover {
                background-color: #334155;
            }
            QScrollBar::add-line:vertical:pressed,
            QScrollBar::sub-line:vertical:pressed {
                background-color: #00FFFF;
            }
            QScrollBar::up-arrow:vertical {
                image: none;
                border: none;
                width: 0px;
                height: 0px;
            }
            QScrollBar::down-arrow:vertical {
                image: none;
                border: none;
                width: 0px;
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            
            /* Horizontal Scrollbar */
            QScrollBar:horizontal {
                background-color: #0F172A;
                height: 16px;
                border: 1px solid #00FFFF;
                border-radius: 2px;
                margin: 0 16px 0 16px;
            }
            QScrollBar::handle:horizontal {
                background-color: #334155;
                border: 1px solid #00FFFF;
                border-radius: 2px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #475569;
            }
            QScrollBar::handle:horizontal:pressed {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:horizontal {
                background-color: #1E293B;
                border: 1px solid #00FFFF;
                width: 14px;
                subcontrol-position: right;
                subcontrol-origin: margin;
                border-radius: 2px;
            }
            QScrollBar::sub-line:horizontal {
                background-color: #1E293B;
                border: 1px solid #00FFFF;
                width: 14px;
                subcontrol-position: left;
                subcontrol-origin: margin;
                border-radius: 2px;
            }
            QScrollBar::add-line:horizontal:hover,
            QScrollBar::sub-line:horizontal:hover {
                background-color: #334155;
            }
            QScrollBar::add-line:horizontal:pressed,
            QScrollBar::sub-line:horizontal:pressed {
                background-color: #00FFFF;
            }
            QScrollBar::left-arrow:horizontal,
            QScrollBar::right-arrow:horizontal {
                image: none;
                border: none;
                width: 0px;
                height: 0px;
            }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: none;
            }
        """

    def setup_ui(self):
        """Setup main window UI with step-by-step workflow."""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header panel with mode information
        self.header = HeaderPanel(
            integrated_mode=self.integrated_mode,
            case_directory=self.case_directory
        )

        # Connect output button only in standalone mode
        if not self.integrated_mode:
            self.header.output_button.clicked.connect(self.select_output_directory)

        main_layout.addWidget(self.header)

        # Content area: splitter with steps on left and content on right
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(15)

        # Left: Steps Panel (NARROW SIDEBAR)
        left_panel = QWidget()
        left_panel.setMaximumWidth(200)  # Fixed narrow width
        left_panel.setMinimumWidth(150)
        steps_layout = QVBoxLayout()
        steps_layout.setContentsMargins(10, 0, 10, 0)
        steps_layout.setSpacing(10)

        # Step indicator label
        step_label = QLabel("STEPS")
        step_label.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 10px;")
        steps_layout.addWidget(step_label)

        # Step buttons
        self.step_buttons = {}
        steps = [
            ("1. Configure", "artifacts"),
            ("2. Collect", "collection")
        ]

        for step_text, step_id in steps:
            btn = QPushButton(step_text)
            btn.setMinimumHeight(60)
            btn.setStyleSheet(
                "background-color: #1E293B; color: #FFFFFF; border: 1px solid #00FFFF; "
                "border-radius: 4px; padding: 8px; text-align: center; font-weight: bold; font-size: 10px;"
            )
            btn.clicked.connect(lambda checked, sid=step_id: self.switch_step(sid))
            self.step_buttons[step_id] = btn
            steps_layout.addWidget(btn)

        steps_layout.addStretch()
        left_panel.setLayout(steps_layout)

        # Right: Content Area using Stacked Widget (TAKES FULL SPACE)
        from PyQt5.QtWidgets import QStackedWidget
        self.stacked_widget = QStackedWidget()

        # Step 1: Artifact Configuration + Path Management (MERGED)
        self.artifact_config_widget = self.create_artifact_config_widget()
        self.stacked_widget.addWidget(self.artifact_config_widget)

        # Step 2: Collection
        self.collection_widget = self.create_collection_widget()
        self.stacked_widget.addWidget(self.collection_widget)

        # Add to content layout
        content_layout.addWidget(left_panel, 0)  # Left panel (fixed width, no stretch)
        content_layout.addWidget(self.stacked_widget, 1)  # Right panel (STRETCHES TO FILL)

        main_layout.addLayout(content_layout, 1)  # Give main layout stretch
        central.setLayout(main_layout)

        # Show first step by default
        self.switch_step("artifacts")

    def switch_step(self, step_id: str):
        """Switch to a different workflow step."""
        step_map = {"artifacts": 0, "collection": 1}
        if step_id in step_map:
            self.stacked_widget.setCurrentIndex(step_map[step_id])

            # Highlight current step button
            for btn_id, btn in self.step_buttons.items():
                if btn_id == step_id:
                    btn.setStyleSheet(
                        "background-color: #00FFFF; color: #0F172A; border: 2px solid #00FFFF; "
                        "border-radius: 4px; padding: 10px; text-align: left; font-weight: bold;"
                    )
                else:
                    btn.setStyleSheet(
                        "background-color: #1E293B; color: #FFFFFF; border: 1px solid #00FFFF; "
                        "border-radius: 4px; padding: 10px; text-align: left; font-weight: bold;"
                    )

    def create_artifact_config_widget(self) -> QWidget:
        """Create artifact configuration widget with details and paths."""
        widget = QWidget()
        layout = QHBoxLayout()

        # Left: Artifact list
        left_layout = QVBoxLayout()
        left_label = QLabel("Available Artifacts:")
        left_label.setStyleSheet("color: #00FFFF; font-weight: bold;")
        left_layout.addWidget(left_label)

        self.artifact_list = QListWidget()
        for artifact in self.artifacts:
            # Add visual indicator for admin-required artifacts
            display_name = artifact.name
            if artifact.required_admin:
                display_name = f"🔒 {artifact.name}"
            
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, artifact)
            
            # Color code admin-required artifacts
            if artifact.required_admin:
                from PyQt5.QtGui import QColor, QBrush
                item.setForeground(QBrush(QColor("#FFAA00")))  # Orange color for admin-required
                item.setToolTip(f"{artifact.name} - Requires Administrator Privileges")
            
            self.artifact_list.addItem(item)
        self.artifact_list.itemSelectionChanged.connect(self.on_artifact_selected)
        left_layout.addWidget(self.artifact_list)

        # Right: Tab widget for Details and Paths
        from PyQt5.QtWidgets import QTabWidget
        right_tabs = QTabWidget()
        right_tabs.setStyleSheet(
            "QTabBar::tab { background-color: #1E293B; color: #FFFFFF; padding: 5px; } "
            "QTabBar::tab:selected { background-color: #334155; color: #00FFFF; border-bottom: 2px solid #00FFFF; }"
        )

        # Tab 1: Artifact Details
        details_widget = QWidget()
        details_layout = QVBoxLayout()

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        
        # Enhanced styling with better font
        detail_font = QFont()
        detail_font.setFamily("Consolas")
        detail_font.setPointSize(10)
        self.detail_text.setFont(detail_font)
        
        self.detail_text.setStyleSheet(
            "QTextEdit { "
            "background-color: #0F1419; "
            "color: #E0E0E0; "
            "border: 2px solid #00FFFF; "
            "border-radius: 6px; "
            "padding: 12px; "
            "font-family: Consolas, monospace; "
            "font-size: 10pt; "
            "line-height: 1.5; "
            "}"
        )
        details_layout.addWidget(self.detail_text)

        # Enable/Disable checkbox
        self.enable_checkbox = QCheckBox("✓ Enabled")
        self.enable_checkbox.setChecked(True)
        self.enable_checkbox.stateChanged.connect(self.on_enable_toggled)
        checkbox_font = QFont()
        checkbox_font.setPointSize(10)
        checkbox_font.setBold(True)
        self.enable_checkbox.setFont(checkbox_font)
        self.enable_checkbox.setStyleSheet(
            "QCheckBox { color: #00FF88; font-weight: bold; padding: 5px; } "
            "QCheckBox::indicator { width: 18px; height: 18px; } "
            "QCheckBox::indicator:checked { background-color: #00FF88; border: 2px solid #00FFFF; } "
            "QCheckBox::indicator:unchecked { background-color: #1E293B; border: 2px solid #FF6B6B; }"
        )
        details_layout.addWidget(self.enable_checkbox)

        # Add custom path button
        add_button = QPushButton("Add Custom Path")
        add_button.clicked.connect(self.add_custom_path)
        add_button.setStyleSheet(
            "QPushButton { background-color: #1E293B; color: #FFFFFF; border: 2px solid #00FFFF; border-radius: 4px; padding: 8px; font-weight: 900; font-size: 11px; } "
            "QPushButton:hover { background-color: #334155; color: #00FF88; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; }"
        )
        details_layout.addWidget(add_button)

        details_widget.setLayout(details_layout)
        right_tabs.addTab(details_widget, "Details")

        # Tab 2: Configured Paths
        paths_widget = QWidget()
        paths_layout = QVBoxLayout()

        self.path_text = QTextEdit()
        self.path_text.setStyleSheet(
            "background-color: #1E293B; color: #E0E0E0; border: 1px solid #00FFFF; border-radius: 4px;"
        )
        self.refresh_path_display()  # Initialize with all paths
        paths_layout.addWidget(self.path_text)

        # Refresh button
        refresh_button = QPushButton("Refresh Paths")
        refresh_button.clicked.connect(self.refresh_path_display)
        refresh_button.setStyleSheet(
            "QPushButton { background-color: #1E293B; color: #FFFFFF; border: 2px solid #00FFFF; border-radius: 4px; padding: 8px; font-weight: 900; font-size: 11px; } "
            "QPushButton:hover { background-color: #334155; color: #00FF88; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; }"
        )
        paths_layout.addWidget(refresh_button)

        paths_widget.setLayout(paths_layout)
        right_tabs.addTab(paths_widget, "Paths")

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_layout_wrapper = QVBoxLayout()
        left_layout_wrapper.addLayout(left_layout)
        left_widget.setLayout(left_layout_wrapper)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_tabs)
        splitter.setSizes([250, 750])

        layout.addWidget(splitter)
        widget.setLayout(layout)

        # Auto-select first artifact to show details
        if self.artifacts:
            self.artifact_list.setCurrentRow(0)

        return widget

    def create_path_management_widget(self) -> QWidget:
        """Create path management tab."""
        widget = QWidget()
        layout = QVBoxLayout()

        label = QLabel("Configured Artifact Paths:")
        label.setStyleSheet("color: #00FFFF; font-weight: bold; padding: 10px;")
        layout.addWidget(label)

        self.path_text = QTextEdit()
        self.path_text.setStyleSheet(
            "background-color: #1E293B; color: #FFFFFF; border: 1px solid #00FFFF; border-radius: 4px;"
        )
        self.refresh_path_display()
        layout.addWidget(self.path_text)

        # Buttons
        button_layout = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_path_display)
        button_layout.addWidget(refresh_button)
        button_layout.addStretch()

        layout.addLayout(button_layout)
        widget.setLayout(layout)
        return widget

    def create_collection_widget(self) -> QWidget:
        """Create collection and progress tab."""
        widget = QWidget()
        layout = QVBoxLayout()

        # Status
        status_layout = QHBoxLayout()
        self.admin_status = QLabel(PathValidator.get_admin_status_string())
        self.admin_status.setStyleSheet("color: #E0E0E0; padding: 10px; font-weight: bold;")
        status_layout.addWidget(self.admin_status)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # Collection button
        self.collect_button = QPushButton("Start Collection")
        self.collect_button.setMinimumHeight(50)
        self.collect_button.setStyleSheet(
            "QPushButton { background-color: #10B981; color: #000000; font-size: 16px; font-weight: 900; border: 2px solid #059669; border-radius: 6px; padding: 10px; } "
            "QPushButton:hover { background-color: #059669; color: #FFFFFF; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; border: 2px solid #0F172A; }"
        )
        self.collect_button.clicked.connect(self.start_collection)
        layout.addWidget(self.collect_button)

        # Progress bar with text display
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p% - Waiting to start...")  # Show percentage and custom text
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignCenter)
        self.progress.setMinimumHeight(30)
        self.progress.setStyleSheet(
            "QProgressBar { "
            "background-color: #1E293B; "
            "border: 2px solid #00FFFF; "
            "border-radius: 6px; "
            "text-align: center; "
            "color: #FFFFFF; "
            "font-weight: bold; "
            "font-size: 12px; "
            "padding: 2px; "
            "} "
            "QProgressBar::chunk { "
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00FF88, stop:1 #00FFFF); "
            "border-radius: 4px; "
            "}"
        )
        layout.addWidget(self.progress)

        # Current item being collected + Access Method on same line
        status_row_layout = QHBoxLayout()
        status_row_layout.setSpacing(20)
        
        # Left side: Current Collection Progress
        current_section = QVBoxLayout()
        current_section.setSpacing(5)
        current_label = QLabel("Current Collection Progress:")
        current_label.setStyleSheet("color: #00FF88; font-weight: bold;")
        current_section.addWidget(current_label)
        
        self.current_item = QLabel("(Waiting to start)")
        self.current_item.setStyleSheet("color: #E0E0E0; padding: 5px; background-color: #1E293B; border: 1px solid #334155; border-radius: 4px;")
        current_section.addWidget(self.current_item)
        
        # Right side: Access Method
        access_section = QVBoxLayout()
        access_section.setSpacing(5)
        access_method_label = QLabel("Access Method:")
        access_method_label.setStyleSheet("color: #00FFFF; font-weight: bold;")
        access_section.addWidget(access_method_label)
        
        self.access_method_display = QLabel("(Not started)")
        self.access_method_display.setStyleSheet("color: #E0E0E0; padding: 5px; background-color: #1E293B; border: 1px solid #334155; border-radius: 4px;")
        access_section.addWidget(self.access_method_display)
        
        # Add both sections to horizontal layout
        status_row_layout.addLayout(current_section, 1)  # Give more space to current progress
        status_row_layout.addLayout(access_section, 1)   # Equal space for access method
        
        layout.addLayout(status_row_layout)

        # Status log
        log_label = QLabel("Collection Log:")
        log_label.setStyleSheet("color: #00FFFF; font-weight: bold; padding: 10px 0px;")
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "background-color: #1E293B; color: #E0E0E0; border: 1px solid #00FFFF; border-radius: 4px;"
        )
        layout.addWidget(self.log_text)

        # Buttons
        button_layout = QHBoxLayout()
        open_button = QPushButton("Open Output Folder")
        open_button.clicked.connect(self.open_output_folder)
        open_button.setStyleSheet(
            "QPushButton { background-color: #1E293B; color: #FFFFFF; border: 2px solid #00FFFF; border-radius: 4px; padding: 8px; font-weight: 900; font-size: 11px; } "
            "QPushButton:hover { background-color: #334155; color: #00FF88; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; }"
        )
        manifest_button = QPushButton("View Manifest")
        manifest_button.clicked.connect(self.view_manifest)
        manifest_button.setStyleSheet(
            "QPushButton { background-color: #1E293B; color: #FFFFFF; border: 2px solid #00FFFF; border-radius: 4px; padding: 8px; font-weight: 900; font-size: 11px; } "
            "QPushButton:hover { background-color: #334155; color: #00FF88; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; }"
        )
        button_layout.addWidget(open_button)
        button_layout.addWidget(manifest_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        widget.setLayout(layout)
        return widget


    def on_artifact_selected(self):
        """Handle artifact selection from list."""
        items = self.artifact_list.selectedItems()
        if items:
            self.selected_artifact = items[0].data(Qt.UserRole)
            self.update_detail_display()
            self.enable_checkbox.setChecked(self.selected_artifact.enabled)

    def update_detail_display(self):
        """Update detail text display for selected artifact with expanded paths."""
        if not self.selected_artifact:
            self.detail_text.clear()
            return

        artifact = self.selected_artifact
        
        # Build admin requirement warning if needed
        admin_warning = ""
        if artifact.required_admin:
            admin_warning = '<div style="background-color: #2D1F0F; border: 3px solid #FFAA00; border-radius: 6px; padding: 12px; margin: 12px 0;">'
            admin_warning += '<p style="margin: 0; font-size: 11pt;"><b style="color: #FFAA00; font-size: 12pt;">⚠ ADMINISTRATOR PRIVILEGES REQUIRED</b></p>'
            admin_warning += '<p style="margin: 5px 0 0 0; color: #FFD700; font-size: 10pt;">This artifact requires administrator privileges to collect successfully.</p>'
            admin_warning += '</div>'
        
        details = f"""
<div style="font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6;">
<p style="margin: 0 0 15px 0;"><b style="color: #3B82F6; font-size: 14pt;">{artifact.name.upper()}</b></p>

{admin_warning}

<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
<tr><td style="color: #94A3B8; font-weight: bold; padding: 4px 0; width: 150px;">Type:</td><td style="color: #E2E8F0;">{artifact.artifact_type.value}</td></tr>
<tr><td style="color: #94A3B8; font-weight: bold; padding: 4px 0;">Required Admin:</td><td style="color: {'#EF4444' if artifact.required_admin else '#10B981'}; font-weight: bold;">{'⚠ Yes' if artifact.required_admin else '✓ No'}</td></tr>
<tr><td style="color: #94A3B8; font-weight: bold; padding: 4px 0;">Status:</td><td style="color: {'#10B981' if artifact.enabled else '#EF4444'}; font-weight: bold;">{'✓ Enabled' if artifact.enabled else '✗ Disabled'}</td></tr>
</table>

<div style="margin: 15px 0; padding: 10px; background-color: #1E293B; border-left: 4px solid #3B82F6; border-radius: 4px;">
<p style="margin: 0; color: #3B82F6; font-weight: bold; font-size: 11pt;">DESCRIPTION</p>
<p style="margin: 8px 0 0 0; color: #E2E8F0; font-size: 10pt;">{artifact.description}</p>
</div>

<div style="margin: 15px 0;">
<p style="margin: 0 0 8px 0; color: #3B82F6; font-weight: bold; font-size: 11pt;">DEFAULT PATHS <span style="color: #10B981; font-size: 9pt;">(Partition: {self.windows_partition})</span></p>
<div style="background-color: #0F172A; padding: 10px; border-radius: 4px; border: 1px solid #334155;">
"""
        # Show expanded paths with actual partition letter
        for idx, path in enumerate(artifact.default_paths, 1):
            expanded_path = path.replace("{PARTITION}", self.windows_partition)
            details += f'<p style="margin: 3px 0; color: #10B981; font-family: Consolas; font-size: 9pt;">  {idx}. <span style="color: #E2E8F0;">{expanded_path}</span></p>'

        details += "</div></div>"

        if artifact.custom_paths:
            details += """
<div style="margin: 15px 0;">
<p style="margin: 0 0 8px 0; color: #8B5CF6; font-weight: bold; font-size: 11pt;">CUSTOM PATHS</p>
<div style="background-color: #0F172A; padding: 10px; border-radius: 4px; border: 1px solid #334155;">
"""
            for idx, path in enumerate(artifact.custom_paths, 1):
                expanded_path = path.replace("{PARTITION}", self.windows_partition)
                details += f'<p style="margin: 3px 0; color: #8B5CF6; font-family: Consolas; font-size: 9pt;">  {idx}. <span style="color: #E2E8F0;">{expanded_path}</span></p>'
            details += "</div></div>"

        # Add info about wildcard expansion
        details += """
<div style="margin: 15px 0; padding: 10px; background-color: #1A2B1A; border-left: 4px solid #00FF88; border-radius: 4px;">
<p style="margin: 0; color: #00FF88; font-weight: bold; font-size: 10pt;">💡 WILDCARD INFO</p>
<p style="margin: 5px 0 0 0; color: #E0E0E0; font-size: 9pt;">• Paths with <b style="color: #FFD700;">*</b> will expand to match multiple files</p>
<p style="margin: 3px 0 0 0; color: #E0E0E0; font-size: 9pt;">• <span style="color: #00FFFF;">Users\\*\\NTUSER.DAT</span> will find all user profiles</p>
<p style="margin: 3px 0 0 0; color: #E0E0E0; font-size: 9pt;">• <span style="color: #00FFFF;">$Recycle.Bin\\S-1-5-*</span> will find all user SIDs</p>
</div>

</div>
"""

        self.detail_text.setHtml(details)

    def on_enable_toggled(self):
        """Handle enable/disable toggle and refresh path display."""
        if self.selected_artifact:
            self.selected_artifact.enabled = self.enable_checkbox.isChecked()
            # Refresh path display to show updated collection list
            self.refresh_path_display()

    def refresh_path_display(self):
        """Refresh path display showing actual paths that will be collected."""
        is_admin = PathValidator.is_admin()
        
        # Enhanced header with better styling
        text = f"""
<div style="background-color: #0F172A; padding: 10px; margin-bottom: 10px;">
    <p style="margin: 0; font-size: 12pt; font-weight: bold; color: #00FFFF; letter-spacing: 2px;">
        PATHS TO BE COLLECTED
    </p>
    <p style="margin: 5px 0 0 0; font-size: 9pt; color: #00FF88;">
        <b>Windows Partition:</b> <span style="color: #FFFFFF; background-color: #1E293B; padding: 2px 8px; border-radius: 3px; font-family: Consolas;">{self.windows_partition}</span>
    </p>
    <p style="margin: 5px 0 0 0; font-size: 9pt; color: {'#00FF88' if is_admin else '#FF6B6B'};">
        <b>Admin Status:</b> <span style="color: {'#00FF88' if is_admin else '#FF6B6B'}; background-color: #1E293B; padding: 2px 8px; border-radius: 3px; font-family: Consolas;">{'✓ Administrator' if is_admin else '⚠ Standard User'}</span>
    </p>
</div>

<div style="border-top: 2px solid #00FFFF; margin: 10px 0;"></div>

"""

        total_artifacts = len([a for a in self.artifacts if a.enabled])
        enabled_count = 0
        admin_required_count = 0

        for artifact in self.artifacts:
            if artifact.enabled:
                enabled_count += 1
                
                # Add admin indicator if required
                admin_indicator = ""
                if artifact.required_admin:
                    admin_required_count += 1
                    if is_admin:
                        admin_indicator = ' <span style="background-color: #3B2F1F; color: #FFAA00; padding: 2px 6px; border-radius: 3px; font-size: 8pt; font-weight: bold;">🔒 ADMIN REQUIRED</span>'
                    else:
                        admin_indicator = ' <span style="background-color: #3B1F1F; color: #FF6B6B; padding: 2px 6px; border-radius: 3px; font-size: 8pt; font-weight: bold;">⚠ ADMIN REQUIRED</span>'
                
                # Artifact header with box styling
                text += f"""
<div style="background-color: #1E293B; border-left: 4px solid #00FFFF; padding: 8px; margin: 8px 0; border-radius: 4px;">
    <p style="margin: 0; font-size: 10pt; font-weight: bold; color: #00FFFF;">
        [{enabled_count}/{total_artifacts}] {artifact.name}{admin_indicator}
    </p>
"""

                # Expand default paths with actual partition
                text += '<p style="margin: 8px 0 4px 0; font-size: 9pt; font-weight: bold; color: #00FF88;">📁 Default Paths:</p>'
                for path in artifact.default_paths:
                    expanded_path = path.replace("{PARTITION}", self.windows_partition)
                    text += f'<p style="margin: 2px 0 2px 20px; font-size: 9pt; color: #E0E0E0; font-family: Consolas;"><span style="color: #00FFFF;">→</span> <span style="background-color: #0F172A; padding: 2px 6px; border-radius: 2px;">{expanded_path}</span></p>'

                # Show custom paths if any
                if artifact.custom_paths:
                    text += '<p style="margin: 8px 0 4px 0; font-size: 9pt; font-weight: bold; color: #FFAA00;">✏️ Custom Paths:</p>'
                    for path in artifact.custom_paths:
                        expanded_path = path.replace("{PARTITION}", self.windows_partition)
                        text += f'<p style="margin: 2px 0 2px 20px; font-size: 9pt; color: #E0E0E0; font-family: Consolas;"><span style="color: #FFAA00;">→</span> <span style="background-color: #0F172A; padding: 2px 6px; border-radius: 2px;">{expanded_path}</span></p>'

                text += "</div>\n"

        # Add summary with enhanced styling
        text += f"""
<div style="border-top: 2px solid #00FFFF; margin: 15px 0 10px 0;"></div>

<div style="background-color: #1E293B; padding: 10px; border-radius: 4px; border: 2px solid #00FFFF;">
    <p style="margin: 0 0 8px 0; font-size: 11pt; font-weight: bold; color: #00FFFF; letter-spacing: 1px;">
        📊 SUMMARY
    </p>
    <table style="width: 100%; font-size: 9pt; color: #E0E0E0;">
        <tr>
            <td style="padding: 3px 0; color: #00FF88;"><b>Enabled artifacts:</b></td>
            <td style="padding: 3px 0; text-align: right; font-family: Consolas; color: #FFFFFF;">{enabled_count}/{len(self.artifacts)}</td>
        </tr>
        <tr>
            <td style="padding: 3px 0; color: #FFAA00;"><b>Admin-required artifacts:</b></td>
            <td style="padding: 3px 0; text-align: right; font-family: Consolas; color: #FFFFFF;">{admin_required_count}</td>
        </tr>
        <tr>
            <td style="padding: 3px 0; color: #FF00FF;"><b>Windows partition:</b></td>
            <td style="padding: 3px 0; text-align: right; font-family: Consolas; color: #FFFFFF;">{self.windows_partition}</td>
        </tr>
        <tr>
            <td style="padding: 3px 0; color: #00FFFF;"><b>Collection ready:</b></td>
            <td style="padding: 3px 0; text-align: right; font-family: Consolas; color: {'#00FF88' if enabled_count > 0 else '#FF6B6B'}; font-weight: bold;">{'✓ Yes' if enabled_count > 0 else '✗ No'}</td>
        </tr>
    </table>
</div>
"""

        if admin_required_count > 0 and not is_admin:
            text += f"""
<div style="background-color: #3B1F1F; border: 2px solid #FF6B6B; border-radius: 4px; padding: 12px; margin: 10px 0;">
    <p style="margin: 0 0 5px 0; font-size: 10pt; font-weight: bold; color: #FF6B6B;">
        ⚠ WARNING: Not running as Administrator
    </p>
    <p style="margin: 0; font-size: 9pt; color: #E0E0E0;">
        {admin_required_count} artifact(s) require admin privileges and may fail to collect.
    </p>
</div>
"""

        text += """
<div style="background-color: #1E293B; border-left: 4px solid #00FF88; padding: 8px; margin: 10px 0; border-radius: 4px;">
    <p style="margin: 0; font-size: 9pt; color: #00FF88;">
        <b>💡 Note:</b> <span style="color: #E0E0E0;">Paths with wildcards (* or S-1-5-*) will expand to match multiple files during collection.</span>
    </p>
</div>
"""

        self.path_text.setHtml(text)

    def add_custom_path(self):
        """Add custom path to selected artifact."""
        if not self.selected_artifact:
            self.show_styled_message("⚠ No Artifact", "Please select an artifact first", "warning")
            return

        path, ok = self.select_file_or_directory()
        if ok and path:
            self.selected_artifact.add_custom_path(path)
            self.update_detail_display()
            self.refresh_path_display()
            self.show_styled_message("✓ Success", f"Added custom path:\n\n{path}", "success")

    def select_output_directory(self):
        """Select output directory for collection."""
        print("\n=== select_output_directory CALLED ===")

        import os

        # Get default path
        default_path = os.path.expanduser("~\\Desktop")
        print(f"Default path: {default_path}")

        # Show file dialog
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            default_path
        )

        if output_dir:
            print(f"Selected: {output_dir}")

            # Store in header panel
            self.header.set_output_path(output_dir)

            # Also store in main window for compatibility
            self.full_output_path = output_dir
            print(f"Stored full_output_path = {self.full_output_path}")

            # Show custom styled dialog
            self.show_styled_message(
                "✓ Directory Selected",
                f"Output path set successfully:\n\n{output_dir}",
                "success"
            )
        else:
            print("No directory selected")

    def show_styled_message(self, title: str, message: str, msg_type: str = "info"):
        """Show a custom styled message dialog matching Crow-Claw theme.
        
        Args:
            title: Dialog title
            message: Message text
            msg_type: Type of message - "success", "error", "warning", "info"
        """
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(500)
        dialog.setModal(True)
        
        # Set dialog background
        dialog.setStyleSheet("QDialog { background-color: #0F172A; }")
        
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Icon and title based on type
        icon_map = {
            "success": "✓",
            "error": "✗",
            "warning": "⚠",
            "info": "ℹ"
        }
        color_map = {
            "success": "#00FF88",
            "error": "#FF6B6B",
            "warning": "#FFAA00",
            "info": "#00FFFF"
        }
        
        icon = icon_map.get(msg_type, "ℹ")
        color = color_map.get(msg_type, "#00FFFF")
        
        # Title with icon
        title_label = QLabel(f"{icon} {title}")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_font.setFamily("Consolas")
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {color}; background-color: transparent; letter-spacing: 2px;")
        layout.addWidget(title_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background-color: {color}; border: none; height: 2px;")
        layout.addWidget(separator)
        
        # Message text
        msg_label = QLabel(message)
        msg_font = QFont()
        msg_font.setPointSize(10)
        msg_font.setFamily("Consolas")
        msg_label.setFont(msg_font)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("color: #E0E0E0; background-color: #1E293B; padding: 15px; border-radius: 4px; border: 1px solid #334155;")
        layout.addWidget(msg_label)
        
        # OK button
        ok_button = QPushButton("OK")
        ok_button_font = QFont()
        ok_button_font.setPointSize(11)
        ok_button_font.setBold(True)
        ok_button.setFont(ok_button_font)
        ok_button.setMinimumHeight(40)
        ok_button.setStyleSheet(
            f"QPushButton {{ "
            f"background-color: #1E293B; "
            f"color: {color}; "
            f"border: 2px solid {color}; "
            f"border-radius: 4px; "
            f"padding: 8px 20px; "
            f"font-weight: 900; "
            f"letter-spacing: 2px; "
            f"}} "
            f"QPushButton:hover {{ "
            f"background-color: {color}; "
            f"color: #0F172A; "
            f"}} "
            f"QPushButton:pressed {{ "
            f"background-color: #00FFFF; "
            f"color: #0F172A; "
            f"}}"
        )
        ok_button.clicked.connect(dialog.accept)
        layout.addWidget(ok_button)
        
        dialog.setLayout(layout)
        dialog.exec_()

    def select_file_or_directory(self) -> tuple:
        """Let user select file or directory."""
        path = QFileDialog.getExistingDirectory(self, "Select Path")
        return path, bool(path)

    def detect_windows_partition(self) -> str:
        """
        Detect the active Windows partition.

        Uses the WindowsPartitionDetector to automatically detect which partition
        contains the Windows installation. Returns "C:" as fallback.

        Returns:
            str: Windows partition letter (e.g., "C:")
        """
        if WindowsPartitionDetector is None:
            print("[WARNING] WindowsPartitionDetector not available, defaulting to C:")
            return "C:"

        try:
            detector = WindowsPartitionDetector()
            partition = detector.detect_live_system()
            print(f"[OK] Windows partition detected: {partition}")
            return partition
        except Exception as e:
            print(f"[WARNING] Error detecting Windows partition: {e}")
            print(f"[INFO] Falling back to default partition: C:")
            return "C:"

    def check_admin_status(self):
        """Check and display admin status."""
        is_admin = PathValidator.is_admin()
        
        # Update header admin status indicator
        self.header.set_admin_status(is_admin)
        
        # Update collection widget status if it exists
        if hasattr(self, 'admin_status'):
            status = PathValidator.get_admin_status_string()
            self.admin_status.setText(status)

    def start_collection(self):
        """Start artifact collection process using worker thread to prevent freezing."""
        from datetime import datetime

        # Get output path from header
        output_path = self.header.get_output_path()

        if not self.full_output_path and not self.integrated_mode:
            self.show_styled_message("⚠ No Output Directory", "Please select an output directory before starting the collection.", "warning")
            return
            
        # In integrated mode, the output path is derived from the case directory
        if self.integrated_mode and not self.full_output_path:
            if self.case_directory:
                self.full_output_path = self.case_directory
                print(f"[INFO] Setting full_output_path for integrated mode: {self.full_output_path}")
            else:
                self.show_styled_message("⚠ Configuration Error", "Running in integrated mode but no case directory is set.", "error")
                return

        # Check admin status and show warning if not admin
        is_admin = PathValidator.is_admin()
        if not is_admin:
            # Get list of enabled admin-required artifacts
            admin_required_artifacts = [
                artifact.name for artifact in self.artifacts 
                if artifact.enabled and artifact.required_admin
            ]
            
            if admin_required_artifacts:
                warning_msg = "⚠ Running without Administrator Privileges\n\n"
                warning_msg += "The following artifacts require administrator privileges and may fail to collect:\n\n"
                for artifact_name in admin_required_artifacts:
                    warning_msg += f"  • {artifact_name}\n"
                warning_msg += "\nTo collect these artifacts, please restart the application as Administrator.\n\n"
                warning_msg += "Do you want to continue anyway?"
                
                reply = QMessageBox.question(
                    self,
                    "Administrator Privileges Required",
                    warning_msg,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                
                if reply == QMessageBox.No:
                    return

        # Reset progress
        self.progress.setValue(0)
        self.progress.setFormat("0% - Initializing collection...")
        self.log_text.clear()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"Collection started at {timestamp}")
        self.log_text.append(f"Windows Partition: {self.windows_partition}")
        self.log_text.append(f"Output Directory: {self.full_output_path}")
        self.log_text.append(f"Admin Status: {'Administrator' if is_admin else 'Standard User'}\n")
        
        # Initialize access method display
        self.access_method_display.setText("(Initializing...)")
        
        # Update button to show collection in progress
        self.collect_button.setText("⏳ Collecting...")
        self.collect_button.setEnabled(False)
        self.collect_button.setStyleSheet(
            "QPushButton { background-color: #FFAA00; color: #000000; font-size: 16px; font-weight: 900; border: 2px solid #FF8800; border-radius: 6px; padding: 10px; } "
        )

        # Track current artifact for progress display
        self.current_artifact_name = ""
        self.total_artifacts = len([a for a in self.artifacts if a.enabled])
        self.current_artifact_index = 0

        # Create and configure worker thread with admin status from main thread
        self.worker = CollectionWorker(
            artifacts=self.artifacts,
            output_directory=self.full_output_path,
            windows_partition=self.windows_partition,
            is_admin=is_admin
        )
        
        # Connect signals to slots
        self.worker.log_signal.connect(self.on_log_message)
        self.worker.progress_signal.connect(self.on_progress_update)
        self.worker.status_signal.connect(self.on_status_update)
        self.worker.finished_signal.connect(self.on_collection_finished)
        self.worker.error_signal.connect(self.on_collection_error)
        
        # Start worker thread
        self.worker.start()

    def on_log_message(self, message: str):
        """Handle log messages from worker thread with color coding for VSS errors."""
        # Check for VSS-related error messages and format them in RED
        if any(keyword in message for keyword in ["[VSS]", "Shadow copy", "VSS service", "vssadmin"]):
            if any(error_keyword in message.lower() for error_keyword in ["fail", "error", "cannot", "unable", "not found", "not running", "denied"]):
                # Format VSS errors in bright RED with bold text
                formatted_message = f'<span style="color: #FF3333; font-weight: bold; background-color: #3D0000; padding: 2px 4px; border-radius: 2px;">{message}</span>'
                self.log_text.append(formatted_message)
                return
        
        # Regular message handling
        self.log_text.append(message)
        
        # Extract artifact name from log messages for progress bar
        if message.startswith("Collecting: "):
            parts = message.split("Collecting: ")
            if len(parts) > 1:
                artifact_info = parts[1].split(" (")
                if len(artifact_info) > 0:
                    self.current_artifact_name = artifact_info[0]
                    # Extract index if available
                    if len(artifact_info) > 1:
                        try:
                            idx_part = artifact_info[1].split("/")[0]
                            self.current_artifact_index = int(idx_part)
                        except:
                            pass
        
        # Extract file count information from log messages
        # Pattern: "✓ ArtifactName: X files (size) via method"
        if "files (" in message and "via" in message:
            try:
                # Extract file count
                parts = message.split(" files (")
                if len(parts) > 1:
                    # Get the number before " files"
                    count_part = parts[0].split(":")[-1].strip()
                    if count_part.isdigit():
                        file_count = int(count_part)
                        # Update current item display with file count
                        if self.current_artifact_name:
                            self.current_item.setText(f"[{self.current_artifact_index}/{self.total_artifacts}] {self.current_artifact_name}: {file_count} files collected")
            except:
                pass

    def on_progress_update(self, percent: int):
        """Handle progress updates from worker thread."""
        self.progress.setValue(percent)
        
        # Update progress bar text with current artifact info
        if self.current_artifact_name:
            if self.total_artifacts > 0:
                self.progress.setFormat(
                    f"%p% - Collecting: {self.current_artifact_name} ({self.current_artifact_index}/{self.total_artifacts})"
                )
            else:
                self.progress.setFormat(f"%p% - Collecting: {self.current_artifact_name}")
        elif percent == 0:
            self.progress.setFormat("%p% - Initializing collection...")
        elif percent == 100:
            self.progress.setFormat("%p% - Collection Complete!")
        else:
            self.progress.setFormat(f"%p% - Processing...")

    def on_status_update(self, message: str):
        """Handle status updates from worker thread."""
        # Parse and enhance status message display
        display_message = message
        
        # Check if this is an error message - also log it
        if message.startswith("✗"):
            self.log_text.append(f"[ERROR] {message}")
        
        # Check for real-time file collection progress
        # Pattern: "[X/Y] ArtifactName: Collecting filename..." or "[X/Y] ArtifactName: Collected N files so far..."
        if message.startswith("[") and "/" in message and "]" in message:
            try:
                # Extract file progress [X/Y]
                bracket_content = message.split("]")[0].replace("[", "")
                current_file, total_files = bracket_content.split("/")
                
                # This is a multi-file collection progress message
                display_message = message  # Use as-is, it's already well formatted
                
                # Extract artifact name if available
                if ":" in message:
                    artifact_part = message.split(":")[0].split("]")[1].strip()
                    self.current_artifact_name = artifact_part
            except:
                pass
        
        # Check if this is a collection complete message with file counts
        # Pattern: "✓ ArtifactName: X files (size) via method"
        elif "✓" in message and " files (" in message:
            try:
                # Extract artifact name and file count
                parts = message.split(":")
                if len(parts) >= 2:
                    artifact_part = parts[0].replace("✓", "").strip()
                    info_part = parts[1].strip()
                    
                    # Extract file count
                    file_count_str = info_part.split(" files")[0].strip()
                    if file_count_str.isdigit():
                        file_count = int(file_count_str)
                        
                        # Extract size if available
                        size_match = info_part.split("(")[1].split(")")[0] if "(" in info_part else ""
                        
                        # Create enhanced display message
                        display_message = f"✓ {artifact_part}: Collected {file_count} files ({size_match})"
                        
                        # Also log successful collections
                        self.log_text.append(f"[OK] {display_message}")
            except:
                pass
        
        # Check if this is a collecting message
        elif "Collecting" in message:
            # Extract artifact name from status message
            if "Collecting: " in message:
                artifact_name = message.split("Collecting: ")[1].split(" (")[0] if "(" in message else message.split("Collecting: ")[1]
                self.current_artifact_name = artifact_name
                
                # Show artifact index if available
                if self.current_artifact_index > 0 and self.total_artifacts > 0:
                    display_message = f"[{self.current_artifact_index}/{self.total_artifacts}] Collecting: {artifact_name}..."
                
                self.on_progress_update(self.progress.value())  # Refresh progress text
        
        self.current_item.setText(display_message)
        
        # Update access method statistics display in real-time
        self._update_access_method_display()

    def on_collection_finished(self, success: bool, statistics):
        """Handle collection completion from worker thread."""
        from datetime import datetime
        
        # Collection complete
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_item.setText("Collection complete!")
        self._update_access_method_display(finished=True)
        self.log_text.append(f"\n[OK] Collection finished at {end_time}")
        self.log_text.append(f"[*] Total artifacts collected: {statistics.total_artifacts_collected}/{statistics.total_artifacts_requested}")
        self.log_text.append(f"[*] Total files collected: {statistics.total_files_collected}")
        self.log_text.append(f"[*] Total bytes collected: {self._format_size(statistics.total_bytes_collected)}")
        
        if statistics.total_errors > 0:
            self.log_text.append(f"[WARNING] Errors occurred: {statistics.total_errors}")
        if statistics.total_skipped > 0:
            self.log_text.append(f"[INFO] Artifacts skipped: {statistics.total_skipped}")
        
        # Display access method statistics
        if hasattr(self.worker.collector, 'access_method_stats') and self.worker.collector.access_method_stats:
            self.log_text.append(f"\n=== Access Method Statistics ===")
            for method, count in self.worker.collector.access_method_stats.items():
                if count > 0:
                    method_display = self._format_access_method(method)
                    self.log_text.append(f"  {method_display}: {count} artifacts")
        
        # Display detailed per-artifact results
        self.log_text.append(f"\n{'='*60}")
        self.log_text.append(f"=== DETAILED COLLECTION RESULTS ===")
        self.log_text.append(f"{'='*60}")
        for result in self.worker.collector.collection_results:
            # Determine status
            if result.status.value == "success":
                status_icon = "✓"
                status_text = "COLLECTED SUCCESSFULLY"
            elif result.status.value == "skipped":
                status_icon = "⊘"
                status_text = "SKIPPED"
            else:
                status_icon = "✗"
                status_text = "FAILED"
            
            size_str = self._format_size(result.bytes_collected)
            self.log_text.append(f"\n{status_icon} {result.artifact_name}: {status_text}")
            self.log_text.append(f"    Files Collected: {result.files_collected}")
            self.log_text.append(f"    Total Size: {size_str}")
            
            # Show errors if any
            if result.errors:
                self.log_text.append(f"    Errors ({len(result.errors)}):")
                for error in result.errors:
                    self.log_text.append(f"      • {error}")
        
        self.log_text.append(f"{'='*60}\n")
        
        self.progress.setValue(100)
        self.progress.setFormat(f"100% - Complete! Collected {statistics.total_files_collected} files from {statistics.total_artifacts_collected} artifacts")
        
        # Reset button to original state
        self.collect_button.setText("Start Collection")
        self.collect_button.setEnabled(True)
        self.collect_button.setStyleSheet(
            "QPushButton { background-color: #10B981; color: #000000; font-size: 16px; font-weight: 900; border: 2px solid #059669; border-radius: 6px; padding: 10px; } "
            "QPushButton:hover { background-color: #059669; color: #FFFFFF; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; border: 2px solid #0F172A; }"
        )

        # Generate collection manifest using the collector's results
        self.generate_collection_manifest_from_collector(self.worker.collector, statistics, end_time)
        
        # Save artifact paths to case configuration for offline parsers
        if self.integrated_mode and self.case_directory:
            self.save_artifact_paths_to_case_config(self.worker.collector)

        self.collection_started.emit()
        
        # Show completion dialog with statistics
        self.show_completion_dialog_from_collector(self.worker.collector, statistics)

    def on_collection_error(self, error_message: str):
        """Handle collection errors from worker thread."""
        self.log_text.append(f"\n[ERROR] Collection failed: {error_message}")
        self.current_item.setText("Collection failed!")
        self.access_method_display.setText("✗ Error occurred")
        
        # Reset button
        self.collect_button.setText("Start Collection")
        self.collect_button.setEnabled(True)
        self.collect_button.setStyleSheet(
            "QPushButton { background-color: #10B981; color: #000000; font-size: 16px; font-weight: 900; border: 2px solid #059669; border-radius: 6px; padding: 10px; } "
            "QPushButton:hover { background-color: #059669; color: #FFFFFF; } "
            "QPushButton:pressed { background-color: #00FFFF; color: #0F172A; border: 2px solid #0F172A; }"
        )
        
        self.show_styled_message("✗ Collection Error", f"An error occurred during collection:\n\n{error_message}", "error")

    def generate_collection_manifest_from_collector(self, collector, statistics, end_time: str):
        """Generate a collection manifest from collector results.

        Args:
            collector: ArtifactCollector instance
            statistics: CollectionStatistics object
            end_time: End time of collection (formatted string)
        """
        import json
        from datetime import datetime

        # Create manifest data
        manifest = {
            "collection_info": {
                "mode": "integrated" if self.integrated_mode else "standalone",
                "timestamp": datetime.now().isoformat(),
                "end_time": end_time,
            },
            "collection_status": {
                "artifacts_requested": statistics.total_artifacts_requested,
                "artifacts_collected": statistics.total_artifacts_collected,
                "files_collected": statistics.total_files_collected,
                "bytes_collected": statistics.total_bytes_collected,
                "errors": statistics.total_errors,
                "skipped": statistics.total_skipped,
                "success": statistics.get_status()
            },
            "paths": {
                "windows_partition": self.windows_partition,
                "output_directory": self.full_output_path
            },
            "access_method_statistics": collector.access_method_stats if hasattr(collector, 'access_method_stats') else {}
        }

        # Add integrated mode specific info
        if self.integrated_mode:
            manifest["integrated_mode"] = {
                "case_directory": self.case_directory,
                "target_artifact_dir": self.full_output_path,
                "artifacts_structure": "Each artifact type has its own subdirectory"
            }

        # Add collected artifacts details
        collected_artifacts = []
        for result in collector.collection_results:
            collected_artifacts.append({
                "name": result.artifact_name,
                "type": result.artifact_type,
                "status": result.status.value,
                "files_collected": result.files_collected,
                "bytes_collected": result.bytes_collected,
                "output_directory": result.dest_path,
                "errors": result.errors
            })
        manifest["artifacts"] = collected_artifacts

        # Save manifest as JSON
        manifest_path = os.path.join(self.full_output_path, "collection_manifest.json")
        try:
            os.makedirs(self.full_output_path, exist_ok=True)
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            self.log_text.append(f"\n[OK] Manifest saved to: {manifest_path}")
            print(f"[INFO] Collection manifest created: {manifest_path}")
        except Exception as e:
            self.log_text.append(f"\n[WARNING] Could not save manifest: {str(e)}")
            print(f"[WARNING] Error saving manifest: {e}")
    
    def save_artifact_paths_to_case_config(self, collector):
        """Save collected artifact paths to case configuration for offline parsers.
        
        This method updates the case_config.json file with artifact paths so that
        offline parsers can directly access the collected artifacts without manual browsing.
        
        Args:
            collector: ArtifactCollector instance with collection_results
        """
        import json
        from datetime import datetime
        from pathlib import Path
        
        try:
            # Build artifact paths dictionary
            artifact_paths = {}
            for result in collector.collection_results:
                if result.status.value == "success" and result.dest_path:
                    # Use artifact type as key
                    artifact_type = result.artifact_type
                    artifact_paths[artifact_type] = result.dest_path
            
            # Get case config path
            case_config_path = os.path.join(self.case_directory, "case_config.json")
            
            # Load existing config or create new one
            if os.path.exists(case_config_path):
                with open(case_config_path, 'r') as f:
                    case_config = json.load(f)
            else:
                case_config = {
                    "case_id": os.path.basename(self.case_directory),
                    "created_at": datetime.now().isoformat()
                }
            
            # Update with artifact paths
            case_config["artifact_paths"] = artifact_paths
            case_config["live_acquisition_path"] = self.full_output_path
            case_config["modified_at"] = datetime.now().isoformat()
            
            # Save updated config
            with open(case_config_path, 'w') as f:
                json.dump(case_config, f, indent=2)
            
            self.log_text.append(f"\n[OK] Artifact paths saved to case configuration")
            self.log_text.append(f"[INFO] Offline parsers can now directly access collected artifacts")
            print(f"[INFO] Saved artifact paths to: {case_config_path}")
            print(f"[INFO] Artifact types saved: {list(artifact_paths.keys())}")
            
        except Exception as e:
            self.log_text.append(f"\n[WARNING] Could not save artifact paths to case config: {str(e)}")
            print(f"[WARNING] Error saving artifact paths: {e}")
            import traceback
            traceback.print_exc()

    def show_completion_dialog_from_collector(self, collector, statistics):
        """Show completion dialog with statistics from collector.
        
        Args:
            collector: ArtifactCollector instance
            statistics: CollectionStatistics object
        """
        # Build summary message - Enhanced compact dialog
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QFrame
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont
        
        # Create custom dialog with dark theme
        dialog = QDialog(self)
        dialog.setWindowTitle("Collection Complete")
        dialog.setMinimumWidth(700)
        dialog.setMaximumWidth(900)
        
        # Apply dark theme to dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #FFFFFF;
            }
            QLabel {
                color: #FFFFFF;
            }
        """)
        
        # Main layout
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header with icon and title
        header_layout = QHBoxLayout()
        
        # Success/Warning icon with dark background
        icon_label = QLabel("✓" if statistics.total_errors == 0 else "⚠")
        icon_font = QFont()
        icon_font.setPointSize(36)
        icon_font.setBold(True)
        icon_label.setFont(icon_font)
        icon_label.setStyleSheet(f"""
            color: {'#10B981' if statistics.total_errors == 0 else '#F59E0B'}; 
            background-color: {'#064E3B' if statistics.total_errors == 0 else '#78350F'};
            padding: 16px;
            border-radius: 8px;
            min-width: 60px;
            max-width: 60px;
            min-height: 60px;
            max-height: 60px;
        """)
        icon_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(icon_label)
        
        # Title
        title_label = QLabel("Collection Complete!")
        title_font = QFont("Segoe UI", 18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #FFFFFF; padding-left: 12px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Summary section (dark theme)
        summary_frame = QFrame()
        summary_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        summary_frame.setStyleSheet("""
            QFrame { 
                background-color: #1E293B; 
                border: 1px solid #334155; 
                border-radius: 6px; 
                padding: 14px; 
            }
        """)
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setSpacing(8)
        
        # Summary title
        summary_title = QLabel("SUMMARY")
        summary_title_font = QFont("Segoe UI", 10)
        summary_title_font.setBold(True)
        summary_title.setFont(summary_title_font)
        summary_title.setStyleSheet("color: #94A3B8; letter-spacing: 1px;")
        summary_layout.addWidget(summary_title)
        
        # Summary stats in compact format with dark theme
        summary_text = f"<table style='width: 100%; font-size: 11pt; color: #E2E8F0;'>"
        summary_text += f"<tr><td style='padding: 4px 0;'><b>Artifacts:</b></td><td align='right' style='padding: 4px 0;'><span style='color: #60A5FA;'>{statistics.total_artifacts_collected}/{statistics.total_artifacts_requested}</span></td></tr>"
        summary_text += f"<tr><td style='padding: 4px 0;'><b>Files:</b></td><td align='right' style='padding: 4px 0;'><span style='color: #60A5FA;'>{statistics.total_files_collected}</span></td></tr>"
        summary_text += f"<tr><td style='padding: 4px 0;'><b>Size:</b></td><td align='right' style='padding: 4px 0;'><span style='color: #60A5FA;'>{self._format_size(statistics.total_bytes_collected)}</span></td></tr>"
        summary_text += f"<tr><td style='padding: 4px 0;'><b>Errors:</b></td><td align='right' style='padding: 4px 0;'><span style='color: {'#EF4444' if statistics.total_errors > 0 else '#10B981'};'><b>{statistics.total_errors}</b></span></td></tr>"
        summary_text += "</table>"
        
        summary_label = QLabel(summary_text)
        summary_label.setTextFormat(Qt.RichText)
        summary_label.setStyleSheet("color: #E2E8F0;")
        summary_layout.addWidget(summary_label)
        
        layout.addWidget(summary_frame)
        
        # Access method statistics (if available) with dark theme
        if hasattr(collector, 'access_method_stats') and collector.access_method_stats:
            access_frame = QFrame()
            access_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
            access_frame.setStyleSheet("""
                QFrame { 
                    background-color: #1E3A5F; 
                    border: 1px solid #2563EB; 
                    border-radius: 6px; 
                    padding: 12px; 
                }
            """)
            access_layout = QVBoxLayout(access_frame)
            access_layout.setSpacing(6)
            
            access_title = QLabel("ACCESS METHODS")
            access_title_font = QFont("Segoe UI", 9)
            access_title_font.setBold(True)
            access_title.setFont(access_title_font)
            access_title.setStyleSheet("color: #93C5FD; letter-spacing: 1px;")
            access_layout.addWidget(access_title)
            
            access_text = ""
            for method, count in collector.access_method_stats.items():
                if count > 0:
                    method_display = self._format_access_method(method)
                    access_text += f"<span style='font-size: 10pt; color: #DBEAFE;'>{method_display}: <b style='color: #60A5FA;'>{count}</b></span><br>"
            
            access_label = QLabel(access_text)
            access_label.setTextFormat(Qt.RichText)
            access_layout.addWidget(access_label)
            
            layout.addWidget(access_frame)
        
        # Detailed results in scrollable text area with dark theme
        details_label = QLabel("DETAILED RESULTS")
        details_label_font = QFont("Segoe UI", 10)
        details_label_font.setBold(True)
        details_label.setFont(details_label_font)
        details_label.setStyleSheet("color: #94A3B8; letter-spacing: 1px; margin-top: 8px;")
        layout.addWidget(details_label)
        
        details_text = QTextEdit()
        details_text.setReadOnly(True)
        details_text.setMaximumHeight(300)
        details_text.setStyleSheet("""
            QTextEdit { 
                background-color: #0F172A; 
                border: 1px solid #334155; 
                border-radius: 6px; 
                padding: 12px; 
                font-family: 'Consolas', 'Courier New', monospace; 
                font-size: 9pt; 
                color: #E2E8F0;
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
        
        # Build detailed results with dark theme colors
        details_content = ""
        for result in collector.collection_results:
            # Determine status and icon
            if result.status.value == "success":
                status_icon = "✓"
                status_color = "#10B981"
            elif result.status.value == "skipped":
                status_icon = "⊘"
                status_color = "#6B7280"
            else:
                status_icon = "✗"
                status_color = "#EF4444"
            
            # Format size
            size_str = self._format_size(result.bytes_collected)
            
            # Build artifact line
            details_content += f"<span style='color: {status_color}; font-weight: bold;'>{status_icon} {result.artifact_name}:</span> "
            details_content += f"<span style='color: #94A3B8;'>{result.status.value.upper()}</span><br>"
            details_content += f"&nbsp;&nbsp;&nbsp;<span style='color: #CBD5E1;'>Files: <b style='color: #60A5FA;'>{result.files_collected}</b> | Size: <b style='color: #60A5FA;'>{size_str}</b></span><br>"
            
            # Show errors if any (compact)
            if result.errors:
                details_content += f"&nbsp;&nbsp;&nbsp;<span style='color: #EF4444;'>Errors: {len(result.errors)}</span><br>"
            
            details_content += "<br>"
        
        details_text.setHtml(details_content)
        layout.addWidget(details_text)
        
        # OK button with modern dark theme
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("OK")
        ok_button.setMinimumWidth(120)
        ok_button.setMinimumHeight(40)
        ok_button.setStyleSheet("""
            QPushButton { 
                background-color: #2563EB; 
                color: white; 
                border: none; 
                padding: 10px 20px; 
                border-radius: 6px; 
                font-weight: bold; 
                font-size: 11pt;
            } 
            QPushButton:hover { 
                background-color: #1D4ED8; 
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
        """)
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        dialog.exec_()
    
    def _update_access_method_display(self, finished: bool = False):
        """Update the access method statistics display in real-time.
        
        Args:
            finished: If True, show "Collection finished" message
        """
        if finished:
            self.access_method_display.setText("✓ Collection finished")
            return
        
        # Get current access method stats from collector
        if not hasattr(self, 'worker') or not self.worker or not hasattr(self.worker, 'collector') or not self.worker.collector:
            return
        
        if not hasattr(self.worker.collector, 'access_method_stats'):
            return
        
        stats = self.worker.collector.access_method_stats
        
        # Build display text with current statistics
        display_parts = []
        for method, count in stats.items():
            if count > 0:
                method_display = self._format_access_method(method)
                display_parts.append(f"{method_display}: {count}")
        
        if display_parts:
            display_text = " | ".join(display_parts)
            self.access_method_display.setText(display_text)
        else:
            self.access_method_display.setText("(In progress...)")
    
    def _format_access_method(self, method: str) -> str:
        """Format access method for display.
        
        Args:
            method: Access method name (standard, vss, raw_disk)
            
        Returns:
            Formatted method name
        """
        method_map = {
            "standard": "Standard Copy",
            "vss": "VSS",
            "raw_disk": "Raw Disk Access",
            "": "Unknown"
        }
        return method_map.get(method.lower(), method)
    
    def _format_size(self, bytes_size: int) -> str:
        """Format bytes to human-readable size.
        
        Args:
            bytes_size: Size in bytes
            
        Returns:
            Formatted size string
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"


    def open_output_folder(self):
        """Open output folder in explorer."""
        if not self.full_output_path:
            QMessageBox.warning(self, "No Output", "Please select an output directory first")
            return

        import platform
        import subprocess
        
        try:
            if platform.system() == "Windows":
                os.startfile(self.full_output_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", self.full_output_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", self.full_output_path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder: {e}")

    def view_manifest(self):
        """View collection manifest."""
        QMessageBox.information(self, "Manifest", "Manifest viewer not yet implemented")

    @staticmethod
    def update_paths_for_artifact(artifact) -> tuple:
        """Get updated paths for artifact."""
        from ..core.validator import PathValidator
        return PathValidator.validate_artifact_paths(artifact)


def main():
    """Run Crow-Claw main window."""
    app = sys.modules.get('PyQt5.QtWidgets.QApplication')
    if app is None:
        from PyQt5.QtWidgets import QApplication
        app = QApplication(sys.argv)

    window = CrowClawMainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
