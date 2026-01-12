"""
Engine Selector
Factory for creating correlation engine instances with integrated features.

This module provides a factory pattern for creating correlation engines
based on configuration, allowing easy switching between different engines
with semantic mapping, weighted scoring, and progress tracking integration.
"""

from typing import Optional, List, Tuple, Dict, Any
from .base_engine import BaseCorrelationEngine, FilterConfig


class EngineType:
    """Engine type constants"""
    TIME_WINDOW_SCANNING = "time_window_scanning"  # New O(N) time-window scanning engine
    IDENTITY_BASED = "identity_based"


class EngineSelector:
    """
    Factory for selecting and creating correlation engines with integrated features.
    
    This class provides methods to:
    1. Create engine instances based on type with semantic mapping and scoring integration
    2. Get list of available engines with metadata including integration capabilities
    3. Configure engines with semantic mapping and weighted scoring
    
    Example:
        # Create engine with integrations
        engine = EngineSelector.create_integrated_engine(
            config=pipeline_config,
            engine_type=EngineType.TIME_WINDOW_SCANNING,
            filters=FilterConfig(time_period_start=start_date),
            semantic_config=semantic_config,
            scoring_config=scoring_config
        )
        
        # Get available engines with integration capabilities
        engines = EngineSelector.get_available_engines()
        for engine_info in engines:
            engine_type, name, desc, complexity, use_cases, supports_id_filter, integration_features = engine_info
            print(f"{name}: {desc}")
            print(f"Integration features: {integration_features}")
    """
    
    @staticmethod
    def create_engine(config: any, 
                     engine_type: str = EngineType.TIME_WINDOW_SCANNING,
                     filters: Optional[FilterConfig] = None) -> BaseCorrelationEngine:
        """
        Create correlation engine based on type (legacy method for backward compatibility).
        
        Args:
            config: Pipeline configuration object
            engine_type: Type of engine to create (TIME_WINDOW_SCANNING or IDENTITY_BASED)
            filters: Optional filter configuration
            
        Returns:
            Correlation engine instance
            
        Raises:
            ValueError: If engine type is unknown
            ImportError: If engine module cannot be imported
        """
        return EngineSelector.create_integrated_engine(config, engine_type, filters)
    
    @staticmethod
    def create_integrated_engine(config: any, 
                               engine_type: str = EngineType.IDENTITY_BASED,
                               filters: Optional[FilterConfig] = None,
                               semantic_config: Optional[Dict[str, Any]] = None,
                               scoring_config: Optional[Dict[str, Any]] = None,
                               progress_config: Optional[Dict[str, Any]] = None,
                               case_id: Optional[str] = None) -> BaseCorrelationEngine:
        """
        Create correlation engine with integrated features.
        
        Args:
            config: Pipeline configuration object
            engine_type: Type of engine to create (TIME_WINDOW_SCANNING or IDENTITY_BASED)
            filters: Optional filter configuration
            semantic_config: Optional semantic mapping configuration
            scoring_config: Optional weighted scoring configuration
            progress_config: Optional progress tracking configuration
            case_id: Optional case ID for case-specific configurations
            
        Returns:
            Correlation engine instance with integrations enabled
            
        Raises:
            ValueError: If engine type is unknown
            ImportError: If engine module cannot be imported
        """
        # Import engines here to avoid circular dependencies
        try:
            if engine_type == EngineType.TIME_WINDOW_SCANNING:
                from .time_based_engine import TimeWindowScanningEngine
                engine = TimeWindowScanningEngine(config, filters)
            
            elif engine_type == EngineType.IDENTITY_BASED:
                from .identity_based_engine_adapter import IdentityBasedEngineAdapter
                engine = IdentityBasedEngineAdapter(config, filters)
            
            else:
                raise ValueError(
                    f"Unknown engine type: '{engine_type}'. "
                    f"Valid types: {EngineType.TIME_WINDOW_SCANNING}, {EngineType.IDENTITY_BASED}"
                )
            
            # Apply integrations if configurations are provided
            EngineSelector._apply_integrations(
                engine, semantic_config, scoring_config, progress_config, case_id
            )
            
            return engine
        
        except ImportError as e:
            raise ImportError(
                f"Failed to import engine '{engine_type}': {str(e)}. "
                f"Ensure the engine module exists and is properly configured."
            )
    
    @staticmethod
    def _apply_integrations(engine: BaseCorrelationEngine,
                          semantic_config: Optional[Dict[str, Any]] = None,
                          scoring_config: Optional[Dict[str, Any]] = None,
                          progress_config: Optional[Dict[str, Any]] = None,
                          case_id: Optional[str] = None):
        """
        Apply integration configurations to an engine.
        
        Args:
            engine: Engine instance to configure
            semantic_config: Semantic mapping configuration
            scoring_config: Weighted scoring configuration
            progress_config: Progress tracking configuration
            case_id: Case ID for case-specific configurations
        """
        try:
            # Apply semantic mapping integration
            if semantic_config and semantic_config.get('enabled', True):
                from ..integration.semantic_mapping_integration import SemanticMappingIntegration
                
                semantic_integration = SemanticMappingIntegration()
                if case_id:
                    semantic_integration.load_case_specific_mappings(case_id)
                
                # Set semantic integration on engine if it supports it
                if hasattr(engine, 'set_semantic_integration'):
                    engine.set_semantic_integration(semantic_integration)
                elif hasattr(engine, 'semantic_integration'):
                    engine.semantic_integration = semantic_integration
            
            # Apply weighted scoring integration
            if scoring_config and scoring_config.get('enabled', True):
                from ..integration.weighted_scoring_integration import WeightedScoringIntegration
                
                scoring_integration = WeightedScoringIntegration()
                if case_id:
                    scoring_integration.load_case_specific_scoring_weights(case_id)
                
                # Set scoring integration on engine if it supports it
                if hasattr(engine, 'set_scoring_integration'):
                    engine.set_scoring_integration(scoring_integration)
                elif hasattr(engine, 'scoring_integration'):
                    engine.scoring_integration = scoring_integration
            
            # Apply progress tracking integration
            if progress_config and progress_config.get('enabled', True):
                from ..integration.progress_tracking_integration import ProgressTrackingIntegration
                
                progress_integration = ProgressTrackingIntegration()
                
                # Set progress integration on engine if it supports it
                if hasattr(engine, 'set_progress_integration'):
                    engine.set_progress_integration(progress_integration)
                elif hasattr(engine, 'progress_integration'):
                    engine.progress_integration = progress_integration
            
        except Exception as e:
            # Log warning but don't fail engine creation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to apply integrations to engine: {e}")
    
    @staticmethod
    def get_integration_capabilities(engine_type: str) -> Dict[str, Any]:
        """
        Get integration capabilities for a specific engine type.
        
        Args:
            engine_type: Engine type constant
            
        Returns:
            Dictionary with integration capability information
        """
        capabilities = {
            'semantic_mapping': {
                'supported': True,
                'description': 'Maps technical field values to human-readable meanings',
                'features': ['Pattern matching', 'Hierarchical mappings', 'Case-specific overrides']
            },
            'weighted_scoring': {
                'supported': True,
                'description': 'Calculates confidence scores based on artifact weights',
                'features': ['Configurable weights', 'Score interpretation', 'Tier-based scoring']
            },
            'progress_tracking': {
                'supported': True,
                'description': 'Real-time progress monitoring with detailed statistics',
                'features': ['Time estimation', 'Memory monitoring', 'Event-based updates']
            },
            'case_specific_config': {
                'supported': True,
                'description': 'Case-specific configuration overrides',
                'features': ['Custom semantic mappings', 'Custom scoring weights', 'Configuration inheritance']
            }
        }
        
        # Engine-specific capabilities
        if engine_type == EngineType.TIME_WINDOW_SCANNING:
            capabilities['time_window_analysis'] = {
                'supported': True,
                'description': 'Systematic temporal analysis with configurable windows',
                'features': ['Configurable window sizes', 'Timestamp format flexibility', 'Memory-efficient processing']
            }
        elif engine_type == EngineType.IDENTITY_BASED:
            capabilities['identity_tracking'] = {
                'supported': True,
                'description': 'Identity-first clustering with relationship mapping',
                'features': ['Identity filtering', 'Relationship tracking', 'Identity-based grouping']
            }
        
        return capabilities
    
    @staticmethod
    def get_available_engines() -> List[Tuple[str, str, str, str, List[str], bool, Dict[str, Any]]]:
        """
        Get list of available engines with metadata including integration features.
        
        Returns:
            List of tuples containing:
                - engine_type: Engine type constant
                - name: Human-readable engine name
                - description: Brief description
                - complexity: Big-O complexity notation
                - use_cases: List of recommended use cases
                - supports_identity_filter: Whether engine supports identity filtering
                - integration_features: Dictionary of integration capabilities
        
        Example:
            engines = EngineSelector.get_available_engines()
            for engine_type, name, desc, complexity, use_cases, supports_id, features in engines:
                print(f"{name} ({complexity})")
                print(f"  {desc}")
                print(f"  Best for: {', '.join(use_cases)}")
                print(f"  Identity Filter: {'Yes' if supports_id else 'No'}")
                print(f"  Integration Features: {list(features.keys())}")
        """
        engines = []
        
        # Time-Window Scanning Engine
        time_window_features = EngineSelector.get_integration_capabilities(EngineType.TIME_WINDOW_SCANNING)
        engines.append((
            EngineType.TIME_WINDOW_SCANNING,
            "Time Engine",
            "O(N) time-window scanning correlation with systematic temporal analysis. "
            "Uses wing's time window size, handles any timestamp format, and provides "
            "excellent performance for large datasets.",
            "O(N)",
            [
                "Large datasets (>1,000 records)",
                "Performance-critical environments", 
                "Systematic temporal analysis",
                "Memory-constrained systems",
                "Any timestamp format support"
            ],
            False,  # Does not support identity filtering
            time_window_features
        ))
        
        # Identity-Based Engine
        identity_features = EngineSelector.get_integration_capabilities(EngineType.IDENTITY_BASED)
        engines.append((
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
            True,  # Supports identity filtering
            identity_features
        ))
        
        return engines
    
    @staticmethod
    def get_engine_metadata(engine_type: str) -> Optional[Tuple[str, str, str, str, List[str], bool, Dict[str, Any]]]:
        """
        Get metadata for a specific engine type including integration features.
        
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
    def get_engine_comparison_data() -> Dict[str, Any]:
        """
        Get comprehensive comparison data for all engines.
        
        Returns:
            Dictionary with engine comparison information
        """
        engines = EngineSelector.get_available_engines()
        
        comparison_data = {
            'engines': [],
            'feature_matrix': {},
            'performance_comparison': {},
            'use_case_recommendations': {}
        }
        
        for engine_type, name, desc, complexity, use_cases, supports_id_filter, integration_features in engines:
            engine_info = {
                'type': engine_type,
                'name': name,
                'description': desc,
                'complexity': complexity,
                'use_cases': use_cases,
                'supports_identity_filter': supports_id_filter,
                'integration_features': integration_features
            }
            
            comparison_data['engines'].append(engine_info)
            
            # Build feature matrix
            for feature_name, feature_info in integration_features.items():
                if feature_name not in comparison_data['feature_matrix']:
                    comparison_data['feature_matrix'][feature_name] = {}
                
                comparison_data['feature_matrix'][feature_name][engine_type] = {
                    'supported': feature_info.get('supported', False),
                    'description': feature_info.get('description', ''),
                    'features': feature_info.get('features', [])
                }
            
            # Performance comparison
            comparison_data['performance_comparison'][engine_type] = {
                'complexity': complexity,
                'memory_efficiency': 'High' if engine_type == EngineType.TIME_WINDOW_SCANNING else 'Medium',
                'processing_speed': 'Very Fast' if engine_type == EngineType.TIME_WINDOW_SCANNING else 'Fast',
                'scalability': 'Excellent' if engine_type == EngineType.TIME_WINDOW_SCANNING else 'Good'
            }
            
            # Use case recommendations
            comparison_data['use_case_recommendations'][engine_type] = use_cases
        
        return comparison_data
    
    @staticmethod
    def validate_engine_type(engine_type: str) -> bool:
        """
        Validate that an engine type is supported.
        
        Args:
            engine_type: Engine type to validate
            
        Returns:
            True if engine type is valid, False otherwise
        """
        valid_types = [EngineType.TIME_WINDOW_SCANNING, EngineType.IDENTITY_BASED]
        return engine_type in valid_types
