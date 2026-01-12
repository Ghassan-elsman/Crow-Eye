"""
Configuration Manager
Manages loading, saving, and organizing configurations.
"""

import os
import json
import tempfile
import shutil
import logging
from typing import List, Optional, Dict, Tuple, Any
from pathlib import Path
from .feather_config import FeatherConfig
from .wing_config import WingConfig
from .pipeline_config import PipelineConfig

logger = logging.getLogger(__name__)


# Configuration schemas for validation
CONFIG_SCHEMAS = {
    "weighted_scoring": {
        "required_fields": ["enabled"],
        "optional_fields": ["score_interpretation", "default_weights", "tier_definitions", "validation_rules", "case_specific"],
        "field_types": {
            "enabled": bool,
            "score_interpretation": dict,
            "default_weights": dict,
            "tier_definitions": dict,
            "validation_rules": dict,
            "case_specific": dict
        },
        "nested_validation": {
            "score_interpretation": {
                "value_type": dict,
                "value_required_fields": ["min", "label"]
            },
            "default_weights": {
                "value_type": (int, float),
                "value_range": (0.0, 1.0)
            },
            "validation_rules": {
                "optional_fields": ["max_weight", "min_weight", "max_tier", "min_tier", "require_positive_weights", "allow_zero_weights"]
            }
        }
    },
    "semantic_mapping": {
        "required_fields": ["enabled"],
        "optional_fields": ["global_mappings_path", "case_specific"],
        "field_types": {
            "enabled": bool,
            "global_mappings_path": str,
            "case_specific": dict
        }
    },
    "feather": {
        "required_fields": ["config_name", "artifact_type"],
        "optional_fields": ["source_database", "output_database", "created_date", "total_records", "field_mappings"],
        "field_types": {
            "config_name": str,
            "artifact_type": str,
            "source_database": str,
            "output_database": str,
            "created_date": str,
            "total_records": int,
            "field_mappings": dict
        }
    },
    "wing": {
        "required_fields": ["config_name", "wing_name"],
        "optional_fields": ["feathers", "created_date", "proves", "description"],
        "field_types": {
            "config_name": str,
            "wing_name": str,
            "feathers": list,
            "created_date": str,
            "proves": str,
            "description": str
        }
    },
    "pipeline": {
        "required_fields": ["config_name", "pipeline_name"],
        "optional_fields": ["feather_configs", "wing_configs", "created_date", "last_executed", "description"],
        "field_types": {
            "config_name": str,
            "pipeline_name": str,
            "feather_configs": list,
            "wing_configs": list,
            "created_date": str,
            "last_executed": str,
            "description": str
        }
    }
}


