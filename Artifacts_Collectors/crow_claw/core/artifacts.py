"""
Artifact Definitions and Configuration
========================================

Defines all forensic artifact types collectible from Windows systems
with their default paths, validation rules, and metadata.

Phase 1: Core Data Model
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional
import os
import glob


class ArtifactType(Enum):
    """Enumeration of all collectible forensic artifact types."""
    REGISTRY_HIVES = "registry"
    PREFETCH = "prefetch"
    AMCACHE = "amcache"
    JUMPLISTS_LNK = "jumplists_lnk"
    MFT = "mft"
    USN_JOURNAL = "usn_journal"
    RECYCLE_BIN = "recycle_bin"
    EVENT_LOGS = "event_logs"
    SRUM_DATABASE = "srum_database"
    SHIMCACHE = "shimcache"
    PARTITION_INFO = "partition_info"


@dataclass
class Artifact:
    """
    Represents a single forensic artifact type.

    Attributes:
        name: Human-readable artifact name
        artifact_type: ArtifactType enum value
        default_paths: List of default Windows paths for this artifact
        custom_paths: User-customized paths
        enabled: Whether this artifact is enabled for collection
        description: Detailed description of the artifact
        required_admin: Whether admin privileges required
        estimated_size: Estimated total size in bytes
    """
    name: str
    artifact_type: ArtifactType
    default_paths: List[str]
    description: str
    required_admin: bool = False
    estimated_size: int = 0
    custom_paths: List[str] = field(default_factory=list)
    enabled: bool = True

    def get_all_paths(self) -> List[str]:
        """Return all paths (default + custom) for this artifact."""
        return self.default_paths + self.custom_paths

    def add_custom_path(self, path: str) -> None:
        """Add a custom path to this artifact."""
        if path and path not in self.custom_paths:
            self.custom_paths.append(path)

    def remove_custom_path(self, path: str) -> None:
        """Remove a custom path from this artifact."""
        if path in self.custom_paths:
            self.custom_paths.remove(path)

    def clear_custom_paths(self) -> None:
        """Clear all custom paths."""
        self.custom_paths.clear()

    def validate_paths(self) -> tuple[List[str], List[str]]:
        """
        Validate all paths for this artifact.

        Returns:
            Tuple of (valid_paths, invalid_paths)
        """
        valid_paths = []
        invalid_paths = []

        for path in self.get_all_paths():
            try:
                expanded_path = os.path.expandvars(path)
                if os.path.exists(expanded_path):
                    valid_paths.append(path)
                else:
                    invalid_paths.append(path)
            except Exception:
                invalid_paths.append(path)

        return valid_paths, invalid_paths

    def expand_wildcards(self, windows_partition: str = "C:") -> List[str]:
        """
        Expand wildcard paths to actual file list.

        Args:
            windows_partition: Windows partition letter (e.g., "C:")

        Returns:
            List of expanded file paths
        """
        expanded = []
        for path in self.get_all_paths():
            # Replace partition placeholder if present
            expanded_path = path.replace("{PARTITION}", windows_partition)
            expanded_path = os.path.expandvars(expanded_path)

            if "*" in expanded_path or "?" in expanded_path:
                # Expand wildcards
                matches = glob.glob(expanded_path)
                expanded.extend(matches)
            else:
                expanded.append(expanded_path)

        return expanded

    def to_dict(self) -> dict:
        """Convert artifact to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "type": self.artifact_type.value,
            "default_paths": self.default_paths,
            "custom_paths": self.custom_paths,
            "enabled": self.enabled,
            "description": self.description,
            "required_admin": self.required_admin,
            "estimated_size": self.estimated_size
        }


def create_registry_artifact() -> Artifact:
    """Create Registry Hives artifact configuration."""
    return Artifact(
        name="Registry Hives",
        artifact_type=ArtifactType.REGISTRY_HIVES,
        default_paths=[
            r"{PARTITION}\Windows\System32\config\SYSTEM",
            r"{PARTITION}\Windows\System32\config\SOFTWARE",
            r"{PARTITION}\Windows\System32\config\SAM",
            r"{PARTITION}\Windows\System32\config\SECURITY",
        ],
        description="Windows Registry hives containing system configuration, software installations, user activity, and security settings",
        required_admin=True,
        estimated_size=100_000_000  # ~100 MB average
    )


