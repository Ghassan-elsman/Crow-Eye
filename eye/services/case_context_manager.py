"""
CaseContextManager - Case-specific context and variable management for EYE AI Assistant.

This service manages case-specific context including investigation reason, objectives,
case variables, semantic rules, and investigation logging. It provides context injection
for system prompts and maintains case state across sessions.

"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class CaseContextManager:
    """
    Manages case-specific context, variables, and investigation logging.
    
    This service provides:
    - Case context file management (eye_case_context.json)
    - Investigation logging (eye_investigation_log.jsonl)
    - Case-specific semantic rules (eye_semantic_rules.json)
    - Case variable storage and retrieval
    - Context injection for system prompts
    
    Attributes:
        case_directory: Path to the case directory
        context_file: Path to eye_case_context.json
        log_file: Path to eye_investigation_log.jsonl
        semantic_rules_file: Path to eye_semantic_rules.json
        case_context: Dictionary containing case context data
        logger: Logger instance for audit trail
    """
    
    # Default case context structure
    DEFAULT_CONTEXT = {
        "case_name": "",
        "investigation_reason": "",
        "investigation_start_date": "",
        "primary_suspects": "",
        "key_timeline_events": [],
        "investigation_objectives": "",
        "expected_evidence_types": "",
        "case_variables": {}
    }
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the CaseContextManager.
        
        Args:
            case_directory: Path to the case directory
            
        """
        self.case_directory = Path(case_directory)
        self.context_file = self.case_directory / "eye_case_context.json"
        self.log_file = self.case_directory / "eye_investigation_log.jsonl"
        self.semantic_rules_file = self.case_directory / "eye_semantic_rules.json"
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Load or create case context
        self.case_context = self._load_or_create_context()
        
        # Auto-upgrade generic or empty names to directory name
        curr_name = self.case_context.get("case_name", "")
        if not curr_name or curr_name.startswith("Case-20"):
            self.case_context["case_name"] = self.case_directory.name
            self._save_context()
    
    def _load_or_create_context(self) -> Dict[str, Any]:
        """
        Load existing case context or create default structure.
        
        Returns:
            Dictionary containing case context data
            
        """
        if self.context_file.exists():
            try:
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    context = json.load(f)
                    self.logger.info(f"Loaded case context from {self.context_file}")
                    return context
            except Exception as e:
                self.logger.error(f"Error loading case context: {e}")
                return self.DEFAULT_CONTEXT.copy()
        else:
            self.logger.info("No existing case context found, using default structure")
            return self.DEFAULT_CONTEXT.copy()
    
    def is_context_initialized(self) -> bool:
        """
        Check if case context has been initialized with investigation details.
        
        Returns:
            True if investigation_reason is set, False otherwise
            
        """
        return bool(self.case_context.get("investigation_reason", "").strip())
    
    def initialize_context(
        self,
        investigation_reason: str,
        primary_suspects: str = "",
        investigation_objectives: str = "",
        expected_evidence_types: str = "",
        key_timeline_events: Optional[List[str]] = None
    ) -> bool:
        """
        Initialize case context with investigation details.
        
        Args:
            investigation_reason: Primary objective or question driving the investigation (required)
            primary_suspects: Optional list of suspects or entities under investigation
            investigation_objectives: Optional specific objectives for the investigation
            expected_evidence_types: Optional types of evidence expected to be relevant
            key_timeline_events: Optional list of key timeline events
            
        Returns:
            True if context was successfully initialized and saved
            
        """
        if not investigation_reason.strip():
            self.logger.error("Cannot initialize context: investigation_reason is required")
            return False
        
        # Update context with provided values
        self.case_context["investigation_reason"] = investigation_reason.strip()
        self.case_context["investigation_start_date"] = datetime.now().isoformat()
        self.case_context["primary_suspects"] = primary_suspects.strip()
        self.case_context["investigation_objectives"] = investigation_objectives.strip()
        self.case_context["expected_evidence_types"] = expected_evidence_types.strip()
        
        if key_timeline_events:
            self.case_context["key_timeline_events"] = key_timeline_events
        
        # Generate case name if not set or if it's a generic default
        current_name = self.case_context.get("case_name", "")
        if not current_name or current_name.startswith("Case-20"):
            self.case_context["case_name"] = self.case_directory.name
            self._save_context()
        
        # Save context to file
        return self._save_context()
    
    def update_context(self, updates: Dict[str, Any]) -> bool:
        """
        Update case context with new values.
        
        Args:
            updates: Dictionary of fields to update
            
        Returns:
            True if context was successfully updated and saved
            
        """
        try:
            # Update context fields
            for key, value in updates.items():
                if key in self.case_context:
                    self.case_context[key] = value
                    self.logger.info(f"Updated case context field: {key}")
                else:
                    self.logger.warning(f"Ignoring unknown context field: {key}")
            
            # Save updated context
            return self._save_context()
            
        except Exception as e:
            self.logger.error(f"Error updating case context: {e}")
            return False
    
    def _save_context(self) -> bool:
        """
        Save case context to file.
        
        Returns:
            True if context was successfully saved
            
        """
        try:
            # Ensure case directory exists
            self.case_directory.mkdir(parents=True, exist_ok=True)
            
            # Write context to file with pretty formatting
            with open(self.context_file, 'w', encoding='utf-8') as f:
                json.dump(self.case_context, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Saved case context to {self.context_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving case context: {e}")
            return False
    
    def set_case_variable(self, key: str, value: Any) -> bool:
        """
        Set a case-specific variable.
        
        Args:
            key: Variable name
            value: Variable value
            
        Returns:
            True if variable was successfully set and saved
            
        """
        try:
            # Ensure case_variables dict exists
            if "case_variables" not in self.case_context:
                self.case_context["case_variables"] = {}
            
            # Set variable
            self.case_context["case_variables"][key] = value
            self.logger.info(f"Set case variable: {key} = {value}")
            
            # Save context
            return self._save_context()
            
        except Exception as e:
            self.logger.error(f"Error setting case variable {key}: {e}")
            return False
    
    def get_case_variable(self, key: str) -> Optional[Any]:
        """
        Retrieve a case-specific variable.
        
        Args:
            key: Variable name
            
        Returns:
            Variable value, or None if not found
            
        """
        return self.case_context.get("case_variables", {}).get(key)
    
    def get_investigation_reason(self) -> str:
        """
        Get the investigation reason for system prompt injection.
        
        Returns:
            Investigation reason string, or empty string if not set
            
        """
        return self.case_context.get("investigation_reason", "")
    
    def get_context_for_prompt(self) -> str:
        """
        Format case context for injection into system prompts.
        
        Returns:
            Formatted context string for system prompt
            
        """
        if not self.is_context_initialized():
            return "No case context loaded. Provide general forensic assistance."
        
        # Build context string
        parts = []
        
        # Include Case Name and Directory
        case_name = self.case_context.get("case_name") or (self.case_directory.name if self.case_directory else "Unknown Case")
        case_path_str = str(self.case_directory) if self.case_directory else "Unknown Path"
        parts.append(f"CASE INFO: You are analyzing the case '{case_name}'. The root directory for this case is '{case_path_str}'.")
        parts.append(
            f"DIRECTORY STRUCTURE:\n"
            f"- Parsed artifact outputs are located in: '{case_path_str}\\Target_Artifacts'\n"
            f"- Correlation Engine Results DB is at: '{case_path_str}\\Correlation\\output\\correlation_results.db'\n"
            f"- Correlation Feathers are at: '{case_path_str}\\Correlation\\feathers'\n"
            f"- Correlation Wings are at: '{case_path_str}\\Correlation\\wings'\n"
            "You MUST use this exact structure when executing shell commands or tools that require file paths."
        )

        # Investigation reason (required)
        investigation_reason = self.case_context.get("investigation_reason", "")
        parts.append(f"\nCASE CONTEXT: This investigation is focused on: {investigation_reason}.")
        
        # Primary suspects (optional)
        suspects = self.case_context.get("primary_suspects", "").strip()
        if suspects:
            parts.append(f"Primary suspects: {suspects}.")
        
        # Investigation objectives (optional)
        objectives = self.case_context.get("investigation_objectives", "").strip()
        if objectives:
            parts.append(f"Investigation objectives: {objectives}.")
        
        # Expected evidence types (optional)
        evidence_types = self.case_context.get("expected_evidence_types", "").strip()
        if evidence_types:
            parts.append(f"Expected evidence types: {evidence_types}.")
        
        # Add directive to stay focused
        parts.append("Keep all responses relevant to this objective.")
        
        return "\n".join(parts)
    
    def log_investigation_step(
        self,
        query: str,
        response_summary: str,
        evidence_found: bool = False,
        suggested_next_steps: str = "",
        artifacts_queried: List[str] = None,
        query_type: str = "general"
    ) -> bool:
        """
        Log an investigation step with expanded metadata for the summary timeline.
        
        Args:
            query: User's query
            response_summary: Summary of AI response
            evidence_found: Whether significant evidence was found
            suggested_next_steps: Suggested next steps for the investigator
            artifacts_queried: List of artifacts or tools accessed
            query_type: Categorization of the query
            
        Returns:
            True if log entry was successfully written
        """
        try:
            self.case_directory.mkdir(parents=True, exist_ok=True)
            
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "response_summary": response_summary,
                "evidence_found": evidence_found,
                "suggested_next_steps": suggested_next_steps,
                "artifacts_queried": artifacts_queried or [],
                "query_type": query_type
            }
            
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            return True
        except Exception as e:
            self.logger.error(f"Error logging investigation step: {e}")
            return False

    def log_investigation_activity(
        self,
        query: str,
        response_summary: str,
        evidence_found: Optional[str] = None,
        suggested_next_steps: Optional[str] = None
    ) -> bool:
        """Legacy alias for log_investigation_step."""
        return self.log_investigation_step(
            query=query,
            response_summary=response_summary,
            evidence_found=bool(evidence_found),
            suggested_next_steps=suggested_next_steps or ""
        )
    
    def get_investigation_timeline(self) -> List[Dict[str, Any]]:
        """
        Retrieve investigation log entries.
        
        Returns:
            List of log entry dictionaries, ordered by timestamp
            
        """
        if not self.log_file.exists():
            return []
        
        try:
            entries = []
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        entries.append(entry)
            
            self.logger.info(f"Retrieved {len(entries)} investigation log entries")
            return entries
            
        except Exception as e:
            self.logger.error(f"Error reading investigation log: {e}")
            return []
    
    def load_case_semantic_rules(self) -> List[Dict[str, Any]]:
        """
        Load case-specific semantic rules.
        
        Returns:
            List of semantic rule dictionaries
            
        """
        if not self.semantic_rules_file.exists():
            self.logger.info("No case-specific semantic rules file found")
            return []
        
        try:
            with open(self.semantic_rules_file, 'r', encoding='utf-8') as f:
                rules = json.load(f)
            
            # Validate structure
            if isinstance(rules, dict) and "rules" in rules:
                rules_list = rules["rules"]
            elif isinstance(rules, list):
                rules_list = rules
            else:
                self.logger.warning("Invalid semantic rules structure")
                return []
            
            self.logger.info(f"Loaded {len(rules_list)} case-specific semantic rules")
            return rules_list
            
        except Exception as e:
            self.logger.error(f"Error loading case semantic rules: {e}")
            return []
    
    def save_case_semantic_rule(self, rule: Dict[str, Any]) -> bool:
        """
        Save a case-specific semantic rule.
        
        Args:
            rule: Semantic rule dictionary
            
        Returns:
            True if rule was successfully saved
            
        """
        try:
            # Ensure case directory exists
            self.case_directory.mkdir(parents=True, exist_ok=True)
            
            # Load existing rules
            existing_rules = self.load_case_semantic_rules()
            
            # Add new rule
            existing_rules.append(rule)
            
            # Save updated rules
            rules_data = {
                "rules": existing_rules,
                "last_updated": datetime.now().isoformat()
            }
            
            with open(self.semantic_rules_file, 'w', encoding='utf-8') as f:
                json.dump(rules_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Saved case-specific semantic rule: {rule.get('name', 'unnamed')}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving case semantic rule: {e}")
            return False
    
    def load_all_semantic_rules(self, global_rules_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        Load and merge global and case-specific semantic rules.
        
        This method loads both global semantic rules from the config directory
        and case-specific rules from the case directory. Both rule sets are
        applied additively - case rules do NOT override global rules.
        
        When both rule sets match the same pattern, results are merged.
        
        Args:
            global_rules_path: Optional path to global semantic rules file.
                             Defaults to configs/semantic_mapping_config.json
        
        Returns:
            List of all semantic rules (global + case-specific)
            
        """
        all_rules = []
        
        # Load global semantic rules
        if global_rules_path is None:
            global_rules_path = Path("configs/semantic_mapping_config.json")
        
        if global_rules_path.exists():
            try:
                with open(global_rules_path, 'r', encoding='utf-8') as f:
                    global_data = json.load(f)
                
                # Extract rules from global config
                if isinstance(global_data, dict) and "rules" in global_data:
                    global_rules = global_data["rules"]
                elif isinstance(global_data, list):
                    global_rules = global_data
                else:
                    self.logger.warning("Invalid global semantic rules structure")
                    global_rules = []
                
                all_rules.extend(global_rules)
                self.logger.info(f"Loaded {len(global_rules)} global semantic rules")
                
            except Exception as e:
                self.logger.error(f"Error loading global semantic rules: {e}")
        else:
            self.logger.warning(f"Global semantic rules file not found: {global_rules_path}")
        
        # Load case-specific semantic rules
        case_rules = self.load_case_semantic_rules()
        all_rules.extend(case_rules)
        
        self.logger.info(
            f"Loaded total of {len(all_rules)} semantic rules "
            f"({len(all_rules) - len(case_rules)} global + {len(case_rules)} case-specific)"
        )
        
        return all_rules
