"""
Session State and Pipeline Management Data Structures

This module contains all core data structures for the Pipeline Configuration Manager,
including session persistence, configuration discovery, pipeline loading, and status tracking.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

from .pipeline_config import PipelineConfig
from .feather_config import FeatherConfig
from .wing_config import WingConfig


@dataclass
class SessionState:
    """
    Persistent session state for the correlation engine.
    Stores the user's last used pipeline and preferences.
    """
    last_pipeline_path: Optional[str] = None
    last_pipeline_name: Optional[str] = None
    last_opened: str = field(default_factory=lambda: datetime.now().isoformat())
    window_geometry: Optional[Dict[str, int]] = None
    active_tab_index: int = 0
    preferences: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save session state to JSON file"""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SessionState':
        """Create from dictionary"""
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'SessionState':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'SessionState':
        """Load session state from JSON file"""
        with open(file_path, 'r') as f:
            return cls.from_json(f.read())


@dataclass
class PipelineMetadata:
    """
    Metadata about a discovered pipeline configuration.
    Used for displaying available pipelines in the UI.
    """
    config_name: str
    pipeline_name: str
    file_path: Path
    description: str
    feather_count: int
    wing_count: int
    last_modified: str
    is_valid: bool
    validation_errors: List[str] = field(default_factory=list)
    
    # Additional metadata
    case_name: Optional[str] = None
    case_id: Optional[str] = None
    investigator: Optional[str] = None
    last_executed: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        data = asdict(self)
        # Convert Path to string for JSON serialization
        data['file_path'] = str(self.file_path)
        return data


@dataclass
class FeatherMetadata:
    """
    Metadata about a discovered feather configuration.
    """
    config_name: str
    feather_name: str
    file_path: Path
    artifact_type: str
    database_path: str
    total_records: int
    created_date: str
    is_valid: bool
    validation_errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        data = asdict(self)
        data['file_path'] = str(self.file_path)
        return data


@dataclass
class WingsMetadata:
    """
    Metadata about a discovered wings configuration.
    """
    config_name: str
    wing_name: str
    file_path: Path
    wing_id: str
    description: str
    feather_count: int
    time_window_minutes: int
    created_date: str
    is_valid: bool
    validation_errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        data = asdict(self)
        data['file_path'] = str(self.file_path)
        return data


@dataclass
class DiscoveryResult:
    """
    Result of configuration discovery scan.
    Contains all discovered configurations with metadata.
    """
    pipelines: List[PipelineMetadata] = field(default_factory=list)
    feathers: List[FeatherMetadata] = field(default_factory=list)
    wings: List[WingsMetadata] = field(default_factory=list)
    discovery_time: str = field(default_factory=lambda: datetime.now().isoformat())
    total_count: int = 0
    
    def __post_init__(self):
        """Calculate total count after initialization"""
        self.total_count = len(self.pipelines) + len(self.feathers) + len(self.wings)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'pipelines': [p.to_dict() for p in self.pipelines],
            'feathers': [f.to_dict() for f in self.feathers],
            'wings': [w.to_dict() for w in self.wings],
            'discovery_time': self.discovery_time,
            'total_count': self.total_count
        }


