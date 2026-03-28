"""
Standard file copy strategy implementation.

This module implements the StandardCopyStrategy which uses standard file
system operations to copy files. It opens files with sharing flags to
minimize locking and properly handles exceptions.
"""

import os
import shutil
import time
from typing import TYPE_CHECKING

from .access_strategy import FileAccessStrategy

if TYPE_CHECKING:
    from .access_result import AccessResult


class StandardCopyStrategy(FileAccessStrategy):
    """Standard file copy strategy using shutil.copy2.
    
    This strategy attempts to copy files using standard file system operations.
    It opens files with FILE_SHARE_READ and FILE_SHARE_WRITE flags to minimize
    additional locking. This is the fastest method and should be tried first
    for unlocked files.
    
    Requirements:
        - 12.1: Use FILE_SHARE_READ | FILE_SHARE_WRITE flags
        - 12.2: Immediately close file handles after operations
    """
    
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        """Check if this strategy can handle the file.
        
        Checks if the file exists and is readable using standard file access.
        
        Args:
            file_path: Path to the file to access
            artifact_type: Type of artifact (not used for standard copy)
            
        Returns:
            True if file exists and has read access
        """
        return os.path.exists(file_path) and os.access(file_path, os.R_OK)
    
    def access_file(self, file_path: str, dest_path: str) -> 'AccessResult':
        """Attempt to access and copy the file using standard copy.
        
        Uses shutil.copy2 to preserve metadata. Opens files with sharing flags
        to minimize locking. Properly handles exceptions and ensures file
        handles are closed.
        
        Args:
            file_path: Source file path
            dest_path: Destination file path
            
        Returns:
            AccessResult containing success status, file size, and any errors
        """
        from .access_result import AccessResult
        
        start_time = time.time()
        
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
            
            # Copy file with metadata preservation
            # shutil.copy2 internally handles file opening/closing properly
            # On Windows, it uses FILE_SHARE_READ | FILE_SHARE_WRITE by default
            shutil.copy2(file_path, dest_path)
            
            # Get file size after successful copy
            file_size = os.path.getsize(dest_path)
            
            duration = time.time() - start_time
            
            return AccessResult(
                success=True,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="standard",
                file_size=file_size,
                duration_seconds=duration,
                status="success"
            )
            
        except PermissionError as e:
            # File is locked or insufficient permissions
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="standard",
                error=f"Permission denied: {str(e)}",
                duration_seconds=duration,
                status="failed"
            )
            
        except OSError as e:
            # Other OS errors (file not found, disk full, etc.)
            duration = time.time() - start_time
            error_msg = f"OS error: {str(e)}"
            
            # Add more specific error information if available
            if hasattr(e, 'winerror'):
                error_msg = f"OS error (code {e.winerror}): {str(e)}"
            
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="standard",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
            
        except Exception as e:
            # Catch-all for unexpected errors
            duration = time.time() - start_time
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="standard",
                error=f"Unexpected error: {str(e)}",
                duration_seconds=duration,
                status="failed"
            )
    
    def requires_admin(self) -> bool:
        """Check if this strategy requires administrator privileges.
        
        Standard file copy does not require admin privileges.
        
        Returns:
            False - standard copy works with normal user privileges
        """
        return False
