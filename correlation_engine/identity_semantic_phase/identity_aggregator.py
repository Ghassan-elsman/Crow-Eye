"""
Identity Aggregator

Aggregates unique identities from correlation results regardless of engine type.
Supports Identity-Based, Time-Based, and streaming mode aggregation.

Note: This is different from the IdentityExtractor in the correlation engines,
which normalizes and extracts identities during correlation processing.
This component aggregates already-extracted identities from final results.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field

from .identity_registry import IdentityRegistry, IdentityRecord, RecordReference

logger = logging.getLogger(__name__)


@dataclass
class AggregationStatistics:
    """Statistics for identity aggregation operations"""
    total_identities_found: int = 0
    identities_successfully_aggregated: int = 0
    aggregation_errors: int = 0
    malformed_results_encountered: int = 0
    skipped_identities: int = 0
    error_details: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class IdentityAggregator:
    """
    Aggregates unique identities from correlation results.
    
    Supports multiple engine types:
    - Identity-Based Engine: Aggregates from identity index
    - Time-Based Engine: Aggregates from correlation matches
    - Streaming Mode: Aggregates from database-stored results
    
    Requirements: 8.1, 8.2, 8.3, 10.1, 10.2
    Property 5: Engine-Specific Identity Extraction
    Property 7: Error Handling and Graceful Degradation
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize Identity Aggregator.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.statistics = AggregationStatistics()
        
        if self.debug_mode:
            logger.info("[Identity Aggregator] Initialized")
    
    
    def _validate_correlation_results(self, results, engine_type: str) -> Tuple[bool, str, List[str]]:
        """
        Validate correlation results structure before processing.
        
        This method checks for common issues with malformed correlation results:
        - Missing required attributes
        - None/null values where objects are expected
        - Empty or invalid data structures
        
        Args:
            results: Correlation results to validate
            engine_type: Expected engine type
            
        Returns:
            Tuple of (is_valid, error_message, warnings_list)
            
        Requirements: 7.1, 7.2, 7.3
        Property 7: Error Handling and Graceful Degradation
        """
        warnings = []
        
        # Check if results is None
        if results is None:
            return (False, "Correlation results is None", warnings)
        
        # Check for identity-based engine requirements
        if engine_type.lower() in ["identity_based", "identity-based", "identity"]:
            if not hasattr(results, 'identities'):
                return (False, "Identity-based results missing 'identities' attribute", warnings)
            
            identities = getattr(results, 'identities', None)
            if identities is None:
                warnings.append("Identities attribute is None, will return empty registry")
                return (True, "", warnings)
            
            if not isinstance(identities, (list, tuple)):
                return (False, f"Identities attribute has invalid type: {type(identities)}", warnings)
        
        # Check for time-based engine requirements
        elif engine_type.lower() in ["time_based", "time-based", "time"]:
            if not hasattr(results, 'matches'):
                return (False, "Time-based results missing 'matches' attribute", warnings)
            
            matches = getattr(results, 'matches', None)
            if matches is None:
                warnings.append("Matches attribute is None, will return empty registry")
                return (True, "", warnings)
            
            if not isinstance(matches, (list, tuple)):
                return (False, f"Matches attribute has invalid type: {type(matches)}", warnings)
        
        # Validation passed
        return (True, "", warnings)
    
    def extract_identities(self, correlation_results, engine_type: str) -> IdentityRegistry:
        """
        Aggregate identities from correlation results based on engine type.
        
        This method handles malformed correlation results gracefully by:
        - Validating correlation results structure before processing
        - Continuing with available identities when errors occur
        - Logging detailed error information for debugging
        - Returning a valid registry even if some identities fail
        
        Args:
            correlation_results: Correlation results object
            engine_type: Type of engine ("identity_based" or "time_based")
            
        Returns:
            IdentityRegistry with aggregated identities (may be partial if errors occurred)
            
        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3
        Property 5: Engine-Specific Identity Extraction
        Property 7: Error Handling and Graceful Degradation
        """
        # Reset statistics for this extraction
        self.statistics = AggregationStatistics()
        
        if self.debug_mode:
            logger.info(f"[Identity Aggregator] Aggregating identities for {engine_type} engine")
        
        # Validate correlation results before processing
        validation_result = self._validate_correlation_results(correlation_results, engine_type)
        
        if not validation_result[0]:
            # Validation failed - log error and return empty registry
            error_msg = f"Correlation results validation failed: {validation_result[1]}"
            logger.error(f"[Identity Aggregator] {error_msg}")
            self.statistics.error_details.append(error_msg)
            self.statistics.malformed_results_encountered += 1
            
            # Return empty registry but don't crash
            return IdentityRegistry()
        
        # Log any validation warnings
        if validation_result[2]:
            for warning in validation_result[2]:
                logger.warning(f"[Identity Aggregator] Validation warning: {warning}")
                self.statistics.warnings.append(warning)
        
        try:
            # Check if streaming mode - extract from database instead of memory
            if hasattr(correlation_results, 'streaming_mode') and correlation_results.streaming_mode:
                if hasattr(correlation_results, 'database_path') and hasattr(correlation_results, 'execution_id'):
                    if correlation_results.database_path and correlation_results.execution_id is not None:
                        if self.debug_mode:
                            logger.info(f"[Identity Aggregator] Streaming mode detected - extracting from database: {correlation_results.database_path}")
                        registry = self.extract_from_streaming_results(
                            correlation_results.database_path,
                            correlation_results.execution_id
                        )
                        return registry
                    else:
                        error_msg = "Streaming mode enabled but database_path or execution_id is missing"
                        logger.error(f"[Identity Aggregator] {error_msg}")
                        self.statistics.error_details.append(error_msg)
                        return IdentityRegistry()
                else:
                    warning_msg = "Streaming mode enabled but database_path/execution_id attributes missing"
                    logger.warning(f"[Identity Aggregator] {warning_msg}")
                    self.statistics.warnings.append(warning_msg)
                    # Fall through to normal extraction
            
            # Determine aggregation method based on engine type
            if engine_type.lower() in ["identity_based", "identity-based", "identity"]:
                registry = self.extract_from_identity_engine(correlation_results)
            elif engine_type.lower() in ["time_based", "time-based", "time"]:
                registry = self.extract_from_time_based_engine(correlation_results)
            else:
                warning_msg = f"Unknown engine type: {engine_type}, attempting time-based aggregation"
                logger.warning(f"[Identity Aggregator] {warning_msg}")
                self.statistics.warnings.append(warning_msg)
                registry = self.extract_from_time_based_engine(correlation_results)
            
            # Log aggregation summary
            if self.debug_mode or self.statistics.aggregation_errors > 0:
                logger.info(
                    f"[Identity Aggregator] Aggregation complete: "
                    f"{self.statistics.identities_successfully_aggregated} identities aggregated, "
                    f"{self.statistics.aggregation_errors} errors, "
                    f"{self.statistics.skipped_identities} skipped"
                )
            
            # Log detailed errors if any occurred
            if self.statistics.aggregation_errors > 0:
                logger.warning(
                    f"[Identity Aggregator] Encountered {self.statistics.aggregation_errors} errors during aggregation. "
                    f"Continuing with {self.statistics.identities_successfully_aggregated} available identities."
                )
                
                # Log first few error details for debugging
                for error_detail in self.statistics.error_details[:5]:
                    logger.debug(f"[Identity Aggregator] Error detail: {error_detail}")
                
                if len(self.statistics.error_details) > 5:
                    logger.debug(
                        f"[Identity Aggregator] ... and {len(self.statistics.error_details) - 5} more errors"
                    )
            
            return registry
            
        except Exception as e:
            # Catch any unexpected errors and return empty registry
            error_msg = f"Unexpected error during identity aggregation: {e}"
            logger.error(f"[Identity Aggregator] {error_msg}", exc_info=True)
            self.statistics.error_details.append(error_msg)
            self.statistics.malformed_results_encountered += 1
            
            # Return empty registry but don't crash
            return IdentityRegistry()
    
    def extract_identities_from_multiple_results(self, 
                                                 correlation_results_list: List[Any], 
                                                 engine_type: str) -> IdentityRegistry:
        """
        Aggregate identities from multiple correlation results (multi-wing scenario).
        
        This method consolidates identities from different wing configurations into
        a single registry, maintaining wing context for each identity.
        
        Handles errors gracefully by:
        - Processing each result independently
        - Continuing with remaining results if one fails
        - Logging detailed error information
        - Tracking which wing each identity came from
        
        Args:
            correlation_results_list: List of CorrelationResult objects from different wings
            engine_type: Type of engine ("identity_based" or "time_based")
            
        Returns:
            IdentityRegistry with aggregated identities from all wings
            
        Requirements: 10.5
        Property 13: Multi-Wing Scenario Support
        Property 7: Error Handling and Graceful Degradation
        """
        # Reset statistics for this extraction
        self.statistics = AggregationStatistics()
        
        if self.debug_mode:
            logger.info(
                f"[Identity Aggregator] Aggregating identities from {len(correlation_results_list)} wings "
                f"for {engine_type} engine"
            )
        
        # Create consolidated registry
        consolidated_registry = IdentityRegistry()
        
        # Track per-wing statistics
        wings_processed = 0
        wings_failed = 0
        
        # Process each wing's correlation results
        for idx, correlation_results in enumerate(correlation_results_list):
            try:
                # Validate correlation results
                validation_result = self._validate_correlation_results(correlation_results, engine_type)
                
                if not validation_result[0]:
                    # Validation failed - log error and continue with next wing
                    error_msg = f"Wing {idx} validation failed: {validation_result[1]}"
                    logger.error(f"[Identity Aggregator] {error_msg}")
                    self.statistics.error_details.append(error_msg)
                    self.statistics.malformed_results_encountered += 1
                    wings_failed += 1
                    continue
                
                # Log any validation warnings
                if validation_result[2]:
                    for warning in validation_result[2]:
                        logger.warning(f"[Identity Aggregator] Wing {idx} warning: {warning}")
                        self.statistics.warnings.append(f"Wing {idx}: {warning}")
                
                # Extract wing context
                wing_id = getattr(correlation_results, 'wing_id', f'wing_{idx}')
                wing_name = getattr(correlation_results, 'wing_name', f'Wing {idx}')
                
                if self.debug_mode:
                    logger.info(f"[Identity Aggregator] Processing wing: {wing_name} ({wing_id})")
                
                # Extract identities from this wing
                wing_registry = self._extract_identities_with_wing_context(
                    correlation_results, 
                    engine_type,
                    wing_id,
                    wing_name
                )
                
                # Merge into consolidated registry
                self._merge_registries(consolidated_registry, wing_registry)
                
                wings_processed += 1
                
                if self.debug_mode:
                    logger.info(
                        f"[Identity Aggregator] Wing {wing_name}: "
                        f"{wing_registry.get_unique_identity_count()} unique identities"
                    )
                
            except Exception as e:
                # Handle unexpected errors gracefully
                wing_id = getattr(correlation_results, 'wing_id', f'wing_{idx}') if correlation_results else f'wing_{idx}'
                error_msg = f"Error processing wing {wing_id}: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}", exc_info=True)
                self.statistics.error_details.append(error_msg)
                self.statistics.aggregation_errors += 1
                wings_failed += 1
                continue
        
        # Update statistics
        self.statistics.identities_successfully_aggregated = consolidated_registry.get_unique_identity_count()
        self.statistics.total_identities_found = consolidated_registry.get_unique_identity_count()
        
        # Log multi-wing aggregation summary
        if self.debug_mode or wings_failed > 0:
            logger.info(
                f"[Identity Aggregator] Multi-wing aggregation complete: "
                f"{wings_processed} wings processed, {wings_failed} wings failed, "
                f"{consolidated_registry.get_unique_identity_count()} unique identities aggregated, "
                f"{self.statistics.aggregation_errors} errors"
            )
        
        # Log detailed errors if any occurred
        if self.statistics.aggregation_errors > 0:
            logger.warning(
                f"[Identity Aggregator] Encountered {self.statistics.aggregation_errors} errors during multi-wing aggregation. "
                f"Continuing with {self.statistics.identities_successfully_aggregated} available identities."
            )
            
            # Log first few error details for debugging
            for error_detail in self.statistics.error_details[:5]:
                logger.debug(f"[Identity Aggregator] Error detail: {error_detail}")
            
            if len(self.statistics.error_details) > 5:
                logger.debug(
                    f"[Identity Aggregator] ... and {len(self.statistics.error_details) - 5} more errors"
                )
        
        return consolidated_registry
    
    def extract_from_identity_engine(self, results) -> IdentityRegistry:
        """
        Aggregate identities from Identity-Based engine results.
        
        Identity-Based engines maintain an identity index with all unique identities
        and their associated evidence. This method aggregates from that index.
        
        ENHANCED: Falls back to extracting from matches if identities list is empty.
        This handles the case where results are loaded from database without the
        pre-populated identities list.
        
        Handles errors gracefully by:
        - Validating each identity before processing
        - Continuing with remaining identities if one fails
        - Logging detailed error information
        - Tracking statistics for successful and failed aggregations
        - Falling back to match-based extraction if needed
        
        Args:
            results: CorrelationResults from Identity-Based engine
            
        Returns:
            IdentityRegistry with aggregated identities (may be partial if errors occurred)
            
        Requirements: 7.1, 7.2, 7.3, 7.4, 8.2, 10.1
        Property 5: Engine-Specific Identity Extraction
        Property 7: Error Handling and Graceful Degradation
        """
        registry = IdentityRegistry()
        
        if self.debug_mode:
            logger.info("[Identity Aggregator] Aggregating from Identity-Based engine")
        
        # Check if results has identities attribute (Identity-Based engine format)
        if not hasattr(results, 'identities'):
            error_msg = "Results object has no 'identities' attribute"
            logger.warning(f"[Identity Aggregator] {error_msg}")
            self.statistics.warnings.append(error_msg)
            
            # FALLBACK: Try extracting from matches instead
            if hasattr(results, 'matches') and results.matches:
                logger.info(f"[Identity Aggregator] Falling back to match-based extraction ({len(results.matches)} matches)")
                return self.extract_from_time_based_engine(results)
            
            return registry
        
        identities = results.identities if hasattr(results, 'identities') else []
        
        # Handle None or empty identities
        if identities is None or not identities:
            warning_msg = f"Identities list is {'None' if identities is None else 'empty'}"
            logger.warning(f"[Identity Aggregator] {warning_msg}")
            self.statistics.warnings.append(warning_msg)
            
            # FALLBACK: Try extracting from matches instead
            if hasattr(results, 'matches') and results.matches:
                logger.info(f"[Identity Aggregator] Falling back to match-based extraction ({len(results.matches)} matches)")
                return self.extract_from_time_based_engine(results)
            
            if self.debug_mode:
                logger.info("[Identity Aggregator] No identities found in index and no matches available")
            return registry
        
        if self.debug_mode:
            logger.info(f"[Identity Aggregator] Found {len(identities)} identities in index")
        
        self.statistics.total_identities_found = len(identities)
        
        # Aggregate each identity from the index
        for idx, identity in enumerate(identities):
            try:
                # Validate identity object
                if identity is None:
                    error_msg = f"Identity at index {idx} is None"
                    logger.warning(f"[Identity Aggregator] {error_msg}")
                    self.statistics.skipped_identities += 1
                    self.statistics.warnings.append(error_msg)
                    continue
                
                # Create identity record
                identity_record = self._create_identity_record_from_identity(identity)
                
                # Validate created record
                if not identity_record.identity_value:
                    error_msg = f"Identity at index {idx} has empty identity_value"
                    logger.warning(f"[Identity Aggregator] {error_msg}")
                    self.statistics.skipped_identities += 1
                    self.statistics.warnings.append(error_msg)
                    continue
                
                # Add to registry
                registry.add_identity(identity_record)
                self.statistics.identities_successfully_aggregated += 1
                
            except AttributeError as e:
                # Handle missing attributes gracefully
                error_msg = f"Identity at index {idx} missing required attribute: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.aggregation_errors += 1
                self.statistics.error_details.append(error_msg)
                continue
                
            except Exception as e:
                # Handle any other errors gracefully
                identity_id = getattr(identity, 'identity_id', f'index_{idx}')
                error_msg = f"Error aggregating identity {identity_id}: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.aggregation_errors += 1
                self.statistics.error_details.append(error_msg)
                continue
        
        if self.debug_mode:
            logger.info(
                f"[Identity Aggregator] Aggregated {registry.get_unique_identity_count()} unique identities "
                f"({self.statistics.aggregation_errors} errors, {self.statistics.skipped_identities} skipped)"
            )
        
        return registry
    
    def extract_from_time_based_engine(self, results) -> IdentityRegistry:
        """
        Aggregate identities from Time-Based engine results.
        
        Time-Based engines produce correlation matches without an identity index.
        This method aggregates identities from the match records themselves.
        
        Handles errors gracefully by:
        - Validating each match before processing
        - Continuing with remaining matches if one fails
        - Logging detailed error information
        - Tracking statistics for successful and failed aggregations
        
        Args:
            results: CorrelationResult from Time-Based engine
            
        Returns:
            IdentityRegistry with aggregated identities (may be partial if errors occurred)
            
        Requirements: 7.1, 7.2, 7.3, 7.4, 8.3, 10.2
        Property 5: Engine-Specific Identity Extraction
        Property 7: Error Handling and Graceful Degradation
        """
        registry = IdentityRegistry()
        
        if self.debug_mode:
            logger.info("[Identity Aggregator] Aggregating from Time-Based engine")
        
        # Check if results has matches attribute (Time-Based engine format)
        if not hasattr(results, 'matches'):
            error_msg = "Results object has no 'matches' attribute"
            logger.warning(f"[Identity Aggregator] {error_msg}")
            self.statistics.warnings.append(error_msg)
            return registry
        
        matches = results.matches if hasattr(results, 'matches') else []
        
        # Handle None or empty matches
        if matches is None:
            warning_msg = "Matches attribute is None"
            logger.warning(f"[Identity Aggregator] {warning_msg}")
            self.statistics.warnings.append(warning_msg)
            return registry
        
        if not matches:
            if self.debug_mode:
                logger.info("[Identity Aggregator] No matches found")
            return registry
        
        if self.debug_mode:
            logger.info(f"[Identity Aggregator] Processing {len(matches)} matches")
        
        # Track initial registry size to calculate identities found
        initial_identity_count = registry.get_unique_identity_count()
        
        # Aggregate identities from each match
        for idx, match in enumerate(matches):
            try:
                # Validate match object
                if match is None:
                    error_msg = f"Match at index {idx} is None"
                    logger.warning(f"[Identity Aggregator] {error_msg}")
                    self.statistics.skipped_identities += 1
                    self.statistics.warnings.append(error_msg)
                    continue
                
                # Aggregate identities from match fields
                self._extract_identities_from_match(match, registry)
                
            except AttributeError as e:
                # Handle missing attributes gracefully
                match_id = getattr(match, 'match_id', f'index_{idx}')
                error_msg = f"Match {match_id} missing required attribute: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.aggregation_errors += 1
                self.statistics.error_details.append(error_msg)
                continue
                
            except Exception as e:
                # Handle any other errors gracefully
                match_id = getattr(match, 'match_id', f'index_{idx}')
                error_msg = f"Error aggregating from match {match_id}: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.aggregation_errors += 1
                self.statistics.error_details.append(error_msg)
                continue
        
        # Calculate identities found from matches
        final_identity_count = registry.get_unique_identity_count()
        self.statistics.total_identities_found = final_identity_count - initial_identity_count
        self.statistics.identities_successfully_aggregated = self.statistics.total_identities_found
        
        if self.debug_mode:
            logger.info(
                f"[Identity Aggregator] Aggregated {registry.get_unique_identity_count()} unique identities "
                f"({self.statistics.aggregation_errors} errors, {self.statistics.skipped_identities} skipped)"
            )
        
        return registry
    
    def extract_from_streaming_results(self, database_path: str, execution_id: int) -> IdentityRegistry:
        """
        Aggregate identities from database-stored streaming results.
        
        For large datasets, correlation results are streamed to a database.
        This method aggregates identities from the database tables.
        
        Handles errors gracefully by:
        - Validating database connection and structure
        - Continuing with remaining records if one fails
        - Logging detailed error information
        - Tracking statistics for successful and failed aggregations
        
        Args:
            database_path: Path to SQLite database
            execution_id: Execution ID to aggregate from
            
        Returns:
            IdentityRegistry with aggregated identities (may be partial if errors occurred)
            
        Requirements: 7.1, 7.2, 7.3, 7.4, 8.5, 10.4
        Property 12: Streaming Mode Compatibility
        Property 7: Error Handling and Graceful Degradation
        """
        registry = IdentityRegistry()
        
        if self.debug_mode:
            logger.info(f"[Identity Aggregator] Aggregating from streaming database: {database_path}")
        
        # Validate database path
        if not database_path:
            error_msg = "Database path is empty or None"
            logger.error(f"[Identity Aggregator] {error_msg}")
            self.statistics.error_details.append(error_msg)
            self.statistics.malformed_results_encountered += 1
            return registry
        
        # Import required modules
        import sqlite3
        import json
        from pathlib import Path
        
        # Check if database file exists
        db_path = Path(database_path)
        if not db_path.exists():
            error_msg = f"Database file does not exist: {database_path}"
            logger.error(f"[Identity Aggregator] {error_msg}")
            self.statistics.error_details.append(error_msg)
            self.statistics.malformed_results_encountered += 1
            return registry
        
        # Initialize connection to None for proper cleanup
        conn = None
        
        try:
            # Connect to database (Requirements 6.4, 15.1)
            # Properly open connection before use
            try:
                conn = sqlite3.connect(database_path)
                cursor = conn.cursor()
                
                if self.debug_mode:
                    logger.info(f"[Identity Aggregator] Connected to database: {database_path}")
                    
            except sqlite3.Error as e:
                error_msg = f"Failed to connect to database: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.error_details.append(error_msg)
                self.statistics.malformed_results_encountered += 1
                return registry
            
            # Verify tables exist
            try:
                # Check for results table
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='results'
                """)
                if not cursor.fetchone():
                    error_msg = "Table 'results' does not exist in database"
                    logger.error(f"[Identity Aggregator] {error_msg}")
                    self.statistics.error_details.append(error_msg)
                    self.statistics.malformed_results_encountered += 1
                    return registry
                
                # Check for matches table
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='matches'
                """)
                if not cursor.fetchone():
                    error_msg = "Table 'matches' does not exist in database"
                    logger.error(f"[Identity Aggregator] {error_msg}")
                    self.statistics.error_details.append(error_msg)
                    self.statistics.malformed_results_encountered += 1
                    return registry
                    
            except sqlite3.Error as e:
                error_msg = f"Failed to verify database structure: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.error_details.append(error_msg)
                self.statistics.malformed_results_encountered += 1
                return registry
            
            # Query matches for this execution via results table
            try:
                # First get result_id(s) for this execution
                cursor.execute("""
                    SELECT result_id
                    FROM results
                    WHERE execution_id = ?
                """, (execution_id,))
                
                result_rows = cursor.fetchall()
                if not result_rows:
                    warning_msg = f"No results found for execution_id={execution_id}"
                    logger.warning(f"[Identity Aggregator] {warning_msg}")
                    self.statistics.warnings.append(warning_msg)
                    return registry
                
                result_ids = [row[0] for row in result_rows]
                
                # Now get all matches for these results
                placeholders = ','.join('?' * len(result_ids))
                cursor.execute(f"""
                    SELECT match_id, feather_records, matched_application, matched_file_path
                    FROM matches
                    WHERE result_id IN ({placeholders})
                """, result_ids)
                
                rows = cursor.fetchall()
                
            except sqlite3.Error as e:
                error_msg = f"Failed to query matches: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.error_details.append(error_msg)
                self.statistics.malformed_results_encountered += 1
                return registry
            
            if not rows:
                warning_msg = f"No matches found for execution_id={execution_id}"
                logger.warning(f"[Identity Aggregator] {warning_msg}")
                self.statistics.warnings.append(warning_msg)
                return registry
            
            if self.debug_mode:
                logger.info(f"[Identity Aggregator] Found {len(rows)} matches in database")
            
            self.statistics.total_identities_found = len(rows)
            
            # Aggregate identities from each match
            for idx, (match_id, feather_records_json, matched_application, matched_file_path) in enumerate(rows):
                try:
                    # Create identity from match data
                    # Use matched_application or matched_file_path as identity value
                    identity_value = matched_application or matched_file_path or match_id
                    
                    if not identity_value:
                        self.statistics.skipped_identities += 1
                        continue
                    
                    # Parse feather_records to get record references
                    record_refs = []
                    if feather_records_json:
                        try:
                            feather_records = json.loads(feather_records_json)
                            if isinstance(feather_records, dict):
                                for feather_id, record_data in feather_records.items():
                                    if isinstance(record_data, dict):
                                        record_refs.append(RecordReference(
                                            match_id=match_id,
                                            feather_id=feather_id,
                                            record_index=record_data.get('_rowid', 0),
                                            original_record=record_data
                                        ))
                        except json.JSONDecodeError:
                            pass  # Skip if JSON is malformed
                    
                    # Create identity record
                    identity_record = IdentityRecord(
                        identity_value=identity_value,
                        identity_type='application' if matched_application else 'file_path',
                        record_references=record_refs,
                        semantic_data={}  # Will be populated during semantic enhancement
                    )
                    
                    # Add to registry
                    registry.add_identity(identity_record)
                    self.statistics.identities_successfully_aggregated += 1
                    
                except Exception as e:
                    error_msg = f"Error aggregating identity from match {match_id}: {e}"
                    logger.error(f"[Identity Aggregator] {error_msg}")
                    self.statistics.aggregation_errors += 1
                    self.statistics.error_details.append(error_msg)
                    continue
            
            if self.debug_mode:
                logger.info(
                    f"[Identity Aggregator] Aggregated {registry.get_unique_identity_count()} unique identities from database "
                    f"({self.statistics.aggregation_errors} errors, {self.statistics.skipped_identities} skipped)"
                )
            
            return registry
            
        except Exception as e:
            error_msg = f"Unexpected error during streaming aggregation: {e}"
            logger.error(f"[Identity Aggregator] {error_msg}", exc_info=True)
            self.statistics.error_details.append(error_msg)
            self.statistics.malformed_results_encountered += 1
            return registry
            
        finally:
            # Always close connection after completion (Requirements 6.4, 15.1)
            # Ensure connection is closed even if errors occur
            if conn is not None:
                try:
                    conn.close()
                    if self.debug_mode:
                        logger.info("[Identity Aggregator] Database connection closed")
                except Exception as e:
                    logger.warning(f"[Identity Aggregator] Error closing database connection: {e}")
    
    def _create_identity_record_from_identity(self, identity) -> IdentityRecord:
        """
        Create IdentityRecord from Identity-Based engine Identity object.
        
        Handles malformed identity objects gracefully by:
        - Providing default values for missing attributes
        - Validating extracted values
        - Logging warnings for unexpected data
        
        Args:
            identity: Identity object from engine
            
        Returns:
            IdentityRecord for registry
            
        Raises:
            ValueError: If identity cannot be created due to missing critical data
            
        Requirements: 7.1, 7.2, 7.3
        Property 7: Error Handling and Graceful Degradation
        """
        # Extract identity information with fallbacks
        identity_value = getattr(identity, 'identity_value', None) or getattr(identity, 'normalized_name', None)
        
        if not identity_value:
            # Try to get any identifying information
            identity_id = getattr(identity, 'identity_id', 'unknown')
            raise ValueError(f"Identity {identity_id} has no identity_value or normalized_name")
        
        # Get identity type with fallback
        identity_type = getattr(identity, 'identity_type', 'unknown')
        
        if identity_type == 'unknown':
            warning_msg = f"Identity '{identity_value}' has unknown type"
            logger.debug(f"[Identity Aggregator] {warning_msg}")
            self.statistics.warnings.append(warning_msg)
        
        # Create identity record
        identity_record = IdentityRecord(
            identity_value=str(identity_value),
            identity_type=str(identity_type)
        )
        
        # Extract record references from all evidence
        all_evidence = getattr(identity, 'all_evidence', [])
        
        if not all_evidence:
            warning_msg = f"Identity '{identity_value}' has no evidence records"
            logger.debug(f"[Identity Aggregator] {warning_msg}")
        
        for evidence_idx, evidence in enumerate(all_evidence):
            try:
                # Validate evidence object
                if evidence is None:
                    logger.debug(f"[Identity Aggregator] Evidence at index {evidence_idx} is None for identity '{identity_value}'")
                    continue
                
                # Create record reference with fallbacks
                record_ref = RecordReference(
                    match_id=getattr(identity, 'identity_id', ''),
                    feather_id=getattr(evidence, 'feather_id', ''),
                    record_index=getattr(evidence, 'row_id', 0),
                    original_record=getattr(evidence, 'original_data', {})
                )
                
                identity_record.add_record_reference(record_ref)
                
            except Exception as e:
                error_msg = f"Error creating record reference for evidence {evidence_idx}: {e}"
                logger.debug(f"[Identity Aggregator] {error_msg}")
                # Continue with other evidence records
                continue
        
        return identity_record
    
    def _extract_identities_from_match(self, match, registry: IdentityRegistry):
        """
        Extract identities from a Time-Based engine match object.
        
        Handles errors gracefully by continuing with available identity fields
        even if some fields are missing or malformed.
        
        Args:
            match: CorrelationMatch object
            registry: IdentityRegistry to add identities to
            
        Requirements: 7.1, 7.2, 7.3
        Property 7: Error Handling and Graceful Degradation
        """
        # Extract identity fields from match
        match_id = getattr(match, 'match_id', '')
        
        if not match_id:
            logger.debug("[Identity Aggregator] Match has no match_id, using empty string")
        
        # Extract file path identity (with error handling)
        try:
            if hasattr(match, 'matched_file_path') and match.matched_file_path:
                self._add_identity_to_registry(
                    registry=registry,
                    identity_value=str(match.matched_file_path),
                    identity_type='file_path',
                    match_id=match_id,
                    match=match
                )
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error extracting file_path from match {match_id}: {e}")
        
        # Extract application identity (with error handling)
        try:
            if hasattr(match, 'matched_application') and match.matched_application:
                self._add_identity_to_registry(
                    registry=registry,
                    identity_value=str(match.matched_application),
                    identity_type='application',
                    match_id=match_id,
                    match=match
                )
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error extracting application from match {match_id}: {e}")
        
        # Extract identities from feather records (with error handling)
        try:
            if hasattr(match, 'feather_records'):
                feather_records = match.feather_records
                
                if feather_records is None:
                    logger.debug(f"[Identity Aggregator] Match {match_id} has None feather_records")
                    return
                
                if not isinstance(feather_records, dict):
                    logger.debug(f"[Identity Aggregator] Match {match_id} has invalid feather_records type: {type(feather_records)}")
                    return
                
                for feather_id, record_data in feather_records.items():
                    try:
                        # Validate record data
                        if record_data is None:
                            logger.debug(f"[Identity Aggregator] Feather record {feather_id} is None in match {match_id}")
                            continue
                        
                        if not isinstance(record_data, dict):
                            logger.debug(f"[Identity Aggregator] Feather record {feather_id} has invalid type: {type(record_data)}")
                            continue
                        
                        # Extract identities from record fields
                        self._extract_identities_from_record(
                            record_data=record_data,
                            feather_id=feather_id,
                            match_id=match_id,
                            registry=registry
                        )
                    except Exception as e:
                        logger.debug(f"[Identity Aggregator] Error extracting from feather record {feather_id}: {e}")
                        continue
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error processing feather_records for match {match_id}: {e}")
    
    def _extract_identities_from_match_dict(self, match_data: Dict[str, Any], 
                                           registry: IdentityRegistry, match_id: str):
        """
        Extract identities from a match dictionary (from database).
        
        Args:
            match_data: Match data dictionary
            registry: IdentityRegistry to add identities to
            match_id: Match ID
        """
        # Extract file path identity
        if 'matched_file_path' in match_data and match_data['matched_file_path']:
            self._add_identity_to_registry(
                registry=registry,
                identity_value=match_data['matched_file_path'],
                identity_type='file_path',
                match_id=match_id,
                match=match_data
            )
        
        # Extract application identity
        if 'matched_application' in match_data and match_data['matched_application']:
            self._add_identity_to_registry(
                registry=registry,
                identity_value=match_data['matched_application'],
                identity_type='application',
                match_id=match_id,
                match=match_data
            )
        
        # Extract identities from feather records
        if 'feather_records' in match_data:
            feather_records = match_data['feather_records']
            
            for feather_id, record_data in feather_records.items():
                # Extract identities from record fields
                self._extract_identities_from_record(
                    record_data=record_data,
                    feather_id=feather_id,
                    match_id=match_id,
                    registry=registry
                )
    
    def _extract_identities_from_record(self, record_data: Dict[str, Any], 
                                       feather_id: str, match_id: str,
                                       registry: IdentityRegistry):
        """
        Extract identities from a feather record.
        
        Handles errors gracefully by continuing with available fields
        even if some fields are missing or malformed.
        
        Args:
            record_data: Record data dictionary
            feather_id: Feather ID
            match_id: Match ID
            registry: IdentityRegistry to add identities to
            
        Requirements: 7.1, 7.2, 7.3
        Property 7: Error Handling and Graceful Degradation
        """
        # Common identity field names to check
        identity_fields = {
            'file_path': ['file_path', 'path', 'full_path', 'executable_path'],
            'process_name': ['process_name', 'name', 'executable_name', 'application'],
            'user_id': ['user', 'user_id', 'username', 'user_name'],
            'hash': ['hash', 'file_hash', 'md5', 'sha1', 'sha256']
        }
        
        # Extract identities from known fields
        for identity_type, field_names in identity_fields.items():
            for field_name in field_names:
                try:
                    if field_name in record_data and record_data[field_name]:
                        value = record_data[field_name]
                        
                        # Skip empty or None values
                        if not value or value == '':
                            continue
                        
                        # Validate value type
                        if not isinstance(value, (str, int, float)):
                            logger.debug(
                                f"[Identity Aggregator] Field {field_name} has invalid type {type(value)} "
                                f"in record {feather_id}"
                            )
                            continue
                        
                        # Add identity to registry
                        self._add_identity_to_registry(
                            registry=registry,
                            identity_value=str(value),
                            identity_type=identity_type,
                            match_id=match_id,
                            match=record_data,
                            feather_id=feather_id
                        )
                except Exception as e:
                    logger.debug(
                        f"[Identity Aggregator] Error extracting {field_name} from record {feather_id}: {e}"
                    )
                    continue
    
    def _add_identity_to_registry(self, registry: IdentityRegistry, 
                                  identity_value: str, identity_type: str,
                                  match_id: str, match: Any, 
                                  feather_id: str = '', record_index: int = 0):
        """
        Add an identity to the registry with record reference.
        
        Handles errors gracefully by validating inputs before adding.
        
        Args:
            registry: IdentityRegistry to add to
            identity_value: Identity value
            identity_type: Identity type
            match_id: Match ID
            match: Match object or dictionary
            feather_id: Feather ID (optional)
            record_index: Record index (optional)
            
        Requirements: 7.1, 7.2, 7.3
        Property 7: Error Handling and Graceful Degradation
        """
        try:
            # Validate identity value
            if not identity_value or not isinstance(identity_value, str):
                logger.debug(f"[Identity Aggregator] Invalid identity_value: {identity_value}")
                return
            
            # Validate identity type
            if not identity_type or not isinstance(identity_type, str):
                logger.debug(f"[Identity Aggregator] Invalid identity_type: {identity_type}")
                return
            
            # Check if identity already exists in registry
            existing = registry.get_identity_record(identity_value)
            
            if existing:
                # Add record reference to existing identity
                record_ref = RecordReference(
                    match_id=match_id,
                    feather_id=feather_id,
                    record_index=record_index,
                    original_record=match if isinstance(match, dict) else {}
                )
                existing.add_record_reference(record_ref)
            else:
                # Create new identity record
                identity_record = IdentityRecord(
                    identity_value=identity_value,
                    identity_type=identity_type
                )
                
                # Add record reference
                record_ref = RecordReference(
                    match_id=match_id,
                    feather_id=feather_id,
                    record_index=record_index,
                    original_record=match if isinstance(match, dict) else {}
                )
                identity_record.add_record_reference(record_ref)
                
                # Add to registry
                registry.add_identity(identity_record)
                
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error adding identity to registry: {e}")
    
    def get_aggregation_statistics(self) -> AggregationStatistics:
        """
        Get statistics from the last aggregation operation.
        
        Returns:
            AggregationStatistics object with detailed metrics
            
        Requirements: 7.3
        Property 7: Error Handling and Graceful Degradation
        """
        return self.statistics
    
    def reset_statistics(self):
        """Reset aggregation statistics"""
        self.statistics = AggregationStatistics()
    
    def _extract_identities_with_wing_context(self, 
                                             correlation_results, 
                                             engine_type: str,
                                             wing_id: str,
                                             wing_name: str) -> IdentityRegistry:
        """
        Extract identities from correlation results with wing context.
        
        This is a helper method for multi-wing aggregation that adds wing context
        to all extracted identities.
        
        Args:
            correlation_results: Correlation results object
            engine_type: Type of engine
            wing_id: Wing identifier
            wing_name: Wing name
            
        Returns:
            IdentityRegistry with wing context added to all identities
            
        Requirements: 10.5
        Property 13: Multi-Wing Scenario Support
        """
        # Extract identities using standard method
        if engine_type.lower() in ["identity_based", "identity-based", "identity"]:
            registry = self._extract_from_identity_engine_with_wing(
                correlation_results, wing_id, wing_name
            )
        elif engine_type.lower() in ["time_based", "time-based", "time"]:
            registry = self._extract_from_time_based_engine_with_wing(
                correlation_results, wing_id, wing_name
            )
        else:
            # Default to time-based
            registry = self._extract_from_time_based_engine_with_wing(
                correlation_results, wing_id, wing_name
            )
        
        return registry
    
    def _extract_from_identity_engine_with_wing(self, results, wing_id: str, wing_name: str) -> IdentityRegistry:
        """
        Extract identities from Identity-Based engine with wing context.
        
        Similar to extract_from_identity_engine but adds wing context to record references.
        
        Args:
            results: CorrelationResults from Identity-Based engine
            wing_id: Wing identifier
            wing_name: Wing name
            
        Returns:
            IdentityRegistry with wing context
        """
        registry = IdentityRegistry()
        
        if not hasattr(results, 'identities'):
            return registry
        
        identities = results.identities if hasattr(results, 'identities') else []
        
        if identities is None or not identities:
            return registry
        
        self.statistics.total_identities_found += len(identities)
        
        # Aggregate each identity from the index
        for idx, identity in enumerate(identities):
            try:
                if identity is None:
                    self.statistics.skipped_identities += 1
                    continue
                
                # Create identity record with wing context
                identity_record = self._create_identity_record_with_wing(
                    identity, wing_id, wing_name
                )
                
                if not identity_record.identity_value:
                    self.statistics.skipped_identities += 1
                    continue
                
                registry.add_identity(identity_record)
                self.statistics.identities_successfully_aggregated += 1
                
            except Exception as e:
                identity_id = getattr(identity, 'identity_id', f'index_{idx}')
                error_msg = f"Error aggregating identity {identity_id} from wing {wing_name}: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.aggregation_errors += 1
                self.statistics.error_details.append(error_msg)
                continue
        
        return registry
    
    def _extract_from_time_based_engine_with_wing(self, results, wing_id: str, wing_name: str) -> IdentityRegistry:
        """
        Extract identities from Time-Based engine with wing context.
        
        Similar to extract_from_time_based_engine but adds wing context to record references.
        
        Args:
            results: CorrelationResult from Time-Based engine
            wing_id: Wing identifier
            wing_name: Wing name
            
        Returns:
            IdentityRegistry with wing context
        """
        registry = IdentityRegistry()
        
        if not hasattr(results, 'matches'):
            return registry
        
        matches = results.matches if hasattr(results, 'matches') else []
        
        if matches is None or not matches:
            return registry
        
        # Aggregate identities from each match
        for idx, match in enumerate(matches):
            try:
                if match is None:
                    self.statistics.skipped_identities += 1
                    continue
                
                # Extract identities from match with wing context
                self._extract_identities_from_match_with_wing(
                    match, registry, wing_id, wing_name
                )
                
            except Exception as e:
                match_id = getattr(match, 'match_id', f'index_{idx}')
                error_msg = f"Error aggregating from match {match_id} in wing {wing_name}: {e}"
                logger.error(f"[Identity Aggregator] {error_msg}")
                self.statistics.aggregation_errors += 1
                self.statistics.error_details.append(error_msg)
                continue
        
        # Update statistics
        final_identity_count = registry.get_unique_identity_count()
        self.statistics.total_identities_found += final_identity_count
        self.statistics.identities_successfully_aggregated += final_identity_count
        
        return registry
    
    def _create_identity_record_with_wing(self, identity, wing_id: str, wing_name: str) -> IdentityRecord:
        """
        Create IdentityRecord from Identity-Based engine Identity object with wing context.
        
        Args:
            identity: Identity object from engine
            wing_id: Wing identifier
            wing_name: Wing name
            
        Returns:
            IdentityRecord with wing context
        """
        # Extract identity information
        identity_value = getattr(identity, 'identity_value', None) or getattr(identity, 'normalized_name', None)
        
        if not identity_value:
            identity_id = getattr(identity, 'identity_id', 'unknown')
            raise ValueError(f"Identity {identity_id} has no identity_value or normalized_name")
        
        identity_type = getattr(identity, 'identity_type', 'unknown')
        
        # Create identity record
        identity_record = IdentityRecord(
            identity_value=str(identity_value),
            identity_type=str(identity_type)
        )
        
        # Extract record references with wing context
        all_evidence = getattr(identity, 'all_evidence', [])
        
        for evidence_idx, evidence in enumerate(all_evidence):
            try:
                if evidence is None:
                    continue
                
                # Create record reference with wing context
                record_ref = RecordReference(
                    match_id=getattr(identity, 'identity_id', ''),
                    feather_id=getattr(evidence, 'feather_id', ''),
                    record_index=getattr(evidence, 'row_id', 0),
                    original_record=getattr(evidence, 'original_data', {}),
                    wing_id=wing_id,
                    wing_name=wing_name
                )
                
                identity_record.add_record_reference(record_ref)
                
            except Exception as e:
                logger.debug(f"[Identity Aggregator] Error creating record reference with wing context: {e}")
                continue
        
        return identity_record
    
    def _extract_identities_from_match_with_wing(self, match, registry: IdentityRegistry, 
                                                 wing_id: str, wing_name: str):
        """
        Extract identities from a Time-Based engine match with wing context.
        
        Args:
            match: CorrelationMatch object
            registry: IdentityRegistry to add identities to
            wing_id: Wing identifier
            wing_name: Wing name
        """
        match_id = getattr(match, 'match_id', '')
        
        # Extract file path identity
        try:
            if hasattr(match, 'matched_file_path') and match.matched_file_path:
                self._add_identity_to_registry_with_wing(
                    registry=registry,
                    identity_value=str(match.matched_file_path),
                    identity_type='file_path',
                    match_id=match_id,
                    match=match,
                    wing_id=wing_id,
                    wing_name=wing_name
                )
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error extracting file_path with wing context: {e}")
        
        # Extract application identity
        try:
            if hasattr(match, 'matched_application') and match.matched_application:
                self._add_identity_to_registry_with_wing(
                    registry=registry,
                    identity_value=str(match.matched_application),
                    identity_type='application',
                    match_id=match_id,
                    match=match,
                    wing_id=wing_id,
                    wing_name=wing_name
                )
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error extracting application with wing context: {e}")
        
        # Extract identities from feather records
        try:
            if hasattr(match, 'feather_records'):
                feather_records = match.feather_records
                
                if feather_records is None or not isinstance(feather_records, dict):
                    return
                
                for feather_id, record_data in feather_records.items():
                    try:
                        if record_data is None or not isinstance(record_data, dict):
                            continue
                        
                        # Extract identities from record fields with wing context
                        self._extract_identities_from_record_with_wing(
                            record_data=record_data,
                            feather_id=feather_id,
                            match_id=match_id,
                            registry=registry,
                            wing_id=wing_id,
                            wing_name=wing_name
                        )
                    except Exception as e:
                        logger.debug(f"[Identity Aggregator] Error extracting from feather record with wing context: {e}")
                        continue
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error processing feather_records with wing context: {e}")
    
    def _extract_identities_from_record_with_wing(self, record_data: Dict[str, Any], 
                                                  feather_id: str, match_id: str,
                                                  registry: IdentityRegistry,
                                                  wing_id: str, wing_name: str):
        """
        Extract identities from a feather record with wing context.
        
        Args:
            record_data: Record data dictionary
            feather_id: Feather ID
            match_id: Match ID
            registry: IdentityRegistry to add identities to
            wing_id: Wing identifier
            wing_name: Wing name
        """
        # Common identity field names to check
        identity_fields = {
            'file_path': ['file_path', 'path', 'full_path', 'executable_path'],
            'process_name': ['process_name', 'name', 'executable_name', 'application'],
            'user_id': ['user', 'user_id', 'username', 'user_name'],
            'hash': ['hash', 'file_hash', 'md5', 'sha1', 'sha256']
        }
        
        # Extract identities from known fields
        for identity_type, field_names in identity_fields.items():
            for field_name in field_names:
                try:
                    if field_name in record_data and record_data[field_name]:
                        value = record_data[field_name]
                        
                        if not value or value == '':
                            continue
                        
                        if not isinstance(value, (str, int, float)):
                            continue
                        
                        # Add identity to registry with wing context
                        self._add_identity_to_registry_with_wing(
                            registry=registry,
                            identity_value=str(value),
                            identity_type=identity_type,
                            match_id=match_id,
                            match=record_data,
                            feather_id=feather_id,
                            wing_id=wing_id,
                            wing_name=wing_name
                        )
                except Exception as e:
                    logger.debug(f"[Identity Aggregator] Error extracting {field_name} with wing context: {e}")
                    continue
    
    def _add_identity_to_registry_with_wing(self, registry: IdentityRegistry, 
                                           identity_value: str, identity_type: str,
                                           match_id: str, match: Any, 
                                           wing_id: str, wing_name: str,
                                           feather_id: str = '', record_index: int = 0):
        """
        Add an identity to the registry with record reference including wing context.
        
        Args:
            registry: IdentityRegistry to add to
            identity_value: Identity value
            identity_type: Identity type
            match_id: Match ID
            match: Match object or dictionary
            wing_id: Wing identifier
            wing_name: Wing name
            feather_id: Feather ID (optional)
            record_index: Record index (optional)
        """
        try:
            if not identity_value or not isinstance(identity_value, str):
                return
            
            if not identity_type or not isinstance(identity_type, str):
                return
            
            # Check if identity already exists in registry
            existing = registry.get_identity_record(identity_value)
            
            if existing:
                # Add record reference with wing context to existing identity
                record_ref = RecordReference(
                    match_id=match_id,
                    feather_id=feather_id,
                    record_index=record_index,
                    original_record=match if isinstance(match, dict) else {},
                    wing_id=wing_id,
                    wing_name=wing_name
                )
                existing.add_record_reference(record_ref)
            else:
                # Create new identity record
                identity_record = IdentityRecord(
                    identity_value=identity_value,
                    identity_type=identity_type
                )
                
                # Add record reference with wing context
                record_ref = RecordReference(
                    match_id=match_id,
                    feather_id=feather_id,
                    record_index=record_index,
                    original_record=match if isinstance(match, dict) else {},
                    wing_id=wing_id,
                    wing_name=wing_name
                )
                identity_record.add_record_reference(record_ref)
                
                # Add to registry
                registry.add_identity(identity_record)
                
        except Exception as e:
            logger.debug(f"[Identity Aggregator] Error adding identity to registry with wing context: {e}")
    
    def _merge_registries(self, target: IdentityRegistry, source: IdentityRegistry):
        """
        Merge source registry into target registry.
        
        This consolidates identities from multiple wings, deduplicating identities
        that appear in multiple wings while preserving all record references.
        
        Args:
            target: Target registry to merge into
            source: Source registry to merge from
            
        Requirements: 10.5
        Property 13: Multi-Wing Scenario Support
        Property 4: Identity Consolidation Completeness
        """
        # Get all identities from source
        for identity in source.get_all_identities():
            # Add to target (will automatically deduplicate and merge references)
            target.add_identity(identity)

    
    def save_identity_fields_to_database(self, database_path: str, execution_id: int, 
                                        force_update: bool = True) -> int:
        """
        Extract identity information from matched_application column and feather records,
        then save identity_value and identity_type fields back to the database.
        
        This enables semantic mapping to work by adding the required identity fields
        that semantic rules expect.
        
        STRATEGY:
        1. Primary: Use matched_application column (fast, already extracted)
        2. Fallback: Parse feather_records JSON (for complex cases)
        
        IMPORTANT: Multiple records in the same feather can share the same identity.
        For example, multiple Prefetch records for "CHROME.EXE" all get the same
        identity_value, allowing them to be grouped and correlated together.
        
        Args:
            database_path: Path to SQLite database
            execution_id: Execution ID to process
            force_update: If True, always update identity fields even if they exist.
                         If False, only add fields if missing. Default: True
            
        Returns:
            Number of matches updated with identity fields
            
        Requirements: Identity Extraction Phase
        """
        import sqlite3
        import json
        
        logger.info(f"[Identity Aggregator] Saving identity fields to database for execution {execution_id}")
        logger.info(f"[Identity Aggregator] Force update: {force_update}")
        logger.info(f"[Identity Aggregator] Strategy: Use matched_application column (primary) + feather_records (fallback)")
        
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        
        try:
            # Get all matches for this execution (including matched_application column)
            cursor.execute("""
                SELECT m.match_id, m.matched_application, m.anchor_feather_id, m.feather_records
                FROM matches m
                INNER JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (execution_id,))
            
            matches = cursor.fetchall()
            logger.info(f"[Identity Aggregator] Processing {len(matches):,} matches")
            
            updated_count = 0
            records_with_identity = 0
            used_matched_application = 0
            used_feather_records = 0
            
            for match_id, matched_application, anchor_feather_id, feather_records_json in matches:
                try:
                    if not feather_records_json:
                        continue
                    
                    records = json.loads(feather_records_json)
                    modified = False
                    
                    # STRATEGY 1: Try to use matched_application column (fast and simple)
                    identity_from_matched_app = None
                    identity_type_from_matched_app = None
                    
                    if matched_application and self._is_valid_identity(matched_application):
                        # Determine identity type based on anchor_feather_id
                        identity_from_matched_app = matched_application
                        identity_type_from_matched_app = self._determine_identity_type(anchor_feather_id)
                    
                    # Process each feather in the match
                    for feather_name, record_data in records.items():
                        if isinstance(record_data, list):
                            # Multiple records in this feather - each can have same or different identity
                            for record in record_data:
                                if isinstance(record, dict):
                                    # Skip metadata records
                                    if record.get('_table') == 'feather_metadata':
                                        continue
                                    
                                    # Check if should update
                                    should_update = force_update or ('identity_value' not in record or 'identity_type' not in record)
                                    
                                    if should_update:
                                        # Try matched_application first
                                        if identity_from_matched_app:
                                            record['identity_value'] = identity_from_matched_app
                                            record['identity_type'] = identity_type_from_matched_app
                                            modified = True
                                            records_with_identity += 1
                                            used_matched_application += 1
                                        else:
                                            # Fallback: Extract from feather_records
                                            identity_value, identity_type = self._extract_identity_from_record(feather_name, record)
                                            
                                            if identity_value:
                                                record['identity_value'] = identity_value
                                                record['identity_type'] = identity_type
                                                modified = True
                                                records_with_identity += 1
                                                used_feather_records += 1
                        
                        elif isinstance(record_data, dict):
                            # Single record in this feather
                            # Skip metadata records
                            if record_data.get('_table') == 'feather_metadata':
                                continue
                            
                            # Check if should update
                            should_update = force_update or ('identity_value' not in record_data or 'identity_type' not in record_data)
                            
                            if should_update:
                                # Try matched_application first
                                if identity_from_matched_app:
                                    record_data['identity_value'] = identity_from_matched_app
                                    record_data['identity_type'] = identity_type_from_matched_app
                                    modified = True
                                    records_with_identity += 1
                                    used_matched_application += 1
                                else:
                                    # Fallback: Extract from feather_records
                                    identity_value, identity_type = self._extract_identity_from_record(feather_name, record_data)
                                    
                                    if identity_value:
                                        record_data['identity_value'] = identity_value
                                        record_data['identity_type'] = identity_type
                                        modified = True
                                        records_with_identity += 1
                                        used_feather_records += 1
                    
                    # Update the match if modified
                    if modified:
                        updated_feather_records = json.dumps(records)
                        cursor.execute("""
                            UPDATE matches
                            SET feather_records = ?
                            WHERE match_id = ?
                        """, (updated_feather_records, match_id))
                        updated_count += 1
                
                except Exception as e:
                    logger.error(f"[Identity Aggregator] Error processing match {match_id}: {e}")
                    continue
            
            # Commit changes
            conn.commit()
            logger.info(f"[Identity Aggregator] Updated {updated_count:,} matches with identity fields")
            logger.info(f"[Identity Aggregator] Total records with identity: {records_with_identity:,}")
            logger.info(f"[Identity Aggregator] Used matched_application: {used_matched_application:,} records")
            logger.info(f"[Identity Aggregator] Used feather_records: {used_feather_records:,} records")
            
            return updated_count
            
        finally:
            conn.close()
    
    def _extract_identity_from_record(self, feather_name: str, record: Dict[str, Any]) -> tuple:
        """
        Extract identity value and type from a forensic record.
        
        Args:
            feather_name: Name of the feather (e.g., 'prefetch', 'shimcache')
            record: Record dictionary
            
        Returns:
            Tuple of (identity_value, identity_type) or (None, None)
        """
        # Prefetch: executable_name is the identity
        if feather_name == 'prefetch':
            if 'executable_name' in record:
                return record['executable_name'], 'application'
        
        # Shimcache: executable is the identity
        elif feather_name == 'shimcache':
            if 'executable' in record:
                return record['executable'], 'application'
            elif 'path' in record:
                # Extract filename from path
                path = record['path']
                if '\\' in path:
                    filename = path.split('\\')[-1]
                    return filename, 'application'
        
        # LNK: target_path is the identity
        elif feather_name == 'lnk':
            if 'target_path' in record:
                path = record['target_path']
                if '\\' in path:
                    filename = path.split('\\')[-1]
                    return filename, 'file'
        
        # ShellBags: path is the identity
        elif feather_name == 'shellbags':
            if 'path' in record:
                return record['path'], 'folder'
        
        # SRUM: application is the identity
        elif 'srum' in feather_name:
            if 'application' in record:
                return record['application'], 'application'
            elif 'app_name' in record:
                return record['app_name'], 'application'
        
        # System/App logs: look for various fields
        elif 'log' in feather_name:
            if 'application' in record:
                return record['application'], 'application'
            elif 'source' in record:
                return record['source'], 'service'
        
        # MFT/USN: file_name is the identity
        elif 'mft' in feather_name or 'usn' in feather_name:
            if 'file_name' in record:
                return record['file_name'], 'file'
            elif 'filename' in record:
                return record['filename'], 'file'
        
        # Amcache: various fields
        elif 'amcache' in feather_name:
            if 'program_name' in record:
                return record['program_name'], 'application'
            elif 'file_name' in record:
                return record['file_name'], 'file'
            elif 'path' in record:
                path = record['path']
                if '\\' in path:
                    filename = path.split('\\')[-1]
                    return filename, 'file'
        
        # Jumplist: application is the identity
        elif 'jumplist' in feather_name:
            if 'application' in record:
                return record['application'], 'application'
            elif 'app_id' in record:
                return record['app_id'], 'application'
        
        return None, None
    
    def _is_valid_identity(self, value: str) -> bool:
        """
        Check if a matched_application value is a valid identity.
        
        Filters out metadata values like:
        - "prefetch", "shimcache" (feather names)
        - Timestamps
        - Database paths
        - Generic metadata
        
        Args:
            value: matched_application value to check
            
        Returns:
            True if valid identity, False if metadata
        """
        if not value or len(value) < 2:
            return False
        
        # Filter out feather names
        feather_names = ['prefetch', 'shimcache', 'lnk', 'shellbags', 'srum', 
                        'mft', 'usn', 'amcache', 'jumplist', 'log', 'logs']
        if value.lower() in feather_names:
            return False
        
        # Filter out feather IDs with underscores
        if '_' in value and any(f in value.lower() for f in ['feather', 'crow', 'eye']):
            return False
        
        # Filter out timestamps (contains T and colons)
        if 'T' in value and ':' in value:
            return False
        
        # Filter out file paths (contains backslashes or forward slashes with drive letters)
        if '\\' in value or (value.count('/') > 1):
            return False
        
        # Filter out database names
        if value.endswith('_data') or value.endswith('.db'):
            return False
        
        return True
    
    def _determine_identity_type(self, anchor_feather_id: str) -> str:
        """
        Determine identity type based on anchor feather ID.
        
        Args:
            anchor_feather_id: Feather ID (e.g., 'prefetch', 'shimcache')
            
        Returns:
            Identity type ('application', 'file', 'folder', 'service', or 'unknown')
        """
        if not anchor_feather_id:
            return 'unknown'
        
        feather_lower = anchor_feather_id.lower()
        
        # Application-related feathers
        if any(f in feather_lower for f in ['prefetch', 'shimcache', 'srum', 'amcache', 'jumplist']):
            return 'application'
        
        # File-related feathers
        if any(f in feather_lower for f in ['mft', 'usn', 'lnk']):
            return 'file'
        
        # Folder-related feathers
        if 'shellbag' in feather_lower:
            return 'folder'
        
        # Service/log-related feathers
        if 'log' in feather_lower:
            return 'service'
        
        return 'unknown'

