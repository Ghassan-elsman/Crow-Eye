"""
Core data structures for the Crow-Eye Correlation Engine.

This module defines the fundamental data structures used throughout the correlation engine:
- Identity: Logical entity inferred from Feather data
- Anchor: Execution window grouping evidence by time
- EvidenceRow: Reference to Feather row supporting an inference
- DetectedColumns: Column names detected in Feather tables
- ExtractedValues: Values extracted from Feather rows
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from uuid import uuid4


@dataclass
class EvidenceRow:
    """
    Reference to a Feather row that supports an inference.
    
    Evidence rows never duplicate Feather data - they only reference it.
    Enhanced with identity-based correlation fields.
    """
    artifact: str  # e.g., "prefetch", "srum", "shimcache"
    table: str  # Feather table name
    row_id: int  # Feather row identifier
    timestamp: Optional[datetime]  # When this evidence occurred (nullable for non-timestamped evidence)
    semantic: Dict[str, Any]  # Extracted semantic data (name, path, etc.)
    
    # NEW: Identity-based correlation fields
    feather_id: str = ""  # Feather identifier
    anchor_id: Optional[str] = None  # Anchor this evidence belongs to (nullable for supporting evidence)
    is_primary: bool = False  # Is this the primary evidence in its anchor?
    has_anchor: bool = True  # Does this evidence have a valid timestamp and anchor?
    role: str = "secondary"  # Evidence role: 'primary', 'secondary', 'supporting'
    match_reason: str = ""  # How this evidence was matched to identity
    match_method: str = ""  # Matching strategy used: 'exact', 'fuzzy', 'hash', 'partial_path'
    similarity_score: float = 0.0  # Similarity score for fuzzy matching
    confidence: float = 1.0  # Confidence in this evidence match
    original_data: Dict[str, Any] = field(default_factory=dict)  # Complete original record data
    semantic_data: Dict[str, Any] = field(default_factory=dict)  # Enhanced semantic mappings
    
    def __post_init__(self):
        """Validate evidence row data."""
        if not self.artifact:
            raise ValueError("artifact cannot be empty")
        if not self.table:
            raise ValueError("table cannot be empty")
        if self.row_id < 0:
            raise ValueError("row_id must be non-negative")
        
        # Validate role
        valid_roles = ["primary", "secondary", "supporting"]
        if self.role and self.role not in valid_roles:
            raise ValueError(f"role must be one of {valid_roles}, got '{self.role}'")


@dataclass
class Anchor:
    """
    Bounded execution or activity window for an identity.
    
    Groups evidence rows whose timestamps fall within a configurable time window.
    Used to distinguish separate executions of the same file.
    Enhanced with role counts and semantic summary.
    """
    anchor_id: str = field(default_factory=lambda: str(uuid4()))
    identity_id: Optional[str] = None  # Identity this anchor belongs to
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    rows: List[EvidenceRow] = field(default_factory=list)
    
    # NEW: Enhanced anchor fields
    duration_minutes: float = 0.0  # Duration of this anchor window
    primary_artifact: str = ""  # Artifact type of primary evidence
    primary_row_id: int = 0  # Row ID of primary evidence
    evidence_count: int = 0  # Total evidence in this anchor
    primary_count: int = 0  # Count of primary evidence
    secondary_count: int = 0  # Count of secondary evidence
    supporting_count: int = 0  # Count of supporting evidence (no timestamp)
    confidence: float = 1.0  # Confidence in this anchor
    semantic_summary: Dict[str, Any] = field(default_factory=dict)  # Semantic event summary
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata
    
    def add_evidence(self, evidence: EvidenceRow):
        """
        Add evidence row and update anchor time bounds and counts.
        
        Args:
            evidence: Evidence row to add
        """
        self.rows.append(evidence)
        self.evidence_count = len(self.rows)
        
        # Update role counts
        if evidence.role == "primary":
            self.primary_count += 1
            self.primary_artifact = evidence.artifact
            self.primary_row_id = evidence.row_id
        elif evidence.role == "secondary":
            self.secondary_count += 1
        elif evidence.role == "supporting":
            self.supporting_count += 1
        
        # Update time bounds only for timestamped evidence
        if evidence.timestamp:
            if self.start_time is None or evidence.timestamp < self.start_time:
                self.start_time = evidence.timestamp
            if self.end_time is None or evidence.timestamp > self.end_time:
                self.end_time = evidence.timestamp
            
            # Calculate duration
            if self.start_time and self.end_time:
                self.duration_minutes = (self.end_time - self.start_time).total_seconds() / 60.0
    
    def contains_timestamp(self, timestamp: datetime, time_window_minutes: int) -> bool:
        """Check if timestamp falls within this anchor's window."""
        if self.start_time is None or self.end_time is None:
            return False
        
        from datetime import timedelta
        window = timedelta(minutes=time_window_minutes)
        
        # Check if timestamp is within [start_time, end_time + window]
        return self.start_time <= timestamp <= (self.end_time + window)


