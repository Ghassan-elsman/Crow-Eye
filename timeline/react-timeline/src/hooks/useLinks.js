import { useMemo } from 'react';
import { normalizeForensicName } from '../utils/formatters';

/**
 * Hook to compute cross-lane analytical links between different artifacts.
 */
export function useLinks(data, activeArtifacts, rangeStartIso, rangeEndIso) {
  return useMemo(() => {
    if (!data) return { events: [], links: [] };
    
    // Viewport bounds in ms
    const vStart = rangeStartIso ? new Date(rangeStartIso).getTime() : 0;
    const vEnd = rangeEndIso ? new Date(rangeEndIso).getTime() : Infinity;

    const events = [];

    // Helper to push valid timestamps with an identity
    const add = (sourceObj, type, timestamp, rawName, extra = {}) => {
      if (!timestamp) return;
      const t = new Date(timestamp).getTime();
      if (isNaN(t)) return;
      
      const normalized = normalizeForensicName(rawName);
      if (!normalized) return;

      // Type normalization to match TimelineView logic
      // IMPORTANT: For MFT artifacts, preserve 'mft_create' and 'mft_usn' as-is
      // This must match TimelineView.jsx posMap registration (lines 395-398)
      let normalizedType = type;
      if (type === 'mft_create' || type === 'mft_usn') normalizedType = type; // Keep as is, TimelineView uses p.type
      
      const id = `${normalizedType}-${t}-${normalized}`.toLowerCase();
      
      // Task 3.2 Step 1: Debug logging for ID generation
      console.log('[useLinks] Generated ID:', id);
      console.log('  type:', normalizedType, 'original:', type);
      console.log('  timestamp:', t, 'original:', timestamp);
      console.log('  normalized:', normalized, 'raw:', rawName);
      
      events.push({
        id,
        type: normalizedType,
        timestamp: t,
        normalized,
        rawName,
        source: sourceObj,
        ...extra
      });
    };

    const getName = (p) => {
      if (!p) return 'Unknown';
      return p.executable_name || p.fn_filename || p.filename || p.app_name || p.name || p.target_path || p.path || p.file_path || 'Unknown';
    };

    // ─── Extract from active lanes ───
    
    if (activeArtifacts.sessions && data.sessions) {
      (data.sessions.events || []).forEach(r => add(r, 'session', r.timestamp, r.event_name || r.type || 'Session Artifact'));
    }

    if (activeArtifacts.srum_app && data.srum_app) {
      data.srum_app.forEach(r => add(r, 'srum_app', r.timestamp, getName(r)));
    }
    
    if (activeArtifacts.srum_net && data.srum_net) {
      (data.srum_net.connectivity || []).forEach(r => add(r, 'srum_net', r.timestamp, getName(r)));
      (data.srum_net.data_usage || []).forEach(r => add(r, 'srum_net', r.timestamp, getName(r)));
    }
    
    if (activeArtifacts.mft_usn && data.mft_usn) {
      data.mft_usn.forEach(r => {
        if (r.si_creation_time) add(r, 'mft_create', r.si_creation_time, getName(r));
        if (r.usn_timestamp) add(r, 'mft_usn', r.usn_timestamp, getName(r));
      });
    }

    if (activeArtifacts.prefetch && data.prefetch) {
      data.prefetch.forEach(r => add(r, 'prefetch', r.last_executed, getName(r)));
    }

    if (activeArtifacts.bam && data.bam) {
      data.bam.forEach(r => add(r, 'bam', r.last_execution, getName(r)));
    }

    if (activeArtifacts.lnk && data.lnk) {
      data.lnk.forEach(r => {
        if (r.Time_Access) add(r, 'lnk', r.Time_Access, getName(r));
      });
    }

    if (activeArtifacts.amcache && data.amcache) {
      (data.amcache.application_files || []).forEach(r => add(r, 'amcache', r.link_date, getName(r)));
    }

    if (activeArtifacts.registry && data.registry) {
      (data.registry.open_save_mru || []).forEach(r => add(r, 'registry', r.access_date, getName(r)));
      (data.registry.last_save_mru || []).forEach(r => add(r, 'registry', r.access_date, getName(r)));
      (data.registry.recent_docs || []).forEach(r => add(r, 'registry', r.access_date, getName(r)));
      (data.registry.user_assist || []).forEach(r => add(r, 'registry', r.access_date, getName(r)));
      (data.registry.shellbags || []).forEach(r => {
        if (r.accessed_date) add(r, 'registry', r.accessed_date, getName(r));
        if (r.modified_date) add(r, 'registry', r.modified_date, getName(r));
      });
    }

    if (activeArtifacts.shimcache && data.shimcache) {
      data.shimcache.forEach(r => add(r, 'shimcache', r.last_modified, getName(r)));
    }
    
    if (activeArtifacts.recyclebin && data.recyclebin) {
      data.recyclebin.forEach(r => add(r, 'recyclebin', r.deletion_time, getName(r)));
    }

    // ─── Compute Links ───
    const byDayAndName = {};
    events.forEach(ev => {
      if (!ev.normalized) return;
      // Case-insensitive baseName splitting for deep file analysis
      const baseName = ev.normalized.split('\\').pop().split('/').pop().toLowerCase();
      if (baseName.length < 3 && ev.type !== 'session') return; 
      
      const d = new Date(ev.timestamp);
      const dayKey = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
      
      const groupKey = `${dayKey}-${baseName}`;

      if (!byDayAndName[groupKey]) byDayAndName[groupKey] = [];
      byDayAndName[groupKey].push(ev);
    });

    const links = [];
    const CORRELATION_WINDOW_MS = 20000; // 20-second fuzzy window for execution latency

    Object.values(byDayAndName).forEach(group => {
      // Group by artifact type to compare across lanes
      const byType = {};
      group.forEach(ev => {
        if (!byType[ev.type]) byType[ev.type] = [];
        byType[ev.type].push(ev);
      });

      const types = Object.keys(byType);
      if (types.length < 2) return;

      // Cross-lane correlation
      for (let i = 0; i < types.length - 1; i++) {
        for (let j = i + 1; j < types.length; j++) {
          const laneA = byType[types[i]];
          const laneB = byType[types[j]];

          laneA.forEach(evA => {
            let linksForEvA = 0; // Prevent link overload per node
            
            laneB.forEach(evB => {
              if (linksForEvA >= 5) return; // Cap at 5 links per lane pair per node to prevent SVG freeze
              
              // 1. Time proximity check (fuzzy match)
              if (Math.abs(evA.timestamp - evB.timestamp) <= CORRELATION_WINDOW_MS) {
                // 2. Performance Culling is now done in TimelineView during render
                links.push({ a: evA, b: evB });
                linksForEvA++;
              }
            });
          });
        }
      }
    });

    return { events, links };
  }, [data, activeArtifacts, rangeStartIso, rangeEndIso]);
}
