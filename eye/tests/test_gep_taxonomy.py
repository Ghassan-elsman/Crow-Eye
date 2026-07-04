"""
Guards the GEP model: the GEP is the vendor-neutral STANDARD (10 principles in
GEP_standard.md), and the Eye's system-prompt rules are OPERATING rules that
UPHOLD it (tagged [Operating] or [Operating · GEP-k]) — the rules are not
themselves "the GEP". Also guards the per-answer check ids.
"""

import json
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from eye.services.query_processor import QueryProcessor

_ROOT = Path(__file__).resolve().parents[2]
_CFG = _ROOT / "configs" / "llm_config.json"
_STD = _ROOT / "eye" / "docs" / "GEP_standard.md"


class TestGepStandardDoc(unittest.TestCase):
    def test_standard_exists_and_lists_10_principles(self):
        self.assertTrue(_STD.exists(), "GEP_standard.md (the vendor-neutral standard) is missing")
        text = _STD.read_text(encoding="utf-8")
        for n in range(1, 11):
            self.assertRegex(text, rf"GEP-{n}\b", f"GEP-{n} principle missing from the standard")
        # It must read as a tool-agnostic standard, not a Crow-Eye feature list.
        low = text.lower()
        self.assertIn("standard", low)
        self.assertTrue("vendor-neutral" in low or "tool-agnostic" in low)


class TestOperatingRulesUpholdGep(unittest.TestCase):
    def setUp(self):
        tmpl = json.loads(_CFG.read_text(encoding="utf-8"))["system_prompt_template"]
        start = next(i for i, l in enumerate(tmpl) if l.startswith("## OPERATING RULES"))
        self.rules = tmpl[start:]

    def _tag(self, prefix):
        line = next(r for r in self.rules if r.startswith(prefix))
        return re.match(r"^\d+\. \[([^\]]+)\]", line).group(1)

    def test_header_frames_rules_as_operating_not_gep(self):
        header = self.rules[0]
        self.assertIn("OPERATING RULES", header)
        self.assertIn("GEP_standard.md", header)
        self.assertIn("not the GEP", header)

    def test_every_rule_is_operating(self):
        numbered = [r for r in self.rules if re.match(r"^\d+\.\s", r)]
        self.assertTrue(numbered)
        for r in numbered:
            # Tag is always "Operating" or "Operating · GEP-k …" — never a bare GEP-n
            # (the rules uphold the GEP; they are not the GEP).
            self.assertRegex(r, r"^\d+\. \[Operating( · GEP-\d+(, GEP-\d+)*)?\] ",
                             f"rule not tagged as Operating(·GEP-k): {r[:60]}")

    def test_specific_citations(self):
        self.assertIn("GEP-1", self._tag("1. "))    # Evidence-only → Evidence Primacy
        self.assertIn("GEP-5", self._tag("26. "))   # Premise verification
        self.assertIn("GEP-7", self._tag("17. "))   # Dual output → Non-Repudiation/record
        self.assertEqual(self._tag("4. "), "Operating")   # action chips: pure UX, no principle
        self.assertEqual(self._tag("8. "), "Operating")   # no-placeholders: pure UX


class TestPerTurnChecks(unittest.TestCase):
    def test_check_ids_are_all_ten_principles(self):
        # Each answer is graded against ALL 10 GEP principles (N-A where a
        # principle doesn't apply to that turn).
        qp = QueryProcessor(MagicMock())
        rec = qp._evaluate_gep_turn("q", "a sufficiently long answer " * 3, [])
        ids = {c["id"] for c in rec["checks"]}
        self.assertEqual(ids, {f"GEP-{n}" for n in range(1, 11)})


