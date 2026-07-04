"""Tests for the forensic-accuracy pass, new behaviours, and per-user labelling."""

from uba.engine.behavior_engine import BehaviorEngine
from uba.utils import log_parser


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=2000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True}, page_size=2000)["events"]
    return timed + timeless


# --- Part A: forensic accuracy -------------------------------------------- #
def test_shellbags_do_not_claim_browsing(artifacts_dir):
    eng = run(artifacts_dir)
    sb = [e for e in all_events(eng) if e["activity"] == "folder_browsing"]
    assert sb
    for e in sb:
        assert "browsing" not in e["description"].lower()
        assert "explorer" not in e["description"].lower() or "session" in e["description"].lower()
        assert e["caveat"], "ShellBags events must carry a caveat"
        assert "application" in e["caveat"].lower()


def test_file_open_has_caveat(artifacts_dir):
    eng = run(artifacts_dir)
    fo = [e for e in all_events(eng) if e["activity"] == "file_opened"]
    assert fo
    assert all(e["caveat"] for e in fo)


def test_presence_has_caveat(artifacts_dir):
    eng = run(artifacts_dir)
    pres = [e for e in all_events(eng) if e["activity"] == "program_presence"]
    assert pres
    assert all(e["caveat"] for e in pres)


def test_userassist_has_no_caveat(artifacts_dir):
    """GUI double-click launches are genuine user interaction — no caveat."""
    eng = run(artifacts_dir)
    ua = [e for e in all_events(eng) if e["activity"] == "app_launch"]
    assert ua
    assert all(not e["caveat"] for e in ua)


# --- Part B: new behaviours ----------------------------------------------- #
def test_prefetch_expands_run_times(artifacts_dir):
    """run_times has 2 timestamps -> 2 program_run events for that exe."""
    eng = run(artifacts_dir)
    runs = [e for e in all_events(eng)
            if e["activity"] == "program_run" and "notepad" in e["description"].lower()]
    # 2 run-time events (the run_count of 3 also adds a timeless summary)
    timed = [e for e in runs if e["ts_start"]]
    assert len(timed) == 2


def test_account_management_names_target_and_subject(artifacts_dir):
    eng = run(artifacts_dir)
    am = [e for e in all_events(eng) if e["activity"] == "account_management"]
    joined = " | ".join(e["description"] for e in am)
    assert "Bob" in joined                       # created account named
    assert "created the user account" in joined
    # 4738 with leading-dummy layout must resolve the target to Alice, not '-'
    changed = [e for e in am if "changed the user account" in e["description"]]
    assert changed and "'-'" not in changed[0]["description"]


def test_admin_group_add_is_suspicious(artifacts_dir):
    eng = run(artifacts_dir)
    am = [e for e in all_events(eng) if e["activity"] == "account_management"]
    admin = [e for e in am if "Administrators" in e["description"]]
    assert admin
    assert admin[0]["severity"] == "suspicious"
    assert "administrator rights" in admin[0]["description"]


def test_file_copy_only_in_user_areas(artifacts_dir):
    eng = run(artifacts_dir)
    copies = [e for e in all_events(eng) if e["activity"] == "file_copied"]
    assert copies
    joined = " ".join(e["description"] + str(e["details"]) for e in copies)
    assert "movie.mp4" in joined              # user-area copy detected
    assert "sys.dll" not in joined            # WinSxS copy excluded
    assert all(e["confidence"] == "inference" for e in copies)
    assert all(e["caveat"] for e in copies)


def test_user_initiated_logoff_captured(artifacts_dir):
    eng = run(artifacts_dir)
    lo = [e for e in all_events(eng) if e["activity"] == "logoff"]
    # both 4634 and 4647 for Alice
    assert len(lo) >= 2


def test_account_target_parser_handles_both_layouts():
    # 4720 layout (no leading dummy)
    a = log_parser.parse_account_target(
        "Bob,PC,S-1-5-21-1-2-3-1002,S-1-5-18,PC$,WG,0x3e7")
    assert a["target_user"] == "Bob"
    assert a["subject_sid"] == "S-1-5-18"
    # 4738 layout (leading dummy)
    b = log_parser.parse_account_target(
        "-,Alice,PC,S-1-5-21-1-2-3-1001,S-1-5-18,PC$,WG,0x3e7,-")
    assert b["target_user"] == "Alice"
    assert b["subject_sid"] == "S-1-5-18"


# --- Part C: per-user labelling ------------------------------------------- #
def test_session_user_labelled_but_not_actor(artifacts_dir):
    """A timed event inside Alice's session gets session_user=Alice, and the
    session user is never written into actor_name when the actor is uncertain."""
    eng = run(artifacts_dir)
    events = eng.store.query_events(page_size=2000)["events"]
    labelled = [e for e in events if e.get("session_user")]
    assert labelled, "some timed events should carry a session_user label"
    assert all(e["session_user"] == "Alice" for e in labelled)
    # invariant: session_user is a label, never a forensic actor substitute
    for e in events:
        if e["actor_name"] == "" and e.get("session_user"):
            assert e["actor_type"] == ""   # stayed unattributed despite the label


def test_session_user_filter_includes_logged_in(artifacts_dir):
    eng = run(artifacts_dir)
    strict = eng.store.query_events(filters={"actors": ["Alice"]}, page_size=2000)["total"]
    loose = eng.store.query_events(
        filters={"actors": ["Alice"], "include_session_user": True},
        page_size=2000)["total"]
    assert loose >= strict


def test_no_actor_without_basis_still_holds(artifacts_dir):
    eng = run(artifacts_dir)
    bad = eng.store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE actor_name != '' AND actor_basis = ''"
    ).fetchone()[0]
    assert bad == 0
