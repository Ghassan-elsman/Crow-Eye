"""
Identity-Level Semantic Processor

Applies semantic mappings to unique identities (not individual records) and manages 
the identity-level semantic enhancement workflow. This processor ensures each unique 
identity is processed exactly once, applying semantic rules based on identity type 
and context, then marks identities as processed.

This is the core component that implements the identity-level semantic mapping 
architecture, replacing per-record semantic processing with identity-level processing.
"""

import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from .identity_registry import IdentityRegistry, IdentityRecord

logger = logging.getLogger(__name__)


@dataclass
class IdentityProcessorStatistics:
    """Statistics for identity-level semantic processing operations"""
    identities_processed: int = 0
    mappings_applied: int = 0
    pattern_matches: int = 0
    exact_matches: int = 0
    enhancement_errors: int = 0
    fallback_count: int = 0
    processing_time_seconds: float = 0.0
    identities_by_type: Dict[str, int] = field(default_factory=dict)


class IdentityLevelSemanticProcessor:
    """
    Identity-Level Semantic Processor - Applies semantic mappings to unique identities.
    
    This processor implements the core identity-level semantic mapping workflow:
    1. Load semantic mapping configuration
    2. Process each unique identity in the registry (not individual records)
    3. Apply relevant semantic rules based on identity type and context
    4. Create semantic metadata for the identity
    5. Mark identity as processed in the registry
    
    Key architectural benefits:
    - Processes each unique identity exactly once (not per-record)
    - Applies semantic rules based on identity type and context
    - Provides progress updates for large identity sets
    - Handles errors gracefully without stopping processing
    - Integrates with existing SemanticMappingIntegration
    
    Requirements: 9.1, 9.2, 9.3, 9.5
    Property 1: Identity Processing Uniqueness
    Property 6: Semantic Processing Isolation
    """
    
    def __init__(self, semantic_integration=None, debug_mode: bool = False):
        """
        Initialize Identity-Level Semantic Processor.
        
        Args:
            semantic_integration: SemanticMappingIntegration instance for applying mappings
            debug_mode: Enable debug logging
        """
        self.semantic_integration = semantic_integration
        self.debug_mode = debug_mode
        self.statistics = IdentityProcessorStatistics()
        
        if self.debug_mode:
            logger.info("[Identity-Level Semantic Processor] Initialized")
    
    def process_identities(self, identity_registry: IdentityRegistry, 
                          wing_configs: Optional[List[Any]] = None) -> IdentityProcessorStatistics:
        """
        Process all identities in the registry with semantic mappings.
        
        This is the main entry point for the identity-level semantic processing workflow.
        Processes each unique identity exactly once (not per-record), applying semantic rules
        and marking identities as processed.
        
        Task 17.1: Optimized for batch operations and efficient data structures
        - Process unique identities rather than individual records (Requirement 13.1)
        - Use batch operations for large datasets (Requirement 13.3)
        - Implement efficient identity registry data structures
        
        Args:
            identity_registry: Registry containing unique identities to process
            wing_configs: Optional list of wing configurations for context
            
        Returns:
            IdentityProcessorStatistics with processing results
            
        Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 13.1, 13.3
        Property 1: Identity Processing Uniqueness
        Property 6: Semantic Processing Isolation
        Property 17: Identity-Level Semantic Processing
        Property 19: Batch Operations for Large Datasets
        """
        # Reset statistics for this processing run
        self.statistics = IdentityProcessorStatistics()
        start_time = time.time()
        
        if self.debug_mode:
            logger.info(f"[Identity-Level Semantic Processor] Starting processing for {identity_registry.get_unique_identity_count()} identities")
        
        # Check if semantic integration is available
        if not self.semantic_integration:
            logger.warning("[Identity-Level Semantic Processor] No semantic integration available, skipping processing")
            self.statistics.processing_time_seconds = time.time() - start_time
            return self.statistics
        
        # Check if semantic mapping is enabled
        if not self.semantic_integration.is_enabled():
            if self.debug_mode:
                logger.info("[Identity-Level Semantic Processor] Semantic mapping is disabled, skipping processing")
            self.statistics.processing_time_seconds = time.time() - start_time
            return self.statistics
        
        # Get all pending identities (not yet processed)
        # Task 17.1: Process unique identities rather than individual records (Requirement 13.1)
        pending_identities = identity_registry.get_pending_identities()
        total_identities = len(pending_identities)
        
        if total_identities == 0:
            if self.debug_mode:
                logger.info("[Identity-Level Semantic Processor] No pending identities to process")
            self.statistics.processing_time_seconds = time.time() - start_time
            return self.statistics
        
        if self.debug_mode:
            logger.info(f"[Identity-Level Semantic Processor] Processing {total_identities} unique identities")
        
        # Task 8.4: Initialize progress reporter for semantic matching
        # Requirements: 4.1, 4.2, 4.3, 4.4
        # Reports progress every 10% (at 10%, 20%, 30%, etc.)
        try:
            from ..engine.progress_tracking import CorrelationProgressReporter
        except ImportError:
            # Fallback: create a simple progress reporter
            class SimpleProgressReporter:
                def __init__(self, total_items, report_percentage_interval, phase_name):
                    self.total_items = total_items
                    self.processed = 0
                    self.phase_name = phase_name
                
                def update(self, items_processed=1):
                    self.processed += items_processed
                    if self.processed % max(1, self.total_items // 10) == 0:
                        pct = (self.processed / self.total_items * 100) if self.total_items > 0 else 0
                        print(f"[{self.phase_name}] Progress: {pct:.1f}% ({self.processed:,}/{self.total_items:,})")
                
                def force_report(self):
                    pct = (self.processed / self.total_items * 100) if self.total_items > 0 else 0
                    print(f"[{self.phase_name}] Progress: {pct:.1f}% ({self.processed:,}/{self.total_items:,})")
            
            CorrelationProgressReporter = SimpleProgressReporter
        
        progress_reporter = CorrelationProgressReporter(
            total_items=total_identities,
            report_percentage_interval=10.0,  # Report every 10%
            phase_name="Semantic Matching"
        )
        
        # Report initial semantic progress (0%)
        logger.info("Starting semantic matching phase...")
        progress_reporter.force_report()
        
        # Task 17.1: Use batch operations for large datasets (Requirement 13.3)
        # Determine batch size based on dataset size
        batch_size = self.determine_optimal_batch_size(total_identities)
        
        if total_identities >= 1000:
            # Use batch processing for large datasets
            logger.info(f"[Identity-Level Semantic Processor] Using batch processing with batch size {batch_size}")
            self._process_identities_in_batches(pending_identities, batch_size, progress_reporter)
        else:
            # Use sequential processing for small datasets
            self._process_identities_sequentially(pending_identities, progress_reporter)
        
        # Task 8.4: Report final semantic progress (100%)
        # Requirements: 4.1, 4.5
        logger.info("Semantic matching phase complete")
        progress_reporter.force_report()
        
        # Calculate processing time
        self.statistics.processing_time_seconds = time.time() - start_time
        
        if self.debug_mode:
            logger.info(f"[Identity-Level Semantic Processor] Completed: {self.statistics.identities_processed} identities processed, "
                       f"{self.statistics.mappings_applied} mappings applied in {self.statistics.processing_time_seconds:.2f}s")
        
        return self.statistics
    
    def determine_optimal_batch_size(self, total_identities: int) -> int:
        """
        Determine optimal batch size based on dataset size.
        
        Task 17.1: Implement efficient batch sizing for large datasets
        This method is public to allow testing and verification of batch sizing logic.
        
        Args:
            total_identities: Total number of identities to process
            
        Returns:
            Optimal batch size
            
        Requirements: 13.3
        Property 19: Batch Operations for Large Datasets
        """
        # Use adaptive batch sizing based on dataset size
        if total_identities < 1000:
            return total_identities  # Process all at once for small datasets
        elif total_identities < 10000:
            return 500  # Medium batches for medium datasets
        elif total_identities < 100000:
            return 1000  # Larger batches for large datasets
        else:
            return 2000  # Very large batches for very large datasets
    
    def _process_identities_in_batches(self, pending_identities: List[IdentityRecord], 
                                      batch_size: int, 
                                      progress_reporter) -> None:
        """
        Process identities in batches for optimal performance on large datasets.
        
        Task 17.1: Use batch operations for large datasets (Requirement 13.3)
        
        Args:
            pending_identities: List of identities to process
            batch_size: Number of identities per batch
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.3
        Property 19: Batch Operations for Large Datasets
        """
        total_identities = len(pending_identities)
        
        # Process identities in batches
        for batch_start in range(0, total_identities, batch_size):
            batch_end = min(batch_start + batch_size, total_identities)
            batch = pending_identities[batch_start:batch_end]
            
            if self.debug_mode:
                logger.debug(f"[Identity-Level Semantic Processor] Processing batch {batch_start//batch_size + 1} "
                           f"({batch_start+1}-{batch_end} of {total_identities})")
            
            # Process each identity in the batch
            for identity_record in batch:
                self._process_single_identity(identity_record, progress_reporter)
    
    def _process_identities_sequentially(self, pending_identities: List[IdentityRecord],
                                        progress_reporter) -> None:
        """
        Process identities sequentially for small datasets.
        
        Task 17.1: Efficient processing for small datasets
        
        Args:
            pending_identities: List of identities to process
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.1
        """
        # Process each identity sequentially
        for identity_record in pending_identities:
            self._process_single_identity(identity_record, progress_reporter)
    
    def _process_single_identity(self, identity_record: IdentityRecord, 
                                 progress_reporter) -> None:
        """
        Process a single identity with semantic mapping.
        
        Task 17.1: Core identity processing logic extracted for reuse
        
        Args:
            identity_record: Identity to process
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.1
        Property 17: Identity-Level Semantic Processing
        """
        try:
            # Apply semantic mapping to this identity
            semantic_data = self.apply_semantic_mapping_to_identity(identity_record)
            
            # Check if there was an error in semantic data
            if semantic_data.get('_error'):
                # Mark identity as error
                identity_record.mark_error(semantic_data['_error'])
                self.statistics.enhancement_errors += 1
                self.statistics.fallback_count += 1
            else:
                # Mark identity as processed with semantic data
                identity_record.mark_processed(semantic_data)
                self.statistics.identities_processed += 1
                
                # Track identities by type
                identity_type = identity_record.identity_type
                if identity_type not in self.statistics.identities_by_type:
                    self.statistics.identities_by_type[identity_type] = 0
                self.statistics.identities_by_type[identity_type] += 1
                
                # Count mappings applied (Requirement 5.1 - accumulate for summary)
                if semantic_data and len(semantic_data) > 0:
                    # Don't count internal fields starting with _ or _no_mappings flag
                    mapping_count = sum(1 for key in semantic_data.keys() 
                                      if not key.startswith('_'))
                    self.statistics.mappings_applied += mapping_count
            
            # Task 8.4: Update progress (will auto-report at 10%, 20%, 30%, etc.)
            # Requirements: 4.2, 4.3, 4.4
            progress_reporter.update(items_processed=1)
            
        except Exception as e:
            # Handle errors gracefully - continue processing other identities
            # Safely get identity value for logging (may fail if identity_record is malformed)
            try:
                identity_value = identity_record.identity_value
            except Exception:
                identity_value = "<unknown>"
            
            logger.error(f"[Identity-Level Semantic Processor] Error processing identity '{identity_value}': {e}")
            
            # Mark identity as error (if possible)
            try:
                identity_record.mark_error(str(e))
            except Exception as mark_error_ex:
                logger.error(f"[Identity-Level Semantic Processor] Failed to mark identity as error: {mark_error_ex}")
            
            # Update error statistics
            self.statistics.enhancement_errors += 1
            self.statistics.fallback_count += 1
    
    def apply_semantic_mapping_to_identity(self, identity_record: IdentityRecord) -> Dict[str, Any]:
        """
        Apply semantic mappings to a single identity.
        
        This method applies relevant semantic rules based on the identity's type
        and context. It creates semantic metadata that will be propagated to all
        records sharing this identity.
        
        Args:
            identity_record: Identity record to enhance
            
        Returns:
            Dictionary with semantic mapping data
            
        Requirements: 9.2, 9.3
        Property 1: Identity Processing Uniqueness
        Property 6: Semantic Processing Isolation
        """
        semantic_data = {}
        
        try:
            # Check if semantic integration is available
            if not self.semantic_integration:
                return semantic_data
            
            # Create a synthetic record for semantic mapping lookup
            # This represents the identity itself, not any specific record
            # IMPORTANT: Include field names that semantic rules expect
            identity_lookup_record = {
                'identity_value': identity_record.identity_value,
                'identity_type': identity_record.identity_type,
                '_feather_id': '_identity',  # Special feather ID for identity-level matching
                '_is_identity_lookup': True  # Flag to indicate this is identity-level lookup
            }
            
            # Add identity value to common field names that semantic rules look for
            # This ensures semantic rules can match against the identity value
            if identity_record.identity_type == 'name':
                # Application/program name fields
                identity_lookup_record['ApplicationName'] = identity_record.identity_value
                identity_lookup_record['ProgramName'] = identity_record.identity_value
                identity_lookup_record['ProcessName'] = identity_record.identity_value
                identity_lookup_record['ExecutableName'] = identity_record.identity_value
                identity_lookup_record['app_name'] = identity_record.identity_value
                identity_lookup_record['application'] = identity_record.identity_value
            elif identity_record.identity_type == 'path':
                # File path fields
                identity_lookup_record['FilePath'] = identity_record.identity_value
                identity_lookup_record['FullPath'] = identity_record.identity_value
                identity_lookup_record['Location'] = identity_record.identity_value
                identity_lookup_record['path'] = identity_record.identity_value
                identity_lookup_record['file_path'] = identity_record.identity_value
            elif identity_record.identity_type == 'hash':
                # Hash fields
                identity_lookup_record['SHA256'] = identity_record.identity_value
                identity_lookup_record['MD5'] = identity_record.identity_value
                identity_lookup_record['FileHash'] = identity_record.identity_value
                identity_lookup_record['hash'] = identity_record.identity_value
            
            # Determine artifact type from identity type
            artifact_type = self._map_identity_type_to_artifact_type(identity_record.identity_type)
            
            # Apply semantic mappings using the integration layer
            # This will use the existing SemanticMappingManager to find relevant rules
            matching_mappings = self.semantic_integration.semantic_manager.apply_to_record(
                identity_lookup_record,
                artifact_type=artifact_type
            )
            
            # Process matching mappings - store as list to support multiple semantic values
            if matching_mappings:
                semantic_mappings_list = []
                
                for mapping in matching_mappings:
                    # Create semantic metadata for this mapping
                    mapping_data = {
                        'semantic_value': mapping.semantic_value,
                        'technical_value': identity_record.identity_value,
                        'description': mapping.description,
                        'category': mapping.category,
                        'severity': mapping.severity,
                        'confidence': mapping.confidence,
                        'mapping_source': mapping.mapping_source,
                        'rule_name': getattr(mapping, 'source', 'unknown')
                    }
                    
                    # Add to list (supports multiple semantic results per identity)
                    semantic_mappings_list.append(mapping_data)
                    
                    # Update statistics
                    if mapping.pattern:
                        self.statistics.pattern_matches += 1
                    else:
                        self.statistics.exact_matches += 1
                
                # Store all mappings as a list
                semantic_data['semantic_mappings'] = semantic_mappings_list
            
            # If no mappings found, return empty dict (Requirement 5.3 - no spam messages)
            # The statistics will track this as an identity processed with 0 mappings
            if not semantic_data:
                semantic_data = {}
        
        except Exception as e:
            # Safely get identity information for error logging
            try:
                identity_value = identity_record.identity_value
            except Exception:
                identity_value = "<unknown>"
            
            try:
                identity_type = identity_record.identity_type
            except Exception:
                identity_type = "<unknown>"
            
            logger.error(f"[Identity-Level Semantic Processor] Error applying semantic mapping to identity '{identity_value}': {e}")
            
            # Create error semantic data (don't increment stats here - will be done in main loop)
            semantic_data = {
                '_error': str(e),
                '_identity_value': identity_value,
                '_identity_type': identity_type
            }
        
        return semantic_data
    
    def _map_identity_type_to_artifact_type(self, identity_type: str) -> Optional[str]:
        """
        Map identity type to artifact type for semantic mapping lookup.
        
        Args:
            identity_type: Type of identity (e.g., 'file_path', 'process_name')
            
        Returns:
            Artifact type string or None
        """
        # Map common identity types to artifact types
        type_mapping = {
            'file_path': 'file',
            'process_name': 'process',
            'application': 'process',
            'user_id': 'user',
            'hash': 'hash',
            'network_address': 'network',
            'registry_key': 'registry'
        }
        
        return type_mapping.get(identity_type.lower())
    
    def get_processing_statistics(self) -> IdentityProcessorStatistics:
        """
        Get statistics from the last processing run.
        
        Returns:
            IdentityProcessorStatistics object
        """
        return self.statistics
    
    def reset_statistics(self):
        """Reset processing statistics"""
        self.statistics = IdentityProcessorStatistics()
    
    def is_enabled(self) -> bool:
        """
        Check if identity-level semantic processing is enabled.
        
        Returns:
            True if enabled, False otherwise
        """
        if not self.semantic_integration:
            return False
        
        return self.semantic_integration.is_enabled()
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        Validate identity-level semantic processing configuration.
        
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            "valid": True,
            "warnings": [],
            "errors": []
        }
        
        # Check if semantic integration is available
        if not self.semantic_integration:
            validation_results["valid"] = False
            validation_results["errors"].append("No semantic integration available")
            return validation_results
        
        # Check if semantic mapping is enabled
        if not self.semantic_integration.is_enabled():
            validation_results["warnings"].append("Semantic mapping is disabled")
        
        # Check if semantic manager is healthy
        if hasattr(self.semantic_integration, 'is_healthy'):
            if not self.semantic_integration.is_healthy():
                validation_results["warnings"].append("Semantic integration health check failed")
        
        return validation_results

    def determine_optimal_batch_size(self, total_identities: int) -> int:
        """
        Determine optimal batch size based on dataset size.
        
        Task 17.1: Implement efficient batch sizing for large datasets
        This method is public to allow testing and verification of batch sizing logic.
        
        Args:
            total_identities: Total number of identities to process
            
        Returns:
            Optimal batch size
            
        Requirements: 13.3
        Property 19: Batch Operations for Large Datasets
        """
        # Use adaptive batch sizing based on dataset size
        if total_identities < 1000:
            return total_identities  # Process all at once for small datasets
        elif total_identities < 10000:
            return 500  # Medium batches for medium datasets
        elif total_identities < 100000:
            return 1000  # Larger batches for large datasets
        else:
            return 2000  # Very large batches for very large datasets
    
    def _process_identities_in_batches(self, pending_identities: List[IdentityRecord], 
                                      batch_size: int, 
                                      progress_reporter) -> None:
        """
        Process identities in batches for optimal performance on large datasets.
        
        Task 17.1: Use batch operations for large datasets (Requirement 13.3)
        
        Args:
            pending_identities: List of identities to process
            batch_size: Number of identities per batch
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.3
        Property 19: Batch Operations for Large Datasets
        """
        total_identities = len(pending_identities)
        
        # Process identities in batches
        for batch_start in range(0, total_identities, batch_size):
            batch_end = min(batch_start + batch_size, total_identities)
            batch = pending_identities[batch_start:batch_end]
            
            if self.debug_mode:
                logger.debug(f"[Identity-Level Semantic Processor] Processing batch {batch_start//batch_size + 1} "
                           f"({batch_start+1}-{batch_end} of {total_identities})")
            
            # Process each identity in the batch
            for identity_record in batch:
                self._process_single_identity(identity_record, progress_reporter)
    
    def _process_identities_sequentially(self, pending_identities: List[IdentityRecord],
                                        progress_reporter) -> None:
        """
        Process identities sequentially for small datasets.
        
        Task 17.1: Efficient processing for small datasets
        
        Args:
            pending_identities: List of identities to process
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.1
        """
        # Process each identity sequentially
        for identity_record in pending_identities:
            self._process_single_identity(identity_record, progress_reporter)
    
    def _process_single_identity(self, identity_record: IdentityRecord, 
                                 progress_reporter) -> None:
        """
        Process a single identity with semantic mapping.
        
        Task 17.1: Core identity processing logic extracted for reuse
        
        Args:
            identity_record: Identity to process
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.1
        Property 17: Identity-Level Semantic Processing
        """
        try:
            # Apply semantic mapping to this identity
            semantic_data = self.apply_semantic_mapping_to_identity(identity_record)
            
            # Check if there was an error in semantic data
            if semantic_data.get('_error'):
                # Mark identity as error
                identity_record.mark_error(semantic_data['_error'])
                self.statistics.enhancement_errors += 1
                self.statistics.fallback_count += 1
            else:
                # Mark identity as processed with semantic data
                identity_record.mark_processed(semantic_data)
                self.statistics.identities_processed += 1
                
                # Track identities by type
                identity_type = identity_record.identity_type
                if identity_type not in self.statistics.identities_by_type:
                    self.statistics.identities_by_type[identity_type] = 0
                self.statistics.identities_by_type[identity_type] += 1
                
                # Count mappings applied (Requirement 5.1 - accumulate for summary)
                if semantic_data and len(semantic_data) > 0:
                    # Don't count internal fields starting with _ or _no_mappings flag
                    mapping_count = sum(1 for key in semantic_data.keys() 
                                      if not key.startswith('_'))
                    self.statistics.mappings_applied += mapping_count
            
            # Task 8.4: Update progress (will auto-report at 10%, 20%, 30%, etc.)
            # Requirements: 4.2, 4.3, 4.4
            progress_reporter.update(items_processed=1)
            
        except Exception as e:
            # Handle errors gracefully - continue processing other identities
            # Safely get identity value for logging (may fail if identity_record is malformed)
            try:
                identity_value = identity_record.identity_value
            except Exception:
                identity_value = "<unknown>"
            
            logger.error(f"[Identity-Level Semantic Processor] Error processing identity '{identity_value}': {e}")
            
            # Mark identity as error (if possible)
            try:
                identity_record.mark_error(str(e))
            except Exception as mark_error_ex:
                logger.error(f"[Identity-Level Semantic Processor] Failed to mark identity as error: {mark_error_ex}")
            
            # Update error statistics
            self.statistics.enhancement_errors += 1
            self.statistics.fallback_count += 1

    def determine_optimal_batch_size(self, total_identities: int) -> int:
        """
        Determine optimal batch size based on dataset size.
        
        Task 17.1: Implement efficient batch sizing for large datasets
        This method is public to allow testing and verification of batch sizing logic.
        
        Args:
            total_identities: Total number of identities to process
            
        Returns:
            Optimal batch size
            
        Requirements: 13.3
        Property 19: Batch Operations for Large Datasets
        """
        # Use adaptive batch sizing based on dataset size
        if total_identities < 1000:
            return total_identities  # Process all at once for small datasets
        elif total_identities < 10000:
            return 500  # Medium batches for medium datasets
        elif total_identities < 100000:
            return 1000  # Larger batches for large datasets
        else:
            return 2000  # Very large batches for very large datasets
    
    def _process_identities_in_batches(self, pending_identities: List[IdentityRecord], 
                                      batch_size: int, 
                                      progress_reporter) -> None:
        """
        Process identities in batches for optimal performance on large datasets.
        
        Task 17.1: Use batch operations for large datasets (Requirement 13.3)
        
        Args:
            pending_identities: List of identities to process
            batch_size: Number of identities per batch
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.3
        Property 19: Batch Operations for Large Datasets
        """
        total_identities = len(pending_identities)
        
        # Process identities in batches
        for batch_start in range(0, total_identities, batch_size):
            batch_end = min(batch_start + batch_size, total_identities)
            batch = pending_identities[batch_start:batch_end]
            
            if self.debug_mode:
                logger.debug(f"[Identity-Level Semantic Processor] Processing batch {batch_start//batch_size + 1} "
                           f"({batch_start+1}-{batch_end} of {total_identities})")
            
            # Process each identity in the batch
            for identity_record in batch:
                self._process_single_identity(identity_record, progress_reporter)
    
    def _process_identities_sequentially(self, pending_identities: List[IdentityRecord],
                                        progress_reporter) -> None:
        """
        Process identities sequentially for small datasets.
        
        Task 17.1: Efficient processing for small datasets
        
        Args:
            pending_identities: List of identities to process
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.1
        """
        # Process each identity sequentially
        for identity_record in pending_identities:
            self._process_single_identity(identity_record, progress_reporter)
    
    def _process_single_identity(self, identity_record: IdentityRecord, 
                                 progress_reporter) -> None:
        """
        Process a single identity with semantic mapping.
        
        Task 17.1: Core identity processing logic extracted for reuse
        
        Args:
            identity_record: Identity to process
            progress_reporter: Progress reporter for tracking
            
        Requirements: 13.1
        Property 17: Identity-Level Semantic Processing
        """
        try:
            # Apply semantic mapping to this identity
            semantic_data = self.apply_semantic_mapping_to_identity(identity_record)
            
            # Check if there was an error in semantic data
            if semantic_data.get('_error'):
                # Mark identity as error
                identity_record.mark_error(semantic_data['_error'])
                self.statistics.enhancement_errors += 1
                self.statistics.fallback_count += 1
            else:
                # Mark identity as processed with semantic data
                identity_record.mark_processed(semantic_data)
                self.statistics.identities_processed += 1
                
                # Track identities by type
                identity_type = identity_record.identity_type
                if identity_type not in self.statistics.identities_by_type:
                    self.statistics.identities_by_type[identity_type] = 0
                self.statistics.identities_by_type[identity_type] += 1
                
                # Count mappings applied (Requirement 5.1 - accumulate for summary)
                if semantic_data and len(semantic_data) > 0:
                    # Don't count internal fields starting with _ or _no_mappings flag
                    mapping_count = sum(1 for key in semantic_data.keys() 
                                      if not key.startswith('_'))
                    self.statistics.mappings_applied += mapping_count
            
            # Task 8.4: Update progress (will auto-report at 10%, 20%, 30%, etc.)
            # Requirements: 4.2, 4.3, 4.4
            progress_reporter.update(items_processed=1)
            
        except Exception as e:
            # Handle errors gracefully - continue processing other identities
            # Safely get identity value for logging (may fail if identity_record is malformed)
            try:
                identity_value = identity_record.identity_value
            except Exception:
                identity_value = "<unknown>"
            
            logger.error(f"[Identity-Level Semantic Processor] Error processing identity '{identity_value}': {e}")
            
            # Mark identity as error (if possible)
            try:
                identity_record.mark_error(str(e))
            except Exception as mark_error_ex:
                logger.error(f"[Identity-Level Semantic Processor] Failed to mark identity as error: {mark_error_ex}")
            
            # Update error statistics
            self.statistics.enhancement_errors += 1
            self.statistics.fallback_count += 1
