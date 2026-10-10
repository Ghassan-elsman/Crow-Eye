import React, { useMemo, useRef, useState } from 'react'
import { flagColor, flagRamp, flagLabel, fmtInt, fmtDay } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

// Log scale. File-system activity is heavy-tailed: one install or update day
// can hold 100x an ordinary one, and on a linear ramp every other day of the
// range fell into the first step - six months of identical cells.
const level = (v, max) => {
  if (!v || v <= 0) return 0
  const r = Math.log1p(v) / Math.log1p(max || 1)
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

// One strip on one day axis for both sources. The MFT used to be a Chart.js
// bar chart at 2px a day across the machine's whole history (~19,500px on a
// 26-year range, past the canvas limit on a HiDPI screen) above a separate
// USN strip on its own axis - so a burst of creations could not be read
// against the journal at all. Now: MFT Created / Modified (distinct files)
// and one row per USN reason flag (journal records), six months at a time.
export default function TimelineStack({ timelines, selectedBucket, onSelectBucket }) {
  const [tip, setTip] = useState(null)
  const stripRef = useRef(null)
  const combined = timelines?.combined || []
  const series = timelines?.series || {}
  const rowsMeta = timelines?.rows || []
  const keys = useMemo(() => combined.map(c => c.key), [combined])
  // Six months at a time (DayAxis.jsx): the strip draws `view`, and the
  // navigator above it pages the window and shows the whole range.
  const win = useStripWindow(keys, selectedBucket)
  const view = win.view
  const totals = useMemo(() => combined.map(c => c.value || 0), [combined])
  const { columns, cellsClass, pitch } = useStripFit(stripRef, view.length)

  const keyAt = (e) => e.target && e.target.dataset ? e.target.dataset.day : null

  // Memoised so the tooltip's state cannot re-render every cell on a mouse move.
  const rows = useMemo(() => rowsMeta.map((meta, i) => {
    const row = series[meta.key] || { buckets: [], max: 0 }
    const map = new Map(row.buckets.map(b => [b.key, b.value]))
    const ramp = flagRamp(meta.key)
    const first = i > 0 && rowsMeta[i - 1].group !== meta.group
    return (
      <div className={'usn-row' + (first ? ' usn-row--group' : '')} key={meta.key}>
        <div className="usn-rowhead" title={`${meta.label} - ${fmtInt(meta.total)} in all`}>
          <span className="usn-sw" style={{ background: flagColor(meta.key) }} />
          <span className="usn-rowlabel">{meta.group === 'mft' ? flagLabel(meta.key) : meta.label}</span>
        </div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const k = keyAt(e)
            if (!k) return
            setTip({ k, row: meta, v: map.get(k) || 0, x: e.clientX, y: e.clientY })
          }}
          onMouseLeave={() => setTip(null)}
          onClick={(e) => { const k = keyAt(e); if (k) onSelectBucket(k) }}>
          {view.map((k) => (
            <div key={k} data-day={k}
              className={'usn-cell' + (selectedBucket === k ? ' sel' : '')}
              style={{ background: ramp[level(map.get(k) || 0, row.max)] }} />
          ))}
        </div>
      </div>
    )
  }), [series, rowsMeta, view, selectedBucket, columns, cellsClass, onSelectBucket])

  const t = timelines?.totals || {}
  return (
    <div className="tl">
      <div className="tl-block">
        <div className="tl-head">
          <span className="tl-title">MFT and USN on one timeline</span>
          <span className="tl-sub">
            files created / modified (MFT Standard-Info, distinct files) and every USN reason flag
            (journal records) &mdash; one cell per day, quiet days included, shade on a log scale; click a day to explore it below
          </span>
          <span className="tl-legend">
            <span className="tl-leg"><b>{fmtInt(t.mftCreated)}</b>&nbsp;created</span>
            <span className="tl-leg"><b>{fmtInt(t.mftModified)}</b>&nbsp;modified</span>
            <span className="tl-leg"><b>{fmtInt(t.usnEvents)}</b>&nbsp;USN records</span>
          </span>
          {(t.mftOutsideCreated > 0 || t.mftOutsideModified > 0) && (
            <span className="tl-sub tl-outside"
              title="A Standard-Info time before 1980 or after 2099 is a zero or damaged value, not a date to draw. These files are still in the lists and the search.">
              not drawn: {fmtInt(t.mftOutsideCreated)} created / {fmtInt(t.mftOutsideModified)} modified
              time outside 1980&ndash;2099
            </span>
          )}
        </div>
        <StripNavigator win={win} days={keys} totals={totals} />
        <div className="usn-strip" ref={stripRef}>
          <div className="usn-axis">
            <div className="usn-rowhead usn-unit">1 cell = 1 day</div>
            <DayAxis days={view} columns={columns} pitch={pitch} />
          </div>
          {rows}
        </div>
      </div>

      {tip && (
        <div className="cal-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 240), top: tip.y + 14 }}>
          <div className="tip-day">{fmtDay(tip.k)}</div>
          <div><span className="usn-sw" style={{ background: flagColor(tip.row.key), display: 'inline-block', marginRight: 6 }} />
            <b>{fmtInt(tip.v)}</b> {tip.row.group === 'mft'
              ? (tip.row.key === 'mft_created' ? 'files created' : 'files modified')
              : `USN records with ${tip.row.label}`}</div>
        </div>
      )}
    </div>
  )
}
