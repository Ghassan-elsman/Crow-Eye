"""
Helpers that enrich the Compliance panel's "Processed vs Dropped Payload" view.

The Evidence Seals carry the self-heal cuts (summarize/drop) and tool-output caps
in their ``cut_details``. The *budget trims* (system prompt / RAG / history
compaction) are recorded only in the hash-chained truncation audit log, and the
*refused payload itself* lives in the seal's sealed-payload sidecar. These pure
functions synthesize "cut" entries for both so the section reflects EVERY drop —
without mutating the tamper-evident seal records (read-side merge only).
"""

from typing import Any, Dict, List

# Budget/assembly trims to surface as cuts. Deliberately EXCLUDES
# `self_heal_context_fit` and `tool_output_memory_cap_*` (already present in seal
# cut_details) and `REFUSED_OVERFLOW` (handled by refused_payload_cuts) to avoid
# double-counting.
ASSEMBLY_REASONS = {
    "system_prompt_core_over_budget",
    "system_prompt_optional_context_budget",
    "rag_context_budget",
    "budget_exceeded",
}


def _query_resolver(seals: List[Dict[str, Any]]):
    """Return f(ts) -> query, attributing a timestamp to the question of the
    latest seal at/before it (so synthesized cuts group by question)."""
    timeline = sorted(
        [(s.get("timestamp", ""), s.get("query", "") or "") for s in (seals or []) if s.get("timestamp")],
        key=lambda x: x[0],
    )

    def query_for(ts: str) -> str:
        q = ""
        if not ts:
            return q
        for t, qq in timeline:
            if t <= ts:
                q = qq
            else:
                break
        return q

    return query_for


def assembly_cuts_from_events(events: List[Dict[str, Any]], seals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Synthesize cut entries from budget-trim audit events (system prompt / RAG /
    history). Each carries the dropped (and, where available, kept) message
    content from the event metadata, plus a question correlated by timestamp."""
    query_for = _query_resolver(seals)
    out: List[Dict[str, Any]] = []
    for ev in (events or []):
        if ev.get("reason") not in ASSEMBLY_REASONS:
            continue
        md = ev.get("metadata") or {}
        cut_content = md.get("cut_content") or ""
        out.append({
            "action": ev.get("action") or "TRUNCATED",
            "phase": ev.get("reason"),
            "timestamp": ev.get("timestamp"),
            "query": query_for(ev.get("timestamp", "")),
            "token_count": ev.get("tokens") or 0,
            "sha256": ev.get("hash") or "",
            "cut_content": cut_content,
            "cut_content_len": len(cut_content),
            "processed_content": md.get("processed_content"),
            "source": "assembly_budget",
        })
    return out


def refused_payload_cuts(seals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per REFUSED payload — the message itself the Eye refused to send.
    The full bytes are recoverable on demand from the sealed-payload sidecar
    (get_sealed_payload_full) using ``payload_sha256``."""
    out: List[Dict[str, Any]] = []
    for rec in (seals or []):
        refused = rec.get("sent_to_model") is False or "REFUSED_OVERFLOW" in (rec.get("phase") or "")
        if not refused:
            continue
        out.append({
            "action": "REFUSED_OVERFLOW",
            "phase": rec.get("phase"),
            "timestamp": rec.get("timestamp"),
            "query": rec.get("query"),
            "token_count": rec.get("payload_tokens") or 0,
            "sha256": rec.get("payload_sha256") or "",
            # Bounded original-message preview (when sealed); full bytes load on
            # demand from the sealed sidecar.
            "cut_content": rec.get("payload_preview") or "",
            "cut_content_len": rec.get("payload_tokens") or 0,
            "payload_sha256": rec.get("payload_sha256"),
            "payload_sidecar": rec.get("payload_sidecar"),
            "max_context_tokens": rec.get("max_context_tokens"),
            "source": "refused",
        })
    return out
