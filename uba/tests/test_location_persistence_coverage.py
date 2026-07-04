"""Tests for the folder_label fix, RecentDocs decoding, persistence rules,
and coverage how/artifacts (UPDATE 2026-07-03h)."""

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine import description


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=2000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True}, page_size=2000)["events"]
    return timed + timeless


# --- folder_label / unknown location ------------------------------------- #
def test_folder_label_expands_short_names():
    assert description.folder_label("./PROGRA~1/COMMON~1/x/f.dll") == "the installed-programs area"
    assert description.folder_label("./PROGRA~3/Microsoft") == "a shared application-data area"
    # a path with no known folder shows the REAL folder, never "unknown"
    assert description.folder_label("./SomeApp/data/file.txt") == "SomeApp/data"


def test_folder_label_never_unknown_for_real_paths():
    for p in ("./Users/Gass3", "./$Extend/$Deleted/x", ".", "./Windows/System32/a.dll",
              "./Users/Gass3/AppData/Local/Discord/c.dat"):
        assert description.folder_label(p) != "an unknown location"


def test_no_unknown_location_events(artifacts_dir):
    eng = run(artifacts_dir)
    bad = eng.store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE description LIKE '%unknown location%'").fetchone()[0]
    assert bad == 0


# --- RecentDocs decoding -------------------------------------------------- #
def test_recentdocs_uses_decoded_names(artifacts_dir):
    eng = run(artifacts_dir)
    rd = [e for e in all_events(eng)
          if e["activity"] == "file_opened" and "recently opened" in e["description"]]
    assert rd
    e = rd[0]
    assert "Budget.xlsx" in e["description"]
    assert "Notes.txt" in e["description"]
    assert "MRUListEx" not in e["description"]        # ordering row skipped
    # deduped: Budget.xlsx appears once despite two subkeys
    assert e["details"]["documents"].count("Budget.xlsx") == 1


# --- persistence ---------------------------------------------------------- #
def test_autostart_program_user_writable_suspicious(artifacts_dir):
    eng = run(artifacts_dir)
    auto = [e for e in all_events(eng) if e["activity"] == "autostart"]
    sketchy = [e for e in auto if "Sketchy" in e["description"]]
    assert sketchy and sketchy[0]["severity"] == "suspicious"


def test_autostart_service_flags_user_path(artifacts_dir):
    eng = run(artifacts_dir)
    svc = [e for e in all_events(eng) if e["activity"] == "autostart_service"]
    flagged = [e for e in svc if "Evil Service" in e["description"]]
    assert flagged and flagged[0]["severity"] == "suspicious"
    # a Manual (start_type 3) service must NOT be treated as auto-start
    assert not any("Manual Service" in e["description"] for e in svc)


# --- coverage how + artifacts --------------------------------------------- #
def test_coverage_has_how_and_artifacts(artifacts_dir):
    eng = run(artifacts_dir)
    rules = eng.coverage_report["rules"]
    assert rules
    for r in rules:
        assert r["how"], "every rule should carry a 'how' sentence"
        assert isinstance(r["artifacts"], list) and r["artifacts"], r["rule_id"]
