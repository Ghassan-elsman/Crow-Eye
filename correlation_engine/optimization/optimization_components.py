"""
Consolidated Optimization Components for Time Engine Performance


- PerformanceProfiler: Operation timing and memory tracking
- EmptyWindowDetector: Empty window detection and skipping
- MemoryMonitor: Memory monitoring and threshold management
- ParallelCoordinator: Parallel processing coordination
- TimestampCache: Timestamp conversion and parsing caching


"""

import gc
import os
import time
import psutil
import logging
import threading
import multiprocessing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any, Callable, Set, TYPE_CHECKING
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
from enum import Enum

if TYPE_CHECKING:
    from correlation_engine.engine.time_based_engine import WindowQueryManager, TimeWindow

logger = logging.getLogger(__name__)


# ============================================================================
# PERFORMANCE PROFILER
# ============================================================================

@dataclass
class OperationStats:

    operation_name: str
    call_count: int = 0
    total_time_seconds: float = 0.0
    average_time_seconds: float = 0.0
    min_time_seconds: float = float('inf')
    max_time_seconds: float = 0.0
    memory_delta_mb: Optional[float] = None

    
    def update(self, elapsed_time: float) -> None:
        """Update statistics with a new timing measurement"""
        self.call_count += 1
        self.total_time_seconds += elapsed_time
        self.average_time_seconds = self.total_time_seconds / self.call_count
        self.min_time_seconds = min(self.min_time_seconds, elapsed_time)
        self.max_time_seconds = max(self.max_time_seconds, elapsed_time)


@dataclass
class PerformanceReport:
    """Complete performance report (Requirements 1.3, 1.5)"""
    total_execution_time: float
    operation_stats: Dict[str, OperationStats]
    memory_checkpoints: Dict[str, float] = field(default_factory=dict)
    peak_memory_mb: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ComparisonReport:
    """Comparison report between baseline and optimized (Requirement 1.5)"""
    baseline: PerformanceReport
    optimized: PerformanceReport
    improvements: Dict[str, float] = field(default_factory=dict)
    
    def __post_init__(self):
        """Calculate improvements after initialization"""
        self._calculate_improvements()
    
    def _calculate_improvements(self) -> None:
        """Calculate percentage improvements"""
        if self.baseline.total_execution_time > 0:
            time_diff = self.baseline.total_execution_time - self.optimized.total_execution_time
            self.improvements['total_execution_time'] = (
                time_diff / self.baseline.total_execution_time * 100
            )
        
        for op_name, baseline_stats in self.baseline.operation_stats.items():
            if op_name in self.optimized.operation_stats:
                optimized_stats = self.optimized.operation_stats[op_name]
                if baseline_stats.total_time_seconds > 0:
                    time_diff = baseline_stats.total_time_seconds - optimized_stats.total_time_seconds
                    self.improvements[f'{op_name}_time'] = (
                        time_diff / baseline_stats.total_time_seconds * 100
                    )
        
        if self.baseline.peak_memory_mb > 0:
            memory_diff = self.baseline.peak_memory_mb - self.optimized.peak_memory_mb
            self.improvements['peak_memory'] = (
                memory_diff / self.baseline.peak_memory_mb * 100
            )



