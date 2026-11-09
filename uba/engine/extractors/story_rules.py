"""Evidence the Activity Story did not tell yet (2026-11-03).

Three rules read a table the parsers already fill:
  printer_added      registry printer_connections (per user)
  rdp_outbound       registry RDPClientMRU (per user): remote hosts this
                     account connected to, the other half of inbound RDP
  cloud_sync_client  a cloud sync app is on the computer (InstalledSoftware,
                     AmCache InventoryApplication), from cloud_sync_clients.json

Two rules read what the other rules found (they run after every extractor;
`"after_extractors": true` in behavior_rules.json):
  usb_file_copy      files written on, or picked in a Save/Open dialog on, a
                     drive letter Windows recorded as USB storage
  files_collected    many files copied or written into one folder in a day,
                     with an archive written there, or gathered by copy

Every sentence is built only from the rows behind it, and each event carries
those rows (directly, or the member events' rows) as its evidence.
"""

import json
import logging
import os
import re
from collections import defaultdict
from typing import Dict, List

from uba.engine.models import BehaviorEvent, EvidenceRef, CONF_ARTIFACT_ONLY
from uba.engine.extractors.artifacts import (
    _mk, _rows, _hive_actor, _time_phrase, _usb_volumes, CAVEAT_MRU_KEY_TIME,
    CAVEAT_PRESENCE)
from uba.utils.timeparse import normalize_ts

logger = logging.getLogger(__name__)

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "config", "cloud_sync_clients.json")
_DRIVE = re.compile(r"^\s*([A-Za-z]):[\\/]")
ARCHIVE_TYPES = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".cab", ".iso"}
COLLECT_MIN_FILES = 20        # files into one folder in one day, with an archive
COLLECT_MIN_COPIED = 10       # files copied (inferred) into one folder in one day


def sync_clients() -> List[dict]:
    """[{name, match: [lower-case substrings], folders: [folder names]}]."""
    try:
        with open(_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f).get("clients", [])
    except (OSError, ValueError) as e:
        logger.warning("UBA: cloud sync client list not read: %s", e)
        return []


