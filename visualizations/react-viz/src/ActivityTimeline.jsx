import React, { useMemo, useState } from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, LinearScale, CategoryScale, PointElement, Tooltip, ScatterController,
} from 'chart.js'
import { fmtBytes, fmtInt, fmtDuration, fmtDay } from './format.js'

ChartJS.register(LinearScale, CategoryScale, PointElement, Tooltip, ScatterController)

// Distinct, colour-blind-friendlyish palette for users.
const USER_COLORS = ['#4aa8ff', '#39d353', '#fbbf24', '#f472b6', '#a78bfa',
  '#22d3ee', '#fb923c', '#94a3b8', '#34d399', '#e879f9']

const MAGNITUDES = {
  network: { label: 'Network (sent / received)', split: true },
  cpu: { label: 'CPU cycles', field: 'cpu', fmt: fmtInt },
  disk: { label: 'Disk bytes', field: 'disk', fmt: fmtBytes },
  presence: { label: 'User presence', field: 'focusS', fmt: fmtDuration },
}

// Shared geometry so the sticky hour ruler and the bubble chart line up exactly.
const Y_AXIS_W = 116          // forced left inset (app labels) — identical on both canvases
const PAD_RIGHT = 12
const ROW = 30                // px per app row
const RULER_H = 30            // sticky hour-ruler height (a single label row)
const SCROLL_MAX = 560        // timeline viewport cap before it scrolls internally
const X_MIN = -0.5, X_MAX = 23.5
const X_SPAN = X_MAX - X_MIN
const RULER_HOURS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
// pixel-fraction of the plot width for hour h (matches chart.js getPixelForValue)
const hourLeftPct = (h) => ((h - X_MIN) / X_SPAN) * 100

