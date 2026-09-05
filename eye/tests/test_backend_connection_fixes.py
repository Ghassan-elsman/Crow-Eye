"""
Connection-layer regressions: placeholder model resolution, OpenAI reasoning-model
parameters, LM Studio's actionable "no models loaded" error, and transient-vs-
permanent error classification.

Each test here pins a defect that was silent in production — the request either
succeeded-then-failed later (placeholder model), 400'd on every call (reasoning
models), or replaced actionable guidance with a bare status code (LM Studio).
"""

import json
import logging
import unittest
from unittest.mock import MagicMock

import requests

from eye.backends.cloud_api.openai_backend import OpenAIBackend
from eye.backends.local_server.lmstudio_backend import LMStudioBackend
from eye.services.model_router import (
    ModelRouter, is_placeholder_model, is_transient_model_error,
)


def _router_over(backend, config):
    """A ModelRouter wrapped around a fake backend, bypassing __init__'s factory."""
    router = ModelRouter.__new__(ModelRouter)
    router.logger = logging.getLogger("test-router")
    router.config = config
    router.credential_manager = None
    router.backend = backend
    return router


class _FakeBackend:
    def __init__(self, models=None):
        self._models = models or []

    def list_models(self):
        return list(self._models)

    def generate(self, *a, **kw):
        return {"content": "ok", "tool_calls": []}


# ---------------------------------------------------------------------------
# Placeholder model resolution
# ---------------------------------------------------------------------------

class TestPlaceholderModelResolution(unittest.TestCase):
    """The model menu's "Connect to <provider>…" rows carry model_name="default".
    Persisting that literally made every later request 404 — while the switch's
    connectivity check passed, because it only lists models."""

    def test_placeholder_detection(self):
        for name in ("", "default", "auto", "Default", "cli-default-model", None, "  "):
            self.assertTrue(is_placeholder_model(name), name)
        for name in ("gpt-4o", "claude-opus-4-8", "llama3:latest"):
            self.assertFalse(is_placeholder_model(name), name)

    def test_default_prefers_a_recommended_model_that_is_actually_available(self):
        """Not simply list_models()[0]. A provider's catalogue includes ids that
        404 on generate (verified live: Gemini lists gemini-2.5-flash-lite then
        rejects it as "no longer available to new users"), so we pick the
        intersection of live-and-recommended."""
        from eye.services.context_window_registry import recommended_models
        cfg = {"backend": "openai", "model_name": "gpt-4o", "integration_type": "cloud_api"}
        # A deprecated id first in the catalogue, then two good ones.
        router = _router_over(_FakeBackend(["gpt-3.5-turbo-0301", "gpt-4o", "gpt-4.1"]), cfg)
        router._initialize_backend = lambda: router.backend

        router.switch_model("default", backend="openai")

        self.assertEqual(cfg["model_name"], recommended_models("openai")[0])
        self.assertNotEqual(cfg["model_name"], "gpt-3.5-turbo-0301",
                            "resolver fell back to the first catalogue entry")
        self.assertFalse(is_placeholder_model(cfg["model_name"]))

    def test_default_uses_any_live_model_when_none_are_curated(self):
        """A provider we don't curate (e.g. a local server) still resolves."""
        cfg = {"backend": "lm_studio", "model_name": "", "integration_type": "local_server"}
        router = _router_over(_FakeBackend(["some-local-model"]), cfg)
        router._initialize_backend = lambda: router.backend

        router.switch_model("default", backend="lm_studio")
        self.assertEqual(cfg["model_name"], "some-local-model")

    def test_default_falls_back_to_the_curated_catalogue(self):
        """No live catalogue (no key yet / provider listing down) must still yield
        a real id rather than persisting the placeholder."""
        cfg = {"backend": "anthropic", "model_name": "", "integration_type": "cloud_api"}
        router = _router_over(_FakeBackend([]), cfg)
        router._initialize_backend = lambda: router.backend

        router.switch_model("default", backend="anthropic")

        from eye.services.context_window_registry import recommended_models
        self.assertEqual(cfg["model_name"], recommended_models("anthropic")[0])

    def test_unresolvable_placeholder_raises(self):
        """So the bridge reverts and tells the investigator, instead of leaving a
        model name no provider accepts."""
        cfg = {"backend": "openai", "model_name": "gpt-4o", "integration_type": "cloud_api"}
        router = _router_over(_FakeBackend([]), cfg)
        router._initialize_backend = lambda: router.backend

        # An unknown provider has no curated catalogue to fall back on.
        cfg["backend"] = "not-a-provider"
        with self.assertRaises(ValueError):
            router.switch_model("default", backend="not-a-provider")

    def test_local_cli_keeps_its_generic_name(self):
        """CLI agents deliberately run their own default when no model is given —
        resolution must not fight that."""
        cfg = {"backend": "gemini_cli", "model_name": "x", "integration_type": "local_cli"}
        router = _router_over(_FakeBackend([]), cfg)
        router._initialize_backend = lambda: router.backend

        router.switch_model("default")
        self.assertEqual(cfg["model_name"], "default")


