"""
Artifact-primary extractors: behaviors proven by on-disk artifacts
(registry, prefetch, LNK/jump lists, SRUM, amcache...), optionally
corroborated by Security 4688 within the rule's time delta.

Data-quality rules encoded here (verified against a real case):
- UserAssist rows may have an EMPTY last_execution -> kept as timeless
  "run-count evidence" (never dropped, never given a fake time).
- BAM contains pseudo-rows ('Version', 'SequenceNumber') -> filtered by
  requiring a path-shaped process value.
- ShimCache proves PRESENCE, not execution -> its own confidence tier and
  "was present" wording.
- SRUM SIDs may carry a 'PySID:' prefix -> normalized before attribution.
- InstalledSoftware install_date is often 'YYYYMMDD' -> parsed explicitly
  (generic numeric parsing would misread it as an epoch).
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from uba.engine import description
from uba.engine.models import (BehaviorEvent, EvidenceRef, CONF_ARTIFACT_ONLY,
                               CONF_CORROBORATED, CONF_PRESENCE,
                               SEV_SUSPICIOUS)
from uba.utils import sid_utils
from uba.utils.timeparse import normalize_ts

logger = logging.getLogger(__name__)

_YYYYMMDD_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

# Forensic caveats — the evidentiary limit of an artifact that can be created
# by an application as well as by the person. Shown to the reviewer so intent
# is never overclaimed.
CAVEAT_SHELLBAGS = (
    "ShellBags are created both when a person browses folders in File Explorer "
    "AND when an application opens a file/save dialog — this confirms the folder "
    "was accessed in this user's session, not necessarily deliberate browsing.")
CAVEAT_FILE_OPEN = (
    "Shortcuts, jump lists and recent-file lists are also written by "
    "applications opening files on the user's behalf — this shows the file was "
    "accessed in this user's session, not necessarily opened by hand.")
CAVEAT_PRESENCE = (
    "Presence evidence only: this shows the program existed on the computer. "
    "It does not prove the program was run, or by whom.")


def _norm_date(value) -> Optional[str]:
    """normalize_ts plus explicit YYYYMMDD handling (install dates)."""
    if value is None:
        return None
    text = str(value).strip()
    match = _YYYYMMDD_RE.match(text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)),
                            int(match.group(3))).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return normalize_ts(value)


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


def _rows(ctx, logical_db, sql, params=()):
    conn = ctx.pool.get(logical_db)
    if conn is None:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as e:
        logger.warning("UBA: query failed on %s: %s", logical_db, e)
        return []


# --------------------------------------------------------------------- #
def userassist_launch(ctx, rules) -> List[BehaviorEvent]:
    """UserAssist (GUI launches, per-user hive) merged with BAM; each timed
    launch is checked against Security 4688 within the rule's delta."""
    rule = rules[0]
    delta = rule.get("log_join", {}).get("delta_seconds", 5)
    events = []
    seen_timed = set()   # (exe_lower, ts) to dedupe BAM rows matching UserAssist

    if ctx.pool.has_table("registry", "UserAssist"):
        for rowid, path, run_count, last_exec, sid in _rows(
                ctx, "registry",
                "SELECT rowid, program_path, run_count, last_execution, user_sid "
                "FROM UserAssist"):
            if not path or str(path).startswith("UEME_"):
                continue
            app = description.app_display_name(path)
            actor = ctx.resolver.from_user_hive("the UserAssist record", sid)
            ts = normalize_ts(last_exec)
            evidence = [EvidenceRef(db="registry", table="UserAssist",
                                    rowids=[rowid], count=1)]
            details = {"program_path": path, "run_count": run_count}
            if ts:
                seen_timed.add((app.lower(), ts))
                hits = ctx.find_4688(path, ts, delta)
                confidence = CONF_ARTIFACT_ONLY
                if hits:
                    confidence = CONF_CORROBORATED
                    evidence.append(EvidenceRef(db="logs", table="SecurityLogs",
                                                role="corroborating",
                                                rowids=hits, count=len(hits)))
                text = "{} opened the program '{}'".format(actor[1] or "Someone", app)
                if run_count:
                    text += " (opened {} time{} in total)".format(
                        run_count, "s" if run_count != 1 else "")
                events.append(_mk(rule, ctx, ts, actor, text, evidence,
                                  confidence=confidence, details=details, app_name=app))
            elif run_count:
                text = ("{} has opened the program '{}' {} time{} "
                        "(Windows did not record the exact times)").format(
                            actor[1] or "Someone", app, run_count,
                            "s" if run_count != 1 else "")
                events.append(_mk(rule, ctx, None, actor, text, evidence,
                                  details=details, count=int(run_count) or 1, app_name=app))

    if ctx.pool.has_table("registry", "BAM"):
        for rowid, app_name, proc_path, sid, last_exec in _rows(
                ctx, "registry",
                "SELECT rowid, app_name, process_path, sid, last_execution FROM BAM"):
            path = proc_path or app_name or ""
            # Filter pseudo-rows: real BAM values are path-shaped
            if "\\" not in str(path) and not str(path).lower().endswith(".exe"):
                continue
            ts = normalize_ts(last_exec)
            if not ts:
                continue
            app = description.app_display_name(path)
            if (app.lower(), ts) in seen_timed:
                continue    # same launch already reported from UserAssist
            actor = ctx.resolver.from_sid(sid, "the background-activity (BAM) record")
            if actor[0] == "System":
                continue    # system processes belong to the application view
            evidence = [EvidenceRef(db="registry", table="BAM",
                                    rowids=[rowid], count=1)]
            hits = ctx.find_4688(path, ts, delta)
            confidence = CONF_ARTIFACT_ONLY
            if hits:
                confidence = CONF_CORROBORATED
                evidence.append(EvidenceRef(db="logs", table="SecurityLogs",
                                            role="corroborating",
                                            rowids=hits, count=len(hits)))
            events.append(_mk(
                rule, ctx, ts, actor,
                "{} used the program '{}'".format(actor[1] or "Someone", app),
                evidence, confidence=confidence, details={"program_path": path},
                app_name=app))
    return events


