import React from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { SOURCES, SOURCE_COLOR, fmtInt, fmtDay, baseName } from './format.js'
import { SourceLegend, MiniBars } from './OverviewPanel.jsx'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

export default function DaySection({ day, detail, loading, onOpenTarget, onPickHour }) {
  if (!day) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a day in the activity strip to see the files opened that day &mdash; by which app, from which
          volume, and when.
        </div>
      </section>
    )
  }
  const byHour = detail?.byHour || {}
  const events = detail?.events || []
  const byApp = detail?.byApp || []
  const topDirs = detail?.topDirs || []
  const topExts = detail?.topExts || []

  const hourData = {
    labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    datasets: SOURCES.map(s => ({ label: s.label, backgroundColor: s.color, borderWidth: 0, data: byHour[s.key] || Array(24).fill(0) })),
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

  return (
    <section className="day-section">
      <div className="day-head">
        <div>
          <div className="day-title">Opened on {fmtDay(day)}</div>
          <div className="day-sub">{fmtInt(events.length)} opens &mdash; click a row for the target's full profile.</div>
        </div>
        <SourceLegend />
      </div>

      {loading && <div className="loading-inline"><span className="spinner" />Loading day…</div>}

      <div className="win-grid">
        <div className="detail-card win-hours">
          <div className="detail-card-title">Opens by hour (by source)</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
        </div>
        <div className="detail-card"><div className="detail-card-title">By application</div><MiniBars rows={byApp} labelOf={a => a.app} valueOf={a => a.n} /></div>
        <div className="detail-card"><div className="detail-card-title">Top directories</div><MiniBars rows={topDirs} labelOf={d => d.dir} valueOf={d => d.n} /></div>
      </div>

      <div className="detail-card" style={{ marginTop: 14 }}>
        <div className="detail-card-title">Opens ({fmtInt(events.length)})</div>
        <div className="evt-table">
          <div className="evt-row lnk-row evt-head"><span>Time</span><span>Src</span><span>App</span><span>Target</span><span>Volume</span></div>
          {events.slice(0, 400).map((e, i) => (
            <div className="evt-row lnk-row" key={i} onClick={() => e.target && onOpenTarget(e.target)} title={e.target ? 'Open target profile' : ''}>
              <span className="evt-t">{String(e.t).slice(11, 19) || '—'}</span>
              <span><span className="cat-dot" style={{ background: SOURCE_COLOR[e.source] }} title={e.source} /></span>
              <span className="evt-file">{e.app || '—'}</span>
              <span className="evt-path" title={e.target}>{e.target || `(${e.source})`}</span>
              <span className="evt-size">{e.volume || '—'}</span>
            </div>
          ))}
        </div>
      </div>

    </section>
  )
}
