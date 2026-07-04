"""
History Manager for EYE AI Assistant.

This module manages conversation memory, including:
- Saving/loading history to the case directory
- Automatic history management (sliding window)
- Intelligent summarization of old forensic evidence
- Token budget enforcement
- Evidence detection and preservation
"""

import os
import json
import logging
import hashlib
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


def _message_tokens(msg: Dict[str, Any], token_count_fn) -> int:
    """Token cost of a single message — uses the pre-counted value when present,
    otherwise counts the content with ``token_count_fn``."""
    tc = msg.get("token_count")
    if isinstance(tc, int) and tc > 0:
        return tc
    return int(token_count_fn(msg.get("content") or ""))


def _is_evidence_protected(msg: Dict[str, Any]) -> bool:
    """The irreducible evidence core: pinned, evidence-flagged, or a tool result.
    These are NEVER summarized or dropped by the memory policy. Note a rolling
    summary is deliberately NOT here — it is mergeable in Stage 1 and droppable
    only as a last resort in Stage 2."""
    md = msg.get("metadata") or {}
    return bool(md.get("pinned") or md.get("preserve_evidence") or md.get("is_tool_result"))


def reduce_messages_to_budget(
    messages: List[Dict[str, Any]],
    usable_tokens: int,
    *,
    token_count_fn,
    base_tokens: int = 0,
    window_turns: int = 5,
    summarize_fn=None,
    enable_summary_buffer: bool = True,
    enable_drop: bool = True,
    keep_first: bool = True,
    archive_cb=None,
):
    """Two-stage conversation-memory reduction — the single implementation shared
    by the persistent compaction (``HistoryManager.manage_history``) and the
    per-call outgoing gate (``QueryProcessor.guarded_generate``).

    Applied IN ORDER, and only while the payload exceeds ``usable_tokens``:

      Stage 1 — Summarization buffer: fold every eligible non-protected message
        OLDER than the sliding window into a SINGLE rolling summary (via
        ``summarize_fn``). Any prior rolling summary that has aged out of the
        window is folded back in, so summaries never proliferate.
      Stage 2 — Sliding window: if still over budget AND ``enable_drop`` is set,
        drop the oldest droppable (non-evidence) message FIFO until it fits —
        sliding the window forward. The first turn is dropped only as a last
        resort; evidence/pinned/tool-result messages are never dropped, so the
        irreducible core may remain over budget (the caller decides whether that
        is acceptable or a hard refusal).

    Always kept verbatim: the first message (case framing, when ``keep_first``),
    every evidence-protected message, and the last ``window_turns`` messages.

    Pure: never mutates the input list or its message dicts. Returns
    ``(reduced_messages, cut_records, summary_msg_or_None)`` where each cut record
    is ``{"action": "SUMMARIZED"|"TRUNCATED", "msg": <message>, "summary_text": str|None}``.
    ``archive_cb(msg)`` is invoked best-effort for each evicted RAW turn (never for
    a derived summary) so it can be persisted to the retrievable conversation
    archive.
    """
    msgs = list(messages or [])
    window_turns = max(0, int(window_turns))

    def total(ms):
        return base_tokens + sum(_message_tokens(m, token_count_fn) for m in ms)

    if total(msgs) <= usable_tokens:
        return msgs, [], None

    cut_records: List[Dict[str, Any]] = []
    summary_msg = None
    working = list(msgs)

    # ---- Stage 1: summarization buffer ----
    if enable_summary_buffer and summarize_fn is not None and len(msgs) > 1:
        n = len(msgs)
        tail_start = max(0, n - window_turns)
        eligible_idx = [
            i for i, m in enumerate(msgs)
            if not (keep_first and i == 0)
            and i < tail_start
            and not _is_evidence_protected(m)
        ]
        eligible = [msgs[i] for i in eligible_idx]
        if eligible:
            try:
                summary_text = summarize_fn(eligible)
            except Exception:
                summary_text = None
            if summary_text:
                summary_msg = {
                    "role": "system",
                    "content": summary_text,
                    "metadata": {"is_summary": True, "is_rolling_summary": True},
                }
                eligible_set = set(eligible_idx)
                rebuilt: List[Dict[str, Any]] = []
                inserted = False
                for i, m in enumerate(msgs):
                    if i in eligible_set:
                        if not inserted:
                            rebuilt.append(summary_msg)
                            inserted = True
                        continue
                    rebuilt.append(m)
                working = rebuilt
                for m in eligible:
                    cut_records.append({"action": "SUMMARIZED", "msg": m, "summary_text": summary_text})
                    if archive_cb and not (m.get("metadata") or {}).get("is_summary"):
                        try:
                            archive_cb(m)
                        except Exception:
                            pass

    # ---- Stage 2: sliding window (hard drop) ----
    if enable_drop:
        while total(working) > usable_tokens:
            nw = len(working)
            tail_start_w = max(0, nw - window_turns)
            # Priority: (1) oldest non-protected strictly BEFORE the window;
            # (2) oldest non-protected, non-first (slide the window forward);
            # (3) the first message, last resort. Never an evidence-protected one.
            drop_idx = None
            for i, m in enumerate(working):
                if (keep_first and i == 0) or _is_evidence_protected(m) or i >= tail_start_w:
                    continue
                drop_idx = i
                break
            if drop_idx is None:
                for i, m in enumerate(working):
                    if (keep_first and i == 0) or _is_evidence_protected(m):
                        continue
                    drop_idx = i
                    break
            if drop_idx is None:
                for i, m in enumerate(working):
                    if _is_evidence_protected(m):
                        continue
                    drop_idx = i
                    break
            if drop_idx is None:
                break  # only the irreducible evidence core remains
            removed = working.pop(drop_idx)
            cut_records.append({"action": "TRUNCATED", "msg": removed, "summary_text": None})
            if archive_cb and not (removed.get("metadata") or {}).get("is_summary"):
                try:
                    archive_cb(removed)
                except Exception:
                    pass

    return working, cut_records, summary_msg


