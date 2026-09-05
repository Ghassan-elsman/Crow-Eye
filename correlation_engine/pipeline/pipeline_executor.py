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
from ..engine import CorrelationResult
from ..engine.engine_selector import EngineSelector, EngineType
from ..engine.base_engine import FilterConfig, BaseCorrelationEngine
from ..wings.core.wing_model import Wing, FeatherSpec, CorrelationRules


class _StatsView:
    """Adapts a plain statistics dict to the DatabaseErrorHandler interface.

    Lets the evidence-accounting loop treat a retained snapshot exactly like a
    live handler, rather than growing a second code path that could drift from
    the first.
    """

    def __init__(self, stats):
        self._stats = stats or {}
        self.feather_status = {
            fid: {'status': 'error'}
            for fid in (self._stats.get('feathers_with_errors') or [])
        }

    def get_error_statistics(self):
        return self._stats


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

        # What was ASKED for. `self.engine_type` is set after construction, from
        # the engine that actually exists - see below.
        requested_engine_type = engine_type

        # These three are populated during construction, so they have to exist
        # before it: the fallback path below appends to self.warnings, and it
        # used to be initialised further down, which is why a silent engine
        # substitution had nowhere to be recorded.
        self.results: List[CorrelationResult] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

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
                # A substituted engine is a different correlation strategy with
                # different semantics, so the run has to say so. This used to
                # reach logging and stdout only, while the summary - which the
                # results viewer and the report read - still named the engine
                # that had FAILED to build.
                self.warnings.append(
                    f"Requested engine '{requested_engine_type}' could not be "
                    f"created ({e2}); fell back to IDENTITY_BASED. Findings in "
                    f"this run were produced by the identity-based strategy."
                )

        # Report what EXISTS, not what was asked for. Derived from the object so
        # it cannot drift from reality the way a pre-assigned value did.
        self.engine_type = self._engine_type_of(self.engine, requested_engine_type)
        self.requested_engine_type = requested_engine_type

        self.progress_widget = None # Optional progress display widget
        self.verbose = False # Set to True for debug output
        self.feather_cache = None # Run-scoped; see set_feather_cache()

    def set_feather_cache(self, cache) -> None:
        """Share one run's feather work across executors.

        A multi-wing GUI run builds one executor per wing, so every wing used to
        re-open and re-derive every feather it names - and wings share feathers.
        The caller (the run, not the wing) owns the cache and passes the same
        one to each executor; the engine takes it from here if it can use it.
        None means "load every time", which is what happened before this
        existed, so CLI and test callers are unaffected.
        """
        self.feather_cache = cache
        if cache is not None and hasattr(self.engine, 'set_feather_cache'):
            self.engine.set_feather_cache(cache)
    
    @staticmethod
    def _engine_type_of(engine, fallback: str) -> str:
        """The engine type of the object that was actually built.

        Read from the instance rather than from the value that was requested.
        The requested value was previously stored straight into
        `self.engine_type` under a comment claiming it reported "what was
        actually created" - so when construction fell back to IDENTITY_BASED,
        `summary['engine_type']` still named the engine that had failed. The
        two engines are different correlation strategies, and a forensic
        summary that names the wrong one is wrong about how its own findings
        were produced.

        `fallback` is used only when the class is unrecognised, so an engine
        added later degrades to the requested name instead of reporting
        nothing.
        """
        name = type(engine).__name__ if engine is not None else ""
        if "TimeWindow" in name:
            return EngineType.TIME_WINDOW_SCANNING
        if "Identity" in name:
            return EngineType.IDENTITY_BASED
        return fallback

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
        except (ValueError, TypeError):
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
    
    def execute(self, resume_execution_id: int = None) -> Dict[str, Any]:
        """
        Execute the complete pipeline.
        
        Args:
            resume_execution_id: Optional execution ID to resume from paused state
        
        Returns:
            Dictionary with execution results and statistics
        """
        start_time = time.time()

        # Ensure a run-group id exists. The GUI worker sets one per run
        # (shared by all its per-wing executors); CLI/direct callers get
        # one per executor here (one executor = one run). On resume, reuse
        # the group stored on the resumed execution so the run stays whole.
        if resume_execution_id and self.config.output_directory:
            stored_group = self._lookup_run_group_id(resume_execution_id)
            if stored_group:
                self.config.run_group_id = stored_group
        if not getattr(self.config, 'run_group_id', None):
            import uuid
            self.config.run_group_id = str(uuid.uuid4())

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
            print("\n[WARN] Execution cancelled before wing execution")
            return self._build_cancelled_summary(start_time)
        
        # Step 2: Execute wings (if configured)
        if self.config.auto_run_correlation:
            if self.verbose:
                print("\nStep 2: Executing Wings...")

            # Pre-flight: surface unsupported operators / missing fields BEFORE
            # the evaluator silently logger.warnings them. Non-fatal; rules
            # still run but the analyst now sees what was problematic.
            from .rule_preflight import validate_semantic_rules
            self._rule_preflight_issues = validate_semantic_rules(self.config)
            if self._rule_preflight_issues:
                for issue in self._rule_preflight_issues:
                    self.warnings.append(
                        f"[Rule pre-flight] {issue['wing']} / {issue['rule_id']}: "
                        f"{issue['kind']} — {issue['detail']}"
                    )
                if self.verbose:
                    print(f" Pre-flight flagged {len(self._rule_preflight_issues)} rule issue(s)")

            # Detect circular dependencies and missing references
            dep_report = self._detect_circular_dependencies(feather_paths)
            
            unsatisfiable = self._unsatisfiable_wings(feather_paths)
            runnable = len(self.config.wing_configs) - len(unsatisfiable)

            if dep_report['errors']:
                if self.verbose:
                    print(" Dependency validation errors:")
                    for error in dep_report['errors']:
                        print(f" [FAIL] {error}")
                for error in dep_report['errors']:
                    self.errors.append(error)

            if dep_report['errors'] and not runnable:
                # Nothing can run. This is the case the halt was written for.
                if self.verbose:
                    print(" Halting execution: no wing has all of its feathers")
            else:
                if unsatisfiable and self.verbose:
                    print(f" Skipping {len(unsatisfiable)} wing(s) with missing feathers; "
                          f"running the remaining {runnable}")
                # Generate dependency graph
                if self.config.output_directory:
                    dot_graph = self._generate_dependency_graph_dot(feather_paths)
                    graph_path = Path(self.config.output_directory) / "dependency_graph.dot"
                    graph_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(graph_path, 'w') as f:
                        f.write(dot_graph)
                    print(f" Dependency graph saved to: {graph_path}")
                
                # Execute wings (with cancellation support)
                self._execute_wings(feather_paths)
        else:
            if self.verbose:
                print("\nStep 2: Skipping correlation (manual execution required)")
        
        # Check for cancellation
        if self._cancelled:
            print("\n[WARN] Execution cancelled - saving partial results")
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

        # Fold each wing's CorrelationResult.errors / .warnings into the
        # top-level summary lists so per-wing failures (feather connection
        # errors, missing-path errors recorded in _load_feathers) reach the
        # analyst-visible surfaces instead of staying buried in the result.
        for r in self.results:
            wing_label = getattr(r, 'wing_name', None) or getattr(r, 'wing_id', '<wing>')
            for err in (getattr(r, 'errors', None) or []):
                self.errors.append(f"[{wing_label}] {err}")
            for warn in (getattr(r, 'warnings', None) or []):
                self.warnings.append(f"[{wing_label}] {warn}")
        
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
        
        # Assemble evidence_accounting — surfaces silent drops to the user.
        # Sources are stats the engine already tracks; we just plumb them up.
        evidence_accounting = self._collect_evidence_accounting()
        # Surface fallback events as a top-level warning so the existing
        # execution log (which renders summary['warnings']) shows them.
        if evidence_accounting.get('fallback_operations', 0) > 0:
            feathers = evidence_accounting.get('feathers_with_errors', []) or []
            self.warnings.append(
                f"[Evidence accounting] {evidence_accounting['fallback_operations']} "
                f"silent DB fallback(s) fired. Feathers affected: "
                f"{', '.join(feathers) if feathers else '(unknown)'}. "
                f"These feathers may have contributed empty results to correlation."
            )

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
            'execution_id': execution_id, # Include execution_id for results viewer
            'database_path': str(Path(self.config.output_directory) / "correlation_results.db") if self.config.output_directory else None,
            'output_directory': self.config.output_directory, # Include output directory for results viewer
            'engine_type': self.engine_type, # Resolved engine type that was actually instantiated
            'run_group_id': getattr(self.config, 'run_group_id', None), # Links per-wing executions of one run
            'cancelled': self._cancelled,
            'rule_diagnostics': getattr(self, '_rule_preflight_issues', []), # Pre-flight rule validation
            'evidence_accounting': evidence_accounting,
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
    
    def _collect_evidence_accounting(self) -> Dict[str, Any]:
        """Aggregate the engine's existing per-feather / per-wing counters
        into a single summary surface so analysts can see silent drops.

        Sources, all pre-existing — no new tracking:
          * DatabaseErrorHandler.get_error_statistics() — DB fallbacks fired.
          * DatabaseErrorHandler.feather_status — which feathers errored.
          * Phase1ErrorHandler.get_summary() (if attached) — Phase 1 collection
            failures (feather query errors, identity-grouping crashes).
          * OptimizedFeatherQuery._schema_detection_errors (added in task #15)
            via the engine — distinguishes "no timestamps in feather" from
            "detection crashed".
          * Per-feather parse stats (added in task #17) — failed_parses rate.

        Returns a dict with a stable shape regardless of which engine is in
        use; missing fields default to empty/zero rather than raising."""
        evidence: Dict[str, Any] = {
            'fallback_operations': 0,
            'feathers_with_errors': [],
            'success_rate_percent': 100.0,
            'error_counts_by_type': {},
            'phase1_errors': {},
            'schema_detection_errors': [],
            'parse_stats_per_feather': {},
        }

        # Every DatabaseErrorHandler in play, not just one.
        #
        # This used to read `self.engine.error_handler` alone. The time-window
        # engine has no such attribute - it has `error_coordinator` and
        # `phase1_error_handler` - and the handlers that actually fire live on
        # the per-feather OptimizedFeatherQuery objects in
        # `engine.feather_queries`, one each. So `getattr` returned None, the
        # whole block was skipped, and a run in which 1,114 queries fell back to
        # "returning empty results" was reported as
        # `fallback_operations: 0, success_rate_percent: 100.0`.
        #
        # The surface built to reveal silent evidence loss was itself silent.
        handlers = []
        engine_handler = getattr(self.engine, 'error_handler', None)
        if engine_handler is not None:
            handlers.append(('engine', engine_handler))
        for feather_id, query in (getattr(self.engine, 'feather_queries', {}) or {}).items():
            h = getattr(query, 'error_handler', None)
            if h is not None:
                handlers.append((feather_id, h))

        # The engine clears `feather_queries` during execute(), long before this
        # runs, so by now that loop usually finds nothing. The engine rolls the
        # per-feather statistics into `retained_error_statistics` before
        # discarding the handlers - that snapshot is the real source here, and
        # without it a run that dropped a whole feather still reported clean.
        retained = getattr(self.engine, 'retained_error_statistics', None)
        if isinstance(retained, dict):
            handlers.append(('retained', _StatsView(retained)))

        if handlers:
            total_ops = successful_ops = 0
            reported_rates = []
            counts_by_type: Dict[str, int] = {}
            with_errors = set()
            for owner, handler in handlers:
                try:
                    stats = handler.get_error_statistics()
                except Exception as e:
                    self.warnings.append(
                        f"[Evidence accounting] stats unavailable for '{owner}': {e}")
                    continue
                evidence['fallback_operations'] += stats.get('fallback_operations', 0) or 0
                total_ops += stats.get('total_operations', 0) or 0
                successful_ops += stats.get('successful_operations', 0) or 0
                if stats.get('success_rate_percent') is not None:
                    reported_rates.append(stats['success_rate_percent'])
                for kind, n in (stats.get('error_counts_by_type') or {}).items():
                    counts_by_type[str(kind)] = counts_by_type.get(str(kind), 0) + n
                if (stats.get('failed_operations') or 0) > 0 or \
                        (stats.get('fallback_operations') or 0) > 0:
                    if owner != 'engine':
                        with_errors.add(owner)
                try:
                    feather_status = getattr(handler, 'feather_status', {}) or {}
                    with_errors.update(
                        fid for fid, s in feather_status.items()
                        if isinstance(s, dict) and s.get('status') == 'error'
                    )
                except Exception as e:
                    self.warnings.append(
                        f"[Evidence accounting] feather_status unavailable for '{owner}': {e}")

            evidence['error_counts_by_type'] = counts_by_type
            evidence['feathers_with_errors'] = sorted(with_errors)
            # Recomputed from the raw counts across every handler, so one quiet
            # feather cannot average away a broken one. When a handler reports a
            # rate but no counts, take the WORST rate reported rather than the
            # mean - an accounting surface should not round a broken feather off.
            if total_ops:
                evidence['success_rate_percent'] = round(
                    successful_ops / total_ops * 100.0, 2)
            elif reported_rates:
                evidence['success_rate_percent'] = min(reported_rates)
            else:
                evidence['success_rate_percent'] = 100.0

        # Phase1ErrorHandler aggregator (used by TimeWindowScanningEngine's
        # two-phase collector). Engines that don't use it just leave this empty.
        phase1_handler = getattr(self.engine, 'phase1_error_handler', None)
        if phase1_handler is not None:
            try:
                evidence['phase1_errors'] = phase1_handler.get_summary()
            except Exception as e:
                self.warnings.append(f"[Evidence accounting] phase1 summary unavailable: {e}")

        # Schema-detection errors are recorded on each OptimizedFeatherQuery;
        # the engine collects them under feather_queries dict. Best-effort —
        # silent if the engine doesn't expose them yet.
        feather_queries = getattr(self.engine, 'feather_queries', None) or {}
        for fid, query_manager in feather_queries.items():
            sde = getattr(query_manager, '_schema_detection_errors', None)
            if sde:
                for entry in sde:
                    evidence['schema_detection_errors'].append({
                        'feather_id': fid,
                        **(entry if isinstance(entry, dict) else {'detail': str(entry)}),
                    })
            parser = getattr(query_manager, 'timestamp_parser', None)
            if parser is not None:
                attempts = getattr(parser, 'parse_attempts', 0)
                failed = getattr(parser, 'failed_parses', 0)
                if attempts > 0:
                    evidence['parse_stats_per_feather'][fid] = {
                        'attempts': attempts,
                        'successful': getattr(parser, 'successful_parses', 0),
                        'failed': failed,
                        'failure_rate_percent': (failed / attempts * 100.0) if attempts else 0.0,
                    }

        return evidence

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
            'engine_type': self.engine_type,
            'run_group_id': getattr(self.config, 'run_group_id', None),
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
                print(f" [{i}/{len(self.config.feather_configs)}] Creating {feather_config.feather_name}...")
            
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
                    print(f" [OK] Created: {feather_config.output_database}")
                
            except Exception as e:
                error_msg = f"Failed to create feather {feather_config.feather_name}: {str(e)}"
                self.errors.append(error_msg)
                if self.verbose:
                    print(f" [FAIL] Error: {str(e)}")
        
        return feather_paths

    
    def _execute_wings(self, feather_paths: Dict[str, str]):
        """
        Execute all wings in the pipeline with enhanced validation.
        
        Args:
            feather_paths: Dictionary mapping feather_config_name -> database_path
        """
        # Pre-execution validation report
        validation_report = self._validate_feather_wing_linkages(feather_paths)

        # Wings missing a feather are skipped individually below rather than
        # taken as a reason to abandon the run.
        unsatisfiable = self._unsatisfiable_wings(feather_paths)

        if validation_report['errors']:
            if self.verbose:
                print(" Pre-execution validation errors:")
                for error in validation_report['errors']:
                    print(f" [FAIL] {error}")
            for error in validation_report['errors']:
                if error not in self.errors:
                    self.errors.append(error)
            if len(unsatisfiable) >= len(self.config.wing_configs):
                return

        if validation_report['warnings']:
            if self.verbose:
                print(" Pre-execution validation warnings:")
                for warning in validation_report['warnings']:
                    print(f" ! {warning}")
            for warning in validation_report['warnings']:
                self.warnings.append(warning)
        
        for i, wing_config in enumerate(self.config.wing_configs, 1):
            if wing_config.wing_name in unsatisfiable:
                absent = ", ".join(unsatisfiable[wing_config.wing_name])
                message = (f"Wing '{wing_config.wing_name}' skipped: this case has no "
                           f"{absent}")
                if message not in self.warnings:
                    self.warnings.append(message)
                if self.verbose:
                    print(f"\n [{i}/{len(self.config.wing_configs)}] Skipping Wing: "
                          f"{wing_config.wing_name} (missing {absent})")
                continue

            if self.verbose:
                print(f"\n [{i}/{len(self.config.wing_configs)}] Executing Wing: {wing_config.wing_name}")
                print(f" Wing ID: {wing_config.wing_id}")
                print(f" Feathers in wing: {len(wing_config.feathers)}")
            
            # NEW: Log filter configuration
            if self.verbose and (self.filters.time_period_start or self.filters.time_period_end):
                print(f" Time Period Filter:")
                if self.filters.time_period_start:
                    print(f" Start: {self.filters.time_period_start}")
                if self.filters.time_period_end:
                    print(f" End: {self.filters.time_period_end}")
            
            if self.verbose and self.filters.identity_filters:
                print(f" Identity Filters: {', '.join(self.filters.identity_filters)}")
                print(f" Case Sensitive: {self.filters.case_sensitive}")
            
            # List all feathers in this wing
            if self.verbose:
                for feather_ref in wing_config.feathers:
                    feather_display_name = feather_ref.feather_config_name or feather_ref.feather_id
                    print(f" • {feather_display_name} ({feather_ref.artifact_type})")
            
            try:
                # Convert WingConfig to Wing (with validation)
                wing = self._wing_config_to_wing(wing_config)
            except ValueError as e:
                # Validation failed - skip this wing
                if self.verbose:
                    print(f" [FAIL] Configuration validation failed: {str(e)}")
                continue
            
            try:
                # Build feather path mapping with enhanced path resolution
                # Primary: feather_config_name → FeatherConfig → output_database
                # Fallback: feather_database_path (absolute or relative)
                wing_feather_paths = {}
                for feather_ref in wing_config.feathers:
                    # Use consistent ID (same logic as in _wing_config_to_wing)
                    consistent_feather_id = feather_ref.feather_id or feather_ref.feather_config_name
                    
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
                            print(f" Resolved {feather_key} via {resolution_method}: {resolved_path}")
                    else:
                        error_msg = (
                            f"Feather database not found for wing '{wing_config.wing_name}', "
                            f"feather_id '{consistent_feather_id}': {feather_ref.feather_database_path}"
                        )
                        self.errors.append(error_msg)
                        if self.verbose:
                            print(f" [FAIL] {error_msg}")
                
                if len(wing_feather_paths) < wing.correlation_rules.minimum_matches:
                    warning_msg = (
                        f"Not enough feathers available for {wing_config.wing_name}: "
                        f"found {len(wing_feather_paths)}, need {wing.correlation_rules.minimum_matches}"
                    )
                    self.warnings.append(warning_msg)
                    if self.verbose:
                        print(f" ! {warning_msg}")
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
                            identity_filters=self.config.identity_filters,
                            run_group_id=getattr(self.config, 'run_group_id', None)
                        )
                    
                    # Now set output directory with execution_id for streaming
                    self.engine.set_output_directory(self.config.output_directory, execution_id)
                    print(f"[Pipeline] Streaming enabled with execution_id={execution_id}")
                
                # Execute wing
                result = self.engine.execute_wing(wing, wing_feather_paths)
                
                # DEBUG: Verify matches before appending
                print(f"[Pipeline] DEBUG: Appending result '{result.wing_name}' with {len(result.matches)} matches")
                
                self.results.append(result)

                # Store execution_id for later use
                if execution_id:
                    self._execution_id = execution_id

                    # Cross-wing identity reconciliation: merge this wing's
                    # identities into the run-level registry so wings that run
                    # after each other share main identities / sub-identities
                    # with full per-wing attribution.
                    self._reconcile_identity_wing(execution_id)

                # Progress reported via events, not print
                
                if result.errors:
                    self.errors.extend(result.errors)
                if result.warnings:
                    self.warnings.extend(result.warnings)
                
            except Exception as e:
                error_msg = f"Failed to execute wing {wing_config.wing_name}: {str(e)}"
                self.errors.append(error_msg)
                if self.verbose:
                    print(f" [FAIL] Error: {str(e)}")
    
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
                    if linkage['status'] != 'ok': # Only error if config resolution also failed
                        report['errors'].append(
                            f"Wing '{wing_config.wing_name}', feather_id '{feather_ref.feather_id}': "
                            f"database path doesn't exist: {feather_ref.feather_database_path}"
                        )
                        linkage['status'] = 'error_missing_file'
                
                report['linkages'].append(linkage)
        
        return report
    
    def _unsatisfiable_wings(self, feather_paths: Dict[str, str]) -> Dict[str, list]:
        """Wings that cannot run, mapped to the feathers they are missing.

        A wing needs every feather it references. One that is missing used to
        stop the whole pipeline: `sync_and_augment_pipeline_wings` injects every
        shipped default wing into whatever case is opened, so a new default wing
        referencing a feather an older case never parsed silently disabled that
        case's entire correlation run - including wings that were complete.
        Skipping just the wing keeps the diagnostic and loses only the analysis
        that genuinely cannot be done.
        """
        missing = {}
        for wing_config in self.config.wing_configs:
            absent = [
                ref.feather_config_name
                for ref in wing_config.feathers
                if ref.feather_config_name and ref.feather_config_name not in feather_paths
            ]
            if absent:
                missing[wing_config.wing_name] = absent
        return missing

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
        feather_usage = {} # feather_config_name -> list of wing_names
        
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
        dot.append(" rankdir=LR;")
        dot.append(" node [shape=box];")
        dot.append("")
        
        # Add feather nodes
        dot.append(" // Feather nodes")
        for feather_name in feather_paths.keys():
            dot.append(f' "{feather_name}" [style=filled, fillcolor=lightblue];')
        
        dot.append("")
        dot.append(" // Wing nodes")
        for wing_config in self.config.wing_configs:
            dot.append(f' "{wing_config.wing_name}" [style=filled, fillcolor=lightgreen];')
        
        dot.append("")
        dot.append(" // Dependencies")
        for wing_config in self.config.wing_configs:
            for feather_ref in wing_config.feathers:
                feather_name = feather_ref.feather_config_name or feather_ref.feather_id
                dot.append(f' "{feather_name}" -> "{wing_config.wing_name}";')
        
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
        
        # Check anchor_priority against this wing's OWN feathers - a preference
        # order, never a reason to refuse to run the wing. See
        # wings.core.wing_model.validate_anchor_priority for why this is not a
        # validation error any more.
        from ..wings.core.wing_model import validate_anchor_priority
        for message in validate_anchor_priority(
                wing_config.anchor_priority,
                [f.artifact_type for f in (wing_config.feathers or [])]):
            warning = f"Wing '{wing_config.wing_name}': {message}"
            if warning not in self.warnings:
                self.warnings.append(warning)
        
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
            error_msg += "\n".join(f" - {err}" for err in validation_errors)
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
            # Use feather_id as the primary identifier for engine consistency
            consistent_feather_id = feather_ref.feather_id or feather_ref.feather_config_name
            
            # Map tier: ensure minimum of 1 if weighted scoring tier is not set or 0
            tier_val = getattr(feather_ref, 'tier', 1)
            if tier_val == 0:
                tier_val = 1
                
            feather_spec = FeatherSpec(
                feather_id=consistent_feather_id,
                database_filename=feather_ref.feather_database_path,
                artifact_type=feather_ref.artifact_type,
                detection_confidence="high",
                manually_overridden=False,
                # Preserve the original config-name from the wing JSON so
                # the engine's per-feather lookups (e.g. source_timezone)
                # can resolve via feather_config_name when feather_id is a
                # short alias like "prefetch" that doesn't appear in the
                # pipeline's FeatherConfig map.
                feather_config_name=getattr(feather_ref, 'feather_config_name', None),
                weight=getattr(feather_ref, 'weight', 0.0),
                tier=tier_val,
                tier_name=getattr(feather_ref, 'tier_name', "")
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
        
        # Set scoring parameters
        wing.use_weighted_scoring = getattr(wing_config, 'use_weighted_scoring', True)
        wing.scoring = getattr(wing_config, 'scoring', {})
        
        return wing
    
    def _lookup_run_group_id(self, execution_id: int) -> Optional[str]:
        """Read the run_group_id stored on an existing execution row
        (used when resuming, so the resumed wing rejoins its run group)."""
        try:
            db_file = Path(self.config.output_directory) / "correlation_results.db"
            if not db_file.exists():
                return None
            import sqlite3
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(executions)")
                if 'run_group_id' not in {row[1] for row in cursor.fetchall()}:
                    return None
                cursor.execute(
                    "SELECT run_group_id FROM executions WHERE execution_id = ?",
                    (execution_id,)
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            finally:
                conn.close()
        except Exception as e:
            print(f"[Pipeline] Could not look up run_group_id for resume: {e}")
            return None

    def _reconcile_identity_wing(self, execution_id: Optional[int]) -> None:
        """Merge a finished wing's identities into the per-run identity
        registry (identity engine only). Non-fatal: reconciliation failures
        become warnings, never break the run."""
        if not execution_id or not self.config.output_directory:
            return
        if self.config.engine_type != 'identity_based':
            return
        try:
            from ..engine.identity_run_reconciler import reconcile_wing
            db_file = Path(self.config.output_directory) / "correlation_results.db"
            stats = reconcile_wing(
                str(db_file),
                getattr(self.config, 'run_group_id', None),
                execution_id
            )
            print(f"[Pipeline] Identity run registry updated: {stats}")
        except Exception as e:
            warning = f"Identity reconciliation failed (non-fatal): {e}"
            self.warnings.append(warning)
            print(f"[Pipeline] WARNING: {warning}")

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
                print(" [WARN] WARNING: No output directory set, results will not be saved!")
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
                print(f"\n Finalizing streaming results...")
                print(f" " + "=" * 60)
                print(f" [OK] Matches already saved via streaming mode")
                
                # Write each result row from the finished CorrelationResult
                # before rolling the totals up.
                #
                # This branch used to call update_execution_stats alone, so the
                # result row kept whatever the engine wrote mid-run: duration 0,
                # every feather's matches_created 0, no records scanned, no
                # anchor. The Summary tab reads that row, so it showed
                # "Time: 0.00s" on a 749-second run and drew empty charts.
                # save_result's streamed branch exists for exactly this - it
                # UPDATEs the streamed row and skips re-writing matches that are
                # already in the database.
                with ResultsDatabase(str(db_file)) as db:
                    for r in self.results:
                        try:
                            db.save_result(execution_id, r)
                        except Exception as e:
                            warning = (f"Could not finalize result row for wing "
                                       f"'{getattr(r, 'wing_name', '?')}': {e}")
                            self.warnings.append(warning)
                            print(f"[Pipeline] WARNING: {warning}")

                # Update execution record with final statistics. Its totals are
                # derived from the result rows, so this must run after they are
                # correct.
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
                print(f"\n Saving results to database...")
                print(f" " + "=" * 60)
                
                # DEBUG: Verify matches before saving
                print(f"[Pipeline] DEBUG: Saving {len(self.results)} result(s) to database")
                for i, r in enumerate(self.results):
                    print(f"[Pipeline] DEBUG: Result {i+1}: {r.wing_name} - {len(r.matches)} matches")
                
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
                        identity_filters=self.config.identity_filters,
                        run_group_id=getattr(self.config, 'run_group_id', None)
                    )

            # Cross-wing identity reconciliation (identity engine only).
            # Streaming runs already reconciled per wing in _execute_wings;
            # this covers the non-streaming path and is idempotent otherwise.
            self._reconcile_identity_wing(execution_id)

            # Get run name from database for display
            with ResultsDatabase(str(db_file)) as db:
                exec_metadata = db.get_execution_metadata(execution_id)
                run_name = exec_metadata.get('run_name', f'Execution_{execution_id}') if exec_metadata else f'Execution_{execution_id}'
            
            print(f" " + "=" * 60)
            print(f" [OK] Results saved to database: {db_file.name}")
            print(f" [OK] Execution ID: {execution_id}")
            print(f" [OK] Run Name: {run_name}")
            print(f" [OK] Total matches: {sum(r.total_matches for r in self.results):,}")
            print(f" [OK] Wings executed: {len(self.results)}")
            print(f" Database location: {db_file.absolute()}")
            print(f" Tables: executions, results, matches")
            
            return execution_id
            
        except Exception as e:
            error_msg = f"Failed to generate report: {str(e)}"
            self.errors.append(error_msg)
            print(f" [FAIL] Error: {str(e)}")
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
    
    def request_cancellation(self, reason: str = "User requested cancellation"):
        """
        Request cancellation of the current execution (Requirement 8.2).
        This sets the cancellation flag that is checked regularly during execution.
        
        Args:
            reason: Reason for cancellation (for logging)
        """
        print(f"\n[WARN] Cancellation requested: {reason}")
        self._cancelled = True
        
        # Also propagate to the engine if it supports cancellation
        if hasattr(self.engine, '_cancelled'):
            self.engine._cancelled = True
        if hasattr(self.engine, 'request_cancellation'):
            self.engine.request_cancellation(reason)
