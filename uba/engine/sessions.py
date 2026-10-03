"""
Interactive session reconstruction from Security 4624 / 4634 / 4647 events.

Sessions provide *context annotations* for other events ("during Gass3's
interactive session") — they are never used to attribute an action to a
user by themselves (an unattributed file write during a session stays
unattributed; the session is shown as a subtitle only).

Only interactive logon types (2 local, 10 RDP, 11 cached) OPEN a session:
service/network logons (types 3/4/5) happen constantly in the background and
say nothing about a human presence. Type 7 (workstation unlock) does not open
a session either — it *resumes* the one already running, so it is recorded on
that session instead of creating an overlapping second window.

Three things this module is deliberately careful about, because each one
produced a confidently wrong answer before:

1. **Pairing is two-pass.** Windows writes the logoff in the same second as
   the logon, and the row order inside that second reflects parser insertion
   order, not event order. A single pass that popped the open logon when it
   met the logoff therefore discarded *every* logoff on a real case (10 of 10),
   so no session ever closed. Logons and logoffs are now collected first and
   paired by LogonId afterwards, so row order cannot matter.

2. **An unfinished session has no end, and no duration.** ``end_ts`` is set
   only from a real logoff. When none was recorded the session stays open
   (``end_basis="open"``) and ``duration_seconds`` is None — the old code
   capped it at the last log timestamp, which turned three unfinished sessions
   into reported 82.2 / 31.4 / 3.9-hour sessions that never happened. The
   annotation window still needs *some* bound, so ``context_end_ts`` is carried
   separately and is never shown as a duration.

3. **Windows double-logs interactive logons.** Two 4624 rows per logon instant
   means two identical "signed in" sessions; they are collapsed on
   (username, logon type, start) with their LogonIds merged.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from uba.utils import log_parser, sid_utils
from uba.utils.timeparse import epoch_seconds, normalize_ts

logger = logging.getLogger(__name__)

# Logon types that open a session. Type 7 (unlock) resumes instead.
SESSION_OPENING_LOGON_TYPES = ("2", "10", "11")
UNLOCK_LOGON_TYPE = "7"

# System-log events that bound a session from the outside: a shutdown or a
# boot means whatever was signed in is no longer signed in.
_MACHINE_BOUNDARY_EIDS = (1074, 6005, 6006, 6008)

# How a session ended — the analyst must be able to tell a recorded sign-out
# from an absence of evidence.
END_BASIS_LABEL = {
    "logoff": "signed out",
    "signout": "chose Sign out",
    "same-second": "sign-out recorded in the same second as the sign-in",
    "open": "no sign-out recorded",
}


@dataclass
class Session:
    username: str
    sid: str
    logon_type: str
    logon_type_label: str
    start_ts: str
    end_ts: Optional[str] = None        # None = no logoff was recorded
    end_basis: str = "open"             # logoff | signout | same-second | open
    # Bound used only for "was this user signed in at moment X" annotation.
    # Derived from the next machine boundary / next logon, NEVER presented as
    # the end of the session and never used to compute a duration.
    context_end_ts: Optional[str] = None
    logon_ids: List[str] = field(default_factory=list)
    unlocks: List[str] = field(default_factory=list)
    start_rowid: int = 0
    end_rowid: int = 0
    unlock_rowids: List[int] = field(default_factory=list)

    @property
    def start_epoch(self) -> Optional[float]:
        return epoch_seconds(self.start_ts)

    @property
    def end_epoch(self) -> Optional[float]:
        return epoch_seconds(self.end_ts) if self.end_ts else None

    @property
    def context_end_epoch(self) -> Optional[float]:
        """Upper bound of the annotation window. None = unbounded."""
        ts = self.end_ts or self.context_end_ts
        return epoch_seconds(ts) if ts else None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Seconds the session is *known* to have lasted, or None.

        None whenever no sign-out was recorded — there is no evidence for a
        duration, and an inferred one would read as a measurement.
        """
        start, end = self.start_epoch, self.end_epoch
        if start is None or end is None:
            return None
        return max(0.0, end - start)

    @property
    def is_open(self) -> bool:
        return self.end_ts is None

    def to_dict(self) -> dict:
        return {
            "username": self.username, "sid": self.sid,
            "logon_type": self.logon_type,
            "logon_type_label": self.logon_type_label,
            "start_ts": self.start_ts, "end_ts": self.end_ts,
            "end_basis": self.end_basis,
            "end_basis_label": END_BASIS_LABEL.get(self.end_basis, self.end_basis),
            "context_end_ts": self.context_end_ts,
            "duration_seconds": self.duration_seconds,
            "is_open": self.is_open,
            "logon_ids": list(self.logon_ids),
            "unlocks": list(self.unlocks),
            "unlock_count": len(self.unlocks),
        }


