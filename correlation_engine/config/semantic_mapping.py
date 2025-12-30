"""
Semantic Mapping Manager

Manages semantic value mappings for correlation results with universal artifact support.
Maps technical values (e.g., Event IDs, status codes, file patterns) to human-readable semantic meanings.

Enhanced Features:
- Artifact-specific mappings for ALL forensic artifacts
- Pattern matching with regex support
- Multi-field conditional matching
- Confidence scoring
- Mapping source tracking (global/wing/built-in)
"""

import json
import logging
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class SemanticMapping:
    """
    Enhanced semantic value mapping with universal artifact support.
    
    Maps technical values to human-readable semantic meanings with support for:
    - Pattern matching (regex)
    - Multi-field conditions
    - Confidence scoring
    - Artifact-specific rules
    """
    source: str  # e.g., "SecurityLogs", "Prefetch", "Registry"
    field: str  # e.g., "EventID", "Status", "executable_name"
    technical_value: str  # e.g., "4624", "chrome.exe"
    semantic_value: str  # e.g., "User Login", "Web Browser"
    description: str = ""  # Optional detailed description
    
    # NEW: Enhanced fields for Task 4
    artifact_type: str = ""  # Artifact type: "Logs", "Prefetch", "Registry", etc.
    category: str = ""  # Semantic category: "authentication", "execution", "network"
    severity: str = "info"  # Severity: "info", "low", "medium", "high", "critical"
    pattern: str = ""  # Regex pattern for matching (empty = exact match)
    conditions: List[Dict[str, Any]] = field(default_factory=list)  # Multi-field conditions
    confidence: float = 1.0  # Confidence score (0.0 to 1.0)
    mapping_source: str = "built-in"  # Source: "built-in", "global", "wing"
    
    # Scope fields (existing)
    scope: str = "global"  # "global", "wing", "pipeline"
    wing_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    
    # Compiled pattern cache
    _compiled_pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)
    
    def compile_pattern(self):
        """Compile regex pattern for efficient matching."""
        if self.pattern and not self._compiled_pattern:
            try:
                self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{self.pattern}': {e}")
                self._compiled_pattern = None
    
    def matches(self, value: str) -> bool:
        """
        Check if value matches this mapping.
        
        Args:
            value: Value to check
            
        Returns:
            True if matches, False otherwise
        """
        if self.pattern:
            # Pattern matching
            if not self._compiled_pattern:
                self.compile_pattern()
            
            if self._compiled_pattern:
                return bool(self._compiled_pattern.search(value))
            return False
        else:
            # Exact matching (case-insensitive)
            return value.lower() == self.technical_value.lower()
    
    def evaluate_conditions(self, record: Dict[str, Any]) -> bool:
        """
        Evaluate multi-field conditions against a record.
        
        Conditions format:
        [
            {"field": "LogonType", "operator": "equals", "value": "2"},
            {"field": "Status", "operator": "in", "value": ["0x0", "0xC0000064"]}
        ]
        
        Args:
            record: Record dictionary to evaluate
            
        Returns:
            True if all conditions match, False otherwise
        """
        if not self.conditions:
            return True  # No conditions = always match
        
        for condition in self.conditions:
            field_name = condition.get("field")
            operator = condition.get("operator", "equals")
            expected_value = condition.get("value")
            
            if field_name not in record:
                return False  # Field not present
            
            actual_value = record[field_name]
            
            # Evaluate based on operator
            if operator == "equals":
                if str(actual_value).lower() != str(expected_value).lower():
                    return False
            
            elif operator == "in":
                if str(actual_value) not in expected_value:
                    return False
            
            elif operator == "regex":
                if not re.search(expected_value, str(actual_value), re.IGNORECASE):
                    return False
            
            elif operator == "greater_than":
                try:
                    if float(actual_value) <= float(expected_value):
                        return False
                except (ValueError, TypeError):
                    return False
            
            elif operator == "less_than":
                try:
                    if float(actual_value) >= float(expected_value):
                        return False
                except (ValueError, TypeError):
                    return False
            
            elif operator == "contains":
                if expected_value.lower() not in str(actual_value).lower():
                    return False
        
        return True  # All conditions matched


