"""
Timeline Renderer for EYE Forensic Assistant.

This module implements the TimelineRenderer class that renders timeline visualizations
for chronological event display in forensic reports.

"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import json


class TimelineRenderer:
    """
    Renders timeline visualizations with event positioning and category coloring.
    """
    
    def __init__(self, color_manager: Optional[Any] = None):
        """
        Initialize TimelineRenderer.
        
        Args:
            color_manager: Optional ColorManager instance for category color assignment
        """
        self.color_manager = color_manager
    
    def render_timeline(
        self,
        title: str,
        events: List[Dict[str, Any]],
        color_scheme: Optional[str] = None,
        custom_colors: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Render timeline visualization configuration.
        
        Args:
            title: Timeline title
            events: List of event dicts with {timestamp, label, description, category}
            color_scheme: Optional palette name for category colors
            custom_colors: Optional category -> color mapping (overrides palette)
            
        Returns:
            Timeline configuration dictionary for rendering
            
        """
        # Sort events by timestamp
        sorted_events = sorted(
            events,
            key=lambda e: self._parse_timestamp(e.get("timestamp", ""))
        )
        
        # Extract unique categories
        categories = list(set(e.get("category", "default") for e in sorted_events))
        
        # Assign colors to categories
        category_colors = self._assign_category_colors(
            categories,
            color_scheme,
            custom_colors
        )
        
        # Build timeline data structure
        timeline_data = {
            "title": title,
            "events": sorted_events,
            "categories": categories,
            "category_colors": category_colors,
            "color_scheme": color_scheme or "forensic"
        }
        
        return timeline_data
    
    def _assign_category_colors(
        self,
        categories: List[str],
        color_scheme: Optional[str],
        custom_colors: Optional[Dict[str, str]]
    ) -> Dict[str, str]:
        """
        Assign colors to timeline categories.
        
        Args:
            categories: List of unique category names
            color_scheme: Optional palette name
            custom_colors: Optional custom color mapping
            
        Returns:
            Dictionary mapping category names to hex colors
            
        """
        category_colors = {}
        
        # Use custom colors if provided
        if custom_colors:
            for category in categories:
                if category in custom_colors:
                    category_colors[category] = custom_colors[category]
                else:
                    # Fall back to default color for unmapped categories
                    category_colors[category] = "#8899aa"
            return category_colors
        
        # Use color manager if available
        if self.color_manager:
            palette_name = color_scheme or "forensic"
            try:
                palette = self.color_manager.get_palette(palette_name)
                for i, category in enumerate(categories):
                    category_colors[category] = palette[i % len(palette)]
            except Exception:
                # Fall back to default colors if palette not found
                default_colors = [
                    "#f97316", "#06b6d4", "#ec4899", "#10b981", "#ff4d6a",
                    "#8b5cf6", "#f59e0b", "#14b8a6", "#ef4444", "#3b82f6"
                ]
                for i, category in enumerate(categories):
                    category_colors[category] = default_colors[i % len(default_colors)]
        else:
            # Use default forensic palette colors
            default_colors = [
                "#f97316", "#06b6d4", "#ec4899", "#10b981", "#ff4d6a",
                "#8b5cf6", "#f59e0b", "#14b8a6", "#ef4444", "#3b82f6"
            ]
            for i, category in enumerate(categories):
                category_colors[category] = default_colors[i % len(default_colors)]
        
        return category_colors
    
    def _parse_timestamp(self, timestamp: Any) -> datetime:
        """
        Parse timestamp string to datetime object.
        
        Args:
            timestamp: Timestamp string or datetime object
            
        Returns:
            datetime object
        """
        if isinstance(timestamp, datetime):
            return timestamp
        
        if isinstance(timestamp, str):
            # Try common timestamp formats
            formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d"
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(timestamp, fmt)
                except ValueError:
                    continue
            
            # Try ISO format
            try:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                pass
        
        # Fall back to current time if parsing fails
        return datetime.now()
    
    def generate_html(self, timeline_data: Dict[str, Any]) -> str:
        """
        Generate HTML representation of timeline.
        
        Args:
            timeline_data: Timeline configuration from render_timeline
            
        Returns:
            HTML string for timeline visualization
        """
        title = timeline_data.get("title", "Timeline")
        events = timeline_data.get("events", [])
        category_colors = timeline_data.get("category_colors", {})
        
        # Build timeline HTML
        events_html = []
        for event in events:
            category = event.get("category", "default")
            color = category_colors.get(category, "#8899aa")
            label = event.get("label", "Event")
            description = event.get("description", "")
            timestamp = event.get("timestamp", "")
            
            event_html = f"""
            <div class="timeline-event" style="border-left: 3px solid {color};">
                <div class="timeline-event-header">
                    <span class="timeline-event-label">{self._escape_html(label)}</span>
                    <span class="timeline-event-time">{self._escape_html(str(timestamp))}</span>
                </div>
                <div class="timeline-event-description">{self._escape_html(description)}</div>
                <div class="timeline-event-category" style="color: {color};">{self._escape_html(category)}</div>
            </div>
            """
            events_html.append(event_html)
        
        html = f"""
        <div class="timeline-container">
            <h3 class="timeline-title">{self._escape_html(title)}</h3>
            <div class="timeline-events">
                {''.join(events_html)}
            </div>
        </div>
        """
        
        return html
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;")
