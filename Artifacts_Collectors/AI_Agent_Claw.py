"""AI agent sessions: what an AI coding or computer-use agent was asked, and what it did.

Three agents keep a session record in the user's profile, written as they work:

  Claude Code   %USERPROFILE%\\.claude\\projects\\<project>\\<session>.jsonl, one JSON
                line per message; a sub-agent's in <session>\\subagents\\*.jsonl
  Gemini CLI    %USERPROFILE%\\.gemini\\tmp\\<project hash>\\chats\\session-*.json
  Codex         %USERPROFILE%\\.codex\\sessions\\YYYY\\MM\\DD\\rollout-*.jsonl(.zst) and
                archived_sessions\\; the session title from state_5.sqlite

Two tables in ai_agents.db:

  ai_agent_sessions  one row per session: agent, account, project folder, model,
                     version, approval mode, first and last step, counts
  ai_agent_steps     one row per step: a prompt the person typed, the agent's
                     answer, each command it ran, each file it read, wrote or
                     edited, each web or other tool call, and that call's result

The record is the agent's own, so a step's time is when the agent took it and
a command row is proof that the agent - not a person at the keyboard - ran it.
Content is kept in full (prompts, answers, commands); a tool's output is cut
at `ai_agents_result_chars` (default 4000) with its full length recorded.
Secrets in any text (API keys, tokens, private keys, passwords in connection
strings) are masked before anything is written.

Never read: credential files (.claude\\.credentials.json, .codex\\auth.json,
.gemini\\oauth_creds.json). Only the paths named here are opened.
"""

import datetime
import glob
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import Dict, Iterable, List, Tuple

from utils.dedupe_insert import Tally, ensure_identity_index, insert_new
try:
    from Artifacts_Collectors.ai_agent_programs import program_of, shell_of_tool
    from Artifacts_Collectors import ai_agent_claude_extras as _extras
    from Artifacts_Collectors import ai_agent_more as _more
except ImportError:                                   # run from Artifacts_Collectors
    from ai_agent_programs import program_of, shell_of_tool
    import ai_agent_claude_extras as _extras
    import ai_agent_more as _more
from utils.time_utils import format_forensic_timestamp, get_current_forensic_timestamp

logger = logging.getLogger(__name__)

DB_NAME = "ai_agents.db"
# This module, handed to the readers in ai_agent_more (no circular import).
_ME = sys.modules[__name__]
CLAUDE_CODE, GEMINI_CLI, CODEX = "Claude Code", "Gemini CLI", "Codex"
RESULT_CHARS_DEFAULT = 4000
# How much of a tool call's result is kept on the call's own row (`output`);
# the whole result, up to ai_agents_result_chars, stays on its `result` row.
OUTPUT_CHARS = 1000
# What this parser derives from a record. A database written by an older
# derivation reads every record once more, so its stored rows gain what is
# derived now (programs per shell, output, approval, origin, exit codes).
DERIVE_VERSION = 3
# How much of the instruction a step answers is kept on the step itself.
INSTRUCTION_CHARS = 300

SESSION_COLUMNS = [
    "agent", "user_name", "session_id", "parent_session_id", "title", "project_path",
    "model", "agent_version", "entrypoint", "git_branch", "approval_mode",
    "first_ts", "last_ts", "prompts", "commands", "file_changes", "tool_calls",
    "source_path", "source_size", "source_modified", "parsed_at",
    # where the agent ran (cli / desktop / desktop-agent-mode / vscode / job),
    # the process that ran it, and the repository and sandbox it worked in
    "app", "pid", "process_start", "git_sha", "git_origin", "sandbox_policy",
    # name: the title the agent recorded, or - when it recorded none - one
    # built from the first request; `title` stays exactly as recorded
    "name"]
STEP_COLUMNS = [
    "agent", "user_name", "session_id", "step_id", "ts", "role", "kind", "tool",
    "command", "target", "cwd", "status", "text", "text_length", "is_sidechain",
    "source_path", "parsed_at",
    # program: what a command started, named as Prefetch/AmCache/SRUM name it
    # (ai_agent_programs); exit_code and duration_ms when the record has them
    "program", "exit_code", "duration_ms",
    # output: the head of a tool call's result, on the call itself; approval:
    # who let the call run; origin: who or what sent a prompt
    "output", "approval", "origin",
    # The order of the work: seq is the step's place in its session (1, 2,
    # 3 ...); turn is which instruction it answers (the session's 1st, 2nd
    # ... prompt); instruction is that prompt's opening words and ordered_by
    # who gave it; session_name names the session on every step.
    "seq", "turn", "instruction", "ordered_by", "session_name"]
STEP_KEY = ["agent", "user_name", "session_id", "step_id"]
# What the AI tools record besides their conversations.
VERSION_COLUMNS = [
    "agent", "user_name", "session_id", "file_path", "version", "saved_at", "size",
    "sha1", "backup_path", "in_case_path", "parsed_at"]
VERSION_KEY = ["agent", "user_name", "session_id", "file_path", "version"]
PROCESS_COLUMNS = [
    "agent", "user_name", "pid", "process_start", "session_id", "cwd", "started_at",
    "kind", "entrypoint", "version", "source_path", "parsed_at"]
PROCESS_KEY = ["agent", "user_name", "pid", "process_start", "session_id"]
SETTING_COLUMNS = [
    "agent", "user_name", "scope", "setting", "value", "source_path", "source_modified",
    "parsed_at"]
SETTING_KEY = ["agent", "user_name", "scope", "setting", "value", "source_path"]
# Step kinds updated on a re-read: what a newer parser derives for a step
# already stored (its program, exit code, duration, or a kind it now knows).
_REFRESHED = ("program", "exit_code", "duration_ms", "kind")

# ---------------------------------------------------------------- secrets
# (kind, pattern, triggers): a pattern runs only when one of its triggers is in
# the text (lower-cased for the case-insensitive ones) - a plain substring test
# in C, where running every pattern over every step was half the parse.
_SECRETS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     ("PRIVATE KEY-----",), False),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), ("sk-ant-",), False),
    ("openai key", re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"), ("sk-",), False),
    ("github token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
     ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"), False),
    ("aws key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), ("AKIA", "ASIA"), False),
    ("google key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), ("AIza",), False),
    ("slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"), ("xox",), False),
    ("cloudflare token", re.compile(r"(?i)(?<=CLOUDFLARE_API_TOKEN=)[^\s'\"]{20,}"),
     ("cloudflare_api_token=",), True),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
     ("eyJ",), False),
    ("bearer token", re.compile(r"(?i)(?<=bearer )[A-Za-z0-9._\-~+/]{20,}=*"), ("bearer ",), True),
    ("password", re.compile(r"(?i)(?<=://)[^\s:/@'\"]+:[^\s@/'\"]+(?=@)"), ("://",), False),
]
# name = value: only the value is masked, so the reader still sees what it was.
_NAMED_SECRET = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)"
    r"[\"']?\s*[:=]\s*[\"']?)(?!\[masked)([^\s\"',;]{6,})")
_NAMED_TRIGGERS = ("pass", "pwd", "secret", "key", "token")


def mask_secrets(text):
    """The text with every secret replaced by [masked: kind]."""
    if not text:
        return text
    s = str(text)
    low = s.lower()
    for kind, rx, triggers, lowered in _SECRETS:
        hay = low if lowered else s
        if any(t in hay for t in triggers):
            s = rx.sub("[masked: %s]" % kind, s)
    if any(t in low for t in _NAMED_TRIGGERS):
        s = _NAMED_SECRET.sub(lambda m: m.group(1) + "[masked: secret]", s)
    return s


# ---------------------------------------------------------------- helpers
def _ts(value) -> str:
    """'YYYY-MM-DD HH:MM:SS' UTC from an ISO string or epoch (s or ms), or ''."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            if v > 1e11:
                v /= 1000.0
            dt = datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc)
        else:
            dt = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        return format_forensic_timestamp(dt)
    except (ValueError, OverflowError, OSError):
        return ""


def _text_of(content) -> str:
    """Plain text from a message content: a string, or a list of text parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                t = part.get("text")
                if t is None and part.get("type") in ("input_text", "output_text"):
                    t = part.get("text")
                if isinstance(t, str):
                    out.append(t)
                elif part.get("type") == "image":
                    out.append("[image]")
        return "\n".join(out)
    if isinstance(content, dict):
        return _text_of(content.get("text") or content.get("content") or content.get("output"))
    return str(content)


def _json(v) -> str:
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(v)


def _cap(text: str, limit: int) -> Tuple[str, int]:
    """(masked text cut at `limit`, full length). limit <= 0 keeps it whole.
    Cut first, with a margin so a secret across the cut is still recognised,
    then masked: masking a tool's whole multi-megabyte output cost minutes."""
    text = text or ""
    n = len(text)
    if limit and limit > 0 and n > limit:
        kept = mask_secrets(text[:limit + 200])[:limit]
        return kept + "\n[... %d more characters not kept]" % (n - limit), n
    return mask_secrets(text), n


def _result_chars() -> int:
    try:
        from config.case_history_manager import read_global_setting
        return int(read_global_setting("ai_agents_result_chars", RESULT_CHARS_DEFAULT))
    except Exception:
        return RESULT_CHARS_DEFAULT


