import { describe, expect, it, vi } from 'vitest';
import { createTooltipStore } from './tooltipStore';

describe('createTooltipStore', () => {
  it('tells its subscribers, and only when the tooltip changes', () => {
    const store = createTooltipStore();
    const seen = vi.fn();
    const off = store.subscribe(seen);
    expect(store.get()).toBe(null);
    const tip = { ev: { name: 'a.exe' }, x: 10, y: 20 };
    store.set(tip);
    expect(store.get()).toBe(tip);
    store.set(tip);                       // the same hover again: nothing to redraw
    expect(seen).toHaveBeenCalledTimes(1);
    store.set(null);
    expect(seen).toHaveBeenCalledTimes(2);
    off();
    store.set(tip);
    expect(seen).toHaveBeenCalledTimes(2);
  });

  it('keeps each view its own tooltip', () => {
    const a = createTooltipStore(), b = createTooltipStore();
    a.set({ x: 1 });
    expect(b.get()).toBe(null);
  });
});
