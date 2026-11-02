"""Loads and validates uba/config/behavior_rules.json."""

import json
import os
import logging
import re
from typing import List

logger = logging.getLogger(__name__)

_VALID_CLASSES = {"user", "application", "system_app", "system"}
_VALID_SEVERITIES = {"routine", "notable", "suspicious", "critical"}
_REQUIRED_KEYS = {"id", "behavior_class", "activity", "title", "extractor",
                  "severity", "color_token"}

DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "behavior_rules.json")


class RuleValidationError(ValueError):
    pass


def load_rules(path: str = None) -> dict:
    """Return {'rules': [...], 'requires_collection': [...]} after strict
    validation — a malformed shipped rules file should fail loudly at
    startup, not mid-analysis."""
    path = path or DEFAULT_RULES_PATH
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    rules: List[dict] = data.get("rules", [])
    if not rules:
        raise RuleValidationError("behavior_rules.json contains no rules")

    seen_ids = set()
    for rule in rules:
        missing = _REQUIRED_KEYS - set(rule)
        if missing:
            raise RuleValidationError(
                "rule {!r} missing keys: {}".format(rule.get("id", "?"), sorted(missing)))
        if rule["id"] in seen_ids:
            raise RuleValidationError("duplicate rule id {!r}".format(rule["id"]))
        seen_ids.add(rule["id"])
        if rule["behavior_class"] not in _VALID_CLASSES:
            raise RuleValidationError(
                "rule {!r}: invalid behavior_class {!r}".format(
                    rule["id"], rule["behavior_class"]))
        if rule["severity"] not in _VALID_SEVERITIES:
            raise RuleValidationError(
                "rule {!r}: invalid severity {!r}".format(rule["id"], rule["severity"]))
        requires = rule.get("requires", {})
        if not isinstance(requires, dict):
            raise RuleValidationError(
                "rule {!r}: 'requires' must be an object".format(rule["id"]))

    # The browser rules read curated site categories; a broken categories file
    # would make every category rule silently match nothing.
    if any(r.get("extractor", "").startswith("browser_") for r in rules):
        from uba.engine import site_categories
        problems = site_categories.validate(site_categories.load())
        if problems:
            raise RuleValidationError("site_categories.json: " + "; ".join(problems[:10]))

    logger.info("UBA: loaded %d behavior rules from %s", len(rules), path)
    return {
        "rules": rules,
        "requires_collection": data.get("requires_collection", []),
        # For the persisted store's freshness stamp (persisted_store.py).
        "version": str(data.get("version") or ""),
        "path": os.path.abspath(path),
    }


# --------------------------------------------------------------------------
# Analyst-created rules (uba/engine/user_rules.py). Checked here without a
# case; the checks that need one - is the table there, does it hold every
# column the rule names - are in extractors/declarative.py.
# --------------------------------------------------------------------------
USER_RULE_OPERATORS = ("equals", "contains", "regex", "not_equals", "greater_than",
                       "less_than", "greater_equal", "less_equal", "wildcard")
TIME_BASES = ("exact", "at_or_before")
ACTOR_MODES = ("sid", "username", "hive_owner", "none")
AGGREGATIONS = ("none", "per_actor_day", "burst")
_USER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,63}$")


def _check_conditions(conds, where, problems):
    if conds is None:
        return
    if not isinstance(conds, list):
        problems.append("%s must be a list of conditions" % where)
        return
    for i, cond in enumerate(conds, 1):
        label = "%s %d" % (where, i)
        if not isinstance(cond, dict):
            problems.append("%s is not a condition object" % label)
            continue
        field = str(cond.get("field_name") or "").strip()
        if not field:
            problems.append("%s names no field" % label)
        op = cond.get("operator", "equals")
        if op not in USER_RULE_OPERATORS:
            problems.append("%s: unknown operator %r" % (label, op))
        if "value" not in cond:
            problems.append("%s has no value" % label)
        elif op == "regex":
            try:
                re.compile(str(cond.get("value") or ""))
            except re.error as e:
                problems.append("%s: the pattern is not a valid regular expression (%s)"
                                % (label, e))
        if cond.get("compare_to_feather") or cond.get("compare_to_field"):
            problems.append("%s compares to another feather; a behaviour rule reads one "
                            "row or one event, so that is not available" % label)


