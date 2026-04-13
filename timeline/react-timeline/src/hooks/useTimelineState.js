/**
 * useTimelineState — Global timeline state management hook.
 * 
 * Manages: zoom level, visible time range, active filters, 
 * selected event, view mode, lane heights.
 */
import { useState, useCallback, useMemo } from 'react';

/** Zoom level definitions */
const ZOOM_LEVELS = [
  { label: 'Year',      pxPerHour: 0.5 },
  { label: '6 Months',  pxPerHour: 1 },
  { label: '3 Months',  pxPerHour: 2 },
  { label: 'Month',     pxPerHour: 4 },
  { label: '2 Weeks',   pxPerHour: 10 },
  { label: 'Week',      pxPerHour: 25 },
  { label: '3 Days',    pxPerHour: 60 },
  { label: 'Day',       pxPerHour: 150 },
  { label: '12 Hours',  pxPerHour: 300 },
  { label: '6 Hours',   pxPerHour: 600 },
  { label: 'Hour',      pxPerHour: 1200 },
  { label: '15 Mins',   pxPerHour: 3600 },
  { label: '5 Mins',    pxPerHour: 8000 },
  { label: '1 Min',     pxPerHour: 24000 },
  { label: '30 Secs',   pxPerHour: 48000 },
  { label: '10 Secs',   pxPerHour: 144000 },
  { label: '1 Sec',     pxPerHour: 1440000 },
  { label: '100 ms',    pxPerHour: 14400000 },
];

/** Default artifact types (all enabled) */
const DEFAULT_ARTIFACTS = {
  sessions: true,
  srum_app: true,
  srum_net: true,
  mft_usn: true,
  prefetch: true,
  lnk: true,
  bam: true,
  registry: true,
  amcache: true,
  shimcache: true,
  recyclebin: true,
};

/** Default lane heights */
const DEFAULT_LANE_HEIGHTS = {
  sessions: 40,
  srum_app: 120,
  srum_net: 100,
  mft_usn: 120,
  execution: 100,
  cache: 80,
};

/** Determine which view to use based on zoomLevel label */
function getViewModeFromZoom(zoomLabel) {
  if (['Year', '6 Months', '3 Months', 'Month', '2 Weeks'].includes(zoomLabel)) return 'heatmap';
  if (['Week', '3 Days'].includes(zoomLabel)) return 'week';
  return '24h';
}

export function useTimelineState() {
  // Time range
  const [timeRange, setTimeRange] = useState({ start: null, end: null });
  
  // Zoom
  const [zoomLevel, setZoomLevel] = useState(8); // Default: 12 Hours view
  
  // View mode override (null = auto from zoom)
  const [viewModeOverride, setViewModeOverride] = useState(null);
  
  // Filters
  const [activeArtifacts, setActiveArtifacts] = useState(DEFAULT_ARTIFACTS);
  
  // Selection
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [detailEvent, setDetailEvent] = useState(null); // For modal
  
  // Lane heights (resizable)
  const [laneHeights, setLaneHeights] = useState({});
  
  // Search
  const [searchTerm, setSearchTerm] = useState('');
  
  // Detail panel
  const [detailPanelCollapsed, setDetailPanelCollapsed] = useState(false);

  // Computed: pixels per hour for current zoom
  const pxPerHour = useMemo(() => {
    return ZOOM_LEVELS[zoomLevel]?.pxPerHour || 60;
  }, [zoomLevel]);

  // Computed: zoom label
  const zoomLabel = useMemo(() => {
    return ZOOM_LEVELS[zoomLevel]?.label || 'Day';
  }, [zoomLevel]);

  // Computed: current view mode (Auto-switches based on zoom)
  const viewMode = useMemo(() => {
    if (viewModeOverride) return viewModeOverride;
    return getViewModeFromZoom(zoomLabel);
  }, [viewModeOverride, zoomLabel]);

  // Zoom handlers
  const zoomIn = useCallback(() => {
    setZoomLevel(z => Math.min(z + 1, ZOOM_LEVELS.length - 1));
  }, []);

  const zoomOut = useCallback(() => {
    setZoomLevel(z => {
      const isForced24h = viewModeOverride === '24h';
      const minIndex = isForced24h ? 7 : 0; // 7 corresponds to 'Day'
      return Math.max(z - 1, minIndex);
    });
  }, [viewModeOverride]);

  // Filter toggle
  const toggleArtifact = useCallback((key) => {
    setActiveArtifacts(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Lane resize
  const setLaneHeight = useCallback((laneKey, height) => {
    setLaneHeights(prev => ({ ...prev, [laneKey]: Math.max(40, height) }));
  }, []);

  return {
    // Time
    timeRange, setTimeRange,
    // Zoom
    zoomLevel, setZoomLevel, zoomIn, zoomOut,
    pxPerHour, zoomLabel,
    // View
    viewMode, setViewModeOverride,
    // Filters
    activeArtifacts, toggleArtifact, setActiveArtifacts,
    // Selection
    selectedEvent, setSelectedEvent,
    detailEvent, setDetailEvent,
    // Layout
    laneHeights, setLaneHeight,
    detailPanelCollapsed, setDetailPanelCollapsed,
    // Search
    searchTerm, setSearchTerm,
    // Constants
    ZOOM_LEVELS,
  };
}
