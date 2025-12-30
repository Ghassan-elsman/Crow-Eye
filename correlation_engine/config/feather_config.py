"""
Feather Configuration
Stores metadata about how a feather was created from source data.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional


@dataclass
class FeatherConfig:
    """Configuration for creating a feather database"""
    
    # Identification
    config_name: str
    feather_name: str
    artifact_type: str
    
    # Source information
    source_database: str  # Path to source database
    source_table: str  # Table name in source database
    
    # Column mapping
    selected_columns: List[str]  # Columns selected from source
    column_mapping: Dict[str, str]  # Original column -> Feather column mapping
    
    # Transformation settings
    timestamp_column: str  # Which column contains timestamps
    timestamp_format: str  # Format of timestamps
    
    # Output
    output_database: str  # Path where feather database was saved
    
    # Optional fields
    application_column: Optional[str] = None  # Column containing app/file names
    path_column: Optional[str] = None  # Column containing file paths
    
    # Metadata
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = ""
    description: str = ""
    notes: str = ""
    
    # Statistics
    total_records: int = 0
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save configuration to JSON file"""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: dict) -> 'FeatherConfig':
        """Create from dictionary"""
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'FeatherConfig':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'FeatherConfig':
        """Load configuration from JSON file"""
        with open(file_path, 'r') as f:
            return cls.from_json(f.read())
