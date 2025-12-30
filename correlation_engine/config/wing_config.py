"""
Wing Configuration
Stores wing definitions with references to feather configs.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional


@dataclass
class WingFeatherReference:
    """Reference to a feather used in a wing"""
    feather_config_name: str  # Name of the feather config
    feather_database_path: str  # Path to the feather database
    artifact_type: str
    feather_id: str  # ID used in the wing
    table_name: Optional[str] = None  # Optional: Override table name
    artifact_type_override: Optional[str] = None  # Optional: Override artifact type
    
    # Weighted scoring fields
    weight: float = 0.0  # Weight for weighted scoring (0.0 - 1.0)
    tier: int = 0  # Tier number for grouping (1-4)
    tier_name: str = ""  # Human-readable tier name


@dataclass
class WingConfig:
    """Configuration for a wing (correlation rule)"""
    
    # Identification
    config_name: str
    wing_name: str
    wing_id: str
    
    # Wing definition
    description: str
    proves: str  # What this wing proves
    author: str
    
    # Feathers used
    feathers: List[WingFeatherReference] = field(default_factory=list)
    
    # Correlation rules
    time_window_minutes: int = 5
    minimum_matches: int = 1
    
    # Filters (wing-level)
    target_application: str = ""
    target_file_path: str = ""
    target_event_id: str = ""
    apply_to: str = "all"  # "all" or "specific"
    
    # Anchor priority
    anchor_priority: List[str] = field(default_factory=lambda: [
        "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
        "Jumplists", "LNK", "MFT", "USN"
    ])
    
    # Weighted scoring configuration
    use_weighted_scoring: bool = False
    scoring: Dict = field(default_factory=dict)  # Scoring configuration with thresholds
    
    # Metadata
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    version: str = "1.0"
    
    # Tags and categorization
    tags: List[str] = field(default_factory=list)
    case_types: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert WingFeatherReference objects to dicts
        data['feathers'] = [asdict(f) for f in self.feathers]
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
                    print(f"[WingConfig]   Feather {i+1}: {f.get('feather_id', 'unknown')}")
                    
                    # Handle Wing Creator JSON format (uses database_filename)
                    if 'database_filename' in f and 'feather_database_path' not in f:
                        f = f.copy()  # Don't modify original
                        f['feather_database_path'] = f.pop('database_filename')
                    
                    # Handle missing feather_config_name (use feather_id as fallback)
                    if 'feather_config_name' not in f and 'feather_id' in f:
                        f['feather_config_name'] = f['feather_id']
                    
                    # Ensure required fields exist
                    if 'feather_database_path' not in f:
                        print(f"[WingConfig]   WARNING: Feather {i+1} missing feather_database_path!")
                    if 'artifact_type' not in f:
                        print(f"[WingConfig]   WARNING: Feather {i+1} missing artifact_type!")
                    
                    # Filter out unexpected keys
                    valid_keys = {
                        'feather_config_name', 'feather_database_path', 'artifact_type',
                        'feather_id', 'table_name', 'artifact_type_override',
                        'weight', 'tier', 'tier_name'  # Weighted scoring fields
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
        
        # Ensure required fields have defaults
        if 'config_name' not in data and 'wing_name' in data:
            data['config_name'] = data['wing_name'].lower().replace(' ', '_')
        
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
