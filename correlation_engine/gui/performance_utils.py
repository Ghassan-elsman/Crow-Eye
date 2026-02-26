"""
Performance Optimization Utilities for Correlation GUI

This module provides utility classes for optimizing GUI performance during
correlation execution by implementing throttling, event queuing, and batching.
"""

import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BatchedTextBuffer:
    """Buffer for batched text insertions."""
    lines: List[str] = field(default_factory=list)
    total_chars: int = 0
    last_flush_time: float = field(default_factory=time.time)
    
    def add_line(self, text: str):
        """Add line to buffer."""
        self.lines.append(text)
        self.total_chars += len(text)
    
    def should_flush(self, batch_window_ms: int) -> bool:
        """Check if buffer should be flushed."""
        elapsed = (time.time() - self.last_flush_time) * 1000
        return elapsed >= batch_window_ms or self.total_chars > 10000
    
    def get_text(self) -> str:
        """Get combined text and clear buffer."""
        text = '\n'.join(self.lines)
        self.lines.clear()
        self.total_chars = 0
        self.last_flush_time = time.time()
        return text


class ProgressThrottler:
    """
    Utility class that limits the frequency of progress updates to the UI.
    
    Implements adaptive throttling based on queue backpressure to prevent
    UI thread blocking during high-frequency progress events.
    """
    
    def __init__(self, min_interval_ms: int = 100):
        """
        Initialize throttler with minimum interval between updates.
        
        Args:
            min_interval_ms: Minimum milliseconds between UI updates (default 100ms = 10 Hz)
        """
        self.base_interval_ms = min_interval_ms
        self.current_interval_ms = min_interval_ms
        self.max_interval_ms = 500  # Maximum 500ms (2 Hz) under heavy load
        self.last_update_time = 0.0
        self._force_next = False
    
    def should_update(self) -> bool:
        """
        Check if enough time has passed to allow an update.
        
        Returns:
            True if update should proceed, False if throttled
        """
        if self._force_next:
            self._force_next = False
            self.last_update_time = time.time()
            return True
        
        current_time = time.time()
        elapsed_ms = (current_time - self.last_update_time) * 1000
        
        if elapsed_ms >= self.current_interval_ms:
            self.last_update_time = current_time
            return True
        
        return False
    
    def force_update(self):
        """Force the next update to proceed regardless of throttling."""
        self._force_next = True
    
    def get_adaptive_interval(self, queue_size: int) -> int:
        """
        Calculate adaptive throttle interval based on queue backpressure.
        
        Args:
            queue_size: Current size of the event queue
            
        Returns:
            Adjusted interval in milliseconds
        """
        if queue_size > 500:
            # High backpressure - increase interval to reduce load
            self.current_interval_ms = min(
                self.base_interval_ms * 2,
                self.max_interval_ms
            )
        elif queue_size < 100:
            # Low backpressure - restore normal interval
            self.current_interval_ms = self.base_interval_ms
        
        return self.current_interval_ms


