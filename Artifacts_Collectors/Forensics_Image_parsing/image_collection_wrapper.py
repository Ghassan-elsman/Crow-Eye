"""
Forensic Image Collection Wrapper

This module provides wrapper classes that extend the Offline Importer's
collection engine to natively support forensic image files via dissect.
This avoids modifying the core Offline Importer files.
"""

import hashlib
import logging
import os
import sys
from datetime import datetime
from typing import List, Optional, Union

logger = logging.getLogger("image_parsing.collection")

# Root of the stand-in path the type detector classifies an image entry by.
# "C:\\" on Windows, as before. On Linux os.path.join("C:\\", ...) gave
# "C:\/fake/x" and a folder's trailing "\\" became part of its name, so a
# folder entry could not be classified there.
_DUMMY_ROOT = "C:\\" if os.name == "nt" else os.sep

# Not damage: a junction such as "Users/Default User" resolves to nothing in an
# image, a name can be a file where a folder was expected. Only the remaining
# errors (read failures, corrupt records) count as unreadable folders.
_BENIGN_LOOKUP_ERRORS = ("FileNotFoundError", "NotADirectoryError", "NotASymlinkError",
                         "SymlinkRecursionError", "IsADirectoryError")


def _is_damage(exc) -> bool:
    return not any(cls.__name__ in _BENIGN_LOOKUP_ERRORS for cls in type(exc).__mro__)

# Add parent and Offline_Importer directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# One identity for the importer: through the package when the app root is on
# sys.path (it always is inside Crow-Eye), so these classes ARE the ones the
# Offline Importer and ParserInvoker use and their records reach the importer's
# log. The bare name is only for running this folder on its own.
try:
    from Artifacts_Collectors.Offline_Importer.artifact_collector import (
        ArtifactCollector, CollectedArtifactInfo, CollectionResult)
    from Artifacts_Collectors.Offline_Importer.collection_coordinator import (
        CollectionCoordinator, CollectionSummary, ProgressUpdate)
except ImportError:
    from Offline_Importer.artifact_collector import ArtifactCollector, CollectedArtifactInfo, CollectionResult
    from Offline_Importer.collection_coordinator import CollectionCoordinator, CollectionSummary, ProgressUpdate

try:
    from utils.parse_status import make_issue
