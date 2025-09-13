"""
Utility functions and helpers for the Crow Eye application.
Includes error handling, file operations, search functionality, and other common utilities.
"""

from .error_handler import ErrorHandler, handle_error, error_decorator, error_context, log_execution
from .file_utils import FileUtils
from .search_utils import SearchUtils, SearchWorker

__all__ = [
    'ErrorHandler', 
    'handle_error', 
    'error_decorator', 
    'error_context', 
    'log_execution',
    'FileUtils',
    'SearchUtils',
    'SearchWorker'
]
