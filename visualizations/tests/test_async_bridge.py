"""AsyncBridge - chart slots answered off the GUI thread.

Every dashboard's QWebChannel slot used to run its SQL on the GUI thread, so a
long query froze the whole window and the page's loading overlay with it
(a timeline day click: 70 s). The contract the pages rely on:

- callAsync(method, id, argsJson) answers on asyncResult(id, json), and the GUI
  thread keeps running its event loop while the slot works;
- only data getters (get*) run there - anything that creates widgets stays on
  the GUI thread, and a refused or failing call answers {"__asyncError": ...}
  (the page turns it into null) instead of never answering;
- cached_slot keeps an answer per filter until a database changes, and works
  for the no-argument bounds slots too.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSlot
import PyQt5.QtWebEngineWidgets  # noqa: F401  (before the QApplication: the timeline imports it)

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from visualizations.async_bridge import AsyncBridge, cached_slot  # noqa: E402

DB = os.path.join(tempfile.mkdtemp(prefix="asyncbridge_"), "fake.db")
with open(DB, "w") as fh:
    fh.write("x")


class FakeBridge(AsyncBridge):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.calls = 0
        self.threads = []

    @pyqtSlot(str, result=str)
    def getSlow(self, args_json):
        self.threads.append(QtCore.QThread.currentThread())
        time.sleep(0.6)
        return json.dumps({"echo": json.loads(args_json)})

    @pyqtSlot(str, result=str)
    def getBroken(self, args_json):
        raise ValueError("bad filter")

    @pyqtSlot(str, result=str)
    def openSomething(self, args_json):
        return json.dumps({"opened": True})

    @pyqtSlot(result=str)
    @cached_slot("getBounds", lambda b: [DB])
    def getBounds(self):
        self.calls += 1
        return json.dumps({"n": self.calls})

    @pyqtSlot(str, result=str)
    @cached_slot("getCounted", lambda b: [DB])
    def getCounted(self, args_json):
        self.calls += 1
        return json.dumps({"n": self.calls, "args": json.loads(args_json or "{}")})


def ask(bridge, method, args, timeout=10.0):
    """callAsync and pump the event loop until the answer; also returns the
    longest gap between 10 ms heartbeats while waiting."""
    got = {}
    rid = "%s#%d" % (method, id(got))
    bridge.asyncResult.connect(lambda i, p: got.setdefault(i, p))
    beats = {"last": time.monotonic(), "gap": 0.0}

    def beat():
        now = time.monotonic()
        beats["gap"] = max(beats["gap"], now - beats["last"])
        beats["last"] = now
    timer = QtCore.QTimer()
    timer.timeout.connect(beat)
    timer.start(10)
    bridge.callAsync(method, rid, json.dumps(args))
    end = time.monotonic() + timeout
    while rid not in got and time.monotonic() < end:
        APP.processEvents(QtCore.QEventLoop.AllEvents, 20)
    timer.stop()
    return (json.loads(got[rid]) if rid in got else None), beats["gap"]


class AsyncBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()

    def tearDown(self):
        self.bridge.wait_for_calls()

    def test_answer_comes_back_on_the_signal_while_the_gui_keeps_running(self):
        out, gap = ask(self.bridge, "getSlow", [json.dumps({"day": "2026-10-08"})])
        self.assertEqual(out, {"echo": {"day": "2026-10-08"}})
        self.assertIsNot(self.bridge.threads[0], APP.thread(), "slot ran on the GUI thread")
        # The slot slept 0.6 s; the heartbeat never stopped for that long.
        self.assertLess(gap, 0.3)

    def test_a_raising_slot_answers_an_error_marker(self):
        out, _ = ask(self.bridge, "getBroken", ["{}"])
        self.assertIn("__asyncError", out)
        self.assertIn("bad filter", out["__asyncError"])

    def test_only_getters_run_off_the_gui_thread(self):
        for method in ("openSomething", "_deliver", "callAsync", "noSuchSlot", ""):
            out, _ = ask(self.bridge, method, ["{}"])
            self.assertIn("__asyncError", out, method)
        self.assertEqual(self.bridge.threads, [])

    def test_cached_slot_without_arguments(self):
        first = json.loads(self.bridge.getBounds())
        again = json.loads(self.bridge.getBounds())
        self.assertEqual(first, again)
        self.assertEqual(self.bridge.calls, 1)
        out, _ = ask(self.bridge, "getBounds", [])
        self.assertEqual(out, first)

    def test_cached_slot_keys_on_filters_and_database_mtime(self):
        a = json.loads(self.bridge.getCounted(json.dumps({"start": "1", "end": "2"})))
        # Same filters in another key order: same answer, not recomputed.
        b = json.loads(self.bridge.getCounted(json.dumps({"end": "2", "start": "1"})))
        self.assertEqual(a, b)
        c = json.loads(self.bridge.getCounted(json.dumps({"start": "1", "end": "3"})))
        self.assertNotEqual(a["n"], c["n"])
        # A re-parse touches the database: the answer is recomputed.
        later = os.path.getmtime(DB) + 5
        os.utime(DB, (later, later))
        d = json.loads(self.bridge.getCounted(json.dumps({"start": "1", "end": "2"})))
        self.assertNotEqual(a["n"], d["n"])

    def test_every_dashboard_bridge_is_an_async_bridge(self):
        from visualizations.browser_bridge import BrowserBridge
        from visualizations.lnkjl_bridge import LnkJlBridge
        from visualizations.mftusn_bridge import MftUsnBridge
        from visualizations.prefetch_bridge import PrefetchBridge
        from visualizations.shellitems_bridge import ShellItemsBridge
        from visualizations.viz_bridge import VizBridge
        from timeline.timeline_bridge import TimelineBridge
        for cls in (BrowserBridge, LnkJlBridge, MftUsnBridge, PrefetchBridge,
                    ShellItemsBridge, VizBridge, TimelineBridge):
            self.assertTrue(issubclass(cls, AsyncBridge), cls.__name__)

    def test_every_page_routes_getters_through_call_async(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pages = [os.path.join(root, "visualizations", d, "src", "bridge.js")
                 for d in os.listdir(os.path.join(root, "visualizations")) if d.startswith("react-")]
        pages.append(os.path.join(root, "timeline", "react-timeline", "src", "hooks", "useBridge.js"))
        self.assertEqual(len(pages), 7)
        for page in pages:
            text = open(page, encoding="utf-8").read()
            self.assertIn("bridge.callAsync(method, id, JSON.stringify(args))", text, page)
            self.assertIn("__asyncError", text, page)
            self.assertIn("/^get/.test(method)", text, page)


if __name__ == "__main__":
    unittest.main()
