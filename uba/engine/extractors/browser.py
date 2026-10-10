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
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

from uba.engine import site_categories as sc
from uba.engine.models import (BehaviorEvent, EvidenceRef, CONF_ARTIFACT_ONLY,
                               CONF_INFERENCE, SEV_NOTABLE, SEV_SUSPICIOUS)
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

# Component extensions the browser itself installs, holding broad permissions
# by design (the store needs `management`, the feedback tool `debugger`). On a
# real case they were five of the nine "risky" extensions, every one of which
# an analyst would dismiss.
BUILT_IN_EXTENSIONS = {
    "ahfgeienlihckogmohjhadlkjgocpleb",   # Web Store (Chrome, Edge, Brave)
    "iglcjdemknebjbklcgkfaebgojjphkec",   # Microsoft Store (Edge)
    "ihmafllikibpmigkcoadcmckbfhibefp",   # Edge / Copilot Feedback
    "mnojpmjdmbbfmejpflffifhffcmidifd",   # Brave (Brave's own component)
    "jmjflgjpcpepeafmmgdpfkogkghcpiha",   # Edge Clipboard / Media
    "nmmhkkegccagdldgiimedpiccmgmieda",   # Chrome Web Store Payments
    "neajdppkdcdipfabeoofebfddakdcjhd",   # Google Network Speech
    "pkedcjkdefgpdelpbcmbmeomcjbeemfm",   # Chrome Media Router
}

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


CAVEAT_OPENED_WHEN = (
    "The browser records THAT the file was opened from its download list, not "
    "when: the time shown is when the download started, and the opening came "
    "at some point after it."
)
CAVEAT_TIMELESS_STATE = (
    "This is the state the browser was in when its files were collected; the "
    "files' own timestamps are when Crow-Eye extracted them, so no time is "
    "given rather than a misleading one."
)
CAVEAT_UPLOAD_INFERRED = (
    "Inferred, not observed: the browser recorded that a form on this site was "
    "submitted. A form submission does not prove a file was attached - it is "
    "the step an upload takes, and also the step a search box or a comment "
    "takes."
)

# Download categories that make a source worth a second look.
RISKY_DOWNLOAD_CATEGORIES = ("file_sharing", "paste", "anonymiser", "hacking_tools")

# file kind -> extensions. "script" before "program": .ps1 is a script.
_KINDS = (
    ("program", (".exe", ".scr", ".com", ".pif", ".cpl", ".dll", ".sys")),
    ("script", (".ps1", ".psm1", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf",
                ".wsh", ".hta", ".py", ".sh", ".lnk", ".reg")),
    ("installer", (".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".msp", ".jar",
                   ".apk", ".dmg", ".pkg", ".deb", ".rpm")),
    ("disk image", (".iso", ".img", ".vhd", ".vhdx")),
)
_DOC_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".jpg",
             ".jpeg", ".png", ".gif", ".zip", ".rar", ".7z", ".mp3", ".mp4", ".rtf", ".csv")

# Chromium page transitions that are a person's own navigation. Excluded:
# subframes (a page loading another page), reloads, redirects and the start
# page, none of which is someone choosing to go somewhere.
_USER_TRANSITIONS = {"link", "typed", "auto_bookmark", "form_submit", "keyword",
                     "keyword_generated", "generated"}
# The same, when the parser stored the numeric core transition.
_TRANSITION_CODES = {0: "link", 1: "typed", 2: "auto_bookmark", 3: "auto_subframe",
                     4: "manual_subframe", 5: "generated", 6: "start_page",
                     7: "form_submit", 8: "reload", 9: "keyword", 10: "keyword_generated"}
# Gecko visit types: 1 link, 2 typed, 3 bookmark, 7 download.
_GECKO_USER_TYPES = {1, 2, 3, 7}

# Category -> rule id of the site-visit rule that reports it.
_VISIT_RULES = {
    "file_sharing": "browser_visit_file_sharing",
    "paste": "browser_visit_paste_site",
    "anonymiser": "browser_visit_anonymiser",
    "crypto": "browser_visit_crypto",
    "remote_access": "browser_visit_remote_access",
    "ai_chat": "browser_visit_ai_chat",
    "hacking_tools": "browser_visit_hacking_resource",
}
# Sensitive enough to raise a tab left open at exit to notable.
_SENSITIVE_CATEGORIES = ("file_sharing", "paste", "anonymiser", "crypto", "remote_access",
                         "hacking_tools")
