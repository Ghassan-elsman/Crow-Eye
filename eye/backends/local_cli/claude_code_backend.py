"""
Claude Code backend: Eye on the analyst's own Claude Code sign-in.

Eye runs `claude -p` as a plain model: Claude Code's own tools, MCP servers,
CLAUDE.md, hooks and slash commands are all switched off, so the only thing
that can touch the evidence is Eye's own tool loop (guardrails, EvidenceSeal).
Eye's tool calls come back through `--json-schema` as structured JSON, not
scraped out of free text.

Facts proven against Claude Code 2.1.316 (2026-11-02):
- `--tools ""` disables every built-in tool; `--safe-mode` drops CLAUDE.md,
  skills, plugins, hooks and MCP; `--strict-mcp-config` with no config loads
  no MCP server. A call then carries ~600 prompt tokens of its own.
- `--system-prompt-file` works outside `--bare`, which keeps a long Eye
  prompt off the command line (Windows caps it at 32K characters).
- `--output-format json` returns one object: `result`, `structured_output`
  (with `--json-schema`), `usage` (cache read / write included),
  `modelUsage`, `total_cost_usd`, `stop_reason`, `is_error`,
  `api_error_status`. A bad model is `is_error: true`, status 404, exit 0.
- ANTHROPIC_API_KEY in the environment makes Claude Code bill that key
  instead of the sign-in, so it is removed from the child's environment.

Sessions (2026-11-02): one `claude -p` per call, with the whole conversation as
one prompt, could never reuse Claude's prompt cache across Eye's steps - the
cache only matches at message boundaries. One question took 53 calls and wrote
20.6M tokens to the cache (list price ~$84) and used up the Claude plan's
limit. So Eye's tool loop now keeps ONE long-lived process per conversation
(`--input-format stream-json`) and sends only what Claude has not seen yet:
earlier turns are real messages there, read back from the cache, and the
per-call start-up (3-5 s) is gone. The session restarts from Eye's own history
when that history stops being an extension of what was sent, or when the
session passes SESSION_TOKEN_CAP.
"""

import atexit
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import weakref
from collections import deque
from typing import Any, Dict, List, Optional

from eye.backends.base import LLMBackend, split_step_context, STEP_CONTEXT_HEADING

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
MODEL_ALIASES = ["sonnet", "opus", "fable", "haiku"]
FULL_MODEL_IDS = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5"]
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT_S = 600
MIN_OUTPUT_TOKENS = 8192
# Past this many tokens in one session, start a new one from Eye's own (slimmed)
# history - but only when what Eye cannot see (earlier step messages and step
# context) is a real share of it; restarting a session that is mostly Eye's own
# history would just write all of it to the cache again (it did, on every call
# after the first 600K, 2026-11-02).
SESSION_TOKEN_CAP = 600_000
SESSION_EXTRA_SHARE = 0.3
# Whatever the share, a session this full starts again from Eye's own history:
# Eye budgets that history against EYE_CONTEXT_WINDOW, which leaves room under the
# model's 1M for Claude Code's own prompt and the session's extra. Without it the
# last call of a 47-step question was ~1,003K tokens: "Prompt is too long".
SESSION_HARD_CAP = 850_000
# Eye trims its own history to this window. At 800K its history alone reached
# ~815K tokens, so a full session could not be made smaller by restarting and
# every call restarted (writing ~850K tokens to the cache each time) until the
# plan's 5-hour limit was used up (2026-11-02). 600K leaves the room.
EYE_CONTEXT_WINDOW = 600_000


def context_size(usage, fallback: int = 0) -> int:
    """How full the session's context is after a turn.

    `usage` sums every API request of the turn - a structured reply takes two -
    so its totals counted the context about twice (a 700K session read as 1.4M
    and restarted on every call). The last request in `iterations` is the size."""
    its = usage.get("iterations") or []
    if its and isinstance(its[-1], dict):
        u = its[-1]
        return (int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
                + int(u.get("cache_creation_input_tokens") or 0) + int(u.get("output_tokens") or 0))
    # No per-request split: the summed totals overcount, so use what was sent.
    return int(fallback)


ASK_AGAIN = ('[The tool(s) you asked for are not available in this step. Write your reply to the investigator in `answer` now, from what you already have; leave `tool_calls` empty.]')


