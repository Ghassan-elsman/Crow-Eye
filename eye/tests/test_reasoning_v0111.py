"""
Tests for the v0.11.1 investigator-grade reasoning behaviors:
  1. Question decomposition into a sub-question checklist + final correlation.
  2. Cross-session per-question answer memory (save/reuse).
  3. Premise verification (prove / disprove the investigator).

Covers the pure helpers (plan parsing, checklist, synthesis mandate), the
CaseContextManager question-memory store, the ContextManager prior-findings
block + reasoning-config loader, and one end-to-end loop integration.
"""

import json
import logging
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from eye.services.query_processor import QueryProcessor, ContextOverflowError
from eye.services.evidence_seal import EvidenceSeal
from eye.services.token_counter import TokenCounter
from eye.services.truncation_auditor import TruncationAuditor
from eye.services.case_context_manager import CaseContextManager

try:
    from eye.services.context_manager import ContextManager
    HAS_CM = True
except Exception:  # heavy optional deps (backend SDKs) may be absent
    HAS_CM = False


def _parse(resp):
    return [
        {"name": tc["function"]["name"],
         "parameters": json.loads(tc["function"].get("arguments") or "{}")}
        for tc in (resp.get("tool_calls") or [])
    ]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestPlanParsing(unittest.TestCase):
    def test_plain_json_legacy_strings(self):
        # Legacy shape: sub_questions as plain strings -> normalized to {q, why}.
        plan = QueryProcessor._parse_plan(
            '{"sub_questions": ["a", "b"], "user_premises": ["os deletes x"], "related_prior": true}'
        )
        self.assertEqual([s["q"] for s in plan["sub_questions"]], ["a", "b"])
        self.assertEqual([s["why"] for s in plan["sub_questions"]], ["", ""])
        self.assertEqual(plan["user_premises"], ["os deletes x"])
        self.assertTrue(plan["related_prior"])

    def test_object_subquestions_capture_why_and_strategy(self):
        # New shape: {q/question, why} objects + a strategy line.
        raw = json.dumps({
            "sub_questions": [
                {"q": "what ran", "why": "establish execution"},
                {"question": "when deleted", "reason": "establish timeline"},
            ],
            "strategy": "split by artifact",
            "user_premises": [],
        })
        plan = QueryProcessor._parse_plan(raw)
        self.assertEqual([s["q"] for s in plan["sub_questions"]], ["what ran", "when deleted"])
        self.assertEqual(plan["sub_questions"][0]["why"], "establish execution")
        self.assertEqual(plan["sub_questions"][1]["why"], "establish timeline")
        self.assertEqual(plan["strategy"], "split by artifact")

    def test_json_in_code_fence_and_prose(self):
        raw = "Here is the plan:\n```json\n{\"sub_questions\": [\"only\"], \"user_premises\": []}\n```\nthanks"
        plan = QueryProcessor._parse_plan(raw)
        self.assertEqual([s["q"] for s in plan["sub_questions"]], ["only"])
        self.assertEqual(plan["user_premises"], [])
        self.assertFalse(plan["related_prior"])

    def test_garbage_returns_none(self):
        self.assertIsNone(QueryProcessor._parse_plan("no json here"))
        self.assertIsNone(QueryProcessor._parse_plan(""))
        self.assertIsNone(QueryProcessor._parse_plan("{not valid json,,,}"))

    def test_caps_subquestions_and_filters_null_premises(self):
        raw = json.dumps({
            "sub_questions": [f"q{i}" for i in range(10)],
            "user_premises": ["null", "", "real claim", "N/A"],
        })
        plan = QueryProcessor._parse_plan(raw, max_subq=3)
        self.assertEqual(len(plan["sub_questions"]), 3)
        self.assertEqual([s["q"] for s in plan["sub_questions"]], ["q0", "q1", "q2"])
        self.assertEqual(plan["user_premises"], ["real claim"])

    def test_should_plan_gate(self):
        self.assertFalse(QueryProcessor._should_plan("hi"))
        self.assertFalse(QueryProcessor._should_plan("show users"))
        self.assertTrue(QueryProcessor._should_plan("was 7zip installed and run?"))

    def test_should_plan_signals(self):
        # Trivial-skip pre-filter: the LLM decides the split, code only skips
        # clearly trivial input. A SHORT assertion still plans (premise check).
        self.assertTrue(QueryProcessor._should_plan("prefetch is auto-deleted"))
        self.assertTrue(QueryProcessor._should_plan("teamviewer was installed"))
        self.assertTrue(QueryProcessor._should_plan("list users and recent logons"))
        self.assertTrue(QueryProcessor._should_plan("who logged in? what ran?"))
        # 4+ word substantive input now reaches the LLM planner (it may return a
        # single sub-question — the LLM, not code, makes that call).
        self.assertTrue(QueryProcessor._should_plan("list the prefetch entries"))
        # <=3-word plain lookups / greetings / empty stay trivial-skipped.
        self.assertFalse(QueryProcessor._should_plan("show recent documents"))
        self.assertFalse(QueryProcessor._should_plan("list users"))
        self.assertFalse(QueryProcessor._should_plan("hi"))
        self.assertFalse(QueryProcessor._should_plan("thanks"))
        self.assertFalse(QueryProcessor._should_plan(""))

    def test_plan_prompt_segmentation_mode(self):
        # The planner prompt is LLM-logical: prefer_segmentation flips the
        # splitting instruction; there is no length/keyword split in code.
        qp = QueryProcessor(MagicMock())
        captured = {}

        def fake_guarded(system_prompt, user_message, history, tools, *, phase, iteration):
            captured["prompt"] = user_message
            return {"content": '{"sub_questions": ["x"], "user_premises": []}'}

        qp._plan_investigation("a big detailed multi-faceted question about the case",
                               fake_guarded, lambda *a, **k: None, lambda *a, **k: None,
                               {"max_sub_questions": 6}, prefer_segmentation=True)
        self.assertIn("LOGICAL/semantic boundaries", captured["prompt"])
        self.assertIn("logically-distinct", captured["prompt"])

        qp._plan_investigation("a single focused question", fake_guarded,
                               lambda *a, **k: None, lambda *a, **k: None,
                               {"max_sub_questions": 6}, prefer_segmentation=False)
        self.assertIn("multiple explicit parts", captured["prompt"])


