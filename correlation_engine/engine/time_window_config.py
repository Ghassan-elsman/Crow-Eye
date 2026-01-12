"""
Time-Window Scanning Configuration
Configuration classes for time-window scanning parameters.

This module provides configuration classes that integrate with wing settings
and provide validation for time-window scanning engine parameters.
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TimeWindowScanningConfig:
    """
    Configuration class for time-window scanning parameters.
    
    This class uses wing's time window settings and provides validation
    for configuration values, serialization, and loading capabilities.
    
    Attributes:
        window_size_minutes: Size of each time window (from wing configuration)
        scanning_interval_minutes: Step size between windows (defaults to window size)
        starting_epoch: Start time for scanning (default: None for auto-detection)
        ending_epoch: End time for scanning (default: auto-detect from data)
        auto_detect_time_range: Enable automatic time range detection from data
        max_time_range_years: Maximum reasonable time range in years
        warn_on_large_range: Warn if detected range exceeds max_time_range_years
        enable_overlapping_windows: Allow overlapping windows
        max_records_per_window: Memory management limit
        enable_window_caching: Cache window queries for performance
        parallel_window_processing: Process windows in parallel
        memory_limit_mb: Memory limit for streaming mode activation
        enable_streaming_mode: Allow automatic streaming mode
        debug_mode: Enable debug logging
    """
    
    # Core time window parameters
    window_size_minutes: int = 180  # Default: 3 hours for better correlation accuracy
    scanning_interval_minutes: Optional[int] = None  # Defaults to window_size_minutes
    starting_epoch: Optional[datetime] = None  # Auto-detect from data (was: datetime(2000, 1, 1))
    ending_epoch: Optional[datetime] = None  # Auto-detect from data
    
    # Time range detection settings
    auto_detect_time_range: bool = True
    max_time_range_years: int = 20  # Maximum time span to prevent false timestamps from expanding range
    warn_on_large_range: bool = True
    
    # Empty window optimization
    enable_quick_empty_check: bool = True
    track_empty_window_stats: bool = True
    
    # Advanced window options
    enable_overlapping_windows: bool = False
    max_records_per_window: int = 10000
    enable_window_caching: bool = True
    
    # Performance options
    parallel_window_processing: bool = False
    max_workers: Optional[int] = None  # Auto-detect optimal worker count
    parallel_batch_size: int = 100
    
    # Memory management
    memory_limit_mb: int = 500
    enable_streaming_mode: bool = True
    
    # Debugging and monitoring
    debug_mode: bool = False
    progress_reporting_interval: int = 100  # Report progress every N windows
    
    # Wing adaptation settings
    adapt_wing_time_window: bool = True  # Use wing's time_window_minutes
    adapt_anchor_priority: bool = True   # Map anchor_priority to feather_priority
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        self._validate_configuration()
        
        # Set default scanning interval if not specified
        if self.scanning_interval_minutes is None:
            self.scanning_interval_minutes = self.window_size_minutes
    
    def _validate_configuration(self):
        """Validate configuration values"""
        # Validate window size
        if self.window_size_minutes <= 0:
            raise ValueError(f"window_size_minutes must be positive, got {self.window_size_minutes}")
        
        if self.window_size_minutes > 1440:  # 24 hours
            raise ValueError(f"window_size_minutes too large (max 1440), got {self.window_size_minutes}")
        
        # Validate scanning interval
        if self.scanning_interval_minutes is not None:
            if self.scanning_interval_minutes <= 0:
                raise ValueError(f"scanning_interval_minutes must be positive, got {self.scanning_interval_minutes}")
            
            # Check for overlapping windows
            if self.scanning_interval_minutes < self.window_size_minutes:
                if not self.enable_overlapping_windows:
                    raise ValueError(
                        f"scanning_interval_minutes ({self.scanning_interval_minutes}) < "
                        f"window_size_minutes ({self.window_size_minutes}) requires "
                        f"enable_overlapping_windows=True"
                    )
        
        # Validate epochs (only if provided)
        if self.starting_epoch is not None:
            if self.starting_epoch.year < 1970:
                raise ValueError(f"starting_epoch year must be >= 1970, got {self.starting_epoch.year}")
            
            if self.starting_epoch.year > 2100:
                raise ValueError(f"starting_epoch year must be <= 2100, got {self.starting_epoch.year}")
        
        if self.ending_epoch is not None:
            if self.starting_epoch is not None and self.ending_epoch <= self.starting_epoch:
                raise ValueError(
                    f"ending_epoch ({self.ending_epoch}) must be after "
                    f"starting_epoch ({self.starting_epoch})"
                )
        
        # Validate time range detection settings
        if self.max_time_range_years <= 0:
            raise ValueError(f"max_time_range_years must be positive, got {self.max_time_range_years}")
        
        if self.max_time_range_years > 100:
            raise ValueError(f"max_time_range_years too large (max 100), got {self.max_time_range_years}")
        
        # Validate memory limits
        if self.memory_limit_mb <= 0:
            raise ValueError(f"memory_limit_mb must be positive, got {self.memory_limit_mb}")
        
        if self.memory_limit_mb > 8192:  # 8GB
            raise ValueError(f"memory_limit_mb too large (max 8192), got {self.memory_limit_mb}")
        
        # Validate record limits
        if self.max_records_per_window <= 0:
            raise ValueError(f"max_records_per_window must be positive, got {self.max_records_per_window}")
        
        # Validate parallel processing
        if self.max_workers is not None:
            if self.max_workers <= 0:
                raise ValueError(f"max_workers must be positive, got {self.max_workers}")
            
            if self.max_workers > 32:
                raise ValueError(f"max_workers too large (max 32), got {self.max_workers}")
        
        if self.parallel_batch_size <= 0:
            raise ValueError(f"parallel_batch_size must be positive, got {self.parallel_batch_size}")
    
    def adapt_from_wing(self, wing: Any) -> 'TimeWindowScanningConfig':
        """
        Adapt configuration from wing settings.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            New TimeWindowScanningConfig adapted from wing
        """
        adapted_config = TimeWindowScanningConfig(
            # Use wing's time window settings
            window_size_minutes=wing.correlation_rules.time_window_minutes if self.adapt_wing_time_window else self.window_size_minutes,
            scanning_interval_minutes=wing.correlation_rules.time_window_minutes if self.adapt_wing_time_window else self.scanning_interval_minutes,
            
            # Keep other settings from current config
            starting_epoch=self.starting_epoch,
            ending_epoch=self.ending_epoch,
            enable_overlapping_windows=self.enable_overlapping_windows,
            max_records_per_window=self.max_records_per_window,
            enable_window_caching=self.enable_window_caching,
            parallel_window_processing=self.parallel_window_processing,
            max_workers=self.max_workers,
            parallel_batch_size=self.parallel_batch_size,
            memory_limit_mb=self.memory_limit_mb,
            enable_streaming_mode=self.enable_streaming_mode,
            debug_mode=self.debug_mode,
            progress_reporting_interval=self.progress_reporting_interval,
            adapt_wing_time_window=self.adapt_wing_time_window,
            adapt_anchor_priority=self.adapt_anchor_priority
        )
        
        return adapted_config
    
    def get_total_windows_estimate(self, start_time: datetime, end_time: datetime) -> int:
        """
        Estimate total number of windows for the given time range.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            Estimated number of windows
        """
        total_minutes = (end_time - start_time).total_seconds() / 60
        return max(1, int(total_minutes / self.scanning_interval_minutes) + 1)
    
    def get_window_duration(self) -> timedelta:
        """Get window duration as timedelta"""
        return timedelta(minutes=self.window_size_minutes)
    
    def get_scanning_interval(self) -> timedelta:
        """Get scanning interval as timedelta"""
        return timedelta(minutes=self.scanning_interval_minutes)
    
    def is_overlapping_mode(self) -> bool:
        """Check if configuration uses overlapping windows"""
        return self.scanning_interval_minutes < self.window_size_minutes
    
    def get_overlap_minutes(self) -> int:
        """Get overlap duration in minutes (0 if non-overlapping)"""
        if self.is_overlapping_mode():
            return self.window_size_minutes - self.scanning_interval_minutes
        return 0
    
    def validate_compatibility(self, wing: Any) -> List[str]:
        """
        Validate compatibility with wing configuration.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            List of warning messages (empty if fully compatible)
        """
        warnings = []
        
        # Check time window compatibility
        wing_window_minutes = wing.correlation_rules.time_window_minutes
        if self.adapt_wing_time_window and wing_window_minutes != self.window_size_minutes:
            warnings.append(
                f"Wing time window ({wing_window_minutes} min) differs from config "
                f"({self.window_size_minutes} min). Wing setting will be used."
            )
        
        # Check minimum matches compatibility
        if hasattr(wing.correlation_rules, 'minimum_matches'):
            min_matches = wing.correlation_rules.minimum_matches
            if min_matches > len(wing.feathers) - 1:
                warnings.append(
                    f"Wing minimum_matches ({min_matches}) may be too high for "
                    f"available feathers ({len(wing.feathers)})"
                )
        
        # Check feather count for parallel processing
        if self.parallel_window_processing and len(wing.feathers) < 2:
            warnings.append(
                "Parallel processing enabled but only one feather available. "
                "Consider disabling parallel processing."
            )
        
        return warnings
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary for serialization.
        
        Returns:
            Dictionary representation of configuration
        """
        return {
            'window_size_minutes': self.window_size_minutes,
            'scanning_interval_minutes': self.scanning_interval_minutes,
            'starting_epoch': self.starting_epoch.isoformat() if self.starting_epoch else None,
            'ending_epoch': self.ending_epoch.isoformat() if self.ending_epoch else None,
            'auto_detect_time_range': self.auto_detect_time_range,
            'max_time_range_years': self.max_time_range_years,
            'warn_on_large_range': self.warn_on_large_range,
            'enable_quick_empty_check': self.enable_quick_empty_check,
            'track_empty_window_stats': self.track_empty_window_stats,
            'enable_overlapping_windows': self.enable_overlapping_windows,
            'max_records_per_window': self.max_records_per_window,
            'enable_window_caching': self.enable_window_caching,
            'parallel_window_processing': self.parallel_window_processing,
            'max_workers': self.max_workers,
            'parallel_batch_size': self.parallel_batch_size,
            'memory_limit_mb': self.memory_limit_mb,
            'enable_streaming_mode': self.enable_streaming_mode,
            'debug_mode': self.debug_mode,
            'progress_reporting_interval': self.progress_reporting_interval,
            'adapt_wing_time_window': self.adapt_wing_time_window,
            'adapt_anchor_priority': self.adapt_anchor_priority
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TimeWindowScanningConfig':
        """
        Create configuration from dictionary.
        
        Args:
            data: Dictionary containing configuration data
            
        Returns:
            TimeWindowScanningConfig instance
        """
        # Parse datetime fields
        starting_epoch = None
        if data.get('starting_epoch'):
            starting_epoch = datetime.fromisoformat(data['starting_epoch'])
        
        ending_epoch = None
        if data.get('ending_epoch'):
            ending_epoch = datetime.fromisoformat(data['ending_epoch'])
        
        return cls(
            window_size_minutes=data['window_size_minutes'],
            scanning_interval_minutes=data.get('scanning_interval_minutes'),
            starting_epoch=starting_epoch,
            ending_epoch=ending_epoch,
            auto_detect_time_range=data.get('auto_detect_time_range', True),
            max_time_range_years=data.get('max_time_range_years', 30),  # Increased default
            warn_on_large_range=data.get('warn_on_large_range', True),
            enable_quick_empty_check=data.get('enable_quick_empty_check', True),
            track_empty_window_stats=data.get('track_empty_window_stats', True),
            enable_overlapping_windows=data.get('enable_overlapping_windows', False),
            max_records_per_window=data.get('max_records_per_window', 10000),
            enable_window_caching=data.get('enable_window_caching', True),
            parallel_window_processing=data.get('parallel_window_processing', False),
            max_workers=data.get('max_workers'),
            parallel_batch_size=data.get('parallel_batch_size', 100),
            memory_limit_mb=data.get('memory_limit_mb', 500),
            enable_streaming_mode=data.get('enable_streaming_mode', True),
            debug_mode=data.get('debug_mode', False),
            progress_reporting_interval=data.get('progress_reporting_interval', 100),
            adapt_wing_time_window=data.get('adapt_wing_time_window', True),
            adapt_anchor_priority=data.get('adapt_anchor_priority', True)
        )
    
    def save_to_file(self, file_path: str):
        """
        Save configuration to JSON file.
        
        Args:
            file_path: Path to save configuration file
        """
        config_dict = self.to_dict()
        
        # Ensure directory exists
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w') as f:
            json.dump(config_dict, f, indent=2)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'TimeWindowScanningConfig':
        """
        Load configuration from JSON file.
        
        Args:
            file_path: Path to configuration file
            
        Returns:
            TimeWindowScanningConfig instance
            
        Raises:
            FileNotFoundError: If configuration file doesn't exist
            ValueError: If configuration file is invalid
        """
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            return cls.from_dict(data)
        
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid configuration file {file_path}: {str(e)}")
    
    @classmethod
    def create_default(cls) -> 'TimeWindowScanningConfig':
        """
        Create default configuration with sensible values.
        
        Returns:
            TimeWindowScanningConfig with default settings
        """
        return cls(
            window_size_minutes=180,  # Default: 3 hours for better correlation accuracy
            scanning_interval_minutes=180,  # Non-overlapping by default
            starting_epoch=None,  # Auto-detect from data
            ending_epoch=None,  # Auto-detect from data
            auto_detect_time_range=True,
            max_time_range_years=20,  # Maximum time span to prevent false timestamps from expanding range
            warn_on_large_range=True,
            enable_quick_empty_check=True,
            track_empty_window_stats=True,
            enable_overlapping_windows=False,
            max_records_per_window=10000,
            enable_window_caching=True,
            parallel_window_processing=False,  # Disabled by default for compatibility
            max_workers=None,  # Auto-detect
            parallel_batch_size=100,
            memory_limit_mb=500,
            enable_streaming_mode=True,
            debug_mode=False,
            progress_reporting_interval=100,
            adapt_wing_time_window=True,
            adapt_anchor_priority=True
        )
    
    def __str__(self) -> str:
        """String representation of configuration"""
        overlap_info = f" (overlapping by {self.get_overlap_minutes()} min)" if self.is_overlapping_mode() else ""
        parallel_info = f", parallel: {self.max_workers or 'auto'} workers" if self.parallel_window_processing else ""
        
        # Handle None starting_epoch gracefully
        if self.starting_epoch:
            epoch_info = f"epoch: {self.starting_epoch.year}-{self.starting_epoch.month:02d}-{self.starting_epoch.day:02d}, "
        else:
            epoch_info = "epoch: auto-detect, "
        
        return (
            f"TimeWindowScanningConfig("
            f"window: {self.window_size_minutes} min, "
            f"interval: {self.scanning_interval_minutes} min{overlap_info}, "
            f"{epoch_info}"
            f"memory: {self.memory_limit_mb} MB{parallel_info})"
        )