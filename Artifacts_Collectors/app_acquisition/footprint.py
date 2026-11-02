"""What belongs to one application.

Every item carries the reason it was included and the user it belongs to, and
is shown to the examiner (ticked or not) before anything is copied:

- the program folder and its executables;
- per user: AppData Roaming / Local / LocalLow folders named after the program
  or its publisher\\program, its Local\\Packages folder (Store apps), and the
  temp files named after it;
- ProgramData folders named after it;
- the folders Prefetch shows the program loading files from (exact paths, so a
  cache kept somewhere unexpected is still found);
- its Prefetch files, its shortcuts (Start menu, Desktop, Recent) and its Jump
  Lists (by AppID);
- its registry keys: the Uninstall / App Paths entry and Software\\<publisher>\\
  <program> in the machine hive and each user's hive.

Matching is by name, so a broad folder is never taken whole: a publisher
folder is only searched for the program's subfolder, and folders such as
AppData\\Local\\Microsoft are never matched on their own.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from .catalog import AppEntry, norm_rel
from .registry import SOFTWARE, RegistryView

logger = logging.getLogger(__name__)

# Never a program's own folder, whatever its name matches.
_BROAD = {
    "microsoft", "windows", "temp", "tmp", "packages", "programs", "common files",
    "installer", "cache", "caches", "crashdumps", "d3dscache", "google", "apple",
    "mozilla", "intel", "nvidia", "amd", "package cache", "comms", "connecteddevicesplatform",
    "history", "inetcache", "logs", "log", "data", "user data", "default", "app", "apps",
    "software", "settings", "config", "update", "updates",
}
# Words that say nothing about which program it is.
_NOISE = {
    "the", "and", "for", "inc", "inc.", "ltd", "llc", "gmbh", "corp", "corporation", "co",
    "company", "limited", "software", "technologies", "technology", "x64", "x86", "64-bit",
    "32-bit", "bit", "edition", "version", "update", "setup", "installer", "beta", "preview",
}
_MIN_TOKEN = 4
# Executables nearly every program ships under the same name. Taken as a name key, 7-Zip's
# uninstall.exe made "uninstall" one, and every "Uninstall ....lnk" on the machine (Zoom, Node.js,
# Clink, a keyboard driver) was listed as 7-Zip's shortcut.
_GENERIC_EXES = {
    "uninstall", "uninst", "unins000", "unins001", "uninstaller", "setup", "install", "installer",
    "update", "updater", "autoupdate", "helper", "launcher", "crashreporter", "crashhandler",
    "elevate", "elevationservice", "notification_helper", "service", "agent", "host", "run", "start",
}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# A program folder's last part that names nothing (Chrome: ...\Chrome\Application).
_GENERIC_LEAVES = {"application", "app", "bin", "program", "current", "x64", "x86", "win64", "win32"}


def _install_leaf(install_dir: str) -> str:
    for part in reversed((install_dir or "").split("\\")):
        if part and part.lower() not in _GENERIC_LEAVES and not re.match(r"^(app-)?\d+(\.\d+)*$", part.lower()):
            return part
    return ""


def name_keys(app: AppEntry) -> Set[str]:
    """Squashed names a folder can be called after this program."""
    keys = set()
    exe_stems = [os.path.splitext(os.path.basename(e))[0] for e in app.exes]
    for raw in [app.name] + [s for s in exe_stems if s.lower() not in _GENERIC_EXES] + \
               ([_install_leaf(app.install_dir)] if app.install_dir else []):
        text = re.sub(r"\(.*?\)|\bv?\d+(\.\d+)+\b", " ", raw or "")
        words = [w for w in re.split(r"[\s_\-.]+", text.lower()) if w and w not in _NOISE]
        if words:
            keys.add(_squash("".join(words)))
            keys.add(_squash(words[0]))
    return {k for k in keys if len(k) >= _MIN_TOKEN and k not in {_squash(b) for b in _BROAD}}


def publisher_keys(app: AppEntry) -> Set[str]:
    """Squashed names of the publisher's container folder (Google, Microsoft...).
    Broad names are allowed here: a publisher folder is only ever searched for
    the program's own subfolder, never taken whole."""
    words = [w for w in re.split(r"[\s,._\-]+", (app.publisher or "").lower()) if w and w not in _NOISE]
    keys = {_squash("".join(words)), _squash(words[0])} if words else set()
    # Also the folder above the program folder (Program Files\Google\Chrome).
    parts = [p for p in (app.install_dir or "").split("\\") if p]
    leaf = _install_leaf(app.install_dir)
    if leaf in parts:
        i = parts.index(leaf)
        if i >= 1 and parts[i - 1].lower() not in ("program files", "program files (x86)", "programs", "appdata",
                                                   "local", "roaming", "users"):
            keys.add(_squash(parts[i - 1]))
    return {k for k in keys if len(k) >= 3}


