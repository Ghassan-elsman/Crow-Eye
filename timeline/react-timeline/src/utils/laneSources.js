/**
 * The artifacts lane's sources, shared by the lane (TimelineView) and the links
 * (useLinks).
 *
 * A link is drawn between two plotted marks, found by id, and an id is built from
 * the source's `type` (getForensicId). The two used to keep their own lists:
 * useLinks typed every registry row 'registry' and event-log rows
 * 'salvaged_event_logs' while the lane typed them by table name and 'event_logs',
 * and it kept the Prefetch 'accessed_on' ends the lane then dropped - so those links
 * were computed and never drawn, and the detail panel never listed them. One list
 * now; the lane plots the last-access time too, and links it.
 */
import { cleanForensicDate } from './formatters';

/** Every source the artifacts lane plots, as {items, type}. */
export function laneArtifactSources(data) {
  if (!data) return [];
  const registry = data.registry || {};
  const am = data.amcache || data.amcache_applications;
  return [
    { items: data.prefetch || data.prefetch_data, type: 'prefetch' },
    { items: data.lnk, type: 'lnk' },
    { items: data.bam, type: 'bam' },
    { items: data.dam, type: 'dam' },
    { items: data.shimcache, type: 'shimcache' },
    { items: data.recyclebin, type: 'recyclebin' },
    { items: am?.application_files, type: 'amcache' },
    { items: am?.applications, type: 'amcache' },
    { items: am?.drivers, type: 'amcache' },
    { items: am?.devices, type: 'amcache' },
    { items: am?.driver_packages, type: 'amcache' },
    { items: data.imported, type: 'imported' },
    // Windows Event Log. This list is hand-written - the registry spreads
    // itself out below, everything else is named - so a payload key
    // missing from it is fetched, counted in the pill, and drawn nowhere.
    // That is exactly what happened here: 553 rows on the day this was
    // written, all of them absent from the lane.
    { items: data.event_logs, type: 'event_logs' },
    ...Object.keys(registry).map(table => ({ items: registry[table], type: table.toLowerCase() }))
  ];
}

/**
 * The sources the lane actually draws: registry KEY write times only when the
 * analyst turns them on (an upper bound, ~2,200 of them on install day), the event
 * log only while its pill is on.
 */
export function laneVisibleSources(data, activeArtifacts = {}) {
  return laneArtifactSources(data).filter(
    src => (src.type !== 'key_times' || activeArtifacts.key_times)
        && (src.type !== 'event_logs' || activeArtifacts.event_logs)
  );
}

/**
 * Timestamps the lane never plots. None today: a Prefetch file's last-access time
 * (accessed_on) is plotted as 'accessed' and linked like every other time - it is
 * not a run, and the lane labels it as an access, but it places the program on the
 * timeline and ties it to the artifacts around it.
 */
export function laneSkipsTimestamp(type, field) {   // eslint-disable-line no-unused-vars
  return false;
}

/**
 * Where a SRUM lane starts row `idx`'s band: `durationMs` back from its timestamp
 * (at least 20 s), but never before the same app's previous row ended. The lane
 * draws the band from here and registers it as a link point; useLinks must use
 * the same number or a link to the band's start finds no mark.
 *
 * Without the clamp a duration is trusted as given, and SRUM's are not all
 * durations: background_cycle_time is a CPU cycle count, and connected_time has
 * read 592,606 hours on a real case - a band "starting" in 1958.
 */
export function srumBandStart(rows, idx, durationMs, keyOf) {
  const row = rows[idx];
  let start = new Date(cleanForensicDate(row.timestamp)).getTime() - Math.max(20000, durationMs || 0);
  const key = keyOf(row);
  for (let i = idx - 1; i >= 0; i--) {
    if (keyOf(rows[i]) === key) {
      // cleaned like the row's own time: a bare SRUM timestamp is UTC (parsed
      // raw it was local time, so the clamp moved with the viewer's zone)
      const prevEnd = new Date(cleanForensicDate(rows[i].timestamp)).getTime();
      if (start < prevEnd) start = prevEnd;
      break;
    }
  }
  return start;
}

/** Malformed (object, not list) payloads the lane salvages, with the type it plots them as. */
export function laneSalvageSources(data) {
  if (!data) return [];
  return [
    { items: data.sessions?.events, type: 'salvaged_sessions_events' },
    { items: data.srum_app, type: 'salvaged_srum_app' },
    { items: data.srum_net?.connectivity, type: 'salvaged_srum_net_conn' },
    { items: data.srum_net?.data_usage, type: 'salvaged_srum_net_usage' },
    { items: data.mft_usn, type: 'salvaged_mft_usn' },
  ].filter(src => src.items && typeof src.items === 'object' && !Array.isArray(src.items));
}
