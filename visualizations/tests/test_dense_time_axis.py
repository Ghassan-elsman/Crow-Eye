"""A heat strip's x axis is time, so every day in the range must be on it.

`SELECT date(timestamp) d, COUNT(*) ... GROUP BY d` returns only the days that
*had* activity. Plot that directly and the strip stops being a time axis and
becomes an ordinal index of active days: two neighbouring cells can be months
apart while `DayAxis` spaces its labels evenly across them, which says the
opposite. Measured on one real case before this was fixed:

    browser      134 cells across   226 calendar days   (92 days erased)
    prefetch     170 cells across   213 days            (43 erased)
    viz           58 cells across    61 days             (3 erased)
    shellitems   146 cells across 4,568 days            (most of 12 years)
    lnkjl         70 cells across 4,568 days

**One cell is one day. Always.** An intermediate version widened the cell to a
week or a month on a long range so it would still fit the pane, and Shell Items'
twelve years became 151 month cells. That answers a different question than the
one being asked - which *days* were quiet - so the bucketing came out again.
A range too long to fit scrolls sideways; the unit never changes.

These guard the shared module, the six bridges and the strip components. How it
actually *looks* - cell widths, no spurious scrollbar, the sticky row head, the
opening position - is checked by driving the real bridges through the render
harness and reading the PNG; a count says nothing about that.
"""
import os
import json
import re
import unittest

from visualizations import timeseries as ts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every bridge that draws a strip, and the slot that builds it.
STRIP_BRIDGES = {
    "viz_bridge.py": "getSrumHeatmaps",
    "browser_bridge.py": "getBrowserHeatmaps",
    "prefetch_bridge.py": "getPrefetchTimeline",
    "shellitems_bridge.py": "getShellItemsTimeline",
    "lnkjl_bridge.py": "getLnkTimeline",
    "mftusn_bridge.py": "getMftUsnTimelines",
}

DASHBOARDS = ["react-viz", "react-mftusn", "react-lnkjl",
              "react-prefetch", "react-shellitems", "react-browser"]

# dashboard -> the component that draws its strip
STRIPS = {
    "react-viz": "HeatmapStack.jsx",
    "react-browser": "BrowserTimeline.jsx",
    "react-lnkjl": "SourceTimeline.jsx",
    "react-shellitems": "SourceTimeline.jsx",
    "react-prefetch": "LocationTimeline.jsx",
    "react-mftusn": "TimelineStack.jsx",
}


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _jsx(dashboard, name):
    with open(os.path.join(ROOT, dashboard, "src", name), encoding="utf-8") as fh:
        return fh.read()


def _css(dashboard):
    with open(os.path.join(ROOT, dashboard, "src", "styles.css"), encoding="utf-8") as fh:
        return fh.read()


def _slot_body(src, slot):
    body = src[src.index("def %s" % slot):]
    return body[:body.index("\n    @pyqtSlot")] if "\n    @pyqtSlot" in body else body


