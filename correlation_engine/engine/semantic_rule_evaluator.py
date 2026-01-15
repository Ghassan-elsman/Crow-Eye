"""
Semantic Rule Evaluator

Evaluates semantic rules against correlation results with support for:
- Rule priority (wing > pipeline > global)
- AND/OR logic evaluation
- Wildcard matching
- Identity-level semantic results

This module provides the SemanticRuleEvaluator class that integrates
with both Identity Correlation Engine and Time-Based Engine.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

from ..config.semantic_mapping import SemanticRule, SemanticCondition, SemanticMappingManager

logger = logging.getLogger(__name__)


@dataclass
class SemanticMatchResult:
    """Result of a semantic rule match."""
    rule_id: str
    rule_name: str
    semantic_value: str
    logic_operator: str
    matched_feathers: List[str]
    conditions: List[str]
    confidence: float
    category: str
    severity: str
    scope: str  # global, wing, pipeline
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'rule_id': self.rule_id,
            'rule_name': self.rule_name,
            'semantic_value': self.semantic_value,
            'logic_operator': self.logic_operator,
            'matched_feathers': self.matched_feathers,
            'conditions': self.conditions,
            'confidence': self.confidence,
            'category': self.category,
            'severity': self.severity,
            'scope': self.scope
        }


@dataclass
class EvaluationStatistics:
    """Statistics from semantic rule evaluation."""
    total_rules_evaluated: int = 0
    rules_matched: int = 0
    identities_evaluated: int = 0
    identities_with_matches: int = 0
    wing_rules_applied: int = 0
    pipeline_rules_applied: int = 0
    global_rules_applied: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'total_rules_evaluated': self.total_rules_evaluated,
            'rules_matched': self.rules_matched,
            'identities_evaluated': self.identities_evaluated,
            'identities_with_matches': self.identities_with_matches,
            'wing_rules_applied': self.wing_rules_applied,
            'pipeline_rules_applied': self.pipeline_rules_applied,
            'global_rules_applied': self.global_rules_applied
        }


class SemanticRuleEvaluator:
    """
    Evaluates semantic rules against correlation results.
    
    Supports:
    - Rule priority: wing-specific > pipeline-specific > global
    - AND/OR logic for multi-condition rules
    - Wildcard matching for "any value" patterns
    - Identity-level and anchor-level evaluation
    
    Usage:
        evaluator = SemanticRuleEvaluator(semantic_manager)
        results = evaluator.evaluate_identity(identity_data, wing_id='my_wing')
    """
    
    def __init__(self, semantic_manager: Optional[SemanticMappingManager] = None,
                 debug_mode: bool = False):
        """
        Initialize SemanticRuleEvaluator.
        
        Args:
            semantic_manager: SemanticMappingManager instance for rule storage
            debug_mode: Enable debug logging
        """
        self.semantic_manager = semantic_manager or SemanticMappingManager()
        self.debug_mode = debug_mode
        self.statistics = EvaluationStatistics()
        
        # Cache for merged rules by context
        self._rule_cache: Dict[str, List[SemanticRule]] = {}
    
    def get_rules_for_context(self, wing_id: Optional[str] = None,
                              pipeline_id: Optional[str] = None,
                              wing_rules: Optional[List[Dict]] = None) -> List[SemanticRule]:
        """
        Get all applicable rules for a given execution context.
        
        Priority order (highest to lowest):
        1. Wing-specific rules (from wing config)
        2. Wing-specific rules (from semantic manager)
        3. Pipeline-specific rules
        4. Global rules
        
        Args:
            wing_id: Wing ID for wing-specific rules
            pipeline_id: Pipeline ID for pipeline-specific rules
            wing_rules: Wing-specific rules from WingConfig.semantic_rules
            
        Returns:
            List of SemanticRule objects in priority order
        """
        cache_key = f"{wing_id}:{pipeline_id}:{len(wing_rules or [])}"
        
        if cache_key in self._rule_cache:
            return self._rule_cache[cache_key]
        
        rules = []
        
        # 1. Wing-specific rules from WingConfig (highest priority)
        if wing_rules:
            for rule_dict in wing_rules:
                try:
                    rule = SemanticRule.from_dict(rule_dict)
                    rule.scope = "wing"
                    rule.wing_id = wing_id
                    rules.append(rule)
                except Exception as e:
                    logger.warning(f"Failed to parse wing rule: {e}")
        
        # 2. Wing-specific rules from semantic manager
        if wing_id:
            wing_manager_rules = self.semantic_manager.get_rules(
                scope="wing", wing_id=wing_id
            )
            # Avoid duplicates by rule_id
            existing_ids = {r.rule_id for r in rules}
            for rule in wing_manager_rules:
                if rule.rule_id not in existing_ids:
                    rules.append(rule)
        
        # 3. Pipeline-specific rules
        if pipeline_id:
            pipeline_rules = self.semantic_manager.get_rules(
                scope="pipeline", pipeline_id=pipeline_id
            )
            existing_ids = {r.rule_id for r in rules}
            for rule in pipeline_rules:
                if rule.rule_id not in existing_ids:
                    rules.append(rule)
        
        # 4. Global rules (lowest priority)
        global_rules = self.semantic_manager.get_rules(scope="global")
        existing_ids = {r.rule_id for r in rules}
        for rule in global_rules:
            if rule.rule_id not in existing_ids:
                rules.append(rule)
        
        # Cache the result
        self._rule_cache[cache_key] = rules
        
        if self.debug_mode:
            logger.debug(f"Loaded {len(rules)} rules for context: wing={wing_id}, pipeline={pipeline_id}")
        
        return rules
    
    def evaluate_identity(self, identity_data: Dict[str, Any],
                         wing_id: Optional[str] = None,
                         pipeline_id: Optional[str] = None,
                         wing_rules: Optional[List[Dict]] = None) -> List[SemanticMatchResult]:
        """
        Evaluate all semantic rules against an identity's data.
        
        Args:
            identity_data: Identity data including anchors and evidence
            wing_id: Wing ID for wing-specific rules
            pipeline_id: Pipeline ID for pipeline-specific rules
            wing_rules: Wing-specific rules from WingConfig
            
        Returns:
            List of SemanticMatchResult for matched rules
        """
        self.statistics.identities_evaluated += 1
        
        # Get applicable rules
        rules = self.get_rules_for_context(wing_id, pipeline_id, wing_rules)
        
        if not rules:
            return []
        
        # Build records dict from identity data
        records = self._build_records_from_identity(identity_data)
        
        if not records:
            return []
        
        # Evaluate each rule
        matched_results = []
        
        for rule in rules:
            self.statistics.total_rules_evaluated += 1
            
            matches, matched_conditions = rule.evaluate(records)
            
            if matches:
                self.statistics.rules_matched += 1
                
                # Track scope statistics
                if rule.scope == "wing":
                    self.statistics.wing_rules_applied += 1
                elif rule.scope == "pipeline":
                    self.statistics.pipeline_rules_applied += 1
                else:
                    self.statistics.global_rules_applied += 1
                
                result = SemanticMatchResult(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    semantic_value=rule.semantic_value,
                    logic_operator=rule.logic_operator,
                    matched_feathers=matched_conditions,
                    conditions=[
                        f"{c.feather_id}.{c.field_name} {c.operator} '{c.value}'"
                        for c in rule.conditions
                    ],
                    confidence=rule.confidence,
                    category=rule.category,
                    severity=rule.severity,
                    scope=rule.scope
                )
                matched_results.append(result)
                
                if self.debug_mode:
                    logger.debug(f"Rule '{rule.name}' matched: {rule.semantic_value}")
        
        if matched_results:
            self.statistics.identities_with_matches += 1
        
        return matched_results
    
    def _build_records_from_identity(self, identity_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Build records dictionary from identity data for rule evaluation.
        
        Args:
            identity_data: Identity data with anchors and evidence
            
        Returns:
            Dict mapping feather_id to record data
        """
        records = {}
        
        # Extract from anchors
        anchors = identity_data.get('anchors', [])
        for anchor in anchors:
            feather_id = anchor.get('feather_id', '')
            if feather_id and feather_id not in records:
                # Use anchor data directly
                records[feather_id] = anchor
            
            # Also check evidence rows within anchor
            evidence_rows = anchor.get('evidence_rows', [])
            for evidence in evidence_rows:
                fid = evidence.get('feather_id', '')
                if fid and fid not in records:
                    data = evidence.get('data', evidence)
                    records[fid] = data
        
        # Extract from sub_identities (new format)
        sub_identities = identity_data.get('sub_identities', [])
        for sub in sub_identities:
            for anchor in sub.get('anchors', []):
                feather_id = anchor.get('feather_id', '')
                if feather_id and feather_id not in records:
                    records[feather_id] = anchor
                
                for evidence in anchor.get('evidence_rows', []):
                    fid = evidence.get('feather_id', '')
                    if fid and fid not in records:
                        data = evidence.get('data', evidence)
                        records[fid] = data
        
        # Extract from direct evidence list
        evidence_list = identity_data.get('evidence', [])
        for evidence in evidence_list:
            feather_id = evidence.get('feather_id', '')
            if feather_id and feather_id not in records:
                records[feather_id] = evidence
        
        # Extract from feather_records (CorrelationMatch format)
        feather_records = identity_data.get('feather_records', {})
        for feather_id, record in feather_records.items():
            if feather_id not in records:
                records[feather_id] = record if isinstance(record, dict) else {}
        
        return records
    
    def evaluate_match(self, match: Any,
                      wing_id: Optional[str] = None,
                      pipeline_id: Optional[str] = None,
                      wing_rules: Optional[List[Dict]] = None) -> List[SemanticMatchResult]:
        """
        Evaluate semantic rules against a CorrelationMatch.
        
        Args:
            match: CorrelationMatch object
            wing_id: Wing ID for wing-specific rules
            pipeline_id: Pipeline ID for pipeline-specific rules
            wing_rules: Wing-specific rules from WingConfig
            
        Returns:
            List of SemanticMatchResult for matched rules
        """
        # Convert match to identity-like format
        identity_data = {
            'feather_records': getattr(match, 'feather_records', {}),
            'anchors': [],
            'evidence': []
        }
        
        return self.evaluate_identity(identity_data, wing_id, pipeline_id, wing_rules)
    
    def evaluate_window(self, window_data: Dict[str, Any],
                       wing_id: Optional[str] = None,
                       pipeline_id: Optional[str] = None,
                       wing_rules: Optional[List[Dict]] = None) -> Dict[str, List[SemanticMatchResult]]:
        """
        Evaluate semantic rules for all identities in a time window.
        
        Args:
            window_data: Time window data with identities
            wing_id: Wing ID for wing-specific rules
            pipeline_id: Pipeline ID for pipeline-specific rules
            wing_rules: Wing-specific rules from WingConfig
            
        Returns:
            Dict mapping identity_name to list of SemanticMatchResult
        """
        results = {}
        
        identities = window_data.get('identities', [])
        for identity in identities:
            identity_name = identity.get('identity_name', 'Unknown')
            matched = self.evaluate_identity(identity, wing_id, pipeline_id, wing_rules)
            if matched:
                results[identity_name] = matched
        
        return results
    
    def clear_cache(self):
        """Clear the rule cache."""
        self._rule_cache.clear()
    
    def reset_statistics(self):
        """Reset evaluation statistics."""
        self.statistics = EvaluationStatistics()
    
    def get_statistics(self) -> EvaluationStatistics:
        """Get current evaluation statistics."""
        return self.statistics
