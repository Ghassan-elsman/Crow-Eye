"""
Error Handler for Forensic Image Parsing

This module provides centralized error handling for forensic image parsing operations.
It classifies errors, determines retry strategies, and generates user-friendly error messages.
"""

import logging
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass


class ErrorCategory(Enum):
    """Categories of errors that can occur during forensic image parsing."""
    IMAGE_FORMAT = "image_format"
    PARTITION_ACCESS = "partition_access"
    FILE_SYSTEM = "file_system"
    ARTIFACT_EXTRACTION = "artifact_extraction"
    INTEGRITY_VERIFICATION = "integrity_verification"
    UNKNOWN = "unknown"


class ErrorType(Enum):
    """Types of errors based on recoverability."""
    TRANSIENT = "transient"  # Temporary failures that may succeed on retry
    PERMANENT = "permanent"  # Failures that will not succeed on retry
    CRITICAL = "critical"    # Failures that require immediate abort


@dataclass
class ErrorClassification:
    """
    Classification of an error.
    
    Attributes:
        error_type: Type of error (transient, permanent, critical)
        category: Category of error (image format, partition access, etc.)
        message: Original error message
        user_message: User-friendly error message with actionable guidance
        should_retry: Whether the operation should be retried
        should_abort: Whether the entire operation should be aborted
    """
    error_type: ErrorType
    category: ErrorCategory
    message: str
    user_message: str
    should_retry: bool = False
    should_abort: bool = False


