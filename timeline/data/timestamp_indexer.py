"""
Timestamp Indexer for Timeline Feature
=======================================

This module provides timestamp column mapping and indexing functionality for the
forensic timeline visualization feature. It defines which columns contain timestamps
in each artifact database and provides methods to create indexes for efficient
time-range queries.

The TimestampIndexer is responsible for:
- Defining timestamp column mappings for all artifact types
- Automatically detecting timestamp columns in databases
- Creating indexes on timestamp columns for query optimization
- Storing and retrieving index metadata to avoid re-indexing

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import sqlite3
import os
import json
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# Configure logger
logger = logging.getLogger(__name__)


class TimestampIndexer:
    """
    Manages timestamp column mappings and indexing for artifact databases.
    
    This class provides comprehensive timestamp column definitions for all artifact
    types and methods to create database indexes for efficient time-range queries.
    """
    
    # Comprehensive timestamp column mappings for all artifact types
    # Format: artifact_type -> [(table_name, timestamp_column, timestamp_type, description)]
    # Updated to match actual database schemas in case directory
    TIMESTAMP_MAPPINGS = {
        'Prefetch': [
            ('prefetch_data', 'last_executed', 'executed', 'Last execution time'),
            ('prefetch_data', 'created_on', 'created', 'File creation time'),
            ('prefetch_data', 'modified_on', 'modified', 'File modification time'),
        ],
        'LNK': [
            ('JLCE', 'Time_Creation', 'created', 'Link file creation time'),
            ('JLCE', 'Time_Modification', 'modified', 'Link file modification time'),
            ('JLCE', 'Time_Access', 'accessed', 'Link file access time'),
        ],
        'Registry': [
            ('UserAssist', 'timestamp', 'various', 'UserAssist timestamp'),
            ('MUICache', 'timestamp', 'various', 'MUICache timestamp'),
            ('InstalledSoftware', 'timestamp', 'various', 'Installed software timestamp'),
        ],
        'BAM': [
            ('BAM', 'timestamp', 'executed', 'Background Activity Moderator execution time'),
        ],
        'ShellBag': [
            ('Shellbags', 'created_date', 'created', 'First interaction time'),
            ('Shellbags', 'modified_date', 'modified', 'Last interaction time'),
            ('Shellbags', 'access_date', 'accessed', 'Access time'),
        ],
        'SRUM': [
            ('srum_application_usage', 'timestamp', 'various', 'Application usage timestamp'),
            ('srum_network_connectivity', 'timestamp', 'various', 'Network connectivity timestamp'),
            ('srum_network_data_usage', 'timestamp', 'various', 'Network data usage timestamp'),
            ('srum_energy_usage', 'timestamp', 'various', 'Energy usage timestamp'),
        ],
        'USN': [
            ('journal_events', 'timestamp', 'various', 'USN journal entry timestamp'),
        ],
        'MFT': [
            ('mft_records', 'created_time', 'created', 'File creation time'),
            ('mft_records', 'modified_time', 'modified', 'File modification time'),
            ('mft_records', 'accessed_time', 'accessed', 'File access time'),
            ('mft_records', 'mft_modified_time', 'mft_modified', 'MFT record modification time'),
        ],
    }
    
    # Primary timestamp columns for each artifact type (used for main timeline display)
    # Updated to match actual database schemas
    PRIMARY_TIMESTAMPS = {
        'Prefetch': ('prefetch_data', 'last_executed'),
        'LNK': ('JLCE', 'Time_Modification'),
        'Registry': ('UserAssist', 'timestamp'),
        'BAM': ('BAM', 'timestamp'),
        'ShellBag': ('Shellbags', 'modified_date'),
        'SRUM': ('srum_application_usage', 'timestamp'),
        'USN': ('journal_events', 'timestamp'),
        'MFT': ('mft_records', 'modified_time'),
    }
    
    def __init__(self, artifacts_dir: str, timeline_dir: str):
        """
        Initialize TimestampIndexer.
        
        Args:
            artifacts_dir: Path to directory containing artifact databases
            timeline_dir: Path to timeline directory for storing index metadata
        """
        self.artifacts_dir = artifacts_dir
        self.timeline_dir = timeline_dir
        self.index_metadata_file = os.path.join(timeline_dir, 'index_metadata.json')
        
        # Load existing index metadata
        self.index_metadata = self._load_index_metadata()
        
        logger.info(f"TimestampIndexer initialized for artifacts in: {artifacts_dir}")
    
    def _load_index_metadata(self) -> Dict:
        """
        Load index metadata from file.
        
        Returns:
            Dict: Index metadata dictionary
        """
        if os.path.exists(self.index_metadata_file):
            try:
                with open(self.index_metadata_file, 'r') as f:
                    metadata = json.load(f)
                    logger.debug(f"Loaded index metadata from {self.index_metadata_file}")
                    return metadata
            except Exception as e:
                logger.warning(f"Failed to load index metadata: {e}")
        
        return {
            'version': '1.0',
            'created_at': datetime.now().isoformat(),
            'indexes': {}
        }
    
    def _save_index_metadata(self):
        """Save index metadata to file."""
        try:
            # Ensure timeline directory exists
            os.makedirs(self.timeline_dir, exist_ok=True)
            
            # Update last modified time
            self.index_metadata['last_modified'] = datetime.now().isoformat()
            
            with open(self.index_metadata_file, 'w') as f:
                json.dump(self.index_metadata, f, indent=2)
            
            logger.debug(f"Saved index metadata to {self.index_metadata_file}")
        
        except Exception as e:
            logger.error(f"Failed to save index metadata: {e}")
    
    def get_timestamp_mappings(self, artifact_type: str) -> List[Tuple[str, str, str, str]]:
        """
        Get timestamp column mappings for an artifact type.
        
        Args:
            artifact_type: Type of artifact (e.g., 'Prefetch', 'LNK')
        
        Returns:
            List[Tuple[str, str, str, str]]: List of (table_name, column_name, timestamp_type, description)
        """
        return self.TIMESTAMP_MAPPINGS.get(artifact_type, [])
    
    def get_primary_timestamp(self, artifact_type: str) -> Optional[Tuple[str, str]]:
        """
        Get primary timestamp column for an artifact type.
        
        Args:
            artifact_type: Type of artifact
        
        Returns:
            Optional[Tuple[str, str]]: (table_name, column_name) or None
        """
        return self.PRIMARY_TIMESTAMPS.get(artifact_type)
    
    def detect_timestamp_columns(self, db_path: str, artifact_type: str) -> List[Tuple[str, str]]:
        """
        Automatically detect timestamp columns in a database.
        
        This method queries the database schema to find columns that likely contain
        timestamps based on column names and data types.
        
        Args:
            db_path: Path to database file
            artifact_type: Type of artifact
        
        Returns:
            List[Tuple[str, str]]: List of (table_name, column_name) tuples
        """
        detected_columns = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Common timestamp column name patterns
            timestamp_patterns = [
                'time', 'date', 'timestamp', 'created', 'modified', 'accessed',
                'executed', 'last_run', 'first_run', 'last_write', 'interacted'
            ]
            
            for table in tables:
                # Get table schema
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                
                for col in columns:
                    col_name = col[1].lower()
                    
                    # Check if column name matches timestamp patterns
                    if any(pattern in col_name for pattern in timestamp_patterns):
                        detected_columns.append((table, col[1]))
                        logger.debug(f"Detected timestamp column: {table}.{col[1]}")
            
            conn.close()
        
        except sqlite3.Error as e:
            logger.error(f"Failed to detect timestamp columns in {db_path}: {e}")
        
        return detected_columns
    
    def create_indexes(
        self,
        db_path: str,
        artifact_type: str,
        progress_callback: Optional[callable] = None
    ) -> bool:
        """
        Create indexes on timestamp columns in a database.
        
        Args:
            db_path: Path to database file
            artifact_type: Type of artifact
            progress_callback: Optional callback function(current, total, message)
        
        Returns:
            bool: True if successful, False otherwise
        """
        # Check if already indexed
        db_filename = os.path.basename(db_path)
        if self._is_indexed(db_filename):
            logger.info(f"Database {db_filename} already indexed, skipping")
            return True
        
        logger.info(f"Creating indexes for {artifact_type} database: {db_filename}")
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get timestamp mappings for this artifact type
            mappings = self.get_timestamp_mappings(artifact_type)
            
            if not mappings:
                logger.warning(f"No timestamp mappings defined for {artifact_type}")
                return False
            
            total_indexes = len(mappings)
            created_indexes = []
            
            for idx, (table_name, column_name, timestamp_type, description) in enumerate(mappings):
                if progress_callback:
                    progress_callback(idx + 1, total_indexes, f"Indexing {table_name}.{column_name}")
                
                # Check if table exists
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if not cursor.fetchone():
                    logger.debug(f"Table {table_name} not found in {db_filename}, skipping")
                    continue
                
                # Check if column exists
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [col[1] for col in cursor.fetchall()]
                if column_name not in columns:
                    logger.debug(f"Column {column_name} not found in {table_name}, skipping")
                    continue
                
                # Create index
                index_name = f"idx_timeline_{table_name}_{column_name}"
                
                try:
                    cursor.execute(f"""
                        CREATE INDEX IF NOT EXISTS {index_name}
                        ON {table_name}({column_name})
                    """)
                    
                    created_indexes.append({
                        'index_name': index_name,
                        'table_name': table_name,
                        'column_name': column_name,
                        'timestamp_type': timestamp_type,
                        'description': description
                    })
                    
                    logger.debug(f"Created index: {index_name}")
                
                except sqlite3.Error as e:
                    logger.warning(f"Failed to create index {index_name}: {e}")
                    continue
            
            conn.commit()
            conn.close()
            
            # Save index metadata
            self.index_metadata['indexes'][db_filename] = {
                'artifact_type': artifact_type,
                'indexed_at': datetime.now().isoformat(),
                'indexes': created_indexes
            }
            self._save_index_metadata()
            
            logger.info(f"Successfully created {len(created_indexes)} indexes for {db_filename}")
            return True
        
        except sqlite3.Error as e:
            logger.error(f"Failed to create indexes for {db_path}: {e}")
            return False
    
    def _is_indexed(self, db_filename: str) -> bool:
        """
        Check if a database has already been indexed.
        
        Args:
            db_filename: Database filename
        
        Returns:
            bool: True if indexed, False otherwise
        """
        return db_filename in self.index_metadata.get('indexes', {})
    
    def get_index_info(self, db_filename: str) -> Optional[Dict]:
        """
        Get index information for a database.
        
        Args:
            db_filename: Database filename
        
        Returns:
            Optional[Dict]: Index information or None if not indexed
        """
        return self.index_metadata.get('indexes', {}).get(db_filename)
    
    def clear_index_metadata(self, db_filename: Optional[str] = None):
        """
        Clear index metadata for a database or all databases.
        
        Args:
            db_filename: Database filename, or None to clear all
        """
        if db_filename:
            if db_filename in self.index_metadata.get('indexes', {}):
                del self.index_metadata['indexes'][db_filename]
                self._save_index_metadata()
                logger.info(f"Cleared index metadata for {db_filename}")
        else:
            self.index_metadata['indexes'] = {}
            self._save_index_metadata()
            logger.info("Cleared all index metadata")
    
    def get_all_timestamp_columns(self, artifact_type: str) -> List[str]:
        """
        Get all timestamp column names for an artifact type.
        
        Args:
            artifact_type: Type of artifact
        
        Returns:
            List[str]: List of column names
        """
        mappings = self.get_timestamp_mappings(artifact_type)
        return [col_name for _, col_name, _, _ in mappings]
    
    def get_timestamp_type(self, artifact_type: str, table_name: str, column_name: str) -> Optional[str]:
        """
        Get timestamp type for a specific column.
        
        Args:
            artifact_type: Type of artifact
            table_name: Table name
            column_name: Column name
        
        Returns:
            Optional[str]: Timestamp type ('created', 'modified', 'accessed', etc.) or None
        """
        mappings = self.get_timestamp_mappings(artifact_type)
        
        for tbl, col, ts_type, _ in mappings:
            if tbl == table_name and col == column_name:
                return ts_type
        
        return None
