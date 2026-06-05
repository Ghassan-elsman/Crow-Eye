"""
Context Manager for EYE AI Forensic Assistant.

This module is the "Heart" of the EYE Assistant. It serves as the primary 
coordination layer between the Chat UI (bridge) and all specialized forensic 
services. 

ARCHITECTURE:
The ContextManager follows a 'Mediator' pattern. Instead of services talking 
to each other directly, they communicate through this manager. This ensures 
that the forensic state (history, database access, case info) is unified 
and consistent.

SUB-SERVICES:
- QueryProcessor: Manages the 'thinking' steps.
- HistoryManager: Handles conversation persistence.
- ForensicHandlers: Maps AI tool requests to Python logic.
- ModelRouter: Routes prompts to the correct AI backend.

"""

import logging
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

# Core AI & Database Services
from eye.services.model_router import ModelRouter
from eye.services.database_service import ForensicDatabaseService
from eye.services.search_service import ForensicSearchService
from eye.services.rag_service import RAGService
from eye.services.report_engine import ReportEngine
from eye.services.token_counter import TokenCounter
from eye.services.context_window_registry import resolve_context_window
from eye.services.correlation_service import CorrelationService
from eye.services.case_context_manager import CaseContextManager

# Specialized Logic Modules
from eye.services.forensic_handlers import ForensicHandlers
from eye.services.report_handlers import ReportHandlers
from eye.services.correlation_config_handlers import CorrelationConfigHandlers
from eye.services.history_manager import HistoryManager
from eye.services.intent_engine import IntentEngine
from eye.services.query_processor import QueryProcessor
from eye.services.internet_search_service import InternetSearchService
from eye.services.threat_intel_service import ThreatIntelService

# Evidence Preservation Services
from eye.services.evidence_detector import EvidenceDetector
from eye.services.truncation_auditor import TruncationAuditor
from eye.services.evidence_seal import EvidenceSeal

