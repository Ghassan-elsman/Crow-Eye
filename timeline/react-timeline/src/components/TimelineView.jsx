/**
 * TimelineView — Main 24H detail view rendering individual events as SVG.
 * Each forensic data source is a horizontal lane with dots/bars/shapes.
 */
import { memo, useMemo, useRef, useState, useEffect, useLayoutEffect } from 'react';
import { normalizeForensicName, formatBytes, formatTime, formatCycleTime, formatDuration } from '../utils/formatters';
import LaneDataModal from './LaneDataModal';

/** trackAllocator logic (now integrated) */
function allocateTracks(items, minGapMs = 20000) {
  if (!items || items.length === 0) return [];
  const sorted = [...items].sort((a, b) => {
    const tA = new Date(a.start || a.timestamp).getTime();
    const tB = new Date(b.start || b.timestamp).getTime();
    return tA - tB;
  });
  const trackEnds = [];
  for (const item of sorted) {
    const startMs = new Date(item.start || item.timestamp).getTime();
    const endMs = item.end ? new Date(item.end).getTime() : startMs + minGapMs;
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
  { key: 'sessions',  label: 'Sessions / Power',   sub: 'Login, Logout, Power, Sleep', color: 'var(--lane-sessions)' },
  { key: 'srum_app',  label: 'SRUM App Usage',      sub: 'FG/BG Cycles, Face Time',    color: 'var(--lane-srum-app)' },
  { key: 'srum_net',  label: 'SRUM Network',         sub: 'Connectivity, Data Usage',   color: 'var(--lane-srum-net)' },
  { key: 'mft_usn',   label: 'MFT / USN',            sub: 'File Create, Modify, Delete', color: 'var(--lane-mft-usn)' },
  { key: 'execution', label: 'Execution Artifacts',  sub: 'Prefetch, LNK, BAM, Registry', color: 'var(--lane-execution)' },
  { key: 'cache',     label: 'Cache & RecycleBin',   sub: 'AmCache, ShimCache, Bin',    color: 'var(--lane-cache)' },
];

/** Safe timeToX that won't crash on bad timestamps */
function safeTimeToX(iso, rangeStart, pxPerHour) {
  if (!iso || !rangeStart) return 0;
  const t = new Date(iso).getTime();
  const s = new Date(rangeStart).getTime();
  if (isNaN(t) || isNaN(s)) return 0;
  return ((t - s) / (1000 * 60 * 60)) * pxPerHour;
}

function filterValid(items) {
  if (!items || !Array.isArray(items)) return [];
  return items.filter(item => {
    if (!item.timestamp) return false;
    return !isNaN(new Date(item.timestamp).getTime());
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
    const type = (item.type || item.artifact_type || '').toLowerCase();
    const isMatch = name.includes(lowerTerm) || type.includes(lowerTerm) || eventName.includes(lowerTerm);
    return { match: isMatch, hide: false }; // We don't hide items, just highlight them
  };

  const scrollFrame = useRef(0);
  const vScrollFrame = useRef(0);
  const laneScrollFrames = useRef({});

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

  const getName = (p) => {
    if (!p) return 'Unknown';
    return p.executable_name || p.fn_filename || p.filename || p.app_name || p.name || p.target_path || p.path || p.file_path || 'Unknown';
  };

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
    const ob = new ResizeObserver(entries => {
      const rect = entries[0].contentRect;
      const offsetH = wrapperRef.current?.offsetHeight || 0;
      const viewportH = wrapperRef.current
        ? Math.floor(window.innerHeight - wrapperRef.current.getBoundingClientRect().top)
        : 0;
      const h = Math.max(Math.floor(rect.height), offsetH, viewportH);
      if (h > 100) setContainerHeight(h);
    });
    if (wrapperRef.current) ob.observe(wrapperRef.current);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      window.removeEventListener('resize', updateH);
      ob.disconnect();
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

  // --- Core Layout Memo ---
  const { lanes, totalH, powerOnBands, posMap, totalWidth } = useMemo(() => {
    const pm = new Map();
    if (!timeRange.start || !timeRange.end) return { lanes: [], totalH: 600, powerOnBands: [], posMap: pm, totalWidth: 800 };

    const s = timeRange.start;
    const e = timeRange.end;
    const sTime = new Date(s).getTime();
    const eTime = new Date(e).getTime();
    const width = Math.max(800, ((eTime - sTime) / HOUR_MS) * pxPerHour);
    const powerOnBands = [];

    const inBounds = (ts) => {
      if (!ts) return false;
      const t = new Date(ts).getTime();
      return t >= sTime && t <= eTime;
    };

    const activeKeys = ['sessions', 'srum_app', 'srum_net', 'mft_usn', 'execution', 'cache'].filter(k => {
        let isActive = true;
        if (activeArtifacts[k] === false && k !== 'execution' && k !== 'cache') isActive = false;
        if (k === 'execution' && !activeArtifacts.prefetch && !activeArtifacts.lnk && !activeArtifacts.bam && !activeArtifacts.registry) isActive = false;
        if (k === 'cache' && !activeArtifacts.amcache && !activeArtifacts.shimcache && !activeArtifacts.recyclebin) isActive = false;
        
        // Final check: Does it have data in the CURRENT day view?
        if (isActive) {
          if (k === 'sessions') return (data.sessions?.events || []).some(e => inBounds(e.timestamp)) || (data.sessions?.bands || []).some(b => inBounds(b.start) || inBounds(b.end));
          if (k === 'srum_app') return (data.srum_app || []).some(a => inBounds(a.timestamp));
          if (k === 'srum_net') return (data.srum_net?.connectivity || []).some(c => inBounds(c.timestamp)) || (data.srum_net?.data_usage || []).some(u => inBounds(u.timestamp));
          if (k === 'mft_usn') return (data.mft_usn || []).some(r => inBounds(r.si_creation_time) || inBounds(r.usn_timestamp));
          if (k === 'execution') {
            return (data.prefetch || []).some(p => inBounds(p.last_executed)) || (data.bam || []).some(p => inBounds(p.last_execution)) || (data.lnk || []).some(p => inBounds(p.Time_Access)) || (data.registry?.open_save_mru || []).some(p => inBounds(p.access_date)) || (data.registry?.last_save_mru || []).some(p => inBounds(p.access_date)) || (data.registry?.recent_docs || []).some(p => inBounds(p.access_date)) || (data.registry?.user_assist || []).some(p => inBounds(p.access_date)) || (data.registry?.shellbags || []).some(p => inBounds(p.accessed_date) || inBounds(p.modified_date));
          }
          if (k === 'cache') {
            return (data.shimcache || []).some(p => inBounds(p.last_modified)) || (data.recyclebin || []).some(p => inBounds(p.deletion_time)) || (data.amcache?.application_files || []).some(p => inBounds(p.link_date));
          }
        }
        
        return isActive;
    });

    const minGap = 20000;
    const laneData = {};
    
    // 1. Data Processing
    if (activeKeys.includes('sessions')) {
        const sBands = (data.sessions?.bands || []).map(b => {
          const x1 = safeTimeToX(b.start, s, pxPerHour);
          const x2 = safeTimeToX(b.end, s, pxPerHour);
          if (b.type === 'power') powerOnBands.push({ startX: Math.max(0, x1), width: Math.max(2, x2 - Math.max(0, x1)) });
          return { ...b, x1, x2, bw: Math.max(2, x2 - x1) };
        }).filter(b => b.x1 > -100000 && b.x2 > -100000);

        const sEvents = (data.sessions?.events || []).map(e => {
          const x = safeTimeToX(e.timestamp, s, pxPerHour);
          const { match } = searchMatch(e);
          return { ...e, x, isSearchMatch: match };
        }).filter(e => e.x > -1000 && e.x < width + 1000);

        laneData['sessions'] = { items: { bands: sBands, events: sEvents }, numTracks: 1, innerH: 40 };
    }

    if (activeKeys.includes('srum_app')) {
      const apps = filterValid(data.srum_app).map((a, idx, arr) => {
        const ts = new Date(a.timestamp).getTime();
        const faceMs = a.face_time ? Number(a.face_time) * 1000 : 0;
        const { match } = searchMatch(a);
        
        // FIX: Bug 8 - SRUM Background Time Extrapolation Overlap
        // Use actual background_cycle_time instead of fixed 1-hour
        const bgCycleMs = a.background_cycle_time ? Number(a.background_cycle_time) * 1000 : 0;
        let bgStart = ts - Math.max(20000, bgCycleMs);
        let fgStart = ts - Math.max(20000, faceMs);

        // FIX: Bug 8 (continued) - Add overlap detection with previous events for the same app
        if (idx > 0) {
          for (let i = idx - 1; i >= 0; i--) {
            const prev = arr[i];
            if (prev.app_name === a.app_name) {
              const prevEnd = new Date(prev.timestamp).getTime();
              // Adjust start times if overlap detected
              if (bgStart < prevEnd) bgStart = prevEnd;
              if (fgStart < prevEnd) fgStart = prevEnd;
              break; // Only check the most recent previous event for same app
            }
          }
        }

        // Both are anchored to ts (the reporting timestamp).
        // They grow backwards according to their specific metrics.
        return { ...a, start: fgStart, end: ts, bgStart, type: 'srum_app', isSearchMatch: match };      });
      // FIX: Bug 8 (continued) - Use smaller minGap for SRUM bands to reduce excessive track allocation
      const tracked = allocateTracks(apps, 10000);
      const numTracks = Math.max(1, tracked.reduce((max, a) => Math.max(max, a.track), 0) + 1);
      laneData['srum_app'] = { items: tracked, numTracks, innerH: numTracks * 40, rH: 40 };
    }

    if (activeKeys.includes('srum_net') && data.srum_net) {
      const nets = filterValid((data.srum_net.connectivity || [])).map((c, idx, arr) => {
         const ts = new Date(c.timestamp).getTime();
         const bytesSent = parseInt(c.bytes_sent || 0);
         const bytesRecv = parseInt(c.bytes_received || 0);
         const durMs = Math.max(20000, (parseFloat(c.connected_time) || 0) * 1000);
         const { match } = searchMatch(c);
         
         // SRUM Network Forensic Alignment Fix:
         // 1. Project backwards from timestamp (record creation time)
         let start = ts - durMs;
         
         // 2. Add overlap detection for the same app to prevent "merged" bars
         if (idx > 0) {
           for (let i = idx - 1; i >= 0; i--) {
             const prev = arr[i];
             if ((prev.app_name || prev.app_id) === (c.app_name || c.app_id)) {
               const prevEnd = new Date(prev.timestamp).getTime();
               if (start < prevEnd) {
                 start = prevEnd;
               }
               break; 
             }
           }
         }
         
         return { ...c, start, end: ts, type: 'srum_net', bytesSent, bytesRecv, isSearchMatch: match };
      });
      // FIX: SRUM Network Bar Overlap
      // Use allocateTracks with 15s gap instead of forcing all connections for an app into one row.
      const trackedNets = allocateTracks(nets, 15000);
      
      const usageItemsList = (data.srum_net.data_usage || []).map(u => {
          const ts = new Date(u.timestamp).getTime();
          const bytesSent = parseInt(u.bytes_sent || 0);
          const bytesRecv = parseInt(u.bytes_received || 0);
          const x = safeTimeToX(u.timestamp, s, pxPerHour);
          const { match } = searchMatch(u);
          return { ...u, x, timestamp: ts, type: 'srum_net_usage', bytesSent, bytesRecv, isSearchMatch: match };
      });
      // Allocate tracks for usage dots as well to prevent vertical stacking
      const trackedUsage = allocateTracks(usageItemsList, 20000);

      const numNetTracks = trackedNets.reduce((max, c) => Math.max(max, c.track), 0) + 1;
      const numUsageTracks = trackedUsage.reduce((max, u) => Math.max(max, u.track), 0) + 1;
      const numTracks = Math.max(1, numNetTracks, numUsageTracks);
      
      laneData['srum_net'] = { 
          items: { netItems: trackedNets, usageItems: trackedUsage }, 
          numTracks, 
          innerH: Math.max(60, numTracks * 40) 
      };
    }

    if (activeKeys.includes('mft_usn')) {
      const pts = [];
      (data.mft_usn || []).forEach(r => {
        const { match: m1 } = searchMatch({...r, timestamp: r.si_creation_time, type: 'mft_create'});
        if (r.si_creation_time) pts.push({...r, timestamp: r.si_creation_time, type: 'mft_create', isSearchMatch: m1});
        const { match: m2 } = searchMatch({...r, timestamp: r.usn_timestamp, type: 'mft_usn'});
        if (r.usn_timestamp) pts.push({...r, timestamp: r.usn_timestamp, type: 'mft_usn', isSearchMatch: m2});
      });
      // INCREASED: minGapMs to 120000 (2 minutes) for MFT/USN to force more tracks in dense regions
      const tracked = allocateTracks(filterValid(pts), 20000);
      const numTracks = Math.max(1, tracked.reduce((max, p) => Math.max(max, p.track), 0) + 1);
      laneData['mft_usn'] = { items: tracked, numTracks, innerH: 30 + numTracks * 35 };
    }

    if (activeKeys.includes('execution')) {
      const pts = [];
      if (data.prefetch) data.prefetch.forEach(p => {
        const { match } = searchMatch({...p, timestamp: p.last_executed, type: 'prefetch'});
        pts.push({...p, timestamp: p.last_executed, type: 'prefetch', isSearchMatch: match});
      });
      if (data.bam) data.bam.forEach(p => {
        const { match } = searchMatch({...p, timestamp: p.last_execution, type: 'bam'});
        pts.push({...p, timestamp: p.last_execution, type: 'bam', isSearchMatch: match});
      });
      if (data.lnk) data.lnk.forEach(p => { 
        if (p.Time_Access) {
          const { match } = searchMatch({...p, timestamp: p.Time_Access, type: 'lnk'});
          pts.push({...p, timestamp: p.Time_Access, type: 'lnk', isSearchMatch: match}); 
        }
      });
      if (data.registry) {
          (data.registry.open_save_mru || []).forEach(p => {
            const { match } = searchMatch({...p, timestamp: p.access_date, type: 'registry'});
            pts.push({...p, timestamp: p.access_date, type: 'registry', isSearchMatch: match});
          });
          (data.registry.last_save_mru || []).forEach(p => {
            const { match } = searchMatch({...p, timestamp: p.access_date, type: 'registry'});
            pts.push({...p, timestamp: p.access_date, type: 'registry', isSearchMatch: match});
          });
          (data.registry.recent_docs || []).forEach(p => {
            const { match } = searchMatch({...p, timestamp: p.access_date, type: 'registry'});
            pts.push({...p, timestamp: p.access_date, type: 'registry', isSearchMatch: match});
          });
          (data.registry.user_assist || []).forEach(p => {
            const { match } = searchMatch({...p, timestamp: p.access_date, type: 'registry'});
            pts.push({...p, timestamp: p.access_date, type: 'registry', isSearchMatch: match});
          });
          (data.registry.shellbags || []).forEach(p => {
              if (p.accessed_date) {
                const { match } = searchMatch({...p, timestamp: p.accessed_date, type: 'registry'});
                pts.push({...p, timestamp: p.accessed_date, type: 'registry', isSearchMatch: match});
              }
              if (p.modified_date) {
                const { match } = searchMatch({...p, timestamp: p.modified_date, type: 'registry'});
                pts.push({...p, timestamp: p.modified_date, type: 'registry', isSearchMatch: match});
              }
          });
      }
      const tracked = allocateTracks(filterValid(pts), 20000);
      const numTracks = Math.max(1, tracked.reduce((max, p) => Math.max(p.track, max), 0) + 1);
      laneData['execution'] = { items: tracked, numTracks, innerH: 30 + numTracks * 35 };
    }

    if (activeKeys.includes('cache')) {
      const pts = [];
      if (data.shimcache) data.shimcache.forEach(p => {
        const { match } = searchMatch({...p, timestamp: p.last_modified, type: 'shimcache'});
        pts.push({...p, timestamp: p.last_modified, type: 'shimcache', isSearchMatch: match});
      });
      if (data.recyclebin) data.recyclebin.forEach(p => {
        const { match } = searchMatch({...p, timestamp: p.deletion_time, type: 'recyclebin'});
        pts.push({...p, timestamp: p.deletion_time, type: 'recyclebin', isSearchMatch: match});
      });
      if (data.amcache) (data.amcache.application_files || []).forEach(p => {
        const { match } = searchMatch({...p, timestamp: p.link_date, type: 'amcache'});
        pts.push({...p, timestamp: p.link_date, type: 'amcache', isSearchMatch: match});
      });
      const tracked = allocateTracks(filterValid(pts), 20000);
      const numTracks = Math.max(1, tracked.reduce((max, p) => Math.max(p.track, max), 0) + 1);
      laneData['cache'] = { items: tracked, numTracks, innerH: 30 + numTracks * 35 };
    }

    // 2. Vertical Layout Distribution
    const availableTotalH = Math.max(400, containerHeight - 30);
    const gapH = 2;
    const totalGapsH = (activeKeys.length - 1) * gapH;
    const poolForLanes = availableTotalH - totalGapsH;
    
    let totalLockedH = 0;
    let totalTracksForFlex = 0;
    
    activeKeys.forEach(k => {
      if (laneHeights[k]) {
        totalLockedH += laneHeights[k];
      } else {
        totalTracksForFlex += (laneData[k]?.numTracks || 1);
      }
    });
    
    const poolForFlexible = Math.max(0, poolForLanes - totalLockedH);
    let unassignedKeys = activeKeys.filter(k => !laneHeights[k]);
    const laneHeightsActual = {};
    const laneTops = {};

    activeKeys.forEach(k => {
        if (laneHeights[k]) laneHeightsActual[k] = laneHeights[k];
    });

    // Iteratively assign heights and clamp. If a flex lane clamps to 48, subtract 48 from pool and re-distribute.
    let remainingFlexiblePool = poolForFlexible;
    let resolved = false;

    while (!resolved && unassignedKeys.length > 0) {
        resolved = true;
        let flexTracks = unassignedKeys.reduce((sum, k) => sum + (laneData[k]?.numTracks || 1), 0);
        if (flexTracks === 0) break;
        
        for (let i = 0; i < unassignedKeys.length; i++) {
            const k = unassignedKeys[i];
            const tracks = laneData[k]?.numTracks || 1;
            const actualH = Math.round(remainingFlexiblePool * (tracks / flexTracks));
            
            if (actualH < 48) {
                // Clamped to minimum. Remove from flexible pool.
                laneHeightsActual[k] = 48;
                remainingFlexiblePool -= 48;
                unassignedKeys.splice(i, 1);
                resolved = false;
                break; // Restart the loop with updated pool and unassignedKeys
            }
        }
    }

    // Assign remaining flexible lanes
    if (unassignedKeys.length > 0) {
        let flexTracks = unassignedKeys.reduce((sum, k) => sum + (laneData[k]?.numTracks || 1), 0);
        unassignedKeys.forEach(k => {
            const tracks = laneData[k]?.numTracks || 1;
            laneHeightsActual[k] = Math.max(48, Math.round(remainingFlexiblePool * (tracks / flexTracks)));
        });
    }

    let currentY = 0;
    activeKeys.forEach(k => {
        laneTops[k] = currentY;
        currentY += laneHeightsActual[k] + gapH;
    });
    // WARNING: Critical layout algorithm - Final height adjustment distributes remaining vertical space
    // DO NOT modify laneTops[k] in this loop - only modify laneHeightsActual[k]
    // Modifying laneTops causes cumulative downward shifts where each lane is pushed down by the sum
    // of all previous lanes' extra height, causing the last lanes to overflow beyond container boundary
    // Final check: if total height is still less than available, distribute remaining space proportionally to all active lanes based on their tracks
    if (currentY < availableTotalH && activeKeys.length > 0) {
        let diff = Math.floor(availableTotalH - (currentY - gapH));
        if (diff > 0) {
            const totalTracks = activeKeys.reduce((sum, k) => sum + (laneData[k]?.numTracks || 1), 0);
            activeKeys.forEach((k) => {
                const tracks = laneData[k]?.numTracks || 1;
                const weight = tracks / totalTracks;
                const extra = Math.floor(diff * weight);
                laneHeightsActual[k] += extra;
            });
            
            let currentTotal = activeKeys.reduce((sum, k) => sum + laneHeightsActual[k], 0) + (activeKeys.length - 1) * gapH;
            let finalDiff = availableTotalH - currentTotal;
            for (let i = 0; i < Math.floor(finalDiff) && i < activeKeys.length; i++) {
                laneHeightsActual[activeKeys[i]] += 1;
            }
        }
    }

    // Recalculate laneTops with adjusted integer heights
    let recalcY = 0;
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
          const ts = new Date(e.timestamp).getTime();
          const fullName = e.event_name || e.type || 'Session Artifact';
          const norm = normalizeForensicName(fullName);
          const evId = `session-${ts}-${norm}`.toLowerCase();
          pm.set(evId, { x: e.x, lane: 'sessions', localY, y: topY + localY });
          return { ...e, y: localY, id: evId, name: fullName };
        });
      } else if (k === 'srum_app') {
        const scaledRH = Math.max(actualH, ld.innerH) / ld.numTracks;
        const bandH = Math.min(scaledRH * 0.7, 24);
        const pad = (scaledRH - bandH) / 2;
        visualItems = ld.items.map(a => {
          const x1_fg = safeTimeToX(a.start, s, pxPerHour);
          const x1_bg = safeTimeToX(a.bgStart, s, pxPerHour);
          const x2 = safeTimeToX(a.end, s, pxPerHour);
          const localY = a.track * scaledRH + pad + bandH/2;
          const ts = new Date(a.timestamp).getTime();
          const id = `srum_app-${ts}-${normalizeForensicName(getName(a))}`.toLowerCase();
          pm.set(id, { x: x1_fg, lane: k, localY, y: topY + localY });
          return { ...a, id, x1_fg, x1_bg, x2, bw_fg: Math.max(oneSecPx, x2 - x1_fg, 4), bw_bg: Math.max(oneSecPx, x2 - x1_bg, 4), y: a.track * scaledRH, bandH, pad };
        });
      } else if (k === 'srum_net') {
        const scaledRH = Math.max(actualH, ld.innerH) / ld.numTracks;
        const netBandH = Math.min(scaledRH * 0.7, 22);
        const netPad = (scaledRH - netBandH) / 2;
        
        visualItems.netItems = ld.items.netItems.map(c => {
          const x1 = safeTimeToX(c.start, s, pxPerHour);
          const x2 = safeTimeToX(c.end, s, pxPerHour);
          const localY = c.track * scaledRH + netPad + netBandH/2;
          const ts = new Date(c.timestamp).getTime();
          const norm = normalizeForensicName(getName(c));
          const id = `srum_net-${ts}-${norm}`.toLowerCase();
          pm.set(id, { x: x1, lane: k, localY, y: topY + localY });
          return { ...c, x1, x2, id, width: Math.max(oneSecPx, x2 - x1, 4), y: c.track * scaledRH + netPad, bandH: netBandH, pad: netPad };
        });
        
        visualItems.usageItems = ld.items.usageItems.map((u, i) => {
          const track = (typeof u.track === 'number') ? u.track : (i % ld.numTracks);
          const localY = track * scaledRH + netPad + netBandH/2;
          const ts = new Date(u.timestamp).getTime();
          const norm = normalizeForensicName(getName(u));
          const id = `srum_net-${ts}-${norm}`.toLowerCase();
          pm.set(id, { x: u.x, lane: k, localY, y: topY + localY });
          return { ...u, id, y: track * scaledRH + netPad, pad: netPad, bandH: netBandH, r: 6 };
        });
      } else if (['mft_usn', 'execution', 'cache'].includes(k)) {
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
          const ts = new Date(p.timestamp).getTime();
          const fullName = getName(p);
          const norm = normalizeForensicName(fullName);
          const id = `${p.type}-${ts}-${norm}`.toLowerCase();
          const x = safeTimeToX(p.timestamp, s, pxPerHour);
          
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

          const item = { ...p, id, x, y: localY, name: fullName.split('\\').pop().split('/').pop(), labelPos, leaderLine };
          
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
    return { lanes, totalH: finalTotalH, powerOnBands, posMap: pm, totalWidth: width };
  }, [data, timeRange, pxPerHour, activeArtifacts, laneHeights, containerHeight]);

  const handleShowInTimeline = (item) => {
    setSelectedLaneModal(null);
    if (!containerRef.current || !item) return;

    const t = item.timestamp || item.start || item.EventTimestampUTC || item.link_date || item.last_executed || item.creation_time || item.deletion_time;
    if (!t) return;

    const itemTime = new Date(t).getTime();
    const sTime = new Date(timeRange.start).getTime();
    const HOUR_MS = 3600000;
    const targetX = ((itemTime - sTime) / HOUR_MS) * pxPerHour;

    let targetY = 0;
    const norm = item.normalized || normalizeForensicName(item.name || item.app_name || item.filename || item.executable_name || 'unknown');
    
    // Determine laneKey to generate the correct ID
    let laneKey = null;
    const laneKeyMap = {
      'SystemLogs': 'sessions', 'ApplicationLogs': 'sessions', 'SecurityLogs': 'sessions',
      'srum_app': 'srum_app', 'srum_net': 'srum_net', 'mft_usn': 'mft_usn',
      'prefetch': 'execution', 'bam': 'execution', 'lnk': 'execution', 'registry': 'execution',
      'shimcache': 'cache', 'recyclebin': 'cache', 'amcache': 'cache'
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

    let key = '';
    if (laneKey === 'sessions') {
      key = `session-${itemTime}-${norm}`.toLowerCase();
    } else if (laneKey === 'srum_app') {
      key = `srum_app-${itemTime}-${norm}`.toLowerCase();
    } else if (laneKey === 'srum_net') {
      key = `srum_net-${itemTime}-${norm}`.toLowerCase();
    } else {
      const prefix = item.type || item.artifact_type || (typeStr === 'mft_usn_correlated' ? 'mft_usn' : 'unknown');
      key = `${prefix}-${itemTime}-${norm}`.toLowerCase();
    }

    const pos = posMap.get(key);

    if (pos && pos.y) {
      targetY = pos.y;
    } else {
      if (laneKey && lanes) {
        const foundLane = lanes.find(l => l.key === laneKey);
        if (foundLane) targetY = foundLane.y;
      }
    }

    // Set the selected event so it highlights visually in the UI
    setSelectedEvent({ ...item, id: key });

    const containerWidth = containerRef.current.clientWidth;
    const containerHeight = containerRef.current.clientHeight;

    containerRef.current.scrollTo({
      left: Math.max(0, targetX - containerWidth / 2),
      top: Math.max(0, targetY - (containerHeight / 2)),
      behavior: 'smooth'
    });
  };

  // Task 3.2 Step 1: Debug logging for link rendering
  useEffect(() => {
    console.log('[Links] Total links generated by useLinks:', links?.length || 0);
    console.log('[Links] posMap size:', posMap?.size || 0);
    console.log('[Links] First 5 posMap entries:', Array.from(posMap?.entries() || []).slice(0, 5));
    
    if (links && links.length > 0) {
      console.log('[Links] First 5 links:');
      links.slice(0, 5).forEach((lk, i) => {
        const keyA = lk.a.id.toLowerCase();
        const keyB = lk.b.id.toLowerCase();
        const pa = posMap.get(keyA);
        const pb = posMap.get(keyB);
        console.log(`  Link ${i}: ${keyA} -> ${keyB}`);
        console.log(`    posMap.get(${keyA}):`, pa);
        console.log(`    posMap.get(${keyB}):`, pb);
        console.log(`    Will render:`, !!(pa && pb && typeof pa.x === 'number' && typeof pb.x === 'number'));
      });
    }
  }, [links, posMap]);

  // --- Auto-scroll and Linked Highlighting ---
  const linkedIds = useMemo(() => {
    if (!selectedEvent || !links) return new Set();
    const ids = new Set();
    links.forEach(lk => {
      if (lk.a.id === selectedEvent.id) ids.add(lk.b.id);
      if (lk.b.id === selectedEvent.id) ids.add(lk.a.id);
    });
    return ids;
  }, [selectedEvent, links]);

  useEffect(() => {
    if (!selectedEvent || !links || links.length === 0 || !posMap) return;
    const relatedLinks = links.filter(lk => lk.a.id === selectedEvent.id || lk.b.id === selectedEvent.id);
    if (relatedLinks.length === 0) return;
    
    const relatedEvents = relatedLinks.map(lk => lk.a.id === selectedEvent.id ? lk.b : lk.a);
    const lanesToScroll = {};
    
    relatedEvents.forEach(ev => {
      const norm = ev.normalized || normalizeForensicName(ev.name || ev.app_name || 'unknown');
      const key = `${ev.type}-${ev.timestamp}-${norm}`.toLowerCase();
      const pos = posMap.get(key);
      if (pos && pos.lane && pos.localY !== undefined) {
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
    for (let time = first; time <= eTime; time += iv) {
      const d = new Date(time);
      const isDayMajor = iv >= HOUR_MS * 24;
      // Task 5.2.2: All formatting uses timeZone: 'UTC' explicitly
      const opts = isDayMajor ? { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' } : { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' };
      let label = d.toLocaleDateString('en-GB', opts);
      if (!isDayMajor && label.includes('/')) label = d.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' });
      // Task 5.2.2: getUTCHours() and getUTCMinutes() ensure UTC-based major tick detection
      t.push({ x: ((time - sTime) / HOUR_MS) * pxPerHour, label, major: d.getUTCHours() === 0 && d.getUTCMinutes() === 0 });
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
            {powerOnBands.map((b, i) => ( <rect key={`pwb-${i}`} x={b.startX} y={0} width={b.width} height="100%" fill="var(--band-power-on)" opacity="0.04" /> ))}
            {ticks.map((t, i) => ( <g key={`bg-tick-${i}`} transform={`translate(${t.x},0)`}><line y1="0" y2="100%" className="time-axis__tick-line" strokeOpacity={t.major ? 0.6 : 0.2} /></g> ))}
            {lanes.map((lane) => ( 
              <line key={`lane-div-${lane.key}`} 
                    x1="0" y1={lane.y + lane.actualHeight} 
                    x2="100%" y2={lane.y + lane.actualHeight} 
                    className="lane-separator" /> 
            ))}
          </svg>

          <div className="lane-container time-axis-container" style={{ height: 30, position: 'sticky', top: 0, zIndex: 15 }}><svg width={totalWidth} height={30}><g className="time-axis" transform="translate(0, 20)">{ticks.map((t, i) => ( <g key={`tick-${i}`} transform={`translate(${t.x},0)`}><line y1={0} y2={10} className="time-axis__tick-line" strokeOpacity={t.major ? 0.6 : 0.2} /><text y="-5" textAnchor="middle" className="time-axis__label">{t.label}</text></g> ))}</g></svg></div>

          <svg style={{ position: 'absolute', top: 30, left: 0, pointerEvents: 'none', zIndex: 10 }} width={totalWidth} height={totalH}>
            <defs><clipPath id="mc"><rect x="0" y="0" width={totalWidth} height="100%" /></clipPath></defs>
            {links.map((lk, i) => {
               const keyA = lk.a.id.toLowerCase();
               const keyB = lk.b.id.toLowerCase();
               const pa = posMap.get(keyA);
               const pb = posMap.get(keyB);

               if (!pa || !pb || typeof pa.x !== 'number' || typeof pb.x !== 'number') return null;

               const sA = pa.lane ? (laneScroll[pa.lane] || 0) : 0;
               const sB = pb.lane ? (laneScroll[pb.lane] || 0) : 0;
               const ya = pa.y - sA; 
               const yb = pb.y - sB;

               // FIX: Prevent links pointing to "empty spaces" when individual lanes scroll vertically.
               // We look up the lane's visual boundaries and if the adjusted Y coordinate falls
               // outside of it, we do not render the link because the endpoint dot is clipped off-screen.
               const laneA = lanes.find(l => l.key === pa.lane);
               if (laneA && (ya < laneA.y || ya > laneA.y + laneA.actualHeight)) return null;

               const laneB = lanes.find(l => l.key === pb.lane);
               if (laneB && (yb < laneB.y || yb > laneB.y + laneB.actualHeight)) return null;

               // WARNING: Critical viewport culling logic - Aggressive culling for performance
               const CULL_BUFFER = 2000;
               if (pa.x < viewStart - CULL_BUFFER || pa.x > viewEnd + CULL_BUFFER || 
                   pb.x < viewStart - CULL_BUFFER || pb.x > viewEnd + CULL_BUFFER) return null;
               const isSel = selectedEvent && (selectedEvent.id === lk.a.id || selectedEvent.id === lk.b.id);

               return <path key={`link-${i}`} d={`M${pa.x},${ya} C${(pa.x+pb.x)/2},${ya} ${(pa.x+pb.x)/2},${yb} ${pb.x},${yb}`} fill="none" stroke={isSel ? 'var(--accent-cyan)' : 'var(--accent-blue)'} strokeDasharray={isSel ? 'none' : '5,4'} strokeWidth={isSel ? 2.5 : 1.2} opacity={isSel ? 0.9 : 0.15} clipPath="url(#mc)" style={{ transition: 'all 0.2s', zIndex: isSel ? 100 : 1 }} />;
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
                      <foreignObject x="0" y="0" width="100%" height="20">
                        <div className="session-legend" xmlns="http://www.w3.org/1999/xhtml">
                          <div className="session-legend__item"><div className="session-legend__swatch" style={{background: 'var(--band-power-on)'}}/>Power / Login</div>
                          <div className="session-legend__item"><div className="session-legend__swatch" style={{background: 'var(--band-lock)'}}/>Lock</div>
                          <div className="session-legend__item"><div className="session-legend__swatch" style={{background: 'var(--band-sleep)'}}/>Sleep</div>
                          <div className="session-legend__item" style={{marginLeft: 'auto'}}><div className="session-legend__swatch" style={{background: 'var(--accent-orange)', border: '1px dashed #fff'}}/>Ongoing</div>
                        </div>
                      </foreignObject>
                    )}
                    {lane.key === 'sessions' && (
                      <>
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
                               style={{cursor: 'pointer'}}>
                              <rect x={b.x1} y={(b.type === 'sleep' || b.type === 'lock') ? (laneH/2 - 10) : 5} 
                                    width={bw} height={(b.type === 'sleep' || b.type === 'lock') ? 20 : Math.max(10, laneH - 10)} 
                                    rx="3" 
                                    fill={isSearchMatch ? 'var(--accent-orange)' : barColor}
                                    className={`session-band session-band--${b.type} ${b.is_dirty ? 'session-band--dirty' : ''} ${isOngoing ? 'session-band--ongoing' : ''}`} 
                                    style={{ filter: isSearchMatch ? 'drop-shadow(0 0 8px var(--accent-orange))' : 'none' }}
                              />
                              {bw > 15 && (
                                <text x={b.x1 + 6} y={((b.type === 'sleep' || b.type === 'lock') ? (laneH/2 - 10) : 5) + 12} 
                                      fill={isSearchMatch ? '#000' : (isGreenType ? "#000" : "var(--text-accent)")} 
                                      fontSize="7.5" 
                                      style={{fontWeight: 800, fontFamily: "var(--font-mono)", letterSpacing: '0.2px'}} 
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
                              <circle cx={ev.x} cy={lane.actualHeight / 2} r={ev.isSearchMatch ? 4.5 : (isLinked ? 3.5 : 2.2)} fill={color} stroke={isSel ? '#FFF' : (ev.isSearchMatch ? 'var(--accent-orange)' : '#060B14')} strokeWidth={isSel ? 2 : (ev.isSearchMatch ? 1.5 : 1)} style={{filter: ev.isSearchMatch ? 'drop-shadow(0 0 6px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 4px var(--accent-cyan))' : 'none')}} />
                            </g>
                          );
                        })}
                      </>
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
                          {hasBgCycle && ( <rect x={a.x1_bg} y={a.y + a.pad + 2} width={a.bw_bg} height={Math.max(4, a.bandH - 4)} rx="2" fill="var(--srum-bg)" fillOpacity={isLinked ? 0.4 : "var(--srum-bg-fill-opacity)"} stroke="var(--srum-bg)" strokeOpacity="var(--srum-bg-stroke-opacity)" strokeWidth="1" strokeDasharray="3,1" /> )}
                          <rect x={a.x1_fg} y={a.y + a.pad} width={a.bw_fg} height={a.bandH} rx="2" fill={a.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--srum-fg)")} fillOpacity="var(--srum-fg-fill-opacity)" stroke={a.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--srum-fg)")} strokeOpacity="var(--srum-fg-stroke-opacity)" strokeWidth={a.isSearchMatch ? 2.5 : (isLinked ? 2 : 1.5)} style={{filter: a.isSearchMatch ? 'drop-shadow(0 0 6px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 3px var(--accent-cyan))' : 'none')}} />
                          <text x={a.x1_fg + 6} y={a.y + a.pad + 11} fill={a.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "var(--srum-fg)")} fontSize="10" style={{fontWeight: (a.isSearchMatch || isLinked) ? 700 : 600, fontFamily: 'var(--font-mono)'}} pointerEvents="none">{normalizeForensicName(a.app_name || a.app_id)}</text>
                        </g>
                      );                    })}
                    {lane.key === 'srum_net' && (
                      <>
                        {lane.items.netItems.map((c, i) => {
                          if (c.x2 < viewStart - 500 || c.x1 > viewEnd + 500) return null;
                          const isSel = selectedEvent?.id === c.id;
                          const isLinked = linkedIds.has(c.id);
                          const name = normalizeForensicName(c.app_name || c.app_id || 'Network');
                          const up = formatBytes(c.bytesSent || 0);
                          const down = formatBytes(c.bytesRecv || 0);
                          return (
                            <g key={`net-${i}`} 
                               className={`${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`} 
                               onClick={() => setSelectedEvent(c)} 
                               onDoubleClick={() => handleEventDblClick(c)}
                               onMouseEnter={(e) => handleEventMouseEnter(e, c)}
                               onMouseLeave={() => setTooltip(null)}
                               style={{cursor: 'pointer'}}>
                              <rect x={c.x1} y={c.y} width={c.width} height={c.bandH} rx="4" fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : 'var(--accent-blue)')} fillOpacity={isSel ? 0.5 : (c.isSearchMatch ? 0.4 : (isLinked ? 0.3 : 0.2))} stroke={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--accent-blue)")} strokeWidth={isSel || isLinked || c.isSearchMatch ? 2 : 1} style={{filter: c.isSearchMatch ? 'drop-shadow(0 0 6px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 5px var(--accent-cyan))' : 'none')}} />
                              <text x={c.x1 + 6} y={c.y + c.bandH/2 + 4} fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#00FFFF")} fontSize="10" fontWeight={(c.isSearchMatch || isLinked) ? "700" : "600"} pointerEvents="none" style={{textShadow: '1px 1px 2px #000'}}>
                                 {name} <tspan fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#4ADE80")}>↓{down}</tspan> <tspan fill={c.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#60A5FA")}>↑{up}</tspan>
                              </text>
                            </g>
                          );
                        })}
                        {lane.items.usageItems.map((u, i) => {
                           if (u.x < viewStart - 500 || u.x > viewEnd + 1000) return null;
                           const isSel = selectedEvent?.id === u.id;
                           const isLinked = linkedIds.has(u.id);
                           const name = normalizeForensicName(u.app_name || u.app_id || 'Network');
                           const up = formatBytes(u.bytesSent || 0);
                           const down = formatBytes(u.bytesRecv || 0);
                           return (
                             <g key={`usage-${i}`} 
                                className={`${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`} 
                                onClick={() => setSelectedEvent(u)} 
                                onDoubleClick={() => handleEventDblClick(u)}
                                onMouseEnter={(e) => handleEventMouseEnter(e, u)}
                                onMouseLeave={() => setTooltip(null)}
                                style={{cursor: 'pointer'}}>
                               <circle cx={u.x} cy={u.y + u.bandH/2} r={u.isSearchMatch ? 11 : (isLinked ? 9 : 7)} fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : "var(--accent-cyan)")} stroke={u.isSearchMatch ? 'var(--accent-orange)' : "#FFF"} strokeWidth={isSel || isLinked || u.isSearchMatch ? 2 : 0} style={{filter: u.isSearchMatch ? 'drop-shadow(0 0 10px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 8px var(--accent-cyan))' : 'none')}} />
                               <text x={u.x + 15} y={u.y + u.bandH/2 + 4} fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#00FFFF")} fontSize="10" fontWeight={(u.isSearchMatch || isLinked) ? "700" : "600"} pointerEvents="none" style={{textShadow: '1px 1px 2px #000'}}>
                                  {name} <tspan fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#4ADE80")}>↓{down}</tspan> <tspan fill={u.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? '#FFF' : "#60A5FA")}>↑{up}</tspan>
                               </text>
                             </g>
                           );
                        })}
                      </>
                    )}
                    {['mft_usn', 'execution', 'cache'].includes(lane.key) && lane.items.map((p, i) => {
                      if (p.x < viewStart - 500 || p.x > viewEnd + 500) return null;
                      const isSel = selectedEvent?.id === p.id;
                      const isLinked = linkedIds.has(p.id);
                      const baseColor = p.op === 'create' ? 'var(--dot-create)' : p.op === 'delete' ? 'var(--dot-delete)' : (lane.key === 'execution' ? 'var(--accent-cyan)' : 'var(--accent-blue)');
                      const textColor = p.isSearchMatch ? 'var(--accent-orange)' : (isLinked ? 'var(--accent-cyan)' : baseColor);
                      const isRight = p.labelPos === 'right';
                      const labelX = isRight ? p.x + 10 : p.x;

                      let labelY = p.y;
                      if (p.labelPos === 'right') labelY += 4;
                      else if (p.labelPos === 'down') labelY += 18;
                      else if (p.labelPos === 'down_low') labelY += 28;
                      else if (p.labelPos === 'up_high') labelY -= 22;
                      else labelY -= 11; // default 'up'

                      return (
                        <g key={`evt-${lane.key}-${i}`}
                           className={`event-dot ${isSel ? 'event-dot--selected' : ''} ${isLinked ? 'event-dot--linked' : ''}`}
                           onClick={() => setSelectedEvent(p)}
                           onDoubleClick={() => handleEventDblClick(p)}
                           onMouseEnter={(e) => handleEventMouseEnter(e, p)}
                           onMouseLeave={() => setTooltip(null)}
                           style={{cursor: 'pointer'}}>
                          {p.leaderLine && <line x1={p.x} y1={p.y} x2={labelX} y2={labelY} stroke={textColor} strokeWidth="0.5" strokeDasharray="2,2" opacity="0.5" />}
                          <circle cx={p.x} cy={p.y} r={p.isSearchMatch ? 5 : (isLinked ? 3.5 : (p.prx || 2.2))} fill={textColor} stroke={isSel ? '#FFF' : (p.isSearchMatch ? 'var(--accent-orange)' : 'none')} strokeWidth="1.5" style={{filter: p.isSearchMatch ? 'drop-shadow(0 0 8px var(--accent-orange))' : (isLinked ? 'drop-shadow(0 0 5px var(--accent-cyan))' : 'none')}} />
                          <text x={labelX} y={labelY} fill={textColor} textAnchor={isRight ? 'start' : 'middle'} fontSize="10" fontWeight={(p.isSearchMatch || isLinked) ? "700" : "600"} pointerEvents="none" style={{textShadow: (p.isSearchMatch || isLinked) ? '0 0 3px #000' : 'none'}}>{p.name || 'Unknown'}</text>
                        </g>
                      );                    })}
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

