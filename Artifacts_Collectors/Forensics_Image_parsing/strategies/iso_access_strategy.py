"""
ISO Access Strategy Implementation

This module implements the ISOAccessStrategy for accessing ISO optical disc
images using pycdlib for file system access.
"""

import os
import time
from typing import List, Optional

# Optional imports - gracefully handle missing dependencies
try:
    import pycdlib
    from pycdlib.pycdlibexception import PyCdlibException
    PYCDLIB_AVAILABLE = True
except ImportError:
    PYCDLIB_AVAILABLE = False
    print("Warning: pycdlib not available - ISO file system access will be limited")

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


class ISOAccessStrategy(FileAccessStrategy):
    """
    Strategy for accessing ISO optical disc images using pycdlib.
    """
    
    # ISO 9660 signature: "CD001" at offset 32769 (0x8001)
    ISO_SIGNATURE_OFFSET = 32769
    ISO_SIGNATURE = b'CD001'
    
    def __init__(self):
        """Initialize the ISO access strategy."""
        self.img_info = None
        self.file_path = None
        self.error_handler = ErrorHandler()
    
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        if not os.path.exists(file_path):
            return False
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext != '.iso':
            return False
        
        try:
            with open(file_path, 'rb') as f:
                f.seek(self.ISO_SIGNATURE_OFFSET)
                signature = f.read(5)
                return signature == self.ISO_SIGNATURE
        except Exception:
            return False
    
    def access_file(self, file_path: str, dest_path: str) -> AccessResult:
        start_time = time.time()
        
        try:
            if not self._open_image(file_path):
                duration = time.time() - start_time
                return AccessResult(
                    success=False,
                    source_path=file_path,
                    dest_path=dest_path,
                    strategy_used="iso",
                    error="Failed to open ISO image",
                    duration_seconds=duration,
                    status="failed"
                )
            
            # Get image size
            file_size = os.path.getsize(file_path)
            
            duration = time.time() - start_time
            
            return AccessResult(
                success=True,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="iso",
                file_size=file_size,
                duration_seconds=duration,
                status="success"
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_classification = self.error_handler.classify_error(e, "ISO image access")
            
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="iso",
                error=error_classification.user_message,
                duration_seconds=duration,
                status="failed"
            )
    
    def requires_admin(self) -> bool:
        return False
    
    def _open_image(self, file_path: str) -> bool:
        if not PYCDLIB_AVAILABLE:
            print("[ERROR] Cannot open ISO image: pycdlib is not installed")
            return False
        
        try:
            self.img_info = pycdlib.PyCdlib()
            self.img_info.open(file_path)
            self.file_path = file_path
            return True
        except Exception as e:
            print(f"[ERROR] Failed to open ISO image: {e}")
            return False
    
    def _close_image(self):
        if self.img_info:
            try:
                self.img_info.close()
            except Exception:
                pass
            self.img_info = None
            self.file_path = None
    
    def _list_partitions(self) -> List[PartitionInfo]:
        if not self.img_info or not self.file_path:
            return []
        try:
            part_info = PartitionInfo(
                partition_number=0,
                start_offset=0,
                size_bytes=os.path.getsize(self.file_path),
                file_system_type="ISO9660",
                description="ISO9660 Optical Disc Image",
                is_bootable=False
            )
            return [part_info]
        except Exception as e:
            print(f"[ERROR] Failed to detect partitions: {e}")
            return []
    
    def get_img_info(self):
        return self.img_info
    
    def list_partitions(self) -> List[PartitionInfo]:
        return self._list_partitions()
