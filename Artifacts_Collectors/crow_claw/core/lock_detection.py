"""
Lock detection and process identification utilities.

This module provides utilities for detecting file locks, identifying locking
processes, and classifying transient errors for retry logic.
"""

import os
from typing import Optional, Tuple
from dataclasses import dataclass


# Windows error codes
ERROR_SHARING_VIOLATION = 32
ERROR_ACCESS_DENIED = 5
ERROR_NOT_READY = 21
ERROR_BUSY = 170
ERROR_LOCK_VIOLATION = 33


@dataclass
class LockInfo:
    """Information about a file lock.
    
    Attributes:
        is_locked: Whether the file is locked
        process_name: Name of the process holding the lock (if available)
        process_id: PID of the process holding the lock (if available)
        error_code: Windows error code that indicated the lock
        error_message: Human-readable error message
    """
    is_locked: bool
    process_name: Optional[str] = None
    process_id: Optional[int] = None
    error_code: Optional[int] = None
    error_message: Optional[str] = None


def detect_file_lock(exception: Exception) -> bool:
    """Detect if an exception indicates a file is locked.
    
    Analyzes PermissionError and OSError exceptions to determine if they
    indicate a file lock condition (sharing violation, access denied due to
    another process, etc.).
    
    Args:
        exception: The exception to analyze
        
    Returns:
        True if the exception indicates a file lock, False otherwise
        
    Examples:
        >>> try:
        ...     with open("locked_file.txt", "r") as f:
        ...         pass
        ... except PermissionError as e:
        ...     if detect_file_lock(e):
        ...         print("File is locked")
    """
    if isinstance(exception, PermissionError):
        # PermissionError often indicates a lock
        return True
    
    if isinstance(exception, OSError):
        # Check for specific Windows error codes
        if hasattr(exception, 'winerror'):
            error_code = exception.winerror
            # Sharing violation, lock violation, or access denied
            if error_code in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION, ERROR_ACCESS_DENIED):
                return True
        
        # Check error message for lock-related keywords
        error_msg = str(exception).lower()
        lock_keywords = [
            'sharing violation',
            'being used by another process',
            'cannot access',
            'permission denied',
            'access is denied'
        ]
        return any(keyword in error_msg for keyword in lock_keywords)
    
    return False


def get_locking_process(file_path: str) -> Tuple[Optional[str], Optional[int]]:
    """Identify the process that has a file locked.
    
    Uses psutil (if available) or win32process to identify which process
    has the file open. Returns the process name and PID if found.
    
    Args:
        file_path: Path to the locked file
        
    Returns:
        Tuple of (process_name, process_id) or (None, None) if not found
        
    Examples:
        >>> name, pid = get_locking_process("C:\\Windows\\System32\\config\\SYSTEM")
        >>> if name:
        ...     print(f"File locked by {name} (PID: {pid})")
    """
    try:
        import psutil
        
        # Normalize the file path for comparison
        normalized_path = os.path.normpath(file_path).lower()
        
        # Iterate through all processes
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Get open files for this process
                open_files = proc.open_files()
                for open_file in open_files:
                    if os.path.normpath(open_file.path).lower() == normalized_path:
                        return proc.info['name'], proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                # Process may have terminated or we don't have permission
                continue
            except Exception:
                # Catch any other exceptions (like access violations)
                # and continue to next process
                continue
                
    except ImportError:
        # psutil not available, try win32process
        try:
            import win32process
            import win32api
            import win32con
            import pywintypes
            
            # This is a more complex approach using Windows API
            # For now, we'll return None if psutil is not available
            # A full implementation would use NtQuerySystemInformation
            # or similar low-level APIs
            pass
            
        except ImportError:
            # Neither psutil nor win32process available
            pass
    except Exception:
        # Catch any unexpected exceptions at the top level
        pass
    
    return None, None


def classify_error_as_transient(exception: Exception) -> bool:
    """Classify an error as transient (retry-able) or permanent.
    
    Transient errors include:
    - Sharing violations (file temporarily locked)
    - Temporary access denied (may succeed on retry)
    - Device not ready (removable media, network issues)
    - System busy
    
    Permanent errors include:
    - File not found
    - Path not found
    - Invalid handle
    - Insufficient privileges (when running as admin)
    
    Args:
        exception: The exception to classify
        
    Returns:
        True if the error is transient and should be retried
        
    Examples:
        >>> try:
        ...     with open("file.txt", "r") as f:
        ...         pass
        ... except OSError as e:
        ...     if classify_error_as_transient(e):
        ...         print("Will retry")
    """
    if isinstance(exception, (FileNotFoundError, IsADirectoryError, NotADirectoryError)):
        # These are permanent errors
        return False
    
    if isinstance(exception, OSError):
        if hasattr(exception, 'winerror'):
            error_code = exception.winerror
            
            # Transient error codes
            transient_codes = [
                ERROR_SHARING_VIOLATION,  # 32 - File is locked
                ERROR_LOCK_VIOLATION,      # 33 - Lock violation
                ERROR_NOT_READY,           # 21 - Device not ready
                ERROR_BUSY,                # 170 - System busy
            ]
            
            if error_code in transient_codes:
                return True
            
            # Access denied might be transient if file is temporarily locked
            # but could also be a permanent permission issue
            if error_code == ERROR_ACCESS_DENIED:
                # Check if it's likely a lock vs. a permission issue
                error_msg = str(exception).lower()
                if any(keyword in error_msg for keyword in ['being used', 'another process', 'sharing']):
                    return True
                # Otherwise treat as permanent (insufficient privileges)
                return False
        
        # Check error message for transient keywords
        error_msg = str(exception).lower()
        transient_keywords = [
            'sharing violation',
            'being used by another process',
            'device not ready',
            'busy',
            'temporarily unavailable',
            'retry'
        ]
        
        if any(keyword in error_msg for keyword in transient_keywords):
            return True
    
    if isinstance(exception, PermissionError):
        # PermissionError might be transient if it's a lock
        error_msg = str(exception).lower()
        if any(keyword in error_msg for keyword in ['being used', 'another process', 'sharing']):
            return True
        # Otherwise it's likely a permanent permission issue
        return False
    
    # Unknown error type - don't retry by default
    return False


def get_lock_info(file_path: str, exception: Exception) -> LockInfo:
    """Get comprehensive information about a file lock.
    
    Combines lock detection, process identification, and error classification
    into a single LockInfo object.
    
    Args:
        file_path: Path to the file
        exception: The exception that occurred when accessing the file
        
    Returns:
        LockInfo object with all available information
        
    Examples:
        >>> try:
        ...     with open("locked.txt", "r") as f:
        ...         pass
        ... except Exception as e:
        ...     info = get_lock_info("locked.txt", e)
        ...     if info.is_locked:
        ...         print(f"Locked by {info.process_name}")
    """
    is_locked = detect_file_lock(exception)
    
    process_name = None
    process_id = None
    if is_locked:
        process_name, process_id = get_locking_process(file_path)
    
    error_code = None
    if isinstance(exception, OSError) and hasattr(exception, 'winerror'):
        error_code = exception.winerror
    
    return LockInfo(
        is_locked=is_locked,
        process_name=process_name,
        process_id=process_id,
        error_code=error_code,
        error_message=str(exception)
    )