class EveryDayInTheRangeIsPresent(unittest.TestCase):

    def test_densify_fills_the_quiet_days(self):
        rows = ts.densify({"2026-01-01": 4, "2026-01-05": 2}, "2026-01-01", "2026-01-05")
        self.assertEqual([r["day"] for r in rows],
                         ["2026-01-01", "2026-01-02", "2026-01-03",
                          "2026-01-04", "2026-01-05"])
        self.assertEqual([r["value"] for r in rows], [4, 0, 0, 0, 2])

    def test_a_twelve_year_range_is_four_thousand_cells_not_a_hundred_and_fifty(self):
        # Shell Items' real span. Bucketing to months made this 151 cells, which
        # cannot answer "which days were quiet".
        self.assertEqual(len(ts.day_keys("2014-03-18", "2026-09-18")), 4568)

    def test_the_filter_range_wins_over_the_data(self):
        # An analyst who narrowed to a week means that week, including the days
        # in it with nothing on them - which are often the point.
        start, end = ts.axis_range({"start": "2026-01-01", "end": "2026-01-05"},
                                   {"2026-02-20": 1})
        self.assertEqual((start, end), ("2026-01-01", "2026-01-05"))
        self.assertEqual(len(ts.densify({"2026-02-20": 1}, start, end)), 5)

    def test_with_no_filter_the_axis_is_the_data(self):
        self.assertEqual(ts.axis_range({}, {"2026-01-03": 1, "2026-01-09": 2}),
                         ("2026-01-03", "2026-01-09"))

    def test_one_blank_side_of_the_filter_falls_back_to_the_data(self):
        self.assertEqual(ts.axis_range({"start": "2026-01-01"},
                                       {"2026-01-03": 1, "2026-01-09": 2}),
                         ("2026-01-01", "2026-01-09"))

    def test_an_empty_case_produces_no_axis_out_of_nothing(self):
        self.assertEqual(ts.axis_range({}, {}), ("", ""))
        self.assertEqual(ts.densify({}, "", ""), [])

    def test_every_series_gets_the_same_days(self):
        # What lets a stack of strips line up cell-for-cell.
        out = ts.densify_series({"a": {"2026-01-01": 1}, "b": {"2026-01-04": 9}, "c": {}},
                                "2026-01-01", "2026-01-04")
        keys = [[d["day"] for d in v["days"]] for v in out.values()]
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[0], keys[2])
        self.assertEqual(out["c"]["max"], 0)

    def test_a_series_can_be_named_the_way_the_usn_strip_names_it(self):
        out = ts.densify_series({"a": {"2026-01-01": 1}}, "2026-01-01", "2026-01-02",
                                key="key", field="buckets")
        self.assertEqual([b["key"] for b in out["a"]["buckets"]],
                         ["2026-01-01", "2026-01-02"])

    def test_a_table_row_carries_every_column(self):
        rows = ts.densify_table({"created": {"2026-01-01": 3},
                                 "modified": {"2026-01-03": 1}},
                                "2026-01-01", "2026-01-03")
        self.assertEqual(rows[1], {"day": "2026-01-02", "created": 0, "modified": 0})
        self.assertEqual(rows[2], {"day": "2026-01-03", "created": 0, "modified": 1})

    def test_day_keys_cross_months_and_leap_years(self):
        self.assertEqual(len(ts.day_keys("2024-02-27", "2024-03-02")), 5)   # 29 Feb
        self.assertEqual(len(ts.day_keys("2025-02-27", "2025-03-02")), 4)   # no 29th
        self.assertEqual(len(ts.day_keys("2025-12-30", "2026-01-02")), 4)

    def test_a_backwards_or_unparseable_range_is_empty_not_wrong(self):
        self.assertEqual(ts.day_keys("2026-01-05", "2026-01-01"), [])
        self.assertEqual(ts.day_keys("not a date", "2026-01-01"), [])

    def test_timestamps_longer_than_a_date_still_land_on_their_day(self):
        rows = ts.densify({"2026-01-02T13:45:00": 2}, "2026-01-01", "2026-01-02")
        self.assertEqual([r["value"] for r in rows], [0, 2])


class NothingChoosesAGranularityAnyMore(unittest.TestCase):
    """The bucketing is gone, and must not come back by accident."""

    def test_the_shared_module_has_no_bucket_api(self):
        for gone in ("choose_bucket", "bucket_key", "bucket_end", "bucket_span",
                     "in_bucket", "bucket_keys", "HOUR", "WEEK", "MONTH"):
            self.assertFalse(hasattr(ts, gone),
                             "timeseries.%s is back; a cell is always one day" % gone)

    def test_no_strip_slot_reports_a_bucket(self):
        offenders = []
        for name, slot in STRIP_BRIDGES.items():
            body = _slot_body(_src(name), slot)
            if '"bucket"' in body or '"mftBucket"' in body or '"gran"' in body:
                offenders.append("%s: %s still reports a granularity" % (name, slot))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_every_strip_slot_densifies(self):
        missing = [name for name, slot in STRIP_BRIDGES.items()
                   if "_densify" not in _slot_body(_src(name), slot)]
        self.assertEqual(missing, [], "these do not fill the range: %s" % missing)

    def test_the_mftusn_window_slot_matches_one_day(self):
        body = _slot_body(_src("mftusn_bridge.py"), "getMftUsnWindowDetail")
        self.assertIn("date(usn_timestamp)=?", body)
        self.assertNotIn("substr(usn_timestamp,1,13)", body)   # the hour branch
        self.assertNotIn("_bucket_end", body)

    def test_no_dashboard_passes_a_bucket_anywhere(self):
        offenders = []
        for dash in DASHBOARDS:
            d = os.path.join(ROOT, dash, "src")
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".jsx") or fn == "DayAxis.jsx":
                    continue
                src = _jsx(dash, fn)
                for token in ("bucketTitle", "periodPhrase", "cellDensity",
                              "bucketSpan", "BucketNote", "?.bucket", "gran"):
                    if token in src:
                        offenders.append("%s/%s uses %s" % (dash, fn, token))
        self.assertEqual(offenders, [], "\n".join(offenders))


