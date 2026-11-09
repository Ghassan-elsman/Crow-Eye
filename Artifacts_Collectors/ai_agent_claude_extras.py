"""What Claude Code keeps besides its conversations, as rows for AI_Agent_Claw.

Every table is created in AI_Agent_Claw.py (Sentinel's extract-schema reads one
file per family); this module only reads and returns rows. Paths are under one
user profile folder - the live C:\\Users\\<name>, or the same folder collected
from an image - and nothing else is opened. Credential files are never read.

  .claude\\sessions\\<pid>.json              which process ran which session
  .claude\\daemon\\attach-journal\\*.json      processes the background daemon ran
  .claude\\file-history\\<session>\\<name>@vN  the copy saved before each edit
  %TEMP%\\claude\\*\\<session>\\tasks\\*.output a background command's output, ending
                                            "[exited with code N]"
  .claude\\tasks\\<session>\\N.json            the agent's todo list
  .claude\\plans\\*.md                        plans written in plan mode
  .claude\\jobs\\<id>\\state.json, timeline.jsonl  background jobs (never tmp\\)
  .claude\\history.jsonl                     each prompt typed, with its project
  .claude\\settings*.json, .claude.json,      what the agent was allowed or set
  <project>\\.claude\\settings*.json,          up to do: permissions, hooks (commands
  plugins, skills                            that run on their own), MCP servers
"""

import datetime
import glob
import hashlib
import json
import os
import re
from typing import Dict, List, Tuple

from utils.time_utils import format_forensic_timestamp

_EXIT_TRAILER = re.compile(rb"\[exited with code (-?\d+)\]\s*$")
# Never opened, whatever folder they turn up in.
CREDENTIAL_NAMES = {".credentials.json", "credentials.json", "auth.json", "oauth_creds.json"}


def mtime_ts(path) -> str:
    try:
        return format_forensic_timestamp(datetime.datetime.fromtimestamp(
            os.path.getmtime(path), tz=datetime.timezone.utc))
    except (OSError, ValueError, OverflowError):
        return ""


def epoch_ts(value) -> str:
    """'YYYY-MM-DD HH:MM:SS' from epoch seconds or milliseconds."""
    try:
        v = float(value)
        if v > 1e11:
            v /= 1000.0
        return format_forensic_timestamp(datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def read_json(path):
    if os.path.basename(path).lower() in CREDENTIAL_NAMES:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def sha1_of(path) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


# ------------------------------------------------------------------ processes
def task_exit_codes(profile) -> Dict[str, Tuple[int, str]]:
    """Background task id -> (exit code, when its output was last written)."""
    root = os.path.join(profile, "AppData", "Local", "Temp", "claude")
    out = {}
    for path in glob.glob(os.path.join(root, "*", "*", "tasks", "*.output")):
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - 160))
                m = _EXIT_TRAILER.search(f.read())
        except OSError:
            continue
        if m:
            out[os.path.splitext(os.path.basename(path))[0]] = (int(m.group(1)), mtime_ts(path))
    return out


def processes(profile, agent, user) -> List[dict]:
    """One row per process the agent recorded: its PID, start and session."""
    claude = os.path.join(profile, ".claude")
    rows = []
    for path in glob.glob(os.path.join(claude, "sessions", "*.json")):
        j = read_json(path)
        if not isinstance(j, dict) or j.get("pid") is None:
            continue
        rows.append({"agent": agent, "user_name": user, "pid": j.get("pid"),
                     "process_start": str(j.get("procStart") or ""),
                     "session_id": str(j.get("sessionId") or ""), "cwd": str(j.get("cwd") or ""),
                     "started_at": epoch_ts(j.get("startedAt")) or mtime_ts(path),
                     "kind": str(j.get("kind") or ""), "entrypoint": str(j.get("entrypoint") or ""),
                     "version": str(j.get("version") or ""), "source_path": path})
    for path in glob.glob(os.path.join(claude, "daemon", "attach-journal", "*.json")):
        j = read_json(path)
        if not isinstance(j, dict) or j.get("pid") is None:
            continue
        rows.append({"agent": agent, "user_name": user, "pid": j.get("pid"),
                     "process_start": str(j.get("procStart") or ""), "session_id": "",
                     "cwd": "", "started_at": epoch_ts(j.get("startedAtEpochMs")) or mtime_ts(path),
                     "kind": "daemon " + str(j.get("surface") or ""), "entrypoint": "daemon",
                     "version": "", "source_path": path})
    return rows


