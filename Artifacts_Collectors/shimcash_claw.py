#!/usr/bin/env python3
"""
Enhanced ShimCache Parser

A comprehensive tool for parsing Windows ShimCache (Application Compatibility Cache) data.
This parser extracts execution artifacts from the Windows registry and stores them in a 
SQLite database for forensic analysis.

Features:
- Supports Windows 7, 10, and 11 ShimCache formats
- Extracts file paths, modification times, and execution status
- Stores parsed data in SQLite database with duplicate prevention
- Provides readable timestamp formatting
- Comprehensive error handling and logging

Author: Forensic Analysis Tool
Version: 2.0
"""

import struct
import sqlite3
import datetime
import sys
import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple

try:
    from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx, CloseKey
    LIVE_REGISTRY_AVAILABLE = True
except ImportError:
    LIVE_REGISTRY_AVAILABLE = False
    print("Warning: Live registry access not available on this platform")

class ShimCacheEntry:
    """
    Represents a single ShimCache entry with all relevant metadata.
    
    Attributes:
        path (str): Full file path of the executable
        filename (str): Just the filename portion of the path
        last_modified (datetime): Last modification timestamp
        last_modified_readable (str): Human-readable timestamp format
        data_size (int): Size of the data section in bytes
        entry_size (int): Total size of the cache entry
        cache_entry_position (int): Position within the cache data
        entry_hash (str): MD5 hash of the entry for duplicate detection
    """
    
    def __init__(self):
        self.path = ""
        self.filename = ""
        self.last_modified = None
        self.last_modified_readable = ""
        self.data_size = 0
        self.entry_size = 0
        self.cache_entry_position = 0
        self.entry_hash = ""
    
    def generate_hash(self) -> str:
        """
        Generate MD5 hash of path and timestamp for duplicate detection.
        
        Returns:
            str: MD5 hash of the entry
        """
        hash_input = f"{self.path}_{self.last_modified}".encode('utf-8')
        return hashlib.md5(hash_input).hexdigest()
    
    def extract_filename(self):
        """Extract filename from full path and handle edge cases."""
        if self.path:
            try:
                self.filename = Path(self.path).name
            except Exception:
                # Fallback for malformed paths
                if '\\' in self.path:
                    self.filename = self.path.split('\\')[-1]
                elif '/' in self.path:
                    self.filename = self.path.split('/')[-1]
                else:
                    self.filename = self.path
        else:
            self.filename = "UNKNOWN"
    
    def format_timestamp(self):
        """Format timestamp to human-readable format."""
        if self.last_modified:
            # Check if datetime object has timezone info and format accordingly
            if self.last_modified.tzinfo is not None:
                # Timezone-aware datetime: use strftime to format without timezone
                self.last_modified_readable = self.last_modified.strftime('%Y-%m-%d %H:%M:%S')
            else:
                # Timezone-naive datetime: convert to string and remove milliseconds
                self.last_modified_readable = str(self.last_modified).split('.')[0]
        else:
            self.last_modified_readable = "Unknown"

