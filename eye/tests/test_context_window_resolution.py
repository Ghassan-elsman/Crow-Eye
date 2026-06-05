"""
Tests for backend-driven context-window resolution.

Covers the precedence chain in ContextManager._resolve_context_window
(backend introspection -> static registry -> 64K fallback, with the lock
override) and each backend's get_context_window() parser.
"""

import logging
import types
import unittest
from unittest.mock import MagicMock

from eye.services.context_manager import ContextManager


class TestResolveContextWindowPrecedence(unittest.TestCase):
    def setUp(self):
        # Build a ContextManager shell without running the heavy __init__.
        self.cm = ContextManager.__new__(ContextManager)
        self.cm.logger = logging.getLogger("test-resolve")
        self.cm.lock_max_total_tokens = False
        self.cm.model_router = MagicMock()
        self.cm.model_router.config = {"backend": "anthropic", "model_name": "claude-opus-4-8"}

    def test_backend_introspection_wins_over_registry(self):
        # Backend reports 250000; registry would say 200000 for this model.
        self.cm.model_router.get_context_window.return_value = 250000
        self.assertEqual(self.cm._resolve_context_window(64000), 250000)

    def test_registry_used_when_backend_returns_none(self):
        self.cm.model_router.get_context_window.return_value = None
        self.assertEqual(self.cm._resolve_context_window(64000), 200000)  # claude-* registry

    def test_default_fallback_when_backend_and_registry_miss(self):
        self.cm.model_router.get_context_window.return_value = None
        self.cm.model_router.config = {"backend": "anthropic", "model_name": "totally-unknown-model"}
        self.assertEqual(self.cm._resolve_context_window(64000), 64000)

    def test_lock_returns_fallback_without_probing(self):
        self.cm.lock_max_total_tokens = True
        self.cm.model_router.get_context_window.return_value = 999999
        self.assertEqual(self.cm._resolve_context_window(64000), 64000)
        self.cm.model_router.get_context_window.assert_not_called()

    def test_introspection_exception_falls_back_to_registry(self):
        self.cm.model_router.get_context_window.side_effect = RuntimeError("boom")
        self.cm.model_router.config = {"backend": "openai", "model_name": "gpt-4o"}
        self.assertEqual(self.cm._resolve_context_window(64000), 128000)  # gpt-4o registry


def _fake_response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


class TestOllamaContextWindow(unittest.TestCase):
    def _backend(self):
        from eye.backends.local_server.ollama_backend import OllamaBackend
        b = OllamaBackend.__new__(OllamaBackend)
        b.logger = logging.getLogger("test-ollama")
        b.model_name = "llama3:8b"
        b.api_endpoint = "http://localhost:11434"
        b.connect_timeout = 5
        b.session = MagicMock()
        b._context_window_cache = None
        return b

    def test_parses_context_length(self):
        b = self._backend()
        b.session.post.return_value = _fake_response(
            200, {"model_info": {"llama.context_length": 131072, "llama.embedding_length": 4096}}
        )
        self.assertEqual(b.get_context_window(), 131072)

    def test_caches_result(self):
        b = self._backend()
        b.session.post.return_value = _fake_response(200, {"model_info": {"llama.context_length": 8192}})
        self.assertEqual(b.get_context_window(), 8192)
        b.get_context_window()
        self.assertEqual(b.session.post.call_count, 1)  # cached; not re-queried

    def test_failure_returns_none(self):
        b = self._backend()
        b.session.post.side_effect = Exception("connection refused")
        self.assertIsNone(b.get_context_window())


class TestLMStudioContextWindow(unittest.TestCase):
    def _backend(self):
        from eye.backends.local_server.lmstudio_backend import LMStudioBackend
        b = LMStudioBackend.__new__(LMStudioBackend)
        b.logger = logging.getLogger("test-lmstudio")
        b.model_name = "qwen2.5-7b"
        b.api_endpoint = "http://localhost:1234"
        b.connect_timeout = 5
        b.session = MagicMock()
        b._context_window_cache = None
        return b

    def test_prefers_loaded_context_length(self):
        b = self._backend()
        b.session.get.return_value = _fake_response(
            200, {"data": [{"id": "qwen2.5-7b", "loaded_context_length": 32768, "max_context_length": 40960}]}
        )
        self.assertEqual(b.get_context_window(), 32768)

    def test_falls_back_to_max_context_length(self):
        b = self._backend()
        b.session.get.return_value = _fake_response(
            200, {"data": [{"id": "qwen2.5-7b", "max_context_length": 40960}]}
        )
        self.assertEqual(b.get_context_window(), 40960)

    def test_404_returns_none(self):
        b = self._backend()
        b.session.get.return_value = _fake_response(404, {})
        self.assertIsNone(b.get_context_window())


class TestGeminiContextWindow(unittest.TestCase):
    def _backend(self):
        try:
            from eye.backends.cloud_api.gemini_backend import GeminiBackend
        except Exception as e:  # pragma: no cover - SDK not installed
            self.skipTest(f"Gemini SDK unavailable: {e}")
        b = GeminiBackend.__new__(GeminiBackend)
        b.logger = logging.getLogger("test-gemini")
        b.model_name = "gemini-1.5-pro"
        b._client = MagicMock()  # backs the lazy `client` property
        b._context_window_cache = None
        return b

    def test_parses_input_token_limit(self):
        b = self._backend()
        fake = types.SimpleNamespace(name="models/gemini-1.5-pro", input_token_limit=2097152)
        b._client.models.list.return_value = [fake]
        self.assertEqual(b.get_context_window(), 2097152)

    def test_failure_returns_none(self):
        b = self._backend()
        b._client.models.list.side_effect = Exception("auth error")
        self.assertIsNone(b.get_context_window())


if __name__ == "__main__":
    unittest.main()
