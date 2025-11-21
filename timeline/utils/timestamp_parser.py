"""
Timestamp Parser Utility for Timeline Feature
==============================================

This module provides unified timestamp parsing functionality for the forensic timeline
visualization feature. It handles multiple timestamp formats commonly found in Windows
forensic artifacts and normalizes them to Python datetime objects in UTC.

Supported Formats:
- Unix timestamps (seconds since epoch)
- Windows FILETIME (100-nanosecond intervals since 1601-01-01)
- ISO 8601 strings (various formats)
- Python datetime objects
- Custom string formats

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import datetime
import logging
from typing import Optional, Union

# Configure logger
logger = logging.getLogger(__name__)


class TimestampParseError(Exception):
    """Exception raised when timestamp parsing fails."""
    pass


class TimestampParser:
    """
    Unified timestamp parser for forensic artifacts.
    
    This class provides methods to parse various timestamp formats found in
    Windows forensic artifacts and convert them to standardized Python datetime
    objects in UTC timezone.
    """
    
    # Windows FILETIME epoch (January 1, 1601) - timezone-naive
    FILETIME_EPOCH = datetime.datetime(1601, 1, 1)
    
    # Unix epoch (January 1, 1970) - timezone-naive
    UNIX_EPOCH = datetime.datetime(1970, 1, 1)
    
    # Maximum reasonable timestamp (year 2100) - timezone-naive
    MAX_TIMESTAMP = datetime.datetime(2100, 1, 1)
    
    # Minimum reasonable timestamp (year 1980 - before Windows) - timezone-naive
    MIN_TIMESTAMP = datetime.datetime(1980, 1, 1)
    
    # Track parse failures
    _parse_failures = []
    
    @classmethod
    def get_parse_failures(cls):
        """Get list of failed parse attempts."""
        return list(cls._parse_failures)
        
    @classmethod
    def clear_parse_failures(cls):
        """Clear parse failure history."""
        cls._parse_failures.clear()
        
    @classmethod
    def _log_failure(cls, value, error):
        """Log a parse failure."""
        cls._parse_failures.append({
            'value': str(value),
            'error': str(error),
            'timestamp': datetime.datetime.now()
        })
    
    @staticmethod
    def parse_timestamp(timestamp: Union[str, int, float, datetime.datetime, None]) -> Optional[datetime.datetime]:
        """
        Parse a timestamp from various formats and return a datetime object in UTC.
        
        This is the main entry point for timestamp parsing. It automatically detects
        the format and applies the appropriate parsing method.
        
        Args:
            timestamp: Timestamp in various formats (string, int, float, datetime, or None)
        
        Returns:
            datetime.datetime: Parsed timestamp in UTC, or None if parsing fails
        
        Examples:
            >>> TimestampParser.parse_timestamp(1699891200)  # Unix timestamp
            datetime.datetime(2023, 11, 13, 16, 0, tzinfo=datetime.timezone.utc)
            
            >>> TimestampParser.parse_timestamp("2023-11-13T16:00:00")  # ISO 8601
            datetime.datetime(2023, 11, 13, 16, 0, tzinfo=datetime.timezone.utc)
            
            >>> TimestampParser.parse_timestamp(133441920000000000)  # FILETIME
            datetime.datetime(2023, 11, 13, 16, 0, tzinfo=datetime.timezone.utc)
        """
        if timestamp is None:
            return None
        
        try:
            # Handle datetime objects
            if isinstance(timestamp, datetime.datetime):
                return TimestampParser._ensure_utc(timestamp)
            
            # Handle numeric timestamps (Unix or FILETIME)
            if isinstance(timestamp, (int, float)):
                return TimestampParser._parse_numeric_timestamp(timestamp)
            
            # Handle string timestamps
            if isinstance(timestamp, str):
                # Skip empty strings
                if not timestamp or timestamp.strip() == '':
                    return None
                
                return TimestampParser._parse_string_timestamp(timestamp)
            
            # Unknown type
            msg = f"Unknown timestamp type: {type(timestamp)}"
            logger.warning(msg)
            TimestampParser._log_failure(timestamp, msg)
            return None
        
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{timestamp}': {e}")
            TimestampParser._log_failure(timestamp, e)
            return None
    
    @staticmethod
    def _parse_numeric_timestamp(timestamp: Union[int, float]) -> Optional[datetime.datetime]:
        """
        Parse numeric timestamp (Unix or FILETIME).
        
        Automatically detects whether the timestamp is Unix (seconds since 1970)
        or Windows FILETIME (100-nanosecond intervals since 1601) based on magnitude.
        
        Args:
            timestamp: Numeric timestamp
        
        Returns:
            datetime.datetime: Parsed timestamp in UTC, or None if invalid
        """
        # Handle zero or negative timestamps
        if timestamp <= 0:
            return None
        
        # Detect format based on magnitude
        # FILETIME values are typically > 10^17 (100-nanosecond intervals since 1601)
        # Unix timestamps are typically < 10^10 (seconds since 1970)
        
        if timestamp > 1e17:
            # Likely FILETIME format
            return TimestampParser._parse_filetime(int(timestamp))
        elif timestamp < 1e10:
            # Likely Unix timestamp in seconds
            return TimestampParser._parse_unix_timestamp(timestamp)
        elif timestamp < 1e13:
            # Likely Unix timestamp in milliseconds
            return TimestampParser._parse_unix_timestamp(timestamp / 1000.0)
        elif timestamp < 1e16:
            # Likely Unix timestamp in microseconds
            return TimestampParser._parse_unix_timestamp(timestamp / 1000000.0)
        else:
            # Ambiguous - try FILETIME first, then Unix
            result = TimestampParser._parse_filetime(int(timestamp))
            if result and TimestampParser._is_reasonable_timestamp(result):
                return result
            
            result = TimestampParser._parse_unix_timestamp(timestamp)
            if result and TimestampParser._is_reasonable_timestamp(result):
                return result
            
            return None
    
    @staticmethod
    def _parse_unix_timestamp(timestamp: float) -> Optional[datetime.datetime]:
        """
        Parse Unix timestamp (seconds since January 1, 1970).
        
        Args:
            timestamp: Unix timestamp in seconds
        
        Returns:
            datetime.datetime: Parsed timestamp in UTC (timezone-naive), or None if invalid
        """
        try:
            # Use utcfromtimestamp to get timezone-naive datetime in UTC
            dt = datetime.datetime.utcfromtimestamp(timestamp)
            
            # Validate timestamp is reasonable
            if TimestampParser._is_reasonable_timestamp(dt):
                return dt
            
            return None
        
        except (ValueError, OSError, OverflowError) as e:
            logger.warning(f"Failed to parse Unix timestamp {timestamp}: {e}")
            TimestampParser._log_failure(timestamp, e)
            return None
    
    @staticmethod
    def _parse_filetime(filetime: int) -> Optional[datetime.datetime]:
        """
        Parse Windows FILETIME (100-nanosecond intervals since January 1, 1601).
        
        Args:
            filetime: FILETIME value
        
        Returns:
            datetime.datetime: Parsed timestamp in UTC, or None if invalid
        """
        try:
            # Convert 100-nanosecond intervals to seconds
            seconds = filetime / 10000000.0
            
            # Add to FILETIME epoch
            dt = TimestampParser.FILETIME_EPOCH + datetime.timedelta(seconds=seconds)
            
            # Validate timestamp is reasonable
            if TimestampParser._is_reasonable_timestamp(dt):
                return dt
            
            return None
        
        except (ValueError, OverflowError) as e:
            logger.warning(f"Failed to parse FILETIME {filetime}: {e}")
            TimestampParser._log_failure(filetime, e)
            return None
    
    @staticmethod
    def _parse_string_timestamp(timestamp_str: str) -> Optional[datetime.datetime]:
        """
        Parse string timestamp in various formats.
        
        Attempts to parse ISO 8601 and other common string formats.
        
        Args:
            timestamp_str: Timestamp string
        
        Returns:
            datetime.datetime: Parsed timestamp in UTC, or None if invalid
        """
        timestamp_str = timestamp_str.strip()
        
        # Try ISO 8601 formats with timezone support
        # First try using datetime.fromisoformat() for full ISO 8601 support (Python 3.7+)
        try:
            dt = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            dt = TimestampParser._ensure_utc(dt)
            if TimestampParser._is_reasonable_timestamp(dt):
                return dt
        except (ValueError, AttributeError):
            pass
        
        # Fallback to manual format parsing
        iso_formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",      # 2023-11-13T16:00:00.000Z
            "%Y-%m-%dT%H:%M:%SZ",          # 2023-11-13T16:00:00Z
            "%Y-%m-%dT%H:%M:%S.%f",        # 2023-11-13T16:00:00.000
            "%Y-%m-%dT%H:%M:%S",           # 2023-11-13T16:00:00
            "%Y-%m-%d %H:%M:%S.%f",        # 2023-11-13 16:00:00.000
            "%Y-%m-%d %H:%M:%S",           # 2023-11-13 16:00:00
            "%Y-%m-%d",                    # 2023-11-13
        ]
        
        for fmt in iso_formats:
            try:
                dt = datetime.datetime.strptime(timestamp_str, fmt)
                
                # Ensure UTC timezone
                dt = TimestampParser._ensure_utc(dt)
                
                # Validate timestamp is reasonable
                if TimestampParser._is_reasonable_timestamp(dt):
                    return dt
            
            except ValueError:
                continue
        
        # Try parsing as numeric string
        try:
            numeric_value = float(timestamp_str)
            return TimestampParser._parse_numeric_timestamp(numeric_value)
        except ValueError:
            pass
        
        logger.warning(f"Failed to parse string timestamp: {timestamp_str}")
        TimestampParser._log_failure(timestamp_str, "Unknown string format")
        return None
    
    @staticmethod
    def _ensure_utc(dt: datetime.datetime) -> datetime.datetime:
        """
        Ensure datetime object is in UTC and timezone-naive.
        
        For timeline visualization, we use timezone-naive datetimes in UTC
        to avoid comparison issues.
        
        Args:
            dt: Datetime object
        
        Returns:
            datetime.datetime: Timezone-naive datetime in UTC
        """
        if dt.tzinfo is None:
            # Already naive, assume it's UTC
            return dt
        elif dt.tzinfo != datetime.timezone.utc:
            # Convert to UTC first, then remove timezone
            return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        else:
            # Already UTC, just remove timezone
            return dt.replace(tzinfo=None)
    
    @staticmethod
    def _is_reasonable_timestamp(dt: datetime.datetime) -> bool:
        """
        Check if timestamp is within reasonable bounds.
        
        Validates that the timestamp is between 1980 and 2100 to catch
        parsing errors that result in unrealistic dates.
        
        Args:
            dt: Datetime object to validate
        
        Returns:
            bool: True if timestamp is reasonable, False otherwise
        """
        return TimestampParser.MIN_TIMESTAMP <= dt <= TimestampParser.MAX_TIMESTAMP
    
    @staticmethod
    def format_timestamp(dt: Optional[datetime.datetime], format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        """
        Format datetime object as string.
        
        Args:
            dt: Datetime object to format
            format_str: Format string (default: "%Y-%m-%d %H:%M:%S")
        
        Returns:
            str: Formatted timestamp string, or empty string if dt is None
        """
        if dt is None:
            return ""
        
        return dt.strftime(format_str)
    
    @staticmethod
    def get_time_bounds(timestamps: list) -> tuple:
        """
        Get earliest and latest timestamps from a list.
        
        Args:
            timestamps: List of timestamps in various formats
        
        Returns:
            tuple: (earliest_datetime, latest_datetime) or (None, None) if no valid timestamps
        """
        parsed_timestamps = []
        
        for ts in timestamps:
            parsed = TimestampParser.parse_timestamp(ts)
            if parsed:
                parsed_timestamps.append(parsed)
        
        if not parsed_timestamps:
            return (None, None)
        
        return (min(parsed_timestamps), max(parsed_timestamps))
