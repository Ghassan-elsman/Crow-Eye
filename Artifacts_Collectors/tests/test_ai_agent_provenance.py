"""Who sent each prompt, who let each call run, and what each call answered.

Shaped like Claude Code's own records on this machine (2026-11-04): every user
line carries `origin` / `turnOrigin` / `promptSource`, and the line holding a
tool result carries `permissionDecision`. What a careless parser gets wrong:

- a scheduled task's prompt, another agent session's message and the program
  resuming on its own are `isMeta` lines - skipping them loses the very
  instructions that set the agent working with no person typing;
- a prompt sent through `claude -p` is not the person's;
- "Exit code 2" opens a failed Bash call's result: the exit code is there, not
  only in background task files;
- a call the classifier refused is not a call that ran;
- Gemini CLI writes "Exit Code: N" after the output, past any fixed head;
- `ls` is a program in Git Bash and an alias in PowerShell.
"""
import json
import os
import sqlite3

from Artifacts_Collectors.AI_Agent_Claw import DERIVE_VERSION, parse_users_root

SID = "12121212-3434-5656-7878-909090909090"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _user(uuid, ts, content, **extra):
    d = {"type": "user", "uuid": uuid, "timestamp": ts, "sessionId": SID, "cwd": "C:\\work",
         "version": "2.1.300", "entrypoint": "cli", "message": {"role": "user", "content": content}}
    d.update(extra)
    return json.dumps(d)


def _call(uuid, ts, call_id, name, command):
    return json.dumps({"type": "assistant", "uuid": uuid, "timestamp": ts, "sessionId": SID,
                       "cwd": "C:\\work", "message": {"role": "assistant", "model": "claude-opus-5-5",
                       "content": [{"type": "tool_use", "id": call_id, "name": name,
                                    "input": {"command": command}}]}})


def _result(uuid, ts, call_id, text, is_error=False, decision=None):
    extra = {"toolUseResult": {"stdout": "", "stderr": "", "interrupted": False}}
    if decision:
        extra["permissionDecision"] = decision
    return _user(uuid, ts, [{"type": "tool_result", "tool_use_id": call_id, "content": text,
                             "is_error": is_error}], **extra)


