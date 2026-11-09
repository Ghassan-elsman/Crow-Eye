"""AI agent sessions in the Activity Story (ai_agents.db, AI_Agent_Claw.py).

Two rules:
  ai_agent_session  one activity per session: which agent worked for whom, in
                    which folder, from when to when, and how much it did
  ai_agent_turn     one activity per request: what the person asked, and the
                    commands the agent ran and the files it changed to answer
                    it - every command row is the evidence

The session record is the agent's own, written as it worked, so a command in
it is proof that the agent ran it, not a person at the keyboard. The turn's
details name the agent (`agent_transcript`), which who_drove.py reads as
automation; Crow-Eye Sentinel names it an AI agent.

Prompts and commands are quoted as the parser kept them (secrets masked at
parse time) and cut short in the sentence; the full text is in the rows.
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List

from uba.engine.models import BehaviorEvent, EvidenceRef
from uba.engine.extractors.artifacts import _mk, _rows, _hive_actor
from uba.utils.db_access import table_columns
from uba.utils.timeparse import normalize_ts

logger = logging.getLogger(__name__)

PROMPT_WORDS = 140        # characters of a request quoted in a sentence
COMMANDS_SHOWN = 3        # commands named in a sentence
CAVEAT_TRANSCRIPT = (
    "Taken from the agent's own session record. A command in it was run by the "
    "agent with this account's rights; whether the person approved each one "
    "depends on the approval mode the session ran in.")


def _short(text, n=PROMPT_WORDS):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n - 3].rstrip() + "..."


# `cd "<folder>" && ...` - the folder is already in the sentence.
_CD_PREFIX = re.compile(r"""^\s*cd\s+(?:"[^"]*"|'[^']*'|\S+)\s*(?:&&|;)\s*""")


def _cmd(text, n=80):
    t = str(text or "")
    while True:
        u = _CD_PREFIX.sub("", t, count=1)
        if u == t:
            break
        t = u
    return _short(t, n)


def _span(first, last):
    """'at 14:02', 'between 14:02 and 14:09', or with dates across midnight."""
    a, b = str(first or ""), str(last or "")
    if not b or a[:16] == b[:16]:
        return "at {}".format(a[11:16])
    if a[:10] == b[:10]:
        return "between {} and {}".format(a[11:16], b[11:16])
    return "between {} and {}".format(a[:16], b[:16])


def _folder(path):
    p = str(path or "").rstrip("\\/")
    return p or "an unknown folder"


def _plural(n, word):
    return "{} {}{}".format(n, word, "" if n == 1 else "s")


