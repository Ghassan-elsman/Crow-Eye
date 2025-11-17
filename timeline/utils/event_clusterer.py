"""
Event Clusterer - Groups events within configurable time windows.

This module provides the EventClusterer class which groups events that occur
within a specified time window to reduce visual clutter on the timeline.
"""

from datetime import timedelta
from collections import defaultdict


class EventClusterer:
    """
    Groups events within configurable time windows for cluster marker creation.
    
    This class implements time-window-based clustering to group related events
    that occur close together in time, reducing visual clutter on the timeline.
    """
    
    def __init__(self, time_window_minutes=5):
        """
        Initialize the event clusterer.
        
        Args:
            time_window_minutes (int): Time window in minutes for grouping events (default: 5)
        """
        self.time_window_minutes = time_window_minutes
        self.time_window = timedelta(minutes=time_window_minutes)
    
    def set_time_window(self, minutes):
        """
        Set the time window for clustering.
        
        Args:
            minutes (int): Time window in minutes
        """
        self.time_window_minutes = minutes
        self.time_window = timedelta(minutes=minutes)
    
    def get_time_window(self):
        """
        Get the current time window in minutes.
        
        Returns:
            int: Time window in minutes
        """
        return self.time_window_minutes
    
    def cluster_events(self, events, min_cluster_size=2):
        """
        Group events within the time window into clusters.
        
        This method groups events that occur within the configured time window.
        Events are sorted by timestamp and grouped sequentially if they fall
        within the time window of the previous event.
        
        Args:
            events (list): List of event dictionaries with 'timestamp' field
            min_cluster_size (int): Minimum number of events to form a cluster (default: 2)
        
        Returns:
            list: List of clusters, where each cluster is a dict with:
                - 'events': List of event dictionaries in the cluster
                - 'start_time': Earliest timestamp in cluster
                - 'end_time': Latest timestamp in cluster
                - 'representative_time': Representative timestamp for positioning (median)
                - 'is_cluster': True if cluster has >= min_cluster_size events
        """
        if not events:
            return []
        
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.get('timestamp'))
        
        clusters = []
        current_cluster = []
        cluster_start_time = None
        
        for event in sorted_events:
            timestamp = event.get('timestamp')
            
            if not timestamp:
                # Skip events without timestamps
                continue
            
            if not current_cluster:
                # Start new cluster
                current_cluster = [event]
                cluster_start_time = timestamp
            else:
                # Check if event is within time window of cluster start
                time_diff = timestamp - cluster_start_time
                
                if time_diff <= self.time_window:
                    # Add to current cluster
                    current_cluster.append(event)
                else:
                    # Finalize current cluster and start new one
                    clusters.append(self._create_cluster_dict(current_cluster, min_cluster_size))
                    current_cluster = [event]
                    cluster_start_time = timestamp
        
        # Add final cluster
        if current_cluster:
            clusters.append(self._create_cluster_dict(current_cluster, min_cluster_size))
        
        return clusters
    
    def _create_cluster_dict(self, events, min_cluster_size):
        """
        Create a cluster dictionary from a list of events.
        
        Args:
            events (list): List of event dictionaries
            min_cluster_size (int): Minimum size to be considered a cluster
        
        Returns:
            dict: Cluster dictionary with metadata
        """
        if not events:
            return None
        
        timestamps = [e.get('timestamp') for e in events if e.get('timestamp')]
        
        if not timestamps:
            return None
        
        start_time = min(timestamps)
        end_time = max(timestamps)
        
        # Use median timestamp as representative position
        sorted_timestamps = sorted(timestamps)
        median_idx = len(sorted_timestamps) // 2
        representative_time = sorted_timestamps[median_idx]
        
        return {
            'events': events,
            'start_time': start_time,
            'end_time': end_time,
            'representative_time': representative_time,
            'is_cluster': len(events) >= min_cluster_size,
            'count': len(events)
        }
    
    def cluster_by_application(self, events, min_cluster_size=2):
        """
        Group events by application within the time window.
        
        This method first groups events by application/artifact type, then
        applies time-window clustering within each group.
        
        Args:
            events (list): List of event dictionaries
            min_cluster_size (int): Minimum number of events to form a cluster
        
        Returns:
            list: List of clusters grouped by application
        """
        if not events:
            return []
        
        # Group events by application/artifact type
        events_by_app = defaultdict(list)
        
        for event in events:
            # Try to get application name, fall back to artifact type
            app_name = event.get('display_name', event.get('artifact_type', 'Unknown'))
            events_by_app[app_name].append(event)
        
        # Cluster each application's events separately
        all_clusters = []
        
        for app_name, app_events in events_by_app.items():
            app_clusters = self.cluster_events(app_events, min_cluster_size)
            
            # Add application name to cluster metadata
            for cluster in app_clusters:
                if cluster:
                    cluster['application'] = app_name
                    all_clusters.append(cluster)
        
        # Sort all clusters by representative time
        all_clusters.sort(key=lambda c: c.get('representative_time'))
        
        return all_clusters
    
    def cluster_by_path(self, events, min_cluster_size=2):
        """
        Group events by file/registry path within the time window.
        
        This method first groups events by their path, then applies
        time-window clustering within each group.
        
        Args:
            events (list): List of event dictionaries
            min_cluster_size (int): Minimum number of events to form a cluster
        
        Returns:
            list: List of clusters grouped by path
        """
        if not events:
            return []
        
        # Group events by path
        events_by_path = defaultdict(list)
        
        for event in events:
            path = event.get('full_path', 'Unknown')
            events_by_path[path].append(event)
        
        # Cluster each path's events separately
        all_clusters = []
        
        for path, path_events in events_by_path.items():
            path_clusters = self.cluster_events(path_events, min_cluster_size)
            
            # Add path to cluster metadata
            for cluster in path_clusters:
                if cluster:
                    cluster['path'] = path
                    all_clusters.append(cluster)
        
        # Sort all clusters by representative time
        all_clusters.sort(key=lambda c: c.get('representative_time'))
        
        return all_clusters
    
    def cluster_by_artifact_type(self, events, min_cluster_size=2):
        """
        Group events by artifact type within the time window.
        
        This method first groups events by artifact type, then applies
        time-window clustering within each group.
        
        Args:
            events (list): List of event dictionaries
            min_cluster_size (int): Minimum number of events to form a cluster
        
        Returns:
            list: List of clusters grouped by artifact type
        """
        if not events:
            return []
        
        # Group events by artifact type
        events_by_type = defaultdict(list)
        
        for event in events:
            artifact_type = event.get('artifact_type', 'Unknown')
            events_by_type[artifact_type].append(event)
        
        # Cluster each type's events separately
        all_clusters = []
        
        for artifact_type, type_events in events_by_type.items():
            type_clusters = self.cluster_events(type_events, min_cluster_size)
            
            # Add artifact type to cluster metadata
            for cluster in type_clusters:
                if cluster:
                    cluster['artifact_type'] = artifact_type
                    all_clusters.append(cluster)
        
        # Sort all clusters by representative time
        all_clusters.sort(key=lambda c: c.get('representative_time'))
        
        return all_clusters
    
    def get_cluster_summary(self, cluster):
        """
        Get a summary string for a cluster.
        
        Args:
            cluster (dict): Cluster dictionary
        
        Returns:
            str: Summary string describing the cluster
        """
        if not cluster:
            return "Empty cluster"
        
        count = cluster.get('count', 0)
        start_time = cluster.get('start_time')
        end_time = cluster.get('end_time')
        
        if start_time and end_time:
            duration = end_time - start_time
            duration_str = self._format_duration(duration)
            
            return f"{count} events over {duration_str}"
        else:
            return f"{count} events"
    
    def _format_duration(self, duration):
        """
        Format a timedelta as a human-readable string.
        
        Args:
            duration (timedelta): Duration to format
        
        Returns:
            str: Formatted duration string
        """
        total_seconds = int(duration.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            if seconds > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{minutes}m"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{hours}h"
