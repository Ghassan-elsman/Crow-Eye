"""
EYE AI Window Manager - Standalone window orchestration for EYE AI Forensic Assistant.

This module provides the EyeWindowManager class, which handles the creation,
display, and lifecycle of the standalone EYE AI Assistant window.
"""

import os
import logging
import traceback
from PyQt5 import QtWidgets, QtCore, QtGui
from eye.ui.eye_tab import EYETab

logger = logging.getLogger(__name__)

class EyeWindowManager(QtCore.QObject):
    """
    Manages the standalone EYE AI Forensic Assistant window.
    """
    
    def __init__(self, main_window):
        """
        Initialize the EYE window manager.
        
        Args:
            main_window: The main Crow Eye QMainWindow instance.
        """
        super().__init__(main_window)
        self.main_window = main_window
        self.eye_window = None
        self.artifacts_dir = None
        
    def show_eye_assistant(self, artifacts_dir=None):
        """
        Show the EYE AI Forensic Assistant in a standalone window.
        
        Args:
            artifacts_dir: Optional path to the forensic artifacts directory.
                           If not provided, uses the last known directory.
        """
        try:
            # Update artifacts directory if provided
            if artifacts_dir:
                self.artifacts_dir = artifacts_dir
            
            # Basic validation
            if not self.artifacts_dir or not os.path.exists(self.artifacts_dir):
                QtWidgets.QMessageBox.warning(
                    self.main_window,
                    "Artifacts Directory Error",
                    "The forensic artifacts directory is missing or invalid.\n\n"
                    "Please ensure a case is loaded and artifacts are collected."
                )
                return False
                
            print(f"[EyeManager] Opening EYE AI Assistant from: {self.artifacts_dir}")
            
            # Check if window already exists
            if self.eye_window is not None:
                # If window exists, just bring it to front
                self.eye_window.show()
                self.eye_window.raise_()
                self.eye_window.activateWindow()
                print("[EyeManager] EYE AI Assistant window brought to front")
                return True
            
            # Create as a standalone window
            # We use EYETab as the content but show it as a window
            self.eye_window = EYETab(
                case_directory=self.artifacts_dir,
                parent=self.main_window # Keeps it in the same process but separate window
            )
            
            # Configure standalone window properties
            self.eye_window.setWindowTitle("EYE AI Forensic Assistant")
            self.eye_window.setWindowIcon(QtGui.QIcon(":/Icons/CrowEye.ico"))
            
            # Set a reasonable default size for a standalone window
            self.eye_window.resize(1200, 900)
            
            # Handle window close event to reset reference
            # We'll use the destroyed signal to set the reference back to None
            self.eye_window.destroyed.connect(self._on_window_destroyed)
            
            # Show the window
            self.eye_window.show()
            self.eye_window.raise_()
            self.eye_window.activateWindow()
            
            print("[EyeManager] EYE AI Assistant opened as standalone window")
            return True
            
        except Exception as e:
            error_msg = f"Failed to show EYE AI Assistant: {str(e)}"
            logger.error(error_msg, exc_info=True)
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(
                self.main_window,
                "EYE AI Assistant Error",
                f"An error occurred while launching the EYE AI window:\n{str(e)}"
            )
            return False

    def _on_window_destroyed(self):
        """Cleanup when the window is closed/destroyed."""
        print("[EyeManager] EYE AI Assistant window destroyed")
        self.eye_window = None

    def update_case_directory(self, artifacts_dir):
        """
        Update the artifacts directory for the current manager.
        If the window is open, it might need to be re-initialized.
        """
        self.artifacts_dir = artifacts_dir
        if self.eye_window:
            # If window is open, we might want to refresh its case context
            # For now, we'll let the user close and re-open to keep it simple
            # but we could add a refresh method to EYETab
            pass
