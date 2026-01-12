"""
Configuration for identifier extraction and correlation.

This module defines the configuration schema for the Crow-Eye Correlation Engine's
identifier extraction features, including extraction strategies, anchor time windows,
and timestamp parsing options.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path


@dataclass
class IdentifierExtractionConfig:
    """Configuration for identifier extraction strategy."""
    extract_from_names: bool = True
    extract_from_paths: bool = True
    name_columns: List[str] = field(default_factory=list)  # Optional override
    path_columns: List[str] = field(default_factory=list)  # Optional override


@dataclass
class TimestampParsingConfig:
    """Configuration for timestamp parsing."""
    custom_formats: List[str] = field(default_factory=list)
    default_timezone: str = "UTC"
    fallback_to_current_time: bool = False


@dataclass
class WingsConfig:
    """
    Wings configuration for correlation engine.
    
    Defines how the engine should process and correlate Feather data.
    """
    identifier_extraction: IdentifierExtractionConfig = field(
        default_factory=IdentifierExtractionConfig
    )
    anchor_time_window_minutes: int = 180
    timestamp_parsing: TimestampParsingConfig = field(
        default_factory=TimestampParsingConfig
    )
    correlation_database: str = "correlation.db"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WingsConfig':
        """Create WingsConfig from dictionary."""
        # Parse identifier_extraction
        id_extract_data = data.get('identifier_extraction', {})
        id_extract = IdentifierExtractionConfig(
            extract_from_names=id_extract_data.get('extract_from_names', True),
            extract_from_paths=id_extract_data.get('extract_from_paths', True),
            name_columns=id_extract_data.get('name_columns', []),
            path_columns=id_extract_data.get('path_columns', [])
        )
        
        # Parse timestamp_parsing
        ts_parse_data = data.get('timestamp_parsing', {})
        ts_parse = TimestampParsingConfig(
            custom_formats=ts_parse_data.get('custom_formats', []),
            default_timezone=ts_parse_data.get('default_timezone', 'UTC'),
            fallback_to_current_time=ts_parse_data.get('fallback_to_current_time', False)
        )
        
        return cls(
            identifier_extraction=id_extract,
            anchor_time_window_minutes=data.get('anchor_time_window_minutes', 180),
            timestamp_parsing=ts_parse,
            correlation_database=data.get('correlation_database', 'correlation.db')
        )
    
    @classmethod
    def load_from_file(cls, config_path: str) -> 'WingsConfig':
        """Load configuration from JSON file."""
        path = Path(config_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(path, 'r') as f:
            data = json.load(f)
        
        return cls.from_dict(data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'identifier_extraction': asdict(self.identifier_extraction),
            'anchor_time_window_minutes': self.anchor_time_window_minutes,
            'timestamp_parsing': asdict(self.timestamp_parsing),
            'correlation_database': self.correlation_database
        }
    
    def save_to_file(self, config_path: str):
        """Save configuration to JSON file."""
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    def get_extraction_strategy(self) -> Dict[str, bool]:
        """Get extraction strategy as dictionary."""
        return {
            'extract_from_names': self.identifier_extraction.extract_from_names,
            'extract_from_paths': self.identifier_extraction.extract_from_paths
        }
    
    def get_anchor_time_window(self) -> int:
        """Get anchor time window in minutes."""
        return self.anchor_time_window_minutes
    
    def has_manual_name_columns(self) -> bool:
        """Check if manual name columns are specified."""
        return len(self.identifier_extraction.name_columns) > 0
    
    def has_manual_path_columns(self) -> bool:
        """Check if manual path columns are specified."""
        return len(self.identifier_extraction.path_columns) > 0


# Example configuration
def create_default_config() -> WingsConfig:
    """Create a default Wings configuration."""
    return WingsConfig(
        identifier_extraction=IdentifierExtractionConfig(
            extract_from_names=True,
            extract_from_paths=True,
            name_columns=[],
            path_columns=[]
        ),
        anchor_time_window_minutes=180,  # Default: 3 hours for better correlation accuracy
        timestamp_parsing=TimestampParsingConfig(
            custom_formats=[],
            default_timezone="UTC",
            fallback_to_current_time=False
        ),
        correlation_database="correlation.db"
    )


def create_example_config_file(output_path: str = "wings_config_example.json"):
    """Create an example configuration file."""
    config = create_default_config()
    
    # Add some example custom formats
    config.timestamp_parsing.custom_formats = [
        "%d-%b-%Y %H:%M:%S",  # Example: "01-Jan-2024 10:00:00"
        "%Y%m%d%H%M%S"        # Example: "20240101100000"
    ]
    
    config.save_to_file(output_path)
    print(f"Example configuration saved to: {output_path}")


if __name__ == "__main__":
    # Create example config when run directly
    create_example_config_file()