class TestReasoningTrace(unittest.TestCase):
    def setUp(self):
        self.qp = QueryProcessor(MagicMock())
        self.checklist = [
            {"q": "Was 7zip installed?", "status": "answered", "kind": "question", "why": "establish install"},
            {"q": "verify: user deleted files", "status": "answered", "kind": "premise"},
        ]
        self.ledger = [{"iteration": 1, "tool": "query_database",
                        "params": {"database_name": "amcache.db"},
                        "result": {"success": True, "row_count": 1}}]

    def test_parse_reasoning_none_on_bad_json(self):
        self.assertIsNone(QueryProcessor._parse_reasoning("not json"))
        self.assertIsNone(QueryProcessor._parse_reasoning(""))
        self.assertIsNone(QueryProcessor._parse_reasoning("[1,2,3]"))  # not a dict

    def test_norm_evidence_accepts_strings_and_objects(self):
        out = QueryProcessor._norm_evidence(
            ["amcache.db:files:3", {"ref": "prefetch.db:pf:7", "note": "3 runs"}, {}, ""])
        self.assertEqual(out[0], {"ref": "amcache.db:files:3", "note": ""})
        self.assertEqual(out[1], {"ref": "prefetch.db:pf:7", "note": "3 runs"})
        self.assertEqual(len(out), 2)  # empties dropped

    def test_capture_trace_normalizes_model_output(self):
        def fake_gg(sysp, um, tools, hist, *, phase, iteration):
            self.assertEqual(phase, "reasoning")  # sealed at planning temperature
            return {"content": json.dumps({
                "sub_questions": [{"id": "sq1", "conclusion": "installed",
                                   "why_concluded": "amcache row present",
                                   "evidence": [{"ref": "amcache.db:files:3", "note": "entry"}],
                                   "status": "answered"}],
                "premises": [{"verdict": "refuted", "why": "no $Recycle.Bin entries", "evidence": []}],
                "consolidation": "7zip installed; no deletion",
            })}
        rec = self.qp._capture_reasoning_trace(
            "Was 7zip installed and did the user delete files?",
            self.checklist, self.ledger, "final answer text",
            fake_gg, lambda *a, **k: None, lambda *a, **k: None,
            strategy="split by artifact", knowledge_consulted=["amcache_knowledge.md"])
        self.assertEqual(rec["strategy"], "split by artifact")
        self.assertEqual(rec["sub_questions"][0]["why_created"], "establish install")
        self.assertEqual(rec["sub_questions"][0]["conclusion"], "installed")
        self.assertEqual(rec["sub_questions"][0]["evidence"][0]["ref"], "amcache.db:files:3")
        self.assertEqual(rec["premises"][0]["verdict"], "REFUTED")
        self.assertEqual(rec["knowledge_consulted"], ["amcache_knowledge.md"])

    def test_capture_trace_falls_back_when_model_json_bad(self):
        # Bad model output -> still returns a decomposition-only record (why_created
        # preserved), never raises.
        def bad_gg(*a, **k):
            return {"content": "sorry, no json here"}
        rec = self.qp._capture_reasoning_trace(
            "q", self.checklist, self.ledger, "ans",
            bad_gg, lambda *a, **k: None, lambda *a, **k: None)
        self.assertEqual(rec["sub_questions"][0]["why_created"], "establish install")
        self.assertEqual(rec["sub_questions"][0]["conclusion"], "")
        self.assertEqual(rec["premises"][0]["verdict"], "INCONCLUSIVE")

    def test_capture_trace_survives_model_exception(self):
        def boom(*a, **k):
            raise RuntimeError("model down")
        rec = self.qp._capture_reasoning_trace(
            "q", self.checklist, self.ledger, "ans",
            boom, lambda *a, **k: None, lambda *a, **k: None)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec["sub_questions"]), 1)


