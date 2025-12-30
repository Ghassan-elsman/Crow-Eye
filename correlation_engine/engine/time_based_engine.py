"""
Time-Based Correlation Engine Adapter
Adapts the existing CorrelationEngine to the BaseCorrelationEngine interface.

This module provides a wrapper around the existing CorrelationEngine that:
1. Inherits from BaseCorrelationEngine
2. Supports FilterConfig for time period filtering
3. Maintains backward compatibility with existing code
"""

from typing import List, Dict, Any, Optional
from .base_engine import BaseCorrelationEngine, EngineMetadata, FilterConfig
from .correlation_engine import CorrelationEngine
from ..wings.core.wing_model import Wing


class TimeBasedCorrelationEngine(BaseCorrelationEngine):
    """
    Time-Based Correlation Engine.
    
    This engine uses time proximity as the primary correlation factor, enhanced with:
    - Semantic field matching (application names, file paths)
    - Weighted scoring based on artifact types
    - Enhanced composite scoring (coverage + time proximity + field similarity)
    - Duplicate prevention using MatchSet
    - Confidence scoring based on time tightness and field consistency
    
    Complexity: O(N²) where N is the number of anchor records
    
    Best for:
    - Small to medium datasets (<1,000 records)
    - Research and debugging
    - Comprehensive analysis requiring detailed field matching
    
    Example:
        engine = TimeBasedCorrelationEngine(
            config=pipeline_config,
            filters=FilterConfig(
                time_period_start=datetime(2024, 1, 1),
                time_period_end=datetime(2024, 12, 31)
            )
        )
        result = engine.execute([wing])
    """
    
    def __init__(self, config: Any, filters: Optional[FilterConfig] = None, debug_mode: bool = True):
        """
        Initialize Time-Based Correlation Engine.
        
        Args:
            config: Pipeline configuration object
            filters: Optional filter configuration
            debug_mode: Enable debug logging
        """
        super().__init__(config, filters)
        
        # Create internal correlation engine instance
        self.engine = CorrelationEngine(debug_mode=debug_mode)
        self.debug_mode = debug_mode
        
        # Store last execution result
        self.last_result = None
        
        # Progress listener (for GUI updates)
        self.progress_listener = None
    
    def register_progress_listener(self, listener):
        """
        Register a progress listener for GUI updates.
        
        Args:
            listener: Callable that receives progress events
        """
        self.progress_listener = listener
        # Pass through to internal engine if it supports it
        if hasattr(self.engine, 'register_progress_listener'):
            self.engine.register_progress_listener(listener)
    
    @property
    def metadata(self) -> EngineMetadata:
        """Get engine metadata"""
        return EngineMetadata(
            name="Time-Based Correlation",
            version="2.0.0",
            description="Time proximity with semantic matching and weighted scoring",
            complexity="O(N²)",
            best_for=[
                "Small datasets (<1,000 records)",
                "Research and debugging",
                "Comprehensive analysis",
                "Detailed field matching"
            ],
            supports_identity_filter=False
        )
    
    def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
        """
        Execute correlation with time period filtering.
        
        Args:
            wing_configs: List of Wing configuration objects (typically one wing)
            
        Returns:
            Dictionary containing:
                - 'result': CorrelationResult object
                - 'engine_type': 'time_based'
                - 'filters_applied': Dictionary of applied filters
        """
        if not wing_configs:
            raise ValueError("No wing configurations provided")
        
        wing = wing_configs[0]  # Typically one wing per execution
        
        # Get feather paths from wing
        feather_paths = self._extract_feather_paths(wing)
        
        # Apply time period filter if configured
        if self.filters.time_period_start or self.filters.time_period_end:
            if self.debug_mode:
                print(f"[Time-Based Engine] Applying time period filter:")
                if self.filters.time_period_start:
                    print(f"  Start: {self.filters.time_period_start}")
                if self.filters.time_period_end:
                    print(f"  End: {self.filters.time_period_end}")
            
            # Filter will be applied during record loading in _apply_filters
            # We pass the filter info to the engine
            self.engine.time_period_filter = self.filters
        
        # Execute correlation using existing engine
        result = self.engine.execute_wing(wing, feather_paths)
        
        # Store result
        self.last_result = result
        
        # Return standardized format
        return {
            'result': result,
            'engine_type': 'time_based',
            'filters_applied': {
                'time_period_start': self.filters.time_period_start.isoformat() if self.filters.time_period_start else None,
                'time_period_end': self.filters.time_period_end.isoformat() if self.filters.time_period_end else None
            }
        }
    
    def execute_wing(self, wing: Any, feather_paths: Dict[str, str]) -> Any:
        """
        Execute correlation for a single wing (backward compatibility method).
        
        This method provides backward compatibility with code that calls execute_wing directly.
        It delegates to the internal CorrelationEngine's execute_wing method.
        
        Args:
            wing: Wing configuration object
            feather_paths: Dictionary mapping feather_id to database path
            
        Returns:
            CorrelationResult object
        """
        # Apply time period filter if configured
        if self.filters.time_period_start or self.filters.time_period_end:
            if self.debug_mode:
                print(f"[Time-Based Engine] Applying time period filter:")
                if self.filters.time_period_start:
                    print(f"  Start: {self.filters.time_period_start}")
                if self.filters.time_period_end:
                    print(f"  End: {self.filters.time_period_end}")
            
            # Pass filter info to internal engine
            self.engine.time_period_filter = self.filters
        
        # Execute using internal engine
        result = self.engine.execute_wing(wing, feather_paths)
        
        # Store result
        self.last_result = result
        
        return result
    
    def get_results(self) -> Any:
        """
        Get correlation results from last execution.
        
        Returns:
            CorrelationResult object or None if no execution yet
        """
        return self.last_result
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get correlation statistics from last execution.
        
        Returns:
            Dictionary containing statistics
        """
        if not self.last_result:
            return {}
        
        return {
            'execution_time': self.last_result.execution_duration_seconds,
            'record_count': self.last_result.total_records_scanned,
            'match_count': self.last_result.total_matches,
            'duplicate_rate': (self.last_result.duplicates_prevented / self.last_result.total_matches * 100) 
                             if self.last_result.total_matches > 0 else 0,
            'duplicates_prevented': self.last_result.duplicates_prevented,
            'feathers_processed': self.last_result.feathers_processed,
            'matches_failed_validation': getattr(self.last_result, 'matches_failed_validation', 0)
        }
    
    def _extract_feather_paths(self, wing: Wing) -> Dict[str, str]:
        """
        Extract feather paths from wing configuration.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            Dictionary mapping feather_id to database path
        """
        feather_paths = {}
        
        for feather_spec in wing.feathers:
            # Get database path from feather spec
            if hasattr(feather_spec, 'database_path') and feather_spec.database_path:
                feather_paths[feather_spec.feather_id] = feather_spec.database_path
            elif hasattr(feather_spec, 'feather_path') and feather_spec.feather_path:
                feather_paths[feather_spec.feather_id] = feather_spec.feather_path
        
        return feather_paths


# Backward compatibility: Keep CorrelationEngine as alias
# This allows existing code to continue working without changes
TimeOnlyCorrelationEngine = TimeBasedCorrelationEngine
