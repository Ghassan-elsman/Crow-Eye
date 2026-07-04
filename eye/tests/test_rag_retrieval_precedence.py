"""
Tests for RAGService.retrieve_context precedence (audit P2 #8).

Deterministic keyword-mapped docs take precedence and are always included;
semantic matches fill the remainder; dedup is by filename so a keyword-loaded
file is never duplicated by a semantic chunk.
"""

import json
import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from eye.services.rag_service import RAGService, _chunk_markdown


def _make_rag(embedding_client=None, vector_index=None, lexical_index=None):
    rag = RAGService.__new__(RAGService)
    rag.logger = logging.getLogger("test-rag")
    rag.embedding_client = embedding_client
    rag.index_built = True
    rag.vector_index = vector_index or []
    # Lexical (BM25) fallback index — pre-built so retrieve_context never touches
    # disk in tests. Empty unless a test supplies chunks.
    rag.lexical_built = True
    rag.lexical_index = lexical_index or []
    rag.lexical_df = {}
    rag.lexical_avg_len = 0.0
    if rag.lexical_index:
        total = 0
        for ch in rag.lexical_index:
            total += ch["len"]
            for term in ch["tf"]:
                rag.lexical_df[term] = rag.lexical_df.get(term, 0) + 1
        rag.lexical_avg_len = total / len(rag.lexical_index)
    rag.last_sources = []
    rag.keyword_mapping = {
        "schema": "Global_schema_database_Reference.md",
        "database": "Global_schema_database_Reference.md",  # same file as 'schema'
        "evidence": "evidence_intelligence.md",
    }
    rag._load_knowledge_file = MagicMock(side_effect=lambda f: f"CONTENT[{f}]")
    return rag


class TestRetrieveContextPrecedence(unittest.TestCase):
    def test_keyword_docs_included_and_deduped_by_file(self):
        # No embedding client -> keyword-only path. 'schema' and 'database' map to
        # the SAME file and must be included exactly once; 'evidence' once.
        rag = _make_rag(embedding_client=None)
        out = rag.retrieve_context(keywords=["schema", "database", "evidence"],
                                   user_query="does the computer have games", max_tokens=5000)
        self.assertEqual(out.count("CONTENT[Global_schema_database_Reference.md]"), 1)
        self.assertIn("CONTENT[evidence_intelligence.md]", out)

    def test_semantic_does_not_duplicate_keyword_file(self):
        # Semantic index contains a chunk from the SAME file a keyword loaded
        # (must be skipped) plus a new file (must be added).
        emb = MagicMock()
        emb.embed_text.return_value = [1.0, 0.0]
        vindex = [
            {"filename": "Global_schema_database_Reference.md", "embedding": [1.0, 0.0], "content": "SCHEMA_CHUNK"},
            {"filename": "prefetch_knowledge.md", "embedding": [1.0, 0.0], "content": "PREFETCH_CHUNK"},
        ]
        rag = _make_rag(embedding_client=emb, vector_index=vindex)
        out = rag.retrieve_context(keywords=["schema"], user_query="prefetch execution", max_tokens=5000)

        # Keyword file present once; its semantic chunk de-duplicated away.
        self.assertEqual(out.count("CONTENT[Global_schema_database_Reference.md]"), 1)
        self.assertNotIn("SCHEMA_CHUNK", out)
        # The genuinely-new semantic file is included.
        self.assertIn("PREFETCH_CHUNK", out)

    def test_empty_when_nothing_matches(self):
        rag = _make_rag(embedding_client=None)
        rag._load_knowledge_file = MagicMock(return_value="")
        self.assertEqual(rag.retrieve_context(keywords=["unknown_kw"], user_query="x"), "")

    def test_lexical_ranker_without_embeddings(self):
        # No embedding client -> the built-in BM25 lexical ranker provides ranked
        # retrieval. The relevant chunk is included; an irrelevant one is not;
        # last_sources reflects what was consulted.
        lex = [
            {"filename": "prefetch_knowledge.md", "content": "PREFETCH_LEX",
             "tf": {"prefetch": 3, "execution": 1}, "len": 10},
            {"filename": "mft_knowledge.md", "content": "MFT_LEX",
             "tf": {"mft": 2, "file": 1}, "len": 8},
        ]
        rag = _make_rag(embedding_client=None, lexical_index=lex)
        out = rag.retrieve_context(keywords=[], user_query="prefetch execution timeline",
                                   max_tokens=5000, top_k=5, min_score=0.0)
        self.assertIn("PREFETCH_LEX", out)
        self.assertNotIn("MFT_LEX", out)
        self.assertIn("prefetch_knowledge.md", rag.last_sources)

    def test_lexical_does_not_duplicate_keyword_file(self):
        # A lexical chunk from a file already loaded by a keyword is de-duplicated.
        lex = [
            {"filename": "evidence_intelligence.md", "content": "EVIDENCE_LEX",
             "tf": {"evidence": 2, "intelligence": 1}, "len": 6},
        ]
        rag = _make_rag(embedding_client=None, lexical_index=lex)
        out = rag.retrieve_context(keywords=["evidence"], user_query="evidence intelligence",
                                   max_tokens=5000, top_k=5, min_score=0.0)
        self.assertEqual(out.count("CONTENT[evidence_intelligence.md]"), 1)
        self.assertNotIn("EVIDENCE_LEX", out)


