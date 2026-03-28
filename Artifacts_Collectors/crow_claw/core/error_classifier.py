"""
Error classification and handling for collection operations.

This module provides centralized error classification to categorize errors
as transient, permanent, or resource-related, and determines appropriate
actions for each error type.
"""

from enum import Enum
from typing import Optional
from dataclasses import dataclass


# Windows error codes
ERROR_SHARING_VIOLATION = 32
ERROR_ACCESS_DENIED = 5
ERROR_NOT_READY = 21
ERROR_BUSY = 170
ERROR_LOCK_VIOLATION = 33
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_PRIVILEGE_NOT_HELD = 1314
ERROR_INVALID_HANDLE = 6
ERROR_DISK_FULL = 112
ERROR_NOT_ENOUGH_MEMORY = 8
ERROR_TOO_MANY_OPEN_FILES = 4


class ErrorCategory(Enum):
    """Categories of errors for collection operations."""
    TRANSIENT = "transient"  # Temporary errors that may succeed on retry
    PERMANENT = "permanent"  # Errors that won't succeed on retry
    RESOURCE = "resource"    # Resource exhaustion errors


class ErrorAction(Enum):
    """Actions to take in response to errors."""
    RETRY = "retry"                    # Retry the same operation
    TRY_VSS = "try_vss"               # Try VSS access method
    TRY_VSS_OR_RETRY = "try_vss_or_retry"  # Try VSS or retry if VSS unavailable
    SKIP_WITH_MESSAGE = "skip_with_message"  # Skip and record error
    ABORT_COLLECTION = "abort_collection"    # Stop entire collection


@dataclass
class ErrorClassification:
    """Result of error classification.
    
    Attributes:
        category: The error category (transient, permanent, resource)
        action: Recommended action to take
        message: Human-readable error message
        is_retryable: Whether the error should be retried
        requires_vss: Whether VSS access should be attempted
    """
    category: ErrorCategory
    action: ErrorAction
    message: str
    is_retryable: bool = False
    requires_vss: bool = False


