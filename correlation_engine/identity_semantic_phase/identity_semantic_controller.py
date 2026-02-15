"""
Identity Semantic Controller

Orchestrates identity-level semantic mapping workflow after correlation completion.
This controller implements the architecture that processes unique identities
in a dedicated phase rather than applying semantic mappings per-record.
"""

import logging
import time
import re
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from ..engine.correlation_result import CorrelationResult
from ..integration.semantic_mapping_integration import SemanticMappingIntegration

logger = logging.getLogger(__name__)


@dataclass
class IdentitySemanticConfig:
    """Configuration for Identity Semantic Phase"""
    enabled: bool = True
    semantic_mapping_enabled: bool = True
    identity_extraction_enabled: bool = True
    progress_reporting_enabled: bool = True
    batch_size: int = 1000
    max_identities_per_batch: int = 10000
    fallback_to_per_record: bool = True
    debug_mode: bool = False
    disable_per_record_semantic_mapping: bool = True  # NEW: Disable semantic mapping during correlation


@dataclass
class IdentitySemanticStatistics:
    """Statistics for Identity Semantic Phase execution"""
    total_identities_extracted: int = 0
    unique_identities_processed: int = 0
    semantic_mappings_applied: int = 0
    records_enhanced: int = 0
    processing_time_seconds: float = 0.0
    identity_extraction_time_seconds: float = 0.0
    semantic_enhancement_time_seconds: float = 0.0
    data_propagation_time_seconds: float = 0.0
    errors_encountered: int = 0
    fallback_used: bool = False
    
    # Performance monitoring metrics (Requirement 5.5)
    memory_usage_start_mb: float = 0.0
    memory_usage_peak_mb: float = 0.0
    memory_usage_end_mb: float = 0.0
    memory_delta_mb: float = 0.0
    system_memory_percent_start: float = 0.0
    system_memory_percent_peak: float = 0.0
    system_memory_percent_end: float = 0.0
    
    # Success/failure rate tracking (Requirement 5.5)
    semantic_enhancement_success_count: int = 0
    semantic_enhancement_failure_count: int = 0
    semantic_enhancement_success_rate: float = 0.0
    identities_with_mappings: int = 0
    identities_without_mappings: int = 0
    
    # Performance metrics (Requirement 5.5)
    identities_per_second: float = 0.0
    records_per_second: float = 0.0
    average_time_per_identity_ms: float = 0.0


