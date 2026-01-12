"""
Configuration Conflict Resolver

Handles conflicts between global, pipeline, wing, and case-specific configurations.
Provides prioritization logic and conflict resolution strategies.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from .integrated_configuration_manager import (
    IntegratedConfiguration, SemanticMappingConfig, WeightedScoringConfig,
    ProgressTrackingConfig, EngineSelectionConfig, CaseSpecificConfig
)

logger = logging.getLogger(__name__)


class ConflictSeverity(Enum):
    """Severity levels for configuration conflicts"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResolutionStrategy(Enum):
    """Strategies for resolving configuration conflicts"""
    CASE_SPECIFIC_PRECEDENCE = "case_specific_precedence"
    WING_PRECEDENCE = "wing_precedence"
    PIPELINE_PRECEDENCE = "pipeline_precedence"
    GLOBAL_PRECEDENCE = "global_precedence"
    MERGE_ADDITIVE = "merge_additive"
    MERGE_OVERRIDE = "merge_override"
    USER_CHOICE = "user_choice"


@dataclass
class ConfigurationConflict:
    """Represents a configuration conflict"""
    conflict_id: str
    section: str  # semantic_mapping, weighted_scoring, etc.
    field: str
    global_value: Any
    case_value: Optional[Any] = None
    wing_value: Optional[Any] = None
    pipeline_value: Optional[Any] = None
    severity: ConflictSeverity = ConflictSeverity.LOW
    description: str = ""
    suggested_resolution: ResolutionStrategy = ResolutionStrategy.CASE_SPECIFIC_PRECEDENCE
    resolved_value: Optional[Any] = None
    resolution_reason: str = ""


@dataclass
class ConflictResolutionResult:
    """Result of conflict resolution process"""
    conflicts_found: int
    conflicts_resolved: int
    conflicts_unresolved: int
    resolution_log: List[str]
    resolved_configuration: IntegratedConfiguration
    warnings: List[str]
    errors: List[str]


