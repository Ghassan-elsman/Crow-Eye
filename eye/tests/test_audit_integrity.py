"""
Tests for audit-trail integrity & durability (audit Pass 4):
- A1: the audit log is a tamper-evident hash chain (verify_chain).
- A2: audit events are written through to disk immediately.
- A3: history save is atomic (temp + os.replace), no .tmp residue.
"""

import os
import re
import json
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from eye.services.truncation_auditor import TruncationAuditor
from eye.services.history_manager import HistoryManager
from eye.services.evidence_seal import EvidenceSeal


def _seal_some(seal, n=3):
    for i in range(n):
        seal.seal(payload_text=f"payload-{i}", phase="request", iteration=i,
                  query="q", model="m", max_context=8192, token_count=10)


class TestEvidenceSealChain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _seal_log(self):
        return os.path.join(self.dir, "EYE_Logs", "eye_payload_seal.jsonl")

    def test_empty_log_is_vacuously_valid(self):
        self.assertTrue(EvidenceSeal(self.dir).verify_chain())

    def test_intact_chain_verifies(self):
        s = EvidenceSeal(self.dir)
        _seal_some(s, 3)
        self.assertTrue(s.verify_chain())
        # A fresh instance reading the same log also verifies.
        self.assertTrue(EvidenceSeal(self.dir).verify_chain())

    def test_tamper_is_detected(self):
        s = EvidenceSeal(self.dir)
        _seal_some(s, 3)
        log = self._seal_log()
        with open(log, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        rec = json.loads(lines[1])
        rec["payload_sha256"] = "0" * 64          # tamper a sealed sub-hash
        lines[1] = json.dumps(rec)
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.assertFalse(EvidenceSeal(self.dir).verify_chain())


def _log_some(auditor, n=3):
    for i in range(n):
        auditor.log_event(
            action="SUMMARIZED", message_id=f"m{i}", token_count=10 * i,
            reason="budget_exceeded", message_hash=f"hash{i}", metadata={"i": i},
        )


class TestAuditChain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _lines(self):
        log = os.path.join(self.dir, "EYE_Logs", "truncation_audit.log")
        with open(log, "r", encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]

    def test_every_line_is_chained_and_verifies(self):
        a = TruncationAuditor(self.dir)
        _log_some(a, 3)
        lines = self._lines()
        self.assertEqual(len(lines), 3)
        for ln in lines:
            self.assertRegex(ln, r" chain=[0-9a-f]{64}$")
        self.assertTrue(a.verify_chain())

    def test_tamper_is_detected(self):
        a = TruncationAuditor(self.dir)
        _log_some(a, 3)
        log = os.path.join(self.dir, "EYE_Logs", "truncation_audit.log")
        lines = self._lines()
        # Tamper the middle record's content but leave its recorded chain hash.
        lines[1] = lines[1].replace("reason=budget_exceeded", "reason=TAMPERED")
        with open(log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.assertFalse(TruncationAuditor(self.dir).verify_chain())

    def test_chain_resumes_across_sessions(self):
        a = TruncationAuditor(self.dir)
        _log_some(a, 2)
        # New instance on the same dir resumes the chain from disk.
        b = TruncationAuditor(self.dir)
        _log_some(b, 2)
        self.assertTrue(b.verify_chain())
        self.assertEqual(len(self._lines()), 4)


class TestAuditDurability(unittest.TestCase):
    def test_single_event_written_through(self):
        d = tempfile.mkdtemp()
        try:
            a = TruncationAuditor(d)
            # One event, well below the old buffer_max_size of 10.
            a.log_event(action="PINNED", message_id="x", token_count=1,
                        reason="manual", message_hash="h", metadata={})
            # Read the file directly WITHOUT calling get_events/flush.
            log = os.path.join(d, "EYE_Logs", "truncation_audit.log")
            with open(log, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("PINNED x", content)
            self.assertRegex(content.strip(), r" chain=[0-9a-f]{64}$")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestAtomicHistorySave(unittest.TestCase):
    def test_save_is_atomic_and_round_trips(self):
        d = tempfile.mkdtemp()
        try:
            hm = HistoryManager.__new__(HistoryManager)
            import threading, logging
            hm._lock = threading.RLock()
            hm.logger = logging.getLogger("test-hm")
            hm.cm = MagicMock()
            hm.cm.case_directory = d
            hm.history = [{"id": "a", "role": "user", "content": "hi", "metadata": {}}]

            hm.save_history()

            logs = os.path.join(d, "EYE_Logs")
            path = os.path.join(logs, "eye_conversation_history.json")
            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data[0]["id"], "a")
            # No temp residue left behind.
            self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(logs)))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
