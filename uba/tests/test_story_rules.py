"""The evidence the Activity Story did not tell before 2026-11-03: printers,
outbound Remote Desktop, cloud sync apps, files written to USB, and files
gathered into one folder. Each rule fires on its own fixture rows (a rule test
that finds nothing would pass silently)."""

import json
import os

import pytest

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.event_store import UBAEventStore
from uba.engine.models import BehaviorEvent, EvidenceRef
from uba.engine.extractors import story_rules
from uba.tests.conftest import _mk

RULES = json.load(open(os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    "config", "behavior_rules.json"), encoding="utf-8"))
BY_ID = {r["id"]: r for r in RULES["rules"]}


@pytest.fixture
def story_case(tmp_path):
    d = tmp_path / "Target_Artifacts"
    d.mkdir()
    _mk(str(d / "registry_data.db"), """
        CREATE TABLE UserProfiles (sid TEXT, profile_path TEXT, user_name TEXT);
        CREATE TABLE printer_connections (user_name TEXT, connection TEXT, server TEXT,
            printer TEXT, key_path TEXT, last_written TEXT, time_basis TEXT, parsed_at TEXT);
        CREATE TABLE RDPClientMRU (user_name TEXT, entry_type TEXT, server TEXT,
            username_hint TEXT, key_path TEXT, last_written TEXT, time_basis TEXT, parsed_at TEXT);
        CREATE TABLE InstalledSoftware (display_name TEXT, display_version TEXT,
            publisher TEXT, install_date TEXT, install_location TEXT,
            uninstall_string TEXT, timestamp TEXT);
    """, {
        "printer_connections": [
            {"user_name": "Alice", "connection": "\\\\print01\\HR-Color", "server": "print01",
             "printer": "HR-Color", "key_path": "", "last_written": "2026-06-12 09:30:00",
             "time_basis": "key upper bound", "parsed_at": ""}],
        "RDPClientMRU": [
            {"user_name": "Alice", "entry_type": "Servers", "server": "fin-db02",
             "username_hint": "CORP\\alice", "key_path": "",
             "last_written": "2026-06-12 10:00:00", "time_basis": "key upper bound",
             "parsed_at": ""},
            {"user_name": "Alice", "entry_type": "Servers", "server": "",
             "username_hint": "", "key_path": "", "last_written": "", "time_basis": "",
             "parsed_at": ""}],
        "InstalledSoftware": [
            {"display_name": "Dropbox", "display_version": "190.4.6383", "publisher": "Dropbox, Inc.",
             "install_date": "20260611", "install_location": "", "uninstall_string": "",
             "timestamp": ""},
            {"display_name": "7-Zip", "display_version": "23.01", "publisher": "",
             "install_date": "20260601", "install_location": "", "uninstall_string": "",
             "timestamp": ""}],
    })
    return str(d)


def _events(artifacts_dir, rule_id):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return [dict(r) for r in eng.store.conn.execute(
        "SELECT * FROM events WHERE rule_id = ?", (rule_id,))]


def test_a_printer_the_user_added(story_case):
    ev = _events(story_case, "printer_added")
    assert len(ev) == 1
    assert "added the printer 'HR-Color' on the print server print01" in ev[0]["description"]
    assert "at or before 2026-06-12 09:30:00" in ev[0]["description"]
    assert json.loads(ev[0]["evidence_json"])[0]["table"] == "printer_connections"


def test_a_remote_desktop_host_the_user_connected_to(story_case):
    ev = _events(story_case, "rdp_outbound")
    assert len(ev) == 1                                    # the row with no host is skipped
    d = ev[0]["description"]
    assert "connected to the computer fin-db02 over Remote Desktop" in d
    assert "signing in as CORP\\alice" in d
    assert ev[0]["severity"] == "notable"


def test_a_cloud_sync_app_and_nothing_else(story_case):
    ev = _events(story_case, "cloud_sync_client")
    assert [e["app_name"] for e in ev] == ["Dropbox"]
    assert "earliest install date recorded is 2026-06-11" in ev[0]["description"]
    assert "version 190.4.6383" in ev[0]["description"]