def create_ntuser_artifact() -> Artifact:
    """Create NTUSER.DAT artifact configuration (per-user)."""
    return Artifact(
        name="User Registry (NTUSER.DAT)",
        artifact_type=ArtifactType.REGISTRY_HIVES,
        default_paths=[
            r"{PARTITION}\Users\*\NTUSER.DAT",
        ],
        description="Per-user registry hive containing user-specific settings, recent files, run history, and user activity artifacts",
        required_admin=False,
        estimated_size=20_000_000  # ~20 MB per user
    )


def create_usrclass_artifact() -> Artifact:
    """Create UsrClass.dat artifact configuration (per-user)."""
    return Artifact(
        name="User Class Registry (UsrClass.dat)",
        artifact_type=ArtifactType.REGISTRY_HIVES,
        default_paths=[
            r"{PARTITION}\Users\*\AppData\Local\Microsoft\Windows\UsrClass.dat",
        ],
        description="Per-user registry hive containing Windows Explorer ShellBags (folder access history), file associations, and COM registrations. Critical for complete ShellBags analysis.",
        required_admin=False,
        estimated_size=10_000_000  # ~10 MB per user
    )


def create_prefetch_artifact() -> Artifact:
    """Create Prefetch artifact configuration."""
    return Artifact(
        name="Prefetch Files",
        artifact_type=ArtifactType.PREFETCH,
        default_paths=[
            r"{PARTITION}\Windows\Prefetch\*.pf",
        ],
        description="Prefetch files containing program execution history, launch timestamps, and execution count for each application",
        required_admin=False,
        estimated_size=10_000_000  # ~10 MB
    )


def create_amcache_artifact() -> Artifact:
    """Create AmCache artifact configuration."""
    return Artifact(
        name="AmCache Database",
        artifact_type=ArtifactType.AMCACHE,
        default_paths=[
            r"{PARTITION}\Windows\AppCompat\Programs\Amcache.hve",
        ],
        description="Application Compatibility Cache containing program execution history, installation records, and execution timestamps",
        required_admin=False,
        estimated_size=50_000_000  # ~50 MB
    )


def create_jumplists_lnk_artifact() -> Artifact:
    """Create Jump Lists and LNK files artifact configuration."""
    return Artifact(
        name="Jump Lists & LNK Files",
        artifact_type=ArtifactType.JUMPLISTS_LNK,
        default_paths=[
            r"{PARTITION}\Users\*\AppData\Roaming\Microsoft\Windows\Recent",
            r"{PARTITION}\Users\*\AppData\Roaming\Microsoft\Windows\Recent Automatic Destinations",
            r"{PARTITION}\Users\*\AppData\Roaming\Microsoft\Windows\Recent Custom Destinations",
            r"{PARTITION}\Users\*\Desktop",
            r"{PARTITION}\Users\*\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Recent",
            r"{PARTITION}\Users\*\AppData\Roaming\Microsoft\Internet Explorer\Quick Launch\User Pinned Items",
            r"{PARTITION}\Users\*\AppData\Local\Microsoft\Windows\Explorer",
        ],
        description="Shortcut files (.lnk) and Jump Lists tracking recently accessed files, shortcuts, and application usage patterns",
        required_admin=False,
        estimated_size=30_000_000  # ~30 MB
    )


def create_mft_artifact() -> Artifact:
    """Create MFT artifact configuration."""
    return Artifact(
        name="Master File Table (MFT)",
        artifact_type=ArtifactType.MFT,
        default_paths=[
            r"\\.\{PARTITION}\$MFT",  # FIXED: Removed colon after {PARTITION} to avoid double colon
        ],
        description="NTFS Master File Table containing complete file system timeline, file metadata, and deleted file recovery data",
        required_admin=True,
        estimated_size=500_000_000  # ~500 MB (varies by drive size)
    )


def create_usn_journal_artifact() -> Artifact:
    """Create USN Journal artifact configuration."""
    return Artifact(
        name="USN Journal",
        artifact_type=ArtifactType.USN_JOURNAL,
        default_paths=[
            r"{PARTITION}\$Extend\$UsnJrnl:$J",  # Via raw disk
        ],
        description="NTFS Update Sequence Number Journal containing detailed file system change log with timestamps for all file operations",
        required_admin=True,
        estimated_size=200_000_000  # ~200 MB
    )


def create_recycle_bin_artifact() -> Artifact:
    """Create Recycle Bin artifact configuration."""
    return Artifact(
        name="Recycle Bin",
        artifact_type=ArtifactType.RECYCLE_BIN,
        default_paths=[
            r"{PARTITION}\$Recycle.Bin\S-1-5-*",
            r"{PARTITION}\$Recycle.Bin\S-1-5-*\$I*",
            r"{PARTITION}\$Recycle.Bin\S-1-5-*\$R*",
        ],
        description="Deleted files and metadata stored in Recycle Bin with original paths and deletion timestamps",
        required_admin=False,
        estimated_size=100_000_000  # ~100 MB average
    )


