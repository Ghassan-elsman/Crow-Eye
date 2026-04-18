import { useMemo } from 'react';
import { normalizeForensicName, getForensicName, getForensicTimestamps, getForensicId, cleanForensicDate } from '../utils/formatters';
import { heuristicFlatten } from '../utils/dataUtils';

/**
 * Hook to compute cross-lane analytical links between different artifacts.
 */
export function useLinks(data, activeArtifacts, rangeStartIso, rangeEndIso) {
  return useMemo(() => {
    if (!data) return { events: [], links: [] };

    const events = [];

    // Helper to push valid timestamps with an identity
    const add = (sourceObj, type, timestamp, rawName, field = '', extra = {}) => {
      if (!timestamp) return;
      
      const cleaned = cleanForensicDate(timestamp);
      const t = new Date(cleaned).getTime();
      if (isNaN(t)) return;

      const normalized = normalizeForensicName(rawName);
      if (!normalized) return;

      // Type normalization to match TimelineView logic
      const id = getForensicId(type, timestamp, field, rawName);

      events.push({
        id,
        type,
        timestamp: t,
        normalized,
        rawName,
        source: sourceObj,
        ...extra
      });
    };

    // ─── Extraction Helper ───
    const processItems = (items, type) => {
      heuristicFlatten(items).forEach(item => {
        const name = getForensicName(item);
        const times = getForensicTimestamps(item);
        times.forEach(ts => add(item, type, ts.time, name, ts.field));
      });
    };

    // ─── Extract from active lanes ───

    if (activeArtifacts.sessions && data.sessions) {
      heuristicFlatten(data.sessions.events).forEach(r => add(r, 'session', r.timestamp, r.event_name || r.type || 'Session Artifact', 'timestamp'));
    }

    if (activeArtifacts.srum_app && data.srum_app) {
      heuristicFlatten(data.srum_app).forEach(item => {
        const name = getForensicName(item);
        const ts = new Date(item.timestamp).getTime();
        // Link by recording time
        add(item, 'srum_app', item.timestamp, name, 'timestamp');
        
        // Link by calculated start times (Face Time / Background Cycle)
        // Note: We use 'timestamp' as the field here because the visual plotter generates 
        // the SRUM ID using the primary timestamp even for the start of the band.
        const bgCycleMs = item.background_cycle_time ? Number(item.background_cycle_time) * 1000 : 0;
        const fgCycleMs = item.face_time ? Number(item.face_time) * 1000 : 0;
        if (bgCycleMs > 5000) add(item, 'srum_app', new Date(ts - bgCycleMs).toISOString(), name, 'timestamp');
        if (fgCycleMs > 5000) add(item, 'srum_app', new Date(ts - fgCycleMs).toISOString(), name, 'timestamp');
      });
    }

    if (activeArtifacts.srum_net && data.srum_net) {
      heuristicFlatten(data.srum_net.connectivity).forEach(item => {
        const name = getForensicName(item);
        const ts = new Date(item.timestamp).getTime();
        // Link by recording time
        add(item, 'srum_net', item.timestamp, name, 'timestamp');
        
        // Link by calculated connection start
        const durMs = (parseFloat(item.connected_time) || 0) * 1000;
        if (durMs > 5000) add(item, 'srum_net', new Date(ts - durMs).toISOString(), name, 'timestamp');
      });
      processItems(data.srum_net.data_usage, 'srum_usage');
    }

    if (activeArtifacts.mft_usn && data.mft_usn) {
      heuristicFlatten(data.mft_usn).forEach(r => {
        const name = getForensicName(r);
        // Task 19.1: Match MFT/USN ID fields exactly with TimelineView plotter
        if (r.si_creation_time) add(r, 'mft_create', r.si_creation_time, name, 'si_creation_time');
        if (r.usn_timestamp) add(r, 'mft_usn', r.usn_timestamp, name, 'usn_timestamp');
      });
    }

    if (activeArtifacts.prefetch && data.prefetch) processItems(data.prefetch, 'prefetch');
    if (activeArtifacts.bam && data.bam) processItems(data.bam, 'bam');
    if (activeArtifacts.bam && data.dam) processItems(data.dam, 'dam');
    if (activeArtifacts.lnk && data.lnk) processItems(data.lnk, 'lnk');
    if (activeArtifacts.shimcache && data.shimcache) processItems(data.shimcache, 'shimcache');
    if (activeArtifacts.recyclebin && data.recyclebin) processItems(data.recyclebin, 'recyclebin');

    if (activeArtifacts.amcache && data.amcache) {
      const am = data.amcache;
      processItems(am.application_files, 'amcache');
      processItems(am.applications, 'amcache');
      processItems(am.drivers, 'amcache');
    }

    if (activeArtifacts.registry && data.registry) {
      Object.keys(data.registry).forEach(table => {
        processItems(data.registry[table], 'registry');
      });
    }

    // Process "Salvaged" items for links too
    Object.keys(data).forEach(key => {
      if (!['sessions', 'srum_app', 'srum_net', 'mft_usn', 'prefetch', 'bam', 'dam', 'lnk', 'shimcache', 'recyclebin', 'amcache', 'registry', 'aggregated'].includes(key)) {
        processItems(data[key], `salvaged_${key}`);
      }
    });

    // ─── Compute Links ───
    const byDayAndName = {};
    events.forEach(ev => {
      if (!ev.normalized || ev.normalized === 'unknown') return;
      
      const baseName = ev.normalized;
      
      // Safety check: Prevent link spaghetti for very short generic names
      if (baseName.length < 3 && ev.type !== 'session') return;

      const d = new Date(ev.timestamp);
      // Re-introduce dayKey to restrict linking within a single day
      const dayKey = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
      const groupKey = `${dayKey}-${baseName}`;

      if (!byDayAndName[groupKey]) byDayAndName[groupKey] = [];
      byDayAndName[groupKey].push(ev);
    });

    const links = [];
    const linkKeys = new Set(); // Prevent duplicate visual lines
    const CORRELATION_WINDOW_MS = 30000; // 30-second fuzzy window for execution latency

    Object.values(byDayAndName).forEach(group => {
      if (group.length < 2) return;

      // O(N log N) sort by time to enable sliding window
      group.sort((a,b) => a.timestamp - b.timestamp);

      // Slidng Window Correlation
      for (let i = 0; i < group.length; i++) {
        const evA = group[i];
        let linksForEvA = 0;

        for (let j = i + 1; j < group.length; j++) {
          const evB = group[j];
          
          // Break if we are outside the window (since array is sorted)
          if (evB.timestamp - evA.timestamp > CORRELATION_WINDOW_MS) break;

          // Correlation Logic:
          // 1. Must be from different objects (don't link an artifact to its own other timestamps)
          // 2. Must be different lane categories OR different specific artifact types 
          //    within high-level lanes (like different Registry tables).
          const isDifferentSource = evA.source !== evB.source && (
            evA.type !== evB.type || 
            (evA.source?.source_table !== evB.source?.source_table && evA.source?.source_table && evB.source?.source_table)
          );

          if (isDifferentSource) {
            // Safety cap: Prevent link spaghetti/overload
            if (linksForEvA >= 4) break; 
            
            // Unidirectional Link Deduplication
            const linkKey = [evA.id, evB.id].sort().join('::');
            if (!linkKeys.has(linkKey)) {
              links.push({ source: evA, target: evB });
              linkKeys.add(linkKey);
              linksForEvA++;
            }
          }
        }
      }
    });

    return { events, links };
  }, [data, activeArtifacts, rangeStartIso, rangeEndIso]);
}
