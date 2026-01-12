"""
Case Configuration Manager

Provides high-level management of case configurations including automatic
switching, comparison, copying, and export/import capabilities.

Features:
- Automatic case-specific settings loading when switching cases
- Configuration export with case results
- Case configuration comparison and copying features
- Configuration change tracking and notifications
- Batch configuration operations
- Configuration validation and repair
"""

import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import shutil

from .case_specific_configuration_manager import (
    CaseSpecificConfigurationManager, CaseSemanticMappingConfig, 
    CaseScoringWeightsConfig, CaseConfigurationMetadata
)
from .case_configuration_file_manager import CaseConfigurationFileManager
from ..integration.case_specific_configuration_integration import CaseSpecificConfigurationIntegration

logger = logging.getLogger(__name__)


@dataclass
class CaseConfigurationComparison:
    """Result of comparing two case configurations"""
    source_case_id: str
    target_case_id: str
    comparison_date: str
    differences: Dict[str, Any]
    similarities: Dict[str, Any]
    recommendations: List[str]
    can_merge: bool
    merge_conflicts: List[str]


@dataclass
class ConfigurationExportResult:
    """Result of configuration export operation"""
    case_id: str
    export_path: str
    export_date: str
    included_components: List[str]
    file_size: int
    success: bool
    error_message: Optional[str] = None


@dataclass
class ConfigurationChangeEvent:
    """Event representing a configuration change"""
    case_id: str
    change_type: str  # 'created', 'updated', 'deleted', 'switched'
    component: str  # 'semantic_mappings', 'scoring_weights', 'metadata'
    timestamp: str
    details: Dict[str, Any]


