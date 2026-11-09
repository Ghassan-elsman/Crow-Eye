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

    # Divide in integers, not floating point. A FILETIME is around 1.3e17, and
    # float64 carries about 15-16 significant digits, so `filetime / 1e7` loses
    # the last microsecond. Forensic output is formatted to whole seconds, so
    # that error is invisible until it lands on a second boundary and moves the
    # displayed time by a full second: 132000000009999999 is 18:40:00.999999
    # exactly, and came out as 18:40:01.
    return WINDOWS_EPOCH + datetime.timedelta(microseconds=filetime // 10)


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


def webkit_to_datetime(webkit: int) -> datetime.datetime:
    """
    Convert a Chromium/WebKit timestamp to UTC datetime.

    Chromium (Chrome, Edge, Brave, ...) stores times as the number of
    microseconds since 1601-01-01 (the same epoch as Windows FILETIME, but in
    microseconds rather than 100-nanosecond ticks). Multiplying by 10 gives a
    FILETIME, so we reuse filetime_to_datetime and keep the exact integer math.

    Args:
        webkit: microseconds since 1601-01-01 (e.g. History.last_visit_time)

    Returns:
        datetime: UTC datetime object

    Raises:
        ValueError: if the value is falsy/zero (Chromium's "never" sentinel)
    """
    if not webkit or webkit == 0:
        raise ValueError("Invalid WebKit timestamp value")
    return filetime_to_datetime(webkit * 10)


def prtime_to_datetime(prtime: int) -> datetime.datetime:
    """
    Convert a Mozilla/Gecko PRTime timestamp to UTC datetime.

    Firefox stores times as PRTime: microseconds since the Unix epoch
    (1970-01-01). Some columns (e.g. formhistory timesUsed) are already in
    microseconds; callers pass the raw value here.

    Args:
        prtime: microseconds since 1970-01-01 (e.g. moz_places.last_visit_date)

    Returns:
        datetime: UTC datetime object

    Raises:
        ValueError: if the value is falsy/zero
    """
    if not prtime or prtime == 0:
        raise ValueError("Invalid PRTime value")
    return UNIX_EPOCH + datetime.timedelta(microseconds=prtime)


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


def format_forensic_timestamp(dt: datetime.datetime) -> str:
    """
    Format datetime as YYYY-MM-DD HH:MM:SS in UTC for forensic output.
    
    This function ensures consistent timestamp formatting across all forensic
    artifact parsers. It converts any timezone-aware datetime to UTC and
    formats it in the standardized ISO 8601 YYYY-MM-DD HH:MM:SS format.
    
    Args:
        dt: datetime object (can be naive or timezone-aware)
        
    Returns:
        str: Formatted timestamp string in YYYY-MM-DD HH:MM:SS format (UTC)
             Returns empty string if dt is None
        
    Example:
        >>> dt = datetime.datetime(2024, 1, 15, 14, 30, 22, tzinfo=datetime.timezone.utc)
        >>> format_forensic_timestamp(dt)
        '2024-01-15 14:30:22'
    """
    if dt is None:
        return ""
    
    # Ensure the datetime is in UTC
    utc_dt = ensure_utc(dt)
    
    # Format as YYYY-MM-DD HH:MM:SS (ISO 8601 standard)
    return utc_dt.strftime('%Y-%m-%d %H:%M:%S')


def get_current_forensic_timestamp() -> str:
    """
    Get current UTC time formatted as YYYY-MM-DD HH:MM:SS.
    
    This is a convenience function that combines get_current_utc() and
    format_forensic_timestamp() for generating standardized timestamps
    for forensic logging and output.
    
    Returns:
        str: Current UTC time in YYYY-MM-DD HH:MM:SS format
        
    Example:
        >>> get_current_forensic_timestamp()
        '2024-01-15 14:30:22'
    """
    return format_forensic_timestamp(get_current_utc())


# Example usage

# ---------------------------------------------- a machine's own zone rules --
def _zone_rule(raw):
    """A StandardStart / DaylightStart value (16 bytes, as stored under
    Control\\TimeZoneInformation: wYear, wMonth, wDay = occurrence 1-5 where 5
    is the last, wHour, wMinute, wSecond, wMilliseconds, then wDayOfWeek LAST -
    see registry_binary_parser.parse_tz_transition_rule). None when the zone
    does not change its clocks or the value is not a rule."""
    if not raw or len(raw) < 16:
        return None
    year, month, occ, hour, minute, second, _ms, dow = struct.unpack_from("<8H", bytes(raw), 0)
    if month == 0 or not (1 <= month <= 12 and 1 <= occ <= 5 and dow <= 6
                          and hour <= 23 and minute <= 59):
        return None
    return month, occ, dow, hour, minute, second


def _rule_moment(year, rule):
    """The local moment a rule names in ``year`` (the occ-th weekday of the month)."""
    month, occ, dow, hour, minute, second = rule
    first = datetime.date(year, month, 1)
    # Windows day of week: 0 = Sunday; Python: Monday = 0.
    offset = (dow - (first.weekday() + 1) % 7) % 7
    day = 1 + offset + 7 * (occ - 1)
    last = (datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    while day > last:
        day -= 7
    return datetime.datetime(year, month, day, hour, minute, second)


def windows_zone_to_utc(bias, standard_bias=0, daylight_bias=0, standard_start=None,
                        daylight_start=None):
    """A function: naive LOCAL datetime -> aware UTC datetime, by the zone rules
    a Windows machine kept in its SYSTEM hive (Control\\TimeZoneInformation:
    Bias, StandardBias, DaylightBias, StandardStart, DaylightStart). For text a
    machine wrote in its own local time - setupapi.dev.log - read from an image,
    where this machine's zone says nothing. UTC = local + Bias + the season's bias
    (minutes). A local time inside the hour that never existed (clocks forward)
    or that happened twice (clocks back) takes the offset in force before the
    change, as Windows does: checked against this machine's own conversion for
    every half hour of two years, transitions included."""
    std_rule, dst_rule = _zone_rule(standard_start), _zone_rule(daylight_start)
    bias, standard_bias, daylight_bias = int(bias or 0), int(standard_bias or 0), int(daylight_bias or 0)
    # DWORDs read unsigned: a zone east of UTC has a negative bias.
    bias, standard_bias, daylight_bias = [v - (1 << 32) if v >= (1 << 31) else v
                                          for v in (bias, standard_bias, daylight_bias)]

    def convert(local):
        extra = standard_bias
        if std_rule and dst_rule:
            # DaylightStart names a standard-time wall clock that jumps
            # forward: the skipped span keeps standard time. StandardStart
            # names a daylight-time wall clock: the repeated span keeps
            # daylight time up to it.
            dst_on = _rule_moment(local.year, dst_rule) + datetime.timedelta(
                minutes=standard_bias - daylight_bias)
            std_on = _rule_moment(local.year, std_rule)
            if dst_on < std_on:
                in_dst = dst_on <= local < std_on
            else:                                  # southern hemisphere
                in_dst = not (std_on <= local < dst_on)
            if in_dst:
                extra = daylight_bias
        utc = local + datetime.timedelta(minutes=bias + extra)
        return utc.replace(tzinfo=datetime.timezone.utc)
    return convert

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
