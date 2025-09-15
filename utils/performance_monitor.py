"""Performance monitoring utilities for Crow Eye."""

import time
import psutil
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging


@dataclass
class PerformanceMetrics:
    """Data class for storing performance metrics."""
    timestamp: datetime
    memory_usage_mb: float
    cpu_percent: float
    operation_name: str
    duration_ms: float
    records_processed: int = 0


class PerformanceMonitor:
    """Monitor and track performance metrics for Crow Eye operations."""
    
    def __init__(self, log_level: int = logging.INFO):
        """Initialize the performance monitor.
        
        Args:
            log_level: Logging level for performance messages
        """
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)
        self.metrics: List[PerformanceMetrics] = []
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        
    def start_monitoring(self, interval: float = 1.0):
        """Start continuous performance monitoring.
        
        Args:
            interval: Monitoring interval in seconds
        """
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
        self.logger.info("Performance monitoring started")
        
    def stop_monitoring(self):
        """Stop continuous performance monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
        self.logger.info("Performance monitoring stopped")
        
    def _monitor_loop(self, interval: float):
        """Continuous monitoring loop."""
        while self._monitoring:
            try:
                self._record_system_metrics()
                time.sleep(interval)
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                
    def _record_system_metrics(self):
        """Record current system metrics."""
        try:
            memory_mb = psutil.virtual_memory().used / (1024 * 1024)
            cpu_percent = psutil.cpu_percent()
            
            metric = PerformanceMetrics(
                timestamp=datetime.now(),
                memory_usage_mb=memory_mb,
                cpu_percent=cpu_percent,
                operation_name="system_monitor",
                duration_ms=0
            )
            
            self.metrics.append(metric)
            
            # Keep only last 1000 metrics to prevent memory growth
            if len(self.metrics) > 1000:
                self.metrics = self.metrics[-1000:]
                
        except Exception as e:
            self.logger.error(f"Error recording system metrics: {e}")
    
    def time_operation(self, operation_name: str, records_count: int = 0):
        """Context manager for timing operations.
        
        Args:
            operation_name: Name of the operation being timed
            records_count: Number of records processed (optional)
            
        Usage:
            with monitor.time_operation("prefetch_parsing", 150):
                # Your operation here
                pass
        """
        return OperationTimer(self, operation_name, records_count)
        
    def record_metric(self, metric: PerformanceMetrics):
        """Record a performance metric.
        
        Args:
            metric: The performance metric to record
        """
        self.metrics.append(metric)
        
        # Log significant operations
        if metric.duration_ms > 1000:  # Operations taking more than 1 second
            self.logger.info(
                f"Operation '{metric.operation_name}' took {metric.duration_ms:.1f}ms "
                f"(Memory: {metric.memory_usage_mb:.1f}MB, CPU: {metric.cpu_percent:.1f}%)"
            )
            
    def get_metrics_summary(self, operation_name: Optional[str] = None) -> Dict[str, Any]:
        """Get a summary of performance metrics.
        
        Args:
            operation_name: Filter metrics by operation name (optional)
            
        Returns:
            Dictionary containing performance summary
        """
        filtered_metrics = self.metrics
        if operation_name:
            filtered_metrics = [m for m in self.metrics if m.operation_name == operation_name]
            
        if not filtered_metrics:
            return {"message": "No metrics available"}
            
        durations = [m.duration_ms for m in filtered_metrics if m.duration_ms > 0]
        memory_usage = [m.memory_usage_mb for m in filtered_metrics]
        cpu_usage = [m.cpu_percent for m in filtered_metrics]
        
        summary = {
            "total_operations": len(filtered_metrics),
            "time_period": {
                "start": min(m.timestamp for m in filtered_metrics).isoformat(),
                "end": max(m.timestamp for m in filtered_metrics).isoformat()
            }
        }
        
        if durations:
            summary["performance"] = {
                "avg_duration_ms": sum(durations) / len(durations),
                "max_duration_ms": max(durations),
                "min_duration_ms": min(durations),
                "total_records_processed": sum(m.records_processed for m in filtered_metrics)
            }
            
        if memory_usage:
            summary["resource_usage"] = {
                "avg_memory_mb": sum(memory_usage) / len(memory_usage),
                "max_memory_mb": max(memory_usage),
                "avg_cpu_percent": sum(cpu_usage) / len(cpu_usage) if cpu_usage else 0,
                "max_cpu_percent": max(cpu_usage) if cpu_usage else 0
            }
            
        return summary
        
    def clear_metrics(self):
        """Clear all stored metrics."""
        self.metrics.clear()
        self.logger.info("Performance metrics cleared")
        
    def export_metrics(self, filepath: str):
        """Export metrics to a JSON file.
        
        Args:
            filepath: Path to save the metrics file
        """
        import json
        
        try:
            metrics_data = []
            for metric in self.metrics:
                metrics_data.append({
                    "timestamp": metric.timestamp.isoformat(),
                    "memory_usage_mb": metric.memory_usage_mb,
                    "cpu_percent": metric.cpu_percent,
                    "operation_name": metric.operation_name,
                    "duration_ms": metric.duration_ms,
                    "records_processed": metric.records_processed
                })
                
            with open(filepath, 'w') as f:
                json.dump(metrics_data, f, indent=2)
                
            self.logger.info(f"Performance metrics exported to {filepath}")
            
        except Exception as e:
            self.logger.error(f"Error exporting metrics: {e}")


class OperationTimer:
    """Context manager for timing operations."""
    
    def __init__(self, monitor: PerformanceMonitor, operation_name: str, records_count: int = 0):
        """Initialize the operation timer.
        
        Args:
            monitor: The performance monitor instance
            operation_name: Name of the operation being timed
            records_count: Number of records being processed
        """
        self.monitor = monitor
        self.operation_name = operation_name
        self.records_count = records_count
        self.start_time = 0
        
    def __enter__(self):
        """Start timing the operation."""
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timing and record the metric."""
        end_time = time.time()
        duration_ms = (end_time - self.start_time) * 1000
        
        try:
            memory_mb = psutil.virtual_memory().used / (1024 * 1024)
            cpu_percent = psutil.cpu_percent()
        except:
            memory_mb = 0
            cpu_percent = 0
            
        metric = PerformanceMetrics(
            timestamp=datetime.now(),
            memory_usage_mb=memory_mb,
            cpu_percent=cpu_percent,
            operation_name=self.operation_name,
            duration_ms=duration_ms,
            records_processed=self.records_count
        )
        
        self.monitor.record_metric(metric)


