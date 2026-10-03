"""Session reconstruction: pairing, honesty about unfinished sessions, and the
offline payload shape.

Every test here corresponds to something that was silently wrong on a real
case while the whole suite stayed green.
"""

import sqlite3

import pytest

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.sessions import SessionBuilder
from uba.utils import log_parser
from uba.utils.db_access import DbPool


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=2000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True}, page_size=2000)["events"]
    return timed + timeless


def sessions_at(eng, ts):
    return [s for s in eng.sessions.sessions if s.start_ts == ts]


# --------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------- #
def test_logoff_written_before_its_logon_still_closes_the_session(artifacts_dir):
    """The regression: Windows logs the logoff in the same second as the logon,
    and the row order within that second is insertion order. A one-pass builder
    discarded every such logoff (10 of 10 on a real case), so no session closed.
    """
    eng = run(artifacts_dir)
    matches = sessions_at(eng, "2026-06-12 18:00:00")
    assert matches, "the 18:00 logon should produce a session"
    session = matches[0]
    assert not session.is_open, "a logoff exists for this LogonId; it must close"
    assert session.end_ts == "2026-06-12 18:00:00"
    assert session.end_basis == "same-second"
    assert session.duration_seconds == 0


def test_user_initiated_signout_closes_a_session(artifacts_dir):
    """4647 carries FOUR fields and no LogonType. Parsed with the 4634 layout it
    returned {} and was dropped, so "chose Sign out" could never appear."""
    eng = run(artifacts_dir)
    session = sessions_at(eng, "2026-06-12 09:59:58")[0]
    assert session.end_basis == "signout"
    assert session.end_ts == "2026-06-12 16:59:00"


def test_4647_payload_has_four_fields(artifacts_dir):
    """Guard the payload shape itself, independently of the engine."""
    info = log_parser.parse_payload(
        4647, "S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d")
    assert info["logon_id"] == "0x5fc1d"
    assert info["target_user"] == "Alice"
    assert "logon_type" not in info       # 4647 genuinely does not carry one


def test_logoff_activity_reported_for_both_event_ids(artifacts_dir):
    eng = run(artifacts_dir)
    lo = [e for e in all_events(eng) if e["activity"] == "logoff"]
    assert lo
    assert any("Sign Out" in e["description"] for e in lo), \
        "the 4647 sign-out must reach the storyline"


# --------------------------------------------------------------------- #
# Honesty about what is not known
# --------------------------------------------------------------------- #
def test_open_session_has_no_end_and_no_duration(artifacts_dir):
    """An unfinished session used to be capped at the last log timestamp and
    shown as a multi-hour session that never happened."""
    eng = run(artifacts_dir)
    session = sessions_at(eng, "2026-06-12 19:30:00")[0]
    assert session.is_open
    assert session.end_ts is None
    assert session.duration_seconds is None
    assert session.end_basis == "open"
    assert session.to_dict()["end_basis_label"] == "no sign-out recorded"


def test_open_session_context_window_is_bounded(artifacts_dir):
    """It still needs a bound for the "who was signed in" annotation - but that
    bound is carried separately so it can never be read as the session's end."""
    eng = run(artifacts_dir)
    session = sessions_at(eng, "2026-06-12 19:30:00")[0]
    assert session.context_end_ts is not None
    assert session.context_end_ts > session.start_ts
    # the 21:15 clean shutdown is the first thing proving the session was over
    assert session.context_end_ts <= "2026-06-12 21:15:00"
    assert session.end_ts is None      # bounding must not invent an end


def test_every_session_either_has_a_real_end_or_is_open(artifacts_dir):
    eng = run(artifacts_dir)
    for s in eng.sessions.sessions:
        if s.end_ts is None:
            assert s.end_basis == "open" and s.duration_seconds is None
        else:
            assert s.end_basis in ("logoff", "signout", "same-second")
            assert s.duration_seconds is not None and s.duration_seconds >= 0


# --------------------------------------------------------------------- #
# Duplicates and non-humans
# --------------------------------------------------------------------- #
def test_duplicate_logon_collapses_to_one_session(artifacts_dir):
    """Windows writes two 4624 rows per logon; both LogonIds are kept on the one
    surviving session so a logoff against either still closes it."""
    eng = run(artifacts_dir)
    matches = sessions_at(eng, "2026-06-12 19:30:00")
    assert len(matches) == 1
    assert len(matches[0].logon_ids) == 2


def test_duplicate_logon_collapses_to_one_activity(artifacts_dir):
    """...and to one card, whose evidence still lists both rows."""
    eng = run(artifacts_dir)
    dupes = [e for e in all_events(eng)
             if e["activity"] == "logon" and e["ts_start"] == "2026-06-12 19:30:00"]
    assert len(dupes) == 1
    assert dupes[0]["aggregate_count"] == 2
    assert dupes[0]["evidence_count"] == 2


