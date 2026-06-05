"""
Correlation Config Handlers — EYE write-side tools for Wings + Semantic Mappings.

These four handlers let the EYE agent author and edit correlation
configuration on behalf of the investigator:

* ``handle_correlation_create_wing``
* ``handle_correlation_edit_wing``
* ``handle_correlation_create_semantic_mapping``
* ``handle_correlation_edit_semantic_mapping``

Every write is governed by three Ghassan Elsman Protocol rules:

* **Rule 9 — Reason-Required**: ``reason`` parameter must be non-empty.
* **Rule 10 — Evidence-Link (write-side)**: ``related_evidence`` must
  contain at least one ``database:table:rowid`` reference. The handler
  attempts to resolve each ref; unresolved refs are recorded as a soft
  warning (the artifact is still persisted) and GEP Rule 10 is logged
  as ``"partially_satisfied"``.
* **Rule 11 — Eye-Stamped**: every persisted artifact carries a
  populated :class:`EyeAuthorship` block.

The edit handlers additionally enforce the **read-only invariant**:
they refuse to modify any Wing or SemanticMapping whose
``eye_authorship.created_by`` does not start with ``"eye"`` — built-in
mappings and human-authored wings stay analyst-owned.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from correlation_engine.config.eye_authorship import EyeAuthorship
from correlation_engine.config.wing_config import WingConfig, WingFeatherReference
from correlation_engine.config.semantic_mapping import (
    SemanticMapping,
    SemanticRule,
    SemanticCondition,
)

logger = logging.getLogger(__name__)


# Regex for the GEP Rule 10 "database:table:rowid" evidence-ref shape.
# rowid must be a positive integer; database/table names allow letters,
# digits, underscore, and dot (for files like Log_Claw.db).
_EVIDENCE_REF_RE = re.compile(r'^([A-Za-z0-9_.\-]+):([A-Za-z0-9_]+):(\d+)$')


class CorrelationConfigHandlers:
    """EYE write-side tools for correlation-engine configuration.

    Wired into :meth:`ContextManager._initialize_tool_handlers`. One
    instance per ContextManager; shares the context manager's case
    directory, model router, and database service.
    """

    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(__name__)

    # ==================================================================
    # Tool handlers — these are what the LLM calls
    # ==================================================================

    def handle_correlation_create_wing(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Wing in the active case's wings directory.

        Wired to LLM tool ``correlation_create_wing``. Returns
        ``{"success": bool, "wing_id"?: str, "path"?: str,
         "human_summary"?: str, "gep_rules": dict, "error"?: str}``.
        """
        try:
            # ---- GEP Rule 9: Reason-Required ----
            reason = (params.get("reason") or "").strip()
            if not reason:
                return self._gep_violation("rule_9", "`reason` is required (GEP Rule 9 — Reason-Required).")

            # ---- Argument coercion + GEP Rule 10 evidence-link ----
            related_evidence = list(params.get("related_evidence") or [])
            if not related_evidence:
                return self._gep_violation(
                    "rule_10",
                    "`related_evidence` is required and must contain at least one "
                    "'database:table:rowid' reference (GEP Rule 10 — Evidence-Link).",
                )
            resolved_status, unresolved_refs = self._resolve_evidence_refs(related_evidence)

            # ---- Required structural args ----
            wing_name = (params.get("wing_name") or "").strip()
            proves = (params.get("proves") or "").strip()
            feathers_raw = params.get("feathers") or []
            if not wing_name:
                return self._fail("Missing required parameter: `wing_name`.")
            if not proves:
                return self._fail("Missing required parameter: `proves` (what this wing forensically demonstrates).")
            if not feathers_raw:
                return self._fail("Missing required parameter: `feathers` (at least one feather reference).")

            # Build the wing
            wing_id = f"eye_wing_{uuid.uuid4().hex[:8]}"
            config_name = wing_name.lower().replace(" ", "_").replace("-", "_")
            authorship = self._build_authorship(
                reason=reason,
                related_evidence=related_evidence,
                unresolved_evidence_refs=unresolved_refs,
                gep_rule_10_status=resolved_status,
            )
            wing = WingConfig(
                config_name=config_name,
                wing_name=wing_name,
                wing_id=wing_id,
                description=params.get("description", "") or "",
                proves=proves,
                author=authorship.created_by,  # mirror authorship into legacy author field
                feathers=[self._coerce_feather_ref(f) for f in feathers_raw],
                time_window_minutes=int(params.get("time_window_minutes") or 180),
                minimum_matches=int(params.get("minimum_matches") or 1),
                anchor_priority=list(params.get("anchor_priority") or []),
                semantic_rules=list(params.get("semantic_rules") or []),
                tags=list(params.get("tags") or []),
                case_types=list(params.get("case_types") or []),
                eye_authorship=authorship,
            )

            # ---- Persist ----
            wings_dir = self._case_wings_dir()
            wings_dir.mkdir(parents=True, exist_ok=True)
            target = wings_dir / f"{wing_id}.json"
            if target.exists():
                # Extremely unlikely with uuid4[:8], but guard anyway.
                return self._fail(f"Target file already exists: {target}")
            self._atomic_write_json(target, wing.to_dict())

            self._record_audit_event(
                action="wing_created",
                target_path=str(target),
                authorship=authorship,
            )

            return {
                "success": True,
                "wing_id": wing_id,
                "path": str(target),
                "human_summary": authorship.human_summary(),
                "gep_rules": authorship.gep_rules_applied,
            }
        except Exception as e:
            self.logger.exception("handle_correlation_create_wing failed")
            return self._fail(f"Unexpected error: {e}")

    def handle_correlation_edit_wing(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Edit a Wing previously authored by EYE.

        Requires ``wing_id`` to identify the target. Refuses to modify
        anything authored by a human or shipped as built-in.
        """
        try:
            reason = (params.get("reason") or "").strip()
            if not reason:
                return self._gep_violation("rule_9", "`reason` is required for every edit (GEP Rule 9).")

            wing_id = (params.get("wing_id") or "").strip()
            if not wing_id:
                return self._fail("Missing required parameter: `wing_id`.")

            wings_dir = self._case_wings_dir()
            target = wings_dir / f"{wing_id}.json"
            if not target.exists():
                return self._fail(f"No wing found with id '{wing_id}' (looked at {target}).")

            with open(target, "r", encoding="utf-8") as f:
                existing = json.load(f)
            wing = WingConfig.from_dict(existing)

            # Read-only invariant
            if wing.eye_authorship is None or not wing.eye_authorship.is_eye_authored:
                return self._fail(
                    f"Wing '{wing_id}' was not authored by EYE — cannot edit "
                    "(built-in and human-authored wings are read-only to the agent). "
                    "Suggest the change to the analyst instead."
                )

            # Apply diffs (only the fields the agent supplied are mutated;
            # everything else stays put).
            diff_summary_parts: List[str] = []
            for field_name in (
                "wing_name", "description", "proves",
                "time_window_minutes", "minimum_matches",
            ):
                if field_name in params and params[field_name] is not None:
                    setattr(wing, field_name, params[field_name])
                    diff_summary_parts.append(field_name)
            if "feathers" in params and params["feathers"] is not None:
                wing.feathers = [self._coerce_feather_ref(f) for f in params["feathers"]]
                diff_summary_parts.append("feathers")
            for list_field in ("anchor_priority", "semantic_rules", "tags", "case_types"):
                if list_field in params and params[list_field] is not None:
                    setattr(wing, list_field, list(params[list_field]))
                    diff_summary_parts.append(list_field)

            # Evidence link for the edit itself (still GEP Rule 10).
            edit_related_evidence = list(params.get("related_evidence") or [])
            resolved_status = "satisfied"
            unresolved_refs: List[str] = []
            if edit_related_evidence:
                resolved_status, unresolved_refs = self._resolve_evidence_refs(edit_related_evidence)
                wing.eye_authorship.related_evidence.extend(edit_related_evidence)
                if unresolved_refs:
                    wing.eye_authorship.unresolved_evidence_refs.extend(unresolved_refs)
                    resolved_status = "partially_satisfied"
            else:
                # Edits inherit the original mapping's evidence by default;
                # treat the absence as "no new evidence cited" rather than a hard fail.
                resolved_status = "satisfied"

            model_name = self._current_model_name()
            wing.eye_authorship.append_edit(
                model_name=model_name,
                reason=reason,
                diff_summary=", ".join(diff_summary_parts) or "(no field changes)",
                unresolved_evidence_refs=unresolved_refs,
            )
            wing.eye_authorship.gep_rules_applied["rule_10_last_edit"] = resolved_status
            wing.last_modified = self._now_iso()

            self._atomic_write_json(target, wing.to_dict())
            self._record_audit_event(
                action="wing_edited",
                target_path=str(target),
                authorship=wing.eye_authorship,
                extra={"diff": diff_summary_parts},
            )
            return {
                "success": True,
                "wing_id": wing.wing_id,
                "path": str(target),
                "human_summary": wing.eye_authorship.human_summary(),
                "gep_rules": wing.eye_authorship.gep_rules_applied,
                "diff": diff_summary_parts,
            }
        except Exception as e:
            self.logger.exception("handle_correlation_edit_wing failed")
            return self._fail(f"Unexpected error: {e}")

    def handle_correlation_create_semantic_mapping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new SemanticMapping or SemanticRule in the case scope."""
        try:
            reason = (params.get("reason") or "").strip()
            if not reason:
                return self._gep_violation("rule_9", "`reason` is required (GEP Rule 9).")

            related_evidence = list(params.get("related_evidence") or [])
            if not related_evidence:
                return self._gep_violation(
                    "rule_10",
                    "`related_evidence` is required (GEP Rule 10).",
                )
            resolved_status, unresolved_refs = self._resolve_evidence_refs(related_evidence)

            mapping_type = (params.get("mapping_type") or "mapping").strip().lower()
            if mapping_type not in ("mapping", "rule"):
                return self._fail(f"`mapping_type` must be 'mapping' or 'rule'; got {mapping_type!r}.")

            authorship = self._build_authorship(
                reason=reason,
                related_evidence=related_evidence,
                unresolved_evidence_refs=unresolved_refs,
                gep_rule_10_status=resolved_status,
            )

            mappings_dir = self._case_mappings_dir()
            mappings_dir.mkdir(parents=True, exist_ok=True)

            if mapping_type == "mapping":
                source = (params.get("source") or "").strip()
                field = (params.get("field") or "").strip()
                semantic_value = (params.get("semantic_value") or "").strip()
                if not (source and field and semantic_value):
                    return self._fail("`source`, `field`, and `semantic_value` are all required for a mapping.")
                m = SemanticMapping(
                    source=source,
                    field=field,
                    technical_value=params.get("technical_value", "") or "",
                    semantic_value=semantic_value,
                    description=params.get("description", "") or "",
                    category=params.get("category", "") or "",
                    severity=params.get("severity", "info") or "info",
                    pattern=params.get("pattern", "") or "",
                    confidence=float(params.get("confidence", 1.0)),
                    mapping_source="eye",
                    scope=(params.get("scope") or "global"),
                    wing_id=params.get("wing_id"),
                    eye_authorship=authorship,
                )
                artifact_id = f"eye_mapping_{uuid.uuid4().hex[:8]}"
                target = mappings_dir / f"{artifact_id}.json"
                self._atomic_write_json(target, m.to_dict())
            else:
                conditions_raw = params.get("conditions") or []
                if not conditions_raw:
                    return self._fail("A `rule` requires at least one condition in `conditions`.")
                conditions = [
                    SemanticCondition(
                        feather_id=c.get("feather_id", ""),
                        field_name=c.get("field_name", ""),
                        value=c.get("value", "*"),
                        operator=c.get("operator", "equals"),
                    )
                    for c in conditions_raw
                ]
                r = SemanticRule(
                    rule_id=f"eye_rule_{uuid.uuid4().hex[:8]}",
                    name=(params.get("name") or params.get("semantic_value") or "EYE Rule"),
                    semantic_value=(params.get("semantic_value") or ""),
                    description=params.get("description", "") or "",
                    conditions=conditions,
                    logic_operator=(params.get("logic_operator") or "AND"),
                    scope=(params.get("scope") or "global"),
                    wing_id=params.get("wing_id"),
                    category=params.get("category", "") or "",
                    severity=params.get("severity", "info") or "info",
                    confidence=float(params.get("confidence", 1.0)),
                    eye_authorship=authorship,
                )
                artifact_id = r.rule_id
                target = mappings_dir / f"{artifact_id}.json"
                self._atomic_write_json(target, r.to_dict())

            self._record_audit_event(
                action=f"semantic_{mapping_type}_created",
                target_path=str(target),
                authorship=authorship,
            )
            return {
                "success": True,
                "mapping_type": mapping_type,
                "artifact_id": artifact_id,
                "path": str(target),
                "human_summary": authorship.human_summary(),
                "gep_rules": authorship.gep_rules_applied,
            }
        except Exception as e:
            self.logger.exception("handle_correlation_create_semantic_mapping failed")
            return self._fail(f"Unexpected error: {e}")

    def handle_correlation_edit_semantic_mapping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Edit a SemanticMapping or SemanticRule previously authored by EYE."""
        try:
            reason = (params.get("reason") or "").strip()
            if not reason:
                return self._gep_violation("rule_9", "`reason` is required for every edit (GEP Rule 9).")

            artifact_id = (params.get("artifact_id") or "").strip()
            if not artifact_id:
                return self._fail("Missing required parameter: `artifact_id`.")

            mappings_dir = self._case_mappings_dir()
            target = mappings_dir / f"{artifact_id}.json"
            if not target.exists():
                return self._fail(f"No EYE-authored semantic artifact found with id '{artifact_id}'.")

            with open(target, "r", encoding="utf-8") as f:
                existing = json.load(f)

            # Detect mapping vs rule by shape
            is_rule = "conditions" in existing and isinstance(existing.get("conditions"), list) and existing.get("rule_id")
            obj = SemanticRule.from_dict(existing) if is_rule else SemanticMapping.from_dict(existing)

            if obj.eye_authorship is None or not obj.eye_authorship.is_eye_authored:
                return self._fail(
                    f"Artifact '{artifact_id}' was not authored by EYE — cannot edit. "
                    "Built-in and human-authored mappings are read-only to the agent."
                )

            diff_summary_parts: List[str] = []
            if is_rule:
                for f_name in ("name", "semantic_value", "description", "logic_operator",
                               "category", "severity", "confidence"):
                    if f_name in params and params[f_name] is not None:
                        setattr(obj, f_name, params[f_name])
                        diff_summary_parts.append(f_name)
                if "conditions" in params and params["conditions"] is not None:
                    obj.conditions = [
                        SemanticCondition(
                            feather_id=c.get("feather_id", ""),
                            field_name=c.get("field_name", ""),
                            value=c.get("value", "*"),
                            operator=c.get("operator", "equals"),
                        )
                        for c in params["conditions"]
                    ]
                    diff_summary_parts.append("conditions")
            else:
                for f_name in ("source", "field", "technical_value", "semantic_value",
                               "description", "category", "severity", "pattern",
                               "confidence"):
                    if f_name in params and params[f_name] is not None:
                        setattr(obj, f_name, params[f_name])
                        diff_summary_parts.append(f_name)

            # Evidence-link bookkeeping
            edit_evidence = list(params.get("related_evidence") or [])
            resolved_status = "satisfied"
            unresolved_refs: List[str] = []
            if edit_evidence:
                resolved_status, unresolved_refs = self._resolve_evidence_refs(edit_evidence)
                obj.eye_authorship.related_evidence.extend(edit_evidence)
                if unresolved_refs:
                    obj.eye_authorship.unresolved_evidence_refs.extend(unresolved_refs)
                    resolved_status = "partially_satisfied"

            obj.eye_authorship.append_edit(
                model_name=self._current_model_name(),
                reason=reason,
                diff_summary=", ".join(diff_summary_parts) or "(no field changes)",
                unresolved_evidence_refs=unresolved_refs,
            )
            obj.eye_authorship.gep_rules_applied["rule_10_last_edit"] = resolved_status

            self._atomic_write_json(target, obj.to_dict())
            self._record_audit_event(
                action="semantic_rule_edited" if is_rule else "semantic_mapping_edited",
                target_path=str(target),
                authorship=obj.eye_authorship,
                extra={"diff": diff_summary_parts},
            )
            return {
                "success": True,
                "artifact_id": artifact_id,
                "path": str(target),
                "human_summary": obj.eye_authorship.human_summary(),
                "gep_rules": obj.eye_authorship.gep_rules_applied,
                "diff": diff_summary_parts,
            }
        except Exception as e:
            self.logger.exception("handle_correlation_edit_semantic_mapping failed")
            return self._fail(f"Unexpected error: {e}")

    # ==================================================================
    # Internals
    # ==================================================================

    def _build_authorship(
        self,
        *,
        reason: str,
        related_evidence: List[str],
        unresolved_evidence_refs: List[str],
        gep_rule_10_status: str,
    ) -> EyeAuthorship:
        """Construct the EyeAuthorship block for a freshly created artifact."""
        rule_10 = gep_rule_10_status if gep_rule_10_status in (
            "satisfied", "partially_satisfied"
        ) else "satisfied"
        return EyeAuthorship.for_eye(
            model_name=self._current_model_name(),
            reason=reason,
            related_evidence=related_evidence,
            unresolved_evidence_refs=unresolved_evidence_refs,
            case_id=self._current_case_id(),
            conversation_id=self._current_conversation_id(),
            eye_version=self._current_eye_version(),
            gep_rules_applied={
                "rule_9": "satisfied",
                "rule_10": rule_10,
                "rule_11": "satisfied",
            },
        )

    def _resolve_evidence_refs(
        self, refs: List[str]
    ) -> Tuple[str, List[str]]:
        """Try to resolve each 'database:table:rowid' ref against the case DBs.

        Returns ``(status, unresolved_refs)`` where status is
        ``"satisfied"`` (all resolved) or ``"partially_satisfied"`` (at
        least one unresolved). Malformed refs are treated as unresolved.

        Soft-warning model: never raises — analysts can author against
        archived or partially-loaded cases.
        """
        unresolved: List[str] = []
        db_service = getattr(self.cm, "database_service", None)
        for ref in refs:
            if not isinstance(ref, str):
                unresolved.append(str(ref))
                continue
            m = _EVIDENCE_REF_RE.match(ref.strip())
            if not m:
                unresolved.append(ref)
                continue
            db_name, table, rowid = m.group(1), m.group(2), int(m.group(3))
            if db_service is None:
                # No DB service at hand — can't verify; treat as unresolved
                # but don't block the write.
                unresolved.append(ref)
                continue
            try:
                # Cheap probe: row count for the exact rowid.
                probe_sql = f'SELECT 1 FROM "{table}" WHERE rowid = ? LIMIT 1'
                res = db_service.execute_query(db_name, probe_sql, params=[rowid])
                rows = (res or {}).get("rows") or []
                if not rows:
                    unresolved.append(ref)
            except Exception as e:
                self.logger.debug("Evidence-ref probe failed for %s: %s", ref, e)
                unresolved.append(ref)
        status = "partially_satisfied" if unresolved else "satisfied"
        return status, unresolved

    def _coerce_feather_ref(self, raw: Any) -> WingFeatherReference:
        """Build a WingFeatherReference from a loose dict shape.

        The LLM may send any subset of fields. Defaults match the
        existing built-in wing JSONs.
        """
        if isinstance(raw, WingFeatherReference):
            return raw
        if not isinstance(raw, dict):
            raise ValueError(f"feather entry must be an object, got {type(raw).__name__}")
        return WingFeatherReference(
            feather_config_name=raw.get("feather_config_name", raw.get("feather_id", "")),
            feather_database_path=raw.get("feather_database_path", raw.get("database_filename", "")),
            artifact_type=raw.get("artifact_type", ""),
            feather_id=raw.get("feather_id", ""),
            table_name=raw.get("table_name"),
            artifact_type_override=raw.get("artifact_type_override"),
            weight=float(raw.get("weight", 0.0)),
            tier=int(raw.get("tier", 0)),
            tier_name=raw.get("tier_name", ""),
        )

    # ---------- case / context lookups ---------- #

    def _case_wings_dir(self) -> Path:
        case_root = self._current_case_root()
        return Path(case_root) / "Correlation" / "wings"

    def _case_mappings_dir(self) -> Path:
        case_root = self._current_case_root()
        return Path(case_root) / "Correlation" / "semantic_mappings" / "eye"

    def _current_case_root(self) -> str:
        # CaseDirectoryManager owns the case path; fall back to cwd in tests.
        case_mgr = getattr(self.cm, "case_directory_manager", None)
        if case_mgr is not None:
            for attr in ("case_directory", "case_root", "active_case"):
                v = getattr(case_mgr, attr, None)
                if v:
                    return str(v)
        # Older code path: cm has the path directly
        direct = getattr(self.cm, "case_directory", None)
        if direct:
            return str(direct)
        return os.getcwd()

    def _current_case_id(self) -> str:
        for src in (self.cm, getattr(self.cm, "case_directory_manager", None)):
            if src is None:
                continue
            cid = getattr(src, "case_id", None)
            if cid:
                return str(cid)
        return ""

    def _current_conversation_id(self) -> str:
        for src in (self.cm, getattr(self.cm, "history_manager", None)):
            if src is None:
                continue
            cid = getattr(src, "conversation_id", None)
            if cid:
                return str(cid)
        return ""

    def _current_model_name(self) -> str:
        router = getattr(self.cm, "model_router", None)
        if router is None:
            return ""
        cfg = getattr(router, "config", None) or {}
        try:
            return str(cfg.get("model_name") or cfg.get("backend") or "")
        except AttributeError:
            return ""

    def _current_eye_version(self) -> str:
        # Best-effort: pull from llm_config if present, else empty.
        cfg = getattr(self.cm, "llm_config", None) or {}
        try:
            return str(cfg.get("eye_version") or "")
        except AttributeError:
            return ""

    # ---------- IO + audit ---------- #

    @staticmethod
    def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
        """Write JSON atomically via os.replace so partial writes can't
        corrupt the case directory."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, path)

    def _record_audit_event(
        self,
        *,
        action: str,
        target_path: str,
        authorship: EyeAuthorship,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a structured audit-trail event. Best-effort — never raises."""
        try:
            auditor = getattr(self.cm, "truncation_auditor", None)
            event = {
                "action": action,
                "target_path": target_path,
                "authorship": authorship.to_dict(),
            }
            if extra:
                event.update(extra)
            if auditor is not None and hasattr(auditor, "record_event"):
                auditor.record_event(event)
            else:
                self.logger.info("[EYE-AUTHORSHIP] %s", json.dumps(event, default=str))
        except Exception as e:
            self.logger.debug("audit-trail write failed: %s", e)

    # ---------- result helpers ---------- #

    @staticmethod
    def _fail(message: str) -> Dict[str, Any]:
        return {"success": False, "error": message}

    @staticmethod
    def _gep_violation(rule_id: str, message: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": message,
            "gep_violation": rule_id,
        }

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