# Global performance monitor instance
performance_monitor = PerformanceMonitor()


def get_system_info() -> Dict[str, Any]:
    """Get detailed system information for debugging and optimization.
    
    Returns:
        Dictionary containing system information
    """
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "system": {
                "cpu_count": psutil.cpu_count(),
                "cpu_count_logical": psutil.cpu_count(logical=True),
                "memory_total_gb": memory.total / (1024**3),
                "memory_available_gb": memory.available / (1024**3),
                "disk_total_gb": disk.total / (1024**3),
                "disk_free_gb": disk.free / (1024**3),
                "platform": psutil.platform.system()
            },
            "performance_recommendations": _get_performance_recommendations(memory, disk)
        }
    except Exception as e:
        return {"error": f"Could not gather system info: {e}"}


def _get_performance_recommendations(memory, disk) -> List[str]:
    """Generate performance recommendations based on system specs.
    
    Args:
        memory: Memory information from psutil
        disk: Disk information from psutil
        
    Returns:
        List of performance recommendations
    """
    recommendations = []
    
    memory_gb = memory.total / (1024**3)
    available_gb = memory.available / (1024**3)
    disk_free_gb = disk.free / (1024**3)
    
    if memory_gb < 8:
        recommendations.append("Consider upgrading RAM to 8GB+ for better performance with large datasets")
        
    if available_gb < 2:
        recommendations.append("Low available memory detected. Close other applications for better performance")
        
    if disk_free_gb < 10:
        recommendations.append("Low disk space detected. Ensure sufficient space for case files and databases")
        
    if memory_gb >= 16:
        recommendations.append("Excellent memory configuration. Consider enabling high-performance processing modes")
        
    return recommendations