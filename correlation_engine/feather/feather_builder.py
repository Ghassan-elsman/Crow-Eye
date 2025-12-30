"""
Feather Builder - Main Application Entry Point
Launches the Feather Builder GUI application.
"""

import sys
from PyQt5.QtWidgets import QApplication
from .ui.main_window import FeatherBuilderWindow


class FeatherBuilder:
    """Main Feather Builder application class."""
    
    def __init__(self):
        self.app = None
        self.window = None
    
    def run(self):
        """Launch the Feather Builder application."""
        self.app = QApplication(sys.argv)
        self.window = FeatherBuilderWindow()
        self.window.show()
        sys.exit(self.app.exec_())


def main():
    """Entry point for the Feather Builder application."""
    builder = FeatherBuilder()
    builder.run()


if __name__ == "__main__":
    main()
