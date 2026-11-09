"""The AI agent rules: a session, and each request with what the agent ran.

The fixture's ai_agents.db is written by the real parser from records shaped
like the agents' own (conftest.py), so a rule that reads a column the parser
does not write fails here instead of finding nothing.
"""
import json

from uba.engine.behavior_engine import BehaviorEngine
from Artifacts_Collectors.tests.ai_agent_transcripts import PLANTED_SECRETS


def _events(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    store = eng.run(progress_cb=lambda p, l: None)
    rows = [dict(r) for r in store.conn.execute(
        "SELECT * FROM events WHERE rule_id LIKE 'ai_agent%' ORDER BY ts_start, description")]
    cat = eng.rules_catalog()
    status = {r["rule_id"]: r["status"] for r in (cat["rules"] if isinstance(cat, dict) else cat)}
    return rows, status


def test_both_rules_run(artifacts_dir):
    _, status = _events(artifacts_dir)
    assert status["ai_agent_session"] != "unavailable"
    assert status["ai_agent_turn"] != "unavailable"


def test_a_session_says_who_worked_with_which_agent_where(artifacts_dir):
    rows, _ = _events(artifacts_dir)
    sessions = [r for r in rows if r["rule_id"] == "ai_agent_session"]
    assert len(sessions) == 3                       # the sub-agent folds into its session
    claude = next(r for r in sessions if r["app_name"] == "Claude Code")
    assert claude["description"] == (
        "Alice worked with Claude Code in C:\\Users\\Alice\\work\\shop between 14:00 and 14:06 "
        "('Fix the checkout'): made 1 request, ran 4 commands, changed files 1 time, "
        "started 1 sub-agent")
    assert claude["actor_sid"] == "S-1-5-21-111-222-333-1001"


def test_a_request_names_what_the_agent_ran_and_who_drove_it(artifacts_dir):
    rows, _ = _events(artifacts_dir)
    turns = {r["description"]: r for r in rows if r["rule_id"] == "ai_agent_turn"}
    main = next(t for d, t in turns.items() if d.startswith("Claude Code ran"))
    assert main["description"].startswith(
        "Claude Code ran 2 commands (`pytest -q`; `curl -H 'x-api-key: [masked: anthropic key]' "
        "https://api.example.test`) and changed 1 file (cart.py) in C:\\Users\\Alice\\work\\shop "
        "between 14:00 and 14:01 (session 'Fix the checkout'), after Alice asked: "
        "\"Fix the failing checkout test\"")
    assert (main["operator"], main["operator_kind"]) == ("automation", "script")
    assert main["operator_basis"] == "run by Claude Code (recorded in its session record)"
    details = json.loads(main["details_json"])
    assert details["agent_transcript"] == "Claude Code" and details["command_count"] == 2
    sub = next(t for d, t in turns.items() if d.startswith("A Claude Code sub-agent"))
    assert 'after the main agent asked: "Search the repo for cart usages"' in sub["description"]
    assert any(d.startswith("Gemini CLI ran 1 command (`mkdir backup`)") for d in turns)
    # Woken by its own background task, not asked: told apart from a request.
    assert ("Claude Code ran 1 command (`git log -1`) in C:\\Users\\Alice\\work\\shop at 14:05 (session 'Fix the checkout'), on its own "
            "after a background task it started had finished (no new request)") in turns
    assert any(d.startswith("Codex ran 1 command (`powershell -c dir -s`)") for d in turns)


def test_no_secret_reaches_an_event(artifacts_dir):
    rows, _ = _events(artifacts_dir)
    text = json.dumps(rows, default=str)
    for secret in PLANTED_SECRETS:
        assert secret not in text