class ProgressEventQueue:
    """
    A bounded queue that manages progress events with backpressure handling.
    
    Automatically drops oldest events when full while preserving the most
    recent event for display.
    """
    
    def __init__(self, max_size: int = 1000):
        """
        Initialize bounded event queue.
        
        Args:
            max_size: Maximum number of events to buffer
        """
        self.max_size = max_size
        self._queue = deque(maxlen=max_size)
        self._dropped_count = 0
        self._warning_threshold = int(max_size * 0.8)
    
    def enqueue(self, event: dict) -> bool:
        """
        Add event to queue, dropping oldest if full.
        
        Args:
            event: Progress event dictionary
            
        Returns:
            True if event was added, False if queue was full and event was dropped
        """
        try:
            # Validate event structure
            if not isinstance(event, dict):
                logger.error(f"Invalid event type for enqueue: {type(event)}")
                return False
            
            current_size = len(self._queue)
            
            # Log warning when queue reaches 80% capacity
            if current_size >= self._warning_threshold and current_size % 100 == 0:
                logger.warning(f"Event queue at {current_size}/{self.max_size} capacity")
            
            # Check if we're at capacity
            if current_size >= self.max_size:
                # deque with maxlen automatically drops oldest, but log it
                logger.error(f"Event queue full, dropping oldest event")
                self._dropped_count += 1
            
            # Add event (deque handles size limiting automatically)
            self._queue.append(event)
            return True
        except Exception as e:
            logger.error(f"Error enqueueing event: {e}", exc_info=True)
            return False
    
    def dequeue_batch(self, max_count: int = 100) -> list:
        """
        Dequeue up to max_count events for processing.
        
        Args:
            max_count: Maximum events to dequeue in one batch
            
        Returns:
            List of events (may be fewer than max_count)
        """
        try:
            batch = []
            for _ in range(min(max_count, len(self._queue))):
                if self._queue:
                    batch.append(self._queue.popleft())
            return batch
        except Exception as e:
            logger.error(f"Error dequeuing batch: {e}", exc_info=True)
            return []  # Return empty list on error
    
    def size(self) -> int:
        """Return current queue size."""
        return len(self._queue)
    
    def clear(self):
        """Clear all queued events."""
        self._queue.clear()
        self._dropped_count = 0
    
    def get_dropped_count(self) -> int:
        """Return the number of events dropped due to queue overflow."""
        return self._dropped_count