class TestSemanticMinScoreThreshold(unittest.TestCase):
    def test_configurable_cosine_cutoff(self):
        emb = MagicMock()
        emb.embed_text.return_value = [1.0, 0.0]
        vindex = [
            {"filename": "prefetch_knowledge.md", "embedding": [1.0, 0.0], "content": "HIGH_SIM"},
            {"filename": "mft_knowledge.md", "embedding": [0.3, 0.95], "content": "LOW_SIM"},
        ]
        rag = _make_rag(embedding_client=emb, vector_index=vindex)
        # Default cutoff (0.4) keeps the ~1.0 match, drops the ~0.30 one.
        out = rag.retrieve_context(keywords=[], user_query="prefetch", max_tokens=5000, top_k=5)
        self.assertIn("HIGH_SIM", out)
        self.assertNotIn("LOW_SIM", out)
        # Loosening the cutoff lets the weak match through.
        out2 = rag.retrieve_context(keywords=[], user_query="prefetch", max_tokens=5000,
                                    top_k=5, semantic_min_score=0.1)
        self.assertIn("LOW_SIM", out2)


class TestHeaderAwareChunking(unittest.TestCase):
    def test_header_prefixed_and_section_split(self):
        md = ("## Prefetch\nPrefetch records execution.\n\nIt stores up to 8 run times.\n\n"
              "## MFT\nThe MFT indexes files on NTFS volumes here.")
        chunks = _chunk_markdown(md, min_chars=10, max_chars=10000)
        self.assertTrue(any(c.startswith("## Prefetch") and "execution" in c for c in chunks))
        self.assertTrue(any(c.startswith("## MFT") for c in chunks))
        # Different sections never bleed into the same chunk.
        self.assertFalse(any("Prefetch" in c and "MFT" in c for c in chunks))

    def test_long_section_is_subsplit_keeping_header(self):
        body = "\n\n".join(f"Paragraph number {i} carrying enough words to count." for i in range(20))
        chunks = _chunk_markdown("## Big\n" + body, min_chars=10, max_chars=200)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.startswith("## Big") for c in chunks))


class TestConversationRecall(unittest.TestCase):
    def _rag(self):
        d = tempfile.mkdtemp()
        return RAGService(knowledge_base_dir=d), d

    def test_retrieve_ranks_relevant_turn(self):
        rag, _ = self._rag()
        rag.index_conversation_turn(
            "The malware dropper wrote evil.exe to C:/temp",
            {"id": "m1", "role": "assistant", "timestamp": "t1"})
        rag.index_conversation_turn(
            "We discussed lunch options and the weather",
            {"id": "m2", "role": "user", "timestamp": "t2"})
        out = rag.retrieve_conversation("where was evil.exe dropped", top_k=1)
        self.assertIn("evil.exe", out)
        self.assertNotIn("lunch", out)
        self.assertEqual(rag.last_conversation_sources, ["m1"])

    def test_empty_when_no_archive(self):
        rag, _ = self._rag()
        self.assertEqual(rag.retrieve_conversation("anything at all"), "")
        self.assertEqual(rag.last_conversation_sources, [])

    def test_load_archive_rebuilds_index(self):
        rag, d = self._rag()
        path = os.path.join(d, "eye_conversation_archive.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "role": "assistant",
                                "content": "powershell encoded base64 command executed",
                                "timestamp": "t"}) + "\n")
            f.write(json.dumps({"id": "a2", "role": "user",
                                "content": "unrelated small talk", "timestamp": "t"}) + "\n")
        rag.load_conversation_archive(path)
        self.assertEqual(len(rag.conversation_index), 2)
        out = rag.retrieve_conversation("powershell base64 encoded", top_k=1)
        self.assertIn("powershell", out)
        self.assertEqual(rag.last_conversation_sources, ["a1"])


if __name__ == "__main__":
    unittest.main()
