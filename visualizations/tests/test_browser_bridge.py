"""BrowserBridge - the browser-forensics dashboard data layer.

Fixture `browser_analysis.db` spanning the five activities and both engines:
Chromium and Gecko history (one typed, one clicked), a download flagged
dangerous, cookies on a host with no surviving history row (the anti-forensics
signal), cache entries, and an omnibox shortcut.

Two tables are deliberately ABSENT (`browser_service_worker`,
`browser_gecko_downloads`) so `_usable()` is exercised on every run, and
`browser_gecko_history` is given the OLDER column spelling (`typed`, not
`typed_count`) so the drift path is covered too - a case parsed before 2026-09
really does look like this.

No test asserts on a secret, because the bridge must never return one.
"""
import os
import sys
import json
import sqlite3
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PROV = ["browser", "vendor", "user_name", "sid", "profile", "source_path", "parsed_at"]

TABLES = {
    "browser_history": PROV + ["url", "title", "visit_count", "typed_count",
                               "last_visit_time", "visit_time", "transition",
                               "from_visit_url", "visit_id"],
    # Older spelling on purpose: `typed`, and no `transition`.
    "browser_gecko_history": PROV + ["url", "title", "visit_count", "typed",
                                     "last_visit_time", "visit_time", "visit_type",
                                     "from_visit_url"],
    "browser_downloads": PROV + ["target_path", "source_url", "referrer", "tab_url",
                                 "received_bytes", "total_bytes", "start_time",
                                 "end_time", "danger_type", "interrupt_reason",
                                 "state", "opened", "mime_type", "download_id"],
    "browser_cookies": PROV + ["host_key", "name", "path", "creation_time",
                               "expires_time", "last_access_time", "is_secure",
                               "is_httponly", "is_persistent", "samesite",
                               "source_scheme", "has_expires",
                               "encrypted_value_b64", "encryption_version"],
    "browser_gecko_cookies": PROV + ["host", "name", "path", "creation_time",
                                     "expiry_time", "last_accessed", "value"],
    "browser_cache": PROV + ["url", "request_time", "response_time", "http_status",
                             "content_type", "content_length", "content_encoding",
                             "server_headers", "extracted_body_path", "cache_format"],
    "browser_shortcuts": PROV + ["text", "fill_into_edit", "url", "contents",
                                 "description", "last_access_time", "number_of_hits"],
    "browser_credentials": PROV + ["origin_url", "action_url", "username_element",
                                   "username_value", "password_element",
                                   "password_encrypted_b64", "encryption_version",
                                   "signon_realm", "date_created", "date_last_used",
                                   "date_password_modified", "times_used", "blacklisted"],
    "browser_favicons": PROV + ["page_url", "icon_url", "icon_domain", "last_updated"],
    "browser_top_sites": PROV + ["url", "title", "url_rank"],
    "browser_metadata": ["browser", "vendor", "user_name", "sid", "profile",
                         "source_path", "version", "os_crypt_key_b64", "key_scheme",
                         "profile_created", "parsed_at"],
}


def _row(cols, **vals):
    return tuple(vals.get(c, "") for c in cols)


class TestBrowserBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication          # QObject needs one
        cls.app = QApplication.instance() or QApplication([])
        from visualizations.browser_bridge import BrowserBridge
        cls.BrowserBridge = BrowserBridge

        cls.tmp = tempfile.mkdtemp(prefix="browserviz_")
        con = sqlite3.connect(os.path.join(cls.tmp, "browser_analysis.db"))
        for t, cols in TABLES.items():
            con.execute('CREATE TABLE "%s" (%s)' % (t, ", ".join(cols)))

        def ins(t, **vals):
            cols = TABLES[t]
            con.execute('INSERT INTO "%s" VALUES (%s)' % (t, ",".join("?" * len(cols))),
                        _row(cols, **vals))

        chrome = dict(browser="Chrome", vendor="chromium", profile="Default")
        fox = dict(browser="Firefox", vendor="gecko", profile="default-release")

        # --- visits: two typed on day 1, one clicked on day 2 ------------------
        ins("browser_history", url="https://example.test/a", title="A",
            visit_time="2026-03-01 09:15:00", typed_count=2, transition="typed", **chrome)
        ins("browser_history", url="https://example.test/b", title="B",
            visit_time="2026-03-01 09:40:00", typed_count=0, transition="link", **chrome)
        ins("browser_history", url="https://other.test/x", title="X",
            visit_time="2026-03-02 14:05:00", typed_count=0, transition="link", **chrome)
        # Gecko, older column spelling
        ins("browser_gecko_history", url="https://mozilla.test/m", title="M",
            visit_time="2026-03-01 11:00:00", typed=1, visit_type="1", **fox)
        # A row with no event time can be placed on no chart and must be dropped.
        ins("browser_history", url="https://notime.test/", title="no time",
            visit_time="", typed_count=0, **chrome)

        # --- searches ----------------------------------------------------------
        ins("browser_shortcuts", text="example rep", url="https://example.test/a",
            number_of_hits=5, last_access_time="2026-03-01 09:14:00", **chrome)

        # --- downloads: one flagged dangerous ----------------------------------
        ins("browser_downloads", source_url="https://other.test/setup.exe",
            target_path="C:\\Users\\a\\Downloads\\setup.exe", received_bytes=1024,
            total_bytes=1024, start_time="2026-03-02 14:10:00", danger_type=2,
            opened=1, mime_type="application/x-msdownload", state=1, **chrome)

        # --- cookies: example.test has history; ghost.test does NOT ------------
        ins("browser_cookies", host_key=".example.test", name="sid",
            creation_time="2026-03-01 09:15:10", last_access_time="2026-03-01 09:41:00",
            expires_time="2027-03-01 00:00:00", is_secure=1, is_httponly=1,
            encrypted_value_b64="SECRET-MUST-NOT-APPEAR", encryption_version="v10", **chrome)
        ins("browser_gecko_cookies", host="ghost.test", name="gsid",
            creation_time="2026-03-03 08:00:00", last_accessed="2026-03-03 08:30:00",
            value="SECRET-MUST-NOT-APPEAR", **fox)

        # --- cache -------------------------------------------------------------
        ins("browser_cache", url="https://example.test/app.js",
            response_time="2026-03-01 09:16:00", http_status=200,
            content_type="text/javascript", content_length=4096,
            content_encoding="br", cache_format="blockfile", **chrome)
        ins("browser_cache", url="https://ghost.test/tracker.gif",
            response_time="2026-03-03 08:05:00", http_status=200,
            content_type="image/gif", content_length=43, cache_format="blockfile", **chrome)

        # --- a saved login (metadata only must come back) ----------------------
        ins("browser_credentials", origin_url="https://example.test/login",
            username_value="ann", password_encrypted_b64="SECRET-MUST-NOT-APPEAR",
            encryption_version="v10", date_created="2026-02-01 00:00:00",
            date_last_used="2026-03-01 09:15:00", times_used=3, blacklisted=0, **chrome)

        # --- survivors of a cleared history ------------------------------------
        ins("browser_favicons", page_url="https://ghost.test/", icon_url="https://ghost.test/f.ico",
            icon_domain="ghost.test", last_updated="2026-03-03 08:00:00", **chrome)
        ins("browser_top_sites", url="https://ghost.test/", title="Ghost", url_rank=1, **chrome)

        ins("browser_metadata", browser="Chrome", vendor="chromium", profile="Default",
            profile_created="2025-01-01 00:00:00", version="152.0.7977.83", parsed_at="")

        con.commit()
        con.close()
        cls.b = cls.BrowserBridge(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- domain normalisation ---------------------------------------------
    def test_domain_normalises_urls_and_cookie_hosts(self):
        """A cookie host and a URL for one site must land on the same string,
        or the detail panel joins nothing."""
        d = self.BrowserBridge._domain
        self.assertEqual(d("https://example.test/a?q=1"), "example.test")
        self.assertEqual(d(".example.test"), "example.test")
        self.assertEqual(d("http://user:pw@example.test:8443/x"), "example.test")
        self.assertEqual(d("HTTPS://Example.TEST/"), "example.test")
        self.assertEqual(d(""), "")

    # ---- bounds -------------------------------------------------------------
    def test_bounds(self):
        r = json.loads(self.b.getBrowserBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual(r["minDate"], "2026-03-01")
        self.assertEqual(r["maxDate"], "2026-03-03")
        # 4 timed Chromium+Gecko visits; the untimed row is not counted
        self.assertEqual(r["sources"]["visits"], 4)
        self.assertEqual(r["sources"]["downloads"], 1)
        # absent tables contribute nothing rather than raising
        self.assertEqual(r["sources"]["cache"], 2)
        self.assertIn("Chrome", r["browsers"])
        self.assertIn("Firefox", r["browsers"])

    def test_missing_db_is_reported_not_raised(self):
        empty = self.BrowserBridge(os.path.join(self.tmp, "nope"))
        r = json.loads(empty.getBrowserBounds())
        self.assertFalse(r["hasData"])
        self.assertEqual(r["reason"], "no_browser_db")
        # and every other slot degrades rather than throwing
        self.assertEqual(json.loads(empty.getBrowserHeatmaps("{}"))["combined"], [])

    # ---- heatmaps -----------------------------------------------------------
    def test_heatmaps(self):
        r = json.loads(self.b.getBrowserHeatmaps(json.dumps({})))
        visits = {d["day"]: d["value"] for d in r["sources"]["visits"]["days"]}
        self.assertEqual(visits["2026-03-01"], 3)     # 2 chromium + 1 gecko
        self.assertEqual(visits["2026-03-02"], 1)
        self.assertEqual(r["sources"]["visits"]["max"], 3)
        combined = {d["day"]: d["value"] for d in r["combined"]}
        self.assertEqual(combined["2026-03-02"], 1 + 1)   # visit + download

    def test_heatmaps_respect_range_and_search(self):
        r = json.loads(self.b.getBrowserHeatmaps(json.dumps(
            {"start": "2026-03-02", "end": "2026-03-02"})))
        days = {d["day"] for d in r["combined"]}
        self.assertEqual(days, {"2026-03-02"})
        r2 = json.loads(self.b.getBrowserHeatmaps(json.dumps({"terms": ["mozilla"]})))
        visits = {d["day"]: d["value"] for d in r2["sources"]["visits"]["days"]}
        self.assertEqual(visits, {"2026-03-01": 1})

    def test_browser_filter(self):
        # The strip carries every day in the range now, so the filter shows as
        # which day has the value rather than as which days are present at all.
        r = json.loads(self.b.getBrowserHeatmaps(json.dumps({"browser": "Firefox"})))
        visits = {d["day"]: d["value"] for d in r["sources"]["visits"]["days"]}
        self.assertEqual({d: v for d, v in visits.items() if v}, {"2026-03-01": 1})
        self.assertTrue(all(v == 0 for d, v in visits.items() if d != "2026-03-01"))

    # ---- overview -----------------------------------------------------------
    def test_overview_top_domains_split_typed_from_clicked(self):
        r = json.loads(self.b.getBrowserOverview(json.dumps({})))
        doms = {d["domain"]: d for d in r["topDomains"]}
        self.assertEqual(doms["example.test"]["visits"], 2)
        self.assertEqual(doms["example.test"]["typed"], 1)
        self.assertEqual(doms["example.test"]["clicked"], 1)
        # Gecko's older `typed` column must be read, not ignored
        self.assertEqual(doms["mozilla.test"]["typed"], 1)

    def test_overview_intent(self):
        r = json.loads(self.b.getBrowserOverview(json.dumps({})))
        terms = [t["text"] for t in r["intent"]["terms"]]
        self.assertIn("example rep", terms)
        typed = {u["url"] for u in r["intent"]["typedUrls"]}
        self.assertIn("https://example.test/a", typed)
        self.assertNotIn("https://example.test/b", typed)   # typed_count 0

    def test_overview_downloads(self):
        r = json.loads(self.b.getBrowserOverview(json.dumps({})))
        self.assertEqual(len(r["downloads"]), 1)
        d = r["downloads"][0]
        self.assertEqual(d["domain"], "other.test")
        self.assertEqual(d["dangerType"], 2)
        self.assertEqual(d["bytes"], 1024)

    def test_the_pruned_history_insight_finds_the_orphan(self):
        """ghost.test has a cookie, a favicon, a top site and a cache entry but
        no history row - which is the whole signal.

        This used to read `overview["antiForensics"]`. That card was folded into
        the Insights card, so the same computation is now reached through the
        insight it feeds, which is also the thing on screen.
        """
        r = json.loads(self.b.getBrowserOverview(json.dumps({})))
        pruned = r["insights"]["historyPruned"]
        names = {s["label"] for s in pruned["subjects"]}
        self.assertIn("ghost.test", names)
        self.assertNotIn("example.test", names)             # it has history
        # the subject opens the domain modal
        s = next(x for x in pruned["subjects"] if x["label"] == "ghost.test")
        self.assertEqual(s["open"], "ghost.test")
        for kind in ("cookie", "favicon", "top site", "cache"):
            self.assertIn(kind, s["note"])

    def test_a_single_artifact_is_not_enough_to_call_it_pruned(self):
        """A third-party cookie is set on domains the user never chose to
        visit, so one artifact is too weak to state: 82 of a real case's 106
        single-artifact orphans were exactly that. Two independent artifacts
        agreeing is the shape of a site that was used and then pruned."""
        r = json.loads(self.b.getBrowserOverview(json.dumps({})))
        for s in r["insights"]["historyPruned"]["subjects"]:
            kinds = [k for k in s["note"].split(" · ") if k]
            self.assertGreaterEqual(len(kinds), 2,
                                    "%s qualified on one artifact" % s["label"])

    def test_overview_totals(self):
        r = json.loads(self.b.getBrowserOverview(json.dumps({})))
        self.assertEqual(r["totals"]["activeDays"], 3)
        self.assertGreaterEqual(r["totals"]["domains"], 4)
        self.assertEqual(r["totals"]["browsers"], 2)

    # ---- day detail ---------------------------------------------------------
    def test_day_detail(self):
        r = json.loads(self.b.getBrowserDayDetail(json.dumps({"day": "2026-03-01"})))
        self.assertEqual(r["day"], "2026-03-01")
        self.assertEqual(len(r["hourly"]), 24)
        self.assertEqual(r["hourly"][9], 2 + 1 + 1 + 1)  # 2 visits, search, cookie, cache
        self.assertEqual(r["hourly"][11], 1)             # the gecko visit
        self.assertEqual(r["perSource"]["visits"], 3)
        self.assertEqual(len(r["hourlyBySource"]["visits"]), 24)
        top = {d["domain"]: d for d in r["topDomains"]}
        self.assertIn("example.test", top)

    def test_day_detail_without_a_day(self):
        r = json.loads(self.b.getBrowserDayDetail("{}"))
        self.assertEqual(r["hourly"], [0] * 24)
        self.assertEqual(r["events"], [])
        self.assertEqual(r["eventsTotal"], 0)

    # ---- the day's individual events ---------------------------------------
    def test_day_detail_carries_the_individual_events(self):
        r = json.loads(self.b.getBrowserDayDetail(json.dumps({"day": "2026-03-01"})))
        events = r["events"]
        # Every row the hour histogram counted is a row the list can show, so on
        # a day under the cap the two must agree - a list quietly shorter than
        # its own total is the failure this guards.
        self.assertEqual(r["eventsTotal"], sum(r["hourly"]))
        self.assertEqual(len(events), r["eventsTotal"])
        self.assertEqual([e["t"] for e in events],
                         sorted(e["t"] for e in events))
        for e in events:
            self.assertIn(e["activity"],
                          ("visits", "searches", "downloads", "cookies", "cache"))
            self.assertRegex(e["time"], r"^\d{2}:\d{2}:\d{2}$")
        by_activity = {}
        for e in events:
            by_activity[e["activity"]] = by_activity.get(e["activity"], 0) + 1
        self.assertEqual(by_activity["visits"], r["perSource"]["visits"])
        self.assertIn("example.test", {e["domain"] for e in events})

    def test_day_events_respect_the_filters(self):
        r = json.loads(self.b.getBrowserDayDetail(json.dumps(
            {"day": "2026-03-01", "browser": "Firefox"})))
        self.assertTrue(r["events"])
        self.assertEqual({e["browser"] for e in r["events"]}, {"Firefox"})

    def test_day_events_never_carry_a_secret(self):
        r = json.loads(self.b.getBrowserDayDetail(json.dumps({"day": "2026-03-01"})))
        blob = json.dumps(r["events"]).lower()
        for secret in ("password", "encrypted_b64", "cookie_value", "hunter2"):
            self.assertNotIn(secret, blob)
        for e in r["events"]:
            self.assertEqual(
                set(e) - {"t", "time", "activity", "domain", "label", "url",
                          "browser", "profile"}, set())

    def test_day_events_are_capped(self):
        from visualizations import browser_bridge as bb
        original = bb.DAY_EVENT_CAP
        bb.DAY_EVENT_CAP = 2
        # The day detail is cached per filter; an earlier test asked for the
        # same day under the real cap.
        self.b.clear_cache()
        try:
            r = json.loads(self.b.getBrowserDayDetail(json.dumps({"day": "2026-03-01"})))
        finally:
            bb.DAY_EVENT_CAP = original
        self.assertEqual(len(r["events"]), 2)
        # The total is still the truth, so the UI can say what it is hiding.
        self.assertEqual(r["eventsTotal"], sum(r["hourly"]))
        self.assertGreater(r["eventsTotal"], len(r["events"]))

    # ---- day activity (the bubble chart) ------------------------------------
    def test_day_activity(self):
        r = json.loads(self.b.getBrowserDayActivity(json.dumps({"day": "2026-03-01"})))
        self.assertIn("example.test", r["domains"])
        hours = {(p["domain"], p["activity"]): p["h"] for p in r["points"]}
        self.assertEqual(hours[("example.test", "visits")], 9)
        self.assertEqual(hours[("mozilla.test", "visits")], 11)
        self.assertEqual(r["ranges"]["example.test"]["min"], 9)

    def test_day_activity_respects_top_n(self):
        r = json.loads(self.b.getBrowserDayActivity(
            json.dumps({"day": "2026-03-01", "topN": 1})))
        self.assertEqual(len(r["domains"]), 1)

    # ---- domain detail ------------------------------------------------------
    def test_domain_detail_joins_every_table(self):
        r = json.loads(self.b.getBrowserDomainDetail(json.dumps({"domain": "example.test"})))
        self.assertTrue(r["hasData"])
        self.assertEqual(r["visitCount"], 2)
        self.assertEqual({c["name"] for c in r["cookies"]}, {"sid"})
        self.assertEqual(r["cache"][0]["status"], 200)
        self.assertEqual(r["cache"][0]["format"], "blockfile")
        self.assertEqual(len(r["credentials"]), 1)
        self.assertTrue(r["credentials"][0]["hasUsername"])
        self.assertEqual(r["credentials"][0]["timesUsed"], 3)

    def test_domain_detail_never_returns_a_secret(self):
        """The parser preserves ciphertext on purpose; a chart must not leak it."""
        for dom in ("example.test", "ghost.test", "other.test"):
            raw = self.b.getBrowserDomainDetail(json.dumps({"domain": dom}))
            self.assertNotIn("SECRET-MUST-NOT-APPEAR", raw)
            self.assertNotIn("password_encrypted", raw)
        every = self.b.getBrowserOverview(json.dumps({}))
        self.assertNotIn("SECRET-MUST-NOT-APPEAR", every)

    def test_domain_detail_does_not_match_a_substring_host(self):
        """`LIKE %example.test%` also matches evil-example.test.co, so the
        bridge re-checks the parsed domain rather than trusting the LIKE."""
        r = json.loads(self.b.getBrowserDomainDetail(json.dumps({"domain": "other.test"})))
        self.assertEqual(r["visitCount"], 1)
        self.assertEqual(len(r["downloads"]), 1)

    def test_domain_detail_without_a_domain(self):
        r = json.loads(self.b.getBrowserDomainDetail("{}"))
        self.assertFalse(r["hasData"])

    # ---- malformed input ----------------------------------------------------
    def test_malformed_args_do_not_raise(self):
        for bad in ("", "not json", "[]", "null"):
            self.assertIsInstance(json.loads(self.b.getBrowserHeatmaps(bad)), dict)
            self.assertIsInstance(json.loads(self.b.getBrowserOverview(bad)), dict)


if __name__ == "__main__":
    unittest.main()
