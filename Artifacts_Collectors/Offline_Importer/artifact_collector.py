"""
Artifact Collector Module

This module provides the core collection engine for scanning directories,
detecting artifact types, and copying them to the case directory structure.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CollectedArtifactInfo:
    """
    Information about a collected artifact.
    
    This dataclass holds metadata about each artifact collected during
    the import process, including source/destination paths, status,
    and integrity information.
    
    Attributes:
        source_path: Original path of the artifact file
        destination_path: Path where the artifact was copied in the case directory
        artifact_type: Type of artifact (Registry, Prefetch, JumpLists, MFT, USN, RecycleBin, AmCache, Unknown)
        file_size: Size of the artifact file in bytes
        file_hash: SHA256 hash of the file for integrity verification
        collection_status: Status of the collection operation (success, failed)
        error_message: Error message if collection failed, None otherwise
        timestamp: When the artifact was collected
    """
    source_path: str
    destination_path: str
    artifact_type: str
    file_size: int
    file_hash: str
    collection_status: str
    error_message: Optional[str]
    timestamp: datetime

import os
import shutil
import hashlib
from typing import Optional, Callable, List, Dict
from .artifact_type_detector import ArtifactTypeDetector, ArtifactDetectionResult
from .artifact_validator import ArtifactValidator, ValidationResult


@dataclass
class CollectionResult:
    """
    Result of an artifact collection operation.
    
    Attributes:
        total_found: Total number of artifacts found during scan
        total_collected: Total number of artifacts successfully copied
        failed: Number of artifacts that failed to copy
        artifacts: List of CollectedArtifactInfo for all processed artifacts
    """
    total_found: int
    total_collected: int
    failed: int
    artifacts: List[CollectedArtifactInfo]


try:
    from Artifacts_Collectors.browser_paths import (
        BROWSER_CASE_DIR, browser_path_info, browser_path_skipped, browser_source_tag)
except ImportError:  # run with Artifacts_Collectors itself on sys.path
    import sys as _sys
    _ac = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ac not in _sys.path:
        _sys.path.insert(0, _ac)
    from browser_paths import (BROWSER_CASE_DIR, browser_path_info, browser_path_skipped,
                               browser_source_tag)

try:
    from Artifacts_Collectors.user_artifact_paths import PER_USER_TYPES, UserFolderPlacer
except ImportError:
    from user_artifact_paths import PER_USER_TYPES, UserFolderPlacer


class ArtifactCollector:
    """
    Core collection engine for scanning directories, detecting artifact types,
    and copying them to the case directory structure.
    
    This class coordinates the artifact collection process:
    1. Scans source directories recursively (optional)
    2. Detects artifact types using ArtifactTypeDetector
    3. Applies artifact type filters
    4. Copies artifacts to case directory organized by type
    5. Calculates file hashes for integrity verification (optional)
    6. Reports progress via callbacks
    7. Handles errors gracefully (continues on individual file errors)
    """
    
    def __init__(self, case_root: str, calculate_hashes: bool = True, validate_artifacts: bool = True, scan_only: bool = False):
        """
        Initialize the artifact collector.
        
        Args:
            case_root: Root directory of the case where artifacts will be stored
            calculate_hashes: Whether to calculate SHA256 hashes for collected artifacts
            validate_artifacts: Whether to validate artifacts before collection
            scan_only: If True, only scan and detect artifacts without copying them
        """
        self.case_root = case_root
        self.target_artifacts_dir = os.path.join(case_root, 'live_acquisition')
        self.calculate_hashes = calculate_hashes
        self.validate_artifacts = validate_artifacts
        self.scan_only = scan_only  # Store scan_only mode
        self.detector = ArtifactTypeDetector()
        self.validator = ArtifactValidator()
        self.progress_callback: Optional[Callable[[str, int, int], None]] = None
        
        # Cancellation support
        self._cancelled = False

        # Browser trees: the "Include browser cache" toggle, the folder being
        # imported (a Users folder above it is the analyst's, not the
        # evidence's), and where each collected file's user folder came from.
        self.include_browser_cache = True
        self._browser_base = None
        self._browser_roots = {}    # source file -> (source user folder, case user folder)

        # Per-user files (hives + their logs, LNK, Jump Lists) keep their
        # owner's folder; see user_artifact_paths.
        self._user_placer = UserFolderPlacer(self.target_artifacts_dir)

        # Mapping of artifact types to their subdirectories in live_acquisition (input files)
        # Output databases go to Target_Artifacts
        self.artifact_directories = {
            'Registry': 'Registry_Hives',
            'Prefetch': 'Prefetch',
            'link_jumplist': 'C_AJL_Lnk',
            'MFT': 'MFT_USN',
            'USN': 'MFT_USN',
            'AmCache': 'AmCache',
            'RecycleBin': 'RecycleBin',
            'EVTX': 'EVTX_Logs',
            'SRUM': 'SRUM_Data',
            'LNK/Shortcut': 'Shortcuts',
            'ShimCache': 'ShimCache',
            # Browser profiles keep their tree below this folder (see
            # _browser_tree_destination) - never flattened by file name.
            'Browser': 'Browser',
            'Unknown': 'Unknown'
        }
        
        # Hash tracking for deduplication: hash -> file_path. Filled from the
        # case on first use (_is_duplicate), not here - every collector,
        # scan-only ones included, used to hash all of live_acquisition when
        # it was created.
        self.collected_hashes: Dict[str, str] = {}
        self._hashes_loaded = False

        # Live counts for the progress panel (found / copied / failed). The
        # coordinator only learned them at the very end, so they read 0 for
        # the whole run.
        self.live_counts = {"found": 0, "collected": 0, "failed": 0}
        # What a cancelled run had done by then (collect_from_directory).
        self.partial_result: Optional["CollectionResult"] = None
        
        # Ensure case directory structure exists (skip if scan_only)
        if not self.scan_only:
            self._ensure_case_structure()
    
    def _ensure_case_structure(self):
        """Create the case directory structure if it doesn't exist."""
        # Create live_acquisition directory
        os.makedirs(self.target_artifacts_dir, exist_ok=True)
        
        # Create subdirectories for each artifact type
        for subdir in self.artifact_directories.values():
            subdir_path = os.path.join(self.target_artifacts_dir, subdir)
            os.makedirs(subdir_path, exist_ok=True)

    def _load_existing_hashes(self):
        """
        Load existing artifact hashes from the case directory.

        This method scans the live_acquisition directory and calculates hashes
        for all existing artifacts to enable deduplication.
        """
        if not os.path.exists(self.target_artifacts_dir):
            return

        try:
            # Scan all artifact subdirectories
            for artifact_type, subdir in self.artifact_directories.items():
                # Browser trees are never deduplicated (identical bytes in two
                # profiles are two pieces of evidence), so their files must not
                # enter the registry either: a Prefetch file that happened to
                # match a browser file's bytes was being skipped as a
                # "duplicate". It also spares hashing thousands of cache files
                # every time a collector is created.
                if artifact_type == 'Browser':
                    continue
                artifact_dir = os.path.join(self.target_artifacts_dir, subdir)
                if not os.path.exists(artifact_dir):
                    continue

                # Scan all files in this artifact directory
                for root, _, files in os.walk(artifact_dir):
                    # Per-user trees are never deduplicated, so they do not
                    # enter the registry either (see _collect_user_file).
                    rel_root = os.path.relpath(root, artifact_dir).replace("/", "\\").lower()
                    if rel_root.split("\\")[0] in ("users", "windows"):
                        continue
                    for filename in files:
                        # Skip database files
                        if filename.endswith('.db'):
                            continue

                        file_path = os.path.join(root, filename)
                        try:
                            # Calculate hash for existing file
                            file_hash = self._calculate_file_hash(file_path)
                            if file_hash:
                                self.collected_hashes[file_hash] = file_path
                        except Exception:
                            # Skip files that can't be hashed
                            continue
        except Exception:
            # If loading fails, just start with empty hash set
            pass

    def _is_duplicate(self, file_hash: str) -> Optional[str]:
        """
        Check if a file with this hash has already been collected.

        Args:
            file_hash: SHA256 hash of the file

        Returns:
            Path to existing file if duplicate, None otherwise
        """
        if not self._hashes_loaded:
            self._hashes_loaded = True
            self._load_existing_hashes()
        return self.collected_hashes.get(file_hash)

    def _save_hash_registry(self):
        """
        Save the hash registry to a JSON file in the case directory.

        This allows persistence of deduplication information across sessions.
        """
        if not self._hashes_loaded:
            return          # never read: writing it would replace it with this run's part
        try:
            import json
            hash_file = os.path.join(self.case_root, 'artifact_hashes.json')
            with open(hash_file, 'w') as f:
                json.dump(self.collected_hashes, f, indent=2)
        except Exception:
            # Non-critical operation, don't fail if it doesn't work
            pass

    
    def set_progress_callback(self, callback: Callable[[str, int, int], None]):
        """
        Set callback for progress updates.
        
        Args:
            callback: Function that takes (current_file, processed_count, total_count)
        """
        self.progress_callback = callback

    
    def _scan_directory(self, source_dir: str, include_subdirs: bool = True) -> List[str]:
        """
        Scan directory for files, optionally including subdirectories.
        
        Args:
            source_dir: Directory to scan
            include_subdirs: Whether to scan subdirectories recursively
            
        Returns:
            List of file paths found in the directory
        """
        file_paths = []
        directories_scanned = set()
        
        if include_subdirs:
            # Recursive scan using os.walk()
            print(f"[SCAN] Starting recursive scan of: {source_dir}")
            for root, dirs, files in os.walk(source_dir):
                directories_scanned.add(root)
                for filename in files:
                    file_path = os.path.join(root, filename)
                    file_paths.append(file_path)
            
            # Log scan summary
            print(f"[SCAN] Scanned {len(directories_scanned)} directories (including subdirectories)")
            print(f"[SCAN] Found {len(file_paths)} total files")
        else:
            # Non-recursive scan - only files in the top-level directory
            print(f"[SCAN] Starting non-recursive scan of: {source_dir}")
            try:
                for item in os.listdir(source_dir):
                    item_path = os.path.join(source_dir, item)
                    if os.path.isfile(item_path):
                        file_paths.append(item_path)
                print(f"[SCAN] Found {len(file_paths)} files in top-level directory")
            except Exception as e:
                # Log error but don't fail - return what we have
                print(f"Error scanning directory {source_dir}: {e}")
        
        return file_paths

    
    def detect_artifact_type(self, file_path: str) -> ArtifactDetectionResult:
        """
        Detect the type of artifact from a file.
        
        This method delegates to the ArtifactTypeDetector for actual detection.
        
        Args:
            file_path: Path to the file to analyze
            
        Returns:
            ArtifactDetectionResult containing detection information
        """
        return self.detector.detect_artifact_type(file_path)

    
    def _should_collect_artifact(self, artifact_type: str, artifact_type_filter: Optional[str]) -> bool:
        """
        Determine if an artifact should be collected based on the filter.
        
        Args:
            artifact_type: Detected artifact type
            artifact_type_filter: Optional filter (e.g., "Registry", "Prefetch", or None for all)
            
        Returns:
            True if the artifact should be collected, False otherwise
        """
        # No filter means collect all artifacts
        if artifact_type_filter is None or artifact_type_filter == "All Types":
            return True
        
        # Map GUI filter names to internal types
        mapping = {
            "Registry Hives": "Registry",
            "Prefetch Files": "Prefetch",
            "Jump Lists": "link_jumplist",
            "Browsers": "Browser",
            "MFT Files": "MFT",
            "USN Journal": "USN",
            "Recycle Bin": "RecycleBin",
            "AmCache": "AmCache",
            "Event Logs": "EVTX",
            "SRUM": "SRUM",
        }

        # ShimCache lives in the SYSTEM hive: the detector types a SYSTEM file
        # found under a shimcache folder 'ShimCache' and any other one
        # 'Registry'. The filter used to map to 'Registry' alone, so it took
        # every hive and missed the 'ShimCache' ones.
        if artifact_type_filter == "ShimCache":
            return artifact_type == "ShimCache" or (
                artifact_type == "Registry" and getattr(self, "_current_name", "").upper().startswith("SYSTEM"))

        target_type = mapping.get(artifact_type_filter, artifact_type_filter)

        # Filter matches artifact type
        return artifact_type == target_type

    
    def _copy_artifact(self, source_path: str, destination_path: str) -> bool:
        """
        Copy artifact file to destination, preserving metadata.
        
        Uses shutil.copy2() to preserve file metadata (timestamps, permissions).
        
        Args:
            source_path: Source file path
            destination_path: Destination file path
            
        Returns:
            True if copy succeeded, False otherwise
        """
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(destination_path)
            os.makedirs(dest_dir, exist_ok=True)
            
            # Copy file with metadata preservation. A USN journal collected
            # before round 20 is a 0-byte file whose data sits in its NTFS
            # alternate data stream ":$J" - a plain copy kept only the empty
            # file, so the stream's bytes are what is copied.
            source = source_path
            try:
                if os.name == "nt" and os.path.getsize(source_path) == 0 \
                        and os.path.getsize(source_path + ":$J") > 0:
                    source = source_path + ":$J"
            except OSError:
                pass
            if source != source_path:
                shutil.copyfile(source, destination_path)
                shutil.copystat(source_path, destination_path)
            else:
                shutil.copy2(source_path, destination_path)
            return True
            
        except Exception as e:
            print(f"Error copying {source_path} to {destination_path}: {e}")
            return False

    
    def _normalize_artifact_type(self, artifact_type: str) -> str:
        """
        Normalize artifact type to match directory mapping.
        
        Handles variations like "EVTX (Security)" -> "EVTX", "Registry (SYSTEM hive)" -> "Registry"
        
        Args:
            artifact_type: Detected artifact type
            
        Returns:
            Normalized artifact type
        """
        # Handle EVTX variations
        if artifact_type.startswith('EVTX'):
            return 'EVTX'
        
        # Handle Registry variations
        if artifact_type.startswith('Registry'):
            return 'Registry'
        
        # Handle other variations
        if artifact_type in ['LNK/Shortcut', 'Shortcut', 'LNK']:
            return 'LNK/Shortcut'
        
        # Return as-is if no normalization needed
        return artifact_type
    
    def copy_artifact_to_case(self, source_path: str, artifact_type: str) -> str:
        """
        Copy artifact to appropriate location in case directory.
        
        Organizes artifacts by type into subdirectories:
        - Registry -> Registry_Hives/
        - Prefetch -> Prefetch/
        - JumpLists -> C_AJL_Lnk/
        - MFT/USN -> MFT_USN/
        - AmCache -> AmCache/
        - RecycleBin -> RecycleBin/
        - EVTX -> EVTX_Logs/
        - SRUM -> SRUM_Data/
        - LNK/Shortcut -> Shortcuts/
        - ShimCache -> ShimCache/
        - Unknown -> Unknown/
        
        Args:
            source_path: Source file path
            artifact_type: Type of artifact
            
        Returns:
            Destination path within case directory
            
        Raises:
            ValueError: If artifact type is not recognized
        """
        # Normalize artifact type
        normalized_type = self._normalize_artifact_type(artifact_type)
        
        # Get the subdirectory for this artifact type
        if normalized_type not in self.artifact_directories:
            raise ValueError(f"Unknown artifact type: {artifact_type} (normalized: {normalized_type})")
        
        subdir = self.artifact_directories[normalized_type]
        
        # Build destination path
        filename = os.path.basename(source_path)
        destination_path = os.path.join(self.target_artifacts_dir, subdir, filename)
        
        # Handle filename conflicts by appending a number
        if os.path.exists(destination_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(destination_path):
                new_filename = f"{base}_{counter}{ext}"
                destination_path = os.path.join(self.target_artifacts_dir, subdir, new_filename)
                counter += 1
        
        return destination_path

    
    def _calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA256 hash of a file.
        
        Uses buffered reading to handle large files efficiently.
        
        Args:
            file_path: Path to the file
            
        Returns:
            SHA256 hash as hexadecimal string, or empty string on error
        """
        if not self.calculate_hashes:
            return ""
        
        try:
            sha256_hash = hashlib.sha256()
            
            # Read file in chunks to handle large files
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            
            return sha256_hash.hexdigest()
            
        except Exception as e:
            print(f"Error calculating hash for {file_path}: {e}")
            return ""

    
    def _report_progress(self, current_file: str, processed_count: int, total_count: int):
        """
        Report progress to the callback if one is set.
        
        Args:
            current_file: Path of the file currently being processed
            processed_count: Number of files processed so far
            total_count: Total number of files to process
        """
        if self.progress_callback:
            try:
                self.progress_callback(current_file, processed_count, total_count)
            except Exception as e:
                # Don't let callback errors stop collection
                print(f"Error in progress callback: {e}")

    
    def _process_single_artifact(self, file_path: str, artifact_type_filter: Optional[str]) -> Optional[CollectedArtifactInfo]:
        """
        Process a single artifact file with error isolation.
        
        This method handles all errors for a single file and returns None on failure,
        allowing the collection process to continue with other files.
        
        Args:
            file_path: Path to the artifact file
            artifact_type_filter: Optional filter for artifact type
            
        Returns:
            CollectedArtifactInfo if successful, None if failed or filtered out
        """
        try:
            # Detect artifact type
            detection_result = self.detect_artifact_type(file_path)
            self._current_name = os.path.basename(file_path)
            
            # Apply filter
            if not self._should_collect_artifact(detection_result.artifact_type, artifact_type_filter):
                return None

            # Browser files keep their folder tree (see _process_browser_file).
            if detection_result.artifact_type == 'Browser':
                return self._process_browser_file(file_path, detection_result)

            # If artifact is Unknown and we are NOT filtering, we should still collect it
            # if the user wants "All Types".
            if detection_result.artifact_type == 'Unknown' and artifact_type_filter is not None and artifact_type_filter != "All Types":
                return None
            
# NO VALIDATION - Just collect based on filename/extension detection
            # All detected Windows artifacts are collected without validation
            
            # In scan-only mode, don't copy files - just detect and record
            if self.scan_only:
                # Calculate hash if enabled (for scan-only mode)
                file_hash = ""
                if self.calculate_hashes:
                    file_hash = self._calculate_file_hash(file_path)
                
                # Return artifact info without copying
                return CollectedArtifactInfo(
                    source_path=file_path,
                    destination_path=None,  # Not copied in scan-only mode
                    artifact_type=detection_result.artifact_type,
                    file_size=detection_result.file_size,
                    file_hash=file_hash,
                    collection_status="success",
                    error_message=None,
                    timestamp=datetime.now()
                )
            
            # Per-user files keep their owner's folder and are never
            # deduplicated: two users' identical Jump Lists are two pieces of
            # evidence, and a hive must stay beside its own logs.
            user_dest = self._user_destination(file_path, detection_result.artifact_type)
            if user_dest:
                return self._collect_user_file(file_path, user_dest, detection_result)

            # Collection mode - proceed with copying files
            # Calculate hash for deduplication check (if enabled)
            file_hash = ""
            if self.calculate_hashes:
                file_hash = self._calculate_file_hash(file_path)
                
                # Check for duplicates
                if file_hash:
                    existing_path = self._is_duplicate(file_hash)
                    if existing_path:
                        # Duplicate found - skip collection
                        return CollectedArtifactInfo(
                            source_path=file_path,
                            destination_path=existing_path,
                            artifact_type=detection_result.artifact_type,
                            file_size=detection_result.file_size,
                            file_hash=file_hash,
                            collection_status="skipped_duplicate",
                            error_message=f"Duplicate of {existing_path}",
                            timestamp=datetime.now()
                        )
            
            # Determine destination path
            destination_path = self.copy_artifact_to_case(file_path, detection_result.artifact_type)
            
            # Copy the file
            copy_success = self._copy_artifact(file_path, destination_path)
            
            if not copy_success:
                # Copy failed
                return CollectedArtifactInfo(
                    source_path=file_path,
                    destination_path="",
                    artifact_type=detection_result.artifact_type,
                    file_size=detection_result.file_size,
                    file_hash="",
                    collection_status="failed",
                    error_message="Failed to copy file",
                    timestamp=datetime.now()
                )
            
            # Recalculate hash of the copied file if not already done
            if not file_hash:
                file_hash = self._calculate_file_hash(destination_path)
            
            # Register hash for deduplication
            if file_hash:
                self.collected_hashes[file_hash] = destination_path
            
            # Success
            return CollectedArtifactInfo(
                source_path=file_path,
                destination_path=destination_path,
                artifact_type=detection_result.artifact_type,
                file_size=detection_result.file_size,
                file_hash=file_hash,
                collection_status="success",
                error_message=None,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            # Catch all errors and return failure info
            return CollectedArtifactInfo(
                source_path=file_path,
                destination_path="",
                artifact_type="Unknown",
                file_size=0,
                file_hash="",
                collection_status="failed",
                error_message=str(e),
                timestamp=datetime.now()
            )

    
    def _user_destination(self, source_path: str, artifact_type: str,
                          source_key_prefix: Optional[str] = None,
                          base: Optional[str] = None) -> Optional[str]:
        """Case path for a per-user file, or None for every other file."""
        normalized = self._normalize_artifact_type(artifact_type)
        if normalized not in PER_USER_TYPES:
            return None
        subdir = self.artifact_directories.get(normalized)
        if not subdir:
            return None
        if source_key_prefix is None:
            source_key_prefix = "dir:%s" % os.path.abspath(self._browser_base or "")
        if base is None:
            base = self._browser_base
        return self._user_placer.destination(subdir, source_path, source_key_prefix, base)

    def _collect_user_file(self, file_path: str, destination_path: str, detection_result) -> CollectedArtifactInfo:
        """Copy one per-user file to its owner's folder in the case."""
        info = dict(source_path=file_path, artifact_type=detection_result.artifact_type,
                    file_size=detection_result.file_size, timestamp=datetime.now())
        same = (os.path.normcase(os.path.abspath(file_path))
                == os.path.normcase(os.path.abspath(destination_path)))
        if not same and not self._copy_artifact(file_path, destination_path):
            return CollectedArtifactInfo(destination_path="", file_hash="", collection_status="failed",
                                         error_message="Failed to copy file", **info)
        file_hash = self._calculate_file_hash(destination_path) if self.calculate_hashes else ""
        return CollectedArtifactInfo(destination_path=destination_path, file_hash=file_hash,
                                     collection_status="success", error_message=None, **info)

    def _browser_tree_destination(self, tag: str, rel_path: str) -> Optional[str]:
        """``live_acquisition/Browser/<tag>/Users/<rel_path>``, or None when the
        result would not stay inside it (a drive or ``..`` component in an
        evidence path must never redirect a copy)."""
        parts = [p for p in rel_path.replace("/", "\\").split("\\")
                 if p and p not in (".", "..") and ":" not in p]
        root = os.path.abspath(os.path.join(self.target_artifacts_dir, BROWSER_CASE_DIR))
        dest = os.path.abspath(os.path.join(root, tag, "Users", *parts))
        if not os.path.normcase(dest).startswith(os.path.normcase(root) + os.sep):
            return None
        return dest

    def _process_browser_file(self, file_path: str, detection_result) -> Optional[CollectedArtifactInfo]:
        """Copy one browser file to its place in the preserved tree.

        Not hash-deduplicated: the same bytes in two profiles are two pieces of
        evidence, and dropping one would leave a profile incomplete. Folders the
        parser never reads (and the cache, when the toggle is off) are skipped.
        Each source keeps its own folder (``browser_source_tag``), so an
        existing destination file can only be this same source collected
        before - never another machine's file with the same name.
        """
        where = browser_path_info(file_path, self._browser_base)
        if not where:
            return None
        rel, src_root, volume_root = where
        if browser_path_skipped(rel, self.include_browser_cache):
            return None
        info = dict(source_path=file_path, artifact_type='Browser',
                    file_size=detection_result.file_size, file_hash="",
                    error_message=None, timestamp=datetime.now())
        if self.scan_only:
            self._browser_roots[file_path] = (src_root, None)
            return CollectedArtifactInfo(destination_path=None, collection_status="success", **info)
        # A file already inside this case's Browser tree stays where it is.
        browser_root = os.path.normcase(os.path.abspath(
            os.path.join(self.target_artifacts_dir, BROWSER_CASE_DIR))) + os.sep
        if os.path.normcase(os.path.abspath(file_path)).startswith(browser_root):
            self._browser_roots[file_path] = (src_root, src_root)
            return CollectedArtifactInfo(destination_path=file_path, collection_status="success", **info)
        tag = browser_source_tag(volume_root)
        destination_path = self._browser_tree_destination(tag, rel)
        if not destination_path:
            info["error_message"] = "Browser path would leave the case folder"
            return CollectedArtifactInfo(destination_path="", collection_status="failed", **info)
        user = rel.replace("/", "\\").split("\\")[0]
        self._browser_roots[file_path] = (
            src_root, os.path.join(self.target_artifacts_dir, BROWSER_CASE_DIR, tag, "Users", user))
        if os.path.exists(destination_path):
            return CollectedArtifactInfo(destination_path=destination_path,
                                         collection_status="success", **info)
        if not self._copy_artifact(file_path, destination_path):
            info["error_message"] = "Failed to copy file"
            return CollectedArtifactInfo(destination_path="", collection_status="failed", **info)
        return CollectedArtifactInfo(destination_path=destination_path, collection_status="success", **info)

    def _collapse_browser_artifacts(self, artifacts):
        """One result per browser USER folder instead of one per file.

        A profile is thousands of files (LevelDB, IndexedDB, cache). Listing each
        in the scan index made the Parse dialog unreadable; the browser parser
        walks the whole tree anyway, so one entry per user is what it needs.
        """
        out, groups = [], {}
        for a in artifacts:
            if a.artifact_type != 'Browser':
                out.append(a)
                continue
            src_root, dst_root = self._browser_roots.get(a.source_path, (None, None))
            key = dst_root or src_root or a.source_path
            g = groups.setdefault(key, {"src": src_root or a.source_path, "dst": dst_root,
                                        "size": 0, "failed": 0, "count": 0, "ts": a.timestamp})
            g["size"] += a.file_size or 0
            g["failed"] += 1 if a.collection_status == "failed" else 0
            g["count"] += 1
        for g in groups.values():
            out.append(CollectedArtifactInfo(
                source_path=g["src"],
                destination_path=None if self.scan_only else g["dst"],
                artifact_type='Browser', file_size=g["size"], file_hash="",
                collection_status="success" if g["failed"] < g["count"] else "failed",
                error_message=(f"{g['failed']} of {g['count']} browser file(s) could not be copied"
                               if g["failed"] else None),
                timestamp=g["ts"]))
        return out

    # -- chain of custody --------------------------------------------------
    def _custody_begin(self, source_dir, artifact_type_filter, include_subdirs, specific_files):
        """Open the run's custody record: a collection (or a scan) of evidence
        files into this case. Never raises; None when it cannot be opened."""
        try:
            from utils import custody
            return custody.begin(
                self.case_root, "offline scan" if self.scan_only else "offline collection",
                options={"source": source_dir, "artifact_type": artifact_type_filter or "All Types",
                         "include_subdirectories": include_subdirs,
                         "specific_files": len(specific_files) if specific_files else None,
                         "hashes": self.calculate_hashes},
                output_dir=None if self.scan_only else self.target_artifacts_dir)
        except Exception as e:
            print(f"[Custody] Record not started: {e}")
            return None

    @staticmethod
    def _custody_times(rec, path):
        if rec is None:
            return None
        try:
            from utils import custody
            return custody.file_times(path)
        except Exception:
            return None

    def _custody_note(self, rec, info, times):
        """One file's outcome into the record. A copied file is verified: the
        SHA-256 of the copy against the source's (which the duplicate check
        already took - the source is not read a second time)."""
        if rec is None or info is None:
            return
        try:
            status = info.collection_status
            src_hash = info.file_hash or None
            if status == "failed":
                rec.add_failure(info.source_path, info.error_message or "not collected",
                                method="copy", artifact_type=info.artifact_type)
            elif status == "skipped_duplicate":
                rec.add_source(info.source_path, method="not copied (duplicate)", times=times,
                               source_sha256=src_hash, hash_source=src_hash is None,
                               note=info.error_message)
            elif self.scan_only or not info.destination_path:
                rec.add_source(info.source_path, method="scan (read, not copied)", times=times,
                               source_sha256=src_hash, hash_source=src_hash is None,
                               note=info.artifact_type)
            else:
                rec.add_source(info.source_path, copy=info.destination_path, method="copy",
                               times=times, source_sha256=src_hash, note=info.artifact_type)
        except Exception as e:
            print(f"[Custody] Entry for {getattr(info, 'source_path', '?')} not recorded: {e}")

    def collect_from_directory(self, source_dir: str, artifact_type_filter: Optional[str] = None,
                               include_subdirs: bool = True, specific_files: Optional[List[str]] = None) -> CollectionResult:
        """Collect (or scan), inside a chain-of-custody record of its own."""
        rec = self._custody_begin(source_dir, artifact_type_filter, include_subdirs, specific_files)
        self._custody_rec = rec
        status = "failed"
        try:
            result = self._collect_from_directory(source_dir, artifact_type_filter,
                                                  include_subdirs, specific_files)
            status = "completed" if not result.failed else "completed with failures"
            return result
        except InterruptedError:
            status = "cancelled"
            raise
        finally:
            self._custody_rec = None
            if rec is not None:
                try:
                    from utils import custody
                    path = custody.end(status, rec=rec)
                    if path:
                        print(f"[Custody] Record written: {path}")
                except Exception as e:
                    print(f"[Custody] Record not written: {e}")

    def _collect_from_directory(self, source_dir: str, artifact_type_filter: Optional[str] = None,
                                include_subdirs: bool = True, specific_files: Optional[List[str]] = None) -> CollectionResult:
        """
        Collect artifacts from a directory or specific files.
        
        Args:
            source_dir: Source directory to scan
            artifact_type_filter: Optional filter
            include_subdirs: Whether to scan subdirectories
            specific_files: Optional list of specific file paths to process
            
        Returns:
            CollectionResult
        """
        # Reset cancellation flag
        self._cancelled = False
        self.live_counts = {"found": 0, "collected": 0, "failed": 0}
        self.partial_result = None

        # Browser attribution is clamped to the folder being imported.
        self._browser_base = os.path.abspath(source_dir) if source_dir else None
        self._browser_roots = {}

        if specific_files:
            file_paths = specific_files
            print(f"[COLLECTION] Processing {len(file_paths)} specific files")
        else:
            # Validate source directory
            if not os.path.exists(source_dir):
                raise ValueError(f"Source directory does not exist: {source_dir}")
            
            if not os.path.isdir(source_dir):
                raise ValueError(f"Source path is not a directory: {source_dir}")
            
            # Log scanning mode
            if include_subdirs:
                print(f"[COLLECTION] Scanning directory recursively (including all subdirectories): {source_dir}")
            else:
                print(f"[COLLECTION] Scanning directory (top-level only, no subdirectories): {source_dir}")
            
            # Scan directory for files
            file_paths = self._scan_directory(source_dir, include_subdirs)
            
            # Log scan results
            print(f"[COLLECTION] Found {len(file_paths)} total files to process")
        
        total_files = len(file_paths)
        
        # Process each file
        collected_artifacts = []
        processed_count = 0
        
        for file_path in file_paths:
            # Check for cancellation
            if self._cancelled:
                # What was copied stays copied: keep its registry entries and
                # hand the caller a result for it ("partial results preserved"
                # used to be said while all of it was dropped).
                self.partial_result = self._finish(collected_artifacts)
                raise InterruptedError("Collection cancelled by user")

            # Report progress
            self._report_progress(file_path, processed_count, total_files)

            # Process the artifact (with error isolation). Its times are read
            # BEFORE the copy, for the custody record.
            rec = getattr(self, "_custody_rec", None)
            times = self._custody_times(rec, file_path)
            artifact_info = self._process_single_artifact(file_path, artifact_type_filter)
            self._custody_note(rec, artifact_info, times)

            # Add to results if it was processed (not filtered out)
            if artifact_info:
                collected_artifacts.append(artifact_info)
                self.live_counts["found"] += 1
                if artifact_info.collection_status == "success":
                    self.live_counts["collected"] += 1
                elif artifact_info.collection_status == "failed":
                    self.live_counts["failed"] += 1

            processed_count += 1

        # Final progress report
        self._report_progress("Complete", total_files, total_files)
        return self._finish(collected_artifacts)

    def _finish(self, collected_artifacts) -> CollectionResult:
        """Persist the registries and total up - for a whole run or a cancelled one."""
        # Save hash registry for deduplication persistence
        self._save_hash_registry()
        self._user_placer.save()

        collected_artifacts = self._collapse_browser_artifacts(collected_artifacts)

        # A skipped duplicate is neither collected nor failed.
        return CollectionResult(
            total_found=len(collected_artifacts),
            total_collected=sum(1 for a in collected_artifacts if a.collection_status == "success"),
            failed=sum(1 for a in collected_artifacts if a.collection_status == "failed"),
            artifacts=collected_artifacts
        )
    
    def cancel(self):
        """
        Request cancellation of the collection process.
        
        This method is thread-safe and can be called from any thread.
        The collection will stop at the next safe checkpoint (after processing
        the current file).
        """
        self._cancelled = True
