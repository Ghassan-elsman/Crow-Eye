"""
Path Validation Module
======================

Path validation logic for artifact collection.
Checks path existence, accessibility, and Windows partition detection.

Phase 1: Core Data Model - Validation Logic
"""

import os
import ctypes
import subprocess
from typing import List, Tuple, Optional
from pathlib import Path


class PathValidator:
    """Validates and checks artifacts paths."""

    @staticmethod
    def is_valid_path(path: str) -> bool:
        """
        Check if a path exists and is accessible.

        Args:
            path: Path to validate

        Returns:
            True if path exists and is accessible
        """
        try:
            expanded = os.path.expandvars(path)
            return os.path.exists(expanded)
        except (OSError, ValueError):
            return False

    @staticmethod
    def is_readable(path: str) -> bool:
        """
        Check if a path is readable.

        Args:
            path: Path to check

        Returns:
            True if path is readable
        """
        try:
            expanded = os.path.expandvars(path)
            return os.access(expanded, os.R_OK)
        except (OSError, ValueError):
            return False

    @staticmethod
    def is_writable(path: str) -> bool:
        """
        Check if a path is writable.

        Args:
            path: Path to check

        Returns:
            True if path is writable
        """
        try:
            expanded = os.path.expandvars(path)
            return os.access(expanded, os.W_OK)
        except (OSError, ValueError):
            return False

    @staticmethod
    def get_path_info(path: str) -> Optional[dict]:
        """
        Get detailed information about a path.

        Args:
            path: Path to get info for

        Returns:
            Dictionary with path info or None if invalid
        """
        try:
            expanded = os.path.expandvars(path)
            if not os.path.exists(expanded):
                return None

            stat_info = os.stat(expanded)
            path_obj = Path(expanded)

            return {
                "path": path,
                "expanded_path": expanded,
                "exists": True,
                "is_file": path_obj.is_file(),
                "is_dir": path_obj.is_dir(),
                "size": stat_info.st_size,
                "readable": os.access(expanded, os.R_OK),
                "writable": os.access(expanded, os.W_OK),
                "created": stat_info.st_ctime,
                "modified": stat_info.st_mtime,
                "accessed": stat_info.st_atime,
            }
        except (OSError, ValueError):
            return None

    @staticmethod
    def get_windows_partitions() -> List[str]:
        """
        Detect available Windows partitions.

        Returns:
            List of drive letters (e.g., ['C:', 'D:', 'E:'])
        """
        partitions = []
        if os.name == 'nt':
            try:
                # Try Windows-specific method
                import ctypes
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for i in range(26):
                    if bitmask & (1 << i):
                        drive = f"{chr(65 + i)}:"
                        partitions.append(drive)
            except (AttributeError, OSError):
                # Fallback for Windows
                for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                    drive = f"{letter}:"
                    if os.path.exists(drive + "\\"):
                        partitions.append(drive)
        else:
            # Linux/macOS fallback using root and mounts
            try:
                import psutil
                for part in psutil.disk_partitions(all=False):
                    if part.mountpoint:
                        partitions.append(part.mountpoint)
            except ImportError:
                partitions.append("/")

        return sorted(list(set(partitions)))

    @staticmethod
    def is_admin() -> bool:
        """
        Check if running with administrator privileges.

        Returns:
            True if running as admin
        """
        if os.name == 'nt':
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except (AttributeError, OSError):
                return False
        else:
            try:
                return getattr(os, 'getuid', lambda: 1)() == 0
            except (AttributeError, OSError):
                return False

    @staticmethod
    def get_admin_status_string() -> str:
        """
        Get human-readable admin status.

        Returns:
            String describing admin status
        """
        if PathValidator.is_admin():
            return "Admin privileges: YES [OK]"
        else:
            return "Admin privileges: NO [WARNING] (Some artifacts may not be collectable)"

    @staticmethod
    def get_disk_space(path: str) -> Optional[dict]:
        """
        Get disk space information for a path.

        Args:
            path: Path to check

        Returns:
            Dictionary with space info or None
        """
        try:
            expanded = os.path.expandvars(path)
            stat = os.statvfs(expanded) if hasattr(os, 'statvfs') else None

            if stat:
                return {
                    "path": path,
                    "total": stat.f_blocks * stat.f_frsize,
                    "free": stat.f_bavail * stat.f_frsize,
                    "used": (stat.f_blocks - stat.f_bavail) * stat.f_frsize,
                }
            else:
                # Windows fallback using shutil
                import shutil
                total, used, free = shutil.disk_usage(expanded)
                return {
                    "path": path,
                    "total": total,
                    "free": free,
                    "used": used,
                }
        except (OSError, ValueError):
            return None

    @staticmethod
    def format_bytes(size_bytes: int) -> str:
        """
        Format bytes to human-readable size.

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string (e.g., "1.5 GB")
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    @staticmethod
    def validate_artifact_paths(artifact) -> Tuple[List[str], List[str], dict]:
        """
        Validate all paths for an artifact with detailed information.

        Args:
            artifact: Artifact object to validate

        Returns:
            Tuple of (valid_paths, invalid_paths, info_dict)
        """
        valid_paths = []
        invalid_paths = []
        info = {
            "total_size": 0,
            "file_count": 0,
            "errors": []
        }

        for path in artifact.get_all_paths():
            path_info = PathValidator.get_path_info(path)
            if path_info:
                valid_paths.append(path)
                if path_info['is_file']:
                    info["total_size"] += path_info['size']
                    info["file_count"] += 1
            else:
                invalid_paths.append(path)

        return valid_paths, invalid_paths, info


class PathExpander:
    """Expands path variables and wildcards."""

    @staticmethod
    def expand_path(path: str, windows_partition: str = "C:") -> str:
        """
        Expand a single path with variables.

        Args:
            path: Path with variables
            windows_partition: Windows partition (e.g., "C:")

        Returns:
            Expanded path
        """
        expanded = path.replace("{PARTITION}", windows_partition)
        expanded = os.path.expandvars(expanded)
        return expanded

    @staticmethod
    def expand_user_paths(base_path: str, windows_partition: str = "C:") -> List[str]:
        r"""
        Expand user wildcard paths to individual user directories using glob.

        Args:
            base_path: Path with {USERNAME} or * for users (e.g., "{PARTITION}\Users\*\NTUSER.DAT")
            windows_partition: Windows partition (e.g., "C:", "D:")

        Returns:
            List of expanded paths for each matching user
        """
        import glob
        # Ensure base_path has the correct partition
        path_with_partition = base_path.replace("{PARTITION}", windows_partition)
        
        # If the path contains a user wildcard (either * or {USERNAME})
        # We use glob to find all matching files
        if r"\Users\*" in path_with_partition or r"\Users\{USERNAME}" in path_with_partition:
            # Normalize to glob pattern
            glob_pattern = path_with_partition.replace("{USERNAME}", "*")
            return glob.glob(glob_pattern)
            
        return [path_with_partition]

    @staticmethod
    def glob_expand(path: str) -> List[str]:
        """
        Expand wildcard paths using glob.

        Args:
            path: Path with wildcards

        Returns:
            List of matching file paths
        """
        import glob
        expanded = os.path.expandvars(path)
        matches = glob.glob(expanded, recursive=True)
        return matches if matches else [path]  # Return original if no matches


def validate_target_directory(path: str) -> Tuple[bool, str]:
    """
    Validate target collection directory.

    Args:
        path: Directory path to validate

    Returns:
        Tuple of (is_valid, message)
    """
    if not path:
        return False, "Target directory path is empty"

    try:
        path_obj = Path(path)

        if path_obj.exists():
            if not path_obj.is_dir():
                return False, f"Path exists but is not a directory: {path}"
            if not os.access(path, os.W_OK):
                return False, f"Target directory is not writable: {path}"
        else:
            # Try to create the directory
            try:
                path_obj.mkdir(parents=True, exist_ok=True)
                return True, f"Target directory created: {path}"
            except OSError as e:
                return False, f"Cannot create target directory: {e}"

        return True, f"Target directory is valid and writable: {path}"

    except Exception as e:
        return False, f"Error validating target directory: {e}"


"""
Artifact Validation Module
===========================