class PerformanceProfiler:
    """
    Performance profiler for measuring operation timing and memory usage.
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """
    
    def __init__(self, enabled: bool = True):
        """Initialize the performance profiler"""
        self._enabled = enabled
        self._operation_stats: Dict[str, OperationStats] = {}
        self._memory_checkpoints: Dict[str, float] = {}
        self._active_operations: Dict[str, float] = {}
        self._start_time: Optional[float] = None
        self._peak_memory_mb: float = 0.0
        self._process = psutil.Process()
    
    def start_operation(self, operation_name: str) -> None:
        """Start timing an operation (Requirement 1.1)"""
        if not self._enabled:
            return
        
        if self._start_time is None:
            self._start_time = time.time()
        
        if operation_name not in self._operation_stats:
            self._operation_stats[operation_name] = OperationStats(operation_name=operation_name)
        
        self._active_operations[operation_name] = time.time()
    
    def end_operation(self, operation_name: str) -> float:
        """End timing an operation (Requirements 1.1, 1.4)"""
        if not self._enabled:
            return 0.0
        
        if operation_name not in self._active_operations:
            return 0.0
        
        start_time = self._active_operations.pop(operation_name)
        elapsed = time.time() - start_time
        self._operation_stats[operation_name].update(elapsed)
        
        return elapsed
    
    def record_memory_checkpoint(self, checkpoint_name: str) -> float:
        """Record current memory usage (Requirement 1.2)"""
        if not self._enabled:
            return 0.0
        
        memory_info = self._process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)
        self._memory_checkpoints[checkpoint_name] = memory_mb
        self._peak_memory_mb = max(self._peak_memory_mb, memory_mb)
        
        return memory_mb
    
    def get_operation_stats(self, operation_name: str) -> Optional[OperationStats]:
        """Get statistics for a specific operation (Requirement 1.4)"""
        return self._operation_stats.get(operation_name)
    
    def get_performance_report(self) -> PerformanceReport:
        """Generate a complete performance report (Requirement 1.3)"""
        total_time = time.time() - self._start_time if self._start_time else 0.0
        
        return PerformanceReport(
            total_execution_time=total_time,
            operation_stats=self._operation_stats.copy(),
            memory_checkpoints=self._memory_checkpoints.copy(),
            peak_memory_mb=self._peak_memory_mb,
            timestamp=datetime.now()
        )
    
    def compare_with_baseline(self, baseline: PerformanceReport) -> ComparisonReport:
        """Compare current performance with baseline (Requirement 1.5)"""
        current_report = self.get_performance_report()
        return ComparisonReport(baseline=baseline, optimized=current_report)
    
    @contextmanager
    def profile_operation(self, operation_name: str):
        """Context manager for profiling an operation"""
        self.start_operation(operation_name)
        try:
            yield
        finally:
            self.end_operation(operation_name)
    
    def reset(self) -> None:
        """Reset all profiling data"""
        self._operation_stats.clear()
        self._memory_checkpoints.clear()
        self._active_operations.clear()
        self._start_time = None
        self._peak_memory_mb = 0.0



# ============================================================================
# EMPTY WINDOW DETECTOR
# ============================================================================

@dataclass
class SkipStatistics:
    """Statistics about empty window detection (Requirement 3.3)"""
    total_windows_checked: int = 0
    empty_windows_found: int = 0
    time_saved_seconds: float = 0.0
    quick_check_failures: int = 0  # Requirement 1.5, 10.5
    index_verification_failures: int = 0  # Requirement 1.5, 10.5

    @property
    def skip_rate_percentage(self) -> float:
        """Calculate the percentage of windows that were skipped"""
        if self.total_windows_checked == 0:
            return 0.0
        return (self.empty_windows_found / self.total_windows_checked) * 100

    @property
    def reliability_percentage(self) -> float:
        """
        Calculate the percentage of checks that completed successfully.

        Requirement 1.5, 10.5

        Returns:
            Percentage of successful checks (0-100)
        """
        if self.total_windows_checked == 0:
            return 100.0
        failures = self.quick_check_failures + self.index_verification_failures
        return ((self.total_windows_checked - failures) / self.total_windows_checked) * 100