class TestChecklist(unittest.TestCase):
    def setUp(self):
        self.qp = QueryProcessor(MagicMock())

    def test_checklist_block_marks_open_and_answered(self):
        checklist = [
            {"q": "Was X installed?", "status": "answered", "kind": "question"},
            {"q": "verify: OS deletes prefetch", "status": "open", "kind": "premise"},
        ]
        block = self.qp._build_checklist_block(checklist)
        self.assertIn("Sub-Questions to Answer", block)
        self.assertIn("[x] Was X installed?", block)
        self.assertIn("[ ] verify: OS deletes prefetch", block)

    def test_empty_checklist_is_blank(self):
        self.assertEqual(self.qp._build_checklist_block([]), "")

    def test_planning_overflow_degrades_to_atomic(self):
        # F3: an optional planning pass must NOT abort the query on overflow.
        def boom(*a, **k):
            raise ContextOverflowError(100, 50, 10)
        plan = self.qp._plan_investigation(
            "a b c d e", boom,
            emit_step=lambda *a, **k: None, emit_dialogue=lambda *a, **k: None,
            reasoning_cfg={"max_sub_questions": 6},
        )
        self.assertIsNone(plan)

    def test_update_marks_item_answered_from_evidence_only(self):
        # A sub-question is satisfied ONLY by real tool evidence — never by the
        # model's own answer prose (which would let planning text falsely complete it).
        checklist = [
            {"q": "Was 7zip installed?", "status": "open", "kind": "question"},
            {"q": "Was Firefox run?", "status": "open", "kind": "question"},
        ]
        self.qp._update_checklist(
            checklist,
            ai_content="7zip was installed per Amcache.",  # prose alone must NOT count
            ledger_entries=[
                {"success": True, "result": {"rows": [{"name": "7zip", "installed": True}]},
                 "params": {}},
            ],
        )
        self.assertEqual(checklist[0]["status"], "answered")  # backed by ledger evidence
        self.assertEqual(checklist[1]["status"], "open")      # firefox untouched

    def test_update_ignores_model_prose_without_evidence(self):
        # The exact false-completion bug: the model narrates a plan mentioning the
        # sub-question's terms but ran no tool → the item MUST stay open.
        checklist = [{"q": "Was 7zip installed?", "status": "open", "kind": "question"}]
        self.qp._update_checklist(
            checklist,
            ai_content="I will now check whether 7zip was installed per Amcache.",
            ledger_entries=[],  # no evidence
        )
        self.assertEqual(checklist[0]["status"], "open")

    def test_update_ignores_failed_tool_results(self):
        checklist = [{"q": "Was 7zip installed?", "status": "open", "kind": "question"}]
        self.qp._update_checklist(
            checklist, ai_content="",
            ledger_entries=[{"success": False, "result": {"error": "7zip installed amcache"},
                             "params": {}}],
        )
        self.assertEqual(checklist[0]["status"], "open")  # a failed call is not evidence


