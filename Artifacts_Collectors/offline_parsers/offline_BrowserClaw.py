"""
Offline Browser Parser Wrapper for Crow-eye
===========================================

Parses browser profiles collected from an offline folder or a forensic image
into the same ``browser_analysis.db`` (and the same 37 tables) as a live parse.

Collectors keep every profile's folder tree at
``live_acquisition/Browser/<source>/Users/<name>/AppData/...`` (``<source>`` is
``vol_<N>_<id>`` for an image partition, ``src_<folder>_<id>`` per imported
source and ``live`` for Crow-Claw). Owners come from that tree and the evidence's own
SOFTWARE hive, never from the analyst's machine:

  * the user name is the ``Users\\<name>`` folder the profile sits in;
  * the SID is the ProfileList entry whose ProfileImagePath ends in that
    folder, read from the hive collected with the evidence. Without one the
    SID stays empty.
"""

import os
import sys
import logging
import re

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from Browser_Claw import discover_offline_profiles, parse_browser_data
    from browser_paths import BROWSER_CASE_DIR, find_users_roots
    import user_identity
except ImportError:
    grandparent_dir = os.path.dirname(parent_dir)
    if grandparent_dir not in sys.path:
        sys.path.insert(0, grandparent_dir)
    from Artifacts_Collectors.Browser_Claw import discover_offline_profiles, parse_browser_data
    from Artifacts_Collectors.browser_paths import BROWSER_CASE_DIR, find_users_roots
    from Artifacts_Collectors import user_identity

logger = logging.getLogger(__name__)


def _say(msg):
    """print() kept ASCII: case paths and user names may be in any script."""
    print(str(msg).encode("ascii", "backslashreplace").decode("ascii"))

# Hive folders the collectors write: the Offline Importer / image extraction
# use Registry_Hives, a Crow-Claw collection uses Registry.
_HIVE_DIR_NAMES = ("Registry_Hives", "Registry Hives", "RegistryHives", "Registry")


_SOFTWARE_RE = re.compile(r"^software(_\d+)?(\.[a-z0-9]+)?$", re.I)
_HIVE_LOG_EXT = (".log", ".log1", ".log2", ".blf", ".regtrans-ms")


def _software_hives(case_path):
    """Every SOFTWARE hive collected into this case.

    All of them, not the first: a second install (another partition, a
    Windows.old) is stored as ``SOFTWARE_1``, and reading only one hid the
    conflict that should leave a folder name unmapped.
    """
    out = []
    acq = os.path.join(case_path, "live_acquisition")
    for name in _HIVE_DIR_NAMES:
        folder = os.path.join(acq, name)
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            low = entry.lower()
            if low.endswith(_HIVE_LOG_EXT) or not _SOFTWARE_RE.match(low):
                continue
            full = os.path.join(folder, entry)
            if os.path.isfile(full) and full not in out:
                out.append(full)
    return out


def evidence_sid_map(case_path):
    """``{profile folder name (lower-case): SID}`` from the case's own hives.

    Only ProfileList entries under a ``\\Users\\`` (or legacy ``Documents and
    Settings``) folder are used; service profiles under ``\\System32\\`` have
    no browser and would map ``systemprofile``. ``<SID>.bak`` (left by a
    temporary-profile failure) is the same account as ``<SID>``. When two
    hives name the same folder with different SIDs (two Windows installs) the
    folder is left unmapped rather than guessed.
    """
    sid_map, conflicts = {}, set()
    for hive in _software_hives(case_path):
        try:
            profiles = user_identity._profile_list(hive)
        except Exception as e:
            logger.debug("ProfileList unreadable in %s: %s", hive, e)
            continue
        for raw_sid, path in profiles.items():
            sid = raw_sid[:-4] if raw_sid.lower().endswith(".bak") else raw_sid
            low = (path or "").replace("/", "\\").lower()
            if "\\users\\" not in low and "\\documents and settings\\" not in low:
                continue
            folder = low.rstrip("\\").rsplit("\\", 1)[-1]
            if not folder:
                continue
            if folder in sid_map and sid_map[folder] != sid:
                conflicts.add(folder)
            sid_map.setdefault(folder, sid)
    for folder in conflicts:
        sid_map.pop(folder, None)
    return sid_map


