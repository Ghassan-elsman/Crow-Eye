"""
Shadow copies: what exists, what each one takes and where, what made it, and what removed the rest.

An investigator asks four things of a volume's shadow copies, and each has its own source:

- What exists. Live: Win32_ShadowCopy (the copies Windows exposes, each with its device) joined to
  the VSS catalog on the volume (volume_layout.shadow_copies), which also holds stores Windows no
  longer exposes. In a forensic image: the catalog alone. Both are read by Crow-Eye's own VSS
  reader (vss_reader), which also rebuilds any copy - exposed, hidden or in an image.
- What each takes and where: the copy's own store file, from its MFT record (volume_layout).
- What made it. VSS writes event 8231 "Snapshot creation initiated for Snapshot Set {id}" to the
  Application log with the requesting process's command line and caller stack, and every copy
  carries its snapshot set id - so the trigger is the requester's own command line, not a guess
  from timing. A System Restore point created within a few minutes (root/default SystemRestore)
  adds its description ("Windows Update", "Installed ...").
- What removed the others. volsnap logs each removal it makes in the System log: 33 "the oldest
  shadow copy ... was deleted to keep disk space usage ... below the user defined limit", 95
  deleted "to allow shadow copies created afterward and marked for delete to be deleted", and the
  others listed in REMOVAL_EVENTS. A copy that disappears with no such event was removed by
  something else - vssadmin, wmic, diskshadow - which is the case MITRE T1490 describes.

Times are UTC throughout. Output printed by this module is ASCII.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import re
import struct
import subprocess
import uuid
from typing import Dict, List, Optional
from Artifacts_Collectors import vss_reader

try:
    from Artifacts_Collectors import volume_layout as _vl
except ImportError:          # run from inside Artifacts_Collectors
    import volume_layout as _vl

# volsnap (System log) events that record a shadow copy being removed, and why in plain words.
REMOVAL_EVENTS = {
    33: "removed for space: the oldest copy, to stay under the storage limit",
    95: "removed: the oldest copy, so copies marked for deletion after it could go",
    25: "removed: shadow storage could not grow",
    35: "removed: shadow storage could not grow (limit reached)",
    36: "removed: shadow storage could not grow (volume full)",
    14: "aborted: an I/O failure on the shadow storage",
}

# SystemRestore.RestorePointType, as documented; 17 and 18 are what Windows Update writes.
RESTORE_POINT_TYPES = {0: "application installed", 1: "application removed", 7: "checkpoint",
                       10: "driver installed", 12: "settings changed", 13: "cancelled operation",
                       14: "backup recovery", 16: "manual", 17: "Windows Update", 18: "Windows Update"}


def _ps_json(cmd: str):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=90)
        data = json.loads(r.stdout) if r.stdout.strip() else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _parse_utc(text) -> Optional[datetime.datetime]:
    if not text:
        return None
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def size_text(n) -> str:
    """Bytes in the largest whole unit: 512 B, 3.2 KB, 17.66 GB."""
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.2f %s" % (n, unit))
        n /= 1024.0
    return ""


# ---------------------------------------------------------------------------------------------
# triggers and removals (live: this machine's own logs)
# ---------------------------------------------------------------------------------------------
def _cmd_8231(days):
    return ("Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='VSS'; Id=8231; "
            "StartTime=(Get-Date).AddDays(-%d)} -ErrorAction SilentlyContinue | ForEach-Object { "
            "[pscustomobject]@{ At=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
            "Msg=$_.Message } }" % days)


def _cmd_restore():
    return ("Get-CimInstance -Namespace root/default -ClassName SystemRestore -ErrorAction SilentlyContinue | "
            "ForEach-Object { [pscustomobject]@{ Seq=$_.SequenceNumber; Desc=$_.Description; "
            "Type=$_.RestorePointType; Created=([Management.ManagementDateTimeConverter]::ToDateTime("
            "$_.CreationTime)).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } }")


def _cmd_removals(days, limit):
    return ("Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='volsnap'; Id=%s; "
            "StartTime=(Get-Date).AddDays(-%d)} -MaxEvents %d -ErrorAction SilentlyContinue | ForEach-Object { "
            "[pscustomobject]@{ At=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); Id=$_.Id; "
            "Msg=($_.Message -split \"`n\")[0] } }" % (",".join(str(i) for i in REMOVAL_EVENTS), days, limit))


def _cmd_8194(days):
    return ("Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='System Restore'; "
            "Id=8194,8216,8193; StartTime=(Get-Date).AddDays(-%d)} -ErrorAction SilentlyContinue | ForEach-Object { "
            "[pscustomobject]@{ Id=$_.Id; At=$_.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); "
            "Process=[string]$_.Properties[0].Value; Desc=[string]$_.Properties[1].Value } }" % days)


def _cmd_8300(days):
    return ("Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Microsoft-Windows-System-Restore'; "
            "Id=8300,8301,8302,8303; StartTime=(Get-Date).AddDays(-%d)} -ErrorAction SilentlyContinue | "
            "ForEach-Object { [pscustomobject]@{ Id=$_.Id; At=$_.TimeCreated.ToUniversalTime().ToString("
            "'yyyy-MM-ddTHH:mm:ssZ'); Msg=$_.Message } }" % days)


def _cmd_4688(pids, days):
    return ("Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4688; StartTime=(Get-Date).AddDays(-%d)} "
            "-ErrorAction SilentlyContinue | Where-Object { @(%s) -contains [int64]$_.Properties[4].Value } | "
            "ForEach-Object { [pscustomobject]@{ Pid=[int64]$_.Properties[4].Value; Name=[string]$_.Properties[5].Value "
            "} }" % (days, ",".join(str(p) for p in pids)))


def requester_events(days: int = 400, rows=None) -> Dict[str, dict]:
    """VSS 8231 by snapshot set id: {set_id: {at, command_line, callers}}. `rows`: the 8231 pipeline's
    rows already fetched (live_copies' snapshot)."""
    out = {}
    if rows is None:
        rows = _ps_json(_cmd_8231(days) + " | ConvertTo-Json -Compress")
    for r in rows:
        msg = r.get("Msg") or ""
        m = re.search(r"Snapshot Set (\{[0-9a-fA-F-]{36}\})", msg)
        if not m:
            continue
        cmd = re.search(r"Process command line:\s*(.*)", msg)
        callers = re.findall(r"Process\[\d+\]:\s*(\S.*)", msg)
        out[m.group(1).upper()] = {"at": r.get("At") or "", "command_line": (cmd.group(1).strip() if cmd else ""),
                                   "callers": [c.strip() for c in callers]}
    return out


def restore_points(rows=None) -> List[dict]:
    """System Restore points: sequence, description, type, created (UTC)."""
    out = []
    for r in (rows if rows is not None else _ps_json(_cmd_restore() + " | ConvertTo-Json -Compress")):
        out.append({"sequence": r.get("Seq"), "description": r.get("Desc") or "",
                    "type": RESTORE_POINT_TYPES.get(r.get("Type"), "type %s" % r.get("Type")),
                    "created": r.get("Created") or ""})
    return out


def removals(letter: str = None, days: int = 400, limit: int = 500, rows=None) -> List[dict]:
    """volsnap removal events, newest first: {at, event_id, reason, volume, message}."""
    out = []
    for r in (rows if rows is not None else _ps_json(_cmd_removals(days, limit) + " | ConvertTo-Json -Compress")):
        msg = (r.get("Msg") or "").strip()
        m = re.search(r"volume ([A-Z]):", msg)
        vol = m.group(1) if m else ""
        if letter and vol and vol != letter.rstrip(":\\").upper():
            continue
        out.append({"at": r.get("At") or "", "event_id": r.get("Id"),
                    "reason": REMOVAL_EVENTS.get(r.get("Id"), "removed"), "volume": vol, "message": msg})
    return out


def explain_no_copies(letter: str, removed: List[dict] = None, storage: dict = None,
                      volume_size=None, volume_used=None, now: datetime.datetime = None) -> str:
    """Why a volume has no shadow copies, in the words of what Windows recorded.

    `removed` is removals(letter) (newest first), `storage` is shadow_storage()[letter]. Says
    only what the logs and the storage settings show: the removals Windows logged and why, or
    that it logged none, and how full the shadow storage and the volume are."""
    letter = (letter or "C").rstrip(":\\").upper()
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    removed = [r for r in (removed or []) if not r.get("volume") or r.get("volume") == letter]
    parts = []
    if removed:
        last = removed[0]
        at = (last.get("at") or "").replace("T", " ").rstrip("Z")
        recent = 0
        for r in removed:
            try:
                t = datetime.datetime.strptime((r.get("at") or "")[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
            if now - t <= datetime.timedelta(hours=24):
                recent += 1
        cap = (storage or {}).get("max")
        if last.get("event_id") in (33, 35, 36, 25):
            why = ("Windows removed the oldest copies to keep shadow storage under its limit%s"
                   % (" (%s)" % size_text(cap) if cap else ""))
        else:
            why = "Windows removed them: %s" % last.get("reason", "removed")
        when = ("%d removal%s in the last 24 hours, the last at %s UTC" % (recent, "" if recent == 1 else "s", at)
                if recent else "%d removal%s logged, the last at %s UTC" % (len(removed), "" if len(removed) == 1 else "s", at))
        parts.append("No shadow copies on %s: right now. %s: %s (volsnap event %s)."
                     % (letter, why, when, last.get("event_id")))
    else:
        parts.append("No shadow copies on %s:, and Windows has logged no removals: none have been made "
                     "on this volume, or System Protection is off for it." % letter)
    if storage:
        parts.append("Shadow storage: %s used, %s allocated, %s maximum."
                     % (size_text(storage.get("used") or 0), size_text(storage.get("allocated") or 0),
                        size_text(storage["max"]) if storage.get("max") else "no limit set"))
    if volume_size:
        free = max(0, volume_size - (volume_used or 0))
        parts.append("%s: has %s free (%d%% used)." % (letter, size_text(free),
                                                      round(100.0 * (volume_used or 0) / volume_size)))
    return "  ".join(parts)


def describe_trigger(req: Optional[dict], rp: Optional[dict]) -> str:
    """One line for the table: what asked for the copy."""
    if rp:
        head = "System Restore: %s (%s)" % (rp["description"] or "restore point", rp["type"])
    else:
        head = ""
    if req and req.get("command_line"):
        cl = req["command_line"]
        low = cl.lower()
        if "wuauserv" in low:
            who = "Windows Update (wuauserv)"
        elif "taskhostw" in low:
            who = "a scheduled task (%s)" % cl.strip()
        elif "srtasks" in low or "rstrui" in low or "systemrestore" in low:
            who = "System Restore (%s)" % cl.strip()
        elif "vssadmin" in low or "wmic" in low or "diskshadow" in low:
            who = "an administrator command (%s)" % cl.strip()
        else:
            who = cl.strip()
        return (head + "; requested by " + who) if head else "Requested by " + who
    return head or "Not recorded in this machine's logs"

# ---------------------------------------------------------------------------------------------
# provenance: every record that says why a copy exists and what asked for it (live)
# ---------------------------------------------------------------------------------------------
# Where each one comes from, measured on Windows 11 against live copies joined by their set id:
#
#   SPP metadata   System Volume Information\SPP\OnlineMetadataCache\{set id}_OnDiskSnapshotProp,
#                  System Restore's own record of the restore point: its description, its type and
#                  when it was made. It outlives the copy. Layout reverse-engineered: @40 the set
#                  GUID, @64 FILETIME, @72 the restore point type, then NDR strings (u32 max count,
#                  u32 offset, u32 actual count, UTF-16), the description first.
#   VSS\Diag       HKLM\SYSTEM\CurrentControlSet\Services\VSS\Diag: per component (the requester's
#                  VssapiPublisher, SystemRestore, SPP, each writer) the LAST occurrence of each
#                  operation - 72 bytes: @8 FILETIME, @16 PID, @24 operation, @28 enter/leave,
#                  @40 the set GUID. Only the newest of each operation survives.
#   8194 / 8216    Application log, provider "System Restore": a restore point created (8194) or
#                  skipped as too soon after the last one (8216), with the requester's full command
#                  line and the description. Filtered by provider: VSS uses the same IDs.
#   8300 - 8302    Microsoft-Windows-System-Restore "scoping ... for shadowcopy <device>": names the
#                  copy's own device, so no time window is needed.
#   8231           VSS "Snapshot creation initiated for Snapshot Set {id}": the requesting process's
#                  command line and caller stack. It names the HOST process (taskhostw.exe, DllHost)
#                  rather than the task or component behind it, and is logged for short-lived copies
#                  too.
#   store flags    How the copy was made: with writers and auto-recovered (System Restore), or with
#                  no writers (WMI Win32_ShadowCopy.Create, wmic, vssadmin - and some Windows
#                  components, so not proof of a person).
#
# A copy no record names is common: two of four live copies on the measuring machine had none. Its
# absence says only that nothing logged it.
SPP_METADATA = r"System Volume Information\SPP\OnlineMetadataCache"
DIAG_KEY = r"SYSTEM\CurrentControlSet\Services\VSS\Diag"
DIAG_OPS = {1000: "identify", 1001: "prepare backup", 1002: "prepare snapshot", 1003: "freeze", 1004: "thaw",
            1014: "backup complete", 1017: "get state", 1034: "do snapshot"}


def _read_backup(path: str) -> Optional[bytes]:
    """A file System Volume Information's ACL keeps from administrators, read with backup semantics
    (SeBackupPrivilege, which volume_layout enables)."""
    if os.name != "nt":
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    h = k32.CreateFileW(path, 0x80000000, 7, None, 3, 0x02000000, None)
    if not h or h == wt.HANDLE(-1).value:
        return None
    try:
        out = bytearray()
        buf = ctypes.create_string_buffer(65536)
        n = wt.DWORD()
        while k32.ReadFile(h, buf, 65536, ctypes.byref(n), None) and n.value:
            out += buf.raw[:n.value]
        return bytes(out)
    finally:
        k32.CloseHandle(h)


def _ndr_strings(data: bytes, start: int, limit: int = 8) -> List[str]:
    """NDR conformant varying strings from `start`: u32 max, u32 offset (0), u32 actual, UTF-16."""
    out, pos = [], start
    while pos + 12 <= len(data) and len(out) < limit:
        mx, off, act = struct.unpack_from("<III", data, pos)
        if off == 0 and 0 < act <= mx <= 4096 and pos + 12 + 2 * act <= len(data):
            raw = data[pos + 12:pos + 12 + 2 * act]
            text = raw.decode("utf-16-le", "replace").rstrip("\0")
            if text and all(ch.isprintable() for ch in text):
                out.append(text)
                pos += 12 + 2 * act
                pos += (-pos) % 4
                continue
        pos += 4
    return out


def spp_restore_points(letter: str = "C") -> Dict[str, dict]:
    """System Restore's own record of each restore point, by snapshot set id - including the copies
    that are gone: {set_id: {created, type, description, strings}}."""
    folder = "%s:\\%s" % (letter.rstrip(":\\").upper(), SPP_METADATA)
    out = {}
    try:
        _vl._enable_backup_privilege()
        names = [n for n, _s, _r in _vl._dir_entries(folder)]
    except Exception:
        return out
    for name in names:
        if not name.endswith("_OnDiskSnapshotProp"):
            continue
        data = _read_backup(os.path.join(folder, name))
        if not data or len(data) < 80:
            continue
        set_id = "{%s}" % str(uuid.UUID(bytes_le=data[40:56])).upper()
        ft, = struct.unpack_from("<Q", data, 64)
        kind, = struct.unpack_from("<I", data, 72)
        strings = _ndr_strings(data, 76)
        out[set_id] = {"created": _vl._filetime_iso(ft) or "", "type_code": kind,
                       "type": RESTORE_POINT_TYPES.get(kind, "type %d" % kind),
                       "description": strings[0] if strings else "", "strings": strings[:6]}
    return out


def vss_diag() -> Dict[str, dict]:
    """HKLM\\...\\VSS\\Diag by snapshot set id: {set_id: {component: [{op, at, pid, enter}]}}."""
    out: Dict[str, dict] = {}
    if os.name != "nt":
        return out
    import winreg
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DIAG_KEY)
    except OSError:
        return out
    i = 0
    while True:
        try:
            comp = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            key = winreg.OpenKey(root, comp)
        except OSError:
            continue
        j = 0
        while True:
            try:
                _name, value, _t = winreg.EnumValue(key, j)
            except OSError:
                break
            j += 1
            if not isinstance(value, bytes) or len(value) < 56:
                continue
            ft, pid, _tid, op, enter = struct.unpack_from("<QIIII", value, 8)
            guid = uuid.UUID(bytes_le=value[40:56])
            if guid.int == 0:
                continue
            set_id = "{%s}" % str(guid).upper()
            out.setdefault(set_id, {}).setdefault(comp, []).append(
                {"op": DIAG_OPS.get(op, "operation %d" % op), "at": _vl._filetime_iso(ft) or "", "pid": pid,
                 "enter": bool(enter)})
    return out


def restore_point_events(days: int = 400, rows=None) -> List[dict]:
    """System Restore's 8194 (created) and 8216 (skipped) with the requester's command line."""
    out = []
    for r in (rows if rows is not None else _ps_json(_cmd_8194(days) + " | ConvertTo-Json -Compress")):
        out.append({"id": r.get("Id"), "at": r.get("At") or "", "process": r.get("Process") or "",
                    "description": r.get("Desc") or ""})
    return out


def scoping_events(days: int = 400, rows=None) -> Dict[str, List[dict]]:
    """Microsoft-Windows-System-Restore 8300-8303 by the copy's device name."""
    out: Dict[str, List[dict]] = {}
    for r in (rows if rows is not None else _ps_json(_cmd_8300(days) + " | ConvertTo-Json -Compress")):
        m = re.search(r"(\\\\\?\\GLOBALROOT\\Device\\HarddiskVolumeShadowCopy\d+)", r.get("Msg") or "")
        if m:
            out.setdefault(m.group(1).upper(), []).append({"id": r.get("Id"), "at": r.get("At") or ""})
    return out


def process_names(pids: List[int], days: int = 30, rows=None) -> Dict[int, str]:
    """PID -> image, from Security 4688 (process creation auditing) when it is on, else from the
    processes still running. Best effort: PIDs are reused, so a name is only a lead."""
    want = sorted(set(p for p in pids if p))
    if not want:
        return {}
    out = {}
    for r in (rows if rows is not None else _ps_json(_cmd_4688(want, days) + " | ConvertTo-Json -Compress")):
        if r.get("Pid") and r.get("Name"):
            out[int(r["Pid"])] = r["Name"]
    try:
        import psutil
        for pid in want:
            if pid not in out and psutil.pid_exists(pid):
                out[pid] = psutil.Process(pid).exe() + " (running now; the PID may have been reused)"
    except Exception:
        pass
    return out


def crow_eye_created() -> Dict[str, dict]:
    """The shadow copies Crow-Eye itself made, from every known case's custody records
    (logs/: the ledger and the run parts): {shadow_id: {case, created_utc, command}}. A copy
    Crow-Eye made to read locked files is deleted when the run ends; one still here outlived a
    run that was killed."""
    import glob
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = {}
    pattern = re.compile(r'\{[^{}]*"shadow_copy_id"\s*:\s*"(\{[0-9A-Fa-f-]{36}\})"[^{}]*\}')
    for cfg in glob.glob(os.path.join(here, "config", "case_*.json")):
        try:
            with open(cfg, encoding="utf-8") as f:
                root = (json.load(f).get("paths") or {}).get("case_root") or ""
        except (OSError, ValueError):
            continue
        logs = os.path.join(root, "logs")
        if not root or not os.path.isdir(logs):
            continue
        for dirpath, _dirs, files in os.walk(logs):
            for name in files:
                if not name.endswith((".jsonl", ".json")):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(path) > 64 * 1024 * 1024:
                        continue
                    with open(path, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                if "shadow_copy_id" not in text:
                    continue
                for m in pattern.finditer(text):
                    try:
                        item = json.loads(m.group(0))
                    except ValueError:
                        continue
                    if item.get("action") == "created":
                        out.setdefault(m.group(1).upper(), {
                            "case": os.path.basename(root.replace("/", "\\").rstrip("\\")),
                            "created_utc": item.get("created_utc") or "", "command": item.get("command") or ""})
    return out


def _who(command_line: str) -> str:
    low = (command_line or "").lower()
    if "wuauserv" in low:
        return "Windows Update"
    if "srtasks" in low and "scheduled" in low:
        return "System Restore's scheduled checkpoint"
    if "srtasks" in low or "rstrui" in low or "systempropertiesprotection" in low:
        return "System Restore"
    if "taskhostw" in low:
        return "a scheduled task (hosted by taskhostw.exe)"
    if "dllhost" in low:
        return "a COM component (hosted by DllHost.exe)"
    if any(k in low for k in ("vssadmin", "wmic", "diskshadow", "powershell", "checkpoint-computer")):
        return "a command typed or scripted on the machine"
    if "msiexec" in low or "setup" in low or "install" in low:
        return "an installer"
    return os.path.basename((command_line or "").split(" -", 1)[0].strip('"')) or "an unnamed process"


def _provenance(copy: dict, spp: dict, diag: dict, rp_events: List[dict], scoping: dict, req: Optional[dict],
               rp: Optional[dict], names: Dict[int, str], crow: Optional[Dict[str, dict]] = None) -> dict:
    """{summary, who, why, evidence: [{source, text}]} for one copy, from every record found.
    `rp_events` are the restore-point events this copy owns (the nearest copy to each)."""
    set_id = (copy.get("set_id") or "").upper()
    created = _parse_utc(copy.get("created"))
    ev, who, why = [], "", ""
    mine = (crow or {}).get((copy.get("shadow_id") or "").upper())
    if mine:
        who = "Crow-Eye (case %s)" % mine["case"]
        ev.append({"source": "Crow-Eye custody records",
                   "text": "Made by Crow-Eye in case %s at %s UTC to read locked files (%s). Crow-Eye deletes "
                           "its copies when a run ends: this one outlived a run that stopped early." % (
                               mine["case"], (mine["created_utc"] or "")[:19].replace("T", " "),
                               mine["command"] or "no command recorded")})
    s = spp.get(set_id)
    if s:
        why = s["description"] or why
        ev.append({"source": "SPP restore point metadata",
                   "text": "Restore point \"%s\" (%s), recorded %s UTC." % (
                       s["description"] or "no description", s["type"], s["created"].replace("T", " ").rstrip("Z"))})
    if rp and not s:
        why = rp.get("description") or why
        ev.append({"source": "System Restore (WMI)", "text": "Restore point %s \"%s\" (%s), %s UTC." % (
            rp.get("sequence"), rp.get("description"), rp.get("type"), (rp.get("created") or "").replace("T", " ")
            .rstrip("Z"))})
    if created is not None:
        for e in rp_events:
            t = _parse_utc(e["at"])
            if t is None or not (-30 <= (t - created).total_seconds() <= 180):
                continue
            if e["id"] == 8194:
                who = who or _who(e["process"])
                why = why or e["description"]
                ev.append({"source": "Application log, System Restore 8194",
                           "text": "%s UTC: restore point \"%s\" created, requested by %s" % (
                               e["at"].replace("T", " ").rstrip("Z"), e["description"], e["process"])})
            elif e["id"] == 8193:
                ev.append({"source": "Application log, System Restore 8193",
                           "text": "%s UTC: creating restore point \"%s\" FAILED (%s)" % (
                               e["at"].replace("T", " ").rstrip("Z"), e["description"], e["process"])})
    device = (copy.get("device") or "").rstrip("\\").upper()
    for e in scoping.get(device, [])[:3]:
        ev.append({"source": "Application log, System Restore %s" % e["id"],
                   "text": "%s UTC: System Restore scoped this very copy (%s)." % (
                       e["at"].replace("T", " ").rstrip("Z"), {8300: "started", 8301: "completed",
                                                               8302: "completed successfully",
                                                               8303: "failed"}.get(e["id"], e["id"]))})
        if not who:
            who = "System Restore"
    if req and req.get("command_line"):
        who = who or _who(req["command_line"])
        ev.append({"source": "Application log, VSS 8231",
                   "text": "%s UTC: creation requested by %s%s" % (
                       (req.get("at") or "").replace("T", " ").rstrip("Z"), req["command_line"],
                       ("  (called from %s)" % " <- ".join(req["callers"][:4])) if req.get("callers") else "")})
    d = diag.get(set_id) or {}
    if d:
        api = d.get("VssapiPublisher") or []
        snap = next((x for x in api if x["op"] in ("do snapshot", "prepare backup") and x["enter"]), None)
        parts = sorted(k for k in d if k not in ("VssapiPublisher", "VssvcPublisher") and not k.startswith("SwProvider"))
        text = "Last recorded in the VSS diagnostics key"
        if snap:
            name = names.get(snap["pid"])
            text += ": the requester, process %d%s, began \"%s\" at %s UTC" % (
                snap["pid"], (" (%s)" % name) if name else "", snap["op"], snap["at"].replace("T", " ").rstrip("Z"))
            if not who and name:
                who = _who(name)
        if parts:
            text += ". Taking part: %s" % ", ".join(parts)
            if not who and ("SystemRestore" in parts or "SPP" in parts):
                who = "System Restore"
        ev.append({"source": "Registry, VSS\\Diag", "text": text + "."})
    attrs = [a.lower() for a in (copy.get("attributes") or [])]
    if "autorecover" in attrs:
        ev.append({"source": "The copy's store",
                   "text": "Made with the VSS writers and auto-recovered: the way System Restore makes its copies."})
        who = who or "System Restore"
    elif "no writers" in attrs:
        ev.append({"source": "The copy's store",
                   "text": "Made without any VSS writer: the way Win32_ShadowCopy.Create (WMI), wmic, vssadmin and "
                           "some Windows components make copies."})
    if not who and not why:
        summary = ("No record names its requester (%s)." % (
            "made without writers: WMI, wmic, vssadmin or a Windows component" if "no writers" in attrs
            else "nothing on this machine logged it"))
    else:
        summary = ("%s: \"%s\"" % (who or "System Restore", why)) if why else (who or "")
    return {"summary": summary, "who": who, "why": why, "evidence": ev}


_live_cache: Dict[tuple, tuple] = {}
LIVE_MAX_AGE = 60.0


def snapshot(provenance: bool = True, max_age: float = None, days: int = 400) -> dict:
    """Every WMI and event-log answer the shadow-copy views need, from ONE PowerShell process
    (volume_layout.wmi_snapshot): copies, storage, volumes, and with `provenance` the restore points,
    VSS 8231, System Restore 8194 / 8300, volsnap removals and Security 4688 for the requesters' PIDs."""
    sections = dict(_vl.SECTIONS)
    sections["removals"] = _cmd_removals(days, 500)
    if provenance:
        pids = sorted(set(x["pid"] for comps in vss_diag().values() for x in comps.get("VssapiPublisher", [])
                          if x.get("pid")))
        sections.update(restore=_cmd_restore(), e8231=_cmd_8231(days), e8194=_cmd_8194(days),
                        e8300=_cmd_8300(days))
        if pids:
            sections["e4688"] = _cmd_4688(pids, 30)
    return _vl.wmi_snapshot(sections, max_age)


def live_copies(volume: str = None, provenance: bool = True, max_age: float = None) -> List[dict]:
    """Every shadow copy of this machine's NTFS volumes (or one volume), oldest first, each with
    its size, position, trigger and whether Windows still exposes it.

    Kept for `max_age` seconds (LIVE_MAX_AGE), so the Shadow Copies window and the File Browser share
    one reading; 0 reads again. Without `provenance` the event logs are not read (the copies, sizes and
    positions come back in about a second and a half) and each copy's trigger says so."""
    import copy as _copy
    import time as _time
    max_age = LIVE_MAX_AGE if max_age is None else max_age
    key = ((volume or "").rstrip(":\\").upper(), bool(provenance))
    hit = _live_cache.get(key) or (_live_cache.get((key[0], True)) if not provenance else None)
    if hit is not None and _time.time() - hit[0] <= max_age:
        return _copy.deepcopy(hit[1])
    snap = snapshot(provenance, max_age)
    storage = _vl.shadow_storage(snapshot=snap)
    letters = [volume.rstrip(":\\").upper()] if volume else sorted(storage)
    if provenance:
        reqs = requester_events(rows=snap.get("e8231"))
        rps = restore_points(rows=snap.get("restore"))
        diag = vss_diag()
        rp_events = restore_point_events(rows=snap.get("e8194"))
        scoping = scoping_events(rows=snap.get("e8300"))
        pids = [x["pid"] for comps in diag.values() for x in comps.get("VssapiPublisher", [])]
        names = process_names(pids, rows=snap.get("e4688") or [])
        crow = crow_eye_created()
    else:
        reqs, rps, diag, rp_events, scoping, names, crow = {}, [], {}, [], {}, {}, {}
    out = []
    for letter in letters:
        copies, catalog_bytes, note = _vl.shadow_copies(letter, snapshot=snap)
        spp = spp_restore_points(letter) if provenance else {}
        # A restore point belongs to the one copy made closest to it, within a minute: Windows
        # Update's point is written seconds after its copy, and the copy a minute before it is
        # someone else's.
        owner = {}
        for i, p in enumerate(rps):
            pt = _parse_utc(p["created"])
            if pt is None:
                continue
            best = min(((abs((_parse_utc(c.get("created")) - pt).total_seconds()), j)
                        for j, c in enumerate(copies) if _parse_utc(c.get("created")) is not None), default=None)
            if best and best[0] <= 60:
                owner[best[1]] = p
        # A restore-point event belongs to the one copy made closest to it, within two minutes, as a
        # restore point does: the copy made a minute and a half earlier is someone else's.
        owned_events: Dict[int, List[dict]] = {}
        for e in rp_events:
            et = _parse_utc(e["at"])
            if et is None:
                continue
            best = min(((abs((_parse_utc(c.get("created")) - et).total_seconds()), j)
                        for j, c in enumerate(copies) if _parse_utc(c.get("created")) is not None), default=None)
            if best and best[0] <= 120:
                owned_events.setdefault(best[1], []).append(e)
        for j, c in enumerate(copies):
            c["catalog_bytes"] = catalog_bytes
            c["note"] = note
            req = reqs.get((c.get("set_id") or "").upper())
            rp = owner.get(j)
            c["requester"] = req
            c["restore_point"] = rp
            if provenance:
                c["provenance"] = _provenance(c, spp, diag, owned_events.get(j, []), scoping, req, rp, names, crow)
                c["trigger"] = c["provenance"]["summary"]
            else:
                c["provenance"] = None
                c["trigger"] = "Finding out..."
            c["exposed"] = bool(c.get("in_wmi") and c.get("device"))
            out.append(c)
    out = sorted(out, key=lambda c: (c["volume"], c.get("created") or ""))
    _live_cache[key] = (_time.time(), _copy.deepcopy(out))
    return out


# ---------------------------------------------------------------------------------------------
# reading copies: Crow-Eye's own VSS reader (vss_reader) over a live volume or an image partition
# ---------------------------------------------------------------------------------------------
class VolumeSlice(io.RawIOBase):
    """One partition of an image (or any stream) as a seekable volume of its own."""

    def __init__(self, fh, offset: int, size: int):
        super().__init__()
        self.fh, self.offset, self.size = fh, offset, size
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        self._pos = offset if whence == io.SEEK_SET else (
            self._pos + offset if whence == io.SEEK_CUR else self.size + offset)
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self._pos
        n = max(0, min(n, self.size - self._pos))
        self.fh.seek(self.offset + self._pos)
        data = self.fh.read(n)
        self._pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


class RawVolume(io.RawIOBase):
    """This machine's volume read raw (administrator): reads are aligned to 4 KiB as the device
    requires, so callers may read any offset and length."""
    ALIGN = 4096

    def __init__(self, letter: str):
        super().__init__()
        import shutil
        letter = letter.rstrip(":\\").upper()
        self.letter = letter
        self.size = shutil.disk_usage("%s:\\" % letter).total
        self.f = open("\\\\.\\%s:" % letter, "rb", buffering=0)
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        self._pos = offset if whence == io.SEEK_SET else (
            self._pos + offset if whence == io.SEEK_CUR else self.size + offset)
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self._pos
        n = max(0, min(n, self.size - self._pos))
        if not n:
            return b""
        start = self._pos - self._pos % self.ALIGN
        end = self._pos + n
        end += (-end) % self.ALIGN
        self.f.seek(start)
        data = self.f.read(end - start)[self._pos - start:self._pos - start + n]
        self._pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass
        super().close()


def raw_volume(letter: str) -> RawVolume:
    return RawVolume(letter)


def open_image_volume(image_path: str, partition_number: int):
    """(image accessor, volume stream) for one partition of an image: the image's own container
    (E01, VHDX, VMDK, raw) as the image accessor opens it, cut to the partition it lists."""
    from Artifacts_Collectors.Forensics_Image_parsing.image_parser import ImageParser
    parser = ImageParser()
    strategy = parser.get_strategy(file_source=image_path)
    if not strategy:
        raise ValueError("Unsupported forensic image format: %s" % image_path)
    if hasattr(strategy, "_open_image") and not strategy._open_image(image_path):
        raise ValueError("Could not open the image: %s" % image_path)
    img = strategy.get_img_info()
    partitions = strategy.list_partitions() if hasattr(strategy, "list_partitions") else []
    part = next((p for p in partitions if p.partition_number == partition_number), None)
    offset = part.start_offset if part else 0
    total = getattr(img, "size", None)
    if total is None:
        img.seek(0, io.SEEK_END)
        total = img.tell()
    size = part.size_bytes if part and part.size_bytes else total - offset
    return strategy, VolumeSlice(img, offset, size)


def open_vss(volume_stream) -> vss_reader.VssVolume:
    """The VSS catalog of a volume stream (raw volume or image partition)."""
    return vss_reader.VssVolume(volume_stream, getattr(volume_stream, "size", None))


def find_store(volume_stream, shadow_id: str = None, index: int = None) -> vss_reader.Store:
    """One copy of a volume, by its id or its index (oldest first)."""
    vss = open_vss(volume_stream)
    try:
        store = vss.find(copy_id=shadow_id) if shadow_id else vss.find(index=index)
    except vss_reader.VssError:
        raise ValueError("The volume's catalog holds no shadow copy %s" % (shadow_id or index))
    if not store.readable:
        raise ValueError("Shadow copy %s cannot be read: %s" % (store.copy_id or store.store_id,
                                                               "; ".join(store.problems)))
    return store


def snapshot_stream(store: vss_reader.Store) -> vss_reader.SnapshotStream:
    """A shadow copy as a readable volume (vss_reader: measured block for block against Windows)."""
    return store.open()


def image_copies(image_path: str, partition_number: int) -> List[dict]:
    """The shadow copies inside one partition of a forensic image, oldest first, with what the
    catalog says of each: {index, created, shadow_id, set_id, store_bytes, attributes, ...}.
    store_bytes is the store's range list (the data it holds on the volume); an image has no WMI."""
    _strategy, vol = open_image_volume(image_path, partition_number)
    try:
        vss = open_vss(vol)
    except vss_reader.VssError:
        return []
    out = []
    for s in vss.stores:
        if not s.readable:
            continue
        out.append({"index": s.index, "number": s.index + 1, "created": s.created or "",
                    "shadow_id": s.copy_id, "set_id": s.set_id or "",
                    "store_bytes": s.footprint(), "extents": s.ranges(), "exposed": False, "in_wmi": False,
                    "in_catalog": True, "device": "", "volume": "",
                    "attributes": s.attribute_names(), "originating_machine": s.originating_machine,
                    "trigger": "Not recorded: an image's own event logs say, once the case has parsed them"})
    return out


def _guid(value) -> str:
    try:
        return "{%s}" % str(uuid.UUID(str(value).strip("{}"))).upper()
    except Exception:
        return str(value or "")


if __name__ == "__main__":
    import sys
    for c in live_copies(sys.argv[1] if len(sys.argv) > 1 else None):
        print("#%s %s %s %s exposed=%s | %s" % (c.get("number"), c.get("created"), c["volume"],
                                                size_text(c.get("store_bytes")), c["exposed"], c["trigger"]))
    for r in removals()[:8]:
        print(r["at"], r["event_id"], r["reason"])


provenance = _provenance          # the name the function had before live_copies took a parameter of it
