"""
Database Error Handler

Provides comprehensive error handling and resilience for database operations
in the Time-Window Scanning Correlation Engine.

Features:
- Retry logic with exponential backoff for database connection failures
- Handling for corrupted or locked database files
- Fallback strategies when feathers are unavailable
- Detailed error logging with context information
- Connection pooling and resource management
"""

import time
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Tuple
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import threading
import random


class DatabaseErrorType(Enum):
    """Types of database errors that can occur"""
    CONNECTION_FAILED = "connection_failed"
    DATABASE_LOCKED = "database_locked"
    DATABASE_CORRUPTED = "database_corrupted"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    DISK_FULL = "disk_full"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class DatabaseError:
    """Represents a database error with context"""
    error_type: DatabaseErrorType
    feather_id: str
    database_path: str
    original_exception: Exception
    timestamp: datetime
    retry_count: int = 0
    context: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}


@dataclass
class RetryConfig:
    """Configuration for retry logic"""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on_error_types: List[DatabaseErrorType] = None
    
    def __post_init__(self):
        if self.retry_on_error_types is None:
            self.retry_on_error_types = [
                DatabaseErrorType.CONNECTION_FAILED,
                DatabaseErrorType.DATABASE_LOCKED,
                DatabaseErrorType.TIMEOUT
            ]


@dataclass
class FallbackStrategy:
    """Configuration for fallback strategies"""
    skip_unavailable_feathers: bool = True
    use_cached_results: bool = True
    continue_with_partial_data: bool = True
    log_fallback_actions: bool = True


