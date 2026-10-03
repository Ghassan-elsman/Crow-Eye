import React, { useMemo } from 'react'
import { Bar } from 'react-chartjs-2'
import {
  Chart as ChartJS, BarElement, CategoryScale, LinearScale, Tooltip, Legend,
} from 'chart.js'
import BrowserActivityTimeline from './BrowserActivityTimeline.jsx'
import { ACTIVITIES, ACTIVITY_COLOR, ACTIVITY_LABEL, fmtDay, fmtInt } from './format.js'

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip, Legend)

const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}`)

const stackedOpts = (indexAxis) => ({
  responsive: true, maintainAspectRatio: false, animation: false,
  indexAxis,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { footer: (its) => `Total ${fmtInt(its.reduce((s, i) => s + (i.raw || 0), 0))}` } },
  },
  scales: {
    x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 10 } },
      grid: { color: 'rgba(99,102,241,0.08)' } },
    y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 10 } },
      grid: { color: 'rgba(99,102,241,0.08)' } },
  },
})

export default function DaySection({ day, detail, activity, onPickDomain, onPickHour }) {
  const hourData = useMemo(() => ({
    labels: HOURS,
    datasets: ACTIVITIES.map(a => ({
      label: a.label,
      data: (detail?.hourlyBySource || {})[a.key] || Array(24).fill(0),
      backgroundColor: a.color,
      borderWidth: 0,
    })).filter(d => d.data.some(v => v > 0)),
  }), [detail])

  // The hour bars are the entry to the hour drill-down; the Chart.js click
  // handler reports the category index, which here IS the hour.
  const hourOpts = useMemo(() => {
    const base = stackedOpts('x')
    return {
      ...base,
      onClick: (_evt, els) => {
        if (onPickHour && els && els.length) onPickHour(els[0].index)
      },
      onHover: (evt, els) => {
        const c = evt?.native?.target
        if (c) c.style.cursor = (onPickHour && els && els.length) ? 'pointer' : 'default'
      },
    }
  }, [onPickHour])

  const topDomains = detail?.topDomains || []
  const domainData = useMemo(() => ({
    labels: topDomains.map(d => d.domain),
    datasets: ACTIVITIES.map(a => ({
      label: a.label,
      data: topDomains.map(d => (d.counts || {})[a.key] || 0),
      backgroundColor: a.color,
      borderWidth: 0,
    })).filter(d => d.data.some(v => v > 0)),
  }), [topDomains])

  if (!day) {
    return <div className="day-empty">Select a day above to explore it.</div>
  }

  const per = detail?.perSource || {}
  const total = Object.values(per).reduce((s, v) => s + v, 0)
  const events = detail?.events || []
  const eventsTotal = detail?.eventsTotal || events.length

  return (
    <div className="day-root">
      <div className="day-head">
        <h3>{fmtDay(day)}</h3>
        <div className="day-sub">{fmtInt(total)} events</div>
      </div>

      {/* proportion strip: the day's activity mix at a glance */}
      <div className="day-strip">
        {ACTIVITIES.filter(a => (per[a.key] || 0) > 0).map(a => (
          <div key={a.key} className="day-strip-seg"
            style={{ flexGrow: per[a.key], background: ACTIVITY_COLOR[a.key] }}
            title={`${ACTIVITY_LABEL[a.key]}: ${fmtInt(per[a.key])}`} />
        ))}
      </div>

      <div className="day-grid">
        <div className="day-chart">
          <div className="day-chart-h">By hour <span className="day-chart-hint">click an hour to open it</span></div>
          <div className="chart-box" style={{ height: 210 }}>
            <Bar data={hourData} options={hourOpts} />
          </div>
        </div>
        <div className="day-chart">
          <div className="day-chart-h">Top domains</div>
          <div className="chart-box" style={{ height: 210 }}>
            <Bar data={domainData} options={stackedOpts('y')} />
          </div>
        </div>
      </div>

      <div className="day-chart-h">Domain &times; hour</div>
      <BrowserActivityTimeline data={activity} />

      {topDomains.length ? (
        <div className="day-list">
          <div className="day-chart-h">Domains on this day</div>
          {topDomains.map(d => (
            <div className="evt-row br-row" key={d.domain} onClick={() => onPickDomain(d.domain)}>
              <span className="evt-name">{d.domain}</span>
              <span className="evt-counts">
                {ACTIVITIES.filter(a => (d.counts || {})[a.key]).map(a => (
                  <span key={a.key} className="evt-chip" style={{ borderColor: a.color, color: a.color }}>
                    {ACTIVITY_LABEL[a.key]} {fmtInt(d.counts[a.key])}
                  </span>
                ))}
              </span>
              <span className="evt-total">{fmtInt(d.total)}</span>
            </div>
          ))}
        </div>
      ) : null}

      {events.length ? (
        <div className="day-list">
          <div className="day-chart-h">
            Events on this day
            <span className="day-chart-hint">
              {events.length < eventsTotal
                ? `first ${fmtInt(events.length)} of ${fmtInt(eventsTotal)}, oldest first`
                : `${fmtInt(events.length)} rows, oldest first`}
            </span>
          </div>
          <div className="evt-scroll">
            <div className="evt-row brev-row evt-head">
              <span>Time</span><span>Activity</span><span>Site</span><span>What</span><span>Browser</span>
            </div>
            {events.map((e, i) => (
              <div className="evt-row brev-row" key={`${e.t}-${i}`}
                onClick={() => e.domain && onPickDomain(e.domain)}>
                <span className="evt-t">{e.time}</span>
                <span>
                  <span className="evt-chip"
                    style={{ borderColor: ACTIVITY_COLOR[e.activity], color: ACTIVITY_COLOR[e.activity] }}>
                    {ACTIVITY_LABEL[e.activity]}
                  </span>
                </span>
                <span className="evt-file" title={e.url}>{e.domain || '—'}</span>
                <span className="evt-path" title={e.label || e.url}>{e.label || e.url}</span>
                <span className="evt-browser">{e.browser}{e.profile ? ` · ${e.profile}` : ''}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
