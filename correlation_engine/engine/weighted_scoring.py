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

        Score semantics (normalised in [0.0, 1.0]):
            score = (sum of weights of matched feathers) / (sum of all feather weights)

        Three correctness fixes vs. the legacy summed-weight model:

        1. **Silent-zero bug.** If every feather in the wing has weight=0.0
           (the FeatherSpec dataclass default — i.e. an unconfigured wing),
           the legacy code returned 0.0 even on full match coverage, which
           made every match look like "Insufficient Evidence." We now fall
           back to equal weighting (1/N per feather) so that unconfigured
           wings still produce a meaningful proportional score.

        2. **No normalisation.** The legacy code summed raw weights, so a
           wing with weights [1.0, 0.5, 0.5] could yield scores up to 2.0.
           Interpretation thresholds (0.70/0.40/0.20) were calibrated for
           the [0, 1] range, so they triggered "Confirmed" on any single
           heavy match. We now divide by total weight, giving a stable
           [0, 1] score regardless of the user's weight magnitudes.

        3. **Per-feather contribution.** The breakdown now reports each
           feather's NORMALISED contribution (its share of the total)
           rather than its raw weight, so the breakdown rows sum to the
           reported score. Tier numbers are still surfaced in the breakdown
           as metadata — they are intentionally NOT applied as a separate
           multiplier (the wing's `weight` is the single source of truth
           for scoring magnitude).
        """
        # Fast path: scoring disabled → count fallback.
        scoring_config = getattr(wing_config, 'scoring', {})
        if not scoring_config.get('enabled', False):
            return {
                'score': len(match_records),
                'interpretation': 'Match Count',
                'breakdown': {},
                'matched_feathers': len(match_records),
                'total_feathers': len(getattr(wing_config, 'feathers', []))
            }

        feathers = getattr(wing_config, 'feathers', [])
        n_feathers = len(feathers)
        if n_feathers == 0:
            return {
                'score': 0.0,
                'interpretation': self._interpret_score(
                    0.0, scoring_config.get('score_interpretation', {})
                ),
                'breakdown': {},
                'matched_feathers': 0,
                'total_feathers': 0,
                'weights_normalised': False,
                'used_equal_weight_fallback': False,
            }

        # ---- Step 1: read weights + tier metadata per feather ----
        def _read(spec, key, default):
            if isinstance(spec, dict):
                return spec.get(key, default)
            return getattr(spec, key, default)

        weights_raw = []
        for spec in feathers:
            try:
                w = float(_read(spec, 'weight', 0.0) or 0.0)
            except (TypeError, ValueError):
                w = 0.0
            if w < 0.0:
                w = 0.0 # negative weights would invert semantics — clamp.
            weights_raw.append(w)

        # ---- Step 2: silent-zero fix — equal weights if all are zero ----
        total_raw = sum(weights_raw)
        used_equal_weight = False
        if total_raw <= 0.0:
            # User didn't configure weights; treat every feather as equal.
            weights_effective = [1.0 / n_feathers] * n_feathers
            total_effective = 1.0
            used_equal_weight = True
        else:
            # ---- Step 3: normalisation fix — divide by total ----
            weights_effective = [w / total_raw for w in weights_raw]
            total_effective = 1.0 # by construction after normalisation

        # ---- Step 4: build breakdown + score in one pass ----
        total_score = 0.0
        breakdown: Dict[str, Dict[str, Any]] = {}
        matched_count = 0

        for spec, w_norm in zip(feathers, weights_effective):
            feather_id = _read(spec, 'feather_id', '') or ''
            tier = _read(spec, 'tier', 0) or 0
            tier_name = _read(spec, 'tier_name', '') or ''
            raw_weight = float(_read(spec, 'weight', 0.0) or 0.0)
            is_matched = feather_id in match_records

            contribution = w_norm if is_matched else 0.0
            if is_matched:
                total_score += contribution
                matched_count += 1

            breakdown[feather_id] = {
                'matched': is_matched,
                'weight': raw_weight, # what the user configured
                'weight_normalised': round(w_norm, 4), # share of total used in score
                'contribution': round(contribution, 4),
                'tier': tier,
                'tier_name': tier_name,
            }

        interpretation = self._interpret_score(
            total_score,
            scoring_config.get('score_interpretation', {})
        )

        return {
            'score': round(total_score, 4),
            'interpretation': interpretation,
            'breakdown': breakdown,
            'matched_feathers': matched_count,
            'total_feathers': n_feathers,
            'weights_normalised': True,
            'used_equal_weight_fallback': used_equal_weight,
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
        
        # Normalize interpretation config to handle both dict and flat float values
        normalized = {}
        for level, config in interpretation_config.items():
            if isinstance(config, dict):
                normalized[level] = config
            else:
                try:
                    normalized[level] = {'min': float(config), 'label': level.title()}
                except (TypeError, ValueError):
                    normalized[level] = {'min': 0.0, 'label': level.title()}

        # Sort by minimum threshold in descending order
        sorted_levels = sorted(
            normalized.items(),
            key=lambda x: x[1].get('min', 0.0),
            reverse=True
        )
        
        # Find first level where score meets threshold
        for level, config in sorted_levels:
            if score >= config.get('min', 0.0):
                return config.get('label', level)
        
        return "Unknown"
