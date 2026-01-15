"""
Pipeline Configuration
Complete end-to-end configuration for the entire correlation process.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
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
    auto_create_feathers: bool = True  # Automatically create feathers from configs
    auto_run_correlation: bool = True  # Automatically run correlation after feathers
    
    # NEW: Engine selection and filtering
    engine_type: str = "time_window_scanning"  # "time_window_scanning" or "identity_based"
    time_period_start: Optional[str] = None  # ISO format datetime string
    time_period_end: Optional[str] = None  # ISO format datetime string
    identity_filters: Optional[List[str]] = None  # List of identity patterns (for identity engine)
    identity_filter_case_sensitive: bool = False  # Case-sensitive identity matching
    
    # NEW: Semantic mapping and scoring configuration
    semantic_mapping_config: Optional[Dict[str, Any]] = None  # Semantic mapping settings
    weighted_scoring_config: Optional[Dict[str, Any]] = None  # Weighted scoring settings (legacy)
    
    # Pipeline-specific semantic rules (advanced multi-value rules with AND/OR logic)
    semantic_rules: List[Dict[str, Any]] = field(default_factory=list)
    
    # Pipeline-level scoring configuration
    scoring_config: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'use_weighted_scoring': True,
        'thresholds': {
            'low': 0.3,
            'medium': 0.5,
            'high': 0.7,
            'critical': 0.9
        },
        'default_tier_weights': {
            'tier1': 1.0,   # Primary evidence (Logs, Prefetch)
            'tier2': 0.8,   # Secondary evidence (Registry, AmCache)
            'tier3': 0.6,   # Supporting evidence (LNK, Jumplists)
            'tier4': 0.4    # Contextual evidence (MFT, USN)
        }
    })
    
    debug_mode: bool = False  # Enable debug output
    verbose_logging: bool = False  # Enable verbose logging
    
    # Output settings
    output_directory: str = ""
    generate_report: bool = True
    report_format: str = "html"  # "html", "pdf", "json"
    
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
            'engine_type': self.engine_type,  # NEW
            'time_period_start': self.time_period_start,  # NEW
            'time_period_end': self.time_period_end,  # NEW
            'identity_filters': self.identity_filters,  # NEW
            'identity_filter_case_sensitive': self.identity_filter_case_sensitive,  # NEW
            'semantic_mapping_config': self.semantic_mapping_config,  # NEW
            'weighted_scoring_config': self.weighted_scoring_config,  # NEW (legacy)
            'semantic_rules': self.semantic_rules,  # Pipeline-specific semantic rules
            'scoring_config': self.scoring_config,  # Pipeline-level scoring configuration
            'debug_mode': self.debug_mode,  # NEW
            'verbose_logging': self.verbose_logging,  # NEW
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
        
        # NEW: Provide defaults for backward compatibility
        if 'engine_type' not in data:
            data['engine_type'] = 'time_based'
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
        if 'semantic_rules' not in data:
            data['semantic_rules'] = []
        if 'scoring_config' not in data:
            data['scoring_config'] = {
                'enabled': True,
                'use_weighted_scoring': True,
                'thresholds': {
                    'low': 0.3,
                    'medium': 0.5,
                    'high': 0.7,
                    'critical': 0.9
                },
                'default_tier_weights': {
                    'tier1': 1.0,
                    'tier2': 0.8,
                    'tier3': 0.6,
                    'tier4': 0.4
                }
            }
        
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'PipelineConfig':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'PipelineConfig':
        """Load configuration from JSON file"""
        with open(file_path, 'r') as f:
            return cls.from_json(f.read())
    
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
