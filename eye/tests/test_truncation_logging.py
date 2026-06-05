import unittest
from unittest.mock import MagicMock, patch
import json
import tempfile
import shutil
from pathlib import Path

from eye.services.truncation_auditor import TruncationAuditor
from eye.services.evidence_seal import EvidenceSeal
from eye.services.token_counter import TokenCounter
from eye.services.query_processor import QueryProcessor, ContextOverflowError


class TestTruncationAuditor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.auditor = TruncationAuditor(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_log_event_and_retrieve(self):
        # Log a summarized event with cut_content and processed_content in metadata
        self.auditor.log_event(
            action="SUMMARIZED",
            message_id="msg_123",
            token_count=150,
            reason="budget_exceeded",
            message_hash="abcde12345",
            metadata={
                "cut_content": "This is the message content that was cut during context compression.",
                "processed_content": "This is the surviving summary."
            }
        )
        self.auditor._flush_buffer()

        events = self.auditor.get_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["action"], "SUMMARIZED")
        self.assertEqual(event["id"], "msg_123")
        self.assertEqual(event["tokens"], 150)
        self.assertEqual(event["reason"], "budget_exceeded")
        self.assertEqual(event["hash"], "abcde12345")
        self.assertEqual(
            event["metadata"]["cut_content"],
            "This is the message content that was cut during context compression."
        )
        self.assertEqual(
            event["metadata"]["processed_content"],
            "This is the surviving summary."
        )


