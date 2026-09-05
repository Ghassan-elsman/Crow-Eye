"""
Correlation Engine - Forensic Analysis System
Main package for the correlation engine system.

Version 0.12.6
==============
Engine highlights (introduced in the 0.11.0 Reliability & Extensibility
Release, still current):
- Single source of truth for field synonyms (config/standard_fields/*.json)
- Per-table feather schemas (correlation_engine/config/feather_schemas.json)
- Unified identity normalization across engine, GUI viewers, and semantic phase
- Multi-timestamp fan-out — every Prefetch run_time correlated, not just the latest
- Tolerant timestamp parser (FILETIME, YYYYMMDD, annotated strings, all parser formats)
- Thread-safe feather query cache (Phase 9 parallelism foundation)
- FeatherWriter: transactional batched inserts, schema metadata, multi-timestamp declaration
- Streaming query_time_range_iter for O(1) memory on large feathers
- 78-test regression suite locking in the contract
"""

__version__ = "0.13.0"
__author__ = "Crow-Eye Forensics"

# Import optimization module
try:
    from . import optimization
except ImportError:
    # Optimization module is optional
    optimization = None
