"""Timestamp normalization for the UBA engine.

Self-contained on purpose: the engine must run headless (in tests and in the
background QThread), so it must not import anything that transitively loads
QtWebEngine. This mirrors the behavior of the timeline's
UniversalTimestampParser (ISO 8601, FILETIME, epoch s/ms, Chromium/WebKit,
Cocoa, OLE; corrupted out-of-range dates discarded) and normalizes every
value to the app-wide convention: UTC ``'%Y-%m-%d %H:%M:%S'`` strings.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

TS_FORMAT = "%Y-%m-%d %H:%M:%S"

_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
_COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_MIN_YEAR = 2000
_MAX_YEAR = datetime.now().year + 2

_ISO_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y",
    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y",
]


def _parse_numeric(value: float) -> Optional[datetime]:
    try:
        if value > 1_000_000_000_000_000:
            seconds = value / 10_000_000 if value > 100_000_000_000_000_000 \
                else value / 1_000_000
            return _FILETIME_EPOCH + timedelta(seconds=seconds)
        if value > 10_000_000_000_00:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        if 946684800 < value < 2524608000:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if 0 < value < 1_500_000_000:
            cand = _COCOA_EPOCH + timedelta(seconds=value)
            if _MIN_YEAR <= cand.year <= _MAX_YEAR:
                return cand
        if 36526 < value < 60000 and isinstance(value, float) and not value.is_integer():
            return datetime.fromtimestamp((value - 25569) * 86400, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        pass
    return None


def _parse_string(value: str) -> Optional[datetime]:
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, OverflowError):
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        pass
    try:
        return _parse_numeric(float(value))
    except (ValueError, OverflowError):
        return None


def normalize_ts(value) -> Optional[str]:
    """Any timestamp value -> UTC 'YYYY-MM-DD HH:MM:SS' string, or None."""
    if value is None or value == "" or value == "N/A":
        return None
    dt = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = _parse_numeric(value)
    elif isinstance(value, str):
        value = value.strip()
        if not value or value == "N/A":
            return None
        dt = _parse_string(value)
    if dt is None:
        return None
    try:
        if dt.year < _MIN_YEAR or dt.year > _MAX_YEAR:
            return None
    except (AttributeError, ValueError):
        return None
    return dt.strftime(TS_FORMAT)


def to_datetime(ts: Optional[str]) -> Optional[datetime]:
    """Normalized timestamp string -> naive UTC datetime (or None)."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, TS_FORMAT)
    except (ValueError, TypeError):
        norm = normalize_ts(ts)
        if norm:
            try:
                return datetime.strptime(norm, TS_FORMAT)
            except (ValueError, TypeError):
                return None
        return None


def epoch_seconds(ts) -> Optional[float]:
    """Normalized timestamp (str or datetime) -> seconds for delta math."""
    dt = ts if isinstance(ts, datetime) else to_datetime(ts)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()
