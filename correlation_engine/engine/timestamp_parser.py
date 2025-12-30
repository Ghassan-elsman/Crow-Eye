"""
Timestamp parser for handling various forensic artifact timestamp formats.

This module provides comprehensive timestamp parsing capabilities for the Crow-Eye
Correlation Engine, supporting multiple formats commonly found in forensic artifacts.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Union

logger = logging.getLogger(__name__)


class TimestampParser:
    """
    Parse and normalize timestamps from various forensic artifact formats.
    
    Supports:
    - ISO 8601 formats
    - Unix epoch (seconds and milliseconds)
    - Windows FILETIME
    - Human-readable formats
    - Custom formats from configuration
    """
    
    def __init__(self, custom_formats: Optional[List[str]] = None):
        """
        Initialize timestamp parser.
        
        Args:
            custom_formats: Optional list of custom strptime format strings
        """
        self.custom_formats = custom_formats or []
        
        # Standard formats to try
        self.supported_formats = [
            "%Y-%m-%dT%H:%M:%S%z",      # ISO 8601 with timezone
            "%Y-%m-%dT%H:%M:%SZ",       # ISO 8601 UTC
            "%Y-%m-%dT%H:%M:%S.%f%z",   # ISO 8601 with microseconds and timezone
            "%Y-%m-%dT%H:%M:%S.%fZ",    # ISO 8601 with microseconds UTC
            "%Y-%m-%d %H:%M:%S",        # Standard datetime
            "%Y-%m-%d %H:%M:%S.%f",     # Standard datetime with microseconds
            "%m/%d/%Y %I:%M:%S %p",     # US format with AM/PM
            "%m/%d/%Y %H:%M:%S",        # US format 24-hour
            "%Y-%m-%d",                 # Date only
            "%m/%d/%Y",                 # US date only
            "%d/%m/%Y",                 # European date only
            "%Y%m%d%H%M%S",             # Compact format
            "%d-%b-%Y %H:%M:%S",        # Day-Month-Year with month name
        ] + self.custom_formats
        
        logger.info(f"TimestampParser initialized with {len(self.supported_formats)} formats")
    
    def parse_timestamp(self, value: Any) -> Optional[datetime]:
        """
        Parse timestamp from various formats.
        
        Args:
            value: Timestamp value (datetime, int, float, or str)
            
        Returns:
            Parsed datetime object or None if parsing fails
        """
        if value is None:
            return None
        
        # Already a datetime
        if isinstance(value, datetime):
            return self._ensure_timezone(value)
        
        # Numeric timestamp (Unix epoch or Windows FILETIME)
        if isinstance(value, (int, float)):
            return self._parse_numeric_timestamp(value)
        
        # String timestamp
        if isinstance(value, str):
            return self._parse_string_timestamp(value)
        
        logger.warning(f"Unsupported timestamp type: {type(value)}")
        return None
    
    def _parse_numeric_timestamp(self, value: Union[int, float]) -> Optional[datetime]:
        """
        Parse Unix epoch or Windows FILETIME.
        
        Args:
            value: Numeric timestamp
            
        Returns:
            Parsed datetime or None
        """
        try:
            # Try Unix epoch (seconds) - valid range roughly 1970-2038
            if 0 < value < 2**31:
                dt = datetime.fromtimestamp(value, tz=timezone.utc)
                logger.debug(f"Parsed Unix epoch (seconds): {value} -> {dt}")
                return dt
            
            # Try Unix epoch (milliseconds) - valid range roughly 1970-2038
            if 0 < value < 2**41:
                dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                logger.debug(f"Parsed Unix epoch (milliseconds): {value} -> {dt}")
                return dt
            
            # Try Windows FILETIME (100-nanosecond intervals since 1601-01-01)
            if value > 2**41:
                dt = self._parse_windows_filetime(int(value))
                if dt:
                    logger.debug(f"Parsed Windows FILETIME: {value} -> {dt}")
                return dt
            
            logger.warning(f"Numeric timestamp out of expected range: {value}")
            return None
            
        except (ValueError, OSError, OverflowError) as e:
            logger.warning(f"Failed to parse numeric timestamp {value}: {e}")
            return None
    
    def _parse_string_timestamp(self, value: str) -> Optional[datetime]:
        """
        Parse string timestamp using multiple formats.
        
        Args:
            value: String timestamp
            
        Returns:
            Parsed datetime or None
        """
        value = value.strip()
        
        if not value:
            return None
        
        # Try each supported format
        for fmt in self.supported_formats:
            try:
                dt = datetime.strptime(value, fmt)
                dt = self._ensure_timezone(dt)
                logger.debug(f"Parsed string timestamp with format '{fmt}': {value} -> {dt}")
                return dt
            except ValueError:
                continue
        
        # Try dateutil parser as fallback (if available)
        try:
            from dateutil import parser as dateutil_parser
            dt = dateutil_parser.parse(value)
            dt = self._ensure_timezone(dt)
            logger.debug(f"Parsed string timestamp with dateutil: {value} -> {dt}")
            return dt
        except (ImportError, ValueError) as e:
            logger.warning(f"Failed to parse string timestamp '{value}': {e}")
            return None
    
    def _parse_windows_filetime(self, filetime: int) -> Optional[datetime]:
        """
        Convert Windows FILETIME to datetime.
        
        Windows FILETIME is a 64-bit value representing the number of
        100-nanosecond intervals since January 1, 1601 (UTC).
        
        Args:
            filetime: Windows FILETIME value
            
        Returns:
            Parsed datetime or None
        """
        try:
            # FILETIME epoch: January 1, 1601
            epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
            
            # Convert 100-nanosecond intervals to microseconds
            delta = timedelta(microseconds=filetime / 10)
            
            dt = epoch + delta
            
            # Validate result is in reasonable range
            if not self.validate_timestamp(dt):
                logger.warning(f"Windows FILETIME {filetime} resulted in out-of-range date: {dt}")
                return None
            
            return dt
            
        except (ValueError, OverflowError) as e:
            logger.warning(f"Failed to parse Windows FILETIME {filetime}: {e}")
            return None
    
    def _ensure_timezone(self, dt: datetime) -> datetime:
        """
        Ensure datetime has timezone information (default to UTC).
        
        Args:
            dt: Datetime object
            
        Returns:
            Datetime with timezone
        """
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    
    def validate_timestamp(self, dt: datetime) -> bool:
        """
        Validate timestamp is within reasonable forensic range.
        
        Reasonable range: 1990-01-01 to 2050-12-31
        
        Args:
            dt: Datetime to validate
            
        Returns:
            True if valid, False otherwise
        """
        min_date = datetime(1990, 1, 1, tzinfo=timezone.utc)
        max_date = datetime(2050, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        
        # Ensure dt has timezone for comparison
        dt = self._ensure_timezone(dt)
        
        is_valid = min_date <= dt <= max_date
        
        if not is_valid:
            logger.warning(f"Timestamp out of valid range (1990-2050): {dt}")
        
        return is_valid


# Convenience functions

def parse_timestamp(value: Any, custom_formats: Optional[List[str]] = None) -> Optional[datetime]:
    """
    Convenience function to parse a single timestamp.
    
    Args:
        value: Timestamp value to parse
        custom_formats: Optional custom format strings
        
    Returns:
        Parsed datetime or None
    """
    parser = TimestampParser(custom_formats=custom_formats)
    return parser.parse_timestamp(value)


def validate_timestamp(dt: datetime) -> bool:
    """
    Convenience function to validate a timestamp.
    
    Args:
        dt: Datetime to validate
        
    Returns:
        True if valid, False otherwise
    """
    parser = TimestampParser()
    return parser.validate_timestamp(dt)
