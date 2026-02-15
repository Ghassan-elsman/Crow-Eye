"""
Memory Manager for Non-Streaming Mode

Monitors and manages memory usage during correlation processing in non-streaming mode.
Ensures efficient data structure management and prevents memory leaks.

Requirements: 6.5, 15.2
"""

import logging
import gc
import psutil
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MemoryStatistics:
    """Statistics for memory management"""
    memory_usage_start_mb: float = 0.0
    memory_usage_peak_mb: float = 0.0
    memory_usage_end_mb: float = 0.0
    memory_delta_mb: float = 0.0
    system_memory_percent_start: float = 0.0
    system_memory_percent_peak: float = 0.0
    system_memory_percent_end: float = 0.0
    gc_collections_triggered: int = 0
    memory_warnings_issued: int = 0
    memory_threshold_exceeded_count: int = 0
    data_structures_cleared: int = 0


class MemoryManager:
    """
    Manages memory usage for non-streaming mode correlation processing.
    
    This class provides:
    - Memory usage monitoring during processing
    - Efficient data structure management
    - Memory leak prevention through garbage collection
    - Memory threshold warnings
    - Memory statistics tracking
    
    Requirements: 6.5, 15.2
    Property 10: Memory Management in Non-Streaming Mode
    """
    
    def __init__(self, 
                 memory_threshold_mb: float = 2048.0,
                 warning_threshold_percent: float = 80.0,
                 debug_mode: bool = False):
        """
        Initialize Memory Manager.
        
        Args:
            memory_threshold_mb: Memory usage threshold in MB (default: 2GB)
            warning_threshold_percent: System memory percentage threshold for warnings
            debug_mode: Enable debug logging
        """
        self.memory_threshold_mb = memory_threshold_mb
        self.warning_threshold_percent = warning_threshold_percent
        self.debug_mode = debug_mode
        self.statistics = MemoryStatistics()
        self._lock = threading.Lock()
        self._monitoring_active = False
        self._process = psutil.Process()
        
        if self.debug_mode:
            logger.info(f"[Memory Manager] Initialized with threshold {memory_threshold_mb} MB")
    
    def start_monitoring(self):
        """
        Start memory monitoring.
        
        Records initial memory usage and begins tracking.
        
        Requirements: 6.5, 15.2
        """
        with self._lock:
            self._monitoring_active = True
            
            # Record initial memory usage
            memory_info = self._process.memory_info()
            self.statistics.memory_usage_start_mb = memory_info.rss / 1024 / 1024
            self.statistics.memory_usage_peak_mb = self.statistics.memory_usage_start_mb
            
            # Record system memory percentage
            system_memory = psutil.virtual_memory()
            self.statistics.system_memory_percent_start = system_memory.percent
            self.statistics.system_memory_percent_peak = system_memory.percent
            
            if self.debug_mode:
                logger.info(f"[Memory Manager] Started monitoring - "
                           f"Initial: {self.statistics.memory_usage_start_mb:.2f} MB "
                           f"({self.statistics.system_memory_percent_start:.1f}% system)")
    
    def check_memory_usage(self) -> Dict[str, Any]:
        """
        Check current memory usage and update statistics.
        
        Returns:
            Dictionary with memory status information
            
        Requirements: 6.5, 15.2
        """
        with self._lock:
            if not self._monitoring_active:
                return {'monitoring_active': False}
            
            # Get current memory usage
            memory_info = self._process.memory_info()
            current_mb = memory_info.rss / 1024 / 1024
            
            # Get system memory percentage
            system_memory = psutil.virtual_memory()
            system_percent = system_memory.percent
            
            # Update peak if necessary
            if current_mb > self.statistics.memory_usage_peak_mb:
                self.statistics.memory_usage_peak_mb = current_mb
            
            if system_percent > self.statistics.system_memory_percent_peak:
                self.statistics.system_memory_percent_peak = system_percent
            
            # Check thresholds
            threshold_exceeded = current_mb > self.memory_threshold_mb
            warning_threshold_exceeded = system_percent > self.warning_threshold_percent
            
            if threshold_exceeded:
                self.statistics.memory_threshold_exceeded_count += 1
                logger.warning(f"[Memory Manager] Memory threshold exceeded: "
                             f"{current_mb:.2f} MB > {self.memory_threshold_mb:.2f} MB")
            
            if warning_threshold_exceeded:
                self.statistics.memory_warnings_issued += 1
                logger.warning(f"[Memory Manager] System memory warning: "
                             f"{system_percent:.1f}% > {self.warning_threshold_percent:.1f}%")
            
            status = {
                'monitoring_active': True,
                'current_mb': current_mb,
                'peak_mb': self.statistics.memory_usage_peak_mb,
                'system_percent': system_percent,
                'threshold_exceeded': threshold_exceeded,
                'warning_threshold_exceeded': warning_threshold_exceeded,
                'should_cleanup': threshold_exceeded or warning_threshold_exceeded
            }
            
            if self.debug_mode:
                logger.debug(f"[Memory Manager] Current: {current_mb:.2f} MB "
                           f"({system_percent:.1f}% system), Peak: {self.statistics.memory_usage_peak_mb:.2f} MB")
            
            return status
    
    def cleanup_memory(self, force: bool = False):
        """
        Perform memory cleanup through garbage collection.
        
        Args:
            force: Force garbage collection even if threshold not exceeded
            
        Requirements: 6.5, 15.2
        """
        with self._lock:
            if not self._monitoring_active and not force:
                return
            
            # Determine if cleanup is needed
            should_cleanup = force
            
            if not force and self._monitoring_active:
                # Check if cleanup is needed based on thresholds
                # Get current memory usage without calling check_memory_usage (avoid nested lock)
                memory_info = self._process.memory_info()
                current_mb = memory_info.rss / 1024 / 1024
                system_memory = psutil.virtual_memory()
                system_percent = system_memory.percent
                
                threshold_exceeded = current_mb > self.memory_threshold_mb
                warning_threshold_exceeded = system_percent > self.warning_threshold_percent
                should_cleanup = threshold_exceeded or warning_threshold_exceeded
            
            if should_cleanup:
                if self.debug_mode:
                    logger.info("[Memory Manager] Performing memory cleanup...")
                
                # Force garbage collection
                collected = gc.collect()
                
                self.statistics.gc_collections_triggered += 1
                
                # Check memory after cleanup
                memory_info = self._process.memory_info()
                after_mb = memory_info.rss / 1024 / 1024
                
                if self.debug_mode:
                    logger.info(f"[Memory Manager] Cleanup complete - "
                               f"Collected {collected} objects, "
                               f"Memory: {after_mb:.2f} MB")
    
    def clear_data_structure(self, data_structure_name: str):
        """
        Record that a data structure was cleared.
        
        Args:
            data_structure_name: Name of the data structure cleared
            
        Requirements: 6.5, 15.2
        """
        with self._lock:
            self.statistics.data_structures_cleared += 1
            
            if self.debug_mode:
                logger.debug(f"[Memory Manager] Cleared data structure: {data_structure_name}")
    
    def stop_monitoring(self):
        """
        Stop memory monitoring and record final statistics.
        
        Requirements: 6.5, 15.2
        """
        with self._lock:
            if not self._monitoring_active:
                return
            
            # Record final memory usage
            memory_info = self._process.memory_info()
            self.statistics.memory_usage_end_mb = memory_info.rss / 1024 / 1024
            
            # Calculate delta
            self.statistics.memory_delta_mb = (
                self.statistics.memory_usage_end_mb - 
                self.statistics.memory_usage_start_mb
            )
            
            # Record final system memory percentage
            system_memory = psutil.virtual_memory()
            self.statistics.system_memory_percent_end = system_memory.percent
            
            self._monitoring_active = False
            
            if self.debug_mode:
                logger.info(f"[Memory Manager] Stopped monitoring - "
                           f"Final: {self.statistics.memory_usage_end_mb:.2f} MB, "
                           f"Delta: {self.statistics.memory_delta_mb:+.2f} MB, "
                           f"Peak: {self.statistics.memory_usage_peak_mb:.2f} MB")
    
    def get_statistics(self) -> MemoryStatistics:
        """
        Get memory management statistics.
        
        Returns:
            MemoryStatistics object
            
        Requirements: 6.5, 15.2
        """
        with self._lock:
            return MemoryStatistics(
                memory_usage_start_mb=self.statistics.memory_usage_start_mb,
                memory_usage_peak_mb=self.statistics.memory_usage_peak_mb,
                memory_usage_end_mb=self.statistics.memory_usage_end_mb,
                memory_delta_mb=self.statistics.memory_delta_mb,
                system_memory_percent_start=self.statistics.system_memory_percent_start,
                system_memory_percent_peak=self.statistics.system_memory_percent_peak,
                system_memory_percent_end=self.statistics.system_memory_percent_end,
                gc_collections_triggered=self.statistics.gc_collections_triggered,
                memory_warnings_issued=self.statistics.memory_warnings_issued,
                memory_threshold_exceeded_count=self.statistics.memory_threshold_exceeded_count,
                data_structures_cleared=self.statistics.data_structures_cleared
            )
    
    def reset_statistics(self):
        """Reset memory statistics"""
        with self._lock:
            self.statistics = MemoryStatistics()
    
    def get_memory_report(self) -> Dict[str, Any]:
        """
        Get comprehensive memory report.
        
        Returns:
            Dictionary with memory report data
            
        Requirements: 6.5, 15.2
        """
        with self._lock:
            # Access statistics directly instead of calling get_statistics() to avoid nested lock
            stats = self.statistics
            
            # Calculate efficiency metrics
            memory_efficiency = "Good"
            if stats.memory_delta_mb > 1000:
                memory_efficiency = "Poor"
            elif stats.memory_delta_mb > 500:
                memory_efficiency = "Fair"
            
            leak_detected = False
            if stats.memory_delta_mb > 100 and stats.gc_collections_triggered > 0:
                # Significant memory increase despite garbage collection
                leak_detected = True
            
            report = {
                'memory_usage': {
                    'start_mb': stats.memory_usage_start_mb,
                    'peak_mb': stats.memory_usage_peak_mb,
                    'end_mb': stats.memory_usage_end_mb,
                    'delta_mb': stats.memory_delta_mb
                },
                'system_memory': {
                    'start_percent': stats.system_memory_percent_start,
                    'peak_percent': stats.system_memory_percent_peak,
                    'end_percent': stats.system_memory_percent_end
                },
                'management': {
                    'gc_collections': stats.gc_collections_triggered,
                    'warnings_issued': stats.memory_warnings_issued,
                    'threshold_exceeded_count': stats.memory_threshold_exceeded_count,
                    'data_structures_cleared': stats.data_structures_cleared
                },
                'assessment': {
                    'efficiency': memory_efficiency,
                    'leak_detected': leak_detected,
                    'peak_within_threshold': stats.memory_usage_peak_mb <= self.memory_threshold_mb
                }
            }
            
            return report
    
    def validate_no_leaks(self) -> Dict[str, Any]:
        """
        Validate that there are no memory leaks.
        
        Returns:
            Dictionary with validation results
            
        Requirements: 6.5, 15.2
        """
        with self._lock:
            # Access statistics directly instead of calling get_statistics() to avoid nested lock
            stats = self.statistics
            
            # Check for memory leaks
            # A leak is suspected if:
            # 1. Memory increased significantly (>100 MB)
            # 2. Garbage collection was performed
            # 3. Memory didn't decrease after GC
            
            leak_suspected = False
            warnings = []
            errors = []
            
            if stats.memory_delta_mb > 100:
                if stats.gc_collections_triggered > 0:
                    leak_suspected = True
                    errors.append(
                        f"Potential memory leak: Memory increased by {stats.memory_delta_mb:.2f} MB "
                        f"despite {stats.gc_collections_triggered} garbage collections"
                    )
                else:
                    warnings.append(
                        f"Large memory increase: {stats.memory_delta_mb:.2f} MB "
                        f"(no garbage collection performed)"
                    )
            
            if stats.memory_usage_peak_mb > self.memory_threshold_mb:
                warnings.append(
                    f"Peak memory exceeded threshold: {stats.memory_usage_peak_mb:.2f} MB > "
                    f"{self.memory_threshold_mb:.2f} MB"
                )
            
            validation_results = {
                'valid': not leak_suspected,
                'leak_suspected': leak_suspected,
                'memory_delta_mb': stats.memory_delta_mb,
                'peak_mb': stats.memory_usage_peak_mb,
                'gc_collections': stats.gc_collections_triggered,
                'warnings': warnings,
                'errors': errors
            }
            
            return validation_results


class MemoryMonitoringContext:
    """
    Context manager for memory monitoring.
    
    Usage:
        with MemoryMonitoringContext(memory_manager) as monitor:
            # Perform memory-intensive operations
            pass
    """
    
    def __init__(self, memory_manager: MemoryManager):
        """
        Initialize monitoring context.
        
        Args:
            memory_manager: MemoryManager instance
        """
        self.memory_manager = memory_manager
    
    def __enter__(self):
        """Start monitoring"""
        self.memory_manager.start_monitoring()
        return self.memory_manager
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop monitoring"""
        self.memory_manager.stop_monitoring()
        return False
