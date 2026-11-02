"""The person key (actor_sid, host), the persisted event store, and the rule
switches - over the fixture case, with rows added where a test needs a
second profile or a log record the shared fixture deliberately lacks."""

import json
import os
import random
import sqlite3

import pytest
from pathlib import Path

from uba.engine import persisted_store, rule_switches
from uba.engine.attribution import ActorResolver
from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.extractors.context import ExtractorContext
from uba.engine.rule_loader import DEFAULT_RULES_PATH, load_rules
from uba.utils.db_access import DbPool

ALICE = "S-1-5-21-111-222-333-1001"
BOB = "S-1-5-21-111-222-333-1002"


def _events(eng):
    timed = eng.store.query_events(page_size=5000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True}, page_size=5000)["events"]
    return timed + timeless


def _exec(path, sql, rows=()):
    conn = sqlite3.connect(path)
    if rows:
        conn.executemany(sql, rows)
    else:
        conn.execute(sql)
    conn.commit()
    conn.close()


def _security(d, rows):
    _exec(str(Path(d) / "Log_Claw.db"),
          "INSERT INTO SecurityLogs (EventID, Source, EventType, Category, "
          "EventTimestampUTC, ComputerName, User, Keywords, TaskCategory, "
          "EventDescription) VALUES (?, '', '', '', ?, 'PC', ?, ?, '', '')", rows)


def _add_bob(d):
    """A second profile, so the only-profile rule no longer answers."""
    _exec(str(Path(d) / "registry_data.db"),
          "INSERT INTO UserProfiles (user_sid, username, profile_path, "
          "profile_image_path, profile_loaded, timestamp) VALUES (?, ?, ?, ?, '1', '')",
          [(BOB, "Bob", "Bob", "C:\\Users\\Bob")])


