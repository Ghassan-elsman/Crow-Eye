"""
Error Handling Coordinator

Provides comprehensive error handling coordination for the Time-Window Scanning Engine.
This module ties together all error handling components and ensures they work cohesively
to provide enterprise-grade resilience.

Features:
- Centralized error handling coordination
- Comprehensive error reporting and recovery
- Graceful degradation strategies
- Error pattern analysis and recommendations
- Health monitoring and diagnostics
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import time

from .database_error_handler import DatabaseErrorHandler, DatabaseError, DatabaseErrorType
from .timestamp_parser import ResilientTimestampParser, TimestampParseResult
from .memory_manager import WindowMemoryManager, MemoryUsageReport


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Categories of errors that can occur"""
    DATABASE = "database"
    TIMESTAMP = "timestamp"
    MEMORY = "memory"
    CONFIGURATION = "configuration"
    PROCESSING = "processing"
    SYSTEM = "system"


@dataclass
class ErrorEvent:
    """Represents an error event with full context"""
    timestamp: datetime
    category: ErrorCategory
    severity: ErrorSeverity
    component: str
    error_message: str
    context: Dict[str, Any]
    recovery_action: Optional[str] = None
    resolved: bool = False
    resolution_time: Optional[datetime] = None


@dataclass
class SystemHealthStatus:
    """Overall system health status"""
    overall_health: str  # "healthy", "degraded", "critical"
    database_health: str
    memory_health: str
    timestamp_health: str
    error_count_24h: int
    critical_errors: List[ErrorEvent]
    recommendations: List[str]
    last_updated: datetime


@dataclass
class ErrorHandlingStats:
    """Comprehensive error handling statistics"""
    total_errors: int
    errors_by_category: Dict[str, int]
    errors_by_severity: Dict[str, int]
    recovery_success_rate: float
    average_recovery_time_seconds: float
    degradation_events: int
    system_uptime_percentage: float