_LOGIN_PATH = ("login", "signin", "sign-in", "sign_in", "auth", "oauth", "account",
               "register", "signup", "sign-up", "password", "sso", "session")

MAX_HOSTS = 10
MAX_TERMS = 15


def _transition(value):
    if value is None:
        return ""
    if isinstance(value, int) or str(value).isdigit():
        return _TRANSITION_CODES.get(int(value) & 0xFF, "")
    return str(value).strip().lower()


def _user_visit(row, gecko):
    if gecko:
        try:
            return int(row["visit_type"]) in _GECKO_USER_TYPES
        except (TypeError, ValueError):
            return False
    return _transition(row["transition"]) in _USER_TRANSITIONS


def _file_kind(name):
    """(kind or None, double extension?) - 'invoice.pdf.exe' is a program
    whose name claims to be a document."""
    low = str(name or "").lower().strip()
    kind = None
    for k, exts in _KINDS:
        if low.endswith(exts):
            kind = k
            break
    double = False
    if kind:
        stem = low.rsplit(".", 1)[0]
        double = stem.endswith(_DOC_EXTS)
    return kind, double


def _ip_scope(url):
    """'loopback' / 'private' / 'public' for a raw-IP host, None for a name."""
    if not sc.is_raw_ip(url):
        return None
    import ipaddress
    host = sc._split(url)[0].strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.is_loopback:
        return "loopback"
    # The local network, named explicitly: ipaddress.is_private also covers
    # documentation and reserved ranges, which are not anyone's LAN.
    lan = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
    if ip.is_link_local or any(ip in ipaddress.ip_network(n) for n in lan
                               if ipaddress.ip_network(n).version == ip.version):
        return "private"
    return "public"


def _is_local_name(url):
    host = sc._split(url)[0]
    return host in ("localhost",) or host.endswith((".local", ".localhost", ".lan", ".internal"))


def _path(url):
    return sc._split(url)[1].lower()


def _history_rows(ctx):
    """Every history visit, Chromium and Gecko, as (table, row, gecko)."""
    out = []
    if _has(ctx, "browser_history"):
        for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, url, title, "
                              "visit_time, transition FROM browser_history"):
            out.append(("browser_history", row, False))
    if _has(ctx, "browser_gecko_history"):
        for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, url, title, "
                              "visit_time, visit_type FROM browser_gecko_history"):
            out.append(("browser_gecko_history", row, True))
    return out


def _refs(pairs):
    by_table = defaultdict(list)
    for table, rowid in pairs:
        by_table[table].append(rowid)
    return [EvidenceRef(db=DB, table=t, rowids=ids[:500], count=len(ids))
            for t, ids in by_table.items()]


