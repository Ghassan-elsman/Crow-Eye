"""
Raw/DD Access Strategy Implementation

This module implements the RawAccessStrategy for accessing Raw/DD (bit-for-bit)
disk images using the dissect ecosystem for file system access.
"""

import os
import time
from typing import List, Optional, Union

# Optional imports - gracefully handle missing dependencies
try:
    from dissect.target.container import open as open_container
    DISSECT_AVAILABLE = True
except ImportError:
    DISSECT_AVAILABLE = False
    print("Warning: dissect not available - Raw/DD file system access will be limited")

# Handle both relative and absolute imports
try:
    if __package__ or "." in __name__:
        from ...crow_claw.core.access_strategy import FileAccessStrategy
        from ...crow_claw.core.access_result import AccessResult
        from ..data_models import PartitionInfo
        from ..partition_detector import detect_partitions
        from ..error_handler import ErrorHandler
    else:
        from Artifacts_Collectors.crow_claw.core.access_strategy import FileAccessStrategy
        from Artifacts_Collectors.crow_claw.core.access_result import AccessResult
        from data_models import PartitionInfo
        from partition_detector import detect_partitions
        from error_handler import ErrorHandler
except (ImportError, ValueError):
    # Fallback attempt
    try:
        from crow_claw.core.access_strategy import FileAccessStrategy
        from crow_claw.core.access_result import AccessResult
    except ImportError:
        from Artifacts_Collectors.crow_claw.core.access_strategy import FileAccessStrategy
        from Artifacts_Collectors.crow_claw.core.access_result import AccessResult
    from data_models import PartitionInfo
    from partition_detector import detect_partitions
    from error_handler import ErrorHandler


class RawAccessStrategy(FileAccessStrategy):
    """
    Strategy for accessing Raw/DD (bit-for-bit) disk images using dissect.
    
    Raw/DD images are uncompressed, unencrypted bit-for-bit copies of storage devices.
    They have no container format or metadata - just raw disk data. dissect can open
    these images directly.
    """
    
    # Raw/DD file extensions
    RAW_EXTENSIONS = {'.dd', '.raw', '.img', '.001'}
    
    def __init__(self):
        """Initialize the Raw/DD access strategy."""
        self.img_info = None
        self.error_handler = ErrorHandler()
    
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        if not os.path.exists(file_path):
            return False
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.RAW_EXTENSIONS:
            return False
            
        return True
    
    def access_file(self, file_path: str, dest_path: str) -> AccessResult:
        start_time = time.time()
        
        try:
            if not self._open_image(file_path):
                duration = time.time() - start_time
                return AccessResult(
                    success=False,
                    source_path=file_path,
                    dest_path=dest_path,
                    strategy_used="raw",
                    error="Failed to open Raw/DD image",
                    duration_seconds=duration,
                    status="failed"
                )
            
            # Get image size
            self.img_info.seek(0, 2)
            file_size = self.img_info.tell()
            self.img_info.seek(0)
            
            duration = time.time() - start_time
            
            return AccessResult(
                success=True,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw",
                file_size=file_size,
                duration_seconds=duration,
                status="success"
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_classification = self.error_handler.classify_error(e, "Raw/DD image access")
            
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="raw",
                error=error_classification.user_message,
                duration_seconds=duration,
                status="failed"
            )
    
    def requires_admin(self) -> bool:
        return False
    
    def _open_image(self, file_source: Union[str, List[str]]) -> bool:
        if not DISSECT_AVAILABLE:
            print("[ERROR] Cannot open Raw/DD image: dissect is not installed")
            return False

        try:
            from typing import List, Union
            import os

            # Normalize file_source: if it's a list of 1, treat as single string
            if isinstance(file_source, list) and len(file_source) == 1:
                file_source = str(file_source[0])
            elif isinstance(file_source, list):
                # Ensure all elements are strings
                file_source = [str(s) for s in file_source]
            else:
                file_source = str(file_source)

            if isinstance(file_source, list):
                # Explicit list of multiple segments provided by user
                print(f"[INFO] Chaining {len(file_source)} explicit Raw/DD segments")
                try:
                    from dissect.util.stream import MultipartStream
                    self._segment_handles = [open(s, 'rb') for s in file_source]
                    self.img_info = MultipartStream(self._segment_handles)
                    return True
                except ImportError:
                    print("[WARNING] MultipartStream not found in dissect.util.stream. Using alternative split container.")
                    try:
                        self.img_info = open_container(file_source)
                        self._segment_handles = []
                        return True
                    except Exception as e:
                        print(f"[ERROR] Split container failed: {e}. Trying first segment only.")
                        file_source = file_source[0]
                        # Fall through to single file logic below

            # Single file path provided - use existing autodiscovery logic
            if not isinstance(file_source, list):
                file_path = file_source
                directory = os.path.dirname(os.path.abspath(file_path))
                filename = os.path.basename(file_path)
                base, ext = os.path.splitext(filename)

                import glob
                import re

                segments = [file_path]
                # If it's a numeric extension like .001 or .01, search for siblings
                # ONLY if we aren't already coming from a failed list-open
                if re.match(r'\.\d{2,3}$', ext):
                    pattern = os.path.join(directory, base + ".[0-9]" * (len(ext) - 1))
                    found_segments = sorted(glob.glob(pattern))
                    if len(found_segments) > 1:
                        segments = found_segments

                if len(segments) > 1:
                    print(f"[INFO] Auto-chaining {len(segments)} Raw/DD segments starting with {filename}")
                    try:
                        from dissect.util.stream import MultipartStream
                        self._segment_handles = [open(s, 'rb') for s in segments]
                        self.img_info = MultipartStream(self._segment_handles)
                    except ImportError:
                        print("[WARNING] MultipartStream not found in dissect.util.stream. Using split container fallback.")
                        self.img_info = open_container(segments)
                        self._segment_handles = []
                else:
                    self.img_info = open_container(file_path)
                    self._segment_handles = []

                return True
        except Exception as e:
            print(f"[ERROR] Failed to open Raw/DD image: {e}")
            return False
    def _close_image(self):
        if self.img_info:
            try:
                # Close the main info if it came from open_container
                if hasattr(self.img_info, 'close'):
                    self.img_info.close()
                # Close individual segment handles if we used MultipartStream
                if hasattr(self, '_segment_handles'):
                    for fh in self._segment_handles:
                        try: fh.close()
                        except: pass
            except Exception:
                pass
            self.img_info = None
    
    def _list_partitions(self) -> List[PartitionInfo]:
        if not self.img_info:
            return []
        try:
            return detect_partitions(self.img_info)
        except Exception as e:
            print(f"[ERROR] Failed to detect partitions: {e}")
            return []
    
    def get_img_info(self):
        return self.img_info
    
    def list_partitions(self) -> List[PartitionInfo]:
        return self._list_partitions()
