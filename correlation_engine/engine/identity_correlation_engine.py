"""
Identity Correlation Engine
Implements identity-based correlation with temporal anchor clustering.

This module provides the core identity correlation functionality:
- Identity extraction from forensic records
- Identity key normalization
- Identity matching strategies
- Temporal anchor clustering
- Primary/secondary/supporting evidence classification
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass

from .data_structures import Identity, Anchor, EvidenceRow, CorrelationResults, CorrelationStatistics


class IdentityCorrelationEngine:
    """
    Core engine for identity-based correlation.
    
    Implements identity-first clustering followed by temporal anchor creation.
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize identity correlation engine.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.identity_index: Dict[str, Identity] = {}  # Hash index for O(1) lookup
        
        # Common field name variations for identity extraction
        # ENHANCED: More comprehensive field patterns for better identity extraction
        self.name_field_patterns = [
            # Primary application/executable names
            'executable_name',      # Prefetch: AESM_SERVICE.EXE
            'app_name',             # SRUM: System, chrome.exe
            'application',          # LastSaveMRU: Sourcetrail.exe
            'name',                 # InventoryApplication: Microsoft.Windows.PrintQueueActionCenter
            'file_name',            # ShellBags, MFT: fn_filename
            'fn_filename',          # MFT: $MFT, file.exe
            'filename',             # Prefetch, ShimCache
            'Source_Name',          # LNK/Jumplist: WinRAR.lnk
            'original_filename',    # RecycleBin: MFT_Claw.py
            'program_name',         # AutoStartPrograms: SecurityHealth
            'display_name',         # InstalledSoftware: 7-Zip 23.01 (x64)
            'product_name',         # InventoryApplicationFile: microsoft® windows® operating system
            'Source',               # Event Logs: Microsoft-Windows-Security-Auditing
            # AmCache specific
            'FileName', 'Name', 'ProductName', 'FileDescription',
            'OriginalFileName', 'InternalName', 'CompanyName',
            # UserAssist specific
            'value', 'Value', 'entry_name', 'program',
            # BAM/DAM specific
            'executable', 'Executable', 'app', 'App',
            # Services specific
            'service_name', 'ServiceName', 'ImagePath',
            # Tasks specific
            'task_name', 'TaskName', 'action_path',
            # Network specific
            'process', 'Process', 'application_name',
            # Generic fallbacks
            'process_name', 'program', 'binary', 'command', 'target_name',
            'exe', 'Exe', 'module', 'Module', 'image', 'Image'
        ]
        
        self.path_field_patterns = [
            # Primary path fields
            'app_path',             # SRUM: System, C:\Program Files\...
            'Local_Path',           # LNK/Jumplist: C:\Program Files (x86)\WinRAR\WinRAR.exe
            'path',                 # ShimCache, generic
            'file_path',            # OpenSaveMRU: Cases\20 Dec\Correlation\wings\test 2 Dec 20.json
            'original_path',        # RecycleBin: C:\Crow-Eye-Crow-Eye\...
            'reconstructed_path',   # MFT: [Unknown], C:\Windows\...
            'lower_case_long_path', # InventoryApplicationFile: c:\program files (x86)\...
            'install_location',     # InstalledSoftware: C:\Program Files\7-Zip\
            'root_dir_path',        # InventoryApplication: C:\Windows\SystemApps\...
            'ShortcutTargetPath',   # InventoryApplicationShortcut: C:\Program Files (x86)\7-Zip\7zFM.exe
            'Source_Path',          # LNK/Jumplist: C:\Users\...\AppData\Roaming\...
            'folder_path',          # LastSaveMRU: Crow-Eye-master2\Crow-Eye-master
            'registry_path',        # ShellBags: Software\Classes\Local Settings\...
            # AmCache specific
            'FullPath', 'Path', 'FilePath', 'LowerCaseLongPath',
            'LinkDate', 'BinaryType',
            # UserAssist specific
            'focus_path', 'run_path',
            # BAM/DAM specific
            'ExecutablePath', 'executable_path',
            # Services specific
            'image_path', 'ImagePath', 'binary_path', 'BinaryPath',
            # Tasks specific
            'action_arguments', 'working_directory',
            # Network specific
            'remote_address', 'local_address',
            # Generic fallbacks
            'full_path', 'executable_path', 'application_path', 'binary_path',
            'program_path', 'command_line', 'image_path', 'exe_path', 'exepath',
            'target_path', 'TargetPath', 'destination', 'Destination',
            'location', 'Location', 'directory', 'Directory'
        ]
        
        self.hash_field_patterns = [
            'hash',                 # Prefetch: D648B59E
            'entry_hash',           # ShimCache: b376b1d9843f2a458ceb5fdbde1360e6
            'md5', 'sha1', 'sha256', 'file_hash', 'executable_hash',
            'sha256_hash', 'md5_hash', 'sha1_hash',
            # AmCache specific
            'SHA1', 'SHA256', 'MD5', 'FileId', 'ProgramId',
            'Hash', 'Sha1', 'Sha256', 'Md5',
            # PE specific
            'pe_hash', 'imphash', 'ImpHash', 'authenticode_hash'
        ]
        
        # Timestamp field patterns for evidence extraction
        # ENHANCED: More timestamp fields for better temporal correlation
        self.timestamp_field_patterns = [
            'timestamp',            # SRUM: 2025-10-22T08:19:00
            'last_executed',        # Prefetch: 2025-12-21 04:37:18
            'EventTimestampUTC',    # Event Logs: 2025-12-21 07:35:53
            'Time_Access',          # LNK/Jumplist: 2025-12-15 18:36:30
            'Time_Creation',        # LNK/Jumplist: 2025-12-14 23:22:04
            'Time_Modification',    # LNK/Jumplist: 2025-12-15 18:13:28
            'deletion_time',        # RecycleBin: 2025-09-30T23:11:44.990000
            'si_creation_time',     # MFT
            'si_modification_time', # MFT
            'usn_timestamp',        # MFT/USN
            'created_date',         # ShellBags
            'modified_date',        # ShellBags
            'accessed_date',        # ShellBags
            'access_date',          # OpenSaveMRU, LastSaveMRU
            'install_date',         # InstalledSoftware, InventoryApplication
            'last_modified',        # ShimCache
            'parsed_at',            # InventoryApplication
            'created_on',           # Prefetch
            'modified_on',          # Prefetch
            'accessed_on',          # Prefetch
            # AmCache specific
            'FileKeyLastWriteTimestamp', 'LinkDate', 'LastModified',
            'LastModified2', 'CompileTime', 'Created', 'Modified',
            # UserAssist specific
            'last_run', 'LastRun', 'last_execution', 'LastExecution',
            'focus_time', 'FocusTime', 'run_counter',
            # BAM/DAM specific
            'execution_time', 'ExecutionTime',
            # Services specific
            'start_time', 'StartTime', 'stop_time', 'StopTime',
            # Tasks specific
            'last_run_time', 'LastRunTime', 'next_run_time',
            # Network specific
            'connection_time', 'ConnectionTime',
            # Generic
            'datetime', 'DateTime', 'date', 'Date', 'time', 'Time',
            'created', 'modified', 'accessed', 'executed',
            'CreatedDate', 'ModifiedDate', 'AccessedDate',
            'creation_time', 'modification_time', 'access_time'
        ]
        
        # Artifact-specific field mappings (checked FIRST before generic patterns)
        # ENHANCED: More comprehensive mappings for each artifact type
        self.artifact_field_mappings = {
            'Prefetch': {
                'name': ['executable_name', 'filename', 'name', 'FileName'],
                'path': ['path', 'file_path', 'Path', 'FilePath'],
                'hash': ['hash', 'prefetch_hash', 'Hash']
            },
            'SRUM': {
                'name': ['app_name', 'application', 'ExeInfo', 'AppId', 'ApplicationName'],
                'path': ['app_path', 'ExePath', 'AppPath', 'ApplicationPath'],
                'hash': []
            },
            'EventLogs': {
                'name': ['Source', 'Provider', 'ProviderName', 'source_name', 'Channel', 'EventSource'],
                'path': ['ProcessName', 'Image', 'CommandLine', 'TargetFilename', 'NewProcessName', 'ParentProcessName'],
                'hash': ['Hashes', 'FileHash']
            },
            'Event Logs': {
                'name': ['Source', 'Provider', 'ProviderName', 'source_name', 'Channel', 'EventSource'],
                'path': ['ProcessName', 'Image', 'CommandLine', 'TargetFilename', 'NewProcessName', 'ParentProcessName'],
                'hash': ['Hashes', 'FileHash']
            },
            'LNK': {
                'name': ['Source_Name', 'name', 'filename', 'lnk_name', 'SourceName', 'LinkName'],
                'path': ['Local_Path', 'Source_Path', 'target_path', 'TargetPath', 'LocalPath', 'SourcePath'],
                'hash': []
            },
            'Jumplist': {
                'name': ['Source_Name', 'name', 'filename', 'AppId', 'SourceName', 'ApplicationName'],
                'path': ['Local_Path', 'Source_Path', 'target_path', 'TargetPath', 'LocalPath'],
                'hash': []
            },
            'Jumplists': {
                'name': ['Source_Name', 'name', 'filename', 'AppId', 'SourceName', 'ApplicationName'],
                'path': ['Local_Path', 'Source_Path', 'target_path', 'TargetPath', 'LocalPath'],
                'hash': []
            },
            'MFT': {
                'name': ['fn_filename', 'file_name', 'filename', 'name', 'FileName', 'Name'],
                'path': ['reconstructed_path', 'full_path', 'path', 'parent_path', 'FullPath', 'ParentPath'],
                'hash': ['entry_hash', 'hash', 'Hash']
            },
            # MFT_USN specific - correlated MFT and USN data
            'MFT_USN': {
                'name': ['fn_filename', 'file_name', 'filename', 'name', 'FileName', 'Name'],
                'path': ['reconstructed_path', 'full_path', 'path', 'parent_path', 'FullPath', 'ParentPath'],
                'hash': []
            },
            'ShimCache': {
                'name': ['filename', 'name', 'file_name', 'Path', 'FileName', 'Name'],
                'path': ['path', 'file_path', 'full_path', 'Path', 'FilePath', 'FullPath'],
                'hash': ['entry_hash', 'hash', 'Hash']
            },
            'AmCache': {
                'name': ['name', 'filename', 'file_name', 'FileName', 'Name', 'ProductName', 
                         'FileDescription', 'OriginalFileName', 'InternalName'],
                'path': ['path', 'file_path', 'full_path', 'FullPath', 'Path', 'FilePath',
                         'LowerCaseLongPath', 'lower_case_long_path'],
                'hash': ['sha1', 'sha256', 'hash', 'FileId', 'SHA1', 'SHA256', 'Hash', 'ProgramId']
            },
            'Registry': {
                'name': ['value_name', 'key_name', 'name', 'ValueName', 'KeyName', 'Name', 'value', 'Value'],
                'path': ['registry_path', 'key_path', 'path', 'KeyPath', 'RegistryPath', 'Path'],
                'hash': []
            },
            'RecycleBin': {
                'name': ['original_filename', 'filename', 'name', 'FileName', 'OriginalFileName', 'Name'],
                'path': ['original_path', 'path', 'OriginalPath', 'Path'],
                'hash': []
            },
            'ShellBags': {
                'name': ['file_name', 'name', 'folder_name', 'value', 'FileName', 'Name', 'FolderName', 'Value'],
                'path': ['path', 'folder_path', 'registry_path', 'abs_path', 'Path', 'FolderPath', 'AbsPath'],
                'hash': []
            },
            'Browser': {
                'name': ['title', 'name', 'url', 'Title', 'Name', 'URL', 'PageTitle'],
                'path': ['url', 'path', 'URL', 'Path', 'VisitedURL'],
                'hash': []
            },
            'BrowserHistory': {
                'name': ['title', 'name', 'url', 'Title', 'Name', 'URL', 'PageTitle'],
                'path': ['url', 'path', 'URL', 'Path', 'VisitedURL'],
                'hash': []
            },
            'USN': {
                'name': ['filename', 'file_name', 'name', 'FileName', 'Name'],
                'path': ['path', 'full_path', 'parent_path', 'Path', 'FullPath', 'ParentPath'],
                'hash': []
            },
            # NEW: UserAssist artifact
            'UserAssist': {
                'name': ['value', 'Value', 'name', 'Name', 'program', 'Program', 'entry_name'],
                'path': ['path', 'Path', 'focus_path', 'run_path'],
                'hash': []
            },
            'userassist': {
                'name': ['value', 'Value', 'name', 'Name', 'program', 'Program', 'entry_name'],
                'path': ['path', 'Path', 'focus_path', 'run_path'],
                'hash': []
            },
            # NEW: BAM/DAM artifact
            'BAM': {
                'name': ['executable', 'Executable', 'name', 'Name', 'app', 'App'],
                'path': ['path', 'Path', 'executable_path', 'ExecutablePath'],
                'hash': []
            },
            'DAM': {
                'name': ['executable', 'Executable', 'name', 'Name', 'app', 'App'],
                'path': ['path', 'Path', 'executable_path', 'ExecutablePath'],
                'hash': []
            },
            # NEW: Services artifact
            'Services': {
                'name': ['service_name', 'ServiceName', 'name', 'Name', 'display_name', 'DisplayName'],
                'path': ['image_path', 'ImagePath', 'path', 'Path', 'binary_path', 'BinaryPath'],
                'hash': []
            },
            # NEW: Tasks artifact
            'Tasks': {
                'name': ['task_name', 'TaskName', 'name', 'Name'],
                'path': ['action_path', 'ActionPath', 'path', 'Path', 'working_directory'],
                'hash': []
            },
            'ScheduledTasks': {
                'name': ['task_name', 'TaskName', 'name', 'Name'],
                'path': ['action_path', 'ActionPath', 'path', 'Path', 'working_directory'],
                'hash': []
            },
            # NEW: Network connections
            'Network': {
                'name': ['process', 'Process', 'application', 'Application', 'name', 'Name'],
                'path': ['path', 'Path', 'process_path', 'ProcessPath'],
                'hash': []
            },
            # NEW: TypedPaths/TypedURLs
            'TypedPaths': {
                'name': ['value', 'Value', 'name', 'Name', 'path', 'Path'],
                'path': ['value', 'Value', 'path', 'Path'],
                'hash': []
            },
            'typedpaths': {
                'name': ['value', 'Value', 'name', 'Name', 'path', 'Path'],
                'path': ['value', 'Value', 'path', 'Path'],
                'hash': []
            },
            # NEW: Run keys
            'RunKeys': {
                'name': ['name', 'Name', 'value_name', 'ValueName'],
                'path': ['value', 'Value', 'path', 'Path', 'data', 'Data'],
                'hash': []
            },
            # NEW: Installed Programs
            'InstalledPrograms': {
                'name': ['name', 'Name', 'display_name', 'DisplayName', 'product_name', 'ProductName'],
                'path': ['install_location', 'InstallLocation', 'path', 'Path'],
                'hash': []
            },
            # NEW: AppCompat
            'AppCompat': {
                'name': ['name', 'Name', 'filename', 'FileName'],
                'path': ['path', 'Path', 'full_path', 'FullPath'],
                'hash': ['sha1', 'SHA1', 'hash', 'Hash']
            }
        }
    
    def normalize_identity_key(self, name: str = "", path: str = "", hash_value: str = "") -> str:
        """
        Normalize identity information into a composite key.
        
        Implements case-insensitive normalization and path standardization
        for consistent identity matching.
        
        Args:
            name: Application or file name
            path: File path
            hash_value: File hash (MD5, SHA1, SHA256)
        
        Returns:
            Normalized composite key in format: "name|path|hash"
        
        Requirements: 1.2, 5.1
        """
        # Normalize name: lowercase, strip whitespace
        normalized_name = name.lower().strip() if name else ""
        
        # Normalize path: forward slashes, lowercase, strip whitespace
        normalized_path = ""
        if path:
            normalized_path = path.replace("\\", "/").lower().strip()
            # Remove trailing slashes
            normalized_path = normalized_path.rstrip("/")
        
        # Normalize hash: lowercase, strip whitespace
        normalized_hash = hash_value.lower().strip() if hash_value else ""
        
        # Create composite key
        # Use pipe separator to avoid conflicts with path separators
        composite_key = f"{normalized_name}|{normalized_path}|{normalized_hash}"
        
        if self.debug_mode:
            print(f"[DEBUG] Normalized identity: name='{normalized_name}', path='{normalized_path}', hash='{normalized_hash}'")
        
        return composite_key
    
    def extract_identity_info(self, record: Dict[str, Any]) -> Tuple[str, str, str, str]:
        """
        Extract identity information from a forensic record.
        
        IMPROVED: Uses artifact-specific field mappings first, then falls back
        to case-insensitive generic pattern matching.
        
        Handles different field naming conventions across artifact types.
        Detects identity type based on available fields.
        
        Args:
            record: Forensic record dictionary
        
        Returns:
            Tuple of (name, path, hash, identity_type)
            identity_type is one of: "name", "path", "hash", "composite"
        
        Requirements: 1.1, 1.2
        """
        name = ""
        path = ""
        hash_value = ""
        
        # Get artifact type from record (normalize spaces and case variations)
        artifact_type = record.get('artifact', '')
        artifact_type_normalized = artifact_type.replace(' ', '')
        
        # Build lowercase key map for case-insensitive lookup
        record_keys_lower = {k.lower(): k for k in record.keys()}
        
        # STEP 1: Try artifact-specific field mappings FIRST
        if artifact_type_normalized in self.artifact_field_mappings:
            mapping = self.artifact_field_mappings[artifact_type_normalized]
            
            # Extract name using artifact-specific fields
            for field in mapping.get('name', []):
                # Try exact match first
                if field in record and record[field]:
                    name = str(record[field])
                    break
                # Try case-insensitive match
                if field.lower() in record_keys_lower:
                    actual_key = record_keys_lower[field.lower()]
                    if record.get(actual_key):
                        name = str(record[actual_key])
                        break
            
            # Extract path using artifact-specific fields
            for field in mapping.get('path', []):
                if field in record and record[field]:
                    path = str(record[field])
                    break
                if field.lower() in record_keys_lower:
                    actual_key = record_keys_lower[field.lower()]
                    if record.get(actual_key):
                        path = str(record[actual_key])
                        break
            
            # Extract hash using artifact-specific fields
            for field in mapping.get('hash', []):
                if field in record and record[field]:
                    hash_value = str(record[field])
                    break
                if field.lower() in record_keys_lower:
                    actual_key = record_keys_lower[field.lower()]
                    if record.get(actual_key):
                        hash_value = str(record[actual_key])
                        break
        
        # STEP 2: Fall back to generic patterns with case-insensitive matching
        if not name:
            for field_pattern in self.name_field_patterns:
                # Try exact match
                if field_pattern in record and record[field_pattern]:
                    name = str(record[field_pattern])
                    break
                # Try case-insensitive match
                if field_pattern.lower() in record_keys_lower:
                    actual_key = record_keys_lower[field_pattern.lower()]
                    if record.get(actual_key):
                        name = str(record[actual_key])
                        break
        
        if not path:
            for field_pattern in self.path_field_patterns:
                if field_pattern in record and record[field_pattern]:
                    path = str(record[field_pattern])
                    break
                if field_pattern.lower() in record_keys_lower:
                    actual_key = record_keys_lower[field_pattern.lower()]
                    if record.get(actual_key):
                        path = str(record[actual_key])
                        break
        
        if not hash_value:
            for field_pattern in self.hash_field_patterns:
                if field_pattern in record and record[field_pattern]:
                    hash_value = str(record[field_pattern])
                    break
                if field_pattern.lower() in record_keys_lower:
                    actual_key = record_keys_lower[field_pattern.lower()]
                    if record.get(actual_key):
                        hash_value = str(record[actual_key])
                        break
        
        # STEP 3: Smart field discovery - look for fields containing key terms
        if not name:
            name = self._smart_field_discovery(record, record_keys_lower, 'name')
        
        if not path:
            path = self._smart_field_discovery(record, record_keys_lower, 'path')
        
        # STEP 4: Extract name from path if we have path but no name
        if path and not name:
            name = self._extract_name_from_path(path)
        
        # Determine identity type based on available fields
        identity_type = self._determine_identity_type(name, path, hash_value)
        
        if self.debug_mode:
            print(f"[DEBUG] Extracted identity: name='{name}', path='{path}', hash='{hash_value}', type='{identity_type}' (artifact={artifact_type})")
        
        return name, path, hash_value, identity_type
    
    def _smart_field_discovery(self, record: Dict[str, Any], record_keys_lower: Dict[str, str], field_type: str) -> str:
        """
        Smart field discovery - find fields by analyzing field names for key terms.
        
        Args:
            record: The record to search
            record_keys_lower: Lowercase key mapping
            field_type: 'name' or 'path'
        
        Returns:
            Extracted value or empty string
        """
        # Key terms that indicate name fields
        name_terms = ['name', 'file', 'exe', 'app', 'program', 'process', 'source', 'target', 'image', 'binary', 'module']
        # Key terms that indicate path fields
        path_terms = ['path', 'location', 'directory', 'folder', 'dir', 'full', 'reconstructed']
        
        terms = name_terms if field_type == 'name' else path_terms
        
        # Score each field by how likely it contains identity info
        candidates = []
        for key_lower, actual_key in record_keys_lower.items():
            value = record.get(actual_key)
            if not value or not isinstance(value, str):
                continue
            
            value_str = str(value).strip()
            if not value_str or value_str.lower() in ('none', 'null', 'n/a', '', '[unknown]', 'unknown'):
                continue
            
            # Score based on field name
            score = 0
            for term in terms:
                if term in key_lower:
                    score += 10
            
            # For name fields, prefer values that look like filenames
            if field_type == 'name':
                if value_str.endswith('.exe') or value_str.endswith('.dll') or value_str.endswith('.sys'):
                    score += 20
                elif '.' in value_str and len(value_str) < 100:
                    score += 5
                # Avoid paths
                if '\\' in value_str or '/' in value_str:
                    score -= 10
            
            # For path fields, prefer values that look like paths
            if field_type == 'path':
                if '\\' in value_str or '/' in value_str:
                    score += 20
                if value_str.startswith('C:') or value_str.startswith('/'):
                    score += 10
            
            if score > 0:
                candidates.append((score, value_str))
        
        # Return highest scoring candidate
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        
        return ""
    
    def _extract_name_from_path(self, path: str) -> str:
        """Extract filename from a path string."""
        if not path:
            return ""
        
        # Normalize path separators
        normalized = path.replace('\\', '/')
        
        # Get the last component
        parts = normalized.rstrip('/').split('/')
        if parts:
            filename = parts[-1]
            # Only return if it looks like a filename
            if '.' in filename or filename.endswith('.exe') or filename.endswith('.dll'):
                return filename
        
        return ""
    
    def _determine_identity_type(self, name: str, path: str, hash_value: str) -> str:
        """
        Determine identity type based on available fields.
        
        Args:
            name: Application name
            path: File path
            hash_value: File hash
        
        Returns:
            Identity type: "hash", "path", "name", or "composite"
        """
        has_name = bool(name)
        has_path = bool(path)
        has_hash = bool(hash_value)
        
        # Priority: hash > path > name > composite
        if has_hash:
            return "hash"
        elif has_path:
            return "path"
        elif has_name:
            return "name"
        elif has_name or has_path:
            return "composite"
        else:
            return "name"  # Default fallback
    
    def get_or_create_identity(self, record: Dict[str, Any]) -> Identity:
        """
        Get existing identity or create new one from record.
        
        Uses hash-based index for O(1) lookup performance.
        
        Args:
            record: Forensic record dictionary
        
        Returns:
            Identity object (existing or newly created)
        
        Requirements: 1.1, 1.2, 5.1
        """
        # Extract identity information
        name, path, hash_value, identity_type = self.extract_identity_info(record)
        
        # Generate normalized key
        identity_key = self.normalize_identity_key(name, path, hash_value)
        
        # Check if identity already exists
        if identity_key in self.identity_index:
            return self.identity_index[identity_key]
        
        # Create new identity
        identity = Identity(
            identity_type=identity_type,
            identity_value=path if path else name,  # Prefer path over name
            primary_name=name,
            normalized_name=self.normalize_identity_key(name, "", ""),
            confidence=1.0,
            match_method="exact"
        )
        
        # Store in index
        self.identity_index[identity_key] = identity
        
        if self.debug_mode:
            print(f"[DEBUG] Created new identity: {identity.identity_id} (key={identity_key})")
        
        return identity
    
    def extract_primary_name(self, name: str, path: str) -> str:
        """
        Extract primary display name from name or path.
        
        IMPROVED: Better normalization to group related files under same identity.
        - Removes file extensions (.exe, .lnk, .dll, etc.)
        - Removes version numbers and copy indicators like (1), (2), v1, v2
        - Normalizes spaces and special characters
        
        Args:
            name: Application name
            path: File path
        
        Returns:
            Primary display name (normalized application name)
        """
        raw_name = ""
        
        # If we have a direct name, use it
        if name:
            # Clean up the name - extract just the filename if it looks like a path
            if '\\' in name or '/' in name:
                extracted = Path(name.replace('\\', '/')).name
                if extracted:
                    raw_name = extracted
                else:
                    raw_name = name
            else:
                raw_name = name
        # Extract from path
        elif path:
            # Normalize path separators
            normalized_path = path.replace('\\', '/')
            # Extract filename from path
            extracted = Path(normalized_path).name
            if extracted:
                raw_name = extracted
        
        if not raw_name:
            return "Unknown"
        
        # Normalize the name
        normalized = self._normalize_application_name(raw_name)
        
        return normalized if normalized else raw_name
    
    def _normalize_application_name(self, name: str) -> str:
        """
        Normalize application name for better grouping.
        
        Removes:
        - File extensions (.exe, .lnk, .dll, .msi, .bat, .cmd, .ps1, .vbs, .js)
        - Copy indicators: (1), (2), (3), - Copy, _copy
        - Version indicators: v1, v2, v1.0, 1.0.0
        - Trailing numbers and special chars
        
        Args:
            name: Raw application name
        
        Returns:
            Normalized name for identity grouping
        """
        if not name:
            return ""
        
        result = name.strip()
        
        # Remove common file extensions (case-insensitive)
        extensions = [
            '.exe', '.lnk', '.dll', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.js',
            '.com', '.scr', '.pif', '.application', '.gadget', '.msp', '.hta',
            '.cpl', '.msc', '.jar', '.py', '.pyc', '.pyw'
        ]
        lower_result = result.lower()
        for ext in extensions:
            if lower_result.endswith(ext):
                result = result[:-len(ext)]
                break
        
        # Remove copy indicators like (1), (2), (3), etc.
        # Pattern: space or underscore followed by (number) at the end
        import re
        result = re.sub(r'[\s_]*\(\d+\)\s*$', '', result)
        
        # Remove " - Copy", "_copy", " copy" at the end
        result = re.sub(r'[\s_]*[-_]?\s*[Cc]opy\s*\d*\s*$', '', result)
        
        # Remove version patterns like v1, v2, v1.0, 1.0.0 at the end
        # But be careful not to remove important version info from product names
        result = re.sub(r'[\s_]*[vV]?\d+(\.\d+)*\s*$', '', result)
        
        # Remove trailing special characters and spaces
        result = result.rstrip(' _-.')
        
        # Normalize multiple spaces to single space
        result = re.sub(r'\s+', ' ', result)
        
        return result.strip()
    
    def clear_index(self):
        """Clear the identity index for new correlation run."""
        self.identity_index.clear()
        if self.debug_mode:
            print("[DEBUG] Identity index cleared")


