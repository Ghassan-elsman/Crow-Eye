"""
Auto Feather Generator

Automatically generates Feathers from Crow-Eye parser output databases.
Converts parsed forensic artifacts into standardized Feather format for correlation analysis.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

# Import from Crow-Eye root config directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.configuration_manager import ConfigurationManager
from correlation_engine.config.feather_config import FeatherConfig

from .feather_mappings import get_feather_mappings

logger = logging.getLogger(__name__)


class AutoFeatherGenerator:
    """
    Generates Feathers automatically from Crow-Eye parser output.
    
    This class handles the automatic conversion of Crow-Eye parsed databases
    into standardized Feather format, including:
    - Reading source database schemas
    - Excluding parsing timestamp columns
    - Creating Feather databases with metadata
    - Registering Feathers with Configuration Manager
    """
    
    def __init__(self, case_directory: str):
        """
        Initialize AutoFeatherGenerator.
        
        Args:
            case_directory: Path to the case directory
        """
        self.case_directory = Path(case_directory)
        self.target_artifacts_dir = self.case_directory / "Target_Artifacts"
        self.feather_output_dir = self.case_directory / "Correlation" / "feathers"
        self.config_manager = ConfigurationManager.get_instance()
        
        # Ensure output directory exists
        self.feather_output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_all_feathers(self, progress_callback=None) -> Dict[str, Any]:
        """
        Generate all Feathers from parser output with progress tracking and error handling.
        
        Args:
            progress_callback: Optional callback function(current, total, feather_name, status)
                             to report progress
        
        Returns:
            Dictionary with generation results:
            {
                'successful': [list of generated feather paths],
                'failed': [list of (feather_name, error_message) tuples],
                'total': total number of mappings,
                'success_count': number of successful generations,
                'failure_count': number of failed generations
            }
        """
        generated_feathers = []
        failed_feathers = []
        
        # Get feather generation mappings
        mappings = self._get_feather_mappings()
        total_mappings = len(mappings)
        
        logger.info(f"Starting Feather generation for {total_mappings} mappings")
        
        for idx, mapping in enumerate(mappings, 1):
            feather_name = mapping['name']
            
            # Report progress
            if progress_callback:
                progress_callback(idx, total_mappings, feather_name, 'processing')
            
            try:
                # Generate feather
                feather_path = self._generate_feather(mapping)
                generated_feathers.append(feather_path)
                
                logger.info(f"✓ [{idx}/{total_mappings}] Generated: {feather_name}")
                
                # Report success
                if progress_callback:
                    progress_callback(idx, total_mappings, feather_name, 'success')
                    
            except FileNotFoundError as e:
                error_msg = f"Source database not found: {e}"
                failed_feathers.append((feather_name, error_msg))
                logger.warning(f"✗ [{idx}/{total_mappings}] Skipped {feather_name}: {error_msg}")
                
                # Report failure
                if progress_callback:
                    progress_callback(idx, total_mappings, feather_name, 'skipped')
                    
            except Exception as e:
                error_msg = str(e)
                failed_feathers.append((feather_name, error_msg))
                logger.error(f"✗ [{idx}/{total_mappings}] Failed to generate {feather_name}: {error_msg}")
                
                # Report failure
                if progress_callback:
                    progress_callback(idx, total_mappings, feather_name, 'failed')
        
        # Generate summary
        success_count = len(generated_feathers)
        failure_count = len(failed_feathers)
        
        logger.info(f"Feather generation complete: {success_count}/{total_mappings} successful, "
                   f"{failure_count} failed/skipped")
        
        # Log detailed failure information
        if failed_feathers:
            logger.info("Failed/Skipped Feathers:")
            for name, error in failed_feathers:
                logger.info(f"  - {name}: {error}")
        
        return {
            'successful': generated_feathers,
            'failed': failed_feathers,
            'total': total_mappings,
            'success_count': success_count,
            'failure_count': failure_count
        }
    
    def _get_feather_mappings(self) -> List[Dict]:
        """
        Get all feather generation mappings.
        
        Returns:
            List of mapping dictionaries
        """
        return get_feather_mappings()
    
    def _generate_feather(self, mapping: Dict) -> str:
        """
        Generate a single Feather from mapping configuration.
        
        Args:
            mapping: Feather generation mapping
            
        Returns:
            Path to generated Feather
            
        Raises:
            FileNotFoundError: If source database not found
            Exception: If Feather generation fails
        """
        source_db_path = self.target_artifacts_dir / mapping['source_db']
        
        # Check if source database exists
        if not source_db_path.exists():
            raise FileNotFoundError(f"Source database not found: {source_db_path}")
        
        logger.debug(f"Generating {mapping['name']} from {source_db_path}")
        
        # Connect to source database
        source_conn = sqlite3.connect(str(source_db_path))
        source_cursor = source_conn.cursor()
        
        try:
            # Get table schema
            source_cursor.execute(f"PRAGMA table_info({mapping['source_table']})")
            columns = source_cursor.fetchall()
            
            if not columns:
                raise Exception(f"Table {mapping['source_table']} not found or empty")
            
            # Exclude last column if specified
            if mapping.get('exclude_last_column', False):
                columns = columns[:-1]
                logger.debug(f"Excluded last column from {mapping['source_table']}")
            
            column_names = [col[1] for col in columns]
            
            # Build SELECT query
            select_cols = ', '.join([f'"{col}"' for col in column_names])
            query = f"SELECT {select_cols} FROM {mapping['source_table']}"
            
            # Add filter if specified
            if 'filter' in mapping:
                query += f" WHERE {mapping['filter']}"
                logger.debug(f"Applied filter: {mapping['filter']}")
            
            # Execute query to get data
            source_cursor.execute(query)
            rows = source_cursor.fetchall()
            
            logger.debug(f"Retrieved {len(rows)} rows from {mapping['source_table']}")
            
            # Create output Feather database
            feather_path = self.feather_output_dir / f"{mapping['name']}.db"
            
            # Remove existing feather if it exists
            if feather_path.exists():
                feather_path.unlink()
                logger.debug(f"Removed existing feather: {feather_path}")
            
            feather_conn = sqlite3.connect(str(feather_path))
            feather_cursor = feather_conn.cursor()
            
            try:
                # Create feather_metadata table with key-value structure (matching FeatherBuilder schema)
                feather_cursor.execute('''
                    CREATE TABLE IF NOT EXISTS feather_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                
                # Insert metadata as key-value pairs
                feather_id = mapping['name'].replace('_CrowEyeFeather', '').lower()
                timestamp = datetime.now().isoformat()
                
                metadata_entries = [
                    ('feather_id', feather_id),
                    ('feather_name', mapping['name']),
                    ('artifact_type', mapping['artifact_type']),
                    ('created_date', timestamp),
                    ('last_modified', timestamp),
                    ('version', '1.0'),
                    ('source_database', str(source_db_path)),
                    ('source_table', mapping['source_table']),
                    ('auto_generated', 'true'),
                    ('filter', mapping.get('filter', '')),
                    ('row_count', str(len(rows))),
                    ('exclude_last_column', str(mapping.get('exclude_last_column', False)))
                ]
                
                for key, value in metadata_entries:
                    feather_cursor.execute('''
                        INSERT OR REPLACE INTO feather_metadata (key, value)
                        VALUES (?, ?)
                    ''', (key, value))
                
                # Create data table with same structure as source
                col_defs = ', '.join([f'"{col[1]}" {col[2]}' for col in columns])
                feather_cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {mapping['source_table']} (
                        {col_defs}
                    )
                ''')
                
                # Insert data
                if rows:
                    placeholders = ', '.join(['?' for _ in column_names])
                    feather_cursor.executemany(
                        f'INSERT INTO {mapping["source_table"]} VALUES ({placeholders})',
                        rows
                    )
                
                # Create indexes for common columns
                self._create_indexes(feather_cursor, mapping['source_table'], column_names)
                
                # Commit and close feather database
                feather_conn.commit()
                
                logger.debug(f"Created feather database: {feather_path}")
                
            finally:
                feather_conn.close()
            
            # Create FeatherConfig and save as JSON
            feather_config = self._create_feather_config(
                mapping=mapping,
                feather_path=feather_path,
                column_names=column_names,
                row_count=len(rows),
                source_db_path=source_db_path
            )
            
            # Save FeatherConfig as JSON file
            config_json_path = self.feather_output_dir / f"{mapping['name']}.json"
            feather_config.save_to_file(str(config_json_path))
            logger.debug(f"Saved FeatherConfig JSON: {config_json_path}")
            
            # Create metadata dict for Configuration Manager
            config_metadata = {
                'source_database': str(source_db_path),
                'source_table': mapping['source_table'],
                'auto_generated': True,
                'filter': mapping.get('filter', None),
                'row_count': len(rows)
            }
            
            # Register with Configuration Manager
            self.config_manager.add_feather(
                feather_id=feather_id,
                db_path=str(feather_path),
                artifact_type=mapping['artifact_type'],
                metadata=config_metadata
            )
            
            logger.debug(f"Registered feather with Configuration Manager: {feather_id}")
            
            return str(feather_path)
            
        finally:
            source_conn.close()
    
    def _create_feather_config(self, mapping: Dict, feather_path: Path,
                              column_names: List[str], row_count: int,
                              source_db_path: Path) -> FeatherConfig:
        """
        Create a FeatherConfig object with all required fields.
        
        Args:
            mapping: Feather generation mapping
            feather_path: Path to generated feather database
            column_names: List of column names in the feather
            row_count: Number of rows in the feather
            source_db_path: Path to source database
            
        Returns:
            FeatherConfig object
        """
        feather_id = mapping['name'].replace('_CrowEyeFeather', '').lower()
        
        # Detect timestamp column (first column with time/date in name)
        timestamp_col = next(
            (col for col in column_names 
             if any(keyword in col.lower() for keyword in ['time', 'date', 'timestamp'])),
            column_names[0] if column_names else 'timestamp'
        )
        
        # Detect application/program column
        app_col = next(
            (col for col in column_names 
             if any(keyword in col.lower() for keyword in ['app', 'program', 'executable', 'name'])),
            None
        )
        
        # Detect path column
        path_col = next(
            (col for col in column_names 
             if any(keyword in col.lower() for keyword in ['path', 'file', 'location'])),
            None
        )
        
        # Create column mapping (identity mapping since we're not renaming columns)
        column_mapping = {col: col for col in column_names}
        
        return FeatherConfig(
            config_name=feather_id,
            feather_name=mapping['name'],
            artifact_type=mapping['artifact_type'],
            source_database=str(source_db_path),
            source_table=mapping['source_table'],
            selected_columns=column_names,
            column_mapping=column_mapping,
            timestamp_column=timestamp_col,
            timestamp_format='ISO8601',  # Crow-Eye uses ISO format
            output_database=str(feather_path),
            application_column=app_col,
            path_column=path_col,
            created_date=datetime.now().isoformat(),
            created_by='Auto-Generated',
            description=f'Auto-generated feather from {mapping["source_db"]} - {mapping["source_table"]}',
            notes=f'Filter: {mapping.get("filter", "None")}',
            total_records=row_count
        )
    
    def _create_indexes(self, cursor: sqlite3.Cursor, table_name: str, 
                       column_names: List[str]) -> None:
        """
        Create indexes on common columns for performance.
        
        Args:
            cursor: Database cursor
            table_name: Name of the table
            column_names: List of column names
        """
        try:
            # Index on timestamp columns
            timestamp_cols = [col for col in column_names 
                            if 'timestamp' in col.lower() or 'time' in col.lower() 
                            or 'date' in col.lower()]
            
            for col in timestamp_cols:
                try:
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{col.replace(" ", "_")} 
                        ON {table_name}("{col}")
                    ''')
                except Exception as e:
                    logger.debug(f"Could not create index on {col}: {e}")
            
            # Index on application/program columns
            app_cols = [col for col in column_names 
                       if 'application' in col.lower() or 'app' in col.lower() 
                       or 'program' in col.lower() or 'executable' in col.lower()]
            
            for col in app_cols:
                try:
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{col.replace(" ", "_")} 
                        ON {table_name}("{col}")
                    ''')
                except Exception as e:
                    logger.debug(f"Could not create index on {col}: {e}")
            
            # Index on path columns
            path_cols = [col for col in column_names 
                        if 'path' in col.lower() or 'file' in col.lower()]
            
            for col in path_cols:
                try:
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{col.replace(" ", "_")} 
                        ON {table_name}("{col}")
                    ''')
                except Exception as e:
                    logger.debug(f"Could not create index on {col}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
