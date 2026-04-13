"""
Forensic Image Collection Wrapper

This module provides wrapper classes that extend the Offline Importer's 
collection engine to natively support forensic image files via dissect.
This avoids modifying the core Offline Importer files.
"""

import os
import sys
from datetime import datetime
from typing import List, Optional, Union

# Add parent and Offline_Importer directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Now we can import these
from Offline_Importer.artifact_collector import ArtifactCollector, CollectedArtifactInfo, CollectionResult
from Offline_Importer.collection_coordinator import CollectionCoordinator, CollectionSummary, ProgressUpdate

# Import local components
try:
    if __package__ or "." in __name__:
        from .image_parser import ImageParser
        from .file_system_accessor import FileSystemAccessor
    else:
        from image_parser import ImageParser
        from file_system_accessor import FileSystemAccessor
except (ImportError, ValueError):
    from image_parser import ImageParser
    from file_system_accessor import FileSystemAccessor

class ImageArtifactCollector(ArtifactCollector):
    """
    Extends ArtifactCollector to natively scan forensic images.
    """
    
    def collect_from_image(self, image_path: Union[str, List[str]], selected_partitions: List[int], artifact_type_filter: Optional[str] = None) -> CollectionResult:
        """Collect-specific artifacts from a forensic image file (Crow-Claw style)."""
        self._cancelled = False
        primary_path = image_path[0] if isinstance(image_path, list) else image_path
        print(f"[IMAGE-COLLECTION] Starting targeted extraction from: {primary_path}")
        
        # Import artifact definitions safely
        try:
            from Artifacts_Collectors.crow_claw.core.artifacts import get_all_artifacts
        except ImportError:
            # Fallback for dynamic loads
            parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
            from crow_claw.core.artifacts import get_all_artifacts
        
        parser = ImageParser()
        strategy = parser.get_strategy(file_source=image_path)
        if not strategy:
            raise ValueError(f"Unsupported forensic image format: {primary_path}")
        
        if hasattr(strategy, '_open_image'):
            if not strategy._open_image(image_path):
                raise ValueError(f"Failed to open image: {primary_path}")
        
        img_info = None
        if hasattr(strategy, 'get_img_info'):
            img_info = strategy.get_img_info()
            
        if not img_info:
            raise ValueError(f"Failed to obtain image info for: {image_path}")
            
        accessor = FileSystemAccessor(img_info)
        
        # Discover VSS snapshots for fallback
        vss_accessors = []
        try:
            # Check for VSS snapshots in the target
            from dissect.target import Target
            # We already have strategy.get_img_info() but Target might be needed for VSS plugin
            # In many dissect setups, Target.open(path) handles VSS discovery
            target = Target.open(primary_path)
            if hasattr(target, 'vss'):
                print(f"[IMAGE-COLLECTION] Found {len(target.vss)} VSS snapshots for fallback.")
                for snapshot in target.vss:
                    try:
                        # Create an accessor for each snapshot
                        snapshot_accessor = FileSystemAccessor(snapshot)
                        # We need to open the partition in the snapshot too
                        # Usually snapshots are of a specific volume, so offset 0
                        snapshot_accessor.open_partition(0)
                        vss_accessors.append(snapshot_accessor)
                    except:
                        pass
            self._vss_accessors = vss_accessors # Store for fallback method
        except Exception as e:
            print(f"[WARNING] VSS discovery failed: {e}")
            self._vss_accessors = []

        collected_artifacts = []
        
        # Phase 1: Partition Metadata Parity (Task 3)
        self._generate_partition_metadata(img_info, primary_path)
        
        # Get all artifact definitions
        all_artifact_defs = get_all_artifacts()
        
        try:
            # Map partition numbers to their offsets
            partitions_info = strategy.list_partitions() if hasattr(strategy, 'list_partitions') else []
            
            for partition_num in selected_partitions:
                if self._cancelled: break
                
                # Find offset for this partition number
                part_offset = next((p.start_offset for p in partitions_info if p.partition_number == partition_num), partition_num)
                
                print(f"[IMAGE-COLLECTION] Scanning partition {partition_num} at offset {part_offset}")
                if not accessor.open_partition(part_offset):
                    print(f"[WARNING] Could not mount partition {partition_num} at {part_offset}")
                    continue
                
                # For each artifact definition
                for art_def in all_artifact_defs:
                    if self._cancelled: break
                    
                    # Apply high-level artifact filter if provided
                    if artifact_type_filter and artifact_type_filter != "All Types":
                        if art_def.artifact_type.value != artifact_type_filter and art_def.name != artifact_type_filter:
                            continue
                    
                    # Get the paths for this artifact. 
                    artifact_type_name = art_def.artifact_type.value
                    
                    for win_path in art_def.get_all_paths():
                        if self._cancelled: break
                        
                        # Convert Windows path to dissect root-relative path
                        import re
                        # Strip \\.\C: or C: or {PARTITION}: or \\.\{PARTITION}
                        p = re.sub(r'^(\\\\\.\\)?([a-zA-Z]:|\{PARTITION\}):?', '', win_path)
                        p = p.replace('\\', '/')
                        # Ensure it's a single leading slash and no double slashes
                        while '//' in p:
                            p = p.replace('//', '/')
                        if not p.startswith('/'):
                            p = '/' + p
                        
                        # Use _expand_dissect_wildcards for all paths to handle streams and case-insensitivity
                        matching_paths = self._expand_dissect_wildcards(accessor, p)
                        
                        for match in matching_paths:
                            if self._cancelled: break
                            # We pass the artifact type name directly to ensure compatibility with Offline Importer
                            artifact_info = self._process_image_entry_by_path(accessor, match, artifact_type_name)
                            if artifact_info:
                                collected_artifacts.append(artifact_info)
                                self._report_progress(f"Found: {os.path.basename(match)}", len(collected_artifacts), 0)
        finally:
            # Always ensure resources are closed properly to avoid locked files
            accessor.close()
            for vss_accessor in getattr(self, '_vss_accessors', []):
                try:
                    vss_accessor.close()
                except:
                    pass
            if hasattr(strategy, '_close_image'):
                strategy._close_image()
        
        self._report_progress("Extraction Complete", len(collected_artifacts), len(collected_artifacts))
        self._save_hash_registry()
        
        return CollectionResult(
            total_found=len(collected_artifacts),
            total_collected=sum(1 for a in collected_artifacts if a.collection_status == "success"),
            failed=sum(1 for a in collected_artifacts if a.collection_status == "failed"),
            artifacts=collected_artifacts
        )

    def _expand_dissect_wildcards(self, accessor: FileSystemAccessor, pattern: str) -> List[str]:
        """Manually expand wildcards for dissect paths with case-insensitivity and ** recursion."""
        parts = pattern.lstrip('/').split('/')
        current_paths = ['/']
        
        i = 0
        while i < len(parts):
            part = parts[i]
            if not part: 
                i += 1
                continue
            
            next_paths = []
            
            # DEEP RECURSION SUPPORT (**)
            if part == '**':
                # Recursively find all directories from current_paths
                for cp in current_paths:
                    try:
                        # Add current path
                        next_paths.append(cp)
                        # Find all subdirectories recursively
                        self._walk_recursive_dirs(accessor, cp, next_paths)
                    except:
                        pass
                # Move to next part after **
                current_paths = list(set(next_paths))
                i += 1
                continue

            # STANDARD WILDCARD/DIRECT MATCH
            clean_part = part
            stream_suffix = ""
            if ':' in part:
                clean_part, stream_suffix = part.split(':', 1)
                stream_suffix = ':' + stream_suffix

            for cp in current_paths:
                try:
                    # In case cp itself was a result of a case-insensitive match or direct root
                    dir_node = accessor.fs_info.get(cp)
                    if not dir_node.is_dir(): continue
                    
                    target_lower = clean_part.lower()
                    
                    if '*' in clean_part or '?' in clean_part:
                        import fnmatch
                        for entry in dir_node.scandir():
                            name = getattr(entry, 'name', '')
                            if fnmatch.fnmatch(name.lower(), target_lower):
                                new_path = f"{cp.rstrip('/')}/{name}{stream_suffix}"
                                next_paths.append(new_path)
                    else:
                        # Case-insensitive lookup for EVERY part
                        found = False
                        # Try direct first (optimization)
                        try:
                            item = dir_node.get(clean_part)
                            if item.name.lower() == target_lower:
                                next_paths.append(f"{cp.rstrip('/')}/{item.name}{stream_suffix}")
                                found = True
                        except:
                            pass
                        
                        if not found:
                            # Manual case-insensitive fallback
                            for entry in dir_node.scandir():
                                if entry.name.lower() == target_lower:
                                    next_paths.append(f"{cp.rstrip('/')}/{entry.name}{stream_suffix}")
                                    found = True
                                    break
                except Exception as e:
                    # print(f"[DEBUG] Wildcard expansion error at {cp}/{clean_part}: {e}")
                    pass
            current_paths = list(set(next_paths))
            if not current_paths:
                break
            i += 1
        if current_paths and current_paths != ['/']:
            print(f"[DEBUG] Wildcard expansion for {pattern} found {len(current_paths)} matches")
        return current_paths

    def _walk_recursive_dirs(self, accessor: FileSystemAccessor, current_path: str, results: List[str]):
        """Helper to recursively find all subdirectories for ** expansion."""
        try:
            dir_node = accessor.fs_info.get(current_path)
            for entry in dir_node.scandir():
                if entry.is_dir():
                    new_path = f"{current_path.rstrip('/')}/{entry.name}"
                    results.append(new_path)
                    self._walk_recursive_dirs(accessor, new_path, results)
        except:
            pass

    def _process_image_entry(self, accessor: FileSystemAccessor, entry, entry_path: str, forced_artifact_type: Optional[str]) -> Optional[CollectedArtifactInfo]:
        """Process a single file entry from a forensic image."""
        # Detect type based on filename
        filename = getattr(entry, 'name', '')
        is_dir = entry.is_dir()
        
        # Artifact detector uses C:\path\ style. Folders should end with \
        # Sanitize filename for Windows (replace colons with underscores)
        safe_filename = filename.replace(':', '_')
        dummy_path = os.path.join("C:\\", "fake", safe_filename)
        if is_dir:
            dummy_path += "\\"
        
        # Use forced type from definition if available, otherwise detect
        if forced_artifact_type and forced_artifact_type not in (None, "All Types", "Unknown"):
            artifact_type = forced_artifact_type
        else:
            detection_result = self.detect_artifact_type(dummy_path)
            artifact_type = detection_result.artifact_type
        
        # Special case for ShimCache filtering
        if forced_artifact_type == "ShimCache":
            if "SYSTEM" not in filename.upper():
                return None

        try:
            stat_info = entry.stat()
            file_size = getattr(stat_info, 'st_size', 0)
        except Exception:
            file_size = 0
        
        if self.scan_only:
            return CollectedArtifactInfo(
                source_path=f"image:{entry_path}",
                destination_path=None,
                artifact_type=artifact_type,
                file_size=file_size,
                file_hash="",
                collection_status="success",
                error_message=None,
                timestamp=datetime.now()
            )
        
        # Determine destination path
        destination_path = self.copy_artifact_to_case(dummy_path, artifact_type)
        print(f"[DEBUG] Destination path for {entry_path} is {destination_path}")
        
        # Extract file or directory from image directly to destination
        try:
            success = False
            if entry.is_dir():
                num_files = accessor.read_directory_recursive(entry_path, destination_path)
                success = num_files >= 0
            else:
                bytes_written = accessor.read_file_streaming(entry_path, destination_path)
                # If extraction results in 0 bytes but logical size > 0, it's a candidate for VSS fallback
                if bytes_written == 0 and file_size > 0:
                    print(f"[VSS-FALLBACK] {entry_path} extracted 0 bytes. Trying VSS...")
                else:
                    success = True

            # Task 2: VSS Fallback Logic
            if not success:
                print(f"[VSS-FALLBACK] Primary extraction failed for {entry_path}. Attempting VSS fallback...")
                success = self._try_vss_fallback(entry_path, destination_path, is_dir)
                if success:
                    print(f"[VSS-FALLBACK] Successfully recovered {entry_path} from VSS.")

        except Exception as e:
            # Even on exception, try fallback
            print(f"[ERROR] Primary extraction failed for {entry_path}: {e}. Trying VSS fallback...")
            success = self._try_vss_fallback(entry_path, destination_path, is_dir)
            if not success:
                return CollectedArtifactInfo(
                    source_path=f"image:{entry_path}",
                    destination_path=destination_path,
                    artifact_type=artifact_type,
                    file_size=0,
                    file_hash="",
                    collection_status="failed",
                    error_message=str(e),
                    timestamp=datetime.now()
                )

        # Calculate hash and handle deduplication
        file_hash = ""
        if self.calculate_hashes and os.path.exists(destination_path) and not is_dir:
            file_hash = self._calculate_file_hash(destination_path)
            if file_hash:
                existing_path = self._is_duplicate(file_hash)
                if existing_path and existing_path != destination_path:
                    # Only skip if the destination path is truly a duplicate (same category)
                    if os.path.dirname(existing_path) == os.path.dirname(destination_path):
                        if os.path.exists(destination_path):
                            try:
                                os.remove(destination_path)
                            except:
                                pass
                        return CollectedArtifactInfo(
                            source_path=f"image:{entry_path}",
                            destination_path=existing_path,
                            artifact_type=artifact_type,
                            file_size=os.path.getsize(existing_path) if os.path.exists(existing_path) else 0,
                            file_hash=file_hash,
                            collection_status="skipped_duplicate",
                            error_message=f"Duplicate of {existing_path}",
                            timestamp=datetime.now()
                        )
                    else:
                        # Same file hash but different category (e.g. SYSTEM in Registry_Hives vs ShimCache)
                        # We SHOULD extract it again to the new directory
                        pass
                self.collected_hashes[file_hash] = destination_path
        
        return CollectedArtifactInfo(
            source_path=f"image:{entry_path}",
            destination_path=destination_path,
            artifact_type=artifact_type,
            file_size=os.path.getsize(destination_path) if os.path.exists(destination_path) else 0,
            file_hash=file_hash,
            collection_status="success",
            error_message=None,
            timestamp=datetime.now()
        )

    def _try_vss_fallback(self, entry_path: str, dest_path: str, is_dir: bool) -> bool:
        """Attempt to extract an artifact from discovered VSS snapshots."""
        if not hasattr(self, '_vss_accessors') or not self._vss_accessors:
            return False
            
        for fallback_accessor in self._vss_accessors:
            try:
                if is_dir:
                    num = fallback_accessor.read_directory_recursive(entry_path, dest_path)
                    if num > 0: return True
                else:
                    written = fallback_accessor.read_file_streaming(entry_path, dest_path)
                    if written > 0: return True
            except:
                continue
        return False

    def _generate_partition_metadata(self, img_info, image_path: str):
        """Generate partition_info.json for Crow-Claw parity (Task 3)."""
        import json
        try:
            partitions_data = []
            from dissect.target.volume import open as open_volume
            vs = open_volume(img_info)
            for i, vol in enumerate(vs.volumes):
                partitions_data.append({
                    "index": i,
                    "offset": vol.offset,
                    "size": vol.size,
                    "description": getattr(vol, 'description', 'N/A'),
                    "filesystem": getattr(vol, 'fs_type', 'Unknown')
                })
            
            metadata_path = os.path.join(self.case_root, "partition_info.json")
            with open(metadata_path, 'w') as f:
                json.dump({
                    "image_path": image_path,
                    "collection_time": datetime.now().isoformat(),
                    "partitions": partitions_data
                }, f, indent=4)
            print(f"[IMAGE-COLLECTION] Generated partition metadata: {metadata_path}")
        except Exception as e:
            print(f"[WARNING] Failed to generate partition metadata: {e}")

    def _process_image_entry_by_path(self, accessor: FileSystemAccessor, entry_path: str, artifact_type: Optional[str]) -> Optional[CollectedArtifactInfo]:
        """Process a file entry from a path, handling NTFS streams."""
        # Handle NTFS stream syntax (e.g. /path/to/file:stream)
        base_path = entry_path
        stream_name = None
        if ':' in entry_path and not entry_path.endswith(':'):
            parts = entry_path.split(':')
            base_path = parts[0]
            stream_name = parts[1]

        # Get the entry
        try:
            entry = accessor.fs_info.get(base_path)
        except Exception as e:
            return None
        
        if stream_name:
            return self._process_image_stream(accessor, entry, entry_path, stream_name, artifact_type)
            
        return self._process_image_entry(accessor, entry, entry_path, artifact_type)

    def _process_image_stream(self, accessor: FileSystemAccessor, entry, full_path: str, stream_name: str, artifact_type: Optional[str]) -> Optional[CollectedArtifactInfo]:
        """Special handling for NTFS streams like $UsnJrnl:$J."""
        filename = os.path.basename(full_path)
        # Sanitize stream filename for Windows compatibility
        safe_filename = filename.replace(':', '_')
        dummy_path = os.path.join("C:\\", "fake", safe_filename)
        
        # If we don't have a forced artifact type, try to detect or use special cases
        if not artifact_type or artifact_type == "Unknown":
            if "$UsnJrnl" in filename:
                artifact_type = "USN"
            else:
                detection_result = self.detect_artifact_type(dummy_path)
                artifact_type = detection_result.artifact_type
        
        # Determine destination
        destination_path = self.copy_artifact_to_case(dummy_path, artifact_type)
        print(f"[DEBUG] Destination for stream {full_path} is {destination_path}")
        
        # Extract stream
        try:
            accessor.read_file_streaming(full_path, destination_path)
            print(f"[DEBUG] Successfully extracted stream {full_path}")
        except Exception as e:
            print(f"[ERROR] Failed to extract stream {full_path}: {e}")
            return None
            
        # Calculate hash and handle deduplication
        file_hash = ""
        if self.calculate_hashes and os.path.exists(destination_path):
            file_hash = self._calculate_file_hash(destination_path)
            if file_hash:
                existing_path = self._is_duplicate(file_hash)
                if existing_path and existing_path != destination_path:
                    # Only skip if the destination path is truly a duplicate (same category)
                    if os.path.dirname(existing_path) == os.path.dirname(destination_path):
                        if os.path.exists(destination_path):
                            try:
                                os.remove(destination_path)
                            except:
                                pass
                        return CollectedArtifactInfo(
                            source_path=f"image:{full_path}",
                            destination_path=existing_path,
                            artifact_type=artifact_type,
                            file_size=os.path.getsize(existing_path) if os.path.exists(existing_path) else 0,
                            file_hash=file_hash,
                            collection_status="skipped_duplicate",
                            error_message=f"Duplicate of {existing_path}",
                            timestamp=datetime.now()
                        )
                    else:
                        # Same file hash but different category
                        pass
                self.collected_hashes[file_hash] = destination_path

        return CollectedArtifactInfo(
            source_path=f"image:{full_path}",
            destination_path=destination_path,
            artifact_type=artifact_type,
            file_size=os.path.getsize(destination_path) if os.path.exists(destination_path) else 0,
            file_hash=file_hash,
            collection_status="success",
            error_message=None,
            timestamp=datetime.now()
        )

