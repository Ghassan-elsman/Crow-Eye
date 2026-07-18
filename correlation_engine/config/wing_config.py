"""
Wing Configuration
Stores wing definitions with references to feather configs.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional

# Import centralized score configuration manager
from .score_configuration_manager import ScoreConfigurationManager
from .eye_authorship import EyeAuthorship


@dataclass
class WingFeatherReference:
    """Reference to a feather used in a wing"""
    feather_config_name: str # Name of the feather config
    feather_database_path: str # Path to the feather database
    artifact_type: str
    feather_id: str # ID used in the wing
    table_name: Optional[str] = None # Optional: Override table name
    artifact_type_override: Optional[str] = None # Optional: Override artifact type
    
    # Weighted scoring fields
    weight: float = 0.0 # Weight for weighted scoring (0.0 - 1.0)
    tier: int = 0 # Tier number for grouping (1-4)
    tier_name: str = "" # Human-readable tier name


def _get_anchor_priority_from_registry() -> List[str]:
    """Get anchor priority list from artifact type registry"""
    try:
        from .artifact_type_registry import get_registry
        return get_registry().get_anchor_priority_list()
    except Exception:
        # Fallback to hard-coded defaults if registry fails
        return [
            "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
            "Jumplists", "LNK", "MFT", "USN"
        ]


@dataclass
class WingConfig:
    """Configuration for a wing (correlation rule)"""
    
    # Identification
    config_name: str
    wing_name: str
    wing_id: str
    
    # Wing definition
    description: str
    proves: str # What this wing proves
    author: str
    
    # Feathers used
    feathers: List[WingFeatherReference] = field(default_factory=list)
    
    # Correlation rules
    time_window_minutes: int = 180 # Default: 3 hours for better correlation accuracy
    minimum_matches: int = 1
    
    # Filters (wing-level)
    target_application: str = ""
    target_file_path: str = ""
    target_event_id: str = ""
    apply_to: str = "all" # "all" or "specific"
    
    # Anchor priority
    anchor_priority: List[str] = field(default_factory=lambda: _get_anchor_priority_from_registry())
    
    # Weighted scoring configuration - ENABLED BY DEFAULT
    use_weighted_scoring: bool = True # Default to True for better correlation accuracy
    # NOTE: Local scoring dict maintained for backward compatibility
    # New code should use get_score_thresholds() and get_tier_weights() methods
    scoring: Dict = field(default_factory=lambda: {
        'enabled': True,
        'thresholds': {
            'low': 0.3,
            'medium': 0.5,
            'high': 0.7,
            'critical': 0.9
        },
        'default_tier_weights': {
            'tier1': 1.0, # Primary evidence (Logs, Prefetch)
            'tier2': 0.8, # Secondary evidence (Registry, AmCache)
            'tier3': 0.6, # Supporting evidence (LNK, Jumplists)
            'tier4': 0.4 # Contextual evidence (MFT, USN)
        }
    })
    
    # Wing-specific semantic rules
    semantic_rules: List[Dict] = field(default_factory=list)
    
    # Metadata
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    version: str = "1.0"
    
    # Tags and categorization
    tags: List[str] = field(default_factory=list)
    case_types: List[str] = field(default_factory=list)

    # EYE agent provenance — populated when EYE creates / edits the wing.
    # ``None`` for human-authored or built-in wings (back-compat). The
    # correlation_edit_wing handler refuses to mutate a wing whose
    # ``eye_authorship`` is ``None`` or whose ``created_by`` does not
    # start with ``"eye"``. See correlation_engine/config/eye_authorship.py.
    eye_authorship: Optional[EyeAuthorship] = None

    # Centralized score configuration manager (not serialized)
    _score_config_manager: Optional[ScoreConfigurationManager] = field(default=None, init=False, repr=False)
    
    def __post_init__(self):
        """Initialize score configuration manager after dataclass initialization"""
        self._score_config_manager = ScoreConfigurationManager()
    
    def get_score_thresholds(self) -> Dict[str, float]:
        """
        Get score thresholds from centralized configuration.
        
        Returns:
            Dictionary of score thresholds (low, medium, high, critical)
        
        Requirements: 7.2, 8.2
        """
        if self._score_config_manager is None:
            self._score_config_manager = ScoreConfigurationManager()
        
        config = self._score_config_manager.get_configuration()
        return config.thresholds.copy()
    
    def get_tier_weights(self) -> Dict[str, float]:
        """
        Get tier weights from centralized configuration.
        
        Returns:
            Dictionary of tier weights (tier1, tier2, tier3, tier4)
        
        Requirements: 7.2, 8.2
        """
        if self._score_config_manager is None:
            self._score_config_manager = ScoreConfigurationManager()
        
        config = self._score_config_manager.get_configuration()
        return config.tier_weights.copy()
    
    @staticmethod
    def semantic_rules_are_advanced(semantic_rules: List[Dict]) -> bool:
        """
        True if any rule uses a capability that only the Identity-Based engine
        supports: an advanced ``rule_type`` (absence/sequence/threshold), nested
        ``condition_groups``, or a condition with ``negate`` / ``compare_to_feather``.

        The Time-Window Scanning engine evaluates one representative row per
        feather per match, so multi-row / ordered / absence logic cannot be
        expressed there. Used to warn the user (and offer an engine switch)
        before running such a wing on the Time-Window engine.
        """
        for rule in semantic_rules or []:
            if not isinstance(rule, dict):
                continue
            if str(rule.get('rule_type', 'match')).lower() != 'match':
                return True
            if rule.get('condition_groups'):
                return True
            for cond in rule.get('conditions', []) or []:
                if isinstance(cond, dict) and (cond.get('negate') or cond.get('compare_to_feather')):
                    return True
        return False

    def has_advanced_rules(self) -> bool:
        """Whether this wing contains any Identity-engine-only advanced rules."""
        return self.semantic_rules_are_advanced(self.semantic_rules)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert WingFeatherReference objects to dicts
        data['feathers'] = [asdict(f) for f in self.feathers]
        # Remove non-serializable fields
        data.pop('_score_config_manager', None)
        return data
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save configuration to JSON file"""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WingConfig':
        """Create from dictionary"""
        # Debug logging
        print(f"[WingConfig] Loading wing: {data.get('wing_name', 'Unknown')}")
        print(f"[WingConfig] Has 'feathers' key: {'feathers' in data}")
        if 'feathers' in data:
            print(f"[WingConfig] Number of feathers in data: {len(data['feathers'])}")
        
        # Convert feather dicts to WingFeatherReference objects
        if 'feathers' in data:
            feather_refs = []
            for i, f in enumerate(data['feathers']):
                if isinstance(f, dict):
                    print(f"[WingConfig] Feather {i+1}: {f.get('feather_id', 'unknown')}")
                    
                    # Handle Wing Creator JSON format (uses database_filename)
                    if 'database_filename' in f and 'feather_database_path' not in f:
                        f = f.copy() # Don't modify original
                        f['feather_database_path'] = f.pop('database_filename')
                    
                    # Handle missing feather_config_name (use feather_id as fallback)
                    if 'feather_config_name' not in f and 'feather_id' in f:
                        f['feather_config_name'] = f['feather_id']
                    
                    # Ensure required fields exist
                    if 'feather_database_path' not in f:
                        print(f"[WingConfig] WARNING: Feather {i+1} missing feather_database_path!")
                    if 'artifact_type' not in f:
                        print(f"[WingConfig] WARNING: Feather {i+1} missing artifact_type!")
                    
                    # Filter out unexpected keys
                    valid_keys = {
                        'feather_config_name', 'feather_database_path', 'artifact_type',
                        'feather_id', 'table_name', 'artifact_type_override',
                        'weight', 'tier', 'tier_name' # Weighted scoring fields
                    }
                    filtered_f = {k: v for k, v in f.items() if k in valid_keys}
                    
                    feather_refs.append(WingFeatherReference(**filtered_f))
                else:
                    feather_refs.append(f)
            
            data['feathers'] = feather_refs
            print(f"[WingConfig] Created {len(feather_refs)} feather references")
        else:
            print(f"[WingConfig] WARNING: No 'feathers' key in wing data!")
        
        # Handle Wing Creator JSON format (nested correlation_rules)
        if 'correlation_rules' in data:
            rules = data.pop('correlation_rules')
            # Map correlation_rules fields to WingConfig fields
            if 'time_window_minutes' in rules:
                data['time_window_minutes'] = rules['time_window_minutes']
            if 'minimum_matches' in rules:
                data['minimum_matches'] = rules['minimum_matches']
            if 'target_application' in rules:
                data['target_application'] = rules['target_application']
            if 'target_file_path' in rules:
                data['target_file_path'] = rules['target_file_path']
            if 'target_event_id' in rules:
                data['target_event_id'] = rules['target_event_id']
            if 'apply_to' in rules:
                data['apply_to'] = rules['apply_to']
            if 'anchor_priority' in rules:
                data['anchor_priority'] = rules['anchor_priority']
            if 'use_weighted_scoring' in rules:
                data['use_weighted_scoring'] = rules['use_weighted_scoring']
        
        # Handle Wing Creator JSON format (nested metadata)
        if 'metadata' in data:
            metadata = data.pop('metadata')
            if 'tags' in metadata:
                data['tags'] = metadata['tags']
            if 'case_types' in metadata:
                data['case_types'] = metadata['case_types']
        
        # Backward compatibility: Apply default scoring config if not present
        if 'scoring' not in data or not data.get('scoring'):
            data['scoring'] = {
                'enabled': True,
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
            print(f"[WingConfig] Applied default scoring configuration")
        
        # Backward compatibility: Enable weighted scoring by default for wings without explicit setting
        if 'use_weighted_scoring' not in data:
            data['use_weighted_scoring'] = True
            print(f"[WingConfig] Enabled weighted scoring by default")
        
        # Load default semantic rules for any default wing — discovered by
        # matching wing_id against the wing_id embedded in every JSON file
        # under the default_wings folder. Previously this only fired for two
        # hardcoded wing IDs; new defaults would have silently received [].
        wing_id = data.get('wing_id', '')
        if wing_id:
            try:
                from ..integration.default_wings_loader import DefaultWingsLoader
                import json as json_module

                default_wings_dir = DefaultWingsLoader.get_default_wings_directory()
                for wing_filename in DefaultWingsLoader.get_default_wing_files():
                    wing_file = default_wings_dir / wing_filename
                    try:
                        with open(wing_file, 'r') as f:
                            default_data = json_module.load(f)
                    except Exception:
                        continue
                    if default_data.get('wing_id') != wing_id:
                        continue
                    if default_data.get('semantic_rules'):
                        data['semantic_rules'] = default_data['semantic_rules']
                        print(f"[WingConfig] Loaded {len(data['semantic_rules'])} default semantic rules for {wing_id}")
                    break
            except Exception as e:
                print(f"[WingConfig] Could not load default semantic rules: {e}")
        
        # Initialize empty semantic_rules if not present (for non-default wings)
        if 'semantic_rules' not in data:
            data['semantic_rules'] = []
        
        # Ensure required fields have defaults
        if 'config_name' not in data and 'wing_name' in data:
            data['config_name'] = data['wing_name'].lower().replace(' ', '_')

        # Rehydrate EYE authorship if present (legacy wings have no
        # eye_authorship key at all — from_dict returns None for that).
        if 'eye_authorship' in data:
            raw = data['eye_authorship']
            data['eye_authorship'] = (
                raw if isinstance(raw, EyeAuthorship) else EyeAuthorship.from_dict(raw)
            )

        # Drop any unexpected top-level keys to keep cls(**data) safe
        # against forward-compatible schema additions in saved files.
        valid = {f.name for f in cls.__dataclass_fields__.values() if f.init}
        data = {k: v for k, v in data.items() if k in valid}

        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'WingConfig':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'WingConfig':
        """Load configuration from JSON file"""
        with open(file_path, 'r') as f:
            return cls.from_json(f.read())
