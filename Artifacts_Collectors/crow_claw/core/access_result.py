"""
Data models for file access results.

This module defines the AccessResult dataclass used to track the outcome
of file access attempts across different strategies.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class AccessResult:
    """Result of a file access attempt.
    
    Tracks the success/failure of accessing a file, which strategy was used,
    file size, errors encountered, and all attempts made.
    
    Attributes:
        success: Whether the file access was successful
        source_path: Original file path being accessed
        dest_path: Destination path where file was copied
        strategy_used: Name of the strategy that succeeded ("standard", "vss", "raw_disk")
        file_size: Size of the accessed file in bytes
        error: Error message if access failed
        attempts: List of all AccessResult attempts made (for retry tracking)
        vss_shadow_copy_id: VSS shadow copy ID if VSS was used
        duration_seconds: Time taken for the access operation
        status: Status of the operation ("success", "failed", "partial")
    """
    success: bool
    source_path: str = ""
    dest_path: str = ""
    strategy_used: str = ""  # "standard", "vss", "raw_disk"
    file_size: int = 0
    error: Optional[str] = None
    attempts: List['AccessResult'] = field(default_factory=list)
    vss_shadow_copy_id: Optional[str] = None
    duration_seconds: float = 0.0
    status: str = "pending"  # "success", "failed", "partial"
    # Where the bytes were really read from (the shadow-copy path for VSS), and
    # when that snapshot was taken (UTC). The chain of custody needs both: the
    # source hash is taken from read_path, because the live file is the one
    # that was locked.
    read_path: Optional[str] = None
    vss_shadow_copy_created: Optional[str] = None
