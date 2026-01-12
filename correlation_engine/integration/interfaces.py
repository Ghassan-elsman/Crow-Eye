"""
Integration Interfaces

Defines abstract base classes (interfaces) for integration components.
These interfaces enable dependency injection, testing with mocks, and
decoupling between engines and integration implementations.

The interfaces follow the Dependency Inversion Principle, allowing
high-level modules (engines) to depend on abstractions rather than
concrete implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class IntegrationStatistics:
    """Base class for integration statistics"""
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    fallback_count: int = 0
    
    def get_success_rate(self) -> float:
        """Calculate success rate as percentage"""
        if self.total_operations == 0:
            return 0.0
        return (self.successful_operations / self.total_operations) * 100.0


class IScoringIntegration(ABC):
    """
    Interface for weighted scoring integration.
    
    Defines the contract for scoring integration implementations,
    enabling dependency injection and testing with mock implementations.
    """
    
    @abstractmethod
    def calculate_match_scores(self,
                              match_records: Dict[str, Dict],
                              wing_config: Any,
                              case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate weighted scores for correlation matches.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing_config: Wing configuration with weights
            case_id: Optional case ID for case-specific configuration
            
        Returns:
            Dictionary with score, interpretation, and breakdown:
            {
                'score': float,
                'interpretation': str,
                'breakdown': Dict[str, Any],
                'matched_feathers': int,
                'total_feathers': int,
                'scoring_mode': str
            }
        """
        pass
    
    @abstractmethod
    def reload_configuration(self) -> bool:
        """
        Reload scoring configuration from config manager.
        
        This method is called when configuration changes are detected,
        allowing the integration to update its internal state without
        requiring application restart.
        
        Returns:
            True if reload was successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_statistics(self) -> IntegrationStatistics:
        """
        Get scoring integration statistics.
        
        Returns:
            IntegrationStatistics object with operation counts and metrics
        """
        pass
    
    @abstractmethod
    def load_case_specific_scoring_weights(self, case_id: str) -> bool:
        """
        Load case-specific scoring weights and configuration.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case-specific configuration was loaded, False otherwise
        """
        pass
    
    @abstractmethod
    def interpret_score(self, score: float, case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Interpret a weighted score into human-readable information.
        
        Args:
            score: Weighted score to interpret
            case_id: Optional case ID for case-specific interpretation
            
        Returns:
            Dictionary with interpretation details:
            {
                'label': str,
                'tier': int,
                'confidence_percentage': float,
                'description': str
            }
        """
        pass
    
    @abstractmethod
    def validate_scoring_configuration(self,
                                      wing_config: Any,
                                      scoring_config: Any) -> Dict[str, Any]:
        """
        Validate wing scoring configuration against rules.
        
        Args:
            wing_config: Wing configuration to validate
            scoring_config: Scoring configuration with validation rules
            
        Returns:
            Dictionary with validation results:
            {
                'valid': bool,
                'errors': List[str],
                'warnings': List[str],
                'fixes': List[Dict[str, Any]]
            }
        """
        pass


class ISemanticMappingIntegration(ABC):
    """
    Interface for semantic mapping integration.
    
    Defines the contract for semantic mapping integration implementations,
    enabling dependency injection and testing with mock implementations.
    """
    
    @abstractmethod
    def apply_to_correlation_results(self,
                                    results: List[Dict[str, Any]],
                                    wing_id: Optional[str] = None,
                                    pipeline_id: Optional[str] = None,
                                    artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply semantic mappings to correlation results.
        
        Args:
            results: List of correlation result records
            wing_id: Optional wing ID for wing-specific mappings
            pipeline_id: Optional pipeline ID for pipeline-specific mappings
            artifact_type: Optional artifact type for filtering mappings
            
        Returns:
            Enhanced results with semantic mapping information.
            Each result will have a '_semantic_mappings' key with:
            {
                'field_name': {
                    'semantic_value': str,
                    'description': str,
                    'category': str,
                    'severity': str,
                    'confidence': float,
                    'mapping_source': str
                }
            }
        """
        pass
    
    @abstractmethod
    def reload_configuration(self) -> bool:
        """
        Reload semantic mapping configuration from config manager.
        
        This method is called when configuration changes are detected,
        allowing the integration to update its internal state without
        requiring application restart.
        
        Returns:
            True if reload was successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_statistics(self) -> IntegrationStatistics:
        """
        Get semantic mapping integration statistics.
        
        Returns:
            IntegrationStatistics object with operation counts and metrics
        """
        pass
    
    @abstractmethod
    def load_case_specific_mappings(self, case_id: str) -> bool:
        """
        Load case-specific semantic mappings.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case-specific mappings were loaded, False otherwise
        """
        pass
    
    @abstractmethod
    def get_semantic_display_data(self,
                                 record: Dict[str, Any],
                                 artifact_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get semantic information for UI display.
        
        Args:
            record: Record to get semantic data for
            artifact_type: Optional artifact type
            
        Returns:
            Dictionary with semantic display information:
            {
                'has_semantic_mappings': bool,
                'semantic_fields': Dict[str, Any],
                'unmapped_fields': List[Dict[str, Any]],
                'mapping_summary': {
                    'total_fields': int,
                    'mapped_fields': int,
                    'unmapped_fields': int
                }
            }
        """
        pass
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """
        Check if semantic mapping is enabled.
        
        Returns:
            True if semantic mapping is enabled, False otherwise
        """
        pass


class IConfigurationObserver(ABC):
    """
    Interface for configuration change observers.
    
    Components that need to react to configuration changes should
    implement this interface and register with the configuration manager.
    """
    
    @abstractmethod
    def on_configuration_changed(self, old_config: Any, new_config: Any) -> None:
        """
        Called when configuration changes.
        
        Args:
            old_config: Previous configuration state
            new_config: New configuration state
        """
        pass


# Type aliases for better readability
ScoringIntegration = IScoringIntegration
SemanticMappingIntegration = ISemanticMappingIntegration
ConfigurationObserver = IConfigurationObserver