def create_event_logs_artifact() -> Artifact:
    """Create Event Logs artifact configuration."""
    return Artifact(
        name="Event Logs",
        artifact_type=ArtifactType.EVENT_LOGS,
        default_paths=[
            r"{PARTITION}\Windows\System32\winevt\Logs\System.evtx",
            r"{PARTITION}\Windows\System32\winevt\Logs\Application.evtx",
            r"{PARTITION}\Windows\System32\winevt\Logs\Security.evtx",
        ],
        description="Windows Event Logs (System, Application, Security) containing system events, warnings, errors, and security-relevant activities",
        required_admin=True,
        estimated_size=150_000_000  # ~150 MB total
    )


def create_srum_artifact() -> Artifact:
    """Create SRUM Database artifact configuration."""
    return Artifact(
        name="SRUM Database",
        artifact_type=ArtifactType.SRUM_DATABASE,
        default_paths=[
            r"{PARTITION}\Windows\System32\sru\SRUDB.dat",
        ],
        description="System Resource Usage Monitor database tracking application network usage, power usage, and resource consumption history",
        required_admin=True,
        estimated_size=50_000_000  # ~50 MB
    )


def create_shimcache_artifact() -> Artifact:
    """Create ShimCache artifact configuration (registry-based)."""
    return Artifact(
        name="ShimCache (AppCompat Cache)",
        artifact_type=ArtifactType.SHIMCACHE,
        default_paths=[
            # ShimCache is extracted via Registry parsing
            r"{PARTITION}\Windows\System32\config\SYSTEM",
        ],
        description="Application Compatibility Shim Cache in registry containing program execution history with timestamps and file metadata",
        required_admin=True,
        estimated_size=10_000_000  # ~10 MB
    )


def create_partition_info_artifact() -> Artifact:
    """Create Partition Information artifact configuration."""
    return Artifact(
        name="Partition & Disk Information",
        artifact_type=ArtifactType.PARTITION_INFO,
        default_paths=[],  # No file paths - this is system analysis
        description="Complete disk and partition layout analysis including partition types, file systems, sizes, boot configuration, and hidden partitions",
        required_admin=False,  # Can run without admin but gets more info with admin
        estimated_size=1_000_000  # ~1 MB (database file)
    )


# Define all default artifacts in collection order
DEFAULT_ARTIFACTS: List[Artifact] = [
    create_partition_info_artifact(),  # Collect partition info first
    create_registry_artifact(),
    create_ntuser_artifact(),
    create_usrclass_artifact(),  # NEW: Collect UsrClass.dat from all users
    create_event_logs_artifact(),
    create_prefetch_artifact(),
    create_amcache_artifact(),
    create_jumplists_lnk_artifact(),
    create_shimcache_artifact(),
    create_srum_artifact(),
    create_recycle_bin_artifact(),
    create_mft_artifact(),
    create_usn_journal_artifact(),
]


def get_all_artifacts() -> List[Artifact]:
    """
    Get all available artifacts.

    Returns:
        List of all Artifact objects
    """
    return DEFAULT_ARTIFACTS.copy()


def get_artifact_by_type(artifact_type: ArtifactType) -> Optional[Artifact]:
    """
    Get artifact by type.

    Args:
        artifact_type: ArtifactType enum value

    Returns:
        Artifact object or None if not found
    """
    for artifact in DEFAULT_ARTIFACTS:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def get_artifacts_by_type(artifact_type: ArtifactType) -> List[Artifact]:
    """
    Get all artifacts of a specific type (some types have multiple artifacts).

    Args:
        artifact_type: ArtifactType enum value

    Returns:
        List of matching Artifact objects
    """
    return [a for a in DEFAULT_ARTIFACTS if a.artifact_type == artifact_type]


def get_admin_required_artifacts() -> List[Artifact]:
    """
    Get all artifacts that require admin privileges.

    Returns:
        List of Artifact objects requiring admin
    """
    return [a for a in DEFAULT_ARTIFACTS if a.required_admin]


def get_enabled_artifacts() -> List[Artifact]:
    """
    Get all enabled artifacts.

    Returns:
        List of enabled Artifact objects
    """
    return [a for a in DEFAULT_ARTIFACTS if a.enabled]
