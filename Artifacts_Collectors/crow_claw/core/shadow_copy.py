"""
Shadow copy data model.

This module defines the ShadowCopy dataclass used to represent
Volume Shadow Copy Service (VSS) snapshots.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ShadowCopy:
    r"""Represents a VSS shadow copy snapshot.
    
    A shadow copy is a point-in-time snapshot of a volume created by the
    Windows Volume Shadow Copy Service. This dataclass stores the metadata
    needed to access files from a shadow copy.
    
    Attributes:
        shadow_copy_id: Unique identifier for the shadow copy (GUID format)
        shadow_copy_volume: Device path to access the shadow copy
                           (e.g., \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1)
        creation_time: Timestamp when the shadow copy was created
        original_volume: The original volume letter (e.g., C:\)
    """
    shadow_copy_id: str
    shadow_copy_volume: str
    creation_time: datetime
    original_volume: str
    
    def __str__(self) -> str:
        """Return a human-readable string representation."""
        return (f"ShadowCopy(id={self.shadow_copy_id}, "
                f"volume={self.original_volume}, "
                f"created={self.creation_time.isoformat()})")