def only_unavailable_tools(reply) -> bool:
    """The model wrote no answer and every tool it asked for is not offered."""
    content = str(reply.get("content") or "")
    lines = [l for l in content.splitlines() if l.strip()]
    return (not reply.get("tool_calls") and bool(lines)
            and all(l.startswith("[Eye ignored a call to an unknown tool") for l in lines))


def step_update(previous: str, current: str):
    """What to send for Eye's per-step context, given the one already sent.

    Eye rebuilds it for every call (pinned evidence, the report so far, queries
    already run, retrieved knowledge) - about 30K tokens on a real case, nearly
    all of it unchanged from the last step. Resending it whole on each of 47
    turns filled a session to 950K tokens. Returns (text, full?)."""
    if not current:
        return "", False
    if previous is None:
        return current, True
    if current == previous:
        return "(Unchanged since your last turn.)", False
    import difflib
    old, new = previous.splitlines(), current.splitlines()
    added, removed = [], 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added.extend(new[j1:j2])
    body = "\n".join(added)
    if len(body) > 0.6 * len(current):
        return current, True
    head = ("(Changes since your last turn: %d line(s) added below%s; everything else is as before.)"
            % (len(added), ", %d line(s) no longer apply" % removed if removed else ""))
    return head + ("\n" + body if body else ""), False

# Variables that would make Claude Code bill an API key or another endpoint
# instead of the analyst's Claude Code sign-in.
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

# One reply: an answer, or the tool calls Eye should run next.
REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string",
                   "description": "Your reply to the investigator. Empty when you are calling tools."},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["answer", "tool_calls"],
}

_ROLE_LABELS = {"user": "Investigator", "assistant": "Eye", "tool": "Tool result",
                "function": "Tool result", "system": "Eye note"}


class ClaudeCodeError(Exception):
    """A failed Claude Code call. ``status_code`` lets the router's retry and
    ``describe_backend_error`` treat it like an SDK error."""

    def __init__(self, message, status_code=None, kind=None):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


def _plain_error(text, status):
    """What the investigator should do, for the failures Claude Code reports."""
    low = (text or "").lower()
    if "prompt is too long" in low or "too many tokens" in low:
        return ("The conversation is too long for the model's context window. Start a new "
                "conversation, or ask a narrower question.", "too_long")
    if ("hit your" in low and "limit" in low) or "usage limit" in low or "limit reached" in low \
            or "limit will reset" in low or "resets" in low and "limit" in low:
        return ("Your Claude plan's usage limit is reached. %s" % (text or "").strip(), "limit")
    if "not logged in" in low or "/login" in low or "please run" in low and "login" in low \
            or status == 401:
        return ("Claude Code is not signed in. Open a terminal, run `claude` once and sign in, "
                "then try again.", "login")
    if "usage limit" in low or "limit reached" in low or "limit will reset" in low:
        return ("Your Claude plan's usage limit is reached. %s" % (text or "").strip(), "limit")
    if status == 404 or "issue with the selected model" in low:
        return ("Claude Code does not know this model. Pick sonnet, opus, fable or haiku in "
                "Settings -> Eye AI.", "model")
    if status == 429:
        said = (text or "").strip()
        return ("Claude is rate-limiting this account; wait a moment and ask again."
                + (" Claude says: %s" % said[:300] if said else ""), "rate")
    if status == 529 or "overloaded" in low:
        return ("Claude is overloaded right now; Eye will retry.", "overloaded")
    if isinstance(status, int) and status >= 500:
        return ("Claude had a server error (%d); Eye will retry." % status, "server")
    return ((text or "Claude Code returned an error.").strip(), "other")


_LIVE_SESSIONS = weakref.WeakSet()


@atexit.register
def _close_all_sessions():
    for sess in list(_LIVE_SESSIONS):
        try:
            sess.close()
        except Exception:
            pass


def _fingerprint(msg) -> str:
    content = msg.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(("%s\x00%s" % (msg.get("role", ""), content)).encode("utf-8", "replace")).hexdigest()


