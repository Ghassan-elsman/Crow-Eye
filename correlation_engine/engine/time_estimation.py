"""
Advanced Time Estimation and Completion Tracking

This module provides sophisticated time estimation algorithms for the time-window
scanning correlation engine, including adaptive estimation, performance prediction,
and completion tracking with multiple estimation strategies.
"""

import time
import statistics
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import deque
import math


@dataclass
class ProcessingMeasurement:
    """A single measurement of processing performance"""
    timestamp: datetime
    windows_processed: int
    processing_time_seconds: float
    records_processed: int
    matches_found: int
    memory_usage_mb: Optional[float] = None
    
    @property
    def windows_per_second(self) -> float:
        """Calculate windows processed per second"""
        return self.windows_processed / max(0.001, self.processing_time_seconds)
    
    @property
    def records_per_second(self) -> float:
        """Calculate records processed per second"""
        return self.records_processed / max(0.001, self.processing_time_seconds)


@dataclass
class EstimationResult:
    """Result of time estimation calculation"""
    estimated_completion_time: Optional[datetime]
    time_remaining_seconds: Optional[float]
    confidence_level: float  # 0.0 to 1.0
    processing_rate_windows_per_second: float
    processing_rate_records_per_second: float
    estimation_method: str
    trend_direction: str  # "improving", "stable", "degrading"
    
    @property
    def time_remaining_formatted(self) -> str:
        """Format time remaining as human-readable string"""
        if not self.time_remaining_seconds:
            return "Unknown"
        
        remaining = timedelta(seconds=self.time_remaining_seconds)
        
        # Format based on duration
        if remaining.total_seconds() < 60:
            return f"{int(remaining.total_seconds())}s"
        elif remaining.total_seconds() < 3600:
            minutes = int(remaining.total_seconds() / 60)
            seconds = int(remaining.total_seconds() % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(remaining.total_seconds() / 3600)
            minutes = int((remaining.total_seconds() % 3600) / 60)
            return f"{hours}h {minutes}m"


class AdaptiveTimeEstimator:
    """
    Advanced time estimator that adapts to changing processing conditions.
    
    Uses multiple estimation strategies and selects the most appropriate one
    based on processing patterns and data characteristics.
    """
    
    def __init__(self, 
                 measurement_window_size: int = 100,
                 min_measurements_for_estimation: int = 5,
                 trend_analysis_window: int = 20):
        """
        Initialize adaptive time estimator.
        
        Args:
            measurement_window_size: Maximum number of measurements to keep
            min_measurements_for_estimation: Minimum measurements needed for estimation
            trend_analysis_window: Number of recent measurements for trend analysis
        """
        self.measurement_window_size = measurement_window_size
        self.min_measurements_for_estimation = min_measurements_for_estimation
        self.trend_analysis_window = trend_analysis_window
        
        # Measurement storage
        self.measurements: deque = deque(maxlen=measurement_window_size)
        self.start_time: Optional[datetime] = None
        self.last_measurement_time: Optional[datetime] = None
        
        # Estimation strategies
        self.estimation_strategies = {
            'simple_average': self._estimate_simple_average,
            'weighted_average': self._estimate_weighted_average,
            'linear_regression': self._estimate_linear_regression,
            'exponential_smoothing': self._estimate_exponential_smoothing,
            'trend_adjusted': self._estimate_trend_adjusted
        }
        
        # Strategy selection weights (updated based on accuracy)
        self.strategy_weights = {
            'simple_average': 1.0,
            'weighted_average': 1.2,
            'linear_regression': 1.1,
            'exponential_smoothing': 1.3,
            'trend_adjusted': 1.0
        }
        
        # Performance tracking
        self.estimation_accuracy_history: List[float] = []
        self.last_estimation: Optional[EstimationResult] = None
    
    def start_tracking(self):
        """Start time estimation tracking"""
        self.start_time = datetime.now()
        self.last_measurement_time = self.start_time
        self.measurements.clear()
        self.estimation_accuracy_history.clear()
    
    def add_measurement(self, 
                       windows_processed: int,
                       processing_time_seconds: float,
                       records_processed: int = 0,
                       matches_found: int = 0,
                       memory_usage_mb: Optional[float] = None):
        """
        Add a processing measurement.
        
        Args:
            windows_processed: Number of windows processed in this measurement
            processing_time_seconds: Time taken for processing
            records_processed: Number of records processed
            matches_found: Number of matches found
            memory_usage_mb: Current memory usage
        """
        measurement = ProcessingMeasurement(
            timestamp=datetime.now(),
            windows_processed=windows_processed,
            processing_time_seconds=processing_time_seconds,
            records_processed=records_processed,
            matches_found=matches_found,
            memory_usage_mb=memory_usage_mb
        )
        
        self.measurements.append(measurement)
        self.last_measurement_time = measurement.timestamp
    
    def estimate_completion(self, 
                          current_windows_processed: int,
                          total_windows: int) -> EstimationResult:
        """
        Estimate completion time using the best available strategy.
        
        Args:
            current_windows_processed: Number of windows already processed
            total_windows: Total number of windows to process
            
        Returns:
            EstimationResult with completion estimate
        """
        if len(self.measurements) < self.min_measurements_for_estimation:
            return EstimationResult(
                estimated_completion_time=None,
                time_remaining_seconds=None,
                confidence_level=0.0,
                processing_rate_windows_per_second=0.0,
                processing_rate_records_per_second=0.0,
                estimation_method="insufficient_data",
                trend_direction="unknown"
            )
        
        # Try all estimation strategies
        estimates = {}
        for strategy_name, strategy_func in self.estimation_strategies.items():
            try:
                estimate = strategy_func(current_windows_processed, total_windows)
                if estimate.time_remaining_seconds is not None:
                    estimates[strategy_name] = estimate
            except Exception as e:
                # Strategy failed, skip it
                continue
        
        if not estimates:
            # No strategies succeeded
            return EstimationResult(
                estimated_completion_time=None,
                time_remaining_seconds=None,
                confidence_level=0.0,
                processing_rate_windows_per_second=0.0,
                processing_rate_records_per_second=0.0,
                estimation_method="estimation_failed",
                trend_direction="unknown"
            )
        
        # Select best estimate based on strategy weights and confidence
        best_estimate = self._select_best_estimate(estimates)
        
        # Update accuracy tracking if we have a previous estimate
        if self.last_estimation and self.last_estimation.estimated_completion_time:
            self._update_accuracy_tracking(self.last_estimation)
        
        self.last_estimation = best_estimate
        return best_estimate
    
    def _estimate_simple_average(self, current_windows: int, total_windows: int) -> EstimationResult:
        """Simple average of recent processing rates"""
        recent_measurements = list(self.measurements)[-self.trend_analysis_window:]
        
        # Calculate average processing rate
        total_windows_in_measurements = sum(m.windows_processed for m in recent_measurements)
        total_time = sum(m.processing_time_seconds for m in recent_measurements)
        
        if total_time <= 0:
            raise ValueError("No processing time recorded")
        
        windows_per_second = total_windows_in_measurements / total_time
        remaining_windows = total_windows - current_windows
        time_remaining = remaining_windows / windows_per_second if windows_per_second > 0 else None
        
        # Calculate records per second
        total_records = sum(m.records_processed for m in recent_measurements)
        records_per_second = total_records / total_time
        
        # Determine trend
        trend = self._analyze_trend(recent_measurements)
        
        return EstimationResult(
            estimated_completion_time=datetime.now() + timedelta(seconds=time_remaining) if time_remaining else None,
            time_remaining_seconds=time_remaining,
            confidence_level=min(0.8, len(recent_measurements) / self.trend_analysis_window),
            processing_rate_windows_per_second=windows_per_second,
            processing_rate_records_per_second=records_per_second,
            estimation_method="simple_average",
            trend_direction=trend
        )
    
    def _estimate_weighted_average(self, current_windows: int, total_windows: int) -> EstimationResult:
        """Weighted average giving more weight to recent measurements"""
        recent_measurements = list(self.measurements)[-self.trend_analysis_window:]
        
        if not recent_measurements:
            raise ValueError("No measurements available")
        
        # Create weights (more recent = higher weight)
        weights = [i + 1 for i in range(len(recent_measurements))]
        total_weight = sum(weights)
        
        # Calculate weighted averages
        weighted_windows_per_second = 0
        weighted_records_per_second = 0
        
        for measurement, weight in zip(recent_measurements, weights):
            if measurement.processing_time_seconds > 0:
                windows_per_sec = measurement.windows_processed / measurement.processing_time_seconds
                records_per_sec = measurement.records_processed / measurement.processing_time_seconds
                
                weighted_windows_per_second += (windows_per_sec * weight) / total_weight
                weighted_records_per_second += (records_per_sec * weight) / total_weight
        
        remaining_windows = total_windows - current_windows
        time_remaining = remaining_windows / weighted_windows_per_second if weighted_windows_per_second > 0 else None
        
        trend = self._analyze_trend(recent_measurements)
        
        return EstimationResult(
            estimated_completion_time=datetime.now() + timedelta(seconds=time_remaining) if time_remaining else None,
            time_remaining_seconds=time_remaining,
            confidence_level=min(0.9, len(recent_measurements) / self.trend_analysis_window),
            processing_rate_windows_per_second=weighted_windows_per_second,
            processing_rate_records_per_second=weighted_records_per_second,
            estimation_method="weighted_average",
            trend_direction=trend
        )
    
    def _estimate_linear_regression(self, current_windows: int, total_windows: int) -> EstimationResult:
        """Linear regression on processing rate over time"""
        if len(self.measurements) < 10:  # Need more data for regression
            raise ValueError("Insufficient data for regression")
        
        recent_measurements = list(self.measurements)[-self.trend_analysis_window:]
        
        # Prepare data for regression (time vs cumulative windows)
        start_time = recent_measurements[0].timestamp
        x_values = []  # Time in seconds from start
        y_values = []  # Cumulative windows processed
        
        cumulative_windows = 0
        for measurement in recent_measurements:
            time_offset = (measurement.timestamp - start_time).total_seconds()
            cumulative_windows += measurement.windows_processed
            x_values.append(time_offset)
            y_values.append(cumulative_windows)
        
        # Simple linear regression
        n = len(x_values)
        sum_x = sum(x_values)
        sum_y = sum(y_values)
        sum_xy = sum(x * y for x, y in zip(x_values, y_values))
        sum_x2 = sum(x * x for x in x_values)
        
        # Calculate slope (windows per second)
        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            raise ValueError("Cannot calculate regression slope")
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        if slope <= 0:
            raise ValueError("Negative or zero processing rate")
        
        remaining_windows = total_windows - current_windows
        time_remaining = remaining_windows / slope
        
        # Calculate records per second (approximate)
        total_records = sum(m.records_processed for m in recent_measurements)
        total_time = sum(m.processing_time_seconds for m in recent_measurements)
        records_per_second = total_records / total_time if total_time > 0 else 0
        
        trend = self._analyze_trend(recent_measurements)
        
        return EstimationResult(
            estimated_completion_time=datetime.now() + timedelta(seconds=time_remaining),
            time_remaining_seconds=time_remaining,
            confidence_level=min(0.85, len(recent_measurements) / self.trend_analysis_window),
            processing_rate_windows_per_second=slope,
            processing_rate_records_per_second=records_per_second,
            estimation_method="linear_regression",
            trend_direction=trend
        )
    
    def _estimate_exponential_smoothing(self, current_windows: int, total_windows: int) -> EstimationResult:
        """Exponential smoothing for processing rate estimation"""
        alpha = 0.3  # Smoothing factor
        
        recent_measurements = list(self.measurements)[-self.trend_analysis_window:]
        
        if not recent_measurements:
            raise ValueError("No measurements available")
        
        # Initialize with first measurement
        first_measurement = recent_measurements[0]
        if first_measurement.processing_time_seconds <= 0:
            raise ValueError("Invalid first measurement")
        
        smoothed_rate = first_measurement.windows_processed / first_measurement.processing_time_seconds
        
        # Apply exponential smoothing
        for measurement in recent_measurements[1:]:
            if measurement.processing_time_seconds > 0:
                current_rate = measurement.windows_processed / measurement.processing_time_seconds
                smoothed_rate = alpha * current_rate + (1 - alpha) * smoothed_rate
        
        remaining_windows = total_windows - current_windows
        time_remaining = remaining_windows / smoothed_rate if smoothed_rate > 0 else None
        
        # Calculate records per second
        total_records = sum(m.records_processed for m in recent_measurements)
        total_time = sum(m.processing_time_seconds for m in recent_measurements)
        records_per_second = total_records / total_time if total_time > 0 else 0
        
        trend = self._analyze_trend(recent_measurements)
        
        return EstimationResult(
            estimated_completion_time=datetime.now() + timedelta(seconds=time_remaining) if time_remaining else None,
            time_remaining_seconds=time_remaining,
            confidence_level=min(0.9, len(recent_measurements) / self.trend_analysis_window),
            processing_rate_windows_per_second=smoothed_rate,
            processing_rate_records_per_second=records_per_second,
            estimation_method="exponential_smoothing",
            trend_direction=trend
        )
    
    def _estimate_trend_adjusted(self, current_windows: int, total_windows: int) -> EstimationResult:
        """Trend-adjusted estimation that accounts for performance changes"""
        recent_measurements = list(self.measurements)[-self.trend_analysis_window:]
        
        if len(recent_measurements) < 5:
            raise ValueError("Insufficient data for trend analysis")
        
        # Calculate processing rates for each measurement
        rates = []
        for measurement in recent_measurements:
            if measurement.processing_time_seconds > 0:
                rate = measurement.windows_processed / measurement.processing_time_seconds
                rates.append(rate)
        
        if not rates:
            raise ValueError("No valid processing rates")
        
        # Analyze trend
        if len(rates) >= 3:
            # Calculate trend slope
            x_values = list(range(len(rates)))
            n = len(rates)
            sum_x = sum(x_values)
            sum_y = sum(rates)
            sum_xy = sum(x * y for x, y in zip(x_values, rates))
            sum_x2 = sum(x * x for x in x_values)
            
            denominator = n * sum_x2 - sum_x * sum_x
            if denominator != 0:
                trend_slope = (n * sum_xy - sum_x * sum_y) / denominator
            else:
                trend_slope = 0
        else:
            trend_slope = 0
        
        # Current rate (recent average)
        current_rate = statistics.mean(rates[-3:])  # Last 3 measurements
        
        # Project future rate based on trend
        remaining_windows = total_windows - current_windows
        
        # Estimate how many more measurements we'll have
        avg_windows_per_measurement = statistics.mean([m.windows_processed for m in recent_measurements])
        estimated_future_measurements = remaining_windows / avg_windows_per_measurement if avg_windows_per_measurement > 0 else 1
        
        # Adjust rate based on trend
        future_rate = current_rate + (trend_slope * estimated_future_measurements)
        future_rate = max(future_rate, current_rate * 0.1)  # Don't let it go too low
        
        # Use average of current and projected rate
        adjusted_rate = (current_rate + future_rate) / 2
        
        time_remaining = remaining_windows / adjusted_rate if adjusted_rate > 0 else None
        
        # Calculate records per second
        total_records = sum(m.records_processed for m in recent_measurements)
        total_time = sum(m.processing_time_seconds for m in recent_measurements)
        records_per_second = total_records / total_time if total_time > 0 else 0
        
        # Determine trend direction
        if abs(trend_slope) < 0.01:
            trend_direction = "stable"
        elif trend_slope > 0:
            trend_direction = "improving"
        else:
            trend_direction = "degrading"
        
        return EstimationResult(
            estimated_completion_time=datetime.now() + timedelta(seconds=time_remaining) if time_remaining else None,
            time_remaining_seconds=time_remaining,
            confidence_level=min(0.95, len(recent_measurements) / self.trend_analysis_window),
            processing_rate_windows_per_second=adjusted_rate,
            processing_rate_records_per_second=records_per_second,
            estimation_method="trend_adjusted",
            trend_direction=trend_direction
        )
    
    def _analyze_trend(self, measurements: List[ProcessingMeasurement]) -> str:
        """
        Analyze processing trend from measurements.
        
        Args:
            measurements: List of recent measurements
            
        Returns:
            Trend direction: "improving", "stable", or "degrading"
        """
        if len(measurements) < 3:
            return "unknown"
        
        # Calculate processing rates
        rates = []
        for measurement in measurements:
            if measurement.processing_time_seconds > 0:
                rate = measurement.windows_processed / measurement.processing_time_seconds
                rates.append(rate)
        
        if len(rates) < 3:
            return "unknown"
        
        # Compare first half to second half
        mid_point = len(rates) // 2
        first_half_avg = statistics.mean(rates[:mid_point])
        second_half_avg = statistics.mean(rates[mid_point:])
        
        # Calculate percentage change
        if first_half_avg > 0:
            change_percent = ((second_half_avg - first_half_avg) / first_half_avg) * 100
            
            if change_percent > 5:
                return "improving"
            elif change_percent < -5:
                return "degrading"
            else:
                return "stable"
        
        return "unknown"
    
    def _select_best_estimate(self, estimates: Dict[str, EstimationResult]) -> EstimationResult:
        """
        Select the best estimate from multiple strategies.
        
        Args:
            estimates: Dictionary of strategy name to EstimationResult
            
        Returns:
            Best EstimationResult
        """
        if len(estimates) == 1:
            return list(estimates.values())[0]
        
        # Score each estimate based on confidence and strategy weight
        scored_estimates = []
        
        for strategy_name, estimate in estimates.items():
            strategy_weight = self.strategy_weights.get(strategy_name, 1.0)
            
            # Calculate composite score
            score = estimate.confidence_level * strategy_weight
            
            # Bonus for trend-aware strategies
            if estimate.trend_direction != "unknown":
                score *= 1.1
            
            scored_estimates.append((score, strategy_name, estimate))
        
        # Sort by score (highest first)
        scored_estimates.sort(key=lambda x: x[0], reverse=True)
        
        # Return best estimate
        return scored_estimates[0][2]
    
    def _update_accuracy_tracking(self, previous_estimate: EstimationResult):
        """
        Update accuracy tracking based on how well previous estimates performed.
        
        Args:
            previous_estimate: Previous estimation result to evaluate
        """
        # This would be implemented to track how accurate our estimates are
        # and adjust strategy weights accordingly
        # For now, we'll keep the basic implementation
        pass
    
    def get_performance_statistics(self) -> Dict[str, Any]:
        """
        Get performance statistics for the estimation system.
        
        Returns:
            Dictionary containing performance metrics
        """
        if not self.measurements:
            return {}
        
        recent_measurements = list(self.measurements)[-self.trend_analysis_window:]
        
        # Calculate various statistics
        processing_times = [m.processing_time_seconds for m in recent_measurements if m.processing_time_seconds > 0]
        windows_per_measurement = [m.windows_processed for m in recent_measurements]
        records_per_measurement = [m.records_processed for m in recent_measurements]
        
        stats = {
            'total_measurements': len(self.measurements),
            'recent_measurements': len(recent_measurements),
            'avg_processing_time_per_measurement': statistics.mean(processing_times) if processing_times else 0,
            'avg_windows_per_measurement': statistics.mean(windows_per_measurement) if windows_per_measurement else 0,
            'avg_records_per_measurement': statistics.mean(records_per_measurement) if records_per_measurement else 0,
            'trend_direction': self._analyze_trend(recent_measurements),
            'estimation_strategies_available': list(self.estimation_strategies.keys()),
            'strategy_weights': self.strategy_weights.copy()
        }
        
        # Add memory statistics if available
        memory_usages = [m.memory_usage_mb for m in recent_measurements if m.memory_usage_mb is not None]
        if memory_usages:
            stats.update({
                'avg_memory_usage_mb': statistics.mean(memory_usages),
                'max_memory_usage_mb': max(memory_usages),
                'min_memory_usage_mb': min(memory_usages)
            })
        
        return stats