"""Parse status: why an artifact - and so a table - came out the way it did.

An empty evidence table used to tell the investigator nothing. A machine that
never had the artifact (Prefetch disabled, SRUM before Windows 8, no browser
installed) looked exactly like a parser crash. This module gives every parse,
live, offline or image, one neutral outcome per artifact:

    PARSED              records were written
    NO_RECORDS          the source was read and held nothing
    SOURCE_NOT_FOUND    the path / hive / file does not exist on this evidence
    FEATURE_DISABLED    a known OS or setting reason (Prefetch turned off, ...)
    UNSUPPORTED_FORMAT  a version or signature the parser does not support
    ACCESS_DENIED       locked or permission problem
    DEPENDENCY_MISSING  a library the parser needs is not installed
    PARTIAL             some of the input parsed, some failed
    FAILED              the parser raised or reported an error
    NOT_RUN             not selected, cancelled, or not available in this mode

The first four are NOT failures and are said so on screen.

Three pieces, all usable without Qt so the live collector can run them in its
worker process:

    probe_sources()    cheap pre-flight existence check of the known sources
    classify_result()  the one normaliser for every shape a parser returns
    ParseStatusStore   <case>/logs/parse_status.json + the parse_status logger

The store is read by the summary dialog (ui/parse_status_dialog.py), the i
button above every empty table (utils/table_sources.py) and Settings -> Logs.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

try:
    from utils.time_utils import get_current_forensic_timestamp
except Exception:  # pragma: no cover - standalone use
    def get_current_forensic_timestamp():
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


logger = logging.getLogger("crow_eye.parse_status")

STATUS_FILE = "parse_status.json"


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

class ParseStatus:
    PARSED = "PARSED"
    NO_RECORDS = "NO_RECORDS"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    ACCESS_DENIED = "ACCESS_DENIED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"

    ALL = (PARSED, NO_RECORDS, SOURCE_NOT_FOUND, FEATURE_DISABLED,
           UNSUPPORTED_FORMAT, ACCESS_DENIED, DEPENDENCY_MISSING, PARTIAL,
           FAILED, NOT_RUN)


# label, severity (ok / neutral / warning / error / idle), colour, one-liner
STATUS_INFO = {
    ParseStatus.PARSED: ("Parsed", "ok", "#22C55E",
                         "Records were extracted."),
    ParseStatus.NO_RECORDS: ("No records", "neutral", "#38BDF8",
                             "The source was read successfully but held no records. "
                             "Not a failure."),
    ParseStatus.SOURCE_NOT_FOUND: ("Source not found", "neutral", "#38BDF8",
                                   "The artifact does not exist on this system or image. "
                                   "Not a failure."),
    ParseStatus.FEATURE_DISABLED: ("Feature disabled", "neutral", "#38BDF8",
                                   "The OS version or a system setting does not produce "
                                   "this artifact. Not a failure."),
    ParseStatus.UNSUPPORTED_FORMAT: ("Unsupported format", "warning", "#F59E0B",
                                     "The artifact exists but its version or format is not "
                                     "supported by the parser."),
    ParseStatus.ACCESS_DENIED: ("Access denied", "warning", "#F59E0B",
                                "The artifact exists but could not be read (locked or "
                                "insufficient privileges)."),
    ParseStatus.DEPENDENCY_MISSING: ("Dependency missing", "warning", "#F59E0B",
                                     "A library the parser needs is not installed."),
    ParseStatus.PARTIAL: ("Partial", "warning", "#F59E0B",
                          "Some input parsed, some failed."),
    ParseStatus.FAILED: ("Failed", "error", "#EF4444",
                         "The parser raised or reported an error."),
    ParseStatus.NOT_RUN: ("Not run", "idle", "#94A3B8",
                          "The parser was not run for this artifact in this mode."),
}

NOT_A_FAILURE = {ParseStatus.NO_RECORDS, ParseStatus.SOURCE_NOT_FOUND,
                 ParseStatus.FEATURE_DISABLED}


def status_label(status: str) -> str:
    return STATUS_INFO.get(status, (status,))[0]


def status_color(status: str) -> str:
    return STATUS_INFO.get(status, ("", "", "#94A3B8"))[2]


def status_severity(status: str) -> str:
    return STATUS_INFO.get(status, ("", "idle"))[1]


def is_failure(status: str) -> bool:
    return status_severity(status) in ("warning", "error")


# --------------------------------------------------------------------------
# Artifacts
# --------------------------------------------------------------------------

# canonical key -> (display label, database file(s) under Target_Artifacts)
ARTIFACTS: Dict[str, tuple] = {
    "registry":            ("Registry", ("registry_data.db",)),
    "lnk_jumplist":        ("LNK & Jump Lists", ("LnkDB.db",)),
    "prefetch":            ("Prefetch", ("prefetch_data.db",)),
    "evtx":                ("Event Logs", ("Log_Claw.db",)),
    "shimcache":           ("ShimCache", ("shimcache.db",)),
    "amcache":             ("Amcache", ("amcache.db",)),
    "recyclebin":          ("Recycle Bin", ("recyclebin_analysis.db",)),
    "srum":                ("SRUM", ("srum_data.db",)),
    "browser":             ("Browsers", ("browser_analysis.db",)),
    "mft":                 ("MFT", ("mft_claw_analysis.db",)),
    "usn":                 ("USN Journal", ("USN_journal.db",)),
    "mft_usn_correlation": ("MFT-USN Correlation", ("mft_usn_correlated_analysis.db",)),
}

ARTIFACT_ORDER = list(ARTIFACTS)

# The type names the offline/image chain (ArtifactTypeDetector, ParserInvoker,
# refresh_gui_tabs_after_parsing) uses, mapped onto the canonical keys.
_TYPE_ALIASES = {
    "registry": "registry",
    "prefetch": "prefetch",
    "amcache": "amcache",
    "link_jumplist": "lnk_jumplist", "jumplists": "lnk_jumplist",
    "lnk": "lnk_jumplist", "lnk_jumplist": "lnk_jumplist",
    "shimcache": "shimcache",
    "evtx": "evtx", "eventlogs": "evtx", "logs": "evtx",
    "recyclebin": "recyclebin",
    "srum": "srum",
    "browser": "browser",
    "mft": "mft",
    "usn": "usn",
    "mft_usn_correlation": "mft_usn_correlation", "correlation": "mft_usn_correlation",
}


def canonical_artifact(name: str) -> Optional[str]:
    if not name:
        return None
    return _TYPE_ALIASES.get(str(name).strip().lower())


def artifact_label(artifact: str) -> str:
    return ARTIFACTS.get(artifact, (artifact,))[0]


# --------------------------------------------------------------------------
# Outcome
# --------------------------------------------------------------------------

@dataclass
class ArtifactOutcome:
    artifact: str
    mode: str                       # live / offline / image
    status: str
    records: int = 0
    message: str = ""
    sources_checked: List[Dict[str, Any]] = field(default_factory=list)
    details: List[str] = field(default_factory=list)
    parsed_at: str = ""
    run_id: str = ""

    def __post_init__(self):
        if not self.parsed_at:
            self.parsed_at = get_current_forensic_timestamp()

    @property
    def label(self) -> str:
        return artifact_label(self.artifact)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactOutcome":
        known = {k: data.get(k) for k in cls.__dataclass_fields__ if k in data}
        known.setdefault("mode", "")
        known.setdefault("status", ParseStatus.NOT_RUN)
        known.setdefault("artifact", "")
        out = cls(**known)
        out.records = int(out.records or 0)
        out.sources_checked = list(out.sources_checked or [])
        out.details = list(out.details or [])
        return out


@dataclass
class ParserResultLike:
    """The ParserResult shape, for results folded from several of them."""
    success: bool
    records_parsed: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: Optional[str] = None


# --------------------------------------------------------------------------
# Error text -> status
# --------------------------------------------------------------------------

_ERROR_RULES = [
    (ParseStatus.DEPENDENCY_MISSING, (
        r"no module named", r"modulenotfounderror", r"importerror", r"pip install",
        r"library (is )?not (available|installed)", r"ese library", r"esent\.dll",
        r"python-evtx", r"dependency")),
    (ParseStatus.ACCESS_DENIED, (
        r"permission denied", r"access (is )?denied", r"cannot access",
        r"administrator", r"privilege", r"locked", r"being used by another process",
        r"winerror 5\b", r"winerror 32\b", r"sharing violation")),
    (ParseStatus.UNSUPPORTED_FORMAT, (
        r"unsupported", r"not supported", r"unknown version", r"invalid signature",
        r"bad signature", r"signature mismatch", r"not compatible", r"unknown format",
        r"corrupt", r"not a valid", r"invalid (file|header|format)")),
    (ParseStatus.SOURCE_NOT_FOUND, (
        r"not found", r"does not exist", r"no such file", r"cannot find",
        r"notadirectoryerror", r"filenotfounderror", r"winerror 2\b", r"winerror 3\b",
        r"no .* (found|available)", r"missing required registry hives",
        r"no ntfs volumes", r"no hives")),
]


def classify_error_text(text: str) -> str:
    """Map a free-text parser error onto a status. Unknown text -> FAILED."""
    low = (text or "").lower()
    if not low.strip():
        return ParseStatus.FAILED
    for status, patterns in _ERROR_RULES:
        for pat in patterns:
            if re.search(pat, low):
                return status
    return ParseStatus.FAILED


# --------------------------------------------------------------------------
# Database inspection
# --------------------------------------------------------------------------

def db_table_counts(db_path: str) -> Dict[str, int]:
    """{table: row count} for a SQLite file, read-only. {} if unreadable."""
    counts: Dict[str, int] = {}
    if not db_path or not os.path.isfile(db_path):
        return counts
    conn = None
    try:
        uri = "file:%s?mode=ro" % db_path.replace("\\", "/")
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        for name in names:
            try:
                counts[name] = int(conn.execute(
                    'SELECT COUNT(*) FROM "%s"' % name.replace('"', '""')).fetchone()[0])
            except sqlite3.Error:
                counts[name] = -1
    except sqlite3.Error:
        return {}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return counts


def artifact_db_paths(case_root: str, artifact: str) -> List[str]:
    files = ARTIFACTS.get(artifact, ("", ()))[1]
    base = os.path.join(case_root or "", "Target_Artifacts")
    return [os.path.join(base, f) for f in files]


def artifact_db_records(case_root: str, artifact: str,
                        since: Optional[float] = None) -> Optional[int]:
    """Total rows across an artifact's databases.

    None when no database exists - or, with `since`, when none was written
    after that moment, so rows left by an earlier parse are not credited to
    this one.
    """
    total, seen = 0, False
    for path in artifact_db_paths(case_root, artifact):
        if not os.path.isfile(path):
            continue
        if since is not None:
            try:
                newest = max(os.path.getmtime(p) for p in (path, path + "-wal")
                             if os.path.exists(p))
            except (OSError, ValueError):
                newest = 0
            if newest + 2 < since:
                continue
        seen = True
        total += sum(c for c in db_table_counts(path).values() if c > 0)
    return total if seen else None


# --------------------------------------------------------------------------
# Source probes
# --------------------------------------------------------------------------

def _src(path: str, exists: Optional[bool] = None, note: str = "") -> Dict[str, Any]:
    if exists is None:
        exists = os.path.exists(path)
    d = {"path": path, "exists": bool(exists)}
    if note:
        d["note"] = note
    return d


def _windows_build() -> int:
    try:
        import sys
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def _prefetch_enabled() -> Optional[int]:
    """EnablePrefetcher value, or None when it cannot be read."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
            r"\PrefetchParameters")
        try:
            value, _ = winreg.QueryValueEx(key, "EnablePrefetcher")
        finally:
            winreg.CloseKey(key)
        return int(value)
    except Exception:
        return None


