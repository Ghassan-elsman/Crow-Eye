"""
Tests for RAGService.retrieve_context precedence (audit P2 #8).

Deterministic keyword-mapped docs take precedence and are always included;
semantic matches fill the remainder; dedup is by filename so a keyword-loaded
file is never duplicated by a semantic chunk.
"""

import logging
import unittest
from unittest.mock import MagicMock

from eye.services.rag_service import RAGService


def _make_rag(embedding_client=None, vector_index=None):
    rag = RAGService.__new__(RAGService)
    rag.logger = logging.getLogger("test-rag")
    rag.embedding_client = embedding_client
    rag.index_built = True
    rag.vector_index = vector_index or []
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


if __name__ == "__main__":
    unittest.main()
