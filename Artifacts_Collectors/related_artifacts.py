"""
What the case already knows about one file or folder.

The File Browser shows a path; the investigator's next question is what the machine recorded about
it. Every parsed artifact that names a path is asked, read-only, by the path itself (or by the name
where the artifact keeps only a name), and each answer says what that artifact shows - executed,
present, opened, deleted - so a row is evidence with its meaning, not a bare hit.

A file is matched exactly (case-insensitive); a folder by prefix, and for a folder only the count
per artifact and a few rows are returned. Tables a case has not parsed, or an older case's tables
without the column, are skipped silently: absence of a database is not absence of evidence, and the
panel says which artifacts were not parsed.
"""
from __future__ import annotations

import glob
import os
import sqlite3
from typing import Dict, List, Optional

# (artifact, database, table, match column, how, columns shown, what a row shows, anatomy page)
# how: "path" = the full path; "name" = the file name only; "pathlike" = the path anywhere in the
# column (shim and LNK paths keep \??\ and device prefixes); "tail" = the column ends with \rel.
SOURCES = [
    ("Prefetch", "prefetch_data.db", "prefetch_data", "executable_name", "name",
     ["executable_name", "last_executed", "run_count", "filename"],
     "the program ran (Prefetch exists only for executed programs)", "prefetch_anatomy"),
    ("Amcache", "amcache.db", "InventoryApplicationFile", "lower_case_long_path", "path",
     ["lower_case_long_path", "sha1", "product_name", "link_date", "last_write_time"],
     "the file was present as an executable Windows inventoried, with its SHA-1", "amcache_anatomy"),
    ("ShimCache", "shimcache.db", "shimcache_entries", "path", "pathlike",
     ["path", "last_modified", "executed", "position"],
     "the file existed and Windows checked it for compatibility (not proof of execution)",
     "shimcache_anatomy"),
    ("BAM", "registry_data.db", "BAM", "process_path", "tail",
     ["user_name", "process_path", "last_execution"], "the program ran under that user", "registry_anatomy"),
    ("DAM", "registry_data.db", "DAM", "process_path", "tail",
     ["user_name", "process_path", "last_execution"], "the program ran (desktop activity moderator)",
     "registry_anatomy"),
    ("UserAssist", "registry_data.db", "UserAssist", "program_path", "pathlike",
     ["user_name", "program_path", "run_count", "last_execution"],
     "the user launched it from the shell", "registry_anatomy"),
    ("MUICache", "registry_data.db", "MUICache", "app_path", "path",
     ["user_name", "app_path", "app_name"], "the program ran for that user at some point", "registry_anatomy"),
    ("Compatibility Assistant", "registry_data.db", "CompatibilityAssistant", "program_path", "path",
     ["user_name", "program_path"], "the program ran and the Compatibility Assistant saw it", "registry_anatomy"),
    ("RecentApps", "registry_data.db", "RecentApps", "app_path", "path",
     ["user_name", "app_path", "launch_count", "last_accessed"], "the user launched it", "registry_anatomy"),
    ("OpenSaveMRU", "registry_data.db", "OpenSaveMRU", "file_path", "path",
     ["user_name", "file_path", "extension"], "the user opened or saved it in a common dialog", "registry_anatomy"),
    ("App Paths", "registry_data.db", "app_paths", "executable_path", "pathlike",
     ["app_name", "executable_path"], "an installed program registered this path", "registry_anatomy"),
    ("Services", "registry_data.db", "SystemServices", "image_path", "pathlike",
     ["name", "display_name", "image_path", "start_type"], "a service runs this file", "registry_anatomy"),
    ("Firewall rules", "registry_data.db", "FirewallRules", "application", "path",
     ["rule_name", "application", "action", "direction"], "a firewall rule names this program", "registry_anatomy"),
    ("LNK files", "LnkDB.db", "LNK_Files", "Local_Path", "path",
     ["Source_Name", "Local_Path", "Time_Access", "Time_Modification"],
     "a shortcut pointed at it: it was opened from the shell", "lnk_anatomy"),
    ("Automatic Jump Lists", "LnkDB.db", "Automatic_JumpLists", "Local_Path", "path",
     ["AppDesc", "Local_Path", "Time_Access"], "an application's recent list held it", "automatic_jumplist"),
    ("Custom Jump Lists", "LnkDB.db", "Custom_JumpLists", "Local_Path", "path",
     ["AppDesc", "Local_Path", "Time_Access"], "an application pinned or listed it", "custom_jumplist"),
    ("Recycle Bin", "recyclebin_analysis.db", "recycle_bin_entries", "original_path", "path",
     ["original_path", "deletion_time", "formatted_file_size", "user_sid"],
     "it was deleted to the Recycle Bin", "index"),
    ("MFT + USN", "mft_usn_correlated_analysis.db", "mft_usn_correlated", "reconstructed_path", "tail",
     ["reconstructed_path", "fn_filename", "si_created", "si_modified", "event_count"],
     "its NTFS record and the journal events about it", "mft_anatomy"),
    ("USN journal", "USN_journal.db", "journal_events", "filename", "name",
     ["timestamp", "filename", "reason", "frn"], "the file system recorded changes to a file of this name",
     "usn_anatomy"),
    ("SRUM", "srum_data.db", "srum_application_usage", "app_path", "pathlike",
     ["app_name", "user_name", "timestamp", "foreground_cycle_time"],
     "the program used CPU and I/O (SRUM, per hour)", "srum_anatomy"),
    ("Browser downloads", "browser_analysis.db", "browser_downloads", "target_path", "path",
     ["browser", "user_name", "target_path", "source_url", "start_time"], "a browser downloaded it", "browser-forensics"),
    ("Correlation results", "correlation_results.db", "matches", "matched_file_path", "path",
     ["matched_application", "matched_file_path"], "a Wing rule matched it", "index"),
]

