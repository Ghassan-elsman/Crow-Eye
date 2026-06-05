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

    out: Dict[str, object] = {}
    try:
        out["store_full_payload"] = bool(cw.get("store_full_payload", DEFAULTS["store_full_payload"]))
        out["sealed_payload_recent_uncompressed"] = int(cw.get("sealed_payload_recent_uncompressed", DEFAULTS["sealed_payload_recent_uncompressed"]))
        out["max_total_tokens"] = int(cw.get("max_total_tokens", DEFAULTS["max_total_tokens"]))
        out["lock_max_total_tokens"] = bool(cw.get("lock_max_total_tokens", DEFAULTS["lock_max_total_tokens"]))
        out["max_tool_output_chars"] = int(cw.get("max_tool_output_chars", DEFAULTS["max_tool_output_chars"]))
        out["confidence_threshold"] = float(ev.get("confidence_threshold", DEFAULTS["confidence_threshold"]))
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

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
