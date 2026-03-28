"""
Collection Coordinator Module

This module orchestrates the entire artifact collection workflow, coordinating
between the artifact collector, detector, and parser invoker. It provides
progress tracking, error aggregation, and collection summary generation.
"""

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Callable, Dict

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from .artifact_collector import ArtifactCollector, CollectedArtifactInfo, CollectionResult
from .report_generator import ReportGenerator


@dataclass
class CollectionSummary:
    """
    Summary of a complete collection session.
    
    This dataclass holds the summary information for an entire artifact
    collection session, including counts, timing, and the list of all
    collected artifacts.
    
    Attributes:
        total_found: Total number of artifacts found during scanning
        total_collected: Total number of artifacts successfully collected
        failed: Number of artifacts that failed to collect
        collection_time: Total time taken for collection in seconds
        artifacts: List of all collected artifact information
        start_time: When the collection session started
        end_time: When the collection session ended
    """
    total_found: int
    total_collected: int
    failed: int
    collection_time: float
    artifacts: List[CollectedArtifactInfo]
    start_time: datetime
    end_time: datetime


@dataclass
class ProgressUpdate:
    """
    Progress update information for GUI callbacks.
    
    Attributes:
        current_file: Path of the file currently being processed
        processed_count: Number of files processed so far
        total_count: Total number of files to process
        artifacts_found: Number of artifacts found so far
        artifacts_collected: Number of artifacts successfully collected
        artifacts_failed: Number of artifacts that failed
        elapsed_time: Time elapsed since collection started (seconds)
    """
    current_file: str
    processed_count: int
    total_count: int
    artifacts_found: int
    artifacts_collected: int
    artifacts_failed: int
    elapsed_time: float