def _plural(n, word, plural=None):
    return "%d %s" % (n, word if n == 1 else (plural or word + "s"))



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
    """Files fetched through the browser - one event per download, plus "opened".

    Five rules share this extractor. Each download produces exactly ONE of the
    first four, in this order of precedence:

    1. ``browser_download_flagged``        the browser marked it dangerous or it
                                           did not complete;
    2. ``browser_download_risky_source``   from a public raw IP, over plain http
                                           from a non-local host, or from a
                                           file-sharing / paste / anonymiser /
                                           hacking-resource site (suspicious when
                                           the file is also executable);
    3. ``browser_download_executable``     a program, script, installer or disk
                                           image - double extensions called out;
    4. ``browser_download``                anything else.

    ``browser_download_opened`` is a separate act and a separate event: the
    browser recorded that the user opened the file from its download list
    (Chromium only - Gecko keeps no such flag).

    Loopback is never "risky": a local web app (a Gradio UI on 127.0.0.1)
    serves files over plain http, and on a real case it was the only http
    source there was.
    """
    by_id = {r["id"]: r for r in rules}
    plain = by_id.get("browser_download")
    flagged = by_id.get("browser_download_flagged")
    risky = by_id.get("browser_download_risky_source")
    executable = by_id.get("browser_download_executable")
    opened_rule = by_id.get("browser_download_opened")

    sources = []
    if _has(ctx, "browser_downloads"):
        for row in _rows(ctx,
                         "SELECT rowid, browser, sid, user_name, target_path, source_url, "
                         "referrer, received_bytes, total_bytes, start_time, danger_type, "
                         "interrupt_reason, state, mime_type, opened FROM browser_downloads"):
            sources.append(("browser_downloads", row["rowid"], row, row["source_url"],
                            row["danger_type"] or 0,
                            str(row["interrupt_reason"] or "") not in ("", "0"),
                            row["opened"]))
    if _has(ctx, "browser_gecko_downloads"):
        for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, target_path, url, "
                              "start_time, state FROM browser_gecko_downloads"):
            sources.append(("browser_gecko_downloads", row["rowid"], row, row["url"], 0,
                            False, None))

    events = []
    for table, rowid, row, url, danger, interrupted, opened in sources:
        ts = normalize_ts(row["start_time"])
        actor = _actor(ctx, row["sid"], row["user_name"], "the browser download record")
        host = _host(url)
        name = str(row["target_path"] or "").replace("/", "\\").split("\\")[-1]
        kind, double_ext = _file_kind(name)
        category = sc.categorize(url)
        scope = _ip_scope(url)
        is_http = str(url or "").lower().startswith("http://")
        risky_why = []
        if scope == "public":
            risky_why.append("a raw IP address")
        if is_http and scope not in ("loopback", "private") and not _is_local_name(url):
            risky_why.append("an unencrypted http connection")
        if category in RISKY_DOWNLOAD_CATEGORIES:
            risky_why.append("a %s site" % sc.category_label(category))
        evidence = [EvidenceRef(db=DB, table=table, rowids=[rowid], count=1)]
        details = {"host": host, "file": name, "browser": row["browser"],
                   "file_kind": kind or "other", "state": row["state"]}
        if table == "browser_downloads":
            details.update(bytes=row["received_bytes"], mime=row["mime_type"],
                           danger_type=danger)
        if double_ext:
            details["double_extension"] = True
        if category:
            details["site_category"] = category
        if scope:
            details["address"] = scope
        who = actor[1] or "A user"
        what = "'%s'" % name if name else "a file"
        app = row["browser"] or ""

        if (danger or interrupted) and flagged is not None:
            why = []
            if danger:
                why.append("flagged by the browser (danger type %s)" % danger)
            if interrupted:
                why.append("did not complete (reason %s)" % row["interrupt_reason"])
            events.append(_mk(flagged, ctx, ts, actor,
                              "%s downloaded %s from %s - %s" % (who, what, host, " and ".join(why)),
                              evidence, severity=SEV_NOTABLE, details=details, app_name=app))
        elif risky_why and risky is not None:
            sev = SEV_SUSPICIOUS if kind in ("program", "script", "installer") else SEV_NOTABLE
            text = "%s downloaded %s from %s, over %s" % (who, what, host, " and ".join(risky_why))
            if kind:
                text += " - a %s%s" % (kind, " with a double extension" if double_ext else "")
            events.append(_mk(risky, ctx, ts, actor, text, evidence, severity=sev,
                              details=details, app_name=app))
        elif kind and executable is not None:
            text = "%s downloaded the %s %s from %s" % (who, kind, what, host)
            if double_ext:
                text += " (double extension - the name disguises the file type)"
            events.append(_mk(executable, ctx, ts, actor, text, evidence,
                              severity=SEV_SUSPICIOUS if double_ext else None,
                              details=details, app_name=app))
        elif plain is not None:
            events.append(_mk(plain, ctx, ts, actor,
                              "%s downloaded %s from %s" % (who, what, host),
                              evidence, details=details, app_name=app))

        if opened and opened_rule is not None:
            events.append(_mk(
                opened_rule, ctx, ts, actor,
                "%s opened %s from the browser's download list" % (who, what),
                evidence, severity=SEV_NOTABLE if kind in ("program", "script", "installer")
                else None, details=dict(details, opened=True), app_name=app,
                caveat=CAVEAT_OPENED_WHEN))
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
            # signin.allowed is the policy default - true on a profile nobody
            # ever signed into. Only a sync.* flag says sync was turned on.
            if not any(k.startswith("sync.") for k in on):
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
        if not matched or str(row["extension_id"] or "").lower() in BUILT_IN_EXTENSIONS:
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
                                    "refs": [], "browser": "", "by_category": {}})

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
                cat = sc.categorize(row["h"])
                if cat:
                    slot["by_category"][cat] = slot["by_category"].get(cat, 0) + 1
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
        # Logins for sites in a category an examiner asks about - hosts and
        # counts only, never the account name.
        notable = {c: n for c, n in slot["by_category"].items() if c != "ai_chat"}
        if notable:
            parts.append("logins for %s" % ", ".join(
                "%d %s site%s" % (n, sc.category_label(c), "" if n == 1 else "s")
                for c, n in sorted(notable.items())))
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
                     "logins_by_category": slot["by_category"],
                     "addresses": slot["addresses"]}))
    return events


