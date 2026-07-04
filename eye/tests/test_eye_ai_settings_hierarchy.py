"""
Settings persistence for the hierarchical investigation caps.

The Settings → Eye dialog writes `enable_hierarchy` / `max_narratives` /
`max_sub_narratives` into the `reasoning` section of `eye_config.json`; this must
round-trip (clamped) so `ContextManager._load_reasoning_config` → `_plan_hierarchy`
pick the values up.
"""

import json
import tempfile
import unittest
from pathlib import Path

from config.eye_ai_settings import read_eye_ai_settings, write_eye_ai_settings, DEFAULTS


class TestHierarchyCapsPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        self.path = Path(self.tmp.name)
        self.tmp.write("{}")
        self.tmp.close()

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_defaults_present(self):
        self.assertEqual(DEFAULTS["enable_hierarchy"], True)
        self.assertEqual(DEFAULTS["max_narratives"], 12)
        self.assertEqual(DEFAULTS["max_sub_narratives"], 8)
        self.assertEqual(DEFAULTS["max_iterations"], 300)

    def test_max_iterations_round_trip_clamped(self):
        write_eye_ai_settings({"max_iterations": 99999}, path=self.path)
        self.assertEqual(read_eye_ai_settings(path=self.path)["max_iterations"], 2000)
        write_eye_ai_settings({"max_iterations": 5}, path=self.path)
        self.assertEqual(read_eye_ai_settings(path=self.path)["max_iterations"], 20)

    def test_round_trip_clamped(self):
        write_eye_ai_settings(
            {"enable_hierarchy": False, "max_narratives": 99, "max_sub_narratives": 0},
            path=self.path)
        got = read_eye_ai_settings(path=self.path)
        self.assertEqual(got["enable_hierarchy"], False)
        self.assertEqual(got["max_narratives"], 30)      # clamped to max 30
        self.assertEqual(got["max_sub_narratives"], 1)   # clamped to min 1

    def test_lands_in_reasoning_section(self):
        write_eye_ai_settings({"max_narratives": 10}, path=self.path)
        cfg = json.loads(self.path.read_text())
        self.assertEqual(cfg["reasoning"]["max_narratives"], 10)

    def test_missing_keys_default(self):
        # An empty config returns the new-key defaults (so the engine stays enabled).
        got = read_eye_ai_settings(path=self.path)
        self.assertTrue(got["enable_hierarchy"])
        self.assertEqual(got["max_narratives"], 12)
        self.assertEqual(got["max_sub_narratives"], 8)


if __name__ == "__main__":
    unittest.main()
