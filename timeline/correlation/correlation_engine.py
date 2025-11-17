"""
Correlation Engine - Identifies and manages relationships between timeline events.

This module provides the CorrelationEngine class which detects temporal correlations,
groups related events, and calculates correlation scores between artifacts.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Tuple, Set


class CorrelationEngine:
    """
    Identifies and manages relationships between timeline events.
    
    This class provides methods to:
    - Find events occurring at the same timestamp (exact correlations)
    - Find events within a configurable time window (temporal correlations)
    - Group events by application, path, or user
    - Calculate correlation scores between events
    """
    
    def __init__(self, time_window_seconds=60):
        """
        Initialize the correlation engine.
        
        Args:
            time_window_seconds (int): Time window in seconds for temporal correlations.
                                      Events within this window are considered correlated.
                                      Default: 60 seconds (1 minute)
        """
        self.time_window_seconds = time_window_seconds
        self.time_window = timedelta(seconds=time_window_seconds)
        
    def set_time_window(self, seconds):
        """
        Update the correlation time window.
        
        Args:
            seconds (int): New time window in seconds
        """
        self.time_window_seconds = seconds
        self.time_window = timedelta(seconds=seconds)
    
    def find_exact_correlations(self, events):
        """
        Find events with identical timestamps.
        
        This method groups events that occurred at exactly the same time,
        which often indicates related system activity.
        
        Args:
            events (list): List of event dictionaries, each containing:
                - id: Unique event identifier
                - timestamp: datetime object
                - artifact_type: Type of artifact
                - display_name: Name to display
                - full_path: Full path
                - details: Additional metadata
        
        Returns:
            dict: Dictionary mapping timestamps to lists of correlated events
                  {timestamp: [event1, event2, ...]}
        """
        correlations = defaultdict(list)
        
        for event in events:
            timestamp = event.get('timestamp')
            if timestamp and isinstance(timestamp, datetime):
                # Group events by exact timestamp
                correlations[timestamp].append(event)
        
        # Filter out timestamps with only one event (no correlation)
        exact_correlations = {
            ts: event_list 
            for ts, event_list in correlations.items() 
            if len(event_list) > 1
        }
        
        return exact_correlations
    
    def find_temporal_correlations(self, events):
        """
        Find events within the configured time window.
        
        This method identifies events that occurred close together in time,
        which may indicate related activity even if not at the exact same moment.
        
        Args:
            events (list): List of event dictionaries
        
        Returns:
            list: List of correlation groups, where each group is a list of related events
                  [[event1, event2, event3], [event4, event5], ...]
        """
        if not events:
            return []
        
        # Sort events by timestamp
        sorted_events = sorted(
            [e for e in events if e.get('timestamp') and isinstance(e.get('timestamp'), datetime)],
            key=lambda e: e['timestamp']
        )
        
        if not sorted_events:
            return []
        
        correlation_groups = []
        current_group = [sorted_events[0]]
        
        for i in range(1, len(sorted_events)):
            current_event = sorted_events[i]
            previous_event = sorted_events[i - 1]
            
            time_diff = current_event['timestamp'] - previous_event['timestamp']
            
            if time_diff <= self.time_window:
                # Event is within time window, add to current group
                current_group.append(current_event)
            else:
                # Time window exceeded, start new group
                if len(current_group) > 1:
                    correlation_groups.append(current_group)
                current_group = [current_event]
        
        # Add the last group if it has multiple events
        if len(current_group) > 1:
            correlation_groups.append(current_group)
        
        return correlation_groups
    
    def group_by_application(self, events):
        """
        Group events by application name.
        
        Extracts application names from file paths and groups related events.
        
        Args:
            events (list): List of event dictionaries
        
        Returns:
            dict: Dictionary mapping application names to lists of events
                  {app_name: [event1, event2, ...]}
        """
        app_groups = defaultdict(list)
        
        for event in events:
            app_name = self._extract_application_name(event)
            if app_name:
                app_groups[app_name].append(event)
        
        # Filter out groups with only one event
        return {
            app: event_list 
            for app, event_list in app_groups.items() 
            if len(event_list) > 1
        }
    
    def group_by_path(self, events):
        """
        Group events by file or registry path.
        
        Groups events that share the same directory or registry key path.
        
        Args:
            events (list): List of event dictionaries
        
        Returns:
            dict: Dictionary mapping paths to lists of events
                  {path: [event1, event2, ...]}
        """
        path_groups = defaultdict(list)
        
        for event in events:
            path = self._extract_base_path(event)
            if path:
                path_groups[path].append(event)
        
        # Filter out groups with only one event
        return {
            path: event_list 
            for path, event_list in path_groups.items() 
            if len(event_list) > 1
        }
    
    def group_by_user(self, events):
        """
        Group events by user profile.
        
        Extracts user names from file paths and groups related events.
        
        Args:
            events (list): List of event dictionaries
        
        Returns:
            dict: Dictionary mapping user names to lists of events
                  {user_name: [event1, event2, ...]}
        """
        user_groups = defaultdict(list)
        
        for event in events:
            user = self._extract_user_from_path(event)
            if user:
                user_groups[user].append(event)
        
        # Filter out groups with only one event
        return {
            user: event_list 
            for user, event_list in user_groups.items() 
            if len(event_list) > 1
        }
    
    def calculate_correlation_score(self, event1, event2):
        """
        Calculate correlation strength between two events.
        
        The score is based on multiple factors:
        - Temporal proximity (closer in time = higher score)
        - Same application (bonus points)
        - Same path (bonus points)
        - Same artifact type (bonus points)
        
        Args:
            event1 (dict): First event
            event2 (dict): Second event
        
        Returns:
            float: Correlation score between 0.0 and 1.0
        """
        score = 0.0
        
        # Check if both events have valid timestamps
        ts1 = event1.get('timestamp')
        ts2 = event2.get('timestamp')
        
        if not (ts1 and ts2 and isinstance(ts1, datetime) and isinstance(ts2, datetime)):
            return 0.0
        
        # Temporal proximity score (0.0 to 0.5)
        time_diff = abs((ts1 - ts2).total_seconds())
        if time_diff == 0:
            score += 0.5  # Exact same time
        elif time_diff <= self.time_window_seconds:
            # Linear decay within time window
            temporal_score = 0.5 * (1 - time_diff / self.time_window_seconds)
            score += temporal_score
        
        # Same application bonus (0.2)
        app1 = self._extract_application_name(event1)
        app2 = self._extract_application_name(event2)
        if app1 and app2 and app1.lower() == app2.lower():
            score += 0.2
        
        # Same path bonus (0.2)
        path1 = self._extract_base_path(event1)
        path2 = self._extract_base_path(event2)
        if path1 and path2 and path1.lower() == path2.lower():
            score += 0.2
        
        # Same artifact type bonus (0.1)
        if event1.get('artifact_type') == event2.get('artifact_type'):
            score += 0.1
        
        # Normalize to 0.0-1.0 range
        return min(score, 1.0)
    
    def find_correlated_pairs(self, events, min_score=0.5):
        """
        Find all pairs of events with correlation score above threshold.
        
        Args:
            events (list): List of event dictionaries
            min_score (float): Minimum correlation score (0.0 to 1.0)
        
        Returns:
            list: List of tuples (event1, event2, score) for correlated pairs
        """
        correlated_pairs = []
        
        # Sort events by timestamp for efficiency
        sorted_events = sorted(
            [e for e in events if e.get('timestamp') and isinstance(e.get('timestamp'), datetime)],
            key=lambda e: e['timestamp']
        )
        
        # Compare each event with subsequent events within time window
        for i in range(len(sorted_events)):
            event1 = sorted_events[i]
            
            # Only check events within time window
            for j in range(i + 1, len(sorted_events)):
                event2 = sorted_events[j]
                
                # Stop if we've exceeded the time window
                time_diff = abs((event2['timestamp'] - event1['timestamp']).total_seconds())
                if time_diff > self.time_window_seconds:
                    break
                
                # Calculate correlation score
                score = self.calculate_correlation_score(event1, event2)
                
                if score >= min_score:
                    correlated_pairs.append((event1, event2, score))
        
        return correlated_pairs
    
    def _extract_application_name(self, event):
        """
        Extract application name from event data.
        
        Args:
            event (dict): Event dictionary
        
        Returns:
            str: Application name or None
        """
        # Try display_name first
        display_name = event.get('display_name', '')
        if display_name:
            # Remove extension
            if '.' in display_name:
                return display_name.rsplit('.', 1)[0]
            return display_name
        
        # Try extracting from full_path
        full_path = event.get('full_path', '')
        if full_path:
            # Get filename from path
            if '\\' in full_path:
                filename = full_path.split('\\')[-1]
            elif '/' in full_path:
                filename = full_path.split('/')[-1]
            else:
                filename = full_path
            
            # Remove extension
            if '.' in filename:
                return filename.rsplit('.', 1)[0]
            return filename
        
        return None
    
    def _extract_base_path(self, event):
        """
        Extract base directory path from event data.
        
        Args:
            event (dict): Event dictionary
        
        Returns:
            str: Base path or None
        """
        full_path = event.get('full_path', '')
        if not full_path:
            return None
        
        # Get directory path (remove filename)
        if '\\' in full_path:
            parts = full_path.split('\\')
            if len(parts) > 1:
                return '\\'.join(parts[:-1])
        elif '/' in full_path:
            parts = full_path.split('/')
            if len(parts) > 1:
                return '/'.join(parts[:-1])
        
        return None
    
    def _extract_user_from_path(self, event):
        """
        Extract user name from file path.
        
        Looks for patterns like C:\\Users\\username\\ in paths.
        
        Args:
            event (dict): Event dictionary
        
        Returns:
            str: User name or None
        """
        full_path = event.get('full_path', '')
        if not full_path:
            return None
        
        # Look for Windows user profile pattern
        path_lower = full_path.lower()
        
        # Pattern: C:\Users\username\...
        if '\\users\\' in path_lower:
            parts = full_path.split('\\')
            try:
                users_index = [p.lower() for p in parts].index('users')
                if users_index + 1 < len(parts):
                    return parts[users_index + 1]
            except (ValueError, IndexError):
                pass
        
        # Pattern: C:/Users/username/...
        if '/users/' in path_lower:
            parts = full_path.split('/')
            try:
                users_index = [p.lower() for p in parts].index('users')
                if users_index + 1 < len(parts):
                    return parts[users_index + 1]
            except (ValueError, IndexError):
                pass
        
        return None
