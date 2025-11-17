"""
Error Handler Utility
=====================

This module provides centralized error handling utilities for the timeline feature,
including user-friendly error messages, logging, and recovery options.

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import logging
import traceback
from typing import Optional, Callable, Any
from PyQt5.QtWidgets import QMessageBox, QPushButton
from PyQt5.QtCore import QObject, pyqtSignal

# Configure logger
logger = logging.getLogger(__name__)


class ErrorSeverity:
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class TimelineError(Exception):
    """Base exception for timeline-related errors."""
    
    def __init__(self, message: str, details: Optional[str] = None, 
                 severity: str = ErrorSeverity.ERROR):
        """
        Initialize timeline error.
        
        Args:
            message: User-friendly error message
            details: Technical details for logging
            severity: Error severity level
        """
        super().__init__(message)
        self.message = message
        self.details = details or message
        self.severity = severity


class DatabaseError(TimelineError):
    """Exception for database-related errors."""
    
    def __init__(self, message: str, db_path: Optional[str] = None, 
                 query: Optional[str] = None, original_error: Optional[Exception] = None,
                 recovery_suggestions: Optional[list] = None):
        """
        Initialize database error.
        
        Args:
            message: User-friendly error message
            db_path: Path to database that caused error
            query: SQL query that failed (if applicable)
            original_error: Original exception that was caught
            recovery_suggestions: List of suggested recovery actions
        """
        details = f"{message}\n"
        if db_path:
            details += f"Database: {db_path}\n"
        if query:
            details += f"Query: {query}\n"
        if original_error:
            details += f"Original error: {str(original_error)}\n"
        
        # Add recovery suggestions
        if recovery_suggestions:
            details += "\nSuggested actions:\n"
            for i, suggestion in enumerate(recovery_suggestions, 1):
                details += f"{i}. {suggestion}\n"
        
        super().__init__(message, details, ErrorSeverity.ERROR)
        self.db_path = db_path
        self.query = query
        self.original_error = original_error
        self.recovery_suggestions = recovery_suggestions or []


class DataLoadError(TimelineError):
    """Exception for data loading errors."""
    pass


class RenderError(TimelineError):
    """Exception for rendering errors."""
    pass


class ErrorHandler(QObject):
    """
    Centralized error handler for timeline feature.
    
    Provides methods for displaying user-friendly error messages,
    logging detailed errors, and offering recovery options.
    
    Signals:
        error_occurred: Emitted when an error is handled (severity, message, details)
    """
    
    error_occurred = pyqtSignal(str, str, str)  # severity, message, details
    
    def __init__(self, parent=None):
        """
        Initialize error handler.
        
        Args:
            parent: Parent widget for message boxes
        """
        super().__init__(parent)
        self.parent = parent
        self._error_count = 0
        self._last_errors = []  # Store last 10 errors
        self._max_stored_errors = 10
    
    def handle_error(self, error: Exception, context: str = "", 
                    show_dialog: bool = True, 
                    recovery_options: Optional[dict] = None) -> Optional[str]:
        """
        Handle an error with logging, user notification, and recovery options.
        
        Args:
            error: The exception that occurred
            context: Context description (e.g., "loading timeline data")
            show_dialog: Whether to show error dialog to user
            recovery_options: Dict of recovery option labels to callback functions
                             e.g., {"Retry": retry_func, "Skip": skip_func}
        
        Returns:
            Optional[str]: Selected recovery option label, or None if no options
        """
        # Increment error count
        self._error_count += 1
        
        # Determine error type and extract information
        if isinstance(error, TimelineError):
            message = error.message
            details = error.details
            severity = error.severity
        else:
            message = f"An unexpected error occurred while {context}" if context else "An unexpected error occurred"
            error_traceback = traceback.format_exc()
            details = f"Context: {context}\n{type(error).__name__}: {str(error)}\n{error_traceback}"
            severity = ErrorSeverity.ERROR
        
        # Log the error
        log_message = f"Error in {context}: {details}" if context else f"Error: {details}"
        
        if severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message)
        elif severity == ErrorSeverity.ERROR:
            logger.error(log_message)
        elif severity == ErrorSeverity.WARNING:
            logger.warning(log_message)
        else:
            logger.info(log_message)
        
        # Store error in history
        self._store_error(severity, message, details)
        
        # Emit signal
        self.error_occurred.emit(severity, message, details)
        
        # Show dialog if requested
        if show_dialog and self.parent:
            return self._show_error_dialog(message, details, severity, recovery_options)
        
        return None
    
    def handle_database_error(self, error: Exception, db_path: str, 
                             operation: str, query: Optional[str] = None,
                             show_dialog: bool = True,
                             recovery_options: Optional[dict] = None) -> Optional[str]:
        """
        Handle a database-specific error.
        
        Args:
            error: The exception that occurred
            db_path: Path to the database
            operation: Description of the operation (e.g., "querying events")
            query: SQL query that failed (optional)
            show_dialog: Whether to show error dialog
            recovery_options: Recovery option callbacks
        
        Returns:
            Optional[str]: Selected recovery option label
        """
        # Create database error
        db_error = DatabaseError(
            message=f"Database error while {operation}",
            db_path=db_path,
            query=query,
            original_error=error
        )
        
        return self.handle_error(db_error, operation, show_dialog, recovery_options)
    
    def _show_error_dialog(self, message: str, details: str, 
                          severity: str, recovery_options: Optional[dict] = None) -> Optional[str]:
        """
        Show error dialog to user with recovery options and error log access.
        
        Args:
            message: User-friendly error message
            details: Technical details
            severity: Error severity level
            recovery_options: Dict of recovery option labels to callbacks
        
        Returns:
            Optional[str]: Selected recovery option label
        """
        # Determine icon based on severity
        if severity == ErrorSeverity.CRITICAL:
            icon = QMessageBox.Critical
            title = "Critical Error"
        elif severity == ErrorSeverity.ERROR:
            icon = QMessageBox.Critical
            title = "Error"
        elif severity == ErrorSeverity.WARNING:
            icon = QMessageBox.Warning
            title = "Warning"
        else:
            icon = QMessageBox.Information
            title = "Information"
        
        # Create message box
        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setDetailedText(details)
        
        # Add recovery options as custom buttons
        selected_option = None
        
        if recovery_options:
            # Add custom buttons for recovery options
            buttons = {}
            for label in recovery_options.keys():
                button = msg_box.addButton(label, QMessageBox.ActionRole)
                buttons[button] = label
            
            # Add "View Error Log" button
            view_log_button = msg_box.addButton("View Error Log", QMessageBox.HelpRole)
            buttons[view_log_button] = "View Error Log"
            
            # Add close button
            close_button = msg_box.addButton(QMessageBox.Close)
            
            # Show dialog and get result
            msg_box.exec_()
            clicked_button = msg_box.clickedButton()
            
            # Determine which option was selected
            if clicked_button in buttons:
                selected_option = buttons[clicked_button]
                
                # Handle "View Error Log" specially
                if selected_option == "View Error Log":
                    self._show_error_log_dialog()
                    # Show the error dialog again after viewing log
                    return self._show_error_dialog(message, details, severity, recovery_options)
        else:
            # Add "View Error Log" button even without recovery options
            view_log_button = msg_box.addButton("View Error Log", QMessageBox.HelpRole)
            ok_button = msg_box.addButton(QMessageBox.Ok)
            
            # Show dialog and get result
            msg_box.exec_()
            clicked_button = msg_box.clickedButton()
            
            # Check if "View Error Log" was clicked
            if clicked_button == view_log_button:
                self._show_error_log_dialog()
                # Show the error dialog again after viewing log
                return self._show_error_dialog(message, details, severity, recovery_options)
        
        return selected_option
    
    def _show_error_log_dialog(self):
        """
        Show a dialog displaying the error log history.
        """
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
        
        # Create dialog
        log_dialog = QDialog(self.parent)
        log_dialog.setWindowTitle("Error Log")
        log_dialog.setMinimumSize(700, 500)
        
        # Create layout
        layout = QVBoxLayout(log_dialog)
        
        # Create text edit for log display
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        
        # Format error log
        if self._last_errors:
            log_content = f"Error Log ({len(self._last_errors)} recent errors)\n"
            log_content += "=" * 80 + "\n\n"
            
            for i, error in enumerate(reversed(self._last_errors), 1):
                timestamp = error['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                severity = error['severity'].upper()
                message = error['message']
                details = error['details']
                
                log_content += f"[{i}] {timestamp} - {severity}\n"
                log_content += f"Message: {message}\n"
                log_content += f"Details:\n{details}\n"
                log_content += "-" * 80 + "\n\n"
        else:
            log_content = "No errors recorded in this session."
        
        log_text.setPlainText(log_content)
        layout.addWidget(log_text)
        
        # Create button layout
        button_layout = QHBoxLayout()
        
        # Add "Copy to Clipboard" button
        copy_button = QPushButton("Copy to Clipboard")
        copy_button.clicked.connect(lambda: self._copy_log_to_clipboard(log_content))
        button_layout.addWidget(copy_button)
        
        # Add "Clear Log" button
        clear_button = QPushButton("Clear Log")
        clear_button.clicked.connect(lambda: self._clear_and_close_log(log_dialog))
        button_layout.addWidget(clear_button)
        
        button_layout.addStretch()
        
        # Add "Close" button
        close_button = QPushButton("Close")
        close_button.clicked.connect(log_dialog.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        log_dialog.exec_()
    
    def _copy_log_to_clipboard(self, log_content: str):
        """
        Copy error log to clipboard.
        
        Args:
            log_content: The log content to copy
        """
        from PyQt5.QtWidgets import QApplication
        
        clipboard = QApplication.clipboard()
        clipboard.setText(log_content)
        
        # Show brief confirmation
        if self.parent:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self.parent, "Copied", "Error log copied to clipboard.")
    
    def _clear_and_close_log(self, dialog):
        """
        Clear error log and close the dialog.
        
        Args:
            dialog: The log dialog to close
        """
        from PyQt5.QtWidgets import QMessageBox
        
        # Confirm clear
        reply = QMessageBox.question(
            self.parent,
            "Clear Error Log",
            "Are you sure you want to clear the error log?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.clear_error_history()
            dialog.accept()
    
    def _store_error(self, severity: str, message: str, details: str):
        """
        Store error in history for later retrieval.
        
        Args:
            severity: Error severity
            message: Error message
            details: Error details
        """
        from datetime import datetime
        
        error_record = {
            'timestamp': datetime.now(),
            'severity': severity,
            'message': message,
            'details': details
        }
        
        self._last_errors.append(error_record)
        
        # Keep only last N errors
        if len(self._last_errors) > self._max_stored_errors:
            self._last_errors = self._last_errors[-self._max_stored_errors:]
    
    def get_error_history(self) -> list:
        """
        Get recent error history.
        
        Returns:
            list: List of error records
        """
        return self._last_errors.copy()
    
    def get_error_count(self) -> int:
        """
        Get total error count.
        
        Returns:
            int: Number of errors handled
        """
        return self._error_count
    
    def clear_error_history(self):
        """Clear error history and reset count."""
        self._last_errors.clear()
        self._error_count = 0
    
    @staticmethod
    def safe_execute(func: Callable, *args, default_return: Any = None, 
                    error_handler: Optional['ErrorHandler'] = None,
                    context: str = "", **kwargs) -> Any:
        """
        Safely execute a function with error handling.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            default_return: Value to return if function fails
            error_handler: ErrorHandler instance to use for handling errors
            context: Context description for error messages
            **kwargs: Keyword arguments for function
        
        Returns:
            Function return value, or default_return if error occurs
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if error_handler:
                error_handler.handle_error(e, context, show_dialog=False)
            else:
                logger.error(f"Error in {context}: {e}")
            return default_return


