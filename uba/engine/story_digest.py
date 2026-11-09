"""The Activity Story, read as a day: repeats folded into one line, and a
summary at the top of each day (2026-11-03).

Pure functions over stored event rows (dicts with the `events` table's columns:
event_id, rule_id, behavior_class, activity, ts_start, ts_end, actor_name,
actor_sid, description, severity, aggregate_count, app_name, details_json or
details). No database, no Qt: the desktop window calls them through the bridge
and Crow-Eye Sentinel calls them on its kept story, so both say the same thing.

Rules for every sentence written here:
  - built only from the rows given; a count, a name or a time that is not in
    them is never written;
  - no words of intent (meant, tried, wanted, in order to);
  - every line keeps the ids of the events it stands for, so it opens them.
"""

import json
from collections import OrderedDict, defaultdict
from typing import Dict, Iterable, List, Optional

from uba.engine import description

SEVERITY_ORDER = {"routine": 0, "notable": 1, "suspicious": 2, "critical": 3}
PERSON_CLASSES = ("user", "application")      # what a person did, or a program they ran
COMPUTER_CLASSES = ("system", "system_app")   # what the computer did by itself
REPEAT_MIN = 3                # three or more alike in one day become one line
REPEAT_GAP_SECONDS = 2 * 3600 # ... when no two are more than two hours apart
LOGON_RULES = ("interactive_logon", "winlogon_logon_notification", "workstation_unlock")
LOGOFF_RULES = ("logoff", "winlogon_logoff_notification")
# New-to-the-day things the summary names, in this order.
FIRSTS = ("usb_connected", "usb_file_copy", "files_collected", "rdp_outbound",
          "printer_added", "cloud_sync_client", "app_installed", "mounted_volume",
          "network_share_access")

# How a folded group reads: activity -> (singular verb phrase, plural pattern).
# {n} is the count, {what} the shared subject (folder, program, site).
_GROUP_WORDS = {
    "file_opened": "opened {n} files in {what}",
    "file_access": "chose {n} files in {what} in Open/Save dialogs",
    "file_created": "created files in {what} {n} times",
    "file_edited": "changed files in {what} {n} times",
    "file_renamed": "renamed or moved files in {what} {n} times",
    "file_deleted": "deleted files in {what} {n} times",
    "file_soft_deleted": "moved files from {what} to the Recycle Bin {n} times",
    "program_run": "ran {what} {n} times",
    "app_launch": "opened {what} {n} times",
    "process_created": "started {what} {n} times",
    "app_usage": "used {what} {n} times",
    "web_browsing": "visited {n} pages on {what}",
    "site_visit": "visited {n} pages on {what}",
    "web_search": "searched the web {n} times",
    "file_download": "downloaded {n} files",
    "folder_browsing": "browsed {n} folders in {what}",
    "logon": "signed in {n} times",
    "logoff": "signed out {n} times",
    "unlock": "unlocked the computer {n} times",
    "failed_logon": "failed to sign in {n} times",
    "network_usage": "{what} transferred data {n} times",
    "network_session": "the computer connected to a network {n} times",
    "service_state_changed": "service start types changed {n} times",
    "windows_update": "Windows updated itself {n} times",
    "scheduled_task_run": "scheduled tasks ran {n} times",
    "execution": "scheduled tasks ran {n} times",
    "app_error": "{what} reported an error {n} times",
}


