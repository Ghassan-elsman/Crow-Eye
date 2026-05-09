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
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QThread, QEventLoop, Qt
import inspect

logger = logging.getLogger(__name__)

class QueryWorker(QThread):
    """
    Background worker thread to run ContextManager queries without blocking the GUI.
    """
    finished_query = pyqtSignal(object)
    request_hitl = pyqtSignal(str, object, dict, object)
    status_updated = pyqtSignal(str)
    report_updated = pyqtSignal(str)
    
    def __init__(self, context_manager, query):
        super().__init__()
        self.context_manager = context_manager
        self.query = query
        self.result = None
        self.error = None
        
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
            
        def report_callback(report_json: str):
            logger.info("Report update triggered from worker")
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
            
            self.result = self.context_manager.process_query(self.query, **params)
        except Exception as e:
            self.error = e
            self.result = {"success": False, "error": str(e)}
        finally:
            if hasattr(self.context_manager, 'hitl_callback'):
                del self.context_manager.hitl_callback
            self.finished_query.emit(self.result)


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
    
    # Signals for async operations
    query_complete = pyqtSignal(str)  # JSON response when query completes
    report_updated = pyqtSignal(str)  # Updated report JSON when report changes
    error_occurred = pyqtSignal(str)  # Error message when backend error occurs
    layout_requested = pyqtSignal(str) # Request UI layout changes (JSON)
    status_updated = pyqtSignal(str)  # Status update message (thinking/searching)
    
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
        logger.info("EYEBridge initialized")
    
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
                return json.dumps({
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
            worker.report_updated.connect(self.report_updated.emit)
            
            # Keep reference to prevent GC
            if not hasattr(self, '_active_workers'):
                self._active_workers = []
            self._active_workers.append(worker)
            
            # Start processing
            worker.start()
            
            # Return immediately to avoid freezing the UI
            # The frontend will receive the final result via the query_complete signal
            return json.dumps({
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
            return json.dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "DatabaseService not initialized"
                })
            
            # Execute query through DatabaseService
            result = self.database_service.execute_query(database, sql)
            
            # Check if query was successful
            if not result.get("success"):
                return json.dumps({
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
            
            return json.dumps({
                "success": True,
                "data": data,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error querying database: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
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
                formatted_results[table_name] = [
                    {
                        "table": sr.table,
                        "row_data": sr.row_data,
                        "matched_columns": sr.matched_columns,
                        "match_count": sr.match_count
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
            
            return json.dumps({
                "success": True,
                "data": data,
                "error": None
            })
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in search config: {e}", exc_info=True)
            error_msg = f"Invalid search configuration JSON: {str(e)}"
            self.error_occurred.emit(error_msg)
            return json.dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error searching artifacts: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "DatabaseService not initialized"
                })
            
            # Get schema through DatabaseService
            result = self.database_service.get_schema(database, table)
            
            # Check if schema retrieval was successful
            if not result.get("success"):
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": result.get("error", "Schema retrieval failed")
                })
            
            # Return the schema data
            return json.dumps({
                "success": True,
                "data": result,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error getting schema: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Get stats from ContextManager
            stats = self.context_manager.get_context_stats()
            logger.info(f"Sending context stats: {stats}")
            print(f"[EYE Bridge] Stats sent: {stats.get('model_name')} ({stats.get('backend')})")
            
            return json.dumps({
                "success": True,
                "data": stats,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error getting context stats: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({"success": False, "data": None, "error": "ContextManager not initialized"})
            
            history = self.context_manager.clear_conversation_history()
            return json.dumps({
                "success": True,
                "data": history,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error clearing history: {e}", exc_info=True)
            return json.dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(result=str)
    def get_conversation_history(self) -> str:
        """
        Get all messages in current session.
        
        Returns:
            JSON string with message list
        """
        try:
            if not self.context_manager:
                return json.dumps({"success": False, "data": None, "error": "ContextManager not initialized"})

            history = self.context_manager.conversation_history
            return json.dumps({                "success": True,
                "data": history,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error getting history: {e}", exc_info=True)
            return json.dumps({"success": False, "data": None, "error": str(e)})

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
                return json.dumps({"success": False, "data": None, "error": "ContextManager not initialized"})
            
            models = self.context_manager.model_router.get_models_with_quota()
            return json.dumps({
                "success": True,
                "data": models,
                "error": None
            })
        except Exception as e:
            logger.error(f"Error getting models: {e}", exc_info=True)
            return json.dumps({"success": False, "data": None, "error": str(e)})

    @pyqtSlot(str, result=bool)
    def switch_active_model(self, model_name: str) -> bool:
        """
        Switch the actively connected AI model.
        """
        try:
            if not self.context_manager:
                return False
            
            self.context_manager.model_router.switch_model(model_name)
            logger.info(f"Switched model to {model_name}")
            
            # Automatically trigger a case context analysis query after switching models
            self.process_query("analyze_case_context")
            
            return True
        except Exception as e:
            logger.error(f"Error switching model: {e}", exc_info=True)
            return False
    
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
                
                return json.dumps({
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
                
                return json.dumps({
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
            return json.dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error proposing semantic mapping: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                
                return json.dumps({
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
                
                return json.dumps({
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
            return json.dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error editing semantic mapping: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Get report state from ReportEngine
            report_state = self.report_engine.get_report_json()
            
            return json.dumps({
                "success": True,
                "data": report_state,
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error getting report state: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Append section through ReportEngine
            block_id = self.report_engine.append_section(title, content)
            
            # Emit report_updated signal with updated report state
            self.report_updated.emit(json.dumps(self.report_engine.get_report_json()))
            
            return json.dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error appending report section: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
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
                return json.dumps({
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
            self.report_updated.emit(json.dumps(self.report_engine.get_report_json()))
            
            return json.dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error adding data table: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
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
            self.report_updated.emit(json.dumps(self.report_engine.get_report_json()))
            
            return json.dumps({
                "success": True,
                "data": {"block_id": block_id},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error adding image: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Edit section through ReportEngine
            success = self.report_engine.edit_section(block_id, content)
            
            if not success:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": f"Block {block_id} not found"
                })
            
            # Emit report_updated signal with updated report state
            self.report_updated.emit(json.dumps(self.report_engine.get_report_json()))
            
            return json.dumps({
                "success": True,
                "data": {"updated": True},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error editing report section: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Delete section through ReportEngine
            success = self.report_engine.delete_section(block_id)
            
            if not success:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": f"Block {block_id} not found"
                })
            
            # Emit report_updated signal with updated report state
            self.report_updated.emit(json.dumps(self.report_engine.get_report_json()))
            
            return json.dumps({
                "success": True,
                "data": {"deleted": True},
                "error": None
            })
            
        except Exception as e:
            logger.error(f"Error deleting report section: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ReportEngine not initialized"
                })
            
            # Validate format_type
            format_type_lower = format_type.lower()
            if format_type_lower not in ["html", "pdf", "markdown"]:
                return json.dumps({
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
                return json.dumps({
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
                
                return json.dumps({
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
            return json.dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
        except Exception as e:
            logger.error(f"Error exporting report: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "error": "ReportEngine not initialized"
                })
            
            # Get case directory from context manager
            if not self.context_manager or not hasattr(self.context_manager, 'case_directory'):
                return json.dumps({
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
            self.report_updated.emit(
                json.dumps(self.report_engine.get_report_json())
            )
            
            return json.dumps({
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
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    def _on_query_finished(self, result: dict):
        """Handle completion of background query worker."""
        # Clean up worker reference
        worker = self.sender()
        if hasattr(self, '_active_workers') and worker in self._active_workers:
            self._active_workers.remove(worker)
            worker.deleteLater()
            
        # Emit signal for the frontend
        self.query_complete.emit(json.dumps(result))
        
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
        self.layout_requested.emit(json.dumps({
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
            warning_json = json.dumps(warning_data)
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Validate history_manager is available
            if not hasattr(self.context_manager, 'history_manager') or not self.context_manager.history_manager:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "HistoryManager not available"
                })
            
            # Pin the message through HistoryManager
            success = self.context_manager.history_manager.pin_message(message_id)
            
            if success:
                return json.dumps({
                    "success": True,
                    "data": {
                        "message_id": message_id,
                        "pinned": True
                    },
                    "error": None
                })
            else:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": f"Message {message_id} not found"
                })
            
        except Exception as e:
            logger.error(f"Error pinning message: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Validate history_manager is available
            if not hasattr(self.context_manager, 'history_manager') or not self.context_manager.history_manager:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "HistoryManager not available"
                })
            
            # Unpin the message through HistoryManager
            success = self.context_manager.history_manager.unpin_message(message_id)
            
            if success:
                return json.dumps({
                    "success": True,
                    "data": {
                        "message_id": message_id,
                        "pinned": False
                    },
                    "error": None
                })
            else:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": f"Message {message_id} not found"
                })
            
        except Exception as e:
            logger.error(f"Error unpinning message: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
                "success": False,
                "data": None,
                "error": error_msg
            })
    
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
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "ContextManager not initialized"
                })
            
            # Validate truncation_auditor is available
            if not hasattr(self.context_manager, 'truncation_auditor') or not self.context_manager.truncation_auditor:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "TruncationAuditor not available. Case directory may not be set."
                })
            
            # Export audit trail through TruncationAuditor
            success = self.context_manager.truncation_auditor.export_audit_trail(output_path)
            
            if success:
                return json.dumps({
                    "success": True,
                    "data": {
                        "output_path": output_path,
                        "exported": True
                    },
                    "error": None
                })
            else:
                return json.dumps({
                    "success": False,
                    "data": None,
                    "error": "Failed to export audit trail"
                })
            
        except Exception as e:
            logger.error(f"Error exporting audit trail: {e}", exc_info=True)
            error_msg = str(e)
            self.error_occurred.emit(error_msg)
            return json.dumps({
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
