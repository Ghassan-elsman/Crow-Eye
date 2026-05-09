"""
Eye AI Window Manager
=====================

Centralized management for the EYE AI Forensic Assistant window.
"""

import os
from PyQt5 import QtWidgets

class EYESplashWindow(QtWidgets.QWidget):
    """HTML-based splash screen for EYE Assistant."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtCore import Qt, QUrl
        from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
        
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(600, 600)
        
        # Center on screen
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground)
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
    def show_assistant(cls, main_window, artifacts_dir):
        try:
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
                    cls._splash.show()
                    QtWidgets.QApplication.processEvents()

                try:
                    if cls._instance and cls._is_window_valid():
                        cls._instance.close()
                        cls._instance.deleteLater()
                    
                    # Deferred import to catch dependency errors
                    from eye.ui.eye_window import EYEAssistantWindow
                    cls._instance = EYEAssistantWindow(case_directory=artifacts_dir, parent=main_window)
                    
                finally:
                    # Always close splash after window initialization (or failure)
                    if cls._splash:
                        cls._splash.close()
                        cls._splash = None
            
            cls._instance.show()
            cls._instance.raise_()
            cls._instance.activateWindow()
            
            # Ensure case context is checked after splash is gone
            if hasattr(cls._instance, '_check_case_context'):
                cls._instance._check_case_context()
                
            return cls._instance
            
        except Exception as e:
            # Ensure splash is closed on error too
            if cls._splash:
                cls._splash.close()
                cls._splash = None
                
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(main_window, "Eye AI Error", f"Failed to load: {str(e)}")
            
    @classmethod
    def _is_window_valid(cls):
        try:
            return cls._instance is not None and (cls._instance.isVisible() or cls._instance.isHidden())
        except:
            return False