class IdentityMatcher:
    """
    Flexible identity matching with multiple strategies.
    
    Implements exact match, partial path match, hash match, and fuzzy name matching.
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize identity matcher.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
    
    def calculate_path_similarity(self, path1: str, path2: str) -> float:
        """
        Calculate similarity between two file paths.
        
        Uses component-based matching for partial path similarity.
        
        Args:
            path1: First file path
            path2: Second file path
        
        Returns:
            Similarity score between 0.0 and 1.0
        
        Requirements: 5.2
        """
        if not path1 or not path2:
            return 0.0
        
        # Normalize paths
        p1 = path1.replace("\\", "/").lower().strip("/")
        p2 = path2.replace("\\", "/").lower().strip("/")
        
        # Exact match
        if p1 == p2:
            return 1.0
        
        # Split into components
        components1 = p1.split("/")
        components2 = p2.split("/")
        
        # Calculate component overlap
        matching_components = 0
        total_components = max(len(components1), len(components2))
        
        for c1 in components1:
            if c1 in components2:
                matching_components += 1
        
        similarity = matching_components / total_components if total_components > 0 else 0.0
        
        return similarity
    
    def calculate_edit_distance(self, str1: str, str2: str) -> int:
        """
        Calculate Levenshtein edit distance between two strings.
        
        Args:
            str1: First string
            str2: Second string
        
        Returns:
            Edit distance (number of edits needed)
        
        Requirements: 5.4
        """
        if not str1:
            return len(str2)
        if not str2:
            return len(str1)
        
        # Create distance matrix
        m, n = len(str1), len(str2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        # Initialize base cases
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        
        # Fill matrix
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if str1[i-1] == str2[j-1]:
                    dp[i][j] = dp[i-1][j-1]
                else:
                    dp[i][j] = 1 + min(
                        dp[i-1][j],    # deletion
                        dp[i][j-1],    # insertion
                        dp[i-1][j-1]   # substitution
                    )
        
        return dp[m][n]



class IdentityBasedCorrelationEngine:
    """
    Complete Identity-Based Correlation Engine.
    
    Implements the full correlation workflow:
    1. Identity extraction and clustering
    2. Temporal anchor clustering
    3. Primary/secondary/supporting evidence classification
    4. Semantic enrichment
    5. Results generation
    
    This is the main engine that ties all components together.
    """
    
    def __init__(self, time_window_minutes: int = 5, debug_mode: bool = False):
        """
        Initialize Identity-Based Correlation Engine.
        
        Args:
            time_window_minutes: Time window for anchor clustering (default 5 minutes, matches Wing default)
            debug_mode: Enable debug logging
        """
        self.time_window_minutes = time_window_minutes
        self.debug_mode = debug_mode
        
        # Core components
        self.identity_engine = IdentityCorrelationEngine(debug_mode=debug_mode)
        self.identity_matcher = IdentityMatcher(debug_mode=debug_mode)
        
        # Correlation state
        self.identities: Dict[str, Identity] = {}  # identity_key -> Identity
        self.correlation_results: Optional[CorrelationResults] = None
        
        # Statistics tracking
        self.stats = CorrelationStatistics()
        self.start_time: Optional[datetime] = None
    
    def correlate_records(self, records: List[Dict[str, Any]], 
                         wing_name: str = "Unknown Wing",
                         wing_id: str = "unknown") -> CorrelationResults:
        """
        Main correlation method - processes all records and returns correlation results.
        
        Args:
            records: List of forensic records to correlate
            wing_name: Name of the Wing being processed
            wing_id: ID of the Wing being processed
        
        Returns:
            CorrelationResults with all identities, anchors, and statistics
        """
        self.start_time = datetime.now()
        
        print(f"[Identity Engine] Starting correlation with time_window={self.time_window_minutes} minutes")
        
        # Count records per feather
        feather_counts = {}
        for record in records:
            fid = record.get('feather_id', 'unknown')
            feather_counts[fid] = feather_counts.get(fid, 0) + 1
        print(f"[Identity Engine] Records per feather:")
        for fid, count in sorted(feather_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {fid}: {count:,}")
        
        # Initialize results
        self.correlation_results = CorrelationResults(
            wing_name=wing_name,
            wing_id=wing_id,
            execution_timestamp=self.start_time
        )
        
        # Step 1: Identity Extraction and Clustering
        self._extract_and_cluster_identities(records)
        print(f"[Identity Engine] Step 1: Extracted {len(self.identities)} unique identities")
        
        # Step 2: Temporal Anchor Clustering
        self._create_temporal_anchors()
        print(f"[Identity Engine] Step 2: Created {self.stats.total_anchors} anchors")
        
        # Step 3: Primary Anchor Selection
        self._select_primary_anchors()
        print(f"[Identity Engine] Step 3: Selected primary evidence")
        
        # Step 4: Generate Final Results
        self._generate_results()
        print(f"[Identity Engine] Step 4: Generated results")
        
        # Calculate final statistics
        self._calculate_final_statistics()
        
        # Print summary of multi-feather identities
        multi_feather_identities = 0
        for identity in self.identities.values():
            feathers = set()
            for evidence in identity.all_evidence:
                if hasattr(evidence, 'feather_id'):
                    feathers.add(evidence.feather_id)
            if len(feathers) > 1:
                multi_feather_identities += 1
        
        print(f"[Identity Engine] Identities with evidence from multiple feathers: {multi_feather_identities}")
        
        return self.correlation_results
    
    def _extract_and_cluster_identities(self, records: List[Dict[str, Any]]):
        """
        Task 7.2 & 7.3: Extract identities from records and cluster them.
        
        FIXED: Uses ONLY the normalized application name as the identity key
        to ensure records from different feathers with the same application
        are grouped together into the same identity.
        
        IMPROVED: Better per-feather extraction statistics tracking.
        """
        self.identities.clear()
        processed_count = 0
        skipped_no_identity = 0
        
        # Track feather contribution per identity for debugging
        identity_feathers = {}
        
        # IMPROVED: Track extraction success per feather (lightweight)
        feather_extraction_stats = {}  # feather_id -> {total, extracted, failed, artifact_type}
        
        for record in records:
            try:
                # Track which feather this record is from
                feather_id = record.get('feather_id', 'unknown')
                artifact_type = record.get('artifact', 'Unknown')
                
                # Initialize stats for this feather
                if feather_id not in feather_extraction_stats:
                    feather_extraction_stats[feather_id] = {
                        'total': 0,
                        'extracted': 0,
                        'failed': 0,
                        'artifact_type': artifact_type
                    }
                
                feather_extraction_stats[feather_id]['total'] += 1
                
                # Extract identity information
                name, path, hash_value, identity_type = self.identity_engine.extract_identity_info(record)
                
                # Skip records without sufficient identity information
                if not any([name, path, hash_value]):
                    skipped_no_identity += 1
                    feather_extraction_stats[feather_id]['failed'] += 1
                    continue
                
                # Get the RAW name (before normalization) for display purposes
                raw_name = name if name else (Path(path.replace('\\', '/')).name if path else "Unknown")
                
                # FIXED: Use ONLY the normalized application name as the identity key
                # This ensures records from different feathers with the same app are grouped together
                normalized_name = self.identity_engine.extract_primary_name(name, path)
                identity_key = normalized_name.lower().strip()
                
                # Skip empty identity keys
                if not identity_key:
                    skipped_no_identity += 1
                    feather_extraction_stats[feather_id]['failed'] += 1
                    continue
                
                # Track successful extraction
                feather_extraction_stats[feather_id]['extracted'] += 1
                
                # Get or create identity
                if identity_key not in self.identities:
                    # Use normalized name as display name for the identity group
                    # But store all original names in the evidence
                    identity = Identity(
                        identity_type=identity_type,
                        identity_value=path if path else name,
                        primary_name=normalized_name,  # Display the normalized group name
                        normalized_name=identity_key,
                        confidence=1.0,
                        match_method="exact"
                    )
                    self.identities[identity_key] = identity
                    identity_feathers[identity_key] = set()
                
                identity = self.identities[identity_key]
                
                # Track which feathers contribute to this identity
                identity_feathers[identity_key].add(feather_id)
                
                # Create evidence row
                evidence = self._create_evidence_row(record, identity)
                
                # Add evidence to identity
                identity.add_evidence(evidence)
                
                processed_count += 1
            except Exception as e:
                if self.debug_mode:
                    print(f"[ERROR] Failed to process record: {e}")
        
        # Log extraction stats per feather with success rate and sample fields for failures
        print(f"[Identity Engine] Extraction stats per feather:")
        feathers_with_issues = []
        for fid, stats in sorted(feather_extraction_stats.items(), key=lambda x: x[1]['total'], reverse=True):
            success_rate = (stats['extracted'] / stats['total'] * 100) if stats['total'] > 0 else 0
            status_icon = "✓" if success_rate >= 90 else "+" if success_rate >= 50 else "!" if success_rate > 0 else "✗"
            print(f"  {status_icon} {fid} ({stats['artifact_type']}): {stats['extracted']}/{stats['total']} ({success_rate:.1f}%)")
            
            # Track feathers with low extraction rates for detailed logging
            if success_rate < 50 and stats['total'] > 0:
                feathers_with_issues.append((fid, stats, success_rate))
        
        # Show sample fields for feathers with low extraction rates
        if feathers_with_issues:
            print(f"\n[Identity Engine] ⚠ Feathers with low extraction rates - sample fields:")
            sample_records_by_feather = {}
            for record in records[:1000]:  # Check first 1000 records for samples
                fid = record.get('feather_id', 'unknown')
                if fid not in sample_records_by_feather:
                    sample_records_by_feather[fid] = record
            
            for fid, stats, rate in feathers_with_issues:
                if fid in sample_records_by_feather:
                    sample = sample_records_by_feather[fid]
                    # Show field names and sample values
                    fields_preview = []
                    for key, value in list(sample.items())[:10]:
                        if key not in ('feather_id', 'artifact', 'table', 'row_id'):
                            val_str = str(value)[:30] if value else 'None'
                            fields_preview.append(f"{key}={val_str}")
                    print(f"    {fid}: {', '.join(fields_preview)}")
        
        # Log identity-feather mapping for debugging
        multi_feather_count = sum(1 for feathers in identity_feathers.values() if len(feathers) > 1)
        print(f"\n[Identity Engine] Identities with multiple feathers: {multi_feather_count}/{len(self.identities)}")
        
        # Show top identities with multiple feathers (limit to 5)
        if multi_feather_count > 0:
            print(f"[Identity Engine] Top multi-feather identities:")
            count = 0
            for identity_key, feathers in sorted(identity_feathers.items(), 
                                                  key=lambda x: len(x[1]), 
                                                  reverse=True):
                if len(feathers) > 1:
                    print(f"  - {identity_key}: {', '.join(sorted(feathers))}")
                    count += 1
                    if count >= 5:
                        break
        
        if skipped_no_identity > 0:
            print(f"[Identity Engine] Skipped {skipped_no_identity} records with no identity info")
        
        self.stats.total_identities = len(self.identities)
        self.stats.total_evidence = processed_count
    
    def _create_evidence_row(self, record: Dict[str, Any], identity: Identity) -> EvidenceRow:
        """
        Create an EvidenceRow from a forensic record.
        
        Args:
            record: Original forensic record
            identity: Identity this evidence belongs to
        
        Returns:
            EvidenceRow with enhanced fields
        """
        # Extract basic fields
        artifact = record.get('artifact', 'Unknown')
        table = record.get('table', 'unknown_table')
        row_id = record.get('row_id', 0)
        
        # Extract timestamp using multiple field patterns
        timestamp = None
        
        # First try the 'timestamp' field directly
        timestamp_field = record.get('timestamp')
        if timestamp_field:
            timestamp = self._parse_timestamp_value(timestamp_field)
        
        # If no timestamp found, try artifact-specific timestamp fields
        if timestamp is None:
            for field_pattern in self.identity_engine.timestamp_field_patterns:
                if field_pattern in record and record[field_pattern]:
                    timestamp = self._parse_timestamp_value(record[field_pattern])
                    if timestamp:
                        break
                # Also try case-insensitive match
                for key in record.keys():
                    if key.lower() == field_pattern.lower() and record[key]:
                        timestamp = self._parse_timestamp_value(record[key])
                        if timestamp:
                            break
                if timestamp:
                    break
        
        # Determine if evidence has anchor (has timestamp)
        has_anchor = timestamp is not None
        
        # Create evidence row
        evidence = EvidenceRow(
            artifact=artifact,
            table=table,
            row_id=row_id,
            timestamp=timestamp,
            semantic=record.copy(),  # Store original semantic data
            feather_id=record.get('feather_id', f"{artifact}_{row_id}"),
            anchor_id=None,  # Will be set during anchor clustering
            is_primary=False,  # Will be determined during anchor selection
            has_anchor=has_anchor,
            role="secondary",  # Default role, will be updated
            match_reason="identity_extraction",
            match_method="exact",
            similarity_score=1.0,
            confidence=1.0,
            original_data=record.copy(),
            semantic_data={}  # Will be populated during semantic enrichment
        )
        
        return evidence
    
    def _parse_timestamp_value(self, value: Any) -> Optional[datetime]:
        """Parse a timestamp value from various formats."""
        if value is None:
            return None
        
        if isinstance(value, datetime):
            return value
        
        timestamp_str = str(value).strip()
        if not timestamp_str or timestamp_str.lower() in ('none', 'null', 'n/a', ''):
            return None
        
        # Try ISO format first
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            pass
        
        # Try common formats
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d",
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(timestamp_str, fmt)
                if 1970 <= parsed.year <= 2100:
                    return parsed
            except:
                continue
        
        # Try numeric timestamps
        try:
            numeric_value = float(timestamp_str)
            if numeric_value > 10000000000000:  # Windows FILETIME
                unix_timestamp = (numeric_value - 116444736000000000) / 10000000
                parsed = datetime.fromtimestamp(unix_timestamp)
            elif numeric_value > 10000000000:  # Milliseconds
                parsed = datetime.fromtimestamp(numeric_value / 1000)
            elif numeric_value > 0:  # Seconds
                parsed = datetime.fromtimestamp(numeric_value)
            else:
                return None
            
            if 1970 <= parsed.year <= 2100:
                return parsed
        except:
            pass
        
        return None
    
    def _create_temporal_anchors(self):
        """
        Task 7.4: Create temporal anchors by clustering timestamped evidence.
        
        IMPROVED APPROACH: Cluster ALL evidence by time windows FIRST, then group by identity.
        This ensures anchors contain evidence from multiple feathers when they occur
        within the same time window.
        """
        print(f"[Identity Engine] Creating temporal anchors with {self.time_window_minutes} minute window")
        
        # Step 1: Collect ALL timestamped evidence across ALL identities
        all_timestamped_evidence = []
        identity_map = {}  # evidence_id -> identity
        
        for identity in self.identities.values():
            for evidence in identity.all_evidence:
                if evidence.timestamp is not None:
                    # Create a unique ID for this evidence
                    evidence_id = id(evidence)
                    all_timestamped_evidence.append(evidence)
                    identity_map[evidence_id] = identity
                else:
                    # Mark non-timestamped evidence as supporting
                    evidence.role = "supporting"
                    evidence.has_anchor = False
        
        if not all_timestamped_evidence:
            print(f"[Identity Engine] No timestamped evidence found")
            self.stats.total_anchors = 0
            return
        
        # Step 2: Sort ALL evidence by timestamp
        all_timestamped_evidence.sort(key=lambda e: e.timestamp)
        
        print(f"[Identity Engine] Clustering {len(all_timestamped_evidence)} timestamped records")
        
        # Step 3: Create time-based clusters (global time windows)
        time_clusters = []
        current_cluster = []
        cluster_start_time = None
        
        for evidence in all_timestamped_evidence:
            if not current_cluster:
                # Start new cluster
                current_cluster = [evidence]
                cluster_start_time = evidence.timestamp
            else:
                # Check if evidence fits in current cluster's time window
                time_diff = (evidence.timestamp - cluster_start_time).total_seconds() / 60.0
                
                if time_diff <= self.time_window_minutes:
                    # Add to current cluster
                    current_cluster.append(evidence)
                else:
                    # Save current cluster and start new one
                    if current_cluster:
                        time_clusters.append(current_cluster)
                    current_cluster = [evidence]
                    cluster_start_time = evidence.timestamp
        
        # Don't forget the last cluster
        if current_cluster:
            time_clusters.append(current_cluster)
        
        print(f"[Identity Engine] Created {len(time_clusters)} time clusters")
        
        # Step 4: Within each time cluster, group by identity and create anchors
        total_anchors = 0
        multi_feather_anchors = 0
        
        for cluster in time_clusters:
            # Group evidence in this cluster by identity
            identity_groups = {}
            for evidence in cluster:
                evidence_id = id(evidence)
                identity = identity_map.get(evidence_id)
                if identity:
                    if identity.identity_id not in identity_groups:
                        identity_groups[identity.identity_id] = {
                            'identity': identity,
                            'evidence': []
                        }
                    identity_groups[identity.identity_id]['evidence'].append(evidence)
            
            # Create an anchor for each identity in this time cluster
            for identity_id, group in identity_groups.items():
                identity = group['identity']
                evidence_list = group['evidence']
                
                if not evidence_list:
                    continue
                
                # Sort evidence by timestamp within the group
                evidence_list.sort(key=lambda e: e.timestamp)
                
                # Create anchor
                anchor = Anchor(
                    identity_id=identity_id,
                    start_time=evidence_list[0].timestamp,
                    end_time=evidence_list[-1].timestamp
                )
                
                # Add all evidence to anchor
                feathers_in_anchor = set()
                for evidence in evidence_list:
                    anchor.add_evidence(evidence)
                    evidence.anchor_id = anchor.anchor_id
                    if hasattr(evidence, 'feather_id'):
                        feathers_in_anchor.add(evidence.feather_id)
                
                # Store feathers in anchor
                anchor.feather_ids = list(feathers_in_anchor)
                if len(feathers_in_anchor) > 1:
                    multi_feather_anchors += 1
                
                # Add anchor to identity
                identity.anchors.append(anchor)
                identity.total_anchors = len(identity.anchors)
                total_anchors += 1
        
        self.stats.total_anchors = total_anchors
        
        print(f"[Identity Engine] Created {total_anchors} anchors, {multi_feather_anchors} with multiple feathers ({multi_feather_anchors * 100 // max(total_anchors, 1)}%)")
    
    def _cluster_evidence_by_time(self, evidence_list: List[EvidenceRow], identity_id: str) -> List[Anchor]:
        """
        Cluster evidence by time windows to create anchors.
        
        Args:
            evidence_list: Sorted list of timestamped evidence
            identity_id: ID of the identity this evidence belongs to
        
        Returns:
            List of Anchor objects
        """
        if not evidence_list:
            return []
        
        anchors = []
        current_anchor = None
        
        for evidence in evidence_list:
            if current_anchor is None:
                # Start new anchor
                current_anchor = Anchor(
                    identity_id=identity_id,
                    start_time=evidence.timestamp,
                    end_time=evidence.timestamp
                )
                current_anchor.add_evidence(evidence)
            else:
                # Check if evidence fits in current anchor's time window
                time_diff = (evidence.timestamp - current_anchor.end_time).total_seconds() / 60.0
                
                if time_diff <= self.time_window_minutes:
                    # Add to current anchor
                    current_anchor.add_evidence(evidence)
                else:
                    # Close current anchor and start new one
                    anchors.append(current_anchor)
                    current_anchor = Anchor(
                        identity_id=identity_id,
                        start_time=evidence.timestamp,
                        end_time=evidence.timestamp
                    )
                    current_anchor.add_evidence(evidence)
        
        # Add final anchor
        if current_anchor:
            anchors.append(current_anchor)
        
        return anchors
    
    def _select_primary_anchors(self):
        """
        Task 7.5: Select primary evidence within each anchor.
        Determines which evidence is primary vs secondary within each anchor.
        """
        primary_count = 0
        secondary_count = 0
        
        for identity in self.identities.values():
            for anchor in identity.anchors:
                if not anchor.rows:
                    continue
                
                # Select primary evidence (earliest timestamp with highest priority artifact)
                primary_evidence = self._select_primary_evidence(anchor.rows)
                
                # Mark evidence roles
                for evidence in anchor.rows:
                    if evidence == primary_evidence:
                        evidence.role = "primary"
                        evidence.is_primary = True
                        primary_count += 1
                    else:
                        evidence.role = "secondary"
                        evidence.is_primary = False
                        secondary_count += 1
                
                # Update anchor metadata
                anchor.primary_artifact = primary_evidence.artifact
                anchor.primary_row_id = primary_evidence.row_id
        
        # Update statistics
        self.stats.evidence_by_role["primary"] = primary_count
        self.stats.evidence_by_role["secondary"] = secondary_count
        
        # Count supporting evidence
        supporting_count = 0
        for identity in self.identities.values():
            supporting_count += len([e for e in identity.all_evidence if e.role == "supporting"])
        self.stats.evidence_by_role["supporting"] = supporting_count
        
        self.stats.evidence_with_anchors = primary_count + secondary_count
        self.stats.evidence_without_anchors = supporting_count
    
    def _select_primary_evidence(self, evidence_list: List[EvidenceRow]) -> EvidenceRow:
        """
        Select the primary evidence from a list of evidence in an anchor.
        
        Priority order:
        1. Prefetch (execution evidence)
        2. Event Logs (system events)
        3. Registry (persistence)
        4. Other artifacts
        5. Earliest timestamp as tiebreaker
        
        Args:
            evidence_list: List of evidence to choose from
        
        Returns:
            Primary evidence row
        """
        if len(evidence_list) == 1:
            return evidence_list[0]
        
        # Define artifact priority (higher = more primary)
        artifact_priority = {
            'prefetch': 100,
            'srum': 90,
            'amcache': 85,
            'shimcache': 80,
            'security_logs': 75,
            'system_logs': 70,
            'application_logs': 65,
            'registry': 60,
            'mft': 55,
            'usn_journal': 50,
            'browser_history': 45,
            'lnk_files': 40
        }
        
        # Sort by priority, then by timestamp
        def priority_key(evidence):
            artifact_name = evidence.artifact.lower()
            priority = artifact_priority.get(artifact_name, 0)
            timestamp = evidence.timestamp or datetime.min
            return (priority, timestamp)
        
        sorted_evidence = sorted(evidence_list, key=priority_key, reverse=True)
        return sorted_evidence[0]
    
    def _generate_results(self):
        """
        Task 7.7: Generate final correlation results.
        Packages all identities, anchors, and evidence into final results.
        """
        # Add all identities to results
        for identity in self.identities.values():
            self.correlation_results.add_identity(identity)
        
        # Update artifacts processed
        artifacts = set()
        for identity in self.identities.values():
            artifacts.update(identity.artifacts_involved)
        self.stats.artifacts_processed = list(artifacts)
        
        # Update identity type breakdown
        for identity in self.identities.values():
            if identity.identity_type not in self.stats.identities_by_type:
                self.stats.identities_by_type[identity.identity_type] = 0
            self.stats.identities_by_type[identity.identity_type] += 1
    
    def _calculate_final_statistics(self):
        """
        Calculate final performance and quality statistics.
        """
        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
            self.stats.execution_duration_seconds = duration
            if duration > 0:
                self.stats.records_per_second = self.stats.total_evidence / duration
        
        # Update correlation results with final statistics
        self.correlation_results.statistics = self.stats


class CorrelationExecutor:
    """
    High-level executor for identity-based correlation.
    Provides a simple interface for running correlation on forensic data.
    """
    
    def __init__(self, time_window_minutes: int = 5, debug_mode: bool = False):
        """
        Initialize correlation executor.
        
        Args:
            time_window_minutes: Time window for anchor clustering (default 5 minutes)
            debug_mode: Enable debug logging
        """
        self.engine = IdentityBasedCorrelationEngine(
            time_window_minutes=time_window_minutes,
            debug_mode=debug_mode
        )
    
    def execute_correlation(self, records: List[Dict[str, Any]], 
                          wing_name: str = "Unknown Wing",
                          wing_id: str = "unknown") -> CorrelationResults:
        """
        Execute identity-based correlation on forensic records.
        
        Args:
            records: List of forensic records to correlate
            wing_name: Name of the Wing being processed
            wing_id: ID of the Wing being processed
        
        Returns:
            CorrelationResults with all identities and statistics
        """
        return self.engine.correlate_records(records, wing_name, wing_id)
    
    def get_statistics(self) -> Optional[CorrelationStatistics]:
        """Get correlation statistics from last execution."""
        if self.engine.correlation_results:
            return self.engine.correlation_results.statistics
        return None


# Convenience function for simple correlation
def correlate_forensic_records(records: List[Dict[str, Any]], 
                             time_window_minutes: int = 5,
                             wing_name: str = "Unknown Wing",
                             wing_id: str = "unknown",
                             debug_mode: bool = False) -> CorrelationResults:
    """
    Convenience function to correlate forensic records.
    
    Args:
        records: List of forensic records to correlate
        time_window_minutes: Time window for anchor clustering (default 5 minutes)
        wing_name: Name of the Wing being processed
        wing_id: ID of the Wing being processed
        debug_mode: Enable debug logging
    
    Returns:
        CorrelationResults with all identities and statistics
    """
    executor = CorrelationExecutor(time_window_minutes, debug_mode)
    return executor.execute_correlation(records, wing_name, wing_id)



# ============================================================================
# Adapter for BaseCorrelationEngine Interface
# ============================================================================

class IdentityBasedEngineAdapter:
    """
    Adapter that wraps IdentityBasedCorrelationEngine to support BaseCorrelationEngine interface.
    
    This adapter:
    1. Inherits from BaseCorrelationEngine
    2. Supports FilterConfig for time period and identity filtering
    3. Wraps the existing IdentityBasedCorrelationEngine
    4. Provides standardized execute() interface
    
    Example:
        from .base_engine import FilterConfig
        
        engine = IdentityBasedEngineAdapter(
            config=pipeline_config,
            filters=FilterConfig(
                time_period_start=datetime(2024, 1, 1),
                identity_filters=["chrome.exe", "*.dll"]
            )
        )
        result = engine.execute([wing])
    """
    
    def __init__(self, config: Any, filters: Optional['FilterConfig'] = None, 
                 time_window_minutes: int = 5, debug_mode: bool = False):
        """
        Initialize Identity-Based Engine Adapter.
        
        Args:
            config: Pipeline configuration object
            filters: Optional filter configuration
            time_window_minutes: Time window for anchor clustering (default 5 minutes)
            debug_mode: Enable debug logging
        """
        # Import here to avoid circular dependency
        from .base_engine import BaseCorrelationEngine, EngineMetadata, FilterConfig
        
        # Store configuration
        self.config = config
        self.filters = filters or FilterConfig()
        self.debug_mode = debug_mode
        
        # Create internal identity engine
        self.engine = IdentityBasedCorrelationEngine(
            time_window_minutes=time_window_minutes,
            debug_mode=debug_mode
        )
        
        # Store last result
        self.last_result = None
        
        # Progress listener (for GUI updates)
        self.progress_listener = None
        
        # Streaming support - output directory and execution ID for database streaming
        self._output_dir = None
        self._execution_id = None
    
    def set_output_directory(self, output_dir: str, execution_id: int = None):
        """
        Set output directory for streaming results to database.
        
        Args:
            output_dir: Directory where correlation_results.db will be created
            execution_id: Optional execution ID for database records
        """
        self._output_dir = output_dir
        self._execution_id = execution_id
    
    def register_progress_listener(self, listener):
        """
        Register a progress listener for GUI updates.
        
        Args:
            listener: Callable that receives progress events
        """
        self.progress_listener = listener
    
    @property
    def metadata(self):
        """Get engine metadata"""
        from .base_engine import EngineMetadata
        
        return EngineMetadata(
            name="Identity-Based Correlation",
            version="2.0.0",
            description="Identity-first clustering with temporal anchors",
            complexity="O(N log N)",
            best_for=[
                "Large datasets (>1,000 records)",
                "Production environments",
                "Identity tracking",
                "Performance-critical analysis",
                "Relationship mapping"
            ],
            supports_identity_filter=True
        )
    
    def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
        """
        Execute correlation with time period AND identity filtering.
        
        Args:
            wing_configs: List of Wing configuration objects
            
        Returns:
            Dictionary containing:
                - 'result': CorrelationResults object
                - 'engine_type': 'identity_based'
                - 'filters_applied': Dictionary of applied filters
        """
        try:
            if not wing_configs:
                raise ValueError("No wing configurations provided")
            
            wing = wing_configs[0]
            print(f"[Identity Engine] Starting execution for wing: {wing.wing_name}")
            
            # Load records from wing
            print(f"[Identity Engine] Loading records from wing...")
            records = self._load_records_from_wing(wing)
            print(f"[Identity Engine] Loaded {len(records)} records")
            
            # Apply time period filter
            if self.filters.time_period_start or self.filters.time_period_end:
                if self.debug_mode:
                    print(f"[Identity Engine] Applying time period filter:")
                    if self.filters.time_period_start:
                        print(f"  Start: {self.filters.time_period_start}")
                    if self.filters.time_period_end:
                        print(f"  End: {self.filters.time_period_end}")
                
                records = self._apply_time_period_filter(records)
                print(f"[Identity Engine] After time filter: {len(records)} records")
            
            # Apply identity filter (IDENTITY ENGINE ONLY)
            if self.filters.identity_filters:
                if self.debug_mode:
                    print(f"[Identity Engine] Applying identity filters:")
                    for pattern in self.filters.identity_filters:
                        print(f"  • {pattern}")
                
                records = self._apply_identity_filter(records)
                print(f"[Identity Engine] After identity filter: {len(records)} records")
            
            # Execute correlation
            print(f"[Identity Engine] Starting correlation...")
            result = self.engine.correlate_records(
                records,
                wing_name=wing.wing_name,
                wing_id=wing.wing_id
            )
            print(f"[Identity Engine] Correlation complete")
            
            # Store result
            self.last_result = result
            
            # Return standardized format
            return {
                'result': result,
                'engine_type': 'identity_based',
                'filters_applied': {
                    'time_period_start': self.filters.time_period_start.isoformat() if self.filters.time_period_start else None,
                    'time_period_end': self.filters.time_period_end.isoformat() if self.filters.time_period_end else None,
                    'identity_filters': self.filters.identity_filters
                }
            }
        except Exception as e:
            print(f"[Identity Engine] ERROR: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    def get_results(self) -> Any:
        """Get correlation results from last execution"""
        return self.last_result
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get correlation statistics from last execution"""
        if not self.last_result or not self.last_result.statistics:
            return {}
        
        stats = self.last_result.statistics
        return {
            'execution_time': stats.execution_duration_seconds,
            'record_count': stats.total_evidence,
            'match_count': stats.total_identities,
            'duplicate_rate': 0,  # Identity engine has very low duplicate rate
            'identities_found': stats.total_identities,
            'anchors_created': stats.total_anchors,
            'evidence_with_anchors': stats.evidence_with_anchors,
            'evidence_without_anchors': stats.evidence_without_anchors
        }
    
    def _load_records_from_wing(self, wing) -> List[Dict[str, Any]]:
        """
        Load records from all feathers in wing.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            List of all records from all feathers
        """
        from .feather_loader import FeatherLoader
        
        all_records = []
        
        for feather_spec in wing.feathers:
            # Get database path
            db_path = None
            if hasattr(feather_spec, 'database_path') and feather_spec.database_path:
                db_path = feather_spec.database_path
            elif hasattr(feather_spec, 'feather_path') and feather_spec.feather_path:
                db_path = feather_spec.feather_path
            
            if not db_path:
                continue
            
            # Load records
            try:
                loader = FeatherLoader(db_path)
                loader.connect()
                records = loader.get_all_records()
                
                # Add feather metadata to each record
                for record in records:
                    record['feather_id'] = feather_spec.feather_id
                    record['artifact'] = feather_spec.artifact_type
                
                all_records.extend(records)
                loader.disconnect()
                
            except Exception as e:
                if self.debug_mode:
                    print(f"[ERROR] Failed to load feather {feather_spec.feather_id}: {e}")
        
        return all_records
    
    def _apply_time_period_filter(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply time period filter to records.
        
        Args:
            records: List of records to filter
            
        Returns:
            Filtered list of records
        """
        filtered = []
        skipped_invalid = 0
        skipped_before_start = 0
        skipped_after_end = 0
        
        for record in records:
            timestamp = self._parse_timestamp(record.get('timestamp'))
            
            if not timestamp:
                skipped_invalid += 1
                continue
            
            # Check start time
            if self.filters.time_period_start and timestamp < self.filters.time_period_start:
                skipped_before_start += 1
                continue
            
            # Check end time
            if self.filters.time_period_end and timestamp > self.filters.time_period_end:
                skipped_after_end += 1
                continue
            
            filtered.append(record)
        
        # Log filter statistics
        if len(filtered) < len(records):
            print(f"[Time Period Filter] {len(records)} → {len(filtered)} records")
            if skipped_invalid > 0:
                print(f"  • Skipped {skipped_invalid} records with invalid timestamps")
            if skipped_before_start > 0:
                print(f"  • Skipped {skipped_before_start} records before start time")
            if skipped_after_end > 0:
                print(f"  • Skipped {skipped_after_end} records after end time")
        
        return filtered
    
    def _apply_identity_filter(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply identity filter to records.
        
        Filters records to only include those matching specified identities.
        Supports wildcards (* and ?) and case-insensitive matching.
        
        Args:
            records: List of records to filter
            
        Returns:
            Filtered list of records
        """
        if not self.filters.identity_filters:
            return records
        
        import fnmatch
        
        filtered = []
        matched_identities = set()
        
        for record in records:
            # Extract identity from record
            name, path, hash_value, _ = self.engine.identity_engine.extract_identity_info(record)
            
            # Check if any filter matches
            matched = False
            for filter_pattern in self.filters.identity_filters:
                # Normalize for comparison
                if not self.filters.case_sensitive:
                    filter_pattern_lower = filter_pattern.lower()
                    name_lower = name.lower() if name else ""
                    path_lower = path.lower() if path else ""
                    hash_lower = hash_value.lower() if hash_value else ""
                else:
                    filter_pattern_lower = filter_pattern
                    name_lower = name if name else ""
                    path_lower = path if path else ""
                    hash_lower = hash_value if hash_value else ""
                
                # Check if filter matches name, path, or hash
                if (fnmatch.fnmatch(name_lower, filter_pattern_lower) or
                    fnmatch.fnmatch(path_lower, filter_pattern_lower) or
                    fnmatch.fnmatch(hash_lower, filter_pattern_lower)):
                    matched = True
                    matched_identities.add(name or path or hash_value)
                    break
            
            if matched:
                filtered.append(record)
        
        # Log filter statistics
        print(f"[Identity Filter] {len(records)} → {len(filtered)} records")
        print(f"  • Matched {len(matched_identities)} unique identities")
        if self.debug_mode and matched_identities:
            print(f"  • Identities: {', '.join(list(matched_identities)[:10])}")
        
        return filtered
    
    def execute_wing(self, wing: Any, feather_paths: Dict[str, str]) -> Any:
        """
        Execute correlation for a single wing (backward compatibility method).
        
        This method provides backward compatibility with code that calls execute_wing directly.
        It wraps the execute() method to provide the same interface as CorrelationEngine.
        
        Args:
            wing: Wing configuration object
            feather_paths: Dictionary mapping feather_id to database path
            
        Returns:
            CorrelationResult-like object with correlation results
        """
        from .correlation_result import CorrelationResult, CorrelationMatch
        import uuid
        
        print(f"[Identity Engine] execute_wing called for: {wing.wing_name}")
        print(f"[Identity Engine] Available feather_paths keys: {list(feather_paths.keys())[:10]}...")
        
        # Get time window from wing's correlation rules (default 5 minutes)
        time_window = 5  # Default
        if hasattr(wing, 'correlation_rules') and hasattr(wing.correlation_rules, 'time_window_minutes'):
            time_window = wing.correlation_rules.time_window_minutes
        print(f"[Identity Engine] Using time window from wing: {time_window} minutes")
        
        # Update the engine's time window
        self.engine.time_window_minutes = time_window
        
        try:
            # Load records from feather databases
            all_records = []
            feathers_loaded = []
            feathers_failed = []
            
            for feather_spec in wing.feathers:
                feather_id = feather_spec.feather_id
                
                # Try multiple ways to find the database path
                db_path = None
                resolution_method = None
                
                # Method 1: Direct feather_id match
                if feather_id in feather_paths:
                    db_path = feather_paths[feather_id]
                    resolution_method = "feather_id"
                
                # Method 2: feather_config_name match
                if not db_path and hasattr(feather_spec, 'feather_config_name') and feather_spec.feather_config_name:
                    config_name = feather_spec.feather_config_name
                    if config_name in feather_paths:
                        db_path = feather_paths[config_name]
                        resolution_method = "config_name"
                    # Also try lowercase
                    elif config_name.lower() in feather_paths:
                        db_path = feather_paths[config_name.lower()]
                        resolution_method = "config_name_lower"
                
                # Method 3: Try lowercase feather_id
                if not db_path and feather_id.lower() in feather_paths:
                    db_path = feather_paths[feather_id.lower()]
                    resolution_method = "feather_id_lower"
                
                # Method 4: Try database_path directly from feather_spec
                if not db_path and hasattr(feather_spec, 'database_path') and feather_spec.database_path:
                    from pathlib import Path
                    if Path(feather_spec.database_path).exists():
                        db_path = feather_spec.database_path
                        resolution_method = "direct_path"
                
                if not db_path:
                    print(f"[Identity Engine] ✗ No path for feather: {feather_id}")
                    if hasattr(feather_spec, 'feather_config_name'):
                        print(f"                   config_name: {feather_spec.feather_config_name}")
                    feathers_failed.append(feather_id)
                    continue
                
                # Load records from database
                try:
                    from .feather_loader import FeatherLoader
                    loader = FeatherLoader(db_path)
                    loader.connect()
                    records = loader.get_all_records()
                    
                    # Add feather metadata to each record
                    artifact_type = feather_spec.artifact_type if hasattr(feather_spec, 'artifact_type') else 'Unknown'
                    for record in records:
                        record['feather_id'] = feather_id
                        record['artifact'] = artifact_type
                    
                    all_records.extend(records)
                    loader.disconnect()
                    feathers_loaded.append((feather_id, len(records), artifact_type))
                    print(f"[Identity Engine] ✓ Loaded {len(records):,} records from {feather_id} ({artifact_type}) via {resolution_method}")
                    
                except Exception as e:
                    print(f"[Identity Engine] ✗ Error loading {feather_id}: {e}")
                    feathers_failed.append(feather_id)
            
            print(f"[Identity Engine] Summary: {len(feathers_loaded)} feathers loaded, {len(feathers_failed)} failed")
            print(f"[Identity Engine] Total records loaded: {len(all_records):,}")
            
            # Build feather metadata from loaded records
            feather_metadata = {}
            for fid, count, artifact in feathers_loaded:
                feather_metadata[fid] = {
                    'records_loaded': count,
                    'artifact_type': artifact,
                    'identities_found': 0  # Will be updated after correlation
                }
            
            if not all_records:
                print(f"[Identity Engine] ERROR: No records loaded from any feather!")
                result = CorrelationResult(wing_id=wing.wing_id, wing_name=wing.wing_name)
                result.errors.append("No records loaded from any feather")
                return result
            
            # Apply time period filter if configured
            if self.filters.time_period_start or self.filters.time_period_end:
                all_records = self._apply_time_period_filter(all_records)
                print(f"[Identity Engine] After time filter: {len(all_records)} records")
            
            # Apply identity filter if configured
            if self.filters.identity_filters:
                all_records = self._apply_identity_filter(all_records)
                print(f"[Identity Engine] After identity filter: {len(all_records)} records")
            
            # Execute correlation
            correlation_results = self.engine.correlate_records(
                all_records,
                wing_name=wing.wing_name,
                wing_id=wing.wing_id
            )
            
            # Store result
            self.last_result = correlation_results
            
            # Count identities found per feather
            feather_identities = {fid: set() for fid in feather_metadata.keys()}
            for identity in correlation_results.identities:
                for evidence in identity.all_evidence:
                    fid = evidence.feather_id if hasattr(evidence, 'feather_id') else None
                    if fid and fid in feather_identities:
                        feather_identities[fid].add(identity.identity_id)
            
            # Update feather metadata with identity counts
            for fid in feather_metadata:
                feather_metadata[fid]['identities_found'] = len(feather_identities.get(fid, set()))
            
            # Print feather contribution summary
            print(f"[Identity Engine] Feather contribution:")
            for fid, meta in sorted(feather_metadata.items(), key=lambda x: x[1]['records_loaded'], reverse=True):
                print(f"  • {fid}: {meta['records_loaded']:,} records, {meta['identities_found']} identities")
            
            # Convert to CorrelationResult format for compatibility
            result = CorrelationResult(
                wing_id=wing.wing_id,
                wing_name=wing.wing_name
            )
            
            # Set feathers processed info with full metadata
            result.feathers_processed = len(feathers_loaded)
            result.feather_metadata = feather_metadata  # Use the detailed metadata
            
            # Copy statistics
            if correlation_results.statistics:
                result.total_records_scanned = correlation_results.statistics.total_evidence
                result.execution_duration_seconds = correlation_results.statistics.execution_duration_seconds
            
            # Get minimum_matches from wing configuration (default 1)
            min_feathers_required = 1
            if hasattr(wing, 'correlation_rules') and hasattr(wing.correlation_rules, 'minimum_matches'):
                min_feathers_required = wing.correlation_rules.minimum_matches
            print(f"[Identity Engine] Minimum feathers required per match: {min_feathers_required}")
            
            # Count total anchors that meet criteria (for statistics)
            total_anchors = sum(len(identity.anchors) for identity in correlation_results.identities)
            print(f"[Identity Engine] Total anchors to process: {total_anchors:,}")
            
            # Check if we should use streaming mode (for large result sets)
            # Streaming writes matches directly to database instead of holding in memory
            use_streaming = total_anchors > 5000  # Stream if more than 5000 anchors
            db_writer = None
            result_id = None
            
            if use_streaming and hasattr(self, '_output_dir') and self._output_dir:
                try:
                    from .database_persistence import StreamingMatchWriter
                    from pathlib import Path as PathLib
                    db_path = PathLib(self._output_dir) / "correlation_results.db"
                    db_writer = StreamingMatchWriter(str(db_path), batch_size=1000)
                    
                    # Create result record with execution_id=0 (placeholder)
                    # The actual execution_id will be set when save_result() is called
                    # by the pipeline executor's _generate_report() method
                    result_id = db_writer.create_result(
                        0,  # Placeholder execution_id - will be updated by save_result()
                        wing.wing_id, 
                        wing.wing_name,
                        feathers_processed=len(feathers_loaded),
                        total_records_scanned=correlation_results.statistics.total_evidence if correlation_results.statistics else 0
                    )
                    result.enable_streaming(db_writer, result_id)
                    print(f"[Identity Engine] Streaming mode enabled - writing directly to database (result_id={result_id})")
                except Exception as e:
                    print(f"[Identity Engine] Could not enable streaming: {e}")
                    use_streaming = False
                    db_writer = None
            
            # Convert identities to CorrelationMatch objects
            # In streaming mode, matches are written directly to database
            feather_contribution = {}  # Track which feathers contributed
            matches_created = 0
            matches_skipped = 0
            
            # Progress tracking for large datasets
            total_identities = len(correlation_results.identities)
            identities_processed = 0
            last_progress_log = 0
            progress_interval = max(1, total_identities // 20)  # Log every 5%
            
            print(f"[Identity Engine] Processing {total_identities:,} identities into matches...")
            
            for identity in correlation_results.identities:
                for anchor in identity.anchors:
                    # Build feather_records from anchor rows
                    feather_records = {}
                    feather_rows = {}  # feather_id -> list of rows
                    
                    for row in anchor.rows:
                        feather_id = row.feather_id if hasattr(row, 'feather_id') else 'unknown'
                        
                        if feather_id not in feather_rows:
                            feather_rows[feather_id] = []
                        
                        # Get row data - only store essential fields to save memory
                        row_data = {}
                        if hasattr(row, 'original_data') and row.original_data:
                            # Only keep essential fields
                            for key in ['timestamp', 'name', 'path', 'hash', 'artifact']:
                                if key in row.original_data:
                                    row_data[key] = row.original_data[key]
                            # Keep first 5 other fields
                            other_keys = [k for k in row.original_data.keys() if k not in row_data][:5]
                            for key in other_keys:
                                row_data[key] = row.original_data[key]
                        
                        feather_rows[feather_id].append(row_data)
                        
                        # Track feather contribution
                        if feather_id not in feather_contribution:
                            feather_contribution[feather_id] = 0
                        feather_contribution[feather_id] += 1
                    
                    # Convert to feather_records format - only store first row per feather
                    # Use first row's data as representative, but include count
                    for feather_id, rows in feather_rows.items():
                        if rows:
                            feather_records[feather_id] = rows[0]
                            feather_records[feather_id]['_evidence_count'] = len(rows)
                    
                    # Check if anchor meets minimum feathers requirement from wing config
                    if len(feather_records) < min_feathers_required:
                        matches_skipped += 1
                        continue
                    
                    matches_created += 1
                    
                    # Calculate time spread
                    time_spread = 0.0
                    if anchor.start_time and anchor.end_time:
                        time_spread = (anchor.end_time - anchor.start_time).total_seconds()
                    
                    # Create proper CorrelationMatch object
                    match = CorrelationMatch(
                        match_id=str(uuid.uuid4()),
                        timestamp=anchor.start_time.isoformat() if anchor.start_time else "",
                        feather_records=feather_records,
                        match_score=1.0,  # Identity matches are high confidence
                        feather_count=len(feather_records),
                        time_spread_seconds=time_spread,
                        anchor_feather_id=anchor.rows[0].feather_id if anchor.rows and hasattr(anchor.rows[0], 'feather_id') else 'unknown',
                        anchor_artifact_type=anchor.primary_artifact or 'Unknown',
                        matched_application=identity.primary_name,
                        matched_file_path=identity.identity_value if identity.identity_type == 'path' else None,
                        confidence_score=1.0,
                        confidence_category="High",
                        semantic_data={
                            'identity_id': identity.identity_id,
                            'identity_type': identity.identity_type,
                            'anchor_id': anchor.anchor_id,
                            'evidence_count': len(anchor.rows),
                            'feathers_in_anchor': list(feather_records.keys())
                        }
                    )
                    result.add_match(match)  # This streams to DB if streaming mode is enabled
                
                # Progress logging after each identity
                identities_processed += 1
                if identities_processed - last_progress_log >= progress_interval:
                    progress_pct = (identities_processed / total_identities) * 100
                    print(f"[Identity Engine] ⏳ Progress: {progress_pct:.0f}% ({identities_processed:,}/{total_identities:,} identities, {matches_created:,} matches)")
                    last_progress_log = identities_processed
            
            # Final progress log
            print(f"[Identity Engine] ✓ Processing complete: {identities_processed:,} identities → {matches_created:,} matches")
            
            # Finalize streaming if enabled
            if use_streaming and db_writer:
                print(f"[Identity Engine] ⏳ Finalizing database write...")
                result.finalize_streaming()
                db_writer.update_result_count(
                    result_id, 
                    matches_created,
                    execution_duration=correlation_results.statistics.execution_duration_seconds if correlation_results.statistics else 0,
                    feather_metadata=feather_metadata
                )
                db_writer.close()
                print(f"[Identity Engine] ✓ Streaming complete - {matches_created:,} matches written to database")
            
            # Log feather contribution
            print(f"[Identity Engine] Feather contribution in results:")
            for fid, count in sorted(feather_contribution.items(), key=lambda x: x[1], reverse=True):
                print(f"  • {fid}: {count:,} evidence rows")
            
            print(f"[Identity Engine] Correlation complete:")
            print(f"  • Matches created: {matches_created:,}")
            print(f"  • Matches skipped (< {min_feathers_required} feathers): {matches_skipped:,}")
            print(f"  • Total matches stored: {result.total_matches:,}")
            if use_streaming:
                print(f"  • Storage mode: Database streaming (memory-efficient)")
            else:
                print(f"  • Storage mode: In-memory")
            
            return result
            
        except Exception as e:
            print(f"[Identity Engine] ERROR in execute_wing: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # Return empty result with error
            result = CorrelationResult(
                wing_id=wing.wing_id,
                wing_name=wing.wing_name
            )
            result.errors.append(f"Identity engine error: {str(e)}")
            return result
    
    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        """Parse timestamp from various formats"""
        if not value:
            return None
        
        if isinstance(value, datetime):
            return value
        
        timestamp_str = str(value).strip()
        
        if not timestamp_str or timestamp_str.lower() in ('none', 'null', 'n/a', ''):
            return None
        
        # Try numeric timestamps
        try:
            numeric_value = float(timestamp_str)
            
            if numeric_value > 10000000000000:  # Windows FILETIME
                unix_timestamp = (numeric_value - 116444736000000000) / 10000000
                parsed_time = datetime.fromtimestamp(unix_timestamp)
            elif numeric_value > 10000000000:  # Milliseconds
                parsed_time = datetime.fromtimestamp(numeric_value / 1000)
            elif numeric_value > 0:  # Seconds
                parsed_time = datetime.fromtimestamp(numeric_value)
            else:
                return None
            
            if 1970 <= parsed_time.year <= 2100:
                return parsed_time
            return None
            
        except (ValueError, OSError, OverflowError):
            pass
        
        # Try ISO format
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            pass
        
        return None
