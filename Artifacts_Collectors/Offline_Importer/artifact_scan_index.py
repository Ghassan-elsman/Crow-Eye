"""
Artifact Scan Index Module

This module provides classes for tracking scanned artifacts and their metadata
for the Case Management Integration feature.

Classes:
    ScannedArtifact: Dataclass representing a scanned artifact
    ArtifactScanIndex: Manager for the artifact scan index with JSON persistence
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any


logger = logging.getLogger(__name__)


@dataclass
class ScannedArtifact:
    """
    Represents a scanned artifact with metadata.
    
    Attributes:
        artifact_id: Unique identifier for the artifact
        artifact_type: Type of artifact (Registry, Prefetch, JumpLists, etc.)
        original_path: Original file path where artifact was found
        current_path: Current path (may differ if collected to case directory)
        file_size: Size of the artifact file in bytes
        file_hash: Optional SHA256 hash of the file
        scan_timestamp: ISO8601 timestamp when artifact was scanned
        collected: Whether artifact has been collected to case directory
        parsed: Whether artifact has been parsed
        parse_timestamp: Optional ISO8601 timestamp when artifact was parsed
    """
    artifact_id: str
    artifact_type: str
    original_path: str
    current_path: str
    file_size: int
    file_hash: Optional[str] = None
    scan_timestamp: str = ""
    collected: bool = False
    parsed: bool = False
    parse_timestamp: Optional[str] = None
    
    def __post_init__(self):
        """Set scan_timestamp to current time if not provided."""
        if not self.scan_timestamp:
            self.scan_timestamp = datetime.now().isoformat()


class ArtifactScanIndex:
    """
    Manages the index of scanned artifacts for a case.
    
    Provides methods to add, retrieve, and update artifact metadata,
    with JSON persistence to disk.
    """
    
    def __init__(self, case_root: str):
        """
        Initialize the ArtifactScanIndex.
        
        Args:
            case_root: Root directory of the case
        """
        self.case_root = case_root
        self.index_path = os.path.join(case_root, ".artifact_scan_index.json")
        self.artifacts: Dict[str, ScannedArtifact] = {}
        
        # Load existing index if it exists
        if os.path.exists(self.index_path):
            try:
                self.load()
            except Exception as e:
                logger.error(f"Failed to load artifact scan index: {e}")
                # Continue with empty index
    
    def add_artifact(self, artifact: ScannedArtifact) -> None:
        """
        Add a scanned artifact to the index.
        
        Args:
            artifact: ScannedArtifact object to add
        """
        self.artifacts[artifact.artifact_id] = artifact
        logger.debug(f"Added artifact {artifact.artifact_id} to index")
    
    def get_artifacts_by_type(self, artifact_type: str) -> List[ScannedArtifact]:
        """
        Get all artifacts of a specific type.
        
        Args:
            artifact_type: Type of artifacts to retrieve
            
        Returns:
            List of ScannedArtifact objects matching the type
        """
        return [
            artifact for artifact in self.artifacts.values()
            if artifact.artifact_type == artifact_type
        ]
    
    def get_all_artifacts(self) -> List[ScannedArtifact]:
        """
        Get all scanned artifacts.
        
        Returns:
            List of all ScannedArtifact objects
        """
        return list(self.artifacts.values())
    
    def mark_as_collected(self, artifact_id: str, new_path: str) -> None:
        """
        Mark an artifact as collected and update its current path.
        
        Args:
            artifact_id: ID of the artifact to mark
            new_path: New path where artifact was collected
            
        Raises:
            KeyError: If artifact_id not found in index
        """
        if artifact_id not in self.artifacts:
            raise KeyError(f"Artifact {artifact_id} not found in index")
        
        self.artifacts[artifact_id].collected = True
        self.artifacts[artifact_id].current_path = new_path
        logger.info(f"Marked artifact {artifact_id} as collected at {new_path}")
    
    def mark_as_parsed(self, artifact_id: str) -> None:
        """
        Mark an artifact as parsed.
        
        Args:
            artifact_id: ID of the artifact to mark
            
        Raises:
            KeyError: If artifact_id not found in index
        """
        try:
            if artifact_id not in self.artifacts:
                raise KeyError(f"Artifact {artifact_id} not found in index")
            
            self.artifacts[artifact_id].parsed = True
            self.artifacts[artifact_id].parse_timestamp = datetime.now().isoformat()
            logger.debug(f"Marked artifact {artifact_id} as parsed")
        except Exception as e:
            # Log the full exception with traceback for debugging
            logger.error(f"Exception in mark_as_parsed for artifact {artifact_id}: {e}", exc_info=True)
            # Re-raise to let caller handle it
            raise
    
    def save(self) -> None:
        """
        Persist the index to disk as JSON.
        
        Raises:
            IOError: If unable to write to disk
        """
        try:
            # Ensure case root directory exists
            os.makedirs(self.case_root, exist_ok=True)
            
            # Convert artifacts to serializable format
            data = {
                "artifacts": [asdict(artifact) for artifact in self.artifacts.values()],
                "last_updated": datetime.now().isoformat()
            }
            
            # Write to file with pretty formatting
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Saved artifact scan index to {self.index_path}")
            print(f"Saved artifact scan index to {self.index_path}")
        except Exception as e:
            error_msg = f"Failed to save artifact scan index: {e}"
            logger.error(error_msg, exc_info=True)
            print(f"[ERROR] {error_msg}")
            raise IOError(error_msg)
    
    def load(self) -> None:
        """
        Load the index from disk.
        
        Raises:
            IOError: If unable to read from disk
            json.JSONDecodeError: If JSON is malformed
        """
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Reconstruct artifacts from JSON
            self.artifacts = {}
            for artifact_data in data.get("artifacts", []):
                artifact = ScannedArtifact(**artifact_data)
                self.artifacts[artifact.artifact_id] = artifact
            
            logger.info(f"Loaded {len(self.artifacts)} artifacts from {self.index_path}")
        except FileNotFoundError:
            logger.warning(f"Artifact scan index not found at {self.index_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Malformed JSON in artifact scan index: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load artifact scan index: {e}")
            raise IOError(f"Failed to load artifact scan index: {e}")
