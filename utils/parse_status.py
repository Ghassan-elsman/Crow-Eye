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

Beside the per-artifact outcomes a run can carry SESSION ISSUES: problems that
belong to the run rather than to one artifact - the investigator picked the
second segment of an E01, the image is BitLocker-encrypted, the volume holds no
Windows installation, nothing could be extracted. ISSUE_CATALOG names every one
with what it means and what to do about it.

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
                                     "supported by the parser, or the file is corrupt."),
    ParseStatus.ACCESS_DENIED: ("Access denied", "warning", "#F59E0B",
                                "The artifact exists but Windows refused to let it be read - "
                                "Crow-Eye is not running as Administrator, or another "
                                "program holds the file. Restart Crow-Eye as Administrator "
                                "and parse it again."),
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
    # What this run added. `records` is what the run READ; of those,
    # `inserted` were new to the case and `duplicates` were already stored (a
    # re-parse of the same machine adds only what is new). `rows_before` /
    # `rows_after` are the artifact's database totals around the run. None =
    # not known (an older outcome, or a parser that does not say).
    inserted: Optional[int] = None
    duplicates: Optional[int] = None
    rows_before: Optional[int] = None
    rows_after: Optional[int] = None
    # The failure itself, and the warning / error lines the parser printed
    # (with any traceback): what the report shows under a failed row.
    error: str = ""
    log_excerpt: List[str] = field(default_factory=list)
    # Identity indexes this run added to the case database (the re-parse
    # check needs them): a change to the case, so the custody record lists it.
    indexes_created: List[str] = field(default_factory=list)

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
        out.log_excerpt = list(out.log_excerpt or [])
        out.error = out.error or ""
        return out

    def counts_text(self) -> str:
        """'12 new, 1,012 already present' / '' when not known."""
        if self.inserted is None and self.duplicates is None:
            return ""
        parts = []
        if self.inserted is not None:
            parts.append("{:,} new".format(max(0, self.inserted)))
        if self.duplicates is not None:
            parts.append("{:,} already present".format(self.duplicates))
        return ", ".join(parts)


@dataclass
class ParserResultLike:
    """The ParserResult shape, for results folded from several of them."""
    success: bool
    records_parsed: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: Optional[str] = None


# --------------------------------------------------------------------------
# Session issues
# --------------------------------------------------------------------------

ISSUE_SEVERITY_COLOR = {"error": "#EF4444", "warning": "#F59E0B", "info": "#38BDF8"}

