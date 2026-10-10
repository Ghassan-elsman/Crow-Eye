import React from 'react'
import FullRecordSection from './FullRecordSection.jsx'
import { Chart, Radar } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController,
  LineElement, LineController, PointElement, RadarController, RadialLinearScale,
  Filler, Tooltip, Legend,
} from 'chart.js'
import { fmtBytes, fmtInt, fmtCompact, fmtDuration, fmtDay } from './format.js'
import { IconSearch } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, LineElement,
  LineController, PointElement, RadarController, RadialLinearScale, Filler, Tooltip, Legend)

const hourLabel = (h) => (h || '').slice(11, 16) || (h || '').slice(5, 10)

export default function AppDetailPanel({ app, detail, loading, onClose }) {
  if (!app) {
    return (
      <div className="detail empty">
        <div className="detail-empty-inner">
          <div className="detail-empty-icon"><IconSearch size={44} /></div>
          Click an application in the timeline to see its full profile &mdash;
          data sent/received over time, resource use, battery, and which users ran it.
        </div>
      </div>
    )
  }

  const hourlyRaw = detail?.hourly || []
  const totals = detail?.totals || {}
  const byUser = detail?.byUser || []
  const radar = detail?.radar || {}

  // Collapse multiple users in the same time bucket into one row per time, so a
  // time is never represented twice (the per-user split lives in "Who ran it").
  const hourly = React.useMemo(() => {
    const m = new Map()
    for (const h of hourlyRaw) {
      const g = m.get(h.hour) || { hour: h.hour, bytesSent: 0, bytesReceived: 0, cpu: 0, disk: 0, focusS: 0, keyboardS: 0, battery: 0, _bn: 0 }
      g.bytesSent += h.bytesSent || 0; g.bytesReceived += h.bytesReceived || 0
      g.cpu += h.cpu || 0; g.disk += h.disk || 0; g.focusS += h.focusS || 0; g.keyboardS += h.keyboardS || 0
      if (h.battery) { g.battery += h.battery; g._bn += 1 }
      m.set(h.hour, g)
    }
    return [...m.values()].map(g => ({ ...g, battery: g._bn ? Math.round(g.battery / g._bn) : 0 }))
      .sort((a, b) => (a.hour < b.hour ? -1 : 1))
  }, [hourlyRaw])

  const labels = hourly.map(h => hourLabel(h.hour))

  const comboData = {
    labels,
    datasets: [
      { type: 'bar', label: 'Sent', data: hourly.map(h => h.bytesSent), backgroundColor: '#4aa8ff', yAxisID: 'y', stack: 'net', borderRadius: 2 },
      { type: 'bar', label: 'Received', data: hourly.map(h => h.bytesReceived), backgroundColor: '#2a6bb0', yAxisID: 'y', stack: 'net', borderRadius: 2 },
      { type: 'line', label: 'CPU', data: hourly.map(h => h.cpu), borderColor: '#39d353', backgroundColor: '#39d353', yAxisID: 'y1', pointRadius: 0, borderWidth: 2, tension: 0.3, pointStyle: 'circle' },
      { type: 'line', label: 'Battery %', data: hourly.map(h => h.battery), borderColor: '#a78bfa', backgroundColor: '#a78bfa', yAxisID: 'y2', pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3], pointStyle: 'circle' },
    ],
  }
  const comboOpts = {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { labels: { color: '#cbd5e1', usePointStyle: true, pointStyleWidth: 12, boxHeight: 8, font: { size: 12 } } },
      tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.dataset.label.startsWith('Battery') ? c.parsed.y + '%' : c.dataset.label === 'CPU' ? fmtInt(c.parsed.y) : fmtBytes(c.parsed.y)}` } } },
    scales: {
      x: { ticks: { color: '#94a3b8', font: { size: 12 }, maxRotation: 0, autoSkip: true }, grid: { display: false } },
      y: { position: 'left', ticks: { color: '#94a3b8', font: { size: 12 }, callback: (v) => fmtBytes(v) }, grid: { color: 'rgba(99,102,241,0.10)' } },
      y1: { position: 'right', display: false },
      y2: { position: 'right', min: 0, max: 100, display: false },
    },
  }

  const radarData = {
    labels: ['CPU', 'Disk', 'Net out', 'Net in', 'Presence'],
    datasets: [{ label: '% of all activity', data: [radar.cpu, radar.disk, radar.netOut, radar.netIn, radar.presence],
      backgroundColor: 'rgba(74,168,255,0.22)', borderColor: '#4aa8ff', borderWidth: 2, pointBackgroundColor: '#4aa8ff' }],
  }
  const radarOpts = {
    responsive: true, maintainAspectRatio: true, aspectRatio: 1,
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.label}: ${c.parsed.r}% of all apps` } } },
    scales: { r: { min: 0, suggestedMax: Math.max(10, radar.cpu, radar.disk, radar.netOut, radar.netIn, radar.presence),
      angleLines: { color: 'rgba(99,102,241,0.14)' }, grid: { color: 'rgba(99,102,241,0.14)' },
      pointLabels: { color: '#cbd5e1', font: { size: 12 } }, ticks: { display: false } } },
  }

  const userData = {
    labels: byUser.map(u => u.user),
    datasets: [{ label: 'Activity (hours)', data: byUser.map(u => u.hours), backgroundColor: '#39d353', borderRadius: 2 }],
  }
  const userOpts = {
    indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false } },
    scales: { x: { ticks: { color: '#94a3b8', font: { size: 12 } }, grid: { color: 'rgba(99,102,241,0.10)' } },
      y: { ticks: { color: '#cbd5e1', font: { size: 12 } }, grid: { display: false } } },
  }

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{app}</div>
          <div className="detail-sub">
            {totals.first ? `${fmtDay(totals.first)} → ${fmtDay(totals.last)} · ${fmtInt(totals.hours)} active hours` : ''}
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      {loading && <div className="detail-loading">Loading&hellip;</div>}

      <div className="detail-body">
        <div className="totals-strip">
          <div className="tot"><span>{fmtBytes(totals.bytesSent)}</span><label>sent</label></div>
          <div className="tot"><span>{fmtBytes(totals.bytesReceived)}</span><label>received</label></div>
          <div className="tot" title={fmtInt(totals.cpu)}><span>{fmtCompact(totals.cpu)}</span><label>CPU cycles</label></div>
          <div className="tot"><span>{fmtDuration(totals.focusS)}</span><label>in focus</label></div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Data &amp; resources over time</div>
          <div className="chart-box tall"><Chart type="bar" data={comboData} options={comboOpts} /></div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Network by time</div>
          {(() => {
            const net = hourly.filter(h => (h.bytesSent || 0) + (h.bytesReceived || 0) > 0)
            return net.length ? (
              <div className="net-times">
                {net.map((h, i) => (
                  <div className="net-time" key={i}>
                    <span className="net-time-t">{hourLabel(h.hour)}</span>
                    <span className="net-time-v" style={{ color: '#4aa8ff' }}>&#9650; {fmtBytes(h.bytesSent)}</span>
                    <span className="net-time-v" style={{ color: '#7fb3e6' }}>&#9660; {fmtBytes(h.bytesReceived)}</span>
                  </div>
                ))}
              </div>
            ) : <div className="detail-none small">No network activity recorded.</div>
          })()}
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Resource footprint (share of all apps)</div>
          <div className="chart-box square"><Radar data={radarData} options={radarOpts} /></div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Who ran it ({byUser.length} user{byUser.length === 1 ? '' : 's'})</div>
          <div className="chart-box" style={{ height: Math.max(80, byUser.length * 34) }}>
            {byUser.length ? <Chart type="bar" data={userData} options={userOpts} />
              : <div className="detail-none">No user records.</div>}
          </div>
        </div>
        <FullRecordSection records={detail?.records} />
      </div>
    </div>
  )
}
