"""
Windows Partition Detector for Crow Eye Forensic Analysis Tool
================================================================

This module provides functionality to detect Windows installations on any partition,
supporting both live system analysis and offline disk image analysis.

Key Features:
- Automatic detection of Windows partition on live systems
- Scanning for Windows installations on offline disk images
- Verification of Windows installations by checking critical system files
- Support for multiple Windows installations with user selection
- Comprehensive error handling and logging

Author: Crow Eye Team
License: GPL-3.0
"""

import os
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PartitionDetector] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class WindowsDetectionResult:
    """Result of Windows partition detection."""
    partition_letter: str  # e.g., "D:"
    partition_path: str    # e.g., "D:\\"
    windows_version: str   # e.g., "Windows 10"
    system_root: str       # e.g., "D:\\Windows"
    detection_method: str  # "environment_variable" or "filesystem_scan"
    confidence: str        # "high", "medium", "low"
    verification_files: List[str]  # Files found to verify Windows installation


class WindowsPartitionDetector:
    """
    Detects Windows partition on live systems and offline disk images.
    
    This class provides methods to automatically detect which partition contains
    the Windows installation, supporting both live analysis and offline forensic
    analysis of disk images.
    """
    
    # Critical Windows system files used for verification
    CRITICAL_SYSTEM_FILES = [
        "Windows\\System32\\ntoskrnl.exe",
        "Windows\\System32\\kernel32.dll",
        "Windows\\System32\\ntdll.dll",
        "Windows\\System32\\config\\SYSTEM",
        "Windows\\System32\\config\\SOFTWARE"
    ]
    
    # Minimum number of critical files that must exist for verification
    MIN_VERIFICATION_FILES = 3
    
    def __init__(self):
        """Initialize the Windows Partition Detector."""
        self.detected_partitions: List[WindowsDetectionResult] = []
        logger.info("Windows Partition Detector initialized")
    
    def detect_live_system(self) -> str:
        """
        Detect Windows partition on live system using environment variables.
        
        This method queries the SystemRoot environment variable to determine
        which partition contains the Windows installation on a running system.
        
        Returns:
            str: Windows partition letter (e.g., "C:")
            
        Raises:
            RuntimeError: If SystemRoot environment variable is not set
            ValueError: If partition letter cannot be extracted
        """
        logger.info("Detecting Windows partition on live system...")
        
        try:
            # Get SystemRoot environment variable (e.g., "C:\Windows")
            system_root = os.getenv('SystemRoot')
            
            if not system_root:
                raise RuntimeError(
                    "SystemRoot environment variable is not set. "
                    "This may not be a Windows system or environment is corrupted."
                )
            
            # Extract partition letter (first character before colon)
            if ':' not in system_root:
                raise ValueError(
                    f"Invalid SystemRoot format: {system_root}. "
                    "Expected format like 'C:\\Windows'"
                )
            
            partition_letter = system_root.split(':')[0] + ':'
            partition_path = partition_letter + '\\'
            
            logger.info(f"Detected Windows partition: {partition_letter}")
            logger.info(f"SystemRoot: {system_root}")
            
            # Verify the installation
            if self.verify_windows_installation(partition_path):
                # Get Windows version
                windows_version = self._detect_windows_version(partition_path)
                
                # Create detection result
                result = WindowsDetectionResult(
                    partition_letter=partition_letter,
                    partition_path=partition_path,
                    windows_version=windows_version,
                    system_root=system_root,
                    detection_method="environment_variable",
                    confidence="high",
                    verification_files=self._get_found_verification_files(partition_path)
                )
                
                self.detected_partitions.append(result)
                logger.info(f"Windows installation verified on {partition_letter}")
                
                return partition_letter
            else:
                logger.warning(
                    f"SystemRoot points to {partition_letter}, but verification failed. "
                    "Windows installation may be corrupted."
                )
                return partition_letter  # Return anyway, but log warning
                
        except Exception as e:
            logger.error(f"Error detecting Windows partition on live system: {e}")
            raise
    
    def detect_offline_system(self, mounted_partitions: Optional[List[str]] = None) -> List[str]:
        """
        Detect Windows installations on offline disk images.
        
        This method scans mounted partitions for Windows directory structures
        and verifies installations by checking for critical system files.
        
        Args:
            mounted_partitions: List of mounted partition paths (e.g., ["D:\\", "E:\\"])
                               If None, will scan all available drive letters
            
        Returns:
            List[str]: List of partition letters containing Windows installations
        """
        logger.info("Detecting Windows installations on offline disk images...")
        
        windows_partitions = []
        
        # If no partitions specified, scan all drive letters
        if mounted_partitions is None:
            mounted_partitions = self._get_all_drive_letters()
            logger.info(f"Scanning all available drives: {mounted_partitions}")
        else:
            logger.info(f"Scanning specified partitions: {mounted_partitions}")
        
        # Scan each partition
        for partition_path in mounted_partitions:
            # Ensure partition path ends with backslash
            if not partition_path.endswith('\\'):
                partition_path += '\\'
            
            # Extract partition letter
            partition_letter = partition_path.rstrip('\\').split(':')[0] + ':'
            
            logger.debug(f"Checking partition: {partition_path}")
            
            # Check if Windows directory exists
            windows_dir = os.path.join(partition_path, "Windows")
            system32_dir = os.path.join(windows_dir, "System32")
            
            if os.path.exists(windows_dir) and os.path.exists(system32_dir):
                logger.info(f"Found Windows directory structure on {partition_letter}")
                
                # Verify the installation
                if self.verify_windows_installation(partition_path):
                    windows_version = self._detect_windows_version(partition_path)
                    
                    result = WindowsDetectionResult(
                        partition_letter=partition_letter,
                        partition_path=partition_path,
                        windows_version=windows_version,
                        system_root=os.path.join(partition_path, "Windows"),
                        detection_method="filesystem_scan",
                        confidence="high",
                        verification_files=self._get_found_verification_files(partition_path)
                    )
                    
                    self.detected_partitions.append(result)
                    windows_partitions.append(partition_letter)
                    logger.info(f"Verified Windows installation on {partition_letter}")
                else:
                    logger.warning(
                        f"Windows directory found on {partition_letter}, "
                        "but verification failed (insufficient critical files)"
                    )
        
        if not windows_partitions:
            logger.warning("No Windows installations found on any partition")
        else:
            logger.info(f"Found {len(windows_partitions)} Windows installation(s): {windows_partitions}")
        
        return windows_partitions
    
    def verify_windows_installation(self, partition_path: str) -> bool:
        """
        Verify that a partition contains a valid Windows installation.
        
        This method checks for the presence of critical Windows system files
        to confirm that the partition contains a legitimate Windows installation.
        
        Args:
            partition_path: Path to partition root (e.g., "D:\\")
            
        Returns:
            bool: True if valid Windows installation found, False otherwise
        """
        logger.debug(f"Verifying Windows installation on {partition_path}")
        
        # Ensure partition path ends with backslash
        if not partition_path.endswith('\\'):
            partition_path += '\\'
        
        found_files = 0
        missing_files = []
        
        # Check for critical system files
        for file_path in self.CRITICAL_SYSTEM_FILES:
            full_path = os.path.join(partition_path, file_path)
            
            if os.path.exists(full_path):
                found_files += 1
                logger.debug(f"  ✓ Found: {file_path}")
            else:
                missing_files.append(file_path)
                logger.debug(f"  ✗ Missing: {file_path}")
        
        # Verify minimum number of critical files exist
        is_valid = found_files >= self.MIN_VERIFICATION_FILES
        
        if is_valid:
            logger.info(
                f"Verification passed: {found_files}/{len(self.CRITICAL_SYSTEM_FILES)} "
                f"critical files found on {partition_path}"
            )
        else:
            logger.warning(
                f"Verification failed: Only {found_files}/{len(self.CRITICAL_SYSTEM_FILES)} "
                f"critical files found on {partition_path} "
                f"(minimum required: {self.MIN_VERIFICATION_FILES})"
            )
            logger.debug(f"Missing files: {missing_files}")
        
        return is_valid
    
    def prompt_user_selection(self, windows_partitions: List[str]) -> str:
        """
        Prompt user to select Windows partition when multiple found.
        
        This method displays information about detected Windows installations
        and prompts the user to select which one to analyze.
        
        Args:
            windows_partitions: List of partition letters with Windows
            
        Returns:
            str: Selected partition letter
        """
        if not windows_partitions:
            raise ValueError("No Windows partitions provided for selection")
        
        if len(windows_partitions) == 1:
            logger.info(f"Only one Windows installation found: {windows_partitions[0]}")
            return windows_partitions[0]
        
        logger.info(f"Multiple Windows installations detected: {windows_partitions}")
        
        print("\n" + "="*70)
        print("MULTIPLE WINDOWS INSTALLATIONS DETECTED")
        print("="*70)
        print("\nThe following Windows installations were found:\n")
        
        # Display information about each installation
        for idx, partition_letter in enumerate(windows_partitions, 1):
            # Find the detection result for this partition
            result = next(
                (r for r in self.detected_partitions if r.partition_letter == partition_letter),
                None
            )
            
            print(f"{idx}. Partition {partition_letter}")
            if result:
                print(f"   Windows Version: {result.windows_version}")
                print(f"   System Root: {result.system_root}")
                print(f"   Confidence: {result.confidence}")
                print(f"   Verified Files: {len(result.verification_files)}")
            print()
        
        # Prompt for selection
        while True:
            try:
                selection = input(f"Select Windows installation to analyze (1-{len(windows_partitions)}): ")
                selection_idx = int(selection) - 1
                
                if 0 <= selection_idx < len(windows_partitions):
                    selected_partition = windows_partitions[selection_idx]
                    logger.info(f"User selected partition: {selected_partition}")
                    print(f"\nSelected: {selected_partition}")
                    print("="*70 + "\n")
                    return selected_partition
                else:
                    print(f"Invalid selection. Please enter a number between 1 and {len(windows_partitions)}")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\n\nSelection cancelled by user.")
                logger.warning("User cancelled partition selection")
                # Default to first partition
                default_partition = windows_partitions[0]
                logger.info(f"Defaulting to first partition: {default_partition}")
                return default_partition
    
    def _get_all_drive_letters(self) -> List[str]:
        """
        Get all available drive letters on the system.
        
        Returns:
            List[str]: List of drive paths (e.g., ["C:\\", "D:\\", "E:\\"])
        """
        import string
        drives = []
        
        for letter in string.ascii_uppercase:
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                drives.append(drive_path)
        
        return drives
    
    def _detect_windows_version(self, partition_path: str) -> str:
        """
        Detect Windows version from partition.
        
        Args:
            partition_path: Path to partition root
            
        Returns:
            str: Windows version string (e.g., "Windows 10")
        """
        # Try to read version from registry or system files
        # For now, return generic version
        # TODO: Implement actual version detection from registry or system files
        
        version_file = os.path.join(partition_path, "Windows", "System32", "ntoskrnl.exe")
        if os.path.exists(version_file):
            try:
                # Get file size as a rough indicator
                file_size = os.path.getsize(version_file)
                
                # Very rough heuristic based on file size
                if file_size > 10_000_000:
                    return "Windows 10/11"
                elif file_size > 7_000_000:
                    return "Windows 8/8.1"
                elif file_size > 5_000_000:
                    return "Windows 7"
                else:
                    return "Windows Vista or earlier"
            except:
                pass
        
        return "Windows (version unknown)"
    
    def _get_found_verification_files(self, partition_path: str) -> List[str]:
        """
        Get list of verification files that were found.
        
        Args:
            partition_path: Path to partition root
            
        Returns:
            List[str]: List of found verification file paths
        """
        if not partition_path.endswith('\\'):
            partition_path += '\\'
        
        found_files = []
        
        for file_path in self.CRITICAL_SYSTEM_FILES:
            full_path = os.path.join(partition_path, file_path)
            if os.path.exists(full_path):
                found_files.append(file_path)
        
        return found_files
    
    def get_detection_results(self) -> List[WindowsDetectionResult]:
        """
        Get all detection results.
        
        Returns:
            List[WindowsDetectionResult]: List of all detected Windows installations
        """
        return self.detected_partitions


