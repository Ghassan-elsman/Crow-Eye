"""
Artifact Type Detector
Detects artifact types from Feather database filenames, table names, and metadata using fuzzy matching.
"""

import os
import sqlite3
import logging
from difflib import SequenceMatcher
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)


class ArtifactDetector:
    """Detects artifact types from Feather database filenames"""
    
    # Artifact type patterns with variations
    PATTERNS = {
        'Prefetch': ['prefetch', 'prefe', 'pf', 'prefetsh'],
        'SRUM': ['srum', 'srm', 'systemresourceusage'],
        'Logs': ['logs', 'log', 'event', 'events', 'eventlog'],
        'Jumplists': ['jumplist', 'jumplists', 'jmp', 'automaticdestinations'],
        'LNK': ['lnk', 'link', 'shortcut', 'shortcuts'],
        'ShimCache': ['shimcache', 'shim', 'appcompat', 'compatibility'],
        'AmCache': ['amcache', 'amcach', 'amc', 'applicationcache'],
        'MFT': ['mft', 'masterfiletable', 'filesystem'],
        'USN': ['usn', 'journal', 'usnjournal', 'changejournal']
    }
    
    # Table name patterns for exact and partial matching
    TABLE_PATTERNS = {
        'Prefetch': {
            'exact': ['prefetch', 'prefetch_data', 'windows_prefetch'],
            'partial': ['prefetch', 'pf']
        },
        'SystemLogs': {
            'exact': ['systemlogs', 'system_logs', 'systemlog', 'system_log', 'syslog'],
            'partial': ['systemlog', 'syslog']
        },
        'SecurityLogs': {
            'exact': ['securitylogs', 'security_logs', 'securitylog', 'security_log'],
            'partial': ['securitylog', 'security']
        },
        'ApplicationLogs': {
            'exact': ['applicationlogs', 'application_logs', 'applicationlog', 'application_log', 'applog'],
            'partial': ['applicationlog', 'applog']
        },
        'Logs': {
            'exact': ['eventlog', 'event_log', 'evtx', 'logs', 'log'],
            'partial': ['evtx', 'log', 'event']
        },
        'MFT': {
            'exact': ['mft', 'mft_records', 'mft_entries', 'master_file_table', 'mft_usn_correlated'],
            'partial': ['mft']
        },
        'SRUM': {
            'exact': ['srum', 'srum_data', 'system_resource'],
            'partial': ['srum']
        },
        'SRUM_ApplicationUsage': {
            'exact': ['srum_application_usage', 'srum_app_usage', 'application_usage'],
            'partial': ['srum_application', 'app_usage']
        },
        'SRUM_NetworkDataUsage': {
            'exact': ['srum_network_data_usage', 'srum_network_usage', 'network_data_usage'],
            'partial': ['srum_network', 'network_usage']
        },
        'AmCache': {
            'exact': ['amcache', 'amcache_entries', 'application_cache'],
            'partial': ['amcache', 'cache']
        },
        'InventoryApplication': {
            'exact': ['inventoryapplication', 'inventory_application'],
            'partial': ['inventoryapplication', 'inventory_app']
        },
        'InventoryApplicationFile': {
            'exact': ['inventoryapplicationfile', 'inventory_application_file'],
            'partial': ['inventoryapplicationfile', 'inventory_app_file']
        },
        'InventoryApplicationShortcut': {
            'exact': ['inventoryapplicationshortcut', 'inventory_application_shortcut'],
            'partial': ['inventoryapplicationshortcut', 'inventory_shortcut']
        },
        'UserAssist': {
            'exact': ['userassist', 'user_assist'],
            'partial': ['userassist', 'assist']
        },
        'ShellBags': {
            'exact': ['shellbags', 'shell_bags', 'shellbag'],
            'partial': ['shellbag', 'bags']
        },
        'MUICache': {
            'exact': ['muicache', 'mui_cache'],
            'partial': ['muicache', 'mui']
        },
        'RecentDocs': {
            'exact': ['recentdocs', 'recent_docs', 'recentdocuments'],
            'partial': ['recentdocs', 'recent']
        },
        'OpenSaveMRU': {
            'exact': ['opensavemru', 'open_save_mru', 'opensave'],
            'partial': ['opensavemru', 'opensave']
        },
        'LastSaveMRU': {
            'exact': ['lastsavemru', 'last_save_mru', 'lastsave'],
            'partial': ['lastsavemru', 'lastsave']
        },
        'TypedPaths': {
            'exact': ['typedpaths', 'typed_paths'],
            'partial': ['typedpaths', 'typed']
        },
        'WordWheelQuery': {
            'exact': ['wordwheelquery', 'word_wheel_query', 'wordwheel'],
            'partial': ['wordwheelquery', 'wordwheel']
        },
        'BAM': {
            'exact': ['bam', 'background_activity_moderator'],
            'partial': ['bam']
        },
        'InstalledSoftware': {
            'exact': ['installedsoftware', 'installed_software'],
            'partial': ['installedsoftware', 'installed']
        },
        'SystemServices': {
            'exact': ['systemservices', 'system_services'],
            'partial': ['systemservices', 'services']
        },
        'AutoStartPrograms': {
            'exact': ['autostartprograms', 'auto_start_programs', 'autostart'],
            'partial': ['autostartprograms', 'autostart']
        },
        'RecycleBin': {
            'exact': ['recyclebin', 'recycle_bin', 'recycle', 'recycle_bin_entries'],
            'partial': ['recycle']
        },
        'Registry': {
            'exact': ['registry', 'reg_data', 'hive', 'registry_data'],
            'partial': ['registry', 'reg']
        },
        'BrowserHistory': {
            'exact': ['browser', 'history', 'web_history', 'browser_history'],
            'partial': ['browser', 'history']
        },
        'ShimCache': {
            'exact': ['shimcache', 'shimcache_entries', 'shim_cache'],
            'partial': ['shimcache', 'shim']
        },
        'LNK': {
            'exact': ['lnk', 'shortcut', 'link_files', 'jlce'],
            'partial': ['lnk', 'shortcut']
        },
        'Jumplists': {
            'exact': ['jumplists', 'jump_lists', 'automatic_destinations'],
            'partial': ['jumplist', 'jump']
        },
        'AutomaticJumplist': {
            'exact': ['automaticjumplist', 'automatic_jumplist', 'automatic_destinations'],
            'partial': ['automaticjumplist', 'automatic_jump']
        },
        'CustomJumplist': {
            'exact': ['customjumplist', 'custom_jumplist', 'custom_jlce'],
            'partial': ['customjumplist', 'custom_jump']
        },
    }
    
    @classmethod
    def detect_from_metadata(cls, db_path: str) -> Optional[str]:
        """
        Detect artifact type from feather_metadata table.
        
        Args:
            db_path: Path to database file
            
        Returns:
            Artifact type from metadata, or None if no metadata table exists
            
        Examples:
            Database with metadata → "Prefetch"
            Database without metadata → None
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Check if metadata table exists
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='feather_metadata'"
            )
            if not cursor.fetchone():
                conn.close()
                return None
            
            # Read artifact_type from metadata
            cursor.execute("SELECT artifact_type FROM feather_metadata LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0]:
                artifact_type = row[0]
                logger.info(f"Detected artifact type from metadata: {artifact_type}")
                return artifact_type
            
            return None
            
        except sqlite3.Error as e:
            logger.warning(f"Failed to read metadata from {db_path}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error reading metadata from {db_path}: {e}")
            return None
    
    @classmethod
    def detect_from_table_name(cls, db_path: str) -> Tuple[str, str]:
        """
        Detect artifact type from table names in database.
        
        Args:
            db_path: Path to database file
            
        Returns:
            Tuple of (artifact_type, confidence)
            - artifact_type: Detected type or 'Unknown'
            - confidence: 'high', 'medium', or 'low'
            
        Examples:
            Database with "prefetch_data" table → ("Prefetch", "high")
            Database with "data_log" table → ("SystemLog", "medium")
            Database with "generic_data" table → ("Unknown", "low")
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all table names
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            # Filter out system tables
            data_tables = [
                t for t in tables 
                if t not in ['feather_metadata', 'sqlite_sequence', 
                            'import_history', 'data_lineage']
            ]
            
            if not data_tables:
                logger.warning(f"No data tables found in {db_path}")
                return ("Unknown", "low")
            
            # Try to match table names against patterns
            for table_name in data_tables:
                artifact_type, confidence = cls._match_table_pattern(table_name.lower())
                if artifact_type != "Unknown":
                    logger.info(
                        f"Detected artifact type from table '{table_name}': "
                        f"{artifact_type} ({confidence} confidence)"
                    )
                    return (artifact_type, confidence)
            
            logger.info(f"No matching table patterns found in {db_path}")
            return ("Unknown", "low")
            
        except sqlite3.Error as e:
            logger.warning(f"Failed to detect from table names in {db_path}: {e}")
            return ("Unknown", "low")
        except Exception as e:
            logger.warning(f"Unexpected error detecting from table names in {db_path}: {e}")
            return ("Unknown", "low")
    
    @classmethod
    def _match_table_pattern(cls, table_name: str) -> Tuple[str, str]:
        """
        Match table name against known patterns.
        
        Args:
            table_name: Table name in lowercase
            
        Returns:
            Tuple of (artifact_type, confidence)
        """
        # Try exact matches first (high confidence)
        for artifact_type, patterns in cls.TABLE_PATTERNS.items():
            if table_name in patterns['exact']:
                return (artifact_type, "high")
        
        # Try partial matches (medium confidence)
        for artifact_type, patterns in cls.TABLE_PATTERNS.items():
            for pattern in patterns['partial']:
                if pattern in table_name:
                    return (artifact_type, "medium")
        
        return ("Unknown", "low")
    
    @classmethod
    def detect_from_filename(cls, filename: str) -> Tuple[str, str]:
        """
        Detect artifact type from Feather database filename.
        
        Args:
            filename: Database filename (e.g., "Prefetch.db", "feather_srum.db")
        
        Returns:
            Tuple of (artifact_type, confidence)
            - artifact_type: Detected type or 'Unknown'
            - confidence: 'high', 'medium', or 'low'
        
        Examples:
            "Prefetch.db" → ("Prefetch", "high")
            "prefe.db" → ("Prefetch", "medium")
            "data.db" → ("Unknown", "low")
        """
        # Extract filename without extension and clean it
        filename_clean = cls._clean_filename(filename)
        
        if not filename_clean:
            return ('Unknown', 'low')
        
        # Find best match
        best_match = None
        best_score = 0
        
        for artifact_type, variations in cls.PATTERNS.items():
            for pattern in variations:
                # Calculate similarity ratio
                ratio = SequenceMatcher(None, filename_clean, pattern).ratio()
                
                # Boost score if pattern is substring
                if pattern in filename_clean:
                    ratio = max(ratio, 0.85)
                
                # Boost score if exact match
                if filename_clean == pattern:
                    ratio = 1.0
                
                if ratio > best_score:
                    best_score = ratio
                    best_match = artifact_type
        
        # Determine confidence based on score
        if best_score >= 0.8:
            confidence = 'high'
        elif best_score >= 0.5:
            confidence = 'medium'
        else:
            confidence = 'low'
            best_match = 'Unknown'
        
        return (best_match, confidence)
    
    @classmethod
    def _clean_filename(cls, filename: str) -> str:
        """
        Clean filename for comparison.
        
        - Remove extension
        - Convert to lowercase
        - Remove separators (_, -, spaces)
        """
        # Get basename if full path provided
        filename = os.path.basename(filename)
        
        # Remove extension
        filename = os.path.splitext(filename)[0]
        
        # Convert to lowercase
        filename = filename.lower()
        
        # Remove separators
        filename = filename.replace('_', '').replace('-', '').replace(' ', '')
        
        return filename
    
    @classmethod
    def get_all_artifact_types(cls) -> List[str]:
        """Get list of all supported artifact types including enhanced subtypes"""
        # Basic artifact types
        basic_types = list(cls.PATTERNS.keys())
        
        # Enhanced subtypes from feather mappings
        enhanced_types = [
            # Registry subtypes
            'UserAssist', 'ShellBags', 'MUICache', 'RecentDocs', 'OpenSaveMRU', 
            'LastSaveMRU', 'TypedPaths', 'WordWheelQuery', 'BAM', 'InstalledSoftware',
            'SystemServices', 'AutoStartPrograms',
            
            # SRUM subtypes  
            'SRUM_ApplicationUsage', 'SRUM_NetworkDataUsage',
            
            # Log subtypes
            'SecurityLogs', 'SystemLogs', 'ApplicationLogs',
            
            # AmCache subtypes
            'InventoryApplication', 'InventoryApplicationFile', 'InventoryApplicationShortcut',
            
            # Jumplist subtypes
            'AutomaticJumplist', 'CustomJumplist',
            
            # Additional types
            'Registry', 'RecycleBin', 'BrowserHistory'
        ]
        
        # Combine and remove duplicates while preserving order
        all_types = []
        seen = set()
        
        # Add basic types first
        for artifact_type in basic_types:
            if artifact_type not in seen:
                all_types.append(artifact_type)
                seen.add(artifact_type)
        
        # Add enhanced types
        for artifact_type in enhanced_types:
            if artifact_type not in seen:
                all_types.append(artifact_type)
                seen.add(artifact_type)
        
        return sorted(all_types)
    
    @classmethod
    def get_confidence_description(cls, confidence: str) -> str:
        """Get human-readable description of confidence level"""
        descriptions = {
            'high': 'High confidence - Clear match found',
            'medium': 'Medium confidence - Partial match, please verify',
            'low': 'Low confidence - Please select manually'
        }
        return descriptions.get(confidence, 'Unknown confidence')
    
    @classmethod
    def get_confidence_icon(cls, confidence: str) -> str:
        """Get icon for confidence level"""
        icons = {
            'high': '✓',
            'medium': '●',
            'low': '○'
        }
        return icons.get(confidence, '⚠')
    
    @classmethod
    def detect_artifact_type(cls, db_path: str) -> Tuple[Optional[str], float, str]:
        """
        Detect artifact type from database using multiple methods.
        
        Args:
            db_path: Path to database file
            
        Returns:
            Tuple of (artifact_type, confidence_score, detection_reason)
            - artifact_type: Detected type or None if unknown
            - confidence_score: 0.0-1.0 confidence level
            - detection_reason: Human-readable explanation
            
        Examples:
            Database with metadata → ("Prefetch", 1.0, "From metadata table")
            Database with prefetch_data table → ("Prefetch", 0.9, "From table name match")
            Database with unknown schema → (None, 0.0, "No matching patterns")
        """
        # Try metadata first (highest confidence)
        artifact_type = cls.detect_from_metadata(db_path)
        if artifact_type:
            return (artifact_type, 1.0, "Detected from feather_metadata table")
        
        # Try table name detection (high confidence)
        artifact_type, confidence = cls.detect_from_table_name(db_path)
        if artifact_type != "Unknown" and confidence in ["high", "medium"]:
            confidence_score = 0.9 if confidence == "high" else 0.7
            return (artifact_type, confidence_score, f"Detected from table names ({confidence} confidence)")
        
        # Try filename detection (medium confidence)
        filename = os.path.basename(db_path)
        artifact_type, confidence = cls.detect_from_filename(filename)
        if artifact_type != "Unknown" and confidence in ["high", "medium"]:
            confidence_score = 0.8 if confidence == "high" else 0.6
            return (artifact_type, confidence_score, f"Detected from filename ({confidence} confidence)")
        
        # Try column pattern matching (lower confidence)
        artifact_type, confidence_score = cls._detect_from_columns(db_path)
        if artifact_type:
            return (artifact_type, confidence_score, "Detected from column patterns")
        
        # No detection
        return (None, 0.0, "No matching patterns found")
    
    @classmethod
    def _detect_from_columns(cls, db_path: str) -> Tuple[Optional[str], float]:
        """
        Detect artifact type from column patterns.
        
        Args:
            db_path: Path to database file
            
        Returns:
            Tuple of (artifact_type, confidence_score)
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
            # Filter out system tables
            data_tables = [
                t for t in tables 
                if t not in ['feather_metadata', 'sqlite_sequence', 
                            'import_history', 'data_lineage']
            ]
            
            if not data_tables:
                conn.close()
                return (None, 0.0)
            
            # Get columns from first data table
            table_name = data_tables[0]
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1].lower() for row in cursor.fetchall()]
            
            conn.close()
            
            # Match column patterns
            scores = cls._match_column_patterns(columns)
            
            if scores:
                best_match = max(scores.items(), key=lambda x: x[1])
                artifact_type, score = best_match
                if score >= 0.5:
                    return (artifact_type, score * 0.7)  # Reduce confidence for column-only match
            
            return (None, 0.0)
            
        except Exception as e:
            logger.warning(f"Error detecting from columns in {db_path}: {e}")
            return (None, 0.0)
    
    @classmethod
    def _match_column_patterns(cls, columns: List[str]) -> Dict[str, float]:
        """
        Match column names against known patterns.
        
        Args:
            columns: List of column names (lowercase)
            
        Returns:
            Dictionary of artifact_type -> confidence_score
        """
        # Column signature patterns
        COLUMN_SIGNATURES = {
            'MFT': ['mft_record_number', 'file_reference', 'parent_reference', 'usn'],
            'Prefetch': ['executable_name', 'run_count', 'last_run_time', 'prefetch_hash'],
            'SRUM': ['app_id', 'bytes_sent', 'bytes_received', 'network_adapter'],
            'Registry': ['key_path', 'value_name', 'value_data', 'hive'],
            'BrowserHistory': ['url', 'visit_count', 'last_visit_time', 'title'],
            'AmCache': ['sha1', 'file_size', 'product_name', 'publisher'],
            'ShimCache': ['path', 'last_modified', 'file_size', 'shimcache_entry'],
            'Jumplists': ['app_id', 'target_path', 'access_time', 'jumplist_type'],
            'LNK': ['target_path', 'creation_time', 'access_time', 'link_flags'],
            'USN': ['usn', 'file_reference_number', 'reason', 'source_info'],
            'Logs': ['event_id', 'source', 'log_name', 'event_data']
        }
        
        scores = {}
        
        for artifact_type, signature_columns in COLUMN_SIGNATURES.items():
            # Count how many signature columns are present
            matches = sum(1 for sig_col in signature_columns if sig_col in columns)
            
            if matches > 0:
                # Calculate confidence based on match ratio
                confidence = matches / len(signature_columns)
                scores[artifact_type] = confidence
        
        return scores
    
    @classmethod
    def generate_feather_name(cls, artifact_type: str) -> str:
        """
        Generate feather name from artifact type.
        
        Args:
            artifact_type: Type of artifact (e.g., "MFT", "Prefetch")
            
        Returns:
            Generated feather name (e.g., "MFT_feather", "Prefetch_feather")
        """
        if not artifact_type or artifact_type == "Unknown":
            return "Unknown_feather"
        
        # Clean artifact type and format
        clean_type = artifact_type.strip().replace(' ', '_')
        return f"{clean_type}_feather"
    
    @classmethod
    def get_table_names(cls, db_path: str) -> List[str]:
        """
        Get all table names from database.
        
        Args:
            db_path: Path to database file
            
        Returns:
            List of table names
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
            conn.close()
            return tables
            
        except Exception as e:
            logger.warning(f"Error getting table names from {db_path}: {e}")
            return []
    
    @classmethod
    def get_column_names(cls, db_path: str, table_name: str) -> List[str]:
        """
        Get column names for specific table.
        
        Args:
            db_path: Path to database file
            table_name: Name of table
            
        Returns:
            List of column names
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            
            conn.close()
            return columns
            
        except Exception as e:
            logger.warning(f"Error getting column names from {db_path}.{table_name}: {e}")
            return []
    
    @classmethod
    def test_detection(cls) -> Dict[str, Tuple[str, str]]:
        """
        Test detection with common filenames.
        Returns dictionary of filename -> (detected_type, confidence)
        """
        test_cases = [
            "Prefetch.db",
            "feather_prefetch.db",
            "PREFETCH_DATA.db",
            "prefe.db",
            "SRUM.db",
            "srum_network.db",
            "AmCache.db",
            "EventLogs.db",
            "Jumplists.db",
            "LNK_Files.db",
            "ShimCache.db",
            "MFT.db",
            "USN_Journal.db",
            "data.db",
            "forensics.db"
        ]
        
        results = {}
        for filename in test_cases:
            results[filename] = cls.detect_from_filename(filename)
        
        return results
