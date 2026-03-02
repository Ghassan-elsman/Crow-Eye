"""
Performance Configuration Manager

This module provides configuration management for Time Engine performance tuning.
Supports validation, safe defaults, and JSON-based configuration loading.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class PerformanceConfig:
    """
    Configuration for Time Engine performance tuning.

    This class centralizes all performance-related parameters with safe defaults
    and validation logic.

    Requirements:
    - 8.1: Window size configuration
    - 8.2: Parallel worker count configuration
    - 8.3: Cache size configuration
    - 8.4: Memory threshold configuration
    - 8.5: Validation and safe defaults
    """

    # Window configuration (Requirement 8.1)
    window_size_minutes: int = 60

    # Parallel processing (Requirement 8.2)
    max_workers: Optional[int] = None  # None = auto-detect
    enable_parallel: bool = True
    parallel_threshold_windows: int = 100  # Min windows for parallel to be worth it

    # Memory management (Requirement 8.4)
    memory_threshold_mb: int = 4096
    streaming_threshold_mb: Optional[int] = None  # Auto-calculated if None
    cache_reduction_threshold_mb: Optional[int] = None  # Auto-calculated if None

    # Cache configuration (Requirement 8.3)
    query_cache_size_mb: int = 512
    query_cache_ttl_seconds: int = 3600
    timestamp_cache_size: int = 10000

    # Empty window detection
    enable_empty_window_skipping: bool = True

    # Profiling
    enable_profiling: bool = True
    profile_memory: bool = True

    def __post_init__(self):
        """Auto-calculate dependent thresholds if not provided."""
        if self.streaming_threshold_mb is None:
            self.streaming_threshold_mb = int(self.memory_threshold_mb * 0.9)
        if self.cache_reduction_threshold_mb is None:
            self.cache_reduction_threshold_mb = int(self.memory_threshold_mb * 0.8)

    def validate(self) -> List[str]:
        """
        Validate configuration values.

        Returns:
            List of validation error messages. Empty list if valid.

        Requirement 8.5: Configuration validation
        """
        errors = []

        # Window size validation
        if self.window_size_minutes < 1:
            errors.append("window_size_minutes must be >= 1")
        if self.window_size_minutes > 1440:  # 24 hours
            errors.append("window_size_minutes should not exceed 1440 (24 hours)")

        # Worker count validation
        if self.max_workers is not None:
            if self.max_workers < 1:
                errors.append("max_workers must be >= 1 or None for auto-detect")
            if self.max_workers > 64:
                errors.append("max_workers should not exceed 64")

        if self.parallel_threshold_windows < 1:
            errors.append("parallel_threshold_windows must be >= 1")

        # Memory threshold validation
        if self.memory_threshold_mb < 1024:
            errors.append("memory_threshold_mb must be >= 1024 (1 GB)")

        if self.streaming_threshold_mb >= self.memory_threshold_mb:
            errors.append("streaming_threshold_mb must be < memory_threshold_mb")

        if self.cache_reduction_threshold_mb >= self.streaming_threshold_mb:
            errors.append("cache_reduction_threshold_mb must be < streaming_threshold_mb")

        # Cache size validation
        if self.query_cache_size_mb < 0:
            errors.append("query_cache_size_mb must be >= 0")
        if self.query_cache_size_mb > self.memory_threshold_mb // 2:
            errors.append("query_cache_size_mb should not exceed half of memory_threshold_mb")

        if self.query_cache_ttl_seconds < 0:
            errors.append("query_cache_ttl_seconds must be >= 0")

        if self.timestamp_cache_size < 0:
            errors.append("timestamp_cache_size must be >= 0")

        return errors

    @staticmethod
    def get_safe_defaults() -> 'PerformanceConfig':
        """
        Get a configuration with safe default values.

        Returns:
            PerformanceConfig with default values

        Requirement 8.5: Safe defaults for fallback
        """
        return PerformanceConfig()

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'PerformanceConfig':
        """
        Create configuration from dictionary.

        Args:
            config_dict: Dictionary with configuration values

        Returns:
            PerformanceConfig instance
        """
        # Filter to only known fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_fields}
        return cls(**filtered_dict)


def load_performance_config(config_path: Optional[str] = None) -> PerformanceConfig:
    """
    Load performance configuration from JSON file or use defaults.

    Args:
        config_path: Optional path to JSON configuration file

    Returns:
        PerformanceConfig instance with validated configuration

    Requirements:
    - 8.1, 8.2, 8.3, 8.4: Load all configuration parameters
    - 8.5: Validate and use safe defaults on error
    """
    # Try to load from file if path provided
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config_dict = json.load(f)

            config = PerformanceConfig.from_dict(config_dict)
            logger.info(f"Loaded performance configuration from {config_path}")

        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(
                f"Failed to load configuration from {config_path}: {e}. "
                f"Using safe defaults."
            )
            return PerformanceConfig.get_safe_defaults()
    else:
        # No config file or file doesn't exist
        if config_path:
            logger.info(
                f"Configuration file {config_path} not found. Using safe defaults."
            )
        config = PerformanceConfig.get_safe_defaults()

    # Validate configuration
    errors = config.validate()
    if errors:
        logger.warning(
            f"Invalid configuration values: {', '.join(errors)}. "
            f"Using safe defaults."
        )
        return PerformanceConfig.get_safe_defaults()

    return config


def save_performance_config(config: PerformanceConfig, config_path: str) -> None:
    """
    Save performance configuration to JSON file.

    Args:
        config: PerformanceConfig instance to save
        config_path: Path where to save the configuration
    """
    # Validate before saving
    errors = config.validate()
    if errors:
        raise ValueError(f"Cannot save invalid configuration: {', '.join(errors)}")

    with open(config_path, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)

    logger.info(f"Saved performance configuration to {config_path}")
