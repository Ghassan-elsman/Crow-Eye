"""Analyst-created behaviour rules (uba_user_rules.json): table rules over a
parsed table, derived rules over behaviours already found.

Every test reads and writes its own config folder (conftest's
_isolated_settings points APPDATA at a temp folder), so nothing here touches
the analyst's real rules file.
"""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from uba.engine import rule_switches, user_rules
from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.extractors import declarative
from uba.engine.rule_loader import load_rules, validate_user_rule
from uba.utils.db_access import DbPool, resolve_db_path

ALICE_SID = "S-1-5-21-111-222-333-1001"


def _plant_prefetch(artifacts_dir, exe, ts):
    """One more Prefetch row; returns its rowid."""
    conn = sqlite3.connect(os.path.join(str(artifacts_dir), "prefetch_data.db"))
    cur = conn.execute(
        "INSERT INTO prefetch_data (filename, executable_name, hash, run_count, "
        "last_executed, run_times, volumes, directories, resources, created_on, "
        "modified_on, accessed_on) VALUES (?, ?, 'ab', 1, ?, ?, '', '', '', '', '', '')",
        ("%s-AB.pf" % exe, exe, ts, json.dumps([ts])))
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return rowid


def _mimikatz_rule(**over):
    rule = {
        "id": "user_mimikatz_prefetch", "kind": "table",
        "title": "Mimikatz ran", "activity": "program_run",
        "behavior_class": "user", "severity": "critical",
        "description": "{actor} ran {executable_name}",
        "source": {"db": "prefetch", "table": "prefetch_data"},
        "logic_operator": "AND",
        "conditions": [{"feather_id": "prefetch_data", "field_name": "executable_name",
                        "operator": "contains", "value": "mimikatz"}],
        "condition_groups": [],
        "columns": {"time": "last_executed", "time_basis": "exact",
                    "actor": {"mode": "hive_owner", "column": ""},
                    "app": "executable_name"},
        "aggregation": {"mode": "none"},
    }
    rule.update(over)
    return rule


def _psexec_rule(**over):
    rule = {
        "id": "user_psexec_run", "kind": "derived",
        "title": "PsExec ran", "activity": "program_run",
        "behavior_class": "user", "severity": "suspicious",
        "description": "PsExec: {description}",
        "base": {"rule_ids": ["program_run"], "activities": []},
        "logic_operator": "AND",
        "conditions": [{"feather_id": "event", "field_name": "details.executable",
                        "operator": "equals", "value": "psexec.exe"}],
        "condition_groups": [],
    }
    rule.update(over)
    return rule


def _events(engine, rule_id):
    return [engine.store.get_event(r[0]) for r in engine.store.conn.execute(
        "SELECT event_id FROM events WHERE rule_id = ? ORDER BY ts_start", (rule_id,))]


def _coverage(engine, rule_id):
    return next(e for e in engine.coverage_report["rules"] if e["rule_id"] == rule_id)


# ----------------------------------------------------------------- table
def test_table_rule_fires_with_actor_sid_and_evidence(artifacts_dir):
    rowid = _plant_prefetch(artifacts_dir, "MIMIKATZ.EXE", "2026-06-12 14:05:00")
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=[_mimikatz_rule()])
    eng.run()
    events = _events(eng, "user_mimikatz_prefetch")
    assert len(events) == 1
    ev = events[0]
    # The fixture has one profile, and the hive-owner mode on a row with no
    # owner column takes the only-profile rule of the attribution ladder.
    assert ev["actor_type"] == "User" and ev["actor_name"] == "Alice"
    assert ev["actor_sid"] == ALICE_SID
    assert "only user profile" in ev["actor_basis"]
    assert ev["ts_start"] == "2026-06-12 14:05:00"
    assert ev["description"] == "Alice ran MIMIKATZ.EXE"
    assert ev["app_name"] == "MIMIKATZ"
    assert ev["severity"] == "critical" and ev["user_rule"] is True
    assert ev["evidence"] == [{"db": "prefetch", "table": "prefetch_data", "role": "primary",
                               "rowids": [rowid], "count": 1}]
    entry = _coverage(eng, "user_mimikatz_prefetch")
    assert entry["status"] == "active" and entry["user_rule"] is True
    # The built-in Prefetch rule still reports the same run, as a program.
    assert any(e["details"].get("executable") == "MIMIKATZ.EXE"
               for e in _events(eng, "program_run"))
    eng.close()


