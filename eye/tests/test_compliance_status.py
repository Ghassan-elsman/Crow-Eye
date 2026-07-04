"""
Tests for the comprehensive Eye compliance dashboard
(EYEBridge.get_gep_compliance_status): every rule tagged with the GEP principle
it upholds, the new Eye-process rows present, and a full GEP-1..10 principle map.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from eye.bridge.eye_bridge import EYEBridge
from eye.services.evidence_seal import EvidenceSeal
from eye.services.truncation_auditor import TruncationAuditor


def _bridge(**cm_attrs):
    b = EYEBridge.__new__(EYEBridge)  # skip QObject.__init__; method only uses context_manager
    cm = MagicMock()
    cm.reasoning_config = {"history_window_turns": 5, "enable_summary_buffer": True}
    cm.evidence_index_service.available.return_value = False
    cm.logs_dir = None
    cm.case_directory = None
    for k, v in cm_attrs.items():
        setattr(cm, k, v)
    b.context_manager = cm
    return b


class TestComplianceStatus(unittest.TestCase):
    def _data(self):
        out = json.loads(_bridge().get_gep_compliance_status())
        self.assertTrue(out["success"], out)
        return out["data"]

    def test_every_rule_tagged_with_gep(self):
        rules = self._data()["rules"]
        self.assertTrue(rules)
        for r in rules:
            self.assertIsInstance(r.get("gep"), list)
            self.assertTrue(r["gep"], f"rule '{r.get('name')}' has no GEP tag")
            for g in r["gep"]:
                self.assertRegex(g, r"^GEP-\d+$")

    def test_new_process_rows_present(self):
        names = {r["name"] for r in self._data()["rules"]}
        for nm in ["Conversation Memory (2-Stage)", "Conversation Recall (Long-Term Memory)",
                   "Completeness & Coverage", "Result Cache (Reproducible Reuse)",
                   "Semantic Search (Embeddings)", "Evidence Seal Hash Chain"]:
            self.assertIn(nm, names)

    def test_full_gep_principle_map(self):
        principles = self._data()["gep_principles"]
        self.assertEqual([p["id"] for p in principles], [f"GEP-{n}" for n in range(1, 11)])
        for p in principles:
            self.assertIn(p["status"], ("PASS", "PARTIAL", "FAIL", "N-A"))
            self.assertTrue(p["name"])
            self.assertIsInstance(p["upheld_by"], list)

    def test_principle_rollup_reflects_a_failing_mechanism(self):
        # Force the evidence-seal writer to be absent -> seal row FAIL -> GEP-7 FAIL.
        out = json.loads(_bridge(evidence_seal=None).get_gep_compliance_status())
        principles = {p["id"]: p for p in out["data"]["gep_principles"]}
        self.assertEqual(principles["GEP-7"]["status"], "FAIL")

    def test_every_principle_has_a_basis(self):
        for p in self._data()["gep_principles"]:
            self.assertIn(p["basis"], ("verified", "structural", "config", "per-answer"))


class TestComplianceActuallyVerifies(unittest.TestCase):
    """Integration: the dashboard VERIFIES the hash chains (not just file
    existence), so tampering flips the relevant rows + GEP-7 to FAIL."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.logs = os.path.join(self.dir, "EYE_Logs")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _cm(self, seal, auditor):
        cm = MagicMock()
        cm.reasoning_config = {"history_window_turns": 5, "enable_summary_buffer": True,
                               "enable_decomposition": True, "enable_premise_verification": True}
        cm.evidence_index_service.available.return_value = False
        cm.evidence_seal = seal
        cm.truncation_auditor = auditor
        cm.logs_dir = self.logs
        cm.case_directory = self.dir
        return cm

    def _status(self, cm):
        b = EYEBridge.__new__(EYEBridge)
        b.context_manager = cm
        return json.loads(b.get_gep_compliance_status())["data"]

    def test_intact_chains_pass(self):
        seal = EvidenceSeal(self.dir)
        seal.seal(payload_text="p1", phase="request", iteration=1, query="q",
                  model="m", max_context=8192, token_count=10)
        auditor = TruncationAuditor(self.dir)
        auditor.log_event(action="PINNED", message_id="m", token_count=1,
                          reason="manual", message_hash="h", metadata={})
        data = self._status(self._cm(seal, auditor))
        rules = {r["name"]: r for r in data["rules"]}
        self.assertEqual(rules["Evidence Seal Hash Chain"]["status"], "PASS")
        self.assertIn("VERIFIED", rules["Evidence Seal Hash Chain"]["detail"])
        self.assertEqual(rules["Chain of Custody (Audit Trail)"]["status"], "PASS")
        self.assertIn("VERIFIED", rules["Chain of Custody (Audit Trail)"]["detail"])

    def test_tampered_seal_fails_seal_row_and_gep7(self):
        seal = EvidenceSeal(self.dir)
        for i in range(2):
            seal.seal(payload_text=f"p{i}", phase="request", iteration=i, query="q",
                      model="m", max_context=8192, token_count=10)
        log = os.path.join(self.logs, "eye_payload_seal.jsonl")
        with open(log, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        rec = json.loads(lines[0]); rec["payload_sha256"] = "0" * 64; lines[0] = json.dumps(rec)
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        data = self._status(self._cm(seal, TruncationAuditor(self.dir)))
        rules = {r["name"]: r for r in data["rules"]}
        self.assertEqual(rules["Evidence Seal Hash Chain"]["status"], "FAIL")
        self.assertIn("BROKEN", rules["Evidence Seal Hash Chain"]["detail"])
        principles = {p["id"]: p for p in data["gep_principles"]}
        self.assertEqual(principles["GEP-7"]["status"], "FAIL")

    def test_premise_verification_disabled_gep5_not_pass(self):
        cm = self._cm(EvidenceSeal(self.dir), TruncationAuditor(self.dir))
        cm.reasoning_config = {"enable_premise_verification": False, "enable_decomposition": True}
        g5 = {p["id"]: p for p in self._status(cm)["gep_principles"]}["GEP-5"]
        self.assertEqual(g5["basis"], "config")
        self.assertNotEqual(g5["status"], "PASS")
        self.assertIn("enable_premise_verification", g5["detail"])


if __name__ == "__main__":
    unittest.main()
