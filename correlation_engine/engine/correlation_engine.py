"""
Correlation Engine
Core engine for executing Wings and correlating feather data.
"""

import time
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, FrozenSet, Tuple
from pathlib import Path
from dataclasses import dataclass

from ..wings.core.wing_model import Wing, FeatherSpec
from .feather_loader import FeatherLoader
from .correlation_result import CorrelationResult, CorrelationMatch
from .weighted_scoring import WeightedScoringEngine
from ..config.semantic_mapping import SemanticMappingManager


@dataclass
class ProgressEvent:
    """
    Progress event emitted during correlation execution.
    
    Provides real-time feedback about correlation progress to registered listeners.
    """
    event_type: str  # "anchor_collection", "correlation_start", "anchor_progress", "summary"
    timestamp: datetime
    data: Dict[str, Any]


@dataclass
class DuplicateInfo:
    """
    Information about a duplicate match.
    
    Tracks the original match that this duplicate references.
    """
    is_duplicate: bool
    original_match_id: Optional[str]
    original_anchor_feather: Optional[str]
    original_anchor_time: Optional[datetime]
    duplicate_count: int  # How many times this pattern was seen


@dataclass(frozen=True)
class MatchSet:
    """
    Unique identifier for a correlation match with duplicate tracking.
    
    A MatchSet represents a specific combination of records from different feathers.
    Two matches are considered duplicates if they have the same anchor record AND
    the same set of non-anchor records from the same feathers.
    
    The same anchor can create multiple different matches when paired with different
    non-anchor record combinations.
    """
    anchor_feather_id: str
    anchor_record_id: str  # Using record's unique identifier (e.g., rowid or composite key)
    non_anchor_records: FrozenSet[Tuple[str, str]]  # (feather_id, record_id)
    
    # NEW: Track original match for duplicates
    original_match_id: Optional[str] = None
    is_duplicate: bool = False
    
    def to_hash(self) -> str:
        """
        Generate unique hash for this match set.
        
        Returns:
            String hash that uniquely identifies this match combination
        """
        # Sort non-anchor records for consistent hashing
        sorted_records = sorted(self.non_anchor_records)
        components = [
            self.anchor_feather_id,
            str(self.anchor_record_id),
            *[f"{fid}:{rid}" for fid, rid in sorted_records]
        ]
        return "|".join(components)


