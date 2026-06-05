"""
Tests for the Advanced Context dialog's config manager — the presets file must
exist and every backend must resolve to a complete, valid config (root cause of
"Failed to open advanced context"), plus partial-config merge + save preservation.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from eye.services.context_window_config_manager import ContextWindowConfigManager

REPO = Path(__file__).resolve().parents[2]
CONFIGS = REPO / "configs"
PRESETS = CONFIGS / "context_window_presets.json"


class TestPresetsLoadAndResolve(unittest.TestCase):
    def setUp(self):
        self.mgr = ContextWindowConfigManager(config_dir=str(CONFIGS))

    def test_presets_file_exists_and_loads(self):
        self.assertTrue(PRESETS.exists(), "context_window_presets.json must exist")
        presets = self.mgr.get_available_presets()
        self.assertTrue(presets)
        self.assertIn("ollama", presets)  # hard-coded unknown-backend fallback

    def test_every_preset_resolves_complete_and_valid(self):
        for backend in self.mgr.get_available_presets():
            cfg = self.mgr.get_config_for_backend(backend)
            self.assertIsInstance(cfg.get("max_total_tokens"), int)
            self.assertGreater(cfg["max_total_tokens"], 0)
            for k in ("system_prompt", "rag_context", "conversation_history",
                      "tool_definitions", "response_buffer"):
                self.assertIn(k, cfg["token_budget"])
            for k in ("sliding_window_size", "preserve_first_message",
                      "preserve_tool_messages", "truncation_strategy"):
                self.assertIn(k, cfg["history_management"])
            # Must satisfy the manager's own validator (budget sum <= max, etc.)
            self.mgr._validate_config(cfg)

    def test_unknown_backend_falls_back(self):
        cfg = self.mgr.get_config_for_backend("totally-unknown-backend")
        self.assertIn("token_budget", cfg)
        self.assertIn("history_management", cfg)


class TestPartialConfigMergeAndSave(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        shutil.copy(PRESETS, os.path.join(self.dir, "context_window_presets.json"))
        # eye_config.json with a PARTIAL context_window (as the Eye-AI panel writes).
        self.eye_cfg = os.path.join(self.dir, "eye_config.json")
        with open(self.eye_cfg, "w") as f:
            json.dump({
                "integration_type": "cloud_api", "backend": "gemini", "model_name": "m",
                "context_window": {"max_total_tokens": 50000, "store_full_payload": True},
            }, f)
        self.mgr = ContextWindowConfigManager(config_dir=self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_partial_config_is_completed_from_preset(self):
        cfg = self.mgr.get_config_for_backend("gemini")
        self.assertEqual(cfg["max_total_tokens"], 50000)      # stored value kept
        self.assertIn("token_budget", cfg)                    # filled from preset
        self.assertIn("system_prompt", cfg["token_budget"])
        self.assertIn("history_management", cfg)              # filled from preset
        self.assertIn("sliding_window_size", cfg["history_management"])

    def test_save_preserves_panel_keys(self):
        cfg = self.mgr.get_config_for_backend("gemini")
        # Keep a valid budget<=max (the gemini preset budget sums to 118000).
        cfg["max_total_tokens"] = 130000
        self.mgr.save_config(cfg)
        with open(self.eye_cfg) as f:
            saved = json.load(f)
        self.assertTrue(saved["context_window"]["store_full_payload"])  # not wiped
        self.assertEqual(saved["context_window"]["max_total_tokens"], 130000)


if __name__ == "__main__":
    unittest.main()
