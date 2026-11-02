"""
Analyst-created behaviour rules - the global file, its shape, and how the
rules join the built-in ones.

One file for every case: ``uba_user_rules.json`` in Crow-Eye's config folder
(``config.case_history_manager.default_config_dir()``, beside
global_config.json) - never a case folder and never the repository's
``config/`` folder. The built-in ``uba/config/behavior_rules.json`` is never
written: Sentinel re-derives the built-in rule count from it.

Two kinds of rule, both written in the Wing condition language
(``SemanticCondition`` dicts plus ``condition_groups``), so there is no third
rule format:

``table``    a parsed artifact table plus conditions on its columns, and a
             column map saying where the time, the person and the program are.
``derived``  a named filter over behaviours the engine already found
             (built-in or user rules, by rule id or activity). It emits its own
             event carrying the base event's evidence.

A rule as stored::

    {"id": "user_mimikatz_prefetch", "kind": "table",
     "title": "Mimikatz ran", "activity": "program_run",
     "behavior_class": "user", "severity": "critical",
     "description": "{actor} ran {executable_name}",
     "source": {"db": "prefetch", "table": "prefetch_data"},
     "logic_operator": "AND",
     "conditions": [{"feather_id": "prefetch_data", "field_name": "executable_name",
                     "operator": "contains", "value": "mimikatz"}],
     "condition_groups": [],
     "columns": {"time": "last_executed", "time_basis": "exact",
                 "actor": {"mode": "hive_owner", "column": ""},
                 "app": "executable_name"},
     "aggregation": {"mode": "none"},
     "author": {"created_by": "human", "name": "Ghass"},
     "created_utc": "2026-10-26 18:00:00", "updated_utc": "...", "version": 1}

Validation lives in ``rule_loader.validate_user_rule``; the checks that need
a case (does the table hold that column?) in ``extractors.declarative``.
Headless: stdlib only.
"""

import copy
import getpass
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FILE_NAME = "uba_user_rules.json"
FILE_VERSION = 1

KIND_TABLE = "table"
KIND_DERIVED = "derived"
KINDS = (KIND_TABLE, KIND_DERIVED)

# The extractor names user rules carry in the merged rules list. They are not
# in extractors.EXTRACTORS: BehaviorEngine runs them itself, table rules after
# every built-in extractor and derived rules last, over the store.
EXTRACTOR_TABLE = "declarative_table"
EXTRACTOR_DERIVED = "declarative_derived"

# The event-field "feather" a derived rule's conditions name, and the default
# description of a derived event: the base event's own sentence.
DERIVED_FEATHER = "event"
DEFAULT_DERIVED_DESCRIPTION = "{description}"

_LOCK = threading.Lock()


# --------------------------------------------------------------------- path
def rules_path() -> str:
    """``<config dir>/uba_user_rules.json`` - the same folder as
    global_config.json, so it applies to every case."""
    try:
        from config.case_history_manager import default_config_dir
        folder = default_config_dir()
    except Exception:                       # pragma: no cover - headless host
        appdata = os.getenv("APPDATA")
        if appdata:
            folder = os.path.join(appdata, "CrowEye", "config")
        else:
            folder = os.path.join(os.getenv("XDG_CONFIG_HOME")
                                  or os.path.join(os.path.expanduser("~"), ".config"),
                                  "crow-eye")
    return os.path.join(folder, FILE_NAME)


def _utc_now_text() -> str:
    try:
        from utils.time_utils import get_current_utc, format_forensic_timestamp
        return format_forensic_timestamp(get_current_utc())
    except Exception:                       # pragma: no cover - headless host
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def current_author() -> dict:
    """Who saved a rule, in the shape of the Wing editor's eye_authorship
    (``created_by`` 'human' for an analyst; Eye would write 'eye:<model>')."""
    try:
        name = getpass.getuser()
    except Exception:
        name = ""
    return {"created_by": "human", "name": name}


