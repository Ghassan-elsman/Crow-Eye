import os
import shutil
import logging
from pathlib import Path
from typing import Optional, Union, List, Dict, Any
import json

class FileUtils:
    """
    Utility class for common file operations with error handling and logging.
    """
    
    def __init__(self, logger_name: str = 'FileUtils'):
        """
        Initialize the FileUtils with a logger.
        
        Args:
            logger_name: Name to use for the logger
        """
        self.logger = logging.getLogger(logger_name)
    
    def ensure_directory_exists(self, directory: Union[str, Path]) -> bool:
        """
        Ensure that a directory exists, creating it if necessary.
        
        Args:
            directory: Path to the directory
            
        Returns:
            bool: True if directory exists or was created, False otherwise
        """
        try:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            self.logger.error(f"Failed to create directory {directory}: {str(e)}")
            return False
    
    def read_json_file(self, file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Read and parse a JSON file.
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            Parsed JSON data as a dictionary, or None if an error occurred
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error reading JSON file {file_path}: {str(e)}")
            return None
    
    def write_json_file(self, data: Any, file_path: Union[str, Path], indent: int = 4) -> bool:
        """
        Write data to a JSON file.
        
        Args:
            data: Data to write (must be JSON serializable)
            file_path: Path to the output file
            indent: Indentation level for pretty printing
            
        Returns:
            bool: True if write was successful, False otherwise
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"Error writing JSON file {file_path}: {str(e)}")
            return False
    
    def copy_file(self, source: Union[str, Path], destination: Union[str, Path], overwrite: bool = False) -> bool:
        """
        Copy a file from source to destination.
        
        Args:
            source: Source file path
            destination: Destination file path
            overwrite: Whether to overwrite if destination exists
            
        Returns:
            bool: True if copy was successful, False otherwise
        """
        try:
            src = Path(source)
            dst = Path(destination)
            
            if not src.exists():
                self.logger.error(f"Source file does not exist: {source}")
                return False
                
            if dst.exists() and not overwrite:
                self.logger.warning(f"Destination file exists and overwrite is False: {destination}")
                return False
                
            # Ensure destination directory exists
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(src, dst)
            return True
            
        except Exception as e:
            self.logger.error(f"Error copying file from {source} to {destination}: {str(e)}")
            return False
    
    def find_files(self, 
                  directory: Union[str, Path], 
                  pattern: str = '*', 
                  recursive: bool = True) -> List[Path]:
        """
        Find files matching a pattern in a directory.
        
        Args:
            directory: Directory to search in
            pattern: File pattern to match (e.g., '*.txt')
            recursive: Whether to search recursively
            
        Returns:
            List of matching file paths
        """
        try:
            path = Path(directory)
            if not path.exists() or not path.is_dir():
                self.logger.warning(f"Directory does not exist or is not a directory: {directory}")
                return []
                
            if recursive:
                return list(path.rglob(pattern))
            else:
                return list(path.glob(pattern))
                
        except Exception as e:
            self.logger.error(f"Error finding files in {directory} with pattern {pattern}: {str(e)}")
            return []
    
    def get_file_hash(self, file_path: Union[str, Path], algorithm: str = 'sha256') -> Optional[str]:
        """
        Calculate the hash of a file.
        
        Args:
            file_path: Path to the file
            algorithm: Hash algorithm to use (e.g., 'md5', 'sha1', 'sha256')
            
        Returns:
            Hex digest of the file hash, or None if an error occurred
        """
        import hashlib
        
        try:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                self.logger.error(f"File does not exist or is not a file: {file_path}")
                return None
                
            hash_func = getattr(hashlib, algorithm.lower(), None)
            if not hash_func:
                self.logger.error(f"Unsupported hash algorithm: {algorithm}")
                return None
                
            h = hash_func()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
                    
            return h.hexdigest()
            
        except Exception as e:
            self.logger.error(f"Error calculating {algorithm} hash for {file_path}: {str(e)}")
            return None
