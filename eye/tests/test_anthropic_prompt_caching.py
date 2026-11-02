"""The Anthropic request keeps what repeats cacheable.

2026-11-01, one question on Claude Sonnet 5.5: 66 calls, 15.4M input tokens, none cached.
The system prompt (26-74K tokens) changed on 63 of 66 calls because the per-call context
(queries already run, retrieved knowledge) sat inside it, in front of the whole
conversation. Now the stable core is a cached system block and the per-call context
follows the conversation, so the conversation stays a prefix the next call can read back.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eye.backends.base import STEP_CONTEXT_HEADING, split_step_context  # noqa: E402
from eye.backends.cloud_api.anthropic_backend import AnthropicBackend  # noqa: E402

CORE = "# EYE Forensic Assistant\n" + "schema and tools\n" * 50
STEP = "## Already-Run Queries\n- [5 rows] SELECT ..."
SYSTEM = CORE + "\n\n" + STEP_CONTEXT_HEADING + "\n" + STEP


def test_split_finds_the_core_and_the_step_context():
    core, step = split_step_context(SYSTEM)
    assert core == CORE and step == STEP
    assert split_step_context("no heading here") == ("no heading here", "")


def test_core_is_a_cached_system_block_and_step_context_follows_the_conversation():
    params = {"system": SYSTEM, "messages": [
        {"role": "user", "content": "Which USB devices?"},
        {"role": "assistant", "content": "Looking."},
        {"role": "user", "content": "Tool results: 20 rows"}]}
    AnthropicBackend._apply_prompt_caching(params)
    assert params["system"] == [{"type": "text", "text": CORE, "cache_control": {"type": "ephemeral"}}]
    assert STEP not in str(params["system"])
    last = params["messages"][-1]["content"]
    # the breakpoint is on the message as the history will keep it ...
    assert last[0] == {"type": "text", "text": "Tool results: 20 rows", "cache_control": {"type": "ephemeral"}}
    # ... and the per-call context comes after it, uncached
    assert STEP in last[1]["text"] and "cache_control" not in last[1]
    # earlier turns are untouched, so they stay byte-identical across calls
    assert params["messages"][0] == {"role": "user", "content": "Which USB devices?"}


def test_a_prompt_without_step_context_still_caches_the_system():
    params = {"system": CORE, "messages": [{"role": "user", "content": "hi"}]}
    AnthropicBackend._apply_prompt_caching(params)
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert len(params["messages"][-1]["content"]) == 1


def test_context_manager_joins_the_parts_under_the_heading():
    src = open(os.path.join(ROOT, "eye", "services", "context_manager.py"), encoding="utf-8").read()
    assert 'STEP_CONTEXT_HEADING + "\\n" + optional_str' in src