class ShimCacheParser:
    """
    Main parser class for ShimCache data extraction and analysis.
    
    This class handles the parsing of Windows ShimCache data from the registry,
    supporting multiple Windows versions with different data formats.
    """
    
    # Windows version signatures and constants
    WINDOWS_10_SIGNATURE = 0x73743031  # "10ts" in little-endian
    WINDOWS_7_SIGNATURE_PATTERN = b'\x30\x00\x00\x00'  # Windows 7 pattern
    INSERT_FLAG_EXECUTED = 0x00000002  # Execution flag for Windows 7
    
    def __init__(self, database_path: str = "shimcache.db"):
        """
        Initialize the ShimCache parser.
        
        Args:
            database_path (str): Path to SQLite database file
        """
        self.database_path = database_path
        self.entries = []
        self.setup_database()
    
    def setup_database(self):
        """
        Create SQLite database and tables with improved schema.
        
        The database schema includes:
        - Unique constraints to prevent duplicates
        - Indexes for performance optimization
        - Readable timestamp formatting
        - Filename extraction
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Create main table with improved schema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shimcache_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                last_modified TEXT,
                last_modified_readable TEXT,
                data_size INTEGER DEFAULT 0,
                entry_size INTEGER DEFAULT 0,
                cache_entry_position INTEGER DEFAULT 0,
                entry_hash TEXT UNIQUE,
                parsed_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(path, last_modified)
            )
        ''')
        
        # Create indexes for faster searches and duplicate detection
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_path ON shimcache_entries(path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON shimcache_entries(filename)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_modified ON shimcache_entries(last_modified)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_entry_hash ON shimcache_entries(entry_hash)')
        
        conn.commit()
        conn.close()
        # Use ASCII-safe character instead of Unicode checkmark to avoid encoding errors
        print(f"[OK] Database initialized: {self.database_path}")
    
    def filetime_to_datetime(self, filetime: int) -> Optional[datetime.datetime]:
        """
        Convert Windows FILETIME to Python datetime object.
        
        Windows FILETIME represents the number of 100-nanosecond intervals
        since January 1, 1601 UTC.
        
        Args:
            filetime (int): Windows FILETIME value
            
        Returns:
            datetime.datetime: Converted timestamp or None if invalid
        """
        try:
            if filetime == 0:
                return None
            # Convert FILETIME to Unix timestamp
            timestamp = filetime / 10000000.0 - 11644473600
            return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        except (ValueError, OSError) as e:
            print(f"Warning: Invalid FILETIME value {filetime}: {e}")
            return None
    
    def detect_windows_version(self, data: bytes) -> str:
        """
        Detect Windows version based on ShimCache data patterns.
        
        Different Windows versions use different ShimCache formats:
        - Windows 10/11: Uses "10ts" signature
        - Windows 7: Uses different header structure
        
        Args:
            data (bytes): Raw ShimCache data
            
        Returns:
            str: Detected Windows version
        """
        if len(data) < 52:
            return "Unknown"
        
        # Check for Windows 10/11 signature
        for i in range(52, min(len(data) - 4, 200)):
            try:
                signature = struct.unpack('<I', data[i:i+4])[0]
                if signature == self.WINDOWS_10_SIGNATURE:
                    return "Windows 10/11"
            except struct.error:
                continue
        
        # Check for Windows 7 patterns
        if self.WINDOWS_7_SIGNATURE_PATTERN in data[:200]:
            return "Windows 7"
        
        return "Unknown"
    
    def parse_windows_10_11(self, data: bytes) -> List[ShimCacheEntry]:
        """
        Parse Windows 10/11 ShimCache format.
        
        Windows 10/11 format structure:
        - 52-byte header
        - Variable-length entries with "10ts" signature
        - Each entry contains path, timestamp, and metadata
        
        Args:
            data (bytes): Raw ShimCache data
            
        Returns:
            List[ShimCacheEntry]: Parsed cache entries
        """
        entries = []
        index = 52  # Skip 52-byte header
        entry_count = 0
        
        print("[INFO] Parsing Windows 10/11 format...")
        
        while index < len(data) - 20:  # Ensure minimum entry size
            try:
                # Check for signature
                if index + 4 > len(data):
                    break
                    
                signature = struct.unpack('<I', data[index:index+4])[0]
                if signature != self.WINDOWS_10_SIGNATURE:
                    index += 1
                    continue
                
                entry = ShimCacheEntry()
                entry.cache_entry_position = index
                
                index += 4  # Skip signature
                index += 4  # Skip 4 unknown bytes
                
                # Entry length
                if index + 4 > len(data):
                    break
                entry.entry_size = struct.unpack('<I', data[index:index+4])[0]
                index += 4
                
                # Path length
                if index + 2 > len(data):
                    break
                path_length = struct.unpack('<H', data[index:index+2])[0]
                index += 2
                
                # Path (Unicode)
                if index + path_length > len(data):
                    break
                try:
                    entry.path = data[index:index+path_length].decode('utf-16le', errors='ignore').rstrip('\x00')
                except UnicodeDecodeError:
                    entry.path = "DECODE_ERROR"
                index += path_length
                
                # Extract filename
                entry.extract_filename()
                
                # Last modified time
                if index + 8 > len(data):
                    break
                filetime = struct.unpack('<Q', data[index:index+8])[0]
                entry.last_modified = self.filetime_to_datetime(filetime)
                entry.format_timestamp()
                index += 8
                
                # Data size
                if index + 2 > len(data):
                    break
                entry.data_size = struct.unpack('<H', data[index:index+2])[0]
                index += 2
                
                # Skip binary data section
                if index + entry.data_size > len(data):
                    break
                index += entry.data_size
                
                # Generate hash for duplicate detection
                entry.entry_hash = entry.generate_hash()
                
                entries.append(entry)
                entry_count += 1
                
                if entry_count % 100 == 0:
                    print(f"  [PROGRESS] Parsed {entry_count} entries...")
                
            except (struct.error, UnicodeDecodeError, IndexError) as e:
                print(f"[WARNING] Error parsing entry at offset {index}: {e}")
                index += 1
                continue
        
        print(f"[OK] Successfully parsed {len(entries)} Windows 10/11 entries")
        return entries
    
    def parse_windows_7(self, data: bytes) -> List[ShimCacheEntry]:
        """
        Parse Windows 7 ShimCache format.
        
        Windows 7 format structure:
        - Header with entry count
        - Fixed-size entry headers with offsets
        - Variable-length data sections
        
        Args:
            data (bytes): Raw ShimCache data
            
        Returns:
            List[ShimCacheEntry]: Parsed cache entries
        """
        entries = []
        
        print("[INFO] Parsing Windows 7 format...")
        
        try:
            # Get number of entries (first 4 bytes after header)
            if len(data) < 8:
                return entries
                
            num_entries = struct.unpack('<I', data[4:8])[0]
            print(f"  [INFO] Found {num_entries} entries in Windows 7 format")
            
            index = 8  # Start after header
            
            for i in range(num_entries):
                if index + 32 > len(data):  # Minimum entry size
                    break
                    
                try:
                    entry = ShimCacheEntry()
                    entry.cache_entry_position = index
                    
                    # Entry length
                    entry.entry_size = struct.unpack('<I', data[index:index+4])[0]
                    index += 4
                    
                    # Skip max path length
                    index += 4
                    
                    # Path length
                    path_length = struct.unpack('<I', data[index:index+4])[0]
                    index += 4
                    
                    # Path offset
                    path_offset = struct.unpack('<I', data[index:index+4])[0]
                    index += 4
                    
                    # Last modified time
                    filetime = struct.unpack('<Q', data[index:index+8])[0]
                    entry.last_modified = self.filetime_to_datetime(filetime)
                    entry.format_timestamp()
                    index += 8
                    
                    # Skip insert flags and unknown bytes
                    index += 8
                    
                    # Data size
                    entry.data_size = struct.unpack('<I', data[index:index+4])[0]
                    index += 4
                    
                    # Skip data offset
                    index += 4
                    
                    # Extract path
                    if path_offset < len(data) and path_offset + path_length <= len(data):
                        try:
                            entry.path = data[path_offset:path_offset+path_length].decode('utf-16le', errors='ignore').rstrip('\x00')
                        except UnicodeDecodeError:
                            entry.path = "DECODE_ERROR"
                    else:
                        entry.path = "INVALID_OFFSET"
                    
                    # Extract filename
                    entry.extract_filename()
                    
                    # Generate hash for duplicate detection
                    entry.entry_hash = entry.generate_hash()
                    
                    entries.append(entry)
                    
                    if (i + 1) % 100 == 0:
                        print(f"  [PROGRESS] Parsed {i + 1}/{num_entries} entries...")
                        
                except (struct.error, UnicodeDecodeError, IndexError) as e:
                    print(f"[WARNING] Error parsing Windows 7 entry {i}: {e}")
                    continue
                    
        except Exception as e:
            print(f"[ERROR] Error parsing Windows 7 format: {e}")
        
        print(f"[OK] Successfully parsed {len(entries)} Windows 7 entries")
        return entries
    
    def parse_shimcache_data(self, data: bytes) -> List[ShimCacheEntry]:
        """
        Main parsing function - detects version and parses accordingly.
        
        Args:
            data (bytes): Raw ShimCache data from registry
            
        Returns:
            List[ShimCacheEntry]: All parsed cache entries
        """
        if not data or len(data) < 20:
            print("[ERROR] Invalid or empty ShimCache data")
            return []
        
        version = self.detect_windows_version(data)
        print(f"[INFO] Detected Windows version: {version}")
        
        if version == "Windows 10/11":
            return self.parse_windows_10_11(data)
        elif version == "Windows 7":
            return self.parse_windows_7(data)
        else:
            print("[WARNING] Unknown Windows version, attempting Windows 10/11 parsing...")
            return self.parse_windows_10_11(data)
    
    def get_live_registry_data(self) -> Optional[bytes]:
        """
        Extract ShimCache data from live Windows registry.
        
        Attempts to read from multiple control sets to ensure data retrieval.
        
        Returns:
            bytes: Raw ShimCache data or None if failed
        """
        if not LIVE_REGISTRY_AVAILABLE:
            print("[ERROR] Live registry access not available on this platform")
            return None
        
        try:
            # Try multiple control sets
            registry_paths = [
                r"SYSTEM\CurrentControlSet\Control\Session Manager\AppCompatCache",
                r"SYSTEM\ControlSet001\Control\Session Manager\AppCompatCache",
                r"SYSTEM\ControlSet002\Control\Session Manager\AppCompatCache"
            ]
            
            for path in registry_paths:
                try:
                    key = OpenKey(HKEY_LOCAL_MACHINE, path)
                    data, _ = QueryValueEx(key, "AppCompatCache")
                    CloseKey(key)
                    print(f"[OK] Successfully read ShimCache data from {path}")
                    return data
                except FileNotFoundError:
                    continue
                except Exception as e:
                    print(f"[WARNING] Error reading from {path}: {e}")
                    continue
            
            print("[ERROR] Could not find ShimCache data in any control set")
            return None
            
        except Exception as e:
            print(f"[ERROR] Error accessing live registry: {e}")
            return None
    
    def check_duplicate_exists(self, entry: ShimCacheEntry) -> bool:
        """
        Check if an entry already exists in the database.
        
        Args:
            entry (ShimCacheEntry): Entry to check
            
        Returns:
            bool: True if duplicate exists, False otherwise
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT COUNT(*) FROM shimcache_entries WHERE entry_hash = ?",
            (entry.entry_hash,)
        )
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def save_to_database(self, entries: List[ShimCacheEntry]):
        """
        Save parsed entries to SQLite database with duplicate checking.
        
        Args:
            entries (List[ShimCacheEntry]): Entries to save
        """
        if not entries:
            print("[INFO] No entries to save")
            return
        
        conn = sqlite3.connect(self.database_path)
        # Configure SQLite to handle datetime objects properly
        conn.execute("PRAGMA table_info(shimcache_entries)")
        cursor = conn.cursor()
        
        new_entries = 0
        duplicates = 0
        
        print(f"[INFO] Saving {len(entries)} entries to database...")
        
        for entry in entries:
            # Check for duplicates
            if self.check_duplicate_exists(entry):
                duplicates += 1
                continue
            
            # Insert new entry
            try:
                # Format datetime consistently without timezone info and milliseconds
                if entry.last_modified:
                    if entry.last_modified.tzinfo is not None:
                        # Timezone-aware datetime: use strftime to format without timezone
                        last_modified_str = entry.last_modified.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        # Timezone-naive datetime: convert to string and remove milliseconds
                        last_modified_str = str(entry.last_modified).split('.')[0]
                else:
                    last_modified_str = None
                
                cursor.execute('''
                    INSERT INTO shimcache_entries 
                    (filename, path, last_modified, last_modified_readable, data_size, 
                     entry_size, cache_entry_position, entry_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    entry.filename,
                    entry.path,
                    last_modified_str,
                    entry.last_modified_readable,
                    entry.data_size,
                    entry.entry_size,
                    entry.cache_entry_position,
                    entry.entry_hash
                ))
                new_entries += 1
            except sqlite3.IntegrityError:
                duplicates += 1
                continue
        
        conn.commit()
        conn.close()
        
        print(f"[OK] Database update complete:")
        print(f"  [INFO] New entries added: {new_entries}")
        print(f"  [INFO] Duplicates skipped: {duplicates}")
        print(f"  [INFO] Database: {self.database_path}")
    
    def print_summary(self, entries: List[ShimCacheEntry]):
        """
        Print comprehensive summary statistics.
        
        Args:
            entries (List[ShimCacheEntry]): Entries to summarize
        """
        if not entries:
            print("[INFO] No entries found")
            return
        
        total = len(entries)
        
        # File extension analysis
        extensions = {}
        for entry in entries:
            if '.' in entry.filename:
                # Only get extension if it's a reasonable length (avoid malformed paths)
                parts = entry.filename.split('.')
                if len(parts) >= 2:
                    ext = parts[-1].lower()
                    # Only count extensions that look valid (alphanumeric, reasonable length)
                    if ext.isalnum() and len(ext) <= 10:
                        extensions[ext] = extensions.get(ext, 0) + 1
        
        # Time range analysis
        timestamps = [e.last_modified for e in entries if e.last_modified]
        if timestamps:
            oldest = min(timestamps)
            newest = max(timestamps)
        else:
            oldest = newest = None
        
        print(f"\n[SUMMARY] === ShimCache Analysis Summary ===")
        print(f"[INFO] Total entries parsed: {total}")
        print(f"[INFO] Database: {self.database_path}")
        
        if timestamps:
            print(f"[INFO] Time range: {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')}")
        
        print(f"\n[INFO] Top file extensions:")
        for ext, count in sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  .{ext}: {count} files")
    
    def run(self):
        """
        Main execution function with comprehensive error handling.
        """
        print("[INFO] ShimCache Enhanced Parser Starting...")
        print("=" * 50)
        
        try:
            # Get data from live registry
            data = self.get_live_registry_data()
            if not data:
                print("[ERROR] Failed to retrieve ShimCache data")
                return
            
            print(f"[INFO] Retrieved {len(data):,} bytes of ShimCache data")
            
            # Parse the data
            entries = self.parse_shimcache_data(data)
            
            if entries:
                # Process entries (extract filenames, format timestamps)
                print("[INFO] Processing entries...")
                for entry in entries:
                    entry.extract_filename()
                    entry.format_timestamp()
                
                # Save to database
                self.save_to_database(entries)
                
                # Print summary
                self.print_summary(entries)
                
                print(f"\n[SUCCESS] Analysis complete! Check database: {self.database_path}")
                
            else:
                print("[ERROR] No entries were successfully parsed")
                
        except Exception as e:
            print(f"[ERROR] Critical error during execution: {e}")
            import traceback
            traceback.print_exc()

def main():
    """
    Main function with command-line argument support.
    """
    print("ShimCache Enhanced Parser v2.0")
    print("Forensic Analysis Tool for Windows Application Compatibility Cache")
    print("=" * 60)
    
    # Initialize parser
    db_path = "shimcache.db"
    
    parser = ShimCacheParser(db_path)
    parser.run()

if __name__ == "__main__":
    main()
