from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.evidence import EvidenceFetcher


def _eng(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def test_keyset_pagination_no_overlap(artifacts_dir):
    eng = _eng(artifacts_dir)
    page1 = eng.store.query_events(page_size=5)
    ids1 = {e["event_id"] for e in page1["events"]}
    if page1["next_cursor"]:
        page2 = eng.store.query_events(cursor=page1["next_cursor"], page_size=5)
        ids2 = {e["event_id"] for e in page2["events"]}
        assert ids1.isdisjoint(ids2)


def test_summary_shapes(artifacts_dir):
    eng = _eng(artifacts_dir)
    summary = eng.store.summary()
    assert "by_class" in summary and "heatmap" in summary
    assert summary["by_severity"]


def test_filter_by_actor_unattributed(artifacts_dir):
    eng = _eng(artifacts_dir)
    res = eng.store.query_events(filters={"actors": [""]}, page_size=1000)
    assert all(e["actor_name"] == "" for e in res["events"])


def test_evidence_roundtrip(artifacts_dir):
    eng = _eng(artifacts_dir)
    # find a file-created burst event that carries a rowid_range
    ev = None
    for e in eng.store.query_events(page_size=1000)["events"]:
        if e["evidence"] and e["evidence"][0].get("count", 0) >= 1:
            ev = e
            break
    assert ev is not None
    fetcher = EvidenceFetcher(eng.db_pool)
    result = fetcher.fetch(ev["evidence"])
    assert result["groups"]
    first = result["groups"][0]
    assert first["rows"], "evidence rows must resolve back to source records"
    assert "__rowid__" in first["rows"][0]
