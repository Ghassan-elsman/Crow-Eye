"""
Performance Monitoring and Metrics Collection for Time-Window Scanning Engine

Provides detailed performance metrics collection, timing for each phase,
memory usage tracking, and performance comparison capabilities.
"""

import time
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum


class ProcessingPhase(Enum):
    """Enumeration of processing phases for timing."""
    INITIALIZATION = "initialization"
    FEATHER_LOADING = "feather_loading"
    TIME_RANGE_DETERMINATION = "time_range_determination"
    WINDOW_GENERATION = "window_generation"
    WINDOW_QUERYING = "window_querying"
    CORRELATION = "correlation"
    SCORING = "scoring"
    RESULT_PROCESSING = "result_processing"
    CLEANUP = "cleanup"
    TOTAL_EXECUTION = "total_execution"


@dataclass
class PhaseMetrics:
    """Metrics for a single processing phase."""
    phase: ProcessingPhase
    start_time: float
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    memory_start_mb: Optional[float] = None
    memory_end_mb: Optional[float] = None
    memory_delta_mb: Optional[float] = None
    records_processed: int = 0
    operations_count: int = 0
    error_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def complete(self, memory_mb: Optional[float] = None, 
                records_processed: int = 0, operations_count: int = 0):
        """Complete the phase timing and calculate metrics."""
        self.end_time = time.time()
        self.duration_seconds = self.end_time - self.start_time
        self.records_processed = records_processed
        self.operations_count = operations_count
        
        if memory_mb is not None:
            self.memory_end_mb = memory_mb
            if self.memory_start_mb is not None:
                self.memory_delta_mb = self.memory_end_mb - self.memory_start_mb


@dataclass
class WindowMetrics:
    """Performance metrics for a single time window."""
    window_id: str
    window_start_time: datetime
    window_end_time: datetime
    processing_start: float
    processing_end: Optional[float] = None
    processing_duration: Optional[float] = None
    
    # Query metrics
    query_start: Optional[float] = None
    query_duration: Optional[float] = None
    feathers_queried: int = 0
    total_records_found: int = 0
    records_by_feather: Dict[str, int] = field(default_factory=dict)
    
    # Correlation metrics
    correlation_start: Optional[float] = None
    correlation_duration: Optional[float] = None
    matches_created: int = 0
    semantic_comparisons: int = 0
    
    # Scoring metrics
    scoring_start: Optional[float] = None
    scoring_duration: Optional[float] = None
    scores_calculated: int = 0
    
    # Memory metrics
    memory_before_mb: Optional[float] = None
    memory_after_mb: Optional[float] = None
    memory_peak_mb: Optional[float] = None
    
    def complete_processing(self):
        """Complete window processing timing."""
        if self.processing_start:
            self.processing_end = time.time()
            self.processing_duration = self.processing_end - self.processing_start


@dataclass
class PerformanceComparison:
    """Performance comparison between different engines or runs."""
    engine_name: str
    execution_time_seconds: float
    memory_peak_mb: float
    records_processed: int
    matches_found: int
    windows_processed: int
    
    # Efficiency metrics
    records_per_second: float = 0.0
    matches_per_second: float = 0.0
    windows_per_second: float = 0.0
    memory_per_1k_records_mb: float = 0.0
    
    def __post_init__(self):
        """Calculate efficiency metrics."""
        if self.execution_time_seconds > 0:
            self.records_per_second = self.records_processed / self.execution_time_seconds
            self.matches_per_second = self.matches_found / self.execution_time_seconds
            self.windows_per_second = self.windows_processed / self.execution_time_seconds
        
        if self.records_processed > 0:
            self.memory_per_1k_records_mb = (self.memory_peak_mb / self.records_processed) * 1000


