import React from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { SOURCES, SOURCE_COLOR, SOURCE_LABEL, TYPE_LABEL, fmtInt, fmtDay } from './format.js'
import { SourceLegend, MiniBars } from './OverviewPanel.jsx'
import ShellActivityTimeline from './ShellActivityTimeline.jsx'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

export default function DaySection({ day, detail, loading, activity, onOpenItem, onPickHour }) {
  if (!day) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a day in the activity strip to see the shell items recorded that day &mdash; which source,
          where they pointed, at what hour, and in what MRU order.
        </div>
      </section>
    )
  }
  const byHour = detail?.byHour || {}
  const events = detail?.events || []
  const bySource = detail?.bySource || []
  const topPlaces = detail?.topPlaces || []

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
          <div className="day-title">Recorded on {fmtDay(day)}</div>
          <div className="day-sub">{fmtInt(events.length)} shell items &mdash; click a row for the item's full profile.</div>
        </div>
        <SourceLegend />
      </div>

      {loading && <div className="loading-inline"><span className="spinner" />Loading day…</div>}

      <div className="detail-card" style={{ marginBottom: 14 }}>
        <div className="detail-card-title">Activity timeline &mdash; item &times; hour</div>
        {activity ? <ShellActivityTimeline data={activity} /> : <div className="detail-none small">Loading timeline…</div>}
      </div>

      <div className="win-grid">
        <div className="detail-card win-hours">
          <div className="detail-card-title">Items by hour (by source)</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
        </div>
        <div className="detail-card"><div className="detail-card-title">By source</div><MiniBars rows={bySource} labelOf={s => SOURCE_LABEL[s.source]} valueOf={s => s.n} colorOf={s => SOURCE_COLOR[s.source]} /></div>
        <div className="detail-card"><div className="detail-card-title">Top places</div><MiniBars rows={topPlaces} labelOf={p => p.place} valueOf={p => p.n} /></div>
      </div>

      <div className="detail-card" style={{ marginTop: 14 }}>
        <div className="detail-card-title">Shell items ({fmtInt(events.length)})</div>
        <div className="evt-table">
          <div className="evt-row si-row evt-head"><span>Time</span><span>Src</span><span>Target</span><span>Path</span><span>MRU</span></div>
          {events.slice(0, 400).map((e, i) => (
            <div className="evt-row si-row" key={i} onClick={() => onOpenItem(e.id)} title="Open item profile">
              <span className="evt-t">{String(e.t).slice(11, 19) || '—'}</span>
              <span><span className="cat-dot" style={{ background: SOURCE_COLOR[e.source] }} title={SOURCE_LABEL[e.source]} /></span>
              <span className="evt-file">{e.target || '—'} <span className="evt-type">{TYPE_LABEL[e.itemType] || ''}</span></span>
              <span className="evt-path" title={e.path}>{e.path || (e.volume || '')}</span>
              <span className="evt-size">{e.mru !== null && e.mru !== undefined ? '#' + e.mru : '—'}</span>
            </div>
          ))}
        </div>
      </div>

    </section>
  )
}
