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
    """A sub-day window returns timed events that OVERLAP it; timeless always
    pass (they render in their own strip).

    Overlap, not containment: the store filters on
    `ts_end >= start AND ts_start <= end`, so an event that begins before the
    window and ends after it belongs in the answer. This used to assert
    containment and held only because nothing in the fixture spanned a window
    boundary - the browser history-gap rule, which is a multi-day phenomenon by
    nature, is the first that does.
    """
    eng = run(artifacts_dir)
    win = {"start": "2026-06-12 09:59:00", "end": "2026-06-12 10:05:00"}
    res = eng.store.query_events(filters=win, page_size=1000)
    assert res["total"] > 0
    for e in res["events"]:
        if e["ts_start"] is None:
            continue
        ends = e["ts_end"] or e["ts_start"]
        assert e["ts_start"] <= win["end"] and ends >= win["start"], (
            "event %s (%s..%s) does not overlap the window"
            % (e["rule_id"], e["ts_start"], ends))


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


# --------------------------------------------------------------------- #
# Rule filter. rule_id was stored on every event from the start but was not
# filterable, not summarised and not exposed — so "show me only these
# detections" was impossible.
# --------------------------------------------------------------------- #
def test_filter_by_rule(artifacts_dir):
    eng = run(artifacts_dir)
    res = eng.store.query_events(
        filters={"rules": ["interactive_logon", "logoff"]}, page_size=500)
    assert res["total"] > 0
    assert {e["rule_id"] for e in res["events"]} <= {"interactive_logon", "logoff"}


def test_rule_filter_narrows(artifacts_dir):
    eng = run(artifacts_dir)
    everything = eng.store.query_events(page_size=2000)["total"]
    one = eng.store.query_events(
        filters={"rules": ["interactive_logon"]}, page_size=2000)["total"]
    assert 0 < one < everything


def test_unknown_rule_id_returns_nothing_not_everything(artifacts_dir):
    """A filter that matches nothing must return nothing — silently ignoring an
    unknown value would show the whole case as if it were filtered."""
    eng = run(artifacts_dir)
    res = eng.store.query_events(filters={"rules": ["no_such_rule"]}, page_size=100)
    assert res["total"] == 0


def test_rule_filter_combines_with_severity(artifacts_dir):
    eng = run(artifacts_dir)
    res = eng.store.query_events(
        filters={"rules": ["failed_logon"], "severities": ["suspicious"]},
        page_size=500)
    assert res["total"] > 0
    assert all(e["rule_id"] == "failed_logon" and e["severity"] == "suspicious"
               for e in res["events"])


def test_summary_groups_by_rule(artifacts_dir):
    eng = run(artifacts_dir)
    by_rule = eng.store.summary({})["by_rule"]
    assert by_rule
    ids = {r["rule_id"] for r in by_rule}
    assert "interactive_logon" in ids
    assert all(r["events"] > 0 for r in by_rule)


def test_rules_catalog_counts_are_unfiltered(artifacts_dir):
    """The picker's counts must not move when a filter is applied, or options
    would vanish as soon as they were deselected."""
    eng = run(artifacts_dir)
    cat = eng.rules_catalog()
    assert len(cat) == len(eng.rules_config["rules"])
    counted = {r["rule_id"]: r["event_count"] for r in cat}
    total = eng.store.query_events(page_size=5000)["total"] \
        + eng.store.query_events(filters={"timeless": True}, page_size=5000)["total"]
    assert sum(counted.values()) == total
    # every entry carries what the picker renders
    for r in cat:
        assert r["title"] and r["status"] in ("active", "degraded", "unavailable")
        assert isinstance(r["event_count"], int)


def test_rules_catalog_surfaces_active_rules_that_found_nothing(artifacts_dir):
    """'The data was there and this rule found nothing' is a different statement
    from 'no data', and this is the only place it is visible."""
    eng = run(artifacts_dir)
    cat = eng.rules_catalog()
    active = [r for r in cat if r["status"] == "active"]
    assert active
    # the shape must allow a zero — a catalogue that silently dropped them
    # would hide exactly the case worth seeing
    assert all(r["event_count"] >= 0 for r in active)


# --------------------------------------------------------------------- #
# Reading order
# --------------------------------------------------------------------- #
def test_ascending_order_reads_forwards(artifacts_dir):
    eng = run(artifacts_dir)
    asc = eng.store.query_events(filters={"order": "asc"}, page_size=50)["events"]
    desc = eng.store.query_events(filters={"order": "desc"}, page_size=50)["events"]
    assert asc and desc
    assert [e["ts_start"] for e in asc] == sorted(e["ts_start"] for e in asc)
    assert asc[0]["ts_start"] <= desc[0]["ts_start"]


def test_ascending_pagination_does_not_repeat_or_skip(artifacts_dir):
    """Keyset pagination has to invert with the sort, or the second page either
    repeats the first or jumps past it."""
    eng = run(artifacts_dir)
    first = eng.store.query_events(filters={"order": "asc"}, page_size=5)
    assert first["next_cursor"]
    second = eng.store.query_events(
        filters={"order": "asc"}, cursor=first["next_cursor"], page_size=5)
    ids_first = [e["event_id"] for e in first["events"]]
    ids_second = [e["event_id"] for e in second["events"]]
    assert not set(ids_first) & set(ids_second)
    assert first["events"][-1]["ts_start"] <= second["events"][0]["ts_start"]