class DatabaseErrorHandler:
    """
    Handles database errors with retry logic and fallback strategies.
    
    Provides resilient database operations for the time-window scanning engine
    with comprehensive error handling, logging, and recovery mechanisms.
    """
    
    def __init__(self, 
                 retry_config: Optional[RetryConfig] = None,
                 fallback_strategy: Optional[FallbackStrategy] = None,
                 debug_mode: bool = False):
        """
        Initialize database error handler.
        
        Args:
            retry_config: Configuration for retry logic
            fallback_strategy: Configuration for fallback strategies
            debug_mode: Enable debug logging
        """
        self.retry_config = retry_config or RetryConfig()
        self.fallback_strategy = fallback_strategy or FallbackStrategy()
        self.debug_mode = debug_mode
        
        # Error tracking
        self.error_history: List[DatabaseError] = []
        self.feather_status: Dict[str, Dict[str, Any]] = {}
        self.connection_pool: Dict[str, sqlite3.Connection] = {}
        self.connection_locks: Dict[str, threading.Lock] = {}
        
        # Statistics
        self.total_operations = 0
        self.successful_operations = 0
        self.failed_operations = 0
        self.retry_operations = 0
        self.fallback_operations = 0
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        if debug_mode:
            self.logger.setLevel(logging.DEBUG)
        
        if self.debug_mode:
            print("[DatabaseErrorHandler] Initialized with retry config:", self.retry_config)
            print("[DatabaseErrorHandler] Fallback strategy:", self.fallback_strategy)
    
    def execute_with_retry(self, 
                          operation: Callable,
                          feather_id: str,
                          database_path: str,
                          operation_name: str = "database_operation",
                          **kwargs) -> Any:
        """
        Execute a database operation with retry logic and error handling.
        
        Args:
            operation: Function to execute (should accept connection as first argument)
            feather_id: ID of the feather being accessed
            database_path: Path to the database file
            operation_name: Name of the operation for logging
            **kwargs: Additional arguments to pass to the operation
            
        Returns:
            Result of the operation
            
        Raises:
            DatabaseError: If operation fails after all retries
        """
        self.total_operations += 1
        last_error = None
        
        for attempt in range(self.retry_config.max_retries + 1):
            try:
                # Get or create connection
                connection = self._get_connection(feather_id, database_path)
                
                # Execute operation
                result = operation(connection, **kwargs)
                
                # Success - update statistics and return
                self.successful_operations += 1
                if attempt > 0:
                    self.retry_operations += 1
                    
                # Update feather status
                self._update_feather_status(feather_id, "healthy", None)
                
                if self.debug_mode and attempt > 0:
                    print(f"[DatabaseErrorHandler] Operation '{operation_name}' succeeded on attempt {attempt + 1}")
                
                return result
                
            except Exception as e:
                # Classify error
                error_type = self._classify_error(e)
                
                # Create database error object
                db_error = DatabaseError(
                    error_type=error_type,
                    feather_id=feather_id,
                    database_path=database_path,
                    original_exception=e,
                    timestamp=datetime.now(),
                    retry_count=attempt,
                    context={
                        'operation_name': operation_name,
                        'attempt': attempt + 1,
                        'max_retries': self.retry_config.max_retries + 1
                    }
                )
                
                # Add to error history
                self.error_history.append(db_error)
                last_error = db_error
                
                # Update feather status
                self._update_feather_status(feather_id, "error", db_error)
                
                # Log error with context
                self._log_database_error(db_error)
                
                # Check if we should retry
                if attempt < self.retry_config.max_retries and self._should_retry(error_type):
                    # Calculate delay with exponential backoff
                    delay = self._calculate_retry_delay(attempt)
                    
                    if self.debug_mode:
                        print(f"[DatabaseErrorHandler] Retrying operation '{operation_name}' "
                              f"in {delay:.2f}s (attempt {attempt + 2}/{self.retry_config.max_retries + 1})")
                    
                    # Close connection on error to force reconnection
                    self._close_connection(feather_id)
                    
                    # Wait before retry
                    time.sleep(delay)
                    continue
                else:
                    # No more retries or error type not retryable
                    break
        
        # All retries exhausted
        self.failed_operations += 1
        
        # Try fallback strategies
        fallback_result = self._try_fallback_strategies(last_error, operation_name, **kwargs)
        if fallback_result is not None:
            self.fallback_operations += 1
            return fallback_result
        
        # No fallback available - raise error
        raise Exception(f"Database operation '{operation_name}' failed after {self.retry_config.max_retries + 1} attempts: {last_error.original_exception}")
    
    def _get_connection(self, feather_id: str, database_path: str) -> sqlite3.Connection:
        """
        Get or create a database connection with proper error handling.
        
        Args:
            feather_id: ID of the feather
            database_path: Path to the database file
            
        Returns:
            SQLite connection object
            
        Raises:
            Exception: If connection cannot be established
        """
        # Get or create lock for this feather
        if feather_id not in self.connection_locks:
            self.connection_locks[feather_id] = threading.Lock()
        
        with self.connection_locks[feather_id]:
            # Check if we already have a connection
            if feather_id in self.connection_pool:
                conn = self.connection_pool[feather_id]
                try:
                    # Test connection
                    conn.execute("SELECT 1")
                    return conn
                except sqlite3.Error:
                    # Connection is bad, remove it
                    self._close_connection(feather_id)
            
            # Create new connection
            if not Path(database_path).exists():
                raise FileNotFoundError(f"Database file not found: {database_path}")
            
            # Check file permissions
            if not os.access(database_path, os.R_OK):
                raise PermissionError(f"No read permission for database: {database_path}")
            
            # Create connection with timeout and other settings
            conn = sqlite3.connect(
                database_path,
                timeout=30.0,  # 30 second timeout
                check_same_thread=False
            )
            
            # Configure connection
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")  # Use WAL mode for better concurrency
            conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety and performance
            conn.execute("PRAGMA cache_size=10000")  # Increase cache size
            conn.execute("PRAGMA temp_store=MEMORY")  # Use memory for temp storage
            
            # Test connection with a simple query
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            
            # Store in pool
            self.connection_pool[feather_id] = conn
            
            if self.debug_mode:
                print(f"[DatabaseErrorHandler] Created new connection for feather {feather_id}")
            
            return conn
    
    def _close_connection(self, feather_id: str):
        """Close and remove connection for a feather"""
        if feather_id in self.connection_pool:
            try:
                self.connection_pool[feather_id].close()
            except Exception:
                pass
            del self.connection_pool[feather_id]
    
    def _classify_error(self, exception: Exception) -> DatabaseErrorType:
        """
        Classify an exception into a database error type.
        
        Args:
            exception: Exception to classify
            
        Returns:
            DatabaseErrorType enum value
        """
        error_message = str(exception).lower()
        
        if isinstance(exception, FileNotFoundError):
            return DatabaseErrorType.FILE_NOT_FOUND
        
        elif isinstance(exception, PermissionError):
            return DatabaseErrorType.PERMISSION_DENIED
        
        elif isinstance(exception, sqlite3.OperationalError):
            if "database is locked" in error_message:
                return DatabaseErrorType.DATABASE_LOCKED
            elif "database disk image is malformed" in error_message or "database corruption" in error_message:
                return DatabaseErrorType.DATABASE_CORRUPTED
            elif "no such table" in error_message or "no such column" in error_message:
                return DatabaseErrorType.DATABASE_CORRUPTED
            elif "disk i/o error" in error_message or "disk full" in error_message:
                return DatabaseErrorType.DISK_FULL
            else:
                return DatabaseErrorType.CONNECTION_FAILED
        
        elif isinstance(exception, sqlite3.DatabaseError):
            if "timeout" in error_message:
                return DatabaseErrorType.TIMEOUT
            else:
                return DatabaseErrorType.CONNECTION_FAILED
        
        else:
            return DatabaseErrorType.UNKNOWN
    
    def _should_retry(self, error_type: DatabaseErrorType) -> bool:
        """
        Determine if an error type should be retried.
        
        Args:
            error_type: Type of database error
            
        Returns:
            True if the error should be retried
        """
        return error_type in self.retry_config.retry_on_error_types
    
    def _calculate_retry_delay(self, attempt: int) -> float:
        """
        Calculate delay for retry with exponential backoff.
        
        Args:
            attempt: Current attempt number (0-based)
            
        Returns:
            Delay in seconds
        """
        # Exponential backoff
        delay = self.retry_config.base_delay_seconds * (self.retry_config.exponential_base ** attempt)
        
        # Cap at maximum delay
        delay = min(delay, self.retry_config.max_delay_seconds)
        
        # Add jitter to prevent thundering herd
        if self.retry_config.jitter:
            jitter = random.uniform(0.1, 0.3) * delay
            delay += jitter
        
        return delay
    
    def _update_feather_status(self, feather_id: str, status: str, error: Optional[DatabaseError]):
        """
        Update the status of a feather.
        
        Args:
            feather_id: ID of the feather
            status: Status string ("healthy", "error", "unavailable")
            error: DatabaseError object if status is "error"
        """
        self.feather_status[feather_id] = {
            'status': status,
            'last_updated': datetime.now(),
            'error': error,
            'consecutive_failures': self.feather_status.get(feather_id, {}).get('consecutive_failures', 0) + (1 if status == 'error' else -self.feather_status.get(feather_id, {}).get('consecutive_failures', 0))
        }
    
    def _log_database_error(self, error: DatabaseError):
        """
        Log database error with detailed context information.
        
        Args:
            error: DatabaseError to log
        """
        context_str = ", ".join([f"{k}={v}" for k, v in error.context.items()])
        
        log_message = (
            f"Database error in feather '{error.feather_id}': "
            f"{error.error_type.value} - {error.original_exception} "
            f"(attempt {error.retry_count + 1}, {context_str})"
        )
        
        if error.error_type in [DatabaseErrorType.DATABASE_CORRUPTED, DatabaseErrorType.FILE_NOT_FOUND]:
            self.logger.error(log_message)
        elif error.retry_count == 0:
            self.logger.warning(log_message)
        else:
            self.logger.debug(log_message)
        
        if self.debug_mode:
            print(f"[DatabaseErrorHandler] {log_message}")
    
    def _try_fallback_strategies(self, error: DatabaseError, operation_name: str, **kwargs) -> Any:
        """
        Try fallback strategies when database operations fail.
        
        Args:
            error: The database error that occurred
            operation_name: Name of the failed operation
            **kwargs: Operation arguments
            
        Returns:
            Fallback result or None if no fallback available
        """
        if not self.fallback_strategy.skip_unavailable_feathers:
            return None
        
        # For query operations, return empty results
        if operation_name in ['query_time_range', 'get_timestamp_range', 'get_record_count']:
            if self.fallback_strategy.log_fallback_actions:
                fallback_msg = f"Using fallback for '{operation_name}' on feather '{error.feather_id}': returning empty results"
                self.logger.warning(fallback_msg)
                if self.debug_mode:
                    print(f"[DatabaseErrorHandler] {fallback_msg}")
            
            # Return appropriate empty result based on operation
            if operation_name == 'query_time_range':
                return []
            elif operation_name == 'get_timestamp_range':
                return (None, None)
            elif operation_name == 'get_record_count':
                return 0
        
        return None
    
    def get_feather_health_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get health status of all feathers.
        
        Returns:
            Dictionary mapping feather_id to health status
        """
        return self.feather_status.copy()
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get error handling statistics.
        
        Returns:
            Dictionary with error statistics
        """
        error_counts_by_type = {}
        for error in self.error_history:
            error_type = error.error_type.value
            error_counts_by_type[error_type] = error_counts_by_type.get(error_type, 0) + 1
        
        success_rate = (self.successful_operations / self.total_operations * 100) if self.total_operations > 0 else 0
        
        return {
            'total_operations': self.total_operations,
            'successful_operations': self.successful_operations,
            'failed_operations': self.failed_operations,
            'retry_operations': self.retry_operations,
            'fallback_operations': self.fallback_operations,
            'success_rate_percent': success_rate,
            'error_counts_by_type': error_counts_by_type,
            'total_errors': len(self.error_history),
            'active_connections': len(self.connection_pool)
        }
    
    def get_recent_errors(self, hours: int = 24) -> List[DatabaseError]:
        """
        Get recent errors within the specified time window.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of recent DatabaseError objects
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [error for error in self.error_history if error.timestamp >= cutoff_time]
    
    def cleanup(self):
        """Cleanup all database connections and resources"""
        for feather_id in list(self.connection_pool.keys()):
            self._close_connection(feather_id)
        
        self.connection_pool.clear()
        self.connection_locks.clear()
        
        if self.debug_mode:
            print("[DatabaseErrorHandler] Cleanup completed")


# Import os for file permission checks
import os