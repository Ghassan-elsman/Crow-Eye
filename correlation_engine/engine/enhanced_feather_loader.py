"""
Enhanced Feather Loader with identifier extraction capabilities.

This module extends the basic Feather Loader with column detection and value extraction
for the Crow-Eye Correlation Engine's identifier extraction features.
"""

import logging
import sqlite3
from typing import List, Dict, Any, Optional, Iterator
from pathlib import Path

from correlation_engine.engine.data_structures import DetectedColumns, ExtractedValues
from correlation_engine.engine.timestamp_parser import TimestampParser
from correlation_engine.config.identifier_extraction_config import WingsConfig

logger = logging.getLogger(__name__)


class EnhancedFeatherLoader:
    """
    Load Feather tables and detect/extract identifier columns.
    
    Responsibilities:
    - Open Feather databases in read-only mode
    - Detect name, path, and timestamp columns
    - Extract values from detected columns
    - Parse timestamps using TimestampParser
    """
    
    # Column detection patterns
    NAME_PATTERNS = ['name', 'executable', 'filename', 'exe_name', 'application', 'app_name', 'process_name']
    PATH_PATTERNS = ['path', 'filepath', 'full_path', 'exe_path', 'executable_path', 'file_path', 'full_file_path']
    TIMESTAMP_PATTERNS = ['timestamp', 'time', 'datetime', 'execution_time', 'last_run', 'modified_time', 
                         'created_time', 'accessed_time', 'run_time', 'exec_time']
    
    def __init__(self, config: WingsConfig, timestamp_parser: Optional[TimestampParser] = None):
        """
        Initialize enhanced feather loader.
        
        Args:
            config: Wings configuration
            timestamp_parser: Optional timestamp parser (creates default if not provided)
        """
        self.config = config
        self.timestamp_parser = timestamp_parser or TimestampParser(
            custom_formats=config.timestamp_parsing.custom_formats
        )
        self.connection = None
        self.current_table = None
        
        logger.info("EnhancedFeatherLoader initialized")
    
    def load_table(self, table_path: str, artifact_name: Optional[str] = None) -> Iterator[ExtractedValues]:
        """
        Load and yield rows from a Feather table.
        
        Args:
            table_path: Path to Feather database
            artifact_name: Optional artifact name (e.g., "prefetch", "srum")
            
        Yields:
            ExtractedValues for each row
        """
        if not Path(table_path).exists():
            logger.error(f"Feather table not found: {table_path}")
            raise FileNotFoundError(f"Feather table not found: {table_path}")
        
        # Infer artifact name from path if not provided
        if artifact_name is None:
            artifact_name = Path(table_path).stem
        
        logger.info(f"Loading Feather table: {table_path} (artifact: {artifact_name})")
        
        try:
            # Connect to database in read-only mode
            self.connection = sqlite3.connect(f"file:{table_path}?mode=ro", uri=True)
            self.connection.row_factory = sqlite3.Row
            self.current_table = artifact_name
            
            # Detect columns
            detected_columns = self.detect_columns()
            
            if not detected_columns.has_names() and not detected_columns.has_paths():
                logger.warning(f"No name or path columns detected in {table_path}")
            
            # Query all rows
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM feather_data")
            
            row_count = 0
            for row in cursor.fetchall():
                row_count += 1
                extracted = self.extract_values(row, detected_columns, artifact_name)
                
                if extracted.has_data():
                    yield extracted
            
            logger.info(f"Loaded {row_count} rows from {table_path}")
            
        except sqlite3.Error as e:
            logger.error(f"Database error loading {table_path}: {e}")
            raise
        
        finally:
            if self.connection:
                self.connection.close()
                self.connection = None
    
    def detect_columns(self) -> DetectedColumns:
        """
        Detect name, path, and timestamp columns in current table.
        
        Returns:
            DetectedColumns with identified column names
        """
        if not self.connection:
            raise RuntimeError("No active database connection")
        
        # Get all column names
        cursor = self.connection.cursor()
        cursor.execute("PRAGMA table_info(feather_data)")
        all_columns = [row[1].lower() for row in cursor.fetchall()]  # row[1] is column name
        
        detected = DetectedColumns()
        
        # Check for manual column specification
        if self.config.has_manual_name_columns():
            detected.name_columns = [
                col for col in self.config.identifier_extraction.name_columns
                if col.lower() in all_columns
            ]
            missing = set(self.config.identifier_extraction.name_columns) - set(detected.name_columns)
            if missing:
                logger.warning(f"Specified name columns not found: {missing}")
        else:
            # Auto-detect name columns
            detected.name_columns = [
                col for col in all_columns
                if any(pattern in col for pattern in self.NAME_PATTERNS)
            ]
        
        if self.config.has_manual_path_columns():
            detected.path_columns = [
                col for col in self.config.identifier_extraction.path_columns
                if col.lower() in all_columns
            ]
            missing = set(self.config.identifier_extraction.path_columns) - set(detected.path_columns)
            if missing:
                logger.warning(f"Specified path columns not found: {missing}")
        else:
            # Auto-detect path columns
            detected.path_columns = [
                col for col in all_columns
                if any(pattern in col for pattern in self.PATH_PATTERNS)
            ]
        
        # Auto-detect timestamp columns (always auto-detect)
        detected.timestamp_columns = [
            col for col in all_columns
            if any(pattern in col for pattern in self.TIMESTAMP_PATTERNS)
        ]
        
        logger.info(f"Detected columns - Names: {detected.name_columns}, "
                   f"Paths: {detected.path_columns}, Timestamps: {detected.timestamp_columns}")
        
        return detected
    
    def extract_values(self, row: sqlite3.Row, columns: DetectedColumns, 
                      artifact_name: str) -> ExtractedValues:
        """
        Extract name, path, and timestamp values from a Feather row.
        
        Args:
            row: Database row
            columns: Detected columns
            artifact_name: Name of the artifact
            
        Returns:
            ExtractedValues with extracted data
        """
        # Convert Row to dict for easier access
        row_dict = dict(row)
        
        extracted = ExtractedValues(
            artifact_name=artifact_name,
            table_name=self.current_table or artifact_name,
            row_id=row_dict.get('id', row_dict.get('rowid', 0))
        )
        
        # Extract names
        if self.config.identifier_extraction.extract_from_names:
            for col in columns.name_columns:
                value = row_dict.get(col)
                if value and isinstance(value, str) and value.strip():
                    extracted.names.append(value.strip())
        
        # Extract paths
        if self.config.identifier_extraction.extract_from_paths:
            for col in columns.path_columns:
                value = row_dict.get(col)
                if value and isinstance(value, str) and value.strip():
                    extracted.paths.append(value.strip())
        
        # Extract timestamps
        for col in columns.timestamp_columns:
            value = row_dict.get(col)
            if value is not None:
                parsed_ts = self.timestamp_parser.parse_timestamp(value)
                if parsed_ts and self.timestamp_parser.validate_timestamp(parsed_ts):
                    extracted.timestamps.append(parsed_ts)
                elif parsed_ts:
                    logger.warning(f"Timestamp out of valid range: {parsed_ts}")
                else:
                    logger.warning(f"Failed to parse timestamp: {value}")
        
        return extracted
    
    def get_table_info(self, table_path: str) -> Dict[str, Any]:
        """
        Get information about a Feather table without loading all data.
        
        Args:
            table_path: Path to Feather database
            
        Returns:
            Dictionary with table information
        """
        if not Path(table_path).exists():
            raise FileNotFoundError(f"Feather table not found: {table_path}")
        
        try:
            conn = sqlite3.connect(f"file:{table_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            # Get column names
            cursor.execute("PRAGMA table_info(feather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Get row count
            cursor.execute("SELECT COUNT(*) FROM feather_data")
            row_count = cursor.fetchone()[0]
            
            # Get metadata if available
            metadata = {}
            try:
                cursor.execute("SELECT * FROM feather_metadata LIMIT 1")
                row = cursor.fetchone()
                if row:
                    cursor.execute("PRAGMA table_info(feather_metadata)")
                    meta_columns = [r[1] for r in cursor.fetchall()]
                    metadata = dict(zip(meta_columns, row))
            except sqlite3.Error:
                pass
            
            conn.close()
            
            return {
                'path': table_path,
                'columns': columns,
                'row_count': row_count,
                'metadata': metadata
            }
            
        except sqlite3.Error as e:
            logger.error(f"Error getting table info for {table_path}: {e}")
            raise
    
    @staticmethod
    def validate_feather_table(table_path: str) -> tuple[bool, List[str]]:
        """
        Validate a Feather table structure.
        
        Args:
            table_path: Path to Feather database
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        if not Path(table_path).exists():
            return False, [f"Table file not found: {table_path}"]
        
        try:
            conn = sqlite3.connect(f"file:{table_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            # Check if feather_data table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='feather_data'"
            )
            if not cursor.fetchone():
                errors.append("'feather_data' table not found")
            
            conn.close()
            
        except sqlite3.Error as e:
            errors.append(f"Database error: {str(e)}")
        
        return len(errors) == 0, errors


# Convenience function

def load_feather_table(table_path: str, config: WingsConfig, 
                      artifact_name: Optional[str] = None) -> Iterator[ExtractedValues]:
    """
    Convenience function to load a Feather table.
    
    Args:
        table_path: Path to Feather database
        config: Wings configuration
        artifact_name: Optional artifact name
        
    Yields:
        ExtractedValues for each row
    """
    loader = EnhancedFeatherLoader(config)
    yield from loader.load_table(table_path, artifact_name)
