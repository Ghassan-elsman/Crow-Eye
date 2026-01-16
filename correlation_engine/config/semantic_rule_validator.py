"""
Semantic Rule Validator

Validates semantic rule JSON files against schema to ensure data integrity
before loading into the system.

Features:
- JSON syntax validation
- Schema structure validation
- Field type and value validation
- Detailed error reporting with actionable guidance
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """Represents a validation error with context and guidance."""
    rule_id: Optional[str]  # Rule ID if available
    rule_index: int  # Index in rules array
    field: str  # Field with error
    message: str  # Error description
    severity: str  # "error" or "warning"
    suggestion: str  # How to fix
    
    def __str__(self) -> str:
        """Format error as human-readable string."""
        prefix = "ERROR" if self.severity == "error" else "WARNING"
        rule_ref = f"Rule '{self.rule_id}'" if self.rule_id else f"Rule #{self.rule_index}"
        return f"[{prefix}] {rule_ref} - {self.field}: {self.message}\n  Suggestion: {self.suggestion}"


@dataclass
class ValidationResult:
    """Result of validation operation."""
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    rules_count: int = 0
    
    def get_report(self) -> str:
        """Get formatted error report."""
        if self.is_valid and not self.warnings:
            return f"✓ Validation successful! {self.rules_count} rules validated."
        
        lines = []
        
        if self.errors:
            lines.append(f"✗ Validation failed with {len(self.errors)} error(s):\n")
            for error in self.errors:
                lines.append(str(error))
                lines.append("")
        
        if self.warnings:
            lines.append(f"⚠ {len(self.warnings)} warning(s):\n")
            for warning in self.warnings:
                lines.append(str(warning))
                lines.append("")
        
        if not self.errors:
            lines.append(f"✓ {self.rules_count} rules validated successfully.")
        
        lines.append("\nFor more information, see: Crow-Eye/configs/README.md")
        
        return "\n".join(lines)


class SemanticRuleValidator:
    """Validates semantic rule JSON files against schema."""
    
    # Valid enum values
    VALID_LOGIC_OPERATORS = ["AND", "OR"]
    VALID_OPERATORS = ["equals", "contains", "regex", "wildcard"]
    VALID_SEVERITIES = ["info", "low", "medium", "high", "critical"]
    VALID_SCOPES = ["global", "wing", "pipeline"]
    
    def __init__(self, schema_path: Optional[Path] = None):
        """
        Initialize validator.
        
        Args:
            schema_path: Optional path to JSON schema file
        """
        self.schema_path = schema_path
        self.schema = self._load_schema() if schema_path else None
    
    def _load_schema(self) -> Optional[Dict[str, Any]]:
        """Load JSON schema from file."""
        if not self.schema_path or not self.schema_path.exists():
            return None
        
        try:
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load schema from {self.schema_path}: {e}")
            return None
    
    def validate_file(self, json_path: Path) -> ValidationResult:
        """
        Validate a JSON file and return detailed results.
        
        Args:
            json_path: Path to JSON file to validate
            
        Returns:
            ValidationResult with errors and warnings
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []
        
        # Check file exists and is readable
        if not json_path.exists():
            errors.append(ValidationError(
                rule_id=None,
                rule_index=-1,
                field="file",
                message=f"File not found: {json_path}",
                severity="error",
                suggestion="Ensure the file path is correct and the file exists."
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        
        # Parse JSON
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(ValidationError(
                rule_id=None,
                rule_index=-1,
                field="json_syntax",
                message=f"JSON syntax error at line {e.lineno}, column {e.colno}: {e.msg}",
                severity="error",
                suggestion="Fix the JSON syntax error. Check for missing brackets, quotes, or commas."
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        except Exception as e:
            errors.append(ValidationError(
                rule_id=None,
                rule_index=-1,
                field="file_read",
                message=f"Failed to read file: {e}",
                severity="error",
                suggestion="Check file permissions and ensure the file is not corrupted."
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        
        # Validate top-level structure
        if not isinstance(data, dict):
            errors.append(ValidationError(
                rule_id=None,
                rule_index=-1,
                field="structure",
                message="JSON root must be an object/dictionary",
                severity="error",
                suggestion='Wrap rules in an object: {"rules": [...]}'
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        
        if "rules" not in data:
            errors.append(ValidationError(
                rule_id=None,
                rule_index=-1,
                field="rules",
                message="Missing 'rules' array in JSON",
                severity="error",
                suggestion='Add a "rules" array: {"rules": [...]}'
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        
        if not isinstance(data["rules"], list):
            errors.append(ValidationError(
                rule_id=None,
                rule_index=-1,
                field="rules",
                message="'rules' must be an array",
                severity="error",
                suggestion='Change "rules" to an array: {"rules": [...]}'
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        
        # Validate each rule
        rules = data["rules"]
        rule_ids_seen = set()
        
        for index, rule in enumerate(rules):
            rule_errors = self.validate_rule(rule, index)
            errors.extend(rule_errors)
            
            # Check for duplicate rule_id
            if isinstance(rule, dict) and "rule_id" in rule:
                rule_id = rule["rule_id"]
                if rule_id in rule_ids_seen:
                    warnings.append(ValidationError(
                        rule_id=rule_id,
                        rule_index=index,
                        field="rule_id",
                        message=f"Duplicate rule_id '{rule_id}' found",
                        severity="warning",
                        suggestion="Use unique rule_id values or remove duplicate rules."
                    ))
                rule_ids_seen.add(rule_id)
        
        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            rules_count=len(rules)
        )
    
    def validate_rule(self, rule: Any, rule_index: int) -> List[ValidationError]:
        """
        Validate a single rule structure.
        
        Args:
            rule: Rule dictionary to validate
            rule_index: Index of rule in array
            
        Returns:
            List of validation errors
        """
        errors: List[ValidationError] = []
        
        # Rule must be a dictionary
        if not isinstance(rule, dict):
            errors.append(ValidationError(
                rule_id=None,
                rule_index=rule_index,
                field="rule",
                message="Rule must be an object/dictionary",
                severity="error",
                suggestion="Ensure each rule is a JSON object with fields."
            ))
            return errors
        
        rule_id = rule.get("rule_id")
        
        # Check required fields
        required_fields = ["rule_id", "name", "semantic_value", "conditions", "logic_operator"]
        for field_name in required_fields:
            if field_name not in rule:
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field=field_name,
                    message=f"Missing required field '{field_name}'",
                    severity="error",
                    suggestion=f"Add '{field_name}' field to the rule."
                ))
        
        # Validate field types and values
        if "rule_id" in rule:
            if not isinstance(rule["rule_id"], str) or not rule["rule_id"].strip():
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="rule_id",
                    message="rule_id must be a non-empty string",
                    severity="error",
                    suggestion="Set rule_id to a unique string identifier."
                ))
        
        if "name" in rule:
            if not isinstance(rule["name"], str) or not rule["name"].strip():
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="name",
                    message="name must be a non-empty string",
                    severity="error",
                    suggestion="Set name to a descriptive string."
                ))
        
        if "semantic_value" in rule:
            if not isinstance(rule["semantic_value"], str) or not rule["semantic_value"].strip():
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="semantic_value",
                    message="semantic_value must be a non-empty string",
                    severity="error",
                    suggestion="Set semantic_value to a meaningful description."
                ))
        
        # Validate logic_operator
        if "logic_operator" in rule:
            if rule["logic_operator"] not in self.VALID_LOGIC_OPERATORS:
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="logic_operator",
                    message=f"Invalid logic_operator '{rule['logic_operator']}'. Must be 'AND' or 'OR'.",
                    severity="error",
                    suggestion="Change logic_operator to either 'AND' or 'OR'."
                ))
        
        # Validate conditions
        if "conditions" in rule:
            if not isinstance(rule["conditions"], list):
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="conditions",
                    message="conditions must be an array",
                    severity="error",
                    suggestion="Change conditions to an array of condition objects."
                ))
            else:
                for cond_index, condition in enumerate(rule["conditions"]):
                    cond_errors = self._validate_condition(condition, rule_id, rule_index, cond_index)
                    errors.extend(cond_errors)
        
        # Validate optional fields
        if "confidence" in rule:
            try:
                confidence = float(rule["confidence"])
                if not (0.0 <= confidence <= 1.0):
                    errors.append(ValidationError(
                        rule_id=rule_id,
                        rule_index=rule_index,
                        field="confidence",
                        message=f"confidence value {confidence} is out of range. Must be between 0.0 and 1.0.",
                        severity="error",
                        suggestion="Set confidence to a value between 0.0 and 1.0 (e.g., 0.85)."
                    ))
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="confidence",
                    message="confidence must be a number",
                    severity="error",
                    suggestion="Set confidence to a float value between 0.0 and 1.0."
                ))
        
        if "severity" in rule:
            if rule["severity"] not in self.VALID_SEVERITIES:
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="severity",
                    message=f"Invalid severity '{rule['severity']}'. Must be one of: {', '.join(self.VALID_SEVERITIES)}.",
                    severity="error",
                    suggestion=f"Change severity to one of: {', '.join(self.VALID_SEVERITIES)}."
                ))
        
        if "scope" in rule:
            if rule["scope"] not in self.VALID_SCOPES:
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field="scope",
                    message=f"Invalid scope '{rule['scope']}'. Must be one of: {', '.join(self.VALID_SCOPES)}.",
                    severity="error",
                    suggestion=f"Change scope to one of: {', '.join(self.VALID_SCOPES)}."
                ))
        
        return errors
    
    def _validate_condition(
        self,
        condition: Any,
        rule_id: Optional[str],
        rule_index: int,
        cond_index: int
    ) -> List[ValidationError]:
        """
        Validate a single condition within a rule.
        
        Args:
            condition: Condition dictionary to validate
            rule_id: Parent rule ID
            rule_index: Parent rule index
            cond_index: Condition index within rule
            
        Returns:
            List of validation errors
        """
        errors: List[ValidationError] = []
        field_prefix = f"conditions[{cond_index}]"
        
        if not isinstance(condition, dict):
            errors.append(ValidationError(
                rule_id=rule_id,
                rule_index=rule_index,
                field=field_prefix,
                message="Condition must be an object/dictionary",
                severity="error",
                suggestion="Ensure each condition is a JSON object with fields."
            ))
            return errors
        
        # Check required condition fields
        required_cond_fields = ["feather_id", "field_name", "value", "operator"]
        for field_name in required_cond_fields:
            if field_name not in condition:
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field=f"{field_prefix}.{field_name}",
                    message=f"Missing required field '{field_name}' in condition",
                    severity="error",
                    suggestion=f"Add '{field_name}' field to the condition."
                ))
        
        # Validate condition field types
        if "feather_id" in condition:
            if not isinstance(condition["feather_id"], str) or not condition["feather_id"].strip():
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field=f"{field_prefix}.feather_id",
                    message="feather_id must be a non-empty string",
                    severity="error",
                    suggestion="Set feather_id to the artifact source name."
                ))
        
        if "field_name" in condition:
            if not isinstance(condition["field_name"], str) or not condition["field_name"].strip():
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field=f"{field_prefix}.field_name",
                    message="field_name must be a non-empty string",
                    severity="error",
                    suggestion="Set field_name to the field to match."
                ))
        
        if "value" in condition:
            if not isinstance(condition["value"], str):
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field=f"{field_prefix}.value",
                    message="value must be a string",
                    severity="error",
                    suggestion="Set value to a string (use '*' for wildcard)."
                ))
        
        # Validate operator
        if "operator" in condition:
            if condition["operator"] not in self.VALID_OPERATORS:
                errors.append(ValidationError(
                    rule_id=rule_id,
                    rule_index=rule_index,
                    field=f"{field_prefix}.operator",
                    message=f"Invalid operator '{condition['operator']}'. Must be one of: {', '.join(self.VALID_OPERATORS)}.",
                    severity="error",
                    suggestion=f"Change operator to one of: {', '.join(self.VALID_OPERATORS)}."
                ))
            
            # Validate regex patterns
            if condition["operator"] == "regex" and "value" in condition:
                try:
                    re.compile(condition["value"])
                except re.error as e:
                    errors.append(ValidationError(
                        rule_id=rule_id,
                        rule_index=rule_index,
                        field=f"{field_prefix}.value",
                        message=f"Invalid regex pattern: {e}",
                        severity="error",
                        suggestion="Fix the regex pattern syntax."
                    ))
        
        return errors
    
    def generate_error_report(self, result: ValidationResult) -> str:
        """
        Generate human-readable error report.
        
        Args:
            result: ValidationResult to format
            
        Returns:
            Formatted error report string
        """
        return result.get_report()
