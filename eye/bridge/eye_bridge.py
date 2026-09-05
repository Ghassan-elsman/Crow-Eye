"""
EYE Bridge - QWebChannel bridge for React ↔ Python communication.

This module provides the EYEBridge class which exposes forensic AI assistant
functionality to the React frontend via QWebChannel slots. It handles:
- Natural language query processing through ContextManager
- Database querying and schema introspection
- Semantic mapping proposal and editing
- Report manipulation (append, edit, delete sections)
- Report export with format selection
- Context management (stats, history clearing)

All methods return JSON strings for consumption by the React frontend.
The React side calls these via window.bridge.methodName(args) through QWebChannel.

"""

import json
import logging
import os
import re
import hashlib
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QThread, QEventLoop, Qt
import base64
from datetime import datetime, date
import inspect
import gc

class SafeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles non-serializable objects safely with recursion protection."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen = set()

    def default(self, obj):
        # Prevent deep recursion for complex forensic objects
        obj_id = id(obj)
        if obj_id in self._seen:
            return f"[Circular Reference: {type(obj).__name__}]"
        
        if len(self._seen) > 1000: # Depth/Breadth limit
             return f"[Serialization Limit Reached: {type(obj).__name__}]"
             
        self._seen.add(obj_id)
        
        try:
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            if hasattr(obj, '__dict__'):
                # Avoid dumping massive internal dictionaries of complex objects
                if type(obj).__name__ in ['Connection', 'Cursor', 'Row', 'Path']:
                    return str(obj)
                return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
            if isinstance(obj, bytes):
                # Cap base64 encoding to 1MB to prevent bridge crashes
                if len(obj) > 1024 * 1024:
                    return f"[Bytes: {len(obj)} bytes (Truncated)]"
                return base64.b64encode(obj).decode('utf-8')
            return str(obj)
        except Exception as e:
            return f"[Error serializing {type(obj).__name__}: {str(e)}]"
        finally:
            # We don't remove from seen because we want to catch the same object 
            # even if it appears in different parts of the tree (DAG preservation)
            pass

def safe_json_dumps(obj):
    """Safely dump object to JSON string with deep preprocessing to prevent crashes."""
    
    def preprocess(o, depth=0):
        # Stop deep recursion early
        if depth > 10:
            return f"[Depth Limit Reached: {type(o).__name__}]"
        
        # Handle basic types directly for speed
        if o is None or isinstance(o, (bool, int, float, str)):
            return o
            
        if isinstance(o, (datetime, date)):
            return o.isoformat()
            
        if isinstance(o, bytes):
            if len(o) > 512 * 1024: # 512KB limit for bytes in general objects
                return f"[Bytes: {len(o)} bytes (Truncated)]"
            return base64.b64encode(o).decode('utf-8')
            
        if isinstance(o, dict):
            # Cap dictionary size
            if len(o) > 500:
                return {k: preprocess(v, depth + 1) for i, (k, v) in enumerate(o.items()) if i < 500}
            return {k: preprocess(v, depth + 1) for k, v in o.items()}
            
        if isinstance(o, (list, tuple, set)):
            # Cap list size
            if len(o) > 1000:
                return [preprocess(v, depth + 1) for v in list(o)[:1000]]
            return [preprocess(v, depth + 1) for v in o]
            
        if hasattr(o, 'to_dict'):
            try: return preprocess(o.to_dict(), depth + 1)
            except: pass
            
        if hasattr(o, '__dict__'):
            # Avoid dumping massive internal dictionaries of complex objects
            if type(o).__name__ in ['Connection', 'Cursor', 'Row', 'Path', 'Thread', 'Process']:
                return str(o)
            return {k: preprocess(v, depth + 1) for k, v in o.__dict__.items() if not k.startswith('_')}
            
        return str(o)

    try:
        clean_obj = preprocess(obj)
        return json.dumps(clean_obj, cls=SafeEncoder, ensure_ascii=False)
    except Exception as e:
        logger.error(f"safe_json_dumps failed: {e}")
        return json.dumps({"success": False, "error": f"Serialization failed: {str(e)}"})

logger = logging.getLogger(__name__)

class QueryWorker(QThread):
    """
    Background worker thread to run ContextManager queries without blocking the GUI.
    """
    finished_query = pyqtSignal(str) # Now emits serialized JSON string
    request_hitl = pyqtSignal(str, object, dict, object)
    status_updated = pyqtSignal(str)
    report_updated = pyqtSignal(str)
    dialogue_updated = pyqtSignal(str)  # Eye<->LLM conversation entries (live)
    
    def __init__(self, context_manager, query, suppress_chat=False):
        super().__init__()
        self.context_manager = context_manager
        self.query = query
        self.result = None
        self.error = None
        # When True (background "investigate this narrative" runs), the worker does
        # NOT emit finished_query — no chat bubble is posted. Report / dialogue /
        # narrative-map updates still stream via their callbacks during run().
        self.suppress_chat = suppress_chat
        
    def run(self):
        def hitl_callback(key, value, case_context):
            # Create a local event loop to wait for the UI thread's response
            loop = QEventLoop()
            
            # Emit signal to show dialog on main thread
            # We pass the loop so the UI thread can quit it when done
            self.request_hitl.emit(key, value, case_context, loop)
            
            # Block the worker thread until the user interacts with the dialog
            loop.exec_()
            
            # Return the approval status or modified data stored in the loop object by the UI thread
            if hasattr(loop, 'approved_data'):
                return loop.approved_data
            return getattr(loop, 'approved', False)

        def status_callback(message: str):
            logger.info(f"Status update: {message}")
            self.status_updated.emit(message)

        def dialogue_callback(entry_json: str):
            # Stream one Eye<->LLM conversation entry to the UI.
            self.dialogue_updated.emit(entry_json)

        def report_callback(report_json: str):
            # Size check before emitting to bridge to prevent QWebChannel overflow crashes
            MAX_REPORT_PAYLOAD = 10 * 1024 * 1024 # 10MB
            if len(report_json) > MAX_REPORT_PAYLOAD:
                logger.warning(f"Report payload too large ({len(report_json)} bytes). Enforcing truncation for bridge stability.")
                try:
                    # Try to reconstruct a minimal valid report JSON
                    data = json.loads(report_json)
                    if "blocks" in data:
                        # Keep only metadata and a warning, clear heavy blocks
                        data["blocks"] = [{
                            "block_id": "error_truncation",
                            "block_type": "text",
                            "title": "⚠️ Report Sync Truncated",
                            "markdown_content": f"The report size ({len(report_json) / 1024 / 1024:.1f}MB) exceeded the bridge stability limit. The full report is still saved to disk, but the live view has been truncated to prevent a crash.",
                            "metadata": {"author": "system", "timestamp": datetime.now().isoformat()}
                        }]
                        report_json = safe_json_dumps(data)
                except:
                    report_json = json.dumps({"error": "Report too large for bridge", "blocks": []})

            logger.info(f"Report update emitted ({len(report_json)} bytes)")
            self.report_updated.emit(report_json)
            
        self.context_manager.hitl_callback = hitl_callback
        
        try:
            # Process query through ContextManager with status updates
            status_callback("Analyzing your query...")
            
            # Check if context_manager supports status_callback and hitl_callback
            sig = inspect.signature(self.context_manager.process_query)
            params = {}
            if 'status_callback' in sig.parameters:
                params['status_callback'] = status_callback
            if 'hitl_callback' in sig.parameters:
                params['hitl_callback'] = hitl_callback
            if 'report_callback' in sig.parameters:
                params['report_callback'] = report_callback
            if 'dialogue_callback' in sig.parameters:
                params['dialogue_callback'] = dialogue_callback

            res = self.context_manager.process_query(self.query, **params)
            
            # Ensure the result is wrapped in the standard {success, data, error} envelope
            # before serialization in the background thread.
            if isinstance(res, dict) and "success" in res and "data" in res:
                self.result = res
            else:
                self.result = {
                    "success": True,
                    "data": res,
                    "error": None
                }
        except Exception as e:
            logger.error(f"CRITICAL: QueryWorker execution failed: {e}", exc_info=True)
            self.error = e
            self.result = {"success": False, "data": None, "error": str(e)}
        finally:
            try:
                if hasattr(self.context_manager, 'hitl_callback'):
                    del self.context_manager.hitl_callback

                # Background investigate run: skip the chat bubble entirely. Map /
                # report updates were already streamed via callbacks during run().
                if self.suppress_chat:
                    logger.info("Investigate run finished (suppressed chat emit).")
                    self.result = None
                    gc.collect()
                    return

                logger.info("Serializing final query result...")
                # Serialize in the background thread to avoid freezing the GUI
                serialized_result = safe_json_dumps(self.result)
                
                # SAFETY CAP: Prevent bridge crashes if the result is still too large
                MAX_BRIDGE_PAYLOAD = 10 * 1024 * 1024 # 10MB
                if len(serialized_result) > MAX_BRIDGE_PAYLOAD:
                    logger.warning(f"Bridge payload too large ({len(serialized_result)} bytes). Enforcing truncation.")
                    # Try to preserve the main response but drop heavy data viewers/tool results
                    if isinstance(self.result, dict):
                        self.result["data_viewer"] = None
                        self.result["data_viewers"] = []
                        self.result["action_chips"] = self.result.get("action_chips", [])[:2]
                        if "error" not in self.result:
                            self.result["error"] = "Result payload was truncated for stability. Try a more granular query."
                        serialized_result = safe_json_dumps(self.result)
                    
                    # If it's still too large, go to last ditch
                    if len(serialized_result) > MAX_BRIDGE_PAYLOAD:
                         serialized_result = json.dumps({
                            "success": False,
                            "data": None,
                            "error": "Critical: Result too large for bridge (>10MB)."
                        })

                logger.info(f"Emitting finished_query signal ({len(serialized_result)} bytes)")
                self.finished_query.emit(serialized_result)
                
                # HARDENING: Explicitly trigger GC after large payload emission to reclaim memory
                # in the frozen process.
                if len(serialized_result) > 1 * 1024 * 1024:
                    logger.info("Large payload emitted. Triggering explicit garbage collection.")
                    serialized_result = None
                    self.result = None
                    gc.collect()
            except Exception as e:
                logger.error(f"FATAL: Failed to finalize query result: {e}", exc_info=True)
                # Last ditch effort with a simple error message
                try:
                    self.finished_query.emit(json.dumps({
                        "success": False,
                        "data": None,
                        "error": f"Internal serialization error: {str(e)}"
                    }))
                except:
                    # Total failure, but at least we don't crash the whole app if possible
                    pass


class ModelSwitchValidator(QThread):
    """Background connectivity check for a just-switched model/backend.

    Runs ``backend.validate_connectivity()`` (one cheap models.list() round-trip)
    OFF the GUI thread so a dead network / bad key can never freeze the UI.
    Emits ``finished_validation(ok, detail)``; the bridge then either persists the
    switch and fires the case-context sync, or reverts to the previous model and
    tells the investigator the key/model is not working.
    """
    finished_validation = pyqtSignal(bool, str)

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    def run(self):
        try:
            ok = bool(self._backend.validate_connectivity())
            detail = "" if ok else ("the provider rejected the request — check that the "
                                    "API key is valid and the model name exists")
            self.finished_validation.emit(ok, detail)
        except Exception as e:
            self.finished_validation.emit(False, str(e))


