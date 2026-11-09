"""Who was driving each activity: a person, a person from another computer, a
program by itself, or automation (a script, RPA or an agent program) (2026-11-03).

`actor` says whose account an activity ran under. This says what drove it, from
evidence only, and says why in one sentence (`operator_basis`):

  person          keyboard or mouse input was recorded for that person (SRUM's
                  App Timeline) in the program, or anywhere, at that time
  remote_person   the same, during a Remote Desktop sign-in, or started by a
                  remote-control program
  program         the computer's own activity (a system rule, a service or
                  scheduler parent), or a program that ran with no focus and no
                  keyboard or mouse input at that time
  automation      started by a script runtime, an RPA tool, a browser driver or a
                  browser started for automation, or by an agent program
                  (operator_kind 'script'); Crow-Eye Sentinel can refine it
  unknown         nothing in the evidence decides it; no basis is written

What Windows records as input is input delivered to the program. Software can
deliver it too (automation, remote control), so input means "someone or
something typed or clicked", and only the lineage and session facts tell a
person from a program doing it. No input at all is the strong signal: nothing
typed or clicked in that program, or for that person, at that time.
"""

import json
import logging
import os
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "automation_tools.json")
PERSON, REMOTE, PROGRAM, AUTOMATION, UNKNOWN = (
    "person", "remote_person", "program", "automation", "unknown")
SLACK_MINUTES = 5          # an activity just after a window closed still belongs to it
REMOTE_LOGON_TYPES = {"10"}
# Activities whose app_name is the program that ran. For the others (a file
# opened, a folder browsed) the app named is the object, not what was driven.
APP_DRIVEN = {"app_usage", "program_run", "app_launch", "process_created", "network_usage",
              "program_presence", "application_state", "app_error"}