class _Pool:
    def __init__(self, usb_rows):
        self.usb_rows = usb_rows

    def get(self, db):
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE USBStorageVolumes (volume_guid TEXT, drive_letter TEXT)")
        c.executemany("INSERT INTO USBStorageVolumes VALUES (?, ?)", self.usb_rows)
        return c

    def has_table(self, db, table):
        return True


class _Ctx:
    def __init__(self, store, usb_rows=()):
        self.store = store
        self.pool = _Pool(list(usb_rows))

    def session_context(self, ts):
        return ""


def _ev(rule_id, ts, folder=None, files=1, path=None, file=None, types=None, rowid=1):
    details = {}
    if folder:
        details.update(folder=folder, files=files, sample_files=["a.docx"],
                       file_types=types or {".docx": files})
    if path:
        details.update(path=path, file=file)
    return BehaviorEvent(
        rule_id=rule_id, behavior_class="user", activity="x", ts_start=ts, ts_end=ts,
        actor_type="User", actor_name="Alice", actor_basis="profile owner",
        actor_sid="S-1-5-21-1-1001", description="d", severity="routine",
        confidence="artifact-only", aggregate_count=files, details=details,
        evidence=[EvidenceRef(db="usn", table="journal_events", rowids=[rowid], count=files)])


def test_files_written_to_a_usb_drive_and_picked_on_it():
    store = UBAEventStore()
    store.add_events([
        _ev("file_created", "2026-06-12 11:00:00", folder="F:\\Exports", files=12, rowid=1),
        _ev("file_dialog_history", "2026-06-12 11:05:00", path="F:\\Exports", file="payroll.xlsx", rowid=2),
        _ev("file_created", "2026-06-12 11:06:00", folder="C:\\Users\\Alice\\Documents", files=3, rowid=3),
    ])
    ev = story_rules.usb_file_copy(_Ctx(store, [("{aaaa}", "F:")]), [BY_ID["usb_file_copy"]])
    assert len(ev) == 1
    e = ev[0]
    assert e.description == ("Alice used the USB drive F: on 2026-06-12: 12 files written to the "
                             "USB drive F:; 1 picked on it in a Save/Open dialog (payroll.xlsx)")
    assert e.actor_sid == "S-1-5-21-1-1001" and e.aggregate_count == 13
    assert sorted(r for ref in e.evidence for r in ref.rowids) == [1, 2]
    assert "may have been opened rather than saved" in e.caveat


def test_no_usb_letter_no_usb_copy():
    store = UBAEventStore()
    store.add_events([_ev("file_created", "2026-06-12 11:00:00", folder="F:\\Exports", files=12)])
    assert story_rules.usb_file_copy(_Ctx(store, []), [BY_ID["usb_file_copy"]]) == []


def test_files_gathered_into_one_folder_with_an_archive():
    store = UBAEventStore()
    store.add_events([
        _ev("file_created", "2026-06-12 09:00:00", folder="C:\\Users\\Alice\\Desktop\\out",
            files=25, types={".docx": 24, ".zip": 1}, rowid=10),
        _ev("file_created", "2026-06-12 09:00:00", folder="C:\\Users\\Alice\\Documents",
            files=30, rowid=11),                                   # many files, no archive
    ])
    ev = story_rules.files_collected(_Ctx(store), [BY_ID["files_collected"]])
    assert [e.details["folder"] for e in ev] == ["C:\\Users\\Alice\\Desktop\\out"]
    assert ev[0].description == ("Alice gathered 25 files in C:\\Users\\Alice\\Desktop\\out on "
                                 "2026-06-12, and 1 archive file was written there")


def test_files_copied_into_one_folder():
    store = UBAEventStore()
    store.add_events([_ev("file_copy_inferred", "2026-06-12 09:00:00",
                          folder="C:\\Users\\Alice\\Downloads\\x", files=14, rowid=5)])
    ev = story_rules.files_collected(_Ctx(store), [BY_ID["files_collected"]])
    assert len(ev) == 1 and "(14 of them copied there)" in ev[0].description


def test_the_rules_over_found_activity_run_last():
    assert BY_ID["usb_file_copy"].get("after_extractors") is True
    assert BY_ID["files_collected"].get("after_extractors") is True