function Tooltip({ data }) {
  const { ev, x, y } = data;
  const name = ev.event_name || ev.app_name || ev.fn_filename || ev.filename || ev.Source_Name || ev.name || ev.executable_name || 'Event';
  const type = ev.type || ev.artifact_type || 'Forensic Artifact';
  const ts = formatTime(ev.timestamp || ev.start);
  
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
      {ev.user && (
        <div className="tooltip__row">
          <span className="tooltip__label">User:</span>
          <span className="tooltip__value" style={{color: 'var(--accent-orange)'}}>{ev.user}</span>
        </div>
      )}
      {logonTypeDesc && (
        <div className="tooltip__row">
          <span className="tooltip__label">Logon:</span>
          <span className="tooltip__value" style={{color: 'var(--accent-cyan)'}}>{logonTypeDesc}</span>
        </div>
      )}
      {ev.bytes_sent != null && (
        <div className="tooltip__row">
          <span className="tooltip__label">Upload:</span>
          <span className="tooltip__value" style={{color: 'var(--accent-blue)'}}>{formatBytes(ev.bytes_sent)}</span>
        </div>
      )}
      {ev.bytes_received != null && (
        <div className="tooltip__row">
          <span className="tooltip__label">Download:</span>
          <span className="tooltip__value" style={{color: 'var(--accent-green)'}}>{formatBytes(ev.bytes_received)}</span>
        </div>
      )}
      {ev.face_time != null && (
        <div className="tooltip__row">
          <span className="tooltip__label">Face Time:</span>
          <span className="tooltip__value">{formatDuration(ev.face_time)}</span>
        </div>
      )}
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 6, borderTop: '1px solid var(--border-subtle)', paddingTop: 4 }}>
        Double-click for full details
      </div>
    </div>
  );
}

export default memo(TimelineView);
