// The slice of a long fixed-height list that is on screen, plus a margin.
// A lane's data modal drew every row it had: 60k+ table rows for a busy MFT/USN
// or artifacts lane, rebuilt on every keystroke of its search box.

export const ROW_H = 33;

/** {start, end, top, bottom}: rows [start, end) to draw, and the empty space
 *  in pixels to leave above and below them so the scrollbar stays true. */
export function windowRange(scrollTop, viewH, n, rowH = ROW_H, overscan = 10) {
  if (!n) return { start: 0, end: 0, top: 0, bottom: 0 };
  const first = Math.floor(Math.max(0, scrollTop) / rowH);
  const shown = Math.ceil(Math.max(viewH, rowH) / rowH);
  const start = Math.max(0, Math.min(n - 1, first) - overscan);
  const end = Math.min(n, first + shown + overscan);
  return { start, end, top: start * rowH, bottom: (n - end) * rowH };
}