def ai_agent_sessions(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    if not ctx.pool.has_table("ai_agents", "ai_agent_sessions"):
        return []
    rows = _rows(ctx, "ai_agents",
                 "SELECT rowid, agent, user_name, session_id, parent_session_id, title, "
                 "project_path, model, agent_version, approval_mode, first_ts, last_ts, "
                 "prompts, commands, file_changes, tool_calls FROM ai_agent_sessions")
    # A sub-agent's work is part of the session that started it.
    sub = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r[4]:
            s = sub[(r[1], r[2], r[4])]
            s[0] += 1
            s[1] += int(r[13] or 0)
            s[2] += int(r[14] or 0)
    events = []
    for (rowid, agent, user, sid, parent, title, project, model, version, approval,
         first, last, prompts, commands, changes, tools) in rows:
        if parent:
            continue
        ts = normalize_ts(first)
        if not ts:
            continue
        n_sub, sub_cmd, sub_chg = sub.get((agent, user, sid), (0, 0, 0))
        commands = int(commands or 0) + sub_cmd
        changes = int(changes or 0) + sub_chg
        actor = _hive_actor(ctx, "the AI agent's session record", owner=user or None)
        who = actor[1] or user or "A user"
        parts = []
        if prompts:
            parts.append("made {}".format(_plural(int(prompts), "request")))
        if commands:
            parts.append("ran {}".format(_plural(commands, "command")))
        if changes:
            parts.append("changed files {}".format(_plural(changes, "time")))
        if n_sub:
            parts.append("started {}".format(_plural(n_sub, "sub-agent")))
        text = "{} worked with {} in {} {}".format(who, agent, _folder(project), _span(first, last))
        if title:
            text += " ('{}')".format(_short(title, 80))
        if parts:
            text += ": " + ", ".join(parts)
        events.append(_mk(
            rule, ctx, ts, actor, text,
            [EvidenceRef(db="ai_agents", table="ai_agent_sessions", rowids=[rowid], count=1)],
            ts_end=normalize_ts(last) or ts, caveat=CAVEAT_TRANSCRIPT, app_name=agent,
            details={"agent": agent, "session_id": sid, "project": project or "",
                     "title": title or "", "model": model or "", "agent_version": version or "",
                     "approval_mode": approval or "", "prompts": int(prompts or 0),
                     "commands": commands, "file_changes": changes, "sub_agents": n_sub,
                     "tool_calls": int(tools or 0), "user": user or ""}))
    return events


def _flush(rule, ctx, turn, events):
    cmds, files = turn["commands"], turn["files"]
    if not cmds and not files:
        return
    first, last = turn["first"], turn["last"]
    ts = normalize_ts(first)
    if not ts:
        return
    actor = _hive_actor(ctx, "the AI agent's session record", owner=turn["user"] or None)
    who = actor[1] or turn["user"] or "the user"
    agent = turn["agent"]
    side = turn["sidechain"]
    doer = "A {} sub-agent".format(agent) if side else agent
    did = []
    if cmds:
        shown = "; ".join("`{}`".format(_cmd(c)) for c, _ in cmds[:COMMANDS_SHOWN])
        more = len(cmds) - COMMANDS_SHOWN
        did.append("ran {} ({}{})".format(
            _plural(len(cmds), "command"), shown,
            "; and {} more".format(more) if more > 0 else ""))
    if files:
        names = sorted({f for f, _ in files})
        did.append("changed {}{}".format(
            _plural(len(names), "file"),
            " ({})".format(", ".join(n.replace("\\", "/").rsplit("/", 1)[-1] for n in names[:3]))
            if names else ""))
    text = "{} {} in {} {}".format(doer, " and ".join(did), _folder(turn["cwd"]), _span(first, last))
    if turn.get("session_name"):
        # Which session was ordered to do it, by name.
        text += " (session '{}')".format(_short(turn["session_name"], 80))
    sender = _sender(turn)
    if turn["prompt"] and sender:
        # Not the person: a scheduled task, another agent session, a program.
        text += ", after {} sent: \"{}\"".format(sender, _short(turn["prompt"]))
    elif turn["prompt"]:
        asker = "the main agent" if side else who
        text += ", after {} asked: \"{}\"".format(asker, _short(turn["prompt"]))
    elif turn.get("woken"):
        text += ", on its own after a background task it started had finished (no new request)"
    rowids = [r for _, r in cmds] + [r for _, r in files]
    if turn["prompt_rowid"]:
        rowids.insert(0, turn["prompt_rowid"])
    events.append(_mk(
        rule, ctx, ts, actor, text,
        [EvidenceRef(db="ai_agents", table="ai_agent_steps", rowids=rowids[:100], count=len(rowids))],
        ts_end=normalize_ts(last) or ts, caveat=CAVEAT_TRANSCRIPT, app_name=agent,
        count=len(cmds) + len(files),
        details={"agent": agent, "agent_transcript": agent, "session_id": turn["session"],
                 "sub_agent": bool(side), "cwd": turn["cwd"] or "",
                 "started_by": (sender or "request") if turn["prompt"] else (
                     "background task" if turn.get("woken") else ""),
                 "origin": turn.get("origin") or "",
                 "session_name": turn.get("session_name") or "",
                 "prompt": _short(turn["prompt"], 500),
                 "commands": [_short(c, 300) for c, _ in cmds[:20]],
                 "files": sorted({f for f, _ in files})[:20],
                 "command_count": len(cmds), "file_count": len({f for f, _ in files}),
                 "user": turn["user"] or ""}))


def _sender(turn) -> str:
    """Who sent the prompt that started a turn, when it was not the person
    (nor the main agent instructing its own sub-agent): '' otherwise."""
    role, origin = turn.get("prompt_role") or "", turn.get("origin") or ""
    if role == "system":
        o = origin.lower()
        if o.startswith("scheduled task"):
            return "a " + origin                    # "a scheduled task 7d874395"
        if o.startswith("a program"):
            return "a program through claude -p (not known to be the person)"
        if o.startswith("automatic continuation"):
            return "the program itself, resuming the agent"
        return "the program (not the person)"
    if role == "agent" and not turn.get("sidechain"):
        return origin or "another agent session"
    return ""


def ai_agent_turns(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    if not ctx.pool.has_table("ai_agents", "ai_agent_steps"):
        return []
    # `origin` (who sent a prompt) exists in cases parsed since 2026-11-04.
    conn = ctx.pool.get("ai_agents")
    have = {c.lower() for c in table_columns(conn, "ai_agent_steps")} if conn is not None else set()
    has_origin = "origin" in have
    rows = _rows(ctx, "ai_agents",
                 "SELECT rowid, agent, user_name, session_id, step_id, ts, role, kind, command, "
                 "target, cwd, is_sidechain, substr(text, 1, 600), {}, {} FROM ai_agent_steps "
                 "WHERE kind IN ('prompt', 'notice', 'command', 'file_write', 'file_edit') "
                 "ORDER BY agent, user_name, session_id, ts, rowid".format(
                     "origin" if has_origin else "''",
                     "session_name" if "session_name" in have else "''"))
    events: List[BehaviorEvent] = []
    seen: Dict[str, set] = defaultdict(set)   # a resumed or forked session repeats steps
    turn = None
    for (rowid, agent, user, session, step_id, ts, role, kind, command, target, cwd,
         side, text, origin, session_name) in rows:
        key = (agent, user, session)
        # A prompt starts a turn whoever sent it: the person, the main agent
        # (to its sub-agent), another agent session, a scheduled task or a
        # program (role system). Who it was is told with the turn.
        starts = kind == "prompt" and role in ("user", "agent", "system")
        # A background task's notice wakes the agent with no new request: what
        # it does next is its own continuation, told apart from a request.
        woken = kind == "notice"
        # A resumed or forked session repeats earlier steps. A repeated request
        # still ends the turn before it - skipped, it let one turn run on for
        # weeks and take in every command until the next new request - and
        # what follows it is repeated too, so it adds nothing.
        repeat = step_id in seen[agent]
        seen[agent].add(step_id)
        if repeat and not (starts or woken):
            continue
        if turn is None or turn["key"] != key or starts or woken:
            if turn is not None:
                _flush(rule, ctx, turn, events)
            turn = {"key": key, "agent": agent, "user": user, "session": session,
                    "sidechain": int(side or 0), "cwd": cwd or "", "first": ts, "last": ts,
                    "prompt": text if starts and not repeat else "",
                    "prompt_rowid": rowid if starts and not repeat else None,
                    "prompt_role": role if starts else "", "origin": origin if starts else "",
                    "session_name": session_name or "",
                    "woken": woken, "commands": [], "files": []}
            if starts or woken:
                continue
        if role != "assistant":
            continue
        if ts and (not turn["first"] or ts < turn["first"]):
            turn["first"] = ts
        if ts and ts > turn["last"]:
            turn["last"] = ts
        if cwd and not turn["cwd"]:
            turn["cwd"] = cwd
        if kind == "command" and command:
            turn["commands"].append((command, rowid))
        elif kind in ("file_write", "file_edit") and target:
            turn["files"].append((target, rowid))
    if turn is not None:
        _flush(rule, ctx, turn, events)
    return events
