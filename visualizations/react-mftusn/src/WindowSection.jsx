import React, { useState } from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { REASONS, REASON_COLOR, fmtInt, fmtBytes, fmtDay, baseName } from './format.js'
import { ReasonLegend } from './OverviewPanel.jsx'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

function CatDots({ cats }) {
  return (
    <span className="cat-dots">
      {(cats || []).map(c => <span key={c} className="cat-dot" style={{ background: REASON_COLOR[c] }} title={c} />)}
    </span>
  )
}

export default function WindowSection({ bucket, detail, loading, onOpenFile, onPickHour }) {
  if (!bucket) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a day in the USN journal strip to see the file-system changes it recorded —
          which files, in which hour, and what kind of change.
        </div>
      </section>
    )
  }
  const byHour = detail?.byHour || {}
  const events = detail?.events || []
  const topDirs = detail?.topDirs || []
  const topExts = detail?.topExts || []

  const hourData = {
    labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    datasets: REASONS.map(r => ({ label: r.label, backgroundColor: r.color, borderWidth: 0, data: byHour[r.key] || Array(24).fill(0) })),
  }
  const hourOpts = {
    responsive: true, maintainAspectRatio: false, animation: false,
    // The chart looked interactive and did nothing. els[0].index is the hour.
    onClick: (_e, els) => { if (els[0] && onPickHour) onPickHour(els[0].index) },
    onHover: (evt, els) => { if (evt.native) evt.native.target.style.cursor = els.length ? 'pointer' : 'default' },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
    scales: {
      x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 }, maxRotation: 0, autoSkip: true }, grid: { display: false } },
      y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(99,102,241,0.10)' }, beginAtZero: true },
    },
  }

  const label = fmtDay(bucket)

  return (
    <section className="day-section">
      <div className="day-head">
        <div>
          <div className="day-title">Activity in {label}</div>
          <div className="day-sub">{fmtInt(events.length)} file-system changes in this window — click a row for the file's full timeline.</div>
        </div>
        <ReasonLegend />
      </div>

      {loading && <div className="loading-inline"><span className="spinner" />Loading window…</div>}

      <div className="win-grid">
        <div className="detail-card win-hours">
          <div className="detail-card-title">Changes by hour (by category)</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Top directories</div>
          <MiniList rows={topDirs} labelOf={d => d.dir} valueOf={d => d.n} />
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Top file types</div>
          <MiniList rows={topExts} labelOf={e => e.ext} valueOf={e => e.n} />
        </div>
      </div>

      <div className="detail-card" style={{ marginTop: 14 }}>
        <div className="detail-card-title">Events ({fmtInt(events.length)})</div>
        <div className="evt-table">
          <div className="evt-row evt-head"><span>Time</span><span>Change</span><span>File</span><span>Path</span><span>Size</span></div>
          {events.slice(0, 400).map((e, i) => (
            <div className="evt-row" key={i} onClick={() => onOpenFile(e.rec)} title="Open file timeline">
              <span className="evt-t">{String(e.t).slice(11, 19)}</span>
              <span><CatDots cats={e.cats} /></span>
              <span className="evt-file">{e.fn || baseName(e.path)}</span>
              <span className="evt-path" title={e.path}>{e.path}</span>
              <span className="evt-size">{fmtBytes(e.size)}</span>
            </div>
          ))}
          {events.length > 400 && <div className="evt-more">Showing first 400 of {fmtInt(events.length)} — narrow the window or search to see the rest.</div>}
        </div>
      </div>

    </section>
  )
}

function MiniList({ rows, labelOf, valueOf }) {
  if (!rows.length) return <div className="detail-none small">No data.</div>
  const max = Math.max(1, ...rows.map(valueOf))
  return (
    <div className="mini-bars">
      {rows.map((r, i) => (
        <div className="mini-bar" key={i} title={`${labelOf(r)} — ${fmtInt(valueOf(r))}`}>
          <span className="mini-label">{labelOf(r)}</span>
          <span className="mini-track"><span className="mini-fill" style={{ width: `${(valueOf(r) / max) * 100}%` }} /></span>
          <span className="mini-val">{fmtInt(valueOf(r))}</span>
        </div>
      ))}
    </div>
  )
}