@dataclass
class Identity:
    """
    Logical entity inferred from Feather data.
    
    Represents a real-world object (executable file, application instance, process, binary).
    Identities do not exist in Feather - they are created by the engine.
    Enhanced with complete evidence storage and metadata.
    """
    identity_id: str = field(default_factory=lambda: str(uuid4()))
    identity_type: str = ""  # "name", "path", "hash"
    identity_value: str = ""  # normalized value
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    anchors: List[Anchor] = field(default_factory=list)
    
    # NEW: Enhanced identity fields
    primary_name: str = ""  # Primary display name
    normalized_name: str = ""  # Normalized name for matching
    confidence: float = 1.0  # Confidence in identity match
    match_method: str = ""  # Method used to create identity: 'exact', 'fuzzy', 'hash', 'partial_path'
    total_evidence: int = 0  # Total evidence records for this identity
    total_anchors: int = 0  # Total temporal anchors
    artifacts_involved: List[str] = field(default_factory=list)  # List of artifact types
    all_evidence: List[EvidenceRow] = field(default_factory=list)  # ALL evidence (timestamped + non-timestamped)
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata
    
    def __post_init__(self):
        """Validate identity data."""
        valid_types = ["name", "path", "hash", "composite"]
        if self.identity_type and self.identity_type not in valid_types:
            raise ValueError(f"identity_type must be one of {valid_types}")
    
    def update_seen_times(self, timestamp: Optional[datetime]):
        """Update first_seen and last_seen based on evidence timestamp."""
        if timestamp is None:
            return
        if self.first_seen is None or timestamp < self.first_seen:
            self.first_seen = timestamp
        if self.last_seen is None or timestamp > self.last_seen:
            self.last_seen = timestamp
    
    def get_identity_key(self) -> str:
        """
        Generate identity key in format: type:normalized_value
        
        Returns:
            Composite key for identity lookup
        """
        # Use normalized_name if available, otherwise use identity_value
        value = self.normalized_name if self.normalized_name else self.identity_value
        return f"{self.identity_type}:{value}"
    
    def add_evidence(self, evidence: EvidenceRow):
        """
        Add evidence to this identity's complete evidence list.
        
        Args:
            evidence: Evidence row to add
        """
        self.all_evidence.append(evidence)
        self.total_evidence = len(self.all_evidence)
        
        # Update seen times if evidence has timestamp
        if evidence.timestamp:
            self.update_seen_times(evidence.timestamp)
        
        # Track artifact types
        if evidence.artifact not in self.artifacts_involved:
            self.artifacts_involved.append(evidence.artifact)


@dataclass
class DetectedColumns:
    """Column names detected in a Feather table."""
    name_columns: List[str] = field(default_factory=list)
    path_columns: List[str] = field(default_factory=list)
    timestamp_columns: List[str] = field(default_factory=list)
    
    def has_names(self) -> bool:
        """Check if any name columns were detected."""
        return len(self.name_columns) > 0
    
    def has_paths(self) -> bool:
        """Check if any path columns were detected."""
        return len(self.path_columns) > 0
    
    def has_timestamps(self) -> bool:
        """Check if any timestamp columns were detected."""
        return len(self.timestamp_columns) > 0


@dataclass
class ExtractedValues:
    """Values extracted from a Feather row."""
    names: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)
    timestamps: List[datetime] = field(default_factory=list)
    row_id: int = 0
    table_name: str = ""
    artifact_name: str = ""
    
    def get_primary_timestamp(self) -> Optional[datetime]:
        """Get the first timestamp (primary) for this row."""
        return self.timestamps[0] if self.timestamps else None
    
    def has_data(self) -> bool:
        """Check if any values were extracted."""
        return len(self.names) > 0 or len(self.paths) > 0


# Query result data structures

@dataclass
class AnchorWithEvidence:
    """Anchor with its evidence rows for query results."""
    anchor_id: str
    start_time: datetime
    end_time: datetime
    evidence_rows: List[EvidenceRow] = field(default_factory=list)


@dataclass
class IdentityWithAnchors:
    """Identity with all its anchors and evidence for query results."""
    identity_id: str
    identity_type: str
    identity_value: str
    first_seen: datetime
    last_seen: datetime
    wings_config_path: str
    anchors: List[AnchorWithEvidence] = field(default_factory=list)


