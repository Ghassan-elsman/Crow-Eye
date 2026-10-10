"""
Correlation Engine GUI Application Entry Point
Launches the Correlation Engine GUI for pipeline management, execution, and results analysis.
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from .main_window import MainWindow


def main():
    """Launch the Correlation Engine GUI application"""
    # Enable high DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("Correlation Engine")
    app.setOrganizationName("Crow-Eye")
    
    # The site fonts (Barlow Semi Condensed / JetBrains Mono); the window
    # sets the site look itself (ui/site_theme.py)
    try:
        from ui.app_fonts import load_app_fonts
        load_app_fonts()
    except Exception as e:
        print(f"[Correlation Engine] site fonts not loaded: {e}")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