def prefetch_execution(ctx, rules) -> List[BehaviorEvent]:
    """Program execution from Prefetch. `run_times` holds up to 8 real run
    timestamps — each becomes its own execution event (4688-corroborated
    within the delta), giving the full run history rather than only the last
    run. A timeless summary carries the total run count."""
    rule = rules[0]
    delta = rule.get("log_join", {}).get("delta_seconds", 5)
    actor = ("Application", None, "prefetch trace of the program itself")
    events = []
    for rowid, exe, run_count, last_exec, run_times in _rows(
            ctx, "prefetch",
            "SELECT rowid, executable_name, run_count, last_executed, run_times "
            "FROM prefetch_data"):
        app = description.app_display_name(exe)
        act = ("Application", app, actor[2])

        run_ts = []
        if run_times:
            try:
                parsed = json.loads(run_times)
                if isinstance(parsed, list):
                    run_ts = [normalize_ts(t) for t in parsed]
                    run_ts = [t for t in run_ts if t]
            except (ValueError, TypeError):
                run_ts = []
        if not run_ts:
            single = normalize_ts(last_exec)
            if single:
                run_ts = [single]

        # One event per recorded run (deduped).
        for ts in sorted(set(run_ts), reverse=True):
            evidence = [EvidenceRef(db="prefetch", table="prefetch_data",
                                    rowids=[rowid], count=1)]
            confidence = CONF_ARTIFACT_ONLY
            hits = ctx.find_4688(exe, ts, delta)
            if hits:
                confidence = CONF_CORROBORATED
                evidence.append(EvidenceRef(db="logs", table="SecurityLogs",
                                            role="corroborating",
                                            rowids=hits, count=len(hits)))
            events.append(_mk(
                rule, ctx, ts, act,
                "The program '{}' ran on the computer".format(app),
                evidence, confidence=confidence,
                details={"executable": exe, "run_count": run_count}, app_name=app))

        # Timeless total-runs summary when Prefetch counted more runs than it
        # kept timestamps for (it stores at most 8).
        if run_count and int(run_count or 0) > len(run_ts):
            events.append(_mk(
                rule, ctx, None, act,
                "The program '{}' has run {} times in total on this computer "
                "(Windows keeps only the {} most recent run times)".format(
                    app, run_count, len(run_ts)),
                [EvidenceRef(db="prefetch", table="prefetch_data",
                             rowids=[rowid], count=1)],
                confidence=CONF_ARTIFACT_ONLY, count=int(run_count),
                details={"executable": exe, "run_count": run_count}, app_name=app))
    return events


def shimcache_presence(ctx, rules) -> List[BehaviorEvent]:
    """Presence-only evidence, aggregated per folder area, timeless.
    ShimCache last_modified is the FILE's modification time, not an
    execution time — treating it as one would be forensically wrong."""
    rule = rules[0]
    buckets = defaultdict(list)
    for rowid, path in _rows(ctx, "shimcache",
                             "SELECT rowid, path FROM shimcache_entries"):
        # Packaged (Store/UWP) apps are stored tab-delimited, e.g.
        # "...\tMicrosoft.Todos\t8wekyb3d8bbwe\t" — not a filesystem path.
        if path and "\t" in path:
            buckets["Windows Store apps"].append((rowid, path))
        else:
            buckets[description.folder_label(path)].append((rowid, path))
    events = []
    for label, items in buckets.items():
        rowids = [r for r, _ in items]
        if label == "Windows Store apps":
            samples = []
            for _, p in items[:8]:
                parts = [x for x in str(p).split("\t") if x and not x[0].isdigit()]
                if parts:
                    samples.append(parts[0])
        else:
            samples = [description.app_display_name(p) for _, p in items[:8]]
        events.append(_mk(
            rule, ctx, None, ("", "", ""),
            "{} program{} in {} {} present on this computer and may have "
            "been run (presence evidence only — no dates)".format(
                len(items), "s" if len(items) != 1 else "", label,
                "were" if len(items) != 1 else "was"),
            [EvidenceRef(db="shimcache", table="shimcache_entries",
                         rowids=rowids[:50], count=len(rowids))],
            confidence=CONF_PRESENCE, count=len(items), caveat=CAVEAT_PRESENCE,
            details={"folder": label, "sample_programs": samples}))
    return events


