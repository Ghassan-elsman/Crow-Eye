"""Loads and validates uba/config/behavior_rules.json."""

import json
import os
import logging
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

    logger.info("UBA: loaded %d behavior rules from %s", len(rules), path)
    return {
        "rules": rules,
        "requires_collection": data.get("requires_collection", []),
    }
