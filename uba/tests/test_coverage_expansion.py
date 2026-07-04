"""Tests for the full default-artifact coverage expansion (Phase 2)."""

import sqlite3

from uba.engine.behavior_engine import BehaviorEngine


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=2000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True}, page_size=2000)["events"]
    return timed + timeless


def test_amcache_file_presence_timeless_and_attributed(artifacts_dir):
    eng = run(artifacts_dir)
    presence = [e for e in all_events(eng)
                if e["activity"] == "program_presence" and e["confidence"] == "presence"]
    assert presence, "amcache/shimcache presence events expected"
    # all presence events are timeless (their timestamps are compile/cache dates)
    assert all(e["ts_start"] is None for e in presence)
    # a system-area program bucket attributes to System; nothing to a person
    assert all(e["actor_type"] in ("System", "") for e in presence)


def test_muicache_suffix_stripped(artifacts_dir):
    """MUICache 'paint.exe.FriendlyAppName' must be cleaned to 'paint'."""
    eng = run(artifacts_dir)
    joined = " ".join(str(e["details"].get("sample_programs", ""))
                      for e in all_events(eng) if e["activity"] == "program_presence")
    assert "FriendlyAppName" not in joined


def test_custom_jumplist_attributed_to_user(artifacts_dir):
    eng = run(artifacts_dir)
    cjl = [e for e in all_events(eng)
           if e["activity"] == "file_opened" and "recent/pinned" in e["description"]]
    assert cjl
    assert cjl[0]["actor_name"] == "Alice"


def test_network_session_shows_duration(artifacts_dir):
    eng = run(artifacts_dir)
    ns = [e for e in all_events(eng) if e["activity"] == "network_session"]
    assert ns
    assert "5m 12s" in ns[0]["description"]
    assert ns[0]["actor_type"] == "System"


def test_device_present_only_interesting_classes(artifacts_dir):
    """USB shows up; internal 'processor' hardware is filtered out."""
    eng = run(artifacts_dir)
    dev = [e for e in all_events(eng) if e["activity"] == "device_present"]
    joined = " ".join(e["description"] for e in dev)
    assert "USB" in joined
    assert "processor" not in joined.lower()


def test_time_change_carries_timezone_context(artifacts_dir):
    eng = run(artifacts_dir)
    tc = [e for e in all_events(eng) if e["activity"] == "time_changed"]
    assert tc
    assert "Egypt Standard Time" in tc[0]["description"]
    assert any(ref["table"] == "TimeZoneInfo" for ref in tc[0]["evidence"])


def test_no_actor_without_basis_after_expansion(artifacts_dir):
    eng = run(artifacts_dir)
    bad = eng.store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE actor_name != '' AND actor_basis = ''"
    ).fetchone()[0]
    assert bad == 0


def test_unsigned_driver_flagged(artifacts_dir):
    eng = run(artifacts_dir)
    drivers = [e for e in all_events(eng) if e["activity"] == "driver_present"]
    unsigned = [e for e in drivers if "UNSIGNED" in e["description"]]
    assert unsigned and unsigned[0]["severity"] == "suspicious"
