import React, { useMemo, useState } from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, LinearScale, CategoryScale, PointElement, Tooltip, ScatterController,
} from 'chart.js'
import { SOURCES, SOURCE_COLOR, SOURCE_LABEL, fmtInt } from './format.js'

ChartJS.register(LinearScale, CategoryScale, PointElement, Tooltip, ScatterController)

// Shared geometry so the sticky hour ruler and the bubble chart line up exactly.
const Y_AXIS_W = 150
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

export default function ShellActivityTimeline({ data }) {
  const [hidden, setHidden] = useState(() => new Set())

  const items = data?.items || []
  const ranges = data?.ranges || {}
  const points = data?.points || []
  const present = useMemo(() => SOURCES.filter(s => points.some(p => p.source === s.key)), [points])

  const datasets = useMemo(() => {
    const visible = points.filter(p => !hidden.has(p.source))
    const max = Math.max(1, ...visible.map(p => p.value))
    // one dataset per source so colour + legend stay coherent
    return present.filter(s => !hidden.has(s.key)).map(s => ({
      label: s.label,
      data: visible.filter(p => p.source === s.key).map(p => ({ x: p.hour, y: p.item, r: radius(p.value, max), _p: p })),
      backgroundColor: s.color + 'bb',
      borderColor: s.color,
      borderWidth: 1,
      pointRadius: (c) => c.raw?.r || 0,
      hoverBorderWidth: 2,
      pointStyle: 'circle',
    }))
  }, [points, hidden, present])

  // Faint bar behind each item row = its active hour range that day.
  const rangePlugin = useMemo(() => ({
    id: 'shellRangeBars',
    beforeDatasetsDraw(chart) {
      const { ctx, scales: { x, y } } = chart
      ctx.save()
      for (const item of items) {
        const rg = ranges[item]
        if (!rg) continue
        const x1 = x.getPixelForValue(rg.min)
        const x2 = x.getPixelForValue(rg.max)
        const yc = y.getPixelForValue(item)
        if (isNaN(yc)) continue
        ctx.fillStyle = 'rgba(99,102,241,0.06)'
        const h = 14
        roundedRect(ctx, Math.min(x1, x2) - 5, yc - h / 2, Math.abs(x2 - x1) + 10, h, 6)
        ctx.fill()
      }
      ctx.restore()
    },
  }), [items, ranges])

  const labels = useMemo(() => [...items].reverse(), [items])

  const options = useMemo(() => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    layout: { padding: { right: PAD_RIGHT } },
    interaction: { mode: 'nearest', intersect: true },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (its) => { const p = its[0]?.raw?._p; return p ? p.item : '' },
          label: (item) => {
            const p = item.raw?._p; if (!p) return ''
            return [
              `${SOURCE_LABEL[p.source]}`,
              `Hour: ${String(p.hour).padStart(2, '0')}:00`,
              `Referenced: ${fmtInt(p.value)}×`,
            ]
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
    return <div className="detail-none small">No timed items on this day.</div>
  }

  const innerH = Math.max(200, items.length * ROW)
  const scrollH = Math.min(innerH + RULER_H, SCROLL_MAX)

  return (
    <div className="atl">
      <div className="atl-controls">
        <div className="atl-note">Item &times; hour of day &middot; bubble size = times referenced &middot; colour = source. Most MRUs carry one time, so they read as a single bubble; Shellbags spread out.</div>
      </div>

      <div className="atl-scroll" style={{ height: scrollH }}>
        <div className="atl-hourbar" style={{ height: RULER_H }}>
          <div className="atl-hb-spacer" style={{ width: Y_AXIS_W }}>Item</div>
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
        <span className="atl-legend-title">Sources:</span>
        {present.map((s) => (
          <button key={s.key} className={'atl-user' + (hidden.has(s.key) ? ' off' : '')}
            onClick={() => setHidden(h => { const n = new Set(h); n.has(s.key) ? n.delete(s.key) : n.add(s.key); return n })}>
            <span className="atl-swatch" style={{ background: s.color }} />{s.label}
          </button>
        ))}
      </div>
    </div>
  )
}
