"""
Message Metadata Model for EYE.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MessageMetadata:
    """
    Extended metadata for conversation messages.
    
    
    Attributes:
        preserve_evidence: Flag indicating message contains forensic evidence
        evidence_patterns: List of detected evidence pattern types
        evidence_confidence: Confidence score for evidence detection (0.0-1.0)
        pinned: Flag indicating message is manually pinned
        pinned_at: ISO timestamp when message was pinned
        is_summary: Flag indicating message is a summary of other messages
        summarized_count: Number of messages this summary represents
        message_hash: SHA-256 hash of message content for audit trail
        created_at: ISO timestamp when metadata was created
    """
    
    # Evidence preservation
    preserve_evidence: bool = False
    evidence_patterns: Optional[List[str]] = None
    evidence_confidence: float = 0.0
    
    # User actions
    pinned: bool = False
    pinned_at: Optional[str] = None
    
    # Summarization tracking
    is_summary: bool = False
    summarized_count: int = 0
    
    # Audit trail
    message_hash: Optional[str] = None
    created_at: Optional[str] = None
    
    def __post_init__(self):
        """Initialize created_at timestamp if not provided."""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of metadata
        """
        return {
            "preserve_evidence": self.preserve_evidence,
            "evidence_patterns": self.evidence_patterns,
            "evidence_confidence": self.evidence_confidence,
            "pinned": self.pinned,
            "pinned_at": self.pinned_at,
            "is_summary": self.is_summary,
            "summarized_count": self.summarized_count,
            "message_hash": self.message_hash,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MessageMetadata':
        """
        Create MessageMetadata from dictionary.
        
        Args:
            data: Dictionary containing metadata fields
            
        Returns:
            MessageMetadata instance
        """
        # Filter to only include fields that exist in the dataclass
        valid_fields = {k: v for k, v in data.items() if k in cls.__annotations__}
        return cls(**valid_fields)
