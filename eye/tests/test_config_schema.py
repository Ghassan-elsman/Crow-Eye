"""
Tests that eye_config_schema.json is reconciled with what the code actually
reads/writes — and that a partial context_window (as written by the main
Settings Eye AI section) validates (the load_config crash fix).
"""

import json
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "configs" / "eye_config_schema.json"
EXAMPLE_PATH = REPO / "configs" / "eye_config_example_full.json"


def _schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestSchemaReconciliation(unittest.TestCase):
    def setUp(self):
        self.schema = _schema()
        self.cw = self.schema["properties"]["context_window"]

    def test_partial_context_window_validates(self):
        # Exactly what the Eye AI settings panel writes — must NOT raise.
        cfg = {
            "integration_type": "cloud_api",
            "backend": "gemini",
            "model_name": "gemini-2.5-flash",
            "context_window": {
                "store_full_payload": True,
                "max_total_tokens": 64000,
                "sealed_payload_recent_uncompressed": 10,
            },
        }
        jsonschema.validate(cfg, self.schema)  # no exception

    def test_no_context_window_validates(self):
        jsonschema.validate(
            {"integration_type": "cloud_api", "backend": "gemini", "model_name": "m"},
            self.schema,
        )

    def test_full_context_window_with_history_management_validates(self):
        cfg = {
            "integration_type": "cloud_api", "backend": "gemini", "model_name": "m",
            "context_window": {
                "max_total_tokens": 64000,
                "token_budget": {"conversation_history": 8000, "system_prompt": 4000,
                                 "rag_context": 2000, "tool_results": 4000},
                "history_management": {"sliding_window_size": 5,
                                       "preserve_first_message": True,
                                       "preserve_tool_messages": True,
                                       "truncation_strategy": "sliding_window"},
                "evidence_preservation": {"confidence_threshold": 0.7},
            },
        }
        jsonschema.validate(cfg, self.schema)

    def test_dead_blocks_removed(self):
        self.assertNotIn("audit_trail", self.cw["properties"])
        ev = self.cw["properties"]["evidence_preservation"]["properties"]
        self.assertEqual(set(ev.keys()), {"confidence_threshold"})

    def test_required_arrays_relaxed(self):
        self.assertNotIn("required", self.cw)  # context_window fields all optional
        tb = self.cw["properties"]["token_budget"]
        self.assertNotIn("required", tb)
        self.assertNotIn("tool_definitions", tb["properties"])
        self.assertNotIn("response_buffer", tb["properties"])
        self.assertIn("tool_results", tb["properties"])

    def test_new_keys_present(self):
        for k in ("store_full_payload", "sealed_payload_recent_uncompressed",
                  "lock_max_total_tokens", "max_tool_output_chars"):
            self.assertIn(k, self.cw["properties"])

    def test_history_management_kept(self):
        self.assertIn("history_management", self.cw["properties"])

    def test_example_config_validates(self):
        with open(EXAMPLE_PATH, "r", encoding="utf-8") as f:
            example = json.load(f)
        jsonschema.validate(example, self.schema)


if __name__ == "__main__":
    unittest.main()
