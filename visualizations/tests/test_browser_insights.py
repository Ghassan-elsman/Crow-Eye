"""Browser Forensics' Insights card, and the two signals that were rejected.

Browser was the last dashboard with no insights at all: its overview was good
at drill-down - domains, typed terms, downloads and orphan domains were all
clickable - but ended in two numbers nothing could open, "a further N domains
appear only in cache" and "+N more corroborated".

The Anti-forensics card was **folded into** the Insights card rather than left
beside it, so its reasoning now lives in the hint each tile carries.

**Two candidate signals were measured and dropped.** Both are guarded here,
because the reason not to ship them is not obvious from the code:

- *Downloads that were opened* - 53 of 160 on the case this was written
  against. Opening what you downloaded is what downloading is for.
- *Domains appearing only in cache* - `browser_cache.url` does not hold one
  clean URL per row (273 of 400 sampled rows parse to something that is not a
  host: concatenated URLs, Permissions-Policy header text), so the 233 it
  counted were mostly parse debris.
"""
import json
import os
import re
import unittest

VIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(VIZ, "browser_bridge.py")


def _bridge_src():
    with open(SRC, encoding="utf-8") as fh:
        return fh.read()


def _jsx(name):
    with open(os.path.join(VIZ, "react-browser", "src", name), encoding="utf-8") as fh:
        return fh.read()


class TheCardExistsAndIsOpenable(unittest.TestCase):

    def test_the_overview_returns_insights(self):
        src = _bridge_src()
        self.assertIn('"insights": self._browser_insights(args)', src)
        # The Anti-forensics card was folded in, not kept beside it.
        self.assertNotIn('"antiForensics"', src)

    def test_it_uses_the_shared_shape(self):
        src = _bridge_src()
        for helper in ("_insight(", "_plain(", "_subject("):
            self.assertIn(helper, src, "browser_bridge does not use %s" % helper)

    def test_the_openable_tiles_are_wired_both_ends(self):
        app, ov = _jsx("App.jsx"), _jsx("OverviewPanel.jsx")
        keys = set(re.findall(r"onOpenInsight\('(\w+)'\)", ov))
        self.assertEqual(keys, {"historyPruned", "flaggedDownloads", "executableDownloads"})
        for k in keys:
            self.assertIn("%s:" % k, app, "%s has no title/hint in App.jsx" % k)
            self.assertIn("ins.%s" % k, ov, "%s is not rendered" % k)

    def test_a_measurement_tile_is_not_clickable(self):
        ov = _jsx("OverviewPanel.jsx")
        m = re.search(r"<Anom d=\{ins\.domains\}[^/]*/>", ov, re.S)
        self.assertTrue(m, "the distinct-domains measurement is not on the card")
        self.assertNotIn("onOpen", m.group(0))

    def test_the_panel_is_mounted_in_app(self):
        # A panel inside a section that returns early can be opened and render
        # nothing at all.
        app = _jsx("App.jsx")
        self.assertIn("<InsightPanel", app)
        self.assertIn("onOpen={(domain) => { setOpenInsight(null); setOpenDomain(domain) }}", app)
        for other in ("DaySection.jsx", "OverviewPanel.jsx"):
            self.assertNotIn("<InsightPanel", _jsx(other), other)

    def test_the_old_card_is_gone_from_the_page(self):
        ov = _jsx("OverviewPanel.jsx")
        self.assertNotIn("Anti-forensics signals", ov)
        self.assertNotIn("overview.antiForensics", ov)
        # ...and its reasoning survived into the hint the tile carries.
        self.assertIn("outlive a cleared history", _jsx("App.jsx"))

    def test_the_close_button_is_a_class_the_dashboard_styles(self):
        # `.modal-x` is styled nowhere, so the domain modal shipped a default
        # browser button.
        src = _jsx("DomainDetailPanel.jsx")
        self.assertNotIn('className="modal-x"', src)
        self.assertIn('className="detail-close"', src)

    def test_the_insight_list_css_is_present(self):
        with open(os.path.join(VIZ, "react-browser", "src", "styles.css"), encoding="utf-8") as fh:
            css = fh.read()
        for rule in (".ins-list", ".ins-row", ".ins-label", ".anom--open"):
            self.assertIn(rule + " ", css, "browser has no %s rule" % rule)
        self.assertIn(".ins-list > * { flex-shrink: 0; }", css)