@dataclass
class QueryFilters:
    """Filters for querying correlation results with semantic support."""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    identity_type: Optional[str] = None
    identity_value: Optional[str] = None
    
    # NEW: Semantic filtering fields
    semantic_category: Optional[str] = None  # Filter by semantic category
    semantic_meaning: Optional[str] = None  # Filter by semantic meaning
    severity: Optional[str] = None  # Filter by severity level
    evidence_role: Optional[str] = None  # Filter by evidence role (primary/secondary/supporting)
    mapping_source: Optional[str] = None  # Filter by mapping source (global/wing/built-in)
    
    # NEW: Pagination fields
    page: int = 0  # Page number (0-indexed)
    page_size: int = 100  # Records per page
    
    # NEW: Time-based filtering fields
    time_window_minutes: float = 30.0  # Time window for anchor grouping


# NEW: Enhanced correlation result data structures

@dataclass
class CorrelationStatistics:
    """
    Aggregate statistics for correlation execution.
    
    Tracks performance metrics and correlation quality indicators.
    """
    total_identities: int = 0
    total_anchors: int = 0
    total_evidence: int = 0
    evidence_with_anchors: int = 0
    evidence_without_anchors: int = 0
    duplicates_prevented: int = 0
    execution_duration_seconds: float = 0.0
    records_per_second: float = 0.0
    identities_by_type: Dict[str, int] = field(default_factory=dict)
    evidence_by_role: Dict[str, int] = field(default_factory=dict)
    artifacts_processed: List[str] = field(default_factory=list)


@dataclass
class CorrelationResults:
    """
    Complete results from identity-based correlation execution.
    
    Contains all identities with their anchors and evidence, plus statistics.
    """
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    wing_name: str = ""
    wing_id: str = ""
    execution_timestamp: datetime = field(default_factory=datetime.now)
    identities: List[Identity] = field(default_factory=list)
    statistics: CorrelationStatistics = field(default_factory=CorrelationStatistics)
    configuration: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: str = "Completed"  # "Completed" or "Cancelled"
    cancellation_timestamp: Optional[datetime] = None
    
    def add_identity(self, identity: Identity):
        """Add identity to results and update statistics."""
        self.identities.append(identity)
        self.statistics.total_identities = len(self.identities)
        self.statistics.total_anchors += len(identity.anchors)
        self.statistics.total_evidence += identity.total_evidence
        
        # Update identity type counts
        if identity.identity_type not in self.statistics.identities_by_type:
            self.statistics.identities_by_type[identity.identity_type] = 0
        self.statistics.identities_by_type[identity.identity_type] += 1
        
        # Update evidence role counts
        for evidence in identity.all_evidence:
            if evidence.role not in self.statistics.evidence_by_role:
                self.statistics.evidence_by_role[evidence.role] = 0
            self.statistics.evidence_by_role[evidence.role] += 1
            
            # Track anchored vs non-anchored evidence
            if evidence.has_anchor:
                self.statistics.evidence_with_anchors += 1
            else:
                self.statistics.evidence_without_anchors += 1


@dataclass
class PaginatedResult:
    """
    Paginated query result for large datasets.
    
    Supports efficient loading of large result sets.
    """
    results: List[Any] = field(default_factory=list)
    page: int = 0
    page_size: int = 100
    total_count: int = 0
    total_pages: int = 0
    has_next: bool = False
    has_previous: bool = False
    
    def __post_init__(self):
        """Calculate pagination metadata."""
        self.has_next = self.page < (self.total_pages - 1)
        self.has_previous = self.page > 0


@dataclass
class IdentityWithAllEvidence:
    """
    Identity with complete evidence breakdown.
    
    Separates anchored evidence from supporting evidence for detailed analysis.
    """
    identity_id: str
    identity_type: str
    identity_value: str
    normalized_name: str
    confidence: float
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]
    anchored_evidence: List[AnchorWithEvidence] = field(default_factory=list)
    supporting_evidence: List[EvidenceRow] = field(default_factory=list)
    artifacts_involved: List[str] = field(default_factory=list)
    semantic_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnchorTimeGroup:
    """
    Group of identities active at a specific anchor time.
    
    Organizes correlation results by temporal anchor points for time-first analysis.
    """
    anchor_time: datetime
    identities: List[IdentityWithAnchors] = field(default_factory=list)
    total_identities: int = 0
    total_evidence: int = 0
    primary_artifacts: List[str] = field(default_factory=list)
    time_window_minutes: float = 0.0
    
    def __post_init__(self):
        """Calculate derived fields."""
        self.total_identities = len(self.identities)
        self.total_evidence = sum(
            len(anchor.evidence_rows) 
            for identity in self.identities 
            for anchor in identity.anchors
        )
        
        # Extract primary artifacts
        artifacts = set()
        for identity in self.identities:
            for anchor in identity.anchors:
                for evidence in anchor.evidence_rows:
                    if evidence.role == "primary":
                        artifacts.add(evidence.artifact)
        self.primary_artifacts = list(artifacts)


