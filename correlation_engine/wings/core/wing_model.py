"""
Wing Data Models
Defines the structure of Wings and their components.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional


@dataclass
class FeatherSpec:
    """Specification for a feather in a wing"""
    feather_id: str
    database_filename: str
    artifact_type: str
    detection_confidence: str  # 'high', 'medium', 'low'
    manually_overridden: bool
    detection_method: str = "filename"  # 'metadata', 'table_name', 'filename', 'unknown'
    required_fields: List[str] = field(default_factory=list)
    original_detection: Optional[str] = None
    feather_config_name: Optional[str] = None  # Preserve original config name for path resolution
    
    # Weighted scoring fields
    weight: float = 0.0
    tier: int = 0
    tier_name: str = ""
    
    def is_metadata_based(self) -> bool:
        """Check if artifact type came from metadata table"""
        return self.detection_method == "metadata"
    
    def get_detection_display(self) -> str:
        """Get user-friendly detection description"""
        if self.manually_overridden:
            return "Manually selected"
        
        method_text = {
            "metadata": "from metadata table",
            "table_name": "from table name",
            "filename": "from filename",
            "unknown": "unknown source"
        }.get(self.detection_method, self.detection_method)
        
        return f"{self.artifact_type} ({self.detection_confidence} confidence - {method_text})"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'FeatherSpec':
        """Create from dictionary"""
        print(f"[FeatherSpec.from_dict] Input data keys: {list(data.keys())}")
        
        # Handle old format with filters field
        if 'filters' in data:
            data = {k: v for k, v in data.items() if k != 'filters'}
        
        # Handle old format without detection_method
        if 'detection_method' not in data:
            data['detection_method'] = "filename"
        
        # Handle WingConfig format with different field names
        if 'feather_config_name' in data:
            # Preserve the original config name for path resolution
            if 'feather_id' not in data:
                data['feather_id'] = data['feather_config_name']
            # Keep feather_config_name in the data
        
        # Handle database_path or feather_database_path -> database_filename
        if 'feather_database_path' in data and 'database_filename' not in data:
            # Keep the full path for proper resolution later
            data['database_filename'] = data['feather_database_path']
        elif 'database_path' in data and 'database_filename' not in data:
            # Handle database_path field (from WingConfig)
            data['database_filename'] = data['database_path']
        
        # Ensure required fields have defaults
        if 'detection_confidence' not in data:
            data['detection_confidence'] = "high"
        if 'manually_overridden' not in data:
            data['manually_overridden'] = True  # Assume manually configured if from Wing JSON
        if 'artifact_type' not in data:
            data['artifact_type'] = "Unknown"
        if 'database_filename' not in data:
            data['database_filename'] = ""
        if 'feather_id' not in data:
            data['feather_id'] = "unknown_feather"
        
        # Filter out fields that aren't in the dataclass
        valid_fields = {
            'feather_id', 'database_filename', 'artifact_type', 'detection_confidence',
            'manually_overridden', 'detection_method', 'required_fields', 
            'original_detection', 'feather_config_name',
            'weight', 'tier', 'tier_name'  # Weighted scoring fields
        }
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        print(f"[FeatherSpec.from_dict] Creating FeatherSpec with: {filtered_data}")
        
        return cls(**filtered_data)


def _get_wing_anchor_priority_from_registry() -> List[str]:
    """Get anchor priority list from artifact type registry"""
    try:
        from ...config.artifact_type_registry import get_registry
        return get_registry().get_anchor_priority_list()
    except Exception:
        # Fallback to hard-coded defaults if registry fails
        return [
            "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
            "Jumplists", "LNK", "MFT", "USN"
        ]


@dataclass
class CorrelationRules:
    """Correlation rules for the wing"""
    time_window_minutes: int = 180  # Default: 3 hours for better correlation accuracy
    minimum_matches: int = 1
    show_partial_matches: bool = True
    max_time_range_years: int = 20  # Maximum time span to prevent false timestamps from expanding range
    
    # Wing-level filters (apply to ALL feathers)
    target_application: str = ""  # e.g., "chrome.exe", "notepad.exe", or "*" for all
    target_file_path: str = ""  # Optional: specific path filter
    target_event_id: str = ""  # For Logs artifacts: e.g., "4688", "4624,4625", or "" for all
    apply_to: str = "all"  # "all" or "specific"
    
    # Anchor configuration
    anchor_feather_override: str = ""  # Optional: manually specify anchor feather_id
    anchor_priority: List[str] = field(default_factory=lambda: _get_wing_anchor_priority_from_registry())
    timestamp_fields: Dict[str, str] = field(default_factory=lambda: {
        "Prefetch": "last_run_time",
        "SRUM": "timestamp",
        "AmCache": "last_modified",
        "Logs": "event_time",
        "Jumplists": "access_time",
        "LNK": "creation_time",
        "ShimCache": "last_modified",
        "MFT": "modification_time",
        "USN": "timestamp"
    })
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CorrelationRules':
        """Create from dictionary"""
        # Filter to only valid fields to avoid errors from extra keys
        valid_fields = {
            'time_window_minutes', 'minimum_matches', 'show_partial_matches',
            'max_time_range_years', 'target_application', 'target_file_path',
            'target_event_id', 'apply_to', 'anchor_feather_override',
            'anchor_priority', 'timestamp_fields'
        }
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class WingMetadata:
    """Metadata for the wing"""
    tags: List[str] = field(default_factory=list)
    case_types: List[str] = field(default_factory=list)
    confidence_level: str = "medium"
    tested_on: List[str] = field(default_factory=list)
    notes: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WingMetadata':
        """Create from dictionary"""
        # Filter to only valid fields to avoid errors from extra keys
        valid_fields = {'tags', 'case_types', 'confidence_level', 'tested_on', 'notes'}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class Wing:
    """Complete wing configuration"""
    wing_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    wing_name: str = ""
    version: str = "1.0"
    author: str = ""
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""
    proves: str = ""
    feathers: List[FeatherSpec] = field(default_factory=list)
    correlation_rules: CorrelationRules = field(default_factory=CorrelationRules)
    metadata: WingMetadata = field(default_factory=WingMetadata)
    semantic_mappings: List[Dict[str, str]] = field(default_factory=list)
    # Advanced semantic rules with AND/OR logic and wildcard support
    semantic_rules: List[Dict[str, Any]] = field(default_factory=list)
    # Weighted scoring configuration - ENABLED BY DEFAULT
    use_weighted_scoring: bool = True
    scoring: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'score_interpretation': {
            'confirmed': {'min': 0.70, 'label': 'Confirmed Evidence'},
            'probable': {'min': 0.40, 'label': 'Probable Match'},
            'weak': {'min': 0.20, 'label': 'Weak / Partial Evidence'},
            'insufficient': {'min': 0.0, 'label': 'Insufficient Evidence'}
        }
    })
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'wing_id': self.wing_id,
            'wing_name': self.wing_name,
            'version': self.version,
            'author': self.author,
            'created_date': self.created_date,
            'description': self.description,
            'proves': self.proves,
            'feathers': [f.to_dict() for f in self.feathers],
            'correlation_rules': self.correlation_rules.to_dict(),
            'metadata': self.metadata.to_dict(),
            'semantic_mappings': self.semantic_mappings,
            'semantic_rules': self.semantic_rules,
            'use_weighted_scoring': self.use_weighted_scoring,
            'scoring': self.scoring
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save wing to JSON file"""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Wing':
        """Create from dictionary"""
        print(f"[Wing.from_dict] Loading wing: {data.get('wing_name', 'Unknown')}")
        print(f"[Wing.from_dict] Keys in data: {list(data.keys())}")
        print(f"[Wing.from_dict] Number of feathers in data: {len(data.get('feathers', []))}")
        
        # Handle WingConfig format (default wings) vs Wing format
        # WingConfig has correlation settings at top level, Wing has them nested
        
        # Check if this is WingConfig format (has time_window_minutes at top level)
        is_wing_config_format = 'time_window_minutes' in data and 'correlation_rules' not in data
        print(f"[Wing.from_dict] Is WingConfig format: {is_wing_config_format}")
        
        if is_wing_config_format:
            # Convert WingConfig format to Wing format
            correlation_rules_data = {
                'time_window_minutes': data.get('time_window_minutes', 5),
                'minimum_matches': data.get('minimum_matches', 1),
                'target_application': data.get('target_application', ''),
                'target_file_path': data.get('target_file_path', ''),
                'target_event_id': data.get('target_event_id', ''),
                'apply_to': data.get('apply_to', 'all'),
                'anchor_priority': data.get('anchor_priority', [])
            }
            correlation_rules = CorrelationRules.from_dict(correlation_rules_data)
        else:
            correlation_rules = CorrelationRules.from_dict(data.get('correlation_rules', {}))
        
        feathers_data = data.get('feathers', [])
        print(f"[Wing.from_dict] Creating {len(feathers_data)} feathers...")
        feathers = []
        for i, f in enumerate(feathers_data):
            print(f"[Wing.from_dict]   Feather {i+1}: {f.get('feather_id', 'unknown')}")
            feather_spec = FeatherSpec.from_dict(f)
            feathers.append(feather_spec)
            print(f"[Wing.from_dict]   Created: {feather_spec.feather_id} - {feather_spec.database_filename}")
        
        print(f"[Wing.from_dict] Total feathers created: {len(feathers)}")
        
        metadata = WingMetadata.from_dict(data.get('metadata', {}))
        semantic_mappings = data.get('semantic_mappings', [])
        
        # Load advanced semantic rules
        semantic_rules = data.get('semantic_rules', [])
        print(f"[Wing.from_dict] Semantic rules in data: {len(semantic_rules)}")
        if semantic_rules:
            print(f"[Wing.from_dict] First rule: {semantic_rules[0].get('name', 'unknown')}")
        
        # Load weighted scoring configuration
        use_weighted_scoring = data.get('use_weighted_scoring', True)
        print(f"[Wing.from_dict] use_weighted_scoring: {use_weighted_scoring}")
        scoring = data.get('scoring', {
            'enabled': True,
            'score_interpretation': {
                'confirmed': {'min': 0.70, 'label': 'Confirmed Evidence'},
                'probable': {'min': 0.40, 'label': 'Probable Match'},
                'weak': {'min': 0.20, 'label': 'Weak / Partial Evidence'},
                'insufficient': {'min': 0.0, 'label': 'Insufficient Evidence'}
            }
        })
        print(f"[Wing.from_dict] scoring keys: {list(scoring.keys()) if scoring else 'None'}")
        
        wing = cls(
            wing_id=data.get('wing_id', str(uuid.uuid4())),
            wing_name=data.get('wing_name', ''),
            version=data.get('version', '1.0'),
            author=data.get('author', ''),
            created_date=data.get('created_date', datetime.now().isoformat()),
            description=data.get('description', ''),
            proves=data.get('proves', ''),
            feathers=feathers,
            correlation_rules=correlation_rules,
            metadata=metadata,
            semantic_mappings=semantic_mappings,
            semantic_rules=semantic_rules,
            use_weighted_scoring=use_weighted_scoring,
            scoring=scoring
        )
        
        print(f"[Wing.from_dict] Created wing '{wing.wing_name}' with {len(wing.feathers)} feathers")
        print(f"[Wing.from_dict] Loaded {len(semantic_rules)} semantic rules")
        print(f"[Wing.from_dict] Weighted scoring: {use_weighted_scoring}")
        return wing
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Wing':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'Wing':
        """Load wing from JSON file"""
        with open(file_path, 'r') as f:
            return cls.from_json(f.read())
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate wing configuration.
        Returns: (is_valid, list_of_errors)
        """
        errors = []
        
        # Check required fields
        if not self.wing_name:
            errors.append("Wing name is required")
        
        if not self.wing_id:
            errors.append("Wing ID is required")
        
        # Check feathers
        if len(self.feathers) < 2:
            errors.append("Wing must have at least 2 feathers")
        
        for i, feather in enumerate(self.feathers):
            if feather.artifact_type == 'Unknown':
                errors.append(f"Feather {i+1}: Artifact type must be selected")
            
            if not feather.database_filename:
                errors.append(f"Feather {i+1}: Database filename is required")
        
        # Check correlation rules
        if self.correlation_rules.time_window_minutes <= 0:
            errors.append("Time window must be greater than 0")
        
        if self.correlation_rules.minimum_matches < 2:
            errors.append("Minimum matches must be at least 2")
        
        return (len(errors) == 0, errors)
