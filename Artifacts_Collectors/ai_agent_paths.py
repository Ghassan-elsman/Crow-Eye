"""
ai_agent_paths - where AI agent session records live, shared by every collector.

The AI agent parser (AI_Agent_Claw.parse_users_root) reads a Users folder and
takes the owner of each record from the profile folder it sits in, so the
records are collected with their tree intact, exactly like browser profiles:

    live_acquisition\\AIAgents\\<source>\\Users\\<name>\\.claude\\projects\\...
                                                    \\.gemini\\tmp\\<hash>\\chats\\...
                                                    \\.codex\\sessions\\...
                                                    \\.codex\\state_5.sqlite

The Offline Importer, forensic-image extraction and Crow-Claw decide the same
three things from here, so they cannot drift apart:

  * which files inside a profile are AI agent session records (only the paths
    the parser opens - AI_Agent_Claw.profile_sources and _codex_titles),
  * that credential files are never among them (``.claude\\.credentials.json``,
    ``.codex\\auth.json``, ``.gemini\\oauth_creds.json``): they sit in the same
    folders and are never copied,
  * where inside the case a collected file goes.

No imports beyond the standard library and browser_paths (whose source tag
keeps two sources apart the same way).
"""

import fnmatch
import ntpath
import os
from typing import Optional

try:
    from Artifacts_Collectors.browser_paths import _anchor_len, _join, _safe, _short_hash
except ImportError:  # run with Artifacts_Collectors itself on sys.path
    from browser_paths import _anchor_len, _join, _safe, _short_hash

# The case folder (under live_acquisition) that holds collected AI agent trees.
AI_AGENT_CASE_DIR = "AIAgents"

# The agents' folders directly under a user profile.
AI_AGENT_DIRS = (".claude", ".gemini", ".codex", ".copilot")
# Below AppData: Claude desktop, the VS Code agent extensions, and Claude
# Code's background task output. Not an agent folder - AppData holds every
# browser profile too - so only the paths named in _appdata_wanted count.
_APPDATA = "appdata"
_VSCODE_AGENT_EXTENSIONS = ("rooveterinaryinc.roo-cline", "kilocode.kilo-code", "saoudrizwan.claude-dev")
# Files a profile keeps at its top (.claude.json beside .claude): read only
# when they sit directly in Users\<name>, never in a project folder.
_PROFILE_FILES = (".claude.json",)

# Credential files the agents keep beside their records. Never copied, never
# opened - checked by name wherever they sit.
CREDENTIAL_FILE_NAMES = frozenset((".credentials.json", "auth.json", "oauth_creds.json"))

# Where the session records are, below {PARTITION}\Users\*: the roots image
# extraction and Crow-Claw copy (each walked with ai_agent_file_wanted).
AI_AGENT_ROOT_PATTERNS = (
    r"\.claude\projects",
    r"\.gemini\tmp\*\chats",
    r"\.codex\sessions",
    r"\.codex\archived_sessions",
    r"\.codex\state_*.sqlite*",
    # what else the agents keep (ai_agent_claude_extras, ai_agent_more)
    r"\.claude\sessions",
    r"\.claude\daemon\attach-journal",
    r"\.claude\file-history",
    r"\.claude\tasks",
    r"\.claude\plans",
    r"\.claude\jobs",
    r"\.claude\history.jsonl",
    r"\.claude\settings*.json",
    r"\.claude\plugins\installed_plugins.json",
    r"\.claude\skills",
    r"\.claude.json",
    r"\.gemini\tmp\*\logs.json",
    r"\.gemini\antigravity\conversations",
    r"\.gemini\antigravity\brain",
    r"\.gemini\antigravity\browser_recordings",
    r"\.gemini\antigravity\mcp_config.json",
    r"\.codex\thread_history_*.sqlite*",
    r"\.codex\config.toml",
    r"\.codex\computer-use\config.json",
    r"\.copilot\session-state",
    r"\.copilot\session-store.db*",
    r"\.copilot\logs",
    r"\AppData\Roaming\Claude\claude-code-sessions",
    r"\AppData\Roaming\Claude\local-agent-mode-sessions",
    r"\AppData\Roaming\Code\User\globalStorage\rooveterinaryinc.roo-cline\tasks",
    r"\AppData\Roaming\Code\User\globalStorage\kilocode.kilo-code\tasks",
    r"\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev\tasks",
    r"\AppData\Local\Temp\claude",
)

_CODEX_STATE = ("state_*.sqlite", "state_*.sqlite-wal", "state_*.sqlite-shm")
_SQLITE_SET = lambda stem: (stem, stem + "-wal", stem + "-shm")   # noqa: E731
# Never copied from a desktop agent session: the key its audit log is signed with.
_SECRET_NAMES = frozenset((".audit-key",))


