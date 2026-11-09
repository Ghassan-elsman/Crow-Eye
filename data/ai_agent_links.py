"""What Windows recorded of what an AI agent did.

An AI agent's own record (ai_agents.db) says what it ran, changed and opened.
Windows keeps its own record of the same acts, written by different code for a
different purpose. This module puts the two side by side: each AI step with the
system rows that record the same program, file or page at the same time.

Every link names the rule that made it and both rows, and says how far apart in
time they are. There is no score: a link is a fact about two records ("the
agent ran `python` at 14:00:05; Prefetch records PYTHON.EXE running at
14:00:06"), and the investigator judges it.

  AI step                      Windows record                      window
  command, its `program`       Prefetch run times                  5 s before the step to its end
                               BAM last execution                  same
                               Security 4688 (new process name)    same
                               SRUM app usage (hourly)             the hour holding the step
  file_write / file_edit       USN journal changes to that name    2 min either side
  browser (URL)                browser history visits              1 min either side

AmCache and ShimCache hold no run time; `program_presence` reports whether
they know the program at all.

Read-only. Every call opens its own connections, so a bridge may call it from
a worker thread.
"""

import datetime
import json
import ntpath
import os
import sqlite3
from typing import Dict, Iterable, List, Optional

AI_DB = "ai_agents.db"
LINK_KINDS = ("command", "file_write", "file_edit", "browser")
BEFORE_S = 5            # a program starts just after the agent's call
DEFAULT_RUN_S = 60      # a command with no recorded duration
FILE_WINDOW_S = 120
URL_WINDOW_S = 60

RULES = {
    "prefetch": "Prefetch records the program running inside the step's run",
    "bam": "BAM's last execution of the program falls inside the step's run",
    "event_4688": "a Security 4688 event creates the program inside the step's run",
    "srum": "SRUM counts the program in the hour holding the step",
    "usn": "the USN journal records a change to the same file name within 2 minutes",
    "browser": "the browser history has a visit to the same page within 1 minute",
}


def _epoch(ts) -> Optional[float]:
    if not ts:
        return None
    s = str(ts).strip().replace("T", " ")[:19]
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def _ts(epoch) -> str:
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect(path):
    from urllib.request import pathname2url
    return sqlite3.connect("file:%s?mode=ro" % pathname2url(path), uri=True)


def _url_key(url) -> str:
    u = str(url or "").strip().lower()
    for p in ("https://", "http://"):
        if u.startswith(p):
            u = u[len(p):]
    return u.rstrip("/")


