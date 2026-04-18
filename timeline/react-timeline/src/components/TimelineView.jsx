/**
 * TimelineView — Main 24H detail view rendering individual events as SVG.
 */
import { memo, useMemo, useRef, useState, useEffect, useLayoutEffect } from 'react';
import { normalizeForensicName, formatBytes, formatTime, formatCycleTime, formatDuration, getForensicName, getForensicTimestamps, getForensicId, getPrimaryTimestamp, cleanForensicDate, getArtifactSources } from '../utils/formatters';
import LaneDataModal from './LaneDataModal';
import { heuristicFlatten } from '../utils/dataUtils';

/** trackAllocator logic (now integrated) */
function allocateTracks(items, minGapMs = 20000) {
  if (!items || items.length === 0) return [];
  const sorted = [...items].sort((a, b) => {
    const tA = new Date(cleanForensicDate(a.start || a.timestamp)).getTime();
    const tB = new Date(cleanForensicDate(b.start || b.timestamp)).getTime();
    return tA - tB;
  });
  const trackEnds = [];
  for (const item of sorted) {
    const startMs = new Date(cleanForensicDate(item.start || item.timestamp)).getTime();
    const endMs = item.end ? new Date(cleanForensicDate(item.end)).getTime() : startMs + minGapMs;
    let assigned = -1;
    for (let t = 0; t < trackEnds.length; t++) {
      if (trackEnds[t] + minGapMs <= startMs) { assigned = t; break; }
    }
    if (assigned === -1) { assigned = trackEnds.length; trackEnds.push(endMs); }
    else { trackEnds[assigned] = endMs; }
    item.track = assigned;
  }
  return sorted;
}

function trackToY(track, laneHeight, maxTracks = 5, padding = 12) {
  const minTrackHeight = Math.max(30, (laneHeight - padding * 2) / Math.max(1, maxTracks));
  return padding + (track * minTrackHeight) + (minTrackHeight / 2);
}

const HOUR_MS = 60 * 60 * 1000;

const LANES_META = [
  { key: 'sessions', label: 'Sessions / Power', sub: 'Logon, Power, Sleep', color: 'var(--lane-sessions)' },
  { key: 'srum_app', label: 'SRUM App Usage', sub: 'Foreground/Background Cycles', color: 'var(--lane-srum-app)' },
  { key: 'srum_net', label: 'SRUM Network', sub: 'Connectivity, Data Usage', color: 'var(--lane-srum-net)' },
  { key: 'mft_usn', label: 'MFT / USN', sub: 'File Creation, Deletion, Rename', color: 'var(--lane-mft-usn)' },
  { key: 'artifacts', label: 'Unified Artifacts', sub: 'LNK, PF, BAM, Reg, USB, Bin', color: 'var(--lane-cache)' },
];

/** Safe timeToX that won't crash on bad timestamps */
function safeTimeToX(iso, rangeStart, pxPerHour) {
  if (!iso || !rangeStart) return 0;

  const t = new Date(cleanForensicDate(iso)).getTime();
  const s = new Date(cleanForensicDate(rangeStart)).getTime();
  if (isNaN(t) || isNaN(s)) return 0;
  return ((t - s) / 3600000) * pxPerHour;
}

function filterValid(items) {
  if (!items || !Array.isArray(items)) return [];
  return items.filter(item => {
    if (!item.timestamp) return false;
    return !isNaN(new Date(cleanForensicDate(item.timestamp)).getTime());
  });
}