# ---------------------------------------------------------------------------
# OpenAI reasoning models
# ---------------------------------------------------------------------------

class TestOpenAIReasoningParams(unittest.TestCase):
    """o3 / o4-mini ship in CURATED_MODELS and RECOMMENDED_MODELS, but the
    o-series rejects both `max_tokens` and any explicit temperature — so the
    wizard recommended models that 400'd on every single query."""

    def _capture_params(self, model_name):
        backend = OpenAIBackend(model_name, MagicMock())
        captured = {}

        message = MagicMock()
        message.content = "hello"
        message.tool_calls = []
        parsed = MagicMock()
        parsed.choices = [MagicMock(message=message)]
        raw = MagicMock()
        raw.headers = {}
        raw.parse.return_value = parsed

        def _create(**params):
            captured.update(params)
            return raw

        client = MagicMock()
        client.chat.completions.with_raw_response.create.side_effect = _create
        backend._client = client

        backend.generate("sys", "msg", gen_params={"temperature": 0.2,
                                                   "max_output_tokens": 4096,
                                                   "top_p": 0.9})
        return captured

    def test_reasoning_model_uses_max_completion_tokens_and_no_sampling(self):
        for model in ("o3", "o4-mini", "o1-preview", "gpt-5", "openai/o3-mini"):
            with self.subTest(model=model):
                params = self._capture_params(model)
                self.assertEqual(params.get("max_completion_tokens"), 4096)
                self.assertNotIn("max_tokens", params)
                self.assertNotIn("temperature", params)
                self.assertNotIn("top_p", params)

    def test_standard_model_keeps_max_tokens_and_sampling(self):
        for model in ("gpt-4o", "gpt-4.1", "llama-3.3-70b-versatile"):
            with self.subTest(model=model):
                params = self._capture_params(model)
                self.assertEqual(params.get("max_tokens"), 4096)
                self.assertEqual(params.get("temperature"), 0.2)
                self.assertEqual(params.get("top_p"), 0.9)
                self.assertNotIn("max_completion_tokens", params)


# ---------------------------------------------------------------------------
# LM Studio error surfacing
# ---------------------------------------------------------------------------

class TestLMStudioNoModelsLoaded(unittest.TestCase):
    """The four-step "load a model" guidance was raised INSIDE a try whose handler
    was a bare `except:` — so it caught its own RuntimeError and replaced the
    instructions with "LM Studio returned error: 400 - …"."""

    def _backend_raising(self, status, body):
        backend = LMStudioBackend("http://localhost:1234", "some-model")
        response = MagicMock()
        response.status_code = status
        response.json.return_value = body
        response.text = json.dumps(body)
        error = requests.exceptions.HTTPError(f"{status} Client Error")
        error.response = response
        response.raise_for_status.side_effect = error
        backend.session = MagicMock()
        backend.session.post.return_value = response
        return backend

    def test_no_models_loaded_message_reaches_the_caller(self):
        backend = self._backend_raising(400, {"error": {"message": "No models loaded"}})
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("sys", "msg")
        message = str(ctx.exception)
        self.assertIn("No AI model is currently loaded", message)
        self.assertIn("LOAD a model into memory", message)

    def test_other_http_errors_still_report_the_status(self):
        backend = self._backend_raising(422, {"error": {"message": "bad payload"}})
        with self.assertRaises(RuntimeError) as ctx:
            backend.generate("sys", "msg")
        self.assertIn("422", str(ctx.exception))
        self.assertIn("bad payload", str(ctx.exception))

    def test_generate_does_not_ping_before_every_call(self):
        """ContextManager already gates each query on a TTL-cached pre-flight;
        a per-call ping added a second round-trip to every loop iteration."""
        backend = LMStudioBackend("http://localhost:1234", "some-model")
        backend.validate_connectivity = MagicMock(return_value=True)
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": "hi", "tool_calls": []}}]
        }
        backend.session = MagicMock()
        backend.session.post.return_value = response

        backend.generate("sys", "msg")
        backend.validate_connectivity.assert_not_called()