def browser_history_gap(ctx, rules) -> List[BehaviorEvent]:
    """A quiet stretch in a profile's history that the same profile's other
    state contradicts.

    Browsers keep no deletion log, so a cleared history can only ever be
    inferred. The inference: one profile's history (Chromium or Gecko) goes
    quiet for GAP_DAYS or more while that profile was still creating cookies
    or writing site-engagement records in the same window. Per profile - one
    browser's busy cookies say nothing about another browser's quiet history.

    `browser_cache` is deliberately not used as corroboration - in the case
    this was built against it carries no usable request_time at all, so it
    would contribute nothing while appearing to.
    """
    rule = rules[0]
    history = defaultdict(set)
    for table, row, _gecko in _history_rows(ctx):
        ts = normalize_ts(row["visit_time"])
        if ts:
            history[(row["sid"], row["user_name"], row["browser"])].add(_day(ts))
    if not history:
        return []

    other = defaultdict(set)
    for table, col in (("browser_cookies", "creation_time"),
                       ("browser_gecko_cookies", "creation_time"),
                       ("browser_dips", "last_user_interaction_time")):
        if not _has(ctx, table):
            continue
        for r in _rows(ctx, 'SELECT sid, browser, "%s" t FROM "%s"' % (col, table)):
            ts = normalize_ts(r["t"])
            if ts:
                other[(r["sid"], r["browser"])].add(_day(ts))

    # The clear-browsing-data dialog's state, if the parser captured it. Not
    # evidence of a clearance - which boxes are ticked, nothing more.
    dialog = defaultdict(dict)
    if _has(ctx, "browser_preferences"):
        for row in _rows(ctx, "SELECT sid, browser, setting_key k, setting_value v "
                              "FROM browser_preferences WHERE setting_key LIKE 'browser.clear_data%'"):
            dialog[(row["sid"], row["browser"])][row["k"]] = row["v"]

    events = []
    for (sid, user_name, browser), day_set in history.items():
        days = sorted(day_set)
        other_days = other.get((sid, browser), set())
        if len(days) < 2 or not other_days:
            continue
        for a, b in zip(days, days[1:]):
            try:
                start = datetime.strptime(a, "%Y-%m-%d")
                end = datetime.strptime(b, "%Y-%m-%d")
            except ValueError:
                continue
            gap = (end - start).days
            if gap < GAP_DAYS:
                continue
            inside = {(start + timedelta(days=n)).strftime("%Y-%m-%d") for n in range(1, gap)}
            corroborating = sorted(inside & other_days)
            if not corroborating:
                continue
            actor = _actor(ctx, sid, user_name, "the browser history database")
            events.append(_mk(
                rule, ctx, a + " 00:00:00", actor,
                "%s's %s history is silent for %d days after %s, but the same profile was "
                "still writing cookies or site-engagement records on %d of them"
                % (actor[1] or "A user", browser or "browser", gap, a, len(corroborating)),
                [EvidenceRef(db=DB, table="browser_history", rowids=[], count=0)],
                confidence=CONF_INFERENCE, severity=SEV_NOTABLE,
                caveat=CAVEAT_CLEARED_INFERRED, ts_end=b + " 00:00:00", app_name=browser or "",
                details={"gap_days": gap, "corroborating_days": corroborating[:20],
                         "clear_data_dialog": dialog.get((sid, browser)) or "not recorded"}))
    return events


