"""
Eye AI settings bridge for the main Crow-Eye Settings dialog.

Pure read/merge/write helpers (no Qt) for the user-facing Eye options that live in
``configs/eye_config.json``. Only settings that the Eye actually consumes are
exposed here:

  context_window.store_full_payload                  (bool)
  context_window.sealed_payload_recent_uncompressed  (int)
  context_window.max_total_tokens                    (int)   fallback / locked window
  context_window.lock_max_total_tokens               (bool)  pin instead of auto-resolve
  context_window.max_tool_output_chars               (int)
  context_window.evidence_preservation.confidence_threshold (float 0..1)

Backend / model / API key are configured via the Eye OnboardingWizard, not here;
``backend`` / ``model_name`` are returned read-only for display.

The Eye reads these at ``ContextManager`` init, so changes apply the next time the
Eye is opened.
"""

import json
from pathlib import Path
from typing import Dict, Optional

DEFAULTS = {
    "store_full_payload": True,
    "sealed_payload_recent_uncompressed": 10,
    "max_total_tokens": 64000,
    "lock_max_total_tokens": False,
    "max_tool_output_chars": 100000,
    "confidence_threshold": 0.7,
    # Embedding / semantic retrieval — top-level "embedding" section.
    "embedding_enabled": False,
    "embedding_model": "nomic-embed-text",
    "embedding_endpoint": "http://localhost:11434",
    "embedding_index_evidence": False,
    # Reasoning behaviors (v0.11.1) — top-level "reasoning" section.
    "enable_decomposition": True,
    "max_sub_questions": 6,
    # Hierarchical plan-driven investigation (verdict → narrative → sub-narrative).
    "enable_hierarchy": True,
    "max_narratives": 12,
    "max_sub_narratives": 8,
    "max_iterations": 300,
    "enable_premise_verification": True,
    "enable_question_memory": True,
    "prior_findings_count": 3,
    # Resilience (v0.11.2).
    "model_retry_max_attempts": 3,
    "auto_segment_question": True,
    "enable_auto_map_reduce": True,
    "auto_map_reduce_row_threshold": 1500,
    # Reasoning transparency + tuning (v0.11.3).
    "enable_reasoning_trace": True,
    "answer_temperature": 0.2,
    "planning_temperature": 0.0,
    "max_output_tokens": 8192,
    "rag_top_k": 5,
    "rag_min_score": 0.05,
    "rag_semantic_min_score": 0.4,
    "rag_subquestion_aware": True,
    # Conversation memory (two-stage policy + long-term recall).
    "history_window_turns": 5,
    "enable_summary_buffer": True,
    "enable_conversation_recall": True,
    "conversation_recall_top_k": 3,
    "search_max_rows": 50,
}


def eye_config_path() -> Path:
    """Absolute path to the app's ``configs/eye_config.json``."""
    return Path(__file__).resolve().parent.parent / "configs" / "eye_config.json"


