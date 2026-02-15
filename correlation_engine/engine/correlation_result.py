"""
Correlation Results
Data structures for storing correlation results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import json


@dataclass
class CorrelationMatch:
    """A single correlation match across feathers"""
    
    # Match identification
    match_id: str
    timestamp: str  # Central timestamp of the match
    
    # Matched records from each feather
    feather_records: Dict[str, Dict[str, Any]]  # feather_id -> record data
    
    # Match quality
    match_score: float  # 0.0 to 1.0
    feather_count: int  # Number of feathers that matched
    time_spread_seconds: float  # Time difference between earliest and latest
    
    # Anchor information
    anchor_feather_id: str
    anchor_artifact_type: str
    
    # What was matched
    matched_application: Optional[str] = None
    matched_file_path: Optional[str] = None
    matched_event_id: Optional[str] = None
    
    # Enhanced scoring metadata
    score_breakdown: Optional[Dict[str, float]] = None  # coverage, time_proximity, field_similarity
    confidence_score: Optional[float] = None  # 0.0 to 1.0
    confidence_category: Optional[str] = None  # "High", "Medium", "Low"
    weighted_score: Optional[Dict[str, Any]] = None  # Weighted scoring data (score, interpretation, breakdown)
    
    # Enhanced match metadata
    time_deltas: Optional[Dict[str, float]] = None  # feather_id -> seconds from anchor
    field_similarity_scores: Optional[Dict[str, float]] = None  # field -> similarity score
    candidate_counts: Optional[Dict[str, int]] = None  # feather_id -> number of candidates evaluated
    algorithm_version: str = "2.0"  # Correlation algorithm version
    wing_config_hash: Optional[str] = None  # Hash of wing configuration
    
    # NEW: Duplicate tracking
    is_duplicate: bool = False
    duplicate_info: Optional[Any] = None  # DuplicateInfo object
    
    # NEW: Semantic mapping data
    semantic_data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        # Ensure feather_records is JSON-serializable
        safe_feather_records = {}
        for fid, data in self.feather_records.items():
            if isinstance(data, dict):
                safe_data = {}
                for k, v in data.items():
                    # Convert non-serializable types to strings
                    if isinstance(v, (datetime, )):
                        safe_data[k] = v.isoformat() if hasattr(v, 'isoformat') else str(v)
                    elif isinstance(v, bytes):
                        safe_data[k] = v.decode('utf-8', errors='replace')
                    elif hasattr(v, '__dict__'):
                        safe_data[k] = str(v)
                    else:
                        safe_data[k] = v
                safe_feather_records[fid] = safe_data
            else:
                safe_feather_records[fid] = str(data) if data is not None else None
        
        result = {
            'match_id': self.match_id,
            'timestamp': self.timestamp,
            'feather_records': safe_feather_records,
            'match_score': self.match_score,
            'feather_count': self.feather_count,
            'time_spread_seconds': self.time_spread_seconds,
            'anchor_feather_id': self.anchor_feather_id,
            'anchor_artifact_type': self.anchor_artifact_type,
            'matched_application': self.matched_application,
            'matched_file_path': self.matched_file_path,
            'matched_event_id': self.matched_event_id,
            'score_breakdown': self.score_breakdown,
            'confidence_score': self.confidence_score,
            'confidence_category': self.confidence_category,
            'weighted_score': self.weighted_score,
            'time_deltas': self.time_deltas,
            'field_similarity_scores': self.field_similarity_scores,
            'candidate_counts': self.candidate_counts,
            'algorithm_version': self.algorithm_version,
            'wing_config_hash': self.wing_config_hash,
            'is_duplicate': self.is_duplicate,
            'semantic_data': self.semantic_data
        }
        
        # Add duplicate_info if present
        if self.duplicate_info:
            result['duplicate_info'] = {
                'is_duplicate': self.duplicate_info.is_duplicate,
                'original_match_id': self.duplicate_info.original_match_id,
                'original_anchor_feather': self.duplicate_info.original_anchor_feather,
                'original_anchor_time': str(self.duplicate_info.original_anchor_time) if self.duplicate_info.original_anchor_time else None,
                'duplicate_count': self.duplicate_info.duplicate_count
            }
        
        return result


@dataclass
class CorrelationResult:
    """Results from executing a wing"""
    
    # Wing information
    wing_id: str
    wing_name: str
    
    # Execution metadata
    execution_time: str = field(default_factory=lambda: datetime.now().isoformat())
    execution_duration_seconds: float = 0.0
    
    # Results
    matches: List[CorrelationMatch] = field(default_factory=list)
    total_matches: int = 0
    
    # Identity information (for Identity Semantic Phase)
    identities: List[Any] = field(default_factory=list)  # List of identity records for semantic processing
    
    # Statistics
    feathers_processed: int = 0
    total_records_scanned: int = 0
    duplicates_prevented: int = 0  # Number of duplicate matches prevented
    duplicates_by_feather: Dict[str, int] = field(default_factory=dict)  # NEW: Track duplicates per feather
    matches_failed_validation: int = 0  # Number of matches that failed time window validation
    
    # Anchor information
    anchor_feather_id: str = ""
    anchor_selection_reason: str = ""
    
    # Filter statistics
    filter_statistics: Dict[str, Dict[str, int]] = field(default_factory=dict)  # feather_id -> {before: X, after: Y}
    
    # Feather metadata
    feather_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # feather_id -> metadata
    
    # Performance metrics
    performance_metrics: Dict[str, Any] = field(default_factory=dict)  # timing, queries, memory
    
    # Filters applied
    filters_applied: Dict[str, Any] = field(default_factory=dict)
    
    # Errors and warnings
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Streaming mode - when True, matches are written to database instead of memory
    streaming_mode: bool = False
    _db_writer: Any = None  # StreamingMatchWriter instance
    _result_id: int = 0  # Database result_id for streaming
    
    # Database information for Identity Semantic Phase (streaming mode support)
    database_path: Optional[str] = None  # Path to correlation_results.db
    execution_id: Optional[int] = None  # Execution ID for database queries
    
    def add_match(self, match: CorrelationMatch):
        """Add a correlation match - streams to database if in streaming mode"""
        if self.streaming_mode and self._db_writer:
            # Stream directly to database
            self._db_writer.write_match(self._result_id, match)
            self.total_matches += 1
        else:
            # Traditional in-memory storage
            self.matches.append(match)
            self.total_matches = len(self.matches)
    
    def enable_streaming(self, db_writer, result_id: int):
        """Enable streaming mode - matches will be written directly to database"""
        self.streaming_mode = True
        self._db_writer = db_writer
        self._result_id = result_id
        # Clear any existing matches to free memory
        self.matches = []
    
    def finalize_streaming(self):
        """Finalize streaming mode - commit any pending writes"""
        if self.streaming_mode and self._db_writer:
            self._db_writer.flush()
            self._db_writer = None
        self.streaming_mode = False
    
    def get_matches_by_score(self, min_score: float = 0.0) -> List[CorrelationMatch]:
        """Get matches filtered by minimum score"""
        return [m for m in self.matches if m.match_score >= min_score]
    
    def get_matches_by_feather_count(self, min_count: int = 2) -> List[CorrelationMatch]:
        """Get matches filtered by minimum feather count"""
        return [m for m in self.matches if m.feather_count >= min_count]
    
    def get_matches_by_application(self, application: str) -> List[CorrelationMatch]:
        """Get matches for a specific application"""
        return [m for m in self.matches if m.matched_application == application]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics"""
        # Handle streaming mode where matches list is empty but total_matches is set
        if not self.matches and self.total_matches == 0:
            return {
                'total_matches': 0,
                'avg_score': 0.0,
                'avg_feather_count': 0.0,
                'applications': [],
                'execution_duration': round(self.execution_duration_seconds, 2),
                'records_scanned': self.total_records_scanned
            }
        
        # If streaming mode (matches empty but total_matches > 0), return basic summary
        if not self.matches and self.total_matches > 0:
            return {
                'total_matches': self.total_matches,
                'avg_score': 1.0,  # Identity matches are high confidence
                'avg_feather_count': 0.0,
                'applications': [],
                'execution_duration': round(self.execution_duration_seconds, 2),
                'records_scanned': self.total_records_scanned,
                'note': 'Full statistics available in database'
            }
        
        avg_score = sum(m.match_score for m in self.matches) / len(self.matches)
        avg_feather_count = sum(m.feather_count for m in self.matches) / len(self.matches)
        
        applications = set()
        for match in self.matches:
            if match.matched_application:
                applications.add(match.matched_application)
        
        return {
            'total_matches': self.total_matches,
            'avg_score': round(avg_score, 3),
            'avg_feather_count': round(avg_feather_count, 2),
            'applications': sorted(list(applications)),
            'execution_duration': round(self.execution_duration_seconds, 2),
            'records_scanned': self.total_records_scanned
        }
    
    def to_dict(self, include_matches: bool = True, max_matches: int = 10000) -> dict:
        """
        Convert to dictionary.
        
        Args:
            include_matches: Whether to include matches in output (default True)
            max_matches: Maximum matches to include to avoid memory issues (default 10000)
        
        Returns:
            Dictionary representation of the result
        """
        # For large result sets or streaming mode, don't include matches
        if self.total_matches > max_matches or (self.streaming_mode and not self.matches):
            matches_data = []
            matches_truncated = True
        elif include_matches:
            matches_data = [m.to_dict() for m in self.matches[:max_matches]]
            matches_truncated = len(self.matches) > max_matches
        else:
            matches_data = []
            matches_truncated = True
        
        return {
            'format_version': '2.0',  # Include format version for future compatibility
            'wing_id': self.wing_id,
            'wing_name': self.wing_name,
            'execution_time': self.execution_time,
            'execution_duration_seconds': self.execution_duration_seconds,
            'matches': matches_data,
            'total_matches': self.total_matches,
            'matches_truncated': matches_truncated,
            'matches_in_dict': len(matches_data),
            'feathers_processed': self.feathers_processed,
            'total_records_scanned': self.total_records_scanned,
            'duplicates_prevented': self.duplicates_prevented,
            'duplicates_by_feather': self.duplicates_by_feather,
            'matches_failed_validation': self.matches_failed_validation,
            'anchor_feather_id': self.anchor_feather_id,
            'anchor_selection_reason': self.anchor_selection_reason,
            'filter_statistics': self.filter_statistics,
            'feather_metadata': self.feather_metadata,
            'performance_metrics': self.performance_metrics,
            'filters_applied': self.filters_applied,
            'errors': self.errors,
            'warnings': self.warnings,
            'summary': self.get_summary()
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        try:
            return json.dumps(self.to_dict(), indent=indent, default=str)
        except MemoryError:
            # print(f"[CorrelationResult] MemoryError: Result too large for JSON string ({self.total_matches} matches)")
            raise
        except Exception as e:
            # print(f"[CorrelationResult] Error in to_json: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def save_to_file(self, file_path: str, max_matches_for_json: int = 10000):
        """
        Save results to JSON file.
        
        For large result sets (>max_matches_for_json), saves only summary and metadata
        to avoid memory issues. Full results are available in the SQLite database.
        
        Args:
            file_path: Path to save JSON file
            max_matches_for_json: Maximum matches to include in JSON (default 10000)
        """
        try:
            # For large result sets, save summary only to avoid memory issues
            if self.total_matches > max_matches_for_json:
                # print(f"[CorrelationResult] Large result set ({self.total_matches:,} matches) - saving summary only")
                
                # Create summary-only dict
                summary_dict = {
                    'wing_id': self.wing_id,
                    'wing_name': self.wing_name,
                    'execution_time': self.execution_time,
                    'execution_duration_seconds': self.execution_duration_seconds,
                    'total_matches': self.total_matches,
                    'matches_truncated': True,
                    'matches_in_json': 0,
                    'full_results_in_database': True,
                    'feathers_processed': self.feathers_processed,
                    'total_records_scanned': self.total_records_scanned,
                    'duplicates_prevented': self.duplicates_prevented,
                    'anchor_feather_id': self.anchor_feather_id,
                    'anchor_selection_reason': self.anchor_selection_reason,
                    'feather_metadata': self.feather_metadata,
                    'filters_applied': self.filters_applied,
                    'errors': self.errors,
                    'warnings': self.warnings,
                    'summary': self.get_summary(),
                    'note': f'Full results ({self.total_matches:,} matches) saved to SQLite database. JSON contains summary only.'
                }
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(summary_dict, f, indent=2, default=str)
                
                # print(f"[CorrelationResult] Saved summary to {file_path}")
            else:
                # Normal save for smaller result sets
                json_content = self.to_json()
                if not json_content:
                    # print(f"[CorrelationResult] Warning: to_json returned empty content")
                    pass
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(json_content)
                # print(f"[CorrelationResult] Saved {len(json_content)} bytes to {file_path}")
                
        except MemoryError:
            # Fallback: save summary only on memory error
            # print(f"[CorrelationResult] MemoryError - falling back to summary-only save")
            summary_dict = {
                'wing_id': self.wing_id,
                'wing_name': self.wing_name,
                'execution_time': self.execution_time,
                'total_matches': self.total_matches,
                'matches_truncated': True,
                'full_results_in_database': True,
                'error': 'MemoryError - results too large for JSON export',
                'summary': self.get_summary()
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(summary_dict, f, indent=2, default=str)
            # print(f"[CorrelationResult] Saved fallback summary to {file_path}")
            
        except Exception as e:
            # print(f"[CorrelationResult] Error saving to file {file_path}: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'CorrelationResult':
        """
        Load results from JSON file with legacy format support.
        
        Handles:
        - Current format with all fields
        - Legacy format without weighted_score (calculates simple score)
        - Legacy format without semantic_mappings (marks as unavailable)
        - Both dictionary and object formats for feather_records
        """
        import logging
        logger = logging.getLogger(__name__)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Detect format version
        format_version = data.get('format_version', '1.0')
        
        # Detect engine type from metadata
        engine_type = None
        if 'feather_metadata' in data:
            engine_type = data['feather_metadata'].get('engine_type')
        if not engine_type and 'summary' in data:
            engine_type = data['summary'].get('engine_type')
        
        # Reconstruct matches with legacy format handling
        matches = []
        for match_data in data.get('matches', []):
            try:
                # Handle legacy format without weighted_score
                if 'weighted_score' not in match_data or match_data.get('weighted_score') is None:
                    # Calculate simple score from feather count
                    feather_count = match_data.get('feather_count', 1)
                    match_data['weighted_score'] = {
                        'score': feather_count,
                        'interpretation': f'{feather_count} Feathers Matched',
                        'scoring_mode': 'simple_count_legacy'
                    }
                    logger.debug(f"Applied legacy scoring for match {match_data.get('match_id', 'unknown')}")
                
                # Handle legacy format without semantic_mappings
                if 'semantic_data' not in match_data or match_data.get('semantic_data') is None:
                    match_data['semantic_data'] = {
                        '_unavailable': True,
                        '_reason': 'Legacy format - semantic mappings not available'
                    }
                
                # Handle both dictionary and object formats for feather_records
                feather_records = match_data.get('feather_records', {})
                if isinstance(feather_records, list):
                    # Convert list format to dictionary
                    converted_records = {}
                    for i, record in enumerate(feather_records):
                        if isinstance(record, dict):
                            feather_id = record.get('feather_id', f'feather_{i}')
                            converted_records[feather_id] = record
                        else:
                            converted_records[f'feather_{i}'] = {'data': str(record)}
                    match_data['feather_records'] = converted_records
                
                # Use sensible defaults for missing required fields
                match_data.setdefault('match_id', f"legacy_{len(matches)}")
                match_data.setdefault('timestamp', '')
                match_data.setdefault('feather_records', {})
                match_data.setdefault('match_score', 0.0)
                match_data.setdefault('feather_count', 0)
                match_data.setdefault('time_spread_seconds', 0.0)
                match_data.setdefault('anchor_feather_id', '')
                match_data.setdefault('anchor_artifact_type', '')
                
                # Remove any fields not in CorrelationMatch
                valid_fields = {
                    'match_id', 'timestamp', 'feather_records', 'match_score', 'feather_count',
                    'time_spread_seconds', 'anchor_feather_id', 'anchor_artifact_type',
                    'matched_application', 'matched_file_path', 'matched_event_id',
                    'score_breakdown', 'confidence_score', 'confidence_category', 'weighted_score',
                    'time_deltas', 'field_similarity_scores', 'candidate_counts',
                    'algorithm_version', 'wing_config_hash', 'is_duplicate', 'duplicate_info',
                    'semantic_data'
                }
                filtered_data = {k: v for k, v in match_data.items() if k in valid_fields}
                
                matches.append(CorrelationMatch(**filtered_data))
                
            except Exception as e:
                logger.warning(f"Error loading match from {file_path}: {e}, skipping match")
                continue
        
        result = cls(
            wing_id=data.get('wing_id', 'unknown'),
            wing_name=data.get('wing_name', 'Unknown Wing'),
            execution_time=data.get('execution_time', ''),
            execution_duration_seconds=data.get('execution_duration_seconds', 0.0),
            matches=matches,
            total_matches=data.get('total_matches', len(matches)),
            feathers_processed=data.get('feathers_processed', 0),
            total_records_scanned=data.get('total_records_scanned', 0),
            duplicates_prevented=data.get('duplicates_prevented', 0),
            matches_failed_validation=data.get('matches_failed_validation', 0),
            anchor_feather_id=data.get('anchor_feather_id', ''),
            anchor_selection_reason=data.get('anchor_selection_reason', ''),
            filter_statistics=data.get('filter_statistics', {}),
            feather_metadata=data.get('feather_metadata', {}),
            performance_metrics=data.get('performance_metrics', {}),
            filters_applied=data.get('filters_applied', {}),
            errors=data.get('errors', []),
            warnings=data.get('warnings', [])
        )
        
        # Store detected engine type in metadata
        if engine_type:
            result.feather_metadata['engine_type'] = engine_type
        
        # Store format version for reference
        result.feather_metadata['loaded_format_version'] = format_version
        
        return result
