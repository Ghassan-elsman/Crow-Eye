"""
ImageParser - Central Coordinator for Forensic Image Format Detection

This module provides the ImageParser class, which orchestrates format detection
and strategy selection for forensic images. It initializes all Image_Access_Strategy
instances and provides a unified interface for format detection and partition enumeration.

Responsibilities:
- Detect image format by signature and extension
- Select appropriate Image_Access_Strategy
- Provide fallback for manual format selection
- Enumerate partitions in images
"""

import os
from typing import List, Optional, Union

# Handle both relative and absolute imports
try:
    if __package__ or "." in __name__:
        from .strategies.e01_access_strategy import E01AccessStrategy
        from .strategies.vhdx_access_strategy import VHDXAccessStrategy
        from .strategies.vmdk_access_strategy import VMDKAccessStrategy
        from .strategies.iso_access_strategy import ISOAccessStrategy
        from .strategies.raw_access_strategy import RawAccessStrategy
        from .data_models import PartitionInfo, ImageInfo
        from .error_handler import ErrorHandler
    else:
        from strategies.e01_access_strategy import E01AccessStrategy
        from strategies.vhdx_access_strategy import VHDXAccessStrategy
        from strategies.vmdk_access_strategy import VMDKAccessStrategy
        from strategies.iso_access_strategy import ISOAccessStrategy
        from strategies.raw_access_strategy import RawAccessStrategy
        from data_models import PartitionInfo, ImageInfo
        from error_handler import ErrorHandler
except (ImportError, ValueError):
    from strategies.e01_access_strategy import E01AccessStrategy
    from strategies.vhdx_access_strategy import VHDXAccessStrategy
    from strategies.vmdk_access_strategy import VMDKAccessStrategy
    from strategies.iso_access_strategy import ISOAccessStrategy
    from strategies.raw_access_strategy import RawAccessStrategy
    from data_models import PartitionInfo, ImageInfo
    from error_handler import ErrorHandler


