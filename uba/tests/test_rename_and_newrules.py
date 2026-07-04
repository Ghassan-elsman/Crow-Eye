"""Tests for rename chains and the expanded detection rules."""

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine import aggregation


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=2000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True}, page_size=2000)["events"]
    return timed + timeless


# --- rename chains -------------------------------------------------------- #
def test_build_rename_chains_consecutive_dedup():
    rows = [
        aggregation.UsnRow(1, "C", "a.txt", 1, 500, 500, "2026-06-12 17:00:00", "RENAME_OLD_NAME", 1.0),
        aggregation.UsnRow(2, "C", "b.txt", 2, 500, 500, "2026-06-12 17:00:01", "RENAME_NEW_NAME | CLOSE", 2.0),
        aggregation.UsnRow(3, "C", "b.txt", 3, 500, 500, "2026-06-12 17:00:02", "RENAME_OLD_NAME", 3.0),
        aggregation.UsnRow(4, "C", "c.txt", 4, 500, 500, "2026-06-12 17:00:03", "RENAME_NEW_NAME | CLOSE", 4.0),
    ]
    chains, recycle = aggregation.build_rename_chains(rows)
    assert len(chains) == 1
    assert chains[0].names == ["a.txt", "b.txt", "c.txt"]
    assert recycle == []


def test_recycle_rename_split_out():
    rows = [
        aggregation.UsnRow(1, "C", "secret.doc", 1, 300, 300, "2026-06-12 15:00:00", "RENAME_OLD_NAME", 1.0),
        aggregation.UsnRow(2, "C", "$R12.doc", 2, 300, 300, "2026-06-12 15:00:01", "RENAME_NEW_NAME | CLOSE", 2.0),
    ]
    chains, recycle = aggregation.build_rename_chains(rows)
    assert chains == []                 # not a rename
    assert len(recycle) == 1            # the $R row goes to soft-delete


def test_rename_event_exposes_full_chain(artifacts_dir):
    eng = run(artifacts_dir)
    renames = [e for e in all_events(eng) if e["activity"] == "file_renamed"]
    chained = [e for e in renames if e["details"].get("rename_chain")]
    assert chained, "a rename event should carry the full name history"
    three = [e for e in chained if len(e["details"]["rename_chain"]) >= 3]
    assert three, "the A->B->C fixture chain should surface all names"
    e = three[0]
    assert e["details"]["rename_chain"][:3] == ["a.txt", "b.txt", "c.txt"]
    assert "renamed 2 times" in e["description"]


def test_simple_rename_two_names(artifacts_dir):
    eng = run(artifacts_dir)
    renames = [e for e in all_events(eng) if e["activity"] == "file_renamed"]
    joined = " | ".join(e["description"] for e in renames)
    assert "draft.txt" in joined and "final.txt" in joined


def test_soft_delete_still_detected(artifacts_dir):
    eng = run(artifacts_dir)
    soft = [e for e in all_events(eng) if e["activity"] == "file_soft_deleted"]
    assert soft and any("secret.doc" in e["description"] for e in soft)


# --- new rules ------------------------------------------------------------ #
def test_app_error_rule(artifacts_dir):
    eng = run(artifacts_dir)
    errs = [e for e in all_events(eng) if e["activity"] == "app_error"]
    assert errs
    assert any("winword" in e["description"].lower() for e in errs)
    assert errs[0]["behavior_class"] == "application"


def test_service_state_changed_rule(artifacts_dir):
    eng = run(artifacts_dir)
    svc = [e for e in all_events(eng) if e["activity"] == "service_state_changed"]
    assert svc
    assert svc[0]["actor_type"] == "System"


def test_no_actor_without_basis(artifacts_dir):
    eng = run(artifacts_dir)
    bad = eng.store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE actor_name != '' AND actor_basis = ''"
    ).fetchone()[0]
    assert bad == 0
