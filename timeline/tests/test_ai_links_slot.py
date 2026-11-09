"""The timeline's getAiLinks: an AI step in the window beside the Windows
record of the same act, with the step's command for the detail panel; a step
outside the window is not asked about."""
import json
import os
import sqlite3
import tempfile
import unittest

from timeline.timeline_bridge import TimelineBridge


class AiLinksSlot(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tl_ailinks_")
        c = sqlite3.connect(os.path.join(self.dir, "ai_agents.db"))
        c.execute("CREATE TABLE ai_agent_steps (agent, user_name, session_id, step_id, ts, role, kind, "
                  "tool, command, target, cwd, status, text, text_length, is_sidechain, source_path, "
                  "parsed_at, program, exit_code, duration_ms)")
        for sid, ts in (("in", "2026-06-10 14:00:00"), ("out", "2026-06-12 09:00:00")):
            c.execute("INSERT INTO ai_agent_steps (agent, session_id, step_id, ts, kind, command, program) "
                      "VALUES ('Claude Code', 's', ?, ?, 'command', 'ping -n 3 example.test', 'ping')", (sid, ts))
        c.commit()
        c.close()
        c = sqlite3.connect(os.path.join(self.dir, "prefetch_data.db"))
        c.execute("CREATE TABLE prefetch_data (executable_name, run_count, last_executed, run_times)")
        c.execute("INSERT INTO prefetch_data VALUES ('PING.EXE', 2, '2026-06-12 09:00:02', ?)",
                  (json.dumps(["2026-06-10 14:00:04", "2026-06-12 09:00:02"]),))
        c.commit()
        c.close()

    def test_only_the_window_and_with_the_command(self):
        got = json.loads(TimelineBridge(self.dir).getAiLinks("2026-06-10T00:00:00Z", "2026-06-10T23:59:59Z"))
        self.assertEqual([(l["source"], l["name"], l["ts"], l["ai_text"]) for l in got],
                         [("Prefetch", "PING.EXE", "2026-06-10 14:00:04", "ping -n 3 example.test")])

    def test_a_bad_window_is_no_links_not_an_error(self):
        self.assertEqual(json.loads(TimelineBridge(self.dir).getAiLinks("", "")), [])
