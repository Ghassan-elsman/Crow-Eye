"""An AI step beside the Windows record of the same act (data/ai_agent_links).

Each rule is checked both ways: the matching record links, and a record that
differs in program, file, page or time does not - a link is a claim that two
records describe one act, so a loose rule is a false claim.
"""
import json
import os
import sqlite3
import tempfile
import unittest

from data.ai_agent_links import AiLinks


def _db(folder, name, ddl, rows):
    c = sqlite3.connect(os.path.join(folder, name))
    c.execute(ddl)
    for sql, vals in rows:
        c.execute(sql, vals)
    c.commit()
    c.close()


class Links(unittest.TestCase):

    def setUp(self):
        d = self.dir = tempfile.mkdtemp(prefix="ailinks_")
        _db(d, "ai_agents.db",
            "CREATE TABLE ai_agent_steps (agent, user_name, session_id, step_id, ts, role, kind, tool, "
            "command, target, cwd, status, text, text_length, is_sidechain, source_path, parsed_at, "
            "program, exit_code, duration_ms)",
            [("INSERT INTO ai_agent_steps (agent, session_id, step_id, ts, kind, command, target, program, "
              "duration_ms) VALUES (?,?,?,?,?,?,?,?,?)", v) for v in (
                ("Claude Code", "s1", "run", "2026-06-10 14:00:00", "command", "python x.py", "", "python", 8000),
                ("Claude Code", "s1", "edit", "2026-06-10 14:05:00", "file_edit", "", "C:\\w\\app.py", "", None),
                ("Claude Code", "s1", "page", "2026-06-10 14:10:00", "browser", "",
                 "https://example.test/admin/", "", None))])
        _db(d, "prefetch_data.db",
            "CREATE TABLE prefetch_data (executable_name, run_count, last_executed, run_times)",
            [("INSERT INTO prefetch_data VALUES (?,?,?,?)", v) for v in (
                ("PYTHON.EXE", 2, "2026-06-10 14:00:03",
                 json.dumps(["2026-06-10 14:00:03", "2026-06-09 09:00:00"])),     # inside / far away
                ("NODE.EXE", 1, "2026-06-10 14:00:02", json.dumps(["2026-06-10 14:00:02"])))])  # other program
        _db(d, "srum_data.db", "CREATE TABLE srum_application_usage (timestamp, app_name)",
            [("INSERT INTO srum_application_usage VALUES (?,?)", v) for v in (
                ("2026-06-10 14:35:00", "python.exe"), ("2026-06-10 14:35:00", "python.exe"),   # two users
                ("2026-06-10 15:35:00", "python.exe"))])                                        # next hour
        _db(d, "USN_journal.db", "CREATE TABLE journal_events (filename, timestamp, reason)",
            [("INSERT INTO journal_events VALUES (?,?,?)", v) for v in (
                ("app.py", "2026-06-10 14:05:20", "DATA_OVERWRITE"),
                ("app.py", "2026-06-10 14:05:20", "CLOSE"),                 # same change, another flag
                ("app.py", "2026-06-10 14:20:00", "DATA_OVERWRITE"),        # too late
                ("other.py", "2026-06-10 14:05:10", "DATA_OVERWRITE"))])    # another file
        _db(d, "browser_analysis.db", "CREATE TABLE browser_history (visit_time, url, browser)",
            [("INSERT INTO browser_history VALUES (?,?,?)", v) for v in (
                ("2026-06-10 14:10:04", "https://example.test/admin", "Chrome"),
                ("2026-06-10 14:10:05", "https://example.test/other", "Chrome"))])
        self.links = AiLinks(d)

    def _by(self, source):
        return [l for l in self.links.links_for(self.links.steps()) if l["source"] == source]

    def test_prefetch_links_the_run_inside_the_command_only(self):
        got = self._by("Prefetch")
        self.assertEqual([(l["name"], l["ts"], l["delta_s"]) for l in got],
                         [("PYTHON.EXE", "2026-06-10 14:00:03", 3.0)])

    def test_srum_links_the_hour_holding_the_step_once(self):
        got = self._by("SRUM")
        self.assertEqual([(l["ts"], l["name"]) for l in got], [("2026-06-10 14:35:00", "python.exe")])

    def test_usn_links_the_same_file_name_nearby_once_per_change(self):
        got = self._by("USN journal")
        self.assertEqual([(l["name"], l["ts"]) for l in got], [("app.py", "2026-06-10 14:05:20")])
        self.assertEqual(got[0]["detail"], "DATA_OVERWRITE ; CLOSE")

    def test_browser_links_the_same_page_only(self):
        got = self._by("Browser history")
        self.assertEqual([l["name"] for l in got], ["https://example.test/admin"])

    def test_every_link_names_its_rule_and_both_rows(self):
        for l in self.links.links_for(self.links.steps()):
            self.assertTrue(l["rule_text"] and l["db"] and l["table"] and l["rowid"] is not None
                            and l["ai_rowid"] is not None)

    def test_presence_without_time(self):
        p = self.links.program_presence(["python", "never"])
        self.assertEqual((p["python"]["prefetch_runs"], p["python"]["prefetch_last"]),
                         (2, "2026-06-10 14:00:03"))
        self.assertEqual(p["never"]["prefetch_runs"], 0)

    def test_a_case_with_no_windows_databases_has_no_links(self):
        empty = tempfile.mkdtemp()
        os.replace(os.path.join(self.dir, "ai_agents.db"), os.path.join(empty, "ai_agents.db"))
        lk = AiLinks(empty)
        self.assertEqual(lk.links_for(lk.steps()), [])
