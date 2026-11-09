// srumBandStart walked back from every SRUM row to the previous row of the same
// app - O(n^2) over a day of many apps, twice per row. srumPrevEnds finds the
// same previous rows in one pass; a careless version takes the previous row of
// ANY app, the next row instead of the previous one, or loses a time that does
// not parse (the scan compares it and keeps the start).
import { describe, expect, it } from 'vitest';
import { srumBandStart, srumPrevEnds } from './laneSources';

function rows() {
  const apps = ['a.exe', 'b.exe', 'c.exe', undefined];
  const out = [];
  let t = Date.UTC(2026, 10, 4, 0, 0, 0);
  for (let i = 0; i < 400; i++) {
    t += ((i * 7919) % 13) * 4000;
    out.push({
      app_name: apps[(i * 31) % apps.length],
      app_id: 'id' + (i % 3),
      timestamp: i % 57 === 0 ? 'not a time' : new Date(t).toISOString().replace('T', ' ').slice(0, 19),
      face_time: String((i * 13) % 90),
    });
  }
  return out;
}

describe('srumPrevEnds', () => {
  it('gives srumBandStart exactly what its backward scan found', () => {
    const data = rows();
    for (const keyOf of [r => r.app_name, r => r.app_name || r.app_id]) {
      const prev = srumPrevEnds(data, keyOf);
      data.forEach((r, i) => {
        const ms = Number(r.face_time) * 1000;
        const scanned = srumBandStart(data, i, ms, keyOf);
        const fast = srumBandStart(data, i, ms, keyOf, prev);
        if (Number.isNaN(scanned)) expect(Number.isNaN(fast)).toBe(true);
        else expect(fast).toBe(scanned);
      });
    }
  });

  it('names no previous row for an app seen first', () => {
    const prev = srumPrevEnds([{ app_name: 'x', timestamp: '2026-11-04 00:00:00' },
                               { app_name: 'y', timestamp: '2026-11-04 00:01:00' },
                               { app_name: 'x', timestamp: '2026-11-04 00:02:00' }], r => r.app_name);
    expect(prev[0]).toBe(null);
    expect(prev[1]).toBe(null);
    expect(prev[2]).toBe(Date.UTC(2026, 10, 4, 0, 0, 0));
  });
});
