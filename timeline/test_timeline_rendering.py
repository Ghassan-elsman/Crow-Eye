"""
Test timeline rendering with sample data.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout
from PyQt5.QtCore import QTimer

from timeline.timeline_canvas import TimelineCanvas

def test_timeline_rendering():
    """Test that timeline renders events correctly"""
    print("\n" + "="*80)
    print("Testing Timeline Rendering")
    print("="*80)
    
    app = QApplication(sys.argv)
    
    # Create dialog
    dialog = QDialog()
    dialog.setWindowTitle("Timeline Rendering Test")
    dialog.resize(1200, 600)
    
    layout = QVBoxLayout(dialog)
    
    # Create timeline canvas
    timeline = TimelineCanvas()
    layout.addWidget(timeline)
    
    # Set time range
    start_time = datetime(2025, 11, 1, 0, 0, 0)
    end_time = datetime(2025, 11, 7, 23, 59, 59)
    
    print(f"\nSetting time range: {start_time} to {end_time}")
    timeline.set_time_range(start_time, end_time)
    
    # Create sample events spread across the week
    events = []
    for day in range(7):
        for hour in [8, 12, 16, 20]:
            event_time = start_time + timedelta(days=day, hours=hour)
            events.append({
                'id': f'event_{day}_{hour}',
                'timestamp': event_time,
                'artifact_type': ['Prefetch', 'Registry', 'SRUM', 'LNK'][day % 4],
                'display_name': f'Test Event Day {day+1} Hour {hour}',
                'full_path': f'C:\\Test\\event_{day}_{hour}.exe',
                'details': {}
            })
    
    print(f"Created {len(events)} test events")
    print(f"First event: {events[0]['timestamp']}")
    print(f"Last event: {events[-1]['timestamp']}")
    
    # Render events
    print("\nRendering events...")
    timeline.render_events(events, show_loading=False)
    
    # Check scene
    print(f"\nScene rect: {timeline.scene.sceneRect()}")
    print(f"Scene width: {timeline.scene.sceneRect().width()}")
    print(f"Number of items in scene: {len(timeline.scene.items())}")
    print(f"Number of event markers: {len(timeline.event_markers)}")
    
    # Show dialog
    dialog.show()
    
    # Close after 3 seconds
    QTimer.singleShot(3000, dialog.close)
    QTimer.singleShot(3100, app.quit)
    
    print("\n✓ Timeline displayed (will close in 3 seconds)")
    print("  Check if events are spread horizontally across the timeline")
    print("="*80)
    
    app.exec_()
    
    return True

if __name__ == '__main__':
    test_timeline_rendering()
