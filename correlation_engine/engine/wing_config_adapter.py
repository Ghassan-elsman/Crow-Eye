"""
Wing Configuration Adapter
Adapter to use wing's time_window_minutes as scanning window size.

This module provides functionality to adapt existing wing configurations
for use with the time-window scanning engine, including validation and
warning for incompatible configurations.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import warnings
from dataclasses import dataclass

from .time_window_config import TimeWindowScanningConfig


@dataclass
class WingAdaptationResult:
    """
    Result of wing configuration adaptation.
    
    Attributes:
        adapted_config: The adapted TimeWindowScanningConfig
        warnings: List of warning messages about adaptations made
        incompatibilities: List of incompatible settings that couldn't be adapted
        feather_priority_mapping: Mapping from anchor_priority to feather_priority
        success: Whether the adaptation was successful (no incompatibilities)
    """
    adapted_config: TimeWindowScanningConfig
    warnings: List[str]
    incompatibilities: List[str]
    feather_priority_mapping: Dict[str, float]
    
    @property
    def success(self) -> bool:
        """Return True if adaptation was successful (no incompatibilities)."""
        return len(self.incompatibilities) == 0


class WingConfigurationAdapter:
    """
    Adapter to use wing's time window settings for time-window scanning.
    
    This class handles:
    1. Using wing's time_window_minutes as scanning window size
    2. Setting scanning interval to match window size by default (non-overlapping)
    3. Mapping anchor_priority to feather_priority within windows
    4. Validation and warnings for incompatible configurations
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize wing configuration adapter.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
    
    def adapt_wing_configuration(self, 
                                wing: Any, 
                                base_config: Optional[TimeWindowScanningConfig] = None) -> WingAdaptationResult:
        """
        Adapt wing configuration for time-window scanning.
        
        Args:
            wing: Wing configuration object
            base_config: Base configuration to adapt (uses default if None)
            
        Returns:
            WingAdaptationResult with adapted configuration and warnings
        """
        if base_config is None:
            base_config = TimeWindowScanningConfig.create_default()
        
        warnings_list = []
        incompatibilities = []
        
        # Extract wing settings
        wing_settings = self._extract_wing_settings(wing)
        
        if self.debug_mode:
            print(f"[WingAdapter] Adapting wing configuration: {wing_settings}")
        
        # Create adapted configuration
        adapted_config = TimeWindowScanningConfig(
            # Use wing's time window as scanning window size
            window_size_minutes=wing_settings['time_window_minutes'],
            scanning_interval_minutes=wing_settings['time_window_minutes'],  # Non-overlapping by default
            
            # Use wing's max_time_range_years if specified
            max_time_range_years=wing_settings['max_time_range_years'],
            
            # Keep base configuration for other settings
            starting_epoch=base_config.starting_epoch,
            ending_epoch=base_config.ending_epoch,
            enable_overlapping_windows=base_config.enable_overlapping_windows,
            max_records_per_window=base_config.max_records_per_window,
            enable_window_caching=base_config.enable_window_caching,
            parallel_window_processing=base_config.parallel_window_processing,
            max_workers=base_config.max_workers,
            parallel_batch_size=base_config.parallel_batch_size,
            memory_limit_mb=base_config.memory_limit_mb,
            enable_streaming_mode=base_config.enable_streaming_mode,
            debug_mode=base_config.debug_mode,
            progress_reporting_interval=base_config.progress_reporting_interval,
            adapt_wing_time_window=True,
            adapt_anchor_priority=True
        )
        
        # Validate wing compatibility
        validation_warnings = self._validate_wing_compatibility(wing, adapted_config)
        warnings_list.extend(validation_warnings)
        
        # Map anchor priority to feather priority
        feather_priority_mapping = self._map_anchor_to_feather_priority(wing)
        
        # Check for incompatible settings
        incompatibility_checks = self._check_incompatible_settings(wing, adapted_config)
        incompatibilities.extend(incompatibility_checks)
        
        # Log adaptation results
        if self.debug_mode:
            print(f"[WingAdapter] Adapted configuration: {adapted_config}")
            if warnings_list:
                print(f"[WingAdapter] Warnings: {warnings_list}")
            if incompatibilities:
                print(f"[WingAdapter] Incompatibilities: {incompatibilities}")
        
        return WingAdaptationResult(
            adapted_config=adapted_config,
            warnings=warnings_list,
            incompatibilities=incompatibilities,
            feather_priority_mapping=feather_priority_mapping
        )
    
    def _extract_wing_settings(self, wing: Any) -> Dict[str, Any]:
        """
        Extract relevant settings from wing configuration.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            Dictionary of extracted settings
        """
        settings = {}
        
        # Extract time window minutes
        if hasattr(wing, 'correlation_rules') and hasattr(wing.correlation_rules, 'time_window_minutes'):
            settings['time_window_minutes'] = wing.correlation_rules.time_window_minutes
        else:
            # Fallback to default
            settings['time_window_minutes'] = 180
            if self.debug_mode:
                print("[WingAdapter] Warning: No time_window_minutes found, using default 180 minutes (3 hours)")
        
        # Extract minimum matches
        if hasattr(wing, 'correlation_rules') and hasattr(wing.correlation_rules, 'minimum_matches'):
            settings['minimum_matches'] = wing.correlation_rules.minimum_matches
        else:
            settings['minimum_matches'] = 1
        
        # Extract max_time_range_years
        if hasattr(wing, 'correlation_rules') and hasattr(wing.correlation_rules, 'max_time_range_years'):
            settings['max_time_range_years'] = wing.correlation_rules.max_time_range_years
        else:
            settings['max_time_range_years'] = 20  # Default
        
        # Extract anchor priority (if exists)
        if hasattr(wing, 'correlation_rules') and hasattr(wing.correlation_rules, 'anchor_priority'):
            settings['anchor_priority'] = wing.correlation_rules.anchor_priority
        else:
            settings['anchor_priority'] = None
        
        # Extract feather information
        if hasattr(wing, 'feathers'):
            settings['feathers'] = wing.feathers
            settings['feather_count'] = len(wing.feathers)
        else:
            settings['feathers'] = []
            settings['feather_count'] = 0
        
        # Extract wing identification
        settings['wing_id'] = getattr(wing, 'wing_id', 'unknown')
        settings['wing_name'] = getattr(wing, 'wing_name', 'unknown')
        
        return settings
    
    def _validate_wing_compatibility(self, wing: Any, config: TimeWindowScanningConfig) -> List[str]:
        """
        Validate compatibility between wing and adapted configuration.
        
        Args:
            wing: Wing configuration object
            config: Adapted configuration
            
        Returns:
            List of warning messages
        """
        warnings_list = []
        wing_settings = self._extract_wing_settings(wing)
        
        # Check time window size
        wing_window = wing_settings['time_window_minutes']
        if wing_window < 1:
            warnings_list.append(
                f"Wing time window ({wing_window} min) is very small. "
                f"Consider using at least 1 minute for meaningful correlations."
            )
        elif wing_window > 60:
            warnings_list.append(
                f"Wing time window ({wing_window} min) is large. "
                f"This may result in many correlations per window."
            )
        
        # Check minimum matches vs feather count
        min_matches = wing_settings['minimum_matches']
        feather_count = wing_settings['feather_count']
        
        if min_matches >= feather_count:
            warnings_list.append(
                f"Wing minimum_matches ({min_matches}) >= feather count ({feather_count}). "
                f"No correlations will be possible. Consider reducing minimum_matches."
            )
        elif min_matches == feather_count - 1 and feather_count > 2:
            warnings_list.append(
                f"Wing minimum_matches ({min_matches}) requires all feathers to have records "
                f"in each window. This may result in few correlations."
            )
        
        # Check feather count for meaningful correlations
        if feather_count < 2:
            warnings_list.append(
                f"Wing has only {feather_count} feather(s). "
                f"At least 2 feathers are needed for correlations."
            )
        
        # Check parallel processing compatibility
        if config.parallel_window_processing and feather_count < 2:
            warnings_list.append(
                "Parallel processing enabled but insufficient feathers for meaningful correlations."
            )
        
        return warnings_list
    
    def _map_anchor_to_feather_priority(self, wing: Any) -> Dict[str, float]:
        """
        Map anchor_priority to feather_priority within windows.
        
        Args:
            wing: Wing configuration object
            
        Returns:
            Dictionary mapping feather_id to priority value
        """
        feather_priority_mapping = {}
        wing_settings = self._extract_wing_settings(wing)
        
        # Get anchor priority settings
        anchor_priority = wing_settings.get('anchor_priority')
        
        if anchor_priority and isinstance(anchor_priority, dict):
            # Map anchor priorities to feather priorities
            for feather in wing_settings['feathers']:
                feather_id = feather.feather_id
                artifact_type = getattr(feather, 'artifact_type', feather_id)
                
                # Look for priority by feather_id first, then artifact_type
                priority = anchor_priority.get(feather_id)
                if priority is None:
                    priority = anchor_priority.get(artifact_type)
                if priority is None:
                    priority = 1.0  # Default priority
                
                feather_priority_mapping[feather_id] = float(priority)
                
                if self.debug_mode:
                    print(f"[WingAdapter] Mapped {feather_id} ({artifact_type}) -> priority {priority}")
        
        else:
            # No anchor priority specified, use equal priority
            for feather in wing_settings['feathers']:
                feather_priority_mapping[feather.feather_id] = 1.0
            
            if self.debug_mode:
                print("[WingAdapter] No anchor_priority found, using equal priority for all feathers")
        
        return feather_priority_mapping
    
    def _check_incompatible_settings(self, wing: Any, config: TimeWindowScanningConfig) -> List[str]:
        """
        Check for incompatible settings that cannot be adapted.
        
        Args:
            wing: Wing configuration object
            config: Adapted configuration
            
        Returns:
            List of incompatibility messages
        """
        incompatibilities = []
        wing_settings = self._extract_wing_settings(wing)
        
        # Check for settings that cannot be adapted
        if hasattr(wing, 'correlation_rules'):
            rules = wing.correlation_rules
            
            # Check for identity-based filtering (not supported by time-window scanning)
            if hasattr(rules, 'identity_filters') and rules.identity_filters:
                incompatibilities.append(
                    "Wing uses identity_filters which are not supported by time-window scanning engine. "
                    "Consider using identity-based correlation engine instead."
                )
            
            # Check for complex semantic rules that may not work well with time windows
            if hasattr(rules, 'semantic_rules') and rules.semantic_rules:
                # This is a warning rather than incompatibility
                pass
            
            # Check for very specific anchor-based configurations
            if hasattr(rules, 'anchor_selection_strategy') and rules.anchor_selection_strategy != 'time_based':
                incompatibilities.append(
                    f"Wing uses anchor_selection_strategy '{rules.anchor_selection_strategy}' "
                    f"which is not compatible with time-window scanning. "
                    f"Time-window scanning uses systematic time-based approach."
                )
        
        return incompatibilities
    
    def create_adapted_wing_rules(self, wing: Any, feather_priority_mapping: Dict[str, float]) -> Any:
        """
        Create adapted correlation rules for the wing.
        
        Args:
            wing: Original wing configuration
            feather_priority_mapping: Mapping of feather priorities
            
        Returns:
            Adapted wing with modified correlation rules
        """
        # Create a copy of the wing (shallow copy for safety)
        adapted_wing = wing
        
        # Update correlation rules if they exist
        if hasattr(adapted_wing, 'correlation_rules'):
            rules = adapted_wing.correlation_rules
            
            # Add feather priority mapping
            if not hasattr(rules, 'feather_priority'):
                rules.feather_priority = feather_priority_mapping
            else:
                # Update existing feather priority
                rules.feather_priority.update(feather_priority_mapping)
            
            # Ensure time-based anchor selection
            if hasattr(rules, 'anchor_selection_strategy'):
                rules.anchor_selection_strategy = 'time_based'
            
            if self.debug_mode:
                print(f"[WingAdapter] Updated wing correlation rules with feather priorities: {feather_priority_mapping}")
        
        return adapted_wing
    
    def validate_adapted_configuration(self, 
                                     wing: Any, 
                                     config: TimeWindowScanningConfig) -> Tuple[bool, List[str]]:
        """
        Validate that the adapted configuration will work with the wing.
        
        Args:
            wing: Wing configuration object
            config: Adapted configuration
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        wing_settings = self._extract_wing_settings(wing)
        
        # Check basic requirements
        if wing_settings['feather_count'] < 2:
            issues.append("At least 2 feathers are required for correlation")
        
        if wing_settings['minimum_matches'] >= wing_settings['feather_count']:
            issues.append("minimum_matches must be less than the number of feathers")
        
        if config.window_size_minutes <= 0:
            issues.append("window_size_minutes must be positive")
        
        # Check memory requirements
        estimated_memory_per_window = wing_settings['feather_count'] * config.max_records_per_window * 0.001  # Rough estimate in MB
        if estimated_memory_per_window > config.memory_limit_mb:
            issues.append(
                f"Estimated memory per window ({estimated_memory_per_window:.1f} MB) "
                f"exceeds memory limit ({config.memory_limit_mb} MB)"
            )
        
        # Check parallel processing requirements
        if config.parallel_window_processing and config.max_workers and config.max_workers > wing_settings['feather_count']:
            issues.append(
                f"max_workers ({config.max_workers}) should not exceed feather count ({wing_settings['feather_count']})"
            )
        
        is_valid = len(issues) == 0
        return is_valid, issues
    
    def get_adaptation_summary(self, result: WingAdaptationResult) -> str:
        """
        Get a human-readable summary of the adaptation.
        
        Args:
            result: Wing adaptation result
            
        Returns:
            Summary string
        """
        config = result.adapted_config
        
        summary_lines = [
            "Wing Configuration Adaptation Summary:",
            f"  Window Size: {config.window_size_minutes} minutes",
            f"  Scanning Interval: {config.scanning_interval_minutes} minutes",
            f"  Window Mode: {'Overlapping' if config.is_overlapping_mode() else 'Non-overlapping'}",
            f"  Starting Epoch: {config.starting_epoch.strftime('%Y-%m-%d')}",
            f"  Memory Limit: {config.memory_limit_mb} MB",
            f"  Parallel Processing: {'Enabled' if config.parallel_window_processing else 'Disabled'}",
        ]
        
        if result.feather_priority_mapping:
            summary_lines.append("  Feather Priorities:")
            for feather_id, priority in result.feather_priority_mapping.items():
                summary_lines.append(f"    {feather_id}: {priority}")
        
        if result.warnings:
            summary_lines.append("  Warnings:")
            for warning in result.warnings:
                summary_lines.append(f"    - {warning}")
        
        if result.incompatibilities:
            summary_lines.append("  Incompatibilities:")
            for incompatibility in result.incompatibilities:
                summary_lines.append(f"    - {incompatibility}")
        
        return "\n".join(summary_lines)


def adapt_wing_for_time_window_scanning(wing: Any, 
                                       base_config: Optional[TimeWindowScanningConfig] = None,
                                       debug_mode: bool = False) -> WingAdaptationResult:
    """
    Convenience function to adapt wing configuration for time-window scanning.
    
    Args:
        wing: Wing configuration object
        base_config: Base configuration to adapt (uses default if None)
        debug_mode: Enable debug logging
        
    Returns:
        WingAdaptationResult with adapted configuration and warnings
    """
    adapter = WingConfigurationAdapter(debug_mode=debug_mode)
    return adapter.adapt_wing_configuration(wing, base_config)


def validate_wing_compatibility(wing: Any, 
                               config: Optional[TimeWindowScanningConfig] = None) -> Tuple[bool, List[str], List[str]]:
    """
    Validate wing compatibility with time-window scanning.
    
    Args:
        wing: Wing configuration object
        config: Configuration to validate against (uses default if None)
        
    Returns:
        Tuple of (is_compatible, warnings, incompatibilities)
    """
    if config is None:
        config = TimeWindowScanningConfig.create_default()
    
    adapter = WingConfigurationAdapter()
    result = adapter.adapt_wing_configuration(wing, config)
    
    is_compatible = len(result.incompatibilities) == 0
    return is_compatible, result.warnings, result.incompatibilities