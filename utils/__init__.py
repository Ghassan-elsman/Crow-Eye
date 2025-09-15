"""
Utility functions and helpers for the Crow Eye application.
Includes error handling, file operations, search functionality, and other common utilities.
"""

from .error_handler import ErrorHandler, handle_error, error_decorator, error_context, log_execution
from .file_utils import FileUtils

# Try to import PyQt5-dependent modules, fallback gracefully if not available
try:
    from .search_utils import SearchUtils, SearchWorker
    _PYQT5_AVAILABLE = True
except ImportError:
    _PYQT5_AVAILABLE = False
    SearchUtils = None
    SearchWorker = None

__all__ = [
    'ErrorHandler', 
    'handle_error', 
    'error_decorator', 
    'error_context', 
    'log_execution',
    'FileUtils'
]

if _PYQT5_AVAILABLE:
    __all__.extend(['SearchUtils', 'SearchWorker'])