class _Session:
    """One long-lived `claude -p --input-format stream-json` process."""

    def __init__(self, backend, base_key, tools_key, core, max_output_tokens=None):
        self.base_key, self.tools_key = base_key, tools_key
        self.sent: List[str] = []          # fingerprints of Eye history already delivered
        self.replies = set()               # fingerprints of what Claude itself answered
        self.context_tokens = 0
        self.extra_chars = 0               # what Eye's history does not hold (step messages)
        self.sent_chars = len(core)        # everything sent or answered, for a size estimate
        self.last_step = None
        self.turns = 0
        self._cost_total = 0.0
        fd, self.sp_path = tempfile.mkstemp(prefix="eye_sp_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(core)
        args = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--tools", "", "--no-session-persistence", "--safe-mode", "--strict-mcp-config",
                "--disable-slash-commands", "--system-prompt-file", self.sp_path,
                "--model", backend.model_name,
                "--json-schema", json.dumps(REPLY_SCHEMA, separators=(",", ":"))]
        if backend.effort:
            args += ["--effort", backend.effort]
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            backend._command_prefix() + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=backend.child_environment(max_output_tokens=max_output_tokens),
            cwd=tempfile.gettempdir(), **kwargs)
        self._lines = queue.Queue()
        self._err = deque(maxlen=40)
        threading.Thread(target=self._pump, args=(self.proc.stdout, self._lines), daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()
        _LIVE_SESSIONS.add(self)

    @staticmethod
    def _pump(stream, q):
        try:
            for line in iter(stream.readline, b""):
                q.put(line)
        finally:
            q.put(None)

    def _drain(self):
        try:
            for line in iter(self.proc.stderr.readline, b""):
                self._err.append(line.decode("utf-8", "replace").rstrip())
        except Exception:
            pass

    def alive(self) -> bool:
        return self.proc.poll() is None

    def ask(self, text: str, timeout: int) -> Dict[str, Any]:
        """Send one user turn; the turn's `result` event (with this turn's cost)."""
        import time
        msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.sent_chars += len(text)
        try:
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            raise ClaudeCodeError(_plain_error("\n".join(self._err) or str(e), None)[0], kind="session")
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.close()
                raise ClaudeCodeError("Claude Code did not answer within %d s." % timeout, kind="timeout")
            try:
                line = self._lines.get(timeout=min(left, 5.0))
            except queue.Empty:
                continue
            if line is None:
                tail = "\n".join(self._err)
                msg_, kind = _plain_error(tail[-600:] or "Claude Code stopped.", None)
                raise ClaudeCodeError(msg_, kind=kind)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "result":
                continue
            self.turns += 1
            total = float(ev.get("total_cost_usd") or 0.0)
            ev = dict(ev, total_cost_usd=max(0.0, total - self._cost_total))
            self._cost_total = max(self._cost_total, total)
            self.context_tokens = context_size(ev.get("usage") or {}, fallback=int(self.sent_chars / 3.5))
            return ev

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        if self.proc.poll() is None:
            try:
                from utils.concurrency.process_tree import kill_tree
                kill_tree(self.proc.pid, grace=1.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        try:
            os.remove(self.sp_path)
        except OSError:
            pass
        _LIVE_SESSIONS.discard(self)


class ClaudeCodeBackend(LLMBackend):
    """Eye's model calls through the local `claude` command."""

    def __init__(self, executable_path: str = "", model_name: str = DEFAULT_MODEL,
                 effort: Optional[str] = None, timeout_s: Optional[int] = None):
        self.executable_path = executable_path or ""
        mn = (model_name or "").strip()
        if mn in ("", "default", "cli-default-model", "Claude Code") or "CLI Agent" in mn:
            mn = DEFAULT_MODEL
        self.model_name = mn
        self.effort = effort if effort in EFFORT_LEVELS else None
        self.timeout_s = int(timeout_s or DEFAULT_TIMEOUT_S)
        self.logger = logging.getLogger(__name__)
        self.last_error = ""
        self.last_usage = None
        self.session_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                              "cost_usd": 0.0}
        self.backend_type = "claude_code"
        # Conversations that keep a live Claude Code process (Eye's tool loop).
        self.use_sessions = True
        self._sessions: Dict[str, _Session] = {}
        self._session_lock = threading.Lock()

    # ---- launching --------------------------------------------------------
    def _resolve_executable(self) -> str:
        path = self.executable_path.strip().strip('"')
        if path:
            if os.name == "nt" and not os.path.splitext(path)[1]:
                for ext in (".exe", ".cmd", ".bat"):
                    if os.path.exists(path + ext):
                        return path + ext
            return path
        return shutil.which("claude") or "claude"

    def _command_prefix(self) -> List[str]:
        exe = self._resolve_executable()
        low = exe.lower()
        if os.name == "nt" and low.endswith((".cmd", ".bat")):
            return ["cmd", "/c", exe]
        if low.endswith(".py"):
            import sys
            return [sys.executable, exe]
        return [exe]

    @staticmethod
    def child_environment(base=None, max_output_tokens=None) -> Dict[str, str]:
        env = dict(os.environ if base is None else base)
        for k in _STRIPPED_ENV:
            env.pop(k, None)
        if max_output_tokens:
            # Claude Code fails the whole call when the reply (thinking and the structured
            # reply included) passes this cap, rather than truncating: a 256-token budget
            # meant for a one-word probe made every probe an error. Never go below 8192.
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max(int(max_output_tokens), MIN_OUTPUT_TOKENS))
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        return env

    def _run(self, args: List[str], stdin_text: str, timeout: int, max_output_tokens=None):
        """(returncode, stdout, stderr). Kills the whole tree on timeout."""
        cmd = self._command_prefix() + args
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.child_environment(max_output_tokens=max_output_tokens),
            cwd=tempfile.gettempdir(), **kwargs)
        try:
            out, err = proc.communicate(input=(stdin_text or "").encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                from utils.concurrency.process_tree import kill_tree
                kill_tree(proc.pid)
            except Exception:
                proc.kill()
            try:
                proc.communicate(timeout=10)
            except Exception:
                pass
            raise ClaudeCodeError("Claude Code did not answer within %d s." % timeout,
                                  status_code=None, kind="timeout")
        return (proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))

    # ---- prompt building --------------------------------------------------
    @staticmethod
    def tool_instructions(tools: List[Dict]) -> str:
        lines = [
            "",
            "## How to use Eye's tools",
            "The tools below are NOT functions you can invoke yourself - you have no callable "
            "tools in this session, and trying to call one directly fails with 'No such tool "
            "available'. You REQUEST them: your reply is a JSON object {answer, tool_calls}. To "
            "run tools, put each request in `tool_calls` as {\"name\": <tool name>, "
            "\"arguments\": {...}} and leave `answer` empty; the Eye runs them and sends the "
            "results back in the next turn. When you have what you need, write the reply in "
            "`answer` and leave `tool_calls` empty. Only these tool names exist, and the "
            "arguments must match their schema:",
        ]
        for t in tools:
            lines.append("")
            lines.append("### %s" % t.get("name", ""))
            if t.get("description"):
                lines.append(str(t["description"]).strip())
            lines.append("Arguments schema: " + json.dumps(t.get("parameters") or {"type": "object"},
                                                           separators=(",", ":"), sort_keys=True))
        return "\n".join(lines)

    @staticmethod
    def render_transcript(history, user_message, step_context) -> str:
        """The conversation as one prompt. Earlier turns come first and never
        change, so Claude Code's prompt cache reads them back; the context
        rebuilt for this step goes last."""
        parts = []
        if history:
            parts.append("<conversation_so_far>")
            for msg in history:
                role = _ROLE_LABELS.get(msg.get("role", "user"), "Investigator")
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False, default=str)
                parts.append("[%s]\n%s\n" % (role, content.strip()))
            parts.append("</conversation_so_far>\n")
        parts.append("[Investigator]\n%s" % (user_message or "").strip())
        if step_context:
            parts.append("\n%s (from the Eye, not the investigator)\n%s"
                         % (STEP_CONTEXT_HEADING, step_context.strip()))
        return "\n".join(parts)

    # ---- the call ---------------------------------------------------------
    @staticmethod
    def _key(*parts) -> str:
        return hashlib.sha1("\x00".join(str(p) for p in parts).encode("utf-8", "replace")).hexdigest()

    def close_sessions(self):
        for sess in list(self._sessions.values()):
            sess.close()
        self._sessions.clear()

    def _session_turn(self, base_core, step, tools, history, user_message, gen_params):
        """A turn in a live session, or None when this call should run on its own."""
        if not self.use_sessions or not history:
            return None            # planning / reasoning passes: no history to keep
        if not self._session_lock.acquire(blocking=False):
            return None            # a parallel call (map-reduce): run it on its own
        try:
            base_key = self._key(self.model_name, self.effort, base_core)
            sess = self._sessions.get(base_key)
            tool_text = self.tool_instructions(tools) if tools else None
            tools_key = self._key(tool_text) if tool_text else None
            if sess is None and not tools:
                return None        # nothing to continue and no tools: a one-off call
            fps = [_fingerprint(m) for m in history]
            reason = ""
            if sess is None:
                reason = "new"
            elif not sess.alive():
                reason = "process ended"
            elif tools_key and tools_key != sess.tools_key:
                reason = "tools changed"
            elif fps[:len(sess.sent)] != sess.sent:
                k = next((i for i, (a, b) in enumerate(zip(sess.sent, fps)) if a != b),
                         min(len(fps), len(sess.sent)))
                reason = "history changed at message %d of %d" % (k, len(sess.sent))
            elif sess.context_tokens > SESSION_TOKEN_CAP:
                # Only restart when it makes the session smaller: a fresh one holds
                # Eye's history and the core, and nothing of the earlier steps.
                fresh = (len(base_core) + len(tool_text or "")
                         + sum(len(str(m.get("content") or "")) for m in history)) / 3.5
                if fresh < 0.75 * sess.context_tokens and (
                        sess.context_tokens > SESSION_HARD_CAP
                        or sess.extra_chars / 4.0 > SESSION_EXTRA_SHARE * sess.context_tokens):
                    reason = "session full (%d tokens)" % sess.context_tokens
            restart = bool(reason)
            if restart:
                if sess is not None:
                    sess.close()
                for k in [k for k in self._sessions if k != base_key]:
                    self._sessions.pop(k).close()       # one live process per backend
                sess = _Session(self, base_key, tools_key, base_core + "\n" + (tool_text or ""),
                                (gen_params or {}).get("max_output_tokens"))
                self._sessions[base_key] = sess
                delta = list(history)
            else:
                delta = [m for m in history[len(sess.sent):]
                         if not (m.get("role") == "assistant" and _fingerprint(m) in sess.replies)
                         and not (m.get("role") == "assistant" and not str(m.get("content") or "").strip())]
            step_text, _full = step_update(sess.last_step, step)
            text = self.render_turn(delta, user_message, step_text, first=restart, tools_allowed=bool(tools))
            try:
                try:
                    data = self._check_result(sess.ask(text, self.timeout_s))
                except ClaudeCodeError as e:
                    # Retry once in a fresh session from Eye's own history: a continued
                    # session that overflowed, or a turn that failed with no API status
                    # (the session process went wrong, not the request).
                    retry = (e.kind == "too_long" and not restart) or (
                        e.status_code is None and e.kind in ("other", "session"))
                    if not retry:
                        raise
                    sess.close()
                    reason = ("too long, started again" if e.kind == "too_long"
                              else "turn failed (%s), started again" % str(e)[:120])
                    sess = _Session(self, base_key, tools_key, base_core + "\n" + (tool_text or ""),
                                    (gen_params or {}).get("max_output_tokens"))
                    self._sessions[base_key] = sess
                    text = self.render_turn(list(history), user_message, step, first=True,
                                            tools_allowed=bool(tools))
                    data = self._check_result(sess.ask(text, self.timeout_s))
            except ClaudeCodeError:
                sess.close()
                self._sessions.pop(base_key, None)
                raise
            sess.sent = fps
            sess.last_step = step
            sess.extra_chars += len(user_message or "") + len(step_text or "")
            if reason and reason != "new":
                self.logger.info("Claude Code session restarted: %s", reason)
            reply = self._to_eye_reply(data, tools or [], structured=True)
            if only_unavailable_tools(reply):
                # It asked only for tools this step does not offer (the write-up step
                # offers report tools only) and wrote no answer: the drop note became
                # the whole answer (2026-11-02 eval). Ask once more, in the session.
                data = self._check_result(sess.ask(ASK_AGAIN, self.timeout_s))
                reply = self._to_eye_reply(data, tools or [], structured=True)
            reply["session"] = {"turn": sess.turns, "restart": reason}
            if reply.get("content"):
                sess.replies.add(_fingerprint({"role": "assistant", "content": reply["content"]}))
            return reply
        finally:
            self._session_lock.release()

    @staticmethod
    def render_turn(delta, user_message, step_context, first, tools_allowed) -> str:
        """One user turn in a session: what happened since Claude's last reply, then this step."""
        parts = []
        if delta:
            parts.append("<conversation_so_far>" if first else "<since_your_last_reply>")
            for msg in delta:
                role = _ROLE_LABELS.get(msg.get("role", "user"), "Investigator")
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False, default=str)
                parts.append("[%s]\n%s\n" % (role, content.strip()))
            parts.append("</conversation_so_far>\n" if first else "</since_your_last_reply>\n")
        parts.append("[Investigator]\n%s" % (user_message or "").strip())
        if step_context:
            parts.append("\n%s (from the Eye, not the investigator)\n%s"
                         % (STEP_CONTEXT_HEADING, step_context.strip()))
        if not tools_allowed:
            parts.append("\n[No tools this turn: write your reply in `answer` and leave `tool_calls` empty.]")
        return "\n".join(parts)

    def generate(self, system_prompt, user_message, tools=None, history=None, gen_params=None):
        sp_path = None
        try:
            core, step = split_step_context(system_prompt or "")
            reply = self._session_turn(core, step, tools, history, user_message, gen_params)
            if reply is not None:
                return reply
            if tools:
                core = core + "\n" + self.tool_instructions(tools)
            fd, sp_path = tempfile.mkstemp(prefix="eye_sp_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(core)
            args = ["-p", "--output-format", "json", "--tools", "",
                    "--no-session-persistence", "--safe-mode", "--strict-mcp-config",
                    "--disable-slash-commands", "--system-prompt-file", sp_path,
                    "--model", self.model_name]
            if self.effort:
                args += ["--effort", self.effort]
            if tools:
                args += ["--json-schema", json.dumps(REPLY_SCHEMA, separators=(",", ":"))]
            prompt = self.render_transcript(history, user_message, step)
            gp = gen_params or {}
            code, out, err = self._run(args, prompt, self.timeout_s, gp.get("max_output_tokens"))
            data = self._parse_output(out, err, code)
            return self._to_eye_reply(data, tools)
        except ClaudeCodeError as e:
            self.last_error = str(e)
            self.logger.error("Claude Code failure: %s", e)
            raise
        except FileNotFoundError as e:
            self.last_error = ("Claude Code was not found. Install it (https://claude.com/claude-code) "
                               "or set its path in Settings -> Eye AI.")
            self.logger.error("Claude Code failure: %s", e)
            raise ClaudeCodeError(self.last_error, kind="missing") from e
        finally:
            if sp_path:
                try:
                    os.remove(sp_path)
                except OSError:
                    pass

    @staticmethod
    def _check_result(data):
        if data.get("is_error"):
            status = data.get("api_error_status")
            # An error turn can carry its reason in `errors` / `subtype` with an empty
            # `result`; reading only `result` gave "Claude Code returned an error." and
            # nothing to act on (2026-11-02 eval).
            said = str(data.get("result") or "").strip()
            errs = data.get("errors")
            if isinstance(errs, list):
                errs = "; ".join(str(e) for e in errs if e)
            detail = "; ".join(x for x in (said, str(errs or "").strip(),
                                           "subtype %s" % data["subtype"] if data.get("subtype")
                                           and data.get("subtype") != "success" else "") if x)
            msg, kind = _plain_error(detail, status)
            if kind == "other" and detail and detail not in msg:
                msg = "Claude Code returned an error: %s" % detail[:400]
            raise ClaudeCodeError(msg, status_code=status, kind=kind)
        return data

    @staticmethod
    def _parse_output(out, err, code):
        data = None
        text = (out or "").strip()
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                # A stray line before the JSON (some versions print a notice): take the last object.
                m = re.search(r"(\{.*\})\s*$", text, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                    except ValueError:
                        data = None
        if not isinstance(data, dict):
            msg, kind = _plain_error((err or text or "").strip()[-600:], None)
            if code == 0 and not msg:
                msg = "Claude Code returned no answer."
            raise ClaudeCodeError(msg or "Claude Code exited with code %s." % code, kind=kind)
        if data.get("is_error"):
            status = data.get("api_error_status")
            msg, kind = _plain_error(str(data.get("result") or err or ""), status)
            raise ClaudeCodeError(msg, status_code=status, kind=kind)
        return data

    def _to_eye_reply(self, data, tools, structured=False):
        usage = data.get("usage") or {}
        model = None
        for mid, mu in (data.get("modelUsage") or {}).items():
            model = (mu or {}).get("canonicalModel") or mid
            break
        u = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cost_usd": float(data.get("total_cost_usd") or 0.0),
            "duration_ms": int(data.get("duration_ms") or 0),
        }
        self.last_usage = u
        s = self.session_usage
        s["calls"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                  "cache_creation_input_tokens"):
            s[k] += u[k]
        s["cost_usd"] += u["cost_usd"]

        stop = data.get("stop_reason")
        reply = {"content": "", "tool_calls": [], "model": model or self.model_name,
                 "usage": u, "stop_reason": stop}
        if stop == "refusal":
            reply["content"] = ("[The model declined this request. Rephrase it around the evidence - "
                                "what the artifacts show - or switch to another model.]")
            reply["refusal"] = True
            return reply

        so = data.get("structured_output")
        if not isinstance(so, dict) and (structured or tools) and isinstance(data.get("result"), str)                 and data["result"].strip().startswith("{"):
            try:
                so = json.loads(data["result"])
            except ValueError:
                so = None
        if (tools or structured) and isinstance(so, dict):
            structured = so
            known = {t.get("name") for t in tools}
            notes = []
            for i, call in enumerate(structured.get("tool_calls") or []):
                name = str((call or {}).get("name") or "").strip()
                args = (call or {}).get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {"value": args}
                if name not in known:
                    notes.append("[Eye ignored a call to an unknown tool '%s'.]" % name)
                    continue
                reply["tool_calls"].append({
                    "id": "cc_%d_%d" % (s["calls"], i), "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)},
                })
            content = str(structured.get("answer") or "")
            if notes:
                content = (content + "\n" if content else "") + "\n".join(notes)
            reply["content"] = content
        else:
            reply["content"] = str(data.get("result") or "")
        if stop == "max_tokens" and reply["content"]:
            reply["content"] += ("\n\n[Output truncated at the model's max output tokens - ask for "
                                 "the remainder or narrow the request.]")
        return reply

    # ---- probes -----------------------------------------------------------
    def version(self) -> str:
        code, out, err = self._run(["--version"], "", 30)
        if code != 0:
            raise ClaudeCodeError((err or out or "claude --version failed").strip()[:300])
        return out.strip()

    def validate_connectivity(self) -> bool:
        """Installed AND signed in: a one-word answer from the smallest model."""
        try:
            self.version()
            code, out, err = self._run(
                ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
                 "--safe-mode", "--strict-mcp-config", "--disable-slash-commands",
                 "--model", "haiku", "Reply with the single word OK."], "", 120)
            self._parse_output(out, err, code)
            self.last_error = ""
            return True
        except FileNotFoundError:
            self.last_error = ("Claude Code was not found. Install it (https://claude.com/claude-code) "
                               "or set its path in Settings -> Eye AI.")
        except ClaudeCodeError as e:
            self.last_error = str(e)
        except Exception as e:  # pragma: no cover - defensive
            self.last_error = "%s: %s" % (type(e).__name__, e)
        return False

    def list_models(self) -> List[str]:
        return list(MODEL_ALIASES) + list(FULL_MODEL_IDS)

    def get_models_with_quota(self) -> List[Dict[str, str]]:
        return [{"id": m, "quota": "Claude plan (Claude Code sign-in)"} for m in self.list_models()]

    def get_context_window(self):
        # Claude 5 models (what the aliases name today) have a 1M window; Eye plans for
        # less, leaving room for Claude Code's own prompt and the session's extra.
        return EYE_CONTEXT_WINDOW
