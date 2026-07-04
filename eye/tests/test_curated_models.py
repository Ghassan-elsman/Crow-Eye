"""
Tests for the curated Claude model catalog and its surfacing in the GUI model
menu (model_router.get_grouped_backend_options).
"""

import logging
import unittest
from unittest.mock import MagicMock

from eye.services.context_window_registry import (
    curated_models,
    recommended_models,
    resolve_context_window,
)
from eye.services.model_router import ModelRouter


class TestCuratedCatalog(unittest.TestCase):
    def test_anthropic_curated_ids(self):
        models = curated_models("anthropic")
        for expected in ("claude-opus-4-8", "claude-sonnet-4-6",
                         "claude-haiku-4-5", "claude-fable-5"):
            self.assertIn(expected, models)

    def test_recommended_subset(self):
        rec = recommended_models("anthropic")
        self.assertEqual(rec[0], "claude-opus-4-8")  # deep analysis first
        self.assertTrue(set(rec).issubset(set(curated_models("anthropic"))))

    def test_unknown_backend_is_empty(self):
        self.assertEqual(curated_models("openai"), [])      # intentionally not curated
        self.assertEqual(curated_models("nope"), [])
        self.assertEqual(recommended_models("nope"), [])

    def test_returns_fresh_list_each_call(self):
        a = curated_models("anthropic")
        a.append("mutated")
        self.assertNotIn("mutated", curated_models("anthropic"))  # no shared mutation

    def test_windows_resolve_for_latest_claude(self):
        for mid in ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5",
                    "claude-fable-5", "claude-opus-4-6"):
            self.assertEqual(resolve_context_window("anthropic", mid), 200_000, mid)


class TestGroupedBackendOptionsCurated(unittest.TestCase):
    def _router(self, live_models):
        r = ModelRouter.__new__(ModelRouter)  # skip _initialize_backend
        r.logger = logging.getLogger("test-router")
        r.config = {"backend": "anthropic", "model_name": "claude-opus-4-8"}
        r.credential_manager = None
        r.backend = MagicMock()
        r.backend.list_models.return_value = live_models
        return r

    def test_curated_merged_and_deduped(self):
        r = self._router(["claude-opus-4-8", "legacy-model"])
        groups = r.get_grouped_backend_options()
        cloud = [o for o in groups["Cloud API"] if o["backend"] == "anthropic"]
        names = [o["model_name"] for o in cloud]
        # Live model kept, curated merged, the shared id appears exactly once.
        self.assertEqual(names.count("claude-opus-4-8"), 1)
        self.assertIn("legacy-model", names)
        self.assertIn("claude-sonnet-4-6", names)
        self.assertIn("claude-fable-5", names)
        # The active model is flagged.
        self.assertTrue(any(o["is_active"] for o in cloud
                            if o["model_name"] == "claude-opus-4-8"))

    def test_works_when_live_list_empty(self):
        r = self._router([])  # e.g. offline / detect failed
        groups = r.get_grouped_backend_options()
        names = [o["model_name"] for o in groups["Cloud API"] if o["backend"] == "anthropic"]
        self.assertIn("claude-opus-4-8", names)  # curated still offered


if __name__ == "__main__":
    unittest.main()