FOLDER_SOURCES = [
    ("Shellbags", "registry_data.db", "Shellbags", "parent_path", "tail",
     ["user_name", "parent_path", "file_name", "last_written"], "the user browsed this folder in Explorer",
     "shell-items-shellbags-anatomy"),
]

_ROW_LIMIT = 25


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _databases(artifacts_dir: str, name: str) -> List[str]:
    """Every copy of one database in the case: the main one and any per-user ones."""
    if not artifacts_dir or not os.path.isdir(artifacts_dir):
        return []
    out = [os.path.join(artifacts_dir, name)] if os.path.isfile(os.path.join(artifacts_dir, name)) else []
    out += [p for p in glob.glob(os.path.join(artifacts_dir, "**", name), recursive=True) if p not in out]
    return out[:8]


def _query(db: str, table: str, column: str, how: str, full: str, rel: str, name: str, folder: bool,
           show: List[str]):
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3f"), uri=True, timeout=5)
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % table)]
        if not cols or column not in cols:
            return None
        shown = [c for c in show if c in cols] or cols[:5]
        if folder:
            # the folder's own separator is escaped too, or "\%" would read as a literal %
            where, args = ('"%s" LIKE ? ESCAPE \'\\\' COLLATE NOCASE' % column,
                           [_escape(full.rstrip("\\") + "\\") + "%"])
            if how in ("pathlike", "tail"):
                args = ["%" + _escape(rel.rstrip("\\") + "\\") + "%"]
            if how == "name":
                return None
        elif how == "path":
            where, args = '"%s" = ? COLLATE NOCASE' % column, [full]
        elif how == "name":
            where, args = '"%s" = ? COLLATE NOCASE' % column, [name]
        elif how == "tail":
            where, args = '"%s" LIKE ? ESCAPE \'\\\' COLLATE NOCASE' % column, ["%" + _escape("\\" + rel)]
        else:
            where, args = '"%s" LIKE ? ESCAPE \'\\\' COLLATE NOCASE' % column, ["%" + _escape(rel)]
        count = con.execute('SELECT COUNT(*) FROM "%s" WHERE %s' % (table, where), args).fetchone()[0]
        if not count:
            return {"count": 0, "rows": [], "columns": shown}
        rows = con.execute('SELECT %s FROM "%s" WHERE %s LIMIT %d' % (
            ", ".join('"%s"' % c for c in shown), table, where, _ROW_LIMIT), args).fetchall()
        return {"count": count, "rows": [dict(zip(shown, r)) for r in rows], "columns": shown}
    finally:
        con.close()


