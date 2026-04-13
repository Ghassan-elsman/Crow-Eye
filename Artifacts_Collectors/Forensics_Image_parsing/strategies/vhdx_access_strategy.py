"""
VHDX/VHD Access Strategy Implementation

This module implements the VHDXAccessStrategy for accessing VHDX/VHD
virtual disk images using the dissect ecosystem for file system access.
"""

import os
import time
from typing import List, Optional

# Optional imports - gracefully handle missing dependencies
try:
    from dissect.target.container import open as open_container
    DISSECT_AVAILABLE = True
except ImportError:
    DISSECT_AVAILABLE = False
    print("Warning: dissect not available - VHDX file system access will be limited")

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


class VHDXAccessStrategy(FileAccessStrategy):
    """
    Strategy for accessing VHDX/VHD disk images using dissect.
    """
    
    VHDX_EXTENSIONS = {'.vhdx', '.vhd'}
    
    def __init__(self):
        self.img_info = None
        self.error_handler = ErrorHandler()
    
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        if not os.path.exists(file_path):
            return False
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.VHDX_EXTENSIONS:
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
                    strategy_used="vhdx",
                    error="Failed to open VHDX/VHD image",
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
                strategy_used="vhdx",
                file_size=file_size,
                duration_seconds=duration,
                status="success"
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_classification = self.error_handler.classify_error(e, "VHDX image access")
            
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vhdx",
                error=error_classification.user_message,
                duration_seconds=duration,
                status="failed"
            )
    
    def requires_admin(self) -> bool:
        return False
    
    def _open_image(self, file_path: str) -> bool:
        if not DISSECT_AVAILABLE:
            print("[ERROR] Cannot open VHDX image: dissect is not installed")
            return False
        
        try:
            self.img_info = open_container(file_path)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to open VHDX image: {e}")
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
