"""
Eye AI Assistant Window
=======================

Main standalone window for the EYE AI Forensic Assistant.
Integrates the React chat interface and report builder panel with a split pane layout.
"""

import os
import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QToolBar, QPushButton,
    QSizePolicy, QLabel, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, QUrl, QSize
from PyQt5.QtGui import QIcon
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from PyQt5.QtWebChannel import QWebChannel

from eye.bridge.eye_bridge import EYEBridge
from eye.services.context_manager import ContextManager
from eye.services.config_manager import ConfigManager
from eye.services.credential_manager import CredentialManager
from eye.services.model_router import ModelRouter
from eye.services.database_service import ForensicDatabaseService
from eye.services.search_service import ForensicSearchService
from eye.services.rag_service import RAGService
from eye.services.report_engine import ReportEngine
from eye.services.case_context_manager import CaseContextManager
from eye.ui.onboarding_wizard import OnboardingWizard
from eye.ui.case_setup_dialog import CaseSetupDialog, CaseContextEditDialog
from eye.ui.case_summary_dialog import CaseSummaryDialog
from eye.ui import message_box_helper

logger = logging.getLogger(__name__)

class SilentWebEnginePage(QWebEnginePage):
    """Custom WebEnginePage that suppresses harmless CSS warnings."""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if "Unknown property transition" in message or "Unknown property transform" in message:
            return
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

