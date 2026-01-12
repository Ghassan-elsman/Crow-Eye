"""
Progress Tracking Integration Layer

This module provides the integration layer for coordinating progress events
between correlation engines and GUI widgets. It bridges the existing
ProgressTracker system with GUI components and provides engine-specific
progress event handling.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass

from ..engine.progress_tracking import (
    ProgressTracker, ProgressListener, ProgressEvent, ProgressEventType,
    OverallProgressData, WindowProgressData
)
from .terminal_progress_logger import TerminalProgressLogger, TerminalDisplayConfig
from .integration_error_handler import IntegrationErrorHandler, FallbackStrategy
from .integration_monitor import IntegrationMonitor

logger = logging.getLogger(__name__)


@dataclass
class EnhancedProgressEvent:
    """Extended progress event with integration data"""
    original_event: ProgressEvent
    semantic_stats: Optional[Dict[str, int]] = None
    scoring_stats: Optional[Dict[str, float]] = None
    engine_metadata: Optional[Dict[str, Any]] = None
    engine_type: Optional[str] = None
    formatted_message: Optional[str] = None


class GUIProgressListener(ProgressListener):
    """
    Progress listener that bridges ProgressTracker events to GUI widgets.
    
    This listener receives progress events from the ProgressTracker and
    formats them appropriately for display in GUI components.
    """
    
    def __init__(self, progress_widget=None, debug_mode: bool = False):
        """
        Initialize GUI progress listener.
        
        Args:
            progress_widget: GUI widget that displays progress (e.g., ProgressDisplayWidget)
            debug_mode: Enable debug logging
        """
        self.progress_widget = progress_widget
        self.debug_mode = debug_mode
        self.engine_type: Optional[str] = None
        self.semantic_stats: Optional[Dict[str, int]] = None
        self.scoring_stats: Optional[Dict[str, float]] = None
        
        # Progress formatting state
        self.last_percentage_reported = -1
        self.start_time: Optional[datetime] = None
        
        logger.info("GUIProgressListener initialized")
    
    def set_engine_context(self, engine_type: str, semantic_stats: Optional[Dict[str, int]] = None,
                          scoring_stats: Optional[Dict[str, float]] = None):
        """
        Set engine context for progress formatting.
        
        Args:
            engine_type: Type of engine ("identity_based" or "time_window")
            semantic_stats: Current semantic mapping statistics
            scoring_stats: Current scoring statistics
        """
        self.engine_type = engine_type
        self.semantic_stats = semantic_stats or {}
        self.scoring_stats = scoring_stats or {}
        
        if self.debug_mode:
            logger.info(f"Engine context set: {engine_type}")
    
    def on_progress_event(self, event: ProgressEvent):
        """
        Handle progress event from ProgressTracker.
        
        Args:
            event: ProgressEvent from the correlation engine
        """
        try:
            # Create enhanced event with integration data
            enhanced_event = EnhancedProgressEvent(
                original_event=event,
                semantic_stats=self.semantic_stats,
                scoring_stats=self.scoring_stats,
                engine_metadata=event.additional_data,
                engine_type=self.engine_type,
                formatted_message=self._format_progress_message(event)
            )
            
            # Send to GUI widget if available
            if self.progress_widget and hasattr(self.progress_widget, 'append_progress'):
                self.progress_widget.append_progress(enhanced_event.formatted_message)
            
            # Log progress event if in debug mode
            if self.debug_mode:
                logger.info(f"Progress Event: {event.event_type.value} - {enhanced_event.formatted_message}")
                
        except Exception as e:
            logger.error(f"Error handling progress event: {e}")
            if self.debug_mode:
                logger.exception("Progress event handling failed")
    
    def _format_progress_message(self, event: ProgressEvent) -> str:
        """
        Format progress event into human-readable message.
        
        Args:
            event: ProgressEvent to format
            
        Returns:
            Formatted message string
        """
        progress = event.overall_progress
        timestamp = event.timestamp.strftime("%H:%M:%S")
        
        if event.event_type == ProgressEventType.SCANNING_START:
            engine_name = "Identity-Based" if self.engine_type == "identity_based" else "Time-Window"
            return (f"[{timestamp}] Starting {engine_name} correlation: "
                   f"{progress.total_windows} {'identities' if self.engine_type == 'identity_based' else 'windows'} to process")
        
        elif event.event_type == ProgressEventType.WINDOW_START:
            if self.engine_type == "identity_based":
                return f"[{timestamp}] Processing identity {progress.windows_processed + 1} of {progress.total_windows}"
            else:
                window_time = progress.current_window_time.strftime("%Y-%m-%d %H:%M:%S") if progress.current_window_time else "unknown"
                return f"[{timestamp}] Processing window {progress.windows_processed + 1} of {progress.total_windows} (time: {window_time})"
        
        elif event.event_type == ProgressEventType.WINDOW_COMPLETE:
            if event.window_progress:
                wp = event.window_progress
                if self.engine_type == "identity_based":
                    return (f"[{timestamp}] Identity {wp.window_id} complete: "
                           f"{wp.records_found} records, {wp.matches_created} matches "
                           f"({wp.processing_time_seconds:.2f}s)")
                else:
                    return (f"[{timestamp}] Window {wp.window_id} complete: "
                           f"{wp.records_found} records, {wp.matches_created} matches "
                           f"({wp.processing_time_seconds:.2f}s)")
        
        elif event.event_type == ProgressEventType.WINDOW_PROGRESS:
            current_percentage = int(progress.completion_percentage)
            
            # Only report major percentage milestones to avoid flooding
            if current_percentage != self.last_percentage_reported and current_percentage % 10 == 0:
                self.last_percentage_reported = current_percentage
                
                time_remaining = ""
                if progress.time_remaining_seconds:
                    minutes = int(progress.time_remaining_seconds // 60)
                    seconds = int(progress.time_remaining_seconds % 60)
                    time_remaining = f", ETA: {minutes}m {seconds}s"
                
                if self.engine_type == "identity_based":
                    return (f"[{timestamp}] Progress: {current_percentage}% complete "
                           f"({progress.windows_processed}/{progress.total_windows} identities, "
                           f"{progress.matches_found} matches{time_remaining})")
                else:
                    return (f"[{timestamp}] Progress: {current_percentage}% complete "
                           f"({progress.windows_processed}/{progress.total_windows} windows, "
                           f"{progress.matches_found} matches{time_remaining})")
        
        elif event.event_type == ProgressEventType.STREAMING_ENABLED:
            return f"[{timestamp}] Streaming mode enabled: {event.message}"
        
        elif event.event_type == ProgressEventType.MEMORY_WARNING:
            memory_mb = event.additional_data.get('current_usage_mb', 0)
            limit_mb = event.additional_data.get('limit_mb', 0)
            return f"[{timestamp}] Memory warning: {memory_mb:.1f}MB / {limit_mb:.1f}MB ({event.message})"
        
        elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
            total_time = ""
            if self.start_time:
                elapsed = (event.timestamp - self.start_time).total_seconds()
                minutes = int(elapsed // 60)
                seconds = int(elapsed % 60)
                total_time = f" in {minutes}m {seconds}s"
            
            # Add semantic and scoring statistics if available
            stats_info = ""
            if self.semantic_stats and self.semantic_stats.get('mappings_applied', 0) > 0:
                stats_info += f", {self.semantic_stats['mappings_applied']} semantic mappings applied"
            
            if self.scoring_stats and self.scoring_stats.get('scores_calculated', 0) > 0:
                avg_score = self.scoring_stats.get('average_score', 0)
                stats_info += f", avg score: {avg_score:.2f}"
            
            return (f"[{timestamp}] Correlation complete: {progress.matches_found} matches found "
                   f"in {progress.windows_processed} {'identities' if self.engine_type == 'identity_based' else 'windows'}"
                   f"{total_time}{stats_info}")
        
        elif event.event_type == ProgressEventType.ERROR_OCCURRED:
            return f"[{timestamp}] Error: {event.message}"
        
        elif event.event_type == ProgressEventType.CANCELLATION_REQUESTED:
            return f"[{timestamp}] Cancellation requested - stopping correlation..."
        
        else:
            # Generic message for unknown event types
            return f"[{timestamp}] {event.event_type.value}: {event.message or 'Processing...'}"
    
    def update_semantic_stats(self, stats: Dict[str, int]):
        """Update semantic mapping statistics for progress display"""
        self.semantic_stats = stats
    
    def update_scoring_stats(self, stats: Dict[str, float]):
        """Update scoring statistics for progress display"""
        self.scoring_stats = stats


class ProgressTrackingIntegration:
    """
    Main integration class that coordinates progress events between
    correlation engines and GUI widgets.
    
    This class provides:
    - GUI listener setup for progress widgets
    - Engine-specific progress event handling
    - Progress event coordination and enhancement
    - Statistics tracking and reporting
    - Comprehensive terminal progress logging
    """
    
    def __init__(self, gui_widgets: Optional[Dict[str, Any]] = None, debug_mode: bool = False,
                 enable_terminal_logging: bool = True, terminal_config: Optional[TerminalDisplayConfig] = None,
                 error_handler: IntegrationErrorHandler = None, monitor: IntegrationMonitor = None):
        """
        Initialize progress tracking integration.
        
        Args:
            gui_widgets: Dictionary of GUI widgets (e.g., {'progress_display': widget})
            debug_mode: Enable debug logging
            enable_terminal_logging: Enable comprehensive terminal progress logging
            terminal_config: Configuration for terminal logging
            error_handler: Error handler for graceful degradation
            monitor: Integration monitor for performance tracking
        """
        self.gui_widgets = gui_widgets or {}
        self.debug_mode = debug_mode
        
        # Error handling and monitoring
        self.error_handler = error_handler or IntegrationErrorHandler()
        self.monitor = monitor or IntegrationMonitor()
        
        # Create progress tracker with error handling
        try:
            self.progress_tracker = ProgressTracker(debug_mode=debug_mode)
        except Exception as e:
            fallback_result = self.error_handler.handle_progress_tracking_error(
                e, context={'operation': 'create_progress_tracker'}
            )
            if fallback_result.success and fallback_result.result:
                self.progress_tracker = fallback_result.result
                logger.warning(f"Using fallback progress tracker: {fallback_result.message}")
            else:
                logger.error(f"Failed to create progress tracker: {e}")
                raise
        
        # Create GUI listener with error handling
        progress_widget = self.gui_widgets.get('progress_display')
        try:
            self.gui_listener = GUIProgressListener(progress_widget, debug_mode)
        except Exception as e:
            fallback_result = self.error_handler.handle_progress_tracking_error(
                e, context={'operation': 'create_gui_listener'}
            )
            if fallback_result.success:
                logger.warning(f"GUI listener creation failed, using fallback: {fallback_result.message}")
                self.gui_listener = None
            else:
                logger.error(f"Failed to create GUI listener: {e}")
                self.gui_listener = None
        
        # Create terminal logger with error handling
        self.terminal_logger: Optional[TerminalProgressLogger] = None
        if enable_terminal_logging:
            try:
                self.terminal_logger = TerminalProgressLogger(terminal_config)
                self.progress_tracker.add_listener(self.terminal_logger)
            except Exception as e:
                fallback_result = self.error_handler.handle_progress_tracking_error(
                    e, context={'operation': 'create_terminal_logger'}
                )
                logger.warning(f"Terminal logger creation failed: {fallback_result.message}")
                self.terminal_logger = None
        
        # Register GUI listener with progress tracker if available
        if self.gui_listener:
            try:
                self.progress_tracker.add_listener(self.gui_listener)
            except Exception as e:
                logger.warning(f"Failed to register GUI listener: {e}")
        
        # Engine-specific state
        self.current_engine_type: Optional[str] = None
        self.engine_start_time: Optional[datetime] = None
        
        # Statistics tracking
        self.semantic_stats: Dict[str, int] = {}
        self.scoring_stats: Dict[str, float] = {}
        
        logger.info("ProgressTrackingIntegration initialized with error handling" + 
                   (" and terminal logging" if self.terminal_logger else ""))
    
    def setup_gui_listeners(self, widgets: Dict[str, Any]):
        """
        Setup GUI listeners for progress widgets.
        
        Args:
            widgets: Dictionary of GUI widgets to connect
        """
        self.gui_widgets.update(widgets)
        
        # Update progress widget in GUI listener
        if 'progress_display' in widgets:
            self.gui_listener.progress_widget = widgets['progress_display']
            logger.info("Progress display widget connected")
        
        if self.debug_mode:
            logger.info(f"GUI listeners setup for {len(widgets)} widgets")
    
    def start_correlation_tracking(self, engine_type: str, config: Dict[str, Any]):
        """
        Start progress tracking for correlation.
        
        Args:
            engine_type: Type of engine ("identity_based" or "time_window")
            config: Engine configuration dictionary
        """
        operation_id = self.monitor.start_operation(
            "progress_tracking", 
            "start_correlation_tracking",
            context={'engine_type': engine_type}
        )
        
        try:
            self.current_engine_type = engine_type
            self.engine_start_time = datetime.now()
            
            # Set engine context in GUI listener
            if self.gui_listener:
                try:
                    self.gui_listener.set_engine_context(
                        engine_type=engine_type,
                        semantic_stats=self.semantic_stats,
                        scoring_stats=self.scoring_stats
                    )
                except Exception as e:
                    logger.warning(f"Failed to set GUI listener engine context: {e}")
            
            # Set engine context in terminal logger
            if self.terminal_logger:
                try:
                    total_items = config.get('total_windows', config.get('total_identities', 0))
                    self.terminal_logger.set_engine_context(engine_type, total_items)
                    self.terminal_logger.update_semantic_stats(self.semantic_stats)
                    self.terminal_logger.update_scoring_stats(self.scoring_stats)
                except Exception as e:
                    logger.warning(f"Failed to set terminal logger engine context: {e}")
            
            # Record start time in GUI listener
            if self.gui_listener:
                self.gui_listener.start_time = self.engine_start_time
            
            # Extract configuration parameters
            total_items = config.get('total_windows', config.get('total_identities', 0))
            window_size = config.get('window_size_minutes', 60)
            time_start = config.get('time_range_start', datetime(2000, 1, 1))
            time_end = config.get('time_range_end', datetime.now())
            parallel = config.get('parallel_processing', False)
            max_workers = config.get('max_workers', 1)
            
            # Start progress tracking with error handling
            try:
                self.progress_tracker.start_scanning(
                    total_windows=total_items,
                    window_size_minutes=window_size,
                    time_range_start=time_start,
                    time_range_end=time_end,
                    parallel_processing=parallel,
                    max_workers=max_workers
                )
            except Exception as e:
                # Handle progress tracker failure
                fallback_result = self.error_handler.handle_progress_tracking_error(
                    e, context={'operation': 'start_scanning', 'engine_type': engine_type}
                )
                
                if fallback_result.success and fallback_result.result:
                    # Use fallback progress tracker
                    fallback_tracker = fallback_result.result
                    fallback_tracker.start_tracking(total_items)
                    logger.warning(f"Using fallback progress tracking: {fallback_result.message}")
                else:
                    logger.error(f"Progress tracking failed to start: {e}")
                    raise
            
            self.monitor.complete_operation(operation_id, success=True)
            logger.info(f"Started {engine_type} correlation tracking with {total_items} items")
            
        except Exception as e:
            self.monitor.complete_operation(operation_id, success=False, error_message=str(e))
            
            # Handle critical failure
            fallback_result = self.error_handler.handle_progress_tracking_error(
                e, context={'operation': 'start_correlation_tracking', 'engine_type': engine_type}
            )
            
            if not fallback_result.success:
                logger.error(f"Failed to start correlation tracking: {e}")
                raise
    
    def handle_engine_specific_progress(self, engine_type: str, event_data: Dict[str, Any]):
        """
        Handle engine-specific progress events.
        
        Args:
            engine_type: Type of engine generating the event
            event_data: Engine-specific event data
        """
        try:
            if engine_type == "identity_based":
                self._handle_identity_engine_progress(event_data)
            elif engine_type == "time_window":
                self._handle_time_window_engine_progress(event_data)
            else:
                logger.warning(f"Unknown engine type for progress handling: {engine_type}")
                
        except Exception as e:
            logger.error(f"Error handling engine-specific progress: {e}")
            if self.debug_mode:
                logger.exception("Engine-specific progress handling failed")
    
    def _handle_identity_engine_progress(self, event_data: Dict[str, Any]):
        """Handle progress events from Identity-Based Engine"""
        event_type = event_data.get('event_type')
        
        if event_type == 'identity_start':
            identity_id = event_data.get('identity_id', 'unknown')
            self.progress_tracker.start_window(
                window_id=f"identity_{identity_id}",
                window_start_time=datetime.now(),
                window_end_time=datetime.now()
            )
        
        elif event_type == 'identity_complete':
            identity_id = event_data.get('identity_id', 'unknown')
            records_found = event_data.get('records_found', 0)
            matches_created = event_data.get('matches_created', 0)
            feathers_with_records = event_data.get('feathers_with_records', [])
            
            self.progress_tracker.complete_window(
                window_id=f"identity_{identity_id}",
                window_start_time=datetime.now(),
                window_end_time=datetime.now(),
                records_found=records_found,
                matches_created=matches_created,
                feathers_with_records=feathers_with_records
            )
        
        elif event_type == 'semantic_stats_update':
            self.semantic_stats.update(event_data.get('stats', {}))
            self.gui_listener.update_semantic_stats(self.semantic_stats)
            if self.terminal_logger:
                self.terminal_logger.update_semantic_stats(self.semantic_stats)
        
        elif event_type == 'scoring_stats_update':
            self.scoring_stats.update(event_data.get('stats', {}))
            self.gui_listener.update_scoring_stats(self.scoring_stats)
            if self.terminal_logger:
                self.terminal_logger.update_scoring_stats(self.scoring_stats)
    
    def _handle_time_window_engine_progress(self, event_data: Dict[str, Any]):
        """Handle progress events from Time-Window Engine"""
        event_type = event_data.get('event_type')
        
        if event_type == 'window_start':
            window_id = event_data.get('window_id', 'unknown')
            window_start = event_data.get('window_start_time', datetime.now())
            window_end = event_data.get('window_end_time', datetime.now())
            
            self.progress_tracker.start_window(
                window_id=window_id,
                window_start_time=window_start,
                window_end_time=window_end
            )
        
        elif event_type == 'window_complete':
            window_id = event_data.get('window_id', 'unknown')
            window_start = event_data.get('window_start_time', datetime.now())
            window_end = event_data.get('window_end_time', datetime.now())
            records_found = event_data.get('records_found', 0)
            matches_created = event_data.get('matches_created', 0)
            feathers_with_records = event_data.get('feathers_with_records', [])
            memory_usage = event_data.get('memory_usage_mb')
            
            self.progress_tracker.complete_window(
                window_id=window_id,
                window_start_time=window_start,
                window_end_time=window_end,
                records_found=records_found,
                matches_created=matches_created,
                feathers_with_records=feathers_with_records,
                memory_usage_mb=memory_usage
            )
        
        elif event_type == 'streaming_enabled':
            reason = event_data.get('reason', 'Memory limit reached')
            database_path = event_data.get('database_path', 'unknown')
            self.progress_tracker.report_streaming_enabled(reason, database_path)
        
        elif event_type == 'memory_warning':
            current_usage = event_data.get('current_usage_mb', 0)
            limit_mb = event_data.get('limit_mb', 0)
            message = event_data.get('message', 'Memory usage high')
            self.progress_tracker.report_memory_warning(current_usage, limit_mb, message)
        
        elif event_type == 'semantic_stats_update':
            self.semantic_stats.update(event_data.get('stats', {}))
            self.gui_listener.update_semantic_stats(self.semantic_stats)
            if self.terminal_logger:
                self.terminal_logger.update_semantic_stats(self.semantic_stats)
        
        elif event_type == 'scoring_stats_update':
            self.scoring_stats.update(event_data.get('stats', {}))
            self.gui_listener.update_scoring_stats(self.scoring_stats)
            if self.terminal_logger:
                self.terminal_logger.update_scoring_stats(self.scoring_stats)
    
    def report_error(self, error_message: str, error_details: Optional[str] = None):
        """
        Report an error during correlation.
        
        Args:
            error_message: Brief error description
            error_details: Detailed error information
        """
        self.progress_tracker.report_error(error_message, error_details)
    
    def complete_correlation(self):
        """Mark correlation as complete"""
        self.progress_tracker.complete_scanning()
        
        # Log final statistics
        if self.debug_mode:
            logger.info("Correlation completed with final statistics:")
            logger.info(f"  Engine type: {self.current_engine_type}")
            logger.info(f"  Semantic stats: {self.semantic_stats}")
            logger.info(f"  Scoring stats: {self.scoring_stats}")
    
    def get_terminal_logger(self) -> Optional[TerminalProgressLogger]:
        """Get the terminal progress logger instance"""
        return self.terminal_logger
    
    def request_cancellation(self):
        """Request cancellation of the current correlation"""
        self.progress_tracker.request_cancellation()
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        return self.progress_tracker.is_cancelled()
    
    def add_progress_listener(self, listener: ProgressListener):
        """
        Add a custom progress listener.
        
        Args:
            listener: ProgressListener to add
        """
        self.progress_tracker.add_listener(listener)
    
    def remove_progress_listener(self, listener: ProgressListener):
        """
        Remove a progress listener.
        
        Args:
            listener: ProgressListener to remove
        """
        self.progress_tracker.remove_listener(listener)
    
    def get_progress_tracker(self) -> ProgressTracker:
        """Get the underlying progress tracker"""
        return self.progress_tracker
    
    def get_current_statistics(self) -> Dict[str, Any]:
        """
        Get current progress and integration statistics.
        
        Returns:
            Dictionary with current statistics
        """
        return {
            'engine_type': self.current_engine_type,
            'engine_start_time': self.engine_start_time.isoformat() if self.engine_start_time else None,
            'semantic_stats': self.semantic_stats.copy(),
            'scoring_stats': self.scoring_stats.copy(),
            'progress_tracker_active': not self.progress_tracker.is_cancelled(),
            'gui_widgets_connected': len(self.gui_widgets)
        }