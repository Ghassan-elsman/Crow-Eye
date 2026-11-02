"""CodexBackend against a fake `codex exec`: structured reply, tool calls with
string arguments, usage, the sign-in kept, and a turn stopped when Codex tries
to act on its own."""

import json
import os
import textwrap

import pytest

from eye.backends.local_cli.codex_backend import CODEX_REPLY_SCHEMA, CodexBackend, CodexError

FAKE = textwrap.dedent(r'''
    import json, os, sys
    argv = sys.argv[1:]
    prompt = sys.stdin.read()
    schema = json.load(open(argv[argv.index("--output-schema") + 1], encoding="utf-8"))
    with open(os.environ["FAKE_CODEX_RECORD"], "w", encoding="utf-8") as fh:
        json.dump({"argv": argv, "prompt": prompt, "cwd": os.getcwd(), "schema": schema,
                   "has_key": "OPENAI_API_KEY" in os.environ}, fh)
    mode = os.environ.get("FAKE_CODEX_MODE", "answer")
    def ev(d): print(json.dumps(d), flush=True)
    ev({"type": "thread.started", "thread_id": "t1"})
    ev({"type": "turn.started"})
    if mode == "action":
        ev({"type": "item.started", "item": {"id": "i0", "type": "command_execution", "command": "dir C:\\"}})
    elif mode == "fail":
        ev({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again at 5pm."}})
        sys.exit(1)
    else:
        if mode == "tools":
            reply = {"answer": "", "tool_calls": [
                {"name": "query_database", "arguments_json": "{\"sql\": \"SELECT 1\"}"},
                {"name": "format_disk", "arguments_json": "{}"}]}
        else:
            reply = {"answer": "CROW-PC", "tool_calls": []}
        ev({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": json.dumps(reply)}})
        ev({"type": "turn.completed", "usage": {"input_tokens": 15000, "cached_input_tokens": 14000,
                                                "output_tokens": 20, "reasoning_output_tokens": 5}})
''')

TOOLS = [{"name": "query_database", "description": "SQL", "parameters": {"type": "object"}}]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "codex.py"
    script.write_text(FAKE, encoding="utf-8")
    rec = tmp_path / "rec.json"
    monkeypatch.setenv("FAKE_CODEX_RECORD", str(rec))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-real")

    def make(mode="answer", **kw):
        monkeypatch.setenv("FAKE_CODEX_MODE", mode)
        return CodexBackend(str(script), **kw)
    make.rec = lambda: json.loads(rec.read_text(encoding="utf-8"))
    return make


def test_answer_flags_usage_and_sign_in(fake):
    be = fake("answer", effort="xhigh")
    out = be.generate("CORE\n\n## Context for this step\nSTEP", "computer name?",
                      history=[{"role": "user", "content": "earlier"}])
    assert out["content"] == "CROW-PC"
    assert out["usage"]["cache_read_input_tokens"] == 14000 and out["usage"]["input_tokens"] == 1000
    assert out["usage"]["output_tokens"] == 25
    r = fake.rec()
    argv = r["argv"]
    for flag in ("exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
        assert flag in argv
    assert argv[argv.index("-s") + 1] == "read-only"
    assert 'model_reasoning_effort="high"' in argv          # xhigh -> Codex's highest
    assert r["schema"] == CODEX_REPLY_SCHEMA
    assert r["has_key"] is False
    assert os.path.basename(r["cwd"]).startswith("eye_codex_")   # an empty folder, not the case
    assert r["prompt"].index("CORE") < r["prompt"].index("earlier") < r["prompt"].index("STEP")


def test_tool_calls_with_string_arguments(fake):
    out = fake("tools").generate("CORE", "q", tools=TOOLS)
    assert len(out["tool_calls"]) == 1
    assert json.loads(out["tool_calls"][0]["function"]["arguments"]) == {"sql": "SELECT 1"}
    assert "format_disk" in out["content"]
    assert '"arguments_json"' in fake.rec()["prompt"]


def test_a_turn_where_codex_acts_on_its_own_is_stopped(fake):
    with pytest.raises(CodexError) as ei:
        fake("action").generate("CORE", "q", tools=TOOLS)
    assert ei.value.kind == "action" and "command_execution" in str(ei.value)


def test_a_failed_turn_says_why(fake):
    with pytest.raises(CodexError) as ei:
        fake("fail").generate("CORE", "q")
    assert ei.value.kind == "limit" and "usage limit" in str(ei.value)


def test_router_builds_codex():
    import logging
    from eye.services.model_router import ModelRouter
    r = ModelRouter.__new__(ModelRouter)
    r.config = {"backend": "codex_cli", "integration_type": "local_cli", "model_name": "default",
                "executable_path": "", "effort": "high"}
    r.logger = logging.getLogger("t")
    be = r._initialize_backend()
    assert isinstance(be, CodexBackend) and be.model_name == "" and be.effort == "high"