def _inside(path, folder):
    p = os.path.normcase(os.path.abspath(path))
    f = os.path.normcase(os.path.abspath(folder))
    return p == f or p.startswith(f + os.sep)


def collected_users_dirs(case_path, artifact_dir=None):
    """Every collected ``Users`` folder of this case's browser trees.

    Only the case's own ``live_acquisition/Browser`` collection. The scan-index
    entry that triggered the parse (``artifact_dir``) is deliberately not
    added: a scan-only entry points at the evidence where it was found
    (possibly this machine's own C:\\Users), which was never collected, and a
    collected entry is already below ``Browser`` - adding it again by another
    spelling of the path (a subst or mapped drive) parsed every profile twice.
    """
    return find_users_roots(os.path.join(case_path, "live_acquisition", BROWSER_CASE_DIR))


def run_offline_browser(case_path, artifact_dir=None, include_cache=True, progress_callback=None):
    """
    Run browser analysis on a case's collected browser trees.

    Args:
        case_path (str): Path to the case directory
        artifact_dir (str): Optional folder from the scan index (a user folder
            or its Users parent); the case's whole Browser collection is
            parsed either way, so one source never hides another.
        include_cache (bool): False skips the HTTP / Service Worker / Gecko
            caches even where they were collected.
        progress_callback (callable): optional callable(str) for status text.

    Returns:
        dict: {success, records, statistics, output_path, warnings, error}
    """
    _say(f"[Offline Browser] Starting analysis for case: {case_path}")
    try:
        users_dirs = collected_users_dirs(case_path, artifact_dir)
        if not users_dirs:
            _say("[Offline Browser] No collected browser profiles in this case")
            return {"success": True, "records": 0, "statistics": {}, "output_path": "",
                    "warnings": [], "error": None}
        warnings = []
        # A SOFTWARE hive cannot be tied to the source it came from (hives are
        # stored flat), so SIDs are given only when the case holds ONE browser
        # source; with several, a user of one machine could take another's SID.
        sources_in_case = {os.path.normcase(os.path.dirname(os.path.normpath(u))) for u in users_dirs}
        sid_map = evidence_sid_map(case_path)
        if len(sources_in_case) > 1 and sid_map:
            warnings.append("This case holds browser trees from %d sources; SIDs were not "
                            "assigned, because a collected SOFTWARE hive cannot be tied to "
                            "one source." % len(sources_in_case))
            sid_map = {}
        _say(f"[Offline Browser] {len(users_dirs)} collected Users folder(s); "
             f"{len(sid_map)} profile SID(s) from the evidence hive")
        sources = discover_offline_profiles(users_dirs, sid_map=sid_map)
        _say(f"[Offline Browser] {len(sources)} browser profile(s) found")
        target = os.path.join(case_path, "Target_Artifacts")
        result = parse_browser_data(target, progress_callback=progress_callback,
                                    offline_mode=True, source_roots=sources,
                                    include_cache=include_cache)
        stats = result.get("statistics") or {}
        records = sum(stats.values())
        errors = result.get("errors") or []
        warnings += result.get("warnings") or []
        _say(f"[Offline Browser] {'[OK]' if result.get('success') else '[FAIL]'} "
             f"{records} rows across {len(stats)} tables")
        return {"success": bool(result.get("success")), "records": records,
                "statistics": stats, "output_path": result.get("output_db", ""),
                "warnings": warnings,
                "error": "; ".join(errors) if errors else None}
    except Exception as e:
        _say(f"[Offline Browser Error] {str(e)}")
        logger.exception("Offline browser parse failed")
        return {"success": False, "error": str(e), "records": 0, "statistics": {}}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_BrowserClaw.py <case_path>")
        sys.exit(1)
    run_offline_browser(sys.argv[1])
