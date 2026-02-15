"""
Identity-Based Engine Adapter

Adapter that wraps the IdentityCorrelationEngine to provide BaseCorrelationEngine interface
and integrates semantic mapping, weighted scoring, and progress tracking systems.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from .base_engine import BaseCorrelationEngine, EngineMetadata, FilterConfig
from .identity_correlation_engine import IdentityCorrelationEngine
from .correlation_result import CorrelationResult, CorrelationMatch
from .weighted_scoring import WeightedScoringEngine
from .progress_tracking import ProgressTracker, ProgressListener, ProgressEvent, ProgressEventType, CorrelationProgressReporter, CorrelationStallMonitor, CorrelationStallException
from ..integration.semantic_mapping_integration import SemanticMappingIntegration, SemanticMappingStats
from ..integration.weighted_scoring_integration import WeightedScoringIntegration
from ..config.identifier_extraction_config import WingsConfig

logger = logging.getLogger(__name__)


class IdentityBasedEngineAdapter(BaseCorrelationEngine):
    """
    Adapter for Identity-Based Correlation Engine with integrated semantic mapping,
    weighted scoring, and progress tracking.
    
    This adapter wraps the existing IdentityCorrelationEngine and provides:
    - BaseCorrelationEngine interface compliance
    - Semantic mapping integration
    - Weighted scoring integration  
    - Progress tracking integration
    - Enhanced result formatting
    """
    
    def __init__(self, config: Any, filters: Optional[FilterConfig] = None,
                 mapping_integration: Optional[Any] = None,
                 scoring_integration: Optional[Any] = None):
        """
        Initialize Identity-Based Engine Adapter.
        
        Args:
            config: Pipeline configuration object
            filters: Optional filter configuration
            mapping_integration: Optional semantic mapping integration (shared instance)
            scoring_integration: Optional weighted scoring integration (shared instance)
        """
        super().__init__(config, filters)
        
        # Debug mode control
        self.debug_mode = getattr(config, 'debug_mode', False)
        self.verbose_logging = getattr(config, 'verbose_logging', False)
        
        # Initialize centralized score configuration manager
        # Requirements: 7.2, 8.3
        from ..config.score_configuration_manager import ScoreConfigurationManager
        self.score_config_manager = ScoreConfigurationManager()
        
        # Use provided integrations or create new ones
        # This allows sharing integrations across multiple engines in the same pipeline
        if mapping_integration:
            self.semantic_integration = mapping_integration
            if self.verbose_logging:
                print("[Identity Engine] Using shared semantic mapping integration")
        else:
            self.semantic_integration = SemanticMappingIntegration(getattr(config, 'config_manager', None))
            if self.verbose_logging:
                print("[Identity Engine] Created new semantic mapping integration")
        
        if scoring_integration:
            self.scoring_integration = scoring_integration
            if self.verbose_logging:
                print("[Identity Engine] Using shared weighted scoring integration")
        else:
            self.scoring_integration = WeightedScoringIntegration(getattr(config, 'config_manager', None))
            if self.verbose_logging:
                print("[Identity Engine] Created new weighted scoring integration")
        
        self.progress_tracker = ProgressTracker(debug_mode=self.debug_mode)
        
        # Initialize core engine with debug mode only
        # (semantic mapping and scoring are handled by the adapter, not the core engine)
        # Note: IdentityCorrelationEngine doesn't accept filters parameter
        # Filters are stored in the adapter and applied during execution
        self.core_engine = IdentityCorrelationEngine(
            debug_mode=self.debug_mode
        )
        
        # Verify semantic integration health (only log if verbose)
        if not self.semantic_integration.is_healthy() and self.verbose_logging:
            logger.warning("Semantic mapping integration health check failed - some features may not work correctly")
        
        # Task 2.3: Add logging for semantic integration health status
        # Requirements: 5.1, 5.2, 5.4 - Log semantic integration initialization status
        if self.verbose_logging:
            health_status = "healthy" if self.semantic_integration.is_healthy() else "unhealthy"
            enabled_status = "enabled" if self.semantic_integration.is_enabled() else "disabled"
            logger.info(f"[Identity Engine] Semantic integration status: {health_status}, {enabled_status}")
            
            # Task 6.3: Enhanced configuration validation and warnings
            # Requirements: 7.4, 7.5 - Provide helpful error messages for troubleshooting
            if not self.semantic_integration.is_enabled():
                logger.warning("[Identity Engine] Semantic mapping is disabled - correlation will continue without semantic enhancement")
                print("[SEMANTIC] WARNING: Semantic mapping disabled for Identity Engine")
                print("[SEMANTIC] HELP: Check semantic mapping configuration to enable semantic features")
            elif not self.semantic_integration.is_healthy():
                logger.warning("[Identity Engine] Semantic integration health check failed - some features may not work correctly")
                print("[SEMANTIC] WARNING: Semantic integration unhealthy for Identity Engine")
                print("[SEMANTIC] HELP: Check semantic mapping configuration files and permissions")
            
            # Log configuration source and availability
            manager = self.semantic_integration.semantic_manager
            if manager.config_dir.exists():
                logger.info(f"[Identity Engine] Semantic config directory found: {manager.config_dir}")
                if manager.default_rules_path.exists():
                    logger.info(f"[Identity Engine]   Default rules file: available")
                else:
                    logger.warning(f"[Identity Engine]   Default rules file: missing")
                    print(f"[SEMANTIC] WARNING: Default rules file missing: {manager.default_rules_path}")
                if manager.custom_rules_path.exists():
                    logger.info(f"[Identity Engine]   Custom rules file: available")
                else:
                    logger.info(f"[Identity Engine]   Custom rules file: not found (optional)")
            else:
                logger.warning(f"[Identity Engine] Semantic config directory not found: {manager.config_dir}")
                print(f"[SEMANTIC] WARNING: Config directory not found: {manager.config_dir}")
                print("[SEMANTIC] HELP: Create semantic mapping configuration directory and files")
        
        # Log semantic rules source (JSON vs built-in)
        if self.verbose_logging:
            manager = self.semantic_integration.semantic_manager
            rules_count = len(manager.global_rules)
            mappings_count = sum(len(v) for v in manager.global_mappings.values())
            logger.info(f"[Identity Engine] Semantic rules loaded: {rules_count} rules, {mappings_count} mappings")
            logger.info(f"[Identity Engine] Rules source: JSON files (configs directory)")
            if manager.config_dir.exists():
                logger.info(f"[Identity Engine] Config directory: {manager.config_dir}")
                if manager.default_rules_path.exists():
                    logger.info(f"[Identity Engine]   - Default rules: {manager.default_rules_path.name}")
                if manager.custom_rules_path.exists():
                    logger.info(f"[Identity Engine]   - Custom rules: {manager.custom_rules_path.name}")
        
        # Results storage
        self.last_results: Optional[CorrelationResult] = None
        self.last_statistics: Dict[str, Any] = {}
        
        # Streaming support
        self._output_dir = None
        self._execution_id = None
    
    def set_output_directory(self, output_dir: str, execution_id: int = None):
        """
        Set output directory for streaming results to database.
        
        Args:
            output_dir: Directory where correlation_results.db will be created
            execution_id: Optional execution ID for database records
        """
        self._output_dir = output_dir
        self._execution_id = execution_id
        print(f"[Identity Engine] Streaming mode enabled: output_dir={output_dir}, execution_id={execution_id}")
    
    @property
    def metadata(self) -> EngineMetadata:
        """Get engine metadata"""
        return EngineMetadata(
            name="Identity-Based Correlation",
            version="2.0.0",
            description="Identity-first clustering with temporal anchors. Fast, clean results "
                       "with identity tracking and relationship mapping. Optimized for "
                       "performance with large datasets. Includes semantic mapping and weighted scoring.",
            complexity="O(N log N)",
            best_for=[
                "Large datasets (>1,000 records)",
                "Production environments",
                "Identity tracking",
                "Performance-critical analysis",
                "Relationship mapping",
                "Semantic analysis"
            ],
            supports_identity_filter=True
        )
    
    def execute(self, wing_configs: List[Any], resume_execution_id: int = None) -> Dict[str, Any]:
        """
        Execute identity-based correlation with integrated systems.
        
        Args:
            wing_configs: List of Wing configuration objects
            resume_execution_id: Optional execution ID to resume from paused state
            
        Returns:
            Dictionary containing correlation results and metadata
        """
        start_time = datetime.now()
        
        try:
            # Always print which engine is being used
            print("\n" + "="*70)
            print("CORRELATION ENGINE: Identity-Based")
            print("="*70)
            
            # Check if this is a resume operation
            if resume_execution_id:
                print(f"[Identity Engine] Resuming execution ID: {resume_execution_id}")
                return self._resume_execution(resume_execution_id, wing_configs, start_time)
            
            print("="*70)
            
            # Simple startup message
            print("[Identity Engine] Starting correlation...")
            
            self.progress_tracker.start_scanning(
                total_windows=1,
                window_size_minutes=getattr(self.core_engine, 'time_window_minutes', 180),
                time_range_start=self.filters.time_period_start or datetime(2000, 1, 1),
                time_range_end=self.filters.time_period_end or datetime.now(),
                parallel_processing=False,
                max_workers=1
            )
            
            # Log identity-specific progress start (only if verbose)
            if self.verbose_logging:
                logger.info(f"Starting identity-based correlation")
            
            # Check if streaming mode is enabled
            streaming_enabled = self._output_dir is not None and self._execution_id is not None
            
            # Process each wing
            all_matches = []
            total_identities = 0
            total_match_count = 0  # Track total matches even when streaming
            all_feather_stats = {}  # Collect feather stats from all wings
            
            for wing_idx, wing_config in enumerate(wing_configs, 1):
                wing_name = getattr(wing_config, 'wing_name', 'Unknown')
                print(f"[Identity Engine] Wing {wing_idx}/{len(wing_configs)}: {wing_name}")
                wing_matches, wing_identity_count, wing_feather_stats = self._process_wing(wing_config, 0, 1)
                
                # Merge feather stats from this wing
                for feather_id, stats in wing_feather_stats.items():
                    if feather_id not in all_feather_stats:
                        all_feather_stats[feather_id] = stats
                    else:
                        # Merge stats if feather appears in multiple wings
                        all_feather_stats[feather_id]['total'] += stats['total']
                        all_feather_stats[feather_id]['extracted'] += stats['extracted']
                        all_feather_stats[feather_id]['filtered'] += stats.get('filtered', 0)
                        all_feather_stats[feather_id]['identities'].update(stats['identities'])
                
                if streaming_enabled:
                    # In streaming mode, matches are written to DB, wing_matches is empty
                    # But we need to count them - get count from the result record
                    # The match count is tracked in _process_wing and saved to DB
                    pass  # No action needed here, matches already saved
                else:
                    all_matches.extend(wing_matches)
                
                total_identities += wing_identity_count
            
            # Get actual match count
            if streaming_enabled:
                # Query the database for the actual match count
                from pathlib import Path
                from .database_persistence import ResultsDatabase
                db_path = Path(self._output_dir) / "correlation_results.db"
                with ResultsDatabase(str(db_path)) as db:
                    results = db.get_execution_results(self._execution_id)
                    total_match_count = sum(r.get('total_matches', 0) for r in results)
            else:
                total_match_count = len(all_matches)
            
            # Task 1.1: Remove semantic mappings from correlation processing
            # Requirements: 1.1, 1.2, 1.3, 1.4
            # Semantic matching will be applied AFTER correlation reaches 100% in Identity Semantic Phase
            # Skip if streaming mode (matches already in DB)
            if streaming_enabled:
                scored_matches = []
            else:
                # Calculate weighted scores (silent unless verbose)
                # NO semantic mappings applied during correlation
                if self.verbose_logging:
                    print(f"[Identity Engine] Calculating weighted scores...")
                scored_matches = self._apply_weighted_scoring(all_matches, wing_configs)
            
            # Create correlation result
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Get stats and convert to dicts for serialization
            semantic_stats = self.semantic_integration.get_mapping_statistics()
            scoring_stats = self.scoring_integration.get_scoring_statistics()
            
            # Convert stats objects to dictionaries
            semantic_stats_dict = {
                'total_records_processed': semantic_stats.total_records_processed,
                'mappings_applied': semantic_stats.mappings_applied,
                'unmapped_fields': semantic_stats.unmapped_fields,
                'pattern_matches': semantic_stats.pattern_matches,
                'exact_matches': semantic_stats.exact_matches,
                'global_mappings_used': getattr(semantic_stats, 'global_mappings_used', 0),
                'case_specific_mappings_used': getattr(semantic_stats, 'case_specific_mappings_used', 0)
            }
            
            scoring_stats_dict = {
                'total_matches_scored': getattr(scoring_stats, 'total_matches_scored', 0),
                'scores_calculated': getattr(scoring_stats, 'scores_calculated', 0),
                'fallback_to_simple_count': getattr(scoring_stats, 'fallback_to_simple_count', 0),
                'average_score': getattr(scoring_stats, 'average_score', 0.0),
                'highest_score': getattr(scoring_stats, 'highest_score', 0.0),
                'lowest_score': getattr(scoring_stats, 'lowest_score', 0.0)
            }
            
            # Note: Identity Semantic Phase will extract identities from CorrelationResult
            # No need to manually build identities_list here
            
            self.last_results = CorrelationResult(
                wing_id=wing_configs[0].wing_id if wing_configs else "unknown",
                wing_name=wing_configs[0].wing_name if wing_configs else "unknown",
                matches=scored_matches,
                total_matches=total_match_count,  # Use tracked count (works for both streaming and non-streaming)
                execution_duration_seconds=execution_time,
                filters_applied=self._get_applied_filters(),
                feather_metadata={},  # Will be populated AFTER Identity Semantic Phase
                # CRITICAL: Set database info for Identity Semantic Phase (streaming mode support)
                streaming_mode=streaming_enabled,
                database_path=str(Path(self._output_dir) / "correlation_results.db") if streaming_enabled and self._output_dir else None,
                execution_id=self._execution_id if streaming_enabled else None
                # Note: identities field left empty - Identity Semantic Phase extracts from matches/database
            )
            
            # Store engine type as a direct attribute for easy access
            self.last_results.engine_type = "identity_based"
            
            # Task 7.1: Execute Identity Semantic Phase after correlation completes
            # Requirements: 10.1, 10.2, 10.3
            # This applies identity-level semantic mappings in a dedicated final analysis phase
            print(f"[Identity Engine] Starting Identity Semantic Phase...")
            print(f"[Identity Engine] DEBUG: About to call _execute_identity_semantic_phase")
            self.last_results = self._execute_identity_semantic_phase(
                self.last_results, 
                wing_configs
            )
            print(f"[Identity Engine] DEBUG: _execute_identity_semantic_phase returned")
            print(f"[Identity Engine] Identity Semantic Phase completed")
            
            # NOW calculate feather metadata AFTER matches are written and semantic phase is complete
            # Build feather_metadata from collected statistics AFTER matches are written
            # Requirements: 7.1, 7.2
            feather_metadata = {}
            
            # Calculate matches per feather by counting how many matches each feather contributed to
            matches_per_feather = {}
            
            if streaming_enabled:
                # In streaming mode, use SQL aggregation to count matches per feather efficiently
                # This avoids loading all matches into memory which causes resource leaks
                from pathlib import Path
                from .database_persistence import ResultsDatabase
                import sqlite3
                import json
                
                db_path = Path(self._output_dir) / "correlation_results.db"
                try:
                    # Use direct SQL connection for efficient aggregation
                    conn = sqlite3.connect(str(db_path), timeout=30.0)
                    cursor = conn.cursor()
                    
                    # Get result_ids for this execution
                    cursor.execute("""
                        SELECT result_id FROM results WHERE execution_id = ?
                    """, (self._execution_id,))
                    result_ids = [row[0] for row in cursor.fetchall()]
                    
                    print(f"[Identity Engine] Counting matches per feather for {len(result_ids)} results...")
                    
                    # For each result, count matches per feather using efficient SQL
                    for result_id in result_ids:
                        # Get total match count first
                        cursor.execute("SELECT COUNT(*) FROM matches WHERE result_id = ?", (result_id,))
                        total_matches = cursor.fetchone()[0]
                        
                        if total_matches == 0:
                            continue
                        
                        # Process matches in batches to avoid memory issues
                        batch_size = 10000
                        offset = 0
                        
                        while offset < total_matches:
                            cursor.execute("""
                                SELECT feather_records FROM matches 
                                WHERE result_id = ? 
                                LIMIT ? OFFSET ?
                            """, (result_id, batch_size, offset))
                            
                            batch = cursor.fetchall()
                            
                            for row in batch:
                                feather_records_str = row[0]
                                if not feather_records_str:
                                    continue
                                
                                try:
                                    feather_records = json.loads(feather_records_str)
                                    for feather_key in feather_records.keys():
                                        # Extract base feather name (remove _0, _1 suffixes)
                                        feather_id = feather_key.split('_')[0] if '_' in feather_key else feather_key
                                        matches_per_feather[feather_id] = matches_per_feather.get(feather_id, 0) + 1
                                except (json.JSONDecodeError, AttributeError):
                                    pass
                            
                            offset += batch_size
                            
                            # Show progress for large datasets
                            if total_matches > 50000 and offset % 50000 == 0:
                                print(f"[Identity Engine]   Processed {offset:,}/{total_matches:,} matches...")
                    
                    conn.close()
                    print(f"[Identity Engine] ✓ Counted matches for {len(matches_per_feather)} feathers")
                    
                except Exception as e:
                    print(f"[Identity Engine] Warning: Could not count matches per feather: {e}")
                    # Use feather stats as fallback
                    for feather_id in all_feather_stats.keys():
                        matches_per_feather[feather_id] = 0
            else:
                # In memory mode, count from scored_matches
                for match in scored_matches:
                    for record in match.feather_records:
                        feather_id = record.get('_feather_id', 'unknown')
                        matches_per_feather[feather_id] = matches_per_feather.get(feather_id, 0) + 1
            
            for feather_id, stats in all_feather_stats.items():
                feather_metadata[feather_id] = {
                    'feather_name': feather_id,
                    'records_processed': stats['total'],
                    'identities_extracted': stats['extracted'],
                    'identities_filtered': stats.get('filtered', 0),
                    'identities_final': len(stats['identities']),
                    'identities_found': len(stats['identities']),  # Alias for GUI compatibility
                    'matches_created': matches_per_feather.get(feather_id, 0)  # Actual count from matches
                }
            
            # Add engine metadata as a special entry
            feather_metadata['_engine_metadata'] = {
                'engine_type': 'identity_based',
                'streaming_mode': streaming_enabled,
                'semantic_mapping_enabled': self.semantic_integration.is_enabled(),
                'semantic_stats': semantic_stats_dict,
                'weighted_scoring_enabled': self.scoring_integration.is_enabled(),
                'scoring_stats': scoring_stats_dict,
                'identities_processed': total_identities,
                'core_engine_stats': self._get_core_engine_stats()
            }
            
            # Update the correlation result with the correct feather metadata
            self.last_results.feather_metadata = feather_metadata
            
            # Save feather_metadata to database if in streaming mode
            if streaming_enabled:
                from pathlib import Path
                from .database_persistence import ResultsDatabase
                db_path = Path(self._output_dir) / "correlation_results.db"
                try:
                    # Use direct instantiation instead of context manager
                    db = ResultsDatabase(str(db_path))
                    
                    # Get all results for this execution
                    results = db.get_execution_results(self._execution_id)
                    for result in results:
                        result_id = result.get('result_id')
                        if result_id:
                            # Update the result with feather_metadata
                            db.update_result_count(
                                result_id=result_id,
                                total_matches=result.get('total_matches', 0),
                                execution_duration=execution_time,
                                duplicates_prevented=0,
                                feather_metadata=feather_metadata
                            )
                    
                    # Close the database connection
                    db.close()
                    
                    print(f"[Identity Engine] ✓ Feather metadata saved to database")
                except Exception as e:
                    print(f"[Identity Engine] Warning: Could not save feather metadata to database: {e}")
                    import traceback
                    traceback.print_exc()
            
            print(f"[Identity Engine] Feather metadata summary:")
            for feather_id, metadata in feather_metadata.items():
                if feather_id.startswith('_'):  # Skip engine metadata
                    continue
                identities_count = metadata.get('identities_found', metadata.get('identities_final', 0))
                matches_count = metadata.get('matches_created', 0)
                print(f"  - {feather_id}: {identities_count} identities, {matches_count} matches")
            
            # Complete progress tracking
            self.progress_tracker.complete_scanning()
            
            # Print simple completion summary
            print(f"[Identity Engine] Complete!")
            print(f"[Identity Engine] Processed {total_identities:,} identities")
            print(f"[Identity Engine] Created {total_match_count:,} matches")
            if streaming_enabled:
                print(f"[Identity Engine] Matches saved to database via streaming")
            
            # Format execution time nicely
            if execution_time < 60:
                time_str = f"{execution_time:.2f}s"
            elif execution_time < 3600:
                minutes = int(execution_time // 60)
                seconds = execution_time % 60
                time_str = f"{minutes}m {seconds:.1f}s"
            else:
                hours = int(execution_time // 3600)
                minutes = int((execution_time % 3600) // 60)
                seconds = execution_time % 60
                time_str = f"{hours}h {minutes}m {seconds:.0f}s"
            
            print(f"[Identity Engine] Time: {time_str}")
            print("="*70 + "\n")
            
            # Store statistics
            self.last_statistics = {
                'execution_time': execution_time,
                'record_count': sum(len(match.feather_records) for match in scored_matches) if scored_matches else 0,
                'match_count': total_match_count,
                'identities_processed': total_identities,
                'semantic_mappings_applied': semantic_stats.mappings_applied,
                'weighted_scoring_stats': scoring_stats_dict,
                'duplicate_rate': 0.0,  # Identity-based engine has minimal duplicates
                'streaming_mode': streaming_enabled
            }
            
            # Log final statistics
            self._log_final_statistics()
            
            return {
                'result': self.last_results,
                'engine_type': 'identity_based',
                'filters_applied': self._get_applied_filters()
            }
            
        except Exception as e:
            # Check if this is a cancellation
            if "cancelled" in str(e).lower() or "OperationCancelledException" in str(type(e).__name__):
                print(f"[Identity Engine] Correlation cancelled by user")
                # Return partial results if available
                if hasattr(self, 'last_results') and self.last_results:
                    return {
                        'result': self.last_results,
                        'engine_type': 'identity_based',
                        'filters_applied': self._get_applied_filters(),
                        'cancelled': True
                    }
                else:
                    # Return empty result for cancellation
                    empty_result = CorrelationResult(
                        wing_id="cancelled",
                        wing_name="Cancelled",
                        matches=[],
                        total_matches=0,
                        execution_duration_seconds=(datetime.now() - start_time).total_seconds()
                    )
                    return {
                        'result': empty_result,
                        'engine_type': 'identity_based',
                        'filters_applied': self._get_applied_filters(),
                        'cancelled': True
                    }
            else:
                # Handle other errors
                import traceback
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                self.progress_tracker.report_error(f"Identity correlation failed: {str(e)}", str(e))
                logger.error(f"Identity-based correlation failed: {error_msg}")
                print(f"[Identity Engine] CRITICAL ERROR: {error_msg}")
                raise
    
    def _resume_execution(self, execution_id: int, wing_configs: List[Any], start_time: datetime) -> Dict[str, Any]:
        """
        Resume a paused execution from where it left off.
        
        Args:
            execution_id: Execution ID to resume
            wing_configs: Wing configurations
            start_time: Current start time
            
        Returns:
            Dictionary containing correlation results and metadata
        """
        print(f"[Identity Engine] Loading paused execution state...")
        
        # Load existing results from database
        if not self._output_dir or not self._execution_id:
            print(f"[Identity Engine] ERROR: Cannot resume - no output directory or execution ID set")
            return self.execute(wing_configs)  # Fall back to new execution
        
        from pathlib import Path
        from .database_persistence import ResultsDatabase
        db_path = Path(self._output_dir) / "correlation_results.db"
        
        try:
            with ResultsDatabase(str(db_path)) as db:
                # Get paused execution info
                paused_executions = db.get_paused_executions()
                paused_execution = None
                
                for exec_data in paused_executions:
                    if exec_data['execution_id'] == execution_id:
                        paused_execution = exec_data
                        break
                
                if not paused_execution:
                    print(f"[Identity Engine] WARNING: No paused execution found with ID {execution_id}")
                    return self.execute(wing_configs)  # Fall back to new execution
                
                progress_details = paused_execution.get('progress_details', {})
                identities_processed = progress_details.get('identities_processed', 0)
                total_identities = progress_details.get('total_identities', 0)
                percentage_complete = progress_details.get('percentage_complete', 0)
                
                print(f"[Identity Engine] Found paused execution:")
                print(f"  - Wing: {paused_execution['wing_name']}")
                print(f"  - Progress: {identities_processed:,}/{total_identities:,} identities ({percentage_complete:.1f}%)")
                print(f"  - Existing matches: {paused_execution['total_matches']:,}")
                print(f"  - Paused at: {progress_details.get('pause_timestamp', 'Unknown')}")
                
                # Load existing matches
                existing_matches = paused_execution['total_matches']
                
                # Create result object with existing data
                
                resumed_result = CorrelationResult(
                    wing_id=wing_configs[0].wing_id if wing_configs else "resumed",
                    wing_name=wing_configs[0].wing_name if wing_configs else "Resumed",
                    matches=[],  # Matches are in database
                    total_matches=existing_matches,
                    execution_duration_seconds=(datetime.now() - start_time).total_seconds(),
                    streaming_mode=True,
                    database_path=str(db_path),
                    execution_id=execution_id
                )
                
                print(f"[Identity Engine] Resume complete!")
                print(f"[Identity Engine] Loaded {existing_matches:,} existing matches")
                print(f"[Identity Engine] Status: Ready to continue or view results")
                
                return {
                    'result': resumed_result,
                    'engine_type': 'identity_based',
                    'filters_applied': {},
                    'resumed': True,
                    'resume_info': {
                        'identities_processed': identities_processed,
                        'total_identities': total_identities,
                        'percentage_complete': percentage_complete,
                        'existing_matches': existing_matches
                    }
                }
                
        except Exception as e:
            print(f"[Identity Engine] ERROR: Failed to resume execution: {e}")
            print(f"[Identity Engine] Falling back to new execution...")
            return self.execute(wing_configs)  # Fall back to new execution
    
    def _smart_truncate_path(self, name: str, max_length: int = 60) -> str:
        """
        Smart truncation for long identity names and paths.
        
        Preserves important information (filename) by showing first 30 and last 27 characters
        with "..." in the middle for names longer than max_length.
        
        Args:
            name: Identity name or path to truncate
            max_length: Maximum length before truncation (default: 60)
            
        Returns:
            Truncated string if longer than max_length, otherwise original string
            
        Requirements: 3.1, 3.2, 3.3, 3.7, 3.8
        """
        if not name or len(name) <= max_length:
            return name
        
        # For long names (>60 chars), show first 30 and last 27 with "..." in middle
        # This preserves the filename at the end for paths
        first_part = name[:30]
        last_part = name[-27:]
        
        return f"{first_part}...{last_part}"
    
    def _get_core_engine_stats(self) -> Dict[str, Any]:
        """
        Get statistics from the core identity correlation engine.
        
        Returns:
            Dictionary with core engine statistics or empty dict if not available
        """
        try:
            # Try different methods to get stats from core engine
            if hasattr(self.core_engine, 'get_statistics'):
                return self.core_engine.get_statistics()
            elif hasattr(self.core_engine, 'stats'):
                return self.core_engine.stats
            elif hasattr(self.core_engine, 'statistics'):
                return self.core_engine.statistics
            else:
                # Return basic info about the engine
                return {
                    'engine_type': 'IdentityCorrelationEngine',
                    'debug_mode': getattr(self.core_engine, 'debug_mode', False),
                    'identity_index_size': len(getattr(self.core_engine, 'identity_index', {})),
                    'stats_available': False
                }
        except Exception as e:
            return {
                'error': f"Failed to get core engine stats: {str(e)}",
                'stats_available': False
            }
    
    def execute_wing(self, wing: Any, feather_paths: Dict[str, str]) -> Any:
        """
        Execute correlation for a single wing (backward compatibility method).
        
        This method provides backward compatibility with code that calls execute_wing directly.
        It wraps the execute() method to provide the same interface as other engines.
        
        Args:
            wing: Wing configuration object
            feather_paths: Dictionary mapping feather_id to database path
            
        Returns:
            CorrelationResult object with correlation results
        """
        if self.verbose_logging:
            logger.info(f"[Identity Engine Adapter] execute_wing called for: {wing.wing_name}")
            logger.info(f"[Identity Engine Adapter] Available feather_paths: {len(feather_paths)} feathers")
        
        # Store feather_paths for use in _process_wing
        self._current_feather_paths = feather_paths
        
        try:
            # Execute using the main execute method with a single wing
            result_dict = self.execute([wing])
            
            # Extract the CorrelationResult from the result dictionary
            correlation_result = result_dict.get('result')
            
            if correlation_result:
                # Update the result with wing-specific information
                correlation_result.wing_id = wing.wing_id
                correlation_result.wing_name = wing.wing_name
                
                if self.verbose_logging:
                    logger.info(f"[Identity Engine Adapter] Wing execution complete: "
                               f"{correlation_result.total_matches} matches found")
                
                return correlation_result
            else:
                # Create empty result if none returned
                empty_result = CorrelationResult(
                    wing_id=wing.wing_id,
                    wing_name=wing.wing_name
                )
                empty_result.matches = []
                empty_result.total_matches = 0
                empty_result.execution_duration_seconds = 0.0
                
                logger.warning(f"[Identity Engine Adapter] No results returned for wing: {wing.wing_name}")
                return empty_result
                
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"[Identity Engine Adapter] Wing execution failed for {wing.wing_name}: {error_msg}")
            print(f"[Identity Engine] ERROR: Wing execution failed: {error_msg}")
            
            # Create error result
            error_result = CorrelationResult(
                wing_id=wing.wing_id,
                wing_name=wing.wing_name
            )
            error_result.matches = []
            error_result.total_matches = 0
            error_result.execution_duration_seconds = 0.0
            error_result.errors = [f"Wing execution failed: {str(e)}"]
            
            return error_result
    
    def _process_wing(self, wing_config: Any, processed_identities_offset: int, total_identities_global: int) -> Tuple[List[CorrelationMatch], int, Dict[str, Dict]]:
        """
        Process a single wing configuration with identity-specific progress tracking.
        Supports streaming mode for incremental database writes.
        
        Args:
            wing_config: Wing configuration object
            processed_identities_offset: Number of identities already processed in previous wings
            total_identities_global: Total estimated identities across all wings
            
        Returns:
            Tuple of (list of correlation matches, number of identities processed in this wing, feather statistics dict)
        """
        import sqlite3
        import uuid
        from pathlib import Path
        
        wing_id = getattr(wing_config, 'wing_id', f'wing_{processed_identities_offset}')
        wing_name = getattr(wing_config, 'wing_name', f'Wing {processed_identities_offset}')
        
        # Check if streaming mode is enabled
        streaming_enabled = self._output_dir is not None and self._execution_id is not None
        streaming_writer = None
        result_id = None
        
        if streaming_enabled:
            # Initialize streaming writer
            from .database_persistence import StreamingMatchWriter
            db_path = Path(self._output_dir) / "correlation_results.db"
            streaming_writer = StreamingMatchWriter(str(db_path), batch_size=1000)
            
            # Create result record in database
            result_id = streaming_writer.create_result(
                execution_id=self._execution_id,
                wing_id=wing_id,
                wing_name=wing_name,
                feathers_processed=0,  # Will update later
                total_records_scanned=0  # Will update later
            )
            print(f"[Identity Engine] Streaming mode active: writing to result_id={result_id}")
        
        # Start wing processing progress with identity-specific formatting
        self.progress_tracker.start_window(
            window_id=f"identity_wing_{wing_id}",
            window_start_time=datetime.now(),
            window_end_time=datetime.now()
        )
        
        # Log identity-specific progress (only if verbose)
        if self.verbose_logging:
            logger.info(f"Processing identity wing {wing_id}")
        
        # Only print if debug mode is enabled
        if self.debug_mode:
            print(f"[Identity Engine] Processing wing: {wing_name}")
        
        matches = []  # Only used if streaming is disabled
        match_count = 0  # Track total matches for both modes
        identity_index = {}  # identity_key -> list of records
        total_records = 0
        feathers_with_records = []
        
        # Get feather paths from stored value
        feather_paths = getattr(self, '_current_feather_paths', {})
        
        if not feather_paths:
            if self.verbose_logging:
                logger.warning(f"No feather paths available for wing {wing_id}")
            if self.debug_mode:
                print(f"[Identity Engine] WARNING: No feather paths available")
            
            if streaming_writer:
                streaming_writer.close()
            
            return matches, 0
        
        if self.debug_mode:
            print(f"[Identity Engine] Loading {len(feather_paths)} feathers...")
        
        # Step 1: Load records from all feather databases and index by identity
        total_feathers = len(feather_paths)
        print(f"[Identity Engine]   Loading {total_feathers} feathers...")
        
        # Track per-feather extraction statistics
        feather_stats = {}  # feather_id -> {total, extracted, identities}
        identity_feathers = {}  # identity_key -> set of feather_ids
        
        feather_count = 0
        for feather_id, db_path in feather_paths.items():
            feather_count += 1
            try:
                # Initialize stats for this feather
                feather_stats[feather_id] = {
                    'total': 0,
                    'extracted': 0,
                    'identities': set(),
                    'filtered': 0  # Track filtered identities
                }
                
                # ENHANCEMENT: Load feather metadata for smart identity extraction
                feather_metadata = self.core_engine.load_feather_metadata(db_path, feather_id)
                if feather_metadata and self.verbose_logging:
                    print(f"[Identity Engine] Loaded metadata for {feather_id}: "
                          f"app_col={feather_metadata.get('application_column')}, "
                          f"path_col={feather_metadata.get('path_column')}")
                
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Get all tables in the database
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                
                # Count total records first for logging
                total_feather_records = 0
                for table in tables:
                    if not table.startswith('sqlite_'):
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table}")
                            total_feather_records += cursor.fetchone()[0]
                        except:
                            pass
                
                # Requirement 5.1: Log feather processing start with record count
                print(f"[Identity Engine] 📊 Processing feather: {feather_id} ({total_feather_records} records)")
                
                if self.verbose_logging:
                    logger.info(f"Loading feather: {feather_id} from {db_path}")
                
                feather_records = 0
                feather_identities_before_filter = 0
                
                for table in tables:
                    if table.startswith('sqlite_'):
                        continue
                    
                    try:
                        cursor.execute(f"SELECT * FROM {table}")
                        rows = cursor.fetchall()
                        columns = [desc[0] for desc in cursor.description]
                        
                        for row in rows:
                            record = dict(zip(columns, row))
                            record['_feather_id'] = feather_id
                            record['_table'] = table
                            
                            feather_stats[feather_id]['total'] += 1
                            
                            # Apply filters - skip record if it should be filtered out
                            if self._should_filter_record(record):
                                continue
                            
                            # ENHANCEMENT: Extract identity using core engine with feather metadata
                            name, path, hash_val, id_type = self.core_engine.extract_identity_info(record, feather_metadata)
                            
                            if name or path or hash_val:
                                # ENHANCEMENT: Normalize identity name to get base and suffix
                                base_name, suffix = self.core_engine.normalize_identity_name(name) if name else (name, "")
                                
                                # Normalize identity key (uses base_name internally)
                                identity_key = self.core_engine.normalize_identity_key(name, path, hash_val)
                                
                                # Track if this is a new identity for this feather
                                is_new_identity = identity_key not in feather_stats[feather_id]['identities']
                                
                                if identity_key not in identity_index:
                                    # Create new identity entry with sub-identity tracking
                                    identity_index[identity_key] = {
                                        'base_name': base_name,  # Base name without suffix
                                        'name': name,  # Original full name
                                        'path': path,
                                        'hash': hash_val,
                                        'records': [],
                                        'sub_identities': []  # Track all versions/variants
                                    }
                                    identity_feathers[identity_key] = set()
                                
                                # Track sub-identity if it has a suffix (version/date/number)
                                if suffix:
                                    # Check if this sub-identity already exists
                                    sub_identity_exists = any(
                                        sub['full_name'] == name and sub['suffix'] == suffix
                                        for sub in identity_index[identity_key]['sub_identities']
                                    )
                                    
                                    if not sub_identity_exists:
                                        identity_index[identity_key]['sub_identities'].append({
                                            'full_name': name,
                                            'suffix': suffix,
                                            'record_count': 0
                                        })
                                    
                                    # Increment record count for this sub-identity
                                    for sub in identity_index[identity_key]['sub_identities']:
                                        if sub['full_name'] == name and sub['suffix'] == suffix:
                                            sub['record_count'] += 1
                                            break
                                
                                identity_index[identity_key]['records'].append(record)
                                identity_feathers[identity_key].add(feather_id)
                                feather_stats[feather_id]['identities'].add(identity_key)
                                feather_stats[feather_id]['extracted'] += 1
                                feather_records += 1
                                total_records += 1
                        
                    except Exception as e:
                        if self.verbose_logging:
                            logger.warning(f"Error reading table {table}: {e}")
                
                conn.close()
                
                # Calculate filtered count (records that didn't produce identities)
                feather_stats[feather_id]['filtered'] = feather_stats[feather_id]['total'] - feather_stats[feather_id]['extracted']
                
                # Requirement 5.2: Log extraction completion with identity count
                unique_identities = len(feather_stats[feather_id]['identities'])
                print(f"[Identity Engine] ✓ Extracted {unique_identities} unique identities from {feather_id}")
                
                # Requirement 5.3: Log filtering summary if any were filtered
                if feather_stats[feather_id]['filtered'] > 0:
                    print(f"[Identity Engine] Filtered {feather_stats[feather_id]['filtered']} invalid identities from {feather_id}")
                
                # Requirement 5.6: Log if feather was skipped due to no valid identities
                if unique_identities == 0:
                    print(f"[Identity Engine]       Skipped {feather_id}: No valid identities found")
                
                if feather_records > 0:
                    feathers_with_records.append(feather_id)
                    
                    if self.verbose_logging:
                        logger.info(f"  Loaded {feather_records} records from {feather_id}")
                    
            except Exception as e:
                # Requirement 5.5: Log errors processing feather
                print(f"[Identity Engine]       Error processing {feather_id}: {e}")
                logger.error(f"Error loading feather {feather_id}: {e}")
        
        # Requirement 5.4 & 5.8: Show detailed extraction statistics summary
        total_filtered = sum(stats.get('filtered', 0) for stats in feather_stats.values())
        
        print(f"\n[Identity Engine] Identity Extraction Summary:")
        print(f"  Total Records Processed: {total_records:,}")
        print(f"  Unique Identities Found: {len(identity_index):,}")
        print(f"  Identities Filtered: {total_filtered:,}")
        
        print(f"\n[Identity Engine] Extraction Statistics by Feather:")
        print(f"  {'Feather':<30} {'Records':<15} {'Extracted':<15} {'Filtered':<15} {'Identities':<15}")
        print(f"  {'-'*30} {'-'*15} {'-'*15} {'-'*15} {'-'*15}")
        
        for fid, stats in sorted(feather_stats.items(), key=lambda x: x[1]['total'], reverse=True):
            if stats['total'] == 0:
                continue
            
            records_str = f"{stats['total']:,}"
            extracted_str = f"{stats['extracted']:,}"
            filtered_str = f"{stats.get('filtered', 0):,}"
            unique_identities = len(stats['identities'])
            identities_str = f"{unique_identities:,}"
            
            # Truncate feather name if too long
            display_fid = fid if len(fid) <= 28 else fid[:25] + "..."
            
            print(f"  {display_fid:<30} {records_str:<15} {extracted_str:<15} {filtered_str:<15} {identities_str:<15}")
        
        # Requirement 3.6: Cross-feather correlations section - DISABLED for cleaner output
        # print(f"\n[Identity Engine] 🔗 Cross-Feather Correlations (identities in 2+ feathers):")
        
        # Requirement 3.4: Filter to show only identities in 2+ feathers
        multi_feather = [(k, v) for k, v in identity_feathers.items() if len(v) > 1]
        # multi_feather.sort(key=lambda x: len(x[1]), reverse=True)
        
        # if multi_feather:
        #     # Show top 10 cross-feather identities
        #     for identity_key, feather_set in multi_feather[:10]:
        #         name = identity_index[identity_key]['name'] or identity_index[identity_key]['path'] or 'unknown'
        #         
        #         # Requirement 3.1, 3.2, 3.3: Apply smart truncation to identity names
        #         name = self._smart_truncate_path(name, max_length=60)
        #         
        #         # Requirement 2.1, 2.2, 2.3: Deduplicate feather names
        #         # Extract base feather name (before first underscore or hyphen)
        #         feather_base_names = set()
        #         for f in feather_set:
        #             # Split on underscore or hyphen and take first part
        #             base_name = f.split('_')[0].split('-')[0]
        #             feather_base_names.add(base_name)
        #         
        #         # Requirement 2.2: Sort alphabetically
        #         feather_names = sorted(feather_base_names)
        #         
        #         # Requirement 2.4, 2.5, 3.7: Consistent formatting with count matching displayed names
        #         print(f"  {name}: Found in {len(feather_names)} feathers ({', '.join(feather_names)})")
        # else:
        #     # Requirement 3.5: Don't log identities found in only 1 feather
        #     print(f"  No identities found across multiple feathers")
        
        # Requirement 2.6, 3.6: Add cross-feather summary with totals
        # Calculate unique feathers across all multi-feather identities (for internal tracking only)
        # all_unique_feathers = set()
        # for _, feather_set in multi_feather:
        #     for f in feather_set:
        #         base_name = f.split('_')[0].split('-')[0]
        #         all_unique_feathers.add(base_name)
        # 
        # print(f"[Identity Engine] Cross-Feather Summary: {len(multi_feather)} identities across {len(all_unique_feathers)} unique feathers")
        
        print(f"\n[Identity Engine]   Correlating {len(identity_index):,} identities...")
        
        min_matches = 1  # Show ALL identities
        time_window_minutes = 180  # Time window for anchor clustering (default: 3 hours)
        
        # Diagnostic counters
        single_record_identities = 0
        single_feather_identities = 0
        multi_feather_identities = 0
        total_anchors = 0
        match_counter = 0  # Counter to ensure unique match IDs
        
        # Task 8.2: Initialize progress reporter for identity processing
        # Requirements: 4.1, 4.2, 4.3, 4.4
        # PERFORMANCE: Use less frequent reporting for large datasets to reduce overhead
        total_identities = len(identity_index)
        
        # Adaptive progress reporting based on dataset size
        if total_identities > 100000:
            report_interval = 10.0  # Report every 10% for very large datasets
        elif total_identities > 50000:
            report_interval = 5.0   # Report every 5% for large datasets
        else:
            report_interval = 2.0   # Report every 2% for smaller datasets
        
        progress_reporter = CorrelationProgressReporter(
            total_items=total_identities,
            report_percentage_interval=report_interval,
            phase_name="Identity Correlation"
        )
        
        print(f"[Identity Engine] PERFORMANCE: Using {report_interval}% progress reporting for {total_identities:,} identities")
        
        # Task 9.2: Initialize stall monitor for identity processing
        # Requirements: 5.2, 5.3, 5.4, 5.5
        # Detects stalls when no progress for 300 seconds (5 minutes)
        stall_monitor = CorrelationStallMonitor(stall_timeout_seconds=300)
        
        # Report initial progress (0%)
        progress_reporter.force_report()
        
        # Task 9.2: Update stall monitor at start
        stall_monitor.update_progress(0, current_stage="identity_processing", last_operation="started_identity_correlation")
        
        # Performance optimization: Check stall less frequently (every 20000 identities for large datasets)
        if total_identities > 100000:
            stall_check_interval = 20000  # Less frequent for very large datasets
        else:
            stall_check_interval = 10000  # Standard frequency
        
        print(f"[Identity Engine] PERFORMANCE: Stall check every {stall_check_interval:,} identities")
        
        processed_count = 0
        cancellation_check_interval = 15000 if total_identities > 100000 else 10000  # Less frequent checks for large datasets
        
        for identity_key, identity_data in identity_index.items():
            # Check for cancellation less frequently for better performance
            if processed_count % cancellation_check_interval == 0:
                try:
                    self.progress_tracker.check_cancellation()
                except Exception as e:
                    print(f"[Identity Engine] Correlation paused by user")
                    # Update progress to show paused state
                    progress_reporter.processed_items = processed_count
                    print(f"[Identity Correlation] PAUSED: {processed_count:,}/{total_identities:,} identities processed ({processed_count/total_identities*100:.1f}%)")
                    
                    # Save partial results to database for resume capability
                    if streaming_enabled and streaming_writer:
                        print(f"[Identity Engine] Saving {match_count:,} partial matches to database...")
                        streaming_writer.flush()
                        
                        # Update result record with partial counts and paused status
                        streaming_writer.update_result_counts(
                            result_id=result_id,
                            total_matches=match_count,
                            feathers_processed=len(feathers_with_records),
                            total_records_scanned=total_records,
                            status="PAUSED",
                            progress_info={
                                'identities_processed': processed_count,
                                'total_identities': total_identities,
                                'percentage_complete': processed_count/total_identities*100,
                                'last_identity_key': identity_key,
                                'pause_timestamp': datetime.now().isoformat()
                            }
                        )
                        
                        streaming_writer.close()
                        print(f"[Identity Engine] ✓ Partial results saved - can resume later")
                    
                    # Return partial results for immediate display
                    return matches, processed_count, feather_stats
            
            # Task 9.2: Check for stall periodically (not every iteration for performance)
            # Requirements: 5.2, 5.3, 5.4
            if processed_count % stall_check_interval == 0:
                if stall_monitor.check_for_stall():
                    diagnostics = stall_monitor.get_stall_diagnostics()
                    logger.error(f"Correlation stalled during identity processing. Diagnostics: {diagnostics}")
                    raise CorrelationStallException(
                        f"Correlation stalled: No progress for {diagnostics['time_since_last_progress']:.1f} seconds. "
                        f"Last operation: {diagnostics['last_successful_operation']}"
                    )
            
            records = identity_data['records']
            
            # Get unique feathers for this identity
            feather_ids = list(set(r.get('_feather_id', '') for r in records))
            
            # Count by category
            if len(records) == 1:
                single_record_identities += 1
            elif len(feather_ids) == 1:
                single_feather_identities += 1
            else:
                multi_feather_identities += 1
            
            # Create anchors for this identity using temporal clustering
            if len(records) >= min_matches:
                # Log hash processing for first few identities or periodically
                if self.debug_mode and (processed_count < 5 or processed_count % 1000 == 0):
                    print(f"[Identity Engine] Processing identity {processed_count}: {len(records)} records, {len(feather_ids)} feathers")
                    print(f"[Identity Engine] Identity key: {identity_key[:50]}...")
                    print(f"[Identity Engine] About to create temporal anchors (will trigger hash calculations)")
                
                identity_anchors = self._create_temporal_anchors(
                    records, 
                    identity_data, 
                    time_window_minutes,
                    feather_paths,
                    match_counter_start=match_counter
                )
                
                if self.debug_mode and (processed_count < 5 or processed_count % 1000 == 0):
                    print(f"[Identity Engine] Created {len(identity_anchors)} anchors for identity {processed_count}")
                
                # Increment match counter for next identity
                match_counter += len(identity_anchors)
                
                # Handle streaming vs in-memory
                if streaming_enabled and streaming_writer:
                    # Task 1.1: Apply scoring to each match before writing to database
                    # Requirements: 1.1, 1.2, 1.3, 1.4
                    # NO semantic mappings during correlation - will be applied in Identity Semantic Phase
                    for match in identity_anchors:
                        # Apply weighted scoring (NO semantic mappings during correlation)
                        scored_match = self._apply_scoring_to_single_match(match, wing_config)
                        streaming_writer.write_match(result_id, scored_match)
                        match_count += 1
                else:
                    # Store in memory (old behavior)
                    matches.extend(identity_anchors)
                    match_count += len(identity_anchors)
                
                total_anchors += len(identity_anchors)
            
            # Task 8.2: Update progress (will auto-report at 1%, 2%, 3%, etc.)
            # Requirements: 4.2, 4.3, 4.4
            processed_count += 1
            progress_reporter.update(items_processed=1)
            
            # Task 9.2: Update stall monitor periodically (every 10000 identities for performance)
            # Requirements: 5.2, 5.4
            if processed_count % stall_check_interval == 0:
                stall_monitor.update_progress(
                    processed_count, 
                    current_stage="identity_processing",
                    last_operation=f"processed_identity_{processed_count}"
                )
        
        # Task 8.2: Report final progress (100%)
        # Requirements: 4.1, 4.5
        progress_reporter.force_report()
        
        # Flush any remaining matches in streaming mode
        if streaming_enabled and streaming_writer:
            print(f"[Identity Engine]   Flushing {match_count:,} matches to database...")
            streaming_writer.flush()
            
            # Update result record with final counts
            # Note: feather_metadata will be calculated and saved later in execute() method
            streaming_writer.update_result_counts(
                result_id=result_id,
                total_matches=match_count,
                feathers_processed=len(feathers_with_records),
                total_records_scanned=total_records
            )
            
            streaming_writer.close()
            
            # Give SQLite a moment to release the lock
            import time
            time.sleep(0.1)
            
            print(f"[Identity Engine]   Saved {match_count:,} matches to database")
        
        # Show completion
        print(f"[Identity Engine]   Created {total_anchors:,} anchors")
        
        if self.debug_mode:
            print(f"[Identity Engine]   Breakdown:")
            print(f"[Identity Engine]     - Single record: {single_record_identities:,}")
            print(f"[Identity Engine]     - Same feather: {single_feather_identities:,}")
            print(f"[Identity Engine]     - Multi-feather: {multi_feather_identities:,} (correlated)")
        
        if self.verbose_logging:
            logger.info(f"Created {match_count} correlation matches for wing {wing_id}")
        
        # Complete wing processing progress with identity-specific details
        self.progress_tracker.complete_window(
            window_id=f"identity_wing_{wing_id}",
            window_start_time=datetime.now(),
            window_end_time=datetime.now(),
            records_found=total_records,
            matches_created=match_count,
            feathers_with_records=feathers_with_records,
            memory_usage_mb=None
        )
        
        return matches, total_identities, feather_stats
    
    def _create_temporal_anchors(self, records: List[Dict[str, Any]], identity_data: Dict[str, Any],
                                time_window_minutes: int, feather_paths: Dict[str, str],
                                match_counter_start: int = 0) -> List[CorrelationMatch]:
        """
        Create temporal anchors by clustering records into time windows.
        
        Args:
            records: List of records for this identity
            identity_data: Identity metadata (name, path, hash)
            time_window_minutes: Time window size for clustering
            feather_paths: Dictionary of feather paths
            
        Returns:
            List of CorrelationMatch objects (one per anchor)
        """
        # PERFORMANCE FIX: Import dateutil parser ONCE at the top, not in the loop
        try:
            from dateutil import parser as date_parser
            has_dateutil = True
        except ImportError:
            has_dateutil = False
        
        # Step 1: Extract timestamps and sort records
        records_with_timestamps = []
        records_without_timestamps = []
        
        for record in records:
            timestamp = None
            for ts_field in self.core_engine.timestamp_field_patterns:
                if ts_field in record and record[ts_field]:
                    try:
                        # Try to parse timestamp
                        ts_str = str(record[ts_field])
                        # Store both string and parsed datetime
                        timestamp = ts_str
                        break
                    except:
                        pass
            
            if timestamp:
                records_with_timestamps.append((timestamp, record))
            else:
                records_without_timestamps.append(record)
        
        # Sort records by timestamp
        records_with_timestamps.sort(key=lambda x: x[0])
        
        # Step 2: Cluster records into temporal anchors based on time proximity
        anchors = []
        current_anchor_records = []
        current_anchor_start = None
        current_anchor_end = None
        
        for timestamp, record in records_with_timestamps:
            if not current_anchor_records:
                # Start first anchor
                current_anchor_records = [record]
                current_anchor_start = timestamp
                current_anchor_end = timestamp
            else:
                # Check if record is within time window of current anchor
                # Parse timestamps and calculate time difference
                should_create_new_anchor = False
                
                if has_dateutil:
                    try:
                        dt_current = date_parser.parse(timestamp)
                        dt_anchor_end = date_parser.parse(current_anchor_end)
                        
                        # Calculate time difference in minutes
                        time_diff = (dt_current - dt_anchor_end).total_seconds() / 60
                        
                        # If time difference exceeds window, create new anchor
                        if abs(time_diff) > time_window_minutes:
                            should_create_new_anchor = True
                    except:
                        # If parsing fails, try simple string comparison
                        # If timestamps are different, might be different time periods
                        if timestamp != current_anchor_end:
                            # For safety, keep in same anchor if can't parse
                            pass
                else:
                    # dateutil not available, use simple heuristic
                    # If timestamps are very different strings, might be different periods
                    pass
                
                if should_create_new_anchor:
                    # Create anchor from current records
                    anchor_match = self._create_anchor_match(
                        current_anchor_records,
                        identity_data,
                        current_anchor_start,
                        current_anchor_end,
                        feather_paths,
                        match_counter=match_counter_start + len(anchors)
                    )
                    if anchor_match:
                        anchors.append(anchor_match)
                    
                    # Start new anchor
                    current_anchor_records = [record]
                    current_anchor_start = timestamp
                    current_anchor_end = timestamp
                else:
                    # Add to current anchor
                    current_anchor_records.append(record)
                    current_anchor_end = timestamp
        
        # Add last anchor
        if current_anchor_records:
            anchor_match = self._create_anchor_match(
                current_anchor_records,
                identity_data,
                current_anchor_start,
                current_anchor_end,
                feather_paths,
                match_counter=match_counter_start + len(anchors)
            )
            if anchor_match:
                anchors.append(anchor_match)
        
        # Step 3: Handle records without timestamps (create separate anchor)
        if records_without_timestamps:
            anchor_match = self._create_anchor_match(
                records_without_timestamps,
                identity_data,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                feather_paths,
                match_counter=match_counter_start + len(anchors)
            )
            if anchor_match:
                anchors.append(anchor_match)
        
        return anchors
    
    def _create_anchor_match(self, records: List[Dict[str, Any]], identity_data: Dict[str, Any],
                            start_time: str, end_time: str, feather_paths: Dict[str, str],
                            match_counter: int = 0) -> Optional[CorrelationMatch]:
        """
        Create a CorrelationMatch for a temporal anchor.
        
        Args:
            records: Records in this anchor
            identity_data: Identity metadata
            start_time: Anchor start time
            end_time: Anchor end time
            feather_paths: Dictionary of feather paths
            
        Returns:
            CorrelationMatch object or None
        """
        if not records:
            return None
        
        # PERFORMANCE OPTIMIZED: Use simplified hash-based deduplication
        # Deduplicate records using a fast hash set for O(N) performance
        feather_records_dict = {}
        seen_hashes = {}  # Track seen record hashes per feather
        
        # Debug logging for hash calculation
        hash_start_time = None
        if self.debug_mode:
            import time
            hash_start_time = time.time()
            print(f"[Identity Engine] HASH: Processing {len(records)} records for anchor")
        
        hash_stats = {
            'total_records': len(records),
            'unique_hashes': 0,
            'duplicate_hashes': 0,
            'feathers_involved': set(),
            'timestamp_fields_found': 0,
            'records_without_timestamp': 0
        }
        
        for record_idx, record in enumerate(records):
            fid = record.get('_feather_id', 'unknown')
            hash_stats['feathers_involved'].add(fid)
            
            if fid not in feather_records_dict:
                feather_records_dict[fid] = []
                seen_hashes[fid] = set()
            
            # PERFORMANCE: Create a fast hash using only essential fields
            # Use timestamp + name + path for deduplication (much faster than all fields)
            ts = None
            for ts_field in self.core_engine.timestamp_field_patterns:
                if ts_field in record and record[ts_field]:
                    ts = str(record[ts_field])
                    hash_stats['timestamp_fields_found'] += 1
                    break
            
            if ts is None:
                hash_stats['records_without_timestamp'] += 1
                if self.debug_mode and record_idx < 3:  # Log first few records without timestamp
                    print(f"[Identity Engine] HASH: Record {record_idx} has no timestamp, feather={fid}")
            
            # Create fast hash from essential fields only
            name = record.get('name', '')
            path = record.get('path', '')
            
            # Log hash creation for debugging (first few records only)
            if self.debug_mode and record_idx < 3:
                print(f"[Identity Engine] HASH: Record {record_idx} - ts='{ts}', name='{name[:30]}...', path='{path[:30]}...', fid='{fid}'")
            
            record_hash = hash((ts, name, path, fid))
            
            if self.debug_mode and record_idx < 3:
                print(f"[Identity Engine] HASH: Record {record_idx} hash = {record_hash}")
            
            # Check if we've seen this hash before (fast O(1) lookup)
            if record_hash not in seen_hashes[fid]:
                seen_hashes[fid].add(record_hash)
                feather_records_dict[fid].append(record)
                hash_stats['unique_hashes'] += 1
                
                if self.debug_mode and record_idx < 3:
                    print(f"[Identity Engine] HASH: Record {record_idx} is unique, added to feather {fid}")
            else:
                hash_stats['duplicate_hashes'] += 1
                
                if self.debug_mode and record_idx < 3:
                    print(f"[Identity Engine] HASH: Record {record_idx} is duplicate, skipped for feather {fid}")
        
        # Log hash statistics
        if self.debug_mode:
            hash_end_time = time.time()
            hash_duration = hash_end_time - hash_start_time if hash_start_time else 0
            
            print(f"[Identity Engine] HASH STATS:")
            print(f"  Total records processed: {hash_stats['total_records']}")
            print(f"  Unique hashes created: {hash_stats['unique_hashes']}")
            print(f"  Duplicate hashes found: {hash_stats['duplicate_hashes']}")
            print(f"  Feathers involved: {len(hash_stats['feathers_involved'])} ({', '.join(sorted(hash_stats['feathers_involved']))})")
            print(f"  Records with timestamps: {hash_stats['timestamp_fields_found']}")
            print(f"  Records without timestamps: {hash_stats['records_without_timestamp']}")
            print(f"  Hash processing time: {hash_duration:.4f} seconds")
            
            dedup_rate = (hash_stats['duplicate_hashes'] / hash_stats['total_records'] * 100) if hash_stats['total_records'] > 0 else 0
            print(f"  Deduplication rate: {dedup_rate:.1f}%")
            
            if hash_stats['total_records'] > 0 and hash_duration > 0:
                records_per_second = hash_stats['total_records'] / hash_duration
                print(f"  Hash performance: {records_per_second:.0f} records/second")
        
        # Flatten for CorrelationMatch
        flattened_feather_records = {}
        for fid, record_list in feather_records_dict.items():
            # Always include ALL records consistently (whether 1 or many)
            # This ensures no data loss and consistent behavior
            flattened_feather_records[fid] = record_list if record_list else []
            
            # Log record inclusion for verification
            if record_list:
                logger.info(f"[Identity Engine] Included {len(record_list)} records for feather_id={fid}")
        
        if self.debug_mode:
            print(f"[Identity Engine] MATCH: Flattened to {len(flattened_feather_records)} feather records")
        
        # Get unique feathers (fast)
        feather_ids = list(feather_records_dict.keys())
        
        # PERFORMANCE: Use counter-based ID with execution_id for guaranteed uniqueness
        # Include execution_id and counter to prevent collisions
        import time
        timestamp_micros = int(time.time() * 1000000)
        exec_id_part = f"e{self._execution_id}_" if self._execution_id else ""
        match_id = f"match_{exec_id_part}{timestamp_micros}_{match_counter}_{len(feather_ids)}"
        
        if self.debug_mode:
            print(f"[Identity Engine] MATCH: Generated ID = {match_id}")
            print(f"[Identity Engine] MATCH: Feathers involved = {feather_ids}")
            print(f"[Identity Engine] MATCH: Creating CorrelationMatch with {len(feather_ids)} feathers")
        
        # Create match
        match = CorrelationMatch(
            match_id=match_id,
            timestamp=start_time,
            feather_records=flattened_feather_records,
            match_score=len(feather_ids) / len(feather_paths) if feather_paths else 0.5,
            feather_count=len(feather_ids),
            time_spread_seconds=0,  # Simplified for performance
            anchor_feather_id=feather_ids[0] if feather_ids else '',
            anchor_artifact_type='Identity',
            matched_application=identity_data.get('base_name', identity_data['name']),  # Use base name for display
            matched_file_path=identity_data['path']
        )
        
        # Add anchor metadata
        match.anchor_start_time = start_time
        match.anchor_end_time = end_time
        match.anchor_record_count = len(records)
        
        # ENHANCEMENT: Add sub-identity information if available
        # This allows UI to show grouped versions/variants
        if 'sub_identities' in identity_data and identity_data['sub_identities']:
            match.sub_identities = identity_data['sub_identities']
            match.has_sub_identities = True
            match.sub_identity_count = len(identity_data['sub_identities'])
        else:
            match.sub_identities = []
            match.has_sub_identities = False
            match.sub_identity_count = 0
        
        return match
    
    def _are_records_identical(self, record1: Dict[str, Any], record2: Dict[str, Any]) -> bool:
        """
        Check if two records are identical (same data and same timestamp).
        
        Args:
            record1: First record
            record2: Second record
            
        Returns:
            True if records are identical, False otherwise
        """
        # Get timestamps from both records
        ts1 = None
        ts2 = None
        
        for ts_field in self.core_engine.timestamp_field_patterns:
            if ts_field in record1 and record1[ts_field]:
                ts1 = str(record1[ts_field])
                break
        
        for ts_field in self.core_engine.timestamp_field_patterns:
            if ts_field in record2 and record2[ts_field]:
                ts2 = str(record2[ts_field])
                break
        
        # If timestamps are different, records are different
        if ts1 != ts2:
            return False
        
        # Compare key fields (excluding internal metadata fields)
        exclude_fields = {'_feather_id', '_table', '_rowid'}
        
        # Get all keys from both records (excluding internal fields)
        keys1 = set(k for k in record1.keys() if k not in exclude_fields)
        keys2 = set(k for k in record2.keys() if k not in exclude_fields)
        
        # If different keys, records are different
        if keys1 != keys2:
            return False
        
        # Compare values for all keys
        for key in keys1:
            val1 = record1.get(key)
            val2 = record2.get(key)
            
            # Convert to string for comparison (handles different types)
            str_val1 = str(val1) if val1 is not None else ''
            str_val2 = str(val2) if val2 is not None else ''
            
            if str_val1 != str_val2:
                return False
        
        # All fields match - records are identical
        return True
    
    def _report_identity_milestone(self, processed_identities: int, total_identities: int):
        """
        Report identity processing milestone with specific formatting.
        
        Args:
            processed_identities: Number of identities processed so far
            total_identities: Total number of identities to process
        """
        # Calculate progress percentage
        progress_percent = (processed_identities / total_identities * 100) if total_identities > 0 else 0
        
        # Always print percentage progress
        print(f"[Identity Engine] Progress: {progress_percent:.1f}% complete ({processed_identities:,}/{total_identities:,} identities)")
        
        # Log identity-specific progress format (only if verbose)
        if self.verbose_logging:
            logger.info(f"Processing identity {processed_identities} of {total_identities} ({progress_percent:.1f}% complete)")
        
        # Report to progress tracker with identity-specific message
        from .progress_tracking import ProgressEvent, ProgressEventType
        
        # Create identity-specific progress event
        event = ProgressEvent(
            event_type=ProgressEventType.WINDOW_PROGRESS,
            timestamp=datetime.now(),
            overall_progress=self.progress_tracker._create_overall_progress(),
            message=f"Processing identity {processed_identities} of {total_identities}",
            additional_data={
                'identity_progress': {
                    'processed_identities': processed_identities,
                    'total_identities': total_identities,
                    'progress_percent': progress_percent,
                    'engine_type': 'identity_based'
                }
            }
        )
        
        # Emit the event to all listeners
        self.progress_tracker._emit_event(event)
    
    def _emit_identity_progress(self, processed_identities: int, total_identities: int):
        """
        Emit identity progress update (alias for _report_identity_milestone).
        
        Args:
            processed_identities: Number of identities processed so far
            total_identities: Total number of identities to process
        """
        self._report_identity_milestone(processed_identities, total_identities)
    
    def _extract_semantic_data_from_records(self, 
                                           enhanced_records: Dict[str, Dict]) -> Dict[str, Any]:
        """
        Extract semantic data from enhanced feather records.
        
        This method iterates through enhanced records that have been processed by
        the semantic integration layer and extracts the _semantic_mappings from each
        record to build a consolidated semantic_data dict for the CorrelationMatch.
        
        Args:
            enhanced_records: Dict of feather_id -> enhanced record with _semantic_mappings
            
        Returns:
            Consolidated semantic_data dict for the match containing:
            - Individual semantic mappings keyed by feather_id.field_name
            - _metadata with mappings_applied flag and count
            
        Requirements: 1.2, 1.3
        """
        semantic_data = {}
        mappings_count = 0
        
        for feather_id, record in enhanced_records.items():
            if not isinstance(record, dict):
                continue
            
            semantic_mappings = record.get('_semantic_mappings', {})
            if not semantic_mappings:
                continue
            
            for field_name, mapping_info in semantic_mappings.items():
                if isinstance(mapping_info, dict) and 'semantic_value' in mapping_info:
                    # Use feather_id.field_name as key to avoid collisions
                    key = f"{feather_id}.{field_name}" if feather_id else field_name
                    semantic_data[key] = {
                        'semantic_value': mapping_info['semantic_value'],
                        'technical_value': mapping_info.get('technical_value', ''),
                        'description': mapping_info.get('description', ''),
                        'category': mapping_info.get('category', ''),
                        'confidence': mapping_info.get('confidence', 1.0),
                        'rule_name': mapping_info.get('rule_name', field_name),
                        'feather_id': feather_id
                    }
                    mappings_count += 1
        
        # Add metadata
        semantic_data['_metadata'] = {
            'mappings_applied': mappings_count > 0,
            'mappings_count': mappings_count,
            'engine_type': self.__class__.__name__
        }
        
        # Task 11.1: Add debug logging for semantic data extraction
        # Requirements: 7.1, 7.2 - Log semantic mapping application details
        if getattr(self, 'verbose_logging', False) and mappings_count > 0:
            logger.debug(f"[Identity Engine] Extracted semantic data: {mappings_count} mappings from {len(enhanced_records)} records")
            # Log summary of semantic values found
            semantic_values = [v.get('semantic_value', '') for k, v in semantic_data.items() 
                             if k != '_metadata' and isinstance(v, dict)]
            if semantic_values:
                unique_values = list(set(semantic_values))[:5]  # Show first 5 unique values
                logger.debug(f"[Identity Engine] Semantic values sample: {unique_values}")
        
        return semantic_data
    
    def _apply_semantic_mappings(self, 
                               matches: List[CorrelationMatch], 
                               wing_configs: List[Any]) -> List[CorrelationMatch]:
        """
        Apply semantic mappings to correlation matches with comprehensive error handling.
        
        IMPORTANT: This method checks the SemanticMappingController to determine if
        per-record semantic mapping should be skipped (when Identity Semantic Phase is enabled).
        
        Task 6.1: Enhanced graceful degradation for semantic mapping failures
        Requirements: 7.1, 7.2, 7.3 - Ensure correlation continues even if semantic mapping fails
        Requirements: 1.5, 2.5 - Semantic processing isolation (skip if Identity Semantic Phase enabled)
        
        Args:
            matches: List of correlation matches
            wing_configs: Wing configurations for context
            
        Returns:
            Enhanced matches with semantic mapping information (or original matches if skipped)
        """
        # CRITICAL: Check if per-record semantic mapping should be skipped
        # This ensures semantic processing isolation when Identity Semantic Phase is enabled
        from ..identity_semantic_phase import SemanticMappingController
        
        # Check if we have a semantic mapping controller that says to skip per-record mapping
        if hasattr(self, 'semantic_mapping_controller'):
            if not self.semantic_mapping_controller.should_apply_per_record_semantic_mapping():
                if self.verbose_logging:
                    logger.info("[Identity Engine] Skipping per-record semantic mapping - will be applied in Identity Semantic Phase")
                print("[Identity Engine] Semantic mapping deferred to Identity Semantic Phase")
                return matches
        
        # Task 6.1: Check if semantic integration is available before proceeding
        if not hasattr(self, 'semantic_integration') or not self.semantic_integration:
            logger.warning("Semantic integration not available - skipping semantic mapping")
            print("[SEMANTIC] WARNING: Semantic integration not initialized - continuing without semantic mapping")
            return matches
        
        if not self.semantic_integration.is_enabled():
            if self.verbose_logging:
                logger.info("Semantic mapping is disabled, skipping mapping application")
            print("[SEMANTIC] INFO: Semantic mapping disabled - continuing correlation")
            return matches
        
        # Task 6.1: Check semantic integration health before processing
        if not self.semantic_integration.is_healthy():
            logger.warning("Semantic integration health check failed - continuing without semantic mapping")
            print("[SEMANTIC] WARNING: Semantic integration unhealthy - continuing correlation without semantic mapping")
            return matches

        if self.verbose_logging:
            logger.info(f"Applying semantic mappings to {len(matches)} correlation matches")
        
        enhanced_matches = []
        errors_count = 0
        critical_failure = False
        
        try:
            for i, match in enumerate(matches):
                try:
                    # Log progress for large datasets (only if verbose)
                    if self.verbose_logging and len(matches) > 100 and i % 50 == 0:
                        logger.info(f"Processing semantic mappings: {i}/{len(matches)} matches completed")
                    
                    # Convert match feather_records to format expected by semantic integration
                    # IMPORTANT: Include feather_id in each record so semantic rules can match
                    records_list = []
                    for feather_id, record in match.feather_records.items():
                        record_with_feather = record.copy() if isinstance(record, dict) else {'value': record}
                        record_with_feather['_feather_id'] = feather_id
                        records_list.append(record_with_feather)
                    
                    # Apply semantic mappings with error handling
                    enhanced_records_list = self.semantic_integration.apply_to_correlation_results(
                        records_list,
                        wing_id=getattr(match, 'wing_id', None),
                        pipeline_id=getattr(match, 'pipeline_id', None),
                        artifact_type=getattr(match, 'artifact_type', match.anchor_artifact_type)
                    )
                    
                    # Convert back to match format
                    enhanced_feather_records = {}
                    for j, enhanced_record in enumerate(enhanced_records_list):
                        # Use original keys if available, otherwise use index
                        original_keys = list(match.feather_records.keys())
                        key = original_keys[j] if j < len(original_keys) else f"record_{j}"
                        enhanced_feather_records[key] = enhanced_record
                    
                    # CRITICAL FIX: Extract actual semantic values from enhanced records
                    # Requirements: 1.1, 1.2 - Store semantic data in CorrelationMatch.semantic_data
                    semantic_data = self._extract_semantic_data_from_records(enhanced_feather_records)
                    
                    # Task 11.1: Log per-match semantic mapping count (Requirements: 7.1, 7.2)
                    if getattr(self, 'debug_mode', False):
                        mappings_count = semantic_data.get('_metadata', {}).get('mappings_count', 0)
                        if mappings_count > 0:
                            logger.debug(f"[Identity Engine] Match {match.match_id}: {mappings_count} semantic mappings applied")
                    
                    # Create enhanced match with actual semantic data (not just a flag)
                    enhanced_match = CorrelationMatch(
                        match_id=match.match_id,
                        timestamp=match.timestamp,
                        feather_records=enhanced_feather_records,
                        match_score=match.match_score,
                        feather_count=match.feather_count,
                        time_spread_seconds=match.time_spread_seconds,
                        anchor_feather_id=match.anchor_feather_id,
                        anchor_artifact_type=match.anchor_artifact_type,
                        matched_application=match.matched_application,
                        matched_file_path=match.matched_file_path,
                        matched_event_id=match.matched_event_id,
                        score_breakdown=match.score_breakdown,
                        confidence_score=match.confidence_score,
                        confidence_category=match.confidence_category,
                        weighted_score=match.weighted_score,
                        time_deltas=match.time_deltas,
                        field_similarity_scores=match.field_similarity_scores,
                        candidate_counts=match.candidate_counts,
                        algorithm_version=match.algorithm_version,
                        wing_config_hash=match.wing_config_hash,
                        is_duplicate=match.is_duplicate,
                        duplicate_info=match.duplicate_info,
                        semantic_data=semantic_data  # Now contains actual values
                    )
                    
                    enhanced_matches.append(enhanced_match)
                    
                except Exception as e:
                    # Task 6.1: Log error and continue processing remaining matches
                    # Requirements: 7.1, 7.2, 7.3 - Never stop correlation due to semantic mapping failures
                    errors_count += 1
                    logger.warning(f"Failed to apply semantic mappings to match {match.match_id}: {e}")
                    
                    # Create match with error metadata in semantic_data
                    error_semantic_data = {
                        '_metadata': {
                            'mappings_applied': False,
                            'error': str(e),
                            'error_type': type(e).__name__,
                            'match_id': match.match_id,
                            'engine_type': 'IdentityBasedEngineAdapter',
                            'fallback_reason': 'Individual match semantic mapping failed'
                        }
                    }
                    
                    # Keep original match but add error semantic_data
                    error_match = CorrelationMatch(
                        match_id=match.match_id,
                        timestamp=match.timestamp,
                        feather_records=match.feather_records,  # Keep original records
                        match_score=match.match_score,
                        feather_count=match.feather_count,
                        time_spread_seconds=match.time_spread_seconds,
                        anchor_feather_id=match.anchor_feather_id,
                        anchor_artifact_type=match.anchor_artifact_type,
                        matched_application=match.matched_application,
                        matched_file_path=match.matched_file_path,
                        matched_event_id=match.matched_event_id,
                        score_breakdown=match.score_breakdown,
                        confidence_score=match.confidence_score,
                        confidence_category=match.confidence_category,
                        weighted_score=match.weighted_score,
                        time_deltas=match.time_deltas,
                        field_similarity_scores=match.field_similarity_scores,
                        candidate_counts=match.candidate_counts,
                        algorithm_version=match.algorithm_version,
                        wing_config_hash=match.wing_config_hash,
                        is_duplicate=match.is_duplicate,
                        duplicate_info=match.duplicate_info,
                        semantic_data=error_semantic_data
                    )
                    
                    enhanced_matches.append(error_match)
        
        except Exception as e:
            # Task 6.1: Critical failure in semantic mapping - continue correlation without semantic data
            # Requirements: 7.1, 7.2, 7.3 - Never crash correlation due to semantic mapping issues
            critical_failure = True
            logger.error(f"Critical failure in semantic mapping processing: {e}")
            print(f"[SEMANTIC] ERROR: Critical semantic mapping failure - {str(e)[:100]}...")
            print("[SEMANTIC] WARNING: Continuing correlation without semantic mapping")
            
            # Return original matches with error metadata
            enhanced_matches = []
            for match in matches:
                error_semantic_data = {
                    '_metadata': {
                        'mappings_applied': False,
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'engine_type': 'IdentityBasedEngineAdapter',
                        'fallback_reason': 'Critical semantic mapping failure'
                    }
                }
                
                error_match = CorrelationMatch(
                    match_id=match.match_id,
                    timestamp=match.timestamp,
                    feather_records=match.feather_records,  # Keep original records
                    match_score=match.match_score,
                    feather_count=match.feather_count,
                    time_spread_seconds=match.time_spread_seconds,
                    anchor_feather_id=match.anchor_feather_id,
                    anchor_artifact_type=match.anchor_artifact_type,
                    matched_application=match.matched_application,
                    matched_file_path=match.matched_file_path,
                    matched_event_id=match.matched_event_id,
                    score_breakdown=match.score_breakdown,
                    confidence_score=match.confidence_score,
                    confidence_category=match.confidence_category,
                    weighted_score=match.weighted_score,
                    time_deltas=match.time_deltas,
                    field_similarity_scores=match.field_similarity_scores,
                    candidate_counts=match.candidate_counts,
                    algorithm_version=match.algorithm_version,
                    wing_config_hash=match.wing_config_hash,
                    is_duplicate=match.is_duplicate,
                    duplicate_info=match.duplicate_info,
                    semantic_data=error_semantic_data
                )
                
                enhanced_matches.append(error_match)
        
        # Add GUI terminal output showing semantic rule detection statistics - SUMMARY ONLY
        # Requirements: 4.1, 4.2, 4.3 - Print detected semantic rules to GUI terminal
        try:
            if not critical_failure:
                # Don't print individual engine summaries - let the integration handle global summary
                semantic_stats = self.semantic_integration.get_mapping_statistics()
                
                # Only show errors if any
                if errors_count > 0:
                    print(f"[SEMANTIC] WARNING: Identity Engine had {errors_count} semantic mapping errors")
            else:
                print("[SEMANTIC] ERROR: Identity Engine semantic mapping failed - correlation completed")
        except Exception as stats_error:
            # Even statistics printing should not crash correlation
            logger.debug(f"Failed to print semantic mapping statistics: {stats_error}")
            # Don't print error to GUI - just continue silently
        
        # Log completion with statistics (only if debug mode)
        if self.debug_mode and not critical_failure:
            try:
                semantic_stats = self.semantic_integration.get_mapping_statistics()
                logger.debug(f"Identity Engine semantic mapping completed: {semantic_stats.mappings_applied} mappings on {len(matches)} matches")
                if errors_count > 0:
                    logger.debug(f"Semantic mapping errors: {errors_count}")
            except Exception as log_error:
                logger.debug(f"Failed to log semantic mapping completion statistics: {log_error}")
        
        return enhanced_matches
    
    def _apply_weighted_scoring(self, 
                              matches: List[CorrelationMatch], 
                              wing_configs: List[Any]) -> List[CorrelationMatch]:
        """
        Apply weighted scoring to correlation matches using integration layer.
        
        Args:
            matches: List of correlation matches
            wing_configs: Wing configurations for scoring context
            
        Returns:
            Matches with weighted scoring information
        """
        scored_matches = []
        case_id = getattr(self.config, 'case_id', None)
        
        # Check if weighted scoring is enabled
        if not self.scoring_integration.is_enabled():
            if self.verbose_logging:
                logger.info("Weighted scoring is disabled, using simple count-based scoring")
            return self._apply_simple_count_scoring(matches, wing_configs)
        
        if self.verbose_logging:
            logger.info(f"Applying weighted scoring to {len(matches)} correlation matches")
        
        for match in matches:
            try:
                # Find appropriate wing config for this match
                wing_config = wing_configs[0] if wing_configs else None  # Simplified
                
                if wing_config:
                    # Calculate weighted score using integration layer
                    weighted_score = self.scoring_integration.calculate_match_scores(
                        match.feather_records, wing_config, case_id
                    )
                    
                    # Update match with scoring information
                    scored_match = CorrelationMatch(
                        match_id=match.match_id,
                        timestamp=match.timestamp,
                        feather_records=match.feather_records,
                        match_score=weighted_score.get('score', match.match_score) if isinstance(weighted_score, dict) else match.match_score,
                        feather_count=match.feather_count,
                        time_spread_seconds=match.time_spread_seconds,
                        anchor_feather_id=match.anchor_feather_id,
                        anchor_artifact_type=match.anchor_artifact_type,
                        matched_application=match.matched_application,
                        matched_file_path=match.matched_file_path,
                        matched_event_id=match.matched_event_id,
                        score_breakdown=weighted_score.get('breakdown', match.score_breakdown) if isinstance(weighted_score, dict) else match.score_breakdown,
                        confidence_score=weighted_score.get('score', match.confidence_score) if isinstance(weighted_score, dict) else match.confidence_score,
                        confidence_category=weighted_score.get('interpretation', match.confidence_category) if isinstance(weighted_score, dict) else match.confidence_category,
                        weighted_score=weighted_score if isinstance(weighted_score, dict) else None,
                        time_deltas=match.time_deltas,
                        field_similarity_scores=match.field_similarity_scores,
                        candidate_counts=match.candidate_counts,
                        algorithm_version=match.algorithm_version,
                        wing_config_hash=match.wing_config_hash,
                        is_duplicate=match.is_duplicate,
                        duplicate_info=match.duplicate_info,
                        semantic_data=getattr(match, 'semantic_data', {})
                    )
                else:
                    # No wing config available, keep original match
                    scored_match = match
                
                scored_matches.append(scored_match)
                
            except Exception as e:
                # If weighted scoring fails for this match, fall back to simple scoring
                if self.verbose_logging:
                    logger.warning(f"Weighted scoring failed for match {match.match_id}: {e}")
                    logger.info(f"Falling back to simple count-based scoring for match {match.match_id}")
                
                # Apply simple scoring to this match
                simple_scored_match = self._apply_simple_count_scoring_to_match(match, wing_configs)
                scored_matches.append(simple_scored_match)
        
        # Log weighted scoring statistics (only if verbose)
        if self.verbose_logging:
            scoring_stats = self.scoring_integration.get_scoring_statistics()
            logger.info(f"Weighted scoring application completed:")
            logger.info(f"  Matches processed: {len(matches)}")
            logger.info(f"  Scores calculated: {scoring_stats.scores_calculated}")
            logger.info(f"  Fallbacks to simple count: {scoring_stats.fallback_to_simple_count}")
            logger.info(f"  Average score: {scoring_stats.average_score:.2f}")
        
        # Log detailed scoring summary
        execution_time = (datetime.now() - datetime.now()).total_seconds()  # This would be actual execution time
        self.scoring_integration.log_scoring_summary(len(matches), execution_time)
        
        return scored_matches
    
    def _apply_simple_count_scoring(self, 
                                  matches: List[CorrelationMatch], 
                                  wing_configs: List[Any]) -> List[CorrelationMatch]:
        """
        Apply simple count-based scoring as fallback when weighted scoring is disabled.
        
        Args:
            matches: List of correlation matches
            wing_configs: Wing configurations for context
            
        Returns:
            Matches with simple count-based scoring information
        """
        scored_matches = []
        
        for match in matches:
            scored_match = self._apply_simple_count_scoring_to_match(match, wing_configs)
            scored_matches.append(scored_match)
        
        if self.verbose_logging:
            logger.info(f"Simple count-based scoring applied to {len(matches)} matches")
        return scored_matches
    
    def _apply_scoring_to_single_match(self, 
                                       match: CorrelationMatch, 
                                       wing_config: Any) -> CorrelationMatch:
        """
        Apply weighted scoring to a single match.
        Used in streaming mode to score matches before writing to database.
        
        Task 1.1: Remove semantic mapping from correlation processing
        Requirements: 1.1, 1.2, 1.3, 1.4
        Semantic matching will be applied AFTER correlation reaches 100% in Identity Semantic Phase
        
        Args:
            match: Correlation match to process
            wing_config: Wing configuration for context
            
        Returns:
            Match with scoring applied (NO semantic data during correlation)
        """
        try:
            case_id = getattr(self.config, 'case_id', None)
            
            # Task 1.1: NO semantic mapping during correlation
            # Semantic data will be applied in Identity Semantic Phase after 100% completion
            semantic_data = None
            
            # Apply weighted scoring if enabled
            weighted_score = None
            score_breakdown = None
            confidence_score = None
            confidence_category = None
            
            if self.scoring_integration.is_enabled() and wing_config:
                try:
                    weighted_score = self.scoring_integration.calculate_match_scores(
                        match.feather_records, wing_config, case_id
                    )
                    if isinstance(weighted_score, dict):
                        score_breakdown = weighted_score.get('breakdown')
                        confidence_score = weighted_score.get('score')
                        confidence_category = weighted_score.get('interpretation')
                except Exception as e:
                    if getattr(self, 'verbose_logging', False):
                        logger.warning(f"Weighted scoring failed for match {match.match_id}: {e}")
                    # Fall back to simple scoring
                    weighted_score = self._calculate_simple_score(match, wing_config)
            else:
                # Use simple scoring
                weighted_score = self._calculate_simple_score(match, wing_config)
            
            # Create scored match WITHOUT semantic data (will be added in Identity Semantic Phase)
            scored_match = CorrelationMatch(
                match_id=match.match_id,
                timestamp=match.timestamp,
                feather_records=match.feather_records,  # Original records, no semantic enhancement
                match_score=weighted_score.get('score', match.match_score) if isinstance(weighted_score, dict) else match.match_score,
                feather_count=match.feather_count,
                time_spread_seconds=match.time_spread_seconds,
                anchor_feather_id=match.anchor_feather_id,
                anchor_artifact_type=match.anchor_artifact_type,
                matched_application=match.matched_application,
                matched_file_path=match.matched_file_path,
                matched_event_id=match.matched_event_id,
                score_breakdown=score_breakdown or match.score_breakdown,
                confidence_score=confidence_score or match.confidence_score,
                confidence_category=confidence_category or match.confidence_category,
                weighted_score=weighted_score if isinstance(weighted_score, dict) else None,
                is_duplicate=match.is_duplicate,
                semantic_data=semantic_data
            )
            
            # Copy anchor metadata
            if hasattr(match, 'anchor_start_time'):
                scored_match.anchor_start_time = match.anchor_start_time
            if hasattr(match, 'anchor_end_time'):
                scored_match.anchor_end_time = match.anchor_end_time
            if hasattr(match, 'anchor_record_count'):
                scored_match.anchor_record_count = match.anchor_record_count
            
            return scored_match
            
        except Exception as e:
            if getattr(self, 'verbose_logging', False):
                logger.warning(f"Error applying scoring to match {match.match_id}: {e}")
            return match
    
    def _calculate_simple_score(self, match: CorrelationMatch, wing_config: Any) -> Dict[str, Any]:
        """Calculate simple count-based score for a match."""
        feather_count = match.feather_count or len(match.feather_records)
        total_feathers = len(getattr(wing_config, 'feathers', [])) if wing_config else feather_count
        
        if total_feathers > 0:
            score = feather_count / total_feathers
            match_percentage = score * 100
            if match_percentage >= 80:
                interpretation = f"Strong Match ({feather_count}/{total_feathers} feathers)"
            elif match_percentage >= 50:
                interpretation = f"Good Match ({feather_count}/{total_feathers} feathers)"
            elif match_percentage >= 25:
                interpretation = f"Partial Match ({feather_count}/{total_feathers} feathers)"
            else:
                interpretation = f"Weak Match ({feather_count}/{total_feathers} feathers)"
        else:
            score = 0.5
            interpretation = f"Match ({feather_count} feathers)"
        
        return {
            'score': score,
            'interpretation': interpretation,
            'breakdown': {
                'feather_count': feather_count,
                'total_feathers': total_feathers,
                'scoring_method': 'simple_count'
            }
        }
    
    def _apply_simple_count_scoring_to_match(self, 
                                           match: CorrelationMatch, 
                                           wing_configs: List[Any]) -> CorrelationMatch:
        """
        Apply simple count-based scoring to a single match.
        
        Args:
            match: Correlation match to score
            wing_configs: Wing configurations for context
            
        Returns:
            Match with simple count-based scoring information
        """
        # Get wing configuration for context
        wing_config = wing_configs[0] if wing_configs else None
        
        # Calculate simple score based on feather count
        feather_count = match.feather_count or len(match.feather_records)
        total_feathers = len(getattr(wing_config, 'feathers', [])) if wing_config else feather_count
        
        # Simple score is just the count of matched feathers
        simple_score = feather_count
        
        # Generate simple interpretation
        if total_feathers > 0:
            match_percentage = (feather_count / total_feathers) * 100
            if match_percentage >= 80:
                interpretation = f"Strong Match ({feather_count}/{total_feathers} feathers)"
            elif match_percentage >= 50:
                interpretation = f"Good Match ({feather_count}/{total_feathers} feathers)"
            elif match_percentage >= 25:
                interpretation = f"Partial Match ({feather_count}/{total_feathers} feathers)"
            else:
                interpretation = f"Weak Match ({feather_count}/{total_feathers} feathers)"
        else:
            interpretation = f"Match ({feather_count} feathers)"
        
        # Create simple scoring breakdown
        simple_breakdown = {
            feather_id: {
                'matched': True,
                'weight': 1.0,
                'contribution': 1.0,
                'tier': 1,
                'tier_name': 'Standard'
            }
            for feather_id in match.feather_records.keys()
        }
        
        # Create simple weighted score structure
        simple_weighted_score = {
            'score': simple_score,
            'interpretation': interpretation,
            'breakdown': simple_breakdown,
            'matched_feathers': feather_count,
            'total_feathers': total_feathers,
            'scoring_mode': 'simple_count'
        }
        
        # Update match with simple scoring information
        return CorrelationMatch(
            match_id=match.match_id,
            timestamp=match.timestamp,
            feather_records=match.feather_records,
            match_score=simple_score,
            feather_count=match.feather_count,
            time_spread_seconds=match.time_spread_seconds,
            anchor_feather_id=match.anchor_feather_id,
            anchor_artifact_type=match.anchor_artifact_type,
            matched_application=match.matched_application,
            matched_file_path=match.matched_file_path,
            matched_event_id=match.matched_event_id,
            score_breakdown=simple_breakdown,
            confidence_score=simple_score,
            confidence_category=interpretation,
            weighted_score=simple_weighted_score,
            time_deltas=match.time_deltas,
            field_similarity_scores=match.field_similarity_scores,
            candidate_counts=match.candidate_counts,
            algorithm_version=match.algorithm_version,
            wing_config_hash=match.wing_config_hash,
            is_duplicate=match.is_duplicate,
            duplicate_info=match.duplicate_info,
            semantic_data=getattr(match, 'semantic_data', {})
        )
    
    def _should_run_identity_semantic_phase(self) -> bool:
        """
        Determine if Identity Semantic Phase should run.
        
        Task 4.1: Add _should_run_identity_semantic_phase() method
        Requirements: 2.1, 2.3
        
        Returns:
            True if phase is enabled and correlation is complete
        """
        # Check if Identity Semantic Phase is enabled in configuration
        # Default to True if not explicitly set
        if not hasattr(self.config, 'identity_semantic_phase_enabled'):
            # Default: enabled
            phase_enabled = True
        else:
            phase_enabled = self.config.identity_semantic_phase_enabled
        
        if not phase_enabled:
            if self.verbose_logging:
                logger.info("[Identity Engine] Identity Semantic Phase disabled in configuration")
            return False
        
        # Check if semantic integration is available
        if not hasattr(self, 'semantic_integration'):
            if self.verbose_logging:
                logger.warning("[Identity Engine] Semantic integration not available")
            return False
        
        # Check if semantic integration is enabled
        if not self.semantic_integration.is_enabled():
            if self.verbose_logging:
                logger.info("[Identity Engine] Semantic integration disabled")
            return False
        
        # All checks passed - phase should run
        return True
    
    def _calculate_score(self, match: CorrelationMatch, wing_config: Any) -> float:
        """
        Calculate score for a match using centralized configuration.
        
        This method delegates to the scoring integration layer which uses
        the centralized score configuration.
        
        Args:
            match: Correlation match to score
            wing_config: Wing configuration for scoring context
        
        Returns:
            Calculated score value
        
        Requirements: 7.2, 8.3
        """
        if self.scoring_integration.is_enabled():
            case_id = getattr(self.config, 'case_id', None)
            weighted_score = self.scoring_integration.calculate_match_scores(
                match.feather_records, wing_config, case_id
            )
            if isinstance(weighted_score, dict):
                return weighted_score.get('score', 0.0)
        
        # Fallback to simple count-based scoring
        feather_count = match.feather_count or len(match.feather_records)
        total_feathers = len(getattr(wing_config, 'feathers', [])) if wing_config else feather_count
        return feather_count / total_feathers if total_feathers > 0 else 0.5
    
    def _interpret_score(self, score: float) -> str:
        """
        Interpret a score value using centralized configuration thresholds.
        
        Args:
            score: Score value to interpret (0.0 to 1.0)
        
        Returns:
            String interpretation ('Critical', 'High', 'Medium', 'Low', or 'Minimal')
        
        Requirements: 7.2, 8.3
        """
        config = self.score_config_manager.get_configuration()
        return config.interpret_score(score)
    
    def _execute_identity_semantic_phase(self, 
                                        correlation_results: CorrelationResult,
                                        wing_configs: List[Any]) -> CorrelationResult:
        """
        Execute Identity Semantic Phase after correlation completes.
        
        This method applies identity-level semantic mappings in a dedicated final analysis phase,
        processing each unique identity once rather than per-record during correlation.
        
        Task 4.2: Add _execute_identity_semantic_phase() method
        Task 7.1: Integrate with IdentityBasedEngineAdapter
        Requirements: 2.1, 2.2, 2.4, 10.1, 10.2, 10.3, 14.1, 14.2
        
        Args:
            correlation_results: Results from correlation engine
            wing_configs: Wing configurations for context
            
        Returns:
            Enhanced correlation results with identity-level semantic data
        """
        # Check if Identity Semantic Phase should run
        if not self._should_run_identity_semantic_phase():
            if self.verbose_logging:
                logger.info("[Identity Engine] Identity Semantic Phase skipped")
            return correlation_results
        
        try:
            # Import Identity Semantic Phase components
            from ..identity_semantic_phase.identity_semantic_controller import (
                IdentitySemanticController,
                IdentitySemanticConfig
            )
            
            # Create configuration for Identity Semantic Phase
            semantic_enabled = self.semantic_integration.is_enabled()
            
            phase_config = IdentitySemanticConfig(
                enabled=True,
                semantic_mapping_enabled=semantic_enabled,
                identity_extraction_enabled=True,
                progress_reporting_enabled=True,
                debug_mode=self.debug_mode
            )
            
            # Create Identity Semantic Controller
            controller = IdentitySemanticController(
                config=phase_config,
                semantic_integration=self.semantic_integration
            )
            
            # Execute final analysis phase
            enhanced_results = controller.execute_final_analysis(
                correlation_results=correlation_results,
                engine_type="identity_based"
            )
            
            return enhanced_results
            
        except ImportError as e:
            # Identity Semantic Phase components not available
            logger.warning(f"[Identity Engine] Identity Semantic Phase not available: {e}")
            if self.verbose_logging:
                print(f"[Identity Engine] Identity Semantic Phase import failed: {e}")
            return correlation_results
            
        except Exception as e:
            # Error during Identity Semantic Phase execution
            # Log error but return original results (graceful degradation)
            logger.error(f"[Identity Engine] Identity Semantic Phase failed: {e}")
            print(f"[Identity Engine] WARNING: Identity Semantic Phase failed: {e}")
            print(f"[Identity Engine] Continuing with original correlation results")
            return correlation_results
    
    def _estimate_total_identities(self, wing_configs: List[Any]) -> int:
        """
        Estimate total number of identities to process for progress tracking.
        
        Args:
            wing_configs: Wing configurations
            
        Returns:
            Estimated number of identities
        """
        # Simple estimation - in real implementation would analyze wing contents
        return len(wing_configs) * 100  # Assume 100 identities per wing
    
    def _should_filter_record(self, record: Dict[str, Any]) -> bool:
        """
        Check if a record should be filtered out based on time period and identity filters.
        
        Args:
            record: Record to check
            
        Returns:
            True if record should be filtered out (excluded), False if it should be kept
        """
        # Apply time period filter
        if self.filters.time_period_start or self.filters.time_period_end:
            # Extract timestamp from record
            timestamp = None
            for ts_field in self.core_engine.timestamp_field_patterns:
                if ts_field in record and record[ts_field]:
                    # Use base engine's timestamp parsing method
                    timestamp = self._parse_timestamp(record[ts_field])
                    if timestamp:
                        break
            
            # If we have a timestamp, check if it's within the filter range
            if timestamp:
                if self.filters.time_period_start and timestamp < self.filters.time_period_start:
                    return True  # Filter out (too early)
                if self.filters.time_period_end and timestamp > self.filters.time_period_end:
                    return True  # Filter out (too late)
        
        # Apply identity filter
        if self.filters.identity_filters:
            # Extract identity from record
            name, path, hash_val, _ = self.core_engine.extract_identity_info(record)
            
            # Check if any identity component matches the filter patterns
            identity_matches = False
            for filter_pattern in self.filters.identity_filters:
                # Support wildcards
                import fnmatch
                
                # Prepare comparison strings
                if self.filters.case_sensitive:
                    name_cmp = name
                    path_cmp = path
                    pattern_cmp = filter_pattern
                else:
                    name_cmp = name.lower() if name else ""
                    path_cmp = path.lower() if path else ""
                    pattern_cmp = filter_pattern.lower()
                
                # Check if pattern matches name, path, or hash
                if (fnmatch.fnmatch(name_cmp, pattern_cmp) or
                    fnmatch.fnmatch(path_cmp, pattern_cmp) or
                    (hash_val and fnmatch.fnmatch(hash_val.lower(), pattern_cmp.lower()))):
                    identity_matches = True
                    break
            
            # If identity filters are specified but no match found, filter out
            if not identity_matches:
                return True  # Filter out (doesn't match identity filter)
        
        return False  # Keep record
    
    def _get_applied_filters(self) -> Dict[str, Any]:
        """Get dictionary of applied filters"""
        return {
            'time_period_start': self.filters.time_period_start.isoformat() if self.filters.time_period_start else None,
            'time_period_end': self.filters.time_period_end.isoformat() if self.filters.time_period_end else None,
            'identity_filters': self.filters.identity_filters,
            'case_sensitive': self.filters.case_sensitive
        }
    
    def _log_final_statistics(self):
        """Log final correlation statistics including comprehensive semantic mapping details and identity-specific metrics"""
        stats = self.last_statistics
        # Only log detailed statistics if verbose logging is enabled
        if self.verbose_logging:
            semantic_stats = self.semantic_integration.get_mapping_statistics()
            
            logger.info("Identity-based correlation completed:")
            logger.info(f"  Execution time: {stats.get('execution_time', 0):.2f} seconds")
            logger.info(f"  Records processed: {stats.get('record_count', 0)}")
            logger.info(f"  Matches found: {stats.get('match_count', 0)}")
            logger.info(f"  Identities processed: {stats.get('identities_processed', 0)}")
            
            # Log identity-specific progress tracking statistics
            if hasattr(self, 'progress_tracker'):
                progress_data = self.progress_tracker._create_overall_progress()
                logger.info("Identity processing statistics:")
                logger.info(f"  Total identities: {progress_data.total_windows}")
                logger.info(f"  Identities completed: {progress_data.windows_processed}")
                logger.info(f"  Processing rate: {progress_data.processing_rate_windows_per_second:.2f} identities/second" if progress_data.processing_rate_windows_per_second else "  Processing rate: N/A")
                logger.info(f"  Average time per identity: {1.0/progress_data.processing_rate_windows_per_second:.3f} seconds" if progress_data.processing_rate_windows_per_second else "  Average time per identity: N/A")
            
            if self.semantic_integration.is_enabled():
                logger.info("Semantic mapping statistics:")
                logger.info(f"  Total records processed: {semantic_stats.total_records_processed}")
                logger.info(f"  Semantic mappings applied: {semantic_stats.mappings_applied}")
                logger.info(f"  Unmapped fields: {semantic_stats.unmapped_fields}")
                logger.info(f"  Pattern matches: {semantic_stats.pattern_matches}")
            logger.info(f"  Exact matches: {semantic_stats.exact_matches}")
            
            if semantic_stats.total_records_processed > 0:
                mapping_rate = (semantic_stats.mappings_applied / semantic_stats.total_records_processed) * 100
                logger.info(f"  Mapping rate: {mapping_rate:.1f}%")
            
            # Log case-specific vs global mapping usage
            if self.semantic_integration.case_specific_enabled:
                logger.info(f"  Global mappings used: {semantic_stats.global_mappings_used}")
                logger.info(f"  Case-specific mappings used: {semantic_stats.case_specific_mappings_used}")
            
            # Log fallback statistics if any failures occurred
            fallback_stats = self.semantic_integration.get_fallback_statistics()
            if fallback_stats['total_fallbacks'] > 0:
                logger.warning("Semantic mapping fallback statistics:")
                logger.warning(f"  Total fallbacks: {fallback_stats['total_fallbacks']}")
                logger.warning(f"  Manager failures: {fallback_stats['manager_failures']}")
                logger.warning(f"  Recovery attempts: {fallback_stats['recovery_attempts']}")
                logger.warning(f"  Successful recoveries: {fallback_stats['successful_recoveries']}")
        else:
            logger.info("Semantic mapping was disabled for this correlation")
    
    def get_results(self) -> Optional[CorrelationResult]:
        """Get correlation results from last execution"""
        return self.last_results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get correlation statistics from last execution"""
        base_stats = self.last_statistics.copy() if self.last_statistics else {}
        
        # Add semantic mapping statistics
        if hasattr(self, 'semantic_integration'):
            semantic_stats = self.semantic_integration.get_mapping_statistics()
            base_stats['semantic_mapping'] = {
                'enabled': self.semantic_integration.is_enabled(),
                'total_records_processed': semantic_stats.total_records_processed,
                'mappings_applied': semantic_stats.mappings_applied,
                'unmapped_fields': semantic_stats.unmapped_fields,
                'pattern_matches': semantic_stats.pattern_matches,
                'exact_matches': semantic_stats.exact_matches,
                'global_mappings_used': semantic_stats.global_mappings_used,
                'case_specific_mappings_used': semantic_stats.case_specific_mappings_used,
                'fallback_statistics': self.semantic_integration.get_fallback_statistics()
            }
        
        # Add weighted scoring statistics
        if hasattr(self, 'scoring_integration'):
            scoring_stats = self.scoring_integration.get_scoring_statistics()
            base_stats['weighted_scoring'] = {
                'enabled': self.scoring_integration.is_enabled(),
                'total_matches_scored': scoring_stats.total_matches_scored,
                'scores_calculated': scoring_stats.scores_calculated,
                'fallback_to_simple_count': scoring_stats.fallback_to_simple_count,
                'average_score': scoring_stats.average_score,
                'highest_score': scoring_stats.highest_score,
                'lowest_score': scoring_stats.lowest_score,
                'case_specific_configs_used': scoring_stats.case_specific_configs_used,
                'global_configs_used': scoring_stats.global_configs_used
            }
        
        return base_stats
    
    def add_progress_listener(self, listener: ProgressListener):
        """
        Add a progress listener to receive progress events.
        
        Args:
            listener: ProgressListener to receive events
        """
        self.progress_tracker.add_listener(listener)
    
    def register_progress_listener(self, listener):
        """
        Register a progress listener for GUI updates.
        
        Args:
            listener: Callable that receives progress events or ProgressListener object
        """
        # Support both old-style callable listeners and new ProgressListener objects
        if hasattr(listener, 'on_progress_event'):
            # New-style ProgressListener
            self.progress_tracker.add_listener(listener)
        else:
            # Legacy callable listener - wrap it in a ProgressListener
            class LegacyListenerWrapper(ProgressListener):
                def __init__(self, callback):
                    self.callback = callback
                
                def on_progress_event(self, event: ProgressEvent):
                    # Convert to legacy format for backward compatibility
                    legacy_event = type('LegacyEvent', (), {
                        'event_type': event.event_type.value,
                        'data': {
                            'windows_processed': event.overall_progress.windows_processed,
                            'total_windows': event.overall_progress.total_windows,
                            'matches_found': event.overall_progress.matches_found,
                            'completion_percentage': event.overall_progress.completion_percentage,
                            'message': event.message
                        }
                    })()
                    self.callback(legacy_event)
            
            wrapper = LegacyListenerWrapper(listener)
            self.progress_tracker.add_listener(wrapper)
    
    def remove_progress_listener(self, listener: ProgressListener):
        """
        Remove a progress listener.
        
        Args:
            listener: ProgressListener to remove
        """
        self.progress_tracker.remove_listener(listener)
    
    def request_cancellation(self):
        """Request cancellation of the current correlation operation"""
        self.progress_tracker.request_cancellation()
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        return self.progress_tracker.is_cancelled()
    
    def get_semantic_mapping_info(self) -> Dict[str, Any]:
        """
        Get semantic mapping information for UI display and debugging.
        
        Returns:
            Dictionary with semantic mapping status and statistics
        """
        if not hasattr(self, 'semantic_integration'):
            return {'enabled': False, 'error': 'Semantic integration not initialized'}
        
        try:
            stats = self.semantic_integration.get_mapping_statistics()
            available_mappings = self.semantic_integration.get_available_mappings()
            
            return {
                'enabled': self.semantic_integration.is_enabled(),
                'healthy': self.semantic_integration.is_healthy(),
                'case_specific_enabled': self.semantic_integration.case_specific_enabled,
                'current_case_id': self.semantic_integration.current_case_id,
                'available_mappings_count': len(available_mappings),
                'statistics': {
                    'total_records_processed': stats.total_records_processed,
                    'mappings_applied': stats.mappings_applied,
                    'unmapped_fields': stats.unmapped_fields,
                    'pattern_matches': stats.pattern_matches,
                    'exact_matches': stats.exact_matches,
                    'global_mappings_used': stats.global_mappings_used,
                    'case_specific_mappings_used': stats.case_specific_mappings_used
                },
                'fallback_statistics': self.semantic_integration.get_fallback_statistics()
            }
        except Exception as e:
            logger.error(f"Failed to get semantic mapping info: {e}")
            return {'enabled': False, 'error': str(e)}
    
    def get_paused_executions(self, output_dir: str) -> List[Dict[str, Any]]:
        """
        Get list of paused executions that can be resumed.
        
        Args:
            output_dir: Directory containing correlation_results.db
            
        Returns:
            List of paused execution information
        """
        from pathlib import Path
        from .database_persistence import ResultsDatabase
        
        db_path = Path(output_dir) / "correlation_results.db"
        
        if not db_path.exists():
            return []
        
        try:
            with ResultsDatabase(str(db_path)) as db:
                return db.get_paused_executions()
        except Exception as e:
            print(f"[Identity Engine] Error loading paused executions: {e}")
            return []