class AiLinks:
    """Links for one case's Target_Artifacts folder."""

    def __init__(self, artifacts_dir):
        self.dir = artifacts_dir

    def _db(self, name):
        p = os.path.join(self.dir, name)
        return p if os.path.isfile(p) else None

    # ------------------------------------------------------------- AI steps
    def steps(self, where="", params=(), limit=5000) -> List[dict]:
        """AI steps that can have a Windows record (LINK_KINDS), as dicts with
        their rowid. `where` narrows them (an SQL condition on ai_agent_steps)."""
        path = self._db(AI_DB)
        if not path:
            return []
        conn = _connect(path)
        conn.row_factory = sqlite3.Row
        try:
            sql = ("SELECT rowid AS rowid, agent, session_id, step_id, ts, kind, tool, command, target, "
                   "program, exit_code, duration_ms FROM ai_agent_steps WHERE kind IN (%s)"
                   % ",".join("?" * len(LINK_KINDS)))
            args = list(LINK_KINDS)
            if where:
                sql += " AND (%s)" % where
                args += list(params)
            sql += " ORDER BY ts LIMIT %d" % int(limit)
            return [dict(r) for r in conn.execute(sql, args)]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    # ------------------------------------------------------------------ links
    def links_for(self, steps: Iterable[dict]) -> List[dict]:
        """Every Windows record that matches one of `steps`, by the RULES."""
        steps = [s for s in steps if _epoch(s.get("ts")) is not None]
        out = []
        runs = []                                    # (step, start, end, programs)
        files = []                                   # (step, t, name)
        pages = []                                   # (step, t, url)
        for s in steps:
            t = _epoch(s["ts"])
            if s.get("kind") == "command" and s.get("program"):
                dur = (s.get("duration_ms") or 0) / 1000.0 or DEFAULT_RUN_S
                progs = [p.strip().lower() for p in str(s["program"]).split(",") if p.strip()]
                runs.append((s, t - BEFORE_S, t + max(dur, 1.0) + 2, progs))
            elif s.get("kind") in ("file_write", "file_edit") and s.get("target"):
                name = ntpath.basename(str(s["target"]).replace("/", "\\")).lower()
                if name:
                    files.append((s, t, name))
            elif s.get("kind") == "browser" and str(s.get("target") or "").lower().startswith("http"):
                pages.append((s, t, _url_key(s["target"])))
        if runs:
            out += self._prefetch(runs) + self._bam(runs) + self._event_4688(runs) + self._srum(runs)
        if files:
            out += self._usn(files)
        if pages:
            out += self._browser(pages)
        # One link per step and Windows fact: SRUM writes a row per user and
        # interface for the same hour, the journal a row per reason flag for the
        # same change - the same fact, more than once.
        seen, unique = set(), []
        for link in out:
            key = (link["ai_rowid"], link["source"], link["ts"], str(link["name"]).lower())
            if key in seen:
                continue
            seen.add(key)
            unique.append(link)
        unique.sort(key=lambda l: (l["ai_ts"], l["source"]))
        return unique

    @staticmethod
    def _link(step, rule, source, db, table, rowid, ts, name, t_ai):
        t = _epoch(ts)
        return {"ai_rowid": step.get("rowid"), "ai_ts": step.get("ts"), "ai_kind": step.get("kind"),
                "ai_agent": step.get("agent"), "ai_session": step.get("session_id"),
                "rule": rule, "rule_text": RULES[rule], "source": source, "db": db, "table": table,
                "rowid": rowid, "ts": ts, "name": name,
                "delta_s": None if t is None or t_ai is None else round(t - t_ai, 1)}

    def _prefetch(self, runs):
        path = self._db("prefetch_data.db")
        if not path:
            return []
        wanted = {p for _s, _a, _b, progs in runs for p in progs}
        conn = _connect(path)
        out = []
        try:
            rows = conn.execute("SELECT rowid, executable_name, run_times, last_executed FROM prefetch_data"
                                ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        by_prog: Dict[str, list] = {}
        for rid, exe, run_times, last in rows:
            prog = str(exe or "").lower()
            prog = prog[:-4] if prog.endswith(".exe") else prog
            if prog not in wanted:
                continue
            try:
                times = json.loads(run_times) if run_times else []
            except ValueError:
                times = []
            for rt in set(times + ([last] if last else [])):
                e = _epoch(rt)
                if e is not None:
                    by_prog.setdefault(prog, []).append((e, rt, rid, exe))
        for step, lo, hi, progs in runs:
            t = _epoch(step["ts"])
            for p in progs:
                for e, rt, rid, exe in by_prog.get(p, ()):
                    if lo <= e <= hi:
                        out.append(self._link(step, "prefetch", "Prefetch", "prefetch_data.db",
                                              "prefetch_data", rid, rt, exe, t))
        return out

    def _bam(self, runs):
        path = self._db("registry_data.db")
        if not path:
            return []
        conn = _connect(path)
        try:
            rows = conn.execute("SELECT rowid, process_path, last_execution FROM BAM").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        by = {}
        for rid, pp, last in rows:
            name = ntpath.basename(str(pp or "")).lower()
            name = name[:-4] if name.endswith(".exe") else name
            e = _epoch(last)
            if name and e is not None:
                by.setdefault(name, []).append((e, last, rid, pp))
        out = []
        for step, lo, hi, progs in runs:
            t = _epoch(step["ts"])
            for p in progs:
                for e, last, rid, pp in by.get(p, ()):
                    if lo <= e <= hi:
                        out.append(self._link(step, "bam", "BAM", "registry_data.db", "BAM", rid, last, pp, t))
        return out

    def _event_4688(self, runs):
        path = self._db("Log_Claw.db")
        if not path:
            return []
        lo = min(r[1] for r in runs)
        hi = max(r[2] for r in runs)
        conn = _connect(path)
        try:
            rows = conn.execute(
                "SELECT rowid, EventTimestampUTC, EventDescription FROM SecurityLogs WHERE EventID = 4688 "
                "AND EventTimestampUTC BETWEEN ? AND ?", (_ts(lo), _ts(hi))).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        events = []
        for rid, ts, desc in rows:
            text = str(desc or "")
            i = text.find("New Process Name:")
            if i < 0:
                continue                     # this log's text does not name the process
            name = ntpath.basename(text[i + 17:].split("\n")[0].strip()).lower()
            name = name[:-4] if name.endswith(".exe") else name
            e = _epoch(ts)
            if name and e is not None:
                events.append((e, ts, rid, name))
        out = []
        for step, lo, hi, progs in runs:
            t = _epoch(step["ts"])
            for e, ts, rid, name in events:
                if name in progs and lo <= e <= hi:
                    out.append(self._link(step, "event_4688", "Security 4688", "Log_Claw.db", "SecurityLogs",
                                          rid, ts, name, t))
        return out

    def _srum(self, runs):
        path = self._db("srum_data.db")
        if not path:
            return []
        names = sorted({p + ".exe" for _s, _a, _b, progs in runs for p in progs})
        lo = min(r[1] for r in runs)
        hi = max(r[2] for r in runs) + 3600
        conn = _connect(path)
        try:
            rows = conn.execute(
                "SELECT rowid, timestamp, app_name FROM srum_application_usage WHERE timestamp BETWEEN ? AND ? "
                "AND lower(app_name) IN (%s)" % ",".join("?" * len(names)), [_ts(lo), _ts(hi)] + names
            ).fetchall() if names else []
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        by = {}
        for rid, ts, app in rows:
            e = _epoch(ts)
            if e is not None:
                by.setdefault(str(app).lower()[:-4], []).append((e, ts, rid, app))
        out = []
        for step, lo_s, _hi_s, progs in runs:
            t = _epoch(step["ts"])
            for p in progs:
                # SRUM writes an hour's totals at its end: the step is inside
                # the hour that ends at the row's time
                for e, ts, rid, app in by.get(p, ()):
                    if e - 3600 <= t <= e:
                        out.append(self._link(step, "srum", "SRUM", "srum_data.db", "srum_application_usage",
                                              rid, ts, app, t))
        return out

    def _usn(self, files):
        path = self._db("USN_journal.db")
        if not path:
            return []
        names = {n for _s, _t, n in files}
        lo = min(t for _s, t, _n in files) - FILE_WINDOW_S
        hi = max(t for _s, t, _n in files) + FILE_WINDOW_S
        conn = _connect(path)
        try:
            rows = conn.execute("SELECT rowid, timestamp, filename, reason FROM journal_events "
                                "WHERE timestamp BETWEEN ? AND ?", (_ts(lo), _ts(hi))).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        by = {}
        for rid, ts, fname, reason in rows:
            n = str(fname or "").lower()
            if n in names:
                e = _epoch(ts)
                if e is not None:
                    by.setdefault(n, []).append((e, ts, rid, fname, reason))
        out = []
        for step, t, name in files:
            # one link per second the file changed in (the journal writes a
            # row per reason flag), its reasons together, nearest three only
            when = {}
            for e, ts, rid, fname, reason in by.get(name, ()):
                if abs(e - t) <= FILE_WINDOW_S:
                    if ts not in when:
                        when[ts] = [e, rid, fname, []]
                    if reason and reason not in when[ts][3]:
                        when[ts][3].append(reason)
            for ts, (e, rid, fname, reasons) in sorted(when.items(), key=lambda kv: abs(kv[1][0] - t))[:3]:
                link = self._link(step, "usn", "USN journal", "USN_journal.db", "journal_events", rid, ts,
                                  fname, t)
                link["detail"] = " ; ".join(reasons)
                out.append(link)
        return out

    def _browser(self, pages):
        path = self._db("browser_analysis.db")
        if not path:
            return []
        lo = min(t for _s, t, _u in pages) - URL_WINDOW_S
        hi = max(t for _s, t, _u in pages) + URL_WINDOW_S
        conn = _connect(path)
        try:
            rows = conn.execute("SELECT rowid, visit_time, url, browser FROM browser_history "
                                "WHERE visit_time BETWEEN ? AND ?", (_ts(lo), _ts(hi))).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        out = []
        for step, t, key in pages:
            for rid, ts, url, browser in rows:
                e = _epoch(ts)
                if e is not None and abs(e - t) <= URL_WINDOW_S and _url_key(url) == key:
                    link = self._link(step, "browser", "Browser history", "browser_analysis.db",
                                      "browser_history", rid, ts, url, t)
                    link["detail"] = browser
                    out.append(link)
        return out

    # ------------------------------------------------------------- presence
    def program_presence(self, programs: Iterable[str]) -> Dict[str, dict]:
        """For each program: what the system knows of it with no time attached -
        Prefetch run count and last run, AmCache entries (path, SHA-1 FileId),
        ShimCache entries."""
        progs = sorted({str(p).strip().lower() for p in programs if p})
        out = {p: {"prefetch_runs": 0, "prefetch_last": "", "amcache": [], "shimcache": 0} for p in progs}
        if not progs:
            return out
        path = self._db("prefetch_data.db")
        if path:
            conn = _connect(path)
            try:
                for exe, count, last in conn.execute(
                        "SELECT executable_name, run_count, last_executed FROM prefetch_data"):
                    p = str(exe or "").lower()
                    p = p[:-4] if p.endswith(".exe") else p
                    if p in out:
                        out[p]["prefetch_runs"] += int(count or 0)
                        if str(last or "") > out[p]["prefetch_last"]:
                            out[p]["prefetch_last"] = str(last)
            except sqlite3.Error:
                pass
            finally:
                conn.close()
        path = self._db("amcache.db")
        if path:
            conn = _connect(path)
            try:
                for name, lpath, fid in conn.execute(
                        "SELECT name, lower_case_long_path, file_id FROM InventoryApplicationFile WHERE "
                        "lower(name) IN (%s)" % ",".join("?" * len(progs)), [p + ".exe" for p in progs]):
                    p = str(name).lower()[:-4]
                    if p in out and len(out[p]["amcache"]) < 5:
                        out[p]["amcache"].append({"path": lpath, "file_id": fid})
            except sqlite3.Error:
                pass
            finally:
                conn.close()
        path = self._db("shimcache.db")
        if path:
            conn = _connect(path)
            try:
                for (fname,) in conn.execute("SELECT filename FROM shimcache_entries"):
                    p = str(fname or "").lower()
                    p = p[:-4] if p.endswith(".exe") else p
                    if p in out:
                        out[p]["shimcache"] += 1
            except sqlite3.Error:
                pass
            finally:
                conn.close()
        return out
