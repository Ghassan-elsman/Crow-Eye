"""
Eye AI Window Manager
=====================

Centralized management for the EYE AI Forensic Assistant window.
"""

import os
from PyQt5 import QtCore, QtWidgets

class EYESplashWindow(QtWidgets.QWidget):
    """HTML-based splash screen for EYE Assistant."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtCore import Qt, QUrl
        from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
        
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(600, 600)

        # Center on screen
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground)
        self.view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.view.page().setBackgroundColor(Qt.transparent)        
        # Disable scrollbars and context menu
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.settings().setAttribute(QWebEngineSettings.ShowScrollBars, False)
        
        # Load the standalone splash HTML
        base_dir = os.path.dirname(os.path.abspath(__file__))
        splash_path = os.path.join(base_dir, 'eye_splash.html')
        self.view.load(QUrl.fromLocalFile(splash_path))
        
        layout.addWidget(self.view)

class EYEWindowManager:
    _instance = None
    _splash = None
    
    @classmethod
    def show_assistant(cls, main_window, artifacts_dir, parent_splash=None):
        try:
            # Mandatory: Set WebEngine sharing attribute before ANY WebEngine-related imports
            # This prevents crashes when launching the Eye from an existing QApplication
            from PyQt5.QtCore import Qt
            from PyQt5.QtWidgets import QApplication
            # AA_ShareOpenGLContexts moved to main entry point (Crow Eye.py) 
            # to ensure it is set before QCoreApplication is created.
            
            # Safety Check
            if not artifacts_dir or not os.path.exists(artifacts_dir):
                QtWidgets.QMessageBox.warning(main_window, "Eye AI", "Open a case first.")
                return None

            # Case change detection
            should_reinit = (
                cls._instance is None or 
                not cls._is_window_valid() or 
                (hasattr(cls._instance, 'case_directory') and cls._instance.case_directory != artifacts_dir)
            )
            
            if should_reinit:
                # Check if configured before showing splash
                # Only show splash if configuration is already set up and valid
                try:
                    from eye.services.config_manager import ConfigManager
                    config_mgr = ConfigManager()
                    show_splash = config_mgr.is_configured()
                except Exception as e:
                    # If ConfigManager fails, skip splash as fallback
                    show_splash = False
                
                # Show the HTML-based splash screen only if configured
                if show_splash:
                    cls._splash = EYESplashWindow()

                    # Handoff: as soon as the WebEngine splash's HTML has
                    # rendered, tear down the caller's instant splash. The
                    # WebEngine splash animates smoothly in its renderer
                    # process even while the main thread is blocked by the
                    # heavy widget construction below, so handing off keeps
                    # the user looking at smooth motion instead of the
                    # timer-driven instant splash that stalls during each
                    # blocking C++ call (QWebEngineView, schema-load, etc.).
                    if parent_splash is not None:
                        _captured = parent_splash
                        def _on_html_splash_loaded(_ok, _splash=_captured):
                            cls._destroy_external_splash(_splash)
                        cls._splash.view.loadFinished.connect(_on_html_splash_loaded)

                    cls._splash.show()
                    QtWidgets.QApplication.processEvents()
                else:
                    # Not configured (first run): EYEAssistantWindow.__init__ opens the onboarding
                    # wizard as a BLOCKING modal (wizard.exec_()). That nested event loop freezes the
                    # caller's timer-driven instant splash, leaving "Initializing Eye engine…" painted
                    # behind the wizard forever. Nothing initializes until a backend is saved, so tear
                    # the instant splash down NOW so the user sees a clean setup wizard.
                    cls._destroy_external_splash(parent_splash)
                    parent_splash = None

                try:
                    if cls._instance and cls._is_window_valid():
                        cls._instance.close()
                        cls._instance.deleteLater()
                        QtWidgets.QApplication.processEvents(
                            QtCore.QEventLoop.ExcludeUserInputEvents, 15
                        )

                    # Deferred import to catch dependency errors. On first
                    # launch this loads eye_window + all of its services /
                    # bridge / ui transitively — ~100-300 ms cold. Pump the
                    # event loop on either side so any splash currently
                    # showing keeps animating across the import.
                    QtWidgets.QApplication.processEvents(
                        QtCore.QEventLoop.ExcludeUserInputEvents, 15
                    )
                    from eye.ui.eye_window import EYEAssistantWindow, OnboardingCancelled
                    QtWidgets.QApplication.processEvents(
                        QtCore.QEventLoop.ExcludeUserInputEvents, 15
                    )
                    try:
                        cls._instance = EYEAssistantWindow(case_directory=artifacts_dir, parent=main_window)
                    except OnboardingCancelled:
                        # User dismissed the onboarding wizard — not an error.
                        # Clear the cached instance so the next click re-prompts
                        # instead of resurrecting a half-built window. Also tear
                        # down the caller's instant splash so it doesn't linger.
                        cls._instance = None
                        cls._destroy_external_splash(parent_splash)
                        return None

                finally:
                    # Always close splash after window initialization (or failure).
                    # close() only queues the event; without flushing it, a modal opened
                    # right after (e.g. CaseSetupDialog on first-open) would block before
                    # the splash actually disappears, leaving the "loading" card painted
                    # on screen behind the dialog.
                    cls._destroy_splash()

            cls._instance.show()
            cls._instance.raise_()
            cls._instance.activateWindow()
            QtWidgets.QApplication.processEvents()

            # Tear down the caller's instant splash (Crow Eye.py's
            # _EyeInstantSplash) now that the real Eye window is on screen.
            # Must happen BEFORE start_session opens the case-setup modal —
            # otherwise the instant splash stays painted behind the dialog
            # for the entire duration the user spends filling it in.
            cls._destroy_external_splash(parent_splash)

            # Start the user-facing session: prompts for case context (first
            # time on this case only) and then loads the React UI, which kicks
            # off the automated triage. Done here — not in __init__ — so the
            # splash is fully torn down before the case-setup modal opens, and
            # so the triage cannot start before the investigator has provided
            # the investigation reason / objectives / suspects.
            if hasattr(cls._instance, 'start_session'):
                cls._instance.start_session()

            return cls._instance
            
        except Exception as e:
            # Ensure splash is closed on error too (both the internal
            # EYESplashWindow and the caller's instant splash, if passed).
            cls._destroy_splash()
            cls._destroy_external_splash(parent_splash)

            import traceback
            traceback.print_exc()
            
            # Run a quick diagnostic to provide better error info
            try:
                from eye.services.diagnostics import SystemDiagnostics
                diag = SystemDiagnostics()
                ui_res = diag.check_ui_artifacts()
                sdk_res = diag.check_backend_sdks()
                
                diag_info = f"\n\nDiagnostics:\n- UI Interface: {ui_res['status']}\n"
                for sdk in sdk_res:
                    diag_info += f"- {sdk['name']}: {sdk['status']}\n"
            except:
                diag_info = ""

            QtWidgets.QMessageBox.critical(
                main_window, 
                "Eye AI Error", 
                f"Failed to load: {str(e)}{diag_info}\n\nPlease run 'Diagnostics' in the Setup Wizard for more details."
            )
            
    @classmethod
    def _destroy_splash(cls):
        if not cls._splash:
            return
        try:
            cls._splash.hide()
            cls._splash.close()
            cls._splash.deleteLater()
        finally:
            cls._splash = None
            QtWidgets.QApplication.processEvents()

    @staticmethod
    def _destroy_external_splash(splash):
        """Tear down a splash owned by the caller (e.g. Crow Eye.py's
        _EyeInstantSplash). Same hide+close+deleteLater+processEvents pattern
        as the internal splash teardown so the widget is painted away before
        any subsequent modal blocks the event loop."""
        if splash is None:
            return
        try:
            splash.hide()
            splash.close()
            splash.deleteLater()
        except Exception:
            # Caller's splash; never propagate teardown errors.
            pass
        finally:
            QtWidgets.QApplication.processEvents()

    @classmethod
    def _is_window_valid(cls):
        try:
            return cls._instance is not None and (cls._instance.isVisible() or cls._instance.isHidden())
        except:
            return False