# Default configurations
DEFAULT_CONFIGS = {
    "weighted_scoring": {
        "enabled": True,
        "score_interpretation": {
            "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
            "probable": {"min": 0.5, "label": "Probable Match"},
            "weak": {"min": 0.2, "label": "Weak Evidence"},
            "minimal": {"min": 0.0, "label": "Minimal Evidence"}
        },
        "default_weights": {
            "Logs": 0.4,
            "Prefetch": 0.3,
            "SRUM": 0.2,
            "AmCache": 0.15,
            "ShimCache": 0.15,
            "Jumplists": 0.1,
            "LNK": 0.1,
            "MFT": 0.05,
            "USN": 0.05
        },
        "tier_definitions": {
            "1": "Primary Evidence",
            "2": "Supporting Evidence", 
            "3": "Contextual Evidence",
            "4": "Background Evidence"
        },
        "validation_rules": {
            "max_weight": 1.0,
            "min_weight": 0.0,
            "max_tier": 4,
            "min_tier": 1,
            "require_positive_weights": True,
            "allow_zero_weights": True
        },
        "case_specific": {
            "enabled": True,
            "storage_path": "cases/{case_id}/scoring_weights.json"
        }
    },
    "semantic_mapping": {
        "enabled": True,
        "global_mappings_path": "config/semantic_mappings.json",
        "case_specific": {
            "enabled": True,
            "storage_path": "cases/{case_id}/semantic_mappings.json"
        }
    }
}


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
    
    # Weighted Scoring Configuration Methods
    
    def get_weighted_scoring_config(self) -> Optional[Dict]:
        """
        Get weighted scoring configuration.
        
        Returns:
            Dictionary with weighted scoring configuration or None if not found
        """
        config_path = self.config_dir / "weighted_scoring.json"
        config_data, errors = self.load_config_with_validation(config_path, "weighted_scoring")
        
        if errors:
            for error in errors:
                logger.warning(f"Weighted scoring config: {error}")
        
        return config_data if config_data else self.get_default_config("weighted_scoring")
    
    def save_weighted_scoring_config(self, config: Dict) -> bool:
        """
        Save weighted scoring configuration.
        
        Args:
            config: Configuration dictionary to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        # Validate before saving
        is_valid, errors = self.validate_config_structure(config, "weighted_scoring")
        if not is_valid:
            logger.error(f"Invalid weighted scoring config: {errors}")
            return False
        
        config_path = self.config_dir / "weighted_scoring.json"
        success, message = self.save_config_atomic(config, config_path)
        return success
    
    # Semantic Mapping Configuration Methods
    
    def get_semantic_mapping_config(self) -> Optional[Dict]:
        """
        Get semantic mapping configuration.
        
        Returns:
            Dictionary with semantic mapping configuration or None if not found
        """
        config_path = self.config_dir / "semantic_mapping.json"
        config_data, errors = self.load_config_with_validation(config_path, "semantic_mapping")
        
        if errors:
            for error in errors:
                logger.warning(f"Semantic mapping config: {error}")
        
        return config_data if config_data else self.get_default_config("semantic_mapping")
    
    def save_semantic_mapping_config(self, config: Dict) -> bool:
        """
        Save semantic mapping configuration.
        
        Args:
            config: Configuration dictionary to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        # Validate before saving
        is_valid, errors = self.validate_config_structure(config, "semantic_mapping")
        if not is_valid:
            logger.error(f"Invalid semantic mapping config: {errors}")
            return False
        
        config_path = self.config_dir / "semantic_mapping.json"
        success, message = self.save_config_atomic(config, config_path)
        return success

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize filename to remove invalid characters"""
        # Remove or replace invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename.strip()
    
    # Configuration Validation Methods
    
    def validate_config_structure(self, config_data: Dict[str, Any], config_type: str) -> Tuple[bool, List[str]]:
        """
        Validate configuration structure against schema.
        
        Args:
            config_data: Configuration dictionary to validate
            config_type: Type of configuration (weighted_scoring, semantic_mapping, feather, wing, pipeline)
            
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        if config_type not in CONFIG_SCHEMAS:
            errors.append(f"Unknown configuration type: {config_type}")
            return False, errors
        
        schema = CONFIG_SCHEMAS[config_type]
        
        # Check required fields
        for field in schema.get("required_fields", []):
            if field not in config_data:
                errors.append(f"Missing required field: {field}")
        
        # Check field types
        field_types = schema.get("field_types", {})
        for field, expected_type in field_types.items():
            if field in config_data:
                value = config_data[field]
                if value is not None and not isinstance(value, expected_type):
                    errors.append(f"Invalid type for field '{field}': expected {expected_type.__name__}, got {type(value).__name__}")
        
        # Check for unknown fields (warning only)
        all_known_fields = set(schema.get("required_fields", [])) | set(schema.get("optional_fields", []))
        for field in config_data.keys():
            if field not in all_known_fields and not field.startswith("_"):
                logger.warning(f"Unknown field in {config_type} config: {field}")
        
        # Nested validation for specific config types
        nested_validation = schema.get("nested_validation", {})
        for field, nested_rules in nested_validation.items():
            if field in config_data and config_data[field] is not None:
                nested_errors = self._validate_nested_field(config_data[field], field, nested_rules)
                errors.extend(nested_errors)
        
        return len(errors) == 0, errors
    
    def _validate_nested_field(self, field_value: Any, field_name: str, rules: Dict[str, Any]) -> List[str]:
        """Validate nested field values."""
        errors = []
        
        if not isinstance(field_value, dict):
            return errors
        
        value_type = rules.get("value_type")
        value_range = rules.get("value_range")
        value_required_fields = rules.get("value_required_fields", [])
        
        for key, value in field_value.items():
            # Check value type
            if value_type and not isinstance(value, value_type):
                errors.append(f"Invalid type for {field_name}['{key}']: expected {value_type}, got {type(value).__name__}")
            
            # Check value range for numeric types
            if value_range and isinstance(value, (int, float)):
                min_val, max_val = value_range
                if value < min_val or value > max_val:
                    errors.append(f"Value out of range for {field_name}['{key}']: {value} (expected {min_val}-{max_val})")
            
            # Check required fields in nested dict
            if isinstance(value, dict) and value_required_fields:
                for req_field in value_required_fields:
                    if req_field not in value:
                        errors.append(f"Missing required field in {field_name}['{key}']: {req_field}")
        
        return errors
    
    def load_config_with_validation(self, config_path: Path, config_type: str) -> Tuple[Optional[Dict], List[str]]:
        """
        Load configuration file with validation.
        
        Args:
            config_path: Path to configuration file
            config_type: Type of configuration for validation
            
        Returns:
            Tuple of (config_dict or None, list of validation errors)
        """
        errors = []
        
        if not config_path.exists():
            errors.append(f"Configuration file not found: {config_path}")
            logger.warning(f"Configuration file not found: {config_path}, using defaults")
            return self.get_default_config(config_type), errors
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in configuration file: {e}")
            logger.error(f"Corrupted configuration file {config_path}: {e}, using defaults")
            return self.get_default_config(config_type), errors
        except Exception as e:
            errors.append(f"Error reading configuration file: {e}")
            logger.error(f"Error reading configuration file {config_path}: {e}, using defaults")
            return self.get_default_config(config_type), errors
        
        # Validate structure
        is_valid, validation_errors = self.validate_config_structure(config_data, config_type)
        errors.extend(validation_errors)
        
        if not is_valid:
            logger.warning(f"Configuration validation failed for {config_path}: {validation_errors}")
        
        return config_data, errors
    
    def get_default_config(self, config_type: str) -> Optional[Dict]:
        """
        Get default configuration for a given type.
        
        Args:
            config_type: Type of configuration
            
        Returns:
            Default configuration dictionary or None if type not found
        """
        if config_type in DEFAULT_CONFIGS:
            logger.info(f"Using default configuration for {config_type}")
            return DEFAULT_CONFIGS[config_type].copy()
        return None
    
    def save_config_atomic(self, config_data: Dict, config_path: Path) -> Tuple[bool, str]:
        """
        Save configuration atomically using write-to-temp-then-rename pattern.
        
        This ensures that the configuration file is never left in a corrupted state
        even if the write operation is interrupted.
        
        Args:
            config_data: Configuration dictionary to save
            config_path: Path to save configuration to
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to temporary file first
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json.tmp',
                dir=config_path.parent
            )
            
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2)
                
                # Atomic rename (on most systems)
                shutil.move(temp_path, config_path)
                
                logger.info(f"Configuration saved atomically to {config_path}")
                return True, f"Configuration saved to {config_path}"
                
            except Exception as e:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise e
                
        except Exception as e:
            error_msg = f"Failed to save configuration: {e}"
            logger.error(error_msg)
            return False, error_msg
