"""
Enhanced Cancellation Support for Time-Window Scanning Engine

This module provides comprehensive cancellation support including graceful shutdown,
resource cleanup, partial result preservation, and cancellation event propagation.
"""

import threading
import time
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass
from pathlib import Path
import weakref


@dataclass
class CancellationContext:
    """Context information for cancellation operations"""
    cancellation_time: datetime
    reason: str
    requested_by: str
    partial_results_preserved: bool = False
    resources_cleaned: bool = False
    cleanup_errors: List[str] = None
    
    def __post_init__(self):
        if self.cleanup_errors is None:
            self.cleanup_errors = []


class ResourceManager:
    """
    Manages resources that need cleanup during cancellation.
    
    Tracks database connections, file handles, threads, and other resources
    that should be properly cleaned up when cancellation occurs.
    """
    
    def __init__(self):
        self._resources: Dict[str, Any] = {}
        self._cleanup_callbacks: Dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()
    
    def register_resource(self, resource_id: str, resource: Any, cleanup_callback: Optional[Callable[[], None]] = None):
        """
        Register a resource for cleanup tracking.
        
        Args:
            resource_id: Unique identifier for the resource
            resource: The resource object
            cleanup_callback: Optional custom cleanup function
        """
        with self._lock:
            self._resources[resource_id] = resource
            if cleanup_callback:
                self._cleanup_callbacks[resource_id] = cleanup_callback
    
    def unregister_resource(self, resource_id: str):
        """
        Unregister a resource (when it's cleaned up normally).
        
        Args:
            resource_id: Resource identifier to remove
        """
        with self._lock:
            self._resources.pop(resource_id, None)
            self._cleanup_callbacks.pop(resource_id, None)
    
    def cleanup_all_resources(self) -> List[str]:
        """
        Clean up all registered resources.
        
        Returns:
            List of error messages if any cleanup operations failed
        """
        errors = []
        
        with self._lock:
            # Copy the dictionaries to avoid modification during iteration
            resources = self._resources.copy()
            callbacks = self._cleanup_callbacks.copy()
        
        # Clean up resources with custom callbacks first
        for resource_id, callback in callbacks.items():
            try:
                callback()
            except Exception as e:
                errors.append(f"Failed to cleanup {resource_id}: {str(e)}")
        
        # Clean up remaining resources using default methods
        for resource_id, resource in resources.items():
            if resource_id not in callbacks:  # Skip if already cleaned with callback
                try:
                    self._default_cleanup(resource_id, resource)
                except Exception as e:
                    errors.append(f"Failed to cleanup {resource_id}: {str(e)}")
        
        # Clear all resources
        with self._lock:
            self._resources.clear()
            self._cleanup_callbacks.clear()
        
        return errors
    
    def _default_cleanup(self, resource_id: str, resource: Any):
        """
        Default cleanup method for common resource types.
        
        Args:
            resource_id: Resource identifier
            resource: Resource to clean up
        """
        # Database connections
        if hasattr(resource, 'close') and callable(resource.close):
            if isinstance(resource, sqlite3.Connection):
                try:
                    resource.close()
                except sqlite3.Error:
                    pass  # Connection might already be closed
            else:
                resource.close()
        
        # File handles
        elif hasattr(resource, 'close') and hasattr(resource, 'read'):
            resource.close()
        
        # Threads
        elif isinstance(resource, threading.Thread):
            if resource.is_alive():
                # Give thread a moment to finish gracefully
                resource.join(timeout=1.0)
        
        # Thread pools
        elif hasattr(resource, 'shutdown'):
            resource.shutdown(wait=False)
    
    def get_resource_count(self) -> int:
        """Get the number of registered resources"""
        with self._lock:
            return len(self._resources)
    
    def get_resource_ids(self) -> List[str]:
        """Get list of registered resource IDs"""
        with self._lock:
            return list(self._resources.keys())


