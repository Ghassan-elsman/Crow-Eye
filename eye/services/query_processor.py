"""
Query Processor for EYE AI Assistant.

This module acts as the "Central Nervous System" of the EYE Assistant. It 
orchestrates the complete investigative pipeline, transforming a raw natural 
language query into a verified forensic conclusion.

PIPELINE STAGES:
1. Intent Detection: Parsing the query for specific forensic targets.
2. RAG Retrieval: Pulling relevant knowledge-base articles about artifacts.
3. Prompt Construction: Merging case context, RAG results, and history.
4. AI Consultation: Calling the configured LLM (Cloud or Local).
5. Tool Execution: Running SQL/Search handlers based on AI requests.
6. Forensic Synthesis: Final validation and reporting using the 
   'Forensic Evidence Protocol' for technical evidence.

UI FEEDBACK:
The processor uses a 'ThinkingStep' JSON protocol to provide real-time updates 
to the React frontend, allowing the investigator to see the AI's logic trail.
"""

import json
import logging
import sqlite3
import os
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from eye.services.evidence_seal import EvidenceSeal
from eye.services.history_manager import reduce_messages_to_budget
from eye.services.rag_service import _rag_tokenize
from eye.services.report_engine import is_triage_block


_TRANSIENT_ERROR_MARKERS = (
    "500", "502", "503", "504",
    "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED",
    "timeout", "timed out", "temporarily unavailable",
    "connection reset", "connection aborted",
)