# --------------------------------------------------------------------- file
def read_file(path: Optional[str] = None) -> dict:
    """The file as stored: ``{"version", "rules": [...]}``. A missing file is
    no rules; an unreadable one is no rules plus ``error`` (logged), never an
    exception - a broken file must not stop the built-in analysis."""
    path = path or rules_path()
    if not os.path.isfile(path):
        return {"version": FILE_VERSION, "rules": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as e:
        logger.error("UBA: your behaviour rules file %s cannot be read: %s", path, e)
        return {"version": FILE_VERSION, "rules": [], "error": str(e)}
    if isinstance(data, list):              # a bare list (an export) is accepted
        data = {"version": FILE_VERSION, "rules": data}
    if not isinstance(data, dict) or not isinstance(data.get("rules", []), list):
        logger.error("UBA: your behaviour rules file %s has no 'rules' list", path)
        return {"version": FILE_VERSION, "rules": [], "error": "no 'rules' list"}
    data.setdefault("version", FILE_VERSION)
    data["rules"] = [r for r in data.get("rules") or [] if isinstance(r, dict)]
    return data


def _write_file(data: dict, path: Optional[str] = None) -> bool:
    """Atomic: a temp file in the same folder replaces the old one, which is
    kept as ``.bak`` first."""
    path = path or rules_path()
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
                    dst.write(src.read())
            except OSError:
                pass
        fd, tmp = tempfile.mkstemp(prefix=".uba_user_rules.", suffix=".tmp", dir=folder)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
        return True
    except OSError as e:
        logger.error("UBA: your behaviour rules could not be saved to %s: %s", path, e)
        return False


# --------------------------------------------------------------- built-ins
def builtin_rule_ids() -> set:
    from uba.engine.rule_loader import load_rules
    return {r["id"] for r in load_rules()["rules"]}


def builtin_activities() -> List[str]:
    """Every activity a built-in rule uses - the list the editor offers, so a
    user rule's events take the icon and label of an existing activity."""
    from uba.engine.rule_loader import load_rules
    return sorted({r["activity"] for r in load_rules()["rules"]})


# ------------------------------------------------------------------ loading
def load_user_rules(builtin_ids=None, path: Optional[str] = None
                    ) -> Tuple[List[dict], Dict[str, List[str]]]:
    """(rules, problems) from the file.

    Every rule comes back, valid or not, except one whose id collides with a
    built-in rule or with an earlier user rule: those are dropped, because two
    rules under one id would make every count, switch and evidence link
    ambiguous. A rule that fails any other check is kept with ``_problems``
    set - the engine does not run it and the coverage page says why.
    ``problems`` maps each rule id (or ``#<n>`` for a rule without one) to its
    reasons, and is logged.
    """
    from uba.engine.rule_loader import validate_user_rule
    if builtin_ids is None:
        builtin_ids = builtin_rule_ids()
    builtin_ids = set(builtin_ids)
    data = read_file(path)
    rules, problems, seen = [], {}, set()
    if data.get("error"):
        problems["(file)"] = ["The rules file cannot be read: %s" % data["error"]]
    for index, raw in enumerate(data.get("rules") or []):
        rule = copy.deepcopy(raw)
        rid = str(rule.get("id") or "").strip()
        key = rid or "#%d" % (index + 1)
        if rid in builtin_ids:
            problems[key] = ["The id '%s' is a built-in rule's id; the rule was "
                             "not loaded. Give it another id." % rid]
            continue
        if rid and rid in seen:
            problems[key] = problems.get(key, []) + [
                "A second rule uses the id '%s'; only the first was loaded." % rid]
            continue
        found = validate_user_rule(rule, builtin_ids)
        if found:
            rule["_problems"] = found
            problems[key] = found
        if not rid:
            continue                        # nothing can refer to it
        seen.add(rid)
        rules.append(rule)
    for key, reasons in problems.items():
        logger.warning("UBA: your behaviour rule %s - %s", key, "; ".join(reasons))
    return rules, problems


def valid_rules(rules: List[dict]) -> List[dict]:
    return [r for r in rules if not r.get("_problems")]


def user_rules_hash(rules: List[dict]) -> str:
    """SHA-256 of the user rules as loaded (sorted by id, bookkeeping keys
    included so an edit always changes it): part of the persisted store's
    freshness stamp. '' when there are none, as before user rules existed."""
    if not rules:
        return ""
    clean = sorted(({k: v for k, v in r.items() if k != "_problems"} for r in rules),
                   key=lambda r: str(r.get("id")))
    text = json.dumps(clean, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extra_sources(rules: List[dict]) -> List[str]:
    """Databases a table rule reads that are not one of UBA's logical names
    (a discovered Target_Artifacts file): their size and mtime join the
    persisted store's stamp, so a re-parse of that file re-runs too."""
    from uba.utils.db_access import DB_CANDIDATES
    out = []
    for rule in rules:
        if rule.get("kind") != KIND_TABLE:
            continue
        db = str((rule.get("source") or {}).get("db") or "")
        if db and db not in DB_CANDIDATES and db not in out:
            out.append(db)
    return sorted(out)


# ------------------------------------------------------------------ merging
def requires_of(rule: dict) -> dict:
    """``requires`` derived from the rule, so coverage treats a user rule as
    it treats a built-in one: a table rule needs its table; a derived rule
    needs nothing of its own (its base rules carry their own status)."""
    if rule.get("kind") == KIND_TABLE:
        source = rule.get("source") or {}
        db, table = source.get("db"), source.get("table")
        if db and table:
            return {"tables": {str(db): [str(table)]}}
    return {}


def how_of(rule: dict) -> str:
    """One sentence for the coverage panel: what the rule reads and tests."""
    conds = list(rule.get("conditions") or [])
    for group in rule.get("condition_groups") or []:
        conds.extend((group or {}).get("conditions") or [])
    words = {"equals": ("is", "is not"), "not_equals": ("is not", "is"),
             "contains": ("contains", "does not contain"),
             "regex": ("matches", "does not match"),
             "greater_than": (">", "is not >"), "less_than": ("<", "is not <"),
             "greater_equal": (">=", "is not >="), "less_equal": ("<=", "is not <=")}
    tests = []
    for cond in conds[:3]:
        op = cond.get("operator", "equals")
        value = cond.get("value", "")
        neg = bool(cond.get("negate"))
        if op == "wildcard" or value == "*":
            tests.append("%s %s" % (cond.get("field_name"),
                                    "has no value" if neg else "has a value"))
        else:
            said = words.get(op, (op, "not " + op))[1 if neg else 0]
            tests.append("%s %s '%s'" % (cond.get("field_name"), said, value))
    more = " and %d more" % (len(conds) - 3) if len(conds) > 3 else ""
    where = (" where " + "; ".join(tests) + more) if tests else ""
    if rule.get("kind") == KIND_TABLE:
        source = rule.get("source") or {}
        return "Your rule: rows of %s (%s)%s." % (source.get("table"), source.get("db"), where)
    base = rule.get("base") or {}
    names = list(base.get("rule_ids") or []) + list(base.get("activities") or [])
    return "Your rule: behaviours %s%s." % (", ".join(names) or "(none)", where)


def to_rule_meta(rule: dict) -> dict:
    """The entry a user rule takes in the merged rules list - the shape every
    built-in rule has, plus ``user_rule`` and the full rule as ``spec``."""
    cls = rule.get("behavior_class") or "user"
    kind = rule.get("kind")
    meta = {
        "id": rule.get("id"),
        "behavior_class": cls,
        "activity": rule.get("activity") or "execution",
        "title": rule.get("title") or rule.get("id"),
        "extractor": EXTRACTOR_TABLE if kind == KIND_TABLE else EXTRACTOR_DERIVED,
        "severity": rule.get("severity") or "notable",
        "color_token": "class_%s" % ("system" if cls == "system_app" else cls),
        "requires": requires_of(rule),
        "how": how_of(rule),
        "user_rule": True,
        "user_kind": kind,
        "spec": rule,
    }
    if rule.get("_problems"):
        meta["invalid"] = list(rule["_problems"])
    return meta


def merged_rules_config(rules_config: dict, rules: Optional[List[dict]] = None,
                        path: Optional[str] = None) -> dict:
    """``rules_config`` (from load_rules) with the user rules appended.

    The built-in dict is not changed. ``user_rules`` (every loaded rule),
    ``user_rules_hash`` and ``builtin_count`` are added for the engine and the
    stamp."""
    builtin = list(rules_config.get("rules") or [])
    if rules is None:
        rules, _problems = load_user_rules({r["id"] for r in builtin}, path=path)
    merged = dict(rules_config)
    merged["rules"] = builtin + [to_rule_meta(r) for r in rules]
    merged["builtin_count"] = len(builtin)
    merged["user_rules"] = rules
    merged["user_rules_hash"] = user_rules_hash(rules)
    return merged


# ------------------------------------------------------------------ editing
_ID_RE = re.compile(r"[^a-z0-9]+")


def suggest_id(title: str, taken=()) -> str:
    """'user_' + a snake_case slug of the title, unique among ``taken``."""
    slug = _ID_RE.sub("_", str(title or "").lower()).strip("_")[:48] or "rule"
    base = "user_" + slug
    candidate, n = base, 2
    taken = set(taken)
    while candidate in taken:
        candidate = "%s_%d" % (base, n)
        n += 1
    return candidate


def save_rule(rule: dict, builtin_ids=None, path: Optional[str] = None
              ) -> Tuple[bool, List[str], Optional[dict]]:
    """Add or replace one rule. (saved, problems, the rule as stored).

    Refused - nothing written - when it fails validation. Stamps the author,
    ``created_utc`` (kept from the stored copy on an edit), ``updated_utc`` and
    ``version`` (+1 on every edit). ``previous_id`` in ``rule`` renames: the
    stored rule under that id is replaced."""
    from uba.engine.rule_loader import validate_user_rule
    if builtin_ids is None:
        builtin_ids = builtin_rule_ids()
    rule = {k: v for k, v in copy.deepcopy(rule).items() if not k.startswith("_")}
    previous_id = str(rule.pop("previous_id", "") or "").strip()
    problems = validate_user_rule(rule, set(builtin_ids))
    if problems:
        return False, problems, None
    with _LOCK:
        data = read_file(path)
        if data.get("error"):
            return False, ["The rules file cannot be read (%s); fix or move it "
                           "before saving." % data["error"]], None
        stored = data.get("rules") or []
        replace_id = previous_id or rule["id"]
        old = next((r for r in stored if r.get("id") == replace_id), None)
        if previous_id and previous_id != rule["id"] and any(
                r.get("id") == rule["id"] for r in stored):
            return False, ["Another rule already uses the id '%s'." % rule["id"]], None
        now = _utc_now_text()
        rule["created_utc"] = (old or {}).get("created_utc") or now
        rule["updated_utc"] = now
        rule["version"] = int((old or {}).get("version") or 0) + 1
        rule["author"] = (old or {}).get("author") or rule.get("author") or current_author()
        if old is not None and old.get("author") and rule.get("author") != current_author():
            rule["edited_by"] = current_author()
        out, replaced = [], False
        for r in stored:
            if r.get("id") == replace_id:
                out.append(rule)
                replaced = True
            else:
                out.append(r)
        if not replaced:
            out.append(rule)
        data["rules"] = out
        data["version"] = FILE_VERSION
        saved = _write_file(data, path)
    if saved:
        logger.info("UBA: your behaviour rule %s saved (version %d)", rule["id"], rule["version"])
        _record_change("saved", rule["id"], rule["version"])
        return True, [], rule
    return False, ["The rules file could not be written - see the application log."], None


def delete_rule(rule_id: str, path: Optional[str] = None) -> bool:
    rule_id = str(rule_id or "")
    with _LOCK:
        data = read_file(path)
        before = data.get("rules") or []
        after = [r for r in before if r.get("id") != rule_id]
        if len(after) == len(before):
            return False
        data["rules"] = after
        saved = _write_file(data, path)
    if saved:
        logger.info("UBA: your behaviour rule %s deleted", rule_id)
        _record_change("deleted", rule_id, None)
    return saved


def export_rules(dest: str, ids=None, path: Optional[str] = None) -> int:
    """Write the rules (all, or those in ``ids``) to ``dest`` as JSON in the
    file's own shape. Returns how many were written."""
    data = read_file(path)
    rules = [r for r in data.get("rules") or [] if not ids or r.get("id") in set(ids)]
    payload = {"version": FILE_VERSION, "exported_utc": _utc_now_text(), "rules": rules}
    with open(dest, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return len(rules)


def import_rules(src: str, builtin_ids=None, path: Optional[str] = None,
                 replace: bool = False) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Add the rules in ``src`` (an export, or a bare list). Returns (added
    ids, [(id, why skipped)]). A rule whose id exists is skipped unless
    ``replace``; one that fails validation is skipped with its reasons."""
    incoming = read_file(src)
    if incoming.get("error"):
        return [], [("(file)", incoming["error"])]
    if builtin_ids is None:
        builtin_ids = builtin_rule_ids()
    existing = {r.get("id") for r in read_file(path).get("rules") or []}
    added, skipped = [], []
    for raw in incoming.get("rules") or []:
        rid = str(raw.get("id") or "")
        if rid in existing and not replace:
            skipped.append((rid, "a rule with this id already exists"))
            continue
        rule = dict(raw)
        if rid in existing:
            rule["previous_id"] = rid
        ok, problems, _stored = save_rule(rule, builtin_ids, path)
        if ok:
            added.append(rid)
            existing.add(rid)
        else:
            skipped.append((rid or "?", "; ".join(problems)))
    return added, skipped


def _record_change(action: str, rule_id: str, version):
    """Into the open case's custody ledger: which rules ran is part of how a
    case was worked, as for the rule switches."""
    try:
        from utils import custody as _custody
        _custody.ledger(None, "settings changed", scope="global",
                        changes={"uba_user_rules": {"action": action, "rule": rule_id,
                                                    "version": version}})
    except Exception:
        pass