class ALongRangeIsPagedSixMonthsAtATime(unittest.TestCase):
    """The strip shows a 183-day window that always fills its pane, and the
    StripNavigator pages it and draws the whole range. It used to become a
    ~22,000px strip behind a scrollbar: 7px slivers, no view of the whole."""

    def test_day_axis_is_byte_identical_across_the_six(self):
        seen = {_jsx(d, "DayAxis.jsx") for d in DASHBOARDS}
        self.assertEqual(len(seen), 1, "DayAxis.jsx has diverged between dashboards")

    def test_the_window_is_six_months_and_never_scrolls(self):
        src = _jsx("react-viz", "DayAxis.jsx")
        self.assertIn("export const WINDOW_DAYS = 183", src)
        self.assertIn("export function useStripWindow(days, selectedDay)", src)
        self.assertIn("export function StripNavigator(", src)
        self.assertNotIn("usn-strip--wide", src)
        self.assertNotIn("scrollLeft", src)

    def test_a_fitting_strip_uses_minmax_zero_not_a_bare_fraction(self):
        # A bare `1fr` is `minmax(auto, 1fr)`, so `.usn-cell.sel`'s 2px borders
        # became every track's minimum and pushed the strip past its pane.
        self.assertIn("repeat(${n}, minmax(0, 1fr))", _jsx("react-viz", "DayAxis.jsx"))

    def test_no_strip_is_a_scroller(self):
        for dash in DASHBOARDS:
            css = _css(dash)
            self.assertNotIn("usn-strip--wide", css, dash)
            self.assertNotRegex(css, r"\.usn-strip \{[^}]*overflow-x", dash)
            self.assertIn(".strip-nav-ov", css, "%s: no navigator overview styles" % dash)

    def test_the_row_head_stays_put_and_covers_the_row(self):
        for dash in DASHBOARDS:
            css = _css(dash)
            head = re.search(r"\.usn-rowhead \{[^}]*\}", css, re.S)
            self.assertTrue(head, dash)
            self.assertIn("position: sticky", head.group(0), dash)
            self.assertIn("background: var(--bg-card)", head.group(0), dash)
            self.assertIn("align-self: stretch", head.group(0), dash)
            # The cells' width is computed from this before layout.
            self.assertIn("width: 120px", head.group(0), dash)
        self.assertIn("const ROWHEAD_PX = 120", _jsx("react-viz", "DayAxis.jsx"))

    def test_the_cells_are_big_enough_to_read(self):
        for dash in DASHBOARDS:
            cell = re.search(r"\n\.usn-cell \{[^}]*\}", _css(dash), re.S)
            self.assertTrue(cell, dash)
            self.assertIn("height: 34px", cell.group(0), dash)

    def test_the_axis_and_the_cells_share_a_gap(self):
        for dash in DASHBOARDS:
            css = _css(dash)
            self.assertRegex(css, r"\.usn-axlabels \{[^}]*gap: 1px", dash)
            self.assertRegex(css, r"\.usn-cells \{[^}]*gap: 1px", dash)

    def test_every_strip_is_windowed_and_navigable(self):
        missing = []
        for dash, comp in STRIPS.items():
            src = _jsx(dash, comp)
            if "1 cell = 1 day" not in src:
                missing.append("%s/%s does not state the unit" % (dash, comp))
            if not re.search(r"const win = useStripWindow\(\w+, \w+\)", src):
                missing.append("%s/%s is not windowed" % (dash, comp))
            if "useStripFit(stripRef, view.length)" not in src:
                missing.append("%s/%s does not fit the window" % (dash, comp))
            if not re.search(r"<StripNavigator win=\{win\} days=\{\w+\} totals=\{totals\} />", src):
                missing.append("%s/%s has no navigator" % (dash, comp))
            if "<DayAxis days={view} columns={columns} pitch={pitch} />" not in src:
                missing.append("%s/%s axis does not label the window's cells" % (dash, comp))
            if "{view.map(" not in src:
                missing.append("%s/%s does not draw the window" % (dash, comp))
            if "usn-strip--wide" in src or "onScroll" in src:
                missing.append("%s/%s still scrolls" % (dash, comp))
        self.assertEqual(missing, [], "\n".join(missing))

    def test_the_axis_labels_month_starts_and_never_overlaps(self):
        src = _jsx("react-viz", "DayAxis.jsx")
        self.assertIn("dd === '01'", src)                 # a label at every month start
        self.assertIn("monthLabel(", src)                  # "Jan 2026" at a year change
        self.assertIn("(t.i - prev.i) * step >= widthOf(prev)", src)
        self.assertIn("gridColumn: t.i + 1", src)          # only labelled columns rendered
        for dash in DASHBOARDS:
            self.assertIn(".usn-axtick--major", _css(dash), dash)