# --------------------------------------------------------------------------- SID
def test_every_user_event_of_a_profile_carries_its_sid(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    profiles = {name: sid for sid, name in eng.resolver.known_users.items()}
    users = [e for e in _events(eng) if e["actor_type"] == "User"]
    assert users
    for e in users:
        if e["actor_name"] in profiles:
            assert e["actor_sid"] == profiles[e["actor_name"]], (e["rule_id"], e["description"])
    # And the rules this phase touched each produced at least one such event.
    rules = {e["rule_id"] for e in users if e["actor_sid"] == ALICE}
    for rule in ("interactive_logon", "failed_logon", "folder_browsing", "file_opened",
                 "gui_app_launch"):
        assert rule in rules, rule


def test_every_event_names_the_case_computer(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    hosts = {e["host"] for e in _events(eng)}
    assert hosts == {"PC"}          # SystemLogs.ComputerName: no ComputerNameInfo here


def test_registry_computer_name_wins(artifacts_dir):
    _exec(str(Path(artifacts_dir) / "registry_data.db"),
          "CREATE TABLE ComputerNameInfo (computer_name TEXT, registered_owner TEXT, "
          "registered_organization TEXT, product_id TEXT, installation_date TEXT, "
          "parsed_at TEXT)")
    _exec(str(Path(artifacts_dir) / "registry_data.db"),
          "INSERT INTO ComputerNameInfo VALUES (?, '', '', '', '', '')", [("ALICE-PC",)])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    assert {e["host"] for e in _events(eng)} == {"ALICE-PC"}


def test_name_variants_are_one_person(artifacts_dir):
    # The e-mail a Microsoft account signs in under, bound to the SID by the
    # same 4672 record - the only thing that may bind it.
    _security(artifacts_dir, [
        (4672, "2026-06-12 10:05:00", "alice@outlook.com",
         ALICE + ",alice@outlook.com,MicrosoftAccount,0x5fc1d,SeDebugPrivilege")])
    resolver = ActorResolver(DbPool(str(artifacts_dir)))
    for name in ("Alice", "alice", "ALICE", "PC\\alice", "alice@outlook.com",
                 "MicrosoftAccount\\alice@outlook.com"):
        actor = resolver.from_account_name(name, "test")
        assert actor[0] == "User" and actor[1] == "Alice", name
        assert actor.sid == ALICE, name
    unknown = resolver.from_account_name("mallory", "test")
    assert unknown[0] == "User" and unknown[1] == "mallory" and unknown.sid == ""
    # An address no record binds is not guessed from its spelling.
    assert resolver.from_account_name("alice@example.com", "test").sid == ""
    system = resolver.from_account_name("LOCAL SERVICE", "test")
    assert system[0] == "System" and system.sid == "S-1-5-19"


def test_an_ambiguous_name_binds_to_nobody(artifacts_dir):
    _exec(str(Path(artifacts_dir) / "registry_data.db"),
          "INSERT INTO UserProfiles (user_sid, username, profile_path, "
          "profile_image_path, profile_loaded, timestamp) VALUES (?, ?, '', '', '1', '')",
          [(BOB, "alice")])      # a second profile spelled the same
    resolver = ActorResolver(DbPool(str(artifacts_dir)))
    assert resolver.sid_for_account("alice") == ""
    assert resolver.from_account_name("ALICE", "test").sid == ""


def test_enriched_sid_columns_still_resolve(artifacts_dir):
    # apply_identity() rewrites BAM.sid to "SID (MACHINE\\user)"; the BAM row
    # used to classify as 'unknown' and lose its actor.
    _exec(str(Path(artifacts_dir) / "registry_data.db"),
          "UPDATE BAM SET sid = ? WHERE sid = ?", [(ALICE + " (PC\\Alice)", ALICE)])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    bam = [e for e in _events(eng) if any(ev["table"] == "BAM" for ev in e["evidence"])]
    assert bam
    assert all(e["actor_name"] == "Alice" and e["actor_sid"] == ALICE for e in bam)


def test_failed_signin_in_another_spelling_is_the_same_person(artifacts_dir):
    _security(artifacts_dir, [
        (4625, "2026-06-12 22:0{}:00".format(i), "-",
         "S-1-5-18,PC$,WG,0x3e7,S-1-0-0,alice,PC,0xC000006D,%%2313,0xC000006A,2,"
         "User32,Negotiate,PC,-,-") for i in range(2)])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    failed = [e for e in _events(eng) if e["rule_id"] == "failed_logon"]
    assert failed and all(e["actor_name"] == "Alice" for e in failed)
    assert all(e["actor_sid"] == ALICE for e in failed)
    late = [e for e in failed if e["ts_start"].startswith("2026-06-12 22")]
    assert late and "account 'alice'" in late[0]["actor_basis"]


def test_log_cleared_and_clock_change_resolve_through_the_record_sid(artifacts_dir):
    _security(artifacts_dir, [
        (1102, "2026-06-12 23:00:00", "Alice", ALICE + ",Alice,PC,0x5fc1d"),
        (4616, "2026-06-12 23:05:00", "LOCAL SERVICE",
         "S-1-5-19,LOCAL SERVICE,NT AUTHORITY,0x3e5,2026-06-12T23:05:00Z,"
         "2026-06-12T23:05:01Z,0xc04,C:\\Windows\\System32\\svchost.exe")])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    ev = {e["rule_id"]: e for e in _events(eng)
          if e["ts_start"] in ("2026-06-12 23:00:00", "2026-06-12 23:05:00")}
    cleared = ev["log_cleared"]
    assert (cleared["actor_type"], cleared["actor_name"], cleared["actor_sid"]) == \
        ("User", "Alice", ALICE)
    clock = ev["time_changed"]
    assert (clock["actor_type"], clock["actor_name"], clock["actor_sid"]) == \
        ("System", "Local Service", "S-1-5-19")


def test_hive_rows_follow_their_owner_on_a_two_profile_machine(artifacts_dir):
    _add_bob(artifacts_dir)
    _exec(str(Path(artifacts_dir) / "registry_data.db"),
          "INSERT INTO Shellbags (file_name, parent_path, accessed_date, modified_date, "
          "created_date, registry_path, bag_views, user_name) "
          "VALUES (?, ?, ?, '', '', '', 'Shell', ?)",
          [("Payroll", "C:\\Users\\Bob\\Documents", "2026-06-12 14:00:00", "Bob"),
           ("Ghost", "C:\\Users\\Carol", "2026-06-12 14:01:00", "Carol")])
    _exec(str(Path(artifacts_dir) / "LnkDB.db"),
          "INSERT INTO LNK_Files (Source_Name, Source_Path, Local_Path, Time_Access, "
          "Time_Modification, Volume_Type, Network_Share_Name) "
          "VALUES (?, ?, ?, ?, '', 'Fixed', '')",
          [("plan.lnk",
            "C:\\Users\\Bob\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\plan.lnk",
            "D:\\plan.docx", "2026-06-12 14:02:00"),
           ("Edge.lnk", "C:\\Users\\Public\\Desktop\\Edge.lnk",
            "C:\\Program Files\\Edge\\msedge.exe", "2026-06-12 14:03:00")])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    events = _events(eng)

    def one(fragment):
        hits = [e for e in events if fragment in e["description"]]
        assert len(hits) == 1, (fragment, [h["description"] for h in hits])
        return hits[0]

    assert (one("Payroll")["actor_name"], one("Payroll")["actor_sid"]) == ("Bob", BOB)
    assert (one("Secret")["actor_name"], one("Secret")["actor_sid"]) == ("Alice", ALICE)
    assert one("Ghost")["actor_type"] == ""              # no profile 'Carol'
    assert (one("plan.docx")["actor_name"], one("plan.docx")["actor_sid"]) == ("Bob", BOB)
    assert one("budget.xlsx")["actor_sid"] == ALICE
    assert one("msedge")["actor_type"] == ""             # Users\Public is nobody's
    # RecentDocs carries no user_name in this (old-schema) fixture: with two
    # profiles it can no longer be pinned on either.
    recent = [e for e in events if "recently opened" in e["description"]]
    assert recent and all(e["actor_type"] == "" for e in recent)


def test_find_4688_bisect_matches_a_linear_scan(artifacts_dir):
    ctx = ExtractorContext(DbPool(str(artifacts_dir)), None, None)
    rng = random.Random(7)
    index = sorted((rng.uniform(0, 5000), rng.choice(["a.exe", "b.exe", "c"]), i)
                   for i in range(4000))
    ctx._index_4688 = index
    from uba.utils.timeparse import epoch_seconds

    base = epoch_seconds("1970-01-01 00:00:00") or 0
    for _ in range(300):
        center = rng.uniform(-10, 5010)
        ts = "1970-01-01 {:02d}:{:02d}:{:02d}".format(
            int(center) // 3600, (int(center) % 3600) // 60, int(center) % 60) \
            if 0 <= center < 86400 else None
        if ts is None:
            continue
        c = epoch_seconds(ts) - base
        for name in ("a.exe", "b", "c"):
            want = [r for e, b, r in index
                    if c - 5 <= e <= c + 5 and b in (name, name + ".exe")]
            assert ctx.find_4688(name, ts, 5) == want


# --------------------------------------------------------------------------- store
def test_rule_count_is_the_rules_file(artifacts_dir):
    with open(DEFAULT_RULES_PATH, encoding="utf-8") as fh:
        raw = json.load(fh)
    loaded = load_rules()
    assert len(loaded["rules"]) == len(raw["rules"])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    assert len(eng.coverage_report["rules"]) == len(raw["rules"])


def test_the_store_is_reused_while_fresh_and_rebuilt_when_not(artifacts_dir):
    first = BehaviorEngine(str(artifacts_dir))
    first.run_or_load()
    path = persisted_store.store_path(str(artifacts_dir))
    assert path == os.path.join(os.path.dirname(str(artifacts_dir)), "UBA", "uba_events.db")
    assert os.path.isfile(path) and not first.loaded_from_store
    before = {r["event_id"]: dict(r) for r in first.store.conn.execute("SELECT * FROM events")}
    first.close()

    second = BehaviorEngine(str(artifacts_dir))
    second.run_or_load()
    assert second.loaded_from_store, "a fresh store was analysed again"
    after = {r["event_id"]: dict(r) for r in second.store.conn.execute("SELECT * FROM events")}
    assert after == before
    assert second.coverage_report["counts"] == first.coverage_report["counts"]
    assert second.sessions_report()["sessions"]        # stored sessions answer
    assert second.users() and second.rules_catalog()
    assert second.is_current()
    meta = persisted_store.PersistedStore(str(artifacts_dir)).read_meta()
    assert meta["stamp"]["rules_count"] == len(load_rules()["rules"])
    assert meta["stamp"]["user_rules_hash"] == ""
    assert meta["built_at_utc"]
    second.close()

    # A re-parse moves an evidence database's mtime: the store is stale.
    db = Path(artifacts_dir) / "registry_data.db"
    st = db.stat()
    os.utime(db, (st.st_atime, st.st_mtime + 30))
    third = BehaviorEngine(str(artifacts_dir))
    assert not third.is_current()
    third.run_or_load()
    assert not third.loaded_from_store
    third.close()


def test_the_store_keeps_its_query_api(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run_or_load()
    again = BehaviorEngine(str(artifacts_dir))
    again.run_or_load()
    page = again.store.query_events(filters={"actor_sids": [ALICE]}, page_size=500)
    assert page["total"] > 0
    assert all(e["actor_sid"] == ALICE for e in page["events"])
    assert again.store.summary({})["by_rule"]
    eng.close(); again.close()


# --------------------------------------------------------------------------- switches
def test_a_switched_off_rule_is_off_not_empty(artifacts_dir, _isolated_settings):
    assert rule_switches.set_rule_enabled("usb_connected", False)
    assert rule_switches.disabled_rule_ids() == {"usb_connected"}
    # Saved in the one global settings file, beside the keys already there.
    path = os.path.join(str(_isolated_settings), "CrowEye", "config", "global_config.json")
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["uba_disabled_rules"] == ["usb_connected"]

    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    assert not [e for e in _events(eng) if e["rule_id"] == "usb_connected"]
    entry = next(r for r in eng.coverage_report["rules"] if r["rule_id"] == "usb_connected")
    assert entry["status"] == "off"
    assert "Turned off in Settings" in entry["note"]
    assert eng.coverage_report["counts"]["off"] == 1
    catalog = next(r for r in eng.rules_catalog() if r["rule_id"] == "usb_connected")
    assert catalog["enabled"] is False and catalog["status"] == "off"

    assert rule_switches.set_rule_enabled("usb_connected", True)
    eng2 = BehaviorEngine(str(artifacts_dir))
    eng2.run()
    assert [e for e in _events(eng2) if e["rule_id"] == "usb_connected"]


def test_one_rule_off_leaves_its_extractor_running_for_the_others(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir), disabled_rules=["scheduled_task_run"])
    eng.run()
    rules = {e["rule_id"] for e in _events(eng)}
    assert "scheduled_task_registered" in rules
    assert "scheduled_task_run" not in rules


def test_switching_a_rule_makes_the_store_stale(artifacts_dir):
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run_or_load()
    assert eng.is_current()
    rule_switches.set_rule_enabled("usb_connected", False)
    assert not eng.is_current()
    off = BehaviorEngine(str(artifacts_dir))
    off.run_or_load()
    assert not off.loaded_from_store
    assert not off.store.query_events(filters={"rules": ["usb_connected"]})["total"]
    rule_switches.set_rule_enabled("usb_connected", True)
    back = BehaviorEngine(str(artifacts_dir))
    back.run_or_load()
    assert back.store.query_events(filters={"rules": ["usb_connected"]})["total"]
    for e in (eng, off, back):
        e.close()


def test_a_settings_save_keeps_the_switches(artifacts_dir, _isolated_settings):
    from config.case_history_manager import CaseHistoryManager
    manager = CaseHistoryManager()          # loaded before the switch is written
    rule_switches.set_rule_enabled("log_cleared", False)
    manager.update_global_config(max_history_size=150)
    assert rule_switches.disabled_rule_ids() == {"log_cleared"}


def test_switch_rows_cover_every_rule_grouped_by_class():
    rule_switches.set_rule_enabled("usb_connected", False)
    rows = rule_switches.switch_rows()
    assert len(rows) == len(load_rules()["rules"])
    order = [r["behavior_class"] for r in rows]
    assert order == sorted(order, key=rule_switches.CLASS_ORDER.index)
    usb = next(r for r in rows if r["rule_id"] == "usb_connected")
    assert usb["enabled"] is False and usb["class_label"] == "User"
    assert all(r["user_rule"] is False for r in rows)
    assert rule_switches.set_disabled_rules([])
    assert all(r["enabled"] for r in rule_switches.switch_rows())


def test_a_system_log_clear_names_its_subject_when_the_event_carries_one(artifacts_dir):
    """Event 104's payload is SubjectUserName, SubjectDomainName, Channel,
    BackupPath (the Microsoft-Windows-Eventlog manifest). The legacy API the
    live parser reads returns it as insertion strings, stored comma-joined in
    Keywords. A clear Windows setup made carries none: it stays unattributed."""
    _exec(str(Path(artifacts_dir) / "Log_Claw.db"),
          "INSERT INTO SystemLogs (EventID, Source, EventType, Category, "
          "EventTimestampUTC, ComputerName, User, Keywords, EventDescription) "
          "VALUES (104, 'Microsoft-Windows-Eventlog', '', '', ?, 'PC', 'N/A', ?, '')",
          [("2026-06-12 23:10:00", "Alice,PC,Application,"),
           ("2026-06-12 23:20:00", "N/A")])
    eng = BehaviorEngine(str(artifacts_dir))
    eng.run()
    by_time = {e["ts_start"]: e for e in _events(eng) if e["rule_id"] == "log_cleared"}
    named = by_time["2026-06-12 23:10:00"]
    assert (named["actor_type"], named["actor_name"], named["actor_sid"]) == ("User", "Alice", ALICE)
    assert "'Application'" in named["description"]
    setup = by_time["2026-06-12 23:20:00"]
    assert (setup["actor_name"], setup["actor_sid"]) == ("", "")
    assert setup["description"] == "A Windows event log was erased"