# ---------------------------------------------------------------------------
# Transient vs permanent classification
# ---------------------------------------------------------------------------

class TestModelCatalogueFiltering(unittest.TestCase):
    """A provider's models.list() is its WHOLE catalogue. Offering non-chat
    models as selectable chat models hands the investigator a broken choice —
    verified live on both providers below."""

    def test_gemini_excludes_non_chat_families(self):
        """A live Gemini account listed 43 models including music (lyria-3-*),
        image (nano-banana-*, *-image), audio (*native-audio*), live-translate,
        robotics and deep-research agents. All were selectable as chat models."""
        from eye.backends.cloud_api.gemini_backend import GeminiBackend

        backend = GeminiBackend("gemini-2.5-flash", MagicMock())
        catalogue = [
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-flash",   # keep
            "lyria-3-pro-preview", "nano-banana-pro-preview",           # music / image
            "gemini-3-pro-image", "gemini-3.1-flash-image",             # image
            "gemini-2.5-flash-native-audio-latest",                     # audio
            "gemini-3.5-live-translate-preview",                        # live translate
            "gemini-robotics-er-1.6-preview", "deep-research-pro-preview-12-2025",
            "gemini-2.5-computer-use-preview-10-2025", "antigravity-preview-05-2026",
            "text-embedding-004",
        ]
        # A plain object, not MagicMock: MagicMock special-cases `name`, so the
        # backend's getattr(m, "name") would get a mock instead of the id.
        class _Model:
            def __init__(self, ident):
                self.name = f"models/{ident}"
                self.supported_actions = []
                self.supported_generation_methods = []

        backend._client = MagicMock()
        backend._client.models.list.return_value = [_Model(n) for n in catalogue]
        kept = backend.list_models()
        self.assertEqual(kept, ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-flash"])

    def test_lm_studio_excludes_embedding_models(self):
        """/v1/models lists embedding models too; they cannot answer a question."""
        backend = LMStudioBackend("http://localhost:1234", "m")
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": [
            {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "state": "not-loaded"},
            {"id": "microsoft/phi-4-reasoning", "type": "llm", "state": "not-loaded"},
            {"id": "some-vision-model", "type": "vlm", "state": "loaded"},
        ]}
        backend.session = MagicMock()
        backend.session.get.return_value = response

        models = backend.list_models()
        self.assertNotIn("text-embedding-nomic-embed-text-v1.5", models)
        # Already-loaded first: auto-selection should not trigger a cold JIT load.
        self.assertEqual(models[0], "some-vision-model")

    def test_lm_studio_flags_a_substituted_model(self):
        """LM Studio answers an unknown model id with whatever is loaded, HTTP
        200. Attributing that answer to the requested model would put a false
        model name in the sealed chain of custody."""
        backend = LMStudioBackend("http://localhost:1234", "requested-model")
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "model": "actually-loaded-model",
            "choices": [{"message": {"content": "hi", "tool_calls": []}}],
        }
        backend.session = MagicMock()
        backend.session.post.return_value = response

        result = backend.generate("sys", "msg")
        self.assertTrue(result["model_substituted"])
        self.assertEqual(result["model"], "actually-loaded-model")

    def test_lm_studio_does_not_flag_a_matching_model(self):
        backend = LMStudioBackend("http://localhost:1234", "the-model")
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "model": "the-model",
            "choices": [{"message": {"content": "hi", "tool_calls": []}}],
        }
        backend.session = MagicMock()
        backend.session.post.return_value = response

        self.assertFalse(backend.generate("sys", "msg")["model_substituted"])