def test_unlock_attaches_to_a_session_instead_of_opening_one(artifacts_dir):
    eng = run(artifacts_dir)
    assert not sessions_at(eng, "2026-06-12 20:15:00"), \
        "a type-7 unlock must not open its own overlapping session"
    session = sessions_at(eng, "2026-06-12 19:30:00")[0]
    assert "2026-06-12 20:15:00" in session.unlocks
    assert session.to_dict()["unlock_count"] == 1
    # the unlock is still reported as its own activity
    unlocks = [e for e in all_events(eng) if e["activity"] == "unlock"]
    assert any(e["ts_start"] == "2026-06-12 20:15:00" for e in unlocks)


def test_service_pseudo_account_never_opens_a_session(artifacts_dir):
    """DWM-1 / UMFD-* log on interactively (type 2) constantly."""
    eng = run(artifacts_dir)
    assert all("DWM" not in s.username.upper() for s in eng.sessions.sessions)
    logons = [e for e in all_events(eng) if e["activity"] == "logon"]
    assert all("DWM" not in (e["actor_name"] or "").upper() for e in logons)


# --------------------------------------------------------------------- #
# New sources
# --------------------------------------------------------------------- #
def test_failed_logons_burst_and_escalate(artifacts_dir):
    eng = run(artifacts_dir)
    failed = [e for e in all_events(eng) if e["activity"] == "failed_logon"]
    assert len(failed) == 1, "six attempts in one hour are one burst, not six cards"
    assert failed[0]["aggregate_count"] == 6
    assert failed[0]["severity"] == "suspicious"
    assert failed[0]["caveat"], "a failed sign-in must carry its limitation"


def test_winlogon_session_records_are_read_and_left_unattributed(artifacts_dir):
    """Windows does not name the account in 7001/7002, so naming the only
    profile on the machine would be a guess presented as evidence."""
    eng = run(artifacts_dir)
    winlogon = [e for e in all_events(eng)
                if e["rule_id"] in ("winlogon_logon_notification",
                                    "winlogon_logoff_notification")]
    assert len(winlogon) == 2
    for e in winlogon:
        assert e["actor_type"] == "" and e["actor_name"] == ""
        assert e["caveat"]
    # the User Profile Service rows for the same moments corroborate them
    assert all(e["confidence"] == "corroborated" for e in winlogon)


def test_boot_events_exist_not_only_shutdowns(artifacts_dir):
    """6005 was never read, so the machine never appeared to start up."""
    eng = run(artifacts_dir)
    power = [e for e in all_events(eng) if e["activity"] == "boot_shutdown"]
    starts = [e for e in power if e["details"].get("transition") == "start"]
    stops = [e for e in power if e["details"].get("transition") == "stop"]
    assert starts, "6005 must produce a 'computer started' activity"
    assert stops


# --------------------------------------------------------------------- #
# Offline-imported cases
# --------------------------------------------------------------------- #
OFFLINE_4624 = (
    "SubjectUserSid: S-1-5-18; SubjectUserName: PC$; SubjectDomainName: WG; "
    "SubjectLogonId: 0x3e7; TargetUserSid: S-1-5-21-111-222-333-1001; "
    "TargetUserName: Alice; TargetDomainName: PC; TargetLogonId: 0xdd001; "
    "LogonType: 2; WorkstationName: PC"
)
OFFLINE_4634 = (
    "TargetUserSid: S-1-5-21-111-222-333-1001; TargetUserName: Alice; "
    "TargetDomainName: PC; TargetLogonId: 0xdd001; LogonType: 2"
)


def test_offline_named_payload_matches_the_live_positional_one():
    """The two event-log parsers disagree about what Keywords means: live stores
    the EventData values, offline stores the Keywords BITMASK and puts EventData
    in EventDescription. Every positional parser therefore returned {} on an
    image-imported case and the entire sign-in story vanished with no error."""
    live = log_parser.parse_payload(
        4624,
        "S-1-5-18,PC$,WG,0x3e7,S-1-5-21-111-222-333-1001,Alice,PC,0xdd001,2,"
        "User32,Negotiate,-,-,-,-,0,0x0,C:\\Windows\\System32\\winlogon.exe,-,-",
        "An account was successfully logged on.")
    offline = log_parser.parse_payload(4624, "0x8020000000000000", OFFLINE_4624)
    for key in ("target_sid", "target_user", "logon_id", "logon_type",
                "logon_type_label"):
        assert offline[key] == live[key], key


def test_live_prose_is_not_mistaken_for_a_payload():
    for prose in ("An account was successfully logged on.",
                  "Description not available",
                  "The service started successfully.", "", None):
        assert log_parser.parse_named_payload(prose) == {}


