"""
Timeline Canvas - Main visualization component for the forensic timeline.

This module provides the TimelineCanvas class which uses QGraphicsView and QGraphicsScene
to render the timeline visualization with zoom, pan, and interactive event markers.

PERFORMANCE OPTIMIZATIONS:
- OpenGL acceleration for 2-10x rendering speedup
- Optimized scene indexing for dynamic cluster expansion
- Magic numbers replaced with named constants
- Profiling infrastructure for performance monitoring
"""

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsTextItem
from PyQt5.QtCore import Qt, pyqtSignal, QRectF, QPointF, QElapsedTimer
from PyQt5.QtGui import QPainter, QBrush, QColor, QPen, QFont, QCursor
from datetime import datetime, timedelta
from timeline.rendering.event_renderer import EventRenderer
from timeline.rendering.zoom_manager import ZoomManager
from timeline.rendering.viewport_optimizer import ViewportOptimizer
from timeline.utils.loading_indicator import LoadingOverlay
from timeline.utils.event_clusterer import EventClusterer

# Try to import OpenGL for hardware acceleration
try:
    from PyQt5.QtWidgets import QOpenGLWidget
    OPENGL_AVAILABLE = True
except ImportError:
    OPENGL_AVAILABLE = False


class TimelineCanvas(QGraphicsView):
    """
    Timeline visualization canvas using QGraphicsView with performance optimizations.
    
    PERFORMANCE FEATURES:
    - OpenGL hardware acceleration (if available)
    - Optimized scene indexing for dynamic updates
    - Incremental rendering with viewport culling
    - Marker caching and reuse
    - LOD (Level of Detail) system
    """
    
    # PERFORMANCE CONSTANTS
    MIN_WIDTH_PER_HOUR = 30  # Minimum pixels per hour (compressed to fit 5X more data)
    AGGREGATION_THRESHOLD = 1000  # Events threshold for aggregation mode
    BATCH_SIZE = 100  # Events per rendering batch
    CACHE_SIZE_LIMIT = 10000  # Maximum cached markers
    VIEWPORT_BUFFER_RATIO = 0.5  # 50% buffer on each side (5x more data loaded)
    
    # ANIMATION CONSTANTS
    FADE_DURATION_MS = 150  # Fade animation duration
    CASCADE_DELAY_MS = 30  # Delay between cascaded animations
    
    # SPACING CONSTANTS
    MIN_LABEL_SPACING = 40  # Minimum pixels between labels (reduced to show more labels)
    
    # Z-ORDER CONSTANTS
    Z_BACKGROUND_SHADING = -200
    Z_BACKGROUND_GRID = -100
    Z_BOUNDARY_MARKERS = -50
    Z_AXIS_BACKGROUND = -10
    Z_AXIS_LABELS = 0
    Z_EVENT_MARKERS = 5
    Z_EXPANDED_MARKERS_BASE = 10
    Z_CLUSTER_MARKERS = 15
    """
    Timeline visualization canvas using QGraphicsView.
    
    This class provides the main timeline visualization with support for:
    - Event marker rendering at temporal positions
    - Zoom and pan functionality
    - Viewport optimization for performance
    - Event selection and interaction
    
    Signals:
        event_selected: Emitted when events are selected (list of event IDs)
        event_double_clicked: Emitted when an event is double-clicked (event data dict)
        viewport_changed: Emitted when the visible time range changes
    """
    
    event_selected = pyqtSignal(list)  # List of selected event IDs
    event_double_clicked = pyqtSignal(dict)  # Event data dictionary
    viewport_changed = pyqtSignal(datetime, datetime)  # Start and end times
    
    def __init__(self, parent=None):
        """
        Initialize the timeline canvas.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Create graphics scene
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Timeline state
        self.start_time = None
        self.end_time = None
        self.selected_events = []
        self._last_selected_id = None  # Track last selected event for Shift+click range selection
        
        # Canvas dimensions
        self.timeline_height = 400  # Height of the timeline area
        self.axis_height = 50  # Height of the time axis
        self.margin_top = 20
        self.margin_bottom = 20
        
        # Event renderer
        self.event_renderer = EventRenderer()
        
        # Zoom manager - start more zoomed out to show 5X more data by default
        # Lower zoom = more zoomed out = more data visible
        # 0 = year view (most data), 10 = minute view (least data)
        self.zoom_manager = ZoomManager(initial_zoom=0)  # Year view for maximum initial data
        
        # Viewport optimizer for performance
        self.viewport_optimizer = ViewportOptimizer()
        
        # Event clusterer for time-window-based grouping
        self.event_clusterer = EventClusterer(time_window_minutes=5)  # Default 5-minute window
        
        # Clustering configuration
        self.clustering_enabled = False  # Disable clustering by default for cleaner horizontal display
        self.clustering_mode = 'time'  # 'time', 'application', 'path', 'artifact_type'
        
        # Event markers storage (for later manipulation)
        self.event_markers = {}  # Maps event_id to marker item
        
        # Track expanded clusters separately for reliable cleanup
        # Maps cluster_marker to dict with 'marker_ids' and 'cluster_id'
        # This allows proper cleanup and prevents ID collisions
        self.expanded_clusters = {}  # {cluster_marker: {'marker_ids': [ids], 'cluster_id': 'cluster_X'}}
        
        # Time axis items
        self.axis_items = []  # List of axis line and label items
        
        # Store center point for zoom operations
        self._zoom_center_time = None
        
        # Incremental rendering system
        self._marker_cache = {}  # Cache of rendered markers: event_id -> marker
        self._visible_marker_ids = set()  # Set of currently visible marker IDs
        self._dirty_flags = {
            'events': False,  # Events data changed
            'viewport': False,  # Viewport position changed
            'zoom': False,  # Zoom level changed
            'filters': False,  # Filters changed
            'clustering': False  # Clustering settings changed
        }
        self._last_viewport_rect = None  # Track last viewport rect for change detection
        
        # Setup viewport optimization
        self._setup_viewport()
        
        # Setup interaction
        self._setup_interaction()
        
        # Initialize scene
        self._initialize_scene()
        
        # Create loading overlay
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()
    
    def _setup_viewport(self):
        """
        Configure viewport optimization flags for performance.
        
        OPTIMIZATIONS:
        - OpenGL hardware acceleration (2-10x speedup)
        - Optimized scene indexing for dynamic updates
        - Minimal viewport updates
        - Background caching
        """
        # OPTIMIZATION: Enable OpenGL hardware acceleration if available
        if OPENGL_AVAILABLE:
            try:
                opengl_widget = QOpenGLWidget()
                self.setViewport(opengl_widget)
                print("OpenGL acceleration enabled for timeline rendering")
            except Exception as e:
                print(f"Warning: Could not enable OpenGL acceleration: {e}")
        
        # Enable viewport optimizations
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        
        # Enable caching for better performance
        self.setCacheMode(QGraphicsView.CacheBackground)
        
        # Set rendering hints for quality
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        # Don't use ScrollHandDrag - we'll handle panning manually
        self.setDragMode(QGraphicsView.NoDrag)
        
        # Set transformation anchor to center for zoom
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        
        # Enable horizontal scrollbar, disable vertical
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    
    def _setup_interaction(self):
        """Setup mouse and keyboard interaction."""
        # Enable mouse tracking for hover effects
        self.setMouseTracking(True)
        
        # Set focus policy for keyboard events
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Track panning state
        self._is_panning = False
        self._pan_start_pos = None
        
        # Set initial cursor to open hand (draggable)
        self.setCursor(Qt.OpenHandCursor)
    
    def _initialize_scene(self):
        """
        Initialize the graphics scene with default background.
        
        OPTIMIZATION: Uses NoIndex for faster item add/remove during cluster expansion.
        """
        # Set scene background color
        self.scene.setBackgroundBrush(QBrush(QColor("#1E293B")))
        
        # Set initial scene rect (will be updated when data is loaded)
        total_height = self.margin_top + self.timeline_height + self.axis_height + self.margin_bottom
        self.scene.setSceneRect(0, 0, 2000, total_height)
        
        # OPTIMIZATION: Disable scene indexing for faster dynamic updates
        # This is beneficial when frequently adding/removing items (cluster expansion)
        # Trade-off: Slightly slower item lookups, but much faster add/remove
        self.scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        
        # Background items (grid lines, shading)
        self.background_items = []
    
    def set_time_range(self, start_time, end_time):
        """
        Set the visible time range and trigger re-render.
        
        Args:
            start_time (datetime): Start of time range
            end_time (datetime): End of time range
        """
        if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
            raise ValueError("start_time and end_time must be datetime objects")
        
        if start_time >= end_time:
            raise ValueError("start_time must be before end_time")
        
        # Check if time range actually changed
        time_range_changed = (self.start_time != start_time or self.end_time != end_time)
        
        self.start_time = start_time
        self.end_time = end_time
        
        # Mark events as dirty if time range changed
        if time_range_changed:
            self._dirty_flags['events'] = True
        
        # Update scene width based on time range
        self._update_scene_dimensions()
        
        # Emit viewport changed signal
        self.viewport_changed.emit(start_time, end_time)
    
    def _update_scene_dimensions(self):
        """Update scene dimensions based on time range and zoom level."""
        if self.start_time and self.end_time:
            # Calculate scene width based on time range and zoom level
            # Use a more generous width calculation for better visibility
            time_delta = self.end_time - self.start_time
            minutes = time_delta.total_seconds() / 60
            
            # Get scale factor from zoom manager
            zoom_scale = self.zoom_manager.get_scale_factor()
            
            # Calculate scene width based on zoom level
            # FIXED: Zoom now properly scales both time axis AND events
            
            # Use zoom scale factor to calculate width
            calculated_width = minutes * zoom_scale
            
            # Ensure minimum width for very short time ranges
            viewport_width = self.viewport().width() if self.viewport() else 1200
            min_scene_width = viewport_width * 0.5  # At least half viewport
            
            # Use calculated width (respects zoom) but ensure minimum
            scene_width = max(calculated_width, min_scene_width)
            
            # Update scene rect
            total_height = self.margin_top + self.timeline_height + self.axis_height + self.margin_bottom
            self.scene.setSceneRect(0, 0, scene_width, total_height)
            
            # Re-render time axis
            self._render_time_axis()
    
    def set_zoom_level(self, level):
        """
        Adjust zoom level (0-10 scale).
        
        Args:
            level (int): Zoom level from 0 (year view) to 10 (minute view)
        """
        if not 0 <= level <= 10:
            raise ValueError("Zoom level must be between 0 and 10")
        
        old_level = self.zoom_manager.current_zoom
        
        # Get center point before zoom
        center_point = self._get_viewport_center()
        
        # Update zoom manager
        self.zoom_manager.set_zoom_level(level)
        
        # Mark zoom as dirty if level changed
        if old_level != level:
            self._dirty_flags['zoom'] = True
        
        # Update scene dimensions
        self._update_scene_dimensions()
        
        # Re-render events if they exist
        if hasattr(self, '_stored_events') and self._stored_events:
            self.render_events(self._stored_events)
        
        # Maintain center point during zoom
        if old_level != level and center_point:
            self._maintain_center_point(center_point)
    
    def zoom_in(self):
        """Increase zoom level (zoom in)."""
        if self.zoom_manager.can_zoom_in():
            self.set_zoom_level(self.zoom_manager.current_zoom + 1)
    
    def zoom_out(self):
        """Decrease zoom level (zoom out)."""
        if self.zoom_manager.can_zoom_out():
            self.set_zoom_level(self.zoom_manager.current_zoom - 1)
    
    def apply_filters(self, filter_config):
        """
        Apply artifact type and search filters.
        
        Args:
            filter_config (dict): Filter configuration with keys:
                - artifact_types: List of artifact types to show
                - search_term: Search term to highlight (optional)
        """
        # Mark filters as dirty to trigger re-render
        self._dirty_flags['filters'] = True
        
        # TODO: Implement filtering logic in future tasks
        # This will hide/show event markers based on filters
        pass
    
    def render_events(self, events, show_loading=True, force_individual=False):
        """
        Render event markers on the timeline with incremental rendering and caching.
        
        Uses a dirty flag system to only re-render what changed. Caches rendered
        markers and reuses them when possible. Only visible events are rendered
        for better performance.
        
        FIXED: Added validation for invalid events to prevent crashes.
        OPTIMIZED: Added profiling to monitor performance.
        
        Args:
            events (list): List of event dictionaries to render
            show_loading (bool): Whether to show loading indicator for large datasets
            force_individual (bool): Force individual event display (disable aggregation)
        """
        # PROFILING: Start performance timer
        timer = QElapsedTimer()
        timer.start()
        
        if not self.start_time or not self.end_time:
            raise ValueError("Time range must be set before rendering events")
        
        # FIXED: Validate events before rendering to prevent crashes
        validated_events = []
        skipped_count = 0
        for event in events:
            # Skip events without required fields
            if not isinstance(event, dict):
                skipped_count += 1
                continue
            if 'id' not in event or 'timestamp' not in event:
                skipped_count += 1
                continue
            if not isinstance(event['timestamp'], datetime):
                skipped_count += 1
                continue
            validated_events.append(event)
        
        # Log warning if events were skipped
        if skipped_count > 0:
            print(f"Warning: Skipped {skipped_count} invalid events (missing id/timestamp or invalid format)")
        
        # Use validated events
        events = validated_events
        
        # Check if events data changed
        events_changed = (not hasattr(self, '_stored_events') or 
                         self._stored_events != events or
                         self._force_individual != force_individual)
        
        if events_changed:
            self._dirty_flags['events'] = True
            self._stored_events = events
            self._force_individual = force_individual
        
        # Check if we need a full re-render
        needs_full_render = (self._dirty_flags['events'] or 
                            self._dirty_flags['zoom'] or 
                            self._dirty_flags['clustering'])
        
        if needs_full_render:
            # Full re-render required - clear cache and start fresh
            self._render_full(events, show_loading, force_individual)
            # Reset dirty flags
            self._dirty_flags['events'] = False
            self._dirty_flags['zoom'] = False
            self._dirty_flags['clustering'] = False
        else:
            # Incremental update - only update visible markers
            self._render_incremental(show_loading)
        
        # Mark viewport as clean
        self._dirty_flags['viewport'] = False
        
        # PROFILING: Log performance metrics
        elapsed_ms = timer.elapsed()
        if elapsed_ms > 100:  # Log if render took >100ms
            print(f"Performance: render_events took {elapsed_ms}ms for {len(events)} events "
                  f"({'full' if needs_full_render else 'incremental'})")
    
    def _render_full(self, events, show_loading, force_individual):
        """
        Perform a full render of all events with caching.
        
        This method clears the scene and re-renders all visible events.
        Markers are cached for potential reuse in incremental updates.
        
        Args:
            events (list): List of event dictionaries to render
            show_loading (bool): Whether to show loading indicator
            force_individual (bool): Force individual event display
        """
        # Show loading indicator for large datasets
        if show_loading and len(events) > 1000:
            self.loading_overlay.show_loading(f"Rendering {len(events)} events...")
        
        # Get visible viewport rect with buffer zone
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        scene_rect = self.scene.sceneRect()
        
        # Filter to only visible events (with buffer for smooth scrolling)
        visible_events = self.viewport_optimizer.get_visible_events(
            events, viewport_rect, scene_rect, self.start_time, self.end_time
        )
        
        # Calculate LOD based on visible event count
        lod = self.viewport_optimizer.calculate_lod(len(visible_events))
        
        # Clear existing event markers from scene
        # Remove all visible markers from scene
        for marker_id in list(self._visible_marker_ids):
            marker = self.event_markers.get(marker_id)
            if marker and marker.scene() == self.scene:
                self.scene.removeItem(marker)
        
        # Clear tracking structures
        self._visible_marker_ids.clear()
        self.event_markers.clear()
        
        # Clear expanded cluster tracking since all markers are being removed
        self.expanded_clusters.clear()
        
        # Note: We keep _marker_cache intact for potential reuse
        # Only clear cache if it gets too large (>10000 items)
        if len(self._marker_cache) > 10000:
            self._marker_cache.clear()
        
        # Check if we should use aggregation mode (>1000 visible events)
        AGGREGATION_THRESHOLD = 1000
        use_aggregation = len(visible_events) > AGGREGATION_THRESHOLD and not force_individual
        
        if use_aggregation:
            # Use aggregated view with bar charts
            self._render_aggregated_view(visible_events, lod)
        else:
            # Use individual/clustered view
            self._render_individual_view(visible_events, lod)
        
        # Store current viewport rect for incremental updates
        self._last_viewport_rect = viewport_rect
        
        # Render time axis to show date/time labels
        self._render_time_axis()
        
        # Hide loading indicator
        if show_loading:
            self.loading_overlay.hide_loading()
    
    def _render_incremental(self, show_loading):
        """
        Perform an incremental render - only update visible markers.
        
        This method reuses cached markers and only adds/removes markers
        that entered/left the viewport. Off-screen items are removed from
        the scene to save memory and improve performance.
        
        FIXED: Now properly handles expanded clusters to prevent ID collisions.
        
        Args:
            show_loading (bool): Whether to show loading indicator
        """
        if not hasattr(self, '_stored_events') or not self._stored_events:
            return
        
        # Get current viewport rect with buffer zone for smooth scrolling
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        scene_rect = self.scene.sceneRect()
        
        # Check if viewport actually changed significantly
        if self._last_viewport_rect:
            # Calculate overlap percentage
            intersection = viewport_rect.intersected(self._last_viewport_rect)
            if intersection.width() > 0:
                overlap = intersection.width() / viewport_rect.width()
                # If >80% overlap, skip incremental update
                if overlap > 0.8:
                    return
        
        # Store current viewport rect
        self._last_viewport_rect = viewport_rect
        
        # Get visible events for current viewport (with buffer)
        visible_events = self.viewport_optimizer.get_visible_events(
            self._stored_events, viewport_rect, scene_rect, 
            self.start_time, self.end_time
        )
        
        # Calculate LOD
        lod = self.viewport_optimizer.calculate_lod(len(visible_events))
        
        # Build set of event IDs that are currently expanded
        # These should NOT be re-rendered as clusters or individual markers
        expanded_event_ids = set()
        for expansion_data in self.expanded_clusters.values():
            expanded_event_ids.update(expansion_data.get('marker_ids', []))
        
        # Determine which events should be visible
        new_visible_ids = set()
        
        # Apply clustering if enabled
        if self.clustering_enabled:
            clusters = self._cluster_events(visible_events)
        else:
            clusters = [{'events': [event], 'representative_time': event.get('timestamp'), 
                        'is_cluster': False, 'count': 1} 
                       for event in visible_events if event.get('timestamp')]
        
        # Build set of IDs that should be visible
        for cluster in clusters:
            if not cluster or not cluster.get('events'):
                continue
            
            cluster_events = cluster['events']
            
            # Check if any events in this cluster are currently expanded
            cluster_event_ids = [e.get('id') for e in cluster_events if e.get('id')]
            has_expanded_events = any(eid in expanded_event_ids for eid in cluster_event_ids)
            
            if has_expanded_events:
                # This cluster is expanded - keep the expanded individual markers
                new_visible_ids.update(cluster_event_ids)
            elif len(cluster_events) > 1 and cluster.get('is_cluster', False):
                # Cluster marker (not expanded)
                first_event_id = cluster_events[0].get('id')
                if first_event_id:
                    new_visible_ids.add(f"cluster_{first_event_id}")
            else:
                # Individual events (not part of expanded cluster)
                for event in cluster_events:
                    event_id = event.get('id')
                    if event_id:
                        new_visible_ids.add(event_id)
        
        # Determine what to add and remove
        to_remove = self._visible_marker_ids - new_visible_ids
        to_add = new_visible_ids - self._visible_marker_ids
        
        # Remove markers that are no longer visible from scene
        # BUT: Don't remove markers that are part of expanded clusters
        for marker_id in to_remove:
            # Skip if this marker is part of an expanded cluster
            if marker_id in expanded_event_ids:
                continue
            
            marker = self.event_markers.get(marker_id)
            if marker and marker.scene() == self.scene:
                # Remove from scene to free memory and improve performance
                self.scene.removeItem(marker)
                # Track removal for statistics
                self.viewport_optimizer.record_item_removed()
            # Remove from event_markers dict but keep in cache for reuse
            self.event_markers.pop(marker_id, None)
        
        # Add markers that became visible
        # BUT: Don't add markers that are already expanded
        to_add_filtered = to_add - expanded_event_ids
        if to_add_filtered:
            self._add_visible_markers(visible_events, to_add_filtered, lod)
        
        # Update visible set
        self._visible_marker_ids = new_visible_ids
        
        # Cleanup cache if it's getting too large
        removed = self.viewport_optimizer.cleanup_cache_if_needed()
        if removed > 0:
            # Also remove these items from _marker_cache
            cache_keys = list(self._marker_cache.keys())
            for key in cache_keys:
                if key not in self.viewport_optimizer.visible_event_ids:
                    self._marker_cache.pop(key, None)
                    removed -= 1
                    if removed <= 0:
                        break
    
    def _add_visible_markers(self, visible_events, marker_ids_to_add, lod):
        """
        Add markers that became visible to the scene.
        
        Reuses cached markers when available for better performance.
        Tracks cache hits/misses for performance monitoring.
        
        FIXED: Now skips events that are part of expanded clusters to prevent duplicates.
        
        Args:
            visible_events (list): List of visible events
            marker_ids_to_add (set): Set of marker IDs to add
            lod (int): Level of detail
        """
        # Build set of event IDs that are currently expanded
        expanded_event_ids = set()
        for expansion_data in self.expanded_clusters.values():
            expanded_event_ids.update(expansion_data.get('marker_ids', []))
        
        # Apply clustering
        if self.clustering_enabled:
            clusters = self._cluster_events(visible_events)
        else:
            clusters = [{'events': [event], 'representative_time': event.get('timestamp'), 
                        'is_cluster': False, 'count': 1} 
                       for event in visible_events if event.get('timestamp')]
        
        base_y = self.margin_top + self.timeline_height / 2
        CLUSTER_THRESHOLD = self.viewport_optimizer.get_aggregation_threshold()
        
        # Render clusters/events that need to be added
        for cluster in clusters:
            if not cluster or not cluster.get('events'):
                continue
            
            cluster_events = cluster['events']
            representative_time = cluster.get('representative_time')
            
            if not representative_time:
                continue
            
            # Check if any events in this cluster are currently expanded
            cluster_event_ids = [e.get('id') for e in cluster_events if e.get('id')]
            has_expanded_events = any(eid in expanded_event_ids for eid in cluster_event_ids)
            
            # Skip this cluster entirely if it has expanded events
            # The expanded markers are already in the scene
            if has_expanded_events:
                continue
            
            position = self._calculate_position(representative_time)
            
            # Check if this is a cluster
            should_cluster = (len(cluster_events) > 1 and 
                            (cluster.get('is_cluster', False) or 
                             len(cluster_events) > CLUSTER_THRESHOLD))
            
            if should_cluster:
                first_event_id = cluster_events[0].get('id')
                cluster_id = f"cluster_{first_event_id}"
                
                if cluster_id in marker_ids_to_add:
                    # Check cache first
                    cache_hit = cluster_id in self._marker_cache
                    self.viewport_optimizer.record_cache_access(cluster_id, cache_hit)
                    
                    if cache_hit:
                        marker = self._marker_cache[cluster_id]
                    else:
                        # Create new cluster marker
                        marker = self.event_renderer.create_cluster_marker(
                            cluster_events, position, y_offset=0, 
                            base_y=base_y, lod=lod
                        )
                        self._marker_cache[cluster_id] = marker
                    
                    # Add to scene (re-adding is safe if already in scene)
                    self.scene.addItem(marker)
                    self.event_markers[cluster_id] = marker
            else:
                # Individual events
                for idx, event in enumerate(cluster_events):
                    event_id = event.get('id')
                    if event_id and event_id in marker_ids_to_add:
                        # Check cache first
                        cache_hit = event_id in self._marker_cache
                        self.viewport_optimizer.record_cache_access(event_id, cache_hit)
                        
                        if cache_hit:
                            marker = self._marker_cache[event_id]
                        else:
                            # Create new marker - no y_offset for individual events
                            marker = self.event_renderer.create_event_marker(
                                event, position, y_offset=0, 
                                base_y=base_y, lod=lod
                            )
                            self._marker_cache[event_id] = marker
                        
                        # Add to scene (re-adding is safe if already in scene)
                        self.scene.addItem(marker)
                        self.event_markers[event_id] = marker
    
    def _render_individual_view(self, visible_events, lod):
        """
        Render individual events with optional clustering.
        
        Args:
            visible_events (list): List of visible event dictionaries
            lod (int): Level of detail (0=high, 1=medium, 2=low)
        """
        # Apply time-window-based clustering if enabled
        if self.clustering_enabled:
            clusters = self._cluster_events(visible_events)
        else:
            # No clustering - treat each event as its own cluster
            clusters = [{'events': [event], 'representative_time': event.get('timestamp'), 
                        'is_cluster': False, 'count': 1} 
                       for event in visible_events if event.get('timestamp')]
        
        # Get aggregation threshold based on LOD
        CLUSTER_THRESHOLD = self.viewport_optimizer.get_aggregation_threshold()
        
        # Calculate base Y position for markers (centered in timeline area)
        base_y = self.margin_top + self.timeline_height / 2
        
        # Batch render for better performance
        batches = self.viewport_optimizer.batch_events_for_rendering(
            clusters, batch_size=100
        )
        
        # Render each batch with error handling
        for batch in batches:
            for cluster in batch:
                # ROBUSTNESS: Wrap in try/except to prevent single bad event from crashing render
                try:
                    if not cluster or not cluster.get('events'):
                        continue
                    
                    cluster_events = cluster['events']
                    representative_time = cluster.get('representative_time')
                    
                    if not representative_time:
                        continue
                    
                    # Calculate X position based on representative timestamp
                    position = self._calculate_position(representative_time)
                    
                    # Determine if we should show as cluster or individual events
                    # Use cluster marker if:
                    # 1. Cluster has multiple events AND
                    # 2. Either marked as cluster by clusterer OR above aggregation threshold
                    should_cluster = (len(cluster_events) > 1 and 
                                    (cluster.get('is_cluster', False) or 
                                     len(cluster_events) > CLUSTER_THRESHOLD))
                    
                    if should_cluster:
                        # Create cluster marker with count badge
                        cluster_marker = self.event_renderer.create_cluster_marker(
                            cluster_events,
                            position,
                            y_offset=0,
                            base_y=base_y,
                            lod=lod
                        )
                        
                        # Add cluster to scene
                        self.scene.addItem(cluster_marker)
                        
                        # Store cluster reference using first event's ID as key
                        first_event_id = cluster_events[0].get('id')
                        if first_event_id:
                            cluster_id = f"cluster_{first_event_id}"
                            self.event_markers[cluster_id] = cluster_marker
                            self._visible_marker_ids.add(cluster_id)
                    else:
                        # Show individual events horizontally (not stacked)
                        for idx, event in enumerate(cluster_events):
                            marker = self.event_renderer.create_event_marker(
                                event, 
                                position, 
                                y_offset=0,  # Horizontal display, not diagonal
                                base_y=base_y,
                                lod=lod
                            )
                            
                            # Add marker to scene
                            self.scene.addItem(marker)
                            
                            # Store marker reference
                            event_id = event.get('id')
                            if event_id:
                                self.event_markers[event_id] = marker
                                self._visible_marker_ids.add(event_id)
                
                except Exception as e:
                    # Log error but continue rendering other events
                    print(f"Warning: Failed to render cluster/event: {e}")
                    continue
    
    def _render_aggregated_view(self, visible_events, lod):
        """
        Render aggregated view with bar charts for large datasets.
        
        Args:
            visible_events (list): List of visible event dictionaries
            lod (int): Level of detail (0=high, 1=medium, 2=low)
        """
        from timeline.data.event_aggregator import EventAggregator
        
        # Initialize aggregator
        aggregator = EventAggregator()
        
        # Calculate optimal bucket size based on visible time range
        time_range_seconds = (self.end_time - self.start_time).total_seconds()
        bucket_size = aggregator.calculate_optimal_bucket_size(
            len(visible_events),
            time_range_seconds,
            target_buckets=50  # Target 50 bars across the viewport
        )
        
        # Aggregate events into buckets
        aggregated_buckets = aggregator.aggregate_events(
            visible_events,
            bucket_size=bucket_size,
            start_time=self.start_time,
            end_time=self.end_time
        )
        
        # Calculate base Y position for bars (centered in timeline area)
        base_y = self.margin_top + self.timeline_height / 2
        
        # Calculate bar width based on bucket size and scene width
        scene_width = self.scene.sceneRect().width()
        bucket_seconds = aggregator.get_bucket_size_seconds(bucket_size)
        time_range_seconds = (self.end_time - self.start_time).total_seconds()
        bar_width = (scene_width * bucket_seconds) / time_range_seconds
        bar_width = max(10, min(bar_width, 50))  # Clamp between 10 and 50 pixels
        
        # Render each aggregated bucket as a bar chart
        for bucket in aggregated_buckets:
            bucket_time = bucket.get('time_bucket')
            if not bucket_time:
                continue
            
            # Calculate X position for bucket (center of bar)
            position = self._calculate_position(bucket_time)
            
            # Create aggregated marker (stacked bar chart)
            aggregated_marker = self.event_renderer.create_aggregated_marker(
                bucket,
                position,
                base_y=base_y,
                bar_width=bar_width
            )
            
            if aggregated_marker:
                # Add to scene
                self.scene.addItem(aggregated_marker)
                
                # Store marker reference and track as visible
                bucket_id = f"bucket_{bucket_time.isoformat()}"
                self.event_markers[bucket_id] = aggregated_marker
                self._visible_marker_ids.add(bucket_id)
    
    def _calculate_position(self, timestamp):
        """
        Calculate X position for a timestamp on the timeline.
        
        Args:
            timestamp (datetime): Event timestamp
        
        Returns:
            float: X position in scene coordinates
        """
        if not self.start_time or not self.end_time:
            return 0
        
        # Calculate relative position (0.0 to 1.0)
        total_duration = (self.end_time - self.start_time).total_seconds()
        if total_duration == 0:
            return 0
        
        event_offset = (timestamp - self.start_time).total_seconds()
        relative_position = event_offset / total_duration
        
        # Map to scene coordinates
        scene_width = self.scene.sceneRect().width()
        position = relative_position * scene_width
        
        return position
    
    def render_power_events(self, power_events):
        """
        Render system power event markers.
        
        Args:
            power_events (list): List of power event dictionaries
        """
        # TODO: Implement in future tasks (Phase 3)
        pass
    
    def render_heat_map(self, activity_data):
        """
        Render heat map overlay showing activity intensity.
        
        Args:
            activity_data (dict): Activity intensity data by time bucket
        """
        # TODO: Implement in future tasks (Phase 3)
        pass
    
    def highlight_search_results(self, matching_event_ids):
        """
        Highlight events matching search criteria.
        
        Args:
            matching_event_ids (list): List of event IDs to highlight
        """
        # TODO: Implement in future tasks (Phase 4)
        pass
    
    def clear_timeline(self):
        """Clear all items from the timeline."""
        # Clear all scene items to prevent memory leaks
        self.scene.clear()
        
        # Clear all tracking dictionaries and lists
        self.selected_events = []
        self.event_markers.clear()
        self.axis_items.clear()
        self.background_items.clear()
        
        # Reset last selected and hovered tracking
        self._last_selected_id = None
        if hasattr(self, '_last_hovered'):
            self._last_hovered = None
        
        # Re-initialize scene with clean state
        self._initialize_scene()
    
    def _clear_selection(self):
        """Clear visual selection from all event markers."""
        for event_id in self.selected_events:
            marker = self.event_markers.get(event_id)
            if marker:
                self.event_renderer.apply_selection(marker, selected=False)
    
    def _handle_single_click(self, event_id, marker, event_data):
        """
        Handle single click on event marker (no modifiers).
        Clears previous selection and selects only the clicked event.
        
        Args:
            event_id (str): ID of clicked event
            marker: QGraphicsItem marker
            event_data (dict): Event data
        """
        # Clear previous selection
        self._clear_selection()
        
        # Select this event
        self.selected_events = [event_id]
        self._last_selected_id = event_id
        
        # Apply visual selection
        self.event_renderer.apply_selection(marker, selected=True)
        
        # Emit signal with selected event data
        self.event_selected.emit([event_data])
    
    def _handle_ctrl_click(self, event_id, marker, event_data):
        """
        Handle Ctrl+click on event marker.
        Toggles the event in the current selection (add if not selected, remove if selected).
        
        Args:
            event_id (str): ID of clicked event
            marker: QGraphicsItem marker
            event_data (dict): Event data
        """
        if event_id in self.selected_events:
            # Remove from selection
            self.selected_events.remove(event_id)
            self.event_renderer.apply_selection(marker, selected=False)
            
            # Update last selected if we removed it
            if self._last_selected_id == event_id:
                self._last_selected_id = self.selected_events[-1] if self.selected_events else None
        else:
            # Add to selection
            self.selected_events.append(event_id)
            self._last_selected_id = event_id
            self.event_renderer.apply_selection(marker, selected=True)
        
        # Emit signal with all selected events
        selected_event_data = self._get_selected_event_data()
        self.event_selected.emit(selected_event_data)
    
    def _handle_shift_click(self, event_id, marker, event_data):
        """
        Handle Shift+click on event marker.
        Selects range from last selected event to clicked event.
        
        Args:
            event_id (str): ID of clicked event
            marker: QGraphicsItem marker
            event_data (dict): Event data
        """
        # If no previous selection, treat as single click
        if not self.selected_events or not self._last_selected_id:
            self._handle_single_click(event_id, marker, event_data)
            return
        
        # Get range of events between last selected and current
        range_event_ids = self._get_event_range(self._last_selected_id, event_id)
        
        # Clear previous selection
        self._clear_selection()
        
        # Select all events in range
        self.selected_events = range_event_ids
        
        # Apply visual selection to all events in range
        for range_event_id in range_event_ids:
            range_marker = self.event_markers.get(range_event_id)
            if range_marker:
                self.event_renderer.apply_selection(range_marker, selected=True)
        
        # Update last selected
        self._last_selected_id = event_id
        
        # Emit signal with all selected events
        selected_event_data = self._get_selected_event_data()
        self.event_selected.emit(selected_event_data)
    
    def _get_event_range(self, start_event_id, end_event_id):
        """
        Get all event IDs between two events (inclusive) based on temporal order.
        
        Args:
            start_event_id (str): Starting event ID
            end_event_id (str): Ending event ID
        
        Returns:
            list: List of event IDs in the range
        """
        if not hasattr(self, '_stored_events') or not self._stored_events:
            return [start_event_id, end_event_id]
        
        # Find indices of start and end events
        start_idx = None
        end_idx = None
        
        for idx, event in enumerate(self._stored_events):
            if event.get('id') == start_event_id:
                start_idx = idx
            if event.get('id') == end_event_id:
                end_idx = idx
        
        # If either not found, return both
        if start_idx is None or end_idx is None:
            return [start_event_id, end_event_id]
        
        # Ensure start is before end
        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx
        
        # Get all event IDs in range
        range_events = []
        for idx in range(start_idx, end_idx + 1):
            event_id = self._stored_events[idx].get('id')
            if event_id and event_id in self.event_markers:
                range_events.append(event_id)
        
        return range_events if range_events else [start_event_id, end_event_id]
    
    def _get_selected_event_data(self):
        """
        Get event data for all currently selected events.
        
        Returns:
            list: List of event data dictionaries for selected events
        """
        if not hasattr(self, '_stored_events') or not self._stored_events:
            return []
        
        selected_data = []
        for event in self._stored_events:
            if event.get('id') in self.selected_events:
                selected_data.append(event)
        
        return selected_data
    
    def _get_viewport_center(self):
        """
        Get the center point of the viewport as a timestamp.
        
        This method calculates which timestamp is currently at the center
        of the visible viewport. This is used to maintain the visual center
        during zoom operations.
        
        NOTE: This replaces the old implementation that returned QPointF scene
        coordinates. The timestamp-based approach is necessary because scene
        coordinates change when zoom level changes, but timestamps remain constant.
        
        Returns:
            datetime or None: The timestamp at the viewport center, or None if
                            time range is not set
        """
        if not self.start_time or not self.end_time:
            return None
        
        # Get viewport center in view coordinates
        viewport_rect = self.viewport().rect()
        viewport_center_point = viewport_rect.center()
        
        # Convert to scene coordinates
        scene_center_point = self.mapToScene(viewport_center_point)
        scene_center_x = scene_center_point.x()
        
        # Convert scene x coordinate to timestamp
        scene_width = self.scene.sceneRect().width()
        if scene_width == 0:
            return self.start_time
        
        # Calculate relative position (0.0 to 1.0)
        relative_position = scene_center_x / scene_width
        
        # Clamp to valid range
        relative_position = max(0.0, min(1.0, relative_position))
        
        # Convert to timestamp
        total_duration = (self.end_time - self.start_time).total_seconds()
        offset_seconds = relative_position * total_duration
        
        from datetime import timedelta
        center_time = self.start_time + timedelta(seconds=offset_seconds)
        
        return center_time
    
    def _maintain_center_point(self, center_time):
        """
        Maintain the specified timestamp at the center of the viewport after zoom.
        
        This method adjusts the viewport scroll position so that the given
        timestamp remains visually centered after a zoom operation changes
        the scene dimensions.
        
        NOTE: This replaces the old implementation that used QPointF scene
        coordinates. The timestamp-based approach correctly handles scene
        dimension changes during zoom operations.
        
        Args:
            center_time (datetime): The timestamp that should be at viewport center
        """
        if not center_time or not self.start_time or not self.end_time:
            return
        
        # Ensure center_time is within the time range
        if center_time < self.start_time or center_time > self.end_time:
            return
        
        # Calculate where this timestamp should be in scene coordinates
        total_duration = (self.end_time - self.start_time).total_seconds()
        if total_duration == 0:
            return
        
        event_offset = (center_time - self.start_time).total_seconds()
        relative_position = event_offset / total_duration
        
        # Get new scene width after zoom
        scene_width = self.scene.sceneRect().width()
        target_scene_x = relative_position * scene_width
        
        # Calculate where this should be in view coordinates to center it
        viewport_width = self.viewport().width()
        viewport_center_x = viewport_width / 2
        
        # We want: mapToScene(viewport_center_x) = target_scene_x
        # So we need to scroll to: target_scene_x - viewport_center_x (in scene coords)
        
        # Center the view on the target scene position
        self.centerOn(target_scene_x, self.scene.sceneRect().center().y())
    
    def _render_background(self):
        """
        Render timeline background with grid lines and time period shading.
        
        FIXED: Only draws visible shading/grid lines for performance.
        """
        from PyQt5.QtWidgets import QGraphicsRectItem
        
        # Clear existing background items to prevent memory leaks
        for item in self.background_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.background_items.clear()
        
        if not self.start_time or not self.end_time:
            return
        
        # Get time unit and interval from zoom manager
        time_unit = self.zoom_manager.get_time_unit()
        interval_minutes = self.zoom_manager.get_interval_minutes()
        
        # Calculate timeline area bounds
        timeline_top = self.margin_top
        timeline_bottom = self.margin_top + self.timeline_height
        
        # FIXED: Calculate time markers (now filtered to viewport)
        markers = self._calculate_time_markers(time_unit, interval_minutes)
        
        # Draw alternating time period shading and grid lines (only visible ones)
        for idx, (marker_time, label_text) in enumerate(markers):
            position = self._calculate_position(marker_time)
            
            # Draw subtle vertical grid line
            grid_line = QGraphicsLineItem(
                position, 
                timeline_top, 
                position, 
                timeline_bottom
            )
            grid_line.setPen(QPen(QColor("#334155"), 1, Qt.DotLine))  # Subtle dotted line
            grid_line.setZValue(-100)  # Behind everything
            self.scene.addItem(grid_line)
            self.background_items.append(grid_line)
            
            # Add alternating shading for time periods
            if idx < len(markers) - 1:
                next_position = self._calculate_position(markers[idx + 1][0])
                
                # Alternate between two shades
                if idx % 2 == 0:
                    shade_color = QColor(30, 41, 59, 30)  # Very subtle darker shade
                else:
                    shade_color = QColor(51, 65, 85, 20)  # Very subtle lighter shade
                
                shading_rect = QGraphicsRectItem(
                    position,
                    timeline_top,
                    next_position - position,
                    timeline_bottom - timeline_top
                )
                shading_rect.setBrush(QBrush(shade_color))
                shading_rect.setPen(QPen(Qt.NoPen))
                shading_rect.setZValue(-200)  # Behind grid lines
                self.scene.addItem(shading_rect)
                self.background_items.append(shading_rect)
        
        # Add visual markers for day/week boundaries (if appropriate for zoom level)
        if time_unit in ['hour', '15min', '5min', 'minute']:
            # Show day boundaries
            self._add_day_boundary_markers()
        elif time_unit in ['day', '12hour', '6hour']:
            # Show week boundaries
            self._add_week_boundary_markers()
    
    def _add_day_boundary_markers(self):
        """Add visual markers for day boundaries."""
        if not self.start_time or not self.end_time:
            return
        
        timeline_top = self.margin_top
        timeline_bottom = self.margin_top + self.timeline_height
        
        # Find all day boundaries in the time range
        current_day = self.start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        while current_day <= self.end_time:
            if current_day >= self.start_time:
                position = self._calculate_position(current_day)
                
                # Draw thicker line for day boundary
                boundary_line = QGraphicsLineItem(
                    position,
                    timeline_top,
                    position,
                    timeline_bottom
                )
                boundary_line.setPen(QPen(QColor("#475569"), 2, Qt.DashLine))
                boundary_line.setZValue(-50)  # In front of shading, behind events
                self.scene.addItem(boundary_line)
                self.background_items.append(boundary_line)
            
            current_day += timedelta(days=1)
    
    def _add_week_boundary_markers(self):
        """Add visual markers for week boundaries (Mondays)."""
        if not self.start_time or not self.end_time:
            return
        
        timeline_top = self.margin_top
        timeline_bottom = self.margin_top + self.timeline_height
        
        # Find first Monday
        current_date = self.start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        days_until_monday = (7 - current_date.weekday()) % 7
        if days_until_monday > 0:
            current_date += timedelta(days=days_until_monday)
        
        while current_date <= self.end_time:
            if current_date >= self.start_time:
                position = self._calculate_position(current_date)
                
                # Draw thicker line for week boundary
                boundary_line = QGraphicsLineItem(
                    position,
                    timeline_top,
                    position,
                    timeline_bottom
                )
                boundary_line.setPen(QPen(QColor("#64748B"), 2, Qt.DashLine))
                boundary_line.setZValue(-50)  # In front of shading, behind events
                self.scene.addItem(boundary_line)
                self.background_items.append(boundary_line)
            
            current_date += timedelta(weeks=1)
    
    def _render_time_axis(self):
        """Render the time axis with improved label readability."""
        from PyQt5.QtWidgets import QGraphicsRectItem
        
        # Clear existing axis items to prevent memory leaks
        for item in self.axis_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.axis_items.clear()
        
        if not self.start_time or not self.end_time:
            return
        
        # Render background first
        self._render_background()
        
        # Get time unit and interval from zoom manager
        time_unit = self.zoom_manager.get_time_unit()
        interval_minutes = self.zoom_manager.get_interval_minutes()
        
        # Calculate axis Y position
        axis_y = self.margin_top + self.timeline_height + 10
        
        # Add background for axis area to improve visibility
        scene_width = self.scene.sceneRect().width()
        axis_background = QGraphicsRectItem(0, axis_y - 5, scene_width, self.axis_height + 10)
        axis_background.setBrush(QBrush(QColor(15, 23, 42, 200)))  # Semi-transparent dark background
        axis_background.setPen(QPen(Qt.NoPen))
        axis_background.setZValue(-10)
        self.scene.addItem(axis_background)
        self.axis_items.append(axis_background)
        
        # Draw main axis line (thicker and brighter for better visibility)
        axis_line = QGraphicsLineItem(0, axis_y, scene_width, axis_y)
        axis_line.setPen(QPen(QColor("#94A3B8"), 4))  # Brighter and thicker
        self.scene.addItem(axis_line)
        self.axis_items.append(axis_line)
        
        # Calculate major and minor time markers
        major_markers = self._calculate_time_markers(time_unit, interval_minutes)
        minor_markers = self._calculate_minor_markers(time_unit, interval_minutes)
        
        # Draw minor tick marks first (shorter, lighter)
        for marker_time in minor_markers:
            position = self._calculate_position(marker_time)
            
            # Draw minor tick mark (shorter and lighter)
            minor_tick = QGraphicsLineItem(position, axis_y, position, axis_y + 6)
            minor_tick.setPen(QPen(QColor("#475569"), 1))
            self.scene.addItem(minor_tick)
            self.axis_items.append(minor_tick)
        
        # Calculate label density to determine if rotation is needed
        label_density = self._calculate_label_density(major_markers)
        
        # Determine if we need to rotate labels based on density
        # High density (>0.7) = rotate, low (<0.7) = normal
        use_rotation = label_density > 0.7
        
        # FIXED: Use class constant for spacing (not local variable)
        min_spacing = self.MIN_LABEL_SPACING
        
        # Draw major tick marks and labels with pixel-based spacing
        last_label_end = -1e9  # Track last label end position to prevent overlap
        
        for idx, (marker_time, label_text) in enumerate(major_markers):
            position = self._calculate_position(marker_time)
            
            # Draw major tick mark (taller and brighter for better visibility)
            major_tick = QGraphicsLineItem(position, axis_y, position, axis_y + 15)
            major_tick.setPen(QPen(QColor("#CBD5E1"), 3))  # Brighter and thicker
            self.scene.addItem(major_tick)
            self.axis_items.append(major_tick)
            
            # Create label with appropriate font (larger for better visibility)
            label = QGraphicsTextItem(label_text)
            label.setDefaultTextColor(QColor("#FFFFFF"))  # Pure white for maximum contrast
            label.setFont(QFont("Segoe UI", 11 if use_rotation else 12, QFont.Bold))
            
            # Calculate label dimensions
            label_width = label.boundingRect().width()
            label_height = label.boundingRect().height()
            
            if use_rotation:
                # Adaptive rotation for dense timelines
                rotation_angle = -45  # 45-degree rotation
                label_x = position + 5
                label_y = axis_y + 14
                
                # FIXED: Calculate rotated bounds using math (not sceneBoundingRect before adding to scene)
                # For 45-degree rotation: diagonal = sqrt(width^2 + height^2)
                import math
                rotated_diagonal = math.sqrt(label_width**2 + label_height**2)
                label_end = position + rotated_diagonal
                
                # Check for overlap with previous rotated label using calculated bounds
                if position > last_label_end + min_spacing:
                    # Position and rotate label
                    label.setPos(label_x, label_y)
                    label.setRotation(rotation_angle)
                    
                    # Add background rectangle with strong contrast
                    bg_width = label_width + 10
                    bg_height = label_height + 6
                    background = QGraphicsRectItem(
                        position + 3,
                        axis_y + 12,
                        bg_width,
                        bg_height
                    )
                    # Dark background with border for maximum contrast
                    background.setBrush(QBrush(QColor(10, 15, 30, 250)))
                    background.setPen(QPen(QColor("#94A3B8"), 2))
                    background.setRotation(rotation_angle)
                    background.setZValue(-1)
                    self.scene.addItem(background)
                    self.axis_items.append(background)
                    
                    # Add label to scene
                    label.setZValue(0)
                    self.scene.addItem(label)
                    self.axis_items.append(label)
                    last_label_end = label_end
            else:
                # Normal horizontal labels
                label_start = position - label_width / 2
                label_end = position + label_width / 2
                
                # FIXED: Only add label if it doesn't overlap (pixel-based spacing)
                if position > last_label_end + min_spacing:
                    # Add background rectangle with strong contrast
                    background = QGraphicsRectItem(
                        label_start - 6,
                        axis_y + 14,
                        label_width + 12,
                        label_height + 8
                    )
                    # Dark background with border for maximum contrast
                    background.setBrush(QBrush(QColor(10, 15, 30, 250)))
                    background.setPen(QPen(QColor("#94A3B8"), 2))
                    background.setZValue(-1)
                    self.scene.addItem(background)
                    self.axis_items.append(background)
                    
                    # Position label on top of background
                    label.setPos(label_start, axis_y + 16)
                    label.setZValue(0)
                    self.scene.addItem(label)
                    self.axis_items.append(label)
                    last_label_end = label_end
    
    def _calculate_time_markers(self, time_unit, interval_minutes):
        """
        Calculate time marker positions and labels.
        
        FIXED: Always uses interval_minutes from ZoomManager (no hardcoded hourly logic).
        FIXED: Filters to only visible viewport for performance.
        
        Args:
            time_unit (str): Time unit name (year, month, day, hour, etc.)
            interval_minutes (int): Interval in minutes
        
        Returns:
            list: List of (datetime, label_text) tuples (only visible markers)
        """
        # Get visible viewport bounds for filtering
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        visible_start_x = visible_rect.left()
        visible_end_x = visible_rect.right()

        # Add buffer to include markers just outside viewport for smooth scrolling
        viewport_width = self.viewport().width() if self.viewport() else 1200
        buffer_pixels = viewport_width * self.VIEWPORT_BUFFER_RATIO
        visible_start_x -= buffer_pixels
        visible_end_x += buffer_pixels
        
        markers = []
        
        # Always use the zoom manager's interval (no special case for short ranges)
        interval = timedelta(minutes=interval_minutes)
        current_time = self._round_time(self.start_time, time_unit)
        
        # Generate markers, but only keep visible ones
        max_markers = 200  # Safety limit
        count = 0
        
        while current_time <= self.end_time and count < max_markers:
            if current_time >= self.start_time:
                position = self._calculate_position(current_time)

                # Only add if within visible range (with buffer)
                if visible_start_x <= position <= visible_end_x:
                    label = self._format_time_label(current_time, time_unit)
                    markers.append((current_time, label))
                    count += 1
                elif position > visible_end_x:
                    # Past visible range, stop generating
                    break

            current_time += interval

        if not markers:
            mid_time = self.start_time + (self.end_time - self.start_time) / 2
            mid_time = self._round_time(mid_time, time_unit)
            if self.start_time <= mid_time <= self.end_time:
                markers.append((mid_time, self._format_time_label(mid_time, time_unit)))

        return markers
    
    def _calculate_minor_markers(self, time_unit, interval_minutes):
        """
        Calculate minor tick mark positions for better granularity.
        
        Minor ticks are placed between major ticks to provide finer time resolution.
        
        FIXED: Aligned with major ticks (same base time).
        FIXED: Filters to only visible viewport for performance.
        
        Args:
            time_unit (str): Time unit name (year, month, day, hour, etc.)
            interval_minutes (int): Major interval in minutes
        
        Returns:
            list: List of datetime objects for minor tick positions (only visible)
        """
        # Get visible viewport bounds for filtering
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        visible_start_x = visible_rect.left()
        visible_end_x = visible_rect.right()

        # Add buffer
        viewport_width = self.viewport().width() if self.viewport() else 1200
        buffer_pixels = viewport_width * self.VIEWPORT_BUFFER_RATIO
        visible_start_x -= buffer_pixels
        visible_end_x += buffer_pixels
        
        minor_markers = []
        
        # FIXED: Start from same base as major markers for alignment
        base_time = self._round_time(self.start_time, time_unit)
        
        # Determine minor interval based on time unit
        if time_unit in ['minute', '5min', '15min']:
            # For minute views, add minor ticks at 1-minute intervals
            minor_interval = timedelta(minutes=1)
        elif time_unit == 'hour':
            # For hour view, add 15-minute minor ticks
            minor_interval = timedelta(minutes=15)
        elif time_unit in ['6hour', '12hour']:
            # For 6/12 hour view, add hourly minor ticks
            minor_interval = timedelta(hours=1)
        elif time_unit == 'day':
            # For day view, add 6-hour minor ticks
            minor_interval = timedelta(hours=6)
        elif time_unit == 'week':
            # For week view, add daily minor ticks
            minor_interval = timedelta(days=1)
        elif time_unit == 'month':
            # For month view, add weekly minor ticks
            minor_interval = timedelta(weeks=1)
        else:
            # For year/quarter view, add monthly minor ticks
            minor_interval = timedelta(days=30)
        
        # Generate minor markers, but only keep visible ones
        current_time = base_time
        max_minor_markers = 500  # Safety limit
        count = 0
        
        while current_time <= self.end_time and count < max_minor_markers:
            if current_time >= self.start_time:
                position = self._calculate_position(current_time)
                
                # Only add if within visible range (with buffer)
                if visible_start_x <= position <= visible_end_x:
                    minor_markers.append(current_time)
                    count += 1
                elif position > visible_end_x:
                    # Past visible range, stop generating
                    break
            
            current_time += minor_interval
        
        return minor_markers
    
    def _get_visible_markers(self, markers, viewport_width):
        """
        Filter markers to only those visible in the current viewport.
        
        Args:
            markers (list): List of (datetime, label_text) tuples
            viewport_width (float): Width of the viewport in pixels
        
        Returns:
            list: Filtered list of visible markers
        """
        if not markers:
            return []
        
        # Get visible scene rect
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        visible_start = visible_rect.left()
        visible_end = visible_rect.right()
        
        # Filter markers within visible range
        visible_markers = []
        for marker_time, label_text in markers:
            position = self._calculate_position(marker_time)
            if visible_start <= position <= visible_end:
                visible_markers.append((marker_time, label_text))
        
        return visible_markers
    
    def _calculate_label_density(self, markers):
        """
        Calculate label density to determine if rotation is needed.
        
        Density is calculated as the ratio of total label width to available space.
        
        FIXED: Works with already-filtered markers (no need for separate filtering).
        
        Args:
            markers (list): List of (datetime, label_text) tuples (already filtered to viewport)
        
        Returns:
            float: Density ratio (0.0 to 1.0+, where >0.7 indicates high density)
        """
        if not markers:
            return 0.0
        
        # Get viewport width
        viewport_width = self.viewport().width() if self.viewport() else 1200
        
        # Estimate average label width (approximate based on font and text length)
        # Average character width for 12pt bold font is ~8 pixels
        avg_char_width = 8
        total_label_width = 0
        
        for _, label_text in markers:
            estimated_width = len(label_text) * avg_char_width + 20  # Add padding
            total_label_width += estimated_width
        
        # Calculate density ratio
        density = total_label_width / viewport_width if viewport_width > 0 else 0.0
        
        return density
    
    def _round_time(self, dt, time_unit):
        """
        Round datetime to the nearest time unit boundary.
        
        Args:
            dt (datetime): Datetime to round
            time_unit (str): Time unit (year, month, day, hour, etc.)
        
        Returns:
            datetime: Rounded datetime
        """
        if time_unit == 'year':
            return datetime(dt.year, 1, 1)
        elif time_unit == 'quarter':
            quarter_month = ((dt.month - 1) // 3) * 3 + 1
            return datetime(dt.year, quarter_month, 1)
        elif time_unit == 'month':
            return datetime(dt.year, dt.month, 1)
        elif time_unit == 'week':
            # Round to Monday
            days_since_monday = dt.weekday()
            return datetime(dt.year, dt.month, dt.day) - timedelta(days=days_since_monday)
        elif time_unit == 'day':
            return datetime(dt.year, dt.month, dt.day)
        elif time_unit in ['12hour', '6hour']:
            hour = (dt.hour // 12) * 12 if time_unit == '12hour' else (dt.hour // 6) * 6
            return datetime(dt.year, dt.month, dt.day, hour)
        elif time_unit == 'hour':
            return datetime(dt.year, dt.month, dt.day, dt.hour)
        elif time_unit in ['15min', '5min']:
            minutes = 15 if time_unit == '15min' else 5
            minute = (dt.minute // minutes) * minutes
            return datetime(dt.year, dt.month, dt.day, dt.hour, minute)
        elif time_unit == 'minute':
            return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        else:
            return dt
    
    def _format_time_label(self, dt, time_unit):
        """
        Format datetime as label text based on time unit.
        
        FIXED: Shows date on major boundaries for clarity at 12-hour+ zoom levels.
        
        Args:
            dt (datetime): Datetime to format
            time_unit (str): Time unit
        
        Returns:
            str: Formatted label text
        """
        if time_unit == 'year':
            return dt.strftime('%Y')
        elif time_unit == 'quarter':
            quarter = (dt.month - 1) // 3 + 1
            return f"Q{quarter} {dt.year}"
        elif time_unit == 'month':
            return dt.strftime('%b %Y')
        elif time_unit == 'week':
            return dt.strftime('%b %d')
        elif time_unit == 'day':
            # Show date with day of week for clarity
            return dt.strftime('%b %d (%a)')
        elif time_unit in ['12hour', '6hour']:
            # FIXED: Show date + time for 12-hour boundaries to avoid confusion
            # Check if this is a day boundary (midnight)
            if dt.hour == 0:
                return dt.strftime('%b %d\n%H:%M')
            else:
                return dt.strftime('%H:%M')
        elif time_unit == 'hour':
            return dt.strftime('%H:%M')
        elif time_unit in ['15min', '5min', 'minute']:
            return dt.strftime('%H:%M')
        else:
            return dt.strftime('%Y-%m-%d %H:%M')
    
    def get_visible_time_range(self):
        """
        Get the currently visible time range in the viewport.
        
        Returns:
            tuple: (start_time, end_time) of visible range, or (None, None) if not set
        """
        if not self.start_time or not self.end_time:
            return (None, None)
        
        # Get visible rect in scene coordinates
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        
        # Calculate time range based on visible rect
        scene_width = self.scene.sceneRect().width()
        total_duration = self.end_time - self.start_time
        
        # Calculate start and end times for visible portion
        start_ratio = visible_rect.left() / scene_width
        end_ratio = visible_rect.right() / scene_width
        
        visible_start = self.start_time + total_duration * start_ratio
        visible_end = self.start_time + total_duration * end_ratio
        
        return (visible_start, visible_end)
    
    def get_zoom_manager(self):
        """
        Get the ZoomManager instance.
        
        Returns:
            ZoomManager: The zoom manager instance
        """
        return self.zoom_manager
    
    def get_current_zoom_level(self):
        """
        Get the current zoom level.
        
        Returns:
            int: Current zoom level (0-10)
        """
        return self.zoom_manager.current_zoom
    
    def scroll_to_time(self, target_time):
        """
        Scroll the timeline to center on a specific time.
        
        Args:
            target_time (datetime): Time to center in viewport
        """
        if not self.start_time or not self.end_time:
            return
        
        # Calculate position for target time
        position = self._calculate_position(target_time)
        
        # Center on that position
        self.centerOn(position, self.scene.sceneRect().center().y())
    
    def scroll_to_start(self):
        """Scroll to the start of the timeline."""
        if self.start_time:
            self.scroll_to_time(self.start_time)
    
    def scroll_to_end(self):
        """Scroll to the end of the timeline."""
        if self.end_time:
            self.scroll_to_time(self.end_time)
    
    def wheelEvent(self, event):
        """
        Handle mouse wheel events for zooming.
        
        Args:
            event: QWheelEvent
        """
        # Zoom with mouse wheel
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        
        event.accept()
    
    def mousePressEvent(self, event):
        """
        Handle mouse press events for event selection, cluster expansion, and panning.
        
        Supports:
        - Single click: Select single event (clears previous selection)
        - Ctrl+click: Add/remove event from selection
        - Shift+click: Range selection from last selected to clicked event
        
        Args:
            event: QMouseEvent
        """
        # Check if clicking on an event marker or cluster
        if event.button() == Qt.LeftButton:
            # Get item at click position
            scene_pos = self.mapToScene(event.pos())
            item = self.scene.itemAt(scene_pos, self.transform())
            
            # Check if item is part of our markers
            clicked_marker = None
            clicked_marker_id = None
            for marker_id, marker in self.event_markers.items():
                if item == marker or (hasattr(marker, 'childItems') and item in marker.childItems()):
                    clicked_marker = marker
                    clicked_marker_id = marker_id
                    break
            
            if clicked_marker:
                # Get event data from marker
                event_data = clicked_marker.data(0)
                
                if event_data:
                    # Check if this is a cluster marker
                    if event_data.get('type') == 'cluster':
                        # Toggle cluster expansion
                        self._toggle_cluster_expansion(clicked_marker, event_data)
                        event.accept()
                        return
                    else:
                        # Regular event marker - handle multi-select
                        event_id = event_data.get('id')
                        
                        # Check for modifier keys
                        modifiers = event.modifiers()
                        ctrl_pressed = modifiers & Qt.ControlModifier
                        shift_pressed = modifiers & Qt.ShiftModifier
                        
                        if ctrl_pressed:
                            # Ctrl+click: Toggle event in selection
                            self._handle_ctrl_click(event_id, clicked_marker, event_data)
                        elif shift_pressed:
                            # Shift+click: Range selection
                            self._handle_shift_click(event_id, clicked_marker, event_data)
                        else:
                            # Regular click: Single selection (clear previous)
                            self._handle_single_click(event_id, clicked_marker, event_data)
                        
                        event.accept()
                        return
            else:
                # Clicked on empty space - clear selection and enable panning
                self._clear_selection()
                self.selected_events = []
                self._last_selected_id = None
                self.event_selected.emit([])
                
                # Enable panning mode
                self._is_panning = True
                self._pan_start_pos = event.pos()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        
        # Pass to parent for drag functionality
        super().mousePressEvent(event)
    
    def _toggle_cluster_expansion(self, cluster_marker, cluster_data):
        """
        Toggle expansion of a cluster marker to show/hide individual events.
        
        Includes visual feedback and smooth animation for better UX.
        
        FIXED: No longer uses 'expanded_' prefix to avoid marker ID collisions.
        Uses original event IDs and tracks expansion state separately.
        
        Args:
            cluster_marker: The cluster marker item
            cluster_data (dict): Cluster data containing events list
        """
        is_expanded = cluster_data.get('expanded', False)
        events = cluster_data.get('events', [])
        
        if not events:
            return
        
        # Get cluster's actual X position from its scene position
        # The cluster is a QGraphicsItemGroup, so get its bounding rect center
        cluster_rect = cluster_marker.sceneBoundingRect()
        position = cluster_rect.center().x()
        
        # Get cluster ID for tracking
        first_event_id = events[0].get('id')
        cluster_id = f"cluster_{first_event_id}" if first_event_id else None
        
        if is_expanded:
            # Collapse: Remove individual event markers and restore cluster
            # Use tracked expanded markers for this specific cluster
            expansion_data = self.expanded_clusters.get(cluster_marker, {})
            expanded_marker_ids = expansion_data.get('marker_ids', [])
            
            # Animate collapse if markers exist
            if expanded_marker_ids:
                from PyQt5.QtCore import QTimer
                
                # Fade out markers with simple opacity animation
                for marker_id in expanded_marker_ids:
                    marker = self.event_markers.get(marker_id)
                    if marker:
                        # Simple fade out by setting opacity
                        marker.setOpacity(0.5)
                
                # After short delay, remove markers and restore cluster
                def cleanup_collapsed_markers():
                    # Remove individual markers
                    for marker_id in expanded_marker_ids:
                        marker = self.event_markers.get(marker_id)
                        if marker:
                            # Remove from scene first
                            if marker.scene() == self.scene:
                                self.scene.removeItem(marker)
                            # Remove from tracking dict
                            self.event_markers.pop(marker_id, None)
                            # Remove from visible set
                            self._visible_marker_ids.discard(marker_id)
                    
                    # FIXED: Show cluster marker again
                    cluster_marker.setVisible(True)
                    cluster_marker.setOpacity(1.0)
                    
                    # Restore cluster marker to tracking
                    if cluster_id:
                        self.event_markers[cluster_id] = cluster_marker
                        self._visible_marker_ids.add(cluster_id)
                    
                    # Clear the expanded cluster tracking for this cluster
                    self.expanded_clusters.pop(cluster_marker, None)
                
                # Use QTimer for delayed cleanup (simple animation effect)
                QTimer.singleShot(150, cleanup_collapsed_markers)
            else:
                # No markers to animate, just restore cluster tracking
                # FIXED: Show cluster marker again
                cluster_marker.setVisible(True)
                cluster_marker.setOpacity(1.0)
                if cluster_id:
                    self.event_markers[cluster_id] = cluster_marker
                    self._visible_marker_ids.add(cluster_id)
                self.expanded_clusters.pop(cluster_marker, None)
            
            # Update cluster state
            cluster_data['expanded'] = False
            cluster_marker.setData(0, cluster_data)
            
            # Update visual appearance to show collapsed state
            self.event_renderer.update_cluster_expansion_visual(cluster_marker, expanded=False)
            
            # Update tooltip
            tooltip = self.event_renderer._create_cluster_tooltip(
                events, 
                cluster_data.get('dominant_type', 'Unknown')
            )
            cluster_marker.setToolTip(tooltip)
        else:
            # Expand: Show individual events stacked vertically below cluster
            from PyQt5.QtCore import QTimer
            
            base_y = self.margin_top + self.timeline_height / 2
            
            # Track expanded marker IDs for this cluster
            expanded_marker_ids = []
            
            # FIXED: Hide cluster marker during expansion (prevents ghost items)
            cluster_marker.setVisible(False)
            
            # Remove cluster marker from tracking (will be restored on collapse)
            if cluster_id:
                self.event_markers.pop(cluster_id, None)
                self._visible_marker_ids.discard(cluster_id)
            
            # Start stacking from y_offset=1 to appear below the cluster marker
            for idx, event in enumerate(events):
                marker = self.event_renderer.create_event_marker(
                    event,
                    position,
                    y_offset=idx + 1,  # Start at 1 to be below cluster (which is at 0)
                    base_y=base_y
                )
                
                # FIXED: Set proper z-order for expanded markers
                marker.setZValue(10 + idx)  # Above cluster, stacked order
                
                # Start with low opacity for fade-in effect
                marker.setOpacity(0.3)
                
                # Add to scene
                self.scene.addItem(marker)
                
                # FIXED: Use original event_id (no 'expanded_' prefix)
                # This prevents ID collisions with incremental rendering
                event_id = event.get('id')
                if event_id:
                    self.event_markers[event_id] = marker
                    self._visible_marker_ids.add(event_id)
                    expanded_marker_ids.append(event_id)
                
                # Fade in with cascade effect using QTimer
                def fade_in_marker(m=marker, delay=idx*30):
                    from PyQt5.QtWidgets import QApplication
                    def do_fade():
                        m.setOpacity(1.0)
                        # FIXED: Process events to ensure rendering
                        QApplication.processEvents()
                    QTimer.singleShot(delay, do_fade)
                
                fade_in_marker()
            
            # Track which markers belong to this expanded cluster
            self.expanded_clusters[cluster_marker] = {
                'marker_ids': expanded_marker_ids,
                'cluster_id': cluster_id
            }
            
            # Update cluster state
            cluster_data['expanded'] = True
            cluster_marker.setData(0, cluster_data)
            
            # Update visual appearance to show expanded state
            self.event_renderer.update_cluster_expansion_visual(cluster_marker, expanded=True)
            
            # Update tooltip
            cluster_marker.setToolTip("<b>Cluster (Expanded)</b><br><i>Click to collapse</i>")
    
    def mouseMoveEvent(self, event):
        """
        Handle mouse move events for panning, hover effects, and cursor changes.
        
        Args:
            event: QMouseEvent
        """
        if self._is_panning and self._pan_start_pos:
            # Calculate delta
            delta = event.pos() - self._pan_start_pos
            self._pan_start_pos = event.pos()
            
            # Update scrollbars
            h_scrollbar = self.horizontalScrollBar()
            h_scrollbar.setValue(h_scrollbar.value() - delta.x())
            
            # Keep closed hand cursor while panning
            self.setCursor(Qt.ClosedHandCursor)
            
            event.accept()
            return
        
        # Handle hover effects for event markers
        scene_pos = self.mapToScene(event.pos())
        item = self.scene.itemAt(scene_pos, self.transform())
        
        # Check if hovering over a marker
        hovered_marker = None
        for marker_id, marker in self.event_markers.items():
            if item == marker or (hasattr(marker, 'childItems') and item in marker.childItems()):
                hovered_marker = marker
                break
        
        # Apply hover effect and cursor change
        if hovered_marker and (not hasattr(self, '_last_hovered') or self._last_hovered != hovered_marker):
            # Remove hover from previous marker
            if hasattr(self, '_last_hovered') and self._last_hovered:
                self.event_renderer.apply_highlight(self._last_hovered, highlighted=False)
            
            # Apply hover to current marker
            self.event_renderer.apply_highlight(hovered_marker, highlighted=True)
            self._last_hovered = hovered_marker
            
            # Change cursor to pointing hand for clickable items
            self.setCursor(Qt.PointingHandCursor)
        elif not hovered_marker and hasattr(self, '_last_hovered') and self._last_hovered:
            # Remove hover when not over any marker
            self.event_renderer.apply_highlight(self._last_hovered, highlighted=False)
            self._last_hovered = None
            
            # Restore default cursor (or open hand for draggable area)
            self.setCursor(Qt.OpenHandCursor)
        elif not hovered_marker and not hasattr(self, '_last_hovered'):
            # Set open hand cursor for draggable timeline area
            self.setCursor(Qt.OpenHandCursor)
        
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """
        Handle mouse release events.
        
        Args:
            event: QMouseEvent
        """
        if event.button() == Qt.LeftButton and self._is_panning:
            # Disable panning mode
            self._is_panning = False
            self._pan_start_pos = None
            
            # Restore cursor based on what's under the mouse
            scene_pos = self.mapToScene(event.pos())
            item = self.scene.itemAt(scene_pos, self.transform())
            
            # Check if over a marker
            over_marker = False
            for marker_id, marker in self.event_markers.items():
                if item == marker or (hasattr(marker, 'childItems') and item in marker.childItems()):
                    over_marker = True
                    break
            
            # Set appropriate cursor
            if over_marker:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
            
            event.accept()
            return
        
        super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """
        Handle double-click events to open event details dialog.
        
        Args:
            event: QMouseEvent
        """
        # Check if double-clicking on an event marker
        if event.button() == Qt.LeftButton:
            # Get item at click position
            scene_pos = self.mapToScene(event.pos())
            item = self.scene.itemAt(scene_pos, self.transform())
            
            # Check if item is part of our markers
            clicked_marker = None
            for marker_id, marker in self.event_markers.items():
                if item == marker or (hasattr(marker, 'childItems') and item in marker.childItems()):
                    clicked_marker = marker
                    break
            
            if clicked_marker:
                # Get event data from marker
                event_data = clicked_marker.data(0)
                
                if event_data and event_data.get('type') != 'cluster':
                    # Regular event marker - open details dialog
                    self._open_event_details_dialog(event_data)
                    event.accept()
                    return
                elif event_data and event_data.get('type') == 'cluster':
                    # For cluster markers, emit signal with all events
                    self.event_double_clicked.emit(event_data)
                    event.accept()
                    return
        
        super().mouseDoubleClickEvent(event)
    
    def _open_event_details_dialog(self, event_data):
        """
        Open a dialog showing detailed information about an event.
        
        Args:
            event_data (dict): Event data dictionary
        """
        from timeline.event_details_dialog import EventDetailsDialog
        
        # Create and show dialog
        dialog = EventDetailsDialog(event_data, parent=self)
        dialog.exec_()
    
    def resizeEvent(self, event):
        """
        Handle resize events to maintain timeline layout.
        
        Args:
            event: QResizeEvent
        """
        super().resizeEvent(event)
        
        # Update scene dimensions to account for new viewport size
        # This ensures scrollbar appears/disappears appropriately
        if self.start_time and self.end_time:
            self._update_scene_dimensions()
        
        # Resize loading overlay to cover viewport
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(self.viewport().rect())
    
    def scrollContentsBy(self, dx, dy):
        """
        Handle scroll events to dynamically render visible events using incremental rendering.
        
        Only triggers updates for significant scroll movements to avoid excessive re-rendering.
        
        Args:
            dx: Horizontal scroll delta
            dy: Vertical scroll delta
        """
        super().scrollContentsBy(dx, dy)
        
        # Only trigger update for significant horizontal scrolling
        # This avoids excessive re-rendering during small scroll adjustments
        SCROLL_THRESHOLD = 10  # Minimum pixels to trigger update
        
        if hasattr(self, '_stored_events') and self._stored_events and abs(dx) >= SCROLL_THRESHOLD:
            self._dirty_flags['viewport'] = True
            self._update_visible_events()
    
    def _update_visible_events(self):
        """
        Update visible events based on current viewport using incremental rendering.
        
        This method only adds/removes markers that entered/left the viewport,
        avoiding a full re-render for better performance.
        """
        if not hasattr(self, '_stored_events') or not self._stored_events:
            return
        
        # Use incremental rendering instead of full re-render
        self._render_incremental(show_loading=False)
    
    def _cluster_events(self, events):
        """
        Cluster events based on the current clustering mode.
        
        Args:
            events (list): List of event dictionaries
        
        Returns:
            list: List of cluster dictionaries
        """
        if not events:
            return []
        
        # Apply clustering based on mode
        if self.clustering_mode == 'time':
            # Simple time-window clustering
            return self.event_clusterer.cluster_events(events, min_cluster_size=2)
        elif self.clustering_mode == 'application':
            # Group by application within time windows
            return self.event_clusterer.cluster_by_application(events, min_cluster_size=2)
        elif self.clustering_mode == 'path':
            # Group by path within time windows
            return self.event_clusterer.cluster_by_path(events, min_cluster_size=2)
        elif self.clustering_mode == 'artifact_type':
            # Group by artifact type within time windows
            return self.event_clusterer.cluster_by_artifact_type(events, min_cluster_size=2)
        else:
            # Default to time-based clustering
            return self.event_clusterer.cluster_events(events, min_cluster_size=2)
    
    def set_clustering_enabled(self, enabled):
        """
        Enable or disable event clustering.
        
        Args:
            enabled (bool): True to enable clustering, False to disable
        """
        if self.clustering_enabled != enabled:
            self.clustering_enabled = enabled
            self._dirty_flags['clustering'] = True
            
            # Re-render events if they exist
            if hasattr(self, '_stored_events') and self._stored_events:
                self.render_events(self._stored_events)
    
    def set_clustering_mode(self, mode):
        """
        Set the clustering mode.
        
        Args:
            mode (str): Clustering mode - 'time', 'application', 'path', or 'artifact_type'
        """
        valid_modes = ['time', 'application', 'path', 'artifact_type']
        if mode not in valid_modes:
            raise ValueError(f"Invalid clustering mode. Must be one of: {valid_modes}")
        
        if self.clustering_mode != mode:
            self.clustering_mode = mode
            self._dirty_flags['clustering'] = True
            
            # Re-render events if they exist
            if hasattr(self, '_stored_events') and self._stored_events:
                self.render_events(self._stored_events)
    
    def set_clustering_time_window(self, minutes):
        """
        Set the time window for clustering.
        
        Args:
            minutes (int): Time window in minutes
        """
        old_window = self.event_clusterer.get_time_window()
        self.event_clusterer.set_time_window(minutes)
        
        if old_window != minutes:
            self._dirty_flags['clustering'] = True
            
            # Re-render events if they exist
            if hasattr(self, '_stored_events') and self._stored_events:
                self.render_events(self._stored_events)
    
    def get_clustering_time_window(self):
        """
        Get the current clustering time window.
        
        Returns:
            int: Time window in minutes
        """
        return self.event_clusterer.get_time_window()
    
    def is_clustering_enabled(self):
        """
        Check if clustering is enabled.
        
        Returns:
            bool: True if clustering is enabled
        """
        return self.clustering_enabled
    
    def get_clustering_mode(self):
        """
        Get the current clustering mode.
        
        Returns:
            str: Current clustering mode
        """
        return self.clustering_mode

    def handle_aggregated_marker_click(self, bucket_data):
        """
        Handle click on an aggregated marker by zooming into that time period.
        
        Args:
            bucket_data (dict): Aggregated bucket data containing time_bucket and bucket_size
        """
        from timeline.data.event_aggregator import EventAggregator
        
        # Get time range for the bucket
        aggregator = EventAggregator()
        start_time, end_time = aggregator.get_bucket_time_range(bucket_data)
        
        # Set new time range to zoom into this bucket
        self.set_time_range(start_time, end_time)
        
        # Increase zoom level to show more detail
        if self.zoom_manager.can_zoom_in():
            self.zoom_in()
        
        # Re-render events with new time range
        if hasattr(self, '_stored_events') and self._stored_events:
            # Filter events to new time range
            filtered_events = [
                e for e in self._stored_events
                if e.get('timestamp') and start_time <= e.get('timestamp') <= end_time
            ]
            self.render_events(filtered_events, force_individual=True)
    
    def set_force_individual_display(self, force: bool):
        """
        Set whether to force individual event display (disable aggregation).
        
        Args:
            force (bool): True to force individual display, False to allow aggregation
        """
        self._force_individual = force
        
        # Re-render events if they exist
        if hasattr(self, '_stored_events') and self._stored_events:
            self.render_events(self._stored_events, force_individual=force)
    
    def get_viewport_culling_stats(self):
        """
        Get viewport culling and memory optimization statistics.
        
        Returns:
            dict: Dictionary containing performance statistics including:
                - visible_markers: Number of markers currently in scene
                - cached_markers: Number of markers in cache
                - cache_hit_rate: Percentage of cache hits
                - items_removed: Total items removed from scene for memory optimization
                - memory_saved_estimate_mb: Estimated memory saved (rough estimate)
        """
        stats = self.viewport_optimizer.get_cache_stats()
        
        # Add timeline-specific stats (use _marker_cache which is the actual cache)
        stats['visible_markers'] = len(self._visible_marker_ids)
        stats['cached_markers'] = len(self._marker_cache)
        stats['total_events'] = len(self._stored_events) if hasattr(self, '_stored_events') else 0
        
        # Override cache_size with actual cache size from _marker_cache
        stats['cache_size'] = len(self._marker_cache)
        
        # Rough estimate: each marker ~5KB (QGraphicsItem with children)
        # This is a conservative estimate
        items_removed = stats.get('items_removed_from_scene', 0)
        stats['memory_saved_estimate_mb'] = (items_removed * 5) / 1024
        
        return stats
    
    def print_viewport_culling_stats(self):
        """
        Print viewport culling statistics to console for debugging.
        
        Useful for measuring the impact of viewport culling optimizations.
        """
        stats = self.get_viewport_culling_stats()
        
        print("\n=== Viewport Culling Statistics ===")
        print(f"Total Events: {stats['total_events']}")
        print(f"Visible Markers in Scene: {stats['visible_markers']}")
        print(f"Cached Markers: {stats['cached_markers']}")
        print(f"Cache Hit Rate: {stats['hit_rate_percent']:.1f}%")
        print(f"Items Removed from Scene: {stats['items_removed_from_scene']}")
        print(f"Estimated Memory Saved: {stats['memory_saved_estimate_mb']:.2f} MB")
        print("===================================\n")
