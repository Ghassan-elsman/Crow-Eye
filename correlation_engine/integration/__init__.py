"""
Integration module for Crow Eye correlation engine.

Provides integration components for automatic Feather generation,
default Wings loading, and Crow-Eye case management.
"""

from .crow_eye_integration import CrowEyeIntegration
from .auto_feather_generator import AutoFeatherGenerator
from .default_wings_loader import (
    DefaultWingsLoader,
    initialize_default_wings_on_startup,
    get_default_wings_for_case
)
from .feather_mappings import (
    FEATHER_MAPPINGS,
    get_feather_mappings,
    get_mapping_by_name,
    get_mappings_by_artifact_type,
    get_mappings_by_source_db
)

__all__ = [
    'CrowEyeIntegration',
    'AutoFeatherGenerator',
    'DefaultWingsLoader',
    'initialize_default_wings_on_startup',
    'get_default_wings_for_case',
    'FEATHER_MAPPINGS',
    'get_feather_mappings',
    'get_mapping_by_name',
    'get_mappings_by_artifact_type',
    'get_mappings_by_source_db',
]
