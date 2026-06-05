"""
Tests for audit P3 fixes:
- #9: pre-flight connectivity check is TTL-cached (not pinged every query).
- #11: tool-output char cap is token-aware and scales with the window.
"""

import logging
import unittest
from unittest.mock import MagicMock

from eye.services.context_manager import ContextManager
from eye.services.query_processor import QueryProcessor


class TestConnectivityCache(unittest.TestCase):
    def _cm(self):
        cm = ContextManager.__new__(ContextManager)
        cm.logger = logging.getLogger("test-conn")
        cm._connectivity_cache = None
        cm.model_router = MagicMock()
        cm.model_router.config = {"backend": "ollama", "model_name": "llama3"}
        return cm

    def test_positive_result_is_cached(self):
        cm = self._cm()
        cm.model_router.validate_connectivity.return_value = True
        self.assertTrue(cm._validate_connectivity_cached())
        self.assertTrue(cm._validate_connectivity_cached())
        self.assertTrue(cm._validate_connectivity_cached())
        # Only the first call hit the backend.
        cm.model_router.validate_connectivity.assert_called_once()

    def test_failure_is_not_cached(self):
        cm = self._cm()
        cm.model_router.validate_connectivity.return_value = False
        self.assertFalse(cm._validate_connectivity_cached())
        self.assertFalse(cm._validate_connectivity_cached())
        # Every failure is re-checked.
        self.assertEqual(cm.model_router.validate_connectivity.call_count, 2)

    def test_model_switch_forces_recheck(self):
        cm = self._cm()
        cm.model_router.validate_connectivity.return_value = True
        self.assertTrue(cm._validate_connectivity_cached())
        # Switching the model changes the cache key -> re-ping.
        cm.model_router.config = {"backend": "ollama", "model_name": "mistral"}
        self.assertTrue(cm._validate_connectivity_cached())
        self.assertEqual(cm.model_router.validate_connectivity.call_count, 2)

    def test_ttl_expiry_rechecks(self):
        cm = self._cm()
        cm.model_router.validate_connectivity.return_value = True
        self.assertTrue(cm._validate_connectivity_cached())
        # Force the cache timestamp to be older than the TTL.
        cm._connectivity_cache["ts"] -= (cm._CONNECTIVITY_TTL_SECONDS + 1)
        self.assertTrue(cm._validate_connectivity_cached())
        self.assertEqual(cm.model_router.validate_connectivity.call_count, 2)


class TestToolOutputCharLimit(unittest.TestCase):
    def _qp(self, max_total_tokens, tool_results_budget, configured_chars=100000):
        cm = MagicMock()
        cm.max_total_tokens = max_total_tokens
        cm.max_tool_output_chars = configured_chars
        cm.token_budget = {"tool_results": tool_results_budget}
        qp = QueryProcessor.__new__(QueryProcessor)
        qp.cm = cm
        qp.logger = logging.getLogger("test-qp")
        return qp

    def test_large_window_scales_above_static_cap(self):
        # 200K window, tool_results ~39,600 tokens -> ceiling ~158,400 chars,
        # which exceeds the old static 100,000 cap (the P3 #11 fix).
        qp = self._qp(max_total_tokens=200_000, tool_results_budget=39_600)
        limit = qp._tool_output_char_limit()
        self.assertGreater(limit, 100_000)
        self.assertEqual(limit, 39_600 * 4)

    def test_small_window_unchanged(self):
        # 32K window, small explicit budget -> configured floor (10k) wins, same
        # as the legacy behavior.
        qp = self._qp(max_total_tokens=32_000, tool_results_budget=100, configured_chars=10_000)
        self.assertEqual(qp._tool_output_char_limit(), 10_000)

    def test_floor_minimum(self):
        qp = self._qp(max_total_tokens=500, tool_results_budget=10, configured_chars=10_000)
        # usable ~250 -> adaptive ~500; floor of 4000 applies.
        self.assertEqual(qp._tool_output_char_limit(), 4000)


if __name__ == "__main__":
    unittest.main()
