"""AI_Agent_Claw: the three agents' session records into ai_agents.db.

Checked through files shaped like the real ones (ai_agent_transcripts.py):
who said what, which commands the agent ran, what a person typed, that
secrets never reach a row, and that a second parse adds nothing.
"""
import os
import sqlite3

from Artifacts_Collectors.AI_Agent_Claw import mask_secrets, parse_users_root, tool_kind
from Artifacts_Collectors.tests.ai_agent_transcripts import CLAUDE_SESSION, PLANTED_SECRETS, write_users


def _parse(tmp_path):
    users = write_users(str(tmp_path))
    db = os.path.join(str(tmp_path), "Target_Artifacts", "ai_agents.db")
    return parse_users_root(users, db), sqlite3.connect(db)


def test_steps_are_attributed_to_who_took_them(tmp_path):
    result, conn = _parse(tmp_path)
    assert result["success"] and result["errors"] == 0
    rows = conn.execute("SELECT agent, role, kind, command FROM ai_agent_steps "
                        "WHERE session_id = ? ORDER BY ts, rowid", (CLAUDE_SESSION,)).fetchall()
    kinds = [(r[1], r[2]) for r in rows]
    assert ("user", "prompt") in kinds
    assert ("assistant", "command") in kinds and ("assistant", "file_edit") in kinds
    # A background task's notice is the program's, and `!git push` is the person's command.
    assert ("system", "notice") in kinds
    assert ("user", "command", "git push") in [(r[1], r[2], r[3]) for r in rows]
    # The sub-agent's instruction came from the main agent, not the person.
    sub = conn.execute("SELECT role, kind FROM ai_agent_steps WHERE session_id LIKE ? AND kind = 'prompt'",
                       (CLAUDE_SESSION + "/%",)).fetchall()
    assert sub == [("agent", "prompt")]


def test_sessions_carry_project_model_and_counts(tmp_path):
    _, conn = _parse(tmp_path)
    got = {r[0]: r[1:] for r in conn.execute(
        "SELECT agent, project_path, model, approval_mode, prompts, commands, file_changes, title "
        "FROM ai_agent_sessions WHERE parent_session_id = ''")}
    assert got["Claude Code"] == ("C:\\Users\\Alice\\work\\shop", "claude-opus-5-5", "auto", 1, 3, 1,
                                  "Fix the checkout")
    assert got["Gemini CLI"][1:5] == ("gemini-3-pro", "", 1, 1)
    assert got["Codex"][:5] == ("C:\\Users\\Alice\\work\\shop", "gpt-5.5-codex",
                                "never / sandbox danger-full-access", 1, 1)
    # Codex's injected environment block is not a request.
    assert conn.execute("SELECT count(*) FROM ai_agent_steps WHERE agent = 'Codex' AND kind = 'prompt'"
                        ).fetchone()[0] == 1
    assert conn.execute("SELECT command FROM ai_agent_steps WHERE agent = 'Codex' AND kind = 'command'"
                        ).fetchone()[0] == "powershell -c dir -s"


def test_no_secret_reaches_a_row_and_credentials_are_not_read(tmp_path):
    _, conn = _parse(tmp_path)
    dump = "\n".join(str(v) for row in conn.execute("SELECT * FROM ai_agent_steps") for v in row)
    dump += "\n".join(str(v) for row in conn.execute("SELECT * FROM ai_agent_sessions") for v in row)
    for secret in PLANTED_SECRETS:
        assert secret not in dump
    assert "[masked: anthropic key]" in dump and "[masked: github token]" in dump
    assert "auth.json" not in dump


def test_a_second_parse_adds_nothing(tmp_path):
    first, conn = _parse(tmp_path)
    users = os.path.join(str(tmp_path), "Users")
    db = os.path.join(str(tmp_path), "Target_Artifacts", "ai_agents.db")
    before = conn.execute("SELECT count(*) FROM ai_agent_steps").fetchone()[0]
    second = parse_users_root(users, db)
    assert second["inserted"] == 0 and second["unchanged_files"] == first["files"]
    # A file that grew is read again and only its new steps are added.
    path = os.path.join(users, "Alice", ".codex", "sessions", "2026", "06", "12",
                        "rollout-2026-06-12T08-00-00-cdx1.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"timestamp": "2026-06-12T08:01:00Z", "type": "response_item", "payload": '
                '{"type": "message", "role": "assistant", "id": "c9", "content": '
                '[{"type": "output_text", "text": "Done."}]}}\n')
    third = parse_users_root(users, db)
    assert third["inserted"] == 1
    assert conn.execute("SELECT count(*) FROM ai_agent_steps").fetchone()[0] == before + 1
    assert conn.execute("SELECT count(*) FROM ai_agent_sessions").fetchone()[0] == 4


def test_tool_kinds_and_masking():
    assert tool_kind("Bash") == "command" and tool_kind("run_shell_command") == "command"
    assert tool_kind("Write") == "file_write" and tool_kind("replace") == "file_edit"
    assert tool_kind("WebFetch") == "web" and tool_kind("TodoWrite") == "tool"
    # MCP tools: driving a browser, the screen, or any other server
    assert tool_kind("mcp__x__y") == "mcp"
    assert tool_kind("mcp__claude-in-chrome__navigate") == "browser"
    assert tool_kind("mcp__claude-in-chrome__computer") == "browser"     # clicks inside the page
    assert tool_kind("mcp__playwright__browser_click") == "browser"
    assert tool_kind("mcp__computer-use__screenshot") == "computer"
    assert tool_kind("computer") == "computer" and tool_kind("browser_action") == "browser"
    assert mask_secrets("postgres://u:hunter22@db/x") == "postgres://[masked: password]@db/x"
    assert mask_secrets("export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz12") == \
        "export OPENAI_API_KEY=[masked: openai key]"
    assert mask_secrets("git commit -m fix") == "git commit -m fix"
