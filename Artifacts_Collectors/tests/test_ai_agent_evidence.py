"""What Claude Code keeps besides its conversations, and what the agent ran.

Checked through a profile shaped like the real one (this machine, 2026-11-04):
each check names what a careless parser gets wrong.

- the program a command started, as Prefetch names it (not the shell the tool
  runs in, not a builtin, not the body of a here-document);
- a background command's exit code, from the task's output file;
- a foreground command's duration, from its call and result times;
- browser control is told apart from other tools;
- which process ran which session (.claude\\sessions\\<pid>.json);
- every saved copy of an edited file, with the hash of the copy;
- prompts kept in history.jsonl for a session whose transcript is gone;
- todos, plans and background jobs;
- permissions, hooks and MCP servers - with no secret value in any row, and the
  credential file never opened;
- a second parse adds nothing.
"""
import hashlib
import json
import os
import sqlite3

from Artifacts_Collectors.AI_Agent_Claw import parse_users_root, save_versions_into_case
from Artifacts_Collectors.ai_agent_programs import program_of

SID = "99999999-8888-7777-6666-555555555555"
GONE = "dddddddd-0000-0000-0000-000000000000"
SECRET = "ghp_PLANTEDplantedPLANTEDplanted9999"
TOKEN = "sk-ant-api03-PLANTEDPLANTEDPLANTED9999"


