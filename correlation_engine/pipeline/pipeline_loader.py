"""
Pipeline Loader

Loads complete pipeline bundles with all dependencies (feathers, wings, databases).
Handles validation, path resolution, and graceful error handling.
"""

from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from ..config.pipeline_config import PipelineConfig
from ..config.feather_config import FeatherConfig
from ..config.wing_config import WingConfig
from ..config.session_state import (
    PipelineBundle,
    LoadStatus,
    PartialLoadInfo,
    ValidationResult
)
from .database_connection_manager import DatabaseConnectionManager


class PipelineLoader:
    """
    Loads complete pipeline bundles with all dependencies.
    Handles validation, path resolution, and database connections.
    """
    
    def __init__(self, case_directory: Path):
        """
        Initialize pipeline loader.
        
        Args:
            case_directory: Path to the case's correlation directory
        """
        self.case_directory = Path(case_directory)
        self.db_manager = DatabaseConnectionManager()
    
    def load_pipeline(self, pipeline_path: str) -> PipelineBundle:
        """
        Load complete pipeline bundle.
        
        Args:
            pipeline_path: Path to pipeline configuration file
        
        Returns:
            PipelineBundle with all loaded components
        
        Raises:
            FileNotFoundError: If pipeline file doesn't exist
            ValueError: If pipeline validation fails
        """
        pipeline_path = Path(pipeline_path)
        
        # Load pipeline configuration
        if not pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline configuration not found: {pipeline_path}")
        
        pipeline_config = PipelineConfig.load_from_file(str(pipeline_path))
        
        # Validate dependencies
        validation = self.validate_pipeline_dependencies(pipeline_config)
        if not validation.is_valid:
            raise ValueError(f"Pipeline validation failed: {', '.join(validation.errors)}")
        
        # Resolve paths
        resolved_paths = self.resolve_config_paths(pipeline_config)
        
        # Load feather configurations
        feather_configs, feather_errors = self._load_feather_configs(pipeline_config, resolved_paths)
        
        # Load wing configurations
        wing_configs, wing_errors = self._load_wing_configs(pipeline_config, resolved_paths)
        
        # Connect to databases
        connections = self.db_manager.connect_all(feather_configs)
        connection_statuses = self.db_manager.get_connection_status()
        
        # Build load status
        load_status = LoadStatus(
            is_complete=len(feather_errors) == 0 and len(wing_errors) == 0,
            feathers_loaded=len(feather_configs),
            feathers_total=len(pipeline_config.feather_configs),
            wings_loaded=len(wing_configs),
            wings_total=len(pipeline_config.wing_configs),
            errors=feather_errors + wing_errors
        )
        
        # Add partial load info if needed
        if not load_status.is_complete:
            load_status.partial_load_info = PartialLoadInfo(
                feathers_loaded=[fc.config_name for fc in feather_configs],
                feathers_failed=[],  # Track failed ones
                wings_loaded=[wc.config_name for wc in wing_configs],
                wings_failed=[]
            )
        
        # Create bundle
        bundle = PipelineBundle(
            pipeline_config=pipeline_config,
            feather_configs=feather_configs,
            wing_configs=wing_configs,
            database_connections=connections,
            resolved_paths=resolved_paths,
            load_status=load_status,
            connection_statuses=connection_statuses
        )
        
        return bundle
    
    def validate_pipeline_dependencies(self, pipeline_config: PipelineConfig) -> ValidationResult:
        """
        Validate all pipeline dependencies exist.
        
        Args:
            pipeline_config: Pipeline configuration to validate
        
        Returns:
            ValidationResult with validation status
        """
        result = ValidationResult(
            is_valid=True,
            config_type="pipeline"
        )
        
        # Check feather configs exist
        for feather_ref in pipeline_config.feather_configs:
            if isinstance(feather_ref, str):
                # It's a path reference
                feather_path = self._resolve_path(feather_ref)
                if not feather_path.exists():
                    result.add_error(f"Feather configuration not found: {feather_ref}")
            elif isinstance(feather_ref, FeatherConfig):
                # It's already a config object - check database
                db_path = self._resolve_path(feather_ref.output_database)
                if not db_path.exists():
                    result.add_warning(f"Feather database not found: {feather_ref.output_database}")
        
        # Check wing configs exist
        for wing_ref in pipeline_config.wing_configs:
            if isinstance(wing_ref, str):
                # It's a path reference
                wing_path = self._resolve_path(wing_ref)
                if not wing_path.exists():
                    result.add_error(f"Wing configuration not found: {wing_ref}")
        
        return result
    
    def resolve_config_paths(self, pipeline_config: PipelineConfig) -> Dict[str, str]:
        """
        Resolve all relative paths to absolute paths.
        
        Args:
            pipeline_config: Pipeline configuration
        
        Returns:
            Dictionary of resolved paths
        """
        resolved = {}
        
        # Resolve feather config paths
        for i, feather_ref in enumerate(pipeline_config.feather_configs):
            if isinstance(feather_ref, str):
                resolved[f"feather_{i}"] = str(self._resolve_path(feather_ref))
        
        # Resolve wing config paths
        for i, wing_ref in enumerate(pipeline_config.wing_configs):
            if isinstance(wing_ref, str):
                resolved[f"wing_{i}"] = str(self._resolve_path(wing_ref))
        
        return resolved
    
    def unload_pipeline(self, bundle: PipelineBundle):
        """
        Unload pipeline and close connections.
        
        Args:
            bundle: PipelineBundle to unload
        """
        # Close all database connections
        self.db_manager.disconnect_all()
    
    def _load_feather_configs(self, pipeline_config: PipelineConfig, 
                             resolved_paths: Dict[str, str]) -> tuple[List[FeatherConfig], List[str]]:
        """Load all feather configurations."""
        configs = []
        errors = []
        
        for i, feather_ref in enumerate(pipeline_config.feather_configs):
            try:
                if isinstance(feather_ref, FeatherConfig):
                    # Already a config object
                    configs.append(feather_ref)
                elif isinstance(feather_ref, dict):
                    # Dictionary - convert to config
                    configs.append(FeatherConfig.from_dict(feather_ref))
                else:
                    # String path - load from file
                    feather_path = self._resolve_path(feather_ref)
                    config = FeatherConfig.load_from_file(str(feather_path))
                    configs.append(config)
            except Exception as e:
                errors.append(f"Failed to load feather config {feather_ref}: {e}")
        
        return configs, errors
    
    def _load_wing_configs(self, pipeline_config: PipelineConfig,
                          resolved_paths: Dict[str, str]) -> tuple[List[WingConfig], List[str]]:
        """Load all wing configurations."""
        configs = []
        errors = []
        
        for i, wing_ref in enumerate(pipeline_config.wing_configs):
            try:
                if isinstance(wing_ref, WingConfig):
                    # Already a config object
                    configs.append(wing_ref)
                elif isinstance(wing_ref, dict):
                    # Dictionary - convert to config
                    configs.append(WingConfig.from_dict(wing_ref))
                else:
                    # String path - load from file
                    wing_path = self._resolve_path(wing_ref)
                    config = WingConfig.load_from_file(str(wing_path))
                    configs.append(config)
            except Exception as e:
                errors.append(f"Failed to load wing config {wing_ref}: {e}")
        
        return configs, errors
    
    def _resolve_path(self, path: str) -> Path:
        """
        Resolve a path (relative or absolute).
        
        Args:
            path: Path string to resolve
        
        Returns:
            Resolved Path object
        """
        path_obj = Path(path)
        
        # If absolute, return as-is
        if path_obj.is_absolute():
            return path_obj
        
        # If relative, resolve from case directory
        return (self.case_directory / path_obj).resolve()