# What each tool is, by name, for all three agents.
_COMMAND_TOOLS = {"bash", "powershell", "run_shell_command", "shell", "local_shell", "exec_command",
                  "shell_command", "exec", "container.exec",
                  "execute_command", "run_in_terminal"}          # Cline family, Copilot
_READ_TOOLS = {"read", "read_file", "read_many_files", "notebookread", "view_image"}
_WRITE_TOOLS = {"write", "write_file", "create_file", "write_to_file", "create"}
_EDIT_TOOLS = {"edit", "multiedit", "notebookedit", "replace", "apply_patch", "edit_file",
               "apply_diff", "replace_in_file", "insert_content", "search_and_replace", "str_replace"}
_SEARCH_TOOLS = {"grep", "glob", "ls", "list_directory", "search_file_content", "glob_files", "find",
                 "list_files", "search_files", "list_code_definition_names", "codebase_search"}
_MCP_TOOLS = {"use_mcp_tool", "access_mcp_resource"}             # Cline family
_WEB_TOOLS = {"webfetch", "websearch", "web_fetch", "google_web_search", "web_search"}
_AGENT_TOOLS = {"agent", "task"}
# Driving a browser or the screen. Claude in Chrome, the built-in browser and
# Playwright/Puppeteer reach the agent as MCP tools named mcp__<server>__<tool>;
# Cline/Roo/Kilo have browser_action; computer use is `computer`.
_BROWSER_SERVERS = ("chrome", "browser", "playwright", "puppeteer")
_BROWSER_TOOLS = {"browser_action", "browser", "navigate", "web_browser"}
_COMPUTER_TOOLS = {"computer", "computer_use", "computer_20250124", "computer_20241022"}


_EXEC_CMD = re.compile(r'exec_command\(\s*\{\s*"cmd"\s*:\s*"((?:[^"\\]|\\.)*)"')


def tool_kind(name: str) -> str:
    n = str(name or "").lower()
    if n in _COMMAND_TOOLS:
        return "command"
    if n in _READ_TOOLS:
        return "file_read"
    if n in _WRITE_TOOLS:
        return "file_write"
    if n in _EDIT_TOOLS:
        return "file_edit"
    if n in _SEARCH_TOOLS:
        return "search"
    if n in _WEB_TOOLS:
        return "web"
    if n in _AGENT_TOOLS:
        return "subagent"
    if n in _COMPUTER_TOOLS:
        return "computer"
    if n in _BROWSER_TOOLS:
        return "browser"
    if n in _MCP_TOOLS:
        return "mcp"
    if n.startswith("mcp__"):
        server = n.split("__")[1] if n.count("__") >= 2 else n[5:]
        # a browser server first: Claude in Chrome's own `computer` tool
        # clicks inside the page, not on the desktop
        if any(b in server for b in _BROWSER_SERVERS):
            return "browser"
        if "computer" in server or n.endswith(("__computer", "__screenshot")):
            return "computer"
        return "mcp"
    return "tool"


def _tool_fields(name: str, args) -> Tuple[str, str, str]:
    """(kind, command, target) of one tool call from its arguments."""
    kind = tool_kind(name)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            args = parsed if isinstance(parsed, dict) else {"input": args}
        except ValueError:
            args = {"input": args}
    if not isinstance(args, dict):
        args = {}
    command = ""
    if kind == "command":
        c = args.get("command") or args.get("cmd") or args.get("input") or ""
        command = " ".join(str(x) for x in c) if isinstance(c, list) else str(c)
        # Codex Desktop's 'exec' tool takes a script that calls
        # tools.exec_command({"cmd": ...}): the commands it ran are those.
        inner = [m.group(1) for m in _EXEC_CMD.finditer(command)]
        if inner:
            try:
                command = "\n".join(json.loads('"%s"' % x) for x in inner)
            except ValueError:
                command = "\n".join(inner)
    target = ""
    for k in ("file_path", "absolute_path", "path", "notebook_path", "url", "query", "pattern",
              "dir_path", "workdir", "description", "prompt", "action", "text", "coordinate"):
        v = args.get(k)
        if isinstance(v, str) and v:
            target = v
            break
    if not target and isinstance(args.get("paths"), list) and args["paths"]:
        target = ", ".join(str(p) for p in args["paths"][:5])
    if kind == "subagent":
        target = str(args.get("description") or args.get("subagent_type") or target)
    return kind, mask_secrets(command), mask_secrets(target[:1000])


_EXIT_LINE = re.compile(r"(?im)^\s*(?:process\s+)?exit(?:ed with)?\s+code:?\s*(-?\d+)")
_WALL_TIME = re.compile(r"(?im)^\s*wall time:?\s*([0-9.]+)\s*(ms|s|seconds?)?")


_LEADING_EXIT = re.compile(r"^\s*(?:Error:\s*)?Exit code:?\s*(-?\d+)\b", re.I)


# Not anchored to a line: inside a JSON string the line breaks are escaped.
_EXIT_ANYWHERE = re.compile(r"(?i)exit code:\s*(-?\d+)")


def _leading_exit(text):
    """The exit code a failed command's result opens with: Claude Code writes
    "Exit code 2" as the first line of a Bash/PowerShell call that failed."""
    m = _LEADING_EXIT.match(str(text or "")[:80])
    return int(m.group(1)) if m else None


def _last_exit(text):
    """The last "Exit Code: N" line anywhere in a result: Gemini CLI writes it
    after the output, with the process group ID."""
    found = _EXIT_ANYWHERE.findall(str(text or ""))
    return int(found[-1]) if found else None


def _exit_in(text):
    """(exit code, duration in ms) a shell tool's output states, or Nones.
    Codex writes "Exit code: 0" and "Wall time: 1.2 seconds"; Gemini CLI
    "Exit Code: 0"."""
    if not text:
        return None, None
    head = str(text)[:600]
    m = _EXIT_LINE.search(head)
    code = int(m.group(1)) if m else None
    w = _WALL_TIME.search(head)
    ms = None
    if w:
        try:
            v = float(w.group(1))
            ms = int(v if (w.group(2) or "").lower() == "ms" else v * 1000)
        except ValueError:
            ms = None
    return code, ms


class _Session:
    def __init__(self, agent, user, session_id, source_path, parent=""):
        self.row = {c: "" for c in SESSION_COLUMNS}
        self.row.update(agent=agent, user_name=user, session_id=session_id,
                        parent_session_id=parent, source_path=source_path,
                        prompts=0, commands=0, file_changes=0, tool_calls=0)
        self.steps: List[dict] = []
        self.seen = set()
        self.by_id: Dict[str, dict] = {}         # step_id -> step, for its result
        self.started: Dict[str, float] = {}      # tool call id -> epoch seconds
        self.background: Dict[str, str] = {}     # background task id -> command step id
        self.versions: List[dict] = []           # files the agent saved a copy of

    def finish(self, call_id, when, exit_code=None):
        """A tool call's result: its duration, and its exit code when known."""
        st = self.by_id.get(call_id)
        if st is None:
            return
        start = self.started.get(call_id)
        if start is not None and when is not None and when >= start:
            st["duration_ms"] = int(round((when - start) * 1000))
        if exit_code is not None:
            st["exit_code"] = exit_code

    def step(self, **kw):
        sid = kw.get("step_id")
        if not sid or sid in self.seen:
            return
        self.seen.add(sid)
        ts = kw.get("ts") or ""
        if ts:
            if not self.row["first_ts"] or ts < self.row["first_ts"]:
                self.row["first_ts"] = ts
            if ts > self.row["last_ts"]:
                self.row["last_ts"] = ts
        kind = kw.get("kind")
        # Counted for the person (prompts typed) and for the agent (what it ran
        # and changed); a sub-agent's instructions and the person's own `!cmd`
        # are kept as steps, not counted.
        role = kw.get("role")
        if kind == "prompt" and role == "user":
            self.row["prompts"] += 1
        elif kind == "command" and role == "assistant":
            self.row["commands"] += 1
        if kind in ("file_write", "file_edit"):
            self.row["file_changes"] += 1
        if kw.get("role") == "assistant" and kind not in ("answer",):
            self.row["tool_calls"] += 1
        base = {c: "" for c in STEP_COLUMNS}
        base.update(agent=self.row["agent"], user_name=self.row["user_name"],
                    session_id=self.row["session_id"], source_path=self.row["source_path"],
                    is_sidechain=0, text_length=0, exit_code=None, duration_ms=None)
        base.update(kw)
        if kind == "command" and not base.get("program"):
            base["program"] = program_of(base.get("command") or "", shell_of_tool(base.get("tool")))
        if kind == "result" and str(sid).endswith(":result"):
            self.result_of(str(sid)[:-len(":result")], base)
        self.steps.append(base)
        self.by_id[sid] = base

    def result_of(self, call_id, result):
        """A tool call's result, written onto the call's own row: whether it
        ran (status), what it answered (the head of the output) and, for a
        command, its exit code when the output states one and the record did
        not."""
        call = self.by_id.get(call_id)
        if call is None:
            return
        out = str(result.get("text") or "")
        call["output"] = out[:OUTPUT_CHARS]
        status = result.get("status") or ""
        if call.get("kind") == "command" and call.get("exit_code") is None:
            code = _leading_exit(out)
            if code is not None:
                call["exit_code"] = code
        if call.get("kind") == "command" and call.get("exit_code") not in (None, 0) and status == "ok":
            status = "error"
        if call.get("status") != "rejected":
            call["status"] = status


