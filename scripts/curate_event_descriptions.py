"""Propose event descriptions for configs/event_descriptions.json - for review.

The catalogue is curated: this tool never writes it on its own. It reads the
wording Windows itself ships for an event and writes a PROPOSALS file; a person
reads it, marks the entries worth keeping ``"approved": true``, and
``--merge-approved`` folds only those in.

Where the wording comes from (this machine's Windows):

* manifest providers - ``Get-WinEvent -ListProvider`` (the highest version of
  each event ID wins);
* legacy event sources - the ``EventMessageFile`` named under
  ``HKLM\\SYSTEM\\CurrentControlSet\\Services\\EventLog\\<log>\\<source>``,
  loaded as a data file and read with FormatMessage, trying the severity bits
  a legacy message ID carries.

Which events to propose for:

* ``--case-db <Log_Claw.db>``  the (source, ID) pairs a real case holds that the
  catalogue has no text for, most frequent first;
* ``--provider <name>``        every event a provider defines (repeatable);
* ``--forensic``               the channels an examiner reads first (PowerShell,
  Task Scheduler, Terminal Services, Defender, WMI, BITS, Firewall, AppLocker).

    python scripts/curate_event_descriptions.py --case-db <case>/Target_Artifacts/Log_Claw.db \\
        --forensic --out <somewhere>/proposals.json
    (review: set "approved": true)
    python scripts/curate_event_descriptions.py --merge-approved <somewhere>/proposals.json

Templates are converted by ``convert_template`` (unit-tested): ``%1!s!`` ->
``%1``, ``%n``/``%t`` -> space, ``%r`` dropped, an unresolved ``%%NNNN`` ->
``?``, first paragraph only, at most ~220 characters.
"""
import argparse
import datetime as _dt
import json
import os
import re
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CATALOGUE = os.path.join(ROOT, "configs", "event_descriptions.json")
MAX_LEN = 220

FORENSIC_PROVIDERS = [
    "Microsoft-Windows-PowerShell",
    "PowerShell",
    "Microsoft-Windows-TaskScheduler",
    "Microsoft-Windows-TerminalServices-LocalSessionManager",
    "Microsoft-Windows-TerminalServices-RemoteConnectionManager",
    "Microsoft-Windows-RemoteDesktopServices-RdpCoreTS",
    "Microsoft-Windows-Windows Defender",
    "Microsoft-Windows-WMI-Activity",
    "Microsoft-Windows-Bits-Client",
    "Microsoft-Windows-Windows Firewall With Advanced Security",
    "Microsoft-Windows-AppLocker",
]

# The IDs an examiner reads first in each forensic channel; --forensic keeps
# only these, not every event the provider defines.
FORENSIC_IDS = {
    "Microsoft-Windows-PowerShell": [4100, 4103, 4104, 4105, 4106, 40961, 40962, 53504],
    "PowerShell": [400, 403, 600, 800],
    "Microsoft-Windows-TaskScheduler": [100, 101, 102, 103, 106, 107, 110, 119, 129, 140, 141,
                                        200, 201, 322],
    "Microsoft-Windows-TerminalServices-LocalSessionManager": [21, 22, 23, 24, 25, 39, 40, 41],
    "Microsoft-Windows-TerminalServices-RemoteConnectionManager": [261, 1149],
    "Microsoft-Windows-RemoteDesktopServices-RdpCoreTS": [98, 131],
    "Microsoft-Windows-Windows Defender": [1006, 1007, 1008, 1009, 1013, 1015, 1116, 1117,
                                           1118, 1119, 1120, 1121, 2000, 2001, 2002, 2003,
                                           3002, 5000, 5001, 5004, 5007, 5008, 5010, 5012,
                                           5013],
    "Microsoft-Windows-WMI-Activity": [5857, 5858, 5859, 5860, 5861],
    "Microsoft-Windows-Bits-Client": [3, 4, 59, 60, 61],
    "Microsoft-Windows-Windows Firewall With Advanced Security": [2004, 2005, 2006, 2009,
                                                                  2033, 2071, 2097],
    "Microsoft-Windows-AppLocker": [8002, 8003, 8004, 8005, 8006, 8007, 8020, 8021, 8022,
                                    8023, 8024, 8025],
}


# --------------------------------------------------------------------------
# Template conversion (pure)
# --------------------------------------------------------------------------

_FMT_SPEC = re.compile(r"%(\d{1,2})![^!]*!")
_PARAM_REF = re.compile(r"%%\d+")


