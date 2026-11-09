import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import React from 'react'

/**
 * The day-strip heat map's shared geometry, its 6-month window, the navigator
 * that moves the window, and the date scale above the cells.
 *
 * Byte-identical across all six dashboards - see
 * docs/building-a-visualization.md.
 *
 * **One cell is one day, always.** The strip fills every day in the window,
 * including the empty ones, because a quiet stretch is usually what an
 * investigator came to find.
 *
 * **Six months at a time, never a scrollbar.** A long range used to become one
 * ~22,000px strip behind a horizontal scrollbar: each day a 7px sliver, no
 * sense of the whole, and dragging the only way around. Now the strip shows a
 * 183-day window that fills the pane, and the StripNavigator above it pages
 * the window and draws the WHOLE range at one bar per week, with the visible
 * six months boxed - so the overall shape of the activity is always on screen
 * and a click anywhere in it goes there. The unit of the strip never changes;
 * the overview is labelled as the coarser thing it is.
 */

// Six months of days. A range this long or shorter is shown whole, with no
// navigator at all.
export const WINDOW_DAYS = 183
// How far Previous / Next move: a window less two weeks, so the edge of the
// period just left stays on screen as context.
export const WINDOW_STEP = WINDOW_DAYS - 14

// These mirror `.usn-rowhead { width }` and the `.usn-row { gap }` in
// styles.css. They are here because the width available to the cells has to be
// known before the cells are laid out, so it cannot be measured from them.
const ROWHEAD_PX = 120
const ROW_GAP_PX = 8

/**
 * Where the window starts, as a pure function so it can be tested on its own.
 *
 *   total     days in the whole range
 *   size      window length (WINDOW_DAYS)
 *   start     the window's current start, or null for "the most recent days"
 *   selected  index of the selected day, or -1
 *
 * Opens on the most recent days - the end of the range is where an
 * investigation usually starts. A selection outside the window (picked from an
 * insight, an item, the date filter) moves the window to it, centred; one
 * already on screen leaves the window where the analyst put it.
 */
export function windowFor(total, size, start, selected) {
  const n = Math.max(0, total | 0)
  const w = Math.max(1, size | 0)
  if (n <= w) return 0
  const last = n - w
  let s = (start === null || start === undefined) ? last : start
  s = Math.min(Math.max(0, s), last)
  if (selected >= 0 && selected < n && (selected < s || selected >= s + w)) {
    s = Math.min(Math.max(0, selected - Math.floor(w / 2)), last)
  }
  return s
}

/**
 * The visible slice of `days` and the controls that move it.
 *
 * `start` is null until the analyst moves the window, which keeps it pinned to
 * the most recent days while the data settles (a filter change, a reload).
 */
export function useStripWindow(days, selectedDay) {
  const all = days || []
  const total = all.length
  const [start, setStart] = useState(null)
  const selected = selectedDay ? all.indexOf(selectedDay) : -1

  // Follow a selection made outside the strip, once, when it is off screen.
  useEffect(() => {
    if (selected < 0) return
    setStart((cur) => {
      const s = windowFor(total, WINDOW_DAYS, cur, -1)
      if (selected >= s && selected < s + WINDOW_DAYS) return cur
      return windowFor(total, WINDOW_DAYS, cur, selected)
    })
  }, [selected, total])

  const s = windowFor(total, WINDOW_DAYS, start, -1)
  const view = useMemo(() => all.slice(s, s + WINDOW_DAYS), [all, s])
  const last = Math.max(0, total - WINDOW_DAYS)
  const go = (v) => setStart(Math.min(Math.max(0, v), last))
  return {
    view,
    start: s,
    end: s + view.length,
    total,
    paged: total > WINDOW_DAYS,
    canPrev: s > 0,
    canNext: s < last,
    prev: () => go(s - WINDOW_STEP),
    next: () => go(s + WINDOW_STEP),
    latest: () => setStart(null),
    // Centre the window on a day index (overview clicks).
    jumpTo: (i) => go(i - Math.floor(WINDOW_DAYS / 2)),
  }
}

/**
 * How wide a cell is. The window is at most 183 days, so the strip always
 * fits its pane: every track is `minmax(0, 1fr)` and nothing scrolls.
 *
 * `minmax(0, 1fr)`, never a bare `1fr`: a bare `1fr` is `minmax(auto, 1fr)`,
 * so the widest cell's minimum becomes every track's minimum - and
 * `.usn-cell.sel` has 2px borders, which pushed a 226-day strip 135px past its
 * pane over one selected day.
 */
