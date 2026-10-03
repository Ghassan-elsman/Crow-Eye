import React, { useState } from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { fmtDay, fmtInt, fmtDuration, PROVIDERS } from './format.js'
import ActivityTimeline from './ActivityTimeline.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'
import { ProviderLegend } from './OverviewPanel.jsx'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

/**
 * The selected period, in full.
 *
 * The app modal used to be mounted here, which made it unreachable from an
 * insight: this section returns early when no day is selected, so opening a
 * record with nothing selected set the state and rendered nothing. It lives in
 * `App` now. The hour panel stays, because an hour can only be clicked from a
 * chart this section drew - see docs/building-a-visualization.md.
 */
export default function DayActivitySection({
  day, activity, companion, loading, selectedApp, onSelectApp,
}) {
  const [hourDetail, setHourDetail] = useState(null)

  if (!day) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a cell in the heat-maps to see everything that ran in that period &mdash;
          which apps, in which hours, and the resources and network they used.
        </div>
      </section>
    )
  }

  const hbp = companion?.hourlyByProvider || {}
  const topByProv = companion?.topAppsByProvider || []
  const perProvider = companion?.perProvider || {}
  const presence = companion?.presence || {}

  // Activity by hour: stacked bars, one dataset per provider.
  const hourData = {
    labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    datasets: PROVIDERS.map(p => ({ label: p.label, backgroundColor: p.color, borderWidth: 0,
      data: (hbp[p.key] || Array(24).fill(0)) })),
  }
  const hourOpts = {
    responsive: true, maintainAspectRatio: false, animation: false,
    onClick: (_e, els) => { if (els[0]) setHourDetail(els[0].index) },
    onHover: (e, els) => { if (e?.native?.target) e.native.target.style.cursor = els[0] ? 'pointer' : 'default' },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
    scales: {
      x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 12 }, maxRotation: 0, autoSkip: true }, grid: { display: false } },
      y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 12 } }, grid: { color: 'rgba(99,102,241,0.10)' }, beginAtZero: true },
    },
  }

  // Top apps: horizontal stacked bars, one dataset per provider.
  const topData = {
    labels: topByProv.map(a => a.app),
    datasets: PROVIDERS.map(p => ({ label: p.label, backgroundColor: p.color, borderWidth: 0,
      data: topByProv.map(a => (a.counts && a.counts[p.key]) || 0) })),
  }
  const topOpts = {
    indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.x)}` } } },
    scales: {
      x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 12 } }, grid: { color: 'rgba(99,102,241,0.10)' } },
      y: { stacked: true, ticks: { color: '#cbd5e1', font: { size: 12 } }, grid: { display: false } },
    },
  }

  const provTotal = Object.values(perProvider).reduce((a, b) => a + b, 0) || 1

  return (
    <section className="day-section">
      <div className="day-head">
        <div>
          <div className="day-title">Activity on {fmtDay(day)}</div>
          <div className="day-sub">
            All applications that ran this day, by hour &mdash; click an app for its full profile.
          </div>
        </div>
        <ProviderLegend />
      </div>

      {loading && <div className="loading-inline"><span className="spinner" />Loading day…</div>}

      <div className="day-timeline">
        {activity && activity.points?.length
          ? <ActivityTimeline data={activity} onSelectApp={onSelectApp} selectedApp={selectedApp} />
          : <div className="detail-none">No application activity recorded on this day.</div>}
      </div>

      <div className="day-companions">
        <div className="detail-card">
          <div className="detail-card-title">Activity by hour (by provider)</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
          <div className="ov-hint">Click an hour to see its detailed activity.</div>
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Top applications (by provider)</div>
          <div className="chart-box tall">
            {topByProv.length ? <Chart type="bar" data={topData} options={topOpts} />
              : <div className="detail-none small">No apps.</div>}
          </div>
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Records by provider</div>
          <div className="prov-bar">
            {PROVIDERS.map(p => {
              const v = perProvider[p.key] || 0
              return v > 0 ? <span key={p.key} className="prov-seg" title={`${p.label}: ${fmtInt(v)}`}
                style={{ background: p.color, flexGrow: v }} /> : null
            })}
          </div>
          <div className="prov-list tight">
            {PROVIDERS.map(p => (
              <div className="prov-row" key={p.key}>
                <span className="prov-name"><span className="prov-swatch" style={{ background: p.color }} />{p.label}</span>
                <span className="prov-count">{fmtInt(perProvider[p.key] || 0)}</span>
              </div>
            ))}
          </div>
          <div className="detail-card-title" style={{ marginTop: 12 }}>User presence</div>
          <div className="pres-grid">
            <div className="pres-cell"><span>{fmtDuration(presence.keyboard)}</span><label>keyboard</label></div>
            <div className="pres-cell"><span>{fmtDuration(presence.mouse)}</span><label>mouse</label></div>
            <div className="pres-cell"><span>{fmtDuration(presence.focus)}</span><label>in focus</label></div>
          </div>
        </div>
      </div>

      {hourDetail != null && (
        <div className="modal-overlay" onClick={() => setHourDetail(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <HourDetailPanel hour={hourDetail} day={day} activity={activity} companion={companion}
              onClose={() => setHourDetail(null)} />
          </div>
        </div>
      )}
    </section>
  )
}
