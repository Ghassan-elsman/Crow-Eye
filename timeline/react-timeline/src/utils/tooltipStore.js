// The timeline's hover tooltip, held outside TimelineView's state. As state it
// re-rendered the whole view - every lane and every mark, 1,700 of them on a
// busy day - each time the pointer entered or left one mark: 20-70 ms a hover.
// Only the tooltip host subscribes, so a hover now redraws the tooltip alone.

export function createTooltipStore() {
  let current = null;
  const listeners = new Set();
  return {
    get: () => current,
    set: (value) => {
      if (value === current) return;
      current = value;
      listeners.forEach((fn) => fn());
    },
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
