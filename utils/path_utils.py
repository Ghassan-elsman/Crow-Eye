import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Union

class PathUtils:
    """
    Utility class for forensic path manipulation and OS compatibility.
    Handles case-sensitivity issues, path separators, and forensic image path mapping.
    """

    @staticmethod
    def normalize_path(path: str) -> str:
        """
        Normalizes path separators to the current OS standard.
        """
        if not path:
            return ""
        return os.path.normpath(path.replace('\\', '/'))

    @staticmethod
    def to_forensic_path(path: str) -> str:
        """
        Converts a path to a forensic-standard path (using forward slashes).
        Useful for internal consistency regardless of host OS.
        """
        if not path:
            return "/"
        return path.replace('\\', '/').replace('//', '/')

    @staticmethod
    def get_case_insensitive_path(base_path: str, target_name: str) -> Optional[str]:
        """
        Searches for target_name within base_path case-insensitively on the local file system.
        Supports multi-level nested paths correctly.
        """
        if not os.path.exists(base_path):
            return None
        
        current_path = base_path
        # Normalize slashes and split
        target_name = target_name.replace('\\', '/').strip('/')
        parts = [p for p in target_name.split('/') if p]
        
        for part in parts:
            part_lower = part.lower()
            found_match = False
            try:
                for entry in os.listdir(current_path):
                    if entry.lower() == part_lower:
                        current_path = os.path.join(current_path, entry)
                        found_match = True
                        break
            except Exception:
                return None
                
            if not found_match:
                return None
                
        return current_path

    @staticmethod
    def join_forensic(*args) -> str:
        """
        Joins path components using forward slashes for forensic image consistency.
        """
        joined = "/".join(str(arg).strip("/") for arg in args if arg)
        return "/" + joined if args and str(args[0]).startswith("/") else joined

    @staticmethod
    def is_windows_path(path: str) -> bool:
        r"""
        Detects if a path follows Windows conventions (e.g., C:\ or \Device\).
        """
        if re.match(r'^[a-zA-Z]:\\', path):
            return True
        if path.startswith('\\\\'):
            return True
        return False

    @staticmethod
    def convert_windows_to_posix(path: str) -> str:
        r"""
        Converts Windows-style paths (C:\Windows) to POSIX-style (/C/Windows).
        Useful for mapping Windows artifacts when running on Linux.
        """
        # Remove drive letter colon
        path = re.sub(r'^([a-zA-Z]):', r'/\1', path)
        return path.replace('\\', '/')

    @staticmethod
    def get_registry_path_parts(reg_path: str) -> List[str]:
        """
        Splits a registry path correctly regardless of which slash is used.
        Registry paths technically use backslashes.
        """
        # Normalize to backslash first as it's the registry standard
        norm_path = reg_path.replace('/', '\\')
        return [p for p in norm_path.split('\\') if p]
