"""
GUI Worker Threads Module

This module provides QThread worker classes for long-running operations in the main Crow Eye GUI.
These workers prevent GUI freezing by moving operations off the main thread.

Classes:
    LiveAcquisitionWorker: Worker for live artifact acquisition operations
    DataLoadingWorker: Worker for data loading operations into GUI tabs
"""

import logging
from typing import Callable, Optional, List, Any
from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class LiveAcquisitionWorker(QThread):
    """
    Worker thread for live artifact acquisition operations.
    
    Bug Fix: Move live_acquisition_with_progress operations to worker thread
    to prevent GUI freezing during artifact collection.
    
    Signals:
        step_update: Emitted when a collection step updates (step_index, step_message)
        log_message: Emitted when a log message should be displayed (message)
        acquisition_complete: Emitted when acquisition finishes successfully (success_message)
        acquisition_error: Emitted if acquisition fails (error_message)
    """
    
    step_update = pyqtSignal(int, str)  # step_index, step_message
    log_message = pyqtSignal(str)  # message
    acquisition_complete = pyqtSignal(str)  # success_message
    acquisition_error = pyqtSignal(str)  # error_message
    
    def __init__(self, 
                 collection_function: Callable,
                 case_paths: dict,
                 windows_partition: Optional[str] = None):
        """
        Initialize the live acquisition worker thread.
        
        Args:
            collection_function: Function that performs the artifact collection
            case_paths: Dictionary containing case_root, artifacts_dir, etc.
            windows_partition: Windows partition path (e.g., "C:")
        """
        super().__init__()
        self.collection_function = collection_function
        self.case_paths = case_paths
        self.windows_partition = windows_partition
        self._cancelled = False
    
    def cancel(self):
        """Request cancellation of the acquisition operation."""
        self._cancelled = True
        logger.info("Live acquisition cancellation requested")
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled
    
    def run(self):
        """Execute live acquisition in background thread."""
        try:
            logger.info("Starting live acquisition worker thread")
            
            # Call the collection function with progress callbacks
            self.collection_function(
                case_paths=self.case_paths,
                windows_partition=self.windows_partition,
                step_callback=self._emit_step_update,
                log_callback=self._emit_log_message,
                cancellation_check=self.is_cancelled
            )
            
            if not self._cancelled:
                self.acquisition_complete.emit("All live artifacts collected successfully")
                logger.info("Live acquisition completed successfully")
            else:
                self.acquisition_error.emit("Acquisition cancelled by user")
                logger.info("Live acquisition cancelled")
                
        except Exception as e:
            error_msg = f"Live acquisition failed: {str(e)}"
            self.acquisition_error.emit(error_msg)
            logger.error(error_msg, exc_info=True)
    
    def _emit_step_update(self, step_index: int, step_message: str):
        """Emit step update signal (called from collection function)."""
        if not self._cancelled:
            self.step_update.emit(step_index, step_message)
    
    def _emit_log_message(self, message: str):
        """Emit log message signal (called from collection function)."""
        if not self._cancelled:
            self.log_message.emit(message)


class DataLoadingWorker(QThread):
    """
    Worker thread for data loading operations into GUI tabs.
    
    Bug Fix: Move data loading operations (load_all_logs, load_data_from_Prefetch,
    load_registry_data_from_db) to worker thread to prevent GUI freezing.
    
    Signals:
        progress_update: Emitted during loading (current, total, data_type)
        loading_complete: Emitted when loading finishes successfully (data_type, loaded_data)
        loading_error: Emitted if loading fails (data_type, error_message)
    """
    
    progress_update = pyqtSignal(int, int, str)  # current, total, data_type
    loading_complete = pyqtSignal(str, object)  # data_type, loaded_data
    loading_error = pyqtSignal(str, str)  # data_type, error_message
    
    def __init__(self,
                 data_type: str,
                 loading_function: Callable,
                 **loading_kwargs):
        """
        Initialize the data loading worker thread.
        
        Args:
            data_type: Type of data being loaded (logs, prefetch, registry, etc.)
            loading_function: Function that performs the data loading
            **loading_kwargs: Additional keyword arguments for loading_function
        """
        super().__init__()
        self.data_type = data_type
        self.loading_function = loading_function
        self.loading_kwargs = loading_kwargs
        self._cancelled = False
    
    def cancel(self):
        """Request cancellation of the loading operation."""
        self._cancelled = True
        logger.info(f"Data loading cancellation requested for {self.data_type}")
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled
    
    def run(self):
        """Execute data loading in background thread."""
        try:
            logger.info(f"Starting data loading worker thread for {self.data_type}")
            
            # Call the loading function with progress callback
            loaded_data = self.loading_function(
                progress_callback=self._emit_progress_update,
                cancellation_check=self.is_cancelled,
                **self.loading_kwargs
            )
            
            if not self._cancelled:
                self.loading_complete.emit(self.data_type, loaded_data)
                logger.info(f"Data loading completed successfully for {self.data_type}")
            else:
                self.loading_error.emit(self.data_type, "Loading cancelled by user")
                logger.info(f"Data loading cancelled for {self.data_type}")
                
        except Exception as e:
            error_msg = f"Data loading failed: {str(e)}"
            self.loading_error.emit(self.data_type, error_msg)
            logger.error(f"Data loading failed for {self.data_type}: {error_msg}", exc_info=True)
    
    def _emit_progress_update(self, current: int, total: int):
        """Emit progress update signal (called from loading function)."""
        if not self._cancelled:
            self.progress_update.emit(current, total, self.data_type)
