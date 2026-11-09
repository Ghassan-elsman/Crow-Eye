/* global process */
// A stored time with no zone is UTC (utils/time_utils writes them so). The
// tooltip and the detail panel printed it through new Date(), which reads such
// a string as the EXAMINER's local time: on a machine at UTC+2 an MFT file
// created at 05:05:01 showed 03:05:01 in its tooltip while its mark sat at
// 05:05 on the axis and the lane's table said 05:05:01.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { formatTime, parseForensicMs } from './formatters';

describe('formatTime in a zone that is not UTC', () => {
  let tz;
  beforeAll(() => { tz = process.env.TZ; process.env.TZ = 'Africa/Cairo'; });
  afterAll(() => { if (tz === undefined) delete process.env.TZ; else process.env.TZ = tz; });

  it('runs in a zone with an offset (or this test proves nothing)', () => {
    expect(new Date('2026-05-10 05:05:01').getUTCHours()).not.toBe(5);
  });

  it('prints a stored time as it was stored', () => {
    expect(formatTime('2026-05-10 05:05:01')).toBe('2026-05-10 05:05:01');
    expect(formatTime('2026-05-10T05:05:01')).toBe('2026-05-10 05:05:01');
    expect(formatTime('2026-05-10 05:05:01.123456')).toBe('2026-05-10 05:05:01');
    expect(formatTime('2026-05-10 05:05:01', 'time')).toBe('05:05:01');
  });

  it('agrees with where the mark is drawn', () => {
    const ts = '2026-05-10 05:05:01';
    expect(formatTime(new Date(parseForensicMs(ts)).toISOString())).toBe(formatTime(ts));
  });

  it('leaves times that carry a zone, and non-strings, as they are', () => {
    expect(formatTime('2026-05-10T05:05:01Z')).toBe('2026-05-10 05:05:01');
    expect(formatTime('2026-05-10T07:05:01+02:00')).toBe('2026-05-10 05:05:01');
    expect(formatTime(Date.UTC(2026, 4, 10, 5, 5, 1))).toBe('2026-05-10 05:05:01');
    expect(formatTime(new Date(Date.UTC(2026, 4, 10, 5, 5, 1)))).toBe('2026-05-10 05:05:01');
    expect(formatTime(null)).toBe('—');
    expect(formatTime('not a time')).toBe('not a time');
  });
});
