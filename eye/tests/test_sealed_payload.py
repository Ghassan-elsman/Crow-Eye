"""
Tests for full-sent-payload persistence with rolling compression (audit follow-up).

- The seal stores the full (redacted) payload to a per-hash sidecar.
- The most recent N stay uncompressed; older ones are compressed (zstd/gzip).
- Reading transparently decompresses; plaintext re-hashes to payload_sha256.
- Dedup by hash; off-switch; no sidecar when disabled.
"""

import os
import hashlib
import shutil
import tempfile
import unittest

from eye.services.evidence_seal import EvidenceSeal


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _seal(a, text, i):
    return a.seal(text, phase="synthesis", iteration=i, query="q",
                  model="m", max_context=100000, token_count=10)


class TestSealedPayloadPersistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.payload_dir = os.path.join(self.dir, "EYE_Logs", "sealed_payloads")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _variants(self, sha):
        base = os.path.join(self.payload_dir, f"{sha}.txt")
        return {
            "txt": os.path.exists(base),
            "zst": os.path.exists(base + ".zst"),
            "gz": os.path.exists(base + ".gz"),
        }

    def test_payload_stored_and_self_verifies(self):
        a = EvidenceSeal(self.dir, store_full_payload=True)
        rec = _seal(a, "FULL PAYLOAD CONTENT", 1)
        self.assertEqual(rec["payload_sidecar"], f"sealed_payloads/{rec['payload_sha256']}.txt")
        content = a.read_sealed_payload(rec["payload_sha256"])
        self.assertEqual(content, "FULL PAYLOAD CONTENT")
        # Independently reproducible: the stored plaintext re-hashes to the seal hash.
        self.assertEqual(_sha(content), rec["payload_sha256"])

    def test_recent_uncompressed_older_compressed(self):
        a = EvidenceSeal(self.dir, store_full_payload=True)
        a._recent_uncompressed = 2
        a._recent_payload_shas = []  # reset window for the smaller N
        recs = [_seal(a, f"PAYLOAD-{i}", i) for i in range(3)]
        # Oldest fell out of the window -> compressed; newest two stay .txt.
        old = self._variants(recs[0]["payload_sha256"])
        self.assertFalse(old["txt"])
        self.assertTrue(old["zst"] or old["gz"])
        for r in recs[1:]:
            self.assertTrue(self._variants(r["payload_sha256"])["txt"])
        # All three are still readable and hash-match (decompress transparently).
        for i, r in enumerate(recs):
            self.assertEqual(a.read_sealed_payload(r["payload_sha256"]), f"PAYLOAD-{i}")

    def test_dedup_same_payload_written_once(self):
        a = EvidenceSeal(self.dir, store_full_payload=True)
        r1 = _seal(a, "SAME", 1)
        r2 = _seal(a, "SAME", 2)
        self.assertEqual(r1["payload_sha256"], r2["payload_sha256"])
        v = self._variants(r1["payload_sha256"])
        self.assertEqual(sum(1 for k in ("txt", "zst", "gz") if v[k]), 1)

    def test_disabled_writes_no_sidecar(self):
        a = EvidenceSeal(self.dir, store_full_payload=False)
        rec = _seal(a, "X", 1)
        self.assertIsNone(rec["payload_sidecar"])
        self.assertFalse(os.path.isdir(self.payload_dir) and os.listdir(self.payload_dir))

    def test_reader_missing_returns_none(self):
        a = EvidenceSeal(self.dir, store_full_payload=True)
        self.assertIsNone(a.read_sealed_payload("0" * 64))

    def test_refused_payload_forced_and_previewed_even_when_disabled(self):
        # Routine storage OFF, but a REFUSED payload must STILL be persisted and
        # carry an inline original-message preview.
        a = EvidenceSeal(self.dir, store_full_payload=False)
        rec = a.seal("REFUSED ORIGINAL MESSAGE", phase="request:REFUSED_OVERFLOW",
                     iteration=1, query="q", model="m", max_context=100,
                     token_count=99999, sent_to_model=False, force_full_payload=True)
        # Sidecar written despite store_full_payload=False (the original is in the data).
        self.assertEqual(rec["payload_sidecar"], f"sealed_payloads/{rec['payload_sha256']}.txt")
        content = a.read_sealed_payload(rec["payload_sha256"])
        self.assertEqual(content, "REFUSED ORIGINAL MESSAGE")
        self.assertEqual(_sha(content), rec["payload_sha256"])
        # Bounded inline original preview present on the refused record.
        self.assertEqual(rec["payload_preview"], "REFUSED ORIGINAL MESSAGE")

    def test_sent_payload_has_no_preview(self):
        a = EvidenceSeal(self.dir, store_full_payload=True)
        rec = _seal(a, "SENT", 1)  # sent_to_model defaults True
        self.assertIsNone(rec["payload_preview"])


if __name__ == "__main__":
    unittest.main()
