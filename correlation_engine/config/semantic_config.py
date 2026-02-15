"""
Semantic Mapping Configuration

Centralized configuration for semantic mapping system.
Provides type-safe configuration with validation and persistence.

Task 8: Create Centralized Configuration
Requirements: Requirement 31 - Centralized Configuration Management
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path


@dataclass
class SemanticConfig:
    """
    Centralized configuration for semantic mapping system.
    
    This configuration class provides type-safe access to all semantic mapping
    settings with validation and persistence support.
    
    Attributes:
        # File Paths
        rules_file_path: Path to default semantic rules JSON file
        custom_rules_file_path: Path to custom/user-defined rules
        schema_file_path: Path to rules schema for validation
        
        # Thresholds
        default_confidence_threshold: Minimum confidence for rule matching (0.0-1.0)
        min_confidence: Minimum allowed confidence value
        max_confidence: Maximum allowed confidence value
        
        # Severity Levels
        severity_levels: Valid severity levels in order
        
        # State Flags
        enabled: Whether semantic mapping is enabled
        validate_on_load: Whether to validate rules when loading
        strict_validation: Whether to use strict validation (reject invalid rules)
        
        # Performance Settings
        batch_size: Number of matches to process in each batch
        cache_size: Maximum number of items in pattern cache
        cache_ttl_seconds: Time-to-live for cached data in seconds
        
        # Progress Reporting
        enable_progress_reporting: Whether to emit progress signals
        progress_update_interval: How often to emit progress updates (matches)
        
        # Error Handling
        continue_on_error: Whether to continue processing after errors
        max_errors_before_abort: Maximum errors before aborting (0 = unlimited)
        log_json_parse_errors: Whether to log JSON parsing errors
        
        # Rule Priority
        rule_priority_order: Order to apply rules (by category)
    """
    
    # File Paths
    rules_file_path: str = "configs/semantic_rules_default.json"
    custom_rules_file_path: str = "configs/semantic_rules_custom.json"
    schema_file_path: str = "configs/semantic_rules_schema.json"
    
    # Thresholds
    default_confidence_threshold: float = 0.5
    min_confidence: float = 0.0
    max_confidence: float = 1.0
    
    # Severity Levels (in order of importance)
    severity_levels: List[str] = field(default_factory=lambda: [
        "info", "low", "medium", "high", "critical"
    ])
    
    # State Flags
    enabled: bool = True
    validate_on_load: bool = True
    strict_validation: bool = False
    
    # Performance Settings
    batch_size: int = 1000
    cache_size: int = 10000
    cache_ttl_seconds: int = 300  # 5 minutes
    
    # Progress Reporting
    enable_progress_reporting: bool = True
    progress_update_interval: int = 100  # Update every 100 matches
    
    # Error Handling
    continue_on_error: bool = True
    max_errors_before_abort: int = 0  # 0 = unlimited
    log_json_parse_errors: bool = True
    
    # Rule Priority (categories to apply first)
    rule_priority_order: List[str] = field(default_factory=lambda: [
        "authentication",
        "process_execution",
        "file_access",
        "network_activity",
        "user_activity",
        "system_activity"
    ])
    
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate configuration settings.
        
        Task 8.2: Implement configuration validation
        
        Returns:
            Tuple of (is_valid, error_messages)
            - (True, []) if configuration is valid
            - (False, ["error1", "error2"]) if configuration has errors
        """
        errors = []
        
        # Validate file paths exist (if not empty)
        if self.rules_file_path:
            if not os.path.exists(self.rules_file_path):
                errors.append(f"Rules file not found: {self.rules_file_path}")
        
        if self.schema_file_path:
            if not os.path.exists(self.schema_file_path):
                # Schema is optional, just warn
                pass
        
        # Validate confidence range
        if not (0.0 <= self.default_confidence_threshold <= 1.0):
            errors.append(
                f"default_confidence_threshold must be between 0.0 and 1.0, "
                f"got {self.default_confidence_threshold}"
            )
        
        if not (0.0 <= self.min_confidence <= 1.0):
            errors.append(
                f"min_confidence must be between 0.0 and 1.0, "
                f"got {self.min_confidence}"
            )
        
        if not (0.0 <= self.max_confidence <= 1.0):
            errors.append(
                f"max_confidence must be between 0.0 and 1.0, "
                f"got {self.max_confidence}"
            )
        
        if self.min_confidence > self.max_confidence:
            errors.append(
                f"min_confidence ({self.min_confidence}) cannot be greater than "
                f"max_confidence ({self.max_confidence})"
            )
        
        # Validate batch size
        if self.batch_size <= 0:
            errors.append(f"batch_size must be > 0, got {self.batch_size}")
        
        # Validate cache size
        if self.cache_size < 0:
            errors.append(f"cache_size must be >= 0, got {self.cache_size}")
        
        # Validate cache TTL
        if self.cache_ttl_seconds < 0:
            errors.append(
                f"cache_ttl_seconds must be >= 0, got {self.cache_ttl_seconds}"
            )
        
        # Validate progress update interval
        if self.progress_update_interval <= 0:
            errors.append(
                f"progress_update_interval must be > 0, "
                f"got {self.progress_update_interval}"
            )
        
        # Validate max errors
        if self.max_errors_before_abort < 0:
            errors.append(
                f"max_errors_before_abort must be >= 0, "
                f"got {self.max_errors_before_abort}"
            )
        
        # Validate severity levels
        if not self.severity_levels:
            errors.append("severity_levels cannot be empty")
        
        # Check for duplicate severity levels
        if len(self.severity_levels) != len(set(self.severity_levels)):
            errors.append("severity_levels contains duplicates")
        
        return (len(errors) == 0, errors)
    
    @classmethod
    def from_file(cls, config_path: str) -> 'SemanticConfig':
        """
        Load configuration from JSON file.
        
        Task 8.3: Implement configuration persistence
        
        Args:
            config_path: Path to configuration JSON file
            
        Returns:
            SemanticConfig instance loaded from file
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file contains invalid JSON
            ValueError: If config contains invalid values
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        
        # Create config instance from dict
        config = cls(**config_dict)
        
        # Validate loaded configuration
        is_valid, errors = config.validate()
        if not is_valid:
            raise ValueError(
                f"Invalid configuration loaded from {config_path}:\n" +
                "\n".join(f"  - {error}" for error in errors)
            )
        
        return config
    
    def to_file(self, config_path: str, indent: int = 2) -> None:
        """
        Save configuration to JSON file.
        
        Task 8.3: Implement configuration persistence
        
        Args:
            config_path: Path to save configuration JSON file
            indent: JSON indentation level (default: 2)
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Validate before saving
        is_valid, errors = self.validate()
        if not is_valid:
            raise ValueError(
                "Cannot save invalid configuration:\n" +
                "\n".join(f"  - {error}" for error in errors)
            )
        
        # Convert to dict
        config_dict = asdict(self)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        # Save to file
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=indent)
    
    @classmethod
    def get_default(cls) -> 'SemanticConfig':
        """
        Get default configuration.
        
        Task 8.3: Implement configuration persistence
        
        Returns:
            SemanticConfig instance with default values
        """
        return cls()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'SemanticConfig':
        """
        Create configuration from dictionary.
        
        Args:
            config_dict: Dictionary with configuration values
            
        Returns:
            SemanticConfig instance
        """
        return cls(**config_dict)
    
    def get_rules_file_path(self, base_path: Optional[str] = None) -> str:
        """
        Get absolute path to rules file.
        
        Args:
            base_path: Base directory path (optional)
            
        Returns:
            Absolute path to rules file
        """
        if os.path.isabs(self.rules_file_path):
            return self.rules_file_path
        
        if base_path:
            return os.path.join(base_path, self.rules_file_path)
        
        return os.path.abspath(self.rules_file_path)
    
    def get_custom_rules_file_path(self, base_path: Optional[str] = None) -> str:
        """
        Get absolute path to custom rules file.
        
        Args:
            base_path: Base directory path (optional)
            
        Returns:
            Absolute path to custom rules file
        """
        if os.path.isabs(self.custom_rules_file_path):
            return self.custom_rules_file_path
        
        if base_path:
            return os.path.join(base_path, self.custom_rules_file_path)
        
        return os.path.abspath(self.custom_rules_file_path)
    
    def get_schema_file_path(self, base_path: Optional[str] = None) -> str:
        """
        Get absolute path to schema file.
        
        Args:
            base_path: Base directory path (optional)
            
        Returns:
            Absolute path to schema file
        """
        if os.path.isabs(self.schema_file_path):
            return self.schema_file_path
        
        if base_path:
            return os.path.join(base_path, self.schema_file_path)
        
        return os.path.abspath(self.schema_file_path)
    
    def is_severity_valid(self, severity: str) -> bool:
        """
        Check if severity level is valid.
        
        Args:
            severity: Severity level to check
            
        Returns:
            True if severity is valid, False otherwise
        """
        return severity in self.severity_levels
    
    def get_severity_index(self, severity: str) -> int:
        """
        Get index of severity level (for comparison).
        
        Args:
            severity: Severity level
            
        Returns:
            Index of severity level (0 = lowest, higher = more severe)
            Returns -1 if severity is invalid
        """
        try:
            return self.severity_levels.index(severity)
        except ValueError:
            return -1
    
    def is_confidence_valid(self, confidence: float) -> bool:
        """
        Check if confidence value is valid.
        
        Args:
            confidence: Confidence value to check
            
        Returns:
            True if confidence is valid, False otherwise
        """
        return self.min_confidence <= confidence <= self.max_confidence
    
    def __repr__(self) -> str:
        """String representation of configuration."""
        return (
            f"SemanticConfig("
            f"enabled={self.enabled}, "
            f"rules_file={self.rules_file_path}, "
            f"batch_size={self.batch_size}, "
            f"cache_ttl={self.cache_ttl_seconds}s)"
        )


# Global default configuration instance
_default_config: Optional[SemanticConfig] = None


def get_global_config() -> SemanticConfig:
    """
    Get global default configuration instance.
    
    Returns:
        Global SemanticConfig instance
    """
    global _default_config
    if _default_config is None:
        _default_config = SemanticConfig.get_default()
    return _default_config


def set_global_config(config: SemanticConfig) -> None:
    """
    Set global default configuration instance.
    
    Args:
        config: SemanticConfig instance to set as global
    """
    global _default_config
    _default_config = config


def reset_global_config() -> None:
    """Reset global configuration to default values."""
    global _default_config
    _default_config = SemanticConfig.get_default()