def convert_template(text):
    """Windows message text -> a catalogue sentence, or None when nothing useful is left."""
    if not text:
        return None
    t = str(text).replace("\r\n", "\n").replace("\r", "\n")
    # First paragraph only: what follows is field listings ("Subject: ...").
    t = re.split(r"\n\s*\n", t.strip(), maxsplit=1)[0]
    t = _FMT_SPEC.sub(r"%\1", t)                 # %1!s! -> %1
    t = t.replace("%n", " ").replace("%t", " ").replace("%r", "")
    t = t.replace("%b", " ").replace("%.", ".").replace("%!", "!").replace("%%", "\x00")
    t = t.replace("\x00", "%%")
    t = _PARAM_REF.sub("?", t)                   # unresolved %%NNNN parameter references
    t = t.replace("\t", " ").replace("\n", " ")
    t = re.sub(r"\s{2,}", " ", t).strip()
    # A stray % that is not a %<digits> insert would be read as text.
    t = re.sub(r"%(?!\d)", "percent", t)
    if not t or t in ("?", "%1") or re.fullmatch(r"[%\d\s?.:,;-]*", t):
        return None
    if len(t) > MAX_LEN:
        cut = t[:MAX_LEN]
        stop = max(cut.rfind(". "), cut.rfind("; "))
        t = (cut[:stop + 1] if stop > 80 else cut.rstrip() + "...").strip()
    t = t[0].upper() + t[1:]
    # "Credential Guard configuration:" introduces a field list that the
    # first-paragraph cut removed; the colon would dangle.
    t = t.rstrip(" :;,-")
    if not t:
        return None
    if t[-1] not in ".!?)":
        t += "."
    return t


# --------------------------------------------------------------------------
# Reading Windows' own wording
# --------------------------------------------------------------------------

def manifest_events(provider, timeout=60):
    """{id: description} from the provider's manifest (highest version), or {}."""
    if os.name != "nt":
        return {}
    ps = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          "(Get-WinEvent -ListProvider '%s').Events | "
          "Select-Object Id, Version, Description | ConvertTo-Json -Compress -Depth 2"
          % provider.replace("'", "''"))
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (subprocess.SubprocessError, OSError):
        return {}
    out = (res.stdout or b"").decode("utf-8", "replace").strip()
    if res.returncode != 0 or not out:
        return {}
    try:
        data = json.loads(out)
    except ValueError:
        return {}
    if isinstance(data, dict):
        data = [data]
    best = {}
    for ev in data or []:
        try:
            eid, ver = int(ev.get("Id")), int(ev.get("Version") or 0)
        except (TypeError, ValueError):
            continue
        desc = ev.get("Description")
        if desc and (eid not in best or ver >= best[eid][0]):
            best[eid] = (ver, desc)
    return {eid: d for eid, (_v, d) in best.items()}


def _expand(path):
    return os.path.expandvars(path.replace("%SystemRoot%", os.environ.get("SystemRoot", r"C:\Windows")))