def test_table_rule_sid_column_resolves_through_the_ladder(artifacts_dir):
    rule = _mimikatz_rule(
        id="user_bam_chrome", title="Chrome in BAM", activity="app_launch",
        description="{actor} used {app_name}", severity="notable",
        source={"db": "registry", "table": "BAM"},
        conditions=[{"feather_id": "BAM", "field_name": "app_name",
                     "operator": "equals", "value": "CHROME.EXE"}],
        columns={"time": "last_execution", "time_basis": "at_or_before",
                 "actor": {"mode": "sid", "column": "sid"}, "app": "process_path"})
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=[rule])
    eng.run()
    (ev,) = _events(eng, "user_bam_chrome")
    assert ev["actor_name"] == "Alice" and ev["actor_sid"] == ALICE_SID
    assert ALICE_SID in ev["actor_basis"]
    # "at or before" is said, with the registry key-time caveat.
    assert "write time" in ev["caveat"] or "last-write" in ev["caveat"]
    eng.close()


def test_aggregation_per_actor_per_day(artifacts_dir):
    for ts in ("2026-06-12 14:05:00", "2026-06-12 15:10:00", "2026-06-13 09:00:00"):
        _plant_prefetch(artifacts_dir, "MIMIKATZ.EXE", ts)
    rule = _mimikatz_rule(aggregation={"mode": "per_actor_day"})
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=[rule])
    eng.run()
    events = _events(eng, "user_mimikatz_prefetch")
    assert [(e["ts_start"], e["ts_end"], e["aggregate_count"]) for e in events] == [
        ("2026-06-12 14:05:00", "2026-06-12 15:10:00", 2),
        ("2026-06-13 09:00:00", "2026-06-13 09:00:00", 1)]
    assert "2 matching rows that day" in events[0]["description"]
    assert len(events[0]["evidence"][0]["rowids"]) == 2
    eng.close()


# --------------------------------------------------------------- derived
def test_derived_rule_fires_and_carries_base_evidence(artifacts_dir):
    rowid = _plant_prefetch(artifacts_dir, "PSEXEC.EXE", "2026-06-12 16:00:00")
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=[_psexec_rule()])
    eng.run()
    events = _events(eng, "user_psexec_run")
    assert len(events) == 1
    ev = events[0]
    assert ev["severity"] == "suspicious" and ev["user_rule"] is True
    assert ev["description"] == "PsExec: The program 'PSEXEC' ran on the computer"
    assert ev["details"]["derived_from"]["rule_id"] == "program_run"
    assert ev["evidence"][0]["db"] == "prefetch"
    assert ev["evidence"][0]["rowids"] == [rowid]
    # The base behaviour is still there, unchanged.
    base = [e for e in _events(eng, "program_run")
            if e["details"].get("executable") == "PSEXEC.EXE"]
    assert len(base) == 1 and base[0]["user_rule"] is False
    # Notepad's runs are program_run too, and were filtered out.
    assert all("PSEXEC" in e["description"] for e in events)
    eng.close()


def test_derived_rule_on_a_turned_off_base_says_so(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=["program_run"],
                         user_rules=[_psexec_rule()])
    eng.run()
    entry = _coverage(eng, "user_psexec_run")
    assert entry["status"] == "unavailable"
    assert "turned off in Settings" in entry["note"]
    eng.close()


# ------------------------------------------------------------- refusals
def test_missing_column_is_refused_with_the_reason(artifacts_dir):
    _plant_prefetch(artifacts_dir, "MIMIKATZ.EXE", "2026-06-12 14:05:00")
    rule = _mimikatz_rule(conditions=[{"feather_id": "prefetch_data", "field_name": "Executable",
                                       "operator": "contains", "value": "mimikatz"}])
    pool = DbPool(str(artifacts_dir))
    problems = declarative.check_table_rule(pool, rule)
    pool.close()
    assert problems == ["The column 'Executable' (a condition) is not in the table "
                        "'prefetch_data' in this case."]
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=[rule])
    eng.run()
    assert _events(eng, "user_mimikatz_prefetch") == []
    entry = _coverage(eng, "user_mimikatz_prefetch")
    assert entry["status"] == "unavailable"
    assert "'Executable'" in entry["note"] and entry["note"].startswith("Not run")
    eng.close()


def test_missing_table_and_template_column_are_refused(artifacts_dir):
    pool = DbPool(str(artifacts_dir))
    assert "is not in the database" in declarative.check_table_rule(
        pool, _mimikatz_rule(source={"db": "prefetch", "table": "nope"}))[0]
    assert declarative.check_table_rule(
        pool, _mimikatz_rule(description="{actor} ran {Exe}")) == [
        "The column 'Exe' (the description) is not in the table 'prefetch_data' in this case."]
    pool.close()