@dataclass
class PerformanceReport:
    """Comprehensive performance report."""
    engine_name: str
    execution_start: datetime
    execution_end: Optional[datetime] = None
    total_duration_seconds: Optional[float] = None
    
    # Phase timing breakdown
    phase_metrics: Dict[ProcessingPhase, PhaseMetrics] = field(default_factory=dict)
    
    # Window-level metrics
    window_metrics: List[WindowMetrics] = field(default_factory=list)
    
    # Overall statistics
    total_windows_processed: int = 0
    total_records_processed: int = 0
    total_matches_found: int = 0
    total_feathers_processed: int = 0
    
    # Memory statistics
    baseline_memory_mb: float = 0.0
    peak_memory_mb: float = 0.0
    average_memory_mb: float = 0.0
    memory_efficiency_mb_per_1k_records: float = 0.0
    
    # Performance rates
    windows_per_second: float = 0.0
    records_per_second: float = 0.0
    matches_per_second: float = 0.0
    
    # Error and warning counts
    error_count: int = 0
    warning_count: int = 0
    
    # Configuration metadata
    configuration: Dict[str, Any] = field(default_factory=dict)
    
    def finalize(self):
        """Finalize the performance report with calculated metrics."""
        if self.execution_start and not self.execution_end:
            self.execution_end = datetime.now()
        
        if self.execution_end and self.execution_start:
            self.total_duration_seconds = (self.execution_end - self.execution_start).total_seconds()
        
        # Calculate performance rates
        if self.total_duration_seconds and self.total_duration_seconds > 0:
            self.windows_per_second = self.total_windows_processed / self.total_duration_seconds
            self.records_per_second = self.total_records_processed / self.total_duration_seconds
            self.matches_per_second = self.total_matches_found / self.total_duration_seconds
        
        # Calculate memory efficiency
        if self.total_records_processed > 0:
            self.memory_efficiency_mb_per_1k_records = (self.peak_memory_mb / self.total_records_processed) * 1000


