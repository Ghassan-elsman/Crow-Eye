"""
Plain-English rendering helpers — everything a manager or HR reviewer sees
goes through here so wording stays consistent and non-technical.
"""

import ntpath
import re
from datetime import datetime
from typing import Optional

from uba.utils.timeparse import to_datetime

# Known-folder labels a non-technical reader understands.
_FOLDER_LABELS = [
    (re.compile(r"\$recycle\.bin", re.I), "the Recycle Bin"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]desktop", re.I), "the Desktop"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]documents", re.I), "the Documents folder"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]downloads", re.I), "the Downloads folder"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]pictures", re.I), "the Pictures folder"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]videos", re.I), "the Videos folder"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]music", re.I), "the Music folder"),
    (re.compile(r"[\\/]users[\\/][^\\/]+[\\/]onedrive", re.I), "the OneDrive folder"),
    (re.compile(r"[\\/]windows[\\/]winsxs", re.I), "the Windows system area"),
    (re.compile(r"[\\/]windows[\\/]", re.I), "the Windows system area"),
    (re.compile(r"[\\/]program files( \(x86\))?[\\/]", re.I), "the installed-programs area"),
    (re.compile(r"[\\/]programdata[\\/]", re.I), "a shared application-data area"),
    (re.compile(r"[\\/]appdata[\\/]", re.I), "an application data area"),
    (re.compile(r"[\\/]temp[\\/]|[\\/]tmp[\\/]", re.I), "a temporary folder"),
]

_USER_AREA_RE = re.compile(
    r"[\\/]users[\\/][^\\/]+[\\/](desktop|documents|downloads|pictures|videos|music|onedrive)",
    re.I)

# Common NTFS 8.3 short names -> their long form, so reconstructed paths (which
# use short names) read as real folders instead of "unknown".
_SHORT_NAME_MAP = {
    "PROGRA~1": "Program Files", "PROGRA~2": "Program Files (x86)",
    "PROGRA~3": "ProgramData", "PROGRAMD~1": "ProgramData",
    "APPLIC~1": "Application Data", "COMMON~1": "Common Files",
    "DOCUME~1": "Documents", "DOWNLO~1": "Downloads", "MICROS~1": "Microsoft",
    "WINDOW~1": "Windows", "SYSTEM~1": "System", "DEFAUL~1": "Default",
}
_NTFS_META_RE = re.compile(r"[\\/]\$[a-z]", re.I)


def _normalize_path(path: str) -> str:
    """Reconstructed paths look like './Users/Gass3/APPLIC~1'. Strip the leading
    './', unify slashes and expand common 8.3 short names."""
    p = str(path).strip().lstrip(".").replace("\\", "/")
    parts = [_SHORT_NAME_MAP.get(seg.upper(), seg) for seg in p.split("/") if seg]
    return "/".join(parts)


def folder_label(path: Optional[str]) -> str:
    """Map a filesystem path onto the folder the reader should see.

    Prefers a friendly known-folder name; otherwise returns the **real**
    folder path (8.3-expanded, truncated) rather than 'unknown location'.
    """
    if not path or str(path).strip() in (".", "", "/"):
        return "the drive root"
    raw = str(path)
    if _NTFS_META_RE.search(raw) or raw.lstrip("./").startswith("$"):
        return "the NTFS system area"
    norm = _normalize_path(raw)          # e.g. "Users/Gass3/Application Data/..."
    slashed = "/" + norm                 # anchor so the [\\/] patterns match
    for pattern, label in _FOLDER_LABELS:
        if pattern.search(slashed):
            return label
    # Fallback: show the actual folder (drop the filename, cap depth ~4).
    parts = norm.split("/")
    if len(parts) <= 1:
        return "the drive root"          # bare filename — folder not recorded
    parts = parts[:-1]                    # directory portion
    if len(parts) > 4:
        parts = parts[-4:]
    return "/".join(parts)


def is_user_document_area(path: Optional[str]) -> bool:
    return bool(path) and bool(_USER_AREA_RE.search(str(path)))


def app_display_name(path_or_name: Optional[str]) -> str:
    """'C:\\...\\WINWORD.EXE' / weird UserAssist entries -> 'winword'."""
    if not path_or_name:
        return "an unknown program"
    name = str(path_or_name)
    # UserAssist paths often look like '{GUID}\\app.exe' or package ids.
    name = ntpath.basename(name.replace("/", "\\"))
    if "!" in name:                       # UWP AppUserModelId
        name = name.split("!")[-1] or name
    if name.lower().endswith((".exe", ".lnk", ".msi")):
        name = name[:-4]
    return name or "an unknown program"


def humanize_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "an unknown amount of data"
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "{:.0f} {}".format(n, unit) if unit == "bytes" else "{:.1f} {}".format(n, unit)
        n /= 1024.0
    return "a very large amount of data"


def humanize_duration(seconds) -> str:
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return "an unknown duration"
    if seconds < 60:
        return "{} seconds".format(seconds)
    if seconds < 3600:
        return "{} minutes".format(seconds // 60)
    return "{:.1f} hours".format(seconds / 3600.0)


def span_phrase(ts_start: Optional[str], ts_end: Optional[str]) -> str:
    """'within 4 minutes' phrasing for burst descriptions."""
    a, b = to_datetime(ts_start), to_datetime(ts_end)
    if not a or not b or b <= a:
        return ""
    return "within {}".format(humanize_duration((b - a).total_seconds()))


def day_phrase(ts: Optional[str]) -> str:
    dt = to_datetime(ts)
    if not dt:
        return ""
    return dt.strftime("%A, %B %d %Y")
