"""
Text tool-call protocol (Gemma-compatible).

Models without native function-calling (e.g. Gemma on the Gemini API, which 500s
if `tools` are sent) must still be able to run forensic tools. They do so by
emitting a fenced ```tool_call JSON block in their reply text; the harness parses
it via `_parse_tool_calls` and executes it like any native call.
"""

import logging
import unittest

from eye.services.context_manager import ContextManager
from eye.services.query_processor import QueryProcessor


def _cm():
    # _parse_tool_calls / _parse_text_tool_calls only need a logger.
    cm = ContextManager.__new__(ContextManager)
    cm.logger = logging.getLogger("test-cm")
    return cm


class TestTextToolCallParsing(unittest.TestCase):
    def setUp(self):
        self.cm = _cm()

    def test_fenced_tool_call_object(self):
        text = (
            "I need the network egress.\n"
            "```tool_call\n"
            '{"name": "query_database", "parameters": {"database_name": "srum.db", '
            '"sql_query": "SELECT * FROM srum_network_data_usage"}}\n'
            "```"
        )
        calls = self.cm._parse_tool_calls({"content": text})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "query_database")
        self.assertEqual(calls[0]["parameters"]["database_name"], "srum.db")

    def test_fenced_tool_calls_array(self):
        text = (
            "```tool_calls\n"
            '[{"name": "get_schema", "parameters": {"database_name": "a.db"}},'
            ' {"name": "query_database", "parameters": {"database_name": "a.db", "sql_query": "SELECT 1"}}]\n'
            "```"
        )
        calls = self.cm._parse_tool_calls({"content": text})
        self.assertEqual([c["name"] for c in calls], ["get_schema", "query_database"])

    def test_json_fenced_block_fallback(self):
        text = '```json\n{"name": "list_case_files", "parameters": {}}\n```'
        calls = self.cm._parse_tool_calls({"content": text})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "list_case_files")
        self.assertEqual(calls[0]["parameters"], {})

    def test_arguments_alias_and_string_json(self):
        # Some models use "arguments" (as a JSON string) instead of "parameters".
        text = '```tool_call\n{"name": "get_schema", "arguments": "{\\"database_name\\": \\"x.db\\"}"}\n```'
        calls = self.cm._parse_tool_calls({"content": text})
        self.assertEqual(calls[0]["parameters"]["database_name"], "x.db")

    def test_native_calls_take_priority_no_double_parse(self):
        # A native tool_call present → text is NOT parsed (avoids prose false-positives).
        resp = {
            "tool_calls": [{"function": {"name": "query_database", "arguments": "{}"}}],
            "content": '```tool_call\n{"name": "get_schema", "parameters": {}}\n```',
        }
        calls = self.cm._parse_tool_calls(resp)
        self.assertEqual([c["name"] for c in calls], ["query_database"])

    def test_plain_prose_is_not_a_tool_call(self):
        calls = self.cm._parse_tool_calls(
            {"content": "I will now query the SRUM database for network usage."})
        self.assertEqual(calls, [])

    def test_malformed_block_is_ignored(self):
        calls = self.cm._parse_tool_calls(
            {"content": "```tool_call\nnot json at all {oops\n```"})
        self.assertEqual(calls, [])

    def test_json_without_name_is_ignored(self):
        # Casual JSON the model wrote in prose (no "name") must not become a call.
        calls = self.cm._parse_tool_calls(
            {"content": '```json\n{"database_name": "srum.db", "rows": 5}\n```'})
        self.assertEqual(calls, [])


class TestToolCallFormatPrompt(unittest.TestCase):
    def test_format_block_lists_params_and_example(self):
        cm = _cm()
        tool_defs = [
            {"name": "query_database", "description": "run SQL",
             "parameters": {"type": "object",
                            "properties": {"database_name": {}, "sql_query": {}},
                            "required": ["database_name", "sql_query"]}},
            {"name": "list_case_files", "description": "browse",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "report_append_section", "description": "doc",
             "parameters": {"type": "object", "properties": {"title": {}}}},
        ]
        block = cm._build_tool_call_format(tool_defs, mandatory=True)
        self.assertIn("```tool_call", block)
        self.assertIn("ONLY way", block)  # mandatory wording for Gemma
        self.assertIn("query_database: database_name*, sql_query*", block)
        self.assertIn("list_case_files: (no parameters)", block)
        self.assertNotIn("report_append_section", block)  # report_* covered elsewhere

    def test_format_block_optional_wording_for_capable_models(self):
        cm = _cm()
        block = cm._build_tool_call_format(
            [{"name": "get_schema", "parameters": {"properties": {"database_name": {}}}}],
            mandatory=False)
        self.assertIn("alternative to native function-calling", block)


class TestStripToolCallBlocks(unittest.TestCase):
    def test_strips_fenced_block_keeps_prose(self):
        text = (
            "Discord sent 4.2 MB of telemetry.\n\n"
            "```tool_call\n{\"name\": \"query_database\", \"parameters\": {}}\n```\n\n"
            "This confirms egress."
        )
        out = QueryProcessor._strip_tool_call_blocks(text)
        self.assertNotIn("tool_call", out)
        self.assertNotIn("query_database", out)
        self.assertIn("Discord sent 4.2 MB of telemetry.", out)
        self.assertIn("This confirms egress.", out)

    def test_strips_array_tag(self):
        text = "Answer.\n```tool_calls\n[{\"name\": \"get_schema\", \"parameters\": {}}]\n```"
        out = QueryProcessor._strip_tool_call_blocks(text)
        self.assertEqual(out, "Answer.")

    def test_plain_text_unchanged(self):
        text = "A normal forensic conclusion with no tool calls."
        self.assertEqual(QueryProcessor._strip_tool_call_blocks(text), text)

    def test_empty_safe(self):
        self.assertEqual(QueryProcessor._strip_tool_call_blocks(""), "")
        self.assertIsNone(QueryProcessor._strip_tool_call_blocks(None))


class TestBuildToolOutput(unittest.TestCase):
    def test_builds_compact_entries(self):
        results = [
            {"tool_name": "query_database", "success": True,
             "parameters": {"database_name": "srum.db", "sql_query": "SELECT 1"},
             "result": {"data": [{"app": "discord", "bytes": 4200000}]}},
            {"tool_name": "get_schema", "success": False,
             "parameters": {"database_name": "missing.db"},
             "result": {"success": False, "error": "not found"}},
        ]
        out = QueryProcessor._build_tool_output(results)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "query_database")
        self.assertTrue(out[0]["success"])
        self.assertIn("discord", out[0]["result_text"])
        self.assertEqual(out[0]["parameters"]["database_name"], "srum.db")
        self.assertFalse(out[1]["success"])

    def test_truncates_huge_result(self):
        big = {"tool_name": "query_database", "success": True,
               "result": {"data": "x" * 9000}}
        out = QueryProcessor._build_tool_output([big])
        self.assertLess(len(out[0]["result_text"]), 6200)
        self.assertIn("truncated", out[0]["result_text"])

    def test_empty(self):
        self.assertEqual(QueryProcessor._build_tool_output([]), [])
        self.assertEqual(QueryProcessor._build_tool_output(None), [])


if __name__ == "__main__":
    unittest.main()
