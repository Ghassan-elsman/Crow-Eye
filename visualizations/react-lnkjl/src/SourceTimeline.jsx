import React, { useEffect, useMemo, useRef, useState } from 'react'
import { SOURCES, SOURCE_RAMPS, SOURCE_LABEL, fmtInt, fmtDay } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

const level = (v, max) => {
  if (!v || v <= 0) return 0
  const r = v / (max || 1)
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

/**
 * Opened-file activity as a day strip: X is the day, Y is the source.
 *
 * Every day in the range is drawn, including the empty ones - a jump list that
 * records nothing for two years is itself a finding. On this case that is 4,568
 * days of which 70 carry anything - shown six months at a time, opening on the
 * most recent end, with the navigator's overview showing all of it. See DayAxis.jsx.
 *
 * The cells carry their day in a `data-` attribute and one handler on the row
 * reads it, so the tooltip's state cannot re-render thousands of cells on every
 * mouse move.
 */
export default function SourceTimeline({ timeline, selectedDay, onSelectDay }) {
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

  const rows = useMemo(() => SOURCES.map(src => {
    const row = sources[src.key] || { days: [], max: 0 }
    const map = new Map(row.days.map(d => [d.day, d.value]))
    const ramp = SOURCE_RAMPS[src.key]
    return (
      <div className="usn-row" key={src.key}>
        <div className="usn-rowhead"><span className="usn-sw" style={{ background: src.color }} />{src.label}</div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const day = dayAt(e)
            if (!day) return
            setTip({ day, src: src.key, v: map.get(day) || 0, x: e.clientX, y: e.clientY })
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
          <span className="tl-title">Opened-file activity</span>
          <span className="tl-sub">when files were opened (target last-access), by source &mdash; one cell per day including the quiet ones, click a day to explore it below</span>
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
          <div><b>{fmtInt(tip.v)}</b> {SOURCE_LABEL[tip.src]} opens</div>
        </div>
      )}
    </div>
  )
}
