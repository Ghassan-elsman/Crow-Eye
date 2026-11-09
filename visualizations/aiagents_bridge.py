"""QWebChannel bridge for the AI Agents dashboard.

Reads the case's ai_agents.db (AI_Agent_Claw: Claude Code, Codex, Gemini CLI,
GitHub Copilot, Antigravity, Roo/Kilo/Cline) and serves the react-aiagents app,
the same shape as the Prefetch, SRUM and MFT/USN bridges: JSON in, JSON out,
data getters named get* so they run off the GUI thread (AsyncBridge).

What is drawn is what the agents themselves recorded: the person's prompts, the
commands the agent ran (and the programs each started), the files it wrote and
edited, the pages and screen it drove. Beside each session, data/ai_agent_links
puts what Windows recorded of the same acts (Prefetch, BAM, 4688, SRUM, USN,
browser history), each link naming its rule. Nothing here infers that activity
was an AI's when no AI record says so (that is Sentinel's).

The strip's series are acts, coloured in the AI actor colour family (cyan), and
the person's prompts in the person colour (blue): who acted is the colour,
which agent is the label.
"""

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from PyQt5.QtCore import pyqtSlot

from visualizations.timeseries import (axis_range as _axis_range, densify as _densify,
                                       densify_series as _densify_series)
from visualizations.raw_record import raw_record as _raw, source_records as _records
from visualizations.insights import insight as _insight, plain as _plain, subject as _subject

try:
    from visualizations.async_bridge import AsyncBridge
except ImportError:                                  # run from its own folder
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from visualizations.async_bridge import AsyncBridge

logger = logging.getLogger(__name__)

AI_DB = "ai_agents.db"
# The strip's rows: one act each (kind, role), in display order.
SERIES = (
    ("prompts", "kind = 'prompt' AND role = 'user'"),
    ("commands", "kind = 'command' AND role = 'assistant'"),
    ("file_changes", "kind IN ('file_write', 'file_edit')"),
    ("browser", "kind IN ('browser', 'computer', 'screenshot', 'web')"),
)
ACT_WHERE = "(%s)" % " OR ".join("(%s)" % w for _k, w in SERIES)
SERIES_CASE = "CASE %s END" % " ".join("WHEN %s THEN '%s'" % (w, k) for k, w in SERIES)
# Files that hold credentials or keys (the AI File Change Wing's rule).
CREDENTIAL_RX = re.compile(
    r"(?i)(\\\.ssh\\|\\\.aws\\|\\\.azure\\|\\\.kube\\|\\\.docker\\config\.json|\\\.git-credentials|"
    r"\\\.netrc|\\Login Data$|\\Cookies$|\\Web Data$|logins\.json$|key4\.db$|\.kdbx$|id_rsa|id_ed25519|"
    r"\\Microsoft\\Credentials\\|\\Microsoft\\Protect\\|\.pfx$|\.pem$|\\\.env$)")
BYPASS_MODES = ("bypasspermissions", "danger-full-access", "never", "yolo", "auto")
EVENTS_MAX = 2000
STEPS_MAX = 3000


def _loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


def _one_line(value, limit=160):
    text = str(value or "").strip()
    for line in text.splitlines():
        if line.strip():
            text = line.strip()
            break
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _base_name(name):
    """GREP.EXE, a full path to grep.exe, or grep -> grep: a program's name without
    its folder or .exe, lower-case (how ai_agent_steps.program stores it)."""
    n = str(name or "").strip().replace("/", "\\").rsplit("\\", 1)[-1].lower()
    return n[:-4] if n.endswith(".exe") else n


TS_FMT = "%Y-%m-%d %H:%M:%S"


def _parse_ts(value):
    try:
        return datetime.strptime(str(value)[:19], TS_FMT)
    except (ValueError, TypeError):
        return None


def _session_key(agent, session_id):
    return "%s|%s" % (agent, session_id)


