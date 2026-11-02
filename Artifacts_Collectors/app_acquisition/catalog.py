"""The applications an examiner can pick.

One list, merged from what the source itself says and what the case has
already parsed:

- installed programs: the Uninstall keys (64-bit, 32-bit and each user's) and
  App Paths, read from the source (live registry or the image's hives);
- programs that ran, installed or not: Amcache, BAM and Prefetch from the
  case's parsed databases, when the case has them. A portable tool run from
  Downloads is in none of the Uninstall keys, and is often the one that matters.

Entries are merged by install folder, then by executable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .registry import SOFTWARE, RegistryView

logger = logging.getLogger(__name__)

_UNINSTALL = ("Microsoft\\Windows\\CurrentVersion\\Uninstall",
              "WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
_APP_PATHS = "Microsoft\\Windows\\CurrentVersion\\App Paths"
_USER_UNINSTALL = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"

# Folders too broad to be "the program's folder" for an executable found in them.
_GENERIC_PARENTS = {
    "", "windows", "system32", "syswow64", "downloads", "desktop", "documents",
    "temp", "tmp", "users", "program files", "program files (x86)", "programdata",
    "appdata", "local", "roaming", "locallow", "public", "onedrive",
}


def norm_rel(path: Optional[str]) -> str:
    """Any Windows path form -> volume-relative, lower-case-insensitive key form.

    ``C:\\Program Files\\X``, ``\\??\\C:\\X``, ``\\Device\\HarddiskVolume3\\X``
    and ``"C:\\X\\a.exe",0`` all become ``Program Files\\X`` / ``X\\a.exe``.
    """
    if not path:
        return ""
    p = str(path).strip().strip('"').split('",')[0].strip('"')
    p = p.split(";")[0].strip()                         # App Paths "Path": a list, first is the program's
    p = re.sub(r",-?\d+$", "", p)                       # DisplayIcon "app.exe,0"
    p = p.replace("/", "\\")
    p = re.sub(r"^\\\\\?\\|^\\\?\?\\", "", p)
    p = re.sub(r"^\\Device\\HarddiskVolume\d+\\", "", p, flags=re.I)
    p = re.sub(r"^\\VOLUME\{[^}]*\}\\", "", p, flags=re.I)
    p = re.sub(r"^[A-Za-z]:\\", "", p)
    p = os.path.expandvars(p) if "%" in p else p
    p = re.sub(r"^[A-Za-z]:\\", "", p)
    return p.strip("\\")


def _folder_of_exe(exe_rel: str) -> str:
    """The exe's folder, unless that folder is too broad to be the program's."""
    folder = exe_rel.rsplit("\\", 1)[0] if "\\" in exe_rel else ""
    leaf = folder.rsplit("\\", 1)[-1].lower()
    if leaf in _GENERIC_PARENTS or (folder.lower().startswith("users\\") and folder.count("\\") <= 1):
        return ""
    return folder


@dataclass
class AppEntry:
    name: str
    publisher: str = ""
    version: str = ""
    install_dir: str = ""                       # volume-relative
    exes: List[str] = field(default_factory=list)   # volume-relative exe paths
    registry_keys: List[Dict[str, str]] = field(default_factory=list)   # {hive, path}
    package_full_name: str = ""
    sources: List[str] = field(default_factory=list)  # where this entry was seen
    users: List[str] = field(default_factory=list)
    last_run: str = ""

    def key(self) -> str:
        if self.install_dir:
            return "dir:" + self.install_dir.lower()
        if self.exes:
            return "exe:" + self.exes[0].lower()
        return "name:" + self.name.lower()

    def merge(self, other: "AppEntry"):
        for attr in ("publisher", "version", "install_dir", "package_full_name"):
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))
        if len(other.name) > len(self.name) and not other.name.lower().endswith(".exe"):
            self.name = other.name
        for attr in ("exes", "registry_keys", "sources", "users"):
            mine = getattr(self, attr)
            # Amcache stores paths lower case and Prefetch upper case: one exe.
            have = {str(m).lower() for m in mine}
            for item in getattr(other, attr):
                if str(item).lower() not in have:
                    mine.append(item)
                    have.add(str(item).lower())
        if other.last_run > self.last_run:
            self.last_run = other.last_run

    def label(self) -> str:
        bits = [self.name]
        if self.version:
            bits.append(self.version)
        if self.publisher:
            bits.append("- " + self.publisher)
        return " ".join(bits)


# -- from the source's registry ------------------------------------------
def _uninstall_entries(view: RegistryView) -> List[AppEntry]:
    out = []
    hives = [(SOFTWARE, p) for p in _UNINSTALL] + [(h, _USER_UNINSTALL) for h in view.user_hives()]
    for hive, base in hives:
        for sub in view.subkeys(hive, base):
            path = base + "\\" + sub
            vals = view.values(hive, path)
            name = str(vals.get("DisplayName") or "").strip()
            if not name or vals.get("SystemComponent") == 1 or vals.get("ParentKeyName"):
                continue
            entry = AppEntry(
                name=name, publisher=str(vals.get("Publisher") or "").strip(),
                version=str(vals.get("DisplayVersion") or "").strip(),
                install_dir=norm_rel(vals.get("InstallLocation")),
                registry_keys=[{"hive": hive, "path": path, "why": "its Uninstall entry"}],
                sources=["Uninstall key" + (" (%s)" % hive.split(":", 1)[1] if hive != SOFTWARE else "")])
            icon = norm_rel(vals.get("DisplayIcon"))
            if icon.lower().endswith(".exe"):
                entry.exes.append(icon)
                if not entry.install_dir:
                    entry.install_dir = _folder_of_exe(icon)
            if hive != SOFTWARE:
                entry.users.append(hive.split(":", 1)[1])
            out.append(entry)
    return out


def _app_paths_entries(view: RegistryView) -> List[AppEntry]:
    out = []
    for sub in view.subkeys(SOFTWARE, _APP_PATHS):
        vals = view.values(SOFTWARE, _APP_PATHS + "\\" + sub)
        exe = norm_rel(vals.get(""))
        if not exe.lower().endswith(".exe"):
            continue
        folder = norm_rel(vals.get("Path")) or _folder_of_exe(exe)
        out.append(AppEntry(name=os.path.splitext(sub)[0], install_dir=folder, exes=[exe],
                            registry_keys=[{"hive": SOFTWARE, "path": _APP_PATHS + "\\" + sub,
                                            "why": "its App Paths entry"}],
                            sources=["App Paths"]))
    return out


# -- from the case's parsed databases ------------------------------------
def _open_ro(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.isfile(path):
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f"), uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _rows(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _parsed_entries(artifacts_dir: Optional[str]) -> List[AppEntry]:
    """Amcache, BAM and Prefetch rows from the case's databases."""
    if not artifacts_dir:
        return []
    out = []
    conn = _open_ro(os.path.join(artifacts_dir, "amcache.db"))
    if conn is not None:
        with conn:
            for name, pub, ver, root, pkg in _rows(conn, "SELECT name, publisher, version, root_dir_path, "
                                                         "package_full_name FROM InventoryApplication"):
                if not name:
                    continue
                out.append(AppEntry(name=str(name), publisher=str(pub or ""), version=str(ver or ""),
                                    install_dir=norm_rel(root), package_full_name=str(pkg or ""),
                                    sources=["Amcache"]))
            for (path,) in _rows(conn, "SELECT DISTINCT lower_case_long_path FROM InventoryApplicationFile "
                                       "WHERE lower_case_long_path LIKE '%.exe'"):
                exe = norm_rel(path)
                if exe:
                    out.append(AppEntry(name=os.path.basename(exe), exes=[exe],
                                        install_dir=_folder_of_exe(exe), sources=["Amcache (file)"]))
    conn = _open_ro(os.path.join(artifacts_dir, "registry_data.db"))
    if conn is not None:
        with conn:
            for path, sid, last in _rows(conn, "SELECT process_path, sid, last_execution FROM BAM"):
                exe = norm_rel(path)
                if exe.lower().endswith(".exe"):
                    out.append(AppEntry(name=os.path.basename(exe), exes=[exe],
                                        install_dir=_folder_of_exe(exe), sources=["BAM"],
                                        last_run=str(last or "")))
    conn = _open_ro(os.path.join(artifacts_dir, "prefetch_data.db"))
    if conn is not None:
        with conn:
            for exe_name, resources, last in _rows(conn, "SELECT executable_name, resources, last_executed "
                                                         "FROM prefetch_data"):
                if not exe_name:
                    continue
                exe = ""
                try:
                    for res in json.loads(resources or "[]"):
                        if str(res).lower().endswith("\\" + str(exe_name).lower()):
                            exe = norm_rel(res)
                            break
                except (ValueError, TypeError):
                    pass
                out.append(AppEntry(name=str(exe_name), exes=[exe] if exe else [],
                                    install_dir=_folder_of_exe(exe) if exe else "",
                                    sources=["Prefetch"], last_run=str(last or "")))
    return out


