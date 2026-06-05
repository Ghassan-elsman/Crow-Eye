"""
EyeAuthorship — provenance stamp for Wings and Semantic Mappings authored by the EYE agent.

Background
----------
When EYE creates or edits a Wing or Semantic Mapping on behalf of an
investigator, the resulting JSON needs to carry an auditable record of
*who* (EYE vs. human), *when*, and *why* the change happened. This
module defines the canonical metadata block.

The same dataclass is embedded in both :class:`WingConfig` and
:class:`SemanticMapping` / :class:`SemanticRule`, so analysts can filter
either catalog by author or query the audit trail uniformly.

Ghassan Elsman Protocol (GEP)
-----------------------------
Three GEP rules govern EYE write actions:

* **Rule 9 — Reason-Required**: ``reason`` must be non-empty.
* **Rule 10 — Evidence-Link (write-side)**: ``related_evidence`` must
  list at least one ``database:table:rowid`` reference. Unresolvable
  refs are surfaced via ``unresolved_evidence_refs`` (soft-warning
  model); the wing/mapping is still persisted but GEP Rule 10 is
  logged as ``"partially_satisfied"``.
* **Rule 11 — Eye-Stamped**: every artifact EYE persists carries a
  populated ``EyeAuthorship`` block.

The ``correlation_edit_*`` handlers refuse to mutate any item whose
``created_by`` does not start with ``"eye"`` — built-in mappings and
human-authored wings remain read-only to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    """Return current UTC time as ISO 8601 (no microseconds)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class EyeAuthorship:
    """Provenance metadata for an EYE-authored Wing or Semantic Mapping.

    The ``created_by`` convention:
      - ``"human"`` — never written by EYE; legacy / analyst-authored.
      - ``"eye"`` — EYE wrote it but model identity wasn't captured.
      - ``"eye:<model_name>"`` — EYE wrote it; full model attribution.

    Only items where ``created_by`` starts with ``"eye"`` are editable
    by EYE. This invariant is enforced by the edit handlers, not here.
    """

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    created_by: str = "human"
    created_by_agent: bool = False
    created_at: str = field(default_factory=_utc_now)
    eye_version: str = ""

    # ------------------------------------------------------------------ #
    # Forensic justification (GEP Rule 9 + 10)
    # ------------------------------------------------------------------ #
    reason: str = ""
    related_evidence: List[str] = field(default_factory=list)
    unresolved_evidence_refs: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Conversation context — links the artifact back to the EYE session
    # that produced it. Empty when the artifact was authored outside the
    # EYE chat (e.g. by a future scripted pipeline).
    # ------------------------------------------------------------------ #
    case_id: str = ""
    conversation_id: str = ""

    # ------------------------------------------------------------------ #
    # GEP compliance record (populated by the handler at write time).
    # Values like {"rule_9": "satisfied", "rule_10": "partially_satisfied",
    # "rule_11": "satisfied"} so the Compliance Panel can render
    # per-rule status without re-deriving it.
    # ------------------------------------------------------------------ #
    gep_rules_applied: Dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Edit history — append-only list. Each entry:
    # {"at": "<iso8601>", "by": "eye:<model>", "reason": "<str>",
    # "diff_summary": "<short text>"}
    # The original ``created_at`` is not mutated; the latest entry
    # records the most recent edit.
    # ------------------------------------------------------------------ #
    edit_history: List[Dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Construction helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def for_eye(
        cls,
        model_name: str,
        *,
        reason: str,
        related_evidence: Optional[List[str]] = None,
        unresolved_evidence_refs: Optional[List[str]] = None,
        case_id: str = "",
        conversation_id: str = "",
        eye_version: str = "",
        gep_rules_applied: Optional[Dict[str, str]] = None,
    ) -> "EyeAuthorship":
        """Construct an authorship block stamped as EYE-authored.

        Used by the create handlers. ``model_name`` becomes part of
        ``created_by`` so analysts can tell which backend produced the
        artifact (useful when switching between local/cloud models
        during one case).
        """
        return cls(
            created_by=f"eye:{model_name}" if model_name else "eye",
            created_by_agent=True,
            created_at=_utc_now(),
            eye_version=eye_version,
            reason=reason,
            related_evidence=list(related_evidence or []),
            unresolved_evidence_refs=list(unresolved_evidence_refs or []),
            case_id=case_id,
            conversation_id=conversation_id,
            gep_rules_applied=dict(gep_rules_applied or {}),
            edit_history=[],
        )

    def append_edit(
        self,
        *,
        model_name: str,
        reason: str,
        diff_summary: str = "",
        unresolved_evidence_refs: Optional[List[str]] = None,
    ) -> None:
        """Record an EYE edit. Original ``created_at`` is preserved."""
        entry: Dict[str, Any] = {
            "at": _utc_now(),
            "by": f"eye:{model_name}" if model_name else "eye",
            "reason": reason,
        }
        if diff_summary:
            entry["diff_summary"] = diff_summary
        if unresolved_evidence_refs:
            entry["unresolved_evidence_refs"] = list(unresolved_evidence_refs)
        self.edit_history.append(entry)

    # ------------------------------------------------------------------ #
    # Predicates
    # ------------------------------------------------------------------ #
    @property
    def is_eye_authored(self) -> bool:
        """True iff EYE created the item (i.e. analyst-authored items
        return False). Edit handlers use this as the read-only gate."""
        return self.created_by.startswith("eye")

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dict suitable for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["EyeAuthorship"]:
        """Reconstruct from a plain dict. ``None`` input returns ``None``
        so legacy items (no authorship block) round-trip cleanly."""
        if not data:
            return None
        # Drop any unknown keys so future schema additions don't break
        # the from_dict path on older code.
        known = {f for f in cls.__dataclass_fields__.keys()}
        cleaned = {k: v for k, v in data.items() if k in known}
        return cls(**cleaned)

    # ------------------------------------------------------------------ #
    # Display
    # ------------------------------------------------------------------ #
    def human_summary(self) -> str:
        """One-line summary for the UI / audit trail."""
        if not self.is_eye_authored:
            return "Authored by analyst (no EYE provenance)."
        first = self.created_at or "(unknown time)"
        evidence_n = len(self.related_evidence)
        unresolved_n = len(self.unresolved_evidence_refs)
        edit_n = len(self.edit_history)
        bits = [
            f"Created by {self.created_by} at {first}",
            f"reason: {self.reason or '(none)'}",
            f"evidence: {evidence_n} ref(s)" + (f", {unresolved_n} unresolved" if unresolved_n else ""),
        ]
        if edit_n:
            bits.append(f"{edit_n} edit(s)")
        return "; ".join(bits) + "."


__all__ = ["EyeAuthorship"]
