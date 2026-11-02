"""The User Behavior window's initial filter ("Open in User Behavior").

UBABridge carries it (getInitialFilter, read by React on load;
initialFilterChanged, re-applied to a window already open), and
uba_dialog.open_user_behavior is the busy-guarded door that re-uses an open
window for the same case instead of opening a second one.
"""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")

# QtWebEngineWidgets must be imported before any QApplication exists, so the
# dialog module is imported here, at collection, or the opener tests skip.
try:
    from uba import uba_dialog
except ImportError as e:                       # pragma: no cover - import order
    uba_dialog = None
    _DIALOG_ERROR = str(e)
else:
    _DIALOG_ERROR = ""

from uba.uba_bridge import UBABridge, normalise_initial_filter  # noqa: E402

SID = "S-1-5-21-1837504242-3964489493-3378464631-1001"
HIT_FILTER = {"actor_sids": [SID], "actors": [], "start": "2026-02-15 17:33:17",
              "end": "2026-02-15 17:53:24",
              "label": "Behaviour Results: Ghass, Mass File Deletion Burst (Behaviour)"}


@pytest.fixture(scope="module")
def qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_normalise_keeps_what_react_filters_on():
    assert normalise_initial_filter(HIT_FILTER) == HIT_FILTER
    # A 'T', fractional seconds or 'Z' come to the store's shape; minutes only gain :00.
    f = normalise_initial_filter({"start": "2026-02-15T17:33:17.250Z", "end": "2026-02-15 17:53"})
    assert (f["start"], f["end"]) == ("2026-02-15 17:33:17", "2026-02-15 17:53:00")
    # Reversed times are put in order; nonsense is dropped, not passed on.
    f = normalise_initial_filter({"start": "2026-02-16 00:00:00", "end": "2026-02-15 00:00:00"})
    assert f["start"] < f["end"]
    assert normalise_initial_filter({"start": "yesterday"}) is None
    # An empty SID is not a person; '' as a name is the store's "unattributed".
    f = normalise_initial_filter({"actor_sids": ["", SID], "actors": [""]})
    assert f["actor_sids"] == [SID] and f["actors"] == [""]
    assert normalise_initial_filter({}) is None
    assert normalise_initial_filter(None) is None
    assert normalise_initial_filter("not a dict") is None


def test_the_slot_round_trips(qapp, tmp_path):
    bridge = UBABridge(str(tmp_path), initial_filter=HIT_FILTER)
    got = json.loads(bridge.getInitialFilter())
    assert got == {"filter": HIT_FILTER, "seq": 1}

    seen = []
    bridge.initialFilterChanged.connect(seen.append)
    second = {"actor_sids": [SID], "label": "Behaviour Results: Ghass"}
    answer = bridge.set_initial_filter(second)
    assert answer["seq"] == 2
    assert len(seen) == 1 and json.loads(seen[0]) == answer
    assert json.loads(bridge.getInitialFilter())["filter"]["actor_sids"] == [SID]
    assert json.loads(bridge.getInitialFilter())["filter"]["start"] == ""
    # The same request again is a new seq, so React applies it again.
    assert bridge.set_initial_filter(second)["seq"] == 3
    # None clears it (a whole-case open of a window that was filtered).
    assert bridge.set_initial_filter(None)["filter"] is None


def test_no_filter_by_default(qapp, tmp_path):
    bridge = UBABridge(str(tmp_path))
    assert json.loads(bridge.getInitialFilter()) == {"filter": None, "seq": 0}


@pytest.mark.skipif(uba_dialog is None, reason=_DIALOG_ERROR or "uba_dialog unavailable")
def test_an_open_window_is_refiltered_not_duplicated(qapp, tmp_path, monkeypatch):
    class Open:                                 # stands in for a UBADialog on screen
        def __init__(self, folder):
            self.folder, self.applied = folder, []

        def isVisible(self):
            return True

        def shows_case(self, d):
            return uba_dialog._same_folder(self.folder, d)

        def apply_initial_filter(self, f):
            self.applied.append(f)

    window = Open(str(tmp_path))
    uba_dialog._OPEN_WINDOWS.add(window)
    monkeypatch.setattr(uba_dialog, "UBADialog",
                        lambda *a, **k: pytest.fail("a second window was opened"))
    try:
        got = uba_dialog.open_user_behavior(None, str(tmp_path) + os.sep, HIT_FILTER)
        assert got is window and window.applied == [HIT_FILTER]
    finally:
        uba_dialog._OPEN_WINDOWS.discard(window)


@pytest.mark.skipif(uba_dialog is None, reason=_DIALOG_ERROR or "uba_dialog unavailable")
def test_nothing_opens_mid_parse(qapp, tmp_path, monkeypatch):
    from ui import busy_guard
    told = []
    monkeypatch.setattr(uba_dialog.QMessageBox, "information",
                        staticmethod(lambda *a, **k: told.append(a)))
    monkeypatch.setattr(uba_dialog, "UBADialog",
                        lambda *a, **k: pytest.fail("opened while Crow-Eye was busy"))
    token = busy_guard.begin("Parsing live artifacts")
    try:
        assert uba_dialog.open_user_behavior(None, str(tmp_path), HIT_FILTER) is None
    finally:
        busy_guard.end(token)
    assert told and "still working" in told[0][2]


@pytest.mark.skipif(uba_dialog is None, reason=_DIALOG_ERROR or "uba_dialog unavailable")
def test_the_main_windows_gate_is_used_when_reachable(qapp, tmp_path, monkeypatch):
    """Through the main UI's _feature_gate (its busy dialog with "Open when
    ready"), found from a parent's ``ui``."""
    asked = []

    class Ui:
        def _feature_gate(self, feature, needs=None, kind="view", retry=None):
            asked.append((feature, needs, kind, callable(retry)))
            return False

    class Parent:
        ui = Ui()

        def parent(self):
            return None

    monkeypatch.setattr(uba_dialog, "UBADialog", lambda *a, **k: pytest.fail("gate ignored"))
    assert uba_dialog.open_user_behavior(Parent(), str(tmp_path), HIT_FILTER) is None
    assert asked == [("User Behavior Analytics", None, "view", True)]
