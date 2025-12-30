"""
Wings Core Module
Data models and business logic for Wings.
"""

from .wing_model import Wing, FeatherSpec, CorrelationRules, WingMetadata
from .artifact_detector import ArtifactDetector
from .wing_validator import WingValidator

__all__ = [
    'Wing',
    'FeatherSpec',
    'CorrelationRules',
    'WingMetadata',
    'ArtifactDetector',
    'WingValidator'
]
