"""
Debug timeline with real case data to see why events stack on left.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeline.data.timeline_data_manager import TimelineDataManager

class MockMainWindow:
    def __init__(self, case_root):
        self.case_paths = {
            'case_root': case_root,
            'artifacts_dir': os.path.join(case_root, 'Target_Artifacts'),
            'timeline_dir': os.path.join(case_root, 'timeline'),
            'registry_db': os.path.join(case_root, 'Target_Artifacts', 'registry_data.db'),
            'prefetch_db': os.path.join(case_root, 'Target_Artifacts', 'prefetch_data.db'),
            'lnk_db': os.path.join(case_root, 'Target_Artifacts', 'lnk_data.db'),
            'bam_db': os.path.join(case_root, 'Target_Artifacts', 'bam_data.db'),
            'srum_db': os.path.join(case_root, 'Target_Artifacts', 'srum_data.db'),
            'usn_db': os.path.join(case_root, 'Target_Artifacts', 'usn_data.db'),
            'mft_db': os.path.join(case_root, 'Target_Artifacts', 'mft_data.db'),
            'shellbags_db': os.path.join(case_root, 'Target_Artifacts', 'shellbags_data.db'),
            'logs_db': os.path.join(case_root, 'Target_Artifacts', 'logs_data.db')
        }

def debug_real_timeline():
    """Debug timeline with real case data"""
    print("\n" + "="*80)
    print("Debugging Real Timeline Data")
    print("="*80)
    
    case_root = r"E:\Cases\9 novmber"
    
    if not os.path.exists(case_root):
        print(f"\n❌ Case not found: {case_root}")
        return
    
    print(f"\n✓ Case found: {case_root}")
    
    # Create data manager
    mock_window = MockMainWindow(case_root)
    data_manager = TimelineDataManager(mock_window.case_paths)
    
    # Get time bounds
    print("\nGetting time bounds...")
    start_time, end_time = data_manager.get_all_time_bounds()
    
    print(f"  Start: {start_time}")
    print(f"  End:   {end_time}")
    print(f"  Span:  {(end_time - start_time).days} days")
    
    # Load a sample of events
    print("\nLoading sample events...")
    events = data_manager.query_time_range(
        start_time,
        end_time,
        artifact_types=['Prefetch', 'Registry']
    )
    
    print(f"  Loaded {len(events)} events")
    
    # Analyze timestamps
    print("\nAnalyzing timestamps:")
    
    if events:
        timestamps = [e.get('timestamp') for e in events if e.get('timestamp')]
        timestamps.sort()
        
        print(f"  First 5 timestamps:")
        for i, ts in enumerate(timestamps[:5]):
            print(f"    {i+1}. {ts}")
        
        print(f"  Last 5 timestamps:")
        for i, ts in enumerate(timestamps[-5:]):
            print(f"    {len(timestamps)-4+i}. {ts}")
        
        # Check if all timestamps are the same
        unique_timestamps = set(timestamps)
        print(f"\n  Unique timestamps: {len(unique_timestamps)}")
        
        if len(unique_timestamps) == 1:
            print(f"  ⚠ WARNING: All events have the same timestamp!")
            print(f"  This would cause all events to stack at the same position")
        elif len(unique_timestamps) < 10:
            print(f"  ⚠ WARNING: Very few unique timestamps ({len(unique_timestamps)})")
            print(f"  Events will cluster heavily")
        else:
            print(f"  ✓ Good distribution of timestamps")
        
        # Test position calculation
        print("\nTesting position calculation:")
        scene_width = 25000  # Typical scene width
        
        total_duration = (end_time - start_time).total_seconds()
        
        for i, event in enumerate(events[:5]):
            ts = event.get('timestamp')
            if ts:
                event_offset = (ts - start_time).total_seconds()
                relative_position = event_offset / total_duration if total_duration > 0 else 0
                position = relative_position * scene_width
                
                print(f"  Event {i+1}: {ts}")
                print(f"    Offset: {event_offset:.2f} seconds")
                print(f"    Relative: {relative_position:.4f}")
                print(f"    Position: {position:.2f} px")
    
    print("\n" + "="*80)
    print("Debug Complete")
    print("="*80)

if __name__ == '__main__':
    debug_real_timeline()
