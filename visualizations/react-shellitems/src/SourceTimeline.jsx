import React, { useEffect, useMemo, useRef, useState } from 'react'
import { SOURCES, SOURCE_RAMPS, SOURCE_LABEL, fmtInt, fmtDay } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

const level = (v, max) => {
  if (!v || v <= 0) return 0
  const r = v / (max || 1)
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

/**
 * Shell-item activity as a day strip: X is the day, Y is the artifact source.
 *
 * This case spans 2014-03-18 to 2026-09-18 - **4,568 days**, of which 146 carry
 * anything. All 4,568 are drawn, because which years were quiet is the question
 * a registry MRU is usually being asked. The strip shows six months of them at
 * a time and the navigator's overview shows all twelve years; the unit stays
 * one day. See DayAxis.jsx.
 *
 * At that size the rows are ~32,000 cells, so the tooltip cannot be allowed to
 * re-render them: the cells carry their day in a `data-` attribute, one handler
 * on the row reads it, and the rows are memoised away from the tooltip's state.
 * With a handler per cell, moving the mouse re-rendered all 32,000.
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

  // Sixteen sources, most of them empty on any one machine: only the ones
  // with something in this range get a row (all of them if none do, so the
  // strip keeps its shape). Every source still has its count, and the reason
  // an empty one is empty, in the overview.
  const shown = useMemo(() => {
    const live = SOURCES.filter(src => (sources[src.key]?.max || 0) > 0)
    return live.length ? live : SOURCES
  }, [sources])

  const rows = useMemo(() => shown.map(src => {
    const row = sources[src.key] || { days: [], max: 0 }
    const map = new Map(row.days.map(d => [d.day, d.value]))
    // A source without its own ramp must not throw during render - that
    // blanks the whole dashboard with no visible error.
    const ramp = SOURCE_RAMPS[src.key] || SOURCE_RAMPS.search
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
  }), [shown, sources, view, selectedDay, columns, cellsClass, onSelectDay])

  return (
    <div className="tl">
      <div className="tl-block">
        <div className="tl-head">
          <span className="tl-title">Shell-item activity</span>
          <span className="tl-sub">rows by artifact source, best-available time each &mdash; one cell per day including the quiet ones, click a day to explore it below</span>
        </div>
        <StripNavigator win={win} days={days} totals={totals} />
        <div className="usn-strip" ref={stripRef}>
          <div className="usn-axis">
            <div className="usn-rowhead usn-unit">1 cell = 1 day</div>
            <DayAxis days={view} columns={columns} pitch={pitch} />
          </div>
          {rows}
        </div>
        <div className="hm-hint">Registry-based MRUs mostly carry one key-write time, so their rows cluster on a day; Shellbags carry per-folder times and spread out.</div>
      </div>

      {tip && (
        <div className="cal-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 220), top: tip.y + 14 }}>
          <div className="tip-day">{fmtDay(tip.day)}</div>
          <div><b>{fmtInt(tip.v)}</b> {SOURCE_LABEL[tip.src]}</div>
        </div>
      )}
    </div>
  )
}
