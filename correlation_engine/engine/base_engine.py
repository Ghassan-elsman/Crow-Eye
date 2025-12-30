"""
Base Correlation Engine
Abstract base class for all correlation engines.

This module provides the foundation for implementing different correlation strategies
while maintaining a consistent interface for the pipeline executor.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EngineMetadata:
    """
    Metadata describing a correlation engine.
    
    Attributes:
        name: Human-readable engine name
        version: Engine version string
        description: Brief description of engine capabilities
        complexity: Big-O complexity notation (e.g., "O(N²)", "O(N log N)")
        best_for: List of use cases where this engine excels
        supports_identity_filter: Whether engine supports identity-based filtering
    """
    name: str
    version: str
    description: str
    complexity: str
    best_for: List[str]
    supports_identity_filter: bool


@dataclass
class FilterConfig:
    """
    Configuration for filtering correlation records.
    
    Attributes:
        time_period_start: Start of time period filter (inclusive)
        time_period_end: End of time period filter (inclusive)
        identity_filters: List of identity patterns to match (supports wildcards)
        case_sensitive: Whether identity matching is case-sensitive
    """
    time_period_start: Optional[datetime] = None
    time_period_end: Optional[datetime] = None
    identity_filters: Optional[List[str]] = None
    case_sensitive: bool = False
    
    def __post_init__(self):
        """Validate filter configuration"""
        # Validate time period
        if (self.time_period_start and self.time_period_end and 
            self.time_period_start > self.time_period_end):
            raise ValueError(
                f"time_period_start ({self.time_period_start}) must be "
                f"before time_period_end ({self.time_period_end})"
            )
        
        # Validate identity filters
        if self.identity_filters is not None:
            if not isinstance(self.identity_filters, list):
                raise TypeError("identity_filters must be a list of strings")
            # Filter out empty strings
            self.identity_filters = [f.strip() for f in self.identity_filters if f.strip()]


class BaseCorrelationEngine(ABC):
    """
    Abstract base class for correlation engines.
    
    All correlation engines must inherit from this class and implement
    the required abstract methods. This ensures a consistent interface
    for the pipeline executor regardless of which engine is selected.
    
    Example:
        class MyEngine(BaseCorrelationEngine):
            @property
            def metadata(self) -> EngineMetadata:
                return EngineMetadata(
                    name="My Engine",
                    version="1.0.0",
                    description="Custom correlation engine",
                    complexity="O(N)",
                    best_for=["Fast processing"],
                    supports_identity_filter=False
                )
            
            def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
                # Implementation here
                pass
    """
    
    def __init__(self, config: Any, filters: Optional[FilterConfig] = None):
        """
        Initialize correlation engine.
        
        Args:
            config: Pipeline configuration object
            filters: Optional filter configuration
        """
        self.config = config
        self.filters = filters or FilterConfig()
    
    @abstractmethod
    def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
        """
        Execute correlation with configured filters.
        
        Args:
            wing_configs: List of Wing configuration objects
            
        Returns:
            Dictionary containing:
                - 'result': Correlation result object
                - 'engine_type': Engine type identifier
                - 'filters_applied': Dictionary of applied filters
                
        Raises:
            Exception: If correlation fails
        """
        pass
    
    @abstractmethod
    def get_results(self) -> Any:
        """
        Get correlation results from last execution.
        
        Returns:
            Correlation results object (format depends on engine)
        """
        pass
    
    @abstractmethod
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get correlation statistics from last execution.
        
        Returns:
            Dictionary containing statistics:
                - execution_time: Execution duration in seconds
                - record_count: Number of records processed
                - match_count: Number of matches found
                - duplicate_rate: Percentage of duplicate matches
                - etc.
        """
        pass
    
    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata:
        """
        Get engine metadata.
        
        Returns:
            EngineMetadata describing this engine
        """
        pass
    
    def apply_time_period_filter(self, records: List[Dict]) -> List[Dict]:
        """
        Apply time period filter to records (common implementation).
        
        This method is provided as a common implementation that both engines
        can use. It filters records to only include those within the configured
        time period.
        
        Args:
            records: List of records to filter
            
        Returns:
            Filtered list of records within time period
        """
        if not self.filters.time_period_start and not self.filters.time_period_end:
            return records  # No filter applied
        
        filtered = []
        skipped_count = 0
        
        for record in records:
            timestamp = self._parse_timestamp(record.get('timestamp'))
            
            if not timestamp:
                skipped_count += 1
                continue
            
            # Check start time
            if self.filters.time_period_start and timestamp < self.filters.time_period_start:
                continue
            
            # Check end time
            if self.filters.time_period_end and timestamp > self.filters.time_period_end:
                continue
            
            filtered.append(record)
        
        # Log filter statistics
        if skipped_count > 0:
            print(f"[Time Filter] Skipped {skipped_count} records with invalid timestamps")
        
        if len(filtered) < len(records):
            print(f"[Time Filter] Filtered {len(records)} → {len(filtered)} records "
                  f"({len(records) - len(filtered)} excluded)")
        
        return filtered
    
    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        """
        Parse timestamp from various formats.
        
        Supports:
        - datetime objects (returned as-is)
        - ISO 8601 strings
        - Unix timestamps (seconds)
        - Unix timestamps (milliseconds)
        - Windows FILETIME
        
        Args:
            value: Timestamp value to parse
            
        Returns:
            Parsed datetime or None if invalid
        """
        if not value:
            return None
        
        # Already a datetime
        if isinstance(value, datetime):
            return value
        
        # Convert to string
        timestamp_str = str(value).strip()
        
        if not timestamp_str or timestamp_str.lower() in ('none', 'null', 'n/a', ''):
            return None
        
        # Try numeric timestamps
        try:
            numeric_value = float(timestamp_str)
            
            # Windows FILETIME (100-nanosecond intervals since 1601-01-01)
            if numeric_value > 10000000000000:
                unix_timestamp = (numeric_value - 116444736000000000) / 10000000
                parsed_time = datetime.fromtimestamp(unix_timestamp)
            # Unix timestamp in milliseconds
            elif numeric_value > 10000000000:
                parsed_time = datetime.fromtimestamp(numeric_value / 1000)
            # Unix timestamp in seconds
            elif numeric_value > 0:
                parsed_time = datetime.fromtimestamp(numeric_value)
            else:
                return None
            
            # Validate range
            if 1970 <= parsed_time.year <= 2100:
                return parsed_time
            return None
            
        except (ValueError, OSError, OverflowError):
            pass
        
        # Try ISO format
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            pass
        
        # Try common formats
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        
        for fmt in formats:
            try:
                parsed_time = datetime.strptime(timestamp_str, fmt)
                if 1970 <= parsed_time.year <= 2100:
                    return parsed_time
            except:
                continue
        
        return None