class BatchedTextWidget:
    """
    A wrapper around QTextEdit that batches text insertions for efficiency.
    
    This class accumulates text in a buffer and flushes it to the widget
    in batches to minimize repaints and improve performance during
    high-frequency log message updates.
    """
    
    def __init__(self, text_widget, batch_window_ms: int = 200):
        """
        Initialize batched text widget wrapper.
        
        Args:
            text_widget: The QTextEdit to wrap
            batch_window_ms: Time window for batching insertions (default 200ms, increased from 100ms to reduce UI blocking)
        """
        from PyQt5.QtCore import QTimer
        
        self.text_widget = text_widget
        self.batch_window_ms = batch_window_ms
        self.buffer = BatchedTextBuffer()
        self._flush_timer = QTimer()
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self.flush)
        self._auto_scroll_enabled = True
        self._user_scrolled = False
        self._scroll_pending = False  # Track if scroll is already scheduled
        
        # Connect to scroll bar to detect manual scrolling
        if hasattr(text_widget, 'verticalScrollBar'):
            scrollbar = text_widget.verticalScrollBar()
            scrollbar.valueChanged.connect(self._on_scroll_changed)
    
    def append_text(self, text: str):
        """
        Queue text for batched insertion.
        
        Args:
            text: Text to append
        """
        try:
            if not text or not text.strip():
                return
            
            self.buffer.add_line(text)
            
            # Start or restart the flush timer
            if not self._flush_timer.isActive():
                self._flush_timer.start(self.batch_window_ms)
            
            # Flush immediately if buffer is too large
            if self.buffer.total_chars > 10000:
                self.flush()
        except Exception as e:
            logger.error(f"Error appending text to batched widget: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def flush(self):
        """Immediately flush all pending text to the widget."""
        try:
            from PyQt5.QtCore import QTimer
            from PyQt5.QtGui import QTextCursor
            
            if not self.buffer.lines:
                return
            
            # Stop the timer if it's running
            if self._flush_timer.isActive():
                self._flush_timer.stop()
            
            # Get all buffered text
            text = self.buffer.get_text()
            
            # Use setPlainText for large batches (more efficient than insertText)
            # For smaller batches, use insertText to preserve existing content
            if len(text) > 5000:
                # Large batch - use setPlainText with existing content
                existing = self.text_widget.toPlainText()
                combined = existing + '\n' + text if existing else text
                
                # Trim if needed before setting
                lines = combined.split('\n')
                if len(lines) > 10000:
                    lines = lines[-10000:]
                    combined = '\n'.join(lines)
                    logger.info(f"Trimmed to 10,000 lines during large batch flush")
                
                self.text_widget.setPlainText(combined)
            else:
                # Small batch - use cursor insertion
                cursor = self.text_widget.textCursor()
                cursor.movePosition(QTextCursor.End)
                cursor.insertText(text + '\n')
                self.text_widget.setTextCursor(cursor)
                
                # Trim content if needed
                self.trim_to_size()
            
            # Defer scrolling to next event loop iteration (only if not already pending)
            if self._auto_scroll_enabled and not self._user_scrolled and not self._scroll_pending:
                self._scroll_pending = True
                QTimer.singleShot(0, self._deferred_scroll)
        except Exception as e:
            logger.error(f"Error flushing batched text: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def trim_to_size(self, max_lines: int = 10000):
        """
        Trim widget content to maximum line count.
        
        Args:
            max_lines: Maximum lines to retain (default 10,000)
        """
        try:
            from PyQt5.QtGui import QTextCursor
            
            document = self.text_widget.document()
            line_count = document.blockCount()
            
            if line_count > max_lines:
                # Calculate how many lines to remove
                lines_to_remove = line_count - max_lines
                
                # Move cursor to start and select lines to remove
                cursor = QTextCursor(document)
                cursor.movePosition(QTextCursor.Start)
                for _ in range(lines_to_remove):
                    cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor)
                
                cursor.removeSelectedText()
                logger.info(f"Trimmed {lines_to_remove} lines from log output")
        except Exception as e:
            logger.error(f"Error trimming text widget: {e}", exc_info=True)
            # Continue processing - don't crash the UI
    
    def _deferred_scroll(self):
        """Perform deferred scroll operation."""
        try:
            self._scroll_pending = False  # Reset flag
            
            if not self._auto_scroll_enabled or self._user_scrolled:
                return
            
            # Scroll to bottom
            scrollbar = self.text_widget.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
            # Ensure cursor is visible
            cursor = self.text_widget.textCursor()
            cursor.movePosition(cursor.End)
            self.text_widget.setTextCursor(cursor)
            self.text_widget.ensureCursorVisible()
        except Exception as e:
            logger.error(f"Error in deferred scroll: {e}", exc_info=True)
            self._scroll_pending = False  # Reset flag on error
    
    def _on_scroll_changed(self, value):
        """
        Detect when user manually scrolls away from bottom.
        
        Args:
            value: Current scroll position
        """
        scrollbar = self.text_widget.verticalScrollBar()
        max_value = scrollbar.maximum()
        
        # If there's no scrollable content, we're always at bottom
        if max_value == 0:
            return
        
        # Check if user scrolled away from bottom
        # Allow small tolerance (5 pixels) for rounding errors
        at_bottom = value >= max_value - 5
        
        # If user scrolled away from bottom, disable auto-scroll
        if not at_bottom and self._auto_scroll_enabled:
            self._user_scrolled = True
        
        # If user scrolled back to bottom, re-enable auto-scroll
        if at_bottom and self._user_scrolled:
            self._user_scrolled = False
    
    def enable_auto_scroll(self):
        """Enable automatic scrolling to bottom."""
        self._auto_scroll_enabled = True
        self._user_scrolled = False
    
    def disable_auto_scroll(self):
        """Disable automatic scrolling to bottom."""
        self._auto_scroll_enabled = False
    
    def force_scroll_to_bottom(self):
        """Force scroll to bottom regardless of auto-scroll state."""
        from PyQt5.QtCore import QTimer
        
        self._user_scrolled = False
        QTimer.singleShot(0, self._deferred_scroll)


class ProgressMessageBuffer:
    """
    Memory-bounded buffer for storing progress messages.
    
    This class maintains a fixed-size buffer of progress messages to prevent
    unbounded memory growth during long-running correlation operations.
    When the buffer exceeds the maximum size, it automatically trims the
    oldest messages.
    """
    
    def __init__(self, max_messages: int = 1000, trim_count: int = 200):
        """
        Initialize progress message buffer.
        
        Args:
            max_messages: Maximum number of messages to store (default 1000)
            trim_count: Number of oldest messages to remove when limit exceeded (default 200)
        """
        self.max_messages = max_messages
        self.trim_count = trim_count
        self._messages = deque(maxlen=max_messages)
        self._total_messages_received = 0
        self._trim_operations = 0
    
    def add_message(self, message: str):
        """
        Add a progress message to the buffer.
        
        Args:
            message: Progress message to store
        """
        try:
            if not message:
                return
            
            self._total_messages_received += 1
            current_size = len(self._messages)
            
            # Check if we need to trim before adding
            if current_size >= self.max_messages:
                self._trim_messages()
            
            # Add the message
            self._messages.append(message)
            
        except Exception as e:
            logger.error(f"Error adding message to buffer: {e}", exc_info=True)
    
    def _trim_messages(self):
        """
        Trim oldest messages from the buffer.
        
        Removes the oldest trim_count messages when the buffer is full.
        """
        try:
            if len(self._messages) < self.max_messages:
                return
            
            # Remove oldest messages
            messages_to_remove = min(self.trim_count, len(self._messages))
            for _ in range(messages_to_remove):
                if self._messages:
                    self._messages.popleft()
            
            self._trim_operations += 1
            logger.info(
                f"Trimmed {messages_to_remove} oldest messages from buffer "
                f"(trim operation #{self._trim_operations})"
            )
            
        except Exception as e:
            logger.error(f"Error trimming message buffer: {e}", exc_info=True)
    
    def get_messages(self) -> List[str]:
        """
        Get all messages currently in the buffer.
        
        Returns:
            List of progress messages
        """
        return list(self._messages)
    
    def clear(self):
        """Clear all messages from the buffer."""
        message_count = len(self._messages)
        self._messages.clear()
        logger.debug(f"Cleared {message_count} messages from progress buffer")
    
    def size(self) -> int:
        """Return current number of messages in buffer."""
        return len(self._messages)
    
    def get_stats(self) -> dict:
        """
        Get buffer statistics.
        
        Returns:
            Dictionary with buffer statistics
        """
        return {
            'current_size': len(self._messages),
            'max_size': self.max_messages,
            'total_received': self._total_messages_received,
            'trim_operations': self._trim_operations,
            'messages_trimmed': self._trim_operations * self.trim_count
        }


class OptimizedHeartbeat:
    """
    An optimized heartbeat mechanism that provides visual feedback without overhead.
    
    This class updates only the progress bar format text (not the value) to create
    a simple animation that indicates the system is still working. This approach
    minimizes widget repaints and ensures minimal performance impact.
    """
    
    def __init__(self, progress_bar, interval_ms: int = 500):
        """
        Initialize optimized heartbeat.
        
        Args:
            progress_bar: QProgressBar to update
            interval_ms: Update interval in milliseconds (default 500ms = 2 Hz)
        """
        from PyQt5.QtCore import QTimer
        
        self.progress_bar = progress_bar
        self.interval_ms = interval_ms
        self._timer = QTimer()
        self._timer.timeout.connect(self.pulse)
        self._animation_state = 0
        self._animation_frames = ["Working.", "Working..", "Working..."]
    
    def start(self):
        """Start the heartbeat timer."""
        self._animation_state = 0
        self._timer.start(self.interval_ms)
        logger.debug(f"Heartbeat started with {self.interval_ms}ms interval")
    
    def stop(self):
        """Stop the heartbeat timer."""
        if self._timer.isActive():
            self._timer.stop()
            logger.debug("Heartbeat stopped")
    
    def pulse(self):
        """Update heartbeat indicator (called by timer)."""
        # Cycle through animation frames
        frame_text = self._animation_frames[self._animation_state]
        self._animation_state = (self._animation_state + 1) % len(self._animation_frames)
        
        # Update only the format text, not the value
        # This minimizes widget repaints
        self.progress_bar.setFormat(frame_text + " %p%")