class CaseConfigurationManager:
    """
    High-level manager for case configurations.
    
    Provides comprehensive case configuration management including automatic
    switching, comparison, copying, and export/import capabilities.
    """
    
    def __init__(self, cases_directory: str = "cases"):
        """
        Initialize case configuration manager.
        
        Args:
            cases_directory: Directory for case configurations
        """
        self.cases_dir = Path(cases_directory)
        
        # Initialize sub-managers
        self.case_manager = CaseSpecificConfigurationManager(cases_directory)
        self.file_manager = CaseConfigurationFileManager(cases_directory)
        self.integration = CaseSpecificConfigurationIntegration(cases_directory)
        
        # Current state
        self.current_case_id: Optional[str] = None
        self.auto_switch_enabled = True
        
        # Change tracking
        self.change_listeners: List[Callable[[ConfigurationChangeEvent], None]] = []
        self.change_history: List[ConfigurationChangeEvent] = []
        
        # Configuration cache
        self._comparison_cache: Dict[str, CaseConfigurationComparison] = {}
        
        logger.info(f"Initialized case configuration manager with directory: {self.cases_dir}")
    
    def add_change_listener(self, listener: Callable[[ConfigurationChangeEvent], None]):
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
    
    def _notify_change_listeners(self, event: ConfigurationChangeEvent):
        """Notify all change listeners of configuration change"""
        self.change_history.append(event)
        
        for listener in self.change_listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(f"Configuration change listener failed: {e}")
    
    def switch_to_case(self, case_id: str, auto_create: bool = True) -> bool:
        """
        Switch to case-specific configuration with automatic loading.
        
        Args:
            case_id: Case identifier to switch to
            auto_create: Whether to create case directory if it doesn't exist
            
        Returns:
            True if switched successfully, False otherwise
        """
        try:
            logger.info(f"Switching to case configuration: {case_id}")
            
            # Check if case exists
            if not self.case_manager.case_exists(case_id):
                if auto_create:
                    self.case_manager.create_case_directory(case_id)
                    logger.info(f"Created new case directory: {case_id}")
                else:
                    logger.error(f"Case does not exist: {case_id}")
                    return False
            
            # Store previous case
            previous_case = self.current_case_id
            
            # Switch using integration layer
            success = self.integration.switch_to_case(case_id, auto_create)
            
            if success:
                self.current_case_id = case_id
                
                # Create change event
                event = ConfigurationChangeEvent(
                    case_id=case_id,
                    change_type='switched',
                    component='all',
                    timestamp=datetime.now().isoformat(),
                    details={
                        'previous_case': previous_case,
                        'new_case': case_id,
                        'auto_created': auto_create and not self.case_manager.case_exists(case_id)
                    }
                )
                
                self._notify_change_listeners(event)
                
                logger.info(f"Successfully switched from case '{previous_case}' to '{case_id}'")
                return True
            else:
                logger.error(f"Failed to switch to case: {case_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error switching to case {case_id}: {e}")
            return False
    
    def get_current_case_id(self) -> Optional[str]:
        """
        Get current case ID.
        
        Returns:
            Current case ID or None if no case is loaded
        """
        return self.current_case_id
    
    def compare_case_configurations(self, 
                                  source_case_id: str, 
                                  target_case_id: str,
                                  use_cache: bool = True) -> CaseConfigurationComparison:
        """
        Compare configurations between two cases.
        
        Args:
            source_case_id: Source case identifier
            target_case_id: Target case identifier
            use_cache: Whether to use cached comparison results
            
        Returns:
            CaseConfigurationComparison object
        """
        # Check cache
        cache_key = f"{source_case_id}:{target_case_id}"
        if use_cache and cache_key in self._comparison_cache:
            return self._comparison_cache[cache_key]
        
        try:
            logger.info(f"Comparing configurations: {source_case_id} vs {target_case_id}")
            
            # Get configurations
            source_summary = self.integration.get_case_configuration_summary(source_case_id)
            target_summary = self.integration.get_case_configuration_summary(target_case_id)
            
            if 'error' in source_summary or 'error' in target_summary:
                raise Exception("Failed to load case configurations for comparison")
            
            # Compare semantic mappings
            semantic_diff = self._compare_semantic_mappings(source_case_id, target_case_id)
            
            # Compare scoring weights
            scoring_diff = self._compare_scoring_weights(source_case_id, target_case_id)
            
            # Compare metadata
            metadata_diff = self._compare_metadata(source_summary, target_summary)
            
            # Aggregate differences and similarities
            differences = {
                'semantic_mappings': semantic_diff['differences'],
                'scoring_weights': scoring_diff['differences'],
                'metadata': metadata_diff['differences']
            }
            
            similarities = {
                'semantic_mappings': semantic_diff['similarities'],
                'scoring_weights': scoring_diff['similarities'],
                'metadata': metadata_diff['similarities']
            }
            
            # Generate recommendations
            recommendations = self._generate_comparison_recommendations(
                source_case_id, target_case_id, differences, similarities
            )
            
            # Check if configurations can be merged
            can_merge, merge_conflicts = self._check_merge_compatibility(differences)
            
            # Create comparison result
            comparison = CaseConfigurationComparison(
                source_case_id=source_case_id,
                target_case_id=target_case_id,
                comparison_date=datetime.now().isoformat(),
                differences=differences,
                similarities=similarities,
                recommendations=recommendations,
                can_merge=can_merge,
                merge_conflicts=merge_conflicts
            )
            
            # Cache result
            self._comparison_cache[cache_key] = comparison
            
            logger.info(f"Configuration comparison completed: {len(recommendations)} recommendations")
            return comparison
            
        except Exception as e:
            logger.error(f"Failed to compare case configurations: {e}")
            # Return empty comparison with error
            return CaseConfigurationComparison(
                source_case_id=source_case_id,
                target_case_id=target_case_id,
                comparison_date=datetime.now().isoformat(),
                differences={'error': str(e)},
                similarities={},
                recommendations=[f"Comparison failed: {e}"],
                can_merge=False,
                merge_conflicts=[f"Comparison error: {e}"]
            )
    
    def _compare_semantic_mappings(self, source_case_id: str, target_case_id: str) -> Dict[str, Any]:
        """Compare semantic mappings between two cases"""
        differences = []
        similarities = []
        
        try:
            # Load configurations
            source_config = self.case_manager.load_case_semantic_mappings(source_case_id)
            target_config = self.case_manager.load_case_semantic_mappings(target_case_id)
            
            # Handle missing configurations
            if not source_config and not target_config:
                similarities.append("Both cases use global semantic mappings")
                return {'differences': differences, 'similarities': similarities}
            
            if not source_config:
                differences.append(f"Source case '{source_case_id}' uses global mappings, target has custom mappings")
                return {'differences': differences, 'similarities': similarities}
            
            if not target_config:
                differences.append(f"Target case '{target_case_id}' uses global mappings, source has custom mappings")
                return {'differences': differences, 'similarities': similarities}
            
            # Compare enabled state
            if source_config.enabled != target_config.enabled:
                differences.append(f"Semantic mappings enabled: {source_config.enabled} vs {target_config.enabled}")
            else:
                similarities.append(f"Both cases have semantic mappings {'enabled' if source_config.enabled else 'disabled'}")
            
            # Compare inheritance settings
            if source_config.inherit_global != target_config.inherit_global:
                differences.append(f"Inherit global: {source_config.inherit_global} vs {target_config.inherit_global}")
            
            if source_config.override_global != target_config.override_global:
                differences.append(f"Override global: {source_config.override_global} vs {target_config.override_global}")
            
            # Compare mappings
            source_mappings = {f"{m.get('source', '')}.{m.get('field', '')}.{m.get('technical_value', '')}": m 
                             for m in source_config.mappings}
            target_mappings = {f"{m.get('source', '')}.{m.get('field', '')}.{m.get('technical_value', '')}": m 
                             for m in target_config.mappings}
            
            # Find unique mappings
            source_only = set(source_mappings.keys()) - set(target_mappings.keys())
            target_only = set(target_mappings.keys()) - set(source_mappings.keys())
            common = set(source_mappings.keys()) & set(target_mappings.keys())
            
            if source_only:
                differences.append(f"Source has {len(source_only)} unique mappings")
            
            if target_only:
                differences.append(f"Target has {len(target_only)} unique mappings")
            
            if common:
                similarities.append(f"Both cases share {len(common)} mappings")
                
                # Compare common mappings for differences
                for key in common:
                    source_mapping = source_mappings[key]
                    target_mapping = target_mappings[key]
                    
                    if source_mapping.get('semantic_value') != target_mapping.get('semantic_value'):
                        differences.append(f"Different semantic values for {key}")
            
        except Exception as e:
            differences.append(f"Error comparing semantic mappings: {e}")
        
        return {'differences': differences, 'similarities': similarities}
    
    def _compare_scoring_weights(self, source_case_id: str, target_case_id: str) -> Dict[str, Any]:
        """Compare scoring weights between two cases"""
        differences = []
        similarities = []
        
        try:
            # Load configurations
            source_config = self.case_manager.load_case_scoring_weights(source_case_id)
            target_config = self.case_manager.load_case_scoring_weights(target_case_id)
            
            # Handle missing configurations
            if not source_config and not target_config:
                similarities.append("Both cases use global scoring weights")
                return {'differences': differences, 'similarities': similarities}
            
            if not source_config:
                differences.append(f"Source case '{source_case_id}' uses global weights, target has custom weights")
                return {'differences': differences, 'similarities': similarities}
            
            if not target_config:
                differences.append(f"Target case '{target_case_id}' uses global weights, source has custom weights")
                return {'differences': differences, 'similarities': similarities}
            
            # Compare enabled state
            if source_config.enabled != target_config.enabled:
                differences.append(f"Scoring weights enabled: {source_config.enabled} vs {target_config.enabled}")
            else:
                similarities.append(f"Both cases have scoring weights {'enabled' if source_config.enabled else 'disabled'}")
            
            # Compare weights
            source_weights = source_config.default_weights
            target_weights = target_config.default_weights
            
            all_artifacts = set(source_weights.keys()) | set(target_weights.keys())
            
            for artifact in all_artifacts:
                source_weight = source_weights.get(artifact, 0.0)
                target_weight = target_weights.get(artifact, 0.0)
                
                if abs(source_weight - target_weight) > 0.01:  # Allow small floating point differences
                    differences.append(f"{artifact} weight: {source_weight} vs {target_weight}")
                else:
                    similarities.append(f"{artifact} weight: {source_weight}")
            
            # Compare score interpretation
            source_interp = source_config.score_interpretation
            target_interp = target_config.score_interpretation
            
            all_levels = set(source_interp.keys()) | set(target_interp.keys())
            
            for level in all_levels:
                source_level = source_interp.get(level, {})
                target_level = target_interp.get(level, {})
                
                if source_level != target_level:
                    differences.append(f"Score interpretation for '{level}' differs")
                else:
                    similarities.append(f"Score interpretation for '{level}' matches")
            
        except Exception as e:
            differences.append(f"Error comparing scoring weights: {e}")
        
        return {'differences': differences, 'similarities': similarities}
    
    def _compare_metadata(self, source_summary: Dict[str, Any], target_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Compare metadata between two cases"""
        differences = []
        similarities = []
        
        try:
            source_metadata = source_summary.get('metadata', {})
            target_metadata = target_summary.get('metadata', {})
            
            # Compare basic fields
            fields_to_compare = ['case_name', 'description', 'tags']
            
            for field in fields_to_compare:
                source_value = source_metadata.get(field, '')
                target_value = target_metadata.get(field, '')
                
                if source_value != target_value:
                    differences.append(f"{field}: '{source_value}' vs '{target_value}'")
                elif source_value:  # Only report similarity if both have values
                    similarities.append(f"{field}: '{source_value}'")
            
            # Compare configuration status
            source_has_semantic = source_summary.get('has_semantic_mappings', False)
            target_has_semantic = target_summary.get('has_semantic_mappings', False)
            
            if source_has_semantic != target_has_semantic:
                differences.append(f"Semantic mappings: {source_has_semantic} vs {target_has_semantic}")
            else:
                similarities.append(f"Both cases {'have' if source_has_semantic else 'lack'} semantic mappings")
            
            source_has_scoring = source_summary.get('has_scoring_weights', False)
            target_has_scoring = target_summary.get('has_scoring_weights', False)
            
            if source_has_scoring != target_has_scoring:
                differences.append(f"Scoring weights: {source_has_scoring} vs {target_has_scoring}")
            else:
                similarities.append(f"Both cases {'have' if source_has_scoring else 'lack'} scoring weights")
            
        except Exception as e:
            differences.append(f"Error comparing metadata: {e}")
        
        return {'differences': differences, 'similarities': similarities}
    
    def _generate_comparison_recommendations(self, 
                                           source_case_id: str, 
                                           target_case_id: str,
                                           differences: Dict[str, Any], 
                                           similarities: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on comparison results"""
        recommendations = []
        
        try:
            # Check if source has more features than target
            source_features = 0
            target_features = 0
            
            # Count semantic mappings
            semantic_diffs = differences.get('semantic_mappings', [])
            for diff in semantic_diffs:
                if 'unique mappings' in diff:
                    if 'Source has' in diff:
                        source_features += 1
                    elif 'Target has' in diff:
                        target_features += 1
            
            # Count scoring weights differences
            scoring_diffs = differences.get('scoring_weights', [])
            if scoring_diffs:
                # If there are scoring differences, one case likely has more comprehensive weights
                if any('Source case' in diff and 'custom weights' in diff for diff in scoring_diffs):
                    source_features += 1
                elif any('Target case' in diff and 'custom weights' in diff for diff in scoring_diffs):
                    target_features += 1
            
            # Generate recommendations based on feature comparison
            if source_features > target_features:
                recommendations.append(f"Consider copying configuration from '{source_case_id}' to '{target_case_id}' for enhanced features")
            elif target_features > source_features:
                recommendations.append(f"Consider copying configuration from '{target_case_id}' to '{source_case_id}' for enhanced features")
            
            # Check for specific improvement opportunities
            if not any('semantic_mappings' in str(similarities.get('semantic_mappings', [])) for _ in [1]):
                recommendations.append("Cases have different semantic mapping approaches - consider standardizing")
            
            if not any('scoring_weights' in str(similarities.get('scoring_weights', [])) for _ in [1]):
                recommendations.append("Cases have different scoring weight configurations - consider harmonizing")
            
            # Check for merge opportunities
            semantic_diffs = differences.get('semantic_mappings', [])
            scoring_diffs = differences.get('scoring_weights', [])
            
            if semantic_diffs and not any('Error' in str(diff) for diff in semantic_diffs):
                recommendations.append("Semantic mappings can be merged to combine unique mappings from both cases")
            
            if scoring_diffs and not any('Error' in str(diff) for diff in scoring_diffs):
                recommendations.append("Scoring weights can be averaged or selectively merged")
            
            # Default recommendation if no specific ones
            if not recommendations:
                recommendations.append("Cases have similar configurations - no immediate changes recommended")
            
        except Exception as e:
            recommendations.append(f"Error generating recommendations: {e}")
        
        return recommendations
    
    def _check_merge_compatibility(self, differences: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Check if configurations can be merged and identify conflicts"""
        conflicts = []
        can_merge = True
        
        try:
            # Check for semantic mapping conflicts
            semantic_diffs = differences.get('semantic_mappings', [])
            for diff in semantic_diffs:
                if 'Different semantic values' in diff:
                    conflicts.append(f"Semantic mapping conflict: {diff}")
                    can_merge = False
            
            # Check for scoring weight conflicts
            scoring_diffs = differences.get('scoring_weights', [])
            for diff in scoring_diffs:
                if 'weight:' in diff and 'vs' in diff:
                    # This is a weight difference, not necessarily a conflict
                    # We can merge by averaging or choosing one
                    pass
            
            # Check for metadata conflicts
            metadata_diffs = differences.get('metadata', [])
            for diff in metadata_diffs:
                if 'case_name:' in diff:
                    conflicts.append(f"Case name conflict: {diff}")
                    # This doesn't prevent merging, just needs resolution
            
            # Check for errors
            for component, diffs in differences.items():
                for diff in diffs:
                    if 'Error' in str(diff):
                        conflicts.append(f"Error in {component}: {diff}")
                        can_merge = False
            
        except Exception as e:
            conflicts.append(f"Error checking merge compatibility: {e}")
            can_merge = False
        
        return can_merge, conflicts
    
    def copy_case_configuration(self, 
                              source_case_id: str, 
                              target_case_id: str,
                              components: Optional[List[str]] = None,
                              merge_strategy: str = 'replace') -> bool:
        """
        Copy configuration from one case to another.
        
        Args:
            source_case_id: Source case identifier
            target_case_id: Target case identifier
            components: List of components to copy ('semantic_mappings', 'scoring_weights', 'metadata')
            merge_strategy: How to handle conflicts ('replace', 'merge', 'skip')
            
        Returns:
            True if copied successfully, False otherwise
        """
        try:
            logger.info(f"Copying configuration from {source_case_id} to {target_case_id}")
            
            # Default to copying all components
            if components is None:
                components = ['semantic_mappings', 'scoring_weights', 'metadata']
            
            # Validate source case exists
            if not self.case_manager.case_exists(source_case_id):
                logger.error(f"Source case does not exist: {source_case_id}")
                return False
            
            # Create target case if it doesn't exist
            if not self.case_manager.case_exists(target_case_id):
                self.case_manager.create_case_directory(target_case_id)
            
            success = True
            
            # Copy semantic mappings
            if 'semantic_mappings' in components:
                semantic_success = self._copy_semantic_mappings(
                    source_case_id, target_case_id, merge_strategy
                )
                success = success and semantic_success
            
            # Copy scoring weights
            if 'scoring_weights' in components:
                scoring_success = self._copy_scoring_weights(
                    source_case_id, target_case_id, merge_strategy
                )
                success = success and scoring_success
            
            # Copy metadata
            if 'metadata' in components:
                metadata_success = self._copy_metadata(
                    source_case_id, target_case_id, merge_strategy
                )
                success = success and metadata_success
            
            if success:
                # Create change event
                event = ConfigurationChangeEvent(
                    case_id=target_case_id,
                    change_type='updated',
                    component='all',
                    timestamp=datetime.now().isoformat(),
                    details={
                        'operation': 'copy',
                        'source_case': source_case_id,
                        'components': components,
                        'merge_strategy': merge_strategy
                    }
                )
                
                self._notify_change_listeners(event)
                
                logger.info(f"Successfully copied configuration from {source_case_id} to {target_case_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to copy case configuration: {e}")
            return False
    
    def _copy_semantic_mappings(self, source_case_id: str, target_case_id: str, merge_strategy: str) -> bool:
        """Copy semantic mappings between cases"""
        try:
            source_config = self.case_manager.load_case_semantic_mappings(source_case_id)
            if not source_config:
                logger.info(f"No semantic mappings to copy from {source_case_id}")
                return True
            
            if merge_strategy == 'replace':
                # Simple replacement
                target_config = CaseSemanticMappingConfig(
                    case_id=target_case_id,
                    enabled=source_config.enabled,
                    mappings=source_config.mappings.copy(),
                    inherit_global=source_config.inherit_global,
                    override_global=source_config.override_global,
                    description=f"Copied from case: {source_case_id}"
                )
            elif merge_strategy == 'merge':
                # Merge with existing configuration
                target_config = self.case_manager.load_case_semantic_mappings(target_case_id)
                if not target_config:
                    target_config = self.case_manager.create_default_semantic_mappings(target_case_id)
                
                # Merge mappings (source takes precedence for conflicts)
                existing_keys = {f"{m.get('source', '')}.{m.get('field', '')}.{m.get('technical_value', '')}": i 
                               for i, m in enumerate(target_config.mappings)}
                
                for source_mapping in source_config.mappings:
                    key = f"{source_mapping.get('source', '')}.{source_mapping.get('field', '')}.{source_mapping.get('technical_value', '')}"
                    if key in existing_keys:
                        # Replace existing mapping
                        target_config.mappings[existing_keys[key]] = source_mapping
                    else:
                        # Add new mapping
                        target_config.mappings.append(source_mapping)
                
                target_config.description = f"Merged with case: {source_case_id}"
            else:  # skip
                # Check if target already has semantic mappings
                if self.case_manager.has_semantic_mappings(target_case_id):
                    logger.info(f"Skipping semantic mappings copy - target case {target_case_id} already has mappings")
                    return True
                
                # Copy since target doesn't have mappings
                target_config = CaseSemanticMappingConfig(
                    case_id=target_case_id,
                    enabled=source_config.enabled,
                    mappings=source_config.mappings.copy(),
                    inherit_global=source_config.inherit_global,
                    override_global=source_config.override_global,
                    description=f"Copied from case: {source_case_id}"
                )
            
            return self.case_manager.save_case_semantic_mappings(target_config)
            
        except Exception as e:
            logger.error(f"Failed to copy semantic mappings: {e}")
            return False
    
    def _copy_scoring_weights(self, source_case_id: str, target_case_id: str, merge_strategy: str) -> bool:
        """Copy scoring weights between cases"""
        try:
            source_config = self.case_manager.load_case_scoring_weights(source_case_id)
            if not source_config:
                logger.info(f"No scoring weights to copy from {source_case_id}")
                return True
            
            if merge_strategy == 'replace':
                # Simple replacement
                target_config = CaseScoringWeightsConfig(
                    case_id=target_case_id,
                    enabled=source_config.enabled,
                    default_weights=source_config.default_weights.copy(),
                    score_interpretation=source_config.score_interpretation.copy(),
                    tier_definitions=source_config.tier_definitions.copy(),
                    validation_rules=source_config.validation_rules.copy(),
                    inherit_global=source_config.inherit_global,
                    override_global=source_config.override_global,
                    description=f"Copied from case: {source_case_id}"
                )
            elif merge_strategy == 'merge':
                # Merge with existing configuration
                target_config = self.case_manager.load_case_scoring_weights(target_case_id)
                if not target_config:
                    target_config = self.case_manager.create_default_scoring_weights(target_case_id)
                
                # Merge weights (average conflicting weights)
                for artifact, weight in source_config.default_weights.items():
                    if artifact in target_config.default_weights:
                        # Average the weights
                        target_config.default_weights[artifact] = (
                            target_config.default_weights[artifact] + weight
                        ) / 2.0
                    else:
                        # Add new weight
                        target_config.default_weights[artifact] = weight
                
                # Merge score interpretation (source takes precedence)
                target_config.score_interpretation.update(source_config.score_interpretation)
                
                target_config.description = f"Merged with case: {source_case_id}"
            else:  # skip
                # Check if target already has scoring weights
                if self.case_manager.has_scoring_weights(target_case_id):
                    logger.info(f"Skipping scoring weights copy - target case {target_case_id} already has weights")
                    return True
                
                # Copy since target doesn't have weights
                target_config = CaseScoringWeightsConfig(
                    case_id=target_case_id,
                    enabled=source_config.enabled,
                    default_weights=source_config.default_weights.copy(),
                    score_interpretation=source_config.score_interpretation.copy(),
                    tier_definitions=source_config.tier_definitions.copy(),
                    validation_rules=source_config.validation_rules.copy(),
                    inherit_global=source_config.inherit_global,
                    override_global=source_config.override_global,
                    description=f"Copied from case: {source_case_id}"
                )
            
            return self.case_manager.save_case_scoring_weights(target_config)
            
        except Exception as e:
            logger.error(f"Failed to copy scoring weights: {e}")
            return False
    
    def _copy_metadata(self, source_case_id: str, target_case_id: str, merge_strategy: str) -> bool:
        """Copy metadata between cases"""
        try:
            source_metadata = self.case_manager.get_case_metadata(source_case_id)
            if not source_metadata:
                logger.info(f"No metadata to copy from {source_case_id}")
                return True
            
            if merge_strategy == 'replace':
                # Simple replacement (but keep target case_id)
                target_metadata = CaseConfigurationMetadata(
                    case_id=target_case_id,
                    case_name=f"{source_metadata.case_name} (Copy)",
                    description=source_metadata.description,
                    tags=source_metadata.tags.copy(),
                    version=source_metadata.version
                )
            elif merge_strategy == 'merge':
                # Merge with existing metadata
                target_metadata = self.case_manager.get_case_metadata(target_case_id)
                if not target_metadata:
                    target_metadata = CaseConfigurationMetadata(case_id=target_case_id)
                
                # Merge tags
                merged_tags = list(set(target_metadata.tags + source_metadata.tags))
                target_metadata.tags = merged_tags
                
                # Update description
                if source_metadata.description and target_metadata.description:
                    target_metadata.description = f"{target_metadata.description}\n\nMerged with: {source_metadata.description}"
                elif source_metadata.description:
                    target_metadata.description = source_metadata.description
            else:  # skip
                # Only copy if target has no metadata
                target_metadata = self.case_manager.get_case_metadata(target_case_id)
                if target_metadata and (target_metadata.case_name or target_metadata.description):
                    logger.info(f"Skipping metadata copy - target case {target_case_id} already has metadata")
                    return True
                
                # Copy metadata
                target_metadata = CaseConfigurationMetadata(
                    case_id=target_case_id,
                    case_name=f"{source_metadata.case_name} (Copy)",
                    description=source_metadata.description,
                    tags=source_metadata.tags.copy(),
                    version=source_metadata.version
                )
            
            return self.case_manager.save_case_metadata(target_metadata)
            
        except Exception as e:
            logger.error(f"Failed to copy metadata: {e}")
            return False
    
    def export_case_configuration_with_results(self, 
                                             case_id: str, 
                                             export_path: str,
                                             include_results: bool = True,
                                             include_metadata: bool = True) -> ConfigurationExportResult:
        """
        Export case configuration with optional correlation results.
        
        Args:
            case_id: Case identifier
            export_path: Path to export file
            include_results: Whether to include correlation results
            include_metadata: Whether to include case metadata
            
        Returns:
            ConfigurationExportResult object
        """
        try:
            logger.info(f"Exporting case configuration with results: {case_id}")
            
            export_data = {
                'case_id': case_id,
                'export_timestamp': datetime.now().isoformat(),
                'export_version': '1.0',
                'included_components': []
            }
            
            # Export case configuration
            case_summary = self.integration.get_case_configuration_summary(case_id)
            if 'error' not in case_summary:
                export_data['case_configuration'] = case_summary
                export_data['included_components'].append('case_configuration')
            
            # Export semantic mappings
            if case_summary.get('has_semantic_mappings'):
                semantic_config = self.case_manager.load_case_semantic_mappings(case_id)
                if semantic_config:
                    export_data['semantic_mappings'] = asdict(semantic_config)
                    export_data['included_components'].append('semantic_mappings')
            
            # Export scoring weights
            if case_summary.get('has_scoring_weights'):
                scoring_config = self.case_manager.load_case_scoring_weights(case_id)
                if scoring_config:
                    export_data['scoring_weights'] = asdict(scoring_config)
                    export_data['included_components'].append('scoring_weights')
            
            # Export metadata
            if include_metadata:
                metadata = self.case_manager.get_case_metadata(case_id)
                if metadata:
                    export_data['metadata'] = asdict(metadata)
                    export_data['included_components'].append('metadata')
            
            # Export correlation results (placeholder - would integrate with actual results system)
            if include_results:
                # This would integrate with the actual correlation results system
                export_data['correlation_results'] = {
                    'note': 'Correlation results would be included here',
                    'results_available': False  # Would check actual results
                }
                export_data['included_components'].append('correlation_results')
            
            # Write export file
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            # Get file size
            file_size = Path(export_path).stat().st_size
            
            # Create result
            result = ConfigurationExportResult(
                case_id=case_id,
                export_path=export_path,
                export_date=datetime.now().isoformat(),
                included_components=export_data['included_components'],
                file_size=file_size,
                success=True
            )
            
            logger.info(f"Successfully exported case configuration: {export_path} ({file_size} bytes)")
            return result
            
        except Exception as e:
            logger.error(f"Failed to export case configuration: {e}")
            return ConfigurationExportResult(
                case_id=case_id,
                export_path=export_path,
                export_date=datetime.now().isoformat(),
                included_components=[],
                file_size=0,
                success=False,
                error_message=str(e)
            )
    
    def import_case_configuration_with_results(self, 
                                             import_path: str, 
                                             target_case_id: Optional[str] = None,
                                             import_results: bool = False) -> bool:
        """
        Import case configuration with optional correlation results.
        
        Args:
            import_path: Path to import file
            target_case_id: Optional target case ID (uses original if not specified)
            import_results: Whether to import correlation results
            
        Returns:
            True if imported successfully, False otherwise
        """
        try:
            logger.info(f"Importing case configuration with results from: {import_path}")
            
            with open(import_path, 'r') as f:
                import_data = json.load(f)
            
            case_id = target_case_id or import_data.get('case_id')
            if not case_id:
                logger.error("No case ID specified for import")
                return False
            
            # Create case directory if needed
            if not self.case_manager.case_exists(case_id):
                self.case_manager.create_case_directory(case_id)
            
            success = True
            
            # Import semantic mappings
            if 'semantic_mappings' in import_data:
                semantic_data = import_data['semantic_mappings']
                semantic_data['case_id'] = case_id  # Update case ID
                semantic_config = CaseSemanticMappingConfig(**semantic_data)
                success = success and self.case_manager.save_case_semantic_mappings(semantic_config)
            
            # Import scoring weights
            if 'scoring_weights' in import_data:
                scoring_data = import_data['scoring_weights']
                scoring_data['case_id'] = case_id  # Update case ID
                scoring_config = CaseScoringWeightsConfig(**scoring_data)
                success = success and self.case_manager.save_case_scoring_weights(scoring_config)
            
            # Import metadata
            if 'metadata' in import_data:
                metadata_data = import_data['metadata']
                metadata_data['case_id'] = case_id  # Update case ID
                metadata = CaseConfigurationMetadata(**metadata_data)
                success = success and self.case_manager.save_case_metadata(metadata)
            
            # Import correlation results (placeholder)
            if import_results and 'correlation_results' in import_data:
                # This would integrate with the actual correlation results system
                logger.info("Correlation results import would be handled here")
            
            if success:
                # Create change event
                event = ConfigurationChangeEvent(
                    case_id=case_id,
                    change_type='updated',
                    component='all',
                    timestamp=datetime.now().isoformat(),
                    details={
                        'operation': 'import',
                        'import_path': import_path,
                        'components': import_data.get('included_components', [])
                    }
                )
                
                self._notify_change_listeners(event)
                
                logger.info(f"Successfully imported case configuration for {case_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to import case configuration: {e}")
            return False
    
    def get_configuration_change_history(self, case_id: Optional[str] = None) -> List[ConfigurationChangeEvent]:
        """
        Get configuration change history.
        
        Args:
            case_id: Optional case ID to filter by
            
        Returns:
            List of configuration change events
        """
        if case_id:
            return [event for event in self.change_history if event.case_id == case_id]
        else:
            return self.change_history.copy()
    
    def clear_comparison_cache(self):
        """Clear the configuration comparison cache"""
        self._comparison_cache.clear()
        logger.info("Cleared configuration comparison cache")
    
    def get_configuration_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive configuration statistics.
        
        Returns:
            Dictionary with configuration statistics
        """
        try:
            # Get basic statistics from file manager
            file_stats = self.file_manager.get_configuration_statistics()
            
            # Get case summary from case manager
            case_summary = self.case_manager.get_configuration_summary()
            
            # Add change history statistics
            change_stats = {
                'total_changes': len(self.change_history),
                'changes_by_type': {},
                'changes_by_component': {},
                'recent_changes': []
            }
            
            for event in self.change_history:
                # Count by type
                change_type = event.change_type
                change_stats['changes_by_type'][change_type] = change_stats['changes_by_type'].get(change_type, 0) + 1
                
                # Count by component
                component = event.component
                change_stats['changes_by_component'][component] = change_stats['changes_by_component'].get(component, 0) + 1
            
            # Get recent changes (last 10)
            change_stats['recent_changes'] = [asdict(event) for event in self.change_history[-10:]]
            
            # Combine all statistics
            combined_stats = {
                'file_statistics': file_stats,
                'case_summary': case_summary,
                'change_history': change_stats,
                'current_case': self.current_case_id,
                'auto_switch_enabled': self.auto_switch_enabled,
                'comparison_cache_size': len(self._comparison_cache)
            }
            
            return combined_stats
            
        except Exception as e:
            logger.error(f"Failed to get configuration statistics: {e}")
            return {'error': f'Failed to get statistics: {e}'}
    
    def perform_maintenance(self) -> Dict[str, Any]:
        """
        Perform maintenance operations on case configurations.
        
        Returns:
            Dictionary with maintenance results
        """
        try:
            logger.info("Performing case configuration maintenance")
            
            results = {
                'start_time': datetime.now().isoformat(),
                'operations_performed': [],
                'files_processed': 0,
                'errors_found': 0,
                'errors_fixed': 0,
                'space_saved': 0
            }
            
            # Perform file manager maintenance
            file_maintenance = self.integration.perform_maintenance()
            results.update(file_maintenance)
            results['operations_performed'].append('file_maintenance')
            
            # Clear old comparison cache entries
            self.clear_comparison_cache()
            results['operations_performed'].append('cache_cleanup')
            
            # Validate all case configurations
            cases = self.case_manager.list_cases()
            for case_id in cases:
                try:
                    validation = self.case_manager.validate_case_configuration(case_id)
                    if not validation['valid']:
                        results['errors_found'] += len(validation['errors'])
                        logger.warning(f"Validation errors in case {case_id}: {validation['errors']}")
                except Exception as e:
                    results['errors_found'] += 1
                    logger.error(f"Failed to validate case {case_id}: {e}")
            
            results['operations_performed'].append('configuration_validation')
            
            # Trim change history (keep last 1000 entries)
            if len(self.change_history) > 1000:
                removed_count = len(self.change_history) - 1000
                self.change_history = self.change_history[-1000:]
                results['operations_performed'].append(f'trimmed_{removed_count}_history_entries')
            
            results['end_time'] = datetime.now().isoformat()
            results['success'] = True
            
            logger.info(f"Maintenance completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Maintenance failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'end_time': datetime.now().isoformat()
            }