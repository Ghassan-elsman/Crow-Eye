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
    def test_no_autopersist_for_trivial_chat_without_tools(self, _s):
        # No tools ran -> nothing to document.
        self.cm.model_router.generate.side_effect = lambda *a, **k: {
            "content": "Hello, how can I help with the case?", "tool_calls": []}
        self.processor.process_query("hi there")
        self.cm.report_engine.append_section.assert_not_called()


if __name__ == "__main__":
    unittest.main()