def create_recovery_options(retry_func: Optional[Callable] = None,
                           skip_func: Optional[Callable] = None,
                           cancel_func: Optional[Callable] = None) -> dict:
    """
    Create a standard set of recovery options.
    
    Args:
        retry_func: Function to call when "Retry" is selected
        skip_func: Function to call when "Skip" is selected
        cancel_func: Function to call when "Cancel" is selected
    
    Returns:
        dict: Recovery options dictionary
    """
    options = {}
    
    if retry_func:
        options["Retry"] = retry_func
    if skip_func:
        options["Skip"] = skip_func
    if cancel_func:
        options["Cancel"] = cancel_func
    
    return options


def create_database_error_with_guidance(operation: str, db_path: str, 
                                        original_error: Exception) -> DatabaseError:
    """
    Create a database error with specific guidance based on the error type.
    
    Args:
        operation: Description of the operation that failed
        db_path: Path to the database
        original_error: The original exception
    
    Returns:
        DatabaseError: Configured database error with recovery suggestions
    """
    import os
    import sqlite3
    
    error_str = str(original_error).lower()
    recovery_suggestions = []
    
    # Determine specific error type and provide guidance
    if "unable to open database" in error_str or "no such file" in error_str:
        message = f"Cannot access database file while {operation}"
        recovery_suggestions = [
            "Verify the database file exists at the specified path",
            "Check that the case was loaded correctly",
            "Ensure the artifact collection completed successfully",
            f"Check file permissions for: {db_path}"
        ]
    
    elif "database is locked" in error_str or "locked" in error_str:
        message = f"Database is locked while {operation}"
        recovery_suggestions = [
            "Close any other applications accessing this database",
            "Wait a moment and try again",
            "Check if another Crow Eye instance is using this case",
            "Restart Crow Eye if the problem persists"
        ]
    
    elif "disk i/o error" in error_str or "i/o" in error_str:
        message = f"Disk I/O error while {operation}"
        recovery_suggestions = [
            "Check available disk space",
            "Verify the storage device is functioning properly",
            "Try copying the case to a different location",
            "Run disk diagnostics on the storage device"
        ]
    
    elif "database disk image is malformed" in error_str or "malformed" in error_str:
        message = f"Database file is corrupted while {operation}"
        recovery_suggestions = [
            "The database file may be corrupted",
            "Try re-running the artifact collection for this type",
            "Check if the original artifact collection completed successfully",
            "Restore from a backup if available"
        ]
    
    elif "permission" in error_str or "access" in error_str:
        message = f"Permission denied while {operation}"
        recovery_suggestions = [
            f"Check file permissions for: {db_path}",
            "Run Crow Eye with appropriate permissions",
            "Verify you have read access to the case directory",
            "Check if the file is marked as read-only"
        ]
    
    elif "no such table" in error_str or "no such column" in error_str:
        message = f"Database schema mismatch while {operation}"
        recovery_suggestions = [
            "The database schema may be outdated or incorrect",
            "Try re-running the artifact collection for this type",
            "Verify you're using a compatible version of Crow Eye",
            "Check if the artifact collection completed successfully"
        ]
    
    else:
        # Generic database error
        message = f"Database error while {operation}"
        recovery_suggestions = [
            f"Check the database file: {db_path}",
            "Verify the database is not corrupted",
            "Try closing and reopening the case",
            "Check the error log for more details"
        ]
    
    # Add database path info
    if os.path.exists(db_path):
        file_size = os.path.getsize(db_path)
        recovery_suggestions.append(f"Database file size: {file_size:,} bytes")
    else:
        recovery_suggestions.append(f"Database file does not exist: {db_path}")
    
    return DatabaseError(
        message=message,
        db_path=db_path,
        original_error=original_error,
        recovery_suggestions=recovery_suggestions
    )