def test_validation_refuses_builtin_ids_and_bad_shapes():
    builtin = {r["id"] for r in load_rules()["rules"]}
    assert "built-in" in " ".join(validate_user_rule(_mimikatz_rule(id="program_run"), builtin))
    assert validate_user_rule(_mimikatz_rule(), builtin) == []
    assert validate_user_rule(_psexec_rule(), builtin) == []
    bad = _mimikatz_rule(severity="high", conditions=[{"field_name": "x", "operator": "like",
                                                       "value": "a"}])
    found = " ".join(validate_user_rule(bad, builtin))
    assert "severity" in found and "unknown operator" in found
    assert "inside the case" in " ".join(validate_user_rule(
        _mimikatz_rule(source={"db": "../outside.db", "table": "t"}), builtin))
    assert "own base" in " ".join(validate_user_rule(
        _psexec_rule(base={"rule_ids": ["user_psexec_run"]}), builtin))


def test_derived_rule_unknown_field_is_refused(artifacts_dir):
    rule = _psexec_rule(conditions=[{"feather_id": "event", "field_name": "program",
                                     "operator": "equals", "value": "x"}])
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=[rule])
    eng.run()
    entry = _coverage(eng, "user_psexec_run")
    assert entry["status"] == "unavailable" and "'program'" in entry["note"]
    eng.close()


# ------------------------------------------------------- file and switches
def test_saved_rules_load_globally_and_switch_off(artifacts_dir):
    _plant_prefetch(artifacts_dir, "MIMIKATZ.EXE", "2026-06-12 14:05:00")
    ok, problems, stored = user_rules.save_rule(_mimikatz_rule())
    assert ok, problems
    assert stored["version"] == 1 and stored["created_utc"] and stored["author"]["created_by"] == "human"
    path = user_rules.rules_path()
    assert path.startswith(os.environ["APPDATA"]) and path.endswith("uba_user_rules.json")

    # Picked up from the file by default, shown on both switch screens.
    rows = {r["rule_id"]: r for r in rule_switches.switch_rows()}
    assert rows["user_mimikatz_prefetch"]["user_rule"] is True
    assert rows["user_mimikatz_prefetch"]["user_kind"] == "table"
    assert rows["program_run"]["user_rule"] is False
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    assert len(_events(eng, "user_mimikatz_prefetch")) == 1
    eng.close()

    # Turned off: not run, and coverage says off - not "found nothing".
    assert rule_switches.set_rule_enabled("user_mimikatz_prefetch", False)
    assert rule_switches.switch_rows() and not {
        r["rule_id"]: r for r in rule_switches.switch_rows()}["user_mimikatz_prefetch"]["enabled"]
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    assert _events(eng, "user_mimikatz_prefetch") == []
    assert _coverage(eng, "user_mimikatz_prefetch")["status"] == "off"
    eng.close()


def test_edit_keeps_created_and_bumps_version_export_import(tmp_path):
    ok, _p, first = user_rules.save_rule(_mimikatz_rule())
    assert ok
    ok, _p, second = user_rules.save_rule(dict(_mimikatz_rule(), title="Mimikatz (edited)"))
    assert ok and second["version"] == 2 and second["created_utc"] == first["created_utc"]
    out = tmp_path / "export.json"
    assert user_rules.export_rules(str(out)) == 1
    assert user_rules.delete_rule("user_mimikatz_prefetch")
    assert user_rules.read_file()["rules"] == []
    added, skipped = user_rules.import_rules(str(out))
    assert added == ["user_mimikatz_prefetch"] and skipped == []
    added, skipped = user_rules.import_rules(str(out))
    assert added == [] and skipped[0][0] == "user_mimikatz_prefetch"
    # A built-in id is refused at save time, and nothing is written.
    ok, problems, _ = user_rules.save_rule(_mimikatz_rule(id="usb_connected"))
    assert not ok and "built-in" in " ".join(problems)


def test_a_colliding_rule_in_the_file_is_dropped_with_a_reason(artifacts_dir):
    path = user_rules.rules_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "rules": [_mimikatz_rule(id="usb_connected"),
                                           _mimikatz_rule(severity="extreme")]}, handle)
    rules, problems = user_rules.load_user_rules()
    assert [r["id"] for r in rules] == ["user_mimikatz_prefetch"]
    assert "built-in" in problems["usb_connected"][0]
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[])
    eng.run()
    entry = _coverage(eng, "user_mimikatz_prefetch")
    assert entry["status"] == "unavailable" and "not valid" in entry["note"]
    eng.close()