class TestSynthesisMandate(unittest.TestCase):
    def setUp(self):
        self.qp = QueryProcessor(MagicMock())

    def test_no_checklist_no_mandate(self):
        self.assertEqual(self.qp._build_correlation_mandate(None), "")
        self.assertEqual(self.qp._build_correlation_mandate([]), "")

    def test_zero_evidence_mandate_is_honest_not_a_plan(self):
        # No successful results → the synthesis prompt must forbid future-tense
        # planning and demand an honest "no data retrieved" answer.
        prompt = self.qp._build_synthesis_prompt("hunt for telemetry", results=[])
        self.assertIn("NO ARTIFACT DATA WAS RETRIEVED", prompt)
        self.assertIn("FORBIDDEN", prompt)
        for banned in ("I will", "I am acting"):
            self.assertIn(banned, prompt)  # named as forbidden phrasings

    def test_evidence_mandate_allows_findings(self):
        # With a successful result the normal forensic-narrative mandate is used.
        prompt = self.qp._build_synthesis_prompt(
            "hunt for telemetry", results=[{"success": True, "result": {"rows": [1]}}])
        self.assertIn("FORENSIC NARRATIVE", prompt)
        self.assertNotIn("NO ARTIFACT DATA WAS RETRIEVED", prompt)

    def test_premise_mandate_requires_verdict_and_consolidation(self):
        checklist = [
            {"q": "Was X run?", "status": "open", "kind": "question"},
            {"q": "verify: Windows auto-deleted all prefetch", "status": "open", "kind": "premise"},
        ]
        prompt = self.qp._build_synthesis_prompt(
            "did X run; also windows deleted prefetch right?",
            results=[{"success": True}],
            checklist=checklist,
        )
        for token in ("CONFIRMED", "REFUTED", "INCONCLUSIVE", "Consolidated Answer",
                      "Was X run?", "mistaken"):
            self.assertIn(token, prompt)


