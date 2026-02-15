"""
Identity Registry

Maintains mapping between unique identities and their associated records.
Tracks processing status for identity-level semantic mapping.
"""

import logging
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RecordReference:
    """Reference to a record associated with an identity"""
    match_id: str
    feather_id: str
    record_index: int
    original_record: Dict[str, Any]
    wing_id: Optional[str] = None  # Track which wing this record came from
    wing_name: Optional[str] = None  # Track wing name for context


@dataclass
class IdentityRecord:
    """Record representing a unique identity and its associated data"""
    identity_value: str
    identity_type: str  # e.g., "file_path", "process_name", "user_id"
    record_references: List[RecordReference] = field(default_factory=list)
    semantic_data: Optional[Dict[str, Any]] = None
    processing_status: str = "pending"  # pending, processed, error
    error_message: Optional[str] = None
    
    def add_record_reference(self, reference: RecordReference):
        """Add a record reference to this identity"""
        self.record_references.append(reference)
    
    def mark_processed(self, semantic_data: Dict[str, Any]):
        """Mark identity as processed with semantic data"""
        self.semantic_data = semantic_data
        self.processing_status = "processed"
        self.error_message = None
    
    def mark_error(self, error_message: str):
        """Mark identity as having an error"""
        self.processing_status = "error"
        self.error_message = error_message
        if not self.semantic_data:
            self.semantic_data = {}
        self.semantic_data['_error'] = error_message
    
    def get_record_count(self) -> int:
        """Get number of records associated with this identity"""
        return len(self.record_references)


