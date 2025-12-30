"""
Identifier Correlation Engine with anchor assignment.

This module implements the core correlation logic for the Crow-Eye Correlation Engine,
building an in-memory state of identities, anchors, and evidence rows.
"""

import logging
from datetime import timedelta
from typing import Dict, Optional, List
from uuid import uuid4

from correlation_engine.engine.data_structures import (
    Identity, Anchor, EvidenceRow, ExtractedValues
)
from correlation_engine.engine.identity_extractor import IdentityExtractor
from correlation_engine.config.identifier_extraction_config import WingsConfig

logger = logging.getLogger(__name__)


class IdentifierCorrelationEngine:
    """
    Build in-memory correlation state and manage identities/anchors.
    
    Maintains the authoritative in-memory engine state dictionary that maps
    identity keys to identities, anchors, and evidence rows.
    """
    
    def __init__(self, config: WingsConfig):
        """
        Initialize correlation engine.
        
        Args:
            config: Wings configuration
        """
        self.config = config
        self.engine_state: Dict[str, Identity] = {}
        self.time_window = timedelta(minutes=config.get_anchor_time_window())
        self.identity_extractor = IdentityExtractor()
        
        # Statistics
        self.stats = {
            'identities_created': 0,
            'anchors_created': 0,
            'evidence_processed': 0,
            'names_extracted': 0,
            'paths_extracted': 0
        }
        
        logger.info(f"IdentifierCorrelationEngine initialized with {self.time_window.total_seconds()/60} minute time window")
    
    def process_evidence(self, extracted: ExtractedValues):
        """
        Process extracted values and create/update identities and anchors.
        
        Args:
            extracted: Values extracted from a Feather row
        """
        if not extracted.has_data():
            logger.debug("No data in extracted values, skipping")
            return
        
        timestamp = extracted.get_primary_timestamp()
        if not timestamp:
            logger.warning(f"No timestamp for evidence from {extracted.artifact_name}, skipping")
            return
        
        # Create evidence row
        evidence = EvidenceRow(
            artifact=extracted.artifact_name,
            table=extracted.table_name,
            row_id=extracted.row_id,
            timestamp=timestamp,
            semantic={}
        )
        
        # Extract identities from names
        if self.config.identifier_extraction.extract_from_names:
            for name in extracted.names:
                identities = self.identity_extractor.extract_identities_from_name(name)
                for identity_type, normalized_value in identities:
                    evidence.semantic['name'] = name
                    self._process_identity(identity_type, normalized_value, evidence)
                    self.stats['names_extracted'] += 1
        
        # Extract identities from paths
        if self.config.identifier_extraction.extract_from_paths:
            for path in extracted.paths:
                # Extract path identity and optionally name from path
                extract_name = self.config.identifier_extraction.extract_from_names
                identities = self.identity_extractor.extract_identities_from_path(path, extract_name)
                for identity_type, normalized_value in identities:
                    if identity_type == "path":
                        evidence.semantic['path'] = path
                        self.stats['paths_extracted'] += 1
                    elif identity_type == "name":
                        evidence.semantic['name'] = normalized_value
                        self.stats['names_extracted'] += 1
                    self._process_identity(identity_type, normalized_value, evidence)
        
        self.stats['evidence_processed'] += 1
    
    def _process_identity(self, identity_type: str, normalized_value: str, evidence: EvidenceRow):
        """
        Process a single identity and assign evidence to appropriate anchor.
        
        Args:
            identity_type: Type of identity ("name", "path", "hash")
            normalized_value: Normalized identity value
            evidence: Evidence row to assign
        """
        # Generate identity key
        identity_key = self.identity_extractor.generate_identity_key(identity_type, normalized_value)
        if not identity_key:
            logger.warning(f"Failed to generate identity key for {identity_type}:{normalized_value}")
            return
        
        # Get or create identity
        identity = self.get_or_create_identity(identity_key, identity_type, normalized_value)
        
        # Update seen times
        identity.update_seen_times(evidence.timestamp)
        
        # Assign evidence to anchor
        self.assign_to_anchor(identity, evidence)
    
    def get_or_create_identity(self, identity_key: str, identity_type: str, 
                               identity_value: str) -> Identity:
        """
        Get existing identity or create new one.
        
        Args:
            identity_key: Identity key (type:normalized_value)
            identity_type: Type of identity
            identity_value: Normalized value
            
        Returns:
            Identity object
        """
        if identity_key in self.engine_state:
            return self.engine_state[identity_key]
        
        # Create new identity
        identity = Identity(
            identity_id=str(uuid4()),
            identity_type=identity_type,
            identity_value=identity_value
        )
        
        self.engine_state[identity_key] = identity
        self.stats['identities_created'] += 1
        
        logger.debug(f"Created new identity: {identity_key}")
        return identity
    
    def assign_to_anchor(self, identity: Identity, evidence: EvidenceRow):
        """
        Assign evidence to an anchor based on timestamp windows.
        
        Algorithm:
        1. Check if evidence timestamp falls within any existing anchor window
        2. If yes, add to that anchor and update end_time
        3. If no, create new anchor
        
        Args:
            identity: Identity to assign evidence to
            evidence: Evidence row to assign
        """
        # Check existing anchors
        for anchor in identity.anchors:
            if anchor.contains_timestamp(evidence.timestamp, int(self.time_window.total_seconds() / 60)):
                # Add evidence to existing anchor
                anchor.add_evidence(evidence)
                logger.debug(f"Added evidence to existing anchor {anchor.anchor_id}")
                return
        
        # No matching anchor found - create new one
        new_anchor = Anchor()
        new_anchor.add_evidence(evidence)
        identity.anchors.append(new_anchor)
        self.stats['anchors_created'] += 1
        
        logger.debug(f"Created new anchor {new_anchor.anchor_id} for identity {identity.get_identity_key()}")
    
    def get_identity_by_key(self, identity_key: str) -> Optional[Identity]:
        """
        Get identity by key.
        
        Args:
            identity_key: Identity key to lookup
            
        Returns:
            Identity or None if not found
        """
        return self.engine_state.get(identity_key)
    
    def get_all_identities(self) -> List[Identity]:
        """
        Get all identities in engine state.
        
        Returns:
            List of all identities
        """
        return list(self.engine_state.values())
    
    def get_identity_count(self) -> int:
        """Get total number of identities."""
        return len(self.engine_state)
    
    def get_anchor_count(self) -> int:
        """Get total number of anchors across all identities."""
        return sum(len(identity.anchors) for identity in self.engine_state.values())
    
    def get_evidence_count(self) -> int:
        """Get total number of evidence rows across all anchors."""
        count = 0
        for identity in self.engine_state.values():
            for anchor in identity.anchors:
                count += len(anchor.rows)
        return count
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get engine statistics.
        
        Returns:
            Dictionary of statistics
        """
        return {
            **self.stats,
            'total_identities': self.get_identity_count(),
            'total_anchors': self.get_anchor_count(),
            'total_evidence': self.get_evidence_count()
        }
    
    def clear_state(self):
        """Clear all engine state (for testing or reset)."""
        self.engine_state.clear()
        self.stats = {
            'identities_created': 0,
            'anchors_created': 0,
            'evidence_processed': 0,
            'names_extracted': 0,
            'paths_extracted': 0
        }
        logger.info("Engine state cleared")
    
    def get_engine_state_dict(self) -> Dict:
        """
        Get engine state as dictionary (for persistence).
        
        Returns:
            Dictionary representation of engine state
        """
        state_dict = {}
        
        for identity_key, identity in self.engine_state.items():
            state_dict[identity_key] = {
                'identity_id': identity.identity_id,
                'identity_type': identity.identity_type,
                'identity_value': identity.identity_value,
                'first_seen': identity.first_seen.isoformat() if identity.first_seen else None,
                'last_seen': identity.last_seen.isoformat() if identity.last_seen else None,
                'anchors': [
                    {
                        'anchor_id': anchor.anchor_id,
                        'start_time': anchor.start_time.isoformat() if anchor.start_time else None,
                        'end_time': anchor.end_time.isoformat() if anchor.end_time else None,
                        'rows': [
                            {
                                'artifact': row.artifact,
                                'table': row.table,
                                'row_id': row.row_id,
                                'timestamp': row.timestamp.isoformat(),
                                'semantic': row.semantic
                            }
                            for row in anchor.rows
                        ]
                    }
                    for anchor in identity.anchors
                ]
            }
        
        return state_dict