def _is_container(name: str, pubs: Set[str]) -> bool:
    sq = _squash(name)
    return bool(sq) and any(sq == k or sq.startswith(k) for k in pubs)


@dataclass
class FootprintItem:
    kind: str                     # "folder" | "file" | "registry"
    path: str                     # volume-relative; registry: key path
    reason: str
    user: str = ""                # profile name, "" = machine-wide
    hive: str = ""                # registry only
    selected: bool = True
    size: Optional[int] = None    # bytes, filled by measure()
    files: Optional[int] = None

    def ident(self) -> str:
        return (self.kind, self.hive, self.path.lower()).__repr__()


@dataclass
class Footprint:
    app: AppEntry
    items: List[FootprintItem] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    _seen: Set[str] = field(default_factory=set)

    def add(self, item: FootprintItem):
        if item.kind != "registry":
            low = item.path.lower()
            # Already inside a folder that is on the list.
            for other in self.items:
                if other.kind == "folder" and low.startswith(other.path.lower() + "\\"):
                    return
        if item.ident() in self._seen:
            return
        self._seen.add(item.ident())
        self.items.append(item)


def _matches(name: str, keys: Set[str]) -> bool:
    sq = _squash(name)
    if not sq or name.lower() in _BROAD:
        return False
    return any(sq == k or sq.startswith(k) or (len(sq) >= _MIN_TOKEN and k.startswith(sq) and len(sq) >= 5)
               for k in keys)


def _contains(name: str, keys: Set[str]) -> bool:
    sq = _squash(name)
    return any(k in sq for k in keys)


