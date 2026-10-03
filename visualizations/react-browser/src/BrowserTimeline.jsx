import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ACTIVITIES, ACTIVITY_RAMPS, ACTIVITY_LABEL } from './format.js'
import { fmtDay, fmtInt } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

/**
 * Browsing activity as a day strip: X is the day, Y is the activity source.
 *
 * This was the GitHub-style calendar ported from react-viz, and its own comment
 * argued for that form "because browser history spans months". It does - and
 * that was the problem: a year of history was 53 stacked week-rows, so the
 * heat-map alone owned most of the page and everything below it started off
 * screen. The strip is a fixed `activities x 22px` whatever the range, which
 * hands the rest of the dashboard back its vertical space.
 *
 * **Every day in the range is a cell, including the empty ones.** Measured on
 * one case, 92 of 226 days had been erased by the `GROUP BY` the strip was
 * built from - and a browser that recorded nothing for three months is a
 * finding, not a blank to close up.
 *
 * A range longer than six months is shown a window at a time, opening on its
 * most recent end; the navigator above the strip pages it and draws the whole
 * range at one bar per week. The cell still means one day. See DayAxis.jsx.
 */

const level = (v, max) => {
  if (!v || v <= 0) return 0
  if (!max) return 1
  const r = v / max
  return r <= 0.2 ? 1 : r <= 0.4 ? 2 : r <= 0.6 ? 3 : r <= 0.8 ? 4 : 5
}

export default function BrowserTimeline({ heatmaps, selectedDay, onSelect }) {
  const [tip, setTip] = useState(null)
  const stripRef = useRef(null)
  const combined = heatmaps?.combined || []
  const sources = heatmaps?.sources || {}
  const days = useMemo(() => combined.map(c => c.day), [combined])
  // Six months at a time (DayAxis.jsx): the strip draws `view`, and the
  // navigator above it pages the window and shows the whole range.
  const win = useStripWindow(days, selectedDay)
  const view = win.view
  const totals = useMemo(() => combined.map(c => c.value || 0), [combined])
  const { columns, cellsClass, pitch } = useStripFit(stripRef, view.length)


  const dayAt = (e) => e.target && e.target.dataset ? e.target.dataset.day : null

  // Memoised so the tooltip's state cannot re-render every cell on a mouse move.
  const rows = useMemo(() => ACTIVITIES.map((act) => {
    const adata = sources[act.key] || { days: [], max: 0 }
    const map = new Map(adata.days.map(d => [d.day, d.value]))
    const ramp = ACTIVITY_RAMPS[act.key]
    return (
      <div className="usn-row" key={act.key}>
        <div className="usn-rowhead">
          <span className="usn-sw" style={{ background: act.color }} />{act.label}
        </div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const day = dayAt(e)
            if (!day) return
            setTip({ day, act: act.key, val: map.get(day) || 0, x: e.clientX, y: e.clientY })
          }}
          onMouseLeave={() => setTip(null)}
          onClick={(e) => { const day = dayAt(e); if (day) onSelect(day) }}>
          {view.map(day => (
            <div key={day} data-day={day}
              className={'usn-cell' + (selectedDay === day ? ' sel' : '')}
              style={{ background: ramp[level(map.get(day) || 0, adata.max)] }} />
          ))}
        </div>
      </div>
    )
  }), [sources, view, selectedDay, columns, cellsClass, onSelect])

  return (
    <div className="hm-root">
      <StripNavigator win={win} days={days} totals={totals} />
      <div className="usn-strip" ref={stripRef}>
        <div className="usn-axis">
          <div className="usn-rowhead usn-unit">1 cell = 1 day</div>
          <DayAxis days={view} columns={columns} pitch={pitch} />
        </div>
        {rows}
      </div>

      <div className="hm-hint">Each row is one browsing-activity source &middot; one cell per day, quiet days included &middot; click a day to explore it below.</div>

      {tip && (
        <div className="cal-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 220), top: tip.y + 14 }}>
          <div className="tip-day">{fmtDay(tip.day)}</div>
          <div><b>{fmtInt(tip.val)}</b> {ACTIVITY_LABEL[tip.act]}</div>
        </div>
      )}
    </div>
  )
}