# ---------------------------------------------------------------- Claude Code
_BASH_INPUT = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
# Lines the program writes into the conversation as if from the user: the
# notice that a background task ended, reminders, a local command's output.
_INJECTED = ("<task-notification", "<system-reminder", "<local-command-stdout", "<local-command-stderr",
             "<bash-stdout", "<bash-stderr", "<local-command-caveat", "Caveat: The messages below",
             # The summary written when a long session's context is compacted.
             "This session is being continued from a previous conversation",
             "<recommended_plugins")


_CLAUDE_TYPES = {"user", "assistant", "ai-title", "custom-title", "permission-mode",
                 "file-history-snapshot", "file-history-delta"}


def _epoch(value):
    """Epoch seconds from an ISO timestamp or epoch (s or ms), or None."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            return v / 1000.0 if v > 1e11 else v
        dt = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _claude_version(s, rel_path, backup):
    """One saved copy of a file the agent was about to change (file-history).

    `rel_path` is how the record names the file (relative to the profile, or
    absolute); `realParentDir`, when present, is the file's real folder."""
    if not isinstance(backup, dict) or not rel_path:
        return
    parent = backup.get("realParentDir")
    path = os.path.join(parent, os.path.basename(rel_path)) if parent else rel_path
    entry = {"file_path": path, "version": backup.get("version"),
             "saved_at": _ts(backup.get("backupTime")),
             "backup_name": backup.get("backupFileName") or ""}
    key = (entry["file_path"], entry["version"])
    if all((v["file_path"], v["version"]) != key for v in s.versions):
        s.versions.append(entry)


def _claude_origin(j) -> Tuple[str, str]:
    """(origin, role) of a Claude Code user line: who or what sent it.

    Claude Code marks every turn with where it came from (`turnOrigin`,
    `origin`, `promptSource`): the person typing, a scheduled task, another
    agent session, the program continuing on its own. Only a person's turn is
    role 'user'; another session's message is role 'agent', the program's own
    is 'system'. ('', '') when the record does not say (older versions)."""
    o = j.get("origin") if isinstance(j.get("origin"), dict) else {}
    kind = str(o.get("kind") or j.get("turnOrigin") or "").replace("_", "-").lower()
    src = str(j.get("promptSource") or "").replace("_", " ")
    if j.get("scheduledTaskId") or kind == "scheduled":
        task = str(j.get("scheduledTaskId") or "")
        return ("scheduled task %s" % task).strip(), "system"
    if src == "sdk":
        # `claude -p` or the Agent SDK: whatever called it wrote the prompt -
        # a script, an application, or a person at a terminal. Not known to be
        # the person.
        return "a program (claude -p / Agent SDK)", "system"
    if kind == "human":
        return ("person (%s)" % src) if src and src != "system" else "person", "user"
    if kind == "peer":
        who = str(o.get("name") or "")
        frm = str(o.get("from") or o.get("senderTaskId") or "")
        if frm.lower().startswith("uds:"):
            frm = "local pipe " + frm.rsplit("-", 1)[-1][:12]
        label = " ".join(x for x in (who, "(%s)" % frm if frm else "") if x)
        return ("another agent session %s" % label).strip(), "agent"
    if kind == "auto-continuation":
        return "automatic continuation", "system"
    if kind == "task-notification":
        return "background task notice", "system"
    if kind == "system":
        return "system", "system"
    return "", ""


_GRANT = {"once": "once", "session": "for the session", "always": "always"}


def _claude_approval(decision) -> str:
    """Who let a tool call run, from Claude Code's `permissionDecision`:
    the person (once / for the session), a settings rule, the permission
    mode, or the auto-mode classifier - or who refused it."""
    if not isinstance(decision, dict):
        return ""
    verdict = {"accept": "allowed", "reject": "refused", "deny": "refused"}.get(
        str(decision.get("decision") or "").lower(), str(decision.get("decision") or ""))
    src = str(decision.get("source") or "").lower()
    reason = str(decision.get("reasonType") or "").lower()
    if src.startswith("user"):
        grant = _GRANT.get(str(decision.get("grantScope") or "").lower(), "")
        if not grant and src == "user_permanent":
            grant = "always"
        by = "by the person" + (" (%s)" % grant if grant else "")
    elif reason == "classifier":
        by = "by the auto-mode classifier"
    elif reason == "mode":
        by = "by the permission mode"
    elif src == "config":
        by = "by a settings rule"
    else:
        by = ("by " + src) if src else ""
    return " ".join(x for x in (verdict, by) if x)


def _subagent_meta(path) -> dict:
    """A sub-agent's meta file beside its transcript (agent-<id>.meta.json):
    its description, type and the tool call that started it."""
    meta = os.path.splitext(path)[0] + ".meta.json"
    try:
        with open(meta, "r", encoding="utf-8", errors="replace") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def _add_mode(row, mode):
    """Every permission mode a session ran in, in the order first seen."""
    mode = str(mode or "").strip()
    if not mode:
        return
    have = [m.strip() for m in str(row.get("approval_mode") or "").split(",") if m.strip()]
    if mode not in have:
        row["approval_mode"] = ", ".join(have + [mode])


def _claude_user_line(body: str, sidechain: int) -> Tuple[str, str, str]:
    """(role, kind, command) of a Claude Code 'user' line that is not a tool result.

    A sub-agent's 'user' line is the main agent's instruction to it, not the
    person's. `!cmd` typed by the person is <bash-input>: a command the person
    ran, not the agent."""
    head = body.lstrip()
    m = _BASH_INPUT.search(head)
    if m and head.startswith("<bash-input>"):
        return "user", "command", m.group(1).strip()
    if head.startswith(_INJECTED):
        return "system", "notice", ""
    if sidechain:
        return "agent", "prompt", ""
    return "user", "prompt", ""


