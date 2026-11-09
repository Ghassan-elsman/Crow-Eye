import { describe, expect, it } from 'vitest';
import { windowRange, ROW_H } from './windowing';

describe('windowRange', () => {
  it('draws only the rows on screen plus the margin', () => {
    const w = windowRange(0, 330, 60000);
    expect(w.start).toBe(0);
    expect(w.end).toBe(20);                      // 10 visible + 10 margin
    expect(w.top).toBe(0);
    expect(w.top + (w.end - w.start) * ROW_H + w.bottom).toBe(60000 * ROW_H);
  });

  it('keeps the scroll height true anywhere in the list', () => {
    const w = windowRange(ROW_H * 30000 + 5, 660, 60000);
    expect(w.start).toBe(29990);
    expect(w.end).toBe(30030);
    expect(w.top + (w.end - w.start) * ROW_H + w.bottom).toBe(60000 * ROW_H);
  });

  it('ends at the last row and survives a scroll past it', () => {
    const w = windowRange(ROW_H * 999999, 330, 50);
    expect(w.end).toBe(50);
    expect(w.bottom).toBe(0);
    expect(w.start).toBeLessThan(50);
    expect(windowRange(0, 330, 0)).toEqual({ start: 0, end: 0, top: 0, bottom: 0 });
    expect(windowRange(0, 330, 3)).toEqual({ start: 0, end: 3, top: 0, bottom: 0 });
  });
});