@dataclass
class TimeBasedQueryResult:
    """
    Results organized by anchor time for time-first hierarchical display.
    
    Transforms identity-first data into time-first organization.
    """
    anchor_time_groups: List[AnchorTimeGroup] = field(default_factory=list)
    total_anchor_times: int = 0
    total_identities: int = 0
    total_evidence: int = 0
    time_range: Optional[Tuple[datetime, datetime]] = None
    
    def __post_init__(self):
        """Calculate summary statistics."""
        self.total_anchor_times = len(self.anchor_time_groups)
        self.total_identities = sum(group.total_identities for group in self.anchor_time_groups)
        self.total_evidence = sum(group.total_evidence for group in self.anchor_time_groups)
        
        # Calculate time range
        if self.anchor_time_groups:
            times = [group.anchor_time for group in self.anchor_time_groups]
            self.time_range = (min(times), max(times))


# NEW: Time-based hierarchical data structures

@dataclass
class AnchorTimeGroup:
    """
    Group of identities active at a specific anchor time.
    
    Represents all identities that have evidence at a particular temporal anchor,
    enabling time-first hierarchical navigation.
    """
    anchor_time: datetime
    identities: List[IdentityWithAnchors] = field(default_factory=list)
    total_identities: int = 0
    total_evidence: int = 0
    primary_artifacts: List[str] = field(default_factory=list)  # Most common artifacts at this time
    time_window_minutes: float = 0.0  # Time window used for grouping
    
    def __post_init__(self):
        """Calculate derived fields."""
        self.total_identities = len(self.identities)
        self.total_evidence = sum(
            len(anchor.evidence_rows) 
            for identity in self.identities 
            for anchor in identity.anchors
            if self._anchor_contains_time(anchor, self.anchor_time)
        )
        
        # Calculate primary artifacts
        artifact_counts = {}
        for identity in self.identities:
            for anchor in identity.anchors:
                if self._anchor_contains_time(anchor, self.anchor_time):
                    for evidence in anchor.evidence_rows:
                        artifact_counts[evidence.artifact] = artifact_counts.get(evidence.artifact, 0) + 1
        
        # Sort by frequency and take top 3
        self.primary_artifacts = sorted(artifact_counts.keys(), 
                                      key=lambda x: artifact_counts[x], 
                                      reverse=True)[:3]
    
    def _anchor_contains_time(self, anchor: AnchorWithEvidence, target_time: datetime) -> bool:
        """Check if anchor contains the target time."""
        return anchor.start_time <= target_time <= anchor.end_time
    
    def get_identities_at_time(self) -> List[IdentityWithAnchors]:
        """Get all identities that have evidence at this anchor time."""
        return self.identities
    
    def get_evidence_count_at_time(self) -> int:
        """Get total evidence count at this anchor time."""
        return self.total_evidence


@dataclass
class TimeBasedQueryResult:
    """
    Results organized by anchor time for time-first hierarchical display.
    
    Transforms identity-centric correlation results into time-centric organization
    while preserving all original data relationships.
    """
    anchor_time_groups: List[AnchorTimeGroup] = field(default_factory=list)
    total_anchor_times: int = 0
    total_identities: int = 0
    total_evidence: int = 0
    time_range: Optional[Tuple[datetime, datetime]] = None
    time_window_minutes: float = 30.0  # Default time window for grouping
    
    def __post_init__(self):
        """Calculate derived statistics."""
        self.total_anchor_times = len(self.anchor_time_groups)
        
        # Calculate totals (avoiding double-counting)
        unique_identities = set()
        total_evidence_count = 0
        
        for group in self.anchor_time_groups:
            for identity in group.identities:
                unique_identities.add(identity.identity_id)
            total_evidence_count += group.total_evidence
        
        self.total_identities = len(unique_identities)
        self.total_evidence = total_evidence_count
        
        # Calculate time range
        if self.anchor_time_groups:
            times = [group.anchor_time for group in self.anchor_time_groups]
            self.time_range = (min(times), max(times))
    
    def get_anchor_times_chronological(self) -> List[AnchorTimeGroup]:
        """Get anchor time groups in chronological order."""
        return sorted(self.anchor_time_groups, key=lambda x: x.anchor_time)
    
    def get_anchor_times_by_activity(self) -> List[AnchorTimeGroup]:
        """Get anchor time groups ordered by activity level (most evidence first)."""
        return sorted(self.anchor_time_groups, key=lambda x: x.total_evidence, reverse=True)
    
    def filter_by_time_range(self, start_time: datetime, end_time: datetime) -> 'TimeBasedQueryResult':
        """Filter results to a specific time range."""
        filtered_groups = [
            group for group in self.anchor_time_groups
            if start_time <= group.anchor_time <= end_time
        ]
        
        result = TimeBasedQueryResult(
            anchor_time_groups=filtered_groups,
            time_window_minutes=self.time_window_minutes
        )
        return result
