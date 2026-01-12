"""
Integration Error Handler

Provides comprehensive error handling and graceful degradation for all integration
components including semantic mapping, weighted scoring, and progress tracking.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import traceback
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class IntegrationComponent(Enum):
    """Enumeration of integration components"""
    SEMANTIC_MAPPING = "semantic_mapping"
    WEIGHTED_SCORING = "weighted_scoring"
    PROGRESS_TRACKING = "progress_tracking"
    ENGINE_SELECTION = "engine_selection"
    CONFIGURATION_MANAGEMENT = "configuration_management"


class ErrorSeverity(Enum):
    """Error severity levels"""
    CRITICAL = "critical"  # System cannot continue
    HIGH = "high"         # Major functionality impacted
    MEDIUM = "medium"     # Some functionality impacted
    LOW = "low"          # Minor impact, degraded performance
    INFO = "info"        # Informational, no impact


class FallbackStrategy(Enum):
    """Available fallback strategies"""
    RAW_VALUES = "raw_values"                    # Use raw technical values
    SIMPLE_COUNT = "simple_count"                # Use simple count-based scoring
    BASIC_LOGGING = "basic_logging"              # Use basic console logging
    DEFAULT_CONFIG = "default_config"            # Use default configuration
    DISABLE_FEATURE = "disable_feature"          # Disable the feature entirely
    RETRY_WITH_DEFAULTS = "retry_with_defaults"  # Retry with default settings


@dataclass
class IntegrationError:
    """Represents an error in an integration component"""
    component: IntegrationComponent
    error_type: str
    message: str
    severity: ErrorSeverity
    timestamp: datetime = field(default_factory=datetime.now)
    exception: Optional[Exception] = None
    context: Dict[str, Any] = field(default_factory=dict)
    fallback_applied: Optional[FallbackStrategy] = None
    recovery_attempted: bool = False
    recovery_successful: bool = False
    additional_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FallbackResult:
    """Result of applying a fallback strategy"""
    strategy: FallbackStrategy
    success: bool
    result: Any = None
    message: str = ""
    performance_impact: str = "none"  # none, low, medium, high
    functionality_impact: str = "none"  # none, degraded, limited, disabled


@dataclass
class RecoveryAttempt:
    """Represents an attempt to recover from an error"""
    component: IntegrationComponent
    error: IntegrationError
    strategy: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = False
    result: Any = None
    message: str = ""
    retry_count: int = 0


class IntegrationErrorHandler:
    """
    Comprehensive error handler for all integration components.
    
    Provides:
    - Graceful degradation strategies
    - Error recovery mechanisms
    - Fallback implementations
    - Error reporting and logging
    - Performance monitoring during errors
    """
    
    def __init__(self, debug_mode: bool = False, enable_recovery: bool = True):
        """
        Initialize integration error handler.
        
        Args:
            debug_mode: Enable detailed debug logging
            enable_recovery: Enable automatic error recovery attempts
        """
        self.debug_mode = debug_mode
        self.enable_recovery = enable_recovery
        
        # Error tracking
        self.errors: List[IntegrationError] = []
        self.recovery_attempts: List[RecoveryAttempt] = []
        self.fallback_statistics: Dict[IntegrationComponent, Dict[FallbackStrategy, int]] = {}
        
        # Error listeners for external notification
        self._error_listeners: List[Callable[[IntegrationError], None]] = []
        
        # Maximum error history size to prevent memory growth
        self._max_error_history = 1000
        
        # Component health tracking
        self.component_health: Dict[IntegrationComponent, bool] = {
            component: True for component in IntegrationComponent
        }
        
        # Recovery strategies
        self.recovery_strategies: Dict[IntegrationComponent, List[Callable]] = {
            IntegrationComponent.SEMANTIC_MAPPING: [
                self._recover_semantic_mapping_manager,
                self._recover_semantic_mapping_config,
                self._recover_semantic_mapping_fallback
            ],
            IntegrationComponent.WEIGHTED_SCORING: [
                self._recover_scoring_engine,
                self._recover_scoring_config,
                self._recover_scoring_fallback
            ],
            IntegrationComponent.PROGRESS_TRACKING: [
                self._recover_progress_tracker,
                self._recover_progress_listeners,
                self._recover_progress_fallback
            ]
        }
        
        # Initialize fallback statistics
        for component in IntegrationComponent:
            self.fallback_statistics[component] = {
                strategy: 0 for strategy in FallbackStrategy
            }
        
        logger.info(f"IntegrationErrorHandler initialized (debug={debug_mode}, recovery={enable_recovery})")
    
    # Error Listener System
    
    def register_error_listener(self, listener: Callable[[IntegrationError], None]):
        """
        Register a listener to be notified of errors.
        
        Args:
            listener: Callable that accepts an IntegrationError
        """
        if listener not in self._error_listeners:
            self._error_listeners.append(listener)
            logger.debug(f"Registered error listener: {listener}")
    
    def unregister_error_listener(self, listener: Callable[[IntegrationError], None]):
        """
        Unregister an error listener.
        
        Args:
            listener: Listener to remove
        """
        if listener in self._error_listeners:
            self._error_listeners.remove(listener)
            logger.debug(f"Unregistered error listener: {listener}")
    
    def emit_error_event(self, error: IntegrationError):
        """
        Emit an error event to all registered listeners.
        
        Args:
            error: IntegrationError to emit
        """
        for listener in self._error_listeners:
            try:
                listener(error)
            except Exception as e:
                logger.error(f"Error in error listener: {e}")
                if self.debug_mode:
                    logger.error(f"Listener error details: {traceback.format_exc()}")
    
    def capture_full_context(self, error: Exception, additional_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Capture full context information for an error including stack trace.
        
        Args:
            error: Exception that occurred
            additional_context: Additional context to include
            
        Returns:
            Dictionary with full error context
        """
        context = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'stack_trace': traceback.format_exc(),
            'timestamp': datetime.now().isoformat(),
        }
        
        # Add exception attributes if available
        if hasattr(error, '__dict__'):
            context['error_attributes'] = {
                k: str(v) for k, v in error.__dict__.items()
                if not k.startswith('_')
            }
        
        # Merge additional context
        if additional_context:
            context.update(additional_context)
        
        return context
    
    # Error History Management
    
    def get_error_history(self, 
                         component: Optional[IntegrationComponent] = None,
                         severity: Optional[ErrorSeverity] = None,
                         since: Optional[datetime] = None,
                         limit: int = 100) -> List[IntegrationError]:
        """
        Get error history with optional filtering.
        
        Args:
            component: Filter by component (optional)
            severity: Filter by severity (optional)
            since: Filter errors after this timestamp (optional)
            limit: Maximum number of errors to return
            
        Returns:
            List of IntegrationError objects matching filters
        """
        filtered_errors = self.errors.copy()
        
        if component:
            filtered_errors = [e for e in filtered_errors if e.component == component]
        
        if severity:
            filtered_errors = [e for e in filtered_errors if e.severity == severity]
        
        if since:
            filtered_errors = [e for e in filtered_errors if e.timestamp >= since]
        
        # Sort by timestamp descending (most recent first)
        filtered_errors.sort(key=lambda e: e.timestamp, reverse=True)
        
        return filtered_errors[:limit]
    
    def get_aggregated_errors(self) -> Dict[str, Any]:
        """
        Get aggregated error statistics.
        
        Returns:
            Dictionary with error counts by type, component, and severity
        """
        aggregated = {
            'total_errors': len(self.errors),
            'by_component': {},
            'by_severity': {},
            'by_type': {},
            'recovery_stats': {
                'total_attempts': len(self.recovery_attempts),
                'successful': sum(1 for r in self.recovery_attempts if r.success),
                'failed': sum(1 for r in self.recovery_attempts if not r.success)
            },
            'fallback_stats': self.fallback_statistics
        }
        
        # Count by component
        for component in IntegrationComponent:
            count = sum(1 for e in self.errors if e.component == component)
            if count > 0:
                aggregated['by_component'][component.value] = count
        
        # Count by severity
        for severity in ErrorSeverity:
            count = sum(1 for e in self.errors if e.severity == severity)
            if count > 0:
                aggregated['by_severity'][severity.value] = count
        
        # Count by error type
        error_types = {}
        for error in self.errors:
            error_types[error.error_type] = error_types.get(error.error_type, 0) + 1
        aggregated['by_type'] = error_types
        
        return aggregated
    
    def _add_error(self, error: IntegrationError):
        """
        Add an error to the history, maintaining max size.
        
        Args:
            error: IntegrationError to add
        """
        self.errors.append(error)
        
        # Trim history if it exceeds max size
        if len(self.errors) > self._max_error_history:
            # Remove oldest errors
            self.errors = self.errors[-self._max_error_history:]
        
        # Emit to listeners
        self.emit_error_event(error)
    
    def handle_semantic_mapping_error(self, 
                                    error: Exception, 
                                    context: Dict[str, Any] = None,
                                    fallback_strategy: FallbackStrategy = FallbackStrategy.RAW_VALUES) -> FallbackResult:
        """
        Handle semantic mapping failures with graceful degradation.
        
        Args:
            error: Exception that occurred
            context: Additional context information
            fallback_strategy: Preferred fallback strategy
            
        Returns:
            FallbackResult with fallback implementation
        """
        integration_error = IntegrationError(
            component=IntegrationComponent.SEMANTIC_MAPPING,
            error_type=type(error).__name__,
            message=str(error),
            severity=self._determine_error_severity(error, IntegrationComponent.SEMANTIC_MAPPING),
            exception=error,
            context=context or {}
        )
        
        # Add full context capture
        integration_error.additional_data = self.capture_full_context(error, context)
        
        self._add_error(integration_error)
        self.component_health[IntegrationComponent.SEMANTIC_MAPPING] = False
        
        logger.error(f"Semantic mapping error: {error}")
        if self.debug_mode:
            logger.error(f"Semantic mapping error details: {traceback.format_exc()}")
        
        # Attempt recovery if enabled
        if self.enable_recovery:
            recovery_result = self._attempt_recovery(integration_error)
            if recovery_result.success:
                self.component_health[IntegrationComponent.SEMANTIC_MAPPING] = True
                return FallbackResult(
                    strategy=FallbackStrategy.RETRY_WITH_DEFAULTS,
                    success=True,
                    result=recovery_result.result,
                    message="Recovered semantic mapping functionality",
                    performance_impact="low",
                    functionality_impact="none"
                )
        
        # Apply fallback strategy
        fallback_result = self._apply_semantic_mapping_fallback(fallback_strategy, integration_error)
        integration_error.fallback_applied = fallback_strategy
        
        # Update statistics
        self.fallback_statistics[IntegrationComponent.SEMANTIC_MAPPING][fallback_strategy] += 1
        
        logger.warning(f"Applied semantic mapping fallback: {fallback_strategy.value}")
        return fallback_result
    
    def handle_weighted_scoring_error(self, 
                                    error: Exception, 
                                    context: Dict[str, Any] = None,
                                    fallback_strategy: FallbackStrategy = FallbackStrategy.SIMPLE_COUNT) -> FallbackResult:
        """
        Handle weighted scoring failures with graceful degradation.
        
        Args:
            error: Exception that occurred
            context: Additional context information
            fallback_strategy: Preferred fallback strategy
            
        Returns:
            FallbackResult with fallback implementation
        """
        integration_error = IntegrationError(
            component=IntegrationComponent.WEIGHTED_SCORING,
            error_type=type(error).__name__,
            message=str(error),
            severity=self._determine_error_severity(error, IntegrationComponent.WEIGHTED_SCORING),
            exception=error,
            context=context or {}
        )
        
        self.errors.append(integration_error)
        self.component_health[IntegrationComponent.WEIGHTED_SCORING] = False
        
        logger.error(f"Weighted scoring error: {error}")
        if self.debug_mode:
            logger.error(f"Weighted scoring error details: {traceback.format_exc()}")
        
        # Attempt recovery if enabled
        if self.enable_recovery:
            recovery_result = self._attempt_recovery(integration_error)
            if recovery_result.success:
                self.component_health[IntegrationComponent.WEIGHTED_SCORING] = True
                return FallbackResult(
                    strategy=FallbackStrategy.RETRY_WITH_DEFAULTS,
                    success=True,
                    result=recovery_result.result,
                    message="Recovered weighted scoring functionality",
                    performance_impact="low",
                    functionality_impact="none"
                )
        
        # Apply fallback strategy
        fallback_result = self._apply_weighted_scoring_fallback(fallback_strategy, integration_error)
        integration_error.fallback_applied = fallback_strategy
        
        # Update statistics
        self.fallback_statistics[IntegrationComponent.WEIGHTED_SCORING][fallback_strategy] += 1
        
        logger.warning(f"Applied weighted scoring fallback: {fallback_strategy.value}")
        return fallback_result
    
    def handle_progress_tracking_error(self, 
                                     error: Exception, 
                                     context: Dict[str, Any] = None,
                                     fallback_strategy: FallbackStrategy = FallbackStrategy.BASIC_LOGGING) -> FallbackResult:
        """
        Handle progress tracking failures with graceful degradation.
        
        Args:
            error: Exception that occurred
            context: Additional context information
            fallback_strategy: Preferred fallback strategy
            
        Returns:
            FallbackResult with fallback implementation
        """
        integration_error = IntegrationError(
            component=IntegrationComponent.PROGRESS_TRACKING,
            error_type=type(error).__name__,
            message=str(error),
            severity=self._determine_error_severity(error, IntegrationComponent.PROGRESS_TRACKING),
            exception=error,
            context=context or {}
        )
        
        self.errors.append(integration_error)
        self.component_health[IntegrationComponent.PROGRESS_TRACKING] = False
        
        logger.error(f"Progress tracking error: {error}")
        if self.debug_mode:
            logger.error(f"Progress tracking error details: {traceback.format_exc()}")
        
        # Attempt recovery if enabled
        if self.enable_recovery:
            recovery_result = self._attempt_recovery(integration_error)
            if recovery_result.success:
                self.component_health[IntegrationComponent.PROGRESS_TRACKING] = True
                return FallbackResult(
                    strategy=FallbackStrategy.RETRY_WITH_DEFAULTS,
                    success=True,
                    result=recovery_result.result,
                    message="Recovered progress tracking functionality",
                    performance_impact="low",
                    functionality_impact="none"
                )
        
        # Apply fallback strategy
        fallback_result = self._apply_progress_tracking_fallback(fallback_strategy, integration_error)
        integration_error.fallback_applied = fallback_strategy
        
        # Update statistics
        self.fallback_statistics[IntegrationComponent.PROGRESS_TRACKING][fallback_strategy] += 1
        
        logger.warning(f"Applied progress tracking fallback: {fallback_strategy.value}")
        return fallback_result
    
    def _determine_error_severity(self, error: Exception, component: IntegrationComponent) -> ErrorSeverity:
        """
        Determine the severity of an error based on its type and component.
        
        Args:
            error: Exception that occurred
            component: Component where error occurred
            
        Returns:
            ErrorSeverity level
        """
        error_type = type(error).__name__
        
        # Critical errors that prevent system operation
        if error_type in ['SystemExit', 'KeyboardInterrupt', 'MemoryError']:
            return ErrorSeverity.CRITICAL
        
        # High severity errors
        if error_type in ['ImportError', 'ModuleNotFoundError', 'AttributeError']:
            return ErrorSeverity.HIGH
        
        # Component-specific severity assessment
        if component == IntegrationComponent.SEMANTIC_MAPPING:
            if error_type in ['FileNotFoundError', 'PermissionError', 'JSONDecodeError']:
                return ErrorSeverity.MEDIUM
            elif error_type in ['KeyError', 'ValueError', 'TypeError']:
                return ErrorSeverity.LOW
        
        elif component == IntegrationComponent.WEIGHTED_SCORING:
            if error_type in ['ZeroDivisionError', 'ValueError', 'TypeError']:
                return ErrorSeverity.MEDIUM
            elif error_type in ['KeyError', 'AttributeError']:
                return ErrorSeverity.LOW
        
        elif component == IntegrationComponent.PROGRESS_TRACKING:
            if error_type in ['RuntimeError', 'OSError']:
                return ErrorSeverity.MEDIUM
            else:
                return ErrorSeverity.LOW
        
        # Default to medium severity
        return ErrorSeverity.MEDIUM
    
    def _attempt_recovery(self, integration_error: IntegrationError) -> RecoveryAttempt:
        """
        Attempt to recover from an integration error.
        
        Args:
            integration_error: Error to recover from
            
        Returns:
            RecoveryAttempt with results
        """
        component = integration_error.component
        recovery_strategies = self.recovery_strategies.get(component, [])
        
        for i, strategy_func in enumerate(recovery_strategies):
            recovery_attempt = RecoveryAttempt(
                component=component,
                error=integration_error,
                strategy=strategy_func.__name__,
                retry_count=i + 1
            )
            
            try:
                logger.info(f"Attempting recovery strategy {i+1}/{len(recovery_strategies)}: {strategy_func.__name__}")
                
                result = strategy_func(integration_error)
                
                if result:
                    recovery_attempt.success = True
                    recovery_attempt.result = result
                    recovery_attempt.message = f"Recovery successful using {strategy_func.__name__}"
                    
                    integration_error.recovery_attempted = True
                    integration_error.recovery_successful = True
                    
                    self.recovery_attempts.append(recovery_attempt)
                    logger.info(f"Recovery successful: {recovery_attempt.message}")
                    return recovery_attempt
                
            except Exception as recovery_error:
                recovery_attempt.message = f"Recovery failed: {str(recovery_error)}"
                logger.warning(f"Recovery strategy {strategy_func.__name__} failed: {recovery_error}")
                
                if self.debug_mode:
                    logger.warning(f"Recovery error details: {traceback.format_exc()}")
        
        # All recovery strategies failed
        final_attempt = RecoveryAttempt(
            component=component,
            error=integration_error,
            strategy="all_strategies_failed",
            success=False,
            message="All recovery strategies failed"
        )
        
        integration_error.recovery_attempted = True
        integration_error.recovery_successful = False
        
        self.recovery_attempts.append(final_attempt)
        logger.error(f"All recovery strategies failed for {component.value}")
        return final_attempt
    
    def _apply_semantic_mapping_fallback(self, 
                                       strategy: FallbackStrategy, 
                                       error: IntegrationError) -> FallbackResult:
        """Apply semantic mapping fallback strategy"""
        if strategy == FallbackStrategy.RAW_VALUES:
            return FallbackResult(
                strategy=strategy,
                success=True,
                result=self._create_raw_values_mapper(),
                message="Using raw technical values instead of semantic mappings",
                performance_impact="none",
                functionality_impact="degraded"
            )
        
        elif strategy == FallbackStrategy.DISABLE_FEATURE:
            return FallbackResult(
                strategy=strategy,
                success=True,
                result=None,
                message="Semantic mapping disabled due to errors",
                performance_impact="none",
                functionality_impact="disabled"
            )
        
        else:
            return FallbackResult(
                strategy=strategy,
                success=False,
                message=f"Unsupported fallback strategy for semantic mapping: {strategy.value}",
                performance_impact="none",
                functionality_impact="disabled"
            )
    
    def _apply_weighted_scoring_fallback(self, 
                                       strategy: FallbackStrategy, 
                                       error: IntegrationError) -> FallbackResult:
        """Apply weighted scoring fallback strategy"""
        if strategy == FallbackStrategy.SIMPLE_COUNT:
            return FallbackResult(
                strategy=strategy,
                success=True,
                result=self._create_simple_count_scorer(),
                message="Using simple count-based scoring instead of weighted scoring",
                performance_impact="low",
                functionality_impact="degraded"
            )
        
        elif strategy == FallbackStrategy.DISABLE_FEATURE:
            return FallbackResult(
                strategy=strategy,
                success=True,
                result=None,
                message="Weighted scoring disabled due to errors",
                performance_impact="none",
                functionality_impact="disabled"
            )
        
        else:
            return FallbackResult(
                strategy=strategy,
                success=False,
                message=f"Unsupported fallback strategy for weighted scoring: {strategy.value}",
                performance_impact="none",
                functionality_impact="disabled"
            )
    
    def _apply_progress_tracking_fallback(self, 
                                        strategy: FallbackStrategy, 
                                        error: IntegrationError) -> FallbackResult:
        """Apply progress tracking fallback strategy"""
        if strategy == FallbackStrategy.BASIC_LOGGING:
            return FallbackResult(
                strategy=strategy,
                success=True,
                result=self._create_basic_logger(),
                message="Using basic console logging instead of advanced progress tracking",
                performance_impact="none",
                functionality_impact="degraded"
            )
        
        elif strategy == FallbackStrategy.DISABLE_FEATURE:
            return FallbackResult(
                strategy=strategy,
                success=True,
                result=None,
                message="Progress tracking disabled due to errors",
                performance_impact="none",
                functionality_impact="disabled"
            )
        
        else:
            return FallbackResult(
                strategy=strategy,
                success=False,
                message=f"Unsupported fallback strategy for progress tracking: {strategy.value}",
                performance_impact="none",
                functionality_impact="disabled"
            )
    
    def _create_raw_values_mapper(self):
        """Create a fallback semantic mapper that returns raw values"""
        class RawValuesMapper:
            def apply_to_record(self, record, artifact_type=None, wing_id=None, pipeline_id=None):
                # Return empty list - no semantic mappings applied
                return []
            
            def apply_to_correlation_results(self, results, wing_id=None, pipeline_id=None, artifact_type=None):
                # Add fallback semantic information to results
                enhanced_results = []
                for result in results:
                    enhanced_result = result.copy()
                    
                    # Create fallback semantic mappings using raw values
                    fallback_mappings = {}
                    for field_name, field_value in result.items():
                        if not field_name.startswith('_'):
                            fallback_mappings[field_name] = {
                                'semantic_value': str(field_value),
                                'description': f'Raw value (semantic mapping unavailable)',
                                'category': 'technical',
                                'severity': 'info',
                                'confidence': 0.0,
                                'mapping_source': 'fallback'
                            }
                    
                    enhanced_result['_semantic_mappings'] = fallback_mappings
                    enhanced_result['_semantic_mapping_fallback'] = True
                    enhanced_results.append(enhanced_result)
                
                return enhanced_results
        
        return RawValuesMapper()
    
    def _create_simple_count_scorer(self):
        """Create a fallback scorer that uses simple counting"""
        class SimpleCountScorer:
            def calculate_match_score(self, match_records, wing_config):
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
                    'scoring_mode': 'simple_count_fallback'
                }
        
        return SimpleCountScorer()
    
    def _create_basic_logger(self):
        """Create a fallback progress logger that uses basic console output"""
        class BasicProgressLogger:
            def __init__(self):
                self.start_time = None
                self.total_items = 0
                self.processed_items = 0
            
            def start_tracking(self, total_items, **kwargs):
                self.start_time = datetime.now()
                self.total_items = total_items
                self.processed_items = 0
                logger.info(f"Starting correlation: {total_items} items to process")
            
            def update_progress(self, processed_items, **kwargs):
                self.processed_items = processed_items
                if self.total_items > 0:
                    percentage = (processed_items / self.total_items) * 100
                    logger.info(f"Progress: {processed_items}/{self.total_items} ({percentage:.1f}%)")
            
            def complete_tracking(self, **kwargs):
                if self.start_time:
                    elapsed = (datetime.now() - self.start_time).total_seconds()
                    logger.info(f"Correlation complete: {self.processed_items} items processed in {elapsed:.1f}s")
        
        return BasicProgressLogger()
    
    # Recovery strategy implementations
    def _recover_semantic_mapping_manager(self, error: IntegrationError) -> Any:
        """Attempt to recover semantic mapping manager"""
        try:
            from ..config.semantic_mapping import SemanticMappingManager
            
            # Try to create a new manager instance
            new_manager = SemanticMappingManager()
            
            # Test basic functionality
            test_record = {'test_field': 'test_value'}
            new_manager.apply_to_record(test_record)
            
            logger.info("Successfully recovered semantic mapping manager")
            return new_manager
            
        except Exception as e:
            logger.warning(f"Failed to recover semantic mapping manager: {e}")
            return None
    
    def _recover_semantic_mapping_config(self, error: IntegrationError) -> Any:
        """Attempt to recover semantic mapping configuration"""
        try:
            # Try to load default configuration
            default_config = {
                'enabled': True,
                'global_mappings_path': None,
                'case_specific': {'enabled': False}
            }
            
            logger.info("Using default semantic mapping configuration")
            return default_config
            
        except Exception as e:
            logger.warning(f"Failed to recover semantic mapping configuration: {e}")
            return None
    
    def _recover_semantic_mapping_fallback(self, error: IntegrationError) -> Any:
        """Final fallback for semantic mapping"""
        return self._create_raw_values_mapper()
    
    def _recover_scoring_engine(self, error: IntegrationError) -> Any:
        """Attempt to recover weighted scoring engine"""
        try:
            from ..engine.weighted_scoring import WeightedScoringEngine
            
            # Try to create a new engine instance
            new_engine = WeightedScoringEngine()
            
            # Test basic functionality
            test_records = {'test_feather': {'test_field': 'test_value'}}
            test_config = type('TestConfig', (), {'feathers': []})()
            new_engine.calculate_match_score(test_records, test_config)
            
            logger.info("Successfully recovered weighted scoring engine")
            return new_engine
            
        except Exception as e:
            logger.warning(f"Failed to recover weighted scoring engine: {e}")
            return None
    
    def _recover_scoring_config(self, error: IntegrationError) -> Any:
        """Attempt to recover scoring configuration"""
        try:
            # Try to load default configuration
            default_config = {
                'enabled': True,
                'score_interpretation': {
                    "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
                    "probable": {"min": 0.5, "label": "Probable Match"},
                    "weak": {"min": 0.2, "label": "Weak Evidence"}
                },
                'default_weights': {
                    "Logs": 0.4,
                    "Prefetch": 0.3,
                    "SRUM": 0.2
                }
            }
            
            logger.info("Using default weighted scoring configuration")
            return default_config
            
        except Exception as e:
            logger.warning(f"Failed to recover weighted scoring configuration: {e}")
            return None
    
    def _recover_scoring_fallback(self, error: IntegrationError) -> Any:
        """Final fallback for weighted scoring"""
        return self._create_simple_count_scorer()
    
    def _recover_progress_tracker(self, error: IntegrationError) -> Any:
        """Attempt to recover progress tracker"""
        try:
            from ..engine.progress_tracking import ProgressTracker
            
            # Try to create a new tracker instance
            new_tracker = ProgressTracker()
            
            logger.info("Successfully recovered progress tracker")
            return new_tracker
            
        except Exception as e:
            logger.warning(f"Failed to recover progress tracker: {e}")
            return None
    
    def _recover_progress_listeners(self, error: IntegrationError) -> Any:
        """Attempt to recover progress listeners"""
        try:
            # Create basic console listener
            basic_listener = self._create_basic_logger()
            
            logger.info("Using basic progress listener")
            return basic_listener
            
        except Exception as e:
            logger.warning(f"Failed to recover progress listeners: {e}")
            return None
    
    def _recover_progress_fallback(self, error: IntegrationError) -> Any:
        """Final fallback for progress tracking"""
        return self._create_basic_logger()
    
    # Health and monitoring methods
    def is_component_healthy(self, component: IntegrationComponent) -> bool:
        """Check if a component is healthy"""
        return self.component_health.get(component, False)
    
    def get_component_health_status(self) -> Dict[str, bool]:
        """Get health status of all components"""
        return {component.value: healthy for component, healthy in self.component_health.items()}
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of all errors"""
        error_counts = {}
        severity_counts = {}
        
        for error in self.errors:
            component = error.component.value
            severity = error.severity.value
            
            error_counts[component] = error_counts.get(component, 0) + 1
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        return {
            'total_errors': len(self.errors),
            'errors_by_component': error_counts,
            'errors_by_severity': severity_counts,
            'recovery_attempts': len(self.recovery_attempts),
            'successful_recoveries': sum(1 for attempt in self.recovery_attempts if attempt.success),
            'fallback_usage': self.fallback_statistics
        }
    
    def get_recent_errors(self, limit: int = 10) -> List[IntegrationError]:
        """Get most recent errors"""
        return sorted(self.errors, key=lambda e: e.timestamp, reverse=True)[:limit]
    
    def clear_error_history(self):
        """Clear error history (useful for testing)"""
        self.errors.clear()
        self.recovery_attempts.clear()
        
        # Reset component health
        for component in IntegrationComponent:
            self.component_health[component] = True
        
        # Reset fallback statistics
        for component in IntegrationComponent:
            self.fallback_statistics[component] = {
                strategy: 0 for strategy in FallbackStrategy
            }
        
        logger.info("Error history cleared")
    
    def export_error_report(self, file_path: Optional[Path] = None) -> str:
        """
        Export comprehensive error report.
        
        Args:
            file_path: Optional path to save report
            
        Returns:
            JSON string with error report
        """
        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': self.get_error_summary(),
            'component_health': self.get_component_health_status(),
            'recent_errors': [
                {
                    'component': error.component.value,
                    'error_type': error.error_type,
                    'message': error.message,
                    'severity': error.severity.value,
                    'timestamp': error.timestamp.isoformat(),
                    'fallback_applied': error.fallback_applied.value if error.fallback_applied else None,
                    'recovery_attempted': error.recovery_attempted,
                    'recovery_successful': error.recovery_successful
                }
                for error in self.get_recent_errors(20)
            ],
            'recovery_attempts': [
                {
                    'component': attempt.component.value,
                    'strategy': attempt.strategy,
                    'success': attempt.success,
                    'message': attempt.message,
                    'timestamp': attempt.timestamp.isoformat()
                }
                for attempt in self.recovery_attempts[-10:]  # Last 10 attempts
            ]
        }
        
        report_json = json.dumps(report, indent=2)
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(report_json)
                logger.info(f"Error report exported to {file_path}")
            except Exception as e:
                logger.error(f"Failed to export error report: {e}")
        
        return report_json