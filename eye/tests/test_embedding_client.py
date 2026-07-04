"""
Tests for the embedding client (nomic v1.5 task prefixes) and the RAG embedding
disk cache + vector-vs-BM25 path selection.
"""

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from eye.services.rag_service import OllamaEmbeddingClient, RAGService


class TestEmbeddingPrefixes(unittest.TestCase):
    def test_nomic_prefixes_auto_applied(self):
        sent = {}

        client = OllamaEmbeddingClient(model_name="nomic-embed-text")
        self.assertEqual(client.query_prefix, "search_query: ")
        self.assertEqual(client.document_prefix, "search_document: ")

        # Capture the prompt actually posted to Ollama.
        import eye.services.rag_service as rs

        def fake_post(url, json=None, timeout=None):
            sent["prompt"] = json["prompt"]
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"embedding": [0.1, 0.2]}
            return resp

        orig = rs.requests.post
        rs.requests.post = fake_post
        try:
            client.embed_text("evil.exe", is_query=True)
            self.assertTrue(sent["prompt"].startswith("search_query: "))
            client.embed_text("evil.exe", is_query=False)
            self.assertTrue(sent["prompt"].startswith("search_document: "))
        finally:
            rs.requests.post = orig

    def test_non_nomic_model_has_no_prefix(self):
        client = OllamaEmbeddingClient(model_name="all-minilm")
        self.assertEqual(client.query_prefix, "")
        self.assertEqual(client.document_prefix, "")


class TestVectorPathAndCache(unittest.TestCase):
    def _kb(self):
        d = Path(tempfile.mkdtemp())
        (d / "prefetch_knowledge.md").write_text(
            "## Prefetch\nPrefetch proves program execution and stores run counts.",
            encoding="utf-8")
        return d

    def test_uses_bm25_when_no_embedding_client(self):
        rag = RAGService(knowledge_base_dir=str(self._kb()), embedding_client=None)
        # No embedding client -> vector index never built; BM25 path is used.
        out = rag.retrieve_context(keywords=[], user_query="program execution", max_tokens=2000)
        self.assertIn("Prefetch", out)
        self.assertEqual(rag.vector_index, [])

    def test_vector_index_built_and_cached_to_disk(self):
        kb = self._kb()
        calls = {"n": 0}
        emb = MagicMock()

        def embed(text, is_query=False):
            calls["n"] += 1
            return [1.0, 0.0]
        emb.embed_text.side_effect = embed
        emb.model_name = "nomic-embed-text"

        rag = RAGService(knowledge_base_dir=str(kb), embedding_client=emb)
        rag._build_vector_index()
        self.assertTrue(rag.vector_index)
        first_calls = calls["n"]
        self.assertGreater(first_calls, 0)
        # Cache file written, namespaced by model.
        cache_file = kb / ".embcache" / "nomic-embed-text.json"
        self.assertTrue(cache_file.exists())

        # A fresh service over the same KB reuses the cache: no new embed calls.
        rag2 = RAGService(knowledge_base_dir=str(kb), embedding_client=emb)
        rag2._build_vector_index()
        self.assertEqual(calls["n"], first_calls, "embeddings should be served from disk cache")
        self.assertTrue(rag2.vector_index)


if __name__ == "__main__":
    unittest.main()