def related(artifacts_dir: str, rel: str, volume: str = "C", is_dir: bool = False,
            name_only_prefetch: bool = True) -> Dict[str, list]:
    """{'found': [...], 'nothing': [artifact], 'not_parsed': [artifact]} for one path.
    found items: {artifact, meaning, anatomy, count, rows, columns, database, table}."""
    rel = (rel or "").replace("/", "\\").strip("\\")
    volume = (volume or "C").rstrip(":\\").upper()
    full = "%s:\\%s" % (volume, rel) if rel else "%s:\\" % volume
    name = rel.rsplit("\\", 1)[-1]
    out = {"found": [], "nothing": [], "not_parsed": [], "path": full, "is_dir": is_dir}
    sources = SOURCES + (FOLDER_SOURCES if is_dir else [])
    for artifact, db_name, table, column, how, show, meaning, anatomy in sources:
        dbs = _databases(artifacts_dir, db_name)
        if not dbs:
            if artifact not in out["not_parsed"]:
                out["not_parsed"].append(artifact)
            continue
        total, rows, columns, answered = 0, [], show, False
        for db in dbs:
            try:
                r = _query(db, table, column, how, full, rel, name, is_dir, show)
            except sqlite3.Error:
                r = None
            if r is None:
                continue
            answered = True
            total += r["count"]
            rows += r["rows"]
            columns = r["columns"]
        if not answered:
            if artifact not in out["not_parsed"]:
                out["not_parsed"].append(artifact)
            continue
        if total:
            out["found"].append({"artifact": artifact, "meaning": meaning, "anatomy": anatomy, "count": total,
                                 "rows": rows[:_ROW_LIMIT], "columns": columns, "database": db_name,
                                 "table": table})
        else:
            out["nothing"].append(artifact)
    return out


def html(result: dict, max_rows: int = 6) -> str:
    """The panel's text: each artifact that names the path as a block of its own - what it is, how
    many rows, what it shows, its anatomy page and the rows themselves - then what is silent and what
    was not parsed, as small pills. QTextBrowser renders a subset of HTML 4: tables and bgcolor, no
    border-radius, so the blocks are one-cell tables."""
    from html import escape as e
    if not result:
        return ""
    found = result.get("found") or []
    out = []
    if not found:
        out.append("<p style='color:#E2E8F0'>No parsed artifact in this case names it.</p>")
    else:
        out.append("<p style='color:#94a3b8'>Named by %d artifact%s of this case:</p>" % (
            len(found), "" if len(found) == 1 else "s"))
    for f in found:
        head = ("<span style='color:#A5B4FC; font-size:14px'><b>%s</b></span>"
                "&nbsp;&nbsp;<span style='color:#0B1220; background-color:#818CF8'>&nbsp;%d row%s&nbsp;</span>"
                % (e(f["artifact"]), f["count"], "" if f["count"] == 1 else "s"))
        if f.get("anatomy"):
            head += "&nbsp;&nbsp;<a href='%s' style='color:#22D3EE'>how it works</a>" % e(f["anatomy"])
        cols = f["columns"]
        rows = "".join(
            "<tr>%s</tr>" % "".join("<td style='color:#CBD5E1; padding:2px 10px 2px 0'>%s</td>" % e(str(r.get(c, "")))
                                    for c in cols) for r in f["rows"][:max_rows])
        more = ("<p style='color:#94a3b8'>... and %d more row%s</p>" % (
            f["count"] - max_rows, "" if f["count"] - max_rows == 1 else "s")) if f["count"] > max_rows else ""
        out.append(
            "<table width='100%%' cellspacing='0' cellpadding='10' style='margin-bottom:10px' bgcolor='#111A2E'>"
            "<tr><td style='border-left:3px solid #818CF8'>%s"
            "<p style='color:#94a3b8; margin:4px 0 6px 0'>%s</p>"
            "<table cellspacing='0' cellpadding='0' style='font-family:Consolas,monospace; font-size:11px'>"
            "<tr>%s</tr>%s</table>%s</td></tr></table>" % (
                head, e(f["meaning"]),
                "".join("<td style='color:#64748B; padding:0 10px 4px 0'><b>%s</b></td>" % e(c) for c in cols),
                rows, more))

    def pills(label, names):
        if not names:
            return ""
        return ("<p style='color:#94a3b8; margin-top:8px'>%s<br>%s</p>" % (
            label, " ".join("<span style='color:#CBD5E1; background-color:#1E293B'>&nbsp;%s&nbsp;</span>" % e(n)
                            for n in names)))
    out.append(pills("Silent - parsed, and naming nothing here:", result.get("nothing") or []))
    out.append(pills("Not parsed in this case, so not asked:", result.get("not_parsed") or []))
    return "".join(out)
