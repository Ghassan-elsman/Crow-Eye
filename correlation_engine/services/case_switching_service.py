"""
Case Switching Service

Provides automatic case-specific configuration switching when cases are changed
in the Crow-Eye system. Monitors case changes and automatically loads appropriate
configurations.

Features:
- Automatic case detection and switching
- Configuration preloading and caching
- Case change event handling
- Integration with main application
- Background configuration validation
- Performance optimization for frequent switches
"""

import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from ..config.case_configuration_manager import CaseConfigurationManager, ConfigurationChangeEvent
from ..integration.case_specific_configuration_integration import CaseSpecificConfigurationIntegration

logger = logging.getLogger(__name__)


@dataclass
class CaseSwitchEvent:
    """Event representing a case switch"""
    previous_case_id: Optional[str]
    new_case_id: str
    switch_time: str
    switch_reason: str  # 'manual', 'automatic', 'startup'
    configuration_loaded: bool
    load_time_ms: float


@dataclass
class CacheEntry:
    """Cache entry for case configuration"""
    case_id: str
    configuration_summary: Dict[str, Any]
    cached_time: str
    access_count: int
    last_accessed: str


class CaseSwitchingService:
    """
    Service for automatic case-specific configuration switching.
    
    Monitors case changes and automatically loads appropriate configurations
    with caching and performance optimization.
    """
    
    def __init__(self, 
                 case_manager: CaseConfigurationManager,
                 cache_size: int = 50,
                 cache_ttl_minutes: int = 30):
        """
        Initialize case switching service.
        
        Args:
            case_manager: Case configuration manager
            cache_size: Maximum number of configurations to cache
            cache_ttl_minutes: Cache time-to-live in minutes
        """
        self.case_manager = case_manager
        self.cache_size = cache_size
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        
        # Current state
        self.current_case_id: Optional[str] = None
        self.is_running = False
        self.auto_switch_enabled = True
        
        # Caching
        self.configuration_cache: Dict[str, CacheEntry] = {}
        self.cache_lock = threading.RLock()
        
        # Event tracking
        self.switch_history: List[CaseSwitchEvent] = []
        self.switch_listeners: List[Callable[[CaseSwitchEvent], None]] = []
        
        # Background thread
        self.background_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Performance metrics
        self.metrics = {
            'total_switches': 0,
            'successful_switches': 0,
            'failed_switches': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'average_switch_time_ms': 0.0
        }
        
        # Register with case manager for change events
        self.case_manager.add_change_listener(self._on_configuration_change)
        
        logger.info("Initialized case switching service")
    
    def start(self):
        """Start the case switching service"""
        if self.is_running:
            logger.warning("Case switching service is already running")
            return
        
        self.is_running = True
        self.stop_event.clear()
        
        # Start background thread for cache maintenance
        self.background_thread = threading.Thread(
            target=self._background_worker,
            name="CaseSwitchingService",
            daemon=True
        )
        self.background_thread.start()
        
        logger.info("Started case switching service")
    
    def stop(self):
        """Stop the case switching service"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.stop_event.set()
        
        if self.background_thread and self.background_thread.is_alive():
            self.background_thread.join(timeout=5.0)
        
        logger.info("Stopped case switching service")
    
    def add_switch_listener(self, listener: Callable[[CaseSwitchEvent], None]):
        """
        Add listener for case switch events.
        
        Args:
            listener: Function to call when case switches occur
        """
        self.switch_listeners.append(listener)
    
    def remove_switch_listener(self, listener: Callable):
        """
        Remove case switch listener.
        
        Args:
            listener: Listener to remove
        """
        if listener in self.switch_listeners:
            self.switch_listeners.remove(listener)
    
    def _notify_switch_listeners(self, event: CaseSwitchEvent):
        """Notify all switch listeners of case switch"""
        self.switch_history.append(event)
        
        # Keep history limited
        if len(self.switch_history) > 1000:
            self.switch_history = self.switch_history[-500:]
        
        for listener in self.switch_listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(f"Case switch listener failed: {e}")
    
    def switch_to_case(self, 
                      case_id: str, 
                      reason: str = 'manual',
                      force_reload: bool = False) -> bool:
        """
        Switch to a specific case with automatic configuration loading.
        
        Args:
            case_id: Case identifier to switch to
            reason: Reason for the switch
            force_reload: Whether to force reload even if already current
            
        Returns:
            True if switched successfully, False otherwise
        """
        start_time = time.time()
        
        try:
            logger.info(f"Switching to case: {case_id} (reason: {reason})")
            
            # Check if already current case
            if case_id == self.current_case_id and not force_reload:
                logger.info(f"Already on case {case_id}, no switch needed")
                return True
            
            previous_case = self.current_case_id
            
            # Try to load from cache first
            configuration_loaded = False
            if not force_reload:
                configuration_loaded = self._load_from_cache(case_id)
            
            # If not in cache or force reload, load from manager
            if not configuration_loaded or force_reload:
                success = self.case_manager.switch_to_case(case_id, auto_create=True)
                if not success:
                    self.metrics['failed_switches'] += 1
                    return False
                
                # Cache the configuration
                self._cache_configuration(case_id)
                configuration_loaded = True
            
            # Update current case
            self.current_case_id = case_id
            
            # Calculate switch time
            switch_time_ms = (time.time() - start_time) * 1000
            
            # Update metrics
            self.metrics['total_switches'] += 1
            self.metrics['successful_switches'] += 1
            
            # Update average switch time
            if self.metrics['total_switches'] > 0:
                current_avg = self.metrics['average_switch_time_ms']
                new_avg = ((current_avg * (self.metrics['total_switches'] - 1)) + switch_time_ms) / self.metrics['total_switches']
                self.metrics['average_switch_time_ms'] = new_avg
            
            # Create switch event
            switch_event = CaseSwitchEvent(
                previous_case_id=previous_case,
                new_case_id=case_id,
                switch_time=datetime.now().isoformat(),
                switch_reason=reason,
                configuration_loaded=configuration_loaded,
                load_time_ms=switch_time_ms
            )
            
            # Notify listeners
            self._notify_switch_listeners(switch_event)
            
            logger.info(f"Successfully switched to case {case_id} in {switch_time_ms:.1f}ms")
            return True
            
        except Exception as e:
            logger.error(f"Failed to switch to case {case_id}: {e}")
            self.metrics['failed_switches'] += 1
            return False
    
    def _load_from_cache(self, case_id: str) -> bool:
        """
        Try to load case configuration from cache.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if loaded from cache, False otherwise
        """
        with self.cache_lock:
            if case_id not in self.configuration_cache:
                self.metrics['cache_misses'] += 1
                return False
            
            cache_entry = self.configuration_cache[case_id]
            
            # Check if cache entry is still valid
            cached_time = datetime.fromisoformat(cache_entry.cached_time)
            if datetime.now() - cached_time > self.cache_ttl:
                # Cache expired, remove entry
                del self.configuration_cache[case_id]
                self.metrics['cache_misses'] += 1
                return False
            
            # Update access information
            cache_entry.access_count += 1
            cache_entry.last_accessed = datetime.now().isoformat()
            
            self.metrics['cache_hits'] += 1
            
            logger.debug(f"Loaded case {case_id} from cache (access count: {cache_entry.access_count})")
            return True
    
    def _cache_configuration(self, case_id: str):
        """
        Cache configuration for a case.
        
        Args:
            case_id: Case identifier to cache
        """
        try:
            with self.cache_lock:
                # Get configuration summary
                summary = self.case_manager.integration.get_case_configuration_summary(case_id)
                
                if 'error' in summary:
                    logger.warning(f"Cannot cache configuration for case {case_id}: {summary['error']}")
                    return
                
                # Create cache entry
                cache_entry = CacheEntry(
                    case_id=case_id,
                    configuration_summary=summary,
                    cached_time=datetime.now().isoformat(),
                    access_count=1,
                    last_accessed=datetime.now().isoformat()
                )
                
                # Add to cache
                self.configuration_cache[case_id] = cache_entry
                
                # Enforce cache size limit
                if len(self.configuration_cache) > self.cache_size:
                    self._evict_cache_entries()
                
                logger.debug(f"Cached configuration for case {case_id}")
                
        except Exception as e:
            logger.error(f"Failed to cache configuration for case {case_id}: {e}")
    
    def _evict_cache_entries(self):
        """Evict least recently used cache entries to maintain size limit"""
        try:
            # Sort by last accessed time (oldest first)
            sorted_entries = sorted(
                self.configuration_cache.items(),
                key=lambda x: x[1].last_accessed
            )
            
            # Remove oldest entries until we're under the limit
            entries_to_remove = len(self.configuration_cache) - self.cache_size + 1
            
            for i in range(entries_to_remove):
                case_id, entry = sorted_entries[i]
                del self.configuration_cache[case_id]
                logger.debug(f"Evicted cache entry for case {case_id} (last accessed: {entry.last_accessed})")
            
        except Exception as e:
            logger.error(f"Failed to evict cache entries: {e}")
    
    def _background_worker(self):
        """Background worker for cache maintenance and monitoring"""
        logger.info("Started case switching service background worker")
        
        while not self.stop_event.wait(60):  # Check every minute
            try:
                self._perform_cache_maintenance()
                self._monitor_case_changes()
                
            except Exception as e:
                logger.error(f"Background worker error: {e}")
        
        logger.info("Stopped case switching service background worker")
    
    def _perform_cache_maintenance(self):
        """Perform cache maintenance operations"""
        try:
            with self.cache_lock:
                current_time = datetime.now()
                expired_cases = []
                
                # Find expired cache entries
                for case_id, cache_entry in self.configuration_cache.items():
                    cached_time = datetime.fromisoformat(cache_entry.cached_time)
                    if current_time - cached_time > self.cache_ttl:
                        expired_cases.append(case_id)
                
                # Remove expired entries
                for case_id in expired_cases:
                    del self.configuration_cache[case_id]
                    logger.debug(f"Removed expired cache entry for case {case_id}")
                
                if expired_cases:
                    logger.info(f"Cache maintenance: removed {len(expired_cases)} expired entries")
                
        except Exception as e:
            logger.error(f"Cache maintenance failed: {e}")
    
    def _monitor_case_changes(self):
        """Monitor for case changes that might require automatic switching"""
        try:
            # This would integrate with the main application's case management
            # For now, it's a placeholder for future integration
            pass
            
        except Exception as e:
            logger.error(f"Case change monitoring failed: {e}")
    
    def _on_configuration_change(self, event: ConfigurationChangeEvent):
        """Handle configuration change events"""
        try:
            logger.debug(f"Configuration change event: {event.case_id} - {event.change_type}")
            
            # Invalidate cache for changed case
            with self.cache_lock:
                if event.case_id in self.configuration_cache:
                    del self.configuration_cache[event.case_id]
                    logger.debug(f"Invalidated cache for case {event.case_id} due to configuration change")
            
            # If this is the current case, consider reloading
            if event.case_id == self.current_case_id and event.change_type in ['updated', 'created']:
                if self.auto_switch_enabled:
                    # Reload current case configuration
                    self.switch_to_case(event.case_id, reason='configuration_change', force_reload=True)
            
        except Exception as e:
            logger.error(f"Failed to handle configuration change event: {e}")
    
    def preload_case_configurations(self, case_ids: List[str]) -> Dict[str, bool]:
        """
        Preload configurations for multiple cases.
        
        Args:
            case_ids: List of case identifiers to preload
            
        Returns:
            Dictionary mapping case_id to success status
        """
        results = {}
        
        logger.info(f"Preloading configurations for {len(case_ids)} cases")
        
        for case_id in case_ids:
            try:
                # Check if already cached
                with self.cache_lock:
                    if case_id in self.configuration_cache:
                        cache_entry = self.configuration_cache[case_id]
                        cached_time = datetime.fromisoformat(cache_entry.cached_time)
                        
                        # If cache is still valid, skip preloading
                        if datetime.now() - cached_time <= self.cache_ttl:
                            results[case_id] = True
                            continue
                
                # Load and cache configuration
                summary = self.case_manager.integration.get_case_configuration_summary(case_id)
                
                if 'error' not in summary:
                    self._cache_configuration(case_id)
                    results[case_id] = True
                    logger.debug(f"Preloaded configuration for case {case_id}")
                else:
                    results[case_id] = False
                    logger.warning(f"Failed to preload case {case_id}: {summary['error']}")
                
            except Exception as e:
                results[case_id] = False
                logger.error(f"Failed to preload case {case_id}: {e}")
        
        successful_preloads = sum(1 for success in results.values() if success)
        logger.info(f"Preloaded {successful_preloads}/{len(case_ids)} case configurations")
        
        return results
    
    def get_cached_cases(self) -> List[str]:
        """
        Get list of currently cached case IDs.
        
        Returns:
            List of cached case identifiers
        """
        with self.cache_lock:
            return list(self.configuration_cache.keys())
    
    def clear_cache(self, case_id: Optional[str] = None):
        """
        Clear configuration cache.
        
        Args:
            case_id: Optional specific case to clear, clears all if None
        """
        with self.cache_lock:
            if case_id:
                if case_id in self.configuration_cache:
                    del self.configuration_cache[case_id]
                    logger.info(f"Cleared cache for case {case_id}")
            else:
                cleared_count = len(self.configuration_cache)
                self.configuration_cache.clear()
                logger.info(f"Cleared all cache entries ({cleared_count} entries)")
    
    def get_switch_history(self, limit: Optional[int] = None) -> List[CaseSwitchEvent]:
        """
        Get case switch history.
        
        Args:
            limit: Optional limit on number of events to return
            
        Returns:
            List of case switch events
        """
        if limit:
            return self.switch_history[-limit:]
        else:
            return self.switch_history.copy()
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for the switching service.
        
        Returns:
            Dictionary with performance metrics
        """
        with self.cache_lock:
            cache_info = {
                'cache_size': len(self.configuration_cache),
                'cache_limit': self.cache_size,
                'cache_hit_rate': 0.0,
                'cached_cases': list(self.configuration_cache.keys())
            }
            
            # Calculate cache hit rate
            total_requests = self.metrics['cache_hits'] + self.metrics['cache_misses']
            if total_requests > 0:
                cache_info['cache_hit_rate'] = self.metrics['cache_hits'] / total_requests
        
        return {
            'service_status': {
                'is_running': self.is_running,
                'current_case': self.current_case_id,
                'auto_switch_enabled': self.auto_switch_enabled
            },
            'performance_metrics': self.metrics.copy(),
            'cache_info': cache_info,
            'switch_history_size': len(self.switch_history)
        }
    
    def enable_auto_switch(self, enabled: bool = True):
        """
        Enable or disable automatic case switching.
        
        Args:
            enabled: Whether to enable automatic switching
        """
        self.auto_switch_enabled = enabled
        logger.info(f"Automatic case switching {'enabled' if enabled else 'disabled'}")
    
    def get_case_switch_recommendations(self) -> List[Dict[str, Any]]:
        """
        Get recommendations for case switching based on usage patterns.
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        try:
            with self.cache_lock:
                # Analyze cache usage patterns
                if self.configuration_cache:
                    # Find most accessed cases
                    sorted_by_access = sorted(
                        self.configuration_cache.items(),
                        key=lambda x: x[1].access_count,
                        reverse=True
                    )
                    
                    top_cases = sorted_by_access[:5]
                    
                    recommendations.append({
                        'type': 'frequently_used_cases',
                        'title': 'Frequently Used Cases',
                        'description': 'Cases you access most often',
                        'cases': [{'case_id': case_id, 'access_count': entry.access_count} 
                                for case_id, entry in top_cases]
                    })
                
                # Find recently accessed cases
                recent_switches = self.switch_history[-10:] if self.switch_history else []
                if recent_switches:
                    recent_cases = list(set(event.new_case_id for event in recent_switches))
                    
                    recommendations.append({
                        'type': 'recent_cases',
                        'title': 'Recently Used Cases',
                        'description': 'Cases you\'ve worked with recently',
                        'cases': recent_cases
                    })
                
                # Performance recommendations
                if self.metrics['cache_hits'] + self.metrics['cache_misses'] > 0:
                    hit_rate = self.metrics['cache_hits'] / (self.metrics['cache_hits'] + self.metrics['cache_misses'])
                    
                    if hit_rate < 0.7:
                        recommendations.append({
                            'type': 'performance',
                            'title': 'Cache Performance',
                            'description': f'Cache hit rate is {hit_rate:.1%}. Consider increasing cache size.',
                            'action': 'increase_cache_size'
                        })
                
                # Switch time recommendations
                if self.metrics['average_switch_time_ms'] > 1000:
                    recommendations.append({
                        'type': 'performance',
                        'title': 'Switch Performance',
                        'description': f'Average switch time is {self.metrics["average_switch_time_ms"]:.0f}ms. Consider preloading frequently used cases.',
                        'action': 'preload_cases'
                    })
            
        except Exception as e:
            logger.error(f"Failed to generate case switch recommendations: {e}")
            recommendations.append({
                'type': 'error',
                'title': 'Recommendation Error',
                'description': f'Failed to generate recommendations: {e}'
            })
        
        return recommendations