def _appdata_wanted(tail) -> bool:
    """`tail` from AppData down: the Claude desktop and VS Code agent records."""
    n = len(tail)
    name = tail[-1]
    if name in _SECRET_NAMES or name in CREDENTIAL_FILE_NAMES:
        return False
    if n >= 4 and tail[1] == "roaming" and tail[2] == "claude":
        if tail[3] == "claude-code-sessions":
            return name.startswith("local_") and name.endswith(".json")
        if tail[3] == "local-agent-mode-sessions" and n >= 8:
            inside = tail[7:]                  # below local_<id>
            return ((inside[0] == ".claude" and len(inside) >= 3 and inside[1] == "projects"
                     and (name.endswith(".jsonl") or name.endswith(".meta.json")))
                    or inside == ["audit.jsonl"] or (inside[0] == "outputs" and len(inside) >= 2))
        return False
    if (n == 9 and tail[1:5] == ["roaming", "code", "user", "globalstorage"]
            and tail[5] in _VSCODE_AGENT_EXTENSIONS and tail[6] == "tasks"):
        return name in ("api_conversation_history.json", "history_item.json", "ui_messages.json")
    # Local\Temp\claude\<cwd>\<session>\tasks\<id>.output
    if n == 8 and tail[1:4] == ["local", "temp", "claude"] and tail[6] == "tasks":
        return name.endswith(".output")
    return False


def is_credential_file(name: str) -> bool:
    """True for an agent credential file name (compared case-insensitively)."""
    return os.path.basename((name or "").replace("\\", "/")).lower() in CREDENTIAL_FILE_NAMES


def session_tail_wanted(tail) -> bool:
    """True when ``tail`` - the lowercase path components from an agent folder
    (``.claude`` / ``.gemini`` / ``.codex``) down to a file name - is a record
    the parser reads. Mirrors AI_Agent_Claw.profile_sources and _codex_titles.
    """
    if len(tail) == 1:
        return tail[0] in _PROFILE_FILES
    if len(tail) < 2:
        return False
    name = tail[-1]
    if name in CREDENTIAL_FILE_NAMES or name in _SECRET_NAMES:
        return False
    top = tail[0]
    n = len(tail)
    if top == _APPDATA:
        return _appdata_wanted(tail)
    if top == ".claude":
        sub = tail[1]
        # projects\**\*.jsonl (sessions and their sub-agent transcripts)
        # ...and each sub-agent's agent-<id>.meta.json (what it was started to do)
        if sub == "projects":
            return n >= 3 and (name.endswith(".jsonl")
                               or (n >= 5 and tail[-2] == "subagents" and name.endswith(".meta.json")))
        if n == 2:
            return name in ("history.jsonl", "settings.json", "settings.local.json")
        if sub in ("sessions",) and n == 3:
            return name.endswith(".json")
        if sub == "daemon" and n == 4 and tail[2] == "attach-journal":
            return name.endswith(".json")
        if sub == "file-history" and n == 4:
            return True                                   # <session>\<hash>@vN
        if sub == "tasks" and n == 4:
            return name.endswith(".json")
        if sub == "plans" and n == 3:
            return name.endswith(".md")
        if sub == "jobs" and n == 4:
            return name in ("state.json", "timeline.jsonl")  # never jobs\*\tmp
        if sub == "plugins" and n == 3:
            return name == "installed_plugins.json"
        if sub == "skills" and n == 4:
            return name == "skill.md"
        return False
    if top == ".gemini":
        # tmp\<project hash>\chats\session-*.json, and logs.json beside chats
        if n == 5 and tail[1] == "tmp" and tail[3] == "chats":
            return name.startswith("session-") and name.endswith(".json")
        if n == 4 and tail[1] == "tmp":
            return name == "logs.json"
        if n >= 3 and tail[1] == "antigravity":
            sub = tail[2]
            if sub == "conversations" and n == 4:
                return any(fnmatch.fnmatchcase(name, p) for p in _SQLITE_SET("*.db"))
            if sub == "brain" and n == 5:
                return name.endswith((".md", ".metadata.json"))
            if sub == "browser_recordings" and n == 5:
                return name.endswith(".jpg")
            return n == 3 and name == "mcp_config.json"
        return False
    if top == ".codex":
        if n == 2:
            # state_<n>.sqlite (+ its -wal / -shm): the session titles;
            # thread_history_<n>.sqlite: threads with no rollout; config.toml
            return (any(fnmatch.fnmatchcase(name, p) for p in _CODEX_STATE)
                    or any(fnmatch.fnmatchcase(name, p) for p in _SQLITE_SET("thread_history_*.sqlite"))
                    or name == "config.toml")
        if n == 3 and tail[1] == "computer-use":
            return name == "config.json"
        # sessions\** and archived_sessions\**: rollout-*.jsonl(.zst)
        return (tail[1] in ("sessions", "archived_sessions") and name.startswith("rollout-")
                and name.endswith((".jsonl", ".jsonl.zst")))
    if top == ".copilot":
        if n == 2:
            return any(fnmatch.fnmatchcase(name, p) for p in _SQLITE_SET("session-store.db"))
        if n == 4 and tail[1] == "session-state":
            return name == "events.jsonl"
        return n == 3 and tail[1] == "logs" and name.startswith("process-") and name.endswith(".log")
    return False


