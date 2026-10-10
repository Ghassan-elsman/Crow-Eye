"""
browser_paths - where browser evidence lives, shared by every collector.

The browser parser (Browser_Claw) needs each profile's folder tree intact:
every profile has its own ``History``, and only the folder a file sits in says
which user, browser and profile it belongs to. The live Crow-Claw collector,
the Offline Importer and forensic-image extraction all decide the same three
things from here, so they cannot drift apart:

  * which folders inside a browser tree are never copied (shader / GPU / model
    / crash caches the parser never reads),
  * which folders are the cache the "Include browser cache" toggle controls,
  * where inside the case a collected browser file goes.

No imports beyond the standard library: this module is loaded by the GUI, the
collectors and the parser wrapper alike.
"""

import hashlib
import ntpath
import os
import re
from typing import Optional

# Folders inside a browser tree that the browser parser never reads. Skipped on
# every collection. Compared case-insensitively by folder NAME.
BROWSER_SKIP_DIRS = frozenset(n.lower() for n in (
    "GPUCache", "Code Cache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "GraphiteDawnCache", "GrShaderCache", "ShaderCache", "Crashpad", "Crash Reports",
    "component_crx_cache", "extensions_crx_cache", "Safe Browsing",
    "OptimizationGuidePredictionModels", "optimization_guide_model_store",
    "WidevineCdm", "SwReporter", "Subresource Filter", "hyphen-data",
    "ZxcvbnData", "MEIPreload", "FileTypePolicies", "OriginTrials",
    "CertificateRevocation", "pnacl", "Dictionaries", "BrowserMetrics",
    "DeferredBrowserMetrics", "ScriptCache", "Media Cache", "startupCache",
    "thumbnails", "jumpListCache", "safebrowsing", "crashes", "minidumps",
))

# The HTTP cache, the Service Worker CacheStorage and Firefox's cache2: where
# the cache parsers read page bodies, and most of a profile's size on disk.
BROWSER_CACHE_DIRS = frozenset(n.lower() for n in ("Cache", "Cache_Data", "CacheStorage", "cache2"))

# The case folder (under live_acquisition) that holds collected browser trees.
BROWSER_CASE_DIR = "Browser"


def browser_dir_skipped(dir_name: str, include_cache: bool = True) -> bool:
    """True when a folder inside a collected browser tree should not be copied."""
    low = (dir_name or "").lower()
    if low in BROWSER_SKIP_DIRS:
        return True
    return (not include_cache) and low in BROWSER_CACHE_DIRS


# Folders under AppData that a profile root matched by a wildcard must not sit
# in: ``Local\Application Data`` is a junction back to ``Local`` itself (every
# profile would be copied twice), and ``Temp`` only holds throwaway profiles
# the parser's discovery never looks at.
_ROOT_EXCLUDED_DIRS = ("temp", "application data")


def browser_root_excluded(root_path: str) -> bool:
    """True when a matched browser root lies under AppData\\...\\Temp or the
    ``Application Data`` junction."""
    low = [p.lower() for p in (root_path or "").replace("/", "\\").split("\\") if p]
    if "appdata" in low:
        low = low[len(low) - 1 - low[::-1].index("appdata") + 1:]
    return any(p in _ROOT_EXCLUDED_DIRS for p in low)


def browser_path_skipped(rel_path: str, include_cache: bool = True) -> bool:
    """True when any FOLDER component of ``rel_path`` is skipped."""
    parts = [p for p in (rel_path or "").replace("/", "\\").split("\\") if p]
    return any(browser_dir_skipped(p, include_cache) for p in parts[:-1])


# Folder names that mark a path as part of a browser / Electron profile tree.
# Matched case-insensitively against path COMPONENTS, never substrings.
_BROWSER_ROOT_MARKERS = ("user data", "opera software", "mozilla", "librewolf", "waterfox",
                         "moonchild productions")
_ELECTRON_STORE_DIRS = ("local storage", "session storage", "indexeddb", "service worker",
                        "local extension settings", "sync extension settings",
                        "managed extension settings")


def _anchor_len(norm: str) -> int:
    """Path components that are the drive or UNC share, never a folder name."""
    drive = ntpath.splitdrive(norm)[0]
    return len([p for p in drive.split("\\") if p])


def _join(norm: str, parts, k: int) -> str:
    """The on-disk folder made of the first ``k`` components of ``norm``."""
    head = "\\".join(parts[:k])
    if norm.startswith("\\\\"):
        return "\\\\" + head
    if k == 1 and head.endswith(":"):
        return head + "\\"
    return head


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:8]


def _safe(name: str, limit: int = 24) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("_.")[:limit]


