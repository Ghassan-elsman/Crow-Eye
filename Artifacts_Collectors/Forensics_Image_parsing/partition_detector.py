"""
Partition Detection Utility

This module provides utilities for detecting and enumerating partitions
in forensic images using the dissect ecosystem.
"""

import logging
from typing import List, Optional

logger = logging.getLogger("image_parsing.partition_detector")

try:
    from dissect.target.volume import open as open_volume
    from dissect.target.filesystem import open as open_fs
    DISSECT_AVAILABLE = True
except ImportError:
    DISSECT_AVAILABLE = False
    logging.getLogger("image_parsing.partition_detector").warning(
        "dissect not available - partition detection will be limited")

try:
    if __package__ or "." in __name__:
        from .data_models import PartitionInfo
    else:
        from data_models import PartitionInfo
except (ImportError, ValueError):
    from data_models import PartitionInfo

try:
    if __package__ or "." in __name__:
        from .image_preflight import classify_boot_sector
    else:
        from image_preflight import classify_boot_sector
except (ImportError, ValueError):
    from image_preflight import classify_boot_sector

_WINDOWS_MARKERS = ("Windows/System32/config", "WINDOWS/system32/config")


def _boot_kind(handle) -> str:
    """The volume type the partition's first sector declares."""
    try:
        handle.seek(0)
        data = handle.read(512)
        handle.seek(0)
        return classify_boot_sector(data)
    except Exception as exc:
        logger.debug("boot sector read failed: %s", exc)
        return "unknown"


def _has_windows(fs) -> Optional[bool]:
    """True when the file system holds Windows' registry folder."""
    if fs is None:
        return None
    for marker in _WINDOWS_MARKERS:
        try:
            if fs.exists(marker):
                return True
        except Exception:
            try:
                fs.get(marker)
                return True
            except Exception:
                continue
    return False


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
        logger.warning("Cannot detect partitions - dissect not available")
        return []

    partitions = []

    try:
        # Try to parse as a volume system (MBR, GPT, etc.)
        logger.debug("Attempting open_volume on %s", file_handle)
        vs = open_volume(file_handle)
        logger.info("Volume system detected: %s", getattr(vs, '__type__', 'Unknown'))

        for partition in vs.volumes:
            logger.info("Found partition %s at offset %s", partition.number, partition.offset)
            boot = _boot_kind(partition)
            fs_type, fs = _detect_fs(partition)
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
                is_bootable=is_bootable,
                boot_kind=boot,
                has_windows=_has_windows(fs),
            )
            partitions.append(part_info)

        if partitions:
            logger.info("Returning %d partitions from the volume system", len(partitions))
            return partitions
        else:
            logger.info("open_volume succeeded but found no partitions")

    except Exception as e:
        logger.info("No partition table detected: %s", e)

    # Handle single partition / raw filesystem case. A volume image (no
    # partition table, the file system starts at offset 0) is genuine; an image
    # whose table simply could not be read is not - only a file system opening
    # here makes the fallback "verified".
    logger.info("Attempting single partition fallback")
    try:
        file_handle.seek(0, 2)
        img_size = file_handle.tell()
        file_handle.seek(0)

        boot = _boot_kind(file_handle)
        fs_type, fs = _detect_fs(file_handle)

        part_info = PartitionInfo(
            partition_number=0,
            start_offset=0,
            size_bytes=img_size,
            file_system_type=fs_type,
            description="C Partition (Fallback)",
            is_bootable=False,
            boot_kind=boot,
            has_windows=_has_windows(fs),
            verified=fs is not None,
        )
        partitions.append(part_info)
    except Exception as e:
        logger.warning("Could not detect a file system, offering the raw image as one partition: %s", e)
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
            is_bootable=False,
            verified=False,
        ))

    return partitions

def _detect_fs(volume_handle):
    """(file system type, the opened file system or None)."""
    try:
        fs = open_fs(volume_handle)
        if fs:
            return getattr(fs, '__type__', 'Unknown').upper(), fs
    except Exception as exc:
        logger.debug("open_fs failed: %s", exc)
    return "Unknown", None


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
