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
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

# Core AI & Database Services
from eye.services.model_router import ModelRouter
from eye.services.database_service import ForensicDatabaseService
from eye.services.search_service import ForensicSearchService
from eye.services.rag_service import RAGService
from eye.services.report_engine import ReportEngine
from eye.services.token_counter import TokenCounter
from eye.services.correlation_service import CorrelationService
from eye.services.case_context_manager import CaseContextManager

# Specialized Logic Modules
from eye.services.forensic_handlers import ForensicHandlers
from eye.services.report_handlers import ReportHandlers
from eye.services.history_manager import HistoryManager
from eye.services.intent_engine import IntentEngine
from eye.services.query_processor import QueryProcessor
from eye.services.internet_search_service import InternetSearchService
from eye.services.threat_intel_service import ThreatIntelService

# Evidence Preservation Services
from eye.services.evidence_detector import EvidenceDetector
from eye.services.truncation_auditor import TruncationAuditor

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
        
        # Token counting for prompt optimization
        backend = self.model_router.config.get("backend", "gemini")
        self.token_counter = TokenCounter(backend)
        
        # Load configuration settings 
        config = self._load_evidence_preservation_config()
        
        # Token budget configuration
        self.token_budget = config.get("token_budget", {
            "conversation_history": 8000,
            "system_prompt": 4000,
            "rag_context": 2000,
            "tool_results": 4000
        })
        self.max_total_tokens = config.get("max_total_tokens", 32000)
        self.truncation_count = 0
        
        # Evidence preservation configuration
        self.evidence_preservation_config = config.get("evidence_preservation", {
            "enabled": True,
            "confidence_threshold": 0.7,
            "max_pinned_messages": 10,
            "auto_detect_evidence": True
        })
        
        # Audit trail configuration
        self.audit_trail_config = config.get("audit_trail", {
            "enabled": True,
            "buffer_size": 10,
            "export_format": "text"
        })

        # --- Modular Components ---
        # We delegate specific logic to these handlers to keep ContextManager clean
        self.history_manager = HistoryManager(self)
        self.intent_engine = IntentEngine()
        self.forensic_handlers = ForensicHandlers(self)
        self.report_handlers = ReportHandlers(self)
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
            "max_total_tokens": 32000,
            "token_budget": {
                "conversation_history": 8000,
                "system_prompt": 4000,
                "rag_context": 2000,
                "tool_results": 4000
            },
            "evidence_preservation": {
                "enabled": True,
                "confidence_threshold": 0.7,
                "max_pinned_messages": 10,
                "auto_detect_evidence": True
            },
            "audit_trail": {
                "enabled": True,
                "buffer_size": 10,
                "export_format": "text"
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
                        "token_budget": context_window.get("token_budget", default_config["token_budget"]),
                        "evidence_preservation": context_window.get("evidence_preservation", default_config["evidence_preservation"]),
                        "audit_trail": context_window.get("audit_trail", default_config["audit_trail"])
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
        return {
            # Investigative Tools
            "query_database": f.handle_query_database,
            "get_schema": f.handle_get_schema,
            "search_artifacts": f.handle_search_artifacts,
            "query_correlation_results": f.handle_query_correlation_results,
            "list_case_files": f.handle_list_case_files,
            "internet_search": f.handle_internet_search,
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
            "export_report": r.handle_export_report
            }
    def process_query(self, query: str, status_callback=None, hitl_callback=None, report_callback=None):
        """
        Entry point for investigative queries. 
        Ensures thread safety and delegates to the QueryProcessor.
        """
        with self._lock:
            return self.query_processor.process_query(query, status_callback, hitl_callback, report_callback)

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
            if self.token_counter.count_tokens(optional_str) > remaining_budget:
                self.logger.warning(f"Optional context exceeds budget. Truncating RAG/Situation Awareness.")
                optional_str = self.token_counter.truncate_text(optional_str, remaining_budget)
            return core_str + "\n\n" + optional_str
        else:
            # Extreme case: Core is already too big (unlikely with 4k budget)
            self.logger.error("Core identity and tools exceed system prompt budget! Emergency truncation active.")
            return self.token_counter.truncate_text(core_str, max_tokens)

    def _get_tool_definitions(self) -> List[Dict]:
        """
        Returns the JSON tool definitions sent to the LLM.
        For constrained models, filters to only essential forensic tools.
        """
        all_tools = self.llm_config.get("tools", [])
        
        # If the model has plenty of space, send everything
        if self.max_total_tokens > 8192:
            return all_tools
            
        # Constrained Model: Keep only the "Essential 8" forensic tools
        essential_names = [
            "query_database", "search_artifacts", "get_schema", 
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

    def _calculate_token_usage_per_component(self) -> Dict[str, int]:
        """
        Calculate token usage per component.
        
        Components:
        - system_prompt: Tokens used by system prompt
        - rag_context: Tokens used by RAG context
        - conversation_history: Tokens used by conversation history
        - tool_results: Tokens used by tool results in history
        
        Returns:
            Dictionary mapping component names to token counts
            
        """
        usage = {
            "system_prompt": 0,
            "rag_context": 0,
            "conversation_history": 0,
            "tool_results": 0
        }
        
        # Calculate conversation history tokens
        for msg in self.history_manager.history:
            # Check if token_count is explicitly stored
            if "token_count" in msg:
                token_count = msg["token_count"]
            elif "content" in msg:
                # Calculate if not stored
                token_count = self.token_counter.count_tokens(msg["content"])
            else:
                token_count = 0
            
            # Classify message type
            role = msg.get("role", "")
            if role == "tool":
                usage["tool_results"] += token_count
            else:
                usage["conversation_history"] += token_count
        
        # Note: system_prompt and rag_context would be calculated when building prompts
        # For now, we use the budgeted amounts as estimates
        # This will be refined when we actually build the prompt
        
        return usage

    def _reallocate_token_budget(self, required_tokens: int, component: str) -> Dict[str, int]:
        """
        Dynamically reallocate token budget to preserve forensic evidence.
        
        Priority Order:
        1. tool_results (forensic evidence) - minimum 4000 tokens
        2. conversation_history (context) - minimum 2000 tokens
        3. system_prompt (instructions) - minimum 1000 tokens
        4. rag_context (knowledge base) - flexible, can reduce to 500 tokens
        
        Args:
            required_tokens: Additional tokens needed
            component: Component requesting more tokens
            
        Returns:
            Updated token budget dictionary
            
        """
        budget = self.token_budget.copy()
        
        # Ensure all components exist in budget
        if "rag_context" not in budget:
            budget["rag_context"] = 2000
        if "tool_results" not in budget:
            budget["tool_results"] = 4000
        
        # Calculate current allocation
        total_allocated = sum(budget.values())
        available = self.max_total_tokens - total_allocated
        
        if available >= required_tokens:
            budget[component] = budget.get(component, 0) + required_tokens
            self.logger.info(f"Allocated {required_tokens} tokens to {component} from available budget")
            return budget
        
        # Need to reallocate - reduce from lowest priority components
        deficit = required_tokens - available
        self.logger.info(f"Token budget reallocation needed. Deficit: {deficit} tokens")
        
        # Try reducing RAG context first (lowest priority)
        if budget.get("rag_context", 0) > 500:
            reduction = min(deficit, budget["rag_context"] - 500)
            budget["rag_context"] -= reduction
            deficit -= reduction
            self.logger.info(f"Reduced rag_context by {reduction} tokens (now {budget['rag_context']})")
            
            # Log to audit trail if available
            if self.truncation_auditor:
                self.truncation_auditor.log_event(
                    action="BUDGET_REDUCED",
                    message_id="rag_context",
                    token_count=reduction,
                    reason="token_reallocation",
                    message_hash="",
                    metadata={"component": "rag_context", "new_budget": budget["rag_context"]}
                )
        
        # If still need more, reduce system prompt
        if deficit > 0 and budget.get("system_prompt", 0) > 1000:
            reduction = min(deficit, budget["system_prompt"] - 1000)
            budget["system_prompt"] -= reduction
            deficit -= reduction
            self.logger.info(f"Reduced system_prompt by {reduction} tokens (now {budget['system_prompt']})")
            
            # Log to audit trail if available
            if self.truncation_auditor:
                self.truncation_auditor.log_event(
                    action="BUDGET_REDUCED",
                    message_id="system_prompt",
                    token_count=reduction,
                    reason="token_reallocation",
                    message_hash="",
                    metadata={"component": "system_prompt", "new_budget": budget["system_prompt"]}
                )
        
        # If still need more, reduce conversation_history (but not below 2000)
        if deficit > 0 and budget.get("conversation_history", 0) > 2000:
            reduction = min(deficit, budget["conversation_history"] - 2000)
            budget["conversation_history"] -= reduction
            deficit -= reduction
            self.logger.info(f"Reduced conversation_history by {reduction} tokens (now {budget['conversation_history']})")
            
            # Log to audit trail if available
            if self.truncation_auditor:
                self.truncation_auditor.log_event(
                    action="BUDGET_REDUCED",
                    message_id="conversation_history",
                    token_count=reduction,
                    reason="token_reallocation",
                    message_hash="",
                    metadata={"component": "conversation_history", "new_budget": budget["conversation_history"]}
                )
        
        # Never reduce tool_results below 4000 tokens 
        # This is enforced by not including tool_results in the reduction order
        
        # Allocate to requesting component
        budget[component] = budget.get(component, 0) + (required_tokens - deficit)
        
        # Log if we couldn't fully satisfy the request
        if deficit > 0:
            self.logger.warning(
                f"Could not fully satisfy token request for {component}. "
                f"Deficit: {deficit} tokens. Allocated: {required_tokens - deficit} tokens"
            )
        
        return budget

    def _emit_truncation_warning(self, count: int, total_tokens: int):
        """
        Emit truncation warning to UI via bridge.
        
        Args:
            count: Number of messages summarized
            total_tokens: Current total token usage
            
        """
        from datetime import datetime
        
        budget = self.token_budget.get("conversation_history", 8000)
        
        warning_data = {
            "type": "truncation_warning",
            "count": count,
            "total_tokens": total_tokens,
            "budget": budget,
            "timestamp": datetime.now().isoformat()
        }
        
        # Check for token budget exhaustion 
        if total_tokens > budget:
            deficit = total_tokens - budget
            warning_data["type"] = "budget_exhausted"
            warning_data["deficit"] = deficit
            warning_data["message"] = (
                f"Token budget exhausted. {deficit} tokens over limit. "
                f"Consider increasing budget or clearing history."
            )
            warning_data["actions"] = [
                {"id": "increase_budget", "label": "Increase Budget"},
                {"id": "clear_non_preserved", "label": "Clear Non-Preserved History"},
                {"id": "export_and_reset", "label": "Export and Reset"}
            ]
            
            self.logger.error(
                f"CRITICAL: Token budget exhausted! "
                f"Total: {total_tokens}, Budget: {budget}, Deficit: {deficit}"
            )
        else:
            self.logger.warning(
                f"Truncation warning: {count} messages summarized. "
                f"Total tokens: {total_tokens}/{budget}"
            )
        
        # Emit via bridge if available
        # Note: The bridge integration will be implemented in Task 9.1
        # For now, we just log the warning
        # In production, this would call: self.bridge.emit_truncation_warning(warning_data)
        
        return warning_data

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