class ErrorClassifier:
    """Classifies errors and determines appropriate handling actions.
    
    Categorizes errors into transient, permanent, and resource errors,
    and provides recommendations for how to handle each error type.
    """
    
    def __init__(self, is_admin: bool = False):
        """Initialize the error classifier.
        
        Args:
            is_admin: Whether the process has administrator privileges
        """
        self.is_admin = is_admin
    
    def classify_error(self, error: Exception, context: Optional[dict] = None) -> ErrorClassification:
        """Classify an error and determine the appropriate action.
        
        Args:
            error: The exception to classify
            context: Optional context dictionary with additional information
                    (e.g., 'file_path', 'artifact_type', 'attempt_number')
        
        Returns:
            ErrorClassification with category and recommended action
        """
        context = context or {}
        
        # Handle PermissionError
        if isinstance(error, PermissionError):
            return self._classify_permission_error(error, context)
        
        # Handle OSError with Windows error codes
        if isinstance(error, OSError):
            return self._classify_os_error(error, context)
        
        # Handle FileNotFoundError
        if isinstance(error, FileNotFoundError):
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                action=ErrorAction.SKIP_WITH_MESSAGE,
                message=f"File not found: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        # Handle MemoryError
        if isinstance(error, MemoryError):
            return ErrorClassification(
                category=ErrorCategory.RESOURCE,
                action=ErrorAction.ABORT_COLLECTION,
                message="Out of memory - aborting collection",
                is_retryable=False,
                requires_vss=False
            )
        
        # Unknown error - treat as permanent
        return ErrorClassification(
            category=ErrorCategory.PERMANENT,
            action=ErrorAction.SKIP_WITH_MESSAGE,
            message=f"Unknown error: {error}",
            is_retryable=False,
            requires_vss=False
        )
    
    def _classify_permission_error(self, error: PermissionError, context: dict) -> ErrorClassification:
        """Classify a PermissionError.
        
        Args:
            error: The PermissionError to classify
            context: Context dictionary
        
        Returns:
            ErrorClassification for the permission error
        """
        error_msg = str(error).lower()
        
        # Check if it's a lock-related permission error (transient)
        if any(keyword in error_msg for keyword in ['being used', 'another process', 'sharing']):
            if self.is_admin:
                return ErrorClassification(
                    category=ErrorCategory.TRANSIENT,
                    action=ErrorAction.TRY_VSS_OR_RETRY,
                    message=f"File locked by another process: {error}",
                    is_retryable=True,
                    requires_vss=True
                )
            else:
                return ErrorClassification(
                    category=ErrorCategory.TRANSIENT,
                    action=ErrorAction.RETRY,
                    message=f"File locked by another process: {error}",
                    is_retryable=True,
                    requires_vss=False
                )
        
        # Permanent permission error (insufficient privileges)
        if self.is_admin:
            # Admin but still permission error - try VSS
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                action=ErrorAction.TRY_VSS,
                message=f"Permission denied (trying VSS): {error}",
                is_retryable=False,
                requires_vss=True
            )
        else:
            # Not admin - skip with message
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                action=ErrorAction.SKIP_WITH_MESSAGE,
                message=f"Permission denied (requires admin privileges): {error}",
                is_retryable=False,
                requires_vss=False
            )
    
    def _classify_os_error(self, error: OSError, context: dict) -> ErrorClassification:
        """Classify an OSError based on Windows error code.
        
        Args:
            error: The OSError to classify
            context: Context dictionary
        
        Returns:
            ErrorClassification for the OS error
        """
        # Check for Windows error code
        error_code = getattr(error, 'winerror', None)
        
        if error_code is None:
            # No Windows error code - check message
            return self._classify_os_error_by_message(error, context)
        
        # Transient errors
        if error_code == ERROR_SHARING_VIOLATION:
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                action=ErrorAction.TRY_VSS if self.is_admin else ErrorAction.RETRY,
                message=f"Sharing violation (file locked): {error}",
                is_retryable=True,
                requires_vss=self.is_admin
            )
        
        # Access denied - could be transient or permanent
        if error_code == ERROR_ACCESS_DENIED:
            error_msg = str(error).lower()
            # On Windows, locked system files often return ERROR_ACCESS_DENIED (5) 
            # instead of ERROR_SHARING_VIOLATION (32)
            if any(keyword in error_msg for keyword in ['being used', 'another process', 'sharing', 'access is denied']):
                # Treat as transient lock that requires VSS
                return ErrorClassification(
                    category=ErrorCategory.TRANSIENT,
                    action=ErrorAction.TRY_VSS if self.is_admin else ErrorAction.RETRY,
                    message=f"Access denied (file likely locked): {error}",
                    is_retryable=True,
                    requires_vss=self.is_admin
                )
        
        # Permanent errors
        if error_code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                action=ErrorAction.SKIP_WITH_MESSAGE,
                message=f"File or path not found: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        if error_code == ERROR_PRIVILEGE_NOT_HELD:
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                action=ErrorAction.SKIP_WITH_MESSAGE,
                message=f"Insufficient privileges: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        if error_code == ERROR_INVALID_HANDLE:
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                action=ErrorAction.SKIP_WITH_MESSAGE,
                message=f"Invalid handle: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        # Resource errors
        if error_code == ERROR_DISK_FULL:
            return ErrorClassification(
                category=ErrorCategory.RESOURCE,
                action=ErrorAction.ABORT_COLLECTION,
                message=f"Disk full - aborting collection: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        if error_code == ERROR_NOT_ENOUGH_MEMORY:
            return ErrorClassification(
                category=ErrorCategory.RESOURCE,
                action=ErrorAction.ABORT_COLLECTION,
                message=f"Out of memory - aborting collection: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        if error_code == ERROR_TOO_MANY_OPEN_FILES:
            return ErrorClassification(
                category=ErrorCategory.RESOURCE,
                action=ErrorAction.ABORT_COLLECTION,
                message=f"Too many open files - aborting collection: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        # Unknown error code - check message
        return self._classify_os_error_by_message(error, context)
    
    def _classify_os_error_by_message(self, error: OSError, context: dict) -> ErrorClassification:
        """Classify an OSError by examining the error message.
        
        Args:
            error: The OSError to classify
            context: Context dictionary
        
        Returns:
            ErrorClassification based on message content
        """
        error_msg = str(error).lower()
        
        # Check for transient keywords
        transient_keywords = [
            'sharing violation',
            'being used by another process',
            'device not ready',
            'busy',
            'temporarily unavailable',
            'lock violation',
            'retry'
        ]
        
        if any(keyword in error_msg for keyword in transient_keywords):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                action=ErrorAction.TRY_VSS_OR_RETRY if self.is_admin else ErrorAction.RETRY,
                message=f"Transient error: {error}",
                is_retryable=True,
                requires_vss=self.is_admin
            )
        
        # Check for resource keywords
        resource_keywords = [
            'disk full',
            'out of memory',
            'no space left',
            'too many open files'
        ]
        
        if any(keyword in error_msg for keyword in resource_keywords):
            return ErrorClassification(
                category=ErrorCategory.RESOURCE,
                action=ErrorAction.ABORT_COLLECTION,
                message=f"Resource error: {error}",
                is_retryable=False,
                requires_vss=False
            )
        
        # Default to permanent error
        return ErrorClassification(
            category=ErrorCategory.PERMANENT,
            action=ErrorAction.SKIP_WITH_MESSAGE,
            message=f"Permanent error: {error}",
            is_retryable=False,
            requires_vss=False
        )


def handle_collection_error(
    error: Exception,
    context: Optional[dict] = None,
    is_admin: bool = False
) -> ErrorClassification:
    """Determine appropriate action for a collection error.
    
    This is a convenience function that creates an ErrorClassifier and
    classifies the error in one step.
    
    Args:
        error: The exception to handle
        context: Optional context dictionary with additional information
        is_admin: Whether the process has administrator privileges
    
    Returns:
        ErrorClassification with category and recommended action
    
    Examples:
        >>> try:
        ...     with open("locked_file.txt", "r") as f:
        ...         pass
        ... except Exception as e:
        ...     classification = handle_collection_error(e, is_admin=True)
        ...     if classification.action == ErrorAction.TRY_VSS:
        ...         print("Should try VSS access")
    """
    classifier = ErrorClassifier(is_admin=is_admin)
    return classifier.classify_error(error, context)