def tools() -> dict:
    try:
        with open(_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("UBA: automation tool list not read: %s", e)
        data = {}
    out = {}
    for key, value in data.items():
        if isinstance(value, list):
            # a tuple, in the file's order: the first matching flag is the one named
            out[key] = tuple(dict.fromkeys(str(v).lower() for v in value))
    return out


def _base(path) -> str:
    p = str(path or "").strip().strip('"').replace("/", "\\")
    return p.rsplit("\\", 1)[-1].lower()


def _dt(ts) -> Optional[datetime]:
    try:
        return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _hhmm(d: datetime) -> str:
    return d.strftime("%H:%M")


# ------------------------------------------------------------ input windows
class InputWindows:
    """SRUM App Timeline rows as windows of focus and input, per person and app.

    One row is one program for one account over a stretch that ends at
    `end_time` and lasted `span_ms` (roughly an hour). Seconds of focus,
    keyboard and mouse input are totals for that stretch."""

    def __init__(self, rows: List[dict]):
        self.rows = rows
        self.by_sid = defaultdict(list)
        for w in rows:
            self.by_sid[w["sid"]].append(w)
        for ws in self.by_sid.values():
            ws.sort(key=lambda w: w["start"])
        self.starts = {sid: [w["start"] for w in ws] for sid, ws in self.by_sid.items()}
        self.by_app = defaultdict(list)
        for w in rows:
            self.by_app[w["app"]].append(w)

    @classmethod
    def load(cls, pool, start: Optional[datetime] = None, end: Optional[datetime] = None) -> "InputWindows":
        """Every App Timeline row, or only those whose record time falls in
        [start, end] (the Who drove it tab's one day)."""
        rows = []
        if pool is None or not pool.has_table("srum", "srum_app_timeline"):
            return cls(rows)
        conn = pool.get("srum")
        cols = ("timestamp", "end_time", "span_ms", "duration_ms", "app_name", "app_path",
                "user_sid", "user_name", "in_focus_s", "user_input_s",
                "keyboard_input_s", "mouse_input_s", "timeline_end", "user_input_timeline",
                "flags", "in_focus_timeline", "keyboard_input_timeline")
        have = [c if pool.has_column("srum", "srum_app_timeline", c) else "NULL" for c in cols]
        where, args = "", ()
        if start is not None and end is not None and have[0] != "NULL":
            where = " WHERE timestamp >= ? AND timestamp <= ?"
            args = (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            cur = conn.execute("SELECT rowid, %s FROM srum_app_timeline%s" % (", ".join(have), where), args)
        except Exception as e:
            logger.warning("UBA: SRUM input windows not read: %s", e)
            return cls(rows)
        from uba.utils import sid_utils
        for r in cur:
            end = _dt(r[2]) or _dt(r[1])
            span = r[3] or r[4]
            try:
                span = float(span)
            except (TypeError, ValueError):
                span = None
            if end is None or not span:
                continue
            num = []
            for v in r[9:13]:
                try:
                    num.append(float(v or 0))
                except (TypeError, ValueError):
                    num.append(0.0)
            rows.append({
                "rowid": r[0], "end": end, "start": end - timedelta(milliseconds=span),
                "app": _base(r[6] or r[5]), "app_label": str(r[5] or _base(r[6])),
                "sid": sid_utils.normalize_sid(r[7]) or "", "user": str(r[8] or ""),
                "focus": num[0], "input": num[1], "keyboard": num[2], "mouse": num[3],
                "runs": input_runs(r[14], slot_end(r[13])),
                "keyboard_runs": input_runs(r[17], slot_end(r[13])),
                # SRUM keeps a foreground record (Flags bit 0x100, the only rows
                # with focus time) and a background record per program and
                # stretch (proven on this machine's rows, 2026-11-03).
                "fg": bool(_int(r[15]) & FOREGROUND_FLAG) or num[0] > 0,
                "focus_end": slot_end(r[13]),
                "focus_bits": _int(r[16]),
                "focus_runs": input_runs(r[16], slot_end(r[13]))})
        return cls(rows)

    def covering(self, sid: str, when: datetime) -> List[dict]:
        """Windows of this account that cover `when` (with the slack)."""
        ws = self.by_sid.get(sid) or []
        if not ws:
            return []
        i = bisect_right(self.starts[sid], when)
        out = []
        for w in ws[max(0, i - 60):i]:
            if w["start"] <= when <= w["end"] + timedelta(minutes=SLACK_MINUTES):
                out.append(w)
        return out

    def covering_app(self, app: str, when: datetime) -> List[dict]:
        """Windows of this program (any account) that cover `when`."""
        return [w for w in self.by_app.get(app) or []
                if w["start"] <= when <= w["end"] + timedelta(minutes=SLACK_MINUTES)]

    def first_last(self):
        if not self.rows:
            return None, None
        return min(w["start"] for w in self.rows), max(w["end"] for w in self.rows)


# SRUM's *_timeline columns, decoded and proven on 2026-11-03 against a scripted
# 30 s on / 30 s off run (decoded runs within ~8 s of the real ones):
# `timeline_end` is Unix time in 4096 ms units, and each *_timeline value is a
# bitmap of up to 64 slots of 4096 ms, bit 0 the slot that ends at
# timeline_end, bit i the slot ending i slots before it - the last ~4.4 minutes
# of the program's stretch at ~4-second resolution.
SLOT_SECONDS = 4.096


def slot_end(units) -> Optional[datetime]:
    try:
        u = int(units)
    except (TypeError, ValueError):
        return None
    if u <= 0:
        return None
    try:
        return datetime(1970, 1, 1) + timedelta(seconds=u * SLOT_SECONDS)
    except OverflowError:
        return None


def is_filler(bits: int) -> bool:
    """SRUM's default fill (0x2A in every byte: 3038287259199220266 as 64 bits,
    707406378 as 32) is not a record. Decoded as a bitmap it reads as a perfect
    on/off rhythm - exactly what the rhythm signal calls a timer."""
    if bits <= 0:
        return False
    raw = bits.to_bytes((bits.bit_length() + 7) // 8, "little")
    return len(raw) >= 4 and all(b == 0x2A for b in raw)


def input_runs(bitmap, end: Optional[datetime]) -> List[tuple]:
    """[(start, stop)] stretches with input, oldest first, from one bitmap."""
    try:
        bits = int(bitmap or 0)
    except (TypeError, ValueError):
        return []
    if is_filler(bits):
        return []
    if not bits or end is None:
        return []
    runs, cur = [], None
    for i in range(bits.bit_length() - 1, -1, -1):
        on = (bits >> i) & 1
        start = end - timedelta(seconds=SLOT_SECONDS * (i + 1))
        if on and cur is None:
            cur = start
        if not on and cur is not None:
            runs.append((cur, start))
            cur = None
    if cur is not None:
        runs.append((cur, end))
    return runs


def input_near(w, when: datetime, seconds: int = 30) -> Optional[datetime]:
    """The moment of input in this window closest to `when` within `seconds`,
    or None (no input that close, or the 4-second record does not reach it)."""
    best = None
    for a, b in w.get("runs") or ():
        if a - timedelta(seconds=seconds) <= when <= b + timedelta(seconds=seconds):
            point = min(max(when, a), b)
            if best is None or abs((point - when).total_seconds()) < abs((best - when).total_seconds()):
                best = point
    return best


FOREGROUND_FLAG = 0x100
FG, BG = "foreground", "background"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def focus_reaches(w, when: datetime) -> bool:
    """Whether the 4-second focus record of this foreground row covers `when`."""
    end = w.get("focus_end")
    if end is None or not w.get("fg"):
        return False
    slots = min(64, max(1, int(((w["end"] - w["start"]).total_seconds()) // SLOT_SECONDS) + 1))
    return end - timedelta(seconds=SLOT_SECONDS * slots) <= when <= end + timedelta(seconds=SLOT_SECONDS)


def app_state(app: str, sid: str, when: datetime, windows: "InputWindows"):
    """("foreground" | "background" | "", basis) of a program at a moment.

    foreground: its 4-second focus record shows it was the window in front then,
    or (when the record does not reach that moment) it had focus in that stretch.
    background: the focus record reaches the moment and shows another window in
    front, or the program had only a background record in that stretch."""
    if not app:
        return "", ""
    ws = [w for w in windows.covering_app(app, when) if not sid or not w["sid"] or w["sid"] == sid]
    if not ws:
        return "", ""
    name = ws[0]["app_label"] or app
    fg = [w for w in ws if w["fg"]]
    if not fg:
        start, end = min(w["start"] for w in ws), max(w["end"] for w in ws)
        return BG, "{} ran only in the background between {} and {} (never the window in front)".format(
            name, _hhmm(start), _hhmm(end))
    reach = [w for w in fg if focus_reaches(w, when)]
    for w in reach:
        for a, b in w["focus_runs"]:
            if a - timedelta(seconds=SLOT_SECONDS) <= when <= b + timedelta(seconds=SLOT_SECONDS):
                return FG, "{} was the window in front at {} (Windows' 4-second focus record)".format(
                    name, when.strftime("%H:%M:%S"))
    if reach:
        return BG, "{} was not the window in front at {}: another program had the focus then (Windows' 4-second focus record)".format(
            name, when.strftime("%H:%M:%S"))
    w = max(fg, key=lambda x: x["focus"])
    return FG, "{} had the focus for {:.0f} s between {} and {}".format(
        name, w["focus"], _hhmm(w["start"]), _hhmm(w["end"]))


def typed(w) -> bool:
    return (w["keyboard"] + w["mouse"] + w["input"]) > 0


def input_words(w) -> str:
    parts = []
    if w["keyboard"]:
        parts.append("{:.0f} s of keyboard".format(w["keyboard"]))
    if w["mouse"]:
        parts.append("{:.0f} s of mouse".format(w["mouse"]))
    if not parts and w["input"]:
        parts.append("{:.0f} s of input".format(w["input"]))
    return " and ".join(parts)


# ------------------------------------------------------------------ verdict
def _lineage(row: dict, details: dict, t: dict):
    """(operator, kind, basis) from the process facts an event names, or None."""
    parent = _base(details.get("parent_process") or details.get("parent"))
    proc = _base(details.get("process_path") or details.get("executable")
                 or details.get("path") or row.get("app_name"))
    cmd = str(details.get("command_line") or "").lower()
    if details.get("agent_transcript"):
        # The agent's own session record says it ran these commands.
        return AUTOMATION, "script", "run by {} (recorded in its session record)".format(
            details["agent_transcript"])
    if parent in t.get("ai_agents", ()) or any(m in cmd for m in t.get("ai_agent_markers", ())):
        # Named as automation here; telling an AI agent apart is Crow-Eye
        # Sentinel's (its agent signals, 2026-11-03).
        who = parent if parent in t.get("ai_agents", ()) else "an automation library on its command line"
        return AUTOMATION, "script", "started by {} (an automation program)".format(who)
    if proc in t.get("browser_drivers", ()):
        return AUTOMATION, "script", "{} is a browser driver (a browser run by software)".format(proc)
    flag = next((f for f in t.get("browser_flags", ()) if f in cmd), None)
    if flag:
        return AUTOMATION, "script", "{} was started with '{}' (a browser run by software)".format(
            proc or "the program", flag.strip("\\"))
    if proc in t.get("rpa", ()) or parent in t.get("rpa", ()):
        return AUTOMATION, "script", "run by {} (a robotic process automation tool)".format(
            parent if parent in t.get("rpa", ()) else proc)
    if parent in t.get("script_runtimes", ()):
        return AUTOMATION, "script", "started by {} (a script runtime)".format(parent)
    if parent in t.get("remote_control", ()):
        return REMOTE, "", "started by {} (a remote-control program)".format(parent)
    if parent in t.get("system_parents", ()):
        return PROGRAM, "", "started by {} on the computer's own behalf".format(parent)
    return None


def _app_of(row: dict, details: dict) -> str:
    for v in (details.get("process_path"), details.get("executable"), row.get("app_name"),
              details.get("application"), details.get("program")):
        b = _base(v)
        if b.endswith(".exe"):
            return b
    a = _base(row.get("app_name"))
    return a + ".exe" if a and "." not in a else a


def verdict(row: dict, windows: InputWindows, sessions=None, t: Optional[dict] = None):
    """(operator, kind, basis) for one stored event row (a dict)."""
    t = t if t is not None else tools()
    d = row.get("details")
    if not isinstance(d, dict):
        try:
            d = json.loads(row.get("details_json") or "{}")
        except ValueError:
            d = {}
    cls = str(row.get("behavior_class") or "")
    if cls in ("system", "system_app") or row.get("actor_type") == "System":
        return PROGRAM, "", "recorded as the computer's own activity"
    found = _lineage(row, d, t)
    if found:
        return found
    when = _dt(row.get("ts_start"))
    if when is None:
        return UNKNOWN, "", ""
    remote = False
    if sessions is not None:
        try:
            from uba.utils.timeparse import epoch_seconds
            s = sessions.session_at(epoch_seconds(row.get("ts_start")))
            remote = bool(s and str(s.logon_type) in REMOTE_LOGON_TYPES)
        except Exception:
            remote = False
    sid = str(row.get("actor_sid") or "")
    app = _app_of(row, d)
    cover = windows.covering(sid, when) if sid else []
    if not cover:
        # No account on the event: the program's own windows still say whether
        # anyone typed or clicked in it then.
        cover = windows.covering_app(app, when) if app else []
        if not cover:
            return UNKNOWN, "", ""
    app_driven = str(row.get("activity") or "") in APP_DRIVEN
    if not app_driven:
        app = ""
    own = [w for w in cover if app and w["app"] == app]
    who = row.get("actor_name") or (own[0]["user"] if own and own[0]["user"] else "this account")
    if own:
        w = max(own, key=lambda x: x["keyboard"] + x["mouse"] + x["input"])
        span = "between {} and {}".format(_hhmm(w["start"]), _hhmm(w["end"]))
        if typed(w):
            near = input_near(w, when)
            if near is not None:
                basis = ("{} received keyboard or mouse input at {} (Windows' 4-second input "
                         "record), {} from {} {}").format(
                             w["app_label"] or app, near.strftime("%H:%M:%S"), input_words(w), who, span)
            else:
                basis = "{} had {} from {} {}".format(w["app_label"] or app, input_words(w), who, span)
            return (REMOTE, "", basis + ", during a Remote Desktop sign-in") if remote else (PERSON, "", basis)
        if not w["focus"]:
            return PROGRAM, "", "{} ran with no focus and no keyboard or mouse input {}".format(
                w["app_label"] or app, span)
    busy = [w for w in cover if typed(w)]
    if app_driven and app and not own:
        start, end = min(w["start"] for w in cover), max(w["end"] for w in cover)
        basis = "{} received no keyboard or mouse input between {} and {}".format(
            app, _hhmm(start), _hhmm(end))
        if busy:
            basis += " (the input went to {})".format(", ".join(
                sorted({w["app_label"] or w["app"] for w in busy})[:3]))
        return PROGRAM, "", basis
    if busy:
        top, names = [], []
        for w in sorted(busy, key=lambda x: -(x["keyboard"] + x["mouse"] + x["input"])):
            name = w["app_label"] or w["app"]
            if name not in names:
                names.append(name)
                top.append(w)
            if len(top) == 3:
                break
        start, end = min(w["start"] for w in top), max(w["end"] for w in top)
        basis = "{} was using the keyboard or mouse (in {}) between {} and {}".format(
            who, ", ".join(names), _hhmm(start), _hhmm(end))
        return (REMOTE, "", basis + ", during a Remote Desktop sign-in") if remote else (PERSON, "", basis)
    start, end = min(w["start"] for w in cover), max(w["end"] for w in cover)
    return PROGRAM, "", "no keyboard or mouse input was recorded for {} between {} and {}".format(
        who, _hhmm(start), _hhmm(end))


def state_of(row: dict, windows: "InputWindows"):
    """Foreground or background of the program a program activity names."""
    if str(row.get("activity") or "") not in APP_DRIVEN:
        return "", ""
    when = _dt(row.get("ts_start"))
    if when is None:
        return "", ""
    d = row.get("details")
    if not isinstance(d, dict):
        try:
            d = json.loads(row.get("details_json") or "{}")
        except ValueError:
            d = {}
    return app_state(_app_of(row, d), str(row.get("actor_sid") or ""), when, windows)


def apply(store, pool, sessions=None) -> Dict[str, int]:
    """Write the verdict and the foreground/background state on every stored
    event; returns counts per operator."""
    windows = InputWindows.load(pool)
    t = tools()
    rows = [dict(r) for r in store.conn.execute(
        "SELECT event_id, rule_id, behavior_class, activity, actor_type, actor_name, actor_sid, "
        "app_name, ts_start, details_json FROM events")]
    updates, counts = [], defaultdict(int)
    for r in rows:
        op, kind, basis = verdict(r, windows, sessions, t)
        state, state_basis = state_of(r, windows)
        # A program that was not the window in front at that moment was not
        # being driven by the keyboard and mouse there, whatever was typed
        # elsewhere at the time.
        if state == BG and op in (PERSON, REMOTE):
            op, kind, basis = PROGRAM, "", state_basis
        counts[op] += 1
        updates.append((op, kind, basis, state, state_basis, r["event_id"]))
    store.conn.executemany(
        "UPDATE events SET operator = ?, operator_kind = ?, operator_basis = ?, app_state = ?, "
        "app_state_basis = ? WHERE event_id = ?",
        updates)
    store.conn.commit()
    return dict(counts)
