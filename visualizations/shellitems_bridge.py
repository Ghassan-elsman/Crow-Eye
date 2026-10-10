"""QWebChannel bridge for the User Activity dashboard: Shell Items & Registry.

(Formerly "Shell Items - user navigation & MRU". The registry tables that
record what a user RAN or SET - UserAssist, BAM, DAM, FeatureUsage, the
Program Compatibility Assistant store, FileExts and the ProgramsCache - sat
beside the shell-item tables with no dashboard at all; they are sources here
now, and every one of those tables' Charts buttons opens this dashboard.)

Reads the case's registry_data.db and unifies all seven Windows shell-item
artifacts into one activity stream for the react-shellitems app. Same shape as
the SRUM / MFT-USN / LNK / Prefetch bridges.

Colour language = artifact SOURCE (which shell-item key the row came from):
  shellbags / recentdocs / opensave / lastvisited / typedpaths / runmru / search

Each of the seven source tables has a DIFFERENT column set, so a per-source
mapper normalises every row to one common record (target, path, item type,
drive/volume, location category, MRU position, best-available timestamp). The
data is small, so every slot fetches all rows once and aggregates in Python.

Timing is coarser than Prefetch's: most shell-item rows carry only a registry
key write time + an MRU position (the only true sequence). Shellbags is the
rich exception - it embeds per-folder FAT created/modified/accessed times, a
last-written value, item type, MFT record and size - so its detail view shows
those FAT times against the registry write time.
"""

import os
import json

from visualizations.timeseries import (axis_range as _axis_range,
                                       densify as _densify,
                                       densify_series as _densify_series)

from visualizations.insights import (insight as _insight,
                                       plain as _plain,
                                       subject as _subject)
from visualizations.raw_record import raw_record as _raw
import time
import sqlite3
import logging
from typing import List, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSlot

logger = logging.getLogger(__name__)

SHELLITEMS_DB = "registry_data.db"

# Display order = colour order in the react app's SOURCES table.
SOURCES = ("shellbags", "recentdocs", "opensave", "lastvisited", "typedpaths", "runmru",
           "search", "dialogapps")
SOURCE_TABLES = {
    "shellbags": "Shellbags",
    "recentdocs": "RecentDocs",
    "opensave": "OpenSaveMRU",
    "lastvisited": "LastSaveMRU",
    "typedpaths": "TypedPaths",
    "runmru": "RunMRU",
    "search": "WordWheelQuery",
    # ComDlg32\CIDSizeMRU: programs that opened a common Open/Save dialog - an
    # application name and a window size, no path. The MRU family member the
    # anatomy page documents and the dashboard used to leave out.
    "dialogapps": "cid_size_mru",
    # The rest of what the registry parse records about where a user went and
    # what they opened. Several are empty on a typical machine and full on
    # others - so every one is read, and an empty one says why.
    "taskband": "system_configuration",     # pinned taskbar shell items
    "mountpoints": "MountPoints2",           # volumes / shares the user mounted
    "office": "OfficeDocuments",             # Office File / Place MRU
    "typedurls": "BrowserHistory",           # Internet Explorer TypedURLs
    "rdp": "RDPClientMRU",                   # Remote Desktop servers typed
    "recentapps": "RecentApps",              # Windows 10 RecentApps
    "appmru": "ApplicationArtifacts",        # 7-Zip, WinSCP, PuTTY, FileZilla...
    "regedit": "regedit_lastkey",            # Registry Editor's last key
}
SOURCES = SOURCES + ("taskband", "mountpoints", "office", "typedurls", "rdp",
                     "recentapps", "appmru", "regedit")
# What the user RAN, with a time per entry: on the strip like the MRUs.
SOURCE_TABLES.update({
    "userassist": "UserAssist",              # Explorer\UserAssist: run + focus counts
    "bam": "BAM",                            # Background Activity Moderator: last run
    "dam": "DAM",                            # Desktop Activity Moderator: last run
    # CapabilityAccessManager\ConsentStore: when each app last used the
    # camera, microphone or location - its own start and stop time per row.
    "apppermissions": "app_permissions",
})
SOURCES = SOURCES + ("userassist", "bam", "dam", "apppermissions")
# Undated by nature - listed in All items and counted, never on the strip.
SOURCE_TABLES.update({
    "muicache": "MUICache",                  # programs launched: name + company
    "shellfolders": "user_shell_folders",    # where each known folder points
    "shellext": "shell_open_command",        # Explorer shell registrations...
})
SOURCES = SOURCES + ("muicache", "shellfolders", "shellext")
# Ran or set, but with only the KEY's write time - one upper bound shared by
# every entry under it. Plotting 268 FeatureUsage rows on that one day would
# be a false spike, so these are listed undated; the key time is in the detail.
SOURCE_TABLES.update({
    "featureusage": "FeatureUsage",          # Explorer\FeatureUsage: taskbar counts
    "compat": "CompatibilityAssistant",      # PCA Store: programs the user ran
    "fileexts": "file_exts",                 # Explorer\FileExts: what opens each type
    "programscache": "programs_cache",       # StartPage2\ProgramsCache
})
SOURCES = SOURCES + ("featureusage", "compat", "fileexts", "programscache")
# ...read from all three tables that share the registration shape.
SOURCE_MULTI = {
    "shellext": ("shell_open_command", "shell_icon_overlay_identifiers",
                 "shell_service_object_delay_load"),
}
SHELLEXT_KIND = {
    "shell_open_command": "shell open command",
    "shell_icon_overlay_identifiers": "icon overlay handler",
    "shell_service_object_delay_load": "delay-load shell service object",
}
# Sources that are not a whole table. Taskband lives in system_configuration,
# one decoded row among many.
SOURCE_QUERIES = {
    "taskband": "SELECT * FROM system_configuration "
                "WHERE key_path LIKE '%Taskband' AND setting = 'Favorites'",
}
# Which configs/empty_table_hints.json entry explains an empty source, where
# that is not simply its table's name.
HINT_KEYS = {"taskband": "Taskband"}


