"""
Artifact Collection Engine
===========================

Core collection logic for gathering forensic artifacts from Windows systems.
Handles file copying, admin verification, error handling, and statistics tracking.

Phase 3: Collection Engine
"""

import logging
import os
import shutil
import stat
import glob
import ctypes
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

from .status_reporter import StatusReporter
from .file_accessor import FileAccessor
from .validator import ArtifactValidator
from .windows_version_detector import WindowsVersionDetector, WindowsVersion
from .manifest import CollectionManifest
from .artifacts import browser_dir_skipped, browser_root_excluded, PER_USER_TYPES, UserFolderPlacer
from .shadow_copy_manager import delete_created_shadow_copies

try:
    from utils import custody as _custody
except Exception:                                   # standalone Crow-Claw
    _custody = None

# __name__ is crow_claw.core.collector (or Artifacts_Collectors.crow_claw...):
# both are routed to <case>/logs/crow_claw.log by the case logging.
logger = logging.getLogger(__name__)


def _now():
    """Collection times are UTC, like every other time Crow-Eye records."""
    return datetime.now(timezone.utc)


def _method(access_result):
    """standard / vss / raw_disk / an image format, from an AccessResult."""
    return (getattr(access_result, "strategy_used", "") or "standard").lower()


def _case_root(output_directory):
    """The case folder a collection writes into (its custody record goes in logs/)."""
    out = os.path.abspath(output_directory)
    if os.path.basename(out).lower() in ("live_acquisition", "target_artifacts"):
        return os.path.dirname(out)
    return out

# Folder (under the output directory) and source tag of a live browser tree;
# the layout matches what the Offline Importer and image extraction write.
_BROWSER_DIR = "Browser"
_BROWSER_SOURCE_TAG = "live"


def _is_link(path: str) -> bool:
    """A symlink or NTFS junction (os.walk follows junctions on Windows)."""
    try:
        return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _p: False)(path))
    except OSError:
        return True


