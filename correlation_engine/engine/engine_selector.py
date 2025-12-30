"""
Engine Selector
Factory for creating correlation engine instances.

This module provides a factory pattern for creating correlation engines
based on configuration, allowing easy switching between different engines.
"""

from typing import Optional, List, Tuple
from .base_engine import BaseCorrelationEngine, FilterConfig


class EngineType:
    """Engine type constants"""
    TIME_BASED = "time_based"
    IDENTITY_BASED = "identity_based"


class EngineSelector:
    """
    Factory for selecting and creating correlation engines.
    
    This class provides methods to:
    1. Create engine instances based on type
    2. Get list of available engines with metadata
    
    Example:
        # Create engine
        engine = EngineSelector.create_engine(
            config=pipeline_config,
            engine_type=EngineType.TIME_BASED,
            filters=FilterConfig(time_period_start=start_date)
        )
        
        # Get available engines
        engines = EngineSelector.get_available_engines()
        for engine_type, name, desc, complexity, use_cases, supports_id_filter in engines:
            print(f"{name}: {desc}")
    """
    
    @staticmethod
    def create_engine(config: any, 
                     engine_type: str = EngineType.TIME_BASED,
                     filters: Optional[FilterConfig] = None) -> BaseCorrelationEngine:
        """
        Create correlation engine based on type.
        
        Args:
            config: Pipeline configuration object
            engine_type: Type of engine to create (TIME_BASED or IDENTITY_BASED)
            filters: Optional filter configuration
            
        Returns:
            Correlation engine instance
            
        Raises:
            ValueError: If engine type is unknown
            ImportError: If engine module cannot be imported
        """
        # Import engines here to avoid circular dependencies
        try:
            if engine_type == EngineType.TIME_BASED:
                from .time_based_engine import TimeBasedCorrelationEngine
                return TimeBasedCorrelationEngine(config, filters)
            
            elif engine_type == EngineType.IDENTITY_BASED:
                from .identity_correlation_engine import IdentityBasedEngineAdapter
                return IdentityBasedEngineAdapter(config, filters)
            
            else:
                raise ValueError(
                    f"Unknown engine type: '{engine_type}'. "
                    f"Valid types: {EngineType.TIME_BASED}, {EngineType.IDENTITY_BASED}"
                )
        
        except ImportError as e:
            raise ImportError(
                f"Failed to import engine '{engine_type}': {str(e)}. "
                f"Ensure the engine module exists and is properly configured."
            )
    
    @staticmethod
    def get_available_engines() -> List[Tuple[str, str, str, str, List[str], bool]]:
        """
        Get list of available engines with metadata.
        
        Returns:
            List of tuples containing:
                - engine_type: Engine type constant
                - name: Human-readable engine name
                - description: Brief description
                - complexity: Big-O complexity notation
                - use_cases: List of recommended use cases
                - supports_identity_filter: Whether engine supports identity filtering
        
        Example:
            engines = EngineSelector.get_available_engines()
            for engine_type, name, desc, complexity, use_cases, supports_id in engines:
                print(f"{name} ({complexity})")
                print(f"  {desc}")
                print(f"  Best for: {', '.join(use_cases)}")
                print(f"  Identity Filter: {'Yes' if supports_id else 'No'}")
        """
        return [
            (
                EngineType.TIME_BASED,
                "Time-Based Correlation",
                "Uses time proximity as primary factor with semantic field matching, "
                "weighted scoring, and duplicate prevention. Comprehensive analysis "
                "but may have duplicates with large datasets.",
                "O(N²)",
                [
                    "Small datasets (<1,000 records)",
                    "Research and debugging",
                    "Comprehensive analysis",
                    "Detailed field matching"
                ],
                False  # Does not support identity filtering
            ),
            (
                EngineType.IDENTITY_BASED,
                "Identity-Based Correlation",
                "Identity-first clustering with temporal anchors. Fast, clean results "
                "with identity tracking and relationship mapping. Optimized for "
                "performance with large datasets.",
                "O(N log N)",
                [
                    "Large datasets (>1,000 records)",
                    "Production environments",
                    "Identity tracking",
                    "Performance-critical analysis",
                    "Relationship mapping"
                ],
                True  # Supports identity filtering
            )
        ]
    
    @staticmethod
    def get_engine_metadata(engine_type: str) -> Optional[Tuple[str, str, str, str, List[str], bool]]:
        """
        Get metadata for a specific engine type.
        
        Args:
            engine_type: Engine type constant
            
        Returns:
            Tuple of engine metadata or None if not found
        """
        for metadata in EngineSelector.get_available_engines():
            if metadata[0] == engine_type:
                return metadata
        return None
    
    @staticmethod
    def validate_engine_type(engine_type: str) -> bool:
        """
        Validate that an engine type is supported.
        
        Args:
            engine_type: Engine type to validate
            
        Returns:
            True if engine type is valid, False otherwise
        """
        valid_types = [EngineType.TIME_BASED, EngineType.IDENTITY_BASED]
        return engine_type in valid_types
