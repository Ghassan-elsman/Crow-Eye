"""
Hierarchical plan-driven investigation: Verdict → Narrative → Sub-narrative.

Covers the planner/parser, the focus message, the SUBVERDICT parse, and an
end-to-end run through `process_query` where a text-only (Gemma-style) model is
driven through a 2-narrative plan — asserting the seeded Narrative Map nodes flip
(proven / negative) WITHOUT duplicates and the verdict lifecycle ends `proven`.
"""

import json
import logging
import shutil
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from eye.services.query_processor import QueryProcessor
from eye.services.narrative_map_service import NarrativeMapService
from eye.services.evidence_seal import EvidenceSeal
from eye.services.token_counter import TokenCounter
from eye.services.truncation_auditor import TruncationAuditor


def _qp():
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.logger = logging.getLogger("test-hier")
    return qp


class TestParseHierarchy(unittest.TestCase):
    def setUp(self):
        self.valid = {"query_database", "get_schema", "query_correlation_results"}

    def test_normalizes_full_hierarchy(self):
        raw = json.dumps({
            "verdict": "x.exe is malicious",
            "narratives": [
                {"claim": "x.exe established persistence", "why": "survives reboot",
                 "sub_narratives": [
                     {"claim": "wrote a Run key", "evidence_needed": "HKCU Run value",
                      "tools": ["query_database", "bogus_tool"]},
                 ]},
            ],
        })
        plan = QueryProcessor._parse_hierarchy(raw, self.valid)
        self.assertEqual(plan["verdict"], "x.exe is malicious")
        self.assertEqual(len(plan["narratives"]), 1)
        sub = plan["narratives"][0]["sub_narratives"][0]
        self.assertEqual(sub["claim"], "wrote a Run key")
        self.assertEqual(sub["tools"], ["query_database"])  # bogus tool clamped out

    def test_bad_json_returns_none(self):
        self.assertIsNone(QueryProcessor._parse_hierarchy("not json", self.valid))
        self.assertIsNone(QueryProcessor._parse_hierarchy("", self.valid))

    def test_narrative_without_subs_dropped(self):
        raw = json.dumps({"verdict": "v", "narratives": [{"claim": "n", "sub_narratives": []}]})
        self.assertIsNone(QueryProcessor._parse_hierarchy(raw, self.valid))

    def test_caps_enforced(self):
        raw = json.dumps({"verdict": "v", "narratives": [
            {"claim": f"n{i}", "sub_narratives": [{"claim": f"s{i}", "tools": []}]}
            for i in range(10)
        ]})
        plan = QueryProcessor._parse_hierarchy(raw, self.valid, max_nar=3)
        self.assertEqual(len(plan["narratives"]), 3)


class TestSubverdictParse(unittest.TestCase):
    def test_proven(self):
        v, r = QueryProcessor._parse_subverdict("Found it.\nSUBVERDICT: PROVEN || HKCU Run has x.exe")
        self.assertEqual(v, "PROVEN")
        self.assertIn("HKCU", r)

    def test_not_proven_variants(self):
        for line in ("SUBVERDICT: NOT-PROVEN || nothing", "SUBVERDICT: NOT PROVEN || nothing"):
            v, _ = QueryProcessor._parse_subverdict(line)
            self.assertEqual(v, "NOT-PROVEN")

    def test_no_marker(self):
        v, r = QueryProcessor._parse_subverdict("Still working on it.")
        self.assertIsNone(v)

    def test_lenient_decorated_and_bare_forms(self):
        # Decorated markers real models tend to emit.
        for line in ("**SUBVERDICT: PROVEN** || ev", "SUB-VERDICT: PROVEN", "**SUBVERDICT** PROVEN"):
            v, _ = QueryProcessor._parse_subverdict(line)
            self.assertEqual(v, "PROVEN", line)
        # Bare trailing conclusion lines (no marker word).
        self.assertEqual(QueryProcessor._parse_subverdict("...\nPROVEN")[0], "PROVEN")
        self.assertEqual(QueryProcessor._parse_subverdict("...\nNOT PROVEN")[0], "NOT-PROVEN")


class TestResolveByEvidence(unittest.TestCase):
    def setUp(self):
        self.qp = _qp()
        self.step = {"claim": "wrote a Run key", "evidence_needed": "HKCU Run value"}

    def test_proven_when_relevant_success_with_data(self):
        results = [{"tool_name": "query_database", "success": True,
                    "result": {"data": [{"v": "HKCU Run key x.exe persistence"}]}}]
        v, _ = self.qp._resolve_by_evidence(self.step, results)
        self.assertEqual(v, "PROVEN")

    def test_not_proven_when_no_success(self):
        results = [{"tool_name": "query_database", "success": False, "result": {"success": False}}]
        v, _ = self.qp._resolve_by_evidence(self.step, results)
        self.assertEqual(v, "NOT-PROVEN")

    def test_not_proven_when_empty_results(self):
        v, _ = self.qp._resolve_by_evidence(self.step, [])
        self.assertEqual(v, "NOT-PROVEN")


