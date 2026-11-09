"""The AI Agents dashboard's bridge, on a small case built with AI_Agent_Claw's
own schema (so a column renamed in the parser breaks this, not the screen).

What is checked is what an analyst would read: the strip counts the acts on the
right day, the overview's insights carry the sessions they name, a session's
story is in order with its programs and files, and a program lists the runs.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from PyQt5 import QtCore  # noqa: F401
    HAVE_QT = True
except Exception:                                     # pragma: no cover
    HAVE_QT = False

STEPS = [
    # agent, session, ts, role, kind, tool, command, target, program, exit
    ("Claude Code", "s1", "2026-11-01 10:00:00", "user", "prompt", "", "", "", "", None),
    ("Claude Code", "s1", "2026-11-01 10:00:05", "assistant", "command", "Bash",
     "cd C:\\work && python build.py", "", "python", 0),
    ("Claude Code", "s1", "2026-11-01 10:00:20", "assistant", "command", "Bash",
     "git push", "", "git", 1),
    ("Claude Code", "s1", "2026-11-01 10:01:00", "assistant", "file_edit", "Edit",
     "", "C:\\work\\build.py", "", None),
    ("Claude Code", "s1", "2026-11-01 10:02:00", "assistant", "file_read", "Read",
     "", "C:\\Users\\a\\.ssh\\id_rsa", "", None),
    ("Codex", "c1", "2026-11-02 09:00:00", "user", "prompt", "", "", "", "", None),
    ("Codex", "c1", "2026-11-02 09:00:10", "assistant", "command", "exec_command",
     "python -m pytest", "", "python", 0),
]


@unittest.skipUnless(HAVE_QT, "PyQt5 unavailable")
class AiAgentsBridgeReadsTheCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from Artifacts_Collectors import AI_Agent_Claw as claw
        cls.dir = tempfile.mkdtemp(prefix="aiagents_bridge_")
        conn = claw._open(os.path.join(cls.dir, "ai_agents.db"))
        try:
            for i, (agent, sid, ts, role, kind, tool, cmd, target, prog, code) in enumerate(STEPS):
                conn.execute(
                    "INSERT INTO ai_agent_steps (agent, user_name, session_id, step_id, ts, role, kind,"
                    " tool, command, target, text, program, exit_code, source_path, parsed_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (agent, "a", sid, "st%d" % i, ts, role, kind, tool, cmd, target,
                     "do the build" if kind == "prompt" else "", prog, code,
                     "C:\\Users\\a\\%s.jsonl" % sid, "2026-11-04 00:00:00"))
            conn.execute(
                "INSERT INTO ai_agent_sessions (agent, user_name, session_id, title, project_path,"
                " approval_mode, first_ts, last_ts, prompts, commands, file_changes, source_path,"
                " parsed_at) VALUES ('Claude Code','a','s1','Build it','C:\\work','bypassPermissions',"
                " '2026-11-01 10:00:00','2026-11-01 10:02:00',1,2,1,'C:\\Users\\a\\s1.jsonl',"
                " '2026-11-04 00:00:00')")
            conn.execute(
                "INSERT INTO ai_agent_sessions (agent, user_name, session_id, title, first_ts, last_ts,"
                " prompts, commands, file_changes, source_path, parsed_at) VALUES ('Codex','a','c1',"
                " 'Tests','2026-11-02 09:00:00','2026-11-02 09:00:10',1,1,0,'C:\\Users\\a\\c1.jsonl',"
                " '2026-11-04 00:00:00')")
            conn.commit()
        finally:
            conn.close()
        from visualizations.aiagents_bridge import AiAgentsBridge
        cls.bridge = AiAgentsBridge(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def call(self, slot, args=None):
        fn = getattr(self.bridge, slot)
        return json.loads(fn(json.dumps(args or {})) if args is not None else fn())

    def test_bounds_cover_the_two_days_and_both_agents(self):
        b = self.call("getAiBounds")
        self.assertTrue(b["hasData"])
        self.assertEqual((b["minDate"], b["maxDate"]), ("2026-11-01", "2026-11-02"))
        self.assertEqual({a["agent"] for a in b["agents"]}, {"Claude Code", "Codex"})

    def test_the_strip_counts_acts_on_their_day(self):
        tl = self.call("getAiTimeline", {})
        cmds = {d["day"]: d["value"] for d in tl["sources"]["commands"]["days"]}
        self.assertEqual(cmds.get("2026-11-01"), 2)
        self.assertEqual(cmds.get("2026-11-02"), 1)
        changes = {d["day"]: d["value"] for d in tl["sources"]["file_changes"]["days"]}
        self.assertEqual(changes.get("2026-11-01"), 1)
        # A read is not a change.
        self.assertEqual(sum(changes.values()), 1)

    def test_an_agent_filter_narrows_it(self):
        tl = self.call("getAiTimeline", {"agent": "Codex"})
        cmds = {d["day"]: d["value"] for d in tl["sources"]["commands"]["days"]}
        self.assertFalse(cmds.get("2026-11-01"))
        self.assertEqual(cmds.get("2026-11-02"), 1)

    def test_insights_name_their_sessions(self):
        ins = self.call("getAiOverview", {})["insights"]
        failed = json.dumps(ins["failedCommands"])
        self.assertIn("git push", failed)
        self.assertIn("id_rsa", json.dumps(ins["credentialFiles"]))
        self.assertIn("s1", json.dumps(ins["bypassSessions"]))

    def test_a_session_tells_its_story_in_order(self):
        d = self.call("getAiSessionDetail", {"session": "Claude Code|s1"})
        times = [x["t"] for x in d["story"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual({p["program"] for p in d["programs"]}, {"python", "git"})
        creds = [f for f in d["files"] if f.get("credential")]
        self.assertEqual([f["path"] for f in creds], ["C:\\Users\\a\\.ssh\\id_rsa"])
        self.assertTrue(d.get("raw"))

    def test_a_program_lists_every_agent_run(self):
        d = self.call("getAiProgramDetail", {"program": "python"})
        self.assertEqual(d["runsTotal"], 2)
        self.assertEqual(d["sessions"], 2)
        self.assertTrue(d.get("records"))

    def test_a_program_finds_its_prefetch_run_and_only_its_own(self):
        """PYTHON.EXE ran one second into the agent's `python build.py`;
        PYTHONW.EXE ran at the same moment and is a different program."""
        db = os.path.join(self.dir, "prefetch_data.db")
        conn = sqlite3.connect(db)
        try:
            conn.execute("CREATE TABLE prefetch_data (executable_name TEXT, run_count INTEGER, "
                         "last_executed TEXT, run_times TEXT)")
            conn.execute("INSERT INTO prefetch_data VALUES ('PYTHON.EXE', 3, '2026-11-01 10:00:06', ?)",
                         (json.dumps(["2026-11-01 10:00:06"]),))
            conn.execute("INSERT INTO prefetch_data VALUES ('PYTHONW.EXE', 1, '2026-11-01 10:00:06', ?)",
                         (json.dumps(["2026-11-01 10:00:06"]),))
            conn.commit()
        finally:
            conn.close()
        try:
            d = self.call("getAiProgramDetail", {"program": "python"})
            pf = [l for l in d["links"] if l["source"] == "Prefetch"]
            self.assertEqual([l["name"] for l in pf], ["PYTHON.EXE"])
            self.assertEqual(pf[0]["ai_ts"], "2026-11-01 10:00:05")
            self.assertEqual(d["presence"]["prefetch_runs"], 3)
        finally:
            os.remove(db)

    def test_a_case_without_the_database_says_so(self):
        from visualizations.aiagents_bridge import AiAgentsBridge
        empty = tempfile.mkdtemp(prefix="aiagents_empty_")
        try:
            self.assertFalse(json.loads(AiAgentsBridge(empty).getAiBounds())["hasData"])
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
