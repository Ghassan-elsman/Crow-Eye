"""A Claude plan's usage limit covers every Claude model: the Eye must not offer
"Try opus / Try haiku" as a way round it (it did, on 2026-11-02, after Claude
Code reported the limit). Other providers keep their model chips."""

import logging

from eye.services.query_processor import QueryProcessor


class _Router:
    def __init__(self, backend, model, models):
        self.config = {"backend": backend, "model_name": model}
        self._models = models

    def list_models(self):
        return list(self._models)


class _CM:
    def __init__(self, router):
        self.model_router = router
        self.case_directory = None


def _reply(backend, model, models, error):
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.cm = _CM(_Router(backend, model, models))
    qp.logger = logging.getLogger("t")
    return qp._handle_generation_failure(Exception(error), None)["data"]


def test_claude_code_plan_limit_offers_no_model_switch():
    data = _reply("claude_code", "sonnet",
                  ["sonnet", "opus", "fable", "haiku", "claude-sonnet-5-5"],
                  "Claude is rate-limiting this account (429). Claude says: limit reached")
    labels = [c["label"] for c in data["action_chips"]]
    assert not any(l.startswith("Try ") for l in labels)
    assert "covers every Claude model" in data["response"]


def test_claude_code_other_failure_offers_aliases_only():
    data = _reply("claude_code", "sonnet",
                  ["sonnet", "opus", "fable", "haiku", "claude-sonnet-5-5", "claude-opus-5-5"],
                  "Claude Code stopped.")
    tries = [c["label"] for c in data["action_chips"] if c["label"].startswith("Try ")]
    assert tries and all(not t.startswith("Try claude-") for t in tries)


def test_api_providers_keep_their_model_chips_on_a_rate_limit():
    data = _reply("anthropic", "claude-sonnet-5-5", ["claude-sonnet-5-5", "claude-haiku-5-5"],
                  "Error code: 429 rate limit")
    assert any(c["label"] == "Try claude-haiku-5-5" for c in data["action_chips"])


def test_a_too_long_prompt_is_not_called_a_rate_limit():
    from eye.backends.local_cli.claude_code_backend import ClaudeCodeError, _plain_error
    msg, kind = _plain_error("Prompt is too long - the request is ~1003302 tokens (limit 1000000)", None)
    assert kind == "too_long" and "too long" in msg
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.cm = _CM(_Router("claude_code", "sonnet", ["sonnet", "opus"]))
    qp.logger = logging.getLogger("t")
    data = qp._handle_generation_failure(ClaudeCodeError(msg, kind=kind), None)["data"]
    assert "rate limit" not in data["response"] and "covers every Claude model" not in data["response"]