# --------------------------------------------------------------------------- round-11 rules
def browser_web_search(ctx, rules) -> List[BehaviorEvent]:
    """What a person searched for - one event per user, browser and day.

    Two sources: search-engine result pages in history (the query is in the
    URL), and the omnibox shortcuts table, which keeps what was TYPED before a
    suggestion was chosen. Searches reached by reloading or inside a frame are
    not counted - they are not the person asking again.
    """
    rule = rules[0]
    buckets = defaultdict(lambda: {"terms": [], "seen": set(), "engines": set(),
                                   "refs": [], "first": None, "last": None})

    def add(key, ts, engine, words, ref):
        b = buckets[key]
        if words.lower() not in b["seen"]:
            b["seen"].add(words.lower())
            b["terms"].append(words)
        b["engines"].add(engine)
        b["refs"].append(ref)
        b["first"] = ts if b["first"] is None or ts < b["first"] else b["first"]
        b["last"] = ts if b["last"] is None or ts > b["last"] else b["last"]

    for table, row, gecko in _history_rows(ctx):
        if not gecko and _transition(row["transition"]) in ("reload", "auto_subframe",
                                                            "manual_subframe"):
            continue
        st = sc.search_term(row["url"])
        ts = normalize_ts(row["visit_time"])
        if not st or not ts:
            continue
        add((row["sid"], row["user_name"], row["browser"] or "a browser", _day(ts)),
            ts, st[0], st[1], (table, row["rowid"]))
    if _has(ctx, "browser_shortcuts"):
        for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, text, url, "
                              "last_access_time FROM browser_shortcuts"):
            st = sc.search_term(row["url"])
            ts = normalize_ts(row["last_access_time"])
            if not st or not ts:
                continue
            add((row["sid"], row["user_name"], row["browser"] or "a browser", _day(ts)),
                ts, st[0], st[1], ("browser_shortcuts", row["rowid"]))

    events = []
    for (sid, user_name, browser, _d), b in buckets.items():
        actor = _actor(ctx, sid, user_name, "the browser history database")
        shown = b["terms"][:MAX_TERMS]
        more = len(b["terms"]) - len(shown)
        text = "%s searched for %s in %s" % (
            actor[1] or "A user", ", ".join('"%s"' % t for t in shown), browser)
        if more:
            text += " and %d more" % more
        events.append(_mk(rule, ctx, b["first"], actor, text, _refs(b["refs"]),
                          ts_end=b["last"], count=len(b["terms"]), app_name=browser,
                          caveat=CAVEAT_SYNCED_PROFILE,
                          details={"terms": b["terms"][:50], "engines": sorted(b["engines"]),
                                   "searches": len(b["terms"])}))
    return events


def browser_site_visits(ctx, rules) -> List[BehaviorEvent]:
    """Visits to sites in a curated category, one event per user, browser, day
    and category, naming up to MAX_HOSTS hosts.

    Seven rules share this extractor, one per category (uba/config/
    site_categories.json). Only a person's own navigations count - a link, a
    typed address, a bookmark, a form - never a frame, a redirect or a reload:
    an advert that embeds a file-sharing widget is not a visit to it.
    """
    by_cat = {}
    for r in rules:
        for cat, rid in _VISIT_RULES.items():
            if r["id"] == rid:
                by_cat[cat] = r
    if not by_cat:
        return []
    buckets = defaultdict(lambda: {"hosts": defaultdict(int), "refs": [], "first": None,
                                   "last": None})
    for table, row, gecko in _history_rows(ctx):
        if not _user_visit(row, gecko):
            continue
        cat = sc.categorize(row["url"])
        if cat not in by_cat:
            continue
        ts = normalize_ts(row["visit_time"])
        if not ts:
            continue
        b = buckets[(cat, row["sid"], row["user_name"], row["browser"] or "a browser", _day(ts))]
        b["hosts"][sc.normalize_host(row["url"])] += 1
        b["refs"].append((table, row["rowid"]))
        b["first"] = ts if b["first"] is None or ts < b["first"] else b["first"]
        b["last"] = ts if b["last"] is None or ts > b["last"] else b["last"]

    events = []
    for (cat, sid, user_name, browser, _d), b in buckets.items():
        rule = by_cat[cat]
        actor = _actor(ctx, sid, user_name, "the browser history database")
        hosts = sorted(b["hosts"], key=lambda h: -b["hosts"][h])
        shown = hosts[:MAX_HOSTS]
        visits = len(b["refs"])
        label = sc.category_label(cat)
        article = "an" if label[:1].lower() in "aeiou" else "a"
        text = "%s visited %s %s in %s: %s%s" % (
            actor[1] or "A user", article if len(hosts) == 1 else len(hosts),
            label + (" site" if len(hosts) == 1 else " sites"), browser,
            ", ".join(shown), (" and %d more" % (len(hosts) - len(shown))) if len(hosts) > len(shown) else "")
        if visits > len(hosts):
            text += " (%d visits)" % visits
        events.append(_mk(rule, ctx, b["first"], actor, text, _refs(b["refs"]),
                          ts_end=b["last"], count=visits, app_name=browser,
                          caveat=CAVEAT_SYNCED_PROFILE,
                          details={"category": cat, "hosts": dict((h, b["hosts"][h]) for h in hosts[:50]),
                                   "visits": visits}))
    return events