class TheWindowOpensOnTheMostRecentDays(unittest.TestCase):
    """windowFor() is pure; run it in node where node exists."""

    @classmethod
    def setUpClass(cls):
        import shutil, subprocess
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is not available")
        src = _jsx("react-viz", "DayAxis.jsx")
        m = re.search(r"export function windowFor\(.*?\n\}\n", src, re.S)
        assert m, "windowFor not found"
        fn = m.group(0).replace("export function", "function")
        script = fn + r"""
const W = 183
const out = {
  short: windowFor(61, W, null, -1),
  latest: windowFor(4568, W, null, -1),
  keepsManual: windowFor(4568, W, 1000, 1050),
  followsSelection: windowFor(4568, W, null, 100),
  clampLow: windowFor(4568, W, -500, -1),
  clampHigh: windowFor(4568, W, 99999, -1),
}
console.log(JSON.stringify(out))
"""
        r = subprocess.run([cls.node, "-e", script], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.r = json.loads(r.stdout)

    def test_a_short_range_is_shown_whole(self):
        self.assertEqual(self.r["short"], 0)

    def test_it_opens_on_the_last_six_months(self):
        self.assertEqual(self.r["latest"], 4568 - 183)

    def test_a_selection_on_screen_leaves_the_window_alone(self):
        self.assertEqual(self.r["keepsManual"], 1000)

    def test_a_selection_off_screen_brings_the_window_to_it_centred(self):
        self.assertEqual(self.r["followsSelection"], 100 - 91)

    def test_the_window_never_runs_off_either_end(self):
        self.assertEqual(self.r["clampLow"], 0)
        self.assertEqual(self.r["clampHigh"], 4568 - 183)

    def test_every_dashboard_defaults_to_the_most_recent_activity(self):
        missing = []
        for dash in DASHBOARDS:
            app = _jsx(dash, "App.jsx")
            if "busiest" in app:
                missing.append("%s/App.jsx still opens on the busiest cell" % dash)
            if "reverse().find(d => d.value > 0)" not in app:
                missing.append("%s/App.jsx does not default to the latest activity" % dash)
        self.assertEqual(missing, [], "\n".join(missing))


class ThirtyTwoThousandCellsStayInteractive(unittest.TestCase):
    """Shell Items is 4,568 days x 7 sources. A handler per cell meant every
    mouse move re-rendered all of them."""

    def test_the_cells_carry_their_day_and_the_row_carries_the_handlers(self):
        missing = []
        for dash, comp in STRIPS.items():
            src = _jsx(dash, comp)
            if "data-day=" not in src:
                missing.append("%s/%s cells do not carry their day" % (dash, comp))
            if re.search(r"<div key=\{\w+\} data-day[^>]*onClick", src, re.S):
                missing.append("%s/%s still puts a handler on every cell" % (dash, comp))
            for handler in ("onMouseMove={(e) =>", "onMouseLeave={() => setTip(null)}",
                            "onClick={(e) =>"):
                if handler not in src:
                    missing.append("%s/%s row is missing %s" % (dash, comp, handler))
        self.assertEqual(missing, [], "\n".join(missing))

    def test_the_rows_are_memoised_away_from_the_tooltip(self):
        missing = []
        for dash, comp in STRIPS.items():
            src = _jsx(dash, comp)
            if "const rows = useMemo(" not in src:
                missing.append("%s/%s does not memoise its rows" % (dash, comp))
            # `tip` must not be a dependency, or the memo is pointless.
            m = re.search(r"const rows = useMemo\(.*?\}\), \[([^\]]*)\]\)", src, re.S)
            if not m:
                missing.append("%s/%s memo has no dependency list" % (dash, comp))
            elif "tip" in m.group(1):
                missing.append("%s/%s memo depends on the tooltip state" % (dash, comp))
        self.assertEqual(missing, [], "\n".join(missing))

    def test_a_cell_sets_no_width_of_its_own(self):
        # The track width comes from `useStripFit`; a `min-width` on the cell
        # would fight it and silently widen the strip.
        for dash in DASHBOARDS:
            cell = re.search(r"\n\.usn-cell \{[^}]*\}", _css(dash), re.S)
            self.assertTrue(cell, dash)
            self.assertIn("min-width: 0", cell.group(0), dash)


if __name__ == "__main__":
    unittest.main()
