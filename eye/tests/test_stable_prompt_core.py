"""The system prompt's core must stay byte-identical while an investigation runs.

The Narrative Map overview (VERDICT / [OPEN] / [NEGATIVE] per narrative) changes
every few steps. It sat in the core, so every backend's cached prefix broke at
each status change and Claude Code sessions restarted every 2-3 steps
(2026-11-02, 44 calls, 14M tokens written to cache). It now leads the per-step
context, and is still never truncated."""

import logging

from eye.backends.base import split_step_context
from eye.services.context_manager import ContextManager
from eye.services.token_counter import TokenCounter


class _Map:
    def __init__(self):
        self.text = "VERDICT -> Establish USB use\n[OPEN] USBSTOR enumeration - investigating"

    def overview_block(self, max_chars=3200):
        return self.text


def _cm(nms):
    cm = ContextManager.__new__(ContextManager)
    cm.logger = logging.getLogger("test-cm")
    cm.token_counter = TokenCounter(backend="gpt-4")
    cm.max_total_tokens = 200_000
    cm.token_budget = {"system_prompt": 100_000}
    cm.case_context_manager = None
    cm.report_engine = None
    cm.database_service = None
    cm._db_manifest_cache = None
    cm.narrative_map_service = nms
    cm.llm_config = {"system_prompt_template": ["# EYE"], "tools": []}
    return cm


def test_a_narrative_status_change_leaves_the_core_unchanged():
    nms = _Map()
    cm = _cm(nms)
    core1, step1 = split_step_context(cm._build_system_prompt("", []))
    nms.text = "VERDICT -> Establish USB use\n[NEGATIVE] USBSTOR enumeration - checked - nothing found"
    core2, step2 = split_step_context(cm._build_system_prompt("", []))
    assert core1 == core2
    assert "[OPEN] USBSTOR" in step1 and "[NEGATIVE] USBSTOR" in step2
    assert "VERDICT" not in core1
    assert step2.startswith("VERDICT")          # first in the step context: never trimmed