class TestEvidenceSeal(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.seal = EvidenceSeal(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_seal_logs_cut_details(self):
        # We want to verify that when we seal a payload, the seal records
        # information about the surviving payload, the truncated flag,
        # and details of what was cut.
        cut_details = [
            {
                "action": "TRUNCATED",
                "message_id": "msg_999",
                "role": "user",
                "token_count": 50,
                "sha256": "abcdef",
                "cut_content": "This content was truncated.",
                "processed_content": ""
            }
        ]
        record = self.seal.seal(
            payload_text="Surviving prompt contents that the model sees",
            phase="request",
            iteration=1,
            query="Find evil patterns",
            model="gemini-pro",
            max_context=8192,
            token_count=100,
            evidence_refs=[{"tool": "query_database", "database": "SecurityLogs.db", "sql": "SELECT ...", "row_count": 5}],
            truncated=True,
            cut_details=cut_details
        )

        self.assertEqual(record["seq"], 1)
        self.assertEqual(record["model"], "gemini-pro")
        self.assertTrue(record["truncated"])
        self.assertEqual(record["payload_tokens"], 100)
        
        # Verify it has the payload SHA-256 hash of the surviving payload
        expected_sha = EvidenceSeal._sha256("Surviving prompt contents that the model sees")
        self.assertEqual(record["payload_sha256"], expected_sha)
        
        # Verify cut content and metadata are captured in the seal
        self.assertIn("cut_details", record)
        self.assertEqual(len(record["cut_details"]), 1)
        self.assertEqual(record["cut_details"][0]["message_id"], "msg_999")
        self.assertEqual(record["cut_details"][0]["cut_content"], "This content was truncated.")
        self.assertEqual(record["cut_details"][0]["processed_content"], "")

    def test_build_cut_detail_tool_output_split(self):
        # A tool-output cap: the kept head is a prefix of the original and the
        # dropped tail exceeds the inline preview cap, so it spills to a sidecar.
        cap = EvidenceSeal.CUT_PREVIEW_CHARS
        processed = "HEAD-KEPT"
        dropped = "Z" * (cap + 5000)
        original = processed + dropped
        detail = self.seal.build_cut_detail(
            action="TRUNCATED_TOOL_OUTPUT",
            message_id="m1",
            role="tool",
            original_text=original,
            processed_text=processed,
            dropped_text=dropped,
            token_count=len(original),
            iteration=2,
            processed_is_prefix=True,
        )
        # Inline preview is bounded; full length + hash recorded.
        self.assertEqual(detail["cut_content"], dropped[:cap])
        self.assertEqual(detail["cut_content_len"], len(dropped))
        self.assertEqual(detail["cut_content_sha256"], EvidenceSeal._sha256(dropped))
        # Explicit byte-range of the cut within the original message.
        self.assertEqual(detail["cut_range"]["total"], len(original))
        self.assertEqual(detail["cut_range"]["processed"], [0, len(processed)])
        self.assertEqual(detail["cut_range"]["dropped"], [len(processed), len(original)])
        # Forensic-artifact offset lists are present (both kinds captured).
        self.assertIn("processed_file_offsets", detail)
        self.assertIn("dropped_file_offsets", detail)
        # The full dropped bytes are recoverable from the sidecar.
        self.assertTrue(detail["cut_content_sidecar"])
        sidecar = Path(self.temp_dir) / "EYE_Logs" / detail["cut_content_sidecar"]
        self.assertTrue(sidecar.exists())
        with open(sidecar, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), dropped)

    def test_build_cut_detail_small_content_no_sidecar(self):
        # Content under the cap stays fully inline; no sidecar file is created.
        detail = self.seal.build_cut_detail(
            action="TRUNCATED",
            message_id="m2",
            role="user",
            original_text="short dropped message",
            processed_text="",
            dropped_text="short dropped message",
            token_count=5,
        )
        self.assertEqual(detail["cut_content"], "short dropped message")
        self.assertIsNone(detail["cut_content_sidecar"])
        self.assertEqual(detail["cut_range"]["processed"], [0, 0])
        self.assertEqual(detail["cut_range"]["dropped"], [0, len("short dropped message")])

    def test_build_cut_detail_summarized_whole_message_dropped(self):
        # For a summary, the survivor is a NEW text (not a prefix slice), so the
        # entire original message counts as dropped.
        original = "some long original forensic message content"
        summary = "short summary"
        detail = self.seal.build_cut_detail(
            action="SUMMARIZED",
            message_id="m3",
            role="user",
            original_text=original,
            processed_text=summary,
            dropped_text=original,
            token_count=10,
        )
        self.assertEqual(detail["cut_range"]["processed"], [0, 0])
        self.assertEqual(detail["cut_range"]["dropped"], [0, len(original)])
        self.assertEqual(detail["processed_content"], summary)

    def test_build_cut_detail_redaction_integrity(self):
        # A secret in the dropped content must be redacted everywhere it is
        # stored, AND the recorded hash/length must describe the redacted bytes
        # actually persisted (so the sidecar is independently verifiable).
        key = "AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0"
        cap = EvidenceSeal.CUT_PREVIEW_CHARS
        dropped = f"secret={key} " + ("padding " * 2000)  # secret in preview; > cap
        self.assertGreater(len(dropped), cap)
        detail = self.seal.build_cut_detail(
            action="TRUNCATED",
            message_id="r1",
            role="user",
            original_text=dropped,
            processed_text="",
            dropped_text=dropped,
            token_count=10,
        )
        # The inline preview is redacted.
        self.assertNotIn(key, detail["cut_content"])
        self.assertIn("[REDACTED_API_KEY]", detail["cut_content"])
        # The sidecar holds the FULL but redacted bytes, and the recorded hash +
        # length match those exact bytes (verifiable chain of custody).
        self.assertTrue(detail["cut_content_sidecar"])
        sidecar = Path(self.temp_dir) / "EYE_Logs" / detail["cut_content_sidecar"]
        raw = sidecar.read_text(encoding="utf-8")
        self.assertNotIn(key, raw)
        self.assertEqual(EvidenceSeal._sha256(raw), detail["cut_content_sha256"])
        self.assertEqual(len(raw), detail["cut_content_len"])
        # The sidecar filename is its own content hash.
        self.assertTrue(detail["cut_content_sidecar"].endswith(f"{detail['cut_content_sha256']}.txt"))


class TestQueryProcessorTruncationLogging(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Mock ContextManager and services
        self.cm = MagicMock()
        self.cm.case_directory = self.temp_dir
        self.cm.truncation_auditor = TruncationAuditor(self.temp_dir)
        # Persistent evidence-seal writer now lives on the ContextManager
        # (one writer per case); provide a real one for the mocked cm.
        self.cm.evidence_seal = EvidenceSeal(self.temp_dir)
        self.cm.token_counter = TokenCounter(backend="gpt-4")
        self.cm.max_total_tokens = 500  # set context window size small to trigger self-healing
        self.cm.token_budget = {
            "conversation_history": 200,
            "system_prompt": 100,
            "rag_context": 50,
            "tool_results": 100
        }
        self.cm.history_manager = MagicMock()
        self.cm.history_manager.history = []
        self.cm.history_manager._summarize_chunk = MagicMock(return_value="History summary")
        
        # IntentEngine
        self.cm.intent_engine = MagicMock()
        self.cm.intent_engine.detect_keywords.return_value = []
        
        # RAGService
        self.cm.rag_service = MagicMock()
        self.cm.rag_service.retrieve_context.return_value = ""
        
        # ModelRouter
        self.cm.model_router = MagicMock()
        self.cm.model_router.config = {"model_name": "mock-model"}
        
        # ReportEngine
        self.cm.report_engine = MagicMock()
        self.cm.report_engine.get_report_json.return_value = {
            "metadata": {"block_count": 0, "last_modified": ""}
        }
        
        self.processor = QueryProcessor(self.cm)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch("time.sleep", return_value=None)
    def test_history_self_heal_logging_cut_content(self, mock_sleep):
        # We mock model_router.generate to return a simple response
        self.cm.model_router.generate.return_value = {
            "content": "Final forensic synthesis.",
            "tool_calls": []
        }
        
        # Construct messages to exceed context limit and trigger self-healing (summarization + dropping)
        # Note: non-protected messages will be eligible for summarization and dropping.
        history = [
            {"id": "h1", "role": "user", "content": "A very long user message " * 20, "metadata": {}},
            {"id": "h2", "role": "assistant", "content": "A very long assistant response " * 20, "metadata": {}},
            {"id": "h3", "role": "user", "content": "Another long user message " * 20, "metadata": {}},
        ]
        self.cm.history_manager.history = history
        self.cm.history_manager.pop_last_message.return_value = None
        
        # We need mock of context_manager._build_system_prompt
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        self.cm._parse_tool_calls.return_value = []

        # Run process_query
        self.processor.process_query("Tell me about the execution pattern")
        
        # Flush auditor
        self.cm.truncation_auditor._flush_buffer()
        events = self.cm.truncation_auditor.get_events()
        
        # We expect SUMMARIZED or TRUNCATED events
        summarized_events = [e for e in events if e["action"] == "SUMMARIZED"]
        truncated_events = [e for e in events if e["action"] == "TRUNCATED"]
        
        self.assertTrue(len(summarized_events) > 0 or len(truncated_events) > 0)
        
        # Verify that for any summarization/dropping event, the "cut_content" and "processed_content" metadata is populated
        for event in summarized_events:
            self.assertIn("cut_content", event["metadata"])
            self.assertTrue(len(event["metadata"]["cut_content"]) > 0)
            self.assertIn("processed_content", event["metadata"])
            self.assertEqual(event["metadata"]["processed_content"], "History summary")
            
        for event in truncated_events:
            self.assertIn("cut_content", event["metadata"])
            self.assertTrue(len(event["metadata"]["cut_content"]) > 0)
            self.assertIn("processed_content", event["metadata"])
            self.assertEqual(event["metadata"]["processed_content"], "")

        # Verify that the EvidenceSeal record also contains these cut details
        seal_log_path = Path(self.temp_dir) / "EYE_Logs" / "eye_payload_seal.jsonl"
        self.assertTrue(seal_log_path.exists())
        seal_records = []
        with open(seal_log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seal_records.append(json.loads(line.strip()))
        
        # At least one seal record should have captured the cut details
        self.assertTrue(len(seal_records) > 0)
        has_cut_details = False
        for rec in seal_records:
            if rec.get("cut_details"):
                has_cut_details = True
                self.assertTrue(any(c["action"] in ("SUMMARIZED", "TRUNCATED") for c in rec["cut_details"]))
                self.assertTrue(any(len(c["cut_content"]) > 0 for c in rec["cut_details"]))
                self.assertTrue(any(c["processed_content"] == ("History summary" if c["action"] == "SUMMARIZED" else "") for c in rec["cut_details"]))
        self.assertTrue(has_cut_details)

    @patch("time.sleep", return_value=None)
    def test_refused_overflow_is_sealed(self, mock_sleep):
        # When the Eye shrinks a payload (summarize) but the irreducible evidence
        # core STILL overflows, it refuses (ContextOverflowError). The refused
        # over-limit payload must still be sealed — flagged sent_to_model=False —
        # carrying the self-heal cut details, so the Compliance panels are not
        # empty for exactly the scenario where the most shrinking happened.
        self.cm.max_total_tokens = 500  # usable ~250 after the 10% (min 512 -> half) reserve

        # A protected (evidence) message that alone exceeds the usable window and
        # cannot be dropped, plus two droppable messages that WILL be summarized
        # (producing cut details) before the hard refusal.
        history = [
            {"id": "e1", "role": "tool", "content": "EVIDENCE_ROW_DATA " * 300,
             "metadata": {"is_tool_result": True}},
            {"id": "h1", "role": "user", "content": "chatter " * 40, "metadata": {}},
            {"id": "h2", "role": "assistant", "content": "more chatter " * 40, "metadata": {}},
        ]
        self.cm.history_manager.history = history
        self.cm.history_manager.pop_last_message.return_value = None
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        self.cm._parse_tool_calls.return_value = []

        result = self.processor.process_query("Tell me everything about this case")

        # The turn must be refused, not silently truncated, and the model must
        # never have been called for the over-limit payload.
        self.assertEqual(result.get("error"), "context_overflow")
        self.cm.model_router.generate.assert_not_called()

        # A REFUSED_OVERFLOW audit event is still recorded.
        self.cm.truncation_auditor._flush_buffer()
        events = self.cm.truncation_auditor.get_events()
        self.assertTrue(any(e["action"] == "REFUSED_OVERFLOW" for e in events))

        # The refused payload was sealed: a record with sent_to_model == False,
        # truncated == True, a REFUSED_OVERFLOW phase, and non-empty cut_details.
        seal_log_path = Path(self.temp_dir) / "EYE_Logs" / "eye_payload_seal.jsonl"
        self.assertTrue(seal_log_path.exists())
        seal_records = []
        with open(seal_log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seal_records.append(json.loads(line.strip()))

        refused = [r for r in seal_records if r.get("sent_to_model") is False]
        self.assertTrue(len(refused) > 0, "refused over-limit payload was not sealed")
        rec = refused[-1]
        self.assertTrue(rec.get("truncated"))
        self.assertIn("REFUSED_OVERFLOW", rec.get("phase", ""))
        self.assertTrue(rec.get("cut_details"), "refused seal lost its self-heal cut details")
        self.assertTrue(any(c["action"] in ("SUMMARIZED", "TRUNCATED") for c in rec["cut_details"]))

        # The hash chain still verifies end-to-end including the refused seal.
        prev = ""
        for s in seal_records:
            expected = EvidenceSeal._sha256(prev + s["payload_sha256"] + s["metadata_sha256"])
            self.assertEqual(s["prev_seal_hash"], prev)
            self.assertEqual(s["seal_hash"], expected)
            prev = s["seal_hash"]

    @patch("time.sleep", return_value=None)
    def test_transient_retry_uses_sealed_slimmed_payload(self, mock_sleep):
        # A transient model error must be retried with the SAME slimmed history
        # that was sealed (`working`), not the original un-slimmed `history` —
        # otherwise the model sees a payload that doesn't match its seal and may
        # re-overflow. We force self-heal (small window + long messages) so the
        # slimmed payload genuinely differs from the original, then make the
        # first generate() call fail transiently.
        self.cm.max_total_tokens = 500  # usable ~250 -> forces summarization
        history = [
            {"id": "h1", "role": "user", "content": "A very long user message " * 20, "metadata": {}},
            {"id": "h2", "role": "assistant", "content": "A very long assistant response " * 20, "metadata": {}},
            {"id": "h3", "role": "user", "content": "Another long user message " * 20, "metadata": {}},
        ]
        self.cm.history_manager.history = history
        self.cm.history_manager.pop_last_message.return_value = None
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        self.cm._parse_tool_calls.return_value = []

        call_count = {"n": 0}

        def gen_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("503 UNAVAILABLE - temporarily unavailable")
            return {"content": "Final synthesis.", "tool_calls": []}

        self.cm.model_router.generate.side_effect = gen_side_effect

        self.processor.process_query("Tell me about the execution pattern")

        calls = self.cm.model_router.generate.call_args_list
        self.assertGreaterEqual(len(calls), 2, "expected a transient call plus a retry")
        first_history = calls[0].kwargs.get("history")
        retry_history = calls[1].kwargs.get("history")
        # The retry must send the exact slimmed payload that was sealed...
        self.assertEqual(first_history, retry_history)
        # ...and that slimmed payload must be smaller than the original history
        # (proves self-heal happened and we did NOT fall back to `history`).
        self.assertLess(len(retry_history), len(history))

    @patch("time.sleep", return_value=None)
    def test_tool_output_truncation_logging_cut_content(self, mock_sleep):
        # We want to test that when a tool returns a huge output (> 10,000 characters),
        # the portion beyond 10,000 characters is cut and logged under "cut_content".
        self.cm.max_total_tokens = 32000
        self.cm.max_tool_output_chars = 10000
        
        # Set up mocks so the loop executes once and calls a tool
        self.cm.model_router.generate.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "query_database", "arguments": "{}"}
                    }
                ]
            },
            {
                "content": "Final forensic synthesis after tools.",
                "tool_calls": []
            }
        ]
        
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        
        # Use a helper function instead of a raw list to handle multiple calls correctly
        def mock_parse_tool_calls(response):
            if response and "tool_calls" in response and response["tool_calls"]:
                tc_item = response["tool_calls"][0]
                return [{"name": tc_item["function"]["name"], "parameters": json.loads(tc_item["function"]["arguments"])}]
            return []
            
        self.cm._parse_tool_calls.side_effect = mock_parse_tool_calls
        
        # A huge tool result (> 10k characters)
        huge_result = {"success": True, "tool_name": "query_database", "data": "A" * 15000}
        self.cm._execute_tool.return_value = huge_result
        self.cm.history_manager.pop_last_message.return_value = None

        # Run process_query
        self.processor.process_query("Query DB")
        
        # Flush auditor
        self.cm.truncation_auditor._flush_buffer()
        events = self.cm.truncation_auditor.get_events()
        
        # We expect a TRUNCATED event specifically for the tool output capping
        tool_trunc_events = [
            e for e in events 
            if e["action"] == "TRUNCATED" and e["id"].startswith("tool-output-iter-")
        ]
        
        self.assertEqual(len(tool_trunc_events), 1)
        event = tool_trunc_events[0]
        self.assertEqual(event["reason"], "tool_output_memory_cap_10000_chars")
        
        # Check that the metadata captures the cut content. The inline value is
        # now a bounded preview (CUT_PREVIEW_CHARS); the full bytes are recorded
        # via length + hash + sidecar.
        self.assertIn("cut_content", event["metadata"])
        self.assertIn("processed_content", event["metadata"])
        cap = EvidenceSeal.CUT_PREVIEW_CHARS
        # The cut content should be the characters beyond index 10,000 of the json-serialized output
        tool_output_str = json.dumps([huge_result], indent=2)
        expected_cut = tool_output_str[10000:]
        expected_processed = tool_output_str[:10000]
        self.assertEqual(event["metadata"]["cut_content"], expected_cut[:cap])
        self.assertEqual(event["metadata"]["cut_content_len"], len(expected_cut))
        self.assertEqual(event["metadata"]["cut_content_sha256"], EvidenceSeal._sha256(expected_cut))
        self.assertEqual(event["metadata"]["processed_content"], expected_processed[:cap])
        # The full dropped bytes must be recoverable from the sidecar file.
        sidecar_rel = event["metadata"]["cut_content_sidecar"]
        self.assertTrue(sidecar_rel)
        sidecar_path = Path(self.temp_dir) / "EYE_Logs" / sidecar_rel
        self.assertTrue(sidecar_path.exists())
        with open(sidecar_path, "r", encoding="utf-8") as sf:
            self.assertEqual(sf.read(), expected_cut)
        # Explicit char-range of the cut within the original message.
        self.assertEqual(event["metadata"]["cut_range"]["processed"], [0, 10000])
        self.assertEqual(event["metadata"]["cut_range"]["dropped"], [10000, len(tool_output_str)])

        # Verify that the EvidenceSeal record also contains the tool output truncation details
        seal_log_path = Path(self.temp_dir) / "EYE_Logs" / "eye_payload_seal.jsonl"
        self.assertTrue(seal_log_path.exists())
        seal_records = []
        with open(seal_log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seal_records.append(json.loads(line.strip()))
        # At least one seal record should have captured the tool output truncation in its cut_details
        self.assertTrue(len(seal_records) > 0)
        has_tool_truncation = False
        for rec in seal_records:
            if rec.get("cut_details"):
                for detail in rec["cut_details"]:
                    if detail.get("action") == "TRUNCATED_TOOL_OUTPUT":
                        has_tool_truncation = True
                        self.assertEqual(detail["cut_content"], expected_cut[:cap])
                        self.assertEqual(detail["cut_content_len"], len(expected_cut))
                        self.assertEqual(detail["processed_content"], expected_processed[:cap])
        self.assertTrue(has_tool_truncation)

    @patch("time.sleep", return_value=None)
    def test_tool_output_truncation_adaptive_and_hot_reload(self, mock_sleep):
        # Test adaptive capping for a small context window
        self.cm.max_total_tokens = 500  # small context
        self.cm.max_tool_output_chars = 100000  # base character limit
        
        self.cm.model_router.generate.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "query_database", "arguments": "{}"}
                    }
                ]
            },
            {
                "content": "Final synthesis",
                "tool_calls": []
            }
        ]
        
        def mock_parse_tool_calls(response):
            if response and "tool_calls" in response and response["tool_calls"]:
                tc_item = response["tool_calls"][0]
                return [{"name": tc_item["function"]["name"], "parameters": json.loads(tc_item["function"]["arguments"])}]
            return []
        self.cm._parse_tool_calls.side_effect = mock_parse_tool_calls
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        
        huge_result = {"success": True, "tool_name": "query_database", "data": "A" * 6000}
        self.cm._execute_tool.return_value = huge_result
        self.cm.history_manager.pop_last_message.return_value = None

        self.processor.process_query("Query DB")
        
        self.cm.truncation_auditor._flush_buffer()
        events = self.cm.truncation_auditor.get_events()
        
        tool_events = [
            e for e in events
            if e["action"] == "TRUNCATED" and e["id"].startswith("tool-output-iter-")
        ]
        self.assertTrue(len(tool_events) > 0)
        self.assertEqual(tool_events[-1]["reason"], "tool_output_memory_cap_4000_chars")

    @patch("time.sleep", return_value=None)
    @patch.object(EvidenceSeal, "seal", side_effect=RuntimeError("disk full"))
    def test_seal_failure_records_marker(self, mock_seal, mock_sleep):
        # If the evidence seal cannot be written, the gap must NOT be swallowed:
        # a visible SEAL_FAILED marker is recorded in the audit trail.
        self.cm.model_router.generate.return_value = {
            "content": "Final synthesis.",
            "tool_calls": []
        }
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        self.cm._parse_tool_calls.return_value = []
        self.cm.history_manager.history = []
        self.cm.history_manager.pop_last_message.return_value = None

        self.processor.process_query("Tell me what happened")

        self.cm.truncation_auditor._flush_buffer()
        events = self.cm.truncation_auditor.get_events()
        seal_failed = [e for e in events if e["action"] == "SEAL_FAILED"]
        self.assertTrue(len(seal_failed) >= 1)
        self.assertEqual(seal_failed[0]["reason"], "evidence_seal_write_error")
        self.assertIn("disk full", seal_failed[0]["metadata"].get("error", ""))

    @patch("time.sleep", return_value=None)
    def test_no_duplicate_tool_truncations_across_seals(self, mock_sleep):
        # Two tool-calling iterations each cap a huge tool output. Each cap must
        # be sealed exactly once, not re-attached to every later per-iteration
        # seal in the same turn.
        self.cm.max_total_tokens = 32000
        self.cm.max_tool_output_chars = 10000
        # Distinct arguments so the loop's cycle-detector doesn't treat the
        # second identical call as a repeat and break early.
        self.cm.model_router.generate.side_effect = [
            {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                "function": {"name": "query_database", "arguments": "{\"q\": \"first\"}"}}]},
            {"content": "", "tool_calls": [{"id": "c2", "type": "function",
                "function": {"name": "query_database", "arguments": "{\"q\": \"second\"}"}}]},
            {"content": "Final synthesis after two tools.", "tool_calls": []},
        ]

        def mock_parse(response):
            if response and response.get("tool_calls"):
                tc = response["tool_calls"][0]
                return [{"name": tc["function"]["name"], "parameters": json.loads(tc["function"]["arguments"])}]
            return []
        self.cm._parse_tool_calls.side_effect = mock_parse
        self.cm._build_system_prompt.return_value = "System prompt"
        self.cm._get_tool_definitions.return_value = []
        self.cm.history_manager.history = []
        self.cm.history_manager.pop_last_message.return_value = None
        self.cm._execute_tool.return_value = {"success": True, "tool_name": "query_database", "data": "A" * 15000}

        self.processor.process_query("Query DB twice")

        seal_log_path = Path(self.temp_dir) / "EYE_Logs" / "eye_payload_seal.jsonl"
        self.assertTrue(seal_log_path.exists())
        counts = {}
        with open(seal_log_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                for d in rec.get("cut_details", []):
                    if d.get("action") == "TRUNCATED_TOOL_OUTPUT":
                        counts[d["message_id"]] = counts.get(d["message_id"], 0) + 1

        # Two distinct tool truncations, each sealed exactly once.
        self.assertEqual(len(counts), 2, f"expected 2 distinct tool truncations, got {counts}")
        for mid, c in counts.items():
            self.assertEqual(c, 1, f"{mid} sealed {c} times (expected exactly once)")


class TestApiKeyRedaction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.auditor = TruncationAuditor(self.temp_dir)
        self.seal = EvidenceSeal(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_auditor_redacts_api_key(self):
        # Log a summarized event containing a Gemini API key
        self.auditor.log_event(
            action="SUMMARIZED",
            message_id="msg_123",
            token_count=100,
            reason="budget_exceeded",
            message_hash="abcde12345",
            metadata={
                "cut_content": "User prompt containing key AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0 inside it."
            }
        )
        self.auditor._flush_buffer()

        events = self.auditor.get_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        # Verify the key is redacted
        self.assertNotIn("AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0", event["metadata"]["cut_content"])
        self.assertIn("[REDACTED_API_KEY]", event["metadata"]["cut_content"])

    def test_evidence_seal_redacts_api_key(self):
        cut_details = [
            {
                "action": "TRUNCATED",
                "message_id": "msg_999",
                "role": "user",
                "token_count": 50,
                "sha256": "abcdef",
                "cut_content": "Key here: AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0",
                "processed_content": "Clean summary text"
            }
        ]
        record = self.seal.seal(
            payload_text="System: act forensicly. User: query with AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0",
            phase="request",
            iteration=1,
            query="Analyze AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0 API key",
            model="gemini-pro",
            max_context=8192,
            token_count=100,
            evidence_refs=[{"tool": "query_database", "database": "SecurityLogs.db", "sql": "SELECT AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0"}],
            truncated=True,
            cut_details=cut_details
        )

        # Check all fields containing key are redacted
        self.assertNotIn("AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0", record["query"])
        self.assertIn("[REDACTED_API_KEY]", record["query"])

        self.assertNotIn("AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0", record["cut_details"][0]["cut_content"])
        self.assertIn("[REDACTED_API_KEY]", record["cut_details"][0]["cut_content"])

        self.assertNotIn("AIzaSyDUMMY_TEST_KEY_NOT_A_REAL_SECRET0", record["evidence_refs"][0]["sql"])
        self.assertIn("[REDACTED_API_KEY]", record["evidence_refs"][0]["sql"])

        # Hashed payload should also be on the redacted text
        expected_sha = EvidenceSeal._sha256("System: act forensicly. User: query with [REDACTED_API_KEY]")
        self.assertEqual(record["payload_sha256"], expected_sha)


class TestDroppedPayloadOffsetExtraction(unittest.TestCase):
    def test_extract_offsets_from_text(self):
        # Scan text for record numbers and computed file offsets
        text = 'MFT record details: "record_number": 12345, "computed_file_offset": 12641280. Also record_number = 6789.'
        offsets = EvidenceSeal.extract_offsets_from_text(text)
        
        # We expect record_number 12345 to map to 12345 * 1024 = 12641280
        # and record_number 6789 to map to 6789 * 1024 = 6951936.
        # The literal "computed_file_offset": 12641280 is also captured as its
        # own FILE_OFFSET marker, so the text yields 3 markers total.
        self.assertEqual(len(offsets), 3)

        # Check that we found record_number 12345
        item1 = next(o for o in offsets if o.get("record_number") == 12345)
        self.assertEqual(item1["computed_file_offset"], 12641280)
        self.assertEqual(item1["record_size"], 1024)
        
        # Check that we found record_number 6789
        item2 = next(o for o in offsets if o.get("record_number") == 6789)
        self.assertEqual(item2["computed_file_offset"], 6789 * 1024)

    def test_extract_offsets_ipv4_validation(self):
        # Invalid octets (>255) must NOT produce NETWORK_IP.
        bad = EvidenceSeal.extract_offsets_from_text("ver 999.999.999.999 and 256.300.1.1")
        self.assertFalse(any(o.get("type") == "NETWORK_IP" for o in bad))
        # A genuine IPv4 still surfaces.
        good = EvidenceSeal.extract_offsets_from_text("remote_host connected to 192.168.1.100 now")
        self.assertTrue(any(o.get("ip") == "192.168.1.100" for o in good))

    def test_extract_offsets_scan_bound(self):
        # A marker in the tail of an over-cap blob is still found (tail scan)...
        cap = EvidenceSeal.OFFSET_SCAN_MAX_CHARS
        tail_text = ("x" * (cap + 50000)) + ' record_number: 7777 '
        res = EvidenceSeal.extract_offsets_from_text(tail_text)
        self.assertTrue(any(o.get("record_number") == 7777 for o in res))
        # ...but a marker buried only in the deep middle is intentionally skipped
        # (the full bytes remain recoverable from the sidecar).
        mid_text = ("a" * cap) + ' record_number: 5555 ' + ("b" * cap)
        res2 = EvidenceSeal.extract_offsets_from_text(mid_text)
        self.assertFalse(any(o.get("record_number") == 5555 for o in res2))

    @patch("time.sleep", return_value=None)
    def test_tool_output_truncation_extracts_offsets(self, mock_sleep):
        # Set up mocks so the loop executes once and calls a tool
        temp_dir = tempfile.mkdtemp()
        try:
            cm = MagicMock()
            cm.case_directory = temp_dir
            cm.truncation_auditor = TruncationAuditor(temp_dir)
            cm.evidence_seal = EvidenceSeal(temp_dir)
            cm.token_counter = TokenCounter(backend="gpt-4")
            cm.max_total_tokens = 500
            cm.token_budget = {
                "conversation_history": 200,
                "system_prompt": 100,
                "rag_context": 50,
                "tool_results": 100
            }
            cm.history_manager = MagicMock()
            cm.history_manager.history = []
            cm.history_manager.pop_last_message.return_value = None
            
            cm.intent_engine = MagicMock()
            cm.intent_engine.detect_keywords.return_value = []
            cm.rag_service = MagicMock()
            cm.rag_service.retrieve_context.return_value = ""
            cm.model_router = MagicMock()
            cm.model_router.config = {"model_name": "mock-model"}
            cm.report_engine = MagicMock()
            cm.report_engine.get_report_json.return_value = {"metadata": {"block_count": 0}}
            
            processor = QueryProcessor(cm)
            
            cm.model_router.generate.side_effect = [
                {
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "query_database", "arguments": "{}"}}
                    ]
                },
                {"content": "Synthesis", "tool_calls": []}
            ]
            cm._build_system_prompt.return_value = "System prompt"
            cm._get_tool_definitions.return_value = []
            
            def mock_parse_tool_calls(response):
                if response and "tool_calls" in response and response["tool_calls"]:
                    tc_item = response["tool_calls"][0]
                    return [{"name": tc_item["function"]["name"], "parameters": json.loads(tc_item["function"]["arguments"])}]
                return []
            cm._parse_tool_calls.side_effect = mock_parse_tool_calls
            
            # A huge tool result containing a specific record_number in the portion that will get cut
            # Index 10,000+ will contain the record number
            data_part = "A" * 10500 + ' "record_number": 8888 ' + "B" * 5000
            huge_result = {"success": True, "tool_name": "query_database", "data": data_part}
            cm._execute_tool.return_value = huge_result
            
            processor.process_query("Query")
            
            # Flush auditor
            cm.truncation_auditor._flush_buffer()
            events = cm.truncation_auditor.get_events()
            
            # Check event has the dropped-portion offsets in metadata. The
            # record_number lands in the cut tail, so it surfaces under
            # dropped_file_offsets.
            tool_events = [e for e in events if e["action"] == "TRUNCATED" and e["id"].startswith("tool-output-iter-")]
            self.assertEqual(len(tool_events), 1)
            meta = tool_events[0]["metadata"]
            self.assertIn("dropped_file_offsets", meta)
            self.assertTrue(len(meta["dropped_file_offsets"]) > 0)
            self.assertEqual(meta["dropped_file_offsets"][0]["record_number"], 8888)
            self.assertEqual(meta["dropped_file_offsets"][0]["computed_file_offset"], 8888 * 1024)
            
            # Check evidence seal has it too
            seal_log_path = Path(temp_dir) / "EYE_Logs" / "eye_payload_seal.jsonl"
            self.assertTrue(seal_log_path.exists())
            seal_records = []
            with open(seal_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        seal_records.append(json.loads(line.strip()))
            
            has_offset = False
            for record in seal_records:
                for detail in record.get("cut_details", []):
                    if detail.get("action") == "TRUNCATED_TOOL_OUTPUT" and "dropped_file_offsets" in detail:
                        offsets = detail["dropped_file_offsets"]
                        if any(o.get("record_number") == 8888 for o in offsets):
                            has_offset = True
            self.assertTrue(has_offset)
            
        finally:
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
