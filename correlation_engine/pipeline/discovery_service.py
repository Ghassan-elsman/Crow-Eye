"""
Configuration Discovery Service

Automatically discovers and validates all available pipeline, feather, and wing configurations
in the case directory structure.
"""

import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from ..config.session_state import (
    PipelineMetadata,
    FeatherMetadata,
    WingsMetadata,
    DiscoveryResult,
    ValidationResult
)
from ..config.pipeline_config import PipelineConfig
from ..config.feather_config import FeatherConfig
from ..config.wing_config import WingConfig


class ConfigurationDiscoveryService:
    """
    Service for discovering and validating configuration files.
    Scans the case directory structure for available configurations.
    """
    
    def __init__(self, case_directory: Path):
        """
        Initialize discovery service with case directory.
        
        Args:
            case_directory: Path to the case's correlation directory
        """
        self.case_directory = Path(case_directory)
        self.pipelines_dir = self.case_directory / "pipelines"
        self.feathers_dir = self.case_directory / "feathers"
        self.wings_dir = self.case_directory / "wings"
        self._discovery_cache: Optional[DiscoveryResult] = None
    
    def discover_all(self) -> DiscoveryResult:
        """
        Discover all configurations (pipelines, feathers, wings).
        
        Returns:
            DiscoveryResult containing all discovered configurations
        """
        pipelines = self.discover_pipelines()
        feathers = self.discover_feathers()
        wings = self.discover_wings()
        
        result = DiscoveryResult(
            pipelines=pipelines,
            feathers=feathers,
            wings=wings
        )
        
        self._discovery_cache = result
        return result
    
    def discover_pipelines(self) -> List[PipelineMetadata]:
        """
        Discover available pipeline configurations.
        
        Returns:
            List of PipelineMetadata for all discovered pipelines
        """
        pipelines = []
        
        if not self.pipelines_dir.exists():
            return pipelines
        
        for config_file in self.pipelines_dir.glob("*.json"):
            try:
                metadata = self._extract_pipeline_metadata(config_file)
                pipelines.append(metadata)
            except Exception as e:
                # Create metadata for invalid pipeline
                pipelines.append(PipelineMetadata(
                    config_name=config_file.stem,
                    pipeline_name=config_file.stem,
                    file_path=config_file,
                    description="",
                    feather_count=0,
                    wing_count=0,
                    last_modified=datetime.fromtimestamp(config_file.stat().st_mtime).isoformat(),
                    is_valid=False,
                    validation_errors=[str(e)]
                ))
        
        return pipelines
    
    def discover_feathers(self) -> List[FeatherMetadata]:
        """
        Discover available feather configurations.
        
        Returns:
            List of FeatherMetadata for all discovered feathers
        """
        feathers = []
        
        if not self.feathers_dir.exists():
            return feathers
        
        for config_file in self.feathers_dir.glob("*.json"):
            try:
                metadata = self._extract_feather_metadata(config_file)
                feathers.append(metadata)
            except Exception as e:
                # Create metadata for invalid feather
                feathers.append(FeatherMetadata(
                    config_name=config_file.stem,
                    feather_name=config_file.stem,
                    file_path=config_file,
                    artifact_type="Unknown",
                    database_path="",
                    total_records=0,
                    created_date=datetime.fromtimestamp(config_file.stat().st_mtime).isoformat(),
                    is_valid=False,
                    validation_errors=[str(e)]
                ))
        
        return feathers
    
    def discover_wings(self) -> List[WingsMetadata]:
        """
        Discover available wings configurations.
        
        Returns:
            List of WingsMetadata for all discovered wings
        """
        wings = []
        
        if not self.wings_dir.exists():
            return wings
        
        for config_file in self.wings_dir.glob("*.json"):
            try:
                metadata = self._extract_wings_metadata(config_file)
                wings.append(metadata)
            except Exception as e:
                # Create metadata for invalid wing
                wings.append(WingsMetadata(
                    config_name=config_file.stem,
                    wing_name=config_file.stem,
                    file_path=config_file,
                    wing_id="",
                    description="",
                    feather_count=0,
                    time_window_minutes=0,
                    created_date=datetime.fromtimestamp(config_file.stat().st_mtime).isoformat(),
                    is_valid=False,
                    validation_errors=[str(e)]
                ))
        
        return wings
    
    def validate_configuration(self, config_path: Path, config_type: str) -> ValidationResult:
        """
        Validate a configuration file.
        
        Args:
            config_path: Path to configuration file
            config_type: Type of configuration ("pipeline", "feather", "wing")
        
        Returns:
            ValidationResult with validation status and errors
        """
        result = ValidationResult(
            is_valid=True,
            config_type=config_type,
            config_path=str(config_path)
        )
        
        # Check file exists
        if not config_path.exists():
            result.add_error(f"Configuration file not found: {config_path}")
            return result
        
        # Check JSON syntax
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            result.add_error(f"Invalid JSON syntax: {e}")
            return result
        except Exception as e:
            result.add_error(f"Error reading file: {e}")
            return result
        
        # Validate based on type
        if config_type == "pipeline":
            self._validate_pipeline_config(data, result)
        elif config_type == "feather":
            self._validate_feather_config(data, result)
        elif config_type == "wing":
            self._validate_wing_config(data, result)
        else:
            result.add_error(f"Unknown configuration type: {config_type}")
        
        return result
    
    def refresh(self):
        """
        Refresh discovery cache by re-scanning all configurations.
        """
        self._discovery_cache = self.discover_all()
    
    def get_cached_discovery(self) -> Optional[DiscoveryResult]:
        """
        Get cached discovery result without re-scanning.
        
        Returns:
            Cached DiscoveryResult or None if not cached
        """
        return self._discovery_cache
    
    def _extract_pipeline_metadata(self, config_file: Path) -> PipelineMetadata:
        """Extract metadata from pipeline configuration file."""
        config = PipelineConfig.load_from_file(str(config_file))
        
        # Validate configuration
        validation = self.validate_configuration(config_file, "pipeline")
        
        return PipelineMetadata(
            config_name=config.config_name,
            pipeline_name=config.pipeline_name,
            file_path=config_file,
            description=config.description,
            feather_count=len(config.feather_configs),
            wing_count=len(config.wing_configs),
            last_modified=config.last_modified,
            is_valid=validation.is_valid,
            validation_errors=validation.errors,
            case_name=config.case_name,
            case_id=config.case_id,
            investigator=config.investigator,
            last_executed=config.last_executed,
            tags=config.tags
        )
    
    def _extract_feather_metadata(self, config_file: Path) -> FeatherMetadata:
        """Extract metadata from feather configuration file."""
        config = FeatherConfig.load_from_file(str(config_file))
        
        # Validate configuration
        validation = self.validate_configuration(config_file, "feather")
        
        return FeatherMetadata(
            config_name=config.config_name,
            feather_name=config.feather_name,
            file_path=config_file,
            artifact_type=config.artifact_type,
            database_path=config.output_database,
            total_records=config.total_records,
            created_date=config.created_date,
            is_valid=validation.is_valid,
            validation_errors=validation.errors
        )
    
    def _extract_wings_metadata(self, config_file: Path) -> WingsMetadata:
        """Extract metadata from wings configuration file."""
        config = WingConfig.load_from_file(str(config_file))
        
        # Validate configuration
        validation = self.validate_configuration(config_file, "wing")
        
        return WingsMetadata(
            config_name=config.config_name,
            wing_name=config.wing_name,
            file_path=config_file,
            wing_id=config.wing_id,
            description=config.description,
            feather_count=len(config.feathers),
            time_window_minutes=config.time_window_minutes,
            created_date=config.created_date,
            is_valid=validation.is_valid,
            validation_errors=validation.errors
        )
    
    def _validate_pipeline_config(self, data: dict, result: ValidationResult):
        """Validate pipeline configuration data."""
        required_fields = ["config_name", "pipeline_name", "description"]
        
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}")
        
        # Check feather_configs is a list
        if "feather_configs" in data:
            if not isinstance(data["feather_configs"], list):
                result.add_error("feather_configs must be a list")
        
        # Check wing_configs is a list
        if "wing_configs" in data:
            if not isinstance(data["wing_configs"], list):
                result.add_error("wing_configs must be a list")
    
    def _validate_feather_config(self, data: dict, result: ValidationResult):
        """Validate feather configuration data."""
        required_fields = [
            "config_name", "feather_name", "artifact_type",
            "source_database", "source_table", "selected_columns",
            "column_mapping", "timestamp_column", "timestamp_format",
            "output_database"
        ]
        
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}")
        
        # Check selected_columns is a list
        if "selected_columns" in data:
            if not isinstance(data["selected_columns"], list):
                result.add_error("selected_columns must be a list")
        
        # Check column_mapping is a dict
        if "column_mapping" in data:
            if not isinstance(data["column_mapping"], dict):
                result.add_error("column_mapping must be a dictionary")
    
    def _validate_wing_config(self, data: dict, result: ValidationResult):
        """Validate wing configuration data."""
        required_fields = [
            "config_name", "wing_name", "wing_id",
            "description", "proves", "author"
        ]
        
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}")
        
        # Check feathers is a list
        if "feathers" in data:
            if not isinstance(data["feathers"], list):
                result.add_error("feathers must be a list")
        
        # Check time_window_minutes is a number
        if "time_window_minutes" in data:
            if not isinstance(data["time_window_minutes"], (int, float)):
                result.add_error("time_window_minutes must be a number")
