"""
Event Renderer - Handles visual representation of timeline events.

This module provides the EventRenderer class which creates QGraphicsItem objects
for event markers, clusters, and connection lines on the timeline.
"""

from PyQt5.QtWidgets import (QGraphicsEllipseItem, QGraphicsRectItem, 
                             QGraphicsItem, QGraphicsPathItem, QGraphicsLineItem)
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QPen, QBrush, QPainterPath, QFont
from datetime import datetime


class EventRenderer:
    """
    Handles rendering of event markers and related visual elements.
    
    This class provides methods to create QGraphicsItem objects for:
    - Individual event markers
    - Cluster markers for grouped events
    - Connection lines between correlated events
    - Power event markers
    """
    
    # Artifact type color mapping (as specified in requirements)
    COLORS = {
        'Prefetch': '#3498db',    # Blue
        'LNK': '#2ecc71',         # Green
        'Registry': '#9b59b6',    # Purple
        'BAM': '#e67e22',         # Orange
        'ShellBag': '#1abc9c',    # Cyan
        'ShellBags': '#1abc9c',   # Cyan (plural form)
        'SRUM': '#e74c3c',        # Red
        'USN': '#f39c12',         # Yellow
        'MFT': '#e91e63',         # Pink
        'Logs': '#8B4513',        # Brown (Windows Event Logs)
        'Unknown': '#95a5a6'      # Gray (fallback)
    }
    
    # Power event colors
    POWER_EVENT_COLORS = {
        'startup': '#2ecc71',      # Green
        'shutdown': '#e74c3c',     # Red
        'sleep': '#3498db',        # Blue
        'wake': '#1abc9c',         # Light green
        'hibernate': '#9b59b6'     # Purple
    }
    
    # Marker dimensions
    MARKER_RADIUS = 10  # Radius for circular markers (increased for better visibility)
    MARKER_SPACING = 24  # Vertical spacing between stacked markers (increased for clarity)
    
    def __init__(self):
        """Initialize the event renderer."""
        pass
    
    def create_event_marker(self, event_data, position, y_offset=0, base_y=200, lod=0):
        """
        Create a QGraphicsItem for an event marker with improved visibility.
        
        Args:
            event_data (dict): Event data containing:
                - id: Unique event identifier
                - artifact_type: Type of artifact (Prefetch, LNK, etc.)
                - timestamp: Event timestamp
                - display_name: Name to display
                - full_path: Full path of artifact
                - details: Additional metadata
            position (float): X position on timeline (in scene coordinates)
            y_offset (int): Vertical offset for stacking (default: 0)
            base_y (float): Base Y position for markers (default: 200)
            lod (int): Level of detail (0=high, 1=medium, 2=low)
        
        Returns:
            QGraphicsEllipseItem: Event marker item with enhanced visibility
        """
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        
        # Get color for artifact type
        artifact_type = event_data.get('artifact_type', 'Unknown')
        color = self.COLORS.get(artifact_type, self.COLORS['Unknown'])
        
        # Adjust marker size based on LOD
        marker_radius = self.MARKER_RADIUS
        if lod == 1:  # Medium detail
            marker_radius = int(self.MARKER_RADIUS * 0.8)
        elif lod == 2:  # Low detail
            marker_radius = int(self.MARKER_RADIUS * 0.6)
        
        # Create circular marker
        marker = QGraphicsEllipseItem(
            position - marker_radius,
            base_y + y_offset * self.MARKER_SPACING - marker_radius,
            marker_radius * 2,
            marker_radius * 2
        )
        
        # Set marker appearance with better contrast
        marker.setBrush(QBrush(QColor(color)))
        # Thicker white border for better visibility
        marker.setPen(QPen(QColor("#FFFFFF"), 2))
        
        # Add effects only for high detail (performance optimization)
        if lod == 0:
            # Add subtle shadow/glow effect for depth
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(8)
            shadow.setColor(QColor(0, 0, 0, 100))  # Semi-transparent black
            shadow.setOffset(0, 2)
            marker.setGraphicsEffect(shadow)
        
        # Enable hover and selection
        marker.setAcceptHoverEvents(True)
        marker.setFlag(QGraphicsItem.ItemIsSelectable, True)
        
        # Store event data in marker for later retrieval
        marker.setData(0, event_data)  # Qt.UserRole = 0
        marker.setData(1, color)  # Store original color for hover effects
        
        # Set tooltip with event information
        tooltip = self._create_tooltip(event_data)
        marker.setToolTip(tooltip)
        
        return marker
    
    def _create_tooltip(self, event_data):
        """
        Create tooltip text for an event marker.
        
        Args:
            event_data (dict): Event data
        
        Returns:
            str: Formatted tooltip text
        """
        artifact_type = event_data.get('artifact_type', 'Unknown')
        display_name = event_data.get('display_name', 'N/A')
        timestamp = event_data.get('timestamp')
        full_path = event_data.get('full_path', 'N/A')
        
        # Format timestamp
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            timestamp_str = str(timestamp)
        
        tooltip = f"""<b>{artifact_type}</b><br>
<b>Name:</b> {display_name}<br>
<b>Time:</b> {timestamp_str}<br>
<b>Path:</b> {full_path}"""
        
        return tooltip
    
    def apply_highlight(self, marker_item, highlighted=True, lod=0):
        """
        Apply or remove highlight effect from a marker with enhanced visibility.
        
        Handles both individual markers (QGraphicsEllipseItem) and cluster markers
        (QGraphicsItemGroup).
        
        Args:
            marker_item (QGraphicsItem): Marker to highlight
            highlighted (bool): True to highlight, False to remove highlight
            lod (int): Level of detail (0=high, 1=medium, 2=low)
        """
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect, QGraphicsItemGroup
        
        # Check if this is a cluster marker (QGraphicsItemGroup)
        is_cluster = isinstance(marker_item, QGraphicsItemGroup)
        
        if is_cluster:
            # For cluster markers, apply effect to the main circle (first child)
            children = marker_item.childItems()
            if children:
                main_marker = children[0]  # First child is the main circle
                if highlighted:
                    main_marker.setPen(QPen(QColor("#00FFFF"), 3))
                else:
                    main_marker.setPen(QPen(QColor("#FFFFFF"), 2))
            
            # Apply glow to entire group
            if highlighted:
                marker_item.setZValue(100)
                glow = QGraphicsDropShadowEffect()
                glow.setBlurRadius(15)
                glow.setColor(QColor("#00FFFF"))
                glow.setOffset(0, 0)
                marker_item.setGraphicsEffect(glow)
            else:
                marker_item.setZValue(0)
                # Only apply shadow in high detail mode
                if lod == 0:
                    shadow = QGraphicsDropShadowEffect()
                    shadow.setBlurRadius(8)
                    shadow.setColor(QColor(0, 0, 0, 100))
                    shadow.setOffset(0, 2)
                    marker_item.setGraphicsEffect(shadow)
                else:
                    marker_item.setGraphicsEffect(None)
        else:
            # Individual marker
            if highlighted:
                # Enhanced highlight with bright cyan border and glow
                marker_item.setPen(QPen(QColor("#00FFFF"), 3))
                marker_item.setZValue(100)  # Bring to front
                
                # Add bright glow effect on hover
                glow = QGraphicsDropShadowEffect()
                glow.setBlurRadius(15)
                glow.setColor(QColor("#00FFFF"))  # Cyan glow
                glow.setOffset(0, 0)
                marker_item.setGraphicsEffect(glow)
                
                # Slightly increase opacity
                marker_item.setOpacity(1.0)
            else:
                # Restore normal appearance with subtle shadow
                marker_item.setPen(QPen(QColor("#FFFFFF"), 2))
                marker_item.setZValue(0)
                
                # Restore subtle shadow only in high detail
                if lod == 0:
                    shadow = QGraphicsDropShadowEffect()
                    shadow.setBlurRadius(8)
                    shadow.setColor(QColor(0, 0, 0, 100))
                    shadow.setOffset(0, 2)
                    marker_item.setGraphicsEffect(shadow)
                else:
                    marker_item.setGraphicsEffect(None)
                
                marker_item.setOpacity(1.0)
    
    def apply_selection(self, marker_item, selected=True, lod=0):
        """
        Apply or remove selection effect from a marker with distinct visual indicator.
        
        Handles both individual markers (QGraphicsEllipseItem) and cluster markers
        (QGraphicsItemGroup).
        
        Args:
            marker_item (QGraphicsItem): Marker to select
            selected (bool): True to select, False to deselect
            lod (int): Level of detail (0=high, 1=medium, 2=low)
        """
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect, QGraphicsItemGroup
        
        # Check if this is a cluster marker (QGraphicsItemGroup)
        is_cluster = isinstance(marker_item, QGraphicsItemGroup)
        
        if is_cluster:
            # For cluster markers, apply effect to the main circle (first child)
            children = marker_item.childItems()
            if children:
                main_marker = children[0]  # First child is the main circle
                if selected:
                    # Bright yellow border for selection
                    main_marker.setPen(QPen(QColor("#FFD700"), 4))
                else:
                    # Restore normal white border
                    main_marker.setPen(QPen(QColor("#FFFFFF"), 2))
            
            # Apply glow to entire group
            if selected:
                marker_item.setZValue(50)
                glow = QGraphicsDropShadowEffect()
                glow.setBlurRadius(20)
                glow.setColor(QColor("#FFD700"))  # Gold glow
                glow.setOffset(0, 0)
                marker_item.setGraphicsEffect(glow)
            else:
                marker_item.setZValue(0)
                # Only apply shadow in high detail mode
                if lod == 0:
                    shadow = QGraphicsDropShadowEffect()
                    shadow.setBlurRadius(8)
                    shadow.setColor(QColor(0, 0, 0, 100))
                    shadow.setOffset(0, 2)
                    marker_item.setGraphicsEffect(shadow)
                else:
                    marker_item.setGraphicsEffect(None)
        else:
            # Individual marker
            if selected:
                # Bright yellow/gold border for distinct selection indicator
                marker_item.setPen(QPen(QColor("#FFD700"), 4))
                marker_item.setZValue(50)  # Bring to front
                
                # Add bright gold glow effect for selection
                glow = QGraphicsDropShadowEffect()
                glow.setBlurRadius(20)
                glow.setColor(QColor("#FFD700"))  # Gold glow
                glow.setOffset(0, 0)
                marker_item.setGraphicsEffect(glow)
                
                # Slightly increase opacity
                marker_item.setOpacity(1.0)
            else:
                # Restore normal appearance with white border and subtle shadow
                marker_item.setPen(QPen(QColor("#FFFFFF"), 2))
                marker_item.setZValue(0)
                
                # Restore subtle shadow only in high detail
                if lod == 0:
                    shadow = QGraphicsDropShadowEffect()
                    shadow.setBlurRadius(8)
                    shadow.setColor(QColor(0, 0, 0, 100))
                    shadow.setOffset(0, 2)
                    marker_item.setGraphicsEffect(shadow)
                else:
                    marker_item.setGraphicsEffect(None)
                
                marker_item.setOpacity(1.0)
    
    def create_cluster_marker(self, events, position, y_offset=0, base_y=200, lod=0):
        """
        Create a cluster marker for grouped events at the same timestamp.
        
        This creates an aggregate marker with a count badge that shows how many
        events are grouped together. The marker can be expanded on hover or click
        to show individual events.
        
        Args:
            events (list): List of event data dictionaries
            position (float): X position on timeline
            y_offset (int): Vertical offset for stacking
            base_y (float): Base Y position for markers (default: 200)
            lod (int): Level of detail (0=high, 1=medium, 2=low)
        
        Returns:
            QGraphicsItemGroup: Cluster marker with count badge
        """
        from PyQt5.QtWidgets import QGraphicsItemGroup, QGraphicsSimpleTextItem
        
        count = len(events)
        
        # Determine dominant artifact type (most common in cluster)
        artifact_types = [e.get('artifact_type', 'Unknown') for e in events]
        dominant_type = max(set(artifact_types), key=artifact_types.count)
        color = self.COLORS.get(dominant_type, self.COLORS['Unknown'])
        
        # Create group to hold marker and badge
        group = QGraphicsItemGroup()
        
        # Adjust cluster size based on LOD
        cluster_radius = int(self.MARKER_RADIUS * 1.5)
        if lod == 1:  # Medium detail
            cluster_radius = int(self.MARKER_RADIUS * 1.2)
        elif lod == 2:  # Low detail
            cluster_radius = int(self.MARKER_RADIUS * 1.0)
        
        # Create larger circular marker for cluster
        marker = QGraphicsEllipseItem(
            position - cluster_radius,
            base_y + y_offset * self.MARKER_SPACING - cluster_radius,
            cluster_radius * 2,
            cluster_radius * 2
        )
        
        # Set appearance with gradient effect
        marker.setBrush(QBrush(QColor(color)))
        marker.setPen(QPen(QColor("#FFFFFF"), 2))
        
        # Enable hover and selection
        marker.setAcceptHoverEvents(True)
        marker.setFlag(QGraphicsItem.ItemIsSelectable, True)
        
        # Add marker to group
        group.addToGroup(marker)
        
        # Create count badge (small circle with number)
        badge_radius = 8 if lod == 0 else 6
        badge_x = position + cluster_radius - badge_radius
        badge_y = base_y + y_offset * self.MARKER_SPACING - cluster_radius
        
        badge_circle = QGraphicsEllipseItem(
            badge_x,
            badge_y,
            badge_radius * 2,
            badge_radius * 2
        )
        badge_circle.setBrush(QBrush(QColor("#EF4444")))  # Red badge
        badge_circle.setPen(QPen(QColor("#FFFFFF"), 1))
        group.addToGroup(badge_circle)
        
        # Add count text to badge
        count_text = QGraphicsSimpleTextItem(str(count))
        count_text.setBrush(QBrush(QColor("#FFFFFF")))
        font_size = 7 if lod == 0 else 6
        count_text.setFont(QFont("Segoe UI", font_size, QFont.Bold))
        
        # Center text in badge
        text_rect = count_text.boundingRect()
        text_x = badge_x + badge_radius - text_rect.width() / 2
        text_y = badge_y + badge_radius - text_rect.height() / 2
        count_text.setPos(text_x, text_y)
        group.addToGroup(count_text)
        
        # Store cluster data in the group
        group.setData(0, {
            'type': 'cluster',
            'events': events,
            'count': count,
            'dominant_type': dominant_type,
            'expanded': False
        })
        
        # Enable interaction
        group.setAcceptHoverEvents(True)
        group.setFlag(QGraphicsItem.ItemIsSelectable, True)
        
        # Create detailed tooltip
        tooltip = self._create_cluster_tooltip(events, dominant_type)
        group.setToolTip(tooltip)
        
        return group
    
    def _create_cluster_tooltip(self, events, dominant_type):
        """
        Create tooltip text for a cluster marker.
        
        Args:
            events (list): List of event data dictionaries
            dominant_type (str): Most common artifact type in cluster
        
        Returns:
            str: Formatted tooltip HTML
        """
        count = len(events)
        
        # Count events by type
        type_counts = {}
        for event in events:
            artifact_type = event.get('artifact_type', 'Unknown')
            type_counts[artifact_type] = type_counts.get(artifact_type, 0) + 1
        
        # Get time range from all events
        timestamps = [e.get('timestamp') for e in events if e.get('timestamp')]
        if timestamps:
            start_time = min(timestamps)
            end_time = max(timestamps)
            
            # Format timestamps
            if isinstance(start_time, datetime):
                start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                start_str = str(start_time)
            
            if isinstance(end_time, datetime):
                end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                end_str = str(end_time)
            
            # Calculate duration if both are datetime objects
            duration_str = ""
            if isinstance(start_time, datetime) and isinstance(end_time, datetime):
                duration = end_time - start_time
                duration_str = self._format_duration_tooltip(duration)
        else:
            start_str = "N/A"
            end_str = "N/A"
            duration_str = ""
        
        # Build tooltip
        tooltip = f"""<b>Cluster: {count} events</b><br>
<b>Time Range:</b> {start_str} to {end_str}"""
        
        if duration_str:
            tooltip += f"<br><b>Duration:</b> {duration_str}"
        
        tooltip += f"<br><b>Dominant Type:</b> {dominant_type}<br>"
        tooltip += "<br><b>Breakdown:</b><br>"
        
        for artifact_type, type_count in sorted(type_counts.items(), key=lambda x: -x[1]):
            tooltip += f"• {artifact_type}: {type_count}<br>"
        
        tooltip += "<br><i>Click to expand and see individual events</i>"
        
        return tooltip
    
    def _format_duration_tooltip(self, duration):
        """
        Format a timedelta as a human-readable string for tooltips.
        
        Args:
            duration (timedelta): Duration to format
        
        Returns:
            str: Formatted duration string
        """
        total_seconds = int(duration.total_seconds())
        
        if total_seconds == 0:
            return "< 1 second"
        elif total_seconds < 60:
            return f"{total_seconds} second{'s' if total_seconds != 1 else ''}"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            if seconds > 0:
                return f"{minutes} minute{'s' if minutes != 1 else ''}, {seconds} second{'s' if seconds != 1 else ''}"
            else:
                return f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if minutes > 0:
                return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{hours} hour{'s' if hours != 1 else ''}"
    
    def create_connection_line(self, event1_pos, event2_pos, y_offset1=0, y_offset2=0, y_level=200):
        """
        Create a curved line connecting correlated events.
        
        This creates a bezier curve that connects two events without obscuring
        other timeline elements. The curve arcs below the timeline markers.
        
        Args:
            event1_pos (float): X position of first event
            event2_pos (float): X position of second event
            y_offset1 (int): Vertical offset of first event (for stacking)
            y_offset2 (int): Vertical offset of second event (for stacking)
            y_level (float): Base Y position for the timeline
        
        Returns:
            QGraphicsPathItem: Connection line item with curved path
        """
        # Calculate Y positions for both events
        y1 = y_level + y_offset1 * self.MARKER_SPACING
        y2 = y_level + y_offset2 * self.MARKER_SPACING
        
        # Create a curved path using bezier curve
        path = QPainterPath()
        
        # Start point (bottom of first marker)
        start_point = QPointF(event1_pos, y1 + self.MARKER_RADIUS)
        path.moveTo(start_point)
        
        # End point (bottom of second marker)
        end_point = QPointF(event2_pos, y2 + self.MARKER_RADIUS)
        
        # Calculate control points for bezier curve
        # The curve arcs downward to avoid obscuring markers
        distance = abs(event2_pos - event1_pos)
        arc_depth = min(30, distance * 0.2)  # Arc depth based on distance
        
        # Control points create a smooth curve below the markers
        control1 = QPointF(event1_pos, y1 + self.MARKER_RADIUS + arc_depth)
        control2 = QPointF(event2_pos, y2 + self.MARKER_RADIUS + arc_depth)
        
        # Create cubic bezier curve
        path.cubicTo(control1, control2, end_point)
        
        # Create graphics item
        line_item = QGraphicsPathItem(path)
        
        # Style the connection line
        pen = QPen(QColor("#64748B"), 1.5, Qt.DashLine)  # Gray dashed line
        pen.setCapStyle(Qt.RoundCap)
        line_item.setPen(pen)
        
        # Set lower z-value so lines appear behind markers
        line_item.setZValue(-10)
        
        # Enable hover events for highlighting
        line_item.setAcceptHoverEvents(True)
        
        # Store connection data
        line_item.setData(0, {
            'type': 'connection_line',
            'event1_pos': event1_pos,
            'event2_pos': event2_pos
        })
        
        return line_item
    
    def highlight_connection_line(self, line_item, highlighted=True):
        """
        Apply or remove highlight effect from a connection line.
        
        Args:
            line_item (QGraphicsPathItem): Connection line to highlight
            highlighted (bool): True to highlight, False to remove highlight
        """
        if highlighted:
            # Make line more prominent when highlighted
            pen = QPen(QColor("#3B82F6"), 2.5, Qt.SolidLine)  # Blue solid line
            pen.setCapStyle(Qt.RoundCap)
            line_item.setPen(pen)
            line_item.setZValue(-5)  # Bring slightly forward
        else:
            # Restore normal appearance
            pen = QPen(QColor("#64748B"), 1.5, Qt.DashLine)  # Gray dashed line
            pen.setCapStyle(Qt.RoundCap)
            line_item.setPen(pen)
            line_item.setZValue(-10)
    
    def create_power_event_marker(self, power_event, position, timeline_height, top_y=50):
        """
        Create a vertical marker for system power events.
        
        Power events are displayed as vertical lines spanning the full timeline height
        with distinct colors for each event type (startup, shutdown, sleep, wake, hibernate).
        
        Args:
            power_event (dict): Power event data containing:
                - event_type: Type of power event (startup, shutdown, sleep, wake, hibernate)
                - timestamp: Event timestamp
                - description: Event description
                - source: Event source (EventLog, Kernel-Power, etc.)
                - message: Full event message
            position (float): X position on timeline (in scene coordinates)
            timeline_height (float): Height of timeline area
            top_y (float): Top Y position for the marker (default: 50)
        
        Returns:
            QGraphicsItemGroup: Power event marker with vertical line and icon
        """
        from PyQt5.QtWidgets import QGraphicsItemGroup, QGraphicsSimpleTextItem, QGraphicsPolygonItem
        from PyQt5.QtGui import QPolygonF
        
        # Get event type and color
        event_type = power_event.get('event_type', 'unknown')
        color = self.POWER_EVENT_COLORS.get(event_type, '#808080')
        
        # Create group to hold all marker elements
        group = QGraphicsItemGroup()
        
        # Create vertical line spanning timeline height
        line_width = 3
        line = QGraphicsRectItem(
            position - line_width / 2,
            top_y,
            line_width,
            timeline_height
        )
        
        # Style the line with solid pattern (changed from dashed to prevent artifacts)
        line.setBrush(QBrush(QColor(color)))
        pen = QPen(QColor(color), 0)  # No border
        pen.setStyle(Qt.SolidLine)  # Use solid line instead of dashed
        line.setPen(pen)
        line.setOpacity(0.6)  # Slightly more transparent for subtlety
        
        # Add line to group
        group.addToGroup(line)
        
        # Create icon at top of line based on event type
        icon_size = 16
        icon_y = top_y - icon_size - 5
        
        if event_type == 'startup':
            # Triangle pointing up for startup
            triangle = QPolygonF([
                QPointF(position, icon_y),
                QPointF(position - icon_size/2, icon_y + icon_size),
                QPointF(position + icon_size/2, icon_y + icon_size)
            ])
            icon = QGraphicsPolygonItem(triangle)
            icon.setBrush(QBrush(QColor(color)))
            icon.setPen(QPen(QColor("#FFFFFF"), 1))
            group.addToGroup(icon)
            
        elif event_type == 'shutdown':
            # Triangle pointing down for shutdown
            triangle = QPolygonF([
                QPointF(position, icon_y + icon_size),
                QPointF(position - icon_size/2, icon_y),
                QPointF(position + icon_size/2, icon_y)
            ])
            icon = QGraphicsPolygonItem(triangle)
            icon.setBrush(QBrush(QColor(color)))
            icon.setPen(QPen(QColor("#FFFFFF"), 1))
            group.addToGroup(icon)
            
        elif event_type in ['sleep', 'hibernate']:
            # Circle for sleep/hibernate
            icon = QGraphicsEllipseItem(
                position - icon_size/2,
                icon_y,
                icon_size,
                icon_size
            )
            icon.setBrush(QBrush(QColor(color)))
            icon.setPen(QPen(QColor("#FFFFFF"), 1))
            group.addToGroup(icon)
            
        elif event_type == 'wake':
            # Star-like shape for wake
            star = QPolygonF([
                QPointF(position, icon_y),
                QPointF(position - icon_size/4, icon_y + icon_size/3),
                QPointF(position - icon_size/2, icon_y + icon_size/3),
                QPointF(position - icon_size/4, icon_y + 2*icon_size/3),
                QPointF(position, icon_y + icon_size),
                QPointF(position + icon_size/4, icon_y + 2*icon_size/3),
                QPointF(position + icon_size/2, icon_y + icon_size/3),
                QPointF(position + icon_size/4, icon_y + icon_size/3)
            ])
            icon = QGraphicsPolygonItem(star)
            icon.setBrush(QBrush(QColor(color)))
            icon.setPen(QPen(QColor("#FFFFFF"), 1))
            group.addToGroup(icon)
        
        # Add text label at bottom
        label_text = event_type.capitalize()
        label = QGraphicsSimpleTextItem(label_text)
        label.setBrush(QBrush(QColor(color)))
        label.setFont(QFont("Segoe UI", 8, QFont.Bold))
        
        # Center label below line
        label_rect = label.boundingRect()
        label_x = position - label_rect.width() / 2
        label_y = top_y + timeline_height + 5
        label.setPos(label_x, label_y)
        group.addToGroup(label)
        
        # Store power event data
        group.setData(0, {
            'type': 'power_event',
            'event_data': power_event,
            'event_type': event_type
        })
        
        # Enable hover for highlighting
        group.setAcceptHoverEvents(True)
        group.setFlag(QGraphicsItem.ItemIsSelectable, True)
        
        # Create tooltip
        tooltip = self._create_power_event_tooltip(power_event)
        group.setToolTip(tooltip)
        
        # Set z-value to appear behind regular events but above background
        group.setZValue(-20)
        
        return group
    
    def update_cluster_expansion_visual(self, cluster_marker, expanded):
        """
        Update the visual appearance of a cluster marker to show expansion state.
        
        Changes the cluster marker's appearance to indicate whether it's expanded or collapsed:
        - Expanded: Green border with expansion icon badge
        - Collapsed: White border with normal appearance
        
        Args:
            cluster_marker (QGraphicsItemGroup): The cluster marker to update
            expanded (bool): True if expanded, False if collapsed
        """
        from PyQt5.QtWidgets import QGraphicsSimpleTextItem
        
        # Get the main circle (first child of the group)
        children = cluster_marker.childItems()
        if not children:
            return
        
        main_circle = children[0]  # First child is the main circle
        
        if expanded:
            # Change border to green to indicate expanded state
            main_circle.setPen(QPen(QColor("#10B981"), 3))  # Green border, thicker
            
            # Add expansion indicator icon if not already present
            # Check if expansion icon already exists
            has_expansion_icon = False
            for child in children:
                if hasattr(child, 'data') and child.data(1) == 'expansion_icon':
                    has_expansion_icon = True
                    break
            
            if not has_expansion_icon:
                # Add a small icon to indicate expansion (downward arrow or minus sign)
                icon_text = QGraphicsSimpleTextItem("▼")  # Down arrow
                icon_text.setBrush(QBrush(QColor("#10B981")))  # Green color
                icon_text.setFont(QFont("Segoe UI", 8, QFont.Bold))
                
                # Position at bottom-left of cluster
                cluster_rect = main_circle.boundingRect()
                icon_x = cluster_rect.left() - 5
                icon_y = cluster_rect.bottom() + 2
                icon_text.setPos(icon_x, icon_y)
                
                # Mark as expansion icon for later identification
                icon_text.setData(1, 'expansion_icon')
                
                # Add to group
                cluster_marker.addToGroup(icon_text)
        else:
            # Restore normal white border
            main_circle.setPen(QPen(QColor("#FFFFFF"), 2))
            
            # Remove expansion indicator icon if present
            for child in list(children):  # Use list() to avoid modification during iteration
                if hasattr(child, 'data') and child.data(1) == 'expansion_icon':
                    cluster_marker.removeFromGroup(child)
                    if child.scene():
                        child.scene().removeItem(child)
    
    def _create_power_event_tooltip(self, power_event):
        """
        Create tooltip text for a power event marker.
        
        Args:
            power_event (dict): Power event data
        
        Returns:
            str: Formatted tooltip HTML
        """
        event_type = power_event.get('event_type', 'Unknown')
        timestamp = power_event.get('timestamp')
        description = power_event.get('description', 'N/A')
        source = power_event.get('source', 'N/A')
        event_id = power_event.get('event_id', 'N/A')
        
        # Format timestamp
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            timestamp_str = str(timestamp)
        
        tooltip = f"""<b>Power Event: {event_type.capitalize()}</b><br>
<b>Time:</b> {timestamp_str}<br>
<b>Description:</b> {description}<br>
<b>Source:</b> {source}<br>
<b>Event ID:</b> {event_id}"""
        
        return tooltip
    
    def highlight_power_event(self, marker_group, highlighted=True):
        """
        Apply or remove highlight effect from a power event marker.
        
        Args:
            marker_group (QGraphicsItemGroup): Power event marker to highlight
            highlighted (bool): True to highlight, False to remove highlight
        """
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        
        if highlighted:
            # Make line more opaque and add glow
            children = marker_group.childItems()
            if children:
                line = children[0]  # First child is the vertical line
                line.setOpacity(1.0)
            
            # Add glow effect
            glow = QGraphicsDropShadowEffect()
            glow.setBlurRadius(20)
            glow.setColor(QColor("#FFFFFF"))
            glow.setOffset(0, 0)
            marker_group.setGraphicsEffect(glow)
            marker_group.setZValue(-15)  # Bring slightly forward
        else:
            # Restore normal appearance
            children = marker_group.childItems()
            if children:
                line = children[0]
                line.setOpacity(0.7)
            
            marker_group.setGraphicsEffect(None)
            marker_group.setZValue(-20)
    
    def get_color_for_artifact_type(self, artifact_type):
        """
        Get the color for a specific artifact type.
        
        Args:
            artifact_type (str): Artifact type name
        
        Returns:
            str: Hex color code
        """
        return self.COLORS.get(artifact_type, self.COLORS['Unknown'])
    
    def get_all_colors(self):
        """
        Get all artifact type colors for legend display.
        
        Returns:
            dict: Dictionary mapping artifact types to colors
        """
        return self.COLORS.copy()
    
    def create_system_off_period(self, start_pos, end_pos, timeline_height, top_y=50):
        """
        Create a grayed-out overlay for system off periods.
        
        This creates a semi-transparent gray rectangle that spans the timeline
        height to indicate when the system was powered off or sleeping.
        
        Args:
            start_pos (float): X position where system went off (shutdown/sleep)
            end_pos (float): X position where system came back (startup/wake)
            timeline_height (float): Height of timeline area
            top_y (float): Top Y position for the overlay (default: 50)
        
        Returns:
            QGraphicsRectItem: Semi-transparent overlay for off period
        """
        # Create rectangle spanning the off period
        width = end_pos - start_pos
        overlay = QGraphicsRectItem(
            start_pos,
            top_y,
            width,
            timeline_height
        )
        
        # Style with semi-transparent gray
        overlay.setBrush(QBrush(QColor(30, 30, 30, 100)))  # Dark gray, semi-transparent
        overlay.setPen(QPen(Qt.NoPen))  # No border
        
        # Set z-value to appear behind events but above background
        overlay.setZValue(-30)
        
        # Store off period data
        overlay.setData(0, {
            'type': 'system_off_period',
            'start_pos': start_pos,
            'end_pos': end_pos
        })
        
        # Enable hover to show duration
        overlay.setAcceptHoverEvents(True)
        
        return overlay
    
    def add_session_duration_label(self, start_pos, end_pos, duration_str, top_y=50):
        """
        Add a text label showing session duration.
        
        Args:
            start_pos (float): X position where session started
            end_pos (float): X position where session ended
            duration_str (str): Formatted duration string (e.g., "2h 30m")
            top_y (float): Top Y position for the label
        
        Returns:
            QGraphicsSimpleTextItem: Duration label
        """
        from PyQt5.QtWidgets import QGraphicsSimpleTextItem
        
        # Create text label
        label = QGraphicsSimpleTextItem(duration_str)
        label.setBrush(QBrush(QColor("#94A3B8")))  # Light gray
        label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        
        # Position label in center of session
        label_rect = label.boundingRect()
        label_x = (start_pos + end_pos) / 2 - label_rect.width() / 2
        label_y = top_y - 25
        label.setPos(label_x, label_y)
        
        # Set z-value to appear above everything
        label.setZValue(100)
        
        return label
    
    def create_aggregated_marker(self, bucket_data, position, base_y=200, bar_width=20):
        """
        Create a stacked bar chart marker for aggregated events.
        
        This creates a vertical bar chart showing event counts by artifact type
        for a time bucket. The bar is stacked with different colors for each
        artifact type.
        
        Args:
            bucket_data (dict): Aggregated bucket data containing:
                - time_bucket: Start of time bucket
                - bucket_size: Bucket size name
                - counts_by_type: Dictionary of {artifact_type: count}
                - total_count: Total events in bucket
                - event_ids: List of event IDs in bucket
            position (float): X position on timeline (center of bar)
            base_y (float): Base Y position for bars (default: 200)
            bar_width (float): Width of bar in pixels (default: 20)
        
        Returns:
            QGraphicsItemGroup: Aggregated marker with stacked bars
        """
        from PyQt5.QtWidgets import QGraphicsItemGroup, QGraphicsSimpleTextItem
        
        counts_by_type = bucket_data.get('counts_by_type', {})
        total_count = bucket_data.get('total_count', 0)
        
        if total_count == 0:
            logger.warning("Cannot create aggregated marker with zero events")
            return None
        
        # Create group to hold all bar segments
        group = QGraphicsItemGroup()
        
        # Calculate bar height based on total count
        # Use logarithmic scale for better visualization
        import math
        max_height = 150  # Maximum bar height in pixels
        min_height = 10   # Minimum bar height in pixels
        
        # Logarithmic scale: height = min + (max - min) * log(count + 1) / log(max_expected_count)
        # Assume max expected count per bucket is 1000
        max_expected = 1000
        height_factor = math.log(total_count + 1) / math.log(max_expected + 1)
        bar_height = min_height + (max_height - min_height) * height_factor
        bar_height = min(bar_height, max_height)  # Cap at max height
        
        # Sort artifact types by count (descending) for consistent stacking
        sorted_types = sorted(counts_by_type.items(), key=lambda x: -x[1])
        
        # Calculate segment heights proportional to counts
        current_y = base_y - bar_height
        
        for artifact_type, count in sorted_types:
            # Calculate segment height proportional to count
            segment_height = (count / total_count) * bar_height
            
            # Get color for artifact type
            color = self.COLORS.get(artifact_type, self.COLORS['Unknown'])
            
            # Create rectangle segment
            segment = QGraphicsRectItem(
                position - bar_width / 2,
                current_y,
                bar_width,
                segment_height
            )
            
            # Set appearance
            segment.setBrush(QBrush(QColor(color)))
            segment.setPen(QPen(QColor("#FFFFFF"), 1))
            
            # Add to group
            group.addToGroup(segment)
            
            # Move to next segment position
            current_y += segment_height
        
        # Add count label on top of bar
        count_label = QGraphicsSimpleTextItem(str(total_count))
        count_label.setBrush(QBrush(QColor("#FFFFFF")))
        count_label.setFont(QFont("Segoe UI", 8, QFont.Bold))
        
        # Position label above bar
        label_rect = count_label.boundingRect()
        label_x = position - label_rect.width() / 2
        label_y = base_y - bar_height - label_rect.height() - 2
        count_label.setPos(label_x, label_y)
        group.addToGroup(count_label)
        
        # Store bucket data in group
        group.setData(0, {
            'type': 'aggregated_marker',
            'bucket_data': bucket_data,
            'total_count': total_count
        })
        
        # Enable interaction
        group.setAcceptHoverEvents(True)
        group.setFlag(QGraphicsItem.ItemIsSelectable, True)
        
        # Create tooltip
        tooltip = self._create_aggregated_tooltip(bucket_data)
        group.setToolTip(tooltip)
        
        return group
    
    def _create_aggregated_tooltip(self, bucket_data):
        """
        Create tooltip text for an aggregated marker.
        
        Args:
            bucket_data (dict): Aggregated bucket data
        
        Returns:
            str: Formatted tooltip HTML
        """
        from timeline.data.event_aggregator import EventAggregator
        
        time_bucket = bucket_data.get('time_bucket')
        bucket_size = bucket_data.get('bucket_size', 'hour')
        counts_by_type = bucket_data.get('counts_by_type', {})
        total_count = bucket_data.get('total_count', 0)
        
        # Format time bucket
        aggregator = EventAggregator()
        bucket_label = aggregator.format_bucket_label(bucket_data)
        
        # Get time range
        start_time, end_time = aggregator.get_bucket_time_range(bucket_data)
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Build tooltip
        tooltip = f"""<b>Aggregated Events: {total_count}</b><br>
<b>Time Period:</b> {bucket_label}<br>
<b>Range:</b> {start_str} to {end_str}<br>
<br><b>Breakdown by Type:</b><br>"""
        
        # Sort by count descending
        for artifact_type, count in sorted(counts_by_type.items(), key=lambda x: -x[1]):
            color = self.COLORS.get(artifact_type, self.COLORS['Unknown'])
            tooltip += f'<span style="color: {color};">●</span> {artifact_type}: {count}<br>'
        
        tooltip += "<br><i>Click to zoom into this time period</i>"
        
        return tooltip
    
    def highlight_aggregated_marker(self, marker_group, highlighted=True):
        """
        Apply or remove highlight effect from an aggregated marker.
        
        Args:
            marker_group (QGraphicsItemGroup): Aggregated marker to highlight
            highlighted (bool): True to highlight, False to remove highlight
        """
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        
        if highlighted:
            # Add glow effect
            glow = QGraphicsDropShadowEffect()
            glow.setBlurRadius(15)
            glow.setColor(QColor("#00FFFF"))
            glow.setOffset(0, 0)
            marker_group.setGraphicsEffect(glow)
            marker_group.setZValue(50)
            
            # Make bars slightly more opaque
            for child in marker_group.childItems():
                if isinstance(child, QGraphicsRectItem):
                    child.setOpacity(1.0)
        else:
            # Remove glow
            marker_group.setGraphicsEffect(None)
            marker_group.setZValue(0)
            
            # Restore normal opacity
            for child in marker_group.childItems():
                if isinstance(child, QGraphicsRectItem):
                    child.setOpacity(1.0)
