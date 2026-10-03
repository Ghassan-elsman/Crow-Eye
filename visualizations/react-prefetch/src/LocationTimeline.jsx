import React, { useEffect, useMemo, useRef, useState } from 'react'
import { LOCATIONS, LOC_RAMPS, LOC_LABEL, fmtInt, fmtDay } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

const level = (v, max) => {
  if (!v || v <= 0) return 0
  const r = v / (max || 1)
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

/**
 * Program execution as a day strip: X is the day, Y is where the .exe ran from.
 *
 * Every day in the range is drawn, including the empty ones: a stretch where
 * nothing executed is exactly what a prefetch timeline is read for. Measured on
 * one case, 43 of 213 days were quiet and had been erased entirely.
 *
 * A range longer than six months is shown a window at a time, opening on its
 * most recent end; the navigator above the strip pages it and draws the whole
 * range at one bar per week. The cell still means one day. See DayAxis.jsx.
 */
export default function LocationTimeline({ timeline, selectedDay, onSelectDay }) {
  const [tip, setTip] = useState(null)
  const stripRef = useRef(null)
  const combined = timeline?.combined || []
  const sources = timeline?.sources || {}
  const days = useMemo(() => combined.map(c => c.day), [combined])
  // Six months at a time (DayAxis.jsx): the strip draws `view`, and the
  // navigator above it pages the window and shows the whole range.
  const win = useStripWindow(days, selectedDay)
  const view = win.view
  const totals = useMemo(() => combined.map(c => c.value || 0), [combined])
  const { columns, cellsClass, pitch } = useStripFit(stripRef, view.length)


  const dayAt = (e) => e.target && e.target.dataset ? e.target.dataset.day : null

  const rows = useMemo(() => LOCATIONS.map(loc => {
    const row = sources[loc.key] || { days: [], max: 0 }
    const map = new Map(row.days.map(d => [d.day, d.value]))
    const ramp = LOC_RAMPS[loc.key]
    return (
      <div className="usn-row" key={loc.key}>
        <div className="usn-rowhead"><span className="usn-sw" style={{ background: loc.color }} />{loc.label}</div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const day = dayAt(e)
            if (!day) return
            setTip({ day, loc: loc.key, v: map.get(day) || 0, x: e.clientX, y: e.clientY })
          }}
          onMouseLeave={() => setTip(null)}
          onClick={(e) => { const day = dayAt(e); if (day) onSelectDay(day) }}>
          {view.map(day => (
            <div key={day} data-day={day}
              className={'usn-cell' + (selectedDay === day ? ' sel' : '')}
              style={{ background: ramp[level(map.get(day) || 0, row.max)] }} />
          ))}
        </div>
      </div>
    )
  }), [sources, view, selectedDay, columns, cellsClass, onSelectDay])

  return (
    <div className="tl">
      <div className="tl-block">
        <div className="tl-head">
          <span className="tl-title">Program execution</span>
          <span className="tl-sub">when programs ran (up to 8 run times each), by where the .exe ran from &mdash; one cell per day including the quiet ones, click a day to explore it below</span>
        </div>
        <StripNavigator win={win} days={days} totals={totals} />
        <div className="usn-strip" ref={stripRef}>
          <div className="usn-axis">
            <div className="usn-rowhead usn-unit">1 cell = 1 day</div>
            <DayAxis days={view} columns={columns} pitch={pitch} />
          </div>
          {rows}
        </div>
      </div>

      {tip && (
        <div className="cal-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 220), top: tip.y + 14 }}>
          <div className="tip-day">{fmtDay(tip.day)}</div>
          <div><b>{fmtInt(tip.v)}</b> {LOC_LABEL[tip.loc]} runs</div>
        </div>
      )}
    </div>
  )
}