class PartialResultsManager:
    """
    Manages preservation of partial results during cancellation.
    
    Ensures that work completed before cancellation is not lost and can be
    retrieved or resumed later.
    """
    
    def __init__(self, base_output_path: Optional[str] = None):
        """
        Initialize partial results manager.
        
        Args:
            base_output_path: Base directory for saving partial results
        """
        self.base_output_path = Path(base_output_path) if base_output_path else Path.cwd() / "partial_results"
        self.base_output_path.mkdir(exist_ok=True)
        
        self._partial_results: Dict[str, Any] = {}
        self._result_metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def save_partial_result(self, 
                          result_id: str,
                          correlation_result: Any,
                          metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Save partial correlation results.
        
        Args:
            result_id: Unique identifier for this result set
            correlation_result: CorrelationResult object to save
            metadata: Additional metadata about the partial result
            
        Returns:
            Path to saved partial result file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"partial_result_{result_id}_{timestamp}.json"
        filepath = self.base_output_path / filename
        
        # Prepare result data for serialization
        result_data = {
            'result_id': result_id,
            'timestamp': timestamp,
            'wing_id': getattr(correlation_result, 'wing_id', None),
            'wing_name': getattr(correlation_result, 'wing_name', None),
            'total_matches': getattr(correlation_result, 'total_matches', 0),
            'feathers_processed': getattr(correlation_result, 'feathers_processed', 0),
            'total_records_scanned': getattr(correlation_result, 'total_records_scanned', 0),
            'execution_duration_seconds': getattr(correlation_result, 'execution_duration_seconds', 0),
            'errors': getattr(correlation_result, 'errors', []),
            'warnings': getattr(correlation_result, 'warnings', []),
            'metadata': metadata or {}
        }
        
        # Save matches if available and not in streaming mode
        if hasattr(correlation_result, 'matches') and correlation_result.matches:
            # Convert matches to serializable format
            serializable_matches = []
            for match in correlation_result.matches[:1000]:  # Limit to first 1000 matches
                match_data = {
                    'match_id': getattr(match, 'match_id', ''),
                    'timestamp': getattr(match, 'timestamp', ''),
                    'match_score': getattr(match, 'match_score', 0.0),
                    'feather_count': getattr(match, 'feather_count', 0),
                    'time_spread_seconds': getattr(match, 'time_spread_seconds', 0),
                    'anchor_feather_id': getattr(match, 'anchor_feather_id', ''),
                    # Note: Not including full feather_records to keep file size manageable
                }
                serializable_matches.append(match_data)
            
            result_data['matches_sample'] = serializable_matches
            result_data['matches_sample_note'] = f"First {len(serializable_matches)} matches (of {result_data['total_matches']} total)"
        
        # Write to file
        import json
        try:
            with open(filepath, 'w') as f:
                json.dump(result_data, f, indent=2, default=str)
            
            # Store in memory cache
            with self._lock:
                self._partial_results[result_id] = result_data
                self._result_metadata[result_id] = {
                    'filepath': str(filepath),
                    'saved_at': datetime.now(),
                    'file_size_bytes': filepath.stat().st_size
                }
            
            return str(filepath)
            
        except Exception as e:
            raise RuntimeError(f"Failed to save partial results: {str(e)}")
    
    def load_partial_result(self, result_id: str) -> Optional[Dict[str, Any]]:
        """
        Load partial results by ID.
        
        Args:
            result_id: Result identifier
            
        Returns:
            Partial result data or None if not found
        """
        with self._lock:
            if result_id in self._partial_results:
                return self._partial_results[result_id].copy()
        
        # Try to load from file
        metadata = self._result_metadata.get(result_id)
        if metadata and 'filepath' in metadata:
            filepath = Path(metadata['filepath'])
            if filepath.exists():
                try:
                    import json
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    
                    with self._lock:
                        self._partial_results[result_id] = data
                    
                    return data
                except Exception:
                    pass
        
        return None
    
    def list_partial_results(self) -> List[Dict[str, Any]]:
        """
        List all available partial results.
        
        Returns:
            List of partial result summaries
        """
        summaries = []
        
        with self._lock:
            for result_id, metadata in self._result_metadata.items():
                result_data = self._partial_results.get(result_id)
                
                summary = {
                    'result_id': result_id,
                    'saved_at': metadata.get('saved_at'),
                    'filepath': metadata.get('filepath'),
                    'file_size_bytes': metadata.get('file_size_bytes', 0)
                }
                
                if result_data:
                    summary.update({
                        'wing_id': result_data.get('wing_id'),
                        'wing_name': result_data.get('wing_name'),
                        'total_matches': result_data.get('total_matches', 0),
                        'execution_duration_seconds': result_data.get('execution_duration_seconds', 0)
                    })
                
                summaries.append(summary)
        
        return summaries
    
    def cleanup_old_results(self, max_age_days: int = 7):
        """
        Clean up partial results older than specified age.
        
        Args:
            max_age_days: Maximum age in days before cleanup
        """
        cutoff_time = datetime.now() - timedelta(days=max_age_days)
        
        to_remove = []
        with self._lock:
            for result_id, metadata in self._result_metadata.items():
                saved_at = metadata.get('saved_at')
                if saved_at and saved_at < cutoff_time:
                    to_remove.append(result_id)
        
        for result_id in to_remove:
            self._remove_partial_result(result_id)
    
    def _remove_partial_result(self, result_id: str):
        """Remove a partial result and its file"""
        with self._lock:
            metadata = self._result_metadata.get(result_id)
            if metadata and 'filepath' in metadata:
                filepath = Path(metadata['filepath'])
                if filepath.exists():
                    try:
                        filepath.unlink()
                    except Exception:
                        pass
            
            self._partial_results.pop(result_id, None)
            self._result_metadata.pop(result_id, None)


class EnhancedCancellationManager:
    """
    Enhanced cancellation manager that provides comprehensive cancellation support
    for the time-window scanning correlation engine.
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize enhanced cancellation manager.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        
        # Core cancellation state
        self._cancelled = False
        self._cancellation_context: Optional[CancellationContext] = None
        self._lock = threading.Lock()
        
        # Resource and result management
        self.resource_manager = ResourceManager()
        self.partial_results_manager = PartialResultsManager()
        
        # Callbacks and listeners
        self._cancellation_callbacks: List[Callable[[CancellationContext], None]] = []
        self._cleanup_callbacks: List[Callable[[], None]] = []
        
        # Progress tracking integration
        self._progress_listeners: Set[Any] = set()  # Weak references to avoid circular deps
    
    def register_cancellation_callback(self, callback: Callable[[CancellationContext], None]):
        """
        Register a callback to be called when cancellation occurs.
        
        Args:
            callback: Function to call with CancellationContext
        """
        self._cancellation_callbacks.append(callback)
    
    def register_cleanup_callback(self, callback: Callable[[], None]):
        """
        Register a callback for resource cleanup.
        
        Args:
            callback: Function to call during cleanup
        """
        self._cleanup_callbacks.append(callback)
    
    def register_progress_listener(self, listener: Any):
        """
        Register a progress listener to receive cancellation events.
        
        Args:
            listener: Progress listener object
        """
        self._progress_listeners.add(weakref.ref(listener))
    
    def request_cancellation(self, reason: str = "User requested", requested_by: str = "Unknown"):
        """
        Request cancellation of the current operation.
        
        Args:
            reason: Reason for cancellation
            requested_by: Who requested the cancellation
        """
        with self._lock:
            if self._cancelled:
                return  # Already cancelled
            
            self._cancelled = True
            self._cancellation_context = CancellationContext(
                cancellation_time=datetime.now(),
                reason=reason,
                requested_by=requested_by
            )
        
        if self.debug_mode:
            print(f"[Cancellation] Cancellation requested: {reason} (by {requested_by})")
        
        # Notify progress listeners
        self._notify_progress_listeners()
        
        # Execute cancellation callbacks
        for callback in self._cancellation_callbacks:
            try:
                callback(self._cancellation_context)
            except Exception as e:
                if self.debug_mode:
                    print(f"[Cancellation] Error in cancellation callback: {e}")
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        with self._lock:
            return self._cancelled
    
    def check_cancellation(self):
        """
        Check for cancellation and raise exception if cancelled.
        
        Raises:
            OperationCancelledException: If operation was cancelled
        """
        if self.is_cancelled():
            from .progress_tracking import OperationCancelledException
            context = self.get_cancellation_context()
            raise OperationCancelledException(
                f"Operation cancelled: {context.reason if context else 'Unknown reason'}"
            )
    
    def get_cancellation_context(self) -> Optional[CancellationContext]:
        """Get cancellation context information"""
        with self._lock:
            return self._cancellation_context
    
    def perform_graceful_shutdown(self, 
                                correlation_result: Any = None,
                                save_partial_results: bool = True) -> CancellationContext:
        """
        Perform graceful shutdown with resource cleanup and result preservation.
        
        Args:
            correlation_result: CorrelationResult to save as partial result
            save_partial_results: Whether to save partial results
            
        Returns:
            CancellationContext with cleanup information
        """
        if not self.is_cancelled():
            self.request_cancellation("Graceful shutdown requested")
        
        context = self._cancellation_context
        if not context:
            return CancellationContext(
                cancellation_time=datetime.now(),
                reason="Unknown",
                requested_by="System"
            )
        
        if self.debug_mode:
            print("[Cancellation] Starting graceful shutdown...")
        
        # Save partial results if requested and available
        if save_partial_results and correlation_result:
            try:
                result_id = f"cancelled_{int(time.time())}"
                filepath = self.partial_results_manager.save_partial_result(
                    result_id=result_id,
                    correlation_result=correlation_result,
                    metadata={
                        'cancellation_reason': context.reason,
                        'cancelled_by': context.requested_by,
                        'cancellation_time': context.cancellation_time.isoformat()
                    }
                )
                context.partial_results_preserved = True
                
                if self.debug_mode:
                    print(f"[Cancellation] Partial results saved to: {filepath}")
                    
            except Exception as e:
                context.cleanup_errors.append(f"Failed to save partial results: {str(e)}")
                if self.debug_mode:
                    print(f"[Cancellation] Error saving partial results: {e}")
        
        # Execute cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                context.cleanup_errors.append(f"Cleanup callback error: {str(e)}")
                if self.debug_mode:
                    print(f"[Cancellation] Error in cleanup callback: {e}")
        
        # Clean up managed resources
        try:
            resource_errors = self.resource_manager.cleanup_all_resources()
            context.cleanup_errors.extend(resource_errors)
            context.resources_cleaned = True
            
            if self.debug_mode and resource_errors:
                print(f"[Cancellation] Resource cleanup errors: {resource_errors}")
            elif self.debug_mode:
                print("[Cancellation] All resources cleaned up successfully")
                
        except Exception as e:
            context.cleanup_errors.append(f"Resource cleanup failed: {str(e)}")
            if self.debug_mode:
                print(f"[Cancellation] Resource cleanup failed: {e}")
        
        if self.debug_mode:
            print(f"[Cancellation] Graceful shutdown complete. "
                  f"Partial results preserved: {context.partial_results_preserved}, "
                  f"Resources cleaned: {context.resources_cleaned}, "
                  f"Errors: {len(context.cleanup_errors)}")
        
        return context
    
    def _notify_progress_listeners(self):
        """Notify progress listeners about cancellation"""
        # Clean up dead weak references
        dead_refs = []
        for listener_ref in self._progress_listeners:
            listener = listener_ref()
            if listener is None:
                dead_refs.append(listener_ref)
            else:
                try:
                    # Try to call a cancellation method if it exists
                    if hasattr(listener, 'on_cancellation_requested'):
                        listener.on_cancellation_requested(self._cancellation_context)
                except Exception as e:
                    if self.debug_mode:
                        print(f"[Cancellation] Error notifying progress listener: {e}")
        
        # Remove dead references
        for dead_ref in dead_refs:
            self._progress_listeners.discard(dead_ref)
    
    def reset(self):
        """Reset cancellation state (for reuse)"""
        with self._lock:
            self._cancelled = False
            self._cancellation_context = None
        
        # Clear callbacks but keep resource and result managers
        self._cancellation_callbacks.clear()
        self._cleanup_callbacks.clear()
        self._progress_listeners.clear()
        
        if self.debug_mode:
            print("[Cancellation] Cancellation manager reset")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """
        Get a summary of cancellation manager status.
        
        Returns:
            Dictionary containing status information
        """
        context = self.get_cancellation_context()
        
        return {
            'is_cancelled': self.is_cancelled(),
            'cancellation_time': context.cancellation_time.isoformat() if context else None,
            'cancellation_reason': context.reason if context else None,
            'requested_by': context.requested_by if context else None,
            'partial_results_preserved': context.partial_results_preserved if context else False,
            'resources_cleaned': context.resources_cleaned if context else False,
            'cleanup_errors': context.cleanup_errors if context else [],
            'registered_resources': self.resource_manager.get_resource_count(),
            'available_partial_results': len(self.partial_results_manager.list_partial_results()),
            'registered_callbacks': len(self._cancellation_callbacks),
            'registered_cleanup_callbacks': len(self._cleanup_callbacks)
        }