"""
Pipeline Configuration Manager (Core)

Central coordinator for all configuration management operations.
Provides unified API for GUI and integrates all sub-managers.
"""

from pathlib import Path
from typing import List, Optional

from .session_state import (
    SessionStateManager,
    SessionState,
    PipelineMetadata,
    PipelineBundle,
    InitializationResult,
    DiscoveryResult
)
from .pipeline_config import PipelineConfig
from .feather_config import FeatherConfig
from ..pipeline.discovery_service import ConfigurationDiscoveryService
from ..pipeline.pipeline_loader import PipelineLoader
from ..pipeline.feather_auto_registration import FeatherAutoRegistrationService


class PipelineConfigurationManager:
    """
    Central manager for all pipeline configuration operations.
    Coordinates session state, discovery, loading, and auto-registration.
    """
    
    def __init__(self, case_directory: Path):
        """
        Initialize Pipeline Configuration Manager.
        
        Args:
            case_directory: Path to the case's correlation directory
        """
        self.case_directory = Path(case_directory)
        
        # Initialize sub-managers
        self.session_manager = SessionStateManager(case_directory)
        self.discovery_service = ConfigurationDiscoveryService(case_directory)
        self.pipeline_loader = PipelineLoader(case_directory)
        self.auto_registration_service = FeatherAutoRegistrationService(case_directory)
        
        # Current state
        self._current_pipeline: Optional[PipelineBundle] = None
        self._available_pipelines: List[PipelineMetadata] = []
    
    def initialize(self) -> InitializationResult:
        """
        Initialize manager and optionally auto-load last pipeline.
        
        Returns:
            InitializationResult with initialization status
        """
        result = InitializationResult(success=True)
        
        try:
            # Load session state
            session = self.session_manager.load_session()
            result.session_state = session
            
            # Discover all configurations
            discovery = self.discovery_service.discover_all()
            result.discovery_result = discovery
            self._available_pipelines = discovery.pipelines
            
            # Auto-load last pipeline if exists
            if session and session.last_pipeline_path:
                last_pipeline_path = Path(session.last_pipeline_path)
                
                if last_pipeline_path.exists():
                    try:
                        bundle = self.pipeline_loader.load_pipeline(str(last_pipeline_path))
                        self._current_pipeline = bundle
                        result.auto_loaded = True
                        result.pipeline_bundle = bundle
                    except Exception as e:
                        result.warnings.append(f"Failed to auto-load pipeline: {e}")
                        # Clear invalid session
                        self.session_manager.clear_session()
                else:
                    result.warnings.append(f"Last pipeline not found: {session.last_pipeline_path}")
                    # Clear invalid session
                    self.session_manager.clear_session()
            
        except Exception as e:
            result.success = False
            result.errors.append(f"Initialization failed: {e}")
        
        return result
    
    def load_pipeline(self, pipeline_path: str) -> PipelineBundle:
        """
        Load a pipeline.
        
        Args:
            pipeline_path: Path to pipeline configuration file
        
        Returns:
            Loaded PipelineBundle
        
        Raises:
            FileNotFoundError: If pipeline doesn't exist
            ValueError: If pipeline is invalid
        """
        # Unload current pipeline if exists
        if self._current_pipeline:
            self.pipeline_loader.unload_pipeline(self._current_pipeline)
        
        # Load new pipeline
        bundle = self.pipeline_loader.load_pipeline(pipeline_path)
        self._current_pipeline = bundle
        
        # Update session state
        self.session_manager.set_last_pipeline(
            pipeline_path=pipeline_path,
            pipeline_name=bundle.pipeline_config.pipeline_name
        )
        
        return bundle
    
    def switch_pipeline(self, new_pipeline_path: str) -> PipelineBundle:
        """
        Switch to a different pipeline.
        
        Args:
            new_pipeline_path: Path to new pipeline configuration
        
        Returns:
            Loaded PipelineBundle
        """
        return self.load_pipeline(new_pipeline_path)
    
    def get_available_pipelines(self) -> List[PipelineMetadata]:
        """
        Get list of available pipelines.
        
        Returns:
            List of PipelineMetadata
        """
        return self._available_pipelines
    
    def get_current_pipeline(self) -> Optional[PipelineBundle]:
        """
        Get currently loaded pipeline.
        
        Returns:
            Current PipelineBundle or None
        """
        return self._current_pipeline
    
    def create_pipeline(self, pipeline_config: PipelineConfig) -> str:
        """
        Create a new pipeline.
        
        Args:
            pipeline_config: Pipeline configuration to create
        
        Returns:
            Path to created pipeline file
        """
        # Ensure pipelines directory exists
        pipelines_dir = self.case_directory / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        filename = f"{pipeline_config.config_name}.json"
        pipeline_path = pipelines_dir / filename
        
        # Save pipeline
        pipeline_config.save_to_file(str(pipeline_path))
        
        # Refresh discovery
        self.refresh_configurations()
        
        return str(pipeline_path)
    
    def auto_register_feather(self, database_path: str, artifact_type: str,
                             detection_method: str = "auto",
                             confidence: str = "high") -> FeatherConfig:
        """
        Auto-register a newly created feather.
        
        Args:
            database_path: Path to feather database
            artifact_type: Detected artifact type
            detection_method: Detection method used
            confidence: Detection confidence
        
        Returns:
            Generated FeatherConfig
        """
        feather_config = self.auto_registration_service.register_new_feather(
            database_path=database_path,
            artifact_type=artifact_type,
            detection_method=detection_method,
            confidence=confidence
        )
        
        # Refresh discovery to include new feather
        self.refresh_configurations()
        
        return feather_config
    
    def refresh_configurations(self):
        """
        Refresh configuration discovery.
        """
        discovery = self.discovery_service.discover_all()
        self._available_pipelines = discovery.pipelines
    
    def get_discovery_result(self) -> Optional[DiscoveryResult]:
        """
        Get current discovery result.
        
        Returns:
            DiscoveryResult or None
        """
        return self.discovery_service.get_cached_discovery()
    
    def get_session_state(self) -> Optional[SessionState]:
        """
        Get current session state.
        
        Returns:
            SessionState or None
        """
        return self.session_manager.get_current_session()
    
    def update_session_preferences(self, preferences: dict):
        """
        Update session preferences.
        
        Args:
            preferences: Dictionary of preferences
        """
        self.session_manager.update_preferences(preferences)
    
    def update_window_geometry(self, geometry: dict):
        """
        Update window geometry in session.
        
        Args:
            geometry: Dictionary with x, y, width, height
        """
        self.session_manager.update_window_geometry(geometry)
    
    def update_active_tab(self, tab_index: int):
        """
        Update active tab in session.
        
        Args:
            tab_index: Index of active tab
        """
        self.session_manager.update_active_tab(tab_index)
    
    def get_feather_configs(self) -> List[FeatherConfig]:
        """
        Get all registered feather configurations.
        
        Returns:
            List of FeatherConfig objects
        """
        return self.auto_registration_service.get_feather_configs()
    
    def validate_database(self, database_path: str) -> tuple[bool, Optional[str]]:
        """
        Validate a feather database.
        
        Args:
            database_path: Path to database
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        return self.auto_registration_service.validate_database(database_path)