Validates collected artifacts for integrity and completeness.
Computes cryptographic hashes and validates file signatures.

Phase 2: Artifact Validation
"""

import hashlib
from dataclasses import dataclass, field
from typing import Optional, List
from .artifacts import ArtifactType


@dataclass
class ValidationResult:
    """Result of artifact validation.
    
    Tracks validation status including cryptographic hashes, file size,
    signature validity, and any warnings or errors encountered.
    
    Attributes:
        file_path: Path to the validated file
        file_size: Size of the file in bytes
        source_file_size: Size of the source file in bytes (for comparison)
        md5_hash: MD5 hash of the file
        sha256_hash: SHA256 hash of the file
        signature_valid: Whether the file signature is valid for its type
        warnings: List of validation warnings
        errors: List of validation errors
    """
    file_path: str
    file_size: int = 0
    source_file_size: Optional[int] = None
    md5_hash: Optional[str] = None
    sha256_hash: Optional[str] = None
    signature_valid: bool = False
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def add_warning(self, warning: str) -> None:
        """Add a validation warning.
        
        Args:
            warning: Warning message to add
        """
        self.warnings.append(warning)
    
    def add_error(self, error: str) -> None:
        """Add a validation error.
        
        Args:
            error: Error message to add
        """
        self.errors.append(error)


class ArtifactValidator:
    """Validates collected artifacts for integrity and completeness.
    
    Provides methods to:
    - Compute MD5 and SHA256 hashes using chunked reading
    - Validate file signatures based on artifact type
    - Check for zero-byte files and size mismatches
    """
    
    CHUNK_SIZE = 8192  # 8KB chunks for hash computation
    
    def compute_md5(self, file_path: str) -> str:
        """Compute MD5 hash of file using chunked reading.
        
        Reads the file in 8KB chunks to avoid loading large files
        entirely into memory.
        
        Args:
            file_path: Path to the file to hash
            
        Returns:
            MD5 hash as hexadecimal string
            
        Raises:
            OSError: If file cannot be read
        """
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(self.CHUNK_SIZE), b''):
                md5.update(chunk)
        return md5.hexdigest()
    
    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file using chunked reading.
        
        Reads the file in 8KB chunks to avoid loading large files
        entirely into memory.
        
        Args:
            file_path: Path to the file to hash
            
        Returns:
            SHA256 hash as hexadecimal string
            
        Raises:
            OSError: If file cannot be read
        """
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(self.CHUNK_SIZE), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def validate_registry_signature(self, file_path: str) -> bool:
        """Check for 'regf' signature at offset 0.
        
        Registry hive files start with the 4-byte signature 'regf'.
        
        Args:
            file_path: Path to the registry hive file
            
        Returns:
            True if signature is valid, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(4)
                return signature == b'regf'
        except (OSError, IOError):
            return False
    
    def validate_evtx_signature(self, file_path: str) -> bool:
        """Check for 'ElfFile' signature.
        
        Windows Event Log files (.evtx) start with the 8-byte signature
        'ElfFile\x00'.
        
        Args:
            file_path: Path to the event log file
            
        Returns:
            True if signature is valid, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(8)
                return signature == b'ElfFile\x00'
        except (OSError, IOError):
            return False
    
    def validate_database_signature(self, file_path: str) -> bool:
        """Check for SQLite or ESE database signature.
        
        SQLite databases start with "SQLite format 3\x00"
        ESE databases have "\xef\xcd\xab\x89" at offset 4
        
        Args:
            file_path: Path to the database file
            
        Returns:
            True if signature is valid, False otherwise
        """
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(16)
                # Check for SQLite signature
                if signature.startswith(b'SQLite format 3'):
                    return True
                # Check for ESE signature at offset 4
                if len(signature) >= 8 and signature[4:8] == b'\xef\xcd\xab\x89':
                    return True
                return False
        except (OSError, IOError):
            return False
    
    def validate_artifact(
        self, 
        file_path: str, 
        artifact_type: ArtifactType,
        source_file_size: Optional[int] = None
    ) -> ValidationResult:
        """Validate a collected artifact.
        
        Performs comprehensive validation including:
        - Computing MD5 and SHA256 hashes
        - Checking file size (zero-byte warning)
        - Comparing source and destination file sizes
        - Validating file signature based on artifact type
        
        Args:
            file_path: Path to the collected artifact file
            artifact_type: Type of artifact being validated
            source_file_size: Optional size of the source file for comparison
            
        Returns:
            ValidationResult with all validation details
        """
        result = ValidationResult(file_path=file_path, source_file_size=source_file_size)
        
        try:
            # Compute hashes
            result.md5_hash = self.compute_md5(file_path)
            result.sha256_hash = self.compute_sha256(file_path)
            
            # Check file size
            result.file_size = os.path.getsize(file_path)
            if result.file_size == 0:
                result.add_warning("File size is zero bytes")
            
            # Compare source and destination file sizes if source size is provided
            if source_file_size is not None and result.file_size != source_file_size:
                result.add_warning(
                    f"File size mismatch: source={source_file_size} bytes, "
                    f"destination={result.file_size} bytes"
                )
            
            # Signature validation based on artifact type
            if artifact_type == ArtifactType.REGISTRY_HIVES:
                result.signature_valid = self.validate_registry_signature(file_path)
                if not result.signature_valid:
                    result.add_error("Invalid registry hive signature (expected 'regf')")
                    
            elif artifact_type == ArtifactType.EVENT_LOGS:
                result.signature_valid = self.validate_evtx_signature(file_path)
                if not result.signature_valid:
                    result.add_error("Invalid event log signature (expected 'ElfFile')")
                    
            elif artifact_type in [ArtifactType.AMCACHE, ArtifactType.SRUM_DATABASE]:
                result.signature_valid = self.validate_database_signature(file_path)
                if not result.signature_valid:
                    result.add_error("Invalid database signature (expected SQLite or ESE)")
            else:
                # For other artifact types, skip signature validation
                result.signature_valid = True
                
        except Exception as e:
            result.add_error(f"Validation failed: {str(e)}")
        
        return result