class SessionIndex:
    """Queryable set of interactive sessions."""

    def __init__(self, sessions: List[Session]):
        self.sessions = sorted(
            [s for s in sessions if s.start_epoch is not None],
            key=lambda s: s.start_epoch,
        )

    def context_for(self, ts_epoch: Optional[float]) -> str:
        """Human-readable annotation for a moment in time, or ''."""
        session = self.session_at(ts_epoch)
        if session is None:
            return ""
        return "during {}'s {}".format(session.username, session.logon_type_label)

    def user_at(self, ts_epoch: Optional[float]) -> str:
        """Username of the interactive session covering a moment, or ''.

        This is the account that was signed in at that time — it is used only
        as a *labelled* association ("logged-in user"), never as proof the
        account performed the activity."""
        session = self.session_at(ts_epoch)
        return session.username if session else ""

    def session_at(self, ts_epoch: Optional[float]) -> Optional[Session]:
        if ts_epoch is None:
            return None
        best = None
        for s in self.sessions:
            if s.start_epoch is None or s.start_epoch > ts_epoch:
                break
            end = s.context_end_epoch
            if end is None or end >= ts_epoch:
                best = s   # latest session containing the moment wins
        return best

    def to_list(self) -> List[dict]:
        return [s.to_dict() for s in self.sessions]


