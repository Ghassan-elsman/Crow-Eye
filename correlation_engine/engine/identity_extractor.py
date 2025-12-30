"""
Identity extractor for normalizing values and generating identity keys.

This module provides normalization and identity key generation for the Crow-Eye
Correlation Engine, ensuring consistent identity representation across artifacts.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class IdentityExtractor:
    """
    Normalize values and generate identity keys.
    
    Handles:
    - Name normalization (lowercase)
    - Path normalization (lowercase, standard separators)
    - Filename extraction from paths
    - Identity key generation (type:normalized_value)
    """
    
    def __init__(self):
        """Initialize identity extractor."""
        logger.info("IdentityExtractor initialized")
    
    def normalize_name(self, name: str) -> Optional[str]:
        """
        Normalize a file name to lowercase.
        
        Args:
            name: File name to normalize
            
        Returns:
            Normalized name or None if invalid
        """
        if not name or not isinstance(name, str):
            return None
        
        name = name.strip()
        
        if not name:
            return None
        
        # Convert to lowercase for case-insensitive matching
        normalized = name.lower()
        
        logger.debug(f"Normalized name: '{name}' -> '{normalized}'")
        return normalized
    
    def normalize_path(self, path: str) -> Optional[str]:
        """
        Normalize a Windows path (lowercase, standard separators).
        
        Args:
            path: File path to normalize
            
        Returns:
            Normalized path or None if invalid
        """
        if not path or not isinstance(path, str):
            return None
        
        path = path.strip()
        
        if not path:
            return None
        
        # Convert to lowercase
        normalized = path.lower()
        
        # Standardize path separators to forward slashes
        normalized = normalized.replace('\\', '/')
        
        # Remove duplicate slashes
        while '//' in normalized:
            normalized = normalized.replace('//', '/')
        
        logger.debug(f"Normalized path: '{path}' -> '{normalized}'")
        return normalized
    
    def extract_filename_from_path(self, path: str) -> Optional[str]:
        """
        Extract filename from a full path.
        
        Uses the last component after the final path separator.
        
        Args:
            path: Full file path
            
        Returns:
            Extracted filename or None if invalid
        """
        if not path or not isinstance(path, str):
            return None
        
        path = path.strip()
        
        if not path:
            return None
        
        # Normalize path separators first
        normalized_path = path.replace('\\', '/')
        
        # Get last component
        filename = normalized_path.split('/')[-1]
        
        if not filename:
            logger.warning(f"Could not extract filename from path: '{path}'")
            return None
        
        # Normalize the filename
        filename = self.normalize_name(filename)
        
        logger.debug(f"Extracted filename from path: '{path}' -> '{filename}'")
        return filename
    
    def generate_identity_key(self, identity_type: str, value: str) -> Optional[str]:
        """
        Generate identity key in format: type:normalized_value
        
        Args:
            identity_type: Type of identity ("name", "path", "hash")
            value: Identity value (should already be normalized)
            
        Returns:
            Identity key or None if invalid
        """
        if not identity_type or not value:
            return None
        
        # Validate identity type
        valid_types = ["name", "path", "hash"]
        if identity_type not in valid_types:
            logger.warning(f"Invalid identity type: '{identity_type}'. Must be one of {valid_types}")
            return None
        
        # Generate key
        key = f"{identity_type}:{value}"
        
        logger.debug(f"Generated identity key: '{key}'")
        return key
    
    def extract_identities_from_name(self, name: str) -> list:
        """
        Extract identity keys from a name value.
        
        Args:
            name: Name value
            
        Returns:
            List of (identity_type, normalized_value) tuples
        """
        identities = []
        
        normalized = self.normalize_name(name)
        if normalized:
            identities.append(("name", normalized))
        
        return identities
    
    def extract_identities_from_path(self, path: str, extract_name: bool = False) -> list:
        """
        Extract identity keys from a path value.
        
        Args:
            path: Path value
            extract_name: If True, also extract filename from path
            
        Returns:
            List of (identity_type, normalized_value) tuples
        """
        identities = []
        
        # Add path identity
        normalized_path = self.normalize_path(path)
        if normalized_path:
            identities.append(("path", normalized_path))
        
        # Optionally extract filename
        if extract_name:
            filename = self.extract_filename_from_path(path)
            if filename:
                identities.append(("name", filename))
        
        return identities
    
    def handle_empty_value(self, value: str, value_type: str) -> bool:
        """
        Check if value is empty and log warning.
        
        Args:
            value: Value to check
            value_type: Type of value (for logging)
            
        Returns:
            True if empty, False otherwise
        """
        if not value or not value.strip():
            logger.warning(f"Empty {value_type} value encountered")
            return True
        return False
    
    def handle_path_without_extension(self, path: str) -> str:
        """
        Handle paths without file extensions.
        
        Args:
            path: File path
            
        Returns:
            Path (unchanged, but logged if no extension)
        """
        if not path:
            return path
        
        filename = os.path.basename(path)
        if '.' not in filename:
            logger.debug(f"Path has no extension: '{path}'")
        
        return path
    
    def handle_mixed_separators(self, path: str) -> str:
        """
        Handle paths with mixed separators.
        
        Args:
            path: File path with potentially mixed separators
            
        Returns:
            Path with standardized separators
        """
        if not path:
            return path
        
        # Check if path has mixed separators
        has_forward = '/' in path
        has_backward = '\\' in path
        
        if has_forward and has_backward:
            logger.debug(f"Path has mixed separators: '{path}'")
        
        # Normalize to forward slashes
        return path.replace('\\', '/')


# Convenience functions

def normalize_name(name: str) -> Optional[str]:
    """Convenience function to normalize a name."""
    extractor = IdentityExtractor()
    return extractor.normalize_name(name)


def normalize_path(path: str) -> Optional[str]:
    """Convenience function to normalize a path."""
    extractor = IdentityExtractor()
    return extractor.normalize_path(path)


def extract_filename(path: str) -> Optional[str]:
    """Convenience function to extract filename from path."""
    extractor = IdentityExtractor()
    return extractor.extract_filename_from_path(path)


def generate_identity_key(identity_type: str, value: str) -> Optional[str]:
    """Convenience function to generate identity key."""
    extractor = IdentityExtractor()
    return extractor.generate_identity_key(identity_type, value)
