"""SRUM's Insights card, and the scoping trap underneath it.

react-viz was the one dashboard with no insights at all: its overview was four
charts and a provider list, so the question "what here is worth looking at?"
had no answer on the page.

**The trap.** An insight counts across the whole filter; the app modal was
called with `start = end = selectedDay`. Measured on a real case, 5 of the
first 6 insight subjects opened a modal with **zero** hours in it - an empty
profile under a tile that had just counted records. So `appRange` carries the
range the tile used, and only falls back to the selected cell.

The thresholds live on the bridge rather than in a literal here: a ratio with
no floor flags a process that sent one packet.
"""
import os
import re
import unittest

from visualizations import viz_bridge
from visualizations.viz_bridge import VizBridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _jsx(name):
    with open(os.path.join(ROOT, "react-viz", "src", name), encoding="utf-8") as fh:
        return fh.read()


def _insights(per_app, app_days=None, per_user=None):
    """Drive the real rule set without needing a case on disk."""
    app_days = app_days if app_days is not None else {a: {"2026-01-01"} for a in per_app}
    return VizBridge._srum_insights(
        VizBridge.__new__(VizBridge), per_app, app_days,
        per_user if per_user is not None else {"S-1-5-21-1": {}})


def _app(name, sent=0, received=0):
    return {"app": name, "sent": sent, "received": received}


MIB = 1 << 20


class SentFarMoreThanItReceived(unittest.TestCase):

    def test_an_upload_shape_is_flagged_with_its_figures(self):
        out = _insights({"a": _app("a.exe", sent=50 * MIB, received=MIB)})
        self.assertEqual(out["netSkew"]["count"], 1)
        s = out["netSkew"]["subjects"][0]
        self.assertEqual(s["label"], "a.exe")
        self.assertEqual(s["open"], "a.exe")           # what AppDetailPanel takes
        self.assertIn("50.0 MB", s["note"])
        self.assertIn("1.0 MB", s["note"])

    def test_an_ordinary_download_is_not(self):
        out = _insights({"a": _app("a.exe", sent=MIB, received=50 * MIB)})
        self.assertEqual(out["netSkew"]["count"], 0)

    def test_a_ratio_with_no_volume_behind_it_is_not(self):
        # 400 bytes sent and 1 received is a 400:1 ratio and tells you nothing.
        out = _insights({"a": _app("a.exe", sent=400, received=1)})
        self.assertEqual(out["netSkew"]["count"], 0)

    def test_the_floor_and_the_ratio_are_both_required(self):
        just_under_ratio = _app("a.exe", sent=4 * MIB, received=MIB)
        self.assertEqual(_insights({"a": just_under_ratio})["netSkew"]["count"], 0)
        just_over = _app("b.exe", sent=4 * MIB + 1, received=MIB)
        self.assertEqual(_insights({"b": just_over})["netSkew"]["count"], 1)

    def test_the_biggest_sender_is_listed_first(self):
        out = _insights({
            "a": _app("small.exe", sent=2 * MIB, received=0),
            "b": _app("big.exe", sent=90 * MIB, received=0),
        })
        self.assertEqual([s["label"] for s in out["netSkew"]["subjects"]],
                         ["big.exe", "small.exe"])


class SeenOnOneDayOnly(unittest.TestCase):

    def test_one_day_is_flagged_and_says_which_day(self):
        out = _insights({"a": _app("once.exe")}, app_days={"once.exe": {"2026-03-04"}})
        self.assertEqual(out["oneDay"]["count"], 1)
        self.assertEqual(out["oneDay"]["subjects"][0]["note"], "only on 2026-03-04")
        self.assertEqual(out["oneDay"]["subjects"][0]["open"], "once.exe")

    def test_two_days_is_not(self):
        out = _insights({"a": _app("twice.exe")},
                        app_days={"twice.exe": {"2026-03-04", "2026-03-05"}})
        self.assertEqual(out["oneDay"]["count"], 0)

    def test_a_long_list_says_it_is_truncated(self):
        days = {"app%03d.exe" % i: {"2026-03-04"} for i in range(200)}
        out = _insights({}, app_days=days)
        self.assertEqual(out["oneDay"]["count"], 200)
        self.assertTrue(out["oneDay"]["truncated"])
        self.assertLess(len(out["oneDay"]["subjects"]), 200)


class MeasurementsCarryNoRecords(unittest.TestCase):
    """`plain()` is for a figure with nothing behind it, and must not pretend."""

    def test_the_busiest_app_and_the_user_count_are_measurements(self):
        out = _insights({"a": _app("a.exe")},
                        app_days={"a.exe": {"2026-01-01", "2026-01-02", "2026-01-03"}},
                        per_user={"S-1-5-21-1": {}, "S-1-5-21-2": {}})
        self.assertEqual(out["busiestApp"]["count"], 3)
        self.assertEqual(out["busiestApp"]["subjects"], [])
        self.assertEqual(out["users"]["count"], 2)
        self.assertEqual(out["users"]["subjects"], [])

    def test_an_empty_case_produces_no_insight_at_all(self):
        out = _insights({}, app_days={}, per_user={})
        self.assertEqual({k: v["count"] for k, v in out.items()},
                         {"netSkew": 0, "oneDay": 0, "busiestApp": 0, "users": 0})