class ErrorHandler:
    """
    Centralized error handling for forensic image parsing.
    
    Responsibilities:
    - Classify errors by type and category
    - Determine retry strategy
    - Generate user-friendly error messages
    - Provide actionable guidance for error resolution
    """
    
    def __init__(self, max_retries: int = 3):
        """
        Initialize the error handler.
        
        Args:
            max_retries: Maximum number of retry attempts for transient errors
        """
        self.max_retries = max_retries
        self.logger = logging.getLogger(__name__)
    
    def classify_error(self, exception: Exception, context: str = "") -> ErrorClassification:
        """
        Classify an error into type and category.
        
        Args:
            exception: The exception that occurred
            context: Additional context about where the error occurred
            
        Returns:
            ErrorClassification with type, category, and user message
        """
        error_msg = str(exception)
        exception_type = type(exception).__name__
        
        # Classify by exception type and message content
        error_type, category = self._determine_error_type_and_category(exception, error_msg)
        
        # Generate user-friendly message
        user_message = self.generate_user_message(error_type, category, error_msg, context)
        
        # Determine if retry is appropriate
        should_retry = error_type == ErrorType.TRANSIENT
        
        # Determine if operation should abort
        should_abort = error_type == ErrorType.CRITICAL
        
        return ErrorClassification(
            error_type=error_type,
            category=category,
            message=error_msg,
            user_message=user_message,
            should_retry=should_retry,
            should_abort=should_abort
        )
    
    def _determine_error_type_and_category(self, exception: Exception, error_msg: str) -> Tuple[ErrorType, ErrorCategory]:
        """
        Determine error type and category based on exception and message.
        
        Args:
            exception: The exception that occurred
            error_msg: The error message string
            
        Returns:
            Tuple of (ErrorType, ErrorCategory)
        """
        exception_type = type(exception).__name__
        error_msg_lower = error_msg.lower()
        
        # Critical errors (require immediate abort)
        if isinstance(exception, MemoryError) or "out of memory" in error_msg_lower:
            return ErrorType.CRITICAL, ErrorCategory.UNKNOWN
        
        if isinstance(exception, OSError):
            if "disk full" in error_msg_lower or "no space left" in error_msg_lower:
                return ErrorType.CRITICAL, ErrorCategory.UNKNOWN
            if "permission denied" in error_msg_lower or "access denied" in error_msg_lower:
                return ErrorType.CRITICAL, ErrorCategory.UNKNOWN
        
        # Transient errors (may succeed on retry)
        if isinstance(exception, (IOError, OSError)):
            if any(keyword in error_msg_lower for keyword in [
                "temporary", "timeout", "timed out", "connection", "network",
                "resource temporarily unavailable", "try again"
            ]):
                # Determine category based on context
                if "partition" in error_msg_lower:
                    return ErrorType.TRANSIENT, ErrorCategory.PARTITION_ACCESS
                elif "file system" in error_msg_lower or "filesystem" in error_msg_lower:
                    return ErrorType.TRANSIENT, ErrorCategory.FILE_SYSTEM
                else:
                    return ErrorType.TRANSIENT, ErrorCategory.ARTIFACT_EXTRACTION
        
        # Image format errors
        if any(keyword in error_msg_lower for keyword in [
            "unsupported format", "invalid format", "corrupted image",
            "not a valid", "cannot open image", "invalid signature",
            "ewf", "vhdx", "vmdk", "iso"
        ]):
            return ErrorType.PERMANENT, ErrorCategory.IMAGE_FORMAT
        
        # Partition access errors
        if any(keyword in error_msg_lower for keyword in [
            "partition", "volume", "cannot access partition",
            "invalid partition", "partition table"
        ]):
            return ErrorType.PERMANENT, ErrorCategory.PARTITION_ACCESS
        
        # File system errors
        if any(keyword in error_msg_lower for keyword in [
            "file system", "filesystem", "ntfs", "fat32", "ext4",
            "cannot read file system", "invalid file system"
        ]):
            return ErrorType.PERMANENT, ErrorCategory.FILE_SYSTEM
        
        # Artifact extraction errors
        if any(keyword in error_msg_lower for keyword in [
            "cannot extract", "extraction failed", "cannot copy",
            "file not found", "path not found", "invalid path"
        ]):
            return ErrorType.PERMANENT, ErrorCategory.ARTIFACT_EXTRACTION
        
        # Integrity verification errors
        if any(keyword in error_msg_lower for keyword in [
            "crc", "checksum", "hash", "integrity", "verification failed",
            "mismatch"
        ]):
            return ErrorType.PERMANENT, ErrorCategory.INTEGRITY_VERIFICATION
        
        # Default to permanent error with unknown category
        return ErrorType.PERMANENT, ErrorCategory.UNKNOWN
    
    def should_retry(self, error_classification: ErrorClassification, attempt: int) -> bool:
        """
        Determine if operation should be retried.
        
        Args:
            error_classification: The classified error
            attempt: Current attempt number (1-based)
            
        Returns:
            True if operation should be retried, False otherwise
        """
        # Don't retry if error is not transient
        if error_classification.error_type != ErrorType.TRANSIENT:
            return False
        
        # Don't retry if max retries exceeded
        if attempt >= self.max_retries:
            return False
        
        # Retry transient errors
        return True
    
    def generate_user_message(self, error_type: ErrorType, category: ErrorCategory,
                             error_msg: str, context: str = "") -> str:
        """
        Generate user-friendly error message with actionable guidance.
        
        Args:
            error_type: Type of error (transient, permanent, critical)
            category: Category of error
            error_msg: Original error message
            context: Additional context about where the error occurred
            
        Returns:
            User-friendly error message with actionable guidance
        """
        # Build context prefix
        context_prefix = f"{context}: " if context else ""
        
        # Generate message based on category
        if category == ErrorCategory.IMAGE_FORMAT:
            return (
                f"{context_prefix}Unable to open forensic image. "
                f"The image format may be unsupported or the file may be corrupted. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Verify the image file is not corrupted\n"
                f"- Try manually selecting the image format\n"
                f"- Use forensic image verification tools (e.g., ewfverify for E01)\n"
                f"- Check if required libraries are installed (pyewf, pyvhdi, pyvmdk)"
            )
        
        elif category == ErrorCategory.PARTITION_ACCESS:
            return (
                f"{context_prefix}Unable to access partition. "
                f"The partition may be encrypted, corrupted, or use an unsupported file system. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Check if the partition is encrypted (BitLocker, LUKS, etc.)\n"
                f"- Verify the partition table is not corrupted\n"
                f"- Try accessing other partitions in the image\n"
                f"- Use partition repair tools if available"
            )
        
        elif category == ErrorCategory.FILE_SYSTEM:
            return (
                f"{context_prefix}Unable to read file system. "
                f"The file system may be corrupted or use an unsupported format. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Verify the file system type is supported (NTFS, FAT32, ext4)\n"
                f"- Check if the file system is corrupted\n"
                f"- Try file system repair tools (chkdsk, fsck)\n"
                f"- Consider using alternative forensic tools for this file system"
            )
        
        elif category == ErrorCategory.ARTIFACT_EXTRACTION:
            return (
                f"{context_prefix}Unable to extract artifact. "
                f"The file may be inaccessible, deleted, or in a protected location. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Verify the file path exists in the image\n"
                f"- Check if the file is in a protected or system directory\n"
                f"- Try extracting other artifacts from the same partition\n"
                f"- Review extraction logs for additional details"
            )
        
        elif category == ErrorCategory.INTEGRITY_VERIFICATION:
            return (
                f"{context_prefix}Integrity verification failed. "
                f"The extracted file may not match the source, or checksums may be corrupted. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Re-extract the artifact to verify consistency\n"
                f"- Check if the source image is corrupted\n"
                f"- Verify disk space is available for extraction\n"
                f"- Review integrity verification settings"
            )
        
        elif error_type == ErrorType.CRITICAL:
            return (
                f"{context_prefix}Critical error occurred. "
                f"The operation cannot continue. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Check available disk space\n"
                f"- Verify sufficient memory is available\n"
                f"- Check file permissions for case directory\n"
                f"- Close other applications to free resources"
            )
        
        elif error_type == ErrorType.TRANSIENT:
            return (
                f"{context_prefix}Temporary error occurred. "
                f"The operation will be retried automatically. "
                f"Details: {error_msg}\n\n"
                f"If the error persists:\n"
                f"- Check network connectivity (for network-mounted images)\n"
                f"- Verify the image file is accessible\n"
                f"- Check system resources (CPU, memory, disk I/O)"
            )
        
        else:
            return (
                f"{context_prefix}An error occurred during processing. "
                f"Details: {error_msg}\n\n"
                f"Suggested actions:\n"
                f"- Review the error details above\n"
                f"- Check the application logs for more information\n"
                f"- Try the operation again\n"
                f"- Contact support if the issue persists"
            )
