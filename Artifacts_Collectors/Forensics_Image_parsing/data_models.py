"""
Data Models for Forensic Image Parsing

This module defines data classes for forensic image information, partition details,
and extraction options.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class PartitionInfo:
    """
    Information about a partition in a forensic image.
    
    Attributes:
        partition_number: Partition index (0-based)
        start_offset: Starting byte offset of the partition
        size_bytes: Size of the partition in bytes
        file_system_type: Type of file system (NTFS, FAT32, ext4, etc.)
        description: Human-readable description of the partition
        is_bootable: Whether the partition is marked as bootable
    """
    partition_number: int
    start_offset: int
    size_bytes: int
    file_system_type: str
    description: str
    is_bootable: bool = False
    
    def __str__(self) -> str:
        """String representation for display."""
        size_gb = self.size_bytes / (1024**3)
        return f"Partition {self.partition_number}: {self.file_system_type} ({size_gb:.2f} GB) - {self.description}"


@dataclass
class ImageInfo:
    """
    Information about a forensic image.
    
    Attributes:
        file_paths: List of paths to the image files (segments)
        format: Image format (E01, VHDX, VMDK, ISO, RAW)
        size_bytes: Total size of the image in bytes
        partitions: List of partitions found in the image
        acquisition_date: Date when the image was acquired (if available)
        case_number: Case number associated with the image (if available)
        examiner: Name of the examiner who acquired the image (if available)
        notes: Additional notes about the image (if available)
    """
    file_paths: List[str]
    format: str
    size_bytes: int
    partitions: List[PartitionInfo] = field(default_factory=list)
    acquisition_date: Optional[datetime] = None
    case_number: Optional[str] = None
    examiner: Optional[str] = None
    notes: Optional[str] = None
    
    def __str__(self) -> str:
        """String representation for display."""
        import os
        size_gb = self.size_bytes / (1024**3)
        path_display = self.file_paths[0] if len(self.file_paths) == 1 else f"{len(self.file_paths)} segments starting with {os.path.basename(self.file_paths[0])}"
        return f"{self.format} Image: {path_display} ({size_gb:.2f} GB, {len(self.partitions)} partitions)"


@dataclass
class ExtractionOptions:
    """
    Options for artifact extraction from forensic images.
    
    Attributes:
        selected_partitions: List of partition numbers to process (empty = all)
        artifact_type_filter: Filter for specific artifact types (None = all types)
        calculate_hashes: Whether to calculate SHA256 hashes for extracted artifacts
        verify_integrity: Whether to verify image integrity (E01 CRC, hash verification)
        skip_known_files: Whether to skip files that already exist in the case directory
        include_subdirs: Whether to recursively scan subdirectories
        max_retries: Maximum number of retry attempts for transient errors
        chunk_size_mb: Chunk size in MB for streaming reads
    """
    selected_partitions: List[int] = field(default_factory=list)
    artifact_type_filter: Optional[str] = None
    calculate_hashes: bool = True
    verify_integrity: bool = True
    skip_known_files: bool = True
    include_subdirs: bool = True
    max_retries: int = 3
    chunk_size_mb: int = 1
    
    def __str__(self) -> str:
        """String representation for display."""
        parts = []
        if self.selected_partitions:
            parts.append(f"Partitions: {', '.join(map(str, self.selected_partitions))}")
        else:
            parts.append("Partitions: All")
        
        if self.artifact_type_filter:
            parts.append(f"Filter: {self.artifact_type_filter}")
        else:
            parts.append("Filter: All Types")
        
        parts.append(f"Hashes: {'Yes' if self.calculate_hashes else 'No'}")
        parts.append(f"Verify: {'Yes' if self.verify_integrity else 'No'}")
        
        return " | ".join(parts)


@dataclass
class FileMetadata:
    """
    Metadata for a file within a forensic image.
    
    Attributes:
        file_path: Path to the file within the image
        size_bytes: Size of the file in bytes
        created_time: File creation timestamp
        modified_time: File modification timestamp
        accessed_time: File access timestamp
        is_directory: Whether this is a directory
        is_hidden: Whether the file has the hidden attribute
        is_system: Whether the file has the system attribute
    """
    file_path: str
    size_bytes: int
    created_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    accessed_time: Optional[datetime] = None
    is_directory: bool = False
    is_hidden: bool = False
    is_system: bool = False
    
    def __str__(self) -> str:
        """String representation for display."""
        size_kb = self.size_bytes / 1024
        attrs = []
        if self.is_directory:
            attrs.append("DIR")
        if self.is_hidden:
            attrs.append("H")
        if self.is_system:
            attrs.append("S")
        
        attr_str = f" [{','.join(attrs)}]" if attrs else ""
        return f"{self.file_path} ({size_kb:.1f} KB){attr_str}"
