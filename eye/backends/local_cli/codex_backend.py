"""
Codex CLI backend: Eye on the analyst's own OpenAI Codex sign-in.

`codex exec` runs one turn per Eye call:
    codex exec --json --output-schema <schema> --ephemeral --skip-git-repo-check
               --ignore-user-config -s read-only -C <empty dir> [-m model]
               [-c model_reasoning_effort=...] -
with the prompt on stdin. Facts proven against codex-cli 0.153.4 (2026-11-02):
- `--output-schema` makes the final agent message JSON in that shape. OpenAI's
  strict schemas allow no free-form object, so a tool call carries its arguments
  as a JSON STRING (`arguments_json`), parsed here.
- `--json` streams JSONL events: `item.completed` (agent_message text, or a
  command_execution / file_change / web_search the agent did), `turn.completed`
  with usage (input, cached_input, output, reasoning tokens), `error`/`turn.failed`.
- Codex cannot be told to have no tools, unlike Claude Code. It runs in an empty
  folder with a read-only sandbox, and if it tries ANY command, file change, MCP
  call or web search the turn is stopped: the evidence must be read through Eye's
  own tools, guardrails and seal, never around them.
- OpenAI caches any repeated prompt prefix of 1,024+ tokens, so the conversation
  sent as one growing prompt still reuses the cache across Eye's steps.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import queue
from typing import Any, Dict, List, Optional

from eye.backends.base import LLMBackend, split_step_context
from eye.backends.local_cli.claude_code_backend import (
    ASK_AGAIN, ClaudeCodeBackend, ClaudeCodeError, _plain_error, only_unavailable_tools)

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
_EFFORT_TO_CODEX = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
DEFAULT_TIMEOUT_S = 600
CODEX_CONTEXT_WINDOW = 200_000

# Strict (OpenAI structured-output) form of Eye's reply.
CODEX_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "arguments_json": {"type": "string"}},
                "required": ["name", "arguments_json"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "tool_calls"],
    "additionalProperties": False,
}

# Anything the agent DOES (rather than says) - never allowed in Eye.
_ACTION_ITEMS = {"command_execution", "file_change", "mcp_tool_call", "web_search", "patch_apply"}


class CodexError(ClaudeCodeError):
    """A failed Codex call (same fields, so the router and doctor treat it alike)."""


class CodexBackend(LLMBackend):
    """Eye's model calls through the local `codex exec`."""

    def __init__(self, executable_path: str = "", model_name: str = "",
                 effort: Optional[str] = None, timeout_s: Optional[int] = None):
        self.executable_path = executable_path or ""
        mn = (model_name or "").strip()
        self.model_name = "" if mn in ("", "default", "cli-default-model") or "CLI" in mn else mn
        self.effort = effort if effort in EFFORT_LEVELS else None
        self.timeout_s = int(timeout_s or DEFAULT_TIMEOUT_S)
        self.logger = logging.getLogger(__name__)
        self.last_error = ""
        self.backend_type = "codex_cli"

    # ---- launching --------------------------------------------------------
    def _command_prefix(self) -> List[str]:
        exe = (self.executable_path or "").strip().strip('"') or shutil.which("codex") or "codex"
        low = exe.lower()
        if os.name == "nt" and not os.path.splitext(exe)[1]:
            for ext in (".cmd", ".exe", ".bat"):
                if os.path.exists(exe + ext):
                    exe, low = exe + ext, (exe + ext).lower()
                    break
        if os.name == "nt" and low.endswith((".cmd", ".bat")):
            return ["cmd", "/c", exe]
        if low.endswith(".py"):
            import sys
            return [sys.executable, exe]
        return [exe]

    def _args(self, schema_path: str, workdir: str) -> List[str]:
        args = ["exec", "--json", "--output-schema", schema_path, "--ephemeral",
                "--skip-git-repo-check", "--ignore-user-config", "-s", "read-only", "-C", workdir]
        if self.model_name:
            args += ["-m", self.model_name]
        if self.effort:
            args += ["-c", 'model_reasoning_effort="%s"' % _EFFORT_TO_CODEX[self.effort]]
        return args + ["-"]

    def _run(self, prompt: str) -> Dict[str, Any]:
        workdir = tempfile.mkdtemp(prefix="eye_codex_")
        fd, schema_path = tempfile.mkstemp(prefix="eye_codex_schema_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(CODEX_REPLY_SCHEMA, fh)
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = ClaudeCodeBackend.child_environment()
        env.pop("OPENAI_API_KEY", None)          # the Codex sign-in, not an API key
        proc = subprocess.Popen(self._command_prefix() + self._args(schema_path, workdir),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=workdir, **kwargs)
        lines: "queue.Queue" = queue.Queue()
        err_tail: List[str] = []

        def pump():
            for raw in iter(proc.stdout.readline, b""):
                lines.put(raw)
            lines.put(None)

        def drain():
            for raw in iter(proc.stderr.readline, b""):
                err_tail.append(raw.decode("utf-8", "replace").rstrip())
                del err_tail[:-40]

        threading.Thread(target=pump, daemon=True).start()
        threading.Thread(target=drain, daemon=True).start()
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
            import time
            deadline = time.monotonic() + self.timeout_s
            message, usage, failure = None, {}, None
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise CodexError("Codex did not answer within %d s." % self.timeout_s, kind="timeout")
                try:
                    raw = lines.get(timeout=min(left, 5.0))
                except queue.Empty:
                    continue
                if raw is None:
                    break
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                kind = ev.get("type")
                item = ev.get("item") or {}
                if kind in ("item.started", "item.completed") and item.get("type") in _ACTION_ITEMS:
                    raise CodexError(
                        "Codex tried to act on its own (%s) instead of asking the Eye's tools; the turn "
                        "was stopped so the evidence is only read through the Eye." % item.get("type"),
                        kind="action")
                if kind == "item.completed" and item.get("type") == "agent_message":
                    message = item.get("text") or ""
                elif kind == "turn.completed":
                    usage = ev.get("usage") or {}
                elif kind in ("error", "turn.failed"):
                    failure = (ev.get("message") or (ev.get("error") or {}).get("message")
                               or json.dumps(ev)[:300])
            if failure and message is None:
                msg, k = _plain_error(failure, None)
                raise CodexError(msg if k != "other" else "Codex returned an error: %s" % failure[:400], kind=k)
            if message is None:
                tail = "\n".join(err_tail)[-600:]
                msg, k = _plain_error(tail or "Codex returned no answer.", None)
                raise CodexError(msg, kind=k)
            return {"message": message, "usage": usage}
        finally:
            if proc.poll() is None:
                try:
                    from utils.concurrency.process_tree import kill_tree
                    kill_tree(proc.pid, grace=1.0)
                except Exception:
                    proc.kill()
            for path in (schema_path,):
                try:
                    os.remove(path)
                except OSError:
                    pass
            shutil.rmtree(workdir, ignore_errors=True)

    # ---- the call ---------------------------------------------------------
    def generate(self, system_prompt, user_message, tools=None, history=None, gen_params=None):
        try:
            core, step = split_step_context(system_prompt or "")
            if tools:
                tool_text = ClaudeCodeBackend.tool_instructions(tools).replace(
                    '{"name": <tool name>, "arguments": {...}}',
                    '{"name": <tool name>, "arguments_json": "<the arguments as a JSON object, in a string>"}')
            else:
                tool_text = "\n[No tools this turn: reply in `answer`; `tool_calls` stays empty.]"
            instructions = core + "\n" + tool_text
            instructions += ("\n\nNever run commands, read files or browse yourself: everything you know "
                             "about the case comes from the Eye's tools, which you request in `tool_calls`.")
            prompt = ("<instructions>\n%s\n</instructions>\n\n%s"
                      % (instructions, ClaudeCodeBackend.render_transcript(history, user_message, step)))
            out = self._run(prompt)
            reply = self._to_eye_reply(out, tools)
            if only_unavailable_tools(reply):
                out = self._run(prompt + "\n\n" + ASK_AGAIN)
                reply = self._to_eye_reply(out, tools)
            return reply
        except ClaudeCodeError as e:
            self.last_error = str(e)
            self.logger.error("Codex failure: %s", e)
            raise
        except FileNotFoundError as e:
            self.last_error = "Codex was not found. Install it (npm i -g @openai/codex) or set its path."
            raise CodexError(self.last_error, kind="missing") from e

    def _to_eye_reply(self, out, tools):
        u = out.get("usage") or {}
        cached = int(u.get("cached_input_tokens") or 0)
        usage = self.record_usage(max(0, int(u.get("input_tokens") or 0) - cached),
                                  int(u.get("output_tokens") or 0) + int(u.get("reasoning_output_tokens") or 0),
                                  cache_read=cached, model=self.model_name or "codex default")
        reply = {"content": "", "tool_calls": [], "usage": usage, "model": self.model_name or "codex default"}
        text = (out.get("message") or "").strip()
        try:
            data = json.loads(text)
        except ValueError:
            reply["content"] = text
            return reply
        known = {t.get("name") for t in (tools or [])}
        notes = []
        for i, call in enumerate(data.get("tool_calls") or []):
            name = str(call.get("name") or "").strip()
            if name not in known:
                notes.append("[Eye ignored a call to an unknown tool '%s'.]" % name)
                continue
            raw = call.get("arguments_json") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                args = {"value": raw}
            reply["tool_calls"].append({"id": "cx_%d_%d" % (self.session_usage["calls"], i),
                                        "type": "function",
                                        "function": {"name": name,
                                                     "arguments": json.dumps(args or {}, ensure_ascii=False)}})
        content = str(data.get("answer") or "")
        reply["content"] = content + ("\n" + "\n".join(notes) if notes else "")
        return reply

    # ---- probes -----------------------------------------------------------
    def validate_connectivity(self) -> bool:
        try:
            out = self._run("Reply with the word OK in `answer`; leave `tool_calls` empty.")
            self.last_error = ""
            return bool(out.get("message"))
        except FileNotFoundError:
            self.last_error = "Codex was not found. Install it (npm i -g @openai/codex) or set its path."
        except ClaudeCodeError as e:
            self.last_error = str(e)
        return False

    def list_models(self) -> List[str]:
        return ["default"]

    def get_models_with_quota(self) -> List[Dict[str, str]]:
        return [{"id": "default", "quota": "ChatGPT plan (Codex sign-in)"}]

    def get_context_window(self):
        return CODEX_CONTEXT_WINDOW