# ---------------------------------------------------------------------------
# Cross-session question memory store
# ---------------------------------------------------------------------------
class TestQuestionMemoryStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ccm = CaseContextManager(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_save_and_recent_roundtrip_with_ids(self):
        self.assertEqual(self.ccm.get_recent_question_memory(), [])
        self.ccm.save_question_memory("Q1?", "answer one", "amcache -> 1 row", ["query_database"])
        self.ccm.save_question_memory("Q2?", "answer two", "prefetch -> 2 rows", ["query_database"])
        recent = self.ccm.get_recent_question_memory(limit=5)
        self.assertEqual([r["id"] for r in recent], ["q1", "q2"])
        self.assertEqual(recent[-1]["question"], "Q2?")
        self.assertEqual(recent[-1]["answer_summary"], "answer two")
        self.assertEqual(recent[-1]["key_findings"], "prefetch -> 2 rows")

    def test_limit_returns_most_recent(self):
        for i in range(5):
            self.ccm.save_question_memory(f"Q{i}", f"a{i}", "")
        recent = self.ccm.get_recent_question_memory(limit=2)
        self.assertEqual([r["question"] for r in recent], ["Q3", "Q4"])

    def test_persists_across_instances(self):
        self.ccm.save_question_memory("persisted?", "yes", "mft -> 3 rows")
        reopened = CaseContextManager(self.dir)
        recent = reopened.get_recent_question_memory()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["answer_summary"], "yes")

    def test_corrupt_line_is_skipped(self):
        self.ccm.save_question_memory("good?", "ok", "")
        with open(self.ccm.question_memory_file, "a", encoding="utf-8") as f:
            f.write("{not json}\n")
        recent = self.ccm.get_recent_question_memory()
        self.assertEqual(len(recent), 1)

    def test_id_no_collision_after_corrupt_line(self):
        # F4: a corrupt line preceding a valid high-id record must NOT cause the
        # next id to collide. Max-based id derivation handles this.
        with open(self.ccm.question_memory_file, "w", encoding="utf-8") as f:
            f.write("{corrupt line\n")
            f.write(json.dumps({"id": "q2", "question": "old", "answer_summary": "a"}) + "\n")
        self.ccm.save_question_memory("new?", "answer", "")
        ids = [r["id"] for r in self.ccm.get_recent_question_memory(limit=None)]
        self.assertEqual(ids, ["q2", "q3"])  # new id is q3, not a duplicate q2
        self.assertEqual(len(ids), len(set(ids)))  # all unique


# ---------------------------------------------------------------------------
# ContextManager: reasoning config + prior-findings block
# ---------------------------------------------------------------------------
@unittest.skipUnless(HAS_CM, "context_manager optional deps missing")
class TestContextManagerReasoning(unittest.TestCase):
    def _bare_cm(self):
        cm = ContextManager.__new__(ContextManager)
        cm.logger = logging.getLogger("test-cm")
        return cm

    def test_load_reasoning_config_has_all_keys(self):
        cfg = self._bare_cm()._load_reasoning_config()
        for k in ContextManager.DEFAULT_REASONING_CONFIG:
            self.assertIn(k, cfg)
        self.assertIsInstance(cfg["enable_decomposition"], bool)
        self.assertIsInstance(cfg["max_sub_questions"], int)

    def test_prior_findings_block_renders_when_enabled(self):
        cm = self._bare_cm()
        cm.reasoning_config = {"enable_question_memory": True, "prior_findings_count": 3}
        cm.case_context_manager = MagicMock()
        cm.case_context_manager.get_recent_question_memory.return_value = [
            {"id": "q1", "question": "Was 7zip installed?",
             "answer_summary": "Yes, found in Amcache.", "key_findings": "amcache -> 1 row"},
        ]
        block = cm._build_prior_findings_block()
        self.assertIn("Prior Findings", block)
        self.assertIn("[q1]", block)
        self.assertIn("Amcache", block)

    def test_prior_findings_block_empty_when_disabled(self):
        cm = self._bare_cm()
        cm.reasoning_config = {"enable_question_memory": False, "prior_findings_count": 3}
        cm.case_context_manager = MagicMock()
        self.assertEqual(cm._build_prior_findings_block(), "")


