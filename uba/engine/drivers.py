"""Who drove it, as views: the data behind the User Behavior "Who drove it" tab.

Three read-only views over what the engine and the parsers already wrote:

  by_person      per account: how many activities a person, a person remotely,
                 a program by itself, a script or an AI agent drove, the agents
                 and folders that account worked with, and the share of
                 automation week by week
  input_layer    one day's SRUM App Timeline per program: seconds of focus,
                 keyboard and mouse input, in front or in the background, and
                 the 4-second runs the bitmaps record (who_drove.input_runs)
  agent_sessions the AI agent sessions that overlap a range, with a mark for
                 each request, command, file change and background-task notice
                 (ai_agents.db, AI_Agent_Claw.py)

Facts only. The desktop names an AI agent only from the agent's own session
record (event_store.DRIVER_SQL); keyboard-only typing and timer rhythm are
Crow-Eye Sentinel's signals (decision 602) and are not drawn here.

input_layer and agent_sessions read the evidence databases and run on a worker
thread (uba_bridge callAsync): each opens its own DbPool, read-only, and closes
it, because SQLite connections belong to the thread that opened them.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional

from uba.engine.event_store import DRIVER_SQL, DRIVERS

logger = logging.getLogger(__name__)

AGENT_SESSIONS_MAX = 80
AGENT_MARKS_MAX = 6000
INPUT_PROGRAMS_MAX = 60


def _secs(day_start: datetime, t: datetime) -> float:
    return max(0.0, min(86400.0, (t - day_start).total_seconds()))


# ---------------------------------------------------------------- by person
def by_person(store, filters: Optional[dict] = None) -> dict:
    """Per account: counts per driver, agents and folders, weekly automation share."""
    where, params = store._build_where(filters or {})
    where_sql = " AND ".join(where) if where else "1=1"
    people: Dict[tuple, dict] = {}

    def person(name, sid, actor_type):
        key = (sid or "", name or "")
        p = people.get(key)
        if p is None:
            # A person: an account with a user SID (local or Entra) or one the
            # engine named a user; the computer's own and service accounts
            # apart, as story_digest's day summary keeps them.
            human = str(sid or "").startswith(("S-1-5-21-", "S-1-12-1-")) or actor_type == "User"
            p = people[key] = {"person": name or "", "actor_sid": sid or "",
                               "kind": "person" if human else ("unattributed" if not name else "computer"),
                               "by_driver": {d: 0 for d in DRIVERS}, "events": 0,
                               "agents": [], "folders": [], "weeks": []}
        return p

    for r in store.conn.execute(
            "SELECT actor_name AS n, actor_sid AS s, MAX(actor_type) AS t, {} AS k, COUNT(*) AS c "
            "FROM events WHERE {} GROUP BY n, s, k".format(DRIVER_SQL, where_sql), params):
        p = person(r["n"], r["s"], r["t"])
        p["by_driver"][r["k"]] = r["c"]
        p["events"] += r["c"]

    weeks = defaultdict(lambda: defaultdict(int))
    for r in store.conn.execute(
            "SELECT actor_name AS n, actor_sid AS s, strftime('%Y-W%W', ts_start) AS w, "
            "{} AS k, COUNT(*) AS c FROM events WHERE ts_start IS NOT NULL AND {} "
            "GROUP BY n, s, w, k".format(DRIVER_SQL, where_sql), params):
        weeks[(r["s"] or "", r["n"] or "")][(r["w"], r["k"])] += r["c"]
    for key, cells in weeks.items():
        if key not in people:
            continue
        by_week = defaultdict(lambda: {"total": 0, "automation": 0})
        for (w, k), c in cells.items():
            by_week[w]["total"] += c
            if k in ("script", "ai_agent"):
                by_week[w]["automation"] += c
        people[key]["weeks"] = [
            {"week": w, "events": v["total"], "automation": v["automation"]}
            for w, v in sorted(by_week.items())]

    agents = defaultdict(lambda: defaultdict(int))
    folders = defaultdict(lambda: defaultdict(int))
    for r in store.conn.execute(
            "SELECT actor_name AS n, actor_sid AS s, details_json AS d FROM events "
            "WHERE rule_id = 'ai_agent_session' AND {}".format(where_sql), params):
        try:
            d = json.loads(r["d"] or "{}")
        except ValueError:
            continue
        key = (r["s"] or "", r["n"] or "")
        agent, folder = d.get("agent"), d.get("project")
        try:
            n = max(1, int(d.get("commands") or 0))      # a session weighs what it ran
        except (TypeError, ValueError):
            n = 1
        if agent:
            agents[key][agent] += n
        if folder:
            folders[key][folder] += n
    for key in people:
        people[key]["agents"] = [{"agent": a, "weight": c} for a, c in
                                 sorted(agents[key].items(), key=lambda kv: -kv[1])[:5]]
        people[key]["folders"] = [{"folder": f, "weight": c} for f, c in
                                  sorted(folders[key].items(), key=lambda kv: -kv[1])[:5]]
    order = {"person": 0, "unattributed": 1, "computer": 2}
    rows = sorted(people.values(), key=lambda p: (order[p["kind"]], -p["events"], p["person"]))
    return {"people": rows, "drivers": list(DRIVERS)}


# ---------------------------------------------------------------- input layer
def input_layer(pool, day: str) -> dict:
    """One day of SRUM App Timeline per program, with the decoded 4-second runs."""
    from uba.engine.who_drove import InputWindows, SLOT_SECONDS
    try:
        day_start = datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError):
        return {"available": False, "reason": "No day was chosen.", "programs": []}
    if pool is None or not pool.has_table("srum", "srum_app_timeline"):
        return {"available": False, "day": day, "programs": [],
                "reason": "This case has no SRUM App Timeline: SRUM was not parsed, or "
                          "Windows was not recording it (the Diagnostic Policy Service off)."}
    day_end = day_start + timedelta(days=1)
    windows = InputWindows.load(pool, start=day_start - timedelta(days=1), end=day_end + timedelta(days=1))
    progs: Dict[str, dict] = {}
    for w in windows.rows:
        if w["end"] < day_start or w["start"] >= day_end:
            continue
        p = progs.get(w["app"])
        if p is None:
            p = progs[w["app"]] = {
                "app": w["app"], "label": w["app_label"] or w["app"], "users": set(),
                "focus_s": 0.0, "keyboard_s": 0.0, "mouse_s": 0.0, "input_s": 0.0,
                "stretches": [], "focus_runs": [], "keyboard_runs": [], "input_runs": [],
                "rowids": []}
        if w["user"]:
            p["users"].add(w["user"])
        for k_out, k_in in (("focus_s", "focus"), ("keyboard_s", "keyboard"),
                            ("mouse_s", "mouse"), ("input_s", "input")):
            p[k_out] += w[k_in]
        p["stretches"].append([_secs(day_start, w["start"]), _secs(day_start, w["end"]),
                               bool(w["fg"])])
        for k_out, k_in in (("focus_runs", "focus_runs"), ("keyboard_runs", "keyboard_runs"),
                            ("input_runs", "runs")):
            for a, b in w.get(k_in) or []:
                if b >= day_start and a < day_end:
                    p[k_out].append([_secs(day_start, a), _secs(day_start, b)])
        p["rowids"].append(w["rowid"])
    out = []
    for p in progs.values():
        p["users"] = sorted(p["users"])
        p["in_front"] = any(s[2] for s in p["stretches"])
        p["rowids"] = p["rowids"][:200]
        out.append(p)
    out.sort(key=lambda p: -(p["focus_s"] + p["input_s"]))
    total = len(out)
    return {"available": True, "day": day, "programs": out[:INPUT_PROGRAMS_MAX],
            "total_programs": total, "slot_seconds": SLOT_SECONDS,
            "reason": "" if out else "SRUM recorded no program on this day."}


# ---------------------------------------------------------------- agent sessions
# ("system", "prompt"): a prompt nobody typed - a scheduled task, a program
# through claude -p, the program resuming; an "instruction" outside a
# sub-agent's transcript is another agent session's message ("peer").
_MARK_KIND = {("user", "prompt"): "request", ("agent", "prompt"): "instruction",
              ("system", "prompt"): "sent",
              ("assistant", "command"): "command", ("user", "command"): "own_command",
              ("assistant", "file_write"): "file", ("assistant", "file_edit"): "file",
              ("system", "notice"): "notice"}


def agent_sessions(pool, start: str, end: str) -> dict:
    """AI agent sessions overlapping [start, end], each with its marks."""
    if pool is None or not pool.has_table("ai_agents", "ai_agent_sessions"):
        return {"available": False, "sessions": [],
                "reason": "No AI agent session records in this case: no Claude Code, Gemini CLI or "
                          "Codex sessions were found in any user profile, or AI agents were not parsed."}
    conn = pool.get("ai_agents")
    total = conn.execute("SELECT COUNT(*) FROM ai_agent_sessions WHERE last_ts >= ? AND first_ts <= ?",
                         (start, end)).fetchone()[0]
    rows = conn.execute(
        "SELECT rowid, agent, user_name, session_id, parent_session_id, title, project_path, model, "
        "approval_mode, first_ts, last_ts, prompts, commands, file_changes FROM ai_agent_sessions "
        "WHERE last_ts >= ? AND first_ts <= ? ORDER BY (commands + file_changes) DESC, first_ts "
        "LIMIT ?", (start, end, AGENT_SESSIONS_MAX)).fetchall()
    sessions = {}
    for r in rows:
        sessions[r[3]] = {
            "rowid": r[0], "agent": r[1], "user": r[2], "session_id": r[3], "parent": r[4] or "",
            "title": r[5] or "", "project": r[6] or "", "model": r[7] or "", "approval_mode": r[8] or "",
            "first_ts": r[9], "last_ts": r[10], "prompts": r[11] or 0, "commands": r[12] or 0,
            "file_changes": r[13] or 0, "marks": [], "marks_total": 0}
    if sessions:
        ids = list(sessions)
        marks_q = (
            "SELECT rowid, session_id, ts, role, kind, substr(command, 1, 160), substr(target, 1, 160), "
            "substr(text, 1, 160), is_sidechain FROM ai_agent_steps WHERE ts >= ? AND ts <= ? "
            "AND session_id IN ({}) AND (kind IN ('command', 'file_write', 'file_edit', 'notice') "
            "OR (kind = 'prompt' AND role IN ('user', 'agent', 'system'))) ORDER BY ts").format(
                ",".join("?" for _ in ids))
        seen = set()
        kept = 0
        for rowid, sid, ts, role, kind, command, target, text, side in conn.execute(marks_q, [start, end] + ids):
            mk = _MARK_KIND.get((role, kind))
            if mk == "instruction" and not side:
                mk = "peer"
            s = sessions.get(sid)
            if not mk or s is None:
                continue
            s["marks_total"] += 1
            if kept >= AGENT_MARKS_MAX:
                continue
            words = command if mk in ("command", "own_command") else (target if mk == "file" else text)
            key = (sid, ts, mk, words)
            if key in seen:                        # a resumed session repeats its steps
                continue
            seen.add(key)
            s["marks"].append({"rowid": rowid, "ts": ts, "kind": mk, "words": " ".join(str(words or "").split())})
            kept += 1
    out = sorted(sessions.values(), key=lambda s: (s["parent"] != "", s["first_ts"] or ""))
    return {"available": True, "sessions": out, "total_sessions": total,
            "shown_sessions": len(out), "marks_cap": AGENT_MARKS_MAX,
            "reason": "" if out else "No AI agent session overlaps this time."}