def ai_agent_path_info(file_path: str, base: Optional[str] = None):
    """Where an AI agent session file belongs, as ``(rel, root, volume_root)``,
    or None when the file is not one.

    * ``rel`` - ``<user>\\.claude\\projects\\...``: the part of the path the case
      tree keeps below ``Users``.
    * ``root`` - the folder on disk that ``rel``'s first component stands for.
    * ``volume_root`` - the folder holding that ``Users`` folder: what tells one
      source's tree from another's (``browser_source_tag`` of it).

    Identified by WHERE the file sits: ``auth.json`` or ``state_5.sqlite`` mean
    nothing by name alone. ``base`` is the folder being imported; a profile
    folder ABOVE it is not the evidence's (every import on this machine sits
    under the analyst's own ``C:\\Users\\<me>``), so such a file is placed under
    a pseudo-user named for the imported folder instead.
    """
    norm = (file_path or "").replace("/", "\\")
    parts = [p for p in norm.split("\\") if p]
    low = [p.lower() for p in parts]
    if not parts or low[-1] in CREDENTIAL_FILE_NAMES:
        return None
    anchor = _anchor_len(norm)
    base_n = 0
    if base:
        bnorm = os.path.normcase(os.path.normpath(base)).replace("/", "\\").rstrip("\\")
        if os.path.normcase(norm).startswith(bnorm + "\\"):
            base_n = len([p for p in bnorm.split("\\") if p])
    floor = max(anchor, base_n - 1)    # lowest index a user folder may have

    # The OUTERMOST agent folder whose tail is a record: the one directly in
    # the profile, as the parser reads it.
    agent_i = None
    for i in range(anchor, len(low)):
        cand = low[i]
        if i == len(low) - 1:
            if cand not in _PROFILE_FILES:
                continue
        elif cand not in AI_AGENT_DIRS and cand != _APPDATA:
            continue
        if not session_tail_wanted(low[i:]):
            continue
        # A project folder has a .claude too (settings, skills): only the
        # profile's own counts, so everything but the transcripts must sit
        # directly in Users\<name>.
        profile_only = cand in (_APPDATA,) + _PROFILE_FILES or (
            cand == ".claude" and low[i + 1] != "projects")
        if profile_only and not (i >= 2 and low[i - 2] == "users"):
            continue
        agent_i = i
        break
    if agent_i is None:
        return None
    tail = parts[agent_i:]

    # Already inside a tree-preserving AIAgents collection (a case's, or a
    # Crow-Claw output being imported): ...\AIAgents\<source>\Users\<name>\...
    b = agent_i - 4
    if b >= 0 and low[b] == AI_AGENT_CASE_DIR.lower() and low[b + 2] == "users":
        return ("\\".join(parts[b + 3:]), _join(norm, parts, b + 4), _join(norm, parts, b + 2))

    user_i = agent_i - 1
    if user_i >= floor and user_i >= anchor:
        rel = "\\".join(parts[user_i:])
        vol = user_i - 1 if user_i - 1 >= anchor and low[user_i - 1] == "users" else user_i
        return rel, _join(norm, parts, user_i + 1), _join(norm, parts, max(vol, anchor))

    # No owner inside the import: a pseudo-user named for the folder imported
    # (or the drive), so two loose trees never share one.
    holder_k = max(base_n, anchor) if base_n else agent_i
    holder = _join(norm, parts, holder_k) if holder_k > 0 else norm
    label = _safe(parts[holder_k - 1] if holder_k > anchor else "root") or "root"
    user = "_unattributed_%s_%s" % (label, _short_hash(os.path.normcase(holder)))
    return "\\".join([user] + tail), holder, holder


def ai_agent_relative_path(file_path: str, base: Optional[str] = None) -> Optional[str]:
    """``<user>\\.claude\\...`` for an AI agent session file, else None."""
    info = ai_agent_path_info(file_path, base)
    return info[0] if info else None


def in_ai_agent_folder(file_path: str) -> bool:
    """True for any file below a ``.claude`` / ``.gemini`` / ``.codex`` folder.

    What the collectors must not copy as *anything else*: a credential file or
    an agent's settings would otherwise be taken as an "Unknown" file by an
    All Types import. Session records are typed AIAgents before this is asked.
    """
    parts = [p.lower() for p in (file_path or "").replace("/", "\\").split("\\") if p]
    return any(p in AI_AGENT_DIRS for p in parts[:-1])


def ai_agent_file_wanted(path_from_volume_root: str) -> bool:
    """True when a file met while walking a collected root (``/Users/<name>/
    .codex/sessions/...``, either separator) is a session record to copy.
    Everything else in those folders - credential files above all - is not."""
    return ai_agent_path_info(path_from_volume_root) is not None


__all__ = ["AI_AGENT_CASE_DIR", "AI_AGENT_DIRS", "AI_AGENT_ROOT_PATTERNS",
           "CREDENTIAL_FILE_NAMES", "ai_agent_file_wanted", "ai_agent_path_info",
           "ai_agent_relative_path", "in_ai_agent_folder", "is_credential_file",
           "session_tail_wanted"]