# code -> (severity, title, what it means, what to do)
ISSUE_CATALOG: Dict[str, tuple] = {
    # the investigator's side
    "no_case": ("error", "No case is open",
                "Evidence is always parsed into a case.",
                "Open or create a case, then start again."),
    "no_partition_selected": ("error", "No partition selected",
                              "Nothing was chosen to extract from.",
                              "Tick at least one partition - normally the one marked Windows."),
    "not_an_image": ("error", "This file is not a disk image",
                     "Its content does not match any image format, whatever its extension says.",
                     "Choose the image itself (E01, VHDX, VHD, VMDK, ISO or a raw dd/img/001 file)."),
    "wrong_segment_selected": ("error", "A later segment was selected",
                               "Split images are opened from their FIRST segment; the rest are found "
                               "next to it.",
                               "Select the first segment (.E01 / .001) and keep every segment in the "
                               "same folder."),
    "case_not_writable": ("error", "The case folder cannot be written",
                          "Extracted artifacts and databases are written into the case.",
                          "Check the folder's permissions or move the case to a writable drive."),
    "low_disk_space": ("warning", "Low disk space",
                       "The case drive may not hold everything that will be extracted.",
                       "Free some space or move the case to a larger drive."),
    "image_inside_case": ("error", "The image is inside the case folder",
                          "Extraction writes into the case; reading the image from the same folder "
                          "mixes evidence with output.",
                          "Keep the image outside the case folder."),
    # the image
    "unsupported_image_format": ("error", "Unsupported image format",
                                 "Crow-Eye reads E01/Ex01, VHDX/VHD, VMDK, ISO and raw images.",
                                 "Convert the image (for example to E01 or raw) and open it again."),
    "image_unreadable": ("error", "The image could not be opened",
                         "The container did not open with any reader.",
                         "Check that the file is complete and is the image's first segment; "
                         "verify it with its acquisition hash."),
    "image_corrupted": ("error", "The image appears corrupted or truncated",
                        "Its structure is damaged, so data past the damage cannot be trusted.",
                        "Verify the image against its acquisition hash and re-acquire or re-copy it."),
    "missing_segments": ("error", "Image segments are missing",
                         "Part of the evidence is not present, so anything stored in the missing "
                         "segments cannot be read.",
                         "Copy every segment into the same folder as the first one."),
    "image_incomplete": ("warning", "The image holds only part of the disk",
                         "Its last segment is marked final, yet its chunks cover less than the "
                         "media size the image declares - the acquisition stopped early. What "
                         "is present can be parsed; anything beyond it reads as nothing.",
                         "Re-acquire if the missing range matters, and note the coverage in the "
                         "case."),
    "image_no_stored_hash": ("warning", "The image carries no acquisition hash",
                             "There is no MD5/SHA-1 inside the image to verify it against, so "
                             "its integrity rests on the hash recorded when it was acquired.",
                             "Compare the image with the hash in the acquisition notes."),
    "image_locked": ("error", "The image is in use by another program",
                     "Windows refused to share the file - typically a virtual machine that is "
                     "running from this disk.",
                     "Shut the virtual machine down (or close the program holding the file) and "
                     "try again."),
    "bitlocker_volume": ("warning", "BitLocker-encrypted volume",
                         "The volume's content is encrypted, so no artifacts can be read from it "
                         "as it is.",
                         "Decrypt the volume with its recovery key, or image it from the running "
                         "system, then parse the decrypted copy."),
    "no_filesystem": ("warning", "No readable file system",
                      "The partition did not open as NTFS or FAT.",
                      "Check the partition is the system volume; it may be unformatted, "
                      "encrypted or damaged."),
    "no_windows_partition": ("warning", "No Windows installation found",
                             "None of the selected partitions holds Windows\\System32\\config, "
                             "where the registry and most artifacts live.",
                             "Select the partition that holds Windows; data partitions carry "
                             "few Windows artifacts."),
    "dependency_missing": ("error", "A required library is missing",
                           "The component that reads this kind of image is not installed.",
                           "Install the library named below (pip install ...) and restart Crow-Eye."),
    # extraction
    "extraction_failed": ("error", "Extraction failed",
                          "The run stopped before artifacts could be collected.",
                          "See the reason below and the Image parsing log in Settings -> Logs."),
    "no_artifacts_extracted": ("error", "No artifacts were extracted",
                               "The image was read but nothing could be collected from it.",
                               "Check the issues above; most often the wrong partition is "
                               "selected or the volume is encrypted."),
    "artifacts_failed_to_extract": ("warning", "Some artifacts could not be extracted",
                                    "Those artifacts are missing from this run - they were found "
                                    "but not copied.",
                                    "See the reasons below; a damaged region of the image or a "
                                    "full case drive are the usual causes."),
    "parsing_failed": ("error", "Parsing stopped part-way",
                       "The parsers stopped before every artifact was processed; artifacts "
                       "marked Not run below were never reached.",
                       "See the error below and the Parsers log in Settings -> Logs, then "
                       "parse again."),
    "unreadable_folders": ("warning", "Some folders could not be read",
                           "The file system refused to list them - usually damaged structures "
                           "in the image. Artifacts inside them may be missing.",
                           "Verify the image against its acquisition hash; a damaged image "
                           "cannot be fully read by any tool."),
    "not_elevated": ("warning", "Crow-Eye is not running as Administrator",
                     "Live system artifacts (the MFT, the USN journal, Prefetch, SRUM, Amcache, "
                     "the Security event log, the SAM and SECURITY hives, other users' "
                     "browsers) are protected by Windows and cannot be read without "
                     "elevation. The artifacts marked Access denied below were refused for "
                     "that reason.",
                     "Restart Crow-Eye as Administrator (the button in the pop-up, or "
                     "right-click -> Run as administrator) and parse again."),
    "vss_unavailable": ("info", "Volume Shadow Copies could not be read",
                        "Older versions of files kept by Windows were not available from this image.",
                        "Nothing to do unless shadow copies matter to this case."),
    # artifacts
    "unsupported_artifact_version": ("warning", "Unsupported artifact version",
                                     "An artifact was found but its version or format is not one "
                                     "the parser reads, or the file is damaged.",
                                     "See which files below; they may come from a Windows "
                                     "version not yet supported, or be corrupt."),
    "foreign_transaction_log": ("warning", "Registry log belongs to another hive",
                                "A transaction log collected beside a registry hive was "
                                "written for a different hive, so it was not replayed. The "
                                "hive is parsed as collected and may lack its most recent "
                                "changes.",
                                "Collect the profile again with this version, which keeps "
                                "each user's hive and logs in the user's own folder."),
}


