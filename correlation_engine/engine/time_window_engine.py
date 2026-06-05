"""
Time Window Scanning Engine — public engine entry point.

Public surface
--------------
``TimeWindowScanningEngine`` lives here as the canonical home. Body is
still defined inside ``time_based_engine.py``; this module re-exports
it so new code can write::

    from correlation_engine.engine.time_window_engine import TimeWindowScanningEngine

today, and the physical extraction is staged for a follow-up.

Contract
--------
Input: a list of Wings + a pipeline_config.
Output: per-wing correlation match lists, plus the
        ``_last_window_correlation_stats`` diagnostics dict.
"""

from __future__ import annotations

from .time_based_engine import TimeWindowScanningEngine # noqa: F401

__all__ = ["TimeWindowScanningEngine"]
