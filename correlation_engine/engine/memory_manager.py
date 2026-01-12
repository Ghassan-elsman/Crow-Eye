"""
Memory Management for Time-Window Scanning Engine

Provides memory tracking, limit checking, and optimization suggestions
for processing large time windows efficiently.
"""

import psutil
import gc
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MemoryUsageReport:
    """Report of current memory usage and recommendations."""
    current_memory_mb: float
    peak_memory_mb: float
    available_memory_mb: float
    memory_limit_mb: float
    usage_percentage: float
    is_over_limit: bool
    recommendations: List[str]
    timestamp: datetime


@dataclass
class WindowMemoryStats:
    """Memory statistics for a specific time window."""
    window_id: str
    estimated_records: int
    estimated_memory_mb: float
    actual_memory_mb: Optional[float] = None
    processing_time_seconds: Optional[float] = None
    memory_efficiency: Optional[float] = None  # MB per 1000 records


class WindowMemoryManager:
    """
    Manages memory usage during time-window processing.
    
    Features:
    - Tracks memory usage per window
    - Enforces memory limits with graceful degradation
    - Provides optimization suggestions
    - Monitors memory efficiency trends
    - Supports streaming mode activation
    """
    
    # Memory estimation constants
    BYTES_PER_RECORD_BASE = 1024  # Base memory per record (1KB)
    BYTES_PER_FIELD = 64  # Additional memory per field
    OVERHEAD_MULTIPLIER = 1.5  # Overhead for Python objects and processing
    
    def __init__(self, max_memory_mb: int = 500, enable_gc: bool = True):
        """
        Initialize memory manager.
        
        Args:
            max_memory_mb: Maximum memory limit in MB
            enable_gc: Enable automatic garbage collection
        """
        self.max_memory_mb = max_memory_mb
        self.enable_gc = enable_gc
        
        # Memory tracking
        self.baseline_memory_mb = self._get_current_memory_usage()
        self.peak_memory_mb = self.baseline_memory_mb
        self.window_stats: Dict[str, WindowMemoryStats] = {}
        
        # Performance tracking
        self.total_windows_processed = 0
        self.total_records_processed = 0
        self.memory_warnings_issued = 0
        self.streaming_mode_activations = 0
        
        # Efficiency tracking
        self.efficiency_history: List[float] = []
        self.processing_time_history: List[float] = []
    
    def can_process_window(self, window_id: str, estimated_records: int, 
                          estimated_fields_per_record: int = 10) -> Tuple[bool, str]:
        """
        Check if a window can be processed within memory limits.
        
        Args:
            window_id: Unique identifier for the window
            estimated_records: Estimated number of records in window
            estimated_fields_per_record: Estimated fields per record
            
        Returns:
            Tuple of (can_process, reason)
        """
        # Estimate memory requirements
        estimated_memory_mb = self._estimate_window_memory(
            estimated_records, estimated_fields_per_record
        )
        
        # Get current memory usage
        current_memory_mb = self._get_current_memory_usage()
        
        # Calculate projected memory usage
        projected_memory_mb = current_memory_mb + estimated_memory_mb
        
        # Store window stats
        self.window_stats[window_id] = WindowMemoryStats(
            window_id=window_id,
            estimated_records=estimated_records,
            estimated_memory_mb=estimated_memory_mb
        )
        
        # Check against limit
        if projected_memory_mb > self.max_memory_mb:
            reason = (f"Projected memory usage ({projected_memory_mb:.1f}MB) "
                     f"exceeds limit ({self.max_memory_mb}MB)")
            return False, reason
        
        # Check system memory availability
        available_memory_mb = self._get_available_system_memory()
        if projected_memory_mb > available_memory_mb * 0.8:  # Leave 20% buffer
            reason = (f"Projected memory usage ({projected_memory_mb:.1f}MB) "
                     f"exceeds available system memory ({available_memory_mb:.1f}MB)")
            return False, reason
        
        return True, "Memory check passed"
    
    def start_window_processing(self, window_id: str) -> float:
        """
        Start processing a window and return baseline memory.
        
        Args:
            window_id: Window identifier
            
        Returns:
            Baseline memory usage in MB
        """
        if self.enable_gc:
            gc.collect()  # Clean up before processing
        
        baseline = self._get_current_memory_usage()
        
        if window_id in self.window_stats:
            self.window_stats[window_id].actual_memory_mb = baseline
        
        return baseline
    
    def finish_window_processing(self, window_id: str, baseline_memory_mb: float, 
                                records_processed: int) -> WindowMemoryStats:
        """
        Finish processing a window and update statistics.
        
        Args:
            window_id: Window identifier
            baseline_memory_mb: Memory usage at start of processing
            records_processed: Actual number of records processed
            
        Returns:
            Updated WindowMemoryStats
        """
        # Calculate actual memory usage
        current_memory_mb = self._get_current_memory_usage()
        actual_memory_used = current_memory_mb - baseline_memory_mb
        
        # Update window stats
        if window_id in self.window_stats:
            stats = self.window_stats[window_id]
            stats.actual_memory_mb = actual_memory_used
            
            # Calculate efficiency (MB per 1000 records)
            if records_processed > 0:
                stats.memory_efficiency = (actual_memory_used / records_processed) * 1000
                self.efficiency_history.append(stats.memory_efficiency)
                
                # Keep only recent history
                if len(self.efficiency_history) > 100:
                    self.efficiency_history = self.efficiency_history[-100:]
        
        # Update global stats
        self.total_windows_processed += 1
        self.total_records_processed += records_processed
        self.peak_memory_mb = max(self.peak_memory_mb, current_memory_mb)
        
        # Cleanup if enabled
        if self.enable_gc:
            gc.collect()
        
        return self.window_stats.get(window_id)
    
    def check_memory_pressure(self) -> MemoryUsageReport:
        """
        Check current memory pressure and generate recommendations.
        
        Returns:
            MemoryUsageReport with current status and recommendations
        """
        current_memory_mb = self._get_current_memory_usage()
        available_memory_mb = self._get_available_system_memory()
        usage_percentage = (current_memory_mb / self.max_memory_mb) * 100
        is_over_limit = current_memory_mb > self.max_memory_mb
        
        # Generate recommendations
        recommendations = []
        
        if usage_percentage > 90:
            recommendations.append("CRITICAL: Memory usage above 90% - enable streaming mode")
            self.memory_warnings_issued += 1
        elif usage_percentage > 75:
            recommendations.append("WARNING: Memory usage above 75% - consider reducing window size")
            self.memory_warnings_issued += 1
        elif usage_percentage > 50:
            recommendations.append("INFO: Memory usage above 50% - monitor closely")
        
        if available_memory_mb < 1000:  # Less than 1GB available
            recommendations.append("SYSTEM: Low system memory - consider closing other applications")
        
        # Performance recommendations
        if len(self.efficiency_history) > 10:
            avg_efficiency = sum(self.efficiency_history[-10:]) / 10
            if avg_efficiency > 5.0:  # More than 5MB per 1000 records
                recommendations.append("PERFORMANCE: High memory per record - check for memory leaks")
        
        return MemoryUsageReport(
            current_memory_mb=current_memory_mb,
            peak_memory_mb=self.peak_memory_mb,
            available_memory_mb=available_memory_mb,
            memory_limit_mb=self.max_memory_mb,
            usage_percentage=usage_percentage,
            is_over_limit=is_over_limit,
            recommendations=recommendations,
            timestamp=datetime.now()
        )
    
    def should_enable_streaming_mode(self) -> Tuple[bool, str]:
        """
        Determine if streaming mode should be enabled.
        
        Returns:
            Tuple of (should_enable, reason)
        """
        report = self.check_memory_pressure()
        
        # Enable streaming if over memory limit
        if report.is_over_limit:
            return True, f"Memory usage ({report.current_memory_mb:.1f}MB) exceeds limit"
        
        # Enable streaming if usage is very high
        if report.usage_percentage > 85:
            return True, f"Memory usage is {report.usage_percentage:.1f}% of limit"
        
        # Enable streaming if system memory is low
        if report.available_memory_mb < 500:  # Less than 500MB available
            return True, f"Low system memory available ({report.available_memory_mb:.1f}MB)"
        
        # Enable streaming if efficiency is poor
        if len(self.efficiency_history) > 5:
            recent_efficiency = sum(self.efficiency_history[-5:]) / 5
            if recent_efficiency > 10.0:  # More than 10MB per 1000 records
                return True, f"Poor memory efficiency ({recent_efficiency:.1f}MB/1000 records)"
        
        return False, "Memory usage within acceptable limits"
    
    def get_optimization_suggestions(self) -> List[str]:
        """
        Get optimization suggestions based on processing history.
        
        Returns:
            List of optimization suggestions
        """
        suggestions = []
        
        # Analyze efficiency trends
        if len(self.efficiency_history) > 20:
            recent_avg = sum(self.efficiency_history[-10:]) / 10
            historical_avg = sum(self.efficiency_history[-20:-10]) / 10
            
            if recent_avg > historical_avg * 1.5:
                suggestions.append("Memory efficiency is degrading - consider restarting the process")
        
        # Analyze processing patterns
        if self.total_windows_processed > 100:
            avg_records_per_window = self.total_records_processed / self.total_windows_processed
            
            if avg_records_per_window > 1000:
                suggestions.append("Large windows detected - consider reducing time window size")
            elif avg_records_per_window < 10:
                suggestions.append("Small windows detected - consider increasing time window size")
        
        # Memory limit suggestions
        if self.memory_warnings_issued > 10:
            suggestions.append("Frequent memory warnings - consider increasing memory limit")
        
        if self.streaming_mode_activations > 5:
            suggestions.append("Frequent streaming mode activation - increase memory limit or reduce window size")
        
        return suggestions
    
    def get_memory_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive memory statistics.
        
        Returns:
            Dictionary with memory statistics
        """
        current_memory_mb = self._get_current_memory_usage()
        
        stats = {
            'current_memory_mb': current_memory_mb,
            'baseline_memory_mb': self.baseline_memory_mb,
            'peak_memory_mb': self.peak_memory_mb,
            'memory_limit_mb': self.max_memory_mb,
            'usage_percentage': (current_memory_mb / self.max_memory_mb) * 100,
            'total_windows_processed': self.total_windows_processed,
            'total_records_processed': self.total_records_processed,
            'memory_warnings_issued': self.memory_warnings_issued,
            'streaming_mode_activations': self.streaming_mode_activations
        }
        
        # Add efficiency statistics
        if self.efficiency_history:
            stats['average_efficiency_mb_per_1k_records'] = sum(self.efficiency_history) / len(self.efficiency_history)
            stats['recent_efficiency_mb_per_1k_records'] = sum(self.efficiency_history[-10:]) / min(10, len(self.efficiency_history))
            stats['efficiency_trend'] = self._calculate_efficiency_trend()
        
        return stats
    
    def reset_statistics(self):
        """Reset all statistics and history."""
        self.window_stats.clear()
        self.efficiency_history.clear()
        self.processing_time_history.clear()
        self.total_windows_processed = 0
        self.total_records_processed = 0
        self.memory_warnings_issued = 0
        self.streaming_mode_activations = 0
        self.baseline_memory_mb = self._get_current_memory_usage()
        self.peak_memory_mb = self.baseline_memory_mb
    
    def _estimate_window_memory(self, estimated_records: int, 
                               estimated_fields_per_record: int) -> float:
        """
        Estimate memory requirements for a window.
        
        Args:
            estimated_records: Number of records
            estimated_fields_per_record: Fields per record
            
        Returns:
            Estimated memory in MB
        """
        # Base memory per record
        base_memory = estimated_records * self.BYTES_PER_RECORD_BASE
        
        # Additional memory for fields
        field_memory = estimated_records * estimated_fields_per_record * self.BYTES_PER_FIELD
        
        # Total memory with overhead
        total_bytes = (base_memory + field_memory) * self.OVERHEAD_MULTIPLIER
        
        # Convert to MB
        return total_bytes / (1024 * 1024)
    
    def _get_current_memory_usage(self) -> float:
        """Get current process memory usage in MB."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            return memory_info.rss / (1024 * 1024)  # Convert bytes to MB
        except Exception:
            # Fallback if psutil is not available
            return 0.0
    
    def _get_available_system_memory(self) -> float:
        """Get available system memory in MB."""
        try:
            memory = psutil.virtual_memory()
            return memory.available / (1024 * 1024)  # Convert bytes to MB
        except Exception:
            # Fallback if psutil is not available
            return 4096.0  # Assume 4GB available
    
    def _calculate_efficiency_trend(self) -> str:
        """Calculate efficiency trend from history."""
        if len(self.efficiency_history) < 10:
            return "insufficient_data"
        
        # Compare recent vs historical efficiency
        recent = sum(self.efficiency_history[-5:]) / 5
        historical = sum(self.efficiency_history[-15:-5]) / 10
        
        if recent > historical * 1.2:
            return "degrading"
        elif recent < historical * 0.8:
            return "improving"
        else:
            return "stable"
    
    def force_garbage_collection(self) -> int:
        """Force garbage collection to free memory (silently)."""
        if self.enable_gc:
            collected = gc.collect()
            return collected
        return 0
    
    def activate_streaming_mode(self, reason: str):
        """Record streaming mode activation."""
        self.streaming_mode_activations += 1