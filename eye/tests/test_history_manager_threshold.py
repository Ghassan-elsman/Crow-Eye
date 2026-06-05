"""
Tests for HistoryManager.manage_history compaction threshold.

After the audit reconciliation, persistent history is compacted only when it
approaches the FULL usable context window (ContextManager.usable_context_tokens())
— not the smaller per-component conversation_history sub-budget. Evidence/pinned
messages are preserved when compaction does happen.
"""

import logging
import threading
import unittest
from unittest.mock import MagicMock

from eye.services.history_manager import HistoryManager


def _make_history_manager(usable_tokens: int):
    hm = HistoryManager.__new__(HistoryManager)
    hm.logger = logging.getLogger("test-history")
    hm._lock = threading.RLock()
    hm.history = []
    cm = MagicMock()
    cm.usable_context_tokens.return_value = usable_tokens
    cm.token_counter.count_tokens.return_value = 5
    cm.truncation_auditor = None
    cm.truncation_count = 0
    # The old per-component cap — manage_history must NOT use this anymore.
    cm.token_budget = {"conversation_history": 200}
    hm.cm = cm
    hm._summarize_chunk = MagicMock(return_value="SUMMARY")
    hm._generate_message_id = MagicMock(return_value="sum-id")
    return hm, cm


def _msg(i, tokens, **md):
    return {"id": f"m{i}", "role": "user", "content": f"msg {i}",
            "token_count": tokens, "metadata": md}


class TestManageHistoryThreshold(unittest.TestCase):
    def test_no_compaction_below_usable_window_above_old_cap(self):
        # Total 400 tokens: well above the old conversation_history cap (200) but
        # below the full usable window (1000) -> must NOT summarize anymore.
        hm, cm = _make_history_manager(usable_tokens=1000)
        hm.history = [_msg(i, 100) for i in range(4)]  # 4 * 100 = 400

        hm.manage_history()

        hm._summarize_chunk.assert_not_called()
        self.assertEqual(len(hm.history), 4)

    def test_compaction_above_usable_window_preserves_evidence(self):
        # Total 1600 > usable 1000 and len > 6 -> compacts; the evidence-flagged
        # mid message is preserved, a summary replaces the summarizable mid msgs.
        hm, cm = _make_history_manager(usable_tokens=1000)
        history = [_msg(i, 200) for i in range(8)]
        history[1]["metadata"] = {"preserve_evidence": True}  # mid + preserved
        hm.history = history

        hm.manage_history()

        hm._summarize_chunk.assert_called_once()
        ids = [m.get("id") for m in hm.history]
        self.assertIn("m1", ids, "evidence-flagged message must be preserved")
        self.assertTrue(any(m.get("metadata", {}).get("is_summary") for m in hm.history),
                        "a summary message must be inserted")


if __name__ == "__main__":
    unittest.main()