def build_footprint(app: AppEntry, source, artifacts_dir: Optional[str] = None,
                    view: Optional[RegistryView] = None,
                    progress: Optional[Callable[[str], None]] = None) -> Footprint:
    view = view or RegistryView(source)
    fp = Footprint(app)
    keys = name_keys(app)
    pubs = publisher_keys(app)
    say = progress or (lambda _m: None)

    # Program folder and executables.
    # A per-user install (AppData\Local\Discord) belongs to that user.
    if app.install_dir and source.isdir(app.install_dir):
        fp.add(FootprintItem("folder", app.install_dir, "program folder", _user_of(app.install_dir)))
    for exe in app.exes:
        if source.isfile(exe):
            fp.add(FootprintItem("file", exe, "the program's executable", _user_of(exe)))

    # Per-user data.
    for user, profile in source.user_profiles():
        say("Looking through %s's profile" % user)
        for area in ("AppData\\Roaming", "AppData\\Local", "AppData\\LocalLow"):
            base = profile + "\\" + area
            for name, is_dir in source.listdir(base):
                if not is_dir:
                    continue
                path = base + "\\" + name
                if _matches(name, keys):
                    fp.add(FootprintItem("folder", path, "%s folder named after the program" % area.split("\\")[-1], user))
                elif pubs and _is_container(name, pubs):
                    for sub, sub_dir in source.listdir(path):
                        if sub_dir and _matches(sub, keys):
                            fp.add(FootprintItem("folder", path + "\\" + sub,
                                                 "%s\\<publisher>\\<program> folder" % area.split("\\")[-1], user))
        packages = profile + "\\AppData\\Local\\Packages"
        for name, is_dir in source.listdir(packages):
            pkg_family = app.package_full_name.split("_")[0].lower() if app.package_full_name else ""
            if is_dir and ((pkg_family and name.lower().startswith(pkg_family)) or _contains(name, {k for k in keys if len(k) >= 5})):
                fp.add(FootprintItem("folder", packages + "\\" + name, "Store app package data", user))
        temp = profile + "\\AppData\\Local\\Temp"
        for name, is_dir in source.listdir(temp):
            if _contains(name, {k for k in keys if len(k) >= 5}):
                fp.add(FootprintItem("folder" if is_dir else "file", temp + "\\" + name,
                                     "temp item named after the program", user, selected=False))
        for sc_dir in ("AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs", "Desktop",
                       "AppData\\Roaming\\Microsoft\\Windows\\Recent"):
            for rel, _size in _limited_walk(source, profile + "\\" + sc_dir, 400):
                if rel.lower().endswith(".lnk") and _contains(os.path.basename(rel), keys):
                    fp.add(FootprintItem("file", rel, "shortcut to the program", user))
        _jump_lists(source, profile, keys, fp, user)

    # Machine-wide.
    for name, is_dir in source.listdir("ProgramData"):
        if not is_dir:
            continue
        if _matches(name, keys):
            fp.add(FootprintItem("folder", "ProgramData\\" + name, "ProgramData folder named after the program"))
        elif pubs and _is_container(name, pubs):
            for sub, sub_dir in source.listdir("ProgramData\\" + name):
                if sub_dir and _matches(sub, keys):
                    fp.add(FootprintItem("folder", "ProgramData\\%s\\%s" % (name, sub),
                                         "ProgramData\\<publisher>\\<program> folder"))
    for rel, _size in _limited_walk(source, "ProgramData\\Microsoft\\Windows\\Start Menu\\Programs", 2000):
        if rel.lower().endswith(".lnk") and _contains(os.path.basename(rel), keys):
            fp.add(FootprintItem("file", rel, "Start menu shortcut (all users)"))
    for name, is_dir in source.listdir("Windows\\Temp"):
        if _contains(name, {k for k in keys if len(k) >= 5}):
            fp.add(FootprintItem("folder" if is_dir else "file", "Windows\\Temp\\" + name,
                                 "system temp item named after the program", selected=False))
    exe_names = {os.path.basename(e).upper() for e in app.exes}
    if app.name.lower().endswith(".exe"):
        exe_names.add(app.name.upper())
    # The Uninstall entry often names no executable (Discord: Update.exe runs
    # app-<ver>\Discord.exe): take the ones in the program folder, two deep.
    if app.install_dir:
        for name, is_dir in source.listdir(app.install_dir):
            if not is_dir and name.lower().endswith(".exe"):
                exe_names.add(name.upper())
            elif is_dir:
                for sub, sub_dir in source.listdir(app.install_dir + "\\" + name)[:200]:
                    if not sub_dir and sub.lower().endswith(".exe"):
                        exe_names.add(sub.upper())
    for name, is_dir in source.listdir("Windows\\Prefetch"):
        if not is_dir and name.upper().endswith(".PF") and name.upper().rsplit("-", 1)[0] in exe_names:
            fp.add(FootprintItem("file", "Windows\\Prefetch\\" + name, "Prefetch file of the program"))

    # Folders Prefetch shows the program loading files from.
    for folder in _prefetch_folders(artifacts_dir, exe_names):
        if source.isdir(folder):
            fp.add(FootprintItem("folder", folder, "the program loaded files from here (Prefetch)",
                                 _user_of(folder), selected=False))

    # Registry.
    say("Reading the registry")
    for key in app.registry_keys:
        if view.exists(key["hive"], key["path"]):
            fp.add(FootprintItem("registry", key["path"], key.get("why", "registry entry"),
                                 key["hive"].split(":", 1)[1] if key["hive"] != SOFTWARE else "",
                                 hive=key["hive"]))
    # HKLM\SOFTWARE\<key> and each user's HKCU\Software\<key>, 64- and 32-bit.
    bases = [(SOFTWARE, ""), (SOFTWARE, "WOW6432Node")]
    for hive in view.user_hives():
        bases += [(hive, "Software"), (hive, "Software\\WOW6432Node")]
    for hive, base_path in bases:
        user = hive.split(":", 1)[1] if hive != SOFTWARE else ""
        for sub in view.subkeys(hive, base_path):
            path = (base_path + "\\" + sub) if base_path else sub
            if _matches(sub, keys):
                fp.add(FootprintItem("registry", path, "registry key named after the program", user, hive=hive))
            elif pubs and _is_container(sub, pubs):
                for child in view.subkeys(hive, path):
                    if _matches(child, keys):
                        fp.add(FootprintItem("registry", path + "\\" + child,
                                             "Software\\<publisher>\\<program> key", user, hive=hive))
    for hive, why in view.unavailable.items():
        fp.notes.append("%s: %s" % (hive.replace("USER:", "user "), why))
    if not fp.items:
        fp.notes.append("Nothing was found for this program on %s." % source.describe())
    return fp