class PerformanceMonitor:
    """
    Comprehensive performance monitoring system for Time-Window Scanning Engine.
    
    Features:
    - Phase-by-phase timing collection
    - Memory usage tracking and reporting
    - Window-level performance metrics
    - Performance comparison capabilities
    - Real-time monitoring with minimal overhead
    - Thread-safe operation for parallel processing
    """
    
    def __init__(self, engine_name: str = "TimeWindowScanningEngine", 
                 enable_detailed_monitoring: bool = True,
                 memory_sampling_interval: float = 1.0):
        """
        Initialize performance monitor.
        
        Args:
            engine_name: Name of the engine being monitored
            enable_detailed_monitoring: Enable detailed window-level monitoring
            memory_sampling_interval: Interval for memory sampling in seconds
        """
        self.engine_name = engine_name
        self.enable_detailed_monitoring = enable_detailed_monitoring
        self.memory_sampling_interval = memory_sampling_interval
        
        # Current performance report
        self.current_report: Optional[PerformanceReport] = None
        
        # Active phase tracking
        self.active_phases: Dict[ProcessingPhase, PhaseMetrics] = {}
        
        # Window metrics tracking
        self.active_windows: Dict[str, WindowMetrics] = {}
        
        # Memory monitoring
        self.memory_samples: deque = deque(maxlen=1000)  # Keep last 1000 samples
        self.memory_monitoring_active = False
        self.memory_monitor_thread: Optional[threading.Thread] = None
        
        # Performance history for comparison
        self.performance_history: List[PerformanceReport] = []
        
        # Thread safety - use RLock for reentrant locking
        self._lock = threading.RLock()
        
        # Baseline memory
        self.baseline_memory_mb = self._get_current_memory_usage()
        
        print(f"[PerformanceMonitor] Initialized for {engine_name}")
        print(f"[PerformanceMonitor] Baseline memory: {self.baseline_memory_mb:.1f}MB")
    
    def start_execution(self, configuration: Dict[str, Any] = None) -> PerformanceReport:
        """
        Start monitoring a new execution.
        
        Args:
            configuration: Engine configuration for metadata
            
        Returns:
            PerformanceReport object for this execution
        """
        with self._lock:
            # Finalize previous report if exists
            if self.current_report:
                self.current_report.finalize()
                self.performance_history.append(self.current_report)
            
            # Create new performance report
            self.current_report = PerformanceReport(
                engine_name=self.engine_name,
                execution_start=datetime.now(),
                baseline_memory_mb=self.baseline_memory_mb,
                configuration=configuration or {}
            )
            
            # Clear active tracking
            self.active_phases.clear()
            self.active_windows.clear()
            
            # Start memory monitoring (non-blocking, with error handling)
            try:
                self._start_memory_monitoring()
            except Exception as e:
                print(f"[PerformanceMonitor] Warning: Memory monitoring disabled: {e}")
            
            # Start total execution timing
            self.start_phase(ProcessingPhase.TOTAL_EXECUTION)
            
            return self.current_report
    
    def complete_execution(self) -> PerformanceReport:
        """
        Complete execution monitoring and finalize report.
        
        Returns:
            Finalized PerformanceReport
        """
        with self._lock:
            if not self.current_report:
                raise RuntimeError("No active execution to complete")
            
            # Complete total execution timing
            self.complete_phase(ProcessingPhase.TOTAL_EXECUTION)
            
            # Stop memory monitoring
            self._stop_memory_monitoring()
            
            # Finalize report
            self.current_report.finalize()
            
            # Calculate final memory statistics
            if self.memory_samples:
                memory_values = [sample['memory_mb'] for sample in self.memory_samples]
                self.current_report.peak_memory_mb = max(memory_values)
                self.current_report.average_memory_mb = sum(memory_values) / len(memory_values)
            
            print(f"[PerformanceMonitor] Execution monitoring complete")
            print(f"[PerformanceMonitor] Total duration: {self.current_report.total_duration_seconds:.2f}s")
            print(f"[PerformanceMonitor] Peak memory: {self.current_report.peak_memory_mb:.1f}MB")
            
            return self.current_report
    
    def start_phase(self, phase: ProcessingPhase, metadata: Dict[str, Any] = None) -> PhaseMetrics:
        """
        Start timing a processing phase.
        
        Args:
            phase: Processing phase to start timing
            metadata: Optional metadata for the phase
            
        Returns:
            PhaseMetrics object for this phase
        """
        current_memory = self._get_current_memory_usage()
        
        phase_metrics = PhaseMetrics(
            phase=phase,
            start_time=time.time(),
            memory_start_mb=current_memory,
            metadata=metadata or {}
        )
        
        with self._lock:
            self.active_phases[phase] = phase_metrics
            
            if self.current_report:
                self.current_report.phase_metrics[phase] = phase_metrics
        
        return phase_metrics
    
    def complete_phase(self, phase: ProcessingPhase, 
                      records_processed: int = 0, 
                      operations_count: int = 0,
                      error_count: int = 0) -> PhaseMetrics:
        """
        Complete timing for a processing phase.
        
        Args:
            phase: Processing phase to complete
            records_processed: Number of records processed in this phase
            operations_count: Number of operations performed
            error_count: Number of errors encountered
            
        Returns:
            Completed PhaseMetrics object
        """
        current_memory = self._get_current_memory_usage()
        
        with self._lock:
            if phase not in self.active_phases:
                raise ValueError(f"Phase {phase} was not started")
            
            phase_metrics = self.active_phases[phase]
            phase_metrics.complete(
                memory_mb=current_memory,
                records_processed=records_processed,
                operations_count=operations_count
            )
            phase_metrics.error_count = error_count
            
            # Remove from active phases
            del self.active_phases[phase]
            
            # Update report totals
            if self.current_report:
                if phase != ProcessingPhase.TOTAL_EXECUTION:
                    self.current_report.total_records_processed += records_processed
                    self.current_report.error_count += error_count
        
        return phase_metrics
    
    def start_window_processing(self, window_id: str, 
                               window_start_time: datetime,
                               window_end_time: datetime) -> Optional[WindowMetrics]:
        """
        Start monitoring a time window processing.
        
        Args:
            window_id: Unique identifier for the window
            window_start_time: Start time of the window
            window_end_time: End time of the window
            
        Returns:
            WindowMetrics object if detailed monitoring enabled
        """
        if not self.enable_detailed_monitoring:
            return None
        
        current_memory = self._get_current_memory_usage()
        
        window_metrics = WindowMetrics(
            window_id=window_id,
            window_start_time=window_start_time,
            window_end_time=window_end_time,
            processing_start=time.time(),
            memory_before_mb=current_memory
        )
        
        with self._lock:
            self.active_windows[window_id] = window_metrics
        
        return window_metrics
    
    def complete_window_processing(self, window_id: str,
                                  records_found: int = 0,
                                  matches_created: int = 0,
                                  feathers_queried: int = 0) -> Optional[WindowMetrics]:
        """
        Complete monitoring for a time window.
        
        Args:
            window_id: Window identifier
            records_found: Total records found in window
            matches_created: Number of matches created
            feathers_queried: Number of feathers queried
            
        Returns:
            Completed WindowMetrics object if detailed monitoring enabled
        """
        if not self.enable_detailed_monitoring:
            return None
        
        current_memory = self._get_current_memory_usage()
        
        with self._lock:
            if window_id not in self.active_windows:
                return None
            
            window_metrics = self.active_windows[window_id]
            window_metrics.complete_processing()
            window_metrics.memory_after_mb = current_memory
            window_metrics.total_records_found = records_found
            window_metrics.matches_created = matches_created
            window_metrics.feathers_queried = feathers_queried
            
            # Update peak memory for this window
            if window_metrics.memory_before_mb and window_metrics.memory_after_mb:
                window_metrics.memory_peak_mb = max(
                    window_metrics.memory_before_mb, 
                    window_metrics.memory_after_mb
                )
            
            # Add to report
            if self.current_report:
                self.current_report.window_metrics.append(window_metrics)
                self.current_report.total_windows_processed += 1
                self.current_report.total_matches_found += matches_created
            
            # Remove from active windows
            del self.active_windows[window_id]
        
        return window_metrics
    
    def record_query_timing(self, window_id: str, duration_seconds: float, 
                           feather_id: str, records_found: int):
        """
        Record query timing for a specific feather in a window.
        
        Args:
            window_id: Window identifier
            duration_seconds: Query duration
            feather_id: Feather that was queried
            records_found: Number of records found
        """
        if not self.enable_detailed_monitoring:
            return
        
        with self._lock:
            if window_id in self.active_windows:
                window_metrics = self.active_windows[window_id]
                
                # Update query metrics
                if window_metrics.query_start is None:
                    window_metrics.query_start = time.time() - duration_seconds
                
                if window_metrics.query_duration is None:
                    window_metrics.query_duration = 0.0
                window_metrics.query_duration += duration_seconds
                
                window_metrics.records_by_feather[feather_id] = records_found
                window_metrics.feathers_queried += 1
    
    def record_correlation_timing(self, window_id: str, duration_seconds: float,
                                 semantic_comparisons: int = 0):
        """
        Record correlation timing for a window.
        
        Args:
            window_id: Window identifier
            duration_seconds: Correlation duration
            semantic_comparisons: Number of semantic comparisons performed
        """
        if not self.enable_detailed_monitoring:
            return
        
        with self._lock:
            if window_id in self.active_windows:
                window_metrics = self.active_windows[window_id]
                window_metrics.correlation_duration = duration_seconds
                window_metrics.semantic_comparisons = semantic_comparisons
    
    def record_scoring_timing(self, window_id: str, duration_seconds: float,
                             scores_calculated: int = 0):
        """
        Record scoring timing for a window.
        
        Args:
            window_id: Window identifier
            duration_seconds: Scoring duration
            scores_calculated: Number of scores calculated
        """
        if not self.enable_detailed_monitoring:
            return
        
        with self._lock:
            if window_id in self.active_windows:
                window_metrics = self.active_windows[window_id]
                window_metrics.scoring_duration = duration_seconds
                window_metrics.scores_calculated = scores_calculated
    
    def get_current_performance_summary(self) -> Dict[str, Any]:
        """
        Get current performance summary.
        
        Returns:
            Dictionary with current performance metrics
        """
        with self._lock:
            if not self.current_report:
                return {}
            
            # Calculate current rates
            current_time = datetime.now()
            elapsed_seconds = (current_time - self.current_report.execution_start).total_seconds()
            
            summary = {
                'engine_name': self.engine_name,
                'execution_start': self.current_report.execution_start.isoformat(),
                'elapsed_seconds': elapsed_seconds,
                'windows_processed': self.current_report.total_windows_processed,
                'records_processed': self.current_report.total_records_processed,
                'matches_found': self.current_report.total_matches_found,
                'current_memory_mb': self._get_current_memory_usage(),
                'peak_memory_mb': self.current_report.peak_memory_mb,
                'baseline_memory_mb': self.current_report.baseline_memory_mb
            }
            
            # Add performance rates if we have elapsed time
            if elapsed_seconds > 0:
                summary.update({
                    'windows_per_second': self.current_report.total_windows_processed / elapsed_seconds,
                    'records_per_second': self.current_report.total_records_processed / elapsed_seconds,
                    'matches_per_second': self.current_report.total_matches_found / elapsed_seconds
                })
            
            # Add phase timing summary
            phase_summary = {}
            for phase, metrics in self.current_report.phase_metrics.items():
                if metrics.duration_seconds is not None:
                    phase_summary[phase.value] = {
                        'duration_seconds': metrics.duration_seconds,
                        'records_processed': metrics.records_processed,
                        'operations_count': metrics.operations_count,
                        'memory_delta_mb': metrics.memory_delta_mb
                    }
            summary['phase_timing'] = phase_summary
            
            return summary
    
    def compare_with_baseline(self, baseline_engine_name: str = "AnchorBasedEngine",
                             baseline_metrics: Dict[str, Any] = None) -> PerformanceComparison:
        """
        Compare current performance with baseline engine.
        
        Args:
            baseline_engine_name: Name of baseline engine
            baseline_metrics: Baseline performance metrics
            
        Returns:
            PerformanceComparison object
        """
        if not self.current_report:
            raise RuntimeError("No current execution to compare")
        
        # Create comparison for current engine
        current_comparison = PerformanceComparison(
            engine_name=self.engine_name,
            execution_time_seconds=self.current_report.total_duration_seconds or 0,
            memory_peak_mb=self.current_report.peak_memory_mb,
            records_processed=self.current_report.total_records_processed,
            matches_found=self.current_report.total_matches_found,
            windows_processed=self.current_report.total_windows_processed
        )
        
        # Create baseline comparison if metrics provided
        if baseline_metrics:
            baseline_comparison = PerformanceComparison(
                engine_name=baseline_engine_name,
                execution_time_seconds=baseline_metrics.get('execution_time_seconds', 0),
                memory_peak_mb=baseline_metrics.get('memory_peak_mb', 0),
                records_processed=baseline_metrics.get('records_processed', 0),
                matches_found=baseline_metrics.get('matches_found', 0),
                windows_processed=baseline_metrics.get('windows_processed', 0)
            )
            
            # Calculate improvement factors
            improvements = {}
            if baseline_comparison.execution_time_seconds > 0:
                improvements['speed_improvement'] = (
                    baseline_comparison.execution_time_seconds / 
                    max(current_comparison.execution_time_seconds, 0.001)
                )
            
            if baseline_comparison.memory_peak_mb > 0:
                improvements['memory_efficiency'] = (
                    baseline_comparison.memory_peak_mb / 
                    max(current_comparison.memory_peak_mb, 0.001)
                )
            
            current_comparison.metadata = {
                'baseline_comparison': baseline_comparison,
                'improvements': improvements
            }
        
        return current_comparison
    
    def get_detailed_report(self) -> Dict[str, Any]:
        """
        Get detailed performance report.
        
        Returns:
            Comprehensive performance report dictionary
        """
        with self._lock:
            if not self.current_report:
                return {}
            
            report = {
                'engine_name': self.engine_name,
                'execution_summary': {
                    'start_time': self.current_report.execution_start.isoformat(),
                    'end_time': self.current_report.execution_end.isoformat() if self.current_report.execution_end else None,
                    'total_duration_seconds': self.current_report.total_duration_seconds,
                    'windows_processed': self.current_report.total_windows_processed,
                    'records_processed': self.current_report.total_records_processed,
                    'matches_found': self.current_report.total_matches_found,
                    'feathers_processed': self.current_report.total_feathers_processed
                },
                'performance_rates': {
                    'windows_per_second': self.current_report.windows_per_second,
                    'records_per_second': self.current_report.records_per_second,
                    'matches_per_second': self.current_report.matches_per_second
                },
                'memory_statistics': {
                    'baseline_mb': self.current_report.baseline_memory_mb,
                    'peak_mb': self.current_report.peak_memory_mb,
                    'average_mb': self.current_report.average_memory_mb,
                    'efficiency_mb_per_1k_records': self.current_report.memory_efficiency_mb_per_1k_records
                },
                'phase_breakdown': {},
                'configuration': self.current_report.configuration,
                'error_count': self.current_report.error_count,
                'warning_count': self.current_report.warning_count
            }
            
            # Add phase breakdown
            for phase, metrics in self.current_report.phase_metrics.items():
                if metrics.duration_seconds is not None:
                    report['phase_breakdown'][phase.value] = {
                        'duration_seconds': metrics.duration_seconds,
                        'percentage_of_total': (
                            (metrics.duration_seconds / self.current_report.total_duration_seconds * 100)
                            if self.current_report.total_duration_seconds else 0
                        ),
                        'records_processed': metrics.records_processed,
                        'operations_count': metrics.operations_count,
                        'memory_start_mb': metrics.memory_start_mb,
                        'memory_end_mb': metrics.memory_end_mb,
                        'memory_delta_mb': metrics.memory_delta_mb,
                        'error_count': metrics.error_count,
                        'metadata': metrics.metadata
                    }
            
            # Add window-level statistics if detailed monitoring enabled
            if self.enable_detailed_monitoring and self.current_report.window_metrics:
                window_durations = [w.processing_duration for w in self.current_report.window_metrics 
                                  if w.processing_duration is not None]
                
                if window_durations:
                    report['window_statistics'] = {
                        'total_windows': len(self.current_report.window_metrics),
                        'average_window_duration': sum(window_durations) / len(window_durations),
                        'min_window_duration': min(window_durations),
                        'max_window_duration': max(window_durations),
                        'windows_with_matches': len([w for w in self.current_report.window_metrics if w.matches_created > 0]),
                        'average_records_per_window': (
                            sum(w.total_records_found for w in self.current_report.window_metrics) / 
                            len(self.current_report.window_metrics)
                        )
                    }
            
            return report
    
    def _start_memory_monitoring(self):
        """Start background memory monitoring thread."""
        if self.memory_monitoring_active:
            return
        
        self.memory_monitoring_active = True
        try:
            self.memory_monitor_thread = threading.Thread(
                target=self._memory_monitoring_loop,
                daemon=True,
                name="PerformanceMonitor-MemoryThread"
            )
            self.memory_monitor_thread.start()
        except Exception as e:
            print(f"[PerformanceMonitor] Failed to start memory monitoring thread: {e}")
            self.memory_monitoring_active = False
    
    def _stop_memory_monitoring(self):
        """Stop background memory monitoring."""
        self.memory_monitoring_active = False
        if self.memory_monitor_thread:
            self.memory_monitor_thread.join(timeout=2.0)
            self.memory_monitor_thread = None
    
    def _memory_monitoring_loop(self):
        """Background memory monitoring loop."""
        while self.memory_monitoring_active:
            try:
                memory_mb = self._get_current_memory_usage()
                timestamp = time.time()
                
                sample = {
                    'timestamp': timestamp,
                    'memory_mb': memory_mb,
                    'datetime': datetime.fromtimestamp(timestamp)
                }
                
                self.memory_samples.append(sample)
                
                # Update peak memory in current report
                if self.current_report:
                    self.current_report.peak_memory_mb = max(
                        self.current_report.peak_memory_mb, 
                        memory_mb
                    )
                
                time.sleep(self.memory_sampling_interval)
                
            except Exception as e:
                print(f"[PerformanceMonitor] Memory monitoring error: {e}")
                time.sleep(self.memory_sampling_interval)
    
    def _get_current_memory_usage(self) -> float:
        """Get current process memory usage in MB."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            return memory_info.rss / (1024 * 1024)  # Convert bytes to MB
        except Exception:
            return 0.0
    
    def export_performance_data(self, filepath: str):
        """
        Export performance data to file.
        
        Args:
            filepath: Path to export file (JSON format)
        """
        import json
        
        export_data = {
            'engine_name': self.engine_name,
            'export_timestamp': datetime.now().isoformat(),
            'current_report': self.get_detailed_report(),
            'performance_history': [
                {
                    'execution_start': report.execution_start.isoformat(),
                    'total_duration_seconds': report.total_duration_seconds,
                    'windows_processed': report.total_windows_processed,
                    'records_processed': report.total_records_processed,
                    'matches_found': report.total_matches_found,
                    'peak_memory_mb': report.peak_memory_mb,
                    'configuration': report.configuration
                }
                for report in self.performance_history
            ]
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        print(f"[PerformanceMonitor] Performance data exported to {filepath}")


# Context manager for easy phase timing
class PhaseTimer:
    """Context manager for timing processing phases."""
    
    def __init__(self, monitor: PerformanceMonitor, phase: ProcessingPhase, 
                 metadata: Dict[str, Any] = None):
        self.monitor = monitor
        self.phase = phase
        self.metadata = metadata
        self.records_processed = 0
        self.operations_count = 0
        self.error_count = 0
    
    def __enter__(self):
        self.monitor.start_phase(self.phase, self.metadata)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error_count += 1
        
        self.monitor.complete_phase(
            self.phase,
            records_processed=self.records_processed,
            operations_count=self.operations_count,
            error_count=self.error_count
        )
    
    def add_records(self, count: int):
        """Add to records processed count."""
        self.records_processed += count
    
    def add_operations(self, count: int):
        """Add to operations count."""
        self.operations_count += count
    
    def add_error(self):
        """Increment error count."""
        self.error_count += 1


# Utility functions for performance monitoring
def create_performance_monitor(engine_name: str = "TimeWindowScanningEngine",
                              enable_detailed: bool = True) -> PerformanceMonitor:
    """
    Create a performance monitor with standard configuration.
    
    Args:
        engine_name: Name of the engine
        enable_detailed: Enable detailed window-level monitoring
        
    Returns:
        Configured PerformanceMonitor instance
    """
    return PerformanceMonitor(
        engine_name=engine_name,
        enable_detailed_monitoring=enable_detailed,
        memory_sampling_interval=1.0
    )


def benchmark_engines(time_window_engine_func, anchor_engine_func, 
                     test_data: Dict[str, Any]) -> Dict[str, PerformanceComparison]:
    """
    Benchmark time-window scanning engine against anchor-based engine.
    
    Args:
        time_window_engine_func: Function that runs time-window engine
        anchor_engine_func: Function that runs anchor-based engine
        test_data: Test data configuration
        
    Returns:
        Dictionary with performance comparisons
    """
    results = {}
    
    # Benchmark time-window engine
    tw_monitor = create_performance_monitor("TimeWindowScanningEngine")
    tw_report = tw_monitor.start_execution(test_data)
    
    try:
        tw_result = time_window_engine_func(test_data)
        tw_monitor.complete_execution()
        
        results['time_window'] = PerformanceComparison(
            engine_name="TimeWindowScanningEngine",
            execution_time_seconds=tw_report.total_duration_seconds or 0,
            memory_peak_mb=tw_report.peak_memory_mb,
            records_processed=tw_report.total_records_processed,
            matches_found=tw_report.total_matches_found,
            windows_processed=tw_report.total_windows_processed
        )
    except Exception as e:
        print(f"Time-window engine benchmark failed: {e}")
    
    # Benchmark anchor-based engine
    anchor_monitor = create_performance_monitor("AnchorBasedEngine")
    anchor_report = anchor_monitor.start_execution(test_data)
    
    try:
        anchor_result = anchor_engine_func(test_data)
        anchor_monitor.complete_execution()
        
        results['anchor_based'] = PerformanceComparison(
            engine_name="AnchorBasedEngine",
            execution_time_seconds=anchor_report.total_duration_seconds or 0,
            memory_peak_mb=anchor_report.peak_memory_mb,
            records_processed=anchor_report.total_records_processed,
            matches_found=anchor_report.total_matches_found,
            windows_processed=0  # Anchor-based doesn't use windows
        )
    except Exception as e:
        print(f"Anchor-based engine benchmark failed: {e}")
    
    return results