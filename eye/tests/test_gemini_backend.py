"""
Tests for the Gemini backend hardening that fixes the recurring 500 INTERNAL:

  - Gemma models on the Gemini API support NEITHER system_instruction NOR function
    calling. The backend must drop both and fold the system prompt into the first
    user turn (otherwise every forensic turn 500s).
  - For real gemini-* models, tool parameter schemas must be sanitized to Gemini's
    OpenAPI subset (strip `default`, `additionalProperties`, `$schema`, ...).
  - No empty text parts may be sent.
"""

import json
import unittest

from eye.backends.cloud_api.gemini_backend import GeminiBackend


class _Resp:
    def __init__(self):
        self.text = "ok"
        self.function_calls = []
        self.candidates = []


class _Models:
    def __init__(self, capture):
        self._capture = capture

    def generate_content(self, model, contents, config):
        self._capture["model"] = model
        self._capture["contents"] = contents
        self._capture["config"] = config
        return _Resp()


class _FakeClient:
    def __init__(self, capture):
        self.models = _Models(capture)


def _backend(model):
    be = GeminiBackend(model, credential_manager=None)
    cap = {}
    be._client = _FakeClient(cap)  # bypass lazy SDK/network init
    return be, cap


_TOOLS = [{
    "name": "chat_add_table",
    "description": "demo",
    "parameters": {
        "type": "object",
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": False,
        "title": "ChatAddTable",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}, "default": []},
            "rows": {"type": "array", "items": {"type": "object"}},
            "flag": {"type": "boolean", "default": False},
        },
        "required": ["columns", "rows"],
    },
}]


class TestGemmaDegrades(unittest.TestCase):
    def test_gemma_detection(self):
        self.assertTrue(GeminiBackend("gemma-3-27b-it", None)._is_gemma())
        self.assertTrue(GeminiBackend("models/gemma-4-31b-it", None)._is_gemma())
        self.assertFalse(GeminiBackend("gemini-2.0-flash", None)._is_gemma())

    def test_gemma_request_has_no_system_instruction_or_tools(self):
        be, cap = _backend("gemma-4-31b-it")
        be.generate("SYSTEM PROMPT", "hello", tools=_TOOLS, history=None)
        config = cap["config"]
        self.assertNotIn("system_instruction", config)
        self.assertNotIn("tools", config)

    def test_gemma_folds_system_into_first_user_turn(self):
        be, cap = _backend("gemma-4-31b-it")
        be.generate("SYSTEM PROMPT", "hello", tools=_TOOLS, history=None)
        contents = cap["contents"]
        self.assertEqual(contents[0]["role"], "user")
        first_text = contents[0]["parts"][0]["text"]
        self.assertIn("SYSTEM PROMPT", first_text)
        self.assertIn("hello", first_text)

    def test_gemma_response_flags_tools_unsupported(self):
        # When tools are requested but dropped for Gemma, the response must tell the
        # orchestrator so it can warn the investigator instead of looping uselessly.
        be, _ = _backend("gemma-4-31b-it")
        resp = be.generate("SYS", "hello", tools=_TOOLS, history=None)
        self.assertTrue(resp.get("tools_unsupported"))

    def test_gemma_no_tools_requested_is_not_flagged(self):
        be, _ = _backend("gemma-4-31b-it")
        resp = be.generate("SYS", "hello", tools=None, history=None)
        self.assertFalse(resp.get("tools_unsupported"))

    def test_gemini_supports_tools_not_flagged(self):
        be, _ = _backend("gemini-2.0-flash")
        resp = be.generate("SYS", "hello", tools=_TOOLS, history=None)
        self.assertFalse(resp.get("tools_unsupported"))

    def test_no_empty_parts(self):
        be, cap = _backend("gemma-4-31b-it")
        # history with an empty assistant turn (e.g. a pure tool-call iteration)
        history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": ""}]
        be.generate("SYS", "hello", tools=None, history=history)
        for c in cap["contents"]:
            for p in c["parts"]:
                self.assertTrue(p["text"].strip(), "empty text part was sent to Gemini")


class TestGeminiSchemaSanitizer(unittest.TestCase):
    def test_gemini_keeps_system_and_tools_but_sanitizes(self):
        be, cap = _backend("gemini-2.0-flash")
        be.generate("SYS", "hi", tools=_TOOLS, history=None)
        config = cap["config"]
        self.assertEqual(config.get("system_instruction"), "SYS")
        decls = config["tools"][0]["function_declarations"]
        blob = json.dumps(decls)
        for bad in ("default", "additionalProperties", "$schema", "title"):
            self.assertNotIn(bad, blob, f"unsupported key '{bad}' leaked to Gemini")
        # structure is preserved
        params = decls[0]["parameters"]
        self.assertEqual(params["properties"]["columns"]["items"]["type"], "string")
        self.assertEqual(params["required"], ["columns", "rows"])

    def test_sanitizer_is_recursive_and_pure(self):
        be, _ = _backend("gemini-2.0-flash")
        dirty = {
            "type": "object",
            "title": "X",
            "additionalProperties": False,
            "properties": {
                "a": {"type": "string", "default": "z"},
                "b": {"type": "array", "items": {"type": "integer", "default": 0}},
            },
        }
        clean = be._sanitize_gemini_schema(dirty)
        self.assertNotIn("title", clean)
        self.assertNotIn("additionalProperties", clean)
        self.assertNotIn("default", clean["properties"]["a"])
        self.assertNotIn("default", clean["properties"]["b"]["items"])
        self.assertEqual(clean["properties"]["a"]["type"], "string")
        # original untouched
        self.assertEqual(dirty["properties"]["a"]["default"], "z")


if __name__ == "__main__":
    unittest.main()