def _read_claude(path, user, limit) -> List[_Session]:
    sessions: Dict[str, _Session] = {}
    parent = ""
    norm = path.replace("/", "\\")
    if "\\subagents\\" in norm:
        # The session folder just above `subagents` - a workflow's sub-agents
        # sit deeper (subagents\workflows\wf_<id>\agent-<id>.jsonl).
        parts = norm.split("\\")
        cut = len(parts) - 1 - parts[::-1].index("subagents")
        parent = parts[cut - 1] if cut > 0 else ""
    stem = os.path.splitext(os.path.basename(path))[0]
    tool_names = {}
    meta = _subagent_meta(path) if parent else {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # A line that names its type first and is one this reader never
            # uses (api requests, file snapshots, queue state) is not decoded.
            if line.startswith('{"type":"'):
                t = line[9:line.find('"', 9)]
                if t not in _CLAUDE_TYPES:
                    continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if not isinstance(j, dict):
                continue
            typ = j.get("type")
            sid = str(j.get("sessionId") or (parent or stem))
            key = sid + ("/" + stem if parent else "")
            s = sessions.get(key)
            if s is None:
                s = sessions[key] = _Session(CLAUDE_CODE, user, key, path, parent)
                if meta.get("description"):
                    kind_of = str(meta.get("agentType") or "sub-agent")
                    s.row["title"] = ("%s: %s" % (kind_of, meta.get("description")))[:300]
            r = s.row
            if typ == "ai-title" and j.get("aiTitle"):
                r["title"] = str(j.get("aiTitle"))[:300]
            elif typ == "custom-title" and j.get("customTitle"):
                r["title"] = str(j.get("customTitle"))[:300]
            elif typ == "permission-mode" and j.get("permissionMode"):
                _add_mode(r, j.get("permissionMode"))
            elif typ == "file-history-snapshot":
                snap = j.get("snapshot") if isinstance(j.get("snapshot"), dict) else {}
                for rel, backup in (snap.get("trackedFileBackups") or {}).items():
                    _claude_version(s, rel, backup)
            elif typ == "file-history-delta":
                _claude_version(s, j.get("trackingPath"), j.get("backup"))
            if typ not in ("user", "assistant"):
                continue
            for k, col in (("cwd", "project_path"), ("version", "agent_version"),
                           ("entrypoint", "entrypoint"), ("gitBranch", "git_branch")):
                if j.get(k) and not r[col]:
                    r[col] = str(j.get(k))
            ts = _ts(j.get("timestamp"))
            cwd = str(j.get("cwd") or "")
            side = 1 if j.get("isSidechain") else 0
            uuid = str(j.get("uuid") or "")
            msg = j.get("message") or {}
            content = msg.get("content")
            if typ == "assistant":
                model = msg.get("model")
                if model and model != "<synthetic>":
                    r["model"] = str(model)
                if not isinstance(content, list):
                    continue
                for i, item in enumerate(content):
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text" and str(item.get("text") or "").strip():
                        text, n = _cap(item.get("text"), 0)
                        s.step(step_id="%s:%d" % (uuid, i), ts=ts, role="assistant", kind="answer",
                               cwd=cwd, text=text, text_length=n, is_sidechain=side)
                    elif item.get("type") == "tool_use":
                        name = str(item.get("name") or "")
                        tool_names[str(item.get("id"))] = name
                        s.started[str(item.get("id"))] = _epoch(j.get("timestamp"))
                        kind, command, target = _tool_fields(name, item.get("input"))
                        text, n = _cap(_json(item.get("input")), limit)
                        s.step(step_id=str(item.get("id") or "%s:%d" % (uuid, i)), ts=ts,
                               role="assistant", kind=kind, tool=name, command=command,
                               target=target, cwd=cwd, text=text, text_length=n, is_sidechain=side)
                continue
            # user line: a typed prompt, or the results of tool calls
            _add_mode(r, j.get("permissionMode"))
            origin, origin_role = _claude_origin(j)
            if j.get("isMeta"):
                # Hidden from the transcript view, but some of these are what
                # set the agent working with no person typing: a scheduled
                # task, another agent session's message, the program resuming
                # on its own. Those are kept, as prompts not from the person;
                # the rest (skill text, caveats) is not a request.
                if origin_role in ("system", "agent") and origin not in ("system", "background task notice"):
                    body = _text_of(content)
                    if body.strip():
                        text, n = _cap(body, 0)
                        s.step(step_id=uuid or "%s:%s" % (key, ts), ts=ts, role=origin_role,
                               kind="prompt", cwd=cwd, text=mask_secrets(text), text_length=n,
                               is_sidechain=side, origin=origin)
                continue
            if j.get("isCompactSummary"):
                text, n = _cap(_text_of(content), limit)
                s.step(step_id=uuid or "%s:%s" % (key, ts), ts=ts, role="system", kind="notice",
                       cwd=cwd, text=text, text_length=n, is_sidechain=side)
                continue
            if isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result"
                                                 for x in content):
                tur = j.get("toolUseResult") if isinstance(j.get("toolUseResult"), dict) else {}
                when = _epoch(j.get("timestamp"))
                approval = _claude_approval(j.get("permissionDecision"))
                refused = approval.startswith("refused")
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "tool_result":
                        continue
                    tid = str(item.get("tool_use_id") or "")
                    if tur.get("backgroundTaskId"):
                        # Sent to the background: the result is only "started";
                        # its exit code is in the task's output file.
                        s.background[str(tur.get("backgroundTaskId"))] = tid
                    else:
                        s.finish(tid, when)
                    status = "rejected" if refused else "error" if item.get("is_error") else (
                        "interrupted" if tur.get("interrupted") else "ok")
                    call = s.by_id.get(tid)
                    if call is not None and approval:
                        call["approval"] = approval
                        if refused:
                            call["status"] = "rejected"
                    text, n = _cap(_text_of(item.get("content")), limit)
                    s.step(step_id=tid + ":result", ts=ts, role="tool", kind="result",
                           tool=tool_names.get(tid, ""), cwd=cwd, status=status, text=text,
                           text_length=n, is_sidechain=side)
                continue
            body = _text_of(content)
            if not body.strip():
                continue
            role, kind, command = _claude_user_line(body, side)
            if kind == "prompt" and origin_role in ("system", "agent") and not side:
                # Sent by a scheduled task or another session, not typed.
                role = origin_role
            text, n = _cap(body, 0 if kind in ("prompt", "command") else limit)
            s.step(step_id=uuid or "%s:%s" % (key, ts), ts=ts, role=role, kind=kind,
                   command=mask_secrets(command), cwd=cwd, text=text, text_length=n,
                   is_sidechain=side, origin=origin if kind in ("prompt", "command") else "")
    return [s for s in sessions.values() if s.steps]


# ---------------------------------------------------------------- Gemini CLI
def _read_gemini(path, user, limit) -> List[_Session]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        try:
            j = json.load(f)
        except ValueError:
            return []
    if not isinstance(j, dict):
        return []
    sid = str(j.get("sessionId") or os.path.splitext(os.path.basename(path))[0])
    s = _Session(GEMINI_CLI, user, sid, path)
    s.row["project_path"] = "project " + str(j.get("projectHash") or "")[:16]
    for idx, m in enumerate(j.get("messages") or []):
        if not isinstance(m, dict):
            continue
        ts = _ts(m.get("timestamp"))
        mid = str(m.get("id") or idx)
        if m.get("model"):
            s.row["model"] = str(m.get("model"))
        typ = m.get("type")
        body = _text_of(m.get("content"))
        if typ == "user" and body.strip():
            text, n = _cap(body, 0)
            s.step(step_id=mid, ts=ts, role="user", kind="prompt", text=text, text_length=n)
        elif typ == "gemini":
            if body.strip():
                text, n = _cap(body, 0)
                s.step(step_id=mid + ":text", ts=ts, role="assistant", kind="answer",
                       text=text, text_length=n)
            for k, call in enumerate(m.get("toolCalls") or []):
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name") or "")
                cid = str(call.get("id") or "%s:%d" % (mid, k))
                cts = _ts(call.get("timestamp")) or ts
                kind, command, target = _tool_fields(name, call.get("args"))
                text, n = _cap(_json(call.get("args")), limit)
                s.step(step_id=cid, ts=cts, role="assistant", kind=kind, tool=name,
                       command=command, target=target, text=text, text_length=n)
                if call.get("result") is not None:
                    out = call.get("resultDisplay") if isinstance(call.get("resultDisplay"), str) \
                        else _json(call.get("result"))
                    if kind == "command":
                        # "Exit Code: N" follows the output in the function
                        # response, however long the output is.
                        code = _last_exit(_json(call.get("result")))
                        if code is None:
                            code, _ms = _exit_in(out)
                        if code is not None and cid in s.by_id:
                            s.by_id[cid]["exit_code"] = code
                    rtext, rn = _cap(out, limit)
                    st = str(call.get("status") or "")
                    s.step(step_id=cid + ":result", ts=cts, role="tool", kind="result", tool=name,
                           status="error" if st in ("error", "cancelled") else (
                               "ok" if st in ("", "success") else st),
                           text=rtext, text_length=rn)
    return [s] if s.steps else []


# ---------------------------------------------------------------- Codex
def _codex_lines(path) -> Iterable[str]:
    if path.lower().endswith(".zst"):
        try:
            import zstandard
        except ImportError:
            logger.warning("AI agents: zstandard is not installed; %s not read", path)
            return []
        with open(path, "rb") as f:
            data = zstandard.ZstdDecompressor().stream_reader(f).read()
        return data.decode("utf-8", "replace").splitlines()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


_CODEX_INJECTED = ("<environment_context>", "<user_instructions>", "<permissions instructions>",
                   "# AGENTS.md", "<INSTRUCTIONS>", "<recommended_plugins")


def _read_codex(path, user, limit, titles) -> List[_Session]:
    s = None
    names = {}
    cwd = ""
    for i, line in enumerate(_codex_lines(path)):
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if not isinstance(j, dict):
            continue
        typ = j.get("type")
        pl = j.get("payload") if isinstance(j.get("payload"), dict) else {}
        ts = _ts(j.get("timestamp"))
        if typ == "session_meta":
            sid = str(pl.get("id") or pl.get("session_id") or "")
            s = _Session(CODEX, user, sid, path)
            cwd = str(pl.get("cwd") or "")
            s.row.update(project_path=cwd, agent_version=str(pl.get("cli_version") or ""),
                         entrypoint=" ".join(x for x in (str(pl.get("originator") or ""),
                                                         str(pl.get("source") or "")) if x),
                         title=titles.get(sid, ""))
            continue
        if s is None:
            stem = os.path.basename(path).split(".")[0]
            s = _Session(CODEX, user, stem, path)
        if typ == "turn_context":
            cwd = str(pl.get("cwd") or cwd)
            if pl.get("model"):
                s.row["model"] = str(pl.get("model"))
            if pl.get("approval_policy"):
                sb = pl.get("sandbox_policy")
                sb = sb.get("type", "") if isinstance(sb, dict) else str(sb or "")
                s.row["approval_mode"] = str(pl.get("approval_policy")) + (" / sandbox " + sb if sb else "")
            continue
        if typ != "response_item":
            continue
        ptype = pl.get("type")
        pid = str(pl.get("id") or pl.get("call_id") or "line%d" % i)
        if ptype == "message":
            role = pl.get("role")
            body = _text_of(pl.get("content"))
            if not body.strip() or role not in ("user", "assistant"):
                continue
            if role == "user" and body.lstrip().startswith(_CODEX_INJECTED):
                continue
            text, n = _cap(body, 0)
            s.step(step_id=pid, ts=ts, role=role, kind="prompt" if role == "user" else "answer",
                   cwd=cwd, text=text, text_length=n)
        elif ptype in ("function_call", "custom_tool_call", "local_shell_call"):
            name = str(pl.get("name") or ("local_shell" if ptype == "local_shell_call" else ""))
            args = pl.get("arguments") if ptype == "function_call" else (
                pl.get("input") if ptype == "custom_tool_call" else pl.get("action"))
            names[str(pl.get("call_id") or pid)] = name
            kind, command, target = _tool_fields(name, args)
            text, n = _cap(args if isinstance(args, str) else _json(args), limit)
            s.step(step_id=str(pl.get("call_id") or pid), ts=ts, role="assistant", kind=kind,
                   tool=name, command=command, target=target, cwd=cwd, text=text, text_length=n)
        elif ptype in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            cid = str(pl.get("call_id") or pid)
            out = pl.get("output")
            if isinstance(out, (list, dict)):
                out = _text_of(out) or _json(out)
            code, ms = _exit_in(out)
            if code is None and isinstance(out, str) and out.lstrip().startswith("{"):
                # older Codex: {"output": ..., "metadata": {"exit_code", "duration_seconds"}}
                try:
                    meta = (json.loads(out).get("metadata") or {})
                    code = meta.get("exit_code") if isinstance(meta.get("exit_code"), int) else None
                    if isinstance(meta.get("duration_seconds"), (int, float)):
                        ms = int(meta["duration_seconds"] * 1000)
                except (ValueError, AttributeError):
                    pass
            step = s.by_id.get(cid)
            if step is not None and step.get("kind") == "command":
                if code is not None:
                    step["exit_code"] = code
                if ms is not None:
                    step["duration_ms"] = ms
            text, n = _cap(str(out or ""), limit)
            failed = isinstance(out, str) and out.lstrip().lower().startswith(("script failed", "error:"))
            s.step(step_id=cid + ":result", ts=ts, role="tool", kind="result",
                   tool=names.get(cid, ""), cwd=cwd, status="error" if failed else "ok",
                   text=text, text_length=n)
    return [s] if s is not None and s.steps else []


