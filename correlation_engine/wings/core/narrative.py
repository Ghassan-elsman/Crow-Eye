"""A Wing's narrative: the sentence its author writes for how a match reads.

The person who understood the detection phrases how it is told (cu-narr,
0x20d3; Sentinel 21.3). The Wing carries the template; a match fills it, only
from the match's own records, and nothing else is added.

    narrative.problems(template, feather_ids)   what is wrong with a template
    narrative.check(template, feather_ids)      raises NarrativeError
    narrative.render(template, match_records, anchor_feather_id, when)

TEMPLATE. Plain text with placeholders in braces:

    {column}               the first record in the match that has the column -
                           the anchor's record first, then the others
    {feather_id.column}    that feather's record
    {when}                 the match's time
    {first_time} {last_time}   the earliest and latest record time in it
    {records}              how many records the match holds
    {feathers}             the feathers that matched, by id

    "{executable_name} ran at {when}: Prefetch recorded it {records} times
     ({AIAgentSteps.command})"

A value is put in exactly as the record holds it. A value the match does not
hold is shown as "[no <name>]" - never guessed.

NO WORD OF INTENT. A narrative says what the records show - who, which
program, when, what followed - never why. The words the author writes (the
template outside its placeholders) are checked against INTENT, the same list
Sentinel's narratives use (sentinel_server/analysis/drift_narrative.INTENT),
and a template holding one is refused. What a record itself says is quoted as
evidence, not checked: a file named "plan to hide.zip" is a file name.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["INTENT", "NarrativeError", "FIRE_FIELDS", "MAX_CHARS", "problems", "check", "render",
           "placeholders"]

# Kept identical to Sentinel's analysis/drift_narrative.INTENT (decision 607),
# so a template the desktop accepts is one Sentinel's server accepts too.
INTENT = re.compile(
    r"\b(meant|means to|mean to|tried|tries|trying|try to|attempt\w*|"
    r"wanted|wants|want to|intend\w*|in order to|so as to|so that|"
    r"purpose\w*|deliberate\w*|on purpose|plann(?:ed|ing) to|plans to|"
    r"aim(?:ed|ing|s)? to|decided to|chose to|hop(?:ed|ing) to|sought|"
    r"seeking|to hide|to cover|to steal|to avoid|to evade|because|"
    r"motive\w*|malicious\w*|suspicious\w*|insider threat|exfiltrated)\b",
    re.IGNORECASE)

# What a match itself says, apart from its records' columns.
FIRE_FIELDS = ("when", "first_time", "last_time", "records", "feathers")
MAX_CHARS = 600
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?\}")
# Columns that hold a record's time, in the order a record is read for one.
_TIME_COLUMNS = ("timestamp", "ts", "time", "event_time", "last_written")


class NarrativeError(ValueError):
    """A template that cannot be told: a word of intent, or a placeholder
    nothing in the match can fill."""


def placeholders(template: str) -> List[tuple]:
    """(feather_id or None, name) for every placeholder, in order."""
    out = []
    for m in _PLACEHOLDER.finditer(template or ""):
        out.append((m.group(1), m.group(2)) if m.group(2) else (None, m.group(1)))
    return out


def problems(template: str, feather_ids: Optional[Iterable[str]] = None) -> List[str]:
    """Everything wrong with `template`, in words; [] when it can be used.

    `feather_ids` are the Wing's feathers: a `{feather_id.column}` naming
    another feather is refused (nothing in a match of this Wing fills it)."""
    text = template or ""
    out = []
    if len(text) > MAX_CHARS:
        out.append("The narrative is %d characters; keep it to %d." % (len(text), MAX_CHARS))
    # The author's own words: the template with its placeholders taken out.
    own = _PLACEHOLDER.sub(" ", text)
    if "{" in own or "}" in own:
        out.append("A brace is not part of a placeholder: write {column} or {feather_id.column}.")
    found = sorted({m.group(0).lower() for m in INTENT.finditer(own)})
    if found:
        out.append("Words of intent say why, which no record shows: %s. Say what the records show "
                   "(who, which program, when, what followed)." % ", ".join('"%s"' % w for w in found))
    known = {str(f) for f in (feather_ids or [])}
    if feather_ids is not None:
        for fid, name in placeholders(text):
            if fid is not None and fid not in known:
                out.append("{%s.%s} names a feather this Wing does not use (it uses: %s)."
                           % (fid, name, ", ".join(sorted(known)) or "none"))
    return out


def check(template: str, feather_ids: Optional[Iterable[str]] = None) -> None:
    """Raise NarrativeError naming what is wrong; return when it can be used."""
    found = problems(template, feather_ids)
    if found:
        raise NarrativeError(" ".join(found))


def _records_of(match_records: Dict[str, Any]):
    """(feather_id, record) pairs; a feather may hold one record or several."""
    for fid, rec in (match_records or {}).items():
        if isinstance(rec, dict):
            yield fid, rec
        elif isinstance(rec, (list, tuple)):
            for r in rec:
                if isinstance(r, dict):
                    yield fid, r


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _time_of(record: Dict[str, Any]) -> str:
    for c in _TIME_COLUMNS:
        if not _blank(record.get(c)):
            return str(record.get(c))
    return ""


def render(template: str, match_records: Dict[str, Any], anchor_feather_id: Optional[str] = None,
           when: Optional[str] = None) -> str:
    """The template filled from one match's records. Nothing but the records
    (and the match's own time and size) goes in; a value the match does not
    hold reads "[no <name>]"."""
    pairs = list(_records_of(match_records))
    # The anchor's record is read first for a bare {column}.
    pairs.sort(key=lambda p: p[0] != anchor_feather_id)
    times = sorted(t for t in (_time_of(r) for _f, r in pairs) if t)
    fire = {
        "when": when or (times[0] if times else ""),
        "first_time": times[0] if times else "",
        "last_time": times[-1] if times else "",
        "records": str(len(pairs)),
        "feathers": ", ".join(dict.fromkeys(f for f, _r in pairs)),
    }

    def fill(m):
        fid, name = (m.group(1), m.group(2)) if m.group(2) else (None, m.group(1))
        if fid is None and name in fire and fire[name] != "":
            return fire[name]
        for f, rec in pairs:
            if fid is not None and f != fid:
                continue
            value = rec.get(name)
            if not _blank(value):
                return str(value)
        return "[no %s]" % (("%s.%s" % (fid, name)) if fid else name)

    return _PLACEHOLDER.sub(fill, template or "")