function TimelineView({ data, state, links, callBridge, loadedTimeRange }) {
  const {
    timeRange, pxPerHour, activeArtifacts,
    laneHeights, selectedEvent, setSelectedEvent, setDetailEvent, setLaneHeight,
    searchTerm
  } = state;

  const containerRef = useRef(null);
  const wrapperRef = useRef(null);
  const laneRefs = useRef({});
  const anchorTimeRef = useRef(null);
  const anchorMouseXRef = useRef(0);
  const lastScale = useRef(pxPerHour);

  const scrollXRef = useRef(0);
  const scrollYRef = useRef(0);
  const labelColumnRef = useRef(null);
  const lanesContentRef = useRef(null);
  const [laneScroll, setLaneScroll] = useState({});
  const [containerHeight, setContainerHeight] = useState(800);
  const [tooltip, setTooltip] = useState(null);
  const [selectedLaneModal, setSelectedLaneModal] = useState(null);

  // Search filtering helper
  const searchMatch = (item) => {
    if (!searchTerm || searchTerm.length < 2) return { match: false, hide: false };
    const lowerTerm = searchTerm.toLowerCase();
    const name = (getName(item) || '').toLowerCase();
    const eventName = (item.event_name || '').toLowerCase();
    const type = (item.type || item.artifact_type || item._artifact_type || '').toLowerCase();
    const source = (item.source_table || '').toLowerCase();
    const path = (item.path || item.id || item.rowid || '').toLowerCase();
    const regKey = (item.registry_key || item.key_path || '').toLowerCase();
    
    // Task 12.3: Forensic Deep Search - Keyword audits paths and registry keys
    const isMatch = name.includes(lowerTerm) || type.includes(lowerTerm) || 
                   eventName.includes(lowerTerm) || source.includes(lowerTerm) ||
                   path.includes(lowerTerm) || regKey.includes(lowerTerm);
    
    return { match: isMatch, hide: false }; 
  };

  const scrollFrame = useRef(0);
  const vScrollFrame = useRef(0);
  const laneScrollFrames = useRef({});
  const prevPxPerHour = useRef(pxPerHour);

  // Task 11.1: Focal-Point Zoom Anchoring
  // Ensures that the time currently in the center of the viewport stays centered during scale changes.
  useLayoutEffect(() => {
    if (!containerRef.current || prevPxPerHour.current === pxPerHour) return;

    const container = containerRef.current;
    const viewWidth = container.clientWidth;
    const scrollX = container.scrollLeft;
    
    // Time (in hours) at the visual center of the screen
    const centerTimeHours = (scrollX + viewWidth / 2) / prevPxPerHour.current;
    
    // Target scroll to keep that same time at the visual center with the new scale
    const newCenterPx = centerTimeHours * pxPerHour;
    const newScrollX = Math.max(0, newCenterPx - viewWidth / 2);
    
    container.scrollLeft = newScrollX;
    prevPxPerHour.current = pxPerHour;
  }, [pxPerHour]);

  // Culling bounds decoupled from immediate scroll position
  const [cullScrollX, setCullScrollX] = useState(0);
  const viewStart = cullScrollX - 1200;
  const viewEnd = cullScrollX + (containerRef.current?.clientWidth || 1500) + 1200;

  const handleScroll = () => {
    if (!containerRef.current) return;
    const currentScrollX = containerRef.current.scrollLeft;
    const currentScrollY = containerRef.current.scrollTop;

    scrollXRef.current = currentScrollX;

    if (scrollFrame.current) cancelAnimationFrame(scrollFrame.current);
    scrollFrame.current = requestAnimationFrame(() => {
      if (Math.abs(currentScrollX - cullScrollX) > 500) {
        setCullScrollX(currentScrollX);
      }
    });

    if (vScrollFrame.current) cancelAnimationFrame(vScrollFrame.current);
    vScrollFrame.current = requestAnimationFrame(() => {
      if (labelColumnRef.current) {
        labelColumnRef.current.scrollTop = currentScrollY;
      }
    });

  };

  const handleLaneScroll = (key, e) => {
    const top = e.target.scrollTop;
    if (laneScrollFrames.current[key]) cancelAnimationFrame(laneScrollFrames.current[key]);
    laneScrollFrames.current[key] = requestAnimationFrame(() => {
      setLaneScroll(prev => ({ ...prev, [key]: top }));
    });
  };

  const handleEventDblClick = (ev) => {
    if (callBridge) {
      callBridge('openEventDetailDialog', JSON.stringify(ev));
    }
  };

  const handleEventMouseEnter = (e, ev) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setTooltip({
      ev,
      x: rect.left + rect.width / 2,
      y: rect.top - 10
    });
  };

  const getName = (p) => getForensicName(p);

  // --- Effects for Resize and Zoom Management ---
  // Use a more aggressive height measurement
  useLayoutEffect(() => {
    const updateH = () => {
      if (wrapperRef.current) {
        // Use multiple measurement methods for robustness in Qt WebEngine
        const rect = wrapperRef.current.getBoundingClientRect();
        const offsetH = wrapperRef.current.offsetHeight;
        const clientH = wrapperRef.current.clientHeight;
        // Also calculate from viewport position as fallback
        const viewportH = Math.floor(window.innerHeight - rect.top);
        const h = Math.max(Math.floor(rect.height), offsetH, clientH, viewportH);
        if (h > 100) setContainerHeight(h);
      }
    };
    updateH();
    // Delayed re-measurements for Qt WebEngine layout settling
    const t1 = setTimeout(updateH, 50);
    const t2 = setTimeout(updateH, 200);
    const t3 = setTimeout(updateH, 500);
    window.addEventListener('resize', updateH);
    
    let ob = null;
    if (typeof ResizeObserver !== 'undefined') {
      ob = new ResizeObserver(entries => {
        const rect = entries[0].contentRect;
        const offsetH = wrapperRef.current?.offsetHeight || 0;
        const viewportH = wrapperRef.current
          ? Math.floor(window.innerHeight - wrapperRef.current.getBoundingClientRect().top)
          : 0;
        const h = Math.max(Math.floor(rect.height), offsetH, viewportH);
        if (h > 100) setContainerHeight(h);
      });
      if (wrapperRef.current) ob.observe(wrapperRef.current);
    }
    
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      window.removeEventListener('resize', updateH);
      if (ob) ob.disconnect();
    };
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handleNativeWheel = (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const rect = el.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const currentScroll = el.scrollLeft;
        anchorTimeRef.current = (currentScroll + mouseX) / pxPerHour;
        anchorMouseXRef.current = mouseX;
        if (e.deltaY < 0) state.zoomIn();
        else state.zoomOut();
      }
    };
    el.addEventListener('wheel', handleNativeWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleNativeWheel);
  }, [state, pxPerHour]);

  useEffect(() => {
    const handleKeyPan = (e) => {
      if (!containerRef.current) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      const panAmount = containerRef.current.clientWidth * 0.4;
      if (e.key === 'ArrowLeft') {
        containerRef.current.scrollTo({ left: containerRef.current.scrollLeft - panAmount, behavior: 'smooth' });
      } else if (e.key === 'ArrowRight') {
        containerRef.current.scrollTo({ left: containerRef.current.scrollLeft + panAmount, behavior: 'smooth' });
      }
    };
    window.addEventListener('keydown', handleKeyPan);
    return () => window.removeEventListener('keydown', handleKeyPan);
  }, []);

  useEffect(() => {
    if (pxPerHour !== lastScale.current && anchorTimeRef.current !== null && containerRef.current) {
      const newScroll = (anchorTimeRef.current * pxPerHour) - anchorMouseXRef.current;
      containerRef.current.scrollLeft = newScroll;
      scrollXRef.current = newScroll;
      setCullScrollX(newScroll);
    }
    lastScale.current = pxPerHour;
  }, [pxPerHour]);

  // --- Core Layout Memo (Restored and Optimized) ---
  const { lanes, totalH, powerOnBands, posMap, totalWidth, activeKeys } = useMemo(() => {
    console.log('[DEBUG] TimelineView data state:', {
      sessions: !!data.sessions,
      srum: !!data.srum_app,
      bam: typeof data.bam
    });
    const s = timeRange.start;
    const e = timeRange.end;
    if (!s || !e) return { lanes: [], totalH: 600, powerOnBands: [], posMap: new Map(), totalWidth: 800, activeKeys: [] };

    const sTime = new Date(cleanForensicDate(s)).getTime();
    const eTime = new Date(cleanForensicDate(e)).getTime();
    const width = Math.max(800, ((eTime - sTime) / HOUR_MS) * pxPerHour);
    const pm = new Map();
    const pOnBands = [];

    // --- Master Forensic Discovery System ---
    // Task 19.3: Centralized Source Discovery
    // Ensures visibility checks and plotting always see the exact same data
    const getArtifactSources = (data) => {
      const registry = data.registry || {};
      return [
        { items: data.prefetch || data.prefetch_data, type: 'prefetch' },
        { items: data.lnk, type: 'lnk' },
        { items: data.bam, type: 'bam' },
        { items: data.dam, type: 'dam' },
        { items: data.shimcache, type: 'shimcache' },
        { items: data.recyclebin, type: 'recyclebin' },
        { items: (data.amcache || data.amcache_applications)?.application_files, type: 'amcache' },
        { items: (data.amcache || data.amcache_applications)?.applications, type: 'amcache' },
        { items: (data.amcache || data.amcache_applications)?.drivers, type: 'amcache' },
        ...Object.keys(registry).map(table => ({ items: registry[table], type: table.toLowerCase() }))
      ];
    };

    const inBounds = (ts) => {
      if (!ts) return false;
      const cleaned = cleanForensicDate(ts);
      const t = new Date(cleaned).getTime();
      return t >= sTime && t <= eTime;
    };

    const hasAnyInBounds = (arr) => {
      return heuristicFlatten(arr).some(item => {
        const times = getForensicTimestamps(item);
        return times.some(t => inBounds(t.time));
      });
    };

    const activeKeys = ['sessions', 'srum_app', 'srum_net', 'mft_usn', 'artifacts'].filter(k => {
      let isActive = true;
      if (activeArtifacts[k] === false && k !== 'artifacts') isActive = false;

      if (isActive) {
        if (k === 'sessions') {
          const evs = data.sessions?.events;
          const bnds = data.sessions?.bands;
          return hasAnyInBounds(evs) ||
            (Array.isArray(bnds) && bnds.some(b => inBounds(b.start) || inBounds(b.end)));
        }
        if (k === 'srum_app') return hasAnyInBounds(data.srum_app);
        if (k === 'srum_net') return hasAnyInBounds(data.srum_net?.connectivity) || hasAnyInBounds(data.srum_net?.data_usage);
        if (k === 'mft_usn') return hasAnyInBounds(data.mft_usn);

        if (k === 'artifacts') {
          const sources = getArtifactSources(data);
          const hasManifestData = sources.some(src => hasAnyInBounds(src.items));
            
          const hasSalvaged = Object.keys(data).some(key => {
            if (!['sessions', 'srum_app', 'srum_net', 'mft_usn', 'prefetch', 'bam', 'dam', 'lnk', 'shimcache', 'recyclebin', 'amcache', 'registry', 'aggregated', 'links'].includes(key)) {
              return hasAnyInBounds(data[key]);
            }
            return false;
          });
            
          return hasManifestData || hasSalvaged;
        }
      }
      return isActive;
    });

    const laneData = {};
    const minGap = 20000;

    // --- Recovery and Initialization ---
    const laneHeightsActual = { ...laneHeights };
    activeKeys.forEach((k) => {
      const val = Number(laneHeightsActual[k]);
      let minH = 60;
      if (k === 'artifacts') minH = 150; // Expand minimal size for unified artifacts lane
      const requestedH = (isNaN(val) || val <= 0) ? minH : val;
      laneHeightsActual[k] = Math.max(requestedH, minH);
    });

    // 1. Sessions / Login
    if (activeKeys.includes('sessions') && data.sessions) {
      const sBands = Array.isArray(data.sessions.bands) ? data.sessions.bands.map(b => {
        const x1 = safeTimeToX(b.start, s, pxPerHour);
        const x2 = safeTimeToX(b.end, s, pxPerHour);
        if (b.type === 'power') pOnBands.push({ startX: Math.max(0, x1), width: Math.max(2, x2 - Math.max(0, x1)) });
        return { ...b, x1, x2, bw: Math.max(2, x2 - x1) };
      }).filter(b => b.x1 > -100000 && b.x2 > -100000) : [];

      const sEvents = Array.isArray(data.sessions.events) ? data.sessions.events.map(ev => {
        const x = safeTimeToX(ev.timestamp, s, pxPerHour);
        const { match } = searchMatch(ev);
        return { ...ev, x, isSearchMatch: match };
      }).filter(ev => ev.x > -1000 && ev.x < width + 1000) : [];

      laneData['sessions'] = { items: { bands: sBands, events: sEvents }, numTracks: 1, innerH: 40 };
    }

    // 2. SRUM App
    if (activeKeys.includes('srum_app') && Array.isArray(data.srum_app)) {
      const apps = data.srum_app.map((a, idx, arr) => {
        const cleaned = cleanForensicDate(a.timestamp);
        const ts = new Date(cleaned).getTime();
        const { match } = searchMatch(a);
        const bgCycleMs = a.background_cycle_time ? Number(a.background_cycle_time) * 1000 : 0;
        const faceMs = a.face_time ? Number(a.face_time) * 1000 : 0;
        let bgStart = ts - Math.max(20000, bgCycleMs);
        let fgStart = ts - Math.max(20000, faceMs);
        if (idx > 0) {
          for (let i = idx - 1; i >= 0; i--) {
            const prev = arr[i];
            if (prev.app_name === a.app_name) {
              const prevEnd = new Date(prev.timestamp).getTime();
              if (bgStart < prevEnd) bgStart = prevEnd;
              if (fgStart < prevEnd) fgStart = prevEnd;
              break;
            }
          }
        }
        return { ...a, start: fgStart, end: ts, bgStart, type: 'srum_app', isSearchMatch: match };
      });
      const tracked = allocateTracks(apps, 10000);
      const nTracks = Math.max(1, tracked.reduce((max, a) => Math.max(max, a.track), 0) + 1);
      laneData['srum_app'] = { items: tracked, numTracks: nTracks, innerH: nTracks * 40 };
    }

    // 3. SRUM Net
    if (activeKeys.includes('srum_net') && data.srum_net) {
      const connData = (data.srum_net && Array.isArray(data.srum_net.connectivity)) ? data.srum_net.connectivity : [];
      const nets = connData.map((c, idx, arr) => {
        const cleaned = cleanForensicDate(c.timestamp);
        const ts = new Date(cleaned).getTime();
        const durMs = Math.max(20000, (parseFloat(c.connected_time) || 0) * 1000);
        const { match } = searchMatch(c);
        let start = ts - durMs;
        if (idx > 0) {
          for (let i = idx - 1; i >= 0; i--) {
            const prev = arr[i];
            if ((prev.app_name || prev.app_id) === (c.app_name || c.app_id)) {
              const prevEnd = new Date(prev.timestamp).getTime();
              if (start < prevEnd) start = prevEnd;
              break;
            }
          }
        }
        return { ...c, start, end: ts, type: 'srum_net', isSearchMatch: match };
      });
      
      const usageRaw = Array.isArray(data.srum_net.data_usage) ? data.srum_net.data_usage : [];
      const usageItems = usageRaw.map(u => {
        const x = safeTimeToX(u.timestamp, s, pxPerHour);
        const { match } = searchMatch(u);
        return { ...u, x, timestamp: u.timestamp, type: 'srum_net_usage', isSearchMatch: match };
      });

      // Unified Track Allocation: Interleave bands and dots to save vertical space
      const allItems = [...nets, ...usageItems];
      const tracked = allocateTracks(allItems, 25000);
      const nTracks = Math.max(1, tracked.reduce((m, p) => Math.max(m, p.track), 0) + 1);

      laneData['srum_net'] = { 
        items: { 
          netItems: tracked.filter(t => t.type === 'srum_net'),
          usageItems: tracked.filter(t => t.type === 'srum_net_usage')
        }, 
        numTracks: nTracks, 
        innerH: nTracks * 40 
      };
    }

    // 4. MFT/USN
    const mftData = heuristicFlatten(data.mft_usn);
    if (activeKeys.includes('mft_usn') && mftData.length > 0) {
      const pts = [];
      mftData.forEach(r => {
        const fullName = getName(r);
        if (r.si_creation_time) {
          const id = getForensicId('mft_create', r.si_creation_time, 'si_creation_time', fullName);
          const { match } = searchMatch({ ...r, timestamp: r.si_creation_time, type: 'mft_create' });
          pts.push({ ...r, id, timestamp: r.si_creation_time, type: 'mft_create', isSearchMatch: match });
        }
        if (r.usn_timestamp) {
          const id = getForensicId('mft_usn', r.usn_timestamp, 'usn_timestamp', fullName);
          const { match } = searchMatch({ ...r, timestamp: r.usn_timestamp, type: 'mft_usn' });
          pts.push({ ...r, id, timestamp: r.usn_timestamp, type: 'mft_usn', isSearchMatch: match });
        }
      });
      const tracked = allocateTracks(pts, 120000);
      const nTracks = Math.max(1, tracked.reduce((m, p) => Math.max(m, p.track), 0) + 1);
      laneData['mft_usn'] = { items: tracked, numTracks: nTracks, innerH: nTracks * 30 };
    }

    // 5. Unified Forensic Artifacts (Consolidated Lane 5)
    if (activeKeys.includes('artifacts')) {
      const pts = [];

      const addPoint = (p, ts, type, field = '') => {
        if (!ts) return;
        const name = getName(p);
        const { match } = searchMatch({ ...p, timestamp: ts, type, name });
        const id = getForensicId(type, ts, field, name);

        // Specialized label mapping for semantic icons
        let label = field.toLowerCase();
        if (label.includes('creation') || label.includes('created')) label = 'created';
        else if (label.includes('modification') || label.includes('modified')) label = 'modified';
        else if (label.includes('access')) label = 'accessed';
        else if (label.includes('executed') || label === 'run_times' || label.includes('last_run')) label = 'executed';
        else if (label.includes('install')) label = 'installed';
        else if (label.includes('delete')) label = 'deleted';
        else if (label.includes('shutdown')) label = 'shutdown';
        else if (label.includes('focus')) label = 'focus';
        else label = field.replace('_date', '').replace('_on', '').replace('Time_', '').replace('installation_', 'inst').toLowerCase();

        pts.push({
          ...p,
          timestamp: ts,
          type: type, 
          lane: 'artifacts',
          isSearchMatch: match,
          id,
          subType: type, // Priority: Style by Artifact Source (BAM, Prefetch, etc.)
          tsType: label, // Secondary: Semantic label for tooltip
          _artifact_type: type
        });
      };

      // 5.1 Unified Data Discovery Engine
      const artifactSources = getArtifactSources(data);
      console.log('[DEBUG] Lane 5 Sources:', artifactSources.map(s => `${s.type}(${s.items?.length || 0})`));
      
      const processedSignatures = new Set();
      let rejectedByBounds = 0;
      let totalPoints = 0;

      artifactSources.forEach(src => {
        heuristicFlatten(src.items).forEach(p => {
          const times = getForensicTimestamps(p);
          times.forEach(tsInfo => {
            // Exclusion Rule
            if (src.type === 'prefetch' && tsInfo.field === 'accessed_on') return;

            if (inBounds(tsInfo.time)) {
              const sig = `${src.type}-${tsInfo.time}-${tsInfo.field}-${normalizeForensicName(getName(p))}`.toLowerCase();
              if (processedSignatures.has(sig)) return;
              processedSignatures.add(sig);

              totalPoints++;
              addPoint(p, tsInfo.time, src.type, tsInfo.field);
            } else {
              rejectedByBounds++;
            }
          });
        });
      });
      console.log(`[DEBUG] Lane 5 Rendered: ${totalPoints} points. Rejected (Out of Bounds): ${rejectedByBounds}`);

      // 5.3 Salvage malformed data across all lanes
      const checkAndSalvage = (rawObj, sourceName) => {
        if (rawObj && typeof rawObj === 'object' && !Array.isArray(rawObj)) {
          const salvaged = heuristicFlatten(rawObj);
          salvaged.forEach(p => {
            const times = getForensicTimestamps(p);
            times.forEach(tsInfo => {
              if (inBounds(tsInfo.time)) {
                addPoint(p, tsInfo.time, sourceName, tsInfo.field);
              }
            });
          });
        }
      };

      checkAndSalvage(data.sessions?.events, 'salvaged_sessions_events');
      checkAndSalvage(data.srum_app, 'salvaged_srum_app');
      checkAndSalvage(data.srum_net?.connectivity, 'salvaged_srum_net_conn');
      checkAndSalvage(data.srum_net?.data_usage, 'salvaged_srum_net_usage');
      checkAndSalvage(data.mft_usn, 'salvaged_mft_usn');

      const tracked = allocateTracks(pts, 25000);
      const nTracks = Math.max(1, tracked.reduce((m, p) => Math.max(m, p.track), 0) + 1);

      laneData['artifacts'] = {
        items: tracked,
        numTracks: nTracks,
        innerH: nTracks * 38 
      };    }

    // --- Final Assembly Logic (Recovery Phase) ---
    const gapH = 8;
    const laneTops = {};
    const safeContainerHeight = Number(containerHeight) || 800;
    const headerH = 50; // 30px time axis + 20px top buffer
    const availableTotalH = Math.max(400, safeContainerHeight - headerH); 

    // Dynamic Sizing based on Data Density (Track Count)
    if (activeKeys.length > 0) {
      const totalAvailable = availableTotalH - (activeKeys.length - 1) * gapH;
      const dynamicKeys = activeKeys.filter(k => k !== 'sessions');
      
      // Pass 1: Set fixed height for Sessions if active
      let remainingH = totalAvailable;
      if (activeKeys.includes('sessions')) {
        laneHeightsActual['sessions'] = 40; // Fixed small height
        remainingH -= 40;
      }

      if (dynamicKeys.length > 0) {
        const laneTrackCounts = {};
        dynamicKeys.forEach(k => {
          laneTrackCounts[k] = Math.max(1, Number(laneData[k]?.numTracks) || 1);
        });
        const totalTracks = Object.values(laneTrackCounts).reduce((a, b) => a + b, 0);

        // Constraints for dynamic lanes
        const minH = 60;
        const minPct = 0.10;
        const maxPct = 0.60; // Allow more space for dynamic lanes since sessions is now small

        const laneMinH = Math.max(minH, Math.floor(totalAvailable * minPct));
        const laneMaxH = Math.floor(totalAvailable * maxPct);

        // pass 1b: Initialize dynamic lanes with minimum height
        dynamicKeys.forEach(k => {
          laneHeightsActual[k] = laneMinH;
          remainingH -= laneMinH;
        });

        // Pass 2: Proportional distribution for dynamic lanes
        if (remainingH > 0) {
          let unsettledKeys = [...dynamicKeys];
          while (unsettledKeys.length > 0 && remainingH > 0) {
            const unsettledTracks = unsettledKeys.reduce((sum, k) => sum + laneTrackCounts[k], 0);
            if (unsettledTracks === 0) break;

            let growthHappened = false;
            const nextUnsettled = [];

            for (const k of unsettledKeys) {
              const share = laneTrackCounts[k] / unsettledTracks;
              const idealExtra = Math.floor(remainingH * share);
              const currentH = laneHeightsActual[k];
              
              if (currentH < laneMaxH) {
                const actualExtra = Math.min(idealExtra, laneMaxH - currentH);
                if (actualExtra > 0) {
                  laneHeightsActual[k] += actualExtra;
                  remainingH -= actualExtra;
                  growthHappened = true;
                }
                if (laneHeightsActual[k] < laneMaxH) {
                  nextUnsettled.push(k);
                }
              }
            }
            if (!growthHappened) break;
            unsettledKeys = nextUnsettled;
          }
        }

        // Final Pass: Rounding error correction
        if (remainingH > 0) {
          const densestKey = dynamicKeys.reduce((a, b) => laneTrackCounts[a] > laneTrackCounts[b] ? a : b);
          laneHeightsActual[densestKey] += Math.floor(remainingH);
        }
      }
    }

    // Initial height calculation (Baseline)
    let currentY = 20; // Task 17.2: Top Row Buffer - Start lanes 20px down to ensure no overlap with header
    activeKeys.forEach((k) => {
      laneTops[k] = currentY;
      currentY += laneHeightsActual[k] + gapH;
    });

    // Recalculate laneTops with adjusted integer heights
    let recalcY = 20; // Maintain the 20px top buffer
    activeKeys.forEach((k) => {
      laneTops[k] = recalcY;
      recalcY += laneHeightsActual[k] + gapH;
    });
    currentY = recalcY;

    // 3. Final visual items mapping with posMap registration
    const lanes = [];
    activeKeys.forEach(k => {
      const ld = laneData[k];
      if (!ld) return; // Skip lanes with no data (e.g. srum_net null during loading)
      const actualH = laneHeightsActual[k];
      const topY = laneTops[k];
      let visualItems = ld.items;
      const oneSecPx = pxPerHour / 3600;

      if (k === 'sessions') {
        visualItems.events = ld.items.events.map(e => {
          const localY = actualH / 2;
          const fullName = e.event_name || e.type || 'Session Artifact';
          const evId = getForensicId('session', e.timestamp, 'timestamp', fullName);
          pm.set(evId, { x: e.x, lane: 'sessions', localY, y: topY + localY });
          return { ...e, y: localY, id: evId, name: fullName };
        });
        visualItems.bands = ld.items.bands; // Bands are already pre-calculated with x coords
      } else if (k === 'srum_app') {
        const scaledRH = Math.max(actualH, ld.innerH) / ld.numTracks;
        const bandH = Math.min(scaledRH * 0.7, 24);
        const pad = (scaledRH - bandH) / 2;
        visualItems = ld.items.map(a => {
          const x1_fg = safeTimeToX(a.start, s, pxPerHour);
          const x1_bg = safeTimeToX(a.bgStart, s, pxPerHour);
          const x2 = safeTimeToX(a.end, s, pxPerHour);
          const localY = a.track * scaledRH + pad + bandH / 2;
          const id = getForensicId('srum_app', a.timestamp, 'timestamp', getName(a));
          pm.set(id, { x: x1_fg, lane: k, localY, y: topY + localY });
          
          // Also register the start of the band so links can attach to the beginning
          if (a.start && a.start !== a.timestamp) {
            const startId = getForensicId('srum_app', a.start, 'timestamp', getName(a));
            pm.set(startId, { x: x1_fg, lane: k, localY, y: topY + localY });
          }
          
          return { ...a, id, x1_fg, x1_bg, x2, bw_fg: Math.max(oneSecPx, x2 - x1_fg, 4), bw_bg: Math.max(oneSecPx, x2 - x1_bg, 4), y: a.track * scaledRH, bandH, pad };
        });
      } else if (k === 'srum_net') {
        const scaledRH = Math.max(actualH, ld.innerH) / ld.numTracks;
        const netBandH = Math.min(scaledRH * 0.7, 22);
        const netPad = (scaledRH - netBandH) / 2;

        visualItems.netItems = ld.items.netItems.map(c => {
          const x1 = safeTimeToX(c.start, s, pxPerHour);
          const x2 = safeTimeToX(c.end, s, pxPerHour);
          const localY = c.track * scaledRH + netPad + netBandH / 2;
          const id = getForensicId('srum_net', c.timestamp, 'timestamp', getName(c));
          pm.set(id, { x: x1, lane: k, localY, y: topY + localY });
          
          // Register connection start
          if (c.start && c.start !== c.timestamp) {
            const startId = getForensicId('srum_net', c.start, 'timestamp', getName(c));
            pm.set(startId, { x: x1, lane: k, localY, y: topY + localY });
          }
          
          return { ...c, x1, x2, id, width: Math.max(oneSecPx, x2 - x1, 4), y: c.track * scaledRH + netPad, bandH: netBandH, pad: netPad };
        });

        visualItems.usageItems = ld.items.usageItems.map((u, i) => {
          const track = (typeof u.track === 'number') ? u.track : (i % ld.numTracks);
          const localY = track * scaledRH + netPad + netBandH / 2;
          const id = getForensicId('srum_usage', u.timestamp, 'timestamp', getName(u));
          pm.set(id, { x: u.x, lane: k, localY, y: topY + localY });
          return { ...u, id, y: track * scaledRH + netPad, pad: netPad, bandH: netBandH, r: 6 };
        });
      } else if (['mft_usn', 'execution', 'artifacts'].includes(k)) {
        const sorted = [...ld.items].sort((a, b) => a.x - b.x);
        // WARNING: Critical label positioning algorithm - Prevents overlapping labels in dense clusters
        // Uses array-based history to check last 5 items within 110px proximity window
        // DO NOT reduce LOOKBACK_COUNT below 5 - causes label overlaps in clusters of 3+ items
        // DO NOT change PROXIMITY_WINDOW without testing dense timeline regions
        // Algorithm alternates up/down positions, then uses 'right' with leader line for 3+ conflicts
        // FIX: Bug 4 - Label Positioning Proximity Check
        // Replaces single-link chain with array-based history to check last 5 items
        // Prevents label overlaps in dense clusters (3+ items within 110px)
        // Task 4.1: Replace single-link chain with array-based history
        const trackHistory = new Map(); // trackId -> array of last N items
        const PROXIMITY_WINDOW = 140;
        const LOOKBACK_COUNT = 5;

        visualItems = sorted.map((p, i) => {
          const localY = trackToY(p.track, Math.max(actualH, ld.innerH), ld.numTracks, 10);
          const fullName = getName(p);
          const t = getPrimaryTimestamp(p);
          const id = p.id || getForensicId(p.type, t, 'timestamp', fullName);
          const x = safeTimeToX(t, s, pxPerHour);

          let labelPos = 'up';
          let leaderLine = false;

          const history = trackHistory.get(p.track) || [];
          const proximityItems = history.filter(item => (x - item.x < PROXIMITY_WINDOW));

          if (proximityItems.length > 0) {
            if (proximityItems.length === 1) {
              labelPos = proximityItems[0].labelPos === 'up' ? 'down' : 'up';
            } else if (proximityItems.length === 2) {
              labelPos = 'up_high';
            } else if (proximityItems.length === 3) {
              labelPos = 'down_low';
            } else {
              labelPos = 'right';
              leaderLine = true;
            }
          }

          const item = { ...p, id, x, y: localY, name: fullName, labelPos, leaderLine };

          // Task 4.4: Update history management
          // Task 4.4.1: Append current item to history array
          // Task 4.4.2: Keep only last LOOKBACK_COUNT items using .slice(-LOOKBACK_COUNT)
          const updatedHistory = [...history, item].slice(-LOOKBACK_COUNT);
          trackHistory.set(p.track, updatedHistory);

          pm.set(id, { x, lane: k, localY, y: topY + localY });
          return item;
        });
      }
      lanes.push({ key: k, y: topY, actualHeight: actualH, items: visualItems, innerH: ld.innerH });
    });

    const finalTotalH = activeKeys.length > 0 ? (currentY - gapH) : 0;
    return { lanes, totalH: finalTotalH, powerOnBands: pOnBands, posMap: pm, totalWidth: width, activeKeys };
  }, [data, timeRange, pxPerHour, activeArtifacts, laneHeights, containerHeight]);

  const handleShowInTimeline = (item) => {
    setSelectedLaneModal(null);
    if (!containerRef.current || !item) return;

    const t = getPrimaryTimestamp(item);
    if (!t) return;

    const itemTime = new Date(t).getTime();
    const sTime = new Date(timeRange.start).getTime();
    const HOUR_MS = 3600000;
    const targetX = ((itemTime - sTime) / HOUR_MS) * pxPerHour;

    let targetY = 0;
    const fullName = getName(item);

    // Determine laneKey to generate the correct ID
    let laneKey = null;
    const laneKeyMap = {
      'SystemLogs': 'sessions', 'ApplicationLogs': 'sessions', 'SecurityLogs': 'sessions',
      'srum_app': 'srum_app', 'srum_net': 'srum_net', 'mft_usn': 'mft_usn',
      'prefetch': 'artifacts', 'bam': 'artifacts', 'lnk': 'artifacts', 'registry': 'artifacts',
      'shimcache': 'artifacts', 'recyclebin': 'artifacts', 'amcache': 'artifacts'
    };

    const typeStr = item.type || item.artifact_type || item.source_table || '';
    for (const [k, mappedLane] of Object.entries(laneKeyMap)) {
      if (typeStr.includes(k)) {
        laneKey = mappedLane; break;
      }
    }

    if (!laneKey) {
      if (typeStr === 'srum_application_usage') laneKey = 'srum_app';
      else if (typeStr === 'srum_network_data_usage') laneKey = 'srum_net';
      else if (typeStr === 'mft_usn_correlated') laneKey = 'mft_usn';
    }
    if (!laneKey) laneKey = item.lane || 'artifacts';

    // Forensic ID matching logic
    let key = item.id || getForensicId(item.type, t, 'timestamp', fullName);

    const pos = posMap.get(key);
    if (pos) {
      targetY = pos.y;
    } else {
      // Fallback: search for first occurrence of same type and name at this X
      for (const [k, v] of posMap.entries()) {
        if (Math.abs(v.x - targetX) < 1 && k.startsWith(item.type) && k.endsWith(normalizeForensicName(fullName))) {
          targetY = v.y;
          key = k; // Update key to the one found in map
          break;
        }
      }
    }

    if (key) {
      setSelectedEvent(item);
      // Wait for re-render before scrolling
      setTimeout(() => {
        const containerWidth = containerRef.current.clientWidth;
        containerRef.current.scrollTo({
          left: Math.max(0, targetX - containerWidth / 2),
          behavior: 'smooth'
        });
        
        // Vertical Scroll
        if (targetY > 0) {
          const laneEl = laneRefs.current[laneKey];
          if (laneEl) {
            const relY = targetY - laneTops[laneKey];
            laneEl.scrollTo({ top: relY - (laneEl.clientHeight / 2), behavior: 'smooth' });
          }
        }
      }, 50);
    }
  };

  // --- Auto-scroll and Linked Highlighting ---
  const linkedIds = useMemo(() => {
    if (!selectedEvent || !links) return new Set();
    const ids = new Set();
    (links || []).forEach(lk => {
      if (lk.source?.id === selectedEvent.id) ids.add(lk.target?.id);
      if (lk.target?.id === selectedEvent.id) ids.add(lk.source?.id);
    });
    return ids;
  }, [selectedEvent, links]);

  // --- Linked Highlights Navigation ---
  useEffect(() => {
    if (!selectedEvent || !containerRef.current) return;

    const ts = getPrimaryTimestamp(selectedEvent);
    if (!ts) return;
    const fullName = getName(selectedEvent);
    const id = selectedEvent.id || getForensicId(selectedEvent.type, ts, 'timestamp', fullName);
    
    // Center the Selected Event itself (ONLY VERTICALLY by default to prevent jumping)
    let selectedPos = posMap.get(id);
    if (!selectedPos) {
      for (const [k, v] of posMap.entries()) {
        if (k.startsWith(selectedEvent.type) && k.includes(String(ts)) && k.endsWith(normalizeForensicName(fullName))) {
          selectedPos = v;
          break;
        }
      }
    }

    if (selectedPos) {
      // Task: Remove Horizontal Scroll centering during simple selection to prevent jitter
      /* 
      const containerWidth = containerRef.current.clientWidth;
      containerRef.current.scrollTo({
        left: Math.max(0, selectedPos.x - containerWidth / 2),
        behavior: 'smooth'
      });
      */

    if (selectedPos) {
      // Automatic selection-driven scrolling has been disabled to ensure stability.
      // Views should only move during explicit link-navigation.
    }
    }

    // 2. Auto-scroll related linked lanes vertically to show correlations
    if (!links || links.length === 0) return;
    const filteredLinks = (links || []).filter(lk => lk.source?.id === selectedEvent.id || lk.target?.id === selectedEvent.id);
    if (filteredLinks.length === 0) return;

    const relatedEvents = filteredLinks.map(lk => lk.source?.id === selectedEvent.id ? lk.target : lk.source);
    const lanesToScroll = {};

    relatedEvents.forEach(ev => {
      const fName = getName(ev);
      const evTs = getPrimaryTimestamp(ev);
      let key = ev.id || getForensicId(ev.type, evTs, 'timestamp', fName);
      let pos = posMap.get(key);
      
      if (!pos) {
        for (const [k, v] of posMap.entries()) {
          if (k.startsWith(ev.type) && k.includes(String(evTs)) && k.endsWith(normalizeForensicName(fName))) {
            pos = v;
            break;
          }
        }
      }

      if (pos && pos.lane && pos.localY !== undefined && pos.lane !== selectedPos?.lane) {
        if (!lanesToScroll[pos.lane]) lanesToScroll[pos.lane] = pos.localY;
      }
    });

    Object.entries(lanesToScroll).forEach(([laneKey, targetY]) => {
      const laneEl = laneRefs.current[laneKey];
      if (laneEl) {
        const targetScrollTop = Math.max(0, targetY - (laneEl.clientHeight / 2));
        laneEl.scrollTo({ top: targetScrollTop, behavior: 'smooth' });
      }
    });
  }, [selectedEvent, links, posMap]);

  // --- Ticks and Labels ---
  // Task 5.2.3: All tick generation uses UTC methods for forensic accuracy
  const ticks = useMemo(() => {
    if (!timeRange.start || !timeRange.end) return [];
    // Task 5.2.2: getTime() returns UTC milliseconds - safe for calculations
    const sTime = new Date(timeRange.start).getTime();
    const eTime = new Date(timeRange.end).getTime();
    const span = (1200 / pxPerHour) * HOUR_MS;
    const ivs = [100, 200, 500, 1000, 5000, 10000, 20000, 30000, 60000, 5 * 60000, 15 * 60000, 30 * 60000, 1 * HOUR_MS, 2 * HOUR_MS, 4 * HOUR_MS, 6 * HOUR_MS, 12 * HOUR_MS, 24 * HOUR_MS, 7 * 24 * HOUR_MS];
    let iv = ivs.find(i => span / i <= 10) || ivs[ivs.length - 1];
    const first = Math.ceil(sTime / iv) * iv;
    const t = [];
    const pad = (n) => String(n).padStart(2, '0');
    const toFmt = (d, major) => {
      const Y = d.getUTCFullYear();
      const M = pad(d.getUTCMonth() + 1);
      const D = pad(d.getUTCDate());
      const h = pad(d.getUTCHours());
      const m = pad(d.getUTCMinutes());
      const s = pad(d.getUTCSeconds());
      if (major) return `${Y}-${M}-${D} ${h}:${m}:${s}`;
      return `${h}:${m}`;
    };

    for (let time = first; time <= eTime; time += iv) {
      const d = new Date(time);
      const isDayMajor = iv >= HOUR_MS * 24;
      const major = d.getUTCHours() === 0 && d.getUTCMinutes() === 0;
      t.push({ x: ((time - sTime) / HOUR_MS) * pxPerHour, label: toFmt(d, major || isDayMajor), major });
      if (t.length > 1000) break;
    }
    return t;
  }, [timeRange, pxPerHour]);

  // Removed early empty-state return here because it causes wrapperRef to be null during the initial 
  // mount, which breaks the useLayoutEffect loop and prevents containerHeight from ever updating.
  return (
    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', overflow: 'hidden', background: 'var(--bg-secondary)' }} ref={wrapperRef}>
      <div className="label-column" style={{ width: 160, flexShrink: 0, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-subtle)', zIndex: 10, overflow: 'hidden' }} ref={labelColumnRef}>
        <div style={{ position: 'relative', width: '100%', height: Math.max(totalH + 30, containerHeight) }}>
          <div className="time-axis-container" style={{ height: 30, borderBottom: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-primary)', position: 'sticky', top: 0, zIndex: 20 }} />
          <div style={{ position: 'absolute', top: 30, left: 0, right: 0, height: totalH }}>
            {lanes.map(lane => (
              <div key={lane.key} className="label-column__item"
                onDoubleClick={() => setSelectedLaneModal(lane.key)}
                style={{ position: 'absolute', top: lane.y, height: lane.actualHeight, width: '100%' }}
                title="Double-click to view all artifacts for this lane in the selected day">
                <div className="label-column__content" style={{ cursor: 'pointer' }}>
                  <div className="label-column__indicator" style={{ '--indicator-color': LANES_META.find(m => m.key === lane.key)?.color, background: LANES_META.find(m => m.key === lane.key)?.color }} />
                  <div className="label-column__info">
                    <div className="label-column__text">{LANES_META.find(m => m.key === lane.key)?.label}</div>
                    <div className="label-column__subtext">{LANES_META.find(m => m.key === lane.key)?.sub}</div>
                  </div>
                </div>
                <div className="label-column__resizer"
                  style={{ cursor: 'ns-resize' }}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const startY = e.clientY;
                    const startH = lane.actualHeight;
                    let raf = null;
                    const move = (m) => {
                      if (raf) cancelAnimationFrame(raf);
                      raf = requestAnimationFrame(() => {
                        const newH = Math.max(40, startH + (m.clientY - startY));
                        setLaneHeight(lane.key, newH);
                      });
                    };
                    const up = () => {
                      window.removeEventListener('mousemove', move);
                      window.removeEventListener('mouseup', up);
                      document.body.style.cursor = 'default';
                    };
                    document.body.style.cursor = 'ns-resize';
                    window.addEventListener('mousemove', move);
                    window.addEventListener('mouseup', up);
                  }}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="timeline-lanes-wrapper svg-scroll" ref={containerRef} onScroll={handleScroll} style={{ flex: 1, overflowY: 'auto', height: '100%', background: 'var(--bg-secondary)' }}>
        <div style={{ position: 'relative', width: totalWidth, height: Math.max(totalH + 30, containerHeight) }}>


          <svg style={{ position: 'absolute', top: 30, left: 0, pointerEvents: 'none', zIndex: 0 }} width={totalWidth} height={totalH}>
            {powerOnBands.map((b, i) => (<rect key={`pwb-${i}`} x={b.startX} y={0} width={b.width} height="100%" fill="var(--band-power-on)" opacity="0.04" />))}
            {ticks.map((t, i) => (<g key={`bg-tick-${i}`} transform={`translate(${t.x},0)`}><line y1="0" y2="100%" className="time-axis__tick-line" strokeOpacity={t.major ? 0.6 : 0.2} /></g>))}
            {lanes.map((lane) => (
              <line key={`lane-div-${lane.key}`}
                x1="0" y1={lane.y + lane.actualHeight}
                x2="100%" y2={lane.y + lane.actualHeight}
                className="lane-separator" />
            ))}
          </svg>

          <div className="lane-container time-axis-container" style={{ height: 30, position: 'sticky', top: 0, zIndex: 15 }}><svg width={totalWidth} height={30}><g className="time-axis" transform="translate(0, 20)">{ticks.map((t, i) => (<g key={`tick-${i}`} transform={`translate(${t.x},0)`}><line y1={0} y2={10} className="time-axis__tick-line" strokeOpacity={t.major ? 0.6 : 0.2} /><text y="-5" textAnchor="middle" className="time-axis__label">{t.label}</text></g>))}</g></svg></div>

          <svg style={{ position: 'absolute', top: 30, left: 0, pointerEvents: 'none', zIndex: 10 }} width={totalWidth} height={totalH}>
            <defs><clipPath id="mc"><rect x="0" y="0" width={totalWidth} height="100%" /></clipPath></defs>
            {/* Task 13.3: JIT Link Rendering - Filter links by viewport to reduce SVG pressure */}
            {(links || []).filter(lk => {
              const pa = posMap.get(lk.source?.id);
              const pb = posMap.get(lk.target?.id);
              if (!pa || !pb) return false;
              return (pa.x >= viewStart - 500 && pa.x <= viewEnd + 500) || 
                     (pb.x >= viewStart - 500 && pb.x <= viewEnd + 500);
            }).map((lk, i) => {
              const pa = posMap.get(lk.source?.id);
              const pb = posMap.get(lk.target?.id);
              if (!pa || !pb) return null;

              const sA = pa.lane ? (laneScroll[pa.lane] || 0) : 0;
              const sB = pb.lane ? (laneScroll[pb.lane] || 0) : 0;
              const ya = pa.y - sA;
              const yb = pb.y - sB;

              const laneA = lanes.find(l => l.key === pa.lane);
              if (laneA && (ya < laneA.y || ya > laneA.y + laneA.actualHeight)) return null;

              const actualLaneB = lanes.find(l => l.key === pb.lane);
              if (actualLaneB && (yb < actualLaneB.y || yb > actualLaneB.y + actualLaneB.actualHeight)) return null;

              const isSel = selectedEvent && (selectedEvent.id === lk.source?.id || selectedEvent.id === lk.target?.id);
              return <path key={`link-${lk.source?.id}-${lk.target?.id}`} d={`M${pa.x},${ya} C${(pa.x + pb.x) / 2},${ya} ${(pa.x + pb.x) / 2},${yb} ${pb.x},${yb}`} fill="none" stroke={isSel ? 'var(--accent-cyan)' : 'var(--accent-blue)'} strokeDasharray={isSel ? 'none' : '5,4'} strokeWidth={isSel ? 2.5 : 1.2} opacity={isSel ? 0.9 : 0.15} clipPath="url(#mc)" style={{ transition: 'all 0.1s', zIndex: isSel ? 100 : 1 }} />;
            })}
          </svg>

          <div style={{ position: 'absolute', zIndex: 5, height: totalH, overflow: 'hidden', top: 30, left: 0, right: 0 }}>
            <div style={{ position: 'relative', width: '100%', height: '100%' }}>
              {lanes.map(lane => (
                <div key={lane.key} className={`lane-container lane-${lane.key}`}
                  ref={el => laneRefs.current[lane.key] = el}
                  style={{ position: 'absolute', top: lane.y, height: lane.actualHeight, width: '100%', overflowY: 'auto', overflowX: 'hidden' }}
                  onScroll={e => handleLaneScroll(lane.key, e)}>

                  <svg width={totalWidth} height={Math.max(lane.actualHeight, lane.innerH)}>
                    <defs>
                      <linearGradient id="ongoing-fade" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" stopColor="currentColor" stopOpacity="0.6" />
                        <stop offset="100%" stopColor="currentColor" stopOpacity="0.1" />
                      </linearGradient>
                    </defs>
                    <rect className="lane-bg" width={totalWidth} height={Math.max(lane.actualHeight, lane.innerH)} />
                    {lane.key === 'sessions' && (
                      <g transform="translate(0, 0)">
                        {lane.items.bands.map((b, i) => {
                          const laneH = Math.max(lane.actualHeight, lane.innerH);
                          const isOngoing = !b.end;
                          const isLast = i === lane.items.bands.length - 1;
                          const { match: isSearchMatch } = searchMatch(b);

                          // If ongoing, cap at a fixed 30-minute block to indicate "Active starting here" 
                          // without stretching to infinity.
                          const FORENSIC_ACTIVE_MS = 30 * 60 * 1000;
                          const endTime = b.end ? b.end : new Date(new Date(b.start).getTime() + FORENSIC_ACTIVE_MS).toISOString();
                          const x2 = safeTimeToX(endTime, timeRange.start, pxPerHour);
                          const bw = Math.max(10, x2 - b.x1);

                          if (b.x1 > viewEnd + 500 || x2 < viewStart - 500) return null;

                          // User requested: Power and Login sessions to be GREEN
                          const isGreenType = b.type === 'power' || b.type === 'login';
                          const barColor = isGreenType ? 'var(--band-power-on)' : `var(--band-${b.type})`;

                          return (
                            <g key={`band-${i}`}
                              onClick={() => setSelectedEvent(b)}
                              onDoubleClick={() => handleEventDblClick(b)}
                              onMouseEnter={(e) => handleEventMouseEnter(e, b)}
                              onMouseLeave={() => setTooltip(null)}
                              style={{ cursor: 'pointer' }}>
                              <rect x={b.x1} y={(b.type === 'sleep' || b.type === 'lock') ? (laneH / 2 - 10) : 5}
                                width={bw} height={(b.type === 'sleep' || b.type === 'lock') ? 20 : Math.max(10, laneH - 10)}
                                rx="3"
                                fill={isSearchMatch ? 'var(--accent-orange)' : barColor}
                                className={`session-band session-band--${b.type} ${b.is_dirty ? 'session-band--dirty' : ''} ${isOngoing ? 'session-band--ongoing' : ''}`}
                                style={{ filter: isSearchMatch ? 'drop-shadow(0 0 8px var(--accent-orange))' : 'none' }}
                              />
                              {bw > 15 && (
                                <text x={b.x1 + 6} y={((b.type === 'sleep' || b.type === 'lock') ? (laneH / 2 - 10) : 5) + 12}
                                  fill={isSearchMatch ? '#000' : (isGreenType ? "#000" : "var(--text-accent)")}
                                  fontSize="7.5"
                                  style={{ fontWeight: 800, fontFamily: "var(--font-mono)", letterSpacing: '0.2px' }}
                                  pointerEvents="none">
                                  {isOngoing ? 'ACTIVE ' : ''}{b.type.toUpperCase().replace('_', ' ')}
                                  {b.user ? ` | USER: ${b.user}` : ''}
                                  {b.logon_type ? ` (${LOGON_TYPES[b.logon_type] || b.logon_type})` : ''}
                                </text>
                              )}
                            </g>
                          );
                        })}
                        {lane.items.events.map((ev, i) => {
                          if (ev.x < viewStart - 500 || ev.x > viewEnd + 500) return null;
                          const isSel = selectedEvent?.id === ev.id;
                          const isLinked = linkedIds.has(ev.id);
                          const lowT = ev.type?.toLowerCase() || '';
                          const baseColor = (lowT.includes('logon') || lowT.includes('start')) ? 'var(--accent-green)' : (lowT.includes('logoff') || lowT.includes('stop')) ? 'var(--dot-delete)' : 'var(--accent-blue)';
                          const color = ev.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : baseColor);
                          return (
                            <g key={`sev-${i}`}
                              className={`event-dot session-event ${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`}
                              onClick={() => setSelectedEvent(ev)}
                              onDoubleClick={() => handleEventDblClick(ev)}
                              onMouseEnter={(e) => handleEventMouseEnter(e, ev)}
                              onMouseLeave={() => setTooltip(null)}>
                              <circle cx={ev.x} cy={lane.actualHeight / 2} r={ev.isSearchMatch ? 4.5 : (isLinked ? 3.5 : 2.2)} fill={color} stroke={isSel ? '#FFF' : (ev.isSearchMatch ? 'var(--accent-orange)' : '#060B14')} strokeWidth={isSel ? 2 : (ev.isSearchMatch ? 1.5 : 1)} style={{ filter: ev.isSearchMatch ? 'drop-shadow(0 0 6px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 4px var(--accent-cyan))' : 'none') }} />
                            </g>
                          );
                        })}
                      </g>
                    )}
                    {lane.key === 'srum_app' && lane.items.map((a, i) => {
                      if (a.x2 < viewStart - 500 || a.x1_bg > viewEnd + 500) return null;
                      const isSel = selectedEvent?.id === a.id;
                      const isLinked = linkedIds.has(a.id);
                      const hasBgCycle = Number(a.background_cycle_time || 0) > 0;
                      return (
                        <g key={`srum-${i}`}
                          className={`srum-bar ${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`}
                          onClick={() => setSelectedEvent(a)}
                          onDoubleClick={() => handleEventDblClick(a)}
                          onMouseEnter={(e) => handleEventMouseEnter(e, a)}
                          onMouseLeave={() => setTooltip(null)}>
                          {hasBgCycle && (<rect x={a.x1_bg} y={a.y + a.pad + 2} width={a.bw_bg} height={Math.max(4, a.bandH - 4)} rx="2" fill="var(--srum-bg)" fillOpacity={isLinked ? 0.4 : "var(--srum-bg-fill-opacity)"} stroke="var(--srum-bg)" strokeOpacity="var(--srum-bg-stroke-opacity)" strokeWidth="1" strokeDasharray="3,1" />)}
                          <rect x={a.x1_fg} y={a.y + a.pad} width={a.bw_fg} height={a.bandH} rx="2" fill={a.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--srum-fg)")} fillOpacity="var(--srum-fg-fill-opacity)" stroke={a.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--srum-fg)")} strokeOpacity="var(--srum-fg-stroke-opacity)" strokeWidth={a.isSearchMatch ? 2.5 : (isLinked ? 2 : 1.5)} style={{ filter: a.isSearchMatch ? 'drop-shadow(0 0 6px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 3px var(--accent-cyan))' : 'none') }} />
                          <text x={a.x1_fg + 6} y={a.y + a.pad + 11} fill={a.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "var(--srum-fg)")} fontSize="10" style={{ fontWeight: (a.isSearchMatch || isLinked) ? 700 : 600, fontFamily: 'var(--font-mono)' }} pointerEvents="none">{normalizeForensicName(a.app_name || a.app_id)}</text>
                        </g>
                      );
                    })}
                    {lane.key === 'srum_net' && (
                      <>
                        {lane.items.netItems.map((c, i) => {
                          if (c.x2 < viewStart - 500 || c.x1 > viewEnd + 500) return null;
                          const isSel = selectedEvent?.id === c.id;
                          const isLinked = linkedIds.has(c.id);
                          const name = getForensicName(c);
                          const up = formatBytes(c.bytesSent || 0);
                          const down = formatBytes(c.bytesRecv || 0);                          return (
                            <g key={`net-${i}`}
                              className={`${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`}
                              onClick={() => setSelectedEvent(c)}
                              onDoubleClick={() => handleEventDblClick(c)}
                              onMouseEnter={(e) => handleEventMouseEnter(e, c)}
                              onMouseLeave={() => setTooltip(null)}
                              style={{ cursor: 'pointer' }}>
                              <rect x={c.x1} y={c.y} width={c.width} height={c.bandH} rx="4" fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : 'var(--accent-blue)')} fillOpacity={isSel ? 0.5 : (c.isSearchMatch ? 0.4 : (isLinked ? 0.3 : 0.2))} stroke={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--accent-blue)")} strokeWidth={isSel || isLinked || c.isSearchMatch ? 2 : 1} style={{ filter: c.isSearchMatch ? 'drop-shadow(0 0 6px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 5px var(--accent-cyan))' : 'none') }} />
                              <text x={c.x1 + 6} y={c.y + c.bandH / 2 + 4} fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#00FFFF")} fontSize="10" fontWeight={(c.isSearchMatch || isLinked) ? "700" : "600"} pointerEvents="none" style={{ textShadow: '1px 1px 2px #000' }}>
                                {name} <tspan fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#4ADE80")}>↓{down}</tspan> <tspan fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#60A5FA")}>↑{up}</tspan>
                              </text>
                            </g>
                          );
                        })}
                        {lane.items.usageItems.map((u, i) => {
                          if (u.x < viewStart - 500 || u.x > viewEnd + 1000) return null;
                          const isSel = selectedEvent?.id === u.id;
                          const isLinked = linkedIds.has(u.id);
                          const name = getForensicName(u);
                          const up = formatBytes(u.bytesSent || 0);
                          const down = formatBytes(u.bytesRecv || 0);                          return (
                            <g key={`usage-${i}`}
                              className={`${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`}
                              onClick={() => setSelectedEvent(u)}
                              onDoubleClick={() => handleEventDblClick(u)}
                              onMouseEnter={(e) => handleEventMouseEnter(e, u)}
                              onMouseLeave={() => setTooltip(null)}
                              style={{ cursor: 'pointer' }}>
                              <circle cx={u.x} cy={u.y + u.bandH / 2} r={u.isSearchMatch ? 11 : (isLinked ? 9 : 7)} fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--accent-cyan)")} stroke={u.isSearchMatch ? 'var(--accent-orange)' : "#FFF"} strokeWidth={isSel || isLinked || u.isSearchMatch ? 2 : 0} style={{ filter: u.isSearchMatch ? 'drop-shadow(0 0 10px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 8px var(--accent-cyan))' : 'none') }} />
                              <text x={u.x + 15} y={u.y + u.bandH / 2 + 4} fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#00FFFF")} fontSize="10" fontWeight={(u.isSearchMatch || isLinked) ? "700" : "600"} pointerEvents="none" style={{ textShadow: '1px 1px 2px #000' }}>
                                {name} <tspan fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#4ADE80")}>↓{down}</tspan> <tspan fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#60A5FA")}>↑{up}</tspan>
                              </text>
                            </g>
                          );
                        })}
                      </>
                    )}
                    {['mft_usn', 'execution', 'artifacts'].includes(lane.key) && lane.items.map((p, i) => {
                      // Standardized naming and identification
                      const fullName = getName(p);
                      
                      // Viewport filter (Broad buffer to prevent flickering)
                      if (p.x < viewStart - 1000 || p.x > viewEnd + 1000) return null;
                      
                      const isSel = selectedEvent?.id === p.id;
                      const isLinked = linkedIds.has(p.id);

                      // Resolve visual style (Color and Shape)
                      const forensicMap = {
                        'created': { color: 'var(--dot-create)', shape: 'triangle' },
                        'modified': { color: 'var(--dot-modify)', shape: 'square' },
                        'accessed': { color: 'var(--dot-access)', shape: 'circle' },
                        'executed': { color: 'var(--accent-cyan)', shape: 'diamond' },
                        'installed': { color: 'var(--accent-green)', shape: 'triangle_down' },
                        'linked': { color: 'var(--accent-blue)', shape: 'circle' },
                        'deleted': { color: 'var(--dot-delete)', shape: 'cross' },
                        // Manifest Direct Mapping
                        'prefetch': { color: '#f59e0b', shape: 'circle' },
                        'lnk': { color: '#3b82f6', shape: 'circle' },
                        'bam': { color: '#ef4444', shape: 'diamond' },
                        'userassist': { color: '#ef4444', shape: 'diamond' },
                        'runmru': { color: '#ef4444', shape: 'diamond' },
                        'wordwheelquery': { color: '#eab308', shape: 'circle' },
                        'shellbags': { color: '#10b981', shape: 'square' },
                        'network_list': { color: '#3b82f6', shape: 'diamond' },
                        'opensavemru': { color: '#10b981', shape: 'triangle' },
                        'lastsavemru': { color: '#10b981', shape: 'square' },
                        'amcache': { color: '#8b5cf6', shape: 'square' },
                        'shimcache': { color: '#ec4899', shape: 'circle' },
                        'recyclebin': { color: '#ef4444', shape: 'cross' }
                      };

                      const lookupType = (p.subType || p.tsType || '').toLowerCase();
                      const fm = forensicMap[lookupType] || {};
                      
                      const baseColor = p.op === 'create' ? 'var(--dot-create)' : p.op === 'delete' ? 'var(--dot-delete)' : (fm.color || (lane.key === 'artifacts' ? 'var(--accent-cyan)' : 'var(--accent-blue)'));
                      const textColor = p.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : baseColor);

                      const r = p.isSearchMatch ? 5 : (isLinked ? 3.5 : (p.prx || 2.2));
                      const dotStroke = isSel ? '#FFF' : (p.isSearchMatch ? 'var(--accent-orange)' : 'none');
                      const dotFilter = p.isSearchMatch ? 'drop-shadow(0 0 8px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 5px var(--accent-cyan))' : 'none');

                      // Dynamic label positioning
                      let labelY = p.y;
                      if (p.labelPos === 'right') labelY += 4;
                      else if (p.labelPos === 'down') labelY += 18;
                      else if (p.labelPos === 'down_low') labelY += 28;
                      else if (p.labelPos === 'up_high') labelY -= 22;
                      else labelY -= 11;

                      const labelX = (p.labelPos === 'right') ? p.x + 8 : p.x;

                      // Shape Selection
                      let dotShape;
                      const shapeType = fm.shape || (p.subType === 'run_time' ? 'diamond' : 'circle');

                      if (shapeType === 'diamond') {
                        dotShape = <polygon points={`${p.x},${p.y - r - 1} ${p.x + r + 1},${p.y} ${p.x},${p.y + r + 1} ${p.x - r - 1},${p.y}`} fill={textColor} stroke={dotStroke} strokeWidth="1.5" style={{ filter: dotFilter }} />;
                      } else if (shapeType === 'triangle') {
                        dotShape = <polygon points={`${p.x},${p.y - r - 1} ${p.x + r + 1},${p.y + r} ${p.x - r - 1},${p.y + r}`} fill={textColor} stroke={dotStroke} strokeWidth="1.5" style={{ filter: dotFilter }} />;
                      } else if (shapeType === 'square') {
                        dotShape = <rect x={p.x - r} y={p.y - r} width={r * 2} height={r * 2} fill={textColor} stroke={dotStroke} strokeWidth="1.5" style={{ filter: dotFilter }} />;
                      } else if (shapeType === 'triangle_down') {
                        dotShape = <polygon points={`${p.x - r - 1},${p.y - r} ${p.x + r + 1},${p.y - r} ${p.x},${p.y + r + 1}`} fill={textColor} stroke={dotStroke} strokeWidth="1.5" style={{ filter: dotFilter }} />;
                      } else if (shapeType === 'cross') {
                        const st = isSel ? '#FFF' : textColor;
                        dotShape = (
                          <g style={{ filter: dotFilter }}>
                            <circle cx={p.x} cy={p.y} r={r + 1} fill="transparent" stroke={st} strokeWidth="1" />
                            <line x1={p.x - r + 1} y1={p.y - r + 1} x2={p.x + r - 1} y2={p.y + r - 1} stroke={st} strokeWidth="1.5" />
                            <line x1={p.x + r - 1} y1={p.y - r + 1} x2={p.x - r + 1} y2={p.y + r - 1} stroke={st} strokeWidth="1.5" />
                          </g>
                        );
                      } else {
                        dotShape = <circle cx={p.x} cy={p.y} r={r} fill={textColor} stroke={dotStroke} strokeWidth="1.5" style={{ filter: dotFilter }} />;
                      }

                      return (
                        <g key={`evt-${lane.key}-${i}`}
                          className={`event-dot ${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`}
                          onClick={() => setSelectedEvent(p)}
                          onDoubleClick={() => handleEventDblClick(p)}
                          onMouseEnter={(e) => handleEventMouseEnter(e, p)}
                          onMouseLeave={() => setTooltip(null)}
                          style={{ cursor: 'pointer' }}>
                          {p.leaderLine && <line x1={p.x} y1={p.y} x2={labelX} y2={labelY} stroke={textColor} strokeWidth="0.5" strokeDasharray="2,2" opacity="0.5" />}
                          {dotShape}
                          <text x={labelX} y={labelY} fill={textColor} textAnchor={(p.labelPos === 'right') ? 'start' : 'middle'} fontSize="10" fontWeight={(p.isSearchMatch || isLinked) ? "700" : "600"} pointerEvents="none" style={{ textShadow: (p.isSearchMatch || isLinked) ? '0 0 3px #000' : 'none' }}>{fullName}</text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {selectedLaneModal && (
        <LaneDataModal
          laneKey={selectedLaneModal}
          laneTitle={LANES_META.find(m => m.key === selectedLaneModal)?.label || selectedLaneModal}
          data={data}
          timeRange={timeRange}
          initialSearch={searchTerm}
          onClose={() => setSelectedLaneModal(null)}
          callBridge={callBridge}
          onShowInTimeline={handleShowInTimeline}
        />
      )}
      {tooltip && <Tooltip data={tooltip} />}
    </div>
  );
}