class AiAgentsBridge(AsyncBridge):
    def __init__(self, case_directory: str, parent=None):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        self._ensure_index()

    def _ensure_index(self):
        """The acts index AI_Agent_Claw creates since 2026-11-04, for a case
        parsed before it: built once (seconds), never on evidence - this is
        Crow-Eye's own parser output."""
        p = self._db_path()
        if not p:
            return
        try:
            conn = sqlite3.connect(p)
            try:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_agent_steps'"
                                ).fetchone():
                    conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_steps_acts "
                                 "ON ai_agent_steps (kind, role, ts, agent, user_name, session_id)")
                    conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.info("AI steps index not built: %s", e)

    # ------------------------------------------------------------ database
    def _db_path(self) -> Optional[str]:
        p = os.path.join(self.case_dir, AI_DB)
        return p if os.path.exists(p) else None

    def _query(self, sql: str, params=()) -> List[Dict]:
        p = self._db_path()
        if not p:
            return []
        for attempt in range(3):
            try:
                conn = sqlite3.connect(p)
                conn.row_factory = sqlite3.Row
                try:
                    return [dict(r) for r in conn.execute(sql, params)]
                finally:
                    conn.close()
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 2:
                    time.sleep(0.1)
                    continue
                logger.error("ai agents query error: %s", e)
                return []
        return []

    def _step_columns(self):
        """ai_agent_steps' columns in this case (older cases lack output,
        approval and origin)."""
        return {r["name"] for r in self._query("PRAGMA table_info(ai_agent_steps)")}

    def _session_columns(self):
        return {r["name"] for r in self._query("PRAGMA table_info(ai_agent_sessions)")}

    def _tables(self):
        return {r["name"] for r in self._query("SELECT name FROM sqlite_master WHERE type='table'")}

    def _filter(self, args, alias=""):
        """(where, params) for the dashboard's filters on ai_agent_steps."""
        a = alias + "." if alias else ""
        where, params = [], []
        if args.get("agent"):
            where.append("%sagent = ?" % a)
            params.append(args["agent"])
        if args.get("user"):
            where.append("%suser_name = ?" % a)
            params.append(args["user"])
        if args.get("start"):
            where.append("%sts >= ?" % a)
            params.append(args["start"])
        if args.get("end"):
            where.append("%sts < date(?, '+1 day')" % a)
            params.append(args["end"])
        terms = [t.strip() for t in (args.get("terms") or []) if t and t.strip()]
        if terms:
            likes = ["(%scommand LIKE ? OR %starget LIKE ? OR %sprogram LIKE ?)" % (a, a, a)
                     for _t in terms]
            joiner = " AND " if (args.get("mode") or "or").lower() == "and" else " OR "
            where.append("(" + joiner.join(likes) + ")")
            for t in terms:
                params += ["%" + t + "%"] * 3
        return (" AND ".join(where) or "1"), params

    # --------------------------------------------------------------- slots
    @pyqtSlot(result=str)
    def getAiBounds(self) -> str:
        if "ai_agent_steps" not in self._tables():
            return json.dumps({"hasData": False})
        r = self._query("SELECT date(MIN(ts)) AS lo, date(MAX(ts)) AS hi FROM ai_agent_steps "
                        "WHERE ts >= '2000' AND " + ACT_WHERE)
        agents = self._query("SELECT agent, count(*) AS sessions FROM ai_agent_sessions "
                             "GROUP BY agent ORDER BY sessions DESC")
        users = [x["user_name"] for x in self._query(
            "SELECT DISTINCT user_name FROM ai_agent_sessions ORDER BY user_name")]
        return json.dumps({"hasData": bool(r and r[0]["lo"]), "minDate": r[0]["lo"] if r else None,
                           "maxDate": r[0]["hi"] if r else None, "agents": agents, "users": users})

    @pyqtSlot(str, result=str)
    def getAiTimeline(self, args_json: str) -> str:
        args = _loads(args_json)
        where, params = self._filter(args)
        rows = self._query(
            "SELECT substr(ts, 1, 10) AS day, %s AS series, count(*) AS n FROM ai_agent_steps "
            "WHERE ts >= '2000' AND %s AND %s GROUP BY day, series" % (SERIES_CASE, ACT_WHERE, where), params)
        per = {k: {} for k, _w in SERIES}
        combined = {}
        for r in rows:
            if r["series"] in per:
                per[r["series"]][r["day"]] = r["n"]
                combined[r["day"]] = combined.get(r["day"], 0) + r["n"]
        start, end = _axis_range(args, combined)
        return json.dumps({"sources": _densify_series(per, start, end),
                           "combined": _densify(combined, start, end)})

    @pyqtSlot(str, result=str)
    def getAiOverview(self, args_json: str) -> str:
        args = _loads(args_json)
        where, params = self._filter(args)
        # Each query reads only what the acts index covers, or the rows of one
        # kind once (measured: 37 s as one aggregate over every row, ~3 s split).
        acts = self._query(
            "SELECT %s AS series, count(*) AS n, count(DISTINCT substr(ts, 1, 10)) AS days "
            "FROM ai_agent_steps WHERE %s AND %s GROUP BY series" % (SERIES_CASE, ACT_WHERE, where), params)
        n_of = {r["series"]: r["n"] for r in acts}
        days = self._query("SELECT count(DISTINCT substr(ts, 1, 10)) AS d FROM ai_agent_steps WHERE %s AND %s"
                           % (ACT_WHERE, where), params)[0]["d"]
        s_where, s_params = [], []
        for col, key in (("agent", "agent"), ("user_name", "user")):
            if args.get(key):
                s_where.append("%s = ?" % col)
                s_params.append(args[key])
        if args.get("start"):
            s_where.append("last_ts >= ?")
            s_params.append(args["start"])
        if args.get("end"):
            s_where.append("first_ts < date(?, '+1 day')")
            s_params.append(args["end"])
        sessions = self._query("SELECT count(*) AS n FROM ai_agent_sessions WHERE %s"
                               % (" AND ".join(s_where) or "1"), s_params)[0]["n"]
        by_agent = self._query(
            "SELECT agent, count(DISTINCT session_id) AS sessions, "
            "sum(kind = 'command' AND role = 'assistant') AS commands, "
            "sum(kind IN ('file_write', 'file_edit')) AS file_changes FROM ai_agent_steps "
            "WHERE %s AND %s GROUP BY agent ORDER BY sessions DESC" % (ACT_WHERE, where), params)
        progs: Dict[str, int] = {}
        failed_ids = []
        for r in self._query("SELECT rowid AS rowid, program, exit_code FROM ai_agent_steps WHERE kind = 'command' "
                             "AND role = 'assistant' AND %s" % where, params):
            if r["exit_code"] not in (None, 0):
                failed_ids.append(r["rowid"])
            for p in str(r["program"] or "").split(","):
                p = p.strip()
                if p:
                    progs[p] = progs.get(p, 0) + 1
        file_rows = self._query("SELECT agent, session_id, kind, target, ts FROM ai_agent_steps WHERE kind IN "
                                "('file_read', 'file_write', 'file_edit') AND %s" % where, params)
        totals = {"sessions": sessions, "prompts": n_of.get("prompts", 0), "commands": n_of.get("commands", 0),
                  "files": len({r["target"] for r in file_rows if r["kind"] != "file_read" and r["target"]}),
                  "pages": n_of.get("browser", 0), "days": days}
        top = sorted(progs.items(), key=lambda kv: kv[1], reverse=True)[:15]
        presence = self._presence([p for p, _n in top])
        top_programs = [{"program": p, "n": n, "prefetchRuns": presence.get(p, {}).get("prefetch_runs", 0),
                         "amcache": len(presence.get(p, {}).get("amcache", []))} for p, n in top]

        def sess_subjects(rows, note_of):
            return [_subject("%s - %s" % (r["agent"], r.get("title") or r["session_id"][:12]),
                             _session_key(r["agent"], r["session_id"]), note_of(r)) for r in rows]

        failed = []
        for i in range(0, len(failed_ids), 500):
            chunk = failed_ids[i:i + 500]
            failed += self._query("SELECT agent, session_id, command, exit_code, ts FROM ai_agent_steps "
                                  "WHERE rowid IN (%s)" % ",".join("?" * len(chunk)), chunk)
        failed.sort(key=lambda r: r["ts"] or "", reverse=True)
        reads = [r for r in file_rows if CREDENTIAL_RX.search(str(r["target"] or ""))]
        bypass = [r for r in self._query(
            "SELECT agent, session_id, title, approval_mode, first_ts FROM ai_agent_sessions "
            "WHERE approval_mode IS NOT NULL AND approval_mode != ''")
            if any(m in str(r["approval_mode"]).lower() for m in BYPASS_MODES)]
        gone = self._query("SELECT agent, session_id, title, project_path, first_ts FROM ai_agent_sessions "
                           "WHERE title LIKE '[transcript not found%' OR title LIKE '[chat file not found%'")
        # Prompts nobody typed (a scheduled task, another agent session, a
        # program through claude -p, the program resuming) and calls refused
        # before they ran: who drove the agent, and what it was stopped from.
        cols = self._step_columns()
        sent, refused = [], []
        if "origin" in cols:
            sent = self._query(
                "SELECT agent, session_id, origin, substr(text, 1, 200) AS text, ts FROM ai_agent_steps "
                "WHERE kind = 'prompt' AND (role = 'system' OR (role = 'agent' AND is_sidechain = 0)) "
                "ORDER BY ts DESC LIMIT 2000")
        if "approval" in cols:
            refused = self._query(
                "SELECT agent, session_id, kind, command, target, approval, ts FROM ai_agent_steps "
                "WHERE status = 'rejected' ORDER BY ts DESC LIMIT 2000")
        insights = {
            "failedCommands": _insight(len(failed), [
                _subject(_one_line(r["command"], 90), _session_key(r["agent"], r["session_id"]),
                         "exit %s - %s" % (r["exit_code"], str(r["ts"])[:16])) for r in failed]),
            "credentialFiles": _insight(len(reads), [
                _subject(str(r["target"]), _session_key(r["agent"], r["session_id"]),
                         "%s - %s" % (r["agent"], str(r["ts"])[:16])) for r in reads]),
            "bypassSessions": _insight(len(bypass), sess_subjects(
                bypass, lambda r: "%s - %s" % (r["approval_mode"], str(r["first_ts"])[:16]))),
            "goneTranscripts": _insight(len(gone), sess_subjects(
                gone, lambda r: "%s - %s" % (r.get("project_path") or "", str(r["first_ts"])[:16]))),
            "notFromPerson": _insight(len(sent), [
                _subject(_one_line(r["text"], 90), _session_key(r["agent"], r["session_id"]),
                         "%s - %s" % (r["origin"] or "not the person", str(r["ts"])[:16])) for r in sent]),
            "refusedCalls": _insight(len(refused), [
                _subject(_one_line(r["command"] or r["target"] or r["kind"], 90),
                         _session_key(r["agent"], r["session_id"]),
                         "%s - %s" % (r["approval"] or "refused", str(r["ts"])[:16])) for r in refused]),
            "distinctPrograms": _plain(len(progs)),
        }
        counts = {}
        for t in ("ai_agent_file_versions", "ai_agent_processes", "ai_agent_settings"):
            if t in self._tables():
                counts[t] = self._query("SELECT count(*) AS n FROM %s" % t)[0]["n"]
        return json.dumps({"totals": totals, "byAgent": by_agent, "topPrograms": top_programs,
                           "insights": insights, "counts": counts})

    @pyqtSlot(str, result=str)
    def getAiDayDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        day = str(args.get("day") or "")[:10]
        if not day:
            return json.dumps({"events": [], "byHour": {}, "sessions": [], "total": 0})
        where, params = self._filter(dict(args, start="", end=""))
        rows = self._query(
            "SELECT rowid AS rowid, agent, session_id, ts, kind, role, tool, command, target, program, "
            "exit_code, %s AS series FROM ai_agent_steps WHERE ts >= ? AND ts < date(?, '+1 day') AND %s "
            "AND %s ORDER BY ts" % (SERIES_CASE, ACT_WHERE, where), [day, day] + params)
        by_hour = {k: [0] * 24 for k, _w in SERIES}
        events = []
        for r in rows:
            hh = int(r["ts"][11:13]) if r["ts"][11:13].isdigit() else 0
            if r["series"] in by_hour:
                by_hour[r["series"]][hh] += 1
            if len(events) < EVENTS_MAX:
                events.append({"t": r["ts"], "hour": hh, "series": r["series"], "agent": r["agent"],
                               "session": _session_key(r["agent"], r["session_id"]), "kind": r["kind"],
                               "role": r["role"], "program": r["program"] or "",
                               "what": _one_line(r["command"] or r["target"] or r["tool"], 140),
                               "exit": r["exit_code"], "rowid": r["rowid"]})
        st_where, st_params = self._filter(dict(args, start="", end=""), "st")
        # The session's name (its recorded title, or one built from its first
        # request) where the case has it.
        name_col = "s.name" if "name" in self._session_columns() else "s.title"
        sessions = self._query(
            "SELECT s.agent, s.session_id, s.title, " + name_col + " AS name, s.project_path, s.model, s.app, "
            "s.first_ts, s.last_ts, count(*) AS acts FROM ai_agent_steps st JOIN ai_agent_sessions s ON s.agent = st.agent "
            "AND s.user_name = st.user_name AND s.session_id = st.session_id WHERE st.ts >= ? "
            "AND st.ts < date(?, '+1 day') AND %s GROUP BY s.agent, s.session_id ORDER BY s.first_ts"
            % st_where, [day, day] + st_params)
        for s in sessions:
            s["key"] = _session_key(s["agent"], s["session_id"])
        return json.dumps({"events": events, "byHour": by_hour, "total": len(rows), "sessions": sessions})

    @pyqtSlot(str, result=str)
    def getAiSessionDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        agent, _sep, sid = str(args.get("session") or "").partition("|")
        sess = self._query("SELECT rowid AS rowid, * FROM ai_agent_sessions WHERE agent = ? AND session_id = ? "
                           "ORDER BY last_ts DESC", (agent, sid))
        if not sess:
            return json.dumps({})
        s = sess[0]
        cols = self._step_columns()
        # The story leaves out result rows when each call carries its own
        # output (below), and the count says the same.
        total = self._query("SELECT count(*) AS n FROM ai_agent_steps WHERE agent = ? AND session_id = ?%s"
                            % (" AND kind != 'result'" if "output" in cols else ""), (agent, sid))[0]["n"]
        extra = "".join(", " + c for c in ("approval", "origin", "seq", "turn", "ordered_by") if c in cols)
        if "instruction" in cols:
            extra += ", substr(instruction, 1, 300) AS instruction"
        if "output" in cols:
            extra += ", substr(output, 1, 1000) AS output"
        steps = self._query(
            "SELECT rowid AS rowid, ts, role, kind, tool, command, target, program, exit_code, duration_ms, "
            "status, substr(text, 1, 400) AS text%s FROM ai_agent_steps WHERE agent = ? AND session_id = ? "
            "AND kind != 'result' ORDER BY %s LIMIT %d"
            % (extra, "seq, rowid" if "seq" in cols else "ts, rowid", STEPS_MAX), (agent, sid))
        # A call's result is on the call's own row now (`output`); the result
        # rows are left out of the story - unless the case predates `output`.
        if "output" not in cols:
            steps = self._query(
                "SELECT rowid AS rowid, ts, role, kind, tool, command, target, program, exit_code, "
                "duration_ms, status, substr(text, 1, 400) AS text FROM ai_agent_steps WHERE agent = ? "
                "AND session_id = ? ORDER BY ts, rowid LIMIT %d" % STEPS_MAX, (agent, sid))
        story = [{"t": x["ts"], "role": x["role"], "kind": x["kind"], "tool": x["tool"] or "",
                  "what": _one_line(x["command"] or x["target"] or x["text"], 220),
                  "program": x["program"] or "", "exit": x["exit_code"], "ms": x["duration_ms"],
                  "status": x["status"] or "", "rowid": x["rowid"],
                  "approval": x.get("approval") or "", "origin": x.get("origin") or "",
                  "output": x.get("output") or "", "seq": x.get("seq"), "turn": x.get("turn"),
                  "ordered_by": x.get("ordered_by") or "", "instruction": x.get("instruction") or ""}
                 for x in steps]
        progs: Dict[str, int] = {}
        for x in steps:
            if x["kind"] == "command" and x["program"]:
                for p in str(x["program"]).split(","):
                    p = p.strip()
                    if p:
                        progs[p] = progs.get(p, 0) + 1
        presence = self._presence(progs)
        files = {}
        for x in steps:
            if x["kind"] in ("file_write", "file_edit", "file_read") and x["target"]:
                f = files.setdefault(x["target"], {"path": x["target"], "reads": 0, "changes": 0, "last": ""})
                f["reads" if x["kind"] == "file_read" else "changes"] += 1
                f["last"] = max(f["last"], x["ts"] or "")
        versions = {}
        if "ai_agent_file_versions" in self._tables():
            for v in self._query("SELECT file_path, version, saved_at, size, sha1, backup_path, in_case_path "
                                 "FROM ai_agent_file_versions WHERE agent = ? AND session_id = ?", (agent, sid)):
                versions.setdefault(v["file_path"], []).append(v)
        file_rows = sorted(files.values(), key=lambda f: f["last"], reverse=True)
        for f in file_rows:
            f["versions"] = versions.get(f["path"], [])
            f["credential"] = bool(CREDENTIAL_RX.search(f["path"]))
        pages = [{"t": x["ts"], "tool": x["tool"] or x["kind"], "target": x["target"]} for x in steps
                 if x["kind"] in ("browser", "computer", "screenshot", "web") and x["target"]]
        procs = self._query("SELECT pid, process_start, started_at, kind, entrypoint, version FROM "
                            "ai_agent_processes WHERE agent = ? AND session_id = ?", (agent, sid)) \
            if "ai_agent_processes" in self._tables() else []
        settings = self._query("SELECT scope, setting, value FROM ai_agent_settings WHERE agent = ? "
                               "AND user_name = ? ORDER BY scope, setting LIMIT 300",
                               (agent, s.get("user_name"))) if "ai_agent_settings" in self._tables() else []
        links = []
        try:
            from data.ai_agent_links import AiLinks
            linker = AiLinks(self.case_dir)
            link_steps = linker.steps("agent = ? AND session_id = ?", (agent, sid))
            links = linker.links_for(link_steps)
        except Exception as e:
            link_steps = []
            logger.error("AI links for the session failed: %s", e)
        # SRUM matches a program per hour, so it outnumbers the exact records
        # (Prefetch, BAM, 4688, USN) many times over: those go first, so the cap
        # below never leaves the list holding SRUM rows only.
        links.sort(key=lambda l: (l["source"] == "SRUM", str(l.get("ai_ts") or "")))
        by_source = {}
        # From the steps the links were made from - the story above is capped.
        what_of = {x["rowid"]: _one_line(x.get("command") or x.get("target"), 160)
                   for x in (link_steps or steps)}
        for l in links:
            by_source[l["source"]] = by_source.get(l["source"], 0) + 1
            l["ai_text"] = what_of.get(l["ai_rowid"], "")
        return json.dumps({
            "session": {k: s.get(k) for k in ("agent", "user_name", "session_id", "parent_session_id", "title",
                                              "project_path", "model", "agent_version", "entrypoint", "git_branch",
                                              "approval_mode", "first_ts", "last_ts", "prompts", "commands",
                                              "file_changes", "tool_calls", "app", "pid", "git_sha", "git_origin",
                                              "sandbox_policy", "source_path", "name")},
            "story": story, "storyTotal": total,
            "programs": [{"program": p, "n": n, **presence.get(p, {})}
                         for p, n in sorted(progs.items(), key=lambda kv: kv[1], reverse=True)],
            "files": file_rows[:400], "pages": pages[:400], "processes": procs, "settings": settings,
            "links": links[:800], "linksTotal": len(links), "linksBySource": by_source,
            "raw": _raw(s, "ai_agent_sessions"),
        })

    @pyqtSlot(str, result=str)
    def getAiProgramDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        prog = str(args.get("program") or "").strip().lower()
        if not prog:
            return json.dumps({})
        rows = self._query(
            "SELECT rowid AS rowid, agent, user_name, session_id, ts, command, exit_code, duration_ms, program "
            "FROM ai_agent_steps WHERE kind = 'command' AND role = 'assistant' AND (program = ? OR "
            "program LIKE ? OR program LIKE ? OR program LIKE ?) ORDER BY ts DESC",
            (prog, prog + ",%", "%, " + prog, "%, " + prog + ",%"))
        runs = [{"t": r["ts"], "agent": r["agent"], "session": _session_key(r["agent"], r["session_id"]),
                 "what": _one_line(r["command"], 220), "exit": r["exit_code"], "ms": r["duration_ms"]}
                for r in rows[:STEPS_MAX]]
        links = []
        try:
            from data.ai_agent_links import AiLinks
            linker = AiLinks(self.case_dir)
            # Prefetch keeps a program's last eight run times only, and those
            # are usually the newest - but an agent that ran the program
            # thousands of times since would push them past any cap on the
            # newest steps. So the steps near each Prefetch run go in first,
            # then the newest up to the cap (SRUM, BAM, 4688, USN).
            near = self._near_prefetch_runs(prog, rows)
            seen = {r["rowid"] for r in near}
            pick = near + [r for r in rows if r["rowid"] not in seen][:max(0, 5000 - len(near))]
            steps = [dict(r, kind="command") for r in pick]
            links = [l for l in linker.links_for(steps) if _base_name(l["name"]) == prog]
            links.sort(key=lambda l: (l["source"] == "SRUM", str(l.get("ai_ts") or "")))
        except Exception as e:
            logger.error("AI links for the program failed: %s", e)
        return json.dumps({"program": prog, "runs": runs, "runsTotal": len(rows),
                           "sessions": len({(r["agent"], r["session_id"]) for r in rows}),
                           "presence": self._presence([prog]).get(prog, {}),
                           "links": links[:600], "linksTotal": len(links),
                           "records": _records(rows[:40], "ai_agent_steps", total=len(rows))})

    # ------------------------------------------------------------ helpers
    def _near_prefetch_runs(self, prog, rows, slack_s=300):
        """The agent steps within `slack_s` of one of the program's Prefetch
        run times (prefetch_data.run_times, up to eight per file)."""
        p = os.path.join(self.case_dir, "prefetch_data.db")
        if not os.path.exists(p) or not rows:
            return []
        windows = []
        try:
            conn = sqlite3.connect(p)
            try:
                for exe, times in conn.execute("SELECT executable_name, run_times FROM prefetch_data"):
                    if _base_name(exe) != prog:
                        continue
                    for t in json.loads(times or "[]"):
                        d = _parse_ts(t)
                        if d:
                            windows.append(((d - timedelta(seconds=slack_s)).strftime(TS_FMT),
                                            (d + timedelta(seconds=slack_s)).strftime(TS_FMT)))
            finally:
                conn.close()
        except (sqlite3.Error, ValueError, TypeError) as e:
            logger.info("prefetch run times not read: %s", e)
            return []
        if not windows:
            return []
        # The step times are stored "YYYY-MM-DD HH:MM:SS", so the text compares
        # in time order (50,000 strptime calls cost a second and a half).
        return [r for r in rows
                if any(lo <= str(r["ts"] or "")[:19] <= hi for lo, hi in windows)]

    def _presence(self, programs):
        try:
            from data.ai_agent_links import AiLinks
            return AiLinks(self.case_dir).program_presence(list(programs))
        except Exception as e:
            logger.error("program presence failed: %s", e)
            return {}
