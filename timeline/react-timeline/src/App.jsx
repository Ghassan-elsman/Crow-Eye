/**
 * App.jsx — Root component for the Crow-Eye Forensic Timeline.
 * 
 * Data loading pipeline:
 *   1. Boot → fetch global time bounds + available databases
 *   2. Fetch aggregated per-day counts for the heatmap overview
 *   3. User clicks a day on heatmap → fetch detailed lane data for day ± 3 days
 *   4. (Auto-test mode): steps 2→3 happen automatically after 1.5s
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
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
import { heuristicFlatten } from './utils/dataUtils';
import { getPrimaryTimestamp, getForensicName, cleanForensicDate, getName, normalizeForensicName } from './utils/formatters';

console.log("CROW-EYE TIMELINE V3.0.7 - CONTAINER HEIGHT FIX ACTIVE");

export default function App() {
  const { callBridge, isLoading: bridgeLoading, isDev } = useBridge();
  const state = useTimelineState();
  const {
    timeRange, setTimeRange, viewMode, setViewModeOverride,
    selectedEvent, detailEvent, setDetailEvent, activeArtifacts,
    searchTerm
  } = state;

  const [globalBounds, setGlobalBounds] = useState({ start: null, end: null });
  const [data, setData] = useState({
    sessions: null, srum_app: null, srum_net: null, mft_usn: null,
    prefetch: null, lnk: null, bam: null, dam: null, registry: null,
    amcache: null, shimcache: null, recyclebin: null, aggregated: null,
  });
  const [loading, setLoading] = useState(true);
  const [loadingMessage, setLoadingMessage] = useState('Initializing forensic engine...');
  const [availableDbs, setAvailableDbs] = useState({});
  const initDone = useRef(false);
  const lastFetchId = useRef(0);

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

    // Task 3.4.3: Implement LRU eviction for memory management
    if (dataCache.current.size > 15) {
      const entries = Array.from(dataCache.current.entries());
      entries.sort((a, b) => a[1].timestamp - b[1].timestamp);
      dataCache.current.delete(entries[0][0]);
    }
  }, []);

  const clearCache = useCallback(() => {
    console.log('[App] Clearing forensic data cache...');
    dataCache.current.clear();
    loadedDayIdRef.current = null;
  }, []);

  // Task 3.3.4: Merge new data with existing data (avoid duplicates)
  const mergeData = useCallback((existingData, newData) => {
    const merged = { ...existingData };

    const mergeArray = (existing, incoming, typeHint) => {
      const safeExisting = Array.isArray(existing) ? existing : [];
      const safeIncoming = Array.isArray(incoming) ? incoming : [];

      const getRefTs = (p) => {
        if (!p) return null;
        const tsFields = [
          'timestamp', 'time', 'start', 'last_execution', 'last_executed', 'run_times',
          'install_date', 'installation_date', 'link_date', 'driver_last_write_time',
          'driver_time_stamp', 'deletion_time', 'created_date', 'modified_date',
          'accessed_date', 'connection_date', 'last_modified', 'si_creation_time',
          'Time_Creation', 'Time_Modification', 'Time_Access'
        ];
        // Case-insensitive manifest field lookup
        const key = Object.keys(p).find(k => tsFields.some(f => f.toLowerCase() === k.toLowerCase()));
        return key ? p[key] : null;
      };

      const getFingerprint = (item) => {
        if (!item) return Math.random().toString();
        const ts = cleanForensicDate(getRefTs(item)) || 'unknown';
        const name = normalizeForensicName(getName(item));
        const secondary = item.id || item.rowid || item.event_id || item.index || '';
        const source = (item.source_table || item.db_name || typeHint || '').toLowerCase();
        return `${ts}-${name}-${source}-${secondary}`.toLowerCase();
      };

      const existingIds = new Set(safeExisting.map(getFingerprint));
      const newItems = safeIncoming.filter(item => !existingIds.has(getFingerprint(item)));

      return [...safeExisting, ...newItems].sort((a, b) => {
        const tA = new Date(cleanForensicDate(getRefTs(a))).getTime();
        const tB = new Date(cleanForensicDate(getRefTs(b))).getTime();
        return (isNaN(tA) ? 0 : tA) - (isNaN(tB) ? 0 : tB);
      });
    };

    // Merge each data type
    const deduplicateBatch = (batch, type) => {
      if (!Array.isArray(batch)) return batch;
      const seen = new Set();
      return batch.filter(item => {
        const fp = getFingerprint(item);
        if (seen.has(fp)) return false;
        seen.add(fp);
        return true;
      });
    };

    if (newData.sessions) {
      merged.sessions = {
        events: mergeArray(existingData.sessions?.events, deduplicateBatch(newData.sessions?.events, 'session')),
        bands: mergeArray(existingData.sessions?.bands, deduplicateBatch(newData.sessions?.bands, 'session_band'), 'session_band'),
      };
    }

    merged.srum_app = mergeArray(existingData.srum_app, deduplicateBatch(newData.srum_app, 'srum_app'), 'srum_app');

    if (newData.srum_net) {
      merged.srum_net = {
        connectivity: mergeArray(existingData.srum_net?.connectivity, deduplicateBatch(newData.srum_net?.connectivity, 'net_conn'), 'net_conn'),
        data_usage: mergeArray(existingData.srum_net?.data_usage, deduplicateBatch(newData.srum_net?.data_usage, 'net_data'), 'net_data'),
      };
    }

    merged.mft_usn = mergeArray(existingData.mft_usn, deduplicateBatch(newData.mft_usn, 'mft_usn'), 'mft_usn');
    merged.prefetch = mergeArray(existingData.prefetch, deduplicateBatch(newData.prefetch, 'prefetch'), 'prefetch');
    merged.lnk = mergeArray(existingData.lnk, deduplicateBatch(newData.lnk, 'lnk'), 'lnk');
    merged.bam = mergeArray(existingData.bam, deduplicateBatch(newData.bam, 'bam'), 'bam');
    merged.dam = mergeArray(existingData.dam, deduplicateBatch(newData.dam, 'dam'), 'dam');

    if (newData.registry) {
      const mergedRegistry = { ...(existingData.registry || {}) };
      Object.keys(newData.registry).forEach(table => {
        mergedRegistry[table] = mergeArray(existingData.registry?.[table], deduplicateBatch(newData.registry[table], `reg_${table}`), `reg_${table}`);
      });
      merged.registry = mergedRegistry;
    }

    merged.amcache = newData.amcache ? {
      application_files: mergeArray(existingData.amcache?.application_files, deduplicateBatch(newData.amcache?.application_files, 'link_date'), 'link_date'),
      applications: mergeArray(existingData.amcache?.applications, deduplicateBatch(newData.amcache?.applications)),
      drivers: mergeArray(existingData.amcache?.drivers, deduplicateBatch(newData.amcache?.drivers)),
    } : existingData.amcache;

    merged.shimcache = mergeArray(existingData.shimcache, deduplicateBatch(newData.shimcache, 'last_modified'), 'last_modified');
    merged.recyclebin = mergeArray(existingData.recyclebin, deduplicateBatch(newData.recyclebin, 'deletion_time'), 'deletion_time');

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

        // Task 10.4: WIPE CACHE ON NEW CASE OPEN
        // Ensures that stale nested data structures from previous forensic images
        // do not poison the new state with incompatible 'bam' or 'lnk' objects.
        clearCache();

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
    
    // Clear tracked day if we are in heatmap, so re-entering the same day triggers a refresh
    if (viewMode === 'heatmap') {
      loadedDayIdRef.current = null;
      return;
    }

    const dayId = timeRange.start.split(/[T ]/)[0];

    // Task 3.4.2: Check cache first
    const { start, end } = timeRange;
    const cached = getCachedData(start, end);

    // Task 3.1: Day-ID based Stability Check
    // We only skip if the day is already loaded AND we haven't just come from heatmap
    if (loadedDayIdRef.current === dayId) {
      setLoading(false);
      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);
      
      return;
    }

    // Task 3.6: Memory Management (Pruning)
    // Only prune if we are actually about to load new data (not found in cache)
    if (!cached) {
      const isAdjacent = loadedDayIdRef.current && 
                         Math.abs(new Date(dayId).getTime() - new Date(loadedDayIdRef.current).getTime()) < 86400000 * 3;
      
      if (!isAdjacent && loadedDayIdRef.current !== null) {
        console.log('[App] Distant jump detected. Clearing memory state to keep RAM usage low.');
        setData({
          sessions: null, srum_app: null, srum_net: null, mft_usn: null,
          prefetch: null, lnk: null, bam: null, dam: null, registry: null,
          amcache: null, shimcache: null, recyclebin: null, aggregated: data.aggregated,
        });
      }
    }

    // Task 3.6.1: LRU Cache Pruning
    if (dataCache.current.size > 10) {
      const firstKey = dataCache.current.keys().next().value;
      dataCache.current.delete(firstKey);
    }

    if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);

    try {
      if (cached) {
        console.log('[App] Using cached data for day:', dayId);
        console.log('[DIAG] Cached Data:', {
          timeRange: { start, end },
          prefetch: cached.data.prefetch?.length || 0,
          lnk: cached.data.lnk?.length || 0,
          shimcache: cached.data.shimcache?.length || 0,
          recyclebin: cached.data.recyclebin?.length || 0
        });
        
        setData(prev => ({ ...prev, ...cached.data }));
        setLoadedTimeRange({ start, end });
        loadedDayIdRef.current = dayId;
        setLoading(false);
        
        return;
      }

      // Task 3.5: Race Condition Prevention (Request Fencing)
      const currentFetchId = ++lastFetchId.current;

      const safeParse = (raw) => {
        if (!raw) return null;
        try {
          const firstPass = (typeof raw === 'string') ? JSON.parse(raw) : raw;
          if (firstPass && typeof firstPass === 'object' && firstPass.hasOwnProperty('value')) {
            return (typeof firstPass.value === 'string') ? JSON.parse(firstPass.value) : firstPass.value;
          }
          return firstPass;
        } catch (e) {
          console.warn('[BRIDGE] JSON Parse Failure:', e);
          return (typeof raw === 'object') ? raw : null;
        }
      };

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

      if (currentFetchId !== lastFetchId.current) return;
      if (loadingTimerRef.current) clearTimeout(loadingTimerRef.current);
      if (signal.aborted) return;

      const val = (i) => results[i].status === 'fulfilled' ? safeParse(results[i].value) : null;

      // Master Mapping Logic: Ensure manifest databases map to standardized keys
      const rawSessions = val(0);
      const rawSrumApp = val(1);
      const rawSrumNet = val(2);
      const rawMft = val(3);
      const rawPrefetch = val(4);
      const rawLnk = val(5);
      const rawBamDam = val(6);
      const rawRegistry = val(7);
      const rawAmcache = val(8);
      const rawShimcache = val(9);
      const rawRecycleBin = val(10);

      // DIAGNOSTIC LOGGING: Backend Response
      console.log('[DIAG] Bridge Responses:', {
        timeRange: { start, end },
        prefetch: Array.isArray(rawPrefetch) ? rawPrefetch.length : 'not array',
        lnk: Array.isArray(rawLnk) ? rawLnk.length : 'not array',
        amcache: rawAmcache ? {
          application_files: rawAmcache.application_files?.length || 0,
          applications: rawAmcache.applications?.length || 0,
          drivers: rawAmcache.drivers?.length || 0
        } : 'null',
        shimcache: Array.isArray(rawShimcache) ? rawShimcache.length : 'not array',
        recyclebin: Array.isArray(rawRecycleBin) ? rawRecycleBin.length : 'not array'
      });

      const bamArray = Array.isArray(rawBamDam?.bam) ? rawBamDam.bam : heuristicFlatten(rawBamDam);
      const damArray = Array.isArray(rawBamDam?.dam) ? rawBamDam.dam : heuristicFlatten(rawBamDam?.dam);

      const newData = {
        sessions: rawSessions ? {
          events: heuristicFlatten(rawSessions.events || rawSessions),
          bands: heuristicFlatten(rawSessions.bands)
        } : null,
        srum_app: heuristicFlatten(rawSrumApp),
        srum_net: rawSrumNet ? {
          connectivity: heuristicFlatten(rawSrumNet.connectivity),
          data_usage: heuristicFlatten(rawSrumNet.data_usage)
        } : null,
        mft_usn: heuristicFlatten(rawMft),
        prefetch: heuristicFlatten(rawPrefetch),
        lnk: heuristicFlatten(rawLnk),
        bam: bamArray,
        dam: damArray,
        registry: rawRegistry,
        amcache: rawAmcache ? {
          application_files: heuristicFlatten(rawAmcache.application_files),
          applications: heuristicFlatten(rawAmcache.applications),
          drivers: heuristicFlatten(rawAmcache.drivers)
        } : null,
        shimcache: heuristicFlatten(rawShimcache),
        recyclebin: heuristicFlatten(rawRecycleBin),
      };

      // Registry table normalization (case-insensitive keys for easier discovery)
      if (newData.registry && typeof newData.registry === 'object') {
        const normalizedReg = {};
        Object.keys(newData.registry).forEach(k => {
          normalizedReg[k.toLowerCase()] = heuristicFlatten(newData.registry[k]);
        });
        newData.registry = normalizedReg;
      }

      console.log('[DEBUG] Ingested Data State:', {
        registryKeys: newData.registry ? Object.keys(newData.registry) : [],
        prefetchCount: newData.prefetch?.length,
        lnkCount: newData.lnk?.length
      });

      // DIAGNOSTIC LOGGING: State After Flatten
      console.log('[DIAG] State After Flatten:', {
        prefetch: newData.prefetch?.length || 0,
        lnk: newData.lnk?.length || 0,
        amcache: newData.amcache ? {
          application_files: newData.amcache.application_files?.length || 0,
          applications: newData.amcache.applications?.length || 0,
          drivers: newData.amcache.drivers?.length || 0
        } : null,
        shimcache: newData.shimcache?.length || 0,
        recyclebin: newData.recyclebin?.length || 0
      });

      setData(prev => ({ ...prev, ...newData }));
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
  }, [timeRange, viewMode, callBridge, getCachedData, setCachedData, data.aggregated]);

  useEffect(() => {
    const controller = new AbortController();
    loadDetailData(controller.signal);
    return () => controller.abort();
  }, [loadDetailData]);

  // ─── Compute reactive stats for TopBar ───
  // Task 11.3: Bind statistics to the filtered model (search/type filters)
  const stats = useMemo(() => {
    let total = 0;
    let visible = 0;

    const lowerTerm = searchTerm?.toLowerCase() || '';
    const checkMatch = (item) => {
      if (!lowerTerm || lowerTerm.length < 2) return true;
      const name = (item.Source_Name || item.executable_name || item.driver_name || item.search_term || item.computer_name || item.name || item.filename || '').toLowerCase();
      const type = (item.type || item.artifact_type || '').toLowerCase();
      return name.includes(lowerTerm) || type.includes(lowerTerm);
    };

    Object.entries(data).forEach(([key, laneData]) => {
      if (!laneData || key === 'aggregated') return;
      
      let items = [];
      if (key === 'registry') {
        // Sum all nested registry tables
        Object.values(laneData).forEach(table => {
          items = [...items, ...heuristicFlatten(table)];
        });
      } else {
        items = Array.isArray(laneData) ? laneData : (laneData.events || []);
      }

      total += items.length;
      if (lowerTerm) {
        visible += items.filter(checkMatch).length;
      } else {
        visible += items.length;
      }

      if (laneData.bands) {
        total += laneData.bands.length;
        visible += lowerTerm ? laneData.bands.filter(checkMatch).length : laneData.bands.length;
      }
    });

    return {
      totalEvents: total,
      visibleEvents: visible,
      loaded: !loading,
      hasSearch: !!lowerTerm
    };
  }, [data, loading, searchTerm]);

  // ─── Render ───
  return (
    <div className="app">
      <TopBar state={state} loading={loading} stats={stats} />
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
