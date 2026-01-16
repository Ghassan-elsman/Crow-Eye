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
        """Load global semantic mapping configuration"""
        operation_id = self.monitor.start_operation("semantic_mapping", "load_global_config")
        
        try:
            if self.config_manager:
                config = self.config_manager.get_semantic_mapping_config()
                if config and config.get('enabled', True):
                    global_mappings_path = config.get('global_mappings_path')
                    if global_mappings_path and Path(global_mappings_path).exists():
                        self.semantic_manager.load_from_file(Path(global_mappings_path))
                        logger.info(f"Loaded global semantic mappings from {global_mappings_path}")
                    
                    # Check if case-specific mappings are enabled
                    case_config = config.get('case_specific', {})
                    self.case_specific_enabled = case_config.get('enabled', False)
            
            self.monitor.complete_operation(operation_id, success=True)
                    
        except Exception as e:
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
            # Handle error with graceful degradation
            fallback_result = self.error_handler.handle_semantic_mapping_error(
                e, context={'operation': 'load_global_configuration'}
            )
            
            if fallback_result.success:
                logger.warning(f"Using fallback for global configuration: {fallback_result.message}")
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
        operation_id = self.monitor.start_operation(
            "semantic_mapping", 
            "apply_to_correlation_results",
            context={'wing_id': wing_id, 'pipeline_id': pipeline_id, 'artifact_type': artifact_type},
            input_size=len(results)
        )
        
        start_time = time.time()
        enhanced_results = []
        self.stats = SemanticMappingStats()  # Reset stats
        
        try:
            for result in results:
                try:
                    enhanced_result = self._apply_semantic_mappings_to_record(
                        result, wing_id, pipeline_id, artifact_type
                    )
                    enhanced_results.append(enhanced_result)
                    self.stats.total_records_processed += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to apply semantic mappings to record: {e}")
                    
                    # Use error handler for individual record failures
                    fallback_result = self.error_handler.handle_semantic_mapping_error(
                        e, context={'operation': 'apply_to_record', 'record_keys': list(result.keys())}
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
            
            # Log statistics
            self._log_mapping_statistics()
            
            self.monitor.complete_operation(operation_id, success=True, output_size=len(enhanced_results))
            
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
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
                # Return original results with error indication
                logger.error(f"Critical semantic mapping failure, returning original results: {e}")
                enhanced_results = results
        
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
                    
                    logger.debug(f"Applied semantic mapping: {field_name}='{actual_technical_value}' -> '{mapping.semantic_value}' (confidence: {mapping.confidence})")
                    
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
                logger.debug(f"Record enhanced with {len(semantic_info)} semantic mappings")
            else:
                # No mappings found - count unmapped fields and create basic fallback
                unmapped_field_names = []
                for field_name in record.keys():
                    if not field_name.startswith('_'):  # Skip internal fields
                        self.stats.unmapped_fields += 1
                        unmapped_field_names.append(field_name)
                
                # Create minimal semantic info for unmapped fields
                enhanced_record['_semantic_mappings'] = {}
                enhanced_record['_semantic_mapping_status'] = 'no_mappings_found'
                
                # Debug logging for troubleshooting
                logger.debug(f"No semantic mappings found for record. Fields checked: {unmapped_field_names[:5]}{'...' if len(unmapped_field_names) > 5 else ''}")
        
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
                        logger.debug(f"Record enhanced with {len(semantic_info)} semantic mappings after recovery")
                    else:
                        enhanced_record['_semantic_mappings'] = {}
                        enhanced_record['_semantic_mapping_status'] = 'recovered_no_mappings'
                        logger.debug("No semantic mappings found after recovery")
                        
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
    
    def get_mapping_statistics(self) -> SemanticMappingStats:
        """
        Get current mapping statistics.
        
        Returns:
            SemanticMappingStats object with current statistics
        """
        return self.stats
    
    def is_enabled(self) -> bool:
        """
        Check if semantic mapping is enabled.
        
        Returns:
            True if semantic mapping is enabled, False otherwise
        """
        if self.config_manager:
            config = self.config_manager.get_semantic_mapping_config()
            return config.get('enabled', True) if config else True
        return True
    
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