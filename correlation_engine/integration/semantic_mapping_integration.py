"""
Semantic Mapping Integration Layer

Provides integration between the SemanticMappingManager and correlation engines.
Handles case-specific configurations, result processing, and UI data preparation.
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from ..config.semantic_mapping import SemanticMappingManager, SemanticMapping
from .integration_error_handler import IntegrationErrorHandler, FallbackStrategy
from .integration_monitor import IntegrationMonitor
from .interfaces import ISemanticMappingIntegration, IntegrationStatistics

logger = logging.getLogger(__name__)


@dataclass
class SemanticMappingStats:
    """Statistics for semantic mapping operations"""
    total_records_processed: int = 0
    mappings_applied: int = 0
    unmapped_fields: int = 0
    pattern_matches: int = 0
    exact_matches: int = 0
    case_specific_mappings_used: int = 0
    global_mappings_used: int = 0
    fallback_count: int = 0
    manager_failure_count: int = 0
    recovery_attempt_count: int = 0
    successful_recovery_count: int = 0


# Global statistics accumulator to prevent multiple summaries
_global_semantic_stats = SemanticMappingStats()
_stats_lock = False  # Simple flag to prevent concurrent access
_last_print_time = None  # Track when we last printed to avoid spam
_print_threshold = 1000  # Only print when we have significant data


class SemanticMappingIntegration(ISemanticMappingIntegration):
    """
    Integration layer for semantic mapping system.
    
    Provides bridge between SemanticMappingManager and correlation engines,
    handling case-specific configurations and result processing.
    
    Implements ISemanticMappingIntegration interface for dependency injection and testing.
    """
    
    def __init__(self, config_manager=None, error_handler: IntegrationErrorHandler = None,
                 monitor: IntegrationMonitor = None):
        """
        Initialize semantic mapping integration.
        
        Args:
            config_manager: Configuration manager for loading settings
            error_handler: Error handler for graceful degradation
            monitor: Integration monitor for performance tracking
        """
        self.semantic_manager = SemanticMappingManager()
        self.config_manager = config_manager
        self.current_case_id: Optional[str] = None
        self.case_specific_enabled = False
        self.stats = SemanticMappingStats()
        
        # Error handling and monitoring
        self.error_handler = error_handler or IntegrationErrorHandler()
        self.monitor = monitor or IntegrationMonitor()
        
        # Load global configuration
        self._load_global_configuration()
    
    def _load_global_configuration(self):
        """Load global semantic mapping configuration with validation and warnings"""
        operation_id = self.monitor.start_operation("semantic_mapping", "load_global_config")
        
        try:
            # Task 6.3: Check if semantic mapping configuration is missing or invalid
            # Requirements: 7.4, 7.5 - Provide helpful error messages for troubleshooting
            if not self.config_manager:
                logger.debug("No configuration manager available - semantic mapping will use default settings")
                self.monitor.complete_operation(operation_id, success=True)
                return
            
            config = self.config_manager.get_semantic_mapping_config()
            
            # Task 6.3: Validate configuration structure
            if not config:
                logger.debug("Semantic mapping configuration is missing - semantic mapping will be disabled")
                self.monitor.complete_operation(operation_id, success=True)
                return
            
            if not isinstance(config, dict):
                logger.error(f"Invalid semantic mapping configuration type: {type(config)}, expected dict")
                print("[SEMANTIC] ERROR: Invalid configuration format - semantic mapping disabled")
                self.monitor.complete_operation(operation_id, success=False, error_message="Invalid config type")
                return
            
            # Task 6.3: Check if semantic mapping is disabled in configuration
            if not config.get('enabled', True):
                logger.info("Semantic mapping is disabled in configuration")
                self.monitor.complete_operation(operation_id, success=True)
                return
            
            # Task 6.3: Validate global mappings path
            global_mappings_path = config.get('global_mappings_path')
            if global_mappings_path:
                mappings_path = Path(global_mappings_path)
                if not mappings_path.exists():
                    logger.debug(f"Global semantic mappings file not found: {global_mappings_path}")
                else:
                    try:
                        self.semantic_manager.load_from_file(mappings_path)
                        logger.debug(f"Loaded global semantic mappings from {global_mappings_path}")
                    except Exception as e:
                        logger.error(f"Failed to load global semantic mappings from {global_mappings_path}: {e}")
                        print(f"[SEMANTIC] ERROR: Failed to load global mappings: {str(e)[:50]}...")
            else:
                logger.debug("No global mappings path configured - using built-in semantic rules only")
            
            # Task 6.3: Validate case-specific configuration
            case_config = config.get('case_specific', {})
            if case_config:
                if not isinstance(case_config, dict):
                    logger.warning(f"Invalid case-specific configuration type: {type(case_config)}, expected dict")
                    self.case_specific_enabled = False
                else:
                    self.case_specific_enabled = case_config.get('enabled', False)
                    if self.case_specific_enabled:
                        storage_path_template = case_config.get('storage_path')
                        if not storage_path_template:
                            logger.warning("Case-specific mappings enabled but no storage_path configured")
                            self.case_specific_enabled = False
                        else:
                            logger.debug(f"Case-specific semantic mappings enabled with path template: {storage_path_template}")
            else:
                self.case_specific_enabled = False
                logger.debug("Case-specific semantic mappings not configured")
            
            # Task 6.3: Validate semantic manager health after configuration
            if not self.semantic_manager:
                logger.error("Semantic manager failed to initialize")
                print("[SEMANTIC] ERROR: Semantic manager initialization failed")
                self.monitor.complete_operation(operation_id, success=False, error_message="Manager init failed")
                return
            
            self.monitor.complete_operation(operation_id, success=True)
                    
        except Exception as e:
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
            # Task 6.3: Provide helpful error messages for troubleshooting
            logger.error(f"Failed to load global semantic mapping configuration: {e}")
            print(f"[SEMANTIC] ERROR: Configuration loading failed - semantic mapping disabled")
            
            # Handle error with graceful degradation
            fallback_result = self.error_handler.handle_semantic_mapping_error(
                e, context={'operation': 'load_global_configuration'}
            )
            
            if fallback_result.success:
                logger.debug(f"Using fallback for global configuration: {fallback_result.message}")
            else:
                logger.error(f"Failed to load global semantic mapping configuration: {e}")
                # Continue with default mappings
    
    def load_case_specific_mappings(self, case_id: str) -> bool:
        """
        Load case-specific semantic mappings.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case-specific mappings were loaded, False otherwise
        """
        if not self.case_specific_enabled:
            return False
        
        try:
            self.current_case_id = case_id
            
            if self.config_manager:
                config = self.config_manager.get_semantic_mapping_config()
                case_config = config.get('case_specific', {})
                storage_path_template = case_config.get('storage_path', 'cases/{case_id}/semantic_mappings.json')
                
                # Replace case_id placeholder
                storage_path = storage_path_template.format(case_id=case_id)
                case_mappings_path = Path(storage_path)
                
                if case_mappings_path.exists():
                    # Load case-specific mappings (they will override global ones)
                    self.semantic_manager.load_from_file(case_mappings_path)
                    logger.info(f"Loaded case-specific semantic mappings for case {case_id}")
                    return True
                else:
                    logger.info(f"No case-specific semantic mappings found for case {case_id}")
            
        except Exception as e:
            logger.error(f"Failed to load case-specific semantic mappings for case {case_id}: {e}")
        
        return False
    
    def apply_to_correlation_results(self, 
                                   results: List[Dict[str, Any]], 
                                   wing_id: Optional[str] = None,
                                   pipeline_id: Optional[str] = None,
                                   artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply semantic mappings to correlation results with comprehensive fallback handling.
        
        Args:
            results: List of correlation result records
            wing_id: Optional wing ID for wing-specific mappings
            pipeline_id: Optional pipeline ID for pipeline-specific mappings
            artifact_type: Optional artifact type for filtering mappings
            
        Returns:
            Enhanced results with semantic mapping information
        """
        # Skip processing if no results or semantic mapping disabled
        if not results or not self.is_enabled() or not self.is_healthy():
            return results
        
        operation_id = self.monitor.start_operation(
            "semantic_mapping", 
            "apply_to_correlation_results",
            context={'wing_id': wing_id, 'pipeline_id': pipeline_id, 'artifact_type': artifact_type},
            input_size=len(results)
        )
        
        start_time = time.time()
        enhanced_results = []
        self.stats = SemanticMappingStats()  # Reset stats
        
        # Task 6.1: Enhanced graceful degradation for semantic mapping failures
        # Requirements: 7.1, 7.2, 7.3 - Ensure correlation continues even if semantic mapping fails
        try:
            # Process records with minimal logging
            for i, result in enumerate(results):
                try:
                    enhanced_result = self._apply_semantic_mappings_to_record(
                        result, wing_id, pipeline_id, artifact_type
                    )
                    enhanced_results.append(enhanced_result)
                    self.stats.total_records_processed += 1
                    
                except Exception as e:
                    # Task 6.1: Log appropriate warnings without stopping execution
                    # Requirements: 7.1, 7.2 - Continue processing even if individual records fail
                    logger.debug(f"Failed to apply semantic mappings to record {i}: {e}")
                    
                    # Use error handler for individual record failures
                    fallback_result = self.error_handler.handle_semantic_mapping_error(
                        e, context={'operation': 'apply_to_record', 'record_index': i}
                    )
                    
                    if fallback_result.success and fallback_result.result:
                        # Use fallback mapper
                        fallback_results = fallback_result.result.apply_to_correlation_results(
                            [result], wing_id, pipeline_id, artifact_type
                        )
                        enhanced_results.extend(fallback_results)
                    else:
                        # Fallback strategy: include original record with fallback metadata
                        fallback_result = self._create_fallback_result(result, str(e))
                        enhanced_results.append(fallback_result)
                    
                    self.stats.total_records_processed += 1
                    self.stats.fallback_count += 1
            
            # Record performance metrics
            execution_time_ms = (time.time() - start_time) * 1000
            self.monitor.record_semantic_mapping_metrics(
                operation_name="apply_to_correlation_results",
                records_processed=self.stats.total_records_processed,
                mappings_applied=self.stats.mappings_applied,
                execution_time_ms=execution_time_ms
            )
            
            # Log statistics (debug level only)
            logger.debug(f"Semantic mapping completed: {self.stats.mappings_applied} mappings on {self.stats.total_records_processed} records")
            
            # TASK 4 FIX: Apply identity-level semantic mapping instead of per-record
            # Only accumulate stats globally - don't print anything here
            # Let the global accumulator handle batched output
            self._accumulate_global_stats()
            
            self.monitor.complete_operation(operation_id, success=True, output_size=len(enhanced_results))
            
        except Exception as e:
            # Task 6.1: Critical failure handling with graceful degradation
            # Requirements: 7.1, 7.2, 7.3 - Never crash correlation due to semantic mapping issues
            execution_time_ms = (time.time() - start_time) * 1000
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
            logger.error(f"Critical semantic mapping failure: {e}")
            print(f"[SEMANTIC] ERROR: Critical failure - continuing without semantic mapping")
            
            # Handle critical failure with error handler
            fallback_result = self.error_handler.handle_semantic_mapping_error(
                e, context={'operation': 'apply_to_correlation_results', 'total_results': len(results)}
            )
            
            if fallback_result.success and fallback_result.result:
                # Use fallback mapper for all results
                logger.warning(f"Using fallback semantic mapping for all results: {fallback_result.message}")
                enhanced_results = fallback_result.result.apply_to_correlation_results(
                    results, wing_id, pipeline_id, artifact_type
                )
            else:
                # Return original results with error indication - correlation continues
                logger.warning(f"Returning original results without semantic enhancement due to: {e}")
                enhanced_results = self._create_error_results(results, str(e))
        
        return enhanced_results
    
    def _apply_semantic_mappings_to_record(self, 
                                         record: Dict[str, Any],
                                         wing_id: Optional[str] = None,
                                         pipeline_id: Optional[str] = None,
                                         artifact_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Apply semantic mappings to a single record with fallback handling.
        
        Args:
            record: Single correlation result record
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            artifact_type: Optional artifact type
            
        Returns:
            Enhanced record with semantic mapping information
        """
        enhanced_record = record.copy()
        
        try:
            # Apply semantic mappings using the manager's apply_to_record method
            matching_mappings = self.semantic_manager.apply_to_record(
                record, artifact_type, wing_id, pipeline_id
            )
            
            if matching_mappings:
                # Add semantic mapping information to the record
                semantic_info = {}
                
                for mapping in matching_mappings:
                    field_name = mapping.field
                    # Get the actual technical value from the record
                    actual_technical_value = str(record.get(field_name, ''))
                    
                    semantic_info[field_name] = {
                        'semantic_value': mapping.semantic_value,
                        'technical_value': actual_technical_value,  # Actual value from record
                        'description': mapping.description,
                        'category': mapping.category,
                        'severity': mapping.severity,
                        'confidence': mapping.confidence,
                        'mapping_source': mapping.mapping_source,
                        'rule_name': getattr(mapping, 'source', field_name)  # Rule name for display
                    }
                    
                    # Update statistics
                    self.stats.mappings_applied += 1
                    if mapping.pattern:
                        self.stats.pattern_matches += 1
                    else:
                        self.stats.exact_matches += 1
                    
                    if mapping.mapping_source == 'global':
                        self.stats.global_mappings_used += 1
                    elif self.current_case_id and mapping.scope != 'global':
                        self.stats.case_specific_mappings_used += 1
                
                enhanced_record['_semantic_mappings'] = semantic_info
            else:
                # No mappings found - count unmapped fields
                for field_name in record.keys():
                    if not field_name.startswith('_'):  # Skip internal fields
                        self.stats.unmapped_fields += 1
                
                # Create minimal semantic info for unmapped fields
                enhanced_record['_semantic_mappings'] = {}
                enhanced_record['_semantic_mapping_status'] = 'no_mappings_found'
        
        except Exception as e:
            # Semantic manager failure - attempt recovery
            logger.warning(f"Semantic mapping manager failed for record: {e}")
            self.stats.manager_failure_count += 1
            
            # Attempt recovery
            self.stats.recovery_attempt_count += 1
            if self.handle_semantic_manager_failure(e):
                self.stats.successful_recovery_count += 1
                
                # Retry the mapping after recovery
                try:
                    matching_mappings = self.semantic_manager.apply_to_record(
                        record, artifact_type, wing_id, pipeline_id
                    )
                    
                    if matching_mappings:
                        semantic_info = {}
                        for mapping in matching_mappings:
                            field_name = mapping.field
                            # Get the actual technical value from the record
                            actual_technical_value = str(record.get(field_name, ''))
                            
                            semantic_info[field_name] = {
                                'semantic_value': mapping.semantic_value,
                                'technical_value': actual_technical_value,  # Actual value from record
                                'description': mapping.description,
                                'category': mapping.category,
                                'severity': mapping.severity,
                                'confidence': mapping.confidence,
                                'mapping_source': mapping.mapping_source,
                                'rule_name': getattr(mapping, 'source', field_name)  # Rule name for display
                            }
                            self.stats.mappings_applied += 1
                        
                        enhanced_record['_semantic_mappings'] = semantic_info
                        enhanced_record['_semantic_mapping_status'] = 'recovered'
                    else:
                        enhanced_record['_semantic_mappings'] = {}
                        enhanced_record['_semantic_mapping_status'] = 'recovered_no_mappings'
                        
                except Exception as retry_error:
                    # Recovery failed - use fallback
                    logger.error(f"Semantic mapping retry after recovery failed: {retry_error}")
                    enhanced_record = self._create_fallback_result(record, f"Recovery retry failed: {retry_error}")
                    self.stats.fallback_count += 1
            else:
                # Recovery failed - use fallback
                enhanced_record = self._create_fallback_result(record, f"Manager failure and recovery failed: {e}")
                self.stats.fallback_count += 1
        
        return enhanced_record
    
    def _create_fallback_result(self, 
                              original_record: Dict[str, Any], 
                              error_message: str) -> Dict[str, Any]:
        """
        Create a fallback result when semantic mapping fails.
        
        Args:
            original_record: Original record that failed semantic mapping
            error_message: Error message from the failure
            
        Returns:
            Record with fallback semantic information
        """
        fallback_record = original_record.copy()
        
        # Add fallback semantic information
        fallback_semantic_info = {}
        
        # For each field in the record, create a basic fallback semantic mapping
        for field_name, field_value in original_record.items():
            if not field_name.startswith('_'):  # Skip internal fields
                fallback_semantic_info[field_name] = {
                    'semantic_value': str(field_value),  # Use raw value as semantic value
                    'technical_value': str(field_value),  # Include technical value for consistency
                    'description': f'Raw value (semantic mapping failed: {error_message})',
                    'category': 'unknown',
                    'severity': 'info',
                    'confidence': 0.0,  # Zero confidence for fallback
                    'mapping_source': 'fallback',
                    'rule_name': 'fallback'  # Indicate this is a fallback mapping
                }
        
        fallback_record['_semantic_mappings'] = fallback_semantic_info
        fallback_record['_semantic_mapping_fallback'] = True
        fallback_record['_semantic_mapping_error'] = error_message
        
        logger.debug(f"Created fallback result with {len(fallback_semantic_info)} fields due to: {error_message}")
        
        return fallback_record
    
    def handle_semantic_manager_failure(self, error: Exception) -> bool:
        """
        Handle failures in the semantic mapping manager.
        
        Args:
            error: Exception that occurred
            
        Returns:
            True if recovery was successful, False otherwise
        """
        try:
            logger.error(f"Semantic mapping manager failure: {error}")
            
            # Attempt to reinitialize the semantic manager
            from ..config.semantic_mapping import SemanticMappingManager
            self.semantic_manager = SemanticMappingManager()
            
            # Reload global configuration
            self._load_global_configuration()
            
            # Reload case-specific mappings if we have a current case
            if self.current_case_id:
                self.load_case_specific_mappings(self.current_case_id)
            
            logger.info("Successfully recovered semantic mapping manager")
            return True
            
        except Exception as recovery_error:
            logger.error(f"Failed to recover semantic mapping manager: {recovery_error}")
            return False
    
    def is_healthy(self) -> bool:
        """
        Check if the semantic mapping integration is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            # Test basic functionality
            test_record = {'test_field': 'test_value'}
            test_mappings = self.semantic_manager.apply_to_record(test_record)
            return True
        except Exception as e:
            logger.warning(f"Semantic mapping integration health check failed: {e}")
            return False
    
    def get_fallback_statistics(self) -> Dict[str, int]:
        """
        Get statistics about fallback usage.
        
        Returns:
            Dictionary with fallback statistics
        """
        return {
            'total_fallbacks': getattr(self.stats, 'fallback_count', 0),
            'manager_failures': getattr(self.stats, 'manager_failure_count', 0),
            'recovery_attempts': getattr(self.stats, 'recovery_attempt_count', 0),
            'successful_recoveries': getattr(self.stats, 'successful_recovery_count', 0)
        }
    
    def get_semantic_display_data(self, 
                                record: Dict[str, Any], 
                                artifact_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get semantic information for UI display.
        
        Args:
            record: Record to get semantic data for
            artifact_type: Optional artifact type
            
        Returns:
            Dictionary with semantic display information
        """
        display_data = {
            'has_semantic_mappings': False,
            'semantic_fields': {},
            'unmapped_fields': [],
            'mapping_summary': {
                'total_fields': 0,
                'mapped_fields': 0,
                'unmapped_fields': 0
            }
        }
        
        # Check if record has semantic mapping information
        semantic_info = record.get('_semantic_mappings', {})
        
        if semantic_info:
            display_data['has_semantic_mappings'] = True
            display_data['semantic_fields'] = semantic_info
        
        # Count mapped vs unmapped fields
        total_fields = 0
        mapped_fields = 0
        
        for field_name, field_value in record.items():
            if not field_name.startswith('_'):  # Skip internal fields
                total_fields += 1
                
                if field_name in semantic_info:
                    mapped_fields += 1
                else:
                    display_data['unmapped_fields'].append({
                        'field': field_name,
                        'value': str(field_value),
                        'suggestion': self._suggest_semantic_mapping(field_name, field_value, artifact_type)
                    })
        
        display_data['mapping_summary'] = {
            'total_fields': total_fields,
            'mapped_fields': mapped_fields,
            'unmapped_fields': total_fields - mapped_fields
        }
        
        return display_data
    
    def _suggest_semantic_mapping(self, 
                                field_name: str, 
                                field_value: Any, 
                                artifact_type: Optional[str] = None) -> Optional[str]:
        """
        Suggest a semantic mapping for an unmapped field.
        
        Args:
            field_name: Name of the field
            field_value: Value of the field
            artifact_type: Optional artifact type
            
        Returns:
            Suggestion string or None
        """
        # Simple heuristic-based suggestions
        field_lower = field_name.lower()
        value_str = str(field_value).lower()
        
        # Common field name patterns
        if 'event' in field_lower and 'id' in field_lower:
            return "Consider mapping Event IDs to semantic meanings (e.g., 4624 = User Login)"
        
        if 'status' in field_lower or 'code' in field_lower:
            return "Consider mapping status codes to semantic meanings"
        
        if 'process' in field_lower or 'executable' in field_lower:
            return "Consider mapping process names to application categories"
        
        if 'path' in field_lower or 'file' in field_lower:
            return "Consider normalizing file paths with environment variables"
        
        # Value-based suggestions
        if value_str.endswith('.exe'):
            return "Consider mapping executable names to application categories"
        
        if value_str.startswith('c:\\'):
            return "Consider normalizing Windows paths"
        
        return None
    
    def _log_mapping_statistics(self):
        """Log semantic mapping statistics"""
        if self.stats.total_records_processed > 0:
            mapping_rate = (self.stats.mappings_applied / self.stats.total_records_processed) * 100
            
            logger.info(f"Semantic mapping statistics:")
            logger.info(f"  Records processed: {self.stats.total_records_processed}")
            logger.info(f"  Mappings applied: {self.stats.mappings_applied}")
            logger.info(f"  Mapping rate: {mapping_rate:.1f}%")
            logger.info(f"  Pattern matches: {self.stats.pattern_matches}")
            logger.info(f"  Exact matches: {self.stats.exact_matches}")
            
            if self.case_specific_enabled:
                logger.info(f"  Global mappings used: {self.stats.global_mappings_used}")
                logger.info(f"  Case-specific mappings used: {self.stats.case_specific_mappings_used}")
    
    def _accumulate_global_stats(self):
        """Accumulate stats globally without printing - TASK 4 FIX"""
        global _global_semantic_stats, _stats_lock
        
        try:
            if not _stats_lock:
                _global_semantic_stats.total_records_processed += self.stats.total_records_processed
                _global_semantic_stats.mappings_applied += self.stats.mappings_applied
                _global_semantic_stats.pattern_matches += self.stats.pattern_matches
                _global_semantic_stats.exact_matches += self.stats.exact_matches
                _global_semantic_stats.manager_failure_count += self.stats.manager_failure_count
                _global_semantic_stats.fallback_count += self.stats.fallback_count
        except Exception as e:
            logger.error(f"Error accumulating global semantic stats: {e}")
    
    def _print_gui_terminal_statistics(self):
        """Print semantic mapping statistics to GUI terminal - BATCHED SUMMARY ONLY"""
        global _global_semantic_stats, _stats_lock, _last_print_time, _print_threshold
        
        try:
            # Only print summary when we have accumulated significant data or enough time has passed
            current_time = time.time()
            time_threshold_met = (_last_print_time is None or 
                                (current_time - _last_print_time) > 120)  # 2 minutes instead of 1
            data_threshold_met = _global_semantic_stats.total_records_processed >= (_print_threshold * 5)  # 5x higher threshold
            
            # TASK 4 FIX: Much more restrictive printing - only print if we have significant mappings OR errors
            should_print = ((data_threshold_met and _global_semantic_stats.mappings_applied > 0) or 
                          time_threshold_met or 
                          _global_semantic_stats.manager_failure_count > 0)
            
            if should_print and _global_semantic_stats.total_records_processed > 0:
                total_processed = _global_semantic_stats.total_records_processed
                total_applied = _global_semantic_stats.mappings_applied
                
                if total_applied > 0:
                    mapping_rate = (total_applied / total_processed) * 100 if total_processed > 0 else 0
                    print(f"[SEMANTIC] Summary: {total_applied} mappings applied to {total_processed} records ({mapping_rate:.1f}%)")
                    
                    # Show only high-level rule type counts
                    rule_types = []
                    if _global_semantic_stats.exact_matches > 0:
                        rule_types.append(f"exact: {_global_semantic_stats.exact_matches}")
                    if _global_semantic_stats.pattern_matches > 0:
                        rule_types.append(f"pattern: {_global_semantic_stats.pattern_matches}")
                    
                    if rule_types:
                        print(f"[SEMANTIC] Rule types: {', '.join(rule_types)}")
                
                # TASK 4 FIX: Don't print "no mappings" messages at all - they're spam
                # Only show errors/warnings if any
                if _global_semantic_stats.manager_failure_count > 0:
                    print(f"[SEMANTIC] WARNING: {_global_semantic_stats.manager_failure_count} manager failures occurred")
                
                if _global_semantic_stats.fallback_count > 0:
                    print(f"[SEMANTIC] INFO: {_global_semantic_stats.fallback_count} records used fallback processing")
                
                # Reset global stats after printing and update last print time
                _global_semantic_stats = SemanticMappingStats()
                _last_print_time = current_time
                
        except Exception as e:
            # Don't let statistics printing crash the correlation
            logger.error(f"Error printing semantic statistics: {e}")
            # Don't print error to GUI - just continue silently
    
    def get_mapping_statistics(self) -> SemanticMappingStats:
        """
        Get current mapping statistics.
        
        Returns:
            SemanticMappingStats object with current statistics
        """
        return self.stats
    
    def is_enabled(self) -> bool:
        """
        Check if semantic mapping is enabled with configuration validation.
        
        Task 6.3: Enhanced configuration validation and warnings
        Requirements: 7.4, 7.5 - Log clear warnings when semantic mapping is disabled
        
        Returns:
            True if semantic mapping is enabled, False otherwise
        """
        try:
            # Task 6.3: Validate configuration manager availability
            if not self.config_manager:
                logger.debug("Semantic mapping enabled by default (no config manager)")
                return True
            
            # Task 6.3: Validate configuration structure and content
            config = self.config_manager.get_semantic_mapping_config()
            if not config:
                logger.warning("Semantic mapping configuration missing - defaulting to enabled")
                return True
            
            if not isinstance(config, dict):
                logger.error(f"Invalid semantic mapping configuration type: {type(config)} - defaulting to disabled")
                return False
            
            enabled = config.get('enabled', True)
            
            # Task 6.3: Log clear warnings when semantic mapping is disabled
            if not enabled:
                logger.info("Semantic mapping is explicitly disabled in configuration")
            
            return enabled
            
        except Exception as e:
            # Task 6.3: Provide helpful error messages for troubleshooting
            logger.error(f"Error checking semantic mapping configuration: {e}")
            logger.warning("Defaulting to semantic mapping disabled due to configuration error")
            return False
    
    def save_case_specific_mappings(self, 
                                  case_id: str, 
                                  mappings: List[SemanticMapping]) -> bool:
        """
        Save case-specific semantic mappings.
        
        Args:
            case_id: Case identifier
            mappings: List of semantic mappings to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not self.case_specific_enabled:
            logger.warning("Case-specific mappings are not enabled")
            return False
        
        try:
            if self.config_manager:
                config = self.config_manager.get_semantic_mapping_config()
                case_config = config.get('case_specific', {})
                storage_path_template = case_config.get('storage_path', 'cases/{case_id}/semantic_mappings.json')
                
                # Replace case_id placeholder
                storage_path = storage_path_template.format(case_id=case_id)
                case_mappings_path = Path(storage_path)
                
                # Ensure directory exists
                case_mappings_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Create temporary manager to save mappings
                temp_manager = SemanticMappingManager()
                for mapping in mappings:
                    temp_manager.add_mapping(mapping)
                
                temp_manager.save_to_file(case_mappings_path)
                logger.info(f"Saved {len(mappings)} case-specific semantic mappings for case {case_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save case-specific semantic mappings for case {case_id}: {e}")
        
        return False
    
    def get_available_mappings(self, 
                             artifact_type: Optional[str] = None,
                             wing_id: Optional[str] = None,
                             pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Get available semantic mappings for display or editing.
        
        Args:
            artifact_type: Optional artifact type filter
            wing_id: Optional wing ID filter
            pipeline_id: Optional pipeline ID filter
            
        Returns:
            List of available semantic mappings
        """
        if artifact_type:
            return self.semantic_manager.get_mappings_by_artifact(artifact_type)
        elif wing_id:
            return self.semantic_manager.get_all_mappings('wing', wing_id)
        elif pipeline_id:
            return self.semantic_manager.get_all_mappings('pipeline', pipeline_id=pipeline_id)
        else:
            return self.semantic_manager.get_all_mappings('global')
    
    def reload_configuration(self) -> bool:
        """
        Reload semantic mapping configuration from config manager.
        
        This method implements the ISemanticMappingIntegration interface requirement
        for live configuration reload without application restart.
        
        Returns:
            True if reload was successful, False otherwise
        """
        try:
            logger.info("Reloading semantic mapping configuration...")
            
            # Preserve current statistics
            preserved_stats = self.stats
            
            # Reload global configuration
            self._load_global_configuration()
            
            # Reload case-specific mappings if we have an active case
            if self.current_case_id:
                self.load_case_specific_mappings(self.current_case_id)
                logger.info(f"Reloaded case-specific mappings for case {self.current_case_id}")
            
            # Restore statistics (don't reset on reload)
            self.stats = preserved_stats
            
            logger.info("Successfully reloaded semantic mapping configuration")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reload semantic mapping configuration: {e}")
            return False
    
    def get_statistics(self) -> IntegrationStatistics:
        """
        Get semantic mapping integration statistics.
        
        This method implements the ISemanticMappingIntegration interface requirement.
        
        Returns:
            IntegrationStatistics object with operation counts and metrics
        """
        return IntegrationStatistics(
            total_operations=self.stats.total_records_processed,
            successful_operations=self.stats.mappings_applied,
            failed_operations=self.stats.manager_failure_count,
            fallback_count=self.stats.fallback_count
        )
    
    def _create_disabled_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create results when semantic mapping is disabled.
        
        Task 6.1: Graceful degradation - return original results with disabled metadata
        Requirements: 7.1, 7.2, 7.3
        
        Args:
            results: Original results
            
        Returns:
            Results with disabled semantic mapping metadata
        """
        disabled_results = []
        for result in results:
            disabled_result = result.copy()
            disabled_result['_semantic_mappings'] = {}
            disabled_result['_semantic_mapping_status'] = 'disabled'
            disabled_result['_semantic_mapping_message'] = 'Semantic mapping is disabled in configuration'
            disabled_results.append(disabled_result)
        
        # Update stats to reflect disabled state
        self.stats.total_records_processed = len(results)
        self.stats.mappings_applied = 0
        
        return disabled_results
    
    def _create_fallback_results(self, results: List[Dict[str, Any]], reason: str) -> List[Dict[str, Any]]:
        """
        Create fallback results when semantic mapping is unhealthy.
        
        Task 6.1: Graceful degradation - return original results with fallback metadata
        Requirements: 7.1, 7.2, 7.3
        
        Args:
            results: Original results
            reason: Reason for fallback
            
        Returns:
            Results with fallback semantic mapping metadata
        """
        fallback_results = []
        for result in results:
            fallback_result = result.copy()
            fallback_result['_semantic_mappings'] = {}
            fallback_result['_semantic_mapping_status'] = 'fallback'
            fallback_result['_semantic_mapping_message'] = f'Using fallback mode: {reason}'
            fallback_results.append(fallback_result)
        
        # Update stats to reflect fallback state
        self.stats.total_records_processed = len(results)
        self.stats.mappings_applied = 0
        self.stats.fallback_count = len(results)
        
        return fallback_results
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        Validate semantic mapping configuration and return detailed status.
        
        Task 6.3: Configuration validation and warnings
        Requirements: 7.4, 7.5 - Check configuration and provide helpful messages
        
        Returns:
            Dictionary with validation results and recommendations
        """
        validation_result = {
            'valid': True,
            'enabled': False,
            'warnings': [],
            'errors': [],
            'recommendations': [],
            'config_found': False,
            'manager_healthy': False,
            'rules_count': 0,
            'mappings_count': 0
        }
        
        try:
            # Check if configuration manager is available
            if not self.config_manager:
                validation_result['warnings'].append("No configuration manager available")
                validation_result['recommendations'].append("Ensure configuration manager is properly initialized")
                validation_result['enabled'] = True  # Default to enabled
                return validation_result
            
            # Check if configuration exists
            config = self.config_manager.get_semantic_mapping_config()
            if not config:
                validation_result['warnings'].append("Semantic mapping configuration not found")
                validation_result['recommendations'].append("Create semantic mapping configuration in config files")
                validation_result['enabled'] = True  # Default to enabled
                return validation_result
            
            validation_result['config_found'] = True
            
            # Validate configuration structure
            if not isinstance(config, dict):
                validation_result['valid'] = False
                validation_result['errors'].append(f"Invalid configuration type: {type(config)}, expected dict")
                validation_result['recommendations'].append("Fix configuration file format")
                return validation_result
            
            # Check if enabled
            validation_result['enabled'] = config.get('enabled', True)
            if not validation_result['enabled']:
                validation_result['warnings'].append("Semantic mapping is disabled in configuration")
                validation_result['recommendations'].append("Set 'enabled': true in semantic mapping configuration to enable features")
                return validation_result
            
            # Validate global mappings path
            global_mappings_path = config.get('global_mappings_path')
            if global_mappings_path:
                mappings_path = Path(global_mappings_path)
                if not mappings_path.exists():
                    validation_result['warnings'].append(f"Global mappings file not found: {global_mappings_path}")
                    validation_result['recommendations'].append(f"Create global mappings file at: {global_mappings_path}")
                elif not mappings_path.is_file():
                    validation_result['errors'].append(f"Global mappings path is not a file: {global_mappings_path}")
                    validation_result['recommendations'].append("Ensure global mappings path points to a valid JSON file")
                    validation_result['valid'] = False
            else:
                validation_result['warnings'].append("No global mappings path configured")
                validation_result['recommendations'].append("Configure 'global_mappings_path' to load custom semantic rules")
            
            # Validate case-specific configuration
            case_config = config.get('case_specific', {})
            if case_config:
                if not isinstance(case_config, dict):
                    validation_result['errors'].append(f"Invalid case-specific config type: {type(case_config)}")
                    validation_result['recommendations'].append("Fix case-specific configuration format")
                    validation_result['valid'] = False
                else:
                    case_enabled = case_config.get('enabled', False)
                    if case_enabled:
                        storage_path = case_config.get('storage_path')
                        if not storage_path:
                            validation_result['errors'].append("Case-specific mappings enabled but no storage_path configured")
                            validation_result['recommendations'].append("Configure 'storage_path' for case-specific mappings")
                            validation_result['valid'] = False
            
            # Check semantic manager health
            validation_result['manager_healthy'] = self.is_healthy()
            if not validation_result['manager_healthy']:
                validation_result['warnings'].append("Semantic manager health check failed")
                validation_result['recommendations'].append("Check semantic manager initialization and configuration files")
            
            # Count available rules and mappings
            try:
                if hasattr(self.semantic_manager, 'global_rules'):
                    validation_result['rules_count'] = len(self.semantic_manager.global_rules)
                if hasattr(self.semantic_manager, 'global_mappings'):
                    validation_result['mappings_count'] = sum(len(v) for v in self.semantic_manager.global_mappings.values())
                
                if validation_result['rules_count'] == 0 and validation_result['mappings_count'] == 0:
                    validation_result['warnings'].append("No semantic rules or mappings found")
                    validation_result['recommendations'].append("Add semantic mapping rules to configuration files")
            except Exception as e:
                validation_result['warnings'].append(f"Could not count rules and mappings: {e}")
            
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Configuration validation failed: {e}")
            validation_result['recommendations'].append("Check configuration files and permissions")
        
        return validation_result
    
    def print_final_summary(self):
        """Print final semantic mapping summary at end of correlation"""
        global _global_semantic_stats
        
        try:
            total_processed = _global_semantic_stats.total_records_processed
            total_applied = _global_semantic_stats.mappings_applied
            
            if total_processed > 0:
                if total_applied > 0:
                    mapping_rate = (total_applied / total_processed) * 100
                    print(f"[SEMANTIC] Final Summary: {total_applied} mappings applied to {total_processed} records ({mapping_rate:.1f}%)")
                    
                    # Show rule type breakdown
                    rule_types = []
                    if _global_semantic_stats.exact_matches > 0:
                        rule_types.append(f"exact: {_global_semantic_stats.exact_matches}")
                    if _global_semantic_stats.pattern_matches > 0:
                        rule_types.append(f"pattern: {_global_semantic_stats.pattern_matches}")
                    
                    if rule_types:
                        print(f"[SEMANTIC] Rule types: {', '.join(rule_types)}")
                else:
                    print(f"[SEMANTIC] Final Summary: No semantic mappings applied to {total_processed} records")
                
                # Show any issues
                if _global_semantic_stats.manager_failure_count > 0:
                    print(f"[SEMANTIC] WARNING: {_global_semantic_stats.manager_failure_count} manager failures")
                
                if _global_semantic_stats.fallback_count > 0:
                    print(f"[SEMANTIC] INFO: {_global_semantic_stats.fallback_count} records used fallback")
            
            # Reset global stats
            _global_semantic_stats = SemanticMappingStats()
            
        except Exception as e:
            logger.error(f"Error printing final semantic summary: {e}")
    
    def reset_global_stats(self):
        """Reset global semantic mapping statistics"""
        global _global_semantic_stats
        _global_semantic_stats = SemanticMappingStats()
        """
        Print detailed configuration status to GUI terminal.
        
        Task 6.3: Provide helpful error messages for troubleshooting
        Requirements: 7.4, 7.5 - Clear warnings and helpful messages
        """
        try:
            validation = self.validate_configuration()
            
            print("[SEMANTIC] Configuration Status:")
            print(f"[SEMANTIC]   Valid: {'Yes' if validation['valid'] else 'No'}")
            print(f"[SEMANTIC]   Enabled: {'Yes' if validation['enabled'] else 'No'}")
            print(f"[SEMANTIC]   Config Found: {'Yes' if validation['config_found'] else 'No'}")
            print(f"[SEMANTIC]   Manager Healthy: {'Yes' if validation['manager_healthy'] else 'No'}")
            print(f"[SEMANTIC]   Rules: {validation['rules_count']}")
            print(f"[SEMANTIC]   Mappings: {validation['mappings_count']}")
            
            if validation['errors']:
                print("[SEMANTIC] Errors:")
                for error in validation['errors']:
                    print(f"[SEMANTIC]   ❌ {error}")
            
            if validation['warnings']:
                print("[SEMANTIC] Warnings:")
                for warning in validation['warnings']:
                    print(f"[SEMANTIC]   ⚠️  {warning}")
            
            if validation['recommendations']:
                print("[SEMANTIC] Recommendations:")
                for rec in validation['recommendations']:
                    print(f"[SEMANTIC]   💡 {rec}")
                    
        except Exception as e:
            print(f"[SEMANTIC] ERROR: Could not print configuration status: {e}")
    
    def _create_error_results(self, results: List[Dict[str, Any]], error_message: str) -> List[Dict[str, Any]]:
        """
        Create error results when semantic mapping fails completely.
        
        Task 6.1: Graceful degradation - return original results with error metadata
        Requirements: 7.1, 7.2, 7.3
        
        Args:
            results: Original results
            error_message: Error message
            
        Returns:
            Results with error semantic mapping metadata
        """
        error_results = []
        for result in results:
            error_result = result.copy()
            error_result['_semantic_mappings'] = {}
            error_result['_semantic_mapping_status'] = 'error'
            error_result['_semantic_mapping_error'] = error_message
            error_result['_semantic_mapping_message'] = 'Semantic mapping failed - correlation continued without enhancement'
            error_results.append(error_result)
        
        # Update stats to reflect error state
        self.stats.total_records_processed = len(results)
        self.stats.mappings_applied = 0
        self.stats.manager_failure_count = 1
        self.stats.fallback_count = len(results)
        
        return error_results