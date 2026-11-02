// Every link end must be a mark the artifacts lane plotted, or the line is never
// drawn (TimelineView finds both ends by id). Registry rows were typed 'registry'
// and event-log rows 'salvaged_event_logs' here while the lane typed them by table
// name and 'event_logs', and Prefetch accessed_on ends linked to marks the lane
// drops - all computed, none drawn.
import { describe, expect, it, vi } from 'vitest';

vi.mock('react', () => ({ useMemo: (fn) => fn() }));

import { useLinks } from './useLinks';
import { laneVisibleSources, laneSkipsTimestamp, srumBandStart } from '../utils/laneSources';
import { getForensicId, getForensicName, getForensicTimestamps } from '../utils/formatters';
import { heuristicFlatten } from '../utils/dataUtils';

const DATA = {
  prefetch: [{ executable_name: 'evil.exe', last_run: '2026-10-20T10:00:00Z', accessed_on: '2026-10-20T10:00:04Z' }],
  registry: { UserAssist: [{ program_name: 'evil.exe', last_executed: '2026-10-20T10:00:08Z' }] },
  event_logs: [{ executable_name: 'evil.exe', timestamp: '2026-10-20T10:00:12Z' }],
};
const ACTIVE = { prefetch: true, registry: true, event_logs: true };

function laneIds(data, active) {
  const ids = new Set();
  laneVisibleSources(data, active).forEach(src => {
    heuristicFlatten(src.items).forEach(p => {
      getForensicTimestamps(p).forEach(ts => {
        if (laneSkipsTimestamp(src.type, ts.field)) return;
        ids.add(getForensicId(src.type, ts.time, ts.field, getForensicName(p)));
      });
    });
  });
  return ids;
}

describe('useLinks', () => {
  const { links } = useLinks(DATA, ACTIVE);
  const plotted = laneIds(DATA, ACTIVE);

  it('links only marks the lane plotted', () => {
    expect(links.length).toBeGreaterThan(0);
    links.forEach(lk => {
      expect(plotted.has(lk.source.id)).toBe(true);
      expect(plotted.has(lk.target.id)).toBe(true);
    });
  });

  it('links registry and event-log rows under the lane types', () => {
    const types = new Set(links.flatMap(lk => [lk.source.type, lk.target.type]));
    expect(types.has('userassist')).toBe(true);
    expect(types.has('event_logs')).toBe(true);
    expect(types.has('registry')).toBe(false);
    expect([...types].some(t => t.startsWith('salvaged_event_logs'))).toBe(false);
  });

  it('links a Prefetch last-access time, which the lane plots', () => {
    const ends = links.flatMap(lk => [lk.source, lk.target]);
    expect(ends.some(e => e.type === 'prefetch' && e.field === 'accessed_on')).toBe(true);
  });

  it('keeps an event log out while its pill is off', () => {
    const off = useLinks(DATA, { ...ACTIVE, event_logs: false }).links;
    expect(off.some(lk => lk.source.type === 'event_logs' || lk.target.type === 'event_logs')).toBe(false);
  });
});

// SRUM band starts: the lane draws (and registers as a link point) each band from
// srumBandStart; useLinks used its own unclamped arithmetic, added a background-
// cycle start the lane never registers, and trusted SRUM "durations" that are CPU
// cycle counts or 67-year connected times - Sentinel's copy threw before year 1.
describe('useLinks SRUM band starts', () => {
  const RANGE = ['2026-02-15T00:00:00Z', '2026-02-16T00:00:00Z'];
  const lo = Date.parse(RANGE[0]);
  const hi = Date.parse(RANGE[1]);
  const SRUM = {
    srum_app: [
      { timestamp: '2026-02-15T10:00:00', app_name: 'chrome.exe', face_time: 600, background_cycle_time: 1.5e11 },
      { timestamp: '2026-02-15T11:00:00', app_name: 'chrome.exe', face_time: 7200, background_cycle_time: 300 },
      { timestamp: '2026-02-15T12:00:00', app_name: 'dwm.exe', face_time: 2.1e9 },
    ],
    srum_net: { connectivity: [
      { timestamp: '2026-02-15T23:40:00', app_name: 'svchost.exe', connected_time: 592606 * 3600 },
    ], data_usage: [] },
  };
  const ACTIVE_SRUM = { srum_app: true, srum_net: true };

  it('survives cycle counts and decades-long durations', () => {
    expect(() => useLinks(SRUM, ACTIVE_SRUM, RANGE[0], RANGE[1])).not.toThrow();
    expect(() => useLinks(SRUM, ACTIVE_SRUM)).not.toThrow();
  });

  it('places no mark outside the loaded range', () => {
    const { events } = useLinks(SRUM, ACTIVE_SRUM, RANGE[0], RANGE[1]);
    events.forEach(ev => {
      expect(ev.timestamp).toBeGreaterThanOrEqual(lo);
      expect(ev.timestamp).toBeLessThanOrEqual(hi);
    });
  });

  it('marks each band start where the lane draws it, clamped to the previous row', () => {
    const { events } = useLinks(SRUM, ACTIVE_SRUM, RANGE[0], RANGE[1]);
    const chrome = events.filter(ev => ev.type === 'srum_app' && ev.rawName === 'chrome.exe').map(ev => ev.timestamp);
    const firstStart = srumBandStart(SRUM.srum_app, 0, 600 * 1000, r => r.app_name);
    const secondStart = srumBandStart(SRUM.srum_app, 1, 7200 * 1000, r => r.app_name);
    expect(firstStart).toBe(Date.parse('2026-02-15T09:50:00Z'));
    // two hours of face time, but the previous chrome row ended at 10:00
    expect(secondStart).toBe(Date.parse('2026-02-15T10:00:00Z'));
    expect(chrome).toContain(firstStart);
    expect(chrome).toContain(secondStart);
  });

  it('adds no background-cycle start, which the lane never registers', () => {
    const { events } = useLinks(SRUM, ACTIVE_SRUM, RANGE[0], RANGE[1]);
    const chromeFirst = events.filter(ev => ev.source === SRUM.srum_app[0]);
    expect(chromeFirst.map(ev => ev.timestamp).sort()).toEqual(
      [Date.parse('2026-02-15T09:50:00Z'), Date.parse('2026-02-15T10:00:00Z')].sort());
  });
});
