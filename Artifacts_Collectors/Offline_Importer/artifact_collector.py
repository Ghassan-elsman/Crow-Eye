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
        
        # Mapping of artifact types to their subdirectories in live_acquisition (input files)
        # Output databases go to Target_Artifacts
        self.artifact_directories = {
            'Registry': 'Registry_Hives',
            'Prefetch': 'Prefetch',
            'JumpLists': 'C_AJL_Lnk',
            'MFT': 'MFT_USN',
            'USN': 'MFT_USN',
            'AmCache': 'AmCache',
            'RecycleBin': 'RecycleBin',
            'EVTX': 'EVTX_Logs',
            'SRUM': 'SRUM_Data',
            'LNK/Shortcut': 'Shortcuts',
            'ShimCache': 'ShimCache',
            'Unknown': 'Unknown'
        }
        
        # Hash tracking for deduplication
        self.collected_hashes: Dict[str, str] = {}  # hash -> file_path mapping
        self._load_existing_hashes()
        
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
                artifact_dir = os.path.join(self.target_artifacts_dir, subdir)
                if not os.path.exists(artifact_dir):
                    continue

                # Scan all files in this artifact directory
                for root, _, files in os.walk(artifact_dir):
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
        return self.collected_hashes.get(file_hash)

    def _save_hash_registry(self):
        """
        Save the hash registry to a JSON file in the case directory.

        This allows persistence of deduplication information across sessions.
        """
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
            "Jump Lists": "JumpLists",
            "MFT Files": "MFT",
            "USN Journal": "USN",
            "Recycle Bin": "RecycleBin",
            "AmCache": "AmCache",
            "ShimCache": "Registry" # ShimCache comes from SYSTEM hive
        }
        
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
            
            # Copy file with metadata preservation
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
            
            # Apply filter
            if not self._should_collect_artifact(detection_result.artifact_type, artifact_type_filter):
                return None
            
            # If artifact is Unknown and we are NOT filtering, we should still collect it
            # if the user wants "All Types".
            if detection_result.artifact_type == 'Unknown' and artifact_type_filter is not None and artifact_type_filter != "All Types":
                return None
            
            # Special case for ShimCache - it is technically part of Registry collection (SYSTEM hive)
            # but we want to show it as a separate parsable type.
            if artifact_type_filter == "ShimCache" and detection_result.artifact_type != "Registry":
                 # If user specifically wants ShimCache, we look for SYSTEM hive which is typed as Registry
                 pass 
            elif artifact_type_filter == "ShimCache" and "SYSTEM" not in file_path.upper():
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

    
    def collect_from_directory(self, source_dir: str, artifact_type_filter: Optional[str] = None, 
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
                raise InterruptedError("Collection cancelled by user")
            
            # Report progress
            self._report_progress(file_path, processed_count, total_files)
            
            # Process the artifact (with error isolation)
            artifact_info = self._process_single_artifact(file_path, artifact_type_filter)
            
            # Add to results if it was processed (not filtered out)
            if artifact_info:
                collected_artifacts.append(artifact_info)
            
            processed_count += 1
        
        # Final progress report
        self._report_progress("Complete", total_files, total_files)
        
        # Save hash registry for deduplication persistence
        self._save_hash_registry()
        
        # Calculate summary statistics
        total_found = len(collected_artifacts)
        total_collected = sum(1 for a in collected_artifacts if a.collection_status == "success")
        failed = sum(1 for a in collected_artifacts if a.collection_status == "failed")
        skipped_duplicates = sum(1 for a in collected_artifacts if a.collection_status == "skipped_duplicate")
        
        return CollectionResult(
            total_found=total_found,
            total_collected=total_collected,
            failed=failed,
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