def _details(row) -> dict:
    d = row.get("details")
    if isinstance(d, dict):
        return d
    raw = row.get("details_json")
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def _epoch(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _hhmm(ts: Optional[str]) -> str:
    return str(ts)[11:16] if ts and len(str(ts)) >= 16 else ""


def person_of(row) -> str:
    """Who a line is about, for reading: the resolved name, or '' (the computer)."""
    return str(row.get("actor_name") or "")


def _person_key(row) -> str:
    return str(row.get("actor_sid") or row.get("actor_name") or "")


def subject_of(row) -> str:
    """What the activity was done to, shared by the rows a group folds."""
    d = _details(row)
    for key in ("folder", "path"):
        if d.get(key):
            return description.folder_label(str(d[key]))
    for key in ("site", "host", "domain"):
        if d.get(key):
            return str(d[key])
    if row.get("app_name"):
        return str(row["app_name"])
    for key in ("executable", "program", "name"):
        if d.get(key):
            return description.app_display_name(str(d[key]))
    return ""


def is_person_activity(row) -> bool:
    return str(row.get("behavior_class") or "") in PERSON_CLASSES


def _worst(rows) -> str:
    return max((str(r.get("severity") or "routine") for r in rows),
               key=lambda s: SEVERITY_ORDER.get(s, 0))


def _group_text(rows, who, what) -> str:
    n = sum(int(r.get("aggregate_count") or 1) if r.get("activity") in (
        "web_browsing", "site_visit", "file_opened", "file_access", "folder_browsing")
        else 1 for r in rows)
    pattern = _GROUP_WORDS.get(rows[0].get("activity"))
    first, last = rows[0].get("ts_start"), rows[-1].get("ts_end") or rows[-1].get("ts_start")
    span = ""
    if _hhmm(first) and _hhmm(last):
        span = (" at {}".format(_hhmm(first)) if _hhmm(first) == _hhmm(last)
                else " between {} and {}".format(_hhmm(first), _hhmm(last)))
    if pattern is None:
        title = rows[0].get("title") or rows[0].get("rule_id") or "activity"
        body = "{} x {}".format(len(rows), title)
    else:
        body = pattern.format(n=n, what=what or "one place")
    if who and not body.startswith(("the computer", "Windows", "scheduled", "service")) \
            and not (pattern and pattern.startswith("{what}")):
        body = "{} {}".format(who, body)
    else:
        body = body[0].upper() + body[1:]
    return body + span


def group_repeats(rows: Iterable[dict], min_count: int = REPEAT_MIN,
                  gap_seconds: int = REPEAT_GAP_SECONDS) -> List[dict]:
    """The rows in their given order, with runs of alike activity folded.

    Alike = same day, same person, same rule, same subject (folder, program,
    site), no two more than `gap_seconds` apart. A run of `min_count` or more
    becomes one line: {"kind": "group", "text", "event_ids", "rule_id",
    "activity", "severity" (the worst), "ts_start", "ts_end", "count", "person"}.
    Every other row passes through as {"kind": "event", "event_id", ...the row}.
    A timeless row is never folded. Nothing is dropped: the event ids of a group
    are every row it stands for.
    """
    rows = list(rows)
    buckets: Dict[tuple, List[List[int]]] = defaultdict(list)
    for i, r in enumerate(rows):
        if not r.get("ts_start"):
            continue
        key = (str(r["ts_start"])[:10], _person_key(r), r.get("rule_id"), subject_of(r))
        runs = buckets[key]
        t = _epoch(r.get("ts_start"))
        if runs:
            last = rows[runs[-1][-1]]
            lt = _epoch(last.get("ts_end") or last.get("ts_start"))
            if t is not None and lt is not None and abs(t - lt) <= gap_seconds:
                runs[-1].append(i)
                continue
        runs.append([i])
    leader, member = {}, set()
    for runs in buckets.values():
        for run in runs:
            if len(run) >= min_count:
                ordered = sorted(run, key=lambda j: str(rows[j].get("ts_start")))
                leader[min(run)] = ordered
                member.update(run)
    out = []
    for i, r in enumerate(rows):
        if i in leader:
            g = [rows[j] for j in leader[i]]
            who, what = person_of(g[0]), subject_of(g[0])
            out.append({
                "kind": "group", "text": _group_text(g, who, what),
                "event_ids": [x.get("event_id") for x in g],
                "rule_id": g[0].get("rule_id"), "activity": g[0].get("activity"),
                "behavior_class": g[0].get("behavior_class"),
                "severity": _worst(g), "ts_start": g[0].get("ts_start"),
                "ts_end": g[-1].get("ts_end") or g[-1].get("ts_start"),
                "count": len(g), "person": who, "subject": what})
        elif i not in member:
            out.append(dict(r, kind="event"))
    return out


def day_summary(rows: Iterable[dict], day: str, person: Optional[str] = None,
                max_highlights: int = 5) -> dict:
    """The opening card of one day, built only from that day's rows.

    Returns {"day", "lines": [{"text", "event_ids"}], "people": [...],
    "counts": {"person", "computer", "needs_review"}}. `person` (an actor_sid or
    name) limits the card to that person's rows.
    """
    rows = [r for r in rows if str(r.get("ts_start") or "")[:10] == day]
    if person:
        rows = [r for r in rows if person in (r.get("actor_sid"), r.get("actor_name"))]
    lines = []
    people = OrderedDict()
    for r in rows:
        # A person: the actor resolved to a user (actor_type 'User', or an
        # account SID). Application events name their program as the actor
        # ('TIMEOUT', 'WC'), which is not a person.
        sid = str(r.get("actor_sid") or "")
        is_user = (str(r.get("actor_type") or "") == "User"
                   or sid.startswith("S-1-5-21-") or sid.startswith("S-1-12-1-"))
        if is_person_activity(r) and person_of(r) and is_user:
            people.setdefault(person_of(r), []).append(r)
    computer = [r for r in rows if not is_person_activity(r)]
    review = [r for r in rows if SEVERITY_ORDER.get(str(r.get("severity")), 0) >= 1]

    for name, own in people.items():
        ins = sorted((r for r in own if r.get("rule_id") in LOGON_RULES),
                     key=lambda r: str(r.get("ts_start")))
        outs = sorted((r for r in own if r.get("rule_id") in LOGOFF_RULES),
                      key=lambda r: str(r.get("ts_start")))
        parts = []
        if ins:
            remote = [r for r in ins if str(_details(r).get("logon_type")) == "10"]
            parts.append("first signed in at {}{}".format(
                _hhmm(ins[0].get("ts_start")),
                " (over Remote Desktop)" if ins[0] in remote else ""))
        if outs:
            parts.append("last signed out at {}".format(_hhmm(outs[-1].get("ts_start"))))
        n = len(own)
        text = "{}: {} activit{}".format(name, n, "y" if n == 1 else "ies")
        if parts:
            text += "; " + ", ".join(parts)
        lines.append({"text": text, "event_ids": [r.get("event_id") for r in (ins[:1] + outs[-1:])]})

    firsts = []
    for rule in FIRSTS:
        for r in rows:
            if r.get("rule_id") == rule:
                firsts.append(r)
    seen = set()
    for r in firsts:
        if r.get("event_id") in seen:
            continue
        seen.add(r.get("event_id"))
        lines.append({"text": str(r.get("description") or ""), "event_ids": [r.get("event_id")]})
        if len(seen) >= max_highlights:
            break

    left = max_highlights - len(seen)
    if left > 0:
        worst = sorted((r for r in review if r.get("event_id") not in seen),
                       key=lambda r: (-SEVERITY_ORDER.get(str(r.get("severity")), 0),
                                      str(r.get("ts_start"))))
        # One line per rule: four Defender exclusions set in the same minute are
        # one thing to look at, said once with how many more there are.
        by_rule = OrderedDict()
        for r in worst:
            by_rule.setdefault(r.get("rule_id"), []).append(r)
        for rule_rows in list(by_rule.values())[:left]:
            text = str(rule_rows[0].get("description") or "")
            if len(rule_rows) > 1:
                text += " (and {} more like it)".format(len(rule_rows) - 1)
            lines.append({"text": text, "event_ids": [r.get("event_id") for r in rule_rows][:200]})

    # What was in front: the programs that had the focus that day, from the
    # input activity (SRUM's foreground records), longest first.
    front = defaultdict(float)
    front_ids = []
    for r in rows:
        if r.get("rule_id") != "input_activity":
            continue
        front_ids.append(r.get("event_id"))
        for p in (_details(r).get("programs") or []):
            try:
                front[str(p.get("app") or "")] += float(p.get("focus_s") or 0)
            except (TypeError, ValueError):
                pass
    top = [(a, s) for a, s in sorted(front.items(), key=lambda kv: -kv[1]) if a and s >= 60][:5]
    if top:
        lines.append({"text": "In front (the window being used): " + ", ".join(
            "{} {} min".format(a, int(round(s / 60))) for a, s in top), "event_ids": front_ids[:200]})
    ops = defaultdict(list)
    for r in rows:
        if r.get("operator") and r.get("operator") != "unknown":
            key = r["operator"]
            if key == "automation" and r.get("operator_kind") == "ai_agent":
                key = "ai_agent"
            ops[key].append(r.get("event_id"))
    if ops:
        words = (("person", "by a person at the keyboard"), ("remote_person", "by a person remotely"),
                 ("ai_agent", "by an AI agent"), ("automation", "by scripts or automation"),
                 ("program", "by programs on their own"))
        parts = ["{} {}".format(len(ops[k]), w) for k, w in words if ops.get(k)]
        lines.append({"text": "Who drove it: " + ", ".join(parts),
                      "event_ids": [i for k, _w in words for i in ops.get(k, [])][:200]})
    if computer:
        lines.append({"text": "The computer itself recorded {} activit{} (updates, services, "
                              "devices and the like)".format(
                                  len(computer), "y" if len(computer) == 1 else "ies"),
                      "event_ids": [r.get("event_id") for r in computer][:200]})
    return {"day": day, "lines": lines, "people": list(people.keys()),
            "counts": {"person": len(rows) - len(computer), "computer": len(computer),
                       "needs_review": len(review)}}
