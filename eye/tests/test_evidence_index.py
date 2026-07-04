"""
Tests for the EvidenceIndexService — per-case semantic discovery over forensic
data rows (additive to SQL; candidates carry database/table/rowid provenance).
"""

import tempfile
import unittest
from pathlib import Path

from eye.services.evidence_index_service import EvidenceIndexService


class FakeDB:
    """Minimal stand-in for ForensicDatabaseService."""
    def __init__(self, total=2):
        self._total = total

    def discover_databases(self):
        return [{"name": "prefetch_data.db", "category": "Prefetch",
                 "tables": ["prefetch_data"], "accessible": True, "exists": True}]

    def get_schema(self, db):
        return {"success": True, "tables": ["prefetch_data"],
                "schema": {"prefetch_data": ["path", "run_count"]},
                "row_counts": {"prefetch_data": self._total}}

    def execute_query(self, db, sql):
        return {"success": True, "columns": ["rowid", "path", "run_count"],
                "data": [
                    {"rowid": 1, "path": "C:/Windows/System32/anydesk.exe", "run_count": 5},
                    {"rowid": 2, "path": "C:/temp/notes.txt", "run_count": 1},
                ], "row_count": 2}


class FakeEmb:
    model_name = "nomic-embed-text"

    def embed_text(self, text, is_query=False):
        t = (text or "").lower()
        remote = 1.0 if any(k in t for k in ("anydesk", "remote", "teamviewer")) else 0.0
        doc = 1.0 if any(k in t for k in ("notes", "txt", "document")) else 0.0
        if remote == 0.0 and doc == 0.0:
            return [0.01, 0.01]
        return [remote, doc]


class TestEvidenceIndex(unittest.TestCase):
    def setUp(self):
        self.case = Path(tempfile.mkdtemp())

    def test_unavailable_without_embedding_client(self):
        svc = EvidenceIndexService(self.case, FakeDB(), embedding_client=None)
        self.assertFalse(svc.available())
        res = svc.search("anything")
        self.assertFalse(res["success"])
        self.assertEqual(res["candidates"], [])

    def test_build_and_search_with_provenance(self):
        svc = EvidenceIndexService(self.case, FakeDB(), FakeEmb())
        summary = svc.build()
        self.assertTrue(summary["built"])
        self.assertEqual(summary["indexed_rows"], 2)

        res = svc.search("remote access tools", top_k=1)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["candidates"]), 1)
        cand = res["candidates"][0]
        self.assertEqual(cand["database"], "prefetch_data.db")
        self.assertEqual(cand["table"], "prefetch_data")
        self.assertEqual(cand["rowid"], 1)  # the anydesk row
        self.assertIn("anydesk", cand["preview"].lower())
        self.assertIn("guidance", res)  # confirm-with-SQL hint present

    def test_persistence_round_trip(self):
        svc = EvidenceIndexService(self.case, FakeDB(), FakeEmb())
        svc.build()
        idx_file = svc._index_file()
        self.assertTrue(idx_file.exists())

        # A fresh service loads from disk instead of rebuilding.
        svc2 = EvidenceIndexService(self.case, FakeDB(), FakeEmb())
        out = svc2.build()
        self.assertTrue(out.get("from_cache"))
        self.assertEqual(out["indexed_rows"], 2)

    def test_capped_table_is_surfaced(self):
        # row_counts says 5 but the query returns 2 -> capped gap recorded.
        svc = EvidenceIndexService(self.case, FakeDB(total=5), FakeEmb())
        summary = svc.build()
        self.assertTrue(any(c["table"] == "prefetch_data" and c["total"] == 5
                            for c in summary["capped_tables"]))

    def test_lazy_build_on_search(self):
        svc = EvidenceIndexService(self.case, FakeDB(), FakeEmb())
        self.assertFalse(svc.built)
        res = svc.search("notes document", top_k=1)
        self.assertTrue(svc.built)
        self.assertTrue(res["success"])
        self.assertEqual(res["candidates"][0]["rowid"], 2)  # the notes.txt row


if __name__ == "__main__":
    unittest.main()