class CollectionStatus(Enum):
    """Status of artifact collection."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class CollectionStatistics:
    """Statistics for a collection operation."""
    total_artifacts_requested: int = 0
    total_artifacts_collected: int = 0
    total_files_collected: int = 0
    total_bytes_collected: int = 0
    total_errors: int = 0
    total_skipped: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, error: str):
        """Add an error message."""
        self.errors.append(error)
        self.total_errors += 1

    def add_warning(self, warning: str):
        """Add a warning message."""
        self.warnings.append(warning)

    def get_summary(self) -> Dict:
        """Get summary dictionary."""
        return {
            "total_artifacts_requested": self.total_artifacts_requested,
            "total_artifacts_collected": self.total_artifacts_collected,
            "total_files_collected": self.total_files_collected,
            "total_bytes_collected": self.total_bytes_collected,
            "total_errors": self.total_errors,
            "total_skipped": self.total_skipped,
            "duration_seconds": self.duration_seconds,
            "status": self.get_status(),
            "errors": self.errors,
            "warnings": self.warnings
        }

    def get_status(self) -> str:
        """Get overall collection status."""
        if self.total_artifacts_collected == self.total_artifacts_requested:
            return "SUCCESS"
        elif self.total_artifacts_collected > 0:
            return "PARTIAL_SUCCESS"
        else:
            return "FAILED"


@dataclass
class ArtifactCollectionResult:
    """Result of collecting a single artifact."""
    artifact_name: str
    artifact_type: str
    source_paths: List[str]
    dest_path: str
    status: CollectionStatus
    files_collected: int = 0
    bytes_collected: int = 0
    errors: List[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "artifact_name": self.artifact_name,
            "artifact_type": self.artifact_type,
            "source_paths": self.source_paths,
            "dest_path": self.dest_path,
            "status": self.status.value,
            "files_collected": self.files_collected,
            "bytes_collected": self.bytes_collected,
            "errors": self.errors,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "duration_seconds": self.duration_seconds
        }


class ArtifactCollector:
    """
    Main artifact collection engine.

    Handles collection of forensic artifacts from Windows systems with
    proper error handling, admin checking, and comprehensive statistics.
    """

    def __init__(self, verbose: bool = False, is_admin: Optional[bool] = None):
        """
        Initialize collector.

        Args:
            verbose: Enable verbose logging
            is_admin: Override admin privilege detection (useful when called from GUI thread)
        """
        self.verbose = verbose
        self.statistics = CollectionStatistics()
        self.collection_results: List[ArtifactCollectionResult] = []
        self.progress_callback: Optional[Callable] = None
        self.status_callback: Optional[Callable] = None
        # (index, total, name) as each artifact starts: the GUI's "(n/N)".
        # Its own channel, so no log rate-limiting can drop it (the "(14/14)"
        # log line was dropped and the window showed 13/14 for the whole
        # browser phase).
        self.artifact_callback: Optional[Callable] = None

        # Initialize status reporter
        self.status_reporter = StatusReporter()

        # Track access method statistics
        self.access_method_stats: Dict[str, int] = {
            "standard": 0,
            "vss": 0,
            "raw_disk": 0
        }

        # Detect admin privileges (Task 12.1)
        # Allow override from parameter (fixes QThread context issue)
        if is_admin is not None:
            self.is_admin = is_admin
        else:
            self.is_admin = self.detect_admin_privileges()

        # Initialize file accessor with admin status
        self.file_accessor = FileAccessor(self.is_admin)

        # Initialize validator
        self.validator = ArtifactValidator()

        # Initialize Windows version detector
        self.version_detector = WindowsVersionDetector()

        # "Include browser cache": copy the HTTP cache / CacheStorage / cache2
        # folders of browser profiles (most of their size on disk).
        self.include_browser_cache = True

        # Display admin status
        if self.is_admin:
            self.log("[OK] Running with administrator privileges")
        else:
            self.log("[WARNING] Not running with administrator privileges")
            self.log("  Some artifacts will be skipped (see admin-required list)")

    def set_progress_callback(self, callback: Callable):
        """Set callback for progress updates."""
        self.progress_callback = callback

    def set_artifact_callback(self, callback: Callable):
        """Set callback(index, total, name) called as each artifact starts."""
        self.artifact_callback = callback

    def set_status_callback(self, callback: Callable):
        """Set callback for status updates."""
        self.status_callback = callback
        self.status_reporter.set_status_callback(callback)

    def detect_admin_privileges(self) -> bool:
        """
        Detect if running with administrator privileges.

        Uses ctypes to call Windows API IsUserAnAdmin() on Windows,
        or os.getuid() on Linux.

        Returns:
            True if running as administrator, False otherwise
        """
        if os.name == 'nt':
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception as e:
                self.log(f"Warning: Could not detect admin privileges: {e}")
                return False
        else:
            try:
                return getattr(os, 'getuid', lambda: 1)() == 0
            except:
                return False

    def get_admin_required_artifacts(self, artifacts: List) -> List[str]:
        """
        Get list of artifact names that require admin privileges.

        Args:
            artifacts: List of Artifact objects

        Returns:
            List of artifact names requiring admin
        """
        return [a.name for a in artifacts if hasattr(a, 'required_admin') and a.required_admin]

    def calculate_estimated_size(self, artifacts: List) -> int:
        """
        Calculate estimated total size of all enabled artifacts.

        Args:
            artifacts: List of Artifact objects

        Returns:
            Estimated total size in bytes
        """
        total_size = 0
        for artifact in artifacts:
            if artifact.enabled and hasattr(artifact, 'estimated_size'):
                total_size += artifact.estimated_size
        return total_size

    def check_available_space(self, output_directory: str, estimated_size: int) -> Tuple[bool, int, str]:
        """
        Check if sufficient disk space is available.

        Args:
            output_directory: Target output directory
            estimated_size: Estimated size needed in bytes

        Returns:
            Tuple of (sufficient: bool, available_bytes: int, warning_message: str)
        """
        try:
            # Get disk usage for the output directory
            usage = shutil.disk_usage(output_directory)
            available_bytes = usage.free

            # Calculate required space with 10% buffer
            required_with_buffer = int(estimated_size * 1.1)

            if available_bytes < required_with_buffer:
                warning = (
                    f"[WARNING] Insufficient disk space!\n"
                    f"  Estimated size: {self._format_size(estimated_size)}\n"
                    f"  Required (with 10% buffer): {self._format_size(required_with_buffer)}\n"
                    f"  Available: {self._format_size(available_bytes)}\n"
                    f"  Shortfall: {self._format_size(required_with_buffer - available_bytes)}"
                )
                return False, available_bytes, warning

            return True, available_bytes, ""

        except Exception as e:
            warning = f"Warning: Could not check disk space: {e}"
            return True, 0, warning  # Assume sufficient if check fails

    def _format_size(self, size_bytes: int) -> str:
        """
        Format byte size as human-readable string.

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted string like "1.5 GB"
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def log(self, message: str):
        """Log a message to the case log (crow_claw.log) and the status line.

        It used to print only - nothing reached a log file, and in the
        windowless build nothing reached anything at all.
        """
        if self.verbose:
            logger.info("%s", message)
        if self.status_callback:
            self.status_callback(message)

    def collect_artifacts(
        self,
        artifacts: List,
        output_directory: str,
        windows_partition: str = "C:",
        handle_locked_files: str = "skip",  # "skip", "lock", "admin"
        hard_fail_on_low_space: bool = False
    ) -> Tuple[bool, CollectionStatistics]:
        """Collect, with a chain-of-custody record around the whole run.

        The record (utils/custody.py) is opened before the first file is read
        and closed after the last shadow copy this run created is deleted -
        including when the collection fails part-way - so it always says what
        was taken and what was changed on the target.
        """
        self.custody_path = None
        self.custody_summary = None
        rec = None
        if _custody is not None:
            try:
                rec = _custody.begin(
                    _case_root(output_directory), "crow-claw live collection",
                    options={
                        "windows_partition": windows_partition,
                        "handle_locked_files": handle_locked_files,
                        "include_browser_cache": self.include_browser_cache,
                        "artifacts": [a.name for a in artifacts if getattr(a, "enabled", False)],
                        "administrator": self.is_admin,
                    },
                    output_dir=output_directory)
                for warning in rec.data["warnings"]:
                    self.log("[WARNING] " + warning)
                    self.statistics.add_warning(warning)
            except Exception as e:
                logger.warning("Chain-of-custody record not started: %s", e)
                rec = None
        status = "failed"
        try:
            ok, stats = self._collect_artifacts(
                artifacts, output_directory, windows_partition,
                handle_locked_files, hard_fail_on_low_space)
            status = stats.get_status().lower()
            return ok, stats
        finally:
            # Snapshots this run created come off the target before the record
            # closes, so the record shows them deleted (or left behind).
            try:
                deleted = delete_created_shadow_copies()
                for sid, gone in deleted.items():
                    self.log(("[OK] Deleted the shadow copy this collection created: %s" if gone
                              else "[WARNING] Could not delete shadow copy %s - it is still on "
                                   "the target") % sid)
            except Exception as e:
                logger.error("Shadow copy cleanup failed: %s", e)
            if rec is not None:
                try:
                    # Per artifact, so one that found nothing (no paths, not
                    # elevated) is in the record, not only the files that came.
                    rec.data["artifacts"] = [
                        {"name": r.artifact_name, "type": r.artifact_type,
                         "status": r.status.value, "files": r.files_collected,
                         "bytes": r.bytes_collected, "errors": list(r.errors)[:20]}
                        for r in self.collection_results]
                    self.custody_summary = rec.summary()
                    self.custody_path = _custody.end(status)
                    self.log("[OK] Chain-of-custody record: %s" % self.custody_path)
                except Exception as e:
                    logger.error("Chain-of-custody record not written: %s", e)

    def _record_copy(self, source, dest, access_result, times, copy_sha256=None):
        """Add one copied file to the custody record; returns a problem or None."""
        rec = _custody.active() if _custody is not None else None
        if rec is None:
            return None
        try:
            entry = rec.add_source(
                source, copy=dest, method=_method(access_result), times=times,
                read_from=getattr(access_result, "read_path", None),
                shadow_copy_id=getattr(access_result, "vss_shadow_copy_id", None),
                shadow_copy_created_utc=getattr(access_result, "vss_shadow_copy_created", None),
                copy_sha256=copy_sha256)
        except Exception as e:
            logger.warning("Custody entry for %s not recorded: %s", source, e)
            return None
        if entry.get("verified") is False:
            return ("SHA-256 of the copy differs from the source (%s) - see the "
                    "chain-of-custody record" % os.path.basename(source))
        return None

    @staticmethod
    def _times_before(source):
        """MACB times of the source, read before it is copied (custody)."""
        if _custody is None or _custody.active() is None:
            return None
        return _custody.file_times(source)

    def _collect_artifacts(
        self,
        artifacts: List,
        output_directory: str,
        windows_partition: str = "C:",
        handle_locked_files: str = "skip",  # "skip", "lock", "admin"
        hard_fail_on_low_space: bool = False
    ) -> Tuple[bool, CollectionStatistics]:
        """
        Collect all enabled artifacts.

        Args:
            artifacts: List of Artifact objects to collect
            output_directory: Root output directory for collected artifacts
            windows_partition: Windows partition (e.g., "C:")
            handle_locked_files: Strategy for locked files
            hard_fail_on_low_space: If True, stop collection if space is insufficient

        Returns:
            Tuple of (success: bool, statistics: CollectionStatistics)
        """
        self.log("Starting artifact collection...")
        self.statistics = CollectionStatistics()
        self.collection_results = []
        self.statistics.start_time = _now()

        # Count total artifacts
        enabled_artifacts = [a for a in artifacts if a.enabled]
        self.statistics.total_artifacts_requested = len(enabled_artifacts)

        if not self.validate_output_directory(output_directory):
            self.statistics.add_error(f"Invalid output directory: {output_directory}")
            return False, self.statistics

        # Task 14.2: Detect Windows version
        windows_version = self.version_detector.detect_version()
        version_info = self.version_detector.get_version_info()
        self.log(f"Detected: {self.version_detector.get_version_string(windows_version)}")

        # Task 12.2: Display admin warning if not elevated
        if not self.is_admin:
            admin_required = self.get_admin_required_artifacts(enabled_artifacts)
            if admin_required:
                warning = (
                    f"[WARNING] Not running as administrator!\n"
                    f"  The following artifacts require elevation and will be skipped:\n"
                )
                for artifact_name in admin_required:
                    warning += f"    - {artifact_name}\n"
                self.log(warning)
                self.statistics.add_warning(warning)

        # Task 13.1: Check disk space before collection
        estimated_size = self.calculate_estimated_size(enabled_artifacts)
        sufficient_space, available_bytes, space_warning = self.check_available_space(
            output_directory, estimated_size
        )

        if not sufficient_space:
            self.log(space_warning)
            self.statistics.add_warning(space_warning)

            if hard_fail_on_low_space:
                self.log("[CRITICAL] Stopping collection due to insufficient disk space (hard_fail_on_low_space=True)")
                self.statistics.add_error("Collection stopped: Insufficient disk space")
                return False, self.statistics
            else:
                self.log("[WARNING] Proceeding with collection despite low space. Monitor disk usage carefully.")

        # Collect each artifact. The percent is what is DONE: (idx-1)/N as an
        # artifact starts, idx/N once it ends - it used to be idx/N at the
        # start, so the bar read 100% as the last (longest) artifact began.
        total_enabled = len(enabled_artifacts)
        for idx, artifact in enumerate(enabled_artifacts, 1):
            progress = int(((idx - 1) / total_enabled) * 100)
            if self.artifact_callback:
                try:
                    self.artifact_callback(idx, total_enabled, artifact.name)
                except Exception:
                    pass
            if self.progress_callback:
                self.progress_callback(progress)

            self.log(f"Collecting: {artifact.name} ({idx}/{len(enabled_artifacts)})")

            # Task 12.2: Skip admin-required artifacts if not admin
            if hasattr(artifact, 'required_admin') and artifact.required_admin and not self.is_admin:
                result = ArtifactCollectionResult(
                    artifact_name=artifact.name,
                    artifact_type=artifact.artifact_type.value if hasattr(artifact, 'artifact_type') else "unknown",
                    source_paths=artifact.get_all_paths() if hasattr(artifact, 'get_all_paths') else [],
                    dest_path="",
                    status=CollectionStatus.SKIPPED,
                    timestamp=_now()
                )
                result.errors.append(
                    f"Skipped: Requires administrator privileges. Please restart as administrator to collect this artifact."
                )
                self.collection_results.append(result)
                self.statistics.total_skipped += 1
                self.log(f"[SKIPPED] {artifact.name}: Requires admin privileges")
                if self.progress_callback:
                    self.progress_callback(int((idx / total_enabled) * 100))
                continue

            # Report collection start
            self.status_reporter.report_artifact_collection(
                artifact.name,
                "Collecting...",
                None,
                progress
            )

            result = self.collect_single_artifact(
                artifact, output_directory, windows_partition, handle_locked_files
            )
            self.collection_results.append(result)

            if result.status == CollectionStatus.SUCCESS:
                self.statistics.total_artifacts_collected += 1
                self.statistics.total_files_collected += result.files_collected
                self.statistics.total_bytes_collected += result.bytes_collected

                # Get access method used
                access_method = "standard"
                if hasattr(result, 'access_methods') and result.access_methods:
                    access_method = result.access_methods[0]  # Use first method

                # Report successful collection
                self.status_reporter.report_collection_complete(
                    artifact.name,
                    access_method,
                    result.files_collected,
                    result.bytes_collected
                )
            elif result.status == CollectionStatus.PARTIAL_SUCCESS:
                self.statistics.total_artifacts_collected += 1
                self.statistics.total_files_collected += result.files_collected
                self.statistics.total_bytes_collected += result.bytes_collected

                # Log errors for partial success
                for error in result.errors:
                    self.statistics.add_error(error)
                    self.status_reporter.report_error(artifact.name, error)
            elif result.status == CollectionStatus.SKIPPED:
                self.statistics.total_skipped += 1
            else:
                for error in result.errors:
                    self.statistics.add_error(error)
                    # Report error immediately
                    self.status_reporter.report_error(artifact.name, error)

            if self.progress_callback:
                self.progress_callback(int((idx / total_enabled) * 100))

        # Finalize statistics
        self.statistics.end_time = _now()
        self.statistics.duration_seconds = (
            self.statistics.end_time - self.statistics.start_time
        ).total_seconds()

        success = self.statistics.total_artifacts_collected >= len(enabled_artifacts) * 0.5
        self.log(f"Collection complete: {self.statistics.get_status()}")

        # Report collection summary. Its totals are the statistics' (which
        # count SUCCESS and PARTIAL_SUCCESS); the reporter's own running totals
        # only ever saw full successes, so a run with 52,969 files said 534.
        # "Failed" is failed ARTIFACTS - it used to be the error count.
        self.status_reporter.total_files_collected = self.statistics.total_files_collected
        self.status_reporter.total_bytes_collected = self.statistics.total_bytes_collected
        failed_artifacts = sum(1 for r in self.collection_results
                               if r.status == CollectionStatus.FAILED)
        self.status_reporter.report_collection_summary(
            total_artifacts=len(enabled_artifacts),
            successful=self.statistics.total_artifacts_collected,
            failed=failed_artifacts,
            duration_seconds=self.statistics.duration_seconds,
            access_method_stats=self.access_method_stats
        )

        if self.progress_callback:
            self.progress_callback(100)

        return success, self.statistics

    def collect_single_artifact(
        self,
        artifact,
        output_directory: str,
        windows_partition: str = "C:",
        handle_locked_files: str = "skip"
    ) -> ArtifactCollectionResult:
        """
        Collect a single artifact using file access strategies and validation.

        Args:
            artifact: Artifact object to collect
            output_directory: Root output directory
            windows_partition: Windows partition
            handle_locked_files: How to handle locked files

        Returns:
            ArtifactCollectionResult with collection details
        """
        start_time = _now()

        # DEBUG: Log artifact collection start
        self.log(f"[COLLECTOR] collect_single_artifact START: {artifact.name}")
        self.log(f"[COLLECTOR] Artifact type: {artifact.artifact_type.value if hasattr(artifact, 'artifact_type') else 'unknown'}")

        result = ArtifactCollectionResult(
            artifact_name=artifact.name,
            artifact_type=artifact.artifact_type.value if hasattr(artifact, 'artifact_type') else "unknown",
            source_paths=artifact.get_all_paths() if hasattr(artifact, 'get_all_paths') else [],
            dest_path="",
            status=CollectionStatus.PENDING,
            timestamp=start_time
        )

        # Special handling for partition info artifact
        if hasattr(artifact, 'artifact_type') and artifact.artifact_type.value == "PartitionInfo":
            return self._collect_partition_info(artifact, output_directory, result, start_time)

        # Browser profiles keep their folder tree (see _collect_preserved_tree).
        if getattr(artifact, "preserve_tree", False):
            return self._collect_preserved_tree(
                artifact, output_directory, windows_partition, result, start_time)

        # DEBUG: Log source paths
        source_paths = artifact.get_all_paths() if hasattr(artifact, 'get_all_paths') else []
        self.log(f"[COLLECTOR] Source paths from artifact: {source_paths}")

        try:
            # Create output subdirectory
            artifact_dir = os.path.join(
                output_directory,
                artifact.artifact_type.value if hasattr(artifact, 'artifact_type') else "unknown"
            )
            Path(artifact_dir).mkdir(parents=True, exist_ok=True)
            result.dest_path = artifact_dir

            # Expand and validate paths
            expanded_paths = self.expand_artifact_paths(
                artifact.get_all_paths() if hasattr(artifact, 'get_all_paths') else [],
                windows_partition
            )

            if not expanded_paths:
                result.status = CollectionStatus.SKIPPED
                result.errors.append("No valid paths found for this artifact")
                return result

            # Collect files
            files_collected = 0
            bytes_collected = 0
            errors = []
            access_methods_used = set()  # Track all methods used
            total_files_to_collect = len(expanded_paths)  # Track total for progress

            # Log collection start
            self.log(f"[COLLECTOR] Starting collection of {total_files_to_collect} files")

            # Progress reporting configuration for large collections
            progress_update_interval = 10 if total_files_to_collect > 100 else 1  # Update every 10 files if > 100 total
            last_progress_report = 0

            # Safety check for very large collections
            if total_files_to_collect > 2000:
                self.log(f"[WARNING] Large collection detected ({total_files_to_collect} files)")
                self.log(f"[WARNING] This may take a while. Consider collecting in smaller batches.")

            try:
                for idx, source_path in enumerate(expanded_paths, 1):
                    try:
                        # Task 13.2: Check for disk full errors
                        if os.path.isfile(source_path):
                            # Report real-time progress for multi-file artifacts
                            # For large collections (like Recycle Bin), update less frequently to avoid GUI flooding
                            should_report_progress = (
                                total_files_to_collect > 1 and
                                (idx - last_progress_report >= progress_update_interval or idx == 1 or idx == total_files_to_collect)
                            )

                            if should_report_progress:
                                try:
                                    percent = int((idx / total_files_to_collect) * 100)
                                    remaining = total_files_to_collect - idx
                                    self.status_reporter.display_status(
                                        f"[{idx}/{total_files_to_collect}] {artifact.name}: Collecting... "
                                        f"({percent}% complete, {remaining} files remaining)"
                                    )
                                    last_progress_report = idx
                                except Exception as status_error:
                                    # Don't crash on status reporting errors
                                    self.log(f"[WARNING] Status report error: {status_error}")

                            # Copy single file using file accessor with retry
                            artifact_type = artifact.artifact_type.value if hasattr(artifact, 'artifact_type') else "unknown"

                            # DEBUG: Log source_path and filename extraction
                            self.log(f"[COLLECTOR] Processing source_path: {source_path}")
                            self.log(f"[COLLECTOR] Artifact type: {artifact_type}")

                            # Use file accessor for better access strategies
                            filename = os.path.basename(source_path)
                            self.log(f"[COLLECTOR] Extracted filename: {filename}")

                            # An NTFS stream name (C:\$Extend\$UsnJrnl:$J) must not
                            # reach the copy's name: a ':' there writes an
                            # alternate data stream and leaves the file 0 bytes.
                            # "$UsnJrnl_$J" - the name image extraction gives it.
                            if ":" in filename:
                                filename = filename.replace(":", "_")
                                self.log(f"[COLLECTOR] Stream name made a file name: {filename}")

                            # Per-user files (hives + logs, LNK, Jump Lists)
                            # keep their owner's folder, so a hive stays
                            # beside its own logs (user_artifact_paths).
                            dest_file_path = None
                            if artifact_type in PER_USER_TYPES:
                                placer = self._user_placer_for(output_directory)
                                dest_file_path = placer.destination(
                                    os.path.basename(artifact_dir), source_path,
                                    "live:" + windows_partition)
                                if dest_file_path:
                                    os.makedirs(os.path.dirname(dest_file_path), exist_ok=True)
                                    placer.save()
                            if not dest_file_path:
                                dest_file_path = self._unique_destination(artifact_dir, filename)
                            self.log(f"[COLLECTOR] Destination file path: {dest_file_path}")

                            try:
                                times_before = self._times_before(source_path)
                                # Use file accessor with retry logic
                                access_result = self.file_accessor.access_file_with_retry(
                                    source_path,
                                    dest_file_path,
                                    artifact_type,
                                    max_retries=3
                                )

                                if access_result.success:
                                    files_collected += 1
                                    bytes_collected += access_result.file_size
                                    access_methods_used.add(access_result.strategy_used)

                                    # Update access method statistics
                                    if access_result.strategy_used in self.access_method_stats:
                                        self.access_method_stats[access_result.strategy_used] += 1

                                    # Report progress after collecting files (batched for large collections)
                                    if total_files_to_collect > 1 and (files_collected % progress_update_interval == 0 or idx == total_files_to_collect):
                                        try:
                                            percent = int((idx / total_files_to_collect) * 100)
                                            size_formatted = self.status_reporter.format_size(bytes_collected)
                                            self.status_reporter.display_status(
                                                f"[{idx}/{total_files_to_collect}] {artifact.name}: Collected {files_collected} files "
                                                f"({size_formatted}, {percent}% complete)"
                                            )
                                        except Exception as status_error:
                                            # Don't crash on status reporting errors
                                            self.log(f"[WARNING] Status report error: {status_error}")

                                    # Task 14.1: Validate collected file - every type.
                                    # The skip list here named types that do not
                                    # exist ('prefetch', 'lnk_files'...; the values
                                    # are "Prefetch", "link_jumplist"), and the
                                    # validator compared enums to these strings, so
                                    # no header was ever really checked. Zero-byte
                                    # files (empty $R, .LOG2) are a warning there.
                                    copy_sha256 = None
                                    try:
                                        validation_result = self.validator.validate_artifact(
                                            dest_file_path,
                                            artifact_type,
                                            source_file_size=(times_before or {}).get("size")
                                            if _method(access_result) == "standard" else None
                                        )
                                        copy_sha256 = validation_result.sha256_hash

                                        # Record validation warnings
                                        if validation_result.warnings:
                                            for warning in validation_result.warnings:
                                                if warning != "File size is zero bytes":
                                                    errors.append(f"Validation warning for {filename}: {warning}")

                                        if validation_result.errors:
                                            for error in validation_result.errors:
                                                errors.append(f"Validation error for {filename}: {error}")
                                    except Exception as val_error:
                                        # Don't crash on validation errors
                                        self.log(f"[WARNING] Validation error for {filename}: {val_error}")
                                        errors.append(f"Validation error for {filename}: {str(val_error)}")

                                    problem = self._record_copy(source_path, dest_file_path, access_result,
                                                                times_before, copy_sha256)
                                    if problem:
                                        errors.append(problem)
                                else:
                                    error_msg = access_result.error or "Unknown error"
                                    errors.append(f"Failed to collect {source_path}: {error_msg}")
                                    if _custody is not None and _custody.active() is not None:
                                        _custody.active().add_failure(source_path, error_msg,
                                                                      _method(access_result))

                            except OSError as e:
                                # Task 13.2: Detect disk space exhaustion
                                if hasattr(e, 'winerror') and e.winerror == 112:  # ERROR_DISK_FULL
                                    error_msg = f"[WARNING] DISK FULL: Collection stopped at {source_path}"
                                    errors.append(error_msg)
                                    self.statistics.add_error(error_msg)
                                    # Stop collecting this artifact
                                    break
                                else:
                                    errors.append(f"OS error collecting {source_path}: {str(e)}")
                            except Exception as file_error:
                                # Catch any other file access errors
                                error_msg = f"Unexpected error collecting {source_path}: {str(file_error)}"
                                errors.append(error_msg)
                                self.log(f"[ERROR] {error_msg}")

                        elif os.path.isdir(source_path):
                            # Copy directory recursively
                            self.log(f"[COLLECTOR] Processing directory: {source_path}")
                            try:
                                success, count, size, dir_errors = self.copy_directory_safe(
                                    source_path, artifact_dir, handle_locked_files
                                )
                                self.log(f"[COLLECTOR] Directory result: success={success}, files={count}, size={size}, errors={len(dir_errors)}")
                                if success or count > 0:
                                    files_collected += count
                                    bytes_collected += size
                                if dir_errors:
                                    for dir_error in dir_errors:
                                        self.log(f"[ERROR] Directory error: {dir_error}")
                                errors.extend(dir_errors)
                            except Exception as dir_error:
                                error_msg = f"Error copying directory {source_path}: {str(dir_error)}"
                                errors.append(error_msg)
                                self.log(f"[ERROR] {error_msg}")

                        else:
                            # Path is neither a file nor a directory - log as warning
                            # This can happen with special paths, non-existent paths, or permission issues
                            if os.path.exists(source_path):
                                self.log(f"[WARNING] Skipping {source_path}: Not a regular file or directory")
                            else:
                                self.log(f"[WARNING] Skipping {source_path}: Path does not exist")
                            # Don't add to errors list - this is expected for some artifact patterns

                    except Exception as e:
                        error_msg = f"Error processing {source_path}: {str(e)}"
                        errors.append(error_msg)
                        self.log(error_msg)
                        # Continue with next file instead of crashing

            except Exception as loop_error:
                # Catch any errors in the entire collection loop
                error_msg = f"Critical error in collection loop: {str(loop_error)}"
                errors.append(error_msg)
                self.log(f"[ERROR] {error_msg}")
                import traceback
                self.log(f"[ERROR] Traceback: {traceback.format_exc()}")

            result.files_collected = files_collected
            result.bytes_collected = bytes_collected
            result.errors = errors

            # Store access methods used (for reporting)
            if hasattr(result, '__dict__'):
                result.access_methods = list(access_methods_used) if access_methods_used else ["standard"]

            # Determine final status
            if files_collected == 0:
                result.status = CollectionStatus.FAILED
            elif len(errors) > 0:
                result.status = CollectionStatus.PARTIAL_SUCCESS
            else:
                result.status = CollectionStatus.SUCCESS

        except Exception as e:
            error_msg = f"Critical error collecting {artifact.name}: {str(e)}"
            result.status = CollectionStatus.FAILED
            result.errors.append(error_msg)
            self.log(error_msg)

        result.duration_seconds = (_now() - start_time).total_seconds()
        return result

    def _collect_preserved_tree(self, artifact, output_directory, windows_partition, result, start_time):
        """Copy whole folder trees, keeping each file's path below the volume.

        Browser evidence is only meaningful in place: every profile has its own
        ``History``, and the folders above it say which user, browser and
        profile it belongs to. Flattening to ``<type>/<basename>`` (as every
        other artifact is collected) would leave one ``History`` and lose the
        rest. Files land at ``<output>/Browser/live/Users/<name>/AppData/...``,
        the layout the Offline Importer and image extraction also write, and
        each file goes through the file accessor so a locked database (a
        running browser) still falls back to VSS / raw disk.
        """
        patterns = list(artifact.get_all_paths())
        if self.include_browser_cache:
            patterns += list(getattr(artifact, "cache_paths", []) or [])
        volume_root = os.path.join(windows_partition.rstrip("\\/") + os.sep)
        dest_root = os.path.join(output_directory, _BROWSER_DIR, _BROWSER_SOURCE_TAG)
        result.dest_path = dest_root
        # One root per real folder: a junction (Local\Application Data -> Local)
        # matches the same profile a second time under another name.
        by_real = {}
        for p in self.expand_artifact_paths(patterns, windows_partition):
            p = os.path.normpath(p)
            if not os.path.isdir(p) or browser_root_excluded(p):
                continue
            real = os.path.normcase(os.path.realpath(p))
            if real not in by_real or real == os.path.normcase(p):
                by_real[real] = p
        roots = sorted(by_real.values())
        # A root nested inside another root would be walked twice.
        roots = [r for r in roots
                 if not any(r != o and r.lower().startswith(o.lower() + os.sep) for o in roots)]
        if not roots:
            result.status = CollectionStatus.SKIPPED
            result.errors.append("No valid paths found for this artifact")
            result.duration_seconds = (_now() - start_time).total_seconds()
            return result

        artifact_type = artifact.artifact_type.value
        files_collected = bytes_collected = failed = 0
        errors, methods = [], set()
        disk_full = False
        copied_now = set()
        for root in roots:
            if disk_full:
                break
            self.status_reporter.display_status(f"{artifact.name}: {root}")
            for cur, dirs, files in os.walk(root):
                if disk_full:
                    break
                dirs[:] = [d for d in dirs if not browser_dir_skipped(d, self.include_browser_cache)
                           and not _is_link(os.path.join(cur, d))]
                for name in files:
                    src = os.path.join(cur, name)
                    try:
                        rel = os.path.relpath(src, volume_root)
                    except ValueError:      # another drive: not below this volume
                        continue
                    dst = os.path.join(dest_root, rel)
                    # An earlier run's copy is refreshed, not kept: a second
                    # collection is taken to capture what changed since.
                    if dst in copied_now:
                        continue
                    copied_now.add(dst)
                    times_before = self._times_before(src)
                    try:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        res = self.file_accessor.access_file_with_retry(
                            src, dst, artifact_type, max_retries=1)
                    except OSError as e:
                        if getattr(e, "winerror", None) == 112:    # ERROR_DISK_FULL
                            errors.append(f"[WARNING] DISK FULL: Collection stopped at {src}")
                            self.statistics.add_error(errors[-1])
                            disk_full = True
                            break
                        res = None
                        err = str(e)
                    except Exception as e:
                        res = None
                        err = str(e)
                    # The strategies report a full disk in the result, not by
                    # raising; stop rather than fail every remaining file.
                    msg = (res.error or "").lower() if res is not None and not res.success else ""
                    if "code 112" in msg or "disk full" in msg or "not enough space" in msg:
                        errors.append(f"[WARNING] DISK FULL: Collection stopped at {src}")
                        self.statistics.add_error(errors[-1])
                        disk_full = True
                        break
                    if res is not None and res.success:
                        files_collected += 1
                        try:
                            bytes_collected += os.path.getsize(dst)
                        except OSError:
                            pass
                        methods.add(res.strategy_used or "standard")
                        # strategy_used is "vss" / "raw_disk": the old "VSS" in
                        # / "Raw" in tests never matched, so every browser file
                        # was counted as a standard copy.
                        method = _method(res)
                        if method == "vss":
                            self.access_method_stats["vss"] += 1
                        elif method == "raw_disk":
                            self.access_method_stats["raw_disk"] += 1
                        else:
                            self.access_method_stats["standard"] += 1
                        problem = self._record_copy(src, dst, res, times_before)
                        if problem and failed + len(errors) <= 50:
                            errors.append(problem)
                    else:
                        failed += 1
                        if _custody is not None and _custody.active() is not None:
                            _custody.active().add_failure(
                                src, (res.error if res is not None else err) or "Unknown error",
                                _method(res) if res is not None else None)
                        # Keep the report readable: a profile is thousands of files.
                        if failed <= 50:
                            errors.append(f"Failed to collect {src}: "
                                          f"{(res.error if res is not None else err) or 'Unknown error'}")
        if failed > 50:
            errors.append(f"... and {failed - 50} more browser file(s) could not be copied")

        result.files_collected = files_collected
        result.bytes_collected = bytes_collected
        result.errors = errors
        result.access_methods = sorted(methods) if methods else ["standard"]
        if files_collected == 0:
            result.status = CollectionStatus.FAILED
        elif errors:
            result.status = CollectionStatus.PARTIAL_SUCCESS
        else:
            result.status = CollectionStatus.SUCCESS
        result.duration_seconds = (_now() - start_time).total_seconds()
        return result

    def expand_artifact_paths(
        self, paths: List[str], windows_partition: str = "C:"
    ) -> List[str]:
        """
        Expand artifact paths with variables and wildcards.

        Args:
            paths: List of paths with possible variables
            windows_partition: Windows partition

        Returns:
            List of expanded, valid paths
        """
        expanded = []

        # DEBUG: Log path expansion
        self.log(f"[COLLECTOR] expand_artifact_paths called with {len(paths)} paths")
        for path in paths:
            self.log(f"[COLLECTOR] Input path: {path}")

        for path in paths:
            try:
                # Replace partition variable
                expanded_path = path.replace("{PARTITION}", windows_partition)
                self.log(f"[COLLECTOR] After partition replacement: {expanded_path}")

                # Expand environment variables
                expanded_path = os.path.expandvars(expanded_path)
                self.log(f"[COLLECTOR] After expandvars: {expanded_path}")

                # Handle wildcards
                if "*" in expanded_path or "?" in expanded_path:
                    try:
                        matches = glob.glob(expanded_path, recursive=True)
                        self.log(f"[COLLECTOR] Wildcard matches: {len(matches)} files")

                        # Warning for very large collections instead of hard truncation
                        if len(matches) > 10000:
                            self.log(f"[WARNING] Large wildcard match detected: {len(matches)} files.")
                            self.log(f"[WARNING] Processing many files may increase memory usage and collection time.")

                        expanded.extend(matches)
                    except Exception as glob_error:
                        self.log(f"[ERROR] Glob pattern failed for {expanded_path}: {glob_error}")
                        import traceback
                        self.log(f"[ERROR] Traceback: {traceback.format_exc()}")
                        # Continue with other paths instead of crashing
                # CRITICAL FIX: Don't filter out raw device paths and NTFS streams
                # Raw device paths like \\.\C:\$MFT and NTFS streams like $Extend\$UsnJrnl:$J
                # don't exist in the standard Win32 namespace but are valid for RawDiskAccessStrategy
                elif os.path.exists(expanded_path) or self._is_raw_device_path(expanded_path):
                    is_raw = self._is_raw_device_path(expanded_path)
                    exists = os.path.exists(expanded_path)
                    self.log(f"[COLLECTOR] Path check: exists={exists}, is_raw={is_raw}")
                    self.log(f"[COLLECTOR] Adding path: {expanded_path}")
                    expanded.append(expanded_path)
                else:
                    self.log(f"[COLLECTOR] Path REJECTED (not exists and not raw): {expanded_path}")

            except Exception as e:
                self.log(f"Warning: Could not expand path {path}: {e}")

        self.log(f"[COLLECTOR] expand_artifact_paths returning {len(expanded)} paths")
        for path in expanded:
            self.log(f"[COLLECTOR] Expanded path: {path}")

        # Sorted, not set order: set order changes from process to process.
        return sorted(set(expanded))

    def _collect_partition_info(
        self,
        artifact,
        output_directory: str,
        result,
        start_time
    ) -> ArtifactCollectionResult:
        """
        Collect partition and disk information using the partition analyzer.

        Args:
            artifact: Partition info artifact object
            output_directory: Root output directory
            result: ArtifactCollectionResult to populate
            start_time: Collection start time

        Returns:
            ArtifactCollectionResult with partition analysis results
        """
        try:
            # Import partition analyzer
            import sys
            import os
            analyzer_path = os.path.join(os.path.dirname(__file__), '..', '..')
            if analyzer_path not in sys.path:
                sys.path.insert(0, analyzer_path)

            from partition_analyzer import PartitionAnalyzer

            # Create output directory for partition info
            artifact_dir = os.path.join(
                output_directory,
                "PartitionInfo"
            )
            Path(artifact_dir).mkdir(parents=True, exist_ok=True)
            result.dest_path = artifact_dir

            # Initialize partition analyzer
            self.log("Analyzing disk partitions and volumes...")
            self.status_reporter.display_status("Analyzing disk partitions and volumes...")

            analyzer = PartitionAnalyzer()

            # Get disk and partition information
            disks = analyzer.get_disks_with_partitions()

            if not disks:
                result.status = CollectionStatus.FAILED
                result.errors.append("No disks found or unable to analyze partitions")
                return result

            # Save to SQLite database
            db_path = os.path.join(artifact_dir, "partition_analysis.db")
            success = analyzer.save_to_database(db_path, disks, source="acquisition")

            if not success:
                result.status = CollectionStatus.FAILED
                result.errors.append("Failed to save partition data to database")
                return result

            # Also save as JSON for easy viewing
            json_path = os.path.join(artifact_dir, "partition_analysis.json")
            import json
            output_data = {
                'boot_mode': analyzer.boot_mode,
                'collection_timestamp': start_time.isoformat(),
                'disks': [disk.to_dict() for disk in disks]
            }
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2)

            # Generate summary text file
            summary_path = os.path.join(artifact_dir, "partition_summary.txt")
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("Partition and Disk Analysis Summary\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Collection Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"System Boot Mode: {analyzer.boot_mode}\n")
                f.write(f"Total Disks Found: {len(disks)}\n\n")

                for disk in disks:
                    f.write(f"{'='*80}\n")
                    f.write(f"Disk {disk.disk_index}: {disk.model}\n")
                    f.write(f"{'='*80}\n")
                    f.write(f"  Size: {analyzer.format_size(disk.size)}\n")
                    f.write(f"  Interface: {disk.interface_type}\n")
                    f.write(f"  Partition Style: {disk.partition_style}\n")
                    f.write(f"  Boot Mode: {disk.boot_mode}\n")
                    if disk.serial_number:
                        f.write(f"  Serial Number: {disk.serial_number}\n")
                    if disk.disk_signature:
                        f.write(f"  Disk Signature: {disk.disk_signature}\n")
                    if disk.is_removable:
                        f.write(f"  Media Type: Removable\n")
                    if disk.is_usb:
                        f.write(f"  Interface: USB\n")
                    if disk.is_bootable:
                        f.write(f"  Bootable: Yes\n")

                    f.write(f"\n  Partitions: {len(disk.partitions)}\n")
                    f.write(f"  {'-'*76}\n")

                    for part in disk.partitions:
                        f.write(f"\n  Device: {part.device}\n")
                        if part.mountpoint:
                            f.write(f"    Mount Point: {part.mountpoint}\n")
                        f.write(f"    File System: {part.fstype}\n")
                        if part.volume_label:
                            f.write(f"    Volume Label: {part.volume_label}\n")
                        f.write(f"    Total Size: {analyzer.format_size(part.total_size)}\n")
                        if part.total_size > 0:
                            f.write(f"    Used: {analyzer.format_size(part.used_size)} ({part.percent_used}%)\n")
                        f.write(f"    Partition Type: {part.partition_type}\n")

                        flags = []
                        if part.is_boot:
                            flags.append("BOOT")
                        if part.is_system:
                            flags.append("SYSTEM")
                        if part.is_swap:
                            flags.append("SWAP")
                        if part.is_linux:
                            flags.append("LINUX")
                        if part.is_efi_system:
                            flags.append("EFI_SYSTEM")
                        if part.is_hidden:
                            flags.append("HIDDEN")

                        if flags:
                            f.write(f"    Flags: {', '.join(flags)}\n")

                    f.write("\n")

            # Update result
            result.files_collected = 3  # database, json, summary
            result.bytes_collected = os.path.getsize(db_path) + os.path.getsize(json_path) + os.path.getsize(summary_path)
            result.status = CollectionStatus.SUCCESS

            # Log summary
            total_partitions = sum(len(disk.partitions) for disk in disks)
            self.log(f"✓ Partition Analysis: {len(disks)} disk(s), {total_partitions} partition(s)")
            self.log(f"  - Database: {db_path}")
            self.log(f"  - JSON: {json_path}")
            self.log(f"  - Summary: {summary_path}")

        except Exception as e:
            error_msg = f"Error collecting partition information: {str(e)}"
            result.status = CollectionStatus.FAILED
            result.errors.append(error_msg)
            self.log(error_msg)
            import traceback
            self.log(traceback.format_exc())

        result.duration_seconds = (_now() - start_time).total_seconds()
        return result

    def _is_raw_device_path(self, path: str) -> bool:
        """Check if path is a raw device path or NTFS stream that requires special handling.

        Args:
            path: Path to check

        Returns:
            True if path is a raw device path or NTFS stream
        """
        path_lower = path.lower()
        # Raw device paths: \\.\C:\$MFT, \\.\PhysicalDrive0
        # NTFS streams: C:\$Extend\$UsnJrnl:$J
        return (
            path.startswith(r"\\.") or  # Fixed: removed trailing backslash
            "$mft" in path_lower or
            "$usnjrnl" in path_lower or
            ":$" in path  # NTFS alternate data streams
        )

    def _user_placer_for(self, output_directory: str) -> UserFolderPlacer:
        """One placer per output folder for the life of this collector."""
        placers = self.__dict__.setdefault("_user_placers", {})
        key = os.path.normcase(os.path.abspath(output_directory))
        if key not in placers:
            placers[key] = UserFolderPlacer(output_directory)
        return placers[key]

    @staticmethod
    def _unique_destination(dest_dir: str, filename: str) -> str:
        """``dest_dir/filename``, or ``name_copy``, ``name_copy2``, ... if taken.

        A single ``_copy`` suffix let the third file of a name overwrite the
        second.
        """
        dest = os.path.join(dest_dir, filename)
        if not os.path.exists(dest):
            return dest
        base, ext = os.path.splitext(filename)
        n = 1
        while True:
            suffix = "_copy" if n == 1 else "_copy%d" % n
            dest = os.path.join(dest_dir, f"{base}{suffix}{ext}")
            if not os.path.exists(dest):
                return dest
            n += 1

    def copy_file_safe(
        self, source_path: str, dest_dir: str, handle_locked: str = "skip"
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Safely copy a single file with error handling.

        Args:
            source_path: Source file path
            dest_dir: Destination directory
            handle_locked: How to handle locked files

        Returns:
            Tuple of (success: bool, file_size: int, error: str or None)
        """
        try:
            if not os.path.exists(source_path):
                return False, 0, f"Source file not found: {source_path}"

            if not os.path.isfile(source_path):
                return False, 0, f"Path is not a file: {source_path}"

            # Get file size
            file_size = os.path.getsize(source_path)

            # Create destination path
            dest_path = self._unique_destination(dest_dir, os.path.basename(source_path))
            times_before = self._times_before(source_path)

            # Try to copy
            try:
                shutil.copy2(source_path, dest_path)
                self._record_copy(source_path, dest_path, None, times_before)
                return True, file_size, None
            except PermissionError:
                if handle_locked == "skip":
                    if _custody is not None and _custody.active() is not None:
                        _custody.active().add_failure(source_path, "permission denied (locked)",
                                                      "standard")
                    return False, 0, f"Permission denied (file locked): {source_path}"
                elif handle_locked == "lock":
                    # Try to read-only copy
                    shutil.copyfile(source_path, dest_path)
                    self._record_copy(source_path, dest_path, None, times_before)
                    return True, file_size, None
                else:
                    # Try with admin operations (would require elevation)
                    return False, 0, f"Requires admin privileges: {source_path}"

        except Exception as e:
            error_msg = f"Error copying file {source_path}: {str(e)}"
            return False, 0, error_msg

    def copy_directory_safe(
        self, source_dir: str, dest_parent: str, handle_locked: str = "skip"
    ) -> Tuple[bool, int, int, List[str]]:
        """
        Safely copy a directory recursively.

        Args:
            source_dir: Source directory path
            dest_parent: Parent destination directory
            handle_locked: How to handle locked files

        Returns:
            Tuple of (success: bool, file_count: int, total_size: int, errors: List[str])
        """
        file_count = 0
        total_size = 0
        errors = []

        try:
            # Create destination
            dir_name = os.path.basename(source_dir)
            dest_dir = os.path.join(dest_parent, dir_name)
            Path(dest_dir).mkdir(parents=True, exist_ok=True)

            # Walk directory
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    source_file = os.path.join(root, file)
                    rel_path = os.path.relpath(source_file, source_dir)
                    dest_file = os.path.join(dest_dir, rel_path)

                    # Create subdirectories
                    Path(dest_file).parent.mkdir(parents=True, exist_ok=True)

                    # Copy file
                    success, size, error = self.copy_file_safe(
                        source_file, Path(dest_file).parent, handle_locked
                    )
                    if success:
                        file_count += 1
                        total_size += size
                    elif error:
                        errors.append(error)

            return True, file_count, total_size, errors

        except Exception as e:
            error_msg = f"Error copying directory {source_dir}: {str(e)}"
            errors.append(error_msg)
            return False, file_count, total_size, errors

    @staticmethod
    def validate_output_directory(path: str) -> bool:
        """
        Validate output directory is writable.

        Args:
            path: Directory path

        Returns:
            True if directory is valid and writable
        """
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            # Test write permission
            test_file = os.path.join(path, ".crow_claw_test")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            return True
        except Exception as e:
            return False

    def get_results_summary(self) -> Dict:
        """
        Get summary of collection results.

        Returns:
            Dictionary with collection summary
        """
        return {
            "statistics": self.statistics.get_summary(),
            "artifacts": [r.to_dict() for r in self.collection_results],
            "success": self.statistics.get_status() == "SUCCESS"
        }