def _is_transient_model_error(exc: Exception) -> bool:
    """A model-call exception is treated as transient (and therefore retryable
    exactly once) only when it looks like a server-side hiccup. Quota / auth /
    bad-request failures are NOT transient and must surface immediately so the
    user can act on them."""
    s = str(exc)
    if any(m in s for m in ("401", "403", "429", "INVALID_ARGUMENT", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED", "quota")):
        return False
    return any(m in s for m in _TRANSIENT_ERROR_MARKERS)


# A forensic evidence reference: ``database:table:rowid``. The database segment is
# matched greedily so imported-evidence DB names (which may contain spaces, dots, or
# a subpath under Target_Artifacts/Imported_Evidence/) are captured whole; the table
# is a SQL identifier and the rowid is an integer.
_EVIDENCE_REF_RE = re.compile(r'^(?P<db>.+):(?P<table>[A-Za-z_]\w*):(?P<rowid>\d+)$')


def _source_from_ref(ref: str) -> tuple:
    """Turn a ``database:table:rowid`` evidence ref into ``(database, query)`` so an
    evidence card can reload its real source row on demand — for BOTH native artifacts
    and imported evidence. Returns ``("", "")`` when ``ref`` is not a row pointer
    (e.g. it is just a tool name)."""
    if not ref:
        return "", ""
    m = _EVIDENCE_REF_RE.match(ref.strip())
    if not m:
        return "", ""
    return m.group("db").strip(), f'SELECT * FROM "{m.group("table")}" WHERE rowid = {m.group("rowid")}'


def _source_from_row(row) -> tuple:
    """Turn one provenance row (as returned by search / imported-evidence
    correlation / semantic search — carrying ``database`` + ``table`` +
    ``row_id``/``rowid``/``__rid``) into ``(database, query)`` so the evidence card
    can reload the REAL source row. Returns ``("", "")`` when provenance is absent."""
    if not isinstance(row, dict):
        return "", ""
    db = row.get("database") or row.get("db") or row.get("source_database")
    table = row.get("table") or row.get("table_name")
    rid = row.get("row_id", row.get("rowid", row.get("__rid")))
    if db and table and rid is not None:
        try:
            return str(db), f'SELECT * FROM "{table}" WHERE rowid = {int(rid)}'
        except (ValueError, TypeError):
            return "", ""
    return "", ""


def _source_from_result(r: dict, inner: dict) -> tuple:
    """Best-effort reloadable source for a tool result that did NOT take raw SQL
    (search_artifacts, correlate_imported_evidence, semantic search). These tools
    still return ``database:table:row_id`` provenance, so derive a single-row query
    from it — this is what makes NATIVE and IMPORTED evidence loadable. Returns
    ``(database, query)`` or ``("", "")``."""
    # 1. Explicit ref string(s) on the result.
    for key in ("evidence_refs", "refs", "ref"):
        refs = inner.get(key) or r.get(key)
        if isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, list):
            for ref in refs:
                db, q = _source_from_ref(str(ref))
                if db and q:
                    return db, q
    # 2. Structured rows carrying provenance (list, or {value: [rows]} maps).
    for container in (inner.get("data"), r.get("data"), inner.get("matches"), inner.get("rows")):
        rows = []
        if isinstance(container, list):
            rows = container
        elif isinstance(container, dict):
            for v in container.values():
                if isinstance(v, list):
                    rows.extend(v)
        for row in rows:
            db, q = _source_from_row(row)
            if db and q:
                return db, q
    return "", ""


class ContextOverflowError(Exception):
    """Raised when an assembled LLM payload exceeds the model's context window.

    The pipeline REFUSES to proceed (rather than silently truncating evidence)
    so the chain of custody is never quietly broken — the investigator is told
    to narrow the query or use map-reduce analysis.
    """
    def __init__(self, payload_tokens: int, max_context: int, reserve: int):
        self.payload_tokens = payload_tokens
        self.max_context = max_context
        self.reserve = reserve
        super().__init__(
            f"Payload {payload_tokens} tokens exceeds the usable context window "
            f"({max_context} - {reserve} reserved = {max_context - reserve} tokens)."
        )


class QueryProcessor:
    """
    Main Orchestrator for the Forensic Investigation Pipeline.
    
    This class is state-agnostic and relies on the provided ContextManager
    to interact with the case database, history, and AI backends.
    """

    # Forensic artifacts Crow-Eye parses + what each provides. Single source of
    # truth used to ground the hierarchical planner so every sub-narrative maps its
    # `evidence_needed` to the artifact that actually holds the evidence. Matches the
    # artifact set in IntentEngine. The execution model still resolves the exact
    # database/table at query time, so a not-collected artifact just returns nothing.
    ARTIFACT_CATALOG = [
        ("Prefetch", "execution history, run count, first/last run timestamps"),
        ("Registry", "AutoRun/persistence, UserAssist (GUI program runs), BAM (background activity), "
                     "networks — also ShellBags (folder views/access) and MRU & RecentDocs (typed paths, Open/Save)"),
        ("Jump Lists & LNK", "file access, paths, target metadata"),
        ("Event Logs", "System, Security (logons/4624/4688), Application"),
        ("AmCache", "full path, install time, publisher, SHA-1"),
        ("ShimCache", "file name, path, last modified (presence/execution evidence)"),
        ("MFT", "file metadata, timestamps, deleted-file records"),
        ("USN Journal", "file create/modify/delete/rename history"),
        ("Recycle Bin", "deleted file names, original paths, deletion times"),
        ("SRUM", "per-app resource usage, network bytes sent/received, energy"),
    ]

    @classmethod
    def _artifact_catalog_block(cls) -> str:
        """Render ARTIFACT_CATALOG as a compact reference for the planner prompt."""
        return "\n".join(f"  - {name}: {desc}" for name, desc in cls.ARTIFACT_CATALOG)

    def __init__(self, context_manager):
        """
        Args:
            context_manager: Instance of eye.services.context_manager.ContextManager
        """
        self.cm = context_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    def _push_narrative_map_update(self, change: dict = None, audit: dict = None) -> None:
        """Notify the UI that the Narrative Map changed mid-investigation (auto-sync,
        evidence attach, state flip) so any open map window live-refreshes. The
        bridge registers ``narrative_map_update_callback`` on the ContextManager;
        when absent (e.g. headless) this is a no-op. Best-effort."""
        try:
            cb = getattr(self.cm, "narrative_map_update_callback", None)
            if callable(cb):
                cb(change, audit)
        except Exception as e:
            self.logger.debug(f"narrative map update push skipped: {e}")

    def _sync_narratives_from_findings(self, checklist, all_tool_results, trace, emit_step,
                                       user_query: str = "", ai_content: str = "") -> None:
        """Create Narrative Map narratives from the FINDINGS of this turn.

        A narrative is a finding/claim — NOT the question. The card title is the
        conclusion (from the reasoning ``trace`` when available, else the best
        supporting evidence snippet); the originating sub-question is kept only as
        ``meta.created_from`` provenance. A sub-question that was checked but yielded
        nothing becomes a ``negative`` narrative so completeness is preserved.

        If ``cm._focus_narrative_id`` is set (a double-click "investigate further"
        run), newly-found evidence is attached to THAT narrative instead of creating
        new cards. Best-effort; never raises."""
        nms = getattr(self.cm, "narrative_map_service", None)
        if nms is None:
            return
        import re as _re

        def _toks(s):
            return {w for w in _re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", (s or "").lower())}

        def _model():
            try:
                return self.cm.model_router.config.get("model_name") or ""
            except Exception:
                return ""

        def _best_result(q):
            q_tokens = _toks(q)
            best, best_score = None, 0
            for r in (all_tool_results or []):
                if not isinstance(r, dict):
                    continue
                inner = r.get("result") if isinstance(r.get("result"), dict) else {}
                if not (r.get("success") or inner.get("success")):
                    continue
                blob = str(r.get("data") or inner.get("data") or inner or "")
                score = len(q_tokens & _toks(blob))
                if score > best_score:
                    best, best_score = r, score
            return best, best_score

        def _evidence_of(r):
            inner = r.get("result") if isinstance(r.get("result"), dict) else {}
            params = r.get("parameters") or {}
            tool = r.get("tool_name") or inner.get("tool_name") or "tool"
            blob = str(r.get("data") or inner.get("data") or inner or "")
            # The SQL + database that produced this result, so the evidence can
            # reload its source rows in the map's detail window.
            query = params.get("sql_query") or ""
            database = params.get("database_name") or ""
            # Fallback for tools that don't take raw SQL (search_artifacts,
            # correlate_imported_evidence, semantic search): derive a reloadable
            # single-row query from the result's database:table:rowid provenance, so
            # the evidence card shows the REAL row — incl. imported evidence.
            if not (query and database):
                db2, q2 = _source_from_result(r, inner)
                if db2 and q2:
                    database, query = db2, q2
            return tool, blob, query, database

        # ── Focused re-investigation of ONE narrative (double-click) ──
        focus_id = getattr(self.cm, "_focus_narrative_id", None)
        if focus_id:
            # Clear it immediately so a later query can never inherit the focus and
            # mis-attach its findings (the bridge's own clear becomes a no-op).
            try:
                self.cm._focus_narrative_id = None
            except Exception:
                pass
            added = 0
            for r in (all_tool_results or []):
                if not isinstance(r, dict):
                    continue
                inner = r.get("result") if isinstance(r.get("result"), dict) else {}
                if not (r.get("success") or inner.get("success")):
                    continue
                tool, blob, query, database = _evidence_of(r)
                if not blob.strip():
                    continue
                if nms.attach_evidence(focus_id, {
                    "kicker": tool,
                    "data": (blob[:120] + "…") if len(blob) > 120 else blob,
                    "reason": "Additional evidence found during deeper investigation.",
                    "ref": tool, "query": query, "database": database,
                }):
                    added += 1
            if added:
                try:
                    emit_step("synthesis", f"Narrative Map: attached {added} new finding(s)", "done")
                except Exception:
                    pass
                self._push_narrative_map_update()
            return

        # ── Normal turn: build the 4-level claim tree ──────────────────────────
        #   VERDICT  (goal-claim, handled in _finalize_verdict)
        #     └─ MAIN narrative   = a sub-question rendered as a CLAIM the Eye proves
        #           └─ SUB narrative = a specific behavior that was established
        #                 • evidence = the tool output that proves the behavior
        # Card titles always say what is being PROVEN — never the raw (typo-ridden)
        # user question; the question survives only as meta.created_from provenance.
        items = [c for c in (checklist or []) if c.get("kind") != "premise"]
        if not items:
            return
        trace_subs = (trace or {}).get("sub_questions") or []
        model = _model()

        def _ev_from_best(q):
            """Evidence card from the best-matching tool result for ``q`` (reloadable)."""
            best, best_score = _best_result(q)
            if best is None or best_score <= 0:
                return None
            tool, blob, query, database = _evidence_of(best)
            return {
                "kicker": tool,
                "data": (blob[:120] + "…") if len(blob) > 120 else blob,
                "reason": "Result that established this finding.",
                "ref": tool, "query": query, "database": database,
            }

        def _ev_from_trace(refs):
            """Evidence cards from trace ``[{ref,note}]`` refs cited for a behavior."""
            cards = []
            for e in (refs or []):
                if not isinstance(e, dict):
                    continue
                ref = (e.get("ref") or "").strip()
                note = (e.get("note") or "").strip()
                if not (ref or note):
                    continue
                # If the ref is a database:table:rowid pointer, derive a reloadable
                # source so the card shows the REAL row (native or imported evidence).
                database, query = _source_from_ref(ref)
                cards.append({
                    "kicker": ref or "evidence",
                    "data": note or ref,
                    "reason": "Evidence cited for this behavior.",
                    "ref": ref,
                    "query": query,
                    "database": database,
                })
            return cards

        created = 0
        for idx, c in enumerate(items):
            q = c.get("q", "")
            answered = c.get("status") == "answered"
            conclusion, why, behaviors = "", c.get("why", ""), []
            is_inconclusive = False
            tsub = trace_subs[idx] if idx < len(trace_subs) else None
            if isinstance(tsub, dict):
                conclusion = (tsub.get("conclusion") or "").strip()
                why = (tsub.get("why_concluded") or why or "").strip()
                behaviors = tsub.get("behaviors") or []
                if str(tsub.get("status", "")).lower() == "inconclusive":
                    answered = False
                    is_inconclusive = True

            # MAIN narrative = the sub-question as a clean claim (the Eye's conclusion
            # if it reached one, else a deterministic claim — NEVER the raw question).
            main_title = conclusion or self._claimify(q) or "Investigation finding"
            main_id = nms.upsert_finding_narrative(
                main_title, why or "Sub-claim under investigation.",
                q, evidence=[], state="open", model=model)
            if not main_id:
                continue
            created += 1

            # An inconclusive sub-question is never a proven claim, even if a tool
            # result keyword-matched or the model emitted behaviors for it.
            positive = (answered or bool(conclusion) or bool(behaviors)) and not is_inconclusive
            child_states = []

            if positive and behaviors:
                # SUB narrative per specific behavior, each with its own evidence.
                for bi, beh in enumerate(behaviors):
                    claim = (beh.get("claim") or "").strip()
                    if not claim:
                        continue
                    bwhy = (beh.get("why") or "").strip()
                    ev = _ev_from_trace(beh.get("evidence"))
                    if not ev:  # behavior unbacked by trace refs → fall back to the
                        card = _ev_from_best(q)  # sub-question's best tool result
                        ev = [card] if card else []
                    state = "proven" if ev else "negative"
                    if nms.upsert_finding_narrative(
                            claim, bwhy or "Specific behavior establishing the claim.",
                            f"{q}::beh:{bi}", evidence=ev, state=state,
                            model=model, parent=main_id):
                        created += 1
                        child_states.append(state)
            elif positive:
                # Graceful degrade (no behavior breakdown): attach the best tool
                # result straight to the sub-question claim (3-level).
                card = _ev_from_best(q)
                if card:
                    nms.attach_evidence(main_id, card, model=model)  # flips → proven
                    child_states.append("proven")

            # Roll the main claim's state up from its behavior children.
            if "proven" in child_states:
                nms.set_state(main_id, "proven",
                              reason="Established by the behavior(s) below.", model=model)
            else:
                nms.set_state(main_id, "negative",
                              reason=(why or f"Checked for: {q} — nothing established."),
                              model=model)

        if created:
            try:
                emit_step("synthesis", f"Narrative Map: recorded {created} finding(s)", "done")
            except Exception:
                pass
            self._push_narrative_map_update()

    @staticmethod
    def _claimify(text: str) -> str:
        """Turn a (possibly messy / typo-ridden) question into a clean declarative
        CLAIM for a card title — the map shows *what we are trying to prove*, never the
        raw question. This is a FALLBACK only; the Eye's reasoning conclusion / behavior
        claim (already declarative) is preferred. An interrogative becomes
        ``Whether <…>`` (the proposition under investigation — grammatical for any
        phrasing and robust to the user's formatting). Returns '' for empty input."""
        import re as _re
        t = _re.sub(r'[*_`#>]+', ' ', (text or "")).strip()
        t = t.strip('"\'' + "“”‘’").strip()
        t = " ".join(t.split())
        if not t:
            return ""
        t = t.rstrip("?").strip()
        if not t:
            return ""
        # Leading auxiliary / copula → drop it and frame the proposition with
        # "Whether" (yes/no questions: "is X bad" → "Whether X bad"). Wh-questions
        # keep their question word (it names what is being determined). Anything
        # else is already declarative → just capitalize.
        aux = {"is", "are", "am", "was", "were", "do", "does", "did", "can",
               "could", "has", "have", "had", "will", "would", "should", "may",
               "might"}
        wh = {"who", "what", "when", "where", "why", "how", "which", "whose", "whom"}
        parts = t.split(" ", 1)
        first = parts[0].lower()
        if first in aux and len(parts) > 1:
            rest = parts[1].strip()
            claim = "Whether " + rest if rest else "Whether " + t
        elif first in wh:
            claim = t[0].upper() + t[1:]
        else:
            claim = t[0].upper() + t[1:]
        return claim[:160]

    @staticmethod
    def _build_map_checklist(checklist, user_query: str, all_tool_results) -> list:
        """The checklist to feed the reasoning-trace + Narrative Map sync.

        A NON-decomposed but *investigative* turn (the planner produced no
        sub-question, yet the Eye ran tools and answered) still gets ONE main claim —
        the whole question — so the Eye's logical thinking ALWAYS reaches the map.
        The synthetic item is for the map/trace only; the investigation ``checklist``
        (which drives the loop and prompt injection) is never mutated. A pure-chat
        turn with no successful tool result is left off the map (no spurious verdict
        for "hello")."""
        checklist = checklist or []
        has_question = any(c.get("kind") != "premise" for c in checklist)
        had_results = any(
            isinstance(r, dict) and (
                r.get("success")
                or (isinstance(r.get("result"), dict) and r["result"].get("success"))
            )
            for r in (all_tool_results or [])
        )
        if not has_question and had_results:
            return list(checklist) + [
                {"q": user_query, "status": "answered", "kind": "question", "why": ""}
            ]
        return list(checklist)

    @staticmethod
    def _strip_tool_call_blocks(text: str) -> str:
        """Remove fenced ```tool_call / ```tool_calls blocks from a chat answer.

        Text-protocol tool calls (the Gemma fallback) are emitted INSIDE the model's
        reply text; they belong in the dedicated "Tool output" section, not the main
        chat bubble. The structured calls + their results are preserved separately
        (eye_dialogue + tool_output), so stripping them here only cleans the prose.
        Never raises."""
        if not text:
            return text
        import re as _re
        try:
            cleaned = _re.sub(r"```tool_calls?\b[^\n]*\n.*?```", "", text,
                              flags=_re.DOTALL | _re.IGNORECASE)
            # Collapse the blank gap a removed block leaves behind.
            cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            return cleaned or text.strip()
        except Exception:
            return text

    @staticmethod
    def _build_tool_output(all_tool_results: list) -> list:
        """Compact per-turn tool-call/result list for the dedicated "Tool output" UI
        section (collapsed by default). One entry per executed tool: name, the call
        parameters, success, and the result text (truncated). Never raises."""
        import json as _json
        out = []
        for r in (all_tool_results or []):
            if not isinstance(r, dict):
                continue
            name = r.get("tool_name") or r.get("name") or "tool"
            params = r.get("parameters") if isinstance(r.get("parameters"), dict) else {}
            inner = r.get("result") if isinstance(r.get("result"), dict) else r
            success = bool(r.get("success") or (isinstance(inner, dict) and inner.get("success")))
            try:
                payload = inner.get("data", inner) if isinstance(inner, dict) else inner
                result_text = payload if isinstance(payload, str) else _json.dumps(payload, default=str)
            except Exception:
                result_text = str(inner)
            if len(result_text) > 6000:
                result_text = result_text[:6000] + "\n… [truncated — full result in the data viewer]"
            out.append({
                "name": name,
                "parameters": params,
                "success": success,
                "result_text": result_text,
            })
        return out

    @staticmethod
    def _headline(text: str) -> str:
        """First sentence of the synthesis answer, markdown-stripped, ~120 chars —
        used as the MAIN narrative's title (a finding, not the question)."""
        import re as _re
        t = _re.sub(r'[*_`#>\-]+', ' ', (text or "")).strip()
        t = _re.split(r'(?<=[.!?])\s+', t)[0] if t else ""
        t = " ".join(t.split())
        return (t[:117] + "…") if len(t) > 120 else t

    def _finalize_verdict(self, ai_content: str, user_query: str = "") -> str:
        """Author the case Verdict as a GOAL-CLAIM and flip its lifecycle state,
        returning the chat answer with the `VERDICT:` directive line removed.

        The verdict says what the whole investigation is trying to prove — never the
        raw question and never the generic "Overall verdict" seed. Title = the AI's
        crafted `VERDICT:` directive if present, else a deterministic claim from the
        user's goal (`_claimify`). State (Phase-1 lifecycle): ``proven`` if any main
        claim was proven, ``unproven`` if mains were checked but none proven, else
        left ``open``. Best-effort; never raises."""
        nms = getattr(self.cm, "narrative_map_service", None)
        if not nms or not ai_content:
            return ai_content
        import re
        title, reason = None, ""
        try:
            m = re.search(r'(?im)^[ \t>*\-]*VERDICT:\s*(.+?)\s*$', ai_content)
            if m:
                line = m.group(1).strip().strip('`').strip()
                if "||" in line:
                    title, reason = (p.strip() for p in line.split("||", 1))
                else:
                    title = line
                # Remove the directive line from the chat answer.
                ai_content = re.sub(r'(?im)^[ \t>*\-]*VERDICT:.*$\n?', '', ai_content).strip()

            model = None
            try:
                model = self.cm.model_router.config.get("model_name")
            except Exception:
                pass

            g = nms.load_graph()
            narratives = g.get("narratives", [])
            # Main claims = narratives that link straight to the verdict.
            verdict_id = (g.get("verdict") or {}).get("id")
            link_to = {l.get("from"): l.get("to") for l in g.get("links", [])}
            mains = [n for n in narratives if link_to.get(n.get("id")) == verdict_id]
            main_states = [n.get("state") for n in mains]
            any_proven = any(s in ("proven", "absolute") for s in main_states)

            if not title:
                # Goal-claim from the user's question — never the seeded default.
                cur = (g.get("verdict") or {}).get("title", "").strip().lower()
                if cur in ("", "overall verdict"):
                    title = self._claimify(user_query) or None
                    if title and not reason:
                        proven = [n.get("title", "") for n in mains
                                  if n.get("state") in ("proven", "absolute") and n.get("title")]
                        reason = ("Established by: " + "; ".join(proven[:5])) if proven else \
                                 "No supporting claim could be established."

            if title:
                nms.set_verdict(title, reason, model=model)

            # Lifecycle state: open → proven / unproven from the main claims' rollup.
            if mains:
                new_state = "proven" if any_proven else "unproven"
                nms.set_verdict_state(
                    new_state,
                    reason=("A main claim was established." if any_proven
                            else "All main claims were checked; none could be established."),
                    model=model)

            if title or mains:
                self._push_narrative_map_update()
        except Exception as e:
            self.logger.debug(f"verdict finalize skipped: {e}")
        return ai_content

    def _tool_output_char_limit(self) -> int:
        """Max chars of a single tool output kept in memory/history.

        Scales with the window: the ``tool_results`` TOKEN budget (~4 chars/token,
        and itself scaled by ``_scale_token_budget``) sets a ceiling that the
        configured ``max_tool_output_chars`` floors — so a large window is not
        truncated more aggressively than the token budget allows (audit P3 #11).
        Never exceeds ~50% of the usable window for any one tool output, and never
        below a 4000-char minimum.
        """
        max_ctx = int(getattr(self.cm, "max_total_tokens", 8192) or 8192)
        reserve = min(max(512, int(max_ctx * 0.1)), max(1, max_ctx // 2))
        usable = max_ctx - reserve
        configured_char_floor = int(getattr(self.cm, "max_tool_output_chars", 100000) or 100000)
        try:
            tool_results_tokens = int((getattr(self.cm, "token_budget", {}) or {}).get("tool_results", 0))
        except (TypeError, ValueError):
            tool_results_tokens = 0
        token_aware_ceiling = max(configured_char_floor, tool_results_tokens * 4)
        adaptive_char_limit = int(usable * 0.5 * 4)
        return max(4000, min(token_aware_ceiling, adaptive_char_limit))

    def _retrieve_conversation_recall(self, user_query: str, emit_step) -> str:
        """Retrieve earlier turns (summarized / slid out of the live window) that
        are relevant to ``user_query`` — the long-term-memory companion to the
        two-stage history policy. Gated by ``reasoning_config`` and budgeted from
        ``token_budget['conversation_recall']``. Best-effort: any failure or a
        backend without the method degrades to no recall (returns "").
        """
        rc = getattr(self.cm, "reasoning_config", None)
        rc = rc if isinstance(rc, dict) else {}
        if not rc.get("enable_conversation_recall", True):
            return ""
        rag = getattr(self.cm, "rag_service", None)
        if rag is None or not hasattr(rag, "retrieve_conversation"):
            return ""
        try:
            budget = int((getattr(self.cm, "token_budget", {}) or {}).get("conversation_recall", 600))
            top_k = int(rc.get("conversation_recall_top_k", 3))
            recalled = rag.retrieve_conversation(
                user_query=user_query, max_tokens=max(200, budget), top_k=top_k,
            )
            if recalled:
                _srcs = list(getattr(rag, "last_conversation_sources", []) or [])
                emit_step(
                    "rag",
                    f"Recalled {len(_srcs)} earlier conversation turn(s) from memory",
                    "done",
                )
            return recalled or ""
        except Exception as e:
            self.logger.debug(f"Conversation recall skipped: {e}")
            return ""

    def _build_subquestion_context(self, subq_items, history_snapshot, user_query,
                                   rag_params, emit_step) -> str:
        """Per-sub-question structured context: for each decomposed sub-question,
        attach its OWN targeted RAG knowledge plus its RELATED EVIDENCE (matching
        report blocks + pinned chat, prior findings, conversation recall, and
        semantic row candidates). Bounded; every source is best-effort and
        degrades to nothing when unavailable. Returns '' when nothing useful.
        """
        try:
            cm = self.cm
            top_k = int(rag_params.get("top_k", 2))
            min_score = float(rag_params.get("min_score", 0.05))
            sem_min = float(rag_params.get("semantic_min_score", 0.4))
            per_q_rag_budget = int(rag_params.get("per_q_budget", 500))
            max_qs = int(rag_params.get("max_qs", 6))

            # Pre-gather reusable evidence sources once.
            blocks = []
            try:
                blocks = [b for b in (getattr(cm.report_engine, "blocks", None) or [])
                          if not is_triage_block(b)]
            except Exception:
                blocks = []
            pinned_msgs = [m for m in (history_snapshot or [])
                           if (m.get("metadata") or {}).get("pinned")
                           or (m.get("metadata") or {}).get("preserve_evidence")]
            prior = []
            try:
                if getattr(cm, "case_context_manager", None):
                    prior = cm.case_context_manager.get_recent_question_memory(limit=8) or []
            except Exception:
                prior = []

            def _block_text(b):
                return " ".join(str(getattr(b, f, "") or "") for f in
                                ("title", "caption", "sql_query", "reference_text", "markdown_content"))

            sections = []
            for sq in subq_items[:max_qs]:
                if not sq:
                    continue
                q_tokens = set(_rag_tokenize(sq))
                lines = [f"### SubQ: {sq[:200]}"]

                # 1. Targeted knowledge for this sub-question.
                try:
                    kws = list(cm.intent_engine.detect_keywords(sq)) if getattr(cm, "intent_engine", None) else []
                except Exception:
                    kws = []
                knowledge = ""
                try:
                    knowledge = cm.rag_service.retrieve_context(
                        keywords=kws, user_query=sq, max_tokens=per_q_rag_budget,
                        top_k=top_k, min_score=min_score, semantic_min_score=sem_min,
                    ) or ""
                except Exception:
                    knowledge = ""
                if isinstance(knowledge, str) and knowledge.strip():
                    lines.append("  Knowledge: " + knowledge.strip()[:per_q_rag_budget * 2])

                evidence = []
                # 2. Matching report blocks (cite by id; full data in Living Report Evidence).
                try:
                    scored = sorted(
                        ((len(q_tokens & set(_rag_tokenize(_block_text(b)))), b) for b in blocks),
                        key=lambda x: x[0], reverse=True)
                    for sc, b in scored[:2]:
                        if sc <= 0:
                            break
                        bid = getattr(b, "block_id", "?")
                        btype = getattr(b, "block_type", "block")
                        title = getattr(b, "title", None) or getattr(b, "caption", None) or btype
                        evidence.append(f"report [{btype} {bid}] {str(title)[:80]}")
                except Exception:
                    pass
                # 3. Matching pinned chat evidence.
                try:
                    scored_p = sorted(
                        ((len(q_tokens & set(_rag_tokenize(m.get('content', '')))), m) for m in pinned_msgs),
                        key=lambda x: x[0], reverse=True)
                    for sc, m in scored_p[:1]:
                        if sc <= 0:
                            break
                        evidence.append("pinned: " + str(m.get("content", ""))[:140])
                except Exception:
                    pass
                # 4. Prior findings relevant to this sub-question.
                try:
                    scored_pf = sorted(
                        ((len(q_tokens & set(_rag_tokenize(str(r.get('question', '')) + ' ' + str(r.get('answer_summary', ''))))), r)
                         for r in prior), key=lambda x: x[0], reverse=True)
                    for sc, r in scored_pf[:1]:
                        if sc <= 0:
                            break
                        evidence.append(f"prior [{r.get('id','q?')}] {str(r.get('answer_summary',''))[:140]}")
                except Exception:
                    pass
                # 5. Conversation recall for this sub-question.
                try:
                    rag = getattr(cm, "rag_service", None)
                    if rag is not None and hasattr(rag, "retrieve_conversation"):
                        rc = rag.retrieve_conversation(user_query=sq, max_tokens=300, top_k=1)
                        if isinstance(rc, str) and rc.strip():
                            evidence.append("recall: " + rc.strip().replace("\n", " ")[:140])
                except Exception:
                    pass
                # 6. Semantic row candidates (only when the evidence index is available).
                try:
                    esvc = getattr(cm, "evidence_index_service", None)
                    if esvc is not None and esvc.available():
                        sres = esvc.search(sq, top_k=3)
                        cands = sres.get("candidates", []) if isinstance(sres, dict) else []
                        refs = [f"{c.get('database')}:{c.get('table')}#{c.get('rowid')}" for c in cands[:3]]
                        if refs:
                            evidence.append("candidates: " + ", ".join(refs))
                except Exception:
                    pass

                if evidence:
                    lines.append("  Related evidence:")
                    for e in evidence:
                        lines.append(f"    - {e}")
                # 7. Narrative Map slice — proven/open narratives + investigator NOTES
                # whose keywords overlap this sub-question. This is how a human note
                # added in the map reaches the model verbatim for the relevant part.
                try:
                    nms = getattr(cm, "narrative_map_service", None)
                    nm_slice = nms.relevant_slice(sq) if nms is not None else ""
                    if isinstance(nm_slice, str) and nm_slice.strip():
                        lines.append("  " + nm_slice.replace("\n", "\n  "))
                except Exception:
                    pass
                if len(lines) > 1:
                    sections.append("\n".join(lines))

            if not sections:
                return ""

            block = ("## Per Sub-Question Context\n"
                     "(Targeted knowledge + already-known evidence for each part of the question — "
                     "use it; confirm specifics with tools as needed.)\n" + "\n".join(sections))
            # Bound the whole block to a slice of the system-prompt budget.
            try:
                cap = int((getattr(cm, "token_budget", {}) or {}).get("system_prompt", 4000)) // 2
                block = cm.token_counter.truncate_text(block, max(800, cap))
            except Exception:
                pass
            try:
                emit_step("rag", f"Attached per-sub-question context for {len(sections)} sub-question(s)", "done")
            except Exception:
                pass
            return block
        except Exception as e:
            self.logger.debug(f"Per-sub-question context skipped: {e}")
            return ""

    def _emit_coverage(self, consulted_dbs, sampled: bool, user_query: str, emit_step) -> Dict[str, Any]:
        """Surface a COVERAGE note for the human reviewer: which case databases the
        Eye consulted vs. which exist, and whether any result was a sample rather
        than the full set. This does NOT auto-guarantee completeness (sensitive
        evidence is always reviewed by a real investigator) — it just makes the
        gaps visible. Persisted to EYE_Logs/eye_coverage_log.jsonl. Best-effort.
        """
        try:
            available = []
            try:
                for d in (self.cm.database_service.discover_databases() if self.cm.database_service else []):
                    if d.get("accessible") and d.get("exists") and d.get("name"):
                        available.append(d["name"])
            except Exception:
                available = []

            consulted = sorted(consulted_dbs)
            not_consulted = sorted(set(available) - set(consulted_dbs))
            coverage = {
                "consulted": consulted,
                "not_consulted": not_consulted,
                "available_count": len(available),
                "sampled": bool(sampled),
            }

            parts = []
            if consulted:
                parts.append("Consulted: " + ", ".join(consulted))
            if not_consulted:
                parts.append("NOT consulted: " + ", ".join(not_consulted))
            if sampled:
                parts.append("one or more results were a SAMPLE (use analyze_large_dataset for the full set)")
            note = "Coverage — " + ("; ".join(parts) if parts else "no databases consulted")
            emit_step("coverage", note, "done")

            try:
                if self.cm.case_directory:
                    from pathlib import Path as _Path
                    logs = _Path(self.cm.case_directory) / "EYE_Logs"
                    logs.mkdir(parents=True, exist_ok=True)
                    rec = {"ts": datetime.now().isoformat(), "query": user_query, **coverage}
                    with open(logs / "eye_coverage_log.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass
            return coverage
        except Exception as e:
            self.logger.debug(f"Coverage emit skipped: {e}")
            return {}

    def _run_python_triage(self, emit_step, check_report_sync, initial_report_state):
        """
        Comprehensive automated forensic triage.
        Extracts key artifacts across all major categories to build a high-fidelity living report.
        """
        emit_step("tool_call", "Discovering Forensic Databases...", "active")

        # Provenance: triage blocks are machine-generated, not from an investigator
        # question. Stamp a clear source so each block's "From question" card reads
        # meaningfully instead of the raw "initialize_case_report" trigger token
        # (process_query set current_source_query to that token before delegating here).
        if getattr(self.cm, "report_engine", None) is not None:
            self.cm.report_engine.current_source_query = "Eye Automated Triage"

        primary_data_dir = os.path.join(self.cm.case_directory, "Target_Artifacts")
        
        # --- ENHANCED DATABASE RESOLVER ---
        def resolve_db(filename: str, required_table: str) -> Optional[str]:
            """Robustly resolve database file path and verify table existence."""
            # 1. Check primary data directory (Target_Artifacts) explicitly
            target_sub = os.path.join(primary_data_dir, filename)
            if os.path.exists(target_sub):
                self.cm.database_service.db_manager.disconnect(filename)
                self.cm.database_service.db_manager.resolved_paths[filename] = Path(target_sub)
                if self.cm.database_service.db_manager.table_exists(filename, required_table):
                    return filename

            # 2. Recursive search fallback from case root
            case_path = Path(self.cm.case_directory)
            for path in case_path.rglob(filename):
                try:
                    path_str = str(path.absolute())
                    conn = sqlite3.connect(path_str, timeout=1.0)
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (required_table,))
                    exists = cur.fetchone()
                    conn.close()
                    if exists:
                        self.cm.database_service.db_manager.disconnect(filename)
                        self.cm.database_service.db_manager.resolved_paths[filename] = path
                        return filename
                except Exception: continue
            return None

        # Resolve core data sources (Done before any query to prevent noise)
        reg_db = resolve_db("registry_data.db", "UserProfiles")
        pref_db = resolve_db("prefetch_data.db", "prefetch_data")
        mft_db = resolve_db("mft_usn_correlated_analysis.db", "mft_usn_correlated")
        log_db = resolve_db("Log_Claw.db", "SecurityLogs")
        bin_db = resolve_db("recyclebin_analysis.db", "recycle_bin_entries")
        am_db = resolve_db("amcache.db", "InventoryApplication")
        shim_db = resolve_db("shimcache.db", "shimcache_entries")
        srum_db = resolve_db("srum_data.db", "srum_application_usage")
        lnk_db = resolve_db("LnkDB.db", "LNK_Files")
        
        # Refresh discovery based on new paths
        self.cm.database_service.discover_databases()

        def safe_add_table(db, query, title, limit=30):
            """Helper to execute query and only add to report if data exists."""
            if not db: return False
            res = self.cm.database_service.execute_query(db, f"{query} LIMIT {limit}")
            
            # Fallback for schema mismatches (e.g. missing columns in older/newer collectors)
            if not res.get("success") and "no such column" in str(res.get("error", "")).lower():
                # Extract table name from query: "SELECT ... FROM TableName ..."
                table_match = re.search(r"FROM\s+[\"']?(\w+)[\"']?", query, re.IGNORECASE)
                if table_match:
                    table_name = table_match.group(1)
                    self.logger.warning(f"Schema mismatch for {table_name} in {db}. Falling back to SELECT *")
                    res = self.cm.database_service.execute_query(db, f"SELECT * FROM {table_name} LIMIT {limit}")
            
            if res.get("success") and res.get("data"):
                # Use compact spacing for triage tables to avoid 'collapsed' look
                self.cm.report_engine.add_data_table(query, list(res["data"][0].keys()), res["data"], title, compact_spacing=True)
                return True
            return False

        # --- 1. SYSTEM IDENTITY & CONFIGURATION ---
        emit_step("tool_call", "Profiling System Identity...", "active")
        sys_info_md = "### System Overview\n"
        
        # Hostname
        comp_name = "Unknown"
        if reg_db:
             name_res = self.cm.database_service.execute_query(reg_db, "SELECT * FROM ComputerNameInfo LIMIT 1")
             if name_res.get("success") and name_res.get("data"):
                  row = name_res["data"][0]
                  comp_name = row.get("computer_name") or row.get("hostname") or next(iter(row.values()), "Unknown")
        sys_info_md += f"- **Computer Name:** {comp_name}\n"
        
        # Users
        users = []
        if reg_db:
            users_res = self.cm.database_service.execute_query(reg_db, "SELECT * FROM UserProfiles")
            if users_res.get("success") and users_res.get("data"):
                for u in users_res["data"]:
                    val = u.get("username") or u.get("user") or u.get("Name")
                    if val: users.append(str(val))
        
        if users:
            sys_info_md += f"- **Identified Users:** {', '.join(users[:10])}{'...' if len(users) > 10 else ''}\n"
        
        # Timezone
        timezone = "N/A"
        if reg_db:
            tz_res = self.cm.database_service.execute_query(reg_db, "SELECT * FROM TimeZoneInfo LIMIT 1")
            if tz_res.get("success") and tz_res.get("data"):
                row = tz_res["data"][0]
                timezone = row.get("time_zone_name") or row.get("TimeZone") or "N/A"
        sys_info_md += f"- **Timezone Info:** {timezone}\n"

        self.cm.report_engine.append_section("System Identity", sys_info_md)

        # --- 2. SECURITY & AUTHENTICATION ---
        emit_step("tool_call", "Auditing Security Logs...", "active")
        s_count, f_count, a_count, e_count, r_count, v_count = 0, 0, 0, 0, 0, 0
        if log_db:
            # 4624: Success, 4625: Failure, 4672: Admin Logon, 4648: Explicit Credentials, 4776: Credential Validation
            s_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4624")
            f_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4625")
            a_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4672")
            e_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4648")
            v_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4776")
            
            # Detect Remote Desktop / Network logons (Logon Type 3 or 10 in description)
            r_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4624 AND (EventDescription LIKE '%Logon Type: 3%' OR EventDescription LIKE '%Logon Type: 10%')")
            
            s_count = s_res.get("data", [{}])[0].get("c", 0) if s_res.get("success") and s_res.get("data") else 0
            f_count = f_res.get("data", [{}])[0].get("c", 0) if f_res.get("success") and f_res.get("data") else 0
            a_count = a_res.get("data", [{}])[0].get("c", 0) if a_res.get("success") and a_res.get("data") else 0
            e_count = e_res.get("data", [{}])[0].get("c", 0) if e_res.get("success") and e_res.get("data") else 0
            v_count = v_res.get("data", [{}])[0].get("c", 0) if v_res.get("success") and v_res.get("data") else 0
            r_count = r_res.get("data", [{}])[0].get("c", 0) if r_res.get("success") and r_res.get("data") else 0
            
            if sum([s_count, f_count, a_count, e_count, r_count, v_count]) > 0:
                # Use a specific high-visibility forensic palette
                # Avoid index 0 if it's black/dark
                login_palette = self.cm.report_engine.color_manager.get_palette("forensic")
                # Ensure visibility: Success(Greenish), Failure(Reddish), Admin(Purple/Gold), Explicit(Cyan), Remote(Orange)
                self.cm.report_engine.add_chart(
                    "Authentication Patterns",
                    ["Success (4624)", "Failure (4625)", "Admin Logon (4672)", "Explicit Creds (4648)", "Remote Access (RDP/Net)"],
                    [{"label": "Events", "data": [s_count, f_count, a_count, e_count, r_count], 
                      "backgroundColor": ["#4CAF50", "#F44336", "#FFD700", "#00BCD4", "#FF9800"]}],
                    "bar"
                )
                
                # Table with detailed remote connections
                remote_query = "SELECT EventTimestampUTC, EventID, User, ComputerName, EventDescription FROM SecurityLogs WHERE EventID=4624 AND (EventDescription LIKE '%Logon Type: 3%' OR EventDescription LIKE '%Logon Type: 10%') ORDER BY EventTimestampUTC DESC"
                safe_add_table(log_db, remote_query, "Remote Access & Network Logons (Type 3/10)")
                
                # --- ENHANCED 4648 PARSING ---
                if e_count > 0:
                    emit_step("tool_call", "Extracting Explicit Credential Details...", "active")
                    e_res = self.cm.database_service.execute_query(log_db, "SELECT EventTimestampUTC, User, Keywords FROM SecurityLogs WHERE EventID=4648 ORDER BY EventTimestampUTC DESC LIMIT 10")
                    if e_res.get("success") and e_res.get("data"):
                        parsed_4648 = []
                        for row in e_res["data"]:
                            k = row.get("Keywords", "")
                            parts = k.split(",")
                            # Field Map: 5:TargetUser, 6:TargetDomain, 8:TargetServer, 11:ProcessName
                            target_user = parts[5] if len(parts) > 5 else "N/A"
                            target_server = parts[8] if len(parts) > 8 else "N/A"
                            process = parts[11] if len(parts) > 11 else "N/A"
                            
                            parsed_4648.append({
                                "Timestamp": row["EventTimestampUTC"],
                                "Subject (Who)": row["User"],
                                "Used Credential": target_user,
                                "Target Server": target_server,
                                "Via Process": process
                            })
                        
                        if parsed_4648:
                            self.cm.report_engine.add_data_table("Internal 4648 Details", list(parsed_4648[0].keys()), parsed_4648, "Explicit Credential Logons (EID 4648 Details)")

                # High-priority security list - enriched with Keywords for better parsing
                safe_add_table(log_db, "SELECT EventTimestampUTC, EventID, User, ComputerName, Keywords, EventDescription FROM SecurityLogs WHERE EventID IN (4624, 4625, 4672, 4648, 4776, 4719, 1102) ORDER BY EventTimestampUTC DESC", "High-Priority Security & Authentication Events")

        # --- 3. EXECUTION INTELLIGENCE ---
        emit_step("tool_call", "Mapping Execution Artifacts...", "active")
        
        # Top Apps (Prefetch)
        if pref_db:
            app_res = self.cm.database_service.execute_query(pref_db, "SELECT executable_name, run_count FROM prefetch_data ORDER BY CAST(run_count AS INTEGER) DESC LIMIT 5")
            if app_res.get("success") and app_res.get("data"):
                forensic_palette = self.cm.report_engine.color_manager.get_palette("forensic")
                self.cm.report_engine.add_chart(
                    "Top 5 Applications (Prefetch)",
                    [a["executable_name"] for a in app_res["data"]],
                    [{"label": "Run Count", "data": [int(a["run_count"]) for a in app_res["data"]], "backgroundColor": forensic_palette}],
                    "pie"
                )
        
        safe_add_table(pref_db, "SELECT executable_name, run_count, last_executed, (SELECT source_path FROM prefetch_data pd2 WHERE pd2.executable_name = prefetch_data.executable_name LIMIT 1) as full_path FROM prefetch_data ORDER BY last_executed DESC", "Recent Prefetch Executions (App Names & Paths)")
        safe_add_table(am_db, "SELECT name, version, publisher, install_date, path FROM InventoryApplication ORDER BY install_date DESC", "Amcache: Installed Applications & Binary Paths")
        
        # SRUM (Long-term activity)
        if srum_db:
             emit_step("tool_call", "Processing SRUM Resource Intelligence...", "active")
             
             # 1. Network Usage Aggregation
             net_res = self.cm.database_service.execute_query(srum_db, "SELECT app_name, bytes_sent, bytes_received, timestamp FROM srum_network_data_usage")
             if net_res.get("success") and net_res.get("data"):
                 def parse_bytes(val):
                     """Convert various SRUM byte strings/ints to raw bytes."""
                     if not val: return 0
                     if isinstance(val, (int, float)): return float(val)
                     v = str(val).lower().strip()
                     try:
                         parts = v.split()
                         num = float(parts[0])
                         if len(parts) > 1:
                             unit = parts[1]
                             if "tb" in unit: return num * 1024**4
                             if "gb" in unit: return num * 1024**3
                             if "mb" in unit: return num * 1024**2
                             if "kb" in unit: return num * 1024
                         return num
                     except: return 0

                 def format_bytes(b):
                     """Convert bytes to human-readable string (e.g., 1.2 GB)."""
                     if b <= 0: return "0 B"
                     for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                         if b < 1024:
                             return f"{round(b, 2)} {unit}"
                         b /= 1024
                     return f"{round(b, 2)} PB"

                 net_stats = {}
                 for row in net_res["data"]:
                     app = row["app_name"] or "Unknown"
                     total = parse_bytes(row["bytes_sent"]) + parse_bytes(row["bytes_received"])
                     ts = row["timestamp"]
                     if app not in net_stats: net_stats[app] = {"total": 0, "first": ts, "last": ts}
                     net_stats[app]["total"] += total
                     if ts < net_stats[app]["first"]: net_stats[app]["first"] = ts
                     if ts > net_stats[app]["last"]: net_stats[app]["last"] = ts
                 
                 sorted_net = sorted(net_stats.items(), key=lambda x: x[1]["total"], reverse=True)[:10]
                 if sorted_net:
                     # Chart labels (Top 5)
                     chart_labels = [x[0] for x in sorted_net[:5]]
                     chart_data = [round(x[1]["total"] / (1024*1024), 2) for x in sorted_net[:5]] # Keep MB for charts to have consistent scale
                     
                     self.cm.report_engine.add_chart(
                         "Top Apps: Network Data Usage",
                         chart_labels,
                         [{"label": "Total MB", "data": chart_data, "backgroundColor": "#2196F3"}],
                         "bar"
                     )
                     
                     # Table data (Readable format)
                     table_data = [{
                         "App Name": k, 
                         "Total Data": format_bytes(v["total"]), 
                         "First Active": v["first"], 
                         "Last Active": v["last"]
                     } for k, v in sorted_net]
                     
                     self.cm.report_engine.add_data_table("Network Activity Ranges", ["App Name", "Total Data", "First Active", "Last Active"], table_data, "App Network Usage & Time Ranges")

             # 2. CPU Cycle / Energy Usage Aggregation
             cpu_res = self.cm.database_service.execute_query(srum_db, "SELECT app_name, foreground_cycle_time, timestamp FROM srum_application_usage")
             if cpu_res.get("success") and cpu_res.get("data"):
                 def parse_time(val):
                     """Convert SRUM time strings/ints to raw seconds."""
                     if not val: return 0
                     if isinstance(val, (int, float)): return float(val)
                     v = str(val).lower().strip()
                     try:
                         parts = v.split()
                         num = float(parts[0])
                         if len(parts) > 1:
                             unit = parts[1]
                             if "hour" in unit or "hr" in unit: return num * 3600
                             if "min" in unit: return num * 60
                         return num # seconds
                     except: return 0

                 def format_duration(seconds):
                     """Convert seconds to human-readable duration (e.g., 2h 15m)."""
                     if seconds <= 0: return "0s"
                     
                     days = int(seconds // 86400)
                     hours = int((seconds % 86400) // 3600)
                     minutes = int((seconds % 3600) // 60)
                     secs = int(seconds % 60)
                     
                     parts = []
                     if days > 0: parts.append(f"{days}d")
                     if hours > 0: parts.append(f"{hours}h")
                     if minutes > 0: parts.append(f"{minutes}m")
                     if secs > 0 or not parts: parts.append(f"{secs}s")
                     
                     return " ".join(parts[:2]) # Keep it concise
                 
                 cpu_stats = {}
                 for row in cpu_res["data"]:
                     app = row["app_name"] or "Unknown"
                     seconds = parse_time(row["foreground_cycle_time"])
                     ts = row["timestamp"]
                     if app not in cpu_stats: cpu_stats[app] = {"total_sec": 0, "first": ts, "last": ts}
                     cpu_stats[app]["total_sec"] += seconds
                     if ts < cpu_stats[app]["first"]: cpu_stats[app]["first"] = ts
                     if ts > cpu_stats[app]["last"]: cpu_stats[app]["last"] = ts
                 
                 sorted_cpu = sorted(cpu_stats.items(), key=lambda x: x[1]["total_sec"], reverse=True)[:10]
                 if sorted_cpu:
                     # Chart labels (Top 5)
                     chart_labels = [x[0][:30] + "..." if len(x[0]) > 30 else x[0] for x in sorted_cpu[:5]]
                     chart_data = [round(x[1]["total_sec"] / 60, 2) for x in sorted_cpu[:5]] # Minutes for chart
                     
                     self.cm.report_engine.add_chart(
                         "Top Apps: CPU Cycle Time (Energy Proxy)",
                         chart_labels,
                         [{"label": "Active Minutes", "data": chart_data, "backgroundColor": "#FFC107"}],
                         "bar"
                     )

                     # Table data (Readable format)
                     table_data = [{
                         "App Name": k, 
                         "Total CPU Time": format_duration(v["total_sec"]), 
                         "First Active": v["first"], 
                         "Last Active": v["last"]
                     } for k, v in sorted_cpu]

                     self.cm.report_engine.add_data_table("CPU Activity Ranges", ["App Name", "Total CPU Time", "First Active", "Last Active"], table_data, "App CPU Usage & Time Ranges")
                     

        # --- 4. PERSISTENCE & REMOTE CONTROL ---
        emit_step("tool_call", "Scanning Persistence & Remote Access Protocols...", "active")
        
        # Remote Control Software Detection
        remote_sw = []
        if reg_db and self.cm.database_service.db_manager.table_exists(reg_db, "SystemServices"):
            # Manual expansion of conditions for SQLite
            svc_conditions = " OR ".join([f"service_name LIKE '%{k}%' OR display_name LIKE '%{k}%'" for k in ['teamviewer', 'anydesk', 'vnc', 'rdp', 'ssh', 'winrm']])
            svc_res = self.cm.database_service.execute_query(reg_db, f"SELECT display_name, service_name, status FROM SystemServices WHERE {svc_conditions}")
            if svc_res.get("success") and svc_res.get("data"):
                remote_sw.extend([{"Type": "Service", "Name": r["display_name"], "Details": r["service_name"], "Status": r["status"]} for r in svc_res["data"]])
                
            # Search Run keys
            run_conditions = " OR ".join([f"name LIKE '%{k}%' OR row_data LIKE '%{k}%'" for k in ['teamviewer', 'anydesk', 'vnc', 'rdp', 'ssh']])
            run_res = self.cm.database_service.execute_query(reg_db, f"SELECT name, row_data FROM machine_run WHERE {run_conditions} UNION SELECT name, row_data FROM user_run WHERE {run_conditions}")
            if run_res.get("success") and run_res.get("data"):
                remote_sw.extend([{"Type": "Startup", "Name": r["name"], "Details": r["row_data"][:100], "Status": "Enabled"} for r in run_res["data"]])

        if remote_sw:
             self.cm.report_engine.add_data_table("Internal Protocol List", ["Type", "Name", "Details", "Status"], remote_sw, "Detected Remote Control & Communication Protocols")

        if reg_db:
            safe_add_table(reg_db, "SELECT name, row_data as data, type, key_path FROM machine_run UNION SELECT name, row_data as data, type, key_path FROM user_run", "Active Persistence Keys (Run/RunOnce)")
            safe_add_table(reg_db, "SELECT display_name, service_name, status, image_path, start_type FROM SystemServices WHERE start_type IN (2, 3)", "Critical System Services (Auto & Manual Start)")

        # --- 5. USER ACTIVITY & INTENT ---
        emit_step("tool_call", "Analyzing User Intent...", "active")
        if reg_db:
            safe_add_table(reg_db, "SELECT command, access_date FROM RunMRU ORDER BY access_date DESC", "Recent Win+R Commands (RunMRU)")
            safe_add_table(reg_db, "SELECT name as filename, data as folder FROM RecentDocs ORDER BY data DESC", "Recently Accessed Documents (RecentDocs)")
            safe_add_table(reg_db, "SELECT url, title, visit_count, last_visit FROM BrowserHistory ORDER BY last_visit DESC", "Extracted Browser History")
        
        # LNK & JumpLists
        if lnk_db:
             safe_add_table(lnk_db, "SELECT Source_Name, Local_Path, Working_Directory, Time_Access FROM LNK_Files ORDER BY Time_Access DESC", "Recent LNK File Access")
             safe_add_table(lnk_db, "SELECT AppID, Local_Path, Time_Access FROM Automatic_JumpLists ORDER BY Time_Access DESC", "Recent JumpList Entries")

        # --- 6. HARDWARE & NETWORK ---
        emit_step("tool_call", "Mapping Hardware & Network History...", "active")
        
        # Enhanced USB Triage
        if reg_db:
            usb_query = "SELECT friendly_name, manufacturer, last_connected, device_id FROM USBDevices ORDER BY last_connected DESC"
            usb_res = self.cm.database_service.execute_query(reg_db, usb_query)
            if usb_res.get("success") and usb_res.get("data"):
                 self.cm.report_engine.add_data_table(usb_query, ["friendly_name", "manufacturer", "last_connected", "device_id"], usb_res["data"], "Comprehensive USB Hardware History")

        # Enhanced Network Triage (Pivoted & Merged Profiles)
        net_data = []
        if reg_db and self.cm.database_service.db_manager.table_exists(reg_db, "Network_list"):
             net_raw = self.cm.database_service.execute_query(reg_db, "SELECT subkey, name, data FROM Network_list")
             if net_raw.get("success") and net_raw.get("data"):
                 profiles = {}
                 for row in net_raw["data"]:
                     sk = row["subkey"]
                     if sk not in profiles: profiles[sk] = {"ProfileID": sk}
                     profiles[sk][row["name"]] = row["data"]
                 
                 merged_networks = {}
                 for sk, p in profiles.items():
                     ssid = p.get("ProfileName") or p.get("Description") or p.get("network_name", "Unknown")
                     created = p.get("DateCreated", "N/A")
                     last = p.get("DateLastConnected", "N/A")
                     mac = p.get("DefaultGatewayMac", "N/A")
                     
                     if ssid not in merged_networks:
                         merged_networks[ssid] = {"SSID": ssid, "Created": created, "LastConnected": last, "GatewayMAC": mac}
                     else:
                         if last != "N/A" and (merged_networks[ssid]["LastConnected"] == "N/A" or last > merged_networks[ssid]["LastConnected"]):
                             merged_networks[ssid]["LastConnected"] = last
                             merged_networks[ssid]["GatewayMAC"] = mac
                 
                 net_data = list(merged_networks.values())
                 net_data.sort(key=lambda x: (x["LastConnected"] == "N/A", x["LastConnected"]), reverse=True)
                 if net_data:
                     self.cm.report_engine.add_data_table("Merged Network Profiles", ["SSID", "Created", "LastConnected", "GatewayMAC"], net_data, "Network Connectivity Profiles (Merged)")

        # --- 7. FILE SYSTEM PULSE ---
        emit_step("tool_call", "Analyzing File Lifecycle...", "active")
        safe_add_table(mft_db, "SELECT fn_filename, si_modification_time, mft_flags, reconstructed_path FROM mft_usn_correlated ORDER BY si_modification_time DESC", "10 Most Recent File Modifications (MFT/USN)")
        safe_add_table(bin_db, "SELECT original_filename, original_path, deletion_time FROM recycle_bin_entries ORDER BY deletion_time DESC", "Recently Deleted Files (Recycle Bin)")

        # --- FINAL SYNTHESIS ---
        emit_step("synthesis", "Finalizing Comprehensive Triage Report...", "active")
        
        # Safe counts for summary
        total_auth = (s_count or 0) + (f_count or 0) + (a_count or 0) + (e_count or 0) + (v_count or 0)
        user_count = len(users)
        usb_count = 0
        if reg_db and self.cm.database_service.db_manager.table_exists(reg_db, "USBDevices"):
             u_count_res = self.cm.database_service.execute_query(reg_db, "SELECT COUNT(*) as c FROM USBDevices")
             usb_count = u_count_res.get("data", [{}])[0].get("c", 0) if u_count_res.get("success") and u_count_res.get("data") else 0

        # Refactor Summary into a real TableBlock for professional 'Uncollapsed' look
        summary_data = [
            {"Category": "Identity", "Finding": f"Found {user_count} user profiles and system metadata."},
            {"Category": "Security", "Finding": f"Audited {total_auth} security events; detected {r_count} remote access attempts."},
            {"Category": "Execution", "Finding": "Aggregated Prefetch, Amcache, and SRUM (Top apps mapped)."},
            {"Category": "Persistence", "Finding": f"Scanned Run keys and {len(remote_sw)} remote protocols identified."},
            {"Category": "User Intent", "Finding": "RecentDocs, RunMRU, and LNK/JumpList activity indexed."},
            {"Category": "Hardware", "Finding": f"Found {usb_count} USB devices and {len(net_data)} network profiles."},
            {"Category": "FileSystem", "Finding": "Correlated MFT/USN Journal for recent pulse."}
        ]
        
        self.cm.report_engine.add_data_table(
            "Triage Summary Table",
            ["Category", "Finding"],
            summary_data,
            "Triage Executive Summary Dashboard",
            column_widths={"Category": "25%", "Finding": "75%"},
            category="Automated Triage",
        )

        # Immediate Observations as a TextBlock
        observations_md = f"""
### Immediate Technical Observations
- **System Owner**: {comp_name}
- **Active Users**: {', '.join(users[:5])}{'...' if len(users) > 5 else ''}
- **Remote Protocols**: {', '.join([s['Name'] for s in remote_sw[:3]]) if remote_sw else 'None detected'}

*This report follows the Ghassan Elsman Protocol (GEP) for automated forensic triage.*
"""
        self.cm.report_engine.append_section(
            "Immediate Technical Observations",
            observations_md,
            category="Automated Triage",
        )

        # --- IMPORTED EVIDENCE (external data) + cross-reference with native artifacts ---
        # Present only when the investigator imported external evidence. Index a sample of
        # each imported table, then run the deterministic identity/time correlation so the
        # case-open report proactively states whether imports connect to native artifacts.
        try:
            imported_dbs = [d for d in self.cm.database_service.discover_databases()
                            if d.get("category") == "Imported Evidence" and d.get("accessible")]
        except Exception:
            imported_dbs = []
        imported_db_names = [d.get("name") for d in imported_dbs]
        if imported_dbs:
            emit_step("tool_call", "Indexing Imported Evidence & cross-referencing...", "active")
            for _d in imported_dbs:
                for _t in (_d.get("tables") or []):
                    safe_add_table(_d.get("name"), f'SELECT * FROM "{_t}"',
                                   f"Imported Evidence — {_d.get('name')} · {_t}", limit=15)
            try:
                _corr = self.cm.forensic_handlers.correlate_imported_evidence_core(max_values=25)
            except Exception as _e:
                _corr = {"success": False, "error": str(_e)}
            if _corr.get("success"):
                _lines = [f"**{_corr.get('summary', '')}**", ""]
                for _m in (_corr.get("identity_matches") or [])[:15]:
                    _hits = ", ".join(f"`{h['database']}:{h['table']}:{h['row_id']}`"
                                      for h in _m.get("native_hits", [])[:3])
                    _lines.append(f"- `{_m['value']}` (from {_m['imported_source']}) → {_hits}")
                if _corr.get("note"):
                    _lines += ["", _corr["note"]]
                self.cm.report_engine.append_section(
                    "Imported Evidence Correlation", "\n".join(_lines), category="Automated Triage")

        self.cm.report_engine.save_report()
        
        # Log this triage as a milestone in the Case Summary
        self.cm.case_context_manager.log_investigation_step(
            query="Initialize Case Triage",
            response_summary=f"Completed automated triage for {comp_name}. Indexed users, auth events, and execution artifacts.",
            evidence_found=True,
            suggested_next_steps="Review the Triage Report and investigate detected remote access events.",
            artifacts_queried=["Registry", "SecurityLogs", "Prefetch", "Amcache", "SRUM", "MFT"],
            query_type="triage"
        )
        
        # Final Sync to GUI
        check_report_sync(initial_report_state)

        emit_step("synthesis", "Forensic Triage Complete.", "done")

        response = f"Automated Forensic Triage for **{comp_name}** is complete.\n\n" \
                  f"I have successfully indexed findings across 7 forensic categories into the Living Report. " \
                  f"No AI resources were consumed for this initial extraction pass.\n\n" \
                  f"**Ready for investigation.** What would you like to analyze first?"

        # Per-step GEP compliance: the triage is the most evidence-heavy step, so it
        # must also leave a record in the compliance trail (Compliance panel). Grade
        # the deterministic triage against the 10 principles and persist. Best-effort
        # — a compliance-logging error must never break the triage.
        try:
            _consulted = [d for d in (reg_db, pref_db, mft_db, log_db, bin_db,
                                      am_db, shim_db, srum_db, lnk_db) if d]
            _consulted += imported_db_names  # imported evidence was swept above
            _expected = ["registry_data.db", "prefetch_data.db",
                         "mft_usn_correlated_analysis.db", "Log_Claw.db",
                         "recyclebin_analysis.db", "amcache.db", "shimcache.db",
                         "srum_data.db", "LnkDB.db"] + imported_db_names
            _blocks_added = (self.cm.report_engine.get_report_json()["metadata"]["block_count"]
                             - initial_report_state["metadata"]["block_count"])
            gep_triage = self._evaluate_gep_triage(_consulted, _expected, _blocks_added, response)
            self._persist_gep_turn(gep_triage)
        except Exception as e:
            self.logger.debug(f"GEP triage evaluation skipped: {e}")

        # Surface the triage's overview onto the Narrative Map as floating GLOBAL
        # cards (System Identity + Technical Observations) — they sit unconnected in
        # the left zone until the investigator/Eye links them. Stable card_ids so a
        # re-triage updates the same cards. Best-effort; never breaks the triage.
        try:
            nms = getattr(self.cm, "narrative_map_service", None)
            if nms is not None:
                nms.upsert_global("system identity", "System Identity",
                                  (sys_info_md or "").strip(), card_id="g_sys_identity")
                nms.upsert_global("technical observation", "Immediate Technical Observations",
                                  (observations_md or "").strip(), card_id="g_tech_obs")
                # These are floating GLOBAL cards — drop any verdict-linked narrative copy
                # the map seed (build_evidence_map) may have created from the same report
                # blocks, so they don't appear twice.
                nms.remove_narratives_by_title(
                    ["System Identity", "Immediate Technical Observations", "Technical Observations"])
        except Exception as e:
            self.logger.debug(f"Narrative-map global cards skipped: {e}")

        self.cm.history_manager.add_message("assistant", response)
        
        return {
            "response": response,
            "action_chips": [
                {"id": "triage_ai", "label": "Ask AI to Analyze Findings", "query": "Based on the triage report, identify any suspicious execution patterns or unauthorized persistence.", "icon": "brain"},
                {"id": "timeline_view", "label": "View Master Timeline", "query": "Generate a chronological timeline of the most significant security and execution events.", "icon": "history"}
            ],
            "metadata": {
                "protocol": "Ghassan Elsman Protocol (GEP)",
                "pillar": 0,
                "pillar_name": "Case Awareness (The Triage)"
            },
            "error": None,
            "context_stats": self.cm.get_context_stats()
        }

    def process_query(
        self,
        user_query: str,
        status_callback: Optional[Callable[[str], None]] = None,
        hitl_callback: Optional[Callable] = None,
        report_callback: Optional[Callable[[str], None]] = None,
        dialogue_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the full forensic pipeline.
        """
        self.cm.last_user_query = user_query
        # Stamp the originating question on the report engine so every block
        # created during this query inherits its provenance (see _stamp_and_append).
        if getattr(self.cm, "report_engine", None) is not None:
            self.cm.report_engine.current_source_query = user_query
        import uuid
        step_counter = [0]
        # Pre-bound so the guarded_generate closure can always read it (the
        # analyze_case_context branch calls the model before the main loop's
        # own initialization). The regular path rebinds this list.
        all_tool_results = []
        tool_truncations = []
        # High-water mark: how many tool_truncations have already been folded into
        # a seal. Each tool-output cap is sealed exactly once (in the first seal
        # after it occurred) instead of being re-attached to every subsequent
        # per-iteration seal in this turn.
        tool_trunc_hwm = [0]

        # Eye <-> LLM conversation transcript. Captured per turn (full prompts,
        # the model's reasoning, the tool calls it requested + their results)
        # so the investigator can watch the Eye think live and review the
        # exchange afterward. Streamed via dialogue_callback; also returned.
        conversation: List[Dict[str, Any]] = []
        dialogue_counter = [0]

        def emit_dialogue(entry: Dict[str, Any]) -> None:
            """Record one Eye<->LLM exchange entry and stream it to the UI."""
            dialogue_counter[0] += 1
            entry = dict(entry)
            entry["seq"] = dialogue_counter[0]
            entry["timestamp"] = datetime.now().isoformat()
            conversation.append(entry)
            if dialogue_callback:
                try:
                    dialogue_callback(json.dumps(entry, ensure_ascii=False, default=str))
                except Exception as dlg_exc:
                    self.logger.debug(f"dialogue_callback failed: {dlg_exc}")
            # Persist so the full Eye<->LLM exchange (prompts, reasoning, tool
            # calls + results) is reviewable later in the Compliance panel.
            try:
                self._persist_dialogue(entry, user_query)
            except Exception as persist_exc:
                self.logger.debug(f"Dialogue persistence skipped: {persist_exc}")

        def emit_step(step_type: str, label: str, status: str,
                      tool: Optional[str] = None,
                      params: Optional[Dict] = None,
                      detail: Optional[str] = None) -> str:
            """
            Internal helper to notify the UI about a pipeline milestone.
            """
            step_counter[0] += 1
            step = {
                "step_id": f"s{step_counter[0]}",
                "type": step_type,          # "thinking" | "rag" | "tool_call" | "synthesis"
                "label": label,
                "status": status,           # "active" | "done" | "error"
                "timestamp": datetime.now().isoformat()
            }
            if tool:
                step["tool"] = tool
            if params:
                # Truncate large param values to prevent UI bloat
                step["params"] = {
                    k: (str(v)[:120] + "...") if len(str(v)) > 120 else v
                    for k, v in params.items()
                }
            if detail:
                step["detail"] = detail
            if status_callback:
                status_callback(json.dumps(step))
            # Persist the step so the Compliance panel can show a per-step
            # execution history (grouped by step, one entry per run) with
            # timestamps. Logging must never break the investigation pipeline.
            try:
                self._persist_step(step, user_query)
            except Exception as persist_exc:
                self.logger.debug(f"Step persistence skipped: {persist_exc}")
            return step["step_id"]

        # Chain-of-custody seal for every payload sent to the model this turn.
        # Single persistent writer owned by the ContextManager (one writer per
        # case dir — see ContextManager.__init__) so the hash chain isn't forked
        # or re-read from disk every turn.
        evidence_seal = self.cm.evidence_seal

        def audit_rag_trunc(rag_context, iteration):
            """If RAGService trimmed the knowledge context to fit its budget,
            surface it (step + chain-of-custody audit) instead of letting it be
            silently dropped. RAG knowledge is non-evidence, so this is a
            visibility measure, not an evidence-integrity block."""
            if not rag_context or "RAG Context Truncated" not in rag_context:
                return
            emit_step("rag", "RAG knowledge trimmed to fit its token budget", "error")
            try:
                if getattr(self.cm, "truncation_auditor", None):
                    self.cm.truncation_auditor.log_event(
                        action="TRUNCATED",
                        message_id=f"rag-{iteration}",
                        token_count=self.cm.token_counter.count_tokens(rag_context),
                        reason="rag_context_budget",
                        message_hash=EvidenceSeal._sha256(rag_context),
                        metadata={"iteration": iteration},
                    )
            except Exception:
                pass

        def guarded_generate(system_prompt, user_message, history, tools, *, phase, iteration):
            """Single choke point for every LLM call:
            (1) SELF-HEAL: if the assembled payload exceeds the model's context
                window, automatically shrink it — summarize, then drop — but ONLY
                non-evidence context (never pinned / evidence / tool-result
                messages), logging every reduction. The persistent on-disk
                history is untouched; only this outgoing payload is slimmed.
            (2) FAIL HARD: refuse only when the irreducible evidence core still
                overflows — evidence is never silently dropped.
            (3) SEAL the exact payload sent (hash + provenance) for chain of
                custody, then call the model with one transient-error retry.
            """
            tc = self.cm.token_counter
            try:
                tools_str = json.dumps(tools, default=str) if tools else ""
            except Exception:
                tools_str = str(tools)
            max_ctx = int(getattr(self.cm, "max_total_tokens", 8192) or 8192)
            # Output reserve: 10% (min 512), but never more than half the window
            # so a tiny configured context can't drive `usable` to <= 0. This is
            # the SAME formula as ContextManager.usable_context_tokens() (which
            # HistoryManager.manage_history uses), so the per-call gate and the
            # persistent-history compaction agree on the same window.
            reserve = min(max(512, int(max_ctx * 0.1)), max(1, max_ctx // 2))
            usable = max_ctx - reserve

            base_tokens = tc.count_tokens(system_prompt or "") + tc.count_tokens(user_message or "") + tc.count_tokens(tools_str)

            def payload_tokens(hist):
                return base_tokens + sum(tc.count_tokens(m.get("content") or "") for m in (hist or []))

            working = list(history or [])
            healed = False
            cut_details = []

            # ---- SELF-HEAL: two-stage memory policy (summary buffer → slide) ----
            # Shared with HistoryManager.manage_history via
            # reduce_messages_to_budget, but here Stage 2 (the hard sliding-window
            # drop) is ENABLED so the OUTGOING payload is forced to fit. The
            # persistent on-disk history is untouched; only this copy is slimmed.
            # archive_cb=None: evicted turns are archived exactly once, by the
            # persistent path (manage_history), never here.
            if payload_tokens(working) > usable:
                _rc = getattr(self.cm, "reasoning_config", None)
                _rc = _rc if isinstance(_rc, dict) else {}
                _window_turns = int(_rc.get("history_window_turns", 5))
                _enable_buf = bool(_rc.get("enable_summary_buffer", True))

                working, cut_records, _summary_msg = reduce_messages_to_budget(
                    working, usable,
                    token_count_fn=tc.count_tokens,
                    base_tokens=base_tokens,
                    window_turns=_window_turns,
                    summarize_fn=self.cm.history_manager._summarize_chunk,
                    enable_summary_buffer=_enable_buf,
                    enable_drop=True,
                    keep_first=True,
                    archive_cb=None,
                )
                if cut_records:
                    healed = True

                _summarized = [c for c in cut_records if c["action"] == "SUMMARIZED"]
                _dropped = [c for c in cut_records if c["action"] == "TRUNCATED"]
                _summary_text = next((c["summary_text"] for c in _summarized if c.get("summary_text")), "")

                # Per-message seal cut details (same shapes the seal expects).
                for c in cut_records:
                    m = c["msg"]
                    msg_content = m.get("content") or ""
                    cut_details.append(evidence_seal.build_cut_detail(
                        action=c["action"],
                        message_id=m.get("id"),
                        role=m.get("role"),
                        original_text=msg_content,
                        processed_text=(c["summary_text"] or "") if c["action"] == "SUMMARIZED" else "",
                        dropped_text=msg_content,
                        token_count=tc.count_tokens(msg_content),
                    ))

                if _summarized:
                    emit_step("thinking", f"Self-healing: summarized {len(_summarized)} old non-evidence message(s) to fit context", "active")
                    if getattr(self.cm, "truncation_auditor", None):
                        aggregate_dropped = "\n".join(c["msg"].get("content", "") for c in _summarized)
                        _sum_tokens = sum(tc.count_tokens(c["msg"].get("content") or "") for c in _summarized)
                        agg_detail = evidence_seal.build_cut_detail(
                            action="SUMMARIZED",
                            message_id=f"selfheal-{phase}-{iteration}",
                            role="system",
                            original_text=aggregate_dropped,
                            processed_text=_summary_text,
                            dropped_text=aggregate_dropped,
                            token_count=_sum_tokens,
                        )
                        self.cm.truncation_auditor.log_event(
                            action="SUMMARIZED",
                            message_id=f"selfheal-{phase}-{iteration}",
                            token_count=_sum_tokens,
                            reason="self_heal_context_fit",
                            message_hash=EvidenceSeal._sha256(_summary_text),
                            metadata={"summarized_count": len(_summarized), "phase": phase, **agg_detail},
                        )

                if _dropped:
                    if getattr(self.cm, "truncation_auditor", None):
                        for c in _dropped:
                            removed = c["msg"]
                            removed_content = removed.get("content") or ""
                            try:
                                self.cm.truncation_auditor.log_event(
                                    action="TRUNCATED",
                                    message_id=removed.get("id", f"selfheal-drop-{phase}-{iteration}"),
                                    token_count=tc.count_tokens(removed_content),
                                    reason="self_heal_context_fit",
                                    message_hash=EvidenceSeal._sha256(removed_content),
                                    metadata={"phase": phase, **evidence_seal.build_cut_detail(
                                        action="TRUNCATED",
                                        message_id=removed.get("id"),
                                        role=removed.get("role"),
                                        original_text=removed_content,
                                        processed_text="",
                                        dropped_text=removed_content,
                                        token_count=tc.count_tokens(removed_content),
                                    )},
                                )
                            except Exception:
                                pass
                    emit_step("thinking", f"Self-healing: dropped {len(_dropped)} oldest non-evidence message(s) to fit context", "active")

            final_tokens = payload_tokens(working)

            # Built once here so the success path and the refusal path below seal
            # the EXACT same payload representation.
            model_name = self.cm.model_router.config.get("model_name", "LLM")

            def _build_full_payload():
                return (
                    f"<<SYSTEM>>\n{system_prompt}\n<<HISTORY>>\n"
                    + "\n".join(f"{m.get('role')}: {m.get('content')}" for m in working)
                    + f"\n<<USER>>\n{user_message}\n<<TOOLS>>\n{tools_str}"
                )

            def _seal_exact_payload(*, token_count, phase_label, sent_to_model):
                """Seal one exact payload + its self-heal cut details and advance
                the tool-truncation high-water mark. Best-effort: a write failure
                is recorded as a visible SEAL_FAILED marker, never swallowed.

                Used for BOTH payloads the model sees (sent_to_model=True) and
                refused over-limit payloads (sent_to_model=False) so the chain of
                custody records refusals and the cuts that occurred before them —
                not only what was actually sent.
                """
                full_payload = _build_full_payload()
                try:
                    # tool_truncations is bound in the enclosing process_query scope.
                    # Fold in only the tool-output caps not yet sealed, so each is
                    # recorded exactly once across this turn's per-iteration seals.
                    combined_cut_details = list(cut_details)
                    combined_cut_details.extend(tool_truncations[tool_trunc_hwm[0]:])
                    evidence_seal.seal(
                        full_payload,
                        phase=phase_label, iteration=iteration, query=user_query,
                        model=model_name, max_context=max_ctx, token_count=token_count,
                        evidence_refs=EvidenceSeal.extract_evidence_refs(all_tool_results),
                        truncated=healed or not sent_to_model,
                        cut_details=combined_cut_details,
                        sent_to_model=sent_to_model,
                        # A refusal is exceptional evidence — always persist the
                        # original message, even if routine full-payload storage is off.
                        force_full_payload=not sent_to_model,
                    )
                    # Advance only after a successful seal so a failed write doesn't
                    # silently drop these truncations from the record.
                    tool_trunc_hwm[0] = len(tool_truncations)
                except Exception as seal_exc:
                    # A skipped seal is a chain-of-custody gap — never swallow it
                    # silently. Record a tamper-evident marker and surface an error
                    # step so the gap is itself provable.
                    self.logger.error(f"Evidence seal FAILED for {phase_label} iter {iteration}: {seal_exc}", exc_info=True)
                    try:
                        if getattr(self.cm, "truncation_auditor", None):
                            self.cm.truncation_auditor.log_event(
                                action="SEAL_FAILED",
                                message_id=f"seal-{phase_label}-{iteration}",
                                token_count=token_count,
                                reason="evidence_seal_write_error",
                                message_hash=EvidenceSeal._sha256(full_payload),
                                metadata={"phase": phase_label, "error": str(seal_exc)},
                            )
                    except Exception:
                        pass
                    emit_step(
                        "thinking",
                        "Evidence seal could not be written — chain-of-custody gap recorded in audit trail",
                        "error",
                        detail=str(seal_exc),
                    )

            # ---- FAIL HARD: irreducible evidence core still overflows ----
            if final_tokens > usable:
                # Bounded preview of the ORIGINAL message we refused, so Context
                # Events shows what was refused (full bytes live in the seal sidecar).
                _refused_payload = _build_full_payload()
                _refused_preview = _refused_payload[:4000]
                try:
                    if getattr(self.cm, "truncation_auditor", None):
                        self.cm.truncation_auditor.log_event(
                            action="REFUSED_OVERFLOW",
                            message_id=f"turn-{iteration}",
                            token_count=final_tokens,
                            reason="evidence_core_exceeds_context_after_self_heal",
                            message_hash=EvidenceSeal._sha256(_refused_payload),
                            metadata={
                                "max_context": max_ctx, "reserve": reserve, "phase": phase,
                                "self_healed": healed,
                                # The original message (bounded) + its hash for full recovery.
                                "cut_content": _refused_preview,
                                "payload_sha256": EvidenceSeal._sha256(_refused_payload),
                            },
                        )
                except Exception:
                    pass
                emit_step(
                    "thinking",
                    "Evidence core exceeds context window even after auto-compaction — refusing to truncate evidence",
                    "error",
                    detail=f"{final_tokens} tokens > usable {usable} (model limit {max_ctx})",
                )
                # Seal the refused over-limit payload (flagged sent_to_model=False)
                # so the Compliance panels show WHAT we refused to send and the
                # self-heal cuts that occurred — instead of nothing at all.
                _seal_exact_payload(
                    token_count=final_tokens,
                    phase_label=f"{phase}:REFUSED_OVERFLOW",
                    sent_to_model=False,
                )
                raise ContextOverflowError(final_tokens, max_ctx, reserve)

            # Seal the EXACT (possibly slimmed) payload the model will see.
            _seal_exact_payload(token_count=final_tokens, phase_label=phase, sent_to_model=True)

            # Transient-error retry + exponential backoff now lives centrally in
            # ModelRouter.generate (covers main loop, map-reduce, summarization).
            # We pass on_retry so each attempt is visible in the live status and
            # the Compliance Chain-of-Custody trail (RETRY events). The model
            # sees `working` (the slimmed, SEALED history) on every attempt.
            def _on_retry(attempt, exc):
                emit_step("thinking",
                          f"Model transient error ({str(exc)[:60]}) — retrying (attempt {attempt + 1})",
                          "active")
                self._audit_event(
                    "RETRY", reason="transient_model_error",
                    metadata={"attempt": attempt, "phase": phase, "error": str(exc)[:300]},
                )
            # Phase-aware generation tuning: planning + reasoning-trace passes run
            # near-deterministic; investigative/synthesis (answer) turns use the
            # configured answer temperature. Forwarded to every backend via the
            # router (backends ignore knobs they don't support).
            _rcfg = getattr(self.cm, "reasoning_config", None) or {}
            _is_planning_phase = str(phase) in ("planning", "reasoning")
            _gen_params = {
                "temperature": _rcfg.get("planning_temperature", 0.0) if _is_planning_phase
                else _rcfg.get("answer_temperature", 0.2),
                "max_output_tokens": _rcfg.get("max_output_tokens", 8192),
            }
            return self.cm.model_router.generate(
                system_prompt=system_prompt, user_message=user_message,
                tools=tools, history=working, on_retry=_on_retry,
                gen_params=_gen_params,
            )

        def check_report_sync(prev_state):
            """Helper to emit update signal if report blocks were changed (added/edited/deleted)."""
            if not report_callback:
                return prev_state
            current_state = self.cm.report_engine.get_report_json()
            

            has_changed = (
                current_state["metadata"]["block_count"] != prev_state["metadata"]["block_count"] or
                current_state["metadata"]["last_modified"] != prev_state["metadata"]["last_modified"]
            )
            
            if has_changed:
                report_callback(json.dumps(current_state))
            return current_state # Return new state for next comparison

        try:
            # --- STAGE 1: Intent Interception & Ingestion ---
            q_lower = user_query.strip().lower()
            
            # A. Special Case: Triage Initialization
            is_initial_triage = q_lower == "initialize_case_report"
            if is_initial_triage:
                # Triage is fast, but we'll use a snapshot for the initial state
                initial_report_state = self.cm.report_engine.get_report_json()
                return self._run_python_triage(emit_step, check_report_sync, initial_report_state)

            # B. Special Case: Analyze Context (Triggered after backend/model switch)
            elif q_lower == "analyze_case_context":
                emit_step("thinking", "Analyzing current case context and report structure...", "active")

                # Fetch current report state to feed the model
                current_report_state = self.cm.report_engine.get_report_json()

                # Create a concise analysis prompt
                analysis_prompt = (
                    "SYSTEM TASK: You have just been loaded into this case (or your model was switched). "
                    "Quickly review the current forensic report workspace structure below. "
                    "Acknowledge the current state of the investigation in 1-2 brief sentences and tell the investigator you are ready to continue. "
                    "DO NOT perform any tool calls or extensive analysis yet.\n\n"
                    f"Report Workspace:\n{json.dumps(current_report_state, indent=2)[:4000]}" # Limit size
                )

                try:
                    system_prompt = self.cm._build_system_prompt("", []) # Just get the base prompt

                    _ctx_history = list(self.cm.history_manager.history)[-5:]  # minor history context
                    # Record this Eye<->LLM exchange so it appears in the
                    # Compliance conversation log like every other turn.
                    emit_dialogue({
                        "phase": "request",
                        "iteration": None,
                        "system_prompt": system_prompt,
                        "user_message": analysis_prompt,
                        "tools_offered": [],
                        "history_count": len(_ctx_history),
                    })

                    analysis_answer = guarded_generate(
                        system_prompt, analysis_prompt, _ctx_history, None,
                        phase="request", iteration=None,
                    )

                    ai_content = analysis_answer.get("content", "The case context has been analyzed. I am ready to assist.")

                    emit_dialogue({
                        "phase": "response",
                        "iteration": None,
                        "content": ai_content,
                        "tool_calls": [],
                    })

                    # Add only the assistant's acknowledgement to history to keep it clean
                    self.cm.history_manager.add_message("assistant", ai_content)

                    # Per-step GEP compliance: this acknowledgement step runs no
                    # investigation, but it must still leave a record in the trail.
                    # With no tool results it grades GEP-10 PASS, the rest N-A — an
                    # honest record. Best-effort; never breaks the turn.
                    try:
                        gep_ctx = self._evaluate_gep_turn("analyze_case_context", ai_content, [])
                        self._persist_gep_turn(gep_ctx)
                    except Exception as e:
                        self.logger.debug(f"GEP context-analysis evaluation skipped: {e}")

                    emit_step("synthesis", "Context analysis complete", "done")

                    if self.cm.case_directory:
                        self.cm.history_manager.save_history()

                    return {
                        "response": ai_content,
                        "eye_llm_conversation": conversation,
                        "error": None,
                        "context_stats": self.cm.get_context_stats()
                    }
                except ContextOverflowError:
                    raise  # fail hard — handled by the outer refusal handler
                except Exception as e:
                    emit_step("synthesis", "Context analysis failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

            # C. Special Case: Switch Model
            elif q_lower == "switch model" or q_lower.startswith("switch model to"):
                target_model = user_query.strip()[16:].strip() if q_lower.startswith("switch model to") else None
                
                emit_step("thinking", "Fetching available models from active agent", "active")
                available_models = self.cm.model_router.list_models()
                
                if not available_models:
                    available_models = ["default"]

                # Case A: User specified a model name directly
                if target_model and any(m.lower() == target_model.lower() for m in available_models):
                    self.cm.model_router.switch_model(target_model)
                    
                    # RE-RESOLVE WINDOW: clear the previous model's "ghost" context
                    # limit, then size max_total_tokens to the NEW model's real
                    # window (registry for cloud; 32k fallback for unknown, with the
                    # local n_ctx probe still able to override downward at call time).
                    self.cm.max_total_tokens = self.cm._resolve_context_window(
                        getattr(self.cm, "default_max_total_tokens", 64000)
                    )
                    self.cm.token_budget = self.cm._resolve_token_budget()
                    self.logger.info(
                        f"Context window re-resolved to {self.cm.max_total_tokens:,} tokens "
                        f"(budget {self.cm.token_budget}) following model switch to {target_model}"
                    )

                    emit_step("thinking", f"Switched to {target_model}", "done")
                    response = f"Successfully switched active model to **{target_model}**."
                    self.cm.history_manager.add_message("assistant", response)
                    return {"response": response, "error": None, "context_stats": self.cm.get_context_stats()}

                # Case B: User requested the list/menu
                emit_step("thinking", "Model list retrieved", "done")
                model_chips = [{
                    "id": f"switch_{m}", "label": f"Use {m}", "query": f"Switch model to {m}", "icon": "switch"
                } for m in available_models[:5]]
                
                response = "Please select which model you would like to switch to for this agent:"
                return {
                    "response": response, "action_chips": model_chips, "error": None, "context_stats": self.cm.get_context_stats()
                }

            # Regular Query Path
            self.cm.history_manager.add_message("user", user_query)
            
            # --- STAGE 2: Forensic Keyword Analysis ---
            emit_step("thinking", "Scanning query for forensic intents ", "active")
            keywords = self.cm.intent_engine.detect_keywords(user_query)
            emit_step("thinking", f"Detected keywords: {', '.join(keywords) if keywords else 'none'}", "done")
            
            # --- STAGE 3: Knowledge Base (RAG) Lookup ---
            _rcfg0 = getattr(self.cm, "reasoning_config", None)
            _rcfg0 = _rcfg0 if isinstance(_rcfg0, dict) else {}
            rag_top_k = int(_rcfg0.get("rag_top_k", 5))
            rag_min_score = float(_rcfg0.get("rag_min_score", 0.05))
            rag_semantic_min_score = float(_rcfg0.get("rag_semantic_min_score", 0.4))
            emit_step("rag", "Retrieving artifact knowledge from knowledge base ", "active")
            rag_budget = self.cm.token_budget.get("rag_context", 2000)
            rag_context = self.cm.rag_service.retrieve_context(
                keywords=keywords, user_query=user_query, max_tokens=rag_budget,
                top_k=rag_top_k, min_score=rag_min_score,
                semantic_min_score=rag_semantic_min_score,
            )
            audit_rag_trunc(rag_context, 1)
            _rag_sections = rag_context.count("## ") if rag_context else 0
            _rag_docs = list(getattr(self.cm.rag_service, "last_sources", []) or [])
            emit_step(
                "rag",
                (f"Loaded {_rag_sections} knowledge section(s): " + ", ".join(_rag_docs)) if _rag_sections
                else "No matching knowledge base entries",
                "done",
            )

            # --- STAGE 3b: Long-term conversation recall ---
            # Pull earlier turns that were summarized / slid out of the live window
            # but are relevant to this query, so the model can recall a specific old
            # detail on demand. Best-effort; degrades to no recall on any failure.
            recalled_conversation = self._retrieve_conversation_recall(user_query, emit_step)

            # --- STAGE 4: Prompt Engineering ---
            # Snapshot history and report for stable prompt construction
            with self.cm.history_manager._lock:
                history_snapshot = list(self.cm.history_manager.history)

            emit_step("thinking", "Building investigative system prompt ", "active")
            system_prompt = self.cm._build_system_prompt(rag_context, history_snapshot, recalled_conversation)
            emit_step("thinking", "System prompt ready", "done")
            
            # --- STAGE 5: AI Reasoning & Tool Traceability ---
            # Budget sized so the Eye can keep going until it has gathered the
            # evidence it needs: up to MAX_CONTINUE_NUDGES "keep going" prods plus
            # the actual tool rounds of a full multi-database sweep. Each nudge
            # consumes an iteration, so MAX_ITERATIONS must exceed the nudge cap.
            MAX_ITERATIONS = 20
            MAX_CONTINUE_NUDGES = 10
            # If the model produces no executable tool call for this many consecutive
            # iterations while NO tool has executed all turn, it is not going to call
            # tools (incapable, e.g. Gemma offered none, or refusing). Stop nudging and
            # answer honestly instead of burning all MAX_CONTINUE_NUDGES on a no-op.
            MAX_TOOLLESS_BEFORE_EXIT = 2
            # Hierarchical (plan-driven) execution: prove one sub-narrative at a time.
            MAX_SUBNARR_ROUNDS = 4  # tool rounds spent on a single sub-narrative before giving up
            hierarchical = False
            hierarchy_plan = None
            plan_steps = []
            focus_idx = 0
            sub_rounds = 0
            step_result_start = 0  # index into all_tool_results where the current step began
            continue_nudges = 0
            toolless_iters = 0  # consecutive iterations with no parseable tool call
            force_honest_synthesis = False  # set when we exit a tool-less, evidence-free run
            text_fallback_offered = False  # taught a capable model the text protocol once
            failing_cycle_hinted = False
            iteration = 0
            
            # Pop the user message added in STAGE 1 so we can manage it dynamically
            popped_user_msg = self.cm.history_manager.pop_last_message()
            
            current_user_message = user_query
            # Initial state for result aggregation
            initial_report_state = self.cm.report_engine.get_report_json()
            final_option_menu = None
            llm_response = {}
            ai_content = ""
            all_tool_results = []
            ledger_entries = []  # compact per-iteration index for cross-source correlation
            tool_call_history = []
            # Coverage signals for the human reviewer (Workstream E): which case
            # databases the Eye actually consulted, and whether any result was a
            # sample rather than the full set. Surfaced + persisted at turn end.
            consulted_dbs = set()
            coverage_sampled = False

            active_keywords = set(keywords)
            active_keywords.add("Global_schema_database_Reference")

            # --- STAGE 4b: Investigation Planning (decomposition + premises) ---
            # Build a sub-question checklist so multi-part questions are driven
            # to completion and asserted premises get proven/disproven. Gated by
            # reasoning_config (default ON); degrades to today's single-question
            # behavior on any failure or when disabled.
            # ContextManager always populates reasoning_config with every key
            # (defaults ON). Treat a missing/non-dict value as "all off" so the
            # base loop behaves exactly as before when reasoning isn't wired.
            _rc = getattr(self.cm, "reasoning_config", None)
            reasoning_cfg = _rc if isinstance(_rc, dict) else {}
            checklist: List[Dict[str, Any]] = []
            plan_strategy = ""  # overall decomposition strategy (for the reasoning trace)
            reuse_hint = ""  # set when the plan flags this question as related to prior ones
            want_decomp = reasoning_cfg.get("enable_decomposition", False)
            want_premise = reasoning_cfg.get("enable_premise_verification", False)
            # The LLM decides whether/how to split into logical sub-questions;
            # _should_plan is only a trivial-skip pre-filter. auto_segment_question
            # selects the planner's aggressive (logical decomposition) vs
            # conservative (multi-part only) prompt.
            _prefer_segmentation = bool(reasoning_cfg.get("auto_segment_question", True))
            # HIERARCHICAL plan FIRST: build the verdict → narrative → sub-narrative
            # claim hierarchy, seed the Narrative Map with it, and drive the sequential
            # one-narrative-at-a-time engine. Falls back to the flat sub-question path
            # below on any failure (trivial query, planner error, or no narratives).
            if reasoning_cfg.get("enable_hierarchy", False):
                _iter_ceiling = int(reasoning_cfg.get("max_iterations", 300))
                # RESUME an interrupted plan if this turn is a continuation. The map
                # cards already exist (stable created_from keys), so we rebuild the
                # steps WITHOUT re-planning or re-seeding and pick up at the first
                # still-open sub-narrative.
                _saved = self._load_active_plan()
                if _saved:
                    _open_steps = [s for n in _saved.get("narratives", [])
                                   for s in n.get("sub_narratives", []) if s.get("status", "open") == "open"]
                    if _open_steps and self._is_continuation_query(user_query, _saved.get("user_query")):
                        plan_steps = self._rebuild_plan_steps(_saved)
                        if plan_steps:
                            hierarchical = True
                            hierarchy_plan = _saved
                            focus_idx = next((k for k, s in enumerate(plan_steps)
                                              if s["sub"].get("status", "open") == "open"), 0)
                            plan_strategy = "resumed hierarchical plan"
                            MAX_ITERATIONS = min(_iter_ceiling, max(MAX_ITERATIONS,
                                                 len(plan_steps) * (MAX_SUBNARR_ROUNDS + 2) + 5))
                            emit_step("thinking",
                                      f"Resuming the saved investigation at sub-narrative "
                                      f"{focus_idx + 1}/{len(plan_steps)} (continuing where it stopped)",
                                      "done")
                    elif _open_steps:
                        # A new/different question → abandon the stale checkpoint.
                        self._clear_active_plan()
                    else:
                        self._clear_active_plan()  # checkpoint already complete

                if not hierarchical and self._should_plan(user_query):
                    _hplan = self._plan_hierarchy(
                        user_query, guarded_generate, emit_step, emit_dialogue, reasoning_cfg)
                    if _hplan and _hplan.get("narratives"):
                        plan_steps = self._seed_hierarchy_map(_hplan, user_query)
                        if plan_steps:
                            hierarchical = True
                            hierarchy_plan = _hplan
                            plan_strategy = "hierarchical plan-driven investigation"
                            # Budget enough iterations to prove every sub-narrative, but
                            # cap it (configurable) so a maximal plan can't run away. Each
                            # step is also bounded by MAX_SUBNARR_ROUNDS + force-advance.
                            MAX_ITERATIONS = min(_iter_ceiling, max(MAX_ITERATIONS,
                                                 len(plan_steps) * (MAX_SUBNARR_ROUNDS + 2) + 5))
                            # Checkpoint the freshly-seeded plan so an interruption is resumable.
                            self._save_active_plan(_hplan, focus_idx, user_query)
                            emit_step(
                                "thinking",
                                f"Planned {len(_hplan['narratives'])} narrative(s) / {len(plan_steps)} "
                                "sub-narrative(s) to prove — working them in sequence",
                                "done")

            if not hierarchical and (want_decomp or want_premise) and self._should_plan(user_query):
                plan = self._plan_investigation(
                    user_query, guarded_generate, emit_step, emit_dialogue, reasoning_cfg,
                    prefer_segmentation=_prefer_segmentation,
                )
                if plan:
                    plan_strategy = plan.get("strategy", "")
                    if want_decomp:
                        subs = plan.get("sub_questions", [])
                        # Only treat as decomposed when there is genuinely >1 part.
                        if len(subs) > 1:
                            for s in subs:
                                checklist.append({
                                    "q": s.get("q", "") if isinstance(s, dict) else str(s),
                                    "status": "open", "kind": "question",
                                    "why": s.get("why", "") if isinstance(s, dict) else "",
                                })
                    if want_premise:
                        for p in plan.get("user_premises", []):
                            checklist.append({"q": f"verify: {p}", "status": "open", "kind": "premise"})
                    if checklist:
                        emit_step("thinking", f"Planned {len(checklist)} investigation item(s) to resolve", "done")
                    # Surface question segmentation in the Compliance trail.
                    _q_items = [c for c in checklist if c.get("kind") != "premise"]
                    if len(_q_items) > 1:
                        self._audit_event(
                            "SEGMENTED",
                            reason="llm_decomposition",
                            metadata={"parts": [c["q"] for c in _q_items]},
                        )
                        emit_step("thinking",
                                  f"Question segmented into {len(_q_items)} parts — working each in turn", "done")
                    # Early OPEN goal-claim: show the Verdict as the proposition the
                    # whole investigation is trying to prove (a clean claim, never the
                    # raw question) while it runs; _finalize_verdict flips its state.
                    if _q_items:
                        try:
                            _nms = getattr(self.cm, "narrative_map_service", None)
                            if _nms is not None:
                                _g = _nms.load_graph()
                                _cur = (_g.get("verdict") or {}).get("title", "").strip().lower()
                                if _cur in ("", "overall verdict"):
                                    _goal = self._claimify(user_query)
                                    if _goal:
                                        _nms.set_verdict(_goal, "Goal of this investigation — still open.")
                                        self._push_narrative_map_update()
                        except Exception as _e:
                            self.logger.debug(f"early goal-claim skipped: {_e}")
                    # Relatedness: if this likely builds on earlier questions and
                    # answer memory is on, tell the model to reuse the Prior
                    # Findings (in the system prompt) before re-querying.
                    if plan.get("related_prior") and reasoning_cfg.get("enable_question_memory", False):
                        reuse_hint = (
                            "## Reuse Prior Findings\n"
                            "This question likely relates to earlier ones in this case. Before running "
                            "new queries, check the 'Prior Findings' in your system prompt and REUSE "
                            "their data (cite by id, e.g. [q2]); only re-query if a prior finding is "
                            "missing or may be stale."
                        )
                        emit_step("thinking", "Related to earlier questions — will reuse prior findings", "done")

            # --- STAGE 4b2: (removed) ---
            # The map no longer creates a provisional narrative per sub-question —
            # a narrative is a FINDING, not the question. Narratives are created at
            # synthesis from real findings (see `_sync_narratives_from_findings`),
            # with the sub-question kept only as `meta.created_from` provenance.

            # --- STAGE 4c: Sub-question-aware knowledge + related evidence ---
            # Each decomposed sub-question pulls its own targeted artifact
            # knowledge AND its related evidence (matching report/pinned evidence,
            # prior findings, conversation recall, semantic row candidates), built
            # into a structured "Per Sub-Question Context" block. Rebuild the
            # prompt once so iteration 1 already sees it. Best-effort.
            subquestion_context = ""
            if reasoning_cfg.get("rag_subquestion_aware", True):
                _subq_items = [c.get("q", "") for c in checklist if c.get("kind") != "premise"]
                if len(_subq_items) > 1:
                    try:
                        _subq_keywords = set()
                        for _sq in _subq_items:
                            for _kw in self.cm.intent_engine.detect_keywords(_sq):
                                _subq_keywords.add(_kw)
                        if _subq_keywords - active_keywords:
                            active_keywords |= _subq_keywords
                            emit_step("rag", "Retrieving targeted knowledge for each sub-question...", "active")
                            rag_context = self.cm.rag_service.retrieve_context(
                                keywords=list(active_keywords),
                                user_query=user_query + " " + " ".join(_subq_items),
                                max_tokens=rag_budget, top_k=rag_top_k, min_score=rag_min_score,
                                semantic_min_score=rag_semantic_min_score,
                            )
                            audit_rag_trunc(rag_context, 1)
                            _docs = list(getattr(self.cm.rag_service, "last_sources", []) or [])
                            emit_step("rag",
                                      f"Knowledge consulted for sub-questions: {', '.join(_docs)}"
                                      if _docs else "Sub-question knowledge retrieval complete", "done")
                        # Per-sub-question structured knowledge + related evidence.
                        subquestion_context = self._build_subquestion_context(
                            _subq_items, history_snapshot, user_query,
                            {"top_k": rag_top_k, "min_score": rag_min_score,
                             "semantic_min_score": rag_semantic_min_score,
                             "max_qs": int(reasoning_cfg.get("max_sub_questions", 6))},
                            emit_step,
                        )
                        system_prompt = self.cm._build_system_prompt(
                            rag_context, history_snapshot, recalled_conversation, subquestion_context)
                    except Exception as _e:
                        self.logger.debug(f"Sub-question-aware context skipped: {_e}")

            # Gemma models on the Gemini API can't use NATIVE function-calling (the
            # backend drops the `tools` config, otherwise the API 500s), so they call
            # tools through the TEXT protocol instead — the system prompt teaches them
            # the ```tool_call format. Note it ONCE so the investigator understands the
            # tool calls arrive as text, not native calls. This is NOT a failure.
            try:
                _mr_cfg = self.cm.model_router.config
                _bk = (_mr_cfg.get("backend") or "").lower()
                _mdl = (_mr_cfg.get("model_name") or "").replace("models/", "").lower()
                if _bk == "gemini" and _mdl.startswith("gemma"):
                    emit_step(
                        "thinking",
                        "Gemma model: native function-calling is unavailable on the Gemini API — "
                        "running forensic tools via the text tool-call protocol.",
                        "done",
                    )
                    self.logger.info(
                        "Active model '%s' is a Gemma model on the Gemini API; using the text "
                        "tool-call protocol (native function-calling unavailable).", _mdl)
            except Exception:
                pass

            while iteration < MAX_ITERATIONS:
                iteration += 1

                # RE-INSERT USER QUERY: If we just started and tools were run,
                # we must ensure the original question is back in the persistent log.
                if iteration == 1 and popped_user_msg:
                    self.cm.history_manager.add_message(
                        popped_user_msg["role"], 
                        popped_user_msg["content"], 
                        popped_user_msg.get("metadata")
                    )
                
                if iteration > 1:
                    emit_step("rag", "Updating forensic knowledge context...", "active")
                    rag_budget = self.cm.token_budget.get("rag_context", 2000)
                    rag_context = self.cm.rag_service.retrieve_context(
                        keywords=list(active_keywords), user_query=user_query, max_tokens=rag_budget,
                        top_k=rag_top_k, min_score=rag_min_score,
                        semantic_min_score=rag_semantic_min_score,
                    )
                    audit_rag_trunc(rag_context, iteration)

                    with self.cm.history_manager._lock:
                        history_snapshot = list(self.cm.history_manager.history)
                    system_prompt = self.cm._build_system_prompt(
                        rag_context, history_snapshot, recalled_conversation, subquestion_context)
                    _rag_sections = rag_context.count("## ") if rag_context else 0
                    emit_step(
                        "rag",
                        f"Knowledge refreshed: {_rag_sections} section(s)" if _rag_sections
                        else "Knowledge refreshed: no matching entries",
                        "done",
                    )

                model_name = self.cm.model_router.config.get('model_name', 'LLM')
                emit_step("thinking", f"Consulting model: {model_name} (Step {iteration}) ", "active")
                
                try:
                    # AI GENERATION IS NOW OUTSIDE ANY LOCKS - Prevents UI from freezing
                    step_message = current_user_message
                    if iteration > 1:
                        step_message = f"[ORIGINAL GOAL: {user_query}]\n\n{current_user_message}"
                        

                    # Model receives history_snapshot AND step_message.
                    # If the newest message is already in snapshot, remove it to save tokens.
                    clean_history = history_snapshot
                    if clean_history and clean_history[-1].get("content") == step_message:
                        clean_history = clean_history[:-1]

                    # Cross-iteration evidence ledger: prepend the compact per-step
                    # index to the OUTGOING message so the model can correlate
                    # across every tool/database it has run — without bloating the
                    # persisted history (only step_message is stored, below).
                    ledger_text = self._build_evidence_ledger(ledger_entries)
                    # Hierarchical runs focus on the CURRENT sub-narrative only; flat
                    # runs show the whole open checklist.
                    checklist_text = (self._build_focus_block(hierarchy_plan, plan_steps, focus_idx)
                                      if hierarchical
                                      else self._build_checklist_block(checklist))
                    # The reuse hint is only worth sending on the first turn.
                    _hint = reuse_hint if iteration == 1 else ""
                    _prefix = "\n\n".join(x for x in (_hint, checklist_text, ledger_text) if x)
                    outgoing_message = (_prefix + "\n\n" + step_message) if _prefix else step_message

                    _tool_defs = self.cm._get_tool_definitions()
                    # Record what the Eye SENT to the model this turn (full prompt).
                    emit_dialogue({
                        "phase": "request",
                        "iteration": iteration,
                        "system_prompt": system_prompt,
                        "user_message": outgoing_message,
                        "tools_offered": [t.get("name") for t in _tool_defs],
                        "history_count": len(clean_history),
                    })
                    # Guarded: fail-hard on context overflow + seal the payload.
                    llm_response = guarded_generate(
                        system_prompt, outgoing_message, clean_history, _tool_defs,
                        phase="request", iteration=iteration,
                    )

                    # Record what the model REPLIED (reasoning + requested tools),
                    # and make the milestone label reflect the real outcome.
                    _resp_content = (llm_response.get("content") or "").strip()
                    _resp_tcs = self.cm._parse_tool_calls(llm_response)
                    emit_dialogue({
                        "phase": "response",
                        "iteration": iteration,
                        "content": _resp_content,
                        "tool_calls": [
                            {"name": tc.get("name"), "arguments": tc.get("parameters", {})}
                            for tc in _resp_tcs
                        ],
                    })
                    if _resp_content and _resp_tcs:
                        _resp_label = f"Model replied: reasoning + {len(_resp_tcs)} tool call(s)"
                    elif _resp_content:
                        _resp_label = "Model replied (text only)"
                    elif _resp_tcs:
                        _resp_label = f"Model requested {len(_resp_tcs)} tool call(s), no text"
                    else:
                        _resp_label = "Model returned an empty response"
                    emit_step("thinking", _resp_label, "done")

                    if iteration > 1:
                        self.cm.history_manager.add_message("user", step_message, {"internal": True})
                    
                    ai_content = llm_response.get("content", "")
                    new_kws = self.cm.intent_engine.detect_keywords(ai_content)
                    for kw in new_kws:
                        active_keywords.add(kw)

                    # Refresh sub-question/premise checklist from this turn's
                    # answer + accumulated evidence (drives the completion gate).
                    self._update_checklist(checklist, ai_content, ledger_entries)

                    if "option_menu" in llm_response:
                        final_option_menu = llm_response.get("option_menu")
                    
                    self.cm.history_manager.add_message("assistant", ai_content, {
                        "tool_calls": llm_response.get("tool_calls")
                    })
                        
                except ContextOverflowError:
                    raise  # fail hard — handled by the outer refusal handler
                except Exception as e:
                    emit_step("thinking", "Model connection failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

                tool_calls = self.cm._parse_tool_calls(llm_response)

                # ── Hierarchical engine: resolve the CURRENT sub-narrative ──────────
                if hierarchical and focus_idx < len(plan_steps):
                    sub_rounds += 1
                    _sv, _sv_reason = self._parse_subverdict(ai_content)
                    # Budget exhausted without a clean marker → decide from the EVIDENCE
                    # gathered (so a model that found the data but skipped the marker is
                    # not auto-failed), not a blind NOT-PROVEN.
                    if _sv is None and sub_rounds > MAX_SUBNARR_ROUNDS:
                        _sv, _sv_reason = self._resolve_by_evidence(
                            plan_steps[focus_idx], all_tool_results[step_result_start:])
                    if _sv is not None:
                        self._resolve_substep(plan_steps[focus_idx], _sv, _sv_reason,
                                              all_tool_results[step_result_start:])
                        emit_step("synthesis",
                                  f"Sub-narrative {focus_idx + 1}/{len(plan_steps)} → {_sv}", "done")
                        focus_idx += 1
                        sub_rounds = 0
                        continue_nudges = 0
                        step_result_start = len(all_tool_results)
                        # Checkpoint progress so an interruption can resume here.
                        self._save_active_plan(hierarchy_plan, focus_idx, user_query)
                        if focus_idx >= len(plan_steps):
                            emit_step("thinking", "All narratives resolved — aggregating the verdict", "done")
                            break
                        current_user_message = "Now prove the NEXT sub-narrative shown below."
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue
                    if not tool_calls:
                        # Narrated without acting AND without concluding → nudge to act
                        # or conclude; force-advance if it keeps stalling on this step.
                        continue_nudges += 1
                        if continue_nudges >= MAX_CONTINUE_NUDGES:
                            _esv, _ereason = self._resolve_by_evidence(
                                plan_steps[focus_idx], all_tool_results[step_result_start:])
                            self._resolve_substep(plan_steps[focus_idx], _esv, _ereason,
                                                  all_tool_results[step_result_start:])
                            focus_idx += 1
                            sub_rounds = 0
                            continue_nudges = 0
                            step_result_start = len(all_tool_results)
                            self._save_active_plan(hierarchy_plan, focus_idx, user_query)
                            if focus_idx >= len(plan_steps):
                                break
                        current_user_message = (
                            "You did not call a tool or conclude. Either emit a tool call to gather "
                            "THIS sub-narrative's evidence, or end your turn with "
                            "`SUBVERDICT: PROVEN || <evidence>` or `SUBVERDICT: NOT-PROVEN || <why>`.")
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue
                    # else: tool calls present, step unresolved → fall through to execute.

                if (not hierarchical) and (not tool_calls):
                    toolless_iters += 1
                    # No tool has executed ALL TURN and the model keeps not calling
                    # tools → it is not going to (incapable — e.g. a Gemma model is
                    # offered none — or refusing). Stop nudging and answer HONESTLY
                    # rather than burning the whole nudge budget on a no-op and then
                    # presenting the model's plan as if it were findings.
                    if not all_tool_results and toolless_iters >= MAX_TOOLLESS_BEFORE_EXIT:
                        emit_step("thinking",
                                  "No tool executed after repeated attempts — the model is not "
                                  "retrieving evidence. Answering honestly without fabricating findings.",
                                  "done")
                        force_honest_synthesis = True
                        break

                    # The model produced text but no tool call. If it signaled it
                    # would keep going (e.g. "I will now check prefetch…"), it has
                    # NOT finished — nudge it to actually act instead of ending the
                    # turn and waiting for the user. Bounded to avoid runaway.
                    _lc = (ai_content or "").lower()
                    _intent = any(p in _lc for p in (
                        "i will now", "i'll now", "i will next", "next, i", "next i",
                        "let me", "proceed to", "i will search", "i will check",
                        "i will query", "i will examine", "i will investigate",
                        "now investigate", "to further investigate", "i will look",
                        "i'm going to", "i am going to", "let's", "i will proceed",
                    ))
                    # When NOTHING has executed yet, escalate from a gentle "keep going"
                    # to a hard "stop narrating, emit an actual call" — re-sending the
                    # same prod verbatim is what let the old run spin 10× uselessly.
                    _no_evidence_yet = not all_tool_results
                    if _intent and continue_nudges < MAX_CONTINUE_NUDGES:
                        continue_nudges += 1
                        emit_step("thinking", f"Model narrated next steps without acting — continuing the investigation (nudge {continue_nudges})", "active")
                        if _no_evidence_yet:
                            current_user_message = (
                                "You have executed NO tool yet — you only narrated a plan. STOP "
                                "describing what you will do. Emit an ACTUAL tool call right now "
                                "(e.g. `query_database` or `get_schema`) against a relevant database. "
                                "Output only the tool call, not prose."
                            )
                        else:
                            current_user_message = (
                                "You stated a next step but did NOT call any tool. Do NOT stop or wait "
                                "for the user. Emit the tool call(s) for that next step now, and keep "
                                "checking every relevant database in sequence until you have actually "
                                "answered the question."
                            )
                        # Text-protocol FALLBACK for a capable (native function-calling)
                        # model that narrated instead of calling a tool: teach it the
                        # text format ONCE so it has a second way to act. Gemma already
                        # has the format in its system prompt (tools_unsupported), so we
                        # only do this for models that were offered native tools.
                        if (not text_fallback_offered
                                and not llm_response.get("tools_unsupported")):
                            text_fallback_offered = True
                            try:
                                _fmt = self.cm._build_tool_call_format(
                                    self.cm._get_tool_definitions(), mandatory=False)
                                current_user_message += "\n\n" + _fmt
                            except Exception as _e:
                                self.logger.debug(f"text-protocol fallback hint skipped: {_e}")
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue

                    # Decomposition completion gate: don't finish while planned
                    # sub-questions / premise checks are still OPEN.
                    open_items = [c for c in checklist if c.get("status") != "answered"]
                    if open_items and continue_nudges < MAX_CONTINUE_NUDGES:
                        continue_nudges += 1
                        emit_step("thinking", f"{len(open_items)} sub-question(s)/premise(s) still open — continuing", "active")
                        _nudge_lead = (
                            "You have executed NO tools and produced NO evidence. Call "
                            "`query_database` / `get_schema` on a relevant database NOW — do not "
                            "narrate a plan.\n" if _no_evidence_yet else ""
                        )
                        current_user_message = (
                            _nudge_lead
                            + "You have NOT yet addressed every part of the investigator's request. "
                            "Still OPEN:\n"
                            + "\n".join(f"- {c.get('q')}" for c in open_items)
                            + "\nInvestigate the open item(s) NOW with the appropriate tool calls. "
                            "For any 'verify:' item, PROVE or DISPROVE the claim against the artifacts. "
                            "Do not stop or hand back to the investigator until every item is resolved."
                        )
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue

                    emit_step("thinking", "Investigation complete", "done")
                    break

                toolless_iters = 0  # a real tool call this iteration resets the counter
                current_calls_signature = [(tc.get("name"), json.dumps(tc.get("parameters", {}), sort_keys=True)) for tc in tool_calls]


                # Detects cycles like A -> B -> A by checking last 3 unique turns
                if any(sig == current_calls_signature for sig in tool_call_history[-3:]):
                    # If the repeated calls were FAILING, give one corrective hint
                    # (use the schema reference / query directly / move on) before
                    # breaking — repeating a failing get_schema shouldn't end the run.
                    _recent_failed = any(
                        (not r.get("success")) for r in all_tool_results[-len(tool_calls):]
                    ) if all_tool_results else False
                    if _recent_failed and not failing_cycle_hinted:
                        failing_cycle_hinted = True
                        emit_step("thinking", "Repeated failing tool call — steering to an alternative", "active")
                        current_user_message = (
                            "That tool call keeps FAILING — do NOT repeat it identically. Use the "
                            "Global Schema Reference for the table's columns, or query the table "
                            "directly with a known column, or move on to the next relevant database. "
                            "Continue the investigation."
                        )
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue
                    emit_step("thinking", "Detected tool call cycle. Breaking cycle.", "done")
                    ai_content += "\n\n*(Detected repetitive tool calls. Providing partial synthesis based on available data.)*"
                    break

                tool_call_history.append(current_calls_signature)

                # --- STAGE 6: Tool Execution & Evidence Anchoring ---
                emit_step("thinking", f"Executing {len(tool_calls)} forensic tool(s) ", "active")
                iteration_tool_results = []
                for i, call in enumerate(tool_calls):
                    tool_name = call.get("name", "unknown")
                    emit_step("tool_call", f"Calling tool: {tool_name} ({i+1}/{len(tool_calls)})", "active", tool=tool_name, params=call.get("parameters"))
                    
                    result = self.cm._execute_tool(call, hitl_callback=hitl_callback)
                    # Transparent auto map-reduce: a very large query result is
                    # analyzed in full (sealed segments) instead of sampled.
                    result = self._maybe_auto_map_reduce(call, result, user_query, reasoning_cfg, emit_step)
                    # Stamp the originating call params (sql_query, database_name) onto
                    # the result so evidence built from it can later reload its source.
                    if isinstance(result, dict):
                        result.setdefault("parameters", call.get("parameters") or {})
                    iteration_tool_results.append(result)
                    all_tool_results.append(result)
                    # Coverage tracking: which DBs were consulted + sampled flag.
                    try:
                        _p = call.get("parameters") or {}
                        if tool_name in ("query_database", "get_schema", "analyze_large_dataset") and _p.get("database_name"):
                            consulted_dbs.add(_p.get("database_name"))
                        _rr = result.get("result") if isinstance(result.get("result"), dict) else result
                        if isinstance(_rr, dict) and (_rr.get("compressed") or
                                (isinstance(_rr.get("row_count"), int) and _rr.get("row_count") > 200)):
                            coverage_sampled = True
                    except Exception:
                        pass
                    # Compact ledger entry (cross-iteration correlation index).
                    ledger_entries.append({
                        "iteration": iteration,
                        "tool": tool_name,
                        "params": call.get("parameters"),
                        "success": bool(result.get("success")),
                        "result": result.get("result") if isinstance(result.get("result"), dict) else result,
                    })

                    status = "done" if result.get("success") else "error"
                    emit_step("tool_call", f"Tool complete: {tool_name}", status, tool=tool_name, detail=result.get("error"))

                    # Record the tool result fed back to the model.
                    try:
                        _result_str = json.dumps(result, ensure_ascii=False, default=str)
                    except Exception:
                        _result_str = str(result)
                    emit_dialogue({
                        "phase": "tool_result",
                        "iteration": iteration,
                        "tool_name": tool_name,
                        "parameters": call.get("parameters", {}),
                        "success": bool(result.get("success")),
                        "result": _result_str[:4000] + (" …[truncated]" if len(_result_str) > 4000 else ""),
                    })
                
                # Sync report changes to GUI
                initial_report_state = check_report_sync(initial_report_state)

                # default=str so a non-JSON-serializable tool result (e.g. a
                # dataclass that slipped through a handler) can NEVER crash the
                # whole investigation turn — it degrades to a string instead.
                tool_output_str = json.dumps(iteration_tool_results, indent=2, default=str)

                # Token-aware, window-scaled cap on a single tool output (P3 #11).
                tool_output_limit = self._tool_output_char_limit()

                if len(tool_output_str) <= tool_output_limit:
                    history_tool_output = tool_output_str
                else:
                    # Never trim evidence silently: surface it as a step and log
                    # it to the chain-of-custody audit trail.
                    history_tool_output = tool_output_str[:tool_output_limit] + f"\n\n... [TRUNCATED IN MEMORY TO {tool_output_limit:,} CHARACTERS. AI MAY NEED TO QUERY SPECIFIC SUBSETS IF EVIDENCE IS MISSING] ..."
                    emit_step(
                        "tool_call",
                        f"Tool output trimmed in memory ({len(tool_output_str):,}→{tool_output_limit:,} chars) — query a narrower subset if evidence is missing",
                        "error",
                    )
                    try:
                        tool_detail = evidence_seal.build_cut_detail(
                            action="TRUNCATED_TOOL_OUTPUT",
                            message_id=f"tool-output-iter-{iteration}",
                            role="tool",
                            original_text=tool_output_str,
                            processed_text=tool_output_str[:tool_output_limit],
                            dropped_text=tool_output_str[tool_output_limit:],
                            token_count=len(tool_output_str),
                            iteration=iteration,
                            processed_is_prefix=True,  # kept head is a literal prefix of the output
                        )
                        tool_truncations.append(tool_detail)
                        if getattr(self.cm, "truncation_auditor", None):
                            self.cm.truncation_auditor.log_event(
                                action="TRUNCATED",
                                message_id=f"tool-output-iter-{iteration}",
                                token_count=len(tool_output_str),
                                reason=f"tool_output_memory_cap_{tool_output_limit}_chars",
                                message_hash=EvidenceSeal._sha256(tool_output_str),
                                metadata={"kept_chars": tool_output_limit, **tool_detail},
                            )
                    except Exception:
                        pass

                new_kws_from_tools = self.cm.intent_engine.detect_keywords(tool_output_str)
                for kw in new_kws_from_tools: active_keywords.add(kw)

                # GEP-8 (Tool Traceability): prepend an LLM-visible header
                # listing every tool call in this iteration with its name + iteration
                # index BEFORE the JSON payload, so the next model turn sees the trace
                # literally in the message content (not just in metadata).
                N = len(iteration_tool_results)
                trace_header = "\n".join(
                    f"[Tool {i + 1}/{N}: {r.get('tool_name', 'unknown')}, iteration {iteration}]"
                    for i, r in enumerate(iteration_tool_results)
                )

                # Stored as a "user"-role turn (not "system") so it stays in
                # chronological order after the assistant's tool call: the
                # backend message sanitizer hoists ALL system messages into one
                # leading block, which would otherwise flatten the
                # tool-call -> tool-result sequence the model needs to reason
                # across iterations. The is_tool_result metadata still drives
                # the Activity audit and GEP-8 (both key on metadata).
                self.cm.history_manager.add_message(
                    "user",
                    f"{trace_header}\nInvestigation Tool Results:\n{history_tool_output}",
                    {"is_tool_result": True, "tool_names": [r.get("tool_name") for r in iteration_tool_results], "iteration": iteration}
                )
                current_user_message = (
                    "Analyze the tool results above. If the question asks whether something "
                    "exists / was installed / was run, you are NOT finished until you have "
                    "checked EVERY relevant database in sequence (Amcache, Prefetch, Registry "
                    "Uninstall keys, ShimCache, SRUM, MFT) — do not stop after one database "
                    "returns nothing, and do not hand back to the investigator mid-sweep. "
                    "If you have genuinely enough evidence, provide your final synthesis; "
                    "otherwise call the next tool now."
                )
                
                # Update history snapshot for next turn
                with self.cm.history_manager._lock:
                    history_snapshot = list(self.cm.history_manager.history)

            # Hierarchical: if the loop exited (e.g. hit MAX_ITERATIONS) with
            # sub-narratives still unresolved, resolve every remaining one from the
            # evidence so NO seeded card is left stuck `open` and the verdict reflects
            # the whole plan. (Safe no-op when all steps already resolved.)
            if hierarchical and focus_idx < len(plan_steps):
                emit_step("thinking",
                          f"Step budget reached — resolving {len(plan_steps) - focus_idx} "
                          "remaining sub-narrative(s) from the evidence gathered", "done")
                while focus_idx < len(plan_steps):
                    _lsv, _lreason = self._resolve_by_evidence(
                        plan_steps[focus_idx], all_tool_results[step_result_start:])
                    self._resolve_substep(plan_steps[focus_idx], _lsv, _lreason,
                                          all_tool_results[step_result_start:])
                    focus_idx += 1
                    step_result_start = len(all_tool_results)

            # --- STAGE 7: Final Forensic Synthesis & Completion ---
            # Force a synthesis pass whenever the iteration loop exited without
            # a usable text answer. Three triggers:
            #   1. Hit MAX_ITERATIONS while still calling tools (original case).
            #   2. Model returned empty text content on the breaking turn — Gemini
            #      often does this after tool calls, leaving ai_content = "".
            #   3. Tools were run earlier but no synthesis text was produced — the
            #      investigator deserves an answer AND the report needs the findings.
            hit_max_iter = bool(tool_calls and iteration >= MAX_ITERATIONS)
            empty_response = not (ai_content or "").strip()
            tools_were_run_but_no_synthesis = bool(all_tool_results) and empty_response
            # 4. The model never executed a tool and produced no evidence — its text
            #    (if any) is a plan, not findings. Force an HONEST synthesis so the plan
            #    is replaced by a truthful "no data retrieved" answer.
            # 5. A hierarchical run that finished proving its narratives ALWAYS gets a
            #    synthesis pass to aggregate the sub-narratives into the verdict answer.
            hierarchical_done = hierarchical and focus_idx >= len(plan_steps)
            needs_synthesis = (hit_max_iter or empty_response
                               or tools_were_run_but_no_synthesis or force_honest_synthesis
                               or hierarchical_done)

            if needs_synthesis:
                if force_honest_synthesis:
                    reason = "No evidence retrieved — forcing an honest answer"
                elif hierarchical_done:
                    reason = "All narratives resolved — aggregating the verdict"
                elif hit_max_iter:
                    reason = "Max steps reached"
                elif tools_were_run_but_no_synthesis:
                    reason = "Tools executed but model returned no synthesis"
                else:
                    reason = "Model returned empty text — forcing synthesis"
                emit_step("synthesis", f"{reason}. Forcing synthesis.", "active")
                # Hierarchical: prepend the plan outcomes so the synthesis aggregates
                # the proven/negative sub-narratives into the final verdict.
                _ledger = self._build_evidence_ledger(ledger_entries)
                if hierarchical:
                    _outcomes = self._hierarchy_outcomes_block(hierarchy_plan)
                    _ledger = (_outcomes + "\n\n" + _ledger) if _ledger else _outcomes
                synthesis_prompt = self._build_synthesis_prompt(
                    user_query, all_tool_results,
                    ledger_text=_ledger,
                    checklist=checklist,
                )
                # With zero successful evidence there is nothing to document — do not
                # offer report_* tools (a report write would assert a finding we cannot
                # support). The synthesis must be a plain, honest chat answer.
                _has_evidence = any(isinstance(r, dict) and r.get("success") for r in all_tool_results)
                _synth_tools = ([t for t in self.cm._get_tool_definitions() if "report_" in t['name']]
                                if _has_evidence else [])
                emit_dialogue({
                    "phase": "synthesis_request",
                    "iteration": iteration,
                    "system_prompt": system_prompt,
                    "user_message": synthesis_prompt,
                    "tools_offered": [t.get("name") for t in _synth_tools],
                    "history_count": len(history_snapshot),
                })

                try:
                    final_answer = guarded_generate(
                        system_prompt, synthesis_prompt, history_snapshot, _synth_tools,
                        phase="synthesis_request", iteration=iteration,
                    )
                    synthesis_content = (final_answer.get("content") or "").strip()

                    synthesis_tool_calls = self.cm._parse_tool_calls(final_answer)

                    emit_dialogue({
                        "phase": "synthesis_response",
                        "iteration": iteration,
                        "content": synthesis_content,
                        "tool_calls": [
                            {"name": tc.get("name"), "arguments": tc.get("parameters", {})}
                            for tc in synthesis_tool_calls
                        ],
                    })

                    # Execute the report_* tool calls FIRST so we know whether the
                    # write actually succeeded before we make any claim about it in
                    # chat. Failures are recorded (not swallowed) so the truthful-claim
                    # logic below and the audit trail both see them.
                    report_persisted = False
                    report_attempted = False
                    for call in synthesis_tool_calls:
                        if (call.get("name") or "").startswith("report_"):
                            report_attempted = True
                            try:
                                tool_result = self.cm._execute_tool(call, hitl_callback=hitl_callback)
                                all_tool_results.append(tool_result)
                                if tool_result.get("success"):
                                    report_persisted = True
                            except Exception as exec_exc:
                                self.logger.error(f"Synthesis-time report tool failed: {exec_exc}")
                                all_tool_results.append({
                                    "tool_name": call.get("name"),
                                    "success": False,
                                    "error": str(exec_exc),
                                })

                    if synthesis_content:
                        ai_content = synthesis_content
                    else:
                        # The model documented to the report but gave us no chat text.
                        # The investigator reads chat first, so force a dedicated
                        # text-only pass that MUST answer conversationally (no tools).
                        emit_step("synthesis", "No chat answer returned — generating direct answer", "active")
                        text_prompt = self._build_synthesis_prompt(
                            user_query, all_tool_results, text_only=True,
                            ledger_text=self._build_evidence_ledger(ledger_entries),
                            checklist=checklist,
                        )
                        emit_dialogue({
                            "phase": "synthesis_request",
                            "iteration": iteration,
                            "system_prompt": system_prompt,
                            "user_message": text_prompt,
                            "tools_offered": [],
                            "history_count": len(history_snapshot),
                        })
                        text_answer = {}
                        try:
                            text_answer = guarded_generate(
                                system_prompt, text_prompt, history_snapshot, [],
                                phase="synthesis_request", iteration=iteration,
                            )
                        except ContextOverflowError:
                            raise  # fail hard — handled by the outer refusal handler
                        except Exception as text_exc:
                            self.logger.error(f"Text-only synthesis pass failed: {text_exc}")

                        ai_content = (text_answer.get("content") or "").strip()
                        emit_dialogue({
                            "phase": "synthesis_response",
                            "iteration": iteration,
                            "content": ai_content,
                            "tool_calls": [],
                        })

                        if not ai_content:
                            # Last-resort placeholder — kept HONEST. Base the report
                            # claim on whether ANY report_* write actually succeeded
                            # across the WHOLE turn (not just this synthesis pass).
                            def _is_report(r):
                                return (r.get("tool_name") or r.get("name") or "").startswith("report_")
                            turn_report_attempted = report_attempted or any(_is_report(r) for r in all_tool_results)
                            turn_report_persisted = report_persisted or any(_is_report(r) and r.get("success") for r in all_tool_results)
                            successful = [r.get("tool_name") for r in all_tool_results if r.get("success")]
                            unique = sorted({n for n in successful if n})
                            unique_str = ', '.join(unique) if unique else 'the requested tools'
                            ai_content = (
                                "Investigator, I have completed the analysis using the following tools: "
                                f"**{unique_str}**. "
                            )
                            if turn_report_persisted:
                                ai_content += "The findings have been documented in the Forensic Report pane for your review. How would you like to proceed?"
                            elif turn_report_attempted:
                                ai_content += "I attempted to document the findings to the Forensic Report, but the write did not succeed — please review the evidence in this conversation. How would you like to proceed?"
                            else:
                                ai_content += "How would you like to proceed?"

                    self.cm.history_manager.add_message("user", synthesis_prompt, {"internal": True})
                    self.cm.history_manager.add_message("assistant", ai_content)
                    emit_step("synthesis", "Forensic synthesis complete ", "done")
                    check_report_sync(initial_report_state)
                except ContextOverflowError:
                    raise  # fail hard — handled by the outer refusal handler
                except Exception as e:
                    emit_step("synthesis", "Synthesis failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

            # Guarantee the Forensic Report is never empty when the Eye actually
            # investigated: if tools ran and we produced a substantive answer but
            # the model did NOT persist a report_* block this turn, auto-document
            # the findings. Covers both exit paths (forced synthesis and a plain
            # final answer) and both surfaces (Case Summary + live report pane).
            try:
                _report_written = any(
                    (r.get("tool_name") or r.get("name") or "").startswith("report_") and r.get("success")
                    for r in all_tool_results
                )
                if all_tool_results and (ai_content or "").strip() and not _report_written \
                        and getattr(self.cm, "report_engine", None):
                    self.cm.report_engine.append_section(
                        f"Investigation Findings: {user_query[:80]}",
                        ai_content,
                        author="ai",
                        category="Investigation Findings",
                    )
                    self.cm.report_engine.save_report()
                    check_report_sync(initial_report_state)
                    emit_step("synthesis", "Findings auto-documented to the Forensic Report", "done")
            except Exception as e:
                self.logger.error(f"Auto-persist findings failed: {e}")

            if self.cm.case_directory:
                self.cm.history_manager.save_history()
                
                # Log this investigation step for the Summary Dialog
                try:
                    summary_text = ai_content[:200] + "..." if len(ai_content) > 200 else ai_content
                    # Try to detect if evidence was found based on tool results or keywords
                    evidence_found = any(r.get("success") and len(str(r.get("data", ""))) > 100 for r in all_tool_results)
                    
                    self.cm.case_context_manager.log_investigation_step(
                        query=user_query,
                        response_summary=summary_text,
                        evidence_found=evidence_found,
                        suggested_next_steps="Continue investigation based on AI recommendations." if not final_option_menu else "Select a suggested next step from the menu.",
                        artifacts_queried=list(set([r.get("tool_name") for r in all_tool_results if r.get("tool_name")])),
                        query_type="analysis"
                    )
                except Exception as e:
                    self.logger.error(f"Failed to log investigation step: {e}")

                # Per-question answer memory (v0.11.1): persist a concise answer
                # summary + the extracted findings (the evidence ledger) so a
                # related follow-up can REUSE the data instead of re-querying.
                try:
                    if reasoning_cfg.get("enable_question_memory", False) and self.cm.case_context_manager:
                        _clean = (ai_content or "").strip()
                        _summary = (_clean[:600] + "…") if len(_clean) > 600 else _clean
                        self.cm.case_context_manager.save_question_memory(
                            question=user_query,
                            answer_summary=_summary,
                            key_findings=self._build_evidence_ledger(ledger_entries),
                            artifacts_queried=list({r.get("tool_name") for r in all_tool_results if r.get("tool_name")}),
                            sub_questions=[c.get("q") for c in checklist],
                        )
                except Exception as e:
                    self.logger.error(f"Failed to save question memory: {e}")

            # NOTE: Narrative Map narratives are now created from FINDINGS (not the
            # sub-questions) AFTER the reasoning trace below, so they can use the
            # trace's per-sub-question conclusions as the card titles. See
            # `_sync_narratives_from_findings` after the reasoning-trace block.

            # Coverage signals (computed BEFORE the GEP evaluation so the GEP-6
            # Completeness & Coverage check can grade/disclose them): which case
            # databases were consulted vs. available, and whether any result was a
            # sample. Surfaced to the investigator + persisted.
            coverage = self._emit_coverage(consulted_dbs, coverage_sampled, user_query, emit_step)

            # Per-answer GEP compliance: evaluate the behavioral rules for this
            # turn and persist so the Compliance panel can show, per question,
            # whether the Eye actually followed the protocol.
            gep_turn = None
            try:
                gep_turn = self._evaluate_gep_turn(user_query, ai_content, all_tool_results, coverage, checklist)
                self._persist_gep_turn(gep_turn)
            except Exception as e:
                self.logger.debug(f"GEP turn evaluation skipped: {e}")

            # A HIERARCHICAL run already OWNS the Narrative Map (seeded the plan, then
            # flipped each sub-narrative live), so the post-hoc flat sync + map-checklist
            # are skipped — running them would create duplicate/competing cards. Only the
            # verdict is finalized (its title was seeded; here its proven/unproven state
            # is rolled up from the narratives by `_finalize_verdict`).
            _was_focus = bool(getattr(self.cm, "_focus_narrative_id", None))
            if hierarchical:
                if not _was_focus:
                    try:
                        ai_content = self._finalize_verdict(ai_content, user_query)
                    except Exception as _e:
                        self.logger.debug(f"Verdict finalize (hierarchical) skipped: {_e}")
                # The plan ran to completion (all sub-narratives resolved) — drop the
                # resume checkpoint so a later turn doesn't re-resume a finished plan.
                self._clear_active_plan()
            else:
                # Map/reasoning checklist: ensures a non-decomposed but investigative turn
                # still lands one main claim on the Narrative Map (the investigation
                # `checklist` itself is never mutated). See `_build_map_checklist`.
                map_checklist = self._build_map_checklist(checklist, user_query, all_tool_results)

                # Reasoning trace (v0.11.3): capture WHY each (sub-)question was created
                # and WHY each conclusion follows from which evidence — a sealed, tool-less
                # structured pass grounded in the evidence ledger — for the Compliance UI
                # and the Narrative Map. Best-effort; never breaks.
                _reasoning_trace = None
                try:
                    _map_q = [c for c in map_checklist if c.get("kind") != "premise"]
                    if reasoning_cfg.get("enable_reasoning_trace", True) and (_map_q or map_checklist):
                        _ls = getattr(self.cm.rag_service, "last_sources", None)
                        _knowledge = list(_ls) if isinstance(_ls, list) else []
                        trace = self._capture_reasoning_trace(
                            user_query, map_checklist, ledger_entries, ai_content,
                            guarded_generate, emit_step, emit_dialogue,
                            strategy=plan_strategy, knowledge_consulted=_knowledge,
                        )
                        if trace:
                            _reasoning_trace = trace
                            self._persist_reasoning_turn(trace, user_query)
                except Exception as e:
                    self.logger.debug(f"Reasoning trace capture skipped: {e}")

                # Narrative Map: create narratives from the FINDINGS (claim/finding as
                # the title, the originating sub-question kept only as metadata).
                try:
                    self._sync_narratives_from_findings(map_checklist, all_tool_results, _reasoning_trace, emit_step, user_query, ai_content)
                except Exception as _e:
                    self.logger.debug(f"Narrative Map findings-sync skipped: {_e}")
                if not _was_focus:
                    try:
                        ai_content = self._finalize_verdict(ai_content, user_query)
                    except Exception as _e:
                        self.logger.debug(f"Verdict finalize skipped: {_e}")

            # Keep the chat answer clean: any text-protocol ```tool_call blocks the
            # model emitted belong in the dedicated "Tool output" section, not the main
            # bubble. The structured calls + results are preserved (eye_dialogue +
            # tool_output), so this only strips the raw protocol text from the prose.
            ai_content = self._strip_tool_call_blocks(ai_content)

            # Persist the full Eye<->LLM transcript ONTO this turn's final
            # assistant message so the "Show the Eye's thinking" dropdown
            # survives close/reopen for EVERY message — not just the last.
            # Stamped here (not at add_message) so `conversation` is complete
            # (it keeps accruing through synthesis + the reasoning trace). The
            # transcript lives only in metadata: the prompt builder renders
            # history from role/content, so it never enters the model context.
            # Compact per-turn tool-output list for the dedicated, collapsed-by-default
            # "🔧 Tool output" UI section — keeps the big raw results out of the main
            # chat bubble while staying one expand away.
            tool_output = self._build_tool_output(all_tool_results)
            try:
                hm = self.cm.history_manager
                with hm._lock:
                    for _msg in reversed(hm.history):
                        if _msg.get("role") == "assistant":
                            _md = _msg.setdefault("metadata", {})
                            if conversation:
                                _md["eye_dialogue"] = conversation
                            if tool_output:
                                _md["tool_output"] = tool_output
                            # Match the cleaned answer shown to the investigator so a
                            # reload never resurfaces the raw ```tool_call text.
                            _msg["content"] = ai_content
                            break
                hm.save_history()
            except Exception as _e:
                self.logger.debug(f"Attaching transcript/tool-output to assistant message skipped: {_e}")

            _data_viewers = self.cm._extract_data_viewers(all_tool_results)
            return {
                "response": ai_content,
                "data_viewer": _data_viewers[0] if _data_viewers else None,
                "data_viewers": _data_viewers,
                "action_chips": self.cm._generate_action_chips(user_query, llm_response, all_tool_results),
                "option_menu": final_option_menu,
                "eye_llm_conversation": conversation,
                "tool_output": tool_output,
                "gep_turn": gep_turn,
                "coverage": coverage,
                "error": None,
                "context_stats": self.cm.get_context_stats()
            }
            
        except ContextOverflowError as oe:
            self.logger.warning(f"Over-context payload: {oe}")
            # Auto-recovery BEFORE refusing: if a re-runnable query is the bloat
            # source, analyze it in full via sealed map-reduce and answer from
            # that, instead of handing the investigator a refusal. Best-effort;
            # uses whichever of these locals exist at the point of overflow.
            _recovered = self._overflow_auto_map_reduce(
                locals().get("ledger_entries", []),
                user_query,
                locals().get("reasoning_cfg", {}) or {},
                emit_step,
            )
            if _recovered is not None:
                # Per-step GEP compliance: the recovery produced a real
                # evidence-bearing answer (sealed full-dataset map-reduce), so it
                # must leave a record like any other answered turn. Best-effort.
                try:
                    _gep_rec = self._evaluate_gep_turn(
                        user_query, _recovered.get("response", ""),
                        locals().get("all_tool_results", []) or [], None,
                        locals().get("checklist"))
                    self._persist_gep_turn(_gep_rec)
                except Exception as _e:
                    self.logger.debug(f"GEP overflow-recovery evaluation skipped: {_e}")
                return _recovered
            # FAIL HARD, never silently truncate. Refuse and tell the
            # investigator how to proceed so the chain of custody stays intact.
            usable = oe.max_context - oe.reserve
            refusal = (
                "**The evidence is too large to read in one pass — even after automatic compaction.**\n\n"
                f"The irreducible evidence core ({oe.payload_tokens:,} tokens) still exceeds what this "
                f"model can safely read ({usable:,} usable of {oe.max_context:,}). I auto-summarized and "
                "trimmed the non-evidence context but will **not** silently drop the evidence itself.\n\n"
                "**Recommended:** re-run this as **`analyze_large_dataset`** (map-reduce) — it analyzes the "
                "full artifact in sealed, token-sized chunks so nothing is dropped.\n"
                "Alternatively: narrow the query (tighter time range / specific user or path / a `LIMIT`), "
                "or switch to a model with a larger context window."
            )
            # Per-step GEP compliance: a fail-hard refusal IS the GEP-mandated
            # defensible action — record it so the trail isn't blank for the very
            # step where the Eye was most protocol-correct. Best-effort.
            try:
                self._persist_gep_turn(self._evaluate_gep_refusal(user_query, "context_overflow"))
            except Exception as _e:
                self.logger.debug(f"GEP refusal evaluation skipped: {_e}")
            return {
                "response": refusal,
                "error": "context_overflow",
                "context_stats": self.cm.get_context_stats(),
            }
        except Exception as e:
            self.logger.error(f"Investigation pipeline failed: {e}", exc_info=True)
            emit_step("thinking", "Investigation failed", "error", detail=str(e))
            return {
                "response": "", "error": f"Internal investigation error: {str(e)}", "context_stats": self.cm.get_context_stats()
            }

    def _persist_step(self, step: Dict[str, Any], user_query: str) -> None:
        """Append a pipeline step to the per-case step log so the Compliance
        panel can render a grouped, timestamped execution history.

        Written as JSON-lines to ``<case>/EYE_Logs/eye_step_log.jsonl`` (same
        EYE_Logs convention used by ReportEngine.save_report). No-ops silently
        when there is no active case directory.
        """
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_step_log.jsonl")
        entry = dict(step)
        entry["query"] = user_query
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _persist_dialogue(self, entry: Dict[str, Any], user_query: str) -> None:
        """Append one Eye<->LLM conversation entry to the per-case dialogue log
        so the full exchange (prompts, reasoning, tool calls + results) can be
        reviewed in the Compliance panel.

        Written as JSON-lines to ``<case>/EYE_Logs/eye_dialogue_log.jsonl``.
        No-ops silently when there is no active case directory.
        """
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_dialogue_log.jsonl")
        record = dict(entry)
        record["query"] = user_query
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    # Investigative (read) tools whose use signals proactive investigation.
    _INVESTIGATIVE_TOOLS = {
        "query_database", "search_artifacts", "query_correlation_results",
        "list_case_files", "get_schema", "query_threat_intel",
        "query_living_off_the_land_intel",
    }
    _TIMESTAMP_RE = re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"          # ISO-ish 2024-03-12 14:02
        r"|\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|UTC)"  # 10:42 PM / 14:02 UTC
    )

    @staticmethod
    def _tool_succeeded(r: Dict[str, Any]) -> bool:
        """A tool result counts as successful when neither the executor wrapper
        nor the handler payload reported failure."""
        if not r.get("success", False):
            return False
        inner = r.get("result")
        if isinstance(inner, dict) and inner.get("success") is False:
            return False
        return True

    def _evaluate_gep_turn(self, user_query, ai_content, all_tool_results, coverage=None, checklist=None):
        """Evaluate the objectively-checkable BEHAVIORAL GEP rules for one
        answered turn so the investigator can confirm, per answer, that the Eye
        followed the protocol. Returns a record with per-rule PASS/FAIL/N-A.

        ``coverage`` (optional, from ``_emit_coverage``) drives the GEP-6
        Completeness & Coverage check: it discloses which databases were
        consulted vs. available and whether any result was a sample, and flags
        (PARTIAL) when a sample stood in for the full set with no map-reduce.
        """
        ai_content = ai_content or ""
        investigative = [r for r in all_tool_results
                         if (r.get("tool_name") or "") in self._INVESTIGATIVE_TOOLS]
        investigative_ok = [r for r in investigative if self._tool_succeeded(r)]
        report_ok = [r for r in all_tool_results
                     if (r.get("tool_name") or "").startswith("report_") and self._tool_succeeded(r)]
        evidence_present = bool(investigative_ok)

        checks = []

        # GEP-10 (Defensibility) — Direct Answer: a substantive chat answer must exist.
        substantive = len(ai_content.strip()) >= 40
        checks.append({
            "id": "GEP-10", "name": "Direct Answer (GEP-10)",
            "status": "PASS" if substantive else "FAIL",
            "detail": f"chat answer is {len(ai_content.strip())} chars"
                      if substantive else "no substantive chat answer produced",
        })

        # GEP-7 — Dual Output: an evidence-bearing turn must also persist a report_* block.
        if not evidence_present:
            checks.append({"id": "GEP-7", "name": "Dual Output (GEP-7)", "status": "N-A",
                           "detail": "no forensic evidence produced this turn"})
        elif report_ok:
            checks.append({"id": "GEP-7", "name": "Dual Output (GEP-7)", "status": "PASS",
                           "detail": f"evidence answered in chat AND {len(report_ok)} report block(s) persisted"})
        else:
            checks.append({"id": "GEP-7", "name": "Dual Output (GEP-7)", "status": "FAIL",
                           "detail": "evidence produced but no report_* block was persisted"})

        # GEP-3 — Specificity & Chronology: an evidence turn cites timestamps.
        if not evidence_present:
            checks.append({"id": "GEP-3", "name": "Specificity & Chronology (GEP-3)", "status": "N-A",
                           "detail": "no evidence requiring timestamps this turn"})
        else:
            blob = ai_content + " " + " ".join(str(r.get("result", "")) for r in investigative_ok)
            has_ts = bool(self._TIMESTAMP_RE.search(blob))
            checks.append({"id": "GEP-3", "name": "Specificity & Chronology (GEP-3)",
                           "status": "PASS" if has_ts else "PARTIAL",
                           "detail": "timestamps present in answer/evidence" if has_ts
                                     else "evidence present but no explicit timestamp detected"})

        # GEP-1 (Evidence Primacy) — Proactive: at least one investigative tool was run.
        if investigative:
            checks.append({"id": "GEP-1", "name": "Proactive Investigation (GEP-1)", "status": "PASS",
                           "detail": f"{len(investigative)} investigative tool call(s): "
                                     + ", ".join(sorted({r.get('tool_name') for r in investigative}))})
        else:
            checks.append({"id": "GEP-1", "name": "Proactive Investigation (GEP-1)", "status": "N-A",
                           "detail": "conversational/no-evidence turn; no database search required"})

        # GEP-6 (Completeness & Coverage) — disclose which databases were consulted
        # vs. available and whether any result was a SAMPLE rather than the full
        # set. Disclose-and-grade: PARTIAL when a sample stood in for the whole set
        # with no full (map-reduce) analysis — the real silent-omission risk — else
        # PASS; the detail always discloses the coverage so the investigator can
        # judge. N-A on conversational turns or when coverage wasn't computed.
        if not investigative or not isinstance(coverage, dict):
            checks.append({"id": "GEP-6", "name": "Completeness & Coverage (GEP-6)", "status": "N-A",
                           "detail": "no evidence turn / coverage not computed"})
        else:
            consulted = coverage.get("consulted", []) or []
            not_consulted = coverage.get("not_consulted", []) or []
            sampled = bool(coverage.get("sampled"))
            ran_full = any(self._tool_succeeded(r) for r in all_tool_results
                           if (r.get("tool_name") or "") == "analyze_large_dataset")
            parts = []
            if consulted:
                parts.append("consulted: " + ", ".join(consulted))
            if not_consulted:
                parts.append("NOT consulted: " + ", ".join(not_consulted))
            if sampled:
                parts.append("a result was a SAMPLE"
                             + ("" if ran_full else " — full set NOT analyzed (use analyze_large_dataset)"))
            detail = "; ".join(parts) if parts else "all available databases consulted; no sampled results"
            status = "PARTIAL" if (sampled and not ran_full) else "PASS"
            checks.append({"id": "GEP-6", "name": "Completeness & Coverage (GEP-6)",
                           "status": status, "detail": detail})

        # GEP-2 (Traceability) — every fact links to a specific source record.
        if not evidence_present:
            checks.append({"id": "GEP-2", "name": "Traceability (GEP-2)", "status": "N-A",
                           "detail": "no factual evidence to trace this turn"})
        else:
            try:
                refs = EvidenceSeal.extract_evidence_refs(all_tool_results) or []
            except Exception:
                refs = []
            if refs:
                checks.append({"id": "GEP-2", "name": "Traceability (GEP-2)", "status": "PASS",
                               "detail": f"{len(refs)} source provenance handle(s) (database:table:row / sql)"})
            else:
                checks.append({"id": "GEP-2", "name": "Traceability (GEP-2)", "status": "PARTIAL",
                               "detail": "evidence produced but no provenance handle derivable"})

        # GEP-4 (Cross-Corroboration) — conclusions rest on ≥2 sources; single-source flagged.
        if not evidence_present or not isinstance(coverage, dict):
            checks.append({"id": "GEP-4", "name": "Cross-Corroboration (GEP-4)", "status": "N-A",
                           "detail": "no multi-source evidence to corroborate this turn"})
        else:
            sources = sorted({s for s in (coverage.get("consulted") or []) if s})
            if len(sources) >= 2:
                checks.append({"id": "GEP-4", "name": "Cross-Corroboration (GEP-4)", "status": "PASS",
                               "detail": f"{len(sources)} sources consulted: " + ", ".join(sources)})
            else:
                checks.append({"id": "GEP-4", "name": "Cross-Corroboration (GEP-4)", "status": "PARTIAL",
                               "detail": "single-source turn — GEP-4 flags single-source claims; corroborate with another artifact"})

        # GEP-5 (Premise Verification) — asserted premises get an explicit verdict.
        premises = [c for c in (checklist or []) if c.get("kind") == "premise"]
        if not premises:
            checks.append({"id": "GEP-5", "name": "Premise Verification (GEP-5)", "status": "N-A",
                           "detail": "no asserted premises to verify this turn"})
        else:
            resolved = [c for c in premises if c.get("status") == "answered"]
            if len(resolved) == len(premises):
                checks.append({"id": "GEP-5", "name": "Premise Verification (GEP-5)", "status": "PASS",
                               "detail": f"all {len(premises)} asserted premise(s) tested with a verdict"})
            elif resolved:
                checks.append({"id": "GEP-5", "name": "Premise Verification (GEP-5)", "status": "PARTIAL",
                               "detail": f"{len(resolved)}/{len(premises)} asserted premise(s) resolved"})
            else:
                checks.append({"id": "GEP-5", "name": "Premise Verification (GEP-5)", "status": "FAIL",
                               "detail": f"{len(premises)} premise(s) asserted but none verified"})

        # GEP-8 (Transparency) — tool calls are traced + logged and LLM-visible.
        if all_tool_results:
            checks.append({"id": "GEP-8", "name": "Transparency (GEP-8)", "status": "PASS",
                           "detail": f"{len(all_tool_results)} tool call(s) traced + logged (steps/dialogue/seals)"})
        else:
            checks.append({"id": "GEP-8", "name": "Transparency (GEP-8)", "status": "N-A",
                           "detail": "conversational turn; reasoning still streamed + logged"})

        # GEP-9 (Human Authority) — durable authored actions are attributable.
        write_tools = [r for r in all_tool_results
                       if (r.get("tool_name") or "").startswith(("correlation_create", "correlation_edit"))]
        if not write_tools:
            checks.append({"id": "GEP-9", "name": "Human Authority (GEP-9)", "status": "N-A",
                           "detail": "read-only investigation; no durable authored artifacts this turn"})
        else:
            write_ok = [r for r in write_tools if self._tool_succeeded(r)]
            if len(write_ok) == len(write_tools):
                checks.append({"id": "GEP-9", "name": "Human Authority (GEP-9)", "status": "PASS",
                               "detail": f"{len(write_ok)} authored artifact(s) — reason + evidence + Eye-stamp enforced"})
            else:
                checks.append({"id": "GEP-9", "name": "Human Authority (GEP-9)", "status": "PARTIAL",
                               "detail": f"{len(write_ok)}/{len(write_tools)} authoring action(s) succeeded"})

        passed = sum(1 for c in checks if c["status"] == "PASS")
        gradable = sum(1 for c in checks if c["status"] in ("PASS", "FAIL", "PARTIAL"))
        return {
            "query": user_query,
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "summary": f"{passed}/{gradable} behavioral GEP rules PASS" if gradable else "no gradable rules this turn",
        }

    def _evaluate_gep_triage(self, consulted, expected, blocks_added, response):
        """Grade the DETERMINISTIC automated triage (initialize_case_report) against
        the 10 GEP principles so the most evidence-heavy step also leaves a per-step
        compliance record in the trail. The triage runs no agentic tool calls, so —
        unlike ``_evaluate_gep_turn`` — this grades the triage's real behavior
        directly (databases resolved + report blocks persisted) with NO fabricated
        tool-result dicts. Returns the same record shape so ``_persist_gep_turn`` and
        the Compliance panel consume it identically.

        ``consulted`` = canonical case-DB filenames that resolved; ``expected`` = the
        full canonical artifact set the triage looks for; ``blocks_added`` = number
        of report blocks persisted this pass; ``response`` = the chat completion text.
        """
        consulted = sorted({d for d in (consulted or []) if d})
        expected = sorted({d for d in (expected or []) if d})
        not_consulted = sorted(set(expected) - set(consulted))
        blocks_added = int(blocks_added or 0)
        response = response or ""
        evidence = bool(consulted) and blocks_added > 0

        checks = []

        # GEP-10 (Defensibility) — Direct Answer: a substantive completion summary.
        substantive = len(response.strip()) >= 40
        checks.append({
            "id": "GEP-10", "name": "Direct Answer (GEP-10)",
            "status": "PASS" if substantive else "FAIL",
            "detail": f"triage completion summary is {len(response.strip())} chars"
                      if substantive else "no substantive triage summary produced",
        })

        # GEP-1 (Evidence Primacy) — Proactive: case databases were queried.
        if consulted:
            checks.append({"id": "GEP-1", "name": "Proactive Investigation (GEP-1)", "status": "PASS",
                           "detail": f"proactively queried {len(consulted)} case database(s): "
                                     + ", ".join(consulted)})
        else:
            checks.append({"id": "GEP-1", "name": "Proactive Investigation (GEP-1)", "status": "N-A",
                           "detail": "no case databases resolved for this collection"})

        # GEP-7 — Dual Output: chat summary AND persisted report block(s).
        if not evidence:
            checks.append({"id": "GEP-7", "name": "Dual Output (GEP-7)", "status": "N-A",
                           "detail": "no forensic evidence persisted this triage pass"})
        else:
            checks.append({"id": "GEP-7", "name": "Dual Output (GEP-7)", "status": "PASS",
                           "detail": f"triage summarized in chat AND {blocks_added} report block(s) persisted"})

        # GEP-2 (Traceability) — every persisted triage block stores its source SQL.
        if not evidence:
            checks.append({"id": "GEP-2", "name": "Traceability (GEP-2)", "status": "N-A",
                           "detail": "no factual evidence to trace this triage pass"})
        else:
            checks.append({"id": "GEP-2", "name": "Traceability (GEP-2)", "status": "PASS",
                           "detail": f"{blocks_added} report block(s) each store the source SQL query"})

        # GEP-3 (Specificity & Chronology) — triage indexes timestamped events.
        if not evidence:
            checks.append({"id": "GEP-3", "name": "Specificity & Chronology (GEP-3)", "status": "N-A",
                           "detail": "no evidence requiring timestamps this triage pass"})
        else:
            checks.append({"id": "GEP-3", "name": "Specificity & Chronology (GEP-3)", "status": "PASS",
                           "detail": "security/execution events indexed with their event timestamps"})

        # GEP-6 (Completeness & Coverage) — disclose consulted vs absent artifact DBs.
        if not expected:
            checks.append({"id": "GEP-6", "name": "Completeness & Coverage (GEP-6)", "status": "N-A",
                           "detail": "coverage not computed for this triage pass"})
        else:
            parts = []
            if consulted:
                parts.append("consulted: " + ", ".join(consulted))
            if not_consulted:
                parts.append("NOT present: " + ", ".join(not_consulted))
            checks.append({"id": "GEP-6", "name": "Completeness & Coverage (GEP-6)",
                           "status": "PASS" if consulted else "PARTIAL",
                           "detail": "; ".join(parts) if parts else "no expected artifact databases present"})

        # GEP-4 (Cross-Corroboration) — triage spans multiple artifact sources.
        if not consulted:
            checks.append({"id": "GEP-4", "name": "Cross-Corroboration (GEP-4)", "status": "N-A",
                           "detail": "no sources consulted to corroborate this triage pass"})
        elif len(consulted) >= 2:
            checks.append({"id": "GEP-4", "name": "Cross-Corroboration (GEP-4)", "status": "PASS",
                           "detail": f"{len(consulted)} artifact sources indexed for cross-corroboration"})
        else:
            checks.append({"id": "GEP-4", "name": "Cross-Corroboration (GEP-4)", "status": "PARTIAL",
                           "detail": "single-source triage — corroborate with another artifact"})

        # GEP-8 (Transparency) — every triage category traced + persisted.
        if evidence:
            checks.append({"id": "GEP-8", "name": "Transparency (GEP-8)", "status": "PASS",
                           "detail": f"{blocks_added} triage block(s) traced via steps + persisted to the report"})
        else:
            checks.append({"id": "GEP-8", "name": "Transparency (GEP-8)", "status": "N-A",
                           "detail": "no persisted triage artifacts to trace this pass"})

        # GEP-5 (Premise Verification) / GEP-9 (Human Authority) — not applicable:
        # the triage asserts no premises and authors no durable (correlation) artifacts.
        checks.append({"id": "GEP-5", "name": "Premise Verification (GEP-5)", "status": "N-A",
                       "detail": "automated triage asserts no premises to verify"})
        checks.append({"id": "GEP-9", "name": "Human Authority (GEP-9)", "status": "N-A",
                       "detail": "read-only triage; no durable authored artifacts"})

        passed = sum(1 for c in checks if c["status"] == "PASS")
        gradable = sum(1 for c in checks if c["status"] in ("PASS", "FAIL", "PARTIAL"))
        return {
            "query": "initialize_case_report",
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "summary": f"{passed}/{gradable} behavioral GEP rules PASS" if gradable else "no gradable rules this turn",
        }

    def _evaluate_gep_refusal(self, user_query, reason=""):
        """Grade a fail-hard REFUSAL turn so the compliance trail records the step
        where the Eye was *most* protocol-correct: refusing to read/answer rather
        than silently truncating evidence preserves the chain of custody, which is
        exactly GEP-10 (Defensibility). A refusal is not an answered turn, so —
        unlike ``_evaluate_gep_turn`` — this does NOT grade dual-output/timestamps
        (there is deliberately no answer/evidence to grade). Same record shape so
        ``_persist_gep_turn`` and the Compliance panel consume it identically.
        """
        why = (reason or "").strip()
        checks = [{
            "id": "GEP-10", "name": "Direct Answer (GEP-10)", "status": "PASS",
            "detail": "fail-hard refusal — refused rather than silently truncate evidence; "
                      "chain of custody preserved"
                      + (f" (reason: {why})" if why else ""),
        }]
        for gid, name in (
            ("GEP-1", "Proactive Investigation (GEP-1)"),
            ("GEP-2", "Traceability (GEP-2)"),
            ("GEP-3", "Specificity & Chronology (GEP-3)"),
            ("GEP-4", "Cross-Corroboration (GEP-4)"),
            ("GEP-5", "Premise Verification (GEP-5)"),
            ("GEP-6", "Completeness & Coverage (GEP-6)"),
            ("GEP-7", "Dual Output (GEP-7)"),
            ("GEP-8", "Transparency (GEP-8)"),
            ("GEP-9", "Human Authority (GEP-9)"),
        ):
            checks.append({"id": gid, "name": name, "status": "N-A",
                           "detail": "turn refused to preserve chain of custody; nothing to grade"})

        passed = sum(1 for c in checks if c["status"] == "PASS")
        gradable = sum(1 for c in checks if c["status"] in ("PASS", "FAIL", "PARTIAL"))
        return {
            "query": user_query,
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "summary": f"{passed}/{gradable} behavioral GEP rules PASS" if gradable else "no gradable rules this turn",
        }

    def _persist_gep_turn(self, record: Dict[str, Any]) -> None:
        """Append a per-answer GEP evaluation to EYE_Logs/eye_gep_turns.jsonl so
        the Compliance panel can show, per question, whether GEP was followed."""
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_gep_turns.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _parse_reasoning(raw: str) -> Optional[Dict[str, Any]]:
        """Pull the first JSON object out of the reasoning-trace model output, or
        None on any failure (caller then logs a decomposition-only fallback)."""
        if not raw:
            return None
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _norm_evidence(ev: Any) -> List[Dict[str, str]]:
        """Normalize an evidence list (strings or {ref,note} objects) to a list of
        {ref, note} dicts; drops empties. Tolerant of malformed model output."""
        out: List[Dict[str, str]] = []
        if not isinstance(ev, list):
            return out
        for item in ev:
            if isinstance(item, dict):
                ref = str(item.get("ref") or item.get("reference") or "").strip()
                note = str(item.get("note") or item.get("detail") or "").strip()
            else:
                ref, note = str(item).strip(), ""
            if ref or note:
                out.append({"ref": ref, "note": note})
        return out

    def _capture_reasoning_trace(self, user_query, checklist, ledger_entries, final_answer,
                                 guarded_generate, emit_step, emit_dialogue,
                                 strategy: str = "", knowledge_consulted=None) -> Optional[Dict[str, Any]]:
        """Capture WHY each sub-question was created and WHY each conclusion
        follows from which evidence, for the Compliance UI (GEP-8 Transparency,
        GEP-2 Traceability).

        One tool-less call routed through ``guarded_generate(phase="reasoning")``
        so it is SEALED and runs at planning temperature. It is given the
        sub-questions (+their 'why'), the evidence ledger (real
        database:table:rowid provenance) and the final answer, and must ground
        its output STRICTLY in the provided ledger (cite only ledger refs, never
        invent). Best-effort: on any failure it falls back to a decomposition-only
        record so the 'why each sub-question' rationale is still surfaced.
        NEVER raises into the pipeline.
        """
        subq_items = [c for c in checklist if c.get("kind") != "premise"]
        prem_items = [c for c in checklist if c.get("kind") == "premise"]
        ledger_text = self._build_evidence_ledger(ledger_entries) or "(no tool calls this turn)"
        _ans = (final_answer or "").strip()
        _ans = (_ans[:4000] + "…") if len(_ans) > 4000 else _ans

        sub_lines = "\n".join(
            f'  sq{i+1}: {c.get("q","")}' + (f'  (why: {c.get("why","")})' if c.get("why") else "")
            for i, c in enumerate(subq_items)
        )
        prem_lines = "\n".join(
            f'  p{i+1}: {c.get("q","")[8:] if c.get("q","").startswith("verify: ") else c.get("q","")}'
            for i, c in enumerate(prem_items)
        )

        reasoning_system = (
            "You are the reasoning-audit unit of a forensic investigation assistant. "
            "Explain the investigation that ALREADY happened. Ground every statement "
            "STRICTLY in the EVIDENCE LEDGER provided — cite only refs that appear "
            "there; NEVER invent evidence. Output ONLY a compact JSON object, no prose, "
            "no code fences."
        )
        reasoning_prompt = (
            "Return a JSON object with keys:\n"
            '  "sub_questions": array, one object per sub-question below, in order: '
            '{"id":"sq1","conclusion":"<the conclusion reached, declarative>","why_concluded":"<why this '
            'conclusion follows from the evidence>","behaviors":[{"claim":"<one specific behavior that '
            'was established, declarative, e.g. \'wrote a Run registry key for persistence\'>","why":"<why '
            'this behavior follows from the evidence>","evidence":[{"ref":"db:table:rowid","note":"..."}]}],'
            '"evidence":[{"ref":"db:table:rowid","note":"..."}],'
            '"status":"answered|inconclusive"}. Each behavior is a discrete, evidence-backed fact that '
            'helps establish the conclusion; omit behaviors you cannot ground in the ledger.\n'
            '  "premises": array, one object per premise: {"verdict":"CONFIRMED|REFUTED|INCONCLUSIVE",'
            '"why":"...","evidence":[...]}.\n'
            '  "consolidation": one or two sentences on how the sub-answers correlate into the final conclusion.\n\n'
            f"MAIN QUESTION:\n{user_query}\n\n"
            f"SUB-QUESTIONS:\n{sub_lines or '  (none)'}\n\n"
            f"PREMISES:\n{prem_lines or '  (none)'}\n\n"
            f"EVIDENCE LEDGER (the only allowed source of evidence refs):\n{ledger_text}\n\n"
            f"FINAL ANSWER (already given to the investigator):\n{_ans}\n\n"
            "Return ONLY the JSON object."
        )

        data = None
        try:
            emit_step("thinking", "Recording reasoning trace (why each sub-question + conclusion)", "active")
            emit_dialogue({
                "phase": "reasoning_request", "iteration": 0,
                "system_prompt": reasoning_system, "user_message": reasoning_prompt,
                "tools_offered": [], "history_count": 0,
            })
            resp = guarded_generate(reasoning_system, reasoning_prompt, [], None,
                                    phase="reasoning", iteration=0)
            raw = (resp.get("content") or "").strip()
            emit_dialogue({"phase": "reasoning_response", "iteration": 0, "content": raw, "tool_calls": []})
            data = self._parse_reasoning(raw)
            emit_step("thinking", "Reasoning trace recorded", "done")
        except ContextOverflowError:
            self.logger.debug("Reasoning trace pass overflowed; logging decomposition-only record.")
        except Exception as e:
            self.logger.debug(f"Reasoning trace pass failed; logging decomposition-only record: {e}")

        model_subs = (data or {}).get("sub_questions") or []
        model_prems = (data or {}).get("premises") or []

        out_subs = []
        for i, c in enumerate(subq_items):
            msub = model_subs[i] if i < len(model_subs) and isinstance(model_subs[i], dict) else {}
            behaviors = []
            for b in (msub.get("behaviors") or []):
                if not isinstance(b, dict):
                    continue
                claim = str(b.get("claim", "")).strip()
                if not claim:
                    continue
                behaviors.append({
                    "claim": claim,
                    "why": str(b.get("why", "")).strip(),
                    "evidence": self._norm_evidence(b.get("evidence")),
                })
            out_subs.append({
                "id": f"sq{i+1}",
                "q": c.get("q", ""),
                "why_created": c.get("why", "") or str(msub.get("why_created", "")).strip(),
                "conclusion": str(msub.get("conclusion", "")).strip(),
                "why_concluded": str(msub.get("why_concluded", "")).strip(),
                "behaviors": behaviors,
                "evidence": self._norm_evidence(msub.get("evidence")),
                "status": str(msub.get("status", "")).strip()
                          or ("answered" if c.get("status") == "answered" else "inconclusive"),
            })

        out_prems = []
        for i, c in enumerate(prem_items):
            q = c.get("q", "")
            claim = q[8:] if q.startswith("verify: ") else q
            mp = model_prems[i] if i < len(model_prems) and isinstance(model_prems[i], dict) else {}
            out_prems.append({
                "claim": claim,
                "verdict": str(mp.get("verdict", "INCONCLUSIVE")).strip().upper() or "INCONCLUSIVE",
                "why": str(mp.get("why", "")).strip(),
                "evidence": self._norm_evidence(mp.get("evidence")),
            })

        return {
            "query": user_query,
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy or str((data or {}).get("strategy", "")).strip(),
            "sub_questions": out_subs,
            "premises": out_prems,
            "consolidation": str((data or {}).get("consolidation", "")).strip(),
            "knowledge_consulted": list(knowledge_consulted or (data or {}).get("knowledge_consulted") or []),
        }

    def _persist_reasoning_turn(self, record: Dict[str, Any], user_query: str) -> None:
        """Append a reasoning trace to EYE_Logs/eye_reasoning_log.jsonl so the
        Compliance panel can show how each question was decomposed and concluded."""
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_reasoning_log.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _audit_event(self, action: str, reason: str = "", metadata: Optional[Dict] = None) -> None:
        """Write one Chain-of-Custody event (RETRY / SEGMENTED / AUTO_MAPREDUCE)
        to the truncation auditor so the Compliance panel surfaces the automatic
        resilience actions. Best-effort: never raises into the pipeline."""
        auditor = getattr(self.cm, "truncation_auditor", None)
        if not auditor:
            return
        try:
            payload = f"{action}|{reason}|{json.dumps(metadata or {}, default=str, sort_keys=True)}"
            auditor.log_event(
                action=action,
                message_id=f"{action.lower()}-{int(time.time() * 1000)}",
                token_count=0,
                reason=reason,
                message_hash=EvidenceSeal._sha256(payload),
                metadata=metadata or {},
            )
        except Exception as e:
            self.logger.debug(f"audit event {action} skipped: {e}")

    def _maybe_auto_map_reduce(self, call, result, question, reasoning_cfg, emit_step):
        """Transparent auto map-reduce: when a `query_database` call returns a
        very large result, analyze ALL rows via the (sealed) map-reduce service
        and feed the model the consolidated summary instead of a sample — so big
        reads are answered completely and automatically. Falls back to the
        original result on any failure. Visible via emit_step + AUTO_MAPREDUCE."""
        try:
            if not reasoning_cfg.get("enable_auto_map_reduce", False):
                return result
            if (call.get("name") != "query_database") or not result.get("success"):
                return result
            inner = result.get("result") if isinstance(result.get("result"), dict) else {}
            threshold = int(reasoning_cfg.get("auto_map_reduce_row_threshold", 1500))
            row_count = inner.get("row_count") or 0
            full_rows = inner.get("full_rows") or inner.get("data") or []
            if not isinstance(row_count, int) or row_count < threshold or len(full_rows) < threshold:
                return result
            params = call.get("parameters", {}) or {}
            db = inner.get("database_name") or params.get("database_name")
            sql = inner.get("sql_query") or params.get("sql_query")
            if not db or not sql:
                return result

            emit_step("tool_call",
                      f"Large result ({row_count} rows) — auto map-reduce over ALL rows", "active")
            from eye.services.map_reduce_service import MapReduceService
            mr = MapReduceService(self.cm).analyze(
                db, sql, instruction=question, prefetched_rows=full_rows
            )
            if not mr.get("success"):
                return result
            self._audit_event(
                "AUTO_MAPREDUCE", reason="large_query_result",
                metadata={"database": db, "rows": row_count, "chunks": mr.get("chunks_processed")},
            )
            emit_step("tool_call",
                      f"Auto map-reduce complete: {mr.get('chunks_processed')} sealed segment(s) over {row_count} rows",
                      "done")
            new_inner = {
                "success": True,
                "database_name": db,
                "sql_query": sql,
                "row_count": row_count,
                "columns": inner.get("columns", []),
                "full_rows": full_rows,          # kept for the report / data viewer
                "auto_map_reduced": True,
                "summary": mr.get("summary"),
                "note": (f"Result had {row_count} rows — analyzed IN FULL via "
                         f"{mr.get('chunks_processed')} sealed map-reduce segment(s). The summary "
                         "below covers ALL rows; do not treat it as a sample."),
            }
            return {"tool_name": "query_database", "success": True,
                    "result": new_inner, "auto_map_reduced": True}
        except Exception as e:
            self.logger.error(f"Auto map-reduce skipped (fell back to sampled result): {e}")
            return result

    def _overflow_auto_map_reduce(self, ledger_entries, question, reasoning_cfg, emit_step):
        """Overflow safety net: when the assembled payload can't fit even after
        self-heal, instead of refusing, find the most recent re-runnable
        `query_database` in the ledger and map-reduce it (sealed), returning a
        consolidated answer. Returns a normal response dict, or None to fall
        through to the existing fail-hard refusal."""
        try:
            if not reasoning_cfg.get("enable_auto_map_reduce", False):
                return None
            cand = None
            for e in reversed(ledger_entries or []):
                if e.get("tool") == "query_database":
                    res = e.get("result") or {}
                    params = e.get("params") or {}
                    sql = res.get("sql_query") or params.get("sql_query")
                    db = res.get("database_name") or params.get("database_name")
                    if sql and db:
                        cand = (db, sql)
                        break
            if not cand:
                return None
            db, sql = cand
            emit_step("synthesis",
                      "Evidence too large to read in one pass — auto map-reducing the dataset instead of refusing",
                      "active")
            from eye.services.map_reduce_service import MapReduceService
            mr = MapReduceService(self.cm).analyze(db, sql, instruction=question)
            if not mr.get("success"):
                return None
            self._audit_event(
                "AUTO_MAPREDUCE", reason="overflow_recovery",
                metadata={"database": db, "chunks": mr.get("chunks_processed")},
            )
            answer = (
                "The evidence was too large to read in one pass, so I analyzed the FULL dataset "
                f"in {mr.get('chunks_processed')} sealed map-reduce segment(s):\n\n{mr.get('summary')}"
            )
            try:
                self.cm.history_manager.add_message("assistant", answer)
                if self.cm.case_directory:
                    self.cm.history_manager.save_history()
            except Exception:
                pass
            emit_step("synthesis", "Auto map-reduce recovery complete", "done")
            return {"response": answer, "error": None, "context_stats": self.cm.get_context_stats()}
        except Exception as e:
            self.logger.error(f"Overflow auto map-reduce recovery failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Investigation planning: decomposition + premise extraction (v0.11.1)
    # ------------------------------------------------------------------
    # Signals that a query is genuinely multi-part (worth decomposing).
    _MULTIPART_SIGNALS = (
        " and ", " and then", " then ", " also ", " as well as ", " plus ",
        "; ", " & ",
    )
    # Verb/claim signals that a message ASSERTS a fact (worth premise-checking),
    # e.g. "prefetch is auto-deleted", "teamviewer was installed".
    _ASSERTION_SIGNALS = (
        " is ", " are ", " was ", " were ", " isn't", " aren't", " wasn't",
        " deletes", " deleted", " removes", " removed", " installed", " ran ",
        " runs ", " executed", " created", " modified", " auto-", " always ",
        " never ", " cannot ", " can't", " doesn't", " does not", " did not",
        " didn't", " happened", " must have",
    )

    # Greeting / chit-chat openers that never warrant a planning model-call.
    _GREETING_TOKENS = {
        "hi", "hii", "hello", "hey", "yo", "thanks", "thank", "thx", "ok",
        "okay", "cool", "nice", "great", "test", "ping", "sup",
    }

    @classmethod
    def _should_plan(cls, user_query: str) -> bool:
        """Cheap *trivial-skip* pre-filter — NOT the splitter.

        The LLM (``_plan_investigation``) decides whether and how to split a
        question into logical sub-questions; this only avoids spending a planner
        call on clearly trivial input. Returns ``False`` for empty text, a bare
        greeting, or a very short (<=3-word) plain lookup with no question /
        assertion / multi-part signal; ``True`` for everything substantive (the
        LLM then judges complexity and may return a single sub-question).
        """
        q = (user_query or "").strip()
        if not q:
            return False
        lc = " " + q.lower() + " "
        words = q.split()
        has_signal = (
            "?" in q
            or any(sig in lc for sig in cls._MULTIPART_SIGNALS)
            or any(sig in lc for sig in cls._ASSERTION_SIGNALS)
        )
        # Short, signal-less input is treated as a trivial lookup / greeting.
        if len(words) <= 3 and not has_signal:
            return False
        # A 1-2 word bare greeting is trivial even if it sneaks a signal char.
        if len(words) <= 2 and q.lower().strip("?!. ") in cls._GREETING_TOKENS:
            return False
        return True

    @staticmethod
    def _parse_plan(raw: str, max_subq: int = 6) -> Optional[Dict[str, Any]]:
        """Parse the planning model output into a normalized plan dict, or None.

        Tolerant: pulls the first ``{...}`` JSON object out of any surrounding
        prose / code fences. Any failure returns None so the caller falls back
        to the current single-question behavior.
        """
        if not raw:
            return None
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        subs_raw = data.get("sub_questions") or []
        prems = data.get("user_premises") or []
        if not isinstance(subs_raw, list):
            subs_raw = []
        if not isinstance(prems, list):
            prems = []
        # Sub-questions: accept plain strings (legacy) OR {"q"/"question", "why"}
        # objects. Normalize to {"q","why"} so the rationale ("why this
        # sub-question") is captured for the Compliance UI.
        subs: List[Dict[str, str]] = []
        for s in subs_raw:
            if isinstance(s, dict):
                q = str(s.get("q") or s.get("question") or "").strip()
                why = str(s.get("why") or s.get("reason") or "").strip()
            else:
                q, why = str(s).strip(), ""
            if q:
                subs.append({"q": q, "why": why})
            if len(subs) >= max(1, int(max_subq)):
                break
        prems = [
            str(p).strip() for p in prems
            if str(p).strip() and str(p).strip().lower() not in ("null", "none", "n/a")
        ]
        return {
            "sub_questions": subs,
            "user_premises": prems,
            "related_prior": bool(data.get("related_prior", False)),
            "strategy": str(data.get("strategy") or "").strip(),
        }

    def _plan_investigation(self, user_query, guarded_generate, emit_step, emit_dialogue,
                            reasoning_cfg, prefer_segmentation: bool = True):
        """Lightweight, tool-less planning pre-pass.

        One model call (routed through ``guarded_generate`` so the payload is
        SEALED like every other call — chain of custody stays intact) where the
        LLM decides how to split the question into logical sub-questions and
        extracts any factual premises the investigator asserted (to
        prove/disprove). Returns a normalized plan dict, or None on any failure
        (caller treats the query as atomic). NEVER breaks the pipeline.

        ``prefer_segmentation`` selects the splitting instruction:
          - True (default): break the message into the minimal set of focused,
            logically-distinct sub-questions (the LLM judges complexity).
          - False: conservative — split only if it has multiple explicit parts.
        Either way the MODEL makes the split — there is no length/keyword rule.
        """
        max_subq = int(reasoning_cfg.get("max_sub_questions", 6))
        planning_system = (
            "You are the planning unit of a forensic investigation assistant. "
            "Output ONLY a compact JSON object, no prose, no code fences."
        )
        if prefer_segmentation:
            split_instruction = (
                '  "sub_questions": break the investigator\'s message into the MINIMAL set of '
                "FOCUSED, logically-distinct sub-questions needed to answer it fully. Split along "
                "LOGICAL/semantic boundaries — distinct artifacts, time ranges, entities, or "
                "claims — NEVER arbitrarily or by length. If it is already a single focused "
                "question, return a one-element array. EACH element is an object "
                '{"q": "<the sub-question>", "why": "<why this sub-question is needed to answer '
                'the main question>"}.\n'
            )
        else:
            split_instruction = (
                '  "sub_questions": array of the distinct sub-questions to investigate. '
                "Split ONLY if the message genuinely has multiple explicit parts; if it is a "
                "single question, return a one-element array. EACH element is an object "
                '{"q": "<the sub-question>", "why": "<why this sub-question is needed>"}.\n'
            )
        planning_prompt = (
            "Analyze the investigator's message and return a JSON object with keys:\n"
            + split_instruction +
            '  "strategy": one short sentence describing your overall decomposition strategy.\n'
            '  "user_premises": array of any factual claims the investigator ASSERTS '
            "(about OS/system behavior or what happened) that must be PROVEN or DISPROVEN "
            "against artifacts. Empty array if none.\n"
            '  "related_prior": boolean — whether this likely relates to earlier questions in the case.\n'
            f"Cap sub_questions at {max_subq}. Return ONLY the JSON object.\n\n"
            f"Investigator message: {user_query}"
        )
        emit_step("thinking", "Planning investigation (decomposition + premise check)", "active")
        try:
            emit_dialogue({
                "phase": "planning_request", "iteration": 0,
                "system_prompt": planning_system, "user_message": planning_prompt,
                "tools_offered": [], "history_count": 0,
            })
            resp = guarded_generate(
                planning_system, planning_prompt, [], None,
                phase="planning", iteration=0,
            )
            raw = (resp.get("content") or "").strip()
            emit_dialogue({
                "phase": "planning_response", "iteration": 0,
                "content": raw, "tool_calls": [],
            })
            return self._parse_plan(raw, max_subq)
        except ContextOverflowError:
            # Planning is OPTIONAL — never abort the whole query because the
            # planning payload overflowed. Degrade to atomic; the main loop will
            # still fail-hard-refuse downstream if the real payload overflows.
            self.logger.debug("Planning pre-pass overflowed context; treating query as atomic.")
            return None
        except Exception as e:
            self.logger.debug(f"Planning pre-pass failed, treating query as atomic: {e}")
            return None

    def _plan_hierarchy(self, user_query, guarded_generate, emit_step, emit_dialogue, reasoning_cfg):
        """Plan the investigation as a CLAIM HIERARCHY, tool-less and sealed.

        Returns a normalized dict
        ``{"verdict": str, "narratives": [{"claim","why","sub_narratives":[
              {"claim","evidence_needed","tools":[...]}]}]}`` or ``None`` on any
        failure (caller falls back to the flat sub-question path). The model decides
        what to prove (verdict), the activities to prove it (narratives), and the
        specific evidence-bearing steps + which tools prove each (sub-narratives)."""
        max_nar = int(reasoning_cfg.get("max_narratives", 12))
        max_sub = int(reasoning_cfg.get("max_sub_narratives", 8))
        tool_names = sorted({(t.get("name") or "") for t in self.cm._get_tool_definitions()
                             if (t.get("name") or "") and not (t.get("name") or "").startswith("report_")})
        planning_system = (
            "You are the planning unit of a forensic investigation assistant. You decompose the "
            "investigator's goal into a claim hierarchy to PROVE. Output ONLY a compact JSON object, "
            "no prose, no code fences."
        )
        planning_prompt = (
            "Return a JSON object with keys:\n"
            '  "verdict": one sentence — the overall claim the investigation must PROVE or DISPROVE '
            "(what we are trying to establish).\n"
            '  "narratives": array of the distinct activities/behaviors we must prove to settle the '
            'verdict. EACH narrative is an object {"claim":"<the activity as a claim>","why":"<why it '
            'matters to the verdict>","sub_narratives":[ ... ]}.\n'
            '  Each sub_narrative is an object {"claim":"<a specific, evidence-bearing step/behavior>",'
            '"evidence_needed":"<the concrete artifact evidence that would prove it>","tools":["<tool>", ...]}.\n'
            "\nBe THOROUGH and SPECIFIC — a richer plan investigates better:\n"
            "- DECOMPOSE FULLY: cover every distinct angle needed to settle the verdict — each relevant "
            "artifact (SRUM, registry Run keys, services, prefetch, amcache, event logs, MFT/USN, "
            "network), time window, user/process/file identity, and any premise the investigator "
            "assumed. Prefer several focused narratives over one broad one.\n"
            "- CONCRETE SUB-NARRATIVES: each claim names a specific behavior, and evidence_needed names "
            "the concrete artifact / table / field / value that proves it (not a vague 'check logs').\n"
            "- CROSS-SOURCE TOOLS: for each sub_narrative list ALL tools whose results would corroborate "
            "it — e.g. `query_database` on the relevant artifact AND `query_correlation_results` AND a "
            "second artifact table — so the proof rests on multiple sources, not one. Use exact names.\n"
            "\nForensic artifacts available in this case — map each sub_narrative's evidence_needed to "
            "the artifact that holds its evidence, and choose the tools that read it:\n"
            + self._artifact_catalog_block() + "\n"
            "(e.g. execution → Prefetch/AmCache/ShimCache/SRUM; persistence → Registry Run keys; "
            "deletion → USN Journal/Recycle Bin/MFT; network → SRUM; file access → Jump Lists/LNK/ShellBags.)\n"
            f"\nAvailable tools (use these exact names): {', '.join(tool_names)}.\n"
            f"Use up to {max_nar} narratives and up to {max_sub} sub_narratives each — go deep enough to "
            "actually prove the verdict. Order them so the investigation flows logically. "
            "Return ONLY the JSON object.\n\n"
            f"Investigator goal: {user_query}"
        )
        emit_step("thinking", "Planning the investigation hierarchy (verdict → narratives → steps)", "active")
        try:
            emit_dialogue({
                "phase": "planning_request", "iteration": 0,
                "system_prompt": planning_system, "user_message": planning_prompt,
                "tools_offered": [], "history_count": 0,
            })
            resp = guarded_generate(planning_system, planning_prompt, [], None,
                                    phase="planning", iteration=0)
            raw = (resp.get("content") or "").strip()
            emit_dialogue({"phase": "planning_response", "iteration": 0, "content": raw, "tool_calls": []})
            return self._parse_hierarchy(raw, set(tool_names), max_nar, max_sub)
        except ContextOverflowError:
            self.logger.debug("Hierarchy planning overflowed context; falling back to flat path.")
            return None
        except Exception as e:
            self.logger.debug(f"Hierarchy planning failed, falling back to flat path: {e}")
            return None

    @staticmethod
    def _parse_hierarchy(raw: str, valid_tools: set, max_nar: int = 5, max_sub: int = 4):
        """Normalize the hierarchy-planner JSON into
        ``{"verdict","narratives":[{"claim","why","sub_narratives":[{"claim",
        "evidence_needed","tools"}]}]}`` — tool names clamped to ``valid_tools``.
        Returns None unless at least one narrative with one sub-narrative survives."""
        if not raw:
            return None
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        verdict = str(data.get("verdict") or "").strip()
        nars_raw = data.get("narratives") if isinstance(data.get("narratives"), list) else []
        narratives = []
        for n in nars_raw:
            if not isinstance(n, dict):
                continue
            n_claim = str(n.get("claim") or n.get("narrative") or "").strip()
            if not n_claim:
                continue
            subs = []
            for s in (n.get("sub_narratives") if isinstance(n.get("sub_narratives"), list) else []):
                if not isinstance(s, dict):
                    continue
                s_claim = str(s.get("claim") or "").strip()
                if not s_claim:
                    continue
                raw_tools = s.get("tools") if isinstance(s.get("tools"), list) else []
                tools = [str(t).strip() for t in raw_tools if str(t).strip() in valid_tools]
                subs.append({
                    "claim": s_claim,
                    "evidence_needed": str(s.get("evidence_needed") or "").strip(),
                    "tools": tools,
                })
                if len(subs) >= max(1, int(max_sub)):
                    break
            if not subs:
                continue
            narratives.append({
                "claim": n_claim,
                "why": str(n.get("why") or "").strip(),
                "sub_narratives": subs,
            })
            if len(narratives) >= max(1, int(max_nar)):
                break
        if not narratives:
            return None
        return {"verdict": verdict, "narratives": narratives}

    def _hier_model(self):
        try:
            return self.cm.model_router.config.get("model_name") or ""
        except Exception:
            return ""

    def _seed_hierarchy_map(self, plan, user_query):
        """Seed the Narrative Map from the plan BEFORE any tool runs: the verdict
        (open goal-claim), each narrative (open), each sub-narrative (open) under its
        narrative — using stable ``created_from`` keys so execution later flips the
        SAME nodes (never duplicates). Returns the ordered ``plan_steps`` the engine
        walks, each carrying its map node ids. Best-effort."""
        nms = getattr(self.cm, "narrative_map_service", None)
        steps = []
        if nms is None:
            return steps
        model = self._hier_model()
        try:
            verdict = (plan.get("verdict") or "").strip() or self._claimify(user_query)
            if verdict:
                nms.set_verdict(verdict, "Goal of this investigation — still open.", model=model)
            plan["verdict"] = verdict
            for i, nar in enumerate(plan.get("narratives", [])):
                nar_id = nms.upsert_finding_narrative(
                    nar.get("claim", ""), nar.get("why", "") or "Activity to prove for the verdict.",
                    f"plan:nar:{i}", evidence=[], state="open", model=model)
                nar["id"] = nar_id
                subs = nar.get("sub_narratives", [])
                for j, sub in enumerate(subs):
                    sub_id = nms.upsert_finding_narrative(
                        sub.get("claim", ""), sub.get("evidence_needed", "") or "Step to establish.",
                        f"plan:nar:{i}:sub:{j}", evidence=[], state="open", model=model, parent=nar_id)
                    sub["id"] = sub_id
                    sub["status"] = "open"
                    steps.append({
                        "nar_index": i, "nar": nar, "nar_id": nar_id,
                        "sub_index": j, "sub": sub, "sub_id": sub_id,
                        "claim": sub.get("claim", ""),
                        "evidence_needed": sub.get("evidence_needed", ""),
                        "tools": sub.get("tools", []),
                        "is_last_in_nar": (j == len(subs) - 1),
                    })
            self._push_narrative_map_update()
        except Exception as e:
            self.logger.debug(f"hierarchy map seeding skipped: {e}")
        return steps

    def _hierarchy_outcomes_block(self, plan) -> str:
        """A compact summary of the plan + each sub-narrative's outcome, fed into the
        final synthesis so it can state whether the verdict is proven from the steps."""
        if not plan:
            return ""
        lines = [f"## Investigation Plan Outcomes — verdict to settle: {plan.get('verdict', '')}"]
        for i, nar in enumerate(plan.get("narratives", [])):
            lines.append(f"- NARRATIVE {i + 1}: {nar.get('claim', '')}")
            for sub in nar.get("sub_narratives", []):
                st = (sub.get("status") or "open").upper()
                lines.append(f"    • [{st}] {sub.get('claim', '')}")
        lines.append(
            "Decide whether the VERDICT is PROVEN or NOT-PROVEN from the sub-narrative outcomes above "
            "and the cited evidence, and explain the reasoning.")
        return "\n".join(lines)

    def _build_focus_block(self, plan, steps, focus_idx: int) -> str:
        """The per-iteration message for a hierarchical run: focus on the CURRENT
        sub-narrative only — verdict + current narrative + current sub-narrative +
        its evidence_needed + the allowed tools — and how to conclude the step."""
        if focus_idx >= len(steps):
            return ""
        step = steps[focus_idx]
        nar = step["nar"]
        n_total = len(plan.get("narratives", []))
        m_total = len(nar.get("sub_narratives", []))
        tools = ", ".join(step["tools"]) if step["tools"] else "any relevant forensic tool"
        return "\n".join([
            "## Investigation Plan — prove ONE step at a time (do not jump ahead)",
            f"VERDICT (what we are proving): {plan.get('verdict', '')}",
            f"CURRENT NARRATIVE ({step['nar_index'] + 1}/{n_total}): {nar.get('claim', '')}",
            f"CURRENT SUB-NARRATIVE ({step['sub_index'] + 1}/{m_total}): {step['claim']}",
            f"EVIDENCE NEEDED: {step['evidence_needed'] or '(find artifact evidence that proves this sub-narrative)'}",
            f"TOOLS TO USE: {tools}",
            "Artifacts: execution → Prefetch/AmCache/ShimCache/SRUM · persistence → Registry Run keys · "
            "deletion → USN Journal/Recycle Bin/MFT · network → SRUM · file access → Jump Lists/LNK/ShellBags.",
            "",
            "Run the tools above to find the evidence for THIS sub-narrative only. When you have run "
            "them and seen the results, END your turn with EXACTLY ONE line:",
            "  SUBVERDICT: PROVEN || <the artifact evidence + one-line why>",
            "  — or —",
            "  SUBVERDICT: NOT-PROVEN || <what you checked and why it is not established>",
        ])

    @staticmethod
    def _parse_subverdict(text: str):
        """Parse the step conclusion. Returns ("PROVEN"|"NOT-PROVEN"|None, reason).

        Lenient so real models trigger resolution reliably: accepts the canonical
        ``SUBVERDICT: PROVEN|NOT-PROVEN || <reason>`` line, decorated forms
        (``**SUBVERDICT**``, ``SUB-VERDICT``), and — as a last resort — a bare line
        that is JUST a ``PROVEN`` / ``NOT PROVEN`` conclusion. NOT-PROVEN is checked
        first so 'not proven' never matches as 'proven'."""
        if not text:
            return None, ""
        # Canonical / decorated marker, tolerant of surrounding **/`/_ decoration and
        # a trailing `|| reason` (anywhere on its line).
        m = re.search(
            r'(?im)SUB[\s\-]?VERDICT\b[\s*_`:|-]*?(PROVEN|NOT[\s\-]?PROVEN)\b(.*)$', text)
        if m:
            verdict = ("NOT-PROVEN" if m.group(1).upper().replace(" ", "").replace("-", "").startswith("NOT")
                       else "PROVEN")
            reason = re.sub(r'^[\s*_`|-]+', '', m.group(2) or '').strip()
            return verdict, reason
        # Bare trailing conclusion line (no marker word) — check NOT-PROVEN first.
        if re.search(r'(?im)^[ \t>*_`-]*NOT[\s\-]?PROVEN\b', text):
            return "NOT-PROVEN", ""
        if re.search(r'(?im)^[ \t>*_`-]*PROVEN\b', text):
            return "PROVEN", ""
        return None, ""

    def _resolve_by_evidence(self, step, step_results):
        """Decide a step's outcome from the EVIDENCE when the model never wrote a
        clean SUBVERDICT (budget/nudge exhausted): PROVEN iff a relevant SUCCESSFUL
        tool result with real data exists for this step, else NOT-PROVEN. This keeps
        a model that gathered the evidence but skipped the marker from being
        auto-failed."""
        best = self._best_step_result(step_results, step)
        if best is None:
            return "NOT-PROVEN", "No supporting tool result was found for this sub-narrative."
        inner = best.get("result") if isinstance(best.get("result"), dict) else {}
        blob = str(best.get("data") or (inner.get("data") if isinstance(inner, dict) else "") or inner or "")
        if blob.strip():
            return "PROVEN", "Established from the tool evidence gathered for this sub-narrative."
        return "NOT-PROVEN", "Tool ran but returned no supporting data."

    @staticmethod
    def _best_step_result(step_results, step):
        """The most relevant SUCCESSFUL tool result for this step (keyword overlap
        with the sub-narrative claim + evidence_needed)."""
        import re as _re
        def _toks(s):
            return {w for w in _re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", (s or "").lower())}
        want = _toks(step.get("claim", "") + " " + step.get("evidence_needed", ""))
        best, best_score = None, -1
        for r in (step_results or []):
            if not isinstance(r, dict):
                continue
            inner = r.get("result") if isinstance(r.get("result"), dict) else {}
            if not (r.get("success") or (isinstance(inner, dict) and inner.get("success"))):
                continue
            blob = str(r.get("data") or (inner.get("data") if isinstance(inner, dict) else "") or inner or "")
            score = len(want & _toks(blob))
            if score > best_score:
                best, best_score = r, score
        return best

    @staticmethod
    def _evidence_card_from_result(r, reason: str):
        """Build a Narrative-Map evidence card from a tool result (reloadable)."""
        if not isinstance(r, dict):
            return None
        inner = r.get("result") if isinstance(r.get("result"), dict) else {}
        params = r.get("parameters") or {}
        tool = r.get("tool_name") or r.get("name") or (inner.get("tool_name") if isinstance(inner, dict) else None) or "tool"
        blob = str(r.get("data") or (inner.get("data") if isinstance(inner, dict) else "") or inner or "")
        return {
            "kicker": tool,
            "data": (blob[:120] + "…") if len(blob) > 120 else blob,
            "reason": reason or "Result that established this sub-narrative.",
            "ref": tool,
            "query": params.get("sql_query") or "",
            "database": params.get("database_name") or "",
        }

    def _resolve_substep(self, step, subverdict, reason, step_results):
        """Flip the sub-narrative's map node from the step's outcome, then roll the
        parent narrative up when its last sub-narrative is resolved. Best-effort."""
        nms = getattr(self.cm, "narrative_map_service", None)
        if nms is None:
            return
        model = self._hier_model()
        sub_id, nar_id = step.get("sub_id"), step.get("nar_id")
        try:
            if subverdict == "PROVEN":
                best = self._best_step_result(step_results, step)
                card = self._evidence_card_from_result(best, reason) if best else None
                if card and sub_id:
                    nms.attach_evidence(sub_id, card, model=model)  # flips open -> proven
                    step["sub"]["status"] = "proven"
                else:
                    # Claimed proven but no supporting tool result → honesty: negative.
                    if sub_id:
                        nms.set_state(sub_id, "negative",
                                      reason="Claimed proven but no supporting tool result.", model=model)
                    step["sub"]["status"] = "negative"
            else:
                if sub_id:
                    nms.set_state(sub_id, "negative", reason=reason or "Not established.", model=model)
                step["sub"]["status"] = "negative"

            if step.get("is_last_in_nar") and nar_id:
                any_proven = any(s.get("status") == "proven"
                                 for s in step["nar"].get("sub_narratives", []))
                nms.set_state(nar_id, "proven" if any_proven else "negative",
                              reason=("Established by a proven sub-narrative." if any_proven
                                      else "No sub-narrative could be established."), model=model)
            self._push_narrative_map_update()
        except Exception as e:
            self.logger.debug(f"resolve substep skipped: {e}")

    # ── Resume-after-disconnect: persist the hierarchical plan + progress ──────
    def _active_plan_path(self):
        """Path to the per-case active-plan checkpoint, or None if no case dir."""
        try:
            cd = getattr(self.cm, "case_directory", None)
            if not cd:
                return None
            from pathlib import Path as _Path
            d = _Path(cd) / "EYE_Logs"
            d.mkdir(parents=True, exist_ok=True)
            return d / "active_plan.json"
        except Exception:
            return None

    def _save_active_plan(self, hierarchy_plan, focus_idx, user_query):
        """Checkpoint the hierarchy plan + per-sub-narrative status + focus so an
        interrupted run (LLM drop / app close) can resume where it stopped."""
        p = self._active_plan_path()
        if not p or not hierarchy_plan:
            return
        try:
            data = {
                "user_query": user_query,
                "verdict": hierarchy_plan.get("verdict", ""),
                "focus_idx": focus_idx,
                "ts": datetime.now().isoformat(),
                "narratives": [
                    {
                        "claim": nar.get("claim", ""), "why": nar.get("why", ""),
                        "id": nar.get("id"),
                        "sub_narratives": [
                            {"claim": s.get("claim", ""), "evidence_needed": s.get("evidence_needed", ""),
                             "tools": s.get("tools", []), "id": s.get("id"),
                             "status": s.get("status", "open")}
                            for s in nar.get("sub_narratives", [])
                        ],
                    }
                    for nar in hierarchy_plan.get("narratives", [])
                ],
            }
            import json as _json
            p.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.debug(f"save active plan skipped: {e}")

    def _load_active_plan(self):
        """Load the active-plan checkpoint, or None."""
        p = self._active_plan_path()
        if not p or not p.exists():
            return None
        try:
            import json as _json
            data = _json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("narratives"):
                return data
        except Exception:
            pass
        return None

    def _clear_active_plan(self):
        """Delete the checkpoint once the plan completes."""
        p = self._active_plan_path()
        try:
            if p and p.exists():
                p.unlink()
        except Exception:
            pass

    def _rebuild_plan_steps(self, plan):
        """Reconstruct the ordered plan_steps from a saved/loaded plan dict WITHOUT
        recreating Narrative Map nodes (the seeded cards already exist). Mirrors the
        step shape produced by `_seed_hierarchy_map`."""
        steps = []
        for i, nar in enumerate(plan.get("narratives", [])):
            subs = nar.get("sub_narratives", [])
            for j, sub in enumerate(subs):
                sub.setdefault("status", "open")
                steps.append({
                    "nar_index": i, "nar": nar, "nar_id": nar.get("id"),
                    "sub_index": j, "sub": sub, "sub_id": sub.get("id"),
                    "claim": sub.get("claim", ""),
                    "evidence_needed": sub.get("evidence_needed", ""),
                    "tools": sub.get("tools", []),
                    "is_last_in_nar": (j == len(subs) - 1),
                })
        return steps

    @staticmethod
    def _is_continuation_query(user_query, saved_query) -> bool:
        """True if this turn should RESUME the saved plan: an empty/short 'continue'
        cue, or a query closely matching the saved goal. A different question → False
        (start fresh)."""
        q = (user_query or "").strip().lower()
        if not q:
            return True
        cues = ("continue", "resume", "keep going", "carry on", "go on", "proceed",
                "pick up", "finish it", "carry-on")
        if len(q.split()) <= 6 and any(c in q for c in cues):
            return True
        sq = (saved_query or "").strip().lower()
        if sq and (q == sq or (len(q) > 12 and q in sq) or (len(sq) > 12 and sq in q)):
            return True
        return False

    def _build_checklist_block(self, checklist: List[Dict]) -> str:
        """Render the sub-question checklist for the outgoing model message so
        the model sees which parts are still OPEN and targets them."""
        if not checklist:
            return ""
        lines = ["## Sub-Questions to Answer (address every OPEN item before finishing)"]
        for c in checklist:
            mark = "x" if c.get("status") == "answered" else " "
            lines.append(f"[{mark}] {c.get('q', '')}")
        return "\n".join(lines)

    _CHECKLIST_STOPWORDS = {
        "verify", "the", "a", "an", "is", "are", "was", "were", "did", "does",
        "do", "of", "to", "in", "on", "and", "or", "any", "there", "this",
        "that", "it", "for", "with", "what", "when", "where", "which", "how",
        "has", "have", "had", "been", "be", "you", "your", "all",
    }

    def _update_checklist(self, checklist: List[Dict], ai_content: str, ledger_entries: List[Dict]) -> None:
        """Mark checklist items answered once their key terms show up in REAL
        EVIDENCE — the successful tool results in ``ledger_entries`` only.

        The model's own answer text (``ai_content``) is DELIBERATELY excluded: a
        sub-question must be satisfied by artifact data, never because the model
        *talked about* the topic (e.g. narrated a plan mentioning "CPU/persistence").
        Folding ``ai_content`` in let planning prose flip items to answered with zero
        evidence — false completion. ``ai_content`` is kept in the signature for
        compatibility but is no longer matched against. Drives the completion gate
        only (bounded by MAX_CONTINUE_NUDGES), so a fuzzy match stays safe."""
        if not checklist:
            return
        haystack = ""
        for e in ledger_entries or []:
            if not e.get("success", True):  # only proven evidence satisfies an item
                continue
            haystack += " " + str(e.get("result", "")).lower() + " " + str(e.get("params", "")).lower()
        if not haystack.strip():
            return  # no evidence yet → nothing can be marked answered
        for c in checklist:
            if c.get("status") == "answered":
                continue
            words = {
                w for w in re.findall(r"[a-z0-9.]+", (c.get("q") or "").lower())
                if w not in self._CHECKLIST_STOPWORDS and len(w) > 2
            }
            if not words:
                continue
            hits = sum(1 for w in words if w in haystack)
            if hits >= max(1, int(len(words) * 0.6)):
                c["status"] = "answered"

    def _build_evidence_ledger(self, entries: List[Dict]) -> str:
        """Compact, one-line-per-tool-call index of what every iteration produced,
        so the model can CORRELATE across tools/databases (it survives even when a
        raw tool output was compressed/truncated). Not persisted to history.

        Each entry is {iteration, tool, params, result}."""
        if not entries:
            return ""

        def _summ(tool, params, res):
            params = params or {}
            res = res or {}
            db = res.get("database_name") or params.get("database_name") or ""
            if not res.get("success", False):
                err = str(res.get("error") or "unknown error")
                return f"{db + ' ' if db else ''}→ FAILED: {err[:120]}"
            if tool == "get_schema":
                tbls = res.get("all_tables") or list((res.get("schema") or {}).keys())
                head = ", ".join(tbls[:6]) + (" …" if len(tbls) > 6 else "")
                return f"{db} → {len(tbls)} table(s)" + (f" ({head})" if head else "")
            if tool in ("query_database", "analyze_large_dataset"):
                table = ""
                sql = res.get("sql_query") or params.get("sql_query") or ""
                m = re.search(r'(?:FROM|JOIN)\s+["\'`]?([A-Za-z_][A-Za-z0-9_]*)', sql, re.IGNORECASE)
                if m:
                    table = "/" + m.group(1)
                n = res.get("row_count")
                if n is None:
                    n = len(res.get("data") or res.get("rows") or [])
                note = " (compressed sample)" if res.get("compressed") else ""
                summ = res.get("summary")
                return f"{db}{table} → {n} row(s){note}" + (f" — {str(summ)[:80]}" if summ else "")
            if tool == "search_artifacts":
                return f"→ {res.get('total_matches', 0)} match(es)"
            if tool == "list_case_files":
                files = res.get("files") or []
                return f"→ {len(files)} item(s)"
            if tool == "query_correlation_results":
                results = res.get("results")
                cnt = len(results) if isinstance(results, list) else res.get("results_count", "?")
                return f"→ {cnt} correlation result(s)"
            if (tool or "").startswith("report_"):
                return "→ documented to report"
            return "→ ok"

        lines = ["## Evidence Gathered So Far (per step — correlate across these)"]
        for e in entries:
            tool = e.get("tool", "?")
            line = f"[{e.get('iteration', '?')}] {tool} {_summ(tool, e.get('params'), e.get('result'))}"
            lines.append(line[:300])
        return "\n".join(lines)

    def _build_correlation_mandate(self, checklist: List[Dict] = None) -> str:
        """Build the per-sub-question + per-premise + consolidated-answer mandate
        appended to the synthesis prompt when a question was decomposed (or had
        asserted premises). Empty string when there is no checklist."""
        if not checklist:
            return ""
        questions = [c for c in checklist if c.get("kind") != "premise"]
        premises = [c for c in checklist if c.get("kind") == "premise"]
        parts = ["DECOMPOSED INVESTIGATION — you MUST resolve every item below:"]
        if questions:
            parts.append(
                "Answer EACH of these sub-questions explicitly and separately:\n"
                + "\n".join(f"  - {c.get('q')}" for c in questions)
            )
        if premises:
            parts.append(
                "For EACH premise the investigator asserted, give an explicit verdict — "
                "CONFIRMED, REFUTED, or INCONCLUSIVE — backed by artifact evidence with UTC "
                "timestamps. If REFUTED, clearly and directly tell the investigator they are "
                "mistaken and show the contradicting evidence:\n"
                + "\n".join(f"  - {c.get('q')}" for c in premises)
            )
        parts.append(
            "Finally, provide a single 'Consolidated Answer' section that CORRELATES the "
            "partial answers into one coherent conclusion (cross-reference sources per the "
            "Forensic Evidence Protocol below)."
        )
        return "\n\n" + "\n\n".join(parts)

    def _build_synthesis_prompt(self, query: str, results: List[Dict], text_only: bool = False, ledger_text: str = None, checklist: List[Dict] = None) -> str:
        """
        Enforces the 'Forensic Evidence Protocol' for forensic reporting.
        Forces the AI to be technical, chronological, and specific.

        When ``text_only`` is True the model has already documented the evidence
        to the report but returned no chat text. This pass must produce ONLY a
        conversational answer to the investigator and must NOT call any tools.

        When ``checklist`` is provided (a decomposed/premise-bearing question),
        the prompt additionally requires a per-sub-question answer, a per-premise
        verdict, and a final consolidated answer.
        """
        any_successful_results = any(r.get("success") for r in results)

        if text_only:
            report_mandate = (
                "The technical evidence has ALREADY been documented in the Forensic Report. "
                "Your ONLY task now is to speak directly to the investigator in chat: write a "
                "complete, natural, conversational answer to their question as a human forensic "
                "assistant would — summarise what you found, the timeline, and its significance. "
                "DO NOT call any tools. DO NOT return an empty response. Just answer."
            )
        else:
            report_mandate = (
            "CRITICAL: You MUST perform TWO actions in this turn:\n"
            "1. PRIMARY TASK: Write the answer as a FORENSIC NARRATIVE — a conclusion stated as a finding, immediately followed by the artifact basis for it. Assert what happened, then cite the evidence: e.g. 'Discord accessed the user's files on 2024-06-12 14:25, based on the SRUM network egress (4.2 MB) correlated with the prefetch execution record.' Every claim is a narrative conclusion + its evidentiary basis (artifact, timestamp, count). Do NOT just list raw data — interpret it into findings.\n"
            "2. SUPPORTING TASK: Call a `report_*` tool (e.g., `report_append_section`, `report_add_data_table`) to document the technical evidence for the formal record.\n"
            "NO HAND-DRAWN TABLES IN CHAT (Rule 29): never draw a table in the chat narrative (no '|' pipe tables, no '+---+'/'____' ASCII grids, no space-aligned columns). To put a real table in the chat answer (verdict matrices, hypothesis summaries, comparisons) call `chat_add_table` with rows directly; for SQL-backed evidence rows call `report_add_data_table`. The narrative itself gives prose + key facts.\n"
            "VERDICT LINE: end your reply with ONE final line in EXACTLY this form so the case Verdict can be set — `VERDICT: <one-sentence overall conclusion> || <why, grounded in the proven findings>`. Use this only for the case-level conclusion; if it is too early to conclude, omit the line.\n"
            "DO NOT return an empty response. You MUST talk to the investigator and provide a direct answer."
        ) if any_successful_results else (
            "CRITICAL — NO ARTIFACT DATA WAS RETRIEVED THIS TURN. No forensic tool executed "
            "successfully, so there is NO evidence to draw a conclusion from. You MUST be honest:\n"
            "1. State plainly and up front that you could NOT retrieve any artifact data this turn, so "
            "you cannot answer the question yet.\n"
            "2. Do NOT describe a plan or what you 'will' do next. FORBIDDEN: future-tense intent such "
            "as 'I will…', 'I am now…', 'I am acting…', 'let me…', 'my plan is…'. You are reporting an "
            "outcome, not announcing an investigation.\n"
            "3. Do NOT assert, imply, or speculate any finding (no 'likely', no 'appears to'). Absence "
            "of data is NOT evidence of anything.\n"
            "4. Briefly note what was attempted and, if the model could not run tools, recommend the "
            "investigator switch to a tool-capable model and re-run.\n"
            "Write this as a short, direct, conversational message. NEVER return an empty response."
        )

        try:
            results_str = json.dumps(results, indent=2)
            if len(results_str) > 40000:
                results_str = results_str[:40000] + "\n... [TRUNCATED DUE TO SIZE. SYNTHESIZE AVAILABLE DATA] ..."
        except Exception:
            results_str = str(results)

        ledger_block = (ledger_text + "\n\n") if ledger_text else ""
        correlation_mandate = self._build_correlation_mandate(checklist)

        return (
            f"Synthesize findings for investigator query: {query}\n\n"
            f"{ledger_block}"
            f"Tool execution results:\n{results_str}\n"
            f"{correlation_mandate}\n\n"
            "FORENSIC EVIDENCE PROTOCOL:\n"
            "1. Conversational Delivery: Speak directly to the investigator as a helpful forensic peer.\n"
            "2. Extract Exact Timestamps, Usernames, and Process Details.\n"
            "3. Construct a clear, chronological TIMELINE of events.\n"
            "4. Explain the forensic significance of each event.\n"
            "5. CROSS-SOURCE CORRELATION: Do NOT report each database/tool in isolation. "
            "Cross-reference the findings above: state where multiple sources CORROBORATE the "
            "same fact (e.g. an application present in Amcache that ALSO has Prefetch execution "
            "and an MFT file record), where a source is SILENT, and where sources CONFLICT. Your "
            "conclusion MUST rest on the combined, cross-referenced evidence — not a single source.\n"
            "6. DIRECT ANSWER: You MUST explicitly answer the query right now. NEVER return an empty response.\n\n"
            f"{report_mandate}"
        )

    def _handle_generation_failure(self, error, status_callback):
        """
        Recovery logic for AI failures.
        Presents the user with alternative model chips to resume the session.
        """
        err_str = str(error)
        is_quota_error = any(msg in err_str.lower() for msg in ["quota", "429", "exhausted", "capacity", "limit"])
        current_model = self.cm.model_router.config.get("model_name")
        
        # Discover fallback options
        model_chips = []
        try:
            available = self.cm.model_router.list_models()
            model_chips = [{
                "id": f"switch_{m}", "label": f"Try {m}", "query": f"Switch model to {m}", "icon": "brain"
            } for m in available if m != current_model]
        except: pass

        # Check for context window limit error
        import re
        context_match = re.search(r"n_ctx:\s*(\d+)", err_str)
        if context_match:
            try:
                # 1. Parse the detected context limit
                detected_limit = int(context_match.group(1))
                if detected_limit > 0:
                    # 2. Apply a SAFETY MARGIN (90%) to account for tokenizer differences
                    # and prevent "off-by-one" token errors.
                    safe_limit = int(detected_limit * 0.9)
                    
                    # 3. Reserve an OUTPUT BUFFER (e.g., 512 tokens) so the model can actually answer.
                    # If the context is tiny, reserve at least 20%.
                    output_buffer = max(512, int(safe_limit * 0.2))
                    available_for_prompt = safe_limit - output_buffer
                    
                    if available_for_prompt < 1000:
                         # Extremely constrained environment (e.g. 2048 ctx)
                         sys_prompt = 800
                         hist = 600
                         rag = 200
                         tools = max(200, available_for_prompt - (sys_prompt + hist + rag))
                    else:
                         # Balanced split for standard context (4096+)
                         sys_prompt = int(available_for_prompt * 0.35)
                         hist = int(available_for_prompt * 0.35)
                         rag = int(available_for_prompt * 0.15)
                         tools = available_for_prompt - (sys_prompt + hist + rag)
                    
                    self.cm.max_total_tokens = detected_limit
                    self.cm.token_budget = {
                        "system_prompt": sys_prompt,
                        "rag_context": rag,
                        "conversation_history": hist,
                        "tool_results": tools
                    }
                    
                    self.logger.warning(f"Auto-adapted token budget for {detected_limit} ctx (Prompt Budget: {available_for_prompt})")
                    
                    response = (
                        f"### Context Window Automatically Adapted\n"
                        f"I detected that your local model has a smaller context limit ({detected_limit} tokens) than expected.\n\n"
                        f"I have automatically optimized my internal forensic budget to fit your model while leaving space for responses. **Please try your query again!**\n\n"
                        f"*(Tip: For better forensic analysis, consider loading the model with a larger context window in LM Studio's settings)*"
                    )
                    
                    return {
                        "response": response, "error": None, "action_chips": model_chips, "context_stats": self.cm.get_context_stats()
                    }
            except Exception as ex:
                self.logger.error(f"Failed to auto-adapt context: {ex}")

        response = (
            f"### Model Connection Failed\n"
            f"The forensic model encountered an error:\n`{err_str}`\n\n"
        )
        if is_quota_error:
            response += (
                "Your current model has exhausted its rate limit. Please wait or "
                "select an alternative model below:"
            )
        else:
            response += (
                "Please verify your API key or server status, or "
                "select an alternative model below:"
            )
        return {
            "success": False, "error": f"Connection failed: {err_str}",
            "data": { "response": response, "action_chips": model_chips[:5] }
        }