def _load(path: Path) -> Dict[str, object]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def read_eye_ai_settings(path: Optional[Path] = None) -> Dict[str, object]:
    """Return all exposed Eye settings, falling back to ``DEFAULTS`` for any that
    are missing. Also includes read-only ``backend`` / ``model_name``."""
    path = Path(path) if path else eye_config_path()
    cfg = _load(path)
    cw = cfg.get("context_window") if isinstance(cfg.get("context_window"), dict) else {}
    ev = cw.get("evidence_preservation") if isinstance(cw.get("evidence_preservation"), dict) else {}
    rs = cfg.get("reasoning") if isinstance(cfg.get("reasoning"), dict) else {}
    em = cfg.get("embedding") if isinstance(cfg.get("embedding"), dict) else {}

    out: Dict[str, object] = {}
    try:
        out["store_full_payload"] = bool(cw.get("store_full_payload", DEFAULTS["store_full_payload"]))
        out["sealed_payload_recent_uncompressed"] = int(cw.get("sealed_payload_recent_uncompressed", DEFAULTS["sealed_payload_recent_uncompressed"]))
        out["max_total_tokens"] = int(cw.get("max_total_tokens", DEFAULTS["max_total_tokens"]))
        out["lock_max_total_tokens"] = bool(cw.get("lock_max_total_tokens", DEFAULTS["lock_max_total_tokens"]))
        out["max_tool_output_chars"] = int(cw.get("max_tool_output_chars", DEFAULTS["max_tool_output_chars"]))
        out["confidence_threshold"] = float(ev.get("confidence_threshold", DEFAULTS["confidence_threshold"]))
        out["enable_decomposition"] = bool(rs.get("enable_decomposition", DEFAULTS["enable_decomposition"]))
        out["max_sub_questions"] = int(rs.get("max_sub_questions", DEFAULTS["max_sub_questions"]))
        out["enable_hierarchy"] = bool(rs.get("enable_hierarchy", DEFAULTS["enable_hierarchy"]))
        out["max_narratives"] = int(rs.get("max_narratives", DEFAULTS["max_narratives"]))
        out["max_sub_narratives"] = int(rs.get("max_sub_narratives", DEFAULTS["max_sub_narratives"]))
        out["max_iterations"] = int(rs.get("max_iterations", DEFAULTS["max_iterations"]))
        out["enable_premise_verification"] = bool(rs.get("enable_premise_verification", DEFAULTS["enable_premise_verification"]))
        out["enable_question_memory"] = bool(rs.get("enable_question_memory", DEFAULTS["enable_question_memory"]))
        out["prior_findings_count"] = int(rs.get("prior_findings_count", DEFAULTS["prior_findings_count"]))
        out["model_retry_max_attempts"] = int(rs.get("model_retry_max_attempts", DEFAULTS["model_retry_max_attempts"]))
        out["auto_segment_question"] = bool(rs.get("auto_segment_question", DEFAULTS["auto_segment_question"]))
        out["enable_auto_map_reduce"] = bool(rs.get("enable_auto_map_reduce", DEFAULTS["enable_auto_map_reduce"]))
        out["auto_map_reduce_row_threshold"] = int(rs.get("auto_map_reduce_row_threshold", DEFAULTS["auto_map_reduce_row_threshold"]))
        out["enable_reasoning_trace"] = bool(rs.get("enable_reasoning_trace", DEFAULTS["enable_reasoning_trace"]))
        out["answer_temperature"] = float(rs.get("answer_temperature", DEFAULTS["answer_temperature"]))
        out["planning_temperature"] = float(rs.get("planning_temperature", DEFAULTS["planning_temperature"]))
        out["max_output_tokens"] = int(rs.get("max_output_tokens", DEFAULTS["max_output_tokens"]))
        out["rag_top_k"] = int(rs.get("rag_top_k", DEFAULTS["rag_top_k"]))
        out["rag_min_score"] = float(rs.get("rag_min_score", DEFAULTS["rag_min_score"]))
        out["rag_semantic_min_score"] = float(rs.get("rag_semantic_min_score", DEFAULTS["rag_semantic_min_score"]))
        out["rag_subquestion_aware"] = bool(rs.get("rag_subquestion_aware", DEFAULTS["rag_subquestion_aware"]))
        out["history_window_turns"] = int(rs.get("history_window_turns", DEFAULTS["history_window_turns"]))
        out["enable_summary_buffer"] = bool(rs.get("enable_summary_buffer", DEFAULTS["enable_summary_buffer"]))
        out["enable_conversation_recall"] = bool(rs.get("enable_conversation_recall", DEFAULTS["enable_conversation_recall"]))
        out["conversation_recall_top_k"] = int(rs.get("conversation_recall_top_k", DEFAULTS["conversation_recall_top_k"]))
        out["search_max_rows"] = int(rs.get("search_max_rows", DEFAULTS["search_max_rows"]))
        out["embedding_enabled"] = bool(em.get("enabled", DEFAULTS["embedding_enabled"]))
        out["embedding_model"] = str(em.get("model", DEFAULTS["embedding_model"]))
        out["embedding_endpoint"] = str(em.get("endpoint", DEFAULTS["embedding_endpoint"]))
        out["embedding_index_evidence"] = bool(em.get("index_evidence", DEFAULTS["embedding_index_evidence"]))
    except Exception:
        out = dict(DEFAULTS)
    # Read-only display fields.
    out["backend"] = cfg.get("backend", "")
    out["model_name"] = cfg.get("model_name", "")
    return out


