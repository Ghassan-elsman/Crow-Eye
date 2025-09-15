"""
Time format conversion utilities for forensic analysis.

This module provides functions to convert between various Windows time formats and UTC datetime objects.
All functions are designed to be reversible (lossless conversion).
"""

import datetime
import struct
from typing import Union, Tuple, Optional

# Windows FILETIME epoch (January 1, 1601)
WINDOWS_EPOCH = datetime.datetime(1601, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
# Unix epoch (January 1, 1970)
UNIX_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

# Constants for time conversions
HUNDRED_NANOSECONDS = 10000000  # 10^7 (100ns per second)
MILLISECONDS_TO_SECONDS = 1000  # Milliseconds to seconds


def filetime_to_datetime(filetime: int) -> datetime.datetime:
    """
    Convert Windows FILETIME (64-bit) to UTC datetime.
    
    Args:
        filetime: Windows FILETIME as 64-bit integer (100-nanosecond intervals since 1601-01-01)
        
    Returns:
        datetime: UTC datetime object
    """
    if not filetime or filetime == 0:
        raise ValueError("Invalid FILETIME value")
    
    # Convert 100-nanosecond intervals to seconds and add to Windows epoch
    seconds = filetime / HUNDRED_NANOSECONDS
    return WINDOWS_EPOCH + datetime.timedelta(seconds=seconds)


def datetime_to_filetime(dt: datetime.datetime) -> int:
    """
    Convert UTC datetime to Windows FILETIME (64-bit).
    
    Args:
        dt: datetime object (assumed to be in UTC)
        
    Returns:
        int: Windows FILETIME as 64-bit integer
    """
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    
    # Calculate the difference from Windows epoch in seconds
    delta = dt - WINDOWS_EPOCH
    # Convert to 100-nanosecond intervals
    return int(delta.total_seconds() * HUNDRED_NANOSECONDS)


def systemtime_to_datetime(systemtime: bytes) -> datetime.datetime:
    """
    Convert Windows SYSTEMTIME structure to UTC datetime.
    
    Args:
        systemtime: 16-byte SYSTEMTIME structure
        
    Returns:
        datetime: UTC datetime object
    """
    if len(systemtime) != 16:
        raise ValueError("SYSTEMTIME must be 16 bytes")
    
    year, month, day_of_week, day, hour, minute, second, milliseconds = \
        struct.unpack('<HHHHHHHH', systemtime)
    
    # Create datetime (ignoring day_of_week as it can be calculated)
    return datetime.datetime(
        year, month, day, hour, minute, second, 
        milliseconds * 1000,  # Convert to microseconds
        tzinfo=datetime.timezone.utc
    )


def datetime_to_systemtime(dt: datetime.datetime) -> bytes:
    """
    Convert UTC datetime to Windows SYSTEMTIME structure.
    
    Args:
        dt: datetime object (assumed to be in UTC)
        
    Returns:
        bytes: 16-byte SYSTEMTIME structure
    """
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    
    # Get day of week (Monday is 0, Sunday is 6 in Python, but Sunday is 0 in Windows)
    day_of_week = (dt.weekday() + 1) % 7
    
    return struct.pack(
        '<HHHHHHHH',
        dt.year, dt.month, day_of_week, dt.day,
        dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def unix_timestamp_to_datetime(timestamp: Union[int, float]) -> datetime.datetime:
    """
    Convert Unix timestamp to UTC datetime.
    
    Args:
        timestamp: Unix timestamp (seconds since 1970-01-01)
        
    Returns:
        datetime: UTC datetime object
    """
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)


def datetime_to_unix_timestamp(dt: datetime.datetime) -> float:
    """
    Convert UTC datetime to Unix timestamp.
    
    Args:
        dt: datetime object (assumed to be in UTC)
        
    Returns:
        float: Unix timestamp (seconds since 1970-01-01)
    """
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def parse_unknown_timestamp(value: Union[int, float, str, bytes], 
                         source_format: Optional[str] = None) -> datetime.datetime:
    """
    Attempt to parse an unknown timestamp format and convert to UTC datetime.
    
    Args:
        value: Timestamp value (int, float, str, or bytes)
        source_format: Optional hint about the source format ('filetime', 'systemtime', 'unix', 'iso')
        
    Returns:
        datetime: UTC datetime object
        
    Raises:
        ValueError: If the timestamp cannot be parsed
    """
    if isinstance(value, (int, float)):
        if source_format == 'filetime' or (isinstance(value, int) and value > 1e17):
            return filetime_to_datetime(value)
        return unix_timestamp_to_datetime(value)
    
    if isinstance(value, str):
        try:
            # Try ISO format
            return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            # Try common formats
            for fmt in [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S %z',
                '%Y-%m-%d %H:%M:%S.%f %z',
                '%Y/%m/%d %H:%M:%S',
                '%m/%d/%Y %H:%M:%S',
                '%d/%m/%Y %H:%M:%S'
            ]:
                try:
                    dt = datetime.datetime.strptime(value, fmt)
                    if not dt.tzinfo:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return dt
                except ValueError:
                    continue
    
    if isinstance(value, bytes):
        if len(value) == 8 and (source_format == 'filetime' or not source_format):
            filetime = int.from_bytes(value, 'little')
            return filetime_to_datetime(filetime)
        elif len(value) == 16 and (source_format == 'systemtime' or not source_format):
            return systemtime_to_datetime(value)
    
    raise ValueError(f"Could not parse timestamp: {value} (format: {source_format or 'auto'})")


def format_timestamp(dt: datetime.datetime, timezone: str = 'UTC') -> str:
    """
    Format datetime as 'YYYY-MM-DD HH:MM:SS' with timezone information.
    
    Args:
        dt: datetime object
        timezone: Target timezone (e.g., 'UTC', 'Africa/Cairo' for Egypt)
                Can be any timezone from pytz.all_timezones
                
    Returns:
        str: Formatted datetime string with timezone info
        
    Example:
        >>> format_timestamp(datetime.now(), 'Africa/Cairo')
        '2025-09-15 03:26:33 EEST (UTC+03:00)'
    """
    if dt is None:
        return ""
    
    try:
        import pytz
        
        # Get the target timezone
        target_tz = pytz.timezone(timezone)
        
        # If datetime is naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            
        # Convert to target timezone
        localized_dt = dt.astimezone(target_tz)
        
        # Get timezone info
        tz_abbr = localized_dt.strftime('%Z')  # E.g., 'EET' or 'EEST'
        tz_offset = localized_dt.strftime('%z')  # E.g., '+0200'
        
        # Format offset as ±HH:MM
        if tz_offset:
            tz_offset = f"{tz_offset[:3]}:{tz_offset[3:]}"
        
        # Format the final string
        return f"{localized_dt.strftime('%Y-%m-%d %H:%M:%S')} {tz_abbr} (UTC{tz_offset})"
        
    except ImportError:
        # Fallback if pytz is not available
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z (UTC%z)')


def format_datetime(dt: datetime.datetime, 
                   format_str: str = '%Y-%m-%d %H:%M:%S',
                   include_microseconds: bool = False) -> str:
    """
    Format datetime as a string with timezone information.
    
    Args:
        dt: datetime object
        format_str: Format string (default: '%Y-%m-%d %H:%M:%S')
        include_microseconds: Whether to include microseconds in the output
        
    Returns:
        str: Formatted datetime string
    """
    if dt is None:
        return ""
        
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    
    if not include_microseconds:
        dt = dt.replace(microsecond=0)
    
    return dt.strftime(format_str)


def normalize_timezone(dt: datetime.datetime) -> datetime.datetime:
    """
    Ensure the datetime has timezone info (defaulting to UTC if none).
    
    Args:
        dt: Input datetime
        
    Returns:
        datetime: Datetime with timezone info
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def ensure_utc(dt: datetime.datetime) -> datetime.datetime:
    """
    Ensure a datetime is timezone-aware and in UTC.
    
    Args:
        dt: Input datetime (naive or timezone-aware)
        
    Returns:
        datetime: Timezone-aware datetime in UTC
        
    Example:
        >>> ensure_utc(datetime(2023, 1, 1, 12, 0))  # Naive datetime
        datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        
        >>> cairo_tz = pytz.timezone('Africa/Cairo')
        >>> cairo_time = cairo_tz.localize(datetime(2023, 1, 1, 14, 0))
        >>> ensure_utc(cairo_time)
        datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
    """
    if dt is None:
        return None
        
    if dt.tzinfo is None:
        # If naive, assume it's already in UTC
        return dt.replace(tzinfo=datetime.timezone.utc)
    
    # Convert to UTC if it's not already
    return dt.astimezone(datetime.timezone.utc)


def detect_timezone(dt: datetime.datetime) -> dict:
    """
    Detect timezone information from a datetime object.
    
    Args:
        dt: datetime object (can be naive or timezone-aware)
        
    Returns:
        dict: Dictionary containing timezone information:
            - 'is_naive': bool (True if no timezone info)
            - 'timezone': str (timezone name if known, else None)
            - 'offset': str (UTC offset as ±HH:MM)
            - 'is_dst': bool (if in daylight saving time, None if unknown)
            - 'abbreviation': str (timezone abbreviation like 'EET', 'PDT')
    """
    result = {
        'is_naive': dt.tzinfo is None,
        'timezone': None,
        'offset': None,
        'is_dst': None,
        'abbreviation': None
    }
    
    if dt.tzinfo is None:
        return result
    
    try:
        import pytz
        
        # Get the timezone name
        tz_name = dt.tzinfo.zone if hasattr(dt.tzinfo, 'zone') else str(dt.tzinfo)
        result['timezone'] = tz_name
        
        # Get UTC offset
        offset = dt.utcoffset()
        if offset:
            total_seconds = int(offset.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            sign = '+' if hours >= 0 else '-'
            result['offset'] = f"{sign}{abs(hours):02d}:{minutes:02d}"
        
        # Get DST info
        if hasattr(dt.tzinfo, 'dst'):
            dst = dt.tzinfo.dst(dt)
            result['is_dst'] = bool(dst and dst.total_seconds() > 0)
        
        # Get timezone abbreviation
        result['abbreviation'] = dt.strftime('%Z') or None
        
    except Exception:
        # Fallback for when pytz is not available
        result['abbreviation'] = dt.strftime('%Z') or None
        offset = dt.utcoffset()
        if offset:
            total_seconds = int(offset.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            sign = '+' if hours >= 0 else '-'
            result['offset'] = f"{sign}{abs(hours):02d}:{minutes:02d}"
    
    return result


def get_timezone_info(dt: datetime.datetime) -> str:
    """
    Get human-readable timezone information for a datetime.
    
    Args:
        dt: datetime object
        
    Returns:
        str: Formatted timezone information
    """
    if dt is None:
        return "No time information"
        
    tz_info = detect_timezone(dt)
    
    if tz_info['is_naive']:
        return "No timezone information (naive datetime)"
    
    parts = []
    if tz_info['abbreviation']:
        parts.append(tz_info['abbreviation'])
    if tz_info['offset']:
        parts.append(f"UTC{tz_info['offset']}")
    if tz_info['timezone']:
        parts.append(f"({tz_info['timezone']})")
    if tz_info['is_dst'] is not None:
        parts.append("Daylight Saving Time" if tz_info['is_dst'] else "Standard Time")
    
    return ' • '.join(parts) if parts else "Unknown timezone"


def get_current_utc() -> datetime.datetime:
    """Get current time in UTC."""
    return datetime.datetime.now(datetime.timezone.utc)


# Example usage
if __name__ == "__main__":
    # Current time in various formats
    now = get_current_utc()
    
    # Conversion examples
    ft = datetime_to_filetime(now)
    dt_from_ft = filetime_to_datetime(ft)
    
    st = datetime_to_systemtime(now)
    dt_from_st = systemtime_to_datetime(st)
    
    unix_ts = datetime_to_unix_timestamp(now)
    dt_from_unix = unix_timestamp_to_datetime(unix_ts)
    
    print(f"Current time: {format_datetime(now)}")
    print(f"FILETIME: {ft} -> {format_datetime(dt_from_ft)}")
    print(f"SYSTEMTIME: {st.hex()} -> {format_datetime(dt_from_st)}")
    print(f"Unix timestamp: {unix_ts} -> {format_datetime(dt_from_unix)}")
    
    # Test parsing unknown format
    test_times = [
        (str(ft), 'filetime'),
        (ft, 'filetime'),
        (st, 'systemtime'),
        (unix_ts, 'unix'),
        (format_datetime(now), 'iso')
    ]
    
    for value, fmt in test_times:
        try:
            parsed = parse_unknown_timestamp(value, fmt)
            print(f"Parsed {fmt}: {value} -> {format_datetime(parsed)}")
        except Exception as e:
            print(f"Failed to parse {fmt} ({value}): {e}")