function radius(value, max) {
  if (!value || value <= 0) return 0
  return 4 + 16 * Math.sqrt(value / (max || 1))   // area ~ value
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

export default function ActivityTimeline({ data, onSelectApp, selectedApp }) {
  const [mag, setMag] = useState('network')
  const [hiddenUsers, setHiddenUsers] = useState(() => new Set())

  const apps = data?.apps || []
  const users = data?.users || []
  const ranges = data?.ranges || {}
  const points = data?.points || []

  const colorFor = useMemo(() => {
    const m = new Map(users.map((u, i) => [u, USER_COLORS[i % USER_COLORS.length]]))
    return (u) => m.get(u) || '#94a3b8'
  }, [users])

  const { datasets } = useMemo(() => {
    const visible = points.filter(p => !hiddenUsers.has(p.user))
    const toXY = (p) => ({ x: p.h, y: p.app, _p: p })   // X = hour of day (0-23)
    let ds = []
    if (MAGNITUDES[mag].split) {
      const maxS = Math.max(1, ...visible.map(p => p.bytesSent))
      const maxR = Math.max(1, ...visible.map(p => p.bytesReceived))
      ds = [
        { label: 'Sent', pointStyle: 'triangle',
          data: visible.filter(p => p.bytesSent > 0).map(p => ({ ...toXY(p), r: radius(p.bytesSent, maxS) })),
          backgroundColor: (c) => colorFor(c.raw?._p.user) + 'cc',
          borderColor: (c) => colorFor(c.raw?._p.user), borderWidth: 1,
          pointRadius: (c) => c.raw?.r || 0, hoverBorderWidth: 2 },
        { label: 'Received', pointStyle: 'triangle', rotation: 180,
          data: visible.filter(p => p.bytesReceived > 0).map(p => ({ ...toXY(p), r: radius(p.bytesReceived, maxR) })),
          // outline-only so a sent+received overlap reads as a filled ▲ inside a
          // ▽ outline, not a solid 6-point star.
          backgroundColor: 'transparent',
          borderColor: (c) => colorFor(c.raw?._p.user), borderWidth: 1.75,
          pointRadius: (c) => c.raw?.r || 0, hoverBorderWidth: 2.5 },
      ]
    } else {
      const f = MAGNITUDES[mag].field
      const mx = Math.max(1, ...visible.map(p => p[f]))
      ds = [{ label: MAGNITUDES[mag].label, pointStyle: 'circle',
        data: visible.filter(p => p[f] > 0).map(p => ({ ...toXY(p), r: radius(p[f], mx) })),
        backgroundColor: (c) => colorFor(c.raw?._p.user) + 'aa',
        borderColor: (c) => colorFor(c.raw?._p.user), borderWidth: 1,
        pointRadius: (c) => c.raw?.r || 0, hoverBorderWidth: 2 }]
    }
    return { datasets: ds }
  }, [points, mag, hiddenUsers, colorFor])

  // Faint bar behind each app row = its active time range.
  const rangePlugin = useMemo(() => ({
    id: 'rangeBars',
    beforeDatasetsDraw(chart) {
      const { ctx, scales: { x, y } } = chart
      ctx.save()
      for (const app of apps) {
        const rg = ranges[app]
        if (!rg) continue
        const x1 = x.getPixelForValue(rg.min)
        const x2 = x.getPixelForValue(rg.max)
        const yc = y.getPixelForValue(app)
        if (isNaN(yc)) continue
        ctx.fillStyle = app === selectedApp ? 'rgba(99,102,241,0.18)' : 'rgba(99,102,241,0.055)'
        const h = 16
        roundedRect(ctx, Math.min(x1, x2) - 5, yc - h / 2, Math.abs(x2 - x1) + 10, h, 7)
        ctx.fill()
      }
      ctx.restore()
    },
  }), [apps, ranges, selectedApp])

  const labels = useMemo(() => [...apps].reverse(), [apps])

  // Main bubble chart — hour ticks hidden (the sticky ruler shows them); gridlines kept.
  const options = useMemo(() => ({
    responsive: true, maintainAspectRatio: false, animation: false,
    layout: { padding: { right: PAD_RIGHT } },
    interaction: { mode: 'nearest', intersect: true },
    onClick: (_e, els, chart) => {
      if (els[0]) {
        const p = chart.data.datasets[els[0].datasetIndex].data[els[0].index]
        if (p?._p?.app) onSelectApp(p._p.app)
      }
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        // Sent (▲) and Received (▼) are two datasets over the SAME record; keep
        // one tooltip item per underlying point so the detail block isn't doubled.
        filter: (item, i, arr) => arr.findIndex(x => x.raw?._p === item.raw?._p) === i,
        callbacks: {
          title: (items) => { const p = items[0]?.raw?._p; return p ? `${p.app}` : '' },
          label: (item) => {
            const p = item.raw?._p; if (!p) return ''
            return [
              `User: ${p.user}`,
              `Hour: ${String(p.h).padStart(2, '0')}:00`,
              `Sent: ${fmtBytes(p.bytesSent)}   Received: ${fmtBytes(p.bytesReceived)}`,
              `CPU cycles: ${fmtInt(p.cpu)}   Disk: ${fmtBytes(p.disk)}`,
              `Battery: ${p.battery || 0}%   Focus: ${fmtDuration(p.focusS)}   Keyboard: ${fmtDuration(p.keyboardS)}`,
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
        ticks: { color: '#cbd5e1', font: { size: 13 } }, grid: { color: 'rgba(99,102,241,0.10)' } },
    },
  }), [labels, onSelectApp])

  const innerH = Math.max(240, apps.length * ROW)
  const scrollH = Math.min(innerH + RULER_H, SCROLL_MAX)

  return (
    <div className="atl">
      <div className="atl-controls">
        <div className="atl-mag">
          {Object.entries(MAGNITUDES).map(([k, m]) => (
            <button key={k} className={'atl-mag-btn' + (mag === k ? ' on' : '')} onClick={() => setMag(k)}>{m.label}</button>
          ))}
        </div>
        <div className="atl-note">Bubble size = magnitude &middot; &#9650; sent &#9663; received &middot; click an app for its full profile</div>
      </div>

      <div className="atl-apps">
        {apps.map(a => (
          <button key={a} className={'atl-app' + (a === selectedApp ? ' on' : '')}
            onClick={() => onSelectApp(a)} title={`Show ${a} profile`}>{a}</button>
        ))}
      </div>

      <div className="atl-scroll" style={{ height: scrollH }}>
        <div className="atl-hourbar" style={{ height: RULER_H }}>
          <div className="atl-hb-spacer" style={{ width: Y_AXIS_W }}>Hour of day</div>
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
        <span className="atl-legend-title">Users:</span>
        {users.map((u) => (
          <button key={u} className={'atl-user' + (hiddenUsers.has(u) ? ' off' : '')}
            onClick={() => setHiddenUsers(s => { const n = new Set(s); n.has(u) ? n.delete(u) : n.add(u); return n })}>
            <span className="atl-swatch" style={{ background: colorFor(u) }} />{u}
          </button>
        ))}
      </div>
    </div>
  )
}