def _codex_titles(codex_dir) -> Dict[str, str]:
    """Session id -> title from Codex's state database (a copy, read-only)."""
    src = os.path.join(codex_dir, "state_5.sqlite")
    if not os.path.isfile(src):
        cands = sorted(glob.glob(os.path.join(codex_dir, "state_*.sqlite")))
        if not cands:
            return {}
        src = cands[-1]
    tmp = tempfile.mkdtemp(prefix="crow_codex_")
    try:
        dst = os.path.join(tmp, os.path.basename(src))
        for suffix in ("", "-wal", "-shm"):
            if os.path.isfile(src + suffix):
                shutil.copy2(src + suffix, dst + suffix)
        conn = sqlite3.connect(dst)
        try:
            return {str(i): str(t or "")[:300] for i, t in conn.execute("SELECT id, title FROM threads")}
        finally:
            conn.close()
    except Exception as e:
        logger.debug("AI agents: Codex titles not read: %s", e)
        return {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- sources
def profile_sources(profile_dir) -> List[Tuple[str, str]]:
    """[(agent, file)] for one user profile folder. Only these paths are opened."""
    out = []
    claude = os.path.join(profile_dir, ".claude", "projects")
    if os.path.isdir(claude):
        for p in glob.glob(os.path.join(claude, "**", "*.jsonl"), recursive=True):
            out.append((CLAUDE_CODE, p))
    gemini = os.path.join(profile_dir, ".gemini", "tmp")
    if os.path.isdir(gemini):
        for p in glob.glob(os.path.join(gemini, "*", "chats", "session-*.json")):
            out.append((GEMINI_CLI, p))
    codex = os.path.join(profile_dir, ".codex")
    for sub in ("sessions", "archived_sessions"):
        d = os.path.join(codex, sub)
        if os.path.isdir(d):
            for p in glob.glob(os.path.join(d, "**", "rollout-*.jsonl*"), recursive=True):
                if p.lower().endswith((".jsonl", ".jsonl.zst")):
                    out.append((CODEX, p))
    # Claude desktop agent mode, Roo/Kilo/Cline, Copilot CLI, Antigravity
    out.extend(_more.file_sources(profile_dir, sys.modules[__name__]))
    return sorted(out, key=lambda x: x[1])


# ---------------------------------------------------------------- database
def _open(db_path):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_agent_sessions (
        agent TEXT, user_name TEXT, session_id TEXT, parent_session_id TEXT, title TEXT,
        project_path TEXT, model TEXT, agent_version TEXT, entrypoint TEXT, git_branch TEXT,
        approval_mode TEXT, first_ts TEXT, last_ts TEXT, prompts INTEGER, commands INTEGER,
        file_changes INTEGER, tool_calls INTEGER, source_path TEXT, source_size INTEGER,
        source_modified TEXT, parsed_at TEXT)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_agent_sessions
        ON ai_agent_sessions (agent, user_name, session_id, source_path)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_agent_steps (
        agent TEXT, user_name TEXT, session_id TEXT, step_id TEXT, ts TEXT, role TEXT,
        kind TEXT, tool TEXT, command TEXT, target TEXT, cwd TEXT, status TEXT, text TEXT,
        text_length INTEGER, is_sidechain INTEGER, source_path TEXT, parsed_at TEXT)""")
    ensure_identity_index(conn, "ai_agent_steps", STEP_KEY)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_steps_ts ON ai_agent_steps (ts)")
    # Columns added after the first release. One statement each, written out:
    # Sentinel's extract-schema reads ALTER TABLE ... ADD COLUMN from this file,
    # and a loop over (name, type) pairs reads to it as tables (CLAUDE.md).
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_sessions)")}
    if "app" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN app TEXT")
    if "pid" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN pid INTEGER")
    if "process_start" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN process_start TEXT")
    if "git_sha" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN git_sha TEXT")
    if "git_origin" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN git_origin TEXT")
    if "sandbox_policy" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN sandbox_policy TEXT")
    if "name" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN name TEXT")
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_steps)")}
    if "program" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN program TEXT")
    if "exit_code" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN exit_code INTEGER")
    if "duration_ms" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN duration_ms INTEGER")
    if "output" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN output TEXT")
    if "approval" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN approval TEXT")
    if "origin" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN origin TEXT")
    if "seq" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN seq INTEGER")
    if "turn" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN turn INTEGER")
    if "instruction" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN instruction TEXT")
    if "ordered_by" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN ordered_by TEXT")
    if "session_name" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN session_name TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_steps_program ON ai_agent_steps (program)")
    # The acts (prompts, commands, file changes, browser) by time, covering the
    # AI dashboard's and the timeline's filters: without it every strip and
    # total read the whole table, text included (11 s -> 0.05 s on 287k steps).
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_steps_acts "
                 "ON ai_agent_steps (kind, role, ts, agent, user_name, session_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_agent_file_versions (
        agent TEXT, user_name TEXT, session_id TEXT, file_path TEXT, version INTEGER,
        saved_at TEXT, size INTEGER, sha1 TEXT, backup_path TEXT, in_case_path TEXT,
        parsed_at TEXT)""")
    ensure_identity_index(conn, "ai_agent_file_versions", VERSION_KEY)
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_agent_processes (
        agent TEXT, user_name TEXT, pid INTEGER, process_start TEXT, session_id TEXT,
        cwd TEXT, started_at TEXT, kind TEXT, entrypoint TEXT, version TEXT,
        source_path TEXT, parsed_at TEXT)""")
    ensure_identity_index(conn, "ai_agent_processes", PROCESS_KEY)
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_agent_settings (
        agent TEXT, user_name TEXT, scope TEXT, setting TEXT, value TEXT,
        source_path TEXT, source_modified TEXT, parsed_at TEXT)""")
    ensure_identity_index(conn, "ai_agent_settings", SETTING_KEY)
    # The profile owner's SID (user_sid), filled after the parse from this
    # machine's ProfileList or the case's own SOFTWARE hive (_fill_sids). Not
    # part of any row's identity: a profile read once without a SOFTWARE hive
    # and once with one is the same rows. One ALTER per table, written out
    # (Sentinel's extract-schema reads them; a loop reads as tables).
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_sessions)")}
    if "user_sid" not in have:
        conn.execute("ALTER TABLE ai_agent_sessions ADD COLUMN user_sid TEXT")
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_steps)")}
    if "user_sid" not in have:
        conn.execute("ALTER TABLE ai_agent_steps ADD COLUMN user_sid TEXT")
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_file_versions)")}
    if "user_sid" not in have:
        conn.execute("ALTER TABLE ai_agent_file_versions ADD COLUMN user_sid TEXT")
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_processes)")}
    if "user_sid" not in have:
        conn.execute("ALTER TABLE ai_agent_processes ADD COLUMN user_sid TEXT")
    have = {r[1] for r in conn.execute("PRAGMA table_info(ai_agent_settings)")}
    if "user_sid" not in have:
        conn.execute("ALTER TABLE ai_agent_settings ADD COLUMN user_sid TEXT")
    return conn


def _unchanged(conn, path, size, modified) -> bool:
    row = conn.execute("SELECT 1 FROM ai_agent_sessions WHERE source_path = ? AND source_size IS ? "
                       "AND source_modified IS ? LIMIT 1", (path, size, modified)).fetchone()
    return row is not None


def app_of(agent, entrypoint, source_path) -> str:
    """Where the agent ran: cli, desktop, desktop-agent-mode, vscode or job."""
    src = str(source_path or "").replace("/", "\\").lower()
    ep = str(entrypoint or "").lower()
    if "\\local-agent-mode-sessions\\" in src:
        return "desktop-agent-mode"
    if "\\.claude\\jobs\\" in src or ep == "job":
        return "job"
    if "\\globalstorage\\" in src or "\\workspacestorage\\" in src or "vscode" in ep:
        return "vscode"
    if "desktop" in ep or "\\roaming\\claude\\" in src:
        return "desktop"
    return "cli"


