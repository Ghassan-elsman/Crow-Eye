"""
Feather Config Generator

Automatically generates JSON configuration files for feather databases that don't have them.
This enables Wings to properly reference and load feathers without manual configuration.
"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from ..config import FeatherConfig
from .auto_feather_generator import AutoFeatherGenerator

logger = logging.getLogger(__name__)


class FeatherConfigGenerator:
    """
    Generates JSON configuration files for feather databases.
    
    Scans a directory for .db files without corresponding .json configs
    and automatically generates the missing configurations.
    """
    
    @staticmethod
    def generate_missing_configs(feathers_directory: Path) -> List[Path]:
        """
        Generate JSON configs for .db files without configs.
        
        Args:
            feathers_directory: Directory containing feather .db files
            
        Returns:
            List of paths to generated config files
        """
        if not feathers_directory.exists():
            logger.warning(f"Feathers directory does not exist: {feathers_directory}")
            return []
        
        logger.info(f"Scanning for missing feather configs in: {feathers_directory}")
        
        generated_configs = []
        db_files = list(feathers_directory.glob("*.db"))
        
        logger.info(f"Found {len(db_files)} .db files")
        
        for db_path in db_files:
            if FeatherConfigGenerator.needs_config_generation(db_path):
                try:
                    config_path = FeatherConfigGenerator.generate_config_for_db(db_path)
                    if config_path:
                        generated_configs.append(config_path)
                        logger.info(f"✓ Generated config: {config_path.name}")
                except Exception as e:
                    logger.error(f"Failed to generate config for {db_path.name}: {e}")
            else:
                logger.debug(f"Config already exists for: {db_path.name}")
        
        logger.info(f"Generated {len(generated_configs)} feather configs")
        return generated_configs
    
    @staticmethod
    def needs_config_generation(db_path: Path) -> bool:
        """
        Check if a .db file needs a JSON config.
        
        Args:
            db_path: Path to the .db file
            
        Returns:
            True if config needs to be generated, False otherwise
        """
        if not db_path.exists():
            return False
        
        # Check for corresponding .json file
        json_path = db_path.with_suffix('.json')
        
        # Config is needed if .json doesn't exist
        return not json_path.exists()
    
    @staticmethod
    def generate_config_for_db(db_path: Path) -> Optional[Path]:
        """
        Generate JSON config for a specific .db file.
        
        Args:
            db_path: Path to the .db file
            
        Returns:
            Path to generated config file, or None if generation failed
        """
        if not db_path.exists():
            logger.error(f"Database file does not exist: {db_path}")
            return None
        
        logger.info(f"Generating config for: {db_path.name}")
        
        try:
            # Extract feather name from filename
            feather_name = db_path.stem
            
            # Detect artifact type from database
            artifact_type = FeatherConfigGenerator._detect_artifact_type(db_path)
            
            if not artifact_type:
                logger.warning(f"Could not detect artifact type for {db_path.name}, using 'Unknown'")
                artifact_type = "Unknown"
            
            # Get table name from database
            table_name = FeatherConfigGenerator._get_table_name(db_path)
            
            if not table_name:
                logger.error(f"Could not determine table name for {db_path.name}")
                return None
            
            # Try to use AutoFeatherGenerator if available
            try:
                generator = AutoFeatherGenerator()
                
                # Generate feather config using the auto generator
                feather_config = generator.generate_feather_config(
                    database_path=str(db_path),
                    artifact_type=artifact_type,
                    feather_name=feather_name
                )
                
                if feather_config:
                    # Save to JSON file
                    json_path = db_path.with_suffix('.json')
                    feather_config.save_to_file(str(json_path))
                    logger.info(f"✓ Saved config to: {json_path.name}")
                    return json_path
                
            except Exception as e:
                logger.warning(f"AutoFeatherGenerator failed, using fallback: {e}")
            
            # Fallback: Create basic config manually
            feather_config = FeatherConfigGenerator._create_basic_config(
                db_path, feather_name, artifact_type, table_name
            )
            
            if feather_config:
                json_path = db_path.with_suffix('.json')
                feather_config.save_to_file(str(json_path))
                logger.info(f"✓ Saved basic config to: {json_path.name}")
                return json_path
            
        except Exception as e:
            logger.error(f"Failed to generate config for {db_path.name}: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    @staticmethod
    def _detect_artifact_type(db_path: Path) -> Optional[str]:
        """
        Detect artifact type from database name or schema.
        
        Args:
            db_path: Path to the database file
            
        Returns:
            Detected artifact type or None
        """
        # Try to detect from filename
        filename_lower = db_path.stem.lower()
        
        # Common artifact type patterns
        artifact_patterns = {
            'prefetch': 'Prefetch',
            'shimcache': 'ShimCache',
            'amcache': 'AmCache',
            'inventoryapplication': 'AmCache',
            'lnk': 'LNK',
            'jumplist': 'Jumplists',
            'automatic': 'Jumplists',
            'custom': 'Jumplists',
            'srum': 'SRUM',
            'userassist': 'Registry',
            'recentdocs': 'Registry',
            'opensavemru': 'Registry',
            'lastsavemru': 'Registry',
            'shellbags': 'Registry',
            'typedpaths': 'Registry',
            'mft': 'MFT',
            'usn': 'USN',
            'recyclebin': 'RecycleBin',
            'security': 'Logs',
            'system': 'Logs',
            'application': 'Logs',
        }
        
        for pattern, artifact_type in artifact_patterns.items():
            if pattern in filename_lower:
                return artifact_type
        
        # Try to detect from table name
        try:
            table_name = FeatherConfigGenerator._get_table_name(db_path)
            if table_name:
                table_lower = table_name.lower()
                for pattern, artifact_type in artifact_patterns.items():
                    if pattern in table_lower:
                        return artifact_type
        except:
            pass
        
        return None
    
    @staticmethod
    def _get_table_name(db_path: Path) -> Optional[str]:
        """
        Get the main table name from the database.
        
        Args:
            db_path: Path to the database file
            
        Returns:
            Table name or None
        """
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            conn.close()
            
            if tables:
                # Return first non-system table
                for table in tables:
                    table_name = table[0]
                    if not table_name.startswith('sqlite_'):
                        return table_name
            
        except Exception as e:
            logger.error(f"Failed to get table name from {db_path.name}: {e}")
        
        return None
    
    @staticmethod
    def _create_basic_config(
        db_path: Path,
        feather_name: str,
        artifact_type: str,
        table_name: str
    ) -> Optional[FeatherConfig]:
        """
        Create a basic feather config as fallback.
        
        Args:
            db_path: Path to the database file
            feather_name: Name of the feather
            artifact_type: Type of artifact
            table_name: Name of the main table
            
        Returns:
            FeatherConfig object or None
        """
        try:
            # Get column names from database
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()
            conn.close()
            
            columns = [col[1] for col in columns_info]
            
            # Try to identify key columns
            timestamp_column = None
            application_column = None
            path_column = None
            
            for col in columns:
                col_lower = col.lower()
                if 'time' in col_lower or 'date' in col_lower:
                    if not timestamp_column:
                        timestamp_column = col
                if 'app' in col_lower or 'program' in col_lower:
                    if not application_column:
                        application_column = col
                if 'path' in col_lower or 'file' in col_lower:
                    if not path_column:
                        path_column = col
            
            # Use first column as timestamp if none found
            if not timestamp_column and columns:
                timestamp_column = columns[0]
            
            # Create basic config
            config_name = feather_name.lower().replace(' ', '_')
            
            # Create column mapping (identity mapping)
            column_mapping = {col: col for col in columns}
            
            feather_config = FeatherConfig(
                config_name=config_name,
                feather_name=feather_name,
                artifact_type=artifact_type,
                source_database=str(db_path),
                source_table=table_name,
                selected_columns=columns,
                column_mapping=column_mapping,
                timestamp_column=timestamp_column or "timestamp",
                timestamp_format="%Y-%m-%d %H:%M:%S",
                output_database=str(db_path),
                application_column=application_column,
                path_column=path_column,
                description=f"Auto-generated config for {feather_name}"
            )
            
            return feather_config
            
        except Exception as e:
            logger.error(f"Failed to create basic config: {e}")
            return None
