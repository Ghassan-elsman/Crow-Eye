"""The two switch screens - Settings -> User Behavior and the User Behavior
window's Rules view - edit one saved setting, and neither undoes the other."""

import json
import os

import pytest

from uba.engine import rule_switches
from uba.engine.rule_loader import load_rules

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_settings_page_saves_only_what_it_flipped(qapp):
    from ui.uba_rules_settings import UserBehaviorSettingsPage
    rule_switches.set_disabled_rules(["usb_connected"])
    page = UserBehaviorSettingsPage()
    assert len(page._switches) == len(load_rules()["rules"])
    assert page._switches["usb_connected"].isChecked() is False
    assert page.count_label.text() == "1 of %d rules off" % len(page._switches)

    # Meanwhile the User Behavior window turns another rule off...
    rule_switches.set_rule_enabled("log_cleared", False)
    # ...and here one is switched off, one back on.
    page._switches["failed_logon"].setChecked(False)
    page._switches["usb_connected"].setChecked(True)
    assert page.changes() == {"failed_logon": False, "usb_connected": True}
    assert page.apply()
    # The window's change survives the Settings save.
    assert rule_switches.disabled_rule_ids() == {"log_cleared", "failed_logon"}


def test_settings_page_search_and_all_on(qapp):
    from ui.uba_rules_settings import UserBehaviorSettingsPage
    rule_switches.set_disabled_rules(["usb_connected", "log_cleared"])
    page = UserBehaviorSettingsPage()
    page.show()
    page.search.setText("usb")
    visible = [rid for rid, (row, _t, _h) in page._rows.items() if row.isVisible()]
    assert "usb_connected" in visible and "log_cleared" not in visible
    page._turn_all_on()
    assert page.apply()
    assert rule_switches.disabled_rule_ids() == set()
    page.close()


def test_rules_view_slots_write_the_same_setting():
    from uba.uba_bridge import UBABridge
    bridge = UBABridge("unused")
    before = json.loads(bridge.getRuleSwitches())
    assert len(before["rules"]) == len(load_rules()["rules"])
    assert before["off_count"] == 0 and before["needs_rerun"] is False

    out = json.loads(bridge.setRuleEnabled(json.dumps({"rule_id": "usb_connected",
                                                       "enabled": False})))
    assert out["saved"] is True and out["off_count"] == 1
    row = next(r for r in out["rules"] if r["rule_id"] == "usb_connected")
    assert row["enabled"] is False
    assert rule_switches.disabled_rule_ids() == {"usb_connected"}

    out = json.loads(bridge.setRuleEnabled(json.dumps({"all_on": True})))
    assert out["off_count"] == 0 and rule_switches.disabled_rule_ids() == set()
    assert "error" in json.loads(bridge.setRuleEnabled("{}"))


def test_rules_view_says_when_the_analysis_is_out_of_date(artifacts_dir):
    from uba.engine.behavior_engine import BehaviorEngine
    from uba.uba_bridge import UBABridge
    bridge = UBABridge(str(artifacts_dir))
    bridge.engine = BehaviorEngine(str(artifacts_dir))
    bridge.engine.run()
    bridge._analysis_done = True
    assert json.loads(bridge.getRuleSwitches())["needs_rerun"] is False
    rule_switches.set_rule_enabled("usb_connected", False)
    state = json.loads(bridge.getRuleSwitches())
    assert state["needs_rerun"] is True
    usb = next(r for r in state["rules"] if r["rule_id"] == "usb_connected")
    assert usb["status"] == "active" and usb["event_count"] > 0   # what is on screen
    bridge.engine.close()
