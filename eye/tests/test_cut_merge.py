"""
Tests for the read-side merge that makes "Processed vs Dropped Payload" reflect
EVERY drop: budget trims (system prompt / RAG / history) synthesized from the
audit log, and the refused payload (the message itself) from the seals.
"""

import unittest

from eye.services.cut_merge import assembly_cuts_from_events, refused_payload_cuts


SEALS = [
    {"timestamp": "2026-06-04T22:10:00", "query": "Q1", "seq": 1},
    {"timestamp": "2026-06-04T22:11:00", "query": "Q2 refused one",
     "seq": 2, "sent_to_model": False, "phase": "request:REFUSED_OVERFLOW",
     "payload_tokens": 34013, "payload_sha256": "a" * 64,
     "payload_sidecar": "sealed_payloads/" + "a" * 64 + ".txt",
     "payload_preview": "ORIGINAL REFUSED MESSAGE PREVIEW",
     "max_context_tokens": 32000},
]

EVENTS = [
    {"action": "TRUNCATED", "reason": "system_prompt_core_over_budget",
     "timestamp": "2026-06-04T22:11:05", "tokens": 4175, "hash": "h1",
     "metadata": {"cut_content": "DROPPED SYS PROMPT TAIL"}},
    {"action": "TRUNCATED", "reason": "rag_context_budget",
     "timestamp": "2026-06-04T22:11:06", "tokens": 2371, "hash": "h2", "metadata": {}},
    {"action": "SUMMARIZED", "reason": "budget_exceeded",
     "timestamp": "2026-06-04T22:11:07", "tokens": 156, "hash": "h3",
     "metadata": {"cut_content": "OLD MSG", "processed_content": "SUMMARY"}},
    # Must be EXCLUDED — already represented in seal cut_details:
    {"action": "SUMMARIZED", "reason": "self_heal_context_fit",
     "timestamp": "2026-06-04T22:11:08", "tokens": 41, "hash": "h4",
     "metadata": {"cut_content": "x", "processed_content": "y"}},
    {"action": "TRUNCATED", "reason": "tool_output_memory_cap_57600_chars",
     "timestamp": "2026-06-04T22:11:09", "tokens": 343266, "hash": "h5", "metadata": {}},
    {"action": "REFUSED_OVERFLOW", "reason": "evidence_core_exceeds_context_after_self_heal",
     "timestamp": "2026-06-04T22:11:10", "tokens": 34013, "hash": "h6", "metadata": {}},
]


class TestAssemblyCuts(unittest.TestCase):
    def test_only_budget_reasons_included(self):
        cuts = assembly_cuts_from_events(EVENTS, SEALS)
        reasons = {c["phase"] for c in cuts}
        self.assertEqual(reasons, {"system_prompt_core_over_budget", "rag_context_budget", "budget_exceeded"})
        # self-heal + tool-cap + refusal event must NOT be synthesized here.
        self.assertNotIn("self_heal_context_fit", reasons)
        self.assertNotIn("tool_output_memory_cap_57600_chars", reasons)

    def test_content_and_source_passthrough(self):
        cuts = {c["phase"]: c for c in assembly_cuts_from_events(EVENTS, SEALS)}
        sysp = cuts["system_prompt_core_over_budget"]
        self.assertEqual(sysp["cut_content"], "DROPPED SYS PROMPT TAIL")
        self.assertEqual(sysp["source"], "assembly_budget")
        self.assertEqual(sysp["token_count"], 4175)
        hist = cuts["budget_exceeded"]
        self.assertEqual(hist["processed_content"], "SUMMARY")

    def test_query_correlated_by_timestamp(self):
        cuts = assembly_cuts_from_events(EVENTS, SEALS)
        # All three budget events are after the 22:11 seal → attributed to Q2.
        self.assertTrue(all(c["query"] == "Q2 refused one" for c in cuts))

    def test_empty_inputs(self):
        self.assertEqual(assembly_cuts_from_events([], SEALS), [])
        # No seals → entries still synthesized, query just resolves to "".
        no_seal = assembly_cuts_from_events(EVENTS, [])
        self.assertEqual(len(no_seal), 3)
        self.assertTrue(all(c["query"] == "" for c in no_seal))


class TestRefusedPayloadCuts(unittest.TestCase):
    def test_refused_entry_built(self):
        cuts = refused_payload_cuts(SEALS)
        self.assertEqual(len(cuts), 1)
        c = cuts[0]
        self.assertEqual(c["action"], "REFUSED_OVERFLOW")
        self.assertEqual(c["source"], "refused")
        self.assertEqual(c["query"], "Q2 refused one")
        self.assertEqual(c["payload_sha256"], "a" * 64)
        self.assertEqual(c["max_context_tokens"], 32000)
        self.assertEqual(c["token_count"], 34013)
        # The original (refused) message preview is carried inline.
        self.assertEqual(c["cut_content"], "ORIGINAL REFUSED MESSAGE PREVIEW")

    def test_sent_payloads_excluded(self):
        self.assertEqual(refused_payload_cuts([{"sent_to_model": True, "phase": "request"}]), [])


if __name__ == "__main__":
    unittest.main()