class EmptyWindowDetector:
    """
    Detects empty time windows to skip unnecessary processing.
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    """
    
    def __init__(self, window_manager: 'WindowQueryManager', debug_mode: bool = False):
        """Initialize the empty window detector"""
        self.window_manager = window_manager
        self.debug_mode = debug_mode
        self.statistics = SkipStatistics()
    
    def is_window_empty(self, window: 'TimeWindow') -> bool:
        """
        Check if a time window is empty (Requirements 3.1, 3.4, 3.5, 1.3, 7.1, 7.4, 1.5)
        
        Returns:
            True if window is empty, False otherwise
        """
        self.statistics.total_windows_checked += 1
        
        # Verify indexes exist before quick check (Requirements 1.3, 7.1, 7.4)
        if not self._verify_indexes():
            self.statistics.index_verification_failures += 1  # Requirement 1.5, 10.5
            if self.debug_mode:
                print(f"[EmptyWindowDetector] Indexes missing, skipping quick check for window {window.window_id}")
            return False  # Assume non-empty if can't verify
        
        # Wrap quick check in try-except for error handling (Requirement 1.5)
        try:
            has_records = self.window_manager.quick_check_window_has_records(window)
            
            if not has_records:
                self.statistics.empty_windows_found += 1
                
                if self.debug_mode:
                    print(f"[EmptyWindowDetector] Window {window.window_id} is empty - skipping")
                
                return True
            
            return False
        except Exception as e:
            # On error, assume window has data (safe fallback) (Requirement 1.5)
            self.statistics.quick_check_failures += 1  # Requirement 1.5, 10.5
            if self.debug_mode:
                print(f"[EmptyWindowDetector] Quick check failed for window {window.window_id}: {e}, assuming non-empty")
            return False
    
    def record_time_saved(self, seconds: float) -> None:
        """Record time saved by skipping (Requirement 3.3)"""
        self.statistics.time_saved_seconds += seconds
    
    def get_skip_statistics(self) -> SkipStatistics:
        """Get skip statistics (Requirement 3.3)"""
        return self.statistics
    
    def reset_statistics(self) -> None:
        """Reset skip statistics"""
        self.statistics = SkipStatistics()

    def _verify_indexes(self) -> bool:
        """
        Verify feathers with timestamp columns have indexes before performing quick checks.

        Requirements: 1.3, 7.1, 7.4

        Returns:
            True if all feathers with timestamps have indexes, False otherwise
        """
        feathers_checked = 0
        feathers_with_indexes = 0
        feathers_without_timestamps = 0
        
        for feather_id, query_manager in self.window_manager.feather_queries.items():
            # Skip feathers without timestamp columns - they can't be indexed
            has_timestamps = False
            if hasattr(query_manager, 'timestamp_columns') and query_manager.timestamp_columns:
                has_timestamps = True
            elif hasattr(query_manager, 'timestamp_column') and query_manager.timestamp_column:
                has_timestamps = True
            
            if not has_timestamps:
                feathers_without_timestamps += 1
                if self.debug_mode:
                    print(f"[EmptyWindowDetector] Skipping {feather_id} - no timestamp columns detected")
                continue
            
            feathers_checked += 1
            if query_manager.has_timestamp_index():
                feathers_with_indexes += 1
            else:
                if self.debug_mode:
                    print(f"[EmptyWindowDetector] Missing timestamp index on {feather_id}")
                return False
        
        # If no feathers have timestamps, we can't do quick checks
        if feathers_checked == 0:
            if self.debug_mode:
                print(f"[EmptyWindowDetector] No feathers with timestamp columns found ({feathers_without_timestamps} feathers total)")
            return False
        
        if self.debug_mode and feathers_without_timestamps > 0:
            print(f"[EmptyWindowDetector] Verified {feathers_with_indexes}/{feathers_checked} feathers with timestamps have indexes ({feathers_without_timestamps} feathers skipped - no timestamps)")
        
        return True




# ============================================================================
# MEMORY MONITOR
# ============================================================================

@dataclass
class MemoryStatus:

    current_mb: float
    threshold_mb: float
    percentage_used: float
    should_enable_streaming: bool
    should_reduce_caches: bool


