import { useMemo } from 'react';
import { normalizeForensicName, getForensicName, getForensicTimestamps, getForensicId, cleanForensicDate } from '../utils/formatters';
import { heuristicFlatten } from '../utils/dataUtils';
import { laneVisibleSources, laneSkipsTimestamp, laneSalvageSources, srumBandStart } from '../utils/laneSources';

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
        rawTimestamp: timestamp,
        field,
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

    // A SRUM band's start is a link point too: the lane registers it, from
    // srumBandStart, at the face time (app) or connected time (network) before the
    // row. Only that start - the lane registers no background-cycle start, so a
    // mark there was a link that never drew - and only inside the loaded range:
    // SRUM's "durations" are not all durations (background_cycle_time is CPU
    // cycles; connected_time has read 67 years), and a start outside the range
    // has no mark to attach to. Sentinel's copy threw on one before year 1.
    const lo = rangeStartIso ? new Date(cleanForensicDate(rangeStartIso)).getTime() : -Infinity;
    const hi = rangeEndIso ? new Date(cleanForensicDate(rangeEndIso)).getTime() : Infinity;
    const addBandStart = (item, type, start, name) => {
      if (Number.isFinite(start) && start >= lo && start <= hi) {
        add(item, type, new Date(start).toISOString(), name, 'timestamp');
      }
    };

    if (activeArtifacts.srum_app && Array.isArray(data.srum_app)) {
      data.srum_app.forEach((item, idx, arr) => {
        const name = getForensicName(item);
        add(item, 'srum_app', item.timestamp, name, 'timestamp');
        const faceMs = item.face_time ? Number(item.face_time) * 1000 : 0;
        addBandStart(item, 'srum_app', srumBandStart(arr, idx, faceMs, r => r.app_name), name);
      });
    }

    if (activeArtifacts.srum_net && data.srum_net) {
      const connectivity = Array.isArray(data.srum_net.connectivity) ? data.srum_net.connectivity : [];
      connectivity.forEach((item, idx, arr) => {
        const name = getForensicName(item);
        add(item, 'srum_net', item.timestamp, name, 'timestamp');
        const durMs = (parseFloat(item.connected_time) || 0) * 1000;
        addBandStart(item, 'srum_net', srumBandStart(arr, idx, durMs, r => r.app_name || r.app_id), name);
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

    // The artifacts lane, from the lane's own source list (utils/laneSources.js), so
    // every event here carries the id the lane gave its mark: same types (registry
    // tables by name, 'event_logs'), the same timestamps (Prefetch last-access included),
    // same salvaged objects. A pill switched off keeps its events out, as before.
    const TOGGLE = { dam: 'bam', amcache: 'amcache', event_logs: 'event_logs', key_times: 'key_times' };
    const toggleOf = (type) => TOGGLE[type] ||
      (['prefetch', 'lnk', 'bam', 'shimcache', 'recyclebin', 'imported'].includes(type) ? type : 'registry');
    laneVisibleSources(data, activeArtifacts).forEach(src => {
      if (src.type !== 'imported' && activeArtifacts[toggleOf(src.type)] === false) return;
      heuristicFlatten(src.items).forEach(item => {
        const name = getForensicName(item);
        getForensicTimestamps(item).forEach(ts => {
          if (laneSkipsTimestamp(src.type, ts.field)) return;
          add(item, src.type, ts.time, name, ts.field);
        });
      });
    });
    laneSalvageSources(data).forEach(src => processItems(src.items, src.type));

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
