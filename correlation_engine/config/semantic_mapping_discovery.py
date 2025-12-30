"""
Semantic Mapping Discovery Service

Automatically discovers and loads semantic mapping configuration files from:
- Global Crow-Eye settings directory
- Wing-specific directories
- Built-in defaults

Supports multiple formats: YAML, JSON, Python
Implements priority-based merging: Wing > Global > Built-in
"""

import json
import logging
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import importlib.util
import sys

from correlation_engine.config.semantic_mapping import SemanticMapping, SemanticMappingManager

logger = logging.getLogger(__name__)


@dataclass
class MappingSource:
    """Information about a discovered mapping source."""
    path: Path
    format: str  # 'yaml', 'json', 'python'
    scope: str  # 'global', 'wing', 'built-in'
    wing_id: Optional[str] = None
    priority: int = 0  # Higher = higher priority


class SemanticMappingDiscovery:
    """
    Discovers and loads semantic mapping configurations.
    
    Search paths:
    1. Global: ~/.crow-eye/semantic_mappings/
    2. Wing-specific: <wing_dir>/semantic_mappings/
    3. Built-in: correlation_engine/config/default_mappings/
    
    Priority: Wing-specific > Global > Built-in
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize semantic mapping discovery service.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.discovered_sources: List[MappingSource] = []
        self.conflicts: List[Dict[str, Any]] = []
        
        # Default search paths
        self.global_search_paths = [
            Path.home() / ".crow-eye" / "semantic_mappings",
            Path.home() / ".crow-eye" / "config" / "semantic_mappings",
        ]
        
        self.built_in_path = Path(__file__).parent / "default_mappings"
    
    def discover_mappings(self, wing_dir: Optional[Path] = None) -> List[MappingSource]:
        """
        Discover all semantic mapping files.
        
        Args:
            wing_dir: Optional wing directory to search for wing-specific mappings
            
        Returns:
            List of discovered mapping sources
        """
        self.discovered_sources.clear()
        
        # Discover built-in mappings (priority 0)
        self._discover_in_directory(self.built_in_path, "built-in", priority=0)
        
        # Discover global mappings (priority 10)
        for global_path in self.global_search_paths:
            if global_path.exists():
                self._discover_in_directory(global_path, "global", priority=10)
        
        # Discover wing-specific mappings (priority 20)
        if wing_dir:
            wing_mapping_dir = wing_dir / "semantic_mappings"
            if wing_mapping_dir.exists():
                wing_id = wing_dir.name
                self._discover_in_directory(
                    wing_mapping_dir, "wing", priority=20, wing_id=wing_id
                )
        
        # Sort by priority (highest first)
        self.discovered_sources.sort(key=lambda s: s.priority, reverse=True)
        
        if self.debug_mode:
            logger.info(f"Discovered {len(self.discovered_sources)} mapping sources")
            for source in self.discovered_sources:
                logger.debug(f"  - {source.scope}: {source.path} (priority={source.priority})")
        
        return self.discovered_sources
    
    def _discover_in_directory(self, directory: Path, scope: str, 
                               priority: int, wing_id: Optional[str] = None):
        """
        Discover mapping files in a directory.
        
        Args:
            directory: Directory to search
            scope: Scope of mappings ('global', 'wing', 'built-in')
            priority: Priority level
            wing_id: Optional wing ID
        """
        if not directory.exists():
            return
        
        # Search for YAML files
        for yaml_file in directory.glob("*.yaml"):
            self.discovered_sources.append(MappingSource(
                path=yaml_file,
                format="yaml",
                scope=scope,
                wing_id=wing_id,
                priority=priority
            ))
        
        for yml_file in directory.glob("*.yml"):
            self.discovered_sources.append(MappingSource(
                path=yml_file,
                format="yaml",
                scope=scope,
                wing_id=wing_id,
                priority=priority
            ))
        
        # Search for JSON files
        for json_file in directory.glob("*.json"):
            self.discovered_sources.append(MappingSource(
                path=json_file,
                format="json",
                scope=scope,
                wing_id=wing_id,
                priority=priority
            ))
        
        # Search for Python files
        for py_file in directory.glob("*.py"):
            if py_file.name != "__init__.py":
                self.discovered_sources.append(MappingSource(
                    path=py_file,
                    format="python",
                    scope=scope,
                    wing_id=wing_id,
                    priority=priority
                ))
    
    def load_all_mappings(self, manager: SemanticMappingManager, 
                         wing_dir: Optional[Path] = None) -> int:
        """
        Discover and load all mappings into manager.
        
        Args:
            manager: SemanticMappingManager to load mappings into
            wing_dir: Optional wing directory
            
        Returns:
            Number of mappings loaded
        """
        # Discover all sources
        sources = self.discover_mappings(wing_dir)
        
        total_loaded = 0
        
        # Load in priority order (highest first)
        for source in sources:
            try:
                mappings = self.load_from_source(source)
                
                # Add to manager
                for mapping in mappings:
                    # Set scope and wing_id
                    mapping.scope = source.scope
                    mapping.wing_id = source.wing_id
                    mapping.mapping_source = source.scope
                    
                    manager.add_mapping(mapping)
                    total_loaded += 1
                
                if self.debug_mode:
                    logger.info(f"Loaded {len(mappings)} mappings from {source.path}")
                    
            except Exception as e:
                logger.error(f"Failed to load mappings from {source.path}: {e}")
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()
        
        logger.info(f"Loaded {total_loaded} total semantic mappings from {len(sources)} sources")
        
        return total_loaded
    
    def load_from_source(self, source: MappingSource) -> List[SemanticMapping]:
        """
        Load mappings from a source file.
        
        Args:
            source: MappingSource to load from
            
        Returns:
            List of SemanticMapping objects
        """
        if source.format == "yaml":
            return self.parse_yaml(source.path)
        elif source.format == "json":
            return self.parse_json(source.path)
        elif source.format == "python":
            return self.parse_python(source.path)
        else:
            logger.warning(f"Unknown format: {source.format}")
            return []
    
    def parse_yaml(self, file_path: Path) -> List[SemanticMapping]:
        """
        Parse YAML mapping file.
        
        Expected format:
        ```yaml
        mappings:
          - source: "SecurityLogs"
            field: "EventID"
            technical_value: "4624"
            semantic_value: "User Login"
            artifact_type: "Logs"
            category: "authentication"
            severity: "info"
        ```
        
        Args:
            file_path: Path to YAML file
            
        Returns:
            List of SemanticMapping objects
        """
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
            
            if not data or 'mappings' not in data:
                logger.warning(f"No 'mappings' key found in {file_path}")
                return []
            
            mappings = []
            for mapping_dict in data['mappings']:
                try:
                    # Handle conditions if present
                    if 'conditions' in mapping_dict and isinstance(mapping_dict['conditions'], list):
                        # Conditions are already in correct format
                        pass
                    
                    mapping = SemanticMapping(**mapping_dict)
                    mappings.append(mapping)
                except Exception as e:
                    logger.error(f"Failed to parse mapping in {file_path}: {e}")
                    if self.debug_mode:
                        logger.debug(f"Problematic mapping: {mapping_dict}")
            
            return mappings
            
        except Exception as e:
            logger.error(f"Failed to parse YAML file {file_path}: {e}")
            return []
    
    def parse_json(self, file_path: Path) -> List[SemanticMapping]:
        """
        Parse JSON mapping file.
        
        Expected format:
        ```json
        {
          "mappings": [
            {
              "source": "SecurityLogs",
              "field": "EventID",
              "technical_value": "4624",
              "semantic_value": "User Login",
              "artifact_type": "Logs",
              "category": "authentication",
              "severity": "info"
            }
          ]
        }
        ```
        
        Args:
            file_path: Path to JSON file
            
        Returns:
            List of SemanticMapping objects
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            if not data or 'mappings' not in data:
                logger.warning(f"No 'mappings' key found in {file_path}")
                return []
            
            mappings = []
            for mapping_dict in data['mappings']:
                try:
                    # Remove any non-field keys
                    mapping_dict.pop('_compiled_pattern', None)
                    
                    mapping = SemanticMapping(**mapping_dict)
                    mappings.append(mapping)
                except Exception as e:
                    logger.error(f"Failed to parse mapping in {file_path}: {e}")
                    if self.debug_mode:
                        logger.debug(f"Problematic mapping: {mapping_dict}")
            
            return mappings
            
        except Exception as e:
            logger.error(f"Failed to parse JSON file {file_path}: {e}")
            return []
    
    def parse_python(self, file_path: Path) -> List[SemanticMapping]:
        """
        Parse Python mapping file.
        
        Expected format:
        ```python
        from correlation_engine.config.semantic_mapping import SemanticMapping
        
        MAPPINGS = [
            SemanticMapping(
                source="SecurityLogs",
                field="EventID",
                technical_value="4624",
                semantic_value="User Login",
                artifact_type="Logs",
                category="authentication",
                severity="info"
            ),
        ]
        ```
        
        Args:
            file_path: Path to Python file
            
        Returns:
            List of SemanticMapping objects
        """
        try:
            # Load Python module dynamically
            spec = importlib.util.spec_from_file_location("mapping_module", file_path)
            if spec is None or spec.loader is None:
                logger.error(f"Failed to load Python module: {file_path}")
                return []
            
            module = importlib.util.module_from_spec(spec)
            sys.modules["mapping_module"] = module
            spec.loader.exec_module(module)
            
            # Look for MAPPINGS variable
            if not hasattr(module, 'MAPPINGS'):
                logger.warning(f"No 'MAPPINGS' variable found in {file_path}")
                return []
            
            mappings = module.MAPPINGS
            
            if not isinstance(mappings, list):
                logger.error(f"MAPPINGS must be a list in {file_path}")
                return []
            
            # Validate all are SemanticMapping objects
            valid_mappings = []
            for mapping in mappings:
                if isinstance(mapping, SemanticMapping):
                    valid_mappings.append(mapping)
                else:
                    logger.warning(f"Invalid mapping type in {file_path}: {type(mapping)}")
            
            return valid_mappings
            
        except Exception as e:
            logger.error(f"Failed to parse Python file {file_path}: {e}")
            if self.debug_mode:
                import traceback
                traceback.print_exc()
            return []
    
    def detect_conflicts(self, manager: SemanticMappingManager) -> List[Dict[str, Any]]:
        """
        Detect conflicts between mappings from different sources.
        
        A conflict occurs when multiple mappings match the same
        source/field/value combination but have different semantic values.
        
        Args:
            manager: SemanticMappingManager to check
            
        Returns:
            List of conflict descriptions
        """
        self.conflicts.clear()
        
        # Group mappings by (source, field, technical_value)
        mapping_groups: Dict[tuple, List[SemanticMapping]] = {}
        
        for mappings_list in manager.global_mappings.values():
            for mapping in mappings_list:
                key = (mapping.source, mapping.field, mapping.technical_value)
                if key not in mapping_groups:
                    mapping_groups[key] = []
                mapping_groups[key].append(mapping)
        
        # Check for conflicts
        for key, mappings in mapping_groups.items():
            if len(mappings) > 1:
                # Check if semantic values differ
                semantic_values = set(m.semantic_value for m in mappings)
                if len(semantic_values) > 1:
                    conflict = {
                        'source': key[0],
                        'field': key[1],
                        'technical_value': key[2],
                        'mappings': [
                            {
                                'semantic_value': m.semantic_value,
                                'mapping_source': m.mapping_source,
                                'confidence': m.confidence
                            }
                            for m in mappings
                        ]
                    }
                    self.conflicts.append(conflict)
        
        if self.conflicts:
            logger.warning(f"Detected {len(self.conflicts)} mapping conflicts")
            for conflict in self.conflicts:
                logger.warning(
                    f"Conflict: {conflict['source']}.{conflict['field']}={conflict['technical_value']} "
                    f"has {len(conflict['mappings'])} different semantic values"
                )
        
        return self.conflicts
    
    def get_coverage_statistics(self, manager: SemanticMappingManager) -> Dict[str, Any]:
        """
        Calculate coverage statistics for semantic mappings.
        
        Args:
            manager: SemanticMappingManager to analyze
            
        Returns:
            Dictionary with coverage statistics
        """
        stats = {
            'total_mappings': 0,
            'by_artifact_type': {},
            'by_category': {},
            'by_severity': {},
            'by_source': {},
            'with_patterns': 0,
            'with_conditions': 0,
        }
        
        all_mappings = manager.get_all_mappings("global")
        stats['total_mappings'] = len(all_mappings)
        
        for mapping in all_mappings:
            # By artifact type
            if mapping.artifact_type:
                stats['by_artifact_type'][mapping.artifact_type] = \
                    stats['by_artifact_type'].get(mapping.artifact_type, 0) + 1
            
            # By category
            if mapping.category:
                stats['by_category'][mapping.category] = \
                    stats['by_category'].get(mapping.category, 0) + 1
            
            # By severity
            if mapping.severity:
                stats['by_severity'][mapping.severity] = \
                    stats['by_severity'].get(mapping.severity, 0) + 1
            
            # By source
            if mapping.mapping_source:
                stats['by_source'][mapping.mapping_source] = \
                    stats['by_source'].get(mapping.mapping_source, 0) + 1
            
            # With patterns
            if mapping.pattern:
                stats['with_patterns'] += 1
            
            # With conditions
            if mapping.conditions:
                stats['with_conditions'] += 1
        
        return stats


# Convenience function

def discover_and_load_mappings(manager: SemanticMappingManager, 
                              wing_dir: Optional[Path] = None,
                              debug_mode: bool = False) -> int:
    """
    Convenience function to discover and load all semantic mappings.
    
    Args:
        manager: SemanticMappingManager to load into
        wing_dir: Optional wing directory
        debug_mode: Enable debug logging
        
    Returns:
        Number of mappings loaded
    """
    discovery = SemanticMappingDiscovery(debug_mode=debug_mode)
    return discovery.load_all_mappings(manager, wing_dir)