def write_eye_ai_settings(settings: Dict[str, object], path: Optional[Path] = None) -> None:
    """Deep-merge the exposed Eye settings into ``context_window`` (and the nested
    ``evidence_preservation``), preserving every other key (backend/model_name/
    token_budget/...). Values are coerced and clamped. Atomic write."""
    path = Path(path) if path else eye_config_path()
    cfg = _load(path)

    cw = cfg.get("context_window")
    if not isinstance(cw, dict):
        cw = {}

    if "store_full_payload" in settings:
        cw["store_full_payload"] = bool(settings["store_full_payload"])
    if "sealed_payload_recent_uncompressed" in settings:
        cw["sealed_payload_recent_uncompressed"] = max(0, int(settings["sealed_payload_recent_uncompressed"]))
    if "max_total_tokens" in settings:
        cw["max_total_tokens"] = max(1000, int(settings["max_total_tokens"]))
    if "lock_max_total_tokens" in settings:
        cw["lock_max_total_tokens"] = bool(settings["lock_max_total_tokens"])
    if "max_tool_output_chars" in settings:
        cw["max_tool_output_chars"] = max(1000, int(settings["max_tool_output_chars"]))
    if "confidence_threshold" in settings:
        ev = cw.get("evidence_preservation")
        if not isinstance(ev, dict):
            ev = {}
        ev["confidence_threshold"] = min(1.0, max(0.0, float(settings["confidence_threshold"])))
        cw["evidence_preservation"] = ev

    cfg["context_window"] = cw

    # Reasoning behaviors live in a sibling top-level "reasoning" section.
    rs = cfg.get("reasoning")
    if not isinstance(rs, dict):
        rs = {}
    if "enable_decomposition" in settings:
        rs["enable_decomposition"] = bool(settings["enable_decomposition"])
    if "max_sub_questions" in settings:
        rs["max_sub_questions"] = min(20, max(1, int(settings["max_sub_questions"])))
    if "enable_hierarchy" in settings:
        rs["enable_hierarchy"] = bool(settings["enable_hierarchy"])
    if "max_narratives" in settings:
        rs["max_narratives"] = min(30, max(1, int(settings["max_narratives"])))
    if "max_sub_narratives" in settings:
        rs["max_sub_narratives"] = min(20, max(1, int(settings["max_sub_narratives"])))
    if "max_iterations" in settings:
        rs["max_iterations"] = min(2000, max(20, int(settings["max_iterations"])))
    if "enable_premise_verification" in settings:
        rs["enable_premise_verification"] = bool(settings["enable_premise_verification"])
    if "enable_question_memory" in settings:
        rs["enable_question_memory"] = bool(settings["enable_question_memory"])
    if "prior_findings_count" in settings:
        rs["prior_findings_count"] = min(20, max(0, int(settings["prior_findings_count"])))
    if "model_retry_max_attempts" in settings:
        rs["model_retry_max_attempts"] = min(6, max(1, int(settings["model_retry_max_attempts"])))
    if "auto_segment_question" in settings:
        rs["auto_segment_question"] = bool(settings["auto_segment_question"])
    if "enable_auto_map_reduce" in settings:
        rs["enable_auto_map_reduce"] = bool(settings["enable_auto_map_reduce"])
    if "auto_map_reduce_row_threshold" in settings:
        rs["auto_map_reduce_row_threshold"] = min(1000000, max(100, int(settings["auto_map_reduce_row_threshold"])))
    if "enable_reasoning_trace" in settings:
        rs["enable_reasoning_trace"] = bool(settings["enable_reasoning_trace"])
    if "answer_temperature" in settings:
        rs["answer_temperature"] = min(2.0, max(0.0, float(settings["answer_temperature"])))
    if "planning_temperature" in settings:
        rs["planning_temperature"] = min(2.0, max(0.0, float(settings["planning_temperature"])))
    if "max_output_tokens" in settings:
        rs["max_output_tokens"] = min(32768, max(256, int(settings["max_output_tokens"])))
    if "rag_top_k" in settings:
        rs["rag_top_k"] = min(20, max(1, int(settings["rag_top_k"])))
    if "rag_min_score" in settings:
        rs["rag_min_score"] = min(1.0, max(0.0, float(settings["rag_min_score"])))
    if "rag_semantic_min_score" in settings:
        rs["rag_semantic_min_score"] = min(1.0, max(0.0, float(settings["rag_semantic_min_score"])))
    if "rag_subquestion_aware" in settings:
        rs["rag_subquestion_aware"] = bool(settings["rag_subquestion_aware"])
    if "history_window_turns" in settings:
        rs["history_window_turns"] = min(50, max(1, int(settings["history_window_turns"])))
    if "enable_summary_buffer" in settings:
        rs["enable_summary_buffer"] = bool(settings["enable_summary_buffer"])
    if "enable_conversation_recall" in settings:
        rs["enable_conversation_recall"] = bool(settings["enable_conversation_recall"])
    if "conversation_recall_top_k" in settings:
        rs["conversation_recall_top_k"] = min(20, max(1, int(settings["conversation_recall_top_k"])))
    if "search_max_rows" in settings:
        rs["search_max_rows"] = min(10000, max(1, int(settings["search_max_rows"])))
    if rs:
        cfg["reasoning"] = rs

    # Embedding / semantic retrieval — top-level "embedding" section.
    em = cfg.get("embedding")
    if not isinstance(em, dict):
        em = {}
    if "embedding_enabled" in settings:
        em["enabled"] = bool(settings["embedding_enabled"])
    if "embedding_model" in settings:
        em["model"] = str(settings["embedding_model"]).strip() or "nomic-embed-text"
    if "embedding_endpoint" in settings:
        em["endpoint"] = str(settings["embedding_endpoint"]).strip() or "http://localhost:11434"
    if "embedding_index_evidence" in settings:
        em["index_evidence"] = bool(settings["embedding_index_evidence"])
    if em:
        cfg["embedding"] = em

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