def browser_path_info(file_path: str, base: Optional[str] = None):
    """Where a browser file belongs, as ``(rel, root, volume_root)``, or None.

    * ``rel`` - ``<user>\\AppData\\...``: the part of the path the case tree
      keeps below ``Users``.
    * ``root`` - the folder on disk that ``rel``'s first component stands for
      (the user folder, or the folder holding a tree that has no user).
    * ``volume_root`` - the folder holding that ``Users`` folder: what tells
      one source's tree from another's (``HOST1\\C`` vs ``HOST2\\C``).

    Browser evidence is identified by WHERE it sits - ``History`` or
    ``Cookies`` mean nothing by name alone, and several filename rules
    (``.url``, ``SRU``, ``.pf``) would misfire on browser files.

    ``base`` is the folder being imported. A ``Users\\<name>`` ABOVE it is not
    the evidence's: every import on this machine sits under the analyst's own
    ``C:\\Users\\<me>``, and taking it attributed evidence to the analyst (and
    widened a scan to the analyst's whole profile).
    """
    norm = (file_path or "").replace("/", "\\")
    parts = [p for p in norm.split("\\") if p]
    low = [p.lower() for p in parts]
    anchor = _anchor_len(norm)
    base_n = 0
    if base:
        bnorm = os.path.normcase(os.path.normpath(base)).replace("/", "\\").rstrip("\\")
        if os.path.normcase(norm).startswith(bnorm + "\\"):
            base_n = len([p for p in bnorm.split("\\") if p])
    floor = max(anchor, base_n - 1)    # lowest index a user folder may have

    # Already inside a tree-preserving Browser collection (a case's, or a
    # Crow-Claw output being imported): ...\Browser\<source>\Users\<name>\...
    for b in range(len(low) - 4, -1, -1):
        if low[b] == BROWSER_CASE_DIR.lower() and low[b + 2] == "users" and b + 4 < len(low):
            return ("\\".join(parts[b + 3:]), _join(norm, parts, b + 4), _join(norm, parts, b + 2))

    def tree_ok(i):
        """Below AppData\\<i>: a Local / Roaming / LocalLow vendor tree with a
        browser marker, and no Temp folder before the marker."""
        tail = low[i + 1:]
        marks = [j for j, p in enumerate(tail) if p in _BROWSER_ROOT_MARKERS or p in _ELECTRON_STORE_DIRS]
        return bool(marks) and tail[0] in ("local", "roaming", "locallow") and "temp" not in tail[:marks[0]]

    # The INNERMOST <name>\AppData - under Users, or under any folder (a
    # collection that renamed or dropped Users: export\alice\AppData).
    for i in range(len(low) - 2, floor, -1):
        if low[i] == "appdata" and i - 1 >= floor and i - 1 >= anchor and tree_ok(i):
            user_i = i - 1
            rel = "\\".join(parts[user_i:])
            vol = user_i - 1 if user_i - 1 >= anchor and low[user_i - 1] == "users" else user_i
            return rel, _join(norm, parts, user_i + 1), _join(norm, parts, max(vol, anchor))

    # Windows XP: Documents and Settings\<name>\{Local Settings\}Application Data.
    for i in range(len(low) - 3, floor, -1):
        if low[i - 1] != "documents and settings" or i < max(floor, anchor + 1):
            continue
        if low[i + 1:i + 3] == ["local settings", "application data"]:
            rest, kind = parts[i + 3:], "Local"
        elif low[i + 1] == "application data":
            rest, kind = parts[i + 2:], "Roaming"
        else:
            continue
        if any(p.lower() in _BROWSER_ROOT_MARKERS for p in rest):
            rel = "\\".join([parts[i], "AppData", kind] + rest)
            return rel, _join(norm, parts, i + 1), _join(norm, parts, i - 1)

    # No owner anywhere: rebuild a plausible AppData path from the vendor
    # folder so discovery still works, under a pseudo-user named for the folder
    # the tree sits in - two loose trees never share one. Drive and share
    # components are never taken as vendor folders.
    def pseudo(holder_k, kind, tree):
        holder = _join(norm, parts, holder_k) if holder_k > 0 else norm
        label = _safe(parts[holder_k - 1] if holder_k > anchor else "root") or "root"
        user = f"_unattributed_{label}_{_short_hash(os.path.normcase(holder))}"
        return "\\".join([user, "AppData", kind] + tree), holder, holder

    if "user data" in low:
        u = len(low) - 1 - low[::-1].index("user data")
        # Up to two vendor folders (Google\Chrome), but never above the import.
        k = min(max(anchor, u - 2, base_n), u)
        return pseudo(k, "Local", parts[k:])
    for marker in _BROWSER_ROOT_MARKERS[1:]:
        if marker in low:
            m = len(low) - 1 - low[::-1].index(marker)
            if m >= anchor:
                return pseudo(m, "Roaming", parts[m:])
    return None


def browser_relative_path(file_path: str, base: Optional[str] = None) -> Optional[str]:
    """``<user>\\AppData\\...`` for a file inside a browser profile tree, else None.

    See browser_path_info; this is its ``rel`` alone.
    """
    info = browser_path_info(file_path, base)
    return info[0] if info else None