def _refresh_steps(conn, steps):
    """What this parser derives for a step already stored by an older one -
    its program, exit code, duration, status, output, who allowed it, who sent
    it, its role, or a kind it now tells apart - written onto that row.
    insert_new leaves an existing row alone. The evidence columns (time, text,
    command, target) are never rewritten."""
    rows = [(st.get("program") or None, st.get("exit_code"), st.get("duration_ms"), st.get("kind"),
             st.get("status") or "", st.get("output") or "", st.get("approval") or "",
             st.get("origin") or "", st.get("role") or "",
             st.get("seq"), st.get("turn"), st.get("instruction") or "", st.get("ordered_by") or "",
             st.get("session_name") or "",
             st["agent"], st["user_name"], st["session_id"], st["step_id"]) for st in steps]
    if rows:
        conn.executemany(
            "UPDATE ai_agent_steps SET program = ?, exit_code = ?, duration_ms = ?, kind = ?, "
            "status = ?, output = ?, approval = ?, origin = ?, role = ?, "
            "seq = ?, turn = ?, instruction = ?, ordered_by = ?, session_name = ? "
            "WHERE agent = ? AND user_name = ? AND session_id = ? AND step_id = ?", rows)


def _flat(text, limit):
    """`text` on one line, cut to `limit` characters."""
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[:limit - 3] + "..."


def _session_name(s) -> str:
    """What to call a session: the title the agent recorded, else its first
    request (the person's, or the instruction a sub-agent was given), else
    the agent and the start of its id."""
    r = s.row
    title = str(r.get("title") or "").strip()
    # A wholly bracketed title is the parser's note ("[chat file not found
    # ...]"), not a name the agent gave the session; "[@Linear](plugin...)
    # Summarize ..." is a real title.
    note = title.startswith("[") and title.endswith("]") and "](" not in title
    if title and not note:
        return _flat(title, 160)
    prompts = [st for st in s.steps if st.get("kind") == "prompt" and str(st.get("text") or "").strip()]
    # The person's own words first, and not text a program injected
    # ("<command-name>", "<recommended_plugins>" ...).
    prompts.sort(key=lambda st: (st.get("role") != "user", str(st.get("text") or "").lstrip().startswith("<")))
    first = prompts[0] if prompts else None
    if first is not None:
        return "first request: " + _flat(first.get("text"), 120)
    return "%s session %s" % (r.get("agent") or "agent", str(r.get("session_id") or "")[:8])


def _ordered_by(st, parent_name) -> str:
    """Who gave the instruction `st` (a prompt) - for the steps that answer it."""
    if st.get("origin"):
        return str(st["origin"])
    role = st.get("role")
    if role == "user":
        return "person"
    if role == "agent":
        return ("the main agent of session '%s'" % parent_name) if parent_name else "the main agent"
    if role == "system":
        return "the program (not the person)"
    return ""


def _order(s, parent_name=""):
    """Number the session's steps in the order the record holds them (time,
    then the record's own order) and give each the instruction it answers:
    a prompt opens a turn, and every step up to the next prompt is that
    turn's work. Steps before any prompt are turn 0 (what the agent did on
    its own, e.g. after a resumed session's notice)."""
    name = _session_name(s)
    s.row["name"] = name
    last_ts = ""
    keyed = []
    for i, st in enumerate(s.steps):
        last_ts = st.get("ts") or last_ts
        keyed.append((last_ts, i, st))
    keyed.sort(key=lambda k: (k[0], k[1]))
    turn, instruction, by = 0, "", ""
    for n, (_t, _i, st) in enumerate(keyed, 1):
        st["seq"] = n
        if st.get("kind") == "prompt":
            turn += 1
            instruction = _flat(st.get("text"), INSTRUCTION_CHARS)
            by = _ordered_by(st, parent_name)
            st["instruction"] = ""
        else:
            st["instruction"] = instruction
        st["turn"] = turn
        st["ordered_by"] = by
        st["session_name"] = name


def _parent_name(conn, s) -> str:
    """A sub-agent's parent session's name, when the parent is stored."""
    parent = s.row.get("parent_session_id")
    if not parent:
        return ""
    row = conn.execute("SELECT name, title FROM ai_agent_sessions WHERE agent = ? AND user_name = ? "
                       "AND session_id = ? LIMIT 1", (s.row["agent"], s.row["user_name"], parent)).fetchone()
    return (row[0] or row[1] or "") if row else ""


SID_TABLES = ("ai_agent_sessions", "ai_agent_steps", "ai_agent_file_versions",
              "ai_agent_processes", "ai_agent_settings")


def sid_map_from_profile_list(profiles) -> Dict[str, str]:
    """``{profile folder name (lower-case): SID}`` from a ProfileList
    (``{sid: ProfileImagePath}``). Only profiles under a Users (or Documents
    and Settings) folder; ``<SID>.bak`` is the same account; a folder two
    SIDs claim is left out rather than guessed (the offline Browser rule)."""
    out, conflicts = {}, set()
    for raw_sid, path in (profiles or {}).items():
        sid = raw_sid[:-4] if str(raw_sid).lower().endswith(".bak") else str(raw_sid)
        low = str(path or "").replace("/", "\\").lower()
        if "\\users\\" not in low and "\\documents and settings\\" not in low:
            continue
        folder = low.rstrip("\\").rsplit("\\", 1)[-1]
        if not folder:
            continue
        if folder in out and out[folder] != sid:
            conflicts.add(folder)
        out.setdefault(folder, sid)
    for folder in conflicts:
        out.pop(folder, None)
    return out


def _fill_sids(conn, sid_map) -> int:
    """Each row's user_sid from its profile folder (user_name), where empty.
    A row whose folder no ProfileList names keeps it empty - never guessed."""
    if not sid_map:
        return 0
    filled = 0
    pairs = [(sid, folder) for folder, sid in sid_map.items() if folder and sid]
    for table in SID_TABLES:
        before = conn.total_changes
        conn.executemany("UPDATE %s SET user_sid = ? WHERE lower(user_name) = ? "
                         "AND COALESCE(user_sid, '') = ''" % table, pairs)
        filled += conn.total_changes - before
    return filled


def _name_and_link(conn):
    """After every record is stored: a name for the sessions stored outside
    `_store` (prompts kept from a deleted transcript, jobs, other agents'
    stores), each step's `session_name`, and a sub-agent's order linked to
    its parent session by name - the parent may be read after the sub-agent."""
    conn.execute(
        "UPDATE ai_agent_sessions SET name = CASE WHEN COALESCE(title, '') <> '' AND NOT (title LIKE '[%]' AND title NOT LIKE '%](%') "
        "THEN title ELSE COALESCE("
        "(SELECT 'first request: ' || substr(trim(replace(replace(st.text, char(13), ' '), char(10), ' ')), 1, 120) "
        " FROM ai_agent_steps st WHERE st.agent = ai_agent_sessions.agent AND st.user_name = "
        " ai_agent_sessions.user_name AND st.session_id = ai_agent_sessions.session_id AND st.kind = 'prompt' "
        " AND COALESCE(st.text, '') <> '' ORDER BY (st.role <> 'user'), (substr(ltrim(st.text), 1, 1) = '<'), "
        " st.ts LIMIT 1), "
        "agent || ' session ' || substr(session_id, 1, 8)) END WHERE COALESCE(name, '') = '' OR (name LIKE '[%]' AND name NOT LIKE '%](%') "
        "OR name LIKE 'first request: <%'")
    conn.execute(
        "UPDATE ai_agent_steps SET session_name = (SELECT s.name FROM ai_agent_sessions s WHERE "
        "s.agent = ai_agent_steps.agent AND s.user_name = ai_agent_steps.user_name AND "
        "s.session_id = ai_agent_steps.session_id ORDER BY s.last_ts DESC LIMIT 1) "
        "WHERE COALESCE(session_name, '') = '' OR (session_name LIKE '[%]' AND session_name NOT LIKE '%](%') "
        "OR session_name LIKE 'first request: <%'")
    parents = conn.execute(
        "SELECT c.agent, c.user_name, c.session_id, p.name FROM ai_agent_sessions c JOIN ai_agent_sessions p "
        "ON p.agent = c.agent AND p.user_name = c.user_name AND p.session_id = c.parent_session_id "
        "WHERE COALESCE(c.parent_session_id, '') <> '' AND COALESCE(p.name, '') <> ''").fetchall()
    conn.executemany(
        "UPDATE ai_agent_steps SET ordered_by = ? WHERE agent = ? AND user_name = ? AND session_id = ? "
        "AND ordered_by = 'the main agent'",
        [("the main agent of session '%s'" % name, agent, user, sid) for agent, user, sid, name in parents])


