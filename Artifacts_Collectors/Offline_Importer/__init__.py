"""
Offline Artifact Importer Package

This package provides functionality for collecting Windows forensic artifacts from
external sources (forensic images, network shares, USB drives) and organizing them
into the Crow-eye case directory structure.

Components:
- offline_importer_gui: Main GUI application for artifact import
- artifact_collector: Core collection engine for scanning and copying artifacts
- artifact_type_detector: Artifact type detection using signatures and patterns
- parser_invoker: Helper for invoking offline parsers
- collection_coordinator: Workflow orchestration and progress tracking

Usage:
    from Artifacts_Collectors.Offline_Importer import launch_gui
    launch_gui()

Author: Crow-eye Forensics
License: MIT
"""

__version__ = "1.0.0"
__author__ = "Crow-eye Forensics Team"
__license__ = "MIT"
__description__ = "Offline Windows Forensic Artifact Importer for Crow-eye"

# ============================================================================
# Public API (Task 15.1)
# ============================================================================

def launch_gui():
    """
    Launch the Offline Artifact Importer GUI (Task 15.2).
    
    This is the main entry point for the application. It creates and displays
    the GUI window for artifact collection.
    
    Returns:
        int: Application exit code
        
    Example:
        >>> from Artifacts_Collectors.Offline_Importer import launch_gui
        >>> launch_gui()
    """
    import sys
    from PyQt5.QtWidgets import QApplication
    from .offline_importer_gui import OfflineImporterGUI
    
    # Create Qt application
    app = QApplication(sys.argv)
    
    # Set application metadata
    app.setApplicationName("Crow-eye Offline Artifact Importer")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Crow-eye Forensics")
    
    # Create and show main window
    window = OfflineImporterGUI()
    window.show()
    
    # Run application event loop
    return app.exec_()

# ============================================================================
# Component Imports (for advanced usage)
# ============================================================================

# Core components
from .artifact_collector import ArtifactCollector, CollectedArtifactInfo
from .artifact_type_detector import ArtifactTypeDetector, ArtifactDetectionResult
from .parser_invoker import ParserInvoker, ParserResult
from .collection_coordinator import CollectionCoordinator, CollectionSummary, ProgressUpdate

# Resources
from .resources.icons import (
    get_artifact_icon,
    get_status_icon,
    get_artifact_color,
    get_status_color,
    ARTIFACT_ICONS,
    STATUS_ICONS
)

# ============================================================================
# Public API Exports
# ============================================================================

__all__ = [
    # Main entry point
    'launch_gui',
    
    # Core components
    'ArtifactCollector',
    'ArtifactTypeDetector',
    'ParserInvoker',
    'CollectionCoordinator',
    
    # Data models
    'CollectedArtifactInfo',
    'ArtifactDetectionResult',
    'ParserResult',
    'CollectionSummary',
    'ProgressUpdate',
    
    # Resource helpers
    'get_artifact_icon',
    'get_status_icon',
    'get_artifact_color',
    'get_status_color',
    
    # Version info
    '__version__',
    '__author__',
    '__license__',
    '__description__',
]

