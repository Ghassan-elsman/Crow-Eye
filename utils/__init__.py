"""
Utility functions and helpers for the Crow Eye application.
Includes error handling, file operations, search functionality, and other common utilities.
"""

from .error_handler import ErrorHandler, handle_error, error_decorator, error_context, log_execution
from .file_utils import FileUtils

# SearchUtils and SearchWorker are NOT imported here. search_utils imports
# PyQt5 (SearchWorker is a QThread), and importing it eagerly means that
# `from utils.file_utils import FileUtils` — which the offline parser chain
# does, for one path helper — loads a GUI toolkit into the process. That
# costs fifty megabytes in the spawned parser processes, and on the Sentinel
# endpoint agent it is a headless-service violation outright.
#
# PEP 562: `from utils import SearchUtils` still works, and now pays for Qt
# only when it actually asks for it.
def __getattr__(name):
    if name in ('SearchUtils', 'SearchWorker'):
        from . import search_utils
        return getattr(search_utils, name)
    raise AttributeError('module %r has no attribute %r' % (__name__, name))


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
