"""
Guards the "no hand-drawn tables in chat" reinforcement (Rule 29) so the system
prompt and the report-tools quick reference keep steering the model to a table
TOOL instead of drawing tables in the chat reply: `chat_add_table` for synthesized
chat-visible tables, `report_add_data_table` for SQL-backed evidence rows.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from eye.services.context_manager import ContextManager

_CFG = Path(__file__).resolve().parents[2] / "configs" / "llm_config.json"


class TestNoTablesRule(unittest.TestCase):
    def test_rule_29_in_system_prompt(self):
        data = json.loads(_CFG.read_text(encoding="utf-8"))
        rules = data["system_prompt_template"]
        joined = "\n".join(rules)
        self.assertIn("NO TABLES IN THE CHAT", joined)
        # Names the offending styles so the model can't rationalize an exception,
        # and both table tools (chat-visible vs SQL-backed).
        for token in ("pipe", "ASCII", "report_add_data_table", "chat_add_table"):
            self.assertIn(token, joined)

    def test_quick_reference_warns_against_drawn_tables(self):
        cm = ContextManager.__new__(ContextManager)  # no heavy init needed
        out = cm._build_report_tools_quick_reference([
            {"name": "report_add_data_table", "description": "table"},
            {"name": "chat_add_table", "description": "chat table"},
        ])
        self.assertIn("Rule 29", out)
        self.assertIn("HAND-DRAWN", out)
        self.assertIn("report_add_data_table", out)
        self.assertIn("chat_add_table", out)


if __name__ == "__main__":
    unittest.main()
