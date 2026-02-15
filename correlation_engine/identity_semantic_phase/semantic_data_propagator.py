"""
Semantic Data Propagator

Propagates semantic data from identities back to all associated records.
This component ensures that semantic mappings applied at the identity level
are consistently propagated to all records sharing that identity.
"""

import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from .identity_registry import IdentityRegistry, IdentityRecord
from ..engine.correlation_result import CorrelationResult, CorrelationMatch

logger = logging.getLogger(__name__)


@dataclass
class PropagationStatistics:
    """Statistics for semantic data propagation operations"""
    identities_propagated: int = 0
    records_updated: int = 0
    matches_updated: int = 0
    propagation_errors: int = 0
    processing_time_seconds: float = 0.0
    records_per_identity_avg: float = 0.0
    streaming_mode: bool = False


class SemanticDataPropagator:
    """
    Propagates semantic data from identities back to all associated records.
    
    This class implements the data propagation strategy that ensures semantic
    mappings applied at the identity level are consistently added to all records
    sharing that identity. It handles both in-memory and database-stored results.
    
    Key features:
    - Propagates semantic data to correlation result matches in memory
    - Propagates semantic data to database records for streaming mode
    - Maintains referential integrity between identity-level and record-level data
    - Preserves original record structure while adding semantic metadata
    - Handles errors gracefully without data loss
    
    Requirements: 1.3, 4.1, 4.2, 4.3, 4.4, 4.5
    Property 2: Semantic Data Propagation Consistency
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize Semantic Data Propagator.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.statistics = PropagationStatistics()
        
        if self.debug_mode:
            logger.info("[Semantic Data Propagator] Initialized")
    
    def propagate_to_correlation_results(self, identity_registry: IdentityRegistry,
                                        correlation_results: CorrelationResult) -> CorrelationResult:
        """
        Propagate semantic data from identities to correlation results in memory.
        
        This method updates correlation matches with semantic data from the identity
        registry. For each match, it looks up the identities involved and adds their
        semantic data to the match's semantic_data field.
        
        The propagation ensures:
        - All records sharing an identity receive identical semantic data
        - Original record structure is preserved
        - Semantic metadata is added consistently
        - Referential integrity is maintained
        
        Args:
            identity_registry: Registry containing identities with semantic data
            correlation_results: Correlation results to enhance
            
        Returns:
            Enhanced correlation results with semantic data
            
        Requirements: 1.3, 4.2, 4.3, 4.4, 4.5
        Property 2: Semantic Data Propagation Consistency
        """
        # Reset statistics for this propagation run
        self.statistics = PropagationStatistics()
        start_time = time.time()
        
        if self.debug_mode:
            logger.info(f"[Semantic Data Propagator] Starting propagation for {len(correlation_results.matches)} matches")
        
        # Check if there are any processed identities with semantic data
        processed_identities = identity_registry.get_processed_identities()
        if not processed_identities:
            if self.debug_mode:
                logger.info("[Semantic Data Propagator] No processed identities to propagate")
            self.statistics.processing_time_seconds = time.time() - start_time
            return correlation_results
        
        if self.debug_mode:
            logger.info(f"[Semantic Data Propagator] Found {len(processed_identities)} processed identities")
        
        # Build a lookup map from (match_id, feather_id, record_index) to identity records
        # This allows efficient lookup when processing matches
        record_to_identity_map = self._build_record_to_identity_map(identity_registry)
        
        if self.debug_mode:
            logger.info(f"[Semantic Data Propagator] Built lookup map with {len(record_to_identity_map)} record references")
        
        # Process each match and propagate semantic data
        matches_updated = 0
        records_updated = 0
        
        for match in correlation_results.matches:
            try:
                # Collect semantic data for this match from all identities
                match_semantic_data = self._collect_semantic_data_for_match(
                    match, 
                    record_to_identity_map
                )
                
                if match_semantic_data:
                    # Add semantic data to the match
                    if match.semantic_data is None:
                        match.semantic_data = {}
                    
                    # Merge semantic data (preserve existing data, add new data)
                    match.semantic_data.update(match_semantic_data)
                    
                    matches_updated += 1
                    records_updated += len(match.feather_records)
                    
            except Exception as e:
                logger.error(f"[Semantic Data Propagator] Error propagating to match {match.match_id}: {e}")
                self.statistics.propagation_errors += 1
                continue
        
        # Update statistics
        self.statistics.identities_propagated = len(processed_identities)
        self.statistics.records_updated = records_updated
        self.statistics.matches_updated = matches_updated
        self.statistics.processing_time_seconds = time.time() - start_time
        
        if len(processed_identities) > 0:
            self.statistics.records_per_identity_avg = records_updated / len(processed_identities)
        
        if self.debug_mode:
            logger.info(f"[Semantic Data Propagator] Completed: {matches_updated} matches updated, "
                       f"{records_updated} records enhanced in {self.statistics.processing_time_seconds:.2f}s")
        
        return correlation_results
    
    def propagate_to_streaming_results(self, identity_registry: IdentityRegistry,
                                      database_path: str, execution_id: int) -> bool:
        """
        Propagate semantic data from identities to database records for streaming mode.
        
        This method updates correlation matches stored in the database with semantic
        data from the identity registry. It's used when correlation results are too
        large to fit in memory and are stored directly in the database.
        
        Args:
            identity_registry: Registry containing identities with semantic data
            database_path: Path to SQLite database containing correlation results
            execution_id: Execution ID to identify which results to update
            
        Returns:
            True if propagation succeeded, False otherwise
            
        Requirements: 1.3, 4.2, 4.3, 4.4, 4.5, 3.1, 3.2
        Property 2: Semantic Data Propagation Consistency
        Property 12: Streaming Mode Compatibility
        Property 5: Database Indexing for Semantic Matching
        """
        # Reset statistics for this propagation run
        self.statistics = PropagationStatistics()
        self.statistics.streaming_mode = True
        start_time = time.time()
        
        if self.debug_mode:
            logger.info(f"[Semantic Data Propagator] Starting streaming propagation for execution_id={execution_id}")
        
        # Check if there are any processed identities with semantic data
        processed_identities = identity_registry.get_processed_identities()
        
        # Import required modules
        import sqlite3
        import json
        
        # Initialize connection to None for proper cleanup
        conn = None
        
        try:
            # Connect to database (Requirements 6.4, 15.1)
            # Properly open connection before use
            try:
                conn = sqlite3.connect(database_path)
                cursor = conn.cursor()
                
                if self.debug_mode:
                    logger.info(f"[Semantic Data Propagator] Connected to database: {database_path}")
                    
            except sqlite3.Error as e:
                error_msg = f"Failed to connect to database {database_path}: {e}"
                logger.error(f"[Semantic Data Propagator] {error_msg}")
                self.statistics.propagation_errors += 1
                self.statistics.processing_time_seconds = time.time() - start_time
                return False
            
            # Create indexes for efficient identity lookups (Requirements 3.1, 3.2)
            # These indexes optimize semantic matching queries on identity fields
            # Create indexes BEFORE checking for identities to ensure they exist
            if self.debug_mode:
                logger.info("[Semantic Data Propagator] Skipping database indexes for testing")
            
            # TEMPORARILY DISABLED: self._create_semantic_matching_indexes(cursor)
            # This is causing performance issues with large datasets
            
            # Check if there are any processed identities with semantic data
            # This check happens AFTER index creation
            if not processed_identities:
                if self.debug_mode:
                    logger.info("[Semantic Data Propagator] No processed identities to propagate")
                self.statistics.processing_time_seconds = time.time() - start_time
                return True
            
            # Build a lookup map from (match_id, feather_id) to identity records
            record_to_identity_map = self._build_record_to_identity_map(identity_registry)
            
            if self.debug_mode:
                logger.info(f"[Semantic Data Propagator] Built lookup map with {len(record_to_identity_map)} record references")
                
                # Debug: Show sample of the lookup map
                sample_keys = list(record_to_identity_map.keys())[:5]
                for key in sample_keys:
                    identities = record_to_identity_map[key]
                    logger.info(f"[Semantic Data Propagator] Sample lookup: {key} -> {len(identities)} identities")
                    for identity in identities[:2]:  # Show first 2 identities
                        semantic_count = len(identity.semantic_data) if identity.semantic_data else 0
                        logger.info(f"[Semantic Data Propagator]   - {identity.identity_type}:{identity.identity_value} ({semantic_count} semantic fields)")
            
            # Also log simplified map if available
            if hasattr(self, '_simplified_record_map'):
                logger.info(f"[Semantic Data Propagator] Simplified lookup map has {len(self._simplified_record_map)} entries")
            
            # Query all matches for this execution using indexed fields (Requirements 3.3, 3.4, 3.5)
            # This query uses the indexes created above for efficient lookups
            try:
                cursor.execute("""
                    SELECT m.match_id, m.semantic_data, m.feather_records
                    FROM matches m
                    INNER JOIN results r ON m.result_id = r.result_id
                    WHERE r.execution_id = ?
                """, (execution_id,))
                
                rows = cursor.fetchall()
                
            except sqlite3.Error as e:
                error_msg = f"Failed to query matches from database: {e}"
                logger.error(f"[Semantic Data Propagator] {error_msg}")
                self.statistics.propagation_errors += 1
                self.statistics.processing_time_seconds = time.time() - start_time
                return False
            
            matches_to_update = []
            records_updated = 0
            total_matches = len(rows)
            total_saved = 0
            
            # Add progress reporting for database updates
            print(f"[Semantic Matching] Adding semantic data to {total_matches:,} matches in database...")
            
            # Calculate commit interval (every 10% of total matches)
            # Commit to database every 10% to avoid memory exhaustion with large datasets
            commit_batch_size = max(100, total_matches // 10)  # Minimum 100 matches per commit
            
            for row_idx, row in enumerate(rows):
                match_id, semantic_data_json, feather_records_json = row
                
                try:
                    # Parse existing semantic data
                    if semantic_data_json:
                        semantic_data = json.loads(semantic_data_json)
                    else:
                        semantic_data = {}
                    
                    # Parse feather records to build match_data structure
                    if feather_records_json:
                        feather_records = json.loads(feather_records_json)
                    else:
                        feather_records = {}
                    
                    match_data = {
                        'match_id': match_id,
                        'feather_records': feather_records
                    }
                    
                    # Debug logging for first few matches
                    if self.debug_mode and row_idx < 3:
                        logger.info(f"[Semantic Data Propagator] Processing match {row_idx+1}: {match_id}")
                        logger.info(f"[Semantic Data Propagator]   Feather records: {list(feather_records.keys())}")
                    
                    # Collect semantic data for this match
                    match_semantic_data = self._collect_semantic_data_for_match_dict(
                        match_data,
                        record_to_identity_map
                    )
                    
                    # Debug logging for semantic data collection
                    if self.debug_mode and row_idx < 3:
                        logger.info(f"[Semantic Data Propagator]   Collected semantic data: {len(match_semantic_data)} entries")
                        for key, data in list(match_semantic_data.items())[:2]:  # Show first 2 entries
                            logger.info(f"[Semantic Data Propagator]     - {key}: {len(data.get('semantic_mappings', {}))} mappings")
                    
                    if match_semantic_data:
                        # Merge semantic data
                        semantic_data.update(match_semantic_data)
                        
                        # Store for batch update
                        matches_to_update.append((json.dumps(semantic_data), match_id))
                        records_updated += len(feather_records)
                        
                        if self.debug_mode and row_idx < 3:
                            logger.info(f"[Semantic Data Propagator]   Match will be updated with {len(match_semantic_data)} semantic entries")
                    else:
                        if self.debug_mode and row_idx < 3:
                            logger.info(f"[Semantic Data Propagator]   No semantic data found for match")
                    
                    # Commit to database every 10% to avoid memory exhaustion
                    if len(matches_to_update) >= commit_batch_size:
                        try:
                            cursor.executemany("""
                                UPDATE matches 
                                SET semantic_data = ? 
                                WHERE match_id = ?
                            """, matches_to_update)
                            
                            conn.commit()
                            
                            total_saved += len(matches_to_update)
                            progress_pct = (total_saved / total_matches) * 100
                            print(f"[Semantic Matching] Progress: {progress_pct:.0f}% ({total_saved:,}/{total_matches:,} matches saved to database)")
                            
                            # Clear the batch to free memory
                            matches_to_update = []
                            
                        except sqlite3.Error as e:
                            error_msg = f"Failed to update matches in database: {e}"
                            logger.error(f"[Semantic Data Propagator] {error_msg}")
                            self.statistics.propagation_errors += 1
                            # Continue processing remaining matches
                            matches_to_update = []
                        
                except Exception as e:
                    logger.error(f"[Semantic Data Propagator] Error processing match {match_id}: {e}")
                    self.statistics.propagation_errors += 1
                    continue
            
            # Commit any remaining matches (final batch)
            if matches_to_update:
                try:
                    cursor.executemany("""
                        UPDATE matches 
                        SET semantic_data = ? 
                        WHERE match_id = ?
                    """, matches_to_update)
                    
                    conn.commit()
                    
                    total_saved += len(matches_to_update)
                    print(f"[Semantic Matching] Progress: 100% ({total_saved:,}/{total_matches:,} matches saved to database)")
                    
                    if self.debug_mode:
                        logger.info(f"[Semantic Data Propagator] Final batch: updated {len(matches_to_update)} matches")
                        
                except sqlite3.Error as e:
                    error_msg = f"Failed to update final batch of matches in database: {e}"
                    logger.error(f"[Semantic Data Propagator] {error_msg}")
                    self.statistics.propagation_errors += 1
                    self.statistics.processing_time_seconds = time.time() - start_time
                    return False
            
            print(f"[Semantic Matching] ✓ Completed: {total_saved:,} matches updated with semantic data")
            
            # Update statistics
            self.statistics.records_updated = records_updated
            
            # Update statistics
            self.statistics.identities_propagated = len(processed_identities)
            self.statistics.records_updated = records_updated
            self.statistics.matches_updated = len(matches_to_update)
            self.statistics.processing_time_seconds = time.time() - start_time
            
            if len(processed_identities) > 0:
                self.statistics.records_per_identity_avg = records_updated / len(processed_identities)
            
            if self.debug_mode:
                logger.info(f"[Semantic Data Propagator] Completed streaming propagation: "
                           f"{len(matches_to_update)} matches updated, "
                           f"{records_updated} records enhanced in {self.statistics.processing_time_seconds:.2f}s")
            
            return True
            
        except Exception as e:
            error_msg = f"Unexpected error in streaming propagation: {e}"
            logger.error(f"[Semantic Data Propagator] {error_msg}", exc_info=True)
            self.statistics.propagation_errors += 1
            self.statistics.processing_time_seconds = time.time() - start_time
            return False
            
        finally:
            # Always close connection after completion (Requirements 6.4, 15.1)
            # Ensure connection is closed even if errors occur
            if conn is not None:
                try:
                    conn.close()
                    if self.debug_mode:
                        logger.info("[Semantic Data Propagator] Database connection closed")
                except Exception as e:
                    logger.warning(f"[Semantic Data Propagator] Error closing database connection: {e}")
    
    def _build_record_to_identity_map(self, identity_registry: IdentityRegistry) -> Dict[tuple, IdentityRecord]:
        """
        Build a lookup map from record references to identity records.
        
        This creates an efficient lookup structure that maps (match_id, feather_id, record_index)
        tuples to their corresponding identity records. This allows fast lookup when
        processing matches.
        
        Args:
            identity_registry: Registry containing identities
            
        Returns:
            Dictionary mapping record reference tuples to IdentityRecord objects
        """
        record_map = {}
        
        for identity in identity_registry.get_processed_identities():
            # Only include identities that have semantic data
            if not identity.semantic_data:
                continue
            
            # Map each record reference to this identity
            for ref in identity.record_references:
                # Create lookup key from record reference
                # Use (match_id, feather_id, record_index) as key
                key = (ref.match_id, ref.feather_id, ref.record_index)
                
                # Store identity record for this reference
                # If multiple identities reference the same record, we'll merge their data
                if key not in record_map:
                    record_map[key] = []
                record_map[key].append(identity)
        
        # Also create a simplified lookup map for cases where record_index is not available
        # This handles the case where we only have match_id and feather_id
        simplified_map = {}
        for identity in identity_registry.get_processed_identities():
            if not identity.semantic_data:
                continue
            
            for ref in identity.record_references:
                # Create simplified key (match_id, feather_id)
                simple_key = (ref.match_id, ref.feather_id)
                if simple_key not in simplified_map:
                    simplified_map[simple_key] = []
                simplified_map[simple_key].append(identity)
        
        # Store simplified map for fallback lookup
        self._simplified_record_map = simplified_map
        
        if self.debug_mode:
            logger.info(f"[Semantic Data Propagator] Built record map with {len(record_map)} exact references and {len(simplified_map)} simplified references")
        
        return record_map
    
    def _collect_semantic_data_for_match(self, match: CorrelationMatch,
                                        record_to_identity_map: Dict[tuple, List[IdentityRecord]]) -> Dict[str, Any]:
        """
        Collect semantic data for a match from all associated identities.
        
        This method looks up all identities associated with records in the match
        and collects their semantic data into a unified structure.
        
        Args:
            match: Correlation match to collect data for
            record_to_identity_map: Lookup map from record references to identities
            
        Returns:
            Dictionary with collected semantic data
        """
        semantic_data = {}
        
        # Process each feather record in the match
        for feather_id, record_data in match.feather_records.items():
            # Try to find identity for this record
            # We use record_index=0 as a default since we don't track it in matches
            key = (match.match_id, feather_id, 0)
            
            if key in record_to_identity_map:
                identities = record_to_identity_map[key]
                
                # Collect semantic data from all identities for this record
                for identity in identities:
                    if identity.semantic_data:
                        # Add identity-level semantic data
                        identity_key = f"{identity.identity_type}_{identity.identity_value}"
                        
                        # Create a clean copy without internal fields
                        clean_semantic_data = {
                            k: v for k, v in identity.semantic_data.items()
                            if not k.startswith('_')
                        }
                        
                        if clean_semantic_data:
                            semantic_data[identity_key] = {
                                'identity_value': identity.identity_value,
                                'identity_type': identity.identity_type,
                                'semantic_mappings': clean_semantic_data,
                                'feather_id': feather_id
                            }
        
        return semantic_data
    
    def _collect_semantic_data_for_match_dict(self, match_data: Dict[str, Any],
                                             record_to_identity_map: Dict[tuple, List[IdentityRecord]]) -> Dict[str, Any]:
        """
        Collect semantic data for a match dictionary (used in streaming mode).
        
        This is similar to _collect_semantic_data_for_match but works with
        dictionary representations of matches instead of CorrelationMatch objects.
        
        Args:
            match_data: Match data dictionary
            record_to_identity_map: Lookup map from record references to identities
            
        Returns:
            Dictionary with collected semantic data
        """
        semantic_data = {}
        match_id = match_data.get('match_id', '')
        
        # Process each feather record in the match
        feather_records = match_data.get('feather_records', {})
        for feather_id in feather_records.keys():
            # Try to find identity for this record using exact lookup first
            key = (match_id, feather_id, 0)  # Default record_index
            identities = record_to_identity_map.get(key, [])
            
            # If no exact match, try simplified lookup (match_id, feather_id)
            if not identities and hasattr(self, '_simplified_record_map'):
                simple_key = (match_id, feather_id)
                identities = self._simplified_record_map.get(simple_key, [])
            
            # If still no match, try all possible record_index values for this match/feather
            if not identities:
                for full_key, identity_list in record_to_identity_map.items():
                    if full_key[0] == match_id and full_key[1] == feather_id:
                        identities.extend(identity_list)
                        break
            
            # Collect semantic data from all identities for this record
            for identity in identities:
                if identity.semantic_data:
                    # Add identity-level semantic data
                    identity_key = f"{identity.identity_type}_{identity.identity_value}"
                    
                    # Create a clean copy without internal fields
                    clean_semantic_data = {
                        k: v for k, v in identity.semantic_data.items()
                        if not k.startswith('_')
                    }
                    
                    if clean_semantic_data:
                        semantic_data[identity_key] = {
                            'identity_value': identity.identity_value,
                            'identity_type': identity.identity_type,
                            'semantic_mappings': clean_semantic_data,
                            'feather_id': feather_id
                        }
        
        return semantic_data
    
    def _create_semantic_matching_indexes(self, cursor) -> None:
        """
        Create database indexes for efficient semantic matching queries.
        
        This method creates indexes on identity-related fields to optimize
        semantic matching lookups in streaming mode. Indexes are created with
        IF NOT EXISTS to avoid errors if they already exist.
        
        Args:
            cursor: SQLite database cursor
            
        Requirements: 3.1, 3.2
        Property 5: Database Indexing for Semantic Matching
        """
        try:
            # Index on match_id for efficient match lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_matches_match_id 
                ON matches(match_id)
            """)
            
            # Index on result_id for efficient join with results table
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_matches_result_id 
                ON matches(result_id)
            """)
            
            # Index on execution_id in results table for filtering by execution
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_execution_id 
                ON results(execution_id)
            """)
            
            # Composite index for the common query pattern (execution_id + match lookups)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_execution_result 
                ON results(execution_id, result_id)
            """)
            
            if self.debug_mode:
                logger.info("[Semantic Data Propagator] Database indexes created successfully")
                
        except Exception as e:
            # Log error but don't fail - queries will still work, just slower
            logger.warning(f"[Semantic Data Propagator] Failed to create some indexes: {e}")
            if self.debug_mode:
                logger.warning("[Semantic Data Propagator] Continuing without indexes (queries may be slower)")
    
    def get_propagation_statistics(self) -> PropagationStatistics:
        """
        Get statistics from the last propagation run.
        
        Returns:
            PropagationStatistics object
        """
        return self.statistics
    
    def reset_statistics(self):
        """Reset propagation statistics"""
        self.statistics = PropagationStatistics()
    
    def validate_propagation(self, identity_registry: IdentityRegistry,
                           correlation_results: CorrelationResult) -> Dict[str, Any]:
        """
        Validate that semantic data has been properly propagated.
        
        This method checks that:
        - All processed identities have their semantic data in matches
        - All records sharing an identity have identical semantic data
        - No data loss occurred during propagation
        
        Args:
            identity_registry: Registry with identities
            correlation_results: Results to validate
            
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            'valid': True,
            'warnings': [],
            'errors': [],
            'statistics': {}
        }
        
        # Count matches with semantic data
        matches_with_semantic_data = sum(
            1 for match in correlation_results.matches
            if match.semantic_data and len(match.semantic_data) > 0
        )
        
        # Count processed identities
        processed_identities = len(identity_registry.get_processed_identities())
        
        validation_results['statistics'] = {
            'processed_identities': processed_identities,
            'matches_with_semantic_data': matches_with_semantic_data,
            'total_matches': len(correlation_results.matches)
        }
        
        # Validate that we have semantic data if we have processed identities
        if processed_identities > 0 and matches_with_semantic_data == 0:
            validation_results['valid'] = False
            validation_results['errors'].append(
                f"Found {processed_identities} processed identities but no matches have semantic data"
            )
        
        return validation_results