class IdentitySemanticController:
    """
    Controller for Identity Semantic Phase that orchestrates identity-level semantic mapping.
    
    This controller implements the architecture where semantic mappings are applied
    to unique identities after correlation completion, rather than per-record during correlation.
    
    Key responsibilities:
    - Detect when correlation engines complete processing
    - Coordinate identity extraction and semantic enhancement phases
    - Handle configuration and error management
    - Provide progress reporting for large identity sets
    
    Requirements: 2.1, 6.1, 10.3
    Property 3: Final Analysis Phase Workflow
    """
    
    def __init__(self, config: Optional[IdentitySemanticConfig] = None,
                 semantic_integration: Optional[SemanticMappingIntegration] = None):
        """
        Initialize Identity Semantic Controller.
        
        Args:
            config: Configuration for the phase
            semantic_integration: Optional semantic mapping integration instance
        """
        self.config = config or IdentitySemanticConfig()
        self.semantic_integration = semantic_integration
        self.statistics = IdentitySemanticStatistics()
        
        # Lazy initialization of components
        self._identity_extractor = None
        self._identity_semantic_processor = None
        self._semantic_data_propagator = None
        self._semantic_data_propagator = None
        
        # Performance monitoring (Requirement 5.5)
        self._process = None
        if PSUTIL_AVAILABLE:
            try:
                self._process = psutil.Process()
            except Exception as e:
                logger.warning(f"[Identity Semantic Phase] Failed to initialize psutil process: {e}")
        
        if self.config.debug_mode:
            logger.info("[Identity Semantic Phase] Controller initialized")
    
    def is_enabled(self) -> bool:
        """
        Check if the Identity Semantic Phase is enabled.
        
        Returns:
            True if enabled, False otherwise
        """
        return self.config.enabled
    
    def should_disable_per_record_semantic_mapping(self) -> bool:
        """
        Check if per-record semantic mapping should be disabled during correlation.
        
        When the Identity Semantic Phase is enabled, semantic mappings should only
        be applied at the identity level in the final analysis phase, not during
        correlation processing.
        
        Returns:
            True if per-record semantic mapping should be disabled, False otherwise
            
        Requirements: 1.5, 2.5
        Property 6: Semantic Processing Isolation
        """
        # If Identity Semantic Phase is enabled and configured to disable per-record mapping
        return self.config.enabled and self.config.disable_per_record_semantic_mapping
    
    def execute_final_analysis(self, correlation_results: CorrelationResult, 
                              engine_type: str) -> CorrelationResult:
        """
        Execute the identity-level semantic mapping workflow.
        
        Args:
            correlation_results: Results from correlation engine
            engine_type: Type of engine ("identity_based" or "time_based")
            
        Returns:
            Enhanced correlation results with semantic data
            
        Requirements: 2.1, 2.2, 2.4, 5.1, 5.2, 5.3, 5.5
        Property 3: Final Analysis Phase Workflow
        Property 8: Output Verbosity Reduction
        """
        if not self.is_enabled():
            if self.config.debug_mode:
                logger.info("[Identity Semantic Phase] Phase disabled, returning original results")
            return correlation_results
        
        # Check if semantic mapping is enabled in settings
        try:
            from config.case_history_manager import CaseHistoryManager
            case_manager = CaseHistoryManager()
            wings_semantic_enabled = getattr(case_manager.global_config, 'wings_semantic_mapping_enabled', True)
            
            if not wings_semantic_enabled:
                print("[Identity Semantic Phase] ⚠ Semantic mapping is disabled in settings")
                print("[Identity Semantic Phase] You can enable it from Settings > General > Wings Semantic Mapping")
                logger.info("[Identity Semantic Phase] Semantic mapping disabled in settings, skipping")
                return correlation_results
        except Exception as e:
            # If we can't load settings, default to enabled (backward compatibility)
            if self.config.debug_mode:
                logger.warning(f"[Identity Semantic Phase] Could not load settings: {e}, defaulting to enabled")
        
        # Reset statistics for this execution
        self.statistics = IdentitySemanticStatistics()
        start_time = time.time()
        
        # Capture initial memory usage
        self._capture_memory_snapshot('start')
        
        try:
            if self.config.debug_mode:
                logger.info(f"[Identity Semantic Phase] Starting for {engine_type} engine")
            
            # Phase 1: Identity Extraction
            if self.config.identity_extraction_enabled:
                identity_registry = self._extract_identities(correlation_results, engine_type)
                self.statistics.total_identities_extracted = identity_registry.get_unique_identity_count()
                
                if self.config.debug_mode:
                    logger.info(f"[Identity Semantic Phase] Extracted {self.statistics.total_identities_extracted} unique identities")
                
                # Capture memory after extraction
                self._capture_memory_snapshot('peak')
            else:
                if self.config.debug_mode:
                    logger.info("[Identity Semantic Phase] Identity extraction disabled")
                return correlation_results
            
            # Phase 2: Semantic Enhancement using NEW query-based system
            if self.config.semantic_mapping_enabled:
                # Use the new query-based semantic evaluation system
                # This applies semantic mapping directly to the database
                logger.info("[Identity Semantic Phase] Starting semantic mapping to database...")
                logger.info(f"[Identity Semantic Phase] Database: {correlation_results.database_path}")
                logger.info(f"[Identity Semantic Phase] Execution ID: {correlation_results.execution_id}")
                
                enhancement_stats = self._apply_semantic_mapping_to_database(correlation_results)
                
                self.statistics.unique_identities_processed = enhancement_stats['identities_processed']
                self.statistics.semantic_mappings_applied = enhancement_stats['mappings_applied']
                self.statistics.records_enhanced = enhancement_stats['matches_updated']
                self.statistics.semantic_enhancement_time_seconds = enhancement_stats['processing_time']
                
                logger.info(
                    f"[Identity Semantic Phase] Semantic mapping complete: "
                    f"identities={enhancement_stats['identities_processed']}, "
                    f"mappings={enhancement_stats['mappings_applied']}, "
                    f"matches_updated={enhancement_stats['matches_updated']}"
                )
                
                if self.config.debug_mode:
                    logger.info(f"[Identity Semantic Phase] Applied semantic mapping to {enhancement_stats['matches_updated']} matches")
            else:
                if self.config.debug_mode:
                    logger.info("[Identity Semantic Phase] Semantic mapping disabled")
            
            self.statistics.processing_time_seconds = time.time() - start_time
            
            # Capture final memory usage (Requirement 5.5)
            self._capture_memory_snapshot('end')
            
            # Calculate performance metrics (Requirement 5.5)
            self._calculate_performance_metrics()
            
            # Task 17.2: Update correlation results with performance metrics
            # Requirements: 13.4
            self._update_correlation_results_with_performance_metrics(correlation_results)
            
            # Print final summary (Requirements 5.1, 5.2, 5.3, 3.5)
            self._print_final_summary()
            
            if self.config.debug_mode:
                logger.info(f"[Identity Semantic Phase] Completed in {self.statistics.processing_time_seconds:.2f}s")
            
            return correlation_results
            
        except Exception as e:
            self.statistics.errors_encountered += 1
            self.statistics.processing_time_seconds = time.time() - start_time
            
            # Capture final memory even on error (Requirement 5.5)
            self._capture_memory_snapshot('end')
            
            logger.error(f"[Identity Semantic Phase] Error during execution: {e}")
            
            # Fallback: return original results
            if self.config.fallback_to_per_record:
                self.statistics.fallback_used = True
                logger.warning("[Identity Semantic Phase] Falling back to original results")
                return correlation_results
            else:
                raise
    
    def _extract_identities(self, correlation_results: CorrelationResult, engine_type: str):
        """
        Extract unique identities from correlation results.
        
        Args:
            correlation_results: Results from correlation engine
            engine_type: Type of engine
            
        Returns:
            IdentityRegistry with extracted identities
        """
        extraction_start = time.time()
        
        # Lazy initialize identity extractor
        if not self._identity_extractor:
            from .identity_aggregator import IdentityAggregator
            self._identity_extractor = IdentityAggregator(debug_mode=self.config.debug_mode)
        
        # IMPORTANT: Save identity fields to database FIRST for streaming mode
        # This adds identity_value and identity_type fields that semantic mapping needs
        # force_update=True ensures fields are always updated with latest extraction logic
        if hasattr(correlation_results, 'streaming_mode') and correlation_results.streaming_mode:
            if hasattr(correlation_results, 'database_path') and hasattr(correlation_results, 'execution_id'):
                if correlation_results.database_path and correlation_results.execution_id is not None:
                    logger.info("[Identity Semantic Phase] Saving identity fields to database...")
                    updated_count = self._identity_extractor.save_identity_fields_to_database(
                        correlation_results.database_path,
                        correlation_results.execution_id,
                        force_update=True  # Always update to ensure latest extraction logic
                    )
                    logger.info(f"[Identity Semantic Phase] Saved identity fields to {updated_count:,} matches")
        
        # Extract identities using the aggregator
        identity_registry = self._identity_extractor.extract_identities(
            correlation_results, 
            engine_type
        )
        
        self.statistics.identity_extraction_time_seconds = time.time() - extraction_start
        
        return identity_registry
    
    def _enhance_identities(self, identity_registry):
        """
        Enhance identities with semantic mappings.
        
        Args:
            identity_registry: IdentityRegistry with extracted identities
            
        Returns:
            EnhancementStatistics from the enhancement phase
        """
        # Lazy initialize identity-level semantic processor
        if not self._identity_semantic_processor:
            from .identity_level_semantic_processor import IdentityLevelSemanticProcessor
            self._identity_semantic_processor = IdentityLevelSemanticProcessor(
                semantic_integration=self.semantic_integration,
                debug_mode=self.config.debug_mode
            )
        
        # Propagate cancellation flag if set
        if hasattr(self, '_cancelled'):
            self._identity_semantic_processor._cancelled = self._cancelled
        
        # Process identities using the identity-level semantic processor
        enhancement_stats = self._identity_semantic_processor.process_identities(identity_registry)
        
        return enhancement_stats
    
    def _create_fts_index(self, conn, execution_id):
        """
        Create FTS5 index for fast semantic search.
        
        This creates a virtual table that enables full-text search on feather_records,
        providing 10-100x speedup over LIKE queries.
        
        Args:
            conn: SQLite database connection
            execution_id: Execution ID to filter matches
            
        Returns:
            True if index was created, False if already exists
        """
        cursor = conn.cursor()
        
        # Check if FTS table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='matches_fts'
        """)
        
        if cursor.fetchone() is None:
            logger.info("[FTS5] Creating FTS5 virtual table for semantic search...")
            print("[FTS5] Creating FTS5 virtual table...")
            
            # Create FTS5 virtual table with porter stemming
            cursor.execute("""
                CREATE VIRTUAL TABLE matches_fts USING fts5(
                    match_id UNINDEXED,
                    feather_records,
                    tokenize='porter unicode61 remove_diacritics 1'
                )
            """)
            
            logger.info("[FTS5] Populating FTS5 index...")
            print("[FTS5] Populating FTS5 index (this may take 30-60 seconds)...")
            
            index_start = time.time()
            
            # Populate with data for this execution
            cursor.execute("""
                INSERT INTO matches_fts(match_id, feather_records)
                SELECT m.match_id, m.feather_records
                FROM matches m
                INNER JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (execution_id,))
            
            conn.commit()
            
            index_time = time.time() - index_start
            
            logger.info(f"[FTS5] Indexed {cursor.rowcount:,} matches in {index_time:.2f}s")
            print(f"[FTS5] Indexed {cursor.rowcount:,} matches in {index_time:.2f}s")
            
            return True
        else:
            logger.info("[FTS5] FTS5 index already exists")
            print("[FTS5] FTS5 index already exists")
            return False
    
    def _apply_semantic_mapping_to_database(self, correlation_results: CorrelationResult) -> Dict[str, Any]:
        """
        Apply semantic mapping to matches in the database using SQL-based approach.
        
        This method uses the SQLSemanticMapper which does ALL matching in the database
        using FTS5 + SQL JOIN, eliminating the slow Python matching loop.
        
        Expected Performance: ~25 seconds (vs 73 minutes in Python)
        
        Args:
            correlation_results: CorrelationResult with database_path and execution_id
            
        Returns:
            Dictionary with statistics:
                - identities_processed: Number of unique identities processed
                - mappings_applied: Number of semantic mappings applied
                - matches_updated: Number of matches updated with semantic data
                - processing_time: Time taken in seconds
        """
        logger.info("[Identity Semantic Phase] _apply_semantic_mapping_to_database() called")
        logger.info(f"[Identity Semantic Phase] Database path: {correlation_results.database_path}")
        logger.info(f"[Identity Semantic Phase] Execution ID: {correlation_results.execution_id}")
        
        start_time = time.time()
        
        # Initialize return statistics
        stats = {
            'identities_processed': 0,
            'mappings_applied': 0,
            'matches_updated': 0,
            'processing_time': 0.0
        }
        
        try:
            # Get database path and execution ID
            database_path = correlation_results.database_path
            execution_id = correlation_results.execution_id
            
            if not database_path or execution_id is None:
                logger.error("[Identity Semantic Phase] Missing database_path or execution_id")
                return stats
            
            logger.info(f"[Identity Semantic Phase] Initializing SQL-based semantic mapper...")
            
            # Initialize semantic evaluation system
            from ..config.semantic_mapping import SemanticMappingManager
            from .sql_semantic_mapper import SQLSemanticMapper
            
            semantic_manager = SemanticMappingManager()
            
            # Rules are automatically loaded in __init__ via _load_rules_from_json()
            logger.info(f"[Identity Semantic Phase] Loaded {len(semantic_manager.global_rules)} semantic rules")
            
            # Get all semantic rules
            rules = semantic_manager.get_rules(scope="global")
            logger.info(f"[Identity Semantic Phase] Loaded {len(rules)} semantic rules")
            
            if not rules:
                logger.warning("[Identity Semantic Phase] No semantic rules loaded, skipping semantic mapping")
                print("[Identity Semantic Phase] WARNING: No semantic rules loaded!")
                return stats
            
            # Filter to rules with conditions
            identity_rules = [rule for rule in rules if rule.conditions]
            
            logger.info(f"[Identity Semantic Phase] Using {len(identity_rules)} rules for semantic mapping")
            
            print(f"\n{'='*80}")
            print(f"SEMANTIC MAPPING - SQL-BASED APPROACH")
            print(f"{'='*80}")
            print(f"  Database: {database_path}")
            print(f"  Execution ID: {execution_id}")
            print(f"  Rules: {len(identity_rules)}")
            print(f"{'='*80}\n")
            
            # Use SQL-based semantic mapper
            mapper = SQLSemanticMapper(database_path, execution_id)
            
            # Apply semantic mapping using SQL
            stats = mapper.apply_semantic_mapping(identity_rules)
            
            logger.info(f"[Identity Semantic Phase] SQL-based semantic mapping complete")
            logger.info(f"[Identity Semantic Phase] Matches updated: {stats['matches_updated']:,}")
            logger.info(f"[Identity Semantic Phase] Processing time: {stats['processing_time']:.2f}s")
            
            return stats
            
        except Exception as e:
            logger.error(f"[Identity Semantic Phase] Error applying semantic mapping to database: {e}")
            import traceback
            traceback.print_exc()
            stats['processing_time'] = time.time() - start_time
            return stats
    
    def _propagate_semantic_data(self, identity_registry, correlation_results):
        """
        Propagate semantic data from identities to correlation results.
        
        Args:
            identity_registry: IdentityRegistry with enhanced identities
            correlation_results: CorrelationResult to enhance
            
        Returns:
            True if propagation succeeded, False otherwise
        """
        # Lazy initialize semantic data propagator
        if not self._semantic_data_propagator:
            from .semantic_data_propagator import SemanticDataPropagator
            self._semantic_data_propagator = SemanticDataPropagator(
                debug_mode=self.config.debug_mode
            )
        
        try:
            # Check if streaming mode
            if correlation_results.streaming_mode:
                # Streaming mode: propagate to database
                if not correlation_results.database_path or correlation_results.execution_id is None:
                    logger.error("[Identity Semantic Phase] Streaming mode enabled but database_path or execution_id missing")
                    if self.config.debug_mode:
                        logger.error(f"[Identity Semantic Phase] database_path={correlation_results.database_path}, execution_id={correlation_results.execution_id}")
                    return False
                
                if self.config.debug_mode:
                    logger.info(f"[Identity Semantic Phase] Propagating to database: {correlation_results.database_path}, execution_id={correlation_results.execution_id}")
                
                success = self._semantic_data_propagator.propagate_to_streaming_results(
                    identity_registry=identity_registry,
                    database_path=correlation_results.database_path,
                    execution_id=correlation_results.execution_id
                )
                
                if self.config.debug_mode:
                    logger.info(f"[Identity Semantic Phase] Database propagation {'succeeded' if success else 'failed'}")
                
                return success
            else:
                # Non-streaming mode: propagate to in-memory results
                if self.config.debug_mode:
                    logger.info("[Identity Semantic Phase] Propagating to in-memory results")
                
                success = self._semantic_data_propagator.propagate_to_correlation_results(
                    identity_registry=identity_registry,
                    correlation_results=correlation_results
                )
                
                return success
                
        except Exception as e:
            logger.error(f"[Identity Semantic Phase] Error propagating semantic data: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_propagation_record_count(self) -> int:
        """
        Get the number of records enhanced during propagation.
        
        Returns:
            Number of records enhanced
        """
        if self._semantic_data_propagator:
            stats = self._semantic_data_propagator.get_propagation_statistics()
            return stats.records_updated
        return 0
    
    def _capture_memory_snapshot(self, phase: str) -> None:
        """
        Capture memory usage snapshot for performance monitoring.
        
        Args:
            phase: Phase identifier ('start', 'peak', 'end')
            
        Requirements: 5.5
        """
        if not PSUTIL_AVAILABLE or not self._process:
            return
        
        try:
            # Get process memory
            process_mem = self._process.memory_info()
            process_mb = process_mem.rss / (1024 * 1024)
            
            # Get system memory
            system_mem = psutil.virtual_memory()
            system_percent = system_mem.percent
            
            # Store in statistics based on phase
            if phase == 'start':
                self.statistics.memory_usage_start_mb = process_mb
                self.statistics.system_memory_percent_start = system_percent
            elif phase == 'peak':
                self.statistics.memory_usage_peak_mb = max(
                    self.statistics.memory_usage_peak_mb,
                    process_mb
                )
                self.statistics.system_memory_percent_peak = max(
                    self.statistics.system_memory_percent_peak,
                    system_percent
                )
            elif phase == 'end':
                self.statistics.memory_usage_end_mb = process_mb
                self.statistics.system_memory_percent_end = system_percent
                
                # Calculate memory delta
                self.statistics.memory_delta_mb = (
                    self.statistics.memory_usage_end_mb - 
                    self.statistics.memory_usage_start_mb
                )
                
                # Update peak if end is higher
                self.statistics.memory_usage_peak_mb = max(
                    self.statistics.memory_usage_peak_mb,
                    process_mb
                )
                self.statistics.system_memory_percent_peak = max(
                    self.statistics.system_memory_percent_peak,
                    system_percent
                )
            
            if self.config.debug_mode:
                logger.debug(
                    f"[Identity Semantic Phase] Memory snapshot [{phase}]: "
                    f"Process: {process_mb:.1f} MB, System: {system_percent:.1f}%"
                )
                
        except Exception as e:
            logger.warning(f"[Identity Semantic Phase] Failed to capture memory snapshot: {e}")
    
    def _calculate_performance_metrics(self) -> None:
        """
        Calculate performance metrics from collected statistics.
        
        Requirements: 5.5
        """
        # Calculate success rate
        total_attempts = (
            self.statistics.semantic_enhancement_success_count + 
            self.statistics.semantic_enhancement_failure_count
        )
        if total_attempts > 0:
            self.statistics.semantic_enhancement_success_rate = (
                self.statistics.semantic_enhancement_success_count / total_attempts
            ) * 100.0
        
        # Calculate processing rates
        if self.statistics.processing_time_seconds > 0:
            self.statistics.identities_per_second = (
                self.statistics.unique_identities_processed / 
                self.statistics.processing_time_seconds
            )
            self.statistics.records_per_second = (
                self.statistics.records_enhanced / 
                self.statistics.processing_time_seconds
            )
        
        # Calculate average time per identity
        if self.statistics.unique_identities_processed > 0:
            self.statistics.average_time_per_identity_ms = (
                (self.statistics.semantic_enhancement_time_seconds / 
                 self.statistics.unique_identities_processed) * 1000.0
            )
    
    def _update_correlation_results_with_performance_metrics(self, correlation_results: CorrelationResult) -> None:
        """
        Update correlation results with semantic matching performance metrics.
        
        Task 17.2
        Requirements: 13.4
        
        Args:
            correlation_results: CorrelationResult to update with performance metrics
        """
        # Update correlation statistics with semantic matching metrics
        if hasattr(correlation_results, 'statistics'):
            stats = correlation_results.statistics
            
            # Set semantic matching metrics
            stats.semantic_matching_enabled = True
            stats.semantic_matching_duration_seconds = self.statistics.semantic_enhancement_time_seconds
            stats.semantic_identities_processed = self.statistics.unique_identities_processed
            stats.semantic_mappings_applied = self.statistics.semantic_mappings_applied
            stats.semantic_records_enhanced = self.statistics.records_enhanced
            stats.semantic_identities_per_second = self.statistics.identities_per_second
            stats.semantic_records_per_second = self.statistics.records_per_second
            
            # Calculate performance comparison
            stats.calculate_performance_comparison()
            
            if self.config.debug_mode:
                logger.info(
                    f"[Identity Semantic Phase] Updated correlation results with performance metrics: "
                    f"{stats.semantic_identities_processed} identities in {stats.semantic_matching_duration_seconds:.2f}s"
                )
                
                if stats.performance_improvement_factor > 0:
                    logger.info(
                        f"[Identity Semantic Phase] Performance improvement: "
                        f"{stats.performance_improvement_factor:.1f}x faster "
                        f"({stats.performance_improvement_percentage:.1f}% improvement)"
                    )
    
    def _print_final_summary(self):
        """
        Print final summary of Identity Semantic Phase execution.
        
        This method prints summary statistics after the Identity Semantic Phase completes,
        matching the output style of existing correlation engines.
        
        Requirements: 5.1, 5.2, 5.3, 3.5, 5.5
        Property 8: Output Verbosity Reduction
        """
        # Format processing time
        time_str = self._format_time(self.statistics.processing_time_seconds)
        
        # Print summary in correlation engine style
        print(f"\n{'='*70}")
        print(f"IDENTITY SEMANTIC PHASE COMPLETE")
        print(f"{'='*70}")
        print(f"  Unique identities processed: {self.statistics.unique_identities_processed:,}")
        print(f"  Semantic mappings applied: {self.statistics.semantic_mappings_applied:,}")
        print(f"  Records enhanced: {self.statistics.records_enhanced:,}")
        print(f"  Processing time: {time_str}")
        
        # Show phase breakdown if available
        if self.statistics.identity_extraction_time_seconds > 0:
            extraction_time = self._format_time(self.statistics.identity_extraction_time_seconds)
            print(f"    - Identity extraction: {extraction_time}")
        
        if self.statistics.semantic_enhancement_time_seconds > 0:
            enhancement_time = self._format_time(self.statistics.semantic_enhancement_time_seconds)
            print(f"    - Semantic enhancement: {enhancement_time}")
        
        if self.statistics.data_propagation_time_seconds > 0:
            propagation_time = self._format_time(self.statistics.data_propagation_time_seconds)
            print(f"    - Data propagation: {propagation_time}")
        
        # Show performance metrics (Requirement 5.5)
        print(f"\n  Performance Metrics:")
        if self.statistics.identities_per_second > 0:
            print(f"    - Identities/second: {self.statistics.identities_per_second:.1f}")
        if self.statistics.records_per_second > 0:
            print(f"    - Records/second: {self.statistics.records_per_second:.1f}")
        if self.statistics.average_time_per_identity_ms > 0:
            print(f"    - Avg time per identity: {self.statistics.average_time_per_identity_ms:.2f}ms")
        
        # Show success/failure rates
        if self.statistics.unique_identities_processed > 0:
            print(f"\n  Enhancement Results:")
            print(f"    - Identities with mappings: {self.statistics.identities_with_mappings:,}")
            print(f"    - Identities without mappings: {self.statistics.identities_without_mappings:,}")

            if self.statistics.semantic_enhancement_failure_count > 0:
                print(f"    - Failures: {self.statistics.semantic_enhancement_failure_count:,}")
        
        # Show memory usage (Requirement 5.5)
        if PSUTIL_AVAILABLE and self.statistics.memory_usage_start_mb > 0:
            print(f"\n  Memory Usage:")
            print(f"    - Start: {self.statistics.memory_usage_start_mb:.1f} MB "
                  f"(System: {self.statistics.system_memory_percent_start:.1f}%)")
            print(f"    - Peak: {self.statistics.memory_usage_peak_mb:.1f} MB "
                  f"(System: {self.statistics.system_memory_percent_peak:.1f}%)")
            print(f"    - End: {self.statistics.memory_usage_end_mb:.1f} MB "
                  f"(System: {self.statistics.system_memory_percent_end:.1f}%)")
            
            # Show delta with sign
            delta_sign = "+" if self.statistics.memory_delta_mb >= 0 else ""
            print(f"    - Delta: {delta_sign}{self.statistics.memory_delta_mb:.1f} MB")
        
        # Show warnings if any errors occurred
        if self.statistics.errors_encountered > 0:
            print(f"\n  ! Errors encountered: {self.statistics.errors_encountered}")
        
        if self.statistics.fallback_used:
            print(f"  ! Fallback to per-record processing was used")
        
        print(f"{'='*70}\n")
    
    def _format_time(self, seconds: float) -> str:
        """
        Format time duration in human-readable format.
        
        Args:
            seconds: Time duration in seconds
            
        Returns:
            Formatted time string (e.g., "1.5s", "2m 30s", "1h 15m")
        """
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
    
    def execute_final_analysis_multi_wing(self, 
                                         correlation_results_list: List[CorrelationResult], 
                                         engine_type: str) -> List[CorrelationResult]:
        """
        Execute identity-level semantic mapping workflow for multiple wings.
        
        This method aggregates identities from all wings, applies semantic mappings
        once per unique identity, and propagates the semantic data back to all
        wing results.
        
        Args:
            correlation_results_list: List of CorrelationResult objects from different wings
            engine_type: Type of engine ("identity_based" or "time_based")
            
        Returns:
            List of enhanced correlation results with semantic data
            
        Requirements: 10.5
        Property 13: Multi-Wing Scenario Support
        Property 3: Final Analysis Phase Workflow
        """
        if not self.is_enabled():
            if self.config.debug_mode:
                logger.info("[Identity Semantic Phase] Phase disabled, returning original results")
            return correlation_results_list
        
        # Check if semantic mapping is enabled in settings
        try:
            from config.case_history_manager import CaseHistoryManager
            case_manager = CaseHistoryManager()
            wings_semantic_enabled = getattr(case_manager.global_config, 'wings_semantic_mapping_enabled', True)
            
            if not wings_semantic_enabled:
                print("[Identity Semantic Phase] ⚠ Semantic mapping is disabled in settings")
                print("[Identity Semantic Phase] You can enable it from Settings > General > Wings Semantic Mapping")
                logger.info("[Identity Semantic Phase] Semantic mapping disabled in settings, skipping")
                return correlation_results_list
        except Exception as e:
            # If we can't load settings, default to enabled (backward compatibility)
            if self.config.debug_mode:
                logger.warning(f"[Identity Semantic Phase] Could not load settings: {e}, defaulting to enabled")
        
        # Reset statistics for this execution
        self.statistics = IdentitySemanticStatistics()
        start_time = time.time()
        
        # Capture initial memory usage
        self._capture_memory_snapshot('start')
        
        try:
            if self.config.debug_mode:
                logger.info(
                    f"[Identity Semantic Phase] Starting multi-wing processing for {len(correlation_results_list)} wings "
                    f"with {engine_type} engine"
                )
            
            # Phase 1: Multi-Wing Identity Extraction
            if self.config.identity_extraction_enabled:
                identity_registry = self._extract_identities_multi_wing(
                    correlation_results_list, engine_type
                )
                self.statistics.total_identities_extracted = identity_registry.get_unique_identity_count()
                
                if self.config.debug_mode:
                    logger.info(
                        f"[Identity Semantic Phase] Extracted {self.statistics.total_identities_extracted} "
                        f"unique identities across {len(correlation_results_list)} wings"
                    )
                
                # Capture memory after extraction
                self._capture_memory_snapshot('peak')
            else:
                if self.config.debug_mode:
                    logger.info("[Identity Semantic Phase] Identity extraction disabled")
                return correlation_results_list
            
            # Phase 2: Semantic Enhancement (if enabled and semantic integration available)
            if self.config.semantic_mapping_enabled and self.semantic_integration:
                enhancement_stats = self._enhance_identities(identity_registry)
                self.statistics.unique_identities_processed = enhancement_stats.identities_processed
                self.statistics.semantic_mappings_applied = enhancement_stats.mappings_applied
                self.statistics.semantic_enhancement_time_seconds = enhancement_stats.processing_time_seconds
                
                # Track success/failure rates
                self.statistics.semantic_enhancement_success_count = enhancement_stats.identities_processed - enhancement_stats.enhancement_errors
                self.statistics.semantic_enhancement_failure_count = enhancement_stats.enhancement_errors
                self.statistics.identities_with_mappings = sum(
                    1 for identity in identity_registry.get_processed_identities()
                    if identity.semantic_data and len([k for k in identity.semantic_data.keys() if not k.startswith('_')]) > 0
                )
                self.statistics.identities_without_mappings = self.statistics.unique_identities_processed - self.statistics.identities_with_mappings
                
                if self.config.debug_mode:
                    logger.info(
                        f"[Identity Semantic Phase] Enhanced {enhancement_stats.identities_processed} identities, "
                        f"applied {enhancement_stats.mappings_applied} mappings"
                    )
            else:
                if self.config.debug_mode:
                    if not self.config.semantic_mapping_enabled:
                        logger.info("[Identity Semantic Phase] Semantic mapping disabled")
                    elif not self.semantic_integration:
                        logger.info("[Identity Semantic Phase] No semantic integration available")
            
            # Phase 3: Data Propagation to All Wings
            propagation_start = time.time()
            total_records_enhanced = 0
            
            for correlation_results in correlation_results_list:
                propagation_success = self._propagate_semantic_data(identity_registry, correlation_results)
                
                if propagation_success:
                    total_records_enhanced += self._get_propagation_record_count()
                else:
                    if self.config.debug_mode:
                        logger.warning(
                            f"[Identity Semantic Phase] Data propagation failed for wing: "
                            f"{correlation_results.wing_name}"
                        )
            
            self.statistics.data_propagation_time_seconds = time.time() - propagation_start
            self.statistics.records_enhanced = total_records_enhanced
            
            if self.config.debug_mode:
                logger.info(
                    f"[Identity Semantic Phase] Propagated semantic data to {total_records_enhanced} records "
                    f"across {len(correlation_results_list)} wings"
                )
            
            self.statistics.processing_time_seconds = time.time() - start_time
            
            # Capture final memory usage
            self._capture_memory_snapshot('end')
            
            # Calculate performance metrics
            self._calculate_performance_metrics()
            
            # Print final summary
            self._print_final_summary_multi_wing(len(correlation_results_list))
            
            if self.config.debug_mode:
                logger.info(
                    f"[Identity Semantic Phase] Multi-wing processing completed in "
                    f"{self.statistics.processing_time_seconds:.2f}s"
                )
            
            return correlation_results_list
            
        except Exception as e:
            self.statistics.errors_encountered += 1
            self.statistics.processing_time_seconds = time.time() - start_time
            
            # Capture final memory even on error
            self._capture_memory_snapshot('end')
            
            logger.error(f"[Identity Semantic Phase] Error during multi-wing execution: {e}", exc_info=True)
            
            # Fallback: return original results
            if self.config.fallback_to_per_record:
                self.statistics.fallback_used = True
                logger.warning("[Identity Semantic Phase] Falling back to original results")
                return correlation_results_list
            else:
                raise
    
    def _extract_identities_multi_wing(self, correlation_results_list: List[CorrelationResult], 
                                      engine_type: str) -> 'IdentityRegistry':
        """
        Extract unique identities from multiple correlation results (multi-wing).
        
        Args:
            correlation_results_list: List of CorrelationResult objects
            engine_type: Type of engine
            
        Returns:
            IdentityRegistry with aggregated identities from all wings
            
        Requirements: 10.5
        Property 13: Multi-Wing Scenario Support
        """
        extraction_start = time.time()
        
        # Lazy initialize identity extractor
        if not self._identity_extractor:
            from .identity_aggregator import IdentityAggregator
            self._identity_extractor = IdentityAggregator(debug_mode=self.config.debug_mode)
        
        # Extract identities from multiple results using the aggregator
        identity_registry = self._identity_extractor.extract_identities_from_multiple_results(
            correlation_results_list, 
            engine_type
        )
        
        self.statistics.identity_extraction_time_seconds = time.time() - extraction_start
        
        return identity_registry
    
    def _print_final_summary_multi_wing(self, wing_count: int):
        """
        Print final summary for multi-wing identity semantic processing.
        
        Args:
            wing_count: Number of wings processed
            
        Requirements: 5.1, 5.2, 5.3, 3.5
        Property 8: Output Verbosity Reduction
        """
        print("\n" + "="*80)
        print("IDENTITY SEMANTIC PHASE SUMMARY (MULTI-WING)")
        print("="*80)
        
        # Wing information
        print(f"\nWings Processed: {wing_count}")
        
        # Identity extraction
        print(f"\nIdentity Extraction:")
        print(f"  Total Unique Identities: {self.statistics.total_identities_extracted}")
        print(f"  Extraction Time: {self.statistics.identity_extraction_time_seconds:.2f}s")
        
        # Semantic enhancement
        if self.config.semantic_mapping_enabled:
            print(f"\nSemantic Enhancement:")
            print(f"  Identities Processed: {self.statistics.unique_identities_processed}")
            print(f"  Mappings Applied: {self.statistics.semantic_mappings_applied}")
            print(f"  Identities with Mappings: {self.statistics.identities_with_mappings}")
            print(f"  Identities without Mappings: {self.statistics.identities_without_mappings}")
            
            if self.statistics.unique_identities_processed > 0:
                success_rate = (self.statistics.semantic_enhancement_success_count / 
                              self.statistics.unique_identities_processed * 100)
                print(f"  Success Rate: {success_rate:.1f}%")
            
            print(f"  Enhancement Time: {self.statistics.semantic_enhancement_time_seconds:.2f}s")
        
        # Data propagation
        print(f"\nData Propagation:")
        print(f"  Records Enhanced: {self.statistics.records_enhanced}")
        print(f"  Propagation Time: {self.statistics.data_propagation_time_seconds:.2f}s")
        
        # Performance metrics
        print(f"\nPerformance:")
        print(f"  Total Processing Time: {self.statistics.processing_time_seconds:.2f}s")
        
        if self.statistics.processing_time_seconds > 0:
            identities_per_sec = self.statistics.total_identities_extracted / self.statistics.processing_time_seconds
            print(f"  Identities/Second: {identities_per_sec:.1f}")
            
            if self.statistics.records_enhanced > 0:
                records_per_sec = self.statistics.records_enhanced / self.statistics.processing_time_seconds
                print(f"  Records/Second: {records_per_sec:.1f}")
        
        # Memory usage (if available)
        if PSUTIL_AVAILABLE and self.statistics.memory_usage_start_mb > 0:
            print(f"\nMemory Usage:")
            print(f"  Start: {self.statistics.memory_usage_start_mb:.1f} MB")
            print(f"  Peak: {self.statistics.memory_usage_peak_mb:.1f} MB")
            print(f"  End: {self.statistics.memory_usage_end_mb:.1f} MB")
            print(f"  Delta: {self.statistics.memory_delta_mb:+.1f} MB")
        
        # Errors
        if self.statistics.errors_encountered > 0:
            print(f"\nErrors: {self.statistics.errors_encountered}")
        
        if self.statistics.fallback_used:
            print("\n⚠️  Fallback to per-record processing was used")
        
        print("="*80 + "\n")
    
    def get_phase_statistics(self) -> IdentitySemanticStatistics:
        """
        Get statistics from the last phase execution.
        
        Returns:
            IdentitySemanticStatistics object
        """
        return self.statistics
    
    def reset_statistics(self):
        """Reset phase statistics"""
        self.statistics = IdentitySemanticStatistics()
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        Validate the current configuration.
        
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            "valid": True,
            "warnings": [],
            "errors": []
        }
        
        # Check batch size
        if self.config.batch_size <= 0:
            validation_results["valid"] = False
            validation_results["errors"].append("batch_size must be positive")
        
        # Check max identities per batch
        if self.config.max_identities_per_batch <= 0:
            validation_results["valid"] = False
            validation_results["errors"].append("max_identities_per_batch must be positive")
        
        # Warn if semantic mapping enabled but no integration
        if self.config.semantic_mapping_enabled and not self.semantic_integration:
            validation_results["warnings"].append(
                "semantic_mapping_enabled but no semantic_integration provided"
            )
        
        return validation_results
