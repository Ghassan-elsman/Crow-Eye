"""
Tooltip Manager - Centralized tooltip management for timeline components.

This module provides comprehensive tooltip text for all timeline UI elements,
ensuring consistent and helpful user guidance throughout the interface.
"""

class TooltipManager:
    """
    Centralized manager for all timeline tooltips.
    
    Provides descriptive, user-friendly tooltips for all interactive elements
    in the timeline visualization interface.
    """
    
    # Filter Bar Tooltips
    FILTER_TOOLTIPS = {
        'prefetch': 'Prefetch files show program execution history',
        'lnk': 'LNK (shortcut) files track recently accessed files and folders',
        'registry': 'Registry artifacts contain system and application configuration changes',
        'bam': 'Background Activity Moderator tracks application execution',
        'shellbag': 'ShellBags record folder access and window positions',
        'srum': 'System Resource Usage Monitor tracks application resource usage',
        'usn': 'USN Journal records file system changes',
        'mft': 'Master File Table contains file metadata and timestamps',
        'logs': 'Windows Event Logs record system and application events',
        
        'select_all': 'Select all artifact types to display on timeline',
        'deselect_all': 'Deselect all artifact types to clear timeline',
        
        'all_time': 'Display all events from earliest to latest timestamp',
        'custom_range': 'Specify a custom date/time range to display',
        
        'zoom_in': 'Zoom in to see more detail (Keyboard: +)',
        'zoom_out': 'Zoom out to see broader time range (Keyboard: -)',
        'zoom_level': 'Current zoom level - controls time scale granularity',
        
        'event_count': 'Total events loaded and currently visible after filtering',
        'sampling_indicator': 'Events are sampled for performance - use filters or zoom to see more detail',
        'disable_sampling': 'Load all events (may impact performance with large datasets)',
        
        'srum_show_ids': 'Display SRUM application IDs alongside resolved names',
        'advanced_options': 'Show/hide advanced filtering options',
        
        'power_events': 'Show system power events (startup, shutdown, sleep, wake)',
        'clustering': 'Group nearby events to reduce visual clutter',
        'grouping_mode': 'Choose how to group related events',
        'force_individual': 'Always show individual events (disable automatic aggregation)',
    }
    
    # Timeline Canvas Tooltips
    CANVAS_TOOLTIPS = {
        'event_marker': 'Click to select, Ctrl+Click to multi-select, Double-click to jump to event',
        'cluster_marker': 'Click to expand and see individual events',
        'aggregated_marker': 'Click to zoom in and see individual events',
        'power_event': 'System power event - hover for details',
        'connection_line': 'Events connected by temporal correlation',
        
        'pan_hint': 'Click and drag to pan timeline, or use scrollbar',
        'zoom_hint': 'Use mouse wheel to zoom, or zoom buttons in filter bar',
        'select_hint': 'Click events to select, Ctrl+Click for multi-select, Shift+Click for range',
    }
    
    # Event Details Panel Tooltips
    DETAILS_TOOLTIPS = {
        'copy_details': 'Copy selected event details to clipboard',
        'jump_to_event': 'Navigate to this event in the main Crow Eye interface',
        'event_context': 'Shows events that occurred near this event in time',
        'related_events': 'Shows events related to the same file or application',
    }
    
    # Dialog Tooltips
    DIALOG_TOOLTIPS = {
        'close': 'Close timeline dialog (Keyboard: Esc)',
        'export': 'Export timeline to CSV, JSON, or PNG image',
        'bookmark': 'Save current timeline view for quick access later',
        'help': 'Show timeline help and keyboard shortcuts',
    }
    
    @classmethod
    def get_filter_tooltip(cls, key):
        """
        Get tooltip for filter bar element.
        
        Args:
            key (str): Tooltip key
        
        Returns:
            str: Tooltip text
        """
        return cls.FILTER_TOOLTIPS.get(key, '')
    
    @classmethod
    def get_canvas_tooltip(cls, key):
        """
        Get tooltip for canvas element.
        
        Args:
            key (str): Tooltip key
        
        Returns:
            str: Tooltip text
        """
        return cls.CANVAS_TOOLTIPS.get(key, '')
    
    @classmethod
    def get_details_tooltip(cls, key):
        """
        Get tooltip for details panel element.
        
        Args:
            key (str): Tooltip key
        
        Returns:
            str: Tooltip text
        """
        return cls.DETAILS_TOOLTIPS.get(key, '')
    
    @classmethod
    def get_dialog_tooltip(cls, key):
        """
        Get tooltip for dialog element.
        
        Args:
            key (str): Tooltip key
        
        Returns:
            str: Tooltip text
        """
        return cls.DIALOG_TOOLTIPS.get(key, '')
    
    @classmethod
    def get_artifact_tooltip(cls, artifact_type):
        """
        Get tooltip for specific artifact type.
        
        Args:
            artifact_type (str): Artifact type name
        
        Returns:
            str: Tooltip text
        """
        key = artifact_type.lower()
        return cls.FILTER_TOOLTIPS.get(key, f'{artifact_type} artifacts')
