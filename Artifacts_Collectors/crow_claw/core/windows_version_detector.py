"""
Windows Version Detection
=========================

Detects Windows version and adjusts artifact paths based on version-specific locations.

Requirements: 8.2, 8.4
"""

import platform
from enum import Enum
from typing import Optional


class WindowsVersion(Enum):
    """Windows version enumeration."""
    WINDOWS_7 = "7"
    WINDOWS_8 = "8"
    WINDOWS_8_1 = "8.1"
    WINDOWS_10 = "10"
    WINDOWS_11 = "11"
    UNKNOWN = "unknown"


class WindowsVersionDetector:
    """
    Detects Windows version and adjusts artifact paths.
    
    Uses platform module to detect Windows version and provides
    version-specific path adjustments for artifacts.
    """

    def __init__(self):
        """Initialize the detector."""
        self._detected_version: Optional[WindowsVersion] = None

    def detect_version(self) -> WindowsVersion:
        """
        Detect Windows version.
        
        Returns:
            WindowsVersion enum value
        """
        if self._detected_version:
            return self._detected_version

        try:
            # Get version information
            version_str = platform.version()
            release = platform.release()
            
            # Parse version string
            # Windows version format: major.minor.build
            # Windows 11: 10.0.22000+
            # Windows 10: 10.0.10240+
            # Windows 8.1: 6.3
            # Windows 8: 6.2
            # Windows 7: 6.1
            
            if release == "10" or release == "11":
                # Need to check build number for Windows 11
                build_number = self._extract_build_number(version_str)
                if build_number >= 22000:
                    self._detected_version = WindowsVersion.WINDOWS_11
                else:
                    self._detected_version = WindowsVersion.WINDOWS_10
            elif release == "8.1":
                self._detected_version = WindowsVersion.WINDOWS_8_1
            elif release == "8":
                self._detected_version = WindowsVersion.WINDOWS_8
            elif release == "7":
                self._detected_version = WindowsVersion.WINDOWS_7
            else:
                self._detected_version = WindowsVersion.UNKNOWN
                
        except Exception:
            self._detected_version = WindowsVersion.UNKNOWN
        
        return self._detected_version

    def _extract_build_number(self, version_str: str) -> int:
        """
        Extract build number from version string.
        
        Args:
            version_str: Version string from platform.version()
            
        Returns:
            Build number as integer, or 0 if not found
        """
        try:
            # Version string format: "10.0.22000" or similar
            parts = version_str.split('.')
            if len(parts) >= 3:
                return int(parts[2])
        except (ValueError, IndexError):
            pass
        return 0

    def adjust_artifact_paths(self, artifact, version: Optional[WindowsVersion] = None) -> tuple:
        """
        Adjust artifact paths based on Windows version.
        
        Args:
            artifact: Artifact object with paths to adjust
            version: Windows version (if None, will detect)
            
        Returns:
            Tuple of (adjusted_artifact, informational_messages)
        """
        if version is None:
            version = self.detect_version()
        
        informational_messages = []
        
        # Version-specific path adjustments
        # Most artifacts are consistent across versions, but some have differences
        
        # Example: Event log locations changed between versions
        # Windows 7: C:\Windows\System32\winevt\Logs\
        # Windows 8+: Same location but different default logs
        
        # For now, we'll handle artifacts that don't exist on specific versions
        if version == WindowsVersion.WINDOWS_7:
            # Windows 7 doesn't have some modern artifacts
            if hasattr(artifact, 'artifact_type'):
                artifact_type = artifact.artifact_type.value if hasattr(artifact.artifact_type, 'value') else str(artifact.artifact_type)
                
                # Check for artifacts that don't exist on Windows 7
                if artifact_type in ['ActivitiesCache', 'Timeline']:
                    informational_messages.append(
                        f"Artifact '{artifact.name}' does not exist on Windows 7"
                    )
        
        return artifact, informational_messages

    def get_version_string(self, version: Optional[WindowsVersion] = None) -> str:
        """
        Get human-readable version string.
        
        Args:
            version: Windows version (if None, will detect)
            
        Returns:
            Version string like "Windows 10" or "Windows 11"
        """
        if version is None:
            version = self.detect_version()
        
        if version == WindowsVersion.UNKNOWN:
            return "Unknown Windows Version"
        
        return f"Windows {version.value}"

    def get_version_info(self) -> dict:
        """
        Get detailed version information.
        
        Returns:
            Dictionary with version details
        """
        version = self.detect_version()
        
        return {
            "version": version.value,
            "version_string": self.get_version_string(version),
            "platform_version": platform.version(),
            "platform_release": platform.release(),
            "platform_system": platform.system(),
            "platform_machine": platform.machine()
        }
