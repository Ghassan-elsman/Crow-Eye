"""ClaudeCodeBackend against a fake `claude`: the flags that keep Claude Code's own
tools off, the sign-in kept (API key stripped), structured tool calls, errors."""

import json
import os
import sys
import textwrap

import pytest

from eye.backends.local_cli.claude_code_backend import (
    ClaudeCodeBackend, ClaudeCodeError, REPLY_SCHEMA, step_update, context_size)

FAKE = textwrap.dedent(r'''
    import json, os, sys
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    argv = sys.argv[1:]
    stdin = "" if "--input-format" in argv else sys.stdin.read()
    sp = None
    if "--system-prompt-file" in argv:
        with open(argv[argv.index("--system-prompt-file") + 1], encoding="utf-8") as fh:
            sp = fh.read()
    with open(rec, "w", encoding="utf-8") as fh:
        json.dump({"argv": argv, "stdin": stdin, "system": sp,
                   "has_key": "ANTHROPIC_API_KEY" in os.environ,
                   "max_out": os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS")}, fh)
    mode = os.environ.get("FAKE_CLAUDE_MODE", "text")
    if "--input-format" in argv:
        # a session: one result per user line; every turn and launch recorded
        launches = rec + ".launches"
        with open(launches, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "has_key": "ANTHROPIC_API_KEY" in os.environ}) + "\n")
        n = 0
        for line in iter(sys.stdin.readline, ""):
            msg = json.loads(line)
            text = msg["message"]["content"][0]["text"]
            with open(rec + ".turns", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"pid": os.getpid(), "text": text}) + "\n")
            n += 1
            if mode == "session_error" and n == 2:
                out = {"type": "result", "is_error": True, "api_error_status": 529, "result": "Overloaded"}
            elif mode == "session_unknown_tool":
                if "not available in this step" in text:
                    out = {"type": "result", "is_error": False, "stop_reason": "end_turn",
                           "usage": {}, "structured_output": {"answer": "Seven Run-key entries.",
                                                              "tool_calls": []}}
                else:
                    out = {"type": "result", "is_error": False, "stop_reason": "end_turn", "usage": {},
                           "structured_output": {"answer": "", "tool_calls": [
                               {"name": "query_user_behavior", "arguments": {}}]}}
                print(json.dumps(out), flush=True)
                continue
            elif mode == "session_too_long" and n == 2 and "<since_your_last_reply>" in text:
                out = {"type": "result", "is_error": True, "api_error_status": 400,
                       "result": "Prompt is too long"}
            else:
                calls = [] if "No tools this turn" in text else [
                    {"name": "query_database", "arguments": {"sql": "SELECT %d" % n}}]
                out = {"type": "result", "is_error": False, "stop_reason": "end_turn",
                       "total_cost_usd": 0.01 * n,
                       "usage": {"input_tokens": 2, "output_tokens": 3,
                                 "cache_read_input_tokens": 1000 * n, "cache_creation_input_tokens": 50},
                       "structured_output": {"answer": "turn %d" % n if not calls else "",
                                             "tool_calls": calls}}
            print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
            print(json.dumps(out), flush=True)
        sys.exit(0)
    if argv[:1] == ["--version"]:
        print("2.1.316 (Claude Code)"); sys.exit(0)
    if mode == "sleep":
        import time; time.sleep(30)
    base = {"type": "result", "is_error": False, "stop_reason": "end_turn",
            "total_cost_usd": 0.0123, "duration_ms": 900,
            "usage": {"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 4000,
                      "cache_creation_input_tokens": 300},
            "modelUsage": {"claude-sonnet-5-5": {"canonicalModel": "claude-sonnet-5-5"}}}
    if mode == "text":
        base["result"] = "Two USB devices were attached."
    elif mode == "tools":
        base["structured_output"] = {"answer": "", "tool_calls": [
            {"name": "query_database", "arguments": {"sql": "SELECT 1"}},
            {"name": "rm_rf", "arguments": {}}]}
        base["result"] = json.dumps(base["structured_output"])
    elif mode == "tools_text_only":
        base["result"] = json.dumps({"answer": "", "tool_calls": [
            {"name": "query_database", "arguments": {"sql": "SELECT 2"}}]})
    elif mode == "bad_model":
        base.update(is_error=True, api_error_status=404,
                    result="There's an issue with the selected model (x).")
    elif mode == "overloaded":
        base.update(is_error=True, api_error_status=529, result="Overloaded")
    elif mode == "login":
        print("Not logged in - Please run /login", file=sys.stderr); sys.exit(1)
    elif mode == "refusal":
        base.update(stop_reason="refusal", result="")
    print(json.dumps(base))
''')

