"""
Timestamp Format Codec — column-format detection and query-side formatting.

Extracted from time_based_engine.py::OptimizedFeatherQuery so the codec
can be reused by other engines (identity-based, future) without dragging
in the whole feather-query class. The two-function API is intentionally
small and pure.

* :func:`detect_column_format(sample)` — classify a sample value into one
  of the engine's recognized format names (``'unix_seconds'``,
  ``'windows_filetime'``, ``'datetime_string'``, …). Used at feather
  load time to learn how a timestamp column is encoded.

* :func:`format_for_query(dt, format_name)` — render a Python ``datetime``
  into the value-shape the column stores, so we can build SQL WHERE
  clauses that compare apples to apples.

The codec is the inverse pair of :class:`ResilientTimestampParser` —
that one parses values *out* of feather rows; this codec writes them
*back in*.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ----- format names ---------------------------------------------------- #
# These match the strings returned by detect_column_format() and accepted
# by format_for_query(). They're a superset of TimestampFormat.value
# strings from timestamp_parser.py so existing engine code calling
# either function continues to work.

FORMAT_WINDOWS_FILETIME = "windows_filetime"
FORMAT_UNIX_MICROSECONDS = "unix_microseconds"
FORMAT_UNIX_MILLISECONDS = "unix_ms"
FORMAT_UNIX_SECONDS = "unix_s"
FORMAT_EPOCH_DAYS = "epoch_days"
FORMAT_NUMERIC = "numeric" # unclassified numeric
FORMAT_ISO8601 = "iso8601"
FORMAT_DATETIME_STRING = "datetime_string" # "YYYY-MM-DD HH:MM:SS"
FORMAT_DATE_SLASH = "date_slash" # MM/DD/YYYY or DD/MM/YYYY
FORMAT_DATE_DASH = "date_dash" # YYYY-MM-DD only, no time
FORMAT_DATE_COMPACT = "date_compact" # YYYYMMDD
FORMAT_STRING_UNKNOWN = "string_unknown"


# ----- detection ------------------------------------------------------- #

def detect_column_format(timestamp_value: Any) -> Optional[str]:
    """Classify the storage format of one sample timestamp column value.

    Order matters: Windows FILETIME values for years 1970-2100 sit in
    the 1.16e17..1.62e17 band, well above any reasonable unix_us / ms /
    s value. Probe FILETIME first when the magnitude is in that range
    so the value isn't mis-tagged as unix_ms (which would make every
    subsequent time-range query miss the column's true values).
    """
    if isinstance(timestamp_value, (int, float)):
        v = timestamp_value
        if v > 1e16:
            return FORMAT_WINDOWS_FILETIME
        if v > 1e15:
            return FORMAT_UNIX_MICROSECONDS
        if v > 1e12:
            return FORMAT_UNIX_MILLISECONDS
        if v > 1e8: # Unix seconds for ~1973..2200+
            return FORMAT_UNIX_SECONDS
        if 1 <= v <= 100000:
            return FORMAT_EPOCH_DAYS
        return FORMAT_NUMERIC

    if isinstance(timestamp_value, str):
        s = timestamp_value.strip()
        # Drop any trailing parenthetical annotation, e.g.
        # "2026-05-19 10:48:21 (Registry Key LastWrite)" — produced by
        # the registry parser when it tags a value with its source.
        if '(' in s and s.endswith(')'):
            head = s.rsplit('(', 1)[0].strip()
            if head:
                s = head
        if 'T' in s:
            return FORMAT_ISO8601
        if '-' in s and ':' in s:
            # "YYYY-MM-DD HH:MM:SS[.ffffff]" — the parser canonical form
            return FORMAT_DATETIME_STRING
        if '/' in s:
            return FORMAT_DATE_SLASH
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return FORMAT_DATE_DASH
        if len(s) == 8 and s.isdigit():
            return FORMAT_DATE_COMPACT
        return FORMAT_STRING_UNKNOWN

    return None


# ----- formatting back ------------------------------------------------- #

# Windows FILETIME epoch offset: seconds between 1601-01-01 and 1970-01-01.
_FILETIME_EPOCH_OFFSET = 11644473600


def format_for_query(dt: datetime, format_name: Optional[str], *, debug: bool = False) -> Any:
    """Render ``dt`` into the value-shape the column stores so WHERE
    clauses can compare against raw column values.

    Unknown / unhandled formats fall back to ISO so the query at least
    runs (and likely returns nothing) rather than crashing.
    """
    if not format_name or format_name == "unknown":
        if debug:
            logger.info("[timestamp_codec] unknown format, defaulting to ISO")
        return dt.isoformat()

    if format_name in ("unix_s", "unix_seconds", FORMAT_UNIX_SECONDS):
        return int(dt.timestamp())
    if format_name in ("unix_ms", "unix_milliseconds", FORMAT_UNIX_MILLISECONDS):
        return int(dt.timestamp() * 1000)
    if format_name == FORMAT_UNIX_MICROSECONDS:
        return int(dt.timestamp() * 1_000_000)
    if format_name == FORMAT_WINDOWS_FILETIME:
        return int((dt.timestamp() + _FILETIME_EPOCH_OFFSET) * 10_000_000)
    if format_name == FORMAT_EPOCH_DAYS:
        return dt.timestamp() / 86400.0
    if format_name in (FORMAT_ISO8601, "iso8601_zulu"):
        return dt.isoformat() + "Z"
    if format_name in (FORMAT_DATETIME_STRING, "string_unknown"):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if format_name in ("date_slash", "date_slash_us"):
        return dt.strftime("%m/%d/%Y %H:%M:%S")
    if format_name == "date_slash_eu":
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    if format_name == FORMAT_DATE_DASH:
        return dt.strftime("%Y-%m-%d")
    if format_name == FORMAT_DATE_COMPACT:
        return dt.strftime("%Y%m%d")
    if format_name == "mixed":
        return dt.isoformat()

    if debug:
        logger.info("[timestamp_codec] unhandled format %r, defaulting to ISO", format_name)
    return dt.isoformat()


__all__ = [
    "detect_column_format",
    "format_for_query",
    "FORMAT_WINDOWS_FILETIME",
    "FORMAT_UNIX_MICROSECONDS",
    "FORMAT_UNIX_MILLISECONDS",
    "FORMAT_UNIX_SECONDS",
    "FORMAT_EPOCH_DAYS",
    "FORMAT_ISO8601",
    "FORMAT_DATETIME_STRING",
    "FORMAT_DATE_SLASH",
    "FORMAT_DATE_DASH",
    "FORMAT_DATE_COMPACT",
]
