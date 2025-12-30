"""
Configuration Management Package
Handles saving and loading configurations for feathers, wings, and complete pipelines.
"""

from .feather_config import FeatherConfig
from .wing_config import WingConfig, WingFeatherReference
from .pipeline_config import PipelineConfig
from .config_manager import ConfigManager

__all__ = [
    'FeatherConfig',
    'WingConfig',
    'WingFeatherReference',
    'PipelineConfig',
    'ConfigManager'
]

