"""The other AI agents' records, read into AI_Agent_Claw's sessions and steps.

Every table is created in AI_Agent_Claw.py; this module reads. Each reader
takes the Claw module `c` (its _Session, _cap, _ts, tool kinds, masking) so the
two stay one parser without a circular import. Formats are as found on a real
machine on 2026-11-04; a reader that meets a shape it does not know skips the
record rather than guess.

  Claude desktop    %APPDATA%\\Claude\\claude-code-sessions\\**\\local_*.json (which CLI
                    session the desktop ran, its title); local-agent-mode-sessions\\
                    *\\*\\local_*\\ - an embedded .claude (read as Claude Code, app
                    desktop-agent-mode), audit.jsonl (signed: model, permission mode,
                    MCP servers, tools) and outputs\\ (files the agent made)
  Codex             .codex\\state_5.sqlite threads (git sha, origin, sandbox,
                    approval, model) and thread_history_1.sqlite thread_items for a
                    thread with no rollout
  Gemini CLI        .gemini\\tmp\\*\\logs.json: prompts of a session with no chat file
  Antigravity       .gemini\\antigravity\\conversations\\<id>.db (steps are protobuf:
                    counted and timed, not decoded), brain\\<id>\\*.md (its plans),
                    browser_recordings\\<id>\\<ns>.jpg (screenshots of pages it drove)
  GitHub Copilot    .copilot\\session-state\\<id>\\events.jsonl, session-store.db
                    (sessions, turns, session_files, forge_trajectory_events with
                    command and exit code), logs\\process-<ms>-<pid>.log
  Roo / Kilo /      %APPDATA%\\Code\\User\\globalStorage\\<extension>\\tasks\\<id>\\
  Cline             api_conversation_history.json (Anthropic-format tool calls),
                    history_item.json (task, workspace, mode)
"""

import glob
import json
import os
import re
import shutil
import sqlite3
import tempfile
from typing import Dict, List

ANTIGRAVITY, COPILOT = "Antigravity", "GitHub Copilot"
VSCODE_AGENTS = (("rooveterinaryinc.roo-cline", "Roo Code"), ("kilocode.kilo-code", "Kilo Code"),
                 ("saoudrizwan.claude-dev", "Cline"))
_SKIP = {"auth.json", "oauth_creds.json", ".credentials.json", ".audit-key"}


def roaming(profile):
    return os.path.join(profile, "AppData", "Roaming")


def _copy_db(src):
    """A private copy of an SQLite file and its WAL, opened read-only."""
    tmp = tempfile.mkdtemp(prefix="crow_ai_")
    dst = os.path.join(tmp, os.path.basename(src))
    for s in ("", "-wal", "-shm"):
        if os.path.isfile(src + s):
            shutil.copy2(src + s, dst + s)
    return tmp, sqlite3.connect(dst)


def _json(path):
    if os.path.basename(path).lower() in _SKIP:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------- file sources
def file_sources(profile, c) -> List[tuple]:
    """(agent, file) pairs read one file at a time (skipped when unchanged)."""
    out = []
    lam = os.path.join(roaming(profile), "Claude", "local-agent-mode-sessions")
    for p in glob.glob(os.path.join(lam, "*", "*", "local_*", ".claude", "projects", "**", "*.jsonl"),
                       recursive=True):
        out.append((c.CLAUDE_CODE, p))
    for ext, agent in VSCODE_AGENTS:
        for p in glob.glob(os.path.join(roaming(profile), "Code", "User", "globalStorage", ext, "tasks",
                                        "*", "api_conversation_history.json")):
            out.append((agent, p))
    for p in glob.glob(os.path.join(profile, ".copilot", "session-state", "*", "events.jsonl")):
        out.append((COPILOT, p))
    for p in glob.glob(os.path.join(profile, ".gemini", "antigravity", "conversations", "*.db")):
        out.append((ANTIGRAVITY, p))
    return out