export function useStripFit(stripRef, count) {
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = stripRef.current
    if (!el) return undefined
    const measure = () => setWidth(el.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [stripRef])
  const n = count || 0
  const avail = Math.max(0, width - ROWHEAD_PX - ROW_GAP_PX)
  return {
    pitch: n ? avail / n : 0,
    columns: `repeat(${n}, minmax(0, 1fr))`,
    cellsClass: 'usn-cells',
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monthOf = (d) => MONTHS[(parseInt(String(d).slice(5, 7), 10) || 1) - 1]
const yearOf = (d) => String(d).slice(0, 4)
export function monthLabel(d) { return monthOf(d) + ' ' + yearOf(d) }

/**
 * The date scale: one label at the start of every month ("Apr", "Jan 2026" at
 * a year change), plus the 15th when a day has room for it. Month starts are
 * what a reader scans a six-month strip by; a label every 90px of `MM-DD`
 * made them count.
 *
 * The axis takes the cells' own `columns`, so a tick sits exactly above its
 * day. Only the labelled columns are rendered, placed on the grid by index.
 */
export default function DayAxis({ days, columns, pitch }) {
  const n = (days || []).length
  if (!n) return <div className="usn-axlabels" />
  const mids = pitch >= 4
  const ticks = []
  for (let i = 0; i < n; i++) {
    const d = String(days[i])
    const dd = d.slice(8, 10)
    if (i === 0 || dd === '01') {
      const yearChange = i === 0 || d.slice(5, 7) === '01'
      ticks.push({ i, text: yearChange ? monthLabel(d) : monthOf(d), major: true })
    } else if (mids && dd === '15') {
      ticks.push({ i, text: '15', major: false })
    }
  }
  // No two labels may overlap. Walking left to right, a label that would land
  // on the previous one is dropped - unless it is a month start and the
  // previous one is the opening label or a "15": then the month start wins and
  // keeps the year. (Dropping the month start instead put "15" right after
  // "Mar 2026" when it was April's 15th.)
  const step = Math.max(pitch, 0.5)
  const widthOf = (t) => t.text.length * 7.5 + 8
  const show = []
  for (const t of ticks) {
    const prev = show[show.length - 1]
    if (!prev || (t.i - prev.i) * step >= widthOf(prev)) { show.push(t); continue }
    if (t.major && (!prev.major || show.length === 1)) {
      const year = show.length === 1 || prev.text.length > 4
      show[show.length - 1] = { ...t, text: year ? monthLabel(days[t.i]) : t.text }
    }
  }
  return (
    <div className="usn-axlabels" style={{ gridTemplateColumns: columns || `repeat(${n}, 1fr)` }}>
      {show.map((t, k) => (
        <span key={days[t.i]} style={{ gridColumn: t.i + 1 }}
          className={'usn-axtick' + (t.major ? ' usn-axtick--major' : '')
            + (k === 0 ? ' usn-axtick--first' : '')}>
          <i>{t.text}</i>
        </span>
      ))}
    </div>
  )
}

/**
 * Above the strip: page the 6-month window, and see the whole range at once.
 *
 * The overview is the entire range at one bar per week - its height is that
 * week's total activity - with the visible six months boxed. Clicking anywhere
 * in it moves the window there. Hidden when the whole range already fits.
 *
 *   win     the useStripWindow() result
 *   days    the whole range, one entry per day
 *   totals  per-day totals: a Map(day -> n) or an array aligned with `days`
 */
export function StripNavigator({ win, days, totals }) {
  const all = days || []
  const weeks = useMemo(() => {
    const val = (i) => {
      if (!totals) return 0
      if (Array.isArray(totals)) return Number(totals[i]) || 0
      return Number(totals.get(all[i])) || 0
    }
    const out = []
    for (let i = 0; i < all.length; i += 7) {
      let v = 0
      for (let j = i; j < Math.min(i + 7, all.length); j++) v += val(j)
      out.push({ i, v, from: all[i], to: all[Math.min(i + 6, all.length - 1)] })
    }
    return out
  }, [all, totals])
  const [hover, setHover] = useState(null)
  const boxRef = useRef(null)
  if (!win || !win.paged || !weeks.length) return null

  const max = Math.max(1, ...weeks.map((w) => w.v))
  const W = weeks.length
  const H = 44
  const years = []
  for (let k = 0; k < W; k++) {
    const y = yearOf(weeks[k].from)
    if (k === 0 || y !== yearOf(weeks[k - 1].from)) years.push({ k, y })
  }
  const weekAt = (e) => {
    const r = boxRef.current.getBoundingClientRect()
    const k = Math.floor(((e.clientX - r.left) / Math.max(1, r.width)) * W)
    return weeks[Math.min(W - 1, Math.max(0, k))]
  }
  const first = win.view[0]
  const lastDay = win.view[win.view.length - 1]
  const onKey = (e) => {
    if (e.key === 'ArrowLeft' && win.canPrev) { e.preventDefault(); win.prev() }
    if (e.key === 'ArrowRight' && win.canNext) { e.preventDefault(); win.next() }
  }

  return (
    <div className="strip-nav" tabIndex={0} onKeyDown={onKey}>
      <div className="strip-nav-bar">
        <button className="strip-nav-btn" disabled={!win.canPrev} onClick={win.prev}>&#9664; Previous 6 months</button>
        <div className="strip-nav-label">
          <b>{monthLabel(first)} &ndash; {monthLabel(lastDay)}</b>
          <span>days {(win.start + 1).toLocaleString()}&ndash;{win.end.toLocaleString()} of {win.total.toLocaleString()}</span>
        </div>
        <button className="strip-nav-btn" disabled={!win.canNext} onClick={win.next}>Next 6 months &#9654;</button>
        <button className="strip-nav-btn strip-nav-latest" disabled={!win.canNext} onClick={win.latest}>Latest</button>
      </div>
      <div className="strip-nav-ov-head">
        <span>Whole range &middot; 1 bar = 1 week &middot; click to jump</span>
        <span className="strip-nav-hover">
          {hover ? <>{hover.from} &rarr; {hover.to}: <b>{hover.v.toLocaleString()}</b></> : ' '}
        </span>
      </div>
      <div className="strip-nav-ov" ref={boxRef}
        onMouseMove={(e) => setHover(weekAt(e))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => win.jumpTo(weekAt(e).i + 3)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}>
          {weeks.map((w, k) => {
            if (!w.v) return null
            const h = Math.max(2, Math.sqrt(w.v / max) * (H - 2))
            return <rect key={k} x={k} y={H - h} width={0.86} height={h} className="strip-nav-barw" />
          })}
          <rect className="strip-nav-win" x={win.start / 7} y={0}
            width={Math.max(1, (win.end - win.start) / 7)} height={H} />
        </svg>
        <div className="strip-nav-years">
          {years.map(({ k, y }) => (
            <span key={y} style={{ left: (k / W * 100) + '%' }}>{y}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
