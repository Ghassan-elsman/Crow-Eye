"""
Results Formatter

Formats correlation results with semantic mappings and enhanced display.
"""

import logging
from typing import Dict, Any, Optional, List

from ..config.semantic_mapping import SemanticMappingManager
from .correlation_result import CorrelationMatch, CorrelationResult

logger = logging.getLogger(__name__)


class ResultsFormatter:
    """
    Formats correlation results with semantic value mappings.
    
    Applies semantic mappings to technical values in correlation results,
    making them more human-readable and easier to interpret.
    """
    
    def __init__(self, semantic_manager: Optional[SemanticMappingManager] = None):
        """
        Initialize ResultsFormatter.
        
        Args:
            semantic_manager: SemanticMappingManager instance (creates new if None)
        """
        self.semantic_manager = semantic_manager or SemanticMappingManager()
    
    def format_match_record(self, record: Dict[str, Any], 
                           source: str,
                           wing_id: Optional[str] = None,
                           pipeline_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Format a single match record with semantic values.
        
        Args:
            record: Record dictionary
            source: Source feather (e.g., "SecurityLogs")
            wing_id: Optional Wing ID for Wing-specific mappings
            pipeline_id: Optional Pipeline ID for Pipeline-specific mappings
            
        Returns:
            Formatted record with semantic values added
        """
        formatted_record = record.copy()
        
        # Fields that commonly have semantic mappings
        semantic_fields = ['EventID', 'event_id', 'Status', 'status', 'Type', 'type']
        
        for field in semantic_fields:
            if field in record:
                technical_value = str(record[field])
                semantic_value = self.semantic_manager.get_semantic_value(
                    source, field, technical_value, wing_id, pipeline_id
                )
                
                if semantic_value:
                    # Add semantic value with special key
                    formatted_record[f"{field}_semantic"] = semantic_value
                    # Also create formatted display string
                    formatted_record[f"{field}_display"] = f"{technical_value} ({semantic_value})"
        
        return formatted_record
    
    def format_match(self, match: CorrelationMatch,
                    wing_id: Optional[str] = None,
                    pipeline_id: Optional[str] = None) -> CorrelationMatch:
        """
        Format a correlation match with semantic values.
        
        Args:
            match: CorrelationMatch to format
            wing_id: Optional Wing ID
            pipeline_id: Optional Pipeline ID
            
        Returns:
            New CorrelationMatch with formatted records
        """
        formatted_records = {}
        
        for feather_id, record in match.feather_records.items():
            # Determine source from feather_id or artifact type
            source = self._get_source_from_feather_id(feather_id)
            formatted_records[feather_id] = self.format_match_record(
                record, source, wing_id, pipeline_id
            )
        
        # Create new match with formatted records
        return CorrelationMatch(
            match_id=match.match_id,
            timestamp=match.timestamp,
            feather_records=formatted_records,
            match_score=match.match_score,
            feather_count=match.feather_count,
            time_spread_seconds=match.time_spread_seconds,
            anchor_feather_id=match.anchor_feather_id,
            anchor_artifact_type=match.anchor_artifact_type,
            matched_application=match.matched_application,
            matched_file_path=match.matched_file_path,
            matched_event_id=match.matched_event_id,
            score_breakdown=match.score_breakdown,
            confidence_score=match.confidence_score,
            confidence_category=match.confidence_category,
            weighted_score=match.weighted_score,
            time_deltas=match.time_deltas,
            field_similarity_scores=match.field_similarity_scores,
            candidate_counts=match.candidate_counts,
            algorithm_version=match.algorithm_version,
            wing_config_hash=match.wing_config_hash
        )
    
    def format_result(self, result: CorrelationResult,
                     wing_id: Optional[str] = None,
                     pipeline_id: Optional[str] = None) -> CorrelationResult:
        """
        Format a correlation result with semantic values.
        
        Args:
            result: CorrelationResult to format
            wing_id: Optional Wing ID
            pipeline_id: Optional Pipeline ID
            
        Returns:
            New CorrelationResult with formatted matches
        """
        formatted_matches = [
            self.format_match(match, wing_id, pipeline_id)
            for match in result.matches
        ]
        
        # Create new result with formatted matches
        formatted_result = CorrelationResult(
            wing_id=result.wing_id,
            wing_name=result.wing_name,
            execution_time=result.execution_time,
            execution_duration_seconds=result.execution_duration_seconds,
            matches=formatted_matches,
            total_matches=result.total_matches,
            feathers_processed=result.feathers_processed,
            total_records_scanned=result.total_records_scanned,
            duplicates_prevented=result.duplicates_prevented,
            matches_failed_validation=result.matches_failed_validation,
            anchor_feather_id=result.anchor_feather_id,
            anchor_selection_reason=result.anchor_selection_reason,
            filter_statistics=result.filter_statistics,
            feather_metadata=result.feather_metadata,
            performance_metrics=result.performance_metrics,
            filters_applied=result.filters_applied,
            errors=result.errors,
            warnings=result.warnings
        )
        
        return formatted_result
    
    def _get_source_from_feather_id(self, feather_id: str) -> str:
        """
        Determine source name from feather ID.
        
        Args:
            feather_id: Feather identifier
            
        Returns:
            Source name for semantic mapping lookup
        """
        # Map common feather IDs to sources
        source_mapping = {
            'security_logs': 'SecurityLogs',
            'system_logs': 'SystemLogs',
            'application_logs': 'ApplicationLogs',
            'prefetch': 'Prefetch',
            'shimcache': 'ShimCache',
            'amcache': 'AmCache',
            'registry': 'Registry',
            'userassist': 'Registry',
            'recentdocs': 'Registry',
            'shellbags': 'Registry',
        }
        
        # Try direct lookup
        if feather_id in source_mapping:
            return source_mapping[feather_id]
        
        # Try partial match
        for key, value in source_mapping.items():
            if key in feather_id.lower():
                return value
        
        # Default: capitalize feather_id
        return feather_id.replace('_', ' ').title()
    
    def get_semantic_value_display(self, source: str, field: str, 
                                   technical_value: str,
                                   wing_id: Optional[str] = None,
                                   pipeline_id: Optional[str] = None) -> str:
        """
        Get formatted display string for a technical value.
        
        Args:
            source: Source of the value
            field: Field name
            technical_value: Technical value
            wing_id: Optional Wing ID
            pipeline_id: Optional Pipeline ID
            
        Returns:
            Formatted string: "TechnicalValue (SemanticValue)" or just "TechnicalValue"
        """
        semantic_value = self.semantic_manager.get_semantic_value(
            source, field, technical_value, wing_id, pipeline_id
        )
        
        if semantic_value:
            return f"{technical_value} ({semantic_value})"
        return technical_value
    
    def get_all_semantic_mappings_for_source(self, source: str) -> List[Dict[str, str]]:
        """
        Get all semantic mappings for a specific source.
        
        Args:
            source: Source name (e.g., "SecurityLogs")
            
        Returns:
            List of mapping dictionaries
        """
        all_mappings = self.semantic_manager.get_all_mappings("global")
        
        source_mappings = []
        for mapping in all_mappings:
            if mapping.source == source:
                source_mappings.append({
                    'field': mapping.field,
                    'technical_value': mapping.technical_value,
                    'semantic_value': mapping.semantic_value,
                    'description': mapping.description
                })
        
        return source_mappings


def apply_semantic_mappings_to_result(result: CorrelationResult,
                                     wing_id: Optional[str] = None,
                                     pipeline_id: Optional[str] = None) -> CorrelationResult:
    """
    Convenience function to apply semantic mappings to a result.
    
    Args:
        result: CorrelationResult to format
        wing_id: Optional Wing ID
        pipeline_id: Optional Pipeline ID
        
    Returns:
        Formatted CorrelationResult
    """
    formatter = ResultsFormatter()
    return formatter.format_result(result, wing_id, pipeline_id)
