"""
Browser_Claw - Crow-Eye browser forensics parser.

Parses Chromium-family (Chrome, Edge, Brave, Chromium, Opera, Vivaldi, ...),
Gecko (Firefox), and Electron-app browser artifacts into a single case
database (browser_analysis.db), and exports large binary payloads (HTTP cache
bodies, IndexedDB blobs) into the case folder for full extraction.

Design notes (why the shape is what it is):

  * One core, three phases. parse_browser_data() takes an optional
    ``source_roots`` list of ProfileSource. When it is None we DISCOVER live
    profiles ourselves; the offline importer and image-parsing phases build the
    same ProfileSource list from a collected tree and hand it in, so the core
    never changes.

  * Every row carries provenance (browser, vendor, user_name, sid, profile,
    source_path, parsed_at). That is what lets one collected copy from any user
    or profile be told apart downstream.

  * Secrets are NEVER decrypted here. Cookie values and saved passwords are
    stored as base64 of the raw encrypted blob together with the encryption
    scheme (v10 / v20 / dpapi / plaintext) and the browser's DPAPI-wrapped
    master key (browser_metadata.os_crypt_key_b64), so a later, separately
    audited step can decrypt them. No plaintext credential ever lands in the
    case DB.

  * Live SQLite databases are read from a COPY (plus their -wal/-journal/-shm
    sidecars) opened read-only, so the evidence file is never touched and
    uncommitted WAL rows are still seen. Locked files (Cookies while the
    browser runs) fall back to the raw backup-semantics copy used for SRUM.

  * Output stays ASCII (see [Browser] prefixes) because parsers run in-process
    under the PyQt app on a cp1252 console; a stray non-ASCII byte would abort
    the whole parse.

Author: Ghassan Elsman
"""

import base64
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# --- Crow-Eye shared utilities (reuse, do not reinvent) --------------------
# Make the project root importable whether we are run in-process (already on
# sys.path) or as a standalone script from Artifacts_Collectors/.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in os.sys.path:
    os.sys.path.insert(0, _PROJECT_ROOT)

from utils.time_utils import (  # noqa: E402
    format_forensic_timestamp,
    get_current_forensic_timestamp,
    webkit_to_datetime,
    prtime_to_datetime,
    unix_timestamp_to_datetime,
)

try:
    from utils.raw_file_copy import copy_locked_file_raw  # noqa: E402
except Exception:  # pragma: no cover - the raw copy helper is Windows-only
    copy_locked_file_raw = None

logger = logging.getLogger(__name__)

# Optional decompressors. All three ship in the Crow-Eye venv; guard the
# imports so a trimmed environment degrades gracefully instead of aborting.
try:
    from dissect.util.compression import snappy as _snappy
except Exception:  # pragma: no cover
    _snappy = None
try:
    from dissect.util.compression import lz4 as _lz4
except Exception:  # pragma: no cover
    _lz4 = None
try:
    import brotli as _brotli
except Exception:  # pragma: no cover
    _brotli = None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# Chromium vendors we probe explicitly, as (browser_label, relative sub-path
# below the user's AppData\Local OR AppData\Roaming that contains "User Data").
# The glob fallback below catches anything not listed here, so this table is a
# convenience for clean labelling, not the limit of what we find.
CHROMIUM_VENDORS = [
    ("Chrome", "Local", r"Google\Chrome"),
    ("Chrome Beta", "Local", r"Google\Chrome Beta"),
    ("Chrome Dev", "Local", r"Google\Chrome Dev"),
    ("Chrome SxS", "Local", r"Google\Chrome SxS"),
    ("Chrome for Testing", "Local", r"Google\Chrome for Testing"),
    ("Edge", "Local", r"Microsoft\Edge"),
    ("Edge Beta", "Local", r"Microsoft\Edge Beta"),
    ("Edge Dev", "Local", r"Microsoft\Edge Dev"),
    ("Edge Canary", "Local", r"Microsoft\Edge SxS"),
    ("Brave", "Local", r"BraveSoftware\Brave-Browser"),
    ("Brave Beta", "Local", r"BraveSoftware\Brave-Browser-Beta"),
    ("Chromium", "Local", r"Chromium"),
    ("Vivaldi", "Local", r"Vivaldi"),
    ("Opera", "Roaming", r"Opera Software\Opera Stable"),
    ("Opera GX", "Roaming", r"Opera Software\Opera GX Stable"),
    ("Opera Crypto", "Roaming", r"Opera Software\Opera Crypto Stable"),
    ("Yandex", "Local", r"Yandex\YandexBrowser"),
    ("Epic", "Local", r"Epic Privacy Browser"),
    ("CocCoc", "Local", r"CocCoc\Browser"),
    ("Naver Whale", "Local", r"Naver\Naver Whale"),
    ("360 Chrome", "Local", r"360Chrome\Chrome"),
    ("Comodo Dragon", "Local", r"Comodo\Dragon"),
    ("Torch", "Local", r"Torch"),
    ("UCBrowser", "Local", r"UCBrowser"),
    ("Maxthon", "Local", r"Maxthon\Application"),
]

# Electron chat/comms apps we always LABEL nicely when found. Discovery is not
# limited to this list: the adaptive scan below finds ANY app that keeps a
# Chromium `Local Storage\leveldb` or `IndexedDB` store. This map only supplies
# a friendly name for the common ones. Path is relative to AppData\Roaming.
ELECTRON_APPS = [
    ("Slack", r"Slack"),
    ("Discord", r"discord"),
    ("Discord Canary", r"discordcanary"),
    ("Discord PTB", r"discordptb"),
    ("Microsoft Teams", r"Microsoft\Teams"),
    ("Microsoft Teams (new)", r"Microsoft\MSTeams"),
    ("Signal", r"Signal"),
    ("WhatsApp", r"WhatsApp"),
    ("Telegram Desktop", r"Telegram Desktop"),
    ("Element", r"Element"),
    ("Skype", r"Microsoft\Skype for Desktop"),
    ("Notion", r"Notion"),
    ("Obsidian", r"obsidian"),
    ("VS Code", r"Code"),
    ("Claude", r"Claude"),
]

# The real-browser roots the adaptive Electron scan must NOT re-list (they are
# already covered as Chromium/Gecko). Compared case-insensitively by folder name.
_ELECTRON_DENY = {
    "google", "microsoft", "bravesoftware", "chromium", "vivaldi",
    "opera software", "yandex", "mozilla", "epic privacy browser", "coccoc",
    "naver", "360chrome", "comodo", "packages", "temp", "microsoft edge",
}

# Profile directory names inside a Chromium "User Data" root. `Snapshots\*`
# holds versioned mini-profiles (Edge) each with their own Default.
CHROMIUM_PROFILE_GLOBS = ["Default", "Profile *", "System Profile", "Guest Profile"]

# Gecko (Firefox-family) vendors, relative to AppData\Roaming; each holds a
# `Profiles` dir and a `profiles.ini`. The Local cache root mirrors the path.
GECKO_VENDORS = [
    ("Firefox", r"Mozilla\Firefox"),
    ("LibreWolf", r"librewolf"),
    ("LibreWolf", r"LibreWolf"),
    ("Waterfox", r"Waterfox"),
    ("Pale Moon", r"Moonchild Productions\Pale Moon"),
    ("SeaMonkey", r"Mozilla\SeaMonkey"),
    ("Tor Browser", r"Mozilla\Firefox"),
]


def _native(rel):
    """A table path in this OS's separators.

    The tables are written the way Windows shows them. On Linux - parsing a
    collected tree or an image's extracted files - os.path.join kept
    "Mozilla\\Firefox" as ONE folder name that never exists, so no Firefox
    profile was ever found there, and named Chromium vendors only turned up
    through the glob fallback, under the wrong label.
    """
    return os.path.join(*rel.split("\\"))


CHROMIUM_VENDORS = [(b, base, _native(rel)) for b, base, rel in CHROMIUM_VENDORS]
ELECTRON_APPS = [(app, _native(rel)) for app, rel in ELECTRON_APPS]
GECKO_VENDORS = [(b, _native(rel)) for b, rel in GECKO_VENDORS]


@dataclass
class ProfileSource:
    """One browser profile to parse.

    ``root_dir`` is the profile directory itself (the folder holding History,
    Cookies, Preferences, ...). For Gecko it is the ``Profiles\\<name>`` dir;
    for Electron it is the app root that holds Local Storage / IndexedDB.
    ``local_state_path`` (Chromium only) points at the sibling ``Local State``
    file that carries the DPAPI-wrapped master key.
    """

    browser: str
    vendor: str  # "chromium" | "gecko" | "electron"
    user_name: str
    sid: str
    profile: str
    root_dir: str
    local_state_path: Optional[str] = None
    cache_dir: Optional[str] = None  # Gecko keeps its cache under LocalAppData


def _live_user_roots() -> List[Tuple[str, str]]:
    """Return [(user_name, profile_folder), ...] for every user on this host.

    Uses the same machine-wide ProfileList that the rest of Crow-Eye reads, so
    a multi-user box is covered, not just the analyst's own account.
    """
    roots: List[Tuple[str, str]] = []
    seen = set()
    try:
        from Artifacts_Collectors.user_identity import _profile_list_live
        for sid, path in _profile_list_live().items():
            if path and os.path.isdir(path):
                name = os.path.basename(path.rstrip("\\/")) or path
                roots.append((name, path))
                seen.add(os.path.normcase(path))
    except Exception as exc:
        logger.debug("ProfileList discovery failed: %s", exc)

    # Fallback / supplement: enumerate C:\Users directly so we never miss a
    # profile whose ProfileList entry is absent.
    users_dir = os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "Users")
    try:
        for entry in os.listdir(users_dir):
            full = os.path.join(users_dir, entry)
            if not os.path.isdir(full):
                continue
            if entry.lower() in ("public", "default", "default user", "all users"):
                continue
            if os.path.normcase(full) not in seen:
                roots.append((entry, full))
    except Exception as exc:
        logger.debug("Users dir enumeration failed: %s", exc)
    return roots


def _sid_for_path(user_path: str) -> str:
    """Best-effort SID lookup for a user profile folder (live only)."""
    try:
        from Artifacts_Collectors.user_identity import _profile_list_live
        target = os.path.normcase(user_path.rstrip("\\/"))
        for sid, path in _profile_list_live().items():
            if os.path.normcase((path or "").rstrip("\\/")) == target:
                return sid
    except Exception:
        pass
    return ""


def _chromium_profiles_in(user_data_dir: str, browser: str, user_name: str,
                          sid: str) -> List[ProfileSource]:
    """Enumerate every profile directory inside a Chromium 'User Data' root."""
    out: List[ProfileSource] = []
    local_state = os.path.join(user_data_dir, "Local State")
    local_state = local_state if os.path.isfile(local_state) else None
    # Normal profiles, plus Snapshots\<version>\<profile> (Edge keeps a full
    # mini-profile tree per browser version under Snapshots).
    search_globs = [os.path.join(user_data_dir, p) for p in CHROMIUM_PROFILE_GLOBS]
    search_globs += [os.path.join(user_data_dir, "Snapshots", "*", p)
                     for p in CHROMIUM_PROFILE_GLOBS]
    for pattern in search_globs:
        for prof_dir in glob.glob(pattern):
            if not os.path.isdir(prof_dir):
                continue
            # A real profile has a History or Preferences file; skip stray dirs.
            if not (os.path.isfile(os.path.join(prof_dir, "History"))
                    or os.path.isfile(os.path.join(prof_dir, "Preferences"))):
                continue
            # Label a snapshot profile distinctly so two do not look the same.
            rel = os.path.relpath(prof_dir, user_data_dir).replace("\\", "/")
            profile_label = os.path.basename(prof_dir) if "Snapshots/" not in rel else rel
            out.append(ProfileSource(
                browser=browser, vendor="chromium", user_name=user_name,
                sid=sid, profile=profile_label, root_dir=prof_dir,
                local_state_path=local_state))
    return out


def _gecko_profile_dirs(vendor_root: str, remap_abs=None):
    """Yield (profile_name, profile_dir) for a Gecko vendor root.

    Reads `profiles.ini` so profiles that live OUTSIDE the default `Profiles\\`
    directory (a `Path=` with `IsRelative=0`) are found, then falls back to a
    plain glob of `Profiles\\*`.

    ``remap_abs`` is for offline / image trees: an absolute ``Path=`` names a
    folder on the EVIDENCE machine (``C:\\Users\\Ann\\...``), and reading it as
    written would open the analyst's own disk. The callable maps it onto the
    collected tree, or returns None to drop it.
    """
    seen = set()
    ini = os.path.join(vendor_root, "profiles.ini")
    if os.path.isfile(ini):
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read(ini, encoding="utf-8")
            for section in cp.sections():
                if not section.lower().startswith("profile"):
                    continue
                path = cp.get(section, "Path", fallback="")
                if not path:
                    continue
                is_rel = cp.get(section, "IsRelative", fallback="1").strip() == "1"
                if is_rel:
                    prof_dir = os.path.join(vendor_root, path.replace("/", "\\"))
                elif remap_abs is not None:
                    prof_dir = remap_abs(path)
                    if not prof_dir:
                        continue
                else:
                    prof_dir = path
                if os.path.isdir(prof_dir):
                    key = os.path.normcase(prof_dir)
                    if key not in seen:
                        seen.add(key)
                        yield os.path.basename(prof_dir.rstrip("\\/")), prof_dir
        except Exception as exc:
            logger.debug("profiles.ini parse failed for %s: %s", vendor_root, exc)
    for prof_dir in glob.glob(os.path.join(vendor_root, "Profiles", "*")):
        if os.path.isdir(prof_dir):
            key = os.path.normcase(prof_dir)
            if key not in seen:
                seen.add(key)
                yield os.path.basename(prof_dir), prof_dir


def discover_live_profiles() -> List[ProfileSource]:
    """Find every parseable browser profile on the running system.

    Smart and adaptive (requirement #4): probes the known vendor table AND a
    glob fallback that treats any ``*\\User Data\\<profile>\\History`` as a
    Chromium install, so CEF / Copilot / EdgeWebView and future vendors are
    caught without being named.
    """
    roots = [(name, path, _sid_for_path(path)) for name, path in _live_user_roots()]
    return discover_profiles(roots)


# Folders under a Users directory that are not people.
_NON_USER_DIRS = {"public", "default", "default user", "all users", "defaultapppool"}


def offline_user_roots(users_dir: str) -> List[Tuple[str, str]]:
    """[(user_name, profile_folder)] for a COLLECTED ``Users`` directory.

    The user name is the folder name and nothing else - the same strict rule
    ``user_identity.identify_ntuser_hive`` uses. Nothing here consults this
    machine: an offline tree is somebody else's computer.
    """
    out: List[Tuple[str, str]] = []
    try:
        for entry in sorted(os.listdir(users_dir)):
            full = os.path.join(users_dir, entry)
            if os.path.isdir(full) and entry.lower() not in _NON_USER_DIRS:
                out.append((entry, full))
    except OSError as exc:
        logger.debug("Users dir enumeration failed for %s: %s", users_dir, exc)
    return out


def _evidence_path_remapper(users_dir: str):
    """Map an absolute evidence path (``C:\\Users\\Ann\\...``) onto a collected
    ``users_dir``; None when the path is not under a Users folder."""
    def remap(path: str) -> Optional[str]:
        norm = path.replace("/", "\\")
        low = norm.lower()
        idx = low.find("\\users\\")
        if idx < 0:
            return None
        # The ini is evidence: a "..\.." in it must not walk the parse out of
        # the collected tree and onto the analyst's own disk.
        base = os.path.normpath(users_dir)
        target = os.path.normpath(os.path.join(base, norm[idx + len("\\users\\"):]))
        if not os.path.normcase(target).startswith(os.path.normcase(base) + os.sep):
            return None
        return target
    return remap


def discover_offline_profiles(users_dirs, sid_map=None) -> List[ProfileSource]:
    """Find every browser profile in one or more COLLECTED ``Users`` trees.

    ``users_dirs``: paths of collected ``Users`` folders (from an image or a
    collected folder - the layout below them is the Windows one).
    ``sid_map``: optional ``{profile folder name (lower-case): SID}`` built
    from the evidence's own SOFTWARE hive. Absent a mapping the SID stays
    empty; it is never looked up on the analyst's machine.
    """
    sid_map = {k.lower(): v for k, v in (sid_map or {}).items()}
    roots = []
    remaps = {}
    for users_dir in users_dirs:
        for name, path in offline_user_roots(users_dir):
            roots.append((name, path, sid_map.get(name.lower(), "")))
            remaps[os.path.normcase(path)] = _evidence_path_remapper(users_dir)
    return discover_profiles(roots, remaps=remaps)


def discover_profiles(user_roots, remaps=None) -> List[ProfileSource]:
    """Walk ``[(user_name, user_folder, sid)]`` for browser profiles.

    The one discovery used by the live parse and by offline / image trees:
    everything below a user folder is relative, so the same walk serves both.
    ``remaps`` maps a user folder to the callable that turns an absolute
    evidence path (Firefox ``profiles.ini`` ``IsRelative=0``) into the
    collected tree; live users have none and use the path as written.
    """
    sources: List[ProfileSource] = []
    seen_roots = set()
    remaps = remaps or {}

    def _add(ps: ProfileSource):
        # By REAL path: Local\Application Data is a junction back to Local, and
        # a glob through it found the same profile a second time.
        key = os.path.normcase(os.path.realpath(ps.root_dir))
        if key not in seen_roots:
            seen_roots.add(key)
            sources.append(ps)

    for user_name, user_path, sid in user_roots:
        remap_abs = remaps.get(os.path.normcase(user_path))
        appdata = {
            "Local": os.path.join(user_path, "AppData", "Local"),
            "Roaming": os.path.join(user_path, "AppData", "Roaming"),
        }

        # 1) Named Chromium vendors.
        for browser, base, rel in CHROMIUM_VENDORS:
            user_data = os.path.join(appdata[base], rel, "User Data")
            if os.path.isdir(user_data):
                for ps in _chromium_profiles_in(user_data, browser, user_name, sid):
                    _add(ps)

        # 2) Glob fallback: any User Data\<profile>\History anywhere under
        #    AppData\Local, zero to two vendor folders deep (Google\Chrome,
        #    CEF, or a loose tree with none), that we did not already label.
        local_root = appdata["Local"]
        try:
            hists = []
            for depth in ((), ("*",), ("*", "*")):
                hists += glob.glob(os.path.join(local_root, *depth, "User Data", "*", "History"))
            for hist in hists:
                prof_dir = os.path.dirname(hist)
                if os.path.normcase(os.path.realpath(prof_dir)) in seen_roots:
                    continue
                user_data = os.path.dirname(prof_dir)
                # Label from the vendor folder above User Data.
                vendor_folder = os.path.basename(os.path.dirname(user_data))
                if vendor_folder.lower() == "local":
                    vendor_folder = "Chromium"
                for ps in _chromium_profiles_in(user_data, vendor_folder, user_name, sid):
                    _add(ps)
        except Exception as exc:
            logger.debug("Chromium glob fallback failed for %s: %s", user_name, exc)

        # 3) Gecko (Firefox and forks). The cache lives under AppData\Local at
        #    the mirror path; the profile itself under AppData\Roaming.
        for browser, rel in GECKO_VENDORS:
            vendor_root = os.path.join(appdata["Roaming"], rel)
            if not os.path.isdir(vendor_root):
                continue
            cache_vendor_root = os.path.join(local_root, rel)
            for name, prof_dir in _gecko_profile_dirs(vendor_root, remap_abs):
                cache_dir = os.path.join(cache_vendor_root, "Profiles", name, "cache2")
                _add(ProfileSource(
                    browser=browser, vendor="gecko", user_name=user_name,
                    sid=sid, profile=name, root_dir=prof_dir,
                    cache_dir=cache_dir if os.path.isdir(cache_dir) else None))

        # 4) Electron / Chromium-storage desktop apps. Adaptive: scan AppData for
        #    ANY app directory holding a Chromium `Local Storage\leveldb` or
        #    `IndexedDB` store, labelling the well-known ones from ELECTRON_APPS.
        electron_labels = {os.path.normcase(rel): app for app, rel in ELECTRON_APPS}
        electron_labels.update({os.path.normcase(os.path.basename(rel)): app
                                for app, rel in ELECTRON_APPS})
        scan_bases = [appdata["Roaming"], appdata["Local"]]
        for base in scan_bases:
            if not os.path.isdir(base):
                continue
            # Depth 1 (AppData\App) and depth 2 (AppData\Vendor\App).
            candidates = glob.glob(os.path.join(base, "*")) + \
                glob.glob(os.path.join(base, "*", "*"))
            for app_root in candidates:
                if not os.path.isdir(app_root):
                    continue
                top = os.path.normcase(os.path.basename(app_root))
                if top in _ELECTRON_DENY:
                    continue
                has_store = (os.path.isdir(os.path.join(app_root, "Local Storage", "leveldb"))
                             or os.path.isdir(os.path.join(app_root, "IndexedDB")))
                if not has_store:
                    continue
                # An app that is really a Chromium browser (has User Data) is
                # handled above; skip it here.
                if os.path.isdir(os.path.join(app_root, "User Data")):
                    continue
                rel_from_base = os.path.relpath(app_root, base)
                label = (electron_labels.get(os.path.normcase(rel_from_base))
                         or electron_labels.get(top)
                         or os.path.basename(app_root))
                _add(ProfileSource(
                    browser=label, vendor="electron", user_name=user_name,
                    sid=sid, profile="default", root_dir=app_root))

    return sources


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

