"""
Tests for config-driven generation tuning (v0.11.3):
  - ModelRouter.generate forwards gen_params to the active backend.
  - Every backend's generate() accepts a gen_params kwarg (interface parity).
(The phase->temperature selection inside guarded_generate is covered end-to-end
in test_reasoning_v0111.TestDecomposition.test_gen_params_temperature_by_phase.)
"""

import inspect
import logging
import unittest

from eye.services.model_router import ModelRouter


class _FakeBackend:
    def __init__(self):
        self.last = None

    def generate(self, system_prompt, user_message, tools=None, history=None, gen_params=None):
        self.last = {"gen_params": gen_params}
        return {"content": "ok", "tool_calls": []}


def _router_over(backend, config=None):
    r = ModelRouter.__new__(ModelRouter)
    r.logger = logging.getLogger("test-router")
    r.config = config or {"reasoning": {"model_retry_max_attempts": 1}}
    r.backend = backend
    return r


class TestRouterForwardsGenParams(unittest.TestCase):
    def test_gen_params_reach_backend(self):
        be = _FakeBackend()
        router = _router_over(be)
        router.generate("sys", "msg", gen_params={"temperature": 0.2, "max_output_tokens": 4096})
        self.assertEqual(be.last["gen_params"], {"temperature": 0.2, "max_output_tokens": 4096})

    def test_none_gen_params_pass_through(self):
        be = _FakeBackend()
        router = _router_over(be)
        router.generate("sys", "msg")
        self.assertIsNone(be.last["gen_params"])


class TestBackendsAcceptGenParams(unittest.TestCase):
    """Every backend's generate() must accept gen_params so the router can tune
    determinism per phase regardless of which backend is active."""

    def test_all_backend_generate_signatures(self):
        from eye.backends.base import LLMBackend
        from eye.backends.cloud_api.gemini_backend import GeminiBackend
        from eye.backends.cloud_api.openai_backend import OpenAIBackend
        from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
        from eye.backends.local_server.ollama_backend import OllamaBackend
        from eye.backends.local_server.lmstudio_backend import LMStudioBackend
        from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend

        for cls in (LLMBackend, GeminiBackend, OpenAIBackend, AnthropicBackend,
                    OllamaBackend, LMStudioBackend, GenericCLIBackend):
            params = inspect.signature(cls.generate).parameters
            self.assertIn("gen_params", params, f"{cls.__name__}.generate missing gen_params")


if __name__ == "__main__":
    unittest.main()
