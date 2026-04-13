/**
 * App.jsx — Root component for the Crow-Eye Forensic Timeline.
 * 
 * Data loading pipeline:
 *   1. Boot → fetch global time bounds + available databases
 *   2. Fetch aggregated per-day counts for the heatmap overview
 *   3. User clicks a day on heatmap → fetch detailed lane data for day ± 3 days
 *   4. (Auto-test mode): steps 2→3 happen automatically after 1.5s
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import './styles/timeline.css';
import { useBridge } from './hooks/useBridge';
import { useTimelineState } from './hooks/useTimelineState';
import { useLinks } from './hooks/useLinks';
import TopBar from './components/TopBar';
import PillBar from './components/PillBar';
import TimelineView from './components/TimelineView';
import WeekView from './components/WeekView';
import HeatmapView from './components/HeatmapView';
import DetailPanel from './components/DetailPanel';
import EventDetailModal from './components/EventDetailModal';
import { DEV_CONFIG } from './utils/devConfig';

console.log("CROW-EYE TIMELINE V3.0.7 - CONTAINER HEIGHT FIX ACTIVE");

export default function App() {
  const { callBridge, isLoading: bridgeLoading, isDev } = useBridge();
  const state = useTimelineState();
  const { 
    timeRange, setTimeRange, viewMode, setViewModeOverride, 
    selectedEvent, detailEvent, setDetailEvent, activeArtifacts
  } = state;

  const [globalBounds, setGlobalBounds] = useState({ start: null, end: null });
  const [data, setData] = useState({
    sessions: null, srum_app: null, srum_net: null, mft_usn: null,
    prefetch: null, lnk: null, bam: null, registry: null,
    amcache: null, shimcache: null, recyclebin: null, aggregated: null,
  });
  const [loading, setLoading] = useState(true);
  const [loadingMessage, setLoadingMessage] = useState('Initializing forensic engine...');
  const [availableDbs, setAvailableDbs] = useState({});
  const initDone = useRef(false);
  
  // Task 3.1: Viewport range management
  const [loadedTimeRange, setLoadedTimeRange] = useState({ start: null, end: null });
  const dataCache = useRef(new Map()); // Task 3.4.1: Store loaded data chunks with time range keys

  const { links } = useLinks(data, activeArtifacts, timeRange?.start, timeRange?.end);

  // Task 3.4.2: Check cache before fetching
  const getCachedData = useCallback((start, end) => {
    const cacheKey = `${start}-${end}`;
    return dataCache.current.get(cacheKey);
  }, []);

  // Task 3.4.1: Store data in cache with time range key
  const setCachedData = useCallback((start, end, newData) => {
    const cacheKey = `${start}-${end}`;
    dataCache.current.set(cacheKey, {
      data: newData,
      timestamp: Date.now(),
    });
    
    // Task 3.4.3: Implement LRU eviction for memory management (keep last 10 chunks)
    if (dataCache.current.size > 10) {
      const entries = Array.from(dataCache.current.entries());
      entries.sort((a, b) => a[1].timestamp - b[1].timestamp);
      dataCache.current.delete(entries[0][0]);
    }
  }, []);

  // Task 3.3.4: Merge new data with existing data (avoid duplicates)
  const mergeData = useCallback((existingData, newData) => {
    const merged = { ...existingData };
    
    // Helper to merge arrays and remove duplicates based on timestamp and type
    const mergeArray = (existing, incoming, idField = 'timestamp') => {
      if (!existing) return incoming;
      if (!incoming) return existing;
      
      const existingIds = new Set(existing.map(item => 
        `${item[idField]}-${item.type || ''}-${item.id || ''}`
      ));
      
      const newItems = incoming.filter(item => 
        !existingIds.has(`${item[idField]}-${item.type || ''}-${item.id || ''}`)
      );
      
      return [...existing, ...newItems].sort((a, b) => 
        new Date(a[idField]).getTime() - new Date(b[idField]).getTime()
      );
    };

    // Merge each data type
    if (newData.sessions) {
      merged.sessions = {
        events: mergeArray(existingData.sessions?.events, newData.sessions?.events),
        bands: mergeArray(existingData.sessions?.bands, newData.sessions?.bands, 'start'),
      };
    }
    
    merged.srum_app = mergeArray(existingData.srum_app, newData.srum_app);
    
    if (newData.srum_net) {
      merged.srum_net = {
        connectivity: mergeArray(existingData.srum_net?.connectivity, newData.srum_net?.connectivity),
        data_usage: mergeArray(existingData.srum_net?.data_usage, newData.srum_net?.data_usage),
      };
    }
    
    merged.mft_usn = mergeArray(existingData.mft_usn, newData.mft_usn);
    merged.prefetch = mergeArray(existingData.prefetch, newData.prefetch, 'last_executed');
    merged.lnk = mergeArray(existingData.lnk, newData.lnk, 'Time_Access');
    merged.bam = mergeArray(existingData.bam, newData.bam, 'last_execution');
    
    if (newData.registry) {
      merged.registry = {
        open_save_mru: mergeArray(existingData.registry?.open_save_mru, newData.registry?.open_save_mru, 'access_date'),
        last_save_mru: mergeArray(existingData.registry?.last_save_mru, newData.registry?.last_save_mru, 'access_date'),
        recent_docs: mergeArray(existingData.registry?.recent_docs, newData.registry?.recent_docs, 'access_date'),
        user_assist: mergeArray(existingData.registry?.user_assist, newData.registry?.user_assist, 'access_date'),
        shellbags: mergeArray(existingData.registry?.shellbags, newData.registry?.shellbags, 'accessed_date'),
      };
    }
    
    merged.amcache = newData.amcache ? {
      application_files: mergeArray(existingData.amcache?.application_files, newData.amcache?.application_files, 'link_date'),
      applications: mergeArray(existingData.amcache?.applications, newData.amcache?.applications),
      drivers: mergeArray(existingData.amcache?.drivers, newData.amcache?.drivers),
    } : existingData.amcache;
    
    merged.shimcache = mergeArray(existingData.shimcache, newData.shimcache, 'last_modified');
    merged.recyclebin = mergeArray(existingData.recyclebin, newData.recyclebin, 'deletion_time');
    
    return merged;
  }, []);


  // ─── Phase 1: Initialize bounds + aggregated heatmap data ───
  useEffect(() => {
    if (bridgeLoading || initDone.current) return;
    initDone.current = true;

    (async () => {
      try {
        setLoading(true);
        setLoadingMessage('Connecting to forensic databases...');

        /* Auto-test jump disabled to prevent unsolicited view changes on case open */

        const [bounds, dbs] = await Promise.all([
          callBridge('getTimeBounds'),
          callBridge('getAvailableDatabases'),
        ]);
        
        if (dbs) setAvailableDbs(dbs);

        if (!bounds?.start || !bounds?.end) {
          setLoadingMessage('No forensic data found in case.');
          setLoading(false);
          return;
        }

        setGlobalBounds(bounds);
        setLoadingMessage('Aggregating activity counts across all databases...');

        const aggregated = await callBridge('getAggregatedCounts', bounds.start, bounds.end);
        setData(prev => ({ ...prev, aggregated }));

        // Land on heatmap overview
        setViewModeOverride('heatmap');
        setLoading(false);

      } catch (e) {
        console.error('[App] Init error:', e);
        setLoadingMessage('Error: ' + e.message);
        setLoading(false);
      }
    })();
  }, [bridgeLoading, callBridge]);

  const loadedDayIdRef = useRef(null);
  const loadingTimerRef = useRef(null);

  // ─── Phase 2: Load detailed lane data when timeRange changes ───
  const loadDetailData = useCallback(async (signal) => {
    if (!timeRange.start || !timeRange.end) return;
    if (viewMode === 'heatmap') return;

    // Task 3.1: Day-ID based Stability Check
    // Extracts the date portion (YYYY-MM-DD) from the ISO string to determine if we already have this day
    const dayId = timeRange.start.split('T')[0];
    
    if (loadedDayIdRef.current === dayId) {
      console.log('[App] Day already loaded in memory:', dayId);
      // Ensure loading state is reset but don't trigger a new fetch
      setLoading(false);
      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);
      return;
    }

    // Clear any existing loading timer to prevent flickering
    if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);

    try {
      const { start, end } = timeRange;
      
      // Check cache first for exact matches
      const cached = getCachedData(start, end);
      if (cached) {
        console.log('[App] Using cached data for day:', dayId);
        setData(prev => ({ ...prev, ...cached.data }));
        setLoadedTimeRange({ start, end });
        loadedDayIdRef.current = dayId;
        setLoading(false);
        return;
      }

      // ONLY SHOW LOADING SCREEN IF FETCH TAKES > 150MS (Prevents flicker for fast responses)
      loadingTimerRef.current = setTimeout(() => {
        setLoading(true);
        setLoadingMessage('Loading detailed forensic events for selected day...');
      }, 150);
      
      const results = await Promise.allSettled([
        callBridge('getSessionData', start, end),
        callBridge('getSrumAppData', start, end),
        callBridge('getSrumNetData', start, end),
        callBridge('getMftUsnData', start, end),
        callBridge('getPrefetchData', start, end),
        callBridge('getLnkData', start, end),
        callBridge('getBamData', start, end),
        callBridge('getRegistryData', start, end),
        callBridge('getAmcacheData', start, end),
        callBridge('getShimcacheData', start, end),
        callBridge('getRecyclebinData', start, end),
      ]);

      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);

      if (signal.aborted) return;

      const val = (i) => results[i].status === 'fulfilled' ? results[i].value : null;

      const newData = {
        sessions: val(0), srum_app: val(1), srum_net: val(2), mft_usn: val(3),
        prefetch: val(4), lnk: val(5), bam: val(6), registry: val(7),
        amcache: val(8), shimcache: val(9), recyclebin: val(10),
      };

      setData(prev => ({ ...prev, ...newData }));
      
      // Store in cache and update tracking refs/state
      setCachedData(start, end, newData);
      setLoadedTimeRange({ start, end });
      loadedDayIdRef.current = dayId;

      setLoading(false);

    } catch (e) {
      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);
      if (signal.aborted) return;
      console.error('[App] Detail load error:', e);
      setLoading(false);
    }
  }, [timeRange, viewMode, callBridge, getCachedData, setCachedData]);

  useEffect(() => {
    const controller = new AbortController();
    loadDetailData(controller.signal);
    return () => controller.abort();
  }, [loadDetailData]);

  // ─── Compute stats for TopBar ───
  const stats = {
    totalEvents: 0,
    loaded: !loading,
  };

  // ─── Render ───
  return (
    <div className="app">
      <TopBar state={state} loading={loading} />
      <PillBar state={state} data={data} />

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
        <div className="timeline-container">
          {/* Main View Area */}
          {isDev ? (
            <div className="empty-state">
              <div style={{ color: 'var(--accent-orange)', fontSize: 16 }}>⚠ Development Mode</div>
              <div>No QWebChannel bridge detected. Run inside Crow-Eye.</div>
            </div>
          ) : !globalBounds.start && !loading ? (
            <div className="empty-state">
              <div>No forensic data available</div>
              <div style={{ fontSize: 11 }}>Load a case to begin timeline analysis</div>
            </div>
          ) : viewMode === 'heatmap' ? (
            <HeatmapView globalBounds={globalBounds} data={data} state={state} setLoading={setLoading} setLoadingMessage={setLoadingMessage} />
          ) : viewMode === 'week' ? (
            <WeekView data={data} state={state} />
          ) : (
            <TimelineView 
               data={data} 
               state={state} 
               links={links} 
               callBridge={callBridge}
               loadedTimeRange={loadedTimeRange}
            />
          )}
        </div>
        
        <DetailPanel state={state} data={data} links={links} callBridge={callBridge} />
      </div>
      
      {detailEvent && (
        <EventDetailModal
          event={detailEvent}
          onClose={() => setDetailEvent(null)}
          callBridge={callBridge}
        />
      )}

      {/* ─── Full-Screen Loading Overlay ─── */}
      {loading && (
        <div style={{
          position: 'fixed', top: 0, left: 0, width: '100%', height: '100%',
          backgroundColor: 'rgba(10, 14, 26, 0.85)',
          backdropFilter: 'blur(8px)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          color: 'var(--text-primary)', zIndex: 9999,
        }}>
          <div style={{
            width: 60, height: 60,
            border: '3px solid var(--border-default)',
            borderTopColor: 'var(--accent-cyan)',
            borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
          }} />
          <h2 style={{
            marginTop: 25, fontSize: 20, fontWeight: '500',
            letterSpacing: '0.5px', color: 'var(--accent-cyan)',
          }}>
            Crow-Eye Timeline
          </h2>
          <p style={{ marginTop: 10, color: 'var(--text-secondary)', fontSize: 13 }}>
            {loadingMessage}
          </p>
        </div>
      )}
    </div>
  );
}
