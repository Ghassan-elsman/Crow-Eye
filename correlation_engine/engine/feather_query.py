"""
Feather Query — per-feather time-range queries with caching + fan-out.

Public surface
--------------
``OptimizedFeatherQuery`` lives here as the canonical home. For the
moment its body is still defined inside ``time_based_engine.py`` for
backwards compatibility with the historical file layout; this module
re-exports the symbols so new code can write::

    from correlation_engine.engine.feather_query import OptimizedFeatherQuery

today, and the physical extraction (splitting the 7,900-line
time_based_engine.py) lands as a follow-up without touching any
consumer.

Contract
--------
Input: a ``FeatherLoader`` pointing at one SQLite feather DB, plus a
        ``[start_time, end_time]`` window.
Output: list of record dicts whose primary timestamp column falls
        inside the window, with multi-timestamp JSON columns fanned
        out into virtual records per timestamp.
Threading:
        Currently single-threaded per instance. Phase 9 adds locks +
        per-thread connections so the class becomes safe to share
        across worker threads. Until then, give each thread its own
        instance.
"""

from __future__ import annotations

from .time_based_engine import OptimizedFeatherQuery # noqa: F401

__all__ = ["OptimizedFeatherQuery"]