class MemoryMonitor:
    """
    Monitors memory usage and triggers actions based on thresholds.
    

    """
    
    def __init__(self, threshold_mb: int = 4096, check_interval_seconds: int = 1):
        """Initialize the memory monitor"""
        self.threshold_mb = threshold_mb
        self.check_interval_seconds = check_interval_seconds
        self.cache_reduction_threshold_mb = threshold_mb * 0.8
        self.streaming_threshold_mb = threshold_mb * 0.9
        
        self.gc_triggered_count = 0
        self.cache_reductions_count = 0
        self.streaming_activations_count = 0
        
        logger.info(
            f"MemoryMonitor initialized: threshold={threshold_mb}MB, "
            f"cache_reduction={self.cache_reduction_threshold_mb:.0f}MB, "
            f"streaming={self.streaming_threshold_mb:.0f}MB"
        )
    
    def get_current_usage_mb(self) -> float:
        """Get current memory usage in MB"""
        process = psutil.Process()
        memory_info = process.memory_info()
        return memory_info.rss / (1024 * 1024)
    
    def check_threshold(self) -> MemoryStatus:
        """Check current memory usage against thresholds (Requirement 5.1)"""
        current_mb = self.get_current_usage_mb()
        percentage_used = (current_mb / self.threshold_mb) * 100
        
        should_reduce_caches = current_mb > self.cache_reduction_threshold_mb
        should_enable_streaming = current_mb > self.streaming_threshold_mb
        
        status = MemoryStatus(
            current_mb=current_mb,
            threshold_mb=self.threshold_mb,
            percentage_used=percentage_used,
            should_enable_streaming=should_enable_streaming,
            should_reduce_caches=should_reduce_caches
        )
        
        if should_enable_streaming:
            self.streaming_activations_count += 1
            logger.warning(
                f"Memory threshold exceeded: {current_mb:.1f}MB / {self.threshold_mb}MB "
                f"({percentage_used:.1f}%) - Streaming mode recommended"
            )
        elif should_reduce_caches:
            logger.info(
                f"Memory usage high: {current_mb:.1f}MB / {self.threshold_mb}MB "
                f"({percentage_used:.1f}%) - Cache reduction recommended"
            )
        
        return status
    
    def trigger_garbage_collection(self) -> float:
        """Trigger garbage collection (Requirement 5.4)"""
        memory_before = self.get_current_usage_mb()
        collected = gc.collect()
        memory_after = self.get_current_usage_mb()
        memory_freed = memory_before - memory_after
        
        self.gc_triggered_count += 1
        logger.info(f"GC triggered: freed {memory_freed:.1f}MB (collected {collected} objects)")
        
        return memory_freed
    
    def reduce_cache_sizes(self, target_reduction_mb: int, 
                          cache_reducers: Optional[List[Callable[[int], float]]] = None) -> float:
        """Reduce cache sizes to free memory (Requirement 5.5)"""
        if not cache_reducers:
            logger.debug("No cache reducers registered")
            return 0.0
        
        memory_before = self.get_current_usage_mb()
        total_freed = 0.0
        
        for reducer in cache_reducers:
            try:
                freed = reducer(target_reduction_mb)
                total_freed += freed
            except Exception as e:
                logger.error(f"Error in cache reducer: {e}")
        
        memory_after = self.get_current_usage_mb()
        actual_freed = memory_before - memory_after
        
        self.cache_reductions_count += 1
        logger.info(f"Cache reduction: target={target_reduction_mb}MB, freed={actual_freed:.1f}MB")
        
        return actual_freed
    
    def get_statistics(self) -> dict:
        """Get memory monitoring statistics"""
        return {
            'threshold_mb': self.threshold_mb,
            'cache_reduction_threshold_mb': self.cache_reduction_threshold_mb,
            'streaming_threshold_mb': self.streaming_threshold_mb,
            'gc_triggered_count': self.gc_triggered_count,
            'cache_reductions_count': self.cache_reductions_count,
            'streaming_activations_count': self.streaming_activations_count,
            'current_usage_mb': self.get_current_usage_mb()
        }
    
    def reset_statistics(self):
        """Reset monitoring statistics"""
        self.gc_triggered_count = 0
        self.cache_reductions_count = 0
        self.streaming_activations_count = 0



# ============================================================================
# PARALLEL COORDINATOR
# ============================================================================

@dataclass
class WorkerConfig:
    """Configuration for parallel workers (Requirement 4.2)"""
    worker_count: int
    memory_per_worker_mb: float
    cpu_cores_available: int
    use_processes: bool = False


