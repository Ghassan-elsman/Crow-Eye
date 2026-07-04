"""
Eye AI Assistant Window
=======================

Main standalone window for the EYE AI Forensic Assistant.
Integrates the React chat interface and report builder panel with a split pane layout.
"""

import os
import logging
import threading
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QToolBar, QPushButton,
    QSizePolicy, QLabel, QMessageBox, QFrame, QApplication
)
from PyQt5.QtCore import Qt, QUrl, QSize, QTimer, QCoreApplication, QEventLoop
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


class OnboardingCancelled(Exception):
    """Raised when the user closes the OnboardingWizard without saving a config —
    distinguished from real init errors so callers can bail silently instead of
    showing a 'Failed to load' dialog or leaving a half-built window on screen."""


class SilentWebEnginePage(QWebEnginePage):
    """Custom WebEnginePage that suppresses harmless CSS warnings."""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if "Unknown property transition" in message or "Unknown property transform" in message:
            return
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)


class EYECompliancePopupWindow(QWidget):
    """
    Standalone OS window hosting the GEP Compliance dashboard.
    Shares the same EYEBridge instance as the main Eye AI window via a fresh
    QWebChannel, so calls from the popup land in the same backend state.
    """

    def __init__(self, react_build_url: str, bridge, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Eye AI — GEP Compliance")
        self.setWindowIcon(QIcon("GUI Resources/the Eye AI agent transparent.png"))
        self.resize(900, 800)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        self.view.setPage(SilentWebEnginePage(self.view))
        self.view.setAttribute(Qt.WA_TranslucentBackground)
        self.view.page().setBackgroundColor(Qt.transparent)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)

        self.web_channel = QWebChannel(self.view.page())
        self.web_channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.web_channel)

        self.view.load(QUrl(react_build_url + "?view=compliance"))
        layout.addWidget(self.view)
        self.setStyleSheet("background-color: #0B1220;")