def browser_upload_inferred(ctx, rules) -> List[BehaviorEvent]:
    """A form submitted to a file-sharing or paste site - where uploads happen.

    Inference only (CAVEAT_UPLOAD_INFERRED). Sign-in, sign-up and account
    pages are left out: a form there is a login, the commonest form of all.
    Chromium only - Gecko records no form-submit transition.
    """
    rule = rules[0]
    if not _has(ctx, "browser_history"):
        return []
    events = []
    for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, url, visit_time, transition "
                          "FROM browser_history"):
        if _transition(row["transition"]) != "form_submit":
            continue
        cat = sc.categorize(row["url"])
        if cat not in ("file_sharing", "paste"):
            continue
        path = _path(row["url"])
        if any(w in path for w in _LOGIN_PATH):
            continue
        ts = normalize_ts(row["visit_time"])
        actor = _actor(ctx, row["sid"], row["user_name"], "the browser history database")
        host = sc.normalize_host(row["url"])
        events.append(_mk(
            rule, ctx, ts, actor,
            "%s submitted a form to the %s site %s - consistent with uploading content"
            % (actor[1] or "A user", sc.category_label(cat), host),
            [EvidenceRef(db=DB, table="browser_history", rowids=[row["rowid"]], count=1)],
            confidence=CONF_INFERENCE, caveat=CAVEAT_UPLOAD_INFERRED,
            app_name=row["browser"] or "",
            details={"host": host, "category": cat, "path": path[:200]}))
    return events


def browser_comm_apps(ctx, rules) -> List[BehaviorEvent]:
    """Chat and collaboration apps built on Electron (Discord, Slack, Teams,
    Signal, ...) whose profile Crow-Eye collected - each one a channel for
    messages and files outside the browser. Presence only; timeless.

    Only names are read. Local storage of these apps holds session tokens
    (a Discord token is enough to sign in as its owner): no key or value is
    read here or anywhere in UBA.
    """
    rule = rules[0]
    if not _has(ctx, "browser_metadata") and not _has(ctx, "browser_files"):
        return []
    found = {}
    for table in ("browser_metadata", "browser_files"):
        if not _has(ctx, table):
            continue
        for row in _rows(ctx, 'SELECT MIN(rowid) rid, browser, sid, user_name, COUNT(*) n '
                              'FROM "%s" WHERE vendor = \'electron\' GROUP BY browser, sid, '
                              'user_name' % table):
            app = sc.electron_app(row["browser"])
            if not app:
                continue
            key = (app, row["sid"], row["user_name"])
            slot = found.setdefault(key, {"refs": [], "files": 0})
            slot["refs"].append((table, row["rid"]))
            if table == "browser_files":
                slot["files"] += row["n"] or 0
    events = []
    for (app, sid, user_name), slot in found.items():
        actor = _actor(ctx, sid, user_name, "the collected application profile")
        events.append(_mk(rule, ctx, None, actor,
                          "%s has %s installed and signed in on this machine (its profile "
                          "data was collected)" % (actor[1] or "A user", app),
                          _refs(slot["refs"]), app_name=app, caveat=CAVEAT_TIMELESS_STATE,
                          details={"app": app, "files_collected": slot["files"]}))
    return events


