// The lane layout reruns on every zoom step and parsed every time again, so
// parseForensicMs remembers string times. It must answer exactly what the
// uncached parse answered, quirks included: a careless cache returns NaN for a
// blank time (the parse gives 0, the epoch), keys a Date object by its text,
// or treats a cached NaN as "not cached".
import { describe, expect, it } from 'vitest';
import { cleanForensicDate, parseForensicMs } from './formatters';

const raw = (ts) => new Date(cleanForensicDate(ts)).getTime();

describe('parseForensicMs', () => {
  it('answers what the uncached parse answers, twice', () => {
    const cases = ['2026-11-04 10:00:00', '2026-11-04T10:00:00Z', '11/04/2026 10:00:00',
      '2026-11-04T10:00:00+02:00', '', 'N/A', 'None', '0s', 'garbage', null, undefined,
      0, 1730714400000, new Date(Date.UTC(2026, 10, 4))];
    for (const c of cases) {
      for (let i = 0; i < 2; i++) {
        const want = raw(c);
        const got = parseForensicMs(c);
        if (Number.isNaN(want)) expect(Number.isNaN(got)).toBe(true);
        else expect(got).toBe(want);
      }
    }
  });
});