# --------------------------------------------------------------- file history
def file_versions(profile, agent, user, session_id, versions, known_sha1) -> List[dict]:
    """Rows for the saved copies a session's records name.

    `known_sha1` maps a backup path already stored to its hash, so a file is
    hashed once, not on every parse."""
    folder = os.path.join(profile, ".claude", "file-history", session_id.split("/")[0])
    rows = []
    for v in versions:
        path = v["file_path"]
        if path and not os.path.isabs(path):
            path = os.path.join(profile, path)
        backup = os.path.join(folder, v["backup_name"]) if v.get("backup_name") else ""
        size, sha1 = None, ""
        if backup and os.path.isfile(backup):
            size = os.path.getsize(backup)
            sha1 = known_sha1.get(backup) or sha1_of(backup)
        rows.append({"agent": agent, "user_name": user, "session_id": session_id,
                     "file_path": path, "version": v.get("version"), "saved_at": v.get("saved_at") or "",
                     "size": size, "sha1": sha1,
                     # no backup: the file did not exist before the agent wrote it
                     "backup_path": backup, "in_case_path": ""})
    return rows


# ------------------------------------------------------- todos, plans, jobs
def todos(profile) -> List[Tuple[str, dict, str]]:
    """[(session id, todo, file)] from .claude\\tasks\\<session>\\N.json."""
    out = []
    for path in glob.glob(os.path.join(profile, ".claude", "tasks", "*", "*.json")):
        j = read_json(path)
        if isinstance(j, dict):
            out.append((os.path.basename(os.path.dirname(path)), j, path))
    return out


def plans(profile) -> List[Tuple[str, str, str]]:
    """[(file, text, modified)] for .claude\\plans\\*.md."""
    out = []
    for path in sorted(glob.glob(os.path.join(profile, ".claude", "plans", "*.md"))):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                out.append((path, f.read(), mtime_ts(path)))
        except OSError:
            continue
    return out


def jobs(profile) -> List[Tuple[str, dict, List[dict], str]]:
    """[(job id, state, timeline entries, state file)]: metadata only."""
    out = []
    for state_path in glob.glob(os.path.join(profile, ".claude", "jobs", "*", "state.json")):
        state = read_json(state_path)
        if not isinstance(state, dict):
            continue
        timeline = []
        tl = os.path.join(os.path.dirname(state_path), "timeline.jsonl")
        try:
            with open(tl, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict):
                        timeline.append(e)
        except OSError:
            pass
        out.append((os.path.basename(os.path.dirname(state_path)), state, timeline, state_path))
    return out


def history(profile) -> List[dict]:
    """Every line of .claude\\history.jsonl: a prompt the person typed."""
    path = os.path.join(profile, ".claude", "history.jsonl")
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if isinstance(j, dict) and j.get("display"):
                    j["_source"] = path
                    out.append(j)
    except OSError:
        pass
    return out


# ------------------------------------------------------------------- settings
def _setting_rows(agent, user, scope, path, j, mask) -> List[dict]:
    rows = []
    modified = mtime_ts(path)

    def add(setting, value):
        rows.append({"agent": agent, "user_name": user, "scope": scope, "setting": setting,
                     "value": mask(str(value))[:2000], "source_path": path,
                     "source_modified": modified})

    if not isinstance(j, dict):
        return rows
    perms = j.get("permissions") if isinstance(j.get("permissions"), dict) else {}
    for k in ("allow", "deny", "ask", "additionalDirectories"):
        for rule in perms.get(k) or []:
            add("permissions.%s" % k, rule)
    if perms.get("defaultMode"):
        add("permissions.defaultMode", perms.get("defaultMode"))
    for k in ("model", "autoMode", "defaultMode", "outputStyle", "apiKeyHelper"):
        if j.get(k) not in (None, "", {}):
            add(k, j.get(k) if not isinstance(j.get(k), (dict, list)) else json.dumps(j.get(k)))
    # Hooks run commands on their own when an event fires: each command is one row.
    hooks = j.get("hooks") if isinstance(j.get("hooks"), dict) else {}
    for event, entries in hooks.items():
        for entry in entries if isinstance(entries, list) else []:
            for h in (entry.get("hooks") if isinstance(entry, dict) else None) or []:
                if isinstance(h, dict) and h.get("command"):
                    add("hook %s" % event, h.get("command"))
    for name in (j.get("enabledPlugins") or {}):
        add("enabledPlugin", name)
    servers = j.get("mcpServers") if isinstance(j.get("mcpServers"), dict) else {}
    for name, cfg in servers.items():
        rows.extend(mcp_server_rows(agent, user, scope, path, modified, name, cfg, mask))
    # env: the variable NAMES only - values are where tokens live
    env = j.get("env") if isinstance(j.get("env"), dict) else {}
    for name in env:
        add("env", name)
    return rows


