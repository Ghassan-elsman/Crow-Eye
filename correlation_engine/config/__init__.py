"""Configuration Management Package.

Public API (post-consolidation):
    - IntegratedConfigurationManager — single façade for case-level and scoring
      configuration. Use this for new code that needs case directories, semantic
      mappings, scoring weights, score thresholds, or case-file lifecycle ops.
    - ConfigManager — feather / wing / pipeline artifact CRUD (orthogonal to
      case config; kept as a sibling).
    - PipelineConfigurationManager — pipeline execution session state.
    - ScoreConfigurationManager — singleton owning the centralised score
      config. Reachable via ``IntegratedConfigurationManager().score_config_manager``
      for new code; kept importable directly for back-compat singleton calls.

The previously public ``CaseConfigurationManager``, ``CaseConfigurationFileManager``
and ``CaseSpecificConfigurationManager`` are now private services under
``_case_coordinator_service``, ``_case_config_file_service`` and
``_case_specific_config_service``. Reach their behaviour through
``IntegratedConfigurationManager``'s public methods (case_files, case_specific,
get_case_config_file_statistics, save_case_scoring_weights, etc).
"""

from .feather_config import FeatherConfig
from .wing_config import WingConfig, WingFeatherReference
from .pipeline_config import PipelineConfig
from .config_manager import ConfigManager
from .semantic_mapping import SemanticMapping, SemanticCondition, SemanticRule, SemanticMappingManager
from .integrated_configuration_manager import IntegratedConfigurationManager
from .score_configuration_manager import ScoreConfigurationManager

__all__ = [
    # Primary façade for case + scoring config
    'IntegratedConfigurationManager',
    # Artifact CRUD (orthogonal domain)
    'ConfigManager',
    'FeatherConfig',
    'WingConfig',
    'WingFeatherReference',
    'PipelineConfig',
    # Semantic mapping types
    'SemanticMapping',
    'SemanticCondition',
    'SemanticRule',
    'SemanticMappingManager',
    # Singleton, kept for legacy callers
    'ScoreConfigurationManager',
]

