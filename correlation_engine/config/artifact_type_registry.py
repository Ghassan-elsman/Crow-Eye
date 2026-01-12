"""
Artifact Type Registry

Centralized registry for artifact type definitions, eliminating hard-coded lists
throughout the codebase. Provides a single source of truth for artifact types,
their weights, tiers, and other metadata.

This module implements a singleton pattern to ensure consistent artifact type
information across the entire application.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class ArtifactType:
    """Definition of an artifact type"""
    id: str
    name: str
    description: str
    default_weight: float
    default_tier: int
    anchor_priority: int
    category: str
    forensic_strength: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'default_weight': self.default_weight,
            'default_tier': self.default_tier,
            'anchor_priority': self.anchor_priority,
            'category': self.category,
            'forensic_strength': self.forensic_strength
        }


class ArtifactTypeRegistry:
    """
    Singleton registry for artifact type definitions.
    
    Provides centralized access to artifact type metadata including
    default weights, tiers, and anchor priorities.
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """Singleton pattern implementation"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the registry (only once due to singleton)"""
        if self._initialized:
            return
        
        self._artifacts: Dict[str, ArtifactType] = {}
        self._config_path: Optional[Path] = None
        self._version: str = "1.0"
        self._cache_valid = False
        
        # Load default configuration
        self._load_default_configuration()
        self._initialized = True
    
    def _load_default_configuration(self):
        """Load artifact types from default configuration file"""
        try:
            # Try to find the configuration file
            config_path = self._find_config_file()
            
            if config_path and config_path.exists():
                self._load_from_file(config_path)
                logger.info(f"Loaded artifact type registry from {config_path}")
            else:
                # Create default configuration if file doesn't exist
                self._create_default_configuration()
                logger.info("Created default artifact type registry")
        
        except Exception as e:
            logger.error(f"Failed to load artifact type registry: {e}")
            # Fall back to hard-coded defaults
            self._load_hardcoded_defaults()
            logger.warning("Using hard-coded artifact type defaults")
    
    def _find_config_file(self) -> Optional[Path]:
        """Find the artifact types configuration file"""
        # Try multiple possible locations
        possible_paths = [
            Path(__file__).parent / "artifact_types.json",
            Path("Crow-Eye/correlation_engine/config/artifact_types.json"),
            Path("correlation_engine/config/artifact_types.json"),
            Path("config/artifact_types.json")
        ]
        
        for path in possible_paths:
            if path.exists():
                self._config_path = path
                return path
        
        # Default to the first path for creation
        self._config_path = possible_paths[0]
        return self._config_path
    
    def _load_from_file(self, config_path: Path):
        """Load artifact types from JSON file"""
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
            
            # Validate schema
            if 'artifact_types' not in data:
                raise ValueError("Invalid artifact types configuration: missing 'artifact_types' key")
            
            # Store version
            self._version = data.get('version', '1.0')
            
            # Clear existing artifacts
            self._artifacts.clear()
            
            # Load artifact types
            for artifact_data in data['artifact_types']:
                artifact = ArtifactType(
                    id=artifact_data['id'],
                    name=artifact_data['name'],
                    description=artifact_data['description'],
                    default_weight=artifact_data['default_weight'],
                    default_tier=artifact_data['default_tier'],
                    anchor_priority=artifact_data['anchor_priority'],
                    category=artifact_data['category'],
                    forensic_strength=artifact_data['forensic_strength']
                )
                self._artifacts[artifact.id] = artifact
            
            self._cache_valid = True
            logger.info(f"Loaded {len(self._artifacts)} artifact types from {config_path}")
        
        except Exception as e:
            logger.error(f"Failed to load artifact types from {config_path}: {e}")
            raise
    
    def _create_default_configuration(self):
        """Create default artifact types configuration file"""
        default_config = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "version": "1.0",
            "description": "Centralized artifact type definitions for Crow-Eye Correlation Engine",
            "artifact_types": [
                {
                    "id": "Logs",
                    "name": "Event Logs",
                    "description": "Windows Event Logs (Security, System, Application)",
                    "default_weight": 0.4,
                    "default_tier": 1,
                    "anchor_priority": 1,
                    "category": "primary_evidence",
                    "forensic_strength": "high"
                },
                {
                    "id": "Prefetch",
                    "name": "Prefetch Files",
                    "description": "Windows Prefetch execution artifacts",
                    "default_weight": 0.3,
                    "default_tier": 1,
                    "anchor_priority": 2,
                    "category": "primary_evidence",
                    "forensic_strength": "high"
                },
                {
                    "id": "SRUM",
                    "name": "System Resource Usage Monitor",
                    "description": "Windows SRUM database artifacts",
                    "default_weight": 0.2,
                    "default_tier": 2,
                    "anchor_priority": 3,
                    "category": "supporting_evidence",
                    "forensic_strength": "medium"
                },
                {
                    "id": "AmCache",
                    "name": "AmCache",
                    "description": "Windows AmCache execution artifacts",
                    "default_weight": 0.15,
                    "default_tier": 2,
                    "anchor_priority": 4,
                    "category": "supporting_evidence",
                    "forensic_strength": "medium"
                },
                {
                    "id": "ShimCache",
                    "name": "ShimCache",
                    "description": "Windows Application Compatibility Cache",
                    "default_weight": 0.15,
                    "default_tier": 2,
                    "anchor_priority": 5,
                    "category": "supporting_evidence",
                    "forensic_strength": "medium"
                },
                {
                    "id": "Jumplists",
                    "name": "Jump Lists",
                    "description": "Windows Jump List artifacts",
                    "default_weight": 0.1,
                    "default_tier": 3,
                    "anchor_priority": 6,
                    "category": "contextual_evidence",
                    "forensic_strength": "low"
                },
                {
                    "id": "LNK",
                    "name": "LNK Files",
                    "description": "Windows shortcut files",
                    "default_weight": 0.1,
                    "default_tier": 3,
                    "anchor_priority": 7,
                    "category": "contextual_evidence",
                    "forensic_strength": "low"
                },
                {
                    "id": "MFT",
                    "name": "Master File Table",
                    "description": "NTFS Master File Table entries",
                    "default_weight": 0.05,
                    "default_tier": 4,
                    "anchor_priority": 8,
                    "category": "background_evidence",
                    "forensic_strength": "low"
                },
                {
                    "id": "USN",
                    "name": "USN Journal",
                    "description": "NTFS Update Sequence Number Journal",
                    "default_weight": 0.05,
                    "default_tier": 4,
                    "anchor_priority": 9,
                    "category": "background_evidence",
                    "forensic_strength": "low"
                },
                {
                    "id": "Registry",
                    "name": "Registry",
                    "description": "Windows Registry artifacts",
                    "default_weight": 0.1,
                    "default_tier": 3,
                    "anchor_priority": 10,
                    "category": "contextual_evidence",
                    "forensic_strength": "medium"
                },
                {
                    "id": "Browser",
                    "name": "Browser History",
                    "description": "Web browser history and artifacts",
                    "default_weight": 0.1,
                    "default_tier": 3,
                    "anchor_priority": 11,
                    "category": "contextual_evidence",
                    "forensic_strength": "low"
                }
            ]
        }
        
        try:
            # Ensure directory exists
            if self._config_path:
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Write configuration file
                with open(self._config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)
                
                # Load the configuration we just created
                self._load_from_file(self._config_path)
                logger.info(f"Created default artifact types configuration at {self._config_path}")
        
        except Exception as e:
            logger.error(f"Failed to create default configuration: {e}")
            # Fall back to hard-coded defaults
            self._load_hardcoded_defaults()
    
    def _load_hardcoded_defaults(self):
        """Load hard-coded default artifact types as last resort fallback"""
        defaults = [
            ("Logs", "Event Logs", 0.4, 1, 1),
            ("Prefetch", "Prefetch Files", 0.3, 1, 2),
            ("SRUM", "System Resource Usage Monitor", 0.2, 2, 3),
            ("AmCache", "AmCache", 0.15, 2, 4),
            ("ShimCache", "ShimCache", 0.15, 2, 5),
            ("Jumplists", "Jump Lists", 0.1, 3, 6),
            ("LNK", "LNK Files", 0.1, 3, 7),
            ("MFT", "Master File Table", 0.05, 4, 8),
            ("USN", "USN Journal", 0.05, 4, 9),
            ("Registry", "Registry", 0.1, 3, 10),
            ("Browser", "Browser History", 0.1, 3, 11)
        ]
        
        self._artifacts.clear()
        
        for artifact_id, name, weight, tier, priority in defaults:
            artifact = ArtifactType(
                id=artifact_id,
                name=name,
                description=f"{name} artifacts",
                default_weight=weight,
                default_tier=tier,
                anchor_priority=priority,
                category="evidence",
                forensic_strength="medium"
            )
            self._artifacts[artifact_id] = artifact
        
        self._cache_valid = True
        logger.info(f"Loaded {len(self._artifacts)} hard-coded default artifact types")
    
    def get_all_types(self) -> List[str]:
        """
        Get list of all artifact type IDs.
        
        Returns:
            List of artifact type IDs sorted by anchor priority
        """
        artifacts = sorted(self._artifacts.values(), key=lambda a: a.anchor_priority)
        return [a.id for a in artifacts]
    
    def get_artifact(self, artifact_id: str) -> Optional[ArtifactType]:
        """
        Get artifact type definition by ID.
        
        Args:
            artifact_id: Artifact type ID
            
        Returns:
            ArtifactType object or None if not found
        """
        return self._artifacts.get(artifact_id)
    
    def get_default_weight(self, artifact_id: str) -> float:
        """
        Get default weight for an artifact type.
        
        Args:
            artifact_id: Artifact type ID
            
        Returns:
            Default weight (0.1 if artifact not found)
        """
        artifact = self._artifacts.get(artifact_id)
        return artifact.default_weight if artifact else 0.1
    
    def get_default_tier(self, artifact_id: str) -> int:
        """
        Get default tier for an artifact type.
        
        Args:
            artifact_id: Artifact type ID
            
        Returns:
            Default tier (3 if artifact not found)
        """
        artifact = self._artifacts.get(artifact_id)
        return artifact.default_tier if artifact else 3
    
    def get_anchor_priority_list(self) -> List[str]:
        """
        Get artifact types sorted by anchor priority.
        
        Returns:
            List of artifact type IDs sorted by anchor priority
        """
        artifacts = sorted(self._artifacts.values(), key=lambda a: a.anchor_priority)
        return [a.id for a in artifacts]
    
    def get_default_weights_dict(self) -> Dict[str, float]:
        """
        Get dictionary of all default weights.
        
        Returns:
            Dictionary mapping artifact type ID to default weight
        """
        return {
            artifact_id: artifact.default_weight
            for artifact_id, artifact in self._artifacts.items()
        }
    
    def register_artifact(self, artifact: ArtifactType) -> bool:
        """
        Register a new artifact type or update existing one.
        
        Args:
            artifact: ArtifactType to register
            
        Returns:
            True if registered successfully, False otherwise
        """
        try:
            self._artifacts[artifact.id] = artifact
            self._cache_valid = False  # Invalidate cache
            logger.info(f"Registered artifact type: {artifact.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to register artifact type {artifact.id}: {e}")
            return False
    
    def reload(self) -> bool:
        """
        Reload artifact types from configuration file.
        
        Returns:
            True if reloaded successfully, False otherwise
        """
        try:
            if self._config_path and self._config_path.exists():
                self._load_from_file(self._config_path)
                logger.info("Reloaded artifact type registry")
                return True
            else:
                logger.warning("Cannot reload: configuration file not found")
                return False
        except Exception as e:
            logger.error(f"Failed to reload artifact type registry: {e}")
            return False
    
    def is_valid_artifact_type(self, artifact_id: str) -> bool:
        """
        Check if an artifact type ID is valid.
        
        Args:
            artifact_id: Artifact type ID to check
            
        Returns:
            True if valid, False otherwise
        """
        return artifact_id in self._artifacts
    
    def get_artifacts_by_category(self, category: str) -> List[ArtifactType]:
        """
        Get all artifact types in a specific category.
        
        Args:
            category: Category name
            
        Returns:
            List of ArtifactType objects in the category
        """
        return [
            artifact for artifact in self._artifacts.values()
            if artifact.category == category
        ]
    
    def get_artifacts_by_forensic_strength(self, strength: str) -> List[ArtifactType]:
        """
        Get all artifact types with a specific forensic strength.
        
        Args:
            strength: Forensic strength ('high', 'medium', 'low')
            
        Returns:
            List of ArtifactType objects with the specified strength
        """
        return [
            artifact for artifact in self._artifacts.values()
            if artifact.forensic_strength == strength
        ]
    
    def get_version(self) -> str:
        """Get registry version"""
        return self._version
    
    def get_artifact_count(self) -> int:
        """Get number of registered artifact types"""
        return len(self._artifacts)


# Global singleton instance
_registry = ArtifactTypeRegistry()


def get_registry() -> ArtifactTypeRegistry:
    """
    Get the global artifact type registry instance.
    
    Returns:
        ArtifactTypeRegistry singleton instance
    """
    return _registry
