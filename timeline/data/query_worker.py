"""
Query Worker Thread
===================

This module provides a QThread-based worker for executing database queries
in the background without blocking the UI thread.

The QueryWorker handles:
- Executing time-range queries in a background thread
- Emitting progress signals during query execution
- Supporting query cancellation
- Handling errors gracefully
- Ensuring thread-safe database access

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal

# Configure logger
logger = logging.getLogger(__name__)


class QueryWorker(QThread):
    """
    Background worker thread for executing database queries.
    
    This worker executes time-range queries in a separate thread to prevent
    UI blocking. It emits signals to report progress and results.
    
    Signals:
        progress: Emitted during query execution (current, total, artifact_type, message)
        finished: Emitted when query completes successfully (events)
        error: Emitted when query fails (exception, error_message)
        cancelled: Emitted when query is cancelled
    """
    
    # Signals
    progress = pyqtSignal(int, int, str, str)  # current, total, artifact_type, message
    finished = pyqtSignal(list)  # events
    error = pyqtSignal(Exception, str)  # exception, error_message
    cancelled = pyqtSignal()
    
    def __init__(
        self,
        data_manager,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        artifact_types: Optional[List[str]] = None,
        max_events: Optional[int] = None
    ):
        """
        Initialize query worker.
        
        Args:
            data_manager: TimelineDataManager instance
            start_time: Start of time range (inclusive), or None for no lower bound
            end_time: End of time range (inclusive), or None for no upper bound
            artifact_types: List of artifact types to query, or None for all available
            max_events: Maximum number of events to load (for progressive loading), or None for all
        """
        super().__init__()
        
        self.data_manager = data_manager
        self.start_time = start_time
        self.end_time = end_time
        self.artifact_types = artifact_types
        self.max_events = max_events
        
        # Cancellation flag
        self._cancelled = False
        
        logger.debug(f"QueryWorker initialized: {start_time} to {end_time}, types: {artifact_types}, max: {max_events}")
    
    def run(self):
        """
        Execute the query in the background thread.
        
        This method is called when the thread starts. It queries each artifact
        type sequentially and emits progress signals with per-artifact details.
        
        Note: SQLite connections cannot be shared across threads, so we need
        to create new connections in this thread.
        """
        try:
            logger.info("QueryWorker started")
            
            # Get artifact types to query
            if self.artifact_types is None:
                artifact_types = self.data_manager.get_available_artifacts()
            else:
                # Filter to only available artifacts
                available = self.data_manager.get_available_artifacts()
                artifact_types = [at for at in self.artifact_types if at in available]
            
            if not artifact_types:
                logger.warning("No valid artifact types to query")
                self.finished.emit([])
                return
            
            # Query each artifact type
            all_events = []
            total = len(artifact_types)
            
            for idx, artifact_type in enumerate(artifact_types):
                # Check for cancellation before starting each artifact query
                if self._cancelled:
                    logger.info("Query cancelled by user")
                    self.cancelled.emit()
                    return
                
                # Check if we've reached the max_events limit
                if self.max_events and len(all_events) >= self.max_events:
                    logger.info(f"Reached max_events limit ({self.max_events}), stopping query")
                    break
                
                # Emit progress with current artifact type and event count
                self.progress.emit(
                    idx + 1,
                    total,
                    artifact_type,
                    f"Querying {artifact_type}... ({len(all_events):,} events loaded)"
                )
                
                try:
                    # Query this artifact type
                    # Note: _query_artifact_time_range will create new connections
                    # in this thread if needed
                    
                    # Calculate remaining events if max_events is set
                    remaining_events = None
                    if self.max_events:
                        remaining_events = self.max_events - len(all_events)
                        if remaining_events <= 0:
                            break  # Already reached limit
                    
                    events = self.data_manager._query_artifact_time_range(
                        artifact_type,
                        self.start_time,
                        self.end_time,
                        max_events=remaining_events
                    )
                    
                    all_events.extend(events)
                    logger.debug(f"Queried {len(events)} events from {artifact_type} (total: {len(all_events)})")
                    
                    # Emit progress update after querying this artifact to show updated event count
                    self.progress.emit(
                        idx + 1,
                        total,
                        artifact_type,
                        f"Loaded {len(events):,} events from {artifact_type} (total: {len(all_events):,})"
                    )
                
                except Exception as e:
                    # Log error but continue with other artifact types
                    logger.error(f"Failed to query {artifact_type}: {e}")
                    # Emit progress to show this artifact failed
                    self.progress.emit(
                        idx + 1,
                        total,
                        artifact_type,
                        f"Failed to query {artifact_type} ({len(all_events):,} events loaded)"
                    )
                    # Don't emit error signal here - just skip this artifact type
                    continue
            
            # Check for cancellation before sorting
            if self._cancelled:
                logger.info("Query cancelled by user")
                self.cancelled.emit()
                return
            
            # Sort events by timestamp
            try:
                all_events.sort(key=lambda e: e['timestamp'])
            except Exception as e:
                logger.error(f"Failed to sort events: {e}")
                # Continue with unsorted events
            
            logger.info(f"QueryWorker completed: {len(all_events)} events (max: {self.max_events})")
            
            # Emit finished signal with results
            self.finished.emit(all_events)
        
        except Exception as e:
            # Unexpected error during query
            logger.error(f"QueryWorker error: {e}", exc_info=True)
            self.error.emit(e, f"Failed to query timeline data: {str(e)}")
    
    def cancel(self):
        """
        Cancel the query operation.
        
        This sets a flag that is checked between artifact type queries.
        The query will stop at the next check point.
        """
        logger.info("QueryWorker cancellation requested")
        self._cancelled = True


class AggregationWorker(QThread):
    """
    Background worker thread for aggregating events.
    
    This worker aggregates events into time buckets in a separate thread
    to prevent UI blocking during aggregation calculations.
    
    Signals:
        progress: Emitted during aggregation (current, total, message)
        finished: Emitted when aggregation completes (aggregated_events)
        error: Emitted when aggregation fails (exception, error_message)
        cancelled: Emitted when aggregation is cancelled
    """
    
    # Signals
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(list)  # aggregated_events
    error = pyqtSignal(Exception, str)  # exception, error_message
    cancelled = pyqtSignal()
    
    def __init__(
        self,
        data_manager,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        artifact_types: Optional[List[str]] = None,
        bucket_size: str = 'hour'
    ):
        """
        Initialize aggregation worker.
        
        Args:
            data_manager: TimelineDataManager instance
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            artifact_types: List of artifact types to aggregate
            bucket_size: Size of time buckets ('minute', 'hour', 'day', etc.)
        """
        super().__init__()
        
        self.data_manager = data_manager
        self.start_time = start_time
        self.end_time = end_time
        self.artifact_types = artifact_types
        self.bucket_size = bucket_size
        
        # Cancellation flag
        self._cancelled = False
        
        logger.debug(f"AggregationWorker initialized: bucket_size={bucket_size}")
    
    def run(self):
        """
        Execute the aggregation in the background thread.
        """
        try:
            logger.info("AggregationWorker started")
            
            # Emit progress
            self.progress.emit(1, 3, "Querying events...")
            
            # Check for cancellation
            if self._cancelled:
                self.cancelled.emit()
                return
            
            # Query events
            events = self.data_manager.query_time_range(
                start_time=self.start_time,
                end_time=self.end_time,
                artifact_types=self.artifact_types
            )
            
            if not events:
                logger.info("No events to aggregate")
                self.finished.emit([])
                return
            
            # Emit progress
            self.progress.emit(2, 3, f"Aggregating {len(events)} events...")
            
            # Check for cancellation
            if self._cancelled:
                self.cancelled.emit()
                return
            
            # Aggregate events
            from timeline.data.event_aggregator import EventAggregator
            aggregator = EventAggregator()
            
            aggregated = aggregator.aggregate_events(
                events,
                bucket_size=self.bucket_size,
                start_time=self.start_time,
                end_time=self.end_time
            )
            
            # Emit progress
            self.progress.emit(3, 3, "Complete")
            
            logger.info(f"AggregationWorker completed: {len(aggregated)} buckets")
            
            # Emit finished signal
            self.finished.emit(aggregated)
        
        except Exception as e:
            logger.error(f"AggregationWorker error: {e}", exc_info=True)
            self.error.emit(e, f"Failed to aggregate events: {str(e)}")
    
    def cancel(self):
        """Cancel the aggregation operation."""
        logger.info("AggregationWorker cancellation requested")
        self._cancelled = True


class IndexingWorker(QThread):
    """
    Background worker thread for creating database indexes.
    
    This worker creates timestamp indexes in a separate thread to prevent
    UI blocking during the indexing process.
    
    Signals:
        progress: Emitted during indexing (current, total, artifact_type, message)
        finished: Emitted when indexing completes (results_dict)
        error: Emitted when indexing fails (exception, error_message)
    """
    
    # Signals
    progress = pyqtSignal(int, int, str, str)  # current, total, artifact_type, message
    finished = pyqtSignal(dict)  # results_dict
    error = pyqtSignal(Exception, str)  # exception, error_message
    
    def __init__(
        self,
        data_manager,
        artifact_types: Optional[List[str]] = None,
        skip_existing: bool = True
    ):
        """
        Initialize indexing worker.
        
        Args:
            data_manager: TimelineDataManager instance
            artifact_types: List of artifact types to index, or None for all
            skip_existing: If True, skip databases that are already indexed
        """
        super().__init__()
        
        self.data_manager = data_manager
        self.artifact_types = artifact_types
        self.skip_existing = skip_existing
        
        logger.debug(f"IndexingWorker initialized: types={artifact_types}, skip_existing={skip_existing}")
    
    def run(self):
        """
        Execute the indexing in the background thread.
        """
        try:
            logger.info("IndexingWorker started")
            
            # Create progress callback that emits signal
            def progress_callback(current, total, artifact_type, message):
                self.progress.emit(current, total, artifact_type, message)
            
            # Create indexes
            results = self.data_manager.create_timestamp_indexes(
                artifact_types=self.artifact_types,
                progress_callback=progress_callback,
                skip_existing=self.skip_existing
            )
            
            logger.info(f"IndexingWorker completed: {sum(results.values())}/{len(results)} successful")
            
            # Emit finished signal
            self.finished.emit(results)
        
        except Exception as e:
            logger.error(f"IndexingWorker error: {e}", exc_info=True)
            self.error.emit(e, f"Failed to create indexes: {str(e)}")