# ----------------------------------------------------------- Roo/Kilo/Cline
def read_cline(c, path, user, limit, agent):
    """One task of a Cline-family extension (Roo Code, Kilo Code, Cline)."""
    msgs = _json(path)
    if not isinstance(msgs, list):
        return []
    folder = os.path.dirname(path)
    sid = os.path.basename(folder)
    s = c._Session(agent, user, sid, path)
    meta = _json(os.path.join(folder, "history_item.json")) or {}
    if isinstance(meta, dict):
        s.row.update(title=c.mask_secrets(str(meta.get("task") or ""))[:300],
                     project_path=str(meta.get("workspace") or ""),
                     model=str(meta.get("apiConfigName") or ""),
                     approval_mode=str(meta.get("mode") or ""), app="vscode")
    s.row["app"] = "vscode"
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        ts = c._ts(m.get("ts"))
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        for k, item in enumerate(content):
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ == "text" and str(item.get("text") or "").strip():
                body = str(item.get("text"))
                if role == "user" and body.lstrip().startswith(("<environment_details>", "[")):
                    continue                 # the extension's own context or a tool echo
                text, n = c._cap(body, 0 if role == "user" else limit)
                s.step(step_id="m%d:%d" % (i, k), ts=ts, role="user" if role == "user" else "assistant",
                       kind="prompt" if role == "user" else "answer", text=text, text_length=n)
            elif typ == "tool_use":
                name = str(item.get("name") or "")
                kind, command, target = c._tool_fields(name, item.get("input"))
                text, n = c._cap(c._json(item.get("input")), limit)
                s.started[str(item.get("id"))] = c._epoch(m.get("ts"))
                s.step(step_id=str(item.get("id") or "m%d:%d" % (i, k)), ts=ts, role="assistant",
                       kind=kind, tool=name, command=command, target=target, text=text, text_length=n)
            elif typ == "tool_result":
                tid = str(item.get("tool_use_id") or "")
                s.finish(tid, c._epoch(m.get("ts")))
                text, n = c._cap(c._text_of(item.get("content")), limit)
                s.step(step_id=tid + ":result", ts=ts, role="tool", kind="result",
                       status="error" if item.get("is_error") else "ok", text=text, text_length=n)
    return [s] if s.steps else []


# ------------------------------------------------------------- Copilot CLI
def read_copilot_events(c, path, user, limit):
    """One Copilot CLI session folder's events.jsonl."""
    sid = os.path.basename(os.path.dirname(path))
    s = c._Session(COPILOT, user, sid, path)
    s.row["app"] = "cli"
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return []
    with f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            typ = e.get("type")
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            ts = c._ts(e.get("timestamp"))
            eid = str(e.get("id") or "")
            if typ in ("session.start", "session.resume"):
                ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
                s.row.update(project_path=str(ctx.get("cwd") or s.row["project_path"]),
                             git_branch=str(ctx.get("branch") or s.row["git_branch"]),
                             git_origin=str(ctx.get("repository") or s.row.get("git_origin") or ""))
                if d.get("selectedModel"):
                    s.row["model"] = str(d.get("selectedModel"))
                if d.get("copilotVersion"):
                    s.row["agent_version"] = str(d.get("copilotVersion"))
                s.step(step_id=eid, ts=ts, role="system", kind="notice", text=typ)
            elif typ == "session.model_change" and d.get("newModel"):
                s.row["model"] = str(d.get("newModel"))
            elif typ == "user.message":
                text, n = c._cap(str(d.get("content") or ""), 0)
                s.step(step_id=eid, ts=ts, role="user", kind="prompt", text=text, text_length=n)
            elif typ == "session.error":
                text, n = c._cap(str(d.get("message") or ""), limit)
                s.step(step_id=eid, ts=ts, role="system", kind="notice", status="error",
                       text=text, text_length=n)
            elif typ and typ.startswith("tool."):
                # tool.execution_start / _complete: name and arguments when present
                name = str(d.get("toolName") or d.get("name") or "")
                if not name:
                    continue
                kind, command, target = c._tool_fields(name, d.get("arguments") or d.get("args"))
                text, n = c._cap(c._json(d), limit)
                s.step(step_id=eid, ts=ts, role="assistant", kind=kind, tool=name,
                       command=command, target=target, text=text, text_length=n)
    return [s] if s.steps else []


