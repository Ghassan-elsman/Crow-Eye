"""Check the specific values in an answer against the evidence the Eye read.

A forensic answer's weight is in its specifics: a time, a serial, a path, a SID,
a hash. A model can produce a plausible one that no tool ever returned (an
invented connection time is the classic case). Before this, nothing compared the
answer with the rows: the GEP checks were recorded, not enforced (2026-11-02).

Deterministic and cheap: pull the specific values out of the answer, look each up
in the text of every tool result of the conversation, and list the ones that are
not there. Times compare to the minute in one form; paths and IDs ignore case and
doubled backslashes. A value missing from the evidence is not necessarily wrong
(it may come from the case notes or the investigator), so the answer is not
changed - a short note under it says which values the Eye could not find in what
it read.

A time that is in the evidence only after a whole-hour shift (to the second) is
a time-zone conversion the model made itself. It is listed apart, with the
shift, because the conversion is the part to verify: which zone the source
records in is a forensic question of its own.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List

_TS = re.compile(r"\b(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2})(?::(\d{2})(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}:?\d{2})?\b")
_VIDPID = re.compile(r"\b(?:VID|PID)_[0-9A-F]{4}\b", re.I)
_SID = re.compile(r"\bS-1-5-21-\d+-\d+-\d+-\d+\b")
_HASH = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b", re.I)
_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s\"'<>|*?`]+\\)*[^\\\s\"'<>|*?`,;)]*")
_MAX_SHIFT_H = 14


def _norm(text: str) -> str:
    # Times first: lowering turns the ISO "T" into "t", which the old order then
    # failed to match, so every ISO time in the evidence went unseen (2026-11-02 eval).
    t = _TS.sub(lambda m: "%s %s" % (m.group(1), m.group(2)), text or "")
    return t.replace("\\\\", "\\").lower()


def _seconds(texts: Iterable[str]) -> set:
    """Every time in the evidence that carries seconds, as 'YYYY-MM-DD HH:MM:SS'."""
    out = set()
    for t in texts:
        for m in _TS.finditer(t or ""):
            if m.group(3):
                out.add("%s %s:%s" % (m.group(1), m.group(2), m.group(3)))
    return out


def _shift_hours(claim: Dict[str, str], evidence_seconds: set):
    """The whole-hour shift that turns this time into one in the evidence, or None."""
    m = _TS.search(claim.get("value") or "")
    if not m or not m.group(3):
        return None
    try:
        when = datetime.strptime("%s %s:%s" % (m.group(1), m.group(2), m.group(3)), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    for h in range(1, _MAX_SHIFT_H + 1):
        for sign in (1, -1):
            if (when + timedelta(hours=sign * h)).strftime("%Y-%m-%d %H:%M:%S") in evidence_seconds:
                return sign * h
    return None


_HEADING = re.compile(r"^\s*(?:#{1,6}\s+|\*\*|__)")
_PROPOSAL = re.compile(r"^\s*(?:#{1,6}\s+|\*\*|__)?\s*(?:next steps?|suggested (?:next )?(?:steps|queries)|"
                       r"recommended (?:next )?steps|to confirm|follow[- ]up)\b", re.I)


def stated_part(answer: str) -> str:
    """The answer without its proposals: a "Next steps" section names windows to
    query ("between 02:00 and 04:30"), which are plans, not findings."""
    keep, skipping = [], False
    for line in (answer or "").splitlines():
        if _PROPOSAL.match(line):
            skipping = True
            continue
        if skipping and _HEADING.match(line):
            skipping = False
        if not skipping:
            keep.append(line)
    return "\n".join(keep)


def extract_claims(answer: str) -> List[Dict[str, str]]:
    """The specific values an answer states as findings, de-duplicated, in order."""
    seen, out = set(), []
    answer = stated_part(answer)

    def add(kind, value, key):
        if key not in seen:
            seen.add(key)
            out.append({"kind": kind, "value": value, "key": key})

    for m in _TS.finditer(answer or ""):
        add("time", m.group(0), "%s %s" % (m.group(1), m.group(2)))
    for rx, kind in ((_VIDPID, "device id"), (_SID, "sid"), (_HASH, "hash")):
        for m in rx.finditer(answer or ""):
            add(kind, m.group(0), m.group(0).lower())
    for m in _PATH.finditer(answer or ""):
        val = m.group(0).rstrip(".:")
        if len(val) > 4:
            add("path", val, val.replace("\\\\", "\\").lower())
    return out


def check_claims(answer: str, evidence_texts: Iterable[str]) -> Dict[str, object]:
    texts = [t for t in evidence_texts if t]
    corpus = "\n".join(_norm(t) for t in texts)
    claims = extract_claims(answer)
    missing, shifted = [], []
    evidence_seconds = None
    for c in claims:
        if c["key"] in corpus:
            continue
        if c["kind"] == "time":
            if evidence_seconds is None:
                evidence_seconds = _seconds(texts)
            h = _shift_hours(c, evidence_seconds)
            if h is not None:
                shifted.append(dict(c, shift_hours=h))
                continue
        missing.append(c)
    return {"checked": len(claims), "unsupported": missing, "shifted": shifted}


def note_for(result: Dict[str, object]) -> str:
    """One short note for the answer, or "" when every value was found as stated."""
    missing = result.get("unsupported") or []
    shifted = result.get("shifted") or []
    if not missing and not shifted:
        return ""
    parts = []
    if missing:
        shown = ", ".join("`%s`" % c["value"] for c in missing[:8])
        more = " and %d more" % (len(missing) - 8) if len(missing) > 8 else ""
        parts.append("%d of %d specific values were not found in any tool result of this "
                     "conversation: %s%s." % (len(missing), result.get("checked", 0), shown, more))
    if shifted:
        shown = ", ".join("`%s` (%+d h)" % (c["value"], -c["shift_hours"]) for c in shifted[:8])
        parts.append("%s converted from the recorded time by a time-zone shift the Eye made "
                     "itself: %s. Confirm which zone the source records in."
                     % ("1 time was" if len(shifted) == 1 else "%d times were" % len(shifted), shown))
    return ("\n\n---\n*Checked against the evidence the Eye read: %s Verify these before relying "
            "on them.*" % " ".join(parts))