# Convenience functions for easy use
def detect_windows_partition_live() -> str:
    """
    Detect Windows partition on live system.
    
    Returns:
        str: Windows partition letter (e.g., "C:")
    """
    detector = WindowsPartitionDetector()
    return detector.detect_live_system()


def detect_windows_partition_offline(mounted_partitions: Optional[List[str]] = None) -> List[str]:
    """
    Detect Windows installations on offline disk images.
    
    Args:
        mounted_partitions: List of mounted partition paths
        
    Returns:
        List[str]: List of partition letters containing Windows installations
    """
    detector = WindowsPartitionDetector()
    return detector.detect_offline_system(mounted_partitions)


if __name__ == "__main__":
    # Test the detector
    print("Windows Partition Detector - Test Mode")
    print("="*70)
    
    detector = WindowsPartitionDetector()
    
    # Try live detection
    try:
        print("\n1. Testing live system detection...")
        live_partition = detector.detect_live_system()
        print(f"   Result: {live_partition}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Try offline detection
    print("\n2. Testing offline system detection...")
    offline_partitions = detector.detect_offline_system()
    print(f"   Found {len(offline_partitions)} Windows installation(s)")
    
    if len(offline_partitions) > 1:
        print("\n3. Testing user selection...")
        selected = detector.prompt_user_selection(offline_partitions)
        print(f"   Selected: {selected}")
    
    print("\n" + "="*70)
    print("Test complete")