def copilot_store(c, profile, user, limit, known: set):
    """Copilot's session-store.db: sessions with no events file, every file a
    session touched, and every command it ran with its exit code."""
    src = os.path.join(profile, ".copilot", "session-store.db")
    if not os.path.isfile(src):
        return [], []
    tmp, conn = _copy_db(src)
    sessions: Dict[str, object] = {}
    loose = []
    try:
        def sess(sid):
            s = sessions.get(sid)
            if s is None:
                s = sessions[sid] = c._Session(COPILOT, user, sid, src)
                s.row["app"] = "cli"
            return s
        try:
            for sid, cwd, repo, branch, summary, created, updated in conn.execute(
                    "SELECT id, cwd, repository, branch, summary, created_at, updated_at FROM sessions"):
                s = sess(str(sid))
                s.row.update(project_path=str(cwd or ""), git_origin=str(repo or ""),
                             git_branch=str(branch or ""), title=c.mask_secrets(str(summary or ""))[:300])
                if str(sid) not in known:
                    s.step(step_id="store:start", ts=c._ts(created), role="system", kind="notice",
                           text="session started")
        except sqlite3.Error:
            pass
        try:
            for tid, sid, idx, um, ar, ts in conn.execute(
                    "SELECT id, session_id, turn_index, user_message, assistant_response, timestamp FROM turns"):
                if str(sid) in known:
                    continue                    # its events file has the prompts
                s = sess(str(sid))
                if um:
                    text, n = c._cap(str(um), 0)
                    s.step(step_id="turn:%s" % tid, ts=c._ts(ts), role="user", kind="prompt",
                           text=text, text_length=n)
                if ar:
                    text, n = c._cap(str(ar), limit)
                    s.step(step_id="turn:%s:a" % tid, ts=c._ts(ts), role="assistant", kind="answer",
                           text=text, text_length=n)
        except sqlite3.Error:
            pass
        try:
            for fid, sid, fpath, tool, idx, seen in conn.execute(
                    "SELECT id, session_id, file_path, tool_name, turn_index, first_seen_at FROM session_files"):
                kind = c.tool_kind(tool or "")
                st = c._loose_step(COPILOT, user, str(sid), "file:%s" % fid, c._ts(seen), "assistant",
                                   kind if kind != "tool" else "file_edit", src, tool=str(tool or ""),
                                   target=c.mask_secrets(str(fpath or ""))[:1000])
                loose.append(st)
        except sqlite3.Error:
            pass
        try:
            for eid, sid, call, idx, etype, cmd, out, code, created in conn.execute(
                    "SELECT id, session_id, tool_call_id, turn_index, event_type, command, output, "
                    "exit_code, created_at FROM forge_trajectory_events"):
                if not cmd:
                    continue
                text, n = c._cap(str(out or ""), limit)
                st = c._loose_step(COPILOT, user, str(sid), "forge:%s" % eid, c._ts(created), "assistant",
                                   "command", src, tool=str(etype or ""), command=c.mask_secrets(str(cmd)),
                                   text=text, text_length=n,
                                   exit_code=code if isinstance(code, int) else None,
                                   output=text[:c.OUTPUT_CHARS],
                                   status="error" if isinstance(code, int) and code != 0 else "ok")
                st["program"] = c.program_of(str(cmd), "powershell")
                loose.append(st)
        except sqlite3.Error:
            pass
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return [s for s in sessions.values() if s.steps], loose


_PROC_LOG = re.compile(r"process-(\d{12,})-(\d+)\.log$", re.I)


def copilot_processes(c, profile, user):
    rows = []
    for p in glob.glob(os.path.join(profile, ".copilot", "logs", "process-*.log")):
        m = _PROC_LOG.search(os.path.basename(p))
        if m:
            rows.append({"agent": COPILOT, "user_name": user, "pid": int(m.group(2)), "process_start": m.group(1),
                         "session_id": "", "cwd": "", "started_at": c._extras.epoch_ts(int(m.group(1))),
                         "kind": "cli", "entrypoint": "copilot", "version": "", "source_path": p})
    return rows


