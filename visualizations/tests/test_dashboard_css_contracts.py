"""CSS contracts the six dashboards must all keep.

The dashboards share class names but no code - `styles.css` is six divergent
forks of one file with the same line numbers, so a fix applied to one is a fix
applied to one. These guard the rules that have to hold in all six.

**The crushed-rows bug this file exists for.** The prefetch "Loaded resources"
list looked collapsed: the heading said 285 resources, and underneath it was
blank. It was not collapsed, not dark, and not an accordion - the rows were
being *crushed*. `.res-list` is a column flexbox with `max-height: 300px`, so
its rows are flex children that shrink to fit. A row whose own `overflow` is
hidden - set on `.res-row` for the ellipsis - has an automatic minimum size of
**zero**, so nothing stops it: measured on a real case, 40 rows rendered at
**8px tall for an 11.5px font**, clipping every glyph into unreadable debris.
And because the shrink absorbed the overflow, `overflow: auto` computed nothing
to scroll, so no scrollbar appeared either - which is why it read as collapsed.

`.evt-row`, `.hour-row` and `.net-time` escaped it only by accident: they put
`overflow: hidden` on their inner `> span` rather than the row, so the row keeps
a min-content floor.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DASHBOARDS = ["react-viz", "react-mftusn", "react-lnkjl",
              "react-prefetch", "react-shellitems", "react-browser"]

# Containers that cap their height and scroll. Every one of them is a column
# flexbox, so every one of them can crush its rows.
CAPPED_SCROLLERS = [".net-times", ".hour-table", ".evt-table", ".res-list"]


def _css(dashboard):
    path = os.path.join(ROOT, dashboard, "src", "styles.css")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class CappedListsScrollRatherThanCrush(unittest.TestCase):

    def test_every_dashboard_guards_its_capped_lists(self):
        missing = []
        for dash in DASHBOARDS:
            css = _css(dash)
            guard = re.search(r"^[^\n{]*\.res-list\s*>\s*\*[^\n{]*\{([^}]*)\}",
                              css, re.M)
            if guard is None or "flex-shrink: 0" not in guard.group(1):
                missing.append(dash)
        self.assertEqual(missing, [],
                         "these can crush their rows instead of scrolling: %s"
                         % ", ".join(missing))

    def test_the_guard_covers_all_four_containers(self):
        """A guard that names only .res-list leaves the other three exposed."""
        for dash in DASHBOARDS:
            css = _css(dash)
            line = [l for l in css.splitlines()
                    if ".res-list > *" in l and "flex-shrink: 0" in l]
            self.assertTrue(line, "%s: no guard line" % dash)
            for container in CAPPED_SCROLLERS:
                self.assertIn("%s > *" % container, line[0],
                              "%s: %s is not covered by the shrink guard"
                              % (dash, container))

    def test_the_containers_still_look_like_the_thing_being_guarded(self):
        """The premise. If one stops being a capped column flexbox the guard is
        pointless for it and this should be revisited rather than left to rot."""
        for dash in DASHBOARDS:
            css = _css(dash)
            for container in CAPPED_SCROLLERS:
                m = re.search(r"^%s\s*\{([^}]*)\}" % re.escape(container), css, re.M)
                if m is None:
                    continue            # not every dashboard has every list
                body = m.group(1)
                self.assertIn("flex-direction: column", body,
                              "%s %s is no longer a column flexbox" % (dash, container))
                self.assertIn("max-height", body,
                              "%s %s is no longer capped" % (dash, container))


class EveryHeatmapIsAHorizontalDayStrip(unittest.TestCase):
    """X is the day, Y is the series - a fixed height whatever the range.

    SRUM and Browser used to be GitHub-style contribution calendars: X weekday,
    Y week, growing DOWNWARD at 27px per week. Browser covers 226 days in this
    case, which was ~33 stacked rows - the heat-map owned the page and pushed
    the dashboard below the fold. The strip is `series x 38px` (34px cell + gap) regardless.
    """

    # The component that draws each dashboard's heat strip.
    STRIPS = {
        "react-viz": "HeatmapStack.jsx",
        "react-mftusn": "TimelineStack.jsx",
        "react-lnkjl": "SourceTimeline.jsx",
        "react-prefetch": "LocationTimeline.jsx",
        "react-shellitems": "SourceTimeline.jsx",
        "react-browser": "BrowserTimeline.jsx",
    }

    def _src(self, dash):
        with open(os.path.join(ROOT, dash, "src", self.STRIPS[dash]),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_none_of_them_still_builds_a_week_calendar(self):
        calendars = [d for d in DASHBOARDS
                     if "hm-weekrow" in self._src(d) or "buildWeeks" in self._src(d)]
        self.assertEqual(calendars, [],
                         "still growing downward by week: %s" % ", ".join(calendars))

    def test_they_all_draw_the_strip(self):
        for dash in DASHBOARDS:
            src = self._src(dash)
            self.assertIn("usn-strip", src, "%s: no day strip" % dash)
            # The cells' class is chosen by `useStripFit` - it is `usn-cells` or
            # `usn-cells usn-cells--wide` depending on whether the days fit.
            self.assertIn("cellsClass", src, "%s: no day cells" % dash)
            self.assertIn("usn-cell", src, "%s: no day cells" % dash)

    def test_they_all_carry_the_shared_date_scale(self):
        """The three-tick axis (first/middle/last) told an investigator almost
        nothing about where a band of activity sat."""
        for dash in DASHBOARDS:
            src = self._src(dash)
            # "<DayAxis", not "DayAxis": the import line alone would satisfy a
            # bare name check even with the element deleted from the markup.
            self.assertIn("<DayAxis", src, "%s: no date scale rendered" % dash)
            self.assertNotIn("Math.floor(days.length / 2)", src,
                             "%s: the old three-tick axis is back" % dash)

    def test_the_scale_is_density_aware(self):
        """One tick per day collides as soon as the range grows; a fixed three
        is useless. The scale labels month starts (plus the 15th when a day has
        room), and a label that would land on the previous one is dropped by
        its rendered width - so a six-month window reads by month, never as
        overprinted text."""
        with open(os.path.join(ROOT, "react-viz", "src", "DayAxis.jsx"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("const mids = pitch >= 4", src)
        self.assertIn("(t.i - prev.i) * step >= widthOf(prev)", src)

    def test_the_axis_is_identical_in_all_six(self):
        """It is duplicated rather than shared, like Icons.jsx and
        DateDropdown.jsx - so it has to actually stay identical."""
        first = None
        for dash in DASHBOARDS:
            with open(os.path.join(ROOT, dash, "src", "DayAxis.jsx"),
                      encoding="utf-8") as fh:
                body = fh.read()
            if first is None:
                first = body
            self.assertEqual(body, first, "%s: DayAxis.jsx has drifted" % dash)


class TheRightHandCardsAreSpaced(unittest.TestCase):
    """Item 4: the overview cards needed real space between them."""

    MIN_GAP = 16

    def _gap(self, css, selector):
        m = re.search(r"^%s\s*\{([^}]*)\}" % re.escape(selector), css, re.M)
        if m is None:
            return None
        g = re.search(r"gap:\s*(\d+)px", m.group(1))
        return int(g.group(1)) if g else None

    def test_every_overview_column_has_room_between_cards(self):
        tight = []
        for dash in DASHBOARDS:
            css = _css(dash)
            # react-browser's panel renders .ov-root; the other five render .ov.
            gaps = [g for g in (self._gap(css, ".ov"), self._gap(css, ".ov-root"))
                    if g is not None]
            self.assertTrue(gaps, "%s: no overview container gap found" % dash)
            if min(gaps) < self.MIN_GAP:
                tight.append("%s (%dpx)" % (dash, min(gaps)))
        self.assertEqual(tight, [],
                         "cards are still crowded in: %s" % ", ".join(tight))

    def test_all_six_agree_on_the_gap(self):
        """They drifted to 12 and 14. Six copies of one stylesheet should not
        disagree about spacing.

        Every gap counts, not the smallest: react-browser carries BOTH `.ov`
        (inherited and dead there, since its panel renders `.ov-root`) and the
        live `.ov-root`. Taking the minimum let the dead rule mask a change to
        the live one.
        """
        seen = {}
        for dash in DASHBOARDS:
            css = _css(dash)
            found = {sel: self._gap(css, sel) for sel in (".ov", ".ov-root")}
            seen[dash] = {sel: g for sel, g in found.items() if g is not None}
        values = {g for gaps in seen.values() for g in gaps.values()}
        self.assertEqual(len(values), 1,
                         "overview gaps disagree across dashboards: %s" % seen)


class ReloadsShowThatSomethingIsHappening(unittest.TestCase):
    """The branded loading screen only ever covered the FIRST load.

    It is a replacement gated on the first payload, so once data had arrived it
    could never show again - changing a filter or a date range queried the case
    and gave no sign of it. The inline spinner meant to cover exactly that was
    dead code: the component returns the full screen on the same condition, so
    `{tlLoading && !timeline && ...}` could never be true.

    `LoadingOverlay` covers `.dash` and NOT the header, so the search box, the
    filters and the date picker stay usable while the reload runs. The
    Timeline's equivalent is `position: fixed` over everything, which briefly
    locks the control you are adjusting from.
    """

    def _app(self, dash):
        with open(os.path.join(ROOT, dash, "src", "App.jsx"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_dead_inline_spinner_is_gone(self):
        alive = []
        for dash in DASHBOARDS:
            if re.search(r"\w+Loading && !\w+ && <div className=\"loading-inline\"",
                         self._app(dash)):
                alive.append(dash)
        self.assertEqual(alive, [],
                         "unreachable spinner still present (the component already "
                         "returned the full screen on that condition): %s" % ", ".join(alive))

    def test_every_dashboard_mounts_the_overlay(self):
        for dash in DASHBOARDS:
            self.assertIn("<LoadingOverlay", self._app(dash),
                          "%s: a re-load shows nothing" % dash)

    def test_the_overlay_is_identical_in_all_six(self):
        """Duplicated like Icons.jsx and DayAxis.jsx, so it must stay identical."""
        first = None
        for dash in DASHBOARDS:
            with open(os.path.join(ROOT, dash, "src", "LoadingOverlay.jsx"),
                      encoding="utf-8") as fh:
                body = fh.read()
            first = body if first is None else first
            self.assertEqual(body, first, "%s: LoadingOverlay.jsx has drifted" % dash)

    def test_it_covers_the_dashboard_not_the_header(self):
        """`position: absolute` inside a positioned `.dash`. `fixed` would put it
        over the header too and lock the filters behind it."""
        for dash in DASHBOARDS:
            css = _css(dash)
            m = re.search(r"^\.loading-overlay\s*\{([^}]*)\}", css, re.M)
            self.assertIsNotNone(m, "%s: no .loading-overlay rule" % dash)
            body = m.group(1)
            self.assertIn("position: absolute", body,
                          "%s: the overlay would cover the header" % dash)
            self.assertNotIn("position: fixed", body)
            # `.dash` is declared twice - the original layout rule and the
            # later `position: relative` the overlay needs. CSS cascades, so
            # the effective value is the union; reading only the first rule
            # would report a problem that does not exist.
            dash_rules = re.findall(r"^\.dash \{([^}]*)\}", css, re.M)
            self.assertTrue(dash_rules, "%s: no .dash rule" % dash)
            self.assertTrue(any("position: relative" in r for r in dash_rules),
                            "%s: .dash is not a containing block, so an absolute "
                            "overlay would escape it" % dash)

    def test_a_failed_query_is_not_silently_an_empty_case(self):
        """The `.catch()` handlers substitute empty data. Without also recording
        the failure, "that query failed" and "this case has no data" render
        identically - and only one of them is the analyst's problem."""
        silent = []
        for dash in DASHBOARDS:
            src = self._app(dash)
            # Read the whole line, not a braced body: these handlers contain
            # object literals (`setBounds({ hasData: false })`), so a `[^}]*`
            # capture stops at the first inner `}` and misses what follows.
            for line in src.splitlines():
                stripped = line.strip()
                # Skip comments: the explanation of this very rule mentions
                # `.catch()`, so a plain text scan reports its own documentation.
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if ".catch(" in line and "setLoadErr" not in line:
                    silent.append("%s: %s" % (dash, stripped[:70]))
            self.assertIn("loading-overlay--error", _css(dash),
                          "%s: no error styling for the overlay" % dash)
        self.assertEqual(silent, [],
                         "these swallow a bridge failure:\n  " + "\n  ".join(silent))

    def test_the_browser_domain_panel_no_longer_shows_nothing(self):
        """`if (!detail) return null` meant clicking a domain produced no panel,
        no spinner and no sign the click had registered."""
        with open(os.path.join(ROOT, "react-browser", "src", "DomainDetailPanel.jsx"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("loading && !detail", src,
                      "the domain panel still renders nothing while loading")


class ClickingAnHourOpensThatHour(unittest.TestCase):
    """Four of the six drew an hour chart that was not clickable at all.

    `react-chartjs-2` renders the bars either way, so the chart looked
    interactive and did nothing - the kind of defect that survives review
    because nothing is broken on screen, there is simply no response.

    It needs no bridge call: every day payload already carries a per-event
    `hour` beside the `byHour` histogram the chart is drawn from, so the panel
    filters data the page already holds. `react-viz/src/HourDetailPanel.jsx`
    says exactly that in its own header.
    """

    # The component that draws each dashboard's hour chart.
    SECTIONS = {
        "react-viz": "DayActivitySection.jsx",
        "react-mftusn": "WindowSection.jsx",
        "react-lnkjl": "DaySection.jsx",
        "react-prefetch": "DaySection.jsx",
        "react-shellitems": "DaySection.jsx",
        "react-browser": "DaySection.jsx",
    }

    def _read(self, dash, name):
        with open(os.path.join(ROOT, dash, "src", name), encoding="utf-8") as fh:
            return fh.read()

    def test_every_dashboard_has_an_hour_panel(self):
        missing = [d for d in DASHBOARDS
                   if not os.path.exists(os.path.join(ROOT, d, "src", "HourDetailPanel.jsx"))]
        self.assertEqual(missing, [], "no hour drill-down in: %s" % ", ".join(missing))

    def test_every_hour_chart_is_clickable(self):
        dead = []
        for dash, section in self.SECTIONS.items():
            src = self._read(dash, section)
            if "onClick:" not in src:
                dead.append("%s/%s" % (dash, section))
        self.assertEqual(dead, [],
                         "these draw an hour chart that does nothing when clicked: %s"
                         % ", ".join(dead))

    def _host(self, dash):
        """Whichever component renders the hour panel, and its name."""
        app = self._read(dash, "App.jsx")
        section = self._read(dash, self.SECTIONS[dash])
        in_app = "<HourDetailPanel" in app
        in_section = "<HourDetailPanel" in section
        self.assertTrue(in_app or in_section, "%s: hour panel is never rendered" % dash)
        self.assertFalse(in_app and in_section, "%s: hour panel is rendered twice" % dash)
        return (app, "App.jsx") if in_app else (section, self.SECTIONS[dash])

    def test_the_panel_lives_with_the_state_that_opens_it(self):
        """The real invariant - not "it must be mounted in App".

        The *detail* modals had to be hoisted to App because an insight can
        open a record with no day selected, and the section holding them
        returns early in that case. An hour panel cannot hit that trap: the
        only way to open one is the hour chart, which lives inside the day
        section itself and never renders without a day.

        What must hold is that the panel is rendered by the same component that
        owns the state opening it, so that state cannot be set while the panel
        is unmounted. Five dashboards keep both in App; react-viz keeps both in
        DayActivitySection. Both are correct - a split between them would not
        be, and that is what this catches.
        """
        for dash in DASHBOARDS:
            host, name = self._host(dash)
            self.assertTrue(
                "openHour" in host or "hourDetail" in host,
                "%s: the hour panel is rendered in %s, away from the state that "
                "opens it" % (dash, name))

    def test_every_panel_wears_the_modal_chrome(self):
        """react-browser's was mounted bare - the only modal in the fleet with
        no overlay, so it did not dim the page and clicking away did nothing."""
        for dash in DASHBOARDS:
            host, name = self._host(dash)
            i = host.find("<HourDetailPanel")
            # The overlay/card wrapper sits just above the element.
            window = host[max(0, i - 500):i]
            self.assertIn("modal-overlay", window,
                          "%s: hour panel has no overlay (%s)" % (dash, name))
            self.assertIn("modal-card", window,
                          "%s: hour panel has no card (%s)" % (dash, name))

    def test_the_panel_filters_rather_than_refetching(self):
        """A bridge call here would mean asking for data the page already has.
        If one appears, the day payload is missing something - check that
        before adding a slot."""
        for dash in DASHBOARDS:
            src = self._read(dash, "HourDetailPanel.jsx")
            self.assertNotIn("call(", src,
                             "%s: the hour panel makes a bridge call" % dash)

    def test_its_rows_cannot_be_crushed(self):
        """`.hour-table` is one of the capped column flexboxes; a new row type
        inside it needs the same shrink guard as the rest."""
        for dash in DASHBOARDS:
            css = _css(dash)
            self.assertIn(".hour-table > *", css,
                          "%s: hour rows are not guarded against crushing" % dash)


if __name__ == "__main__":
    unittest.main()
