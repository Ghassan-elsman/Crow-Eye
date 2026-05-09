"""
TimestampService - Timestamp parsing and formatting service for EYE AI Assistant.

This service wraps Crow-eye's UniversalTimestampParser to provide timestamp
parsing and formatting capabilities for the EYE AI assistant. It handles various
timestamp formats including Windows FILETIME, Unix timestamps, and ISO 8601.

"""

import logging
from datetime import datetime
from typing import Any, Optional

# Import Crow-eye's UniversalTimestampParser
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from timeline.timeline_bridge import UniversalTimestampParser


class TimestampService:
    """
    Provides timestamp parsing and formatting for forensic analysis.
    
    This service wraps Crow-eye's UniversalTimestampParser and adds additional
    functionality for human-readable formatting and validation.
    
    Supported Formats:
    - Windows FILETIME (100-nanosecond intervals since 1601)
    - Unix epoch timestamps (seconds and milliseconds)
    - Mac Cocoa Absolute Time (seconds since 2001)
    - OLE Automation Date (days since December 30, 1899)
    - ISO 8601 format strings
    
    Validation:
    - Detects corrupted timestamps (year < 2000 or > current year + 2)
    - Returns None for invalid/corrupted timestamps
    
    Attributes:
        logger: Logger instance for debugging and error tracking
    """
    
    def __init__(self):
        """Initialize the TimestampService."""
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def parse_timestamp(self, value: Any) -> Optional[str]:
        """
        Parse a timestamp from various formats to standardized format.
        
        This method wraps UniversalTimestampParser.parse() to convert timestamps
        from various forensic formats into a standardized "YYYY-MM-DD HH:MM:SS" format.
        
        Supported input formats:
        - Windows FILETIME (large integers > 1,000,000,000,000,000)
        - Unix epoch in seconds (10 digits, e.g., 1609459200)
        - Unix epoch in milliseconds (13 digits, e.g., 1609459200000)
        - Mac Cocoa Absolute Time (seconds since 2001-01-01)
        - OLE Automation Date (float days since 1899-12-30)
        - ISO 8601 strings (e.g., "2024-01-01T12:00:00")
        - Various date string formats
        
        Validation:
        - Timestamps with year < 2000 are considered corrupted and return None
        - Timestamps with year > (current year + 2) are considered corrupted and return None
        - Invalid or unparseable values return None
        
        Args:
            value: Timestamp value in any supported format (int, float, str, datetime)
            
        Returns:
            Standardized timestamp string "YYYY-MM-DD HH:MM:SS", or None if invalid/corrupted
            
        
        Examples:
            >>> service = TimestampService()
            >>> service.parse_timestamp(1609459200)  # Unix epoch
            '2021-01-01 00:00:00'
            >>> service.parse_timestamp(132600000000000000)  # Windows FILETIME
            '2021-03-15 10:30:00'
            >>> service.parse_timestamp("2024-01-01T12:00:00")  # ISO 8601
            '2024-01-01 12:00:00'
            >>> service.parse_timestamp(946684799)  # Before year 2000
            None
        """
        try:
            result = UniversalTimestampParser.parse(value)
            
            if result is None:
                self.logger.debug(f"Failed to parse timestamp: {value}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing timestamp {value}: {e}")
            return None
    
    def format_for_display(self, timestamp_str: Optional[str]) -> str:
        """
        Format a timestamp string for human-readable display.
        
        This method takes a standardized timestamp string (YYYY-MM-DD HH:MM:SS)
        and formats it in a more human-readable format suitable for display
        in the UI or reports.
        
        Args:
            timestamp_str: Standardized timestamp string in "YYYY-MM-DD HH:MM:SS" format,
                          or None for invalid timestamps
            
        Returns:
            Human-readable timestamp string, or "N/A" if input is None/invalid
            
        
        Examples:
            >>> service = TimestampService()
            >>> service.format_for_display("2024-01-01 12:00:00")
            'January 01, 2024 at 12:00:00'
            >>> service.format_for_display(None)
            'N/A'
            >>> service.format_for_display("")
            'N/A'
        """
        if not timestamp_str:
            return "N/A"
        
        try:
            # Parse the standardized format
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            
            # Format for human-readable display
            # Format: "January 01, 2024 at 12:00:00"
            formatted = dt.strftime("%B %d, %Y at %H:%M:%S")
            
            return formatted
            
        except (ValueError, AttributeError) as e:
            self.logger.warning(f"Failed to format timestamp '{timestamp_str}': {e}")
            return "N/A"
    
    def is_valid_timestamp(self, value: Any) -> bool:
        """
        Check if a value can be parsed as a valid timestamp.
        
        This is a convenience method that returns True if parse_timestamp()
        would return a valid timestamp string, False otherwise.
        
        Args:
            value: Timestamp value to validate
            
        Returns:
            True if value is a valid, parseable timestamp; False otherwise
            
        Examples:
            >>> service = TimestampService()
            >>> service.is_valid_timestamp(1609459200)
            True
            >>> service.is_valid_timestamp("invalid")
            False
            >>> service.is_valid_timestamp(None)
            False
        """
        return self.parse_timestamp(value) is not None
    
    def batch_parse_timestamps(self, values: list) -> list:
        """
        Parse multiple timestamp values in batch.
        
        This method efficiently processes multiple timestamp values and returns
        a list of parsed results in the same order.
        
        Args:
            values: List of timestamp values to parse
            
        Returns:
            List of parsed timestamp strings (or None for invalid values)
            
        Examples:
            >>> service = TimestampService()
            >>> service.batch_parse_timestamps([1609459200, "2024-01-01T12:00:00", None])
            ['2021-01-01 00:00:00', '2024-01-01 12:00:00', None]
        """
        results = []
        for value in values:
            results.append(self.parse_timestamp(value))
        return results
