"""
Tool-calling capability detection — the ladder, the probe, the cache, the gate.

The Eye used to answer "can this model call tools?" with a hardcoded `gemma*` name
match and an optimistic "yes" for everything else. These tests pin the replacement:
a verdict for ANY model, carrying how it was determined, that only changes what the
Eye sends when the evidence is good enough to act on.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eye.services import tool_capability as tc
from eye.services.tool_capability import ToolCapabilityProbe, registry_lookup


class _FakeRouter:
    """Enough of a ModelRouter for the probe: config, backend, generate."""

    def __init__(self, backend="openai", model="some-model", responses=None, raises=None):
        self.config = {"backend": backend, "model_name": model}
        self.backend = MagicMock(spec=[])  # no _is_gemma unless a test adds it
        self.calls = []
        self._responses = list(responses or [])
        self._raises = raises

    def generate(self, system_prompt, user_message, tools=None, history=None,
                 on_retry=None, gen_params=None, _bypass_capability_gate=False):
        self.calls.append({"tools": tools, "bypass": _bypass_capability_gate})
        if self._raises:
            raise self._raises
        return self._responses.pop(0) if self._responses else {"content": "", "tool_calls": []}


def _probe(router, tmpdir):
    return ToolCapabilityProbe(router, cache_path=Path(tmpdir) / "cap.json")


# ---------------------------------------------------------------------------
# Rung 3 — family / architecture registry
# ---------------------------------------------------------------------------

class TestFamilyRegistry(unittest.TestCase):
    def test_gemma_is_text_protocol(self):
        for name in ("gemma-4-31b-it", "models/gemma-2-9b", "google/gemma-3-27b"):
            verdict = registry_lookup("gemini", name)
            self.assertIsNotNone(verdict, name)
            self.assertEqual(verdict["support"], tc.TEXT_PROTOCOL)
            self.assertEqual(verdict["confidence"], tc.KNOWN)

    def test_gemma_detected_by_lm_studio_architecture(self):
        """A local GGUF can be named anything — `gama-4b` on this machine is a
        gemma3. The reported arch is the honest signal."""
        verdict = registry_lookup("lm_studio", "gama-4b", arch="gemma3")
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict["support"], tc.TEXT_PROTOCOL)

    def test_embedding_models_cannot_call_tools_at_all(self):
        for name in ("text-embedding-nomic-embed-text-v1.5", "bge-large-en"):
            verdict = registry_lookup("lm_studio", name)
            self.assertIsNotNone(verdict, name)
            self.assertEqual(verdict["support"], tc.NONE)

    def test_known_native_families(self):
        for name in ("gpt-4o", "claude-opus-4-8", "gemini-2.5-flash", "llama-3.3-70b"):
            verdict = registry_lookup("x", name)
            self.assertIsNotNone(verdict, name)
            self.assertEqual(verdict["support"], tc.NATIVE)

    def test_unknown_family_returns_none(self):
        """The whole point: an unrecognized model must fall through to a probe,
        not be silently assumed capable."""
        self.assertIsNone(registry_lookup("lm_studio", "somebody-custom-finetune-v3"))


# ---------------------------------------------------------------------------
# Rung 2 — provider metadata
# ---------------------------------------------------------------------------

class TestProviderMetadata(unittest.TestCase):
    def test_openrouter_supported_parameters(self):
        payload = {"data": [
            {"id": "anthropic/claude-opus-5", "supported_parameters": ["tools", "max_tokens"]},
            {"id": "google/gemini-3.1-flash-image", "supported_parameters": ["max_tokens"]},
        ]}
        with patch("eye.services.tool_capability.requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: payload)

            yes = tc._openrouter_metadata("anthropic/claude-opus-5")
            self.assertEqual(yes["support"], tc.NATIVE)
            self.assertEqual(yes["confidence"], tc.CONFIRMED)

            no = tc._openrouter_metadata("google/gemini-3.1-flash-image")
            self.assertEqual(no["support"], tc.TEXT_PROTOCOL)
            self.assertEqual(no["confidence"], tc.CONFIRMED)

    def test_openrouter_unknown_model_returns_none(self):
        with patch("eye.services.tool_capability.requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"data": []})
            self.assertIsNone(tc._openrouter_metadata("nobody/knows"))

    def test_ollama_capabilities(self):
        with patch("eye.services.tool_capability.requests.post") as post:
            post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"capabilities": ["completion", "tools"]})
            verdict = tc._ollama_metadata("http://localhost:11434", "llama3.3")
            self.assertEqual(verdict["support"], tc.NATIVE)
            self.assertEqual(verdict["confidence"], tc.CONFIRMED)

    def test_ollama_without_capabilities_field_falls_through(self):
        """Older Ollama omits the field — that is 'unknown', not 'no tools'."""
        with patch("eye.services.tool_capability.requests.post") as post:
            post.return_value = MagicMock(status_code=200, json=lambda: {"model_info": {}})
            self.assertIsNone(tc._ollama_metadata("http://localhost:11434", "llama3"))

    def test_lmstudio_rules_out_non_chat_and_returns_arch(self):
        payload = {"data": [
            {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "arch": "nomic-bert"},
            {"id": "microsoft/phi-4-reasoning", "type": "llm", "arch": "phi3"},
        ]}
        with patch("eye.services.tool_capability.requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: payload)

            verdict, arch = tc._lmstudio_metadata("http://localhost:1234",
                                                  "text-embedding-nomic-embed-text-v1.5")
            self.assertEqual(verdict["support"], tc.NONE)

            # An LLM gets no verdict from metadata (LM Studio does not report tool
            # support) but DOES hand its architecture to the registry.
            verdict, arch = tc._lmstudio_metadata("http://localhost:1234",
                                                  "microsoft/phi-4-reasoning")
            self.assertIsNone(verdict)
            self.assertEqual(arch, "phi3")


# ---------------------------------------------------------------------------
# Rungs 4-5 — the live probe
# ---------------------------------------------------------------------------

class TestLiveProbe(unittest.TestCase):
    def test_native_tool_call_confirms_native(self):
        router = _FakeRouter(responses=[{
            "content": "",
            "tool_calls": [{"id": "1", "type": "function",
                            "function": {"name": "eye_capability_check",
                                         "arguments": '{"ok":"yes"}'}}],
        }])
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).probe(force=True)
        self.assertEqual(verdict["support"], tc.NATIVE)
        self.assertEqual(verdict["confidence"], tc.CONFIRMED)
        self.assertEqual(verdict["source"], tc.SRC_PROBE)

    def test_probe_bypasses_the_capability_gate(self):
        """Otherwise the probe's own tools could be stripped by a prior verdict —
        circular reasoning instead of evidence."""
        router = _FakeRouter(responses=[{"content": "", "tool_calls": [
            {"function": {"name": "eye_capability_check", "arguments": "{}"}}]}])
        with tempfile.TemporaryDirectory() as tmp:
            _probe(router, tmp).probe(force=True)
        self.assertTrue(router.calls[0]["bypass"])
        self.assertIsNotNone(router.calls[0]["tools"])

    def test_tools_rejected_error_means_no_native(self):
        router = _FakeRouter(raises=RuntimeError(
            "400 INVALID_ARGUMENT: Function calling is not supported for this model"))
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).probe(force=True)
        self.assertEqual(verdict["support"], tc.TEXT_PROTOCOL)
        self.assertEqual(verdict["confidence"], tc.CONFIRMED)

    def test_accepts_tools_but_emits_none_then_text_protocol_works(self):
        router = _FakeRouter(responses=[
            {"content": "Sure, I will do that.", "tool_calls": []},          # native probe
            {"content": '```tool_call\n{"name":"eye_capability_check",'
                        '"parameters":{"ok":"yes"}}\n```'},                   # text probe
        ])
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).probe(force=True)
        self.assertEqual(verdict["support"], tc.TEXT_PROTOCOL)
        self.assertEqual(verdict["confidence"], tc.CONFIRMED)

    def test_neither_mode_works_is_none(self):
        """What phi-4-reasoning actually did in the live run: no native call and
        no parseable fenced block."""
        router = _FakeRouter(responses=[
            {"content": "", "tool_calls": []},
            {"content": "I am thinking about it..."},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).probe(force=True)
        self.assertEqual(verdict["support"], tc.NONE)
        self.assertEqual(verdict["confidence"], tc.CONFIRMED)

    def test_backend_reported_tools_unsupported(self):
        router = _FakeRouter(responses=[
            {"content": "hi", "tool_calls": [], "tools_unsupported": True},
            {"content": '```tool_call\n{"name":"eye_capability_check"}\n```'},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).probe(force=True)
        self.assertEqual(verdict["support"], tc.TEXT_PROTOCOL)


# ---------------------------------------------------------------------------
# Rung 1 — the cache
# ---------------------------------------------------------------------------

class TestCache(unittest.TestCase):
    def test_verdict_is_cached_and_reused_without_a_model_call(self):
        router = _FakeRouter(responses=[{"content": "", "tool_calls": [
            {"function": {"name": "eye_capability_check", "arguments": "{}"}}]}])
        with tempfile.TemporaryDirectory() as tmp:
            probe = _probe(router, tmp)
            probe.probe(force=True)
            calls_after_first = len(router.calls)

            again = probe.probe()
            self.assertEqual(len(router.calls), calls_after_first, "cache did not prevent a call")
            self.assertEqual(again["support"], tc.NATIVE)
            self.assertEqual(again["source"], tc.SRC_CACHE)
            self.assertEqual(again["origin"], tc.SRC_PROBE)

    def test_cache_survives_a_new_probe_instance(self):
        router = _FakeRouter(responses=[{"content": "", "tool_calls": [
            {"function": {"name": "eye_capability_check", "arguments": "{}"}}]}])
        with tempfile.TemporaryDirectory() as tmp:
            _probe(router, tmp).probe(force=True)
            fresh = ToolCapabilityProbe(router, cache_path=Path(tmp) / "cap.json")
            self.assertEqual(fresh.cached("openai", "some-model")["support"], tc.NATIVE)

    def test_stale_and_version_bumped_entries_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cap.json"
            path.write_text(json.dumps({
                "openai::old": {"support": tc.NATIVE, "probe_version": tc.PROBE_VERSION,
                                "probed_at": time.time() - tc.CACHE_TTL_SECONDS - 10},
                "openai::v0": {"support": tc.NATIVE, "probe_version": 0,
                               "probed_at": time.time()},
            }), encoding="utf-8")
            probe = ToolCapabilityProbe(_FakeRouter(), cache_path=path)
            self.assertIsNone(probe.cached("openai", "old"), "expired entry was served")
            self.assertIsNone(probe.cached("openai", "v0"), "old probe_version was served")

    def test_forget_clears_one_entry(self):
        router = _FakeRouter(responses=[{"content": "", "tool_calls": [
            {"function": {"name": "eye_capability_check", "arguments": "{}"}}]}])
        with tempfile.TemporaryDirectory() as tmp:
            probe = _probe(router, tmp)
            probe.probe(force=True)
            probe.forget("openai", "some-model")
            self.assertIsNone(probe.cached("openai", "some-model"))

    def test_unreadable_cache_does_not_break_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cap.json"
            path.write_text("{ this is not json", encoding="utf-8")
            probe = ToolCapabilityProbe(_FakeRouter(model="gpt-4o"), cache_path=path)
            self.assertEqual(probe.resolve()["support"], tc.NATIVE)


# ---------------------------------------------------------------------------
# resolve() — the cheap, GUI-safe path
# ---------------------------------------------------------------------------

class TestCheapResolution(unittest.TestCase):
    def test_resolve_never_calls_the_model(self):
        router = _FakeRouter(model="totally-unknown-model-xyz")
        with tempfile.TemporaryDirectory() as tmp:
            _probe(router, tmp).resolve()
        self.assertEqual(router.calls, [], "resolve() issued a model call")

    def test_unknown_model_defaults_to_native_but_only_assumed(self):
        """Optimistic so an unknown model is never blocked — but ASSUMED, so the
        guess can never change what the Eye sends."""
        router = _FakeRouter(model="totally-unknown-model-xyz")
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).resolve()
        self.assertEqual(verdict["support"], tc.NATIVE)
        self.assertEqual(verdict["confidence"], tc.ASSUMED)
        self.assertFalse(tc.is_actionable(verdict))

    def test_probe_skips_the_model_call_when_metadata_already_answered(self):
        router = _FakeRouter(model="gemma-4-31b-it", backend="gemini")
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _probe(router, tmp).probe()
        self.assertEqual(verdict["support"], tc.TEXT_PROTOCOL)
        self.assertEqual(router.calls, [], "spent a model call on a known family")


class TestCapabilityGateInGenerate(unittest.TestCase):
    """ModelRouter.generate is the single choke point for every model call, so the
    capability gate lives there — map-reduce and history summarization inherit it."""

    def _router(self, verdict):
        import logging
        from eye.services.model_router import ModelRouter

        backend = MagicMock()
        backend.generate.return_value = {"content": "ok", "tool_calls": []}
        router = ModelRouter.__new__(ModelRouter)
        router.logger = logging.getLogger("gate-test")
        router.config = {"backend": "gemini", "model_name": "m",
                         "reasoning": {"model_retry_max_attempts": 1}}
        router.backend = backend
        router.get_tool_capability = lambda use_cache=True: verdict
        return router, backend

    _TOOLS = [{"name": "query_database", "description": "", "parameters": {}}]

    def test_confirmed_non_native_drops_the_tools_payload(self):
        """Sending tools to a model that rejects them is what produced the
        recurring Gemma 500 INTERNAL."""
        router, backend = self._router(
            {"support": tc.TEXT_PROTOCOL, "confidence": tc.CONFIRMED, "source": tc.SRC_PROBE})
        router.generate("sys", "msg", tools=self._TOOLS)
        self.assertIsNone(backend.generate.call_args[0][2])

    def test_known_none_drops_the_tools_payload(self):
        router, backend = self._router(
            {"support": tc.NONE, "confidence": tc.KNOWN, "source": tc.SRC_REGISTRY})
        router.generate("sys", "msg", tools=self._TOOLS)
        self.assertIsNone(backend.generate.call_args[0][2])

    def test_assumed_verdict_never_changes_the_request(self):
        """The safeguard: a guess must not disable native tools on a model that
        actually supports them."""
        router, backend = self._router(
            {"support": tc.TEXT_PROTOCOL, "confidence": tc.ASSUMED, "source": tc.SRC_DEFAULT})
        router.generate("sys", "msg", tools=self._TOOLS)
        self.assertEqual(backend.generate.call_args[0][2], self._TOOLS)

    def test_native_verdict_keeps_the_tools_payload(self):
        router, backend = self._router(
            {"support": tc.NATIVE, "confidence": tc.CONFIRMED, "source": tc.SRC_PROBE})
        router.generate("sys", "msg", tools=self._TOOLS)
        self.assertEqual(backend.generate.call_args[0][2], self._TOOLS)

    def test_bypass_flag_defeats_the_gate(self):
        router, backend = self._router(
            {"support": tc.NONE, "confidence": tc.CONFIRMED, "source": tc.SRC_PROBE})
        router.generate("sys", "msg", tools=self._TOOLS, _bypass_capability_gate=True)
        self.assertEqual(backend.generate.call_args[0][2], self._TOOLS)


class TestSystemPromptFollowsCapability(unittest.TestCase):
    """The text-protocol instructions used to be gated on a `gemma*` name match,
    so every OTHER model without native tools got no tool list and no call format
    — it could not see the tools, nor knew how to invoke them."""

    def _system_prompt_for(self, support):
        import logging
        from eye.services.context_manager import ContextManager

        cm = ContextManager.__new__(ContextManager)
        cm.logger = logging.getLogger("prompt-test")
        cm.model_router = MagicMock()
        cm.model_router.config = {"backend": "lm_studio", "model_name": "custom-finetune"}
        cm.model_router.get_tool_support.return_value = support
        cm.llm_config = {"system_prompt_template": ["You are EYE."], "tools": []}
        cm.max_total_tokens = 128000
        cm.token_budget = {"system_prompt": 40000}
        cm.case_directory = None
        cm.case_context_manager = None
        cm._get_tool_definitions = lambda: [
            {"name": "query_database", "description": "Run SQL",
             "parameters": {"type": "object", "properties": {}}}]
        cm.database_service = None
        cm.evidence_index_service = None
        cm.narrative_map_service = None
        cm.token_counter = MagicMock()
        cm.token_counter.count_tokens.return_value = 10
        return cm._build_system_prompt("", [])

    def test_non_native_model_is_taught_the_text_protocol(self):
        prompt = self._system_prompt_for("text_protocol")
        self.assertIn("```tool_call", prompt)
        self.assertIn("query_database", prompt)

    def test_native_model_is_not_cluttered_with_it(self):
        prompt = self._system_prompt_for("native")
        self.assertNotIn("```tool_call", prompt)


class TestActionability(unittest.TestCase):
    def test_only_confirmed_and_known_are_actionable(self):
        self.assertTrue(tc.is_actionable({"confidence": tc.CONFIRMED}))
        self.assertTrue(tc.is_actionable({"confidence": tc.KNOWN}))
        self.assertFalse(tc.is_actionable({"confidence": tc.ASSUMED}))
        self.assertFalse(tc.is_actionable(None))

    def test_describe_names_the_source(self):
        self.assertIn("live probe", tc.describe(
            {"confidence": tc.CONFIRMED, "source": tc.SRC_PROBE}))
        self.assertIn("provider", tc.describe(
            {"confidence": tc.CONFIRMED, "source": tc.SRC_METADATA}))


if __name__ == "__main__":
    unittest.main()