# -- the merged list -----------------------------------------------------
def list_applications(source, artifacts_dir: Optional[str] = None,
                      view: Optional[RegistryView] = None) -> List[AppEntry]:
    """Every application the source and the case know of, merged."""
    view = view or RegistryView(source)
    raw: List[AppEntry] = []
    for builder in (_uninstall_entries, _app_paths_entries):
        try:
            raw.extend(builder(view))
        except Exception as exc:
            logger.warning("%s failed: %s", builder.__name__, exc)
    if source.kind == "live" or artifacts_dir:
        # A case parsed from another machine says nothing about this source;
        # the dialog only passes artifacts_dir when they belong together.
        raw.extend(_parsed_entries(artifacts_dir))

    merged: Dict[str, AppEntry] = {}
    by_exe: Dict[str, str] = {}
    for entry in raw:
        target = None
        if entry.install_dir and ("dir:" + entry.install_dir.lower()) in merged:
            target = "dir:" + entry.install_dir.lower()
        for exe in entry.exes:
            target = target or by_exe.get(exe.lower())
        if target is None and entry.exes and not entry.install_dir:
            # An exe inside an installed program's folder belongs to that program.
            low = entry.exes[0].lower()
            for k, e in merged.items():
                if e.install_dir and low.startswith(e.install_dir.lower() + "\\"):
                    target = k
                    break
        if target is None:
            target = entry.key()
            if target in merged:
                merged[target].merge(entry)
            else:
                merged[target] = entry
        else:
            merged[target].merge(entry)
        for exe in merged[target].exes:
            by_exe.setdefault(exe.lower(), target)
    apps = [a for a in merged.values() if a.install_dir or a.exes or a.registry_keys]
    return sorted(apps, key=lambda a: a.name.lower())