def test_offline_shaped_case_still_builds_sessions(tmp_path):
    """End-to-end on the offline shape: bitmask Keywords, named
    EventDescription. This produced zero sessions before."""
    db = tmp_path / "Log_Claw.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE SecurityLogs (EventID INTEGER, Source TEXT, EventType TEXT,
            Category TEXT, EventTimestampUTC TEXT, ComputerName TEXT, User TEXT,
            Keywords TEXT, TaskCategory TEXT, EventDescription TEXT);
        CREATE TABLE SystemLogs (EventID INTEGER, Source TEXT, EventType TEXT,
            Category TEXT, EventTimestampUTC TEXT, ComputerName TEXT, User TEXT,
            Keywords TEXT, EventDescription TEXT);
    """)
    conn.executemany(
        "INSERT INTO SecurityLogs (EventID, EventTimestampUTC, Keywords, "
        "EventDescription) VALUES (?,?,?,?)",
        [(4624, "2026-06-12 09:00:00", "0x8020000000000000", OFFLINE_4624),
         (4634, "2026-06-12 17:00:00", "0x8020000000000000", OFFLINE_4634)])
    conn.commit()
    conn.close()

    pool = DbPool(str(tmp_path))
    try:
        index = SessionBuilder(pool).build()
        assert len(index.sessions) == 1, \
            "an offline-parsed case must reconstruct its sessions too"
        session = index.sessions[0]
        assert session.username == "Alice"
        assert session.start_ts == "2026-06-12 09:00:00"
        assert session.end_ts == "2026-06-12 17:00:00"
        assert session.end_basis == "logoff"
        assert session.duration_seconds == 8 * 3600
    finally:
        pool.close()


# --------------------------------------------------------------------- #
# sessions_report() — what the Sign-ins view renders
# --------------------------------------------------------------------- #
def test_sessions_report_shape(artifacts_dir):
    eng = run(artifacts_dir)
    rep = eng.sessions_report()
    assert set(rep) == {"sessions", "accounts", "uptime", "auditing"}
    assert rep["sessions"]
    for s in rep["sessions"]:
        assert s["username"]
        assert "end_basis_label" in s
        assert isinstance(s["event_count"], int)
        assert isinstance(s["failed_before"], int)
        # an open session must not carry a duration anywhere in the payload
        if s["is_open"]:
            assert s["duration_seconds"] is None and s["end_ts"] is None


def test_failed_attempts_are_counted_against_the_session_that_followed(artifacts_dir):
    """Six failures at 07:1x then a successful sign-in — the successful session
    should show what preceded it."""
    eng = run(artifacts_dir)
    rep = eng.sessions_report()
    assert any(s["failed_before"] > 0 for s in rep["sessions"]), \
        "a sign-in preceded by failures should say so"


def test_accounts_come_from_the_account_table(artifacts_dir):
    eng = run(artifacts_dir)
    accounts = eng.sessions_report()["accounts"]
    by_name = {a["username"]: a for a in accounts}
    assert "Alice" in by_name and "Bob" in by_name
    alice = by_name["Alice"]
    assert alice["login_count"] == 42
    assert alice["bad_password_count"] == 6
    assert alice["last_logon"] == "2026-06-12 19:30:00"
    assert alice["has_profile"] is True
    # Bob has no profile on this machine
    assert by_name["Bob"]["has_profile"] is False


def test_uptime_windows_pair_start_with_stop(artifacts_dir):
    eng = run(artifacts_dir)
    uptime = eng.sessions_report()["uptime"]
    assert uptime, "6005/6006 should produce at least one uptime window"
    for w in uptime:
        assert w["start_ts"]
        if w["end_ts"]:
            assert w["end_ts"] > w["start_ts"]


def test_auditing_note_is_reported(artifacts_dir):
    """A thin session list must be readable as 'auditing was limited' rather
    than 'nobody signed in'."""
    eng = run(artifacts_dir)
    auditing = eng.sessions_report()["auditing"]
    assert auditing["audit_policy_available"] is True
    names = {e["name"] for e in auditing["entries"]}
    assert "Logon" in names and "Logoff" in names


def test_report_degrades_cleanly_without_the_optional_tables(tmp_path):
    """Cases parsed before the SAM/SECURITY tables existed must not break the
    view — they report absence instead."""
    import os
    from uba.engine.behavior_engine import BehaviorEngine as BE
    os.makedirs(str(tmp_path), exist_ok=True)
    eng = BE(str(tmp_path))
    eng.run()
    rep = eng.sessions_report()
    assert rep["accounts"] == []
    assert rep["auditing"]["audit_policy_available"] is False
    eng.close()
