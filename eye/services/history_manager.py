"""
History Manager for EYE AI Assistant.

This module manages conversation memory, including:
- Saving/loading history to the case directory
- Automatic history management (sliding window)
- Intelligent summarization of old forensic evidence
- Token budget enforcement
- Evidence detection and preservation
"""

import json
import logging
import hashlib
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

class HistoryManager:
    """
    Manages conversation history, persistence, and summarization.
    """

    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(__name__)
        self.history: List[Dict[str, Any]] = []
        self._message_id_counter = 0
        self._lock = threading.RLock()

    def load_history(self):
        """Load conversation history from the case directory."""
        if not self.cm.case_directory:
            return

        path = Path(self.cm.case_directory) / "EYE_Logs" / "eye_conversation_history.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        with self._lock:
                            # Migrate existing history if needed
                            self.history = self._migrate_existing_history(data)
                        self.logger.info(f"Loaded {len(self.history)} messages from history.")
            except Exception as e:
                self.logger.error(f"Failed to load history: {e}")

    def save_history(self):
        """Save conversation history to the case directory."""
        if not self.cm.case_directory:
            return

        logs_dir = Path(self.cm.case_directory) / "EYE_Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        path = logs_dir / "eye_conversation_history.json"
        try:
            with self._lock:
                history_snapshot = list(self.history)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(history_snapshot, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save history: {e}")

    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """
        Add a message to the history with automatic evidence detection.

        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content
            metadata: Optional metadata dictionary
        """
        # Generate unique message ID
        message_id = self._generate_message_id()

        # Count tokens
        token_count = self.cm.token_counter.count_tokens(content)

        # Create base message
        message = {
            "id": message_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "token_count": token_count,
            "metadata": metadata or {}
        }

        # Detect evidence in content if evidence_detector is available
        if hasattr(self.cm, 'evidence_detector') and self.cm.evidence_detector:
            try:
                # Retrieve threshold from config (default to 0.7 if missing)
                threshold = 0.7
                if hasattr(self.cm, 'evidence_preservation_config'):
                    threshold = self.cm.evidence_preservation_config.get("confidence_threshold", 0.7)

                evidence_result = self.cm.evidence_detector.detect_evidence(content)

                # Flag for preservation if evidence detected AND confidence meets threshold
                if evidence_result["has_evidence"] and evidence_result["confidence"] >= threshold:
                    message["metadata"]["preserve_evidence"] = True
                    message["metadata"]["evidence_patterns"] = evidence_result["patterns_found"]
                    message["metadata"]["evidence_confidence"] = evidence_result["confidence"]
                    message["metadata"]["evidence_matches"] = evidence_result.get("matches", {})

                    # Log preservation decision to audit trail if available
                    if hasattr(self.cm, 'truncation_auditor') and self.cm.truncation_auditor:
                        message_hash = self._hash_message(content)
                        # Extract snippets for the audit log (sanitized)
                        snippets = {}
                        for p_type, m_list in evidence_result.get("matches", {}).items():
                            snippets[p_type] = [m[:100] + ("..." if len(m) > 100 else "") for m in m_list[:3]]

                        self.cm.truncation_auditor.log_event(
                            action="PRESERVED",
                            message_id=message_id,
                            token_count=token_count,
                            reason="evidence_detected",
                            message_hash=message_hash,
                            metadata={
                                "patterns": evidence_result["patterns_found"],
                                "confidence": round(evidence_result["confidence"], 4),
                                "snippets": snippets,
                                "source_tool": metadata.get("tool_names") or metadata.get("tool_name") if metadata else None
                            }
                        )
                        # Pillar 7: Auto-export JSON for machine readability
                        self.cm.truncation_auditor.auto_export_json()

                    self.logger.info(
                        f"Message {message_id} flagged for preservation. "
                        f"Patterns: {evidence_result['patterns_found']}, "
                        f"Confidence: {evidence_result['confidence']:.2f}"
                    )
            except Exception as e:
                self.logger.error(f"Evidence detection failed for message {message_id}: {e}")
                # Continue without evidence detection - don't block message addition

        with self._lock:
            self.history.append(message)
            self.manage_history()

    def manage_history(self):
        """
        Keep history within token budget using evidence-aware summarization.

        This method implements and :
        - Separates preserved messages from summarizable messages
        - Skips messages with preserve_evidence=true or pinned=true
        - Reconstructs history: first + preserved + summary + last 5 messages
        - Logs summarization events to audit trail
        """
        # --- Phase 1: Read state under lock ---
        with self._lock:
            total_tokens = sum(m.get("token_count", 0) for m in self.history)

            # If we exceed budget and have enough messages to summarize
            if not (total_tokens > self.cm.token_budget["conversation_history"] and len(self.history) > 3):
                return  # Nothing to do

            # Identify static boundaries to prevent fragmentation
            first_msg = self.history[0]
            last_msgs = self.history[-5:] if len(self.history) > 6 else self.history[1:]
            mid_msgs  = self.history[1:-5] if len(self.history) > 6 else []

            preserved_msgs    = []
            summarizable_msgs = []
            for msg in mid_msgs:
                metadata = msg.get("metadata", {})
                if metadata.get("preserve_evidence") or metadata.get("pinned"):
                    preserved_msgs.append(msg)
                else:
                    summarizable_msgs.append(msg)

        # If nothing to summarize, exit early (lock already released)
        if not summarizable_msgs:
            return

        # --- Phase 2: LLM call OUTSIDE the lock ---
        # _summarize_chunk() calls the model router which can take 10-60s.
        # Holding the lock here would block all concurrent add_message() calls
        # (e.g. status callback messages from the QueryWorker thread).
        summary_text = self._summarize_chunk(summarizable_msgs)

        # --- Phase 3: Write new history under lock ---
        with self._lock:
            summary_msg = {
                "id": self._generate_message_id(),
                "role": "system",
                "content": summary_text,
                "timestamp": datetime.now().isoformat(),
                "token_count": self.cm.token_counter.count_tokens(summary_text),
                "metadata": {
                    "is_summary": True,
                    "summarized_count": len(summarizable_msgs)
                }
            }

            # Reconstruct history: first + preserved + summary + last messages
            preserved_ids   = {m.get("id") for m in preserved_msgs}
            deduped_last    = [m for m in last_msgs if m.get("id") not in preserved_ids]
            self.history    = [first_msg] + preserved_msgs + [summary_msg] + deduped_last

            # Log summarization events to audit trail for each summarized message
            if hasattr(self.cm, 'truncation_auditor') and self.cm.truncation_auditor:
                for msg in summarizable_msgs:
                    message_hash = self._hash_message(msg.get("content", ""))
                    self.cm.truncation_auditor.log_event(
                        action="SUMMARIZED",
                        message_id=msg.get("id", "unknown"),
                        token_count=msg.get("token_count", 0),
                        reason="budget_exceeded",
                        message_hash=message_hash,
                        metadata={
                            "summary_msg_id": summary_msg["id"],
                            "total_summarized": len(summarizable_msgs)
                        }
                    )
                # Pillar 7: Auto-export JSON for machine readability
                self.cm.truncation_auditor.auto_export_json()

            # Track truncation count in context manager
            self.cm.truncation_count += len(summarizable_msgs)

            self.logger.info(
                f"Conversation history summarized due to token budget. "
                f"Summarized: {len(summarizable_msgs)} messages, "
                f"Preserved: {len(preserved_msgs)} messages"
            )


    def _summarize_chunk(self, messages: List[Dict]) -> str:
        """Use the LLM to summarize a block of conversation."""
        summary_prompt = (
            "Summarize the following forensic investigation discussion concisely. "
            "CRITICAL: You MUST preserve all high-fidelity forensic indicators: "
            "- Application Names and Executable Paths "
            "- Timestamps (ISO 8601 format) "
            "- IP Addresses, Domains, and Registry Keys "
            "- Evidence detected in tool results. "
            "Maintain forensic integrity. Discussion:\n\n"
        )
        for msg in messages:

            # to ensure critical findings in large datasets aren't lost during summarization.
            content = msg.get('content', "")
            if len(content) > 2000:
                content_sample = content[:1000] + "\n... [BODY TRUNCATED FOR SUMMARY] ...\n" + content[-1000:]
            else:
                content_sample = content
                
            summary_prompt += f"[{msg['role']}]: {content_sample}\n"

        try:
            # We use a simple generate call without tools for summarization
            res = self.cm.model_router.generate(
                system_prompt="You are a senior forensic investigator. Summarize discussions while ensuring absolute preservation of technical indicators (paths, timestamps, app names).",
                user_message=summary_prompt,
                tools=None
            )
            summary = res.get("content", "Investigation discussion summarized.")
            return f"SUMMARY OF PREVIOUS ACTIVITY: {summary}"
        except Exception:
            return "SUMMARY OF PREVIOUS ACTIVITY: [Forensic history summarized due to token limits. Evidence was analyzed previously.]"

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics for the current history."""
        with self._lock:
            total_tokens = sum(m.get("token_count", 0) for m in self.history)
            return {
                "total_messages": len(self.history),
                "total_tokens": total_tokens,
                "budget_remaining": self.cm.token_budget["conversation_history"] - total_tokens
            }

    def pop_last_message(self) -> Optional[Dict[str, Any]]:
        """Remove and return the last message in history if it's from the user."""
        with self._lock:
            if self.history and self.history[-1].get("role") == "user":
                return self.history.pop()
            return None
    def clear_history(self) -> List[Dict[str, Any]]:
        """Clear the conversation history and persist the empty state."""
        self.history = []
        self.save_history()
        self.logger.info("Conversation history cleared.")
        return self.history

    def _generate_message_id(self) -> str:
        """
        Generate a unique message ID.
        Thread-safe to prevent duplicates in concurrent operations.
        
        Returns:
            Unique message ID in format: msg_{timestamp}_{counter}
        """
        with self._lock:
            self._message_id_counter += 1
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            return f"msg_{timestamp}_{self._message_id_counter}"
    
    def _hash_message(self, content: str) -> str:
        """
        Generate SHA-256 hash of message content for audit trail.
        
        Args:
            content: Message content to hash
            
        Returns:
            Hexadecimal hash string (first 16 characters for brevity)
        """
        hash_obj = hashlib.sha256(content.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    def pin_message(self, message_id: str) -> Dict[str, Any]:
        """
        Pin a message to prevent it from being summarized.
        
        Pinned messages are treated the same as evidence-preserved messages
        during summarization and will never be included in summary operations.
        
        Maximum of 10 messages can be pinned at once .
        
        Args:
            message_id: Unique identifier of the message to pin
            
        Returns:
            Dictionary with format:
            {
                "success": bool,
                "message": str,
                "pinned_count": int,
                "max_pinned": int,
                "action_required": str or None  # "unpin_oldest", "cancel", "manage_pins"
            }
            
        Error Handling :
            - Shows error when attempting to pin 11th message
            - Provides options: Cancel, Unpin Oldest, Manage Pins
            - Logs decision to audit trail
        """
        # Find the message by ID
        for msg in self.history:
            if msg.get("id") == message_id:
                # Check if message is already pinned
                is_already_pinned = msg.get("metadata", {}).get("pinned", False)
                
                # Short-circuit: If already pinned, don't re-pin (prevents audit trail corruption)
                if is_already_pinned:
                    pinned_count = sum(
                        1 for m in self.history 
                        if m.get("metadata", {}).get("pinned", False)
                    )
                    return {
                        "success": True,
                        "message": f"Message is already pinned ({pinned_count}/10)",
                        "pinned_count": pinned_count,
                        "max_pinned": 10,
                        "action_required": None
                    }
                
                # Check the maximum pinned messages constraint
                pinned_count = sum(
                    1 for m in self.history 
                    if m.get("metadata", {}).get("pinned", False)
                )
                
                # Enforce maximum of 10 pinned messages 
                if pinned_count >= 10:
                    self.logger.warning(
                        f"Cannot pin message {message_id}: maximum of 10 pinned messages reached"
                    )
                    return {
                        "success": False,
                        "message": "Maximum 10 pinned messages. Unpin an existing message or enable auto-unpin oldest.",
                        "pinned_count": pinned_count,
                        "max_pinned": 10,
                        "action_required": "show_modal",  # UI should show modal with options
                        "options": [
                            {"id": "cancel", "label": "Cancel"},
                            {"id": "unpin_oldest", "label": "Unpin Oldest"},
                            {"id": "manage_pins", "label": "Manage Pins"}
                        ]
                    }
                
                # Set pinned flag in metadata
                if "metadata" not in msg:
                    msg["metadata"] = {}
                
                msg["metadata"]["pinned"] = True
                msg["metadata"]["pinned_at"] = datetime.now().isoformat()
                
                # Log pinning action to audit trail if available
                if hasattr(self.cm, 'truncation_auditor') and self.cm.truncation_auditor:
                    message_hash = self._hash_message(msg.get("content", ""))
                    self.cm.truncation_auditor.log_event(
                        action="PINNED",
                        message_id=message_id,
                        token_count=msg.get("token_count", 0),
                        reason="user_action",
                        message_hash=message_hash,
                        metadata={}
                    )
                
                # Save history to persist pinned state
                self.save_history()
                
                # Count pinned messages after pinning
                pinned_count = sum(
                    1 for m in self.history 
                    if m.get("metadata", {}).get("pinned", False)
                )
                
                self.logger.info(f"Message {message_id} pinned successfully ({pinned_count}/10)")
                return {
                    "success": True,
                    "message": f"Message pinned successfully ({pinned_count}/10)",
                    "pinned_count": pinned_count,
                    "max_pinned": 10,
                    "action_required": None
                }
        
        # Message not found
        self.logger.warning(f"Cannot pin message {message_id}: message not found")
        return {
            "success": False,
            "message": "Message not found",
            "pinned_count": 0,
            "max_pinned": 10,
            "action_required": None
        }

    def unpin_message(self, message_id: str) -> bool:
        """
        Unpin a message to allow it to be summarized.
        
        This is the inverse operation of pin_message. Once unpinned, the message
        will be subject to normal summarization rules (unless it has evidence
        preservation flag set).
        
        Args:
            message_id: Unique identifier of the message to unpin
            
        Returns:
            True if message was successfully unpinned, False if message not found
        """
        # Find the message by ID
        for msg in self.history:
            if msg.get("id") == message_id:
                # Set pinned flag to false in metadata
                if "metadata" not in msg:
                    msg["metadata"] = {}
                
                msg["metadata"]["pinned"] = False
                
                # Log unpinning action to audit trail if available
                if hasattr(self.cm, 'truncation_auditor') and self.cm.truncation_auditor:
                    message_hash = self._hash_message(msg.get("content", ""))
                    self.cm.truncation_auditor.log_event(
                        action="UNPINNED",
                        message_id=message_id,
                        token_count=msg.get("token_count", 0),
                        reason="user_action",
                        message_hash=message_hash,
                        metadata={}
                    )
                
                # Save history to persist unpinned state
                self.save_history()
                
                self.logger.info(f"Message {message_id} unpinned successfully")
                return True
        
        # Message not found
        self.logger.warning(f"Cannot unpin message {message_id}: message not found")
        return False
    
    def unpin_oldest_pinned_message(self) -> Optional[str]:
        """
        Unpin the oldest pinned message.
        
        This is used when the pinning limit is reached and the user
        chooses to automatically unpin the oldest message.
        
        Returns:
            Message ID of the unpinned message, or None if no pinned messages exist
        """
        # Find all pinned messages with their pinned_at timestamps
        pinned_messages = []
        for msg in self.history:
            metadata = msg.get("metadata", {})
            if metadata.get("pinned"):
                pinned_at = metadata.get("pinned_at")
                pinned_messages.append((msg.get("id"), pinned_at))
        
        if not pinned_messages:
            self.logger.warning("No pinned messages to unpin")
            return None
        
        # Sort by pinned_at timestamp (oldest first)
        pinned_messages.sort(key=lambda x: x[1] if x[1] else "")
        
        # Unpin the oldest
        oldest_message_id = pinned_messages[0][0]
        self.unpin_message(oldest_message_id)
        
        self.logger.info(f"Automatically unpinned oldest message: {oldest_message_id}")
        return oldest_message_id

    def _migrate_existing_history(self, history: List[Dict]) -> List[Dict]:
        """
        Migrate existing conversation history to include metadata fields.
        
        This method ensures backward compatibility with conversation history
        files created before the evidence preservation feature was implemented.
        
        Migration steps:
        1. Add metadata field to messages that don't have it
        2. Add id field to messages that don't have it
        3. Don't retroactively detect evidence in old messages 
        
        Args:
            history: List of message dictionaries from loaded history file
            
        Returns:
            Migrated history with all required fields
        """
        migrated_history = []
        migration_count = 0
        
        for msg in history:
            # Check if message needs migration
            needs_migration = False
            
            # Add metadata field if missing
            if "metadata" not in msg:
                msg["metadata"] = {}
                needs_migration = True
            
            # Add id field if missing
            if "id" not in msg:
                msg["id"] = self._generate_message_id()
                needs_migration = True
            
            # Add token_count if missing (estimate from content)
            if "token_count" not in msg and "content" in msg:
                msg["token_count"] = self.cm.token_counter.count_tokens(msg["content"])
                needs_migration = True
            
            # Add timestamp if missing
            if "timestamp" not in msg:
                msg["timestamp"] = datetime.now().isoformat()
                needs_migration = True
            
            if needs_migration:
                migration_count += 1
            
            migrated_history.append(msg)
        
        if migration_count > 0:
            self.logger.info(
                f"Migrated {migration_count} messages to include metadata fields. "
                f"Evidence detection not applied retroactively ."
            )
            # Save migrated history
            self.save_history()
        
        return migrated_history
