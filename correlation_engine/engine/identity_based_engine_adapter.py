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
from .progress_tracking import ProgressTracker, ProgressListener, ProgressEvent, ProgressEventType
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
    
    def __init__(self, config: Any, filters: Optional[FilterConfig] = None):
        """
        Initialize Identity-Based Engine Adapter.
        
        Args:
            config: Pipeline configuration object
            filters: Optional filter configuration
        """
        super().__init__(config, filters)
        
        # Debug mode control
        self.debug_mode = getattr(config, 'debug_mode', False)
        self.verbose_logging = getattr(config, 'verbose_logging', False)
        
        # Initialize integration systems first
        self.semantic_integration = SemanticMappingIntegration(getattr(config, 'config_manager', None))
        self.scoring_integration = WeightedScoringIntegration(getattr(config, 'config_manager', None))
        self.progress_tracker = ProgressTracker(debug_mode=self.debug_mode)
        
        # Initialize core engine with debug mode only
        # (semantic mapping and scoring are handled by the adapter, not the core engine)
        self.core_engine = IdentityCorrelationEngine(
            debug_mode=self.debug_mode
        )
        
        # Verify semantic integration health (only log if verbose)
        if not self.semantic_integration.is_healthy() and self.verbose_logging:
            logger.warning("Semantic mapping integration health check failed - some features may not work correctly")
        
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
    
    def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
        """
        Execute identity-based correlation with integrated systems.
        
        Args:
            wing_configs: List of Wing configuration objects
            
        Returns:
            Dictionary containing correlation results and metadata
        """
        start_time = datetime.now()
        
        # Always print which engine is being used
        print("\n" + "="*70)
        print("🔧 CORRELATION ENGINE: Identity-Based")
        print("="*70)
        
        try:
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
            
            for wing_idx, wing_config in enumerate(wing_configs, 1):
                wing_name = getattr(wing_config, 'wing_name', 'Unknown')
                print(f"[Identity Engine] Wing {wing_idx}/{len(wing_configs)}: {wing_name}")
                wing_matches, wing_identity_count = self._process_wing(wing_config, 0, 1)
                
                if streaming_enabled:
                    # In streaming mode, matches are written to DB, wing_matches is empty
                    # But we need to count them - get count from the result record
                    print(f"[Identity Engine] DEBUG: Streaming mode - matches saved to database")
                    # The match count is tracked in _process_wing and saved to DB
                else:
                    print(f"[Identity Engine] DEBUG: _process_wing returned {len(wing_matches)} matches, {wing_identity_count} identities")
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
                print(f"[Identity Engine] DEBUG: Total matches from database = {total_match_count}")
            else:
                total_match_count = len(all_matches)
                print(f"[Identity Engine] DEBUG: Total all_matches = {len(all_matches)}")
            
            # Apply semantic mappings to results (silent unless verbose)
            # Skip if streaming mode (matches already in DB)
            if streaming_enabled:
                enhanced_matches = []
                scored_matches = []
            else:
                if self.semantic_integration.is_enabled():
                    if self.verbose_logging:
                        print(f"[Identity Engine] Applying semantic mappings...")
                    enhanced_matches = self._apply_semantic_mappings(all_matches, wing_configs)
                else:
                    enhanced_matches = all_matches
                
                # Calculate weighted scores (silent unless verbose)
                if self.verbose_logging:
                    print(f"[Identity Engine] Calculating weighted scores...")
                scored_matches = self._apply_weighted_scoring(enhanced_matches, wing_configs)
                
                print(f"[Identity Engine] DEBUG: enhanced_matches = {len(enhanced_matches)}, scored_matches = {len(scored_matches)}")
            
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
            
            self.last_results = CorrelationResult(
                wing_id=wing_configs[0].wing_id if wing_configs else "unknown",
                wing_name=wing_configs[0].wing_name if wing_configs else "unknown",
                matches=scored_matches,
                total_matches=total_match_count,  # Use tracked count (works for both streaming and non-streaming)
                execution_duration_seconds=execution_time,
                filters_applied=self._get_applied_filters(),
                feather_metadata={
                    # Engine metadata stored as a single dict entry with key '_engine_metadata'
                    '_engine_metadata': {
                        'engine_type': 'identity_based',
                        'streaming_mode': streaming_enabled,
                        'semantic_mapping_enabled': self.semantic_integration.is_enabled(),
                        'semantic_stats': semantic_stats_dict,
                        'weighted_scoring_enabled': self.scoring_integration.is_enabled(),
                        'scoring_stats': scoring_stats_dict,
                        'identities_processed': total_identities,
                        'core_engine_stats': self._get_core_engine_stats()
                    }
                }
            )
            
            # Debug: Verify matches are set
            print(f"[Identity Engine] DEBUG: Created CorrelationResult with {len(scored_matches)} matches (total_matches={total_match_count})")
            print(f"[Identity Engine] DEBUG: Streaming mode: {streaming_enabled}")
            
            # Store engine type as a direct attribute for easy access
            self.last_results.engine_type = "identity_based"
            
            # Complete progress tracking
            self.progress_tracker.complete_scanning()
            
            # Print simple completion summary
            print("[Identity Engine] ✓ Complete!")
            print(f"[Identity Engine] ✓ Processed {total_identities:,} identities")
            print(f"[Identity Engine] ✓ Created {total_match_count:,} matches")
            if streaming_enabled:
                print(f"[Identity Engine] ✓ Matches saved to database via streaming")
            print(f"[Identity Engine] ✓ Time: {execution_time:.2f}s")
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
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.progress_tracker.report_error(f"Identity correlation failed: {str(e)}", str(e))
            logger.error(f"Identity-based correlation failed: {error_msg}")
            print(f"[Identity Engine] CRITICAL ERROR: {error_msg}")
            raise
    
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
                from .correlation_result import CorrelationResult
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
            from .correlation_result import CorrelationResult
            error_result = CorrelationResult(
                wing_id=wing.wing_id,
                wing_name=wing.wing_name
            )
            error_result.matches = []
            error_result.total_matches = 0
            error_result.execution_duration_seconds = 0.0
            error_result.errors = [f"Wing execution failed: {str(e)}"]
            
            return error_result
    
    def _process_wing(self, wing_config: Any, processed_identities_offset: int, total_identities_global: int) -> Tuple[List[CorrelationMatch], int]:
        """
        Process a single wing configuration with identity-specific progress tracking.
        Supports streaming mode for incremental database writes.
        
        Args:
            wing_config: Wing configuration object
            processed_identities_offset: Number of identities already processed in previous wings
            total_identities_global: Total estimated identities across all wings
            
        Returns:
            Tuple of (list of correlation matches, number of identities processed in this wing)
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
                # Show progress for each feather
                print(f"[Identity Engine]   [{feather_count}/{total_feathers}] {feather_id}")
                
                if self.verbose_logging:
                    logger.info(f"Loading feather: {feather_id} from {db_path}")
                
                # Initialize stats for this feather
                feather_stats[feather_id] = {
                    'total': 0,
                    'extracted': 0,
                    'identities': set()
                }
                
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Get all tables in the database
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                
                feather_records = 0
                
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
                            
                            # Extract identity using core engine
                            name, path, hash_val, id_type = self.core_engine.extract_identity_info(record)
                            
                            if name or path or hash_val:
                                # Normalize identity key
                                identity_key = self.core_engine.normalize_identity_key(name, path, hash_val)
                                
                                if identity_key not in identity_index:
                                    identity_index[identity_key] = {
                                        'name': name,
                                        'path': path,
                                        'hash': hash_val,
                                        'records': []
                                    }
                                    identity_feathers[identity_key] = set()
                                
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
                
                if feather_records > 0:
                    feathers_with_records.append(feather_id)
                    
                    if self.verbose_logging:
                        logger.info(f"  Loaded {feather_records} records from {feather_id}")
                    
            except Exception as e:
                if self.debug_mode:
                    print(f"[Identity Engine]   ✗ Error loading {feather_id}: {e}")
                logger.error(f"Error loading feather {feather_id}: {e}")
        
        # Show detailed extraction statistics
        print(f"\n[Identity Engine] 📊 Identity Extraction Summary:")
        print(f"  Total Records Processed: {total_records:,}")
        print(f"  Unique Identities Found: {len(identity_index):,}")
        
        print(f"\n[Identity Engine] 📁 Extraction Statistics by Feather:")
        for fid, stats in sorted(feather_stats.items(), key=lambda x: x[1]['total'], reverse=True):
            if stats['total'] == 0:
                continue
            success_rate = (stats['extracted'] / stats['total'] * 100) if stats['total'] > 0 else 0
            status_icon = "✓" if success_rate >= 90 else "+" if success_rate >= 50 else "!" if success_rate > 0 else "✗"
            unique_identities = len(stats['identities'])
            
            print(f"  {status_icon} {fid}")
            print(f"      Records: {stats['extracted']}/{stats['total']} extracted ({success_rate:.1f}%)")
            print(f"      Identities: {unique_identities} unique")
            
            # Show top 3 identities from this feather
            if unique_identities > 0:
                identity_counts = {}
                for identity_key in stats['identities']:
                    if identity_key in identity_index:
                        count = sum(1 for r in identity_index[identity_key]['records'] 
                                  if r.get('_feather_id') == fid)
                        identity_counts[identity_key] = count
                
                top_identities = sorted(identity_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                if top_identities:
                    top_names = []
                    for k, v in top_identities:
                        name = identity_index[k]['name'] or identity_index[k]['path'] or 'unknown'
                        if len(name) > 20:
                            name = name[:17] + "..."
                        top_names.append(f"{name} ({v})")
                    print(f"      Top: {', '.join(top_names)}")
        
        # Show cross-feather correlations
        print(f"\n[Identity Engine] 🔗 Cross-Feather Correlations:")
        multi_feather = [(k, v) for k, v in identity_feathers.items() if len(v) > 1]
        multi_feather.sort(key=lambda x: len(x[1]), reverse=True)
        
        if multi_feather:
            for identity_key, feather_set in multi_feather[:10]:
                name = identity_index[identity_key]['name'] or identity_index[identity_key]['path'] or 'unknown'
                if len(name) > 30:
                    name = name[:27] + "..."
                feather_names = [f.split('_')[0] for f in sorted(feather_set)]
                print(f"  {name}: Found in {len(feather_set)} feathers ({', '.join(feather_names)})")
        else:
            print(f"  No identities found across multiple feathers")
        
        print(f"\n[Identity Engine]   Correlating {len(identity_index):,} identities...")
        
        min_matches = 1  # Show ALL identities
        time_window_minutes = 180  # Time window for anchor clustering (default: 3 hours)
        
        # Diagnostic counters
        single_record_identities = 0
        single_feather_identities = 0
        multi_feather_identities = 0
        total_anchors = 0
        
        # Track progress
        total_identities = len(identity_index)
        processed_identities = 0
        last_printed_percent = -1
        
        for identity_key, identity_data in identity_index.items():
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
                identity_anchors = self._create_temporal_anchors(
                    records, 
                    identity_data, 
                    time_window_minutes,
                    feather_paths
                )
                
                # Handle streaming vs in-memory
                if streaming_enabled and streaming_writer:
                    # Apply scoring to each match before writing to database
                    for match in identity_anchors:
                        # Apply weighted scoring to this match
                        scored_match = self._apply_scoring_to_single_match(match, wing_config)
                        streaming_writer.write_match(result_id, scored_match)
                        match_count += 1
                else:
                    # Store in memory (old behavior)
                    matches.extend(identity_anchors)
                    match_count += len(identity_anchors)
                
                total_anchors += len(identity_anchors)
            
            # Update progress - print every 10%
            processed_identities += 1
            current_percent = int((processed_identities / total_identities) * 100)
            if current_percent % 10 == 0 and current_percent != last_printed_percent and current_percent > 0:
                print(f"[Identity Engine]   Progress: {current_percent}% ({processed_identities:,}/{total_identities:,})")
                last_printed_percent = current_percent
        
        # Flush any remaining matches in streaming mode
        if streaming_enabled and streaming_writer:
            print(f"[Identity Engine]   Flushing {match_count:,} matches to database...")
            streaming_writer.flush()
            
            # Update result record with final counts
            streaming_writer.update_result_counts(
                result_id=result_id,
                total_matches=match_count,
                feathers_processed=len(feathers_with_records),
                total_records_scanned=total_records
            )
            
            streaming_writer.close()
            print(f"[Identity Engine]   ✓ Saved {match_count:,} matches to database")
        
        # Show completion
        print(f"[Identity Engine]   ✓ Created {total_anchors:,} anchors")
        
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
        
        print(f"[Identity Engine] DEBUG: Returning {len(matches)} matches from _process_wing (streaming={streaming_enabled})")
        return matches, total_identities
    
    def _create_temporal_anchors(self, records: List[Dict[str, Any]], identity_data: Dict[str, Any],
                                time_window_minutes: int, feather_paths: Dict[str, str]) -> List[CorrelationMatch]:
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
                
                try:
                    # Try to parse timestamps as datetime objects
                    from dateutil import parser as date_parser
                    
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
                except ImportError:
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
                        feather_paths
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
                feather_paths
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
                feather_paths
            )
            if anchor_match:
                anchors.append(anchor_match)
        
        return anchors
    
    def _create_anchor_match(self, records: List[Dict[str, Any]], identity_data: Dict[str, Any],
                            start_time: str, end_time: str, feather_paths: Dict[str, str]) -> Optional[CorrelationMatch]:
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
        
        # Deduplicate records
        feather_records_dict = {}
        for record in records:
            fid = record.get('_feather_id', 'unknown')
            if fid not in feather_records_dict:
                feather_records_dict[fid] = []
            
            # Check if this record is a duplicate
            is_duplicate = False
            for existing_record in feather_records_dict[fid]:
                if self._are_records_identical(record, existing_record):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                feather_records_dict[fid].append(record)
        
        # Flatten for CorrelationMatch
        flattened_feather_records = {}
        for fid, record_list in feather_records_dict.items():
            if len(record_list) == 1:
                flattened_feather_records[fid] = record_list[0]
            else:
                for idx, record in enumerate(record_list):
                    key = f"{fid}_{idx}"
                    flattened_feather_records[key] = record
        
        # Get unique feathers
        feather_ids = list(set(r.get('_feather_id', '') for r in records))
        
        # Calculate time spread
        try:
            # Simple calculation - would be more sophisticated in production
            time_spread_seconds = 0
        except:
            time_spread_seconds = 0
        
        # Create match
        match = CorrelationMatch(
            match_id=str(uuid.uuid4()),
            timestamp=start_time,
            feather_records=flattened_feather_records,
            match_score=len(feather_ids) / len(feather_paths) if feather_paths else 0.5,
            feather_count=len(feather_ids),
            time_spread_seconds=time_spread_seconds,
            anchor_feather_id=feather_ids[0] if feather_ids else '',
            anchor_artifact_type='Identity',
            matched_application=identity_data['name'],
            matched_file_path=identity_data['path']
        )
        
        # Add anchor metadata
        match.anchor_start_time = start_time
        match.anchor_end_time = end_time
        match.anchor_record_count = len(records)
        
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
    
    def _apply_semantic_mappings(self, 
                               matches: List[CorrelationMatch], 
                               wing_configs: List[Any]) -> List[CorrelationMatch]:
        """
        Apply semantic mappings to correlation matches.
        
        Args:
            matches: List of correlation matches
            wing_configs: Wing configurations for context
            
        Returns:
            Enhanced matches with semantic mapping information
        """
        if not self.semantic_integration.is_enabled():
            if self.verbose_logging:
                logger.info("Semantic mapping is disabled, skipping mapping application")
            return matches
        
        if self.verbose_logging:
            logger.info(f"Applying semantic mappings to {len(matches)} correlation matches")
        enhanced_matches = []
        
        for i, match in enumerate(matches):
            # Log progress for large datasets (only if verbose)
            if self.verbose_logging and len(matches) > 100 and i % 50 == 0:
                logger.info(f"Processing semantic mappings: {i}/{len(matches)} matches completed")
            
            # Convert match feather_records to format expected by semantic integration
            records_list = [record for record in match.feather_records.values()]
            
            # Apply semantic mappings
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
            
            # Create enhanced match with updated feather_records
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
                semantic_data={'semantic_mappings_applied': True}
            )
            
            enhanced_matches.append(enhanced_match)
        
        # Log completion with statistics (only if verbose)
        if self.verbose_logging:
            semantic_stats = self.semantic_integration.get_mapping_statistics()
            logger.info(f"Semantic mapping application completed:")
            logger.info(f"  Matches processed: {len(matches)}")
            logger.info(f"  Mappings applied: {semantic_stats.mappings_applied}")
            logger.info(f"  Pattern matches: {semantic_stats.pattern_matches}")
            logger.info(f"  Exact matches: {semantic_stats.exact_matches}")
        
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
        Apply semantic mapping and weighted scoring to a single match.
        Used in streaming mode to score matches before writing to database.
        
        Args:
            match: Correlation match to process
            wing_config: Wing configuration for context
            
        Returns:
            Match with scoring and semantic data applied
        """
        try:
            case_id = getattr(self.config, 'case_id', None)
            
            # Apply semantic mapping if enabled
            semantic_data = None
            if self.semantic_integration.is_enabled():
                try:
                    records_list = [record for record in match.feather_records.values()]
                    enhanced_records = self.semantic_integration.apply_to_correlation_results(
                        records_list,
                        wing_id=getattr(wing_config, 'wing_id', None),
                        pipeline_id=None,
                        artifact_type=match.anchor_artifact_type
                    )
                    semantic_data = {'semantic_mappings_applied': True}
                except Exception as e:
                    if self.verbose_logging:
                        logger.warning(f"Semantic mapping failed for match {match.match_id}: {e}")
                    semantic_data = {'semantic_mappings_applied': False, 'error': str(e)}
            
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
                    if self.verbose_logging:
                        logger.warning(f"Weighted scoring failed for match {match.match_id}: {e}")
                    # Fall back to simple scoring
                    weighted_score = self._calculate_simple_score(match, wing_config)
            else:
                # Use simple scoring
                weighted_score = self._calculate_simple_score(match, wing_config)
            
            # Create scored match
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
            if self.verbose_logging:
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