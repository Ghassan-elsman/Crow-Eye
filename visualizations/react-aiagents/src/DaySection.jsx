import React from 'react'
import { Chart } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip } from 'chart.js'
import { SERIES, SERIES_COLOR, fmtInt, fmtDay } from './format.js'
import { SeriesLegend } from './OverviewPanel.jsx'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

export default function DaySection({ day, detail, loading, onOpenSession, onOpenProgram, onPickHour }) {
  if (!day) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a day in the strip to see that day's agent sessions, what they ran and changed, hour by hour.
        </div>
      </section>
    )
  }
  const byHour = detail?.byHour || {}
  const events = detail?.events || []
  const sessions = detail?.sessions || []
  const total = detail?.total || 0
  const hourData = {
    labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    datasets: SERIES.map(s => ({ label: s.label, backgroundColor: s.color, borderWidth: 0, data: byHour[s.key] || Array(24).fill(0) })),
  }
  const hourOpts = {
    responsive: true, maintainAspectRatio: false, animation: false,
    onClick: (_e, els) => { if (els[0] && onPickHour) onPickHour(els[0].index) },
    onHover: (evt, els) => { if (evt.native) evt.native.target.style.cursor = els.length ? 'pointer' : 'default' },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
    scales: {
      x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 }, maxRotation: 0, autoSkip: true }, grid: { display: false } },
      y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(34,211,238,0.10)' }, beginAtZero: true },
    },
  }

  return (
    <section className="day-section">
      <div className="day-head">
        <div>
          <div className="day-title">{fmtDay(day)}</div>
          <div className="day-sub">{fmtInt(sessions.length)} session{sessions.length === 1 ? '' : 's'} &middot; {fmtInt(total)} acts &mdash; click an hour, a session, or a step's program.</div>
        </div>
        <SeriesLegend />
      </div>
      {loading && <div className="loading-inline"><span className="spinner" />Loading day…</div>}

      <div className="win-grid ai-day-grid">
        <div className="detail-card win-hours">
          <div className="detail-card-title">Acts by hour</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Sessions this day ({fmtInt(sessions.length)})</div>
          <div className="sess-list">
            {sessions.map((s, i) => (
              <div className="sess-row" key={i} onClick={() => onOpenSession(s.key)} title="Open the session: its story, what Windows recorded of it">
                <span className="sess-agent">{s.agent}</span>
                <span className="sess-title" title={s.title && s.name !== s.title ? `Recorded title: ${s.title}` : (s.name || s.title || s.session_id)}>{s.name || s.title || s.session_id}</span>
                <span className="sess-meta">{String(s.first_ts || '').slice(11, 16)}&ndash;{String(s.last_ts || '').slice(11, 16)} &middot; {fmtInt(s.acts)}</span>
              </div>
            ))}
            {!sessions.length && <div className="detail-none small">No sessions.</div>}
          </div>
        </div>
      </div>

      <div className="detail-card" style={{ marginTop: 14 }}>
        <div className="detail-card-title">Acts ({fmtInt(total)}{total > events.length ? `, the first ${fmtInt(events.length)} shown` : ''})</div>
        <div className="evt-table">
          <div className="evt-row ai-row evt-head"><span>Time</span><span>Act</span><span>Agent</span><span>Program</span><span>What</span><span>Exit</span></div>
          {events.map((e, i) => (
            <div className="evt-row ai-row" key={i} onClick={() => onOpenSession(e.session)} title="Open the session">
              <span className="evt-t">{String(e.t).slice(11, 19)}</span>
              <span><span className="cat-dot" style={{ background: SERIES_COLOR[e.series] }} title={e.series} /></span>
              <span className="evt-file">{e.agent}</span>
              <span className="evt-file">{e.program ? <a className="link" onClick={(ev) => { ev.stopPropagation(); onOpenProgram(e.program.split(',')[0].trim()) }}>{e.program}</a> : ''}</span>
              <span className="evt-path" title={e.what}>{e.what}</span>
              <span className={'evt-size' + (e.exit ? ' bad' : '')}>{e.exit === null || e.exit === undefined ? '' : e.exit}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