class IdentityRegistry:
    """
    Registry for managing unique identities and their associated records.
    
    Provides efficient identity consolidation, deduplication, and lookup.
    Tracks processing status for identity-level semantic mapping.
    
    Task 17.1: Optimized with efficient data structures for large datasets
    - Uses hash-based lookups for O(1) identity access
    - Maintains separate indexes for type-based and status-based filtering
    - Implements efficient batch operations
    
    Requirements: 3.1, 3.2, 8.4, 9.4, 13.1, 13.3
    Property 4: Identity Consolidation Completeness
    Property 11: Identity Registry Creation and Management
    Property 17: Identity-Level Semantic Processing
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize empty identity registry with optimized data structures.
        
        Task 17.1: Implement efficient identity registry data structures (Requirement 13.1, 13.3)
        
        Args:
            debug_mode: Enable debug logging
        """
        # Primary storage: hash map for O(1) lookups
        self._identities: Dict[str, IdentityRecord] = {}
        self._identity_count = 0
        self._total_records = 0
        self.debug_mode = debug_mode
        
        # Task 17.1: Efficient indexes for filtering operations
        # Index by identity type for efficient type-based filtering
        self._identities_by_type: Dict[str, Set[str]] = {}
        
        # Task 17.1: Index by processing status for efficient status-based filtering
        # Avoids full scan when getting pending/processed/error identities
        self._identities_by_status: Dict[str, Set[str]] = {
            'pending': set(),
            'processed': set(),
            'error': set()
        }
    
    def add_identity(self, identity: IdentityRecord):
        """
        Add an identity to the registry with deduplication.
        
        If the identity already exists, merges record references.
        This implements identity consolidation and deduplication.
        
        Task 17.1: Optimized with efficient index maintenance
        
        Args:
            identity: IdentityRecord to add
            
        Requirements: 3.1, 3.2, 13.1, 13.3
        Property 4: Identity Consolidation Completeness
        Property 17: Identity-Level Semantic Processing
        """
        identity_key = self._get_identity_key(identity.identity_value, identity.identity_type)
        
        if identity_key not in self._identities:
            # New identity - add to registry
            self._identities[identity_key] = identity
            self._identity_count += 1
            self._total_records += len(identity.record_references)
            
            # Add to type index
            if identity.identity_type not in self._identities_by_type:
                self._identities_by_type[identity.identity_type] = set()
            self._identities_by_type[identity.identity_type].add(identity_key)
            
            # Task 17.1: Add to status index for efficient filtering
            status = identity.processing_status
            if status in self._identities_by_status:
                self._identities_by_status[status].add(identity_key)
            
        else:
            # Existing identity - merge record references (deduplication)
            existing = self._identities[identity_key]
            
            # Track existing record references to avoid duplicates
            existing_refs = {
                (ref.match_id, ref.feather_id, ref.record_index)
                for ref in existing.record_references
            }
            
            # Add only new record references
            for ref in identity.record_references:
                ref_key = (ref.match_id, ref.feather_id, ref.record_index)
                if ref_key not in existing_refs:
                    existing.add_record_reference(ref)
                    self._total_records += 1
    
    def get_unique_identities(self) -> List[str]:
        """
        Get list of unique identity values.
        
        Returns:
            List of identity value strings
        """
        return [identity.identity_value for identity in self._identities.values()]
    
    def get_identity_record(self, identity_value: str, identity_type: Optional[str] = None) -> Optional[IdentityRecord]:
        """
        Get identity record by value and optional type.
        
        Args:
            identity_value: Identity value to look up
            identity_type: Optional identity type for disambiguation
            
        Returns:
            IdentityRecord if found, None otherwise
        """
        if identity_type:
            # Use specific type
            identity_key = self._get_identity_key(identity_value, identity_type)
            return self._identities.get(identity_key)
        else:
            # Search all types for this value
            for identity in self._identities.values():
                if identity.identity_value == identity_value:
                    return identity
            return None
    
    def mark_processed(self, identity_value: str, semantic_data: Dict[str, Any], 
                      identity_type: Optional[str] = None):
        """
        Mark an identity as processed with semantic data.
        
        Task 17.1: Optimized with efficient status index updates
        
        Args:
            identity_value: Identity value to mark
            semantic_data: Semantic data to associate
            identity_type: Optional identity type for disambiguation
            
        Requirements: 9.4, 13.1, 13.3
        Property 11: Identity Registry Creation and Management
        Property 17: Identity-Level Semantic Processing
        """
        identity = self.get_identity_record(identity_value, identity_type)
        if identity:
            # Get identity key for index updates
            identity_key = self._get_identity_key(identity.identity_value, identity.identity_type)
            
            # Task 17.1: Update status index efficiently
            old_status = identity.processing_status
            if old_status in self._identities_by_status:
                self._identities_by_status[old_status].discard(identity_key)
            
            # Mark identity as processed
            identity.mark_processed(semantic_data)
            
            # Add to processed index
            self._identities_by_status['processed'].add(identity_key)
    
    def mark_error(self, identity_value: str, error_message: str,
                  identity_type: Optional[str] = None):
        """
        Mark an identity as having an error.
        
        Task 17.1: Optimized with efficient status index updates
        
        Args:
            identity_value: Identity value to mark
            error_message: Error message
            identity_type: Optional identity type for disambiguation
            
        Requirements: 13.1, 13.3
        """
        identity = self.get_identity_record(identity_value, identity_type)
        if identity:
            # Get identity key for index updates
            identity_key = self._get_identity_key(identity.identity_value, identity.identity_type)
            
            # Task 17.1: Update status index efficiently
            old_status = identity.processing_status
            if old_status in self._identities_by_status:
                self._identities_by_status[old_status].discard(identity_key)
            
            # Mark identity as error
            identity.mark_error(error_message)
            
            # Add to error index
            self._identities_by_status['error'].add(identity_key)
    
    def get_unique_identity_count(self) -> int:
        """
        Get count of unique identities in registry.
        
        Returns:
            Number of unique identities
        """
        return self._identity_count
    
    def get_total_record_count(self) -> int:
        """
        Get total count of record references across all identities.
        
        Returns:
            Total number of record references
        """
        return self._total_records
    
    def get_all_identities(self) -> List[IdentityRecord]:
        """
        Get all identity records.
        
        Returns:
            List of all IdentityRecord objects
        """
        return list(self._identities.values())
    
    def get_identities_by_type(self, identity_type: str) -> List[IdentityRecord]:
        """
        Get identities filtered by type.
        
        Args:
            identity_type: Type to filter by
            
        Returns:
            List of IdentityRecord objects of specified type
        """
        if identity_type not in self._identities_by_type:
            return []
        
        identity_keys = self._identities_by_type[identity_type]
        return [self._identities[key] for key in identity_keys if key in self._identities]
    
    def get_pending_identities(self) -> List[IdentityRecord]:
        """
        Get identities that haven't been processed yet.
        
        Task 17.1: Optimized using status index for O(1) filtering instead of O(n) scan
        
        Returns:
            List of pending IdentityRecord objects
            
        Requirements: 13.1, 13.3
        Property 17: Identity-Level Semantic Processing
        """
        # Task 17.1: Use status index for efficient filtering
        pending_keys = self._identities_by_status.get('pending', set())
        return [self._identities[key] for key in pending_keys if key in self._identities]
    
    def get_processed_identities(self) -> List[IdentityRecord]:
        """
        Get identities that have been processed.
        
        Task 17.1: Optimized using status index for O(1) filtering instead of O(n) scan
        Note: Falls back to full scan if status index is inconsistent
        
        Returns:
            List of processed IdentityRecord objects
            
        Requirements: 13.1, 13.3
        """
        # Task 17.1: Use status index for efficient filtering
        processed_keys = self._identities_by_status.get('processed', set())
        processed_from_index = [self._identities[key] for key in processed_keys if key in self._identities]
        
        # Fallback: If status index seems inconsistent, do a full scan
        # This handles cases where identities were marked processed directly without updating the index
        if len(processed_from_index) == 0:
            # Full scan fallback - check all identities for processed status
            processed_from_scan = [
                identity for identity in self._identities.values()
                if identity.processing_status == 'processed'
            ]
            
            # If we found processed identities via scan but not via index, the index is inconsistent
            if len(processed_from_scan) > 0:
                if self.debug_mode:
                    logger.warning(f"[Identity Registry] Status index inconsistent: found {len(processed_from_scan)} processed identities via scan but 0 via index")
                
                # Rebuild the status index for processed identities
                self._identities_by_status['processed'] = {
                    self._get_identity_key(identity.identity_value, identity.identity_type)
                    for identity in processed_from_scan
                }
                
                return processed_from_scan
        
        return processed_from_index
    
    def get_error_identities(self) -> List[IdentityRecord]:
        """
        Get identities that encountered errors during processing.
        
        Task 17.1: Optimized using status index for O(1) filtering instead of O(n) scan
        
        Returns:
            List of error IdentityRecord objects
            
        Requirements: 13.1, 13.3
        """
        # Task 17.1: Use status index for efficient filtering
        error_keys = self._identities_by_status.get('error', set())
        return [self._identities[key] for key in error_keys if key in self._identities]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive registry statistics.
        
        Task 17.1: Optimized using status index for efficient counting
        
        Returns:
            Dictionary with statistics
            
        Requirements: 8.4, 13.1, 13.3
        Property 11: Identity Registry Creation and Management
        Property 17: Identity-Level Semantic Processing
        """
        # Task 17.1: Use status index for efficient counting (O(1) instead of O(n))
        pending_count = len(self._identities_by_status.get('pending', set()))
        processed_count = len(self._identities_by_status.get('processed', set()))
        error_count = len(self._identities_by_status.get('error', set()))
        
        # Calculate identities by type
        identities_by_type = {}
        for identity_type, identity_keys in self._identities_by_type.items():
            identities_by_type[identity_type] = len(identity_keys)
        
        # Calculate average records per identity
        avg_records_per_identity = (
            self._total_records / self._identity_count 
            if self._identity_count > 0 else 0.0
        )
        
        return {
            'total_identities': self._identity_count,
            'total_records': self._total_records,
            'avg_records_per_identity': round(avg_records_per_identity, 2),
            'pending': pending_count,
            'processed': processed_count,
            'errors': error_count,
            'identities_by_type': identities_by_type,
            'processing_progress': round(
                (processed_count / self._identity_count * 100) if self._identity_count > 0 else 0.0,
                2
            )
        }
    
    def get_identity_types(self) -> List[str]:
        """
        Get list of all identity types in registry.
        
        Returns:
            List of identity type strings
        """
        return list(self._identities_by_type.keys())
    
    def clear(self):
        """
        Clear all identities from registry.
        
        Task 17.1: Clear all indexes for complete reset
        """
        self._identities.clear()
        self._identities_by_type.clear()
        # Task 17.1: Clear status index
        for status_set in self._identities_by_status.values():
            status_set.clear()
        self._identity_count = 0
        self._total_records = 0
    
    def _get_identity_key(self, identity_value: str, identity_type: str) -> str:
        """
        Generate unique key for identity lookup.
        
        Args:
            identity_value: Identity value
            identity_type: Identity type
            
        Returns:
            Composite key string
        """
        # Normalize identity value for consistent lookup
        normalized_value = identity_value.lower().strip()
        return f"{identity_type}:{normalized_value}"
    
    def __len__(self) -> int:
        """Return number of unique identities"""
        return self._identity_count
    
    def __contains__(self, identity_value: str) -> bool:
        """Check if identity value exists in registry"""
        return any(
            identity.identity_value == identity_value 
            for identity in self._identities.values()
        )
    
    def __repr__(self) -> str:
        """String representation of registry"""
        return (f"IdentityRegistry(identities={self._identity_count}, "
                f"records={self._total_records}, "
                f"types={len(self._identities_by_type)})")