def _filesystem_name(root: str) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(64)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0, None, None, None, buf, len(buf))
        return buf.value if ok else ""
    except Exception:
        return ""


_BROWSER_ROOTS = (
    r"AppData\Local\Google\Chrome\User Data",
    r"AppData\Local\Microsoft\Edge\User Data",
    r"AppData\Local\BraveSoftware\Brave-Browser\User Data",
    r"AppData\Local\Vivaldi\User Data",
    r"AppData\Local\Chromium\User Data",
    r"AppData\Roaming\Opera Software",
    r"AppData\Roaming\Mozilla\Firefox\Profiles",
)


def probe_sources(artifact: str, mode: str = "live", windows_partition: str = "C:",
                  case_root: Optional[str] = None,
                  scanned_paths: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Pre-flight check of where an artifact lives.

    Returns {"sources": [...], "status": <hint or None>, "message": str}.
    The hint is only ever a neutral one (SOURCE_NOT_FOUND / FEATURE_DISABLED):
    a probe can say "it is not there", never "the parser broke".

    Offline/image: `scanned_paths` are the paths ArtifactTypeDetector found
    for this type; an empty list means the evidence does not contain it.
    """
    if mode != "live":
        paths = list(scanned_paths or [])
        if artifact == "browser":
            return {"sources": [], "status": ParseStatus.NOT_RUN,
                    "message": "Browser parsing is available for live systems only; "
                               "offline/image browser parsing is not supported yet."}
        if not paths:
            return {"sources": [], "status": ParseStatus.SOURCE_NOT_FOUND,
                    "message": "No %s artifacts were found in the collected evidence."
                               % artifact_label(artifact)}
        return {"sources": [_src(p) for p in paths[:5]], "status": None,
                "message": "%d source file(s) found in the evidence." % len(paths)}

    part = (windows_partition or "C:").rstrip("\\/")
    root = part + "\\"
    win = os.path.join(root, "Windows")
    users = glob.glob(os.path.join(root, "Users", "*"))
    sources: List[Dict[str, Any]] = []
    status, message = None, ""

    if artifact in ("registry", "shimcache"):
        sources = [_src(os.path.join(win, "System32", "config", "SYSTEM")),
                   _src(os.path.join(win, "System32", "config", "SOFTWARE"))]
        if not any(s["exists"] for s in sources):
            status, message = ParseStatus.SOURCE_NOT_FOUND, "Registry hives not found."

    elif artifact == "prefetch":
        pf = os.path.join(win, "Prefetch")
        sources = [_src(pf)]
        enabled = _prefetch_enabled()
        if enabled == 0:
            sources.append(_src("HKLM\\...\\PrefetchParameters\\EnablePrefetcher", True,
                                "value 0 (disabled)"))
            status = ParseStatus.FEATURE_DISABLED
            message = ("Prefetch is disabled on this system (EnablePrefetcher = 0). "
                       "This is the default on Windows Server and on some SSD/VM "
                       "configurations.")
        elif not sources[0]["exists"]:
            status, message = ParseStatus.SOURCE_NOT_FOUND, "%s does not exist." % pf
        else:
            try:
                if not any(n.lower().endswith(".pf") for n in os.listdir(pf)):
                    status = ParseStatus.SOURCE_NOT_FOUND
                    message = "The Prefetch folder exists but contains no .pf files."
            except PermissionError:
                pass
            except OSError:
                pass

    elif artifact == "amcache":
        hve = os.path.join(win, "AppCompat", "Programs", "Amcache.hve")
        sources = [_src(hve)]
        if not sources[0]["exists"]:
            build = _windows_build()
            if build and build < 9200:
                status = ParseStatus.FEATURE_DISABLED
                message = "Amcache.hve exists only on Windows 8 / Server 2012 and later."
            else:
                status, message = ParseStatus.SOURCE_NOT_FOUND, "%s does not exist." % hve

    elif artifact == "srum":
        db = os.path.join(win, "System32", "sru", "SRUDB.dat")
        sources = [_src(db)]
        if not sources[0]["exists"]:
            build = _windows_build()
            if build and build < 9200:
                status = ParseStatus.FEATURE_DISABLED
                message = "SRUM exists only on Windows 8 and later."
            else:
                status = ParseStatus.SOURCE_NOT_FOUND
                message = ("SRUDB.dat does not exist - the Diagnostic Policy Service may "
                           "be disabled.")

    elif artifact == "evtx":
        logs = os.path.join(win, "System32", "winevt", "Logs")
        sources = [_src(logs)]
        if not sources[0]["exists"]:
            status, message = ParseStatus.SOURCE_NOT_FOUND, "%s does not exist." % logs

    elif artifact == "recyclebin":
        bins = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            p = "%s:\\$Recycle.Bin" % letter
            if os.path.exists("%s:\\" % letter) and os.path.exists(p):
                bins.append(p)
        sources = [_src(p, True) for p in bins] or [_src(root + "$Recycle.Bin")]
        if not bins:
            status, message = ParseStatus.SOURCE_NOT_FOUND, "No $Recycle.Bin folder found."

    elif artifact == "lnk_jumplist":
        recent = [os.path.join(u, "AppData", "Roaming", "Microsoft", "Windows", "Recent")
                  for u in users]
        found = [p for p in recent if os.path.isdir(p)]
        sources = [_src(p, True) for p in found[:5]]
        if not found:
            sources = [_src(os.path.join(root, "Users", "*", r"AppData\Roaming\Microsoft"
                                         r"\Windows\Recent"), False)]
            status = ParseStatus.SOURCE_NOT_FOUND
            message = "No user Recent folders were found."

    elif artifact == "browser":
        found = []
        for u in users:
            for rel in _BROWSER_ROOTS:
                p = os.path.join(u, rel)
                if os.path.isdir(p):
                    found.append(p)
        sources = [_src(p, True) for p in found[:8]]
        if not found:
            sources = [_src(os.path.join(root, "Users", "*", r"AppData\...\User Data"), False)]
            status = ParseStatus.SOURCE_NOT_FOUND
            message = "No Chromium or Firefox profile folders were found for any user."

    elif artifact in ("mft", "usn", "mft_usn_correlation"):
        fs = _filesystem_name(root)
        sources = [_src(root, os.path.exists(root), ("filesystem: %s" % fs) if fs else "")]
        if fs and fs.upper() != "NTFS":
            status = ParseStatus.SOURCE_NOT_FOUND
            message = "%s is %s, not NTFS - there is no $MFT / $UsnJrnl." % (root, fs)

    return {"sources": sources, "status": status, "message": message}


# --------------------------------------------------------------------------
# Normaliser
# --------------------------------------------------------------------------

def _texts(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


def _records_from(value) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        for k in ("total_records", "records", "total", "rows"):
            if isinstance(value.get(k), (int, float)) and not isinstance(value.get(k), bool):
                return int(value[k])
        return sum(int(v) for v in value.values()
                   if isinstance(v, (int, float)) and not isinstance(v, bool))
    return 0


def classify_result(artifact: str, raw_result: Any = None, exc: Optional[BaseException] = None,
                    probe: Optional[Dict[str, Any]] = None, mode: str = "live",
                    db_records: Optional[int] = None, details: Optional[List[str]] = None,
                    cancelled: bool = False) -> ArtifactOutcome:
    """Turn whatever a parser handed back into one ArtifactOutcome.

    Understands: dicts with success/error/errors/warnings/records/statistics,
    ParserResult objects, the run_task {"error", "traceback"} dict, int exit
    codes (MFT/USN: 0 ok), a db path string, None, and an exception.

    Order: explicit status -> cancelled -> exception/error text -> neutral
    probe hint when nothing was produced -> record count.
    """
    probe = probe or {}
    sources = list(probe.get("sources") or [])
    details = list(details or [])
    errors: List[str] = []
    warnings: List[str] = []
    reported = 0
    explicit = None
    success: Optional[bool] = None

    r = raw_result
    if r is not None and hasattr(r, "records_parsed") and hasattr(r, "success"):
        success = bool(r.success)
        reported = int(getattr(r, "records_parsed", 0) or 0)
        errors += _texts(getattr(r, "errors", None))
        warnings += _texts(getattr(r, "warnings", None))
        explicit = getattr(r, "status", None)
    elif isinstance(r, dict):
        explicit = r.get("status")
        if "success" in r:
            success = bool(r.get("success"))
        errors += _texts(r.get("error")) + _texts(r.get("errors"))
        warnings += _texts(r.get("warnings"))
        if r.get("traceback") and "success" not in r:
            success = False
        reported = _records_from(r.get("records"))
        if not reported:
            reported = _records_from(r.get("statistics"))
    elif isinstance(r, bool):
        success = r
    elif isinstance(r, int):
        success = (r == 0)
        if r != 0:
            errors.append("Parser exited with code %d" % r)
    # str (db path) / None: nothing to read - the probe and the db decide.

    if exc is not None:
        success = False
        errors.insert(0, "%s: %s" % (type(exc).__name__, exc))

    records = max(reported, db_records or 0)
    probe_hint = probe.get("status")
    probe_msg = probe.get("message", "")

    def out(status, message):
        return ArtifactOutcome(artifact=artifact, mode=mode, status=status,
                               records=records, message=message,
                               sources_checked=sources,
                               details=details + ["Warning: %s" % w for w in warnings[:10]]
                               + ["Error: %s" % e for e in errors[1:10]])

    if explicit in ParseStatus.ALL:
        return out(explicit, (errors[0] if errors else probe_msg) or STATUS_INFO[explicit][3])

    if cancelled:
        return out(ParseStatus.NOT_RUN, "Cancelled before this artifact finished.")

    if probe_hint == ParseStatus.NOT_RUN and records == 0:
        return out(ParseStatus.NOT_RUN, probe_msg)

    # Nothing produced and the probe already knows why: that is the answer,
    # whatever error text the parser threw on its way out.
    if records == 0 and probe_hint in (ParseStatus.SOURCE_NOT_FOUND,
                                       ParseStatus.FEATURE_DISABLED):
        return out(probe_hint, probe_msg)

    if errors or success is False:
        text = errors[0] if errors else "The parser reported failure without a message."
        status = classify_error_text(text) if errors else ParseStatus.FAILED
        if records > 0:
            return out(ParseStatus.PARTIAL,
                       "%d record(s) extracted, but: %s" % (records, text))
        return out(status, text)

    if records > 0:
        msg = "%d record(s) extracted." % records
        if details:
            msg += " %d item(s) skipped - see details." % len(details)
        return out(ParseStatus.PARSED, msg)

    if db_records is None and r is None and success is None and probe_hint is None:
        # A None return and no database written: the parser said nothing and
        # left nothing. Most live parsers return None only when they bail out.
        return out(ParseStatus.FAILED,
                   "The parser produced no output database and reported no reason.")

    msg = "The source was read but contained no records."
    if probe_msg:
        # A neutral hint explains the emptiness; otherwise the probe only
        # said what it found, which is context, not the reason.
        msg = probe_msg if probe_hint else "%s (%s)" % (msg, probe_msg)
    return out(ParseStatus.NO_RECORDS, msg)


def prefetch_failed_files(case_root: str, since: Optional[float] = None) -> List[str]:
    """Names in failed_prefetch_files.txt (unsupported/corrupt .pf), if fresh."""
    path = os.path.join(case_root or "", "Target_Artifacts", "failed_prefetch_files.txt")
    try:
        if since is not None and os.path.getmtime(path) + 2 < since:
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            names = [ln.strip() for ln in fh if ln.strip()]
        return ["Unsupported or corrupt prefetch file skipped: %s" % n for n in names]
    except OSError:
        return []


def collect_live_outcome(artifact: str, case_root: str, windows_partition: str,
                         raw_result: Any = None, exc: Optional[BaseException] = None,
                         started: Optional[float] = None, probe: Optional[dict] = None,
                         cancelled: bool = False) -> ArtifactOutcome:
    """classify_result with the live probe, fresh db counts and side files."""
    if probe is None:
        try:
            probe = probe_sources(artifact, "live", windows_partition)
        except Exception as e:  # a probe must never break a parse
            probe = {"sources": [], "status": None, "message": "probe failed: %s" % e}
    db_records = artifact_db_records(case_root, artifact, since=started)
    details = prefetch_failed_files(case_root, since=started) if artifact == "prefetch" else []
    return classify_result(artifact, raw_result, exc=exc, probe=probe, mode="live",
                           db_records=db_records, details=details, cancelled=cancelled)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

_store_lock = threading.Lock()


def status_path(case_root: str) -> str:
    return os.path.join(case_root, "logs", STATUS_FILE)


class ParseStatusStore:
    """<case>/logs/parse_status.json - latest outcome per artifact + run history.

    {
      "version": 1,
      "latest":  {artifact: outcome},
      "runs":    [{run_id, mode, started, finished, artifacts: [artifact,...]}],
      "pending_display": run_id | null
    }
    """

    MAX_RUNS = 25

    def __init__(self, case_root: str):
        self.case_root = case_root
        self.path = status_path(case_root)

    # -- io --------------------------------------------------------------
    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data.setdefault("latest", {})
                data.setdefault("runs", [])
                data.setdefault("pending_display", None)
                return data
        except (OSError, ValueError):
            pass
        return {"version": 1, "latest": {}, "runs": [], "pending_display": None}

    def _write(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=True)
        os.replace(tmp, self.path)

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    # -- runs ------------------------------------------------------------
    def begin_run(self, mode: str) -> str:
        run_id = "%s-%s" % (time.strftime("%Y%m%dT%H%M%S", time.gmtime()), uuid.uuid4().hex[:6])
        with _store_lock:
            data = self._read()
            data["runs"].append({"run_id": run_id, "mode": mode,
                                 "started": get_current_forensic_timestamp(),
                                 "finished": None, "artifacts": []})
            data["runs"] = data["runs"][-self.MAX_RUNS:]
            self._write(data)
        logger.info("Parse run %s started (%s)", run_id, mode)
        return run_id

    def record(self, outcome: ArtifactOutcome, run_id: Optional[str] = None) -> None:
        if run_id:
            outcome.run_id = run_id
        with _store_lock:
            data = self._read()
            data["latest"][outcome.artifact] = outcome.to_dict()
            for run in data["runs"]:
                if run.get("run_id") == outcome.run_id and outcome.artifact not in run["artifacts"]:
                    run["artifacts"].append(outcome.artifact)
            self._write(data)
        self._log(outcome)

    def finish_run(self, run_id: str, show: bool = True) -> None:
        with _store_lock:
            data = self._read()
            for run in data["runs"]:
                if run.get("run_id") == run_id:
                    run["finished"] = get_current_forensic_timestamp()
            if show:
                data["pending_display"] = run_id
            self._write(data)
        counts: Dict[str, int] = {}
        for o in self.run_outcomes(run_id):
            counts[o.status] = counts.get(o.status, 0) + 1
        logger.info("Parse run %s finished: %s", run_id,
                    ", ".join("%s=%d" % kv for kv in sorted(counts.items())) or "no artifacts")

    def take_pending(self) -> Optional[str]:
        """The run waiting to be shown, cleared as it is taken."""
        with _store_lock:
            data = self._read()
            run_id = data.get("pending_display")
            if run_id:
                data["pending_display"] = None
                self._write(data)
        return run_id

    # -- queries ---------------------------------------------------------
    def latest(self) -> Dict[str, ArtifactOutcome]:
        return {k: ArtifactOutcome.from_dict(v) for k, v in self._read()["latest"].items()}

    def outcome_for(self, artifact: str) -> Optional[ArtifactOutcome]:
        v = self._read()["latest"].get(artifact)
        return ArtifactOutcome.from_dict(v) if v else None

    def run_info(self, run_id: Optional[str]) -> Optional[Dict[str, Any]]:
        for run in self._read()["runs"]:
            if run.get("run_id") == run_id:
                return run
        return None

    def last_run(self) -> Optional[Dict[str, Any]]:
        runs = self._read()["runs"]
        return runs[-1] if runs else None

    def run_outcomes(self, run_id: Optional[str]) -> List[ArtifactOutcome]:
        latest = self._read()["latest"]
        outs = [ArtifactOutcome.from_dict(v) for v in latest.values()
                if run_id is None or v.get("run_id") == run_id]
        order = {a: i for i, a in enumerate(ARTIFACT_ORDER)}
        return sorted(outs, key=lambda o: order.get(o.artifact, 99))

    # -- log -------------------------------------------------------------
    @staticmethod
    def _log(o: ArtifactOutcome) -> None:
        sev = status_severity(o.status)
        level = {"error": logging.ERROR, "warning": logging.WARNING}.get(sev, logging.INFO)
        srcs = "; ".join("%s [%s]" % (s.get("path"), "exists" if s.get("exists") else "missing")
                         for s in o.sources_checked[:4])
        logger.log(level, "[%s] %s: %s - %d record(s) - %s%s", o.mode, o.label,
                   status_label(o.status), o.records, o.message,
                   (" | sources: " + srcs) if srcs else "")
        for d in o.details[:20]:
            logger.log(level, "[%s] %s:   %s", o.mode, o.label, d)


def record_outcomes(case_root: str, outcomes: Iterable[ArtifactOutcome], mode: str,
                    show: bool = True) -> Optional[str]:
    """One-shot: open a run, record every outcome, close it."""
    outcomes = list(outcomes)
    if not case_root or not outcomes:
        return None
    store = ParseStatusStore(case_root)
    run_id = store.begin_run(mode)
    for o in outcomes:
        store.record(o, run_id)
    store.finish_run(run_id, show=show)
    return run_id