# ---------------------------------------------------------------- Antigravity
def read_antigravity(c, path, user, limit):
    """One Antigravity conversation: its step count and times (the steps are
    protobuf), the plans it wrote, and the screenshots of pages it drove."""
    cid = os.path.splitext(os.path.basename(path))[0]
    root = os.path.dirname(os.path.dirname(path))
    s = c._Session(ANTIGRAVITY, user, cid, path)
    s.row["app"] = "desktop"
    steps = None
    try:
        tmp, conn = _copy_db(path)
        try:
            steps = conn.execute("SELECT count(*) FROM steps").fetchone()[0]
        finally:
            conn.close()
            shutil.rmtree(tmp, ignore_errors=True)
    except (sqlite3.Error, OSError):
        pass
    s.row["title"] = "[%s steps, stored as protobuf - not decoded]" % (
        steps if steps is not None else "unknown number of")
    s.step(step_id="conversation", ts=c._extras.mtime_ts(path), role="system", kind="notice",
           text="conversation file last written", target=path)
    _antigravity_steps(c, s, root, cid, limit)
    return [s]


def antigravity_orphans(c, profile, user, limit, known: set):
    """Plans and screenshot folders whose id names no conversation file: the
    recordings are kept under a different id than the conversation, and plans
    outlive their conversation."""
    root = os.path.join(profile, ".gemini", "antigravity")
    ids = set()
    for sub in ("brain", "browser_recordings"):
        for d in glob.glob(os.path.join(root, sub, "*")):
            if os.path.isdir(d):
                ids.add(os.path.basename(d))
    out = []
    for cid in sorted(ids - known):
        src = os.path.join(root, "browser_recordings", cid)
        if not os.path.isdir(src):
            src = os.path.join(root, "brain", cid)
        s = c._Session(ANTIGRAVITY, user, cid, src)
        s.row.update(app="desktop", title="[no conversation file: plans and screenshots only]")
        _antigravity_steps(c, s, root, cid, limit)
        if s.steps:
            out.append(s)
    return out