class SemanticMappingManager:
    """
    Enhanced semantic mapping manager with universal artifact support.
    
    Provides hierarchical mapping system with:
    1. Global mappings (apply to all Wings)
    2. Pipeline-specific mappings (apply to all Wings in a Pipeline)
    3. Wing-specific mappings (apply only to that Wing)
    
    Priority: Wing-specific > Pipeline-specific > Global
    
    NEW Features (Task 4):
    - Artifact-specific mapping index for efficient lookup
    - Pattern matching with compiled regex
    - Multi-field conditional matching
    - Confidence scoring
    - apply_to_record() for automatic mapping application
    """
    
    def __init__(self):
        """Initialize SemanticMappingManager."""
        self.global_mappings: Dict[str, List[SemanticMapping]] = {}
        self.wing_mappings: Dict[str, List[SemanticMapping]] = {}
        self.pipeline_mappings: Dict[str, List[SemanticMapping]] = {}
        
        # NEW: Artifact-specific mapping index (Task 4.2)
        self.artifact_mappings: Dict[str, List[SemanticMapping]] = {}
        
        # NEW: Compiled pattern cache (Task 4.3)
        self.pattern_cache: Dict[str, re.Pattern] = {}
        
        # Load default mappings
        self._load_default_mappings()
    
    def _load_default_mappings(self):
        """Load default semantic mappings for all artifact types."""
        # User Activity Events (Security Logs)
        user_activity_mappings = [
            SemanticMapping("SecurityLogs", "EventID", "4624", "User Login", 
                          "Successful user logon (Type 2: Interactive, Type 10: Remote)",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4634", "User Logoff", 
                          "User logoff event",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4647", "User Logoff", 
                          "User initiated logoff",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4800", "Session Locked", 
                          "Workstation locked",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4801", "Session Unlocked", 
                          "Workstation unlocked",
                          artifact_type="Logs", category="authentication", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4648", "Account Switch", 
                          "Logon with explicit credentials (account switch)",
                          artifact_type="Logs", category="authentication", severity="low"),
        ]
        
        # System Events (System Logs)
        system_event_mappings = [
            SemanticMapping("SystemLogs", "EventID", "6005", "System Startup", 
                          "Event Log service started",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "6006", "System Shutdown", 
                          "Event Log service stopped",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "1074", "System Restart", 
                          "System restart or shutdown initiated",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "42", "System Sleep", 
                          "System entering sleep mode",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "1", "System Wake", 
                          "System resuming from sleep",
                          artifact_type="Logs", category="system_power", severity="info"),
            SemanticMapping("SystemLogs", "EventID", "6008", "Unexpected Shutdown", 
                          "Previous system shutdown was unexpected",
                          artifact_type="Logs", category="system_power", severity="medium"),
            SemanticMapping("SystemLogs", "EventID", "107", "Hibernate Resume", 
                          "System resumed from hibernation",
                          artifact_type="Logs", category="system_power", severity="info"),
        ]
        
        # Process Execution Events (Security Logs)
        process_execution_mappings = [
            SemanticMapping("SecurityLogs", "EventID", "4688", "Process Creation", 
                          "A new process was created",
                          artifact_type="Logs", category="process_execution", severity="info"),
            SemanticMapping("SecurityLogs", "EventID", "4689", "Process Termination", 
                          "A process has exited",
                          artifact_type="Logs", category="process_execution", severity="info"),
        ]
        
        # Add all default mappings
        for mapping in user_activity_mappings + system_event_mappings + process_execution_mappings:
            self.add_mapping(mapping)
        
        logger.info(f"Loaded {len(user_activity_mappings + system_event_mappings + process_execution_mappings)} default semantic mappings")
    
    def add_mapping(self, mapping: SemanticMapping):
        """
        Add a semantic mapping with artifact indexing.
        
        Args:
            mapping: SemanticMapping to add
        """
        key = f"{mapping.source}.{mapping.field}"
        
        # Add to scope-based storage
        if mapping.scope == "global":
            if key not in self.global_mappings:
                self.global_mappings[key] = []
            self.global_mappings[key].append(mapping)
            
        elif mapping.scope == "wing" and mapping.wing_id:
            if mapping.wing_id not in self.wing_mappings:
                self.wing_mappings[mapping.wing_id] = []
            self.wing_mappings[mapping.wing_id].append(mapping)
            
        elif mapping.scope == "pipeline" and mapping.pipeline_id:
            if mapping.pipeline_id not in self.pipeline_mappings:
                self.pipeline_mappings[mapping.pipeline_id] = []
            self.pipeline_mappings[mapping.pipeline_id].append(mapping)
        
        # NEW: Add to artifact-specific index (Task 4.2)
        if mapping.artifact_type:
            if mapping.artifact_type not in self.artifact_mappings:
                self.artifact_mappings[mapping.artifact_type] = []
            self.artifact_mappings[mapping.artifact_type].append(mapping)
        
        # NEW: Compile pattern if present (Task 4.3)
        if mapping.pattern:
            mapping.compile_pattern()
    
    # NEW: Task 4.2 - Artifact-specific mapping support
    
    def add_artifact_mappings(self, artifact_type: str, mappings: List[SemanticMapping]):
        """
        Add multiple mappings for a specific artifact type.
        
        Args:
            artifact_type: Artifact type (e.g., "Prefetch", "Registry")
            mappings: List of SemanticMapping objects
        """
        for mapping in mappings:
            mapping.artifact_type = artifact_type
            self.add_mapping(mapping)
        
        logger.info(f"Added {len(mappings)} mappings for artifact type '{artifact_type}'")
    
    def get_mappings_by_artifact(self, artifact_type: str) -> List[SemanticMapping]:
        """
        Get all mappings for a specific artifact type.
        
        Args:
            artifact_type: Artifact type to retrieve
            
        Returns:
            List of SemanticMapping objects for that artifact
        """
        return self.artifact_mappings.get(artifact_type, [])
    
    # NEW: Task 4.3 - Pattern matching support
    
    def pattern_match(self, pattern: str, value: str) -> bool:
        """
        Match value against regex pattern with caching.
        
        Args:
            pattern: Regex pattern
            value: Value to match
            
        Returns:
            True if matches, False otherwise
        """
        # Check cache
        if pattern not in self.pattern_cache:
            try:
                self.pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{pattern}': {e}")
                return False
        
        compiled_pattern = self.pattern_cache[pattern]
        return bool(compiled_pattern.search(value))
    
    # NEW: Task 4.4 - Multi-field conditional matching
    
    def evaluate_conditions(self, conditions: List[Dict[str, Any]], record: Dict[str, Any]) -> bool:
        """
        Evaluate multi-field conditions against a record.
        
        Supports AND/OR logic and multiple operators.
        
        Args:
            conditions: List of condition dictionaries
            record: Record to evaluate
            
        Returns:
            True if conditions match, False otherwise
        """
        if not conditions:
            return True
        
        # Check if we have logic operator
        logic = "AND"  # Default
        if conditions and isinstance(conditions[0], dict) and "logic" in conditions[0]:
            logic = conditions[0]["logic"].upper()
            conditions = conditions[1:]  # Skip logic operator
        
        results = []
        for condition in conditions:
            if isinstance(condition, dict):
                result = self._evaluate_single_condition(condition, record)
                results.append(result)
        
        # Apply logic
        if logic == "OR":
            return any(results)
        else:  # AND
            return all(results)
    
    def _evaluate_single_condition(self, condition: Dict[str, Any], record: Dict[str, Any]) -> bool:
        """Evaluate a single condition."""
        field_name = condition.get("field")
        operator = condition.get("operator", "equals")
        expected_value = condition.get("value")
        
        if field_name not in record:
            return False
        
        actual_value = record[field_name]
        
        # Evaluate based on operator
        if operator == "equals":
            return str(actual_value).lower() == str(expected_value).lower()
        
        elif operator == "in":
            return str(actual_value) in expected_value
        
        elif operator == "regex":
            return self.pattern_match(expected_value, str(actual_value))
        
        elif operator == "greater_than":
            try:
                return float(actual_value) > float(expected_value)
            except (ValueError, TypeError):
                return False
        
        elif operator == "less_than":
            try:
                return float(actual_value) < float(expected_value)
            except (ValueError, TypeError):
                return False
        
        elif operator == "contains":
            return expected_value.lower() in str(actual_value).lower()
        
        return False
    
    # NEW: Task 4.5 - Apply mappings to record
    
    def apply_to_record(self, record: Dict[str, Any], artifact_type: Optional[str] = None,
                       wing_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Apply all matching semantic mappings to a record.
        
        Returns list of all mappings that match the record, with confidence scores.
        
        Args:
            record: Record dictionary to apply mappings to
            artifact_type: Optional artifact type for filtering
            wing_id: Optional wing ID for wing-specific mappings
            pipeline_id: Optional pipeline ID for pipeline-specific mappings
            
        Returns:
            List of matching SemanticMapping objects
        """
        matching_mappings = []
        
        # Get candidate mappings
        candidates = []
        
        # Add artifact-specific mappings if artifact_type provided
        if artifact_type:
            candidates.extend(self.get_mappings_by_artifact(artifact_type))
        
        # Add wing-specific mappings
        if wing_id and wing_id in self.wing_mappings:
            candidates.extend(self.wing_mappings[wing_id])
        
        # Add pipeline-specific mappings
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            candidates.extend(self.pipeline_mappings[pipeline_id])
        
        # Add global mappings
        for mappings_list in self.global_mappings.values():
            candidates.extend(mappings_list)
        
        # Test each candidate mapping
        for mapping in candidates:
            # Check if field exists in record
            if mapping.field not in record:
                continue
            
            field_value = str(record[mapping.field])
            
            # Check if value matches
            if not mapping.matches(field_value):
                continue
            
            # Check conditions
            if not mapping.evaluate_conditions(record):
                continue
            
            # Mapping matches!
            matching_mappings.append(mapping)
        
        # Sort by confidence (highest first)
        matching_mappings.sort(key=lambda m: m.confidence, reverse=True)
        
        return matching_mappings
    
    def get_semantic_value(self, source: str, field: str, 
                          technical_value: str,
                          wing_id: Optional[str] = None,
                          pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Get semantic value for a technical value.
        
        Priority: Wing-specific > Pipeline-specific > Global
        
        Args:
            source: Source of the value (e.g., "SecurityLogs")
            field: Field name (e.g., "EventID")
            technical_value: Technical value to map (e.g., "4624")
            wing_id: Optional Wing ID for Wing-specific mappings
            pipeline_id: Optional Pipeline ID for Pipeline-specific mappings
            
        Returns:
            Semantic value if found, None otherwise
        """
        # Check wing-specific mappings first
        if wing_id and wing_id in self.wing_mappings:
            for mapping in self.wing_mappings[wing_id]:
                if (mapping.source == source and 
                    mapping.field == field and
                    mapping.technical_value == technical_value):
                    return mapping.semantic_value
        
        # Check pipeline-specific mappings
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            for mapping in self.pipeline_mappings[pipeline_id]:
                if (mapping.source == source and 
                    mapping.field == field and
                    mapping.technical_value == technical_value):
                    return mapping.semantic_value
        
        # Check global mappings
        key = f"{source}.{field}"
        if key in self.global_mappings:
            for mapping in self.global_mappings[key]:
                if mapping.technical_value == technical_value:
                    return mapping.semantic_value
        
        return None
    
    def remove_mapping(self, source: str, field: str, technical_value: str,
                      scope: str = "global", 
                      wing_id: Optional[str] = None,
                      pipeline_id: Optional[str] = None):
        """
        Remove a semantic mapping.
        
        Args:
            source: Source of the value
            field: Field name
            technical_value: Technical value
            scope: Scope of mapping ("global", "wing", "pipeline")
            wing_id: Wing ID if scope is "wing"
            pipeline_id: Pipeline ID if scope is "pipeline"
        """
        if scope == "global":
            key = f"{source}.{field}"
            if key in self.global_mappings:
                self.global_mappings[key] = [
                    m for m in self.global_mappings[key]
                    if m.technical_value != technical_value
                ]
                
        elif scope == "wing" and wing_id and wing_id in self.wing_mappings:
            self.wing_mappings[wing_id] = [
                m for m in self.wing_mappings[wing_id]
                if not (m.source == source and m.field == field and 
                       m.technical_value == technical_value)
            ]
            
        elif scope == "pipeline" and pipeline_id and pipeline_id in self.pipeline_mappings:
            self.pipeline_mappings[pipeline_id] = [
                m for m in self.pipeline_mappings[pipeline_id]
                if not (m.source == source and m.field == field and 
                       m.technical_value == technical_value)
            ]
    
    def get_all_mappings(self, scope: str = "global",
                        wing_id: Optional[str] = None,
                        pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Get all mappings for a given scope.
        
        Args:
            scope: Scope to retrieve ("global", "wing", "pipeline")
            wing_id: Wing ID if scope is "wing"
            pipeline_id: Pipeline ID if scope is "pipeline"
            
        Returns:
            List of SemanticMapping objects
        """
        if scope == "global":
            return [m for mappings in self.global_mappings.values() for m in mappings]
        elif scope == "wing" and wing_id:
            return self.wing_mappings.get(wing_id, [])
        elif scope == "pipeline" and pipeline_id:
            return self.pipeline_mappings.get(pipeline_id, [])
        return []
    
    def save_to_file(self, file_path: Path, scope: str = "global",
                    wing_id: Optional[str] = None,
                    pipeline_id: Optional[str] = None):
        """
        Save mappings to JSON file.
        
        Args:
            file_path: Path to save file
            scope: Scope to save
            wing_id: Wing ID if scope is "wing"
            pipeline_id: Pipeline ID if scope is "pipeline"
        """
        mappings = self.get_all_mappings(scope, wing_id, pipeline_id)
        data = [asdict(m) for m in mappings]
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved {len(mappings)} semantic mappings to {file_path}")
    
    def load_from_file(self, file_path: Path):
        """
        Load mappings from JSON file.
        
        Args:
            file_path: Path to load file
        """
        if not file_path.exists():
            logger.warning(f"Semantic mappings file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        for mapping_dict in data:
            mapping = SemanticMapping(**mapping_dict)
            self.add_mapping(mapping)
        
        logger.info(f"Loaded {len(data)} semantic mappings from {file_path}")
    
    def normalize_field_value(self, field_type: str, value: str, wing_id: Optional[str] = None) -> str:
        """
        Normalize a field value using semantic mappings.
        
        Args:
            field_type: Type of field ('application' or 'path')
            value: Value to normalize
            wing_id: Optional wing ID for wing-specific mappings
            
        Returns:
            Normalized value
        """
        if not value:
            return value
        
        # Convert to lowercase for comparison
        value_lower = value.lower()
        
        # Application normalization
        if field_type == 'application':
            # Common application name mappings
            app_mappings = {
                'chrome.exe': 'Google Chrome',
                'firefox.exe': 'Mozilla Firefox',
                'msedge.exe': 'Microsoft Edge',
                'iexplore.exe': 'Internet Explorer',
                'explorer.exe': 'Windows Explorer',
                'notepad.exe': 'Notepad',
                'cmd.exe': 'Command Prompt',
                'powershell.exe': 'PowerShell',
                'python.exe': 'Python',
                'java.exe': 'Java',
                'code.exe': 'Visual Studio Code',
                'excel.exe': 'Microsoft Excel',
                'word.exe': 'Microsoft Word',
                'outlook.exe': 'Microsoft Outlook'
            }
            
            # Check if we have a mapping
            for exe_name, normalized_name in app_mappings.items():
                if exe_name in value_lower:
                    return normalized_name
            
            # Return original if no mapping found
            return value
        
        # Path normalization
        elif field_type == 'path':
            # Normalize common path prefixes
            path_mappings = {
                'c:\\program files\\': '%ProgramFiles%\\',
                'c:\\program files (x86)\\': '%ProgramFiles(x86)%\\',
                'c:\\windows\\': '%Windows%\\',
                'c:\\users\\': '%UserProfile%\\',
                'c:\\programdata\\': '%ProgramData%\\'
            }
            
            normalized = value
            for original, replacement in path_mappings.items():
                if value_lower.startswith(original):
                    normalized = replacement + value[len(original):]
                    break
            
            return normalized
        
        return value
    
    def calculate_semantic_similarity(self, values: List[str]) -> float:
        """
        Calculate semantic similarity score for a list of values.
        
        Args:
            values: List of values to compare
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        if not values or len(values) < 2:
            return 1.0
        
        # Count how many values are the same
        unique_values = set(values)
        
        if len(unique_values) == 1:
            # All values are identical
            return 1.0
        
        # Calculate similarity as ratio of most common value
        from collections import Counter
        counter = Counter(values)
        most_common_count = counter.most_common(1)[0][1]
        
        similarity = most_common_count / len(values)
        return similarity

    
    def get_semantic_value(self, source: str, field: str, 
                          technical_value: str,
                          wing_id: Optional[str] = None,
                          pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Get semantic value for a technical value.
        
        Priority: Wing-specific > Pipeline-specific > Global
        
        Args:
            source: Source of the value (e.g., "SecurityLogs")
            field: Field name (e.g., "EventID")
            technical_value: Technical value to map (e.g., "4624")
            wing_id: Optional Wing ID for Wing-specific mappings
            pipeline_id: Optional Pipeline ID for Pipeline-specific mappings
            
        Returns:
            Semantic value if found, None otherwise
        """
        # Check wing-specific mappings first
        if wing_id and wing_id in self.wing_mappings:
            for mapping in self.wing_mappings[wing_id]:
                if (mapping.source == source and 
                    mapping.field == field and
                    mapping.matches(technical_value)):
                    return mapping.semantic_value
        
        # Check pipeline-specific mappings
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            for mapping in self.pipeline_mappings[pipeline_id]:
                if (mapping.source == source and 
                    mapping.field == field and
                    mapping.matches(technical_value)):
                    return mapping.semantic_value
        
        # Check global mappings
        key = f"{source}.{field}"
        if key in self.global_mappings:
            for mapping in self.global_mappings[key]:
                if mapping.matches(technical_value):
                    return mapping.semantic_value
        
        return None
    
    def remove_mapping(self, source: str, field: str, technical_value: str,
                      scope: str = "global", 
                      wing_id: Optional[str] = None,
                      pipeline_id: Optional[str] = None):
        """
        Remove a semantic mapping.
        
        Args:
            source: Source of the value
            field: Field name
            technical_value: Technical value
            scope: Scope of mapping ("global", "wing", "pipeline")
            wing_id: Wing ID if scope is "wing"
            pipeline_id: Pipeline ID if scope is "pipeline"
        """
        if scope == "global":
            key = f"{source}.{field}"
            if key in self.global_mappings:
                self.global_mappings[key] = [
                    m for m in self.global_mappings[key]
                    if not m.matches(technical_value)
                ]
                
        elif scope == "wing" and wing_id and wing_id in self.wing_mappings:
            self.wing_mappings[wing_id] = [
                m for m in self.wing_mappings[wing_id]
                if not (m.source == source and m.field == field and 
                       m.matches(technical_value))
            ]
            
        elif scope == "pipeline" and pipeline_id and pipeline_id in self.pipeline_mappings:
            self.pipeline_mappings[pipeline_id] = [
                m for m in self.pipeline_mappings[pipeline_id]
                if not (m.source == source and m.field == field and 
                       m.matches(technical_value))
            ]
    
    def get_all_mappings(self, scope: str = "global",
                        wing_id: Optional[str] = None,
                        pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Get all mappings for a given scope.
        
        Args:
            scope: Scope to retrieve ("global", "wing", "pipeline")
            wing_id: Wing ID if scope is "wing"
            pipeline_id: Pipeline ID if scope is "pipeline"
            
        Returns:
            List of SemanticMapping objects
        """
        if scope == "global":
            return [m for mappings in self.global_mappings.values() for m in mappings]
        elif scope == "wing" and wing_id:
            return self.wing_mappings.get(wing_id, [])
        elif scope == "pipeline" and pipeline_id:
            return self.pipeline_mappings.get(pipeline_id, [])
        return []
    
    def save_to_file(self, file_path: Path, scope: str = "global",
                    wing_id: Optional[str] = None,
                    pipeline_id: Optional[str] = None):
        """
        Save mappings to JSON file.
        
        Args:
            file_path: Path to save file
            scope: Scope to save
            wing_id: Wing ID if scope is "wing"
            pipeline_id: Pipeline ID if scope is "pipeline"
        """
        mappings = self.get_all_mappings(scope, wing_id, pipeline_id)
        
        # Convert to dict, excluding non-serializable fields
        data = []
        for m in mappings:
            m_dict = asdict(m)
            # Remove compiled pattern
            m_dict.pop('_compiled_pattern', None)
            data.append(m_dict)
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved {len(mappings)} semantic mappings to {file_path}")
    
    def load_from_file(self, file_path: Path):
        """
        Load mappings from JSON file.
        
        Args:
            file_path: Path to load file
        """
        if not file_path.exists():
            logger.warning(f"Semantic mappings file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        for mapping_dict in data:
            # Remove any non-field keys
            mapping_dict.pop('_compiled_pattern', None)
            mapping = SemanticMapping(**mapping_dict)
            self.add_mapping(mapping)
        
        logger.info(f"Loaded {len(data)} semantic mappings from {file_path}")
    
    def normalize_field_value(self, field_type: str, value: str, wing_id: Optional[str] = None) -> str:
        """
        Normalize a field value using semantic mappings.
        
        Args:
            field_type: Type of field ('application' or 'path')
            value: Value to normalize
            wing_id: Optional wing ID for wing-specific mappings
            
        Returns:
            Normalized value
        """
        if not value:
            return value
        
        # Convert to lowercase for comparison
        value_lower = value.lower()
        
        # Application normalization
        if field_type == 'application':
            # Common application name mappings
            app_mappings = {
                'chrome.exe': 'Google Chrome',
                'firefox.exe': 'Mozilla Firefox',
                'msedge.exe': 'Microsoft Edge',
                'iexplore.exe': 'Internet Explorer',
                'explorer.exe': 'Windows Explorer',
                'notepad.exe': 'Notepad',
                'cmd.exe': 'Command Prompt',
                'powershell.exe': 'PowerShell',
                'python.exe': 'Python',
                'java.exe': 'Java',
                'code.exe': 'Visual Studio Code',
                'excel.exe': 'Microsoft Excel',
                'word.exe': 'Microsoft Word',
                'outlook.exe': 'Microsoft Outlook'
            }
            
            # Check if we have a mapping
            for exe_name, normalized_name in app_mappings.items():
                if exe_name in value_lower:
                    return normalized_name
            
            # Return original if no mapping found
            return value
        
        # Path normalization
        elif field_type == 'path':
            # Normalize common path prefixes
            path_mappings = {
                'c:\\program files\\': '%ProgramFiles%\\',
                'c:\\program files (x86)\\': '%ProgramFiles(x86)%\\',
                'c:\\windows\\': '%Windows%\\',
                'c:\\users\\': '%UserProfile%\\',
                'c:\\programdata\\': '%ProgramData%\\'
            }
            
            normalized = value
            for original, replacement in path_mappings.items():
                if value_lower.startswith(original):
                    normalized = replacement + value[len(original):]
                    break
            
            return normalized
        
        return value
    
    def calculate_semantic_similarity(self, values: List[str]) -> float:
        """
        Calculate semantic similarity score for a list of values.
        
        Args:
            values: List of values to compare
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        if not values or len(values) < 2:
            return 1.0
        
        # Count how many values are the same
        unique_values = set(values)
        
        if len(unique_values) == 1:
            # All values are identical
            return 1.0
        
        # Calculate similarity as ratio of most common value
        from collections import Counter
        counter = Counter(values)
        most_common_count = counter.most_common(1)[0][1]
        
        similarity = most_common_count / len(values)
        return similarity