class ParallelCoordinator:
    """
    Coordinates parallel processing of time windows.
    
   
    """
    
    def __init__(self, max_workers: Optional[int] = None, 
                 memory_limit_mb: Optional[int] = None,
                 shared_data_strategy: str = "thread_local"):
        """Initialize the parallel coordinator"""
        self.max_workers = max_workers
        self.memory_limit_mb = memory_limit_mb
        self.shared_data_strategy = shared_data_strategy
        
        self._executor = None
        self._work_queue: Optional[Queue] = None
        self._results_queue: Optional[Queue] = None
        self._worker_errors: Dict[str, List[str]] = {}
        self._lock = threading.Lock()
        
        self.total_windows_assigned = 0
        self.total_windows_completed = 0
        self.worker_completion_counts: Dict[str, int] = {}
        self.worker_error_counts: Dict[str, int] = {}
    
    def configure_workers(self, cpu_cores: int, memory_mb: int, data_size_mb: int = 0) -> int:
        """Calculate optimal worker count (Requirement 4.2)"""
        optimal_workers = cpu_cores
        
        memory_per_worker = 500
        if data_size_mb > 0:
            memory_per_worker += (data_size_mb / cpu_cores)
        
        memory_limited_workers = max(1, int(memory_mb / memory_per_worker))
        optimal_workers = min(optimal_workers, memory_limited_workers)
        
        if data_size_mb > 0 and data_size_mb < 100:
            optimal_workers = 1
        
        if self.max_workers is not None:
            optimal_workers = min(optimal_workers, self.max_workers)
        
        return max(1, optimal_workers)
    
    def distribute_windows(self, windows: List[Any]) -> List[List[Any]]:
        """Distribute windows across workers (Requirement 4.1)"""
        if not windows:
            return []
        
        worker_count = self._get_active_worker_count()
        if worker_count <= 0:
            worker_count = 1
        
        batches = [[] for _ in range(worker_count)]
        
        for i, window in enumerate(windows):
            worker_idx = i % worker_count
            batches[worker_idx].append(window)
        
        return batches
    
    def process_with_shared_cache(self, windows: List[Any], process_func: Callable,
                                 shared_data: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Process windows in parallel (Requirements 4.3, 4.4, 4.5)"""
        if not windows:
            return []
        
        cpu_cores = os.cpu_count() or 4
        memory_mb = self._get_available_memory_mb()
        worker_count = self.configure_workers(cpu_cores, memory_mb)
        
        self._work_queue = Queue()
        self._results_queue = Queue()
        
        for i, window in enumerate(windows):
            self._work_queue.put((i, window))
        
        for _ in range(worker_count):
            self._work_queue.put(None)
        
        results = []
        
        try:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                self._executor = executor
                
                futures = []
                for worker_id in range(worker_count):
                    future = executor.submit(
                        self._worker_process_loop,
                        worker_id,
                        process_func,
                        shared_data
                    )
                    futures.append(future)
                
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        with self._lock:
                            worker_id = "unknown"
                            if worker_id not in self._worker_errors:
                                self._worker_errors[worker_id] = []
                            self._worker_errors[worker_id].append(str(e))
            
            results_dict = {}
            while not self._results_queue.empty():
                try:
                    idx, result, error = self._results_queue.get_nowait()
                    if error is None:
                        results_dict[idx] = result
                except Empty:
                    break
            
            results = [results_dict.get(i) for i in range(len(windows)) if i in results_dict]
            
        finally:
            self._executor = None
            self._work_queue = None
            self._results_queue = None
        
        return results
    
    def _worker_process_loop(self, worker_id: int, process_func: Callable,
                            shared_data: Optional[Dict[str, Any]]):
      
        worker_name = f"worker_{worker_id}"
        
        with self._lock:
            self.worker_completion_counts[worker_name] = 0
            self.worker_error_counts[worker_name] = 0
        
        while True:
            try:
                work_item = self._work_queue.get(timeout=1.0)
                
                if work_item is None:
                    break
                
                idx, window = work_item
                
                try:
                    result = process_func(window, shared_data)
                    self._results_queue.put((idx, result, None))
                    
                    with self._lock:
                        self.worker_completion_counts[worker_name] += 1
                        self.total_windows_completed += 1
                    
                except Exception as e:
                    error_msg = f"Worker {worker_name} error: {str(e)}"
                    self._results_queue.put((idx, None, error_msg))
                    
                    with self._lock:
                        self.worker_error_counts[worker_name] += 1
                        if worker_name not in self._worker_errors:
                            self._worker_errors[worker_name] = []
                        self._worker_errors[worker_name].append(error_msg)
                
            except Empty:
                continue
            except Exception as e:
                with self._lock:
                    if worker_name not in self._worker_errors:
                        self._worker_errors[worker_name] = []
                    self._worker_errors[worker_name].append(f"Worker loop error: {str(e)}")
                break
    
    def _get_active_worker_count(self) -> int:
        """Get the number of active workers"""
        if self.max_workers is not None:
            return self.max_workers
        
        cpu_cores = os.cpu_count() or 4
        memory_mb = self._get_available_memory_mb()
        
        return self.configure_workers(cpu_cores, memory_mb)
    
    def _get_available_memory_mb(self) -> int:
        """Get available system memory in MB"""
        if self.memory_limit_mb is not None:
            return self.memory_limit_mb
        
        try:
            mem = psutil.virtual_memory()
            return int(mem.available / (1024 * 1024))
        except Exception:
            return 4096
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about parallel processing"""
        with self._lock:
            return {
                'total_windows_assigned': self.total_windows_assigned,
                'total_windows_completed': self.total_windows_completed,
                'worker_completion_counts': dict(self.worker_completion_counts),
                'worker_error_counts': dict(self.worker_error_counts),
                'worker_errors': dict(self._worker_errors),
                'active_workers': self._get_active_worker_count(),
                'shared_data_strategy': self.shared_data_strategy
            }
    
    def reset_statistics(self):
        """Reset all statistics counters"""
        with self._lock:
            self.total_windows_assigned = 0
            self.total_windows_completed = 0
            self.worker_completion_counts.clear()
            self.worker_error_counts.clear()
            self._worker_errors.clear()
    
    def has_errors(self) -> bool:
        """Check if any workers encountered errors"""
        with self._lock:
            return len(self._worker_errors) > 0
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of worker errors"""
        with self._lock:
            total_errors = sum(self.worker_error_counts.values())
            
            sample_errors = {}
            for worker, errors in self._worker_errors.items():
                sample_errors[worker] = errors[:5]
            
            return {
                'total_errors': total_errors,
                'errors_by_worker': dict(self.worker_error_counts),
                'sample_errors': sample_errors
            }


def calculate_optimal_workers(cpu_cores: int, memory_mb: int, data_size_mb: int = 0) -> int:
    """Standalone function to calculate optimal worker count"""
    max_workers = cpu_cores
    memory_per_worker = 500
    memory_limited_workers = memory_mb // memory_per_worker
    max_workers = min(max_workers, memory_limited_workers)
    
    if data_size_mb < 100:
        max_workers = 1
    
    return max(1, max_workers)



# ============================================================================
# TIMESTAMP CACHE
# ============================================================================

class TimestampFormat(Enum):
   
    UNKNOWN = "unknown"
    ISO8601 = "iso8601"
    ISO8601_ZULU = "iso8601_zulu"
    DATETIME_STRING = "datetime_string"
    UNIX_SECONDS = "unix_seconds"
    UNIX_MILLISECONDS = "unix_milliseconds"
    UNIX_MICROSECONDS = "unix_microseconds"
    WINDOWS_FILETIME = "windows_filetime"
    EPOCH_DAYS = "epoch_days"
    DATE_SLASH_US = "date_slash_us"
    DATE_SLASH_EU = "date_slash_eu"
    DATE_DASH = "date_dash"
    CUSTOM = "custom"


class TimestampCache:
    """
    Cache for UTC timestamp conversions.
    
    Requirements: 6.3, 7.3
    """
    
    def __init__(self, max_size: int = 10000):
        """Initialize timestamp cache"""
        self.max_size = max_size
        self._cache: Dict[datetime, datetime] = {}
        self._hits = 0
        self._misses = 0
    
    def get(self, dt: datetime) -> Optional[datetime]:
        """Get cached UTC conversion"""
        if dt in self._cache:
            self._hits += 1
            return self._cache[dt]
        
        self._misses += 1
        return None
    
    def put(self, dt: datetime, utc_dt: datetime) -> None:
        """Cache UTC conversion result"""
        if len(self._cache) >= self.max_size:
            items = list(self._cache.items())
            self._cache = dict(items[len(items)//2:])
        
        self._cache[dt] = utc_dt
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'size': len(self._cache),
            'max_size': self.max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate_percent': hit_rate
        }
    
    def clear(self) -> None:
        """Clear the cache"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0


class TimestampFormatCache:
    """
    Cache for timestamp format detection results.
   
    """
    
    def __init__(self):
        """Initialize format cache"""
        self._cache: Dict[str, TimestampFormat] = {}
        self._hits = 0
        self._misses = 0
    
    def get(self, data_source: str) -> Optional[TimestampFormat]:
        """Get cached format for data source"""
        if data_source in self._cache:
            self._hits += 1
            return self._cache[data_source]
        
        self._misses += 1
        return None
    
    def put(self, data_source: str, format: TimestampFormat) -> None:
        """Cache format detection result"""
        self._cache[data_source] = format
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'size': len(self._cache),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate_percent': hit_rate
        }
    
    def clear(self) -> None:
        """Clear the cache"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0


@dataclass
class ParsedTimestamp:
    """Cached parse result"""
    datetime_value: datetime
    format: TimestampFormat


class TimestampParseCache:
    """
    Cache for timestamp parsing results with error caching.
    

    """
    
    def __init__(self, max_size: int = 10000):
        """Initialize parse cache"""
        self.max_size = max_size
        self._cache: Dict[Any, ParsedTimestamp] = {}
        self._error_cache: Set[Any] = set()
        self._hits = 0
        self._misses = 0
        self._error_hits = 0
    
    def get(self, value: Any) -> Optional[ParsedTimestamp]:
        """Get cached parse result"""
        if value in self._error_cache:
            self._error_hits += 1
            return None
        
        if value in self._cache:
            self._hits += 1
            return self._cache[value]
        
        self._misses += 1
        return None
    
    def put_success(self, value: Any, dt: datetime, format: TimestampFormat) -> None:
        """Cache successful parse result"""
        if len(self._cache) >= self.max_size:
            items = list(self._cache.items())
            self._cache = dict(items[len(items)//2:])
        
        self._cache[value] = ParsedTimestamp(datetime_value=dt, format=format)
    
    def put_error(self, value: Any) -> None:
        """Cache parse error (Requirement 7.5)"""
        if len(self._error_cache) >= self.max_size:
            errors = list(self._error_cache)
            self._error_cache = set(errors[len(errors)//2:])
        
        self._error_cache.add(value)
    
    def is_known_error(self, value: Any) -> bool:
        """Check if value is a known parse error"""
        return value in self._error_cache
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self._hits + self._misses + self._error_hits
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
        error_hit_rate = (self._error_hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'cache_size': len(self._cache),
            'error_cache_size': len(self._error_cache),
            'max_size': self.max_size,
            'hits': self._hits,
            'misses': self._misses,
            'error_hits': self._error_hits,
            'hit_rate_percent': hit_rate,
            'error_hit_rate_percent': error_hit_rate
        }
    
    def clear(self) -> None:
        """Clear the cache"""
        self._cache.clear()
        self._error_cache.clear()
        self._hits = 0
        self._misses = 0
        self._error_hits = 0


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Performance Profiler
    'PerformanceProfiler',
    'OperationStats',
    'PerformanceReport',
    'ComparisonReport',
    # Empty Window Detector
    'EmptyWindowDetector',
    'SkipStatistics',
    # Memory Monitor
    'MemoryMonitor',
    'MemoryStatus',
    # Parallel Coordinator
    'ParallelCoordinator',
    'WorkerConfig',
    'calculate_optimal_workers',
    # Timestamp Cache
    'TimestampCache',
    'TimestampFormatCache',
    'TimestampParseCache',
    'TimestampFormat',
    'ParsedTimestamp',
]
