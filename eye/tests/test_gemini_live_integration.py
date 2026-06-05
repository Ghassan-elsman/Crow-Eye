"""
Live Gemini integration tests for the Eye context-adaptation + evidence-seal path.

These hit the REAL Gemini API, so they are skipped unless the API key is provided
via the ``GEMINI_LIVE_API_KEY`` environment variable. The key is never stored in
this file.

Run:
    # bash
    GEMINI_LIVE_API_KEY=... python -m unittest eye.tests.test_gemini_live_integration -v
    # PowerShell
    $env:GEMINI_LIVE_API_KEY="..."; python -m unittest eye.tests.test_gemini_live_integration -v

They verify, against a real model:
  1. ModelRouter routes to GeminiBackend, connectivity is valid, and a plain
     generate() returns text.
  2. A full QueryProcessor turn (with a forced context overflow) drives the
     self-heal ladder, calls the real model, and writes a hash-chained evidence
     seal whose cut_details carry the real dropped content + offsets + cut_range.
"""

import os
import json
import hashlib
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eye.services.model_router import ModelRouter
from eye.services.query_processor import QueryProcessor
from eye.services.evidence_seal import EvidenceSeal
from eye.services.truncation_auditor import TruncationAuditor
from eye.services.token_counter import TokenCounter

API_KEY = os.environ.get("GEMINI_LIVE_API_KEY")


class _StubCredentialManager:
    """Minimal stand-in matching CredentialManager.get_credential()."""
    def __init__(self, gemini_api_key):
        self._key = gemini_api_key

    def get_credential(self, key, timeout: float = 2.0):
        return self._key if key == "gemini_api_key" else None


def _pick_model(router) -> str:
    """Prefer a cheap model that has free-tier quota; fall back sensibly.

    On the test account gemini-2.5-flash(-lite) carry free quota while
    gemini-2.0-* are limit-0, so the 2.5 variants are tried first by exact name.
    """
    try:
        models = router.list_models() or []
    except Exception:
        models = []
    for pref in ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"):
        if pref in models:
            return pref
    for sub in ("flash-lite", "flash"):
        for m in models:
            if sub in m:
                return m
    return models[0] if models else "gemini-2.5-flash"


@unittest.skipUnless(API_KEY, "Set GEMINI_LIVE_API_KEY to run live Gemini tests")
class TestGeminiLiveRouting(unittest.TestCase):
    def setUp(self):
        self.cred = _StubCredentialManager(API_KEY)

    def _router(self, model_name="gemini-2.5-flash"):
        return ModelRouter(
            {"backend": "gemini", "model_name": model_name, "integration_type": "cloud_api"},
            credential_manager=self.cred,
        )

    def test_connectivity_and_model_discovery(self):
        router = self._router()
        self.assertTrue(router.validate_connectivity(), "Gemini connectivity failed — bad key or network")
        models = router.list_models()
        self.assertTrue(len(models) > 0, "No Gemini models discovered")
        print(f"\n[live] discovered {len(models)} models, e.g. {models[:5]}")

    def test_basic_generate(self):
        router = self._router(_pick_model(self._router()))
        resp = router.generate(
            system_prompt="You are a terse forensic assistant. Answer in one short sentence.",
            user_message="Reply with exactly the word: ACKNOWLEDGED",
            tools=None,
            history=None,
        )
        self.assertIn("content", resp)
        self.assertTrue(len(resp["content"].strip()) > 0, "Empty content from Gemini")
        print(f"\n[live] model said: {resp['content'].strip()[:120]!r}")