except ImportError:  # pragma: no cover - standalone
    def make_issue(code, detail="", **context):
        return None

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

    # The "Include browser cache" toggle. Set by the coordinator / dialog.
    include_browser_cache = True

    def collect_from_image(self, image_path: Union[str, List[str]], selected_partitions: List[int], artifact_type_filter: Optional[str] = None) -> CollectionResult:
        """Collect-specific artifacts from a forensic image file (Crow-Claw style)."""
        self._cancelled = False
        primary_path = image_path[0] if isinstance(image_path, list) else image_path
        self._image_path = primary_path
        # Problems that belong to the run, not to one file - the image window
        # puts them in the Parse Status Report.
        self.session_issues = []
        self._unreadable_dirs = 0
        logger.info(f"Starting targeted extraction from: {primary_path}")

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
                logger.info(f"Found {len(target.vss)} VSS snapshots for fallback.")
                for snapshot in target.vss:
                    try:
                        # Create an accessor for each snapshot
                        snapshot_accessor = FileSystemAccessor(snapshot)
                        # We need to open the partition in the snapshot too
                        # Usually snapshots are of a specific volume, so offset 0
                        snapshot_accessor.open_partition(0)
                        vss_accessors.append(snapshot_accessor)
                    except Exception as exc:
                        logger.warning("A shadow copy could not be opened: %s", exc)
            self._vss_accessors = vss_accessors # Store for fallback method
        except Exception as e:
            self._vss_accessors = []
            if "can't find plugin" in str(e).lower():
                # dissect has no shadow-copy reader for this target - a fact
                # about the tooling, not the evidence; nothing to report.
                logger.info("No shadow-copy support for this image: %s", e)
            else:
                logger.warning("VSS discovery failed: %s", e)
                issue = make_issue("vss_unavailable", "%s: %s" % (type(e).__name__, e))
                if issue is not None:
                    self.session_issues.append(issue)

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

                logger.info(f"Scanning partition {partition_num} at offset {part_offset}")
                self._current_partition = partition_num
                if not accessor.open_partition(part_offset):
                    logger.warning("Could not mount partition %s at offset %s", partition_num, part_offset)
                    issue = make_issue("no_filesystem",
                                       "Partition %s (offset %s) could not be opened, so nothing "
                                       "was extracted from it." % (partition_num, part_offset),
                                       partition=partition_num)
                    if issue is not None:
                        self.session_issues.append(issue)
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

                    # Tree-preserving artifacts (browser profiles) are copied
                    # with their path intact and reported once per user.
                    if getattr(art_def, "preserve_tree", False):
                        collected_artifacts.extend(
                            self._collect_preserved_tree(accessor, art_def, partition_num))
                        continue

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
        self._user_placer.save()
        if self._unreadable_dirs:
            issue = make_issue("unreadable_folders",
                               "%d folder(s) could not be listed." % self._unreadable_dirs)
            if issue is not None:
                self.session_issues.append(issue)

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
                # Sorted, not set order: set order changes from process to
                # process, and with it which user's file was collected first.
                current_paths = sorted(set(next_paths))
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
                    # A folder the file system would not list: damaged
                    # structures. Counted, so the run can say so.
                    if _is_damage(e):
                        self._unreadable_dirs = getattr(self, "_unreadable_dirs", 0) + 1
                        logger.warning("Folder could not be listed: %s/%s: %s", cp, clean_part, e)
                    else:
                        logger.debug("Not a folder here: %s/%s: %s", cp, clean_part, e)
            current_paths = sorted(set(next_paths))
            if not current_paths:
                break
            i += 1
        if current_paths and current_paths != ['/']:
            logger.debug(f"Wildcard expansion for {pattern} found {len(current_paths)} matches")
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
        except Exception as e:
            if _is_damage(e):
                self._unreadable_dirs = getattr(self, "_unreadable_dirs", 0) + 1
                logger.warning("Folder could not be walked: %s: %s", current_path, e)
            else:
                logger.debug("Not walkable: %s: %s", current_path, e)

    @staticmethod
    def _win_to_dissect(win_path: str) -> str:
        """``{PARTITION}\\Users\\*\\X`` -> ``/Users/*/X`` (dissect root-relative)."""
        import re
        p = re.sub(r'^(\\\\\.\\)?([a-zA-Z]:|\{PARTITION\}):?', '', win_path)
        p = p.replace('\\', '/')
        while '//' in p:
            p = p.replace('//', '/')
        return p if p.startswith('/') else '/' + p

    def _volume_tag(self, partition_num) -> str:
        """``vol_<partition>_<image id>``: one source volume, across runs."""
        import hashlib
        image_id = hashlib.sha1(os.path.normcase(os.path.abspath(
            getattr(self, "_image_path", "") or "")).encode("utf-8", "replace")).hexdigest()[:8]
        return f"vol_{partition_num}_{image_id}"

    def _image_user_destination(self, entry_path: str, artifact_type: str) -> Optional[str]:
        """The owner's folder for a per-user file in the image, or None.

        Keyed on image + partition, so ``Users/Hunter`` on two partitions (or
        in two images of one case) never share a folder.
        """
        prefix = "image:" + self._volume_tag(getattr(self, "_current_partition", ""))
        dest = self._user_destination(entry_path, artifact_type,
                                      source_key_prefix=prefix, base="")
        if dest and not self.scan_only:
            # The flat type folders exist from the start; an owner's folder
            # is created when its first file arrives.
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        return dest

    def _collect_preserved_tree(self, accessor: FileSystemAccessor, art_def, partition_num) -> List[CollectedArtifactInfo]:
        """Copy every root an artifact matches, keeping its path from the volume
        root, and return one result per user folder.

        Browser profiles are the reason: each profile has its own ``History``,
        and only the folder a file sits in says which user, browser and profile
        it belongs to - flattening into one folder per type destroyed that.
        Files are not hash-deduplicated across the case for the same reason: an
        identical file in two profiles is two pieces of evidence.
        """
        try:
            from Artifacts_Collectors.browser_paths import browser_dir_skipped, browser_root_excluded
        except ImportError:
            from browser_paths import browser_dir_skipped, browser_root_excluded
        include_cache = bool(self.include_browser_cache)
        type_name = art_def.artifact_type.value
        subdir = self.artifact_directories.get(type_name, type_name)
        # Partition AND image: partition 3 of a second image in the same case
        # must not land in (and be skipped as already present in) the first's.
        vol_tag = self._volume_tag(partition_num)
        vol_root = os.path.join(self.target_artifacts_dir, subdir, vol_tag)

        patterns = list(art_def.get_all_paths())
        if include_cache:
            patterns += list(getattr(art_def, "cache_paths", []) or [])

        per_user = {}   # "/Users/<name>" -> [files, bytes, failed]
        seen_roots = set()
        for win_path in patterns:
            if self._cancelled:
                break
            for root in self._expand_dissect_wildcards(accessor, self._win_to_dissect(win_path)):
                key = root.lower()
                if self._cancelled or key in seen_roots or root == '/' or browser_root_excluded(root):
                    continue
                seen_roots.add(key)
                parts = root.strip('/').split('/')
                user_key = '/'.join(parts[:2]) if len(parts) >= 2 and parts[0].lower() == 'users' else parts[0]
                stats = per_user.setdefault(user_key, [0, 0, 0])
                if self.scan_only:
                    stats[0] += 1
                    continue
                files, size, failed = self._copy_tree(accessor, root, vol_root, include_cache,
                                                      browser_dir_skipped)
                stats[0] += files
                stats[1] += size
                stats[2] += failed
                self._report_progress(f"Browser: {root}", stats[0], 0)

        results = []
        for user_key, (files, size, failed) in sorted(per_user.items()):
            if not files and not failed and not self.scan_only:
                continue    # matched a pattern but held nothing to copy
            dest = os.path.join(vol_root, *user_key.split('/'))
            results.append(CollectedArtifactInfo(
                # Per volume: two partitions can both hold Users/<name>.
                source_path=f"image:{vol_tag}/{user_key}",
                destination_path=None if self.scan_only else dest,
                artifact_type=type_name,
                file_size=size,
                file_hash="",
                collection_status="success" if files else "failed",
                error_message=(f"{failed} file(s) could not be read" if failed else None),
                timestamp=datetime.now()))
        return results

    def _copy_tree(self, accessor: FileSystemAccessor, root: str, vol_root: str,
                   include_cache: bool, skipped) -> tuple:
        """Copy ``root`` from the image to ``vol_root/<root>``, skipping folders
        ``skipped(name, include_cache)`` rejects. Returns (files, bytes, failed);
        files already present from an earlier run count as collected."""
        files = size = failed = 0
        stack = [root]
        while stack:
            if self._cancelled:
                break
            current = stack.pop()
            try:
                node = accessor.fs_info.get(current)
            except Exception:
                failed += 1
                continue
            try:
                is_dir = node.is_dir()
            except Exception:
                is_dir = False
            if not is_dir:
                dest = os.path.join(vol_root, *current.strip('/').split('/'))
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if os.path.exists(dest):
                        # Same image, same path: an overlapping pattern or an
                        # earlier run already copied it. Counted, so a re-run
                        # still reports the user; a short (interrupted) copy
                        # is taken again.
                        try:
                            want = node.stat().st_size
                        except Exception:
                            want = None
                        have = os.path.getsize(dest)
                        if want is None or have == want:
                            size += have
                            files += 1
                            continue
                    # Byte for byte: zero-skipping would shift every offset.
                    size += accessor.read_file_streaming(current, dest, compact=False) or 0
                    files += 1
                except Exception as exc:
                    failed += 1
                    logger.warning(f"Browser file not extracted: {current}: {exc}")
                continue
            try:
                entries = list(node.scandir())
            except Exception:
                failed += 1
                continue
            for entry in entries:
                name = getattr(entry, 'name', '')
                if name in ('.', '..'):
                    continue
                try:
                    child_is_dir = entry.is_dir()
                except Exception:
                    child_is_dir = False
                if child_is_dir and skipped(name, include_cache):
                    continue
                stack.append(f"{current.rstrip('/')}/{name}")
        return files, size, failed

    def _process_image_entry(self, accessor: FileSystemAccessor, entry, entry_path: str, forced_artifact_type: Optional[str]) -> Optional[CollectedArtifactInfo]:
        """Extract one entry, and put it in the run's chain-of-custody record.

        The SHA-256 is the one taken as the bytes came out of the image and
        were written (one read) - the copy is not read back - so the entry
        says so rather than claiming an independent verification.
        """
        info = self._process_image_entry_impl(accessor, entry, entry_path, forced_artifact_type)
        try:
            from utils import custody
            rec = custody.active()
            if rec is not None and info is not None:
                if info.collection_status == "failed":
                    rec.add_failure(info.source_path, info.error_message or "not extracted",
                                    method="image extraction", artifact_type=info.artifact_type)
                else:
                    entry_rec = rec.add_source(
                        info.source_path, method="image extraction",
                        times={"size": info.file_size}, hash_source=False,
                        source_sha256=info.file_hash or None,
                        note="; ".join(x for x in (
                            info.artifact_type,
                            "duplicate - not kept" if info.collection_status == "skipped_duplicate" else None)
                            if x))
                    if info.destination_path:
                        entry_rec["copy"] = info.destination_path
                    if info.file_hash:
                        entry_rec["hash_basis"] = ("SHA-256 of the bytes read from the image, "
                                                   "taken as they were written to the copy")
        except Exception as e:
            logger.debug("custody entry for %s not recorded: %s", entry_path, e)
        return info

    def _process_image_entry_impl(self, accessor: FileSystemAccessor, entry, entry_path: str, forced_artifact_type: Optional[str]) -> Optional[CollectedArtifactInfo]:
        """Process a single file entry from a forensic image."""
        # Detect type based on filename
        filename = getattr(entry, 'name', '')
        is_dir = entry.is_dir()

        # Artifact detector uses C:\path\ style. Folders should end with \
        # Sanitize filename for Windows (replace colons with underscores)
        safe_filename = filename.replace(':', '_')
        dummy_path = os.path.join(_DUMMY_ROOT, "fake", safe_filename)
        if is_dir:
            dummy_path += os.sep

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

        # Determine destination path. An artifact type with no case folder is
        # reported for THIS item; letting the ValueError escape used to abort
        # the whole extraction and return an empty summary.
        user_dest = self._image_user_destination(entry_path, artifact_type)
        try:
            destination_path = user_dest or self.copy_artifact_to_case(dummy_path, artifact_type)
        except ValueError as exc:
            logger.warning(f"{entry_path}: {exc}")
            return CollectedArtifactInfo(
                source_path=f"image:{entry_path}", destination_path="",
                artifact_type=artifact_type, file_size=file_size, file_hash="",
                collection_status="failed", error_message=str(exc),
                timestamp=datetime.now())
        logger.debug(f"Destination path for {entry_path} is {destination_path}")

        # Extract file or directory from image directly to destination.
        # The copy is hashed as it is written (`streamed`); reading the
        # destination back for its SHA-256 doubled the I/O of every file.
        streamed = hashlib.sha256() if (self.calculate_hashes and not is_dir) else None
        try:
            success = False
            if entry.is_dir():
                num_files = accessor.read_directory_recursive(entry_path, destination_path)
                success = num_files >= 0
            else:
                bytes_written = accessor.read_file_streaming(entry_path, destination_path,
                                                             hasher=streamed)
                # If extraction results in 0 bytes but logical size > 0, it's a candidate for VSS fallback
                if bytes_written == 0 and file_size > 0:
                    logger.info(f"{entry_path} extracted 0 bytes. Trying VSS...")
                else:
                    success = True

            # Task 2: VSS Fallback Logic
            if not success:
                streamed = None            # the fallback writes the file; hash it after
                logger.info(f"Primary extraction failed for {entry_path}. Attempting VSS fallback...")
                success = self._try_vss_fallback(entry_path, destination_path, is_dir)
                if success:
                    logger.info(f"Successfully recovered {entry_path} from VSS.")

        except Exception as e:
            # Even on exception, try fallback
            streamed = None
            logger.error(f"Primary extraction failed for {entry_path}: {e}. Trying VSS fallback...")
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

        # Calculate hash and handle deduplication. Per-user files are hashed
        # but never deduplicated: each user's copy is its own evidence.
        file_hash = ""
        if user_dest and self.calculate_hashes and os.path.exists(destination_path) and not is_dir:
            file_hash = streamed.hexdigest() if streamed is not None \
                else self._calculate_file_hash(destination_path)
        elif self.calculate_hashes and os.path.exists(destination_path) and not is_dir:
            file_hash = streamed.hexdigest() if streamed is not None \
                else self._calculate_file_hash(destination_path)
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
            logger.info(f"Generated partition metadata: {metadata_path}")
        except Exception as e:
            logger.warning(f"Failed to generate partition metadata: {e}")

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
        dummy_path = os.path.join(_DUMMY_ROOT, "fake", safe_filename)

        # If we don't have a forced artifact type, try to detect or use special cases
        if not artifact_type or artifact_type == "Unknown":
            if "$UsnJrnl" in filename:
                artifact_type = "USN"
            else:
                detection_result = self.detect_artifact_type(dummy_path)
                artifact_type = detection_result.artifact_type

        # Determine destination (an unmapped type fails this item only)
        try:
            destination_path = (self._image_user_destination(full_path.rsplit(':', 1)[0], artifact_type)
                                or self.copy_artifact_to_case(dummy_path, artifact_type))
        except ValueError as exc:
            logger.warning("%s: %s", full_path, exc)
            return CollectedArtifactInfo(
                source_path=f"image:{full_path}", destination_path="",
                artifact_type=artifact_type, file_size=0, file_hash="",
                collection_status="failed", error_message=str(exc), timestamp=datetime.now())
        logger.debug(f"Destination for stream {full_path} is {destination_path}")

        # Extract stream
        try:
            accessor.read_file_streaming(full_path, destination_path)
            logger.debug("Extracted stream %s", full_path)
        except Exception as e:
            logger.error("Failed to extract stream %s: %s", full_path, e)
            return CollectedArtifactInfo(
                source_path=f"image:{full_path}", destination_path=destination_path,
                artifact_type=artifact_type, file_size=0, file_hash="",
                collection_status="failed", error_message=str(e), timestamp=datetime.now())

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

    @property
    def session_issues(self):
        return list(getattr(self.artifact_collector, "session_issues", []) or [])

    def collect_from_image(self, image_path: str, selected_partitions: List[int], artifact_type_filter: Optional[str] = None,
                           include_browser_cache: bool = True) -> CollectionSummary:
        self.errors = []; self.warnings = []; self.artifacts_found = 0; self.artifacts_collected = 0; self.artifacts_failed = 0
        self.artifact_collector.include_browser_cache = include_browser_cache
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
            # Raised, not swallowed: an empty summary here used to read as
            # "Extraction completed successfully, 0 artifacts" for an image
            # that never opened.
            logger.error("Image extraction failed: %s", e, exc_info=True)
            self.errors.append(f"Image extraction failure: {str(e)}")
            raise
