"""End-to-end engine tests over the synthetic fixture case."""

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine import aggregation


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=1000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True},
                                      page_size=1000)["events"]
    return timed + timeless


def test_engine_runs_and_finds_events(artifacts_dir):
    eng = run(artifacts_dir)
    assert eng.stats["total_events"] > 0


def test_user_map_resolves_profile(artifacts_dir):
    eng = run(artifacts_dir)
    users = {u["username"] for u in eng.users()}
    assert "Alice" in users


def test_no_actor_without_basis(artifacts_dir):
    """Forensic invariant: a named actor must always carry its justification."""
    eng = run(artifacts_dir)
    bad = eng.store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE actor_name != '' AND actor_basis = ''"
    ).fetchone()[0]
    assert bad == 0


def test_userassist_corroborated_by_4688(artifacts_dir):
    """notepad UserAssist (10:00:00) + 4688 (10:00:02) -> corroborated."""
    eng = run(artifacts_dir)
    hits = [e for e in all_events(eng)
            if e["activity"] == "app_launch" and "notepad" in e["description"].lower()]
    assert hits and hits[0]["confidence"] == "corroborated"
    assert hits[0]["actor_name"] == "Alice"


def test_userassist_empty_timestamp_is_timeless(artifacts_dir):
    """ghost.exe has run_count 5 but no last_execution -> timeless, kept."""
    eng = run(artifacts_dir)
    timeless = eng.store.query_events(filters={"timeless": True},
                                      page_size=1000)["events"]
    ghosts = [e for e in timeless if "ghost" in e["description"].lower()]
    assert ghosts
    assert ghosts[0]["ts_start"] is None
    assert ghosts[0]["actor_name"] == "Alice"


def test_bam_pseudo_row_filtered(artifacts_dir):
    """The BAM 'Version' pseudo-row must never become an event."""
    eng = run(artifacts_dir)
    assert not [e for e in all_events(eng)
                if e["description"] and "Version" == e["details"].get("program_path")]


def test_file_creation_attributed_to_user_folder(artifacts_dir):
    eng = run(artifacts_dir)
    created = [e for e in all_events(eng) if e["activity"] == "file_created"]
    assert created
    alice = [e for e in created if e["actor_name"] == "Alice"]
    assert alice, "files under /Users/Alice should attribute to Alice"


def test_soft_delete_detected_from_usn_fallback(artifacts_dir):
    """No recyclebin DB -> soft delete recovered from $R rename pair."""
    eng = run(artifacts_dir)
    soft = [e for e in all_events(eng) if e["activity"] == "file_soft_deleted"]
    assert soft
    assert "Recycle Bin" in soft[0]["description"]
    assert "secret.doc" in soft[0]["description"]


def test_rename_pair_paired(artifacts_dir):
    eng = run(artifacts_dir)
    renamed = [e for e in all_events(eng) if e["activity"] == "file_renamed"]
    assert renamed
    joined = " ".join(e["description"] for e in renamed)
    assert "draft.txt" in joined and "final.txt" in joined


def test_noise_rows_skipped(artifacts_dir):
    eng = run(artifacts_dir)
    assert eng.stats.get("usn_rows_skipped_noise", 0) >= 1


def test_time_change_is_unattributed_and_suspicious(artifacts_dir):
    eng = run(artifacts_dir)
    tc = [e for e in all_events(eng) if e["activity"] == "time_changed"]
    assert tc
    assert tc[0]["actor_name"] == ""          # kernel log names no one
    assert tc[0]["severity"] == "suspicious"


def test_service_install_corroborated(artifacts_dir):
    eng = run(artifacts_dir)
    svc = [e for e in all_events(eng) if e["activity"] == "service_installed"]
    assert svc
    assert svc[0]["actor_type"] == "System"


def test_interactive_session_built(artifacts_dir):
    eng = run(artifacts_dir)
    assert len(eng.sessions.sessions) >= 1
    assert eng.sessions.sessions[0].username == "Alice"


def test_coverage_reports_degraded_log_cleared(artifacts_dir):
    eng = run(artifacts_dir)
    statuses = {r["rule_id"]: r["status"] for r in eng.coverage_report["rules"]}
    # 1102/104 absent in fixture -> log_cleared degraded, not active
    assert statuses.get("log_cleared") in ("degraded", "unavailable")
    assert eng.coverage_report["counts"]["requires_collection"] > 0


def test_classify_reason():
    assert aggregation.classify_reason("FILE_DELETE | CLOSE") == aggregation.OP_DELETE
    assert aggregation.classify_reason("FILE_CREATE") == aggregation.OP_CREATE
    assert aggregation.classify_reason("DATA_OVERWRITE | CLOSE") == aggregation.OP_MODIFY
    assert aggregation.classify_reason("RENAME_NEW_NAME") == aggregation.OP_RENAME
    assert aggregation.classify_reason("CLOSE") is None
    assert aggregation.classify_reason("SECURITY_CHANGE | CLOSE") is None