class TheByteNoteIsReadable(unittest.TestCase):

    def test_it_scales(self):
        self.assertEqual(viz_bridge._bytes(0), "0 B")
        self.assertEqual(viz_bridge._bytes(900), "900 B")
        self.assertEqual(viz_bridge._bytes(2048), "2.0 KB")
        self.assertEqual(viz_bridge._bytes(1 << 30), "1.0 GB")
        self.assertEqual(viz_bridge._bytes(None), "0 B")


class TheModalOpensWithTheRangeThatCountedIt(unittest.TestCase):
    """The scoping trap, guarded at its two ends."""

    def test_the_app_modal_prefers_the_range_the_tile_used(self):
        app = _jsx("App.jsx")
        self.assertIn("const scope = appRange || { start: selectedDay, end: selectedDay }", app)
        self.assertIn("latest('getSrumAppDetail', JSON.stringify({ app: selectedApp, ...scope", app)
        # An insight sets the filter's own range before opening the app.
        self.assertIn("setAppRange({ start: range.start, end: range.end })", app)

    def test_picking_a_cell_clears_an_insights_range(self):
        app = _jsx("App.jsx")
        self.assertRegex(app, r"onSelect=\{\(d\) => \{[^}]*setAppRange\(null\)")
        self.assertRegex(app, r"onSelectApp=\{\(a\) => \{ setAppRange\(null\)")

    def test_both_modals_are_mounted_in_app_not_in_the_day_section(self):
        # DayActivitySection returns early when nothing is selected, so a modal
        # inside it can be opened from an insight and render nothing at all.
        app = _jsx("App.jsx")
        section = _jsx("DayActivitySection.jsx")
        self.assertIn("<AppDetailPanel", app)
        self.assertIn("<InsightPanel", app)
        self.assertNotIn("<AppDetailPanel", section)
        self.assertNotIn("<InsightPanel", section)

    def test_the_section_still_returns_early(self):
        # If it ever stopped doing so the rule above would be untestable rather
        # than satisfied.
        self.assertRegex(_jsx("DayActivitySection.jsx"), r"if \(!day\) \{\s*\n\s*return")


class TheCardIsOnThePageAndOpens(unittest.TestCase):

    def test_the_overview_renders_every_insight_the_bridge_returns(self):
        ov = _jsx("OverviewPanel.jsx")
        for key in ("netSkew", "oneDay", "busiestApp", "users"):
            self.assertIn("ins.%s" % key, ov, key)
        # The two with records behind them are openable; the measurements are not.
        self.assertEqual(len(re.findall(r"onOpenInsight\('(\w+)'\)", ov)), 2)
        self.assertEqual(set(re.findall(r"onOpenInsight\('(\w+)'\)", ov)),
                         {"netSkew", "oneDay"})

    def test_the_card_states_the_foreground_time_coverage(self):
        # SRUM records focus time for a fraction of what it records at all - 26
        # of 890 applications on the case this was written against - so a
        # missing focus time is a gap in the artifact, not a finding.
        ov = _jsx("OverviewPanel.jsx")
        self.assertIn("t.appsWithFocus", ov)
        src = open(os.path.join(ROOT, "viz_bridge.py"), encoding="utf-8").read()
        self.assertIn('totals["appsWithFocus"]', src)

    def test_the_network_app_rows_open_the_app(self):
        # Every clickable surface opens something; this list was inert.
        ov = _jsx("OverviewPanel.jsx")
        self.assertIn("onOpenApp && onOpenApp(a.app)", ov)
        self.assertIn("net-app--open", ov)

    def test_insight_panel_is_byte_identical_across_the_six(self):
        seen = set()
        for dash in ("react-viz", "react-mftusn", "react-lnkjl",
                     "react-prefetch", "react-shellitems", "react-browser"):
            with open(os.path.join(ROOT, dash, "src", "InsightPanel.jsx"), encoding="utf-8") as fh:
                seen.add(fh.read())
        self.assertEqual(len(seen), 1, "InsightPanel.jsx has diverged")

    def test_the_close_button_is_a_class_the_dashboards_style(self):
        # `.modal-x` is styled nowhere, so the panel shipped a default button.
        panel = _jsx("InsightPanel.jsx")
        self.assertIn('className="detail-close"', panel)
        self.assertNotIn("modal-x", panel)


if __name__ == "__main__":
    unittest.main()