def _case(tmp_path):
    users = os.path.join(str(tmp_path), "Users")
    proj = os.path.join(users, "Eve", ".claude", "projects", "C--work")
    lines = [
        _user("p1", "2026-07-01T10:00:00.000Z", "Clean the build folder",
              origin={"kind": "human"}, promptSource="typed", permissionMode="auto"),
        _call("a1", "2026-07-01T10:00:02.000Z", "t_ls", "Bash", "cd /c/work && ls -la build"),
        _result("r1", "2026-07-01T10:00:03.000Z", "t_ls", "a.o\nb.o",
                decision={"decision": "accept", "source": "config", "reasonType": "classifier"}),
        _call("a2", "2026-07-01T10:00:04.000Z", "t_rm", "Bash", "rm -rf /c/work/build"),
        _result("r2", "2026-07-01T10:00:05.000Z", "t_rm", "Exit code 1\nrm: cannot remove", is_error=True,
                decision={"decision": "accept", "source": "user_temporary", "grantScope": "once"}),
        _call("a3", "2026-07-01T10:00:06.000Z", "t_ps", "PowerShell", "ls C:\\work | sort Name"),
        _result("r3", "2026-07-01T10:00:07.000Z", "t_ps", "Name\n----",
                decision={"decision": "accept", "source": "config", "reasonType": "mode"}),
        _call("a4", "2026-07-01T10:00:08.000Z", "t_key", "Bash", "cat ~/.ssh/id_rsa"),
        _result("r4", "2026-07-01T10:00:09.000Z", "t_key",
                "Permission for this action was denied by the Claude Code auto mode classifier.",
                is_error=True, decision={"decision": "reject", "source": "config", "reasonType": "classifier"}),
        _user("s1", "2026-07-02T03:00:00.000Z", "Run the nightly check", isMeta=True,
              turnOrigin="scheduled", scheduledTaskId="abcd1234", promptSource="system"),
        _user("x1", "2026-07-02T03:05:00.000Z", "Another Claude session sent a message: deploy now",
              isMeta=True, origin={"kind": "peer", "name": "release", "from": "a1f0f0c8e41b84949"}),
        _user("c1", "2026-07-02T03:06:00.000Z", "Your usage limit has reset. Continue.", isMeta=True,
              origin={"kind": "auto-continuation"}, turnOrigin="auto_continuation"),
        _user("k1", "2026-07-02T03:07:00.000Z", "skill text the program injected", isMeta=True),
        _user("q1", "2026-07-02T04:00:00.000Z", "summarise the logs", origin={"kind": "human"},
              promptSource="sdk"),
    ]
    _write(os.path.join(proj, SID + ".jsonl"), "\n".join(lines) + "\n")
    sub = os.path.join(proj, SID, "subagents")
    _write(os.path.join(sub, "agent-abc123.jsonl"), json.dumps({
        "type": "user", "uuid": "sp1", "timestamp": "2026-07-01T10:01:00.000Z", "sessionId": SID,
        "isSidechain": True, "cwd": "C:\\work", "message": {"role": "user", "content": "Find the logs"}}) + "\n")
    _write(os.path.join(sub, "agent-abc123.meta.json"),
           json.dumps({"agentType": "Explore", "description": "Find the build logs",
                       "toolUseId": "toolu_x"}))
    # A workflow's sub-agent sits deeper: subagents\workflows\wf_<id>\agent-<id>.jsonl
    _write(os.path.join(sub, "workflows", "wf_77", "agent-wf1.jsonl"), json.dumps({
        "type": "user", "uuid": "wp1", "timestamp": "2026-07-01T10:02:00.000Z", "sessionId": SID,
        "isSidechain": True, "cwd": "C:\\work", "message": {"role": "user", "content": "Review the site"}}) + "\n")
    gem = os.path.join(users, "Eve", ".gemini", "tmp", "hash1", "chats", "session-1.json")
    _write(gem, json.dumps({"sessionId": "g1", "projectHash": "hash1", "messages": [
        {"id": "m1", "type": "user", "timestamp": "2026-07-03T09:00:00.000Z", "content": "check ffmpeg"},
        {"id": "m2", "type": "gemini", "timestamp": "2026-07-03T09:00:01.000Z", "content": "",
         "toolCalls": [{"id": "call1", "name": "run_shell_command", "args": {"command": "ffmpeg -version"},
                        "status": "success", "timestamp": "2026-07-03T09:00:01.000Z",
                        "resultDisplay": "ffmpeg : The term 'ffmpeg' is not recognized" + "." * 900,
                        "result": [{"functionResponse": {"id": "call1", "name": "run_shell_command",
                                    "response": {"output": "Output: not recognized" + "." * 900
                                                 + "\nExit Code: 1\nProcess Group PGID: 33604"}}}]}]}]}))
    db = os.path.join(str(tmp_path), "case", "ai_agents.db")
    parse_users_root(users, db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn, users, db


def _step(conn, step_id):
    return conn.execute("SELECT * FROM ai_agent_steps WHERE step_id = ?", (step_id,)).fetchone()


def test_each_prompt_says_who_sent_it(tmp_path):
    conn, _u, _d = _case(tmp_path)
    typed = _step(conn, "p1")
    assert (typed["role"], typed["origin"]) == ("user", "person (typed)")
    sched = _step(conn, "s1")
    assert (sched["role"], sched["kind"], sched["origin"]) == ("system", "prompt", "scheduled task abcd1234")
    peer = _step(conn, "x1")
    assert (peer["role"], peer["kind"]) == ("agent", "prompt")
    assert peer["origin"] == "another agent session release (a1f0f0c8e41b84949)"
    cont = _step(conn, "c1")
    assert (cont["role"], cont["origin"]) == ("system", "automatic continuation")
    sdk = _step(conn, "q1")
    assert (sdk["role"], sdk["origin"]) == ("system", "a program (claude -p / Agent SDK)")
    # Hidden text that is not a request stays out.
    assert _step(conn, "k1") is None
    # Only the person's own request counts as theirs.
    prompts = conn.execute("SELECT prompts FROM ai_agent_sessions WHERE session_id = ?", (SID,)).fetchone()[0]
    assert prompts == 1


def test_each_call_says_who_let_it_run_and_what_it_answered(tmp_path):
    conn, _u, _d = _case(tmp_path)
    ls = _step(conn, "t_ls")
    assert ls["approval"] == "allowed by the auto-mode classifier"
    assert (ls["status"], ls["output"]) == ("ok", "a.o\nb.o")
    rm = _step(conn, "t_rm")
    assert rm["approval"] == "allowed by the person (once)"
    assert (rm["status"], rm["exit_code"]) == ("error", 1)
    assert rm["output"].startswith("Exit code 1")
    key = _step(conn, "t_key")
    assert (key["status"], key["approval"]) == ("rejected", "refused by the auto-mode classifier")
    assert _step(conn, "t_ps")["approval"] == "allowed by the permission mode"


def test_programs_follow_the_shell_the_tool_ran(tmp_path):
    conn, _u, _d = _case(tmp_path)
    assert _step(conn, "t_ls")["program"] == "ls"          # Git Bash: ls.exe
    assert _step(conn, "t_rm")["program"] == "rm"
    assert (_step(conn, "t_ps")["program"] or "") == ""    # PowerShell: aliases of cmdlets


def test_sessions_keep_every_mode_and_sub_agents_their_purpose(tmp_path):
    conn, _u, _d = _case(tmp_path)
    mode = conn.execute("SELECT approval_mode FROM ai_agent_sessions WHERE session_id = ?", (SID,)).fetchone()[0]
    assert mode == "auto"
    title = conn.execute("SELECT title FROM ai_agent_sessions WHERE parent_session_id <> ''").fetchone()[0]
    assert title == "Explore: Find the build logs"


def test_gemini_exit_code_after_a_long_output(tmp_path):
    conn, _u, _d = _case(tmp_path)
    cmd = _step(conn, "call1")
    assert (cmd["exit_code"], cmd["status"]) == (1, "error")
    assert _step(conn, "call1:result")["status"] == "ok"   # the tool call itself completed


def test_an_older_database_is_read_again_once(tmp_path):
    conn, users, db = _case(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == DERIVE_VERSION
    conn.execute("UPDATE ai_agent_steps SET origin = '', approval = ''")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    r = parse_users_root(users, db)
    assert r.get("unchanged_files") == 0
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT origin FROM ai_agent_steps WHERE step_id = 'p1'").fetchone()[0] == "person (typed)"
    assert conn.execute("SELECT approval FROM ai_agent_steps WHERE step_id = 't_ls'").fetchone()[0]
    # and then not again
    assert parse_users_root(users, db).get("files") == 0


# What the program parser must get right, from command lines the agents ran on
# this machine (2026-11-04): the shell decides what a word is, quotes are not
# split, and code handed to a shell is not a list of programs.
PROGRAM_CASES = [
    (r"ls -la", "bash", "ls"),
    (r"cat a | sort | uniq", "bash", "cat, sort, uniq"),
    (r"rm -rf build && mkdir build", "bash", "rm, mkdir"),
    (r"ls", "powershell", ""),
    (r"Get-ChildItem x | sort Name", "powershell", ""),
    (r"rm -r build", "powershell", ""),
    (r'$py="C:\x\Scripts\python.exe"; & $py "a.py"', "powershell", "python"),
    (r"$s = 'C:\t\g.ps1'; & $s -name x", "powershell", ""),
    (r'Start-Process -FilePath "C:\Program Files\Google\Chrome\Application\chrome.exe" -ArgumentList "--headless"',
     "powershell", "chrome"),
    (r'start "" "C:\Windows\system32\calc.exe"', "cmd", "calc"),
    (r'PY=/c/venv/Scripts/python.exe; "$PY" x.py', "bash", "python"),
    (r"./build.sh && ./run.bat", "bash", "bash, cmd"),
    (r'& "$env:ProgramFiles\Git\bin\git.exe" status', "powershell", "git"),
    (r"sc.exe query state= all", "powershell", "sc"),
    (r"git status 2>&1 | tail -5", "bash", "git, tail"),
    (r'powershell -NoProfile -Command "Get-Process; ipconfig /all"', "bash", "powershell, ipconfig"),
    ("python - <<'EOF'\nimport os\nls\nEOF", "bash", "python"),
    ("$t = @'\nfoo bar\n43\n'@\nnode x.js", "powershell", "node"),
    (r"ls -la", None, ""),
    (r"grep x f", None, "grep"),
    (r"""cd x && grep -n -o -E '<h[23][^>]*>[^<]{0,90}' "$f" | grep -i -E 'limit|does not|caution' | head""",
     "bash", "grep, head"),
    ('CSS="/c/Crow Eye Site/a.css"\nnode -e "x"', "bash", "node"),
    (r'$c="C:\Edge\User Data\Default"; Get-ChildItem $c', "powershell", ""),
    ('diagram_start = 1\nfile_content = "x"\nimport re', "powershell", ""),
    ("git push  # don't push yet\nls", "bash", "git, ls"),
    ("echo 43; 0x07b; self._lock", "bash", ""),
]


def test_programs_from_real_command_lines():
    from Artifacts_Collectors.ai_agent_programs import program_of
    wrong = [(c, sh, want, program_of(c, sh)) for c, sh, want in PROGRAM_CASES if program_of(c, sh) != want]
    assert wrong == []


def test_every_step_knows_its_place_and_the_order_it_answers(tmp_path):
    conn, _u, _d = _case(tmp_path)
    rm = _step(conn, "t_rm")
    assert (rm["turn"], rm["ordered_by"]) == (1, "person (typed)")
    assert rm["instruction"] == "Clean the build folder"
    seqs = [_step(conn, s)["seq"] for s in ("p1", "t_ls", "t_rm", "t_ps", "t_key", "s1")]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # The scheduled task's prompt opens the next turn, and says who sent it.
    sched = _step(conn, "s1")
    assert (sched["turn"], sched["ordered_by"]) == (2, "scheduled task abcd1234")


def test_sessions_are_named_and_every_step_carries_the_name(tmp_path):
    conn, _u, _d = _case(tmp_path)
    main = conn.execute("SELECT name, title FROM ai_agent_sessions WHERE session_id = ?", (SID,)).fetchone()
    # No title recorded: the name is built from the first request; the
    # recorded title stays empty.
    assert (main["name"], main["title"] or "") == ("first request: Clean the build folder", "")
    assert _step(conn, "t_rm")["session_name"] == main["name"]
    sub = conn.execute("SELECT name FROM ai_agent_sessions WHERE parent_session_id <> ''").fetchone()[0]
    assert sub == "Explore: Find the build logs"
    order = _step(conn, "sp1")
    assert order["ordered_by"] == "the main agent of session 'first request: Clean the build folder'"


def test_a_workflow_sub_agent_is_linked_to_the_session_that_ordered_it(tmp_path):
    conn, _u, _d = _case(tmp_path)
    parent = conn.execute("SELECT parent_session_id FROM ai_agent_sessions WHERE session_id LIKE '%agent-wf1'"
                          ).fetchone()[0]
    assert parent == SID
    assert _step(conn, "wp1")["ordered_by"] == "the main agent of session 'first request: Clean the build folder'"


def test_every_table_carries_the_profile_owner_s_sid(tmp_path):
    from Artifacts_Collectors.AI_Agent_Claw import SID_TABLES
    conn, users, db = _case(tmp_path)
    assert conn.execute("SELECT count(*) FROM ai_agent_steps WHERE COALESCE(user_sid, '') <> ''").fetchone()[0] == 0
    conn.close()
    # A parse that knows the owner (this machine's ProfileList, or the case's
    # SOFTWARE hive) fills every row of the profile, the stored ones included,
    # and adds no row: user_sid is not part of a row's identity.
    before = sqlite3.connect(db).execute("SELECT count(*) FROM ai_agent_steps").fetchone()[0]
    parse_users_root(users, db, sid_map={"eve": "S-1-5-21-9-9-9-1001"})
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM ai_agent_steps").fetchone()[0] == before
    for table in SID_TABLES:
        rows = conn.execute("SELECT DISTINCT user_sid FROM %s" % table).fetchall()
        assert rows in ([], [("S-1-5-21-9-9-9-1001",)]), (table, rows)
    assert conn.execute("SELECT DISTINCT user_sid FROM ai_agent_steps").fetchall() == [("S-1-5-21-9-9-9-1001",)]