class ConfigurationConflictResolver:
    """
    Resolves conflicts between different levels of configuration.
    
    Priority order (highest to lowest):
    1. Case-specific configuration
    2. Wing-specific configuration  
    3. Pipeline-specific configuration
    4. Global configuration
    """
    
    def __init__(self):
        """Initialize configuration conflict resolver"""
        self.resolution_strategies = {
            ResolutionStrategy.CASE_SPECIFIC_PRECEDENCE: self._resolve_case_precedence,
            ResolutionStrategy.WING_PRECEDENCE: self._resolve_wing_precedence,
            ResolutionStrategy.PIPELINE_PRECEDENCE: self._resolve_pipeline_precedence,
            ResolutionStrategy.GLOBAL_PRECEDENCE: self._resolve_global_precedence,
            ResolutionStrategy.MERGE_ADDITIVE: self._resolve_merge_additive,
            ResolutionStrategy.MERGE_OVERRIDE: self._resolve_merge_override
        }
        
        self.conflict_counter = 0
    
    def resolve_configuration_conflicts(self,
                                      global_config: IntegratedConfiguration,
                                      case_config: Optional[CaseSpecificConfig] = None,
                                      wing_config: Optional[Dict[str, Any]] = None,
                                      pipeline_config: Optional[Dict[str, Any]] = None) -> ConflictResolutionResult:
        """
        Resolve conflicts between different configuration levels.
        
        Args:
            global_config: Global configuration
            case_config: Case-specific configuration
            wing_config: Wing-specific configuration
            pipeline_config: Pipeline-specific configuration
            
        Returns:
            ConflictResolutionResult with resolved configuration
        """
        try:
            # Detect conflicts
            conflicts = self._detect_all_conflicts(global_config, case_config, wing_config, pipeline_config)
            
            # Resolve conflicts
            resolved_config, resolution_log, warnings, errors = self._resolve_conflicts(
                global_config, conflicts, case_config, wing_config, pipeline_config
            )
            
            # Create result
            result = ConflictResolutionResult(
                conflicts_found=len(conflicts),
                conflicts_resolved=len([c for c in conflicts if c.resolved_value is not None]),
                conflicts_unresolved=len([c for c in conflicts if c.resolved_value is None]),
                resolution_log=resolution_log,
                resolved_configuration=resolved_config,
                warnings=warnings,
                errors=errors
            )
            
            logger.info(f"Configuration conflict resolution completed: "
                       f"{result.conflicts_found} conflicts found, "
                       f"{result.conflicts_resolved} resolved, "
                       f"{result.conflicts_unresolved} unresolved")
            
            return result
            
        except Exception as e:
            logger.error(f"Configuration conflict resolution failed: {e}")
            return ConflictResolutionResult(
                conflicts_found=0,
                conflicts_resolved=0,
                conflicts_unresolved=0,
                resolution_log=[],
                resolved_configuration=global_config,
                warnings=[],
                errors=[f"Conflict resolution failed: {e}"]
            )
    
    def _detect_all_conflicts(self,
                            global_config: IntegratedConfiguration,
                            case_config: Optional[CaseSpecificConfig] = None,
                            wing_config: Optional[Dict[str, Any]] = None,
                            pipeline_config: Optional[Dict[str, Any]] = None) -> List[ConfigurationConflict]:
        """Detect all configuration conflicts"""
        conflicts = []
        
        # Detect semantic mapping conflicts
        conflicts.extend(self._detect_semantic_mapping_conflicts(
            global_config.semantic_mapping, case_config, wing_config, pipeline_config
        ))
        
        # Detect weighted scoring conflicts
        conflicts.extend(self._detect_weighted_scoring_conflicts(
            global_config.weighted_scoring, case_config, wing_config, pipeline_config
        ))
        
        # Detect progress tracking conflicts
        conflicts.extend(self._detect_progress_tracking_conflicts(
            global_config.progress_tracking, case_config, wing_config, pipeline_config
        ))
        
        # Detect engine selection conflicts
        conflicts.extend(self._detect_engine_selection_conflicts(
            global_config.engine_selection, case_config, wing_config, pipeline_config
        ))
        
        return conflicts
    
    def _detect_semantic_mapping_conflicts(self,
                                         global_semantic: SemanticMappingConfig,
                                         case_config: Optional[CaseSpecificConfig] = None,
                                         wing_config: Optional[Dict[str, Any]] = None,
                                         pipeline_config: Optional[Dict[str, Any]] = None) -> List[ConfigurationConflict]:
        """Detect semantic mapping configuration conflicts"""
        conflicts = []
        
        # Check enabled state conflicts
        global_enabled = global_semantic.enabled
        case_enabled = None
        wing_enabled = None
        pipeline_enabled = None
        
        if case_config and case_config.use_case_specific_mappings:
            # Case-specific semantic mapping settings would override global
            case_enabled = True  # Implicit enabling when case-specific is used
        
        if wing_config and 'semantic_mapping' in wing_config:
            wing_enabled = wing_config['semantic_mapping'].get('enabled')
        
        if pipeline_config and 'semantic_mapping' in pipeline_config:
            pipeline_enabled = pipeline_config['semantic_mapping'].get('enabled')
        
        # Create conflict if there are different enabled states
        if any(v is not None and v != global_enabled for v in [case_enabled, wing_enabled, pipeline_enabled]):
            conflict = ConfigurationConflict(
                conflict_id=self._generate_conflict_id(),
                section="semantic_mapping",
                field="enabled",
                global_value=global_enabled,
                case_value=case_enabled,
                wing_value=wing_enabled,
                pipeline_value=pipeline_enabled,
                severity=ConflictSeverity.MEDIUM,
                description="Semantic mapping enabled state differs between configuration levels",
                suggested_resolution=ResolutionStrategy.CASE_SPECIFIC_PRECEDENCE
            )
            conflicts.append(conflict)
        
        # Check mappings path conflicts
        global_path = global_semantic.global_mappings_path
        case_path = None
        wing_path = None
        pipeline_path = None
        
        if case_config and case_config.semantic_mappings_path:
            case_path = case_config.semantic_mappings_path
        
        if wing_config and 'semantic_mapping' in wing_config:
            wing_path = wing_config['semantic_mapping'].get('mappings_path')
        
        if pipeline_config and 'semantic_mapping' in pipeline_config:
            pipeline_path = pipeline_config['semantic_mapping'].get('mappings_path')
        
        # Create conflict if there are different paths
        if any(v is not None and v != global_path for v in [case_path, wing_path, pipeline_path]):
            conflict = ConfigurationConflict(
                conflict_id=self._generate_conflict_id(),
                section="semantic_mapping",
                field="mappings_path",
                global_value=global_path,
                case_value=case_path,
                wing_value=wing_path,
                pipeline_value=pipeline_path,
                severity=ConflictSeverity.LOW,
                description="Semantic mappings file path differs between configuration levels",
                suggested_resolution=ResolutionStrategy.CASE_SPECIFIC_PRECEDENCE
            )
            conflicts.append(conflict)
        
        return conflicts
    
    def _detect_weighted_scoring_conflicts(self,
                                         global_scoring: WeightedScoringConfig,
                                         case_config: Optional[CaseSpecificConfig] = None,
                                         wing_config: Optional[Dict[str, Any]] = None,
                                         pipeline_config: Optional[Dict[str, Any]] = None) -> List[ConfigurationConflict]:
        """Detect weighted scoring configuration conflicts"""
        conflicts = []
        
        # Check enabled state conflicts
        global_enabled = global_scoring.enabled
        case_enabled = None
        wing_enabled = None
        pipeline_enabled = None
        
        if case_config and case_config.use_case_specific_scoring:
            case_enabled = True  # Implicit enabling when case-specific is used
        
        if wing_config and 'weighted_scoring' in wing_config:
            wing_enabled = wing_config['weighted_scoring'].get('enabled')
        
        if pipeline_config and 'weighted_scoring' in pipeline_config:
            pipeline_enabled = pipeline_config['weighted_scoring'].get('enabled')
        
        # Create conflict if there are different enabled states
        if any(v is not None and v != global_enabled for v in [case_enabled, wing_enabled, pipeline_enabled]):
            conflict = ConfigurationConflict(
                conflict_id=self._generate_conflict_id(),
                section="weighted_scoring",
                field="enabled",
                global_value=global_enabled,
                case_value=case_enabled,
                wing_value=wing_enabled,
                pipeline_value=pipeline_enabled,
                severity=ConflictSeverity.MEDIUM,
                description="Weighted scoring enabled state differs between configuration levels",
                suggested_resolution=ResolutionStrategy.CASE_SPECIFIC_PRECEDENCE
            )
            conflicts.append(conflict)
        
        # Check default weights conflicts
        global_weights = global_scoring.default_weights
        case_weights = None
        wing_weights = None
        pipeline_weights = None
        
        if case_config and case_config.scoring_weights_path:
            # Case-specific weights would be loaded from file
            case_weights = "case_specific_file"
        
        if wing_config and 'weighted_scoring' in wing_config:
            wing_weights = wing_config['weighted_scoring'].get('default_weights')
        
        if pipeline_config and 'weighted_scoring' in pipeline_config:
            pipeline_weights = pipeline_config['weighted_scoring'].get('default_weights')
        
        # Check for weight conflicts for each artifact type
        all_artifact_types = set(global_weights.keys())
        if wing_weights:
            all_artifact_types.update(wing_weights.keys())
        if pipeline_weights:
            all_artifact_types.update(pipeline_weights.keys())
        
        for artifact_type in all_artifact_types:
            global_weight = global_weights.get(artifact_type, 0.0)
            wing_weight = wing_weights.get(artifact_type) if wing_weights else None
            pipeline_weight = pipeline_weights.get(artifact_type) if pipeline_weights else None
            
            if any(v is not None and v != global_weight for v in [wing_weight, pipeline_weight]):
                conflict = ConfigurationConflict(
                    conflict_id=self._generate_conflict_id(),
                    section="weighted_scoring",
                    field=f"default_weights.{artifact_type}",
                    global_value=global_weight,
                    case_value=case_weights,
                    wing_value=wing_weight,
                    pipeline_value=pipeline_weight,
                    severity=ConflictSeverity.LOW,
                    description=f"Weight for {artifact_type} differs between configuration levels",
                    suggested_resolution=ResolutionStrategy.WING_PRECEDENCE  # Wing weights are more specific
                )
                conflicts.append(conflict)
        
        return conflicts
    
    def _detect_progress_tracking_conflicts(self,
                                          global_progress: ProgressTrackingConfig,
                                          case_config: Optional[CaseSpecificConfig] = None,
                                          wing_config: Optional[Dict[str, Any]] = None,
                                          pipeline_config: Optional[Dict[str, Any]] = None) -> List[ConfigurationConflict]:
        """Detect progress tracking configuration conflicts"""
        conflicts = []
        
        # Progress tracking conflicts are less common since they're mostly global settings
        # But we can check for wing/pipeline specific overrides
        
        if wing_config and 'progress_tracking' in wing_config:
            wing_progress = wing_config['progress_tracking']
            
            # Check update frequency conflicts
            global_freq = global_progress.update_frequency_ms
            wing_freq = wing_progress.get('update_frequency_ms')
            
            if wing_freq is not None and wing_freq != global_freq:
                conflict = ConfigurationConflict(
                    conflict_id=self._generate_conflict_id(),
                    section="progress_tracking",
                    field="update_frequency_ms",
                    global_value=global_freq,
                    wing_value=wing_freq,
                    severity=ConflictSeverity.LOW,
                    description="Progress update frequency differs between global and wing configuration",
                    suggested_resolution=ResolutionStrategy.WING_PRECEDENCE
                )
                conflicts.append(conflict)
        
        return conflicts
    
    def _detect_engine_selection_conflicts(self,
                                         global_engine: EngineSelectionConfig,
                                         case_config: Optional[CaseSpecificConfig] = None,
                                         wing_config: Optional[Dict[str, Any]] = None,
                                         pipeline_config: Optional[Dict[str, Any]] = None) -> List[ConfigurationConflict]:
        """Detect engine selection configuration conflicts"""
        conflicts = []
        
        # Check for pipeline-specific engine preferences
        if pipeline_config and 'engine_selection' in pipeline_config:
            pipeline_engine = pipeline_config['engine_selection']
            
            # Check default engine conflicts
            global_default = global_engine.default_engine
            pipeline_default = pipeline_engine.get('default_engine')
            
            if pipeline_default is not None and pipeline_default != global_default:
                conflict = ConfigurationConflict(
                    conflict_id=self._generate_conflict_id(),
                    section="engine_selection",
                    field="default_engine",
                    global_value=global_default,
                    pipeline_value=pipeline_default,
                    severity=ConflictSeverity.LOW,
                    description="Default engine differs between global and pipeline configuration",
                    suggested_resolution=ResolutionStrategy.PIPELINE_PRECEDENCE
                )
                conflicts.append(conflict)
        
        return conflicts
    
    def _resolve_conflicts(self,
                         global_config: IntegratedConfiguration,
                         conflicts: List[ConfigurationConflict],
                         case_config: Optional[CaseSpecificConfig] = None,
                         wing_config: Optional[Dict[str, Any]] = None,
                         pipeline_config: Optional[Dict[str, Any]] = None) -> Tuple[IntegratedConfiguration, List[str], List[str], List[str]]:
        """Resolve all detected conflicts"""
        resolved_config = IntegratedConfiguration(**asdict(global_config))
        resolution_log = []
        warnings = []
        errors = []
        
        for conflict in conflicts:
            try:
                # Apply resolution strategy
                strategy = conflict.suggested_resolution
                if strategy in self.resolution_strategies:
                    resolved_value, reason = self.resolution_strategies[strategy](conflict)
                    conflict.resolved_value = resolved_value
                    conflict.resolution_reason = reason
                    
                    # Apply resolved value to configuration
                    self._apply_resolved_value(resolved_config, conflict)
                    
                    resolution_log.append(
                        f"Resolved {conflict.section}.{conflict.field}: "
                        f"{conflict.global_value} -> {resolved_value} ({reason})"
                    )
                    
                    logger.info(f"Resolved conflict {conflict.conflict_id}: {reason}")
                    
                else:
                    errors.append(f"Unknown resolution strategy: {strategy}")
                    logger.error(f"Unknown resolution strategy for conflict {conflict.conflict_id}: {strategy}")
                    
            except Exception as e:
                error_msg = f"Failed to resolve conflict {conflict.conflict_id}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        return resolved_config, resolution_log, warnings, errors
    
    def _resolve_case_precedence(self, conflict: ConfigurationConflict) -> Tuple[Any, str]:
        """Resolve conflict using case-specific precedence"""
        if conflict.case_value is not None:
            return conflict.case_value, "Case-specific value takes precedence"
        elif conflict.wing_value is not None:
            return conflict.wing_value, "Wing-specific value takes precedence (no case value)"
        elif conflict.pipeline_value is not None:
            return conflict.pipeline_value, "Pipeline-specific value takes precedence (no case/wing value)"
        else:
            return conflict.global_value, "Global value used (no overrides)"
    
    def _resolve_wing_precedence(self, conflict: ConfigurationConflict) -> Tuple[Any, str]:
        """Resolve conflict using wing-specific precedence"""
        if conflict.wing_value is not None:
            return conflict.wing_value, "Wing-specific value takes precedence"
        elif conflict.case_value is not None:
            return conflict.case_value, "Case-specific value takes precedence (no wing value)"
        elif conflict.pipeline_value is not None:
            return conflict.pipeline_value, "Pipeline-specific value takes precedence (no wing/case value)"
        else:
            return conflict.global_value, "Global value used (no overrides)"
    
    def _resolve_pipeline_precedence(self, conflict: ConfigurationConflict) -> Tuple[Any, str]:
        """Resolve conflict using pipeline-specific precedence"""
        if conflict.pipeline_value is not None:
            return conflict.pipeline_value, "Pipeline-specific value takes precedence"
        elif conflict.case_value is not None:
            return conflict.case_value, "Case-specific value takes precedence (no pipeline value)"
        elif conflict.wing_value is not None:
            return conflict.wing_value, "Wing-specific value takes precedence (no pipeline/case value)"
        else:
            return conflict.global_value, "Global value used (no overrides)"
    
    def _resolve_global_precedence(self, conflict: ConfigurationConflict) -> Tuple[Any, str]:
        """Resolve conflict using global precedence"""
        return conflict.global_value, "Global value takes precedence (forced)"
    
    def _resolve_merge_additive(self, conflict: ConfigurationConflict) -> Tuple[Any, str]:
        """Resolve conflict by merging values additively"""
        # This is mainly for dictionary/list values
        if isinstance(conflict.global_value, dict):
            merged = conflict.global_value.copy()
            
            if isinstance(conflict.pipeline_value, dict):
                merged.update(conflict.pipeline_value)
            
            if isinstance(conflict.wing_value, dict):
                merged.update(conflict.wing_value)
            
            if isinstance(conflict.case_value, dict):
                merged.update(conflict.case_value)
            
            return merged, "Values merged additively (case > wing > pipeline > global)"
        
        # For non-dict values, fall back to case precedence
        return self._resolve_case_precedence(conflict)
    
    def _resolve_merge_override(self, conflict: ConfigurationConflict) -> Tuple[Any, str]:
        """Resolve conflict by merging with override"""
        # Similar to additive but with complete override at each level
        return self._resolve_case_precedence(conflict)
    
    def _apply_resolved_value(self, config: IntegratedConfiguration, conflict: ConfigurationConflict):
        """Apply resolved value to configuration object"""
        try:
            section_name = conflict.section
            field_path = conflict.field.split('.')
            
            # Get the section object
            section_obj = getattr(config, section_name)
            
            # Navigate to the field
            obj = section_obj
            for part in field_path[:-1]:
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                elif isinstance(obj, dict):
                    obj = obj[part]
                else:
                    logger.warning(f"Cannot navigate to field {conflict.field} in section {section_name}")
                    return
            
            # Set the final field value
            final_field = field_path[-1]
            if hasattr(obj, final_field):
                setattr(obj, final_field, conflict.resolved_value)
            elif isinstance(obj, dict):
                obj[final_field] = conflict.resolved_value
            else:
                logger.warning(f"Cannot set field {final_field} in {type(obj)}")
                
        except Exception as e:
            logger.error(f"Failed to apply resolved value for conflict {conflict.conflict_id}: {e}")
    
    def _generate_conflict_id(self) -> str:
        """Generate unique conflict ID"""
        self.conflict_counter += 1
        return f"conflict_{self.conflict_counter:04d}"
    
    def log_configuration_decisions(self, conflicts: List[ConfigurationConflict], log_level: str = "INFO"):
        """
        Log configuration decisions for audit purposes.
        
        Args:
            conflicts: List of resolved conflicts
            log_level: Logging level to use
        """
        if not conflicts:
            logger.info("No configuration conflicts to log")
            return
        
        logger.info("="*60)
        logger.info("CONFIGURATION CONFLICT RESOLUTION LOG")
        logger.info("="*60)
        
        for conflict in conflicts:
            logger.info(f"Conflict ID: {conflict.conflict_id}")
            logger.info(f"Section: {conflict.section}")
            logger.info(f"Field: {conflict.field}")
            logger.info(f"Severity: {conflict.severity.value}")
            logger.info(f"Description: {conflict.description}")
            
            logger.info("Values:")
            logger.info(f"  Global: {conflict.global_value}")
            if conflict.pipeline_value is not None:
                logger.info(f"  Pipeline: {conflict.pipeline_value}")
            if conflict.wing_value is not None:
                logger.info(f"  Wing: {conflict.wing_value}")
            if conflict.case_value is not None:
                logger.info(f"  Case: {conflict.case_value}")
            
            logger.info(f"Resolution: {conflict.resolved_value}")
            logger.info(f"Reason: {conflict.resolution_reason}")
            logger.info("-" * 40)
        
        logger.info("="*60)
    
    def get_conflict_summary(self, conflicts: List[ConfigurationConflict]) -> Dict[str, Any]:
        """
        Get summary of configuration conflicts.
        
        Args:
            conflicts: List of conflicts
            
        Returns:
            Dictionary with conflict summary
        """
        summary = {
            'total_conflicts': len(conflicts),
            'by_severity': {
                'low': len([c for c in conflicts if c.severity == ConflictSeverity.LOW]),
                'medium': len([c for c in conflicts if c.severity == ConflictSeverity.MEDIUM]),
                'high': len([c for c in conflicts if c.severity == ConflictSeverity.HIGH]),
                'critical': len([c for c in conflicts if c.severity == ConflictSeverity.CRITICAL])
            },
            'by_section': {},
            'resolution_strategies': {},
            'resolved_count': len([c for c in conflicts if c.resolved_value is not None]),
            'unresolved_count': len([c for c in conflicts if c.resolved_value is None])
        }
        
        # Count by section
        for conflict in conflicts:
            section = conflict.section
            if section not in summary['by_section']:
                summary['by_section'][section] = 0
            summary['by_section'][section] += 1
        
        # Count by resolution strategy
        for conflict in conflicts:
            strategy = conflict.suggested_resolution.value
            if strategy not in summary['resolution_strategies']:
                summary['resolution_strategies'][strategy] = 0
            summary['resolution_strategies'][strategy] += 1
        
        return summary