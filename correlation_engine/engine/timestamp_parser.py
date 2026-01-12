"""
Timestamp Parser with Resilience

Provides robust timestamp parsing with multiple format support, graceful handling
of invalid timestamp values, and fallback strategies for missing timestamp columns.

Features:
- Support for multiple timestamp formats (Unix, ISO8601, custom formats)
- Graceful handling of invalid timestamp values
- Fallback strategies for missing timestamp columns
- Timestamp validation and error reporting
- Format detection and automatic conversion
- Timezone handling and normalization
"""

import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import calendar


class TimestampFormat(Enum):
    """Supported timestamp formats"""
    UNIX_SECONDS = "unix_seconds"
    UNIX_MILLISECONDS = "unix_milliseconds"
    UNIX_MICROSECONDS = "unix_microseconds"
    ISO8601 = "iso8601"
    ISO8601_ZULU = "iso8601_zulu"
    DATETIME_STRING = "datetime_string"
    DATE_SLASH_US = "date_slash_us"  # MM/DD/YYYY
    DATE_SLASH_EU = "date_slash_eu"  # DD/MM/YYYY
    DATE_DASH = "date_dash"  # YYYY-MM-DD
    WINDOWS_FILETIME = "windows_filetime"
    EPOCH_DAYS = "epoch_days"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


@dataclass
class TimestampParseResult:
    """Result of timestamp parsing operation"""
    success: bool
    datetime_value: Optional[datetime]
    original_value: Any
    detected_format: TimestampFormat
    error_message: Optional[str] = None
    confidence: float = 1.0  # 0.0 to 1.0
    timezone_info: Optional[str] = None


@dataclass
class TimestampValidationRule:
    """Rules for validating parsed timestamps"""
    min_year: int = 1970
    max_year: int = 2100
    require_timezone: bool = False
    allow_future_dates: bool = True
    max_future_days: int = 365


