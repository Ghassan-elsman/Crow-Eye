"""
Feather Schemas Registry — per-table metadata for the correlation engine.

The engine historically used heuristics (column-name patterns, lazy index
creation, hardcoded MULTI_TIMESTAMP_FIELDS dicts) to discover what each
feather DB table contained. That worked for the built-in parsers but
broke down whenever a new parser shipped — the engine would either
ignore real timestamps or mis-identify them.

This module loads ``correlation_engine/config/feather_schemas.json`` and
exposes a thin lookup API. The engine consults it as its first source of
truth and falls back to the existing heuristics when a table isn't
declared.

The JSON file lists, per SQLite table name:

* ``artifact_type`` Category (matches artifact_types.json)
* ``primary_timestamp_column`` Column to index and to filter window queries on
* ``secondary_timestamp_columns`` Additional timestamps for analysis
* ``multi_timestamp_json_columns`` JSON list-of-timestamps columns (Prefetch run_times shape)
* ``identity_columns_preferred`` Identity-extraction priority for raw name
* ``table_kind`` Coarse category for downstream tooling

Adding a new parser table is a single JSON edit — no code change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent / "feather_schemas.json"
_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _load() -> Dict[str, Dict[str, Any]]:
    """Load and cache the feather schemas. Empty dict on any error."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if not _SCHEMA_PATH.exists():
        logger.info("feather_schemas.json not present at %s — heuristics only", _SCHEMA_PATH)
        _CACHE = {}
        return _CACHE

    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("feather_schemas.json parse error: %s — heuristics only", e)
        _CACHE = {}
        return _CACHE

    # Drop the doc comment if present
    raw.pop("_doc", None)
    _CACHE = {k: v for k, v in raw.items() if isinstance(v, dict)}
    return _CACHE


def reload() -> None:
    """Drop the cache so the next access reads disk again (for tests)."""
    global _CACHE
    _CACHE = None


def get_schema(table_name: str) -> Optional[Dict[str, Any]]:
    """Return the declared schema for ``table_name`` or None if undeclared."""
    return _load().get(table_name)


def primary_timestamp_column(table_name: str) -> Optional[str]:
    """Return the declared primary timestamp column for ``table_name``."""
    schema = get_schema(table_name)
    return schema.get("primary_timestamp_column") if schema else None


def all_timestamp_columns(table_name: str) -> List[str]:
    """Return primary + secondary timestamp columns (declared order)."""
    schema = get_schema(table_name)
    if not schema:
        return []
    out: List[str] = []
    primary = schema.get("primary_timestamp_column")
    if primary:
        out.append(primary)
    for col in schema.get("secondary_timestamp_columns", []) or []:
        if col and col not in out:
            out.append(col)
    return out


def multi_timestamp_json_columns(table_name: str) -> List[Dict[str, str]]:
    """Return the JSON-list-of-timestamps columns for ``table_name``.

    Each entry has ``{"column": str, "format": str}``. Empty list when the
    table has no fan-out columns (most tables).
    """
    schema = get_schema(table_name)
    if not schema:
        return []
    return list(schema.get("multi_timestamp_json_columns", []) or [])


def identity_columns_preferred(table_name: str) -> List[str]:
    """Return identity-field priority list for ``table_name``."""
    schema = get_schema(table_name)
    if not schema:
        return []
    return list(schema.get("identity_columns_preferred", []) or [])


def all_declared_tables() -> List[str]:
    """Return all table names that have a declared schema."""
    return list(_load().keys())


__all__ = [
    "get_schema",
    "primary_timestamp_column",
    "all_timestamp_columns",
    "multi_timestamp_json_columns",
    "identity_columns_preferred",
    "all_declared_tables",
    "reload",
]