class TestPerAnswerAllPrinciples(unittest.TestCase):
    def _qp(self):
        return QueryProcessor(MagicMock())

    @staticmethod
    def _c(rec, gid):
        return next(c for c in rec["checks"] if c["id"] == gid)

    def _evidence(self):
        return [{"tool_name": "query_database", "success": True,
                 "result": {"success": True, "database_name": "prefetch.db",
                            "sql_query": "SELECT 1", "data": [{"a": 1}], "row_count": 1}}]

    def test_gep2_traceability(self):
        rec = self._qp()._evaluate_gep_turn("q", "answer " * 20, self._evidence())
        self.assertEqual(self._c(rec, "GEP-2")["status"], "PASS")
        rec2 = self._qp()._evaluate_gep_turn("q", "answer " * 20, [])
        self.assertEqual(self._c(rec2, "GEP-2")["status"], "N-A")

    def test_gep4_cross_corroboration(self):
        ev = self._evidence()
        multi = self._qp()._evaluate_gep_turn("q", "a " * 20, ev,
                                              {"consulted": ["a.db", "b.db"], "not_consulted": [], "sampled": False})
        self.assertEqual(self._c(multi, "GEP-4")["status"], "PASS")
        single = self._qp()._evaluate_gep_turn("q", "a " * 20, ev,
                                               {"consulted": ["a.db"], "not_consulted": [], "sampled": False})
        self.assertEqual(self._c(single, "GEP-4")["status"], "PARTIAL")
        none = self._qp()._evaluate_gep_turn("q", "a " * 20, [], None)
        self.assertEqual(self._c(none, "GEP-4")["status"], "N-A")

    def test_gep5_premise_verification(self):
        done = self._qp()._evaluate_gep_turn("q", "a " * 20, [], None,
                                             [{"q": "verify: x", "kind": "premise", "status": "answered"}])
        self.assertEqual(self._c(done, "GEP-5")["status"], "PASS")
        unresolved = self._qp()._evaluate_gep_turn("q", "a " * 20, [], None,
                                                   [{"q": "verify: x", "kind": "premise", "status": "open"}])
        self.assertEqual(self._c(unresolved, "GEP-5")["status"], "FAIL")
        nopremise = self._qp()._evaluate_gep_turn("q", "a " * 20, [], None, [])
        self.assertEqual(self._c(nopremise, "GEP-5")["status"], "N-A")

    def test_gep8_transparency_and_gep9_authority(self):
        rec = self._qp()._evaluate_gep_turn("q", "a " * 20, self._evidence())
        self.assertEqual(self._c(rec, "GEP-8")["status"], "PASS")
        self.assertEqual(self._c(rec, "GEP-9")["status"], "N-A")  # read-only
        write = [{"tool_name": "correlation_create_wing", "success": True, "result": {"success": True}}]
        rec2 = self._qp()._evaluate_gep_turn("q", "a " * 20, write)
        self.assertEqual(self._c(rec2, "GEP-9")["status"], "PASS")


class TestGep6CoverageCheck(unittest.TestCase):
    def _qp(self):
        return QueryProcessor(MagicMock())

    @staticmethod
    def _g6(rec):
        return next(c for c in rec["checks"] if c["id"] == "GEP-6")

    def _evidence(self, extra=None):
        results = [{"tool_name": "query_database", "success": True, "result": {"success": True}}]
        if extra:
            results.append(extra)
        return results

    def test_na_on_conversational_turn(self):
        rec = self._qp()._evaluate_gep_turn("q", "answer " * 20, [], None)
        self.assertEqual(self._g6(rec)["status"], "N-A")

    def test_na_when_coverage_missing(self):
        rec = self._qp()._evaluate_gep_turn("q", "answer " * 20, self._evidence(), None)
        self.assertEqual(self._g6(rec)["status"], "N-A")

    def test_partial_when_sampled_without_full_analysis(self):
        coverage = {"consulted": ["prefetch.db"], "not_consulted": ["srum.db"], "sampled": True}
        rec = self._qp()._evaluate_gep_turn("q", "answer " * 20, self._evidence(), coverage)
        g6 = self._g6(rec)
        self.assertEqual(g6["status"], "PARTIAL")
        self.assertIn("SAMPLE", g6["detail"])
        self.assertIn("srum.db", g6["detail"])  # the gap is disclosed

    def test_pass_when_sampled_but_map_reduce_ran(self):
        coverage = {"consulted": ["prefetch.db"], "not_consulted": [], "sampled": True}
        mr = {"tool_name": "analyze_large_dataset", "success": True, "result": {"success": True}}
        rec = self._qp()._evaluate_gep_turn("q", "answer " * 20, self._evidence(mr), coverage)
        self.assertEqual(self._g6(rec)["status"], "PASS")

    def test_pass_when_fully_covered_no_sample(self):
        coverage = {"consulted": ["prefetch.db", "srum.db"], "not_consulted": [], "sampled": False}
        rec = self._qp()._evaluate_gep_turn("q", "answer " * 20, self._evidence(), coverage)
        g6 = self._g6(rec)
        self.assertEqual(g6["status"], "PASS")
        self.assertIn("consulted", g6["detail"])


