"""The UBA window's heavier reads run off the GUI thread and answer the same.

getSummary, getDriversByPerson, getBehaviorEvents and getDaySummary are in
uba_bridge.ASYNC_SLOTS: a worker runs them while the window stays live, each
holding the event store's lock. The story pages by a row-value cursor over a
(ts_start, event_id) index; the pages, joined, are the whole ordered story,
in both directions.
"""
import json
import time

import pytest

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.evidence import EvidenceFetcher
from uba.uba_bridge import ASYNC_SLOTS, UBABridge
from PyQt5.QtWidgets import QApplication

# Before any bridge: the queued answer needs an application to deliver it.
# A widget application, as the suite's qapp fixture makes: a bare
# QCoreApplication here left every later widget test unable to make one.
APP = QApplication.instance() or QApplication(["uba-tests"])


@pytest.fixture
def bridge(artifacts_dir):
    b = UBABridge(str(artifacts_dir))
    b.engine = BehaviorEngine(str(artifacts_dir))
    b.engine.run(progress_cb=lambda p, l: None)
    b.fetcher = EvidenceFetcher(b.engine.db_pool)
    b._analysis_done = True
    return b


def _async(bridge, method, *args):
    app = APP
    got = []
    bridge.asyncResult.connect(lambda rid, payload: got.append(payload))
    bridge.callAsync(method, "r1", json.dumps(list(args)))
    deadline = time.time() + 20
    while not got and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert got, "no answer from %s" % method
    return json.loads(got[0])


def test_each_heavy_reader_answers_the_same_off_the_gui_thread(bridge):
    # getSessions and getEvidence read the evidence pool; they are safe off the
    # GUI thread now that getSessions hands its thread's connections back
    # (_cleanup_worker_pool) and getEvidence reads on a throwaway own pool.
    assert {"getSummary", "getDriversByPerson", "getBehaviorEvents", "getDaySummary",
            "getSessions", "getRowEvidence", "getEvidence"} <= ASYNC_SLOTS
    first = json.loads(bridge.getBehaviorEvents(json.dumps({"page_size": 1})))["events"][0]
    day, eid = first["ts_start"][:10], first["event_id"]
    for method, arg in (("getSummary", "{}"), ("getDriversByPerson", "{}"),
                        ("getBehaviorEvents", json.dumps({"page_size": 50})),
                        ("getDaySummary", json.dumps({"day": day})),
                        ("getEvidence", json.dumps({"event_id": eid}))):
        assert _async(bridge, method, arg) == json.loads(getattr(bridge, method)(arg)), method
    # getSessions takes no request argument; it reads the registry/logs pool.
    assert _async(bridge, "getSessions") == json.loads(bridge.getSessions()), "getSessions"


@pytest.mark.parametrize("order", ["desc", "asc"])
def test_the_pages_joined_are_the_whole_story(bridge, order):
    store = bridge.engine.store
    want = [r[0] for r in store.conn.execute(
        "SELECT event_id FROM events WHERE ts_start IS NOT NULL ORDER BY ts_start %s, event_id %s"
        % (order, order))]
    got, cursor = [], None
    for _ in range(len(want) + 2):
        page = store.query_events(filters={"order": order}, cursor=cursor, page_size=3)
        got += [e["event_id"] for e in page["events"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert got == want and len(want) > 3


def test_the_cursor_reads_the_index(bridge):
    conn = bridge.engine.store.conn
    plan = " ".join(str(r[3]) for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM events WHERE ts_start IS NOT NULL AND "
        "(ts_start, event_id) < ('2026-06-10 00:00:00', 'x') "
        "ORDER BY ts_start DESC, event_id DESC LIMIT 10"))
    assert "idx_events_ts" in plan and "SCAN events" not in plan


def test_a_stored_analysis_gains_the_index(bridge, artifacts_dir):
    from uba.engine import persisted_store
    # a store saved without the new index, as an older build left it
    bridge.engine.store.conn.execute("DROP INDEX IF EXISTS idx_events_ts_id")
    ps = persisted_store.PersistedStore(str(artifacts_dir))
    assert ps.save(bridge.engine.store, {"format": "test"})
    store, _meta = ps.load()
    assert store is not None
    names = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_events_ts_id" in names
