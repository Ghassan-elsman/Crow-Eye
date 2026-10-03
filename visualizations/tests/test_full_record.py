"""The raw row under a detail panel, and what it must never show.

A detail panel is hand-curated, so anything the parser stored but the panel
never learned about was invisible - and an analyst could not tell "this
artifact does not record that" from "this panel does not show it". Panels whose
record comes from ONE source row now carry that row verbatim underneath.

Two dashboards deliberately do not, and that is the interesting part:

* **shellitems** assembles an item from several registry tables (Shellbags,
  RecentDocs, OpenSaveMRU, TypedPaths), and
* **lnkjl** reaches a target through LNK_Files, Automatic_JumpLists,
  Custom_JumpLists and JLCE, often several records at once.

There is no single row to show, and inventing one would be less honest than the
curated view rather than more. Both name their source in the curated fields
instead. These tests pin that as a decision so nobody "fixes" it by picking an
arbitrary row.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

VIZ = os.path.join(ROOT, "visualizations")
# A real parsed case; set CROW_EYE_TEST_CASE to point elsewhere. Without one
# the case-backed tests skip.
CASE = os.environ.get("CROW_EYE_TEST_CASE") or os.path.join(
    os.path.expanduser("~"), "Downloads", "18.9.2026", "Target_Artifacts")


class WhatTheHelperWithholds(unittest.TestCase):
    """No case needed - this is the rule, not the data."""

    def test_a_secret_is_named_but_never_valued(self):
        """Dropping the column would hide that the row HAS a stored password,
        which is itself a finding. The value is not."""
        from visualizations.raw_record import raw_record
        row = {"origin_url": "x", "password_encrypted_b64": "shouldnotappear",
               "username_value": "alsonot", "times_used": 4}
        out = raw_record(row, "browser_credentials")
        by_name = {f["name"]: f for f in out["fields"]}
        for secret in ("password_encrypted_b64", "username_value"):
            self.assertIn(secret, by_name, "the column vanished instead of being withheld")
            self.assertTrue(by_name[secret]["withheld"])
            self.assertEqual(by_name[secret]["value"], "")
        self.assertFalse(by_name["times_used"]["withheld"])
        self.assertEqual(by_name["times_used"]["value"], "4")
        self.assertNotIn("shouldnotappear", json.dumps(out))
        self.assertNotIn("alsonot", json.dumps(out))

    def test_the_suffix_rule_catches_new_columns(self):
        """A parser adding `foo_encrypted_b64` must not have to be remembered."""
        from visualizations.raw_record import raw_record
        out = raw_record({"anything_encrypted_b64": "nope", "a_token": "nope"}, "t")
        self.assertTrue(all(f["withheld"] for f in out["fields"]))
        self.assertNotIn("nope", json.dumps(out))

    def test_parser_bookkeeping_is_dropped(self):
        """`parsed_at` is when Crow-Eye read the artifact, not when anything
        happened on the machine - it is noise in a detail panel.

        Asserted against the helper rather than a real table: `prefetch_data`
        happens not to carry the column at all, so a test that read a live row
        would pass whether the rule existed or not.
        """
        from visualizations.raw_record import raw_record
        out = raw_record({"path": "x", "parsed_at": "2026-09-18T00:00:00"}, "t")
        self.assertEqual([f["name"] for f in out["fields"]], ["path"])

    def test_an_empty_column_is_kept(self):
        """"This column exists and is blank" and "this column does not exist"
        are different facts, and only one of them is a parser bug."""
        from visualizations.raw_record import raw_record
        out = raw_record({"path": "", "size": None}, "t")
        self.assertEqual([f["name"] for f in out["fields"]], ["path", "size"])

    def test_a_huge_value_is_truncated_and_says_so(self):
        from visualizations.raw_record import raw_record
        out = raw_record({"blob": "x" * 9000}, "t")
        value = out["fields"][0]["value"]
        self.assertLess(len(value), 9000)
        self.assertIn("more characters", value)


class PanelsWithOneSourceRowCarryIt(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(CASE):
            raise unittest.SkipTest("no parsed case to read shapes from")

    def test_prefetch(self):
        from visualizations.prefetch_bridge import PrefetchBridge
        b = PrefetchBridge(CASE)
        ov = json.loads(b.getPrefetchOverview(json.dumps({})))
        fn = ov["topPrograms"][0]["filename"]
        raw = json.loads(b.getPrefetchProgramDetail(json.dumps({"filename": fn}))).get("raw")
        self.assertTrue(raw and raw["fields"], "no raw row behind the program panel")
        self.assertEqual(raw["table"], "prefetch_data")

    def test_mftusn(self):
        from visualizations.mftusn_bridge import MftUsnBridge
        b = MftUsnBridge(CASE)
        anom = json.loads(b.getMftUsnOverview(json.dumps({})))["anomalies"]
        subjects = anom["timestompCandidates"]["subjects"]
        if not subjects:
            self.skipTest("no timestomp candidates in this case")
        raw = json.loads(b.getMftUsnFileDetail(
            json.dumps({"rec": subjects[0]["open"]}))).get("raw")
        self.assertTrue(raw and raw["fields"], "no raw row behind the file panel")
        self.assertEqual(raw["table"], "mft_usn_correlated")



class EveryPanelCarriesTheRecordsBehindIt(unittest.TestCase):
    """The four that aggregate used to show only the curated reading.

    An earlier version of this file asserted the opposite - that shellitems and
    lnkjl deliberately returned no raw row. That was half right: an LNK target
    genuinely is reached through several artifacts at once, but a shell ITEM is
    one registry row, and the comment excusing it confused the dashboard (which
    reads Shellbags, RecentDocs, OpenSaveMRU, TypedPaths) with an item. Both now
    carry their records: one row where there is one row, the whole contributing
    set where there is not.
    """

    SINGLE_ROW = {
        "shellitems_bridge.py": "getShellItemsItemDetail",
        "prefetch_bridge.py": "getPrefetchProgramDetail",
        "mftusn_bridge.py": "getMftUsnFileDetail",
    }
    MANY_ROWS = {
        "lnkjl_bridge.py": "getLnkTargetDetail",
        "viz_bridge.py": "getSrumAppDetail",
        "browser_bridge.py": "getBrowserDomainDetail",
    }

    def _slot(self, name, slot):
        with open(os.path.join(VIZ, name), encoding="utf-8") as fh:
            src = fh.read()
        body = src[src.index("def %s" % slot):]
        mark = "\n    @pyqtSlot"
        return body[:body.index(mark)] if mark in body else body

    def test_a_single_row_panel_returns_that_row(self):
        for name, slot in self.SINGLE_ROW.items():
            self.assertIn('"raw"', self._slot(name, slot),
                          "%s: %s returns no source row" % (name, slot))

    def test_an_aggregate_panel_returns_all_of_them(self):
        for name, slot in self.MANY_ROWS.items():
            body = self._slot(name, slot)
            self.assertIn('"records"', body,
                          "%s: %s returns no source records" % (name, slot))

    def test_the_aggregates_do_not_fake_a_single_row(self):
        """Picking one of several contributing rows would be less honest than
        showing all of them, not more."""
        for name, slot in self.MANY_ROWS.items():
            self.assertNotIn('"raw":', self._slot(name, slot), name)

    def test_every_dashboard_renders_the_section(self):
        panels = {
            "react-prefetch": "ProgramDetailPanel.jsx",
            "react-mftusn": "FileDetailPanel.jsx",
            "react-shellitems": "ItemDetailPanel.jsx",
            "react-lnkjl": "TargetDetailPanel.jsx",
            "react-viz": "AppDetailPanel.jsx",
            "react-browser": "DomainDetailPanel.jsx",
        }
        for dash, panel in panels.items():
            with open(os.path.join(VIZ, dash, "src", panel), encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("<FullRecordSection", src, "%s/%s" % (dash, panel))
            # `detail` can be null while the modal loads - AppDetailPanel guards
            # on `!app`, not `!detail`, and a bare `detail.records` threw.
            self.assertNotRegex(src, r"<FullRecordSection \w+=\{detail\.",
                                "%s/%s: unguarded detail access" % (dash, panel))

    def test_the_component_is_byte_identical_across_the_six(self):
        seen = set()
        for dash in ("react-viz", "react-mftusn", "react-lnkjl",
                     "react-prefetch", "react-shellitems", "react-browser"):
            with open(os.path.join(VIZ, dash, "src", "FullRecordSection.jsx"),
                      encoding="utf-8") as fh:
                seen.add(fh.read())
        self.assertEqual(len(seen), 1, "FullRecordSection.jsx has diverged")

    def test_every_dashboard_styles_it(self):
        for dash in ("react-viz", "react-mftusn", "react-lnkjl",
                     "react-prefetch", "react-shellitems", "react-browser"):
            with open(os.path.join(VIZ, dash, "src", "styles.css"), encoding="utf-8") as fh:
                css = fh.read()
            # The exact rule, not the selector: `.fr-rec ` also appears inside
            # `.fr-rec .fr-list`, so a prefix check survives its removal.
            for rule in (".fr-head {", ".fr-list {", ".fr-row {", ".fr-rec {"):
                self.assertIn(rule, css, "%s has no %s rule" % (dash, rule))
            self.assertIn(".fr-list > * { flex-shrink: 0; }", css, dash)


class SourceRecordsNeverOverstateWhatItShows(unittest.TestCase):
    """`showing 40 of 600` where 600 was itself a LIMIT is still a wrong number."""

    def test_the_cap_is_applied_and_declared(self):
        from visualizations.raw_record import source_records, MAX_RECORDS
        out = source_records([{"a": i} for i in range(MAX_RECORDS + 5)], "t")
        self.assertEqual(len(out["records"]), MAX_RECORDS)
        self.assertEqual(out["total"], MAX_RECORDS + 5)
        self.assertTrue(out["truncated"])

    def test_an_exact_fit_is_not_marked_truncated(self):
        from visualizations.raw_record import source_records
        out = source_records([{"a": 1}], "t")
        self.assertEqual(out["total"], 1)
        self.assertFalse(out["truncated"])

    def test_a_caller_that_limited_its_own_query_passes_the_real_total(self):
        from visualizations.raw_record import source_records
        out = source_records([{"a": i} for i in range(5)], "t", cap=2, total=9999)
        self.assertEqual(out["total"], 9999)
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["records"]), 2)

    def test_the_two_aggregates_that_can_run_long_count_rather_than_infer(self):
        for name in ("viz_bridge.py", "browser_bridge.py"):
            with open(os.path.join(VIZ, name), encoding="utf-8") as fh:
                src = fh.read()
            # Scoped to the method: both bridges run COUNT(*) elsewhere, so a
            # file-wide check passes even with the counting removed from here.
            marker = ("def _app_source_records" if "viz" in name
                      else "def _domain_source_records")
            body = src[src.index(marker):]
            end = body.find("\n    def ", 1)
            if end > 0:
                body = body[:end]
            self.assertIn("SELECT COUNT(*) c", body,
                          "%s infers its total from the rows it fetched" % name)
            self.assertIn("total=total", body, name)

    def test_each_record_says_which_artifact_it_came_from(self):
        from visualizations.raw_record import source_records
        out = source_records([("t1", {"a": 1}), ("t2", {"b": 2})],
                             label_of=lambda it: it[0])
        self.assertEqual([r["label"] for r in out["records"]], ["t1", "t2"])
        self.assertEqual([r["table"] for r in out["records"]], ["t1", "t2"])

    def test_a_withheld_column_stays_withheld_in_a_list(self):
        from visualizations.raw_record import source_records
        out = source_records([{"url": "u", "encrypted_value_b64": "SECRET"}],
                             "browser_cookies")
        f = {x["name"]: x for x in out["records"][0]["fields"]}
        self.assertTrue(f["encrypted_value_b64"]["withheld"])
        self.assertEqual(f["encrypted_value_b64"]["value"], "")
        self.assertNotIn("SECRET", json.dumps(out))



if __name__ == "__main__":
    unittest.main()
