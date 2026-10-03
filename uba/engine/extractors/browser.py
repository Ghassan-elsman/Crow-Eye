"""
Browser-primary extractors: behaviours proven by the browser's own databases
(`browser_analysis.db`, written by Browser_Claw).

Until now UBA's only browser rule read **typed URLs out of the registry** and
said so in a degrade note. Crow-Eye collects the real databases; this reads
them.

Design decisions taken against a real case rather than against the schema,
because three of them disagreed:

- **`from_webstore = 0` does not mean sideloaded.** 34 of 39 extensions in that
  case have it, because Edge and Brave extensions are not from the *Chrome*
  web store. Triggering on it would flag almost every extension installed. The
  risk signal is the **permission set**; `from_webstore` is context.
- **`browser.clear_data.*` is the state of the clear-browsing-data dialog**
  (which boxes are ticked, which time range is selected), not a record that
  anything was cleared, and `browser.last_clear_browsing_data_time` does not
  exist. A cleared history can only be *inferred*, from a gap that other
  artifacts contradict - so that rule carries CONF_INFERENCE and a caveat, and
  the dialog state rides along as context.
- **`browser_search_engines` is inert**: `is_default` never set, no
  `date_created`, no `usage_count`, and no `default_search_provider_data`
  preference. There is no honest default-search-hijack rule to write here, so
  none is written. See `_SEARCH_ENGINES_NOT_USABLE` below.

Two caveats the schema forces on anything history-derived, both real
attribution hazards:

- A **synced profile carries other devices' activity**. History on this machine
  is not proof the browsing happened on this machine.
- **Incognito leaves nothing here by design** - no column, no table. Absence of
  private browsing is not evidence it did not happen.

PRIVACY. Browser databases hold credentials, payment instruments and account
identity. Rules report *that* something exists and how it was used - counts,
hosts, timestamps - and never the value. `account_info.*` in particular carries
e-mail, full name and phone number; a sync rule says an account is signed in,
never whose. Row pointers go in EvidenceRef and reach the analyst through the
evidence modal, which is where that line is already drawn.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

from uba.engine.models import (BehaviorEvent, EvidenceRef, CONF_ARTIFACT_ONLY,
                               CONF_INFERENCE, SEV_NOTABLE)
from uba.utils.timeparse import normalize_ts

logger = logging.getLogger(__name__)

DB = "browser"

CAVEAT_SYNCED_PROFILE = (
    "A signed-in profile synchronises history between devices, so a visit "
    "recorded here may have happened on another machine."
)
CAVEAT_NO_PRIVATE_MODE = (
    "Private/Incognito browsing is not recorded in these databases at all, so "
    "this is a floor on activity, never a complete account of it."
)
CAVEAT_CLEARED_INFERRED = (
    "Inferred, not observed: browsers keep no log of a history deletion. A "
    "quiet stretch in history that cookies or site-engagement records "
    "contradict is consistent with a clearance - and also with a profile that "
    "simply was not used for browsing while other state was written."
)

# Permissions worth a second look on any extension, whatever store it came
# from. Deliberately short: a list that matches most extensions is a list that
# tells an analyst nothing.
RISKY_PERMISSIONS = (
    "<all_urls>", "webRequest", "webRequestBlocking", "nativeMessaging",
    "debugger", "proxy", "cookies", "privacy", "management",
    "declarativeNetRequest", "desktopCapture", "tabCapture",
)

# Kept as a note rather than a rule: see the module docstring.
_SEARCH_ENGINES_NOT_USABLE = (
    "browser_search_engines carries the shipped engine list with no state - "
    "is_default unset, date_created empty, usage_count zero - so a "
    "default-search-hijack rule would never fire. Revisit if the parser "
    "starts recording default_search_provider_data."
)

# A gap in history this long, while other browser state was being written, is
# worth surfacing. Shorter stretches are ordinary (a weekend, a trip).
GAP_DAYS = 3


# --------------------------------------------------------------------------- helpers
def _mk(rule, ctx, ts, actor, text, evidence, confidence=CONF_ARTIFACT_ONLY,
        severity=None, details=None, count=1, ts_end=None, caveat="", app_name=""):
    actor_type, actor_name, actor_basis = actor
    return BehaviorEvent(
        rule_id=rule["id"], behavior_class=rule["behavior_class"],
        activity=rule["activity"], ts_start=ts, ts_end=ts_end or ts,
        actor_type=actor_type, actor_name=actor_name, actor_basis=actor_basis,
        description=text, severity=severity or rule["severity"],
        confidence=confidence, caveat=caveat, app_name=app_name,
        session_context=ctx.session_context(ts) if ts else "",
        aggregate_count=count, details=details or {}, evidence=evidence)


def _rows(ctx, sql, params=()):
    conn = ctx.pool.get(DB)
    if conn is None:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as e:
        logger.warning("UBA: browser query failed: %s", e)
        return []


def _has(ctx, table):
    return ctx.pool.has_table(DB, table)


def _actor(ctx, sid, user_name, label):
    """Per-row attribution. Every browser table carries the owning SID.

    Stronger than the registry rule it replaces, which could only say "a user
    of this profile" because a user hive names no one.
    """
    if sid:
        return ctx.resolver.from_sid(sid, label)
    if user_name:
        return ctx.resolver.from_account_name(user_name, label)
    return ctx.resolver.from_user_hive(label)


def _host(url):
    """eTLD+1 is overkill; the host is what an analyst reads."""
    text = str(url or "")
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split("/", 1)[0].split("?", 1)[0] or "an unknown host"


def _day(ts):
    return (ts or "")[:10]


# --------------------------------------------------------------------------- rules
def web_history(ctx, rules) -> List[BehaviorEvent]:
    """Browsing, aggregated per user per browser per day.

    One event per visit would be 13,730 events on a single real case and would
    bury every other behaviour on the timeline. A day's browsing in one browser
    is the unit an analyst actually reasons about; the evidence ref points at
    every row behind it.
    """
    rule = rules[0]
    events = []
    for table, kind in (("browser_history", "chromium"),
                        ("browser_gecko_history", "gecko")):
        if not _has(ctx, table):
            continue
        time_col = "visit_time" if kind == "chromium" else "visit_time"
        buckets = defaultdict(lambda: {"rowids": [], "hosts": set(),
                                       "first": None, "last": None})
        for row in _rows(ctx, 'SELECT rowid, browser, sid, user_name, url, "%s" t '
                              'FROM "%s"' % (time_col, table)):
            ts = normalize_ts(row["t"])
            if not ts:
                continue
            key = (row["sid"], row["user_name"], row["browser"] or "a browser", _day(ts))
            b = buckets[key]
            b["rowids"].append(row["rowid"])
            b["hosts"].add(_host(row["url"]))
            if b["first"] is None or ts < b["first"]:
                b["first"] = ts
            if b["last"] is None or ts > b["last"]:
                b["last"] = ts

        for (sid, user_name, browser, _d), b in buckets.items():
            actor = _actor(ctx, sid, user_name, "the browser history database")
            hosts = len(b["hosts"])
            text = "%s browsed %d site%s in %s" % (
                actor[1] or "A user", hosts, "" if hosts == 1 else "s", browser)
            events.append(_mk(
                rule, ctx, b["first"], actor, text,
                [EvidenceRef(db=DB, table=table, rowids=b["rowids"][:500],
                             count=len(b["rowids"]))],
                ts_end=b["last"], count=len(b["rowids"]), app_name=browser,
                caveat=CAVEAT_SYNCED_PROFILE + " " + CAVEAT_NO_PRIVATE_MODE,
                details={"browser": browser, "distinct_hosts": hosts,
                         "visits": len(b["rowids"])}))
    return events


def web_downloads(ctx, rules) -> List[BehaviorEvent]:
    """Files fetched through the browser, and the ones it objected to.

    Two rules share this extractor: an ordinary download, and one the browser
    flagged or could not finish. `danger_type` and `interrupt_reason` are
    Chromium enums - the fact that they are non-zero is the finding; decoding
    every value is not this rule's job.
    """
    by_id = {r["id"]: r for r in rules}
    plain = by_id.get("browser_download")
    flagged = by_id.get("browser_download_flagged")
    if not _has(ctx, "browser_downloads"):
        return []
    events = []
    for row in _rows(ctx,
                     "SELECT rowid, browser, sid, user_name, target_path, source_url, "
                     "referrer, received_bytes, total_bytes, start_time, danger_type, "
                     "interrupt_reason, state, mime_type FROM browser_downloads"):
        ts = normalize_ts(row["start_time"])
        actor = _actor(ctx, row["sid"], row["user_name"], "the browser download record")
        host = _host(row["source_url"])
        name = str(row["target_path"] or "").replace("/", "\\").split("\\")[-1]
        danger = row["danger_type"] or 0
        interrupted = str(row["interrupt_reason"] or "") not in ("", "0")
        evidence = [EvidenceRef(db=DB, table="browser_downloads",
                                rowids=[row["rowid"]], count=1)]
        details = {"host": host, "file": name, "browser": row["browser"],
                   "bytes": row["received_bytes"], "mime": row["mime_type"],
                   "danger_type": danger, "state": row["state"]}
        if (danger or interrupted) and flagged is not None:
            why = []
            if danger:
                why.append("flagged by the browser (danger type %s)" % danger)
            if interrupted:
                why.append("did not complete (reason %s)" % row["interrupt_reason"])
            events.append(_mk(
                flagged, ctx, ts, actor,
                "%s downloaded '%s' from %s - %s"
                % (actor[1] or "A user", name or "a file", host, " and ".join(why)),
                evidence, severity=SEV_NOTABLE, details=details,
                app_name=row["browser"] or ""))
        elif plain is not None:
            events.append(_mk(
                plain, ctx, ts, actor,
                "%s downloaded '%s' from %s"
                % (actor[1] or "A user", name or "a file", host),
                evidence, details=details, app_name=row["browser"] or ""))
    return events


def browser_profile_state(ctx, rules) -> List[BehaviorEvent]:
    """Preference-recorded state: abnormal exits, save locations, sync.

    Three rules share this extractor because they all read one table and the
    interesting keys are a short whitelist.
    """
    by_id = {r["id"]: r for r in rules}
    if not _has(ctx, "browser_preferences"):
        return []
    rows = _rows(ctx, "SELECT rowid, browser, sid, user_name, profile, setting_key, "
                      "setting_value FROM browser_preferences")
    events = []

    # --- abnormal exit ---
    rule = by_id.get("browser_abnormal_exit")
    if rule is not None:
        for row in rows:
            if row["setting_key"] != "profile.exit_type":
                continue
            value = str(row["setting_value"] or "")
            if value in ("Normal", "SessionEnded", ""):
                continue
            actor = _actor(ctx, row["sid"], row["user_name"], "the browser profile preferences")
            events.append(_mk(
                rule, ctx, None, actor,
                "%s's %s profile last closed abnormally (%s)"
                % (actor[1] or "A user", row["browser"] or "browser", value),
                [EvidenceRef(db=DB, table="browser_preferences",
                             rowids=[row["rowid"]], count=1)],
                severity=SEV_NOTABLE, app_name=row["browser"] or "",
                details={"exit_type": value, "profile": row["profile"]}))

    # --- where downloads are saved ---
    rule = by_id.get("browser_save_location")
    if rule is not None:
        for row in rows:
            if row["setting_key"] not in ("savefile.default_directory",
                                          "selectfile.last_directory",
                                          "download.default_directory"):
                continue
            value = str(row["setting_value"] or "")
            if not value:
                continue
            actor = _actor(ctx, row["sid"], row["user_name"], "the browser profile preferences")
            events.append(_mk(
                rule, ctx, None, actor,
                "%s's %s saves downloads to %s"
                % (actor[1] or "A user", row["browser"] or "browser", value),
                [EvidenceRef(db=DB, table="browser_preferences",
                             rowids=[row["rowid"]], count=1)],
                app_name=row["browser"] or "",
                details={"key": row["setting_key"], "directory": value}))

    # --- signed in / syncing ---
    # NOTE: account_info.* holds e-mail, full name and phone number. This rule
    # reports THAT an account is signed in and syncing, never whose, and no
    # account_info value is read at all.
    rule = by_id.get("browser_account_sync")
    if rule is not None:
        per_profile = defaultdict(lambda: {"rowids": [], "flags": {}, "meta": None})
        for row in rows:
            key = str(row["setting_key"] or "")
            if key not in ("signin.allowed", "sync.has_been_enabled",
                           "sync.keep_everything_synced", "sync.passwords",
                           "sync.history_edge_supported", "sync.tabs"):
                continue
            slot = per_profile[(row["sid"], row["user_name"], row["browser"], row["profile"])]
            slot["rowids"].append(row["rowid"])
            slot["flags"][key] = str(row["setting_value"] or "")
            slot["meta"] = row
        for (sid, user_name, browser, profile), slot in per_profile.items():
            flags = slot["flags"]
            on = [k for k, v in flags.items() if v.lower() in ("true", "1")]
            if not on:
                continue
            actor = _actor(ctx, sid, user_name, "the browser profile preferences")
            events.append(_mk(
                rule, ctx, None, actor,
                "%s is signed into %s with synchronisation enabled (%s)"
                % (actor[1] or "A user", browser or "a browser",
                   ", ".join(sorted(k.split(".")[-1] for k in on))),
                [EvidenceRef(db=DB, table="browser_preferences",
                             rowids=slot["rowids"], count=len(slot["rowids"]))],
                app_name=browser or "", caveat=CAVEAT_SYNCED_PROFILE,
                details={"profile": profile, "enabled": sorted(on)}))
    return events


def browser_extensions(ctx, rules) -> List[BehaviorEvent]:
    """Extensions holding permissions worth reviewing.

    NOT keyed on `from_webstore`: in a real three-browser case 34 of 39
    extensions have it zero, because Edge and Brave extensions do not come from
    the Chrome web store. It is reported as context instead.
    """
    rule = rules[0]
    if not _has(ctx, "browser_extensions"):
        return []
    events = []
    for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, extension_id, name, "
                          "version, permissions, install_time, from_webstore, state "
                          "FROM browser_extensions"):
        raw = str(row["permissions"] or "")
        matched = sorted({p for p in RISKY_PERMISSIONS if p in raw})
        if not matched:
            continue
        actor = _actor(ctx, row["sid"], row["user_name"], "the browser extension record")
        events.append(_mk(
            rule, ctx, normalize_ts(row["install_time"]), actor,
            "%s has '%s' installed in %s, holding %s"
            % (actor[1] or "A user", row["name"] or row["extension_id"],
               row["browser"] or "a browser", ", ".join(matched)),
            [EvidenceRef(db=DB, table="browser_extensions",
                         rowids=[row["rowid"]], count=1)],
            severity=SEV_NOTABLE, app_name=row["browser"] or "",
            details={"extension_id": row["extension_id"], "version": row["version"],
                     "permissions": matched, "from_webstore": row["from_webstore"],
                     "state": row["state"]}))
    return events


def browser_stored_secrets(ctx, rules) -> List[BehaviorEvent]:
    """Credentials, payment instruments and addresses the browser holds.

    Counts and hosts only. The values stay in the database: the parser keeps
    the ciphertext deliberately and this never decrypts, reads or forwards it.
    """
    rule = rules[0]
    events = []
    per_user = defaultdict(lambda: {"creds": 0, "used": 0, "cards": 0, "addresses": 0,
                                    "hosts": set(), "last_used": None,
                                    "refs": [], "browser": ""})

    # Chromium and Gecko name the same facts differently - `signon_realm` vs
    # `hostname`, `date_last_used` vs `time_last_used`. Naming the wrong one
    # fails the whole query inside _rows(), which logs a line and returns [],
    # so the behaviour would vanish from the report with the run still green.
    for table, host_col, last_col in (
            ("browser_credentials", "signon_realm", "date_last_used"),
            ("browser_gecko_credentials", "hostname", "time_last_used")):
        if not _has(ctx, table):
            continue
        for row in _rows(ctx, 'SELECT rowid, browser, sid, user_name, "%s" h, '
                              'times_used used, "%s" last FROM "%s"'
                              % (host_col, last_col, table)):
            slot = per_user[(row["sid"], row["user_name"])]
            slot["creds"] += 1
            slot["browser"] = slot["browser"] or (row["browser"] or "")
            if (row["used"] or 0) > 0:
                slot["used"] += 1
            if row["h"]:
                slot["hosts"].add(_host(row["h"]))
            ts = normalize_ts(row["last"])
            if ts and (slot["last_used"] is None or ts > slot["last_used"]):
                slot["last_used"] = ts
            slot["refs"].append((table, row["rowid"]))

    for table, field in (("browser_payments", "cards"), ("browser_addresses", "addresses")):
        if not _has(ctx, table):
            continue
        for row in _rows(ctx, 'SELECT rowid, browser, sid, user_name FROM "%s"' % table):
            slot = per_user[(row["sid"], row["user_name"])]
            slot[field] += 1
            slot["refs"].append((table, row["rowid"]))

    for (sid, user_name), slot in per_user.items():
        if not (slot["creds"] or slot["cards"] or slot["addresses"]):
            continue
        actor = _actor(ctx, sid, user_name, "the browser credential store")
        parts = []
        if slot["creds"]:
            parts.append("%d saved login%s for %d site%s (%d used at least once)"
                         % (slot["creds"], "" if slot["creds"] == 1 else "s",
                            len(slot["hosts"]), "" if len(slot["hosts"]) == 1 else "s",
                            slot["used"]))
        if slot["cards"]:
            parts.append("%d stored payment instrument%s"
                         % (slot["cards"], "" if slot["cards"] == 1 else "s"))
        if slot["addresses"]:
            parts.append("%d stored address%s"
                         % (slot["addresses"], "" if slot["addresses"] == 1 else "es"))
        by_table = defaultdict(list)
        for table, rowid in slot["refs"]:
            by_table[table].append(rowid)
        events.append(_mk(
            rule, ctx, slot["last_used"], actor,
            "%s's browser holds %s" % (actor[1] or "A user", "; ".join(parts)),
            [EvidenceRef(db=DB, table=t, rowids=ids[:500], count=len(ids))
             for t, ids in by_table.items()],
            severity=SEV_NOTABLE, app_name=slot["browser"],
            details={"logins": slot["creds"], "logins_used": slot["used"],
                     "distinct_hosts": len(slot["hosts"]),
                     "payment_instruments": slot["cards"],
                     "addresses": slot["addresses"]}))
    return events


def browser_history_gap(ctx, rules) -> List[BehaviorEvent]:
    """A quiet stretch in history that other browser state contradicts.

    Browsers keep no deletion log, so a cleared history can only ever be
    inferred. The inference: history goes quiet for GAP_DAYS or more while
    cookies were still being created or site-engagement records were still
    being written in the same window.

    `browser_cache` is deliberately not used as corroboration - in the case
    this was built against it carries no usable request_time at all, so it
    would contribute nothing while appearing to.
    """
    rule = rules[0]
    if not _has(ctx, "browser_history"):
        return []

    days = sorted({_day(normalize_ts(r["t"]))
                   for r in _rows(ctx, "SELECT visit_time t FROM browser_history")
                   if normalize_ts(r["t"])})
    if len(days) < 2:
        return []

    other = []
    if _has(ctx, "browser_cookies"):
        other += [normalize_ts(r["t"]) for r in
                  _rows(ctx, "SELECT creation_time t FROM browser_cookies")]
    if _has(ctx, "browser_dips"):
        other += [normalize_ts(r["t"]) for r in
                  _rows(ctx, "SELECT last_user_interaction_time t FROM browser_dips")]
    other_days = {_day(t) for t in other if t}
    if not other_days:
        return []

    # The clear-browsing-data dialog's state, if the parser captured it. Not
    # evidence of a clearance - which boxes are ticked, nothing more.
    dialog = {}
    for row in _rows(ctx, "SELECT setting_key k, setting_value v FROM browser_preferences "
                          "WHERE setting_key LIKE 'browser.clear_data%'") \
            if _has(ctx, "browser_preferences") else []:
        dialog[row["k"]] = row["v"]

    events = []
    for a, b in zip(days, days[1:]):
        try:
            start = datetime.strptime(a, "%Y-%m-%d")
            end = datetime.strptime(b, "%Y-%m-%d")
        except ValueError:
            continue
        gap = (end - start).days
        if gap < GAP_DAYS:
            continue
        inside = {(start + timedelta(days=n)).strftime("%Y-%m-%d")
                  for n in range(1, gap)}
        corroborating = sorted(inside & other_days)
        if not corroborating:
            continue
        actor = ctx.resolver.from_user_hive("the browser history database")
        events.append(_mk(
            rule, ctx, a + " 00:00:00", actor,
            "Browsing history is silent for %d days after %s, but cookies or "
            "site-engagement records were still being written on %d of them"
            % (gap, a, len(corroborating)),
            [EvidenceRef(db=DB, table="browser_history", rowids=[], count=0)],
            confidence=CONF_INFERENCE, severity=SEV_NOTABLE,
            caveat=CAVEAT_CLEARED_INFERRED, ts_end=b + " 00:00:00",
            details={"gap_days": gap, "corroborating_days": corroborating[:20],
                     "clear_data_dialog": dialog or "not recorded"}))
    return events
