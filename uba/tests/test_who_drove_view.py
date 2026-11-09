"""The Who drove it tab: every number it shows is what it opens.

event_store.summary's by_driver / by_app_state / driver_heatmap and the
"drivers" / "app_states" filters share one expression (DRIVER_SQL), so a tile,
a day cell or an hour bar opens exactly the activities it counted. drivers.py
answers the per-person table, a day's AI agent sessions and a day's keyboard,
mouse and focus record; the bridge runs the two evidence readers off the GUI
thread and opens rows of three source tables only.
"""
import json
import sqlite3

import pytest

from uba.engine import drivers
from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.event_store import DRIVERS
from uba.utils.db_access import DbPool


@pytest.fixture
def store(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    return eng.run(progress_cb=lambda p, l: None)


def _total(store, **filters):
    """What the Activity Story shows for a filter: its timed activities and,
    in their own section, those without an exact time."""
    timed = store.query_events(filters=filters, page_size=1)["total"]
    timeless = store.query_events(filters=dict(filters, timeless=True), page_size=1)["total"]
    return timed + timeless


def test_each_tile_opens_exactly_what_it_counts(store):
    s = store.summary({})
    by = {r["driver"]: r["events"] for r in s["by_driver"]}
    assert set(by) <= set(DRIVERS)
    assert sum(by.values()) == _total(store)
    assert by.get("ai_agent") and by.get("program")          # the fixture's agent turns and system work
    for k, n in by.items():
        assert _total(store, drivers=[k]) == n, k
    for r in s["by_app_state"]:
        if r["app_state"]:
            assert _total(store, app_states=[r["app_state"]]) == r["events"]


def test_an_hour_bar_opens_its_hour(store):
    cells = store.summary({})["driver_heatmap"]
    cell = max(cells, key=lambda c: c["events"])
    hour = "%s %02d" % (cell["day"], cell["hour"])
    got = store.query_events(filters={"drivers": [cell["driver"]], "start": hour + ":00:00",
                                      "end": hour + ":59:59"}, page_size=500)["events"]
    starting = [e for e in got if e["ts_start"] and e["ts_start"].startswith(hour)]
    assert len(starting) == cell["events"]


def test_the_ai_agent_driver_is_only_the_agents_own_record(store):
    """Decision 602: the desktop names an AI agent from its session record and
    nothing else; any other automation is a script."""
    got = store.query_events(filters={"drivers": ["ai_agent"]}, page_size=500)["events"]
    assert got and {e["rule_id"] for e in got} == {"ai_agent_turn"}


def test_per_person_counts_people_first(store):
    out = drivers.by_person(store, {})
    rows = out["people"]
    assert sum(p["events"] for p in rows) == _total(store)
    kinds = [p["kind"] for p in rows]
    assert kinds == sorted(kinds, key={"person": 0, "unattributed": 1, "computer": 2}.get)
    alice = next(p for p in rows if p["person"] == "Alice")
    assert alice["kind"] == "person" and alice["by_driver"]["ai_agent"] >= 3
    assert [a["agent"] for a in alice["agents"]][:1] == ["Claude Code"]
    assert any(f["folder"].endswith("shop") for f in alice["folders"])
    assert all(w["automation"] <= w["events"] for w in alice["weeks"])


def test_agent_sessions_draw_each_kind_of_mark(artifacts_dir, monkeypatch):
    pool = DbPool(artifacts_dir)
    day = drivers.agent_sessions(pool, "2026-06-10 00:00:00", "2026-06-10 23:59:59")
    assert day["available"] and day["total_sessions"] == 2      # the session and its sub-agent
    marks = {m["kind"] for s in day["sessions"] for m in s["marks"]}
    assert {"request", "command", "file", "own_command", "notice", "instruction"} <= marks
    assert day["sessions"][0]["parent"] == ""                    # the session before its sub-agent
    monkeypatch.setattr(drivers, "AGENT_SESSIONS_MAX", 1)
    capped = drivers.agent_sessions(pool, "2026-06-01 00:00:00", "2026-06-30 23:59:59")
    assert capped["shown_sessions"] == 1 and capped["total_sessions"] == 4
    pool.close()


def test_without_the_evidence_each_section_says_why(tmp_path):
    pool = DbPool(str(tmp_path))
    assert "SRUM" in drivers.input_layer(pool, "2026-06-10")["reason"]
    assert "AI agent" in drivers.agent_sessions(pool, "2026-06-10", "2026-06-11")["reason"]
    assert drivers.input_layer(pool, "not a day")["available"] is False


def _srum_case(tmp_path):
    """One SRUM App Timeline row: the lab test's scripted SendInput run."""
    d = tmp_path / "Target_Artifacts"
    d.mkdir(parents=True)
    conn = sqlite3.connect(str(d / "srum_data.db"))
    conn.execute("CREATE TABLE srum_app_timeline (timestamp TEXT, end_time TEXT, span_ms INTEGER, "
                 "duration_ms INTEGER, app_name TEXT, app_path TEXT, user_sid TEXT, user_name TEXT, "
                 "in_focus_s REAL, user_input_s REAL, keyboard_input_s REAL, mouse_input_s REAL, "
                 "timeline_end INTEGER, user_input_timeline INTEGER, flags INTEGER, "
                 "in_focus_timeline INTEGER, keyboard_input_timeline INTEGER)")
    conn.execute("INSERT INTO srum_app_timeline VALUES ('2026-11-03 13:59:00', '2026-11-03 13:59:00', "
                 "240000, 240000, 'pythonw.exe', 'pythonw.exe', 'S-1-5-21-1-2-3-1001', 'analyst', 152, 84, "
                 "84, 0, 437918532, 548698817534, 256, 548698817534, 548698817534)")
    conn.commit()
    conn.close()
    return str(d)


def test_the_input_layer_draws_the_decoded_runs(tmp_path):
    pool = DbPool(_srum_case(tmp_path))
    out = drivers.input_layer(pool, "2026-11-03")
    pool.close()
    assert out["available"] and out["total_programs"] == 1
    p = out["programs"][0]
    assert (p["app"], p["keyboard_s"], p["mouse_s"], p["in_front"]) == ("pythonw.exe", 84, 0, True)
    assert len(p["keyboard_runs"]) == 3                         # the three bursts of the scripted run
    assert all(0 <= a < b <= 86400 for a, b in p["keyboard_runs"])
    empty = drivers.input_layer(DbPool(_srum_case(tmp_path / "b")), "2026-11-05")
    assert empty["available"] and empty["programs"] == [] and empty["reason"]


def test_the_bridge_slots(artifacts_dir):
    from uba.engine.evidence import EvidenceFetcher
    from uba.uba_bridge import UBABridge
    bridge = UBABridge(str(artifacts_dir))
    bridge.engine = BehaviorEngine(str(artifacts_dir))
    bridge.engine.run(progress_cb=lambda p, l: None)
    bridge.fetcher = EvidenceFetcher(bridge.engine.db_pool)
    bridge._analysis_done = True
    people = json.loads(bridge.getDriversByPerson("{}"))
    assert people["people"] and people["drivers"] == list(DRIVERS)
    sessions = json.loads(bridge.getAgentSessions(json.dumps(
        {"start": "2026-06-10 00:00:00", "end": "2026-06-10 23:59:59"})))
    assert sessions["available"] and sessions["sessions"]
    assert json.loads(bridge.getAgentSessions("{}"))["available"] is False
    mark = sessions["sessions"][0]["marks"][0]
    rows = json.loads(bridge.getRowEvidence(json.dumps(
        {"db": "ai_agents", "table": "ai_agent_steps", "rowids": [mark["rowid"]], "title": "x"})))
    assert rows["groups"][0]["rows"][0]["__rowid__"] == mark["rowid"]
    # Only the three source tables open here; nothing else off the GUI thread.
    refused = json.loads(bridge.getRowEvidence(json.dumps(
        {"db": "registry", "table": "UserProfiles", "rowids": [1]})))
    assert "error" in refused
    got = []
    bridge.asyncResult.connect(lambda rid, payload: got.append((rid, json.loads(payload))))
    bridge.callAsync("getUsers", "r1", "[]")
    assert got and "__asyncError" in got[0][1]
    summary = json.loads(bridge.getSummary(json.dumps({"drivers": ["ai_agent"]})))
    assert {r["driver"] for r in summary["by_driver"]} == {"ai_agent"}
