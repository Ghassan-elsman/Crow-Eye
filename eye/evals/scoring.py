"""Score an Eye answer against a gold question (see run_eval.py).

Deterministic on purpose: the facts a forensic answer must state (a serial, a
time, a path, a count) either appear in it or they do not. Timestamps are
compared in one form (`YYYY-MM-DD HH:MM`), case and doubled backslashes are
ignored."""

import re
from typing import Any, Dict, List

# Phrases an answer uses when it says the case cannot show something.
UNKNOWN_PHRASES = (
    "cannot", "can't", "can not", "not established", "not be established", "no evidence",
    "not recorded", "unknown", "not possible to", "does not show", "doesn't show",
    "not determin", "not prov", "no record", "isn't recorded", "is not recorded",
    "not available", "not in the case", "not present", "no connection time",
)


def normalise(text: str) -> str:
    t = str(text or "")
    t = t.replace("\\\\", "\\")
    t = re.sub(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", r"\1 \2", t)
    t = re.sub(r"\s+", " ", t)
    return t.lower()


def _fact_found(answer_n: str, fact) -> bool:
    alternatives = fact if isinstance(fact, (list, tuple)) else [fact]
    return any(normalise(a) in answer_n for a in alternatives)


def score(question: Dict[str, Any], answer: str) -> Dict[str, Any]:
    answer_n = normalise(answer)
    includes: List = question.get("must_include") or []
    found = [f for f in includes if _fact_found(answer_n, f)]
    missing = [f for f in includes if not _fact_found(answer_n, f)]
    wrong = [p for p in (question.get("must_not") or []) if re.search(p, answer or "", re.I)]
    unknown_ok = True
    if question.get("honest_unknown"):
        unknown_ok = any(p in answer_n for p in UNKNOWN_PHRASES)
    facts = (len(found) / len(includes)) if includes else 1.0
    passed = not missing and not wrong and unknown_ok and bool(answer_n.strip())
    return {
        "passed": passed,
        "facts": round(facts, 3),
        "missing": missing,
        "wrong": wrong,
        "unknown_ok": unknown_ok,
    }
