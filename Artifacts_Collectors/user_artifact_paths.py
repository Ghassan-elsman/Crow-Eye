"""
user_artifact_paths - where a per-user file goes inside the case, shared by
every collector.

Every user has an ``NTUSER.DAT``, a ``UsrClass.dat``, a ``Recent`` folder and a
set of Jump Lists, and the files have the same names in every profile. The
collectors used to flatten them into one folder per type and rename the
collisions - ``NTUSER.DAT`` became ``NTUSER_1.DAT`` but its log became
``NTUSER.DAT_1.LOG1``, so no hive kept its own transaction log, and which user
got ``_1`` changed from run to run because the paths were expanded through a
``set``. Two parses of the same image gave 11,387 and 13,358 registry rows.

Here a per-user file keeps the part of its path that names its owner:

    Users\\<name>\\NTUSER.DAT                         (+ .LOG1 / .LOG2)
    Users\\<name>\\AppData\\Local\\Microsoft\\Windows\\UsrClass.dat
    Users\\<name>\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\...
    Windows\\ServiceProfiles\\<account>\\NTUSER.DAT
    Windows\\System32\\config\\systemprofile\\NTUSER.DAT

so a hive and its logs always sit together, and the folder says whose they are.
Machine-wide files (SAM, SYSTEM, Prefetch, ...) are not touched.

No imports beyond the standard library: the GUI, the three collectors and the
parsers all load this module.
"""

import json
import ntpath
import os
from typing import Dict, List, Optional, Tuple

# Collector type names whose files are per-user. Crow-Claw, the Offline
# Importer and image extraction share these names (Crow-Claw's ArtifactType
# values, the importer's normalised types).
PER_USER_TYPES = frozenset(("Registry", "link_jumplist", "LNK/Shortcut"))

# The registry of which source each case user folder came from.
USER_FOLDERS_FILE = "user_folders.json"


def _parts(path: str) -> List[str]:
    """Path components, whatever the separator. Drive and stream suffixes stay
    on their component; callers never use them as folder names."""
    return [p for p in (path or "").replace("/", "\\").split("\\") if p and p != "."]


def split_user_path(path: str, base: Optional[str] = None) -> Optional[Tuple[List[str], List[str]]]:
    """(owner_root, rest) for a file inside a user or service profile, else None.

    ``owner_root`` is the folder that identifies the owner, as the case keeps
    it (``['Users', 'Hunter']``, ``['Windows', 'ServiceProfiles',
    'LocalService']``); ``rest`` is the path below it, ending in the file name.

    ``base`` clamps the search to what was imported: a loose ``NTUSER.DAT``
    copied to ``C:\\Users\\Examiner\\Desktop\\triage`` belongs to nobody, and
    without the clamp it would be filed under the examiner.
    """
    parts = _parts(path)
    if base:
        base_parts = _parts(base)
        low = [p.lower() for p in parts]
        if low[:len(base_parts)] == [p.lower() for p in base_parts]:
            parts = parts[len(base_parts):]
        # A base that is not a prefix (a dissect path against a Windows base)
        # leaves the path as it is.
    low = [p.lower() for p in parts]

    # The LAST profile marker wins: an evidence folder can itself sit under
    # someone's Users folder (D:\Users\Examiner\cases\...\Users\Hunter\...).
    for i in range(len(low) - 1, -1, -1):
        name = low[i]
        if name == "users" and len(parts) > i + 2:
            return ["Users", parts[i + 1]], parts[i + 2:]
        if name == "serviceprofiles" and len(parts) > i + 2:
            return ["Windows", "ServiceProfiles", parts[i + 1]], parts[i + 2:]
        if name == "systemprofile" and len(parts) > i + 1:
            return ["Windows", "System32", "config", "systemprofile"], parts[i + 1:]
    return None


def user_relative_path(path: str, base: Optional[str] = None) -> Optional[str]:
    """``Users\\Hunter\\NTUSER.DAT`` style relative path, or None."""
    split = split_user_path(path, base)
    if not split:
        return None
    root, rest = split
    return ntpath.join(*(root + rest))


def collected_base(path: str) -> Optional[str]:
    """The case's ``live_acquisition`` folder above ``path``, or None.

    Per-user files are collected below it (``live_acquisition/<type>/Users/
    <name>/...``). A ``Users`` folder ABOVE it is the analyst's own profile -
    a case kept under ``C:\\Users\\<analyst>\\Documents`` - and must never name
    the owner of the evidence.
    """
    parts = _parts(path)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].lower() == "live_acquisition":
            return "\\".join(parts[:i + 1])     # compared part by part, any separator
    return None


