"""
Power Event Extractor
=====================

This module extracts system power events from Windows Event Logs to display
on the forensic timeline. Power events include system startup, shutdown, sleep,
wake, and hibernate events that help investigators understand system availability
and identify suspicious activity patterns.

The PowerEventExtractor provides:
- Extraction of power events from Windows Event Log databases
- Mapping of Event IDs to power event types
- Timestamp parsing and metadata extraction
- Integration with timeline data manager

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import sqlite3
import os
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum

# Import timestamp parser utility
from timeline.utils.timestamp_parser import TimestampParser

# Configure logger
logger = logging.getLogger(__name__)


class PowerEventType(Enum):
    """Enumeration of system power event types."""
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    SLEEP = "sleep"
    WAKE = "wake"
    HIBERNATE = "hibernate"
    UNKNOWN = "unknown"


class PowerEventExtractor:
    """
    Extracts system power events from Windows Event Logs.
    
    This class handles extraction of power-related events from Windows Event Log
    databases, mapping Event IDs to power event types, and providing structured
    event data for timeline visualization.
    """
    
    # Windows Event Log Event ID mappings for power events
    # Format: Event ID -> (Event Type, Description, Log Source)
    EVENT_ID_MAPPINGS = {
        # System Event Log - Kernel-General (Event ID 12, 13)
        12: (PowerEventType.STARTUP, "System startup", "System"),
        13: (PowerEventType.SHUTDOWN, "System shutdown", "System"),
        
        # System Event Log - EventLog service (Event ID 6005, 6006, 6009)
        6005: (PowerEventType.STARTUP, "Event Log service started", "EventLog"),
        6006: (PowerEventType.SHUTDOWN, "Event Log service stopped", "EventLog"),
        6009: (PowerEventType.STARTUP, "System boot", "EventLog"),
        
        # System Event Log - User32 (Event ID 1074)
        1074: (PowerEventType.SHUTDOWN, "System shutdown initiated by user/process", "User32"),
        
        # System Event Log - Kernel-Power (Event ID 42, 1, 107, 109)
        42: (PowerEventType.SLEEP, "System entering sleep", "Kernel-Power"),
        1: (PowerEventType.WAKE, "System resumed from sleep", "Kernel-Power"),
        107: (PowerEventType.WAKE, "System resumed from sleep", "Kernel-Power"),
        109: (PowerEventType.SHUTDOWN, "Kernel power shutdown", "Kernel-Power"),
        
        # System Event Log - Power-Troubleshooter (Event ID 1)
        # Note: This is context-dependent, usually wake from sleep
        
        # Additional power-related events
        41: (PowerEventType.SHUTDOWN, "System rebooted without cleanly shutting down", "Kernel-Power"),
        6008: (PowerEventType.SHUTDOWN, "Unexpected shutdown", "EventLog"),
        
        # Hibernate events
        27: (PowerEventType.HIBERNATE, "System entering hibernation", "Kernel-Power"),
        28: (PowerEventType.WAKE, "System resumed from hibernation", "Kernel-Power"),
    }
    
    # Color mappings for power event types (for visualization)
    EVENT_TYPE_COLORS = {
        PowerEventType.STARTUP: "#00FF00",      # Green
        PowerEventType.SHUTDOWN: "#FF0000",     # Red
        PowerEventType.SLEEP: "#0000FF",        # Blue
        PowerEventType.WAKE: "#90EE90",         # Light Green
        PowerEventType.HIBERNATE: "#800080",    # Purple
        PowerEventType.UNKNOWN: "#808080",      # Gray
    }
    
    def __init__(self, event_log_db_path: Optional[str] = None):
        """
        Initialize PowerEventExtractor.
        
        Args:
            event_log_db_path: Path to Windows Event Log database (optional)
                              If not provided, will attempt to find it in standard locations
        """
        self.event_log_db_path = event_log_db_path
        self._connection = None
        self._power_events_cache = []
        
        logger.info("PowerEventExtractor initialized")
    
    def set_event_log_path(self, db_path: str):
        """
        Set the path to the Windows Event Log database.
        
        Args:
            db_path: Path to the event log database file
        """
        self.event_log_db_path = db_path
        # Close existing connection if any
        if self._connection:
            try:
                self._connection.close()
            except:
                pass
            self._connection = None
        
        logger.info(f"Event log database path set to: {db_path}")
    
    def _get_connection(self) -> Optional[sqlite3.Connection]:
        """
        Get or create database connection to event log database.
        
        Returns:
            sqlite3.Connection: Database connection, or None if database doesn't exist
        """
        if not self.event_log_db_path:
            logger.warning("Event log database path not set")
            return None
        
        # Return cached connection if exists
        if self._connection:
            try:
                self._connection.execute("SELECT 1")
                return self._connection
            except sqlite3.Error:
                # Connection is stale, create new one
                logger.warning("Stale connection detected, reconnecting")
                try:
                    self._connection.close()
                except:
                    pass
                self._connection = None
        
        # Verify database file exists
        if not os.path.exists(self.event_log_db_path):
            logger.error(f"Event log database not found: {self.event_log_db_path}")
            return None
        
        # Create connection
        try:
            conn = sqlite3.connect(self.event_log_db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            self._connection = conn
            logger.debug("Created event log database connection")
            return conn
        
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to event log database: {e}")
            return None
    
    def extract_power_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Extract power events from Windows Event Log database.
        
        Args:
            start_time: Start of time range (inclusive), or None for no lower bound
            end_time: End of time range (inclusive), or None for no upper bound
        
        Returns:
            List[Dict]: List of power event dictionaries with standardized structure
        """
        conn = self._get_connection()
        if not conn:
            logger.warning("Cannot extract power events: no database connection")
            return []
        
        power_events = []
        cursor = conn.cursor()
        
        try:
            # Query event log for power-related events
            # Assuming the event log database has a table structure like:
            # event_logs(event_id, timestamp, source, message, level, etc.)
            
            # Build query with event ID filter
            event_ids = list(self.EVENT_ID_MAPPINGS.keys())
            placeholders = ','.join('?' * len(event_ids))
            
            query = f"""
                SELECT *
                FROM event_logs
                WHERE event_id IN ({placeholders})
                AND timestamp IS NOT NULL
            """
            
            params = event_ids.copy()
            
            # Add time range filters
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())
            
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())
            
            query += " ORDER BY timestamp ASC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Convert rows to power event dictionaries
            for row in rows:
                event_id = row['event_id']
                timestamp_str = row['timestamp']
                
                # Parse timestamp
                timestamp = TimestampParser.parse_timestamp(timestamp_str)
                if not timestamp:
                    logger.warning(f"Failed to parse timestamp for event ID {event_id}: {timestamp_str}")
                    continue
                
                # Map event ID to power event type
                event_mapping = self.EVENT_ID_MAPPINGS.get(event_id)
                if not event_mapping:
                    logger.warning(f"Unknown power event ID: {event_id}")
                    event_type = PowerEventType.UNKNOWN
                    description = f"Unknown power event (ID {event_id})"
                    source = "Unknown"
                else:
                    event_type, description, source = event_mapping
                
                # Extract additional metadata
                try:
                    message = row['message'] if 'message' in row.keys() else ''
                except (KeyError, IndexError):
                    message = ''
                
                try:
                    level = row['level'] if 'level' in row.keys() else ''
                except (KeyError, IndexError):
                    level = ''
                
                # Create power event dictionary
                power_event = {
                    'id': f"power_{event_type.value}_{timestamp.isoformat()}",
                    'timestamp': timestamp,
                    'event_type': event_type.value,
                    'event_id': event_id,
                    'description': description,
                    'source': source,
                    'message': message,
                    'level': level,
                    'color': self.EVENT_TYPE_COLORS[event_type],
                    'artifact_type': 'PowerEvent',
                    'display_name': f"{event_type.value.title()} Event",
                }
                
                power_events.append(power_event)
            
            logger.info(f"Extracted {len(power_events)} power events")
        
        except sqlite3.Error as e:
            logger.error(f"Failed to query power events: {e}")
            return []
        
        except Exception as e:
            logger.error(f"Unexpected error extracting power events: {e}")
            return []
        
        return power_events
    
    def detect_system_sessions(self, power_events: List[Dict]) -> List[Dict]:
        """
        Detect system sessions (periods between startup and shutdown).
        
        Args:
            power_events: List of power event dictionaries
        
        Returns:
            List[Dict]: List of session dictionaries with start, end, and duration
        """
        sessions = []
        current_session_start = None
        current_session_start_event = None
        
        for event in power_events:
            event_type = event['event_type']
            
            # Session starts on startup or wake
            if event_type in ['startup', 'wake']:
                if current_session_start is None:
                    current_session_start = event['timestamp']
                    current_session_start_event = event
            
            # Session ends on shutdown, sleep, or hibernate
            elif event_type in ['shutdown', 'sleep', 'hibernate']:
                if current_session_start is not None:
                    # Calculate session duration
                    duration = event['timestamp'] - current_session_start
                    
                    session = {
                        'start_time': current_session_start,
                        'end_time': event['timestamp'],
                        'duration': duration,
                        'duration_seconds': duration.total_seconds(),
                        'start_event': current_session_start_event,
                        'end_event': event,
                    }
                    
                    sessions.append(session)
                    
                    # Reset for next session
                    current_session_start = None
                    current_session_start_event = None
        
        # Handle case where system is still running (no shutdown event)
        if current_session_start is not None:
            # Create open-ended session
            session = {
                'start_time': current_session_start,
                'end_time': None,
                'duration': None,
                'duration_seconds': None,
                'start_event': current_session_start_event,
                'end_event': None,
            }
            sessions.append(session)
        
        logger.info(f"Detected {len(sessions)} system sessions")
        return sessions
    
    def calculate_uptime_statistics(self, sessions: List[Dict]) -> Dict:
        """
        Calculate system uptime statistics from sessions.
        
        Args:
            sessions: List of session dictionaries
        
        Returns:
            Dict: Statistics including total uptime, number of startups, average session duration
        """
        if not sessions:
            return {
                'total_uptime_seconds': 0,
                'total_uptime_hours': 0,
                'number_of_sessions': 0,
                'number_of_startups': 0,
                'average_session_duration_seconds': 0,
                'average_session_duration_hours': 0,
            }
        
        # Calculate total uptime (excluding open-ended sessions)
        total_uptime_seconds = sum(
            s['duration_seconds'] for s in sessions 
            if s['duration_seconds'] is not None
        )
        
        # Count sessions and startups
        number_of_sessions = len(sessions)
        number_of_startups = sum(
            1 for s in sessions 
            if s['start_event'] and s['start_event']['event_type'] in ['startup', 'wake']
        )
        
        # Calculate average session duration (excluding open-ended sessions)
        completed_sessions = [s for s in sessions if s['duration_seconds'] is not None]
        if completed_sessions:
            average_session_duration_seconds = total_uptime_seconds / len(completed_sessions)
        else:
            average_session_duration_seconds = 0
        
        statistics = {
            'total_uptime_seconds': total_uptime_seconds,
            'total_uptime_hours': total_uptime_seconds / 3600,
            'number_of_sessions': number_of_sessions,
            'number_of_startups': number_of_startups,
            'average_session_duration_seconds': average_session_duration_seconds,
            'average_session_duration_hours': average_session_duration_seconds / 3600,
        }
        
        logger.info(f"Uptime statistics: {statistics}")
        return statistics
    
    def get_event_type_color(self, event_type: str) -> str:
        """
        Get the color for a power event type.
        
        Args:
            event_type: Power event type string
        
        Returns:
            str: Hex color code
        """
        try:
            event_type_enum = PowerEventType(event_type)
            return self.EVENT_TYPE_COLORS.get(event_type_enum, "#808080")
        except ValueError:
            return "#808080"  # Gray for unknown types
    
    def close_connection(self):
        """Close the database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.debug("Closed event log database connection")
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
            finally:
                self._connection = None
    
    def __del__(self):
        """Destructor to ensure connection is closed."""
        self.close_connection()