def create_query_error_with_guidance(artifact_type: str, db_path: str,
                                     original_error: Exception,
                                     query: Optional[str] = None) -> DatabaseError:
    """
    Create a query-specific error with guidance.
    
    Args:
        artifact_type: Type of artifact being queried
        db_path: Path to the database
        original_error: The original exception
        query: The SQL query that failed (optional)
    
    Returns:
        DatabaseError: Configured database error with recovery suggestions
    """
    import os
    
    error_str = str(original_error).lower()
    recovery_suggestions = []
    
    message = f"Failed to query {artifact_type} artifacts"
    
    # Provide specific guidance based on error
    if "no such table" in error_str:
        recovery_suggestions = [
            f"The {artifact_type} table does not exist in the database",
            f"Re-run the {artifact_type} artifact collection",
            "Verify the artifact collection completed successfully",
            "Check if this artifact type is supported for your case"
        ]
    
    elif "no such column" in error_str:
        recovery_suggestions = [
            f"The {artifact_type} database schema is incompatible",
            "You may be using an older database format",
            f"Re-run the {artifact_type} artifact collection",
            "Update to the latest version of Crow Eye"
        ]
    
    elif "syntax error" in error_str:
        recovery_suggestions = [
            "There is a SQL syntax error in the query",
            "This may be a bug in Crow Eye",
            "Report this issue with the error log",
            "Try skipping this artifact type for now"
        ]
    
    else:
        recovery_suggestions = [
            f"Check the {artifact_type} database: {db_path}",
            "Verify the database is not corrupted",
            f"Try re-running the {artifact_type} artifact collection",
            "Check the error log for more details"
        ]
    
    # Add database info
    if os.path.exists(db_path):
        file_size = os.path.getsize(db_path)
        recovery_suggestions.append(f"Database: {db_path} ({file_size:,} bytes)")
    else:
        recovery_suggestions.append(f"Database file not found: {db_path}")
    
    return DatabaseError(
        message=message,
        db_path=db_path,
        query=query,
        original_error=original_error,
        recovery_suggestions=recovery_suggestions
    )
