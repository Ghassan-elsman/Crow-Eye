"""
Tests that the agent loop does NOT stop and wait for the user when the model
narrates a next step without calling a tool — it nudges the model to continue
(audit fix for the "I will now check prefetch…" early-stop).
"""

import json
import logging
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from eye.services.query_processor import QueryProcessor
from eye.services.evidence_seal import EvidenceSeal
from eye.services.token_counter import TokenCounter
from eye.services.truncation_auditor import TruncationAuditor


def _parse(resp):
    return [
        {"name": tc["function"]["name"],
         "parameters": json.loads(tc["function"].get("arguments") or "{}")}
        for tc in (resp.get("tool_calls") or [])
    ]


class TestLoopContinuesOnNarration(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cm = MagicMock()
        self.cm.case_directory = self.dir
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
    def test_narration_without_tool_call_is_nudged_not_ended(self, _s):
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                # Narrates a next step but emits NO tool call.
                return {"content": "I will now check prefetch_data.db for game executables.",
                        "tool_calls": []}
            if calls["n"] == 2:
                # After the nudge, actually calls a tool.
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "query_database", "arguments": "{}"}}]}
            # Real final answer.
            return {"content": "Checked Amcache and Prefetch; no games found.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen

        self.processor.process_query("does this pc has games ?")

        # Old behavior would have ended at iteration 1 (text-only -> break).
        self.assertGreaterEqual(self.cm.model_router.generate.call_count, 3)
        self.cm._execute_tool.assert_called()  # it actually ran the next-step tool

    @patch("time.sleep", return_value=None)
    def test_evidence_ledger_injected_into_outgoing_not_history(self, _s):
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "get_schema", "arguments": "{\"database_name\": \"amcache_data.db\"}"}}]}
            if calls["n"] == 2:
                return {"content": "", "tool_calls": [
                    {"id": "c2", "type": "function",
                     "function": {"name": "query_database", "arguments": "{\"database_name\": \"prefetch_data.db\"}"}}]}
            return {"content": "Checked Amcache and Prefetch; no games.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("does this pc has games ?")

        # The ledger must reach the MODEL (an outgoing user_message), once tools ran.
        outgoing = [c.kwargs.get("user_message", "") for c in self.cm.model_router.generate.call_args_list]
        self.assertTrue(any("Evidence Gathered So Far" in m for m in outgoing),
                        "evidence ledger was not injected into any outgoing message")
        # ...but it must NOT be persisted into history (no bloat).
        persisted = [c.args[1] for c in self.cm.history_manager.add_message.call_args_list
                     if len(c.args) >= 2 and isinstance(c.args[1], str)]
        self.assertFalse(any("Evidence Gathered So Far" in m for m in persisted),
                         "ledger should not be written into persistent history")

    @patch("time.sleep", return_value=None)
    def test_findings_autopersisted_when_model_skips_report_tool(self, _s):
        # Investigation runs a query tool then answers in chat without report_*.
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "query_database", "arguments": "{}"}}]}
            return {"content": "Yes — Steam was installed and executed.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("does this pc has games ?")

        self.cm.report_engine.append_section.assert_called_once()
        self.cm.report_engine.save_report.assert_called()

    @patch("time.sleep", return_value=None)
    def test_no_autopersist_when_model_wrote_report(self, _s):
        # The model's own report_* write means we must NOT double-document.
        self.cm._execute_tool.return_value = {
            "tool_name": "report_append_section", "success": True, "result": {"block_id": "b1"},
        }
        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "report_append_section", "arguments": "{}"}}]}
            return {"content": "Documented.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("summarize findings")

        self.cm.report_engine.append_section.assert_not_called()

    @patch("time.sleep", return_value=None)
    def test_text_protocol_model_runs_tools_without_native_calls(self, _s):
        # A Gemma-style model that emits tool calls ONLY as fenced ```tool_call text
        # (no native tool_calls) must still drive real tool execution. We route the
        # parse through the REAL ContextManager parser so the text protocol is exercised.
        from eye.services.context_manager import ContextManager
        real_cm = ContextManager.__new__(ContextManager)
        real_cm.logger = logging.getLogger("test-parse")
        self.cm._parse_tool_calls.side_effect = real_cm._parse_tool_calls

        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                # Text tool call only — no native "tool_calls" key.
                return {"content":
                        'Checking SRUM.\n```tool_call\n'
                        '{"name": "query_database", "parameters": '
                        '{"database_name": "srum.db", "sql_query": "SELECT 1"}}\n```',
                        "tools_unsupported": True}
            return {"content": "Discord sent 4.2 MB of telemetry — confirmed.",
                    "tools_unsupported": True}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("did discord send telemetry?")

        self.cm._execute_tool.assert_called()  # the text tool call actually executed
        executed = self.cm._execute_tool.call_args[0][0]
        self.assertEqual(executed.get("name"), "query_database")

    @patch("time.sleep", return_value=None)
    def test_capable_model_gets_text_protocol_fallback_after_native_miss(self, _s):
        # A function-calling model that narrates a next step without emitting a native
        # call should be taught the text protocol ONCE in the follow-up nudge, then it
        # uses it to run a tool.
        self.cm._build_tool_call_format.return_value = "## Tool-Call Format\n```tool_call ..."
        self.cm._get_tool_definitions.return_value = []

        calls = {"n": 0}

        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                # Narrates intent, no native tool_calls, NOT tools_unsupported (capable).
                return {"content": "I will now query the SRUM database.", "tool_calls": []}
            if calls["n"] == 2:
                return {"content": "", "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "query_database", "arguments": "{}"}}]}
            return {"content": "Done — SRUM shows the egress.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("did discord exfiltrate?")

        # The fallback format was offered exactly once.
        self.cm._build_tool_call_format.assert_called_once()
        # And it was injected into an outgoing nudge message.
        outgoing = [c.kwargs.get("user_message", "") for c in self.cm.model_router.generate.call_args_list]
        self.assertTrue(any("Tool-Call Format" in m for m in outgoing))

    @patch("time.sleep", return_value=None)
    def test_toolless_model_exits_early_without_burning_all_nudges(self, _s):
        # A model that ONLY narrates plans and never emits a tool call (e.g. a model
        # that cannot do function calling) must NOT spin through all MAX_CONTINUE_NUDGES
        # (10) and must NOT execute any tool — it exits early to an honest answer.
        def gen(*a, **k):
            return {"content": "I will now query srum_application_usage and check persistence.",
                    "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen
        result = self.processor.process_query("hunt for telemetry and hidden tracking")

        self.cm._execute_tool.assert_not_called()  # no tool ever ran
        # Early exit (toolless bound 2 + one forced synthesis), NOT 10+ nudges.
        self.assertLessEqual(self.cm.model_router.generate.call_count, 4)
        self.assertIsNotNone(result)

    @patch("time.sleep", return_value=None)
    def test_tools_unsupported_response_does_not_loop(self, _s):
        # The backend reports it dropped tools (Gemma): the loop must not keep nudging
        # a model that physically cannot call tools.
        def gen(*a, **k):
            return {"content": "Here is my plan for the investigation.",
                    "tool_calls": [], "tools_unsupported": True}

        self.cm.model_router.generate.side_effect = gen
        self.processor.process_query("hunt for telemetry")

        self.cm._execute_tool.assert_not_called()
        self.assertLessEqual(self.cm.model_router.generate.call_count, 4)

    @patch("time.sleep", return_value=None)
    def test_no_autopersist_for_trivial_chat_without_tools(self, _s):
        # No tools ran -> nothing to document.
        self.cm.model_router.generate.side_effect = lambda *a, **k: {
            "content": "Hello, how can I help with the case?", "tool_calls": []}
        self.processor.process_query("hi there")
        self.cm.report_engine.append_section.assert_not_called()


if __name__ == "__main__":
    unittest.main()