class EYEAssistantWindow(QWidget):
    """
    Main Eye AI Assistant window with split pane layout.
    """
    
    def __init__(self, case_directory: str, parent=None):
        """
        Initialize the Eye AI Assistant Window.
        """
        super().__init__(parent)
        
        # Standalone Window Configuration
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setWindowTitle("Eye AI Forensic Assistant")
        self.setWindowIcon(QIcon("GUI Resources/the Eye AI agent transparent.png"))
        self.setMinimumSize(1200, 900)
        
        self.case_directory = case_directory
        self.main_window = parent
        
        # UI State
        self.report_pane_visible = True
        self.last_splitter_sizes = [600, 400]
        
        # UI components
        self.toolbar = None
        self.splitter = None
        self.chat_view = None
        self.report_view = None
        self.web_channel = None
        self.bridge = None
        
        # Services
        self.credential_manager = None
        self.config_manager = None
        self.model_router = None
        self.database_service = None
        self.search_service = None
        self.rag_service = None
        self.report_engine = None
        self.context_manager = None
        self.case_context_manager = None
        
        try:
            message_box_helper.apply_messagebox_style()
            self.config_manager = ConfigManager()
            
            if not self.config_manager.is_configured():
                self._show_onboarding_wizard()
            else:
                self._init_services()
                self._init_ui()
                self._setup_bridge()
                self._load_react_apps()
        except Exception as e:
            logger.error(f"Error initializing Eye AI Window: {e}", exc_info=True)
            raise
    
    def _init_services(self):
        """Initialize all AI backend services."""
        self.credential_manager = CredentialManager()
        self.config_manager = ConfigManager()
        config = self.config_manager.load_config()
        self.model_router = ModelRouter(config=config, credential_manager=self.credential_manager)
        
        artifacts_dir = os.path.join(self.case_directory, "Target_Artifacts")
        if not os.path.exists(artifacts_dir):
            artifacts_dir = self.case_directory
            
        self.database_service = ForensicDatabaseService(artifacts_dir)
        self.search_service = ForensicSearchService(artifacts_dir)
        self.rag_service = RAGService()
        

        self.report_engine = ReportEngine(self.case_directory)
        self.case_context_manager = CaseContextManager(self.case_directory)
        

        self.context_manager = ContextManager(
            model_router=self.model_router,
            database_service=self.database_service,
            search_service=self.search_service,
            rag_service=self.rag_service,
            report_engine=self.report_engine,
            case_directory=self.case_directory,
            case_context_manager=self.case_context_manager
        )

    def _init_ui(self):
        """Setup the window UI."""
        if self.layout():
            # UI already initialized, don't create new layout or widgets
            return
            
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.toolbar = self._create_toolbar()
        layout.addWidget(self.toolbar)
        
        # Main Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setContentsMargins(0, 0, 0, 0)
        self.splitter.setHandleWidth(2)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #334155; } QSplitter::handle:hover { background-color: #00FFFF; }")
        
        self.chat_view = QWebEngineView(self)
        self.chat_view.setPage(SilentWebEnginePage(self.chat_view))
        
        self.report_view = QWebEngineView(self)
        self.report_view.setPage(SilentWebEnginePage(self.report_view))
        
        # Security: Enable local content access to resources (for qrc:/// qwebchannel)
        for view in [self.chat_view, self.report_view]:
            view.setAttribute(Qt.WA_TranslucentBackground)
            view.page().setBackgroundColor(Qt.transparent)
            settings = view.settings()
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        
        self.splitter.addWidget(self.chat_view)
        
        # Central Toggle Bar (Between Chat and Report)
        self.toggle_bar = QFrame()
        self.toggle_bar.setFixedWidth(24)
        self.toggle_bar.setStyleSheet("background-color: #0B1220; border-left: 1px solid #1E293B; border-right: 1px solid #1E293B;")
        toggle_layout = QVBoxLayout(self.toggle_bar)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.addStretch() # Push button to center
        
        self.btn_side_toggle = QPushButton("◀") # Initially pointing left to hide
        self.btn_side_toggle.setToolTip("Toggle Forensic Investigation Report")
        self.btn_side_toggle.setFixedSize(20, 100) # Taller vertical handle
        self.btn_side_toggle.setStyleSheet("""
            QPushButton { 
                background-color: #1E293B; 
                color: #C084FC; 
                border: 1px solid #334155; 
                border-radius: 4px;
                font-weight: bold; 
                font-size: 14pt;
                outline: none;
            }
            QPushButton:hover { 
                background-color: #334155; 
                color: #FFFFFF; 
                border-color: #C084FC;
            }
        """)
        self.btn_side_toggle.clicked.connect(self._toggle_report_pane)
        toggle_layout.addWidget(self.btn_side_toggle)
        toggle_layout.addStretch() # Push button to center
        
        # Add toggle bar and report view to splitter
        self.splitter.addWidget(self.toggle_bar)
        self.splitter.addWidget(self.report_view)
        
        self.splitter.setSizes([700, 24, 476])
        
        # Ensure the toggle bar doesn't collapse
        self.splitter.setCollapsible(1, False) 
        
        layout.addWidget(self.splitter)
        self.setStyleSheet("""
            QWidget { 
                background-color: #0B1220; 
                color: #E2E8F0;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QSplitter::handle { 
                background-color: #1E293B; 
                margin: 2px 0;
            }
            QSplitter::handle:horizontal:hover { 
                background-color: #C084FC; 
            }
        """)

    def _create_toolbar(self) -> QToolBar:
        """Create window toolbar."""
        toolbar = QToolBar("Eye AI Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setStyleSheet("""
            QToolBar { 
                spacing: 8px; 
                padding: 4px 12px; 
                background: #0B0C12; 
                border-bottom: 1px solid #1E293B; 
            }
            QPushButton { 
                background: transparent; 
                color: #94A3B8; 
                border: 1px solid transparent; 
                border-radius: 4px; 
                padding: 4px 10px; 
                font-size: 11px; 
                font-weight: 500;
            }
            QPushButton:hover { 
                background: rgba(255, 255, 255, 0.05); 
                color: #E2E8F0;
                border: 1px solid rgba(255, 255, 255, 0.1); 
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.02);
            }
        """)
        
        btn_context = QPushButton("\ud83d\udccb Case Context")
        btn_context.clicked.connect(self._on_case_context_clicked)
        toolbar.addWidget(btn_context)
        
        btn_summary = QPushButton("\ud83d\udcca Case Summary")
        btn_summary.clicked.connect(self._on_case_summary_clicked)
        toolbar.addWidget(btn_summary)
        
        # Side toggle button is now vertical on the right
        # No button needed in top toolbar
        
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        
        return toolbar

    def _toggle_report_pane(self):
        """Toggle report pane visibility."""
        if self.report_pane_visible:
            # Hide the report pane
            sizes = self.splitter.sizes()
            self.last_splitter_sizes = sizes
            self.report_view.hide()
            self.report_pane_visible = False
            self.btn_side_toggle.setText("▶") # Point right to show
        else:
            # Show the report pane
            self.report_view.show()
            # Restore sizes
            if hasattr(self, 'last_splitter_sizes'):
                # If last size was too small, use default
                if self.last_splitter_sizes[2] < 50:
                    self.last_splitter_sizes[2] = 400
                self.splitter.setSizes(self.last_splitter_sizes)
            else:
                self.splitter.setSizes([780, 20, 400])
                
            self.report_pane_visible = True
            self.btn_side_toggle.setText("◀") # Point left to hide

    def _setup_bridge(self):
        self.web_channel = QWebChannel()
        self.bridge = EYEBridge(
            context_manager=self.context_manager,
            database_service=self.database_service,
            search_service=self.search_service,
            report_engine=self.report_engine,
            parent=self
        )
        
        # Connect layout signals
        self.bridge.layout_requested.connect(self._handle_layout_request)
        
        self.web_channel.registerObject("bridge", self.bridge)
        self.chat_view.page().setWebChannel(self.web_channel)
        self.report_view.page().setWebChannel(self.web_channel)
        
        # Connect bridge signals for UI integration
        self.bridge.case_context_requested.connect(self._on_case_context_clicked)
        self.bridge.case_summary_requested.connect(self._on_case_summary_clicked)
        self.bridge.settings_requested.connect(self._show_onboarding_wizard)
        
        # Hide the redundant PyQt toolbar (navigation moved to React header)
        if hasattr(self, 'toolbar') and self.toolbar:
            self.toolbar.hide()

    def _load_react_apps(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        react_build_path = os.path.join(base_dir, 'ui', 'react', 'dist', 'index.html')
        if not os.path.exists(react_build_path):
            raise FileNotFoundError("React build missing.")
        url = QUrl.fromLocalFile(react_build_path)
        self.chat_view.load(QUrl(url.toString() + "?view=chat"))
        self.report_view.load(QUrl(url.toString() + "?view=report"))

    def _show_onboarding_wizard(self):
        wizard = OnboardingWizard(self.config_manager, CredentialManager(), None, self)
        wizard.configuration_complete.connect(self._on_configuration_complete)
        wizard.exec_()

    def _on_configuration_complete(self, config):
        self._init_services()
        self._init_ui()
        self._setup_bridge()
        self._load_react_apps()
        self._check_case_context()

    def _check_case_context(self):
        if not self.case_context_manager:
            return
        if not self.case_context_manager.is_context_initialized():
            dialog = CaseSetupDialog(parent=self)
            dialog.case_context_initialized.connect(self._on_case_context_initialized)
            dialog.exec_()

    def _on_case_context_initialized(self, case_context):
        self.case_context_manager.initialize_context(**case_context)

    def _handle_layout_request(self, request_json: str):
        """Handle layout requests from the React frontend."""
        import json
        try:
            request = json.loads(request_json)
            action = request.get("action")
            
            if action == "set_report_pane_visible":
                visible = request.get("visible", True)
                if visible != self.report_pane_visible:
                    self._toggle_report_pane()
        except Exception as e:
            print(f"Error handling layout request: {e}")

    def _on_case_context_clicked(self):
        dialog = CaseContextEditDialog(self.case_context_manager.case_context, self)
        dialog.case_context_updated.connect(self._on_case_context_updated)
        dialog.exec_()

    def _on_case_context_updated(self, updated_context):
        self.case_context_manager.update_context(updated_context)

    def _on_clear_history_clicked(self):
        if message_box_helper.question(self, "Clear History", "Confirm?") == QMessageBox.Yes:
            if self.context_manager:
                self.context_manager.conversation_history = []
                if hasattr(self.context_manager, "history_manager"):
                    self.context_manager.history_manager.save_history()

    def _on_case_summary_clicked(self):
        """Handle case summary button click."""
        timeline = self.case_context_manager.get_investigation_timeline() if self.case_context_manager else []
        # Always open the dialog so user can see Report Findings and Charts tabs even if timeline is empty
        report_blocks = self.report_engine.blocks if self.report_engine else []
        dialog = CaseSummaryDialog(timeline, report_blocks, self)
        dialog.exec_()


