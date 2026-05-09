"""
File accessor orchestrator with retry logic.

This module provides the FileAccessor class that orchestrates multiple
file access strategies with automatic retry for transient failures.
"""

import os
import time
from typing import List, Optional
from .access_strategy import FileAccessStrategy
from .access_result import AccessResult
from .lock_detection import classify_error_as_transient, get_lock_info
from .error_classifier import ErrorClassifier, ErrorAction


# Windows error codes for transient errors
ERROR_SHARING_VIOLATION = 32
ERROR_ACCESS_DENIED = 5
ERROR_NOT_READY = 21
ERROR_BUSY = 170


class FileAccessor:
    """Orchestrates file access strategies with retry logic.
    
    Manages multiple file access strategies and attempts them in priority order.
    Implements retry logic for transient errors like sharing violations.
    
    Attributes:
        strategies: List of available file access strategies
        is_admin: Whether the current process has admin privileges
    """
    
    def __init__(self, is_admin: bool):
        """Initialize the file accessor.
        
        Args:
            is_admin: Whether the process has administrator privileges
        """
        self.strategies: List[FileAccessStrategy] = []
        self.is_admin = is_admin
        self.error_classifier = ErrorClassifier(is_admin=is_admin)
        self._initialize_strategies()
    
    def _report_progress(self, message: str):
        """Report progress message (for debugging)."""
        print(message)
    
    def _initialize_strategies(self):
        """Initialize strategies based on privilege level.
        
        Standard copy strategy is always available. VSS and raw disk access
        strategies are only added if admin privileges are detected.
        Image access strategies are always available for forensic image formats.
        """
        import importlib.util
        import os
        import sys
        from .standard_copy_strategy import StandardCopyStrategy
        from .vss_access_strategy import VSSAccessStrategy
        from .raw_disk_access_strategy import RawDiskAccessStrategy
        
        # Always add standard copy strategy
        self.strategies.append(StandardCopyStrategy())
        
        # Add advanced strategies if admin
        if self.is_admin:
            # VSS strategy will enumerate shadow copies lazily when needed
            # Don't enumerate during init - it may fail if no snapshots exist yet
            # VSS can still create snapshots on-demand during access_file()
            self.strategies.append(VSSAccessStrategy())
            self.strategies.append(RawDiskAccessStrategy())
        
        # Add image access strategies (always available, don't require admin)
        # Import with try/except to handle missing dependencies gracefully
        # Use importlib to handle directory name with spaces
        
        # Get the path to Artifacts_Collectors directory
        artifacts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        forensics_dir = os.path.join(artifacts_dir, 'Forensics_Image_parsing', 'strategies')
        
        # Add to sys.path temporarily if needed
        if artifacts_dir not in sys.path:
            sys.path.insert(0, artifacts_dir)
        
        try:
            # Import E01AccessStrategy
            spec = importlib.util.spec_from_file_location(
                "e01_access_strategy",
                os.path.join(forensics_dir, "e01_access_strategy.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.strategies.append(module.E01AccessStrategy())
        except Exception as e:
            print(f"[WARNING] E01AccessStrategy not available: {e}")
        
        try:
            # Import VHDXAccessStrategy
            spec = importlib.util.spec_from_file_location(
                "vhdx_access_strategy",
                os.path.join(forensics_dir, "vhdx_access_strategy.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.strategies.append(module.VHDXAccessStrategy())
        except Exception as e:
            print(f"[WARNING] VHDXAccessStrategy not available: {e}")
        
        try:
            # Import VMDKAccessStrategy
            spec = importlib.util.spec_from_file_location(
                "vmdk_access_strategy",
                os.path.join(forensics_dir, "vmdk_access_strategy.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.strategies.append(module.VMDKAccessStrategy())
        except Exception as e:
            print(f"[WARNING] VMDKAccessStrategy not available: {e}")
        
        try:
            # Import ISOAccessStrategy
            spec = importlib.util.spec_from_file_location(
                "iso_access_strategy",
                os.path.join(forensics_dir, "iso_access_strategy.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.strategies.append(module.ISOAccessStrategy())
        except Exception as e:
            print(f"[WARNING] ISOAccessStrategy not available: {e}")
        
        try:
            # Import RawAccessStrategy
            spec = importlib.util.spec_from_file_location(
                "raw_access_strategy",
                os.path.join(forensics_dir, "raw_access_strategy.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.strategies.append(module.RawAccessStrategy())
        except Exception as e:
            print(f"[WARNING] RawAccessStrategy not available: {e}")
    
    def access_file_with_retry(
        self,
        file_path: str,
        dest_path: str,
        artifact_type: str,
        max_retries: int = 3
    ) -> AccessResult:
        """Try all strategies with retry logic for transient errors.
        
        Attempts each available strategy in order. For transient errors,
        retries up to max_retries times with a 1-second delay between attempts.
        Uses ErrorClassifier to make intelligent fallback decisions.
        
        For locked files (WinError 32), immediately tries VSS/Raw Disk access
        instead of retrying standard copy.
        
        Args:
            file_path: Source file path to access
            dest_path: Destination path for the copied file
            artifact_type: Type of artifact being collected
            max_retries: Maximum number of retry attempts (default: 3)
            
        Returns:
            AccessResult with success status and all attempt details
        """
        attempts = []
        last_error = None
        locked_file_detected = False
        
        # DEBUG: Log file access attempt and available strategies
        self._report_progress(f"[FILE_ACCESSOR] access_file_with_retry: file_path={file_path}, artifact_type={artifact_type}")
        self._report_progress(f"[FILE_ACCESSOR] Total strategies available: {len(self.strategies)}")
        for idx, strategy in enumerate(self.strategies):
            strategy_name = strategy.__class__.__name__
            can_handle = strategy.can_handle(file_path, artifact_type)
            self._report_progress(f"[FILE_ACCESSOR] Strategy {idx+1}: {strategy_name}, can_handle={can_handle}")
        
        for strategy in self.strategies:
            if not strategy.can_handle(file_path, artifact_type):
                continue
            
            strategy_name = strategy.__class__.__name__
            self._report_progress(f"[FILE_ACCESSOR] Attempting strategy: {strategy_name}")
            
            # Skip standard copy if we already detected a locked file
            if locked_file_detected and strategy_name == "StandardCopyStrategy":
                self._report_progress(f"[FILE_ACCESSOR] Skipping {strategy_name} due to locked file detection")
                continue
            
            for attempt in range(max_retries):
                try:
                    self._report_progress(f"[FILE_ACCESSOR] {strategy_name} attempt {attempt+1}/{max_retries}")
                    result = strategy.access_file(file_path, dest_path)
                    attempts.append(result)
                    
                    if result.success:
                        self._report_progress(f"[FILE_ACCESSOR] {strategy_name} SUCCESS")
                        result.attempts = attempts
                        return result
                    
                    self._report_progress(f"[FILE_ACCESSOR] {strategy_name} FAILED: {result.error}")
                    
                    # Use ErrorClassifier to determine if we should retry
                    if result.error:
                        last_error = result.error
                        classification = self._classify_error_from_message(
                            result.error,
                            {"file_path": file_path, "artifact_type": artifact_type}
                        )
                        
                        # Detect locked file errors (WinError 32 or WinError 5 with usage keywords)
                        error_lower = result.error.lower()
                        is_locked = "winerror 32" in error_lower or \
                                    "being used by another process" in error_lower or \
                                    "lock violation" in error_lower
                        
                        is_access_denied = "winerror 5" in error_lower or \
                                          "access is denied" in error_lower or \
                                          "permission denied" in error_lower
                        
                        if is_locked or is_access_denied:
                            locked_file_detected = True
                            self._report_progress(f"[FILE_ACCESSOR] Locked or Access Denied detected, breaking retry loop")
                            # If we hit a lock or access denied, immediately break this strategy's retry loop
                            # and let the outer strategy loop move to the next strategy (VSS/Raw)
                            break
                        
                        # Check if error is retryable
                        if not classification.is_retryable:
                            self._report_progress(f"[FILE_ACCESSOR] Error not retryable, breaking retry loop")
                            break  # Don't retry non-transient errors
                    
                    if attempt < max_retries - 1:  # Don't sleep after last attempt
                        time.sleep(1)  # Wait before retry
                        
                except Exception as e:
                    # Handle unexpected exceptions during strategy execution
                    error_msg = f"Unexpected error in {strategy_name}: {str(e)}"
                    self._report_progress(f"[FILE_ACCESSOR] EXCEPTION: {error_msg}")
                    attempts.append(AccessResult(
                        success=False,
                        source_path=file_path,
                        dest_path=dest_path,
                        strategy_used=strategy_name,
                        error=error_msg,
                        status="failed"
                    ))
                    last_error = error_msg
                    
                    # Classify the exception
                    classification = self.error_classifier.classify_error(
                        e,
                        {"file_path": file_path, "artifact_type": artifact_type}
                    )
                    
                    # If it's a resource error, abort immediately
                    if classification.action == ErrorAction.ABORT_COLLECTION:
                        self._report_progress(f"[FILE_ACCESSOR] ABORT_COLLECTION action, stopping")
                        return self._create_final_error_result(
                            file_path,
                            dest_path,
                            attempts,
                            classification.message
                        )
                    
                    # Don't retry non-transient errors
                    if not classification.is_retryable:
                        break
        
        # All strategies failed - create actionable error message
        self._report_progress(f"[FILE_ACCESSOR] All strategies failed for {file_path}")
        final_error = self._create_actionable_error_message(
            file_path,
            artifact_type,
            attempts,
            last_error
        )
        
        return self._create_final_error_result(
            file_path,
            dest_path,
            attempts,
            final_error
        )
    
    def _is_transient_error(self, error: str) -> bool:
        """Determine if an error is transient and should be retried.
        
        Uses keyword-based detection to identify transient errors from
        error messages. Transient errors include:
        - Sharing violations (file locked by another process)
        - Temporary access denied
        - Device not ready
        - System busy
        
        Args:
            error: Error message or description
            
        Returns:
            True if the error is transient and retry-able
        """
        if not error:
            return False
        
        # Use keyword-based detection for error messages
        error_lower = error.lower()
        transient_keywords = [
            'sharing violation',
            'being used by another process',
            'device not ready',
            'busy',
            'temporarily unavailable',
            'lock violation',
            'retry'
        ]
        
        return any(keyword in error_lower for keyword in transient_keywords)
    
    def _classify_error_from_message(self, error_msg: str, context: dict):
        """Classify an error from an error message string.
        
        Args:
            error_msg: Error message string
            context: Context dictionary with file_path, artifact_type, etc.
            
        Returns:
            ErrorClassification object
        """
        # Try to reconstruct an exception from the error message
        # This is a best-effort approach for error messages
        if "permission denied" in error_msg.lower():
            return self.error_classifier.classify_error(
                PermissionError(error_msg),
                context
            )
        elif "file not found" in error_msg.lower():
            return self.error_classifier.classify_error(
                FileNotFoundError(error_msg),
                context
            )
        elif any(keyword in error_msg.lower() for keyword in ['sharing violation', 'locked', 'being used']):
            # Create an OSError with sharing violation code
            error = OSError(error_msg)
            if os.name == 'nt':
                error.winerror = ERROR_SHARING_VIOLATION
            return self.error_classifier.classify_error(error, context)
        else:
            # Generic OSError
            return self.error_classifier.classify_error(
                OSError(error_msg),
                context
            )
    
    def _create_actionable_error_message(
        self,
        file_path: str,
        artifact_type: str,
        attempts: List[AccessResult],
        last_error: Optional[str]
    ) -> str:
        """Create an actionable error message that tells the user what to do.
        
        Args:
            file_path: The file that failed to be accessed
            artifact_type: Type of artifact
            attempts: List of all access attempts
            last_error: The last error message encountered
            
        Returns:
            Actionable error message with specific guidance
        """
        # Build a detailed error message
        error_parts = [f"Failed to collect '{file_path}'"]
        
        # Add information about what was tried
        if attempts:
            strategies_tried = [a.strategy_used for a in attempts if a.strategy_used]
            if strategies_tried:
                error_parts.append(f"Tried {len(attempts)} attempt(s) using: {', '.join(set(strategies_tried))}")
        
        # Add the last error
        if last_error:
            error_parts.append(f"Last error: {last_error}")
        
        # Provide actionable guidance based on the error
        if last_error:
            error_lower = last_error.lower()
            
            if "permission denied" in error_lower or "access denied" in error_lower:
                if not self.is_admin:
                    error_parts.append("ACTION REQUIRED: Run Crow-Claw as Administrator to access this file")
                else:
                    error_parts.append("ACTION REQUIRED: File may be locked by another process. Try closing applications that might be using this file")
            
            elif "sharing violation" in error_lower or "being used" in error_lower or "locked" in error_lower:
                error_parts.append("ACTION REQUIRED: File is locked by another process")
                
                # Check if VSS was attempted
                vss_attempted = any("VSS" in a.strategy_used for a in attempts if a.strategy_used)
                
                # Try to get lock info
                try:
                    lock_info = get_lock_info(file_path, OSError("File locked"))
                    if lock_info and lock_info.process_name:
                        error_parts.append(f"Locked by: {lock_info.process_name} (PID: {getattr(lock_info, 'process_id', 'unknown')})")
                        error_parts.append(f"Try closing {lock_info.process_name} and retry collection")
                except Exception:
                    pass
                
                if self.is_admin and not vss_attempted:
                    error_parts.append("TIP: VSS (Volume Shadow Copy) may help access locked files. Ensure VSS is enabled on this system")
                elif self.is_admin and vss_attempted:
                    error_parts.append("NOTE: VSS access was attempted but no shadow copies are available. Enable VSS with 'vssadmin create shadow /for=C:' or close the locking process")
                elif not self.is_admin:
                    error_parts.append("TIP: Running as Administrator enables VSS access for locked files")
            
            elif "file not found" in error_lower or "path not found" in error_lower:
                error_parts.append("ACTION REQUIRED: Verify the file path exists on this system")
                error_parts.append(f"This artifact may not be present on this Windows version")
            
            elif "disk full" in error_lower or "no space" in error_lower:
                error_parts.append("ACTION REQUIRED: Free up disk space on the destination drive and retry")
            
            elif "memory" in error_lower:
                error_parts.append("ACTION REQUIRED: Close other applications to free up memory and retry")
            
            else:
                # Generic guidance
                error_parts.append("TIP: Check that the file exists and is accessible")
                if not self.is_admin:
                    error_parts.append("TIP: Running as Administrator may help access protected files")
        
        return " | ".join(error_parts)
    
    def _create_final_error_result(
        self,
        file_path: str,
        dest_path: str,
        attempts: List[AccessResult],
        error_message: str
    ) -> AccessResult:
        """Create the final error result with all attempt details.
        
        Args:
            file_path: Source file path
            dest_path: Destination file path
            attempts: List of all attempts
            error_message: Final error message
            
        Returns:
            AccessResult with failure status and detailed information
        """
        return AccessResult(
            success=False,
            source_path=file_path,
            dest_path=dest_path,
            error=error_message,
            attempts=attempts,
            status="failed"
        )
