"""
ConfigManager for EYE AI Forensic Assistant.

This module provides configuration management for EYE, including loading,
saving, and validating configuration against JSON schema.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import jsonschema
from jsonschema import validate, ValidationError


class ConfigManager:
    """
    Manages EYE configuration with JSON schema validation.
    
    Handles loading and saving of eye_config.json with validation against
    eye_config_schema.json. Supports non-sensitive settings like model name,
    backend type, and context window configuration.
    """
    
    def __init__(self, config_dir: str = "configs"):
        """
        Initialize ConfigManager.
        
        Args:
            config_dir: Directory containing configuration files (default: "configs")
        """
        self.config_dir = Path(config_dir)
        self.config_path = self.config_dir / "eye_config.json"
        self.schema_path = self.config_dir / "eye_config_schema.json"
        self._schema: Optional[Dict[str, Any]] = None
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from configs/eye_config.json.
        
        Returns:
            Configuration dictionary, or empty dict if file doesn't exist or is incomplete
            
        Raises:
            json.JSONDecodeError: If the file contains invalid JSON
        """
        if not self.config_path.exists():
            # Return empty config instead of raising exception
            # This allows first-time setup to proceed without errors
            return {}
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Check if config has required fields before validating
        # If missing required fields, treat as incomplete and return empty dict
        required_fields = ["integration_type", "backend", "model_name"]
        if not all(field in config for field in required_fields):
            return {}
        
        # Validate against schema only if config has required fields
        self.validate_config(config)
        
        return config
    
    def save_config(self, config_dict: Dict[str, Any]) -> None:
        """
        Save configuration to configs/eye_config.json with JSON schema validation.
        
        Args:
            config_dict: Configuration dictionary to save
            
        Raises:
            ValidationError: If configuration doesn't match the schema
            OSError: If unable to write to the configuration file
        """
        # Validate before saving
        self.validate_config(config_dict)
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Write configuration to file
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2)
    
    def validate_config(self, config_dict: Dict[str, Any]) -> None:
        """
        Validate configuration dictionary against JSON schema.
        
        Args:
            config_dict: Configuration dictionary to validate
            
        Raises:
            FileNotFoundError: If schema file does not exist
            ValidationError: If configuration doesn't match the schema
        """
        # Load schema if not already loaded
        if self._schema is None:
            if not self.schema_path.exists():
                raise FileNotFoundError(
                    f"Schema file not found: {self.schema_path}"
                )
            
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                self._schema = json.load(f)
        
        # Validate configuration against schema
        try:
            validate(instance=config_dict, schema=self._schema)
        except ValidationError as e:
            raise ValidationError(
                f"Configuration validation failed: {e.message}"
            )
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a specific configuration value.
        
        Args:
            key: Configuration key (supports dot notation for nested keys)
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        try:
            config = self.load_config()
            
            # Support dot notation for nested keys
            keys = key.split('.')
            value = config
            for k in keys:
                value = value[k]
            
            return value
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            return default
    
    def update_config_value(self, key: str, value: Any) -> None:
        """
        Update a specific configuration value.
        
        Args:
            key: Configuration key (supports dot notation for nested keys)
            value: New value to set
            
        Raises:
            ValidationError: If updated configuration is invalid
        """
        # Load existing config or start with empty dict
        config = self.load_config() if self.config_exists() else {}
        
        # Support dot notation for nested keys
        keys = key.split('.')
        current = config
        
        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Set the value
        current[keys[-1]] = value
        
        # Save updated configuration
        self.save_config(config)
    
    def config_exists(self) -> bool:
        """
        Check if configuration file exists.
        
        Returns:
            True if eye_config.json exists, False otherwise
        """
        return self.config_path.exists()

    def is_configured(self) -> bool:
        """
        Check if EYE is fully configured with required fields.
        
        Returns:
            True if configuration exists and is complete, False otherwise
        """
        try:
            config = self.load_config()
            return bool(config)
        except Exception:
            return False
