"""
Rule switches — which behaviour rules an administrator has turned off.

One saved setting, ``uba_disabled_rules`` in Crow-Eye's global_config.json (a
list of rule ids, built-in or analyst-created), behind both switch screens:
Settings -> User Behavior and the User Behavior window's Rules view. It is
global, so it applies to every case.

A rule that is off is not run. The coverage panel shows it as ``off``
("Turned off in Settings") - never "unavailable" and never "found nothing",
because absence of its events then says nothing about the evidence. The
persisted event store's freshness stamp includes ``disabled_hash()``, so
turning a rule off or on makes the next analysis run again.

Read through config.case_history_manager.read_global_setting and written
through write_global_setting - the same file the Settings dialog saves, no
second config file. Headless: no Qt. Where Crow-Eye's config package is not
importable (a headless host), nothing is off.
"""

import hashlib
import json
import logging
import threading
from typing import Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

SETTING_KEY = "uba_disabled_rules"

_LOCK = threading.Lock()


def _read_setting(default):
    try:
        from config.case_history_manager import read_global_setting
    except Exception:                       # pragma: no cover - headless host
        return default
    return read_global_setting(SETTING_KEY, default)


def _write_setting(value) -> bool:
    try:
        from config.case_history_manager import write_global_setting
    except Exception as e:                  # pragma: no cover - headless host
        logger.warning("UBA: rule switches cannot be saved here: %s", e)
        return False
    return write_global_setting(SETTING_KEY, value)


def _clean(ids: Optional[Iterable]) -> List[str]:
    out = []
    for rule_id in ids or []:
        text = str(rule_id or "").strip()
        if text and text not in out:
            out.append(text)
    return sorted(out)


def disabled_rule_ids() -> Set[str]:
    """Ids of every rule turned off in Settings (built-in or user rules)."""
    value = _read_setting([])
    if not isinstance(value, (list, tuple)):
        return set()
    return set(_clean(value))


def is_rule_enabled(rule_id: str) -> bool:
    return str(rule_id) not in disabled_rule_ids()


def set_rule_enabled(rule_id: str, on: bool) -> bool:
    """Turn one rule on or off. True when the setting was saved."""
    rule_id = str(rule_id or "").strip()
    if not rule_id:
        return False
    with _LOCK:
        before = disabled_rule_ids()
        after = set(before)
        if on:
            after.discard(rule_id)
        else:
            after.add(rule_id)
        if after == before:
            return True
        saved = _write_setting(_clean(after))
    if saved:
        _record_change(before, after)
    return saved


def set_disabled_rules(rule_ids: Iterable[str]) -> bool:
    """Replace the whole off-list (Settings' Save, and "Turn all on")."""
    with _LOCK:
        before = disabled_rule_ids()
        after = set(_clean(rule_ids))
        if after == before:
            return True
        saved = _write_setting(_clean(after))
    if saved:
        _record_change(before, after)
    return saved


CLASS_LABELS = {
    "user": "User",
    "application": "Application",
    "system_app": "System program",
    "system": "System",
}
CLASS_ORDER = ("user", "application", "system_app", "system")
SEVERITY_ORDER = ("critical", "suspicious", "notable", "routine")


def switch_rows(rules_config: Optional[dict] = None) -> List[dict]:
    """Every rule as a switch row - the list both switch screens draw.

    Grouped by behaviour class (User, Application, System program, System),
    most severe first inside a class. ``user_rule`` is False for every
    built-in rule and True for the analyst's own (uba_user_rules.json), which
    carry ``user_kind`` (table / derived) and, when they fail validation,
    ``invalid`` (the reasons). ``rules_config`` None reads both files now.
    """
    if rules_config is None:
        from uba.engine.rule_loader import load_rules
        from uba.engine.user_rules import merged_rules_config
        rules_config = merged_rules_config(load_rules())
    off = disabled_rule_ids()
    rows = []
    for rule in rules_config.get("rules", []):
        cls = rule.get("behavior_class", "")
        rows.append({
            "rule_id": rule["id"],
            "title": rule.get("title", rule["id"]),
            "activity": rule.get("activity", ""),
            "behavior_class": cls,
            "class_label": CLASS_LABELS.get(cls, cls or "Other"),
            "severity": rule.get("severity", "routine"),
            "how": rule.get("how", ""),
            "enabled": rule["id"] not in off,
            "user_rule": bool(rule.get("user_rule", False)),
            "user_kind": rule.get("user_kind", ""),
            "invalid": list(rule.get("invalid") or []),
        })

    def _key(r):
        cls_i = (CLASS_ORDER.index(r["behavior_class"])
                 if r["behavior_class"] in CLASS_ORDER else len(CLASS_ORDER))
        sev_i = (SEVERITY_ORDER.index(r["severity"])
                 if r["severity"] in SEVERITY_ORDER else len(SEVERITY_ORDER))
        return (cls_i, sev_i, r["title"].lower())
    rows.sort(key=_key)
    return rows


def disabled_hash(ids: Optional[Iterable[str]] = None) -> str:
    """SHA-256 of the sorted off-list: part of the event store's freshness
    stamp, so a store built under other switches is never reused."""
    ids = disabled_rule_ids() if ids is None else ids
    text = json.dumps(_clean(ids))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_change(before: Set[str], after: Set[str]):
    """Into the open case's custody ledger: which rules ran is part of how
    the case was worked, like any other setting change."""
    try:
        from utils import custody as _custody
        _custody.ledger(None, "settings changed", scope="global",
                        changes={SETTING_KEY: [_clean(before), _clean(after)]})
    except Exception:
        pass