def validate_user_rule(rule: dict, builtin_ids=()) -> List[str]:
    """Every reason ``rule`` cannot be saved or run, in plain words ([] = valid).

    Ids are snake_case and may not be a built-in rule's id: events, switches,
    coverage and Wing steps all refer to a rule by id alone.
    """
    problems: List[str] = []
    if not isinstance(rule, dict):
        return ["A rule must be an object."]
    rid = str(rule.get("id") or "").strip()
    if not rid:
        problems.append("The rule has no id.")
    elif not _USER_ID_RE.match(rid):
        problems.append("The id '%s' must be 3-64 characters of a-z, 0-9 and _ "
                        "(starting with a letter or digit)." % rid)
    elif rid in set(builtin_ids or ()):
        problems.append("The id '%s' is a built-in rule's id." % rid)
    kind = rule.get("kind")
    if kind not in ("table", "derived"):
        problems.append("The kind must be 'table' or 'derived', not %r." % kind)
    if not str(rule.get("title") or "").strip():
        problems.append("The rule has no title.")
    if not str(rule.get("activity") or "").strip():
        problems.append("The rule has no activity.")
    if rule.get("behavior_class") not in _VALID_CLASSES:
        problems.append("The class must be one of %s." % ", ".join(sorted(_VALID_CLASSES)))
    if rule.get("severity") not in _VALID_SEVERITIES:
        problems.append("The severity must be one of routine, notable, suspicious, critical.")
    if not isinstance(rule.get("description", ""), str):
        problems.append("The description must be text.")
    if str(rule.get("logic_operator", "AND")).upper() not in ("AND", "OR"):
        problems.append("The condition logic must be AND or OR.")
    _check_conditions(rule.get("conditions", []), "Condition", problems)
    groups = rule.get("condition_groups", [])
    if groups is not None and not isinstance(groups, list):
        problems.append("condition_groups must be a list.")
    else:
        for g, group in enumerate(groups or [], 1):
            if not isinstance(group, dict):
                problems.append("Group %d is not an object." % g)
                continue
            if str(group.get("logic_operator", "AND")).upper() not in ("AND", "OR"):
                problems.append("Group %d: logic must be AND or OR." % g)
            _check_conditions(group.get("conditions", []), "Group %d condition" % g, problems)

    if kind == "table":
        source = rule.get("source") or {}
        db = str(source.get("db") or "").strip()
        table = str(source.get("table") or "").strip()
        if not db or not table:
            problems.append("A table rule needs a database and a table.")
        elif (".." in db.replace("\\", "/").split("/") or os.path.isabs(db)
              or db.startswith(("/", "\\"))):
            problems.append("The database must be inside the case's Target_Artifacts folder.")
        columns = rule.get("columns") or {}
        if not isinstance(columns, dict):
            problems.append("columns must be an object.")
            columns = {}
        if columns.get("time_basis", "exact") not in TIME_BASES:
            problems.append("The time basis must be 'exact' or 'at_or_before'.")
        actor = columns.get("actor") or {"mode": "none"}
        mode = actor.get("mode", "none") if isinstance(actor, dict) else None
        if mode not in ACTOR_MODES:
            problems.append("The actor must come from a SID column, a user-name column, "
                            "the hive owner, or nowhere (none).")
        elif mode in ("sid", "username") and not str(actor.get("column") or "").strip():
            problems.append("The actor mode '%s' needs a column." % mode)
        agg = rule.get("aggregation") or {"mode": "none"}
        agg_mode = agg.get("mode", "none") if isinstance(agg, dict) else None
        if agg_mode not in AGGREGATIONS:
            problems.append("The aggregation must be none, per_actor_day or burst.")
        elif agg_mode == "burst":
            try:
                if float(agg.get("gap_minutes") or 0) <= 0:
                    problems.append("A burst needs a gap in minutes above 0.")
            except (TypeError, ValueError):
                problems.append("The burst gap must be a number of minutes.")
        if agg_mode in ("per_actor_day", "burst") and not columns.get("time"):
            problems.append("Aggregating by day or by burst needs a time column.")
    elif kind == "derived":
        base = rule.get("base") or {}
        ids = [str(x) for x in (base.get("rule_ids") or []) if str(x).strip()]
        acts = [str(x) for x in (base.get("activities") or []) if str(x).strip()]
        if not ids and not acts:
            problems.append("A derived rule needs at least one base rule or activity.")
        if rid and rid in ids:
            problems.append("A derived rule cannot be its own base.")
    return problems
