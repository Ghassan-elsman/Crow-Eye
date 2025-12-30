"""
Query interface for correlation results.

This module provides querying and filtering capabilities for correlation results
stored in the relational database with enhanced semantic filtering, pagination,
and aggregate query support.
"""

import logging
import sqlite3
import json
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path

from correlation_engine.engine.data_structures import (
    QueryFilters, IdentityWithAnchors, AnchorWithEvidence, EvidenceRow,
    PaginatedResult, IdentityWithAllEvidence
)

logger = logging.getLogger(__name__)


class QueryInterface:
    """
    Query and filter correlation results from database.
    
    Provides hierarchical data retrieval (Identity → Anchors → Evidence)
    with filtering capabilities.
    """
    
    def __init__(self, db_path: str):
        """
        Initialize query interface.
        
        Args:
            db_path: Path to correlation database
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        
        logger.info(f"QueryInterface initialized with database: {db_path}")
    
    def connect(self):
        """Connect to database."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        logger.info(f"Connected to database: {self.db_path}")
    
    def disconnect(self):
        """Disconnect from database."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Disconnected from database")
    
    def query_identities(self, filters: Optional[QueryFilters] = None) -> List[IdentityWithAnchors]:
        """
        Query identities with optional filters.
        
        Args:
            filters: Optional query filters
            
        Returns:
            List of IdentityWithAnchors objects
        """
        if not self.conn:
            self.connect()
        
        # Build query
        query = "SELECT * FROM identities WHERE 1=1"
        params = []
        
        if filters:
            if filters.identity_type:
                query += " AND identity_type = ?"
                params.append(filters.identity_type)
            
            if filters.identity_value:
                query += " AND identity_value LIKE ?"
                params.append(f"%{filters.identity_value}%")
        
        query += " ORDER BY first_seen DESC"
        
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        
        identities = []
        for row in cursor.fetchall():
            identity = self._build_identity_with_anchors(row, filters)
            if identity:  # Skip identities with no matching anchors
                identities.append(identity)
        
        logger.info(f"Queried {len(identities)} identities")
        return identities
    
    def _build_identity_with_anchors(self, identity_row: sqlite3.Row, 
                                    filters: Optional[QueryFilters] = None) -> Optional[IdentityWithAnchors]:
        """
        Build IdentityWithAnchors from database row.
        
        Args:
            identity_row: Identity row from database
            filters: Optional filters to apply to anchors
            
        Returns:
            IdentityWithAnchors object or None if no anchors match filters
        """
        identity_id = identity_row['identity_id']
        
        # Query anchors for this identity
        anchors = self._query_anchors_for_identity(identity_id, filters)
        
        # If time filters are applied and no anchors match, skip this identity
        if filters and (filters.start_time or filters.end_time) and not anchors:
            return None
        
        return IdentityWithAnchors(
            identity_id=identity_id,
            identity_type=identity_row['identity_type'],
            identity_value=identity_row['identity_value'],
            first_seen=datetime.fromisoformat(identity_row['first_seen']),
            last_seen=datetime.fromisoformat(identity_row['last_seen']),
            wings_config_path=identity_row['wings_config_path'] or "",
            anchors=anchors
        )
    
    def _query_anchors_for_identity(self, identity_id: str, 
                                   filters: Optional[QueryFilters] = None) -> List[AnchorWithEvidence]:
        """
        Query anchors for a specific identity.
        
        Args:
            identity_id: Identity ID
            filters: Optional time range filters
            
        Returns:
            List of AnchorWithEvidence objects
        """
        query = "SELECT * FROM anchors WHERE identity_id = ?"
        params = [identity_id]
        
        if filters:
            if filters.start_time:
                query += " AND end_time >= ?"
                params.append(filters.start_time.isoformat())
            
            if filters.end_time:
                query += " AND start_time <= ?"
                params.append(filters.end_time.isoformat())
        
        query += " ORDER BY start_time ASC"
        
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        
        anchors = []
        for row in cursor.fetchall():
            anchor = self._build_anchor_with_evidence(row)
            anchors.append(anchor)
        
        return anchors
    
    def _build_anchor_with_evidence(self, anchor_row: sqlite3.Row) -> AnchorWithEvidence:
        """
        Build AnchorWithEvidence from database row.
        
        Args:
            anchor_row: Anchor row from database
            
        Returns:
            AnchorWithEvidence object
        """
        anchor_id = anchor_row['anchor_id']
        
        # Query evidence for this anchor
        evidence_rows = self._query_evidence_for_anchor(anchor_id)
        
        return AnchorWithEvidence(
            anchor_id=anchor_id,
            start_time=datetime.fromisoformat(anchor_row['start_time']),
            end_time=datetime.fromisoformat(anchor_row['end_time']),
            evidence_rows=evidence_rows
        )
    
    def _query_evidence_for_anchor(self, anchor_id: str) -> List[EvidenceRow]:
        """
        Query evidence for a specific anchor.
        
        Args:
            anchor_id: Anchor ID
            
        Returns:
            List of EvidenceRow objects
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM evidence 
            WHERE anchor_id = ?
            ORDER BY timestamp ASC
        """, (anchor_id,))
        
        evidence_rows = []
        for row in cursor.fetchall():
            evidence = EvidenceRow(
                artifact=row['artifact'],
                table=row['feather_table'],
                row_id=row['feather_row_id'],
                timestamp=datetime.fromisoformat(row['timestamp']),
                semantic=json.loads(row['semantic_json'])
            )
            evidence_rows.append(evidence)
        
        return evidence_rows
    
    def get_identity_with_anchors(self, identity_id: str) -> Optional[IdentityWithAnchors]:
        """
        Get identity with all anchors and evidence.
        
        Args:
            identity_id: Identity ID to retrieve
            
        Returns:
            IdentityWithAnchors or None if not found
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM identities WHERE identity_id = ?", (identity_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return self._build_identity_with_anchors(row)
    
    def filter_by_time_range(self, start_time: datetime, end_time: datetime) -> List[AnchorWithEvidence]:
        """
        Filter anchors by time range.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            List of anchors within time range
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM anchors 
            WHERE start_time <= ? AND end_time >= ?
            ORDER BY start_time ASC
        """, (end_time.isoformat(), start_time.isoformat()))
        
        anchors = []
        for row in cursor.fetchall():
            anchor = self._build_anchor_with_evidence(row)
            anchors.append(anchor)
        
        logger.info(f"Found {len(anchors)} anchors in time range")
        return anchors
    
    def filter_by_identity(self, identity_type: str, identity_value: str) -> List[IdentityWithAnchors]:
        """
        Filter by identity type and value.
        
        Args:
            identity_type: Type of identity ("name", "path", "hash")
            identity_value: Identity value (supports partial match)
            
        Returns:
            List of matching identities
        """
        filters = QueryFilters(
            identity_type=identity_type,
            identity_value=identity_value
        )
        return self.query_identities(filters)
    
    def get_all_identity_types(self) -> List[str]:
        """
        Get all unique identity types in database.
        
        Returns:
            List of identity types
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT identity_type FROM identities ORDER BY identity_type")
        
        return [row[0] for row in cursor.fetchall()]
    
    def get_identity_count(self) -> int:
        """Get total number of identities."""
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM identities")
        return cursor.fetchone()[0]
    
    def get_anchor_count(self) -> int:
        """Get total number of anchors."""
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM anchors")
        return cursor.fetchone()[0]
    
    def get_evidence_count(self) -> int:
        """Get total number of evidence rows."""
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM evidence")
        return cursor.fetchone()[0]
    
    # NEW: Task 3.1 - Semantic Filtering Queries
    
    def query_with_semantic_filter(self, filters: QueryFilters) -> List[IdentityWithAnchors]:
        """
        Query identities with semantic filtering.
        
        Filters evidence by semantic category, meaning, severity, role, and mapping source.
        Only returns identities that have evidence matching the semantic filters.
        
        Args:
            filters: QueryFilters with semantic filter fields
            
        Returns:
            List of IdentityWithAnchors with filtered evidence
            
        Requirements: 19, 20.2
        """
        if not self.conn:
            self.connect()
        
        # Build query with semantic joins
        query = """
            SELECT DISTINCT i.* 
            FROM identities i
            INNER JOIN evidence e ON i.identity_id = e.identity_id
        """
        
        # Add semantic_mappings join if semantic filters are present
        if filters.semantic_category or filters.semantic_meaning or filters.severity or filters.mapping_source:
            query += " INNER JOIN semantic_mappings sm ON e.evidence_id = sm.evidence_id"
        
        query += " WHERE 1=1"
        params = []
        
        # Apply semantic filters
        if filters.semantic_category:
            query += " AND sm.category = ?"
            params.append(filters.semantic_category)
        
        if filters.semantic_meaning:
            query += " AND sm.meaning LIKE ?"
            params.append(f"%{filters.semantic_meaning}%")
        
        if filters.severity:
            query += " AND sm.severity = ?"
            params.append(filters.severity)
        
        if filters.mapping_source:
            query += " AND sm.mapping_source = ?"
            params.append(filters.mapping_source)
        
        # Apply evidence role filter
        if filters.evidence_role:
            query += " AND e.role = ?"
            params.append(filters.evidence_role)
        
        # Apply identity filters
        if filters.identity_type:
            query += " AND i.identity_type = ?"
            params.append(filters.identity_type)
        
        if filters.identity_value:
            query += " AND i.identity_value LIKE ?"
            params.append(f"%{filters.identity_value}%")
        
        query += " ORDER BY i.first_seen DESC"
        
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        
        identities = []
        for row in cursor.fetchall():
            identity = self._build_identity_with_anchors(row, filters)
            if identity:
                identities.append(identity)
        
        logger.info(f"Queried {len(identities)} identities with semantic filters")
        return identities
    
    # NEW: Task 3.2 - Pagination Support
    
    def query_with_pagination(self, filters: QueryFilters) -> PaginatedResult:
        """
        Query identities with pagination support.
        
        Efficiently loads large result sets using LIMIT and OFFSET.
        
        Args:
            filters: QueryFilters with page and page_size fields
            
        Returns:
            PaginatedResult with page metadata
            
        Requirements: 19, 20.2
        """
        if not self.conn:
            self.connect()
        
        page = filters.page if filters.page is not None else 0
        page_size = filters.page_size if filters.page_size else 100
        
        # Get total count first
        count_query = "SELECT COUNT(DISTINCT i.identity_id) FROM identities i"
        count_params = []
        
        # Add joins and filters for count query
        if filters.semantic_category or filters.semantic_meaning or filters.severity or filters.mapping_source or filters.evidence_role:
            count_query += " INNER JOIN evidence e ON i.identity_id = e.identity_id"
            
            if filters.semantic_category or filters.semantic_meaning or filters.severity or filters.mapping_source:
                count_query += " INNER JOIN semantic_mappings sm ON e.evidence_id = sm.evidence_id"
        
        count_query += " WHERE 1=1"
        
        # Apply filters to count query
        if filters.semantic_category:
            count_query += " AND sm.category = ?"
            count_params.append(filters.semantic_category)
        
        if filters.evidence_role:
            count_query += " AND e.role = ?"
            count_params.append(filters.evidence_role)
        
        if filters.identity_type:
            count_query += " AND i.identity_type = ?"
            count_params.append(filters.identity_type)
        
        cursor = self.conn.cursor()
        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()[0]
        
        # Calculate pagination metadata
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1
        
        # Query for page of results
        if filters.semantic_category or filters.semantic_meaning or filters.severity or filters.mapping_source:
            identities = self.query_with_semantic_filter(filters)
        else:
            identities = self.query_identities(filters)
        
        # Apply pagination to results
        start_idx = page * page_size
        end_idx = start_idx + page_size
        page_results = identities[start_idx:end_idx]
        
        result = PaginatedResult(
            results=page_results,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages
        )
        
        logger.info(f"Paginated query: page {page+1}/{total_pages}, {len(page_results)} results")
        return result
    
    # NEW: Task 3.3 - Aggregate Query Methods
    
    def get_semantic_summary(self) -> Dict[str, int]:
        """
        Get semantic category breakdown.
        
        Returns count of evidence by semantic category.
        
        Returns:
            Dictionary mapping category to count
            
        Requirements: 19, 20.2
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM semantic_mappings
            GROUP BY category
            ORDER BY count DESC
        """)
        
        return {row['category']: row['count'] for row in cursor.fetchall()}
    
    def get_artifact_breakdown(self) -> Dict[str, int]:
        """
        Get artifact type breakdown.
        
        Returns count of evidence by artifact type.
        
        Returns:
            Dictionary mapping artifact to count
            
        Requirements: 19, 20.2
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT artifact, COUNT(*) as count
            FROM evidence
            GROUP BY artifact
            ORDER BY count DESC
        """)
        
        return {row['artifact']: row['count'] for row in cursor.fetchall()}
    
    def get_role_breakdown(self) -> Dict[str, int]:
        """
        Get evidence role breakdown.
        
        Returns count of evidence by role (primary/secondary/supporting).
        
        Returns:
            Dictionary mapping role to count
            
        Requirements: 19, 20.2
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT role, COUNT(*) as count
            FROM evidence
            GROUP BY role
            ORDER BY count DESC
        """)
        
        return {row['role']: row['count'] for row in cursor.fetchall()}
    
    def get_identity_type_breakdown(self) -> Dict[str, int]:
        """
        Get identity type breakdown.
        
        Returns count of identities by type.
        
        Returns:
            Dictionary mapping identity type to count
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT identity_type, COUNT(*) as count
            FROM identities
            GROUP BY identity_type
            ORDER BY count DESC
        """)
        
        return {row['identity_type']: row['count'] for row in cursor.fetchall()}
    
    def get_timeline_statistics(self) -> Dict[str, Any]:
        """
        Get timeline statistics.
        
        Returns min/max timestamps and time range.
        
        Returns:
            Dictionary with timeline statistics
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                MIN(first_seen) as earliest,
                MAX(last_seen) as latest,
                COUNT(*) as identity_count
            FROM identities
        """)
        
        row = cursor.fetchone()
        
        if row['earliest'] and row['latest']:
            earliest = datetime.fromisoformat(row['earliest'])
            latest = datetime.fromisoformat(row['latest'])
            duration = (latest - earliest).total_seconds()
            
            return {
                'earliest': earliest,
                'latest': latest,
                'duration_seconds': duration,
                'duration_days': duration / 86400,
                'identity_count': row['identity_count']
            }
        
        return {
            'earliest': None,
            'latest': None,
            'duration_seconds': 0,
            'duration_days': 0,
            'identity_count': 0
        }
    
    # NEW: Task 3.4 - Query All Evidence for Identity
    
    def get_identity_with_all_evidence(self, identity_id: str) -> Optional[IdentityWithAllEvidence]:
        """
        Get identity with ALL evidence (anchored + supporting).
        
        Queries both anchored evidence and supporting evidence (no timestamp).
        Includes semantic mappings for each evidence record.
        
        Args:
            identity_id: Identity ID to retrieve
            
        Returns:
            IdentityWithAllEvidence or None if not found
            
        Requirements: 2, 19, 20.2
        """
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        
        # Get identity
        cursor.execute("SELECT * FROM identities WHERE identity_id = ?", (identity_id,))
        identity_row = cursor.fetchone()
        
        if not identity_row:
            return None
        
        # Get anchored evidence (with anchors)
        cursor.execute("""
            SELECT a.*, e.*
            FROM anchors a
            INNER JOIN evidence e ON a.anchor_id = e.anchor_id
            WHERE a.identity_id = ?
            ORDER BY a.start_time ASC, e.timestamp ASC
        """, (identity_id,))
        
        # Group evidence by anchor
        anchors_dict = {}
        for row in cursor.fetchall():
            anchor_id = row['anchor_id']
            
            if anchor_id not in anchors_dict:
                anchors_dict[anchor_id] = {
                    'anchor': AnchorWithEvidence(
                        anchor_id=anchor_id,
                        start_time=datetime.fromisoformat(row['start_time']) if row['start_time'] else None,
                        end_time=datetime.fromisoformat(row['end_time']) if row['end_time'] else None,
                        evidence_rows=[]
                    ),
                    'evidence': []
                }
            
            # Create evidence row with enhanced fields
            evidence = self._build_enhanced_evidence_row(row)
            anchors_dict[anchor_id]['evidence'].append(evidence)
        
        # Populate evidence in anchors
        anchored_evidence = []
        for anchor_data in anchors_dict.values():
            anchor_data['anchor'].evidence_rows = anchor_data['evidence']
            anchored_evidence.append(anchor_data['anchor'])
        
        # Get supporting evidence (no anchor)
        cursor.execute("""
            SELECT * FROM evidence
            WHERE identity_id = ? AND anchor_id IS NULL
            ORDER BY feather_row_id ASC
        """, (identity_id,))
        
        supporting_evidence = []
        for row in cursor.fetchall():
            evidence = self._build_enhanced_evidence_row(row)
            supporting_evidence.append(evidence)
        
        # Parse artifacts_involved
        artifacts_involved = []
        if identity_row['artifacts_involved']:
            try:
                artifacts_involved = json.loads(identity_row['artifacts_involved'])
            except json.JSONDecodeError:
                pass
        
        # Build semantic summary
        semantic_summary = self._get_semantic_summary_for_identity(identity_id)
        
        return IdentityWithAllEvidence(
            identity_id=identity_id,
            identity_type=identity_row['identity_type'],
            identity_value=identity_row['identity_value'],
            normalized_name=identity_row['normalized_name'] or "",
            confidence=identity_row['confidence'] or 1.0,
            first_seen=datetime.fromisoformat(identity_row['first_seen']) if identity_row['first_seen'] else None,
            last_seen=datetime.fromisoformat(identity_row['last_seen']) if identity_row['last_seen'] else None,
            anchored_evidence=anchored_evidence,
            supporting_evidence=supporting_evidence,
            artifacts_involved=artifacts_involved,
            semantic_summary=semantic_summary
        )
    
    def _build_enhanced_evidence_row(self, row: sqlite3.Row) -> EvidenceRow:
        """
        Build EvidenceRow with all enhanced fields from database row.
        
        Args:
            row: Evidence row from database
            
        Returns:
            EvidenceRow with all fields populated
        """
        # Parse JSON fields
        semantic = json.loads(row['semantic_json']) if row['semantic_json'] else {}
        original_data = json.loads(row['original_data']) if row['original_data'] else {}
        semantic_data = json.loads(row['semantic_data']) if row['semantic_data'] else {}
        
        return EvidenceRow(
            artifact=row['artifact'],
            table=row['feather_table'],
            row_id=row['feather_row_id'],
            timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else None,
            semantic=semantic,
            feather_id=row['feather_id'] or "",
            anchor_id=row['anchor_id'],
            is_primary=bool(row['is_primary']),
            has_anchor=bool(row['has_anchor']),
            role=row['role'] or "secondary",
            match_reason=row['match_reason'] or "",
            match_method=row['match_method'] or "",
            similarity_score=row['similarity_score'] or 0.0,
            confidence=row['confidence'] or 1.0,
            original_data=original_data,
            semantic_data=semantic_data
        )
    
    def _get_semantic_summary_for_identity(self, identity_id: str) -> Dict[str, Any]:
        """
        Get semantic summary for an identity.
        
        Args:
            identity_id: Identity ID
            
        Returns:
            Dictionary with semantic category counts and meanings
        """
        cursor = self.conn.cursor()
        
        # Get category breakdown
        cursor.execute("""
            SELECT sm.category, COUNT(*) as count
            FROM semantic_mappings sm
            INNER JOIN evidence e ON sm.evidence_id = e.evidence_id
            WHERE e.identity_id = ?
            GROUP BY sm.category
            ORDER BY count DESC
        """, (identity_id,))
        
        categories = {row['category']: row['count'] for row in cursor.fetchall()}
        
        # Get top meanings
        cursor.execute("""
            SELECT sm.meaning, COUNT(*) as count
            FROM semantic_mappings sm
            INNER JOIN evidence e ON sm.evidence_id = e.evidence_id
            WHERE e.identity_id = ?
            GROUP BY sm.meaning
            ORDER BY count DESC
            LIMIT 10
        """, (identity_id,))
        
        meanings = {row['meaning']: row['count'] for row in cursor.fetchall()}
        
        return {
            'categories': categories,
            'top_meanings': meanings
        }
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


# Convenience functions

def query_identities(db_path: str, filters: Optional[QueryFilters] = None) -> List[IdentityWithAnchors]:
    """
    Convenience function to query identities.
    
    Args:
        db_path: Path to database
        filters: Optional filters
        
    Returns:
        List of identities
    """
    with QueryInterface(db_path) as qi:
        return qi.query_identities(filters)


def get_identity(db_path: str, identity_id: str) -> Optional[IdentityWithAnchors]:
    """
    Convenience function to get a single identity.
    
    Args:
        db_path: Path to database
        identity_id: Identity ID
        
    Returns:
        Identity or None
    """
    with QueryInterface(db_path) as qi:
        return qi.get_identity_with_anchors(identity_id)
