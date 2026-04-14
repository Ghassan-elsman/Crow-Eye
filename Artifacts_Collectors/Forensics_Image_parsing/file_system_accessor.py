"""
File System Accessor

Abstraction layer for file system access via the dissect ecosystem.
Provides consistent interface regardless of image format.
"""

import os
from typing import List, Optional
from datetime import datetime
try:
    if __package__ or "." in __name__:
        from .data_models import FileMetadata
    else:
        from data_models import FileMetadata
except (ImportError, ValueError):
    from data_models import FileMetadata

# Import PathUtils for Linux compatibility
try:
    if __package__ or "." in __name__:
        from ...utils.path_utils import PathUtils
    else:
        # Check if utils is in sys.path or use direct import
        try:
            from utils.path_utils import PathUtils
        except ImportError:
            import sys
            sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from utils.path_utils import PathUtils
except (ImportError, ValueError):
    PathUtils = None

# Optional imports - gracefully handle missing dependencies
try:
    from dissect.target.volume import open as open_volume
    from dissect.target.filesystem import open as open_fs
    DISSECT_AVAILABLE = True
except ImportError:
    DISSECT_AVAILABLE = False
    print("Warning: dissect not available - file system access will be limited")


class FileSystemAccessor:
    """
    Abstraction layer for file system access via dissect or pycdlib.
    
    Provides consistent interface for navigating and reading files
    from forensic images regardless of the underlying format.
    """
    
    def __init__(self, img_info):
        """
        Initialize file system accessor.
        
        Args:
            img_info: file-like object for the forensic container (from container.open)
                      or a pycdlib.PyCdlib object.
        """
        self.img_info = img_info
        self.fs_info = None
        self.current_partition_offset = 0
        self.is_pycdlib = hasattr(img_info, 'list_dir')
    
    def open_partition(self, partition_offset: int) -> bool:
        """
        Open file system at the specified partition offset.
        
        Args:
            partition_offset: Byte offset of the partition
            
        Returns:
            True if successful, False otherwise
        """
        if self.is_pycdlib:
            self.fs_info = self.img_info
            self.current_partition_offset = 0
            return True
            
        try:
            # Step 1: Attempt standard volume system discovery (MBR/GPT)
            try:
                vs = open_volume(self.img_info)
                for vol in vs.volumes:
                    if vol.offset == partition_offset:
                        self.fs_info = open_fs(vol)
                        self.current_partition_offset = partition_offset
                        print(f"[INFO] Successfully opened partition via Volume System at offset {partition_offset}")
                        return True
            except Exception:
                pass
            
            # Step 2: Fallback to Direct Filesystem Mounting (Volume-Only Image Parity)
            # If standard discovery failed or this is a raw volume mount (offset 0)
            self.img_info.seek(partition_offset)
            try:
                # Deterministically attempt to open as a raw filesystem
                self.fs_info = open_fs(self.img_info)
                self.current_partition_offset = partition_offset
                print(f"[INFO] Successfully opened direct filesystem at offset {partition_offset}")
                return True
            except Exception as e:
                print(f"[DEBUG] Direct filesystem mount failed at {partition_offset}: {e}")
                
            print(f"[ERROR] Could not identify a valid filesystem at offset {partition_offset}")
            return False
            
        except Exception as e:
            print(f"[ERROR] Critical failure during partition mount at {partition_offset}: {e}")
            return False
    
    def list_directory(self, path: str = "/") -> List[FileMetadata]:
        """
        List files in a directory.
        
        Args:
            path: Directory path (default: root)
            
        Returns:
            List of FileMetadata objects for files in the directory
        """
        if not self.fs_info:
            raise RuntimeError("File system not opened. Call open_partition() first.")
        
        files = []
        
        try:
            dir_entry = self.fs_info.get(path)
            if not dir_entry or not dir_entry.is_dir():
                return files
                
            for entry in dir_entry.scandir():
                # Skip . and .. entries if they exist
                name = getattr(entry, 'name', None) or ""
                if name in ['.', '..']:
                    continue
                
                try:
                    file_meta = self._extract_metadata(entry, path)
                    files.append(file_meta)
                except Exception as e:
                    print(f"[WARNING] Could not access file {name}: {e}")
                    continue
        
        except Exception as e:
            print(f"[ERROR] Failed to list directory {path}: {e}")
        
        return files
    
    def read_file(self, path: str) -> bytes:
        """
        Read complete file contents.
        
        Args:
            path: File path within the image
            
        Returns:
            File contents as bytes
        """
        if not self.fs_info:
            raise RuntimeError("File system not opened. Call open_partition() first.")
        
        if self.is_pycdlib:
            import io
            try:
                iso_path = path if path.startswith('/') else '/' + path
                out_io = io.BytesIO()
                self.fs_info.get_file_from_iso_fp(out_io, iso_path=iso_path)
                return out_io.getvalue()
            except Exception as e:
                raise IOError(f"Failed to read file {path} from ISO: {e}")
        
        try:
            entry = self.fs_info.get(path)
            with entry.open() as f:
                return f.read()
        except Exception as e:
            raise IOError(f"Failed to read file {path}: {e}")
    
    def _set_forensic_timestamps(self, dest_path, atime, mtime, ctime):
        """
        Sets forensic MAC times (Modified, Accessed, Created) on the local file.
        Uses ctypes on Windows to set Creation Time which os.utime doesn't support.
        """
        try:
            # Set Access and Modified times
            os.utime(dest_path, (atime, mtime))
            
            # Set Creation time (Windows only)
            if os.name == 'nt' and ctime:
                import ctypes
                from ctypes import wintypes
                
                # Convert unix timestamp to Win32 FILETIME
                # FILETIME is 100-nanosecond intervals since Jan 1, 1601
                # (116444736000000000 is the offset in 100ns units)
                win_ctime = int(ctime * 10000000) + 116444736000000000
                
                low = win_ctime & 0xFFFFFFFF
                high = win_ctime >> 32
                ft_ctime = wintypes.FILETIME(low, high)
                
                # Open file handle
                FILE_WRITE_ATTRIBUTES = 0x0100
                OPEN_EXISTING = 3
                handle = ctypes.windll.kernel32.CreateFileW(
                    dest_path, FILE_WRITE_ATTRIBUTES, 0, None, OPEN_EXISTING, 0, None
                )
                
                if handle != -1:
                    ctypes.windll.kernel32.SetFileTime(handle, ctypes.byref(ft_ctime), None, None)
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception as e:
            # Silently fail if we can't set timestamps (e.g. permission issues on dest)
            pass

    def read_file_streaming(self, path: str, dest_path: str, chunk_size: int = 1024*1024) -> int:
        """
        Read file using streaming to minimize memory usage, handles NTFS streams.
        Specifically optimized for USN Journal compaction (skips leading sparse zeros).
        
        Args:
            path: Source file path within the image (can include :stream_name)
            dest_path: Destination file path on local system
            chunk_size: Size of chunks to read (default: 1MB)
            
        Returns:
            Total bytes read
        """
        if not self.fs_info:
            raise RuntimeError("File system not opened. Call open_partition() first.")
        
        try:
            # Handle potential stream names in path (e.g., File:$J)
            base_path = path
            stream_name = None
            if ':' in path and not path.startswith('\\\\.'):
                parts = path.split(':')
                base_path = parts[0]
                stream_name = parts[1]
                
            entry = self.fs_info.get(base_path)
            bytes_read_total = 0
            
            # Open the stream (named or default)
            try:
                # Dissect's entry.open() takes 'name' as first positional arg
                # in its NtfsFilesystemEntry implementation.
                source_stream = entry.open(stream_name)
            except Exception as e:
                # Fallback: if it's NTFS, try to find the attribute manually
                source_stream = None
                if stream_name and hasattr(entry, 'attr'):
                    try:
                        attrs = entry.attr() if callable(entry.attr) else entry.attr
                        for attr in attrs:
                            # Use hasattr/getattr safely as some underlying objects vary
                            if getattr(attr, 'name', '') == stream_name:
                                source_stream = attr.open()
                                break
                    except:
                        pass
                
                if not source_stream:
                    # Final attempt: default open
                    try:
                        source_stream = entry.open()
                    except:
                        raise IOError(f"Could not open stream '{stream_name or 'DATA'}' on {base_path}: {e}")

            with source_stream as src_file, open(dest_path, 'wb') as dest_file:
                # Determine logical size for compaction limits
                # Getting size can be tricky for named streams
                logical_size = 0
                if hasattr(src_file, 'size'):
                    logical_size = src_file.size
                elif hasattr(src_file, 'attr') and hasattr(src_file.attr, 'size'):
                    logical_size = src_file.attr.size
                
                # If we still don't have a size, try entry.stat() as fallback
                try:
                    stat_info = entry.stat()
                    if logical_size == 0:
                        logical_size = stat_info.st_size
                except:
                    stat_info = None

                # SPECIAL COMPACTION LOGIC for USN Journal or large sparse streams
                # Find the first non-zero block to avoid gigabytes of leading zeros
                # USN ($J) is almost always sparse at the beginning
                if stream_name == '$J' or (logical_size > 100*1024*1024):
                    print(f"[INFO] Applying compaction logic to large/sparse stream: {path} (Logical size: {logical_size})")
                    
                    # Find start of data
                    pos = 0
                    limit = logical_size
                    found_data = False
                    
                    # Search in moderate steps (5MB) to avoid missing small buffers but save time
                    step = 5 * 1024 * 1024
                    while pos < limit:
                        src_file.seek(pos)
                        check_data = src_file.read(min(chunk_size, limit - pos))
                        if not check_data: break
                        
                        if any(check_data):
                            found_data = True
                            print(f"[INFO] Found data start at offset {pos}. Beginning extraction...")
                            src_file.seek(pos)
                            break
                        pos += step
                    
                    if not found_data:
                        print(f"[WARNING] No data found in entire stream {path}")
                        return 0

                # Standard streaming (contributing from potentially seeked position)
                while True:
                    data = src_file.read(chunk_size)
                    if not data:
                        break
                    dest_file.write(data)
                    bytes_read_total += len(data)
            
            # After extraction, preserve forensic timestamps
            if stat_info and not stream_name: # Only for main file, named streams share base entry timestamps
                self._set_forensic_timestamps(
                    dest_path, 
                    getattr(stat_info, 'st_atime', 0),
                    getattr(stat_info, 'st_mtime', 0),
                    getattr(stat_info, 'st_ctime', 0)
                )
                
            return bytes_read_total
        
        except Exception as e:
            raise IOError(f"Failed to stream file {path}: {e}")

    def read_directory_recursive(self, image_dir_path: str, local_dest_root: str) -> int:
        """
        Recursively extract a directory from the image to a local path.
        
        Args:
            image_dir_path: Source directory path in image
            local_dest_root: Local destination path
            
        Returns:
            Number of files successfully extracted
        """
        if not self.fs_info:
            raise RuntimeError("File system not opened. Call open_partition() first.")
            
        files_extracted = 0
        directories_to_fix = []
        try:
            dir_entry = self.fs_info.get(image_dir_path)
            if not dir_entry or not dir_entry.is_dir():
                return 0
                
            os.makedirs(local_dest_root, exist_ok=True)
            
            for root_path, dirs, files in dir_entry.walk():
                # root_path is a string in this version of dissect
                rel_path = root_path[len(image_dir_path):].lstrip('/')
                current_dest_dir = os.path.join(local_dest_root, rel_path.replace('/', os.sep))
                os.makedirs(current_dest_dir, exist_ok=True)
                
                # Get the root entry for this directory level
                try:
                    root_entry = self.fs_info.get(root_path)
                    
                    # Track this directory to set its timestamps later (bottom-up)
                    # We need its stat info
                    try:
                        st = root_entry.stat()
                        directories_to_fix.append((current_dest_dir, st))
                    except:
                        pass

                    for filename in files:
                        try:
                            file_entry = root_entry.get(filename)
                            if not file_entry.is_file():
                                continue
                                
                            source_path = file_entry.path
                            target_path = os.path.join(current_dest_dir, filename)
                            
                            self.read_file_streaming(source_path, target_path)
                            files_extracted += 1
                        except Exception as e:
                            print(f"[WARNING] Failed to extract {filename} in {root_path}: {e}")
                except Exception as e:
                    print(f"[ERROR] Could not get entry for {root_path}: {e}")
            
            # Fix directory timestamps in reverse order (deepest first)
            # This ensures that setting subfolder times doesn't mess up parent folder times
            for dest_dir, stat_info in reversed(directories_to_fix):
                self._set_forensic_timestamps(
                    dest_dir,
                    getattr(stat_info, 'st_atime', 0),
                    getattr(stat_info, 'st_mtime', 0),
                    getattr(stat_info, 'st_ctime', 0)
                )
                        
            return files_extracted
        except Exception as e:
            print(f"[ERROR] recursive extraction of {image_dir_path} failed: {e}")
            return files_extracted
    
    def get_metadata(self, path: str) -> FileMetadata:
        """
        Get file metadata without reading contents.
        
        Args:
            path: File path within the image
            
        Returns:
            FileMetadata object
        """
        if not self.fs_info:
            raise RuntimeError("File system not opened. Call open_partition() first.")
        
        try:
            entry = self.fs_info.get(path)
            # parent path
            import posixpath
            parent_path = posixpath.dirname(path)
            return self._extract_metadata(entry, parent_path)
        except Exception as e:
            raise IOError(f"Failed to get metadata for {path}: {e}")
    
    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists.
        
        Args:
            path: File path within the image
            
        Returns:
            True if file exists, False otherwise
        """
        if not self.fs_info:
            return False
        
        if self.is_pycdlib:
            try:
                iso_path = path if path.startswith('/') else '/' + path
                self.fs_info.get_record(iso_path=iso_path)
                return True
            except:
                return False
        
        try:
            return self.fs_info.exists(path)
        except:
            return False

    def find_path_case_insensitive(self, path: str) -> Optional[str]:
        """
        Finds a case-insensitive match for a path within the forensic image.
        Essential for Linux hosts where the filesystem is case-sensitive but 
        the image (Windows/NTFS) may be treated with case-insensitive logic.
        
        Args:
            path: Target path (e.g., /windows/system32/config/SYSTEM)
            
        Returns:
            The correctly-cased path if found, or None
        """
        if not self.fs_info:
            return None
            
        # Standardize to forward slashes
        path = path.replace('\\', '/')
        parts = [p for p in path.split('/') if p]
        
        current_path = "/"
        
        for part in parts:
            found_part = None
            try:
                # Get the current directory entry
                dir_entry = self.fs_info.get(current_path)
                if not dir_entry or not dir_entry.is_dir():
                    return None
                    
                # Search entries for a case-insensitive match
                target_lower = part.lower()
                for entry in dir_entry.scandir():
                    name = getattr(entry, 'name', '')
                    if name.lower() == target_lower:
                        found_part = name
                        break
                
                if not found_part:
                    return None
                
                # Update current path for next iteration
                if current_path == "/":
                    current_path = "/" + found_part
                else:
                    current_path = current_path + "/" + found_part
                    
            except Exception:
                return None
                
        return current_path
    
    def _extract_metadata(self, entry, parent_path: str) -> FileMetadata:
        """
        Extract metadata from a directory entry.
        
        Args:
            entry: dissect FilesystemEntry
            parent_path: Parent directory path
            
        Returns:
            FileMetadata object
        """
        name = getattr(entry, 'name', '')
        full_path = f"{parent_path}/{name}".replace('//', '/')
        
        try:
            stat_info = entry.stat()
            size = getattr(stat_info, 'st_size', 0)
            
            created_time = None
            modified_time = None
            accessed_time = None
            
            if hasattr(stat_info, 'st_ctime') and stat_info.st_ctime:
                created_time = datetime.fromtimestamp(stat_info.st_ctime)
            if hasattr(stat_info, 'st_mtime') and stat_info.st_mtime:
                modified_time = datetime.fromtimestamp(stat_info.st_mtime)
            if hasattr(stat_info, 'st_atime') and stat_info.st_atime:
                accessed_time = datetime.fromtimestamp(stat_info.st_atime)
                
        except Exception:
            size = 0
            created_time = None
            modified_time = None
            accessed_time = None
        
        is_directory = entry.is_dir()
        
        # Dissect might not natively expose DOS attributes on all file systems easily through generic stat
        # We will set them to False as a fallback. 
        is_hidden = False
        is_system = False
        
        # if the filesystem has an attribute method or similar for Windows attributes:
        # For now, default to False
        
        return FileMetadata(
            file_path=full_path,
            size_bytes=size,
            created_time=created_time,
            modified_time=modified_time,
            accessed_time=accessed_time,
            is_directory=is_directory,
            is_hidden=is_hidden,
            is_system=is_system
        )
    
    def close(self):
        """Close the file system."""
        self.fs_info = None
        self.img_info = None