def _split_taskband(decoded: str):
    """("5 pinned: a.lnk, b.lnk; 6 by app id (no shortcut)") -> ([names], 6).

    The format is registry_binary_parser.decode_taskband's own. Anything else
    returns ([], 0) and the caller keeps the row whole rather than losing it.
    """
    import re as _re
    pins, apps = [], 0
    for part in (decoded or "").split("; "):
        m = _re.match(r"\s*\d+ pinned: (.*)$", part)
        if m:
            pins = [p.strip() for p in m.group(1).split(", ") if p.strip()]
            continue
        m = _re.match(r"\s*(\d+) by app id", part)
        if m:
            apps = int(m.group(1))
    return pins, apps


def _office_filetime(raw: str) -> str:
    """The [T<16 hex>] FILETIME in an Office MRU value, as a forensic timestamp."""
    import re as _re
    m = _re.search(r"\[T([0-9A-Fa-f]{16})\]", raw or "")
    if not m:
        return ""
    try:
        ft = int(m.group(1), 16)
        if ft <= 0:
            return ""
        try:
            from utils.time_utils import filetime_to_datetime, format_forensic_timestamp
            return format_forensic_timestamp(filetime_to_datetime(ft))
        except Exception:
            import datetime as _dt
            t = _dt.datetime(1601, 1, 1) + _dt.timedelta(microseconds=ft // 10)
            return t.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        return ""
LOCATIONS = ("localfixed", "removable", "network", "userprofile", "other")


def _loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


def _pick(r: dict, *keys):
    """First non-empty value among alternative column names (schema drift).

    The registry parser has renamed columns across versions - older case DBs
    store the MRU value in `data` (newer: `row_data`) and the key write time in
    `timestamp` (newer: `key_last_write`) - so every read tries both spellings.
    """
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return ""


def _base(path: str) -> str:
    p = str(path or "").replace("/", "\\").rstrip("\\")
    return p[p.rfind("\\") + 1:] if "\\" in p else p


def _dirof(path: str) -> str:
    p = str(path or "").replace("/", "\\").rstrip("\\")
    return p[:p.rfind("\\")] if "\\" in p else ""


def _daypart(t) -> str:
    s = str(t or "").strip()
    return s[:10] if len(s) >= 10 and s[:4].isdigit() and s[:4] >= "1900" else ""


def _hourpart(t) -> int:
    s = str(t or "").strip()
    return int(s[11:13]) if len(s) >= 13 and s[11:13].isdigit() else 0


def _drive_of(path: str) -> str:
    p = str(path or "").strip()
    if p[:2] == "\\\\":
        return ""                       # UNC -> handled as network, no letter
    return p[:2].upper() if len(p) >= 2 and p[1] == ":" else ""


def _clean_str(v) -> str:
    """A displayable value, or "" for a raw/partially-decoded blob.

    Some MRU rows keep a REG_BINARY blob the parser could not fully decode; it
    surfaces as bytes or a python bytes-repr with control characters. Those are
    not names a human should see, so they collapse to "".
    """
    if isinstance(v, (bytes, bytearray)):
        return ""
    s = str(v or "")
    if s[:2] in ("b'", 'b"'):
        return ""
    if any(ord(c) < 32 for c in s):
        return ""
    return s.strip()


def _account(v) -> str:
    """'S-1-5-21-...-1001 (HOST\\ann)' -> 'HOST\\ann'; a bare SID or name as it is."""
    s = _clean_str(v)
    if s.endswith(")") and " (" in s:
        return s[s.rindex(" (") + 2:-1]
    return s


def _upper_bound_note(r: dict) -> str:
    t = _clean_str(r.get("last_written"))
    return ("key written %s (an upper bound for every entry in it)" % t) if t else "no time recorded"


def _looks_pathy(s: str) -> bool:
    """True for a string that reads like a real filesystem/UNC path."""
    s = s or ""
    return bool(s) and ("\\" in s) and (s[1:3] == ":\\" or s[:2] == "\\\\" or s.count("\\") >= 2)


# Filename-illegal characters; a "place" segment carrying one is a decode fragment.
_ILLEGAL_PLACE_CHARS = set('<>:"/|?*')


try:
    from visualizations.async_bridge import AsyncBridge
except ImportError:                                  # run from its own folder
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from visualizations.async_bridge import AsyncBridge


# AsyncBridge (a QObject): the page calls its slots through callAsync, off
# the GUI thread, so the window keeps painting while a query runs.
class ShellItemsBridge(AsyncBridge):
    def __init__(self, case_directory: str, parent=None, focus_source: str = ""):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        self._cache = None
        # The source whose table's Charts button opened the dashboard; the
        # app pre-selects it in the source filter.
        self.focus_source = focus_source if focus_source in SOURCES else ""
        # table -> error text. A source whose query failed used to come back
        # as an empty list, indistinguishable on screen from "no rows".
        self._errors = {}
        logger.info(f"ShellItemsBridge initialized with case dir: {case_directory}")

    def _db_path(self) -> Optional[str]:
        p = os.path.join(self.case_dir, SHELLITEMS_DB)
        return p if os.path.exists(p) else None

    def _query(self, sql: str, params: tuple = ()) -> List[Dict]:
        p = self._db_path()
        if not p:
            return []
        for attempt in range(3):
            try:
                conn = sqlite3.connect(p)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                return rows
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 2:
                    time.sleep(0.1); continue
                logger.error(f"shellitems query error: {e}")
                self._errors[sql] = str(e)
                return []
            except Exception as e:
                logger.error(f"shellitems query failure: {e}")
                self._errors[sql] = str(e)
                return []
        return []

    def _table_exists(self, name: str) -> bool:
        return len(self._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))) > 0

    # ---- classify a target's location -------------------------------------
    def _classify(self, path: str, drive: str, network: bool) -> str:
        up = (path or "").upper()
        if network or up[:2] == "\\\\":
            return "network"
        d = (drive or _drive_of(path)).upper()
        if d and d[0] != "C":
            return "removable"          # any non-system-drive letter is another volume
        if "\\USERS\\" in up or "%USERPROFILE%" in up or "\\APPDATA\\" in up:
            return "userprofile"
        if d == "C:" or up.startswith("C:"):
            return "localfixed"
        return "other"

    # ---- unify one row of a given source ----------------------------------
    def _record(self, source: str, r: dict) -> Optional[dict]:
        g = r.get
        if str(g("name") or "").strip() == "MRUListEx":
            return None                 # ordering metadata, not a shell item
        rec = {
            "source": source, "target": "", "path": "", "itemType": "other",
            "volume": "", "volType": "", "location": "other",
            "mruPosition": g("mru_position") if g("mru_position") is not None else g("mru_number"),
            "when": "", "user": g("user_name") or "",
            "created": "", "modified": "", "accessed": "", "lastWritten": "",
            "keyLastWrite": _pick(r, "key_last_write", "last_written", "timestamp"),
            "mftRecord": "", "size": "", "registryPath": "", "parentPath": "", "note": "",
        }
        network = False

        if source == "shellbags":
            name = g("file_name") or g("short_name") or ""
            parent = g("registry_path") or g("parent_path") or ""
            sit = (g("shell_item_type") or "").lower()
            srv, shr = g("server_name") or "", g("share_name") or ""
            network = bool(g("network_share") or srv or shr) or "network" in sit
            unc = g("network_share") if str(g("network_share") or "").startswith("\\\\") else \
                (("\\\\" + srv + ("\\" + shr if shr else "")) if srv else "")
            rec["target"] = name or unc or "(root)"
            rec["path"] = (g("parent_path") + "\\" + name) if g("parent_path") and name else (g("parent_path") or name)
            if network and unc:
                rec["path"] = unc
            rec["itemType"] = ("network" if network else
                               "volume" if ("volume" in sit or "drive" in sit) else
                               "file" if "file" in sit else "folder")
            rec["created"] = g("created_date") or ""
            rec["modified"] = g("modified_date") or ""
            rec["accessed"] = g("accessed_date") or ""
            rec["lastWritten"] = g("last_written") or ""
            rec["mftRecord"] = g("mft_record_number") or ""
            rec["size"] = g("file_size") or ""
            rec["registryPath"] = g("registry_path") or ""
            rec["parentPath"] = g("parent_path") or ""
            drive = g("drive_letter") or _drive_of(rec["path"])
            # When Explorer recorded the folder: the bag key's own write time.
            # The FAT modified time inside the shell item is the FOLDER's time,
            # so dating by it put folders browsed this week on 2014's days and
            # left recent days looking empty. It stays in the detail as
            # "Folder modified"; it is the fallback only when no write time
            # was recorded (cases parsed before last_written existed).
            rec["when"] = rec["lastWritten"] or rec["modified"] or rec["created"]

        elif source == "recentdocs":
            val = _clean_str(_pick(r, "row_data", "data"))
            rec["target"] = val or _clean_str(g("name")) or "(unparsed entry)"
            rec["path"] = val if _looks_pathy(val) else ""
            rec["itemType"] = "file" if "." in _base(rec["target"]) else "folder"
            rec["note"] = g("type") or ""
            drive = _drive_of(rec["path"])
            rec["when"] = rec["keyLastWrite"]

        elif source == "opensave":
            path = _clean_str(g("file_path"))
            rec["target"] = _clean_str(g("file_name")) or _base(path) or "(unparsed entry)"
            rec["path"] = path if _looks_pathy(path) else ""
            rec["itemType"] = "file"
            rec["note"] = (g("extension") or "").lstrip(".")
            drive = g("drive_letter") or _drive_of(rec["path"])
            rec["when"] = g("access_date") or rec["keyLastWrite"]

        elif source == "lastvisited":
            path = _clean_str(g("folder_path"))
            folder = _clean_str(g("folder_name")) or _base(path)
            app = g("application") or ""
            rec["target"] = folder or app or "(unparsed entry)"
            rec["path"] = path if _looks_pathy(path) else ""
            rec["itemType"] = "folder"
            rec["note"] = ("via " + app) if app else ""
            drive = g("drive_letter") or _drive_of(rec["path"])
            rec["when"] = g("access_date") or rec["keyLastWrite"]

        elif source == "typedpaths":
            val = _clean_str(_pick(r, "row_data", "data", "name"))
            rec["target"] = val or "(unparsed entry)"
            rec["path"] = val if ("\\" in val or ":" in val) else ""
            rec["itemType"] = "folder"
            network = val[:2] == "\\\\"
            drive = _drive_of(val)
            rec["when"] = rec["keyLastWrite"]

        elif source == "runmru":
            cmd = _clean_str(g("command"))
            rec["target"] = cmd or "(unparsed entry)"
            rec["path"] = cmd
            rec["itemType"] = "command"
            drive = _drive_of(cmd)
            rec["when"] = g("access_date") or rec["keyLastWrite"]

        elif source == "search":
            rec["target"] = _clean_str(g("search_term")) or "(unparsed entry)"
            rec["itemType"] = "search"
            rec["note"] = g("search_type") or ""
            drive = ""
            rec["when"] = g("access_date") or rec["keyLastWrite"]

        elif source == "dialogapps":
            rec["target"] = _clean_str(g("application")) or "(unparsed entry)"
            rec["itemType"] = "application"
            rec["mruPosition"] = g("position")
            rec["registryPath"] = g("key_path") or ""
            # One write time for the whole key: an upper bound for every entry,
            # exact only for the most recent one. Said so, not implied.
            rec["note"] = ("opened a file dialog; time is the key's write - " +
                           (g("time_basis") or "an upper bound"))
            drive = ""
            rec["when"] = rec["keyLastWrite"]
        elif source == "taskband":
            # One record per pinned item, split out by _records() from the
            # Favorites row's decoded list (registry_binary_parser.decode_taskband).
            pin = g("_pin") or ""
            rec["target"] = pin or _clean_str(g("value_decoded")) or "(pinned items)"
            rec["itemType"] = "pinned"
            rec["mruPosition"] = g("_pos")
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = ("pinned to the taskbar; time is the Taskband key's write - " +
                           (g("time_basis") or "an upper bound"))
            drive = ""
            rec["when"] = rec["keyLastWrite"]

        elif source == "mountpoints":
            mid = _clean_str(g("mount_id"))
            if mid.startswith("##"):
                # "##server#share" is how MountPoints2 spells \\server\share.
                rec["path"] = "\\\\" + mid[2:].replace("#", "\\")
                rec["target"] = rec["path"]
                network = True
                rec["itemType"] = "network"
            else:
                rec["target"] = mid or "(unnamed mount point)"
                rec["itemType"] = "volume"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = ((g("mount_type") or "mount point") + "; time is the key's write - " +
                           (g("time_basis") or "an upper bound"))
            drive = mid if len(mid) == 1 else ""
            rec["when"] = rec["keyLastWrite"]

        elif source == "office":
            raw = str(g("raw") or g("document") or "")
            doc = _clean_str(g("document")) or raw
            # "[F00000000][T01DC9F6D04C58F20][O00000000]*C:\path" - the [T..]
            # field is the item's own FILETIME, more exact than the key's write.
            opened = _office_filetime(raw)
            if "*" in doc and doc.startswith("["):
                doc = doc.split("*", 1)[1]
            rec["path"] = doc if _looks_pathy(doc) else ""
            rec["target"] = _base(doc) or doc or "(unparsed entry)"
            rec["itemType"] = "folder" if doc.endswith("\\") else "file"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = " ".join(x for x in ((g("application") or ""), (g("kind") or "")) if x)
            if not opened:
                rec["note"] += "; time is the key's write - " + (g("time_basis") or "an upper bound")
            drive = _drive_of(rec["path"])
            rec["when"] = opened or rec["keyLastWrite"]

        elif source == "typedurls":
            url = _clean_str(g("url"))
            rec["target"] = url or "(unparsed entry)"
            rec["itemType"] = "url"
            rec["note"] = "typed into the " + (g("browser") or "Internet Explorer") + " address bar"
            drive = ""
            rec["when"] = g("last_visit") or ""

        elif source == "rdp":
            rec["target"] = _clean_str(g("server")) or "(unparsed entry)"
            rec["itemType"] = "remote host"
            rec["registryPath"] = g("key_path") or ""
            hint = _clean_str(g("username_hint"))
            rec["note"] = ("Remote Desktop " + (g("entry_type") or "connection") +
                           ("; user " + hint if hint else ""))
            network = True
            drive = ""
            rec["when"] = rec["keyLastWrite"]

        elif source == "recentapps":
            app = _clean_str(g("app_path")) or _clean_str(g("app_id"))
            rec["target"] = _base(app) or app or "(unparsed entry)"
            rec["path"] = app if _looks_pathy(app) else ""
            rec["itemType"] = "application"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "launched %s time(s)" % (g("launch_count") or 0)
            drive = _drive_of(rec["path"])
            rec["when"] = g("last_accessed") or rec["keyLastWrite"]

        elif source == "appmru":
            val = _clean_str(g("value"))
            rec["target"] = (_base(val) if _looks_pathy(val) else val) or _clean_str(g("name")) or "(unparsed entry)"
            rec["path"] = val if _looks_pathy(val) else ""
            rec["itemType"] = "file" if rec["path"] else "item"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = " · ".join(x for x in ((g("application") or ""), (g("artifact") or "")) if x)
            drive = _drive_of(rec["path"])
            rec["when"] = rec["keyLastWrite"]

        elif source == "muicache":
            app = _clean_str(g("app_path"))
            rec["target"] = _clean_str(g("app_name")) or _base(app) or "(unparsed entry)"
            rec["path"] = app if _looks_pathy(app) else ""
            rec["itemType"] = "application"
            rec["note"] = " · ".join(x for x in (_clean_str(g("company")),
                                                 "launched by this user (MUICache; no time recorded)") if x)
            drive = _drive_of(rec["path"])
            rec["when"] = ""

        elif source == "shellfolders":
            target = _clean_str(g("data_decoded")) or _clean_str(g("data"))
            rec["target"] = _clean_str(g("name")) or "(unnamed folder)"
            rec["path"] = target if _looks_pathy(target) else ""
            rec["itemType"] = "folder"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "known folder redirected to %s (%s; no time recorded)" % (
                target or "?", g("hive") or "registry")
            if rec["user"] == "(machine-wide)":
                rec["user"] = ""
            drive = _drive_of(rec["path"])
            rec["when"] = ""

        elif source == "shellext":
            data = _clean_str(g("data_decoded")) or _clean_str(g("data"))
            rec["target"] = _clean_str(g("name")) or data or "(unnamed registration)"
            # Overlay handlers are stored as "{CLSID} -> <dll>": the DLL is the path.
            handler = data.split(" -> ", 1)[1].strip() if " -> " in data else data
            rec["path"] = handler if _looks_pathy(handler) else ""
            rec["itemType"] = "shell extension"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "%s: %s (no time recorded)" % (
                SHELLEXT_KIND.get(g("_src_table") or "", "shell registration"), data or "-")
            drive = _drive_of(rec["path"])
            rec["when"] = ""

        elif source == "userassist":
            prog = _clean_str(g("program_path"))
            if not prog or prog.upper().startswith("UEME_CTL"):
                return None             # UserAssist's own session counters
            rec["target"] = _base(prog) or prog
            rec["path"] = prog if _looks_pathy(prog) else ""
            rec["itemType"] = "executed"
            rec["user"] = _account(g("user_sid"))
            try:
                focus_s = "%.0fs" % (int(g("focus_time") or 0) / 1000.0)
            except (TypeError, ValueError):
                focus_s = str(g("focus_time") or "0")
            rec["note"] = "UserAssist: run %s time(s), focused %s time(s) for %s" % (
                g("run_count") or 0, g("focus_count") or 0, focus_s)
            drive = _drive_of(rec["path"])
            rec["when"] = _clean_str(g("last_execution"))

        elif source in ("bam", "dam"):
            proc = _clean_str(g("process_path"))
            if not proc:
                return None             # the Version / SequenceNumber values
            rec["target"] = _clean_str(g("app_name")) or _base(proc) or proc
            rec["path"] = proc
            rec["itemType"] = "executed"
            rec["user"] = _account(g("sid"))
            rec["registryPath"] = _clean_str(g("subkey"))
            what = "Background" if source == "bam" else "Desktop"
            rec["note"] = "%s Activity Moderator: last run by this account%s" % (
                what, ("; %s execution(s)" % g("execution_count")) if g("execution_count") else "")
            drive = _drive_of(rec["path"])
            rec["when"] = _clean_str(g("last_execution"))

        elif source == "apppermissions":
            app = _clean_str(g("app"))
            cap = _clean_str(g("capability")) or "a device"
            rec["target"] = (_base(app) if _looks_pathy(app) else app) or "(unnamed app)"
            rec["path"] = app if _looks_pathy(app) else ""
            rec["itemType"] = "device access"
            rec["registryPath"] = g("key_path") or ""
            start, stop = _clean_str(g("last_used_start")), _clean_str(g("last_used_stop"))
            rec["note"] = "used the %s%s%s%s" % (
                cap,
                (" from " + start) if start else "",
                (" until " + stop) if stop and stop != start else "",
                ("; permission " + _clean_str(g("permission"))) if _clean_str(g("permission")) else "")
            drive = _drive_of(rec["path"])
            rec["when"] = start or stop

        elif source == "featureusage":
            rec["target"] = _clean_str(g("program")) or "(unnamed program)"
            rec["path"] = rec["target"] if _looks_pathy(rec["target"]) else ""
            rec["itemType"] = "executed"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "FeatureUsage %s: %s; %s" % (
                g("usage_type") or "?", g("count") or 0, _upper_bound_note(r))
            drive = _drive_of(rec["path"])
            rec["when"] = ""

        elif source == "compat":
            prog = _clean_str(g("program_path"))
            rec["target"] = _base(prog) or prog or "(unparsed entry)"
            rec["path"] = prog if _looks_pathy(prog) else ""
            rec["itemType"] = "executed"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "Program Compatibility Assistant saw this program run; " + _upper_bound_note(r)
            drive = _drive_of(rec["path"])
            rec["when"] = ""

        elif source == "fileexts":
            rec["target"] = _clean_str(g("extension")) or "(no extension)"
            rec["itemType"] = "configured"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "opens with %s (%s); %s" % (
                _clean_str(g("progid")) or "?", g("choice_type") or "?", _upper_bound_note(r))
            drive = ""
            rec["when"] = ""

        elif source == "programscache":
            rec["target"] = _clean_str(g("value_name")) or "(unnamed value)"
            rec["itemType"] = "configured"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "Start menu program cache, %s byte(s); %s" % (
                g("blob_size") or 0, _upper_bound_note(r))
            drive = ""
            rec["when"] = ""

        elif source == "regedit":
            rec["target"] = _clean_str(g("value")) or "(unparsed entry)"
            rec["itemType"] = "registry key"
            rec["registryPath"] = g("key_path") or ""
            rec["note"] = "last key open in Registry Editor"
            drive = ""
            rec["when"] = rec["keyLastWrite"]
        else:
            return None

        rec["location"] = self._classify(rec["path"], drive, network)
        if rec["location"] == "network":
            rec["volume"] = rec["path"] if str(rec["path"]).startswith("\\\\") else "network"
            rec["volType"] = "network"
        elif drive:
            rec["volume"] = drive.upper()
            rec["volType"] = "removable" if drive.upper()[0] != "C" else "fixed"
        return rec

    def _records(self, source: str, r: dict) -> List[dict]:
        """The records one row yields - one, except Taskband's Favorites row,
        which names every pinned item ("5 pinned: Brave.lnk, ...; 6 by app id")."""
        if source != "taskband":
            rec = self._record(source, r)
            return [rec] if rec else []
        pins, apps = _split_taskband(r.get("value_decoded") or "")
        out = []
        for pos, name in enumerate(pins):
            rec = self._record(source, dict(r, _pin=name, _pos=pos))
            if rec:
                out.append(rec)
        if apps:
            rec = self._record(source, dict(r, _pin="%d Store app(s) pinned by app id (no shortcut)" % apps))
            if rec:
                rec["itemType"] = "application"
                out.append(rec)
        if not out:
            # A decode in a format this split does not know: keep the row whole.
            rec = self._record(source, dict(r))
            if rec:
                out.append(rec)
        return out

    def _all(self) -> List[dict]:
        if self._cache is None:
            recs, i = [], 0
            for src in SOURCES:
                # Most sources are one table; the shell-extension source reads
                # three that share a shape.
                for table in SOURCE_MULTI.get(src, (SOURCE_TABLES[src],)):
                    if not self._table_exists(table):
                        continue
                    sql = SOURCE_QUERIES.get(src, "SELECT * FROM %s" % table)
                    for r in self._query(sql):
                        if src in SOURCE_MULTI:
                            r = dict(r, _src_table=table)
                        for rec in self._records(src, r):
                            rec["id"] = i; i += 1
                            # The row this was built from, for the panel's Full
                            # record section. One shell item is one registry row
                            # (a Taskband row names several pins, and each pin
                            # points back to it).
                            rec["_row"] = {k: v for k, v in dict(r).items()
                                           if not k.startswith("_")}
                            rec["_table"] = table
                            recs.append(rec)
            self._cache = recs
        return self._cache

    def _filtered(self, args: dict) -> List[dict]:
        recs = self._all()
        start, end = args.get("start", ""), args.get("end", "")
        src = args.get("source", "")
        loc = args.get("location", "")
        vol = args.get("volume", "")
        terms = [t.strip().lower() for t in (args.get("terms") or []) if t and t.strip()]
        mode = (args.get("mode", "or") or "or").lower()
        out = []
        for x in recs:
            if src and x["source"] != src:
                continue
            if loc and x["location"] != loc:
                continue
            if vol and x["volume"] != vol:
                continue
            # An undated record (MUICache, User Shell Folders, the shell
            # extensions, most TypedURLs) has no time to fall outside a range,
            # so a range never drops it - the dashboard always sets one, and
            # these sources could never appear at all. The strip and the day
            # detail still skip it: they need a day.
            d = _daypart(x["when"])
            if (start or end) and d:
                if start and d < start:
                    continue
                if end and d > end:
                    continue
            if terms:
                hay = (x["target"] + " " + x["path"] + " " + x["user"] + " " + x["volume"]).lower()
                hit = [t in hay for t in terms]
                if (all(hit) if mode == "and" else any(hit)) is False:
                    continue
            out.append(x)
        return out

    @staticmethod
    def _place(x: dict) -> str:
        """The folder a row 'visited' - the target itself for a folder, else its parent."""
        if x["itemType"] in ("folder", "volume", "network"):
            v = x["path"] or x["target"]
        else:
            v = _dirof(x["path"])
        v = _clean_str(v)
        if not v or v.startswith("(") or v.isdigit():
            return ""
        if (v[1:3] == ":\\" or v[:2] == "\\\\") and _looks_pathy(v):
            return v                                       # absolute drive or UNC
        # A clean single folder name, or a clean relative path (the decoder now
        # emits MUI-resolved relatives like "Pictures\Screenshots"), is a real
        # place. A segment carrying an illegal filename char is a half-decoded
        # PIDL fragment - drop it rather than rank junk.
        segs = [s for s in v.split("\\") if s]
        if segs and len(v) >= 2 and not any(set(s) & _ILLEGAL_PLACE_CHARS for s in segs):
            return v
        return ""

    # ---- slots -------------------------------------------------------------
    @pyqtSlot(result=str)
    def getShellItemsFocus(self) -> str:
        """{"source": key} - the table the dashboard was opened from, or ""."""
        return json.dumps({"source": self.focus_source})

    @pyqtSlot(result=str)
    def getShellItemsBounds(self) -> str:
        recs = self._all()
        if not recs:
            return json.dumps({"hasData": False})
        days = [d for d in (_daypart(x["when"]) for x in recs) if d]
        counts = {s: sum(1 for x in recs if x["source"] == s) for s in SOURCES}
        vols = sorted({x["volume"] for x in recs if x["volume"]})
        return json.dumps({
            "hasData": True,
            "minDate": min(days) if days else None,
            "maxDate": max(days) if days else None,
            "counts": counts, "volumes": vols,
            "total": len(recs),
            "sourceErrors": self._source_errors(),
            "emptyNotes": self._empty_notes(counts),
        })

    def _source_errors(self) -> dict:
        """source -> error text, for sources whose table could not be read."""
        out = {}
        for src, table in SOURCE_TABLES.items():
            for sql, err in self._errors.items():
                if (" " + table) in sql:
                    out[src] = err
        return out

    def _empty_notes(self, counts: dict) -> dict:
        """source -> why it can legitimately hold nothing (configs/empty_table_hints.json)."""
        try:
            from utils.table_sources import hint_for
        except Exception:
            return {}
        notes = {}
        for src, n in counts.items():
            if not n:
                text = hint_for(HINT_KEYS.get(src, SOURCE_TABLES[src]), "registry")
                if not self._table_exists(SOURCE_TABLES[src]):
                    text = "Not in this case's registry database. " + text
                notes[src] = text.strip()
        return notes

    @pyqtSlot(str, result=str)
    def getShellItemsAll(self, args_json: str) -> str:
        """Every item that matches the filters, across all days - the full list.

        The rest of the dashboard is read one day at a time, so on a case with
        1,100 items over 157 days the only way to see them all was to click
        through every day. Paged: `offset`/`limit` (default 500), newest first
        unless `order` is "asc". Undated items are listed too, last.
        """
        args = _loads(args_json)
        recs = list(self._filtered(args))
        asc = (args.get("order") or "desc").lower() == "asc"
        dated = sorted((x for x in recs if _daypart(x["when"])),
                       key=lambda x: str(x["when"]), reverse=not asc)
        undated = [x for x in recs if not _daypart(x["when"])]
        ordered = dated + undated
        try:
            offset = max(0, int(args.get("offset", 0) or 0))
            limit = max(1, min(2000, int(args.get("limit", 500) or 500)))
        except (TypeError, ValueError):
            offset, limit = 0, 500
        page = ordered[offset:offset + limit]
        days = {_daypart(x["when"]) for x in dated}
        return json.dumps({
            "total": len(ordered), "days": len(days), "offset": offset,
            "rows": [{"id": x["id"], "t": x["when"], "source": x["source"],
                      "target": x["target"], "path": x["path"], "user": x["user"],
                      "itemType": x["itemType"], "volume": x["volume"]} for x in page],
        })

    @pyqtSlot(str, result=str)
    def getShellItemsTimeline(self, args_json: str) -> str:
        args = _loads(args_json)
        recs = self._filtered(args)
        per = {s: {} for s in SOURCES}
        combined = {}
        for x in recs:
            d = _daypart(x["when"])
            if not d:
                continue
            per[x["source"]][d] = per[x["source"]].get(d, 0) + 1
            combined[d] = combined.get(d, 0) + 1
        # Only days that HAD activity come out of a GROUP BY, which turns the
        # strip into an ordinal list of active days rather than a time axis -
        # a quiet stretch closes up and vanishes. Fill every day in the range.
        # A cell is always one day; a range too long to fit scrolls instead of
        # changing what a cell means. See timeseries.py.
        start, end = _axis_range(args, combined)
        sources = _densify_series(per, start, end)
        combined_rows = _densify(combined, start, end)
        return json.dumps({"sources": sources, "combined": combined_rows})

    @pyqtSlot(str, result=str)
    def getShellItemsOverview(self, args_json: str) -> str:
        recs = self._filtered(_loads(args_json))
        by_src = {s: 0 for s in SOURCES}
        vols, places, files = {}, {}, {}
        days, users, targets = set(), set(), set()
        network = removable = mac_mismatch = 0
        # Who matched, not just how many - see visualizations/insights.py.
        network_subj, removable_subj, mac_subj = [], [], []
        for x in recs:
            by_src[x["source"]] += 1
            d = _daypart(x["when"])
            if d:
                days.add(d)
            if x["user"]:
                users.add(x["user"])
            targets.add(x["path"] or x["target"])
            if x["location"] == "network":
                network += 1
                network_subj.append(_subject(x["path"] or x["target"], x["id"],
                                             x["user"] or x["source"]))
            if x["location"] == "removable":
                removable += 1
                removable_subj.append(_subject(x["path"] or x["target"], x["id"],
                                               x["volume"] or "unnamed volume"))
            if (x["source"] == "shellbags" and x["modified"] and x["lastWritten"]
                    and _daypart(x["modified"]) and _daypart(x["modified"]) != _daypart(x["lastWritten"])):
                mac_mismatch += 1
                mac_subj.append(_subject(
                    x["path"] or x["target"], x["id"],
                    "modified %s, key written %s" % (x["modified"], x["lastWritten"])))
            if x["volume"]:
                key = (x["volume"], x["volType"] or "local")
                vols[key] = vols.get(key, 0) + 1
            pl = self._place(x)
            if pl:
                places[pl] = places.get(pl, 0) + 1
            if (x["itemType"] == "file" and x["target"] and "." in x["target"]
                    and not x["target"].startswith("(")):
                files[x["target"]] = files.get(x["target"], 0) + 1
        top = lambda d, kn, n: sorted(({kn: k, "n": v} for k, v in d.items()),
                                      key=lambda z: z["n"], reverse=True)[:n]
        volumes = sorted(({"label": k[0], "type": k[1], "n": v} for k, v in vols.items()),
                         key=lambda z: z["n"], reverse=True)[:12]
        return json.dumps({
            "totals": {"items": len(recs), "targets": len(targets),
                       "sources": sum(1 for s in SOURCES if by_src[s]), "activeDays": len(days),
                       "network": network, "removable": removable, "users": len(users)},
            "bySource": [{"source": s, "n": by_src[s]} for s in SOURCES],
            "topPlaces": top(places, "place", 12),
            "topFiles": top(files, "file", 10),
            "volumes": volumes,
            "insights": {
                "network": _insight(network, network_subj),
                "removable": _insight(removable, removable_subj),
                # A count of distinct users, not of records.
                "users": _plain(len(users)),
                "macMismatch": _insight(mac_mismatch, mac_subj),
            },
        })

    @pyqtSlot(str, result=str)
    def getShellItemsDayDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        day = args.get("day")
        if not day:
            return json.dumps({"events": [], "byHour": {}, "bySource": [], "topPlaces": []})
        recs = self._filtered(args)
        by_hour = {s: [0] * 24 for s in SOURCES}
        by_src, places = {s: 0 for s in SOURCES}, {}
        events = []
        for x in recs:
            if _daypart(x["when"]) != day[:10]:
                continue
            hh = _hourpart(x["when"])
            by_hour[x["source"]][hh] += 1
            by_src[x["source"]] += 1
            pl = self._place(x)
            if pl:
                places[pl] = places.get(pl, 0) + 1
            events.append({"id": x["id"], "source": x["source"], "target": x["target"],
                           "t": x["when"], "hour": hh, "itemType": x["itemType"],
                           "mru": x["mruPosition"], "volume": x["volume"], "path": x["path"]})
        events.sort(key=lambda z: str(z["t"]))
        top = sorted(({"place": k, "n": v} for k, v in places.items()),
                     key=lambda z: z["n"], reverse=True)[:8]
        return json.dumps({"events": events, "byHour": by_hour,
                           "bySource": [{"source": s, "n": by_src[s]} for s in SOURCES if by_src[s]],
                           "topPlaces": top})

    @pyqtSlot(str, result=str)
    def getShellItemsDayActivity(self, args_json: str) -> str:
        """Bubble-timeline data for one day: item (Y) x hour (X), size = count.

        Modelled on SRUM's getSrumDayActivity. A shell-item row contributes one
        point at (target, hour-of-its-time); points at the same cell accumulate,
        so a folder browsed several times in an hour reads as a larger bubble.
        Colour = source. Most rows carry a single time, so a quiet day is a
        column of small bubbles rather than a dense field - honest for the data.
        """
        args = _loads(args_json)
        day = args.get("day")
        top_n = int(args.get("topN", 30) or 30)
        if not day:
            return json.dumps({"day": day, "items": [], "points": [], "ranges": {}})
        cells = {}                      # (item, hour) -> {value, source}
        totals = {}                     # item -> count
        for x in self._filtered(args):
            if _daypart(x["when"]) != day[:10]:
                continue
            # By path: 188 names are shared by 664 records on the reference
            # case ("Pictures", "Downloads"), and grouping by name merged items
            # at different places into one row.
            item = x["path"] or x["target"] or "(unnamed)"
            hh = _hourpart(x["when"])
            key = (item, hh)
            c = cells.get(key)
            if c is None:
                cells[key] = {"value": 1, "source": x["source"]}
            else:
                c["value"] += 1
            totals[item] = totals.get(item, 0) + 1
        items = [k for k, _ in sorted(totals.items(), key=lambda z: z[1], reverse=True)][:top_n]
        keep = set(items)
        points, ranges = [], {}
        for (item, hh), c in cells.items():
            if item not in keep:
                continue
            points.append({"item": item, "hour": hh, "value": c["value"], "source": c["source"]})
            r = ranges.get(item)
            ranges[item] = {"min": min(hh, r["min"]), "max": max(hh, r["max"])} if r else {"min": hh, "max": hh}
        return json.dumps({"day": day, "items": items, "points": points, "ranges": ranges})

    @pyqtSlot(str, result=str)
    def getShellItemsItemDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        iid = args.get("id")
        rec = next((x for x in self._all() if x["id"] == iid), None)
        if not rec:
            return json.dumps({})
        mismatch = bool(rec["source"] == "shellbags" and rec["modified"] and rec["lastWritten"]
                        and _daypart(rec["modified"]) and _daypart(rec["modified"]) != _daypart(rec["lastWritten"]))
        return json.dumps({
            "source": rec["source"], "target": rec["target"], "path": rec["path"],
            "itemType": rec["itemType"], "volume": rec["volume"], "volType": rec["volType"],
            "location": rec["location"], "mruPosition": rec["mruPosition"],
            "when": rec["when"], "user": rec["user"], "note": rec["note"],
            "times": {"created": rec["created"], "modified": rec["modified"],
                      "accessed": rec["accessed"], "lastWritten": rec["lastWritten"],
                      "keyLastWrite": rec["keyLastWrite"]},
            "mftRecord": rec["mftRecord"], "size": rec["size"],
            "registryPath": rec["registryPath"], "parentPath": rec["parentPath"],
            "macMismatch": mismatch,
            # The registry row this item was read from, verbatim. An earlier
            # comment here claimed a shell item had no single source row: that
            # confused the dashboard (which reads Shellbags, RecentDocs,
            # OpenSaveMRU, TypedPaths...) with an item, which comes from one
            # row of one of them.
            "raw": _raw(rec.get("_row"), rec.get("_table", "")),
        })