def browser_crypto_wallet(ctx, rules) -> List[BehaviorEvent]:
    """A cryptocurrency wallet extension, and whether it holds stored data.

    The extension's storage is COUNTED, never read: a wallet vault is an
    encrypted seed phrase. Timeless unless the extension records its install
    time.
    """
    rule = rules[0]
    if not _has(ctx, "browser_extensions"):
        return []
    storage = defaultdict(int)
    if _has(ctx, "browser_extension_storage"):
        for row in _rows(ctx, "SELECT browser, sid, extension_id, COUNT(*) n "
                              "FROM browser_extension_storage GROUP BY 1, 2, 3"):
            storage[(row["browser"], row["sid"], str(row["extension_id"] or "").lower())] += row["n"]
    if _has(ctx, "browser_local_storage"):
        for row in _rows(ctx, "SELECT browser, sid, origin, COUNT(*) n FROM browser_local_storage "
                              "WHERE origin LIKE 'chrome-extension://%' GROUP BY 1, 2, 3"):
            ext = str(row["origin"] or "")[len("chrome-extension://"):].strip("/").lower()
            storage[(row["browser"], row["sid"], ext)] += row["n"]
    events = []
    for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, extension_id, name, "
                          "version, install_time FROM browser_extensions"):
        wallet = sc.wallet_extension(row["extension_id"] or "", row["name"] or "")
        if not wallet:
            continue
        held = storage.get((row["browser"], row["sid"], str(row["extension_id"] or "").lower()), 0)
        actor = _actor(ctx, row["sid"], row["user_name"], "the browser extension record")
        text = "%s has the %s cryptocurrency wallet installed in %s" % (
            actor[1] or "A user", wallet, row["browser"] or "a browser")
        text += (" - it holds stored data (%s), so a wallet has been set up or imported"
                 % _plural(held, "record")) if held else " - no stored data was found for it"
        events.append(_mk(rule, ctx, normalize_ts(row["install_time"]), actor, text,
                          [EvidenceRef(db=DB, table="browser_extensions",
                                       rowids=[row["rowid"]], count=1)],
                          app_name=row["browser"] or "",
                          caveat="" if row["install_time"] else CAVEAT_TIMELESS_STATE,
                          details={"wallet": wallet, "extension_id": row["extension_id"],
                                   "version": row["version"], "storage_records": held}))
    return events


def _session_stamp(name):
    """Chromium names session files Session_<WebKit microseconds>."""
    m = re.search(r"_(\d{16,18})$", str(name or ""))
    if not m:
        return None
    try:
        secs = int(m.group(1)) / 1e6 - 11644473600
        return (datetime(1970, 1, 1) + timedelta(seconds=secs)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError, OSError):
        return None


def browser_open_tabs(ctx, rules) -> List[BehaviorEvent]:
    """The tabs a browser would restore - what was open when it last closed.

    Chromium keeps a Session_<time> file per run; the newest is the last run,
    and each tab's last navigation in it is the page that tab showed. NOT the
    Tabs_<time> files: those are the recently-CLOSED tabs list, and counting
    them reported 30 tabs "open" where the session held one. Timeless: the
    file name dates when that session STARTED, not when it ended. form_text
    (what was typed into pages) is never read.
    """
    rule = rules[0]
    events = []
    if _has(ctx, "browser_sessions"):
        rows = _rows(ctx, "SELECT rowid, browser, sid, user_name, profile, session_file, "
                          "window_index, tab_index, url, title FROM browser_sessions "
                          "WHERE session_file LIKE 'Session_%' "
                          "ORDER BY rowid")
        newest = {}
        for row in rows:
            key = (row["browser"], row["sid"], row["user_name"], row["profile"])
            stamp = _session_stamp(row["session_file"]) or ""
            if key not in newest or stamp > newest[key][0]:
                newest[key] = (stamp, row["session_file"])
        tabs = defaultdict(dict)
        for row in rows:
            key = (row["browser"], row["sid"], row["user_name"], row["profile"])
            if row["session_file"] != newest[key][1]:
                continue
            tabs[key][(row["window_index"], row["tab_index"])] = row     # last navigation wins
        for key, by_tab in tabs.items():
            events.append(_tabs_event(rule, ctx, key, list(by_tab.values()), "browser_sessions",
                                      newest[key][0]))
    if _has(ctx, "browser_gecko_sessions"):
        by_key = defaultdict(dict)
        for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, profile, window_index, "
                              "tab_index, url, title FROM browser_gecko_sessions ORDER BY rowid"):
            by_key[(row["browser"], row["sid"], row["user_name"], row["profile"])][
                (row["window_index"], row["tab_index"])] = row
        for key, by_tab in by_key.items():
            events.append(_tabs_event(rule, ctx, key, list(by_tab.values()),
                                      "browser_gecko_sessions", None))
    return [e for e in events if e is not None]


