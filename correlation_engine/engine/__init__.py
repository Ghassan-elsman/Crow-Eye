"""
Correlation Engine Package
Core engine for executing Wings and correlating feather data.
"""

from .correlation_engine import CorrelationEngine
from .correlation_result import CorrelationResult, CorrelationMatch
from .feather_loader import FeatherLoader
from .weighted_scoring import WeightedScoringEngine
from .results_formatter import ResultsFormatter, apply_semantic_mappings_to_result
from .base_engine import BaseCorrelationEngine, EngineMetadata, FilterConfig
from .engine_selector import EngineSelector, EngineType

__all__ = [
    'CorrelationEngine',
    'CorrelationResult',
    'CorrelationMatch',
    'FeatherLoader',
    'WeightedScoringEngine',
    'ResultsFormatter',
    'apply_semantic_mappings_to_result',
    'BaseCorrelationEngine',
    'EngineMetadata',
    'FilterConfig',
    'EngineSelector',
    'EngineType'
]
