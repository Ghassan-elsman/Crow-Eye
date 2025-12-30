"""
Feather Auto-Registration Service

Automatically registers newly created feather databases using artifact type detection.
Integrates with the existing ArtifactDetector in the Feather Creation GUI.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

from ..config.feather_config import FeatherConfig


class FeatherAutoRegistrationService:
    """
    Service for automatically registering newly created feather databases.
    Uses artifact type detection results from the Feather Creation GUI.
    """
    
    def __init__(self, case_directory: Path):
        """
        Initialize auto-registration service.
        
        Args:
            case_directory: Path to the case's correlation directory
        """
        self.case_directory = Path(case_directory)
        self.feathers_dir = self.case_directory / "feathers"
        self.databases_dir = self.case_directory / "databases"
        self._notification_callback: Optional[Callable] = None
    
    def register_new_feather(self, database_path: str, artifact_type: str,
                            detection_method: str = "auto", 
                            confidence: str = "high") -> FeatherConfig:
        """
        Register a newly created feather database with already-detected type.
        
        Args:
            database_path: Path to the feather database
            artifact_type: Detected artifact type (from ArtifactDetector)
            detection_method: Method used for detection ("metadata", "table_name", "filename")
            confidence: Detection confidence ("high", "medium", "low")
        
        Returns:
            Generated FeatherConfig
        
        Raises:
            FileNotFoundError: If database doesn't exist
            ValueError: If database is invalid
        """
        db_path = Path(database_path)
        
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {database_path}")
        
        # Generate feather configuration
        feather_config = self.generate_feather_config(
            database_path=database_path,
            artifact_type=artifact_type,
            detection_method=detection_method,
            confidence=confidence
        )
        
        # Save configuration
        config_path = self.save_feather_config(feather_config)
        
        # Notify if callback is set
        if self._notification_callback:
            self._notification_callback(feather_config, config_path)
        
        return feather_config
    
    def generate_feather_config(self, database_path: str, artifact_type: str,
                               detection_method: str, confidence: str) -> FeatherConfig:
        """
        Generate feather configuration from detection results.
        
        Args:
            database_path: Path to the feather database
            artifact_type: Detected artifact type
            detection_method: Detection method used
            confidence: Detection confidence
        
        Returns:
            Generated FeatherConfig
        """
        db_path = Path(database_path)
        
        # Generate config name from database filename and timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        config_name = f"{db_path.stem}_{timestamp}"
        
        # Get feather name (clean version of filename)
        feather_name = db_path.stem.replace("_", " ").title()
        
        # Get record count and metadata from database
        total_records = 0
        date_range_start = None
        date_range_end = None
        
        try:
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Get record count
            cursor.execute("SELECT COUNT(*) FROM feather_data")
            total_records = cursor.fetchone()[0]
            
            # Try to get date range
            try:
                cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM feather_data")
                date_range = cursor.fetchone()
                if date_range[0] and date_range[1]:
                    date_range_start = date_range[0]
                    date_range_end = date_range[1]
            except:
                pass  # Date range is optional
            
            conn.close()
        except Exception as e:
            print(f"Warning: Could not read database metadata: {e}")
        
        # Create feather configuration
        feather_config = FeatherConfig(
            config_name=config_name,
            feather_name=feather_name,
            artifact_type=artifact_type,
            source_database=str(db_path),  # Original source
            source_table="feather_data",
            selected_columns=["timestamp", "application", "file_path", "event_data"],
            column_mapping={
                "timestamp": "timestamp",
                "application": "application",
                "file_path": "file_path",
                "event_data": "event_data"
            },
            timestamp_column="timestamp",
            timestamp_format="%Y-%m-%d %H:%M:%S",
            output_database=str(db_path),
            total_records=total_records,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            description=f"Auto-registered {artifact_type} feather (detection: {detection_method}, confidence: {confidence})",
            notes=f"Automatically registered on {datetime.now().isoformat()}"
        )
        
        return feather_config
    
    def save_feather_config(self, config: FeatherConfig) -> str:
        """
        Save feather configuration to case directory.
        
        Args:
            config: FeatherConfig to save
        
        Returns:
            Path to saved configuration file
        """
        # Ensure feathers directory exists
        self.feathers_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate config filename
        config_filename = f"{config.config_name}.json"
        config_path = self.feathers_dir / config_filename
        
        # Save configuration
        config.save_to_file(str(config_path))
        
        return str(config_path)
    
    def set_notification_callback(self, callback: Callable):
        """
        Set callback for registration notifications.
        
        Args:
            callback: Function to call when feather is registered
                     Signature: callback(feather_config: FeatherConfig, config_path: str)
        """
        self._notification_callback = callback
    
    def get_feather_configs(self) -> list[FeatherConfig]:
        """
        Get all registered feather configurations.
        
        Returns:
            List of FeatherConfig objects
        """
        configs = []
        
        if not self.feathers_dir.exists():
            return configs
        
        for config_file in self.feathers_dir.glob("*.json"):
            try:
                config = FeatherConfig.load_from_file(str(config_file))
                configs.append(config)
            except Exception as e:
                print(f"Warning: Could not load config {config_file}: {e}")
        
        return configs
    
    def validate_database(self, database_path: str) -> tuple[bool, Optional[str]]:
        """
        Validate that a database is a valid feather database.
        
        Args:
            database_path: Path to database to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            db_path = Path(database_path)
            
            if not db_path.exists():
                return False, "Database file not found"
            
            # Try to connect and check for feather_data table
            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feather_data'")
            if not cursor.fetchone():
                conn.close()
                return False, "Database does not contain 'feather_data' table"
            
            # Check for required columns
            cursor.execute("PRAGMA table_info(feather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            required_columns = ["timestamp"]
            missing_columns = [col for col in required_columns if col not in columns]
            
            conn.close()
            
            if missing_columns:
                return False, f"Missing required columns: {', '.join(missing_columns)}"
            
            return True, None
            
        except Exception as e:
            return False, str(e)
