"""
E01 Access Strategy Implementation

This module implements the E01AccessStrategy for accessing E01/Ex01 (Expert Witness)
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
    print("Warning: dissect not available - E01 file system access will be limited")

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


class E01AccessStrategy(FileAccessStrategy):
    """
    Strategy for accessing E01/Ex01 disk images using dissect.
    """
    
    E01_EXTENSIONS = {'.e01', '.ex01'}
    
    def __init__(self):
        self.img_info = None
        self.error_handler = ErrorHandler()
    
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        if not os.path.exists(file_path):
            return False
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.E01_EXTENSIONS:
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
                    strategy_used="e01",
                    error="Failed to open E01 image",
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
                strategy_used="e01",
                file_size=file_size,
                duration_seconds=duration,
                status="success"
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_classification = self.error_handler.classify_error(e, "E01 image access")
            
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="e01",
                error=error_classification.user_message,
                duration_seconds=duration,
                status="failed"
            )
    
    def requires_admin(self) -> bool:
        return False
    
    def _open_image(self, file_source: Union[str, List[str]]) -> bool:
        if not DISSECT_AVAILABLE:
            print("[ERROR] Cannot open E01 image: dissect is not installed")
            return False
        
        # Determine primary path for opening (dissect usually autodetects siblings from first part)
        primary_path = file_source[0] if isinstance(file_source, list) else file_source
        
        try:
            # Try standard open
            self.img_info = open_container(primary_path)
            return True
        except Exception as e:
            # DETERMINE IF THIS IS A MISSING SEGMENT ISSUE (Logical Copy)
            error_str = str(e).lower()
            if "missing" in error_str and ("segment" in error_str or "ewf file" in error_str):
                print(f"[WARNING] Missing segments detected for {primary_path}. Attempting Lenient/Logical Load...")
                try:
                    # Manually load the available segments
                    from dissect.target.containers.ewf import EWF
                    # EWF class can be more lenient if we hand-provide the file handle
                    fh = open(primary_path, 'rb')
                    # We wrap it in the EWF internal logic but skip the segment-discovery failure
                    self.img_info = EWF(fh)
                    print(f"[INFO] Lenient Load Successful: Identified logical slice of {self.img_info.size} bytes.")
                    return True
                except Exception as inner_e:
                    print(f"[ERROR] Lenient load failed for {primary_path}: {inner_e}")
                    return False
            
            print(f"[ERROR] Failed to open E01 image: {e}")
            return False
    
    def _close_image(self):
        if self.img_info:
            try:
                self.img_info.close()
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
