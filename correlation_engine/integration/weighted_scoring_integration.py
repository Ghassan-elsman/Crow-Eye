"""
Weighted Scoring Integration Layer

Provides integration between the WeightedScoringEngine and correlation engines.
Handles case-specific configurations, scoring validation, and conflict resolution.
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import json

from ..engine.weighted_scoring import WeightedScoringEngine
from .integration_error_handler import IntegrationErrorHandler, FallbackStrategy
from .integration_monitor import IntegrationMonitor
from .interfaces import IScoringIntegration, IntegrationStatistics

logger = logging.getLogger(__name__)


@dataclass
class ScoringStats:
    """Statistics for weighted scoring operations"""
    total_matches_scored: int = 0
    scores_calculated: int = 0
    fallback_to_simple_count: int = 0
    configuration_errors: int = 0
    validation_failures: int = 0
    case_specific_configs_used: int = 0
    global_configs_used: int = 0
    conflict_resolutions: int = 0
    average_score: float = 0.0
    highest_score: float = 0.0
    lowest_score: float = 0.0


@dataclass
class ScoringConfiguration:
    """Configuration for weighted scoring"""
    enabled: bool = True
    score_interpretation: Dict[str, Dict[str, Any]] = None
    default_weights: Dict[str, float] = None
    tier_definitions: Dict[int, str] = None
    validation_rules: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.score_interpretation is None:
            self.score_interpretation = {
                "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
                "probable": {"min": 0.5, "label": "Probable Match"},
                "weak": {"min": 0.2, "label": "Weak Evidence"},
                "minimal": {"min": 0.0, "label": "Minimal Evidence"}
            }
        
        if self.default_weights is None:
            self.default_weights = {
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
        
        if self.tier_definitions is None:
            self.tier_definitions = {
                1: "Primary Evidence",
                2: "Supporting Evidence", 
                3: "Contextual Evidence",
                4: "Background Evidence"
            }
        
        if self.validation_rules is None:
            self.validation_rules = {
                "max_weight": 1.0,
                "min_weight": 0.0,
                "max_tier": 4,
                "min_tier": 1,
                "require_positive_weights": True,
                "allow_zero_weights": True
            }


class WeightedScoringIntegration(IScoringIntegration):
    """
    Integration layer for weighted scoring system.
    
    Provides bridge between WeightedScoringEngine and correlation engines,
    handling case-specific configurations and scoring validation.
    
    Implements IScoringIntegration interface for dependency injection and testing.
    """
    
    def __init__(self, config_manager=None, error_handler: IntegrationErrorHandler = None,
                 monitor: IntegrationMonitor = None):
        """
        Initialize weighted scoring integration.
        
        Args:
            config_manager: Configuration manager for loading settings
            error_handler: Error handler for graceful degradation
            monitor: Integration monitor for performance tracking
        """
        self.scoring_engine = WeightedScoringEngine()
        self.config_manager = config_manager
        self.current_case_id: Optional[str] = None
        self.case_specific_enabled = False
        self.stats = ScoringStats()
        self.global_config = ScoringConfiguration()
        self.case_specific_config: Optional[ScoringConfiguration] = None
        
        # Error handling and monitoring
        self.error_handler = error_handler or IntegrationErrorHandler()
        self.monitor = monitor or IntegrationMonitor()
        
        # Load global configuration
        self._load_global_configuration()
    
    def _load_global_configuration(self):
        """Load global weighted scoring configuration"""
        operation_id = self.monitor.start_operation("weighted_scoring", "load_global_config")
        
        try:
            if self.config_manager:
                config = self.config_manager.get_weighted_scoring_config()
                if config:
                    self.global_config = self._parse_scoring_configuration(config)
                    logger.info("Loaded global weighted scoring configuration")
                    
                    # Check if case-specific scoring is enabled
                    case_config = config.get('case_specific', {})
                    self.case_specific_enabled = case_config.get('enabled', False)
            
            self.monitor.complete_operation(operation_id, success=True)
                    
        except Exception as e:
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
            # Handle error with graceful degradation
            fallback_result = self.error_handler.handle_weighted_scoring_error(
                e, context={'operation': 'load_global_configuration'}
            )
            
            if fallback_result.success:
                logger.warning(f"Using fallback for global configuration: {fallback_result.message}")
            else:
                logger.error(f"Failed to load global weighted scoring configuration: {e}")
                # Continue with default configuration
                self.global_config = ScoringConfiguration()
    
    def _parse_scoring_configuration(self, config_dict: Dict[str, Any]) -> ScoringConfiguration:
        """
        Parse configuration dictionary into ScoringConfiguration object.
        
        Args:
            config_dict: Configuration dictionary
            
        Returns:
            ScoringConfiguration object
        """
        return ScoringConfiguration(
            enabled=config_dict.get('enabled', True),
            score_interpretation=config_dict.get('score_interpretation', {}),
            default_weights=config_dict.get('default_weights', {}),
            tier_definitions=config_dict.get('tier_definitions', {}),
            validation_rules=config_dict.get('validation_rules', {})
        )
    
    def load_case_specific_scoring_weights(self, case_id: str) -> bool:
        """
        Load case-specific scoring weights and configuration.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case-specific configuration was loaded, False otherwise
        """
        if not self.case_specific_enabled:
            return False
        
        try:
            self.current_case_id = case_id
            
            if self.config_manager:
                config = self.config_manager.get_weighted_scoring_config()
                case_config = config.get('case_specific', {})
                storage_path_template = case_config.get('storage_path', 'cases/{case_id}/scoring_weights.json')
                
                # Replace case_id placeholder
                storage_path = storage_path_template.format(case_id=case_id)
                case_config_path = Path(storage_path)
                
                if case_config_path.exists():
                    # Load case-specific configuration
                    with open(case_config_path, 'r') as f:
                        case_config_data = json.load(f)
                    
                    self.case_specific_config = self._parse_scoring_configuration(case_config_data)
                    logger.info(f"Loaded case-specific scoring configuration for case {case_id}")
                    return True
                else:
                    logger.info(f"No case-specific scoring configuration found for case {case_id}")
            
        except Exception as e:
            logger.error(f"Failed to load case-specific scoring configuration for case {case_id}: {e}")
        
        return False
    
    def get_scoring_configuration(self, case_id: Optional[str] = None) -> ScoringConfiguration:
        """
        Get effective scoring configuration (case-specific overrides global).
        
        Args:
            case_id: Optional case ID to load case-specific config
            
        Returns:
            Effective scoring configuration
        """
        # Load case-specific config if needed
        if case_id and case_id != self.current_case_id:
            self.load_case_specific_scoring_weights(case_id)
        
        # Return case-specific config if available, otherwise global
        if self.case_specific_config:
            return self._merge_configurations(self.global_config, self.case_specific_config)
        else:
            return self.global_config
    
    def _merge_configurations(self, 
                            global_config: ScoringConfiguration, 
                            case_config: ScoringConfiguration) -> ScoringConfiguration:
        """
        Merge global and case-specific configurations with conflict resolution.
        
        Args:
            global_config: Global configuration
            case_config: Case-specific configuration
            
        Returns:
            Merged configuration with case-specific taking precedence
        """
        merged_config = ScoringConfiguration()
        
        # Case-specific settings take precedence
        merged_config.enabled = case_config.enabled if case_config.enabled is not None else global_config.enabled
        
        # Merge score interpretation (case-specific overrides global)
        merged_config.score_interpretation = global_config.score_interpretation.copy()
        if case_config.score_interpretation:
            merged_config.score_interpretation.update(case_config.score_interpretation)
            self.stats.conflict_resolutions += len(case_config.score_interpretation)
        
        # Merge default weights (case-specific overrides global)
        merged_config.default_weights = global_config.default_weights.copy()
        if case_config.default_weights:
            merged_config.default_weights.update(case_config.default_weights)
            self.stats.conflict_resolutions += len(case_config.default_weights)
        
        # Merge tier definitions (case-specific overrides global)
        merged_config.tier_definitions = global_config.tier_definitions.copy()
        if case_config.tier_definitions:
            merged_config.tier_definitions.update(case_config.tier_definitions)
        
        # Merge validation rules (case-specific overrides global)
        merged_config.validation_rules = global_config.validation_rules.copy()
        if case_config.validation_rules:
            merged_config.validation_rules.update(case_config.validation_rules)
        
        logger.info(f"Merged configurations with {self.stats.conflict_resolutions} conflict resolutions")
        return merged_config
    
    def calculate_match_scores(self, 
                             match_records: Dict[str, Dict],
                             wing_config: Any,
                             case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate weighted scores for correlation matches with configuration validation.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing_config: Wing configuration with weights
            case_id: Optional case ID for case-specific configuration
            
        Returns:
            Dictionary with score, interpretation, and breakdown
        """
        match_id = f"match_{self.stats.total_matches_scored + 1}"
        
        operation_id = self.monitor.start_operation(
            "weighted_scoring",
            "calculate_match_scores",
            context={'match_id': match_id, 'case_id': case_id},
            input_size=len(match_records)
        )
        
        start_time = time.time()
        
        try:
            # Get effective configuration
            effective_config = self.get_scoring_configuration(case_id)
            
            # Validate wing configuration
            validation_result = self.validate_scoring_configuration(wing_config, effective_config)
            if not validation_result['valid']:
                logger.warning(f"Wing configuration validation failed for {match_id}: {validation_result['errors']}")
                self.stats.validation_failures += 1
                
                # Apply fixes if possible
                wing_config = self._apply_configuration_fixes(wing_config, validation_result['fixes'])
                logger.info(f"Applied {len(validation_result['fixes'])} configuration fixes for {match_id}")
            
            # Check if weighted scoring is enabled
            # Default use_weighted_scoring to True when not explicitly set, but respect explicit False
            use_weighted_scoring = getattr(wing_config, 'use_weighted_scoring', True)
            
            if not effective_config.enabled or use_weighted_scoring is False:
                # Fall back to simple count-based scoring
                logger.debug(f"Falling back to simple count-based scoring for {match_id}")
                self.stats.fallback_to_simple_count += 1
                result = self._calculate_simple_score(match_records, wing_config)
                
                # Log the fallback calculation
                self.log_scoring_calculation(match_id, result, wing_config, case_id)
                
                execution_time_ms = (time.time() - start_time) * 1000
                self.monitor.complete_operation(operation_id, success=True)
                self.monitor.record_weighted_scoring_metrics(
                    operation_name="calculate_match_scores_fallback",
                    matches_scored=1,
                    scores_calculated=1,
                    execution_time_ms=execution_time_ms,
                    average_score=result.get('score', 0)
                )
                
                return result
            
            # Apply case-specific weights to wing configuration if needed
            wing_config = self._apply_case_specific_weights(wing_config, effective_config)
            
            # Use the existing WeightedScoringEngine
            result = self.scoring_engine.calculate_match_score(match_records, wing_config)
            
            # Add scoring mode indicator
            result['scoring_mode'] = 'weighted'
            
            # Enhance result with interpretation
            score = result.get('score', 0.0)
            interpretation_info = self.interpret_score(score, case_id)
            
            # Update result with enhanced interpretation
            result['interpretation'] = interpretation_info['label']
            result['interpretation_details'] = interpretation_info
            result['tier'] = interpretation_info['tier']
            result['confidence_percentage'] = interpretation_info['confidence_percentage']
            result['description'] = interpretation_info['description']
            
            # Update statistics
            self.stats.total_matches_scored += 1
            self.stats.scores_calculated += 1
            
            if score > self.stats.highest_score:
                self.stats.highest_score = score
            if self.stats.lowest_score == 0.0 or score < self.stats.lowest_score:
                self.stats.lowest_score = score
            
            # Update average score
            if self.stats.scores_calculated > 0:
                self.stats.average_score = (
                    (self.stats.average_score * (self.stats.scores_calculated - 1) + score) / 
                    self.stats.scores_calculated
                )
            
            # Track configuration usage
            if self.case_specific_config:
                self.stats.case_specific_configs_used += 1
            else:
                self.stats.global_configs_used += 1
            
            # Log the successful calculation
            self.log_scoring_calculation(match_id, result, wing_config, case_id)
            
            # Record performance metrics
            execution_time_ms = (time.time() - start_time) * 1000
            self.monitor.record_weighted_scoring_metrics(
                operation_name="calculate_match_scores",
                matches_scored=1,
                scores_calculated=1,
                execution_time_ms=execution_time_ms,
                average_score=score
            )
            
            self.monitor.complete_operation(operation_id, success=True)
            
            logger.debug(f"Weighted scoring completed for {match_id}: score={score:.3f}, "
                        f"interpretation={interpretation_info['label']}")
            
            return result
            
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
            logger.error(f"Failed to calculate weighted scores for {match_id}: {e}")
            self.stats.configuration_errors += 1
            
            # Handle error with graceful degradation
            fallback_result = self.error_handler.handle_weighted_scoring_error(
                e, context={'operation': 'calculate_match_scores', 'match_id': match_id}
            )
            
            if fallback_result.success and fallback_result.result:
                # Use fallback scorer
                logger.info(f"Using fallback scoring for {match_id}: {fallback_result.message}")
                result = fallback_result.result.calculate_match_score(match_records, wing_config)
            else:
                # Fall back to simple scoring
                logger.info(f"Falling back to simple count-based scoring for {match_id} due to error")
                self.stats.fallback_to_simple_count += 1
                result = self._calculate_simple_score(match_records, wing_config)
            
            # Add error information to result
            result['error'] = str(e)
            result['scoring_mode'] = 'error_fallback'
            
            # Record fallback metrics
            self.monitor.record_weighted_scoring_metrics(
                operation_name="calculate_match_scores_error_fallback",
                matches_scored=1,
                scores_calculated=1,
                execution_time_ms=execution_time_ms,
                average_score=result.get('score', 0)
            )
            
            # Log the fallback calculation
            self.log_scoring_calculation(match_id, result, wing_config, case_id)
            
            return result
            
            # Update average score
            if self.stats.scores_calculated > 0:
                self.stats.average_score = (
                    (self.stats.average_score * (self.stats.scores_calculated - 1) + score) / 
                    self.stats.scores_calculated
                )
            
            # Track configuration usage
            if self.case_specific_config:
                self.stats.case_specific_configs_used += 1
            else:
                self.stats.global_configs_used += 1
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to calculate weighted scores: {e}")
            self.stats.configuration_errors += 1
            
            # Fall back to simple scoring
            self.stats.fallback_to_simple_count += 1
            return self._calculate_simple_score(match_records, wing_config)
    
    def _calculate_simple_score(self, 
                              match_records: Dict[str, Dict],
                              wing_config: Any) -> Dict[str, Any]:
        """
        Calculate simple count-based score as fallback.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing_config: Wing configuration
            
        Returns:
            Dictionary with simple score information
        """
        feathers = getattr(wing_config, 'feathers', [])
        total_feathers = len(feathers)
        matched_feathers = len(match_records)
        
        return {
            'score': matched_feathers,
            'interpretation': f'{matched_feathers}/{total_feathers} Matches',
            'breakdown': {
                feather_id: {
                    'matched': feather_id in match_records,
                    'weight': 1.0,
                    'contribution': 1.0 if feather_id in match_records else 0.0,
                    'tier': 1,
                    'tier_name': 'Standard'
                }
                for feather_spec in feathers
                for feather_id in [getattr(feather_spec, 'feather_id', '') if hasattr(feather_spec, 'feather_id') 
                                 else feather_spec.get('feather_id', '')]
            },
            'matched_feathers': matched_feathers,
            'total_feathers': total_feathers,
            'scoring_mode': 'simple_count'
        }
    
    def _apply_case_specific_weights(self, 
                                   wing_config: Any,
                                   effective_config: ScoringConfiguration) -> Any:
        """
        Apply weight precedence logic: wing > case > global > default.
        
        This method implements the correct weight precedence order:
        1. Wing-specific weight (if > 0, use it)
        2. Case-specific weight (if available)
        3. Global weight (if available)
        4. Default fallback weight (0.1)
        
        Args:
            wing_config: Wing configuration to modify
            effective_config: Effective scoring configuration
            
        Returns:
            Modified wing configuration with correct weight precedence
        """
        if not effective_config.default_weights:
            return wing_config
        
        # Apply weight precedence to feathers
        feathers = getattr(wing_config, 'feathers', [])
        
        for feather_spec in feathers:
            if isinstance(feather_spec, dict):
                artifact_type = feather_spec.get('artifact_type', '')
                wing_weight = feather_spec.get('weight', 0.0)
                feather_id = feather_spec.get('feather_id', 'unknown')
            else:
                artifact_type = getattr(feather_spec, 'artifact_type', '')
                wing_weight = getattr(feather_spec, 'weight', 0.0)
                feather_id = getattr(feather_spec, 'feather_id', 'unknown')
            
            # Determine final weight using precedence order
            final_weight = None
            weight_source = None
            
            # 1. Check wing weight first (if explicitly set and > 0)
            if wing_weight > 0.0:
                final_weight = wing_weight
                weight_source = 'wing'
            
            # 2. Check case-specific weight
            elif self.case_specific_config and artifact_type in self.case_specific_config.default_weights:
                final_weight = self.case_specific_config.default_weights[artifact_type]
                weight_source = 'case'
            
            # 3. Check global weight
            elif artifact_type in effective_config.default_weights:
                final_weight = effective_config.default_weights[artifact_type]
                weight_source = 'global'
            
            # 4. Use default fallback
            else:
                final_weight = 0.1
                weight_source = 'default'
            
            # Apply the final weight
            if isinstance(feather_spec, dict):
                feather_spec['weight'] = final_weight
            else:
                feather_spec.weight = final_weight
            
            # Log weight decision for debugging
            logger.debug(f"Weight precedence for {feather_id} ({artifact_type}): "
                        f"{final_weight:.3f} from {weight_source} "
                        f"(wing={wing_weight:.3f}, case={self.case_specific_config.default_weights.get(artifact_type, 'N/A') if self.case_specific_config else 'N/A'}, "
                        f"global={effective_config.default_weights.get(artifact_type, 'N/A')})")
        
        return wing_config
    
    def validate_scoring_configuration(self, 
                                     wing_config: Any,
                                     scoring_config: ScoringConfiguration) -> Dict[str, Any]:
        """
        Validate wing scoring configuration against rules.
        
        Args:
            wing_config: Wing configuration to validate
            scoring_config: Scoring configuration with validation rules
            
        Returns:
            Dictionary with validation results and suggested fixes
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'fixes': []
        }
        
        rules = scoring_config.validation_rules
        feathers = getattr(wing_config, 'feathers', [])
        
        for i, feather_spec in enumerate(feathers):
            # Extract weight and tier
            if isinstance(feather_spec, dict):
                weight = feather_spec.get('weight', 0.0)
                tier = feather_spec.get('tier', 1)
                feather_id = feather_spec.get('feather_id', f'feather_{i}')
            else:
                weight = getattr(feather_spec, 'weight', 0.0)
                tier = getattr(feather_spec, 'tier', 1)
                feather_id = getattr(feather_spec, 'feather_id', f'feather_{i}')
            
            # Validate weight range
            max_weight = rules.get('max_weight', 1.0)
            min_weight = rules.get('min_weight', 0.0)
            
            if weight > max_weight:
                validation_result['valid'] = False
                validation_result['errors'].append(f"Feather {feather_id} weight {weight} exceeds maximum {max_weight}")
                validation_result['fixes'].append({
                    'feather_index': i,
                    'field': 'weight',
                    'current_value': weight,
                    'suggested_value': max_weight,
                    'reason': f'Weight exceeds maximum allowed value of {max_weight}'
                })
            
            if weight < min_weight:
                if not (rules.get('allow_zero_weights', True) and weight == 0.0):
                    validation_result['valid'] = False
                    validation_result['errors'].append(f"Feather {feather_id} weight {weight} below minimum {min_weight}")
                    validation_result['fixes'].append({
                        'feather_index': i,
                        'field': 'weight',
                        'current_value': weight,
                        'suggested_value': min_weight,
                        'reason': f'Weight below minimum allowed value of {min_weight}'
                    })
            
            # Validate tier range
            max_tier = rules.get('max_tier', 4)
            min_tier = rules.get('min_tier', 1)
            
            if tier > max_tier:
                validation_result['valid'] = False
                validation_result['errors'].append(f"Feather {feather_id} tier {tier} exceeds maximum {max_tier}")
                validation_result['fixes'].append({
                    'feather_index': i,
                    'field': 'tier',
                    'current_value': tier,
                    'suggested_value': max_tier,
                    'reason': f'Tier exceeds maximum allowed value of {max_tier}'
                })
            
            if tier < min_tier:
                validation_result['valid'] = False
                validation_result['errors'].append(f"Feather {feather_id} tier {tier} below minimum {min_tier}")
                validation_result['fixes'].append({
                    'feather_index': i,
                    'field': 'tier',
                    'current_value': tier,
                    'suggested_value': min_tier,
                    'reason': f'Tier below minimum allowed value of {min_tier}'
                })
            
            # Check for positive weights requirement
            if rules.get('require_positive_weights', True) and weight <= 0.0:
                validation_result['warnings'].append(f"Feather {feather_id} has zero or negative weight")
        
        return validation_result
    
    def _apply_configuration_fixes(self, 
                                 wing_config: Any,
                                 fixes: List[Dict[str, Any]]) -> Any:
        """
        Apply suggested fixes to wing configuration.
        
        Args:
            wing_config: Wing configuration to fix
            fixes: List of suggested fixes
            
        Returns:
            Fixed wing configuration
        """
        feathers = getattr(wing_config, 'feathers', [])
        
        for fix in fixes:
            feather_index = fix['feather_index']
            field = fix['field']
            suggested_value = fix['suggested_value']
            
            if feather_index < len(feathers):
                feather_spec = feathers[feather_index]
                
                if isinstance(feather_spec, dict):
                    feather_spec[field] = suggested_value
                else:
                    setattr(feather_spec, field, suggested_value)
                
                logger.info(f"Applied fix: Set {field} to {suggested_value} for feather {feather_index}")
        
        return wing_config
    
    def save_case_specific_scoring_weights(self, 
                                         case_id: str,
                                         scoring_config: ScoringConfiguration) -> bool:
        """
        Save case-specific scoring configuration.
        
        Args:
            case_id: Case identifier
            scoring_config: Scoring configuration to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not self.case_specific_enabled:
            logger.warning("Case-specific scoring is not enabled")
            return False
        
        try:
            if self.config_manager:
                config = self.config_manager.get_weighted_scoring_config()
                case_config = config.get('case_specific', {})
                storage_path_template = case_config.get('storage_path', 'cases/{case_id}/scoring_weights.json')
                
                # Replace case_id placeholder
                storage_path = storage_path_template.format(case_id=case_id)
                case_config_path = Path(storage_path)
                
                # Ensure directory exists
                case_config_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Convert to dictionary and save
                config_dict = {
                    'enabled': scoring_config.enabled,
                    'score_interpretation': scoring_config.score_interpretation,
                    'default_weights': scoring_config.default_weights,
                    'tier_definitions': scoring_config.tier_definitions,
                    'validation_rules': scoring_config.validation_rules
                }
                
                with open(case_config_path, 'w') as f:
                    json.dump(config_dict, f, indent=2)
                
                logger.info(f"Saved case-specific scoring configuration for case {case_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save case-specific scoring configuration for case {case_id}: {e}")
        
        return False
    
    def get_scoring_statistics(self) -> ScoringStats:
        """
        Get current scoring statistics.
        
        Returns:
            ScoringStats object with current statistics
        """
        return self.stats
    
    def is_enabled(self) -> bool:
        """
        Check if weighted scoring is enabled.
        
        Returns:
            True if weighted scoring is enabled, False otherwise
        """
        effective_config = self.get_scoring_configuration()
        return effective_config.enabled
    
    def get_score_interpretation_labels(self, case_id: Optional[str] = None) -> Dict[str, str]:
        """
        Get score interpretation labels for UI display.
        
        Args:
            case_id: Optional case ID for case-specific labels
            
        Returns:
            Dictionary mapping score ranges to labels
        """
        effective_config = self.get_scoring_configuration(case_id)
        
        labels = {}
        for level, config in effective_config.score_interpretation.items():
            min_score = config.get('min', 0.0)
            label = config.get('label', level)
            labels[f"{min_score}+"] = label
        
        return labels
    
    def resolve_configuration_conflicts(self, 
                                      global_config: Dict[str, Any],
                                      case_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve conflicts between global and case-specific configurations.
        
        Args:
            global_config: Global configuration
            case_config: Case-specific configuration
            
        Returns:
            Resolved configuration with conflict resolution log
        """
        conflicts = []
        resolved_config = global_config.copy()
        
        # Check for conflicts and resolve them
        for key, case_value in case_config.items():
            if key in global_config:
                global_value = global_config[key]
                
                if global_value != case_value:
                    conflicts.append({
                        'field': key,
                        'global_value': global_value,
                        'case_value': case_value,
                        'resolution': 'case_specific_takes_precedence'
                    })
                    
                    resolved_config[key] = case_value
            else:
                resolved_config[key] = case_value
        
        # Log conflicts
        if conflicts:
            logger.info(f"Resolved {len(conflicts)} configuration conflicts:")
            for conflict in conflicts:
                logger.info(f"  {conflict['field']}: {conflict['global_value']} -> {conflict['case_value']}")
        
        return {
            'config': resolved_config,
            'conflicts': conflicts,
            'resolution_strategy': 'case_specific_precedence'
        }
    
    def _log_scoring_statistics(self):
        """Log comprehensive weighted scoring statistics"""
        if self.stats.total_matches_scored > 0:
            success_rate = (self.stats.scores_calculated / self.stats.total_matches_scored) * 100
            
            logger.info("="*60)
            logger.info("WEIGHTED SCORING STATISTICS")
            logger.info("="*60)
            logger.info(f"Matches processed: {self.stats.total_matches_scored}")
            logger.info(f"Successful calculations: {self.stats.scores_calculated}")
            logger.info(f"Success rate: {success_rate:.1f}%")
            logger.info(f"Fallbacks to simple count: {self.stats.fallback_to_simple_count}")
            logger.info(f"Configuration errors: {self.stats.configuration_errors}")
            logger.info(f"Validation failures: {self.stats.validation_failures}")
            
            # Score distribution
            logger.info(f"Score statistics:")
            logger.info(f"  Average score: {self.stats.average_score:.3f}")
            logger.info(f"  Highest score: {self.stats.highest_score:.3f}")
            logger.info(f"  Lowest score: {self.stats.lowest_score:.3f}")
            
            # Configuration usage
            if self.case_specific_enabled:
                total_configs = self.stats.global_configs_used + self.stats.case_specific_configs_used
                if total_configs > 0:
                    global_percentage = (self.stats.global_configs_used / total_configs) * 100
                    case_percentage = (self.stats.case_specific_configs_used / total_configs) * 100
                    
                    logger.info(f"Configuration usage:")
                    logger.info(f"  Global configs: {self.stats.global_configs_used} ({global_percentage:.1f}%)")
                    logger.info(f"  Case-specific configs: {self.stats.case_specific_configs_used} ({case_percentage:.1f}%)")
                    logger.info(f"  Conflict resolutions: {self.stats.conflict_resolutions}")
            
            # Score interpretation breakdown
            self._log_score_interpretation_breakdown()
            
            logger.info("="*60)
        else:
            logger.info("No weighted scoring statistics available (no matches processed)")
    
    def _log_score_interpretation_breakdown(self):
        """Log breakdown of score interpretations"""
        try:
            effective_config = self.get_scoring_configuration()
            
            logger.info("Score interpretation thresholds:")
            
            # Sort interpretations by minimum score (descending)
            sorted_interpretations = sorted(
                effective_config.score_interpretation.items(),
                key=lambda x: x[1].get('min', 0.0),
                reverse=True
            )
            
            for level, config in sorted_interpretations:
                min_score = config.get('min', 0.0)
                label = config.get('label', level.title())
                logger.info(f"  {label}: {min_score:.2f}+")
            
        except Exception as e:
            logger.warning(f"Failed to log score interpretation breakdown: {e}")
    
    def interpret_score(self, score: float, case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Interpret a score value using configured thresholds.
        
        Args:
            score: Score value to interpret
            case_id: Optional case ID for case-specific interpretation
            
        Returns:
            Dictionary with interpretation information
        """
        try:
            effective_config = self.get_scoring_configuration(case_id)
            
            # Find the appropriate interpretation level
            best_match = None
            best_min_score = -1
            
            for level, config in effective_config.score_interpretation.items():
                min_score = config.get('min', 0.0)
                if score >= min_score and min_score > best_min_score:
                    best_match = level
                    best_min_score = min_score
            
            if best_match:
                interpretation_config = effective_config.score_interpretation[best_match]
                return {
                    'level': best_match,
                    'label': interpretation_config.get('label', best_match.title()),
                    'min_threshold': interpretation_config.get('min', 0.0),
                    'score': score,
                    'confidence_percentage': min(100.0, (score / 1.0) * 100),  # Assuming max score is 1.0
                    'tier': self._get_score_tier(score, effective_config),
                    'description': self._generate_score_description(score, best_match, interpretation_config)
                }
            else:
                # Fallback interpretation
                return {
                    'level': 'unknown',
                    'label': 'Unknown',
                    'min_threshold': 0.0,
                    'score': score,
                    'confidence_percentage': 0.0,
                    'tier': 4,
                    'description': f'Score {score:.3f} does not match any configured interpretation level'
                }
                
        except Exception as e:
            logger.error(f"Failed to interpret score {score}: {e}")
            return {
                'level': 'error',
                'label': 'Interpretation Error',
                'min_threshold': 0.0,
                'score': score,
                'confidence_percentage': 0.0,
                'tier': 4,
                'description': f'Error interpreting score: {str(e)}'
            }
    
    def _get_score_tier(self, score: float, config: ScoringConfiguration) -> int:
        """
        Get tier number for a score based on interpretation levels.
        
        Args:
            score: Score value
            config: Scoring configuration
            
        Returns:
            Tier number (1-4, where 1 is highest)
        """
        # Map score ranges to tiers
        if score >= 0.8:
            return 1  # Primary Evidence
        elif score >= 0.5:
            return 2  # Supporting Evidence
        elif score >= 0.2:
            return 3  # Contextual Evidence
        else:
            return 4  # Background Evidence
    
    def _generate_score_description(self, 
                                  score: float, 
                                  level: str, 
                                  interpretation_config: Dict[str, Any]) -> str:
        """
        Generate a descriptive explanation of the score.
        
        Args:
            score: Score value
            level: Interpretation level
            interpretation_config: Configuration for this level
            
        Returns:
            Descriptive string explaining the score
        """
        label = interpretation_config.get('label', level.title())
        min_threshold = interpretation_config.get('min', 0.0)
        
        if score >= 0.8:
            return f"{label} - High confidence match with score {score:.3f} (threshold: {min_threshold:.2f})"
        elif score >= 0.5:
            return f"{label} - Moderate confidence match with score {score:.3f} (threshold: {min_threshold:.2f})"
        elif score >= 0.2:
            return f"{label} - Low confidence match with score {score:.3f} (threshold: {min_threshold:.2f})"
        else:
            return f"{label} - Minimal confidence match with score {score:.3f} (threshold: {min_threshold:.2f})"
    
    def log_scoring_calculation(self, 
                              match_id: str, 
                              score_result: Dict[str, Any], 
                              wing_config: Any,
                              case_id: Optional[str] = None):
        """
        Log detailed information about a scoring calculation.
        
        Args:
            match_id: Identifier for the match
            score_result: Result from calculate_match_scores
            wing_config: Wing configuration used
            case_id: Optional case ID
        """
        try:
            score = score_result.get('score', 0.0)
            interpretation = score_result.get('interpretation', 'Unknown')
            breakdown = score_result.get('breakdown', {})
            scoring_mode = score_result.get('scoring_mode', 'weighted')
            
            logger.debug(f"Scoring calculation for match {match_id}:")
            logger.debug(f"  Final score: {score:.3f}")
            logger.debug(f"  Interpretation: {interpretation}")
            logger.debug(f"  Scoring mode: {scoring_mode}")
            
            if breakdown:
                logger.debug(f"  Breakdown details:")
                for feather_id, details in breakdown.items():
                    weight = details.get('weight', 0.0)
                    contribution = details.get('contribution', 0.0)
                    matched = details.get('matched', False)
                    tier = details.get('tier', 1)
                    
                    logger.debug(f"    {feather_id}: weight={weight:.2f}, "
                               f"contribution={contribution:.3f}, matched={matched}, tier={tier}")
            
            # Log configuration source
            config_source = "case-specific" if self.case_specific_config else "global"
            logger.debug(f"  Configuration source: {config_source}")
            
            if case_id:
                logger.debug(f"  Case ID: {case_id}")
                
        except Exception as e:
            logger.warning(f"Failed to log scoring calculation for match {match_id}: {e}")
    
    def log_scoring_summary(self, matches_processed: int, execution_time: float):
        """
        Log a summary of scoring operations.
        
        Args:
            matches_processed: Number of matches processed
            execution_time: Total execution time in seconds
        """
        try:
            logger.info("="*50)
            logger.info("SCORING OPERATION SUMMARY")
            logger.info("="*50)
            
            # Basic statistics
            logger.info(f"Matches processed: {matches_processed}")
            logger.info(f"Execution time: {execution_time:.2f} seconds")
            
            if matches_processed > 0:
                avg_time_per_match = (execution_time / matches_processed) * 1000  # milliseconds
                logger.info(f"Average time per match: {avg_time_per_match:.2f} ms")
            
            # Detailed statistics
            self._log_scoring_statistics()
            
            # Performance metrics
            if self.stats.total_matches_scored > 0:
                success_rate = (self.stats.scores_calculated / self.stats.total_matches_scored) * 100
                error_rate = ((self.stats.configuration_errors + self.stats.validation_failures) / 
                            self.stats.total_matches_scored) * 100
                
                logger.info(f"Performance metrics:")
                logger.info(f"  Success rate: {success_rate:.1f}%")
                logger.info(f"  Error rate: {error_rate:.1f}%")
                logger.info(f"  Fallback rate: {(self.stats.fallback_to_simple_count / self.stats.total_matches_scored) * 100:.1f}%")
            
            logger.info("="*50)
            
        except Exception as e:
            logger.error(f"Failed to log scoring summary: {e}")
    
    def get_score_interpretation_labels(self, case_id: Optional[str] = None) -> Dict[str, str]:
        """
        Get score interpretation labels for UI display.
        
        Args:
            case_id: Optional case ID for case-specific labels
            
        Returns:
            Dictionary mapping score ranges to labels
        """
        try:
            effective_config = self.get_scoring_configuration(case_id)
            
            labels = {}
            for level, config in effective_config.score_interpretation.items():
                min_score = config.get('min', 0.0)
                label = config.get('label', level.title())
                labels[f"{min_score:.2f}+"] = label
            
            return labels
            
        except Exception as e:
            logger.error(f"Failed to get score interpretation labels: {e}")
            return {"0.00+": "Unknown"}
    
    def get_detailed_scoring_report(self) -> Dict[str, Any]:
        """
        Get a detailed report of scoring operations.
        
        Returns:
            Dictionary with comprehensive scoring information
        """
        try:
            effective_config = self.get_scoring_configuration()
            
            return {
                'statistics': {
                    'total_matches_scored': self.stats.total_matches_scored,
                    'scores_calculated': self.stats.scores_calculated,
                    'fallback_to_simple_count': self.stats.fallback_to_simple_count,
                    'configuration_errors': self.stats.configuration_errors,
                    'validation_failures': self.stats.validation_failures,
                    'success_rate': (self.stats.scores_calculated / max(1, self.stats.total_matches_scored)) * 100,
                    'error_rate': ((self.stats.configuration_errors + self.stats.validation_failures) / 
                                 max(1, self.stats.total_matches_scored)) * 100,
                    'average_score': self.stats.average_score,
                    'score_range': {
                        'min': self.stats.lowest_score,
                        'max': self.stats.highest_score
                    }
                },
                'configuration': {
                    'enabled': effective_config.enabled,
                    'case_specific_enabled': self.case_specific_enabled,
                    'current_case_id': self.current_case_id,
                    'global_configs_used': self.stats.global_configs_used,
                    'case_specific_configs_used': self.stats.case_specific_configs_used,
                    'conflict_resolutions': self.stats.conflict_resolutions
                },
                'interpretation_levels': effective_config.score_interpretation,
                'tier_definitions': effective_config.tier_definitions,
                'validation_rules': effective_config.validation_rules
            }
            
        except Exception as e:
            logger.error(f"Failed to generate detailed scoring report: {e}")
            return {'error': str(e)}
    
    def reload_configuration(self) -> bool:
        """
        Reload scoring configuration from config manager.
        
        This method implements the IScoringIntegration interface requirement
        for live configuration reload without application restart.
        
        Returns:
            True if reload was successful, False otherwise
        """
        try:
            logger.info("Reloading weighted scoring configuration...")
            
            # Preserve current statistics
            preserved_stats = self.stats
            
            # Reload global configuration
            self._load_global_configuration()
            
            # Reload case-specific configuration if we have an active case
            if self.current_case_id:
                self.load_case_specific_scoring_weights(self.current_case_id)
                logger.info(f"Reloaded case-specific configuration for case {self.current_case_id}")
            
            # Restore statistics (don't reset on reload)
            self.stats = preserved_stats
            
            logger.info("Successfully reloaded weighted scoring configuration")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reload weighted scoring configuration: {e}")
            return False
    
    def get_statistics(self) -> IntegrationStatistics:
        """
        Get scoring integration statistics.
        
        This method implements the IScoringIntegration interface requirement.
        
        Returns:
            IntegrationStatistics object with operation counts and metrics
        """
        return IntegrationStatistics(
            total_operations=self.stats.total_matches_scored,
            successful_operations=self.stats.scores_calculated,
            failed_operations=self.stats.configuration_errors + self.stats.validation_failures,
            fallback_count=self.stats.fallback_to_simple_count
        )