@dataclass
class SessionIssue:
    code: str
    severity: str = ""
    title: str = ""
    message: str = ""
    fix: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    at: str = ""

    def __post_init__(self):
        sev, title, meaning, fix = ISSUE_CATALOG.get(
            self.code, ("warning", self.code.replace("_", " ").capitalize(), "", ""))
        self.severity = self.severity or sev
        self.title = self.title or title
        self.message = self.message or meaning
        self.fix = self.fix or fix
        if not self.at:
            self.at = get_current_forensic_timestamp()

    @property
    def color(self) -> str:
        return ISSUE_SEVERITY_COLOR.get(self.severity, "#94A3B8")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionIssue":
        known = {k: data.get(k) for k in cls.__dataclass_fields__ if k in data}
        known.setdefault("code", "unknown")
        out = cls(**known)
        out.context = dict(out.context or {})
        return out


def make_issue(code: str, detail: str = "", **context) -> SessionIssue:
    """A catalogue issue; ``detail`` is appended to the catalogue meaning."""
    issue = SessionIssue(code=code, context=dict(context))
    if detail:
        issue.message = ("%s %s" % (issue.message, detail)).strip()
    return issue


# --------------------------------------------------------------------------
# Error text -> status
# --------------------------------------------------------------------------

_ERROR_RULES = [
    # A corrupt or dirty file is a format problem even when the message goes on
    # to suggest installing something (the SRUM dirty-state text says
    # "pip install dissect.esedb"), so it is matched before the dependency rule.
    (ParseStatus.UNSUPPORTED_FORMAT, (
        r"dirty state", r"corrupt", r"invalid registry (hive format|structure)",
        r"cannot open as registry hive", r"file too small", r"is empty \(0 bytes\)",
        r"unknown version", r"invalid signature", r"unsupported .*version")),
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


# MFT_Claw / USN_Claw return this (not 1) when they cannot open the volume
# for lack of rights, so a refused read is told apart from a crash.
EXIT_ACCESS_DENIED = 5

# Windows error codes that mean "refused", whatever the message says:
# 5 access denied, 32 sharing violation (file in use), 1314 privilege not held.
_DENIED_WINERRORS = {5, 32, 33, 1314}


def _raised_kind(exc, raw):
    """ACCESS_DENIED / FAILED from what was raised, or None to fall back to text.

    ``exc`` is the exception itself (in-process stages); ``raw`` may be the
    error dict a pool worker sends back (utils.concurrency.standalone_parsers
    ._error_dict), which keeps the type name, winerror and exit code.
    """
    if exc is not None:
        if isinstance(exc, PermissionError):
            return ParseStatus.ACCESS_DENIED
        if getattr(exc, "winerror", None) in _DENIED_WINERRORS:
            return ParseStatus.ACCESS_DENIED
        if isinstance(exc, SystemExit):
            return (ParseStatus.ACCESS_DENIED if exc.code == EXIT_ACCESS_DENIED
                    else ParseStatus.FAILED)
        return None
    if isinstance(raw, dict) and raw.get("error_type"):
        if raw.get("error_type") == "PermissionError" or raw.get("winerror") in _DENIED_WINERRORS:
            return ParseStatus.ACCESS_DENIED
        if raw.get("error_type") == "SystemExit":
            return (ParseStatus.ACCESS_DENIED if raw.get("exit_code") == EXIT_ACCESS_DENIED
                    else ParseStatus.FAILED)
    return None


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


def db_has_rows(db_path: str) -> bool:
    """Whether any table of a SQLite file holds a row - without counting them.

    For yes/no questions (may this feature open?). db_table_counts() counts
    every row of every table: 1.9 s across one case's databases, which the
    feature gate paid on the GUI thread each time a window was opened.
    """
    if not db_path or not os.path.isfile(db_path):
        return False
    conn = None
    try:
        uri = "file:%s?mode=ro" % db_path.replace("\\", "/")
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        for name in names:
            try:
                if conn.execute('SELECT 1 FROM "%s" LIMIT 1'
                                % name.replace('"', '""')).fetchone():
                    return True
            except sqlite3.Error:
                continue
        return False
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def artifact_db_paths(case_root: str, artifact: str) -> List[str]:
    files = ARTIFACTS.get(artifact, ("", ()))[1]
    base = os.path.join(case_root or "", "Target_Artifacts")
    return [os.path.join(base, f) for f in files]


def artifact_db_rowcount(case_root: str, artifact: str) -> Optional[int]:
    """Total rows in an artifact's databases now (None: no database yet).

    Taken before and after a parse, the difference is what the parse added -
    whatever the parser itself reports.
    """
    total, seen = 0, False
    for path in artifact_db_paths(case_root, artifact):
        if os.path.isfile(path):
            seen = True
            total += sum(c for c in db_table_counts(path).values() if c > 0)
    return total if seen else None


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
    denied = False
    if exists is None:
        # Not os.path.exists: it answers False for a file Windows refuses to
        # let us see, and Amcache.hve / SRUDB.dat were reported "does not
        # exist" on every unelevated run - a refusal dressed as an absence.
        # stat() of a refused file raises PermissionError; of a missing one,
        # FileNotFoundError (even inside the same protected folder).
        try:
            os.stat(path)
            exists = True
        except PermissionError:
            exists, denied = True, True
        except OSError:
            exists = False
    d = {"path": path, "exists": bool(exists)}
    if denied:
        d["denied"] = True
        note = note or "exists, but access is denied"
    if note:
        d["note"] = note
    return d


def _denied_hint(sources: List[Dict[str, Any]], what: str):
    """(ACCESS_DENIED, message) when every source exists but was refused."""
    if sources and all(s.get("denied") for s in sources):
        return (ParseStatus.ACCESS_DENIED,
                "%s exists, but Windows refused access to it - Crow-Eye is not running "
                "as Administrator." % what)
    return None, ""


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
    The hint is a neutral one (SOURCE_NOT_FOUND / FEATURE_DISABLED) or
    ACCESS_DENIED (it is there, and Windows will not let it be read): a probe
    can say why nothing could be read, never "the parser broke".

    Offline/image: `scanned_paths` are the paths ArtifactTypeDetector found
    for this type; an empty list means the evidence does not contain it.
    """
    if mode != "live":
        paths = list(scanned_paths or [])
        if artifact == "browser" and not paths and case_root:
            # Browser trees are collected as folders, one Users tree per source.
            bdir = os.path.join(case_root, "live_acquisition", "Browser")
            if os.path.isdir(bdir):
                paths = [os.path.join(r, d) for r, ds, _f in os.walk(bdir)
                         if r.count(os.sep) - bdir.count(os.sep) < 3
                         for d in ds if os.path.basename(r).lower() == "users"]
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
        status, message = _denied_hint(sources, hve)
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
        status, message = _denied_hint(sources, db)
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


def _int_or_none(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def classify_result(artifact: str, raw_result: Any = None, exc: Optional[BaseException] = None,
                    probe: Optional[Dict[str, Any]] = None, mode: str = "live",
                    db_records: Optional[int] = None, details: Optional[List[str]] = None,
                    cancelled: bool = False, rows_before: Optional[int] = None,
                    rows_after: Optional[int] = None,
                    log_excerpt: Optional[List[str]] = None) -> ArtifactOutcome:
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
    inserted = duplicates = None
    traceback_text = ""
    indexes = []
    if isinstance(raw_result, dict):
        indexes = [str(x) for x in (raw_result.get("indexes_created") or [])]

    r = raw_result
    # MFT / USN come back as {"exit_code": n, records, inserted, duplicates}:
    # the exit code decides success, the counts say what was added.
    if (isinstance(r, dict) and "exit_code" in r and "success" not in r
            and "error" not in r and "traceback" not in r):
        counts = r
        r = r.get("exit_code")
        inserted = _int_or_none(counts.get("inserted"))
        duplicates = _int_or_none(counts.get("duplicates"))
        reported = _records_from(counts.get("records"))
    if r is not None and hasattr(r, "records_parsed") and hasattr(r, "success"):
        success = bool(r.success)
        reported = int(getattr(r, "records_parsed", 0) or 0)
        errors += _texts(getattr(r, "errors", None))
        warnings += _texts(getattr(r, "warnings", None))
        explicit = getattr(r, "status", None)
        inserted = _int_or_none(getattr(r, "inserted", None))
        duplicates = _int_or_none(getattr(r, "duplicates", None))
    elif isinstance(r, dict):
        explicit = r.get("status")
        if "success" in r:
            success = bool(r.get("success"))
        errors += _texts(r.get("error")) + _texts(r.get("errors"))
        warnings += _texts(r.get("warnings"))
        if r.get("traceback") and "success" not in r:
            success = False
        traceback_text = str(r.get("traceback") or "")
        reported = _records_from(r.get("records"))
        if not reported:
            reported = _records_from(r.get("statistics"))
        inserted = _int_or_none(r.get("inserted"))
        duplicates = _int_or_none(r.get("duplicates"))
    elif isinstance(r, bool):
        success = r
    elif isinstance(r, int) and not isinstance(r, bool):
        success = (r == 0)
        if r == EXIT_ACCESS_DENIED:
            errors.append("Parser exited with code %d: access denied - run Crow-Eye as "
                          "Administrator" % r)
        elif r != 0:
            errors.append("Parser exited with code %d" % r)
    # str (db path) / None: nothing to read - the probe and the db decide.

    if exc is not None:
        success = False
        errors.insert(0, "%s: %s" % (type(exc).__name__, exc))

    # What was raised says more than its text: a PermissionError reads
    # "[Errno 13] ..." in one parser and a translated message in another, and a
    # SystemExit carries only a number.
    kind = _raised_kind(exc, r)

    # What this run added. The parser's own count when it gives one; else the
    # artifact's database totals before and after the run.
    delta = (rows_after - rows_before) if (rows_after is not None and rows_before is not None) else None
    if inserted is None and delta is not None:
        inserted = max(0, delta)
    if not reported and inserted is not None and duplicates is not None:
        reported = inserted + duplicates
    if duplicates is None and reported and inserted is not None and reported >= inserted:
        duplicates = reported - inserted
    # `records` is what this run READ - no longer the database total, which
    # grew with every run ("MFT 19,090,321" was four tables summed).
    if reported:
        records = reported
    elif inserted is not None:
        records = inserted
    else:
        records = db_records or 0
    probe_hint = probe.get("status")
    probe_msg = probe.get("message", "")
    excerpt = list(log_excerpt or [])
    if traceback_text and not any("Traceback" in ln for ln in excerpt):
        excerpt += traceback_text.strip().splitlines()[-25:]

    def out(status, message):
        return ArtifactOutcome(artifact=artifact, mode=mode, status=status,
                               records=records, message=message,
                               sources_checked=sources,
                               details=details + ["Warning: %s" % w for w in warnings[:10]]
                               + ["Error: %s" % e for e in errors[1:10]],
                               inserted=inserted, duplicates=duplicates,
                               rows_before=rows_before, rows_after=rows_after,
                               error=(errors[0] if errors else ""),
                               log_excerpt=excerpt[-60:], indexes_created=indexes)

    def counted(text):
        """'1,024 record(s) read: 0 new, 1,024 already in the case.'"""
        if inserted is None:
            return text
        if duplicates is None:
            return "{:,} record(s) read: {:,} new.".format(records, inserted)
        return "{:,} record(s) read: {:,} new, {:,} already in the case.".format(
            records, inserted, duplicates)

    if explicit in ParseStatus.ALL:
        return out(explicit, (errors[0] if errors else probe_msg) or STATUS_INFO[explicit][3])

    if cancelled:
        return out(ParseStatus.NOT_RUN, "Cancelled before this artifact finished.")

    if probe_hint == ParseStatus.NOT_RUN and records == 0:
        return out(ParseStatus.NOT_RUN, probe_msg)

    # Nothing produced and the probe already knows why: that is the answer,
    # whatever error text the parser threw on its way out.
    if records == 0 and probe_hint in (ParseStatus.SOURCE_NOT_FOUND,
                                       ParseStatus.FEATURE_DISABLED,
                                       ParseStatus.ACCESS_DENIED):
        return out(probe_hint, probe_msg)

    if errors or success is False:
        text = errors[0] if errors else "The parser reported failure without a message."
        if kind is not None:
            status = kind
        else:
            status = classify_error_text(text) if errors else ParseStatus.FAILED
        if records > 0:
            return out(ParseStatus.PARTIAL,
                       "%s, but: %s" % (counted("{:,} record(s) extracted.".format(records))
                                        .rstrip("."), text))
        return out(status, text)

    if records > 0:
        msg = counted("{:,} record(s) extracted.".format(records))
        if details:
            msg += " %d item(s) skipped - see details." % len(details)
        return out(ParseStatus.PARSED, msg)

    # Nothing new, and the database already holds what an earlier parse
    # wrote: a re-parse that found nothing to add, not a missing output.
    # (ShimCache returned None, inserted no row, left the file untouched - and
    # was reported FAILED, "the parser produced no output database".)
    # Only when the parser SAID it succeeded: every live parser returns a
    # result now, so a bare None is a parser that bailed out - reading that as
    # "no new rows" because an earlier run's database exists would hide the
    # failure (review, round 17).
    if rows_after and (delta is None or delta <= 0) and success is True:
        return out(ParseStatus.PARSED,
                   "No new rows: the database already holds {:,} from an earlier parse.".format(rows_after))

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
        out = []
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                ln = ln.rstrip("\r\n")
                if not ln.strip():
                    continue
                name, _tab, reason = ln.partition("\t")
                if reason.startswith("partly parsed"):
                    out.append("Prefetch file only partly parsed: %s (%s)" % (
                        name.strip(), reason[len("partly parsed - "):] or "body unreadable"))
                else:
                    out.append("Unsupported or corrupt prefetch file skipped: %s%s" % (
                        name.strip(), (" (%s)" % reason.strip()) if reason.strip() else ""))
        return out
    except OSError:
        return []


def collect_live_outcome(artifact: str, case_root: str, windows_partition: str,
                         raw_result: Any = None, exc: Optional[BaseException] = None,
                         started: Optional[float] = None, probe: Optional[dict] = None,
                         cancelled: bool = False, rows_before: Optional[int] = None,
                         log_excerpt: Optional[List[str]] = None) -> ArtifactOutcome:
    """classify_result with the live probe, fresh db counts and side files.

    ``rows_before``: the artifact's database total taken before the run
    (artifact_db_rowcount); with the total after, it says what the run added.
    ``log_excerpt``: the warning / error lines the parser printed.
    """
    if probe is None:
        try:
            probe = probe_sources(artifact, "live", windows_partition)
        except Exception as e:  # a probe must never break a parse
            probe = {"sources": [], "status": None, "message": "probe failed: %s" % e}
    db_records = artifact_db_records(case_root, artifact, since=started)
    details = prefetch_failed_files(case_root, since=started) if artifact == "prefetch" else []
    if details and not db_records and exc is None and not cancelled:
        # Every .pf failed: an unsupported format, as the offline path says -
        # not "no records", which reads as if the folder were empty.
        raw_result = {"status": ParseStatus.UNSUPPORTED_FORMAT,
                      "errors": ["%d prefetch file(s) use a version or format the parser does "
                                 "not support, or are corrupt" % len(details)]}
    rows_after = artifact_db_rowcount(case_root, artifact) if rows_before is not None else None
    return classify_result(artifact, raw_result, exc=exc, probe=probe, mode="live",
                           db_records=db_records, details=details, cancelled=cancelled,
                           rows_before=rows_before, rows_after=rows_after,
                           log_excerpt=log_excerpt)


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
      "runs":    [{run_id, mode, started, finished, artifacts: [artifact,...],
                   outcomes: {artifact: outcome}, issues: [issue], source: {...}}],
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
    def begin_run(self, mode: str, source: Optional[Dict[str, Any]] = None) -> str:
        run_id = "%s-%s" % (time.strftime("%Y%m%dT%H%M%S", time.gmtime()), uuid.uuid4().hex[:6])
        with _store_lock:
            data = self._read()
            data["runs"].append({"run_id": run_id, "mode": mode,
                                 "started": get_current_forensic_timestamp(),
                                 "finished": None, "artifacts": [], "outcomes": {},
                                 "issues": [], "source": dict(source or {})})
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
                if run.get("run_id") == outcome.run_id:
                    if outcome.artifact not in run["artifacts"]:
                        run["artifacts"].append(outcome.artifact)
                    # the run keeps its own copy: "latest" moves on with the next run
                    run.setdefault("outcomes", {})[outcome.artifact] = outcome.to_dict()
            self._write(data)
        self._log(outcome)

    def add_issue(self, run_id: str, issue: SessionIssue) -> None:
        with _store_lock:
            data = self._read()
            for run in data["runs"]:
                if run.get("run_id") == run_id:
                    run.setdefault("issues", []).append(issue.to_dict())
            self._write(data)
        level = {"error": logging.ERROR, "warning": logging.WARNING}.get(issue.severity, logging.INFO)
        ctx = ", ".join("%s=%s" % kv for kv in sorted(issue.context.items()))
        logger.log(level, "[issue] %s: %s%s", issue.title, issue.message,
                   (" (%s)" % ctx) if ctx else "")

    def set_source(self, run_id: str, source: Dict[str, Any]) -> None:
        with _store_lock:
            data = self._read()
            for run in data["runs"]:
                if run.get("run_id") == run_id:
                    run.setdefault("source", {}).update(source or {})
            self._write(data)

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

    def modes(self) -> set:
        """Every mode this case has been parsed in ("live", "offline", "image")."""
        return {r.get("mode") for r in self._read()["runs"] if r.get("mode")}

    def last_run(self) -> Optional[Dict[str, Any]]:
        runs = self._read()["runs"]
        return runs[-1] if runs else None

    def run_issues(self, run_id: Optional[str]) -> List[SessionIssue]:
        run = self.run_info(run_id) if run_id else None
        return [SessionIssue.from_dict(i) for i in (run or {}).get("issues", [])]

    def run_outcomes(self, run_id: Optional[str]) -> List[ArtifactOutcome]:
        data = self._read()
        run = None
        if run_id:
            run = next((r for r in data["runs"] if r.get("run_id") == run_id), None)
        if run is not None and run.get("outcomes"):
            values = list(run["outcomes"].values())
        else:
            # runs written before per-run outcomes existed
            values = [v for v in data["latest"].values()
                      if run_id is None or v.get("run_id") == run_id]
        outs = [ArtifactOutcome.from_dict(v) for v in values]
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
        if o.log_excerpt and sev in ("error", "warning"):
            logger.log(level, "[%s] %s:   log excerpt (%d line(s)):", o.mode, o.label,
                       len(o.log_excerpt))
            for ln in o.log_excerpt[-25:]:
                logger.log(level, "[%s] %s:     %s", o.mode, o.label, ln)


def record_outcomes(case_root: str, outcomes: Iterable[ArtifactOutcome], mode: str,
                    show: bool = True, issues: Optional[Iterable[SessionIssue]] = None,
                    source: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """One-shot: open a run, record every outcome and session issue, close it."""
    outcomes = list(outcomes)
    issues = list(issues or [])
    if not case_root or not (outcomes or issues):
        return None
    store = ParseStatusStore(case_root)
    run_id = store.begin_run(mode, source=source)
    for o in outcomes:
        store.record(o, run_id)
    for i in issues:
        store.add_issue(run_id, i)
    store.finish_run(run_id, show=show)
    return run_id


_VERSION_TEXT = re.compile(r"unknown version|unsupported .*version|invalid signature|"
                           r"bad signature|not a valid|corrupt|dirty state|"
                           r"invalid registry (hive format|structure)|file too small", re.I)


def version_problems(texts: Iterable[str]) -> List[str]:
    """The texts that say a file's version/format is not readable."""
    return [t for t in texts if t and _VERSION_TEXT.search(t)]