def _write(path, data, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if binary else "w"
    with open(path, mode, **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(data)


def _line(typ, uuid, ts, message, **extra):
    d = {"type": typ, "uuid": uuid, "timestamp": ts, "sessionId": SID, "cwd": "C:\\work",
         "version": "2.1.300", "entrypoint": "cli", "message": message}
    d.update(extra)
    return json.dumps(d)


def _profile(root):
    users = os.path.join(root, "Users")
    home = os.path.join(users, "Bob")
    claude = os.path.join(home, ".claude")
    lines = [
        json.dumps({"type": "file-history-snapshot", "messageId": "m0", "snapshot": {
            "messageId": "m0", "trackedFileBackups": {
                "work\\app.py": {"backupFileName": "aaaa@v1", "version": 1,
                                 "backupTime": "2026-06-10T14:00:01.000Z", "realParentDir": "C:\\work"},
                "work\\new.py": {"backupFileName": None, "version": 1,
                                 "backupTime": "2026-06-10T14:00:01.000Z"}}}}),
        _line("user", "u1", "2026-06-10T14:00:00.000Z", {"role": "user", "content": "Build it"}),
        _line("assistant", "a1", "2026-06-10T14:00:05.000Z", {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t_fg", "name": "Bash",
             "input": {"command": "cd C:/work && python -m pytest -q 2>&1 | tail -3"}},
            {"type": "tool_use", "id": "t_bg", "name": "PowerShell",
             "input": {"command": "& \"C:\\Tools\\build.exe\" --all", "run_in_background": True}},
            {"type": "tool_use", "id": "t_web", "name": "mcp__claude-in-chrome__navigate",
             "input": {"url": "https://example.test/admin"}},
            {"type": "tool_use", "id": "t_doc", "name": "Bash",
             "input": {"command": "python - <<'EOF'\nimport os\nos.remove('x')\nEOF"}}]}),
        _line("user", "u2", "2026-06-10T14:00:07.500Z", {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t_fg", "content": "3 passed"}]},
            toolUseResult={"stdout": "3 passed", "interrupted": False}),
        _line("user", "u3", "2026-06-10T14:00:08.000Z", {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t_bg", "content": "started"}]},
            toolUseResult={"backgroundTaskId": "btask42", "interrupted": False}),
    ]
    _write(os.path.join(claude, "projects", "C--work", SID + ".jsonl"), "\n".join(lines) + "\n")
    _write(os.path.join(claude, "file-history", SID, "aaaa@v1"), b"print('before the edit')\n", True)
    _write(os.path.join(home, "AppData", "Local", "Temp", "claude", "C--work", SID, "tasks",
                        "btask42.output"), "building...\n[exited with code 3]\n")
    _write(os.path.join(claude, "sessions", "4242.json"), json.dumps(
        {"pid": 4242, "sessionId": SID, "cwd": "C:\\work", "startedAt": 1781100000000,
         "procStart": "133999", "version": "2.1.300", "kind": "interactive", "entrypoint": "cli"}))
    _write(os.path.join(claude, "tasks", SID, "1.json"), json.dumps(
        {"id": "1", "subject": "Run the build", "description": "then fix", "status": "completed"}))
    _write(os.path.join(claude, "plans", "brave-fox.md"), "# Plan\nDelete the old builds.\n")
    _write(os.path.join(claude, "jobs", "job7", "state.json"), json.dumps(
        {"state": "done", "detail": "nightly sweep", "cwd": "C:\\work"}))
    _write(os.path.join(claude, "jobs", "job7", "timeline.jsonl"),
           json.dumps({"at": "2026-06-11T01:00:00.000Z", "state": "running", "detail": "started"}) + "\n")
    _write(os.path.join(claude, "history.jsonl"), "\n".join([
        json.dumps({"display": "Build it", "timestamp": 1781100000000, "project": "C:\\work",
                    "sessionId": SID}),
        json.dumps({"display": "wipe the logs", "timestamp": 1781000000000, "project": "C:\\old",
                    "sessionId": GONE})]) + "\n")
    _write(os.path.join(claude, "settings.local.json"), json.dumps({
        "permissions": {"allow": ["Bash(git push:*)"], "deny": ["Read(.env)"]},
        "hooks": {"PostToolUse": [{"hooks": [{"type": "command",
                                              "command": "curl -H 'Authorization: Bearer %s' x" % TOKEN}]}]}}))
    _write(os.path.join(home, ".claude.json"), json.dumps({"mcpServers": {"gh": {
        "command": "npx", "args": ["-y", "server-github"], "env": {"GITHUB_TOKEN": SECRET}}}}))
    _write(os.path.join(claude, ".credentials.json"), json.dumps({"token": SECRET}))
    return users


def _parse(tmp_path):
    users = _profile(str(tmp_path))
    db = os.path.join(str(tmp_path), "case", "Target_Artifacts", "ai_agents.db")
    return parse_users_root(users, db), sqlite3.connect(db), db


def test_programs_are_named_as_windows_names_them():
    assert program_of("cd C:/work && python -m pytest -q 2>&1 | tail -3") == "python, tail"
    assert program_of('& "C:\\Tools\\build.exe" --all') == "build"
    assert program_of("python - <<'EOF'\nimport os\nos.remove('x')\nEOF") == "python"
    assert program_of('powershell -NoProfile -Command "Get-Process"') == "powershell"
    assert program_of('cmd /c "npm run build"') == "cmd, npm"
    assert program_of('python -c "import os\ndef f(): pass" | grep x') == "python, grep"
    assert program_of("echo hi > out.txt; cd x; Get-ChildItem") == ""        # nothing started


def test_commands_carry_program_exit_code_and_duration(tmp_path):
    result, conn, _db = _parse(tmp_path)
    assert result["errors"] == 0
    got = {r[0]: r[1:] for r in conn.execute(
        "SELECT step_id, kind, program, exit_code, duration_ms FROM ai_agent_steps WHERE session_id = ?",
        (SID,))}
    assert got["t_fg"] == ("command", "python, tail", None, 2500)
    assert got["t_bg"] == ("command", "build", 3, None)            # from the task's output file
    assert got["t_web"][0] == "browser"
    assert got["t_doc"][1] == "python"                             # not 'import' or 'os.remove'


def test_the_process_that_ran_the_session(tmp_path):
    _r, conn, _db = _parse(tmp_path)
    assert conn.execute("SELECT pid, session_id, kind FROM ai_agent_processes").fetchall() == \
        [(4242, SID, "interactive")]
    assert conn.execute("SELECT pid FROM ai_agent_sessions WHERE session_id = ?", (SID,)).fetchone() == (4242,)


def test_saved_copies_are_listed_hashed_and_saved_only_when_asked(tmp_path):
    _r, conn, db = _parse(tmp_path)
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT file_path, backup_path, sha1, in_case_path FROM ai_agent_file_versions")}
    backup, sha1, in_case = rows["C:\\work\\app.py"]
    assert sha1 == hashlib.sha1(b"print('before the edit')\n").hexdigest() and in_case == ""
    assert rows[os.path.join(str(tmp_path), "Users", "Bob", "work\\new.py")][0] == ""   # new file: no copy
    assert not os.path.isdir(os.path.join(str(tmp_path), "case", "AI_Agents"))           # off by default
    copied, failed = save_versions_into_case(db)
    assert (copied, failed) == (1, 0)
    dest = sqlite3.connect(db).execute(
        "SELECT in_case_path FROM ai_agent_file_versions WHERE sha1 = ?", (sha1,)).fetchone()[0]
    assert dest.startswith(os.path.join(str(tmp_path), "case", "AI_Agents", "file_versions"))
    assert open(dest, "rb").read() == b"print('before the edit')\n"


def test_prompts_of_a_deleted_transcript_todos_plans_and_jobs(tmp_path):
    _r, conn, _db = _parse(tmp_path)
    gone = conn.execute("SELECT title, project_path FROM ai_agent_sessions WHERE session_id = ?",
                        (GONE,)).fetchone()
    assert gone and gone[0].startswith("[transcript not found")
    assert conn.execute("SELECT text FROM ai_agent_steps WHERE session_id = ?", (GONE,)).fetchone() == \
        ("wipe the logs",)
    # the session whose transcript exists does not get a second copy of its prompt
    assert conn.execute("SELECT count(*) FROM ai_agent_steps WHERE step_id LIKE 'history:%' "
                        "AND session_id = ?", (SID,)).fetchone()[0] == 0
    kinds = dict(conn.execute("SELECT kind, count(*) FROM ai_agent_steps "
                              "WHERE kind IN ('todo', 'plan', 'job') GROUP BY kind").fetchall())
    assert kinds == {"todo": 1, "plan": 1, "job": 1}
    assert conn.execute("SELECT app FROM ai_agent_sessions WHERE session_id = 'job:job7'").fetchone() == ("job",)


def test_permissions_hooks_and_mcp_servers_with_no_secret(tmp_path):
    _r, conn, _db = _parse(tmp_path)
    rows = conn.execute("SELECT setting, value FROM ai_agent_settings").fetchall()
    settings = {(s, v) for s, v in rows}
    assert ("permissions.allow", "Bash(git push:*)") in settings
    assert ("permissions.deny", "Read(.env)") in settings
    assert any(s == "hook PostToolUse" for s, _v in rows)
    assert ("mcp_server gh", "npx -y server-github  [env: GITHUB_TOKEN]") in settings
    dump = "\n".join(str(v) for t in ("ai_agent_settings", "ai_agent_steps", "ai_agent_sessions")
                     for row in conn.execute("SELECT * FROM %s" % t) for v in row)
    assert SECRET not in dump and TOKEN not in dump


def test_a_second_parse_adds_nothing(tmp_path):
    users = _profile(str(tmp_path))
    db = os.path.join(str(tmp_path), "case", "Target_Artifacts", "ai_agents.db")
    parse_users_root(users, db)
    conn = sqlite3.connect(db)
    tables = ("ai_agent_sessions", "ai_agent_steps", "ai_agent_file_versions", "ai_agent_processes",
              "ai_agent_settings")
    before = {t: conn.execute("SELECT count(*) FROM %s" % t).fetchone()[0] for t in tables}
    conn.close()
    second = parse_users_root(users, db)
    conn = sqlite3.connect(db)
    after = {t: conn.execute("SELECT count(*) FROM %s" % t).fetchone()[0] for t in tables}
    assert after == before and second["inserted"] == 0
