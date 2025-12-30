"""
Weighted Scoring Engine

Calculates match confidence scores based on weighted contributions from matched Feathers.
Provides sophisticated scoring for correlation matches using configurable weights and tiers.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class WeightedScoringEngine:
    """
    Calculates weighted scores for correlation matches.
    
    This engine implements a sophisticated scoring system where each matched Feather
    contributes to the overall match score based on its configured weight. Scores are
    then interpreted using configurable thresholds to provide human-readable confidence levels.
    """
    
    def calculate_match_score(self, 
                             match_records: Dict[str, Dict],
                             wing_config: Any) -> Dict[str, Any]:
        """
        Calculate weighted score for a match.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing_config: Wing configuration with weights
            
        Returns:
            Dictionary with score, interpretation, and breakdown:
            {
                'score': float,  # Total weighted score (0.0 - 1.0+)
                'interpretation': str,  # Human-readable interpretation
                'breakdown': dict,  # Per-Feather breakdown
                'matched_feathers': int,  # Count of matched Feathers
                'total_feathers': int  # Total Feathers in Wing
            }
        """
        # Check if weighted scoring is enabled
        scoring_config = getattr(wing_config, 'scoring', {})
        if not scoring_config.get('enabled', False):
            # Fall back to simple count-based scoring
            return {
                'score': len(match_records),
                'interpretation': 'Match Count',
                'breakdown': {},
                'matched_feathers': len(match_records),
                'total_feathers': len(getattr(wing_config, 'feathers', []))
            }
        
        total_score = 0.0
        breakdown = {}
        
        # Calculate weighted score
        feathers = getattr(wing_config, 'feathers', [])
        for feather_spec in feathers:
            # Handle both dict and object formats
            if isinstance(feather_spec, dict):
                feather_id = feather_spec.get('feather_id', '')
                weight = feather_spec.get('weight', 0.0)
                tier = feather_spec.get('tier', 0)
                tier_name = feather_spec.get('tier_name', '')
            else:
                feather_id = getattr(feather_spec, 'feather_id', '')
                weight = getattr(feather_spec, 'weight', 0.0)
                tier = getattr(feather_spec, 'tier', 0)
                tier_name = getattr(feather_spec, 'tier_name', '')
            
            if feather_id in match_records:
                total_score += weight
                
                breakdown[feather_id] = {
                    'matched': True,
                    'weight': weight,
                    'contribution': weight,
                    'tier': tier,
                    'tier_name': tier_name
                }
            else:
                breakdown[feather_id] = {
                    'matched': False,
                    'weight': weight,
                    'contribution': 0.0,
                    'tier': tier,
                    'tier_name': tier_name
                }
        
        # Determine interpretation
        interpretation = self._interpret_score(
            total_score,
            scoring_config.get('score_interpretation', {})
        )
        
        return {
            'score': round(total_score, 2),
            'interpretation': interpretation,
            'breakdown': breakdown,
            'matched_feathers': len([b for b in breakdown.values() if b['matched']]),
            'total_feathers': len(breakdown)
        }
    
    def _interpret_score(self, score: float, 
                        interpretation_config: Dict) -> str:
        """
        Interpret score based on thresholds.
        
        Args:
            score: Calculated weighted score
            interpretation_config: Dictionary of interpretation levels with thresholds
            
        Returns:
            Human-readable interpretation label
        """
        if not interpretation_config:
            return "Unknown"
        
        # Sort by minimum threshold in descending order
        sorted_levels = sorted(
            interpretation_config.items(),
            key=lambda x: x[1].get('min', 0.0),
            reverse=True
        )
        
        # Find first level where score meets threshold
        for level, config in sorted_levels:
            if score >= config.get('min', 0.0):
                return config.get('label', level)
        
        return "Unknown"
