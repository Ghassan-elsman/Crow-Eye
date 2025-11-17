"""
Timestamp parsing module for multi-format timestamp detection and conversion.

This module provides the TimestampParser class for parsing timestamps in various
formats commonly found in forensic databases, including ISO 8601, Unix epoch,
Windows FILETIME, and standard datetime formats.
"""

import datetime
import re
from typing import Any, Optional, Union
from utils.time_utils import (
    filetime_to_datetime,
    unix_timestamp_to_datetime,
    systemtime_to_datetime,
    ensure_utc,
    format_datetime
)


class TimestampParser:
    """
    Parses timestamps in multiple formats and normalizes to datetime objects.
    
    Supports automatic format detection for:
    - ISO 8601 with microseconds (2025-11-08T03:42:59.315901)
    - Standard datetime (2025-11-07 02:53:46)
    - Unix epoch (integer/float seconds since 1970-01-01)
    - Windows FILETIME (large integer, 100-nanosecond intervals since 1601-01-01)
    - ISO 8601 variations (with/without timezone, with/without microseconds)
    """
    
    # Regex patterns for timestamp detection
    ISO8601_PATTERN = re.compile(
        r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$'
    )
    STANDARD_DATETIME_PATTERN = re.compile(
        r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$'
    )
    
    # Thresholds for format detection
    MIN_FILETIME = 116444736000000000  # 1970-01-01 in FILETIME
    MAX_FILETIME = 253402300799999999  # 9999-12-31 in FILETIME
    MIN_UNIX_TIMESTAMP = 0  # 1970-01-01
    MAX_UNIX_TIMESTAMP = 253402300799  # 9999-12-31 in Unix timestamp
    
    def __init__(self):
        """Initialize the timestamp parser."""
        pass
    
    def parse_timestamp(
        self,
        value: Any,
        hint: Optional[str] = None
    ) -> Optional[datetime.datetime]:
        """
        Parse timestamp value with automatic format detection.
        
        Attempts formats in order:
        1. ISO 8601 with microseconds (2025-11-08T03:42:59.315901)
        2. Standard datetime (2025-11-07 02:53:46)
        3. Unix epoch (integer seconds)
        4. Windows FILETIME (large integer)
        5. ISO 8601 variations
        
        Args:
            value: Timestamp value (str, int, float, bytes, datetime)
            hint: Optional format hint to try first ('iso8601', 'datetime', 
                  'unix', 'filetime', 'systemtime')
            
        Returns:
            datetime object in UTC or None if parsing fails
        """
        if value is None:
            return None
        
        # If already a datetime, ensure it's UTC
        if isinstance(value, datetime.datetime):
            return ensure_utc(value)
        
        # Try hint first if provided
        if hint:
            result = self._try_parse_with_hint(value, hint)
            if result:
                return result
        
        # Try parsing based on value type
        if isinstance(value, str):
            return self._parse_string_timestamp(value)
        elif isinstance(value, (int, float)):
            return self._parse_numeric_timestamp(value)
        elif isinstance(value, bytes):
            return self._parse_bytes_timestamp(value)
        
        return None
    
    def _try_parse_with_hint(
        self,
        value: Any,
        hint: str
    ) -> Optional[datetime.datetime]:
        """
        Try parsing with a specific format hint.
        
        Args:
            value: Timestamp value
            hint: Format hint
            
        Returns:
            Parsed datetime or None
        """
        try:
            if hint == 'iso8601' and isinstance(value, str):
                return self._parse_iso8601(value)
            elif hint == 'datetime' and isinstance(value, str):
                return self._parse_standard_datetime(value)
            elif hint == 'unix' and isinstance(value, (int, float)):
                return self._parse_unix_timestamp(value)
            elif hint == 'filetime' and isinstance(value, (int, bytes)):
                return self._parse_filetime(value)
            elif hint == 'systemtime' and isinstance(value, bytes):
                return self._parse_systemtime(value)
        except Exception:
            pass
        
        return None
    
    def _parse_string_timestamp(self, value: str) -> Optional[datetime.datetime]:
        """
        Parse string timestamp with automatic format detection.
        
        Args:
            value: String timestamp
            
        Returns:
            Parsed datetime or None
        """
        if not value or not isinstance(value, str):
            return None
        
        value = value.strip()
        
        # Try ISO 8601 format first (most common in modern databases)
        if self.ISO8601_PATTERN.match(value):
            result = self._parse_iso8601(value)
            if result:
                return result
        
        # Try standard datetime format
        if self.STANDARD_DATETIME_PATTERN.match(value):
            result = self._parse_standard_datetime(value)
            if result:
                return result
        
        # Try other common formats
        result = self._parse_common_formats(value)
        if result:
            return result
        
        # Try parsing as numeric string (Unix timestamp or FILETIME)
        try:
            numeric_value = float(value)
            return self._parse_numeric_timestamp(numeric_value)
        except (ValueError, TypeError):
            pass
        
        return None
    
    def _parse_iso8601(self, value: str) -> Optional[datetime.datetime]:
        """
        Parse ISO 8601 format timestamp.
        
        Supports:
        - 2025-11-08T03:42:59.315901
        - 2025-11-08T03:42:59
        - 2025-11-08T03:42:59Z
        - 2025-11-08T03:42:59+00:00
        - 2025-11-08 03:42:59.315901
        
        Args:
            value: ISO 8601 string
            
        Returns:
            Parsed datetime or None
        """
        try:
            # Replace 'Z' with '+00:00' for fromisoformat
            value = value.replace('Z', '+00:00')
            
            # Handle space separator (convert to T)
            if ' ' in value and 'T' not in value:
                value = value.replace(' ', 'T', 1)
            
            dt = datetime.datetime.fromisoformat(value)
            return ensure_utc(dt)
        except (ValueError, AttributeError):
            pass
        
        return None
    
    def _parse_standard_datetime(self, value: str) -> Optional[datetime.datetime]:
        """
        Parse standard datetime format (YYYY-MM-DD HH:MM:SS[.ffffff]).
        
        Args:
            value: Standard datetime string
            
        Returns:
            Parsed datetime or None
        """
        formats = [
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%d %H:%M:%S',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.datetime.strptime(value, fmt)
                return ensure_utc(dt)
            except ValueError:
                continue
        
        return None
    
    def _parse_common_formats(self, value: str) -> Optional[datetime.datetime]:
        """
        Try parsing with common datetime formats.
        
        Args:
            value: Datetime string
            
        Returns:
            Parsed datetime or None
        """
        formats = [
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d %H:%M:%S.%f',
            '%m/%d/%Y %H:%M:%S',
            '%m/%d/%Y %H:%M:%S.%f',
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M:%S.%f',
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%m/%d/%Y',
            '%d/%m/%Y',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.datetime.strptime(value, fmt)
                return ensure_utc(dt)
            except ValueError:
                continue
        
        return None
    
    def _parse_numeric_timestamp(
        self,
        value: Union[int, float]
    ) -> Optional[datetime.datetime]:
        """
        Parse numeric timestamp (Unix epoch or Windows FILETIME).
        
        Args:
            value: Numeric timestamp
            
        Returns:
            Parsed datetime or None
        """
        try:
            # Check if it's a FILETIME (very large integer)
            if isinstance(value, int) and value >= self.MIN_FILETIME:
                if value <= self.MAX_FILETIME:
                    return filetime_to_datetime(value)
            
            # Try as Unix timestamp
            if self.MIN_UNIX_TIMESTAMP <= value <= self.MAX_UNIX_TIMESTAMP:
                return unix_timestamp_to_datetime(value)
            
            # Try as millisecond Unix timestamp
            if value > self.MAX_UNIX_TIMESTAMP:
                ms_value = value / 1000.0
                if self.MIN_UNIX_TIMESTAMP <= ms_value <= self.MAX_UNIX_TIMESTAMP:
                    return unix_timestamp_to_datetime(ms_value)
        
        except (ValueError, OSError, OverflowError):
            pass
        
        return None
    
    def _parse_filetime(
        self,
        value: Union[int, bytes]
    ) -> Optional[datetime.datetime]:
        """
        Parse Windows FILETIME.
        
        Args:
            value: FILETIME as integer or 8-byte bytes
            
        Returns:
            Parsed datetime or None
        """
        try:
            if isinstance(value, bytes):
                if len(value) == 8:
                    value = int.from_bytes(value, 'little')
                else:
                    return None
            
            if isinstance(value, int):
                if self.MIN_FILETIME <= value <= self.MAX_FILETIME:
                    return filetime_to_datetime(value)
        
        except (ValueError, OSError):
            pass
        
        return None
    
    def _parse_systemtime(self, value: bytes) -> Optional[datetime.datetime]:
        """
        Parse Windows SYSTEMTIME structure.
        
        Args:
            value: 16-byte SYSTEMTIME structure
            
        Returns:
            Parsed datetime or None
        """
        try:
            if len(value) == 16:
                return systemtime_to_datetime(value)
        except (ValueError, struct.error):
            pass
        
        return None
    
    def _parse_bytes_timestamp(self, value: bytes) -> Optional[datetime.datetime]:
        """
        Parse bytes timestamp (FILETIME or SYSTEMTIME).
        
        Args:
            value: Bytes timestamp
            
        Returns:
            Parsed datetime or None
        """
        if len(value) == 8:
            return self._parse_filetime(value)
        elif len(value) == 16:
            return self._parse_systemtime(value)
        
        return None
    
    def format_for_display(
        self,
        dt: datetime.datetime,
        include_microseconds: bool = False
    ) -> str:
        """
        Format datetime for display in results table.
        
        Args:
            dt: Datetime object to format
            include_microseconds: Whether to include microseconds
            
        Returns:
            Formatted string (YYYY-MM-DD HH:MM:SS[.ffffff])
        """
        if dt is None:
            return ""
        
        if include_microseconds and dt.microsecond > 0:
            return format_datetime(dt, '%Y-%m-%d %H:%M:%S.%f', include_microseconds=True)
        else:
            return format_datetime(dt, '%Y-%m-%d %H:%M:%S', include_microseconds=False)
    
    def detect_format(self, value: Any) -> Optional[str]:
        """
        Detect the format of a timestamp value without parsing.
        
        Args:
            value: Timestamp value
            
        Returns:
            Format name ('iso8601', 'datetime', 'unix', 'filetime', 'systemtime')
            or None if format cannot be determined
        """
        if value is None:
            return None
        
        if isinstance(value, datetime.datetime):
            return 'datetime_object'
        
        if isinstance(value, str):
            value = value.strip()
            if self.ISO8601_PATTERN.match(value):
                return 'iso8601'
            if self.STANDARD_DATETIME_PATTERN.match(value):
                return 'datetime'
            try:
                float(value)
                return 'numeric_string'
            except ValueError:
                return None
        
        if isinstance(value, (int, float)):
            if isinstance(value, int) and value >= self.MIN_FILETIME:
                return 'filetime'
            if self.MIN_UNIX_TIMESTAMP <= value <= self.MAX_UNIX_TIMESTAMP:
                return 'unix'
            return 'numeric'
        
        if isinstance(value, bytes):
            if len(value) == 8:
                return 'filetime_bytes'
            if len(value) == 16:
                return 'systemtime'
            return None
        
        return None