@unittest.skipUnless(API_KEY, "Set GEMINI_LIVE_API_KEY to run live Gemini tests")
class TestGeminiLiveSealEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cred = _StubCredentialManager(API_KEY)

        # Discover a real model once.
        probe = ModelRouter(
            {"backend": "gemini", "model_name": "gemini-2.5-flash", "integration_type": "cloud_api"},
            credential_manager=self.cred,
        )
        self.model_name = _pick_model(probe)

        # ContextManager mock — every service is mocked EXCEPT model_router,
        # which is the real Gemini-backed router so the final generate() is live.
        self.cm = MagicMock()
        self.cm.case_directory = self.temp_dir
        self.cm.truncation_auditor = TruncationAuditor(self.temp_dir)
        self.cm.token_counter = TokenCounter(backend="gpt-4")
        self.cm.max_total_tokens = 800   # small window -> force self-heal
        self.cm.token_budget = {
            "conversation_history": 300, "system_prompt": 200,
            "rag_context": 100, "tool_results": 200,
        }
        self.cm.history_manager = MagicMock()
        self.cm.history_manager.history = []
        self.cm.history_manager.pop_last_message.return_value = None
        # Deterministic, offline summary so the self-heal summarize step doesn't
        # add cost/nondeterminism; the FINAL synthesis call is the live one.
        self.cm.history_manager._summarize_chunk = MagicMock(return_value="Summary of older context.")
        self.cm.intent_engine = MagicMock()
        self.cm.intent_engine.detect_keywords.return_value = []
        self.cm.rag_service = MagicMock()
        self.cm.rag_service.retrieve_context.return_value = ""
        self.cm.report_engine = MagicMock()
        self.cm.report_engine.get_report_json.return_value = {"metadata": {"block_count": 0, "last_modified": ""}}
        self.cm._build_system_prompt.return_value = "You are EYE, a terse forensic assistant."
        self.cm._get_tool_definitions.return_value = []
        self.cm._parse_tool_calls.return_value = []

        # The real router.
        self.cm.model_router = ModelRouter(
            {"backend": "gemini", "model_name": self.model_name, "integration_type": "cloud_api"},
            credential_manager=self.cred,
        )

        self.processor = QueryProcessor(self.cm)

    def tearDown(self):
        # Flush and disarm the auditor before removing the dir so its __del__
        # doesn't try (and fail) to write into a deleted path during GC.
        try:
            self.cm.truncation_auditor._flush_buffer()
        except Exception:
            pass
        self.cm.truncation_auditor.buffer = []
        self.cm.truncation_auditor.failed_writes_buffer = []
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("time.sleep", return_value=None)
    def test_live_turn_writes_chained_seal_with_real_cut_details(self, _sleep):
        # Long, droppable history to force the self-heal ladder.
        self.cm.history_manager.history = [
            {"id": f"h{i}", "role": ("user" if i % 2 == 0 else "assistant"),
             "content": (f"Older forensic note {i}: record_number {1000+i} at "
                         f"computed_file_offset {(1000+i)*1024}. " * 12),
             "metadata": {}}
            for i in range(6)
        ]

        result = self.processor.process_query("In one sentence, what is an MFT record number?")

        # A real model answer came back.
        self.assertTrue(result is not None)
        print(f"\n[live] model used: {self.model_name}")

        # The evidence seal was written.
        seal_path = Path(self.temp_dir) / "EYE_Logs" / "eye_payload_seal.jsonl"
        self.assertTrue(seal_path.exists(), "No evidence seal written")
        seals = [json.loads(l) for l in seal_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(len(seals) > 0)

        # The hash chain verifies end-to-end (same logic as eye_bridge).
        prev = ""
        for s in seals:
            expected = hashlib.sha256(
                (prev + s["payload_sha256"] + s["metadata_sha256"]).encode("utf-8", errors="replace")
            ).hexdigest()
            self.assertEqual(s["prev_seal_hash"], prev)
            self.assertEqual(s["seal_hash"], expected)
            prev = s["seal_hash"]

        # At least one seal recorded real cut_details with the new schema.
        all_cuts = [c for s in seals for c in s.get("cut_details", [])]
        self.assertTrue(len(all_cuts) > 0, "Context overflow did not produce any cut_details")
        sample = all_cuts[0]
        self.assertIn(sample["action"], ("SUMMARIZED", "TRUNCATED", "TRUNCATED_TOOL_OUTPUT"))
        self.assertIn("cut_range", sample)
        self.assertIn("dropped_file_offsets", sample)
        # The dropped notes contained record numbers -> forensic offsets captured.
        has_offsets = any(c.get("dropped_file_offsets") for c in all_cuts)
        self.assertTrue(has_offsets, "Expected dropped_file_offsets from the dropped notes")
        print(f"\n[live] {len(all_cuts)} cut_detail(s); sample action={sample['action']} "
              f"range={sample.get('cut_range')}")


@unittest.skipUnless(API_KEY, "Set GEMINI_LIVE_API_KEY to run live Gemini tests")
class TestGeminiLiveGEPProtocol(unittest.TestCase):
    """Drive the REAL Eye (real ContextManager + real Gemini) through one query,
    then confirm the Ghassan Elsman Protocol (GEP) is actually applied and
    evaluated — both the live per-rule compliance state and the per-answer
    behavioral evaluation that the Eye persists for each turn."""

    def setUp(self):
        # Heavy imports kept local so the offline skip path never loads PyQt.
        from PyQt5.QtCore import QCoreApplication
        from eye.services.context_manager import ContextManager
        from eye.services.database_service import ForensicDatabaseService
        from eye.services.search_service import ForensicSearchService
        from eye.services.rag_service import RAGService
        from eye.services.report_engine import ReportEngine
        from eye.services.case_context_manager import CaseContextManager
        from eye.bridge.eye_bridge import EYEBridge

        # A QObject (EYEBridge) needs a Qt application object to exist.
        self._app = QCoreApplication.instance() or QCoreApplication([])

        self.temp_dir = tempfile.mkdtemp()
        self.cred = _StubCredentialManager(API_KEY)

        probe = ModelRouter(
            {"backend": "gemini", "model_name": "gemini-2.5-flash", "integration_type": "cloud_api"},
            credential_manager=self.cred,
        )
        self.model_name = _pick_model(probe)

        config = {"backend": "gemini", "model_name": self.model_name, "integration_type": "cloud_api"}
        router = ModelRouter(config, credential_manager=self.cred)

        # Real services wired exactly like eye_window._init_services().
        db = ForensicDatabaseService(self.temp_dir)
        search = ForensicSearchService(self.temp_dir)
        rag = RAGService()
        report = ReportEngine(self.temp_dir)
        ccm = CaseContextManager(self.temp_dir)

        self.cm = ContextManager(
            model_router=router,
            database_service=db,
            search_service=search,
            rag_service=rag,
            report_engine=report,
            case_directory=self.temp_dir,
            case_context_manager=ccm,
        )
        self.bridge = EYEBridge(context_manager=self.cm)

    def tearDown(self):
        try:
            if getattr(self.cm, "truncation_auditor", None):
                self.cm.truncation_auditor._flush_buffer()
                self.cm.truncation_auditor.buffer = []
                self.cm.truncation_auditor.failed_writes_buffer = []
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _rule(self, rules, rule_id):
        return next((r for r in rules if r.get("id") == rule_id), None)

    @patch("time.sleep", return_value=None)
    def test_gep_protocol_applied_on_live_query(self, _sleep):
        # A conceptual forensic question — answerable directly, so the turn does
        # not depend on any case database being populated.
        res = self.cm.process_query(
            "In two sentences, explain what a Windows Prefetch artifact reveals "
            "during a forensic investigation."
        )
        self.assertTrue(res is not None)
        print(f"\n[live][GEP] model: {self.model_name}")

        # ---- (1) Live per-rule GEP compliance state, via the real bridge -----
        status = json.loads(self.bridge.get_gep_compliance_status())
        self.assertTrue(status.get("success"), f"GEP status error: {status.get('error')}")
        rules = status["data"]["rules"]
        # All 11 GEP rules (0..10) are evaluated.
        self.assertEqual(sorted(r["id"] for r in rules), list(range(11)))
        valid = {"PASS", "PARTIAL", "FAIL", "N-A"}
        for r in rules:
            self.assertIn(r["status"], valid, f"rule {r['id']} bad status {r['status']}")

        # Rule 1 — Pre-Flight Integrity: the live Gemini backend must be reachable.
        r1 = self._rule(rules, 1)
        self.assertEqual(r1["status"], "PASS", f"Pre-flight ping not PASS: {r1}")

        # Rule 4 — Non-Repudiation: after a real turn, history message IDs are
        # the 16-char SHA chain IDs the protocol mandates.
        r4 = self._rule(rules, 4)
        self.assertEqual(r4["status"], "PASS", f"Hash-linked IDs not PASS: {r4}")
        print("[live][GEP] per-rule status: " + ", ".join(f"{r['id']}:{r['status']}" for r in rules))

        # ---- (2) Per-answer behavioral GEP, persisted by the Eye itself ------
        turns = json.loads(self.bridge.get_gep_turns())
        self.assertTrue(turns.get("success"))
        self.assertGreaterEqual(turns["data"]["total_turns"], 1,
                                "Eye did not persist a per-answer GEP evaluation")
        last = turns["data"]["turns"][-1]
        self.assertIn("checks", last)
        r13 = next((c for c in last["checks"] if c.get("id") == 13), None)
        self.assertIsNotNone(r13, "Direct Answer (R13) check missing from GEP turn")
        self.assertEqual(r13["status"], "PASS", f"Direct Answer not PASS: {r13}")
        print(f"[live][GEP] turn summary: {last.get('summary')}")


if __name__ == "__main__":
    unittest.main()