def app_install(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, name, version, publisher, install_date in _rows(
            ctx, "registry",
            "SELECT rowid, display_name, display_version, publisher, install_date "
            "FROM InstalledSoftware"):
        if not name:
            continue
        ts = _norm_date(install_date)
        text = "The program '{}' was installed".format(name)
        if publisher:
            text += " (publisher: {})".format(publisher)
        events.append(_mk(
            rule, ctx, ts, ("", "", ""), text,
            [EvidenceRef(db="registry", table="InstalledSoftware",
                         rowids=[rowid], count=1)],
            details={"name": name, "version": version, "publisher": publisher},
            app_name=description.app_display_name(name)))

    seen = {e.details.get("name", "").lower() for e in events}
    for rowid, name, publisher, install_date, root_dir in _rows(
            ctx, "amcache",
            "SELECT rowid, name, publisher, install_date, root_dir_path "
            "FROM InventoryApplication"):
        if not name or str(name).lower() in seen:
            continue
        ts = _norm_date(install_date)
        text = "The application '{}' was installed".format(name)
        if publisher:
            text += " (publisher: {})".format(publisher)
        events.append(_mk(
            rule, ctx, ts, ("", "", ""), text,
            [EvidenceRef(db="amcache", table="InventoryApplication",
                         rowids=[rowid], count=1)],
            details={"name": name, "publisher": publisher, "path": root_dir},
            app_name=description.app_display_name(name)))
    return events


# --------------------------------------------------------------------- #
def network_share_access(ctx, rules) -> List[BehaviorEvent]:
    """Folders browsed on a network share (ShellBags rows carrying a
    network share / server name) — reveals access to remote/shared storage."""
    rule = rules[0]
    if not ctx.pool.has_table("registry", "Shellbags"):
        return []
    events = []
    for rowid, name, network_share, server, share, accessed in _rows(
            ctx, "registry",
            "SELECT rowid, file_name, network_share, server_name, share_name, "
            "accessed_date FROM Shellbags "
            "WHERE (network_share IS NOT NULL AND network_share != '') "
            "OR (server_name IS NOT NULL AND server_name != '')"):
        location = network_share or (
            "\\\\{}\\{}".format(server, share) if server else (name or "a network share"))
        ts = normalize_ts(accessed)
        actor = ctx.resolver.from_user_hive("the folder-view (ShellBags) record")
        events.append(_mk(
            rule, ctx, ts, actor,
            "{} browsed the network share '{}'".format(
                actor[1] or "A user of this profile", location),
            [EvidenceRef(db="registry", table="Shellbags", rowids=[rowid], count=1)],
            caveat=CAVEAT_SHELLBAGS, details={"network_location": location}))
    return events


def shellbags_browsing(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, name, parent, accessed, modified in _rows(
            ctx, "registry",
            "SELECT rowid, file_name, parent_path, accessed_date, modified_date "
            "FROM Shellbags"):
        folder = "{}\\{}".format(parent, name) if parent else (name or "")
        ts = normalize_ts(accessed) or normalize_ts(modified)
        actor = ctx.resolver.from_user_hive("the folder-view (ShellBags) record")
        who = actor[1] or "this user profile"
        text = "The folder '{}' was accessed in {}'s Windows session".format(
            folder or "(unknown)", who)
        events.append(_mk(
            rule, ctx, ts, actor, text,
            [EvidenceRef(db="registry", table="Shellbags", rowids=[rowid], count=1)],
            caveat=CAVEAT_SHELLBAGS,
            details={"folder": folder, "area": description.folder_label(folder)}))
    return events


def file_open_artifacts(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []

    for rowid, source_name, local_path, t_access, t_mod, vol_type, net_share in _rows(
            ctx, "lnk",
            "SELECT rowid, Source_Name, Local_Path, Time_Access, Time_Modification, "
            "Volume_Type, Network_Share_Name FROM LNK_Files"):
        target = local_path or source_name or ""
        ts = normalize_ts(t_access) or normalize_ts(t_mod)
        actor = ctx.resolver.from_user_hive("the Windows shortcut record")
        doc = description.app_display_name(target) if target else "(unknown file)"
        who = actor[1] or "this user profile"
        # Flag files that came from removable media or a network location.
        origin = ""
        if net_share:
            origin = " — stored on a network location ({})".format(net_share)
        elif vol_type and str(vol_type).strip().lower() in ("removable", "cd-rom", "remote"):
            origin = " — stored on removable media ({})".format(vol_type)
        events.append(_mk(
            rule, ctx, ts, actor,
            "'{}' was opened in {}'s session (shortcut, from {}){}".format(
                doc, who, description.folder_label(target), origin),
            [EvidenceRef(db="lnk", table="LNK_Files", rowids=[rowid], count=1)],
            caveat=CAVEAT_FILE_OPEN, details={"path": target}))

    for rowid, app_desc, local_path, t_access in _rows(
            ctx, "lnk",
            "SELECT rowid, AppDesc, Local_Path, Time_Access FROM Automatic_JumpLists"):
        if not local_path:
            continue
        ts = normalize_ts(t_access)
        actor = ctx.resolver.from_user_hive("the jump-list record")
        doc = description.app_display_name(local_path)
        via = " using {}".format(app_desc) if app_desc else ""
        who = actor[1] or "this user profile"
        events.append(_mk(
            rule, ctx, ts, actor,
            "'{}' was opened in {}'s session{}".format(doc, who, via),
            [EvidenceRef(db="lnk", table="Automatic_JumpLists",
                         rowids=[rowid], count=1)],
            caveat=CAVEAT_FILE_OPEN,
            details={"path": local_path, "application": app_desc}))

    # Custom jump lists = per-application pinned/recent items the user opened.
    if ctx.pool.has_table("lnk", "Custom_JumpLists"):
        for rowid, app_name, app_desc, local_path, t_access in _rows(
                ctx, "lnk",
                "SELECT rowid, Source_Name, AppDesc, Local_Path, Time_Access "
                "FROM Custom_JumpLists"):
            app = app_desc or app_name
            if not app and not local_path:
                continue
            ts = normalize_ts(t_access)
            actor = ctx.resolver.from_user_hive("the application jump-list record")
            what = description.app_display_name(local_path) if local_path else (app or "an item")
            events.append(_mk(
                rule, ctx, ts, actor,
                "{} used {}'s recent/pinned items ('{}')".format(
                    actor[1] or "A user of this profile", app or "an application", what),
                [EvidenceRef(db="lnk", table="Custom_JumpLists",
                             rowids=[rowid], count=1)],
                caveat=CAVEAT_FILE_OPEN,
                details={"application": app, "path": local_path}))

    for table, name_col, date_col, what in (
            ("OpenSaveMRU", "file_name", "access_date", "opened or saved"),
            ("LastSaveMRU", "folder_name", "access_date", "saved a file into")):
        if not ctx.pool.has_table("registry", table):
            continue
        for rowid, name, date in _rows(
                ctx, "registry",
                "SELECT rowid, {}, {} FROM {}".format(name_col, date_col, table)):
            if not name:
                continue
            ts = normalize_ts(date)
            actor = ctx.resolver.from_user_hive("the open/save-dialog record")
            events.append(_mk(
                rule, ctx, ts, actor,
                "{} {} '{}' via an Open/Save window".format(
                    actor[1] or "A user of this profile", what, name),
                [EvidenceRef(db="registry", table=table, rowids=[rowid], count=1)],
                caveat=CAVEAT_FILE_OPEN, details={"name": name}))

    if ctx.pool.has_table("registry", "RecentDocs"):
        # The parser decodes the document name into `data`; `name` is just the
        # MRU index ("0"/"1"/"MRUListEx"). Read `data`, skip the MRUListEx
        # ordering row and any raw-binary values (Python-repr byte strings).
        items = []
        for rowid, mru_name, data in _rows(
                ctx, "registry", "SELECT rowid, name, data FROM RecentDocs"):
            if not data or mru_name == "MRUListEx":
                continue
            doc = str(data).strip()
            if not doc or doc.startswith("b'") or doc.startswith('b"'):
                continue                 # undecoded binary value
            items.append((rowid, doc))
        if items:
            actor = ctx.resolver.from_user_hive("the recent-documents list")
            docs, _seen = [], set()      # dedupe (same file appears per-extension subkey)
            for _r, d in items:
                if d.lower() not in _seen:
                    _seen.add(d.lower())
                    docs.append(d)
            preview = ", ".join(docs[:6])
            events.append(_mk(
                rule, ctx, None, actor,
                "{} recently opened {} document{}: {}{} (Windows keeps the "
                "list but not the exact times)".format(
                    actor[1] or "A user of this profile", len(docs),
                    "s" if len(docs) != 1 else "", preview,
                    ", …" if len(docs) > 6 else ""),
                [EvidenceRef(db="registry", table="RecentDocs",
                             rowids=[r for r, _ in items], count=len(docs))],
                count=len(docs), caveat=CAVEAT_FILE_OPEN,
                details={"documents": docs[:20]}))
    return events


# --------------------------------------------------------------------- #
def usb_devices(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, device_id, desc_text, friendly, last_connected in _rows(
            ctx, "registry",
            "SELECT rowid, device_id, description, friendly_name, last_connected "
            "FROM USBDevices"):
        label = friendly or desc_text or device_id or "a USB device"
        ts = normalize_ts(last_connected)
        events.append(_mk(
            rule, ctx, ts, ("", "", ""),
            "The USB device '{}' was plugged into this computer".format(label),
            [EvidenceRef(db="registry", table="USBDevices", rowids=[rowid], count=1)],
            details={"device": label, "device_id": device_id}))
    if ctx.pool.has_table("registry", "USBStorageDevices"):
        for rowid, friendly, serial, first_c, last_c, last_r in _rows(
                ctx, "registry",
                "SELECT rowid, friendly_name, serial_number, first_connected, "
                "last_connected, last_removed FROM USBStorageDevices"):
            label = friendly or "a USB storage drive"
            ts = normalize_ts(last_c) or normalize_ts(first_c)
            events.append(_mk(
                rule, ctx, ts, ("", "", ""),
                "The USB storage drive '{}' was plugged into this computer "
                "(files could be copied to or from it)".format(label),
                [EvidenceRef(db="registry", table="USBStorageDevices",
                             rowids=[rowid], count=1)],
                details={"device": label, "serial": serial,
                         "removed": normalize_ts(last_r)}))
    return events


def browser_history(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, browser, url, title, visit_count, last_visit in _rows(
            ctx, "registry",
            "SELECT rowid, browser, url, title, visit_count, last_visit "
            "FROM BrowserHistory"):
        if not url:
            continue
        ts = normalize_ts(last_visit)
        actor = ctx.resolver.from_user_hive("the browser-history registry record")
        text = "{} visited '{}'".format(actor[1] or "A user of this profile",
                                        title or url)
        if browser:
            text += " in {}".format(browser)
        events.append(_mk(
            rule, ctx, ts, actor, text,
            [EvidenceRef(db="registry", table="BrowserHistory",
                         rowids=[rowid], count=1)],
            details={"url": url, "title": title, "visits": visit_count}))
    return events


def local_search(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    specs = [
        ("WordWheelQuery", "search_term", "access_date",
         "searched Windows for '{}'"),
        ("RunMRU", "command", "access_date",
         "ran '{}' from the Start-Run box"),
    ]
    for table, value_col, date_col, template in specs:
        if not ctx.pool.has_table("registry", table):
            continue
        for rowid, value, date in _rows(
                ctx, "registry",
                "SELECT rowid, {}, {} FROM {}".format(value_col, date_col, table)):
            if not value:
                continue
            ts = normalize_ts(date)
            actor = ctx.resolver.from_user_hive("the {} record".format(table))
            events.append(_mk(
                rule, ctx, ts, actor,
                "{} {}".format(actor[1] or "A user of this profile",
                               template.format(value)),
                [EvidenceRef(db="registry", table=table, rowids=[rowid], count=1)],
                details={"value": value}))
    if ctx.pool.has_table("registry", "TypedPaths"):
        items = [(rowid, data) for rowid, data in _rows(
            ctx, "registry", "SELECT rowid, data FROM TypedPaths") if data]
        if items:
            actor = ctx.resolver.from_user_hive("the typed-paths record")
            events.append(_mk(
                rule, ctx, None, actor,
                "{} typed {} location{} directly into the Explorer address "
                "bar".format(actor[1] or "A user of this profile", len(items),
                             "s" if len(items) != 1 else ""),
                [EvidenceRef(db="registry", table="TypedPaths",
                             rowids=[r for r, _ in items], count=len(items))],
                count=len(items), details={"paths": [d for _, d in items[:10]]}))
    return events


# --------------------------------------------------------------------- #
def srum_foreground(ctx, rules) -> List[BehaviorEvent]:
    """Actively-used programs (SRUM foreground time), per user+app+day."""
    rule = rules[0]
    buckets = defaultdict(lambda: {"rowids": [], "face": 0, "first_ts": None})
    for rowid, ts, app_name, app_path, sid, user_name, face_time in _rows(
            ctx, "srum",
            "SELECT rowid, timestamp, app_name, app_path, user_sid, user_name, "
            "face_time FROM srum_application_usage "
            "WHERE COALESCE(foreground_cycle_time, 0) > 0"):
        norm_sid = sid_utils.normalize_sid(sid)
        if sid_utils.classify_sid(norm_sid) != "human_candidate":
            continue
        ts = normalize_ts(ts)
        app = description.app_display_name(app_path or app_name)
        key = (norm_sid, app, (ts or "")[:10])
        bucket = buckets[key]
        bucket["rowids"].append(rowid)
        try:
            bucket["face"] += float(face_time or 0)
        except (TypeError, ValueError):
            pass
        if bucket["first_ts"] is None or (ts and ts < bucket["first_ts"]):
            bucket["first_ts"] = ts
    events = []
    for (norm_sid, app, day), bucket in buckets.items():
        actor = ctx.resolver.from_sid(norm_sid, "the system resource-usage (SRUM) record")
        if actor[0] != "User":
            continue
        text = "{} actively used '{}'".format(actor[1], app)
        events.append(_mk(
            rule, ctx, bucket["first_ts"], actor, text,
            [EvidenceRef(db="srum", table="srum_application_usage",
                         rowids=bucket["rowids"][:50],
                         count=len(bucket["rowids"]))],
            count=len(bucket["rowids"]), details={"application": app, "day": day},
            app_name=app))
    return events


def srum_network(ctx, rules) -> List[BehaviorEvent]:
    """Per app+day data transfer volumes (SRUM network usage)."""
    rule = rules[0]
    buckets = defaultdict(lambda: {"rowids": [], "sent": 0, "recv": 0,
                                   "first_ts": None, "sid": ""})
    for rowid, ts, app_name, app_path, sid, sent, received in _rows(
            ctx, "srum",
            "SELECT rowid, timestamp, app_name, app_path, user_sid, "
            "bytes_sent, bytes_received FROM srum_network_data_usage"):
        ts = normalize_ts(ts)
        app = description.app_display_name(app_path or app_name)
        key = (app, (ts or "")[:10])
        bucket = buckets[key]
        bucket["rowids"].append(rowid)
        bucket["sid"] = bucket["sid"] or sid_utils.normalize_sid(sid)
        try:
            bucket["sent"] += float(sent or 0)
            bucket["recv"] += float(received or 0)
        except (TypeError, ValueError):
            pass
        if bucket["first_ts"] is None or (ts and ts < bucket["first_ts"]):
            bucket["first_ts"] = ts
    events = []
    for (app, day), bucket in buckets.items():
        total = bucket["sent"] + bucket["recv"]
        if total <= 0:
            continue
        text = ("The program '{}' transferred {} over the network "
                "(sent {}, received {})".format(
                    app, description.humanize_bytes(total),
                    description.humanize_bytes(bucket["sent"]),
                    description.humanize_bytes(bucket["recv"])))
        events.append(_mk(
            rule, ctx, bucket["first_ts"],
            ("Application", app, "the SRUM network-usage record names the program"),
            text,
            [EvidenceRef(db="srum", table="srum_network_data_usage",
                         rowids=bucket["rowids"][:50],
                         count=len(bucket["rowids"]))],
            count=len(bucket["rowids"]),
            details={"application": app, "day": day,
                     "bytes_sent": bucket["sent"], "bytes_received": bucket["recv"]},
            app_name=app))
    return events


def network_profiles(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, name, connection_date, gateway_mac in _rows(
            ctx, "registry",
            "SELECT rowid, network_name, connection_date, gateway_mac "
            "FROM Network_list"):
        if not name:
            continue
        ts = normalize_ts(connection_date)
        events.append(_mk(
            rule, ctx, ts, ("System", "Windows", "recorded in the network list"),
            "The computer connected to the network '{}'".format(name),
            [EvidenceRef(db="registry", table="Network_list",
                         rowids=[rowid], count=1)],
            details={"network": name, "gateway_mac": gateway_mac}))
    return events


def driver_binaries(ctx, rules) -> List[BehaviorEvent]:
    """Unsigned drivers are reported individually (suspicious); signed ones
    are aggregated into a single routine summary."""
    rule = rules[0]
    events = []
    signed_rowids = []
    for rowid, name, signed, last_write in _rows(
            ctx, "amcache",
            "SELECT rowid, driver_name, driver_signed, driver_last_write_time "
            "FROM InventoryDriverBinary"):
        is_signed = str(signed).strip() in ("1", "True", "true", "yes")
        if is_signed:
            signed_rowids.append(rowid)
            continue
        ts = normalize_ts(last_write)
        events.append(_mk(
            rule, ctx, ts, ("", "", ""),
            "An UNSIGNED hardware driver '{}' is present — unsigned drivers "
            "can be used to bypass security and deserve review".format(
                description.app_display_name(name)),
            [EvidenceRef(db="amcache", table="InventoryDriverBinary",
                         rowids=[rowid], count=1)],
            severity=SEV_SUSPICIOUS, details={"driver": name}))
    if signed_rowids:
        events.append(_mk(
            rule, ctx, None, ("System", "Windows", "driver inventory (amcache)"),
            "{} digitally-signed hardware drivers are installed (normal)".format(
                len(signed_rowids)),
            [EvidenceRef(db="amcache", table="InventoryDriverBinary",
                         rowids=signed_rowids[:50], count=len(signed_rowids))],
            count=len(signed_rowids)))
    return events


# A command/image path in one of these areas is user-writable — a common
# malware persistence tell when something auto-starts from there.
def _is_user_writable_path(path) -> bool:
    if not path:
        return False
    low = str(path).lower()
    return ("appdata" in low or "\\temp\\" in low or "/temp/" in low
            or "programdata" in low or "\\downloads" in low
            or ("\\users\\" in low and "\\appdata" not in low
                and "system32" not in low))


def autostart_programs(ctx, rules) -> List[BehaviorEvent]:
    """Persistence: programs set to auto-run at startup (Run/RunOnce/Startup).
    Auto-start from a user-writable location is escalated for review."""
    rule = rules[0]
    events = []
    for rowid, location, program_name, command in _rows(
            ctx, "registry",
            "SELECT rowid, location, program_name, command FROM AutoStartPrograms"):
        name = program_name or description.app_display_name(command)
        suspicious = _is_user_writable_path(command)
        text = ("The program '{}' is set to run automatically at startup "
                "(via {})".format(name, location or "an autostart key"))
        if suspicious:
            text += " — it runs from a user-writable location, which is a common persistence trick"
        events.append(_mk(
            rule, ctx, None, ("", "", ""), text,
            [EvidenceRef(db="registry", table="AutoStartPrograms",
                         rowids=[rowid], count=1)],
            severity=SEV_SUSPICIOUS if suspicious else None,
            details={"program": name, "location": location, "command": command},
            app_name=description.app_display_name(name)))
    return events


# Windows service start types: 0 Boot, 1 System, 2 Automatic all run without a
# user; 3 Manual, 4 Disabled do not auto-start.
_AUTO_START_TYPES = {"0", "1", "2", 0, 1, 2}


def autostart_service(ctx, rules) -> List[BehaviorEvent]:
    """Persistence via services: services set to start automatically. Auto-start
    services whose executable lives outside the Windows/Program-Files system
    dirs are flagged individually; the rest are summarized."""
    rule = rules[0]
    if not ctx.pool.has_table("registry", "SystemServices"):
        return []
    events = []
    normal_rowids = []
    for rowid, svc, disp, start_type, image_path in _rows(
            ctx, "registry",
            "SELECT rowid, service_name, display_name, start_type, image_path "
            "FROM SystemServices"):
        if str(start_type).strip() not in ("0", "1", "2"):
            continue                      # not an auto-start service
        name = disp or svc or "a service"
        if _is_user_writable_path(image_path):
            events.append(_mk(
                rule, ctx, None, ("", "", ""),
                "The auto-start service '{}' runs from a user-writable location "
                "({}) — an unusual place for a service and a persistence red flag"
                .format(name, image_path),
                [EvidenceRef(db="registry", table="SystemServices",
                             rowids=[rowid], count=1)],
                severity=SEV_SUSPICIOUS,
                details={"service": name, "image_path": image_path}))
        else:
            normal_rowids.append(rowid)
    if normal_rowids:
        events.append(_mk(
            rule, ctx, None, ("System", "Windows", "the services registry"),
            "{} services are set to start automatically with Windows (normal "
            "system/software services)".format(len(normal_rowids)),
            [EvidenceRef(db="registry", table="SystemServices",
                         rowids=normal_rowids[:50], count=len(normal_rowids))],
            count=len(normal_rowids), severity=None))
    return events


# MUICache stores shell property keys, e.g. the executable path with a
# '.FriendlyAppName' / '.ApplicationCompany' suffix. Strip that suffix back
# to the real binary path so it can be deduped and folder-bucketed.
_MUICACHE_SUFFIX_RE = re.compile(
    r"\.(FriendlyAppName|ApplicationCompany|FriendlyTypeName)$", re.I)


def _clean_muicache_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return _MUICACHE_SUFFIX_RE.sub("", str(path))


def amcache_file_presence(ctx, rules) -> List[BehaviorEvent]:
    """Programs that were PRESENT on / available to run from this computer,
    from the standard execution-inventory artifacts AmCache
    InventoryApplicationFile + InventoryApplicationShortcut and the shell
    MUICache. Timeless (their timestamps are compile dates / caches, not
    activity times), folder-aggregated, presence confidence, wording
    "was present / available to run" — never "executed".

    Completes the default-Windows execution-evidence set alongside
    ShimCache/UserAssist/BAM/Prefetch: none of these six may be omitted.
    """
    rule = rules[0]
    # bucket -> {table -> [rowids]}, plus sample program names per bucket
    buckets = defaultdict(lambda: {"refs": defaultdict(list), "names": [],
                                   "count": 0})

    def add(path, rowid, table, name):
        if not path:
            return
        label = description.folder_label(path)
        b = buckets[label]
        b["refs"][table].append(rowid)
        b["count"] += 1
        if len(b["names"]) < 8:
            disp = description.app_display_name(name or path)
            if disp not in b["names"]:
                b["names"].append(disp)

    if ctx.pool.has_table("amcache", "InventoryApplicationFile"):
        for rowid, name, path in _rows(
                ctx, "amcache",
                "SELECT rowid, name, lower_case_long_path "
                "FROM InventoryApplicationFile"):
            add(path or name, rowid, "InventoryApplicationFile", name)

    if ctx.pool.has_table("amcache", "InventoryApplicationShortcut"):
        for rowid, target in _rows(
                ctx, "amcache",
                "SELECT rowid, ShortcutTargetPath FROM InventoryApplicationShortcut"):
            add(target, rowid, "InventoryApplicationShortcut", target)

    if ctx.pool.has_table("registry", "MUICache"):
        seen = set()
        for rowid, app_path, app_name in _rows(
                ctx, "registry",
                "SELECT rowid, app_path, app_name FROM MUICache"):
            clean = _clean_muicache_path(app_path)
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            add(clean, rowid, "MUICache", app_name or clean)

    events = []
    for label, b in buckets.items():
        # System-area programs attribute to System; user areas stay EMPTY
        # (presence is not an action a specific person took).
        actor = ("System", "Windows", "the programs live in the Windows / "
                 "installed-programs system area") \
            if "Windows system area" in label or "installed-programs" in label \
            else ("", "", "")
        evidence = [EvidenceRef(db=("amcache" if t.startswith("Inventory") else "registry"),
                                table=t, rowids=ids[:50], count=len(ids))
                    for t, ids in b["refs"].items()]
        events.append(_mk(
            rule, ctx, None, actor,
            "{} program{} in {} {} present on this computer and available to "
            "run (presence evidence only — no run times)".format(
                b["count"], "s" if b["count"] != 1 else "", label,
                "were" if b["count"] != 1 else "was"),
            evidence, confidence=CONF_PRESENCE, count=b["count"],
            caveat=CAVEAT_PRESENCE,
            details={"folder": label, "sample_programs": b["names"]}))
    return events


def srum_network_sessions(ctx, rules) -> List[BehaviorEvent]:
    """Machine network-online sessions from SRUM (srum_network_connectivity).
    connected_time is already a human string like '1m 29s'. System-level
    network presence — shows the computer was connected to a network."""
    rule = rules[0]
    events = []
    for rowid, ts, app_name, user_name, connected_time, connect_start in _rows(
            ctx, "srum",
            "SELECT rowid, timestamp, app_name, user_name, connected_time, "
            "connect_start_time FROM srum_network_connectivity"):
        start = normalize_ts(connect_start) or normalize_ts(ts)
        dur = str(connected_time).strip() if connected_time else ""
        text = "The computer was connected to a network"
        if dur:
            text += " for {}".format(dur)
        events.append(_mk(
            rule, ctx, start,
            ("System", "Windows", "recorded by the system resource monitor (SRUM)"),
            text,
            [EvidenceRef(db="srum", table="srum_network_connectivity",
                         rowids=[rowid], count=1)],
            details={"connected_time": dur}))
    return events


def device_present(ctx, rules) -> List[BehaviorEvent]:
    """Hardware/peripherals seen by this computer (AmCache device inventory),
    aggregated by device class. Timeless, EMPTY actor (device inventory is
    not an action by a person). Highlights removable/communication classes
    (usb, bluetooth, net) which matter for data movement."""
    rule = rules[0]
    # Only classes that indicate data movement / peripherals a reviewer cares
    # about — internal hardware (processor, system, hidclass, volume…) is noise.
    _INTERESTING = {"usb", "bluetooth", "net", "wpd", "diskdrive", "media",
                    "image", "printqueue", "modem"}
    buckets = defaultdict(list)
    if ctx.pool.has_table("amcache", "InventoryDevicePnp"):
        for rowid, cls, model in _rows(
                ctx, "amcache",
                "SELECT rowid, class, model FROM InventoryDevicePnp"):
            cls_l = str(cls or "other").lower()
            if cls_l not in _INTERESTING:
                continue
            buckets[(cls_l, "InventoryDevicePnp")].append((rowid, model))
    events = []
    for (cls, table), items in buckets.items():
        rowids = [r for r, _ in items]
        names = [m for _, m in items if m][:6]
        severity = "notable" if cls in ("usb", "bluetooth") else rule["severity"]
        friendly = {"usb": "USB", "net": "network", "wpd": "portable/media",
                    "diskdrive": "disk-drive", "printqueue": "printer"}.get(cls, cls)
        n = len(items)
        plural = n != 1
        events.append(_mk(
            rule, ctx, None, ("", "", ""),
            "{} {} device{} {} connected to or installed on this computer".format(
                n, friendly, "s" if plural else "", "were" if plural else "was"),
            [EvidenceRef(db="amcache", table=table, rowids=rowids[:50],
                         count=len(rowids))],
            severity=severity, count=len(items),
            details={"class": cls, "sample_models": names}))
    return events
