import React, { useMemo, useState } from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, LinearScale, CategoryScale, PointElement, Tooltip, ScatterController,
} from 'chart.js'
import { ACTIVITIES, ACTIVITY_LABEL, fmtInt } from './format.js'

ChartJS.register(LinearScale, CategoryScale, PointElement, Tooltip, ScatterController)

// Ported from react-viz/src/ActivityTimeline.jsx by way of react-shellitems.
// Geometry, radius(), roundedRect() and the range-bar plugin are unchanged; the
// Y axis is the DOMAIN and the series are activity types.

// Shared geometry so the sticky hour ruler and the bubble chart line up exactly.
const Y_AXIS_W = 190
const LABEL_CHARS = Math.floor((Y_AXIS_W - 8) / (12 * 0.56))
const PAD_RIGHT = 12
const ROW = 26
const RULER_H = 30
const SCROLL_MAX = 520
const X_MIN = -0.5, X_MAX = 23.5
const X_SPAN = X_MAX - X_MIN
const RULER_HOURS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
const hourLeftPct = (h) => ((h - X_MIN) / X_SPAN) * 100


// The axis is a fixed width (it must match the sticky ruler), and chart.js
// draws a longer label past the canvas edge, so a name lost its start
// ('sbarbitrator64.exe' for an Xbox service). Cut in the middle instead: the
// start and the end (extension, TLD, last folder) stay readable; the full
// name is in the tooltip.
function shortLabel(s, max) {
  s = String(s ?? '')
  if (s.length <= max) return s
  const tail = Math.min(10, Math.floor(max / 3))
  return s.slice(0, max - tail - 1) + '\u2026' + s.slice(-tail)
}
function radius(value, max) {
  if (!value || value <= 0) return 0
  return 4 + 13 * Math.sqrt(value / (max || 1))   // area ~ value
}

// ctx.roundRect() is missing in older QWebEngine builds - draw it by hand.
function roundedRect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

export default function BrowserActivityTimeline({ data }) {
  const [hidden, setHidden] = useState(() => new Set())

  const domains = data?.domains || []
  const ranges = data?.ranges || {}
  const points = data?.points || []
  const present = useMemo(
    () => ACTIVITIES.filter(a => points.some(p => p.activity === a.key)), [points])

  const datasets = useMemo(() => {
    const visible = points.filter(p => !hidden.has(p.activity))
    const max = Math.max(1, ...visible.map(p => p.n))
    // one dataset per activity so colour + legend stay coherent
    return present.filter(a => !hidden.has(a.key)).map(a => ({
      label: a.label,
      data: visible.filter(p => p.activity === a.key)
        .map(p => ({ x: p.h, y: p.domain, r: radius(p.n, max), _p: p })),
      backgroundColor: a.color + 'bb',
      borderColor: a.color,
      borderWidth: 1,
      pointRadius: (c) => c.raw?.r || 0,
      hoverBorderWidth: 2,
      pointStyle: 'circle',
    }))
  }, [points, hidden, present])

  // Faint bar behind each domain row = the hours it was active that day.
  const rangePlugin = useMemo(() => ({
    id: 'browserRangeBars',
    beforeDatasetsDraw(chart) {
      const { ctx, scales: { x, y } } = chart
      ctx.save()
      for (const domain of domains) {
        const rg = ranges[domain]
        if (!rg) continue
        const x1 = x.getPixelForValue(rg.min)
        const x2 = x.getPixelForValue(rg.max)
        const yc = y.getPixelForValue(domain)
        if (isNaN(yc)) continue
        ctx.fillStyle = 'rgba(99,102,241,0.06)'
        const h = 14
        roundedRect(ctx, Math.min(x1, x2) - 5, yc - h / 2, Math.abs(x2 - x1) + 10, h, 6)
        ctx.fill()
      }
      ctx.restore()
    },
  }), [domains, ranges])

  const labels = useMemo(() => [...domains].reverse(), [domains])

  const options = useMemo(() => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    layout: { padding: { right: PAD_RIGHT } },
    interaction: { mode: 'nearest', intersect: true },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (its) => { const p = its[0]?.raw?._p; return p ? p.domain : '' },
          label: (item) => {
            const p = item.raw?._p; if (!p) return ''
            const out = [
              `${ACTIVITY_LABEL[p.activity]}`,
              `Hour: ${String(p.h).padStart(2, '0')}:00`,
              `Events: ${fmtInt(p.n)}`,
            ]
            if (p.browser) out.push(`Browser: ${p.browser}`)
            return out
          },
        },
      },
    },
    scales: {
      x: { type: 'linear', min: X_MIN, max: X_MAX,
        ticks: { display: false }, border: { display: false },
        grid: { color: 'rgba(99,102,241,0.10)', tickLength: 0 } },
      y: { type: 'category', labels, offset: true,
        afterFit: (s) => { s.width = Y_AXIS_W },
        ticks: { color: '#cbd5e1', font: { size: 12 },
          callback(v) { return shortLabel(this.getLabelForValue(v), LABEL_CHARS) } }, grid: { color: 'rgba(99,102,241,0.10)' } },
    },
  }), [labels])

  if (!points.length) {
    return <div className="detail-none small">No timed browser activity on this day.</div>
  }

  const innerH = Math.max(200, domains.length * ROW)
  const scrollH = Math.min(innerH + RULER_H, SCROLL_MAX)

  return (
    <div className="atl">
      <div className="atl-controls">
        <div className="atl-note">Domain &times; hour of day &middot; bubble size = events &middot; colour = activity. A domain with cookies and cache but no visits is a site reached without a surviving history row.</div>
      </div>

      <div className="atl-scroll" style={{ height: scrollH }}>
        <div className="atl-hourbar" style={{ height: RULER_H }}>
          <div className="atl-hb-spacer" style={{ width: Y_AXIS_W }}>Domain</div>
          <div className="atl-hb-track" style={{ marginRight: PAD_RIGHT }}>
            {RULER_HOURS.map(h => (
              <span key={h} className="atl-hb-tick" style={{ left: `${hourLeftPct(h)}%` }}>
                {String(h).padStart(2, '0')}:00
              </span>
            ))}
          </div>
        </div>
        <div className="atl-chart" style={{ height: innerH }}>
          <Chart type="scatter" data={{ datasets }} options={options} plugins={[rangePlugin]} />
        </div>
      </div>

      <div className="atl-legend">
        <span className="atl-legend-title">Activity:</span>
        {present.map((a) => (
          <button key={a.key} className={'atl-user' + (hidden.has(a.key) ? ' off' : '')}
            onClick={() => setHidden(h => { const n = new Set(h); n.has(a.key) ? n.delete(a.key) : n.add(a.key); return n })}>
            <span className="atl-swatch" style={{ background: a.color }} />{a.label}
          </button>
        ))}
      </div>
    </div>
  )
}
