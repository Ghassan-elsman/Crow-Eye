"""
Case-Specific Configuration Integration

Provides high-level integration layer for case-specific configurations.
Coordinates between case configuration managers, semantic mapping systems,
and weighted scoring systems to provide seamless case-specific overrides.

Features:
- Unified case configuration loading and management
- Automatic configuration switching when changing cases
- Configuration inheritance and merging
- Real-time configuration validation
- Configuration change event handling
- Integration with existing correlation engines
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime

from ..config.case_specific_configuration_manager import (
    CaseSpecificConfigurationManager, 
    CaseSemanticMappingConfig, 
    CaseScoringWeightsConfig,
    CaseConfigurationMetadata
)
from ..config.case_configuration_file_manager import CaseConfigurationFileManager
from ..config.semantic_mapping import SemanticMappingManager, SemanticMapping
from ..integration.weighted_scoring_integration import WeightedScoringIntegration
from ..config.integrated_configuration_manager import IntegratedConfigurationManager

logger = logging.getLogger(__name__)


@dataclass
class CaseConfigurationState:
    """Current state of case-specific configuration"""
    current_case_id: Optional[str] = None
    has_semantic_mappings: bool = False
    has_scoring_weights: bool = False
    semantic_mappings_enabled: bool = False
    scoring_weights_enabled: bool = False
    last_loaded: Optional[str] = None
    configuration_valid: bool = True
    validation_errors: List[str] = None
    
    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []


class CaseSpecificConfigurationIntegration:
    """
    High-level integration layer for case-specific configurations.
    
    Provides unified interface for managing case-specific semantic mappings
    and scoring weights, with automatic switching and validation.
    """
    
    def __init__(self, 
                 cases_directory: str = "cases",
                 integrated_config_manager: Optional[IntegratedConfigurationManager] = None):
        """
        Initialize case-specific configuration integration.
        
        Args:
            cases_directory: Directory for case configurations
            integrated_config_manager: Optional integrated configuration manager
        """
        self.cases_dir = Path(cases_directory)
        
        # Initialize managers
        self.case_config_manager = CaseSpecificConfigurationManager(cases_directory)
        self.file_manager = CaseConfigurationFileManager(cases_directory)
        self.semantic_mapping_manager = SemanticMappingManager()
        self.scoring_integration = WeightedScoringIntegration()
        self.integrated_config_manager = integrated_config_manager
        
        # Current state
        self.state = CaseConfigurationState()
        
        # Change listeners
        self.change_listeners: List[Callable] = []
        
        # Cache for merged configurations
        self._merged_semantic_cache: Dict[str, Any] = {}
        self._merged_scoring_cache: Dict[str, Any] = {}
        
        logger.info(f"Initialized case-specific configuration integration with directory: {self.cases_dir}")
    
    def add_change_listener(self, listener: Callable[[CaseConfigurationState], None]):
        """
        Add listener for configuration changes.
        
        Args:
            listener: Function to call when configuration changes
        """
        self.change_listeners.append(listener)
    
    def remove_change_listener(self, listener: Callable):
        """
        Remove configuration change listener.
        
        Args:
            listener: Listener to remove
        """
        if listener in self.change_listeners:
            self.change_listeners.remove(listener)
    
    def _notify_change_listeners(self):
        """Notify all change listeners of configuration change"""
        for listener in self.change_listeners:
            try:
                listener(self.state)
            except Exception as e:
                logger.error(f"Configuration change listener failed: {e}")
    
    def switch_to_case(self, case_id: str, auto_create: bool = True) -> bool:
        """
        Switch to case-specific configuration.
        
        Args:
            case_id: Case identifier to switch to
            auto_create: Whether to create case directory if it doesn't exist
            
        Returns:
            True if switched successfully, False otherwise
        """
        try:
            logger.info(f"Switching to case configuration: {case_id}")
            
            # Create case directory if needed
            if auto_create and not self.case_config_manager.case_exists(case_id):
                self.case_config_manager.create_case_directory(case_id)
            
            # Update state
            previous_case = self.state.current_case_id
            self.state.current_case_id = case_id
            self.state.last_loaded = datetime.now().isoformat()
            
            # Load case-specific configurations
            self._load_case_configurations(case_id)
            
            # Validate configurations
            self._validate_current_configuration()
            
            # Clear caches
            self._clear_configuration_cache()
            
            # Update integrated configuration manager if available
            if self.integrated_config_manager:
                self.integrated_config_manager.load_case_specific_configuration(case_id)
            
            # Notify listeners
            self._notify_change_listeners()
            
            logger.info(f"Successfully switched from case '{previous_case}' to '{case_id}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to switch to case {case_id}: {e}")
            self.state.configuration_valid = False
            self.state.validation_errors.append(f"Failed to switch to case: {e}")
            return False
    
    def _load_case_configurations(self, case_id: str):
        """Load case-specific configurations"""
        # Load semantic mappings
        semantic_config = self.case_config_manager.load_case_semantic_mappings(case_id)
        self.state.has_semantic_mappings = semantic_config is not None
        self.state.semantic_mappings_enabled = (
            semantic_config.enabled if semantic_config else False
        )
        
        # Load scoring weights
        scoring_config = self.case_config_manager.load_case_scoring_weights(case_id)
        self.state.has_scoring_weights = scoring_config is not None
        self.state.scoring_weights_enabled = (
            scoring_config.enabled if scoring_config else False
        )
        
        # Apply configurations to managers
        if semantic_config and semantic_config.enabled:
            self._apply_semantic_mappings(semantic_config)
        
        if scoring_config and scoring_config.enabled:
            self._apply_scoring_weights(case_id, scoring_config)
    
    def _apply_semantic_mappings(self, config: CaseSemanticMappingConfig):
        """Apply case-specific semantic mappings"""
        try:
            # Add case-specific mappings to semantic mapping manager
            for mapping_data in config.mappings:
                mapping = SemanticMapping(**mapping_data)
                mapping.scope = "case"
                mapping.wing_id = config.case_id  # Use case_id as wing_id for case-specific mappings
                self.semantic_mapping_manager.add_mapping(mapping)
            
            logger.info(f"Applied {len(config.mappings)} case-specific semantic mappings for case {config.case_id}")
            
        except Exception as e:
            logger.error(f"Failed to apply semantic mappings for case {config.case_id}: {e}")
            self.state.validation_errors.append(f"Failed to apply semantic mappings: {e}")
    
    def _apply_scoring_weights(self, case_id: str, config: CaseScoringWeightsConfig):
        """Apply case-specific scoring weights"""
        try:
            # Load case-specific scoring weights into scoring integration
            success = self.scoring_integration.load_case_specific_scoring_weights(case_id)
            if not success:
                logger.warning(f"Failed to load case-specific scoring weights for case {case_id}")
            else:
                logger.info(f"Applied case-specific scoring weights for case {case_id}")
            
        except Exception as e:
            logger.error(f"Failed to apply scoring weights for case {case_id}: {e}")
            self.state.validation_errors.append(f"Failed to apply scoring weights: {e}")
    
    def _validate_current_configuration(self):
        """Validate current case configuration"""
        if not self.state.current_case_id:
            self.state.configuration_valid = True
            return
        
        try:
            validation_result = self.case_config_manager.validate_case_configuration(
                self.state.current_case_id
            )
            
            self.state.configuration_valid = validation_result['valid']
            self.state.validation_errors = validation_result['errors']
            
            if not validation_result['valid']:
                logger.warning(f"Case configuration validation failed for {self.state.current_case_id}: "
                             f"{validation_result['errors']}")
            
        except Exception as e:
            logger.error(f"Failed to validate case configuration: {e}")
            self.state.configuration_valid = False
            self.state.validation_errors.append(f"Validation failed: {e}")
    
    def _clear_configuration_cache(self):
        """Clear configuration caches"""
        self._merged_semantic_cache.clear()
        self._merged_scoring_cache.clear()
        self.case_config_manager.clear_cache(self.state.current_case_id)
    
    def create_case_configuration(self, 
                                case_id: str, 
                                case_name: str = "",
                                enable_semantic_mappings: bool = False,
                                enable_scoring_weights: bool = False,
                                copy_from_case: Optional[str] = None) -> bool:
        """
        Create new case configuration.
        
        Args:
            case_id: Case identifier
            case_name: Optional case name
            enable_semantic_mappings: Whether to enable semantic mappings
            enable_scoring_weights: Whether to enable scoring weights
            copy_from_case: Optional case to copy configuration from
            
        Returns:
            True if created successfully, False otherwise
        """
        try:
            logger.info(f"Creating case configuration: {case_id}")
            
            # Create case directory
            self.case_config_manager.create_case_directory(case_id)
            
            # Create metadata
            metadata = CaseConfigurationMetadata(
                case_id=case_id,
                case_name=case_name or case_id,
                description=f"Configuration for case: {case_name or case_id}"
            )
            self.case_config_manager.save_case_metadata(metadata)
            
            # Copy from existing case if specified
            if copy_from_case and self.case_config_manager.case_exists(copy_from_case):
                success = self.case_config_manager.copy_case_configuration(
                    copy_from_case, case_id,
                    copy_semantic_mappings=enable_semantic_mappings,
                    copy_scoring_weights=enable_scoring_weights
                )
                if not success:
                    logger.warning(f"Failed to copy configuration from {copy_from_case}")
            
            # Create default configurations if enabled
            if enable_semantic_mappings:
                semantic_config = self.case_config_manager.create_default_semantic_mappings(
                    case_id, case_name
                )
                self.case_config_manager.save_case_semantic_mappings(semantic_config)
            
            if enable_scoring_weights:
                scoring_config = self.case_config_manager.create_default_scoring_weights(
                    case_id, case_name
                )
                self.case_config_manager.save_case_scoring_weights(scoring_config)
            
            logger.info(f"Successfully created case configuration: {case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create case configuration {case_id}: {e}")
            return False
    
    def get_case_configuration_summary(self, case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get summary of case configuration.
        
        Args:
            case_id: Optional case ID (uses current case if not specified)
            
        Returns:
            Dictionary with configuration summary
        """
        target_case = case_id or self.state.current_case_id
        if not target_case:
            return {'error': 'No case specified or loaded'}
        
        try:
            summary = {
                'case_id': target_case,
                'exists': self.case_config_manager.case_exists(target_case),
                'has_semantic_mappings': self.case_config_manager.has_semantic_mappings(target_case),
                'has_scoring_weights': self.case_config_manager.has_scoring_weights(target_case),
                'metadata': None,
                'semantic_mappings_count': 0,
                'scoring_weights_count': 0,
                'validation': None
            }
            
            # Get metadata
            metadata = self.case_config_manager.get_case_metadata(target_case)
            if metadata:
                summary['metadata'] = asdict(metadata)
            
            # Get semantic mappings info
            if summary['has_semantic_mappings']:
                semantic_config = self.case_config_manager.load_case_semantic_mappings(target_case)
                if semantic_config:
                    summary['semantic_mappings_count'] = len(semantic_config.mappings)
                    summary['semantic_mappings_enabled'] = semantic_config.enabled
            
            # Get scoring weights info
            if summary['has_scoring_weights']:
                scoring_config = self.case_config_manager.load_case_scoring_weights(target_case)
                if scoring_config:
                    summary['scoring_weights_count'] = len(scoring_config.default_weights)
                    summary['scoring_weights_enabled'] = scoring_config.enabled
            
            # Get validation info
            summary['validation'] = self.case_config_manager.validate_case_configuration(target_case)
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get case configuration summary for {target_case}: {e}")
            return {'error': f'Failed to get summary: {e}'}
    
    def update_case_semantic_mappings(self, 
                                    case_id: str,
                                    mappings: List[Dict[str, Any]],
                                    enabled: bool = True,
                                    inherit_global: bool = True) -> bool:
        """
        Update case-specific semantic mappings.
        
        Args:
            case_id: Case identifier
            mappings: List of semantic mapping dictionaries
            enabled: Whether semantic mappings are enabled
            inherit_global: Whether to inherit global mappings
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            # Load existing configuration or create new
            existing_config = self.case_config_manager.load_case_semantic_mappings(case_id)
            
            if existing_config:
                config = existing_config
                config.mappings = mappings
                config.enabled = enabled
                config.inherit_global = inherit_global
                config.last_modified = datetime.now().isoformat()
            else:
                config = CaseSemanticMappingConfig(
                    case_id=case_id,
                    enabled=enabled,
                    mappings=mappings,
                    inherit_global=inherit_global
                )
            
            # Save configuration
            success = self.case_config_manager.save_case_semantic_mappings(config)
            
            # Reload if this is the current case
            if case_id == self.state.current_case_id:
                self._load_case_configurations(case_id)
                self._notify_change_listeners()
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to update semantic mappings for case {case_id}: {e}")
            return False
    
    def update_case_scoring_weights(self,
                                  case_id: str,
                                  weights: Dict[str, float],
                                  score_interpretation: Optional[Dict[str, Dict[str, Any]]] = None,
                                  enabled: bool = True,
                                  inherit_global: bool = True) -> bool:
        """
        Update case-specific scoring weights.
        
        Args:
            case_id: Case identifier
            weights: Dictionary of artifact type -> weight
            score_interpretation: Optional score interpretation configuration
            enabled: Whether scoring weights are enabled
            inherit_global: Whether to inherit global weights
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            # Load existing configuration or create new
            existing_config = self.case_config_manager.load_case_scoring_weights(case_id)
            
            if existing_config:
                config = existing_config
                config.default_weights = weights
                config.enabled = enabled
                config.inherit_global = inherit_global
                config.last_modified = datetime.now().isoformat()
                
                if score_interpretation:
                    config.score_interpretation = score_interpretation
            else:
                config = CaseScoringWeightsConfig(
                    case_id=case_id,
                    enabled=enabled,
                    default_weights=weights,
                    score_interpretation=score_interpretation or {},
                    inherit_global=inherit_global
                )
            
            # Save configuration
            success = self.case_config_manager.save_case_scoring_weights(config)
            
            # Reload if this is the current case
            if case_id == self.state.current_case_id:
                self._load_case_configurations(case_id)
                self._notify_change_listeners()
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to update scoring weights for case {case_id}: {e}")
            return False
    
    def get_effective_semantic_mappings(self, case_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Get effective semantic mappings (global + case-specific).
        
        Args:
            case_id: Optional case ID (uses current case if not specified)
            
        Returns:
            List of effective semantic mappings
        """
        target_case = case_id or self.state.current_case_id
        
        # Check cache
        cache_key = f"semantic_{target_case}"
        if cache_key in self._merged_semantic_cache:
            return self._merged_semantic_cache[cache_key]
        
        try:
            effective_mappings = []
            
            # Start with global mappings
            global_mappings = self.semantic_mapping_manager.get_all_mappings("global")
            effective_mappings.extend(global_mappings)
            
            # Add case-specific mappings if available
            if target_case:
                case_config = self.case_config_manager.load_case_semantic_mappings(target_case)
                if case_config and case_config.enabled:
                    for mapping_data in case_config.mappings:
                        mapping = SemanticMapping(**mapping_data)
                        mapping.scope = "case"
                        mapping.wing_id = target_case
                        effective_mappings.append(mapping)
            
            # Cache result
            self._merged_semantic_cache[cache_key] = effective_mappings
            
            return effective_mappings
            
        except Exception as e:
            logger.error(f"Failed to get effective semantic mappings for case {target_case}: {e}")
            return []
    
    def get_effective_scoring_configuration(self, case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get effective scoring configuration (global + case-specific).
        
        Args:
            case_id: Optional case ID (uses current case if not specified)
            
        Returns:
            Dictionary with effective scoring configuration
        """
        target_case = case_id or self.state.current_case_id
        
        # Check cache
        cache_key = f"scoring_{target_case}"
        if cache_key in self._merged_scoring_cache:
            return self._merged_scoring_cache[cache_key]
        
        try:
            # Get global configuration from scoring integration
            global_config = self.scoring_integration.get_scoring_configuration()
            effective_config = {
                'enabled': global_config.enabled,
                'default_weights': global_config.default_weights.copy(),
                'score_interpretation': global_config.score_interpretation.copy(),
                'tier_definitions': global_config.tier_definitions.copy(),
                'validation_rules': global_config.validation_rules.copy()
            }
            
            # Apply case-specific overrides if available
            if target_case:
                case_config = self.case_config_manager.load_case_scoring_weights(target_case)
                if case_config and case_config.enabled:
                    # Override with case-specific values
                    if case_config.default_weights:
                        effective_config['default_weights'].update(case_config.default_weights)
                    if case_config.score_interpretation:
                        effective_config['score_interpretation'].update(case_config.score_interpretation)
                    if case_config.tier_definitions:
                        effective_config['tier_definitions'].update(case_config.tier_definitions)
                    if case_config.validation_rules:
                        effective_config['validation_rules'].update(case_config.validation_rules)
            
            # Cache result
            self._merged_scoring_cache[cache_key] = effective_config
            
            return effective_config
            
        except Exception as e:
            logger.error(f"Failed to get effective scoring configuration for case {target_case}: {e}")
            return {}
    
    def export_case_configuration(self, case_id: str, export_path: str) -> bool:
        """
        Export case configuration to file.
        
        Args:
            case_id: Case identifier
            export_path: Path to export file
            
        Returns:
            True if exported successfully, False otherwise
        """
        return self.case_config_manager.export_case_configuration(case_id, export_path)
    
    def import_case_configuration(self, import_path: str, target_case_id: Optional[str] = None) -> bool:
        """
        Import case configuration from file.
        
        Args:
            import_path: Path to import file
            target_case_id: Optional target case ID
            
        Returns:
            True if imported successfully, False otherwise
        """
        success = self.case_config_manager.import_case_configuration(import_path, target_case_id)
        
        # Reload if this affects the current case
        imported_case = target_case_id
        if not imported_case:
            # Try to determine case ID from import file
            try:
                import json
                with open(import_path, 'r') as f:
                    data = json.load(f)
                imported_case = data.get('case_id')
            except:
                pass
        
        if imported_case == self.state.current_case_id:
            self._load_case_configurations(imported_case)
            self._notify_change_listeners()
        
        return success
    
    def delete_case_configuration(self, case_id: str, backup: bool = True) -> bool:
        """
        Delete case configuration.
        
        Args:
            case_id: Case identifier
            backup: Whether to create backup before deletion
            
        Returns:
            True if deleted successfully, False otherwise
        """
        success = self.case_config_manager.delete_case_configuration(case_id, backup)
        
        # If we deleted the current case, switch to no case
        if case_id == self.state.current_case_id:
            self.state = CaseConfigurationState()
            self._clear_configuration_cache()
            self._notify_change_listeners()
        
        return success
    
    def list_available_cases(self) -> List[Dict[str, Any]]:
        """
        List all available cases with their configuration status.
        
        Returns:
            List of dictionaries with case information
        """
        cases = []
        
        for case_id in self.case_config_manager.list_cases():
            case_info = {
                'case_id': case_id,
                'has_semantic_mappings': self.case_config_manager.has_semantic_mappings(case_id),
                'has_scoring_weights': self.case_config_manager.has_scoring_weights(case_id),
                'is_current': case_id == self.state.current_case_id
            }
            
            # Get metadata
            metadata = self.case_config_manager.get_case_metadata(case_id)
            if metadata:
                case_info.update({
                    'case_name': metadata.case_name,
                    'description': metadata.description,
                    'last_modified': metadata.last_modified,
                    'tags': metadata.tags
                })
            
            cases.append(case_info)
        
        return sorted(cases, key=lambda x: x.get('last_modified', ''), reverse=True)
    
    def get_current_state(self) -> CaseConfigurationState:
        """
        Get current configuration state.
        
        Returns:
            Current CaseConfigurationState
        """
        return self.state
    
    def perform_maintenance(self) -> Dict[str, Any]:
        """
        Perform maintenance operations on case configurations.
        
        Returns:
            Dictionary with maintenance results
        """
        try:
            results = {
                'archived_files': 0,
                'cleaned_directories': 0,
                'repaired_files': 0,
                'validation_errors': 0,
                'statistics': {}
            }
            
            # Archive old configurations
            results['archived_files'] = self.file_manager.archive_old_configurations(days_old=30)
            
            # Clean up empty directories
            results['cleaned_directories'] = self.file_manager.cleanup_empty_case_directories()
            
            # Validate and repair configurations
            for case_id in self.case_config_manager.list_cases():
                validation = self.case_config_manager.validate_case_configuration(case_id)
                if not validation['valid']:
                    results['validation_errors'] += len(validation['errors'])
                    
                    # Attempt to repair files
                    case_dir = self.case_config_manager.get_case_directory(case_id)
                    for config_type, filename in self.file_manager.config_files.items():
                        config_file = case_dir / filename
                        if config_file.exists():
                            file_validation = self.file_manager.validate_configuration_file(
                                config_file, config_type
                            )
                            if not file_validation['valid']:
                                if self.file_manager.repair_configuration_file(config_file, config_type):
                                    results['repaired_files'] += 1
            
            # Get statistics
            results['statistics'] = self.file_manager.get_configuration_statistics()
            
            logger.info(f"Maintenance completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Maintenance failed: {e}")
            return {'error': f'Maintenance failed: {e}'}