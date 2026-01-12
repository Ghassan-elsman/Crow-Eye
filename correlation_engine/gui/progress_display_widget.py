"""
Progress Display Widget
Displays real-time progress during correlation execution.
"""

from PyQt5.QtWidgets import QTextEdit, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCharFormat, QColor, QTextCursor
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


# Severity colors for error visualization
SEVERITY_COLORS = {
    "critical": "#FF0000",  # Red
    "high": "#FF6600",      # Orange-Red
    "medium": "#FFCC00",    # Yellow-Orange
    "low": "#FFFF00",       # Yellow
    "info": "#00CCFF"       # Cyan
}


class ProgressDisplayWidget(QTextEdit):
    """
    Widget for displaying real-time correlation progress.
    
    Shows detailed progress information including:
    - Wing information
    - Anchor collection statistics
    - Correlation progress updates
    - Summary statistics
    - Error visualization with severity coloring
    """
    
    def __init__(self, parent=None):
        """
        Initialize progress display widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(200)
        self.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
            }
        """)
        
        # Store error details for dialog display
        self._error_details: Dict[str, Dict[str, Any]] = {}
        
        # Throttling for progress updates
        self._last_progress_update: Optional[datetime] = None
        self._min_update_interval_seconds: float = 1.0  # Update at most once per second
        self._last_progress_line_index: int = -1  # Track last progress line for updating
        
        # Correlation statistics tracking
        self._statistics_tracker = None  # Will be initialized when engine type is known
        self._last_percentage_display: float = -1.0  # Track last displayed percentage
    
    def _should_throttle_progress(self) -> bool:
        """Check if progress update should be throttled."""
        now = datetime.now()
        if self._last_progress_update is None:
            self._last_progress_update = now
            return False
        
        elapsed = (now - self._last_progress_update).total_seconds()
        if elapsed < self._min_update_interval_seconds:
            return True
        
        self._last_progress_update = now
        return False
    
    def update_progress_line(self, message: str):
        """
        Update the last progress line instead of appending a new one.
        This creates a dynamic single-line progress display for PyQt5.
        
        Args:
            message: Progress message to display
        """
        try:
            # Apply throttling
            if self._should_throttle_progress():
                return
            
            # Block signals to prevent flicker during update
            self.blockSignals(True)
            
            # Get the current text
            current_text = self.toPlainText()
            
            # If we have a previous progress line, replace the last line
            if self._last_progress_line_index >= 0 and current_text:
                # Split into lines
                lines = current_text.split('\n')
                
                # Replace the last line
                if lines:
                    lines[-1] = message
                    
                    # Set the updated text
                    new_text = '\n'.join(lines)
                    self.setPlainText(new_text)
            else:
                # First progress line - append it
                if current_text:
                    new_text = current_text + '\n' + message
                else:
                    new_text = message
                
                self.setPlainText(new_text)
                self._last_progress_line_index = 1  # Mark that we have a progress line
            
            # Move cursor to end and ensure visible
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
            
            # Re-enable signals
            self.blockSignals(False)
            
            # Auto-scroll to bottom
            self.ensureCursorVisible()
            
        except Exception as e:
            # If update fails, re-enable signals and fall back to appending
            self.blockSignals(False)
            # Fall back to appending
            try:
                self.append_progress(message)
            except:
                pass
    
    def append_progress(self, message: str):
        """
        Append a progress message and auto-scroll to bottom.
        This is for static messages (not dynamic updates).
        
        Args:
            message: Progress message to display
        """
        # Reset dynamic line tracking when appending a new static message
        self._last_progress_line_index = -1
        
        # Use append() which handles formatting properly
        self.append(message)
        
        # Auto-scroll to bottom
        self.ensureCursorVisible()
    
    def handle_progress_event(self, event):
        """
        Handle progress event from correlation engine.
        
        Args:
            event: ProgressEvent object with event_type and data, or EnhancedProgressEvent
        """
        # Handle NEW ProgressEvent format with ProgressEventType enum
        if hasattr(event, 'event_type') and hasattr(event, 'overall_progress'):
            self._handle_new_progress_event(event)
        # Handle EnhancedProgressEvent from integration layer
        elif hasattr(event, 'original_event'):
            self._handle_enhanced_progress_event(event)
        # Handle legacy format
        elif hasattr(event, 'event_type') and hasattr(event, 'data'):
            self._handle_legacy_progress_event(event)
    
    def _handle_new_progress_event(self, event):
        """
        Handle NEW progress event format with ProgressEventType enum.
        
        Args:
            event: ProgressEvent with event_type (ProgressEventType) and overall_progress
        """
        try:
            from ..engine.progress_tracking import ProgressEventType
            from ..engine.correlation_statistics import CorrelationStatisticsTracker
            
            # Initialize statistics tracker if needed
            if self._statistics_tracker is None and hasattr(event, 'additional_data'):
                engine_type = event.additional_data.get('engine_type', 'time_window_scanning')
                self._statistics_tracker = CorrelationStatisticsTracker(engine_type)
            
            if event.event_type == ProgressEventType.SCANNING_START:
                self._last_progress_line_index = -1  # Reset progress line tracking
                progress = event.overall_progress
                
                # Initialize statistics tracker
                if self._statistics_tracker:
                    self._statistics_tracker.start_correlation(progress.total_windows)
                
                self.append_progress(f"\n[Correlation] Starting correlation engine...")
                self.append_progress(f"[Correlation] Processing {progress.total_windows} items")
                
                # Display initial percentage
                self._display_percentage_analysis(progress)
            
            elif event.event_type == ProgressEventType.WINDOW_PROGRESS:
                # Update statistics tracker
                if self._statistics_tracker:
                    self._statistics_tracker.update_progress(event.overall_progress)
                
                # Dynamic progress update with percentage
                progress = event.overall_progress
                percentage = progress.completion_percentage
                
                # Only update percentage display if it changed significantly (every 5%)
                if abs(percentage - self._last_percentage_display) >= 5.0:
                    self._display_percentage_analysis(progress)
                    self._last_percentage_display = percentage
                
                progress_msg = f"    [Working] {percentage:.1f}% complete - {progress.matches_found} matches found"
                self.update_progress_line(progress_msg)
            
            elif event.event_type == ProgressEventType.WINDOW_COMPLETE:
                # Update statistics tracker
                if self._statistics_tracker:
                    self._statistics_tracker.update_progress(event.overall_progress)
                
                # Also update on window complete
                progress = event.overall_progress
                percentage = progress.completion_percentage
                progress_msg = f"    [Working] {percentage:.1f}% complete - {progress.matches_found} matches found"
                self.update_progress_line(progress_msg)
            
            elif event.event_type == ProgressEventType.SCANNING_COMPLETE:
                # Mark completion in statistics tracker
                if self._statistics_tracker:
                    self._statistics_tracker.complete_correlation()
                
                # Reset dynamic line tracking before showing completion
                self._last_progress_line_index = -1
                progress = event.overall_progress
                self.append_progress(f"\n[Correlation] Complete! Found {progress.matches_found} matches")
                
                # Display final percentage analysis
                self._display_final_percentage_analysis()
            
            elif event.event_type == ProgressEventType.ERROR_OCCURRED:
                # Mark failure in statistics tracker
                if self._statistics_tracker:
                    self._statistics_tracker.fail_correlation(event.message or "Unknown error")
                
                # Reset dynamic line tracking before showing error
                self._last_progress_line_index = -1
                self.append_progress(f"\n[Error] {event.message}")
                if event.error_details:
                    # Show error details on separate lines
                    for line in event.error_details.split('\n')[:5]:  # Show first 5 lines
                        if line.strip():
                            self.append_progress(f"  {line}")
            
            elif event.event_type == ProgressEventType.STREAMING_ENABLED:
                self._last_progress_line_index = -1
                self.append_progress(f"\n[Info] Streaming mode enabled: {event.message}")
            
            elif event.event_type == ProgressEventType.MEMORY_WARNING:
                self._last_progress_line_index = -1
                self.append_progress(f"\n[Warning] {event.message}")
                
        except Exception as e:
            # If event handling fails, silently continue
            pass
    
    def _display_percentage_analysis(self, progress):
        """
        Display percentage analysis of correlation progress.
        
        Args:
            progress: OverallProgressData object
        """
        try:
            percentage_complete = progress.completion_percentage
            percentage_remaining = 100.0 - percentage_complete
            
            item_type = "identities" if hasattr(self._statistics_tracker, 'engine_type') and \
                       self._statistics_tracker.engine_type == "identity_based" else "windows"
            
            self.append_progress(f"\n[Progress Analysis]")
            self.append_progress(f"  Completed: {percentage_complete:.1f}% ({progress.windows_processed:,} {item_type})")
            self.append_progress(f"  Remaining: {percentage_remaining:.1f}% ({progress.total_windows - progress.windows_processed:,} {item_type})")
            
            if progress.time_remaining_seconds and progress.time_remaining_seconds > 0:
                remaining_time = timedelta(seconds=progress.time_remaining_seconds)
                self.append_progress(f"  Estimated Time Remaining: {remaining_time}")
            
            if progress.processing_rate_windows_per_second and progress.processing_rate_windows_per_second > 0:
                self.append_progress(f"  Processing Rate: {progress.processing_rate_windows_per_second:.2f} {item_type}/sec")
            
        except Exception as e:
            # Silently fail if percentage display fails
            pass
    
    def _display_final_percentage_analysis(self):
        """Display final percentage analysis at completion"""
        try:
            if not self._statistics_tracker:
                return
            
            stats = self._statistics_tracker.get_current_progress()
            
            self.append_progress(f"\n{'='*60}")
            self.append_progress("CORRELATION PERCENTAGE ANALYSIS")
            self.append_progress(f"{'='*60}")
            
            item_type = "identities" if stats.engine_type == "identity_based" else "windows"
            
            self.append_progress(f"Total {item_type} processed: {stats.processed_items:,}")
            self.append_progress(f"Completion: 100.0%")
            self.append_progress(f"Matches found: {stats.matches_found:,}")
            
            if stats.elapsed_seconds > 0:
                elapsed = timedelta(seconds=stats.elapsed_seconds)
                self.append_progress(f"Total time: {elapsed}")
                
                if stats.processed_items > 0:
                    avg_rate = stats.processed_items / stats.elapsed_seconds
                    self.append_progress(f"Average rate: {avg_rate:.2f} {item_type}/sec")
            
            # Calculate match rate
            if stats.processed_items > 0:
                match_rate = (stats.matches_found / stats.processed_items) * 100.0
                self.append_progress(f"Match rate: {match_rate:.2f}% of {item_type} had matches")
            
            self.append_progress(f"{'='*60}")
            
        except Exception as e:
            # Silently fail if final analysis fails
            pass
    
    def _handle_enhanced_progress_event(self, enhanced_event):
        """
        Handle enhanced progress event with semantic and scoring integration.
        
        Args:
            enhanced_event: EnhancedProgressEvent with integration data
        """
        # Use the formatted message if available
        if enhanced_event.formatted_message:
            self.append_progress(enhanced_event.formatted_message)
        
        # Add semantic mapping statistics if available
        if enhanced_event.semantic_stats:
            self._display_semantic_stats(enhanced_event.semantic_stats)
        
        # Add scoring statistics if available
        if enhanced_event.scoring_stats:
            self._display_scoring_stats(enhanced_event.scoring_stats)
        
        # Add engine type and configuration display
        if enhanced_event.engine_type and enhanced_event.engine_metadata:
            self._display_engine_info(enhanced_event.engine_type, enhanced_event.engine_metadata)
        
        # Handle original event for backward compatibility
        if hasattr(enhanced_event, 'original_event') and enhanced_event.original_event:
            # Only handle if it's a real ProgressEvent, not our mock
            if hasattr(enhanced_event.original_event, 'data'):
                self._handle_legacy_progress_event(enhanced_event.original_event)
    
    def _handle_legacy_progress_event(self, event):
        """
        Handle legacy progress event (backward compatibility).
        Simplified to show only that correlation is working.
        
        Args:
            event: ProgressEvent object with event_type and data
        """
        event_type = event.event_type
        data = event.data
        
        if event_type == "wing_start":
            self._last_progress_line_index = -1  # Reset progress line tracking
            self.append_progress(f"\n[Correlation] Processing Wing: {data['wing_name']}")
        
        elif event_type == "correlation_start":
            self.append_progress("[Correlation] Starting correlation analysis...")
        
        elif event_type == "anchor_progress" or event_type == "summary_progress":
            # Simple progress message without anchor details
            matches_found = data.get('matches_found', 0)
            progress_msg = f"    [Working] Correlation in progress... {matches_found} matches found"
            self.update_progress_line(progress_msg)
    
    def _display_semantic_stats(self, semantic_stats):
        """
        Display semantic mapping statistics.
        
        Args:
            semantic_stats: Dictionary with semantic mapping statistics
        """
        if not semantic_stats:
            return
        
        mappings_applied = semantic_stats.get('mappings_applied', 0)
        total_records = semantic_stats.get('total_records_processed', 0)
        unmapped_fields = semantic_stats.get('unmapped_fields', 0)
        pattern_matches = semantic_stats.get('pattern_matches', 0)
        exact_matches = semantic_stats.get('exact_matches', 0)
        case_specific_used = semantic_stats.get('case_specific_mappings_used', 0)
        global_used = semantic_stats.get('global_mappings_used', 0)
        fallback_count = semantic_stats.get('fallback_count', 0)
        
        if mappings_applied > 0:
            mapping_rate = (mappings_applied / max(1, total_records)) * 100
            self.append_progress(f"[Semantic] Applied {mappings_applied} mappings ({mapping_rate:.1f}% coverage)")
            
            if pattern_matches > 0 or exact_matches > 0:
                self.append_progress(f"[Semantic] Pattern matches: {pattern_matches}, Exact matches: {exact_matches}")
            
            if case_specific_used > 0 or global_used > 0:
                self.append_progress(f"[Semantic] Global: {global_used}, Case-specific: {case_specific_used}")
            
            if unmapped_fields > 0:
                self.append_progress(f"[Semantic] Unmapped fields: {unmapped_fields}")
            
            if fallback_count > 0:
                self.append_progress(f"[Semantic] Fallback to raw values: {fallback_count}")
        else:
            if total_records > 0:
                self.append_progress(f"[Semantic] No mappings applied ({total_records} records processed)")
            else:
                self.append_progress("[Semantic] No semantic mapping activity")
    
    def _display_scoring_stats(self, scoring_stats):
        """
        Display weighted scoring statistics.
        
        Args:
            scoring_stats: Dictionary with scoring statistics
        """
        if not scoring_stats:
            return
        
        scores_calculated = scoring_stats.get('scores_calculated', 0)
        average_score = scoring_stats.get('average_score', 0.0)
        highest_score = scoring_stats.get('highest_score', 0.0)
        lowest_score = scoring_stats.get('lowest_score', 0.0)
        fallback_count = scoring_stats.get('fallback_to_simple_count', 0)
        total_matches = scoring_stats.get('total_matches_scored', 0)
        case_specific_used = scoring_stats.get('case_specific_configs_used', 0)
        global_used = scoring_stats.get('global_configs_used', 0)
        validation_failures = scoring_stats.get('validation_failures', 0)
        
        if scores_calculated > 0:
            self.append_progress(f"[Scoring] Calculated {scores_calculated} weighted scores (avg: {average_score:.3f})")
            
            if highest_score > 0 and lowest_score >= 0:
                self.append_progress(f"[Scoring] Score range: {lowest_score:.2f} - {highest_score:.2f}")
            
            if case_specific_used > 0 or global_used > 0:
                self.append_progress(f"[Scoring] Global configs: {global_used}, Case-specific: {case_specific_used}")
            
            if fallback_count > 0:
                fallback_rate = (fallback_count / max(1, total_matches)) * 100
                self.append_progress(f"[Scoring] Fallback to simple count: {fallback_count} ({fallback_rate:.1f}%)")
            
            if validation_failures > 0:
                self.append_progress(f"[Scoring] Configuration validation failures: {validation_failures}")
        else:
            if total_matches > 0:
                self.append_progress(f"[Scoring] No weighted scores calculated ({total_matches} matches processed)")
            else:
                self.append_progress("[Scoring] No scoring activity")
    
    def _display_engine_info(self, engine_type, engine_metadata):
        """
        Display engine type and configuration information.
        
        Args:
            engine_type: Type of correlation engine
            engine_metadata: Engine-specific metadata
        """
        if not engine_metadata:
            return
        
        # Display engine type
        engine_name = "Identity-Based" if engine_type == "identity_based" else "Time-Window"
        self.append_progress(f"[Engine] Type: {engine_name}")
        
        # Display relevant configuration
        if 'total_windows' in engine_metadata:
            total_items = engine_metadata['total_windows']
            item_type = "identities" if engine_type == "identity_based" else "windows"
            self.append_progress(f"[Engine] Processing {total_items} {item_type}")
        
        if 'window_size_minutes' in engine_metadata:
            window_size = engine_metadata['window_size_minutes']
            self.append_progress(f"[Engine] Window size: {window_size} minutes")
        
        if 'time_range_start' in engine_metadata and 'time_range_end' in engine_metadata:
            start_time = engine_metadata['time_range_start']
            end_time = engine_metadata['time_range_end']
            if hasattr(start_time, 'strftime') and hasattr(end_time, 'strftime'):
                start_str = start_time.strftime("%Y-%m-%d %H:%M")
                end_str = end_time.strftime("%Y-%m-%d %H:%M")
                self.append_progress(f"[Engine] Time range: {start_str} to {end_str}")
        
        if 'parallel_processing' in engine_metadata:
            parallel = engine_metadata['parallel_processing']
            if parallel:
                max_workers = engine_metadata.get('max_workers', 1)
                self.append_progress(f"[Engine] Parallel processing: {max_workers} workers")
            else:
                self.append_progress("[Engine] Sequential processing")
        
        if 'streaming_enabled' in engine_metadata:
            streaming = engine_metadata['streaming_enabled']
            if streaming:
                self.append_progress("[Engine] Streaming mode enabled")
        
        # Display integration features status
        semantic_enabled = engine_metadata.get('semantic_mapping_enabled', False)
        scoring_enabled = engine_metadata.get('weighted_scoring_enabled', False)
        
        integration_features = []
        if semantic_enabled:
            integration_features.append("Semantic Mapping")
        if scoring_enabled:
            integration_features.append("Weighted Scoring")
        
        if integration_features:
            self.append_progress(f"[Engine] Integration features: {', '.join(integration_features)}")
        else:
            self.append_progress("[Engine] No integration features enabled")
        
        # Display case-specific configuration if available
        case_id = engine_metadata.get('case_id')
        if case_id:
            self.append_progress(f"[Engine] Case ID: {case_id}")
        
        # Display memory configuration
        memory_limit = engine_metadata.get('memory_limit_mb')
        if memory_limit:
            self.append_progress(f"[Engine] Memory limit: {memory_limit} MB")
    
    def clear_progress(self):
        """Clear all progress messages."""
        self.clear()
        self._last_progress_line_index = -1
        self._last_progress_update = None
    
    def get_progress_text(self) -> str:
        """
        Get all progress text.
        
        Returns:
            Complete progress text
        """
        return self.toPlainText()
    
    def update_semantic_stats(self, semantic_stats):
        """
        Update semantic mapping statistics display.
        
        Args:
            semantic_stats: Dictionary with current semantic mapping statistics
        """
        self._display_semantic_stats(semantic_stats)
    
    def update_scoring_stats(self, scoring_stats):
        """
        Update weighted scoring statistics display.
        
        Args:
            scoring_stats: Dictionary with current scoring statistics
        """
        self._display_scoring_stats(scoring_stats)
    
    def update_integration_stats(self, semantic_stats=None, scoring_stats=None):
        """
        Update both semantic and scoring statistics in a single call.
        
        Args:
            semantic_stats: Optional semantic mapping statistics
            scoring_stats: Optional scoring statistics
        """
        if semantic_stats:
            self._display_semantic_stats(semantic_stats)
        
        if scoring_stats:
            self._display_scoring_stats(scoring_stats)
    
    def display_integration_summary(self, semantic_stats=None, scoring_stats=None, engine_metadata=None):
        """
        Display a comprehensive summary of integration features status.
        
        Args:
            semantic_stats: Semantic mapping statistics
            scoring_stats: Scoring statistics
            engine_metadata: Engine metadata
        """
        self.append_progress(f"\n{'='*50}")
        self.append_progress("INTEGRATION FEATURES SUMMARY")
        self.append_progress(f"{'='*50}")
        
        # Semantic mapping summary
        if semantic_stats:
            mappings_applied = semantic_stats.get('mappings_applied', 0)
            total_records = semantic_stats.get('total_records_processed', 0)
            
            if total_records > 0:
                mapping_rate = (mappings_applied / total_records) * 100
                status = "Active" if mappings_applied > 0 else "No mappings applied"
                self.append_progress(f"Semantic Mapping: {status} ({mapping_rate:.1f}% coverage)")
            else:
                self.append_progress("Semantic Mapping: No activity")
        else:
            self.append_progress("Semantic Mapping: Not available")
        
        # Scoring summary
        if scoring_stats:
            scores_calculated = scoring_stats.get('scores_calculated', 0)
            total_matches = scoring_stats.get('total_matches_scored', 0)
            average_score = scoring_stats.get('average_score', 0.0)
            
            if total_matches > 0:
                success_rate = (scores_calculated / total_matches) * 100
                status = f"Active ({success_rate:.1f}% success rate)"
                if scores_calculated > 0:
                    status += f", avg score: {average_score:.3f}"
                self.append_progress(f"Weighted Scoring: {status}")
            else:
                self.append_progress("Weighted Scoring: No activity")
        else:
            self.append_progress("Weighted Scoring: Not available")
        
        # Engine configuration summary
        if engine_metadata:
            semantic_enabled = engine_metadata.get('semantic_mapping_enabled', False)
            scoring_enabled = engine_metadata.get('weighted_scoring_enabled', False)
            case_id = engine_metadata.get('case_id')
            
            config_status = []
            if semantic_enabled:
                config_status.append("Semantic")
            if scoring_enabled:
                config_status.append("Scoring")
            
            if config_status:
                self.append_progress(f"Enabled features: {', '.join(config_status)}")
            else:
                self.append_progress("Enabled features: None")
            
            if case_id:
                self.append_progress(f"Case-specific config: {case_id}")
        
        self.append_progress(f"{'='*50}")
    
    def display_configuration_conflicts(self, conflicts):
        """
        Display configuration conflicts and their resolutions.
        
        Args:
            conflicts: List of configuration conflicts
        """
        if not conflicts:
            return
        
        self.append_progress(f"\n[Config] Configuration conflicts detected and resolved:")
        
        for i, conflict in enumerate(conflicts, 1):
            field = conflict.get('field', 'unknown')
            global_value = conflict.get('global_value', 'N/A')
            case_value = conflict.get('case_value', 'N/A')
            resolution = conflict.get('resolution', 'unknown')
            
            self.append_progress(f"[Config]   {i}. {field}: {global_value} -> {case_value} ({resolution})")
        
        self.append_progress(f"[Config] {len(conflicts)} conflicts resolved using case-specific precedence")
    
    def display_error_recovery(self, component, error_type, recovery_successful):
        """
        Display error recovery information.
        
        Args:
            component: Component that experienced the error (e.g., 'semantic', 'scoring')
            error_type: Type of error
            recovery_successful: Whether recovery was successful
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        status = "successful" if recovery_successful else "failed"
        
        self.append_progress(f"[{timestamp}] [{component.title()}] Error recovery {status}: {error_type}")
        
        if recovery_successful:
            self.append_progress(f"[{timestamp}] [{component.title()}] Component restored to working state")
        else:
            self.append_progress(f"[{timestamp}] [{component.title()}] Falling back to degraded mode")
    
    def display_engine_configuration(self, engine_type, config):
        """
        Display engine type and configuration at the start of correlation.
        
        Args:
            engine_type: Type of correlation engine ("identity_based" or "time_window")
            config: Engine configuration dictionary
        """
        self.append_progress(f"\n{'='*60}")
        self.append_progress(f"CORRELATION ENGINE CONFIGURATION")
        self.append_progress(f"{'='*60}")
        
        # Engine type
        engine_name = "Identity-Based" if engine_type == "identity_based" else "Time-Window"
        self.append_progress(f"Engine Type: {engine_name}")
        
        # Configuration details
        if 'total_windows' in config:
            total_items = config['total_windows']
            item_type = "identities" if engine_type == "identity_based" else "windows"
            self.append_progress(f"Total {item_type}: {total_items}")
        
        if 'window_size_minutes' in config:
            window_size = config['window_size_minutes']
            self.append_progress(f"Window size: {window_size} minutes")
        
        if 'time_range_start' in config and 'time_range_end' in config:
            start_time = config['time_range_start']
            end_time = config['time_range_end']
            if hasattr(start_time, 'strftime') and hasattr(end_time, 'strftime'):
                start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
                end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
                self.append_progress(f"Time range: {start_str} to {end_str}")
        
        if 'parallel_processing' in config:
            parallel = config['parallel_processing']
            if parallel:
                max_workers = config.get('max_workers', 1)
                self.append_progress(f"Processing mode: Parallel ({max_workers} workers)")
            else:
                self.append_progress("Processing mode: Sequential")
        
        # Integration features
        semantic_enabled = config.get('semantic_mapping_enabled', False)
        scoring_enabled = config.get('weighted_scoring_enabled', False)
        
        self.append_progress(f"Semantic mapping: {'Enabled' if semantic_enabled else 'Disabled'}")
        self.append_progress(f"Weighted scoring: {'Enabled' if scoring_enabled else 'Disabled'}")
        
        # Case-specific configuration
        if config.get('case_id'):
            self.append_progress(f"Case ID: {config['case_id']}")
        
        # Memory and streaming configuration
        memory_limit = config.get('memory_limit_mb')
        if memory_limit:
            self.append_progress(f"Memory limit: {memory_limit} MB")
        
        streaming_enabled = config.get('streaming_enabled', False)
        if streaming_enabled:
            self.append_progress("Streaming mode: Enabled")
        
        # Configuration sources
        config_sources = []
        if config.get('use_case_specific_semantic_mappings'):
            config_sources.append("Case-specific semantic mappings")
        if config.get('use_case_specific_scoring_weights'):
            config_sources.append("Case-specific scoring weights")
        if config.get('use_global_semantic_mappings', True):
            config_sources.append("Global semantic mappings")
        if config.get('use_global_scoring_weights', True):
            config_sources.append("Global scoring weights")
        
        if config_sources:
            self.append_progress(f"Configuration sources: {', '.join(config_sources)}")
        
        self.append_progress(f"{'='*60}")
    
    def display_final_statistics(self, final_stats):
        """
        Display comprehensive final statistics at correlation completion.
        
        Args:
            final_stats: Dictionary with final correlation statistics
        """
        self.append_progress(f"\n{'='*60}")
        self.append_progress(f"CORRELATION COMPLETE - FINAL STATISTICS")
        self.append_progress(f"{'='*60}")
        
        # Basic correlation statistics
        matches_found = final_stats.get('matches_found', 0)
        windows_processed = final_stats.get('windows_processed', 0)
        total_time = final_stats.get('total_time_seconds', 0)
        
        self.append_progress(f"Matches found: {matches_found}")
        self.append_progress(f"Windows processed: {windows_processed}")
        
        if total_time > 0:
            minutes = int(total_time // 60)
            seconds = int(total_time % 60)
            self.append_progress(f"Total time: {minutes}m {seconds}s")
            
            # Performance metrics
            if windows_processed > 0:
                avg_time_per_window = total_time / windows_processed
                self.append_progress(f"Average time per window: {avg_time_per_window:.2f}s")
        
        # Semantic mapping statistics
        semantic_stats = final_stats.get('semantic_stats', {})
        if semantic_stats:
            self.append_progress(f"\nSemantic Mapping:")
            mappings_applied = semantic_stats.get('mappings_applied', 0)
            total_records = semantic_stats.get('total_records_processed', 0)
            
            if total_records > 0:
                mapping_rate = (mappings_applied / total_records) * 100
                self.append_progress(f"  Mappings applied: {mappings_applied} ({mapping_rate:.1f}% coverage)")
            
            pattern_matches = semantic_stats.get('pattern_matches', 0)
            exact_matches = semantic_stats.get('exact_matches', 0)
            if pattern_matches > 0 or exact_matches > 0:
                self.append_progress(f"  Pattern matches: {pattern_matches}, Exact matches: {exact_matches}")
            
            case_specific_used = semantic_stats.get('case_specific_mappings_used', 0)
            global_used = semantic_stats.get('global_mappings_used', 0)
            if case_specific_used > 0 or global_used > 0:
                self.append_progress(f"  Global mappings: {global_used}, Case-specific: {case_specific_used}")
            
            unmapped_fields = semantic_stats.get('unmapped_fields', 0)
            if unmapped_fields > 0:
                self.append_progress(f"  Unmapped fields: {unmapped_fields}")
            
            fallback_count = semantic_stats.get('fallback_count', 0)
            if fallback_count > 0:
                self.append_progress(f"  Fallback to raw values: {fallback_count}")
            
            # Error handling statistics
            manager_failures = semantic_stats.get('manager_failure_count', 0)
            recovery_attempts = semantic_stats.get('recovery_attempt_count', 0)
            successful_recoveries = semantic_stats.get('successful_recovery_count', 0)
            
            if manager_failures > 0:
                self.append_progress(f"  Manager failures: {manager_failures}")
                if recovery_attempts > 0:
                    recovery_rate = (successful_recoveries / recovery_attempts) * 100
                    self.append_progress(f"  Recovery attempts: {recovery_attempts} ({recovery_rate:.1f}% successful)")
        
        # Weighted scoring statistics
        scoring_stats = final_stats.get('scoring_stats', {})
        if scoring_stats:
            self.append_progress(f"\nWeighted Scoring:")
            scores_calculated = scoring_stats.get('scores_calculated', 0)
            total_matches_scored = scoring_stats.get('total_matches_scored', 0)
            average_score = scoring_stats.get('average_score', 0.0)
            highest_score = scoring_stats.get('highest_score', 0.0)
            lowest_score = scoring_stats.get('lowest_score', 0.0)
            
            if scores_calculated > 0:
                success_rate = (scores_calculated / max(1, total_matches_scored)) * 100
                self.append_progress(f"  Scores calculated: {scores_calculated}/{total_matches_scored} ({success_rate:.1f}%)")
                self.append_progress(f"  Score range: {lowest_score:.3f} - {highest_score:.3f} (avg: {average_score:.3f})")
            
            fallback_count = scoring_stats.get('fallback_to_simple_count', 0)
            if fallback_count > 0:
                fallback_rate = (fallback_count / max(1, total_matches_scored)) * 100
                self.append_progress(f"  Simple count fallbacks: {fallback_count} ({fallback_rate:.1f}%)")
            
            # Configuration usage
            case_specific_used = scoring_stats.get('case_specific_configs_used', 0)
            global_used = scoring_stats.get('global_configs_used', 0)
            if case_specific_used > 0 or global_used > 0:
                total_configs = case_specific_used + global_used
                case_percentage = (case_specific_used / total_configs) * 100 if total_configs > 0 else 0
                self.append_progress(f"  Global configs: {global_used}, Case-specific: {case_specific_used} ({case_percentage:.1f}%)")
            
            # Error statistics
            config_errors = scoring_stats.get('configuration_errors', 0)
            validation_failures = scoring_stats.get('validation_failures', 0)
            conflict_resolutions = scoring_stats.get('conflict_resolutions', 0)
            
            if config_errors > 0 or validation_failures > 0:
                self.append_progress(f"  Configuration errors: {config_errors}, Validation failures: {validation_failures}")
            
            if conflict_resolutions > 0:
                self.append_progress(f"  Configuration conflicts resolved: {conflict_resolutions}")
        
        # Memory and performance statistics
        memory_stats = final_stats.get('memory_stats', {})
        if memory_stats:
            peak_memory = memory_stats.get('peak_usage_mb', 0)
            if peak_memory > 0:
                self.append_progress(f"\nMemory usage: Peak {peak_memory:.1f} MB")
            
            memory_warnings = memory_stats.get('memory_warnings', 0)
            if memory_warnings > 0:
                self.append_progress(f"Memory warnings issued: {memory_warnings}")
        
        streaming_enabled = final_stats.get('streaming_enabled', False)
        if streaming_enabled:
            self.append_progress("Streaming mode was enabled during processing")
            
            streaming_stats = final_stats.get('streaming_stats', {})
            if streaming_stats:
                records_streamed = streaming_stats.get('records_streamed', 0)
                if records_streamed > 0:
                    self.append_progress(f"Records processed in streaming mode: {records_streamed}")
        
        # Engine-specific statistics
        engine_type = final_stats.get('engine_type')
        if engine_type:
            engine_name = "Identity-Based" if engine_type == "identity_based" else "Time-Window"
            self.append_progress(f"\nEngine: {engine_name}")
            
            if engine_type == "identity_based":
                unique_identities = final_stats.get('unique_identities_processed', 0)
                if unique_identities > 0:
                    self.append_progress(f"Unique identities processed: {unique_identities}")
            elif engine_type == "time_window":
                window_size = final_stats.get('window_size_minutes', 0)
                if window_size > 0:
                    self.append_progress(f"Window size used: {window_size} minutes")
        
        self.append_progress(f"{'='*60}")
        self.append_progress("Correlation analysis complete.")
        self.append_progress("")

    # Error Visualization Methods
    
    def display_error(self, error_message: str, severity: str = "medium", 
                     error_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        """
        Display an error message with severity-based coloring.
        
        Args:
            error_message: Error message to display
            severity: Error severity (critical, high, medium, low, info)
            error_id: Optional unique identifier for the error
            details: Optional detailed error information for dialog display
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = SEVERITY_COLORS.get(severity.lower(), SEVERITY_COLORS["medium"])
        
        # Format the error message with severity prefix
        severity_prefix = f"[{severity.upper()}]"
        formatted_message = f'<span style="color: {color};">[{timestamp}] {severity_prefix} {error_message}</span>'
        
        # Store details for potential dialog display
        if error_id and details:
            self._error_details[error_id] = {
                'message': error_message,
                'severity': severity,
                'timestamp': timestamp,
                'details': details
            }
        
        # Append with HTML formatting
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.insertHtml(formatted_message + "<br>")
        
        # Auto-scroll to bottom
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def display_aggregated_errors(self, aggregated_errors: Dict[str, Any]):
        """
        Display aggregated error summary.
        
        Args:
            aggregated_errors: Dictionary with error counts by type, component, severity
        """
        total_errors = aggregated_errors.get('total_errors', 0)
        
        if total_errors == 0:
            self.append_progress("[Errors] No errors recorded")
            return
        
        self.append_progress(f"\n{'='*50}")
        self.append_progress("ERROR SUMMARY")
        self.append_progress(f"{'='*50}")
        self.append_progress(f"Total errors: {total_errors}")
        
        # By severity
        by_severity = aggregated_errors.get('by_severity', {})
        if by_severity:
            self.append_progress("\nBy Severity:")
            for severity, count in sorted(by_severity.items(), 
                                         key=lambda x: ['critical', 'high', 'medium', 'low', 'info'].index(x[0]) 
                                         if x[0] in ['critical', 'high', 'medium', 'low', 'info'] else 99):
                color = SEVERITY_COLORS.get(severity, "#FFFFFF")
                self.display_error(f"  {severity}: {count}", severity=severity)
        
        # By component
        by_component = aggregated_errors.get('by_component', {})
        if by_component:
            self.append_progress("\nBy Component:")
            for component, count in by_component.items():
                self.append_progress(f"  {component}: {count}")
        
        # By error type
        by_type = aggregated_errors.get('by_type', {})
        if by_type:
            self.append_progress("\nBy Error Type:")
            for error_type, count in sorted(by_type.items(), key=lambda x: -x[1])[:5]:  # Top 5
                self.append_progress(f"  {error_type}: {count}")
        
        # Recovery stats
        recovery_stats = aggregated_errors.get('recovery_stats', {})
        if recovery_stats:
            total_attempts = recovery_stats.get('total_attempts', 0)
            successful = recovery_stats.get('successful', 0)
            if total_attempts > 0:
                success_rate = (successful / total_attempts) * 100
                self.append_progress(f"\nRecovery: {successful}/{total_attempts} successful ({success_rate:.1f}%)")
        
        self.append_progress(f"{'='*50}")
    
    def show_error_details_dialog(self, error_id: str):
        """
        Show a dialog with full error details including stack trace.
        
        Args:
            error_id: Unique identifier of the error to display
        """
        if error_id not in self._error_details:
            QMessageBox.warning(
                self,
                "Error Not Found",
                f"Error details not found for ID: {error_id}"
            )
            return
        
        error_info = self._error_details[error_id]
        details = error_info.get('details', {})
        
        # Build detailed message
        detail_text = f"Error: {error_info['message']}\n"
        detail_text += f"Severity: {error_info['severity']}\n"
        detail_text += f"Time: {error_info['timestamp']}\n"
        detail_text += "\n--- Details ---\n"
        
        if 'error_type' in details:
            detail_text += f"Type: {details['error_type']}\n"
        
        if 'error_message' in details:
            detail_text += f"Message: {details['error_message']}\n"
        
        if 'stack_trace' in details:
            detail_text += f"\n--- Stack Trace ---\n{details['stack_trace']}\n"
        
        if 'error_attributes' in details:
            detail_text += "\n--- Attributes ---\n"
            for key, value in details['error_attributes'].items():
                detail_text += f"  {key}: {value}\n"
        
        # Show in message box
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Error Details")
        msg_box.setText(f"Error: {error_info['message']}")
        msg_box.setDetailedText(detail_text)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.exec_()
    
    def display_error_from_integration(self, integration_error):
        """
        Display an error from the IntegrationErrorHandler.
        
        Args:
            integration_error: IntegrationError object from integration_error_handler
        """
        # Extract information from IntegrationError
        component = integration_error.component.value if hasattr(integration_error.component, 'value') else str(integration_error.component)
        severity = integration_error.severity.value if hasattr(integration_error.severity, 'value') else str(integration_error.severity)
        message = f"[{component}] {integration_error.message}"
        
        # Generate error ID
        error_id = f"{component}_{integration_error.timestamp.strftime('%H%M%S%f')}"
        
        # Prepare details
        details = {
            'error_type': integration_error.error_type,
            'error_message': integration_error.message,
            'component': component,
            'context': integration_error.context,
            'additional_data': integration_error.additional_data
        }
        
        # Add stack trace if available
        if integration_error.additional_data and 'stack_trace' in integration_error.additional_data:
            details['stack_trace'] = integration_error.additional_data['stack_trace']
        
        # Display the error
        self.display_error(message, severity=severity, error_id=error_id, details=details)
        
        # Log recovery information if available
        if integration_error.recovery_attempted:
            if integration_error.recovery_successful:
                self.append_progress(f"  ✓ Recovery successful")
            else:
                self.append_progress(f"  ✗ Recovery failed")
        
        if integration_error.fallback_applied:
            fallback_name = integration_error.fallback_applied.value if hasattr(integration_error.fallback_applied, 'value') else str(integration_error.fallback_applied)
            self.append_progress(f"  → Fallback applied: {fallback_name}")

    # Engine-Specific Progress Formatting
    
    def display_progress_update(self, processed: int, total: int, matches: int = 0,
                               engine_type: str = "time_window", rate: Optional[float] = None):
        """
        Display a progress update with engine-specific terminology.
        
        Args:
            processed: Number of items processed
            total: Total number of items
            matches: Number of matches found
            engine_type: Engine type for terminology
            rate: Processing rate (items per second)
        """
        # Get terminology
        if engine_type == "identity_based":
            unit = "identities"
            verb = "correlated"
        else:
            unit = "windows"
            verb = "processed"
        
        # Calculate percentage
        percentage = (processed / total * 100) if total > 0 else 0
        
        # Build message
        message = f"[Progress] {processed}/{total} {unit} {verb} ({percentage:.1f}%)"
        
        if matches > 0:
            message += f", {matches} matches found"
        
        if rate is not None and rate > 0:
            message += f" ({rate:.1f} {unit}/sec)"
        
        self.append_progress(message)
    
    def display_indeterminate_progress(self, message: str, engine_type: str = "time_window"):
        """
        Display indeterminate progress when total count is unknown.
        
        Args:
            message: Progress message
            engine_type: Engine type for context
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Use animated indicator
        indicator = "⏳"
        
        self.append_progress(f"[{timestamp}] {indicator} {message}")
    
    def display_completion_summary(self, total_items: int, total_matches: int, 
                                  processing_time_seconds: float, engine_type: str = "time_window"):
        """
        Display completion summary with total matches and processing time.
        
        Args:
            total_items: Total items processed
            total_matches: Total matches found
            processing_time_seconds: Total processing time
            engine_type: Engine type for terminology
        """
        # Get terminology
        if engine_type == "identity_based":
            unit = "identities"
            verb = "correlated"
        else:
            unit = "windows"
            verb = "scanned"
        
        # Format time
        if processing_time_seconds >= 60:
            minutes = int(processing_time_seconds // 60)
            seconds = int(processing_time_seconds % 60)
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{processing_time_seconds:.1f}s"
        
        self.append_progress(f"\n{'='*50}")
        self.append_progress("CORRELATION COMPLETE")
        self.append_progress(f"{'='*50}")
        self.append_progress(f"Total {unit} {verb}: {total_items:,}")
        self.append_progress(f"Total matches found: {total_matches:,}")
        self.append_progress(f"Processing time: {time_str}")
        
        # Calculate rate
        if processing_time_seconds > 0:
            rate = total_items / processing_time_seconds
            self.append_progress(f"Average rate: {rate:.1f} {unit}/sec")
        
        self.append_progress(f"{'='*50}")
    
    def display_status_line(self, status_type: str, **kwargs):
        """
        Display a dynamic status line based on status type.
        
        Args:
            status_type: Type of status (indexing, processing_window, processing_identity, 
                        querying, match_found, error)
            **kwargs: Status-specific parameters
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if status_type == "indexing":
            feather_name = kwargs.get('feather_name', 'Unknown')
            record_count = kwargs.get('record_count', 0)
            self.append_progress(f"[{timestamp}] Indexing {feather_name}: {record_count:,} records loaded")
        
        elif status_type == "processing_window":
            start_time = kwargs.get('start_time', '')
            end_time = kwargs.get('end_time', '')
            match_count = kwargs.get('match_count', 0)
            self.append_progress(f"[{timestamp}] Processing window {start_time} - {end_time}: {match_count} matches")
        
        elif status_type == "processing_identity":
            identity_value = kwargs.get('identity_value', 'Unknown')
            feather_count = kwargs.get('feather_count', 0)
            self.append_progress(f"[{timestamp}] Processing identity {identity_value}: {feather_count} feathers matched")
        
        elif status_type == "querying":
            feather_name = kwargs.get('feather_name', 'Unknown')
            query_time_ms = kwargs.get('query_time_ms', 0)
            self.append_progress(f"[{timestamp}] Querying {feather_name}: {query_time_ms}ms")
        
        elif status_type == "match_found":
            count = kwargs.get('count', 1)
            self.append_progress(f"[{timestamp}] ✓ Found {count} new match{'es' if count > 1 else ''}")
        
        elif status_type == "error":
            error_category = kwargs.get('category', 'Error')
            error_message = kwargs.get('message', 'Unknown error')
            self.display_error(f"[{error_category}] {error_message}", severity="medium")
    
    def get_correlation_statistics(self) -> Optional[Dict[str, Any]]:
        """
        Get current correlation statistics including percentage analysis.
        
        Returns:
            Dictionary with correlation statistics or None if not available
        """
        if not self._statistics_tracker:
            return None
        
        return self._statistics_tracker.get_progress_dict()
    
    def get_percentage_breakdown(self) -> Optional[Dict[str, float]]:
        """
        Get detailed percentage breakdown of correlation progress.
        
        Returns:
            Dictionary with percentage metrics or None if not available
        """
        if not self._statistics_tracker:
            return None
        
        return self._statistics_tracker.get_percentage_breakdown()
    
    def display_percentage_summary(self):
        """Display a summary of percentage statistics on demand"""
        if not self._statistics_tracker:
            self.append_progress("\n[Statistics] No correlation statistics available")
            return
        
        summary = self._statistics_tracker.get_summary()
        self.append_progress(f"\n{summary}")
    
    def reset_statistics(self):
        """Reset correlation statistics"""
        if self._statistics_tracker:
            self._statistics_tracker.reset()
        self._last_percentage_display = -1.0
