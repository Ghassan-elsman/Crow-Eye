"""
Tests for the main-Settings Eye AI options bridge (config/eye_ai_settings.py):
read defaults, write-merge (preserving other keys), nested confidence threshold,
clamping, and round-trip.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from config.eye_ai_settings import read_eye_ai_settings, write_eye_ai_settings, DEFAULTS


class TestEyeAiSettings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "eye_config.json"

    def test_defaults_when_missing(self):
        s = read_eye_ai_settings(self.path)
        for k, v in DEFAULTS.items():
            self.assertEqual(s[k], v)
        self.assertEqual(s["backend"], "")
        self.assertEqual(s["model_name"], "")

    def test_roundtrip_all_fields(self):
        write_eye_ai_settings({
            "store_full_payload": False,
            "sealed_payload_recent_uncompressed": 25,
            "confidence_threshold": 0.4,
            "max_total_tokens": 128000,
            "lock_max_total_tokens": True,
            "max_tool_output_chars": 250000,
        }, self.path)
        s = read_eye_ai_settings(self.path)
        self.assertEqual(s["store_full_payload"], False)
        self.assertEqual(s["sealed_payload_recent_uncompressed"], 25)
        self.assertAlmostEqual(s["confidence_threshold"], 0.4)
        self.assertEqual(s["max_total_tokens"], 128000)
        self.assertEqual(s["lock_max_total_tokens"], True)
        self.assertEqual(s["max_tool_output_chars"], 250000)

    def test_confidence_written_nested_and_clamped(self):
        write_eye_ai_settings({"confidence_threshold": 5.0}, self.path)
        cfg = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["context_window"]["evidence_preservation"]["confidence_threshold"], 1.0)
        write_eye_ai_settings({"confidence_threshold": -2.0}, self.path)
        self.assertEqual(read_eye_ai_settings(self.path)["confidence_threshold"], 0.0)

    def test_write_preserves_existing_keys(self):
        self.path.write_text(json.dumps({
            "integration_type": "cloud_api",
            "backend": "gemini",
            "model_name": "gemini-2.5-flash",
            "context_window": {"max_total_tokens": 200000,
                               "token_budget": {"tool_results": 4000}},
        }), encoding="utf-8")

        write_eye_ai_settings({"store_full_payload": True,
                               "sealed_payload_recent_uncompressed": 5}, self.path)

        cfg = json.loads(self.path.read_text(encoding="utf-8"))
        # Top-level + unrelated context_window keys preserved.
        self.assertEqual(cfg["backend"], "gemini")
        self.assertEqual(cfg["model_name"], "gemini-2.5-flash")
        self.assertEqual(cfg["context_window"]["token_budget"]["tool_results"], 4000)
        self.assertEqual(cfg["context_window"]["max_total_tokens"], 200000)
        # New keys merged in.
        self.assertEqual(cfg["context_window"]["store_full_payload"], True)
        self.assertEqual(cfg["context_window"]["sealed_payload_recent_uncompressed"], 5)
        # read-only display fields surfaced.
        s = read_eye_ai_settings(self.path)
        self.assertEqual(s["backend"], "gemini")
        self.assertEqual(s["model_name"], "gemini-2.5-flash")

    def test_clamping_and_atomic(self):
        write_eye_ai_settings({"sealed_payload_recent_uncompressed": -3,
                               "max_total_tokens": 10, "max_tool_output_chars": 10}, self.path)
        s = read_eye_ai_settings(self.path)
        self.assertEqual(s["sealed_payload_recent_uncompressed"], 0)
        self.assertEqual(s["max_total_tokens"], 1000)
        self.assertEqual(s["max_tool_output_chars"], 1000)
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.dir)))


if __name__ == "__main__":
    unittest.main()
