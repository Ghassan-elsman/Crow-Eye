"""
Pipeline Configuration
Complete end-to-end configuration for the entire correlation process.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from .feather_config import FeatherConfig
from .wing_config import WingConfig


@dataclass
class PipelineConfig:
    """Complete pipeline configuration for automated analysis"""
    
    # Identification
    config_name: str
    pipeline_name: str
    description: str
    
    # Case information
    case_name: str = ""
    case_id: str = ""
    investigator: str = ""
    
    # Feather creation configurations
    feather_configs: List[FeatherConfig] = field(default_factory=list)
    
    # Wing configurations
    wing_configs: List[WingConfig] = field(default_factory=list)
    
    # Execution settings
    auto_create_feathers: bool = True # Automatically create feathers from configs
    auto_run_correlation: bool = True # Automatically run correlation after feathers
    
    # NEW: Engine selection and filtering
    #
    # Identity-Based is the default engine. Every pipeline anything builds -
    # the per-case default from DefaultPipelineCreator, and anything the
    # Pipeline Builder saves - inherits this, and neither passes an engine of
    # its own. A pipeline that names an engine keeps it; this only decides
    # what a pipeline says when nobody chose.
    engine_type: str = "identity_based" # "identity_based" or "time_window_scanning"

    # Runtime-only: groups the per-wing executions of one run (live GUI runs
    # create a separate execution per wing). Set by the execution worker /
    # PipelineExecutor per run; deliberately NOT serialized in to_dict —
    # a saved pipeline must not pin a stale run id.
    run_group_id: Optional[str] = None
    # None = the whole case. Both used to default to "the 365 days up to now",
    # so a run's evidence depended on the day it was started.
    time_period_start: Optional[str] = None # ISO format datetime string
    time_period_end: Optional[str] = None # ISO format datetime string
    identity_filters: Optional[List[str]] = None # List of identity patterns (for identity engine)
    identity_filter_case_sensitive: bool = False # Case-sensitive identity matching
    
    # NEW: Semantic mapping and scoring configuration
    semantic_mapping_config: Optional[Dict[str, Any]] = None # Semantic mapping settings
    weighted_scoring_config: Optional[Dict[str, Any]] = None # Weighted scoring settings (legacy)
    
    # Identity Semantic Phase configuration (Requirements 6.2, 6.3, 6.4, 6.5)
    identity_semantic_phase_enabled: bool = True # Enable identity-level semantic mapping in final analysis phase
    
    # Pipeline-specific semantic rules (advanced multi-value rules with AND/OR logic)
    semantic_rules: List[Dict[str, Any]] = field(default_factory=list)
    
    # Pipeline-level scoring configuration
    scoring_config: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'use_weighted_scoring': True,
        'thresholds': __import__('correlation_engine.config.centralized_score_config', fromlist=['CentralizedScoreConfig']).CentralizedScoreConfig.get_default().thresholds,
        'default_tier_weights': __import__('correlation_engine.config.centralized_score_config', fromlist=['CentralizedScoreConfig']).CentralizedScoreConfig.get_default().tier_weights
    })
    
    debug_mode: bool = False # Enable debug output
    verbose_logging: bool = False # Enable verbose logging
    
    # Output settings
    output_directory: str = ""
    generate_report: bool = True
    report_format: str = "html" # "html", "pdf", "json"
    
    # Metadata
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    last_executed: Optional[str] = None
    version: str = "1.0"
    
    # Tags
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'config_name': self.config_name,
            'pipeline_name': self.pipeline_name,
            'description': self.description,
            'case_name': self.case_name,
            'case_id': self.case_id,
            'investigator': self.investigator,
            'feather_configs': [f.to_dict() for f in self.feather_configs],
            'wing_configs': [w.to_dict() for w in self.wing_configs],
            'auto_create_feathers': self.auto_create_feathers,
            'auto_run_correlation': self.auto_run_correlation,
            'engine_type': self.engine_type, # NEW
            'time_period_start': self.time_period_start, # NEW
            'time_period_end': self.time_period_end, # NEW
            'identity_filters': self.identity_filters, # NEW
            'identity_filter_case_sensitive': self.identity_filter_case_sensitive, # NEW
            'semantic_mapping_config': self.semantic_mapping_config, # NEW
            'weighted_scoring_config': self.weighted_scoring_config, # NEW (legacy)
            'identity_semantic_phase_enabled': self.identity_semantic_phase_enabled, # Identity Semantic Phase
            'semantic_rules': self.semantic_rules, # Pipeline-specific semantic rules
            'scoring_config': self.scoring_config, # Pipeline-level scoring configuration
            'debug_mode': self.debug_mode, # NEW
            'verbose_logging': self.verbose_logging, # NEW
            'output_directory': self.output_directory,
            'generate_report': self.generate_report,
            'report_format': self.report_format,
            'created_date': self.created_date,
            'last_modified': self.last_modified,
            'last_executed': self.last_executed,
            'version': self.version,
            'tags': self.tags,
            'notes': self.notes
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save configuration to JSON file"""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
        try:
            from utils import custody
            custody.record_config(file_path, 'pipeline')
        except Exception:
            pass
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PipelineConfig':
        """Create from dictionary"""
        # Convert feather config dicts to FeatherConfig objects
        if 'feather_configs' in data:
            data['feather_configs'] = [
                FeatherConfig.from_dict(f) if isinstance(f, dict) else f
                for f in data['feather_configs']
            ]
        
        # Convert wing config dicts to WingConfig objects
        if 'wing_configs' in data:
            data['wing_configs'] = [
                WingConfig.from_dict(w) if isinstance(w, dict) else w
                for w in data['wing_configs']
            ]
        
        # run_group_id is runtime-only; discard if present in serialized data
        data.pop('run_group_id', None)

        # NEW: Provide defaults for backward compatibility
        #
        # This is a MIGRATION value, not the product default (which is
        # identity_based, above). It fires only for a pipeline saved before the
        # field existed, and those pipelines have been running on the
        # time-window engine ever since. Changing it to agree with the new
        # default would silently change how an existing case runs, so leave it
        # alone - the disagreement is deliberate.
        if 'engine_type' not in data:
            data['engine_type'] = 'time_window_scanning'
        # No period saved means the whole case. It meant "the 365 days up to
        # whenever the pipeline is opened", so an old pipeline lost evidence
        # older than a year from today, and a different set each day.
        if 'time_period_start' not in data:
            data['time_period_start'] = None
        if 'time_period_end' not in data:
            data['time_period_end'] = None
        if 'identity_filters' not in data:
            data['identity_filters'] = None
        if 'identity_filter_case_sensitive' not in data:
            data['identity_filter_case_sensitive'] = False
        if 'semantic_mapping_config' not in data:
            data['semantic_mapping_config'] = None
        if 'weighted_scoring_config' not in data:
            data['weighted_scoring_config'] = None
        if 'debug_mode' not in data:
            data['debug_mode'] = False
        if 'verbose_logging' not in data:
            data['verbose_logging'] = False
        if 'identity_semantic_phase_enabled' not in data:
            data['identity_semantic_phase_enabled'] = True # Enabled by default
        if 'semantic_rules' not in data:
            data['semantic_rules'] = []
        if 'scoring_config' not in data:
            data['scoring_config'] = {
                'enabled': True,
                'use_weighted_scoring': True,
                'thresholds': __import__('correlation_engine.config.centralized_score_config', fromlist=['CentralizedScoreConfig']).CentralizedScoreConfig.get_default().thresholds,
                'default_tier_weights': __import__('correlation_engine.config.centralized_score_config', fromlist=['CentralizedScoreConfig']).CentralizedScoreConfig.get_default().tier_weights
            }
        
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'PipelineConfig':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'PipelineConfig':
        """Load configuration from JSON file, its feather paths rebased to the
        case it sits in (see rebase_to_case)."""
        with open(file_path, 'r') as f:
            config = cls.from_json(f.read())
        config.rebase_to_case(Path(file_path).resolve().parent.parent)
        return config

    def rebase_to_case(self, correlation_dir) -> int:
        """Point feather paths that no longer exist at this case's own copies.

        A pipeline stores absolute paths. A case folder that was moved, copied
        or synced (the 16-2-2026 pipeline points at a OneDrive folder that no
        longer holds it) kept the old ones, every feather then failed to
        resolve, and every Wing reported "this case has no ...". A path that
        still exists is never touched; one that does not is replaced only by a
        file of the same name in <case>/Correlation/feathers (the feather) or
        <case>/Target_Artifacts (its source). Returns how many were rebased."""
        correlation_dir = Path(correlation_dir)
        feathers = correlation_dir / "feathers"
        artifacts = correlation_dir.parent / "Target_Artifacts"
        moved = 0
        for fc in self.feather_configs or []:
            for attr, folder in (('output_database', feathers), ('source_database', artifacts)):
                value = getattr(fc, attr, None)
                if not value or Path(value).exists():
                    continue
                candidate = folder / value.replace(chr(92), '/').rsplit('/', 1)[-1]
                if candidate.exists():
                    setattr(fc, attr, str(candidate))
                    moved += 1
        return moved
    
    def add_feather_config(self, feather_config: FeatherConfig):
        """Add a feather configuration to the pipeline"""
        self.feather_configs.append(feather_config)
        self.last_modified = datetime.now().isoformat()
    
    def add_wing_config(self, wing_config: WingConfig):
        """Add a wing configuration to the pipeline"""
        self.wing_configs.append(wing_config)
        self.last_modified = datetime.now().isoformat()
    
    def get_feather_config(self, config_name: str) -> Optional[FeatherConfig]:
        """Get a feather config by name"""
        for config in self.feather_configs:
            if config.config_name == config_name:
                return config
        return None
    
    def get_wing_config(self, config_name: str) -> Optional[WingConfig]:
        """Get a wing config by name"""
        for config in self.wing_configs:
            if config.config_name == config_name:
                return config
        return None
