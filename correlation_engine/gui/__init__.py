"""
Correlation Engine GUI
PyQt5-based graphical interface for the correlation engine.
"""

__version__ = "1.0.0"

# Export main components
from .wing_selection_dialog import WingSelectionDialog, show_wing_selection_dialog
from .timebased_results_viewer import TimeBasedResultsViewer
from .identity_results_view import IdentityResultsView

__all__ = [
    'WingSelectionDialog',
    'show_wing_selection_dialog',
    'TimeBasedResultsViewer',
    'IdentityResultsView',
]

