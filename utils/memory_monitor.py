"""
Memory Monitor for Crow Eye
Tracks memory usage and provides optimization recommendations.
"""

import psutil
import logging
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MemorySnapshot:
    """Snapshot of memory usage at a point in time."""
    timestamp: datetime
    total_mb: float
    available_mb: float
    used_mb: float
    percent_used: float
    process_mb: float


class MemoryMonitor:
    """
    Monitors system and process memory usage.
    Provides warnings and optimization recommendations.
    """
    
    # Memory thresholds
    WARNING_THRESHOLD = 80.0  # Warn at 80% memory usage
    CRITICAL_THRESHOLD = 90.0  # Critical at 90% memory usage
    
    def __init__(self, warning_callback: Optional[Callable[[str], None]] = None):
        """
        Initialize memory monitor.
        
        Args:
            warning_callback: Optional callback for memory warnings
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.warning_callback = warning_callback
        self.process = psutil.Process()
        self.snapshots = []
        self.max_snapshots = 100  # Keep last 100 snapshots
    
    def get_current_usage(self) -> MemorySnapshot:
        """
        Get current memory usage snapshot.
        
        Returns:
            MemorySnapshot with current memory statistics
        """
        # Get system memory
        mem = psutil.virtual_memory()
        
        # Get process memory
        process_mem = self.process.memory_info()
        
        snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            total_mb=mem.total / (1024 * 1024),
            available_mb=mem.available / (1024 * 1024),
            used_mb=mem.used / (1024 * 1024),
            percent_used=mem.percent,
            process_mb=process_mem.rss / (1024 * 1024)
        )
        
        # Store snapshot
        self.snapshots.append(snapshot)
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots.pop(0)
        
        # Check thresholds
        self._check_thresholds(snapshot)
        
        return snapshot
    
    def _check_thresholds(self, snapshot: MemorySnapshot) -> None:
        """
        Check if memory usage exceeds thresholds and trigger warnings.
        
        Args:
            snapshot: Current memory snapshot
        """
        if snapshot.percent_used >= self.CRITICAL_THRESHOLD:
            message = (
                f"CRITICAL: Memory usage at {snapshot.percent_used:.1f}% "
                f"({snapshot.used_mb:.0f} MB / {snapshot.total_mb:.0f} MB). "
                f"Consider reducing buffer sizes or closing other applications."
            )
            self.logger.critical(message)
            if self.warning_callback:
                self.warning_callback(message)
        
        elif snapshot.percent_used >= self.WARNING_THRESHOLD:
            message = (
                f"WARNING: Memory usage at {snapshot.percent_used:.1f}% "
                f"({snapshot.used_mb:.0f} MB / {snapshot.total_mb:.0f} MB). "
                f"Performance may be affected."
            )
            self.logger.warning(message)
            if self.warning_callback:
                self.warning_callback(message)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive memory statistics.
        
        Returns:
            Dictionary with memory statistics
        """
        current = self.get_current_usage()
        
        stats = {
            'current': {
                'total_mb': current.total_mb,
                'available_mb': current.available_mb,
                'used_mb': current.used_mb,
                'percent_used': current.percent_used,
                'process_mb': current.process_mb
            },
            'thresholds': {
                'warning_percent': self.WARNING_THRESHOLD,
                'critical_percent': self.CRITICAL_THRESHOLD,
                'warning_mb': (self.WARNING_THRESHOLD / 100) * current.total_mb,
                'critical_mb': (self.CRITICAL_THRESHOLD / 100) * current.total_mb
            },
            'status': self._get_status(current.percent_used)
        }
        
        # Add historical data if available
        if len(self.snapshots) > 1:
            stats['history'] = {
                'min_percent': min(s.percent_used for s in self.snapshots),
                'max_percent': max(s.percent_used for s in self.snapshots),
                'avg_percent': sum(s.percent_used for s in self.snapshots) / len(self.snapshots),
                'min_process_mb': min(s.process_mb for s in self.snapshots),
                'max_process_mb': max(s.process_mb for s in self.snapshots),
                'avg_process_mb': sum(s.process_mb for s in self.snapshots) / len(self.snapshots)
            }
        
        return stats
    
    def _get_status(self, percent_used: float) -> str:
        """
        Get memory status based on usage percentage.
        
        Args:
            percent_used: Memory usage percentage
            
        Returns:
            Status string ('ok', 'warning', 'critical')
        """
        if percent_used >= self.CRITICAL_THRESHOLD:
            return 'critical'
        elif percent_used >= self.WARNING_THRESHOLD:
            return 'warning'
        else:
            return 'ok'
    
    def should_reduce_buffer(self) -> bool:
        """
        Check if buffer sizes should be reduced due to memory pressure.
        
        Returns:
            True if buffers should be reduced, False otherwise
        """
        current = self.get_current_usage()
        return current.percent_used >= self.WARNING_THRESHOLD
    
    def get_recommended_buffer_size(self, current_buffer: int, max_rows: int) -> int:
        """
        Get recommended buffer size based on current memory usage.
        
        Args:
            current_buffer: Current buffer size
            max_rows: Maximum allowed rows
            
        Returns:
            Recommended buffer size
        """
        current = self.get_current_usage()
        
        if current.percent_used >= self.CRITICAL_THRESHOLD:
            # Reduce to 25% of current
            return max(500, min(current_buffer // 4, max_rows))
        elif current.percent_used >= self.WARNING_THRESHOLD:
            # Reduce to 50% of current
            return max(1000, min(current_buffer // 2, max_rows))
        else:
            # No reduction needed
            return current_buffer
    
    def log_memory_usage(self, context: str = "") -> None:
        """
        Log current memory usage with optional context.
        
        Args:
            context: Optional context string for the log message
        """
        current = self.get_current_usage()
        
        context_str = f" [{context}]" if context else ""
        self.logger.info(
            f"Memory Usage{context_str}: "
            f"System: {current.percent_used:.1f}% "
            f"({current.used_mb:.0f}/{current.total_mb:.0f} MB), "
            f"Process: {current.process_mb:.0f} MB"
        )
    
    def get_optimization_recommendations(self) -> list:
        """
        Get memory optimization recommendations based on current usage.
        
        Returns:
            List of recommendation strings
        """
        current = self.get_current_usage()
        recommendations = []
        
        if current.percent_used >= self.CRITICAL_THRESHOLD:
            recommendations.append(
                "Critical memory usage detected. Immediate actions recommended:"
            )
            recommendations.append("- Reduce page size to 500-1000 rows")
            recommendations.append("- Reduce buffer size to 1000-2000 rows")
            recommendations.append("- Close other applications")
            recommendations.append("- Consider upgrading system RAM")
        
        elif current.percent_used >= self.WARNING_THRESHOLD:
            recommendations.append(
                "High memory usage detected. Consider these optimizations:"
            )
            recommendations.append("- Reduce page size to 1000-2000 rows")
            recommendations.append("- Reduce buffer size to 2000-5000 rows")
            recommendations.append("- Close unnecessary browser tabs or applications")
        
        else:
            recommendations.append("Memory usage is within normal range.")
            
            # Check process memory
            if current.process_mb > 500:
                recommendations.append(
                    f"Process using {current.process_mb:.0f} MB. "
                    "Consider clearing cached data if performance degrades."
                )
        
        return recommendations
    
    def clear_snapshots(self) -> None:
        """Clear stored memory snapshots."""
        self.snapshots.clear()
        self.logger.debug("Cleared memory snapshots")


class VirtualTableMemoryManager:
    """
    Memory manager specifically for virtual table widgets.
    Manages row caching and buffer sizes based on memory availability.
    """
    
    def __init__(
        self,
        monitor: MemoryMonitor,
        initial_buffer_size: int = 2000,
        max_memory_rows: int = 50000
    ):
        """
        Initialize virtual table memory manager.
        
        Args:
            monitor: MemoryMonitor instance
            initial_buffer_size: Initial buffer size
            max_memory_rows: Maximum rows to keep in memory
        """
        self.monitor = monitor
        self.buffer_size = initial_buffer_size
        self.max_memory_rows = max_memory_rows
        self.cached_rows = 0
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def update_buffer_size(self) -> int:
        """
        Update buffer size based on current memory usage.
        
        Returns:
            New buffer size
        """
        if self.monitor.should_reduce_buffer():
            new_size = self.monitor.get_recommended_buffer_size(
                self.buffer_size,
                self.max_memory_rows
            )
            
            if new_size != self.buffer_size:
                self.logger.info(
                    f"Adjusting buffer size: {self.buffer_size} -> {new_size} "
                    f"(memory at {self.monitor.get_current_usage().percent_used:.1f}%)"
                )
                self.buffer_size = new_size
        
        return self.buffer_size
    
    def can_cache_more_rows(self, additional_rows: int) -> bool:
        """
        Check if more rows can be cached without exceeding limits.
        
        Args:
            additional_rows: Number of additional rows to cache
            
        Returns:
            True if rows can be cached, False otherwise
        """
        # Check row limit
        if self.cached_rows + additional_rows > self.max_memory_rows:
            return False
        
        # Check memory usage
        if self.monitor.should_reduce_buffer():
            return False
        
        return True
    
    def register_cached_rows(self, count: int) -> None:
        """
        Register that rows have been cached.
        
        Args:
            count: Number of rows cached
        """
        self.cached_rows += count
        
        if self.cached_rows > self.max_memory_rows:
            self.logger.warning(
                f"Cached rows ({self.cached_rows}) exceeds maximum ({self.max_memory_rows})"
            )
    
    def release_cached_rows(self, count: int) -> None:
        """
        Register that rows have been released from cache.
        
        Args:
            count: Number of rows released
        """
        self.cached_rows = max(0, self.cached_rows - count)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        return {
            'cached_rows': self.cached_rows,
            'max_memory_rows': self.max_memory_rows,
            'buffer_size': self.buffer_size,
            'utilization_percent': (self.cached_rows / self.max_memory_rows) * 100,
            'memory_status': self.monitor._get_status(
                self.monitor.get_current_usage().percent_used
            )
        }
    
    def clear_cache(self) -> None:
        """Clear the cache."""
        self.cached_rows = 0
        self.logger.info("Cleared row cache")