class CorrelationEngine:
    """Core correlation engine"""
    
    def __init__(self, debug_mode: bool = True):  # Changed default to True
        """
        Initialize correlation engine.
        
        Args:
            debug_mode: If True, include detailed debug logging and stack traces
        """
        self.feather_loaders: Dict[str, FeatherLoader] = {}
        self.timestamp_columns: Dict[str, str] = {}  # Cache: feather_id -> timestamp_column_name
        self.detected_columns: Dict[str, Any] = {}  # Cache: feather_id -> DetectedColumns
        self.seen_match_sets: Dict[str, str] = {}  # NEW: Track seen match sets (hash -> original_match_id)
        self.duplicate_info: Dict[str, DuplicateInfo] = {}  # NEW: Track duplicate information (match_id -> DuplicateInfo)
        self.duplicates_prevented: int = 0  # Counter for duplicate matches prevented
        self.duplicates_by_feather: Dict[str, int] = {}  # Track duplicates per feather
        self.matches_failed_validation: int = 0  # Counter for matches that failed validation
        self.debug_mode: bool = debug_mode
        self.weighted_scoring_engine = WeightedScoringEngine()  # Weighted scoring engine
        self.semantic_manager = SemanticMappingManager()  # NEW: Semantic mapping manager
        self.progress_listeners: List = []  # NEW: List of progress event listeners
        self.time_period_filter = None  # NEW: Time period filter (FilterConfig)
        
        # FORENSIC TIMESTAMP PATTERNS - Comprehensive detection for ALL artifact types
        # This ensures we NEVER skip a feather with valid timestamps
        self.forensic_timestamp_patterns = [
            # Exact matches (highest priority)
            'timestamp', 'eventtimestamputc', 'focus_time',
            # ShimCache patterns
            'last_modified', 'last_modified_readable', 'modified_time', 'modification_time',
            # AmCache patterns  
            'install_date', 'link_date', 'first_install_date', 'install_time', 'link_time',
            # LNK & Jumplist patterns (case-sensitive variations)
            'time_access', 'time_creation', 'time_modification',
            'access_time', 'creation_time', 'modification_time',
            'accessed_time', 'created_time', 'modified_time',
            # Prefetch patterns
            'last_run_time', 'execution_time', 'run_time', 'exec_time', 'last_execution',
            # SRUM patterns
            'timestamp_utc', 'sample_time', 'usage_time',
            # Registry patterns
            'last_write_time', 'key_timestamp', 'registry_time',
            # Event log patterns
            'event_time', 'log_time', 'generated_time', 'system_time',
            # MFT patterns
            'created', 'modified', 'accessed', 'mft_modified',
            'file_created', 'file_modified', 'file_accessed',
            # Generic patterns (lowest priority)
            'time', 'date', 'datetime', 'ts', 'when', 'occurred', 'happened'
        ]
        
        if self.debug_mode:
            print("[DEBUG] Correlation Engine initialized in DEBUG MODE")
            print(f"[DEBUG] Loaded {len(self.forensic_timestamp_patterns)} forensic timestamp patterns")
    
    def register_progress_listener(self, listener):
        """
        Register a progress event listener.
        
        Args:
            listener: Callable that accepts a ProgressEvent
        """
        self.progress_listeners.append(listener)
    
    def _emit_progress_event(self, event_type: str, data: Dict[str, Any]):
        """
        Emit a progress event to registered listeners.
        
        Args:
            event_type: Type of progress event
            data: Event data dictionary
        """
        event = ProgressEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            data=data
        )
        
        for listener in self.progress_listeners:
            try:
                listener(event)
            except Exception as e:
                # Log error but continue execution
                if self.debug_mode:
                    print(f"[DEBUG] Progress listener error: {str(e)}")
                # Fallback to console output
                print(f"[Progress] {event_type}: {data}")
    
    def execute_wing(self, wing: Wing, feather_paths: Dict[str, str]) -> CorrelationResult:
        """
        Execute a wing and find correlations.
        
        Args:
            wing: Wing configuration to execute
            feather_paths: Mapping of feather_id -> database_path
            
        Returns:
            CorrelationResult with matches
        """
        start_time = time.time()
        
        # Performance tracking
        phase_times = {}
        phase_start = time.time()
        
        result = CorrelationResult(
            wing_id=wing.wing_id,
            wing_name=wing.wing_name
        )
        
        try:
            # Validate configuration before execution
            validation_errors = self._validate_configuration(wing, feather_paths)
            if validation_errors:
                result.errors.extend(validation_errors)
                return result
            
            phase_times['validation'] = time.time() - phase_start
            phase_start = time.time()
            
            # Load all feathers
            self._load_feathers(wing, feather_paths, result)
            
            phase_times['loading'] = time.time() - phase_start
            phase_start = time.time()
            
            if result.errors:
                return result
            
            # Apply wing-level filters and get filtered records
            filtered_records = self._apply_filters(wing, result)
            
            phase_times['filtering'] = time.time() - phase_start
            phase_start = time.time()
            
            # Find correlations
            matches = self._correlate_records(wing, filtered_records, result)
            
            phase_times['correlation'] = time.time() - phase_start
            phase_start = time.time()
            
            # Add matches to result
            for match in matches:
                result.add_match(match)
            
            phase_times['scoring'] = time.time() - phase_start
            
            # Add duplicate prevention statistics
            result.duplicates_prevented = self.duplicates_prevented
            result.duplicates_by_feather = self.duplicates_by_feather.copy()
            result.matches_failed_validation = self.matches_failed_validation
            result.matches_failed_validation = self.matches_failed_validation
            
            # Add performance metrics
            total_time = time.time() - start_time
            result.performance_metrics = {
                'phase_times': phase_times,
                'total_time': total_time,
                'records_per_second': result.total_records_scanned / total_time if total_time > 0 else 0,
                'matches_per_second': result.total_matches / total_time if total_time > 0 else 0
            }
            
        except Exception as e:
            result.errors.append(f"Execution error: {str(e)}")
        
        finally:
            # Cleanup
            self._cleanup_loaders()
            
            # Record execution time
            result.execution_duration_seconds = time.time() - start_time
        
        return result
    
    def _validate_configuration(self, wing: Wing, feather_paths: Dict[str, str]) -> List[str]:
        """
        Validate wing configuration before execution.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        rules = wing.correlation_rules
        
        # Validate time_window_minutes > 0
        if rules.time_window_minutes <= 0:
            errors.append(
                f"Configuration error: time_window_minutes must be greater than 0 "
                f"(current value: {rules.time_window_minutes})"
            )
        
        # Validate minimum_matches >= 1
        if rules.minimum_matches < 1:
            errors.append(
                f"Configuration error: minimum_matches must be at least 1 "
                f"(current value: {rules.minimum_matches})"
            )
        
        # Validate all feather_ids have corresponding paths
        for feather_spec in wing.feathers:
            if feather_spec.feather_id not in feather_paths:
                errors.append(
                    f"Configuration error: feather_id '{feather_spec.feather_id}' "
                    f"has no corresponding database path"
                )
        
        # Validate anchor_priority list contains valid artifact types
        valid_artifact_types = {
            "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
            "Jumplists", "LNK", "MFT", "USN", "Registry", "Browser"
        }
        
        for artifact_type in rules.anchor_priority:
            if artifact_type not in valid_artifact_types:
                errors.append(
                    f"Configuration warning: anchor_priority contains unknown artifact type '{artifact_type}'. "
                    f"Valid types: {', '.join(sorted(valid_artifact_types))}"
                )
        
        # Validate minimum_matches vs available feathers
        total_feathers = len(wing.feathers)
        available_non_anchor_feathers = total_feathers - 1  # Subtract 1 for anchor
        
        if rules.minimum_matches > available_non_anchor_feathers:
            errors.append(
                f"Configuration error: minimum_matches ({rules.minimum_matches}) "
                f"exceeds available non-anchor feathers ({available_non_anchor_feathers}). "
                f"Note: The anchor feather is always included but not counted toward minimum_matches."
            )
        
        return errors
    
    def _load_feathers(self, wing: Wing, feather_paths: Dict[str, str], result: CorrelationResult):
        """Load all feather databases with enhanced error handling"""
        import sqlite3
        import traceback
        
        for feather_spec in wing.feathers:
            feather_id = feather_spec.feather_id
            
            if feather_id not in feather_paths:
                result.errors.append(
                    f"Missing path for feather: {feather_id} (artifact type: {feather_spec.artifact_type})"
                )
                continue
            
            db_path = feather_paths[feather_id]
            
            # Check if file exists
            if not Path(db_path).exists():
                result.errors.append(
                    f"Feather database not found: {db_path} (feather_id: {feather_id})"
                )
                continue
            
            try:
                loader = FeatherLoader(db_path)
                loader.connect()
                self.feather_loaders[feather_id] = loader
                result.feathers_processed += 1
                
                # Detect timestamp column for this feather
                detected_cols = loader.detect_columns()
                
                # Cache detected columns for later use
                self.detected_columns[feather_id] = detected_cols
                
                if detected_cols.timestamp_columns:
                    self.timestamp_columns[feather_id] = detected_cols.timestamp_columns[0]
                    if self.debug_mode:
                        print(f"[DEBUG] {feather_id}: Detected timestamp column = '{detected_cols.timestamp_columns[0]}'")
                        if len(detected_cols.timestamp_columns) > 1:
                            print(f"[DEBUG] {feather_id}: Additional timestamp columns: {detected_cols.timestamp_columns[1:]}")
                        print(f"[DEBUG] {feather_id}: Name columns = {detected_cols.name_columns}")
                        print(f"[DEBUG] {feather_id}: Path columns = {detected_cols.path_columns}")
                else:
                    # Fallback: look for 'timestamp' column
                    self.timestamp_columns[feather_id] = 'timestamp'
                    if self.debug_mode:
                        print(f"[DEBUG] {feather_id}: No timestamp column detected, using fallback 'timestamp'")
                
                # Collect feather metadata
                result.feather_metadata[feather_id] = {
                    'artifact_type': loader.artifact_type or feather_spec.artifact_type,
                    'database_path': db_path,
                    'total_records': loader.get_record_count(),
                    'metadata': loader.metadata,
                    'timestamp_column': self.timestamp_columns[feather_id]
                }
                
                if self.debug_mode:
                    print(f"[DEBUG] {feather_id}: Loaded {loader.get_record_count()} records, artifact_type={loader.artifact_type}")
                
                # Validate artifact type consistency
                if loader.artifact_type and loader.artifact_type != feather_spec.artifact_type:
                    result.warnings.append(
                        f"Artifact type mismatch for feather {feather_id}: "
                        f"config says '{feather_spec.artifact_type}', database says '{loader.artifact_type}'"
                    )
                
            except FileNotFoundError as e:
                result.errors.append(
                    f"Feather database file not found: {db_path} (feather_id: {feather_id})"
                )
                # Non-critical: continue with other feathers
                
            except sqlite3.DatabaseError as e:
                result.errors.append(
                    f"Database corrupted or invalid: {db_path} (feather_id: {feather_id}) - {str(e)}"
                )
                # Non-critical: continue with other feathers
                
            except Exception as e:
                error_msg = f"Failed to load feather {feather_id} from {db_path}: {str(e)}"
                result.errors.append(error_msg)
                
                # Add stack trace in debug mode (check if debug attribute exists)
                if hasattr(self, 'debug_mode') and self.debug_mode:
                    result.errors.append(f"Stack trace:\n{traceback.format_exc()}")
                
                # Non-critical: continue with other feathers
    
    def _apply_filters(self, wing: Wing, result: CorrelationResult) -> Dict[str, List[Dict[str, Any]]]:
        """
        Apply wing-level filters to all feathers with statistics tracking.
        
        Returns:
            Dictionary of feather_id -> filtered records
        """
        filtered_records = {}
        rules = wing.correlation_rules
        
        # Build filter parameters
        filters = {}
        if rules.apply_to == "specific" and rules.target_application:
            filters['application'] = rules.target_application
            result.filters_applied['application'] = rules.target_application
        
        if rules.target_file_path:
            filters['file_path'] = rules.target_file_path
            result.filters_applied['file_path'] = rules.target_file_path
        
        if rules.target_event_id:
            filters['event_id'] = rules.target_event_id
            result.filters_applied['event_id'] = rules.target_event_id
        
        # Apply filters to each feather
        for feather_spec in wing.feathers:
            feather_id = feather_spec.feather_id
            
            if feather_id not in self.feather_loaders:
                continue
            
            loader = self.feather_loaders[feather_id]
            
            try:
                # Get total record count before filtering
                records_before = loader.get_record_count()
                
                # Get filtered records
                if filters:
                    records = loader.get_records_by_filters(
                        application=filters.get('application'),
                        file_path=filters.get('file_path'),
                        event_id=filters.get('event_id')
                    )
                else:
                    records = loader.get_all_records()
                
                # Expand records with multiple timestamps
                records = self._expand_multi_timestamp_records(records, feather_id)
                
                # NEW: Apply time period filter if configured
                if hasattr(self, 'time_period_filter') and self.time_period_filter:
                    records = self._apply_time_period_filter(records, feather_id)
                
                records_after = len(records)
                
                # Track filter statistics
                result.filter_statistics[feather_id] = {
                    'before': records_before,
                    'after': records_after,
                    'filtered_out': records_before - records_after
                }
                
                # Log warning if all records were filtered out
                if records_before > 0 and records_after == 0:
                    result.warnings.append(
                        f"Filters eliminated all {records_before} records from feather {feather_id}"
                    )
                
                filtered_records[feather_id] = records
                result.total_records_scanned += records_after
                
            except Exception as e:
                result.warnings.append(f"Error filtering feather {feather_id}: {str(e)}")
                filtered_records[feather_id] = []
        
        return filtered_records
    
    def _correlate_records(self, wing: Wing, 
                          filtered_records: Dict[str, List[Dict[str, Any]]],
                          result: CorrelationResult) -> List[CorrelationMatch]:
        """
        Correlate records across feathers based on time proximity.
        
        NEW STRATEGY: Collect ALL anchors from ALL feathers in the wing first,
        then match them together based on time proximity.
        
        Returns:
            List of correlation matches
        """
        matches = []
        rules = wing.correlation_rules
        
        # Reset duplicate tracking for this execution
        self.seen_match_sets.clear()
        self.duplicates_prevented = 0
        self.matches_failed_validation = 0
        
        # Configurable limit to prevent combinatorial explosion
        max_matches_per_anchor = 100
        matches_limited_count = 0
        
        # STEP 1: Collect ALL anchors from ALL feathers in the wing
        print(f"\n[Correlation] Collecting anchors from all feathers in wing...")
        print(f"[Correlation] Wing: {wing.wing_name} (ID: {wing.wing_id})")
        print(f"[Correlation] Feathers in wing: {len(filtered_records)}")
        
        # Emit wing start event
        self._emit_progress_event("wing_start", {
            'wing_name': wing.wing_name,
            'wing_id': wing.wing_id,
            'feather_count': len(filtered_records)
        })
        
        all_anchors = []
        anchors_per_feather = {}  # Track anchors per feather
        
        for feather_id, records in filtered_records.items():
            if not records:
                continue
            
            artifact_type = self._get_artifact_type(wing, feather_id)
            
            # FORENSIC TIMESTAMP DETECTION - Never skip a feather with valid timestamps!
            timestamp_columns = self._detect_forensic_timestamp_columns(feather_id, records)
            
            if not timestamp_columns:
                print(f"[Correlation]   • {feather_id} ({artifact_type}): 0 anchors (no valid timestamp columns)")
                anchors_per_feather[feather_id] = 0
                self._emit_progress_event("anchor_collection", {
                    'feather_id': feather_id,
                    'artifact_type': artifact_type,
                    'anchor_count': 0
                })
                continue
            
            # Use the best timestamp column found
            primary_timestamp_col = timestamp_columns[0]
            self.timestamp_columns[feather_id] = primary_timestamp_col
            
            feather_anchor_count = 0
            invalid_timestamps = 0
            
            for record in records:
                # Try primary timestamp column first, then fall back to alternatives
                anchor_time = None
                timestamp_col_used = None
                
                for timestamp_col in timestamp_columns:
                    if timestamp_col in record and record[timestamp_col]:
                        anchor_time = self._parse_timestamp(record.get(timestamp_col))
                        if anchor_time:
                            timestamp_col_used = timestamp_col
                            break
                        else:
                            invalid_timestamps += 1
                
                if anchor_time:
                    all_anchors.append({
                        'feather_id': feather_id,
                        'artifact_type': artifact_type,
                        'record': record,
                        'timestamp': anchor_time,
                        'timestamp_col': timestamp_col_used
                    })
                    feather_anchor_count += 1
            
            anchors_per_feather[feather_id] = feather_anchor_count
            
            # Enhanced logging for forensic audit trail
            if feather_anchor_count > 0:
                print(f"[Correlation]   • {feather_id} ({artifact_type}): {feather_anchor_count} anchors (using {primary_timestamp_col})")
                if invalid_timestamps > 0:
                    print(f"[Correlation]     └─ Filtered {invalid_timestamps} invalid timestamps")
            else:
                print(f"[Correlation]   • {feather_id} ({artifact_type}): 0 anchors (all timestamps invalid)")
            
            # Emit anchor collection event
            self._emit_progress_event("anchor_collection", {
                'feather_id': feather_id,
                'artifact_type': artifact_type,
                'anchor_count': feather_anchor_count,
                'timestamp_column': primary_timestamp_col,
                'invalid_timestamps': invalid_timestamps
            })
        
        # Sort anchors by timestamp for efficient processing
        all_anchors.sort(key=lambda x: x['timestamp'])
        
        total_anchors = len(all_anchors)
        print(f"[Correlation] Total anchors collected: {total_anchors}")
        print(f"[Correlation] Time window: {rules.time_window_minutes} minutes")
        print(f"[Correlation] Minimum matches required: {rules.minimum_matches}")
        print(f"[Correlation] Starting correlation analysis...")
        
        # Emit correlation start event
        self._emit_progress_event("correlation_start", {
            'total_anchors': total_anchors,
            'time_window': rules.time_window_minutes,
            'minimum_matches': rules.minimum_matches
        })
        
        if total_anchors == 0:
            result.warnings.append("No valid anchors found in any feather")
            return matches
        
        # STEP 2: For each anchor, find matching records from OTHER feathers
        invalid_timestamps_count = 0
        PROGRESS_INTERVAL = 1000
        
        if self.debug_mode:
            print(f"[DEBUG] Starting correlation with {total_anchors} total anchors")
            print(f"[DEBUG] Time window: {rules.time_window_minutes} minutes")
            print(f"[DEBUG] Minimum matches required: {rules.minimum_matches}")
        
        for anchor_index, anchor_data in enumerate(all_anchors):
            # Progress tracking
            if anchor_index > 0 and anchor_index % PROGRESS_INTERVAL == 0:
                print(f"    Progress: {anchor_index}/{total_anchors} anchors processed, {len(matches)} matches found")
                # Emit summary progress event
                self._emit_progress_event("summary_progress", {
                    'anchors_processed': anchor_index,
                    'total_anchors': total_anchors,
                    'matches_found': len(matches)
                })
            
            anchor_feather_id = anchor_data['feather_id']
            anchor_record = anchor_data['record']
            anchor_time = anchor_data['timestamp']
            anchor_artifact_type = anchor_data['artifact_type']
            timestamp_col = anchor_data['timestamp_col']
            
            # Debug first few anchor records
            if self.debug_mode and anchor_index < 3:
                print(f"[DEBUG] Anchor {anchor_index}: feather={anchor_feather_id}, time={anchor_time}, data={str(anchor_record)[:100]}...")
            
            # Generate unique identifier for anchor record
            # IMPORTANT: Include timestamp to make multi-timestamp records unique
            # This prevents false duplicates when same record has multiple timestamps
            timestamp_value = anchor_record.get(timestamp_col, '')
            timestamp_str = str(anchor_time) if anchor_time else str(timestamp_value)
            
            if anchor_record.get('rowid'):
                # Use rowid + timestamp for uniqueness
                anchor_record_id = f"{anchor_record.get('rowid')}_{timestamp_str}"
            else:
                # Fallback: composite key with timestamp
                anchor_record_id = f"{timestamp_str}_{anchor_record.get('application', '')}_{anchor_record.get('file_path', '')}"
            
            # Generate all valid match combinations for this anchor
            match_combinations = self._generate_match_combinations(
                anchor_record,
                anchor_feather_id,
                anchor_time,
                filtered_records,
                rules.time_window_minutes,
                rules.minimum_matches,
                max_matches_per_anchor
            )
            
            if self.debug_mode and anchor_index < 3:
                print(f"[DEBUG] Anchor {anchor_index}: Generated {len(match_combinations)} match combinations")
            
            # Track if we hit the limit for this anchor
            if len(match_combinations) >= max_matches_per_anchor:
                matches_limited_count += 1
            
            # Emit anchor progress event (GUI will display this)
            if anchor_index % 100 == 0:
                self._emit_progress_event("anchor_progress", {
                    'anchor_index': anchor_index,
                    'total_anchors': total_anchors,
                    'feather_id': anchor_feather_id,
                    'artifact_type': anchor_artifact_type,
                    'timestamp': str(anchor_time)
                })
            
            # Process each match combination
            for match_records in match_combinations:
                # Validate time window for all records (bidirectional validation)
                is_valid, validated_records = self._validate_time_window(
                    match_records,
                    anchor_feather_id,
                    anchor_time,
                    rules.time_window_minutes
                )
                
                # If validation removed records, check if we still meet minimum matches
                # NOTE: minimum_matches counts ONLY non-anchor feathers
                non_anchor_count = len(validated_records) - 1  # Subtract 1 for anchor
                if non_anchor_count < rules.minimum_matches:
                    # Match no longer meets threshold after validation
                    self.matches_failed_validation += 1
                    continue
                
                # Use validated records for the match
                match_records = validated_records
                
                # Create MatchSet for duplicate detection
                non_anchor_records = []
                for fid, record in match_records.items():
                    if fid != anchor_feather_id:
                        # IMPORTANT: Include timestamp to make multi-timestamp records unique
                        # This prevents false duplicates when same record has multiple timestamps
                        record_timestamp = str(record.get('timestamp', ''))
                        
                        if record.get('rowid'):
                            # Use rowid + timestamp for uniqueness
                            record_id = f"{record.get('rowid')}_{record_timestamp}"
                        else:
                            # Fallback: composite key with timestamp
                            record_id = f"{record_timestamp}_{record.get('application', '')}_{record.get('file_path', '')}"
                        
                        non_anchor_records.append((fid, record_id))
                
                match_set = MatchSet(
                    anchor_feather_id=anchor_feather_id,
                    anchor_record_id=anchor_record_id,
                    non_anchor_records=frozenset(non_anchor_records)
                )
                
                # Check for duplicate
                match_hash = match_set.to_hash()
                if match_hash in self.seen_match_sets:
                    # Duplicate detected - get original match ID
                    original_match_id = self.seen_match_sets[match_hash]
                    self.duplicates_prevented += 1
                    if anchor_feather_id not in self.duplicates_by_feather:
                        self.duplicates_by_feather[anchor_feather_id] = 0
                    self.duplicates_by_feather[anchor_feather_id] += 1
                    
                    # Create match but mark as duplicate
                    match = self._create_match(
                        match_records,
                        anchor_feather_id,
                        anchor_artifact_type,
                        anchor_time,
                        wing
                    )
                    
                    # Add duplicate information
                    match.is_duplicate = True
                    match.duplicate_info = DuplicateInfo(
                        is_duplicate=True,
                        original_match_id=original_match_id,
                        original_anchor_feather=anchor_feather_id,
                        original_anchor_time=anchor_time,
                        duplicate_count=self.duplicates_by_feather[anchor_feather_id]
                    )
                    
                    # Store duplicate info
                    self.duplicate_info[match.match_id] = match.duplicate_info
                    
                    # Still add to matches for tracking, but marked as duplicate
                    matches.append(match)
                    continue
                
                # Not a duplicate - create match and store as original
                match = self._create_match(
                    match_records,
                    anchor_feather_id,
                    anchor_artifact_type,
                    anchor_time,
                    wing
                )
                
                # Store this as the original match for this hash
                self.seen_match_sets[match_hash] = match.match_id
                
                # Validate match integrity
                is_valid, validation_errors = self._validate_match_integrity(match, wing)
                if not is_valid:
                    # Log validation failures and exclude invalid match
                    for error in validation_errors:
                        result.warnings.append(f"Match integrity validation failed: {error}")
                    continue
                
                matches.append(match)
        
        # Log statistics
        if self.debug_mode:
            print(f"[DEBUG] Correlation complete:")
            print(f"[DEBUG]   - Total anchor records: {total_anchors}")
            print(f"[DEBUG]   - Invalid timestamps: {invalid_timestamps_count}")
            print(f"[DEBUG]   - Matches found: {len(matches)}")
            print(f"[DEBUG]   - Duplicates prevented: {self.duplicates_prevented}")
            if self.duplicates_by_feather:
                print(f"[DEBUG]   - Duplicates by feather:")
                for feather_id, count in sorted(self.duplicates_by_feather.items()):
                    print(f"[DEBUG]     • {feather_id}: {count} duplicates")
        
        if invalid_timestamps_count > 0:
            result.warnings.append(
                f"Skipped {invalid_timestamps_count} anchor records with invalid timestamps"
            )
        
        if self.duplicates_prevented > 0:
            dup_summary = f"Prevented {self.duplicates_prevented} duplicate matches"
            if self.duplicates_by_feather:
                dup_details = ", ".join([f"{fid}: {count}" for fid, count in sorted(self.duplicates_by_feather.items())])
                dup_summary += f" ({dup_details})"
            result.warnings.append(dup_summary)
        
        if self.matches_failed_validation > 0:
            result.warnings.append(
                f"{self.matches_failed_validation} matches failed time window validation"
            )
        
        if matches_limited_count > 0:
            result.warnings.append(
                f"Match limit ({max_matches_per_anchor} per anchor) reached for {matches_limited_count} anchor records"
            )
        
        return matches
    
    def _get_field_value(self, record: Dict[str, Any], feather_id: str, field_type: str) -> Optional[str]:
        """
        Extract field value from record using detected columns.
        
        Args:
            record: Record dictionary
            feather_id: ID of the feather this record came from
            field_type: Type of field to extract ('name' or 'path')
            
        Returns:
            Field value or None if not found
        """
        if feather_id not in self.detected_columns:
            # Fallback to hardcoded field names if columns not detected
            if field_type == 'name':
                for field in ['application', 'app_name', 'executable_name', 'filename', 'name', 'executable', 'process_name']:
                    if field in record and record.get(field):
                        return record.get(field)
            elif field_type == 'path':
                for field in ['file_path', 'path', 'full_path', 'filepath', 'full_file_path', 'exe_path', 'executable_path']:
                    if field in record and record.get(field):
                        return record.get(field)
            return None
        
        detected_cols = self.detected_columns[feather_id]
        
        # Use detected columns
        if field_type == 'name':
            for col_name in detected_cols.name_columns:
                if col_name in record and record.get(col_name):
                    return record.get(col_name)
        elif field_type == 'path':
            for col_name in detected_cols.path_columns:
                if col_name in record and record.get(col_name):
                    return record.get(col_name)
        
        return None
    
    def _select_anchor_feather(self, wing: Wing, 
                               filtered_records: Dict[str, List[Dict[str, Any]]]) -> Tuple[Optional[str], str]:
        """
        Select anchor feather based on priority with validation and logging.
        
        Returns:
            Tuple of (anchor_feather_id, selection_reason)
        """
        rules = wing.correlation_rules
        
        # Find feathers with records
        available_feathers = {fid: records for fid, records in filtered_records.items() if records}
        
        if not available_feathers:
            return None, "No feathers have records after filtering"
        
        # Check for manual override
        if rules.anchor_feather_override:
            if rules.anchor_feather_override in available_feathers:
                return rules.anchor_feather_override, f"Manual override: {rules.anchor_feather_override}"
            else:
                # Override specified but feather not available - log warning and fall through
                reason = f"Manual override {rules.anchor_feather_override} not available, using priority selection"
        
        # Select based on anchor priority
        for artifact_type in rules.anchor_priority:
            for feather_spec in wing.feathers:
                if (feather_spec.artifact_type == artifact_type and 
                    feather_spec.feather_id in available_feathers):
                    record_count = len(available_feathers[feather_spec.feather_id])
                    return feather_spec.feather_id, f"Priority selection: {artifact_type} ({record_count} records)"
        
        # Fallback to first available feather
        fallback_id = list(available_feathers.keys())[0]
        record_count = len(available_feathers[fallback_id])
        return fallback_id, f"Fallback selection: {fallback_id} ({record_count} records)"
    
    def _get_artifact_type(self, wing: Wing, feather_id: str) -> str:
        """Get artifact type for a feather"""
        for feather_spec in wing.feathers:
            if feather_spec.feather_id == feather_id:
                return feather_spec.artifact_type
        return "Unknown"
    
    def _detect_forensic_timestamp_columns(self, feather_id: str, records: List[Dict[str, Any]]) -> List[str]:
        """
        FORENSIC-GRADE timestamp column detection.
        
        NEVER skips a feather with valid timestamps - this is forensically critical!
        Detects timestamp columns using comprehensive pattern matching and validates
        actual data to ensure timestamps are parseable.
        
        Args:
            feather_id: Feather identifier
            records: Sample records to analyze
            
        Returns:
            List of valid timestamp column names (prioritized by quality)
        """
        if not records:
            return []
        
        sample_record = records[0]
        available_columns = list(sample_record.keys())
        
        if self.debug_mode:
            print(f"[DEBUG] {feather_id}: Analyzing {len(available_columns)} columns for timestamps")
        
        # Find potential timestamp columns using forensic patterns
        potential_columns = []
        for pattern in self.forensic_timestamp_patterns:
            for col_name in available_columns:
                # Case-insensitive pattern matching
                if pattern.lower() in col_name.lower():
                    potential_columns.append((col_name, pattern))
                    break  # Found match for this pattern, move to next
        
        if self.debug_mode and potential_columns:
            print(f"[DEBUG] {feather_id}: Found {len(potential_columns)} potential timestamp columns")
            for col_name, pattern in potential_columns[:5]:  # Show first 5
                print(f"[DEBUG] {feather_id}:   • {col_name} (matched pattern: {pattern})")
        
        # Validate each potential column by checking actual data
        valid_columns = []
        for col_name, pattern in potential_columns:
            valid_count = 0
            total_checked = 0
            
            # Check up to 100 records for valid timestamps
            for record in records[:100]:
                if col_name in record and record[col_name]:
                    total_checked += 1
                    timestamp_str = str(record[col_name])
                    if self._parse_timestamp(timestamp_str):
                        valid_count += 1
            
            if valid_count > 0:
                percentage = (valid_count / total_checked * 100) if total_checked > 0 else 0
                valid_columns.append((col_name, valid_count, total_checked, percentage))
                
                if self.debug_mode:
                    print(f"[DEBUG] {feather_id}: ✅ {col_name} has {valid_count}/{total_checked} valid timestamps ({percentage:.1f}%)")
        
        if not valid_columns:
            if self.debug_mode:
                print(f"[DEBUG] {feather_id}: ❌ No valid timestamp columns found")
            return []
        
        # Sort by percentage of valid timestamps (best first)
        valid_columns.sort(key=lambda x: x[3], reverse=True)
        
        # Return column names in priority order
        result = [col[0] for col in valid_columns]
        
        if self.debug_mode:
            best_col, best_valid, best_total, best_pct = valid_columns[0]
            print(f"[DEBUG] {feather_id}: 🎯 Selected '{best_col}' as primary timestamp column ({best_valid}/{best_total} valid, {best_pct:.1f}%)")
            if len(valid_columns) > 1:
                print(f"[DEBUG] {feather_id}: 📋 {len(valid_columns)-1} backup timestamp columns available")
        
        return result
    
    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """
        Parse timestamp string to datetime with comprehensive format support.
        
        Supports multiple timestamp formats commonly found in forensic artifacts:
        - ISO 8601 formats (with/without timezone)
        - Standard datetime formats
        - Unix timestamps (seconds/milliseconds)
        - Windows FILETIME (if numeric and very large)
        
        Validates:
        - NULL/empty values
        - Valid datetime parsing
        - Reasonable range (1970-2100)
        
        Args:
            timestamp_str: Timestamp string to parse
            
        Returns:
            Parsed datetime or None if invalid
        """
        # Validate NULL/empty
        if not timestamp_str:
            return None
        
        # Convert to string if not already
        timestamp_str = str(timestamp_str).strip()
        
        if not timestamp_str or timestamp_str.lower() in ('none', 'null', 'n/a', ''):
            return None
        
        parsed_time = None
        
        # Try numeric timestamps (Unix epoch or Windows FILETIME)
        try:
            numeric_value = float(timestamp_str)
            
            # Windows FILETIME (100-nanosecond intervals since 1601-01-01)
            if numeric_value > 10000000000000:  # Very large number
                # Convert FILETIME to Unix timestamp
                unix_timestamp = (numeric_value - 116444736000000000) / 10000000
                parsed_time = datetime.fromtimestamp(unix_timestamp)
            # Unix timestamp in milliseconds
            elif numeric_value > 10000000000:  # Likely milliseconds
                parsed_time = datetime.fromtimestamp(numeric_value / 1000)
            # Unix timestamp in seconds
            elif numeric_value > 0:
                parsed_time = datetime.fromtimestamp(numeric_value)
            
            if parsed_time:
                # Validate range before returning
                if 1970 <= parsed_time.year <= 2100:
                    return parsed_time
                else:
                    parsed_time = None
        except (ValueError, OSError, OverflowError):
            pass  # Not a numeric timestamp, try string formats
        
        # Try ISO format variations
        try:
            # Handle 'Z' timezone indicator
            parsed_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            try:
                # Try without timezone
                parsed_time = datetime.fromisoformat(timestamp_str)
            except:
                pass
        
        # Try common datetime formats
        if not parsed_time:
            formats_to_try = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%m-%d-%Y",
                "%Y%m%d%H%M%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%a %b %d %H:%M:%S %Y",  # "Mon Jan 01 12:00:00 2024"
            ]
            
            for fmt in formats_to_try:
                try:
                    parsed_time = datetime.strptime(timestamp_str, fmt)
                    break
                except:
                    continue
        
        # Validate parsed datetime
        if not isinstance(parsed_time, datetime):
            return None
        
        # Validate reasonable range (1970-2100)
        min_year = 1970
        max_year = 2100
        
        if parsed_time.year < min_year or parsed_time.year > max_year:
            # Timestamp out of reasonable range
            return None
        
        return parsed_time
    
    def _get_record_timestamp(self, record: Dict[str, Any], feather_id: str) -> Optional[str]:
        """
        Get timestamp value from a record using the detected timestamp column.
        
        Args:
            record: Record dictionary
            feather_id: ID of the feather this record came from
            
        Returns:
            Timestamp string or None
        """
        timestamp_col = self.timestamp_columns.get(feather_id, 'timestamp')
        return record.get(timestamp_col)
    
    def _expand_multi_timestamp_records(self, records: List[Dict[str, Any]], feather_id: str) -> List[Dict[str, Any]]:
        """
        Expand records that contain multiple timestamps into separate records.
        
        For forensic accuracy, records with timestamp arrays (like Prefetch run_times)
        should be expanded so each timestamp can be correlated independently.
        
        Args:
            records: List of records
            feather_id: ID of the feather
            
        Returns:
            Expanded list of records (one per timestamp)
        """
        import json
        
        expanded_records = []
        timestamp_col = self.timestamp_columns.get(feather_id, 'timestamp')
        
        for record in records:
            timestamp_value = record.get(timestamp_col)
            
            # Check if timestamp is a JSON array
            if timestamp_value and isinstance(timestamp_value, str) and timestamp_value.strip().startswith('['):
                try:
                    # Parse JSON array
                    timestamps = json.loads(timestamp_value)
                    
                    if isinstance(timestamps, list) and timestamps:
                        # Create a separate record for each timestamp
                        for ts in timestamps:
                            if ts:  # Skip empty timestamps
                                expanded_record = record.copy()
                                expanded_record[timestamp_col] = ts
                                # Add metadata to track this is an expanded record
                                expanded_record['_expanded_from_array'] = True
                                expanded_record['_original_timestamp_array'] = timestamp_value
                                expanded_records.append(expanded_record)
                    else:
                        # Empty array or not a list - keep original
                        expanded_records.append(record)
                except (json.JSONDecodeError, ValueError):
                    # Not valid JSON - keep original
                    expanded_records.append(record)
            else:
                # Single timestamp - keep as is
                expanded_records.append(record)
        
        # Log expansion statistics
        if len(expanded_records) > len(records):
            expansion_ratio = len(expanded_records) / len(records) if records else 0
            print(f"    [Timestamp Expansion] {feather_id}: {len(records)} → {len(expanded_records)} records ({expansion_ratio:.1f}x)")
            
            if self.debug_mode:
                # Show sample of expanded records
                sample_original = [r for r in records if r.get(timestamp_col, '').strip().startswith('[')][:2]
                for orig in sample_original:
                    print(f"[DEBUG] Sample expansion for {feather_id}:")
                    print(f"[DEBUG]   Original: {orig.get(timestamp_col)[:100]}...")
                    expanded_count = len([r for r in expanded_records if r.get('_original_timestamp_array') == orig.get(timestamp_col)])
                    print(f"[DEBUG]   Expanded to: {expanded_count} records")
        
        return expanded_records
    
    def _apply_time_period_filter(self, records: List[Dict[str, Any]], feather_id: str) -> List[Dict[str, Any]]:
        """
        Apply time period filter to records.
        
        Filters records to only include those within the configured time period.
        
        Args:
            records: List of records to filter
            feather_id: ID of the feather (for timestamp column detection)
            
        Returns:
            Filtered list of records
        """
        if not self.time_period_filter:
            return records
        
        filtered = []
        skipped_invalid = 0
        skipped_before_start = 0
        skipped_after_end = 0
        
        for record in records:
            # Get timestamp using detected column
            timestamp_str = self._get_record_timestamp(record, feather_id)
            timestamp = self._parse_timestamp(timestamp_str)
            
            if not timestamp:
                skipped_invalid += 1
                continue
            
            # Check start time
            if self.time_period_filter.time_period_start and timestamp < self.time_period_filter.time_period_start:
                skipped_before_start += 1
                continue
            
            # Check end time
            if self.time_period_filter.time_period_end and timestamp > self.time_period_filter.time_period_end:
                skipped_after_end += 1
                continue
            
            filtered.append(record)
        
        # Log filter statistics
        if len(filtered) < len(records):
            print(f"    [Time Period Filter] {feather_id}: {len(records)} → {len(filtered)} records")
            if skipped_invalid > 0:
                print(f"      • Skipped {skipped_invalid} records with invalid timestamps")
            if skipped_before_start > 0:
                print(f"      • Skipped {skipped_before_start} records before start time")
            if skipped_after_end > 0:
                print(f"      • Skipped {skipped_after_end} records after end time")
        
        return filtered
    
    def _find_closest_record(self, anchor_time: datetime, 
                            records: List[Dict[str, Any]], 
                            time_window_minutes: int) -> Optional[Dict[str, Any]]:
        """
        Find the closest record within time window.
        
        Note: This method is kept for backward compatibility but is being replaced
        by _find_all_records_in_window for complete time window correlation.
        """
        time_window = timedelta(minutes=time_window_minutes)
        closest_record = None
        min_diff = None
        
        for record in records:
            record_time = self._parse_timestamp(record.get('timestamp'))
            
            if not record_time:
                continue
            
            time_diff = abs((record_time - anchor_time).total_seconds())
            
            # Check if within window
            if time_diff <= time_window.total_seconds():
                if min_diff is None or time_diff < min_diff:
                    min_diff = time_diff
                    closest_record = record
        
        return closest_record
    
    def _find_all_records_in_window(self, anchor_time: datetime,
                                    records: List[Dict[str, Any]],
                                    time_window_minutes: int,
                                    feather_id: str = None) -> List[Tuple[Dict[str, Any], float]]:
        """
        Find all records within the time window, sorted by proximity to anchor.
        
        Args:
            anchor_time: The anchor timestamp
            records: List of records to search
            time_window_minutes: Time window in minutes
            feather_id: ID of the feather (for timestamp column detection)
            
        Returns:
            List of tuples (record, time_diff_seconds) sorted by proximity
        """
        time_window = timedelta(minutes=time_window_minutes)
        candidates = []
        
        for record in records:
            # Get timestamp using detected column
            timestamp_str = self._get_record_timestamp(record, feather_id) if feather_id else record.get('timestamp')
            record_time = self._parse_timestamp(timestamp_str)
            
            if not record_time:
                continue
            
            time_diff = abs((record_time - anchor_time).total_seconds())
            
            # Check if within window
            if time_diff <= time_window.total_seconds():
                candidates.append((record, time_diff))
        
        # Sort by time proximity (closest first)
        candidates.sort(key=lambda x: x[1])
        
        return candidates
    
    def _generate_match_combinations(self, anchor_record: Dict[str, Any],
                                    anchor_feather_id: str,
                                    anchor_time: datetime,
                                    filtered_records: Dict[str, List[Dict[str, Any]]],
                                    time_window_minutes: int,
                                    minimum_matches: int,
                                    max_matches_per_anchor: int = 100) -> List[Dict[str, Dict[str, Any]]]:
        """
        Generate all valid match combinations from candidate records within time window.
        
        Args:
            anchor_record: The anchor record
            anchor_feather_id: ID of the anchor feather
            anchor_time: Timestamp of the anchor record
            filtered_records: All filtered records by feather
            time_window_minutes: Time window in minutes
            minimum_matches: Minimum number of NON-ANCHOR feathers required
                           (anchor is always included but NOT counted toward this threshold)
            max_matches_per_anchor: Maximum matches to generate per anchor (default 100)
            
        Returns:
            List of match record dictionaries (feather_id -> record)
        """
        # Find all candidate records within time window for each non-anchor feather
        candidates_by_feather = {}
        
        for feather_id, records in filtered_records.items():
            if feather_id == anchor_feather_id:
                continue
            
            # Get all records within time window, sorted by proximity
            candidates = self._find_all_records_in_window(
                anchor_time,
                records,
                time_window_minutes,
                feather_id  # Pass feather_id for timestamp column detection
            )
            
            if candidates:
                # Store just the records (without time diff) for combination generation
                candidates_by_feather[feather_id] = [rec for rec, _ in candidates]
        
        # Generate match combinations
        # For now, we'll use a simple approach: take the closest record from each feather
        # This avoids combinatorial explosion while still finding all unique matches
        
        matches = []
        
        # Strategy 1: Best match (closest from each feather)
        best_match = {anchor_feather_id: anchor_record}
        for feather_id, candidate_records in candidates_by_feather.items():
            if candidate_records:
                best_match[feather_id] = candidate_records[0]  # Closest record
        
        # Check if best match meets minimum threshold
        # NOTE: minimum_matches counts ONLY non-anchor feathers
        # The anchor is always included but not counted
        non_anchor_count = len(best_match) - 1  # Subtract 1 for anchor
        if non_anchor_count >= minimum_matches:
            matches.append(best_match)
        
        # Strategy 2: If there are multiple candidates in any feather, create additional matches
        # This handles cases where multiple records from the same feather are equally valid
        # We limit this to prevent combinatorial explosion
        
        if len(matches) < max_matches_per_anchor:
            # For each feather with multiple candidates, try creating alternate matches
            for feather_id, candidate_records in candidates_by_feather.items():
                if len(candidate_records) > 1:
                    # Try each candidate record from this feather
                    for i, alt_record in enumerate(candidate_records[1:], start=1):
                        if len(matches) >= max_matches_per_anchor:
                            break
                        
                        # Create alternate match with this record
                        alt_match = {anchor_feather_id: anchor_record}
                        for other_fid, other_candidates in candidates_by_feather.items():
                            if other_fid == feather_id:
                                alt_match[other_fid] = alt_record
                            elif other_candidates:
                                alt_match[other_fid] = other_candidates[0]
                        
                        # Check if this creates a valid match
                        # NOTE: minimum_matches counts ONLY non-anchor feathers
                        non_anchor_count = len(alt_match) - 1  # Subtract 1 for anchor
                        if non_anchor_count >= minimum_matches:
                            matches.append(alt_match)
        
        return matches[:max_matches_per_anchor]  # Enforce limit
    
    def _calculate_enhanced_score(self, match_records: Dict[str, Dict[str, Any]],
                                 anchor_time: datetime,
                                 time_window_minutes: int,
                                 total_feathers: int) -> Tuple[float, Dict[str, float]]:
        """
        Calculate enhanced composite match score with breakdown.
        
        Formula:
            Match_Score = (0.4 × Coverage) + (0.3 × Time_Proximity) + (0.3 × Field_Similarity)
        
        Args:
            match_records: Dictionary of feather_id -> record
            anchor_time: Anchor timestamp
            time_window_minutes: Time window in minutes
            total_feathers: Total number of feathers in wing
            
        Returns:
            Tuple of (final_score, score_breakdown_dict)
        """
        import math
        
        feather_count = len(match_records)
        
        # Component 1: Coverage Score (40% weight)
        # Measures how many feathers participated in the match
        coverage_score = feather_count / total_feathers if total_feathers > 0 else 0.0
        
        # Component 2: Time Proximity Score (30% weight)
        # Uses inverse exponential decay - tighter clustering = higher score
        timestamps = []
        for record in match_records.values():
            ts = self._parse_timestamp(record.get('timestamp'))
            if ts:
                timestamps.append(ts)
        
        if len(timestamps) > 1:
            time_spread = (max(timestamps) - min(timestamps)).total_seconds()
        else:
            time_spread = 0.0
        
        # Convert time window to seconds
        time_window_seconds = time_window_minutes * 60
        
        # Exponential decay: exp(-time_spread / time_window)
        # When time_spread = 0, score = 1.0
        # When time_spread = time_window, score ≈ 0.37
        if time_window_seconds > 0:
            time_proximity_score = math.exp(-time_spread / time_window_seconds)
        else:
            time_proximity_score = 1.0
        
        # Component 3: Field Similarity Score (30% weight)
        # Compares application names and file paths across feathers
        applications = []
        file_paths = []
        
        for record in match_records.values():
            app = record.get('application')
            path = record.get('file_path')
            if app:
                applications.append(app.lower())  # Case-insensitive comparison
            if path:
                file_paths.append(path.lower())
        
        # Count exact matches
        app_matches = 0
        path_matches = 0
        
        if applications:
            # Most common application
            most_common_app = max(set(applications), key=applications.count)
            app_matches = applications.count(most_common_app)
        
        if file_paths:
            # Most common file path
            most_common_path = max(set(file_paths), key=file_paths.count)
            path_matches = file_paths.count(most_common_path)
        
        # Calculate field similarity
        # (app_matches + path_matches) / (2 × feather_count)
        total_possible_matches = 2 * feather_count  # 2 fields × feather_count
        actual_matches = app_matches + path_matches
        field_similarity_score = actual_matches / total_possible_matches if total_possible_matches > 0 else 0.0
        
        # Calculate weighted composite score
        final_score = (
            0.4 * coverage_score +
            0.3 * time_proximity_score +
            0.3 * field_similarity_score
        )
        
        # Ensure score is in valid range
        final_score = max(0.0, min(1.0, final_score))
        
        # Create breakdown dictionary
        breakdown = {
            'coverage': round(coverage_score, 4),
            'time_proximity': round(time_proximity_score, 4),
            'field_similarity': round(field_similarity_score, 4)
        }
        
        return final_score, breakdown
    
    def _calculate_confidence_score(self, match_records: Dict[str, Dict[str, Any]],
                                    time_window_minutes: int,
                                    time_spread_seconds: float) -> Tuple[float, str]:
        """
        Calculate confidence score and category for a match.
        
        Formula:
            Confidence_Score = (0.5 × Time_Tightness) + (0.5 × Field_Consistency)
            Time_Tightness = 1.0 - (time_spread / time_window)
            Field_Consistency = matching_fields / total_comparable_fields
        
        Categories:
            High: > 0.8
            Medium: 0.5 - 0.8
            Low: < 0.5
        
        Args:
            match_records: Dictionary of feather_id -> record
            time_window_minutes: Time window in minutes
            time_spread_seconds: Time spread of the match in seconds
            
        Returns:
            Tuple of (confidence_score, confidence_category)
        """
        feather_count = len(match_records)
        
        # Component 1: Time Tightness (50% weight)
        # Tighter time clustering = higher confidence
        time_window_seconds = time_window_minutes * 60
        if time_window_seconds > 0:
            time_tightness = 1.0 - (time_spread_seconds / time_window_seconds)
            time_tightness = max(0.0, min(1.0, time_tightness))  # Clamp to 0-1
        else:
            time_tightness = 1.0
        
        # Component 2: Field Consistency (50% weight)
        # More matching fields across feathers = higher confidence
        applications = []
        file_paths = []
        
        for record in match_records.values():
            app = record.get('application')
            path = record.get('file_path')
            if app:
                applications.append(app.lower())
            if path:
                file_paths.append(path.lower())
        
        # Count how many fields are consistent
        matching_fields = 0
        total_fields = 0
        
        # Check application consistency
        if applications:
            total_fields += 1
            most_common_app = max(set(applications), key=applications.count)
            app_consistency = applications.count(most_common_app) / len(applications)
            if app_consistency >= 0.8:  # 80% or more match
                matching_fields += 1
        
        # Check file path consistency
        if file_paths:
            total_fields += 1
            most_common_path = max(set(file_paths), key=file_paths.count)
            path_consistency = file_paths.count(most_common_path) / len(file_paths)
            if path_consistency >= 0.8:  # 80% or more match
                matching_fields += 1
        
        # Calculate field consistency
        if total_fields > 0:
            field_consistency = matching_fields / total_fields
        else:
            field_consistency = 0.0
        
        # Calculate final confidence score
        confidence_score = (0.5 * time_tightness) + (0.5 * field_consistency)
        confidence_score = max(0.0, min(1.0, confidence_score))  # Ensure 0-1 range
        
        # Determine confidence category
        if confidence_score > 0.8:
            confidence_category = "High"
        elif confidence_score >= 0.5:
            confidence_category = "Medium"
        else:
            confidence_category = "Low"
        
        return confidence_score, confidence_category
    
    def _validate_time_window(self, match_records: Dict[str, Dict[str, Any]],
                             anchor_feather_id: str,
                             anchor_time: datetime,
                             time_window_minutes: int) -> Tuple[bool, Dict[str, Dict[str, Any]]]:
        """
        Validate that all non-anchor records fall within the time window from anchor.
        
        This provides bidirectional validation - each record is checked against the anchor
        to ensure it's within the specified time window.
        
        Args:
            match_records: Dictionary of feather_id -> record
            anchor_feather_id: ID of the anchor feather
            anchor_time: Anchor timestamp
            time_window_minutes: Time window in minutes
            
        Returns:
            Tuple of (is_valid, validated_records)
            - is_valid: True if all records pass validation
            - validated_records: Dictionary with only valid records
        """
        time_window_seconds = time_window_minutes * 60
        validated_records = {anchor_feather_id: match_records[anchor_feather_id]}
        
        for feather_id, record in match_records.items():
            if feather_id == anchor_feather_id:
                continue
            
            record_time = self._parse_timestamp(record.get('timestamp'))
            if not record_time:
                # Invalid timestamp - exclude this record
                continue
            
            # Check if within time window
            time_diff = abs((record_time - anchor_time).total_seconds())
            if time_diff <= time_window_seconds:
                validated_records[feather_id] = record
        
        # Check if we still have the same records (all passed validation)
        is_valid = len(validated_records) == len(match_records)
        
        return is_valid, validated_records
    
    def _apply_semantic_mappings(self, 
                                match_records: Dict[str, Dict[str, Any]],
                                wing: Wing) -> Dict[str, Any]:
        """
        Apply semantic mappings to match records for improved field matching.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing: Wing configuration
            
        Returns:
            Dictionary containing:
            - normalized_values: Dict of field -> normalized value
            - semantic_matches: List of semantic equivalences found
            - similarity_scores: Dict of field -> semantic similarity score
        """
        semantic_data = {
            'normalized_values': {},
            'semantic_matches': [],
            'similarity_scores': {}
        }
        
        # Normalize application names
        applications = []
        for feather_id, record in match_records.items():
            app_value = self._get_field_value(record, feather_id, 'name')
            if app_value:
                normalized = self.semantic_manager.normalize_field_value(
                    'application', app_value, wing.wing_id
                )
                applications.append((feather_id, app_value, normalized))
        
        # Calculate semantic similarity for applications
        if len(applications) > 1:
            normalized_apps = [app[2] for app in applications]
            similarity = self.semantic_manager.calculate_semantic_similarity(normalized_apps)
            semantic_data['similarity_scores']['application'] = similarity
            
            # Track semantic matches (where original values differ but normalized values match)
            for i, (fid1, orig1, norm1) in enumerate(applications):
                for fid2, orig2, norm2 in applications[i+1:]:
                    if norm1 == norm2 and orig1 != orig2:
                        semantic_data['semantic_matches'].append({
                            'field': 'application',
                            'feather1': fid1,
                            'value1': orig1,
                            'feather2': fid2,
                            'value2': orig2,
                            'normalized': norm1
                        })
            
            # Store normalized application value
            if normalized_apps:
                semantic_data['normalized_values']['application'] = normalized_apps[0]
        
        # Normalize file paths
        paths = []
        for feather_id, record in match_records.items():
            path_value = self._get_field_value(record, feather_id, 'path')
            if path_value:
                normalized = self.semantic_manager.normalize_field_value(
                    'path', path_value, wing.wing_id
                )
                paths.append((feather_id, path_value, normalized))
        
        # Calculate semantic similarity for paths
        if len(paths) > 1:
            normalized_paths = [path[2] for path in paths]
            similarity = self.semantic_manager.calculate_semantic_similarity(normalized_paths)
            semantic_data['similarity_scores']['path'] = similarity
            
            # Track semantic matches for paths
            for i, (fid1, orig1, norm1) in enumerate(paths):
                for fid2, orig2, norm2 in paths[i+1:]:
                    if norm1 == norm2 and orig1 != orig2:
                        semantic_data['semantic_matches'].append({
                            'field': 'path',
                            'feather1': fid1,
                            'value1': orig1,
                            'feather2': fid2,
                            'value2': orig2,
                            'normalized': norm1
                        })
            
            # Store normalized path value
            if normalized_paths:
                semantic_data['normalized_values']['path'] = normalized_paths[0]
        
        return semantic_data
    
    def _create_match(self, match_records: Dict[str, Dict[str, Any]],
                     anchor_feather_id: str,
                     anchor_artifact_type: str,
                     anchor_time: datetime,
                     wing: Wing) -> CorrelationMatch:
        """Create a correlation match object with enhanced scoring and metadata"""
        import hashlib
        import json
        
        # Calculate time spread
        timestamps = []
        for record in match_records.values():
            ts = self._parse_timestamp(record.get('timestamp'))
            if ts:
                timestamps.append(ts)
        
        if len(timestamps) > 1:
            time_spread = (max(timestamps) - min(timestamps)).total_seconds()
        else:
            time_spread = 0.0
        
        # Calculate enhanced match score with breakdown
        feather_count = len(match_records)
        total_feathers = len(wing.feathers)
        
        enhanced_score, score_breakdown = self._calculate_enhanced_score(
            match_records,
            anchor_time,
            wing.correlation_rules.time_window_minutes,
            total_feathers
        )
        
        # Calculate weighted score if enabled
        weighted_score_data = None
        if hasattr(wing, 'use_weighted_scoring') and wing.use_weighted_scoring:
            # Convert wing to a format compatible with WeightedScoringEngine
            # The engine expects a wing_config object with feathers and scoring attributes
            weighted_score_data = self.weighted_scoring_engine.calculate_match_score(
                match_records,
                wing
            )
        
        # Calculate confidence score
        confidence_score, confidence_category = self._calculate_confidence_score(
            match_records,
            wing.correlation_rules.time_window_minutes,
            time_spread
        )
        
        # Calculate time deltas (seconds from anchor for each feather)
        time_deltas = {}
        for feather_id, record in match_records.items():
            if feather_id == anchor_feather_id:
                time_deltas[feather_id] = 0.0
            else:
                record_time = self._parse_timestamp(record.get('timestamp'))
                if record_time:
                    time_deltas[feather_id] = abs((record_time - anchor_time).total_seconds())
        
        # Calculate field similarity scores using detected columns
        field_similarity_scores = {}
        
        # Application similarity - use detected columns
        applications = []
        for feather_id, record in match_records.items():
            app_value = self._get_field_value(record, feather_id, 'name')
            if app_value:
                applications.append(app_value.lower())
        
        if applications:
            most_common_app = max(set(applications), key=applications.count)
            app_similarity = applications.count(most_common_app) / len(applications)
            field_similarity_scores['application'] = round(app_similarity, 4)
        
        # File path similarity - use detected columns
        file_paths = []
        for feather_id, record in match_records.items():
            path_value = self._get_field_value(record, feather_id, 'path')
            if path_value:
                file_paths.append(path_value.lower())
        
        if file_paths:
            most_common_path = max(set(file_paths), key=file_paths.count)
            path_similarity = file_paths.count(most_common_path) / len(file_paths)
            field_similarity_scores['file_path'] = round(path_similarity, 4)
        
        # Candidate counts (would need to be passed from correlation method)
        # For now, set to None - can be enhanced later
        candidate_counts = None
        
        # Generate wing config hash
        wing_config_dict = {
            'wing_id': wing.wing_id,
            'time_window': wing.correlation_rules.time_window_minutes,
            'minimum_matches': wing.correlation_rules.minimum_matches,
            'target_application': wing.correlation_rules.target_application,
            'target_file_path': wing.correlation_rules.target_file_path,
            'target_event_id': wing.correlation_rules.target_event_id
        }
        wing_config_str = json.dumps(wing_config_dict, sort_keys=True)
        wing_config_hash = hashlib.md5(wing_config_str.encode()).hexdigest()
        
        # Extract matched values using detected columns
        anchor_record = match_records[anchor_feather_id]
        
        # Use detected columns to find application/name field
        matched_app = self._get_field_value(anchor_record, anchor_feather_id, 'name')
        
        # Use detected columns to find file path field
        matched_path = self._get_field_value(anchor_record, anchor_feather_id, 'path')
        
        # Try to find event ID field
        matched_event = anchor_record.get('event_id')
        
        # NEW: Apply semantic mappings
        semantic_data = self._apply_semantic_mappings(match_records, wing)
        
        return CorrelationMatch(
            match_id=str(uuid.uuid4()),
            timestamp=anchor_time.isoformat(),
            feather_records=match_records,
            match_score=enhanced_score,
            feather_count=feather_count,
            time_spread_seconds=time_spread,
            anchor_feather_id=anchor_feather_id,
            anchor_artifact_type=anchor_artifact_type,
            matched_application=matched_app,
            matched_file_path=matched_path,
            matched_event_id=matched_event,
            score_breakdown=score_breakdown,
            confidence_score=confidence_score,
            confidence_category=confidence_category,
            weighted_score=weighted_score_data,
            time_deltas=time_deltas,
            field_similarity_scores=field_similarity_scores,
            candidate_counts=candidate_counts,
            algorithm_version="2.0",
            wing_config_hash=wing_config_hash,
            semantic_data=semantic_data  # NEW: Add semantic data
        )
    
    def _validate_match_integrity(self, match: CorrelationMatch, wing: Wing) -> Tuple[bool, List[str]]:
        """
        Validate match integrity.
        
        Checks:
        - Match ID is unique
        - feather_count matches actual number of records
        - time_spread is calculated correctly
        - anchor feather is present
        - match_score is in valid range
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Validate feather_count matches actual records
        actual_count = len(match.feather_records)
        if match.feather_count != actual_count:
            errors.append(
                f"Match {match.match_id}: feather_count ({match.feather_count}) "
                f"doesn't match actual records ({actual_count})"
            )
        
        # Validate anchor feather is present
        if match.anchor_feather_id not in match.feather_records:
            errors.append(
                f"Match {match.match_id}: anchor feather {match.anchor_feather_id} "
                f"not present in feather_records"
            )
        
        # Validate match_score is in valid range
        if not (0.0 <= match.match_score <= 1.0):
            errors.append(
                f"Match {match.match_id}: match_score ({match.match_score}) "
                f"is outside valid range [0.0, 1.0]"
            )
        
        # Validate time_spread calculation
        timestamps = []
        for record in match.feather_records.values():
            ts_str = record.get('timestamp')
            if ts_str:
                ts = self._parse_timestamp(ts_str)
                if ts:
                    timestamps.append(ts)
        
        if len(timestamps) > 1:
            expected_spread = (max(timestamps) - min(timestamps)).total_seconds()
            # Allow small floating point differences
            if abs(match.time_spread_seconds - expected_spread) > 0.01:
                errors.append(
                    f"Match {match.match_id}: time_spread_seconds ({match.time_spread_seconds}) "
                    f"doesn't match calculated value ({expected_spread})"
                )
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def _cleanup_loaders(self):
        """Cleanup feather loaders"""
        for loader in self.feather_loaders.values():
            try:
                loader.disconnect()
            except:
                pass
        
        self.feather_loaders.clear()