def _tabs_event(rule, ctx, key, rows, table, started):
    browser, sid, user_name, profile = key
    rows = [r for r in rows if r["url"] and not str(r["url"]).startswith(("chrome://", "edge://",
                                                                           "about:", "brave://"))]
    if not rows:
        return None
    actor = _actor(ctx, sid, user_name, "the browser session file")
    hosts = []
    sensitive = {}
    for r in rows:
        url = str(r["url"])
        if url.lower().startswith("file:"):
            from urllib.parse import unquote
            h = "local file %s" % unquote(url.replace("\\", "/").rstrip("/").split("/")[-1])
        else:
            h = sc.normalize_host(url) or url[:60]
        if h and h not in hosts:
            hosts.append(h)
        cat = sc.categorize(r["url"])
        if cat in _SENSITIVE_CATEGORIES:
            sensitive[h] = cat
    text = "%s's %s had %s open when it last closed: %s%s" % (
        actor[1] or "A user", browser or "browser", _plural(len(rows), "tab"),
        ", ".join(hosts[:MAX_HOSTS]), " and more" if len(hosts) > MAX_HOSTS else "")
    if sensitive:
        text += " - including %s" % ", ".join("%s (%s)" % (h, sc.category_label(c))
                                              for h, c in list(sensitive.items())[:5])
    return _mk(rule, ctx, None, actor, text,
               [EvidenceRef(db=DB, table=table, rowids=[r["rowid"] for r in rows][:500],
                            count=len(rows))],
               severity=SEV_NOTABLE if sensitive else None, app_name=browser or "",
               caveat=CAVEAT_TIMELESS_STATE,
               details={"tabs": len(rows), "hosts": hosts[:50], "profile": profile,
                        "session_started": started, "sensitive": sensitive})


def browser_media_playback(ctx, rules) -> List[BehaviorEvent]:
    """Audio and video the browser played, per user, browser and day, with
    the watch time it recorded for each site."""
    rule = rules[0]
    if not _has(ctx, "browser_media_history"):
        return []
    buckets = defaultdict(lambda: {"sites": defaultdict(float), "refs": [], "first": None,
                                   "last": None})
    for row in _rows(ctx, "SELECT rowid, browser, sid, user_name, origin, url, "
                          "watch_time_seconds, last_updated FROM browser_media_history"):
        ts = normalize_ts(row["last_updated"])
        if not ts:
            continue
        b = buckets[(row["sid"], row["user_name"], row["browser"] or "a browser", _day(ts))]
        b["sites"][sc.normalize_host(row["origin"] or row["url"])] += float(row["watch_time_seconds"] or 0)
        b["refs"].append(("browser_media_history", row["rowid"]))
        b["first"] = ts if b["first"] is None or ts < b["first"] else b["first"]
        b["last"] = ts if b["last"] is None or ts > b["last"] else b["last"]
    events = []
    for (sid, user_name, browser, _d), b in buckets.items():
        actor = _actor(ctx, sid, user_name, "the browser media history")
        sites = sorted(b["sites"].items(), key=lambda kv: -kv[1])
        total = sum(v for _k, v in sites)
        text = "%s played media in %s on %s - %d min in total" % (
            actor[1] or "A user", browser, ", ".join("%s (%d min)" % (h, round(v / 60))
                                                     for h, v in sites[:MAX_HOSTS]),
            round(total / 60))
        events.append(_mk(rule, ctx, b["first"], actor, text, _refs(b["refs"]),
                          ts_end=b["last"], count=len(b["refs"]), app_name=browser,
                          details={"watch_seconds": round(total),
                                   "sites": dict((h, round(v)) for h, v in sites[:50])}))
    return events