class ImageCollectionCoordinator(CollectionCoordinator):
    """Extends CollectionCoordinator to handle image-based extraction."""
    def __init__(self, case_root: str, calculate_hashes: bool = True, validate_artifacts: bool = False, scan_only: bool = False):
        super().__init__(case_root, calculate_hashes, validate_artifacts, scan_only)
        self.artifact_collector = ImageArtifactCollector(case_root, calculate_hashes, validate_artifacts, scan_only)
        
    def collect_from_image(self, image_path: str, selected_partitions: List[int], artifact_type_filter: Optional[str] = None) -> CollectionSummary:
        self.errors = []; self.warnings = []; self.artifacts_found = 0; self.artifacts_collected = 0; self.artifacts_failed = 0
        if not self._validate_case_directory(): raise ValueError("Case directory validation failed")
        start_time_val = datetime.now()
        self.start_time = datetime.now().timestamp()
        self.artifact_collector.set_progress_callback(self._collector_progress_callback)
        
        try:
            result = self.artifact_collector.collect_from_image(image_path=image_path, selected_partitions=selected_partitions, artifact_type_filter=artifact_type_filter)
            self.artifacts_found = result.total_found; self.artifacts_collected = result.total_collected; self.artifacts_failed = result.failed
            self._aggregate_errors(result)
            end_time_val = datetime.now()
            summary = self._generate_collection_summary(result, start_time_val, end_time_val)
            if self.progress_callback:
                self.progress_callback(ProgressUpdate(current_file="Complete", processed_count=summary.total_found, total_count=summary.total_found, 
                                      artifacts_found=summary.total_found, artifacts_collected=summary.total_collected, artifacts_failed=summary.failed, elapsed_time=summary.collection_time))
            return summary
        except Exception as e:
            import traceback
            print(f"[ERROR] ImageCollectionCoordinator error: {e}")
            traceback.print_exc()
            self.errors.append(f"Image extraction failure: {str(e)}")
            now = datetime.now()
            return CollectionSummary(total_found=0, total_collected=0, failed=0, collection_time=(now-start_time_val).total_seconds(), artifacts=[], start_time=start_time_val, end_time=now)
