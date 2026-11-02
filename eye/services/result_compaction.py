"""Older tool results go to the model as short digests; the full result stays one
call away (`recall_result`) and in the persistent, sealed history.

Why: every tool result was kept whole and protected from summarising, so one
question's history reached ~700K tokens and every later call re-read all of it
(2026-11-02 review). The evidence rule still holds - nothing is dropped: the
stored history and the EvidenceSeal keep the full results, only the OUTGOING copy
is compacted, and every compaction is recorded.

Cache-friendly by design: compaction runs only when the raw tool output in the
payload passes a threshold, then compacts every raw result except the newest few
at once, and a message once compacted stays compacted. So the payload's prefix is
stable between compactions and a provider's prompt cache breaks only at a
compaction, not on every step.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

RESULTS_MARKER = "Investigation Tool Results:\n"
DEFAULT_TRIGGER_CHARS = 120_000     # ~34K tokens of raw tool output
DEFAULT_KEEP_LAST = 2               # newest tool-result messages stay whole


def _fp(msg) -> str:
    return hashlib.sha1(str(msg.get("content") or "").encode("utf-8", "replace")).hexdigest()


def result_id(result) -> str:
    blob = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return "r" + hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:8]


def is_tool_message(msg) -> bool:
    return bool((msg.get("metadata") or {}).get("is_tool_result")) and RESULTS_MARKER in str(msg.get("content") or "")


def parse_results(content: str) -> Optional[List[Dict[str, Any]]]:
    """The tool results a stored tool-result message holds, or None if unreadable
    (e.g. a payload cut at the memory cap)."""
    text = str(content or "")
    i = text.find(RESULTS_MARKER)
    if i < 0:
        return None
    try:
        data = json.loads(text[i + len(RESULTS_MARKER):])
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _short(value, limit) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def digest_result(r: Dict[str, Any]) -> str:
    rid = result_id(r)
    name = r.get("tool_name") or r.get("name") or "tool"
    params = r.get("parameters") or {}
    inner = r.get("result") if isinstance(r.get("result"), dict) else {}
    ok = bool(r.get("success")) and not (isinstance(inner, dict) and inner.get("success") is False)
    if not ok:
        err = r.get("error") or (inner.get("error") if isinstance(inner, dict) else "") or "failed"
        return "- [%s] %s(%s) -> FAILED: %s" % (rid, name, _short(params, 160), _short(err, 200))
    rows = None
    for key in ("rows", "data", "results", "events", "matches", "records"):
        if isinstance(inner, dict) and isinstance(inner.get(key), list):
            rows = inner[key]
            break
    count = inner.get("row_count") if isinstance(inner, dict) else None
    if count is None and rows is not None:
        count = len(rows)
    sample = ""
    if rows:
        sample = "; first rows: " + _short(rows[:2], 500)
    elif isinstance(inner, dict) and inner:
        sample = "; " + _short({k: v for k, v in inner.items() if k not in ("success",)}, 500)
    return "- [%s] %s(%s) -> ok%s%s" % (rid, name, _short(params, 160),
                                        ", %s rows" % count if count is not None else "", sample)


def digest_message(content: str) -> str:
    results = parse_results(content)
    head = ("[Earlier tool results, compacted to save context. Each line is one result; "
            "call recall_result with its [id] to read it in full.]\n")
    if results is None:
        text = str(content or "")
        return head + "- (unparsed) " + _short(text[text.find(RESULTS_MARKER) + len(RESULTS_MARKER):]
                                               if RESULTS_MARKER in text else text, 1200)
    return head + "\n".join(digest_result(r) for r in results if isinstance(r, dict))


class ResultCompactor:
    """Per-conversation state: which tool-result messages are compacted."""

    def __init__(self, trigger_chars: int = DEFAULT_TRIGGER_CHARS, keep_last: int = DEFAULT_KEEP_LAST):
        self.trigger_chars = int(trigger_chars)
        self.keep_last = int(keep_last)
        self.compacted = set()          # fingerprints of compacted messages
        self.last_event = None          # what the latest compaction did, for the audit trail

    def apply(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        self.last_event = None
        tool_idx = [i for i, m in enumerate(history) if is_tool_message(m)]
        raw = [i for i in tool_idx if _fp(history[i]) not in self.compacted]
        raw_chars = sum(len(str(history[i].get("content") or "")) for i in raw)
        if raw_chars > self.trigger_chars and len(raw) > self.keep_last:
            newly = raw[:-self.keep_last] if self.keep_last else raw
            before = sum(len(str(history[i].get("content") or "")) for i in newly)
            for i in newly:
                self.compacted.add(_fp(history[i]))
            self.last_event = {"messages": len(newly), "chars_before": before,
                               "hashes": [_fp(history[i])[:16] for i in newly]}
        if not self.compacted:
            return history
        out = []
        for m in history:
            if is_tool_message(m) and _fp(m) in self.compacted:
                m = dict(m, content=digest_message(m.get("content")))
            out.append(m)
        if self.last_event is not None:
            self.last_event["chars_after"] = sum(
                len(str(m.get("content") or "")) for m in out if str(m.get("content") or "").startswith(
                    "[Earlier tool results, compacted"))
        return out


def find_result(history: List[Dict[str, Any]], rid: str) -> Optional[Dict[str, Any]]:
    """The full tool result with this id, from the stored history (newest first)."""
    for m in reversed(history or []):
        if not is_tool_message(m):
            continue
        for r in parse_results(m.get("content")) or []:
            if isinstance(r, dict) and result_id(r) == rid:
                return r
    return None