def owner_from_path(path: str, base: Optional[str] = None) -> Optional[str]:
    """The profile name a collected or source path belongs to, or None.

    ``...\\Users\\Hunter\\NTUSER.DAT`` -> ``Hunter``;
    ``...\\ServiceProfiles\\LocalService\\NTUSER.DAT`` -> ``LocalService``;
    ``...\\systemprofile\\NTUSER.DAT`` -> ``systemprofile``.
    A case folder that had to be suffixed (``Hunter_2``, see
    UserFolderPlacer) is reported with its suffix: the folder is what the
    analyst can find on disk.

    ``base`` limits the search to what lies below it - pass
    ``collected_base(path)`` for anything in a case, or the analyst's own
    profile becomes the owner of every hive collected flat.
    """
    split = split_user_path(path, base)
    if not split:
        return None
    return split[0][-1]


def is_per_user_file(path: str, artifact_type: str, base: Optional[str] = None) -> bool:
    """True when a collected file must keep its owner's folder."""
    return artifact_type in PER_USER_TYPES and split_user_path(path, base) is not None


def _safe_component(name: str) -> str:
    """A path component that cannot climb out of the case or name a drive."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if (c in bad or ord(c) < 32) else c for c in name).strip(" .")
    return out or "_"


class UserFolderPlacer(object):
    """Chooses the case folder for each per-user file.

    One profile folder in the case holds one source's profile. A hive and its
    logs are placed by the same rule, so they cannot be split. When two
    sources have the same profile name - partition 3 and partition 5 of one
    image, or two images in one case - the second gets ``<name>_2``, decided
    by the source, never by the order files happen to arrive in.

    The choice is remembered in ``live_acquisition/user_folders.json``, so a
    re-run of the same source lands in the same folder instead of beside it.
    """

    def __init__(self, target_artifacts_dir: str):
        self.target_artifacts_dir = target_artifacts_dir
        self._registry_path = os.path.join(target_artifacts_dir, USER_FOLDERS_FILE)
        self._by_folder: Dict[str, str] = {}    # "<subdir>\\Users\\Hunter" (lower) -> source key
        self._by_source: Dict[str, str] = {}    # "<subdir>|<source key>" -> case folder (relative)
        self._dirty = False
        self._load()

    def _load(self):
        try:
            with open(self._registry_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        for folder, source in (data.get("folders") or {}).items():
            self._by_folder[folder.lower()] = source
            subdir = folder.split("\\", 1)[0]
            self._by_source["%s|%s" % (subdir.lower(), source)] = folder

    def save(self):
        """Persist the folder registry. Best effort: placement already happened."""
        if not self._dirty:
            return
        self._dirty = False
        folders = {}
        for key, folder in self._by_source.items():
            folders[folder] = key.split("|", 1)[1]
        try:
            os.makedirs(self.target_artifacts_dir, exist_ok=True)
            with open(self._registry_path, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "folders": dict(sorted(folders.items()))}, fh, indent=2)
        except OSError:
            pass

    def destination(self, subdir: str, path: str, source_key_prefix: str = "",
                    base: Optional[str] = None) -> Optional[str]:
        """Absolute case path for a per-user file, or None if it is not one.

        ``source_key_prefix`` names the source the path is relative to (an
        image + partition, an import folder, a live machine); together with the
        owner folder it is the source key the folder is reserved for.
        """
        split = split_user_path(path, base)
        if not split:
            return None
        root, rest = split
        source_parts = _parts(path)
        # The owner folder as it appears in the SOURCE (Hunter's profile on
        # partition 3), so the same user on another partition is a different key.
        low = [p.lower() for p in source_parts]
        owner_index = len(low) - len(rest)
        source_key = "%s|%s" % (source_key_prefix.lower(),
                                "\\".join(low[:owner_index]))
        reg_key = "%s|%s" % (subdir.lower(), source_key)

        folder = self._by_source.get(reg_key)
        if folder is None:
            safe_root = [_safe_component(p) for p in root]
            n = 1
            while True:
                tail = safe_root[-1] if n == 1 else "%s_%d" % (safe_root[-1], n)
                candidate = "\\".join([subdir] + safe_root[:-1] + [tail])
                owner = self._by_folder.get(candidate.lower())
                if owner is None or owner == source_key:
                    break
                n += 1
            folder = candidate
            self._by_folder[folder.lower()] = source_key
            self._by_source[reg_key] = folder
            self._dirty = True

        dest = os.path.join(self.target_artifacts_dir, *folder.split("\\"),
                            *[_safe_component(p) for p in rest])
        root_abs = os.path.normcase(os.path.abspath(self.target_artifacts_dir)) + os.sep
        if not os.path.normcase(os.path.abspath(dest)).startswith(root_abs):
            return None
        return dest