# ---------------------------------------------------------------------------
# End-to-end loop integration
# ---------------------------------------------------------------------------
class TestDecompositionLoopIntegration(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cm = MagicMock()
        self.cm.case_directory = self.dir
        self.cm.reasoning_config = {
            "enable_decomposition": True,
            "max_sub_questions": 6,
            "enable_premise_verification": True,
            "enable_question_memory": True,
            "prior_findings_count": 3,
        }
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
        self.cm.model_router = MagicMock()
        self.cm.model_router.config = {"model_name": "mock"}
        self.cm.report_engine = MagicMock()
        self.cm.report_engine.get_report_json.return_value = {"metadata": {"block_count": 0, "last_modified": ""}}
        self.cm._build_system_prompt.return_value = "SYS"
        self.cm._get_tool_definitions.return_value = []
        self.cm._parse_tool_calls.side_effect = _parse
        self.cm._execute_tool.return_value = {
            "tool_name": "query_database", "success": True,
            "result": {"columns": ["name"], "data": [], "row_count": 0},
        }
        self.cm._generate_action_chips.return_value = []
        self.processor = QueryProcessor(self.cm)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    @patch("time.sleep", return_value=None)
    def test_decomposition_drives_checklist_and_saves_memory(self, _s):
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                # Planning pre-pass: decompose into two sub-questions.
                return {"content": json.dumps({
                    "sub_questions": ["Was 7zip installed?", "Was 7zip run?"],
                    "user_premises": [],
                    "related_prior": False,
                }), "tool_calls": []}
            if calls["n"] == 2:
                # First investigative turn: run a tool.
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "query_database", "arguments": "{}"}}]}
            # Final answer covering both sub-questions.
            return {"content": "7zip was installed (Amcache) and 7zip was run (Prefetch).",
                    "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("Was 7zip installed and was it run?")

        # The sub-question checklist must have reached the model.
        outgoing = [c.kwargs.get("user_message", "") for c in self.cm.model_router.generate.call_args_list]
        self.assertTrue(any("Sub-Questions to Answer" in m for m in outgoing),
                        "sub-question checklist was not injected into any outgoing message")
        # Planning consumed the first model call (so >= 3 total).
        self.assertGreaterEqual(self.cm.model_router.generate.call_count, 3)
        # The answer + findings were saved to per-question memory.
        self.cm.case_context_manager.save_question_memory.assert_called_once()

    @patch("time.sleep", return_value=None)
    def test_gen_params_temperature_by_phase(self, _s):
        # guarded_generate must tag the planning call with planning_temperature
        # and the investigative/answer calls with answer_temperature.
        self.cm.reasoning_config = {
            "enable_decomposition": True, "max_sub_questions": 6,
            "enable_premise_verification": True, "enable_question_memory": False,
            "prior_findings_count": 0, "enable_reasoning_trace": False,
            "answer_temperature": 0.2, "planning_temperature": 0.0, "max_output_tokens": 4096,
        }
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": json.dumps({"sub_questions": ["a", "b"], "user_premises": [],
                                               "related_prior": False}), "tool_calls": []}
            return {"content": "done", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("Was 7zip installed and was it run?")

        temps = [(c.kwargs.get("gen_params") or {}).get("temperature")
                 for c in self.cm.model_router.generate.call_args_list]
        # First call is the planning pass (planning_temperature == 0.0).
        self.assertEqual(temps[0], 0.0)
        # Subsequent (answer) calls use answer_temperature == 0.2.
        self.assertIn(0.2, temps[1:])

    @patch("time.sleep", return_value=None)
    def test_related_prior_surfaces_reuse_hint(self, _s):
        # F2: when the plan flags related_prior, a reuse hint must reach the model.
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": json.dumps({
                    "sub_questions": ["What time exactly?"],   # single → no checklist
                    "user_premises": [],
                    "related_prior": True,
                }), "tool_calls": []}
            return {"content": "It happened at 14:02 UTC.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("and what time exactly did that happen?")

        outgoing = [c.kwargs.get("user_message", "") for c in self.cm.model_router.generate.call_args_list]
        self.assertTrue(any("Reuse Prior Findings" in m for m in outgoing),
                        "related_prior did not surface a reuse hint to the model")

    @patch("time.sleep", return_value=None)
    def test_disabled_reasoning_skips_planning(self, _s):
        self.cm.reasoning_config = {
            "enable_decomposition": False, "enable_premise_verification": False,
            "enable_question_memory": False, "prior_findings_count": 0,
        }
        self.cm.model_router.generate.side_effect = lambda *a, **k: {
            "content": "Single answer.", "tool_calls": []}
        self.processor.process_query("Was 7zip installed and was it run?")
        outgoing = [c.kwargs.get("user_message", "") for c in self.cm.model_router.generate.call_args_list]
        self.assertFalse(any("Sub-Questions to Answer" in m for m in outgoing))
        self.cm.case_context_manager.save_question_memory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