def browser_source_tag(volume_root: str, prefix: str = "src_") -> str:
    """The case folder name for one source's browser tree.

    Built from the full path of the folder holding the evidence's ``Users``
    folder, not its basename: two drive roots, two KAPE ``C`` folders and two
    hosts in one export each get their own tree instead of silently merging
    (an existing destination file is taken as already collected).
    """
    full = os.path.normcase(os.path.abspath(volume_root or ""))
    label = (_safe(os.path.basename(os.path.normpath(volume_root or "")))
             or _safe(os.path.splitdrive(full)[0].rstrip(":")) or "root")
    return f"{prefix}{label}_{_short_hash(full)}"


# Crow-Claw's source tag for the tree it copies from the machine it runs on
# (crow_claw/core/collector.py: <output>/Browser/live/<path below the volume>).
LIVE_SOURCE_TAG = "live"
_MANIFEST_NAME = "collection_manifest.json"
_partition_cache = {}


def _collection_partition(acq_dir: str) -> Optional[str]:
    """The Windows partition a Crow-Claw collection was taken from, read from
    the ``collection_manifest.json`` it wrote beside its Browser folder."""
    key = os.path.normcase(os.path.abspath(acq_dir))
    if key not in _partition_cache:
        part = None
        try:
            import json
            with open(os.path.join(acq_dir, _MANIFEST_NAME), "r", encoding="utf-8") as fh:
                part = ((json.load(fh) or {}).get("paths") or {}).get("windows_partition")
        except (OSError, ValueError, AttributeError):
            part = None
        part = str(part or "").strip().rstrip("\\/")
        _partition_cache[key] = part if re.match(r"^[A-Za-z]:$", part) else None
    return _partition_cache[key]


def collected_copy_origin(file_path: str):
    """``(copy_root, original_root)`` for a file in Crow-Claw's live browser
    copy, else None.

    Crow-Claw copies each profile to ``<output>\\Browser\\live\\<the path below
    the volume>`` - ``...\\Browser\\live\\Users\\bob\\AppData\\...`` is the copy of
    ``C:\\Users\\bob\\AppData\\...``. Here ``copy_root`` is that
    ``...\\Browser\\live`` folder and ``original_root`` the volume it was copied
    from (``C:``), taken from the collection's own manifest
    (``paths.windows_partition``) - never assumed. Without a manifest the copy
    is not mapped. Neither root ends in a separator.

    Used for a row's IDENTITY only: a profile parsed live and then again from
    the collected copy is the same evidence, and its rows must not be stored
    twice. The copy's path is still what the row records as its source.
    """
    norm = (file_path or "").replace("/", "\\")
    parts = [p for p in norm.split("\\") if p]
    low = [p.lower() for p in parts]
    for b in range(len(low) - 3, 0, -1):
        if (low[b] == BROWSER_CASE_DIR.lower() and low[b + 1] == LIVE_SOURCE_TAG
                and low[b + 2] == "users"):
            part = _collection_partition(_join(norm, parts, b))
            if not part:
                return None
            return _join(norm, parts, b + 2), part
    return None


def rebase_path(path: str, from_root: str, to_root: str) -> Optional[str]:
    """``path`` moved from below ``from_root`` to below ``to_root``, or None
    when it does not lie below ``from_root``. Case-insensitive, and blind to
    ``/`` versus ``\\`` and doubled separators."""
    if not isinstance(path, str) or not path:
        return None
    parts = [p for p in path.replace("/", "\\").split("\\") if p]
    root = [p.lower() for p in (from_root or "").replace("/", "\\").split("\\") if p]
    if not root or len(parts) <= len(root) or [p.lower() for p in parts[:len(root)]] != root:
        return None
    return "\\".join([to_root.rstrip("\\/")] + parts[len(root):])


def original_profile_path(file_path: str) -> str:
    """The path a collected copy was taken from (see collected_copy_origin),
    or ``file_path`` itself when it is not a mapped copy."""
    origin = collected_copy_origin(file_path)
    if not origin:
        return file_path
    return rebase_path(file_path, origin[0], origin[1]) or file_path


def find_users_roots(browser_dir: str, max_depth: int = 4):
    """Every ``Users`` folder below a case's Browser collection folder.

    Collections are laid out ``Browser/<source>/Users/<name>/AppData/...``
    (``<source>`` = ``vol_<N>_<id>`` for an image partition, ``src_<folder>_<id>``
    per imported source, ``live`` for Crow-Claw), so a case can hold several.
    """
    out = []
    if not browser_dir or not os.path.isdir(browser_dir):
        return out
    base_depth = browser_dir.rstrip("\\/").count(os.sep)
    for root, dirs, _files in os.walk(browser_dir):
        if root.rstrip("\\/").count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
            continue
        for d in list(dirs):
            if d.lower() == "users":
                out.append(os.path.join(root, d))
                dirs.remove(d)      # do not descend into a Users tree
    return sorted(out)
