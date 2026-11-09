import React, { useMemo, useRef, useState } from 'react'
import { SERIES, SERIES_RAMPS, SERIES_LABEL, fmtInt, fmtDay } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

const level = (v, max) => {
  if (!v || v <= 0) return 0
  const r = v / (max || 1)
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

/**
 * What AI agents did, as a day strip: X is the day, Y is the act - the
 * person's prompts, the commands the agent ran, the files it wrote or edited,
 * the pages and screen it drove.
 *
 * Every day in the range is a cell, the quiet ones included: a day the agent
 * did nothing is as much an answer as a busy one. Six months at a time, opening
 * on the most recent end (DayAxis.jsx). One delegated handler per row, the
 * cells carrying data-day (a handler per cell re-rendered every cell).
 */
export default function ActivityStrip({ timeline, selectedDay, onSelectDay }) {
  const [tip, setTip] = useState(null)
  const stripRef = useRef(null)
  const combined = timeline?.combined || []
  const sources = timeline?.sources || {}
  const days = useMemo(() => combined.map(c => c.day), [combined])
  const win = useStripWindow(days, selectedDay)
  const view = win.view
  const totals = useMemo(() => combined.map(c => c.value || 0), [combined])
  const { columns, cellsClass, pitch } = useStripFit(stripRef, view.length)
  const dayAt = (e) => e.target && e.target.dataset ? e.target.dataset.day : null

  const rows = useMemo(() => SERIES.map(s => {
    const row = sources[s.key] || { days: [], max: 0 }
    const map = new Map(row.days.map(d => [d.day, d.value]))
    const ramp = SERIES_RAMPS[s.key]
    return (
      <div className="usn-row" key={s.key}>
        <div className="usn-rowhead" title={s.hint}><span className="usn-sw" style={{ background: s.color }} />{s.label}</div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const day = dayAt(e)
            if (!day) return
            setTip({ day, key: s.key, v: map.get(day) || 0, x: e.clientX, y: e.clientY })
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
          <span className="tl-title">What the AI agents did</span>
          <span className="tl-sub">from the agents' own session records &mdash; one cell per day including the quiet ones, click a day to see its sessions below</span>
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
          <div><b>{fmtInt(tip.v)}</b> {SERIES_LABEL[tip.key]}</div>
        </div>
      )}
    </div>
  )
}
