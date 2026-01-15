"""
Semantic Mapping System

Unified module for semantic value mappings in correlation results.
Maps technical values (e.g., Event IDs, status codes, file patterns) to human-readable semantic meanings.

This module provides:
- SemanticMapping: Basic semantic value mapping with pattern matching
- SemanticCondition: Single condition for advanced multi-value rules
- SemanticRule: Advanced semantic rule with AND/OR logic and wildcard support
- SemanticMappingManager: Manager for all semantic mappings

Features:
- Artifact-specific mappings for ALL forensic artifacts
- Pattern matching with regex support
- Multi-field conditional matching
- AND/OR logic for complex rules
- Wildcard (*) support for "any value" matching
- Confidence scoring
- Mapping source tracking (global/wing/pipeline/built-in)
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# BASIC SEMANTIC MAPPING
# =============================================================================

@dataclass
class SemanticMapping:
    """
    Basic semantic value mapping with universal artifact support.
    
    Maps technical values to human-readable semantic meanings with support for:
    - Pattern matching (regex)
    - Multi-field conditions
    - Confidence scoring
    - Artifact-specific rules
    
    Attributes:
        source: Source of the value (e.g., "SecurityLogs", "Prefetch")
        field: Field name (e.g., "EventID", "executable_name")
        technical_value: Technical value to match (e.g., "4624", "chrome.exe")
        semantic_value: Human-readable meaning (e.g., "User Login", "Web Browser")
        description: Optional detailed description
        artifact_type: Artifact type for filtering
        category: Semantic category
        severity: Severity level
        pattern: Regex pattern for matching (empty = exact match)
        conditions: Multi-field conditions
        confidence: Confidence score (0.0 to 1.0)
        mapping_source: Source of mapping (built-in, global, wing)
        scope: Scope of mapping (global, wing, pipeline)
        wing_id: Wing ID if scope is "wing"
        pipeline_id: Pipeline ID if scope is "pipeline"
    """
    source: str
    field: str
    technical_value: str
    semantic_value: str
    description: str = ""
    
    # Enhanced fields
    artifact_type: str = ""
    category: str = ""
    severity: str = "info"
    pattern: str = ""
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    mapping_source: str = "built-in"
    
    # Scope fields
    scope: str = "global"
    wing_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    
    # Compiled pattern cache (not serialized)
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
            if not self._compiled_pattern:
                self.compile_pattern()
            if self._compiled_pattern:
                return bool(self._compiled_pattern.search(value))
            return False
        else:
            return value.lower() == self.technical_value.lower()
    
    def evaluate_conditions(self, record: Dict[str, Any]) -> bool:
        """
        Evaluate multi-field conditions against a record.
        
        Args:
            record: Record dictionary to evaluate
            
        Returns:
            True if all conditions match, False otherwise
        """
        if not self.conditions:
            return True
        
        for condition in self.conditions:
            field_name = condition.get("field")
            operator = condition.get("operator", "equals")
            expected_value = condition.get("value")
            
            if field_name not in record:
                return False
            
            actual_value = record[field_name]
            
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
        
        return True


# =============================================================================
# ADVANCED SEMANTIC RULES (Multi-Value with AND/OR Logic)
# =============================================================================

@dataclass
class SemanticCondition:
    """
    Single condition in a multi-value semantic rule.
    
    Supports multiple operators for flexible matching:
    - equals: Exact match (case-insensitive)
    - contains: Substring match (case-insensitive)
    - regex: Regular expression match
    - wildcard: Match any non-empty value (when value is "*")
    
    Attributes:
        feather_id: ID of the feather this condition applies to
        field_name: Name of the field to match
        value: Value to match, or "*" for wildcard
        operator: Match operator (equals, contains, regex, wildcard)
    """
    feather_id: str
    field_name: str
    value: str
    operator: str = "equals"
    
    # Compiled pattern cache (not serialized)
    _compiled_pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False, compare=False)
    
    def __post_init__(self):
        """Post-initialization processing."""
        if self.value == "*" and self.operator == "equals":
            self.operator = "wildcard"
        if self.operator == "regex":
            self._compile_pattern()
    
    def _compile_pattern(self):
        """Compile regex pattern for efficient matching."""
        if self.operator == "regex" and self.value and not self._compiled_pattern:
            try:
                self._compiled_pattern = re.compile(self.value, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{self.value}': {e}")
                self._compiled_pattern = None
    
    def matches(self, record: Dict[str, Any]) -> bool:
        """
        Check if this condition matches the record.
        
        Args:
            record: Dictionary containing field values to match against
            
        Returns:
            True if the condition matches, False otherwise
        """
        if self.field_name not in record:
            return False
        
        field_value = record[self.field_name]
        if field_value is None:
            return False
        
        field_value_str = str(field_value)
        
        # Wildcard matching
        if self.value == "*" or self.operator == "wildcard":
            return bool(field_value_str.strip())
        
        # Equals matching (case-insensitive)
        if self.operator == "equals":
            return field_value_str.lower() == self.value.lower()
        
        # Contains matching (case-insensitive)
        if self.operator == "contains":
            return self.value.lower() in field_value_str.lower()
        
        # Regex matching
        if self.operator == "regex":
            if not self._compiled_pattern:
                self._compile_pattern()
            if self._compiled_pattern:
                return bool(self._compiled_pattern.search(field_value_str))
            return False
        
        # Default to equals
        return field_value_str.lower() == self.value.lower()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'feather_id': self.feather_id,
            'field_name': self.field_name,
            'value': self.value,
            'operator': self.operator
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SemanticCondition':
        """Create SemanticCondition from dictionary."""
        required_fields = ['feather_id', 'field_name', 'value']
        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        return cls(
            feather_id=data['feather_id'],
            field_name=data['field_name'],
            value=data['value'],
            operator=data.get('operator', 'equals')
        )
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        if self.operator == "wildcard" or self.value == "*":
            return f"{self.feather_id}.{self.field_name} has any value"
        return f"{self.feather_id}.{self.field_name} {self.operator} '{self.value}'"



@dataclass
class SemanticRule:
    """
    Advanced semantic rule with multi-value support.
    
    Supports:
    - Multiple conditions with AND/OR logic
    - Wildcard matching for "any value" patterns
    - Scope-based rules (global, wing, pipeline)
    - Confidence scoring and severity levels
    
    Attributes:
        rule_id: Unique identifier for the rule
        name: Human-readable name
        semantic_value: Result value when rule matches
        description: Detailed description of the rule
        conditions: List of conditions to evaluate
        logic_operator: "AND" or "OR" for combining conditions
        scope: Rule scope (global, wing, pipeline)
        wing_id: Wing ID if scope is "wing"
        pipeline_id: Pipeline ID if scope is "pipeline"
        category: Semantic category
        severity: Severity level (info, low, medium, high, critical)
        confidence: Confidence score (0.0 to 1.0)
    """
    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    semantic_value: str = ""
    description: str = ""
    
    # Multi-value conditions
    conditions: List[SemanticCondition] = field(default_factory=list)
    logic_operator: str = "AND"
    
    # Scope
    scope: str = "global"
    wing_id: Optional[str] = None
    pipeline_id: Optional[str] = None
    
    # Metadata
    category: str = ""
    severity: str = "info"
    confidence: float = 1.0
    
    def __post_init__(self):
        """Post-initialization validation."""
        self.logic_operator = self.logic_operator.upper()
        if self.logic_operator not in ("AND", "OR"):
            logger.warning(f"Invalid logic operator '{self.logic_operator}', defaulting to AND")
            self.logic_operator = "AND"
        
        if not 0.0 <= self.confidence <= 1.0:
            logger.warning(f"Confidence {self.confidence} out of range, clamping to [0.0, 1.0]")
            self.confidence = max(0.0, min(1.0, self.confidence))
    
    def evaluate(self, records: Dict[str, Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Evaluate rule against records from multiple feathers.
        
        Args:
            records: Dict mapping feather_id to record data
            
        Returns:
            Tuple of (matches: bool, matched_conditions: List[str])
        """
        if not self.conditions:
            return True, []
        
        matched_conditions = []
        
        for condition in self.conditions:
            record = records.get(condition.feather_id, {})
            if condition.matches(record):
                matched_conditions.append(f"{condition.feather_id}.{condition.field_name}")
        
        if self.logic_operator == "AND":
            matches = len(matched_conditions) == len(self.conditions)
        else:
            matches = len(matched_conditions) > 0
        
        return matches, matched_conditions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'rule_id': self.rule_id,
            'name': self.name,
            'semantic_value': self.semantic_value,
            'description': self.description,
            'conditions': [c.to_dict() for c in self.conditions],
            'logic_operator': self.logic_operator,
            'scope': self.scope,
            'wing_id': self.wing_id,
            'pipeline_id': self.pipeline_id,
            'category': self.category,
            'severity': self.severity,
            'confidence': self.confidence
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SemanticRule':
        """Create SemanticRule from dictionary."""
        required_fields = ['rule_id', 'semantic_value', 'conditions']
        missing_fields = [f for f in required_fields if f not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")
        
        conditions = []
        for cond_data in data.get('conditions', []):
            try:
                conditions.append(SemanticCondition.from_dict(cond_data))
            except ValueError as e:
                raise ValueError(f"Invalid condition in rule: {e}")
        
        return cls(
            rule_id=data['rule_id'],
            name=data.get('name', ''),
            semantic_value=data['semantic_value'],
            description=data.get('description', ''),
            conditions=conditions,
            logic_operator=data.get('logic_operator', 'AND'),
            scope=data.get('scope', 'global'),
            wing_id=data.get('wing_id'),
            pipeline_id=data.get('pipeline_id'),
            category=data.get('category', ''),
            severity=data.get('severity', 'info'),
            confidence=data.get('confidence', 1.0)
        )
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'SemanticRule':
        """Create SemanticRule from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def get_human_readable(self) -> str:
        """Get human-readable description of the rule."""
        if not self.conditions:
            return f"'{self.name}' → {self.semantic_value} (always matches)"
        
        condition_strs = [str(c) for c in self.conditions]
        logic_word = " AND " if self.logic_operator == "AND" else " OR "
        conditions_text = logic_word.join(condition_strs)
        
        return f"'{self.name}': IF {conditions_text} THEN → {self.semantic_value}"
    
    def __str__(self) -> str:
        return self.get_human_readable()


# =============================================================================
# SEMANTIC MAPPING MANAGER
# =============================================================================

class SemanticMappingManager:
    """
    Unified semantic mapping manager.
    
    Provides hierarchical mapping system with:
    1. Global mappings (apply to all Wings)
    2. Pipeline-specific mappings (apply to all Wings in a Pipeline)
    3. Wing-specific mappings (apply only to that Wing)
    
    Priority: Wing-specific > Pipeline-specific > Global
    
    Features:
    - Artifact-specific mapping index for efficient lookup
    - Pattern matching with compiled regex
    - Multi-field conditional matching
    - Advanced rules with AND/OR logic
    - Confidence scoring
    """
    
    def __init__(self):
        """Initialize SemanticMappingManager."""
        # Basic mappings storage
        self.global_mappings: Dict[str, List[SemanticMapping]] = {}
        self.wing_mappings: Dict[str, List[SemanticMapping]] = {}
        self.pipeline_mappings: Dict[str, List[SemanticMapping]] = {}
        
        # Artifact-specific mapping index
        self.artifact_mappings: Dict[str, List[SemanticMapping]] = {}
        
        # Advanced rules storage
        self.global_rules: List[SemanticRule] = []
        self.wing_rules: Dict[str, List[SemanticRule]] = {}
        self.pipeline_rules: Dict[str, List[SemanticRule]] = {}
        
        # Compiled pattern cache
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
    
    # =========================================================================
    # BASIC MAPPING METHODS
    # =========================================================================
    
    def add_mapping(self, mapping: SemanticMapping):
        """Add a semantic mapping with artifact indexing."""
        key = f"{mapping.source}.{mapping.field}"
        
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
        
        if mapping.artifact_type:
            if mapping.artifact_type not in self.artifact_mappings:
                self.artifact_mappings[mapping.artifact_type] = []
            self.artifact_mappings[mapping.artifact_type].append(mapping)
        
        if mapping.pattern:
            mapping.compile_pattern()
    
    def add_artifact_mappings(self, artifact_type: str, mappings: List[SemanticMapping]):
        """Add multiple mappings for a specific artifact type."""
        for mapping in mappings:
            mapping.artifact_type = artifact_type
            self.add_mapping(mapping)
        logger.info(f"Added {len(mappings)} mappings for artifact type '{artifact_type}'")
    
    def get_mappings_by_artifact(self, artifact_type: str) -> List[SemanticMapping]:
        """Get all mappings for a specific artifact type."""
        return self.artifact_mappings.get(artifact_type, [])
    
    def get_all_mappings(self, scope: str = "global",
                        wing_id: Optional[str] = None,
                        pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """Get all mappings for a given scope."""
        if scope == "global":
            return [m for mappings in self.global_mappings.values() for m in mappings]
        elif scope == "wing" and wing_id:
            return self.wing_mappings.get(wing_id, [])
        elif scope == "pipeline" and pipeline_id:
            return self.pipeline_mappings.get(pipeline_id, [])
        return []
    
    def remove_mapping(self, source: str, field: str, technical_value: str,
                      scope: str = "global", 
                      wing_id: Optional[str] = None,
                      pipeline_id: Optional[str] = None):
        """Remove a semantic mapping."""
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
                if not (m.source == source and m.field == field and m.matches(technical_value))
            ]
        elif scope == "pipeline" and pipeline_id and pipeline_id in self.pipeline_mappings:
            self.pipeline_mappings[pipeline_id] = [
                m for m in self.pipeline_mappings[pipeline_id]
                if not (m.source == source and m.field == field and m.matches(technical_value))
            ]

    # =========================================================================
    # ADVANCED RULE METHODS
    # =========================================================================
    
    def add_rule(self, rule: SemanticRule):
        """Add an advanced semantic rule."""
        if rule.scope == "global":
            self.global_rules.append(rule)
        elif rule.scope == "wing" and rule.wing_id:
            if rule.wing_id not in self.wing_rules:
                self.wing_rules[rule.wing_id] = []
            self.wing_rules[rule.wing_id].append(rule)
        elif rule.scope == "pipeline" and rule.pipeline_id:
            if rule.pipeline_id not in self.pipeline_rules:
                self.pipeline_rules[rule.pipeline_id] = []
            self.pipeline_rules[rule.pipeline_id].append(rule)
    
    def get_rules(self, scope: str = "global",
                 wing_id: Optional[str] = None,
                 pipeline_id: Optional[str] = None) -> List[SemanticRule]:
        """Get all rules for a given scope."""
        if scope == "global":
            return self.global_rules.copy()
        elif scope == "wing" and wing_id:
            return self.wing_rules.get(wing_id, []).copy()
        elif scope == "pipeline" and pipeline_id:
            return self.pipeline_rules.get(pipeline_id, []).copy()
        return []
    
    def get_all_rules_for_execution(self, wing_id: Optional[str] = None,
                                   pipeline_id: Optional[str] = None) -> List[SemanticRule]:
        """
        Get all applicable rules for execution with proper priority.
        
        Priority: Wing-specific > Pipeline-specific > Global
        """
        rules = []
        
        # Add wing-specific rules first (highest priority)
        if wing_id and wing_id in self.wing_rules:
            rules.extend(self.wing_rules[wing_id])
        
        # Add pipeline-specific rules
        if pipeline_id and pipeline_id in self.pipeline_rules:
            rules.extend(self.pipeline_rules[pipeline_id])
        
        # Add global rules (lowest priority)
        rules.extend(self.global_rules)
        
        return rules
    
    def remove_rule(self, rule_id: str, scope: str = "global",
                   wing_id: Optional[str] = None,
                   pipeline_id: Optional[str] = None):
        """Remove a semantic rule by ID."""
        if scope == "global":
            self.global_rules = [r for r in self.global_rules if r.rule_id != rule_id]
        elif scope == "wing" and wing_id and wing_id in self.wing_rules:
            self.wing_rules[wing_id] = [r for r in self.wing_rules[wing_id] if r.rule_id != rule_id]
        elif scope == "pipeline" and pipeline_id and pipeline_id in self.pipeline_rules:
            self.pipeline_rules[pipeline_id] = [r for r in self.pipeline_rules[pipeline_id] if r.rule_id != rule_id]
    
    # =========================================================================
    # PATTERN MATCHING
    # =========================================================================
    
    def pattern_match(self, pattern: str, value: str) -> bool:
        """Match value against regex pattern with caching."""
        if pattern not in self.pattern_cache:
            try:
                self.pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                logger.error(f"Invalid regex pattern '{pattern}': {e}")
                return False
        return bool(self.pattern_cache[pattern].search(value))
    
    def evaluate_conditions(self, conditions: List[Dict[str, Any]], record: Dict[str, Any]) -> bool:
        """Evaluate multi-field conditions against a record."""
        if not conditions:
            return True
        
        logic = "AND"
        if conditions and isinstance(conditions[0], dict) and "logic" in conditions[0]:
            logic = conditions[0]["logic"].upper()
            conditions = conditions[1:]
        
        results = []
        for condition in conditions:
            if isinstance(condition, dict):
                result = self._evaluate_single_condition(condition, record)
                results.append(result)
        
        return any(results) if logic == "OR" else all(results)
    
    def _evaluate_single_condition(self, condition: Dict[str, Any], record: Dict[str, Any]) -> bool:
        """Evaluate a single condition."""
        field_name = condition.get("field")
        operator = condition.get("operator", "equals")
        expected_value = condition.get("value")
        
        if field_name not in record:
            return False
        
        actual_value = record[field_name]
        
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
    
    # =========================================================================
    # APPLY MAPPINGS TO RECORDS
    # =========================================================================
    
    def apply_to_record(self, record: Dict[str, Any], artifact_type: Optional[str] = None,
                       wing_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Apply all matching semantic mappings to a record.
        
        Returns list of all mappings that match the record, sorted by confidence.
        """
        matching_mappings = []
        candidates = []
        
        if artifact_type:
            candidates.extend(self.get_mappings_by_artifact(artifact_type))
        if wing_id and wing_id in self.wing_mappings:
            candidates.extend(self.wing_mappings[wing_id])
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            candidates.extend(self.pipeline_mappings[pipeline_id])
        for mappings_list in self.global_mappings.values():
            candidates.extend(mappings_list)
        
        for mapping in candidates:
            if mapping.field not in record:
                continue
            field_value = str(record[mapping.field])
            if not mapping.matches(field_value):
                continue
            if not mapping.evaluate_conditions(record):
                continue
            matching_mappings.append(mapping)
        
        matching_mappings.sort(key=lambda m: m.confidence, reverse=True)
        return matching_mappings
    
    def get_semantic_value(self, source: str, field: str, 
                          technical_value: str,
                          wing_id: Optional[str] = None,
                          pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Get semantic value for a technical value.
        
        Priority: Wing-specific > Pipeline-specific > Global
        """
        # Check wing-specific mappings first
        if wing_id and wing_id in self.wing_mappings:
            for mapping in self.wing_mappings[wing_id]:
                if (mapping.source == source and mapping.field == field and
                    mapping.matches(technical_value)):
                    return mapping.semantic_value
        
        # Check pipeline-specific mappings
        if pipeline_id and pipeline_id in self.pipeline_mappings:
            for mapping in self.pipeline_mappings[pipeline_id]:
                if (mapping.source == source and mapping.field == field and
                    mapping.matches(technical_value)):
                    return mapping.semantic_value
        
        # Check global mappings
        key = f"{source}.{field}"
        if key in self.global_mappings:
            for mapping in self.global_mappings[key]:
                if mapping.matches(technical_value):
                    return mapping.semantic_value
        
        return None
    
    # =========================================================================
    # NORMALIZATION UTILITIES
    # =========================================================================
    
    def normalize_field_value(self, field_type: str, value: str, wing_id: Optional[str] = None) -> str:
        """Normalize a field value using semantic mappings."""
        if not value:
            return value
        
        value_lower = value.lower()
        
        if field_type == 'application':
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
            for exe_name, normalized_name in app_mappings.items():
                if exe_name in value_lower:
                    return normalized_name
            return value
        
        elif field_type == 'path':
            path_mappings = {
                'c:\\program files\\': '%ProgramFiles%\\',
                'c:\\program files (x86)\\': '%ProgramFiles(x86)%\\',
                'c:\\windows\\': '%Windows%\\',
                'c:\\users\\': '%UserProfile%\\',
                'c:\\programdata\\': '%ProgramData%\\'
            }
            for original, replacement in path_mappings.items():
                if value_lower.startswith(original):
                    return replacement + value[len(original):]
            return value
        
        return value
    
    def calculate_semantic_similarity(self, values: List[str]) -> float:
        """Calculate semantic similarity score for a list of values."""
        if not values or len(values) < 2:
            return 1.0
        
        unique_values = set(values)
        if len(unique_values) == 1:
            return 1.0
        
        from collections import Counter
        counter = Counter(values)
        most_common_count = counter.most_common(1)[0][1]
        return most_common_count / len(values)
    
    # =========================================================================
    # FILE I/O
    # =========================================================================
    
    def save_to_file(self, file_path: Path, scope: str = "global",
                    wing_id: Optional[str] = None,
                    pipeline_id: Optional[str] = None):
        """Save mappings and rules to JSON file."""
        mappings = self.get_all_mappings(scope, wing_id, pipeline_id)
        rules = self.get_rules(scope, wing_id, pipeline_id)
        
        data = {
            'mappings': [],
            'rules': []
        }
        
        for m in mappings:
            m_dict = asdict(m)
            m_dict.pop('_compiled_pattern', None)
            data['mappings'].append(m_dict)
        
        for r in rules:
            data['rules'].append(r.to_dict())
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved {len(mappings)} mappings and {len(rules)} rules to {file_path}")
    
    def load_from_file(self, file_path: Path):
        """Load mappings and rules from JSON file."""
        if not file_path.exists():
            logger.warning(f"Semantic mappings file not found: {file_path}")
            return
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Handle both old format (list) and new format (dict with mappings/rules)
        if isinstance(data, list):
            # Old format - just mappings
            for mapping_dict in data:
                mapping_dict.pop('_compiled_pattern', None)
                mapping = SemanticMapping(**mapping_dict)
                self.add_mapping(mapping)
            logger.info(f"Loaded {len(data)} semantic mappings from {file_path}")
        else:
            # New format
            mappings_data = data.get('mappings', [])
            rules_data = data.get('rules', [])
            
            for mapping_dict in mappings_data:
                mapping_dict.pop('_compiled_pattern', None)
                mapping = SemanticMapping(**mapping_dict)
                self.add_mapping(mapping)
            
            for rule_dict in rules_data:
                rule = SemanticRule.from_dict(rule_dict)
                self.add_rule(rule)
            
            logger.info(f"Loaded {len(mappings_data)} mappings and {len(rules_data)} rules from {file_path}")