const LOGON_TYPES = {
  '2': 'Interactive',
  '3': 'Network',
  '4': 'Batch',
  '5': 'Service',
  '7': 'Unlock',
  '8': 'NetworkCleartext',
  '9': 'NewCredentials',
  '10': 'RemoteInteractive',
  '11': 'CachedInteractive',
  '12': 'CachedRemoteInteractive',
  '13': 'CachedUnlock'
};

const SUBTYPE_LABELS = {
  'run_time': '◆ Historical Run',
  'created': '▲ Created',
  'modified': '■ Modified',
  'accessed': '● Accessed',
  'executed': '● Last Executed',
  'access': '● LNK Access',
  'installed': '▼ Installed',
  'linked': '● Linked',
  'driver_write': '■ Driver Write',
  'driver_stamp': '▲ Driver Timestamp',
  'shimcache': '■ Shimcache Mod',
  'deleted': '✖ Deleted',
};

function Tooltip({ data }) {
  const { ev, x, y } = data;
  const name = ev.event_name || ev.app_name || ev.original_filename || ev.filename || ev.fn_filename || ev.Source_Name || ev.name || ev.executable_name || ev.app_path || 'Event';
  const type = ev.type || ev.artifact_type || 'Forensic Artifact';
  const ts = formatTime(ev.timestamp || ev.start);
  const subTypeLabel = ev.subType ? SUBTYPE_LABELS[ev.subType] : null;

  const logonTypeDesc = ev.logon_type ? (LOGON_TYPES[ev.logon_type] || `Type ${ev.logon_type}`) : null;

  return (
    <div className="tooltip" style={{ left: x, top: y, transform: 'translate(-50%, -100%)' }}>
      <div className="tooltip__title">{name}</div>
      <div className="tooltip__row">
        <span className="tooltip__label">Time:</span>
        <span className="tooltip__value">{ts}</span>
      </div>
      <div className="tooltip__row">
        <span className="tooltip__label">Type:</span>
        <span className="tooltip__value">{type.replace('_', ' ').toUpperCase()}</span>
      </div>
      {subTypeLabel && (
        <div className="tooltip__row">
          <span className="tooltip__label">Timestamp:</span>
          <span className="tooltip__value" style={{ color: 'var(--accent-cyan)' }}>{subTypeLabel}</span>
        </div>
      )}
      {ev.user && (
        <div className="tooltip__row">
          <span className="tooltip__label">User:</span>
          <span className="tooltip__value" style={{ color: 'var(--accent-orange)' }}>{ev.user}</span>
        </div>
      )}
      {logonTypeDesc && (
        <div className="tooltip__row">
          <span className="tooltip__label">Logon:</span>
          <span className="tooltip__value" style={{ color: 'var(--accent-cyan)' }}>{logonTypeDesc}</span>
        </div>
      )}
      {ev.bytes_sent != null && (
        <div className="tooltip__row">
          <span className="tooltip__label">Upload:</span>
          <span className="tooltip__value" style={{ color: 'var(--accent-blue)' }}>{formatBytes(ev.bytes_sent)}</span>
        </div>
      )}
      {ev.bytes_received != null && (
        <div className="tooltip__row">
          <span className="tooltip__label">Download:</span>
          <span className="tooltip__value" style={{ color: 'var(--accent-green)' }}>{formatBytes(ev.bytes_received)}</span>
        </div>
      )}
      {ev.face_time != null && (
        <div className="tooltip__row">
          <span className="tooltip__label">Face Time:</span>
          <span className="tooltip__value">{formatDuration(ev.face_time)}</span>
        </div>
      )}
      {(ev.original_path || ev.file_path || ev.folder_path || ev.reconstructed_path || ev.path) && (
        <div style={{ fontSize: 9, color: '#9CA3AF', marginTop: 4, fontStyle: 'italic', wordBreak: 'break-all' }}>
          {ev.original_path || ev.file_path || ev.folder_path || ev.reconstructed_path || ev.path}
        </div>
      )}
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 6, borderTop: '1px solid var(--border-subtle)', paddingTop: 4 }}>
        Double-click for full details
      </div>
    </div>
  );
}

export default memo(TimelineView);
