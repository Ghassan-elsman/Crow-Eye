"""An insight states a number; it must also be able to say who it is about.

Insights used to be bare integers - `{"userTemp": 19}` - and the loop that
counted those 19 programs discarded which ones they were, so the card could
state a number and the analyst had no way to ask the obvious next question.
`visualizations/insights.py` replaced that with `{count, subjects, truncated}`.

**Why this file exists.** Converting `lnkjl_bridge.py` I declared the subject
lists and passed them to `insight(...)`, but the three `.append(...)` calls
never landed - a heredoc ate the backslashes in the `"\\temp\\"` block and
nothing asserted the anchor had matched. The bridge then returned
`insight(32, [])`, which is `truncated: True` with an empty list: the UI would
have said *"32 records - showing the first 0"*, implying records were being
withheld. That is worse than the bare number it replaced, and every structural
check passed, because the shape was right and only the content was missing.

So this asserts the thing that actually matters: a positive count comes with
subjects, unless the bridge explicitly says it is a measurement rather than a
set of records (`insights.plain()`), which is exactly what a maximum or a
distinct-user count is.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# A real parsed case. These tests are about the SHAPE of what a bridge returns,
# never about its contents - no value from the case is asserted on or printed.
# A real parsed case; set CROW_EYE_TEST_CASE to point elsewhere. Without one
# the case-backed tests skip.
CASE = os.environ.get("CROW_EYE_TEST_CASE") or os.path.join(
    os.path.expanduser("~"), "Downloads", "18.9.2026", "Target_Artifacts")

# bridge module, class, overview slot, the keys that are measurements rather
# than sets of records, and the key the insights live under - react-mftusn
# calls them "anomalies", and naming it here is what stops it being skipped.
BRIDGES = [
    ("visualizations.prefetch_bridge", "PrefetchBridge",
     "getPrefetchOverview", {"maxRuns"}, "insights"),
    ("visualizations.lnkjl_bridge", "LnkJlBridge",
     "getLnkOverview", {"externalVolumes"}, "insights"),
    ("visualizations.shellitems_bridge", "ShellItemsBridge",
     "getShellItemsOverview", {"users"}, "insights"),
    ("visualizations.mftusn_bridge", "MftUsnBridge",
     "getMftUsnOverview", set(), "anomalies"),
    ("visualizations.viz_bridge", "VizBridge",
     "getSrumOverview", {"busiestApp", "users"}, "insights"),
    ("visualizations.browser_bridge", "BrowserBridge",
     "getBrowserOverview", {"domains", "activeDays"}, "insights"),
]


def _insights_of(mod, cls, slot, key):
    __import__(mod)
    bridge = getattr(sys.modules[mod], cls)(CASE)
    return json.loads(getattr(bridge, slot)(json.dumps({}))).get(key) or {}


class InsightsCarryTheirSubjects(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(CASE):
            raise unittest.SkipTest("no parsed case to read shapes from")
        try:
            from PyQt5 import QtCore                      # noqa: F401
        except Exception as exc:                          # pragma: no cover
            raise unittest.SkipTest("PyQt5 unavailable: %s" % exc)

    def test_a_positive_count_comes_with_its_records(self):
        """The Part A regression, guarded."""
        from visualizations.insights import SUBJECT_CAP
        empty = []
        for mod, cls, slot, measurements, key in BRIDGES:
            insights = _insights_of(mod, cls, slot, key)
            for key, value in insights.items():
                if key in measurements or not isinstance(value, dict):
                    continue
                count = value.get("count", 0)
                got = len(value.get("subjects") or [])
                if count > 0 and got == 0:
                    empty.append("%s.%s (count=%d, subjects=0)" % (cls, key, count))
                elif count > 0:
                    self.assertEqual(
                        got, min(count, SUBJECT_CAP),
                        "%s.%s: %d subjects for a count of %d" % (cls, key, got, count))
        self.assertEqual(empty, [],
                         "these state a number they cannot back up:\n  "
                         + "\n  ".join(empty))

    def test_truncated_is_never_a_lie(self):
        """`truncated: True` with nothing listed tells the analyst records are
        being withheld when in fact none were collected."""
        bad = []
        for mod, cls, slot, _m, key in BRIDGES:
            insights = _insights_of(mod, cls, slot, key)
            for key, value in insights.items():
                if not isinstance(value, dict):
                    continue
                if value.get("truncated") and not (value.get("subjects") or []):
                    bad.append("%s.%s" % (cls, key))
        self.assertEqual(bad, [], "truncated with no subjects: %s" % ", ".join(bad))

    def test_every_insight_uses_the_shared_shape(self):
        """A bare integer is the old shape; the React tile renders it read-only
        rather than crashing, so a missed conversion is invisible on screen."""
        stale = []
        for mod, cls, slot, _m, key in BRIDGES:
            insights = _insights_of(mod, cls, slot, key)
            self.assertTrue(insights, "%s returned no insights at all" % cls)
            for key, value in insights.items():
                if not isinstance(value, dict) or "count" not in value:
                    stale.append("%s.%s = %r" % (cls, key, value))
        self.assertEqual(stale, [],
                         "still bare numbers: %s" % ", ".join(stale))

    def test_a_subject_can_actually_be_opened(self):
        """`open` is the whole point - it is the id the dashboard's existing
        detail modal takes. A subject list with no openable rows is a list, not
        a drill-down."""
        from visualizations.prefetch_bridge import PrefetchBridge
        bridge = PrefetchBridge(CASE)
        insights = json.loads(bridge.getPrefetchOverview(json.dumps({})))["insights"]
        subjects = insights["userTemp"]["subjects"]
        if not subjects:
            self.skipTest("this case has no programs run from User/Temp")
        first = subjects[0]
        self.assertIn("open", first, "subject carries no id to open")
        detail = json.loads(bridge.getPrefetchProgramDetail(
            json.dumps({"filename": first["open"]})))
        self.assertTrue(detail.get("exe"),
                        "the id in a subject did not resolve to a program profile")


class TheDetailModalDoesNotDependOnADay(unittest.TestCase):
    """Opening a record from an insight must not require a day to be selected.

    The detail modal used to be rendered inside `DaySection`, which returns
    early when `!day`. So clicking a subject in an insight panel set the state,
    closed the panel, and showed **nothing at all** - the modal simply never
    mounted. It was invisible in testing because the day is usually already
    selected by the time anyone clicks around.

    A modal is not part of a day section, so it belongs in App.
    """

    # dashboard -> (detail panel, the section that used to trap it)
    DASHBOARDS = {
        "react-prefetch": ("ProgramDetailPanel", "DaySection.jsx"),
        "react-lnkjl": ("TargetDetailPanel", "DaySection.jsx"),
        "react-shellitems": ("ItemDetailPanel", "DaySection.jsx"),
        "react-mftusn": ("FileDetailPanel", "WindowSection.jsx"),
    }
    VIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(self, dash, name):
        with open(os.path.join(self.VIZ, dash, "src", name), encoding="utf-8") as fh:
            return fh.read()

    def test_the_modal_is_rendered_from_app(self):
        for dash, (panel, _sec) in self.DASHBOARDS.items():
            self.assertIn("<%s" % panel, self._read(dash, "App.jsx"),
                          "%s: detail modal is not mounted at App level" % dash)

    def test_it_is_no_longer_trapped_in_a_conditional_section(self):
        for dash, (panel, section) in self.DASHBOARDS.items():
            self.assertNotIn("<%s" % panel, self._read(dash, section),
                             "%s: detail modal is back inside %s, which returns "
                             "early when nothing is selected" % (dash, section))

    def test_those_sections_still_return_early(self):
        """The premise. If one stops short-circuiting, the trap is gone for it
        and this can be revisited rather than left as a rule with no reason."""
        for dash, (_panel, section) in self.DASHBOARDS.items():
            src = self._read(dash, section)
            self.assertTrue("if (!day)" in src or "if (!bucket)" in src,
                            "%s: %s no longer short-circuits" % (dash, section))


class TheSharedShapeBehaves(unittest.TestCase):
    """insights.py on its own - no case needed."""

    def test_the_count_is_not_derived_from_the_list(self):
        """Deriving it would silently under-report the moment the cap bit."""
        from visualizations.insights import insight
        out = insight(500, [{"label": str(i)} for i in range(500)], cap=10)
        self.assertEqual(out["count"], 500)
        self.assertEqual(len(out["subjects"]), 10)
        self.assertTrue(out["truncated"])

    def test_an_exact_fit_is_not_marked_truncated(self):
        from visualizations.insights import insight
        out = insight(3, [{"label": "a"}, {"label": "b"}, {"label": "c"}])
        self.assertFalse(out["truncated"])

    def test_a_measurement_says_so(self):
        """`plain` exists so the UI can tell "nothing matched" from "we never
        collected the subjects" - identical if both are just an empty list."""
        from visualizations.insights import plain
        out = plain(1092)
        self.assertEqual(out["count"], 1092)
        self.assertEqual(out["subjects"], [])
        self.assertFalse(out["truncated"])


if __name__ == "__main__":
    unittest.main()
