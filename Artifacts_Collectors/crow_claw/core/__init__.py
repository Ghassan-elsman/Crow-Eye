"""Core module for Crow-Claw artifact collection engine."""

from .artifacts import (
    Artifact,
    ArtifactType,
    get_all_artifacts,
    get_artifact_by_type,
    DEFAULT_ARTIFACTS
)

from .collector import (
    ArtifactCollector,
    CollectionStatus,
    CollectionStatistics,
    ArtifactCollectionResult
)

from .manifest import CollectionManifest

from .validator import (
    PathValidator,
    PathExpander,
    validate_target_directory
)

from .access_result import AccessResult

from .access_strategy import FileAccessStrategy

from .standard_copy_strategy import StandardCopyStrategy

from .vss_access_strategy import VSSAccessStrategy

from .raw_disk_access_strategy import RawDiskAccessStrategy

from .shadow_copy import ShadowCopy

from .file_accessor import FileAccessor

from .windows_version_detector import WindowsVersionDetector, WindowsVersion

from .status_reporter import StatusReporter

from .error_classifier import (
    ErrorClassifier,
    ErrorCategory,
    ErrorAction,
    ErrorClassification,
    handle_collection_error
)

from .vss_diagnostics import (
    VSSDiagnostics,
    ServiceStatus
)

__all__ = [
    "Artifact",
    "ArtifactType",
    "get_all_artifacts",
    "get_artifact_by_type",
    "DEFAULT_ARTIFACTS",
    "ArtifactCollector",
    "CollectionStatus",
    "CollectionStatistics",
    "ArtifactCollectionResult",
    "CollectionManifest",
    "PathValidator",
    "PathExpander",
    "validate_target_directory",
    "AccessResult",
    "FileAccessStrategy",
    "StandardCopyStrategy",
    "VSSAccessStrategy",
    "RawDiskAccessStrategy",
    "ShadowCopy",
    "FileAccessor",
    "WindowsVersionDetector",
    "WindowsVersion",
    "StatusReporter",
    "ErrorClassifier",
    "ErrorCategory",
    "ErrorAction",
    "ErrorClassification",
    "handle_collection_error",
    "VSSDiagnostics",
    "ServiceStatus"
]
