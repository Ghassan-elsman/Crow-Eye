"""
Interactive session reconstruction from Security 4624/4634 events.

Sessions provide *context annotations* for other events ("during Gass3's
interactive session") — they are never used to attribute an action to a
user by themselves (an unattributed file write during a session stays
unattributed; the session is shown as a subtitle only).

Only interactive logon types (2 local, 7 unlock, 10 RDP, 11 cached) open a
session window: service/network logons (types 3/4/5) happen constantly in
the background and say nothing about a human presence.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from uba.utils import log_parser, sid_utils
from uba.utils.timeparse import epoch_seconds

logger = logging.getLogger(__name__)


@dataclass
class Session:
    username: str
    sid: str
    logon_id: str
    logon_type: str
    logon_type_label: str
    start_ts: str
    end_ts: Optional[str]          # None = never saw the logoff
    start_rowid: int = 0
    end_rowid: int = 0

    @property
    def start_epoch(self) -> Optional[float]:
        return epoch_seconds(self.start_ts)

    @property
    def end_epoch(self) -> Optional[float]:
        return epoch_seconds(self.end_ts) if self.end_ts else None

    def to_dict(self) -> dict:
        return {
            "username": self.username, "sid": self.sid,
            "logon_id": self.logon_id, "logon_type": self.logon_type,
            "logon_type_label": self.logon_type_label,
            "start_ts": self.start_ts, "end_ts": self.end_ts,
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
            end = s.end_epoch
            if end is None or end >= ts_epoch:
                best = s   # latest session containing the moment wins
        return best


class SessionBuilder:
    """Builds interactive sessions by pairing 4624 with 4634 on LogonId."""

    def __init__(self, db_pool, resolver=None):
        self.db_pool = db_pool
        # Optional ActorResolver: normalizes the session username via SID ->
        # UserProfiles so a Microsoft-account logon recorded as
        # 'name@outlook.com' is labelled with the profile name ('Gass3'),
        # consistent with actor_name.
        self.resolver = resolver

    def build(self) -> SessionIndex:
        conn = self.db_pool.get("logs")
        if conn is None or not self.db_pool.has_table("logs", "SecurityLogs"):
            return SessionIndex([])

        open_by_logon_id: Dict[str, Session] = {}
        sessions: List[Session] = []
        last_ts = None

        try:
            cursor = conn.execute(
                "SELECT rowid, EventID, EventTimestampUTC, Keywords "
                "FROM SecurityLogs WHERE EventID IN (4624, 4634) "
                "ORDER BY EventTimestampUTC, rowid"
            )
        except Exception as e:
            logger.warning("UBA: session query failed: %s", e)
            return SessionIndex([])

        for rowid, event_id, ts, keywords in cursor:
            last_ts = ts or last_ts
            info = log_parser.parse_payload(event_id, keywords)
            if not info:
                continue
            if event_id == 4624:
                if info.get("logon_type") not in log_parser.INTERACTIVE_LOGON_TYPES:
                    continue
                user = info.get("target_user", "")
                sid = sid_utils.normalize_sid(info.get("target_sid"))
                if not sid_utils.is_human_account_name(user):
                    continue
                if sid and sid_utils.classify_sid(sid) != "human_candidate":
                    continue
                # Prefer the profile display name for this SID when available.
                profile_name = (self.resolver.username_for_sid(sid)
                                if self.resolver and sid else None)
                session = Session(
                    username=profile_name or user, sid=sid,
                    logon_id=info.get("logon_id", ""),
                    logon_type=info.get("logon_type", ""),
                    logon_type_label=info.get("logon_type_label", "interactive session"),
                    start_ts=ts, end_ts=None, start_rowid=rowid,
                )
                sessions.append(session)
                if session.logon_id:
                    open_by_logon_id[session.logon_id] = session
            else:  # 4634 logoff
                logon_id = info.get("logon_id", "")
                session = open_by_logon_id.pop(logon_id, None)
                if session is not None:
                    session.end_ts = ts
                    session.end_rowid = rowid

        # Unclosed sessions: cap at the last log timestamp seen so context
        # windows do not extend beyond the evidence.
        for session in sessions:
            if session.end_ts is None and last_ts:
                session.end_ts = last_ts

        logger.info("UBA: built %d interactive sessions", len(sessions))
        return SessionIndex(sessions)