OUTPUT_DB_NAME = "browser_analysis.db"

# Provenance columns prepended to (almost) every table.
_PROV = (
    "browser TEXT, vendor TEXT, user_name TEXT, sid TEXT, profile TEXT, "
    "source_path TEXT, parsed_at TEXT"
)

# table_name -> full CREATE column list (provenance + fields). Written out
# literally, no '#' comments inside the SQL (SQLite would choke and the table
# would come out empty inside the enclosing except).
TABLE_SCHEMAS: Dict[str, str] = {
    "browser_history": (
        f"{_PROV}, url TEXT, title TEXT, visit_count INTEGER, typed_count INTEGER, "
        "last_visit_time TEXT, visit_time TEXT, transition TEXT, from_visit_url TEXT, "
        "visit_id INTEGER, "
        "UNIQUE(source_path, visit_id)"
    ),
    "browser_downloads": (
        f"{_PROV}, target_path TEXT, source_url TEXT, referrer TEXT, tab_url TEXT, "
        "received_bytes INTEGER, total_bytes INTEGER, start_time TEXT, end_time TEXT, "
        "danger_type INTEGER, interrupt_reason INTEGER, state INTEGER, opened INTEGER, "
        "mime_type TEXT, download_id INTEGER, "
        "UNIQUE(source_path, download_id)"
    ),
    "browser_cookies": (
        f"{_PROV}, host_key TEXT, name TEXT, path TEXT, creation_time TEXT, "
        "expires_time TEXT, last_access_time TEXT, is_secure INTEGER, is_httponly INTEGER, "
        "is_persistent INTEGER, samesite INTEGER, source_scheme INTEGER, has_expires INTEGER, "
        "encrypted_value_b64 TEXT, encryption_version TEXT, "
        "UNIQUE(source_path, host_key, name, path, creation_time)"
    ),
    "browser_autofill": (
        f"{_PROV}, field_name TEXT, value TEXT, count INTEGER, "
        "date_created TEXT, date_last_used TEXT, "
        "UNIQUE(source_path, field_name, value)"
    ),
    "browser_credentials": (
        f"{_PROV}, origin_url TEXT, action_url TEXT, username_element TEXT, "
        "username_value TEXT, password_element TEXT, password_encrypted_b64 TEXT, "
        "encryption_version TEXT, signon_realm TEXT, date_created TEXT, "
        "date_last_used TEXT, date_password_modified TEXT, times_used INTEGER, blacklisted INTEGER, "
        "UNIQUE(source_path, origin_url, username_value, signon_realm)"
    ),
    "browser_shortcuts": (
        f"{_PROV}, text TEXT, fill_into_edit TEXT, url TEXT, contents TEXT, "
        "description TEXT, last_access_time TEXT, number_of_hits INTEGER, "
        "UNIQUE(source_path, text, url)"
    ),
    "browser_network_predictor": (
        f"{_PROV}, user_text TEXT, url_id INTEGER, hit_count INTEGER, miss_count INTEGER, "
        "UNIQUE(source_path, user_text, url_id)"
    ),
    "browser_favicons": (
        f"{_PROV}, page_url TEXT, icon_url TEXT, icon_domain TEXT, last_updated TEXT, "
        "UNIQUE(source_path, page_url, icon_url)"
    ),
    "browser_bookmarks": (
        f"{_PROV}, folder TEXT, name TEXT, url TEXT, date_added TEXT, "
        "date_last_used TEXT, guid TEXT, "
        "UNIQUE(source_path, guid)"
    ),
    "browser_extensions": (
        f"{_PROV}, extension_id TEXT, name TEXT, version TEXT, description TEXT, "
        "permissions TEXT, install_time TEXT, from_webstore INTEGER, state INTEGER, "
        "manifest_path TEXT, "
        "UNIQUE(source_path, extension_id)"
    ),
    "browser_preferences": (
        f"{_PROV}, setting_key TEXT, setting_value TEXT, category TEXT, "
        "UNIQUE(source_path, setting_key)"
    ),
    "browser_sessions": (
        f"{_PROV}, session_file TEXT, window_index INTEGER, tab_index INTEGER, "
        "url TEXT, title TEXT, referrer TEXT, form_text TEXT, entry_type TEXT"
    ),
    "browser_local_storage": (
        f"{_PROV}, store_kind TEXT, origin TEXT, key TEXT, value TEXT, "
        "is_deleted INTEGER, seq INTEGER"
    ),
    "browser_indexeddb": (
        f"{_PROV}, origin TEXT, database_name TEXT, object_store TEXT, "
        "key TEXT, value TEXT, blob_path TEXT, is_deleted INTEGER"
    ),
    "browser_service_worker": (
        f"{_PROV}, scope TEXT, resource_url TEXT, response_time TEXT, "
        "content_length INTEGER, extracted_body_path TEXT, request_method TEXT, "
        "http_status INTEGER, content_type TEXT, content_encoding TEXT, "
        "server_headers TEXT"
    ),
    "browser_cache": (
        f"{_PROV}, url TEXT, request_time TEXT, response_time TEXT, http_status INTEGER, "
        "content_type TEXT, content_length INTEGER, content_encoding TEXT, "
        "server_headers TEXT, extracted_body_path TEXT, cache_format TEXT"
    ),
    "browser_push": (
        f"{_PROV}, app_id TEXT, origin TEXT, registration_id TEXT, sender_id TEXT, source_key TEXT"
    ),
    "browser_media_router": (
        f"{_PROV}, device_name TEXT, device_type TEXT, model_name TEXT, ip_endpoint TEXT, "
        "capabilities TEXT, last_seen TEXT"
    ),
    "browser_files": (
        "browser TEXT, vendor TEXT, user_name TEXT, sid TEXT, profile TEXT, "
        "artifact TEXT, original_path TEXT, extracted_path TEXT, size INTEGER, "
        "sha1 TEXT, mtime TEXT, parsed_at TEXT, "
        "UNIQUE(extracted_path)"
    ),
    "browser_metadata": (
        "browser TEXT, vendor TEXT, user_name TEXT, sid TEXT, profile TEXT, "
        "source_path TEXT, version TEXT, os_crypt_key_b64 TEXT, key_scheme TEXT, "
        "profile_created TEXT, parsed_at TEXT, "
        "UNIQUE(source_path)"
    ),
    # Web Data extras (saved addresses, payment methods, search engines).
    "browser_addresses": (
        f"{_PROV}, guid TEXT, full_name TEXT, company TEXT, street_address TEXT, "
        "city TEXT, state TEXT, zipcode TEXT, country TEXT, phone TEXT, email TEXT, "
        "date_modified TEXT, use_count INTEGER, use_date TEXT, origin TEXT, "
        "UNIQUE(source_path, guid)"
    ),
    "browser_payments": (
        f"{_PROV}, kind TEXT, name_on_card TEXT, last_four TEXT, network TEXT, "
        "expiration_month INTEGER, expiration_year INTEGER, bank_name TEXT, "
        "card_number_encrypted_b64 TEXT, encryption_version TEXT, billing_address_id TEXT, "
        "nickname TEXT, use_count INTEGER, use_date TEXT, date_modified TEXT, "
        "UNIQUE(source_path, kind, last_four, name_on_card, expiration_year)"
    ),
    "browser_search_engines": (
        f"{_PROV}, short_name TEXT, keyword TEXT, url TEXT, favicon_url TEXT, "
        "suggest_url TEXT, date_created TEXT, last_modified TEXT, usage_count INTEGER, "
        "is_default INTEGER, "
        "UNIQUE(source_path, keyword, url)"
    ),
    "browser_extension_storage": (
        f"{_PROV}, extension_id TEXT, store_kind TEXT, key TEXT, value TEXT, "
        "is_deleted INTEGER, seq INTEGER"
    ),
    "browser_reading_list": (
        f"{_PROV}, title TEXT, url TEXT, date_added TEXT, date_last_opened TEXT, "
        "read_status TEXT, "
        "UNIQUE(source_path, url)"
    ),
    "browser_network_state": (
        f"{_PROV}, source TEXT, host_or_key TEXT, detail TEXT, expiry TEXT"
    ),
    "browser_dips": (
        f"{_PROV}, site TEXT, first_site_storage_time TEXT, last_site_storage_time TEXT, "
        "first_user_interaction_time TEXT, last_user_interaction_time TEXT"
    ),
    "browser_media_history": (
        f"{_PROV}, origin TEXT, url TEXT, watch_time_seconds REAL, has_audio INTEGER, "
        "has_video INTEGER, last_updated TEXT, position_seconds REAL, "
        "UNIQUE(source_path, url, last_updated)"
    ),
    "browser_top_sites": (
        f"{_PROV}, url TEXT, title TEXT, url_rank INTEGER, "
        "UNIQUE(source_path, url)"
    ),
    # Gecko (Firefox). Written now, verified later on a real profile.
    "browser_gecko_localstorage": (
        f"{_PROV}, origin TEXT, key TEXT, value TEXT, source_kind TEXT"
    ),
    "browser_gecko_history": (
        f"{_PROV}, url TEXT, title TEXT, visit_count INTEGER, typed INTEGER, "
        "last_visit_time TEXT, visit_time TEXT, visit_type INTEGER, from_visit_url TEXT, "
        "UNIQUE(source_path, url, visit_time)"
    ),
    "browser_gecko_downloads": (
        f"{_PROV}, url TEXT, target_path TEXT, start_time TEXT, end_time TEXT, "
        "state INTEGER, "
        "UNIQUE(source_path, url, start_time)"
    ),
    "browser_gecko_bookmarks": (
        f"{_PROV}, folder TEXT, title TEXT, url TEXT, date_added TEXT, last_modified TEXT, "
        "UNIQUE(source_path, url, title)"
    ),
    "browser_gecko_cookies": (
        f"{_PROV}, host TEXT, name TEXT, path TEXT, value TEXT, creation_time TEXT, "
        "expiry_time TEXT, last_accessed TEXT, is_secure INTEGER, is_httponly INTEGER, "
        "UNIQUE(source_path, host, name, path)"
    ),
    "browser_gecko_formhistory": (
        f"{_PROV}, field_name TEXT, value TEXT, times_used INTEGER, first_used TEXT, "
        "last_used TEXT, "
        "UNIQUE(source_path, field_name, value)"
    ),
    "browser_gecko_credentials": (
        f"{_PROV}, hostname TEXT, username_encrypted_b64 TEXT, password_encrypted_b64 TEXT, "
        "encryption_version TEXT, time_created TEXT, time_last_used TEXT, times_used INTEGER, "
        "UNIQUE(source_path, hostname, username_encrypted_b64)"
    ),
    "browser_gecko_sessions": (
        f"{_PROV}, window_index INTEGER, tab_index INTEGER, url TEXT, title TEXT, "
        "form_text TEXT, entry_type TEXT"
    ),
}


# The columns that tell a row apart, per table with no UNIQUE key (behind
# source_path). The identity a re-parse checks is still every column but
# parsed_at; this index is what makes that lookup a seek instead of a scan.
_IDENTITY_INDEX = {
    "browser_sessions": ["session_file", "window_index", "tab_index", "url"],
    "browser_local_storage": ["origin", "key", "seq"],
    "browser_indexeddb": ["origin", "database_name", "object_store", "key"],
    "browser_service_worker": ["resource_url", "response_time"],
    "browser_cache": ["url", "response_time"],
    "browser_push": ["app_id", "origin"],
    "browser_media_router": ["device_name", "last_seen"],
    "browser_extension_storage": ["extension_id", "key", "seq"],
    "browser_network_state": ["host_or_key", "source"],
    "browser_dips": ["site"],
    "browser_gecko_localstorage": ["origin", "key"],
    "browser_gecko_sessions": ["window_index", "tab_index", "url"],
}


def create_schema(conn: sqlite3.Connection) -> None:
    """Create every output table if it does not already exist.

    Also two kinds of index: on a table with no UNIQUE key, the identity a
    re-parse checks (source_path + the first data column); and on every table,
    its first time column - the browser dashboard and the timeline read by
    time, and the database had no secondary index at all.
    """
    cur = conn.cursor()
    for name, cols in TABLE_SCHEMAS.items():
        cur.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
        names = [c[1] for c in cur.execute(f"PRAGMA table_info({name})")]
        upper = cols.upper()
        if "UNIQUE" not in upper and "PRIMARY KEY" not in upper and "source_path" in names:
            data = [c for c in names if c not in _PROV_COLS]
            ident = [c for c in _IDENTITY_INDEX.get(name, data[:1]) if c in names] or data[:1]
            # A new name: cases parsed before keep their old, two-column
            # index (harmless); the planner takes the more selective one.
            ensure_identity_index(conn, name, ["source_path"] + ident,
                                  name="idx_%s_identity_v2" % name)
        when = next((c for c in names if c.endswith("_time") or c.startswith("date_")
                     or c in ("timestamp", "last_visit_time")), None)
        if when:
            cur.execute(f'CREATE INDEX IF NOT EXISTS "idx_{name}_{when}" ON {name} ("{when}")')
    conn.commit()


# ---------------------------------------------------------------------------
# SQLite copy + read helpers
# ---------------------------------------------------------------------------

_SQLITE_SIDECARS = ("-wal", "-journal", "-shm")


# Databases that could not be copied in this parse (locked by a running
# browser) - reported as warnings, so a profile read only in part does not
# show as plainly "Parsed". Reset by parse_browser_data.
_UNREAD: List[str] = []
_ACCESSOR = {"obj": None}


def _copy_locked(src: str, dst: str) -> bool:
    """Copy a file the browser holds open, the way the rest of Crow-Eye does.

    FileAccessor (StandardCopy -> VSS -> RawDisk, with retry) - the chain the
    image collector and SRUM use - then the raw backup-semantics copy. The
    raw fallback alone could not open a Cookies file a running browser locks
    ("Raw disk access method not yet fully implemented"), and the profile's
    cookies were simply missing from the case.
    """
    try:
        if _ACCESSOR["obj"] is None:
            from Artifacts_Collectors.crow_claw.core.file_accessor import FileAccessor
            import ctypes as _ct
            try:
                admin = bool(_ct.windll.shell32.IsUserAnAdmin())
            except Exception:
                admin = False
            acc = FileAccessor(is_admin=admin)
            try:
                from Artifacts_Collectors.SRUM_Claw import _parser_allows_snapshot_creation
                if not _parser_allows_snapshot_creation():
                    for strategy in getattr(acc, "strategies", []):
                        if type(strategy).__name__ == "VSSAccessStrategy":
                            strategy.allow_snapshot_creation = False
            except Exception:
                pass
            _ACCESSOR["obj"] = acc
        result = _ACCESSOR["obj"].access_file_with_retry(src, dst, "Browser")
        if getattr(result, "success", False) and os.path.exists(dst):
            return True
    except Exception as exc:
        logger.debug("FileAccessor copy of %s unavailable: %s", src, exc)
    if copy_locked_file_raw is not None:
        try:
            return bool(copy_locked_file_raw(src, dst)) and os.path.exists(dst)
        except Exception as exc:
            logger.debug("Raw copy of %s failed: %s", src, exc)
    return False


def _custody_before(src):
    """(open custody record or None, the source's times read before the copy)."""
    try:
        from utils import custody
        rec = custody.active()
        return (rec, custody.file_times(src)) if rec is not None else (None, None)
    except Exception:
        return None, None


def _copy_sqlite_with_sidecars(src: str, tmp_dir: str) -> Optional[str]:
    """Copy a SQLite DB (and its WAL/journal/shm sidecars) into tmp_dir.

    Returns the path to the copied main DB, or None on failure. Locked files
    (e.g. Cookies while the browser runs) fall back to the raw backup-semantics
    copy that SRUM uses. The evidence file itself is never opened for write.
    """
    if not os.path.isfile(src):
        return None
    # One private folder per copy. A shared folder keyed on the basename let a
    # leftover "data.sqlite-wal" from one origin / profile sit beside the next
    # copy of the same-named DB, and SQLite would apply the wrong WAL to it.
    dst_dir = tempfile.mkdtemp(prefix="db_", dir=tmp_dir)
    dst = os.path.join(dst_dir, os.path.basename(src))
    copied = False
    method = "copy"
    rec, times = _custody_before(src)
    try:
        shutil.copy2(src, dst)
        copied = True
    except (PermissionError, OSError) as exc:
        logger.debug("Plain copy of %s failed (%s); trying the locked-file chain", src, exc)
        copied = _copy_locked(src, dst)
        method = "locked-file copy (FileAccessor / backup semantics)"
    if not copied:
        _UNREAD.append(src)
        if rec is not None:
            rec.add_failure(src, "browser database could not be copied (locked by the browser)",
                            method="copy")
        return None
    if rec is not None:
        try:
            # Source and copy hashed; a browser that is running can change the
            # file between the two reads, which the entry then says.
            rec.add_source(src, copy=dst, method=method, times=times,
                           note="temporary working copy, parsed read-only")
        except Exception:
            pass
    # Bring the sidecars along so WAL/rollback content is visible.
    for suffix in _SQLITE_SIDECARS:
        side = src + suffix
        if os.path.isfile(side):
            try:
                shutil.copy2(side, dst + suffix)
            except (PermissionError, OSError):
                if copy_locked_file_raw is not None:
                    try:
                        copy_locked_file_raw(side, dst + suffix)
                    except Exception:
                        pass
    return dst


def _open_ro(db_path: str) -> Optional[sqlite3.Connection]:
    """Open a copied SQLite DB read-only. Returns None if it will not open.

    ``db_path`` is always our private copy, never the evidence. It is opened
    with plain ``mode=ro`` so SQLite applies the copied ``-wal``: with
    ``immutable=1`` it ignores the WAL, and rows the browser had committed but
    not yet checkpointed silently vanished (measured: 1 of 2 rows read).
    ``immutable=1`` is kept only as the fallback for a copy SQLite refuses to
    open normally.
    """
    base = "file:" + db_path.replace("?", "%3f").replace("#", "%23")
    for query in ("?mode=ro", "?mode=ro&immutable=1"):
        try:
            conn = sqlite3.connect(base + query, uri=True, timeout=5)
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:
            logger.debug("Could not open %s (%s): %s", db_path, query, exc)
    return None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols
    except sqlite3.Error:
        return False


def _fmt_webkit(value) -> str:
    """WebKit microseconds -> forensic string; '' for null/0/garbage."""
    try:
        if value in (None, 0):
            return ""
        return format_forensic_timestamp(webkit_to_datetime(int(value)))
    except (ValueError, OverflowError, OSError):
        return ""


def _fmt_prtime(value) -> str:
    try:
        if value in (None, 0):
            return ""
        return format_forensic_timestamp(prtime_to_datetime(int(value)))
    except (ValueError, OverflowError, OSError):
        return ""


def _fmt_unix(value) -> str:
    try:
        if value in (None, 0):
            return ""
        return format_forensic_timestamp(unix_timestamp_to_datetime(float(value)))
    except (ValueError, OverflowError, OSError):
        return ""


