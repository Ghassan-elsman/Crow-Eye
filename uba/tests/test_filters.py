"""Tests for the time-range, user, and app filters."""

from uba.engine.behavior_engine import BehaviorEngine


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def test_app_dimension_populated(artifacts_dir):
    eng = run(artifacts_dir)
    apps = eng.apps()
    names = {a["app"] for a in apps}
    # notepad ran (prefetch + userassist), should surface as an app
    assert any("notepad" in n.lower() for n in names)
    # every listed app has a positive count
    assert all(a["event_count"] > 0 for a in apps)


def test_filter_by_app(artifacts_dir):
    eng = run(artifacts_dir)
    apps = eng.apps()
    target = apps[0]["app"]
    res = eng.store.query_events(filters={"apps": [target]}, page_size=500)
    assert res["total"] > 0
    assert all(e["app_name"] == target for e in res["events"])


def test_presence_events_have_no_app_name(artifacts_dir):
    """Folder-aggregated presence rows span many programs -> no single app."""
    eng = run(artifacts_dir)
    pres = eng.store.query_events(
        filters={"activities": ["program_presence"], "timeless": True},
        page_size=100)["events"]
    assert pres
    assert all(not e["app_name"] for e in pres)


def test_precise_time_window(artifacts_dir):
    """A sub-day window returns only in-window timed events; timeless always
    pass (they render in their own strip)."""
    eng = run(artifacts_dir)
    win = {"start": "2026-06-12 09:59:00", "end": "2026-06-12 10:05:00"}
    res = eng.store.query_events(filters=win, page_size=1000)
    assert res["total"] > 0
    for e in res["events"]:
        if e["ts_start"] is not None:
            assert win["start"] <= e["ts_start"] <= win["end"]


def test_time_window_excludes_outside(artifacts_dir):
    eng = run(artifacts_dir)
    everything = eng.store.query_events(page_size=2000)["total"]
    tiny = eng.store.query_events(
        filters={"start": "2000-01-01 00:00:00", "end": "2000-01-01 00:01:00"},
        page_size=2000)["total"]
    assert tiny < everything   # an empty window drops the timed events


def test_app_filter_combines_with_time(artifacts_dir):
    eng = run(artifacts_dir)
    apps = eng.apps()
    target = next((a["app"] for a in apps if "notepad" in a["app"].lower()), apps[0]["app"])
    combined = eng.store.query_events(
        filters={"apps": [target], "start": "2026-06-12 00:00:00",
                 "end": "2026-06-12 23:59:59"}, page_size=500)
    assert all(e["app_name"] == target for e in combined["events"])