def _limited_walk(source, rel, limit):
    n = 0
    for item in source.walk_files(rel):
        yield item
        n += 1
        if n >= limit:
            return


def _user_of(rel: str) -> str:
    parts = rel.split("\\")
    return parts[1] if len(parts) > 2 and parts[0].lower() == "users" else ""


_APPIDS: Optional[Dict[str, str]] = None


def _appids() -> Dict[str, str]:
    """AppID -> application name, from Known_AppIDs.csv."""
    global _APPIDS
    if _APPIDS is None:
        _APPIDS = {}
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Known_AppIDs.csv")
        try:
            with open(path, encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 3:
                        _APPIDS[row[1].strip().lower()] = row[2]
        except OSError:
            pass
    return _APPIDS


def _jump_lists(source, profile, keys, fp, user):
    ids = {aid for aid, name in _appids().items() if _contains(name, keys)}
    if not ids:
        return
    for sub in ("AutomaticDestinations", "CustomDestinations"):
        base = profile + "\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\" + sub
        for name, is_dir in source.listdir(base):
            if not is_dir and name.split(".", 1)[0].lower() in ids:
                fp.add(FootprintItem("file", base + "\\" + name, "Jump List of the program (AppID)", user))


# Prefetch "directories" worth taking: data folders, not the OS.
_DATA_ROOTS = ("users\\", "programdata\\")


def _prefetch_folders(artifacts_dir, exe_names) -> List[str]:
    if not artifacts_dir or not exe_names:
        return []
    path = os.path.join(artifacts_dir, "prefetch_data.db")
    if not os.path.isfile(path):
        return []
    out = []
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    except sqlite3.Error:
        return []
    with conn:
        marks = ",".join("?" * len(exe_names))
        try:
            rows = conn.execute("SELECT resources FROM prefetch_data WHERE UPPER(executable_name) IN (%s)"
                                % marks, sorted(exe_names)).fetchall()
        except sqlite3.Error:
            rows = []
    folders: Dict[str, int] = {}
    for (resources,) in rows:
        try:
            files = json.loads(resources or "[]")
        except (ValueError, TypeError):
            continue
        for f in files:
            rel = norm_rel(f)
            if "\\" not in rel or not rel.lower().startswith(_DATA_ROOTS):
                continue
            parts = rel.split("\\")
            # Users\<u>\AppData\<area>\<Folder> or ProgramData\<Folder>
            depth = 5 if parts[0].lower() == "users" and len(parts) > 4 and parts[2].lower() == "appdata" else \
                    (2 if parts[0].lower() == "programdata" else 0)
            if not depth or len(parts) <= depth:
                continue
            folder = "\\".join(parts[:depth])
            if parts[depth - 1].lower() in _BROAD:
                continue
            folders[folder] = folders.get(folder, 0) + 1
    # The case-insensitive path Prefetch records is upper case; keep it, the
    # file systems are case-insensitive.
    return sorted(folders)


def measure(item: FootprintItem, source, cap_files: int = 200000):
    """Fill item.size / item.files (stops counting at cap_files)."""
    if item.kind == "registry":
        return
    total = files = 0
    for _rel, size in source.walk_files(item.path):
        total += size or 0
        files += 1
        if files >= cap_files:
            break
    item.size, item.files = total, files
