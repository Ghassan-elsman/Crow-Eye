"""
Log-primary extractors: behaviors whose authoritative source is a Windows
event-log row (Log_Claw.db). Each returns a list of BehaviorEvents.

Common conventions:
- Timestamps in Log_Claw are already UTC 'YYYY-MM-DD HH:MM:SS' strings but
  are still normalized defensively.
- Attribution uses parsed Keywords payloads (see uba/utils/log_parser.py);
  a missing/unparseable payload leaves the actor EMPTY.
"""

import logging
from collections import defaultdict
from typing import List

from uba.engine import description
from uba.engine.models import (BehaviorEvent, EvidenceRef, CONF_LOG_ONLY,
                               CONF_CORROBORATED, SEV_NOTABLE, SEV_ROUTINE,
                               SEV_SUSPICIOUS)
from uba.utils import log_parser, sid_utils
from uba.utils.timeparse import normalize_ts, epoch_seconds

logger = logging.getLogger(__name__)


def _security_rows(ctx, eids):
    conn = ctx.pool.get("logs")
    if conn is None or not ctx.pool.has_table("logs", "SecurityLogs"):
        return []
    marks = ",".join("?" for _ in eids)
    return conn.execute(
        "SELECT rowid, EventID, EventTimestampUTC, User, Keywords "
        "FROM SecurityLogs WHERE EventID IN ({}) "
        "ORDER BY EventTimestampUTC".format(marks), list(eids)).fetchall()


def _system_rows(ctx, eids, source_like=None):
    conn = ctx.pool.get("logs")
    if conn is None or not ctx.pool.has_table("logs", "SystemLogs"):
        return []
    marks = ",".join("?" for _ in eids)
    sql = ("SELECT rowid, EventID, EventTimestampUTC, Source, User, Keywords, "
           "EventDescription FROM SystemLogs WHERE EventID IN ({})".format(marks))
    params = list(eids)
    if source_like:
        sql += " AND Source LIKE ?"
        params.append(source_like)
    sql += " ORDER BY EventTimestampUTC"
    return conn.execute(sql, params).fetchall()


def _app_rows(ctx, eids, source_like=None):
    conn = ctx.pool.get("logs")
    if conn is None or not ctx.pool.has_table("logs", "ApplicationLogs"):
        return []
    marks = ",".join("?" for _ in eids)
    sql = ("SELECT rowid, EventID, EventTimestampUTC, Source, User, Keywords, "
           "EventDescription FROM ApplicationLogs WHERE EventID IN ({})".format(marks))
    params = list(eids)
    if source_like:
        sql += " AND Source LIKE ?"
        params.append(source_like)
    sql += " ORDER BY EventTimestampUTC"
    return conn.execute(sql, params).fetchall()


def _mk(rule, ts, actor, description_text, evidence, confidence=CONF_LOG_ONLY,
        ctx=None, severity=None, details=None, count=1, caveat="", app_name=""):
    actor_type, actor_name, actor_basis = actor
    return BehaviorEvent(
        rule_id=rule["id"], behavior_class=rule["behavior_class"],
        activity=rule["activity"], ts_start=ts, ts_end=ts,
        actor_type=actor_type, actor_name=actor_name, actor_basis=actor_basis,
        description=description_text, severity=severity or rule["severity"],
        confidence=confidence, caveat=caveat, app_name=app_name,
        session_context=ctx.session_context(ts) if ctx else "",
        aggregate_count=count, details=details or {}, evidence=evidence)


# --------------------------------------------------------------------- #
def sessions_logon(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4624]):
        info = log_parser.parse_payload(4624, keywords)
        if info.get("logon_type") not in ("2", "10", "11"):
            continue
        ts = normalize_ts(ts)
        actor = ctx.resolver.from_sid(info.get("target_sid"), "the logon event")
        if not actor[0]:
            actor = ctx.resolver.from_account_name(
                info.get("target_user"), "the Windows security log")
        if actor[0] != "User":
            continue                     # service noise, not a person signing in
        remote = info.get("logon_type") == "10"
        if remote:
            text = "{} signed in remotely over Remote Desktop".format(actor[1])
            severity = SEV_NOTABLE
        else:
            text = "{} signed in to the computer ({})".format(
                actor[1], info.get("logon_type_label", "logon"))
            severity = None
        events.append(_mk(
            rule, ts, actor, text,
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx, severity=severity, details={"logon_type": info.get("logon_type")}))
    return events