def _store(conn, sessions: List[_Session], size, modified, parsed_at, tally):
    for s in sessions:
        if not s.row.get("app"):
            s.row["app"] = app_of(s.row["agent"], s.row.get("entrypoint"), s.row["source_path"])
        _order(s, _parent_name(conn, s))
        r = dict(s.row, source_size=size, source_modified=modified, parsed_at=parsed_at)
        vals = [r[c] for c in SESSION_COLUMNS]
        upd = ", ".join("%s = excluded.%s" % (c, c) for c in SESSION_COLUMNS
                        if c not in ("agent", "user_name", "session_id", "source_path"))
        before = conn.total_changes
        existed = conn.execute(
            "SELECT 1 FROM ai_agent_sessions WHERE agent = ? AND user_name = ? AND session_id = ? "
            "AND source_path = ?", (r["agent"], r["user_name"], r["session_id"], r["source_path"])).fetchone()
        conn.execute("INSERT INTO ai_agent_sessions (%s) VALUES (%s) ON CONFLICT "
                     "(agent, user_name, session_id, source_path) DO UPDATE SET %s"
                     % (", ".join(SESSION_COLUMNS), ", ".join("?" for _ in SESSION_COLUMNS), upd), vals)
        tally.add("ai_agent_sessions", 1, 0 if existed else conn.total_changes - before)
        rows = [[st.get(c, "") if c != "parsed_at" else parsed_at for c in STEP_COLUMNS] for st in s.steps]
        insert_new(conn, "ai_agent_steps", STEP_COLUMNS, rows, key_cols=STEP_KEY, tally=tally,
                   fast_if_empty=True)
        _refresh_steps(conn, s.steps)


def _copy_versions_setting() -> bool:
    """Copy every saved file version into the case at parse time (off by default)."""
    try:
        from config.case_history_manager import read_global_setting
        return bool(read_global_setting("ai_agents_copy_file_versions", False))
    except Exception:
        return False


def save_versions_into_case(db_path, rowids=None, keys=None) -> Tuple[int, int]:
    """Copy saved file versions into the case: <case>\\AI_Agents\\file_versions\\
    <agent>\\<session>\\<version>_<name>, each verified by SHA-1 after the copy,
    and record where in `in_case_path`. `rowids`, or `keys` (records holding the
    VERSION_KEY columns, as a table's selected rows do), pick versions; neither
    means every version not yet in the case. Returns (copied, failed)."""
    case_root = os.path.dirname(os.path.dirname(os.path.abspath(db_path)))
    conn = sqlite3.connect(db_path)
    copied = failed = 0
    if keys:
        where = " AND ".join("%s IS ?" % k for k in VERSION_KEY)
        rowids = [r[0] for k in keys for r in conn.execute(
            "SELECT rowid FROM ai_agent_file_versions WHERE " + where, [k.get(c) for c in VERSION_KEY])]
    try:
        sql = ("SELECT rowid, agent, session_id, file_path, version, sha1, backup_path "
               "FROM ai_agent_file_versions WHERE backup_path != '' AND "
               "(in_case_path IS NULL OR in_case_path = '')")
        rows = conn.execute(sql).fetchall()
        if rowids is not None:
            wanted = {int(r) for r in rowids}
            rows = [r for r in rows if r[0] in wanted]
        for rid, agent, session, fpath, version, sha1, backup in rows:
            safe = lambda x: re.sub(r'[<>:"/\\|?*]+', "_", str(x or ""))[:120]
            dest_dir = os.path.join(case_root, "AI_Agents", "file_versions", safe(agent),
                                    safe(str(session).split("/")[0]))
            dest = os.path.join(dest_dir, "v%s_%s" % (version, safe(os.path.basename(fpath or backup))))
            try:
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(backup, dest)
                if sha1 and _extras.sha1_of(dest) != sha1:
                    os.remove(dest)
                    failed += 1
                    continue
                conn.execute("UPDATE ai_agent_file_versions SET in_case_path = ? WHERE rowid = ?",
                             (dest, rid))
                copied += 1
            except OSError as e:
                logger.warning("AI agents: version %s not copied: %s", backup, e)
                failed += 1
        conn.commit()
    finally:
        conn.close()
    return copied, failed


def _store_rows(conn, table, columns, key, rows, parsed_at, tally):
    vals = [[(r.get(c) if c != "parsed_at" else parsed_at) for c in columns] for r in rows]
    if vals:
        insert_new(conn, table, columns, vals, key_cols=key, tally=tally)


def _claude_profile_extras(conn, profile, user, sessions, limit, parsed_at, tally):
    """Everything Claude Code keeps besides the session files, for one profile.

    `sessions` are the Claude Code sessions read in this parse (their saved
    file versions come from their records)."""
    # saved copies of edited files
    known = dict(conn.execute("SELECT backup_path, sha1 FROM ai_agent_file_versions "
                              "WHERE sha1 != ''").fetchall())
    for s in sessions:
        if s.versions:
            _store_rows(conn, "ai_agent_file_versions", VERSION_COLUMNS, VERSION_KEY,
                        _extras.file_versions(profile, CLAUDE_CODE, user, s.row["session_id"],
                                              s.versions, known), parsed_at, tally)
    # processes, and each session's PID
    procs = _extras.processes(profile, CLAUDE_CODE, user)
    _store_rows(conn, "ai_agent_processes", PROCESS_COLUMNS, PROCESS_KEY, procs, parsed_at, tally)
    conn.executemany(
        "UPDATE ai_agent_sessions SET pid = ?, process_start = ? WHERE agent = ? AND user_name = ? "
        "AND session_id = ?", [(p["pid"], p["process_start"], CLAUDE_CODE, user, p["session_id"])
                               for p in procs if p["session_id"]])
    # todos, plans, jobs, and prompts whose transcript is gone
    steps = []
    for session_id, todo, path in _extras.todos(profile):
        text, n = _cap(str(todo.get("description") or ""), limit)
        steps.append(_loose_step(CLAUDE_CODE, user, session_id, "todo:%s" % todo.get("id"),
                                 _extras.mtime_ts(path), "assistant", "todo", path,
                                 target=mask_secrets(str(todo.get("subject") or ""))[:1000],
                                 status=str(todo.get("status") or ""), text=text, text_length=n))
    for path, body, when in _extras.plans(profile):
        text, n = _cap(body, limit)
        steps.append(_loose_step(CLAUDE_CODE, user, "", "plan:%s" % os.path.basename(path), when,
                                 "assistant", "plan", path, target=path, text=text, text_length=n))
    known_sessions = {r[0] for r in conn.execute(
        "SELECT DISTINCT session_id FROM ai_agent_sessions WHERE agent = ? AND user_name = ?",
        (CLAUDE_CODE, user))}
    orphans: Dict[str, _Session] = {}
    for h in _extras.history(profile):
        sid = str(h.get("sessionId") or "")
        if not sid or sid in known_sessions:
            continue
        s = orphans.get(sid)
        if s is None:
            s = orphans[sid] = _Session(CLAUDE_CODE, user, sid, h["_source"])
            s.row.update(project_path=str(h.get("project") or ""),
                         title="[transcript not found: prompts from history.jsonl]")
        text, n = _cap(str(h.get("display") or ""), 0)
        s.step(step_id="history:%s" % h.get("timestamp"), ts=_ts(h.get("timestamp")), role="user",
               kind="prompt", cwd=str(h.get("project") or ""), text=text, text_length=n)
    for job_id, state, timeline, path in _extras.jobs(profile):
        s = _Session(CLAUDE_CODE, user, "job:" + job_id, path)
        s.row.update(title=mask_secrets(str(state.get("name") or state.get("intent")
                                            or state.get("detail") or ""))[:300],
                     project_path=str(state.get("cwd") or ""), entrypoint="job", app="job",
                     agent_version=str(state.get("cliVersion") or ""))
        for k, e in enumerate(timeline):
            text, n = _cap(" ".join(str(e.get(x) or "") for x in ("detail", "text")).strip(), limit)
            s.step(step_id="job:%d" % k, ts=_ts(e.get("at")), role="system", kind="job",
                   status=str(e.get("state") or ""), text=text, text_length=n)
        if not s.steps:
            s.step(step_id="job:state", ts=_extras.mtime_ts(path), role="system", kind="job",
                   status=str(state.get("state") or ""))
        orphans[s.row["session_id"]] = s
    for s in orphans.values():
        st = os.stat(s.row["source_path"]) if os.path.exists(s.row["source_path"]) else None
        _store(conn, [s], st.st_size if st else None, _extras.mtime_ts(s.row["source_path"]),
               parsed_at, tally)
    _store_rows(conn, "ai_agent_steps", STEP_COLUMNS, STEP_KEY, steps, parsed_at, tally)
    # what it was allowed and set up to do
    projects = [r[0] for r in conn.execute(
        "SELECT DISTINCT project_path FROM ai_agent_sessions WHERE agent = ? AND user_name = ? "
        "AND project_path != ''", (CLAUDE_CODE, user))]
    # A project's own .claude settings only when the project folder is inside
    # the profile being read. A transcript names the project by its path on the
    # machine it came from; on an offline case that path is the analyst's own
    # disk, and reading it would put this machine's settings into the evidence.
    home = os.path.normcase(os.path.abspath(profile)) + os.sep
    inside = [p for p in projects
              if os.path.normcase(os.path.abspath(p)).startswith(home) and os.path.isdir(p)]
    _store_rows(conn, "ai_agent_settings", SETTING_COLUMNS, SETTING_KEY,
                _extras.settings(profile, CLAUDE_CODE, user, inside, mask_secrets), parsed_at, tally)


def _known(conn, agent, user):
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT session_id FROM ai_agent_sessions WHERE agent = ? AND user_name = ?", (agent, user))}