class TestFocusBlock(unittest.TestCase):
    def test_shows_only_current_step(self):
        qp = _qp()
        plan = {"verdict": "x is bad", "narratives": [
            {"claim": "N1", "sub_narratives": [{"claim": "S1a"}, {"claim": "S1b"}]},
            {"claim": "N2", "sub_narratives": [{"claim": "S2a"}]},
        ]}
        steps = [
            {"nar_index": 0, "nar": plan["narratives"][0], "sub_index": 0,
             "claim": "S1a", "evidence_needed": "ev", "tools": ["query_database"]},
            {"nar_index": 1, "nar": plan["narratives"][1], "sub_index": 0,
             "claim": "S2a", "evidence_needed": "ev2", "tools": []},
        ]
        block = qp._build_focus_block(plan, steps, 0)
        self.assertIn("S1a", block)
        self.assertIn("query_database", block)
        self.assertIn("SUBVERDICT", block)
        self.assertNotIn("S2a", block)  # only the current step is shown


class TestArtifactCatalog(unittest.TestCase):
    def test_catalog_covers_core_artifacts(self):
        names = [n for n, _ in QueryProcessor.ARTIFACT_CATALOG]
        for a in ("Prefetch", "Registry", "AmCache", "ShimCache", "MFT", "USN Journal",
                  "Recycle Bin", "SRUM", "Event Logs", "Jump Lists & LNK"):
            self.assertIn(a, names)

    def test_catalog_block_renders(self):
        block = QueryProcessor._artifact_catalog_block()
        self.assertIn("Prefetch", block)
        self.assertIn("SRUM", block)
        self.assertIn("ShellBags", block)  # noted under Registry

    def test_focus_block_has_artifact_hint(self):
        qp = _qp()
        plan = {"verdict": "v", "narratives": [
            {"claim": "N1", "sub_narratives": [{"claim": "S1"}]}]}
        steps = [{"nar_index": 0, "nar": plan["narratives"][0], "sub_index": 0,
                  "claim": "S1", "evidence_needed": "ev", "tools": ["query_database"]}]
        block = qp._build_focus_block(plan, steps, 0)
        self.assertIn("Prefetch", block)  # artifact reminder present


class TestPlanPersistResume(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.qp = QueryProcessor.__new__(QueryProcessor)
        self.qp.logger = logging.getLogger("test-resume")
        self.qp.cm = types.SimpleNamespace(case_directory=self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _plan(self):
        return {
            "user_query": "is x.exe malicious?",
            "verdict": "x.exe is malicious",
            "narratives": [
                {"claim": "N1", "id": "n_a", "sub_narratives": [
                    {"claim": "S1", "evidence_needed": "e", "tools": ["query_database"],
                     "id": "s_a", "status": "proven"},
                    {"claim": "S2", "evidence_needed": "e", "tools": [], "id": "s_b", "status": "open"},
                ]},
            ],
        }

    def test_save_load_clear_round_trip(self):
        self.qp._save_active_plan(self._plan(), 1, "is x.exe malicious?")
        loaded = self.qp._load_active_plan()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["focus_idx"], 1)
        self.assertEqual(loaded["narratives"][0]["sub_narratives"][0]["status"], "proven")
        self.qp._clear_active_plan()
        self.assertIsNone(self.qp._load_active_plan())

    def test_rebuild_plan_steps_preserves_status_and_ids(self):
        steps = self.qp._rebuild_plan_steps(self._plan())
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["sub_id"], "s_a")
        self.assertEqual(steps[0]["sub"]["status"], "proven")
        self.assertTrue(steps[1]["is_last_in_nar"])
        # Focus resumes at the first still-open step.
        focus = next(k for k, s in enumerate(steps) if s["sub"].get("status") == "open")
        self.assertEqual(focus, 1)

    def test_continuation_detection(self):
        self.assertTrue(QueryProcessor._is_continuation_query("continue", "hunt telemetry"))
        self.assertTrue(QueryProcessor._is_continuation_query("keep going", "x"))
        self.assertTrue(QueryProcessor._is_continuation_query("", "x"))
        self.assertFalse(QueryProcessor._is_continuation_query(
            "now check the registry for a totally different thing", "hunt telemetry"))


class TestHierarchyEndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.nms = NarrativeMapService(self.dir, model_name="gemma-test")
        self.cm = MagicMock()
        self.cm.case_directory = self.dir
        self.cm.narrative_map_service = self.nms
        self.cm.truncation_auditor = TruncationAuditor(self.dir)
        self.cm.evidence_seal = EvidenceSeal(self.dir)
        self.cm.token_counter = TokenCounter(backend="gpt-4")
        self.cm.max_total_tokens = 200000
        self.cm.token_budget = {"conversation_history": 80000, "system_prompt": 40000,
                                "rag_context": 20000, "tool_results": 40000}
        self.cm.history_manager = MagicMock()
        self.cm.history_manager.history = []
        self.cm.history_manager.pop_last_message.return_value = None
        self.cm.intent_engine = MagicMock()
        self.cm.intent_engine.detect_keywords.return_value = []
        self.cm.rag_service = MagicMock()
        self.cm.rag_service.retrieve_context.return_value = ""
        self.cm.rag_service.last_sources = []
        self.cm._focus_narrative_id = None  # not a "Dive deeper" run
        self.cm.model_router = MagicMock()
        self.cm.model_router.config = {"model_name": "gemma-test"}
        self.cm.report_engine = MagicMock()
        self.cm.report_engine.get_report_json.return_value = {"metadata": {"block_count": 0, "last_modified": ""}}
        self.cm._build_system_prompt.return_value = "SYS"
        self.cm._get_tool_definitions.return_value = [
            {"name": "query_database", "parameters": {"properties": {"database_name": {}, "sql_query": {}}}},
        ]
        self.cm._parse_tool_calls.side_effect = self._parse
        self.cm._execute_tool.return_value = {
            "tool_name": "query_database", "success": True,
            "parameters": {"database_name": "reg.db", "sql_query": "SELECT 1"},
            "result": {"columns": ["v"], "data": [{"v": "run key persistence x.exe"}], "row_count": 1},
        }
        self.cm._extract_data_viewers.return_value = []
        self.cm._generate_action_chips.return_value = []
        self.cm.reasoning_config = {
            "enable_hierarchy": True, "max_narratives": 5, "max_sub_narratives": 4,
            "enable_reasoning_trace": False, "enable_decomposition": False,
            "rag_subquestion_aware": False, "enable_question_memory": False,
        }
        self.processor = QueryProcessor(self.cm)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    @staticmethod
    def _parse(resp):
        cm = MagicMock()
        from eye.services.context_manager import ContextManager
        real = ContextManager.__new__(ContextManager)
        real.logger = logging.getLogger("p")
        return real._parse_tool_calls(resp)

    @patch("time.sleep", return_value=None)
    def test_two_narrative_plan_drives_map_and_verdict(self, _s):
        plan_json = json.dumps({
            "verdict": "x.exe is malicious",
            "narratives": [
                {"claim": "x.exe established persistence",
                 "sub_narratives": [{"claim": "wrote a Run key", "evidence_needed": "HKCU Run",
                                     "tools": ["query_database"]}]},
                {"claim": "x.exe exfiltrated data",
                 "sub_narratives": [{"claim": "sent data out", "evidence_needed": "egress",
                                     "tools": ["query_database"]}]},
            ],
        })
        state = {"ran_tool": False}

        def gen(*a, **k):
            message = k.get("user_message", "") or (a[1] if len(a) > 1 else "")
            history = k.get("history", []) or []
            # The hierarchy planner prompt is the only one mentioning "sub_narratives".
            if "sub_narratives" in message:
                return {"content": plan_json, "tool_calls": []}
            # Sub-narrative 1: run a tool (text protocol) once, then conclude PROVEN.
            if "wrote a Run key" in message:
                if not state["ran_tool"]:
                    state["ran_tool"] = True
                    return {"content": '```tool_call\n{"name":"query_database","parameters":'
                            '{"database_name":"reg.db","sql_query":"SELECT 1"}}\n```'}
                return {"content": "SUBVERDICT: PROVEN || HKCU Run key holds x.exe"}
            # Sub-narrative 2: conclude NOT-PROVEN.
            if "sent data out" in message:
                return {"content": "SUBVERDICT: NOT-PROVEN || no egress records found"}
            # Final synthesis.
            return {"content": "x.exe is malicious. VERDICT: x.exe is malicious || persistence established"}

        self.cm.model_router.generate.side_effect = gen
        result = self.processor.process_query("is x.exe malicious?")

        g = self.nms.load_graph()
        narrs = {(n.get("meta") or {}).get("created_from"): n for n in g["narratives"]}
        # The seeded plan nodes exist with stable keys (no duplicates).
        self.assertIn("plan:nar:0", narrs)
        self.assertIn("plan:nar:0:sub:0", narrs)
        self.assertIn("plan:nar:1:sub:0", narrs)
        keys = [(n.get("meta") or {}).get("created_from") for n in g["narratives"]]
        self.assertEqual(len(keys), len(set(keys)))  # no duplicate cards
        # Sub-narrative 1 proven (evidence attached), sub-narrative 2 negative.
        self.assertEqual(narrs["plan:nar:0:sub:0"]["state"], "proven")
        self.assertEqual(narrs["plan:nar:1:sub:0"]["state"], "negative")
        # Verdict proven (a narrative was established) and tools actually ran.
        self.assertEqual(g["verdict"]["state"], "proven")
        self.cm._execute_tool.assert_called()
        self.assertIsNotNone(result)
        # No seeded card is left stuck `open` — every narrative reached a terminal state.
        self.assertFalse(any(n.get("state") == "open" for n in g["narratives"]),
                         "a sub-narrative/narrative was left open after the run")


if __name__ == "__main__":
    unittest.main()
