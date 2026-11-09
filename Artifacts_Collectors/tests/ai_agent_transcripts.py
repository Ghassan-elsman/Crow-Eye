"""Synthetic AI agent session records, in the shapes the agents write.

Shared by the parser's tests and the UBA rule tests: a Users folder holding
one Claude Code session (with a sub-agent), one Gemini CLI chat and one Codex
rollout, so the parser and the rules are checked through the same files a
real profile holds. The secrets planted here must never reach a row.
"""

import json
import os

PLANTED_SECRETS = ("sk-ant-api03-PLANTEDPLANTEDPLANTED0123", "ghp_PLANTEDplantedPLANTEDplanted0123")
CLAUDE_SESSION = "11111111-2222-3333-4444-555555555555"
CWD = "C:\\Users\\Alice\\work\\shop"


def _jsonl(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def _claude_line(typ, uuid, ts, message, **extra):
    line = {"type": typ, "uuid": uuid, "timestamp": ts, "sessionId": CLAUDE_SESSION,
            "cwd": CWD, "version": "2.1.300", "entrypoint": "cli", "gitBranch": "main",
            "isSidechain": False, "message": message}
    line.update(extra)
    return line


def write_users(root):
    """Write the records under root\\Users\\Alice; returns the Users folder."""
    users = os.path.join(root, "Users")
    home = os.path.join(users, "Alice")
    proj = os.path.join(home, ".claude", "projects", "C--Users-Alice-work-shop")
    _jsonl(os.path.join(proj, CLAUDE_SESSION + ".jsonl"), [
        {"type": "api-request", "body": "never decoded"},
        {"type": "ai-title", "aiTitle": "Fix the checkout", "sessionId": CLAUDE_SESSION},
        {"type": "permission-mode", "permissionMode": "auto", "sessionId": CLAUDE_SESSION},
        _claude_line("user", "u1", "2026-06-10T14:00:00.000Z",
                     {"role": "user", "content": "Fix the failing checkout test"}),
        _claude_line("assistant", "a1", "2026-06-10T14:00:05.000Z",
                     {"role": "assistant", "model": "claude-opus-5-5", "content": [
                         {"type": "text", "text": "Running the tests first."},
                         {"type": "tool_use", "id": "toolu_1", "name": "Bash",
                          "input": {"command": "cd \"C:/Users/Alice/work/shop\" && pytest -q",
                                    "description": "Run tests"}}]}),
        _claude_line("user", "u2", "2026-06-10T14:00:09.000Z",
                     {"role": "user", "content": [
                         {"type": "tool_result", "tool_use_id": "toolu_1",
                          "content": "1 failed; token=" + PLANTED_SECRETS[1]}]},
                     toolUseResult={"stdout": "1 failed", "interrupted": False}),
        _claude_line("assistant", "a2", "2026-06-10T14:01:00.000Z",
                     {"role": "assistant", "model": "claude-opus-5-5", "content": [
                         {"type": "tool_use", "id": "toolu_2", "name": "Edit",
                          "input": {"file_path": CWD + "\\cart.py", "old_string": "a",
                                    "new_string": "b"}},
                         {"type": "tool_use", "id": "toolu_3", "name": "Bash",
                          "input": {"command": "curl -H 'x-api-key: " + PLANTED_SECRETS[0]
                                               + "' https://api.example.test"}}]}),
        _claude_line("user", "u3", "2026-06-10T14:05:00.000Z",
                     {"role": "user", "content": "<task-notification>done</task-notification>"}),
        _claude_line("assistant", "a3", "2026-06-10T14:05:30.000Z",
                     {"role": "assistant", "model": "claude-opus-5-5", "content": [
                         {"type": "tool_use", "id": "toolu_4", "name": "Bash",
                          "input": {"command": "git log -1"}}]}),
        _claude_line("user", "u4", "2026-06-10T14:06:00.000Z",
                     {"role": "user", "content": "<bash-input>git push</bash-input>"}),
    ])
    _jsonl(os.path.join(proj, CLAUDE_SESSION, "subagents", "agent-abc.jsonl"), [
        _claude_line("user", "s1", "2026-06-10T14:02:00.000Z",
                     {"role": "user", "content": "Search the repo for cart usages"}, isSidechain=True),
        _claude_line("assistant", "s2", "2026-06-10T14:02:03.000Z",
                     {"role": "assistant", "model": "claude-opus-5-5", "content": [
                         {"type": "tool_use", "id": "toolu_s1", "name": "Bash",
                          "input": {"command": "grep -rn cart ."}}]}, isSidechain=True),
    ])
    chats = os.path.join(home, ".gemini", "tmp", "abcdef0123456789", "chats")
    os.makedirs(chats, exist_ok=True)
    with open(os.path.join(chats, "session-2026-06-11T09-00-aaaa.json"), "w", encoding="utf-8") as f:
        json.dump({"sessionId": "gem-1", "projectHash": "abcdef0123456789",
                   "startTime": "2026-06-11T09:00:00Z", "messages": [
                       {"id": "m1", "timestamp": "2026-06-11T09:00:00Z", "type": "user",
                        "content": "Make a backup folder"},
                       {"id": "m2", "timestamp": "2026-06-11T09:00:04Z", "type": "gemini",
                        "content": "", "model": "gemini-3-pro", "toolCalls": [
                            {"id": "tc1", "name": "run_shell_command",
                             "args": {"command": "mkdir backup"}, "status": "success",
                             "timestamp": "2026-06-11T09:00:05Z",
                             "result": [{"functionResponse": {"response": {"output": "ok"}}}]}]}]}, f)
    _jsonl(os.path.join(home, ".codex", "sessions", "2026", "06", "12",
                        "rollout-2026-06-12T08-00-00-cdx1.jsonl"), [
        {"timestamp": "2026-06-12T08:00:00Z", "type": "session_meta",
         "payload": {"id": "cdx-1", "cwd": CWD, "originator": "codex_cli_rs", "cli_version": "0.150.0",
                     "source": "cli"}},
        {"timestamp": "2026-06-12T08:00:00Z", "type": "turn_context",
         "payload": {"cwd": CWD, "model": "gpt-5.5-codex", "approval_policy": "never",
                     "sandbox_policy": {"type": "danger-full-access"}}},
        {"timestamp": "2026-06-12T08:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "id": "c1",
                     "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
        {"timestamp": "2026-06-12T08:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "id": "c2",
                     "content": [{"type": "input_text", "text": "List the large files"}]}},
        {"timestamp": "2026-06-12T08:00:03Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell", "call_id": "call_1",
                     "arguments": json.dumps({"command": ["powershell", "-c", "dir -s"], "workdir": CWD})}},
        {"timestamp": "2026-06-12T08:00:04Z", "type": "response_item",
         "payload": {"type": "function_call_output", "call_id": "call_1", "output": "big.iso"}},
    ])
    # A credential file beside the records: never opened by the parser.
    with open(os.path.join(home, ".codex", "auth.json"), "w", encoding="utf-8") as f:
        json.dump({"OPENAI_API_KEY": PLANTED_SECRETS[0]}, f)
    return users
