import React from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { LOCATIONS, LOC_COLOR, fmtInt, fmtDay } from './format.js'
import { LocationLegend, MiniBars } from './OverviewPanel.jsx'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

export default function DaySection({ day, detail, loading, onOpenProgram, onPickHour }) {
  if (!day) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a day in the execution strip to see the programs that ran that day &mdash; from where, at
          what hour, and how many times.
        </div>
      </section>
    )
  }
  const byHour = detail?.byHour || {}
  const events = detail?.events || []
  const byProgram = detail?.byProgram || []
  const topDirs = detail?.topDirs || []

  const hourData = {
    labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    datasets: LOCATIONS.map(l => ({ label: l.label, backgroundColor: l.color, borderWidth: 0, data: byHour[l.key] || Array(24).fill(0) })),
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
          <div className="day-title">Ran on {fmtDay(day)}</div>
          <div className="day-sub">{fmtInt(events.length)} executions &mdash; click an hour for that hour, or a row for the program's full profile.</div>
        </div>
        <LocationLegend />
      </div>

      {loading && <div className="loading-inline"><span className="spinner" />Loading day…</div>}

      <div className="win-grid">
        <div className="detail-card win-hours">
          <div className="detail-card-title">Runs by hour (by location)</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
        </div>
        <div className="detail-card"><div className="detail-card-title">Top programs</div><MiniBars rows={byProgram} labelOf={p => p.exe} valueOf={p => p.n} /></div>
        <div className="detail-card"><div className="detail-card-title">Top directories</div><MiniBars rows={topDirs} labelOf={d => d.dir} valueOf={d => d.n} /></div>
      </div>

      <div className="detail-card" style={{ marginTop: 14 }}>
        <div className="detail-card-title">Executions ({fmtInt(events.length)})</div>
        <div className="evt-table">
          <div className="evt-row lnk-row evt-head"><span>Time</span><span>Loc</span><span>Program</span><span>Path</span><span>Runs</span></div>
          {events.slice(0, 400).map((e, i) => (
            <div className="evt-row lnk-row" key={i} onClick={() => onOpenProgram(e.filename)} title="Open program profile">
              <span className="evt-t">{String(e.t).slice(11, 19)}</span>
              <span><span className="cat-dot" style={{ background: LOC_COLOR[e.location] }} title={e.location} /></span>
              <span className="evt-file">{e.exe}</span>
              <span className="evt-path" title={e.path}>{e.path}</span>
              <span className="evt-size">{fmtInt(e.runCount)}&times;</span>
            </div>
          ))}
        </div>
      </div>

    </section>
  )
}