class TestToolSupportProbe(unittest.TestCase):
    """The Eye is agentic; a model that cannot function-call is a degraded state
    the investigator must see BEFORE starting, not as a mid-query status step."""

    def setUp(self):
        # The capability probe persists verdicts to configs/eye_tool_capability.json.
        # Point it at a temp file so tests never write into the user's real config
        # directory (they did, leaving a bogus 'anthropic::mock' entry behind).
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _router(self, backend_obj, model_name, backend="gemini"):
        from pathlib import Path
        from eye.services.tool_capability import ToolCapabilityProbe

        router = _router_over(backend_obj, {"backend": backend, "model_name": model_name})
        router._tool_capability_probe = ToolCapabilityProbe(
            router, cache_path=Path(self._tmp.name) / "cap.json")
        return router

    def test_gemma_reports_text_protocol_with_a_warning(self):
        from eye.backends.cloud_api.gemini_backend import GeminiBackend
        backend = GeminiBackend("gemma-4-31b-it", MagicMock())
        router = self._router(backend, "gemma-4-31b-it")

        self.assertEqual(router.get_tool_support(), ModelRouter.TOOL_SUPPORT_TEXT)
        warning = router.get_tool_support_warning()
        self.assertIn("gemma-4-31b-it", warning)
        self.assertIn("native function calling", warning)

    def test_standard_model_reports_native_and_no_warning(self):
        from eye.backends.cloud_api.gemini_backend import GeminiBackend
        backend = GeminiBackend("gemini-2.5-flash", MagicMock())
        router = self._router(backend, "gemini-2.5-flash")

        self.assertEqual(router.get_tool_support(), ModelRouter.TOOL_SUPPORT_NATIVE)
        self.assertIsNone(router.get_tool_support_warning())

    def test_backend_may_declare_its_own_capability(self):
        backend = _FakeBackend()
        backend.tool_support = ModelRouter.TOOL_SUPPORT_TEXT
        router = self._router(backend, "whatever", backend="lm_studio")
        self.assertEqual(router.get_tool_support(), ModelRouter.TOOL_SUPPORT_TEXT)

    def test_probe_never_raises(self):
        class Exploding:
            @property
            def tool_support(self):
                raise RuntimeError("boom")

        router = self._router(Exploding(), "x")
        self.assertEqual(router.get_tool_support(), ModelRouter.TOOL_SUPPORT_UNKNOWN)


class TestTransientErrorClassification(unittest.TestCase):
    """Bare substring matching fired on request ids, token counts and quoted
    parameters — so a real 503 mentioning 429 was never retried, and a permanent
    400 mentioning 500 was retried three times with backoff."""

    @staticmethod
    def _err(message, status=None):
        error = Exception(message)
        if status is not None:
            error.status_code = status
        return error

    def test_status_code_wins_over_message_digits(self):
        self.assertTrue(is_transient_model_error(
            self._err("overloaded; previous request hit 429", 503)))
        self.assertFalse(is_transient_model_error(
            self._err("invalid max_tokens: 500", 400)))

    def test_permanent_statuses_are_not_retried(self):
        for status in (400, 401, 403, 404, 422, 429):
            self.assertFalse(is_transient_model_error(self._err("boom", status)), status)

    def test_transient_statuses_are_retried(self):
        for status in (500, 502, 503, 504, 529):
            self.assertTrue(is_transient_model_error(self._err("boom", status)), status)

    def test_requests_response_shape_is_read(self):
        error = requests.exceptions.HTTPError("server error")
        error.response = MagicMock(status_code=503)
        self.assertTrue(is_transient_model_error(error))

    def test_message_fallback_uses_word_boundaries(self):
        self.assertTrue(is_transient_model_error(Exception("500 INTERNAL")))
        self.assertTrue(is_transient_model_error(Exception("UNAVAILABLE: try again")))
        # A request id that merely contains the digits must not be misread.
        self.assertFalse(is_transient_model_error(Exception("bad request id=req_1500x")))

    def test_quota_is_permanent(self):
        self.assertFalse(is_transient_model_error(Exception("RESOURCE_EXHAUSTED: quota")))


if __name__ == "__main__":
    unittest.main()