class CollectionCoordinator:
    """
    Orchestrates the entire artifact collection workflow.
    
    This class coordinates between the artifact collector, detector, and parser
    invoker. It provides:
    - Workflow orchestration (collector → detector → invoker)
    - Progress aggregation from multiple sources
    - Error aggregation and reporting
    - Collection summary generation
    - GUI callback mechanism for updates
    """
    
    def __init__(self, case_root: str, calculate_hashes: bool = True, validate_artifacts: bool = False, scan_only: bool = False):
        """
        Initialize the collection coordinator.
        
        Args:
            case_root: Root directory of the case where artifacts will be stored
            calculate_hashes: Whether to calculate SHA256 hashes for collected artifacts
            validate_artifacts: Whether to perform strict validation on artifacts (default: False for better compatibility)
            scan_only: If True, only scan and detect artifacts without copying them
        """
        self.case_root = case_root
        self.calculate_hashes = calculate_hashes
        self.scan_only = scan_only
        
        # Initialize the artifact collector with validation and scan_only settings
        self.artifact_collector = ArtifactCollector(case_root, calculate_hashes, validate_artifacts, scan_only)
        
        # Initialize the report generator
        self.report_generator = ReportGenerator(case_root)
        
        # Progress tracking
        self.progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
        self.start_time: Optional[float] = None
        
        # Error aggregation
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
        # Statistics tracking
        self.artifacts_found = 0
        self.artifacts_collected = 0
        self.artifacts_failed = 0
    
    def set_progress_callback(self, callback: Callable[[ProgressUpdate], None]):
        """
        Set callback for progress updates.
        
        The callback will be called periodically during collection with
        ProgressUpdate information.
        
        Args:
            callback: Function that takes a ProgressUpdate parameter
        """
        self.progress_callback = callback
    
    def _validate_source_directory(self, source_dir: str) -> bool:
        """
        Validate that the source directory exists and is accessible.
        
        Args:
            source_dir: Path to the source directory
            
        Returns:
            True if valid, False otherwise
        """
        if not source_dir:
            self.errors.append("Source directory path is empty")
            return False
        
        if not os.path.exists(source_dir):
            self.errors.append(f"Source directory does not exist: {source_dir}")
            return False
        
        if not os.path.isdir(source_dir):
            self.errors.append(f"Source path is not a directory: {source_dir}")
            return False
        
        if not os.access(source_dir, os.R_OK):
            self.errors.append(f"Source directory is not readable: {source_dir}")
            return False
        
        return True
    
    def _validate_case_directory(self) -> bool:
        """
        Validate that the case directory exists and is accessible.
        
        Returns:
            True if valid, False otherwise
        """
        if not self.case_root:
            self.errors.append("Case root directory path is empty")
            return False
        
        if not os.path.exists(self.case_root):
            try:
                # Try to create the case directory
                os.makedirs(self.case_root, exist_ok=True)
            except Exception as e:
                self.errors.append(f"Cannot create case directory: {e}")
                return False
        
        if not os.path.isdir(self.case_root):
            self.errors.append(f"Case root path is not a directory: {self.case_root}")
            return False
        
        if not os.access(self.case_root, os.W_OK):
            self.errors.append(f"Case directory is not writable: {self.case_root}")
            return False
        
        return True
    
    def _collector_progress_callback(self, current_file: str, processed_count: int, total_count: int):
        """
        Internal callback for artifact collector progress updates.
        
        This method receives progress from the artifact collector and
        aggregates it with other statistics before forwarding to the GUI.
        
        Args:
            current_file: Path of the file currently being processed
            processed_count: Number of files processed so far
            total_count: Total number of files to process
        """
        if self.progress_callback and self.start_time:
            elapsed_time = time.time() - self.start_time
            
            # Create progress update
            progress = ProgressUpdate(
                current_file=current_file,
                processed_count=processed_count,
                total_count=total_count,
                artifacts_found=self.artifacts_found,
                artifacts_collected=self.artifacts_collected,
                artifacts_failed=self.artifacts_failed,
                elapsed_time=elapsed_time
            )
            
            # Forward to GUI callback
            try:
                self.progress_callback(progress)
            except Exception as e:
                # Don't let callback errors stop collection
                self.warnings.append(f"Progress callback error: {e}")
    
    def _aggregate_errors(self, collection_result: CollectionResult):
        """
        Aggregate errors from collection result.
        
        Groups similar errors together and adds them to the error list.
        
        Args:
            collection_result: Result from artifact collection
        """
        # Group errors by message
        error_groups: Dict[str, List[str]] = {}
        
        for artifact in collection_result.artifacts:
            if artifact.collection_status == "failed" and artifact.error_message:
                error_msg = artifact.error_message
                if error_msg not in error_groups:
                    error_groups[error_msg] = []
                error_groups[error_msg].append(artifact.source_path)
        
        # Add grouped errors to error list
        for error_msg, file_paths in error_groups.items():
            if len(file_paths) == 1:
                self.errors.append(f"{error_msg}: {file_paths[0]}")
            else:
                self.errors.append(f"{error_msg} ({len(file_paths)} files)")
                # Add first few file paths as examples
                for path in file_paths[:3]:
                    self.errors.append(f"  - {path}")
                if len(file_paths) > 3:
                    self.errors.append(f"  ... and {len(file_paths) - 3} more")
    
    def _generate_collection_summary(self, collection_result: CollectionResult, 
                                    start_time: datetime, end_time: datetime) -> CollectionSummary:
        """
        Generate collection summary from collection result.
        
        Args:
            collection_result: Result from artifact collection
            start_time: When collection started
            end_time: When collection ended
            
        Returns:
            CollectionSummary with complete session information
        """
        collection_time = (end_time - start_time).total_seconds()
        
        return CollectionSummary(
            total_found=collection_result.total_found,
            total_collected=collection_result.total_collected,
            failed=collection_result.failed,
            collection_time=collection_time,
            artifacts=collection_result.artifacts,
            start_time=start_time,
            end_time=end_time
        )
    
    def collect_artifacts(self, source_dir: str, artifact_type_filter: Optional[str] = None,
                         include_subdirs: bool = True) -> CollectionSummary:
        """
        Collect artifacts from a directory.
        
        This is the main entry point for the collection workflow. It:
        1. Validates source and case directories
        2. Starts the artifact collector with filters
        3. Tracks progress and aggregates statistics
        4. Collects errors and warnings
        5. Generates collection summary
        
        Args:
            source_dir: Source directory to scan
            artifact_type_filter: Optional filter (e.g., "Registry", "Prefetch", or None for all)
            include_subdirs: Whether to scan subdirectories recursively
            
        Returns:
            CollectionSummary containing complete session information
            
        Raises:
            ValueError: If validation fails
            InterruptedError: If collection is cancelled
        """
        # Reset state
        self.errors = []
        self.warnings = []
        self.artifacts_found = 0
        self.artifacts_collected = 0
        self.artifacts_failed = 0
        
        # Validate directories
        if not self._validate_source_directory(source_dir):
            raise ValueError(f"Source directory validation failed: {'; '.join(self.errors)}")
        
        if not self._validate_case_directory():
            raise ValueError(f"Case directory validation failed: {'; '.join(self.errors)}")
        
        # Record start time
        start_time = datetime.now()
        self.start_time = time.time()
        
        # Set up progress callback for collector
        self.artifact_collector.set_progress_callback(self._collector_progress_callback)
        
        try:
            # Execute collection workflow
            collection_result = self.artifact_collector.collect_from_directory(
                source_dir=source_dir,
                artifact_type_filter=artifact_type_filter,
                include_subdirs=include_subdirs
            )
            
            # Update statistics
            self.artifacts_found = collection_result.total_found
            self.artifacts_collected = collection_result.total_collected
            self.artifacts_failed = collection_result.failed
            
            # Aggregate errors
            self._aggregate_errors(collection_result)
            
            # Record end time
            end_time = datetime.now()
            
            # Generate summary
            summary = self._generate_collection_summary(collection_result, start_time, end_time)
            
            # Final progress update
            if self.progress_callback:
                final_progress = ProgressUpdate(
                    current_file="Complete",
                    processed_count=summary.total_found,
                    total_count=summary.total_found,
                    artifacts_found=summary.total_found,
                    artifacts_collected=summary.total_collected,
                    artifacts_failed=summary.failed,
                    elapsed_time=summary.collection_time
                )
                try:
                    self.progress_callback(final_progress)
                except Exception as e:
                    self.warnings.append(f"Final progress callback error: {e}")
            
            return summary
        
        except InterruptedError:
            # Collection was cancelled - re-raise to propagate to caller
            raise
            
        except Exception as e:
            # Handle unexpected errors
            self.errors.append(f"Collection failed: {str(e)}")
            end_time = datetime.now()
            
            # Return partial results
            return CollectionSummary(
                total_found=self.artifacts_found,
                total_collected=self.artifacts_collected,
                failed=self.artifacts_failed,
                collection_time=(end_time - start_time).total_seconds(),
                artifacts=[],
                start_time=start_time,
                end_time=end_time
            )
    
    def cancel(self):
        """
        Request cancellation of the collection process.
        
        This method is thread-safe and can be called from any thread.
        The cancellation request is passed to the artifact collector.
        """
        self.artifact_collector.cancel()
    
    def get_errors(self) -> List[str]:
        """
        Get list of errors encountered during collection.
        
        Returns:
            List of error messages
        """
        return self.errors.copy()
    
    def get_warnings(self) -> List[str]:
        """
        Get list of warnings encountered during collection.
        
        Returns:
            List of warning messages
        """
        return self.warnings.copy()
    
    def generate_report(self, summary: CollectionSummary, format: str = "html") -> Optional[str]:
        """
        Generate a collection report in the specified format.
        
        Args:
            summary: Collection summary to generate report from
            format: Report format - "html" or "pdf"
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        if format.lower() == "html":
            return self.report_generator.generate_html_report(
                summary, 
                errors=self.errors, 
                warnings=self.warnings
            )
        elif format.lower() == "pdf":
            return self.report_generator.generate_pdf_report(
                summary,
                errors=self.errors,
                warnings=self.warnings
            )
        else:
            raise ValueError(f"Unsupported report format: {format}. Use 'html' or 'pdf'.")

    def collect_artifacts_incremental(self, source_dir: str, artifact_type_filter: Optional[str] = None,
                                      include_subdirs: bool = True) -> CollectionSummary:
        """
        Collect artifacts incrementally, adding to an existing case.
        
        This method is identical to collect_artifacts() but explicitly documents
        that it supports incremental collection. The deduplication mechanism
        automatically prevents re-collecting artifacts that already exist in the case.
        
        When this method is called:
        1. Existing artifacts in the case are loaded and their hashes calculated
        2. New artifacts are scanned from the source directory
        3. Duplicates are detected by hash comparison
        4. Only new (non-duplicate) artifacts are copied to the case
        
        Args:
            source_dir: Source directory to scan
            artifact_type_filter: Optional filter (e.g., "Registry", "Prefetch", or None for all)
            include_subdirs: Whether to scan subdirectories recursively
            
        Returns:
            CollectionSummary containing complete session information, including
            count of skipped duplicates
            
        Raises:
            ValueError: If validation fails
            InterruptedError: If collection is cancelled
        """
        # The standard collect_artifacts method already supports incremental collection
        # through the deduplication mechanism
        return self.collect_artifacts(source_dir, artifact_type_filter, include_subdirs)

    def collect_artifacts_batch(self, source_dirs: List[str], artifact_type_filter: Optional[str] = None,
                                include_subdirs: bool = True) -> CollectionSummary:
        """
        Collect artifacts from multiple source directories in batch.

        This method processes multiple source directories sequentially, aggregating
        results into a single collection summary. Progress updates are sent for each
        directory and each artifact within those directories.

        Args:
            source_dirs: List of source directory paths to scan
            artifact_type_filter: Optional filter for artifact type (e.g., "Registry", "Prefetch")
            include_subdirs: Whether to scan subdirectories recursively

        Returns:
            CollectionSummary containing aggregated results from all directories

        Raises:
            ValueError: If source_dirs is empty or contains invalid paths
        """
        if not source_dirs:
            raise ValueError("source_dirs cannot be empty")

        # Validate all source directories first
        invalid_dirs = []
        for source_dir in source_dirs:
            if not self._validate_source_directory(source_dir):
                invalid_dirs.append(source_dir)

        if invalid_dirs:
            raise ValueError(f"Invalid source directories: {', '.join(invalid_dirs)}")

        # Validate case directory
        if not self._validate_case_directory():
            raise ValueError(f"Case directory validation failed: {self.case_root}")

        # Initialize aggregated results
        all_artifacts = []
        total_found = 0
        total_collected = 0
        total_failed = 0
        start_time = datetime.now()
        self.start_time = time.time()
        
        # Reset state
        self.errors = []
        self.warnings = []
        self.artifacts_found = 0
        self.artifacts_collected = 0
        self.artifacts_failed = 0

        # Process each source directory
        for idx, source_dir in enumerate(source_dirs):
            try:
                # Update progress for current directory
                if self.progress_callback:
                    elapsed_time = time.time() - self.start_time if self.start_time else 0
                    self.progress_callback(ProgressUpdate(
                        current_file=f"Processing directory {idx + 1}/{len(source_dirs)}: {source_dir}",
                        processed_count=idx,
                        total_count=len(source_dirs),
                        artifacts_found=total_found,
                        artifacts_collected=total_collected,
                        artifacts_failed=total_failed,
                        elapsed_time=elapsed_time
                    ))

                # Collect from this directory
                result = self.artifact_collector.collect_from_directory(
                    source_dir=source_dir,
                    artifact_type_filter=artifact_type_filter,
                    include_subdirs=include_subdirs
                )

                # Aggregate results
                all_artifacts.extend(result.artifacts)
                total_found += result.total_found
                total_collected += result.total_collected
                total_failed += result.failed

                # Aggregate errors
                self._aggregate_errors(result)

            except Exception as e:
                error_msg = f"Error processing directory {source_dir}: {str(e)}"
                self.errors.append(error_msg)
                self.warnings.append(f"Skipping directory {source_dir} due to error")
                continue

        end_time = datetime.now()
        collection_time = (end_time - start_time).total_seconds()

        # Create aggregated summary
        summary = CollectionSummary(
            total_found=total_found,
            total_collected=total_collected,
            failed=total_failed,
            collection_time=collection_time,
            artifacts=all_artifacts,
            start_time=start_time,
            end_time=end_time
        )

        # Final progress update
        if self.progress_callback:
            elapsed_time = time.time() - self.start_time if self.start_time else collection_time
            self.progress_callback(ProgressUpdate(
                current_file="Batch collection complete",
                processed_count=len(source_dirs),
                total_count=len(source_dirs),
                artifacts_found=total_found,
                artifacts_collected=total_collected,
                artifacts_failed=total_failed,
                elapsed_time=elapsed_time
            ))

        return summary

    def collect_artifacts_incremental(self, source_dir: str, artifact_type_filter: Optional[str] = None,
                                      include_subdirs: bool = True) -> CollectionSummary:
        """
        Collect artifacts incrementally, adding to an existing case.

        This method is identical to collect_artifacts() but explicitly documents
        that it supports incremental collection. The deduplication mechanism
        automatically prevents re-collecting artifacts that already exist in the case.

        When this method is called:
        1. Existing artifacts in the case are loaded and their hashes calculated
        2. New artifacts are scanned from the source directory
        3. Duplicates are detected by hash comparison
        4. Only new (non-duplicate) artifacts are copied to the case

        Args:
            source_dir: Source directory to scan
            artifact_type_filter: Optional filter (e.g., "Registry", "Prefetch", or None for all)
            include_subdirs: Whether to scan subdirectories recursively

        Returns:
            CollectionSummary containing complete session information, including
            count of skipped duplicates

        Raises:
            ValueError: If validation fails
            InterruptedError: If collection is cancelled
        """
        # The standard collect_artifacts method already supports incremental collection
        # through the deduplication mechanism
        return self.collect_artifacts(source_dir, artifact_type_filter, include_subdirs)


