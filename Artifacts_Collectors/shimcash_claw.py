#!/usr/bin/env python3
"""
Enhanced ShimCache Parser

A comprehensive tool for parsing Windows ShimCache (Application Compatibility Cache) data.
This parser extracts execution artifacts from the Windows registry and stores them in a 
SQLite database for forensic analysis.

Features:
- Parses the Windows 10/11 AppCompatCache format; an older cache is named
  and refused rather than mis-parsed
- Extracts file paths, modification times and cache order
- Decodes packaged (Store/UWP) application records
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
from utils.time_utils import format_forensic_timestamp, filetime_to_datetime

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
    
    # PE machine types seen in a packaged-app cache record. The same constants
    # IMAGE_FILE_MACHINE_* uses, which is what identifies the field.
    MACHINE_TYPES = {
        "8664": "x64",
        "014c": "x86",
        "01c0": "ARM",
        "aa64": "ARM64",
    }

    # The same machine types as integers, for the record's data blob, which
    # stores them as numbers rather than as the hex text a packaged-app record
    # uses. One vocabulary, two encodings.
    MACHINE_BY_VALUE = {
        0x8664: "x64",
        0x014c: "x86",
        0x01c0: "ARM",
        0xaa64: "ARM64",
        0x01c4: "ARMNT",
        0x0200: "IA64",
    }

    # The trailing data blob is an ARRAY OF 12-BYTE SLOTS, not an opaque
    # payload: every blob length on 165 live records was a multiple of 12.
    # Each slot is (tag, type, value) as three little-endian DWORDs.
    SHIM_SLOT_SIZE = 12

    # `type` is a size code. 2 means the value is a PE machine type: 294 of 294
    # type-2 slots held one, and 0 of 509 type-4 slots did.
    SHIM_TYPE_MACHINE = 2

    # Tag meanings, and ONLY the ones the bytes actually established. Each was
    # measured against something read independently of the cache - the PE
    # header on disk, the path, the Authenticode signer:
    #
    #   0x800 / 0x2000  the executable's machine type. Agreed with the PE
    #                   header of the file on disk on 296 of 300 files that
    #                   still exist; the disagreements are files replaced
    #                   since the cache recorded them, which is the artifact
    #                   being right rather than the decode being wrong.
    #                   Both tags always carried the same value.
    #   0x200           present on every record; set on operating-system
    #                   binaries. 164 of 165 against "path under C:\Windows",
    #                   and the single exception is a third-party driver
    #                   package staged in DriverStore - which is not an OS
    #                   binary, so the flag is right and the path is the
    #                   imperfect proxy.
    #
    # The rest are NOT named. Their best correlations sit at 94-97%, close
    # enough to the base rates to be coincidence, and they are recorded by
    # number rather than given a meaning they have not earned:
    #
    #   0x400  96.7% with "declares a Windows 10 or later subsystem version"
    #   0x100  appeared only on binaries declaring subsystem 6.x (20 of 20),
    #          but not on every such binary
    #   0x40   94.6% on the same axis as 0x400
    #   0x20   constant 0; correlates with nothing above its base rate
    SHIM_TAG_MACHINE = (0x800, 0x2000)
    SHIM_TAG_OS_BINARY = 0x200

    def __init__(self):
        self.path = ""
        self.filename = ""
        self.last_modified = None
        self.last_modified_readable = ""
        self.data_size = 0
        self.entry_size = 0
        self.cache_entry_position = 0
        # Ordinal within the cache: 0 is the most recently inserted
        # entry. `cache_entry_position` is a byte offset and answers a
        # different question; the order is the one an analyst reasons
        # about, and it was not recoverable from what was stored.
        self.cache_index = -1
        # The DWORD at record offset 4. Unique on every record measured (165
        # records, 165 distinct values, uniformly distributed) and NOT
        # reproducible from the path or the timestamp by CRC32, Adler32, MD5
        # or SHA-1 - so it is an identifier the cache assigns, not a checksum
        # of the record's own contents. Stored because it was being discarded.
        self.record_id = ""
        # The record's trailing blob, decoded. See apply_shim_data().
        self.shim_flags = ""
        self.entry_hash = ""
        # Packaged (Store/UWP) applications, see classify() below.
        self.entry_type = "file"
        self.package_family_name = ""
        self.package_version = ""
        self.architecture = ""
        self.raw_entry = ""

    def generate_hash(self) -> str:
        """
        Generate MD5 hash of path, timestamp, and metadata for robust duplicate detection.

        Returns:
            str: MD5 hash of the entry
        """
        # Include data_size and position to handle files that might have been
        # executed multiple times but share a timestamp (rare but possible in some OS versions)
        # raw_entry keeps packaged-app records distinct from one another: their
        # path is empty, so without it two entries for the same package would
        # collapse into one hash.
        hash_input = (f"{self.path}_{self.raw_entry}_{self.last_modified}_"
                      f"{self.data_size}_{self.cache_entry_position}_"
                      f"{self.cache_index}").encode('utf-8')
        return hashlib.md5(hash_input).hexdigest()

    def classify(self):
        """Split a packaged-application record out of the path field.

        Not every AppCompatCache entry names a file. Store and UWP applications
        are recorded as seven tab-separated fields instead:

            flags, version, unknown, machine type, package name, publisher id, ''

        Stored whole, that string sat in `path` and `filename` - 209 of 1024
        entries on this machine - so the ShimCache tab showed a packed record
        where a path belongs, and correlation, which keys on filename then path,
        could never match the same program in Amcache or Prefetch.

        Fields 1, 3, 4 and 5 are decoded because each was confirmed against
        Get-AppxPackage on a live machine: 4 and 5 joined with '_' reproduce the
        installed PackageFamilyName exactly, 1 is the package version as four
        big-endian 16-bit values, and 3 is the PE machine type. Field 2 varies
        between entries of one package and is NOT decoded - it stays in
        raw_entry rather than being given a meaning it has not earned.
        """
        # Idempotent: the parse loop classifies each entry and run() classifies
        # again over the whole list. Without this guard the second pass saw an
        # already-emptied path, found no tab, and reset every packaged entry
        # back to "file".
        if self.entry_type == "packaged app":
            return

        if "\t" not in (self.path or ""):
            self.entry_type = "file"
            return

        self.raw_entry = self.path
        fields = self.path.split("\t")
        self.entry_type = "packaged app"
        self.path = ""

        name = fields[4].strip() if len(fields) > 4 else ""
        publisher = fields[5].strip() if len(fields) > 5 else ""
        if name and publisher:
            self.package_family_name = "%s_%s" % (name, publisher)
        elif name:
            self.package_family_name = name
        self.filename = name or "UNKNOWN"

        if len(fields) > 3:
            self.architecture = self.MACHINE_TYPES.get(
                fields[3].strip().lower(), fields[3].strip())

        if len(fields) > 1:
            self.package_version = self._decode_version(fields[1].strip())

    @staticmethod
    def _decode_version(field: str) -> str:
        """Four big-endian 16-bit values as a dotted version, or '' if unreadable.

        `0025007265910000` is 37.114.25969.0 - which Get-AppxPackage reports as
        37.114.26001.0 for the same package, the same major.minor with an older
        build. That is what a record of a past execution should hold.
        """
        if len(field) != 16:
            return ""
        try:
            parts = [int(field[i:i + 4], 16) for i in range(0, 16, 4)]
        except ValueError:
            return ""
        return ".".join(str(p) for p in parts)

    def apply_shim_data(self, blob: bytes) -> int:
        """Decode the record's trailing blob and record what it holds.

        The blob is an array of 12-byte slots, each three little-endian
        DWORDs: tag, type, value. It was previously skipped entirely - only
        its LENGTH was stored - and the website's byte map described it as
        "undocumented, and not decoded by any public parser including this
        one". On 165 live records every blob length was a multiple of 12, and
        the machine type inside agreed with the PE header of the file on disk
        116 times out of 117.

        Two things are pulled out by name because the bytes established them:
        the executable's `architecture`, and an operating-system-binary flag.
        Every other slot is recorded by its tag NUMBER. Their correlations sit
        at 94-97%, close enough to the base rates to be coincidence, and a
        guessed name in an evidence column is worse than an honest number.

        Args:
            blob (bytes): the bytes after `data size`

        Returns:
            int: bytes left over after whole slots - 0 on a well-formed blob
        """
        if not blob:
            return 0

        parts = []
        count = len(blob) // self.SHIM_SLOT_SIZE
        for k in range(count):
            off = k * self.SHIM_SLOT_SIZE
            tag, kind, value = struct.unpack(
                '<III', blob[off:off + self.SHIM_SLOT_SIZE])

            if tag in self.SHIM_TAG_MACHINE and kind == self.SHIM_TYPE_MACHINE:
                # Only set it for a file record. A packaged-app record already
                # carries an architecture decoded from its own fields, and that
                # one is the package's declared architecture - do not overwrite
                # it with the image's.
                arch = self.MACHINE_BY_VALUE.get(value, "0x%X" % value)
                if self.entry_type != "packaged app" and not self.architecture:
                    self.architecture = arch
                # Both tags carry the machine type and always agreed on every
                # record measured, but they are two separate slots - naming
                # each with its tag keeps one part per slot and stops
                # "machine=x64;machine=x64" reading like a duplicate bug.
                parts.append("machine(0x%X)=%s" % (tag, arch))
            elif tag == self.SHIM_TAG_OS_BINARY:
                parts.append("os_binary=%d" % value)
            else:
                parts.append("0x%X=0x%X" % (tag, value))

        self.shim_flags = ";".join(parts)
        return len(blob) - count * self.SHIM_SLOT_SIZE

    def extract_filename(self):
        """Extract filename from full path and handle edge cases."""
        if self.entry_type == "packaged app":
            return          # classify() already set the display name
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
                # Timezone-aware datetime: use format_forensic_timestamp for consistent formatting
                self.last_modified_readable = format_forensic_timestamp(self.last_modified)
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

    # The blob opens with the size of its own header, and that is what
    # identifies the format. Windows 10 and 11 use 0x30 or 0x34. The
    # older layouts announce themselves with a magic instead - XP
    # 0xDEADBEEF, Vista 0xBADC0FFE, Windows 7 0xBADC0FEE - and Windows 8
    # uses a "00ts" record. None of those are parsed here; they are
    # named so an unsupported hive is REPORTED as unsupported instead of
    # being run through the Windows 10 parser, which is what used to
    # happen.
    WINDOWS_10_HEADER_SIZES = (0x30, 0x34)
    KNOWN_OTHER_FORMATS = {
        0xDEADBEEF: 'Windows XP',
        0xBADC0FFE: 'Windows Vista / Server 2008',
        0xBADC0FEE: 'Windows 7 / Server 2008 R2',
        0x00000080: 'Windows 8 / 8.1',
    }
    
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

        # A database written before packaged-app entries were decoded is
        # REBUILT, not migrated. Its rows carry the tab record in `path` and it
        # declares UNIQUE(path, last_modified) - which packaged entries, whose
        # path is now empty, would collide on. SQLite cannot alter a constraint
        # and CREATE TABLE IF NOT EXISTS would silently leave the old one in
        # place, so the table is dropped and re-parsed from the cache, the same
        # way create_correlated_database handles a pre-fix table.
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' "
                       "AND name='shimcache_entries'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(shimcache_entries)")
            existing = [c[1] for c in cursor.fetchall()]
            if "entry_type" not in existing:
                print("[OK] Rebuilding shimcache_entries for the packaged-app schema")
                cursor.execute("DROP TABLE shimcache_entries")
            elif not {"cache_index", "record_id", "shim_flags"}.issubset(
                    existing):
                # Added, NOT rebuilt. The packaged-app case above has to drop
                # because a UNIQUE constraint changed and SQLite cannot alter
                # one; adding a column needs no such thing.
                #
                # The difference matters here more than in most tables:
                # ShimCache ages entries out, so a row a previous parse
                # captured may no longer be anywhere in the cache. Dropping
                # the table to gain a column would destroy that evidence for
                # good. Older rows keep -1 / NULL, which the tab and the
                # knowledge base read as "not recorded" rather than as a
                # position of zero or an empty flag set.
                #
                # Written out one statement at a time on purpose. A list of
                # ("name", "DDL") pairs reads more neatly, but Sentinel's
                # extract-schema.js recognises exactly that shape as a table
                # DEFINITION - Regclaw builds ten of its tables that way - so
                # the pairs below became two phantom tables called `record_id`
                # and `shim_flags` in the fleet schema, and the gate failed in
                # a different repository than the one edited.
                if "cache_index" not in existing:
                    print("[OK] Adding cache_index to shimcache_entries")
                    cursor.execute("ALTER TABLE shimcache_entries "
                                   "ADD COLUMN cache_index INTEGER DEFAULT -1")
                if "record_id" not in existing:
                    print("[OK] Adding record_id to shimcache_entries")
                    cursor.execute("ALTER TABLE shimcache_entries "
                                   "ADD COLUMN record_id TEXT")
                if "shim_flags" not in existing:
                    print("[OK] Adding shim_flags to shimcache_entries")
                    cursor.execute("ALTER TABLE shimcache_entries "
                                   "ADD COLUMN shim_flags TEXT")

        # Create main table with improved schema.
        #
        # entry_hash is the single dedup key. It is built from path, raw_entry,
        # timestamp, size and cache position, so it distinguishes every entry -
        # including packaged apps, which share an empty path. The old
        # UNIQUE(path, last_modified) is gone because it cannot: 209 entries
        # with no path would collide with each other.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shimcache_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                entry_type TEXT DEFAULT 'file',
                package_family_name TEXT,
                package_version TEXT,
                architecture TEXT,
                raw_entry TEXT,
                last_modified TEXT,
                last_modified_readable TEXT,
                data_size INTEGER DEFAULT 0,
                entry_size INTEGER DEFAULT 0,
                cache_entry_position INTEGER DEFAULT 0,
                cache_index INTEGER DEFAULT -1,
                record_id TEXT,
                shim_flags TEXT,
                entry_hash TEXT UNIQUE,
                parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create indexes for faster searches and duplicate detection
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_path ON shimcache_entries(path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON shimcache_entries(filename)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_modified ON shimcache_entries(last_modified)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_entry_hash ON shimcache_entries(entry_hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_package_family ON shimcache_entries(package_family_name)')

        conn.commit()
        conn.close()
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
            return filetime_to_datetime(filetime)
        except (ValueError, OSError, OverflowError) as e:
            print(f"Warning: Invalid FILETIME value {filetime}: {e}")
            return None    
    def detect_windows_version(self, data: bytes) -> str:
        """Identify the cache format from its header.

        The blob opens with the size of its own header, and that is the
        discriminator. This used to scan the first 150 bytes for the "10ts"
        signature and otherwise test for b'\x30\x00\x00\x00' - the integer 48 -
        as a "Windows 7 pattern", which matches almost any blob; an
        unrecognised format then fell through to Windows 10 parsing anyway.

        Args:
            data (bytes): Raw ShimCache data

        Returns:
            str: "Windows 10/11", a named older format, or "Unknown"
        """
        if len(data) < 8:
            return "Unknown"

        header_size = struct.unpack('<I', data[0:4])[0]

        if header_size in self.WINDOWS_10_HEADER_SIZES:
            # Confirm: the first record must sit right after the header.
            if data[header_size:header_size + 4] == b'10ts':
                return "Windows 10/11"
            return "Unknown"

        named = self.KNOWN_OTHER_FORMATS.get(header_size)
        if named:
            return named

        return "Unknown"

    def parse_windows_10_11(self, data: bytes) -> List[ShimCacheEntry]:
        """
        Parse the Windows 10/11 ShimCache format.

        Each record, confirmed against a live AppCompatCache value:

            "10ts" | unknown(4) | cell size(4) | path size(2) | path
                   | FILETIME(8) | data size(4) | data blob

        `cell size` counts the bytes from just after itself to the end of the
        record, so it is what steps to the next entry. The previous version
        scanned forward for "10ts" one byte at a time instead, and read
        `data size` as 2 bytes where the format has 4 - the scan silently
        absorbed the resulting two-byte drift, so the output looked correct
        while the walk was guessing at every boundary. A "10ts" sequence
        occurring inside a path or a data blob would have started a phantom
        entry.

        Args:
            data (bytes): Raw ShimCache data

        Returns:
            List[ShimCacheEntry]: Parsed cache entries, in cache order
        """
        entries = []
        header_size = struct.unpack('<I', data[0:4])[0]
        index = header_size if header_size in self.WINDOWS_10_HEADER_SIZES else 52
        resyncs = 0
        # Blobs whose length is not a whole number of 12-byte slots. Counted
        # and reported rather than quietly truncated: it would mean the slot
        # size is wrong, or that this build writes something else there.
        ragged = 0

        print("[STATS] Parsing Windows 10/11 format...")

        while index + 14 <= len(data):
            if data[index:index + 4] != b'10ts':
                # Lost alignment. Recover, but say so: from here the entry
                # count is a guess, not a reading of the structure.
                nxt = data.find(b'10ts', index + 1)
                if nxt == -1:
                    break
                resyncs += 1
                index = nxt
                continue

            start = index
            try:
                cell_size = struct.unpack('<I', data[index + 8:index + 12])[0]
                path_size = struct.unpack('<H', data[index + 12:index + 14])[0]

                cursor = index + 14
                if cursor + path_size > len(data):
                    break
                entry = ShimCacheEntry()
                entry.cache_entry_position = start
                entry.cache_index = len(entries)
                entry.entry_size = cell_size
                # The DWORD at offset 4 - unique per record, and previously
                # read past without being stored.
                entry.record_id = "0x%08X" % struct.unpack(
                    '<I', data[index + 4:index + 8])[0]
                entry.path = data[cursor:cursor + path_size].decode(
                    'utf-16le', errors='ignore').rstrip('\x00')
                cursor += path_size

                if cursor + 12 > len(data):
                    break
                filetime = struct.unpack('<Q', data[cursor:cursor + 8])[0]
                entry.last_modified = self.filetime_to_datetime(filetime)
                entry.format_timestamp()
                cursor += 8

                # 4 bytes, not 2. Reading a USHORT here left the cursor two
                # bytes short of the data blob on every single entry.
                entry.data_size = struct.unpack('<I', data[cursor:cursor + 4])[0]
                cursor += 4
                blob = data[cursor:cursor + entry.data_size]
                cursor += entry.data_size

                # Split a packaged-app record out of `path` before anything
                # downstream treats that field as a filesystem path.
                entry.classify()
                entry.extract_filename()

                # Decode the trailing blob AFTER classify(), which is what
                # decides whether the architecture slot may set `architecture`
                # - a packaged app already has one from its own fields.
                odd = entry.apply_shim_data(blob)
                if odd:
                    ragged += 1
                entry.entry_hash = entry.generate_hash()

                entries.append(entry)

                # Step by the record's own length; fall back to where the
                # fields landed if the cell size is not usable.
                stride = start + 12 + cell_size
                index = stride if stride > start else cursor

                if len(entries) % 100 == 0:
                    print(f"  [NOTE] Parsed {len(entries)} entries...")

            except (struct.error, UnicodeDecodeError, IndexError) as e:
                print(f"[WARN] Error parsing entry at offset {start}: {e}")
                nxt = data.find(b'10ts', start + 1)
                if nxt == -1:
                    break
                resyncs += 1
                index = nxt

        leftover = len(data) - index
        print(f"[OK] Successfully parsed {len(entries)} Windows 10/11 entries")
        if resyncs:
            print(f"[WARN] Lost alignment {resyncs} time(s) - the entry count "
                  f"is a recovery, not a clean read of the structure")
        if leftover > 0:
            print(f"[WARN] {leftover} trailing byte(s) not accounted for")
        if ragged:
            print(f"[WARN] {ragged} record(s) have a data blob that is not a "
                  f"whole number of 12-byte slots - the trailing bytes were "
                  f"not decoded")
        return entries

    def parse_shimcache_data(self, data: bytes) -> List[ShimCacheEntry]:
        """
        Identify the format and parse it, or refuse it.

        Only Windows 10/11 is parsed. An older cache is NAMED and returns no
        entries; it used to be handed to the Windows 10 parser regardless,
        which returned whatever a byte scan happened to find in a layout it
        does not understand.

        Args:
            data (bytes): Raw ShimCache data from the registry

        Returns:
            List[ShimCacheEntry]: All parsed cache entries
        """
        if not data or len(data) < 20:
            print("[FAIL] Invalid or empty ShimCache data")
            return []

        version = self.detect_windows_version(data)
        print(f"[SCAN] Detected cache format: {version}")

        if version == "Windows 10/11":
            return self.parse_windows_10_11(data)

        print(f"[FAIL] {version} ShimCache is not supported by this parser - "
              f"no entries read. Supported: Windows 10/11 "
              f"(header size 0x30 or 0x34).")
        return []

    def get_live_registry_data(self) -> List[bytes]:
        """Read the AppCompatCache value from every control set.

        Returns a list because a machine can carry more than one: the older
        set holds the cache as it stood at an earlier boot, and its entries
        need not be in the current one.

        This used to return on the FIRST key that opened, so only
        CurrentControlSet was ever read - while the offline parser
        (`offline_ShimCacheClaw.get_offline_registry_data`) enumerated every
        ControlSet and merged them. Same artifact, two different answers
        depending on which path an analyst took.

        CurrentControlSet is normally a link to one of the numbered sets, so
        identical blobs are collapsed rather than parsed twice.

        Returns:
            list[bytes]: one blob per distinct control set, [] if none
        """
        if not LIVE_REGISTRY_AVAILABLE:
            print("[FAIL] Live registry access not available on this platform")
            return []

        registry_paths = [
            r"SYSTEM\CurrentControlSet\Control\Session Manager\AppCompatCache",
            r"SYSTEM\ControlSet001\Control\Session Manager\AppCompatCache",
            r"SYSTEM\ControlSet002\Control\Session Manager\AppCompatCache",
            r"SYSTEM\ControlSet003\Control\Session Manager\AppCompatCache",
        ]

        blobs = []
        seen = set()
        for path in registry_paths:
            try:
                key = OpenKey(HKEY_LOCAL_MACHINE, path)
                data, _ = QueryValueEx(key, "AppCompatCache")
                CloseKey(key)
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"[WARN] Error reading from {path}: {e}")
                continue

            data = bytes(data)
            digest = hashlib.md5(data).hexdigest()
            if digest in seen:
                print(f"[OK] {path} is identical to a set already read")
                continue
            seen.add(digest)
            blobs.append(data)
            print(f"[OK] Read {len(data):,} bytes of ShimCache data from {path}")

        if not blobs:
            print("[FAIL] Could not find ShimCache data in any control set")
        return blobs

    def check_duplicate_exists(self, entry: ShimCacheEntry, cursor=None) -> bool:
        """
        Check if an entry already exists in the database.

        Pass a cursor when one is already open. Without it this opens and
        closes its own connection, which is fine for a single lookup and ruinous
        in a loop - see the note in save_to_database.

        Args:
            entry (ShimCacheEntry): Entry to check
            cursor: an open sqlite3 cursor to reuse, or None

        Returns:
            bool: True if duplicate exists, False otherwise
        """
        if cursor is not None:
            cursor.execute(
                "SELECT 1 FROM shimcache_entries WHERE entry_hash = ? LIMIT 1",
                (entry.entry_hash,))
            return cursor.fetchone() is not None

        conn = sqlite3.connect(self.database_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM shimcache_entries WHERE entry_hash = ? LIMIT 1",
                (entry.entry_hash,)).fetchone()
        finally:
            conn.close()
        return row is not None
    
    def save_to_database(self, entries: List[ShimCacheEntry]):
        """
        Save parsed entries to SQLite database with duplicate checking.
        
        Args:
            entries (List[ShimCacheEntry]): Entries to save
        """
        if not entries:
            print("[NOTE] No entries to save")
            return
        
        conn = sqlite3.connect(self.database_path)
        # Configure SQLite to handle datetime objects properly
        conn.execute("PRAGMA table_info(shimcache_entries)")
        cursor = conn.cursor()
        
        new_entries = 0
        duplicates = 0
        
        print(f"[SAVE] Saving {len(entries)} entries to database...")
        
        # Every hash already stored, read ONCE.
        #
        # This loop used to call check_duplicate_exists per entry, and that
        # opened and closed a fresh sqlite3 connection every time - 1,024 file
        # opens for a full cache, each one a separate open/read-header/close
        # that real-time antivirus inspects. It measured 0.4s on a warm SSD
        # here and is the kind of cost that becomes tens of seconds on a slower
        # disk, a synced case folder, or a machine with aggressive AV. One
        # query replaces all of them.
        #
        # The IntegrityError branch below stays: entry_hash is UNIQUE, and it
        # is what catches a duplicate appearing twice within THIS batch, which
        # a snapshot taken before the loop cannot see.
        known = {h for (h,) in cursor.execute(
            "SELECT entry_hash FROM shimcache_entries")}

        for entry in entries:
            # Check for duplicates
            if entry.entry_hash in known:
                duplicates += 1
                continue
            
            # Insert new entry
            try:
                # Format datetime consistently without timezone info and milliseconds
                if entry.last_modified:
                    if entry.last_modified.tzinfo is not None:
                        # Timezone-aware datetime: use format_forensic_timestamp for consistent formatting
                        last_modified_str = format_forensic_timestamp(entry.last_modified)
                    else:
                        # Timezone-naive datetime: convert to string and remove milliseconds
                        last_modified_str = str(entry.last_modified).split('.')[0]
                else:
                    last_modified_str = None
                
                cursor.execute('''
                    INSERT INTO shimcache_entries 
                    (filename, path, entry_type, package_family_name, package_version,
                     architecture, raw_entry, last_modified, last_modified_readable,
                     data_size, entry_size, cache_entry_position, cache_index,
                     record_id, shim_flags, entry_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    entry.filename,
                    entry.path,
                    entry.entry_type,
                    entry.package_family_name,
                    entry.package_version,
                    entry.architecture,
                    entry.raw_entry,
                    last_modified_str,
                    entry.last_modified_readable,
                    entry.data_size,
                    entry.entry_size,
                    entry.cache_entry_position,
                    entry.cache_index,
                    entry.record_id,
                    entry.shim_flags,
                    entry.entry_hash
                ))
                known.add(entry.entry_hash)
                new_entries += 1
            except sqlite3.IntegrityError:
                duplicates += 1
                continue
        
        conn.commit()
        conn.close()
        
        print(f"[OK] Database update complete:")
        print(f"  [NOTE] New entries added: {new_entries}")
        print(f"  [SYNC] Duplicates skipped: {duplicates}")
        print(f"  [SAVE] Database: {self.database_path}")
    
    def print_summary(self, entries: List[ShimCacheEntry]):
        """
        Print comprehensive summary statistics.
        
        Args:
            entries (List[ShimCacheEntry]): Entries to summarize
        """
        if not entries:
            print("[STATS] No entries found")
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
        
        print(f"\n[TARGET] === ShimCache Analysis Summary ===")
        print(f"[STATS] Total entries parsed: {total}")
        print(f"[SAVE] Database: {self.database_path}")
        
        if timestamps:
            print(f"[DATE] Time range: {format_forensic_timestamp(oldest).split(' ')[0]} to {format_forensic_timestamp(newest).split(' ')[0]}")
        
        print(f"\n[TOOL] Top file extensions:")
        for ext, count in sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  .{ext}: {count} files")
    
    def run(self):
        """
        Main execution function with comprehensive error handling.
        """
        print("[START] ShimCache Enhanced Parser Starting...")
        print("=" * 50)
        
        try:
            # Get data from every control set on the live registry
            blobs = self.get_live_registry_data()
            if not blobs:
                print("[FAIL] Failed to retrieve ShimCache data")
                return
            
            print(f"[STATS] Retrieved {len(blobs)} distinct control set(s)")

            # Parse each control set. entry_hash dedups on save, so a program
            # present in two sets is stored once.
            entries = []
            for blob in blobs:
                print(f"[STATS] Parsing {len(blob):,} bytes...")
                entries.extend(self.parse_shimcache_data(blob))

            if entries:
                # Process entries (extract filenames, format timestamps)
                print("[SYNC] Processing entries...")
                for entry in entries:
                    entry.classify()
                    entry.extract_filename()
                    entry.format_timestamp()
                
                # Save to database
                self.save_to_database(entries)
                
                # Print summary
                self.print_summary(entries)
                
                print(f"\n[OK] Analysis complete! Check database: {self.database_path}")
                
            else:
                print("[FAIL] No entries were successfully parsed")
                
        except Exception as e:
            print(f"[FAIL] Critical error during execution: {e}")
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