def _other_profile_records(conn, profile, user, limit, parsed_at, tally):
    """What the other agents keep outside their per-session files."""
    me = _ME
    # Claude desktop: a session it ran is the CLI session it names - its row is
    # marked desktop and titled, not stored twice; one with no transcript is kept.
    sessions, loose, settings = _more.claude_desktop(me, profile, user, limit)
    known = _known(conn, CLAUDE_CODE, user)
    for s in sessions:
        sid = s.row["session_id"]
        if sid in known:
            conn.execute("UPDATE ai_agent_sessions SET app = 'desktop', title = CASE WHEN title = '' "
                         "OR title IS NULL THEN ? ELSE title END WHERE agent = ? AND user_name = ? "
                         "AND session_id = ?", (s.row["title"], CLAUDE_CODE, user, sid))
        else:
            _store(conn, [s], None, _extras.mtime_ts(s.row["source_path"]), parsed_at, tally)
    _store_rows(conn, "ai_agent_steps", STEP_COLUMNS, STEP_KEY, loose, parsed_at, tally)
    _store_rows(conn, "ai_agent_settings", SETTING_COLUMNS, SETTING_KEY, settings, parsed_at, tally)
    # Codex: thread metadata onto the rollout sessions; threads with no rollout
    known = _known(conn, CODEX, user)
    meta, sessions = _more.codex_threads(me, profile, user, limit, known)
    for tid, m in meta.items():
        if tid in known:
            row = {}
            _more.apply_codex_meta(row, m)
            if row:
                cols = [c for c in ("git_sha", "git_origin", "git_branch", "sandbox_policy") if row.get(c)]
                if cols:
                    conn.execute("UPDATE ai_agent_sessions SET %s WHERE agent = ? AND user_name = ? "
                                 "AND session_id = ?" % ", ".join("%s = ?" % c for c in cols),
                                 [row[c] for c in cols] + [CODEX, user, tid])
    for s in sessions:
        _store(conn, [s], None, _extras.mtime_ts(s.row["source_path"]), parsed_at, tally)
    _store_rows(conn, "ai_agent_settings", SETTING_COLUMNS, SETTING_KEY,
                _more.codex_settings(me, profile, user), parsed_at, tally)
    # Gemini CLI prompts whose chat file is gone
    for s in _more.gemini_log_prompts(me, profile, user, _known(conn, GEMINI_CLI, user)):
        _store(conn, [s], None, _extras.mtime_ts(s.row["source_path"]), parsed_at, tally)
    # Antigravity plans and screenshots with no conversation file
    for s in _more.antigravity_orphans(me, profile, user, limit, _known(conn, _more.ANTIGRAVITY, user)):
        _store(conn, [s], None, _extras.mtime_ts(s.row["source_path"]), parsed_at, tally)
    # GitHub Copilot: its session store, and its processes
    sessions, loose = _more.copilot_store(me, profile, user, limit, _known(conn, _more.COPILOT, user))
    for s in sessions:
        _store(conn, [s], None, _extras.mtime_ts(s.row["source_path"]), parsed_at, tally)
    _store_rows(conn, "ai_agent_steps", STEP_COLUMNS, STEP_KEY, loose, parsed_at, tally)
    _store_rows(conn, "ai_agent_processes", PROCESS_COLUMNS, PROCESS_KEY,
                _more.copilot_processes(me, profile, user), parsed_at, tally)


def _loose_step(agent, user, session_id, step_id, ts, role, kind, source, **kw):
    """A step that belongs to no session file (a todo, a plan)."""
    st = {c: "" for c in STEP_COLUMNS}
    st.update(agent=agent, user_name=user, session_id=session_id, step_id=step_id, ts=ts,
              role=role, kind=kind, source_path=source, is_sidechain=0, text_length=0,
              exit_code=None, duration_ms=None)
    st.update(kw)
    return st


def parse_users_root(users_root, db_path, progress=None, sid_map=None) -> dict:
    """Parse every profile under a Users folder (live C:\\Users, or one from an image)."""
    limit = _result_chars()
    tally = Tally()
    upgrade = False
    if os.path.isfile(db_path):
        # A database written before the saved-versions table existed: read every
        # session file once more, so its stored steps gain their programs, exit
        # codes and durations and its sessions their saved file versions.
        probe = sqlite3.connect(db_path)
        try:
            names = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            upgrade = "ai_agent_sessions" in names and (
                "ai_agent_file_versions" not in names
                or probe.execute("PRAGMA user_version").fetchone()[0] < DERIVE_VERSION)
        finally:
            probe.close()
    conn = _open(db_path)
    parsed_at = get_current_forensic_timestamp()
    files = skipped = errors = 0
    try:
        for profile in sorted(glob.glob(os.path.join(users_root, "*"))):
            if not os.path.isdir(profile):
                continue
            user = os.path.basename(profile)
            try:
                sources = profile_sources(profile)
            except OSError as e:
                logger.info("AI agents: %s not readable: %s", profile, e)
                continue
            titles = _codex_titles(os.path.join(profile, ".codex")) \
                if any(a == CODEX for a, _ in sources) else {}
            has_claude = os.path.isdir(os.path.join(profile, ".claude"))
            exits = _extras.task_exit_codes(profile) if has_claude else {}
            claude_read: List[_Session] = []
            for agent, path in sources:
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                modified = format_forensic_timestamp(
                    datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc))
                if not upgrade and _unchanged(conn, path, st.st_size, modified):
                    skipped += 1
                    continue
                files += 1
                try:
                    if agent == CLAUDE_CODE:
                        sessions = _read_claude(path, user, limit)
                        for s in sessions:
                            for task_id, step_id in s.background.items():
                                if task_id in exits and step_id in s.by_id:
                                    s.by_id[step_id]["exit_code"] = exits[task_id][0]
                        claude_read.extend(s for s in sessions if s.versions)
                    elif agent == GEMINI_CLI:
                        sessions = _read_gemini(path, user, limit)
                    elif agent == CODEX:
                        sessions = _read_codex(path, user, limit, titles)
                    elif agent == _more.COPILOT:
                        sessions = _more.read_copilot_events(_ME, path, user, limit)
                    elif agent == _more.ANTIGRAVITY:
                        sessions = _more.read_antigravity(_ME, path, user, limit)
                    else:                                      # Roo Code, Kilo Code, Cline
                        sessions = _more.read_cline(_ME, path, user, limit, agent)
                    _store(conn, sessions, st.st_size, modified, parsed_at, tally)
                    conn.commit()
                except (OSError, MemoryError, sqlite3.Error) as e:
                    errors += 1
                    logger.warning("AI agents: %s not parsed: %s", path, e)
                if progress and files % 25 == 0:
                    progress("[AI agents] %d session files read\r" % files)
            if has_claude:
                try:
                    _claude_profile_extras(conn, profile, user, claude_read, limit, parsed_at, tally)
                    conn.commit()
                except (OSError, MemoryError, sqlite3.Error) as e:
                    errors += 1
                    logger.warning("AI agents: Claude Code records in %s not read: %s", profile, e)
            try:
                _other_profile_records(conn, profile, user, limit, parsed_at, tally)
                conn.commit()
            except (OSError, MemoryError, sqlite3.Error) as e:
                errors += 1
                logger.warning("AI agents: other agents' records in %s not read: %s", profile, e)
        _name_and_link(conn)
        _fill_sids(conn, sid_map)
        conn.execute("PRAGMA user_version = %d" % DERIVE_VERSION)
        conn.commit()
    finally:
        conn.close()
    if _copy_versions_setting():
        copied, failed = save_versions_into_case(db_path)
        print("[OK] AI agents: %d saved file version(s) copied into the case%s"
              % (copied, (", %d failed" % failed) if failed else ""))
    print("[OK] AI agents: %d session file(s) read, %d unchanged since the last parse" % (files, skipped))
    return tally.as_result(primary="ai_agent_steps", success=True, output_path=db_path,
                           files=files, unchanged_files=skipped, errors=errors)


def parse_ai_agent_data(case_artifacts_dir, windows_partition="C:", users_root=None) -> dict:
    """The live parse: every profile under <partition>\\Users into ai_agents.db."""
    root = users_root or os.path.join((windows_partition or "C:").rstrip("\\/") + "\\", "Users")
    if not os.path.isdir(root):
        return {"success": True, "status": "source_not_found", "records": 0,
                "message": "No Users folder at %s." % root}
    db_path = os.path.join(case_artifacts_dir, DB_NAME)
    # This machine's own profiles: its live ProfileList names their owners.
    # A Users folder given from elsewhere (users_root) is not this machine's.
    sid_map = {}
    if users_root is None:
        try:
            try:
                from Artifacts_Collectors.user_identity import _profile_list_live
            except ImportError:
                from user_identity import _profile_list_live
            sid_map = sid_map_from_profile_list(_profile_list_live())
        except Exception as exc:
            logger.info("AI agents: no SIDs for the profiles (%s)", exc)
    return parse_users_root(root, db_path, progress=lambda m: print(m, end=""), sid_map=sid_map)


if __name__ == "__main__":  # pragma: no cover - manual run
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(parse_ai_agent_data(out, users_root=sys.argv[2] if len(sys.argv) > 2 else None))