class ContextManager:
    """
    Main Orchestrator for Forensic Intelligence.
    
    This class manages the lifecycle of an investigation session, ensuring 
    that the AI has the correct context, tools, and history to answer 
    forensic queries accurately.
    """
    
    def __init__(
        self,
        model_router: ModelRouter,
        database_service: ForensicDatabaseService,
        search_service: ForensicSearchService,
        rag_service: RAGService,
        report_engine: ReportEngine,
        case_directory: Optional[str] = None,
        case_context_manager: Optional[CaseContextManager] = None
    ):
        """
        Initializes the forensic state and wires up all sub-services.
        
        Args:
            model_router: Handles AI generation.
            database_service: Access to forensic SQL databases.
            search_service: Access to file search indices.
            rag_service: Access to the forensic knowledge base.
            report_engine: Handles report generation.
            case_directory: Path to the active Crow-Eye case.
            case_context_manager: Optional existing case context manager.
        """
        self.model_router = model_router
        self.database_service = database_service
        # Cache for the always-injected database manifest (built lazily in
        # _build_database_manifest; the case's DB set is fixed for our lifetime).
        self._db_manifest_cache = None
        # TTL cache for the pre-flight connectivity ping (see _validate_connectivity_cached).
        self._connectivity_cache = None
        self.search_service = search_service
        self.rag_service = rag_service
        self.report_engine = report_engine
        self.case_directory = case_directory
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Thread lock for process_query to prevent race conditions during history updates
        self._lock = threading.RLock()

        # --- Specialized Sub-Services ---
        self.correlation_service = CorrelationService(case_directory) if case_directory else None
        self.case_context_manager = case_context_manager or (CaseContextManager(case_directory) if case_directory else None)
        self.internet_search_service = InternetSearchService()
        self.threat_intel_service = ThreatIntelService()
        
        # Evidence Preservation Services 
        self.evidence_detector = EvidenceDetector()
        
        # Initialize standardized logs directory (EYE_Logs)
        if case_directory:
            self.logs_dir = Path(case_directory) / "EYE_Logs"
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            try:
                self.truncation_auditor = TruncationAuditor(case_directory)
                self.logger.info("Truncation auditor initialized successfully in EYE_Logs")
            except Exception as e:
                self.logger.error(f"Failed to initialize truncation auditor: {e}")
                self.truncation_auditor = None
        else:
            self.truncation_auditor = None
            self.logger.info(
                "No case directory provided. Audit trail and pinning features disabled."
            )

        # Single persistent evidence-seal writer for this case. Constructing one
        # per turn (the old behavior) re-read the hash chain from disk every turn
        # and, worse, let two writers (query loop + map-reduce) on the same case
        # dir fork the chain. One writer per ContextManager/case fixes both. It
        # no-ops safely when there is no case_directory.
        try:
            self.evidence_seal = EvidenceSeal(case_directory)
        except Exception as e:
            self.logger.error(f"Failed to initialize evidence seal: {e}")
            self.evidence_seal = EvidenceSeal(None)

        # Token counting for prompt optimization
        backend = self.model_router.config.get("backend", "gemini")
        self.token_counter = TokenCounter(backend)
        
        # Load configuration settings 
        config = self._load_evidence_preservation_config()
        
        # Adaptive context window: size max_total_tokens to the active backend
        # model's real context window (cloud models via the registry; local
        # servers stay on their runtime n_ctx probe). The configured value is
        # the fallback for unknown models, and `lock_max_total_tokens` forces
        # the configured value verbatim when an investigator wants a fixed cap.
        self.lock_max_total_tokens = config.get("lock_max_total_tokens", False)
        # The configured value is the fallback for unknown models; kept so model
        # switches fall back to it (not to the previous model's larger window).
        self.default_max_total_tokens = config.get("max_total_tokens", 64000)
        self.max_total_tokens = self._resolve_context_window(self.default_max_total_tokens)

        # Token budget: per-component sub-allocations used during prompt
        # assembly. These scale with the resolved window so history / tool
        # results / RAG grow on a larger backend instead of staying pinned at
        # the old fixed caps — UNLESS the investigator pinned an explicit
        # token_budget in eye_config.json, which is then honored verbatim.
        self._token_budget_explicit = config.get("token_budget_explicit", False)
        if self._token_budget_explicit:
            self.token_budget = config.get("token_budget")
        else:
            self.token_budget = self._scale_token_budget(self.max_total_tokens)

        self.max_tool_output_chars = config.get("max_tool_output_chars", 100000)
        self.truncation_count = 0

        # Apply sealed-payload persistence config to the seal writer (built above,
        # before config was loaded). Re-seed the recency window if N changed.
        try:
            self.evidence_seal.store_full_payload = config.get("store_full_payload", True)
            n = int(config.get("sealed_payload_recent_uncompressed", 10))
            if n != self.evidence_seal._recent_uncompressed:
                self.evidence_seal._recent_uncompressed = n
                self.evidence_seal._seed_recent_payloads()
        except Exception as e:
            self.logger.warning(f"Could not apply sealed-payload config: {e}")
        
        # Evidence preservation configuration. Only confidence_threshold is
        # consumed (history_manager evidence auto-preservation gate).
        self.evidence_preservation_config = config.get("evidence_preservation", {
            "confidence_threshold": 0.7
        })

        # --- Modular Components ---
        # We delegate specific logic to these handlers to keep ContextManager clean
        self.history_manager = HistoryManager(self)
        self.intent_engine = IntentEngine()
        self.forensic_handlers = ForensicHandlers(self)
        self.report_handlers = ReportHandlers(self)
        # Correlation Engine authoring handlers — GEP-compliant write
        # actions for Wings and Semantic Mappings.
        self.correlation_config_handlers = CorrelationConfigHandlers(self)
        self.query_processor = QueryProcessor(self)
        
        # Dispatch table for AI Tool Calls
        self.tool_handlers = self._initialize_tool_handlers()
        
        # Load prompt templates and tool definitions from config
        self.llm_config = self._load_llm_config()
        
        if case_directory:
            self.history_manager.load_history()
            if self.report_engine:
                self.report_engine.load_report()
            
        self.logger.info("Forensic ContextManager initialized successfully.")

    @property
    def conversation_history(self):
        """Returns the active chat history list."""
        return self.history_manager.history

    @conversation_history.setter
    def conversation_history(self, value):
        self.history_manager.history = value

    def clear_conversation_history(self):
        """Wipes the current session history."""
        return self.history_manager.clear_history()

    def _load_llm_config(self) -> Dict[str, Any]:
        """Loads static prompts and tool JSON definitions from the filesystem."""
        app_root = Path(__file__).parent.parent.parent
        config_path = app_root / "configs" / "llm_config.json"
        try:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load LLM config: {e}")
        return {}
    
    def _load_evidence_preservation_config(self) -> Dict[str, Any]:
        """
        Load evidence preservation configuration from eye_config.json.
        
        Loads token budget, evidence preservation, and audit trail settings.
        Provides defaults if configuration is missing.
        
        Returns:
            Dictionary with configuration settings:
                - token_budget: Token allocation per component
                - max_total_tokens: Maximum total tokens
                - evidence_preservation: Evidence detection settings
                - audit_trail: Audit trail settings
        
        """
        app_root = Path(__file__).parent.parent.parent
        config_path = app_root / "configs" / "eye_config.json"
        
        # Default configuration
        default_config = {
            "max_total_tokens": 64000,
            "lock_max_total_tokens": False,
            "max_tool_output_chars": 100000,
            "token_budget": {
                "conversation_history": 8000,
                "system_prompt": 4000,
                "rag_context": 2000,
                "tool_results": 4000
            },
            # Whether the user pinned a token_budget; when False the budget is
            # scaled to the resolved context window instead of held fixed.
            "token_budget_explicit": False,
            # Persist the full sent payload per seal (independently reproducible
            # Compliance log); keep the most recent N uncompressed, compress older.
            "store_full_payload": True,
            "sealed_payload_recent_uncompressed": 10,
            "evidence_preservation": {
                "confidence_threshold": 0.7
            }
        }
        
        try:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    
                    # Extract context_window configuration if present
                    context_window = config.get("context_window", {})
                    
                    # Merge with defaults
                    result = {
                        "max_total_tokens": context_window.get("max_total_tokens", default_config["max_total_tokens"]),
                        "lock_max_total_tokens": context_window.get("lock_max_total_tokens", default_config["lock_max_total_tokens"]),
                        "max_tool_output_chars": context_window.get("max_tool_output_chars", default_config["max_tool_output_chars"]),
                        "token_budget": context_window.get("token_budget", default_config["token_budget"]),
                        "token_budget_explicit": "token_budget" in context_window,
                        "store_full_payload": context_window.get("store_full_payload", default_config["store_full_payload"]),
                        "sealed_payload_recent_uncompressed": context_window.get("sealed_payload_recent_uncompressed", default_config["sealed_payload_recent_uncompressed"]),
                        "evidence_preservation": context_window.get("evidence_preservation", default_config["evidence_preservation"])
                    }
                    
                    self.logger.info("Loaded evidence preservation configuration from eye_config.json")
                    return result
        except Exception as e:
            self.logger.warning(f"Failed to load evidence preservation config: {e}. Using defaults.")
        
        self.logger.info("Using default evidence preservation configuration")
        return default_config
    
    def log_performance_statistics(self):
        """
        Log performance statistics for evidence preservation features.
        
        Logs:
        - Evidence detection time with percentiles (p50, p95, p99)
        - Token counting time with percentiles
        - Audit trail write time with percentiles
        - Truncation event frequency
        - Preserved message ratio
        - Token budget utilization per component
        
        """
        # Evidence detection performance
        if hasattr(self, 'evidence_detector') and self.evidence_detector:
            stats = self.evidence_detector.get_performance_stats()
            self.logger.info(
                f"Evidence Detection Performance: "
                f"avg={stats['avg_detection_time_ms']:.2f}ms, "
                f"p50={stats['p50_detection_time_ms']:.2f}ms, "
                f"p95={stats['p95_detection_time_ms']:.2f}ms, "
                f"p99={stats['p99_detection_time_ms']:.2f}ms, "
                f"cache_hit_rate={stats['cache_hit_rate']:.1f}%, "
                f"total_detections={stats['total_detections']}"
            )
        
        # Token budget utilization
        if hasattr(self, 'history_manager') and self.history_manager:
            history_stats = self.history_manager.get_stats()
            total_tokens = history_stats.get("total_tokens", 0)
            budget = self.token_budget.get("conversation_history", 8000)
            utilization = (total_tokens / budget * 100) if budget > 0 else 0
            
            self.logger.info(
                f"Token Budget Utilization: "
                f"conversation_history={total_tokens}/{budget} ({utilization:.1f}%), "
                f"truncation_count={self.truncation_count}"
            )
        
        # Preserved message ratio
        if hasattr(self, 'history_manager') and self.history_manager:
            total_messages = len(self.history_manager.history)
            preserved_count = sum(
                1 for msg in self.history_manager.history
                if msg.get("metadata", {}).get("preserve_evidence") or msg.get("metadata", {}).get("pinned")
            )
            preserved_ratio = (preserved_count / total_messages * 100) if total_messages > 0 else 0
            
            self.logger.info(
                f"Message Preservation: "
                f"preserved={preserved_count}/{total_messages} ({preserved_ratio:.1f}%)"
            )
        
        # Audit trail statistics
        if hasattr(self, 'truncation_auditor') and self.truncation_auditor:
            audit_summary = self.truncation_auditor.get_audit_summary()
            self.logger.info(
                f"Audit Trail: "
                f"total_events={audit_summary['total_events']}, "
                f"summarized={audit_summary['summarized_count']}, "
                f"preserved={audit_summary['preserved_count']}, "
                f"pinned={audit_summary['pinned_count']}, "
                f"chain_of_custody_at_risk={audit_summary['chain_of_custody_at_risk']}"
            )


    def _initialize_tool_handlers(self) -> Dict[str, Callable]:
        """
        Maps tool names (as seen by the AI) to their Python handler methods.
        This provides a secure, explicit boundary for AI tool execution.
        """
        f = self.forensic_handlers
        r = self.report_handlers
        c = self.correlation_config_handlers
        return {
            # Investigative Tools
            "query_database": f.handle_query_database,
            "analyze_large_dataset": f.handle_analyze_large_dataset,
            "get_schema": f.handle_get_schema,
            "search_artifacts": f.handle_search_artifacts,
            "query_correlation_results": f.handle_query_correlation_results,
            "list_case_files": f.handle_list_case_files,
            "internet_search": f.handle_internet_search,
            "fetch_web_content": f.handle_fetch_web_content,
            "switch_model": f.handle_switch_model,
            "query_living_off_the_land_intel": f.handle_query_living_off_the_land_intel,
            "query_threat_intel": f.handle_query_threat_intel,

            # Evidence Reporting Tools
            "report_add_chat_transcript": r.handle_report_add_chat_transcript,
            "report_add_chart": r.handle_report_add_chart,
            "report_add_timeline": r.handle_report_add_timeline,
            "report_add_heatmap": r.handle_report_add_heatmap,
            "report_add_chain_of_custody": r.handle_report_add_chain_of_custody,
            "report_append_section": r.handle_report_append_section,
            "report_add_data_table": r.handle_report_add_data_table,
            "report_add_image": r.handle_report_add_image,
            "report_edit_section": r.handle_report_edit_section,
            "report_delete_section": r.handle_report_delete_section,
            "export_report": r.handle_export_report,

            # Correlation Engine Authoring Tools (GEP-compliant write
            # actions). EYE has create+edit scope on items it authored
            # itself (eye_authorship.created_by starts with "eye");
            # built-in and human-authored items remain read-only.
            "correlation_create_wing":             c.handle_correlation_create_wing,
            "correlation_edit_wing":               c.handle_correlation_edit_wing,
            "correlation_create_semantic_mapping": c.handle_correlation_create_semantic_mapping,
            "correlation_edit_semantic_mapping":   c.handle_correlation_edit_semantic_mapping,
        }
    # Connectivity is re-checked at most once per this many seconds, so a burst
    # of queries doesn't trigger a network round-trip (and, for local CLI
    # backends, a list_models call) on every single turn.
    _CONNECTIVITY_TTL_SECONDS = 60

    def _validate_connectivity_cached(self) -> bool:
        """Pre-flight connectivity check with a short TTL cache.

        Only a *positive* result is cached (keyed by backend+model), so a healthy
        backend isn't re-pinged on every query, while a failure is always
        re-checked next turn. A model/backend switch changes the key and forces a
        fresh check. Stale-but-down backends still surface: the actual model call
        fails and is handled downstream.
        """
        now = time.time()
        cfg = getattr(self.model_router, "config", {}) or {}
        key = (cfg.get("backend"), cfg.get("model_name"))
        cache = getattr(self, "_connectivity_cache", None)
        if (cache and cache.get("ok") and cache.get("key") == key
                and (now - cache.get("ts", 0)) < self._CONNECTIVITY_TTL_SECONDS):
            return True
        ok = self.model_router.validate_connectivity()
        self._connectivity_cache = {"key": key, "ok": bool(ok), "ts": now}
        return ok

    def process_query(self, query: str, status_callback=None, hitl_callback=None, report_callback=None, dialogue_callback=None):
        """
        Entry point for investigative queries.
        Ensures thread safety and delegates to the QueryProcessor.

        GEP Rule 1 (Pre-Flight Integrity): every query is gated by a
        validate_connectivity() call on the active LLM backend.  If the backend
        is unreachable we return a structured error envelope so the chat
        renders a "Backend unreachable" bubble instead of hanging silently.
        The check is TTL-cached so a burst of queries doesn't re-ping every turn.
        """
        # ---- GEP Rule 1: Pre-Flight Ping (TTL-cached) -------------------
        try:
            ok = self._validate_connectivity_cached()
            ping_err = None
        except Exception as e:
            ok = False
            ping_err = str(e)
        if not ok:
            if status_callback:
                try:
                    status_callback(json.dumps({
                        "step_id": f"ping-{int(time.time() * 1000)}",
                        "type": "thinking",
                        "status": "error",
                        "label": "Pre-flight ping failed",
                        "detail": ping_err or "Backend unreachable"
                    }))
                except Exception:
                    pass  # status_callback is best-effort; never block the error return
            return {
                "success": False,
                "error": "Backend unreachable",
                "data": {
                    "response": f"Backend unreachable: {ping_err or 'no response from LLM backend'}"
                }
            }
        # -----------------------------------------------------------------

        with self._lock:
            return self.query_processor.process_query(
                query, status_callback, hitl_callback, report_callback, dialogue_callback
            )

    def _resolve_context_window(self, fallback: int = 64000) -> int:
        """Resolve the effective ``max_total_tokens`` for the active backend model.

        Precedence (the limit's *source* is the backend wherever possible):
        1. **Live backend introspection** — the model's real window reported by
           the backend itself (Gemini ``input_token_limit``; Ollama/LM Studio
           model info). This is the authoritative source when available.
        2. **Static registry** — known windows for cloud APIs that do NOT expose
           it (Anthropic 200K, OpenAI 128K, ...).
        3. **Fallback** — the configured default (64K) for unknown models.

        Local servers also keep their runtime ``n_ctx`` probe, which still
        overrides downward at call time if a model was loaded with a smaller
        window than it was trained for. Set
        ``context_window.lock_max_total_tokens: true`` to pin the configured
        value verbatim and disable all auto-resolution.
        """
        if getattr(self, "lock_max_total_tokens", False):
            return fallback
        try:
            backend = self.model_router.config.get("backend")
            model_name = self.model_router.config.get("model_name")

            # 1. Ask the backend for its real window (None if unsupported/failed).
            window = None
            try:
                window = self.model_router.get_context_window()
            except Exception as probe_exc:
                self.logger.debug(f"Backend context-window introspection failed: {probe_exc}")
            source = "backend"

            # 2. Fall back to the static registry for non-reporting cloud APIs.
            if not window:
                window = resolve_context_window(backend, model_name)
                source = "registry"

            if window:
                if window != fallback:
                    self.logger.info(
                        f"Adaptive context window: using {window:,} tokens for model "
                        f"'{model_name}' (backend '{backend}', source={source}); "
                        f"configured fallback was {fallback:,}."
                    )
                return window
        except Exception as e:
            self.logger.warning(
                f"Context window resolution failed ({e}); using fallback {fallback:,}."
            )
        return fallback

    def usable_context_tokens(self) -> int:
        """The token budget actually usable for an outgoing payload / persistent
        history: the resolved context window minus a ~10% output reserve (min
        512, capped at half the window so a tiny window can't drive this <= 0).

        Single source of truth shared by ``guarded_generate`` (the per-call
        outgoing gate) and ``HistoryManager.manage_history`` (persistent
        compaction), so both layers agree on the same window.
        """
        max_ctx = int(getattr(self, "max_total_tokens", 8192) or 8192)
        reserve = min(max(512, int(max_ctx * 0.1)), max(1, max_ctx // 2))
        return max_ctx - reserve

    # Historical default proportions (8k/4k/4k/2k of an 18k budget),
    # normalized to 1.0 — history-heaviest because conversation history and
    # tool results carry the evidence; RAG is the most compressible.
    _TOKEN_BUDGET_WEIGHTS = {
        "conversation_history": 0.45,
        "system_prompt": 0.22,
        "tool_results": 0.22,
        "rag_context": 0.11,
    }

    def _scale_token_budget(self, max_total_tokens: int) -> Dict[str, int]:
        """Scale the per-component token sub-budgets to a context window.

        Keeps the historical relative proportions (see ``_TOKEN_BUDGET_WEIGHTS``)
        but grows every component with the window, so a large backend actually
        uses its capacity instead of being pinned at the old fixed caps. A ~10%
        response reserve is held back first (mirroring ``guarded_generate``)
        before the remainder is split.
        """
        try:
            mt = int(max_total_tokens)
        except (TypeError, ValueError):
            mt = self.default_max_total_tokens
        mt = max(mt, 1000)
        reserve = min(max(512, int(mt * 0.1)), max(1, mt // 2))
        available = max(mt - reserve, len(self._TOKEN_BUDGET_WEIGHTS))
        return {
            component: max(1, int(available * weight))
            for component, weight in self._TOKEN_BUDGET_WEIGHTS.items()
        }

    def _resolve_token_budget(self) -> Dict[str, int]:
        """Budget for the current window: explicit config wins, else scaled.

        Used on model switch to re-size the budget to the newly resolved
        ``max_total_tokens`` without clobbering an investigator's pinned budget.
        """
        if getattr(self, "_token_budget_explicit", False):
            return dict(self.token_budget)
        return self._scale_token_budget(self.max_total_tokens)

    def _build_database_manifest(self, max_tables_per_db: int = 12, max_cols_per_table: int = 24) -> str:
        """Compact, always-present schema map of the case's forensic databases —
        their real tables AND columns.

        Sourced from ``database_service.discover_databases()`` (the DB + table
        set) and ``database_service.get_schema()`` (the real column names, thread-
        safe + cached). Injected into every system prompt so the model writes SQL
        grounded in the actual schema instead of inventing identifiers (the root
        cause of repeated ``no such column`` / ``no such table`` errors, e.g.
        ``last_run_time`` instead of ``last_executed``, or the DB name
        ``registry_data`` used as a table). Per-table columns are capped (with a
        ``+N more`` hint) to stay within the system-prompt budget.

        Cached for the ContextManager's lifetime (the case's database set does
        not change mid-session — the Eye queries databases but does not create
        them; a new ContextManager is built when the case changes).
        """
        if getattr(self, "_db_manifest_cache", None) is not None:
            return self._db_manifest_cache

        manifest = ""
        try:
            if self.database_service:
                dbs = self.database_service.discover_databases()
                accessible = [d for d in dbs if d.get("accessible") and d.get("exists")]
                if accessible:
                    lines = [
                        "## Available Case Databases (real schema)",
                        "These are the forensic databases present in THIS case, with their "
                        "REAL tables and columns. Write SQL using ONLY these exact table and "
                        "column names — do NOT invent identifiers (no guessing column names, "
                        "and never use a database's filename as a table name). If you need a "
                        "column that is not listed, call get_schema for that database first. "
                        "Query every database relevant to the question (Amcache, Registry, "
                        "Prefetch, ShimCache, SRUM, MFT) — do NOT assume only the MFT.",
                    ]
                    for d in sorted(accessible, key=lambda x: ((x.get("category") or ""), (x.get("name") or ""))):
                        name = d.get("name")
                        category = d.get("category") or "Artifact"
                        tables = d.get("tables") or []

                        # Pull the real column schema (cached). Fall back to
                        # table-names-only for this DB if the fetch fails.
                        schema = {}
                        try:
                            res = self.database_service.get_schema(name)
                            if res and res.get("success"):
                                schema = res.get("schema") or {}
                        except Exception:
                            schema = {}

                        lines.append(f"- **{name}** ({category})")
                        for tbl in tables[:max_tables_per_db]:
                            cols = schema.get(tbl) or []
                            if cols:
                                shown_cols = ", ".join(cols[:max_cols_per_table])
                                if len(cols) > max_cols_per_table:
                                    shown_cols += f", +{len(cols) - max_cols_per_table} more"
                                lines.append(f"    - {tbl}({shown_cols})")
                            else:
                                lines.append(f"    - {tbl}")
                        if len(tables) > max_tables_per_db:
                            lines.append(f"    - ... (+{len(tables) - max_tables_per_db} more tables)")
                    manifest = "\n".join(lines)
        except Exception as e:
            self.logger.warning(f"Failed to build database manifest: {e}")
            manifest = ""

        self._db_manifest_cache = manifest
        return manifest

    def update_context_config(self, new_config: Dict[str, Any]) -> None:
        """
        Applies a new context window configuration to the context manager at runtime.
        """
        self.max_total_tokens = new_config.get("max_total_tokens", self.max_total_tokens)
        self.max_tool_output_chars = new_config.get("max_tool_output_chars", self.max_tool_output_chars)
        self.token_budget = new_config.get("token_budget", self.token_budget)
        
        if "evidence_preservation" in new_config:
            self.evidence_preservation_config = new_config["evidence_preservation"]

        self.logger.info("Context configuration updated successfully at runtime.")

    def _execute_tool(self, call: Dict, hitl_callback=None) -> Dict:
        """
        Internal dispatcher that routes a parsed tool call to its handler.
        """
        name = call.get("name")
        params = call.get("parameters", {})
        if name not in self.tool_handlers:
            return {"tool_name": name, "success": False, "error": f"Tool '{name}' is not recognized."}
        try:
            handler = self.tool_handlers[name]
            # Handlers are responsible for their own error handling and parameter validation
            result = handler(params)
            return {"tool_name": name, "success": True, "result": result}
        except Exception as e:
            self.logger.error(f"Tool execution failed [{name}]: {e}")
            return {"tool_name": name, "success": False, "error": str(e)}

    def _build_system_prompt(self, rag_context: str, history: List[Dict]) -> str:
        """
        Dynamically constructs the Master System Prompt with priority-based truncation.
        Ensures Core Identity and Tools are preserved while optional context is truncated.
        """
        # Calculate budget for optional parts
        budget_config = self.token_budget.get("system_prompt", 4000)
        # If the total model context is small, we must be extremely aggressive
        is_constrained = self.max_total_tokens <= 8192
        
        # 1. CORE IDENTITY (Priority 1: MUST KEEP)
        core_identity = self.llm_config.get("system_prompt_template", ["# EYE Forensic Assistant"])
        
        # For constrained models, keep only the most vital rules to save tokens
        if is_constrained and len(core_identity) > 15:
             # Keep headers and the first 10 rules + last 2 rules
             core_identity = core_identity[:12] + ["... [Forensic Protocols active] ..."] + core_identity[-3:]
             
        core_str = "\n".join(core_identity)
        
        # 2. CASE CONTEXT (Priority 1: MUST KEEP)
        if self.case_context_manager:
            case_info = self.case_context_manager.get_context_for_prompt()
            # Truncate case info if it's too long for a constrained model
            if is_constrained and len(case_info) > 1000:
                 case_info = case_info[:1000] + "... [TRUNCATED]"
            core_str += f"\n\n## Case Context\n{case_info}"

        # 2b. AVAILABLE CASE DATABASES (Priority 1: MUST KEEP)
        # Always list the databases that actually exist in THIS case so the model
        # never has to guess which to query — the root cause of it hitting only
        # the MFT for questions like "does the computer have games" when the
        # answer lives in Amcache / Prefetch / ShimCache / SRUM / Registry.
        # Sourced from discover_databases(), independent of RAG semantic retrieval.
        db_manifest = self._build_database_manifest(
            max_tables_per_db=6 if is_constrained else 12,
            max_cols_per_table=12 if is_constrained else 24,
        )
        if db_manifest:
            core_str += "\n\n" + db_manifest

        # 3. TOOLS (Priority 1: MUST KEEP)
        tool_defs = self._get_tool_definitions()
        # For small context models, we skip the text summary of tools because
        # they are already provided in the JSON 'tools' field of the API call.
        if not is_constrained:
            tools_list = ["\n## Available Tools", "You have access to the following forensic tools:"]
            for tool in tool_defs:
                tools_list.append(f"- **{tool['name']}**: {tool.get('description', '')}")
            core_str += "\n" + "\n".join(tools_list)
        else:
            core_str += "\n\n## Tools\n(Forensic tools are available via function calling)"

        # 3b. REPORT TOOLS QUICK REFERENCE — concrete invocation examples for the
        # report_* tools. The AI was falling back to inline markdown tables in chat
        # because the one-line descriptions did not show the shape it needed to call.
        # Always include this block (compact); it pays for itself by preventing
        # wasted-tokens chat tables that then have to be re-extracted by the user.
        core_str += "\n" + self._build_report_tools_quick_reference(tool_defs)

        # 3c. LARGE-RESULT (TOON) COMPRESSION DOCS — teach the model that
        # query_database results over the threshold arrive as a SAMPLE and how to
        # get the full set. Compact; always included so the model never treats a
        # compressed sample as the complete answer.
        toon_docs = self.llm_config.get("toon_compression_docs", [])
        if toon_docs:
            core_str += "\n\n" + "\n".join(toon_docs)

        core_tokens = self.token_counter.count_tokens(core_str)
        
        # Safety margin for separators and model overhead
        remaining_budget = budget_config - core_tokens - 100
        
        # 4. OPTIONAL CONTEXT (Priority 2: TRUNCATABLE)
        optional_parts = []
        
        # A. Situation Awareness (Pinned Evidence & Report Summary)
        situation_awareness = ["\n## Forensic Situation Awareness"]
        pinned = [m for m in history if m.get("metadata", {}).get("pinned") or m.get("metadata", {}).get("preserve_evidence")]
        if pinned:
            situation_awareness.append("### CRITICAL PINNED EVIDENCE")
            for m in pinned:
                ts = m.get("timestamp", "N/A")
                content = m.get("content", "")
                # Truncate individual pinned items to keep summary concise
                clean_content = (content[:500] + "...") if len(content) > 500 else content
                situation_awareness.append(f"- [{ts}] {clean_content}")
        
        if self.report_engine and self.report_engine.blocks:
            situation_awareness.append("### Living Report State")
            for block in self.report_engine.blocks:
                author = block.metadata.get("author", "unknown")
                block_title = getattr(block, "title", None) or getattr(block, "caption", block.block_type.title())
                situation_awareness.append(f"- **ID: {block.block_id}** | Type: {block.block_type} | Title: {block_title} (By: {author})")
        
        if len(situation_awareness) > 1:
            optional_parts.append("\n".join(situation_awareness))
            
        # B. RAG Knowledge (Last priority for truncation)
        if rag_context:
            optional_parts.append(f"\n## Artifact Technical Knowledge\n{rag_context}")
        else:
            optional_parts.append("\n## Artifact Technical Knowledge\n(Use your internal forensic knowledge for standard Windows artifacts)")

        # Combine optional parts - we put Situation Awareness FIRST so it survives longer
        # if the total exceeds budget and truncate_text cuts from the end.
        optional_str = "\n\n".join(optional_parts)
        
        if remaining_budget > 0:
            optional_tokens = self.token_counter.count_tokens(optional_str)
            if optional_tokens > remaining_budget:
                self.logger.warning(f"Optional context exceeds budget. Truncating RAG/Situation Awareness.")
                # Chain of custody: record the (non-evidence) trim so it is
                # visible in the Compliance "Chain-of-Custody Events" section
                # rather than being silently dropped.
                auditor = getattr(self, "truncation_auditor", None)
                if auditor:
                    try:
                        import hashlib as _hl
                        dropped_tail = optional_str[remaining_budget * 4:]
                        auditor.log_event(
                            action="TRUNCATED",
                            message_id="system_prompt_optional",
                            token_count=optional_tokens,
                            reason="system_prompt_optional_context_budget",
                            message_hash=_hl.sha256(dropped_tail.encode("utf-8", errors="replace")).hexdigest()[:16],
                            metadata={"budget": remaining_budget, "kind": "rag_and_situation_awareness", "cut_content": dropped_tail},
                        )
                    except Exception:
                        pass
                optional_str = self.token_counter.truncate_text(optional_str, remaining_budget)
            return core_str + "\n\n" + optional_str
        else:
            # Extreme case: Core is already too big (unlikely with 4k budget).
            # (Fixes a latent NameError — this branch referenced an undefined
            # `max_tokens`; the correct cap is the system-prompt budget.)
            self.logger.error("Core identity and tools exceed system prompt budget! Emergency truncation active.")
            auditor = getattr(self, "truncation_auditor", None)
            if auditor:
                try:
                    import hashlib as _hl
                    dropped_tail = core_str[budget_config * 4:]
                    auditor.log_event(
                        action="TRUNCATED",
                        message_id="system_prompt_core",
                        token_count=core_tokens,
                        reason="system_prompt_core_over_budget",
                        message_hash=_hl.sha256(dropped_tail.encode("utf-8", errors="replace")).hexdigest()[:16] if dropped_tail else "",
                        metadata={"budget": budget_config, "cut_content": dropped_tail},
                    )
                except Exception:
                    pass
            return self.token_counter.truncate_text(core_str, budget_config)

    def _build_report_tools_quick_reference(self, tool_defs: List[Dict]) -> str:
        """Concrete invocation examples for every `report_*` tool the model has
        access to. Injected into the system prompt so the LLM stops defaulting
        to inline markdown tables in chat when it should be calling a tool.

        Examples are derived from the actual schema in llm_config.json so they
        stay in sync if a schema changes — required parameters are listed
        explicitly and a minimal JSON example is included for each tool.
        """
        report_tool_names = {t.get("name") for t in tool_defs if (t.get("name") or "").startswith("report_")}
        if not report_tool_names:
            return ""

        # Hand-crafted minimal examples per tool. Each example only contains the
        # REQUIRED fields so the model copies the smallest valid shape; optional
        # fields are mentioned in prose so it knows they exist.
        examples = {
            "report_append_section": (
                "When to use: narrative findings, conclusions, interpretation. NEVER for raw rows.\n"
                'Call: {"title": "Anomalous RDP Activity 2024-03-12", '
                '"markdown_content": "Three failed RDP logons preceded the successful logon at 14:02 UTC. ..."}'
            ),
            "report_add_data_table": (
                "When to use: ANY tabular forensic evidence — query results, file listings, event rows, "
                "user enumerations. THIS IS THE TOOL TO USE INSTEAD OF PASTING A MARKDOWN TABLE IN CHAT.\n"
                'Call: {"sql_query": "SELECT EventTime, UserName, SourceIP FROM SecurityEvents WHERE EventID=4624", '
                '"columns": ["EventTime", "UserName", "SourceIP"], "database_name": "SecurityLogs.db"}\n'
                "The table is rendered interactively in the Report pane. database_name must be the actual DB filename you queried."
            ),
            "report_add_chart": (
                "When to use: distributions, comparisons, temporal patterns over discrete buckets.\n"
                'Call: {"title": "Failed Logons by Hour", "chart_type": "bar", '
                '"labels": ["00", "01", "02", "03"], '
                '"datasets": [{"label": "Failed", "data": [3, 1, 0, 7]}]}'
            ),
            "report_add_timeline": (
                "When to use: ordered chronology of events (executions, logons, file ops, network).\n"
                'Call: {"title": "Attacker Activity Timeline", '
                '"events": [{"timestamp": "2024-03-12T14:02:11Z", "label": "RDP Logon", '
                '"description": "Account: alice, IP: 10.0.0.5", "category": "Auth"}]}'
            ),
            "report_add_heatmap": (
                "When to use: 2D activity intensity (e.g., hour-of-day × day-of-week).\n"
                'Call: {"title": "Logon Activity Heatmap", "x_labels": ["Mon", "Tue"], '
                '"y_labels": ["09:00", "10:00"], "intensity_values": [[3, 5], [1, 2]]}'
            ),
            "report_add_image": (
                "When to use: screenshots, diagrams, exhibit images already on disk.\n"
                'Call: {"image_path": "C:/Cases/123/screenshots/desktop.png", "caption": "Desktop at time of acquisition"}'
            ),
            "report_add_chain_of_custody": (
                "When to use: documenting evidence handling for legal review.\n"
                'Call: {"entries": [{"evidence_id": "MFT-001", "handler_name": "Investigator", '
                '"action": "Analyzed", "timestamp": "2024-03-12T15:00:00Z"}]}'
            ),
            "report_add_chat_transcript": (
                "When to use: preserving important investigator↔AI dialogue verbatim in the report.\n"
                'Call: {"messages": [{"role": "user", "content": "What did this binary do?"}, '
                '{"role": "ai", "content": "It established persistence via Run key ..."}]}'
            ),
            "report_edit_section": (
                "When to use: amending a section you wrote earlier in this case. block_id comes from the Living Report State listing.\n"
                'Call: {"block_id": "blk_abc123", "new_content": "Updated narrative with new evidence."}'
            ),
            "report_delete_section": (
                "When to use: removing a stale/duplicate block. block_id from Living Report State.\n"
                'Call: {"block_id": "blk_abc123"}'
            ),
        }

        lines = [
            "## Report Tools — Quick Reference (USE THESE; DO NOT PASTE TABLES OR CHARTS IN CHAT)",
            "Per Rule 17 every evidence-bearing turn MUST produce BOTH a chat answer AND a `report_*` tool call.",
            "If you are about to format a markdown table in chat, STOP and call `report_add_data_table` instead.",
            "If you are about to describe a chart in chat, STOP and call `report_add_chart` instead.",
            "",
        ]
        for name in [
            "report_append_section",
            "report_add_data_table",
            "report_add_chart",
            "report_add_timeline",
            "report_add_heatmap",
            "report_add_image",
            "report_add_chain_of_custody",
            "report_add_chat_transcript",
            "report_edit_section",
            "report_delete_section",
        ]:
            if name not in report_tool_names:
                continue
            example = examples.get(name)
            if not example:
                continue
            lines.append(f"### `{name}`")
            lines.append(example)
            lines.append("")
        return "\n".join(lines).rstrip()

    def _get_tool_definitions(self) -> List[Dict]:
        """
        Returns the JSON tool definitions sent to the LLM.
        For constrained models, filters to only essential forensic tools.
        """
        all_tools = self.llm_config.get("tools", [])
        
        # If the model has plenty of space, send everything
        if self.max_total_tokens > 8192:
            return all_tools
            
        # Constrained Model: Keep only the essential forensic tools.
        # analyze_large_dataset is included BECAUSE this is the tight-context
        # case — it's the map-reduce path the guardrail hands off to when a
        # payload won't fit, so it must be offered exactly here.
        essential_names = [
            "query_database", "analyze_large_dataset", "search_artifacts", "get_schema",
            "report_append_section", "report_add_data_table", "report_add_chart",
            "query_correlation_results", "list_case_files"
        ]
        
        filtered = [t for t in all_tools if t.get("name") in essential_names]
        
        # If we didn't find any (config error?), return all as fallback
        return filtered if filtered else all_tools

    def _parse_tool_calls(self, response: Dict) -> List[Dict]:
        """
        Extracts and normalizes tool requests from varied AI backend response formats.
        """
        calls = []
        if "tool_calls" in response and response["tool_calls"]:
            for tc in response["tool_calls"]:
                if "function" in tc:
                    args = tc["function"].get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except:
                            args = {}
                    calls.append({"name": tc["function"]["name"], "parameters": args})
                    
        # Support for Anthropic format
        if "content" in response and isinstance(response["content"], list):
            for block in response["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({"name": block.get("name"), "parameters": block.get("input", {})})
                    
        return calls

    def get_context_stats(self):
        """
        Aggregates telemetry for the UI (token usage, model name, etc.).
        
        Includes information about feature availability for graceful degradation.
        """
        stats = self.history_manager.get_stats()
        stats.update({
            "backend": self.model_router.config.get("backend"),
            "model_name": self.model_router.config.get("model_name"),
            "features": {
                "evidence_detection": self.evidence_detector is not None,
                "audit_trail": self.truncation_auditor is not None,
                "pinning": self.truncation_auditor is not None,  # Pinning requires audit trail
                "case_directory_available": self.case_directory is not None
            }
        })
        
        # Add audit trail status if available
        if self.truncation_auditor:
            try:
                audit_summary = self.truncation_auditor.get_audit_summary()
                stats["audit_trail_status"] = {
                    "chain_of_custody_at_risk": audit_summary.get("chain_of_custody_at_risk", False),
                    "failed_writes_count": audit_summary.get("failed_writes_count", 0)
                }
            except Exception as e:
                self.logger.error(f"Failed to get audit trail status: {e}")
        
        return stats

    def _generate_action_chips(
        self,
        query: str,
        response: Dict[str, Any],
        tool_results: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """
        Proactively generates 'Action Chips' (UI buttons) based on the current state.
        
        Logic:
        - If correlation was mentioned, suggest correlation tools.
        - If database results were found, suggest exporting or reporting.
        """
        action_chips = []
        query_lower = query.lower()

        # 1. Check for explicit AI suggestions in the response
        if "action_chips" in response and isinstance(response["action_chips"], list):
            return response["action_chips"][:5]

        # 2. Pattern Matching in Query and Response
        ai_content = response.get("content", "").lower()
        
        # A. IP Intelligence Heuristic
        import re
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        if re.search(ip_pattern, ai_content):
            action_chips.append({"id": "ip_intel", "label": "Research IP Intel", "query": "Research the reputation and ownership of the IP addresses identified in your previous answer.", "icon": "language"})

        # B. Binary Analysis Heuristic
        if ".exe" in ai_content or ".sys" in ai_content or ".dll" in ai_content:
            action_chips.append({"id": "bin_intel", "label": "Analyze Binaries (LotL)", "query": "Use the Living Off the Land intelligence tool to analyze the binaries or drivers mentioned in your findings.", "icon": "policy"})

        # C. Remote Access Heuristic
        if "remote" in query_lower or "rdp" in query_lower or "ssh" in query_lower:
            action_chips.append({"id": "rdp_logs", "label": "Audit RDP Sessions", "query": "Query the RDP Operational logs and Security Event ID 10 logons to correlate the remote access activity.", "icon": "settings_remote"})

        # D. Suggest Correlation
        if "correlate" in query_lower or "correlation" in query_lower:
            action_chips.append({"id": "corr_engine", "label": "Use Correlation Engine", "query": "Query the Crow-eye Correlation Engine results.", "icon": "device_hub"})
            action_chips.append({"id": "corr_manual", "label": "Correlate Manually via SQL", "query": "Write custom SQL queries to manually correlate events.", "icon": "code"})

        # 3. Heuristic: Suggest Reporting if findings exist
        has_findings = any(
            r.get("success") and (
                r.get("result", {}).get("data") or 
                r.get("result", {}).get("rows") or 
                r.get("result", {}).get("files") or
                r.get("result", {}).get("matches") or
                r.get("result", {}).get("results") # Added for threat intel results
            ) for r in tool_results
        )

        if has_findings:
            action_chips.append({"id": "add_report", "label": "Add to Report", "query": "Add these forensic findings to my investigation report.", "icon": "document"})
            action_chips.append({"id": "export_csv", "label": "Export to CSV", "query": "Export the results to a CSV file.", "icon": "download"})

        return action_chips[:5]
    def _extract_data_viewer(self, tool_results):
        """
        Converts raw tool output into a structured format for the UI's Data Table viewer.
        """
        for r in tool_results:
            if r.get("success") and r.get("result"):
                res = r["result"]
                cols = res.get("columns", [])
                # Handle various backend data compression formats (TOON vs Raw)
                rows = res.get("full_rows") or res.get("data", []) or res.get("rows", [])
                if cols and rows:
                    return {
                        "columns": cols, "rows": rows, 
                        "database": res.get("database_name", "Forensic Result")
                    }
        return None
