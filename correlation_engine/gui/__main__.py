"""
Correlation Engine GUI Application Entry Point
Launches the Correlation Engine GUI for pipeline management, execution, and results analysis.
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
# QtWebEngine must be imported before the QApplication exists: the User
# Behavior window (opened from the Behaviour Results tab) is a web view.
try:
    from PyQt5 import QtWebEngineWidgets  # noqa: F401
except ImportError:
    QtWebEngineWidgets = None
from .main_window import MainWindow


def main():
    """Launch the Correlation Engine GUI application"""
    # Enable high DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # Create application
    # DirectWrite font engine on Windows: even letter spacing at small sizes
    try:
        from ui.app_fonts import qt_platform_args
        app = QApplication(qt_platform_args(sys.argv))
    except ImportError:
        app = QApplication(sys.argv)
    app.setApplicationName("Correlation Engine")
    app.setOrganizationName("Crow-Eye")
    
    # The site fonts (Barlow Semi Condensed / JetBrains Mono); the window
    # sets the site look itself (ui/app_theme.py)
    try:
        from ui.app_fonts import load_app_fonts, apply_text_rendering
        load_app_fonts()
        apply_text_rendering(app)
    except Exception as e:
        print(f"[Correlation Engine] site fonts not loaded: {e}")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
