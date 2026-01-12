"""
Parallel Window Processor for Time-Window Scanning Engine

This module provides parallel processing capabilities for time windows in the
Time-Window Scanning Correlation Engine. It implements thread pool management,
advanced load balancing, and comprehensive resource management for concurrent window processing.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

# Optional import for resource monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from .two_phase_correlation import TimeWindow
from .correlation_result import CorrelationMatch
from ..wings.core.wing_model import Wing


@dataclass
class WindowProcessingTask:
    """Represents a window processing task for parallel execution"""
    window: TimeWindow
    task_id: str
    priority: int = 0  # Higher priority = processed first
    estimated_complexity: float = 1.0  # Estimated processing complexity


@dataclass
class WindowProcessingResult:
    """Result from processing a window in parallel"""
    task_id: str
    window: TimeWindow
    matches: List[CorrelationMatch]
    processing_time_seconds: float
    error: Optional[str] = None
    worker_id: Optional[str] = None


@dataclass
class ParallelProcessingStats:
    """Statistics for parallel processing performance"""
    total_windows_processed: int = 0
    total_matches_found: int = 0
    total_processing_time: float = 0.0
    average_window_time: float = 0.0
    worker_utilization: Dict[str, float] = None
    load_balancing_efficiency: float = 0.0
    parallel_speedup: float = 1.0
    
    def __post_init__(self):
        if self.worker_utilization is None:
            self.worker_utilization = {}


class WorkerLoadBalancer:
    """
    Manages load balancing across worker threads.
    
    Tracks worker performance and distributes tasks based on:
    - Current worker load
    - Historical performance
    - Task complexity estimates
    - Resource utilization (CPU, memory)
    - Dynamic load redistribution
    """
    
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.worker_loads: Dict[str, float] = {}
        self.worker_performance: Dict[str, List[float]] = {}
        self.worker_resource_usage: Dict[str, Dict[str, float]] = {}
        self.worker_error_counts: Dict[str, int] = {}
        self.task_queue = Queue()
        self._lock = threading.Lock()
        
        # Enhanced load balancing parameters
        self.load_balancing_algorithm = "adaptive"  # "round_robin", "least_loaded", "adaptive"
        self.performance_weight = 0.4  # Weight for historical performance
        self.load_weight = 0.4  # Weight for current load
        self.resource_weight = 0.2  # Weight for resource utilization
        
        # Dynamic adjustment parameters
        self.load_imbalance_threshold = 0.3  # Threshold for triggering load redistribution
        self.performance_variance_threshold = 0.5  # Threshold for performance variance
        self.last_rebalance_time = time.time()
        self.rebalance_interval_seconds = 30  # Minimum interval between rebalances
    
    def register_worker(self, worker_id: str):
        """Register a new worker thread"""
        with self._lock:
            self.worker_loads[worker_id] = 0.0
            self.worker_performance[worker_id] = []
            self.worker_resource_usage[worker_id] = {
                'cpu_usage': 0.0,
                'memory_usage_mb': 0.0,
                'active_tasks': 0
            }
            self.worker_error_counts[worker_id] = 0
    
    def get_optimal_worker(self, task_complexity: float) -> Optional[str]:
        """
        Get the optimal worker for a task based on current load, performance, and resources.
        
        Args:
            task_complexity: Estimated complexity of the task
            
        Returns:
            Worker ID of optimal worker, or None if all workers are busy
        """
        with self._lock:
            if not self.worker_loads:
                return None
            
            # Check if dynamic rebalancing is needed
            self._check_and_perform_rebalancing()
            
            if self.load_balancing_algorithm == "round_robin":
                return self._get_round_robin_worker()
            elif self.load_balancing_algorithm == "least_loaded":
                return self._get_least_loaded_worker()
            else:  # adaptive algorithm
                return self._get_adaptive_optimal_worker(task_complexity)
    
    def _get_round_robin_worker(self) -> Optional[str]:
        """Simple round-robin worker selection"""
        if not hasattr(self, '_round_robin_index'):
            self._round_robin_index = 0
        
        worker_ids = list(self.worker_loads.keys())
        if not worker_ids:
            return None
        
        worker_id = worker_ids[self._round_robin_index % len(worker_ids)]
        self._round_robin_index += 1
        return worker_id
    
    def _get_least_loaded_worker(self) -> Optional[str]:
        """Select worker with lowest current load"""
        if not self.worker_loads:
            return None
        
        return min(self.worker_loads.keys(), key=lambda w: self.worker_loads[w])
    
    def _get_adaptive_optimal_worker(self, task_complexity: float) -> Optional[str]:
        """
        Advanced adaptive worker selection based on multiple factors.
        
        Args:
            task_complexity: Estimated complexity of the task
            
        Returns:
            Optimal worker ID
        """
        best_worker = None
        best_score = float('inf')
        
        for worker_id in self.worker_loads.keys():
            # Calculate composite score based on multiple factors
            score = self._calculate_worker_score(worker_id, task_complexity)
            
            if score < best_score:
                best_score = score
                best_worker = worker_id
        
        return best_worker
    
    def _calculate_worker_score(self, worker_id: str, task_complexity: float) -> float:
        """
        Calculate composite score for worker selection.
        
        Lower score = better worker for the task.
        
        Args:
            worker_id: ID of the worker to score
            task_complexity: Complexity of the task to assign
            
        Returns:
            Composite score for the worker
        """
        # Current load factor
        current_load = self.worker_loads.get(worker_id, 0.0)
        load_score = current_load * self.load_weight
        
        # Performance factor (average processing time)
        perf_history = self.worker_performance.get(worker_id, [])
        if perf_history:
            recent_perf = perf_history[-10:]  # Last 10 tasks
            avg_performance = sum(recent_perf) / len(recent_perf)
            # Normalize performance (lower is better)
            performance_score = avg_performance * task_complexity * self.performance_weight
        else:
            performance_score = task_complexity * self.performance_weight  # Default performance
        
        # Resource utilization factor
        resource_usage = self.worker_resource_usage.get(worker_id, {})
        cpu_usage = resource_usage.get('cpu_usage', 0.0)
        memory_usage = resource_usage.get('memory_usage_mb', 0.0)
        active_tasks = resource_usage.get('active_tasks', 0)
        
        # Combine resource metrics (higher usage = higher score)
        resource_score = (cpu_usage + memory_usage / 100.0 + active_tasks) * self.resource_weight
        
        # Error penalty (workers with more errors get higher scores)
        error_count = self.worker_error_counts.get(worker_id, 0)
        error_penalty = error_count * 0.1  # Small penalty per error
        
        return load_score + performance_score + resource_score + error_penalty
    
    def _check_and_perform_rebalancing(self):
        """
        Check if load rebalancing is needed and perform it if necessary.
        """
        current_time = time.time()
        
        # Only rebalance if enough time has passed
        if current_time - self.last_rebalance_time < self.rebalance_interval_seconds:
            return
        
        # Check load imbalance
        if self._is_load_imbalanced():
            self._perform_load_rebalancing()
            self.last_rebalance_time = current_time
    
    def _is_load_imbalanced(self) -> bool:
        """
        Check if the current load distribution is imbalanced.
        
        Returns:
            True if load is imbalanced and rebalancing is needed
        """
        if len(self.worker_loads) < 2:
            return False
        
        loads = list(self.worker_loads.values())
        if not loads:
            return False
        
        avg_load = sum(loads) / len(loads)
        if avg_load == 0:
            return False
        
        # Calculate coefficient of variation (std dev / mean)
        variance = sum((load - avg_load) ** 2 for load in loads) / len(loads)
        std_dev = variance ** 0.5
        coefficient_of_variation = std_dev / avg_load
        
        return coefficient_of_variation > self.load_imbalance_threshold
    
    def _perform_load_rebalancing(self):
        """
        Perform load rebalancing by adjusting algorithm parameters.
        """
        # Analyze current performance variance
        all_performance = []
        for perf_list in self.worker_performance.values():
            if perf_list:
                all_performance.extend(perf_list[-5:])  # Recent performance
        
        if len(all_performance) < 2:
            return
        
        # Calculate performance variance
        avg_perf = sum(all_performance) / len(all_performance)
        perf_variance = sum((p - avg_perf) ** 2 for p in all_performance) / len(all_performance)
        perf_std_dev = perf_variance ** 0.5
        
        # Adjust algorithm based on performance variance
        if perf_std_dev > self.performance_variance_threshold:
            # High variance - emphasize performance more
            self.performance_weight = min(0.6, self.performance_weight + 0.1)
            self.load_weight = max(0.2, self.load_weight - 0.05)
        else:
            # Low variance - emphasize load balancing more
            self.load_weight = min(0.6, self.load_weight + 0.1)
            self.performance_weight = max(0.2, self.performance_weight - 0.05)
        
        # Ensure weights sum to reasonable total
        total_weight = self.performance_weight + self.load_weight + self.resource_weight
        if total_weight > 1.0:
            factor = 1.0 / total_weight
            self.performance_weight *= factor
            self.load_weight *= factor
            self.resource_weight *= factor
    
    def update_worker_load(self, worker_id: str, load_delta: float):
        """Update worker load (positive = increase, negative = decrease)"""
        with self._lock:
            if worker_id in self.worker_loads:
                self.worker_loads[worker_id] = max(0.0, self.worker_loads[worker_id] + load_delta)
                
                # Update active task count
                if worker_id in self.worker_resource_usage:
                    if load_delta > 0:
                        self.worker_resource_usage[worker_id]['active_tasks'] += 1
                    else:
                        self.worker_resource_usage[worker_id]['active_tasks'] = max(0, 
                            self.worker_resource_usage[worker_id]['active_tasks'] - 1)
    
    def update_worker_resources(self, worker_id: str, cpu_usage: float, memory_usage_mb: float):
        """
        Update worker resource utilization metrics.
        
        Args:
            worker_id: ID of the worker
            cpu_usage: CPU usage percentage (0.0 to 100.0)
            memory_usage_mb: Memory usage in MB
        """
        with self._lock:
            if worker_id in self.worker_resource_usage:
                self.worker_resource_usage[worker_id]['cpu_usage'] = cpu_usage
                self.worker_resource_usage[worker_id]['memory_usage_mb'] = memory_usage_mb
    
    def record_task_completion(self, worker_id: str, processing_time: float, success: bool = True):
        """
        Record task completion for performance tracking.
        
        Args:
            worker_id: ID of the worker
            processing_time: Time taken to process the task
            success: Whether the task completed successfully
        """
        with self._lock:
            if worker_id in self.worker_performance:
                self.worker_performance[worker_id].append(processing_time)
                # Keep only recent history
                if len(self.worker_performance[worker_id]) > 50:
                    self.worker_performance[worker_id] = self.worker_performance[worker_id][-50:]
            
            # Track error counts
            if not success and worker_id in self.worker_error_counts:
                self.worker_error_counts[worker_id] += 1
    
    def get_load_balancing_stats(self) -> Dict[str, Any]:
        """Get comprehensive load balancing statistics"""
        with self._lock:
            total_load = sum(self.worker_loads.values())
            avg_load = total_load / len(self.worker_loads) if self.worker_loads else 0
            
            # Calculate load variance (lower = better balance)
            load_variance = 0.0
            if self.worker_loads:
                load_variance = sum((load - avg_load) ** 2 for load in self.worker_loads.values()) / len(self.worker_loads)
            
            # Efficiency = 1 - (variance / max_possible_variance)
            max_variance = avg_load ** 2 if avg_load > 0 else 1.0
            efficiency = max(0.0, 1.0 - (load_variance / max_variance))
            
            # Calculate performance statistics
            all_recent_performance = []
            worker_performance_stats = {}
            for worker_id, perf_list in self.worker_performance.items():
                if perf_list:
                    recent_perf = perf_list[-10:]
                    avg_perf = sum(recent_perf) / len(recent_perf)
                    worker_performance_stats[worker_id] = avg_perf
                    all_recent_performance.extend(recent_perf)
                else:
                    worker_performance_stats[worker_id] = 0.0
            
            # Calculate performance variance across workers
            performance_variance = 0.0
            if all_recent_performance:
                avg_performance = sum(all_recent_performance) / len(all_recent_performance)
                performance_variance = sum((p - avg_performance) ** 2 for p in all_recent_performance) / len(all_recent_performance)
            
            return {
                'total_load': total_load,
                'average_load': avg_load,
                'load_variance': load_variance,
                'balancing_efficiency': efficiency,
                'worker_loads': dict(self.worker_loads),
                'worker_performance_avg': worker_performance_stats,
                'worker_resource_usage': dict(self.worker_resource_usage),
                'worker_error_counts': dict(self.worker_error_counts),
                'performance_variance': performance_variance,
                'algorithm_weights': {
                    'performance_weight': self.performance_weight,
                    'load_weight': self.load_weight,
                    'resource_weight': self.resource_weight
                },
                'load_balancing_algorithm': self.load_balancing_algorithm,
                'last_rebalance_time': self.last_rebalance_time,
                'is_load_imbalanced': self._is_load_imbalanced()
            }
    
    def set_load_balancing_algorithm(self, algorithm: str):
        """
        Set the load balancing algorithm.
        
        Args:
            algorithm: "round_robin", "least_loaded", or "adaptive"
        """
        if algorithm in ["round_robin", "least_loaded", "adaptive"]:
            self.load_balancing_algorithm = algorithm
        else:
            raise ValueError(f"Unknown load balancing algorithm: {algorithm}")
    
    def adjust_algorithm_weights(self, performance_weight: float, load_weight: float, resource_weight: float):
        """
        Manually adjust algorithm weights for adaptive load balancing.
        
        Args:
            performance_weight: Weight for historical performance (0.0 to 1.0)
            load_weight: Weight for current load (0.0 to 1.0)
            resource_weight: Weight for resource utilization (0.0 to 1.0)
        """
        # Normalize weights to sum to 1.0
        total = performance_weight + load_weight + resource_weight
        if total > 0:
            self.performance_weight = performance_weight / total
            self.load_weight = load_weight / total
            self.resource_weight = resource_weight / total


class ParallelWindowProcessor:
    """
    Processes multiple time windows in parallel with advanced load balancing and resource management.
    
    Features:
    - Thread pool management with configurable worker count
    - Advanced load balancing with multiple algorithms (round-robin, least-loaded, adaptive)
    - Dynamic load rebalancing based on performance metrics
    - Resource monitoring and management (CPU, memory)
    - Result aggregation with proper ordering
    - Intelligent worker selection based on task complexity
    - Error tracking and recovery
    - Progress tracking and cancellation support
    """
    
    def __init__(self, 
                 max_workers: int = 4,
                 enable_load_balancing: bool = True,
                 batch_size: int = 100,
                 memory_limit_mb: int = 500,
                 load_balancing_algorithm: str = "adaptive",
                 resource_monitoring_enabled: bool = True):
        """
        Initialize parallel window processor with enhanced resource management.
        
        Args:
            max_workers: Maximum number of worker threads
            enable_load_balancing: Enable intelligent load balancing
            batch_size: Number of windows to process in each batch
            memory_limit_mb: Memory limit for parallel processing
            load_balancing_algorithm: Algorithm for load balancing ("round_robin", "least_loaded", "adaptive")
            resource_monitoring_enabled: Enable resource monitoring for workers
        """
        self.max_workers = max_workers
        self.enable_load_balancing = enable_load_balancing
        self.batch_size = batch_size
        self.memory_limit_mb = memory_limit_mb
        self.load_balancing_algorithm = load_balancing_algorithm
        self.resource_monitoring_enabled = resource_monitoring_enabled
        
        # Thread pool and load balancer
        self.executor: Optional[ThreadPoolExecutor] = None
        self.load_balancer: Optional[WorkerLoadBalancer] = None
        
        # Processing state
        self.is_processing = False
        self.cancellation_requested = False
        self.progress_callback: Optional[Callable] = None
        
        # Statistics
        self.stats = ParallelProcessingStats()
        self._processing_start_time = 0.0
        
        # Resource management
        self._active_futures: List[Future] = []
        self._completed_results: List[WindowProcessingResult] = []
        self._resource_monitor_thread: Optional[threading.Thread] = None
        self._resource_monitoring_active = False
        
        # Performance optimization
        self.adaptive_batch_sizing = True
        self.min_batch_size = 10
        self.max_batch_size = 500
        self.optimal_batch_size = batch_size
    
    def process_windows_parallel(self, 
                                windows: List[TimeWindow],
                                wing: Wing,
                                window_processor_func: Callable[[TimeWindow, Wing], List[CorrelationMatch]],
                                progress_callback: Optional[Callable] = None) -> List[CorrelationMatch]:
        """
        Process windows in parallel with load balancing and resource management.
        
        Args:
            windows: List of TimeWindow objects to process
            wing: Wing configuration
            window_processor_func: Function to process individual windows
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of all correlation matches found across all windows
        """
        if not windows:
            return []
        
        self.progress_callback = progress_callback
        self.is_processing = True
        self.cancellation_requested = False
        self._processing_start_time = time.time()
        
        try:
            # Initialize thread pool and load balancer
            self._initialize_parallel_processing()
            
            # Create processing tasks
            tasks = self._create_processing_tasks(windows)
            
            # Process tasks in batches with adaptive sizing
            all_matches = []
            total_tasks = len(tasks)
            processed_count = 0
            
            for batch_start in range(0, len(tasks), self.optimal_batch_size):
                if self.cancellation_requested:
                    break
                
                batch_end = min(batch_start + self.optimal_batch_size, len(tasks))
                batch_tasks = tasks[batch_start:batch_end]
                
                # Process batch
                batch_matches = self._process_batch_parallel(batch_tasks, wing, window_processor_func)
                all_matches.extend(batch_matches)
                
                processed_count += len(batch_tasks)
                
                # Report progress with enhanced statistics
                if self.progress_callback:
                    lb_stats = self.load_balancer.get_load_balancing_stats() if self.load_balancer else {}
                    self.progress_callback({
                        'event_type': 'parallel_batch_complete',
                        'windows_processed': processed_count,
                        'total_windows': total_tasks,
                        'matches_found': len(all_matches),
                        'batch_size': len(batch_tasks),
                        'optimal_batch_size': self.optimal_batch_size,
                        'load_balancing_stats': lb_stats,
                        'resource_monitoring_enabled': self.resource_monitoring_enabled,
                        'load_balancing_algorithm': self.load_balancing_algorithm
                    })
            
            # Finalize statistics
            self._finalize_processing_stats(len(all_matches))
            
            return all_matches
            
        finally:
            self._cleanup_parallel_processing()
            self.is_processing = False
    
    def _initialize_parallel_processing(self):
        """Initialize thread pool, load balancer, and resource monitoring"""
        # Create thread pool
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="WindowProcessor"
        )
        
        # Create load balancer if enabled
        if self.enable_load_balancing:
            self.load_balancer = WorkerLoadBalancer(self.max_workers)
            self.load_balancer.set_load_balancing_algorithm(self.load_balancing_algorithm)
            
            # Register workers
            for i in range(self.max_workers):
                worker_id = f"worker_{i}"
                self.load_balancer.register_worker(worker_id)
        
        # Start resource monitoring if enabled
        if self.resource_monitoring_enabled and self.load_balancer:
            self._start_resource_monitoring()
        
        # Reset statistics
        self.stats = ParallelProcessingStats()
        self._active_futures.clear()
        self._completed_results.clear()
    
    def _start_resource_monitoring(self):
        """Start background resource monitoring for workers"""
        if self._resource_monitoring_active:
            return
        
        self._resource_monitoring_active = True
        self._resource_monitor_thread = threading.Thread(
            target=self._resource_monitoring_loop,
            name="ResourceMonitor",
            daemon=True
        )
        self._resource_monitor_thread.start()
    
    def _resource_monitoring_loop(self):
        """Background loop for monitoring worker resource usage"""
        if not PSUTIL_AVAILABLE:
            # Fallback monitoring without psutil
            while self._resource_monitoring_active and not self.cancellation_requested:
                try:
                    # Simple monitoring without detailed resource info
                    if self.load_balancer:
                        # Update with placeholder values
                        for i in range(self.max_workers):
                            worker_id = f"worker_{i}"
                            self.load_balancer.update_worker_resources(worker_id, 0.0, 0.0)
                    
                    time.sleep(5.0)
                except Exception:
                    time.sleep(5.0)
            return
        
        # Full resource monitoring with psutil
        while self._resource_monitoring_active and not self.cancellation_requested:
            try:
                # Get current process and its children (worker threads)
                current_process = psutil.Process()
                
                # Monitor overall process resources
                cpu_percent = current_process.cpu_percent(interval=1.0)
                memory_info = current_process.memory_info()
                memory_mb = memory_info.rss / (1024 * 1024)
                
                # Update load balancer with resource information
                if self.load_balancer:
                    # Distribute resource usage across workers (approximation)
                    per_worker_cpu = cpu_percent / self.max_workers
                    per_worker_memory = memory_mb / self.max_workers
                    
                    for i in range(self.max_workers):
                        worker_id = f"worker_{i}"
                        self.load_balancer.update_worker_resources(
                            worker_id, per_worker_cpu, per_worker_memory
                        )
                
                # Check for resource pressure and adjust batch size
                if self.adaptive_batch_sizing:
                    self._adjust_batch_size_based_on_resources(cpu_percent, memory_mb)
                
                # Sleep before next monitoring cycle
                time.sleep(5.0)  # Monitor every 5 seconds
                
            except Exception as e:
                # Continue monitoring even if there are errors
                time.sleep(5.0)
    
    def _adjust_batch_size_based_on_resources(self, cpu_percent: float, memory_mb: float):
        """
        Dynamically adjust batch size based on resource utilization.
        
        Args:
            cpu_percent: Current CPU usage percentage
            memory_mb: Current memory usage in MB
        """
        # Calculate resource pressure
        memory_pressure = memory_mb / self.memory_limit_mb if self.memory_limit_mb > 0 else 0
        cpu_pressure = cpu_percent / 100.0
        
        # Adjust batch size based on resource pressure
        if memory_pressure > 0.8 or cpu_pressure > 0.9:
            # High resource pressure - reduce batch size
            self.optimal_batch_size = max(self.min_batch_size, int(self.optimal_batch_size * 0.8))
        elif memory_pressure < 0.5 and cpu_pressure < 0.6:
            # Low resource pressure - increase batch size
            self.optimal_batch_size = min(self.max_batch_size, int(self.optimal_batch_size * 1.2))
    
    def _stop_resource_monitoring(self):
        """Stop background resource monitoring"""
        self._resource_monitoring_active = False
        if self._resource_monitor_thread and self._resource_monitor_thread.is_alive():
            self._resource_monitor_thread.join(timeout=2.0)
    
    def _create_processing_tasks(self, windows: List[TimeWindow]) -> List[WindowProcessingTask]:
        """
        Create processing tasks from windows with complexity estimation.
        
        Args:
            windows: List of TimeWindow objects
            
        Returns:
            List of WindowProcessingTask objects
        """
        tasks = []
        
        for i, window in enumerate(windows):
            # Estimate task complexity based on window characteristics
            complexity = self._estimate_window_complexity(window)
            
            task = WindowProcessingTask(
                window=window,
                task_id=f"task_{i:06d}",
                priority=0,  # Could be based on window importance
                estimated_complexity=complexity
            )
            tasks.append(task)
        
        # Sort by priority and complexity for optimal scheduling
        tasks.sort(key=lambda t: (-t.priority, t.estimated_complexity))
        
        return tasks
    
    def _estimate_window_complexity(self, window: TimeWindow) -> float:
        """
        Estimate processing complexity for a window.
        
        Args:
            window: TimeWindow to estimate
            
        Returns:
            Complexity estimate (1.0 = baseline)
        """
        # Base complexity
        complexity = 1.0
        
        # Adjust based on window characteristics
        total_records = window.get_total_record_count()
        if total_records > 0:
            # More records = higher complexity
            complexity += (total_records / 100.0) * 0.1
        
        feather_count = window.get_feather_count()
        if feather_count > 2:
            # More feathers = more cross-correlations = higher complexity
            complexity += (feather_count - 2) * 0.2
        
        return max(0.1, complexity)  # Minimum complexity
    
    def _process_batch_parallel(self, 
                               tasks: List[WindowProcessingTask],
                               wing: Wing,
                               window_processor_func: Callable) -> List[CorrelationMatch]:
        """
        Process a batch of tasks in parallel.
        
        Args:
            tasks: List of WindowProcessingTask objects
            wing: Wing configuration
            window_processor_func: Function to process individual windows
            
        Returns:
            List of correlation matches from the batch
        """
        # Submit tasks to thread pool
        future_to_task = {}
        
        for task in tasks:
            if self.cancellation_requested:
                break
            
            # Get optimal worker if load balancing is enabled
            worker_id = None
            if self.load_balancer:
                worker_id = self.load_balancer.get_optimal_worker(task.estimated_complexity)
                if worker_id:
                    self.load_balancer.update_worker_load(worker_id, task.estimated_complexity)
            
            # Submit task
            future = self.executor.submit(
                self._process_window_with_tracking,
                task,
                wing,
                window_processor_func,
                worker_id
            )
            
            future_to_task[future] = task
            self._active_futures.append(future)
        
        # Collect results as they complete
        batch_matches = []
        
        for future in as_completed(future_to_task.keys()):
            if self.cancellation_requested:
                break
            
            task = future_to_task[future]
            
            try:
                result = future.result()
                self._completed_results.append(result)
                
                # Add matches to batch results
                batch_matches.extend(result.matches)
                
                # Update statistics
                self.stats.total_windows_processed += 1
                self.stats.total_matches_found += len(result.matches)
                self.stats.total_processing_time += result.processing_time_seconds
                
                # Update load balancer with success/failure information
                if self.load_balancer and result.worker_id:
                    self.load_balancer.update_worker_load(result.worker_id, -task.estimated_complexity)
                    self.load_balancer.record_task_completion(
                        result.worker_id, 
                        result.processing_time_seconds,
                        success=(result.error is None)
                    )
                
            except Exception as e:
                # Handle task failure with enhanced error tracking
                error_result = WindowProcessingResult(
                    task_id=task.task_id,
                    window=task.window,
                    matches=[],
                    processing_time_seconds=0.0,
                    error=str(e),
                    worker_id=worker_id
                )
                self._completed_results.append(error_result)
                
                # Update load balancer with failure information
                if self.load_balancer and worker_id:
                    self.load_balancer.update_worker_load(worker_id, -task.estimated_complexity)
                    self.load_balancer.record_task_completion(worker_id, 0.0, success=False)
            
            # Remove from active futures
            if future in self._active_futures:
                self._active_futures.remove(future)
        
        return batch_matches
    
    def _process_window_with_tracking(self, 
                                    task: WindowProcessingTask,
                                    wing: Wing,
                                    window_processor_func: Callable,
                                    worker_id: Optional[str]) -> WindowProcessingResult:
        """
        Process a single window with performance tracking.
        
        Args:
            task: WindowProcessingTask to process
            wing: Wing configuration
            window_processor_func: Function to process the window
            worker_id: ID of the worker processing this task
            
        Returns:
            WindowProcessingResult with matches and performance data
        """
        start_time = time.time()
        
        try:
            # Process the window
            matches = window_processor_func(task.window, wing)
            
            processing_time = time.time() - start_time
            
            return WindowProcessingResult(
                task_id=task.task_id,
                window=task.window,
                matches=matches,
                processing_time_seconds=processing_time,
                worker_id=worker_id
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            
            return WindowProcessingResult(
                task_id=task.task_id,
                window=task.window,
                matches=[],
                processing_time_seconds=processing_time,
                error=str(e),
                worker_id=worker_id
            )
    
    def _finalize_processing_stats(self, total_matches: int):
        """Finalize processing statistics"""
        total_time = time.time() - self._processing_start_time
        
        # Calculate averages
        if self.stats.total_windows_processed > 0:
            self.stats.average_window_time = self.stats.total_processing_time / self.stats.total_windows_processed
        
        # Calculate parallel speedup (estimated)
        sequential_time_estimate = self.stats.total_processing_time
        actual_time = total_time
        if actual_time > 0:
            self.stats.parallel_speedup = sequential_time_estimate / actual_time
        
        # Get load balancing stats
        if self.load_balancer:
            lb_stats = self.load_balancer.get_load_balancing_stats()
            self.stats.load_balancing_efficiency = lb_stats.get('balancing_efficiency', 0.0)
            self.stats.worker_utilization = lb_stats.get('worker_performance_avg', {})
    
    def _cleanup_parallel_processing(self):
        """Cleanup parallel processing resources"""
        # Stop resource monitoring
        self._stop_resource_monitoring()
        
        # Cancel any remaining futures
        for future in self._active_futures:
            future.cancel()
        
        # Shutdown executor
        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None
        
        # Clear state
        self._active_futures.clear()
        self.load_balancer = None
    
    def request_cancellation(self):
        """Request cancellation of parallel processing"""
        self.cancellation_requested = True
        
        # Cancel active futures
        for future in self._active_futures:
            future.cancel()
    
    def get_processing_stats(self) -> ParallelProcessingStats:
        """Get current processing statistics"""
        return self.stats
    
    def is_memory_limit_exceeded(self) -> bool:
        """Check if memory limit is exceeded (placeholder for memory monitoring)"""
        # This would integrate with actual memory monitoring
        # For now, return False as memory management is handled elsewhere
        return False
    
    def get_optimal_worker_count(self, total_windows: int, avg_window_complexity: float = 1.0) -> int:
        """
        Calculate optimal worker count based on workload characteristics.
        
        Args:
            total_windows: Total number of windows to process
            avg_window_complexity: Average complexity per window
            
        Returns:
            Recommended number of workers
        """
        # Base calculation on CPU cores and workload
        import os
        cpu_count = os.cpu_count() or 4
        
        # For I/O bound tasks (database queries), can use more workers than CPU cores
        max_workers = min(cpu_count * 2, 16)  # Cap at 16 workers
        
        # Adjust based on workload
        if total_windows < 50:
            # Small workload - fewer workers to avoid overhead
            return min(2, max_workers)
        elif total_windows < 500:
            # Medium workload - moderate parallelism
            return min(4, max_workers)
        else:
            # Large workload - full parallelism
            return max_workers
    
    def configure_load_balancing(self, 
                               algorithm: str = "adaptive",
                               performance_weight: float = 0.4,
                               load_weight: float = 0.4,
                               resource_weight: float = 0.2):
        """
        Configure load balancing parameters.
        
        Args:
            algorithm: Load balancing algorithm ("round_robin", "least_loaded", "adaptive")
            performance_weight: Weight for historical performance in adaptive algorithm
            load_weight: Weight for current load in adaptive algorithm
            resource_weight: Weight for resource utilization in adaptive algorithm
        """
        self.load_balancing_algorithm = algorithm
        
        if self.load_balancer:
            self.load_balancer.set_load_balancing_algorithm(algorithm)
            if algorithm == "adaptive":
                self.load_balancer.adjust_algorithm_weights(
                    performance_weight, load_weight, resource_weight
                )
    
    def configure_resource_monitoring(self, 
                                    enabled: bool = True,
                                    adaptive_batch_sizing: bool = True,
                                    min_batch_size: int = 10,
                                    max_batch_size: int = 500):
        """
        Configure resource monitoring and adaptive batch sizing.
        
        Args:
            enabled: Enable resource monitoring
            adaptive_batch_sizing: Enable adaptive batch size adjustment
            min_batch_size: Minimum batch size for adaptive sizing
            max_batch_size: Maximum batch size for adaptive sizing
        """
        self.resource_monitoring_enabled = enabled
        self.adaptive_batch_sizing = adaptive_batch_sizing
        self.min_batch_size = min_batch_size
        self.max_batch_size = max_batch_size
        
        # Start or stop resource monitoring based on configuration
        if enabled and not self._resource_monitoring_active and self.is_processing:
            self._start_resource_monitoring()
        elif not enabled and self._resource_monitoring_active:
            self._stop_resource_monitoring()
    
    def get_resource_utilization_stats(self) -> Dict[str, Any]:
        """
        Get current resource utilization statistics.
        
        Returns:
            Dictionary with resource utilization information
        """
        stats = {
            'resource_monitoring_enabled': self.resource_monitoring_enabled,
            'adaptive_batch_sizing': self.adaptive_batch_sizing,
            'current_batch_size': self.optimal_batch_size,
            'min_batch_size': self.min_batch_size,
            'max_batch_size': self.max_batch_size,
            'active_workers': len(self._active_futures),
            'max_workers': self.max_workers
        }
        
        # Add load balancer resource stats if available
        if self.load_balancer:
            lb_stats = self.load_balancer.get_load_balancing_stats()
            stats.update({
                'worker_resource_usage': lb_stats.get('worker_resource_usage', {}),
                'load_balancing_algorithm': lb_stats.get('load_balancing_algorithm', 'unknown'),
                'algorithm_weights': lb_stats.get('algorithm_weights', {}),
                'is_load_imbalanced': lb_stats.get('is_load_imbalanced', False)
            })
        
        # Add system resource information if available
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                stats.update({
                    'system_cpu_percent': process.cpu_percent(),
                    'system_memory_mb': process.memory_info().rss / (1024 * 1024),
                    'memory_limit_mb': self.memory_limit_mb,
                    'memory_utilization_percent': (process.memory_info().rss / (1024 * 1024)) / self.memory_limit_mb * 100 if self.memory_limit_mb > 0 else 0
                })
            except Exception:
                # Error getting system stats
                pass
        else:
            stats['psutil_available'] = False
        
        return stats
    
    def optimize_for_workload(self, total_windows: int, avg_records_per_window: int, available_memory_mb: int):
        """
        Automatically optimize configuration for a specific workload.
        
        Args:
            total_windows: Total number of windows to process
            avg_records_per_window: Average number of records per window
            available_memory_mb: Available memory for processing
        """
        # Optimize worker count
        optimal_workers = self.get_optimal_worker_count(total_windows)
        self.max_workers = min(optimal_workers, self.max_workers)
        
        # Optimize batch size based on memory and workload
        estimated_memory_per_window = avg_records_per_window * 0.001  # Rough estimate: 1KB per record
        max_windows_in_memory = int(available_memory_mb / estimated_memory_per_window) if estimated_memory_per_window > 0 else 1000
        
        # Set batch size to use about 50% of available memory
        optimal_batch_size = max(self.min_batch_size, min(self.max_batch_size, max_windows_in_memory // 2))
        self.optimal_batch_size = optimal_batch_size
        
        # Choose load balancing algorithm based on workload characteristics
        if total_windows < 100:
            # Small workload - simple round robin is sufficient
            self.load_balancing_algorithm = "round_robin"
        elif avg_records_per_window > 1000:
            # High complexity windows - use adaptive algorithm
            self.load_balancing_algorithm = "adaptive"
            # Emphasize performance over load balancing for complex tasks
            if self.load_balancer:
                self.load_balancer.adjust_algorithm_weights(0.6, 0.3, 0.1)
        else:
            # Medium workload - least loaded algorithm
            self.load_balancing_algorithm = "least_loaded"