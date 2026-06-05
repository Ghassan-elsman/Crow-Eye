"""
Window Query Manager — orchestrates per-window queries across feathers.

Public surface
--------------
``WindowQueryManager`` lives here as the canonical home. Body is still
defined inside ``time_based_engine.py``; this module re-exports it so
new code can write::

    from correlation_engine.engine.window_query_manager import WindowQueryManager

today, and the physical extraction is staged for a follow-up.

Contract
--------
Input: a TimeWindow with start/end, plus a dict of feather queries.
Output: populated TimeWindow with records_by_feather filled in,
        identity filters applied.
"""

from __future__ import annotations

from .time_based_engine import WindowQueryManager # noqa: F401

__all__ = ["WindowQueryManager"]