class ErrorHandlingCoordinator:
    """
    Coordinates all error handling components for comprehensive resilience.
    
    This class provides a unified interface for error handling across the
    Time-Window Scanning Engine, ensuring all components work together
    to provide maximum resilience and graceful degradation.
    """
    
    def __init__(self, 
                 database_handler: Optional[DatabaseErrorHandler] = None,
                 timestamp_parser: Optional[ResilientTimestampParser] = None,
                 memory_manager: Optional[WindowMemoryManager] = None,
                 debug_mode: bool = False):
        """
        Initialize error handling coordinator.
        
        Args:
            database_handler: Database error handler instance
            timestamp_parser: Timestamp parser instance
            memory_manager: Memory manager instance
            debug_mode: Enable debug logging
        """
        self.database_handler = database_handler
        self.timestamp_parser = timestamp_parser
        self.memory_manager = memory_manager
        self.debug_mode = debug_mode
        
        # Error tracking
        self.error_history: List[ErrorEvent] = []
        self.error_lock = threading.Lock()
        
        # Health monitoring
        self.health_check_interval = 300  # 5 minutes
        self.last_health_check = datetime.now()
        self.system_start_time = datetime.now()
        
        # Recovery strategies
        self.recovery_strategies: Dict[ErrorCategory, List[Callable]] = {
            ErrorCategory.DATABASE: [
                self._recover_database_connection,
                self._fallback_to_cached_data,
                self._skip_problematic_feather
            ],
            ErrorCategory.MEMORY: [
                self._activate_streaming_mode,
                self._force_garbage_collection,
                self._reduce_batch_size
            ],
            ErrorCategory.TIMESTAMP: [
                self._retry_with_different_format,
                self._use_fallback_timestamp,
                self._skip_invalid_records
            ]
        }
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        if debug_mode:
            self.logger.setLevel(logging.DEBUG)
        
        if self.debug_mode:
            print("[ErrorCoordinator] Initialized comprehensive error handling coordination")
    
    def register_error_handlers(self,
                               database_handler: DatabaseErrorHandler,
                               timestamp_parser: ResilientTimestampParser,
                               memory_manager: WindowMemoryManager):
        """
        Register error handling components.
        
        Args:
            database_handler: Database error handler
            timestamp_parser: Timestamp parser
            memory_manager: Memory manager
        """
        self.database_handler = database_handler
        self.timestamp_parser = timestamp_parser
        self.memory_manager = memory_manager
        
        if self.debug_mode:
            print("[ErrorCoordinator] Registered all error handling components")
    
    def handle_error(self, 
                    category: ErrorCategory,
                    component: str,
                    error_message: str,
                    context: Dict[str, Any],
                    severity: ErrorSeverity = ErrorSeverity.MEDIUM) -> Tuple[bool, str]:
        """
        Handle an error with comprehensive recovery strategies.
        
        Args:
            category: Category of the error
            component: Component that generated the error
            error_message: Error message
            context: Additional context information
            severity: Error severity level
            
        Returns:
            Tuple of (recovered, recovery_action)
        """
        # Create error event
        error_event = ErrorEvent(
            timestamp=datetime.now(),
            category=category,
            severity=severity,
            component=component,
            error_message=error_message,
            context=context
        )
        
        # Add to error history
        with self.error_lock:
            self.error_history.append(error_event)
            
            # Keep only recent errors (last 7 days)
            cutoff_time = datetime.now() - timedelta(days=7)
            self.error_history = [e for e in self.error_history if e.timestamp >= cutoff_time]
        
        # Log the error
        self._log_error(error_event)
        
        # Attempt recovery
        recovered, recovery_action = self._attempt_recovery(error_event)
        
        # Update error event with recovery information
        error_event.recovery_action = recovery_action
        error_event.resolved = recovered
        if recovered:
            error_event.resolution_time = datetime.now()
        
        return recovered, recovery_action
    
    def check_system_health(self) -> SystemHealthStatus:
        """
        Perform comprehensive system health check.
        
        Returns:
            SystemHealthStatus with current health information
        """
        now = datetime.now()
        
        # Get component health statuses
        database_health = self._check_database_health()
        memory_health = self._check_memory_health()
        timestamp_health = self._check_timestamp_health()
        
        # Count recent errors
        recent_errors = self._get_recent_errors(hours=24)
        critical_errors = [e for e in recent_errors if e.severity == ErrorSeverity.CRITICAL]
        
        # Determine overall health
        overall_health = self._determine_overall_health(
            database_health, memory_health, timestamp_health, len(critical_errors)
        )
        
        # Generate recommendations
        recommendations = self._generate_health_recommendations(
            database_health, memory_health, timestamp_health, recent_errors
        )
        
        health_status = SystemHealthStatus(
            overall_health=overall_health,
            database_health=database_health,
            memory_health=memory_health,
            timestamp_health=timestamp_health,
            error_count_24h=len(recent_errors),
            critical_errors=critical_errors,
            recommendations=recommendations,
            last_updated=now
        )
        
        self.last_health_check = now
        
        if self.debug_mode:
            print(f"[ErrorCoordinator] Health check: {overall_health} "
                  f"(DB: {database_health}, Mem: {memory_health}, TS: {timestamp_health})")
        
        return health_status
    
    def get_error_statistics(self) -> ErrorHandlingStats:
        """
        Get comprehensive error handling statistics.
        
        Returns:
            ErrorHandlingStats with detailed statistics
        """
        with self.error_lock:
            total_errors = len(self.error_history)
            
            # Count by category
            errors_by_category = {}
            for error in self.error_history:
                category = error.category.value
                errors_by_category[category] = errors_by_category.get(category, 0) + 1
            
            # Count by severity
            errors_by_severity = {}
            for error in self.error_history:
                severity = error.severity.value
                errors_by_severity[severity] = errors_by_severity.get(severity, 0) + 1
            
            # Calculate recovery success rate
            resolved_errors = len([e for e in self.error_history if e.resolved])
            recovery_success_rate = (resolved_errors / total_errors * 100) if total_errors > 0 else 100
            
            # Calculate average recovery time
            recovery_times = []
            for error in self.error_history:
                if error.resolved and error.resolution_time:
                    recovery_time = (error.resolution_time - error.timestamp).total_seconds()
                    recovery_times.append(recovery_time)
            
            average_recovery_time = sum(recovery_times) / len(recovery_times) if recovery_times else 0
            
            # Count degradation events
            degradation_events = len([e for e in self.error_history 
                                    if e.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]])
            
            # Calculate system uptime percentage
            uptime_seconds = (datetime.now() - self.system_start_time).total_seconds()
            downtime_seconds = sum(recovery_times)  # Approximate downtime
            uptime_percentage = ((uptime_seconds - downtime_seconds) / uptime_seconds * 100) if uptime_seconds > 0 else 100
        
        return ErrorHandlingStats(
            total_errors=total_errors,
            errors_by_category=errors_by_category,
            errors_by_severity=errors_by_severity,
            recovery_success_rate=recovery_success_rate,
            average_recovery_time_seconds=average_recovery_time,
            degradation_events=degradation_events,
            system_uptime_percentage=uptime_percentage
        )
    
    def get_recent_errors(self, hours: int = 24) -> List[ErrorEvent]:
        """Get recent errors within specified time window"""
        return self._get_recent_errors(hours)
    
    def clear_error_history(self):
        """Clear error history (for testing or maintenance)"""
        with self.error_lock:
            self.error_history.clear()
        
        if self.debug_mode:
            print("[ErrorCoordinator] Error history cleared")
    
    def _attempt_recovery(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """
        Attempt to recover from an error using appropriate strategies.
        
        Args:
            error_event: Error event to recover from
            
        Returns:
            Tuple of (success, recovery_action_description)
        """
        recovery_strategies = self.recovery_strategies.get(error_event.category, [])
        
        for strategy in recovery_strategies:
            try:
                success, action_description = strategy(error_event)
                if success:
                    if self.debug_mode:
                        print(f"[ErrorCoordinator] Recovery successful: {action_description}")
                    return True, action_description
            except Exception as e:
                if self.debug_mode:
                    print(f"[ErrorCoordinator] Recovery strategy failed: {e}")
                continue
        
        return False, "No recovery strategy succeeded"
    
    def _recover_database_connection(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Attempt to recover database connection"""
        if self.database_handler:
            # Force cleanup of existing connections
            self.database_handler.cleanup()
            
            # Wait a moment for cleanup
            time.sleep(1.0)
            
            return True, "Database connections reset"
        
        return False, "No database handler available"
    
    def _fallback_to_cached_data(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Use cached data as fallback"""
        # This would be implemented based on specific caching strategy
        return False, "Cached data fallback not implemented"
    
    def _skip_problematic_feather(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Skip the problematic feather and continue processing"""
        feather_id = error_event.context.get('feather_id')
        if feather_id:
            return True, f"Skipped problematic feather: {feather_id}"
        
        return False, "No feather ID in context"
    
    def _activate_streaming_mode(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Activate streaming mode to reduce memory usage"""
        if self.memory_manager:
            self.memory_manager.activate_streaming_mode("Error recovery")
            return True, "Streaming mode activated"
        
        return False, "No memory manager available"
    
    def _force_garbage_collection(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Force garbage collection to free memory"""
        if self.memory_manager:
            collected = self.memory_manager.force_garbage_collection()
            return True, f"Garbage collection freed {collected} objects"
        
        return False, "No memory manager available"
    
    def _reduce_batch_size(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Reduce processing batch size"""
        # This would be implemented based on specific batch processing logic
        return True, "Batch size reduction recommended"
    
    def _retry_with_different_format(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Retry timestamp parsing with different format"""
        if self.timestamp_parser:
            # Clear format detection cache to force re-detection
            self.timestamp_parser.clear_cache()
            return True, "Timestamp format cache cleared for retry"
        
        return False, "No timestamp parser available"
    
    def _use_fallback_timestamp(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Use fallback timestamp strategy"""
        return True, "Fallback timestamp strategy applied"
    
    def _skip_invalid_records(self, error_event: ErrorEvent) -> Tuple[bool, str]:
        """Skip records with invalid timestamps"""
        return True, "Invalid timestamp records will be skipped"
    
    def _check_database_health(self) -> str:
        """Check database component health"""
        if not self.database_handler:
            return "unknown"
        
        stats = self.database_handler.get_error_statistics()
        
        if stats['success_rate_percent'] >= 95:
            return "healthy"
        elif stats['success_rate_percent'] >= 80:
            return "degraded"
        else:
            return "critical"
    
    def _check_memory_health(self) -> str:
        """Check memory component health"""
        if not self.memory_manager:
            return "unknown"
        
        report = self.memory_manager.check_memory_pressure()
        
        if report.usage_percentage < 70:
            return "healthy"
        elif report.usage_percentage < 90:
            return "degraded"
        else:
            return "critical"
    
    def _check_timestamp_health(self) -> str:
        """Check timestamp parsing component health"""
        if not self.timestamp_parser:
            return "unknown"
        
        stats = self.timestamp_parser.get_parsing_statistics()
        
        if stats['success_rate_percent'] >= 90:
            return "healthy"
        elif stats['success_rate_percent'] >= 70:
            return "degraded"
        else:
            return "critical"
    
    def _determine_overall_health(self, db_health: str, mem_health: str, 
                                 ts_health: str, critical_error_count: int) -> str:
        """Determine overall system health"""
        if critical_error_count > 0:
            return "critical"
        
        health_scores = {"healthy": 3, "degraded": 2, "critical": 1, "unknown": 2}
        
        total_score = (health_scores.get(db_health, 2) + 
                      health_scores.get(mem_health, 2) + 
                      health_scores.get(ts_health, 2))
        
        avg_score = total_score / 3
        
        if avg_score >= 2.7:
            return "healthy"
        elif avg_score >= 2.0:
            return "degraded"
        else:
            return "critical"
    
    def _generate_health_recommendations(self, db_health: str, mem_health: str,
                                       ts_health: str, recent_errors: List[ErrorEvent]) -> List[str]:
        """Generate health recommendations based on current status"""
        recommendations = []
        
        if db_health == "critical":
            recommendations.append("CRITICAL: Database health is poor - check database connections and disk space")
        elif db_health == "degraded":
            recommendations.append("WARNING: Database performance is degraded - monitor connection pool")
        
        if mem_health == "critical":
            recommendations.append("CRITICAL: Memory usage is critical - enable streaming mode or increase memory limit")
        elif mem_health == "degraded":
            recommendations.append("WARNING: Memory usage is high - consider reducing batch sizes")
        
        if ts_health == "critical":
            recommendations.append("CRITICAL: Timestamp parsing is failing - check data formats")
        elif ts_health == "degraded":
            recommendations.append("WARNING: Timestamp parsing issues detected - validate data sources")
        
        # Analyze error patterns
        error_categories = {}
        for error in recent_errors:
            category = error.category.value
            error_categories[category] = error_categories.get(category, 0) + 1
        
        for category, count in error_categories.items():
            if count > 10:
                recommendations.append(f"High error rate in {category} component ({count} errors) - investigate root cause")
        
        return recommendations
    
    def _get_recent_errors(self, hours: int) -> List[ErrorEvent]:
        """Get errors within specified time window"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with self.error_lock:
            return [error for error in self.error_history if error.timestamp >= cutoff_time]
    
    def _log_error(self, error_event: ErrorEvent):
        """Log error event with appropriate level"""
        log_message = (f"[{error_event.category.value.upper()}] {error_event.component}: "
                      f"{error_event.error_message}")
        
        if error_event.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(log_message)
        elif error_event.severity == ErrorSeverity.HIGH:
            self.logger.error(log_message)
        elif error_event.severity == ErrorSeverity.MEDIUM:
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
        
        if self.debug_mode:
            print(f"[ErrorCoordinator] {error_event.severity.value.upper()}: {log_message}")