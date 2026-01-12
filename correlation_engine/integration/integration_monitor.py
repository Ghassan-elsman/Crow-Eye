"""
Integration Monitor and Diagnostics

Provides comprehensive monitoring and diagnostics for all integration points
including performance monitoring, logging, and troubleshooting tools.
"""

import logging
import time
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from collections import defaultdict, deque
import traceback

logger = logging.getLogger(__name__)


class MonitoringLevel(Enum):
    """Monitoring detail levels"""
    BASIC = "basic"           # Basic performance metrics
    DETAILED = "detailed"     # Detailed operation tracking
    VERBOSE = "verbose"       # Verbose logging with full context
    DEBUG = "debug"          # Debug level with all internal operations


class PerformanceMetric(Enum):
    """Types of performance metrics"""
    EXECUTION_TIME = "execution_time"
    MEMORY_USAGE = "memory_usage"
    CPU_USAGE = "cpu_usage"
    OPERATION_COUNT = "operation_count"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    LATENCY = "latency"


@dataclass
class PerformanceData:
    """Performance measurement data"""
    metric: PerformanceMetric
    value: float
    timestamp: datetime = field(default_factory=datetime.now)
    component: str = ""
    operation: str = ""
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationTrace:
    """Trace of an operation execution"""
    operation_id: str
    component: str
    operation_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    input_size: Optional[int] = None
    output_size: Optional[int] = None
    memory_delta_mb: Optional[float] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check"""
    check_name: str
    component: str
    status: str  # "healthy", "warning", "error"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    recommendations: List[str] = field(default_factory=list)


class IntegrationMonitor:
    """
    Comprehensive monitoring and diagnostics for integration components.
    
    Provides:
    - Performance monitoring for semantic mapping and scoring operations
    - Operation tracing and profiling
    - Resource usage monitoring
    - Diagnostic checks and health monitoring
    - Troubleshooting tools and recommendations
    """
    
    def __init__(self, monitoring_level: MonitoringLevel = MonitoringLevel.BASIC,
                 enable_performance_monitoring: bool = True,
                 enable_operation_tracing: bool = True,
                 max_trace_history: int = 1000):
        """
        Initialize integration monitor.
        
        Args:
            monitoring_level: Level of monitoring detail
            enable_performance_monitoring: Enable performance metric collection
            enable_operation_tracing: Enable operation tracing
            max_trace_history: Maximum number of operation traces to keep
        """
        self.monitoring_level = monitoring_level
        self.enable_performance_monitoring = enable_performance_monitoring
        self.enable_operation_tracing = enable_operation_tracing
        self.max_trace_history = max_trace_history
        
        # Performance data storage
        self.performance_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.operation_traces: deque = deque(maxlen=max_trace_history)
        
        # Active operations tracking
        self.active_operations: Dict[str, OperationTrace] = {}
        self.operation_counter = 0
        self.lock = threading.Lock()
        
        # Component statistics
        self.component_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'total_operations': 0,
            'successful_operations': 0,
            'failed_operations': 0,
            'total_execution_time': 0.0,
            'average_execution_time': 0.0,
            'peak_memory_usage': 0.0,
            'last_operation_time': None
        })
        
        # System resource monitoring
        self.system_monitor_active = False
        self.system_monitor_thread = None
        self.system_metrics: deque = deque(maxlen=100)
        
        # Diagnostic checks
        self.diagnostic_checks: Dict[str, Callable] = {
            'semantic_mapping_health': self._check_semantic_mapping_health,
            'weighted_scoring_health': self._check_weighted_scoring_health,
            'progress_tracking_health': self._check_progress_tracking_health,
            'memory_usage': self._check_memory_usage,
            'performance_degradation': self._check_performance_degradation,
            'error_rate': self._check_error_rate
        }
        
        logger.info(f"IntegrationMonitor initialized (level={monitoring_level.value}, "
                   f"performance={enable_performance_monitoring}, tracing={enable_operation_tracing})")
    
    def start_system_monitoring(self, interval_seconds: float = 5.0):
        """
        Start system resource monitoring in background thread.
        
        Args:
            interval_seconds: Monitoring interval in seconds
        """
        if self.system_monitor_active:
            logger.warning("System monitoring already active")
            return
        
        self.system_monitor_active = True
        self.system_monitor_thread = threading.Thread(
            target=self._system_monitor_loop,
            args=(interval_seconds,),
            daemon=True
        )
        self.system_monitor_thread.start()
        logger.info(f"Started system monitoring (interval={interval_seconds}s)")
    
    def stop_system_monitoring(self):
        """Stop system resource monitoring"""
        self.system_monitor_active = False
        if self.system_monitor_thread:
            self.system_monitor_thread.join(timeout=1.0)
        logger.info("Stopped system monitoring")
    
    def _system_monitor_loop(self, interval_seconds: float):
        """System monitoring loop (runs in background thread)"""
        while self.system_monitor_active:
            try:
                # Collect system metrics
                cpu_percent = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                
                system_data = {
                    'timestamp': datetime.now(),
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_used_mb': memory.used / (1024 * 1024),
                    'memory_available_mb': memory.available / (1024 * 1024)
                }
                
                self.system_metrics.append(system_data)
                
                # Log warnings for high resource usage
                if cpu_percent > 80:
                    logger.warning(f"High CPU usage: {cpu_percent:.1f}%")
                
                if memory.percent > 85:
                    logger.warning(f"High memory usage: {memory.percent:.1f}% ({memory.used / (1024**3):.1f}GB)")
                
                time.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"Error in system monitoring loop: {e}")
                time.sleep(interval_seconds)
    
    def start_operation(self, component: str, operation_name: str, 
                       context: Dict[str, Any] = None, input_size: int = None) -> str:
        """
        Start monitoring an operation.
        
        Args:
            component: Component name (e.g., "semantic_mapping", "weighted_scoring")
            operation_name: Name of the operation
            context: Additional context information
            input_size: Size of input data (e.g., number of records)
            
        Returns:
            Operation ID for tracking
        """
        if not self.enable_operation_tracing:
            return ""
        
        with self.lock:
            self.operation_counter += 1
            operation_id = f"{component}_{operation_name}_{self.operation_counter}_{int(time.time())}"
        
        # Record memory usage before operation
        memory_before = None
        if self.enable_performance_monitoring:
            try:
                process = psutil.Process()
                memory_before = process.memory_info().rss / (1024 * 1024)  # MB
            except:
                pass
        
        operation_trace = OperationTrace(
            operation_id=operation_id,
            component=component,
            operation_name=operation_name,
            start_time=datetime.now(),
            input_size=input_size,
            context=context or {}
        )
        
        # Store memory baseline
        if memory_before is not None:
            operation_trace.context['memory_before_mb'] = memory_before
        
        self.active_operations[operation_id] = operation_trace
        
        if self.monitoring_level in [MonitoringLevel.VERBOSE, MonitoringLevel.DEBUG]:
            logger.debug(f"Started operation {operation_id}: {component}.{operation_name}")
        
        return operation_id
    
    def complete_operation(self, operation_id: str, success: bool = True, 
                          error_message: str = None, output_size: int = None):
        """
        Complete monitoring an operation.
        
        Args:
            operation_id: Operation ID from start_operation
            success: Whether operation was successful
            error_message: Error message if operation failed
            output_size: Size of output data
        """
        if not operation_id or operation_id not in self.active_operations:
            return
        
        operation_trace = self.active_operations.pop(operation_id)
        operation_trace.end_time = datetime.now()
        operation_trace.success = success
        operation_trace.error_message = error_message
        operation_trace.output_size = output_size
        
        # Calculate duration
        duration = operation_trace.end_time - operation_trace.start_time
        operation_trace.duration_ms = duration.total_seconds() * 1000
        
        # Record memory usage after operation
        if self.enable_performance_monitoring:
            try:
                process = psutil.Process()
                memory_after = process.memory_info().rss / (1024 * 1024)  # MB
                memory_before = operation_trace.context.get('memory_before_mb', 0)
                operation_trace.memory_delta_mb = memory_after - memory_before
            except:
                pass
        
        # Store completed trace
        self.operation_traces.append(operation_trace)
        
        # Update component statistics
        self._update_component_stats(operation_trace)
        
        # Record performance metrics
        if self.enable_performance_monitoring:
            self._record_performance_metrics(operation_trace)
        
        if self.monitoring_level in [MonitoringLevel.VERBOSE, MonitoringLevel.DEBUG]:
            status = "SUCCESS" if success else "FAILED"
            logger.debug(f"Completed operation {operation_id}: {status} in {operation_trace.duration_ms:.1f}ms")
        
        # Log warnings for slow operations
        if operation_trace.duration_ms > 5000:  # 5 seconds
            logger.warning(f"Slow operation detected: {operation_trace.component}.{operation_trace.operation_name} "
                          f"took {operation_trace.duration_ms:.1f}ms")
        
        # Log warnings for high memory usage
        if operation_trace.memory_delta_mb and operation_trace.memory_delta_mb > 100:  # 100MB
            logger.warning(f"High memory usage: {operation_trace.component}.{operation_trace.operation_name} "
                          f"used {operation_trace.memory_delta_mb:.1f}MB")
    
    def _update_component_stats(self, operation_trace: OperationTrace):
        """Update statistics for a component"""
        component = operation_trace.component
        stats = self.component_stats[component]
        
        stats['total_operations'] += 1
        stats['last_operation_time'] = operation_trace.end_time
        
        if operation_trace.success:
            stats['successful_operations'] += 1
        else:
            stats['failed_operations'] += 1
        
        if operation_trace.duration_ms:
            stats['total_execution_time'] += operation_trace.duration_ms
            stats['average_execution_time'] = (
                stats['total_execution_time'] / stats['total_operations']
            )
        
        if operation_trace.memory_delta_mb and operation_trace.memory_delta_mb > stats['peak_memory_usage']:
            stats['peak_memory_usage'] = operation_trace.memory_delta_mb
    
    def _record_performance_metrics(self, operation_trace: OperationTrace):
        """Record performance metrics from operation trace"""
        component = operation_trace.component
        
        # Execution time metric
        if operation_trace.duration_ms:
            self.performance_data[f"{component}_execution_time"].append(
                PerformanceData(
                    metric=PerformanceMetric.EXECUTION_TIME,
                    value=operation_trace.duration_ms,
                    component=component,
                    operation=operation_trace.operation_name,
                    context={'operation_id': operation_trace.operation_id}
                )
            )
        
        # Memory usage metric
        if operation_trace.memory_delta_mb:
            self.performance_data[f"{component}_memory_usage"].append(
                PerformanceData(
                    metric=PerformanceMetric.MEMORY_USAGE,
                    value=operation_trace.memory_delta_mb,
                    component=component,
                    operation=operation_trace.operation_name,
                    context={'operation_id': operation_trace.operation_id}
                )
            )
        
        # Throughput metric (if input/output sizes available)
        if operation_trace.input_size and operation_trace.duration_ms:
            throughput = operation_trace.input_size / (operation_trace.duration_ms / 1000)  # items per second
            self.performance_data[f"{component}_throughput"].append(
                PerformanceData(
                    metric=PerformanceMetric.THROUGHPUT,
                    value=throughput,
                    component=component,
                    operation=operation_trace.operation_name,
                    context={'operation_id': operation_trace.operation_id}
                )
            )
    
    def record_semantic_mapping_metrics(self, operation_name: str, 
                                      records_processed: int, 
                                      mappings_applied: int,
                                      execution_time_ms: float,
                                      memory_usage_mb: float = None):
        """
        Record semantic mapping specific metrics.
        
        Args:
            operation_name: Name of the semantic mapping operation
            records_processed: Number of records processed
            mappings_applied: Number of mappings applied
            execution_time_ms: Execution time in milliseconds
            memory_usage_mb: Memory usage in MB
        """
        if not self.enable_performance_monitoring:
            return
        
        component = "semantic_mapping"
        timestamp = datetime.now()
        
        # Record execution time
        self.performance_data[f"{component}_execution_time"].append(
            PerformanceData(
                metric=PerformanceMetric.EXECUTION_TIME,
                value=execution_time_ms,
                timestamp=timestamp,
                component=component,
                operation=operation_name,
                context={
                    'records_processed': records_processed,
                    'mappings_applied': mappings_applied
                }
            )
        )
        
        # Record throughput
        if execution_time_ms > 0:
            throughput = records_processed / (execution_time_ms / 1000)
            self.performance_data[f"{component}_throughput"].append(
                PerformanceData(
                    metric=PerformanceMetric.THROUGHPUT,
                    value=throughput,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name,
                    context={'records_per_second': throughput}
                )
            )
        
        # Record memory usage
        if memory_usage_mb:
            self.performance_data[f"{component}_memory_usage"].append(
                PerformanceData(
                    metric=PerformanceMetric.MEMORY_USAGE,
                    value=memory_usage_mb,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name
                )
            )
        
        # Record mapping efficiency
        if records_processed > 0:
            mapping_rate = mappings_applied / records_processed
            self.performance_data[f"{component}_mapping_rate"].append(
                PerformanceData(
                    metric=PerformanceMetric.OPERATION_COUNT,
                    value=mapping_rate,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name,
                    context={'mapping_efficiency': mapping_rate}
                )
            )
        
        if self.monitoring_level in [MonitoringLevel.DETAILED, MonitoringLevel.VERBOSE, MonitoringLevel.DEBUG]:
            logger.info(f"Semantic mapping metrics: {operation_name} - "
                       f"{records_processed} records, {mappings_applied} mappings, "
                       f"{execution_time_ms:.1f}ms")
    
    def record_weighted_scoring_metrics(self, operation_name: str,
                                      matches_scored: int,
                                      scores_calculated: int,
                                      execution_time_ms: float,
                                      average_score: float = None,
                                      memory_usage_mb: float = None):
        """
        Record weighted scoring specific metrics.
        
        Args:
            operation_name: Name of the scoring operation
            matches_scored: Number of matches scored
            scores_calculated: Number of successful score calculations
            execution_time_ms: Execution time in milliseconds
            average_score: Average score calculated
            memory_usage_mb: Memory usage in MB
        """
        if not self.enable_performance_monitoring:
            return
        
        component = "weighted_scoring"
        timestamp = datetime.now()
        
        # Record execution time
        self.performance_data[f"{component}_execution_time"].append(
            PerformanceData(
                metric=PerformanceMetric.EXECUTION_TIME,
                value=execution_time_ms,
                timestamp=timestamp,
                component=component,
                operation=operation_name,
                context={
                    'matches_scored': matches_scored,
                    'scores_calculated': scores_calculated
                }
            )
        )
        
        # Record throughput
        if execution_time_ms > 0:
            throughput = matches_scored / (execution_time_ms / 1000)
            self.performance_data[f"{component}_throughput"].append(
                PerformanceData(
                    metric=PerformanceMetric.THROUGHPUT,
                    value=throughput,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name,
                    context={'matches_per_second': throughput}
                )
            )
        
        # Record success rate
        if matches_scored > 0:
            success_rate = scores_calculated / matches_scored
            self.performance_data[f"{component}_success_rate"].append(
                PerformanceData(
                    metric=PerformanceMetric.OPERATION_COUNT,
                    value=success_rate,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name,
                    context={'scoring_success_rate': success_rate}
                )
            )
        
        # Record average score
        if average_score is not None:
            self.performance_data[f"{component}_average_score"].append(
                PerformanceData(
                    metric=PerformanceMetric.OPERATION_COUNT,
                    value=average_score,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name,
                    context={'score_quality': average_score}
                )
            )
        
        # Record memory usage
        if memory_usage_mb:
            self.performance_data[f"{component}_memory_usage"].append(
                PerformanceData(
                    metric=PerformanceMetric.MEMORY_USAGE,
                    value=memory_usage_mb,
                    timestamp=timestamp,
                    component=component,
                    operation=operation_name
                )
            )
        
        if self.monitoring_level in [MonitoringLevel.DETAILED, MonitoringLevel.VERBOSE, MonitoringLevel.DEBUG]:
            logger.info(f"Weighted scoring metrics: {operation_name} - "
                       f"{matches_scored} matches, {scores_calculated} scores, "
                       f"{execution_time_ms:.1f}ms, avg_score={average_score:.3f}")
    
    def run_diagnostics(self, components: List[str] = None) -> List[DiagnosticResult]:
        """
        Run diagnostic checks on integration components.
        
        Args:
            components: List of components to check (None for all)
            
        Returns:
            List of diagnostic results
        """
        results = []
        
        checks_to_run = self.diagnostic_checks.keys()
        if components:
            checks_to_run = [check for check in checks_to_run 
                           if any(comp in check for comp in components)]
        
        for check_name in checks_to_run:
            try:
                check_func = self.diagnostic_checks[check_name]
                result = check_func()
                results.append(result)
                
                if result.status == "error":
                    logger.error(f"Diagnostic check failed: {check_name} - {result.message}")
                elif result.status == "warning":
                    logger.warning(f"Diagnostic warning: {check_name} - {result.message}")
                else:
                    logger.info(f"Diagnostic check passed: {check_name}")
                    
            except Exception as e:
                error_result = DiagnosticResult(
                    check_name=check_name,
                    component="monitor",
                    status="error",
                    message=f"Diagnostic check failed with exception: {str(e)}",
                    details={'exception': str(e), 'traceback': traceback.format_exc()}
                )
                results.append(error_result)
                logger.error(f"Diagnostic check exception: {check_name} - {e}")
        
        return results
    
    def _check_semantic_mapping_health(self) -> DiagnosticResult:
        """Check semantic mapping component health"""
        component = "semantic_mapping"
        stats = self.component_stats.get(component, {})
        
        total_ops = stats.get('total_operations', 0)
        failed_ops = stats.get('failed_operations', 0)
        
        if total_ops == 0:
            return DiagnosticResult(
                check_name="semantic_mapping_health",
                component=component,
                status="warning",
                message="No semantic mapping operations recorded",
                recommendations=["Verify semantic mapping integration is active"]
            )
        
        error_rate = failed_ops / total_ops if total_ops > 0 else 0
        
        if error_rate > 0.1:  # More than 10% error rate
            return DiagnosticResult(
                check_name="semantic_mapping_health",
                component=component,
                status="error",
                message=f"High error rate: {error_rate:.1%} ({failed_ops}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'failed_operations': failed_ops},
                recommendations=[
                    "Check semantic mapping configuration files",
                    "Verify semantic mapping patterns are valid",
                    "Review error logs for specific failure causes"
                ]
            )
        elif error_rate > 0.05:  # More than 5% error rate
            return DiagnosticResult(
                check_name="semantic_mapping_health",
                component=component,
                status="warning",
                message=f"Moderate error rate: {error_rate:.1%} ({failed_ops}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'failed_operations': failed_ops},
                recommendations=[
                    "Monitor semantic mapping errors",
                    "Consider updating semantic mapping patterns"
                ]
            )
        else:
            return DiagnosticResult(
                check_name="semantic_mapping_health",
                component=component,
                status="healthy",
                message=f"Semantic mapping healthy: {error_rate:.1%} error rate ({total_ops} operations)",
                details={'error_rate': error_rate, 'total_operations': total_ops}
            )
    
    def _check_weighted_scoring_health(self) -> DiagnosticResult:
        """Check weighted scoring component health"""
        component = "weighted_scoring"
        stats = self.component_stats.get(component, {})
        
        total_ops = stats.get('total_operations', 0)
        failed_ops = stats.get('failed_operations', 0)
        
        if total_ops == 0:
            return DiagnosticResult(
                check_name="weighted_scoring_health",
                component=component,
                status="warning",
                message="No weighted scoring operations recorded",
                recommendations=["Verify weighted scoring integration is active"]
            )
        
        error_rate = failed_ops / total_ops if total_ops > 0 else 0
        
        if error_rate > 0.1:  # More than 10% error rate
            return DiagnosticResult(
                check_name="weighted_scoring_health",
                component=component,
                status="error",
                message=f"High error rate: {error_rate:.1%} ({failed_ops}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'failed_operations': failed_ops},
                recommendations=[
                    "Check weighted scoring configuration",
                    "Verify scoring weights are valid",
                    "Review scoring engine initialization"
                ]
            )
        elif error_rate > 0.05:  # More than 5% error rate
            return DiagnosticResult(
                check_name="weighted_scoring_health",
                component=component,
                status="warning",
                message=f"Moderate error rate: {error_rate:.1%} ({failed_ops}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'failed_operations': failed_ops},
                recommendations=[
                    "Monitor weighted scoring errors",
                    "Consider adjusting scoring configuration"
                ]
            )
        else:
            return DiagnosticResult(
                check_name="weighted_scoring_health",
                component=component,
                status="healthy",
                message=f"Weighted scoring healthy: {error_rate:.1%} error rate ({total_ops} operations)",
                details={'error_rate': error_rate, 'total_operations': total_ops}
            )
    
    def _check_progress_tracking_health(self) -> DiagnosticResult:
        """Check progress tracking component health"""
        component = "progress_tracking"
        stats = self.component_stats.get(component, {})
        
        total_ops = stats.get('total_operations', 0)
        failed_ops = stats.get('failed_operations', 0)
        
        if total_ops == 0:
            return DiagnosticResult(
                check_name="progress_tracking_health",
                component=component,
                status="warning",
                message="No progress tracking operations recorded",
                recommendations=["Verify progress tracking integration is active"]
            )
        
        error_rate = failed_ops / total_ops if total_ops > 0 else 0
        
        if error_rate > 0.05:  # More than 5% error rate (lower threshold for progress tracking)
            return DiagnosticResult(
                check_name="progress_tracking_health",
                component=component,
                status="error",
                message=f"High error rate: {error_rate:.1%} ({failed_ops}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'failed_operations': failed_ops},
                recommendations=[
                    "Check progress tracking listeners",
                    "Verify GUI widget connections",
                    "Review progress event handling"
                ]
            )
        else:
            return DiagnosticResult(
                check_name="progress_tracking_health",
                component=component,
                status="healthy",
                message=f"Progress tracking healthy: {error_rate:.1%} error rate ({total_ops} operations)",
                details={'error_rate': error_rate, 'total_operations': total_ops}
            )
    
    def _check_memory_usage(self) -> DiagnosticResult:
        """Check system memory usage"""
        try:
            memory = psutil.virtual_memory()
            
            if memory.percent > 90:
                return DiagnosticResult(
                    check_name="memory_usage",
                    component="system",
                    status="error",
                    message=f"Critical memory usage: {memory.percent:.1f}% ({memory.used / (1024**3):.1f}GB used)",
                    details={'memory_percent': memory.percent, 'memory_used_gb': memory.used / (1024**3)},
                    recommendations=[
                        "Consider enabling streaming mode",
                        "Reduce correlation window size",
                        "Close unnecessary applications"
                    ]
                )
            elif memory.percent > 80:
                return DiagnosticResult(
                    check_name="memory_usage",
                    component="system",
                    status="warning",
                    message=f"High memory usage: {memory.percent:.1f}% ({memory.used / (1024**3):.1f}GB used)",
                    details={'memory_percent': memory.percent, 'memory_used_gb': memory.used / (1024**3)},
                    recommendations=[
                        "Monitor memory usage closely",
                        "Consider enabling streaming mode for large datasets"
                    ]
                )
            else:
                return DiagnosticResult(
                    check_name="memory_usage",
                    component="system",
                    status="healthy",
                    message=f"Memory usage normal: {memory.percent:.1f}% ({memory.used / (1024**3):.1f}GB used)",
                    details={'memory_percent': memory.percent, 'memory_used_gb': memory.used / (1024**3)}
                )
                
        except Exception as e:
            return DiagnosticResult(
                check_name="memory_usage",
                component="system",
                status="error",
                message=f"Failed to check memory usage: {str(e)}",
                details={'exception': str(e)}
            )
    
    def _check_performance_degradation(self) -> DiagnosticResult:
        """Check for performance degradation"""
        # Check recent execution times vs historical averages
        recent_threshold = datetime.now() - timedelta(minutes=10)
        
        performance_issues = []
        
        for component, stats in self.component_stats.items():
            avg_time = stats.get('average_execution_time', 0)
            if avg_time == 0:
                continue
            
            # Get recent operations for this component
            recent_ops = [trace for trace in self.operation_traces 
                         if trace.component == component and trace.end_time and trace.end_time > recent_threshold]
            
            if len(recent_ops) < 3:  # Need at least 3 recent operations
                continue
            
            recent_avg = sum(op.duration_ms for op in recent_ops) / len(recent_ops)
            
            # Check if recent average is significantly higher than historical average
            if recent_avg > avg_time * 2:  # 100% slower
                performance_issues.append({
                    'component': component,
                    'historical_avg': avg_time,
                    'recent_avg': recent_avg,
                    'degradation_factor': recent_avg / avg_time
                })
        
        if performance_issues:
            worst_issue = max(performance_issues, key=lambda x: x['degradation_factor'])
            
            return DiagnosticResult(
                check_name="performance_degradation",
                component="system",
                status="warning",
                message=f"Performance degradation detected in {worst_issue['component']}: "
                       f"{worst_issue['degradation_factor']:.1f}x slower than average",
                details={'performance_issues': performance_issues},
                recommendations=[
                    "Check system resource usage",
                    "Review recent configuration changes",
                    "Consider restarting the application"
                ]
            )
        else:
            return DiagnosticResult(
                check_name="performance_degradation",
                component="system",
                status="healthy",
                message="No significant performance degradation detected"
            )
    
    def _check_error_rate(self) -> DiagnosticResult:
        """Check overall error rate across all components"""
        total_ops = sum(stats.get('total_operations', 0) for stats in self.component_stats.values())
        total_errors = sum(stats.get('failed_operations', 0) for stats in self.component_stats.values())
        
        if total_ops == 0:
            return DiagnosticResult(
                check_name="error_rate",
                component="system",
                status="warning",
                message="No operations recorded across any components"
            )
        
        error_rate = total_errors / total_ops
        
        if error_rate > 0.1:  # More than 10% error rate
            return DiagnosticResult(
                check_name="error_rate",
                component="system",
                status="error",
                message=f"High overall error rate: {error_rate:.1%} ({total_errors}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'total_errors': total_errors},
                recommendations=[
                    "Review error logs for common failure patterns",
                    "Check configuration files",
                    "Consider running individual component diagnostics"
                ]
            )
        elif error_rate > 0.05:  # More than 5% error rate
            return DiagnosticResult(
                check_name="error_rate",
                component="system",
                status="warning",
                message=f"Moderate overall error rate: {error_rate:.1%} ({total_errors}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'total_errors': total_errors},
                recommendations=[
                    "Monitor error trends",
                    "Review component-specific error rates"
                ]
            )
        else:
            return DiagnosticResult(
                check_name="error_rate",
                component="system",
                status="healthy",
                message=f"Overall error rate acceptable: {error_rate:.1%} ({total_errors}/{total_ops})",
                details={'error_rate': error_rate, 'total_operations': total_ops, 'total_errors': total_errors}
            )
    
    def get_performance_summary(self, component: str = None, 
                              time_window_minutes: int = 60) -> Dict[str, Any]:
        """
        Get performance summary for components.
        
        Args:
            component: Specific component to analyze (None for all)
            time_window_minutes: Time window for analysis
            
        Returns:
            Performance summary dictionary
        """
        cutoff_time = datetime.now() - timedelta(minutes=time_window_minutes)
        
        summary = {
            'time_window_minutes': time_window_minutes,
            'components': {},
            'system_metrics': self._get_system_metrics_summary(cutoff_time)
        }
        
        components_to_analyze = [component] if component else self.component_stats.keys()
        
        for comp in components_to_analyze:
            comp_summary = {
                'statistics': self.component_stats.get(comp, {}),
                'recent_operations': [],
                'performance_metrics': {}
            }
            
            # Get recent operations
            recent_ops = [trace for trace in self.operation_traces 
                         if trace.component == comp and trace.end_time and trace.end_time > cutoff_time]
            
            comp_summary['recent_operations'] = len(recent_ops)
            
            if recent_ops:
                # Calculate recent performance metrics
                durations = [op.duration_ms for op in recent_ops if op.duration_ms]
                if durations:
                    comp_summary['performance_metrics']['avg_duration_ms'] = sum(durations) / len(durations)
                    comp_summary['performance_metrics']['max_duration_ms'] = max(durations)
                    comp_summary['performance_metrics']['min_duration_ms'] = min(durations)
                
                memory_deltas = [op.memory_delta_mb for op in recent_ops if op.memory_delta_mb]
                if memory_deltas:
                    comp_summary['performance_metrics']['avg_memory_delta_mb'] = sum(memory_deltas) / len(memory_deltas)
                    comp_summary['performance_metrics']['max_memory_delta_mb'] = max(memory_deltas)
                
                success_count = sum(1 for op in recent_ops if op.success)
                comp_summary['performance_metrics']['success_rate'] = success_count / len(recent_ops)
            
            summary['components'][comp] = comp_summary
        
        return summary
    
    def _get_system_metrics_summary(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Get system metrics summary"""
        recent_metrics = [m for m in self.system_metrics if m['timestamp'] > cutoff_time]
        
        if not recent_metrics:
            return {'message': 'No recent system metrics available'}
        
        cpu_values = [m['cpu_percent'] for m in recent_metrics]
        memory_values = [m['memory_percent'] for m in recent_metrics]
        
        return {
            'samples': len(recent_metrics),
            'cpu': {
                'avg': sum(cpu_values) / len(cpu_values),
                'max': max(cpu_values),
                'min': min(cpu_values)
            },
            'memory': {
                'avg': sum(memory_values) / len(memory_values),
                'max': max(memory_values),
                'min': min(memory_values)
            }
        }
    
    def export_monitoring_report(self, file_path: Optional[Path] = None) -> str:
        """
        Export comprehensive monitoring report.
        
        Args:
            file_path: Optional path to save report
            
        Returns:
            JSON string with monitoring report
        """
        report = {
            'timestamp': datetime.now().isoformat(),
            'monitoring_config': {
                'level': self.monitoring_level.value,
                'performance_monitoring': self.enable_performance_monitoring,
                'operation_tracing': self.enable_operation_tracing,
                'max_trace_history': self.max_trace_history
            },
            'component_statistics': dict(self.component_stats),
            'performance_summary': self.get_performance_summary(),
            'diagnostic_results': [
                {
                    'check_name': result.check_name,
                    'component': result.component,
                    'status': result.status,
                    'message': result.message,
                    'timestamp': result.timestamp.isoformat(),
                    'recommendations': result.recommendations
                }
                for result in self.run_diagnostics()
            ],
            'recent_operations': [
                {
                    'operation_id': trace.operation_id,
                    'component': trace.component,
                    'operation_name': trace.operation_name,
                    'duration_ms': trace.duration_ms,
                    'success': trace.success,
                    'timestamp': trace.start_time.isoformat()
                }
                for trace in list(self.operation_traces)[-20:]  # Last 20 operations
            ]
        }
        
        report_json = json.dumps(report, indent=2)
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(report_json)
                logger.info(f"Monitoring report exported to {file_path}")
            except Exception as e:
                logger.error(f"Failed to export monitoring report: {e}")
        
        return report_json
    
    def get_troubleshooting_recommendations(self, component: str = None) -> List[str]:
        """
        Get troubleshooting recommendations based on current state.
        
        Args:
            component: Specific component to get recommendations for
            
        Returns:
            List of troubleshooting recommendations
        """
        recommendations = []
        
        # Run diagnostics to get current issues
        diagnostic_results = self.run_diagnostics([component] if component else None)
        
        # Collect recommendations from diagnostic results
        for result in diagnostic_results:
            if result.status in ['warning', 'error']:
                recommendations.extend(result.recommendations)
        
        # Add general recommendations based on statistics
        if component:
            stats = self.component_stats.get(component, {})
            error_rate = (stats.get('failed_operations', 0) / 
                         max(1, stats.get('total_operations', 1)))
            
            if error_rate > 0.1:
                recommendations.append(f"High error rate in {component}: Review error logs and configuration")
            
            avg_time = stats.get('average_execution_time', 0)
            if avg_time > 5000:  # 5 seconds
                recommendations.append(f"Slow performance in {component}: Consider optimization or resource allocation")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recommendations.append(rec)
        
        return unique_recommendations
    
    def cleanup(self):
        """Cleanup monitoring resources"""
        self.stop_system_monitoring()
        
        # Clear data structures
        self.performance_data.clear()
        self.operation_traces.clear()
        self.active_operations.clear()
        self.component_stats.clear()
        self.system_metrics.clear()
        
        logger.info("Integration monitor cleanup completed")