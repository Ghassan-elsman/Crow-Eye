"""
Path Resolver

Utility for resolving and validating file paths in configurations.
Handles both Windows and Unix paths, relative and absolute paths.
"""

import os
from pathlib import Path
from typing import Optional, Union


class PathResolver:
    """
    Utility for resolving and validating configuration file paths.
    Handles cross-platform path resolution.
    """
    
    def __init__(self, base_directory: Path):
        """
        Initialize path resolver with base directory.
        
        Args:
            base_directory: Base directory for resolving relative paths
        """
        self.base_directory = Path(base_directory).resolve()
    
    def resolve_relative_path(self, path: Union[str, Path], 
                             relative_to: Optional[Path] = None) -> Path:
        """
        Resolve a relative path to an absolute path.
        
        Args:
            path: Path to resolve (can be relative or absolute)
            relative_to: Optional base path (defaults to base_directory)
        
        Returns:
            Resolved absolute Path
        """
        path_obj = Path(path)
        
        # If already absolute, return as-is
        if path_obj.is_absolute():
            return path_obj.resolve()
        
        # Resolve relative to specified directory or base directory
        base = Path(relative_to).resolve() if relative_to else self.base_directory
        return (base / path_obj).resolve()
    
    def make_relative_path(self, path: Union[str, Path], 
                          relative_to: Optional[Path] = None) -> Path:
        """
        Convert an absolute path to a relative path.
        
        Args:
            path: Absolute path to convert
            relative_to: Optional base path (defaults to base_directory)
        
        Returns:
            Relative Path
        """
        path_obj = Path(path).resolve()
        base = Path(relative_to).resolve() if relative_to else self.base_directory
        
        try:
            return path_obj.relative_to(base)
        except ValueError:
            # Paths are on different drives or not related
            return path_obj
    
    def validate_path(self, path: Union[str, Path], 
                     must_exist: bool = False,
                     must_be_file: bool = False,
                     must_be_dir: bool = False) -> tuple[bool, Optional[str]]:
        """
        Validate a path.
        
        Args:
            path: Path to validate
            must_exist: If True, path must exist
            must_be_file: If True, path must be a file
            must_be_dir: If True, path must be a directory
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            path_obj = Path(path)
            
            # Check if path exists
            if must_exist and not path_obj.exists():
                return False, f"Path does not exist: {path}"
            
            # Check if it's a file
            if must_be_file and path_obj.exists() and not path_obj.is_file():
                return False, f"Path is not a file: {path}"
            
            # Check if it's a directory
            if must_be_dir and path_obj.exists() and not path_obj.is_dir():
                return False, f"Path is not a directory: {path}"
            
            return True, None
            
        except Exception as e:
            return False, f"Invalid path: {str(e)}"
    
    def normalize_path(self, path: Union[str, Path]) -> str:
        """
        Normalize a path to use forward slashes (cross-platform).
        
        Args:
            path: Path to normalize
        
        Returns:
            Normalized path string
        """
        return str(Path(path)).replace('\\', '/')
    
    def ensure_directory_exists(self, path: Union[str, Path]) -> bool:
        """
        Ensure a directory exists, creating it if necessary.
        
        Args:
            path: Directory path
        
        Returns:
            True if directory exists or was created, False on error
        """
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"Failed to create directory {path}: {e}")
            return False
    
    def get_file_extension(self, path: Union[str, Path]) -> str:
        """
        Get file extension from path.
        
        Args:
            path: File path
        
        Returns:
            File extension (including dot) or empty string
        """
        return Path(path).suffix
    
    def change_extension(self, path: Union[str, Path], new_extension: str) -> Path:
        """
        Change file extension.
        
        Args:
            path: File path
            new_extension: New extension (with or without dot)
        
        Returns:
            Path with new extension
        """
        path_obj = Path(path)
        if not new_extension.startswith('.'):
            new_extension = '.' + new_extension
        return path_obj.with_suffix(new_extension)
    
    def join_paths(self, *paths: Union[str, Path]) -> Path:
        """
        Join multiple path components.
        
        Args:
            *paths: Path components to join
        
        Returns:
            Joined Path
        """
        result = Path(paths[0])
        for path in paths[1:]:
            result = result / path
        return result
    
    def get_relative_config_path(self, config_path: Union[str, Path],
                                 config_type: str) -> Path:
        """
        Get relative path for a configuration file within the case structure.
        
        Args:
            config_path: Configuration file path
            config_type: Type of configuration ("pipeline", "feather", "wing")
        
        Returns:
            Relative path from base directory
        """
        path_obj = Path(config_path)
        
        # If already relative, return as-is
        if not path_obj.is_absolute():
            return path_obj
        
        # Try to make relative to base directory
        try:
            return path_obj.relative_to(self.base_directory)
        except ValueError:
            # If not under base directory, return filename only
            return Path(f"{config_type}s") / path_obj.name
    
    def resolve_config_reference(self, reference: str, config_type: str) -> Path:
        """
        Resolve a configuration reference to an absolute path.
        Handles both relative paths and just filenames.
        
        Args:
            reference: Configuration reference (path or filename)
            config_type: Type of configuration ("pipeline", "feather", "wing")
        
        Returns:
            Resolved absolute Path
        """
        ref_path = Path(reference)
        
        # If absolute, return as-is
        if ref_path.is_absolute():
            return ref_path.resolve()
        
        # If it's just a filename (no directory), look in standard location
        if len(ref_path.parts) == 1:
            standard_dir = self.base_directory / f"{config_type}s"
            return (standard_dir / reference).resolve()
        
        # Otherwise, resolve relative to base directory
        return (self.base_directory / ref_path).resolve()
    
    def is_under_base_directory(self, path: Union[str, Path]) -> bool:
        """
        Check if a path is under the base directory.
        
        Args:
            path: Path to check
        
        Returns:
            True if path is under base directory
        """
        try:
            path_obj = Path(path).resolve()
            path_obj.relative_to(self.base_directory)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def is_windows_path(path: str) -> bool:
        """
        Check if a path string is a Windows path.
        
        Args:
            path: Path string
        
        Returns:
            True if Windows path format
        """
        return '\\' in path or (len(path) > 1 and path[1] == ':')
    
    @staticmethod
    def is_unix_path(path: str) -> bool:
        """
        Check if a path string is a Unix path.
        
        Args:
            path: Path string
        
        Returns:
            True if Unix path format
        """
        return path.startswith('/') and '\\' not in path
    
    @staticmethod
    def convert_to_platform_path(path: str) -> str:
        """
        Convert path to current platform format.
        
        Args:
            path: Path string
        
        Returns:
            Platform-appropriate path string
        """
        return str(Path(path))