# --------------------------------------------------------------- table rules
def printer_added(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    if not ctx.pool.has_table("registry", "printer_connections"):
        return []
    events = []
    for rowid, user, connection, server, printer, last_written, basis in _rows(
            ctx, "registry",
            "SELECT rowid, user_name, connection, server, printer, last_written, "
            "time_basis FROM printer_connections"):
        name = printer or connection or "a printer"
        ts = normalize_ts(last_written)
        when, caveat = _time_phrase(ts, basis)
        actor = _hive_actor(ctx, "the user's printer list", owner=user or None)
        who = actor[1] or user or "A user"
        where = " on the print server {}".format(server) if server else ""
        text = "{} added the printer '{}'{}{}".format(
            who, name, where, " " + when if when else "")
        events.append(_mk(
            rule, ctx, ts, actor, text,
            [EvidenceRef(db="registry", table="printer_connections",
                         rowids=[rowid], count=1)],
            caveat=caveat,
            details={"printer": name, "server": server or "",
                     "connection": connection or "", "user": user or "",
                     "time_basis": basis or ""}))
    return events


def rdp_outbound(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    if not ctx.pool.has_table("registry", "RDPClientMRU"):
        return []
    events = []
    for rowid, user, entry_type, server, hint, last_written, basis in _rows(
            ctx, "registry",
            "SELECT rowid, user_name, entry_type, server, username_hint, "
            "last_written, time_basis FROM RDPClientMRU"):
        if not server:
            continue
        ts = normalize_ts(last_written)
        when, caveat = _time_phrase(ts, basis)
        if ts and "mru" in str(entry_type or "").lower():
            caveat = CAVEAT_MRU_KEY_TIME
        actor = _hive_actor(ctx, "the user's Remote Desktop history", owner=user or None)
        who = actor[1] or user or "A user"
        text = "{} connected to the computer {} over Remote Desktop".format(who, server)
        if hint:
            text += ", signing in as {}".format(hint)
        if when:
            text += " ({} last)".format(when)
        events.append(_mk(
            rule, ctx, ts, actor, text,
            [EvidenceRef(db="registry", table="RDPClientMRU",
                         rowids=[rowid], count=1)],
            caveat=caveat,
            details={"server": server, "username_hint": hint or "",
                     "entry_type": entry_type or "", "user": user or "",
                     "time_basis": basis or ""}))
    return events


def _client_of(name, clients):
    low = str(name or "").lower()
    for c in clients:
        if any(m in low for m in c.get("match", [])):
            return c
    return None


def cloud_sync_client(ctx, rules) -> List[BehaviorEvent]:
    """One event per sync app found, with every install record behind it
    (InstalledSoftware and AmCache often both list it, under several versions)."""
    from uba.engine.extractors.artifacts import _norm_date
    rule = rules[0]
    clients = sync_clients()
    found = {}
    sources = []
    if ctx.pool.has_table("registry", "InstalledSoftware"):
        sources.append(("registry", "InstalledSoftware",
                        "SELECT rowid, display_name, display_version, install_date "
                        "FROM InstalledSoftware"))
    if ctx.pool.has_table("amcache", "InventoryApplication"):
        cols = ", ".join(c if ctx.pool.has_column("amcache", "InventoryApplication", c) else "NULL"
                         for c in ("name", "version", "install_date"))
        sources.append(("amcache", "InventoryApplication",
                        "SELECT rowid, %s FROM InventoryApplication" % cols))
    for db, table, sql in sources:
        for rowid, name, version, installed in _rows(ctx, db, sql):
            client = _client_of(name, clients)
            if client is None:
                continue
            f = found.setdefault(client["name"], {"versions": [], "dates": [], "refs": {}})
            if version and str(version) not in f["versions"]:
                f["versions"].append(str(version))
            ts = _norm_date(installed)
            if ts:
                f["dates"].append(ts)
            f["refs"].setdefault((db, table), []).append(rowid)
    events = []
    for name, f in found.items():
        first = min(f["dates"]) if f["dates"] else None
        text = "The cloud sync app {} is installed on this computer".format(name)
        if f["versions"]:
            text += " (version{} {})".format("s" if len(f["versions"]) > 1 else "",
                                             ", ".join(f["versions"][:4]))
        if first:
            text += "; the earliest install date recorded is {}".format(first[:10])
        n = sum(len(v) for v in f["refs"].values())
        events.append(_mk(
            rule, ctx, first, ("Application", name, "installed program record"), text,
            [EvidenceRef(db=db, table=table, rowids=ids[:50], count=len(ids))
             for (db, table), ids in f["refs"].items()],
            caveat=CAVEAT_PRESENCE, app_name=name, count=n,
            details={"client": name, "versions": f["versions"], "records": n}))
    return events


# --------------------------------------------- rules over the found activity
_WRITE_RULES = ("file_created", "file_edited", "file_renamed", "file_copy_inferred")


def _found(store, rule_ids):
    marks = ",".join("?" for _ in rule_ids)
    return store.conn.execute(
        "SELECT event_id, rule_id, ts_start, ts_end, actor_type, actor_name, "
        "actor_basis, actor_sid, aggregate_count, details_json, evidence_json "
        "FROM events WHERE rule_id IN (%s) AND ts_start IS NOT NULL" % marks,
        list(rule_ids)).fetchall()


def _evidence_of(rows) -> List[EvidenceRef]:
    merged: Dict[tuple, EvidenceRef] = {}
    for r in rows:
        for e in json.loads(r[10] or "[]"):
            key = (e.get("db"), e.get("table"), e.get("role", "primary"))
            ref = merged.setdefault(key, EvidenceRef(db=key[0], table=key[1], role=key[2]))
            for rid in e.get("rowids") or []:
                if rid not in ref.rowids and len(ref.rowids) < 200:
                    ref.rowids.append(rid)
            ref.count += int(e.get("count") or len(e.get("rowids") or []))
    return list(merged.values())


def _person(row):
    return (row[7] or "", row[5] or "")


def usb_file_copy(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    store = getattr(ctx, "store", None)
    if store is None:
        return []
    _guids, letters = _usb_volumes(ctx)
    letters.discard("C")
    if not letters:
        return []
    groups = defaultdict(lambda: {"written": 0, "picked": [], "rows": [], "samples": []})
    for row in _found(store, _WRITE_RULES + ("file_dialog_history",)):
        d = json.loads(row[9] or "{}")
        place = d.get("folder") if row[1] != "file_dialog_history" else d.get("path")
        m = _DRIVE.match(str(place or ""))
        if not m or m.group(1).upper() not in letters:
            continue
        key = (_person(row), row[2][:10], m.group(1).upper())
        g = groups[key]
        g["rows"].append(row)
        if row[1] == "file_dialog_history":
            g["picked"].append(d.get("file") or "")
        else:
            g["written"] += int(d.get("files") or row[8] or 1)
            g["samples"].extend((d.get("sample_files") or [])[:3])
    events = []
    for ((sid, name), day, letter), g in sorted(groups.items(), key=lambda kv: kv[0][1:]):
        first = min(r[2] for r in g["rows"])
        last = max((r[3] or r[2]) for r in g["rows"])
        who = name or "Someone"
        parts = []
        if g["written"]:
            parts.append("{} file{} written to the USB drive {}:".format(
                g["written"], "" if g["written"] == 1 else "s", letter))
        if g["picked"]:
            parts.append("{} picked on it in a Save/Open dialog ({})".format(
                len(g["picked"]), ", ".join(p for p in g["picked"][:3] if p)))
        text = "{} used the USB drive {}: on {}: {}".format(who, letter, day, "; ".join(parts))
        lead = g["rows"][0]
        events.append(BehaviorEvent(
            rule_id=rule["id"], behavior_class=rule["behavior_class"],
            activity=rule["activity"], ts_start=first, ts_end=last,
            actor_type=lead[4] or "", actor_name=name, actor_basis=lead[6] or "",
            actor_sid=sid, description=text, severity=rule["severity"],
            confidence=CONF_ARTIFACT_ONLY,
            session_context=ctx.session_context(first),
            aggregate_count=g["written"] + len(g["picked"]),
            caveat=("A file picked in a Save/Open dialog may have been opened "
                    "rather than saved; the dialog keeps no direction."
                    if g["picked"] else ""),
            details={"drive": letter, "day": day, "files_written": g["written"],
                     "picked": g["picked"][:20], "sample_files": g["samples"][:10],
                     "from_events": [r[0] for r in g["rows"]][:50]},
            evidence=_evidence_of(g["rows"])))
    return events


def files_collected(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    store = getattr(ctx, "store", None)
    if store is None:
        return []
    groups = defaultdict(lambda: {"files": 0, "copied": 0, "archives": 0, "rows": [],
                                  "types": defaultdict(int)})
    for row in _found(store, _WRITE_RULES):
        d = json.loads(row[9] or "{}")
        folder = str(d.get("folder") or "")
        if not folder or row[1] == "file_renamed":
            continue
        key = (_person(row), row[2][:10], folder)
        g = groups[key]
        g["rows"].append(row)
        n = int(d.get("files") or row[8] or 1)
        g["files"] += n
        if row[1] == "file_copy_inferred":
            g["copied"] += n
        for t, v in (d.get("file_types") or {}).items():
            if isinstance(v, (int, float)):
                g["types"][str(t).lower()] += int(v)
                if str(t).lower() in ARCHIVE_TYPES:
                    g["archives"] += int(v)
    events = []
    for ((sid, name), day, folder), g in sorted(groups.items(), key=lambda kv: kv[0][1:]):
        if not ((g["files"] >= COLLECT_MIN_FILES and g["archives"])
                or g["copied"] >= COLLECT_MIN_COPIED):
            continue
        first = min(r[2] for r in g["rows"])
        last = max((r[3] or r[2]) for r in g["rows"])
        who = name or "Someone"
        text = "{} gathered {} files in {} on {}".format(who, g["files"], folder, day)
        if g["copied"]:
            text += " ({} of them copied there)".format(g["copied"])
        if g["archives"]:
            text += ", and {} archive file{} {} written there".format(
                g["archives"], "" if g["archives"] == 1 else "s",
                "was" if g["archives"] == 1 else "were")
        lead = g["rows"][0]
        events.append(BehaviorEvent(
            rule_id=rule["id"], behavior_class=rule["behavior_class"],
            activity=rule["activity"], ts_start=first, ts_end=last,
            actor_type=lead[4] or "", actor_name=name, actor_basis=lead[6] or "",
            actor_sid=sid, description=text, severity=rule["severity"],
            confidence=CONF_ARTIFACT_ONLY,
            session_context=ctx.session_context(first),
            aggregate_count=g["files"],
            details={"folder": folder, "day": day, "files": g["files"],
                     "copied": g["copied"], "archives": g["archives"],
                     "file_types": dict(g["types"]),
                     "from_events": [r[0] for r in g["rows"]][:50]},
            evidence=_evidence_of(g["rows"])))
    return events


# ------------------------------------------------------------- input layer
CAVEAT_INPUT = (
    "Windows counts the seconds a program received keyboard or mouse input, "
    "per account, about once an hour (SRUM). Input sent by software - "
    "automation, remote control - is counted the same way (tested: a script's "
    "SendInput typing was recorded as keyboard input), so this shows that input "
    "reached the program, not that a hand was on the keyboard.")


def input_activity(ctx, rules) -> List[BehaviorEvent]:
    """One activity per account per SRUM write: which programs received
    keyboard or mouse input in that stretch, and for how long."""
    from uba.engine.who_drove import InputWindows, input_words, typed
    rule = rules[0]
    windows = InputWindows.load(ctx.pool)
    groups = defaultdict(list)
    for w in windows.rows:
        if typed(w) and w["sid"]:
            groups[(w["sid"], w["end"])].append(w)
    events = []
    for (sid, end), rows in sorted(groups.items(), key=lambda kv: kv[0][1]):
        # One line per program: SRUM can hold several rows for one program in
        # one stretch; their seconds add up.
        merged = {}
        for w in rows:
            m = merged.setdefault(w["app"], dict(w, rowids=[]))
            if m is not w and m["rowids"]:
                for k in ("keyboard", "mouse", "input", "focus"):
                    m[k] += w[k]
                m["start"] = min(m["start"], w["start"])
            m["rowids"].append(w["rowid"])
        ws = sorted(merged.values(), key=lambda w: -(w["keyboard"] + w["mouse"] + w["input"]))
        start = min(w["start"] for w in ws)
        actor = ctx.resolver.from_sid(sid, "the input record (SRUM App Timeline)")
        who = actor[1] or ws[0]["user"] or "An account"
        apps = "; ".join("{} {}".format(w["app_label"] or w["app"], input_words(w)) for w in ws[:5])
        more = len(ws) - 5
        text = "{} used the keyboard or mouse between {} and {}: {}{}".format(
            who, start.strftime("%H:%M"), end.strftime("%H:%M"), apps,
            "; and {} more program{}".format(more, "" if more == 1 else "s") if more > 0 else "")
        ts = start.strftime("%Y-%m-%d %H:%M:%S")
        ev = _mk(rule, ctx, ts, actor, text,
                 [EvidenceRef(db="srum", table="srum_app_timeline",
                              rowids=[i for w in ws for i in w["rowids"]][:50],
                              count=sum(len(w["rowids"]) for w in ws))],
                 caveat=CAVEAT_INPUT, count=len(ws), ts_end=end.strftime("%Y-%m-%d %H:%M:%S"),
                 details={"programs": [{"app": w["app_label"] or w["app"],
                                        "keyboard_s": w["keyboard"], "mouse_s": w["mouse"],
                                        "focus_s": w["focus"]} for w in ws[:20]],
                          "keyboard_s": sum(w["keyboard"] for w in ws),
                          "mouse_s": sum(w["mouse"] for w in ws)})
        events.append(ev)
    return events
