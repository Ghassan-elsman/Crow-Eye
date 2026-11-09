"""A stored evidence query runs off Crow-Eye's GUI thread.

The Narrative Map's evidence popup re-runs the Eye's stored SQL through
EYEBridge.query_database, a synchronous slot: one LIKE over the 3.9 M-row
MFT/USN table held the GUI thread - all of Crow-Eye - for 10 s. The bridge
now has callAsync(method, id, argsJson) for the slots in _ASYNC_SLOTS, the
dashboards' pattern (visualizations/async_bridge.py), and the page uses it:

  returns at once      while the query is still running
  runs on a worker     not on the thread that called it
  answers by id        asyncResult(id, json) carries the slot's own answer
  keeps the slot's     a failed query answers {"success": false, ...} as the
  answers              plain call does
  refuses the rest     anything outside _ASYNC_SLOTS answers __asyncError and
                       never runs (report and widget slots stay on the GUI thread)
"""
import json
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets  # noqa: E402

from eye.bridge.eye_bridge import EYEBridge  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _SlowSource:
    def __init__(self, seconds=0.6):
        self.seconds = seconds
        self.threads = []

    def execute_query(self, database, sql):
        self.threads.append(threading.get_ident())
        time.sleep(self.seconds)
        if "missing" in sql:
            return {"success": False, "error": "no such table: missing"}
        return {"success": True, "data": [{"name": "a.exe", "n": 1}], "row_count": 1}


def _listen(bridge):
    got = {}
    bridge.asyncResult.connect(lambda rid, payload: got.__setitem__(rid, json.loads(payload)))
    return got


def _collect(app, got, ids, timeout=10):
    end = time.time() + timeout
    while time.time() < end and not set(ids) <= set(got):
        app.processEvents()
        time.sleep(0.01)
    return got


def test_a_query_runs_off_the_gui_thread_and_answers_by_id(app):
    src = _SlowSource()
    bridge = EYEBridge(database_service=src)
    got = _listen(bridge)
    t = time.time()
    bridge.callAsync("query_database", "p-1", json.dumps(["mft.db", "SELECT 1"]))
    bridge.callAsync("query_database", "p-2", json.dumps(["mft.db", "SELECT * FROM missing"]))
    assert time.time() - t < 0.2                     # the caller is not held
    _collect(app, got, ["p-1", "p-2"])
    assert got["p-1"]["success"] is True
    assert got["p-1"]["data"]["rows"] == [{"name": "a.exe", "n": 1}]
    assert got["p-2"]["success"] is False and "missing" in got["p-2"]["error"]
    assert threading.get_ident() not in src.threads
    # the same answer the plain slot gives
    src.seconds = 0
    assert json.loads(bridge.query_database("mft.db", "SELECT 1")) == got["p-1"]
    assert bridge.wait_for_async_calls(5000)


def test_the_windows_log_readers_run_off_the_gui_thread_too(app, tmp_path):
    # Read whole .jsonl files from EYE_Logs when the window opens; a long
    # investigation's logs grow past what the GUI thread should parse.
    import types
    logs = tmp_path / "EYE_Logs"
    logs.mkdir()
    (logs / "eye_step_log.jsonl").write_text(
        "\n".join(json.dumps({"type": "tool_call", "label": "query_database", "status": "done"})
                  for _ in range(5000)), encoding="utf-8")
    bridge = EYEBridge(context_manager=types.SimpleNamespace(case_directory=str(tmp_path)))
    got = _listen(bridge)
    plain = json.loads(bridge.get_step_history())
    t = time.time()
    bridge.callAsync("get_step_history", "s-1", "[]")
    assert time.time() - t < 0.2
    _collect(app, got, ["s-1"])
    assert got["s-1"] == plain and got["s-1"]["data"]["total_runs"] == 5000
    for name in ("get_dialogue_history", "get_gep_turns", "get_reasoning_turns"):
        assert name in EYEBridge._ASYNC_SLOTS
    assert bridge.wait_for_async_calls(5000)


def test_other_slots_are_refused_and_never_run(app):
    bridge = EYEBridge(database_service=_SlowSource(0))
    ran = []
    bridge.export_report = lambda *a: ran.append(a) or "{}"
    got = _listen(bridge)
    for i, name in enumerate(("export_report", "report_delete_section", "process_query", "nope")):
        bridge.callAsync(name, "r-%d" % i, json.dumps(["x"]))
    _collect(app, got, ["r-0", "r-1", "r-2", "r-3"], timeout=3)
    assert all("not callable off the GUI thread" in got["r-%d" % i]["__asyncError"] for i in range(4))
    assert ran == []
