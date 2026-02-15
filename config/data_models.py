"""Data models for case configuration management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional


@dataclass
class CaseMetadata:
    """Metadata for a forensic investigation case."""
    case_id: str
    name: str
    path: str
    description: str
    created_date: datetime
    last_accessed: datetime
    last_opened: datetime
    is_favorite: bool = False
    tags: List[str] = field(default_factory=list)
    status: str = "active"  # active, archived, unavailable
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'case_id': self.case_id,
            'name': self.name,
            'path': self.path,
            'description': self.description,
            'created_date': self.created_date.isoformat() if isinstance(self.created_date, datetime) else self.created_date,
            'last_accessed': self.last_accessed.isoformat() if isinstance(self.last_accessed, datetime) else self.last_accessed,
            'last_opened': self.last_opened.isoformat() if isinstance(self.last_opened, datetime) else self.last_opened,
            'is_favorite': self.is_favorite,
            'tags': self.tags,
            'status': self.status
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CaseMetadata':
        """Create from dictionary loaded from JSON."""
        # Parse datetime strings
        created_date = data.get('created_date')
        if isinstance(created_date, str):
            created_date = datetime.fromisoformat(created_date)
        
        last_accessed = data.get('last_accessed')
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
        
        last_opened = data.get('last_opened', last_accessed)
        if isinstance(last_opened, str):
            last_opened = datetime.fromisoformat(last_opened)
        
        return cls(
            case_id=data.get('case_id', ''),
            name=data.get('name', ''),
            path=data.get('path', ''),
            description=data.get('description', ''),
            created_date=created_date,
            last_accessed=last_accessed,
            last_opened=last_opened,
            is_favorite=data.get('is_favorite', False),
            tags=data.get('tags', []),
            status=data.get('status', 'active')
        )


@dataclass
class GlobalConfig:
    """Global application configuration."""
    version: str
    default_case_directory: str
    recent_cases_display_count: int
    max_history_size: int
    theme: str
    last_updated: datetime
    identity_semantic_phase_enabled: bool = True  # Enable identity-level semantic mapping by default
    wings_semantic_mapping_enabled: bool = True  # Enable semantic mapping for Wings by default
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'version': self.version,
            'default_case_directory': self.default_case_directory,
            'recent_cases_display_count': self.recent_cases_display_count,
            'max_history_size': self.max_history_size,
            'theme': self.theme,
            'last_updated': self.last_updated.isoformat() if isinstance(self.last_updated, datetime) else self.last_updated,
            'identity_semantic_phase_enabled': self.identity_semantic_phase_enabled,
            'wings_semantic_mapping_enabled': self.wings_semantic_mapping_enabled
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GlobalConfig':
        """Create from dictionary loaded from JSON."""
        last_updated = data.get('last_updated')
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        
        return cls(
            version=data.get('version', '1.0'),
            default_case_directory=data.get('default_case_directory', 'C:/Cases'),
            recent_cases_display_count=data.get('recent_cases_display_count', 10),
            max_history_size=data.get('max_history_size', 200),
            theme=data.get('theme', 'cyberpunk_dark'),
            last_updated=last_updated,
            identity_semantic_phase_enabled=data.get('identity_semantic_phase_enabled', True),
            wings_semantic_mapping_enabled=data.get('wings_semantic_mapping_enabled', True)
        )
    
    @classmethod
    def default(cls) -> 'GlobalConfig':
        """Create default global configuration."""
        return cls(
            version='1.0',
            default_case_directory='C:/Cases',
            recent_cases_display_count=10,
            max_history_size=200,
            theme='cyberpunk_dark',
            last_updated=datetime.now(),
            identity_semantic_phase_enabled=True,
            wings_semantic_mapping_enabled=True
        )


@dataclass
class CaseConfig:
    """Configuration for a specific case."""
    version: str
    case_id: str
    name: str
    description: str
    created_date: datetime
    last_accessed: datetime
    case_paths: Dict[str, Any]
    case_settings: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'version': self.version,
            'case_id': self.case_id,
            'name': self.name,
            'description': self.description,
            'created_date': self.created_date.isoformat() if isinstance(self.created_date, datetime) else self.created_date,
            'last_accessed': self.last_accessed.isoformat() if isinstance(self.last_accessed, datetime) else self.last_accessed,
            'case_paths': self.case_paths,
            'case_settings': self.case_settings
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CaseConfig':
        """Create from dictionary loaded from JSON."""
        created_date = data.get('created_date')
        if isinstance(created_date, str):
            created_date = datetime.fromisoformat(created_date)
        
        last_accessed = data.get('last_accessed')
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
        
        return cls(
            version=data.get('version', '1.0'),
            case_id=data.get('case_id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            created_date=created_date,
            last_accessed=last_accessed,
            case_paths=data.get('case_paths', {}),
            case_settings=data.get('case_settings', {})
        )
