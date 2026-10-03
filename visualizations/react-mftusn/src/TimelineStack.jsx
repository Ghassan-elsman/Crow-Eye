import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { REASONS, REASON_RAMPS, REASON_LABEL, MFT_CREATED, MFT_MODIFIED, fmtInt, fmtDay } from './format.js'
import DayAxis, { useStripFit, useStripWindow, StripNavigator } from './DayAxis.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

const level = (v, max) => {
  if (!v || v <= 0) return 0
  const r = v / (max || 1)
  return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4
}

// One bar per day on the MFT chart. Measured on one case the range is
// 2000-01-01 to 2026-09-18 - 9,758 days, of which 954 carry anything - so the
// chart is ~19,500px wide and scrolls, like the strip below it.
const MFT_BAR_PX = 2

export default function TimelineStack({ timelines, selectedBucket, onSelectBucket }) {
  const [tip, setTip] = useState(null)
  const stripRef = useRef(null)
  const mftRef = useRef(null)
  const combined = timelines?.combined || []
  const usn = timelines?.usnEvents || {}
  const keys = useMemo(() => combined.map(c => c.key), [combined])
  // Six months at a time (DayAxis.jsx): the strip draws `view`, and the
  // navigator above it pages the window and shows the whole range.
  const win = useStripWindow(keys, selectedBucket)
  const view = win.view
  const totals = useMemo(() => combined.map(c => c.value || 0), [combined])
  const { columns, cellsClass, pitch } = useStripFit(stripRef, view.length)

  // --- MFT history: created + modified, one stacked bar per day ---------
  const mh = timelines?.mftHistory || []
  const mftWidth = mh.length * MFT_BAR_PX
  const mftData = useMemo(() => ({
    labels: mh.map(d => d.day),
    datasets: [
      { label: 'Created', backgroundColor: MFT_CREATED, borderWidth: 0, data: mh.map(d => d.created), stack: 'm' },
      { label: 'Modified', backgroundColor: MFT_MODIFIED, borderWidth: 0, data: mh.map(d => d.modified), stack: 'm' },
    ],
  }), [mh])
  const mftOpts = useMemo(() => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (i) => fmtDay(i[0].label),
          label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}`,
        },
      },
    },
    scales: {
      x: {
        stacked: true, grid: { display: false },
        ticks: {
          color: '#94a3b8', font: { size: 10 }, maxRotation: 0, autoSkip: true,
          // A label roughly every 90px, whatever the range - ten ticks spread
          // over 19,500px would leave most viewports with none.
          maxTicksLimit: Math.max(6, Math.round(mftWidth / 90)),
          callback(i) { return String(this.getLabelForValue(i)).slice(0, 7) },
        },
      },
      y: {
        stacked: true, beginAtZero: true,
        ticks: { color: '#94a3b8', font: { size: 10 } },
        grid: { color: 'rgba(99,102,241,0.10)' },
      },
    },
  }), [mftWidth])

  // Both the chart and the strip open on the most recent end.
  useEffect(() => {
    if (mftRef.current && mh.length) mftRef.current.scrollLeft = mftRef.current.scrollWidth
  }, [mh.length])


  const keyAt = (e) => e.target && e.target.dataset ? e.target.dataset.day : null

  // Memoised so the tooltip's state cannot re-render every cell on a mouse move.
  const rows = useMemo(() => REASONS.map(cat => {
    const row = usn[cat.key] || { buckets: [], max: 0 }
    const map = new Map(row.buckets.map(b => [b.key, b.value]))
    const ramp = REASON_RAMPS[cat.key]
    return (
      <div className="usn-row" key={cat.key}>
        <div className="usn-rowhead"><span className="usn-sw" style={{ background: cat.color }} />{cat.label}</div>
        <div className={cellsClass} style={{ gridTemplateColumns: columns }}
          onMouseMove={(e) => {
            const k = keyAt(e)
            if (!k) return
            setTip({ k, cat: cat.key, v: map.get(k) || 0, x: e.clientX, y: e.clientY })
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
  }), [usn, view, selectedBucket, columns, cellsClass, onSelectBucket])

  return (
    <div className="tl">
      <div className="tl-block">
        <div className="tl-head">
          <span className="tl-title">MFT history</span>
          <span className="tl-sub">files created / modified over the machine's history (Standard-Info times) &mdash; one bar per day, quiet days included</span>
          <span className="tl-legend">
            <span className="tl-leg"><span className="tl-sw" style={{ background: MFT_CREATED }} />Created</span>
            <span className="tl-leg"><span className="tl-sw" style={{ background: MFT_MODIFIED }} />Modified</span>
          </span>
        </div>
        <div className="tl-mft tl-mft--scroll" ref={mftRef}>
          <div className="tl-mft-inner" style={{ width: Math.max(mftWidth, 100) }}>
            <Chart type="bar" data={mftData} options={mftOpts} />
          </div>
        </div>
      </div>

      <div className="tl-block">
        <div className="tl-head">
          <span className="tl-title">USN journal events</span>
          <span className="tl-sub">file-system changes in the journal window &mdash; one cell per day including the quiet ones, click a day to explore it below</span>
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
        <div className="cal-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 220), top: tip.y + 14 }}>
          <div className="tip-day">{fmtDay(tip.k)}</div>
          <div><b>{fmtInt(tip.v)}</b> {REASON_LABEL[tip.cat]} events</div>
        </div>
      )}
    </div>
  )
}
