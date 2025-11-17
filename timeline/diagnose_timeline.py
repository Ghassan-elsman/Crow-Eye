"""
Diagnose timeline rendering issues.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

print("\n" + "="*80)
print("Timeline Rendering Diagnostic")
print("="*80)

# Test 1: Check time range calculation
print("\n1. Testing time range calculation:")
start_time = datetime(2025, 1, 1, 0, 0, 0)
end_time = datetime(2025, 1, 7, 23, 59, 59)  # 7 days

time_delta = end_time - start_time
hours = time_delta.total_seconds() / 3600
min_width_per_hour = 150

min_calculated_width = hours * min_width_per_hour
print(f"  Time range: {start_time} to {end_time}")
print(f"  Duration: {hours:.2f} hours ({time_delta.days} days)")
print(f"  Minimum calculated width: {min_calculated_width:.2f} pixels")

# Test 2: Check position calculation
print("\n2. Testing position calculation:")
scene_width = max(1200, min_calculated_width)
print(f"  Scene width: {scene_width:.2f} pixels")

test_times = [
    start_time,
    start_time + timedelta(days=1),
    start_time + timedelta(days=3),
    start_time + timedelta(days=6),
    end_time
]

for test_time in test_times:
    total_duration = (end_time - start_time).total_seconds()
    event_offset = (test_time - start_time).total_seconds()
    relative_position = event_offset / total_duration
    position = relative_position * scene_width
    
    print(f"  {test_time}: position = {position:.2f} px (relative: {relative_position:.2%})")

# Test 3: Check if events would be visible
print("\n3. Checking event visibility:")
print(f"  If all events are at position 0-20, they would stack vertically on the left")
print(f"  Expected: Events should spread from 0 to {scene_width:.2f} pixels")

print("\n" + "="*80)
print("Diagnostic Complete")
print("="*80)
print("\nPossible issues:")
print("  1. If scene width is too small, events will cluster")
print("  2. If start_time == end_time, all events will be at position 0")
print("  3. If timestamps are outside the time range, they won't be visible")
print("="*80)