@dataclass
class ConnectionStatus:
    """
    Status of a database connection for a feather.
    """
    feather_name: str
    database_path: str
    is_connected: bool
    connection_time: Optional[str] = None
    error_message: Optional[str] = None
    record_count: Optional[int] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class ValidationResult:
    """
    Result of configuration validation.
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    config_type: str = ""
    config_path: Optional[str] = None
    
    def add_error(self, error: str):
        """Add an error message"""
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, warning: str):
        """Add a warning message"""
        self.warnings.append(warning)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class PartialLoadInfo:
    """
    Information about a partial pipeline load.
    """
    feathers_loaded: List[str] = field(default_factory=list)
    feathers_failed: List[str] = field(default_factory=list)
    wings_loaded: List[str] = field(default_factory=list)
    wings_failed: List[str] = field(default_factory=list)
    failure_reasons: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class LoadStatus:
    """
    Status of a pipeline load operation.
    """
    is_complete: bool
    feathers_loaded: int
    feathers_total: int
    wings_loaded: int
    wings_total: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    partial_load_info: Optional[PartialLoadInfo] = None
    
    def is_partial_load(self) -> bool:
        """Check if this is a partial load"""
        return (self.feathers_loaded < self.feathers_total or 
                self.wings_loaded < self.wings_total)
    
    def get_summary(self) -> str:
        """Get a human-readable summary"""
        if self.is_complete:
            return f"Loaded {self.feathers_loaded} feathers and {self.wings_loaded} wings"
        else:
            return (f"Partial load: {self.feathers_loaded}/{self.feathers_total} feathers, "
                   f"{self.wings_loaded}/{self.wings_total} wings")
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        data = asdict(self)
        if self.partial_load_info:
            data['partial_load_info'] = self.partial_load_info.to_dict()
        return data


@dataclass
class PipelineBundle:
    """
    Complete bundle of a loaded pipeline with all dependencies.
    This is the main data structure returned when a pipeline is loaded.
    """
    pipeline_config: PipelineConfig
    feather_configs: List[FeatherConfig] = field(default_factory=list)
    wing_configs: List[WingConfig] = field(default_factory=list)
    database_connections: Dict[str, Any] = field(default_factory=dict)
    resolved_paths: Dict[str, str] = field(default_factory=dict)
    load_time: str = field(default_factory=lambda: datetime.now().isoformat())
    load_status: Optional[LoadStatus] = None
    connection_statuses: Dict[str, ConnectionStatus] = field(default_factory=dict)
    
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
    
    def get_connection(self, feather_name: str) -> Optional[Any]:
        """Get database connection for a feather"""
        return self.database_connections.get(feather_name)
    
    def is_fully_loaded(self) -> bool:
        """Check if pipeline is fully loaded"""
        return self.load_status and self.load_status.is_complete
    
    def to_dict(self) -> dict:
        """Convert to dictionary (excluding connections)"""
        return {
            'pipeline_config': self.pipeline_config.to_dict(),
            'feather_configs': [f.to_dict() for f in self.feather_configs],
            'wing_configs': [w.to_dict() for w in self.wing_configs],
            'resolved_paths': self.resolved_paths,
            'load_time': self.load_time,
            'load_status': self.load_status.to_dict() if self.load_status else None,
            'connection_statuses': {k: v.to_dict() for k, v in self.connection_statuses.items()}
        }


@dataclass
class InitializationResult:
    """
    Result of Pipeline Configuration Manager initialization.
    """
    success: bool
    discovery_result: Optional[DiscoveryResult] = None
    auto_loaded: bool = False
    pipeline_bundle: Optional[PipelineBundle] = None
    session_state: Optional[SessionState] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'success': self.success,
            'discovery_result': self.discovery_result.to_dict() if self.discovery_result else None,
            'auto_loaded': self.auto_loaded,
            'pipeline_bundle': self.pipeline_bundle.to_dict() if self.pipeline_bundle else None,
            'session_state': self.session_state.to_dict() if self.session_state else None,
            'errors': self.errors,
            'warnings': self.warnings
        }


@dataclass
class ErrorResponse:
    """
    Standardized error response for error handling.
    """
    severity: str  # "error", "warning", "info"
    message: str
    recovery_action: str
    user_message: str
    technical_details: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)



class SessionStateManager:
    """
    Manages persistent session state for the correlation engine.
    Handles loading, saving, and updating session information.
    """
    
    def __init__(self, case_directory: Path):
        """
        Initialize SessionStateManager with case directory.
        
        Args:
            case_directory: Path to the case's correlation directory
        """
        self.case_directory = Path(case_directory)
        self.session_file = self.case_directory / "session.json"
        self._current_session: Optional[SessionState] = None
    
    def load_session(self) -> Optional[SessionState]:
        """
        Load session state from file.
        
        Returns:
            SessionState if file exists and is valid, None otherwise
        """
        if not self.session_file.exists():
            return None
        
        try:
            session = SessionState.load_from_file(str(self.session_file))
            self._current_session = session
            return session
        except json.JSONDecodeError as e:
            # Handle corrupted session file
            print(f"Warning: Corrupted session file: {e}")
            self._backup_corrupted_session()
            return None
        except Exception as e:
            print(f"Error loading session: {e}")
            return None
    
    def save_session(self, state: SessionState):
        """
        Save session state to file.
        
        Args:
            state: SessionState to save
        """
        try:
            # Ensure directory exists
            self.case_directory.mkdir(parents=True, exist_ok=True)
            
            # Update last_opened timestamp
            state.last_opened = datetime.now().isoformat()
            
            # Save to file
            state.save_to_file(str(self.session_file))
            self._current_session = state
            
        except Exception as e:
            print(f"Error saving session: {e}")
            raise
    
    def get_last_pipeline(self) -> Optional[str]:
        """
        Get path to last used pipeline.
        
        Returns:
            Path to last pipeline, or None if no session exists
        """
        if self._current_session is None:
            self._current_session = self.load_session()
        
        if self._current_session:
            return self._current_session.last_pipeline_path
        return None
    
    def set_last_pipeline(self, pipeline_path: str, pipeline_name: str = ""):
        """
        Set last used pipeline and save session.
        
        Args:
            pipeline_path: Path to the pipeline configuration file
            pipeline_name: Name of the pipeline (optional)
        """
        if self._current_session is None:
            self._current_session = SessionState()
        
        self._current_session.last_pipeline_path = pipeline_path
        self._current_session.last_pipeline_name = pipeline_name
        self.save_session(self._current_session)
    
    def clear_session(self):
        """
        Clear session state and delete session file.
        """
        self._current_session = None
        if self.session_file.exists():
            try:
                self.session_file.unlink()
            except Exception as e:
                print(f"Error deleting session file: {e}")
    
    def update_preferences(self, preferences: Dict[str, Any]):
        """
        Update session preferences.
        
        Args:
            preferences: Dictionary of preference key-value pairs
        """
        if self._current_session is None:
            self._current_session = SessionState()
        
        self._current_session.preferences.update(preferences)
        self.save_session(self._current_session)
    
    def update_window_geometry(self, geometry: Dict[str, int]):
        """
        Update window geometry in session.
        
        Args:
            geometry: Dictionary with x, y, width, height
        """
        if self._current_session is None:
            self._current_session = SessionState()
        
        self._current_session.window_geometry = geometry
        self.save_session(self._current_session)
    
    def update_active_tab(self, tab_index: int):
        """
        Update active tab index in session.
        
        Args:
            tab_index: Index of the active tab
        """
        if self._current_session is None:
            self._current_session = SessionState()
        
        self._current_session.active_tab_index = tab_index
        self.save_session(self._current_session)
    
    def get_current_session(self) -> Optional[SessionState]:
        """
        Get current session state.
        
        Returns:
            Current SessionState or None
        """
        if self._current_session is None:
            self._current_session = self.load_session()
        return self._current_session
    
    def _backup_corrupted_session(self):
        """
        Backup corrupted session file for debugging.
        """
        if self.session_file.exists():
            backup_path = self.session_file.with_suffix('.json.corrupted')
            try:
                import shutil
                shutil.copy(self.session_file, backup_path)
                print(f"Backed up corrupted session to: {backup_path}")
            except Exception as e:
                print(f"Failed to backup corrupted session: {e}")