def test_stored_analysis_rebuilds_when_a_user_rule_changes(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run_or_load()
    assert eng.stamp["user_rules_hash"] == ""
    assert eng.is_current() and not eng.user_rules_changed()
    assert user_rules.save_rule(_mimikatz_rule())[0]
    assert not eng.is_current() and eng.user_rules_changed()
    eng.close()
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run_or_load()
    assert not eng.loaded_from_store and eng.stamp["user_rules_hash"]
    eng.close()
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run_or_load()
    assert eng.loaded_from_store
    eng.close()


# ------------------------------------------------- built-ins are unchanged
def test_builtin_outputs_unchanged_by_user_rules(artifacts_dir):
    _plant_prefetch(artifacts_dir, "MIMIKATZ.EXE", "2026-06-12 14:05:00")
    _plant_prefetch(artifacts_dir, "PSEXEC.EXE", "2026-06-12 16:00:00")

    def snapshot(rules):
        eng = BehaviorEngine(str(artifacts_dir), disabled_rules=[], user_rules=rules)
        eng.run()
        rows = eng.store.conn.execute(
            "SELECT rule_id, event_id, actor_sid, description FROM events "
            "WHERE user_rule = 0 ORDER BY rule_id, event_id").fetchall()
        cov = {e["rule_id"]: e["status"] for e in eng.coverage_report["rules"]
               if not e.get("user_rule")}
        mine = eng.store.conn.execute(
            "SELECT COUNT(*) FROM events WHERE user_rule = 1").fetchone()[0]
        eng.close()
        return [tuple(r) for r in rows], cov, mine

    plain, plain_cov, none = snapshot([])
    with_rules, rules_cov, mine = snapshot([_mimikatz_rule(), _psexec_rule()])
    assert none == 0 and mine == 2
    assert with_rules == plain
    assert rules_cov == plain_cov


# ------------------------------------------------------------- plumbing
def test_file_database_names_stay_inside_target_artifacts(artifacts_dir):
    sub = os.path.join(str(artifacts_dir), "Extra")
    os.makedirs(sub)
    sqlite3.connect(os.path.join(sub, "other.db")).close()
    assert resolve_db_path(str(artifacts_dir), "Extra/other.db").endswith("other.db")
    assert resolve_db_path(str(artifacts_dir), "../registry_data.db") is None
    assert resolve_db_path(str(artifacts_dir), "C:/Windows/x.db") is None


def test_declarative_rules_import_without_qt():
    """The engine runs headless (Sentinel imports it): the user-rule path,
    including the Wing condition language it borrows, must not load Qt."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = (
        "import sys\n"
        "class B:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'PyQt5' or name.startswith('PyQt5.'):\n"
        "            raise ImportError('blocked ' + name)\n"
        "sys.meta_path.insert(0, B())\n"
        "from uba.engine.extractors import declarative\n"
        "declarative._semantic_classes()\n"
        "from uba.engine.behavior_engine import BehaviorEngine\n"
        "print('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ok")


# ------------------------------------------------------------ the editor
@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_editor_round_trips_a_rule_and_refuses_a_missing_column(qapp, artifacts_dir):
    from uba.ui import behaviour_rule_dialog as brd
    dialog = brd.BehaviourRuleDialog(None, artifacts_dir=str(artifacts_dir), offer_rerun=False)
    dialog._load(_mimikatz_rule(), "table")
    built = dialog.build_rule()
    for key in ("id", "kind", "title", "activity", "behavior_class", "severity",
                "description", "source", "conditions", "columns", "aggregation"):
        assert built[key] == _mimikatz_rule()[key], key
    assert dialog.problems(built) == []

    built["conditions"][0]["field_name"] = "Executable"
    assert any("'Executable'" in p for p in dialog.problems(built))

    dialog._load(_psexec_rule(), "derived")
    derived = dialog.build_rule()
    assert derived["base"]["rule_ids"] == ["program_run"]
    assert derived["conditions"] == _psexec_rule()["conditions"]
    assert dialog.problems(derived) == []
    dialog.reject()


def test_editor_test_button_previews_on_the_case(qapp, artifacts_dir):
    rowid = _plant_prefetch(artifacts_dir, "MIMIKATZ.EXE", "2026-06-12 14:05:00")
    result = declarative.preview_table_rule(str(artifacts_dir), _mimikatz_rule())
    assert result["ok"] and result["count"] == 1
    row = result["events"][0]
    assert row["actor_name"] == "Alice" and row["actor_sid"] == ALICE_SID
    assert row["evidence"] == "prefetch:prefetch_data:%d" % rowid
