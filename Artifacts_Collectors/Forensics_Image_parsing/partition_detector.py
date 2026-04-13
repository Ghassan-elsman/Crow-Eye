"""
Partition Detection Utility

This module provides utilities for detecting and enumerating partitions
in forensic images using the dissect ecosystem.
"""

from typing import List

try:
    from dissect.target.volume import open as open_volume
    from dissect.target.filesystem import open as open_fs
    DISSECT_AVAILABLE = True
except ImportError:
    DISSECT_AVAILABLE = False
    print("Warning: dissect not available - partition detection will be limited")

try:
    if __package__ or "." in __name__:
        from .data_models import PartitionInfo
    else:
        from data_models import PartitionInfo
except (ImportError, ValueError):
    from data_models import PartitionInfo


def detect_partitions(file_handle) -> List[PartitionInfo]:
    """
    Detect partitions in a forensic image container.
    
    This function uses dissect.volume to enumerate partitions in the image.
    
    Args:
        file_handle: File-like object returned by dissect.target.container.open()
        
    Returns:
        List of PartitionInfo objects describing each partition.
    """
    if not DISSECT_AVAILABLE:
        print("Warning: Cannot detect partitions - dissect not available")
        return []
    
    partitions = []
    
    try:
        # Try to parse as a volume system (MBR, GPT, etc.)
        print(f"[DEBUG] Attempting open_volume on {file_handle}")
        vs = open_volume(file_handle)
        print(f"[DEBUG] Volume system detected: {getattr(vs, '__type__', 'Unknown')}")
        
        for partition in vs.volumes:
            print(f"[DEBUG] Found partition {partition.number} at offset {partition.offset}")
            fs_type = _detect_fs_type(partition)
            description = getattr(partition, 'name', 'Unknown') or "Unknown"
            # In MBR, active partitions indicate bootable. In GPT, there are attributes.
            is_bootable = False
            if hasattr(partition, 'active'):
                is_bootable = partition.active
                
            part_info = PartitionInfo(
                partition_number=partition.number,
                start_offset=partition.offset,
                size_bytes=partition.size,
                file_system_type=fs_type,
                description=description,
                is_bootable=is_bootable
            )
            partitions.append(part_info)
            
        if partitions:
            print(f"[DEBUG] Returning {len(partitions)} partitions from volume system")
            return partitions
        else:
            print("[DEBUG] open_volume succeeded but found no partitions")
            
    except Exception as e:
        print(f"[INFO] No partition table detected: {e}")
        
    # Handle single partition / raw filesystem case
    print("[DEBUG] Attempting single partition fallback")
    try:
        file_handle.seek(0, 2)
        img_size = file_handle.tell()
        file_handle.seek(0)
        
        fs_type = _detect_fs_type(file_handle)
        
        part_info = PartitionInfo(
            partition_number=0,
            start_offset=0,
            size_bytes=img_size,
            file_system_type=fs_type,
            description="C Partition (Fallback)",
            is_bootable=False
        )
        partitions.append(part_info)
    except Exception as e:
        print(f"[WARNING] Could not detect file system, returning Raw C Partition: {e}")
        # Final desperate fallback for "0 partition" issue
        try:
            file_handle.seek(0, 2)
            total_size = file_handle.tell()
        except:
            total_size = 0
            
        partitions.append(PartitionInfo(
            partition_number=0,
            start_offset=0,
            size_bytes=total_size,
            file_system_type="UNKNOWN",
            description="C Partition (Forced Fallback)",
            is_bootable=False
        ))
        
    return partitions

def _detect_fs_type(volume_handle) -> str:
    """
    Detect file system type for a volume.
    
    Args:
        volume_handle: A file-like object or a dissect volume
        
    Returns:
        String describing the file system type.
    """
    try:
        fs = open_fs(volume_handle)
        if fs:
            # dissect filesystems have a __type__ attribute like 'ntfs', 'extfs', 'fat'
            return getattr(fs, '__type__', 'Unknown').upper()
    except Exception:
        pass
    return "Unknown"

def get_partition_by_number(partitions: List[PartitionInfo], partition_number: int) -> PartitionInfo:
    for partition in partitions:
        if partition.partition_number == partition_number:
            return partition
    raise ValueError(f"Partition {partition_number} not found")

def filter_partitions_by_fs_type(partitions: List[PartitionInfo], fs_type: str) -> List[PartitionInfo]:
    return [p for p in partitions if p.file_system_type.upper() == fs_type.upper()]

def get_bootable_partitions(partitions: List[PartitionInfo]) -> List[PartitionInfo]:
    return [p for p in partitions if p.is_bootable]