def sessions_logoff(ctx, rules) -> List[BehaviorEvent]:
    """4634 (session logoff) + 4647 (user-initiated logoff)."""
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4634, 4647]):
        info = log_parser.parse_payload(4634, keywords)
        actor = ctx.resolver.from_sid(info.get("target_sid"), "the logoff event")
        if actor[0] != "User":
            continue
        ts = normalize_ts(ts)
        verb = "signed out" if eid == 4634 else "signed out (chose Sign Out)"
        events.append(_mk(
            rule, ts, actor, "{} {}".format(actor[1], verb),
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    return events


def sessions_unlock(ctx, rules) -> List[BehaviorEvent]:
    """Explicit 4800/4801 auditing is normally off; logon type 7 events are
    the reliable unlock signal that IS captured by default."""
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4624]):
        info = log_parser.parse_payload(4624, keywords)
        if info.get("logon_type") != "7":
            continue
        actor = ctx.resolver.from_sid(info.get("target_sid"), "the unlock event")
        if not actor[0]:
            actor = ctx.resolver.from_account_name(
                info.get("target_user"), "the Windows security log")
        if actor[0] != "User":
            continue
        ts = normalize_ts(ts)
        events.append(_mk(
            rule, ts, actor,
            "{} unlocked the computer (was present at the keyboard)".format(actor[1]),
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    return events


# --------------------------------------------------------------------- #
def process_creation_4688(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4688]):
        info = log_parser.parse_payload(4688, keywords)
        proc = info.get("new_process_name", "")
        if not proc or proc == "-":
            continue
        ts = normalize_ts(ts)
        actor = ctx.resolver.from_sid(info.get("subject_sid"), "the process event")
        app = description.app_display_name(proc)
        parent = info.get("parent_process_name", "")
        text = "The program '{}' started".format(app)
        if parent and parent != "-":
            text += " (launched by '{}')".format(description.app_display_name(parent))
        details = {"process_path": proc, "parent_process": parent}
        if info.get("command_line"):
            details["command_line"] = info["command_line"]
        events.append(_mk(rule, ts, actor, text,
                          [EvidenceRef(db="logs", table="SecurityLogs",
                                       rowids=[rowid], count=1)],
                          ctx=ctx, details=details, app_name=app))
    return events


# --------------------------------------------------------------------- #
def service_installed(ctx, rules) -> List[BehaviorEvent]:
    """System 7045. The parsed SystemLogs rows carry no payload (Keywords
    'N/A'), so the service name is unknown; the registry SystemServices
    table is attached as corroborating state evidence."""
    rule = rules[0]
    events = []
    reg_conn = ctx.pool.get("registry")
    has_services = ctx.pool.has_table("registry", "SystemServices")
    for rowid, eid, ts, source, user, keywords, desc in _system_rows(
            ctx, [7045], source_like="%Service Control Manager%"):
        ts = normalize_ts(ts)
        evidence = [EvidenceRef(db="logs", table="SystemLogs", rowids=[rowid], count=1)]
        confidence = CONF_LOG_ONLY
        if has_services and reg_conn is not None:
            confidence = CONF_CORROBORATED
            evidence.append(EvidenceRef(
                db="registry", table="SystemServices", role="corroborating",
                rowids=[], count=0))
        events.append(_mk(
            rule, ts, ("System", "Windows", "recorded by the Service Control Manager"),
            "A new background service was installed on the computer",
            evidence, confidence=confidence, ctx=ctx))
    return events


def boot_shutdown(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, eid, ts, source, user, keywords, desc in _system_rows(ctx, [1074, 6008]):
        ts = normalize_ts(ts)
        if eid == 6008:
            text = ("The computer shut down unexpectedly (power loss, crash "
                    "or forced power-off)")
            severity = SEV_NOTABLE
        else:
            text = "The computer was shut down or restarted"
            severity = SEV_ROUTINE
        events.append(_mk(
            rule, ts, ("System", "Windows", "recorded in the system log"),
            text, [EvidenceRef(db="logs", table="SystemLogs", rowids=[rowid], count=1)],
            ctx=ctx, severity=severity))
    return events


def time_changed(ctx, rules) -> List[BehaviorEvent]:
    """Kernel-General EID 1 = system time changed. The parsed row has no
    payload, so WHO changed it is unknowable here — actor stays EMPTY and
    severity stays at the rule's 'suspicious' so a reviewer looks at it.
    Security 4616 rows (when auditing is on) are also consumed."""
    rule = rules[0]
    events = []
    # The machine's configured time zone (registry) — context for a reviewer
    # judging whether a clock change is benign. Attached as evidence.
    tz_evidence = []
    tz_name = None
    if ctx.pool.has_table("registry", "TimeZoneInfo"):
        try:
            row = ctx.pool.get("registry").execute(
                "SELECT rowid, time_zone_name, bias FROM TimeZoneInfo LIMIT 1").fetchone()
            if row:
                tz_name = row["time_zone_name"] if hasattr(row, "keys") else row[1]
                tz_evidence = [EvidenceRef(db="registry", table="TimeZoneInfo",
                                           role="corroborating",
                                           rowids=[row[0]], count=1)]
        except Exception:
            tz_evidence = []
    tz_ctx = " (this computer's time zone is {})".format(tz_name) if tz_name else ""

    for rowid, eid, ts, source, user, keywords, desc in _system_rows(
            ctx, [1], source_like="%Kernel-General%"):
        ts = normalize_ts(ts)
        events.append(_mk(
            rule, ts, ("", "", ""),
            "The system clock was changed (the kernel log does not record "
            "who changed it — this can be routine time sync or deliberate "
            "tampering)" + tz_ctx,
            [EvidenceRef(db="logs", table="SystemLogs", rowids=[rowid], count=1)]
            + tz_evidence,
            ctx=ctx))
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4616]):
        ts = normalize_ts(ts)
        actor = ctx.resolver.from_account_name(user, "the security log")
        events.append(_mk(
            rule, ts, actor, "The system clock was changed",
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    return events


def log_cleared(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [1102]):
        ts = normalize_ts(ts)
        actor = ctx.resolver.from_account_name(user, "the security log")
        events.append(_mk(
            rule, ts, actor,
            "The Windows security event log was erased — activity records "
            "before this moment were deliberately removed",
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    for rowid, eid, ts, source, user, keywords, desc in _system_rows(ctx, [104]):
        ts = normalize_ts(ts)
        events.append(_mk(
            rule, ts, ("", "", ""),
            "A Windows event log was erased",
            [EvidenceRef(db="logs", table="SystemLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    return events


# --------------------------------------------------------------------- #
def _burst_by_user_hour(rows_with_actor):
    """Group (rowid, ts, actor) tuples into per-user-per-hour buckets."""
    buckets = defaultdict(list)
    for rowid, ts, actor in rows_with_actor:
        hour = (ts or "")[:13]
        buckets[(actor, hour)].append((rowid, ts))
    return buckets


def privileged_logon(ctx, rules) -> List[BehaviorEvent]:
    """4672 fires for every SYSTEM logon constantly; only human accounts are
    reported, aggregated per hour."""
    rule = rules[0]
    rows = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4672]):
        info = log_parser.parse_payload(4672, keywords)
        actor = ctx.resolver.from_sid(info.get("subject_sid"), "the privilege event")
        if actor[0] != "User":
            continue
        rows.append((rowid, normalize_ts(ts), actor))
    events = []
    for (actor, hour), items in _burst_by_user_hour(rows).items():
        rowids = [r for r, _ in items]
        ts = items[0][1]
        events.append(_mk(
            rule, ts, actor,
            "{} signed in with administrator-level rights ({} time{})".format(
                actor[1], len(items), "s" if len(items) != 1 else ""),
            [EvidenceRef(db="logs", table="SecurityLogs",
                         rowids=rowids[:50], count=len(rowids))],
            ctx=ctx, count=len(items)))
    return events


def explicit_credentials(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4648]):
        info = log_parser.parse_payload(4648, keywords)
        ts = normalize_ts(ts)
        actor = ctx.resolver.from_sid(info.get("subject_sid"), "the credential event")
        if not actor[0]:
            actor = ctx.resolver.from_account_name(
                info.get("subject_user"), "the security log")
        target = info.get("target_user", "another account")
        if actor[0] == "System" and sid_utils.is_system_account_name(target):
            continue                     # OS talking to itself — noise
        events.append(_mk(
            rule, ts, actor,
            "{} used the credentials of account '{}' to perform an action".format(
                actor[1] or "Someone", target),
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    return events


def account_enumeration(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    rows = []
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4798, 4799]):
        info = log_parser.parse_payload(eid, keywords)
        actor = ctx.resolver.from_sid(info.get("subject_sid"), "the lookup event")
        if not actor[0]:
            actor = ("", "", "")
        rows.append((rowid, normalize_ts(ts), actor))
    events = []
    for (actor, hour), items in _burst_by_user_hour(rows).items():
        rowids = [r for r, _ in items]
        severity = SEV_NOTABLE if len(items) > 20 else rule["severity"]
        subject = actor[1] if actor[0] else "A program"
        events.append(_mk(
            rule, items[0][1], actor,
            "{} looked up user-account and group information ({} time{})".format(
                subject, len(items), "s" if len(items) != 1 else ""),
            [EvidenceRef(db="logs", table="SecurityLogs",
                         rowids=rowids[:50], count=len(rowids))],
            ctx=ctx, severity=severity, count=len(items)))
    return events


_ACCOUNT_EVENT_VERB = {
    4720: "created the user account",
    4722: "enabled the user account",
    4724: "reset the password of",
    4725: "disabled the user account",
    4726: "deleted the user account",
    4738: "changed the user account",
}


def account_management(ctx, rules) -> List[BehaviorEvent]:
    """Account administration from the security log (authoritative): who
    created / enabled / disabled / deleted / changed accounts, and who was
    added to a group. Names both the target account affected and the subject
    who performed the action.

    Privilege escalation (added to Administrators) and account deletion are
    escalated to 'suspicious' for HR/manager review."""
    rule = rules[0]

    def _clean(name):
        return None if name in ("-", "", None) else name

    def _subject(info):
        actor = ctx.resolver.from_sid(info.get("subject_sid"), "the security log")
        if not actor[0]:
            actor = ctx.resolver.from_account_name(
                info.get("subject_user"), "the security log")
        return actor

    # Aggregate identical administrative actions (setup produces many repeats)
    # into one event: key = (verb/kind, subject_name, target, group, severity).
    groups = {}

    def _add(key, ts, rowid, make_desc, actor, severity):
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"rowids": [], "first_ts": ts, "actor": actor,
                               "severity": severity, "desc": make_desc}
        g["rowids"].append(rowid)
        if ts and (g["first_ts"] is None or ts < g["first_ts"]):
            g["first_ts"] = ts

    # Target-account events (create / enable / disable / delete / change / pwd)
    for rowid, eid, ts, user, keywords in _security_rows(
            ctx, list(_ACCOUNT_EVENT_VERB)):
        info = log_parser.parse_payload(eid, keywords)
        if not info:
            continue
        ts = normalize_ts(ts)
        actor = _subject(info)
        target = (ctx.resolver.username_for_sid(info.get("target_sid"))
                  or _clean(info.get("target_user")) or "an account")
        verb = _ACCOUNT_EVENT_VERB[eid]
        severity = SEV_SUSPICIOUS if eid == 4726 else SEV_NOTABLE
        key = ("acct", eid, actor[1], target)
        _add(key, ts, rowid,
             "{} {} '{}'".format(actor[1] or "Someone", verb, target),
             actor, severity)

    # Group-membership additions (4732 local, 4728 global)
    for rowid, eid, ts, user, keywords in _security_rows(ctx, [4728, 4732]):
        info = log_parser.parse_payload(eid, keywords)
        if not info:
            continue
        ts = normalize_ts(ts)
        actor = _subject(info)
        member = (ctx.resolver.username_for_sid(info.get("member_sid"))
                  or _clean(info.get("member_name")) or "an account")
        group = info.get("group_name") or "a group"
        admin = "admin" in group.lower()
        severity = SEV_SUSPICIOUS if admin else SEV_NOTABLE
        key = ("group", actor[1], member, group)
        _add(key, ts, rowid,
             "{} added '{}' to the '{}' group{}".format(
                 actor[1] or "Someone", member, group,
                 " — this grants administrator rights" if admin else ""),
             actor, severity)

    events = []
    for key, g in groups.items():
        n = len(g["rowids"])
        desc = g["desc"]
        if n > 1:
            desc += " ({} times)".format(n)
        events.append(_mk(
            rule, g["first_ts"], g["actor"], desc,
            [EvidenceRef(db="logs", table="SecurityLogs",
                         rowids=g["rowids"][:50], count=n)],
            ctx=ctx, severity=g["severity"], count=n,
            details={"kind": key[0]}))
    return events


import ntpath as _ntpath


def _wer_app(keywords):
    """Best-effort app / problem name from a WER 1001 payload."""
    if not keywords or keywords in ("N/A", "-"):
        return None, None
    parts = [p.strip() for p in str(keywords).split(",")]
    exe = next((p for p in parts if p.lower().endswith(".exe")), None)
    app = _ntpath.basename(exe) if exe else None
    problem = parts[2] if len(parts) > 2 and parts[2] not in ("", "-") else None
    return app, problem


def app_error(ctx, rules) -> List[BehaviorEvent]:
    """Application error / crash reports (Windows Error Reporting, App EID 1001),
    aggregated by app/problem."""
    rule = rules[0]
    buckets = defaultdict(lambda: {"rowids": [], "first_ts": None})
    for rowid, eid, ts, source, user, keywords, desc in _app_rows(ctx, [1001]):
        app, problem = _wer_app(keywords)
        label = app or problem or "an application"
        ts = normalize_ts(ts)
        b = buckets[label]
        b["rowids"].append(rowid)
        if b["first_ts"] is None or (ts and ts < b["first_ts"]):
            b["first_ts"] = ts
    events = []
    for label, b in buckets.items():
        n = len(b["rowids"])
        events.append(_mk(
            rule, b["first_ts"],
            ("Application", label, "recorded by Windows Error Reporting"),
            "An application error was reported for '{}'{}".format(
                label, " ({} times)".format(n) if n > 1 else ""),
            [EvidenceRef(db="logs", table="ApplicationLogs",
                         rowids=b["rowids"][:50], count=n)],
            ctx=ctx, count=n, app_name=label))
    return events


def service_state_changed(ctx, rules) -> List[BehaviorEvent]:
    """A service's start type was changed (System EID 7040). The payload
    carries no service name, so this is a system-configuration signal."""
    rule = rules[0]
    events = []
    for rowid, eid, ts, source, user, keywords, desc in _system_rows(
            ctx, [7040], source_like="%Service Control Manager%"):
        ts = normalize_ts(ts)
        events.append(_mk(
            rule, ts, ("System", "Windows", "recorded by the Service Control Manager"),
            "A Windows service's start type was changed",
            [EvidenceRef(db="logs", table="SystemLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    return events


def windows_update(ctx, rules) -> List[BehaviorEvent]:
    """WindowsUpdateClient 19 (installed) / 43 (started) / 44 (downloading),
    aggregated per day."""
    rule = rules[0]
    by_day = defaultdict(list)
    for rowid, eid, ts, source, user, keywords, desc in _system_rows(
            ctx, [19, 43, 44], source_like="%WindowsUpdateClient%"):
        ts = normalize_ts(ts)
        if ts:
            by_day[ts[:10]].append((rowid, ts))
    events = []
    for day, items in sorted(by_day.items()):
        rowids = [r for r, _ in items]
        events.append(_mk(
            rule, items[0][1],
            ("System", "Windows", "recorded by the Windows Update client"),
            "Windows downloaded or installed updates ({} update event{})".format(
                len(items), "s" if len(items) != 1 else ""),
            [EvidenceRef(db="logs", table="SystemLogs",
                         rowids=rowids[:50], count=len(rowids))],
            ctx=ctx, count=len(items)))
    return events
