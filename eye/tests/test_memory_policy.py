"""
Tests for the unified two-stage conversation-memory policy
(``reduce_messages_to_budget`` in history_manager.py):

  Stage 1 — Summarization buffer: fold older non-protected turns into ONE rolling
            summary.
  Stage 2 — Sliding window: drop the oldest droppable turn FIFO until it fits.

Always kept verbatim: the first turn, every evidence/pinned/tool-result turn, and
the last ``window_turns`` turns. Evicted RAW turns are handed to ``archive_cb`` so
they can be recalled later (long-term memory).
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from eye.services.history_manager import HistoryManager, reduce_messages_to_budget
from eye.services.rag_service import RAGService
from eye.services.token_counter import TokenCounter


def _cf(s):
    """Deterministic stand-in token counter (≈4 chars/token, min 1)."""
    return max(1, len(s or "") // 4)


def _m(i, tokens, **md):
    return {"id": f"m{i}", "role": "user", "content": f"content-of-message-{i}",
            "token_count": tokens, "metadata": dict(md)}


class TestReduceMessagesToBudget(unittest.TestCase):
    def test_no_change_when_within_budget(self):
        msgs = [_m(i, 10) for i in range(5)]  # 50 tokens
        reduced, cuts, summary = reduce_messages_to_budget(
            msgs, usable_tokens=1000, token_count_fn=_cf,
            window_turns=3, summarize_fn=lambda e: "ROLLED",
        )
        self.assertEqual([m["id"] for m in reduced], [m["id"] for m in msgs])
        self.assertEqual(cuts, [])
        self.assertIsNone(summary)

    def test_summary_buffer_folds_middle_turns(self):
        msgs = [_m(i, 100) for i in range(10)]  # 1000 tokens
        archived = []
        reduced, cuts, summary = reduce_messages_to_budget(
            msgs, usable_tokens=500, token_count_fn=_cf,
            window_turns=3, summarize_fn=lambda e: "ROLLED-SUMMARY",
            enable_summary_buffer=True, enable_drop=True,
            archive_cb=archived.append,
        )
        ids = [m.get("id") for m in reduced]
        # First turn and the last-3 window survive verbatim.
        self.assertEqual(ids[0], "m0")
        for keep in ("m7", "m8", "m9"):
            self.assertIn(keep, ids)
        # The middle (m1..m6) is gone, folded into a single rolling summary.
        for gone in ("m1", "m2", "m3", "m4", "m5", "m6"):
            self.assertNotIn(gone, ids)
        self.assertIsNotNone(summary)
        self.assertTrue(summary["metadata"]["is_summary"])
        self.assertTrue(summary["metadata"]["is_rolling_summary"])
        # Every folded turn is a SUMMARIZED cut and was archived for recall.
        self.assertEqual({c["action"] for c in cuts}, {"SUMMARIZED"})
        self.assertEqual(len(cuts), 6)
        self.assertEqual({m["id"] for m in archived}, {"m1", "m2", "m3", "m4", "m5", "m6"})

    def test_persistent_path_summarizes_without_dropping(self):
        # enable_drop=False (the manage_history persistent path): Stage 1 only —
        # the result may stay over budget, never hard-dropped.
        msgs = [_m(i, 100) for i in range(10)]
        reduced, cuts, summary = reduce_messages_to_budget(
            msgs, usable_tokens=300, token_count_fn=_cf,
            window_turns=3, summarize_fn=lambda e: "S",
            enable_summary_buffer=True, enable_drop=False,
        )
        self.assertEqual(len(reduced), 5)  # m0 + summary + m7,m8,m9
        self.assertTrue(all(c["action"] == "SUMMARIZED" for c in cuts))
        self.assertIsNotNone(summary)

    def test_sliding_window_drops_oldest_when_summary_off(self):
        msgs = [_m(i, 100) for i in range(5)]  # 500 tokens
        reduced, cuts, summary = reduce_messages_to_budget(
            msgs, usable_tokens=250, token_count_fn=_cf,
            window_turns=2, summarize_fn=lambda e: "S",
            enable_summary_buffer=False, enable_drop=True,
        )
        self.assertIsNone(summary)
        self.assertTrue(cuts)
        self.assertTrue(all(c["action"] == "TRUNCATED" for c in cuts))
        # The most recent turn and the first turn survive; total now fits.
        ids = [m.get("id") for m in reduced]
        self.assertIn("m4", ids)
        self.assertLessEqual(sum(m.get("token_count", 0) for m in reduced), 250)

    def test_protected_turns_never_cut(self):
        msgs = [
            _m(0, 100),
            _m(1, 100, preserve_evidence=True),
            _m(2, 100),
            _m(3, 100, pinned=True),
            _m(4, 100, is_tool_result=True),
            _m(5, 100),
        ]
        reduced, cuts, _ = reduce_messages_to_budget(
            msgs, usable_tokens=150, token_count_fn=_cf,
            window_turns=1, summarize_fn=lambda e: "S",
            enable_summary_buffer=False, enable_drop=True,
        )
        ids = [m.get("id") for m in reduced]
        # Evidence / pinned / tool-result turns are the irreducible core.
        for protected in ("m1", "m3", "m4"):
            self.assertIn(protected, ids)
        # Cuts only ever touched non-protected turns.
        self.assertTrue(all(c["msg"]["id"] in ("m0", "m2", "m5") for c in cuts))

    def test_summarize_runs_before_drop(self):
        # With both stages on and a budget that even the summary can't fully meet,
        # SUMMARIZED records must precede any TRUNCATED record (ordering).
        msgs = [_m(i, 100) for i in range(12)]
        reduced, cuts, summary = reduce_messages_to_budget(
            msgs, usable_tokens=250, token_count_fn=_cf,
            window_turns=2, summarize_fn=lambda e: "S",
            enable_summary_buffer=True, enable_drop=True,
        )
        actions = [c["action"] for c in cuts]
        self.assertIn("SUMMARIZED", actions)
        if "TRUNCATED" in actions:
            self.assertLess(actions.index("SUMMARIZED"), actions.index("TRUNCATED"))
        self.assertLessEqual(
            sum(m.get("token_count", 0) or _cf(m.get("content")) for m in reduced), 250)


class TestManageHistoryArchiveRecall(unittest.TestCase):
    """End-to-end: persistent compaction (Stage 1) archives evicted turns and the
    conversation-recall index can later retrieve them (long-term memory)."""

    def _cm(self, case_dir):
        cm = MagicMock()
        cm.case_directory = case_dir
        cm.token_counter = TokenCounter(backend="gpt-4")
        cm.usable_context_tokens.return_value = 50  # tiny window -> force compaction
        cm.reasoning_config = {"history_window_turns": 2, "enable_summary_buffer": True}
        cm.truncation_auditor = None
        cm.truncation_count = 0
        cm.rag_service = RAGService(knowledge_base_dir=case_dir)
        cm.model_router.config = {"model_name": "m"}
        cm.model_router.generate.return_value = {"content": "rolled summary"}
        cm.evidence_seal = MagicMock()
        cm.max_total_tokens = 8192
        return cm

    def test_evicted_turns_archived_and_recallable(self):
        d = tempfile.mkdtemp()
        cm = self._cm(d)
        hm = HistoryManager(cm)
        hm.history = [
            {"id": f"h{i}", "role": "user",
             "content": f"turn {i}: powershell base64 dropper wrote evil.exe to disk",
             "token_count": 100, "metadata": {}}
            for i in range(8)
        ]

        hm.manage_history()

        # The persistent log collapsed to first + summary + last-2 window.
        self.assertTrue(any(m.get("metadata", {}).get("is_summary") for m in hm.history))
        self.assertLess(len(hm.history), 8)

        # Evicted raw turns were archived to disk...
        archive = os.path.join(d, "EYE_Logs", "eye_conversation_archive.jsonl")
        self.assertTrue(os.path.exists(archive))
        with open(archive, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertGreater(len(lines), 0)

        # ...and are retrievable from the conversation-recall index.
        out = cm.rag_service.retrieve_conversation("where was evil.exe dropped", top_k=2)
        self.assertIn("evil.exe", out)
        self.assertTrue(cm.rag_service.last_conversation_sources)


if __name__ == "__main__":
    unittest.main()