def _antigravity_steps(c, s, root, cid, limit):
    for md in sorted(glob.glob(os.path.join(root, "brain", cid, "*.md"))):
        meta = _json(md + ".metadata.json") or {}
        try:
            with open(md, "r", encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError:
            continue
        text, n = c._cap(body, limit)
        s.step(step_id="brain:%s" % os.path.basename(md),
               ts=c._ts(meta.get("updatedAt")) or c._extras.mtime_ts(md), role="assistant", kind="plan",
               tool=str(meta.get("artifactType") or ""), target=md, text=text, text_length=n)
    for jpg in sorted(glob.glob(os.path.join(root, "browser_recordings", cid, "*.jpg"))):
        stem = os.path.splitext(os.path.basename(jpg))[0]
        ts = c._extras.epoch_ts(int(stem) / 1e9) if stem.isdigit() else c._extras.mtime_ts(jpg)
        s.step(step_id="shot:%s" % stem, ts=ts, role="assistant", kind="screenshot", target=jpg)


# ------------------------------------------------------------ Claude desktop
def claude_desktop(c, profile, user, limit):
    """(sessions, loose steps, settings rows) from the Claude desktop app."""
    base = os.path.join(roaming(profile), "Claude")
    sessions, loose, settings = [], [], []
    for p in glob.glob(os.path.join(base, "claude-code-sessions", "**", "local_*.json"), recursive=True):
        j = _json(p)
        if not isinstance(j, dict):
            continue
        sid = str(j.get("cliSessionId") or j.get("sessionId") or "")
        if not sid:
            continue
        s = c._Session(c.CLAUDE_CODE, user, sid, p)
        s.row.update(title=c.mask_secrets(str(j.get("title") or ""))[:300], project_path=str(j.get("cwd") or ""),
                     model=str(j.get("model") or ""), app="desktop", entrypoint="claude-desktop")
        s.step(step_id="desktop:created", ts=c._extras.epoch_ts(j.get("createdAt")), role="system",
               kind="notice", text="session created in the Claude desktop app")
        if j.get("lastActivityAt"):
            s.step(step_id="desktop:last", ts=c._extras.epoch_ts(j.get("lastActivityAt")), role="system",
                   kind="notice", text="last activity")
        sessions.append(s)
    lam = os.path.join(base, "local-agent-mode-sessions")
    for folder in glob.glob(os.path.join(lam, "*", "*", "local_*")):
        ids = [os.path.splitext(os.path.basename(x))[0] for x in
               glob.glob(os.path.join(folder, ".claude", "projects", "*", "*.jsonl"))]
        sid = ids[0] if ids else os.path.basename(folder)
        audit = os.path.join(folder, "audit.jsonl")
        if os.path.isfile(audit):
            modified = c._extras.mtime_ts(audit)
            try:
                with open(audit, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"type":"system"' not in line.replace(" ", ""):
                            continue
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        scope = "desktop agent session %s" % (e.get("session_id") or sid)

                        def add(setting, value):
                            settings.append({"agent": c.CLAUDE_CODE, "user_name": user, "scope": scope,
                                             "setting": setting, "value": c.mask_secrets(str(value))[:2000],
                                             "source_path": audit, "source_modified": modified})
                        for k in ("permissionMode", "model", "claude_code_version", "cwd"):
                            if e.get(k):
                                add(k, e.get(k))
                        for m in e.get("mcp_servers") or []:
                            if isinstance(m, dict):
                                add("mcp_server %s" % m.get("name"), m.get("status") or "")
                        if e.get("tools"):
                            add("tools", ", ".join(str(t) for t in e.get("tools")))
            except OSError:
                pass
        for out in glob.glob(os.path.join(folder, "outputs", "**", "*"), recursive=True):
            if os.path.isfile(out):
                loose.append(c._loose_step(c.CLAUDE_CODE, user, sid, "output:%s" % os.path.relpath(out, folder),
                                           c._extras.mtime_ts(out), "assistant", "file_write", out,
                                           tool="outputs", target=out))
    return sessions, loose, settings


# ---------------------------------------------------------------------- Codex
def codex_threads(c, profile, user, limit, known: set):
    """(thread metadata by id, sessions for threads with no rollout read)."""
    codex = os.path.join(profile, ".codex")
    meta: Dict[str, dict] = {}
    state = os.path.join(codex, "state_5.sqlite")
    if not os.path.isfile(state):
        cands = sorted(glob.glob(os.path.join(codex, "state_*.sqlite")))
        state = cands[-1] if cands else ""
    if state:
        try:
            tmp, conn = _copy_db(state)
            try:
                conn.row_factory = sqlite3.Row
                for r in conn.execute("SELECT * FROM threads"):
                    meta[str(r["id"])] = dict(r)
            finally:
                conn.close()
                shutil.rmtree(tmp, ignore_errors=True)
        except (sqlite3.Error, OSError):
            pass
    sessions = []
    hist = os.path.join(codex, "thread_history_1.sqlite")
    if os.path.isfile(hist):
        try:
            tmp, conn = _copy_db(hist)
            try:
                by: Dict[str, object] = {}
                for tid, iid, created, item_json, itype in conn.execute(
                        "SELECT thread_id, item_id, created_at_ms, item_json, item_type FROM thread_items "
                        "ORDER BY created_at_ms"):
                    tid = str(tid)
                    if tid in known:
                        continue            # its rollout was read
                    s = by.get(tid)
                    if s is None:
                        s = by[tid] = c._Session(c.CODEX, user, tid, hist)
                    try:
                        item = json.loads(item_json)
                    except (TypeError, ValueError):
                        continue
                    ts = c._ts(created)
                    if itype in ("userMessage", "agentMessage"):
                        body = c._text_of(item.get("content") or item.get("text") or item.get("message"))
                        if body.strip():
                            text, n = c._cap(body, 0)
                            s.step(step_id=str(iid), ts=ts, role="user" if itype == "userMessage" else "assistant",
                                   kind="prompt" if itype == "userMessage" else "answer", text=text, text_length=n)
                    elif itype == "mcpToolCall":
                        name = "mcp__%s__%s" % (item.get("server") or "", item.get("tool") or "")
                        kind, command, target = c._tool_fields(name, item.get("arguments"))
                        text, n = c._cap(c._json(item.get("arguments")), limit)
                        s.step(step_id=str(iid), ts=ts, role="assistant", kind=kind, tool=name,
                               command=command, target=target, status=str(item.get("status") or ""),
                               text=text, text_length=n,
                               duration_ms=item.get("durationMs") if isinstance(item.get("durationMs"), int) else None)
                    elif itype == "commandExecution":
                        cmd = item.get("command")
                        cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
                        s.step(step_id=str(iid), ts=ts, role="assistant", kind="command", tool="commandExecution",
                               command=c.mask_secrets(cmd), cwd=str(item.get("cwd") or ""),
                               exit_code=item.get("exitCode") if isinstance(item.get("exitCode"), int) else None,
                               duration_ms=item.get("durationMs") if isinstance(item.get("durationMs"), int) else None)
                sessions = [s for s in by.values() if s.steps]
            finally:
                conn.close()
                shutil.rmtree(tmp, ignore_errors=True)
        except (sqlite3.Error, OSError):
            pass
    for s in sessions:
        apply_codex_meta(s.row, meta.get(s.row["session_id"]))
    return meta, sessions


def apply_codex_meta(row, m):
    if not m:
        return
    for col, key in (("git_sha", "git_sha"), ("git_origin", "git_origin_url"), ("git_branch", "git_branch"),
                     ("sandbox_policy", "sandbox_policy"), ("approval_mode", "approval_mode"),
                     ("model", "model"), ("title", "title"), ("project_path", "cwd"),
                     ("agent_version", "cli_version")):
        v = m.get(key)
        if v not in (None, "") and not row.get(col):
            row[col] = str(v)[:300]


def codex_settings(c, profile, user):
    """MCP servers and computer use from Codex's config.toml and computer-use."""
    rows = []
    cfg = os.path.join(profile, ".codex", "config.toml")
    if os.path.isfile(cfg):
        try:
            import tomllib
            with open(cfg, "rb") as f:
                t = tomllib.load(f)
        except Exception:
            t = {}
        modified = c._extras.mtime_ts(cfg)
        for name, server in (t.get("mcp_servers") or {}).items():
            rows += c._extras.mcp_server_rows(c.CODEX, user, "user", cfg, modified, name, server, c.mask_secrets)
        for k in ("model", "approval_policy", "sandbox_mode"):
            if t.get(k):
                rows.append({"agent": c.CODEX, "user_name": user, "scope": "user", "setting": k,
                             "value": str(t.get(k)), "source_path": cfg, "source_modified": modified})
    cu = os.path.join(profile, ".codex", "computer-use", "config.json")
    j = _json(cu) if os.path.isfile(cu) else None
    if isinstance(j, dict):
        for k, v in j.items():
            if not isinstance(v, (dict, list)):
                rows.append({"agent": c.CODEX, "user_name": user, "scope": "computer use",
                             "setting": str(k), "value": c.mask_secrets(str(v))[:2000], "source_path": cu,
                             "source_modified": c._extras.mtime_ts(cu)})
    ag = os.path.join(profile, ".gemini", "antigravity", "mcp_config.json")
    j = _json(ag) if os.path.isfile(ag) else None
    if isinstance(j, dict):
        for name, server in (j.get("mcpServers") or {}).items():
            rows += c._extras.mcp_server_rows(ANTIGRAVITY, user, "user", ag, c._extras.mtime_ts(ag),
                                              name, server, c.mask_secrets)
    return rows


# ---------------------------------------------------------------- Gemini CLI
def gemini_log_prompts(c, profile, user, known: set):
    """Prompts in .gemini\\tmp\\*\\logs.json for a session with no chat file."""
    by: Dict[str, object] = {}
    for p in glob.glob(os.path.join(profile, ".gemini", "tmp", "*", "logs.json")):
        entries = _json(p)
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict) or e.get("type") != "user":
                continue
            sid = str(e.get("sessionId") or "")
            if not sid or sid in known:
                continue
            s = by.get(sid)
            if s is None:
                s = by[sid] = c._Session(c.GEMINI_CLI, user, sid, p)
                s.row.update(title="[chat file not found: prompts from logs.json]",
                             project_path="project " + os.path.basename(os.path.dirname(p))[:16])
            text, n = c._cap(str(e.get("message") or ""), 0)
            s.step(step_id="log:%s" % e.get("messageId"), ts=c._ts(e.get("timestamp")), role="user",
                   kind="prompt", text=text, text_length=n)
    return [s for s in by.values() if s.steps]
