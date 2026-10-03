import React, { useEffect, useMemo, useRef, useState } from 'react'
import { PROVIDERS, PROVIDER_RAMPS, PROVIDER_LABEL } from './format.js'
import { fmtDay, fmtInt } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

/**
 * SRUM activity as a day strip: X is the day, Y is the provider.
 *
 * This was a GitHub-style contribution calendar - X weekday, Y week - which
 * grew DOWNWARD at 27px per week, so a year of SRUM data was 53 rows tall and
 * pushed the whole dashboard below the fold. The strip is a fixed
 * `providers x 22px` regardless of range, which is what the Shell Items,
 * Prefetch, LNK and MFT/USN dashboards already do.
 *
 * **Every day in the range is a cell, including the empty ones.** SRUM only
 * records while the service is running, so a day with no row at all means the
 * machine was off or the service was stopped - which the old strip erased by
 * simply not drawing that day.
 *
 * A range longer than six months is shown a window at a time, opening on its
 * most recent end; the navigator above the strip pages it and draws the whole
 * range at one bar per week. The cell still means one day. See DayAxis.jsx.
 */

const level = (v, max) => {
  if (!v || v <= 0) return 0
  if (!max) return 1
  const r = v / max
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

export default function HeatmapStack({ heatmaps, selectedDay, onSelect }) {
  const [tip, setTip] = useState(null)
  const stripRef = useRef(null)
  const combined = heatmaps?.combined || []
  const providers = heatmaps?.providers || {}
  const days = useMemo(() => combined.map(c => c.day), [combined])
  // Six months at a time (DayAxis.jsx): the strip draws `view`, and the
  // navigator above it pages the window and shows the whole range.
  const win = useStripWindow(days, selectedDay)
  const view = win.view
  const totals = useMemo(() => combined.map(c => c.value || 0), [combined])
  const { columns, cellsClass, pitch } = useStripFit(stripRef, view.length)


  const dayAt = (e) => e.target && e.target.dataset ? e.target.dataset.day : null

  // Memoised so the tooltip's state cannot re-render every cell on a mouse move.
  const rows = useMemo(() => PROVIDERS.map((prov) => {
    const pdata = providers[prov.key] || { days: [], max: 0 }
    const map = new Map(pdata.days.map(d => [d.day, d.value]))
    const ramp = PROVIDER_RAMPS[prov.key]
    return (
      <div className="usn-row" key={prov.key}>
        <div className="usn-rowhead">
          <span className="usn-sw" style={{ background: prov.color }} />{prov.label}
        </div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const day = dayAt(e)
            if (!day) return
            setTip({ day, prov: prov.key, val: map.get(day) || 0, x: e.clientX, y: e.clientY })
          }}
          onMouseLeave={() => setTip(null)}
          onClick={(e) => { const day = dayAt(e); if (day) onSelect(day) }}>
          {view.map(day => (
            <div key={day} data-day={day}
              className={'usn-cell' + (selectedDay === day ? ' sel' : '')}
              style={{ background: ramp[level(map.get(day) || 0, pdata.max)] }} />
          ))}
        </div>
      </div>
    )
  }), [providers, view, selectedDay, columns, cellsClass, onSelect])

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

      <div className="hm-hint">Each row is one SRUM provider &middot; one cell per day, quiet days included &middot; click a day to select it in all five and explore it below.</div>

      {tip && (
        <div className="cal-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 220), top: tip.y + 14 }}>
          <div className="tip-day">{fmtDay(tip.day)}</div>
          <div><b>{fmtInt(tip.val)}</b> {PROVIDER_LABEL[tip.prov]} records</div>
        </div>
      )}
    </div>
  )
}
