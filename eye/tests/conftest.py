"""
Shared test guards.

The tool-capability probe persists its verdicts to ``configs/eye_tool_capability.json``
so a model is probed once and never again. That is right for the app and wrong for a
test run: constructing a ModelRouter in a unit test was silently writing entries into
the developer's real config directory (a bogus ``anthropic::mock`` verdict showed up
there). Redirect the cache for the whole session so no test can touch real state,
whether or not it remembers to inject a path.
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_tool_capability_cache():
    from eye.services.tool_capability import ToolCapabilityProbe

    original = ToolCapabilityProbe._default_cache_path
    with tempfile.TemporaryDirectory() as tmp:
        ToolCapabilityProbe._default_cache_path = staticmethod(
            lambda: Path(tmp) / "eye_tool_capability.json")
        try:
            yield
        finally:
            ToolCapabilityProbe._default_cache_path = original
