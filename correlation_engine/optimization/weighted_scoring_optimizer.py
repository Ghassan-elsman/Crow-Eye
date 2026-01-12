"""
Weighted Scoring Performance Optimizer

Provides performance optimizations for weighted scoring calculations including:
- Score calculation caching
- Batch processing for multiple matches
- Configuration optimization
- Memory-efficient score storage
"""

import logging
import time
import threading
from collections import OrderedDict, defaultdict
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from functools import lru_cache
import hashlib

from ..engine.weighted_scoring import WeightedScoringEngine

logger = logging.getLogger(__name__)


@dataclass
class WeightedScoringPerformanceMetrics:
    """Performance metrics for weighted scoring operations"""
    total_calculations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    batch_operations: int = 0
    config_optimizations: int = 0
    average_calculation_time_ms: float = 0.0
    total_processing_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    
    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate percentage"""
        if self.total_calculations == 0:
            return 0.0
        return (self.cache_hits / self.total_calculations) * 100.0


@dataclass
class OptimizedWingConfig:
    """Optimized wing configuration for faster scoring calculations"""
    feathers: List[Dict[str, Any]]
    total_weight: float
    weight_lookup: Dict[str, float]
    tier_lookup: Dict[str, int]
    enabled_feathers: List[str]
    config_hash: str
    
    @classmethod
    def from_wing_config(cls, wing_config: Any) -> 'OptimizedWingConfig':
        """Create optimized config from original wing config"""
        feathers = getattr(wing_config, 'feathers', [])
        
        # Convert to standardized format
        standardized_feathers = []
        weight_lookup = {}
        tier_lookup = {}
        enabled_feathers = []
        total_weight = 0.0
        
        for feather_spec in feathers:
            if isinstance(feather_spec, dict):
                feather_id = feather_spec.get('feather_id', '')
                weight = feather_spec.get('weight', 0.0)
                tier = feather_spec.get('tier', 1)
                tier_name = feather_spec.get('tier_name', '')
            else:
                feather_id = getattr(feather_spec, 'feather_id', '')
                weight = getattr(feather_spec, 'weight', 0.0)
                tier = getattr(feather_spec, 'tier', 1)
                tier_name = getattr(feather_spec, 'tier_name', '')
            
            if feather_id:
                feather_dict = {
                    'feather_id': feather_id,
                    'weight': weight,
                    'tier': tier,
                    'tier_name': tier_name
                }
                
                standardized_feathers.append(feather_dict)
                weight_lookup[feather_id] = weight
                tier_lookup[feather_id] = tier
                
                if weight > 0:
                    enabled_feathers.append(feather_id)
                    total_weight += weight
        
        # Create hash for caching
        config_str = str(sorted(weight_lookup.items())) + str(sorted(tier_lookup.items()))
        config_hash = hashlib.md5(config_str.encode()).hexdigest()
        
        return cls(
            feathers=standardized_feathers,
            total_weight=total_weight,
            weight_lookup=weight_lookup,
            tier_lookup=tier_lookup,
            enabled_feathers=enabled_feathers,
            config_hash=config_hash
        )


class OptimizedWeightedScoringEngine:
    """
    Performance-optimized weighted scoring engine with advanced caching and batch processing.
    
    Key optimizations:
    - Score calculation caching based on match patterns
    - Batch processing for multiple matches
    - Optimized configuration preprocessing
    - Memory-efficient score storage
    - Fast lookup tables for weights and tiers
    """
    
    def __init__(self, cache_size: int = 5000, enable_batch_processing: bool = True):
        """
        Initialize optimized weighted scoring engine.
        
        Args:
            cache_size: Size of score calculation cache
            enable_batch_processing: Enable batch processing optimizations
        """
        self.base_engine = WeightedScoringEngine()
        self.cache_size = cache_size
        self.enable_batch_processing = enable_batch_processing
        
        # Performance optimization structures
        self._score_cache: OrderedDict = OrderedDict()
        self._config_cache: Dict[str, OptimizedWingConfig] = {}
        self._interpretation_cache: Dict[Tuple[float, str], Dict[str, Any]] = {}
        
        # Performance metrics
        self.metrics = WeightedScoringPerformanceMetrics()
        
        # Thread safety
        self._cache_lock = threading.RLock()
        
        logger.info(f"OptimizedWeightedScoringEngine initialized with cache_size={cache_size}, "
                   f"batch_processing={enable_batch_processing}")
    
    def calculate_match_score_optimized(self, 
                                      match_records: Dict[str, Dict],
                                      wing_config: Any,
                                      use_cache: bool = True) -> Dict[str, Any]:
        """
        Optimized match score calculation with caching and preprocessing.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing_config: Wing configuration with weights
            use_cache: Whether to use caching
            
        Returns:
            Dictionary with score, interpretation, and breakdown
        """
        start_time = time.time()
        self.metrics.total_calculations += 1
        
        # Create cache key based on matched feathers and config
        if use_cache:
            cache_key = self._create_cache_key(match_records, wing_config)
            
            with self._cache_lock:
                if cache_key in self._score_cache:
                    # Move to end (LRU)
                    result = self._score_cache.pop(cache_key)
                    self._score_cache[cache_key] = result
                    self.metrics.cache_hits += 1
                    
                    calculation_time = (time.time() - start_time) * 1000
                    self._update_average_calculation_time(calculation_time)
                    
                    return result
                
                self.metrics.cache_misses += 1
        
        # Get or create optimized config
        optimized_config = self._get_optimized_config(wing_config)
        
        # Check if weighted scoring is enabled
        scoring_config = getattr(wing_config, 'scoring', {})
        if not scoring_config.get('enabled', False):
            result = self._calculate_simple_score_optimized(match_records, optimized_config)
        else:
            result = self._calculate_weighted_score_optimized(match_records, optimized_config, scoring_config)
        
        # Cache the result
        if use_cache:
            with self._cache_lock:
                self._score_cache[cache_key] = result
                
                # Maintain cache size limit
                if len(self._score_cache) > self.cache_size:
                    self._score_cache.popitem(last=False)
        
        calculation_time = (time.time() - start_time) * 1000
        self._update_average_calculation_time(calculation_time)
        self.metrics.total_processing_time_ms += calculation_time
        
        return result
    
    def calculate_batch_scores(self, 
                             matches: List[Tuple[str, Dict[str, Dict]]], 
                             wing_config: Any) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Calculate scores for multiple matches in batch for better performance.
        
        Args:
            matches: List of (match_id, match_records) tuples
            wing_config: Wing configuration with weights
            
        Returns:
            List of (match_id, score_result) tuples
        """
        if not self.enable_batch_processing or len(matches) <= 1:
            # Fall back to individual calculations
            return [(match_id, self.calculate_match_score_optimized(match_records, wing_config))
                   for match_id, match_records in matches]
        
        start_time = time.time()
        results = []
        
        # Get optimized config once for all matches
        optimized_config = self._get_optimized_config(wing_config)
        
        # Group matches by pattern for better cache utilization
        pattern_groups = defaultdict(list)
        for match_id, match_records in matches:
            pattern = frozenset(match_records.keys())
            pattern_groups[pattern].append((match_id, match_records))
        
        # Process each pattern group
        for pattern, pattern_matches in pattern_groups.items():
            # Calculate score for first match in pattern
            first_match_id, first_match_records = pattern_matches[0]
            first_result = self.calculate_match_score_optimized(first_match_records, wing_config)
            results.append((first_match_id, first_result))
            
            # For remaining matches with same pattern, reuse calculation structure
            if len(pattern_matches) > 1:
                for match_id, match_records in pattern_matches[1:]:
                    # Quick calculation since pattern is the same
                    result = self._calculate_score_with_pattern_reuse(
                        match_records, optimized_config, first_result
                    )
                    results.append((match_id, result))
        
        self.metrics.batch_operations += 1
        batch_time = (time.time() - start_time) * 1000
        self.metrics.total_processing_time_ms += batch_time
        
        logger.debug(f"Batch calculated {len(matches)} scores in {batch_time:.2f}ms "
                    f"({len(pattern_groups)} unique patterns)")
        
        return results
    
    def _create_cache_key(self, match_records: Dict[str, Dict], wing_config: Any) -> str:
        """
        Create cache key for score calculation.
        
        Args:
            match_records: Dictionary of feather_id -> record
            wing_config: Wing configuration
            
        Returns:
            Cache key string
        """
        # Create key based on matched feathers and config hash
        matched_feathers = sorted(match_records.keys())
        optimized_config = self._get_optimized_config(wing_config)
        
        key_parts = [
            'matched:' + '|'.join(matched_feathers),
            'config:' + optimized_config.config_hash
        ]
        
        return '||'.join(key_parts)
    
    def _get_optimized_config(self, wing_config: Any) -> OptimizedWingConfig:
        """
        Get or create optimized wing configuration.
        
        Args:
            wing_config: Original wing configuration
            
        Returns:
            OptimizedWingConfig instance
        """
        # Create a simple hash of the config for caching
        config_id = str(id(wing_config))
        
        if config_id not in self._config_cache:
            optimized_config = OptimizedWingConfig.from_wing_config(wing_config)
            self._config_cache[config_id] = optimized_config
            self.metrics.config_optimizations += 1
        
        return self._config_cache[config_id]
    
    def _calculate_weighted_score_optimized(self, 
                                          match_records: Dict[str, Dict],
                                          optimized_config: OptimizedWingConfig,
                                          scoring_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Optimized weighted score calculation using preprocessed configuration.
        
        Args:
            match_records: Dictionary of feather_id -> record
            optimized_config: Optimized wing configuration
            scoring_config: Scoring configuration
            
        Returns:
            Dictionary with score, interpretation, and breakdown
        """
        total_score = 0.0
        breakdown = {}
        
        # Use optimized lookups instead of iterating through all feathers
        for feather_dict in optimized_config.feathers:
            feather_id = feather_dict['feather_id']
            weight = feather_dict['weight']
            tier = feather_dict['tier']
            tier_name = feather_dict['tier_name']
            
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
        
        # Determine interpretation using cached interpretation
        interpretation = self._interpret_score_cached(
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
    
    def _calculate_simple_score_optimized(self, 
                                        match_records: Dict[str, Dict],
                                        optimized_config: OptimizedWingConfig) -> Dict[str, Any]:
        """
        Optimized simple count-based score calculation.
        
        Args:
            match_records: Dictionary of feather_id -> record
            optimized_config: Optimized wing configuration
            
        Returns:
            Dictionary with simple score information
        """
        matched_feathers = len(match_records)
        total_feathers = len(optimized_config.feathers)
        
        # Use optimized breakdown generation
        breakdown = {}
        for feather_dict in optimized_config.feathers:
            feather_id = feather_dict['feather_id']
            breakdown[feather_id] = {
                'matched': feather_id in match_records,
                'weight': 1.0,
                'contribution': 1.0 if feather_id in match_records else 0.0,
                'tier': feather_dict['tier'],
                'tier_name': feather_dict['tier_name']
            }
        
        return {
            'score': matched_feathers,
            'interpretation': f'{matched_feathers}/{total_feathers} Matches',
            'breakdown': breakdown,
            'matched_feathers': matched_feathers,
            'total_feathers': total_feathers,
            'scoring_mode': 'simple_count'
        }
    
    def _calculate_score_with_pattern_reuse(self, 
                                          match_records: Dict[str, Dict],
                                          optimized_config: OptimizedWingConfig,
                                          template_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate score by reusing the structure from a template result.
        
        Args:
            match_records: Dictionary of feather_id -> record
            optimized_config: Optimized wing configuration
            template_result: Template result to reuse structure from
            
        Returns:
            Dictionary with score, interpretation, and breakdown
        """
        # Since the pattern is the same, we can reuse most of the calculation
        # Only need to verify the matched feathers are the same
        template_breakdown = template_result.get('breakdown', {})
        
        # Quick verification that the pattern matches
        matched_feathers_template = {fid for fid, details in template_breakdown.items() if details.get('matched', False)}
        matched_feathers_current = set(match_records.keys())
        
        if matched_feathers_template == matched_feathers_current:
            # Pattern matches exactly, can reuse the result
            return template_result.copy()
        else:
            # Pattern doesn't match exactly, fall back to full calculation
            return self._calculate_weighted_score_optimized(
                match_records, optimized_config, {'enabled': True}
            )
    
    @lru_cache(maxsize=1000)
    def _interpret_score_cached(self, score: float, interpretation_config_str: str) -> str:
        """
        Cached version of score interpretation.
        
        Args:
            score: Score to interpret
            interpretation_config_str: String representation of interpretation config
            
        Returns:
            Interpretation string
        """
        # Convert string back to dict (this is a simplified approach)
        # In practice, you might want to use a more sophisticated caching strategy
        try:
            import ast
            interpretation_config = ast.literal_eval(interpretation_config_str)
        except:
            interpretation_config = {}
        
        return self.base_engine._interpret_score(score, interpretation_config)
    
    def _update_average_calculation_time(self, calculation_time_ms: float):
        """Update average calculation time metric"""
        if self.metrics.total_calculations == 1:
            self.metrics.average_calculation_time_ms = calculation_time_ms
        else:
            # Running average
            self.metrics.average_calculation_time_ms = (
                (self.metrics.average_calculation_time_ms * (self.metrics.total_calculations - 1) + calculation_time_ms) /
                self.metrics.total_calculations
            )
    
    def preoptimize_configurations(self, wing_configs: List[Any]):
        """
        Preoptimize multiple wing configurations for better performance.
        
        Args:
            wing_configs: List of wing configurations to optimize
        """
        start_time = time.time()
        optimized_count = 0
        
        for wing_config in wing_configs:
            config_id = str(id(wing_config))
            if config_id not in self._config_cache:
                optimized_config = OptimizedWingConfig.from_wing_config(wing_config)
                self._config_cache[config_id] = optimized_config
                optimized_count += 1
        
        optimization_time = (time.time() - start_time) * 1000
        logger.info(f"Preoptimized {optimized_count} wing configurations in {optimization_time:.2f}ms")
    
    def clear_caches(self):
        """Clear all caches to free memory"""
        with self._cache_lock:
            self._score_cache.clear()
            self._config_cache.clear()
            self._interpretation_cache.clear()
        
        # Clear LRU cache
        self._interpret_score_cached.cache_clear()
        
        logger.info("Weighted scoring caches cleared")
    
    def get_performance_metrics(self) -> WeightedScoringPerformanceMetrics:
        """Get current performance metrics"""
        return self.metrics
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get detailed cache statistics"""
        with self._cache_lock:
            return {
                'score_cache_size': len(self._score_cache),
                'score_cache_limit': self.cache_size,
                'config_cache_size': len(self._config_cache),
                'interpretation_cache_size': len(self._interpretation_cache),
                'cache_hit_rate': self.metrics.cache_hit_rate,
                'total_calculations': self.metrics.total_calculations,
                'cache_hits': self.metrics.cache_hits,
                'cache_misses': self.metrics.cache_misses,
                'batch_operations': self.metrics.batch_operations,
                'config_optimizations': self.metrics.config_optimizations
            }
    
    def optimize_for_workload(self, sample_matches: List[Tuple[str, Dict[str, Dict]]], 
                            wing_config: Any):
        """
        Optimize the engine for a specific workload by analyzing match patterns.
        
        Args:
            sample_matches: Sample matches to analyze
            wing_config: Wing configuration
        """
        start_time = time.time()
        
        # Analyze match patterns
        pattern_frequency = defaultdict(int)
        feather_frequency = defaultdict(int)
        
        for match_id, match_records in sample_matches:
            pattern = frozenset(match_records.keys())
            pattern_frequency[pattern] += 1
            
            for feather_id in match_records.keys():
                feather_frequency[feather_id] += 1
        
        # Preoptimize configuration
        self._get_optimized_config(wing_config)
        
        # Pre-calculate scores for common patterns
        common_patterns = sorted(pattern_frequency.items(), key=lambda x: x[1], reverse=True)[:10]
        
        for pattern, frequency in common_patterns:
            # Create sample match records for this pattern
            sample_match_records = {feather_id: {} for feather_id in pattern}
            
            # Pre-calculate and cache the score
            self.calculate_match_score_optimized(sample_match_records, wing_config)
        
        optimization_time = (time.time() - start_time) * 1000
        logger.info(f"Workload optimization completed in {optimization_time:.2f}ms. "
                   f"Analyzed {len(sample_matches)} matches with {len(pattern_frequency)} unique patterns")
    
    def get_optimization_report(self) -> Dict[str, Any]:
        """
        Get a detailed optimization report.
        
        Returns:
            Dictionary with optimization information
        """
        cache_stats = self.get_cache_statistics()
        
        return {
            'performance_metrics': {
                'total_calculations': self.metrics.total_calculations,
                'average_calculation_time_ms': self.metrics.average_calculation_time_ms,
                'total_processing_time_ms': self.metrics.total_processing_time_ms,
                'cache_hit_rate': self.metrics.cache_hit_rate
            },
            'cache_utilization': cache_stats,
            'optimization_features': {
                'score_caching': True,
                'config_preprocessing': True,
                'batch_processing': self.enable_batch_processing,
                'pattern_reuse': True
            },
            'recommendations': self._generate_optimization_recommendations()
        }
    
    def _generate_optimization_recommendations(self) -> List[str]:
        """Generate optimization recommendations based on current metrics"""
        recommendations = []
        
        if self.metrics.cache_hit_rate < 50.0 and self.metrics.total_calculations > 100:
            recommendations.append("Consider increasing cache size - low cache hit rate detected")
        
        if self.metrics.average_calculation_time_ms > 10.0:
            recommendations.append("Consider enabling batch processing for better performance")
        
        if len(self._config_cache) > 50:
            recommendations.append("Many wing configurations detected - consider config consolidation")
        
        if not recommendations:
            recommendations.append("Performance is optimal for current workload")
        
        return recommendations