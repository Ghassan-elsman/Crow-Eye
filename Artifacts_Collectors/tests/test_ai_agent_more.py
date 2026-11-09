"""The other agents on a machine, and the offline copy rules that carry them.

Fixtures are shaped like the records found on a real machine (2026-11-04):
Claude desktop (its session list and agent mode), Codex's thread databases,
Gemini CLI's logs.json, Antigravity, GitHub Copilot CLI, and Roo / Kilo Code.
Each check names what a careless reader gets wrong.
"""
import json
import os
import sqlite3

from Artifacts_Collectors.AI_Agent_Claw import parse_users_root
from Artifacts_Collectors.ai_agent_paths import AI_AGENT_ROOT_PATTERNS, ai_agent_relative_path

USER = "Carol"


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _db(path, ddl, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    for d in ddl:
        c.execute(d)
    for sql, vals in rows:
        c.execute(sql, vals)
    c.commit()
    c.close()


def _machine(root):
    home = os.path.join(root, "Users", USER)
    roam = os.path.join(home, "AppData", "Roaming")
    # Claude desktop: a session it ran (its CLI transcript is absent here),
    # and an agent-mode session with its audit log and an output file
    _w(os.path.join(roam, "Claude", "claude-code-sessions", "a", "b", "local_1.json"), json.dumps(
        {"sessionId": "local_1", "cliSessionId": "cli-1", "cwd": "C:\\proj", "createdAt": 1781100000000,
         "lastActivityAt": 1781100600000, "model": "claude-opus-5-5", "title": "Fix the build"}))
    lam = os.path.join(roam, "Claude", "local-agent-mode-sessions", "a", "b", "local_9")
    _w(os.path.join(lam, ".claude", "projects", "p", "am-1.jsonl"), json.dumps(
        {"type": "user", "uuid": "u1", "timestamp": "2026-06-10T10:00:00Z", "sessionId": "am-1",
         "message": {"role": "user", "content": "Make a report"}}) + "\n")
    _w(os.path.join(lam, "audit.jsonl"), json.dumps(
        {"type": "system", "session_id": "am-1", "permissionMode": "bypassPermissions",
         "model": "claude-opus-5-5", "mcp_servers": [{"name": "files", "status": "connected"}],
         "tools": ["Bash", "Write"]}) + "\n")
    _w(os.path.join(lam, "outputs", "report.md"), "# report")
    _w(os.path.join(lam, ".audit-key"), "SIGNING-KEY")
    # Codex: a thread with no rollout file, read from thread_history
    _db(os.path.join(home, ".codex", "thread_history_1.sqlite"),
        ["CREATE TABLE thread_items (thread_id, turn_id, item_id, rollout_ordinal, created_at_ms, "
         "item_json, item_type, updated_at_ordinal)"],
        [("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)",
          ("th-1", "t1", "i1", 1, 1781200000000, json.dumps({"content": "list the services"}), "userMessage", 1)),
         ("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)",
          ("th-1", "t1", "i2", 2, 1781200005000, json.dumps(
              {"server": "node_repl", "tool": "js", "status": "completed", "durationMs": 640,
               "arguments": {"code": "1+1"}}), "mcpToolCall", 2))])
    _db(os.path.join(home, ".codex", "state_5.sqlite"),
        ["CREATE TABLE threads (id, title, cwd, git_sha, git_origin_url, git_branch, sandbox_policy, "
         "approval_mode, model, cli_version)"],
        [("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)",
          ("th-1", "Services", "C:\\proj", "abc123", "https://git.example/x.git", "main",
           "workspace-write", "on-request", "gpt-5.5-codex", "0.150.0"))])
    # Gemini CLI: logs.json prompts of a session whose chat file is gone
    _w(os.path.join(home, ".gemini", "tmp", "h1", "logs.json"), json.dumps(
        [{"sessionId": "gem-gone", "messageId": 0, "type": "user", "message": "delete the cache",
          "timestamp": "2026-06-12T08:00:00Z"}]))
    # Antigravity: a conversation file, its plan, screenshots kept under another id
    ag = os.path.join(home, ".gemini", "antigravity")
    _db(os.path.join(ag, "conversations", "conv-1.db"),
        ["CREATE TABLE steps (idx INTEGER, step_payload BLOB)"],
        [("INSERT INTO steps VALUES (?, ?)", (1, b"\x0a\x02pb"))])
    _w(os.path.join(ag, "brain", "conv-1", "task.md"), "- [x] open the admin page")
    _w(os.path.join(ag, "brain", "conv-1", "task.md.metadata.json"),
       json.dumps({"artifactType": "ARTIFACT_TYPE_TASK", "updatedAt": "2026-06-13T09:00:00Z"}))
    _w(os.path.join(ag, "browser_recordings", "rec-7", "1781300000000000000.jpg"), "jpg")
    # GitHub Copilot CLI: an events file, a store with a command and its exit
    # code, and a process log named for its PID
    _w(os.path.join(home, ".copilot", "session-state", "cp-1", "events.jsonl"), "\n".join([
        json.dumps({"type": "session.start", "id": "e1", "timestamp": "2026-06-14T10:00:00Z",
                    "data": {"sessionId": "cp-1", "selectedModel": "gpt-5", "copilotVersion": "1.0.4",
                             "context": {"cwd": "C:\\proj", "branch": "main", "repository": "org/x"}}}),
        json.dumps({"type": "user.message", "id": "e2", "timestamp": "2026-06-14T10:00:05Z",
                    "data": {"content": "run the tests"}})]))
    _db(os.path.join(home, ".copilot", "session-store.db"),
        ["CREATE TABLE sessions (id, cwd, repository, host_type, branch, summary, created_at, updated_at)",
         "CREATE TABLE turns (id, session_id, turn_index, user_message, assistant_response, timestamp)",
         "CREATE TABLE session_files (id, session_id, file_path, tool_name, turn_index, first_seen_at)",
         "CREATE TABLE forge_trajectory_events (id, session_id, tool_call_id, turn_index, event_type, "
         "command, output, exit_code, event_key, event_value, created_at)"],
        [("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
          ("cp-1", "C:\\proj", "org/x", "cli", "main", "Run tests", "2026-06-14T10:00:00Z", "2026-06-14T10:05:00Z")),
         ("INSERT INTO turns VALUES (?,?,?,?,?,?)", (1, "cp-1", 0, "run the tests", "ok", "2026-06-14T10:00:05Z")),
         ("INSERT INTO session_files VALUES (?,?,?,?,?,?)",
          (1, "cp-1", "C:\\proj\\app.py", "edit", 0, "2026-06-14T10:01:00Z")),
         ("INSERT INTO forge_trajectory_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          (1, "cp-1", "c1", 0, "shell", "npm test", "1 failing", 1, "", "", "2026-06-14T10:02:00Z"))])
    _w(os.path.join(home, ".copilot", "logs", "process-1781400000000-5150.log"), "log")
    # Roo Code: a task with an Anthropic-format command call and its result
    task = os.path.join(roam, "Code", "User", "globalStorage", "rooveterinaryinc.roo-cline", "tasks", "rt-1")
    _w(os.path.join(task, "api_conversation_history.json"), json.dumps([
        {"role": "user", "ts": 1781500000000, "content": [{"type": "text", "text": "build it"}]},
        {"role": "assistant", "ts": 1781500002000, "content": [
            {"type": "tool_use", "id": "tu1", "name": "execute_command",
             "input": {"command": "npm run build", "cwd": "C:\\proj"}}]},
        {"role": "user", "ts": 1781500009000, "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "built"}]}]))
    _w(os.path.join(task, "history_item.json"), json.dumps(
        {"id": "rt-1", "task": "build it", "workspace": "C:\\proj", "mode": "code", "apiConfigName": "sonnet"}))
    return os.path.join(root, "Users")


def _parse(tmp_path):
    db = os.path.join(str(tmp_path), "case", "Target_Artifacts", "ai_agents.db")
    result = parse_users_root(_machine(str(tmp_path)), db)
    return result, sqlite3.connect(db)


def test_every_agent_on_the_machine_is_read(tmp_path):
    result, c = _parse(tmp_path)
    assert result["errors"] == 0
    got = {(a, app) for a, app in c.execute("SELECT agent, app FROM ai_agent_sessions")}
    assert {("Claude Code", "desktop"), ("Claude Code", "desktop-agent-mode"), ("Codex", "cli"),
            ("Gemini CLI", "cli"), ("Antigravity", "desktop"), ("GitHub Copilot", "cli"),
            ("Roo Code", "vscode")} <= got


def test_desktop_agent_mode_its_audit_and_the_files_it_made(tmp_path):
    _r, c = _parse(tmp_path)
    assert c.execute("SELECT count(*) FROM ai_agent_steps WHERE tool = 'outputs' AND kind = 'file_write' "
                     "AND target LIKE '%report.md'").fetchone()[0] == 1
    s = dict(c.execute("SELECT setting, value FROM ai_agent_settings WHERE scope LIKE 'desktop agent%'"))
    assert s["permissionMode"] == "bypassPermissions" and s["mcp_server files"] == "connected"
    dump = "\n".join(str(v) for t in ("ai_agent_settings", "ai_agent_steps") for r in
                     c.execute("SELECT * FROM %s" % t) for v in r)
    assert "SIGNING-KEY" not in dump                               # the audit key is never read


def test_codex_thread_with_no_rollout_and_its_repository(tmp_path):
    _r, c = _parse(tmp_path)
    row = c.execute("SELECT kind, tool, duration_ms FROM ai_agent_steps WHERE session_id = 'th-1' "
                    "AND kind != 'prompt'").fetchone()
    assert row == ("mcp", "mcp__node_repl__js", 640)
    assert c.execute("SELECT git_sha, git_origin, sandbox_policy FROM ai_agent_sessions "
                     "WHERE session_id = 'th-1'").fetchone() == ("abc123", "https://git.example/x.git",
                                                                 "workspace-write")


def test_gemini_prompts_whose_chat_file_is_gone(tmp_path):
    _r, c = _parse(tmp_path)
    assert c.execute("SELECT text FROM ai_agent_steps WHERE session_id = 'gem-gone'").fetchone() == \
        ("delete the cache",)


def test_antigravity_plans_and_screenshots_kept_under_another_id(tmp_path):
    _r, c = _parse(tmp_path)
    assert c.execute("SELECT title FROM ai_agent_sessions WHERE session_id = 'conv-1'").fetchone()[0] \
        .startswith("[1 steps")
    assert c.execute("SELECT kind FROM ai_agent_steps WHERE session_id = 'conv-1' AND kind = 'plan'"
                     ).fetchone() == ("plan",)
    shot = c.execute("SELECT session_id, ts FROM ai_agent_steps WHERE kind = 'screenshot'").fetchone()
    assert shot[0] == "rec-7" and shot[1] == "2026-06-12 21:33:20"   # time from the file name


def test_copilot_prompts_files_commands_exit_codes_and_pid(tmp_path):
    _r, c = _parse(tmp_path)
    prompts = c.execute("SELECT count(*) FROM ai_agent_steps WHERE agent = 'GitHub Copilot' "
                        "AND kind = 'prompt'").fetchone()[0]
    assert prompts == 1                                           # events file, not again from turns
    assert c.execute("SELECT command, program, exit_code FROM ai_agent_steps WHERE agent = 'GitHub Copilot' "
                     "AND kind = 'command'").fetchone() == ("npm test", "npm", 1)
    assert c.execute("SELECT target FROM ai_agent_steps WHERE agent = 'GitHub Copilot' AND kind = 'file_edit'"
                     ).fetchone() == ("C:\\proj\\app.py",)
    assert c.execute("SELECT pid FROM ai_agent_processes WHERE agent = 'GitHub Copilot'").fetchone() == (5150,)


def test_roo_code_command_and_its_duration(tmp_path):
    _r, c = _parse(tmp_path)
    assert c.execute("SELECT command, program, duration_ms FROM ai_agent_steps WHERE agent = 'Roo Code' "
                     "AND kind = 'command'").fetchone() == ("npm run build", "npm", 7000)
    assert c.execute("SELECT project_path, model FROM ai_agent_sessions WHERE agent = 'Roo Code'"
                     ).fetchone() == ("C:\\proj", "sonnet")


def test_offline_copy_takes_every_source_and_no_secret(tmp_path):
    users = _machine(str(tmp_path))
    wanted, refused = [], []
    for d, _s, files in os.walk(users):
        for f in files:
            p = os.path.join(d, f)
            (wanted if ai_agent_relative_path(p) else refused).append(os.path.relpath(p, users))
    assert any(p.endswith("audit.jsonl") for p in wanted)
    assert any("browser_recordings" in p for p in wanted)
    assert any(p.endswith("api_conversation_history.json") for p in wanted)
    assert any(p.endswith("session-store.db") for p in wanted)
    assert [p for p in refused if p.endswith(".audit-key")]
    assert not [p for p in wanted if p.endswith(".audit-key")]
    # Every root is joined to "Users\<name>": a pattern missing its leading
    # backslash names a folder that cannot exist ("Users\CarolAppData").
    assert all(p.startswith("\\") for p in AI_AGENT_ROOT_PATTERNS)


def test_a_projects_own_settings_are_never_read_from_this_machine(tmp_path):
    """An offline profile names projects by their paths on the evidence
    machine; the same path on the analyst's disk is not evidence."""
    users = _machine(str(tmp_path))
    outside = os.path.join(str(tmp_path), "analyst_disk", "proj")
    _w(os.path.join(outside, ".claude", "settings.local.json"),
       json.dumps({"permissions": {"allow": ["Bash(rm -rf:*)"]}}))
    _w(os.path.join(users, USER, ".claude", "projects", "x", "s1.jsonl"), json.dumps(
        {"type": "user", "uuid": "u1", "timestamp": "2026-06-10T10:00:00Z", "sessionId": "s1",
         "cwd": outside, "message": {"role": "user", "content": "hi"}}) + "\n")
    db = os.path.join(str(tmp_path), "case", "Target_Artifacts", "ai_agents.db")
    parse_users_root(users, db)
    c = sqlite3.connect(db)
    assert c.execute("SELECT count(*) FROM ai_agent_settings WHERE value LIKE '%rm -rf%'").fetchone()[0] == 0