class TestPerStepGepCoverage(unittest.TestCase):
    """Every forensic step must leave a GEP record. Guards the two steps that used
    to early-return before the per-turn evaluator: the deterministic triage and the
    post-switch context-analysis acknowledgement."""

    def _qp(self):
        return QueryProcessor(MagicMock())

    @staticmethod
    def _c(rec, gid):
        return next(c for c in rec["checks"] if c["id"] == gid)

    _EXPECTED = ["registry_data.db", "prefetch_data.db",
                 "mft_usn_correlated_analysis.db", "Log_Claw.db",
                 "recyclebin_analysis.db", "amcache.db", "shimcache.db",
                 "srum_data.db", "LnkDB.db"]

    def test_triage_record_grades_all_ten_and_passes_core_rules(self):
        consulted = ["registry_data.db", "Log_Claw.db", "prefetch_data.db", "srum_data.db"]
        rec = self._qp()._evaluate_gep_triage(
            consulted, self._EXPECTED, blocks_added=12,
            response="Automated Forensic Triage is complete and indexed into the report.")
        # All 10 principles present, identified as the triage step.
        self.assertEqual({c["id"] for c in rec["checks"]}, {f"GEP-{n}" for n in range(1, 11)})
        self.assertEqual(rec["query"], "initialize_case_report")
        for gid in ("GEP-1", "GEP-2", "GEP-7", "GEP-10", "GEP-4"):
            self.assertEqual(self._c(rec, gid)["status"], "PASS", gid)
        # Coverage discloses both consulted and the absent artifact DBs.
        g6 = self._c(rec, "GEP-6")
        self.assertEqual(g6["status"], "PASS")
        self.assertIn("registry_data.db", g6["detail"])
        self.assertIn("amcache.db", g6["detail"])  # not consulted → disclosed as NOT present
        # Triage asserts no premises and authors nothing durable.
        self.assertEqual(self._c(rec, "GEP-5")["status"], "N-A")
        self.assertEqual(self._c(rec, "GEP-9")["status"], "N-A")
        self.assertRegex(rec["summary"], r"^\d+/\d+ behavioral GEP rules PASS$")

    def test_degenerate_triage_makes_no_false_pass(self):
        # No DBs resolved and no blocks persisted → no fabricated evidence claims.
        rec = self._qp()._evaluate_gep_triage([], self._EXPECTED, 0, "Triage complete.")
        self.assertEqual(self._c(rec, "GEP-1")["status"], "N-A")
        self.assertEqual(self._c(rec, "GEP-2")["status"], "N-A")
        self.assertEqual(self._c(rec, "GEP-7")["status"], "N-A")
        self.assertEqual(self._c(rec, "GEP-4")["status"], "N-A")
        self.assertNotIn("PASS", {self._c(rec, g)["status"] for g in ("GEP-1", "GEP-2", "GEP-7")})

    def test_context_analysis_ack_grades_direct_answer_pass_rest_na(self):
        rec = self._qp()._evaluate_gep_turn(
            "analyze_case_context", "Reviewed the report workspace; ready to continue.", [])
        self.assertEqual(self._c(rec, "GEP-10")["status"], "PASS")
        for gid in ("GEP-1", "GEP-2", "GEP-3", "GEP-6", "GEP-7"):
            self.assertEqual(self._c(rec, gid)["status"], "N-A", gid)

    def test_refusal_records_defensibility_pass_and_never_fails(self):
        # A fail-hard refusal IS the GEP-mandated defensible action — it must be
        # recorded as GEP-10 PASS and must NEVER read as a compliance failure.
        rec = self._qp()._evaluate_gep_refusal("Find every event in 8 huge DBs", "context_overflow")
        self.assertEqual({c["id"] for c in rec["checks"]}, {f"GEP-{n}" for n in range(1, 11)})
        self.assertEqual(rec["query"], "Find every event in 8 huge DBs")
        self.assertEqual(self._c(rec, "GEP-10")["status"], "PASS")
        for gid in (f"GEP-{n}" for n in range(1, 10)):  # GEP-1..9 are N-A
            self.assertEqual(self._c(rec, gid)["status"], "N-A", gid)
        self.assertNotIn("FAIL", {c["status"] for c in rec["checks"]})
        self.assertEqual(rec["summary"], "1/1 behavioral GEP rules PASS")


if __name__ == "__main__":
    unittest.main()