def legacy_message_files(source):
    """EventMessageFile paths registered for a legacy event source."""
    if os.name != "nt":
        return []
    import winreg
    base = r"SYSTEM\CurrentControlSet\Services\EventLog"
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as logs:
            i = 0
            while True:
                try:
                    log = winreg.EnumKey(logs, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(logs, "%s\\%s" % (log, source)) as k:
                        val, _t = winreg.QueryValueEx(k, "EventMessageFile")
                        found += [_expand(p.strip()) for p in str(val).split(";") if p.strip()]
                except OSError:
                    continue
    except OSError:
        pass
    return found


def legacy_message(files, event_id):
    """FormatMessage text for a legacy ID, trying the severity bits it may carry."""
    if os.name != "nt" or not files:
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.FormatMessageW.argtypes = [wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p]
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    LOAD_LIBRARY_AS_DATAFILE = 0x2
    FMT = 0x00000800 | 0x00000200          # FROM_HMODULE | IGNORE_INSERTS
    buf = ctypes.create_unicode_buffer(8192)
    for path in files:
        h = k32.LoadLibraryExW(path, None, LOAD_LIBRARY_AS_DATAFILE)
        if not h:
            continue
        try:
            for bits in (0, 0x40000000, 0x80000000, 0xC0000000):
                n = k32.FormatMessageW(FMT, h, (event_id & 0xFFFF) | bits, 0, buf, len(buf), None)
                if n:
                    return buf.value
        finally:
            k32.FreeLibrary(h)
    return None


# --------------------------------------------------------------------------
# What to propose for
# --------------------------------------------------------------------------

def case_gaps(db_path, limit=400):
    """[(source, id, rows)] the case holds with no catalogue text, most rows first."""
    from utils.event_descriptions import has_text
    counts = {}
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            cols = [r[1] for r in conn.execute('PRAGMA table_info("%s")' % table)]
            if "Source" not in cols or "EventID" not in cols:
                continue
            for src, eid, n in conn.execute(
                    'SELECT Source, EventID, COUNT(*) FROM "%s" GROUP BY 1, 2' % table):
                try:
                    eid = int(eid) & 0xFFFF
                except (TypeError, ValueError):
                    continue
                if src and not has_text(src, eid):
                    counts[(src, eid)] = counts.get((src, eid), 0) + n
    finally:
        conn.close()
    return sorted(((s, e, n) for (s, e), n in counts.items()), key=lambda x: -x[2])[:limit]


def propose(pairs, log=print):
    """{provider: {id: {...}}} for [(provider, id, rows)] - each reading cached per provider."""
    from utils.event_descriptions import has_text
    by_provider = {}
    for src, eid, rows in pairs:
        by_provider.setdefault(src, []).append((eid, rows))
    out = {}
    for src, wanted in sorted(by_provider.items()):
        manifest = manifest_events(src)
        if not manifest and not src.lower().startswith("microsoft-windows-"):
            manifest = manifest_events("Microsoft-Windows-" + src)
        files = None
        for eid, rows in sorted(wanted, key=lambda x: -x[1]):
            if has_text(src, eid):
                continue
            raw, origin = manifest.get(eid), "manifest"
            if raw is None:
                if files is None:
                    files = legacy_message_files(src)
                raw, origin = legacy_message(files, eid), "message file"
            text = convert_template(raw)
            entry = {"rows": rows, "approved": False}
            if text:
                entry.update(text=text, source=origin, original=(raw or "")[:600])
            else:
                entry.update(text=None, source="none",
                             note="Windows on this machine has no text for it (vendor driver not "
                                  "installed, or an event without a message)")
            out.setdefault(src, {})[str(eid)] = entry
        got = sum(1 for e in out.get(src, {}).values() if e["text"])
        log("%-60s %3d proposed, %3d without text" % (src[:60], got, len(out.get(src, {})) - got))
    return out


def forensic_pairs():
    return [(p, eid, 0) for p in FORENSIC_PROVIDERS for eid in FORENSIC_IDS.get(p, [])]


def provider_pairs(provider):
    return [(provider, eid, 0) for eid in sorted(manifest_events(provider))]


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------

def _windows_build():
    try:
        v = sys.getwindowsversion()
        return "%d.%d.%d" % (v.major, v.minor, v.build)
    except AttributeError:
        return "not windows"


def merge_approved(proposals_path, catalogue_path=CATALOGUE, replace=False):
    """Fold the approved proposals in. Existing entries are kept unless ``replace``."""
    with open(proposals_path, encoding="utf-8") as fh:
        props = json.load(fh)
    with open(catalogue_path, encoding="utf-8") as fh:
        cat = json.load(fh)
    from utils.event_descriptions import normalise_provider
    by_norm = {normalise_provider(p): p for p in cat["providers"]}
    aliases = {normalise_provider(a): normalise_provider(t) for a, t in cat.get("aliases", {}).items()}
    added = 0
    for provider, events in (props.get("proposals") or {}).items():
        take = {eid: p["text"] for eid, p in events.items() if p.get("approved") and p.get("text")}
        if not take:
            continue                         # never an empty provider entry
        norm = normalise_provider(provider)
        norm = aliases.get(norm, norm)
        name = by_norm.get(norm, provider)
        entry = cat["providers"].setdefault(name, {})   # new providers go at the end
        by_norm[norm] = name
        evs = entry.setdefault("events", {})
        for eid, text in take.items():
            if eid in evs and not replace:
                continue
            evs[eid] = text
            added += 1
        entry["events"] = dict(sorted(evs.items(), key=lambda kv: int(kv[0])))
    cat.setdefault("_curation", []).append({
        "merged_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": added, "windows_build": (props.get("_about") or {}).get("windows_build")})
    with open(catalogue_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cat, fh, indent=1, ensure_ascii=False)     # the file's own layout
        fh.write("\n")
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--case-db", action="append", default=[])
    ap.add_argument("--provider", action="append", default=[])
    ap.add_argument("--forensic", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--merge-approved")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)

    if a.merge_approved:
        n = merge_approved(a.merge_approved, replace=a.replace)
        print("Merged %d approved entr%s into %s" % (n, "y" if n == 1 else "ies", CATALOGUE))
        return 0
    if not a.out:
        ap.error("--out is required (somewhere you keep - not %TEMP%)")
    pairs = []
    for db in a.case_db:
        pairs += case_gaps(db)
    if a.forensic:
        pairs += forensic_pairs()
    for p in a.provider:
        pairs += provider_pairs(p)
    proposals = propose(pairs)
    doc = {"_about": {"windows_build": _windows_build(),
                      "made_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "how": "Set \"approved\": true on each entry to keep, then run with "
                             "--merge-approved. Entries with text null have nothing to merge."},
           "proposals": proposals}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    total = sum(len(v) for v in proposals.values())
    with_text = sum(1 for v in proposals.values() for e in v.values() if e["text"])
    print("%d proposal(s), %d with text -> %s" % (total, with_text, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