class ResilientTimestampParser:
    """
    Robust timestamp parser with multiple format support and error resilience.
    
    Handles various timestamp formats commonly found in forensic artifacts
    and provides fallback strategies when parsing fails.
    """
    
    def __init__(self, 
                 validation_rules: Optional[TimestampValidationRule] = None,
                 debug_mode: bool = False):
        """
        Initialize timestamp parser.
        
        Args:
            validation_rules: Rules for validating parsed timestamps
            debug_mode: Enable debug logging
        """
        self.validation_rules = validation_rules or TimestampValidationRule()
        self.debug_mode = debug_mode
        
        # Statistics
        self.parse_attempts = 0
        self.successful_parses = 0
        self.failed_parses = 0
        self.format_detection_cache: Dict[str, TimestampFormat] = {}
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        if debug_mode:
            self.logger.setLevel(logging.DEBUG)
        
        # Compile regex patterns for performance
        self._compile_patterns()
        
        if self.debug_mode:
            print("[TimestampParser] Initialized with validation rules:", self.validation_rules)
    
    def _compile_patterns(self):
        """Compile regex patterns for timestamp format detection"""
        self.patterns = {
            TimestampFormat.ISO8601: re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'),
            TimestampFormat.ISO8601_ZULU: re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$'),
            TimestampFormat.DATETIME_STRING: re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'),
            TimestampFormat.DATE_SLASH_US: re.compile(r'^\d{1,2}/\d{1,2}/\d{4}'),
            TimestampFormat.DATE_SLASH_EU: re.compile(r'^\d{1,2}/\d{1,2}/\d{4}'),
            TimestampFormat.DATE_DASH: re.compile(r'^\d{4}-\d{2}-\d{2}$'),
        }
    
    def parse_timestamp(self, 
                       value: Any, 
                       hint_format: Optional[TimestampFormat] = None,
                       column_name: Optional[str] = None) -> TimestampParseResult:
        """
        Parse a timestamp value with resilient error handling.
        
        Args:
            value: Timestamp value to parse
            hint_format: Optional format hint to try first
            column_name: Optional column name for context
            
        Returns:
            TimestampParseResult with parsing outcome
        """
        self.parse_attempts += 1
        
        # Handle None/null values
        if value is None or (isinstance(value, str) and value.strip() == ''):
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.UNKNOWN,
                error_message="Null or empty timestamp value"
            )
        
        # Try hint format first if provided
        if hint_format and hint_format != TimestampFormat.UNKNOWN:
            result = self._try_parse_format(value, hint_format, column_name)
            if result.success:
                self.successful_parses += 1
                return result
        
        # Try to detect format automatically
        detected_format = self._detect_format(value)
        
        if detected_format != TimestampFormat.UNKNOWN:
            result = self._try_parse_format(value, detected_format, column_name)
            if result.success:
                self.successful_parses += 1
                return result
        
        # Try all formats as fallback
        for format_type in TimestampFormat:
            if format_type in [TimestampFormat.UNKNOWN, TimestampFormat.CUSTOM]:
                continue
            
            if format_type == hint_format or format_type == detected_format:
                continue  # Already tried
            
            result = self._try_parse_format(value, format_type, column_name)
            if result.success:
                result.confidence = 0.7  # Lower confidence for fallback parsing
                self.successful_parses += 1
                return result
        
        # All parsing attempts failed
        self.failed_parses += 1
        return TimestampParseResult(
            success=False,
            datetime_value=None,
            original_value=value,
            detected_format=TimestampFormat.UNKNOWN,
            error_message=f"Unable to parse timestamp: {value}",
            confidence=0.0
        )
    
    def _detect_format(self, value: Any) -> TimestampFormat:
        """
        Detect timestamp format from value.
        
        Args:
            value: Timestamp value to analyze
            
        Returns:
            Detected TimestampFormat
        """
        # Cache key for format detection
        cache_key = str(type(value).__name__) + "_" + str(value)[:50]
        if cache_key in self.format_detection_cache:
            return self.format_detection_cache[cache_key]
        
        detected_format = TimestampFormat.UNKNOWN
        
        if isinstance(value, (int, float)):
            # Numeric timestamp
            if value > 1e15:  # Microseconds
                detected_format = TimestampFormat.UNIX_MICROSECONDS
            elif value > 1e12:  # Milliseconds
                detected_format = TimestampFormat.UNIX_MILLISECONDS
            elif value > 1e9:  # Seconds
                detected_format = TimestampFormat.UNIX_SECONDS
            elif value > 1e8:  # Windows FILETIME (approximate)
                detected_format = TimestampFormat.WINDOWS_FILETIME
            elif 1 <= value <= 100000:  # Days since epoch
                detected_format = TimestampFormat.EPOCH_DAYS
        
        elif isinstance(value, str):
            # String timestamp - use regex patterns
            value_str = value.strip()
            
            for format_type, pattern in self.patterns.items():
                if pattern.match(value_str):
                    detected_format = format_type
                    break
        
        # Cache the result
        self.format_detection_cache[cache_key] = detected_format
        return detected_format
    
    def _try_parse_format(self, 
                         value: Any, 
                         format_type: TimestampFormat,
                         column_name: Optional[str] = None) -> TimestampParseResult:
        """
        Try to parse timestamp using specific format.
        
        Args:
            value: Timestamp value to parse
            format_type: Format to try
            column_name: Optional column name for context
            
        Returns:
            TimestampParseResult with parsing outcome
        """
        try:
            if format_type == TimestampFormat.UNIX_SECONDS:
                return self._parse_unix_seconds(value)
            
            elif format_type == TimestampFormat.UNIX_MILLISECONDS:
                return self._parse_unix_milliseconds(value)
            
            elif format_type == TimestampFormat.UNIX_MICROSECONDS:
                return self._parse_unix_microseconds(value)
            
            elif format_type == TimestampFormat.ISO8601:
                return self._parse_iso8601(value)
            
            elif format_type == TimestampFormat.ISO8601_ZULU:
                return self._parse_iso8601_zulu(value)
            
            elif format_type == TimestampFormat.DATETIME_STRING:
                return self._parse_datetime_string(value)
            
            elif format_type == TimestampFormat.DATE_SLASH_US:
                return self._parse_date_slash_us(value)
            
            elif format_type == TimestampFormat.DATE_SLASH_EU:
                return self._parse_date_slash_eu(value)
            
            elif format_type == TimestampFormat.DATE_DASH:
                return self._parse_date_dash(value)
            
            elif format_type == TimestampFormat.WINDOWS_FILETIME:
                return self._parse_windows_filetime(value)
            
            elif format_type == TimestampFormat.EPOCH_DAYS:
                return self._parse_epoch_days(value)
            
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=format_type,
                    error_message=f"Unsupported format: {format_type}"
                )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=format_type,
                error_message=f"Parse error for {format_type}: {str(e)}"
            )
    
    def _parse_unix_seconds(self, value: Any) -> TimestampParseResult:
        """Parse Unix timestamp in seconds"""
        try:
            timestamp = float(value)
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            
            if self._validate_datetime(dt):
                return TimestampParseResult(
                    success=True,
                    datetime_value=dt,
                    original_value=value,
                    detected_format=TimestampFormat.UNIX_SECONDS,
                    confidence=0.95
                )
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=TimestampFormat.UNIX_SECONDS,
                    error_message="Timestamp validation failed"
                )
        
        except (ValueError, OSError, OverflowError) as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.UNIX_SECONDS,
                error_message=f"Unix seconds parse error: {str(e)}"
            )
    
    def _parse_unix_milliseconds(self, value: Any) -> TimestampParseResult:
        """Parse Unix timestamp in milliseconds"""
        try:
            timestamp = float(value) / 1000.0
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            
            if self._validate_datetime(dt):
                return TimestampParseResult(
                    success=True,
                    datetime_value=dt,
                    original_value=value,
                    detected_format=TimestampFormat.UNIX_MILLISECONDS,
                    confidence=0.95
                )
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=TimestampFormat.UNIX_MILLISECONDS,
                    error_message="Timestamp validation failed"
                )
        
        except (ValueError, OSError, OverflowError) as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.UNIX_MILLISECONDS,
                error_message=f"Unix milliseconds parse error: {str(e)}"
            )
    
    def _parse_unix_microseconds(self, value: Any) -> TimestampParseResult:
        """Parse Unix timestamp in microseconds"""
        try:
            timestamp = float(value) / 1000000.0
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            
            if self._validate_datetime(dt):
                return TimestampParseResult(
                    success=True,
                    datetime_value=dt,
                    original_value=value,
                    detected_format=TimestampFormat.UNIX_MICROSECONDS,
                    confidence=0.95
                )
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=TimestampFormat.UNIX_MICROSECONDS,
                    error_message="Timestamp validation failed"
                )
        
        except (ValueError, OSError, OverflowError) as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.UNIX_MICROSECONDS,
                error_message=f"Unix microseconds parse error: {str(e)}"
            )
    
    def _parse_iso8601(self, value: Any) -> TimestampParseResult:
        """Parse ISO8601 timestamp"""
        try:
            value_str = str(value).strip()
            
            # Handle various ISO8601 formats
            formats = [
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%dT%H:%M:%S.%f%z'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(value_str, fmt)
                    
                    # Add UTC timezone if none specified
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    
                    if self._validate_datetime(dt):
                        return TimestampParseResult(
                            success=True,
                            datetime_value=dt,
                            original_value=value,
                            detected_format=TimestampFormat.ISO8601,
                            confidence=0.9,
                            timezone_info=str(dt.tzinfo)
                        )
                except ValueError:
                    continue
            
            # Try fromisoformat as fallback (Python 3.7+)
            try:
                # Handle Z suffix
                if value_str.endswith('Z'):
                    value_str = value_str[:-1] + '+00:00'
                
                dt = datetime.fromisoformat(value_str)
                
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                if self._validate_datetime(dt):
                    return TimestampParseResult(
                        success=True,
                        datetime_value=dt,
                        original_value=value,
                        detected_format=TimestampFormat.ISO8601,
                        confidence=0.85,
                        timezone_info=str(dt.tzinfo)
                    )
            except ValueError:
                pass
            
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.ISO8601,
                error_message="No matching ISO8601 format found"
            )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.ISO8601,
                error_message=f"ISO8601 parse error: {str(e)}"
            )
    
    def _parse_iso8601_zulu(self, value: Any) -> TimestampParseResult:
        """Parse ISO8601 timestamp with Zulu time"""
        try:
            value_str = str(value).strip()
            
            # Ensure Z suffix
            if not value_str.endswith('Z'):
                value_str += 'Z'
            
            # Remove Z and add UTC timezone
            value_str = value_str[:-1] + '+00:00'
            
            dt = datetime.fromisoformat(value_str)
            
            if self._validate_datetime(dt):
                return TimestampParseResult(
                    success=True,
                    datetime_value=dt,
                    original_value=value,
                    detected_format=TimestampFormat.ISO8601_ZULU,
                    confidence=0.9,
                    timezone_info="UTC"
                )
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=TimestampFormat.ISO8601_ZULU,
                    error_message="Timestamp validation failed"
                )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.ISO8601_ZULU,
                error_message=f"ISO8601 Zulu parse error: {str(e)}"
            )
    
    def _parse_datetime_string(self, value: Any) -> TimestampParseResult:
        """Parse common datetime string formats"""
        try:
            value_str = str(value).strip()
            
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M',
                '%d-%m-%Y %H:%M:%S',
                '%m-%d-%Y %H:%M:%S',
                '%Y/%m/%d %H:%M:%S',
                '%d/%m/%Y %H:%M:%S',
                '%m/%d/%Y %H:%M:%S'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(value_str, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)  # Assume UTC
                    
                    if self._validate_datetime(dt):
                        return TimestampParseResult(
                            success=True,
                            datetime_value=dt,
                            original_value=value,
                            detected_format=TimestampFormat.DATETIME_STRING,
                            confidence=0.8
                        )
                except ValueError:
                    continue
            
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATETIME_STRING,
                error_message="No matching datetime string format found"
            )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATETIME_STRING,
                error_message=f"Datetime string parse error: {str(e)}"
            )
    
    def _parse_date_slash_us(self, value: Any) -> TimestampParseResult:
        """Parse US date format (MM/DD/YYYY)"""
        try:
            value_str = str(value).strip()
            
            formats = [
                '%m/%d/%Y %H:%M:%S',
                '%m/%d/%Y %H:%M',
                '%m/%d/%Y',
                '%m/%d/%y'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(value_str, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)
                    
                    if self._validate_datetime(dt):
                        return TimestampParseResult(
                            success=True,
                            datetime_value=dt,
                            original_value=value,
                            detected_format=TimestampFormat.DATE_SLASH_US,
                            confidence=0.7
                        )
                except ValueError:
                    continue
            
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATE_SLASH_US,
                error_message="No matching US date format found"
            )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATE_SLASH_US,
                error_message=f"US date parse error: {str(e)}"
            )
    
    def _parse_date_slash_eu(self, value: Any) -> TimestampParseResult:
        """Parse European date format (DD/MM/YYYY)"""
        try:
            value_str = str(value).strip()
            
            formats = [
                '%d/%m/%Y %H:%M:%S',
                '%d/%m/%Y %H:%M',
                '%d/%m/%Y',
                '%d/%m/%y'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(value_str, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)
                    
                    if self._validate_datetime(dt):
                        return TimestampParseResult(
                            success=True,
                            datetime_value=dt,
                            original_value=value,
                            detected_format=TimestampFormat.DATE_SLASH_EU,
                            confidence=0.7
                        )
                except ValueError:
                    continue
            
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATE_SLASH_EU,
                error_message="No matching European date format found"
            )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATE_SLASH_EU,
                error_message=f"European date parse error: {str(e)}"
            )
    
    def _parse_date_dash(self, value: Any) -> TimestampParseResult:
        """Parse dash-separated date format (YYYY-MM-DD)"""
        try:
            value_str = str(value).strip()
            
            formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d %H:%M',
                '%Y-%m-%d'
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(value_str, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)
                    
                    if self._validate_datetime(dt):
                        return TimestampParseResult(
                            success=True,
                            datetime_value=dt,
                            original_value=value,
                            detected_format=TimestampFormat.DATE_DASH,
                            confidence=0.8
                        )
                except ValueError:
                    continue
            
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATE_DASH,
                error_message="No matching dash date format found"
            )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.DATE_DASH,
                error_message=f"Dash date parse error: {str(e)}"
            )
    
    def _parse_windows_filetime(self, value: Any) -> TimestampParseResult:
        """Parse Windows FILETIME format"""
        try:
            # Windows FILETIME is 100-nanosecond intervals since January 1, 1601
            filetime = int(value)
            
            # Convert to Unix timestamp
            # FILETIME epoch is January 1, 1601
            # Unix epoch is January 1, 1970
            # Difference is 11644473600 seconds
            unix_timestamp = (filetime / 10000000.0) - 11644473600
            
            dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
            
            if self._validate_datetime(dt):
                return TimestampParseResult(
                    success=True,
                    datetime_value=dt,
                    original_value=value,
                    detected_format=TimestampFormat.WINDOWS_FILETIME,
                    confidence=0.85
                )
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=TimestampFormat.WINDOWS_FILETIME,
                    error_message="Timestamp validation failed"
                )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.WINDOWS_FILETIME,
                error_message=f"Windows FILETIME parse error: {str(e)}"
            )
    
    def _parse_epoch_days(self, value: Any) -> TimestampParseResult:
        """Parse days since Unix epoch"""
        try:
            days = float(value)
            
            # Convert days to seconds and create datetime
            seconds = days * 86400  # 24 * 60 * 60
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
            
            if self._validate_datetime(dt):
                return TimestampParseResult(
                    success=True,
                    datetime_value=dt,
                    original_value=value,
                    detected_format=TimestampFormat.EPOCH_DAYS,
                    confidence=0.6
                )
            else:
                return TimestampParseResult(
                    success=False,
                    datetime_value=None,
                    original_value=value,
                    detected_format=TimestampFormat.EPOCH_DAYS,
                    error_message="Timestamp validation failed"
                )
        
        except Exception as e:
            return TimestampParseResult(
                success=False,
                datetime_value=None,
                original_value=value,
                detected_format=TimestampFormat.EPOCH_DAYS,
                error_message=f"Epoch days parse error: {str(e)}"
            )
    
    def _validate_datetime(self, dt: datetime) -> bool:
        """
        Validate parsed datetime against validation rules.
        
        Args:
            dt: Datetime to validate
            
        Returns:
            True if datetime is valid
        """
        try:
            # Check year range
            if dt.year < self.validation_rules.min_year or dt.year > self.validation_rules.max_year:
                return False
            
            # Check future dates if not allowed
            if not self.validation_rules.allow_future_dates:
                now = datetime.now(tz=timezone.utc)
                if dt > now:
                    return False
            
            # Check maximum future days
            if self.validation_rules.max_future_days > 0:
                now = datetime.now(tz=timezone.utc)
                max_future = now + timedelta(days=self.validation_rules.max_future_days)
                if dt > max_future:
                    return False
            
            # Check timezone requirement
            if self.validation_rules.require_timezone and dt.tzinfo is None:
                return False
            
            return True
        
        except Exception:
            return False
    
    def get_parsing_statistics(self) -> Dict[str, Any]:
        """
        Get parsing statistics.
        
        Returns:
            Dictionary with parsing statistics
        """
        success_rate = (self.successful_parses / self.parse_attempts * 100) if self.parse_attempts > 0 else 0
        
        return {
            'total_attempts': self.parse_attempts,
            'successful_parses': self.successful_parses,
            'failed_parses': self.failed_parses,
            'success_rate_percent': success_rate,
            'cache_size': len(self.format_detection_cache)
        }
    
    def clear_cache(self):
        """Clear format detection cache"""
        self.format_detection_cache.clear()
    
    def find_timestamp_columns(self, 
                              records: List[Dict[str, Any]], 
                              sample_size: int = 100) -> List[Tuple[str, TimestampFormat, float]]:
        """
        Find potential timestamp columns in a dataset.
        
        Args:
            records: List of record dictionaries
            sample_size: Number of records to sample for analysis
            
        Returns:
            List of (column_name, detected_format, confidence) tuples
        """
        if not records:
            return []
        
        # Sample records for analysis
        sample_records = records[:sample_size]
        
        # Get all column names
        all_columns = set()
        for record in sample_records:
            all_columns.update(record.keys())
        
        timestamp_columns = []
        
        for column_name in all_columns:
            # Skip obviously non-timestamp columns
            if any(skip_word in column_name.lower() for skip_word in ['id', 'count', 'size', 'length']):
                continue
            
            # Analyze values in this column
            successful_parses = 0
            total_values = 0
            detected_formats = {}
            
            for record in sample_records:
                if column_name in record and record[column_name] is not None:
                    total_values += 1
                    
                    result = self.parse_timestamp(record[column_name])
                    if result.success:
                        successful_parses += 1
                        format_key = result.detected_format.value
                        detected_formats[format_key] = detected_formats.get(format_key, 0) + 1
            
            # Calculate confidence based on success rate
            if total_values > 0:
                success_rate = successful_parses / total_values
                
                # Require at least 70% success rate to consider it a timestamp column
                if success_rate >= 0.7:
                    # Find most common format
                    most_common_format = TimestampFormat.UNKNOWN
                    if detected_formats:
                        most_common_format_str = max(detected_formats, key=detected_formats.get)
                        most_common_format = TimestampFormat(most_common_format_str)
                    
                    timestamp_columns.append((column_name, most_common_format, success_rate))
        
        # Sort by confidence (success rate)
        timestamp_columns.sort(key=lambda x: x[2], reverse=True)
        
        return timestamp_columns