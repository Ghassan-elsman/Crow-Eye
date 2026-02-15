"""
Semantic Mapping Controller

Controls when semantic mappings are applied - during correlation or in the Identity Semantic Phase.
This ensures semantic processing isolation by preventing semantic mappings during correlation
when the Identity Semantic Phase is enabled.
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class SemanticMappingController:
    """
    Controls semantic mapping behavior to ensure processing isolation.
    
    When the Identity Semantic Phase is enabled, this controller prevents
    semantic mappings from being applied during correlation processing,
    ensuring they only occur in the dedicated Identity Semantic Phase.
    
    Requirements: 1.5, 2.5
    Property 6: Semantic Processing Isolation
    """
    
    def __init__(self, identity_semantic_controller=None):
        """
        Initialize Semantic Mapping Controller.
        
        Args:
            identity_semantic_controller: Optional IdentitySemanticController instance
        """
        self.identity_semantic_controller = identity_semantic_controller
        self._per_record_mapping_disabled = False
    
    def should_apply_per_record_semantic_mapping(self) -> bool:
        """
        Check if semantic mappings should be applied per-record during correlation.
        
        Returns False when Identity Semantic Phase is enabled and configured to
        disable per-record semantic mapping, ensuring semantic processing isolation.
        
        Returns:
            True if per-record semantic mapping should be applied, False otherwise
            
        Requirements: 1.5, 2.5
        Property 6: Semantic Processing Isolation
        """
        # If no Identity Semantic Controller, allow per-record mapping (backward compatibility)
        if not self.identity_semantic_controller:
            return True
        
        # Check if Identity Semantic Phase wants to disable per-record mapping
        if hasattr(self.identity_semantic_controller, 'should_disable_per_record_semantic_mapping'):
            should_disable = self.identity_semantic_controller.should_disable_per_record_semantic_mapping()
            
            if should_disable:
                # Log once when first disabled
                if not self._per_record_mapping_disabled:
                    logger.info("[Semantic Mapping Controller] Per-record semantic mapping disabled - "
                               "will be applied in Identity Semantic Phase")
                    self._per_record_mapping_disabled = True
                
                return False
        
        # Default: allow per-record mapping
        return True
    
    def apply_to_correlation_results_with_isolation(self, 
                                                    semantic_integration,
                                                    results: List[Dict[str, Any]], 
                                                    wing_id: Optional[str] = None,
                                                    pipeline_id: Optional[str] = None,
                                                    artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply semantic mappings to correlation results with isolation control.
        
        This method wraps the semantic integration's apply_to_correlation_results
        method and checks if per-record semantic mapping should be skipped.
        
        Args:
            semantic_integration: SemanticMappingIntegration instance
            results: List of correlation result records
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            artifact_type: Optional artifact type
            
        Returns:
            Enhanced results (or original results if per-record mapping is disabled)
            
        Requirements: 1.5, 2.5
        Property 6: Semantic Processing Isolation
        """
        # Check if per-record semantic mapping should be applied
        if not self.should_apply_per_record_semantic_mapping():
            # Skip per-record semantic mapping - will be done in Identity Semantic Phase
            logger.debug("[Semantic Mapping Controller] Skipping per-record semantic mapping "
                        "(will be applied in Identity Semantic Phase)")
            
            # Return results with metadata indicating semantic mapping will be done later
            enhanced_results = []
            for result in results:
                enhanced_result = result.copy()
                enhanced_result['_semantic_mapping_deferred'] = True
                enhanced_result['_semantic_mapping_phase'] = 'identity_semantic_phase'
                enhanced_results.append(enhanced_result)
            
            return enhanced_results
        
        # Apply per-record semantic mapping as normal
        return semantic_integration.apply_to_correlation_results(
            results, wing_id, pipeline_id, artifact_type
        )
    
    def set_identity_semantic_controller(self, controller):
        """
        Set the Identity Semantic Controller.
        
        Args:
            controller: IdentitySemanticController instance
        """
        self.identity_semantic_controller = controller
    
    def reset(self):
        """Reset the controller state"""
        self._per_record_mapping_disabled = False
