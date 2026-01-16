"""
Pipeline Executor
Executes complete analysis pipelines from configuration files.
"""

import os
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..config import PipelineConfig, FeatherConfig, WingConfig
from ..engine import CorrelationEngine, CorrelationResult
from ..engine.engine_selector import EngineSelector, EngineType
from ..engine.base_engine import FilterConfig, BaseCorrelationEngine
from ..wings.core.wing_model import Wing, FeatherSpec, CorrelationRules


class PipelineExecutor:
    """Executes complete analysis pipelines"""
    
    def __init__(self, pipeline_config: PipelineConfig):
        """
        Initialize pipeline executor.
        
        Args:
            pipeline_config: Pipeline configuration to execute
        """
        self.config = pipeline_config
        
        # Cancellation flag
        self._cancelled = False
        
        # NEW: Create filter configuration from pipeline config
        self.filters = FilterConfig(
            time_period_start=self._parse_datetime(getattr(pipeline_config, 'time_period_start', None)),
            time_period_end=self._parse_datetime(getattr(pipeline_config, 'time_period_end', None)),
            identity_filters=getattr(pipeline_config, 'identity_filters', None),
            case_sensitive=getattr(pipeline_config, 'identity_filter_case_sensitive', False)
        )
        
        # Create shared integration instances for dependency injection
        self._create_shared_integrations(pipeline_config)
        
        # NEW: Create engine using selector based on pipeline config with integrations
        # Use getattr with default to handle old configs without engine_type
        # Default to identity_based (the preferred default engine)
        engine_type = getattr(pipeline_config, 'engine_type', EngineType.IDENTITY_BASED)
        
        # Normalize engine type - handle legacy 'time_based' value
        if engine_type == 'time_based':
            engine_type = EngineType.TIME_WINDOW_SCANNING
        
        print(f"[PipelineExecutor] Creating engine: {engine_type}")
        
        try:
            # Create engine with shared integrations (dependency injection)
            self.engine = self._create_engine_with_integrations(
                pipeline_config=pipeline_config,
                engine_type=engine_type
            )
            print(f"[PipelineExecutor] Engine created successfully: {type(self.engine).__name__}")
        except Exception as e:
            # Only log errors, not routine messages
            import logging
            logging.warning(f"Failed to create {engine_type} engine with integrations: {e}")
            print(f"[PipelineExecutor] WARNING: Failed to create {engine_type} engine: {e}")
            try:
                self.engine = EngineSelector.create_engine(
                    config=pipeline_config,
                    engine_type=engine_type,
                    filters=self.filters
                )
                print(f"[PipelineExecutor] Engine created (without integrations): {type(self.engine).__name__}")
            except Exception as e2:
                logging.warning(f"Failed to create {engine_type} engine: {e2}, falling back to identity_based")
                print(f"[PipelineExecutor] WARNING: Falling back to IDENTITY_BASED: {e2}")
                self.engine = EngineSelector.create_engine(
                    config=pipeline_config,
                    engine_type=EngineType.IDENTITY_BASED,
                    filters=self.filters
                )
        
        self.results: List[CorrelationResult] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.progress_widget = None  # Optional progress display widget
        self.verbose = False  # Set to True for debug output
    
    def _create_shared_integrations(self, pipeline_config: PipelineConfig):
        """
        Create shared integration instances for dependency injection.
        
        Args:
            pipeline_config: Pipeline configuration
        """
        try:
            from ..integration.weighted_scoring_integration import WeightedScoringIntegration
            from ..integration.semantic_mapping_integration import SemanticMappingIntegration
            
            # Get config manager from pipeline config
            config_manager = getattr(pipeline_config, 'config_manager', None)
            
            # Create shared integration instances
            self.scoring_integration = WeightedScoringIntegration(config_manager)
            self.semantic_integration = SemanticMappingIntegration(config_manager)
            
            # Load case-specific configurations if available
            case_id = getattr(pipeline_config, 'case_id', None)
            if case_id:
                self.scoring_integration.load_case_specific_scoring_weights(case_id)
                self.semantic_integration.load_case_specific_mappings(case_id)
            
            # Register integrations as configuration observers
            if config_manager:
                config_manager.register_observer(self._on_config_changed)
            
            print("[PipelineExecutor] Shared integrations created and registered as observers")
            
        except Exception as e:
            import logging
            logging.warning(f"Failed to create shared integrations: {e}")
            # Set to None so engines will create their own
            self.scoring_integration = None
            self.semantic_integration = None
    
    def _on_config_changed(self, old_config, new_config):
        """
        Called when configuration changes.
        
        Args:
            old_config: Previous configuration
            new_config: New configuration
        """
        try:
            print("[PipelineExecutor] Configuration changed, reloading integrations...")
            
            # Reload integrations
            if self.scoring_integration:
                self.scoring_integration.reload_configuration()
            
            if self.semantic_integration:
                self.semantic_integration.reload_configuration()
            
            print("[PipelineExecutor] Integrations reloaded successfully")
            
        except Exception as e:
            import logging
            logging.error(f"Failed to reload integrations after configuration change: {e}")
    
    def _create_engine_with_integrations(self, pipeline_config: PipelineConfig, 
                                        engine_type: EngineType) -> BaseCorrelationEngine:
        """
        Create engine with shared integrations injected.
        
        Args:
            pipeline_config: Pipeline configuration
            engine_type: Type of engine to create
            
        Returns:
            Engine instance with injected integrations
        """
        from ..engine.time_based_engine import TimeWindowScanningEngine
        from ..engine.identity_based_engine_adapter import IdentityBasedEngineAdapter
        
        if engine_type == EngineType.TIME_WINDOW_SCANNING:
            return TimeWindowScanningEngine(
                config=pipeline_config,
                filters=self.filters,
                debug_mode=getattr(pipeline_config, 'debug_mode', False),
                scoring_integration=self.scoring_integration,
                mapping_integration=self.semantic_integration
            )
        elif engine_type == EngineType.IDENTITY_BASED:
            return IdentityBasedEngineAdapter(
                config=pipeline_config,
                filters=self.filters,
                mapping_integration=self.semantic_integration,
                scoring_integration=self.scoring_integration
            )
        else:
            # Fallback to EngineSelector for other engine types
            return EngineSelector.create_engine(
                config=pipeline_config,
                engine_type=engine_type,
                filters=self.filters
            )
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse datetime string to datetime object"""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except:
            return None
    
    def set_progress_widget(self, widget):
        """
        Set progress display widget for GUI feedback.
        
        Args:
            widget: ProgressDisplayWidget instance
        """
        self.progress_widget = widget
        # Register progress listener with engine
        if widget:
            self.engine.register_progress_listener(widget.handle_progress_event)
    
    def execute(self) -> Dict[str, Any]:
        """
        Execute the complete pipeline.
        
        Returns:
            Dictionary with execution results and statistics
        """
        start_time = time.time()
        
        if self.verbose:
            print(f"Executing Pipeline: {self.config.pipeline_name}")
            print("=" * 60)
        
        # Step 1: Create feathers (if configured)
        feather_paths = {}
        if self.config.auto_create_feathers:
            if self.verbose:
                print("\nStep 1: Creating Feathers...")
            feather_paths = self._create_feathers()
        else:
            if self.verbose:
                print("\nStep 1: Skipping feather creation (using existing feathers)")
            # Use paths from feather configs
            # Map by BOTH config_name AND feather_name for compatibility
            for feather_config in self.config.feather_configs:
                feather_paths[feather_config.config_name] = feather_config.output_database
                feather_paths[feather_config.feather_name] = feather_config.output_database
        
        # Check for cancellation
        if self._cancelled:
            print("\n⚠️ Execution cancelled before wing execution")
            return self._build_cancelled_summary(start_time)
        
        # Step 2: Execute wings (if configured)
        if self.config.auto_run_correlation:
            if self.verbose:
                print("\nStep 2: Executing Wings...")
            
            # Detect circular dependencies and missing references
            dep_report = self._detect_circular_dependencies(feather_paths)
            
            if dep_report['errors']:
                if self.verbose:
                    print("  Dependency validation errors:")
                    for error in dep_report['errors']:
                        print(f"    ✗ {error}")
                for error in dep_report['errors']:
                    self.errors.append(error)
                if self.verbose:
                    print("  Halting execution due to missing feather references")
            else:
                # Generate dependency graph
                if self.config.output_directory:
                    dot_graph = self._generate_dependency_graph_dot(feather_paths)
                    graph_path = Path(self.config.output_directory) / "dependency_graph.dot"
                    graph_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(graph_path, 'w') as f:
                        f.write(dot_graph)
                    print(f"  Dependency graph saved to: {graph_path}")
                
                # Execute wings (with cancellation support)
                self._execute_wings(feather_paths)
        else:
            if self.verbose:
                print("\nStep 2: Skipping correlation (manual execution required)")
        
        # Check for cancellation
        if self._cancelled:
            print("\n⚠️ Execution cancelled - saving partial results")
            return self._build_cancelled_summary(start_time)
        
        # Step 3: Generate report (if configured)
        execution_id = None
        if self.config.generate_report:
            if self.verbose:
                print("\nStep 3: Generating Report...")
            execution_id = self._generate_report()
        
        # Calculate execution time
        execution_time = time.time() - start_time
        
        # Update pipeline config
        self.config.last_executed = datetime.now().isoformat()
        
        # Calculate feathers actually used in correlation (from results)
        feathers_used = 0
        for r in self.results:
            if hasattr(r, 'feathers_processed') and r.feathers_processed:
                feathers_used = max(feathers_used, r.feathers_processed)
            elif hasattr(r, 'feather_metadata') and r.feather_metadata:
                feathers_used = max(feathers_used, len(r.feather_metadata))
        
        # Build summary - use memory-safe to_dict for large results
        results_summary = []
        for r in self.results:
            try:
                # Use to_dict with include_matches=False for large results
                if r.total_matches > 10000:
                    results_summary.append(r.to_dict(include_matches=False))
                else:
                    results_summary.append(r.to_dict(include_matches=True, max_matches=1000))
            except MemoryError:
                # Fallback to minimal summary on memory error
                results_summary.append({
                    'wing_id': r.wing_id,
                    'wing_name': r.wing_name,
                    'total_matches': r.total_matches,
                    'matches_truncated': True,
                    'error': 'MemoryError - results too large'
                })
        
        summary = {
            'pipeline_name': self.config.pipeline_name,
            'execution_time': execution_time,
            'feathers_created': len(feather_paths),
            'feathers_used': feathers_used if feathers_used > 0 else len(feather_paths),
            'wings_executed': len(self.results),
            'total_matches': sum(r.total_matches for r in self.results),
            'errors': self.errors,
            'warnings': self.warnings,
            'results': results_summary,
            'execution_id': execution_id,  # Include execution_id for results viewer
            'database_path': str(Path(self.config.output_directory) / "correlation_results.db") if self.config.output_directory else None,
            'output_directory': self.config.output_directory,  # Include output directory for results viewer
            'engine_type': getattr(self.config, 'engine_type', 'time_window_scanning'),  # Include engine type for viewer selection
            'cancelled': self._cancelled
        }
        
        if self.verbose:
            print("\n" + "=" * 60)
            if self._cancelled:
                print(f"Pipeline Execution Cancelled (Partial Results Saved)")
            else:
                print(f"Pipeline Execution Complete!")
            print(f"Time: {execution_time:.2f} seconds")
            print(f"Feathers Used: {summary['feathers_used']}")
            print(f"Wings: {len(self.results)}")
            print(f"Total Matches: {summary['total_matches']}")
        
        if self.errors and self.verbose:
            print(f"Errors: {len(self.errors)}")
        if self.warnings and self.verbose:
            print(f"Warnings: {len(self.warnings)}")
        
        return summary
    
    def _build_cancelled_summary(self, start_time: float) -> Dict[str, Any]:
        """Build summary for cancelled execution."""
        execution_time = time.time() - start_time
        
        # Save partial results if any
        execution_id = None
        if self.results and self.config.generate_report:
            execution_id = self._generate_report()
        
        return {
            'pipeline_name': self.config.pipeline_name,
            'execution_time': execution_time,
            'feathers_created': 0,
            'feathers_used': 0,
            'wings_executed': len(self.results),
            'total_matches': sum(r.total_matches for r in self.results),
            'errors': self.errors + ["Execution cancelled by user"],
            'warnings': self.warnings,
            'results': [],
            'execution_id': execution_id,
            'database_path': str(Path(self.config.output_directory) / "correlation_results.db") if self.config.output_directory else None,
            'engine_type': getattr(self.config, 'engine_type', 'time_window_scanning'),
            'cancelled': True
        }
    
    def _create_feathers(self) -> Dict[str, str]:
        """
        Create feather databases from configurations.
        
        Returns:
            Dictionary mapping feather_config_name -> database_path
        """
        feather_paths = {}
        
        for i, feather_config in enumerate(self.config.feather_configs, 1):
            if self.verbose:
                print(f"  [{i}/{len(self.config.feather_configs)}] Creating {feather_config.feather_name}...")
            
            try:
                # In a real implementation, this would:
                # 1. Load source data
                # 2. Apply transformations
                # 3. Create feather database
                # For now, we'll just validate the config
                
                if not Path(feather_config.source_database).exists():
                    self.warnings.append(
                        f"Source database not found for {feather_config.feather_name}: "
                        f"{feather_config.source_database}"
                    )
                    continue
                
                # Store the output path - map by BOTH config_name AND feather_name
                feather_paths[feather_config.config_name] = feather_config.output_database
                feather_paths[feather_config.feather_name] = feather_config.output_database
                
                if self.verbose:
                    print(f"      ✓ Created: {feather_config.output_database}")
                
            except Exception as e:
                error_msg = f"Failed to create feather {feather_config.feather_name}: {str(e)}"
                self.errors.append(error_msg)
                if self.verbose:
                    print(f"      ✗ Error: {str(e)}")
        
        return feather_paths

    
    def _execute_wings(self, feather_paths: Dict[str, str]):
        """
        Execute all wings in the pipeline with enhanced validation.
        
        Args:
            feather_paths: Dictionary mapping feather_config_name -> database_path
        """
        # Pre-execution validation report
        validation_report = self._validate_feather_wing_linkages(feather_paths)
        
        if validation_report['errors']:
            if self.verbose:
                print("  Pre-execution validation errors:")
                for error in validation_report['errors']:
                    print(f"    ✗ {error}")
            for error in validation_report['errors']:
                self.errors.append(error)
            return
        
        if validation_report['warnings']:
            if self.verbose:
                print("  Pre-execution validation warnings:")
                for warning in validation_report['warnings']:
                    print(f"    ! {warning}")
            for warning in validation_report['warnings']:
                self.warnings.append(warning)
        
        for i, wing_config in enumerate(self.config.wing_configs, 1):
            if self.verbose:
                print(f"\n  [{i}/{len(self.config.wing_configs)}] Executing Wing: {wing_config.wing_name}")
                print(f"      Wing ID: {wing_config.wing_id}")
                print(f"      Feathers in wing: {len(wing_config.feathers)}")
            
            # NEW: Log filter configuration
            if self.verbose and (self.filters.time_period_start or self.filters.time_period_end):
                print(f"      Time Period Filter:")
                if self.filters.time_period_start:
                    print(f"        Start: {self.filters.time_period_start}")
                if self.filters.time_period_end:
                    print(f"        End: {self.filters.time_period_end}")
            
            if self.verbose and self.filters.identity_filters:
                print(f"      Identity Filters: {', '.join(self.filters.identity_filters)}")
                print(f"        Case Sensitive: {self.filters.case_sensitive}")
            
            # List all feathers in this wing
            if self.verbose:
                for feather_ref in wing_config.feathers:
                    feather_display_name = feather_ref.feather_config_name or feather_ref.feather_id
                    print(f"        • {feather_display_name} ({feather_ref.artifact_type})")
            
            try:
                # Convert WingConfig to Wing (with validation)
                wing = self._wing_config_to_wing(wing_config)
            except ValueError as e:
                # Validation failed - skip this wing
                if self.verbose:
                    print(f"      ✗ Configuration validation failed: {str(e)}")
                continue
            
            try:
                # Build feather path mapping with enhanced path resolution
                # Primary: feather_config_name → FeatherConfig → output_database
                # Fallback: feather_database_path (absolute or relative)
                wing_feather_paths = {}
                for feather_ref in wing_config.feathers:
                    # Use consistent ID (same logic as in _wing_config_to_wing)
                    consistent_feather_id = feather_ref.feather_config_name or feather_ref.feather_id
                    
                    resolved_path = None
                    resolution_method = None
                    
                    # Primary: Resolve via feather_config_name
                    if feather_ref.feather_config_name and feather_ref.feather_config_name in feather_paths:
                        resolved_path = feather_paths[feather_ref.feather_config_name]
                        resolution_method = "config_name"
                    
                    # Secondary: Resolve via feather_id
                    elif feather_ref.feather_id and feather_ref.feather_id in feather_paths:
                        resolved_path = feather_paths[feather_ref.feather_id]
                        resolution_method = "feather_id"
                    
                    # Fallback: Use feather_database_path directly
                    elif feather_ref.feather_database_path:
                        # Support both absolute and relative paths
                        db_path = Path(feather_ref.feather_database_path)
                        
                        if db_path.is_absolute():
                            resolved_path = str(db_path)
                            resolution_method = "absolute_path"
                        else:
                            # Try multiple locations for relative paths
                            potential_paths = []
                            
                            # Try 1: Relative to pipeline's output_directory
                            if self.config.output_directory:
                                potential_paths.append(Path(self.config.output_directory) / db_path)
                            
                            # Try 2: Relative to case's Correlation directory (parent of output)
                            if self.config.output_directory:
                                output_parent = Path(self.config.output_directory).parent
                                potential_paths.append(output_parent / db_path)
                                # Also try feathers subdirectory
                                potential_paths.append(output_parent / "feathers" / db_path.name)
                            
                            # Try 3: Just the path as-is
                            potential_paths.append(db_path)
                            
                            # Try 4: Extract filename and look in common locations
                            db_filename = db_path.name
                            if self.config.output_directory:
                                output_parent = Path(self.config.output_directory).parent
                                potential_paths.append(output_parent / "feathers" / db_filename)
                            
                            # Find first existing path
                            for potential in potential_paths:
                                if potential.exists():
                                    resolved_path = str(potential)
                                    resolution_method = f"relative_search"
                                    break
                        
                        # Verify path exists
                        if resolved_path and not Path(resolved_path).exists():
                            resolved_path = None
                    
                    if resolved_path:
                        # Use feather_id as the key (what the engine expects)
                        feather_key = feather_ref.feather_id or consistent_feather_id
                        wing_feather_paths[feather_key] = resolved_path
                        # Log resolved path for debugging
                        if self.verbose and self.config.output_directory:
                            print(f"        Resolved {feather_key} via {resolution_method}: {resolved_path}")
                    else:
                        error_msg = (
                            f"Feather database not found for wing '{wing_config.wing_name}', "
                            f"feather_id '{consistent_feather_id}': {feather_ref.feather_database_path}"
                        )
                        self.errors.append(error_msg)
                        if self.verbose:
                            print(f"      ✗ {error_msg}")
                
                if len(wing_feather_paths) < wing.correlation_rules.minimum_matches:
                    warning_msg = (
                        f"Not enough feathers available for {wing_config.wing_name}: "
                        f"found {len(wing_feather_paths)}, need {wing.correlation_rules.minimum_matches}"
                    )
                    self.warnings.append(warning_msg)
                    if self.verbose:
                        print(f"      ! {warning_msg}")
                    continue
                
                # Create execution record BEFORE wing execution for streaming support
                execution_id = None
                if hasattr(self.engine, 'set_output_directory') and self.config.output_directory:
                    # Create database and execution record first
                    output_dir = Path(self.config.output_directory)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    db_file = output_dir / "correlation_results.db"
                    
                    from ..engine.database_persistence import ResultsDatabase
                    with ResultsDatabase(str(db_file)) as db:
                        # Create execution record with placeholder values
                        execution_id = db.create_execution_placeholder(
                            pipeline_name=self.config.pipeline_name,
                            output_dir=str(output_dir),
                            case_name=self.config.case_name,
                            investigator=self.config.investigator,
                            engine_type=self.config.engine_type,
                            wing_config=self.config.wing_configs[0].to_dict() if self.config.wing_configs else None,
                            pipeline_config=self.config.to_dict(),
                            time_period_start=self.config.time_period_start,
                            time_period_end=self.config.time_period_end,
                            identity_filters=self.config.identity_filters
                        )
                    
                    # Now set output directory with execution_id for streaming
                    self.engine.set_output_directory(self.config.output_directory, execution_id)
                    print(f"[Pipeline] Streaming enabled with execution_id={execution_id}")
                
                # Execute wing
                result = self.engine.execute_wing(wing, wing_feather_paths)
                
                # DEBUG: Verify matches before appending
                print(f"[Pipeline] 🔍 DEBUG: Appending result '{result.wing_name}' with {len(result.matches)} matches")
                
                self.results.append(result)
                
                # Store execution_id for later use
                if execution_id:
                    self._execution_id = execution_id
                
                # Progress reported via events, not print
                
                if result.errors:
                    self.errors.extend(result.errors)
                if result.warnings:
                    self.warnings.extend(result.warnings)
                
            except Exception as e:
                error_msg = f"Failed to execute wing {wing_config.wing_name}: {str(e)}"
                self.errors.append(error_msg)
                if self.verbose:
                    print(f"      ✗ Error: {str(e)}")
    
    def _validate_feather_wing_linkages(self, feather_paths: Dict[str, str]) -> Dict[str, Any]:
        """
        Validate all feather-wing linkages before execution.
        
        Returns:
            Dictionary with 'errors', 'warnings', and 'linkages' lists
        """
        report = {
            'errors': [],
            'warnings': [],
            'linkages': []
        }
        
        for wing_config in self.config.wing_configs:
            for feather_ref in wing_config.feathers:
                linkage = {
                    'wing_name': wing_config.wing_name,
                    'feather_id': feather_ref.feather_id,
                    'feather_config_name': feather_ref.feather_config_name,
                    'feather_database_path': feather_ref.feather_database_path,
                    'status': 'unknown'
                }
                
                # Validate feather_config_name reference exists
                if feather_ref.feather_config_name:
                    if feather_ref.feather_config_name not in feather_paths:
                        report['errors'].append(
                            f"Wing '{wing_config.wing_name}' references feather_config_name "
                            f"'{feather_ref.feather_config_name}' which doesn't exist in pipeline"
                        )
                        linkage['status'] = 'error_missing_config'
                    else:
                        linkage['resolved_path'] = feather_paths[feather_ref.feather_config_name]
                        linkage['status'] = 'ok'
                
                # Validate feather_database_path points to existing file
                if not Path(feather_ref.feather_database_path).exists():
                    if linkage['status'] != 'ok':  # Only error if config resolution also failed
                        report['errors'].append(
                            f"Wing '{wing_config.wing_name}', feather_id '{feather_ref.feather_id}': "
                            f"database path doesn't exist: {feather_ref.feather_database_path}"
                        )
                        linkage['status'] = 'error_missing_file'
                
                report['linkages'].append(linkage)
        
        return report
    
    def _detect_circular_dependencies(self, feather_paths: Dict[str, str]) -> Dict[str, Any]:
        """
        Detect circular dependencies and missing feather references.
        
        Returns:
            Dictionary with 'errors', 'warnings', and 'dependency_graph'
        """
        report = {
            'errors': [],
            'warnings': [],
            'dependency_graph': {}
        }
        
        # Track which feathers are referenced by which wings
        feather_usage = {}  # feather_config_name -> list of wing_names
        
        for wing_config in self.config.wing_configs:
            for feather_ref in wing_config.feathers:
                feather_name = feather_ref.feather_config_name or feather_ref.feather_id
                
                if feather_name not in feather_usage:
                    feather_usage[feather_name] = []
                feather_usage[feather_name].append(wing_config.wing_name)
                
                # Check if feather exists in pipeline
                if feather_ref.feather_config_name and feather_ref.feather_config_name not in feather_paths:
                    report['errors'].append(
                        f"Wing '{wing_config.wing_name}' references feather '{feather_ref.feather_config_name}' "
                        f"which doesn't exist in pipeline's feather_configs"
                    )
        
        # Log feathers used by multiple wings (informational)
        for feather_name, wing_names in feather_usage.items():
            if len(wing_names) > 1:
                report['warnings'].append(
                    f"Feather '{feather_name}' is referenced by multiple wings: {', '.join(wing_names)}"
                )
        
        # Build dependency graph
        report['dependency_graph'] = feather_usage
        
        return report
    
    def _generate_dependency_graph_dot(self, feather_paths: Dict[str, str]) -> str:
        """
        Generate dependency graph in DOT format for visualization with GraphViz.
        
        Returns:
            DOT format string
        """
        dot = ["digraph FeatherWingDependencies {"]
        dot.append("  rankdir=LR;")
        dot.append("  node [shape=box];")
        dot.append("")
        
        # Add feather nodes
        dot.append("  // Feather nodes")
        for feather_name in feather_paths.keys():
            dot.append(f'  "{feather_name}" [style=filled, fillcolor=lightblue];')
        
        dot.append("")
        dot.append("  // Wing nodes")
        for wing_config in self.config.wing_configs:
            dot.append(f'  "{wing_config.wing_name}" [style=filled, fillcolor=lightgreen];')
        
        dot.append("")
        dot.append("  // Dependencies")
        for wing_config in self.config.wing_configs:
            for feather_ref in wing_config.feathers:
                feather_name = feather_ref.feather_config_name or feather_ref.feather_id
                dot.append(f'  "{feather_name}" -> "{wing_config.wing_name}";')
        
        dot.append("}")
        
        return "\n".join(dot)
    
    def _wing_config_to_wing(self, wing_config: WingConfig) -> Wing:
        """
        Convert WingConfig to Wing object with comprehensive validation.
        
        Validates all required fields and configuration values before conversion.
        
        Args:
            wing_config: Wing configuration to convert
            
        Returns:
            Wing object ready for execution
            
        Raises:
            ValueError: If validation fails
        """
        validation_errors = []
        
        # Validate required fields
        if not wing_config.wing_id:
            validation_errors.append("wing_id is required")
        if not wing_config.wing_name:
            validation_errors.append("wing_name is required")
        
        # Validate time_window_minutes
        if wing_config.time_window_minutes <= 0:
            validation_errors.append(
                f"time_window_minutes must be > 0 (current: {wing_config.time_window_minutes})"
            )
        
        # Validate minimum_matches
        if wing_config.minimum_matches < 1:
            validation_errors.append(
                f"minimum_matches must be >= 1 (current: {wing_config.minimum_matches}). "
                f"This value determines how many non-anchor feathers must have matching records. "
                f"For example, minimum_matches=1 requires anchor + 1 other feather (2 total)."
            )
        
        # Validate minimum_matches vs feather count
        feather_count = len(wing_config.feathers) if wing_config.feathers else 0
        if feather_count > 0 and wing_config.minimum_matches >= feather_count:
            validation_errors.append(
                f"minimum_matches ({wing_config.minimum_matches}) must be less than feather count ({feather_count}). "
                f"With {feather_count} feathers, maximum minimum_matches is {feather_count - 1}. "
                f"Remember: minimum_matches determines non-anchor feathers required (total = anchor + minimum_matches)."
            )
        
        # Validate anchor_priority contains valid artifact types
        try:
            from ..config.artifact_type_registry import get_registry
            registry = get_registry()
            valid_artifact_types = set(registry.get_all_types())
        except Exception:
            # Fallback to hard-coded set if registry fails
            valid_artifact_types = {
                "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
                "Jumplists", "LNK", "MFT", "USN", "Registry", "Browser"
            }
        for artifact_type in wing_config.anchor_priority:
            if artifact_type not in valid_artifact_types:
                validation_errors.append(
                    f"Invalid artifact type in anchor_priority: '{artifact_type}'"
                )
        
        # Validate feather references
        if not wing_config.feathers:
            validation_errors.append("Wing must have at least one feather")
        
        for i, feather_ref in enumerate(wing_config.feathers):
            if not feather_ref.feather_id and not feather_ref.feather_config_name:
                validation_errors.append(
                    f"Feather {i+1}: must have either feather_id or feather_config_name"
                )
            if not feather_ref.artifact_type:
                validation_errors.append(
                    f"Feather {i+1}: artifact_type is required"
                )
            if not feather_ref.feather_database_path:
                validation_errors.append(
                    f"Feather {i+1}: feather_database_path is required"
                )
        
        # If validation failed, add errors and raise
        if validation_errors:
            error_msg = f"Wing configuration validation failed for '{wing_config.wing_name}':\n"
            error_msg += "\n".join(f"  - {err}" for err in validation_errors)
            self.errors.extend(validation_errors)
            raise ValueError(error_msg)
        
        # Proceed with conversion
        wing = Wing()
        wing.wing_id = wing_config.wing_id
        wing.wing_name = wing_config.wing_name
        wing.description = wing_config.description
        wing.proves = wing_config.proves
        wing.author = wing_config.author
        
        # Convert feather references to FeatherSpecs
        # Ensure feather_id consistency: use feather_config_name as primary identifier
        wing.feathers = []
        for feather_ref in wing_config.feathers:
            # Use feather_config_name as feather_id if available for consistency
            # Otherwise use the provided feather_id
            consistent_feather_id = feather_ref.feather_config_name or feather_ref.feather_id
            
            feather_spec = FeatherSpec(
                feather_id=consistent_feather_id,
                database_filename=feather_ref.feather_database_path,
                artifact_type=feather_ref.artifact_type,
                detection_confidence="high",
                manually_overridden=False
            )
            wing.feathers.append(feather_spec)
        
        # Set correlation rules
        wing.correlation_rules.time_window_minutes = wing_config.time_window_minutes
        wing.correlation_rules.minimum_matches = wing_config.minimum_matches
        wing.correlation_rules.target_application = wing_config.target_application
        wing.correlation_rules.target_file_path = wing_config.target_file_path
        wing.correlation_rules.target_event_id = wing_config.target_event_id
        wing.correlation_rules.apply_to = wing_config.apply_to
        wing.correlation_rules.anchor_priority = wing_config.anchor_priority
        
        return wing
    
    def _execute_wings_old(self, feather_paths: Dict[str, str]):
        """
        Execute all wings in the pipeline.
        
        Args:
            feather_paths: Dictionary mapping feather_config_name -> database_path
        """
        for i, wing_config in enumerate(self.config.wing_configs, 1):
            if self.verbose:
                print(f"  [{i}/{len(self.config.wing_configs)}] Executing {wing_config.wing_name}...")
            
            try:
                # Convert WingConfig to Wing
                wing = self._wing_config_to_wing(wing_config)
                
                # Build feather path mapping
                wing_feather_paths = {}
                for feather_ref in wing_config.feathers:
                    # Try to find the feather database
                    if feather_ref.feather_config_name in feather_paths:
                        wing_feather_paths[feather_ref.feather_id] = feather_paths[feather_ref.feather_config_name]
                    elif Path(feather_ref.feather_database_path).exists():
                        wing_feather_paths[feather_ref.feather_id] = feather_ref.feather_database_path
                    else:
                        self.warnings.append(
                            f"Feather database not found: {feather_ref.feather_database_path}"
                        )
                
                if len(wing_feather_paths) < wing.correlation_rules.minimum_matches:
                    self.warnings.append(
                        f"Not enough feathers available for {wing_config.wing_name}"
                    )
                    continue
                
                # Execute wing
                result = self.engine.execute_wing(wing, wing_feather_paths)
                self.results.append(result)
                
                if self.verbose:
                    print(f"      ✓ Matches found: {result.total_matches}")
                
                if result.errors:
                    self.errors.extend(result.errors)
                if result.warnings:
                    self.warnings.extend(result.warnings)
                
            except Exception as e:
                error_msg = f"Failed to execute wing {wing_config.wing_name}: {str(e)}"
                self.errors.append(error_msg)
                if self.verbose:
                    print(f"      ✗ Error: {str(e)}")
    
    def _wing_config_to_wing(self, wing_config: WingConfig) -> Wing:
        """Convert WingConfig to Wing object"""
        wing = Wing()
        wing.wing_id = wing_config.wing_id
        wing.wing_name = wing_config.wing_name
        wing.description = wing_config.description
        wing.proves = wing_config.proves
        wing.author = wing_config.author
        
        # Convert feather references to FeatherSpecs
        wing.feathers = []
        for feather_ref in wing_config.feathers:
            feather_spec = FeatherSpec(
                feather_id=feather_ref.feather_id,
                database_filename=feather_ref.feather_database_path,
                artifact_type=feather_ref.artifact_type,
                detection_confidence="high",
                manually_overridden=False
            )
            wing.feathers.append(feather_spec)
        
        # Set correlation rules
        wing.correlation_rules.time_window_minutes = wing_config.time_window_minutes
        wing.correlation_rules.minimum_matches = wing_config.minimum_matches
        wing.correlation_rules.target_application = wing_config.target_application
        wing.correlation_rules.target_file_path = wing_config.target_file_path
        wing.correlation_rules.target_event_id = wing_config.target_event_id
        wing.correlation_rules.apply_to = wing_config.apply_to
        wing.correlation_rules.anchor_priority = wing_config.anchor_priority
        
        return wing
    
    def _generate_report(self) -> Optional[int]:
        """
        Generate analysis report - saves to SQLite database and JSON files.
        
        If streaming mode was used, matches are already in the database,
        so we only update the execution record and save JSON files.
        
        Returns:
            execution_id if successful, None otherwise
        """
        if not self.config.output_directory:
            self.warnings.append("No output directory specified, skipping report generation")
            if self.verbose:
                print("      ⚠ WARNING: No output directory set, results will not be saved!")
            return None
        
        try:
            # Create output directory
            output_dir = Path(self.config.output_directory)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            db_file = output_dir / "correlation_results.db"
            from ..engine.database_persistence import ResultsDatabase
            
            # Check if streaming mode was used (execution_id already exists)
            streaming_used = hasattr(self, '_execution_id') and self._execution_id is not None
            
            if streaming_used:
                # Streaming mode: matches already saved, just update execution record
                execution_id = self._execution_id
                print(f"\n      📁 Finalizing streaming results...")
                print(f"      " + "=" * 60)
                print(f"      ✓ Matches already saved via streaming mode")
                
                # Update execution record with final statistics
                with ResultsDatabase(str(db_file)) as db:
                    db.update_execution_stats(
                        execution_id=execution_id,
                        execution_duration=sum(r.execution_duration_seconds for r in self.results),
                        total_matches=sum(r.total_matches for r in self.results),
                        total_records_scanned=sum(r.total_records_scanned for r in self.results),
                        errors=self.errors,
                        warnings=self.warnings
                    )
            else:
                # Non-streaming mode: save everything to database
                print(f"\n      📁 Saving results to database...")
                print(f"      " + "=" * 60)
                
                # DEBUG: Verify matches before saving
                print(f"[Pipeline] 🔍 DEBUG: Saving {len(self.results)} result(s) to database")
                for i, r in enumerate(self.results):
                    print(f"[Pipeline] 🔍 DEBUG:   Result {i+1}: {r.wing_name} - {len(r.matches)} matches")
                
                with ResultsDatabase(str(db_file)) as db:
                    execution_id = db.save_execution(
                        pipeline_name=self.config.pipeline_name,
                        execution_time=sum(r.execution_duration_seconds for r in self.results),
                        results=self.results,
                        output_dir=str(output_dir),
                        case_name=self.config.case_name,
                        investigator=self.config.investigator,
                        errors=self.errors,
                        warnings=self.warnings,
                        engine_type=self.config.engine_type,
                        wing_config=self.config.wing_configs[0].to_dict() if self.config.wing_configs else None,
                        pipeline_config=self.config.to_dict(),
                        time_period_start=self.config.time_period_start,
                        time_period_end=self.config.time_period_end,
                        identity_filters=self.config.identity_filters
                    )
            
            # Get run name from database for display
            with ResultsDatabase(str(db_file)) as db:
                exec_metadata = db.get_execution_metadata(execution_id)
                run_name = exec_metadata.get('run_name', f'Execution_{execution_id}') if exec_metadata else f'Execution_{execution_id}'
            
            print(f"      " + "=" * 60)
            print(f"      ✓ Results saved to database: {db_file.name}")
            print(f"      ✓ Execution ID: {execution_id}")
            print(f"      ✓ Run Name: {run_name}")
            print(f"      ✓ Total matches: {sum(r.total_matches for r in self.results):,}")
            print(f"      ✓ Wings executed: {len(self.results)}")
            print(f"      📂 Database location: {db_file.absolute()}")
            print(f"      💾 Tables: executions, results, matches")
            
            return execution_id
            
        except Exception as e:
            error_msg = f"Failed to generate report: {str(e)}"
            self.errors.append(error_msg)
            print(f"      ✗ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_results(self) -> List[CorrelationResult]:
        """Get correlation results"""
        return self.results
    
    def get_errors(self) -> List[str]:
        """Get execution errors"""
        return self.errors
    
    def get_warnings(self) -> List[str]:
        """Get execution warnings"""
        return self.warnings
