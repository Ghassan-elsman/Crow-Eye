"""
File access strategy pattern implementation.

This module defines the abstract base class for file access strategies
and provides a framework for implementing different access methods
(standard copy, VSS, raw disk access).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .access_result import AccessResult


class FileAccessStrategy(ABC):
    """Abstract base class for file access strategies.
    
    Defines the interface that all file access strategies must implement.
    Strategies include standard file copy, VSS access, and raw disk access.
    """
    
    @abstractmethod
    def can_handle(self, file_path: str, artifact_type: str) -> bool:
        """Check if this strategy can handle the given file.
        
        Args:
            file_path: Path to the file to access
            artifact_type: Type of artifact (e.g., "registry_hives", "mft")
            
        Returns:
            True if this strategy can attempt to access the file
        """
        pass
    
    @abstractmethod
    def access_file(self, file_path: str, dest_path: str) -> 'AccessResult':
        """Attempt to access and copy the file.
        
        Args:
            file_path: Source file path
            dest_path: Destination file path
            
        Returns:
            AccessResult containing success status, errors, and metadata
        """
        pass
    
    @abstractmethod
    def requires_admin(self) -> bool:
        """Check if this strategy requires administrator privileges.
        
        Returns:
            True if admin privileges are required
        """
        pass
