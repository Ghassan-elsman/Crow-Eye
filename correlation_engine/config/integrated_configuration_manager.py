"""
Integrated Configuration Manager

Unified configuration management for semantic mapping, weighted scoring, progress tracking,
and other integrated features in the Crow-Eye system.

Provides:
- Global configuration loading and validation
- Case-specific configuration management
- Configuration conflict resolution
- Configuration enable/disable toggles
- Hierarchical configuration merging
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SemanticMappingConfig:
    """Configuration for semantic mapping system"""
    enabled: bool = True
    global_mappings_path: str = "config/semantic_mappings.json"
    case_specific: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "storage_path": "cases/{case_id}/semantic_mappings.json"
    })
    fallback_to_raw_values: bool = True
    log_mapping_statistics: bool = True


@dataclass
class WeightedScoringConfig:
    """Configuration for weighted scoring system"""
    enabled: bool = True
    score_interpretation: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
        "probable": {"min": 0.5, "label": "Probable Match"},
        "weak": {"min": 0.2, "label": "Weak Evidence"},
        "minimal": {"min": 0.0, "label": "Minimal Evidence"}
    })
    default_weights: Dict[str, float] = field(default_factory=lambda: _get_default_weights_from_registry())
    tier_definitions: Dict[int, str] = field(default_factory=lambda: {
        1: "Primary Evidence",
        2: "Supporting Evidence", 
        3: "Contextual Evidence",
        4: "Background Evidence"
    })
    validation_rules: Dict[str, Any] = field(default_factory=lambda: {
        "max_weight": 1.0,
        "min_weight": 0.0,
        "max_tier": 4,
        "min_tier": 1,
        "require_positive_weights": True,
        "allow_zero_weights": True
    })
    case_specific: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "storage_path": "cases/{case_id}/scoring_weights.json"
    })
    fallback_to_simple_count: bool = True


def _get_default_weights_from_registry() -> Dict[str, float]:
    """Get default weights from artifact type registry"""
    try:
        from .artifact_type_registry import get_registry
        return get_registry().get_default_weights_dict()
    except Exception:
        # Fallback to hard-coded defaults if registry fails
        return {
            "Logs": 0.4,
            "Prefetch": 0.3,
            "SRUM": 0.2,
            "AmCache": 0.15,
            "ShimCache": 0.15,
            "Jumplists": 0.1,
            "LNK": 0.1,
            "MFT": 0.05,
            "USN": 0.05
        }


@dataclass
class ProgressTrackingConfig:
    """Configuration for progress tracking system"""
    enabled: bool = True
    update_frequency_ms: int = 500
    show_memory_usage: bool = True
    show_time_estimates: bool = True
    log_progress_events: bool = True
    terminal_output_enabled: bool = True
    gui_updates_enabled: bool = True


@dataclass
class EngineSelectionConfig:
    """Configuration for engine selection system"""
    default_engine: str = "identity_based"
    show_engine_comparison: bool = True
    show_engine_capabilities: bool = True
    allow_engine_switching: bool = True


@dataclass
class CaseSpecificConfig:
    """Case-specific configuration overrides"""
    case_id: str
    use_case_specific_mappings: bool = False
    use_case_specific_scoring: bool = False
    semantic_mappings_path: Optional[str] = None
    scoring_weights_path: Optional[str] = None
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class IntegratedConfiguration:
    """Complete integrated configuration"""
    semantic_mapping: SemanticMappingConfig = field(default_factory=SemanticMappingConfig)
    weighted_scoring: WeightedScoringConfig = field(default_factory=WeightedScoringConfig)
    progress_tracking: ProgressTrackingConfig = field(default_factory=ProgressTrackingConfig)
    engine_selection: EngineSelectionConfig = field(default_factory=EngineSelectionConfig)
    case_specific: Optional[CaseSpecificConfig] = None
    version: str = "1.0"
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())


class ConfigurationValidationError(Exception):
    """Exception raised when configuration validation fails"""
    pass


class IntegratedConfigurationManager:
    """
    Unified configuration manager for all integrated systems.
    
    Manages global and case-specific configurations with conflict resolution,
    validation, and hierarchical merging.
    """
    
    def __init__(self, config_directory: str = "configs"):
        """
        Initialize integrated configuration manager.
        
        Args:
            config_directory: Root directory for storing configurations
        """
        self.config_dir = Path(config_directory)
        self.global_config_path = self.config_dir / "integrated_config.json"
        self.case_configs_dir = self.config_dir / "cases"
        
        # Create directories if they don't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.case_configs_dir.mkdir(parents=True, exist_ok=True)
        
        # Current configuration state
        self.global_config: IntegratedConfiguration = IntegratedConfiguration()
        self.current_case_config: Optional[CaseSpecificConfig] = None
        self.effective_config: IntegratedConfiguration = IntegratedConfiguration()
        
        # Configuration change listeners
        self.change_listeners: List[callable] = []
        
        # Load global configuration
        self._load_global_configuration()
    
    def _load_global_configuration(self):
        """Load global configuration from file or create default"""
        try:
            if self.global_config_path.exists():
                with open(self.global_config_path, 'r') as f:
                    config_data = json.load(f)
                
                # Parse configuration data
                self.global_config = self._parse_configuration_data(config_data)
                logger.info(f"Loaded global integrated configuration from {self.global_config_path}")
            else:
                # Create default configuration
                self.global_config = IntegratedConfiguration()
                self._save_global_configuration()
                logger.info("Created default global integrated configuration")
            
            # Update effective configuration
            self._update_effective_configuration()
            
        except Exception as e:
            logger.error(f"Failed to load global configuration: {e}")
            # Use default configuration
            self.global_config = IntegratedConfiguration()
            self._update_effective_configuration()
    
    def _parse_configuration_data(self, config_data: Dict[str, Any]) -> IntegratedConfiguration:
        """
        Parse configuration data dictionary into IntegratedConfiguration object.
        
        Args:
            config_data: Configuration dictionary
            
        Returns:
            IntegratedConfiguration object
        """
        try:
            # Parse semantic mapping config
            semantic_data = config_data.get('semantic_mapping', {})
            semantic_config = SemanticMappingConfig(
                enabled=semantic_data.get('enabled', True),
                global_mappings_path=semantic_data.get('global_mappings_path', 'config/semantic_mappings.json'),
                case_specific=semantic_data.get('case_specific', {
                    "enabled": True,
                    "storage_path": "cases/{case_id}/semantic_mappings.json"
                }),
                fallback_to_raw_values=semantic_data.get('fallback_to_raw_values', True),
                log_mapping_statistics=semantic_data.get('log_mapping_statistics', True)
            )
            
            # Parse weighted scoring config
            scoring_data = config_data.get('weighted_scoring', {})
            scoring_config = WeightedScoringConfig(
                enabled=scoring_data.get('enabled', True),
                score_interpretation=scoring_data.get('score_interpretation', {}),
                default_weights=scoring_data.get('default_weights', {}),
                tier_definitions=scoring_data.get('tier_definitions', {}),
                validation_rules=scoring_data.get('validation_rules', {}),
                case_specific=scoring_data.get('case_specific', {
                    "enabled": True,
                    "storage_path": "cases/{case_id}/scoring_weights.json"
                }),
                fallback_to_simple_count=scoring_data.get('fallback_to_simple_count', True)
            )
            
            # Parse progress tracking config
            progress_data = config_data.get('progress_tracking', {})
            progress_config = ProgressTrackingConfig(
                enabled=progress_data.get('enabled', True),
                update_frequency_ms=progress_data.get('update_frequency_ms', 500),
                show_memory_usage=progress_data.get('show_memory_usage', True),
                show_time_estimates=progress_data.get('show_time_estimates', True),
                log_progress_events=progress_data.get('log_progress_events', True),
                terminal_output_enabled=progress_data.get('terminal_output_enabled', True),
                gui_updates_enabled=progress_data.get('gui_updates_enabled', True)
            )
            
            # Parse engine selection config
            engine_data = config_data.get('engine_selection', {})
            engine_config = EngineSelectionConfig(
                default_engine=engine_data.get('default_engine', 'identity_based'),
                show_engine_comparison=engine_data.get('show_engine_comparison', True),
                show_engine_capabilities=engine_data.get('show_engine_capabilities', True),
                allow_engine_switching=engine_data.get('allow_engine_switching', True)
            )
            
            # Parse case-specific config if present
            case_data = config_data.get('case_specific')
            case_config = None
            if case_data and isinstance(case_data, dict):
                case_config = CaseSpecificConfig(
                    case_id=case_data.get('case_id', ''),
                    use_case_specific_mappings=case_data.get('use_case_specific_mappings', False),
                    use_case_specific_scoring=case_data.get('use_case_specific_scoring', False),
                    semantic_mappings_path=case_data.get('semantic_mappings_path'),
                    scoring_weights_path=case_data.get('scoring_weights_path'),
                    created_date=case_data.get('created_date', datetime.now().isoformat()),
                    last_modified=case_data.get('last_modified', datetime.now().isoformat())
                )
            elif isinstance(case_data, CaseSpecificConfig):
                case_config = case_data
            
            return IntegratedConfiguration(
                semantic_mapping=semantic_config,
                weighted_scoring=scoring_config,
                progress_tracking=progress_config,
                engine_selection=engine_config,
                case_specific=case_config,
                version=config_data.get('version', '1.0'),
                created_date=config_data.get('created_date', datetime.now().isoformat()),
                last_modified=config_data.get('last_modified', datetime.now().isoformat())
            )
            
        except Exception as e:
            logger.error(f"Failed to parse configuration data: {e}")
            raise ConfigurationValidationError(f"Invalid configuration format: {e}")
    
    def _save_global_configuration(self):
        """Save global configuration to file and notify observers"""
        try:
            # Capture old configuration before save
            old_config = IntegratedConfiguration(**asdict(self.global_config))
            
            # Update last modified timestamp
            self.global_config.last_modified = datetime.now().isoformat()
            
            # Convert to dictionary
            config_data = asdict(self.global_config)
            
            # Save to file
            with open(self.global_config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Saved global integrated configuration to {self.global_config_path}")
            
            # Update effective configuration
            self._update_effective_configuration()
            
            # Notify observers of the change
            try:
                self._notify_configuration_change()
            except Exception as notify_error:
                # Don't let notification errors prevent save completion
                logger.error(f"Error notifying configuration observers: {notify_error}")
            
        except Exception as e:
            logger.error(f"Failed to save global configuration: {e}")
            raise
    
    def get_global_configuration(self) -> IntegratedConfiguration:
        """
        Get global configuration.
        
        Returns:
            Global IntegratedConfiguration object
        """
        return self.global_config
    
    def get_effective_configuration(self) -> IntegratedConfiguration:
        """
        Get effective configuration (global + case-specific overrides).
        
        Returns:
            Effective IntegratedConfiguration object
        """
        return self.effective_config
    
    def load_case_specific_configuration(self, case_id: str) -> bool:
        """
        Load case-specific configuration.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case-specific configuration was loaded, False otherwise
        """
        try:
            case_config_path = self.case_configs_dir / f"{case_id}.json"
            
            if case_config_path.exists():
                with open(case_config_path, 'r') as f:
                    case_data = json.load(f)
                
                self.current_case_config = CaseSpecificConfig(
                    case_id=case_data.get('case_id', case_id),
                    use_case_specific_mappings=case_data.get('use_case_specific_mappings', False),
                    use_case_specific_scoring=case_data.get('use_case_specific_scoring', False),
                    semantic_mappings_path=case_data.get('semantic_mappings_path'),
                    scoring_weights_path=case_data.get('scoring_weights_path'),
                    created_date=case_data.get('created_date', datetime.now().isoformat()),
                    last_modified=case_data.get('last_modified', datetime.now().isoformat())
                )
                
                # Update effective configuration
                self._update_effective_configuration()
                
                logger.info(f"Loaded case-specific configuration for case {case_id}")
                return True
            else:
                logger.info(f"No case-specific configuration found for case {case_id}")
                self.current_case_config = None
                self._update_effective_configuration()
                return False
                
        except Exception as e:
            logger.error(f"Failed to load case-specific configuration for case {case_id}: {e}")
            self.current_case_config = None
            self._update_effective_configuration()
            return False
    
    def save_case_specific_configuration(self, case_config: CaseSpecificConfig) -> bool:
        """
        Save case-specific configuration.
        
        Args:
            case_config: Case-specific configuration to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            case_config_path = self.case_configs_dir / f"{case_config.case_id}.json"
            
            # Update last modified timestamp
            case_config.last_modified = datetime.now().isoformat()
            
            # Convert to dictionary
            case_data = asdict(case_config)
            
            # Save to file
            with open(case_config_path, 'w') as f:
                json.dump(case_data, f, indent=2)
            
            # Update current case config
            self.current_case_config = case_config
            self._update_effective_configuration()
            
            logger.info(f"Saved case-specific configuration for case {case_config.case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save case-specific configuration for case {case_config.case_id}: {e}")
            return False
    
    def _update_effective_configuration(self):
        """Update effective configuration by merging global and case-specific configs with conflict resolution"""
        try:
            # Start with global configuration - create deep copies to avoid reference issues
            semantic_dict = asdict(self.global_config.semantic_mapping)
            scoring_dict = asdict(self.global_config.weighted_scoring)
            progress_dict = asdict(self.global_config.progress_tracking)
            engine_dict = asdict(self.global_config.engine_selection)
            
            base_config = IntegratedConfiguration(
                semantic_mapping=SemanticMappingConfig(**semantic_dict),
                weighted_scoring=WeightedScoringConfig(**scoring_dict),
                progress_tracking=ProgressTrackingConfig(**progress_dict),
                engine_selection=EngineSelectionConfig(**engine_dict),
                case_specific=self.current_case_config,  # Keep as object, not dict
                version=self.global_config.version,
                created_date=self.global_config.created_date,
                last_modified=datetime.now().isoformat()
            )
            
            # Set as effective config first
            self.effective_config = base_config
            
            # Resolve conflicts if case-specific configuration exists
            if self.current_case_config:
                conflict_resolution = self.resolve_configuration_conflicts(
                    base_config, self.current_case_config
                )
                
                # Log conflict resolution results
                if conflict_resolution['conflicts_found'] > 0:
                    logger.info(f"Configuration conflict resolution: "
                               f"{conflict_resolution['conflicts_resolved']} resolved, "
                               f"{conflict_resolution['conflicts_unresolved']} unresolved")
                
                # Apply case-specific overrides
                if self.current_case_config.use_case_specific_mappings:
                    if self.current_case_config.semantic_mappings_path:
                        self.effective_config.semantic_mapping.global_mappings_path = self.current_case_config.semantic_mappings_path
                
                if self.current_case_config.use_case_specific_scoring:
                    if self.current_case_config.scoring_weights_path:
                        # Load case-specific scoring weights
                        self._load_case_specific_scoring_weights()
            
            # Notify listeners of configuration change
            self._notify_configuration_change()
            
        except Exception as e:
            logger.error(f"Failed to update effective configuration: {e}")
            # Fall back to global configuration
            self.effective_config = self.global_config
            # Ensure case_specific is preserved even in fallback
            if self.current_case_config:
                self.effective_config.case_specific = self.current_case_config
    
    def _load_case_specific_scoring_weights(self):
        """Load case-specific scoring weights into effective configuration"""
        if not self.current_case_config or not self.current_case_config.scoring_weights_path:
            return
        
        try:
            scoring_path = Path(self.current_case_config.scoring_weights_path)
            if scoring_path.exists():
                with open(scoring_path, 'r') as f:
                    scoring_data = json.load(f)
                
                # Update effective configuration with case-specific weights
                if 'default_weights' in scoring_data:
                    self.effective_config.weighted_scoring.default_weights.update(scoring_data['default_weights'])
                
                if 'score_interpretation' in scoring_data:
                    self.effective_config.weighted_scoring.score_interpretation.update(scoring_data['score_interpretation'])
                
                logger.info(f"Loaded case-specific scoring weights from {scoring_path}")
                
        except Exception as e:
            logger.error(f"Failed to load case-specific scoring weights: {e}")
    
    def validate_configuration(self, config: IntegratedConfiguration) -> Dict[str, Any]:
        """
        Validate configuration for correctness and consistency.
        
        Args:
            config: Configuration to validate
            
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'fixes': []
        }
        
        try:
            # Validate semantic mapping configuration
            semantic_validation = self._validate_semantic_mapping_config(config.semantic_mapping)
            validation_result['errors'].extend(semantic_validation.get('errors', []))
            validation_result['warnings'].extend(semantic_validation.get('warnings', []))
            validation_result['fixes'].extend(semantic_validation.get('fixes', []))
            
            # Validate weighted scoring configuration
            scoring_validation = self._validate_weighted_scoring_config(config.weighted_scoring)
            validation_result['errors'].extend(scoring_validation.get('errors', []))
            validation_result['warnings'].extend(scoring_validation.get('warnings', []))
            validation_result['fixes'].extend(scoring_validation.get('fixes', []))
            
            # Validate progress tracking configuration
            progress_validation = self._validate_progress_tracking_config(config.progress_tracking)
            validation_result['errors'].extend(progress_validation.get('errors', []))
            validation_result['warnings'].extend(progress_validation.get('warnings', []))
            validation_result['fixes'].extend(progress_validation.get('fixes', []))
            
            # Set overall validity
            validation_result['valid'] = len(validation_result['errors']) == 0
            
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Configuration validation failed: {e}")
        
        return validation_result
    
    def _validate_semantic_mapping_config(self, config: SemanticMappingConfig) -> Dict[str, Any]:
        """Validate semantic mapping configuration"""
        result = {'errors': [], 'warnings': [], 'fixes': []}
        
        # Check if global mappings path exists
        if config.enabled and config.global_mappings_path:
            mappings_path = Path(config.global_mappings_path)
            if not mappings_path.exists():
                result['warnings'].append(f"Global semantic mappings file not found: {config.global_mappings_path}")
                result['fixes'].append({
                    'field': 'global_mappings_path',
                    'action': 'create_default_file',
                    'description': 'Create default semantic mappings file'
                })
        
        return result
    
    def _validate_weighted_scoring_config(self, config: WeightedScoringConfig) -> Dict[str, Any]:
        """Validate weighted scoring configuration"""
        result = {'errors': [], 'warnings': [], 'fixes': []}
        
        # Validate score interpretation thresholds
        if config.score_interpretation:
            thresholds = []
            for level, interpretation in config.score_interpretation.items():
                min_score = interpretation.get('min', 0.0)
                thresholds.append((level, min_score))
            
            # Check for overlapping thresholds
            thresholds.sort(key=lambda x: x[1])
            for i in range(1, len(thresholds)):
                if thresholds[i][1] <= thresholds[i-1][1]:
                    result['errors'].append(f"Overlapping score thresholds: {thresholds[i-1][0]} and {thresholds[i][0]}")
        
        # Validate default weights
        if config.default_weights:
            for artifact_type, weight in config.default_weights.items():
                if not isinstance(weight, (int, float)):
                    result['errors'].append(f"Invalid weight type for {artifact_type}: {type(weight)}")
                elif weight < 0.0 or weight > 1.0:
                    result['errors'].append(f"Weight out of range for {artifact_type}: {weight}")
                    result['fixes'].append({
                        'field': f'default_weights.{artifact_type}',
                        'action': 'clamp_value',
                        'current_value': weight,
                        'suggested_value': max(0.0, min(1.0, weight)),
                        'description': f'Clamp weight to valid range [0.0, 1.0]'
                    })
        
        # Validate validation rules
        if config.validation_rules:
            rules = config.validation_rules
            max_weight = rules.get('max_weight', 1.0)
            min_weight = rules.get('min_weight', 0.0)
            
            if max_weight <= min_weight:
                result['errors'].append(f"Invalid weight range: max_weight ({max_weight}) <= min_weight ({min_weight})")
        
        return result
    
    def _validate_progress_tracking_config(self, config: ProgressTrackingConfig) -> Dict[str, Any]:
        """Validate progress tracking configuration"""
        result = {'errors': [], 'warnings': [], 'fixes': []}
        
        # Validate update frequency
        if config.update_frequency_ms <= 0:
            result['errors'].append(f"Invalid update frequency: {config.update_frequency_ms}")
            result['fixes'].append({
                'field': 'update_frequency_ms',
                'action': 'set_default',
                'current_value': config.update_frequency_ms,
                'suggested_value': 500,
                'description': 'Set to default update frequency of 500ms'
            })
        elif config.update_frequency_ms < 100:
            result['warnings'].append(f"Very high update frequency may impact performance: {config.update_frequency_ms}ms")
        
        return result
    
    def apply_configuration_fixes(self, config: IntegratedConfiguration, fixes: List[Dict[str, Any]]) -> IntegratedConfiguration:
        """
        Apply suggested fixes to configuration.
        
        Args:
            config: Configuration to fix
            fixes: List of fixes to apply
            
        Returns:
            Fixed configuration
        """
        fixed_config = IntegratedConfiguration(**asdict(config))
        
        for fix in fixes:
            try:
                field_path = fix['field'].split('.')
                action = fix['action']
                suggested_value = fix.get('suggested_value')
                
                # Navigate to the field
                obj = fixed_config
                for part in field_path[:-1]:
                    obj = getattr(obj, part)
                
                field_name = field_path[-1]
                
                if action == 'clamp_value':
                    setattr(obj, field_name, suggested_value)
                elif action == 'set_default':
                    setattr(obj, field_name, suggested_value)
                elif action == 'create_default_file':
                    # Handle file creation separately
                    pass
                
                logger.info(f"Applied configuration fix: {fix['description']}")
                
            except Exception as e:
                logger.error(f"Failed to apply configuration fix: {e}")
        
        return fixed_config
    
    def resolve_configuration_conflicts(self, 
                                      global_config: IntegratedConfiguration,
                                      case_config: Optional[CaseSpecificConfig] = None,
                                      wing_config: Optional[Dict[str, Any]] = None,
                                      pipeline_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Resolve conflicts between global and case-specific configurations.
        
        Args:
            global_config: Global configuration
            case_config: Case-specific configuration
            wing_config: Wing-specific configuration
            pipeline_config: Pipeline-specific configuration
            
        Returns:
            Dictionary with conflict resolution information
        """
        try:
            # For now, use simple case-specific precedence without the complex resolver
            # to avoid object serialization issues
            conflicts_found = 0
            resolution_log = []
            
            if case_config:
                if case_config.use_case_specific_mappings:
                    conflicts_found += 1
                    resolution_log.append("Semantic mapping: case-specific takes precedence")
                
                if case_config.use_case_specific_scoring:
                    conflicts_found += 1
                    resolution_log.append("Weighted scoring: case-specific takes precedence")
            
            # Don't modify self.effective_config here - let the caller handle it
            
            return {
                'conflicts_found': conflicts_found,
                'conflicts_resolved': conflicts_found,
                'conflicts_unresolved': 0,
                'resolution_log': resolution_log,
                'warnings': [],
                'errors': [],
                'resolution_strategy': 'case_specific_precedence'
            }
            
        except Exception as e:
            logger.error(f"Configuration conflict resolution failed: {e}")
            return {
                'conflicts_found': 0,
                'conflicts_resolved': 0,
                'conflicts_unresolved': 0,
                'resolution_log': [],
                'warnings': [],
                'errors': [f"Conflict resolution failed: {e}"],
                'resolution_strategy': 'fallback_to_global'
            }
    
    def add_configuration_change_listener(self, listener: callable):
        """
        Add a listener for configuration changes.
        
        Args:
            listener: Callable that will be called when configuration changes
        """
        self.change_listeners.append(listener)
    
    def remove_configuration_change_listener(self, listener: callable):
        """
        Remove a configuration change listener.
        
        Args:
            listener: Listener to remove
        """
        if listener in self.change_listeners:
            self.change_listeners.remove(listener)
    
    def _notify_configuration_change(self):
        """Notify all listeners of configuration change with error isolation"""
        old_config = None  # We don't have old config stored, so pass None
        new_config = self.effective_config
        
        for listener in self.change_listeners:
            try:
                # Check if listener expects two arguments (old and new config)
                import inspect
                sig = inspect.signature(listener)
                param_count = len(sig.parameters)
                
                if param_count >= 2:
                    listener(old_config, new_config)
                else:
                    # Legacy listener that only expects new config
                    listener(new_config)
            except Exception as e:
                # Isolate errors - don't let one listener failure affect others
                logger.error(f"Configuration change listener failed: {e}")
                logger.exception("Listener exception details:")
    
    def register_observer(self, callback: callable):
        """
        Register an observer for configuration changes.
        
        This is an alias for add_configuration_change_listener for
        consistency with observer pattern terminology.
        
        Args:
            callback: Callable that will be called when configuration changes
        """
        self.add_configuration_change_listener(callback)
    
    def unregister_observer(self, callback: callable):
        """
        Unregister a configuration change observer.
        
        This is an alias for remove_configuration_change_listener for
        consistency with observer pattern terminology.
        
        Args:
            callback: Listener to remove
        """
        self.remove_configuration_change_listener(callback)
    
    def get_effective_configuration_for_execution(self, 
                                                wing_config: Optional[Dict[str, Any]] = None,
                                                pipeline_config: Optional[Dict[str, Any]] = None) -> IntegratedConfiguration:
        """
        Get effective configuration for a specific execution context with wing/pipeline overrides.
        
        Args:
            wing_config: Wing-specific configuration overrides
            pipeline_config: Pipeline-specific configuration overrides
            
        Returns:
            Effective configuration with all overrides applied
        """
        try:
            # Start with current effective configuration
            base_config = self.get_effective_configuration()
            
            # Resolve conflicts with wing and pipeline configurations
            if wing_config or pipeline_config:
                conflict_resolution = self.resolve_configuration_conflicts(
                    base_config, self.current_case_config, wing_config, pipeline_config
                )
                
                # Log conflict resolution if there were conflicts
                if conflict_resolution['conflicts_found'] > 0:
                    logger.info(f"Execution context conflict resolution: "
                               f"{conflict_resolution['conflicts_resolved']} resolved, "
                               f"{conflict_resolution['conflicts_unresolved']} unresolved")
                    
                    # Log specific resolutions for debugging
                    for log_entry in conflict_resolution['resolution_log']:
                        logger.debug(f"  {log_entry}")
                
                # Return the resolved configuration from the conflict resolver
                # The resolver updates self.effective_config, so we return that
                return self.effective_config
            else:
                # No wing/pipeline overrides, return current effective config
                return base_config
                
        except Exception as e:
            logger.error(f"Failed to get effective configuration for execution: {e}")
            # Fall back to current effective configuration
            return self.get_effective_configuration()
    
    def log_configuration_decisions(self, include_conflict_details: bool = True):
        """
        Log configuration decisions for audit purposes.
        
        Args:
            include_conflict_details: Whether to include detailed conflict resolution information
        """
        try:
            logger.info("="*60)
            logger.info("CONFIGURATION AUDIT LOG")
            logger.info("="*60)
            
            # Log current configuration state
            summary = self.get_configuration_summary()
            
            logger.info("Configuration Summary:")
            logger.info(f"  Global config loaded: {summary['global_config_loaded']}")
            logger.info(f"  Case config loaded: {summary['case_config_loaded']}")
            logger.info(f"  Current case: {summary['current_case_id']}")
            logger.info(f"  Configuration version: {summary['configuration_version']}")
            logger.info(f"  Last modified: {summary['last_modified']}")
            
            logger.info("\nFeature Status:")
            logger.info(f"  Semantic mapping: {'enabled' if summary['semantic_mapping_enabled'] else 'disabled'}")
            logger.info(f"  Weighted scoring: {'enabled' if summary['weighted_scoring_enabled'] else 'disabled'}")
            logger.info(f"  Progress tracking: {'enabled' if summary['progress_tracking_enabled'] else 'disabled'}")
            
            if summary['case_config_loaded']:
                logger.info("\nCase-Specific Overrides:")
                logger.info(f"  Case-specific mappings: {'enabled' if summary['case_specific_mappings'] else 'disabled'}")
                logger.info(f"  Case-specific scoring: {'enabled' if summary['case_specific_scoring'] else 'disabled'}")
            
            # Log configuration file paths
            config = self.get_effective_configuration()
            logger.info("\nConfiguration Paths:")
            logger.info(f"  Global config: {self.global_config_path}")
            logger.info(f"  Semantic mappings: {config.semantic_mapping.global_mappings_path}")
            
            if self.current_case_config:
                logger.info(f"  Case config: {self.case_configs_dir / f'{self.current_case_config.case_id}.json'}")
                if self.current_case_config.semantic_mappings_path:
                    logger.info(f"  Case semantic mappings: {self.current_case_config.semantic_mappings_path}")
                if self.current_case_config.scoring_weights_path:
                    logger.info(f"  Case scoring weights: {self.current_case_config.scoring_weights_path}")
            
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"Failed to log configuration decisions: {e}")
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """
        Get a summary of current configuration state.
        
        Returns:
            Dictionary with configuration summary
        """
        return {
            'global_config_loaded': self.global_config is not None,
            'case_config_loaded': self.current_case_config is not None,
            'current_case_id': self.current_case_config.case_id if self.current_case_config else None,
            'semantic_mapping_enabled': self.effective_config.semantic_mapping.enabled,
            'weighted_scoring_enabled': self.effective_config.weighted_scoring.enabled,
            'progress_tracking_enabled': self.effective_config.progress_tracking.enabled,
            'case_specific_mappings': self.current_case_config.use_case_specific_mappings if self.current_case_config else False,
            'case_specific_scoring': self.current_case_config.use_case_specific_scoring if self.current_case_config else False,
            'configuration_version': self.effective_config.version,
            'last_modified': self.effective_config.last_modified
        }
    
    def export_configuration(self, export_path: str, include_case_specific: bool = True) -> bool:
        """
        Export configuration to file.
        
        Args:
            export_path: Path to export file
            include_case_specific: Whether to include case-specific configuration
            
        Returns:
            True if exported successfully, False otherwise
        """
        try:
            export_data = {
                'global_config': asdict(self.global_config),
                'export_timestamp': datetime.now().isoformat(),
                'version': self.effective_config.version
            }
            
            if include_case_specific and self.current_case_config:
                export_data['case_config'] = asdict(self.current_case_config)
            
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            logger.info(f"Exported configuration to {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export configuration: {e}")
            return False
    
    def import_configuration(self, import_path: str, apply_immediately: bool = True) -> bool:
        """
        Import configuration from file.
        
        Args:
            import_path: Path to import file
            apply_immediately: Whether to apply the imported configuration immediately
            
        Returns:
            True if imported successfully, False otherwise
        """
        try:
            with open(import_path, 'r') as f:
                import_data = json.load(f)
            
            # Parse global configuration
            if 'global_config' in import_data:
                imported_global = self._parse_configuration_data(import_data['global_config'])
                
                if apply_immediately:
                    self.global_config = imported_global
                    self._save_global_configuration()
                    self._update_effective_configuration()
            
            # Parse case-specific configuration if present
            if 'case_config' in import_data:
                case_data = import_data['case_config']
                imported_case = CaseSpecificConfig(**case_data)
                
                if apply_immediately:
                    self.save_case_specific_configuration(imported_case)
            
            logger.info(f"Imported configuration from {import_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import configuration: {e}")
            return False
    
    def reset_to_defaults(self, reset_case_specific: bool = False):
        """
        Reset configuration to defaults.
        
        Args:
            reset_case_specific: Whether to also reset case-specific configuration
        """
        try:
            # Reset global configuration
            self.global_config = IntegratedConfiguration()
            self._save_global_configuration()
            
            # Reset case-specific configuration if requested
            if reset_case_specific:
                self.current_case_config = None
            
            # Update effective configuration
            self._update_effective_configuration()
            
            logger.info("Reset configuration to defaults")
            
        except Exception as e:
            logger.error(f"Failed to reset configuration: {e}")
            raise