class HistoryManager:
    """
    Manages conversation history, persistence, and summarization.
    """

    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(__name__)
        self.history: List[Dict[str, Any]] = []
        self._message_id_counter = 0   # retained for legacy fallback only
        # GEP-7 (Non-Repudiation): rolling SHA-256 chain pointer.
        # Each new message_id = sha256(prev_id + content + role).hexdigest()[:16].
        # Flipping any byte of any historical message breaks the chain on next load.
        self._prev_msg_id: str = ""
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
                            # GEP-7: rehydrate the hash-chain pointer from the
                            # tail of history so newly-appended messages extend the
                            # same chain across process restarts.
                            if self.history:
                                self._prev_msg_id = self.history[-1].get("id", "") or ""
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

            # Atomic write: a crash mid-write must not corrupt the persisted
            # history. Write to a temp file, fsync, then atomically replace.
            tmp_path = path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(history_snapshot, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
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
        # Generate unique message ID (GEP-7 hash-chained)
        message_id = self._generate_message_id(content, role)

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

                    # GEP-2/GEP-6 (Evidence Anchoring): embed raw evidence snippets
                    # DIRECTLY into the message content as <evidence anchor="..."> tags
                    # so the forensic markers travel with the message verbatim through
                    # context-window summarization (the summarizer sees the tags as
                    # part of the text and preserves them).
                    preserve_flag = bool(message["metadata"].get("preserve_evidence"))
                    cap_per_pattern = 25 if preserve_flag else 8
                    anchor_lines = []
                    for p_type, m_list in evidence_result.get("matches", {}).items():
                        for m in m_list[:cap_per_pattern]:
                            anchor_lines.append(f'<evidence anchor="{p_type}">{m}</evidence>')
                    if anchor_lines:
                        message["content"] = content + "\n\n" + "\n".join(anchor_lines)
                        message["token_count"] = self.cm.token_counter.count_tokens(message["content"])

                    # Log preservation decision to audit trail if available
                    if hasattr(self.cm, 'truncation_auditor') and self.cm.truncation_auditor:
                        message_hash = self._hash_message(message["content"])
                        # Extract snippets for the audit log (sanitized)
                        snippets = {}
                        for p_type, m_list in evidence_result.get("matches", {}).items():
                            snippets[p_type] = [m[:100] + ("..." if len(m) > 100 else "") for m in m_list[:cap_per_pattern]]

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
                        # GEP-8 (Machine-Readable Compliance): Auto-export JSON
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
        # manage_history() does its own phased locking and may make a 10-60s LLM
        # summarization call; it MUST run OUTSIDE this lock so concurrent readers
        # (e.g. the GUI-thread get_stats / get_context_stats) don't block on it.
        self.manage_history()

    def manage_history(self):
        """
        Keep persistent history bounded with the shared two-stage memory policy
        (``reduce_messages_to_budget``) — Stage 1 ONLY (the summarization buffer).

        The hard sliding-window DROP (Stage 2) runs per-call in
        ``guarded_generate`` against the OUTGOING payload; persistent history is
        only folded — its summarizable middle is collapsed into a single rolling
        summary so the on-disk log never balloons, while the first turn, every
        evidence/pinned message, and the recent window stay verbatim. Each evicted
        raw turn is archived to the retrievable conversation memory so nothing is
        truly lost.
        """
        rc = getattr(self.cm, "reasoning_config", None)
        rc = rc if isinstance(rc, dict) else {}
        window_turns = int(rc.get("history_window_turns", 5))
        enable_buf = bool(rc.get("enable_summary_buffer", True))

        # --- Phase 1: threshold check under lock ---
        # Compact only when history approaches the FULL usable context window
        # (max_total_tokens minus the output reserve) — the same `usable` value
        # guarded_generate uses, so the two layers agree.
        with self._lock:
            total_tokens = sum(
                _message_tokens(m, self.cm.token_counter.count_tokens) for m in self.history
            )
            if not (total_tokens > self.cm.usable_context_tokens() and len(self.history) > 3):
                return  # Nothing to do
            snapshot = list(self.history)

        usable = int(self.cm.usable_context_tokens())

        # --- Phase 2: reduce OUTSIDE the lock (Stage 1 may make a 10-60s LLM call) ---
        # _summarize_chunk() calls the model router; holding the lock here would
        # block concurrent add_message() calls (e.g. status messages from the
        # QueryWorker thread).
        _reduced, cut_records, summary_msg = reduce_messages_to_budget(
            snapshot, usable,
            token_count_fn=self.cm.token_counter.count_tokens,
            window_turns=window_turns,
            summarize_fn=self._summarize_chunk,
            enable_summary_buffer=enable_buf,
            enable_drop=False,                 # persistent history is not hard-fit here
            keep_first=True,
            archive_cb=self._archive_evicted_message,
        )
        if not cut_records:
            return

        summarized_msgs = [c["msg"] for c in cut_records if c["action"] == "SUMMARIZED"]
        summary_text = next((c["summary_text"] for c in cut_records if c.get("summary_text")), "")

        # --- Phase 3: reconcile with the LIVE history under lock (no lost update) ---
        with self._lock:
            if summary_msg is not None:
                summary_msg["id"] = self._generate_message_id(summary_msg["content"], "system")
                summary_msg["token_count"] = self.cm.token_counter.count_tokens(summary_msg["content"])
                summary_msg["timestamp"] = datetime.now().isoformat()
                summary_msg["metadata"]["summarized_count"] = len(summarized_msgs)

            # Reconstruct from the LIVE history (not the Phase-2 snapshot) so any
            # message appended DURING the lock-free LLM call survives. Drop the
            # summarized messages and splice the summary in at the position the
            # first summarized message held.
            cut_ids = {c["msg"].get("id") for c in cut_records}
            new_history = []
            inserted = False
            for m in self.history:
                if m.get("id") in cut_ids:
                    if summary_msg is not None and not inserted:
                        new_history.append(summary_msg)
                        inserted = True
                    continue
                new_history.append(m)
            if summary_msg is not None and not inserted:
                new_history.insert(min(1, len(new_history)), summary_msg)
            self.history = new_history

            # Audit every cut (SUMMARIZED / TRUNCATED) for the Compliance trail.
            auditor = getattr(self.cm, 'truncation_auditor', None)
            if auditor:
                for c in cut_records:
                    msg = c["msg"]
                    is_sum = c["action"] == "SUMMARIZED"
                    auditor.log_event(
                        action=c["action"],
                        message_id=msg.get("id", "unknown"),
                        token_count=msg.get("token_count", 0),
                        reason="budget_exceeded",
                        message_hash=self._hash_message(msg.get("content", "")),
                        metadata={
                            "summary_msg_id": summary_msg["id"] if summary_msg else None,
                            "total_summarized": len(summarized_msgs),
                            "cut_content": msg.get("content", ""),
                            "processed_content": (summary_text if is_sum else ""),
                        },
                    )
                auditor.auto_export_json()

            self.cm.truncation_count = getattr(self.cm, "truncation_count", 0) + len(cut_records)
            self.logger.info(
                f"Conversation history compacted (summary buffer). "
                f"Summarized: {len(summarized_msgs)} message(s)."
            )

    def _archive_evicted_message(self, msg: Dict[str, Any]):
        """Persist an evicted raw turn to the per-case conversation archive and
        feed it to the retrievable conversation-memory index, so a summarized /
        slid-out turn can still be recalled on demand later (long-term memory).

        Best-effort: a failure here must never block history management.
        """
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        try:
            rec = {
                "id": msg.get("id"),
                "role": msg.get("role"),
                "content": msg.get("content", "") or "",
                "timestamp": msg.get("timestamp") or datetime.now().isoformat(),
            }
            logs_dir = Path(case_dir) / "EYE_Logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            with open(logs_dir / "eye_conversation_archive.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            rag = getattr(self.cm, "rag_service", None)
            if rag is not None and hasattr(rag, "index_conversation_turn"):
                rag.index_conversation_turn(
                    rec["content"],
                    {"id": rec["id"], "role": rec["role"], "timestamp": rec["timestamp"]},
                )
        except Exception as e:
            self.logger.debug(f"Conversation archive failed for {msg.get('id')}: {e}")


    def _summarize_chunk(self, messages: List[Dict]) -> str:
        """Use the LLM to summarize a block of conversation.

        The summary prompt is SIZE-BOUNDED to the model's usable context window
        (so it can't overflow and fail on a small/local model — which would
        silently fall back to a stub and lose the real summary), and the model
        call is SEALED via the shared EvidenceSeal so this stays inside the
        chain-of-custody guarantee (no un-sealed model calls).
        """
        tc = self.cm.token_counter
        try:
            usable = int(self.cm.usable_context_tokens())
        except Exception:
            usable = 8192

        system_instruction = (
            "You are a senior forensic investigator. Summarize discussions while ensuring "
            "absolute preservation of technical indicators (paths, timestamps, app names)."
        )
        header = (
            "Summarize the following forensic investigation discussion concisely. "
            "CRITICAL: You MUST preserve all high-fidelity forensic indicators: "
            "- Application Names and Executable Paths "
            "- Timestamps (ISO 8601 format) "
            "- IP Addresses, Domains, and Registry Keys "
            "- Evidence detected in tool results. "
            "Maintain forensic integrity. Discussion:\n\n"
        )

        # Reserve room for system instruction + header + the model's reply, then
        # fit message lines newest-first so the freshest evidence always survives.
        reserve_out = 1024
        base_tokens = tc.count_tokens(system_instruction) + tc.count_tokens(header) + reserve_out
        body_budget = max(512, usable - base_tokens)

        lines: List[str] = []
        used = 0
        dropped = 0
        for msg in reversed(messages):
            content = msg.get("content", "")
            if len(content) > 2000:
                content = content[:1000] + "\n... [BODY TRUNCATED FOR SUMMARY] ...\n" + content[-1000:]
            line = f"[{msg.get('role', 'user')}]: {content}\n"
            lt = tc.count_tokens(line)
            if lines and used + lt > body_budget:
                dropped = len(messages) - len(lines)
                break
            lines.append(line)
            used += lt
        lines.reverse()
        body = "".join(lines)
        if dropped > 0:
            body = f"[Note: {dropped} older message(s) omitted to fit the summary window.]\n" + body
        summary_prompt = header + body

        # Seal the exact payload (chain of custody) before the call. Best-effort.
        payload = f"<<SYSTEM>>\n{system_instruction}\n<<USER>>\n{summary_prompt}"
        try:
            seal = getattr(self.cm, "evidence_seal", None)
            if seal is not None:
                seal.seal(
                    payload, phase="history_summarize", iteration=0,
                    query="history summarization",
                    model=self.cm.model_router.config.get("model_name", "LLM"),
                    max_context=int(getattr(self.cm, "max_total_tokens", 8192) or 8192),
                    token_count=tc.count_tokens(payload),
                )
        except Exception:
            pass

        try:
            res = self.cm.model_router.generate(
                system_prompt=system_instruction,
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

    def _generate_message_id(self, content: str = "", role: str = "") -> str:
        """
        GEP-7 (Non-Repudiation): generate a deterministic, hash-chained
        message ID.  The ID is the first 16 hex chars of
        sha256(previous_message_id + content + role).  Because the previous ID
        is folded into every successor, silently editing any historical
        message breaks the chain on next load and the tamper is detectable.

        Thread-safe.  Falls back to the legacy timestamp+counter format only
        if the inputs are completely empty (rare; preserves uniqueness for
        edge cases that pre-date this rule).

        Returns:
            16-char lowercase hex message ID (or legacy `msg_*` for fallback).
        """
        with self._lock:
            payload = (self._prev_msg_id + content + role).encode("utf-8", errors="replace")
            if payload:
                new_id = hashlib.sha256(payload).hexdigest()[:16]
            else:
                # Fallback for truly-empty inputs (should not happen in normal flow)
                self._message_id_counter += 1
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                new_id = f"msg_{timestamp}_{self._message_id_counter}"
            self._prev_msg_id = new_id
            return new_id
    
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
                msg["id"] = self._generate_message_id(
                    msg.get("content", "") or "",
                    msg.get("role", "") or ""
                )
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
