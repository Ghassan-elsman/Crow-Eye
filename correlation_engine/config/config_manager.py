"""
Configuration Manager
Manages loading, saving, and organizing configurations.
"""

import os
import json
from typing import List, Optional, Dict
from pathlib import Path
from .feather_config import FeatherConfig
from .wing_config import WingConfig
from .pipeline_config import PipelineConfig


class ConfigManager:
    """Manages configuration files for feathers, wings, and pipelines"""
    
    def __init__(self, config_directory: str = "configs"):
        """
        Initialize configuration manager.
        
        Args:
            config_directory: Root directory for storing configurations
        """
        self.config_dir = Path(config_directory)
        self.feather_dir = self.config_dir / "feathers"
        self.wing_dir = self.config_dir / "wings"
        self.pipeline_dir = self.config_dir / "pipelines"
        
        # Create directories if they don't exist
        self.feather_dir.mkdir(parents=True, exist_ok=True)
        self.wing_dir.mkdir(parents=True, exist_ok=True)
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
    
    # Feather Configuration Methods
    
    def save_feather_config(self, config: FeatherConfig, custom_name: Optional[str] = None) -> str:
        """
        Save a feather configuration.
        
        Args:
            config: FeatherConfig to save
            custom_name: Optional custom filename (without extension)
            
        Returns:
            Path to saved file
        """
        filename = custom_name or config.config_name
        filename = self._sanitize_filename(filename) + ".json"
        file_path = self.feather_dir / filename
        
        config.save_to_file(str(file_path))
        return str(file_path)
    
    def load_feather_config(self, config_name: str) -> FeatherConfig:
        """Load a feather configuration by name"""
        filename = self._sanitize_filename(config_name) + ".json"
        file_path = self.feather_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Feather config not found: {config_name}")
        
        return FeatherConfig.load_from_file(str(file_path))
    
    def list_feather_configs(self) -> List[str]:
        """List all available feather configurations"""
        configs = []
        for file_path in self.feather_dir.glob("*.json"):
            configs.append(file_path.stem)
        return sorted(configs)
    
    def delete_feather_config(self, config_name: str):
        """Delete a feather configuration"""
        filename = self._sanitize_filename(config_name) + ".json"
        file_path = self.feather_dir / filename
        
        if file_path.exists():
            file_path.unlink()
    
    # Wing Configuration Methods
    
    def save_wing_config(self, config: WingConfig, custom_name: Optional[str] = None) -> str:
        """
        Save a wing configuration.
        
        Args:
            config: WingConfig to save
            custom_name: Optional custom filename (without extension)
            
        Returns:
            Path to saved file
        """
        filename = custom_name or config.config_name
        filename = self._sanitize_filename(filename) + ".json"
        file_path = self.wing_dir / filename
        
        config.save_to_file(str(file_path))
        return str(file_path)
    
    def load_wing_config(self, config_name: str) -> WingConfig:
        """Load a wing configuration by name"""
        filename = self._sanitize_filename(config_name) + ".json"
        file_path = self.wing_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Wing config not found: {config_name}")
        
        return WingConfig.load_from_file(str(file_path))
    
    def list_wing_configs(self) -> List[str]:
        """List all available wing configurations"""
        configs = []
        for file_path in self.wing_dir.glob("*.json"):
            configs.append(file_path.stem)
        return sorted(configs)
    
    def delete_wing_config(self, config_name: str):
        """Delete a wing configuration"""
        filename = self._sanitize_filename(config_name) + ".json"
        file_path = self.wing_dir / filename
        
        if file_path.exists():
            file_path.unlink()
    
    # Pipeline Configuration Methods
    
    def save_pipeline_config(self, config: PipelineConfig, custom_name: Optional[str] = None) -> str:
        """
        Save a pipeline configuration.
        
        Args:
            config: PipelineConfig to save
            custom_name: Optional custom filename (without extension)
            
        Returns:
            Path to saved file
        """
        filename = custom_name or config.config_name
        filename = self._sanitize_filename(filename) + ".json"
        file_path = self.pipeline_dir / filename
        
        config.save_to_file(str(file_path))
        return str(file_path)
    
    def load_pipeline_config(self, config_name: str) -> PipelineConfig:
        """Load a pipeline configuration by name"""
        filename = self._sanitize_filename(config_name) + ".json"
        file_path = self.pipeline_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Pipeline config not found: {config_name}")
        
        return PipelineConfig.load_from_file(str(file_path))
    
    def list_pipeline_configs(self) -> List[str]:
        """List all available pipeline configurations"""
        configs = []
        for file_path in self.pipeline_dir.glob("*.json"):
            configs.append(file_path.stem)
        return sorted(configs)
    
    def delete_pipeline_config(self, config_name: str):
        """Delete a pipeline configuration"""
        filename = self._sanitize_filename(config_name) + ".json"
        file_path = self.pipeline_dir / filename
        
        if file_path.exists():
            file_path.unlink()
    
    # Utility Methods
    
    def get_config_info(self, config_type: str, config_name: str) -> Dict:
        """
        Get summary information about a configuration.
        
        Args:
            config_type: "feather", "wing", or "pipeline"
            config_name: Name of the configuration
            
        Returns:
            Dictionary with config information
        """
        if config_type == "feather":
            config = self.load_feather_config(config_name)
            return {
                'name': config.config_name,
                'type': 'feather',
                'artifact_type': config.artifact_type,
                'source': config.source_database,
                'output': config.output_database,
                'created': config.created_date,
                'records': config.total_records
            }
        elif config_type == "wing":
            config = self.load_wing_config(config_name)
            return {
                'name': config.config_name,
                'type': 'wing',
                'wing_name': config.wing_name,
                'feathers': len(config.feathers),
                'created': config.created_date,
                'proves': config.proves
            }
        elif config_type == "pipeline":
            config = self.load_pipeline_config(config_name)
            return {
                'name': config.config_name,
                'type': 'pipeline',
                'pipeline_name': config.pipeline_name,
                'feathers': len(config.feather_configs),
                'wings': len(config.wing_configs),
                'created': config.created_date,
                'last_executed': config.last_executed
            }
        else:
            raise ValueError(f"Unknown config type: {config_type}")
    
    def export_config(self, config_type: str, config_name: str, export_path: str):
        """Export a configuration to a specific path"""
        if config_type == "feather":
            config = self.load_feather_config(config_name)
        elif config_type == "wing":
            config = self.load_wing_config(config_name)
        elif config_type == "pipeline":
            config = self.load_pipeline_config(config_name)
        else:
            raise ValueError(f"Unknown config type: {config_type}")
        
        config.save_to_file(export_path)
    
    def import_config(self, config_type: str, import_path: str, new_name: Optional[str] = None):
        """Import a configuration from a file"""
        if config_type == "feather":
            config = FeatherConfig.load_from_file(import_path)
            if new_name:
                config.config_name = new_name
            self.save_feather_config(config)
        elif config_type == "wing":
            config = WingConfig.load_from_file(import_path)
            if new_name:
                config.config_name = new_name
            self.save_wing_config(config)
        elif config_type == "pipeline":
            config = PipelineConfig.load_from_file(import_path)
            if new_name:
                config.config_name = new_name
            self.save_pipeline_config(config)
        else:
            raise ValueError(f"Unknown config type: {config_type}")
    
    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize filename to remove invalid characters"""
        # Remove or replace invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename.strip()