def _fmt_keyword_created(value) -> str:
    """keywords.date_created: WebKit microseconds (17 digits) in current
    Chromium, Unix seconds in old builds."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return _fmt_webkit(n) if n > 10 ** 13 else _fmt_unix(n)


def _fmt_unix_scaled(value) -> str:
    """Unix time that may be seconds, milliseconds or microseconds.

    Modern Firefox stores moz_cookies.expiry in MILLISECONDS; feeding that to a
    seconds-based converter overflows and silently yields "". Scale by
    magnitude: 13-digit values are ms, 16-digit values are us.
    """
    try:
        if value in (None, 0, ""):
            return ""
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v > 1e14:
        v /= 1e6
    elif v > 1e11:
        v /= 1e3
    return _fmt_unix(v)


# Chromium page-transition core types (low byte of the transition mask).
_TRANSITION = {
    0: "link", 1: "typed", 2: "auto_bookmark", 3: "auto_subframe",
    4: "manual_subframe", 5: "generated", 6: "start_page", 7: "form_submit",
    8: "reload", 9: "keyword", 10: "keyword_generated",
}


def _transition_text(raw) -> str:
    try:
        core = int(raw) & 0xFF
        return _TRANSITION.get(core, f"type_{core}")
    except (TypeError, ValueError):
        return ""


class _Writer:
    """Batched writer against the output DB: only rows not stored yet.

    A table with a UNIQUE key uses INSERT OR IGNORE; the twelve without one
    (sessions, local storage, IndexedDB, caches ...) go through
    utils.dedupe_insert.insert_new with every column but parsed_at as the
    identity. Before, a re-parse DELETED each profile's earlier rows to avoid
    duplicates - and history or cookies that had since aged out of the live
    browser were lost from the case with them.

    ``stats`` counts rows READ per table (it used to count every row as
    written when SQLite reported no rowcount); ``tally`` has what was new and
    what was already present.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.stats: Dict[str, int] = {}
        self.tally = Tally()
        self._unique: Dict[str, bool] = {}
        self._keys: Dict[str, List[str]] = {}
        # Was the table empty when this run first wrote to it? Then nothing in
        # it can repeat a stored row, and the per-row check is skipped.
        self._empty_at_start: Dict[str, bool] = {}
        # Rows already in the case whose values changed since (a visit count,
        # a last-access time, an extension's version): updated in place.
        self.updated: Dict[str, int] = {}
        # Per table, for this run: the path column's stored values by
        # normcase, and the Crow-Claw copy roots among them (see
        # _drop_stored_under_other_path).
        self._stored_paths: Dict[str, Dict[str, str]] = {}
        self._copy_roots: Dict[str, Dict[str, Tuple[str, str]]] = {}
        self._origin: Dict[str, Optional[Tuple[str, str]]] = {}

    def _origin_of(self, path) -> Optional[Tuple[str, str]]:
        if not isinstance(path, str):
            return None
        if path not in self._origin:
            self._origin[path] = collected_copy_origin(path)
        return self._origin[path]

    def _load_stored_paths(self, table: str, col: str) -> None:
        """Every distinct stored path of the table (once per run), and the
        Crow-Claw copy roots among them."""
        stored, roots = {}, {}
        try:
            for (p,) in self.conn.execute(f"SELECT DISTINCT {col} FROM {table}"):
                if not isinstance(p, str):
                    continue
                stored[os.path.normcase(p)] = p
                origin = self._origin_of(p)
                if origin:
                    roots[os.path.normcase(origin[0])] = origin
        except sqlite3.Error:
            pass
        self._stored_paths[table] = stored
        self._copy_roots[table] = roots

    def _has_copy_rows(self, table: str, col: str) -> bool:
        try:
            return self.conn.execute(
                f"SELECT 1 FROM {table} WHERE {col} LIKE ? LIMIT 1",
                ("%\\" + BROWSER_CASE_DIR + "\\" + LIVE_SOURCE_TAG + "\\Users\\%",)
            ).fetchone() is not None
        except sqlite3.Error:
            return False

    def _drop_stored_under_other_path(self, table: str, columns: List[str],
                                      rows: List[tuple]) -> List[tuple]:
        """The rows not already stored under the other spelling of their file.

        Crow-Claw copies a live profile to <case>\\live_acquisition\\Browser\\
        live\\Users\\...; parsing the live profile and then that copy (or the
        other way round) read the same evidence twice, and because the identity
        includes the path every row of the copy looked new - case 7.10.2026
        held ~113k Brave rows twice (all of its downloads, autofill and
        credentials). A row is already present when the same row, with every
        path below the copy root moved to the original volume (or back), is
        stored: every column but parsed_at, provenance (user, SID) included,
        so another machine's profile never matches. The row keeps its own
        path when it IS new - the copy's path stays the evidence it came from.
        """
        col = "original_path" if table == "browser_files" else "source_path"
        if col not in columns:
            return rows
        pi = columns.index(col)
        batch_is_copy = any(self._origin_of(r[pi]) for r in rows)
        if table not in self._stored_paths:
            if not batch_is_copy and not self._has_copy_rows(table, col):
                self._stored_paths[table], self._copy_roots[table] = {}, {}
            else:
                self._load_stored_paths(table, col)
        stored = self._stored_paths[table]
        if not stored:
            return rows
        idx = [i for i, c in enumerate(columns) if c != "parsed_at"]
        sql = "SELECT 1 FROM %s WHERE %s LIMIT 1" % (
            table, " AND ".join("%s IS ?" % columns[i] for i in idx))
        keep = []
        for row in rows:
            path = row[pi]
            moves = []
            origin = self._origin_of(path)
            if origin:
                moves.append((origin[0], origin[1]))
            elif isinstance(path, str):
                for copy_root, original_root in self._copy_roots[table].values():
                    if rebase_path(path, original_root, copy_root):
                        moves.append((original_root, copy_root))
            found = False
            for src_root, dst_root in moves:
                other = rebase_path(path, src_root, dst_root)
                other = stored.get(os.path.normcase(other)) if other else None
                if not other:
                    continue
                moved = []
                for i in idx:
                    v = row[i]
                    if i == pi:
                        v = other
                    elif isinstance(v, str):
                        m = rebase_path(v, src_root, dst_root)
                        if m:
                            v = stored.get(os.path.normcase(m), m)
                    moved.append(v)
                if self.conn.execute(sql, moved).fetchone():
                    found = True
                    break
            if not found:
                keep.append(row)
        dropped = len(rows) - len(keep)
        if dropped:
            self.tally.add(table, dropped, 0)
            self.stats[table] = self.stats.get(table, 0) + dropped
        return keep

    def _unique_key(self, table: str) -> List[str]:
        """The columns of the table's UNIQUE(...) constraint, from its schema."""
        if table not in self._keys:
            import re as _re
            m = _re.search(r"UNIQUE\s*\(([^)]*)\)", TABLE_SCHEMAS.get(table, ""), _re.I)
            self._keys[table] = [c.strip() for c in m.group(1).split(",")] if m else []
        return self._keys[table]

    def _has_unique_key(self, table: str) -> bool:
        if table not in self._unique:
            schema = TABLE_SCHEMAS.get(table, "")
            self._unique[table] = "UNIQUE" in schema.upper() or "PRIMARY KEY" in schema.upper()
        return self._unique[table]

    def add(self, table: str, columns: List[str], rows: List[tuple]) -> None:
        if not rows:
            return
        try:
            rows = self._drop_stored_under_other_path(table, columns, rows)
            if not rows:
                return
            key = self._unique_key(table)
            n_read = len(rows)
            if key and all(k in columns for k in key):
                # A NULL in the UNIQUE key never conflicts - SQLite treats every
                # NULL as distinct - so ON CONFLICT never fired for such a row
                # and each re-parse stored it again (a saved card with no
                # name_on_card: browser_payments grew by 3 on every parse).
                # Those rows are checked NULL-safely (IS) on every column but
                # parsed_at, as a table without a UNIQUE key is: two cards that
                # differ only outside the key are both kept, as before.
                kidx = [columns.index(k) for k in key]
                with_null = [r for r in rows if any(r[i] is None for i in kidx)]
                if with_null:
                    insert_new(self.conn, table, columns, with_null,
                               [c for c in columns if c != "parsed_at"], self.tally)
                    rows = [r for r in rows if not any(r[i] is None for i in kidx)]
            if not rows:
                pass
            elif key and all(k in columns for k in key):
                # Upsert: new keys are inserted; an existing key is updated
                # only where a value differs (parsed_at follows the change).
                # INSERT OR IGNORE kept the first parse's values for ever.
                placeholders = ",".join("?" * len(columns))
                data_cols = [c for c in columns if c not in key and c != "parsed_at"]
                set_cols = [c for c in columns if c not in key]
                sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
                if set_cols:
                    sql += (" ON CONFLICT(%s) DO UPDATE SET %s" % (
                        ",".join(key), ",".join("%s=excluded.%s" % (c, c) for c in set_cols)))
                    if data_cols:
                        sql += " WHERE " + " OR ".join(
                            "%s IS NOT excluded.%s" % (c, c) for c in data_cols)
                else:
                    sql += " ON CONFLICT DO NOTHING"
                top = self.conn.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {table}").fetchone()[0]
                before = self.conn.total_changes
                self.conn.executemany(sql, rows)
                changes = self.conn.total_changes - before
                new = self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE rowid > ?",
                                        (top,)).fetchone()[0]
                self.tally.add(table, len(rows), new)
                if changes > new:
                    self.updated[table] = self.updated.get(table, 0) + (changes - new)
            elif self._has_unique_key(table):
                placeholders = ",".join("?" * len(columns))
                sql = f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
                before = self.conn.total_changes
                self.conn.executemany(sql, rows)
                self.tally.add(table, len(rows), self.conn.total_changes - before)
            else:
                if table not in self._empty_at_start:
                    self._empty_at_start[table] = table_is_empty(self.conn, table)
                if self._empty_at_start[table]:
                    placeholders = ",".join("?" * len(columns))
                    before = self.conn.total_changes
                    self.conn.executemany(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", rows)
                    self.tally.add(table, len(rows), self.conn.total_changes - before)
                else:
                    insert_new(self.conn, table, columns, rows,
                               [c for c in columns if c != "parsed_at"], self.tally)
            self.stats[table] = self.stats.get(table, 0) + n_read
        except sqlite3.Error as exc:
            logger.warning("[Browser] insert into %s failed: %s", table, exc)


def _prov_tuple(ps: ProfileSource, source_path: str, now: str) -> tuple:
    return (ps.browser, ps.vendor, ps.user_name, ps.sid, ps.profile, source_path, now)


_PROV_COLS = ["browser", "vendor", "user_name", "sid", "profile", "source_path", "parsed_at"]

try:
    from utils.dedupe_insert import Tally, ensure_identity_index, insert_new, table_is_empty
except ImportError:                                    # run as a script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.dedupe_insert import Tally, ensure_identity_index, insert_new, table_is_empty
try:
    from Artifacts_Collectors.browser_paths import (BROWSER_CASE_DIR, LIVE_SOURCE_TAG,
                                                    collected_copy_origin, original_profile_path,
                                                    rebase_path)
except ImportError:                                    # run as a script
    from browser_paths import (BROWSER_CASE_DIR, LIVE_SOURCE_TAG, collected_copy_origin,
                               original_profile_path, rebase_path)


# ---------------------------------------------------------------------------
# Chromium: SQLite-backed artifacts (History, Cookies, Web Data, Login Data,
# Shortcuts, Network Action Predictor, Favicons)
# ---------------------------------------------------------------------------

def _parse_chromium_history(ps, writer, now, tmp_dir):
    """History DB: visited URLs, downloads, and keyword search terms."""
    src = os.path.join(ps.root_dir, "History")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn:
        return
    try:
        prov = _prov_tuple(ps, src, now)

        # Visits joined to urls, with the referrer URL resolved through
        # from_visit -> visits -> urls.
        if _has_table(conn, "urls") and _has_table(conn, "visits"):
            rows = []
            q = (
                "SELECT v.id AS visit_id, u.url, u.title, u.visit_count, u.typed_count, "
                "u.last_visit_time, v.visit_time, v.transition, "
                "(SELECT u2.url FROM visits v2 JOIN urls u2 ON u2.id=v2.url "
                " WHERE v2.id=v.from_visit) AS from_url "
                "FROM visits v JOIN urls u ON u.id=v.url"
            )
            for r in conn.execute(q):
                rows.append(prov + (
                    r["url"], r["title"], r["visit_count"], r["typed_count"],
                    _fmt_webkit(r["last_visit_time"]), _fmt_webkit(r["visit_time"]),
                    _transition_text(r["transition"]), r["from_url"], r["visit_id"]))
            writer.add("browser_history", _PROV_COLS + [
                "url", "title", "visit_count", "typed_count", "last_visit_time",
                "visit_time", "transition", "from_visit_url", "visit_id"], rows)

        # Downloads (source URL chain via downloads_url_chains).
        if _has_table(conn, "downloads"):
            rows = []
            q = (
                "SELECT d.id, d.target_path, d.referrer, d.tab_url, d.received_bytes, "
                "d.total_bytes, d.start_time, d.end_time, d.danger_type, "
                "d.interrupt_reason, d.state, d.opened, d.mime_type, "
                "(SELECT url FROM downloads_url_chains c WHERE c.id=d.id "
                " ORDER BY chain_index LIMIT 1) AS source_url "
                "FROM downloads d"
            )
            for r in conn.execute(q):
                rows.append(prov + (
                    r["target_path"], r["source_url"], r["referrer"], r["tab_url"],
                    r["received_bytes"], r["total_bytes"], _fmt_webkit(r["start_time"]),
                    _fmt_webkit(r["end_time"]), r["danger_type"], r["interrupt_reason"],
                    r["state"], r["opened"], r["mime_type"], r["id"]))
            writer.add("browser_downloads", _PROV_COLS + [
                "target_path", "source_url", "referrer", "tab_url", "received_bytes",
                "total_bytes", "start_time", "end_time", "danger_type",
                "interrupt_reason", "state", "opened", "mime_type", "download_id"], rows)

        # Keyword search terms typed into the omnibox -> becomes shortcut-like
        # intent evidence; stored in browser_shortcuts alongside Shortcuts DB.
        if _has_table(conn, "keyword_search_terms"):
            rows = []
            q = (
                "SELECT k.term, u.url, u.last_visit_time, u.visit_count "
                "FROM keyword_search_terms k JOIN urls u ON u.id=k.url_id"
            )
            for r in conn.execute(q):
                rows.append(prov + (
                    r["term"], r["term"], r["url"], None, "keyword_search_term",
                    _fmt_webkit(r["last_visit_time"]), r["visit_count"]))
            writer.add("browser_shortcuts", _PROV_COLS + [
                "text", "fill_into_edit", "url", "contents", "description",
                "last_access_time", "number_of_hits"], rows)
    finally:
        conn.close()


def _parse_chromium_cookies(ps, writer, now, tmp_dir):
    """Cookies DB (metadata + encrypted blob only, never decrypted)."""
    for rel in (os.path.join("Network", "Cookies"), "Cookies"):
        src = os.path.join(ps.root_dir, rel)
        if not os.path.isfile(src):
            continue
        db = _copy_sqlite_with_sidecars(src, tmp_dir)
        if not db:
            continue
        conn = _open_ro(db)
        if not conn or not _has_table(conn, "cookies"):
            if conn:
                conn.close()
            continue
        try:
            prov = _prov_tuple(ps, src, now)
            has_samesite = _has_column(conn, "cookies", "samesite")
            has_scheme = _has_column(conn, "cookies", "source_scheme")
            rows = []
            for r in conn.execute("SELECT * FROM cookies"):
                blob = r["encrypted_value"] if "encrypted_value" in r.keys() else None
                enc_b64, scheme = _encode_secret(blob)
                # Chrome before ~M66 named these secure / httponly / persistent;
                # reading only the new names failed the whole table on older
                # images ("No item with that key").
                rows.append(prov + (
                    r["host_key"], r["name"], r["path"],
                    _fmt_webkit(r["creation_utc"]), _fmt_webkit(r["expires_utc"]),
                    _fmt_webkit(_col(r, "last_access_utc")),
                    _col(r, "is_secure", _col(r, "secure")),
                    _col(r, "is_httponly", _col(r, "httponly")),
                    _col(r, "is_persistent", _col(r, "persistent")),
                    r["samesite"] if has_samesite else None,
                    r["source_scheme"] if has_scheme else None,
                    r["has_expires"] if "has_expires" in r.keys() else None,
                    enc_b64, scheme))
            writer.add("browser_cookies", _PROV_COLS + [
                "host_key", "name", "path", "creation_time", "expires_time",
                "last_access_time", "is_secure", "is_httponly", "is_persistent",
                "samesite", "source_scheme", "has_expires",
                "encrypted_value_b64", "encryption_version"], rows)
        finally:
            conn.close()
        return  # first existing Cookies DB wins


def _col(r, name, default=None):
    """Safe column access on a sqlite3.Row (returns default if absent)."""
    try:
        return r[name] if name in r.keys() else default
    except (IndexError, KeyError):
        return default


# Chromium autofill FieldType values used by `address_type_tokens.type`.
# Named because a bare integer in a column lookup is unreviewable: the street
# address really is 77, and reading the wrong number returns an empty string
# rather than an error.
_FT_NAME_FIRST = 3
_FT_NAME_LAST = 5
_FT_NAME_FULL = 7
_FT_EMAIL = 9
_FT_PHONE = 14
_FT_ADDRESS_LINE1 = 30
_FT_ADDRESS_LINE2 = 31
_FT_CITY = 33
_FT_STATE = 34
_FT_ZIP = 35
_FT_COUNTRY = 36
_FT_COMPANY_NAME = 60
_FT_STREET_ADDRESS = 77


def _parse_chromium_webdata(ps, writer, now, tmp_dir):
    """Web Data DB: autofill/autocomplete, saved addresses, payment methods,
    and search-engine (keyword) configuration."""
    src = os.path.join(ps.root_dir, "Web Data")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn:
        return
    try:
        prov = _prov_tuple(ps, src, now)

        # --- Autofill / autocomplete field history ---
        if _has_table(conn, "autofill"):
            rows = []
            for r in conn.execute("SELECT name, value, count, date_created, date_last_used FROM autofill"):
                rows.append(prov + (
                    r["name"], r["value"], r["count"],
                    _fmt_unix(r["date_created"]), _fmt_unix(r["date_last_used"])))
            writer.add("browser_autofill", _PROV_COLS + [
                "field_name", "value", "count", "date_created", "date_last_used"], rows)

        # --- Saved addresses (modern `addresses` + `address_type_tokens`, or
        #     legacy flat autofill_profiles) ---
        addr_rows = []
        if _has_table(conn, "addresses"):
            # Field VALUES live in address_type_tokens keyed by Chrome's
            # FieldType enum. Build {guid: {type: value}} first.
            tokens = {}
            if _has_table(conn, "address_type_tokens"):
                for tr in conn.execute("SELECT guid, type, value FROM address_type_tokens"):
                    tokens.setdefault(_col(tr, "guid"), {})[_col(tr, "type")] = _col(tr, "value")
            for r in conn.execute("SELECT * FROM addresses"):
                g = _col(r, "guid")
                t = tokens.get(g, {})
                full = t.get(_FT_NAME_FULL) or " ".join(
                    x for x in (t.get(_FT_NAME_FIRST), t.get(_FT_NAME_LAST)) if x)
                # The whole street address is type 77. Types 30/31 are the
                # individual address lines, used only when 77 is absent - the
                # street was previously read from type 101, which is not an
                # address type at all, so it was always empty.
                street = t.get(_FT_STREET_ADDRESS) or "\n".join(
                    x for x in (t.get(_FT_ADDRESS_LINE1), t.get(_FT_ADDRESS_LINE2)) if x)
                addr_rows.append(prov + (
                    g, full or None, t.get(_FT_COMPANY_NAME),
                    street or None, t.get(_FT_CITY), t.get(_FT_STATE),
                    t.get(_FT_ZIP), t.get(_FT_COUNTRY), t.get(_FT_PHONE),
                    t.get(_FT_EMAIL),
                    _fmt_unix(_col(r, "date_modified")),
                    _col(r, "use_count"), _fmt_unix(_col(r, "use_date")),
                    _col(r, "label") or _col(r, "language_code")))
        elif _has_table(conn, "autofill_profiles"):
            for r in conn.execute("SELECT * FROM autofill_profiles"):
                addr_rows.append(prov + (
                    _col(r, "guid"), _col(r, "full_name"), _col(r, "company_name"),
                    _col(r, "street_address"), _col(r, "city"), _col(r, "state"),
                    _col(r, "zipcode"), _col(r, "country_code"), _col(r, "phone"),
                    _col(r, "email"),
                    _fmt_unix(_col(r, "date_modified")),
                    _col(r, "use_count"), _fmt_unix(_col(r, "use_date")),
                    _col(r, "origin")))
        writer.add("browser_addresses", _PROV_COLS + [
            "guid", "full_name", "company", "street_address", "city", "state",
            "zipcode", "country", "phone", "email", "date_modified", "use_count",
            "use_date", "origin"], addr_rows)

        # --- Payment methods (metadata + encrypted PAN blob only) ---
        pay_rows = []
        if _has_table(conn, "credit_cards"):
            for r in conn.execute("SELECT * FROM credit_cards"):
                blob = _col(r, "card_number_encrypted")
                enc_b64, scheme = _encode_secret(blob)
                pay_rows.append(prov + (
                    "local_card", _col(r, "name_on_card"), None, None,
                    _col(r, "expiration_month"), _col(r, "expiration_year"), None,
                    enc_b64, scheme, _col(r, "billing_address_id"), _col(r, "nickname"),
                    _col(r, "use_count"), _fmt_unix(_col(r, "use_date")),
                    _fmt_unix(_col(r, "date_modified"))))
        if _has_table(conn, "masked_credit_cards"):
            for r in conn.execute("SELECT * FROM masked_credit_cards"):
                pay_rows.append(prov + (
                    "masked_card", _col(r, "name_on_card"), _col(r, "last_four"),
                    _col(r, "network"), _col(r, "exp_month"), _col(r, "exp_year"),
                    _col(r, "bank_name"), None, "server", None, _col(r, "nickname"),
                    None, None, None))
        for tname, kind in (("masked_bank_accounts", "bank_account"),
                            ("local_ibans", "iban"), ("masked_ibans", "iban")):
            if _has_table(conn, tname):
                for r in conn.execute(f"SELECT * FROM {tname}"):
                    blob = _col(r, "value_encrypted") or _col(r, "value")
                    enc_b64, scheme = _encode_secret(blob) if isinstance(blob, (bytes, bytearray)) else (None, "plaintext")
                    pay_rows.append(prov + (
                        kind, _col(r, "nickname") or _col(r, "bank_name"),
                        _col(r, "prefix") or _col(r, "suffix") or _col(r, "mask"),
                        _col(r, "network"), None, None, _col(r, "bank_name"),
                        enc_b64, scheme, None, _col(r, "nickname"), None, None, None))
        writer.add("browser_payments", _PROV_COLS + [
            "kind", "name_on_card", "last_four", "network", "expiration_month",
            "expiration_year", "bank_name", "card_number_encrypted_b64",
            "encryption_version", "billing_address_id", "nickname", "use_count",
            "use_date", "date_modified"], pay_rows)

        # --- Search engines / keyword providers ---
        if _has_table(conn, "keywords"):
            default_kw = _chromium_default_search_guid(ps)
            rows = []
            for r in conn.execute("SELECT * FROM keywords"):
                is_default = 1 if (default_kw and (_col(r, "sync_guid") == default_kw
                                                   or str(_col(r, "id")) == default_kw)) else 0
                rows.append(prov + (
                    _col(r, "short_name"), _col(r, "keyword"), _col(r, "url"),
                    _col(r, "favicon_url"), _col(r, "suggest_url"),
                    # WebKit time (us since 1601) in current Chromium, like
                    # last_modified: read as Unix seconds it gave nothing -
                    # 49 of 49 blank on one machine. Older builds wrote Unix
                    # seconds, so the scale decides. 0 = a built-in engine.
                    _fmt_keyword_created(_col(r, "date_created")),
                    # keywords.last_modified is Chrome/WebKit time (us since 1601),
                    # not Unix seconds - _fmt_unix silently yielded nothing.
                    _fmt_webkit(_col(r, "last_modified")),
                    _col(r, "usage_count"), is_default))
            writer.add("browser_search_engines", _PROV_COLS + [
                "short_name", "keyword", "url", "favicon_url", "suggest_url",
                "date_created", "last_modified", "usage_count", "is_default"], rows)
    finally:
        conn.close()


def _chromium_default_search_guid(ps):
    """The default search provider's sync GUID, from Preferences."""
    prefs = _load_json(os.path.join(ps.root_dir, "Preferences")) or {}
    dsp = (prefs.get("default_search_provider_data") or {}).get("template_url_data") or {}
    return dsp.get("synced_guid") or dsp.get("id")


def _parse_chromium_logindata(ps, writer, now, tmp_dir):
    """Login Data DB: saved credentials (encrypted blob only, no plaintext)."""
    for name in ("Login Data", "Login Data For Account"):
        src = os.path.join(ps.root_dir, name)
        db = _copy_sqlite_with_sidecars(src, tmp_dir)
        if not db:
            continue
        conn = _open_ro(db)
        if not conn or not _has_table(conn, "logins"):
            if conn:
                conn.close()
            continue
        try:
            prov = _prov_tuple(ps, src, now)
            has_mod = _has_column(conn, "logins", "date_password_modified")
            rows = []
            for r in conn.execute("SELECT * FROM logins"):
                blob = r["password_value"] if "password_value" in r.keys() else None
                pw_b64, scheme = _encode_secret(blob)
                rows.append(prov + (
                    r["origin_url"], r["action_url"], r["username_element"],
                    r["username_value"], r["password_element"], pw_b64, scheme,
                    r["signon_realm"], _fmt_webkit(r["date_created"]),
                    _fmt_webkit(r["date_last_used"]) if "date_last_used" in r.keys() else "",
                    _fmt_webkit(r["date_password_modified"]) if has_mod else "",
                    r["times_used"] if "times_used" in r.keys() else None,
                    r["blacklisted_by_user"] if "blacklisted_by_user" in r.keys() else None))
            writer.add("browser_credentials", _PROV_COLS + [
                "origin_url", "action_url", "username_element", "username_value",
                "password_element", "password_encrypted_b64", "encryption_version",
                "signon_realm", "date_created", "date_last_used",
                "date_password_modified", "times_used", "blacklisted"], rows)
        finally:
            conn.close()


def _parse_chromium_shortcuts(ps, writer, now, tmp_dir):
    """Shortcuts DB: omnibox text -> chosen destination (typed intent)."""
    src = os.path.join(ps.root_dir, "Shortcuts")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn or not _has_table(conn, "omni_box_shortcuts"):
        if conn:
            conn.close()
        return
    try:
        prov = _prov_tuple(ps, src, now)
        rows = []
        for r in conn.execute("SELECT * FROM omni_box_shortcuts"):
            keys = r.keys()
            rows.append(prov + (
                r["text"] if "text" in keys else None,
                r["fill_into_edit"] if "fill_into_edit" in keys else None,
                r["url"] if "url" in keys else None,
                r["contents"] if "contents" in keys else None,
                r["description"] if "description" in keys else None,
                _fmt_webkit(r["last_access_time"]) if "last_access_time" in keys else "",
                r["number_of_hits"] if "number_of_hits" in keys else None))
        writer.add("browser_shortcuts", _PROV_COLS + [
            "text", "fill_into_edit", "url", "contents", "description",
            "last_access_time", "number_of_hits"], rows)
    finally:
        conn.close()


def _parse_chromium_predictor(ps, writer, now, tmp_dir):
    """Network Action Predictor DB: address-bar text pre-rendered (typed even
    if the user never pressed Enter)."""
    src = os.path.join(ps.root_dir, "Network Action Predictor")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn or not _has_table(conn, "network_action_predictor"):
        if conn:
            conn.close()
        return
    try:
        prov = _prov_tuple(ps, src, now)
        rows = []
        for r in conn.execute("SELECT * FROM network_action_predictor"):
            keys = r.keys()
            rows.append(prov + (
                r["user_text"] if "user_text" in keys else None,
                r["id"] if "id" in keys else None,
                r["number_of_hits"] if "number_of_hits" in keys else None,
                r["number_of_misses"] if "number_of_misses" in keys else None))
        writer.add("browser_network_predictor", _PROV_COLS + [
            "user_text", "url_id", "hit_count", "miss_count"], rows)
    finally:
        conn.close()


def _parse_chromium_favicons(ps, writer, now, tmp_dir):
    """Favicons DB: page URL <-> icon domain (survives History deletion)."""
    src = os.path.join(ps.root_dir, "Favicons")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn:
        return
    try:
        prov = _prov_tuple(ps, src, now)
        if _has_table(conn, "icon_mapping") and _has_table(conn, "favicons"):
            rows = []
            q = (
                "SELECT m.page_url, f.url AS icon_url, "
                "(SELECT MAX(last_updated) FROM favicon_bitmaps b WHERE b.icon_id=f.id) AS last_updated "
                "FROM icon_mapping m JOIN favicons f ON f.id=m.icon_id"
            )
            for r in conn.execute(q):
                icon_url = r["icon_url"] or ""
                domain = ""
                if "://" in icon_url:
                    domain = icon_url.split("://", 1)[1].split("/", 1)[0]
                rows.append(prov + (
                    r["page_url"], icon_url, domain, _fmt_webkit(r["last_updated"])))
            writer.add("browser_favicons", _PROV_COLS + [
                "page_url", "icon_url", "icon_domain", "last_updated"], rows)
    finally:
        conn.close()


def _encode_secret(blob) -> Tuple[Optional[str], str]:
    """Return (base64 of the encrypted blob, encryption scheme label).

    Detects the Chromium prefix: 'v10'/'v11' (AES-GCM, DPAPI-wrapped key),
    'v20' (App-Bound), or a raw DPAPI blob ('\\x01\\x00\\x00\\x00...'). We never
    decrypt here; we only classify and preserve.
    """
    if not blob:
        return None, "plaintext"
    try:
        raw = bytes(blob)
    except (TypeError, ValueError):
        return None, "unknown"
    if not raw:
        return None, "plaintext"
    b64 = base64.b64encode(raw).decode("ascii")
    prefix = raw[:3]
    if prefix == b"v10":
        return b64, "v10"
    if prefix == b"v11":
        return b64, "v11"
    if prefix == b"v20":
        return b64, "v20"
    if raw[:4] == b"\x01\x00\x00\x00":
        return b64, "dpapi"
    return b64, "unknown"


# ---------------------------------------------------------------------------
# Chromium: JSON-backed artifacts (Bookmarks, Preferences, Extensions) and the
# Local State master-key metadata
# ---------------------------------------------------------------------------

def _load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.debug("JSON load failed for %s: %s", path, exc)
        return None


def _parse_chromium_bookmarks(ps, writer, now):
    src = os.path.join(ps.root_dir, "Bookmarks")
    data = _load_json(src)
    if not data:
        return
    prov = _prov_tuple(ps, src, now)
    rows = []

    def walk(node, folder):
        if not isinstance(node, dict):
            return
        ntype = node.get("type")
        if ntype == "url":
            rows.append(prov + (
                folder, node.get("name"), node.get("url"),
                _fmt_webkit(node.get("date_added")),
                _fmt_webkit(node.get("date_last_used")), node.get("guid")))
        elif ntype == "folder" or "children" in node:
            new_folder = (folder + "/" + node.get("name", "")).strip("/") if node.get("name") else folder
            for child in node.get("children", []):
                walk(child, new_folder)

    for root_name, root in (data.get("roots") or {}).items():
        if isinstance(root, dict):
            walk(root, root_name)
    writer.add("browser_bookmarks", _PROV_COLS + [
        "folder", "name", "url", "date_added", "date_last_used", "guid"], rows)


def _flatten_prefs(obj, prefix, out, wanted_prefixes):
    """Collect a curated subset of Preferences keys (settings + anti-forensics
    tells) rather than every leaf, which would be enormous and noisy."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                _flatten_prefs(v, key, out, wanted_prefixes)
            else:
                if any(key.startswith(p) for p in wanted_prefixes):
                    out.append((key, str(v)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten_prefs(v, f"{prefix}[{i}]", out, wanted_prefixes)


def _parse_chromium_preferences(ps, writer, now):
    src = os.path.join(ps.root_dir, "Preferences")
    data = _load_json(src)
    if not data:
        # Present but unreadable (damaged clusters on an image) is not the same
        # as absent: raise so the profile's warnings say so.
        if os.path.isfile(src) and os.path.getsize(src) > 0:
            raise ValueError("Preferences is present but is not valid JSON")
        return
    prov = _prov_tuple(ps, src, now)
    # Anti-forensics + identity + configuration keys worth surfacing.
    wanted = [
        "profile.exit_type", "profile.last_engagement_time", "profile.created_by_version",
        "profile.name", "account_info", "browser.clear_data", "browser.last_clear_browsing_data_time",
        "download.default_directory", "savefile.default_directory", "selectfile.last_directory",
        "session.restore_on_startup", "homepage", "default_search_provider_data",
        "extensions.last_chrome_version", "signin.allowed", "sync.",
    ]
    collected: List[tuple] = []
    _flatten_prefs(data, "", collected, wanted)
    rows = [prov + (k, v, "preferences") for (k, v) in collected]
    writer.add("browser_preferences", _PROV_COLS + [
        "setting_key", "setting_value", "category"], rows)


def _ext_install_time(meta):
    """Chromium stores this as first_install_time (WebKit us); older builds
    used install_time. Both are strings in Secure Preferences."""
    for key in ("first_install_time", "install_time"):
        val = meta.get(key)
        if val is not None and str(val).isdigit():
            return _fmt_webkit(val)
    return ""


def _ext_state(meta):
    """There is no "state" key; Chromium records disable_reasons (0 = enabled)."""
    if "state" in meta and meta.get("state") is not None:
        return meta.get("state")
    dr = meta.get("disable_reasons")
    if dr is None:
        return ""
    try:
        return "enabled" if int(dr) == 0 else "disabled:%d" % int(dr)
    except (TypeError, ValueError):
        return str(dr)


def _parse_chromium_extensions(ps, writer, now):
    """Extensions: from Preferences' extensions.settings plus manifest scan."""
    prefs_path = os.path.join(ps.root_dir, "Secure Preferences")
    if not os.path.isfile(prefs_path):
        prefs_path = os.path.join(ps.root_dir, "Preferences")
    data = _load_json(prefs_path)
    prov = _prov_tuple(ps, prefs_path, now)
    rows = []
    settings = (((data or {}).get("extensions") or {}).get("settings") or {}) if data else {}
    for ext_id, meta in settings.items():
        if not isinstance(meta, dict):
            continue
        manifest = meta.get("manifest") or {}
        perms = manifest.get("permissions") or []
        rows.append(prov + (
            ext_id, manifest.get("name"), manifest.get("version"),
            manifest.get("description"),
            ",".join(str(p) for p in perms if isinstance(p, (str, int))),
            _ext_install_time(meta),
            1 if meta.get("from_webstore") else 0, _ext_state(meta),
            os.path.join(ps.root_dir, "Extensions", ext_id)))
    # Also scan the Extensions folder for anything not in settings.
    ext_dir = os.path.join(ps.root_dir, "Extensions")
    known = {r[7] for r in rows}
    if os.path.isdir(ext_dir):
        for ext_id in os.listdir(ext_dir):
            if ext_id in known or ext_id == "Temp":
                continue
            manifests = glob.glob(os.path.join(ext_dir, ext_id, "*", "manifest.json"))
            if not manifests:
                continue
            man = _load_json(manifests[0]) or {}
            perms = man.get("permissions") or []
            rows.append(prov + (
                ext_id, man.get("name"), man.get("version"), man.get("description"),
                ",".join(str(p) for p in perms if isinstance(p, (str, int))),
                "", None, None, os.path.dirname(manifests[0])))
    writer.add("browser_extensions", _PROV_COLS + [
        "extension_id", "name", "version", "description", "permissions",
        "install_time", "from_webstore", "state", "manifest_path"], rows)


def _chromium_last_version(ps):
    """The browser build that last wrote this profile.

    Chromium drops a plain-text `Last Version` file beside `Local State` in the
    User Data directory, holding the full version string of the build that last
    ran (e.g. "152.0.7977.83"). That is the version of the code that produced
    the artifacts in this profile, which is what an examiner needs when a schema
    or an encryption scheme changed between builds. `Preferences ->
    profile.created_by_version` is a different fact - the build that CREATED the
    profile - so it is only a fallback, never a substitute.
    """
    if ps.local_state_path:
        candidate = os.path.join(os.path.dirname(ps.local_state_path), "Last Version")
        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read(128).strip()
            # Guard the shape: a version string, not whatever else landed there.
            if text and len(text) < 64 and text[0].isdigit():
                return text
        except OSError:
            pass
    prefs = _load_json(os.path.join(ps.root_dir, "Preferences")) or {}
    return str(((prefs.get("profile") or {}).get("created_by_version") or ""))


def _parse_chromium_metadata(ps, writer, now):
    """One browser_metadata row per profile, capturing the DPAPI-wrapped master
    key from Local State so cookie/password blobs can be decrypted later."""
    os_key_b64 = None
    scheme = ""
    version = ""
    if ps.local_state_path and os.path.isfile(ps.local_state_path):
        ls = _load_json(ps.local_state_path) or {}
        oc = ls.get("os_crypt") or {}
        # Prefer the App-Bound key when present (v20 installs), else the
        # classic encrypted_key (v10/v11). Store raw base64 as found; the label
        # records which scheme it is.
        if oc.get("app_bound_encrypted_key"):
            os_key_b64 = oc.get("app_bound_encrypted_key")
            scheme = "app_bound_v20"
        elif oc.get("encrypted_key"):
            os_key_b64 = oc.get("encrypted_key")
            scheme = "dpapi_v10"
    version = _chromium_last_version(ps)
    prof_created = ""
    prefs = _load_json(os.path.join(ps.root_dir, "Preferences")) or {}
    prof_created = str(((prefs.get("profile") or {}).get("created_by_version") or ""))
    writer.add("browser_metadata", [
        "browser", "vendor", "user_name", "sid", "profile", "source_path",
        "version", "os_crypt_key_b64", "key_scheme", "profile_created", "parsed_at"],
        [(ps.browser, ps.vendor, ps.user_name, ps.sid, ps.profile,
          ps.local_state_path or ps.root_dir, version, os_key_b64, scheme,
          prof_created, now)])


# ---------------------------------------------------------------------------
# LevelDB reader (feeds Local Storage, Session Storage, IndexedDB)
#
# A pragmatic forensic reader: it parses the write-ahead .log files (which
# still hold uncommitted and DELETED records, valuable evidence) and the
# on-disk .ldb / .sst tables. Checksums are not verified on purpose, so
# partially corrupt stores still yield what they can.
# ---------------------------------------------------------------------------

_LEVELDB_MAGIC = 0xDB4775248B80FB57
_BLOCK_SIZE = 32768


def _read_varint(buf, pos):
    """Decode a base-128 varint. Returns (value, new_pos).

    LevelDB calls this LEB128 and protobuf calls it a base-128 varint; they are
    the same encoding, so one reader serves both the LevelDB tables below and
    the CacheStorage protobuf further down.

    A corrupt buffer can present a run of bytes that all have the continuation
    bit set, so the shift is capped - without it a damaged store spins building
    an unbounded integer instead of returning nothing.
    """
    result = 0
    shift = 0
    while pos < len(buf):
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
        if shift > 63:
            return 0, len(buf)
    return result, pos


def _leveldb_iter_log(path):
    """Yield (key, value, is_deleted, seq) from a LevelDB .log file."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return
    # Reassemble physical records into logical batches.
    pos = 0
    pending = bytearray()
    while pos + 7 <= len(data):
        block_off = pos % _BLOCK_SIZE
        if _BLOCK_SIZE - block_off < 7:
            pos += (_BLOCK_SIZE - block_off)
            continue
        # header: crc(4) length(2) type(1)
        length = struct.unpack_from("<H", data, pos + 4)[0]
        rectype = data[pos + 6]
        rec_start = pos + 7
        if rec_start + length > len(data):
            break
        chunk = data[rec_start:rec_start + length]
        pos = rec_start + length
        if rectype in (1, 2):  # FULL or FIRST
            pending = bytearray(chunk) if rectype == 2 else bytearray()
            if rectype == 1:
                yield from _leveldb_parse_batch(chunk)
                pending = bytearray()
            # FIRST: keep accumulating
        elif rectype in (3, 4):  # MIDDLE or LAST
            pending += chunk
            if rectype == 4:
                yield from _leveldb_parse_batch(bytes(pending))
                pending = bytearray()
        else:
            pending = bytearray()


def _leveldb_parse_batch(batch):
    """Parse a WriteBatch payload: seq(8) count(4) then entries."""
    if len(batch) < 12:
        return
    seq = struct.unpack_from("<Q", batch, 0)[0]
    count = struct.unpack_from("<I", batch, 8)[0]
    pos = 12
    for _ in range(count):
        if pos >= len(batch):
            break
        tag = batch[pos]
        pos += 1
        if tag == 1:  # kTypeValue
            klen, pos = _read_varint(batch, pos)
            key = batch[pos:pos + klen]
            pos += klen
            vlen, pos = _read_varint(batch, pos)
            value = batch[pos:pos + vlen]
            pos += vlen
            yield key, value, 0, seq
        elif tag == 0:  # kTypeDeletion
            klen, pos = _read_varint(batch, pos)
            key = batch[pos:pos + klen]
            pos += klen
            yield key, b"", 1, seq
        else:
            break


def _leveldb_iter_table(path):
    """Yield (key, value, is_deleted, seq) from a LevelDB .ldb/.sst table."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return
    if len(data) < 48:
        return
    footer = data[-48:]
    magic = struct.unpack_from("<Q", footer, 40)[0]
    if magic != _LEVELDB_MAGIC:
        return
    # metaindex handle then index handle (varint offset,size each).
    p = 0
    _, p = _read_varint(footer, p)  # metaindex offset
    _, p = _read_varint(footer, p)  # metaindex size
    idx_off, p = _read_varint(footer, p)
    idx_size, p = _read_varint(footer, p)
    index_block = _leveldb_read_block(data, idx_off, idx_size)
    if index_block is None:
        return
    # Each index entry's value is a BlockHandle for a data block.
    for _key, handle in _leveldb_block_entries(index_block):
        hp = 0
        d_off, hp = _read_varint(handle, hp)
        d_size, hp = _read_varint(handle, hp)
        block = _leveldb_read_block(data, d_off, d_size)
        if block is None:
            continue
        for ikey, value in _leveldb_block_entries(block):
            if len(ikey) < 8:
                yield ikey, value, 0, 0
                continue
            trailer = struct.unpack_from("<Q", ikey, len(ikey) - 8)[0]
            vtype = trailer & 0xFF
            seq = trailer >> 8
            user_key = ikey[:-8]
            yield user_key, value, (1 if vtype == 0 else 0), seq


def _leveldb_read_block(data, offset, size):
    """Read a block, decompressing snappy/zstd if flagged. Returns content
    bytes (without the restart trailer stripped)."""
    if offset + size + 5 > len(data):
        return None
    raw = data[offset:offset + size]
    comp = data[offset + size]  # compression type byte follows block data
    if comp == 0:
        return raw
    if comp == 1 and _snappy is not None:
        try:
            return _snappy.decompress(raw)
        except Exception:
            return None
    # zstd (4) and others not decoded here.
    return None


def _leveldb_block_entries(block):
    """Yield (key, value) from a LevelDB block, resolving prefix-compressed
    keys via the restart points."""
    if len(block) < 4:
        return
    num_restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    restart_arr_start = len(block) - 4 - 4 * num_restarts
    if restart_arr_start < 0:
        return
    pos = 0
    prev_key = b""
    while pos < restart_arr_start:
        shared, pos = _read_varint(block, pos)
        non_shared, pos = _read_varint(block, pos)
        value_len, pos = _read_varint(block, pos)
        if pos + non_shared + value_len > len(block):
            break
        key_delta = block[pos:pos + non_shared]
        pos += non_shared
        value = block[pos:pos + value_len]
        pos += value_len
        key = prev_key[:shared] + key_delta
        prev_key = key
        yield key, value


def iter_leveldb(dir_path):
    """Yield (key, value, is_deleted, seq) across every log and table in a
    LevelDB directory."""
    if not os.path.isdir(dir_path):
        return
    for fname in sorted(os.listdir(dir_path)):
        full = os.path.join(dir_path, fname)
        if not os.path.isfile(full):
            continue
        low = fname.lower()
        try:
            if low.endswith(".log"):
                yield from _leveldb_iter_log(full)
            elif low.endswith(".ldb") or low.endswith(".sst"):
                yield from _leveldb_iter_table(full)
        except Exception as exc:
            logger.debug("LevelDB parse of %s failed: %s", full, exc)


def _decode_ls_value(value: bytes) -> str:
    """Decode a Chromium Local Storage value. First byte is an encoding flag:
    0 -> UTF-16-LE, 1 -> Latin-1/UTF-8."""
    if not value:
        return ""
    flag = value[0]
    body = value[1:]
    try:
        if flag == 0:
            return body.decode("utf-16-le", errors="replace")
        return body.decode("utf-8", errors="replace")
    except Exception:
        return body.decode("latin-1", errors="replace")


def _printable(raw: bytes, limit: int = 2048) -> str:
    """Best-effort text rendering of an arbitrary byte string for a DB cell."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw[:limit]
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    text = "".join(ch if (ch.isprintable() or ch in "\t\n") else "." for ch in text)
    return text[:limit]


# ---------------------------------------------------------------------------
# Full extraction: copy a payload into the case folder and inventory it
# ---------------------------------------------------------------------------

def _sha1_file(path: str) -> str:
    try:
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _extract_dir_for(ps: ProfileSource, extract_root: str, artifact: str) -> str:
    safe = lambda s: "".join(c if c.isalnum() or c in "-._" else "_" for c in (s or "x"))
    # Keyed on the profile's folder too: two sources in one case can both
    # hold Chrome\bob\Default, and their f_000001 bodies would overwrite.
    # Crow-Claw's copy of a live profile is keyed on the folder it was copied
    # from, so its payloads land beside the live parse's: the same body is
    # reused rather than extracted twice, and its rows name the same file.
    root = original_profile_path(ps.root_dir or "")
    tag = hashlib.sha1(os.path.normcase(os.path.normpath(root))
                       .encode("utf-8", "replace")).hexdigest()[:8]
    path = os.path.join(extract_root, safe(ps.browser), safe(ps.user_name),
                        safe(ps.profile) + "_" + tag, artifact)
    os.makedirs(path, exist_ok=True)
    return path


def _versioned_dest(dest: str, new_sha1: str) -> str:
    """Where a payload goes without overwriting a different one.

    Chrome recycles cache file names (f_00000a), so a re-parse used to copy a
    new body over the file an earlier browser_cache / browser_files row still
    described. A destination holding the same bytes is reused (no copy); one
    holding different bytes gets this body's SHA-1 in its name."""
    if not os.path.exists(dest) or not new_sha1:
        return dest
    if _sha1_file(dest) == new_sha1:
        return dest
    root, ext = os.path.splitext(dest)
    return "%s.%s%s" % (root, new_sha1[:12], ext)


def _copy_payload(src: str, dest: str) -> str:
    """Copy ``src`` to ``dest`` (or its versioned name); returns the path used."""
    dest = _versioned_dest(dest, _sha1_file(src))
    if not os.path.exists(dest):
        shutil.copy2(src, dest)
    return dest


def _record_extracted(writer, ps, now, artifact, original_path, extracted_path):
    """Add a browser_files inventory row for an extracted payload."""
    try:
        size = os.path.getsize(extracted_path)
        mtime = format_forensic_timestamp(
            unix_timestamp_to_datetime(os.path.getmtime(extracted_path)))
    except OSError:
        size, mtime = 0, ""
    writer.add("browser_files", [
        "browser", "vendor", "user_name", "sid", "profile", "artifact",
        "original_path", "extracted_path", "size", "sha1", "mtime", "parsed_at"],
        [(ps.browser, ps.vendor, ps.user_name, ps.sid, ps.profile, artifact,
          original_path, extracted_path, size, _sha1_file(extracted_path), mtime, now)])


# ---------------------------------------------------------------------------
# Chromium: LevelDB-backed stores (Local Storage, Session Storage, IndexedDB,
# Service Worker CacheStorage, GCM push) and SNSS sessions
# ---------------------------------------------------------------------------

def _parse_chromium_localstorage(ps, writer, now):
    for store_kind, rel in (("local_storage", os.path.join("Local Storage", "leveldb")),
                            ("session_storage", "Session Storage")):
        ldb = os.path.join(ps.root_dir, rel)
        if not os.path.isdir(ldb):
            continue
        src = ldb
        rows = []
        for key, value, is_deleted, seq in iter_leveldb(ldb):
            origin = ""
            disp_key = ""
            try:
                if key[:1] == b"_" and b"\x00" in key:
                    origin_part, rest = key[1:].split(b"\x00", 1)
                    origin = origin_part.decode("utf-8", "replace")
                    disp_key = _decode_ls_value(rest) if rest[:1] in (b"\x00", b"\x01") else _printable(rest)
                elif key[:5] == b"META:":
                    origin = key[5:].decode("utf-8", "replace")
                    disp_key = "META"
                else:
                    disp_key = _printable(key)
            except Exception:
                disp_key = _printable(key)
            rows.append(_prov_tuple(ps, src, now) + (
                store_kind, origin, disp_key,
                _decode_ls_value(value) if not is_deleted else "",
                is_deleted, seq))
        writer.add("browser_local_storage", _PROV_COLS + [
            "store_kind", "origin", "key", "value", "is_deleted", "seq"], rows)


def _idb_decode_prefix(key):
    """Decode an IndexedDB LevelDB KeyPrefix.

    The first byte packs the byte-widths of three little-endian ids:
        bits 7-5 = len(database_id) - 1
        bits 4-2 = len(object_store_id) - 1
        bits 1-0 = len(index_id) - 1
    Returns (database_id, object_store_id, index_id, consumed) or None.
    """
    if not key:
        return None
    b = key[0]
    db_len = ((b >> 5) & 0x07) + 1
    os_len = ((b >> 2) & 0x07) + 1
    ix_len = (b & 0x03) + 1
    need = 1 + db_len + os_len + ix_len
    if len(key) < need:
        return None
    pos = 1
    db = int.from_bytes(key[pos:pos + db_len], "little"); pos += db_len
    store = int.from_bytes(key[pos:pos + os_len], "little"); pos += os_len
    index = int.from_bytes(key[pos:pos + ix_len], "little")
    return db, store, index, need


def _idb_utf16(raw):
    """Object-store names are stored as UTF-16 (big-endian on disk)."""
    if not isinstance(raw, (bytes, bytearray)):
        return ""
    for enc in ("utf-16-be", "utf-16-le"):
        try:
            text = raw.decode(enc).strip(chr(0))
            if text and all(ch.isprintable() for ch in text):
                return text
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def _idb_store_names(pairs):
    """Map (database_id, object_store_id) -> name from ObjectStoreMetaData keys.

    Key layout: <prefix(db,0,0)> 0x32 <object_store_id> <metadata_type>
    where metadata_type 0 is the store name.
    """
    names = {}
    for key, value in pairs:
        decoded = _idb_decode_prefix(key)
        if not decoded:
            continue
        db, _store, _index, used = decoded
        rest = key[used:]
        if db > 0 and len(rest) >= 3 and rest[0] == 0x32 and rest[2] == 0x00:
            text = _idb_utf16(value)
            if text:
                names[(db, rest[1])] = text
    return names


def _parse_chromium_indexeddb(ps, writer, now, extract_root):
    idb_root = os.path.join(ps.root_dir, "IndexedDB")
    if not os.path.isdir(idb_root):
        return
    for entry in sorted(os.listdir(idb_root)):
        if not entry.endswith(".leveldb"):
            continue
        ldb = os.path.join(idb_root, entry)
        origin = entry.replace(".indexeddb.leveldb", "")
        rows = []
        entries = list(iter_leveldb(ldb))
        # First pass: recover the object-store names this database declares.
        store_names = _idb_store_names([(k, v) for k, v, _d, _s in entries])
        for key, value, is_deleted, seq in entries:
            value_text = _printable(value)
            db_id = store_id = None
            decoded = _idb_decode_prefix(key)
            if decoded:
                db_id, store_id = decoded[0], decoded[1]
            store = store_names.get((db_id, store_id), "")
            if not store and store_id:
                store = "store_%d" % store_id
            database = "db_%d" % db_id if db_id else ""
            rows.append(_prov_tuple(ps, ldb, now) + (
                origin, database, store, _printable(key), value_text, None, is_deleted))
        writer.add("browser_indexeddb", _PROV_COLS + [
            "origin", "database_name", "object_store", "key", "value",
            "blob_path", "is_deleted"], rows)
        # Full extraction: copy any associated .blob store for this origin.
        blob_src = os.path.join(idb_root, entry.replace(".leveldb", ".blob"))
        if os.path.isdir(blob_src):
            dest = _extract_dir_for(ps, extract_root, os.path.join("indexeddb", origin))
            for root_d, _dirs, files in os.walk(blob_src):
                for f in files:
                    s = os.path.join(root_d, f)
                    rel = os.path.relpath(s, blob_src)
                    d = os.path.join(dest, rel)
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    try:
                        d = _copy_payload(s, d)
                        _record_extracted(writer, ps, now, "indexeddb_blob", s, d)
                    except OSError:
                        pass


def _cache_key_url(key):
    """The resource URL out of a Chromium cache key.

    **A cache key is not a URL.** Chromium double-keys its HTTP cache by the
    NetworkIsolationKey, so the key for a third-party resource carries the
    top-frame site and the frame site in front of the URL, space-separated,
    sometimes behind a `_dk_` marker:

        _dk_https://site.example https://site.example https://cdn.example/a.js

    Reading that string as a URL is what filled `browser_cache.url` with
    things that are not hosts. Measured on one real profile of 30,863 cache
    rows: 69.4% carried the double-keyed form, 11.4% a plain URL, and the rest
    were empty - and the domain parser downstream turned the first group into
    "hosts" like `localhost http`, which then propagated into the Browser
    dashboard's cache row and its anti-forensics domain list.

    The URL is the last space-separated field. Anything that does not then
    look like `scheme://host` is returned as empty rather than stored: some
    entries yield HTTP response-header text (a `Link:` header, a
    `Permissions-Policy` value) because Simple Cache keeps its metadata after
    the body, and a column holding a URL or nothing is worth more than one
    holding header debris that reads like evidence.

    Gecko prefixes its keys instead (`a,:https://...`), which the old code
    handled by splitting on the first colon - turning a bare `https://host/x`
    into `//host/x`. Cutting from the last scheme in the string covers both
    browsers and that case.
    """
    text = (key or "").strip()
    if not text:
        return ""
    if text.startswith("_dk_"):
        text = text[4:].strip()
    fields = text.split()
    if not fields:
        return ""

    # In a double-keyed cache key every field is an origin or a URL:
    # `<top-frame-site> <frame-site> <url>`. Header text is not - it opens with
    # something else, and that is how a `Permissions-Policy` value or a `Link:`
    # header is told apart from a key that merely has several fields.
    if len(fields) > 1 and not _CACHE_SCHEME_RE.match(fields[0]):
        return ""

    candidate = fields[-1]
    # A prefix may still be glued on with no space (Gecko's `a,:https://...`).
    # Only cut when there is a prefix to cut: a URL that already starts with a
    # scheme is left alone, or `/faviconV2?...&url=http://en.wikipedia.org` gets
    # chopped at its own query parameter and the request becomes the resource.
    if not _CACHE_SCHEME_RE.match(candidate):
        schemes = list(_CACHE_SCHEME_RE.finditer(candidate))
        if schemes:
            candidate = candidate[schemes[-1].start():]

    if _is_clean_cache_url(candidate):
        return candidate
    # Only now try unwrapping: a value that already parsed is returned
    # untouched, so this can rescue `"https://host"` without trimming a real
    # URL that happens to end in a bracket or a semicolon.
    unwrapped = candidate.strip("\"'<>")
    return unwrapped if _is_clean_cache_url(unwrapped) else ""


def _is_clean_cache_url(value):
    """`scheme://host...` with nothing in it that only a header would carry."""
    if not value or not _CACHE_URL_RE.match(value):
        return False
    return not any(ch in value for ch in '"<>')


_CACHE_SCHEME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://")
# No `<>"` and no comma in the host: those come from `Link:` headers and
# `Permissions-Policy` values, never from a cache key.
_CACHE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s?#<>\",]+")


def _simple_cache_key(path):
    """Read the URL key out of a Simple Cache entry file (<hash>_0).

    Layout: SimpleFileHeader { u64 magic, u32 version, u32 key_length,
    u32 key_hash } followed by the key bytes. The key itself is run through
    `_cache_key_url`, because it is a cache key and not a URL.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return ""
    if len(head) < 20:
        return ""
    magic, _version, key_len, _key_hash = struct.unpack_from("<QIII", head, 0)
    if magic != _SIMPLE_CACHE_MAGIC64 or not (0 < key_len < 4096):
        return ""
    return _cache_key_url(head[20:20 + key_len].decode("utf-8", "replace"))


_SIMPLE_CACHE_EOF_MAGIC64 = 0xF4FA6F45970D41D8
_SIMPLE_CACHE_EOF_PACKED = struct.pack("<Q", _SIMPLE_CACHE_EOF_MAGIC64)
# SimpleFileEOF { u64 magic, u32 flags, u32 data_crc32, i32 stream_size }
_SIMPLE_CACHE_EOF_SIZE = 20


def _pb_fields(buf):
    """Walk a flat protobuf message, yielding (field_number, wire_type, value).

    `value` is an int for varint/fixed wire types and a bytes slice for
    length-delimited ones. Every read is bounds-checked and the walk stops at
    the first byte that is not a valid tag, so a truncated or mis-located
    buffer yields what it can and then nothing - it never raises and never
    runs off the end.
    """
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0 or wire not in (0, 1, 2, 5):
            return
        if wire == 0:
            value, pos = _read_varint(buf, pos)
            yield field, wire, value
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            if length < 0 or pos + length > len(buf):
                return
            yield field, wire, buf[pos:pos + length]
            pos += length
        elif wire == 5:
            if pos + 4 > len(buf):
                return
            yield field, wire, struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        else:
            if pos + 8 > len(buf):
                return
            yield field, wire, struct.unpack_from("<Q", buf, pos)[0]
            pos += 8


def _simple_cache_stream0(blob, key_len):
    """The metadata stream of a Simple Cache entry file.

    An entry file is laid out header, key, stream 1 (the response BODY), a
    SimpleFileEOF record, then stream 0 (the metadata) and its own EOF record.
    The metadata therefore sits AFTER the body, which is why reading forward
    from the key returns page content rather than headers.
    """
    first = blob.find(_SIMPLE_CACHE_EOF_PACKED, 20 + key_len)
    if first < 0:
        return b""
    start = first + _SIMPLE_CACHE_EOF_SIZE
    second = blob.find(_SIMPLE_CACHE_EOF_PACKED, start)
    return blob[start:second if second > 0 else len(blob)]


def _cachestorage_meta(stream0):
    """Decode a CacheStorage stream-0 protobuf.

    CacheStorage does not store a serialized HttpResponseInfo - there is no
    "HTTP/" literal anywhere in the file - so the status line cannot be found
    by text search the way the blockfile cache allows. The metadata is a
    protobuf, preceded by a short run of zero bytes:

        1 request  { 1: method }
        2 response { 1: status_code, 2: status_text, 4: repeated
                     header { 1: name, 2: value } }

    Returns (method, status, content_type, content_encoding, content_length,
    headers). Anything that does not parse yields empty values rather than a
    guess.
    """
    empty = ("", None, "", "", None, "")
    if not stream0:
        return empty
    start = 0
    while start < len(stream0) and stream0[start] == 0:
        start += 1
    body = stream0[start:]
    if not body:
        return empty

    method = ""
    status = None
    headers = {}
    for field, wire, value in _pb_fields(body):
        if field == 1 and wire == 2:                       # request
            for f2, w2, v2 in _pb_fields(value):
                if f2 == 1 and w2 == 2:
                    method = v2.decode("utf-8", "replace")[:16]
        elif field == 2 and wire == 2:                     # response
            for f2, w2, v2 in _pb_fields(value):
                if f2 == 1 and w2 == 0:
                    status = v2
                elif f2 == 4 and w2 == 2:                  # repeated header
                    name = val = ""
                    for f3, w3, v3 in _pb_fields(v2):
                        if f3 == 1 and w3 == 2:
                            name = v3.decode("utf-8", "replace")
                        elif f3 == 2 and w3 == 2:
                            val = v3.decode("utf-8", "replace")
                    if name:
                        headers[name.strip().lower()] = val.strip()

    if status is not None and not (100 <= status <= 599):
        status = None                                      # refuse a wild value
    length = None
    raw_len = headers.get("content-length", "")
    if raw_len.isdigit():
        length = int(raw_len)
    rendered = "\r\n".join("%s: %s" % (k, v) for k, v in headers.items())[:4000]
    return (method, status, headers.get("content-type", ""),
            headers.get("content-encoding", ""), length, rendered)


def _parse_chromium_service_worker(ps, writer, now, extract_root):
    """CacheStorage entries backed by the Simple Cache.

    Layout: Service Worker/CacheStorage/<origin-hash>/{index.txt, <cache-uuid>/}
    and each <cache-uuid> directory is a Simple Cache instance ("<hash>_0"
    files plus index/index-dir) - NOT a LevelDB, which is why scanning for
    .ldb/.log used to return nothing.
    """
    sw_root = os.path.join(ps.root_dir, "Service Worker", "CacheStorage")
    if not os.path.isdir(sw_root):
        return
    entries = []                      # (scope, entry path), in directory order
    for scope_dir in glob.glob(os.path.join(sw_root, "*")):
        if not os.path.isdir(scope_dir):
            continue
        scope = ""
        idx = os.path.join(scope_dir, "index.txt")
        if os.path.isfile(idx):
            try:
                with open(idx, "r", encoding="utf-8", errors="replace") as fh:
                    scope = fh.read().strip()
            except OSError:
                pass
        for cache_dir in glob.glob(os.path.join(scope_dir, "*")):
            if not os.path.isdir(cache_dir):
                continue
            try:
                names = os.listdir(cache_dir)
            except OSError:
                continue
            entries.extend((scope, os.path.join(cache_dir, name)) for name in names
                           if len(name) >= 18 and name[16:18] == "_0")

    def _one(item):
        scope, entry = item
        try:
            with open(entry, "rb") as handle:
                blob = handle.read()
        except OSError:
            return None
        if len(blob) < 24:
            return None
        magic, _version, key_len, _key_hash = struct.unpack_from("<QIII", blob, 0)
        if magic != _SIMPLE_CACHE_MAGIC64 or not (0 < key_len < 4096):
            return None
        url = blob[20:20 + key_len].decode("utf-8", "replace")
        if not url:
            return None
        method, status, ctype, cenc, clen, headers = _cachestorage_meta(
            _simple_cache_stream0(blob, key_len))
        return _prov_tuple(ps, entry, now) + (
            scope, url, "", clen if clen is not None else len(blob), "",
            method, status, ctype, cenc, headers)

    # The cost is the first open of each file (on-access antivirus scanning),
    # not the reading: measured 8.7 ms per cold open one at a time, 1.2 ms with
    # eight in flight. One Brave profile held 26,674 entries - 332 s of a
    # 373 s profile parse. map() keeps the order, so the rows are the same.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(_one, entries, chunksize=64) if r is not None]
    writer.add("browser_service_worker", _PROV_COLS + [
        "scope", "resource_url", "response_time", "content_length",
        "extracted_body_path", "request_method", "http_status", "content_type",
        "content_encoding", "server_headers"], rows)


def _gcm_split_key(ktext):
    """Split a GCM registration key into (app_id, origin, sender_id).

    The key is `<app_id>,<sender_id>`. Two app_id shapes occur:

      * a reverse-DNS product id - `com.google.chrome.sharing.fcm` - which is a
        browser feature, not a site, so there is no origin;
      * a Web Push registration - `wp:https://example.com/#<uuid>` - where the
        origin is the part after the `wp:` prefix and before the `#`.

    A key that does not split keeps the whole string as app_id rather than
    guessing, so a shape we have not seen never invents an origin.
    """
    app_id, _, sender_id = ktext.partition(",")
    origin = ""
    if app_id.startswith("wp:"):
        origin = app_id[3:].split("#", 1)[0]
    elif "://" in app_id:
        origin = app_id.split("#", 1)[0]
    return app_id, origin, sender_id


def _parse_chromium_push(ps, writer, now):
    gcm = os.path.join(ps.root_dir, "GCM Store", "Encryption")
    rows = []
    for cand in (gcm, os.path.join(ps.root_dir, "gcm_store")):
        if os.path.isdir(cand):
            for key, value, is_deleted, seq in iter_leveldb(cand):
                ktext = _printable(key)
                app_id, origin, sender_id = _gcm_split_key(ktext)
                rows.append(_prov_tuple(ps, cand, now) + (
                    app_id, origin, _printable(value), sender_id, ktext))
    writer.add("browser_push", _PROV_COLS + [
        "app_id", "origin", "registration_id", "sender_id", "source_key"], rows)


def _parse_chromium_media_router(ps, writer, now):
    """Cast/DLNA device discovery, read from Preferences media_router keys."""
    prefs = _load_json(os.path.join(ps.root_dir, "Preferences")) or {}
    mr = (prefs.get("media_router") or {})
    receiver = mr.get("receiver_id_hash_token")
    rows = []
    devices = (mr.get("device_id") or {})
    if isinstance(devices, dict):
        for name, meta in devices.items():
            rows.append(_prov_tuple(ps, os.path.join(ps.root_dir, "Preferences"), now) + (
                name, "", "", "", json.dumps(meta)[:500] if meta else "", ""))
    if receiver:
        rows.append(_prov_tuple(ps, os.path.join(ps.root_dir, "Preferences"), now) + (
            "receiver_id_hash_token", "", "", str(receiver), "", ""))
    writer.add("browser_media_router", _PROV_COLS + [
        "device_name", "device_type", "model_name", "ip_endpoint",
        "capabilities", "last_seen"], rows)


# --- SNSS session parsing --------------------------------------------------

def _snss_read_pickle_string(buf, pos):
    """Read a Chromium pickled 8-bit string: int32 byte-length + bytes,
    padded to a 4-byte boundary. Used for the navigation URL."""
    if pos + 4 > len(buf):
        return None, pos
    length = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if length < 0 or pos + length > len(buf):
        return None, pos
    data = buf[pos:pos + length]
    pos += length
    pad = (4 - (length % 4)) % 4
    pos += pad
    return data, pos


def _snss_read_pickle_string16(buf, pos):
    """Read a Chromium pickled UTF-16 string: int32 CHAR16 count + count*2
    bytes, padded to a 4-byte boundary. Used for the navigation title, which
    Chromium serialises as std::u16string (WriteString16)."""
    if pos + 4 > len(buf):
        return "", pos
    count = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    nbytes = count * 2
    if count < 0 or pos + nbytes > len(buf):
        return "", pos
    data = buf[pos:pos + nbytes]
    pos += nbytes
    pad = (4 - (nbytes % 4)) % 4
    pos += pad
    try:
        return data.decode("utf-16-le", "replace"), pos
    except Exception:
        return _printable(data), pos


def _snss_scavenge_text(page_state: bytes, exclude: str = "", limit: int = 500) -> str:
    """Pull readable UTF-16LE strings out of a serialized page_state blob.

    page_state (ExplodedPageState) embeds document/form field values as length-
    prefixed UTF-16 strings, but its full layout is version-specific. Rather than
    parse it exactly, we harvest UTF-16LE runs of >= 3 printable chars, drop the
    URL echoes and obvious noise, and join the distinct remainder. Best-effort:
    surfaces typed form content without a fragile structural parser."""
    if not page_state or len(page_state) < 6:
        return ""
    found = []
    seen = set()
    i, n = 0, len(page_state)
    while i + 2 <= n:
        # Greedily read a run of printable BMP UTF-16LE code units.
        j = i
        chars = []
        while j + 2 <= n:
            lo, hi = page_state[j], page_state[j + 1]
            if hi == 0 and 0x20 <= lo < 0x7F:
                chars.append(chr(lo))
                j += 2
            else:
                break
        if len(chars) >= 3:
            s = "".join(chars).strip()
            key = s.lower()
            noise = (s.startswith(("http", "chrome", "file:", "blob:", "about:", "<!--"))
                     or "Blink serialized form state" in s
                     or "dynamicFrame" in s
                     or s in ("No owner", "field ", "[field ]"))
            if s and key not in seen and s not in exclude and not exclude.startswith(s) \
                    and not noise:
                seen.add(key)
                found.append(s)
            i = j
        else:
            i += 2
    text = " | ".join(found)
    return text[:limit]


def _snss_commands(data):
    """Yield (command_id, payload) for every record in an SNSS stream.

    Header is magic(4) + version(4); each record is size(uint16) then one
    command-id byte followed by size-1 payload bytes.
    """
    pos = 8
    while pos + 2 <= len(data):
        size = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        if size == 0 or pos + size > len(data):
            return
        yield data[pos], data[pos + 1:pos + size]
        pos += size


# Session command ids. The two placement commands are what turn a flat list of
# navigations into "which window, which tab" - kCommandUpdateTabNavigation
# carries only a tab id and the navigation's index WITHIN that tab.
_SNSS_SET_TAB_WINDOW = 0           # payload: window_id(int32), tab_id(int32)
_SNSS_SET_TAB_INDEX_IN_WINDOW = 2  # payload: tab_id(int32), tab_index(int32)
_SNSS_UPDATE_TAB_NAVIGATION = 6    # payload: pickle_size, tab_id, nav_index, ...


def _snss_tab_placement(data):
    """First pass over an SNSS stream: where each tab actually sat.

    Returns (tab_to_window_ordinal, tab_to_index). Window ids are session-unique
    integers, not positions, so they are mapped to 0-based ordinals in the order
    the windows first appear - which is what the `window_index` column means.
    A tab with no placement command is simply absent from the maps, and stays
    NULL rather than being guessed at.
    """
    tab_window = {}
    tab_index = {}
    window_order = []
    for cmd_id, payload in _snss_commands(data):
        if len(payload) < 8:
            continue
        if cmd_id == _SNSS_SET_TAB_WINDOW:
            window_id, tab_id = struct.unpack_from("<ii", payload, 0)
            if window_id not in window_order:
                window_order.append(window_id)
            tab_window[tab_id] = window_order.index(window_id)
        elif cmd_id == _SNSS_SET_TAB_INDEX_IN_WINDOW:
            tab_id, index = struct.unpack_from("<ii", payload, 0)
            if index >= 0:
                tab_index[tab_id] = index
    return tab_window, tab_index


# Chrome before M86 kept its SNSS files in the profile folder itself, under
# these fixed names, instead of Sessions\Session_<n> / Tabs_<n>.
_LEGACY_SNSS_FILES = ("Current Session", "Last Session", "Current Tabs", "Last Tabs")


def _parse_chromium_sessions(ps, writer, now):
    files = []
    sess_dir = os.path.join(ps.root_dir, "Sessions")
    if os.path.isdir(sess_dir):
        files += [os.path.join(sess_dir, f) for f in sorted(os.listdir(sess_dir))
                  if f.startswith(("Session_", "Tabs_", "Apps_"))]
    files += [os.path.join(ps.root_dir, f) for f in _LEGACY_SNSS_FILES
              if os.path.isfile(os.path.join(ps.root_dir, f))]
    if not files:
        return
    rows = []
    for full in files:
        fname = os.path.basename(full)
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if data[:4] != b"SNSS":
            continue
        # Pass 1: tab placement. Pass 2: the navigations themselves, joined to
        # their window and tab on tab_id.
        tab_window, tab_index = _snss_tab_placement(data)
        for cmd_id, payload in _snss_commands(data):
            # The payload is a pickle beginning with its own size, then tab_id,
            # then the navigation's index within that tab, then the pickled url
            # and title strings.
            if cmd_id not in (_SNSS_UPDATE_TAB_NAVIGATION, 1) or len(payload) < 12:
                continue
            tab_id = struct.unpack_from("<i", payload, 4)[0]
            p = 12  # pickle size(4) + tab_id(4) + navigation index(4)
            url_b, p = _snss_read_pickle_string(payload, p)
            title, p = _snss_read_pickle_string16(payload, p)
            url = url_b.decode("utf-8", "replace") if url_b else ""
            # The next pickle string is the serialized page_state, which
            # embeds document/form field values. Scavenge readable text from
            # it (best-effort, guarded so a failure never loses url/title).
            form_text = ""
            try:
                page_state, _ = _snss_read_pickle_string(payload, p)
                if page_state:
                    form_text = _snss_scavenge_text(page_state, exclude=url)
            except Exception:
                form_text = ""
            if url.startswith("http") or url.startswith("file") or url.startswith("chrome"):
                rows.append(_prov_tuple(ps, full, now) + (
                    fname, tab_window.get(tab_id), tab_index.get(tab_id),
                    url, title, "", form_text, "navigation"))
    writer.add("browser_sessions", _PROV_COLS + [
        "session_file", "window_index", "tab_index", "url", "title",
        "referrer", "form_text", "entry_type"], rows)


# --- HTTP disk cache -------------------------------------------------------

# SimpleFileHeader.initial_magic_number is a uint64; verified against live
# Chromium/Edge cache entries (40/40 matched). An earlier uint32 constant here
# was a guess that matched nothing, so the Simple Cache branch silently never
# fired - a wrong magic left "for reference" is a trap, not a reference.
_SIMPLE_CACHE_MAGIC64 = 0xFCFB6D1BA7725C30


def _detect_encoding(head: bytes) -> str:
    if head[:2] == b"\x1f\x8b":
        return "gzip"
    if head[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg(body)"
    return ""


_BLOCKFILE_INDEX_MAGIC = 0xC103CAC3
_BLOCKFILE_DATA_MAGIC = 0xC104CAC3
_BLOCKFILE_HEADER = 8192
_BLOCKFILE_BLOCK_SIZE = {1: 36, 2: 256, 3: 1024, 4: 4096}


def _blockfile_addr(addr):
    """Decode a Chromium cache address (uint32).

    bit31 initialised, bits30-28 file type, bits27-24 block count - 1,
    bits23-16 file selector, bits15-0 block number. File type 0 means the
    payload lives in a separate f_XXXXXX file.
    """
    if not addr & 0x80000000:
        return None
    return (
        (addr >> 28) & 0x07,          # file type
        ((addr >> 24) & 0x0F) + 1,    # number of blocks
        (addr >> 16) & 0xFF,          # file selector
        addr & 0xFFFF,                # block number
    )


class _BlockfileReader:
    """Resolves cache addresses inside a blockfile cache directory."""

    def __init__(self, cache_dir):
        self.dir = cache_dir
        self._files = {}

    def _data_file(self, selector):
        if selector not in self._files:
            blob = b""
            path = os.path.join(self.dir, "data_%d" % selector)
            try:
                with open(path, "rb") as handle:
                    blob = handle.read()
            except OSError:
                blob = b""
            if len(blob) < 4 or struct.unpack_from("<I", blob, 0)[0] != _BLOCKFILE_DATA_MAGIC:
                blob = b""          # refuse to read a file that fails its magic
            self._files[selector] = blob
        return self._files[selector]

    def read(self, addr):
        decoded = _blockfile_addr(addr)
        if not decoded:
            return b""
        file_type, num_blocks, selector, block_number = decoded
        if file_type == 0:
            path = os.path.join(self.dir, "f_%06x" % block_number)
            try:
                with open(path, "rb") as handle:
                    return handle.read()
            except OSError:
                return b""
        size = _BLOCKFILE_BLOCK_SIZE.get(file_type)
        if not size:
            return b""
        blob = self._data_file(selector)
        start = _BLOCKFILE_HEADER + block_number * size
        end = start + size * num_blocks
        if start < 0 or start >= len(blob):
            return b""
        return blob[start:end]


# A cached HTTP response cannot predate the web or come from the far future.
# The window is deliberately generous - it is there to catch a mis-read offset,
# not to judge the evidence.
_CACHE_TIME_MIN_YEAR = 1995
_CACHE_TIME_MAX_YEAR = 2100


def _cache_times_from_stream0(raw, header_at):
    """The fetch times from a serialized HttpResponseInfo.

    `HttpResponseInfo::Persist` writes, after the pickle payload-size word:
    flags, a version word, then request_time and response_time as int64
    Chromium Time values - microseconds since 1601, the same epoch as the
    WebKit timestamps elsewhere in this parser.

    Offsets 12 and 20 were measured, not assumed: the first plausible
    (2015-2030) int64 in the preamble sits at 12 and the next at 20 on every
    entry checked, with request a fraction before response. `header_at` is
    where "HTTP/" begins; anything at or past it is header text, not a time,
    so a shorter preamble simply yields nothing rather than a wrong date.

    A value is also range-checked before it is kept. Reading these bytes from
    the wrong offset does NOT raise - `-1` decodes cleanly to the year 1600 -
    so without the window a mis-read produces a confident wrong timestamp,
    which is the failure mode this parser exists to avoid.

    Returns (request_time, response_time) as formatted strings, or ("", "").
    """
    if header_at < 28:
        return "", ""
    out = []
    for offset in (12, 20):
        value = struct.unpack_from("<q", raw, offset)[0]
        try:
            when = webkit_to_datetime(value)
            out.append(format_forensic_timestamp(when)
                       if _CACHE_TIME_MIN_YEAR <= when.year <= _CACHE_TIME_MAX_YEAR
                       else "")
        except Exception:
            out.append("")
    return out[0], out[1]


def _http_info_from_stream0(raw):
    """Parse a serialized Chromium HttpResponseInfo (cache stream 0).

    The response headers are stored as a NUL-separated run beginning with the
    status line. Located by the "HTTP/" marker rather than a fixed pickle
    offset, so it tolerates the pickle preamble changing between versions.

    Returns (status, content_type, content_encoding, content_length, headers,
    request_time, response_time).
    """
    empty = (None, "", "", None, "", "", "")
    if not raw:
        return empty
    start = raw.find(b"HTTP/")
    if start < 0:
        return empty
    end = raw.find(b"\x00\x00", start)
    block = raw[start:end if end > 0 else min(len(raw), start + 16384)]
    lines = [p.decode("utf-8", "replace") for p in block.split(b"\x00") if p]
    if not lines or not lines[0].startswith("HTTP/"):
        return empty

    status = None
    parts = lines[0].split()
    if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 3:
        status = int(parts[1])

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()

    length = None
    raw_len = headers.get("content-length", "")
    if raw_len.isdigit():
        length = int(raw_len)

    req_time, rsp_time = _cache_times_from_stream0(raw, start)

    return (status,
            headers.get("content-type", ""),
            headers.get("content-encoding", ""),
            length,
            "\r\n".join(lines[1:])[:4000],
            req_time,
            rsp_time)


def _blockfile_entries(cache_dir):
    """Walk the blockfile index and yield real cache entries.

    Yields dicts with url / status / content_type / content_encoding /
    content_length / headers. Only entries reachable from the index hash table
    are returned, so each one is an actual cache record rather than a URL
    string that happens to appear inside cached data.
    """
    index_path = os.path.join(cache_dir, "index")
    try:
        with open(index_path, "rb") as handle:
            index = handle.read()
    except OSError:
        return
    if len(index) < 0x30 or struct.unpack_from("<I", index, 0)[0] != _BLOCKFILE_INDEX_MAGIC:
        return
    table_len = struct.unpack_from("<I", index, 0x1C)[0]
    if not (0 < table_len <= 1 << 22):
        return
    table_off = len(index) - table_len * 4
    if table_off < 0x30:
        return

    reader = _BlockfileReader(cache_dir)
    for slot in range(table_len):
        pos = table_off + slot * 4
        if pos + 4 > len(index):
            break
        addr = struct.unpack_from("<I", index, pos)[0]
        if not addr:
            continue
        record = reader.read(addr)
        if len(record) < 0x60:
            continue
        key_len = struct.unpack_from("<I", record, 0x20)[0]
        long_key = struct.unpack_from("<I", record, 0x24)[0]
        if long_key:
            key_bytes = reader.read(long_key)[:key_len]
        else:
            key_bytes = record[0x60:0x60 + key_len] if 0 < key_len < 4096 else b""
        # The blockfile cache double-keys its entries the same way the Simple
        # Cache does, so this is a cache key, not a URL.
        url = _cache_key_url(key_bytes.split(b"\x00")[0].decode("utf-8", "replace"))
        stream0 = struct.unpack_from("<I", record, 0x38)[0]
        status, ctype, cenc, clen, headers, req_time, rsp_time = (
            _http_info_from_stream0(reader.read(stream0)) if stream0 else
            (None, "", "", None, "", "", ""))
        yield {
            "url": url,
            "status": status,
            "content_type": ctype,
            "content_encoding": cenc,
            "content_length": clen,
            "headers": headers,
            "request_time": req_time,
            "response_time": rsp_time,
        }


def _parse_chromium_cache(ps, writer, now, extract_root, tmp_dir):
    cache_dir = os.path.join(ps.root_dir, "Cache", "Cache_Data")
    if not os.path.isdir(cache_dir):
        cache_dir = os.path.join(ps.root_dir, "Cache")
    if not os.path.isdir(cache_dir):
        return
    files = os.listdir(cache_dir)
    simple = [f for f in files if len(f) >= 18 and f[16:18] == "_0"]
    prov = lambda src: _prov_tuple(ps, src, now)
    rows = []
    extract_dir = _extract_dir_for(ps, extract_root, "cache")

    if simple:
        cache_format = "simple"
        for f in simple:
            src = os.path.join(cache_dir, f)
            try:
                with open(src, "rb") as fh:
                    head = fh.read(1024)
            except OSError:
                continue
            url = ""
            if len(head) >= 20 and struct.unpack_from("<Q", head, 0)[0] == _SIMPLE_CACHE_MAGIC64:
                key_len = struct.unpack_from("<I", head, 12)[0]
                key_bytes = head[20:20 + key_len] if 0 < key_len < 4096 else b""
                url = _cache_key_url(key_bytes.decode("utf-8", "replace"))
            rows.append(prov(src) + (
                url, "", "", None, "", os.path.getsize(src), "", "", "", cache_format))
        writer.add("browser_cache", _PROV_COLS + [
            "url", "request_time", "response_time", "http_status", "content_type",
            "content_length", "content_encoding", "server_headers",
            "extracted_body_path", "cache_format"], rows)
        return

    # Blockfile: scavenge URLs from block files, and full-extract external
    # bodies (f_* files), detecting their transfer encoding.
    cache_format = "blockfile"
    urls = set()
    for block in ("data_1", "data_2", "data_3"):
        bpath = os.path.join(cache_dir, block)
        copied = _copy_sqlite_with_sidecars(bpath, tmp_dir) if os.path.isfile(bpath) else None
        if not copied:
            continue
        try:
            with open(copied, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        # Cache keys are stored as the URL, often double-keyed like
        # "1/0/https://example.com/...". Scan for http(s) runs.
        for marker in (b"https://", b"http://"):
            start = 0
            while True:
                i = blob.find(marker, start)
                if i < 0:
                    break
                end = i
                while end < len(blob) and 0x20 <= blob[end] < 0x7F:
                    end += 1
                urls.add(blob[i:end].decode("ascii", "replace"))
                start = end
    # Real cache records first: walk the index so each row is an actual entry
    # with its HTTP response metadata. The scavenge below then keeps any URL
    # string found in the block data that the index did not account for - those
    # are recovered strings, not entries, and are labelled as such.
    indexed = set()
    try:
        for entry in _blockfile_entries(cache_dir):
            indexed.add(entry["url"])
            rows.append(prov(cache_dir) + (
                entry["url"], entry["request_time"], entry["response_time"],
                entry["status"], entry["content_type"],
                entry["content_length"], entry["content_encoding"],
                entry["headers"], "", cache_format))
    except (OSError, struct.error, ValueError):
        pass

    for u in sorted(urls):
        if u in indexed:
            continue
        rows.append(prov(cache_dir) + (
            u, "", "", None, "", None, "", "", "", "blockfile_scan"))

    # External bodies -> full extraction.
    for f in files:
        if not f.startswith("f_"):
            continue
        src = os.path.join(cache_dir, f)
        copied = _copy_sqlite_with_sidecars(src, tmp_dir) if os.path.isfile(src) else None
        if not copied:
            continue
        dest = os.path.join(extract_dir, f)
        try:
            dest = _copy_payload(copied, dest)
        except OSError:
            continue
        try:
            with open(dest, "rb") as fh:
                head = fh.read(8)
        except OSError:
            head = b""
        rows.append(prov(src) + (
            "", "", "", None, "", os.path.getsize(dest), _detect_encoding(head),
            "", dest, cache_format))
        _record_extracted(writer, ps, now, "cache_body", src, dest)
    writer.add("browser_cache", _PROV_COLS + [
        "url", "request_time", "response_time", "http_status", "content_type",
        "content_length", "content_encoding", "server_headers",
        "extracted_body_path", "cache_format"], rows)


# ---------------------------------------------------------------------------
# Chromium: extension storage, reading list, network state, DIPS, media
# history, top sites
# ---------------------------------------------------------------------------

# Extension storage roots inside a Chromium profile: each is either a folder of
# per-extension LevelDB dirs, or a single shared LevelDB.
_EXT_STORAGE_ROOTS = [
    ("local_ext_settings", "Local Extension Settings", True),
    ("sync_ext_settings", "Sync Extension Settings", True),
    ("managed_ext_settings", "Managed Extension Settings", True),
    ("extension_state", "Extension State", False),
    ("extension_rules", "Extension Rules", False),
    ("extension_scripts", "Extension Scripts", False),
]


def _parse_chromium_extension_storage(ps, writer, now, extract_root):
    """LevelDB stores that back extensions (crypto-wallet vaults, password
    managers, etc.). Values are preserved verbatim; large values are also
    exported to browser_extracted/."""
    rows = []
    for store_kind, folder, per_extension in _EXT_STORAGE_ROOTS:
        base = os.path.join(ps.root_dir, folder)
        if not os.path.isdir(base):
            continue
        if per_extension:
            targets = [(os.path.basename(d), d) for d in glob.glob(os.path.join(base, "*"))
                       if os.path.isdir(d)]
        else:
            targets = [("", base)]
        for ext_id, ldb in targets:
            has_leveldb = any(f.endswith((".ldb", ".log")) for f in os.listdir(ldb)) \
                if os.path.isdir(ldb) else False
            if not has_leveldb:
                continue
            for key, value, is_deleted, seq in iter_leveldb(ldb):
                rows.append(_prov_tuple(ps, ldb, now) + (
                    ext_id, store_kind, _printable(key),
                    _printable(value) if not is_deleted else "", is_deleted, seq))
    writer.add("browser_extension_storage", _PROV_COLS + [
        "extension_id", "store_kind", "key", "value", "is_deleted", "seq"], rows)


def _parse_chromium_reading_list(ps, writer, now):
    """Reading list, from the Bookmarks JSON (reading_list root)."""
    src = os.path.join(ps.root_dir, "Bookmarks")
    data = _load_json(src)
    rows = []
    if data:
        rl = (data.get("roots") or {}).get("reading_list") or {}
        for node in rl.get("children", []) if isinstance(rl, dict) else []:
            if isinstance(node, dict) and node.get("type") == "url":
                rows.append(_prov_tuple(ps, src, now) + (
                    node.get("name"), node.get("url"),
                    _fmt_webkit(node.get("date_added")),
                    _fmt_webkit(node.get("date_last_used")),
                    "read" if node.get("read_status") else "unread"))
    writer.add("browser_reading_list", _PROV_COLS + [
        "title", "url", "date_added", "date_last_opened", "read_status"], rows)


def _parse_chromium_network_state(ps, writer, now):
    """Network Persistent State (alt-svc / QUIC), TransportSecurity (HSTS), and
    Reporting & NEL endpoints."""
    rows = []
    net_dir = os.path.join(ps.root_dir, "Network")

    nps = os.path.join(net_dir, "Network Persistent State")
    data = _load_json(nps)
    if isinstance(data, dict):
        net = data.get("net") or {}
        for server in (net.get("http_server_properties") or {}).get("servers", []) or []:
            if isinstance(server, dict):
                rows.append(_prov_tuple(ps, nps, now) + (
                    "alt_svc", server.get("server", ""),
                    json.dumps(server.get("alternative_service", ""))[:400], ""))
        for bh in (net.get("http_server_properties") or {}).get("broken_alternative_services", []) or []:
            if isinstance(bh, dict):
                rows.append(_prov_tuple(ps, nps, now) + (
                    "broken_alt_svc", bh.get("host", ""),
                    json.dumps(bh)[:400], _fmt_unix(bh.get("broken_until"))))

    ts = os.path.join(net_dir, "TransportSecurity")
    if not os.path.isfile(ts):
        ts = os.path.join(ps.root_dir, "TransportSecurity")
    tdata = _load_json(ts)
    if isinstance(tdata, dict):
        for host_hash, meta in tdata.items():
            if isinstance(meta, dict):
                rows.append(_prov_tuple(ps, ts, now) + (
                    "hsts", host_hash,
                    json.dumps({k: meta.get(k) for k in ("mode", "sts_include_subdomains") if k in meta})[:300],
                    _fmt_unix(meta.get("expiry"))))

    nel = os.path.join(net_dir, "Reporting and NEL")
    if os.path.isdir(nel) and any(f.endswith((".ldb", ".log")) for f in os.listdir(nel)):
        for key, value, is_deleted, seq in iter_leveldb(nel):
            ktext = _printable(key)
            if ktext:
                rows.append(_prov_tuple(ps, nel, now) + (
                    "reporting_nel", ktext, _printable(value)[:400], ""))

    writer.add("browser_network_state", _PROV_COLS + [
        "source", "host_or_key", "detail", "expiry"], rows)


def _parse_chromium_dips(ps, writer, now, tmp_dir):
    """DIPS (bounce-tracking) DB: per-site interaction and storage times."""
    src = os.path.join(ps.root_dir, "DIPS")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn or not _has_table(conn, "bounces"):
        if conn:
            conn.close()
        return
    try:
        rows = []
        for r in conn.execute("SELECT * FROM bounces"):
            rows.append(_prov_tuple(ps, src, now) + (
                _col(r, "site"),
                _fmt_webkit(_col(r, "first_bounce_time")),
                _fmt_webkit(_col(r, "last_bounce_time")),
                _fmt_webkit(_col(r, "first_user_activation_time")),
                _fmt_webkit(_col(r, "last_user_activation_time"))))
        writer.add("browser_dips", _PROV_COLS + [
            "site", "first_site_storage_time", "last_site_storage_time",
            "first_user_interaction_time", "last_user_interaction_time"], rows)
    finally:
        conn.close()


def _parse_chromium_media_history(ps, writer, now, tmp_dir):
    """Media History DB: per-origin playback and watch time."""
    src = os.path.join(ps.root_dir, "Media History")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn:
        return
    try:
        rows = []
        if _has_table(conn, "playbackSession") and _has_table(conn, "origin"):
            q = ("SELECT o.origin, s.url, s.duration_ms, s.position_ms, s.last_updated_time_s "
                 "FROM playbackSession s LEFT JOIN origin o ON o.id=s.origin_id")
            try:
                for r in conn.execute(q):
                    rows.append(_prov_tuple(ps, src, now) + (
                        _col(r, "origin"), _col(r, "url"),
                        (_col(r, "duration_ms") or 0) / 1000.0, None, None,
                        _fmt_unix(_col(r, "last_updated_time_s")),
                        (_col(r, "position_ms") or 0) / 1000.0))
            except sqlite3.Error:
                rows = []
        if not rows and _has_table(conn, "playback"):
            for r in conn.execute("SELECT * FROM playback"):
                rows.append(_prov_tuple(ps, src, now) + (
                    None, _col(r, "url"),
                    (_col(r, "watch_time_ms") or _col(r, "watchtime_ms") or 0) / 1000.0,
                    _col(r, "has_audio"), _col(r, "has_video"),
                    _fmt_unix(_col(r, "last_updated_time_s")), None))
        writer.add("browser_media_history", _PROV_COLS + [
            "origin", "url", "watch_time_seconds", "has_audio", "has_video",
            "last_updated", "position_seconds"], rows)
    finally:
        conn.close()


def _parse_chromium_top_sites(ps, writer, now, tmp_dir):
    """Top Sites DB: the most-visited tiles."""
    src = os.path.join(ps.root_dir, "Top Sites")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    # Chrome before ~M70 kept the same tiles in a `thumbnails` table (with
    # the page thumbnail beside them); url / title / url_rank are the same.
    table = next((t for t in ("top_sites", "thumbnails") if conn and _has_table(conn, t)), None)
    if not table:
        if conn:
            conn.close()
        return
    try:
        rows = []
        for r in conn.execute(f"SELECT url, title, url_rank FROM {table}"):
            rows.append(_prov_tuple(ps, src, now) + (
                _col(r, "url"), _col(r, "title"), _col(r, "url_rank")))
        writer.add("browser_top_sites", _PROV_COLS + ["url", "title", "url_rank"], rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Gecko (Firefox). Written now, verified later on a real profile (Firefox is
# not installed on the development host).
# ---------------------------------------------------------------------------

def _parse_gecko_places(ps, writer, now, tmp_dir):
    src = os.path.join(ps.root_dir, "places.sqlite")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn:
        return
    try:
        prov = _prov_tuple(ps, src, now)
        if _has_table(conn, "moz_places") and _has_table(conn, "moz_historyvisits"):
            rows = []
            q = (
                "SELECT p.url, p.title, p.visit_count, p.typed, p.last_visit_date, "
                "v.visit_date, v.visit_type, "
                "(SELECT p2.url FROM moz_historyvisits v2 JOIN moz_places p2 ON p2.id=v2.place_id "
                " WHERE v2.id=v.from_visit) AS from_url "
                "FROM moz_historyvisits v JOIN moz_places p ON p.id=v.place_id"
            )
            for r in conn.execute(q):
                rows.append(prov + (
                    r["url"], r["title"], r["visit_count"], r["typed"],
                    _fmt_prtime(r["last_visit_date"]), _fmt_prtime(r["visit_date"]),
                    r["visit_type"], r["from_url"]))
            writer.add("browser_gecko_history", _PROV_COLS + [
                "url", "title", "visit_count", "typed", "last_visit_time",
                "visit_time", "visit_type", "from_visit_url"], rows)
        if _has_table(conn, "moz_bookmarks"):
            rows = []
            q = (
                "SELECT b.title, p.url, b.dateAdded, b.lastModified, "
                "(SELECT bp.title FROM moz_bookmarks bp WHERE bp.id=b.parent) AS folder "
                "FROM moz_bookmarks b LEFT JOIN moz_places p ON p.id=b.fk WHERE b.type=1"
            )
            for r in conn.execute(q):
                rows.append(prov + (
                    r["folder"], r["title"], r["url"],
                    _fmt_prtime(r["dateAdded"]), _fmt_prtime(r["lastModified"])))
            writer.add("browser_gecko_bookmarks", _PROV_COLS + [
                "folder", "title", "url", "date_added", "last_modified"], rows)
        if _has_table(conn, "moz_annos"):
            rows = []
            q = (
                "SELECT p.url, a.content, a.dateAdded, a.lastModified "
                "FROM moz_annos a JOIN moz_places p ON p.id=a.place_id "
                "JOIN moz_anno_attributes n ON n.id=a.anno_attribute_id "
                "WHERE n.name='downloads/destinationFileURI'"
            )
            try:
                for r in conn.execute(q):
                    rows.append(prov + (
                        r["url"], r["content"], _fmt_prtime(r["dateAdded"]),
                        _fmt_prtime(r["lastModified"]), None))
                writer.add("browser_gecko_downloads", _PROV_COLS + [
                    "url", "target_path", "start_time", "end_time", "state"], rows)
            except sqlite3.Error:
                pass
    finally:
        conn.close()


def _parse_gecko_cookies(ps, writer, now, tmp_dir):
    src = os.path.join(ps.root_dir, "cookies.sqlite")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn or not _has_table(conn, "moz_cookies"):
        if conn:
            conn.close()
        return
    try:
        prov = _prov_tuple(ps, src, now)
        rows = []
        for r in conn.execute("SELECT * FROM moz_cookies"):
            keys = r.keys()
            rows.append(prov + (
                r["host"], r["name"], r["path"], r["value"],
                _fmt_prtime(r["creationTime"]) if "creationTime" in keys else "",
                _fmt_unix_scaled(r["expiry"]) if "expiry" in keys else "",
                _fmt_prtime(r["lastAccessed"]) if "lastAccessed" in keys else "",
                r["isSecure"] if "isSecure" in keys else None,
                r["isHttpOnly"] if "isHttpOnly" in keys else None))
        writer.add("browser_gecko_cookies", _PROV_COLS + [
            "host", "name", "path", "value", "creation_time", "expiry_time",
            "last_accessed", "is_secure", "is_httponly"], rows)
    finally:
        conn.close()


def _parse_gecko_formhistory(ps, writer, now, tmp_dir):
    src = os.path.join(ps.root_dir, "formhistory.sqlite")
    db = _copy_sqlite_with_sidecars(src, tmp_dir)
    if not db:
        return
    conn = _open_ro(db)
    if not conn or not _has_table(conn, "moz_formhistory"):
        if conn:
            conn.close()
        return
    try:
        prov = _prov_tuple(ps, src, now)
        rows = []
        for r in conn.execute("SELECT fieldname, value, timesUsed, firstUsed, lastUsed FROM moz_formhistory"):
            rows.append(prov + (
                r["fieldname"], r["value"], r["timesUsed"],
                _fmt_prtime(r["firstUsed"]), _fmt_prtime(r["lastUsed"])))
        writer.add("browser_gecko_formhistory", _PROV_COLS + [
            "field_name", "value", "times_used", "first_used", "last_used"], rows)
    finally:
        conn.close()


def _parse_gecko_logins(ps, writer, now):
    src = os.path.join(ps.root_dir, "logins.json")
    data = _load_json(src)
    if not data:
        return
    prov = _prov_tuple(ps, src, now)
    rows = []
    for entry in (data.get("logins") or []):
        rows.append(prov + (
            entry.get("hostname"), entry.get("encryptedUsername"),
            entry.get("encryptedPassword"), "nss_key4",
            _fmt_unix((entry.get("timeCreated") or 0) / 1000.0),
            _fmt_unix((entry.get("timeLastUsed") or 0) / 1000.0),
            entry.get("timesUsed")))
    writer.add("browser_gecko_credentials", _PROV_COLS + [
        "hostname", "username_encrypted_b64", "password_encrypted_b64",
        "encryption_version", "time_created", "time_last_used", "times_used"], rows)


def _mozlz4_decompress(path):
    """Decompress a mozLz40 file (sessionstore.jsonlz4). Returns text or None."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if raw[:8] != b"mozLz40\x00" or _lz4 is None:
        return None
    size = struct.unpack_from("<I", raw, 8)[0]
    try:
        out = _lz4.decompress(raw[12:], uncompressed_size=size)
        return bytes(out).decode("utf-8", "replace")
    except Exception as exc:
        logger.debug("mozlz4 decompress failed for %s: %s", path, exc)
        return None


def _parse_gecko_sessions(ps, writer, now):
    for name in ("sessionstore.jsonlz4", os.path.join("sessionstore-backups", "recovery.jsonlz4")):
        src = os.path.join(ps.root_dir, name)
        if not os.path.isfile(src):
            continue
        text = _mozlz4_decompress(src)
        if not text:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        prov = _prov_tuple(ps, src, now)
        rows = []
        for wi, window in enumerate(data.get("windows", [])):
            for ti, tab in enumerate(window.get("tabs", [])):
                idx = tab.get("index", 1) - 1
                entries = tab.get("entries", [])
                if 0 <= idx < len(entries):
                    e = entries[idx]
                    rows.append(prov + (
                        wi, ti, e.get("url"), e.get("title"),
                        json.dumps(tab.get("formdata", {}))[:1000] if tab.get("formdata") else "",
                        "current"))
                for e in entries:
                    rows.append(prov + (
                        wi, ti, e.get("url"), e.get("title"), "", "history"))
        writer.add("browser_gecko_sessions", _PROV_COLS + [
            "window_index", "tab_index", "url", "title", "form_text", "entry_type"], rows)
        return  # sessionstore wins over recovery


def _parse_gecko_localstorage(ps, writer, now, tmp_dir):
    """Firefox HTML5 local storage: legacy webappsstore.sqlite AND the modern
    per-origin storage/default/<origin>/ls/data.sqlite."""
    rows = []
    legacy = os.path.join(ps.root_dir, "webappsstore.sqlite")
    db = _copy_sqlite_with_sidecars(legacy, tmp_dir)
    if db:
        conn = _open_ro(db)
        if conn:
            try:
                if _has_table(conn, "webappsstore2"):
                    for r in conn.execute("SELECT * FROM webappsstore2"):
                        rows.append(_prov_tuple(ps, legacy, now) + (
                            _col(r, "originKey") or _col(r, "scope"),
                            _col(r, "key"), _printable(_col(r, "value")), "webappsstore"))
            finally:
                conn.close()
    storage_default = os.path.join(ps.root_dir, "storage", "default")
    if os.path.isdir(storage_default):
        for origin_dir in glob.glob(os.path.join(storage_default, "*")):
            ls_db = os.path.join(origin_dir, "ls", "data.sqlite")
            db = _copy_sqlite_with_sidecars(ls_db, tmp_dir)
            if not db:
                continue
            conn = _open_ro(db)
            if not conn:
                continue
            try:
                if _has_table(conn, "data"):
                    origin = os.path.basename(origin_dir)
                    for r in conn.execute("SELECT * FROM data"):
                        rows.append(_prov_tuple(ps, ls_db, now) + (
                            origin, _col(r, "key"),
                            _printable(_col(r, "value")), "storage_default"))
            finally:
                conn.close()
    writer.add("browser_gecko_localstorage", _PROV_COLS + [
        "origin", "key", "value", "source_kind"], rows)


def _parse_gecko_storage_idb(ps, writer, now, extract_root, tmp_dir):
    """Firefox IndexedDB: storage/default/<origin>/idb/*.sqlite (+ .files blobs
    exported for full extraction). Rows land in the shared browser_indexeddb."""
    storage_default = os.path.join(ps.root_dir, "storage", "default")
    if not os.path.isdir(storage_default):
        return
    rows = []
    for origin_dir in glob.glob(os.path.join(storage_default, "*")):
        origin = os.path.basename(origin_dir)
        idb_dir = os.path.join(origin_dir, "idb")
        if not os.path.isdir(idb_dir):
            continue
        for sqlite_file in glob.glob(os.path.join(idb_dir, "*.sqlite")):
            db = _copy_sqlite_with_sidecars(sqlite_file, tmp_dir)
            if not db:
                continue
            conn = _open_ro(db)
            if not conn:
                continue
            try:
                # Gecko keeps real metadata in its own tables - use them rather
                # than borrowing Chromium's LevelDB key-prefix scheme, which
                # does not exist here. object_store(id, name) names the store
                # and the database table carries the real database name.
                store_names = {}
                if _has_table(conn, "object_store"):
                    for sid, sname in conn.execute(
                            "SELECT id, name FROM object_store"):
                        store_names[sid] = sname or ""
                db_name = ""
                if _has_table(conn, "database"):
                    row = conn.execute("SELECT name FROM database LIMIT 1").fetchone()
                    if row:
                        db_name = row[0] or ""
                if not db_name:
                    db_name = os.path.basename(sqlite_file)

                if _has_table(conn, "object_data"):
                    for r in conn.execute("SELECT * FROM object_data LIMIT 100000"):
                        store_id = _col(r, "object_store_id")
                        rows.append(_prov_tuple(ps, sqlite_file, now) + (
                            origin, db_name,
                            store_names.get(store_id, ""),
                            _printable(_col(r, "key")), _printable(_col(r, "data")),
                            None, 0))
            except sqlite3.Error:
                pass
            finally:
                conn.close()
        # Full extraction of blob files stored beside the idb sqlite.
        for files_dir in glob.glob(os.path.join(idb_dir, "*.files")):
            dest = _extract_dir_for(ps, extract_root, os.path.join("gecko_idb", origin))
            for root_d, _dirs, files in os.walk(files_dir):
                for f in files:
                    s = os.path.join(root_d, f)
                    d = os.path.join(dest, os.path.relpath(s, files_dir))
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    try:
                        d = _copy_payload(s, d)
                        _record_extracted(writer, ps, now, "gecko_idb_blob", s, d)
                    except OSError:
                        pass
    writer.add("browser_indexeddb", _PROV_COLS + [
        "origin", "database_name", "object_store", "key", "value",
        "blob_path", "is_deleted"], rows)


# CacheFileMetadataHeader, all big-endian uint32:
#   version, fetchCount, lastFetched, lastModified, frecency, expirationTime,
#   keySize, flags   -> 32 bytes on version >= 2
_CACHE2_HEADER_FMT = ">IIIIIII"
_CACHE2_HEADER_LENS = (32, 28)          # with flags, then without
_CACHE2_TIME_MIN = 1_400_000_000        # 2014
_CACHE2_TIME_MAX = 2_100_000_000        # 2036


def _cache2_header(meta):
    """Locate and decode the cache2 metadata header.

    The header does NOT sit at a fixed offset: it is preceded by a metadata
    hash and one uint16 per 256 KB chunk of payload, so its position moves with
    the file size. An earlier fixed-offset attempt here read fetch counts in
    the billions for exactly that reason.

    So the header is found by VALIDATING it rather than by arithmetic - the
    first offset whose whole structure is self-consistent wins:

      * version 1-10 and a fetch count that is not absurd,
      * lastFetched and lastModified both plausible Unix seconds,
      * expirationTime either zero or plausible,
      * keySize placing the key inside the metadata and landing exactly on the
        NUL that terminates it.

    Measured across 925 live entries: 883 resolve, every one of them version 4
    with a 32-byte header, and lastFetched <= lastModified on all 883. The
    remainder yield nothing rather than a guess.

    Returns a dict, or None.
    """
    if not meta or len(meta) < 40:
        return None
    limit = min(len(meta) - 32, 72)
    for offset in range(0, max(limit, 0)):
        version, fetch, fetched, modified, frecency, expires, key_size = \
            struct.unpack_from(_CACHE2_HEADER_FMT, meta, offset)
        if not (1 <= version <= 10) or not (1 <= fetch <= 1_000_000):
            continue
        if not (_CACHE2_TIME_MIN < fetched < _CACHE2_TIME_MAX):
            continue
        if not (_CACHE2_TIME_MIN < modified < _CACHE2_TIME_MAX):
            continue
        if expires and not (_CACHE2_TIME_MIN < expires < _CACHE2_TIME_MAX):
            continue
        if not (0 < key_size < len(meta)):
            continue
        for header_len in _CACHE2_HEADER_LENS:
            end = offset + header_len + key_size
            if end < len(meta) and meta[end] == 0:
                return {
                    "version": version,
                    "fetch_count": fetch,
                    "last_fetched": fetched,
                    "last_modified": modified,
                    "frecency": frecency,
                    "expiration_time": expires,
                    "key_size": key_size,
                }
    return None


def _cache2_times(meta):
    """(request_time, response_time) for a Firefox cache2 entry.

    cache2 records `lastFetched` - when the resource was last actually fetched
    - which is the event both the timeline ("Resource fetched") and the browser
    dashboard's cache activity plot, so it fills `response_time`.

    `request_time` stays EMPTY. Firefox keeps no request time; the header's
    other date, `lastModified`, is when the entry was written, and writing it
    into a column that means "when the request was sent" would make the column
    mean two different things depending on the engine.
    """
    header = _cache2_header(meta)
    if not header:
        return "", ""
    try:
        return "", format_forensic_timestamp(
            unix_timestamp_to_datetime(header["last_fetched"]))
    except Exception:
        return "", ""


def _cache2_response_head(meta):
    """Pull the HTTP response head out of a Firefox cache2 metadata block.

    The metadata carries name/value elements terminated by NUL bytes; the
    element named "response-head" holds the raw status line and headers as
    text, for example:

        HTTP/2 200
        content-type: application/json
        content-encoding: br

    It is located by NAME rather than by a fixed offset, so it survives the
    metadata header layout differing between cache2 versions. Verified against
    1,142 live entries: 925 carried a status line (200 x922, 206 x3).

    Returns (status, content_type, content_encoding, content_length, headers).
    """
    empty = (None, "", "", None, "")
    if not meta:
        return empty
    idx = meta.find(b"response-head")
    if idx < 0:
        return empty
    start = meta.find(b"\x00", idx)
    if start < 0:
        return empty
    end = meta.find(b"\x00", start + 1)
    head = meta[start + 1:end if end > 0 else len(meta)]
    lines = head.decode("utf-8", "replace").split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        return empty

    status = None
    parts = lines[0].split()
    if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 3:
        status = int(parts[1])

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()

    length = None
    raw_len = headers.get("content-length", "")
    if raw_len.isdigit():
        length = int(raw_len)

    return (status,
            headers.get("content-type", ""),
            headers.get("content-encoding", ""),
            length,
            "\r\n".join(lines[1:])[:4000])


def _parse_gecko_cache(ps, writer, now, extract_root, tmp_dir):
    """Firefox cache2: each cache2/entries/<hash> file holds the response body
    followed by a metadata trailer whose start offset is the last 4 bytes; the
    metadata begins with the request URL key. We read the URL and full-extract
    the body."""
    cache_dir = ps.cache_dir
    if not cache_dir:
        # Derive from the profile path if discovery did not set it.
        cache_dir = os.path.join(ps.root_dir, "cache2", "entries")
    entries = os.path.join(cache_dir, "entries") if os.path.isdir(os.path.join(cache_dir, "entries")) else cache_dir
    if not os.path.isdir(entries):
        return
    rows = []
    extract_dir = _extract_dir_for(ps, extract_root, "gecko_cache")
    for fname in os.listdir(entries):
        fpath = os.path.join(entries, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        if len(blob) < 8:
            continue
        url = ""
        meta = b""
        try:
            # Last 4 bytes = offset of the metadata block within the file.
            meta_off = struct.unpack_from(">I", blob, len(blob) - 4)[0]
            if 0 < meta_off < len(blob):
                meta = blob[meta_off:]
                # metadata: version(4) fetchcount(4) lastFetch(4) lastMod(4)
                # frecency(4) expire(4) keySize(4) flags(4) then the key string.
                if len(meta) > 36:
                    key_size = struct.unpack_from(">I", meta, 32)[0]
                    key_bytes = meta[36:36 + key_size] if 0 < key_size < 8192 else b""
                    # `split(":", 1)[-1]` turned a bare `https://host/x` into
                    # `//host/x`; the helper cuts from the last scheme instead.
                    url = _cache_key_url(key_bytes.decode("utf-8", "replace"))
                    body = blob[:meta_off]
                else:
                    body = blob
            else:
                body = blob
        except Exception:
            body = blob
        dest = _versioned_dest(os.path.join(extract_dir, fname),
                               hashlib.sha1(body).hexdigest())
        try:
            if not os.path.exists(dest):
                with open(dest, "wb") as out:
                    out.write(body)
            _record_extracted(writer, ps, now, "gecko_cache_body", fpath, dest)
            body_head = body[:8]
        except OSError:
            dest = ""
            body_head = b""
        status, ctype, cenc, clen, headers = _cache2_response_head(meta)
        req_time, rsp_time = _cache2_times(meta)
        rows.append(_prov_tuple(ps, fpath, now) + (
            url, req_time, rsp_time, status, ctype,
            clen if clen is not None else len(body),
            cenc or _detect_encoding(body_head),
            headers, dest, "firefox_cache2"))
    writer.add("browser_cache", _PROV_COLS + [
        "url", "request_time", "response_time", "http_status", "content_type",
        "content_length", "content_encoding", "server_headers",
        "extracted_body_path", "cache_format"], rows)


def _gecko_last_version(ps):
    """The Firefox build that last opened this profile.

    Gecko's equivalent of Chromium's `Last Version` is `compatibility.ini`:

        [Compatibility]
        LastVersion=156.0.1_20260921121718/20260921121718

    Only the part before the underscore is the version; the rest is the build
    id repeated. Parsed by key name rather than by line number, because the
    section gains and loses keys between releases.
    """
    path = os.path.join(ps.root_dir, "compatibility.ini")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                name, sep, value = line.partition("=")
                if sep and name.strip().lower() == "lastversion":
                    version = value.strip().split("_")[0]
                    if version and version[0].isdigit():
                        return version
    except OSError:
        pass
    return ""


def _parse_gecko_metadata(ps, writer, now, extract_root):
    """Record a Firefox profile row and preserve the NSS key material
    (key4.db, cert9.db, logins.json) for later decryption of logins.json."""
    key_dir = _extract_dir_for(ps, extract_root, "gecko_keys")
    kept = []
    for name in ("key4.db", "cert9.db", "logins.json", "key3.db", "signons.sqlite"):
        s = os.path.join(ps.root_dir, name)
        if os.path.isfile(s):
            d = os.path.join(key_dir, name)
            try:
                d = _copy_payload(s, d)
                _record_extracted(writer, ps, now, "gecko_key_material", s, d)
                kept.append(name)
            except OSError:
                pass
    key_ref = os.path.join(key_dir, "key4.db") if "key4.db" in kept else None
    writer.add("browser_metadata", [
        "browser", "vendor", "user_name", "sid", "profile", "source_path",
        "version", "os_crypt_key_b64", "key_scheme", "profile_created", "parsed_at"],
        [(ps.browser, ps.vendor, ps.user_name, ps.sid, ps.profile, ps.root_dir,
          _gecko_last_version(ps), key_ref,
          "nss_key4" if key_ref else "", "", now)])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _parse_one_profile(ps, writer, now, tmp_dir, extract_root, warnings,
                       include_cache=True):
    """Dispatch every applicable artifact parser for a single profile,
    isolating each so one failure never aborts the profile or the run.

    ``include_cache=False`` skips the HTTP / Service Worker / Gecko caches -
    the bulk of a profile on disk - for a faster, smaller offline parse.
    """

    def run(label, fn, *args):
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 - guarded on purpose
            msg = f"{ps.browser}/{ps.profile}: {label} failed: {exc}"
            logger.warning("[Browser] %s", msg)
            warnings.append(msg)

    if ps.vendor in ("chromium", "electron"):
        if ps.vendor == "chromium":
            run("history", _parse_chromium_history, ps, writer, now, tmp_dir)
            run("cookies", _parse_chromium_cookies, ps, writer, now, tmp_dir)
            run("web_data", _parse_chromium_webdata, ps, writer, now, tmp_dir)
            run("login_data", _parse_chromium_logindata, ps, writer, now, tmp_dir)
            run("shortcuts", _parse_chromium_shortcuts, ps, writer, now, tmp_dir)
            run("predictor", _parse_chromium_predictor, ps, writer, now, tmp_dir)
            run("favicons", _parse_chromium_favicons, ps, writer, now, tmp_dir)
            run("bookmarks", _parse_chromium_bookmarks, ps, writer, now)
            run("preferences", _parse_chromium_preferences, ps, writer, now)
            run("extensions", _parse_chromium_extensions, ps, writer, now)
            run("metadata", _parse_chromium_metadata, ps, writer, now)
            run("sessions", _parse_chromium_sessions, ps, writer, now)
            run("push", _parse_chromium_push, ps, writer, now)
            run("media_router", _parse_chromium_media_router, ps, writer, now)
            if include_cache:
                run("cache", _parse_chromium_cache, ps, writer, now, extract_root, tmp_dir)
            run("reading_list", _parse_chromium_reading_list, ps, writer, now)
            run("network_state", _parse_chromium_network_state, ps, writer, now)
            run("dips", _parse_chromium_dips, ps, writer, now, tmp_dir)
            run("media_history", _parse_chromium_media_history, ps, writer, now, tmp_dir)
            run("top_sites", _parse_chromium_top_sites, ps, writer, now, tmp_dir)
        # Storage engines are shared by Chromium browsers and Electron apps.
        run("local_storage", _parse_chromium_localstorage, ps, writer, now)
        run("indexeddb", _parse_chromium_indexeddb, ps, writer, now, extract_root)
        if include_cache:
            run("service_worker", _parse_chromium_service_worker, ps, writer, now, extract_root)
        run("extension_storage", _parse_chromium_extension_storage, ps, writer, now, extract_root)
    elif ps.vendor == "gecko":
        run("places", _parse_gecko_places, ps, writer, now, tmp_dir)
        run("cookies", _parse_gecko_cookies, ps, writer, now, tmp_dir)
        run("formhistory", _parse_gecko_formhistory, ps, writer, now, tmp_dir)
        run("logins", _parse_gecko_logins, ps, writer, now)
        run("sessions", _parse_gecko_sessions, ps, writer, now)
        run("localstorage", _parse_gecko_localstorage, ps, writer, now, tmp_dir)
        run("storage_idb", _parse_gecko_storage_idb, ps, writer, now, extract_root, tmp_dir)
        if include_cache:
            run("cache", _parse_gecko_cache, ps, writer, now, extract_root, tmp_dir)
        run("metadata", _parse_gecko_metadata, ps, writer, now, extract_root)


def _forget_profile_rows(conn, ps: ProfileSource) -> None:
    """Drop the rows an earlier parse wrote for THIS profile, before re-reading it.

    Twelve tables have no UNIQUE key, so a second parse of the same case
    doubled them. Rows are matched on their own source path (``original_path``
    for browser_files), so other profiles and other sources are untouched.
    """
    prefixes = [os.path.join(d, "") for d in (ps.root_dir, ps.cache_dir) if d]
    for table in TABLE_SCHEMAS:
        col = "original_path" if table == "browser_files" else "source_path"
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            continue
        for p in prefixes:
            conn.execute(f"DELETE FROM {table} WHERE {col} = ? OR substr({col}, 1, ?) = ?",
                         (p[:-1], len(p), p))


def parse_browser_data(case_artifacts_dir, progress_callback=None,
                       windows_partition="C:", offline_mode=False,
                       source_roots=None, include_cache=True):
    """Parse browser artifacts into browser_analysis.db.

    Args:
        case_artifacts_dir: the case Target_Artifacts directory (output goes
            here as browser_analysis.db, with extracted payloads under
            browser_extracted/).
        progress_callback: optional callable(str) for status messages.
        windows_partition: accepted for call-site symmetry; a live parse always
            reads this host's own profiles, and offline / image callers pass
            ``source_roots`` built from the collected tree instead.
        offline_mode: when True, ``source_roots`` must be supplied - an
            offline parse never falls back to discovering this machine.
        source_roots: optional list of ProfileSource (see
            discover_offline_profiles). When None, live profiles are
            discovered on this host.
        include_cache: False skips the HTTP / Service Worker / Gecko caches.

    Returns:
        dict with success / statistics / errors / warnings / output_db.
    """
    def status(msg):
        # User / profile names come from the evidence and may be any script;
        # a cp1252 console would abort the whole parse on them.
        print(f"[Browser] {msg}".encode("ascii", "backslashreplace").decode("ascii"))
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    result = {"success": False, "statistics": {}, "errors": [], "warnings": [],
              "output_db": ""}

    os.makedirs(case_artifacts_dir, exist_ok=True)
    output_db = os.path.join(case_artifacts_dir, OUTPUT_DB_NAME)
    extract_root = os.path.join(case_artifacts_dir, "browser_extracted")
    os.makedirs(extract_root, exist_ok=True)
    result["output_db"] = output_db

    status("Discovering browser profiles...")
    if source_roots is None:
        if offline_mode:
            result["errors"].append("offline_mode requires source_roots")
            return result
        sources = discover_live_profiles()
    else:
        sources = list(source_roots)

    if not sources:
        status("No browser profiles found.")
        result["success"] = True  # nothing to do is not a failure
        # Still create an empty DB so the GUI/timeline see the family.
        conn = sqlite3.connect(output_db)
        create_schema(conn)
        conn.close()
        return result

    status(f"Found {len(sources)} profile(s): " +
           ", ".join(sorted({f'{s.browser}' for s in sources})))

    conn = sqlite3.connect(output_db)
    writer = _Writer(conn)   # first: its tally lists the indexes create_schema adds
    create_schema(conn)
    del _UNREAD[:]
    now = get_current_forensic_timestamp()
    warnings: List[str] = []

    tmp_dir = tempfile.mkdtemp(prefix="crow_browser_")
    try:
        for i, ps in enumerate(sources, 1):
            status(f"[{i}/{len(sources)}] {ps.browser} - {ps.user_name}\\{ps.profile}")
            # Earlier runs' rows are KEPT; the writer adds only what is new.
            _parse_one_profile(ps, writer, now, tmp_dir, extract_root, warnings,
                               include_cache=include_cache)
            conn.commit()
    finally:
        conn.commit()
        conn.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    result["statistics"] = dict(writer.stats)
    # Each database a running browser kept locked, by name: its rows are
    # missing from this parse (close the browser, or parse again elevated).
    for path in _UNREAD:
        warnings.append("Not read - locked by the running browser: %s" % path)
    result["warnings"] = warnings
    result["success"] = True
    tot = writer.tally.totals()
    result["records"] = tot["parsed"]
    result["inserted"] = tot["inserted"]
    result["duplicates"] = tot["duplicates"]
    result["tables"] = writer.tally.tables
    result["updated"] = sum(writer.updated.values())
    status(f"Done. {tot['parsed']} rows read across {len(writer.stats)} tables: "
           f"{tot['inserted']} new, {tot['duplicates']} already in the database. DB: {output_db}")
    return result


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Crow-Eye browser forensics parser")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "Target_Artifacts"),
                    help="output Target_Artifacts directory")
    args = ap.parse_args()

    res = parse_browser_data(args.out)
    print("[OK]" if res["success"] else "[FAIL]")
    for table, count in sorted(res["statistics"].items()):
        print(f"  {table}: {count}")
    if res["warnings"]:
        print(f"  warnings: {len(res['warnings'])}")