class SessionBuilder:
    """Builds interactive sessions by pairing 4624 with 4634 / 4647 on LogonId."""

    def __init__(self, db_pool, resolver=None):
        self.db_pool = db_pool
        # Optional ActorResolver: normalizes the session username via SID ->
        # UserProfiles so a Microsoft-account logon recorded as
        # 'name@outlook.com' is labelled with the profile name ('Gass3'),
        # consistent with actor_name.
        self.resolver = resolver

    # ------------------------------------------------------------------ #
    def build(self) -> SessionIndex:
        conn = self.db_pool.get("logs")
        if conn is None or not self.db_pool.has_table("logs", "SecurityLogs"):
            return SessionIndex([])

        try:
            rows = conn.execute(
                "SELECT rowid, EventID, EventTimestampUTC, Keywords, EventDescription "
                "FROM SecurityLogs WHERE EventID IN (4624, 4634, 4647) "
                "ORDER BY EventTimestampUTC, rowid"
            ).fetchall()
        except Exception as e:
            logger.warning("UBA: session query failed: %s", e)
            return SessionIndex([])

        logons, unlocks, logoffs, last_ts = self._collect(rows)
        sessions = self._dedupe_logons(logons)
        self._pair_logoffs(sessions, logoffs)
        # Bound BEFORE attaching unlocks: an unbounded session would otherwise
        # claim an unlock that falls outside the window the evidence can place
        # it in. Bounding depends only on logons and machine boundaries.
        self._bound_open_sessions(sessions, last_ts)
        self._attach_unlocks(sessions, unlocks)

        open_count = sum(1 for s in sessions if s.is_open)
        logger.info("UBA: built %d interactive sessions (%d with no recorded "
                    "sign-out)", len(sessions), open_count)
        return SessionIndex(sessions)

    # ------------------------------------------------------------------ #
    def _collect(self, rows):
        """Pass one: split the rows into logons, unlocks and logoffs.

        Nothing is paired here — see the module docstring for why doing it in
        one pass silently discarded every logoff.
        """
        logons: List[dict] = []
        unlocks: List[dict] = []
        logoffs: Dict[str, List[dict]] = {}
        last_ts = None

        for rowid, event_id, ts, keywords, desc in rows:
            ts = normalize_ts(ts) or ts
            if ts:
                last_ts = ts if last_ts is None or ts > last_ts else last_ts
            info = log_parser.parse_payload(event_id, keywords, desc)
            if not info:
                continue

            if event_id == 4624:
                logon_type = info.get("logon_type")
                if logon_type not in SESSION_OPENING_LOGON_TYPES \
                        and logon_type != UNLOCK_LOGON_TYPE:
                    continue
                identity = self._identify(info)
                if identity is None:
                    continue
                username, sid = identity
                entry = {
                    "username": username, "sid": sid,
                    "logon_type": logon_type,
                    "logon_type_label": info.get("logon_type_label",
                                                 "interactive session"),
                    "logon_id": info.get("logon_id", ""),
                    "ts": ts, "rowid": rowid,
                }
                (unlocks if logon_type == UNLOCK_LOGON_TYPE else logons).append(entry)
            else:   # 4634 logoff / 4647 user-initiated sign-out
                logon_id = info.get("logon_id", "")
                if not logon_id:
                    continue
                logoffs.setdefault(logon_id, []).append(
                    {"ts": ts, "rowid": rowid, "event_id": event_id})

        return logons, unlocks, logoffs, last_ts

    def _identify(self, info):
        """(username, sid) for a human interactive logon, or None.

        Service pseudo-accounts (DWM-1, UMFD-0, ...) log on interactively as
        type 2 constantly; they are not people and must never open a session.
        """
        user = info.get("target_user", "")
        sid = sid_utils.normalize_sid(info.get("target_sid"))
        if not sid_utils.is_human_account_name(user):
            return None
        if sid and sid_utils.classify_sid(sid) != "human_candidate":
            return None
        # Prefer the profile display name for this SID when available.
        profile_name = (self.resolver.username_for_sid(sid)
                        if self.resolver and sid else None)
        username = profile_name or user
        if not username:
            return None
        return username, sid

    # ------------------------------------------------------------------ #
    @staticmethod
    def _dedupe_logons(logons: List[dict]) -> List[Session]:
        """Collapse Windows' duplicate 4624 rows into one session each.

        Windows logs an interactive logon twice, which previously produced two
        identical overlapping sessions (and two identical "signed in" cards).
        The LogonIds differ, so both are kept on the surviving session — the
        logoff can arrive against either one.
        """
        by_key: Dict[tuple, Session] = {}
        for entry in logons:
            key = (entry["username"], entry["logon_type"], entry["ts"])
            session = by_key.get(key)
            if session is None:
                session = Session(
                    username=entry["username"], sid=entry["sid"],
                    logon_type=entry["logon_type"],
                    logon_type_label=entry["logon_type_label"],
                    start_ts=entry["ts"], start_rowid=entry["rowid"],
                )
                by_key[key] = session
            if entry["logon_id"] and entry["logon_id"] not in session.logon_ids:
                session.logon_ids.append(entry["logon_id"])
        return sorted(by_key.values(), key=lambda s: (s.start_ts, s.username))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _pair_logoffs(sessions: List[Session], logoffs: Dict[str, List[dict]]):
        """Pass two: close each session from the logoffs for its LogonIds.

        Order-independent by construction. A logoff timestamped strictly before
        its own logon is clock skew and is skipped rather than producing a
        negative duration; one in the same second is kept but flagged, because
        that is what the log records.
        """
        claimed = set()
        for session in sessions:
            best = None
            for logon_id in session.logon_ids:
                for cand in logoffs.get(logon_id, []):
                    marker = (logon_id, cand["rowid"])
                    if marker in claimed:
                        continue
                    if not cand["ts"] or cand["ts"] < session.start_ts:
                        continue            # predates its own logon: skew
                    if best is None or cand["ts"] < best[1]["ts"]:
                        best = (marker, cand)
            if best is None:
                continue
            marker, cand = best
            claimed.add(marker)
            session.end_ts = cand["ts"]
            session.end_rowid = cand["rowid"]
            if cand["ts"] == session.start_ts:
                session.end_basis = "same-second"
            else:
                session.end_basis = "signout" if cand["event_id"] == 4647 else "logoff"

    # ------------------------------------------------------------------ #
    @staticmethod
    def _attach_unlocks(sessions: List[Session], unlocks: List[dict]):
        """Record type-7 unlocks on the session they resumed.

        An unlock that no session covers is not invented into one — the unlock
        *event* is still reported by the sessions_unlock rule; only the session
        model stays silent about a window it cannot evidence.
        """
        for entry in unlocks:
            ts = entry["ts"]
            if not ts:
                continue
            covering = None
            for session in sessions:
                if session.username != entry["username"]:
                    continue
                if session.start_ts > ts:
                    continue
                bound = session.end_ts or session.context_end_ts
                if bound is None or bound >= ts:
                    covering = session
            if covering is None:
                continue
            if ts not in covering.unlocks:
                covering.unlocks.append(ts)
                covering.unlock_rowids.append(entry["rowid"])

    # ------------------------------------------------------------------ #
    def _bound_open_sessions(self, sessions: List[Session], last_ts):
        """Give every unfinished session an annotation bound (not an end).

        The bound is the first thing that proves the session was over: a
        shutdown/boot, or the same account signing in again. The last log
        timestamp is only the final fallback. This is what stops a session with
        no recorded sign-out from labelling weeks of unrelated activity with
        its user.
        """
        boundaries = self._machine_boundaries()
        starts_by_user: Dict[str, List[str]] = {}
        for session in sessions:
            starts_by_user.setdefault(session.username, []).append(session.start_ts)

        for session in sessions:
            if not session.is_open:
                continue
            candidates = [ts for ts in boundaries if ts > session.start_ts]
            candidates += [ts for ts in starts_by_user.get(session.username, [])
                           if ts > session.start_ts]
            if candidates:
                session.context_end_ts = min(candidates)
            elif last_ts and last_ts > session.start_ts:
                session.context_end_ts = last_ts

    def _machine_boundaries(self) -> List[str]:
        """Sorted timestamps of boots and shutdowns from the System log."""
        conn = self.db_pool.get("logs")
        if conn is None or not self.db_pool.has_table("logs", "SystemLogs"):
            return []
        marks = ",".join("?" for _ in _MACHINE_BOUNDARY_EIDS)
        try:
            rows = conn.execute(
                "SELECT EventTimestampUTC FROM SystemLogs "
                "WHERE EventID IN ({}) ORDER BY EventTimestampUTC".format(marks),
                list(_MACHINE_BOUNDARY_EIDS)).fetchall()
        except Exception as e:
            logger.debug("UBA: machine boundary query failed: %s", e)
            return []
        out = []
        for (ts,) in rows:
            norm = normalize_ts(ts)
            if norm:
                out.append(norm)
        return sorted(out)