class EYEBridge(QObject):
    """
    QWebChannel bridge exposing EYE AI assistant functionality to React frontend.
    
    This bridge follows the same pattern as TimelineBridge, providing @pyqtSlot
    decorated methods that return JSON strings. The React frontend communicates
    with Python backend through QWebChannel bidirectional communication.
    """
    
    # Signals for UI interactions
    case_context_requested = pyqtSignal()
    case_summary_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    add_evidence_requested = pyqtSignal()  # open the "Add new evidence" import flow
    compliance_window_requested = pyqtSignal()
    narrative_map_window_requested = pyqtSignal()  # open the Narrative Map OS window
    narrative_map_focus = pyqtSignal(str)  # focus a Verdict/Narrative/Evidence card (id) in the map
    evidence_window_requested = pyqtSignal()  # open the Imported Evidence OS window
    imported_evidence_ready = pyqtSignal(str)  # async verified imported-evidence listing (JSON)
    grouped_backends_ready = pyqtSignal(str)  # async live-refreshed model-menu grouping (JSON)

    # Signals for async operations
    query_complete = pyqtSignal(str)  # JSON response when query completes
    report_updated = pyqtSignal(str)  # Updated report JSON when report changes
    narrative_map_updated = pyqtSignal(str)  # Narrative Map changed (Eye or investigator)
    narrativeInvestigationComplete = pyqtSignal(str)  # a double-click "investigate" run finished (narrative id)
    error_occurred = pyqtSignal(str)  # Error message when backend error occurs
    layout_requested = pyqtSignal(str) # Request UI layout changes (JSON)
    status_updated = pyqtSignal(str)  # Status update message (thinking/searching)
    dialogue_updated = pyqtSignal(str)  # Eye<->LLM conversation entry (live transcript)
    reflow_charts = pyqtSignal()      # Trigger chart alignment reflow
    
    def __init__(
        self,
        context_manager=None,
        database_service=None,
        search_service=None,
        report_engine=None,
        parent=None
    ):
        """
        Initialize the EYE Bridge.
        
        Args:
            context_manager: ContextManager instance for query processing
            database_service: ForensicDatabaseService for database operations
            search_service: ForensicSearchService for artifact search
            report_engine: ReportEngine instance for report manipulation
            parent: Parent QObject (optional)
        """
        super().__init__(parent)
        self.context_manager = context_manager
        self.database_service = database_service
        self.search_service = search_service
        self.report_engine = report_engine
        # Let the agentic loop push live Narrative Map updates through this bridge.
        if context_manager is not None:
            try:
                context_manager.narrative_map_update_callback = self.emit_narrative_map_changed
            except Exception as e:
                logger.debug(f"Could not register narrative map update callback: {e}")
        logger.info("EYEBridge initialized")
    
    def _emit_report_updated(self, report_json: str):
        """Emits report_updated signal with size safety checks."""
        MAX_REPORT_PAYLOAD = 10 * 1024 * 1024 # 10MB
        if len(report_json) > MAX_REPORT_PAYLOAD:
            logger.warning(f"Report payload too large ({len(report_json)} bytes). Enforcing truncation for bridge stability.")
            try:
                data = json.loads(report_json)
                if "blocks" in data:
                    data["blocks"] = [{
                        "block_id": "error_truncation",
                        "block_type": "text",
                        "title": "⚠️ Report Sync Truncated",
                        "markdown_content": f"The report size ({len(report_json) / 1024 / 1024:.1f}MB) exceeded the bridge stability limit. Live view truncated.",
                        "metadata": {"author": "system", "timestamp": datetime.now().isoformat()}
                    }]
                    report_json = safe_json_dumps(data)
            except:
                report_json = json.dumps({"error": "Report too large for bridge", "blocks": []})
        
        self.report_updated.emit(report_json)
        self.reflow_charts.emit()
    
    # ──────────────────────────────────────────────
    # Query Processing Methods
    # ──────────────────────────────────────────────
    
    @pyqtSlot(result=str)
    def initialize_triage(self) -> str:
        """
        Trigger the automated forensic triage report if it doesn't exist,
        or analyze the existing context if it does.
        """
        # Check if the report engine already has content
        if hasattr(self, 'report_engine') and self.report_engine.blocks:
            logger.info("Report already has content. Triggering case context analysis.")
            return self.process_query("analyze_case_context")

        logger.info("Report is empty. Triggering automated forensic triage protocol...")
        return self.process_query("initialize_case_report")

    @pyqtSlot(str, result=str)
    def process_query(self, query: str) -> str:
        """
        Process natural language query through ContextManager.
        
        This is the main entry point for user queries. The ContextManager
        orchestrates LLM interaction, tool routing, and response generation.
        
        Args:
            query: Natural language query from investigator
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "response": "AI response text",
                    "data_viewer": {...} or null,
                    "action_chips": [...],
                    "context_stats": {...}
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Processing query: {query[:100]}...")
            
            # Validate context_manager is available
            if not self.context_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Create and start the worker thread
            worker = QueryWorker(self.context_manager, query)
            
            # Connect worker signals
            worker.finished_query.connect(self._on_query_finished)
            worker.request_hitl.connect(self._show_hitl_dialog)
            worker.status_updated.connect(self.status_updated.emit)
            worker.dialogue_updated.connect(self.dialogue_updated.emit)
            # Connect worker to centralized guarded emitter
            worker.report_updated.connect(self._emit_report_updated)
            
            # Keep reference to prevent GC
            if not hasattr(self, '_active_workers'):
                self._active_workers = []
            self._active_workers.append(worker)
            
            # Start processing
            worker.start()
            
            # Return immediately to avoid freezing the UI
            # The frontend will receive the final result via the query_complete signal
            return safe_json_dumps({
                "success": True,
                "data": {
                    "status": "processing",
                    "message": "Query is being processed in background"
                },
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })

    def _on_query_finished(self, serialized_result):
        """
        Handle completed query and send result to React.
        """
        # Cleanup worker reference
        sender = self.sender()
        if hasattr(self, '_active_workers') and sender in self._active_workers:
            try:
                self._active_workers.remove(sender)
            except ValueError:
                pass
            
        logger.info("Query worker finished. Sending result to React.")
        self.query_complete.emit(serialized_result)

    # NOTE: the real HITL handler is the later `_show_hitl_dialog(key, data,
    # case_context, loop)` (it matches the `request_hitl` signal and is what
    # `worker.request_hitl` connects to). A previous duplicate defined here
    # referenced a `hitl_requested` signal that is NOT declared on this class —
    # dead/shadowed, and an AttributeError landmine if ever reached — so it was
    # removed.

    @pyqtSlot(str, str, result=str)
    def query_database(self, database: str, sql: str) -> str:
        """
        Execute SQL query against specified database.
        
        Provides direct database access for the React frontend.
        Uses DatabaseService for read-only parameterized queries.
        
        Args:
            database: Database name (e.g., "prefetch_data.db")
            sql: SQL query string
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "columns": ["col1", "col2", ...],
                    "rows": [{...}, {...}, ...],
                    "row_count": 123
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Querying database: {database}")
            
            # Validate database_service is available
            if not self.database_service:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "DatabaseService not initialized"
                })
            
            # Execute query through DatabaseService
            result = self.database_service.execute_query(database, sql)
            
            # Check if query was successful
            if not result.get("success"):
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": result.get("error", "Query execution failed")
                })
            
            # Format response for frontend
            data = {
                "columns": [col for col in result.get("data", [{}])[0].keys()] if result.get("data") else [],
                "rows": result.get("data", []),
                "row_count": result.get("row_count", 0)
            }
            
            return safe_json_dumps({
                "success": True,
                "data": data,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error querying database: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, result=str)
    def search_artifacts(self, search_config_json: str) -> str:
        """
        Search across forensic artifacts using SearchService.
        
        Supports full-text search, regex, exact match, and case-sensitive options.
        
        Args:
            search_config_json: JSON string with SearchConfig format:
            {
                "search_term": "malware.exe",
                "tables": ["prefetch_data", "mft_data"],
                "columns": ["filename", "path"],
                "case_sensitive": false,
                "exact_match": false,
                "use_regex": false,
                "max_results": 1000,
                "timeout_seconds": 30
            }
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "results": {
                        "table_name": [{...}, {...}],
                        ...
                    },
                    "total_matches": 45,
                    "search_time": 1.23
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Searching artifacts with config: {search_config_json[:100]}...")
            
            # Validate search_service is available
            if not self.search_service:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "SearchService not initialized"
                })
            
            # Parse search configuration
            search_config_dict = json.loads(search_config_json)
            
            # Import SearchConfig from search_service
            from data.search_engine import SearchConfig
            
            # Create SearchConfig object
            search_config = SearchConfig(
                search_term=search_config_dict.get("search_term", ""),
                tables=search_config_dict.get("tables"),
                columns=search_config_dict.get("columns"),
                case_sensitive=search_config_dict.get("case_sensitive", False),
                exact_match=search_config_dict.get("exact_match", False),
                use_regex=search_config_dict.get("use_regex", False),
                max_results=search_config_dict.get("max_results", 1000),
                timeout_seconds=search_config_dict.get("timeout_seconds", 30.0)
            )
            
            # Execute search through SearchService
            results = self.search_service.search(search_config)
            
            # Format response for frontend
            # Convert SearchResult objects to dictionaries
            formatted_results = {}
            for table_name, search_results in results.results.items():
                # SearchResult is a dataclass with fields table_name / row_id /
                # matched_columns / record_data / relevance_score — use those
                # (the old sr.table / sr.row_data / sr.match_count did not exist
                # and raised AttributeError on the first result).
                formatted_results[table_name] = [
                    {
                        "table": sr.table_name,
                        "row_id": sr.row_id,
                        "row_data": sr.record_data,
                        "matched_columns": sr.matched_columns,
                        "match_count": len(sr.matched_columns or []),
                        "relevance": sr.relevance_score,
                    }
                    for sr in search_results
                ]
            
            data = {
                "results": formatted_results,
                "total_matches": results.total_matches,
                "search_time": results.search_time,
                "truncated": results.truncated,
                "tables_searched": results.tables_searched,
                "tables_with_results": results.tables_with_results
            }
            
            return safe_json_dumps({
                "success": True,
                "data": data,
                "error": None
            })
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in search config: {e}", exc_info=True)
            error_msg = f"Invalid search configuration JSON: {str(e)}"
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error searching artifacts: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, str, result=str)
    def get_schema(self, database: str, table: str) -> str:
        """
        Get schema information for a database table.
        
        Returns column names, types, and constraints for schema introspection.
        
        Args:
            database: Database name (e.g., "prefetch_data.db")
            table: Table name (e.g., "prefetch_data")
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "database": "prefetch_data.db",
                    "tables": ["prefetch_data"],
                    "schema": {
                        "prefetch_data": [
                            {"name": "id", "type": "INTEGER"},
                            {"name": "filename", "type": "TEXT"},
                            ...
                        ]
                    },
                    "sample_data": {
                        "prefetch_data": [{...}, {...}, ...]
                    },
                    "row_counts": {
                        "prefetch_data": 1234
                    }
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Getting schema for {database}.{table}")
            
            # Validate database_service is available
            if not self.database_service:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "DatabaseService not initialized"
                })
            
            # Get schema through DatabaseService
            result = self.database_service.get_schema(database, table)
            
            # Check if schema retrieval was successful
            if not result.get("success"):
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": result.get("error", "Schema retrieval failed")
                })
            
            # Return the schema data
            return safe_json_dumps({
                "success": True,
                "data": result,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error getting schema: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    # ──────────────────────────────────────────────
    # Context Management Methods
    # ──────────────────────────────────────────────
    
    @pyqtSlot(result=str)
    def get_context_stats(self) -> str:
        """
        Get conversation history statistics.
        
        Returns token usage, message count, and truncation information
        for display in the React frontend.
        
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "total_messages": 10,
                    "total_tokens": 5432,
                    "budget_remaining": 2568,
                    "truncation_count": 1,
                    "max_total_tokens": 8000
                },
                "error": null
            }
        
        """
        try:
            logger.debug("Getting context stats")
            
            # Validate context_manager is available
            if not self.context_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Get stats from ContextManager
            stats = self.context_manager.get_context_stats()
            logger.info(f"Sending context stats: {stats}")
            print(f"[EYE Bridge] Stats sent: {stats.get('model_name')} ({stats.get('backend')})")
            
            return safe_json_dumps({
                "success": True,
                "data": stats,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error getting context stats: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(result=str)
    def clear_conversation_history(self) -> str:
        """
        Clear conversation history except the first message.
        
        Returns:
            JSON string with updated history
        """
        try:
            logger.info("Clearing conversation history")
            if not self.context_manager:
                return safe_json_dumps({"success": False, "data": None, "error": "ContextManager not initialized"})
            
            history = self.context_manager.clear_conversation_history()
            return safe_json_dumps({
                "success": True,
                "data": history,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error clearing history: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_conversation_history(self) -> str:
        """
        Get all messages in current session.
        
        Returns:
            JSON string with message list
        """
        try:
            if not self.context_manager:
                return safe_json_dumps({"success": False, "data": None, "error": "ContextManager not initialized"})

            history = self.context_manager.conversation_history
            history = self._backfill_message_thinking(history)
            return safe_json_dumps({
                "success": True,
                "data": history,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error getting history: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(str, result=str)
    def update_token_budget(self, budget_json: str) -> str:
        """Apply a manually-edited token budget from the UI slider.

        The React TokenBudgetSlider sends a flat object
        ``{conversation_history, system_prompt, rag_context, tool_results,
        max_total}``. We translate the component allocations into the
        ContextManager's config shape and mark the budget as explicitly set so
        adaptive scaling (`_resolve_token_budget`) won't overwrite it on the next
        model switch. The resolved context window itself is left untouched.
        """
        try:
            if not self.context_manager:
                return safe_json_dumps({"success": False, "data": None, "error": "ContextManager not initialized"})
            payload = json.loads(budget_json) if budget_json else {}
            if not isinstance(payload, dict):
                return safe_json_dumps({"success": False, "data": None, "error": "Invalid budget payload"})

            component_keys = ("conversation_history", "system_prompt", "rag_context", "tool_results")
            if isinstance(payload.get("token_budget"), dict):
                source = payload["token_budget"]
            else:
                source = payload
            token_budget = {k: int(source[k]) for k in component_keys if isinstance(source.get(k), (int, float))}
            if not token_budget:
                return safe_json_dumps({"success": False, "data": None, "error": "No valid token_budget fields provided"})

            self.context_manager.update_context_config({"token_budget": token_budget})
            # Pin so the adaptive budget scaler doesn't clobber the manual values.
            self.context_manager._token_budget_explicit = True
            return safe_json_dumps({
                "success": True,
                "data": {"token_budget": self.context_manager.token_budget},
                "error": None,
            })
        except Exception as e:
            logger.error(f"Error updating token budget: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    # ──────────────────────────────────────────────
    # Model Selection Methods
    # ──────────────────────────────────────────────

    @pyqtSlot(result=str)
    def get_available_models_with_quota(self) -> str:
        """
        Get the list of available models and their quota status.
        """
        try:
            if not self.context_manager:
                return safe_json_dumps({"success": False, "data": None, "error": "ContextManager not initialized"})
            
            models = self.context_manager.model_router.get_models_with_quota()
            return safe_json_dumps({
                "success": True,
                "data": models,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error getting models: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_grouped_backend_connections(self) -> str:
        """
        Get all configured backend connections and their models, grouped by backend
        type. Returns the FAST in-memory grouping synchronously (no network / no
        OS-keychain reads) so the model dropdown opens instantly, and kicks off a
        background thread that does the authoritative live refresh and emits it via
        ``grouped_backends_ready`` — the UI updates the menu in place when it lands.
        """
        try:
            if not self.context_manager or not self.context_manager.model_router:
                return safe_json_dumps({"success": False, "data": None, "error": "ModelRouter not initialized"})

            router = self.context_manager.model_router
            options = router.get_grouped_backend_options(live=False)

            # Background live refresh (real list_models() + credential probes).
            bridge = self

            class _GroupedBackendsWorker(QThread):
                def run(self):
                    try:
                        live = router.get_grouped_backend_options(live=True)
                        bridge.grouped_backends_ready.emit(safe_json_dumps(
                            {"success": True, "data": live, "error": None}))
                    except Exception as exc:
                        logger.debug(f"grouped-backends live refresh failed: {exc}")

            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            worker = _GroupedBackendsWorker()
            self._active_workers.append(worker)
            worker.finished.connect(lambda w=worker: (
                self._active_workers.remove(w) if w in self._active_workers else None,
                w.deleteLater()))
            worker.start()

            return safe_json_dumps({
                "success": True,
                "data": options,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error getting grouped backend connections: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    # Backend id -> integration_type, used when persisting a model switch. Must
    # cover EVERY selectable provider (the old inline list only knew
    # openai/anthropic/gemini, so switching to the newer providers persisted a
    # wrong integration_type).
    _INTEGRATION_TYPE_BY_BACKEND = {
        "openai": "cloud_api", "anthropic": "cloud_api", "gemini": "cloud_api",
        "deepseek": "cloud_api", "kimi": "cloud_api", "moonshot": "cloud_api",
        "openrouter": "cloud_api", "nvidia": "cloud_api", "groq": "cloud_api",
        "mistral": "cloud_api", "xai": "cloud_api", "grok": "cloud_api",
        "ollama": "local_server", "lm_studio": "local_server", "vllm": "local_server",
    }

    @pyqtSlot(str, result=bool)
    def switch_active_model(self, model_name: str) -> bool:
        """
        Switch the actively connected AI model, supporting format "backend:model_name"
        to change the backend connection type on-the-fly.

        The switch is ACCEPTED immediately (returns True), then the new
        model/key is VALIDATED on a background thread. Only a validated switch is
        persisted and followed by the case-context sync; a failed validation
        reverts to the previous model and posts a clear error to the chat — so a
        bad API key or model name surfaces in seconds, not as a silent hang.
        """
        try:
            if not self.context_manager:
                return False

            backend = None
            if ":" in model_name:
                backend, model_name = model_name.split(":", 1)

            router = self.context_manager.model_router
            # Snapshot for revert if the new model/key turns out not to work.
            prev = {
                "backend": router.config.get("backend"),
                "model_name": router.config.get("model_name"),
                "integration_type": router.config.get("integration_type"),
            }

            router.switch_model(model_name, backend=backend)
            logger.info(f"Switched model to {model_name} (Backend: {backend or 'unchanged'}) — validating…")

            # Validate connectivity off the GUI thread. Context for the continuation
            # is stored on self, and the signal connects to a BOUND METHOD of this
            # QObject so Qt queues the callback onto the main thread (a lambda would
            # run on the worker thread instead).
            validator = ModelSwitchValidator(router.backend)
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(validator)  # keep a ref so it isn't GC'd
            self._pending_switch = {"backend": backend, "model_name": model_name,
                                    "prev": prev, "worker": validator}
            validator.finished_validation.connect(self._on_switch_validated)
            validator.start()
            return True
        except Exception as e:
            logger.error(f"Error switching model: {e}", exc_info=True)
            return False

    def _on_switch_validated(self, ok: bool, detail: str) -> None:
        """Main-thread continuation of switch_active_model after the background
        connectivity check."""
        ctx = getattr(self, "_pending_switch", None) or {}
        self._pending_switch = None
        backend = ctx.get("backend")
        model_name = ctx.get("model_name") or ""
        prev = ctx.get("prev") or {}
        worker = ctx.get("worker")
        try:
            if worker in getattr(self, "_active_workers", []):
                self._active_workers.remove(worker)
                worker.deleteLater()
        except Exception:
            pass

        if ok:
            logger.info(f"Model switch validated: {backend or 'same backend'}:{model_name}")
            # Persist the configuration only now that we know it works.
            try:
                from eye.services.config_manager import ConfigManager
                cfg_manager = ConfigManager()
                config = cfg_manager.load_config()
                if backend:
                    config["backend"] = backend
                    it = self._INTEGRATION_TYPE_BY_BACKEND.get(backend)
                    if it:
                        config["integration_type"] = it
                config["model_name"] = model_name
                cfg_manager.save_config(config)
                logger.info("Saved updated backend configuration to eye_config.json")
            except Exception as cfg_exc:
                logger.warning(f"Could not save config to eye_config.json: {cfg_exc}")

            # Case-context sync on the (now verified) model.
            self.process_query("analyze_case_context")
            return

        # Validation failed — revert to the previous model so the Eye keeps working.
        target_label = f"{backend + ':' if backend else ''}{model_name}"
        prev_label = f"{prev.get('backend')}:{prev.get('model_name')}"
        logger.warning(f"Model switch to {target_label} failed validation: {detail} — reverting to {prev_label}")
        try:
            router = self.context_manager.model_router
            router.switch_model(prev.get("model_name") or "", backend=prev.get("backend"))
            if prev.get("integration_type"):
                router.config["integration_type"] = prev["integration_type"]
        except Exception as revert_exc:
            logger.error(f"Could not revert model switch: {revert_exc}", exc_info=True)

        self.query_complete.emit(safe_json_dumps({
            "success": False,
            "data": None,
            "error": (f"Could not activate {target_label} — the API key or model is not "
                      f"working ({detail or 'connectivity check failed'}). "
                      f"Reverted to {prev_label}."),
        }))

    @pyqtSlot(result=str)
    def get_backend_status(self) -> str:
        """
        Report whether the EYE is currently connected to its configured AI backend.

        Used by the React "EYE Synchronization" step to decide whether to proceed
        with the automated triage handshake or surface a clear disconnect message.

        Returns JSON envelope with data:
            {
                "connected": bool,
                "backend": str | None,        # e.g. "openai", "anthropic", "ollama"
                "model": str | None,          # active model_name
                "integration_type": str | None,  # "cloud_api" | "local_server" | "local_cli"
                "detail": str                 # human-readable status
            }
        """
        try:
            cm = self.context_manager
            if not cm or not getattr(cm, "model_router", None):
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "connected": False,
                        "backend": None,
                        "model": None,
                        "integration_type": None,
                        "detail": "AI backend not initialized"
                    },
                    "error": None
                })

            cfg = getattr(cm.model_router, "config", {}) or {}
            backend = cfg.get("backend")
            model = cfg.get("model_name")
            integration_type = cfg.get("integration_type")

            try:
                connected = bool(cm.model_router.validate_connectivity())
                detail = "Active backend reachable" if connected else "Backend did not respond to connectivity check"
            except Exception as e:
                connected = False
                detail = f"Connectivity check failed: {e}"

            return safe_json_dumps({
                "success": True,
                "data": {
                    "connected": connected,
                    "backend": backend,
                    "model": model,
                    "integration_type": integration_type,
                    "detail": detail,
                },
                "error": None
            })
        except Exception as e:
            logger.error(f"Error checking backend status: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    # ──────────────────────────────────────────────
    # Semantic Mapping Methods
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, result=str)
    def propose_semantic_mapping(self, rule_json: str) -> str:
        """
        Propose a new semantic mapping rule with HitL approval.
        
        Displays a Human-in-the-Loop dialog for investigator approval
        before creating the semantic mapping rule.
        
        Args:
            rule_json: JSON string with Semantic_Rule format:
            {
                "name": "Suspicious PowerShell",
                "description": "Detects encoded PowerShell commands",
                "pattern": "powershell.*-enc.*",
                "severity": "high",
                "tags": ["powershell", "obfuscation"]
            }
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "rule_id": "rule_123",
                    "approved": true
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Proposing semantic mapping: {rule_json[:100]}...")
            
            # Parse the proposed rule
            proposed_rule = json.loads(rule_json)
            
            # Import the HitL dialog
            from eye.ui.hitl_dialogs import SemanticMappingApprovalDialog
            
            # Show HitL approval dialog
            dialog = SemanticMappingApprovalDialog(
                parent=self.parent(),
                proposed_rule=proposed_rule
            )
            
            # Execute dialog and get result
            dialog_result = dialog.exec_()
            
            # Check if approved
            if dialog.was_approved():
                approved_rule = dialog.get_approved_rule()
                
                # Generate rule_id if not present
                if "rule_id" not in approved_rule:
                    import uuid
                    approved_rule["rule_id"] = str(uuid.uuid4())
                
                # Save the approved rule to semantic rules file
                self._save_semantic_rule(approved_rule)
                
                logger.info(f"Semantic mapping approved and saved: {approved_rule.get('rule_id')}")
                
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "rule_id": approved_rule.get("rule_id"),
                        "approved": True
                    },
                    "error": None
                })
            else:
                # User rejected the proposal
                logger.info("Semantic mapping proposal rejected by user")
                
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "rule_id": None,
                        "approved": False
                    },
                    "error": None
                })
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in rule proposal: {e}", exc_info=True)
            error_msg = f"Invalid rule JSON: {str(e)}"
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error proposing semantic mapping: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, str, result=str)
    def edit_semantic_mapping(self, rule_id: str, rule_json: str) -> str:
        """
        Edit an existing semantic mapping rule with HitL approval.
        
        Displays a Human-in-the-Loop dialog for investigator approval
        before modifying the semantic mapping rule.
        
        Args:
            rule_id: Unique identifier of the rule to edit
            rule_json: JSON string with updated Semantic_Rule format
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "rule_id": "rule_123",
                    "approved": true,
                    "updated": true
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Editing semantic mapping: {rule_id}")
            
            # Parse the updated rule
            updated_rule = json.loads(rule_json)
            
            # Ensure rule_id is set
            updated_rule["rule_id"] = rule_id
            
            # Import the HitL dialog
            from eye.ui.hitl_dialogs import SemanticMappingApprovalDialog
            
            # Show HitL approval dialog with the updated rule
            dialog = SemanticMappingApprovalDialog(
                parent=self.parent(),
                proposed_rule=updated_rule
            )
            
            # Execute dialog and get result
            dialog_result = dialog.exec_()
            
            # Check if approved
            if dialog.was_approved():
                approved_rule = dialog.get_approved_rule()
                
                # Ensure rule_id is preserved
                approved_rule["rule_id"] = rule_id
                
                # Update the rule in semantic rules file
                self._update_semantic_rule(rule_id, approved_rule)
                
                logger.info(f"Semantic mapping edit approved and saved: {rule_id}")
                
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "rule_id": rule_id,
                        "approved": True,
                        "updated": True
                    },
                    "error": None
                })
            else:
                # User rejected the edit
                logger.info(f"Semantic mapping edit rejected by user: {rule_id}")
                
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "rule_id": rule_id,
                        "approved": False,
                        "updated": False
                    },
                    "error": None
                })
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in rule edit: {e}", exc_info=True)
            error_msg = f"Invalid rule JSON: {str(e)}"
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error editing semantic mapping: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    # ──────────────────────────────────────────────
    # Report Manipulation Methods
    # ──────────────────────────────────────────────
    
    @pyqtSlot(result=str)
    def get_report_state(self) -> str:
        """
        Get current report state.
        
        Returns the complete report structure with all blocks
        for display in the React report builder panel.
        
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "blocks": [
                        {
                            "id": "block_1",
                            "type": "text",
                            "content": "# Investigation Report\\n\\n...",
                            "timestamp": "2024-01-15T10:30:00Z"
                        },
                        ...
                    ],
                    "metadata": {
                        "case_name": "Case-2024-001",
                        "investigator": "John Doe",
                        "created": "2024-01-15T09:00:00Z",
                        "modified": "2024-01-15T10:30:00Z"
                    }
                },
                "error": null
            }
        
        """
        try:
            logger.debug("Getting report state")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Get report state from ReportEngine
            report_state = self.report_engine.get_report_json()
            
            return safe_json_dumps({
                "success": True,
                "data": report_state,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error getting report state: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, str, result=str)
    def report_append_section(self, title: str, content: str) -> str:
        """
        Append a new section to the report.
        
        Creates a new text block and emits report_updated signal.
        
        Args:
            title: Section title
            content: Markdown content
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "block_id": "block_123"
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Appending report section: {title}")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Append section through ReportEngine
            block_id = self.report_engine.append_section(title, content)
            
            # Emit report_updated signal with updated report state
            if self.report_engine:
                self._emit_report_updated(safe_json_dumps(self.report_engine.get_report_json()))
            
            return safe_json_dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error appending report section: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, str, result=str)
    def report_add_data_table(self, query: str, columns_json: str) -> str:
        """
        Add a data table block to the report.
        
        Creates a new table block with query results and emits report_updated signal.
        
        Args:
            query: SQL query that generated the data
            columns_json: JSON string containing columns and rows data:
                {
                    "columns": ["col1", "col2", ...],
                    "rows": [{...}, {...}, ...],
                    "caption": "Optional caption"
                }
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "block_id": "block_124"
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Adding data table to report")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Parse columns_json to extract columns, rows, and optional caption
            try:
                table_data = json.loads(columns_json)
                columns = table_data.get("columns", [])
                rows = table_data.get("rows", [])
                caption = table_data.get("caption", "")
            except json.JSONDecodeError as e:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": f"Invalid JSON in columns_json: {str(e)}"
                })
            
            # Add data table through ReportEngine
            block_id = self.report_engine.add_data_table(
                sql_query=query,
                columns=columns,
                rows=rows,
                caption=caption
            )
            
            # Emit report_updated signal with updated report state
            if self.report_engine:
                self._emit_report_updated(safe_json_dumps(self.report_engine.get_report_json()))
            
            return safe_json_dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error adding data table: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, str, str, result=str)
    def report_add_evidence(self, text_or_evidence_json: str, link_or_query: str, evidence_json_or_title: str) -> str:
        """
        Add forensic evidence to the report. Handles both direct React calls and 
        data viewer references.
        
        Args:
            text_or_evidence_json: Either the reference text OR the raw evidence JSON
            link_or_query: Either the source link OR the SQL query
            evidence_json_or_title: Either the evidence JSON OR the display title
        """
        try:
            if not self.report_engine:
                return safe_json_dumps({"success": False, "error": "ReportEngine not initialized"})

            # Heuristic to detect argument order (React frontend vs Internal bridge)
            # If the first arg is a JSON list/dict, it's likely the internal pattern [evidence, query, title]
            is_json = text_or_evidence_json.strip().startswith(('[', '{'))
            
            if is_json:
                # Internal/DataViewer Pattern: [evidence_json, query, title]
                evidence_json = text_or_evidence_json
                query = link_or_query
                title = evidence_json_or_title
                source_link = f"SQL: {query}" if query else ""
            else:
                # Standard UI Pattern: [text, link, evidence_json]
                title = text_or_evidence_json
                source_link = link_or_query
                evidence_json = evidence_json_or_title

            logger.info(f"Adding evidence reference: {title}")
            evidence_data = json.loads(evidence_json)
            
            # Ensure it's a list for ReferenceBlock
            if isinstance(evidence_data, dict):
                evidence_data = [evidence_data]
            
            # Add to report engine
            block_id = self.report_engine.add_evidence(
                reference_text=title or "Forensic Evidence",
                source_link=source_link,
                evidence_data=evidence_data,
                author="user",
                category="evidence"
            )
            
            # Persist changes
            self.report_engine.save_report()
            
            # Emit report updated signal to refresh frontend
            report_data = self.report_engine.get_report_json()
            if report_data:
                self._emit_report_updated(safe_json_dumps(report_data))
            
            return safe_json_dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error in report_add_evidence: {e}", exc_info=True)
            error_msg = str(e)
            if hasattr(self, 'error_occurred'):
                self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })

    @pyqtSlot(str, str, result=str)
    def report_add_image(self, path: str, caption: str) -> str:
        """
        Add an image block to the report.
        
        Creates a new image block and emits report_updated signal.
        
        Args:
            path: Path to image file
            caption: Image caption
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "block_id": "block_125"
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Adding image to report: {path}")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Add image through ReportEngine
            block_id = self.report_engine.add_image(
                image_path=path,
                caption=caption
            )
            
            # Emit report_updated signal with updated report state
            if self.report_engine:
                self._emit_report_updated(safe_json_dumps(self.report_engine.get_report_json()))
            
            return safe_json_dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error adding image: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    
    @pyqtSlot(str, str, result=str)
    def report_edit_section(self, block_id: str, content: str) -> str:
        """
        Edit an existing report section.
        
        Updates the content of a text block and emits report_updated signal.
        
        Args:
            block_id: Unique identifier of the block to edit
            content: New markdown content
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "updated": true
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Editing report section: {block_id}")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Edit section through ReportEngine
            success = self.report_engine.edit_section(block_id, content)
            
            if not success:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": f"Block {block_id} not found"
                })
            
            # Emit report_updated signal with updated report state
            self._emit_report_updated(safe_json_dumps(self.report_engine.get_report_json()))
            
            return safe_json_dumps({
                "success": True,
                "data": {"updated": True},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error editing report section: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, result=str)
    def report_delete_section(self, block_id: str) -> str:
        """
        Delete a report section.
        
        Removes a block from the report and emits report_updated signal.
        
        Args:
            block_id: Unique identifier of the block to delete
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "deleted": true
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Deleting report section: {block_id}")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Delete section through ReportEngine
            success = self.report_engine.delete_section(block_id)
            
            if not success:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": f"Block {block_id} not found"
                })
            
            # Emit report_updated signal with updated report state
            self._emit_report_updated(safe_json_dumps(self.report_engine.get_report_json()))
            
            return safe_json_dumps({
                "success": True,
                "data": {"deleted": True},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error deleting report section: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    # ──────────────────────────────────────────────
    # Export Methods
    # ──────────────────────────────────────────────
    
    @pyqtSlot(str, result=str)
    def export_report(self, format_type: str) -> str:
        """
        Export report to specified format with HitL approval.
        
        Displays a Human-in-the-Loop dialog for investigator approval
        before exporting the report to file.
        
        Args:
            format_type: Export format ("html", "pdf", or "markdown")
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "file_path": "/path/to/report.html",
                    "format": "html",
                    "approved": true
                },
                "error": null
            }
        
        """
        try:
            logger.info(f"Exporting report as {format_type}")
            
            # Validate report_engine is available
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Validate format_type
            format_type_lower = format_type.lower()
            if format_type_lower not in ["html", "pdf", "markdown"]:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": f"Invalid format type: {format_type}. Must be 'html', 'pdf', or 'markdown'"
                })
            
            # Generate the report content to estimate file size
            if format_type_lower == "html":
                content = self.report_engine.render_html()
                file_extension = ".html"
            elif format_type_lower == "pdf":
                # For PDF, we generate HTML first (PDF is rendered from HTML)
                content = self.report_engine.render_html()
                file_extension = ".pdf"
            else:  # markdown
                content = self.report_engine.export_markdown()
                file_extension = ".md"
            
            # Estimate file size
            file_size = len(content.encode('utf-8'))
            
            # Generate destination path
            from datetime import datetime
            import os
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"forensic_report_{timestamp}{file_extension}"
            
            # Use current working directory or a reports directory
            reports_dir = os.path.join(os.getcwd(), "reports")
            os.makedirs(reports_dir, exist_ok=True)
            destination_path = os.path.join(reports_dir, filename)
            
            # Import the HitL dialog
            from eye.ui.hitl_dialogs import ReportExportApprovalDialog
            
            # Show HitL approval dialog
            dialog = ReportExportApprovalDialog(
                parent=self.parent(),
                format_type=format_type_lower,
                file_size=file_size,
                destination_path=destination_path
            )
            
            # Execute dialog and get result
            dialog_result = dialog.exec_()
            
            # Check if approved
            if dialog.was_approved():
                # User approved - proceed with export
                logger.info(f"Export approved by user. Writing to {destination_path}")
                
                # Write the file based on format
                if format_type_lower == "html":
                    with open(destination_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"HTML report exported to {destination_path}")
                    
                elif format_type_lower == "pdf":
                    # Use ReportEngine's export_pdf method
                    self.report_engine.export_pdf(destination_path)
                    logger.info(f"PDF report exported to {destination_path}")
                    
                else:  # markdown
                    with open(destination_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"Markdown report exported to {destination_path}")
                
                # Return success response
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "file_path": destination_path,
                        "format": format_type_lower,
                        "approved": True
                    },
                    "error": None
                })
            else:
                # User cancelled the export
                logger.info("Export cancelled by user")
                
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "file_path": None,
                        "format": format_type_lower,
                        "approved": False
                    },
                    "error": None
                })
            
        except ImportError as e:
            # Handle missing dependencies (e.g., weasyprint for PDF)
            logger.error(f"Missing dependency for export: {e}", exc_info=True)
            error_msg = f"Missing required library for {format_type} export: {str(e)}"
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error exporting report: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, result=str)
    def import_reports(self, file_paths_json: str) -> str:
        """
        Import forensic reports from HTML files.
        
        Args:
            file_paths_json: JSON array of file paths
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "total_files": 2,
                    "total_blocks": 15,
                    "imports": [
                        {
                            "file": "report1.html",
                            "blocks": 8,
                            "errors": []
                        },
                        ...
                    ]
                },
                "error": null
            }
            
        """
        try:
            file_paths = json.loads(file_paths_json)
            
            if not self.report_engine:
                return safe_json_dumps({
                    "success": False,
                    "error": "ReportEngine not initialized"
                })
            
            # Get case directory from context manager
            if not self.context_manager or not hasattr(self.context_manager, 'case_directory'):
                return safe_json_dumps({
                    "success": False,
                    "error": "Case directory not available"
                })
            
            case_dir = self.context_manager.case_directory
            
            # Import ForensicReportParser
            from eye.services.report_parser import ForensicReportParser
            parser = ForensicReportParser(case_dir)
            
            imports = []
            total_blocks = 0
            
            for file_path in file_paths:
                try:
                    # Parse report file
                    parsed_data = parser.parse_report_file(file_path)
                    
                    # Convert to ReportBlock objects
                    blocks = parser.convert_to_report_blocks(parsed_data)
                    
                    # Import into ReportEngine
                    filename = os.path.basename(file_path)
                    result = self.report_engine.import_blocks(blocks, filename)
                    
                    imports.append({
                        "file": filename,
                        "blocks": result["imported_count"],
                        "errors": parsed_data.get("parse_errors", []) + result.get("errors", [])
                    })
                    
                    total_blocks += result["imported_count"]
                    
                except Exception as e:
                    logger.error(f"Error importing {file_path}: {e}")
                    imports.append({
                        "file": os.path.basename(file_path),
                        "blocks": 0,
                        "errors": [str(e)]
                    })
            
            # Emit report_updated signal
            self._emit_report_updated(
                safe_json_dumps(self.report_engine.get_report_json())
            )
            
            return safe_json_dumps({
                "success": True,
                "data": {
                    "total_files": len(file_paths),
                    "total_blocks": total_blocks,
                    "imports": imports
                },
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error in import_reports: {e}", exc_info=True)
            return safe_json_dumps({
                "success": False,
                "error": str(e)
            })
    
    def _on_query_finished(self, serialized_result):
        """Handle completion of background query worker."""
        # Clean up worker reference
        worker = self.sender()
        if hasattr(self, '_active_workers') and worker in self._active_workers:
            self._active_workers.remove(worker)
            worker.deleteLater()

        # result is expected to be a serialized JSON string from QueryWorker.
        # If it's already a string, we emit it directly to avoid redundant 
        # serialization on the main GUI thread.
        if isinstance(serialized_result, str):
            logger.info("Emitting query_complete signal (pre-serialized).")
            self.query_complete.emit(serialized_result)
            return

        # Fallback for dictionary results (compatibility)
        result = serialized_result
        if isinstance(result, dict) and "success" in result and "data" in result:
            # Already wrapped
            envelope = result
        else:
            # Raw data dict from query_processor — wrap it
            error = result.get("error") if isinstance(result, dict) else None
            envelope = {
                "success": not bool(error),
                "data": result,
                "error": error
            }

        # Emit signal for the frontend
        logger.info(f"Emitting query_complete signal. Success: {envelope.get('success')}")
        self.query_complete.emit(safe_json_dumps(envelope))
        
    def _show_hitl_dialog(self, key, data, case_context, loop):
        """
        Show the appropriate HitL dialog based on operation type.
        
        This method is called on the main thread via a signal from the QueryWorker.
        It uses the provided QEventLoop to synchronize with the background thread.
        """
        try:
            from eye.ui.hitl_dialogs import (
                CaseVariableApprovalDialog,
                SemanticMappingApprovalDialog
            )
            
            dialog = None
            
            # Map key/operation to appropriate dialog
            if key == "export_report":
                # data is the format_type (html, pdf, markdown)
                # We reuse the existing export_report slot logic
                export_json = self.export_report(data)
                export_result = json.loads(export_json)
                
                if export_result.get("success"):
                    loop.approved = True
                    loop.approved_data = export_result.get("data", {}).get("file_path")
                else:
                    loop.approved = False
                    loop.approved_data = None
                
                # We return here because export_report already handled its own dialog
                loop.quit()
                return

            elif key in ["propose_semantic_mapping", "edit_semantic_mapping"]:
                # data is the proposed rule dict
                dialog = SemanticMappingApprovalDialog(
                    parent=self.parent(),
                    proposed_rule=data
                )
            else:
                # Default: CaseVariableApprovalDialog (key is variable name, data is value)
                dialog = CaseVariableApprovalDialog(
                    parent=self.parent(),
                    variable_name=key,
                    variable_value=data,
                    case_context=case_context
                )
            
            if dialog:
                result_code = dialog.exec_()
                is_approved = dialog.was_approved()
                
                # Store results for the worker thread
                loop.approved = is_approved
                
                # If it's a dialog that supports editing (like semantic mapping),
                # pass back the potentially modified data
                if hasattr(dialog, 'get_approved_rule') and is_approved:
                    loop.approved_data = dialog.get_approved_rule()
                else:
                    loop.approved_data = is_approved
            else:
                loop.approved = False
                loop.approved_data = False
                
            # Resume the worker thread
            loop.quit()
        except Exception as e:
            logger.error(f"Error showing HitL dialog: {e}")
            loop.approved = False
            loop.approved_data = False
            loop.quit()

    # ──────────────────────────────────────────────
    # Layout and UI Control Methods
    # ──────────────────────────────────────────────
    
    @pyqtSlot(bool)
    def set_report_pane_visible(self, visible: bool):
        """
        Request to show or hide the report pane.
        
        Args:
            visible: True to show, False to hide
        """
        logger.info(f"Layout requested: set_report_pane_visible={visible}")
        self.layout_requested.emit(safe_json_dumps({
            "action": "set_report_pane_visible",
            "visible": visible
        }))

    def _save_semantic_rule(self, rule: dict):
        """
        Save a new semantic rule to the semantic rules file.
        
        This method appends the rule to configs/semantic_rules_custom.json,
        creating the file if it doesn't exist.
        
        Args:
            rule: Dictionary containing the semantic rule
        """
        import os
        from pathlib import Path
        
        # Path to custom semantic rules file
        rules_file = Path("configs/semantic_rules_custom.json")
        
        # Ensure configs directory exists
        rules_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing rules or create new structure
        if rules_file.exists():
            try:
                with open(rules_file, 'r', encoding='utf-8') as f:
                    rules_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load existing rules file: {e}. Creating new file.")
                rules_data = {"rules": []}
        else:
            rules_data = {"rules": []}
        
        # Add the new rule
        rules_data["rules"].append(rule)
        
        # Save back to file
        with open(rules_file, 'w', encoding='utf-8') as f:
            json.dump(rules_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved semantic rule to {rules_file}: {rule.get('rule_id')}")
    
    def _update_semantic_rule(self, rule_id: str, updated_rule: dict):
        """
        Update an existing semantic rule in the semantic rules file.
        
        This method searches for the rule by rule_id and updates it.
        It searches in both default and custom rules files.
        
        Args:
            rule_id: Unique identifier of the rule to update
            updated_rule: Dictionary containing the updated rule
        """
        from pathlib import Path
        
        # Paths to semantic rules files
        custom_rules_file = Path("configs/semantic_rules_custom.json")
        default_rules_file = Path("configs/semantic_rules_default.json")
        
        # Try to update in custom rules first
        updated = False
        
        if custom_rules_file.exists():
            try:
                with open(custom_rules_file, 'r', encoding='utf-8') as f:
                    rules_data = json.load(f)
                
                # Find and update the rule
                for i, rule in enumerate(rules_data.get("rules", [])):
                    if rule.get("rule_id") == rule_id:
                        rules_data["rules"][i] = updated_rule
                        updated = True
                        break
                
                if updated:
                    # Save back to file
                    with open(custom_rules_file, 'w', encoding='utf-8') as f:
                        json.dump(rules_data, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"Updated semantic rule in {custom_rules_file}: {rule_id}")
                    return
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error updating rule in custom rules file: {e}")
        
        # If not found in custom rules, check default rules
        # Note: We don't modify default rules, so we add the updated rule to custom rules
        if default_rules_file.exists():
            try:
                with open(default_rules_file, 'r', encoding='utf-8') as f:
                    default_rules_data = json.load(f)
                
                # Check if rule exists in default rules
                for rule in default_rules_data.get("rules", []):
                    if rule.get("rule_id") == rule_id:
                        # Rule found in default rules, add updated version to custom rules
                        logger.info(f"Rule {rule_id} found in default rules. Adding override to custom rules.")
                        self._save_semantic_rule(updated_rule)
                        return
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error reading default rules file: {e}")
        
        # If rule not found anywhere, log warning
        logger.warning(f"Rule {rule_id} not found in any rules file. Adding as new rule.")
        self._save_semantic_rule(updated_rule)

    # ──────────────────────────────────────────────
    # Evidence Preservation Methods
    # ──────────────────────────────────────────────
    
    def emit_truncation_warning(self, warning_data: dict):
        """
        Emit truncation warning to UI via QWebChannel.
        
        This method is called by the ContextManager when messages are
        summarized or truncated. It emits a signal that the React frontend
        can listen to for displaying truncation warnings.
        
        Args:
            warning_data: Dictionary containing warning information:
                {
                    "type": "truncation_warning",
                    "count": int,  # Number of messages summarized
                    "total_tokens": int,  # Current total token usage
                    "budget": int,  # Token budget for conversation history
                    "timestamp": str  # ISO timestamp
                }
                """
        try:
            # Emit warning signal with JSON-serialized data
            warning_json = safe_json_dumps(warning_data)
            self.status_updated.emit(warning_json)
            logger.info(f"Emitted truncation warning: {warning_data.get('count')} messages summarized")
        except Exception as e:
            logger.error(f"Error emitting truncation warning: {e}", exc_info=True)
    
    @pyqtSlot(str, result=str)
    def pin_message(self, message_id: str) -> str:
        """
        Pin a message to prevent summarization.
        
        Calls the HistoryManager to pin the specified message and returns
        the result to the React frontend.
        
        Args:
            message_id: Unique identifier of the message to pin
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "message_id": "msg_123",
                    "pinned": true
                },
                "error": null
            }
                """
        try:
            logger.info(f"Pinning message: {message_id}")
            
            # Validate context_manager is available
            if not self.context_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Validate history_manager is available
            if not hasattr(self.context_manager, 'history_manager') or not self.context_manager.history_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "HistoryManager not available"
                })
            
            # Pin the message through HistoryManager
            success = self.context_manager.history_manager.pin_message(message_id)
            
            if success:
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "message_id": message_id,
                        "pinned": True
                    },
                    "error": None
                })
            else:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": f"Message {message_id} not found"
                })
            
        except Exception as e:
            logger.error(f"Error pinning message: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(str, result=str)
    def unpin_message(self, message_id: str) -> str:
        """
        Unpin a message.
        
        Calls the HistoryManager to unpin the specified message and returns
        the result to the React frontend.
        
        Args:
            message_id: Unique identifier of the message to unpin
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "message_id": "msg_123",
                    "pinned": false
                },
                "error": null
            }
                """
        try:
            logger.info(f"Unpinning message: {message_id}")
            
            # Validate context_manager is available
            if not self.context_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Validate history_manager is available
            if not hasattr(self.context_manager, 'history_manager') or not self.context_manager.history_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "HistoryManager not available"
                })
            
            # Unpin the message through HistoryManager
            success = self.context_manager.history_manager.unpin_message(message_id)
            
            if success:
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "message_id": message_id,
                        "pinned": False
                    },
                    "error": None
                })
            else:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": f"Message {message_id} not found"
                })
            
        except Exception as e:
            logger.error(f"Error unpinning message: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
    @pyqtSlot(result=str)
    def get_gep_compliance_status(self) -> str:
        """
        GEP-8 (Machine-Readable Synthesis): return live per-rule
        Ghassan Elsman Protocol compliance state as a JSON string the React
        Protocol Compliance dashboard can render directly.

        Returns:
            JSON string of shape:
            {
                "success": true,
                "data": {
                    "rules": [
                        {"id": 0, "name": "...", "status": "PASS"|"PARTIAL"|"FAIL"|"N-A", "detail": "..."},
                        ...
                    ]
                },
                "error": null
            }
        """
        try:
            cm = self.context_manager
            if not cm:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })

            rules = []
            history = []
            try:
                history = list(getattr(cm.history_manager, "history", []))
            except Exception:
                history = []

            # ---- Rule 0: Case Awareness (Triage) ------------------------
            try:
                ctx_text = ""
                if hasattr(cm, "case_context_manager") and cm.case_context_manager:
                    ctx_text = cm.case_context_manager.get_context_for_prompt() or ""
                status = "PASS" if ctx_text.strip() else "FAIL"
                detail = f"case context is {len(ctx_text)} chars" if ctx_text else "no case context loaded"
            except Exception as e:
                status, detail = "FAIL", f"case context error: {e}"
            rules.append({"id": 0, "name": "Case Awareness (Triage)",
                          "status": status, "detail": detail})

            # ---- Rule 1: Pre-Flight Integrity (Ping) --------------------
            try:
                ok = cm.model_router.validate_connectivity()
                status = "PASS" if ok else "FAIL"
                detail = "active backend reachable" if ok else "validate_connectivity() returned False"
            except Exception as e:
                status, detail = "FAIL", f"ping error: {e}"
            rules.append({"id": 1, "name": "Pre-Flight Integrity (Ping)",
                          "status": status, "detail": detail})

            # ---- Rule 2: Evidence Anchoring (Snippets) ------------------
            # Reflects the REAL evidence pipeline: EvidenceDetector tags
            # messages with preserve_evidence / evidence_patterns metadata via
            # HistoryManager. (The Eye does not emit literal <evidence anchor=>
            # tags, so keying on those produced a perpetually misleading status.)
            with_evidence = 0
            for m in history[-25:]:
                meta = m.get("metadata") or {}
                if (meta.get("preserve_evidence")
                        or meta.get("evidence_matches")
                        or meta.get("evidence_patterns")):
                    with_evidence += 1
            if with_evidence > 0:
                status = "PASS"
                detail = f"{with_evidence} of last {min(25, len(history))} messages flagged + preserved by the evidence detector"
            else:
                status = "N-A"
                detail = "no messages with detected forensic evidence yet"
            rules.append({"id": 2, "name": "Evidence Anchoring (Snippets)",
                          "status": status, "detail": detail})

            # ---- Rule 3: Chain of Custody (Audit Trail) -----------------
            # The TruncationAuditor writes truncation_audit.log on the first
            # preservation/truncation event. Absence of the file when the
            # auditor is active just means no such event has occurred yet —
            # that is N-A, not a compliance FAILURE. FAIL only if the auditor
            # could not be initialized at all.
            logs_dir = getattr(cm, "logs_dir", None)
            auditor = getattr(cm, "truncation_auditor", None)
            audit_log = os.path.join(str(logs_dir), "truncation_audit.log") if logs_dir else None
            if auditor is None:
                status = "FAIL"
                detail = "truncation auditor not initialized (no EYE_Logs / case directory)"
            elif audit_log and os.path.exists(audit_log) and os.path.getsize(audit_log) > 0:
                # Actually VERIFY the tamper-evident chain — not just file existence.
                try:
                    ok = bool(auditor.verify_chain()) if hasattr(auditor, "verify_chain") else None
                except Exception:
                    ok = None
                if ok is True:
                    status = "PASS"
                    detail = f"audit hash chain VERIFIED ({os.path.getsize(audit_log)} B)"
                elif ok is False:
                    status = "FAIL"
                    detail = "audit hash chain BROKEN — tampering detected"
                else:
                    status = "PASS"
                    detail = f"{audit_log} ({os.path.getsize(audit_log)} B)"
            else:
                status = "N-A"
                detail = "audit trail active; no preservation/truncation events logged yet"
            rules.append({"id": 3, "name": "Chain of Custody (Audit Trail)",
                          "status": status, "detail": detail})

            # ---- Rule 4: Non-Repudiation (Hash-Linked IDs) --------------
            sample = [m.get("id", "") for m in history[-10:]]
            hex_pat = re.compile(r"^[0-9a-f]{16}$")
            sha_count = sum(1 for i in sample if hex_pat.match(i or ""))
            if not sample:
                status, detail = "N-A", "no messages in history yet"
            elif sha_count == len(sample):
                status = "PASS"
                detail = f"all {sha_count} of last {len(sample)} message IDs are 16-char SHA"
            elif sha_count > 0:
                status = "PARTIAL"
                detail = f"{sha_count} of {len(sample)} IDs are SHA; rest are legacy"
            else:
                status = "FAIL"
                detail = "no message IDs match the SHA-16 chain format"
            rules.append({"id": 4, "name": "Non-Repudiation (Hash-Linked IDs)",
                          "status": status, "detail": detail})

            # ---- Rule 5: Context Preservation (Pinning) -----------------
            pinned = sum(1 for m in history
                         if (m.get("metadata") or {}).get("pinned")
                         or (m.get("metadata") or {}).get("preserve_evidence"))
            handler_present = hasattr(cm.history_manager, "pin_message")
            if not handler_present:
                status, detail = "FAIL", "history_manager.pin_message() missing"
            elif pinned > 0:
                status = "PASS"
                detail = f"{pinned} message(s) pinned / evidence-preserved"
            else:
                status = "N-A"
                detail = "pin handler present; no messages pinned yet"
            rules.append({"id": 5, "name": "Context Preservation (Pinning)",
                          "status": status, "detail": detail})

            # ---- Rule 6: Tool Traceability ------------------------------
            last_tool = None
            for m in reversed(history):
                if (m.get("metadata") or {}).get("is_tool_result"):
                    last_tool = m
                    break
            if last_tool is None:
                status, detail = "N-A", "no tool-result messages in history yet"
            elif (last_tool.get("content") or "").lstrip().startswith("[Tool "):
                status = "PASS"
                detail = "latest tool-result message begins with [Tool N/M: ...] header"
            else:
                status = "PARTIAL"
                detail = "tool-result messages exist but header is not in content (metadata-only)"
            rules.append({"id": 6, "name": "Tool Traceability",
                          "status": status, "detail": detail})

            # ---- Rule 7: Machine-Readable Synthesis (Audit JSON) --------
            # audit_trail.json is generated on demand (the "Export Audit JSON"
            # action / export_audit_trail). Not-yet-exported is N-A, not a
            # FAILURE — the capability is present whenever the auditor is.
            audit_json = os.path.join(str(logs_dir), "audit_trail.json") if logs_dir else None
            if audit_json and os.path.exists(audit_json) and os.path.getsize(audit_json) > 0:
                status = "PASS"
                detail = f"{audit_json} ({os.path.getsize(audit_json)} B)"
            elif auditor is not None:
                status = "N-A"
                detail = "machine-readable audit export available on demand; not generated yet"
            else:
                status = "FAIL"
                detail = "auditor not initialized; cannot produce machine-readable synthesis"
            rules.append({"id": 7, "name": "Machine-Readable Synthesis",
                          "status": status, "detail": detail})

            # =================================================================
            # Write-side rules — apply to the four correlation_create_*
            # and correlation_edit_* tools handled by
            # CorrelationConfigHandlers. The status here is a rolling
            # summary across all EYE-authored Wings and Mappings in the
            # active case.
            # =================================================================
            wings_dir = None
            mappings_dir = None
            case_root = getattr(cm, "case_directory", None) or getattr(
                getattr(cm, "case_directory_manager", None), "case_directory", None
            )
            if case_root:
                wings_dir = os.path.join(str(case_root), "Correlation", "wings")
                mappings_dir = os.path.join(str(case_root), "Correlation",
                                            "semantic_mappings", "eye")

            eye_artifact_paths = []
            for d in (wings_dir, mappings_dir):
                if d and os.path.isdir(d):
                    for fn in os.listdir(d):
                        if fn.endswith(".json"):
                            eye_artifact_paths.append(os.path.join(d, fn))

            # Load just the authorship blocks (cheap, no full
            # deserialization). Best-effort — never raises.
            authorship_blocks = []
            for p in eye_artifact_paths:
                try:
                    import json as _json
                    with open(p, "r", encoding="utf-8") as f:
                        raw = _json.load(f)
                    auth = (raw.get("eye_authorship") or {})
                    if auth and str(auth.get("created_by", "")).startswith("eye"):
                        authorship_blocks.append((p, auth))
                except Exception:
                    continue

            # ---- Rule 8: Reason-Required (write-side) --------------------
            if not authorship_blocks:
                status, detail = "N-A", "no EYE-authored Wings or Mappings in this case yet"
            else:
                missing = [p for p, a in authorship_blocks if not (a.get("reason") or "").strip()]
                if missing:
                    status = "FAIL"
                    detail = f"{len(missing)} EYE-authored artifact(s) lack a populated reason"
                else:
                    status = "PASS"
                    detail = f"every EYE-authored artifact carries a non-empty reason ({len(authorship_blocks)} item(s))"
            rules.append({"id": 8, "name": "Reason-Required (write-side)",
                          "status": status, "detail": detail})

            # ---- Rule 9: Evidence-Link (write-side) ---------------------
            if not authorship_blocks:
                status, detail = "N-A", "no EYE-authored artifacts to evaluate"
            else:
                no_evidence = [p for p, a in authorship_blocks if not a.get("related_evidence")]
                partial = [p for p, a in authorship_blocks
                           if (a.get("unresolved_evidence_refs") or [])]
                if no_evidence:
                    status = "FAIL"
                    detail = f"{len(no_evidence)} artifact(s) missing related_evidence (should be impossible — handler bug)"
                elif partial:
                    status = "PARTIAL"
                    detail = f"{len(partial)} artifact(s) have unresolved evidence refs (soft-warning)"
                else:
                    status = "PASS"
                    detail = f"all {len(authorship_blocks)} artifact(s) have fully resolved evidence refs"
            rules.append({"id": 9, "name": "Evidence-Link (write-side)",
                          "status": status, "detail": detail})

            # ---- Rule 10: Eye-Stamped ----------------------------------
            if not authorship_blocks:
                status, detail = "N-A", "no EYE-authored artifacts to evaluate"
            else:
                unstamped = [p for p, a in authorship_blocks
                             if not (a.get("created_by") or "").startswith("eye")
                             or not a.get("created_at")]
                if unstamped:
                    status = "FAIL"
                    detail = f"{len(unstamped)} artifact(s) lack a fully populated EyeAuthorship block"
                else:
                    status = "PASS"
                    detail = f"every EYE-authored artifact carries a complete EyeAuthorship block ({len(authorship_blocks)} item(s))"
            rules.append({"id": 10, "name": "Eye-Stamped",
                          "status": status, "detail": detail})

            # =================================================================
            # GEP tagging — label each operating/write rule with the GEP
            # principle(s) it upholds, so the dashboard shows the protocol link.
            # =================================================================
            _GEP_BY_RULE_ID = {
                0: ["GEP-1"], 1: ["GEP-1"], 2: ["GEP-2"], 3: ["GEP-7", "GEP-8"],
                4: ["GEP-7"], 5: ["GEP-6"], 6: ["GEP-8"], 7: ["GEP-8"],
                8: ["GEP-9"], 9: ["GEP-2", "GEP-9"], 10: ["GEP-7", "GEP-9"],
            }
            for r in rules:
                r.setdefault("gep", _GEP_BY_RULE_ID.get(r.get("id"), []))

            # =================================================================
            # Eye-process rows — surface the live status of the newer subsystems
            # so the dashboard reflects the WHOLE current Eye. Each is best-effort.
            # =================================================================
            # ---- Conversation Memory (two-stage policy) ----
            try:
                rcfg = getattr(cm, "reasoning_config", None) or {}
                win = rcfg.get("history_window_turns")
                if win:
                    buf = rcfg.get("enable_summary_buffer", True)
                    status = "PASS"
                    detail = (f"two-stage policy active (window={win} turns, summary buffer "
                              f"{'on' if buf else 'off'}); pinned/evidence messages protected")
                else:
                    status, detail = "N-A", "conversation memory policy not configured"
            except Exception as e:
                status, detail = "N-A", f"memory status error: {e}"
            rules.append({"id": "mem", "name": "Conversation Memory (2-Stage)",
                          "status": status, "detail": detail, "gep": ["GEP-6"]})

            # ---- Conversation Recall (long-term memory) ----
            try:
                idx = getattr(getattr(cm, "rag_service", None), "conversation_index", None)
                n = len(idx) if isinstance(idx, list) else 0
                arch = os.path.join(str(logs_dir), "eye_conversation_archive.jsonl") if logs_dir else None
                if n > 0:
                    status, detail = "PASS", f"{n} earlier turn(s) archived and retrievable on demand"
                elif arch and os.path.exists(arch):
                    status, detail = "PASS", "conversation archive present (recall index built on load)"
                else:
                    status, detail = "N-A", "no conversation turns evicted/archived yet"
            except Exception as e:
                status, detail = "N-A", f"recall status error: {e}"
            rules.append({"id": "recall", "name": "Conversation Recall (Long-Term Memory)",
                          "status": status, "detail": detail, "gep": ["GEP-6", "GEP-8"]})

            # ---- Completeness & Coverage (GEP-6) ----
            try:
                cov = os.path.join(str(logs_dir), "eye_coverage_log.jsonl") if logs_dir else None
                if cov and os.path.exists(cov) and os.path.getsize(cov) > 0:
                    status = "PASS"
                    detail = "per-answer coverage disclosed + logged (consulted vs. available, sample vs. full)"
                else:
                    status = "N-A"
                    detail = "coverage disclosure active; no answered evidence turn yet"
            except Exception as e:
                status, detail = "N-A", f"coverage status error: {e}"
            rules.append({"id": "coverage", "name": "Completeness & Coverage",
                          "status": status, "detail": detail, "gep": ["GEP-6"]})

            # ---- Result Cache (reproducible reuse) ----
            try:
                has_cache = getattr(cm, "result_cache", None) is not None
                cache_file = os.path.join(str(logs_dir), "eye_result_cache.jsonl") if logs_dir else None
                if cache_file and os.path.exists(cache_file):
                    status = "PASS"
                    detail = "identical queries reused from the per-case cache (reproducible results)"
                elif has_cache:
                    status, detail = "N-A", "result cache active; nothing cached yet"
                else:
                    status, detail = "N-A", "no result cache (no case directory)"
            except Exception as e:
                status, detail = "N-A", f"cache status error: {e}"
            rules.append({"id": "cache", "name": "Result Cache (Reproducible Reuse)",
                          "status": status, "detail": detail, "gep": ["GEP-7", "GEP-8"]})

            # ---- Semantic Search (embeddings) ----
            try:
                esvc = getattr(cm, "evidence_index_service", None)
                avail = bool(esvc and esvc.available())
                if avail:
                    status = "PASS"
                    detail = "semantic discovery available; candidates confirmed with exact SQL (SQL authoritative)"
                else:
                    status, detail = "N-A", "embeddings disabled; SQL + BM25 in use (semantic search off)"
            except Exception as e:
                status, detail = "N-A", f"semantic status error: {e}"
            rules.append({"id": "semantic", "name": "Semantic Search (Embeddings)",
                          "status": status, "detail": detail, "gep": ["GEP-1", "GEP-8"]})

            # ---- Evidence Seal Hash Chain ----
            try:
                seal = getattr(cm, "evidence_seal", None)
                seal_file = os.path.join(str(logs_dir), "eye_payload_seal.jsonl") if logs_dir else None
                if seal_file and os.path.exists(seal_file) and os.path.getsize(seal_file) > 0:
                    verified = None
                    try:
                        if seal is not None and hasattr(seal, "verify_chain"):
                            verified = bool(seal.verify_chain())
                    except Exception:
                        verified = None
                    if verified is True:
                        status, detail = "PASS", "payload seal hash chain VERIFIED (tamper-evident)"
                    elif verified is False:
                        status, detail = "FAIL", "payload seal hash chain BROKEN — tampering detected"
                    else:
                        status = "PASS"
                        detail = "every model payload sealed (SHA-256 hash chain) to eye_payload_seal.jsonl"
                elif seal is not None:
                    status, detail = "N-A", "evidence seal active; no payloads sealed yet"
                else:
                    status, detail = "FAIL", "evidence seal writer not initialized"
            except Exception as e:
                status, detail = "N-A", f"seal status error: {e}"
            rules.append({"id": "seal", "name": "Evidence Seal Hash Chain",
                          "status": status, "detail": detail, "gep": ["GEP-7"]})

            # =================================================================
            # Full GEP protocol — a live status for ALL 10 principles, rolled up
            # from the mechanisms above (structural PASS for always-on guarantees).
            # =================================================================
            _GEP_STRUCTURAL = {
                "GEP-1": ("Evidence Primacy",
                          "Read-only DB access, schema-grounded SQL, pre-flight connectivity ping, proactive investigation."),
                "GEP-2": ("Traceability",
                          "EvidenceSeal provenance (database:table:rowid), evidence anchoring, write-side evidence links."),
                "GEP-3": ("Specificity & Chronology",
                          "Per-answer timestamp check; exact UTC/identifier reporting; chronological ordering."),
                "GEP-4": ("Cross-Corroboration",
                          "Multi-source sweep + cross-iteration evidence ledger; conflicts surfaced."),
                "GEP-5": ("Premise Verification",
                          "Planning premises (verify: checklist) + sealed reasoning trace."),
                "GEP-6": ("Completeness",
                          "No-silent-truncation guard, map-reduce, two-stage memory, coverage disclosure + per-answer GEP-6 check."),
                "GEP-7": ("Integrity & Non-Repudiation",
                          "Read-only evidence, SHA-256 hash-chained IDs, EvidenceSeal payload hash chain."),
                "GEP-8": ("Transparency & Explainability",
                          "Tool traceability, step/dialogue logs, machine-readable compliance export."),
                "GEP-9": ("Human Authority",
                          "HITL approvals; write-side authorship (reason + evidence + Eye-stamp); read-only on non-Eye items."),
                "GEP-10": ("Defensibility",
                           "Objective, precise output structured for independent review; "
                           "structured report blocks, per-answer direct-answer check."),
            }
            # An honest status needs a real BASIS — never a bare structural PASS:
            #   verified   = rolled up from live rules (incl. genuinely verified
            #                hash chains; a BROKEN chain propagates to FAIL).
            #   config     = gated by a reasoning setting; N-A (named) when disabled.
            #   per-answer = graded each turn (see Per-Answer GEP Compliance).
            #   structural = an always-on guarantee inherent to the build.
            _rcfg = getattr(cm, "reasoning_config", None)
            _rcfg = _rcfg if isinstance(_rcfg, dict) else {}
            _CONFIG_GATED = {  # principle -> reasoning_config flag (default ON)
                "GEP-4": "enable_decomposition",
                "GEP-5": "enable_premise_verification",
            }
            gep_principles = []
            for gid, (gname, gdesc) in _GEP_STRUCTURAL.items():
                upheld = [r for r in rules if gid in (r.get("gep") or [])]
                detail = gdesc
                if upheld:
                    sts = [r["status"] for r in upheld]
                    if any(s == "FAIL" for s in sts):
                        st = "FAIL"
                    elif any(s == "PASS" for s in sts):
                        st = "PASS"
                    elif any(s == "PARTIAL" for s in sts):
                        # A principle upheld only by partially-met rules is PARTIAL,
                        # not N-A — it is actively (if incompletely) met, not dormant.
                        st = "PARTIAL"
                    else:
                        st = "N-A"
                    basis = "verified"
                    upheld_by = [r["name"] for r in upheld]
                elif gid in _CONFIG_GATED:
                    flag = _CONFIG_GATED[gid]
                    on = bool(_rcfg.get(flag, True))
                    st = "PASS" if on else "N-A"
                    basis = "config"
                    detail = gdesc + ("" if on else f" — DISABLED ({flag}=false)")
                    upheld_by = []
                elif gid == "GEP-3":
                    st, basis, upheld_by = "PASS", "per-answer", []
                    detail = gdesc + " — graded each answer (see Per-Answer GEP Compliance)."
                else:
                    # Always-on structural guarantee (e.g. GEP-10 output structured
                    # for independent review).
                    st, basis, upheld_by = "PASS", "structural", []
                gep_principles.append({"id": gid, "name": gname, "status": st, "basis": basis,
                                       "detail": detail, "upheld_by": upheld_by})

            return safe_json_dumps({
                "success": True,
                "data": {"rules": rules, "gep_principles": gep_principles},
                "error": None
            })
        except Exception as e:
            logger.error(f"get_gep_compliance_status failed: {e}", exc_info=True)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": str(e)
            })

    @pyqtSlot(result=str)
    def get_activity_audit(self) -> str:
        """
        Build a chronological activity log for the GEP Compliance window.

        Merges three streams the EYE already records:
          - conversation_history       -> user queries, AI responses, tool calls
          - tool-result messages       -> evidence the AI pulled while answering
          - report_engine.edit_history -> blocks added / edited / deleted

        Each entry is a uniform record:
            {
                "timestamp": ISO-8601 string,
                "type":      "user_query"        |
                             "assistant_response" |
                             "tool_result"        |
                             "report_added"       |
                             "report_edited"      |
                             "report_deleted"     |
                             "report_other",
                "summary":   short label (one line),
                "detail":    longer prose / preview,
                "tools":     [tool names invoked] or null,
                "block_id":  block touched in the report, or null,
                "iteration": agent loop iteration, or null
            }

        Returns the standard {success, data: {entries: [...]}, error} envelope.
        """
        try:
            cm = self.context_manager
            if not cm:
                return safe_json_dumps({"success": False, "data": None,
                                        "error": "ContextManager not initialized"})

            entries = []

            # ----- Conversation stream --------------------------------
            history = list(getattr(cm, "conversation_history", []) or [])
            for m in history:
                role = m.get("role")
                meta = m.get("metadata") or {}
                content = (m.get("content") or "").strip()
                ts = meta.get("timestamp") or m.get("timestamp") or ""

                # Tool-result messages carry the evidence the AI pulled.
                # query_processor stores these as role="system" with
                # is_tool_result=True in metadata, so we must check the flag
                # BEFORE the role filter (otherwise system rows fall through).
                if meta.get("is_tool_result"):
                    tools = meta.get("tool_names") or []
                    iteration = meta.get("iteration")
                    preview = content[:1200] + ("…" if len(content) > 1200 else "")
                    entries.append({
                        "timestamp": ts,
                        "type": "tool_result",
                        "summary": "Evidence: " + (", ".join(t for t in tools if t) or "tool result"),
                        "detail": preview,
                        "tools": tools or None,
                        "block_id": None,
                        "iteration": iteration,
                    })
                    continue

                if role == "user":
                    preview = content[:600] + ("…" if len(content) > 600 else "")
                    is_internal = meta.get("internal")
                    
                    entries.append({
                        "timestamp": ts,
                        "type": "tool_call" if is_internal else "user_query",
                        "summary": "Internal AI Consultation: " + (preview.splitlines()[0] if preview else "")[:150] if is_internal else (preview.splitlines()[0] if preview else "(empty query)")[:200],
                        "detail": preview,
                        "tools": None,
                        "block_id": None,
                        "iteration": None,
                    })
                elif role == "assistant":
                    preview = content[:800] + ("…" if len(content) > 800 else "")
                    entries.append({
                        "timestamp": ts,
                        "type": "assistant_response",
                        "summary": (preview.splitlines()[0] if preview else "(no text response)")[:200],
                        "detail": preview,
                        "tools": None,
                        "block_id": None,
                        "iteration": meta.get("iteration"),
                    })

                    # Every tool the EYE *ran* in this assistant turn is
                    # stored as metadata.tool_calls (name + parameters,
                    # e.g. SQL string, search filters). Surface each one
                    # as its own audit entry so the user can see the
                    # actual queries the agent issued.
                    tool_calls = meta.get("tool_calls") or []
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        tname = call.get("name") or "unknown_tool"
                        params = call.get("parameters") or call.get("arguments") or {}
                        # Build a one-line summary highlighting the most
                        # query-like parameter when present.
                        param_preview = ""
                        if isinstance(params, dict):
                            for key in ("sql", "query", "search", "filter", "pattern", "path", "expression"):
                                v = params.get(key)
                                if v:
                                    param_preview = f"{key}={str(v)[:140]}"
                                    break
                            if not param_preview and params:
                                # Fall back to first non-empty key/value pair
                                k0, v0 = next(iter(params.items()))
                                param_preview = f"{k0}={str(v0)[:140]}"
                        try:
                            full_params = json.dumps(params, ensure_ascii=False, indent=2)
                        except Exception:
                            full_params = str(params)
                        entries.append({
                            "timestamp": ts,
                            "type": "tool_call",
                            "summary": f"{tname}({param_preview})" if param_preview else f"{tname}()",
                            "detail": full_params[:2000],
                            "tools": [tname],
                            "block_id": None,
                            "iteration": meta.get("iteration"),
                        })
                # system / other roles are intentionally skipped — they're
                # plumbing, not user-facing activity (tool results above
                # already covered the is_tool_result system rows).

            # ----- Report edit stream ---------------------------------
            re_engine = getattr(cm, "report_engine", None)
            edit_history = list(getattr(re_engine, "edit_history", []) or []) if re_engine else []
            ACTION_TYPE = {
                "add": "report_added",
                "append": "report_added",
                "create": "report_added",
                "add_section": "report_added",
                "add_data_table": "report_added",
                "add_chart": "report_added",
                "add_image": "report_added",
                "add_evidence": "report_added",
                "edit": "report_edited",
                "edit_section": "report_edited",
                "update": "report_edited",
                "delete": "report_deleted",
                "delete_section": "report_deleted",
                "remove": "report_deleted",
            }
            for ev in edit_history:
                action = (ev.get("action") or "").lower()
                etype = ACTION_TYPE.get(action, "report_other")
                details = ev.get("details") or {}
                title = (details.get("title")
                         or details.get("caption")
                         or details.get("name")
                         or ev.get("block_id")
                         or "report block")
                entries.append({
                    "timestamp": ev.get("timestamp", ""),
                    "type": etype,
                    "summary": f"{action or 'report change'}: {title}",
                    "detail": json.dumps(details, ensure_ascii=False)[:500] if details else "",
                    "tools": None,
                    "block_id": ev.get("block_id"),
                    "iteration": None,
                })

            # ----- Narrative Map stream -------------------------------
            # Surface every sealed Narrative Map change (by the Eye OR the
            # investigator) so the Compliance window shows it alongside queries,
            # evidence and report edits — same chain-of-custody feed.
            nms = getattr(cm, "narrative_map_service", None)
            if nms is not None:
                try:
                    for r in (nms.recent_audit(limit=200) or []):
                        gep = r.get("gep", {}) or {}
                        actor = "Eye" if r.get("actor") == "eye" else "Investigator"
                        detail = (
                            f"{r.get('reason', '') or '(no reason)'}\n"
                            f"GEP  R9:{gep.get('r9','-')}  R10:{gep.get('r10','-')}  R11:{gep.get('r11','-')}\n"
                            f"{r.get('prevHash','')[:8]} -> {r.get('hash','')[:12]}"
                        )
                        entries.append({
                            "timestamp": r.get("ts", ""),
                            "type": "narrative_map",
                            "summary": f"#{r.get('seq','?')} {r.get('action','')} · {r.get('target','')} ({actor})",
                            "detail": detail,
                            "tools": None,
                            "block_id": None,
                            "iteration": None,
                            # Node id for deep-linking to the map's detail panel.
                            "card_id": r.get("card_id") or "",
                        })
                except Exception as e:
                    logger.debug(f"narrative-map activity stream skipped: {e}")

            # ----- Imported evidence stream ---------------------------
            # Chain of custody: every imported database/document appears in the
            # Compliance feed with its SHA-256 hashes (source + in-case copy).
            try:
                manifest = self._imported_evidence_manifest()
                if manifest is not None:
                    for e in manifest.list_entries(verify=False):
                        sha = e.get("sha256") or "?"
                        sha_src = e.get("sha256_source")
                        detail = (f"Source: {e.get('source_path') or '(pre-manifest import)'}\n"
                                  f"In-case copy: {e.get('dest_path')}\n"
                                  f"SHA-256 (in-case): {sha}")
                        if sha_src:
                            detail += f"\nSHA-256 (source): {sha_src}"
                        if e.get("row_count"):
                            detail += f"\nRows: {e['row_count']:,}"
                        if e.get("size_bytes"):
                            detail += f"\nSize: {e['size_bytes']:,} bytes"
                        entries.append({
                            "timestamp": e.get("imported_at", ""),
                            "type": "evidence_import",
                            "summary": f"Imported evidence: {e.get('name')} ({e.get('kind')})",
                            "detail": detail,
                            "tools": None,
                            "block_id": None,
                            "iteration": None,
                        })
            except Exception as e:
                logger.debug(f"imported-evidence activity stream skipped: {e}")

            # ----- Sort chronologically (entries with missing timestamps
            #       float to the end so they don't break the ordering).
            entries.sort(key=lambda e: e.get("timestamp") or "9999")

            # Perf: return only the most recent N for display; report the true count.
            _AUDIT_CAP = 300
            total_audit = len(entries)
            entries = entries[-_AUDIT_CAP:]
            return safe_json_dumps({
                "success": True,
                "data": {"entries": entries, "count": total_audit},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_activity_audit failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_step_history(self) -> str:
        """
        Return the persisted pipeline-step execution history for the Compliance
        panel, GROUPED PER STEP. Each step kind+label gets its own entry whose
        ``runs`` list holds every individual execution with its timestamp and
        status — so the investigator sees a per-step list of every time that
        step ran.

        Reads ``<case>/EYE_Logs/eye_step_log.jsonl`` (written by
        QueryProcessor._persist_step). Returns the standard envelope:

            {
                "success": true,
                "data": {
                    "steps": [
                        {
                            "key": "rag::Retrieving artifact knowledge",
                            "type": "rag",
                            "label": "Retrieving artifact knowledge",
                            "run_count": 3,
                            "last_status": "done",
                            "last_timestamp": "2026-05-31T...",
                            "runs": [
                                {"timestamp": "...", "status": "done",
                                 "iteration": null, "query": "...", "detail": null},
                                ...
                            ]
                        },
                        ...
                    ],
                    "total_runs": 12
                },
                "error": null
            }
        """
        try:
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({
                    "success": True,
                    "data": {"steps": [], "total_runs": 0},
                    "error": None,
                })

            log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_step_log.jsonl")
            if not os.path.exists(log_path):
                return safe_json_dumps({
                    "success": True,
                    "data": {"steps": [], "total_runs": 0},
                    "error": None,
                })

            grouped = {}
            order = []
            total_runs = 0
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        step = json.loads(line)
                    except Exception:
                        continue
                    total_runs += 1
                    stype = step.get("type", "step")
                    label = step.get("label", "").strip()
                    key = f"{stype}::{label}"
                    if key not in grouped:
                        grouped[key] = {
                            "key": key,
                            "type": stype,
                            "label": label,
                            "run_count": 0,
                            "last_status": None,
                            "last_timestamp": None,
                            "runs": [],
                        }
                        order.append(key)
                    g = grouped[key]
                    run = {
                        "timestamp": step.get("timestamp", ""),
                        "status": step.get("status", ""),
                        "iteration": step.get("iteration"),
                        "query": step.get("query", ""),
                        "detail": step.get("detail"),
                        "tool": step.get("tool"),
                    }
                    g["runs"].append(run)
                    g["run_count"] += 1
                    g["last_status"] = run["status"]
                    g["last_timestamp"] = run["timestamp"]

            steps = [grouped[k] for k in order]
            # Perf: cap each step's run list to the most recent N (run_count stays true).
            _RUNS_CAP = 100
            for g in steps:
                if len(g["runs"]) > _RUNS_CAP:
                    g["runs"] = g["runs"][-_RUNS_CAP:]

            return safe_json_dumps({
                "success": True,
                "data": {"steps": steps, "total_runs": total_runs},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_step_history failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_payload_seals(self) -> str:
        """
        Return the chain-of-custody Evidence Seals — one per LLM payload — so the
        Compliance panel can prove exactly which bytes the model saw. Each record
        carries the SHA-256 of the exact injected payload, token count, model +
        context limit, the hash chain (prev_seal_hash -> seal_hash), and the
        provenance of the evidence rows (database:table:rowid + computed offset
        where derivable).

        Reads ``<case>/EYE_Logs/eye_payload_seal.jsonl`` (written by EvidenceSeal).
        Also reports whether the hash chain verifies end-to-end.
        """
        try:
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({"success": True, "data": {"seals": [], "total_seals": 0, "chain_valid": True}, "error": None})
            log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_payload_seal.jsonl")
            if not os.path.exists(log_path):
                return safe_json_dumps({"success": True, "data": {"seals": [], "total_seals": 0, "chain_valid": True}, "error": None})

            seals = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        seals.append(json.loads(line))
                    except Exception:
                        continue

            # Verify the tamper-evident hash chain via the single source of truth
            # on the EvidenceSeal writer (same logic, reused by the compliance
            # dashboard). Falls back to a local walk only if no writer is wired.
            seal_writer = getattr(self.context_manager, "evidence_seal", None) if self.context_manager else None
            if seal_writer is not None and hasattr(seal_writer, "verify_chain"):
                chain_valid = bool(seal_writer.verify_chain())
            else:
                chain_valid = True
                prev = ""
                for s in seals:
                    p_hash = s.get("payload_sha256", "")
                    m_hash = s.get("metadata_sha256", "")
                    if m_hash:
                        expected = hashlib.sha256((prev + p_hash + m_hash).encode("utf-8", errors="replace")).hexdigest()
                    else:
                        expected = hashlib.sha256((prev + p_hash).encode("utf-8", errors="replace")).hexdigest()
                    if s.get("prev_seal_hash", "") != prev or s.get("seal_hash") != expected:
                        chain_valid = False
                    prev = s.get("seal_hash", "")

            total_seals = len(seals)
            seals.reverse()  # most recent first for display
            # Perf: chain verified over the FULL log above; display only recent N.
            _SEALS_CAP = 200
            seals = seals[:_SEALS_CAP]
            return safe_json_dumps({
                "success": True,
                "data": {"seals": seals, "total_seals": total_seals, "chain_valid": chain_valid},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_payload_seals failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_truncation_events(self) -> str:
        """
        Return the chain-of-custody audit events — PRESERVED / SUMMARIZED /
        TRUNCATED / PINNED / UNPINNED / REFUSED_OVERFLOW — so the Compliance
        panel can show every context-integrity decision the Eye made (including
        self-heal compaction and hard refusals).

        Reads via TruncationAuditor.get_events(). Envelope:
            { success, data: { events: [...], counts: {ACTION: n}, total: N,
                               chain_valid: bool }, error }
        Most-recent first. ``chain_valid`` reports whether the audit log's
        tamper-evident hash chain verifies end-to-end (parallel to
        get_payload_seals).
        """
        try:
            cm = self.context_manager
            auditor = getattr(cm, "truncation_auditor", None) if cm else None
            if not auditor:
                return safe_json_dumps({"success": True, "data": {"events": [], "counts": {}, "total": 0, "chain_valid": True}, "error": None})
            events = auditor.get_events()
            counts = {}
            for e in events:
                a = e.get("action", "?")
                counts[a] = counts.get(a, 0) + 1
            # Perf: counts computed over ALL events above; display only recent N.
            events_recent_first = list(reversed(events))[:300]
            try:
                chain_valid = auditor.verify_chain()
            except Exception:
                chain_valid = False
            return safe_json_dumps({
                "success": True,
                "data": {"events": events_recent_first, "counts": counts, "total": len(events), "chain_valid": chain_valid},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_truncation_events failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_payload_cut_details(self) -> str:
        """Flatten the per-payload ``cut_details`` across all Evidence Seals into
        one list for the Compliance panel's dedicated "Processed vs Dropped
        Payload" section.

        Each entry carries: the seal seq + timestamp + phase, the action
        (SUMMARIZED / TRUNCATED / TRUNCATED_TOOL_OUTPUT), the explicit char-range
        of the cut (``cut_range``), the bounded inline previews of the kept and
        dropped content, the full length + SHA-256 + sidecar reference for each
        portion, and the forensic-artifact offsets found in each
        (``processed_file_offsets`` / ``dropped_file_offsets``). Most-recent
        first. Reads ``<case>/EYE_Logs/eye_payload_seal.jsonl``.
        """
        try:
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({"success": True, "data": {"cuts": [], "total": 0}, "error": None})
            log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_payload_seal.jsonl")
            if not os.path.exists(log_path):
                return safe_json_dumps({"success": True, "data": {"cuts": [], "total": 0}, "error": None})

            records = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue

            cuts = []
            # (a) Self-heal / tool-cap cuts already attached to each seal.
            for rec in records:
                for detail in (rec.get("cut_details") or []):
                    merged = dict(detail)
                    merged["seq"] = rec.get("seq")
                    merged["timestamp"] = rec.get("timestamp")
                    merged["phase"] = rec.get("phase")
                    merged["query"] = rec.get("query")
                    merged["model"] = rec.get("model")
                    cuts.append(merged)

            # (b) Budget trims (system prompt / RAG / history) from the audit log,
            # and (c) the refused payload itself — synthesized so this section
            # reflects EVERY drop, each grouped under its question.
            from eye.services.cut_merge import assembly_cuts_from_events, refused_payload_cuts
            try:
                auditor = getattr(cm, "truncation_auditor", None)
                events = auditor.get_events() if auditor else []
            except Exception:
                events = []
            cuts.extend(assembly_cuts_from_events(events, records))
            cuts.extend(refused_payload_cuts(records))

            # Most recent first for display; cap to recent N.
            cuts.sort(key=lambda c: c.get("timestamp") or "", reverse=True)
            total_cuts = len(cuts)
            cuts = cuts[:300]
            return safe_json_dumps({
                "success": True,
                "data": {"cuts": cuts, "total": total_cuts},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_payload_cut_details failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(str, result=str)
    def get_dropped_payload_full(self, sha256: str) -> str:
        """Return the COMPLETE dropped (or processed) payload bytes for one cut,
        read on demand from its sidecar file. The Compliance panel calls this
        when the investigator expands a cut whose inline preview was bounded.

        ``sha256`` is the content hash recorded on the cut detail
        (``cut_content_sha256`` / ``processed_content_sha256``). Path-validated to
        stay within ``EYE_Logs/dropped_payloads`` — only a 64-char hex hash maps
        to a file, so traversal is impossible.
        """
        try:
            if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
                return safe_json_dumps({"success": False, "data": None, "error": "Invalid content hash."})
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({"success": False, "data": None, "error": "No active case."})
            spill_dir = os.path.join(str(case_dir), "EYE_Logs", "dropped_payloads")
            file_path = os.path.join(spill_dir, f"{sha256}.txt")
            # Defense in depth: confirm the resolved path is inside spill_dir.
            if os.path.commonpath([os.path.realpath(file_path), os.path.realpath(spill_dir)]) != os.path.realpath(spill_dir):
                return safe_json_dumps({"success": False, "data": None, "error": "Path outside sidecar directory."})
            if not os.path.exists(file_path):
                return safe_json_dumps({"success": False, "data": None, "error": "Sidecar not found (content was within the inline cap)."})
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return safe_json_dumps({
                "success": True,
                "data": {"sha256": sha256, "len": len(content), "content": content},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_dropped_payload_full failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(str, result=str)
    def get_sealed_payload_full(self, sha256: str) -> str:
        """Return the COMPLETE payload the model saw for one seal (system prompt +
        history + tools + user message), decompressing its sidecar on demand.

        The Compliance panel's "View full payload" calls this with a seal's
        ``payload_sha256`` (exposed as ``payload_sidecar`` in get_payload_seals).
        The returned plaintext re-hashes to that same ``payload_sha256``, so it is
        independently verifiable. Traversal-proof: only a 64-char hex hash is
        accepted and it maps to a single file inside ``EYE_Logs/sealed_payloads``.
        """
        try:
            if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
                return safe_json_dumps({"success": False, "data": None, "error": "Invalid content hash."})
            cm = self.context_manager
            seal = getattr(cm, "evidence_seal", None) if cm else None
            if not seal:
                return safe_json_dumps({"success": False, "data": None, "error": "No active case."})
            content = seal.read_sealed_payload(sha256)
            if content is None:
                return safe_json_dumps({"success": False, "data": None, "error": "Sealed payload not found (full-payload storage disabled, or zstd unavailable for a compressed sidecar)."})
            return safe_json_dumps({
                "success": True,
                "data": {"sha256": sha256, "len": len(content), "content": content},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_sealed_payload_full failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_gep_turns(self) -> str:
        """
        Return the per-answer behavioral GEP compliance evaluations so the
        Compliance panel can show, for each investigator question, whether the
        Eye actually followed the protocol (direct answer, dual output,
        timestamps, proactive investigation).

        Reads ``<case>/EYE_Logs/eye_gep_turns.jsonl`` (written by
        QueryProcessor._persist_gep_turn). Besides ordinary answered turns, the
        log also carries deterministic per-step records — the automated triage
        (``query == "initialize_case_report"``) and the post-switch context
        acknowledgement (``"analyze_case_context"``) — plus fail-hard refusal and
        overflow-recovery turns, so every forensic step appears here. Envelope:

            {
                "success": true,
                "data": {
                    "turns": [
                        {"query": "...", "timestamp": "...", "summary": "3/4 ...",
                         "checks": [{"id":"GEP-1","name":"...","status":"PASS","detail":"..."}, ...]},
                        ...
                    ],
                    "total_turns": 4
                },
                "error": null
            }
        """
        try:
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({"success": True, "data": {"turns": [], "total_turns": 0}, "error": None})
            log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_gep_turns.jsonl")
            if not os.path.exists(log_path):
                return safe_json_dumps({"success": True, "data": {"turns": [], "total_turns": 0}, "error": None})

            turns = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turns.append(json.loads(line))
                    except Exception:
                        continue
            # Most recent first for the dashboard; return only the recent N so the
            # payload + render stay bounded (the UI windows it further). total_turns
            # reports the true count so the UI can show "showing N of total".
            turns.reverse()
            total = len(turns)
            _GEP_TURNS_CAP = 200
            return safe_json_dumps({
                "success": True,
                "data": {"turns": turns[:_GEP_TURNS_CAP], "total_turns": total},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_gep_turns failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_reasoning_turns(self) -> str:
        """
        Return the per-answer reasoning traces so the Compliance panel can show,
        for each decomposed question, WHY each sub-question was created and WHY
        each conclusion follows from which evidence (GEP-8 Transparency,
        GEP-2 Traceability).

        Reads ``<case>/EYE_Logs/eye_reasoning_log.jsonl`` (written by
        QueryProcessor._persist_reasoning_turn). Envelope:

            {
                "success": true,
                "data": {
                    "turns": [
                        {"query": "...", "timestamp": "...", "strategy": "...",
                         "sub_questions": [{"id":"sq1","q":"...","why_created":"...",
                            "conclusion":"...","why_concluded":"...",
                            "evidence":[{"ref":"db:table:rowid","note":"..."}],
                            "status":"answered"}, ...],
                         "premises": [{"claim":"...","verdict":"REFUTED","why":"...",
                            "evidence":[...]}, ...],
                         "consolidation": "...",
                         "knowledge_consulted": ["prefetch_knowledge.md", ...]},
                        ...
                    ],
                    "total_turns": 2
                },
                "error": null
            }
        """
        try:
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({"success": True, "data": {"turns": [], "total_turns": 0}, "error": None})
            log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_reasoning_log.jsonl")
            if not os.path.exists(log_path):
                return safe_json_dumps({"success": True, "data": {"turns": [], "total_turns": 0}, "error": None})

            turns = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turns.append(json.loads(line))
                    except Exception:
                        continue
            # Most recent first; cap to the recent N (the UI windows it further).
            turns.reverse()
            total = len(turns)
            _REASONING_TURNS_CAP = 200
            return safe_json_dumps({
                "success": True,
                "data": {"turns": turns[:_REASONING_TURNS_CAP], "total_turns": total},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_reasoning_turns failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @staticmethod
    def _normalize_query(text):
        """Strip the trailing ``<evidence ...>`` anchor block (appended to some
        messages by HistoryManager) so a stored user message matches the raw
        ``query`` recorded in the dialogue log."""
        s = (text or "")
        cut = s.find("\n\n<evidence")
        if cut != -1:
            s = s[:cut]
        return s.strip()

    def _backfill_message_thinking(self, history):
        """Attach each turn's Eye<->LLM transcript to the assistant message that
        produced it, for messages that don't already carry it.

        Going forward, QueryProcessor stamps ``metadata.eye_dialogue`` on the
        final assistant message of each turn. For conversations saved before that
        (or any message missing it), reconstruct the transcript from the per-case
        dialogue log so the "Show the Eye's thinking" dropdown reappears for ALL
        restored messages. Read-time only — never rewrites the saved history.

        Matching: split history into turns at each real (non-internal) user
        message; the LAST assistant message in a turn is its answer. Consume the
        dialogue-log groups for that query in order (FIFO) so repeated identical
        questions map to the right turn. Best-effort; any mismatch simply leaves
        a message without thinking (prior behavior).
        """
        try:
            if not isinstance(history, list) or not history:
                return history
            # Skip the log read entirely if every assistant message already has
            # its transcript (the common going-forward case).
            if all(
                (m.get("role") != "assistant") or (m.get("metadata") or {}).get("eye_dialogue")
                for m in history
            ):
                return history

            case_dir = getattr(self.context_manager, "case_directory", None)
            if not case_dir:
                return history
            groups, _ = self._load_dialogue_groups(case_dir)
            if not groups:
                return history

            # Bucket groups by normalized query, preserving chronological order.
            from collections import defaultdict, deque
            buckets = defaultdict(deque)
            for g in groups:
                buckets[self._normalize_query(g.get("query"))].append(g)

            # Segment history into turns and find each turn's answer message index.
            out = list(history)  # shallow copy; we replace only the dicts we touch
            current_query = None
            answer_idx = None

            def _flush(turn_query, idx):
                if turn_query is None or idx is None:
                    return
                bucket = buckets.get(turn_query)
                if not bucket:
                    return
                grp = bucket.popleft()  # consume in order even if already stamped
                msg = out[idx]
                meta = msg.get("metadata") or {}
                if meta.get("eye_dialogue"):
                    return  # exact transcript already present (Fix A) — keep it
                new_meta = dict(meta)
                new_meta["eye_dialogue"] = grp.get("entries", [])
                out[idx] = {**msg, "metadata": new_meta}

            for i, m in enumerate(history):
                role = m.get("role")
                is_internal = bool((m.get("metadata") or {}).get("internal"))
                if role == "user" and not is_internal:
                    _flush(current_query, answer_idx)   # close previous turn
                    current_query = self._normalize_query(m.get("content"))
                    answer_idx = None
                elif role == "assistant" and not is_internal:
                    answer_idx = i   # last assistant before next real user = answer
            _flush(current_query, answer_idx)  # close final turn
            return out
        except Exception as e:
            logger.debug(f"Thinking backfill skipped: {e}")
            return history

    def _load_dialogue_groups(self, case_dir):
        """Parse ``<case>/EYE_Logs/eye_dialogue_log.jsonl`` into ordered per-turn
        conversation groups.

        A dialogue's ``seq`` counter resets to 1 per ``process_query`` call, so
        ``seq == 1`` marks the start of a fresh conversation for a question;
        otherwise the entry extends that question's currently-open group. Returns
        ``(conversations, total_entries)`` where each conversation is
        ``{"query", "started", "entry_count", "entries"}`` in file (chronological)
        order. Shared by ``get_dialogue_history`` (Compliance panel) and
        ``get_conversation_history`` (per-message thinking backfill).
        """
        conversations = []
        active_by_query = {}   # query -> its currently-open conversation group
        total_entries = 0
        log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_dialogue_log.jsonl")
        if not os.path.exists(log_path):
            return conversations, total_entries
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                total_entries += 1
                query = entry.get("query", "(unknown question)")
                group = active_by_query.get(query)
                if entry.get("seq") == 1 or group is None:
                    group = {
                        "query": query,
                        "started": entry.get("timestamp", ""),
                        "entry_count": 0,
                        "entries": [],
                    }
                    conversations.append(group)
                    active_by_query[query] = group
                group["entries"].append(entry)
                group["entry_count"] += 1
        return conversations, total_entries

    @pyqtSlot(result=str)
    def get_dialogue_history(self) -> str:
        """
        Return the full Eye<->LLM conversation for the Compliance panel, GROUPED
        BY the investigator question that produced it. For each question the
        ``entries`` list holds, in order, every exchange with the model: the
        prompt the Eye sent (incl. full system prompt), the model's reasoning,
        the tool calls it requested (with arguments), the tool results, and the
        synthesis turns.

        Reads ``<case>/EYE_Logs/eye_dialogue_log.jsonl`` (written by
        QueryProcessor._persist_dialogue). Envelope:

            {
                "success": true,
                "data": {
                    "conversations": [
                        {
                            "query": "Did the user run malware.exe?",
                            "started": "2026-05-31T...",
                            "entry_count": 5,
                            "entries": [ <dialogue entry>, ... ]
                        }, ...
                    ],
                    "total_entries": 12
                },
                "error": null
            }
        """
        try:
            cm = self.context_manager
            case_dir = getattr(cm, "case_directory", None) if cm else None
            if not case_dir:
                return safe_json_dumps({
                    "success": True,
                    "data": {"conversations": [], "total_entries": 0},
                    "error": None,
                })

            log_path = os.path.join(str(case_dir), "EYE_Logs", "eye_dialogue_log.jsonl")
            if not os.path.exists(log_path):
                return safe_json_dumps({
                    "success": True,
                    "data": {"conversations": [], "total_entries": 0},
                    "error": None,
                })

            conversations, total_entries = self._load_dialogue_groups(case_dir)

            # Perf: dialogue entries carry full system prompts — return only the
            # most recent N conversations for display; report the true totals.
            _CONV_CAP = 25
            total_conversations = len(conversations)
            conversations = conversations[-_CONV_CAP:]
            return safe_json_dumps({
                "success": True,
                "data": {"conversations": conversations,
                         "total_entries": total_entries,
                         "total_conversations": total_conversations},
                "error": None,
            })
        except Exception as e:
            logger.error(f"get_dialogue_history failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(str, result=str)
    def export_audit_trail(self, output_path: str) -> str:
        """
        Export audit trail to specified path.
        
        Calls the TruncationAuditor to export the audit trail and returns
        the result to the React frontend.
        
        Args:
            output_path: Destination file path for audit trail export
            
        Returns:
            JSON string with format:
            {
                "success": true,
                "data": {
                    "output_path": "/path/to/audit_trail.log",
                    "exported": true
                },
                "error": null
            }
                """
        try:
            logger.info(f"Exporting audit trail to: {output_path}")
            
            # Validate context_manager is available
            if not self.context_manager:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Validate truncation_auditor is available
            if not hasattr(self.context_manager, 'truncation_auditor') or not self.context_manager.truncation_auditor:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "TruncationAuditor not available. Case directory may not be set."
                })
            
            # Export audit trail through TruncationAuditor
            success = self.context_manager.truncation_auditor.export_audit_trail(output_path)
            
            if success:
                return safe_json_dumps({
                    "success": True,
                    "data": {
                        "output_path": output_path,
                        "exported": True
                    },
                    "error": None
                })
            else:
                return safe_json_dumps({
                    "success": False,
                    "data": None,
                    "error": "Failed to export audit trail"
                })
            
        except Exception as e:
            logger.error(f"Error exporting audit trail: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return safe_json_dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })

    # ── UI Integration Slots ───────────────────────────────────
    
    @pyqtSlot()
    def requestCaseContext(self):
        """Emit signal to show Case Context dialog from main window."""
        self.case_context_requested.emit()
        
    @pyqtSlot()
    def requestCaseSummary(self):
        """Emit signal to show Case Summary dialog from main window."""
        self.case_summary_requested.emit()

    @pyqtSlot()
    def requestSettings(self):
        """Emit signal to show Settings/Onboarding wizard from main window."""
        self.settings_requested.emit()

    @pyqtSlot()
    def requestAddEvidence(self):
        """Emit signal to open the 'Add new evidence' import flow from the main window.

        The native file picker + conversion + case refresh all run on the Qt GUI
        thread in EyeWindow (see EyeWindow._on_add_evidence), mirroring how
        settings_requested is handled — a bridge QObject cannot host a QFileDialog.
        """
        self.add_evidence_requested.emit()

    @pyqtSlot()
    def requestComplianceWindow(self):
        """Emit signal to open the GEP Compliance dashboard in its own OS window."""
        self.compliance_window_requested.emit()

    @pyqtSlot()
    def requestNarrativeMapWindow(self):
        """Emit signal to open the Narrative Map in its own OS window."""
        self.narrative_map_window_requested.emit()

    @pyqtSlot()
    def requestEvidenceWindow(self):
        """Emit signal to open the Imported Evidence window (list + hashes)."""
        self.evidence_window_requested.emit()

    def _imported_evidence_manifest(self):
        """Manifest rooted at the case's artifacts directory, or None."""
        try:
            from eye.services.imported_evidence_manifest import ImportedEvidenceManifest
            artifacts_dir = getattr(self.database_service, "case_directory", None)
            if not artifacts_dir and getattr(self.context_manager, "case_directory", None):
                from pathlib import Path
                cand = Path(self.context_manager.case_directory) / "Target_Artifacts"
                artifacts_dir = cand if cand.exists() else self.context_manager.case_directory
            return ImportedEvidenceManifest(artifacts_dir) if artifacts_dir else None
        except Exception as e:
            logger.error(f"Could not open imported-evidence manifest: {e}")
            return None

    @pyqtSlot(result=str)
    def get_imported_evidence(self) -> str:
        """Immediate (unverified) imported-evidence listing. Also kicks off a
        background re-hash of every file; the verified listing arrives via the
        ``imported_evidence_ready`` signal so multi-GB evidence never blocks the
        GUI thread."""
        manifest = self._imported_evidence_manifest()
        if manifest is None:
            return safe_json_dumps({"success": False, "data": None,
                                    "error": "No case is loaded."})
        try:
            entries = manifest.list_entries(verify=False)
            for e in entries:
                e.setdefault("integrity", "verifying")

            # Background verification (streamed re-hash of each file).
            bridge = self

            class _HashVerifyWorker(QThread):
                def run(self):
                    try:
                        verified = manifest.list_entries(verify=True)
                        bridge.imported_evidence_ready.emit(safe_json_dumps(
                            {"success": True, "data": {"entries": verified}, "error": None}))
                    except Exception as exc:
                        bridge.imported_evidence_ready.emit(safe_json_dumps(
                            {"success": False, "data": None, "error": str(exc)}))

            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            worker = _HashVerifyWorker()
            self._active_workers.append(worker)
            worker.finished.connect(lambda w=worker: (
                self._active_workers.remove(w) if w in self._active_workers else None,
                w.deleteLater()))
            worker.start()

            return safe_json_dumps({"success": True,
                                    "data": {"entries": entries}, "error": None})
        except Exception as e:
            logger.error(f"get_imported_evidence failed: {e}", exc_info=True)
            return safe_json_dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(str)
    def focus_narrative_map(self, card_id: str):
        """Open/raise the Narrative Map window and focus a specific card, opening its
        detail panel. Invoked from the Compliance window's 'view in map' links.

        The bridge object is shared across the Eye windows' QWebChannels, so
        emitting ``narrative_map_focus`` reaches the map window's React (mirroring
        how ``narrative_map_updated`` live-updates it). The focus is deferred so a
        freshly-opened map window has a moment to mount before it selects the card.
        """
        cid = card_id or ""
        try:
            self.narrative_map_window_requested.emit()
        except Exception as e:
            logger.debug(f"focus_narrative_map: could not request map window: {e}")
        try:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(350, lambda: self.narrative_map_focus.emit(cid))
        except Exception:
            try:
                self.narrative_map_focus.emit(cid)
            except Exception as e:
                logger.debug(f"focus_narrative_map: could not emit focus: {e}")

    # ── Narrative Map ──────────────────────────────────────────
    def _narrative_map_service(self):
        """Resolve the per-case NarrativeMapService held by the ContextManager
        (None when no case is loaded)."""
        return getattr(self.context_manager, "narrative_map_service", None)

    @pyqtSlot(result=str)
    def getNarrativeMap(self):
        """Return the active case's Narrative Map (MapGraph + recent audit) as JSON.
        Empty graph JSON when no case/service is available."""
        svc = self._narrative_map_service()
        if svc is None:
            return json.dumps({"verdict": {"id": "verdict", "title": "Overall verdict",
                                           "reason": "", "authoredBy": "eye"},
                               "narratives": [], "evidence": {}, "links": [], "audit": []})
        try:
            return svc.load_graph_json()
        except Exception as e:
            logger.error(f"getNarrativeMap failed: {e}")
            return json.dumps({"verdict": {"id": "verdict", "title": "Overall verdict",
                                           "reason": "", "authoredBy": "eye"},
                               "narratives": [], "evidence": {}, "links": [], "audit": []})

    @pyqtSlot(str, result=str)
    def commitMapEdit(self, event_json: str):
        """Validate + apply + seal one Narrative Map mutation. Returns
        {ok, seal_hash, ...}. On success, pushes narrative_map_updated so any open
        map window (and other views) live-refresh."""
        svc = self._narrative_map_service()
        if svc is None:
            return json.dumps({"ok": False, "error": "no case / narrative map service"})
        try:
            res = svc.commit(event_json)
            if res.get("ok"):
                # Push the FULL graph (not just a patch) so every open map view —
                # this window, a second window, the embedded view — reconciles to
                # the persisted state. The change descriptor still drives the
                # changed-card pulse, and the audit row is appended.
                self.emit_narrative_map_changed(change=res.get("change"),
                                                audit=res.get("audit"))
            return safe_json_dumps(res)
        except Exception as e:
            logger.error(f"commitMapEdit failed: {e}")
            return json.dumps({"ok": False, "error": str(e)})

    @pyqtSlot(str)
    def investigateNarrative(self, narrative_id: str):
        """Double-click a narrative → the Eye investigates it deeper in the
        BACKGROUND. Runs a focused query whose NEW evidence attaches to this
        narrative (no chat bubble). Emits ``narrativeInvestigationComplete`` when
        done so the map can clear the per-card spinner."""
        svc = self._narrative_map_service()
        if svc is None or not self.context_manager:
            try: self.narrativeInvestigationComplete.emit(narrative_id)
            except Exception: pass
            return
        try:
            g = svc.load_graph()
            n = next((x for x in g.get("narratives", []) if x.get("id") == narrative_id), None)
            if not n:
                self.narrativeInvestigationComplete.emit(narrative_id)
                return
            title = (n.get("title") or "").strip()
            reason = (n.get("reason") or "").strip()
            query = (
                f'Investigate further and find ADDITIONAL forensic evidence for this established '
                f'finding: "{title}". {reason} Report ONLY new artifacts, timestamps, or '
                f'correlations not already recorded, and cite the exact source for each.'
            )
            # Scope: new evidence attaches to THIS narrative (see
            # query_processor._sync_narratives_from_findings).
            try:
                self.context_manager._focus_narrative_id = narrative_id
            except Exception:
                pass

            worker = QueryWorker(self.context_manager, query, suppress_chat=True)
            worker.status_updated.connect(self.status_updated.emit)
            worker.dialogue_updated.connect(self.dialogue_updated.emit)
            worker.report_updated.connect(self._emit_report_updated)
            worker.request_hitl.connect(self._show_hitl_dialog)
            worker.finished.connect(
                lambda nid=narrative_id, w=worker: self._on_investigate_finished(nid, w))

            if not hasattr(self, '_active_workers'):
                self._active_workers = []
            self._active_workers.append(worker)
            worker.start()
        except Exception as e:
            logger.error(f"investigateNarrative failed: {e}")
            try:
                self.context_manager._focus_narrative_id = None
            except Exception:
                pass
            try: self.narrativeInvestigationComplete.emit(narrative_id)
            except Exception: pass

    def _on_investigate_finished(self, narrative_id, worker):
        """Clear the focus scope + drop the worker ref + tell the map the
        investigation finished (clears the per-card spinner)."""
        try:
            self.context_manager._focus_narrative_id = None
        except Exception:
            pass
        if hasattr(self, '_active_workers') and worker in self._active_workers:
            try:
                self._active_workers.remove(worker)
            except ValueError:
                pass
        try:
            self.narrativeInvestigationComplete.emit(narrative_id)
        except Exception:
            pass

    def emit_narrative_map_changed(self, change: dict = None, audit: dict = None):
        """Backend-side helper: push a live Narrative Map update (e.g. after the Eye
        auto-syncs sub-questions or attaches evidence mid-investigation). Sends the
        full graph so the UI reconciles even if it missed earlier patches."""
        svc = self._narrative_map_service()
        if svc is None:
            return
        try:
            envelope = {"kind": "graph", "graph": json.loads(svc.load_graph_json())}
            if change:
                envelope["change"] = change
            if audit:
                envelope["audit"] = audit
            self.narrative_map_updated.emit(safe_json_dumps(envelope))
        except Exception as e:
            logger.debug(f"emit_narrative_map_changed skipped: {e}")