class EYENarrativeMapPopupWindow(QWidget):
    """
    Standalone OS window hosting the Narrative Map — the Eye's persistent working
    memory (Verdict → Narrative → Evidence). Shares the same EYEBridge instance as
    the main Eye AI window via a fresh QWebChannel, so edits land in the same backend
    state and are sealed + injected into the Eye's prompt.
    """

    def __init__(self, react_build_url: str, bridge, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Eye AI — Narrative Map")
        self.setWindowIcon(QIcon("GUI Resources/the Eye AI agent transparent.png"))
        self.resize(1100, 800)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        self.view.setPage(SilentWebEnginePage(self.view))
        self.view.setAttribute(Qt.WA_TranslucentBackground)
        self.view.page().setBackgroundColor(Qt.transparent)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)

        self.web_channel = QWebChannel(self.view.page())
        self.web_channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.web_channel)

        self.view.load(QUrl(react_build_url + "?view=map"))
        layout.addWidget(self.view)
        self.setStyleSheet("background-color: #0d0e14;")


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
        self._compliance_window = None  # lazy-instantiated EYECompliancePopupWindow
        self._narrative_map_window = None  # lazy-instantiated EYENarrativeMapPopupWindow
        self._session_started = False  # gate so start_session() runs once per window

        # Debounce chart reflow so dragging the splitter doesn't fire dozens of
        # signals per second across the bridge. The timer is restarted on every
        # splitterMoved; it fires once 150 ms after motion settles.
        self._chart_reflow_timer = QTimer(self)
        self._chart_reflow_timer.setSingleShot(True)
        self._chart_reflow_timer.setInterval(150)
        self._chart_reflow_timer.timeout.connect(self._emit_chart_reflow)
        
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
            # is_configured() reads + validates eye_config.json — give the
            # splash a tick before that I/O and schema-load runs.
            self._pump_splash()

            # 1. Eye AI configuration wizard (only if not already configured).
            #    Raises OnboardingCancelled if the user dismisses it.
            if not self.config_manager.is_configured():
                self._show_onboarding_wizard()

            # Pump once between the config branch and the heavy init below
            # — the wizard path runs its own nested event loop (exec_) so the
            # splash animates during it, but the moment exec_() returns we go
            # straight into _init_services which would otherwise freeze again.
            self._pump_splash()

            # 2. Build services / UI / bridge. case_context_manager is created
            #    inside _init_services so it must run before _check_case_context.
            #    NOTE: the case-setup dialog and React load are deliberately
            #    NOT run here — see start_session(). The constructor only builds
            #    structure so the splash can be torn down before any modal opens.
            #
            #    processEvents() between steps lets _EyeInstantSplash's QTimer
            #    fire so the spinner keeps animating instead of freezing for
            #    the full duration of the constructor. ExcludeUserInputEvents
            #    prevents accidental clicks reaching the half-built window.
            self._init_services()
            self._pump_splash()
            self._init_ui()
            self._pump_splash()
            self._setup_bridge()
            self._pump_splash()
        except Exception as e:
            logger.error(f"Error initializing Eye AI Window: {e}", exc_info=True)
            raise

    def start_session(self):
        """Run the user-facing session start: prompt for case context (first
        time on this case only) and then load the React UI. Called by
        EYEWindowManager after the loading splash has been torn down and the
        Eye window is on screen, so the case-setup modal opens cleanly and the
        automated triage in the React frontend doesn't kick off until the
        investigation reason / objectives / suspects are set.

        Idempotent: a re-show of an already-running Eye window (same case, no
        reinit) must not reload React, which would restart the triage."""
        if self._session_started:
            return
        self._session_started = True

        # Case setup dialog — only opens on first-time-on-this-case
        # (is_context_initialized() returns False until the user fills it).
        # Must run BEFORE _load_react_apps because the React frontend kicks
        # off the automated triage (initialize_triage) as soon as it boots.
        self._check_case_context()

        # Now that config + case context are ready, boot the React UI.
        # Its onBridgeReady handler will call initialize_triage().
        self._load_react_apps()
    
    @staticmethod
    def _pump_splash():
        """Drain the Qt event queue briefly so the instant splash's QTimer
        gets a tick — its spinner / progress bar / status text are all driven
        by that timer, and without periodic pumps during the synchronous
        constructor the animation freezes for the full duration of init.

        ExcludeUserInputEvents keeps stray clicks from reaching the
        half-built window. The 15 ms cap bounds the pump so a single slow
        widget can't stall the next init step waiting on unrelated events."""
        QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents, 15)

    def _build_embedding_client(self, config):
        """Construct an embedding client for semantic retrieval, gated on config.

        Returns None (→ the RAG service uses its always-available BM25 fallback)
        unless ``embedding.enabled`` is set AND a quick probe of the embedding
        server succeeds. This keeps Cloud/CLI deployments (no local Ollama)
        working unchanged; semantic retrieval is strictly opt-in. Default model is
        ``nomic-embed-text`` (v1.5 task prefixes applied automatically).
        """
        emb_cfg = (config or {}).get("embedding") or {}
        if not emb_cfg.get("enabled", False):
            return None
        log = logging.getLogger(__name__)
        try:
            from eye.services.rag_service import OllamaEmbeddingClient
            client = OllamaEmbeddingClient(
                api_endpoint=emb_cfg.get("endpoint", "http://localhost:11434"),
                model_name=emb_cfg.get("model", "nomic-embed-text"),
                timeout=int(emb_cfg.get("timeout", 10) or 10),
            )
            if client.embed_text("probe", is_query=True):
                log.info(f"Embedding client ready: {client.model_name} @ {client.api_endpoint}")
                return client
            log.warning("Embedding server/model not reachable; using BM25 retrieval fallback.")
        except Exception as e:
            log.warning(f"Embedding client init failed; using BM25 fallback: {e}")
        return None

    def _warm_embedding_client_async(self, config):
        """Build the optional embedding client on a background daemon thread and,
        on success, attach it to the already-running RAG service.

        Keeps the blocking embedding-server probe (``_build_embedding_client``)
        OFF the GUI thread so the startup splash never freezes on it. Safe by
        design: the RAG vector index is built lazily on the first retrieval (the
        first query, long after startup), so attaching the client a moment later
        just upgrades BM25 → semantic when ready; a query that fires before the
        warmup finishes transparently uses BM25 (strictly additive). No Qt
        objects are touched, and ``embedding_client`` is only read during a later
        query, so the single attribute set needs no lock."""
        emb_cfg = (config or {}).get("embedding") or {}
        if not emb_cfg.get("enabled", False):
            return

        def _warm():
            try:
                client = self._build_embedding_client(config)
                if client is not None and getattr(self, "rag_service", None) is not None:
                    self.rag_service.embedding_client = client
                    logging.getLogger(__name__).info(
                        "Semantic embedding client attached to RAG service (background warmup).")
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Background embedding warmup failed; staying on BM25: {e}")

        threading.Thread(target=_warm, name="eye-embedding-warmup", daemon=True).start()

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
        self._pump_splash()
        self.search_service = ForensicSearchService(artifacts_dir)
        self._pump_splash()
        # Build RAG with the always-available BM25 fallback IMMEDIATELY (no I/O),
        # then warm up the optional embedding client OFF the GUI thread. The
        # embedding probe is a blocking network call (up to its timeout); running
        # it inline froze the startup splash whenever the embedding server was
        # slow/unreachable. The vector index is built lazily on the first query,
        # so attaching the client a moment later loses nothing.
        self.rag_service = RAGService(embedding_client=None)
        self._warm_embedding_client_async(config)
        self._pump_splash()

        self.report_engine = ReportEngine(self.case_directory)
        self.case_context_manager = CaseContextManager(self.case_directory)
        self._pump_splash()

        self.context_manager = ContextManager(
            model_router=self.model_router,
            database_service=self.database_service,
            search_service=self.search_service,
            rag_service=self.rag_service,
            report_engine=self.report_engine,
            case_directory=self.case_directory,
            case_context_manager=self.case_context_manager
        )
        self._pump_splash()

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
        
        # QWebEngineView construction is the single biggest freeze source on
        # first launch (cold WebEngine process spin-up, ~hundreds of ms each).
        # Pump events around each one so the instant splash keeps animating.
        self._pump_splash()
        self.chat_view = QWebEngineView(self)
        self.chat_view.setPage(SilentWebEnginePage(self.chat_view))
        self._pump_splash()

        self.report_view = QWebEngineView(self)
        self.report_view.setPage(SilentWebEnginePage(self.report_view))
        self._pump_splash()
        
        # Security: Enable local content access to resources (for qrc:/// qwebchannel)
        for view in [self.chat_view, self.report_view]:
            view.setAttribute(Qt.WA_TranslucentBackground)
            view.page().setBackgroundColor(Qt.transparent)
            settings = view.settings()
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
            self._pump_splash()

        self.splitter.addWidget(self.chat_view)
        self._pump_splash()
        
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
        self._pump_splash()
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
            # Pane just became visible — its width changed, so charts need to reflow.
            self._chart_reflow_timer.start()

    def _emit_chart_reflow(self):
        """Tell the React layer to re-measure and re-render charts. Called via
        the debounced timer after splitter drags, pane toggles, or window resize."""
        if self.bridge is not None:
            self.bridge.reflow_charts.emit()

    def resizeEvent(self, event):
        """Trigger a debounced chart reflow on OS-level window resize."""
        super().resizeEvent(event)
        if getattr(self, '_chart_reflow_timer', None) is not None:
            self._chart_reflow_timer.start()

    def _setup_bridge(self):
        self.web_channel = QWebChannel()
        self._pump_splash()
        self.bridge = EYEBridge(
            context_manager=self.context_manager,
            database_service=self.database_service,
            search_service=self.search_service,
            report_engine=self.report_engine,
            parent=self
        )
        self._pump_splash()

        # Connect layout signals
        self.bridge.layout_requested.connect(self._handle_layout_request)

        self.web_channel.registerObject("bridge", self.bridge)
        # setWebChannel on a QWebEnginePage can trigger renderer-side
        # bookkeeping; pump between the two so the splash keeps animating.
        self.chat_view.page().setWebChannel(self.web_channel)
        self._pump_splash()
        self.report_view.page().setWebChannel(self.web_channel)
        self._pump_splash()
        
        # Connect bridge signals for UI integration
        self.bridge.case_context_requested.connect(self._on_case_context_clicked)
        self.bridge.case_summary_requested.connect(self._on_case_summary_clicked)
        self.bridge.settings_requested.connect(self._show_onboarding_wizard)
        self.bridge.compliance_window_requested.connect(self._open_compliance_window)
        self.bridge.narrative_map_window_requested.connect(self._open_narrative_map_window)

        # Reflow report-pane charts whenever the splitter is dragged so charts
        # stay aligned with their container width. Debounced via _chart_reflow_timer.
        if self.splitter is not None:
            self.splitter.splitterMoved.connect(lambda *_: self._chart_reflow_timer.start())
        
        # Hide the redundant PyQt toolbar (navigation moved to React header)
        if hasattr(self, 'toolbar') and self.toolbar:
            self.toolbar.hide()

    def _load_react_apps(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        react_build_path = os.path.join(base_dir, 'ui', 'react', 'dist', 'index.html')
        
        if not os.path.exists(react_build_path):
            from PyQt5.QtWidgets import QMessageBox
            err_msg = "The EYE AI React interface could not be found.\n\nPlease ensure Node.js is installed and the React app is built successfully."
            print(f"[Error] {err_msg}")
            
            # Show a warning dialog but don't crash
            QMessageBox.warning(self, "EYE AI Build Missing", err_msg)
            
            # Load fallback HTML instead of raising an exception
            fallback_html = f"""
            <html><body style="background-color: #0B1220; color: #E2E8F0; font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; text-align: center;">
                <div>
                    <h2 style="color: #ff5555;">EYE AI Interface Missing</h2>
                    <p>The React application build was not found at:</p>
                    <code style="background: #1E293B; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-top: 10px; display: inline-block;">{react_build_path}</code>
                    <p style="margin-top: 20px; color: #94A3B8;">Please restart Crow-Eye with an active internet connection to automatically download Node.js and build the GUI, or build it manually.</p>
                </div>
            </body></html>
            """
            self.chat_view.setHtml(fallback_html)
            self.report_view.setHtml(fallback_html)
            return

        url = QUrl.fromLocalFile(react_build_path)
        self.chat_view.load(QUrl(url.toString() + "?view=chat"))
        self.report_view.load(QUrl(url.toString() + "?view=report"))

    def _show_onboarding_wizard(self):
        # Ensure we have a credential manager instance
        if self.credential_manager is None:
            self.credential_manager = CredentialManager()

        # The wizard saves config (and stores API keys) on accept. The main
        # __init__ flow picks up from where this returns, so we no longer wire
        # the configuration_complete signal — it would race the linear init
        # below and end up loading React twice.
        wizard = OnboardingWizard(self.config_manager, self.credential_manager, None, self)
        wizard.exec_()

        # If the user dismissed the wizard without saving, the config file was
        # never written. Aborting here prevents the rest of __init__ from being
        # skipped silently and leaving an empty Eye window with no layout or
        # services on screen.
        if not self.config_manager.is_configured():
            raise OnboardingCancelled("Eye AI onboarding was cancelled before configuration was saved.")

        # Re-initialize services with the new configuration. This ensures that
        # any changes to backend, model, or credentials take effect immediately.
        # We call _init_services which recreates the ModelRouter and ContextManager.
        try:
            # Clean up old database connections before recreating services
            if self.database_service:
                self.database_service.close_all()
                
            self._init_services()
            
            # Sync the bridge with new service instances so React calls land on the 
            # new backend immediately without requiring a window restart.
            if self.bridge:
                self.bridge.context_manager = self.context_manager
                self.bridge.database_service = self.database_service
                self.bridge.search_service = self.search_service
                self.bridge.report_engine = self.report_engine
                # Re-register the live Narrative Map update callback on the new CM.
                try:
                    self.context_manager.narrative_map_update_callback = self.bridge.emit_narrative_map_changed
                except Exception:
                    pass
                logger.info("Eye AI services refreshed successfully after configuration update.")
                
        except Exception as e:
            logger.error(f"Failed to refresh services after configuration: {e}", exc_info=True)
            QMessageBox.warning(self, "Service Refresh Error", 
                               f"Configuration was saved, but some services failed to restart: {str(e)}\n\n"
                               "Please restart the Eye AI Assistant window.")

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
        report_blocks = self.report_engine.blocks if self.report_engine else []
        # Full chat conversation history — the dialog's Queries tab shows all
        # user-side queries, broader than the AI-curated investigation timeline.
        conversation = self.context_manager.conversation_history if self.context_manager else []
        # Case context drives the dialog's overview band (case name, reason, time range, counts).
        case_context = self.case_context_manager.case_context if self.case_context_manager else {}
        dialog = CaseSummaryDialog(timeline, report_blocks, conversation, case_context, self)
        dialog.exec_()

    def _open_compliance_window(self):
        """Open the GEP Compliance dashboard as a separate OS window so the
        investigator can view chat, report, and compliance simultaneously."""
        # If a popup already exists, re-use it whether visible or hidden — we
        # used to gate on isVisible() and construct a new window every time the
        # user closed and re-opened, leaking the previous QWebEngineView.
        if self._compliance_window is not None:
            try:
                if not self._compliance_window.isVisible():
                    self._compliance_window.show()
                self._compliance_window.raise_()
                self._compliance_window.activateWindow()
                return
            except RuntimeError:
                # Underlying C++ object was deleted (e.g. WA_DeleteOnClose) —
                # drop the dangling ref and rebuild below.
                self._compliance_window = None

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        react_build_path = os.path.join(base_dir, 'ui', 'react', 'dist', 'index.html')
        if not os.path.exists(react_build_path):
            logger.error("Cannot open Compliance window: React build missing at %s", react_build_path)
            return
        react_build_url = QUrl.fromLocalFile(react_build_path).toString()

        self._compliance_window = EYECompliancePopupWindow(react_build_url, self.bridge, parent=self)
        # If the widget ever gets destroyed (manual close + delete, parent
        # teardown), clear the reference so the next click rebuilds cleanly.
        self._compliance_window.destroyed.connect(lambda *_: setattr(self, '_compliance_window', None))
        self._compliance_window.show()
        self._compliance_window.raise_()
        self._compliance_window.activateWindow()

    def _open_narrative_map_window(self):
        """Open the Narrative Map as a separate OS window so the investigator can view
        chat, report, and the case's narrative memory simultaneously."""
        if self._narrative_map_window is not None:
            try:
                if not self._narrative_map_window.isVisible():
                    self._narrative_map_window.show()
                self._narrative_map_window.raise_()
                self._narrative_map_window.activateWindow()
                return
            except RuntimeError:
                # Underlying C++ object was deleted — drop the dangling ref and rebuild.
                self._narrative_map_window = None

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        react_build_path = os.path.join(base_dir, 'ui', 'react', 'dist', 'index.html')
        if not os.path.exists(react_build_path):
            logger.error("Cannot open Narrative Map window: React build missing at %s", react_build_path)
            return
        react_build_url = QUrl.fromLocalFile(react_build_path).toString()

        self._narrative_map_window = EYENarrativeMapPopupWindow(react_build_url, self.bridge, parent=self)
        self._narrative_map_window.destroyed.connect(lambda *_: setattr(self, '_narrative_map_window', None))
        self._narrative_map_window.show()
        self._narrative_map_window.raise_()
        self._narrative_map_window.activateWindow()

    def closeEvent(self, event):
        """Close the popup windows when the main Eye AI window closes."""
        if self._compliance_window is not None:
            self._compliance_window.close()
            self._compliance_window = None
        if self._narrative_map_window is not None:
            self._narrative_map_window.close()
            self._narrative_map_window = None
        super().closeEvent(event)


