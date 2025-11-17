"""
Event Aggregator - Aggregates events into time buckets for zoomed-out views.

This module provides the EventAggregator class which groups events into time buckets
and calculates event counts per artifact type. This is used for performance optimization
when displaying large numbers of events in zoomed-out timeline views.

Author: Crow Eye Timeline Feature
Version: 1.0
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict

# Configure logger
logger = logging.getLogger(__name__)


class EventAggregator:
    """
    Aggregates timeline events into time buckets for efficient rendering.
    
    This class groups events by time periods (buckets) and calculates counts
    by artifact type. This allows the timeline to display aggregated views
    when zoomed out, improving performance with large datasets.
    """
    
    # Time bucket sizes in seconds
    BUCKET_SIZES = {
        'minute': 60,
        '5min': 300,
        '15min': 900,
        'hour': 3600,
        '6hour': 21600,
        '12hour': 43200,
        'day': 86400,
        'week': 604800,
        'month': 2592000,  # 30 days
        'quarter': 7776000,  # 90 days
        'year': 31536000
    }
    
    def __init__(self):
        """Initialize the event aggregator."""
        pass
    
    def aggregate_events(
        self,
        events: List[Dict],
        bucket_size: str = 'hour',
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Aggregate events into time buckets with counts by artifact type.
        
        This method groups events into time periods (buckets) and calculates
        the count of events per artifact type in each bucket. This is used
        for displaying aggregated views when the timeline is zoomed out.
        
        Args:
            events: List of event dictionaries to aggregate
            bucket_size: Size of time buckets ('minute', 'hour', 'day', 'week', etc.)
            start_time: Optional start time for bucketing (uses earliest event if None)
            end_time: Optional end time for bucketing (uses latest event if None)
        
        Returns:
            List[Dict]: List of aggregated bucket dictionaries with structure:
                {
                    'time_bucket': datetime,  # Start of time bucket
                    'bucket_size': str,       # Bucket size name
                    'counts_by_type': dict,   # {artifact_type: count}
                    'total_count': int,       # Total events in bucket
                    'events': list            # List of event IDs in bucket (for expansion)
                }
        """
        if not events:
            logger.warning("No events to aggregate")
            return []
        
        # Validate bucket size
        if bucket_size not in self.BUCKET_SIZES:
            logger.warning(f"Invalid bucket size '{bucket_size}', defaulting to 'hour'")
            bucket_size = 'hour'
        
        bucket_seconds = self.BUCKET_SIZES[bucket_size]
        
        # Determine time range
        if start_time is None or end_time is None:
            timestamps = [e['timestamp'] for e in events if e.get('timestamp')]
            if not timestamps:
                logger.warning("No valid timestamps in events")
                return []
            
            if start_time is None:
                start_time = min(timestamps)
            if end_time is None:
                end_time = max(timestamps)
        
        # Round start time down to bucket boundary
        start_bucket = self._round_to_bucket(start_time, bucket_seconds, round_down=True)
        
        # Create buckets dictionary
        buckets = defaultdict(lambda: {
            'counts_by_type': defaultdict(int),
            'total_count': 0,
            'event_ids': []
        })
        
        # Assign events to buckets
        for event in events:
            timestamp = event.get('timestamp')
            if not timestamp:
                continue
            
            # Skip events outside time range
            if timestamp < start_time or timestamp > end_time:
                continue
            
            # Calculate which bucket this event belongs to
            bucket_time = self._round_to_bucket(timestamp, bucket_seconds, round_down=True)
            
            # Get artifact type
            artifact_type = event.get('artifact_type', 'Unknown')
            
            # Increment counts
            buckets[bucket_time]['counts_by_type'][artifact_type] += 1
            buckets[bucket_time]['total_count'] += 1
            buckets[bucket_time]['event_ids'].append(event.get('id'))
        
        # Convert to list of aggregated bucket dictionaries
        aggregated = []
        for bucket_time in sorted(buckets.keys()):
            bucket_data = buckets[bucket_time]
            
            aggregated.append({
                'time_bucket': bucket_time,
                'bucket_size': bucket_size,
                'counts_by_type': dict(bucket_data['counts_by_type']),
                'total_count': bucket_data['total_count'],
                'event_ids': bucket_data['event_ids']
            })
        
        logger.info(f"Aggregated {len(events)} events into {len(aggregated)} buckets (size: {bucket_size})")
        return aggregated
    
    def _round_to_bucket(self, timestamp: datetime, bucket_seconds: int, round_down: bool = True) -> datetime:
        """
        Round a timestamp to the nearest bucket boundary.
        
        Args:
            timestamp: Timestamp to round
            bucket_seconds: Size of bucket in seconds
            round_down: If True, round down; if False, round up
        
        Returns:
            datetime: Rounded timestamp
        """
        # Convert to Unix timestamp
        unix_timestamp = timestamp.timestamp()
        
        # Round to bucket boundary
        if round_down:
            bucket_timestamp = (unix_timestamp // bucket_seconds) * bucket_seconds
        else:
            bucket_timestamp = ((unix_timestamp + bucket_seconds - 1) // bucket_seconds) * bucket_seconds
        
        # Convert back to datetime
        return datetime.fromtimestamp(bucket_timestamp, tz=timestamp.tzinfo)
    
    def calculate_optimal_bucket_size(
        self,
        event_count: int,
        time_range_seconds: float,
        target_buckets: int = 100
    ) -> str:
        """
        Calculate optimal bucket size based on event count and time range.
        
        This method determines the best bucket size to use for aggregation
        based on the number of events and the time range being displayed.
        The goal is to create approximately target_buckets buckets.
        
        Args:
            event_count: Number of events to aggregate
            time_range_seconds: Time range in seconds
            target_buckets: Target number of buckets (default: 100)
        
        Returns:
            str: Optimal bucket size name
        """
        if event_count == 0 or time_range_seconds == 0:
            return 'hour'
        
        # Calculate ideal bucket size in seconds
        ideal_bucket_seconds = time_range_seconds / target_buckets
        
        # Find closest bucket size
        closest_size = 'hour'
        min_diff = float('inf')
        
        for size_name, size_seconds in self.BUCKET_SIZES.items():
            diff = abs(size_seconds - ideal_bucket_seconds)
            if diff < min_diff:
                min_diff = diff
                closest_size = size_name
        
        logger.debug(f"Calculated optimal bucket size: {closest_size} "
                    f"(event_count={event_count}, time_range={time_range_seconds}s)")
        
        return closest_size
    
    def get_bucket_size_seconds(self, bucket_size: str) -> int:
        """
        Get the size of a bucket in seconds.
        
        Args:
            bucket_size: Bucket size name
        
        Returns:
            int: Bucket size in seconds
        """
        return self.BUCKET_SIZES.get(bucket_size, 3600)
    
    def get_available_bucket_sizes(self) -> List[str]:
        """
        Get list of available bucket size names.
        
        Returns:
            List[str]: List of bucket size names
        """
        return list(self.BUCKET_SIZES.keys())
    
    def should_aggregate(self, visible_event_count: int, threshold: int = 1000) -> bool:
        """
        Determine if events should be aggregated based on count.
        
        Args:
            visible_event_count: Number of events visible in current view
            threshold: Threshold above which to aggregate (default: 1000)
        
        Returns:
            bool: True if aggregation should be used, False otherwise
        """
        return visible_event_count > threshold
    
    def expand_bucket(self, bucket: Dict, all_events: List[Dict]) -> List[Dict]:
        """
        Expand an aggregated bucket to show individual events.
        
        This method takes an aggregated bucket and returns the individual
        events that were grouped into that bucket.
        
        Args:
            bucket: Aggregated bucket dictionary
            all_events: List of all events (to look up by ID)
        
        Returns:
            List[Dict]: List of individual event dictionaries in the bucket
        """
        event_ids = bucket.get('event_ids', [])
        
        # Create lookup dictionary for fast access
        event_lookup = {e.get('id'): e for e in all_events}
        
        # Get events by ID
        expanded_events = []
        for event_id in event_ids:
            event = event_lookup.get(event_id)
            if event:
                expanded_events.append(event)
        
        logger.debug(f"Expanded bucket with {len(expanded_events)} events")
        return expanded_events
    
    def get_bucket_time_range(self, bucket: Dict) -> tuple:
        """
        Get the time range (start, end) for a bucket.
        
        Args:
            bucket: Aggregated bucket dictionary
        
        Returns:
            tuple: (start_time, end_time) for the bucket
        """
        bucket_time = bucket.get('time_bucket')
        bucket_size = bucket.get('bucket_size', 'hour')
        bucket_seconds = self.BUCKET_SIZES.get(bucket_size, 3600)
        
        start_time = bucket_time
        end_time = bucket_time + timedelta(seconds=bucket_seconds)
        
        return (start_time, end_time)
    
    def format_bucket_label(self, bucket: Dict) -> str:
        """
        Format a human-readable label for a bucket.
        
        Args:
            bucket: Aggregated bucket dictionary
        
        Returns:
            str: Formatted label (e.g., "2025-11-14 10:00", "Nov 14", "Week of Nov 10")
        """
        bucket_time = bucket.get('time_bucket')
        bucket_size = bucket.get('bucket_size', 'hour')
        
        if bucket_size in ['minute', '5min', '15min']:
            return bucket_time.strftime('%H:%M')
        elif bucket_size in ['hour', '6hour', '12hour']:
            return bucket_time.strftime('%Y-%m-%d %H:%M')
        elif bucket_size == 'day':
            return bucket_time.strftime('%Y-%m-%d')
        elif bucket_size == 'week':
            return f"Week of {bucket_time.strftime('%b %d')}"
        elif bucket_size == 'month':
            return bucket_time.strftime('%B %Y')
        elif bucket_size in ['quarter', 'year']:
            return bucket_time.strftime('%Y')
        else:
            return bucket_time.strftime('%Y-%m-%d %H:%M')