class OnlyCorroboratedDomainsCountAsPruned(unittest.TestCase):
    """One artifact is too weak to state.

    A third-party cookie is set on domains the user never chose to visit: 82 of
    this case's 106 single-artifact orphans were exactly that. Two independent
    artifacts agreeing is the shape of a site that was used and then pruned.
    """

    def test_the_rule_is_two_or_more_kinds(self):
        src = _bridge_src()
        self.assertIn('len(set(o["sources"])) >= 2', src)

    def test_the_hint_says_why_the_weak_ones_are_excluded(self):
        self.assertIn("corroborated by a single artifact are excluded", _jsx("App.jsx"))

    def test_the_names_are_kept_not_just_counted(self):
        # `_anti_forensics` used to drop the cache-only names and return a bare
        # count; the orphan list it returns must carry the domains themselves.
        src = _bridge_src()
        self.assertIn('"orphans": corroborated', src)


class TheRejectedSignalsStayRejected(unittest.TestCase):

    def test_neither_is_emitted(self):
        src = _bridge_src()
        insights = src[src.index("def _browser_insights"):]
        mark = "\n    @pyqtSlot"
        if mark in insights:
            insights = insights[:insights.index(mark)]
        self.assertNotIn('"openedDownloads"', insights)
        self.assertNotIn('"cacheOnly"', insights)
        # and the unreliable column is not computed for anything else either
        self.assertNotIn('"cacheOnlyCount"', src)

    def test_the_reasoning_is_recorded_next_to_the_code(self):
        src = _bridge_src()
        doc = src[src.index("def _browser_insights"):]
        doc = doc[:doc.index('"""', doc.index('"""') + 3)]
        for phrase in ("53 of 160", "273 of 400"):
            self.assertIn(phrase, doc,
                          "the measurement that rejected a signal is not recorded")


class DownloadSignalsReadTheRightColumns(unittest.TestCase):

    def test_safe_danger_types_are_excluded(self):
        # Chromium: 0 is NOT_DANGEROUS, 7 is USER_VALIDATED.
        src = _bridge_src()
        self.assertIn("SAFE_DANGER_TYPES = {0, 7}", src)

    def test_an_unparseable_danger_type_is_not_a_warning(self):
        src = _bridge_src()
        self.assertIn("except (TypeError, ValueError):", src)
        self.assertIn("risky = False", src)

    def test_executables_are_matched_by_extension(self):
        src = _bridge_src()
        self.assertIn("EXECUTABLE_EXT", src)
        for ext in (".exe", ".ps1", ".scr", ".jar"):
            self.assertIn('"%s"' % ext, src, "%s is not treated as executable" % ext)

    def test_the_download_scan_is_not_the_capped_overview_list(self):
        """`_downloads` caps at 20 for the card; an insight that counted those
        would under-report."""
        src = _bridge_src()
        self.assertIn("def _download_rows", src)
        body = src[src.index("def _download_rows"):]
        body = body[:body.index("\n    def ", 1)]
        self.assertNotIn("LIMIT", body)
        # ...and the insight reads that uncapped scan, not the card's list.
        mark = "\n    @pyqtSlot"
        ins = src[src.index("def _browser_insights"):]
        if mark in ins:
            ins = ins[:ins.index(mark)]
        self.assertIn("self._download_rows(args)", ins)
        self.assertNotIn("self._downloads(args)", ins)


class TheDomainPanelShowsItsSourceRows(unittest.TestCase):

    def test_every_table_that_can_name_a_domain_is_listed(self):
        src = _bridge_src()
        # Scoped to the block: `("browser_cookies", ...)` appears in four other
        # table lists in this file, so a bare substring check still passes once
        # the table has been dropped from the search.
        block = src[src.index("DOMAIN_TABLES = ("):]
        block = block[:block.index("\n    )")]
        for table in ("browser_history", "browser_cookies", "browser_downloads",
                      "browser_favicons", "browser_sessions", "browser_logins"):
            self.assertIn('("%s"' % table, block, "%s is not searched" % table)

    def test_the_sensitive_tables_rely_on_the_withhold_list(self):
        """`browser_cookies` and `browser_logins` are emitted verbatim, so the
        withhold list is the only thing keeping secrets off the screen."""
        from visualizations.raw_record import raw_record
        row = {"host_key": "example.test", "encrypted_value_b64": "SECRET-VALUE",
               "name": "sid"}
        rec = raw_record(row, "browser_cookies")
        fields = {f["name"]: f for f in rec["fields"]}
        self.assertTrue(fields["encrypted_value_b64"]["withheld"])
        self.assertEqual(fields["encrypted_value_b64"]["value"], "")
        self.assertNotIn("SECRET-VALUE", json.dumps(rec))
        # ...and the column is still named, because "this cookie has a stored
        # value" is itself a fact.
        self.assertIn("encrypted_value_b64", json.dumps(rec))


if __name__ == "__main__":
    unittest.main()
