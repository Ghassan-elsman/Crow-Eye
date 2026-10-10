"""Data models for case configuration management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional


def default_cases_dir() -> str:
    """Where new cases go until the analyst picks somewhere: C:/Cases on
    Windows, ~/Cases elsewhere (there is no C: on Linux)."""
    import os
    if os.name == 'nt':
        return 'C:/Cases'
    return os.path.join(os.path.expanduser('~'), 'Cases')


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
    cascade_tree_expansion_enabled: bool = True  # Enable cascade expansion in tree views by default
    # May a parse CREATE a shadow copy to read a locked hive, or only use
    # ones that already exist? On by default: a hive that cannot be read is
    # evidence lost. Off, the parser still uses existing snapshots and falls
    # back to raw disk and then to an NtSaveKeyEx export.
    parser_allow_snapshot_creation: bool = True
    # Parse automatically once a collection finishes: the Offline Importer's
    # COLLECT, the main window's Parse Offline Artifacts scan, and the default
    # of Image Parsing's "Parse automatically after extraction". Off, every one
    # of them stops at a ready Parse button.
    auto_parse_after_collection: bool = True
    # Settings -> Semantic Mappings -> "Semantic mapping engine": how the
    # semantic phase runs (read by sql_semantic_mapper through
    # read_global_setting). Worker threads for the rules; the share of
    # matches (percent) above which the FTS5 prefilter is skipped because it
    # cannot filter; candidates matched per chunk; and the detailed per-rule
    # debug log in <case>/logs.
    semantic_worker_count: int = 4
    semantic_fts_skip_coverage: int = 50
    semantic_candidate_chunk_size: int = 20000
    semantic_debug_log: bool = False

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
            'wings_semantic_mapping_enabled': self.wings_semantic_mapping_enabled,
            'cascade_tree_expansion_enabled': self.cascade_tree_expansion_enabled,
            'parser_allow_snapshot_creation': self.parser_allow_snapshot_creation,
            'auto_parse_after_collection': self.auto_parse_after_collection,
            'semantic_worker_count': self.semantic_worker_count,
            'semantic_fts_skip_coverage': self.semantic_fts_skip_coverage,
            'semantic_candidate_chunk_size': self.semantic_candidate_chunk_size,
            'semantic_debug_log': self.semantic_debug_log
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GlobalConfig':
        """Create from dictionary loaded from JSON."""
        last_updated = data.get('last_updated')
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        
        return cls(
            version=data.get('version', '1.0'),
            default_case_directory=data.get('default_case_directory', default_cases_dir()),
            recent_cases_display_count=data.get('recent_cases_display_count', 10),
            max_history_size=data.get('max_history_size', 200),
            theme=data.get('theme', 'cyberpunk_dark'),
            last_updated=last_updated,
            identity_semantic_phase_enabled=data.get('identity_semantic_phase_enabled', True),
            wings_semantic_mapping_enabled=data.get('wings_semantic_mapping_enabled', True),
            cascade_tree_expansion_enabled=data.get('cascade_tree_expansion_enabled', True),
            parser_allow_snapshot_creation=data.get('parser_allow_snapshot_creation', True),
            auto_parse_after_collection=data.get('auto_parse_after_collection', True),
            semantic_worker_count=data.get('semantic_worker_count', 4),
            semantic_fts_skip_coverage=data.get('semantic_fts_skip_coverage', 50),
            semantic_candidate_chunk_size=data.get('semantic_candidate_chunk_size', 20000),
            semantic_debug_log=data.get('semantic_debug_log', False)
        )
    
    @classmethod
    def default(cls) -> 'GlobalConfig':
        """Create default global configuration."""
        return cls(
            version='1.0',
            default_case_directory=default_cases_dir(),
            recent_cases_display_count=10,
            max_history_size=200,
            theme='cyberpunk_dark',
            last_updated=datetime.now(),
            identity_semantic_phase_enabled=True,
            wings_semantic_mapping_enabled=True,
            cascade_tree_expansion_enabled=True,
            parser_allow_snapshot_creation=True,
            auto_parse_after_collection=True
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