def mcp_server_rows(agent, user, scope, path, modified, name, cfg, mask) -> List[dict]:
    """One row per MCP server: what it runs (command and arguments, or URL);
    its environment's variable names, never their values."""
    if not isinstance(cfg, dict):
        return []
    runs = cfg.get("command") or cfg.get("url") or ""
    args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
    value = " ".join([str(runs)] + [str(a) for a in args]).strip()
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    if env:
        value += "  [env: %s]" % ", ".join(sorted(env))
    return [{"agent": agent, "user_name": user, "scope": scope, "setting": "mcp_server %s" % name,
             "value": mask(value)[:2000], "source_path": path, "source_modified": modified}]


def settings(profile, agent, user, project_dirs, mask) -> List[dict]:
    """What Claude Code was allowed and set up to do, per scope."""
    claude = os.path.join(profile, ".claude")
    rows = []
    for name, scope in (("settings.json", "user"), ("settings.local.json", "user local")):
        p = os.path.join(claude, name)
        if os.path.isfile(p):
            rows += _setting_rows(agent, user, scope, p, read_json(p), mask)
    # .claude.json: MCP servers for the user and per project, and the tools
    # each project allowed.
    p = os.path.join(profile, ".claude.json")
    j = read_json(p) if os.path.isfile(p) else None
    if isinstance(j, dict):
        modified = mtime_ts(p)
        for name, cfg in (j.get("mcpServers") or {}).items():
            rows += mcp_server_rows(agent, user, "user", p, modified, name, cfg, mask)
        for proj, pj in (j.get("projects") or {}).items():
            if not isinstance(pj, dict):
                continue
            for name, cfg in (pj.get("mcpServers") or {}).items():
                rows += mcp_server_rows(agent, user, "project %s" % proj, p, modified, name, cfg, mask)
            for tool in pj.get("allowedTools") or []:
                rows.append({"agent": agent, "user_name": user, "scope": "project %s" % proj,
                             "setting": "allowedTools", "value": mask(str(tool)), "source_path": p,
                             "source_modified": modified})
    for proj in sorted(set(d for d in project_dirs if d)):
        for name in ("settings.json", "settings.local.json"):
            sp = os.path.join(proj, ".claude", name)
            if os.path.isfile(sp):
                rows += _setting_rows(agent, user, "project %s" % proj, sp, read_json(sp), mask)
    ip = os.path.join(claude, "plugins", "installed_plugins.json")
    j = read_json(ip) if os.path.isfile(ip) else None
    if isinstance(j, dict):
        plugins = j.get("plugins") if isinstance(j.get("plugins"), dict) else {}
        for name, info in plugins.items():
            ver = ""
            if isinstance(info, list) and info and isinstance(info[0], dict):
                ver = info[0].get("version") or ""
            elif isinstance(info, dict):
                ver = info.get("version") or ""
            rows.append({"agent": agent, "user_name": user, "scope": "user", "setting": "plugin",
                         "value": ("%s %s" % (name, ver)).strip(), "source_path": ip,
                         "source_modified": mtime_ts(ip)})
    for d in sorted(glob.glob(os.path.join(claude, "skills", "*"))):
        if os.path.isdir(d):
            rows.append({"agent": agent, "user_name": user, "scope": "user", "setting": "skill",
                         "value": os.path.basename(d), "source_path": d, "source_modified": mtime_ts(d)})
    return rows
