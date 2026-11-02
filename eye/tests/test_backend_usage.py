"""Every backend reports token use in one shape (only Claude Code did before)."""

from types import SimpleNamespace as NS
from unittest import mock

from eye.backends.base import _num


def test_num_ignores_missing_and_non_numeric_fields():
    assert _num(NS(a=5), "a") == 5
    assert _num(NS(), "a") == 0
    assert _num({"a": None}, "a") == 0
    assert _num(mock.MagicMock(), "a") == 0


def _session(be):
    return {k: be.session_usage[k] for k in ("calls", "input_tokens", "output_tokens",
                                              "cache_read_input_tokens")}


def test_openai_counts_cached_prompt_tokens_apart():
    from eye.backends.cloud_api.openai_backend import OpenAIBackend
    be = OpenAIBackend.__new__(OpenAIBackend)
    u = be.record_usage(900, 40, cache_read=100, model="gpt-4.1")
    assert u == {"input_tokens": 900, "output_tokens": 40, "cache_read_input_tokens": 100,
                 "cache_creation_input_tokens": 0, "cost_usd": 0.0, "model": "gpt-4.1"}
    be.record_usage(10, 5)
    assert _session(be) == {"calls": 2, "input_tokens": 910, "output_tokens": 45,
                            "cache_read_input_tokens": 100}


def test_anthropic_reply_carries_usage():
    from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
    be = AnthropicBackend("claude-haiku-5-5", credential_manager=None)
    resp = NS(stop_reason="end_turn", model="claude-haiku-5-5",
              usage=NS(input_tokens=12, output_tokens=7, cache_read_input_tokens=3000,
                       cache_creation_input_tokens=50),
              content=[NS(type="text", text="CROW-PC")])
    raw = mock.MagicMock()
    raw.parse.return_value = resp
    raw.headers = {}
    be._client = mock.MagicMock()
    be._client.messages.with_raw_response.create.return_value = raw
    out = be.generate("system", "computer name?")
    assert out["content"] == "CROW-PC"
    assert out["usage"]["cache_read_input_tokens"] == 3000 and out["usage"]["output_tokens"] == 7
    assert be.session_usage["calls"] == 1