class ImageParser:
    """
    Central coordinator for forensic image format detection and strategy selection.
    
    The ImageParser initializes all 5 Image_Access_Strategy instances (E01, VHDX,
    VMDK, ISO, Raw) and provides a unified interface for:
    - Format detection using signature verification and extension checking
    - Strategy selection based on can_handle() results
    - Partition enumeration
    - Manual format selection when auto-detection fails
    
    Requirements:
    - 3.1: Format detection SHALL use signature verification
    - 3.2: Format detection SHALL use extension checking as fallback
    - 3.3: Unsupported formats SHALL return descriptive error messages
    - 3.4: User SHALL be able to manually select format if auto-detection fails
    - 12.4: Strategy selection SHALL be based on can_handle() results
    """
    
    # Format name constants
    FORMAT_E01 = "E01"
    FORMAT_VHDX = "VHDX"
    FORMAT_VMDK = "VMDK"
    FORMAT_ISO = "ISO"
    FORMAT_RAW = "RAW"
    FORMAT_UNKNOWN = "UNKNOWN"
    
    def __init__(self):
        """
        Initialize the ImageParser with all Image_Access_Strategy instances.
        
        Initializes strategies in priority order:
        1. E01AccessStrategy (most specific signature)
        2. VHDXAccessStrategy (specific signature)
        3. VMDKAccessStrategy (specific signature)
        4. ISOAccessStrategy (specific signature)
        5. RawAccessStrategy (fallback, extension-based)
        """
        self.error_handler = ErrorHandler()
        
        # Initialize all strategy instances
        # Order matters: more specific formats first, fallback formats last
        self.strategies = [
            E01AccessStrategy(),
            VHDXAccessStrategy(),
            VMDKAccessStrategy(),
            ISOAccessStrategy(),
            RawAccessStrategy()  # Fallback strategy (extension-based)
        ]
        
        # Map format names to strategies for manual selection
        self.format_strategy_map = {
            self.FORMAT_E01: E01AccessStrategy,
            self.FORMAT_VHDX: VHDXAccessStrategy,
            self.FORMAT_VMDK: VMDKAccessStrategy,
            self.FORMAT_ISO: ISOAccessStrategy,
            self.FORMAT_RAW: RawAccessStrategy
        }
    
    def detect_format(self, file_source: Union[str, List[str]]) -> str:
        """
        Detect forensic image format using signature verification and extension checking.
        
        Detection process:
        1. Iterate through all strategies in priority order
        2. Call can_handle() on each strategy (performs signature + extension check)
        3. Return format name of first strategy that can handle the file
        4. Return "UNKNOWN" if no strategy can handle the file
        
        Args:
            file_source: Path to the forensic image file or list of paths for segments
            
        Returns:
            Format name: "E01", "VHDX", "VMDK", "ISO", "RAW", or "UNKNOWN"
            
        Requirements:
        - 3.1: Format detection SHALL use signature verification
        - 3.2: Format detection SHALL use extension checking as fallback
        """
        # Determine the primary path for detection
        primary_path = file_source[0] if isinstance(file_source, list) else file_source
        
        # Check if file exists
        if not primary_path or not os.path.exists(primary_path):
            return self.FORMAT_UNKNOWN
        
        # Iterate through strategies and check if any can handle the file
        for strategy in self.strategies:
            try:
                # can_handle() performs both signature and extension checking
                if strategy.can_handle(primary_path, artifact_type=""):
                    # Determine format name based on strategy type
                    strategy_class_name = strategy.__class__.__name__
                    
                    if "E01" in strategy_class_name:
                        return self.FORMAT_E01
                    elif "VHDX" in strategy_class_name:
                        return self.FORMAT_VHDX
                    elif "VMDK" in strategy_class_name:
                        return self.FORMAT_VMDK
                    elif "ISO" in strategy_class_name:
                        return self.FORMAT_ISO
                    elif "Raw" in strategy_class_name:
                        return self.FORMAT_RAW
            except Exception as e:
                # Log error but continue checking other strategies
                print(f"[WARNING] Error checking strategy {strategy.__class__.__name__}: {e}")
                continue
        
        # No strategy could handle the file
        return self.FORMAT_UNKNOWN
    
    def get_strategy(self, file_source: Union[str, List[str]] = None, format_name: str = None):
        """
        Get appropriate Image_Access_Strategy for the image.
        
        This method supports two modes:
        1. Automatic selection: Pass file_source, format is auto-detected
        2. Manual selection: Pass format_name, strategy is selected directly
        
        Args:
            file_source: Path to the forensic image file or list of paths for segments
            format_name: Format name for manual selection ("E01", "VHDX", etc.)
            
        Returns:
            Image_Access_Strategy instance that can handle the file, or None if unsupported
            
        Raises:
            ValueError: If neither file_source nor format_name is provided
            ValueError: If format_name is invalid
            
        Requirements:
        - 3.4: User SHALL be able to manually select format if auto-detection fails
        - 12.4: Strategy selection SHALL be based on can_handle() results
        """
        # Validate input
        if file_source is None and format_name is None:
            raise ValueError("Either file_source or format_name must be provided")
        
        # Manual format selection
        if format_name is not None:
            format_name = format_name.upper()
            
            if format_name not in self.format_strategy_map:
                raise ValueError(
                    f"Invalid format name: {format_name}. "
                    f"Valid formats: {', '.join(self.format_strategy_map.keys())}"
                )
            
            # Create new instance of the selected strategy
            strategy_class = self.format_strategy_map[format_name]
            return strategy_class()
        
        # Automatic format selection
        if file_source is not None:
            # Determine the primary path for detection
            primary_path = file_source[0] if isinstance(file_source, list) else file_source
            
            # Iterate through strategies and return first one that can handle the file
            for strategy in self.strategies:
                try:
                    if strategy.can_handle(primary_path, artifact_type=""):
                        return strategy
                except Exception as e:
                    # Log error but continue checking other strategies
                    print(f"[WARNING] Error checking strategy {strategy.__class__.__name__}: {e}")
                    continue
            
            # No strategy could handle the file
            # Generate descriptive error message
            detected_format = self.detect_format(file_source)
            error_msg = self._generate_unsupported_format_error(primary_path, detected_format)
            print(f"[ERROR] {error_msg}")
            return None
        
        return None
    
    def list_partitions(self, file_source: Union[str, List[str]], format_name: str = None) -> List[PartitionInfo]:
        """
        Enumerate partitions in the forensic image.
        
        Process:
        1. Get appropriate strategy for the image (auto or manual selection)
        2. Open the image using the strategy
        3. Call list_partitions() on the strategy
        4. Return list of PartitionInfo objects
        
        Args:
            file_source: Path to the forensic image file or list of paths for segments
            format_name: Optional format name for manual selection
            
        Returns:
            List of PartitionInfo objects describing each partition.
            Returns empty list if image cannot be opened or has no partitions.
            
        Requirements:
        - 4.5: Multi-partition detection
        - 10.1: Partition enumeration
        """
        primary_path = file_source[0] if isinstance(file_source, list) else file_source
        try:
            # Get appropriate strategy
            strategy = self.get_strategy(file_source=file_source, format_name=format_name)
            
            if strategy is None:
                print(f"[ERROR] No strategy available for: {primary_path}")
                return []
            
            # Open the image
            # Note: The strategy's _open_image() is private, but we can use access_file()
            # to trigger image opening, or we can call the public list_partitions() method
            # which internally opens the image
            
            # For now, we'll use a temporary approach: open the image via the strategy's
            # internal method (this will be refactored when FileSystemAccessor is implemented)
            if hasattr(strategy, '_open_image'):
                if not strategy._open_image(file_source):
                    print(f"[ERROR] Failed to open image: {primary_path}")
                    return []
            
            # Get partitions from the strategy
            partitions = []
            if hasattr(strategy, 'list_partitions'):
                partitions = strategy.list_partitions()
            
            # DETERMINISTIC STRUCTURAL IDENTIFICATION
            # If no partitions found, check if the image is a direct Volume acquisition
            if not partitions:
                synthetic_partition = self._probe_volume_filesystem(strategy)
                if synthetic_partition:
                    print(f"[INFO] Structural Identification: Valid Volume Image detected at offset 0.")
                    partitions = [synthetic_partition]
                else:
                    print(f"[WARNING] Structural Identification: No Partition Table or Filesystem Header found.")

            return partitions
        
        except Exception as e:
            error_classification = self.error_handler.classify_error(e, "Partition enumeration")
            print(f"[ERROR] {error_classification.user_message}")
            return []
    
    def get_image_info(self, file_source: Union[str, List[str]], format_name: str = None) -> Optional[ImageInfo]:
        """
        Get comprehensive information about a forensic image.
        
        This method combines format detection, partition enumeration, and metadata
        extraction into a single ImageInfo object.
        
        Args:
            file_source: Path to the forensic image file or list of paths for segments
            format_name: Optional format name for manual selection
            
        Returns:
            ImageInfo object with format, size, partitions, and metadata.
            Returns None if image cannot be opened.
        """
        primary_path = file_source[0] if isinstance(file_source, list) else file_source
        try:
            # Detect format (or use provided format_name)
            if format_name is None:
                detected_format = self.detect_format(file_source)
            else:
                detected_format = format_name.upper()
            
            # Check if format is supported
            if detected_format == self.FORMAT_UNKNOWN:
                print(f"[ERROR] Unknown image format: {primary_path}")
                return None
            
            # Get strategy
            strategy = self.get_strategy(file_source=file_source, format_name=detected_format)
            
            if strategy is None:
                print(f"[ERROR] No strategy available for format: {detected_format}")
                return None
            
            # Open the image
            if hasattr(strategy, '_open_image'):
                if not strategy._open_image(file_source):
                    print(f"[ERROR] Failed to open image: {primary_path}")
                    return None
            
            # Get image size
            size_bytes = 0
            if isinstance(file_source, list):
                size_bytes = sum(os.path.getsize(p) for p in file_source)
            else:
                size_bytes = os.path.getsize(file_source)
            
            # Get partitions
            partitions = self.list_partitions(file_source, detected_format)
            
            # Create ImageInfo object
            return ImageInfo(
                file_paths=file_source if isinstance(file_source, list) else [file_source],
                format=detected_format,
                size_bytes=size_bytes,
                partitions=partitions
            )
            
            return image_info
        
        except Exception as e:
            error_classification = self.error_handler.classify_error(e, "Image info retrieval")
            print(f"[ERROR] {error_classification.user_message}")
            return None
    
    def _generate_unsupported_format_error(self, file_path: str, detected_format: str) -> str:
        """
        Generate descriptive error message for unsupported formats.
        
        Args:
            file_path: Path to the unsupported file
            detected_format: Detected format name (or "UNKNOWN")
            
        Returns:
            Descriptive error message with actionable guidance
            
        Requirements:
        - 3.3: Unsupported formats SHALL return descriptive error messages
        """
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if detected_format == self.FORMAT_UNKNOWN:
            return (
                f"Unsupported forensic image format: {file_path}\n"
                f"File extension: {file_ext}\n"
                f"The file signature and extension do not match any supported format.\n\n"
                f"Supported formats:\n"
                f"- E01/Ex01 (Expert Witness Format) - .E01, .E02, etc.\n"
                f"- VHDX/VHD (Hyper-V Virtual Disk) - .vhdx, .vhd\n"
                f"- VMDK (VMware Virtual Disk) - .vmdk\n"
                f"- ISO (Optical Disc Image) - .iso\n"
                f"- Raw/DD (Bit-for-bit Copy) - .dd, .raw, .img, .001\n\n"
                f"Suggested actions:\n"
                f"- Verify the file is a valid forensic image\n"
                f"- Check if the file extension is correct\n"
                f"- Try manually selecting the format if you know the correct type\n"
                f"- Use forensic image verification tools to check integrity"
            )
        else:
            return (
                f"Cannot open forensic image: {file_path}\n"
                f"Detected format: {detected_format}\n"
                f"File extension: {file_ext}\n"
                f"The file appears to be {detected_format} format, but cannot be opened.\n\n"
                f"Suggested actions:\n"
                f"- Verify the file is not corrupted\n"
                f"- Check if required libraries are installed (dissect.target)\n"
                f"- Try using forensic image verification tools\n"
                f"- Check file permissions and accessibility"
            )
    
    def _probe_volume_filesystem(self, strategy) -> Optional[PartitionInfo]:
        """
        Probe the image container directly for a filesystem header (Volume-Only acquisition).
        
        Args:
            strategy: The access strategy providing img_info
            
        Returns:
            PartitionInfo if a filesystem is found at offset 0, None otherwise.
        """
        try:
            img_info = strategy.get_img_info()
            if not img_info:
                return None
            
            # Read first sector to identify filesystem
            img_info.seek(0)
            sector = img_info.read(512)
            
            # Determine size
            img_info.seek(0, 2)
            size = img_info.tell()
            img_info.seek(0)
            
            fs_type = "Unknown"
            description = "Raw Volume"
            
            # Check for common VBR signatures (NTFS, FAT32/16)
            if sector[3:7] == b'NTFS':
                fs_type = "NTFS"
                description = "Volume Acquisition (NTFS)"
            elif b'FAT32' in sector[82:90] or b'FAT16' in sector[54:62]:
                fs_type = "FAT"
                description = "Volume Acquisition (FAT)"
            elif sector[510:512] == b'\x55\xaa' and (b'EFI' in sector or b'BOOT' in sector):
                # Potentially a direct volume but let's be conservative
                fs_type = "Unknown (VBR-Signature Found)"
            else:
                return None
                
            return PartitionInfo(
                partition_number=0,
                start_offset=0,
                size_bytes=size,
                file_system_type=fs_type,
                description=description,
                is_bootable=False
            )
        except Exception as e:
            print(f"[DEBUG] Volume probing failed: {e}")
            return None

    def _find_sequential_segments(self, file_path: str) -> List[str]:
        """
        Automatically discover sequential segments of a split forensic image.
        Supports .001, .E01, .raw[0-9]+ naming conventions.
        
        Args:
            file_path: Path to one of the segment files
            
        Returns:
            Sorted list of all identified segment paths.
        """
        import re
        import glob
        
        directory = os.path.dirname(os.path.abspath(file_path))
        filename = os.path.basename(file_path)
        base, ext = os.path.splitext(filename)
        
        segments = []
        
        # Pattern 1: Split Raw (.001, .002, .003)
        if re.match(r'\.\d{3}$', ext):
            # Find the true base by stripping the .001 part
            # Often it's image.raw.001 or image.001
            # We look for all files sharing the same prefix before the numeric extension
            pattern = os.path.join(directory, base + ".[0-9][0-9][0-9]")
            segments = glob.glob(pattern)
            
        # Pattern 2: Multi-part EWF (.E01, .E02, .E03...)
        elif re.match(r'\.[Ee]\d{2}$', ext):
            prefix = ext[:2] # .E
            pattern = os.path.join(directory, base + prefix + "[0-9][0-9]")
            segments = glob.glob(pattern)
            
        # Pattern 3: .raw.01, .raw.02 and variations
        elif re.match(r'\.\d{2}$', ext):
            pattern = os.path.join(directory, base + ".[0-9][0-9]")
            segments = glob.glob(pattern)
            
        if not segments:
            return [file_path]
            
        # Ensure they are sorted naturally
        segments.sort()
        
        # Check for missing segments
        self._check_for_missing_segments(segments)
        
        return segments

    def _check_for_missing_segments(self, sorted_segments: List[str]):
        """Alert the user if there are gaps in the sequential sequence."""
        if len(sorted_segments) < 2:
            return

        def get_seq_num(path):
            match = re.search(r'\d+$', path)
            return int(match.group()) if match else None

        seq_nums = [get_seq_num(s) for s in sorted_segments]
        seq_nums = [s for s in seq_nums if s is not None]
        
        if not seq_nums: return
        
        # Check for gaps
        expected = range(min(seq_nums), max(seq_nums) + 1)
        missing = set(expected) - set(seq_nums)
        
        if missing:
            print(f"[WARNING] Detected missing segments in forensic image sequence: {missing}")

    def get_supported_formats(self) -> List[str]:
        """
        Get list of supported forensic image formats.
        
        Returns:
            List of format names: ["E01", "VHDX", "VMDK", "ISO", "RAW"]
        """
        return list(self.format_strategy_map.keys())
    
    def is_format_supported(self, format_name: str) -> bool:
        """
        Check if a format is supported.
        
        Args:
            format_name: Format name to check (case-insensitive)
            
        Returns:
            True if format is supported, False otherwise
        """
        return format_name.upper() in self.format_strategy_map
