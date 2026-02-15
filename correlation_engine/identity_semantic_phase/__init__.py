"""
Identity Semantic Phase Package

Provides identity-level semantic mapping after correlation completion.
"""

from .identity_semantic_controller import (
    IdentitySemanticController,
    IdentitySemanticConfig,
    IdentitySemanticStatistics
)
from .identity_aggregator import IdentityAggregator
from .identity_registry import IdentityRegistry, IdentityRecord, RecordReference
from .identity_level_semantic_processor import IdentityLevelSemanticProcessor, IdentityProcessorStatistics
from .semantic_mapping_controller import SemanticMappingController
from .semantic_data_propagator import SemanticDataPropagator, PropagationStatistics

__all__ = [
    'IdentitySemanticController',
    'IdentitySemanticConfig',
    'IdentitySemanticStatistics',
    'IdentityAggregator',
    'IdentityRegistry',
    'IdentityRecord',
    'RecordReference',
    'IdentityLevelSemanticProcessor',
    'IdentityProcessorStatistics',
    'SemanticMappingController',
    'SemanticDataPropagator',
    'PropagationStatistics'
]