TOOLS = [{"name": "query_database", "description": "Run SQL on a case database.",
          "parameters": {"type": "object", "properties": {"sql": {"type": "string"}},
                         "required": ["sql"]}}]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "claude.py"
    script.write_text(FAKE, encoding="utf-8")
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    def run(mode="text", **kw):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        return ClaudeCodeBackend(str(script), **kw)

    def rec():
        return json.loads(record.read_text(encoding="utf-8"))
    run.rec = rec
    return run


def test_plain_answer_flags_and_sign_in(fake):
    be = fake("text", model_name="sonnet", effort="high")
    out = be.generate("You are Eye.", "Which USB devices?", history=[
        {"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
        gen_params={"max_output_tokens": 4000})
    assert out["content"] == "Two USB devices were attached."
    assert out["tool_calls"] == []
    assert out["model"] == "claude-sonnet-5-5"
    assert out["usage"]["cache_read_input_tokens"] == 4000
    assert out["usage"]["cost_usd"] == pytest.approx(0.0123)
    r = fake.rec()
    argv = r["argv"]
    # Claude Code's own tools, customisations and MCP are always off.
    i = argv.index("--tools")
    assert argv[i + 1] == ""
    for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
                 "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "high"
    assert "--json-schema" not in argv          # no tools -> plain text reply
    assert r["system"] == "You are Eye."         # through a file, not the command line
    assert r["has_key"] is False                 # the sign-in, never an API key
    assert r["max_out"] == "8192"            # never below the floor
    assert "[Investigator]\nhello" in r["stdin"] and "[Eye]\nhi" in r["stdin"]
    assert r["stdin"].rstrip().endswith("Which USB devices?")


def test_step_context_goes_after_the_conversation(fake):
    be = fake("text")
    be.generate("CORE\n\n## Context for this step\nPINNED", "q",
                history=[{"role": "user", "content": "earlier"}])
    r = fake.rec()
    assert r["system"] == "CORE"
    assert r["stdin"].index("earlier") < r["stdin"].index("q") < r["stdin"].index("PINNED")


def test_structured_tool_calls_are_mapped_and_unknown_ones_dropped(fake):
    be = fake("tools")
    out = be.generate("You are Eye.", "How many prefetch rows?", tools=TOOLS)
    r = fake.rec()
    assert json.loads(r["argv"][r["argv"].index("--json-schema") + 1]) == REPLY_SCHEMA
    assert "### query_database" in r["system"]
    assert len(out["tool_calls"]) == 1
    call = out["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "query_database"
    assert json.loads(call["function"]["arguments"]) == {"sql": "SELECT 1"}
    assert "rm_rf" in out["content"]             # said, not run


def test_structured_reply_only_in_result_text(fake):
    out = fake("tools_text_only").generate("s", "q", tools=TOOLS)
    assert json.loads(out["tool_calls"][0]["function"]["arguments"]) == {"sql": "SELECT 2"}


def test_parsed_by_context_manager(fake):
    from eye.services.context_manager import ContextManager
    out = fake("tools").generate("s", "q", tools=TOOLS)
    cm = ContextManager.__new__(ContextManager)
    import logging
    cm.logger = logging.getLogger("t")
    parsed = cm._parse_tool_calls(out)
    names = [c.get("name") or c.get("function", {}).get("name") for c in parsed]
    assert "query_database" in names


@pytest.mark.parametrize("mode,status,words", [
    ("bad_model", 404, "does not know this model"),
    ("overloaded", 529, "overloaded"),
    ("login", None, "not signed in"),
])
def test_errors_are_plain_and_typed(fake, mode, status, words):
    be = fake(mode)
    with pytest.raises(ClaudeCodeError) as ei:
        be.generate("s", "q")
    assert ei.value.status_code == status
    assert words in str(ei.value).lower()
    assert be.last_error == str(ei.value)


def test_router_retries_overload_but_not_a_bad_model(fake):
    from eye.services.model_router import is_transient_model_error
    for mode, transient in (("overloaded", True), ("bad_model", False)):
        with pytest.raises(ClaudeCodeError) as ei:
            fake(mode).generate("s", "q")
        assert is_transient_model_error(ei.value) is transient


def test_refusal_is_said_not_silent(fake):
    out = fake("refusal").generate("s", "q")
    assert out["refusal"] is True and "declined" in out["content"]


def test_timeout_stops_the_call(fake):
    be = fake("sleep", timeout_s=2)
    with pytest.raises(ClaudeCodeError) as ei:
        be.generate("s", "q")
    assert "did not answer within 2 s" in str(ei.value)


def test_missing_executable(tmp_path):
    be = ClaudeCodeBackend(str(tmp_path / "nope.exe"))
    with pytest.raises(ClaudeCodeError) as ei:
        be.generate("s", "q")
    assert "not found" in str(ei.value)
    assert be.validate_connectivity() is False


def test_generic_model_names_become_sonnet():
    for name in ("", "default", "Claude Code", "cli-default-model"):
        assert ClaudeCodeBackend("", model_name=name).model_name == "sonnet"


def test_router_builds_the_claude_code_backend():
    from eye.services.model_router import ModelRouter
    r = ModelRouter.__new__(ModelRouter)
    r.config = {"backend": "claude_code", "integration_type": "local_cli",
                "model_name": "opus", "executable_path": "", "effort": "xhigh",
                "cli_timeout_s": 900}
    import logging
    r.logger = logging.getLogger("t")
    be = r._initialize_backend()
    assert isinstance(be, ClaudeCodeBackend)
    assert (be.model_name, be.effort, be.timeout_s) == ("opus", "xhigh", 900)


def test_context_window_and_tool_support_for_aliases():
    from eye.services.context_window_registry import resolve_context_window
    from eye.services.tool_capability import registry_lookup
    assert resolve_context_window("claude_code", "sonnet") == 600_000   # room under 1M for Claude Code itself
    assert registry_lookup("claude_code", "opus")["support"] == "native"


def test_doctor_reads_executable_path():
    from eye.services import backend_doctor as bd
    src = open(bd.__file__, encoding="utf-8").read()
    assert 'cfg.get("executable_path")' in src


def _turns(tmp_rec):
    with open(tmp_rec + ".turns", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


def test_tool_loop_keeps_one_session_and_sends_only_the_new_part(fake, monkeypatch):
    be = fake("session")
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    h1 = [{"role": "user", "content": "Which USB devices were attached?"}]
    out1 = be.generate("CORE\n\n## Context for this step\nSTEP-1", "step one", tools=TOOLS, history=h1)
    assert json.loads(out1["tool_calls"][0]["function"]["arguments"]) == {"sql": "SELECT 1"}
    # Eye appends the model's tool call and the tool's result, then asks again
    h2 = h1 + [{"role": "assistant", "content": ""},
               {"role": "tool", "content": "RESULT-ROWS-AAA"}]
    out2 = be.generate("CORE\n\n## Context for this step\nSTEP-2", "step two", tools=TOOLS, history=h2)
    assert json.loads(out2["tool_calls"][0]["function"]["arguments"]) == {"sql": "SELECT 2"}
    # the last pass has no tools: same session, answer only
    h3 = h2 + [{"role": "tool", "content": "RESULT-ROWS-BBB"}]
    out3 = be.generate("CORE\n\n## Context for this step\nSTEP-3", "write it up", tools=None, history=h3)
    assert out3["content"] == "turn 3" and out3["tool_calls"] == []
    turns = _turns(rec)
    assert len({t["pid"] for t in turns}) == 1            # one process for the whole loop
    with open(rec + ".launches", encoding="utf-8") as fh:
        launches = [json.loads(l) for l in fh]
    assert len(launches) == 1 and launches[0]["has_key"] is False
    argv = launches[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "" and "--safe-mode" in argv
    assert "Which USB devices" in turns[0]["text"] and "STEP-1" in turns[0]["text"]
    # later turns carry only what is new: not the first question again
    assert "Which USB devices" not in turns[1]["text"]
    assert "RESULT-ROWS-AAA" in turns[1]["text"] and "STEP-2" in turns[1]["text"]
    assert "RESULT-ROWS-AAA" not in turns[2]["text"] and "RESULT-ROWS-BBB" in turns[2]["text"]
    assert "No tools this turn" in turns[2]["text"]
    # cost is per turn, not the session's running total
    assert out2["usage"]["cost_usd"] == pytest.approx(0.01)
    be.close_sessions()


def test_a_history_that_changed_starts_a_new_session(fake):
    be = fake("session")
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    be.generate("CORE", "q", tools=TOOLS, history=[{"role": "user", "content": "first"}])
    # Eye slimmed its history (summarised the old turns): not an extension any more
    be.generate("CORE", "q", tools=TOOLS, history=[{"role": "user", "content": "[summary] first"}])
    turns = _turns(rec)
    assert turns[0]["pid"] != turns[1]["pid"]
    assert "[summary] first" in turns[1]["text"]
    be.close_sessions()


def test_a_failed_turn_closes_the_session_and_says_why(fake):
    be = fake("session_error")
    h = [{"role": "user", "content": "first"}]
    be.generate("CORE", "q", tools=TOOLS, history=h)
    with pytest.raises(ClaudeCodeError) as ei:
        be.generate("CORE", "q", tools=TOOLS, history=h + [{"role": "tool", "content": "x"}])
    assert ei.value.status_code == 529
    assert be._sessions == {}


def test_calls_without_history_never_start_a_session(fake):
    be = fake("tools")
    be.generate("planning", "plan it", tools=None, history=[])
    assert be._sessions == {}


def test_step_context_is_sent_whole_once_then_as_changes():
    big = "\n".join("pinned evidence row %d" % i for i in range(400))
    text, full = step_update(None, big)
    assert full and text == big
    text, full = step_update(big, big)
    assert not full and "Unchanged" in text
    grown = big + "\nquery already run: SELECT 1"
    text, full = step_update(big, grown)
    assert not full and "1 line(s) added" in text and "SELECT 1" in text
    assert "pinned evidence row 5\n" not in text          # not resent
    text, full = step_update(big, "something else entirely")
    assert full


def test_session_sends_the_big_step_context_only_once(fake):
    be = fake("session")
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    big = "\n".join("pinned evidence row %d" % i for i in range(300))
    h = [{"role": "user", "content": "q"}]
    be.generate("CORE\n\n## Context for this step\n" + big, "s1", tools=TOOLS, history=h)
    h2 = h + [{"role": "tool", "content": "r1"}]
    be.generate("CORE\n\n## Context for this step\n" + big + "\nNEW-LINE", "s2", tools=TOOLS, history=h2)
    turns = _turns(rec)
    assert "pinned evidence row 299" in turns[0]["text"]
    assert "pinned evidence row 299" not in turns[1]["text"] and "NEW-LINE" in turns[1]["text"]
    be.close_sessions()


def test_a_session_full_of_eyes_own_history_is_not_restarted(fake, monkeypatch):
    import eye.backends.local_cli.claude_code_backend as cc
    monkeypatch.setattr(cc, "SESSION_TOKEN_CAP", 1000)
    be = fake("session")
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    h = [{"role": "user", "content": "x" * 40000}]           # ~10K tokens of Eye history
    be.generate("CORE", "q", tools=TOOLS, history=h)
    sess = next(iter(be._sessions.values()))
    sess.context_tokens = 12000                               # over the cap, almost all history
    be.generate("CORE", "q", tools=TOOLS, history=h + [{"role": "tool", "content": "r"}])
    turns = _turns(rec)
    assert turns[0]["pid"] == turns[1]["pid"]
    be.close_sessions()


def test_context_size_is_the_last_request_not_the_turns_sum():
    usage = {"input_tokens": 4, "cache_read_input_tokens": 1415200, "cache_creation_input_tokens": 6476,
             "output_tokens": 486,
             "iterations": [
                 {"input_tokens": 2, "cache_read_input_tokens": 707000, "cache_creation_input_tokens": 3000,
                  "output_tokens": 200},
                 {"input_tokens": 2, "cache_read_input_tokens": 708200, "cache_creation_input_tokens": 3476,
                  "output_tokens": 286}]}
    assert context_size(usage) == 2 + 708200 + 3476 + 286
    # without the per-request split the summed totals overcount: the sent-text estimate is used
    assert context_size({"input_tokens": 1, "cache_read_input_tokens": 1_400_000}, fallback=700_000) == 700_000


def test_the_plan_limit_is_named_as_such():
    from eye.backends.local_cli.claude_code_backend import _plain_error
    msg, kind = _plain_error("You've hit your 5-hour limit \u00b7 resets 5:10pm (Africa/Cairo)", 429)
    assert kind == "limit"
    assert "usage limit is reached" in msg and "resets 5:10pm" in msg
    assert "rate-limiting" not in msg


def test_a_full_session_is_not_restarted_when_that_would_not_shrink_it(fake, monkeypatch):
    import eye.backends.local_cli.claude_code_backend as cc
    monkeypatch.setattr(cc, "SESSION_TOKEN_CAP", 1000)
    monkeypatch.setattr(cc, "SESSION_HARD_CAP", 1500)
    be = fake("session")
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    h = [{"role": "user", "content": "x" * 20000}]        # Eye's own history: ~5.7K tokens
    be.generate("CORE", "q", tools=TOOLS, history=h)
    next(iter(be._sessions.values())).context_tokens = 6000    # over both caps, nearly all history
    be.generate("CORE", "q", tools=TOOLS, history=h + [{"role": "tool", "content": "r"}])
    turns = _turns(rec)
    assert turns[0]["pid"] == turns[1]["pid"]
    be.close_sessions()


def test_an_overflowing_session_is_retried_once_from_eyes_history(fake):
    be = fake("session_too_long")
    rec = os.environ["FAKE_CLAUDE_RECORD"]
    h = [{"role": "user", "content": "first"}]
    be.generate("CORE", "q", tools=TOOLS, history=h)
    out = be.generate("CORE", "q2", tools=TOOLS, history=h + [{"role": "tool", "content": "RES"}])
    assert out["tool_calls"]                                    # answered, by a fresh session
    assert out["session"]["restart"] == "too long, started again"
    turns = _turns(rec)
    assert turns[-1]["pid"] != turns[0]["pid"]
    assert "first" in turns[-1]["text"] and "RES" in turns[-1]["text"]
    be.close_sessions()


def test_an_error_turn_says_what_claude_code_reported():
    with pytest.raises(ClaudeCodeError) as ei:
        ClaudeCodeBackend._check_result({"is_error": True, "result": "", "subtype": "error_during_execution",
                                         "errors": ["structured output did not validate"]})
    assert "structured output did not validate" in str(ei.value)
    assert ei.value.status_code is None and ei.value.kind == "other"


def test_asking_only_for_an_unoffered_tool_gets_one_more_turn_for_the_answer(fake):
    # The write-up step offers report tools only; the model asked for an
    # investigative one and wrote nothing: the drop note was the whole answer.
    be = fake("session_unknown_tool")
    report_tools = [{"name": "report_append_section", "parameters": {"type": "object"}}]
    out = be.generate("CORE", "write it up", tools=report_tools,
                      history=[{"role": "user", "content": "Which Run keys?"}])
    assert out["content"] == "Seven Run-key entries." and out["tool_calls"] == []
    be.close_sessions()
